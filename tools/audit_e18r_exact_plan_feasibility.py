#!/usr/bin/env python3
"""Measure whether E18R can reach its beat/runtime targets without source reuse."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import wave
from array import array
from pathlib import Path


BASE = Path(__file__).resolve().parents[1]


def load_json(path: str) -> dict:
    return json.loads((BASE / path).read_text(encoding="utf-8"))


def media_duration(path: Path, ffmpeg: str) -> float:
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in proc.stderr.splitlines():
        if "Duration:" not in line:
            continue
        value = line.split("Duration:", 1)[1].split(",", 1)[0].strip()
        hours, minutes, seconds = value.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    raise RuntimeError(f"Unable to probe duration: {path}")


def active_audio_bounds(path: Path, threshold_db: float, pad_sec: float) -> dict:
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        sample_rate = handle.getframerate()
        frame_count = handle.getnframes()
        raw = handle.readframes(frame_count)

    if sample_width != 2:
        raise RuntimeError(f"Expected 16-bit PCM WAV: {path}")
    samples = array("h")
    samples.frombytes(raw)
    if channels > 1:
        mono = array("h", (samples[index] for index in range(0, len(samples), channels)))
    else:
        mono = samples

    window = max(1, round(sample_rate * 0.02))
    threshold = 32767 * (10 ** (threshold_db / 20.0))
    active_windows: list[int] = []
    for start in range(0, len(mono), window):
        chunk = mono[start : start + window]
        if not chunk:
            continue
        rms = math.sqrt(sum(value * value for value in chunk) / len(chunk))
        if rms >= threshold:
            active_windows.append(start)

    source_seconds = len(mono) / sample_rate
    if not active_windows:
        return {
            "source_seconds": round(source_seconds, 3),
            "active_start_seconds": None,
            "active_end_seconds": None,
            "minimum_complete_seconds": 0.0,
            "active_detected": False,
        }

    start_sec = max(0.0, active_windows[0] / sample_rate - pad_sec)
    end_sec = min(source_seconds, (active_windows[-1] + window) / sample_rate + pad_sec)
    return {
        "source_seconds": round(source_seconds, 3),
        "active_start_seconds": round(start_sec, 3),
        "active_end_seconds": round(end_sec, 3),
        "minimum_complete_seconds": round(end_sec - start_sec, 3),
        "active_detected": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--b05-plan", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--threshold-db", type=float, default=-40.0)
    parser.add_argument("--audio-pad-sec", type=float, default=0.12)
    args = parser.parse_args()

    coverage = load_json(args.coverage)
    inventory = load_json(args.inventory)
    b05_plan = load_json(args.b05_plan)
    rows_by_beat: dict[str, list[dict]] = {}
    failures: list[str] = []

    for item in inventory["items"]:
        picture = BASE / item["picture"]
        audio = BASE / item["audio"]
        try:
            picture_seconds = media_duration(picture, args.ffmpeg)
            audio_bounds = active_audio_bounds(audio, args.threshold_db, args.audio_pad_sec)
        except Exception as exc:
            failures.append(f"{item['dialogue_id']}: {exc}")
            continue
        rows_by_beat.setdefault(item["beat_id"], []).append(
            {
                "dialogue_id": item["dialogue_id"],
                "picture_seconds": round(picture_seconds, 3),
                "audio": audio_bounds,
            }
        )

    beat_reports: list[dict] = []
    unique_picture_seconds = 0.0
    minimum_complete_audio_seconds = 0.0
    for beat in coverage["beats"]:
        beat_id = beat["beat_id"]
        rows = rows_by_beat.get(beat_id, [])
        picture_seconds = sum(row["picture_seconds"] for row in rows)
        audio_minimum = sum(row["audio"]["minimum_complete_seconds"] for row in rows)
        if beat_id == "B05":
            admitted_picture_seconds = float(b05_plan["target_runtime_sec"])
            picture_basis = "accepted_b05_r6_exact_plan"
        else:
            admitted_picture_seconds = picture_seconds
            picture_basis = "unique_ordered_picture_sources"
        target = float(beat["target_seconds"])
        beat_reports.append(
            {
                "beat_id": beat_id,
                "dialogue_count": len(rows),
                "target_seconds": target,
                "unique_picture_source_seconds": round(picture_seconds, 3),
                "admitted_picture_plan_seconds": round(admitted_picture_seconds, 3),
                "picture_basis": picture_basis,
                "minimum_complete_dialogue_audio_seconds": round(audio_minimum, 3),
                "target_minus_admitted_picture_seconds": round(target - admitted_picture_seconds, 3),
                "target_can_hold_complete_dialogue": target + 0.05 >= audio_minimum,
                "requires_additional_dynamic_picture_for_exact_target": target > admitted_picture_seconds + 0.05,
                "lines": rows,
            }
        )
        unique_picture_seconds += admitted_picture_seconds
        minimum_complete_audio_seconds += audio_minimum

    runtime = coverage["runtime_target_seconds"]
    target_seconds = float(runtime["target"])
    minimum_seconds = float(runtime["min"])
    dialogue_count = int(coverage["dialogue_count"])
    report = {
        "schema": "qingshan.e18r.exact_plan_feasibility_audit.v1",
        "episode": "E18R",
        "status": "FAIL_PROBE" if failures else "PASS_TO_NATIVE_RANGE_PLAN_REQUIRES_DYNAMIC_COVERAGE_FOR_178_TARGET",
        "inputs": {
            "coverage": args.coverage,
            "inventory": args.inventory,
            "b05_plan": args.b05_plan,
        },
        "audio_activity_method": {
            "window_seconds": 0.02,
            "threshold_dbfs": args.threshold_db,
            "edge_padding_seconds": args.audio_pad_sec,
            "purpose": "planning estimate only; ASR and watch/listen remain required",
        },
        "beat_reports": beat_reports,
        "summary": {
            "dialogue_count": dialogue_count,
            "target_runtime_seconds": target_seconds,
            "allowed_runtime_min_seconds": minimum_seconds,
            "allowed_runtime_max_seconds": float(runtime["max"]),
            "admitted_unique_picture_plan_seconds": round(unique_picture_seconds, 3),
            "minimum_complete_dialogue_audio_seconds": round(minimum_complete_audio_seconds, 3),
            "dynamic_picture_gap_to_178_seconds": round(max(0.0, target_seconds - unique_picture_seconds), 3),
            "native_picture_plan_is_within_allowed_runtime_range": minimum_seconds <= unique_picture_seconds <= float(runtime["max"]),
            "whole_line_density_at_target_per_minute": round(dialogue_count / target_seconds * 60, 3),
            "whole_line_density_at_min_runtime_per_minute": round(dialogue_count / minimum_seconds * 60, 3),
            "density_note": "The >=15 rule must use measured ASR segments, not whole dialogue-line count; whole-line arithmetic alone cannot reach 15/min at runtime >=165s.",
        },
        "failures": failures,
        "confidence": "HIGH_FOR_CONTAINER_DURATION_AND_ARITHMETIC_MEDIUM_FOR_AUDIO_ACTIVITY_BOUNDS",
        "decision": "Compile a native-cadence plan inside 165-185s first. Reach 178s only with separately admitted real dynamic bridge/insert footage; no loops, freezes, or post-speed changes.",
        "rollback": "Discard this planning audit only; preserve the ordered inventory and all source QA.",
        "final_lock": False,
        "package_allowed": False,
        "platform_mutation_allowed": False,
    }
    output = BASE / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(output), "summary": report["summary"]}, ensure_ascii=False))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
