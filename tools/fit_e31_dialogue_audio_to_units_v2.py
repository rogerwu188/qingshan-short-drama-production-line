#!/usr/bin/env python3
"""Fit E31 exact dialogue references inside each video unit without dropping words."""

from __future__ import annotations

import hashlib
import json
import subprocess
import wave
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "workflow/claude_writer_agent/production/e31_claude_writer_v1_20260722/E31_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json"
SOURCE = ROOT / "working_assets/e31_dialogue_audio_refs_20260722/E31_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1.json"
OUT_DIR = ROOT / "working_assets/e31_dialogue_audio_refs_20260722/fitted_v2"
OUT_MANIFEST = ROOT / "working_assets/e31_dialogue_audio_refs_20260722/E31_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
GATE = ROOT / "qa/e31_dialogue_audio_20260722/E31_DIALOGUE_AUDIO_TIMELINE_GATE_V2.json"
FFMPEG = ROOT / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


def atempo_chain(speed: float) -> str:
    parts = []
    remaining = speed
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining:.8f}")
    return ",".join(parts)


def fitted_targets(source_rows: list[dict], available: float) -> list[float]:
    """Proportionally fit lines while honoring Seedance's 2-second audio minimum."""
    sources = [float(row["duration_seconds"]) for row in source_rows]
    targets = [0.0] * len(sources)
    open_indexes = set(range(len(sources)))
    remaining = available
    while open_indexes:
        source_total = sum(sources[index] for index in open_indexes)
        changed = False
        for index in list(open_indexes):
            proposal = remaining * sources[index] / source_total
            if proposal < 2.15:
                targets[index] = 2.15
                remaining -= 2.15
                open_indexes.remove(index)
                changed = True
        if not changed:
            for index in open_indexes:
                targets[index] = remaining * sources[index] / source_total
            break
    if remaining < 0 or any(target < 2.15 for target in targets):
        raise SystemExit("dialogue unit cannot satisfy Seedance 2-second per-audio minimum")
    return targets


def main() -> int:
    if not FFMPEG.is_file():
        raise SystemExit(f"missing bundled ffmpeg: {FFMPEG}")
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    durations = {row["unit_id"]: float(row["duration_seconds"]) for row in plan["units"]}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in source["rows"]:
        grouped[row["video_unit_id"]].append(row)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    unit_reports = []
    failures = []
    for unit_id, source_rows in sorted(grouped.items()):
        unit_duration = durations[unit_id]
        gap_total = 0.16 * max(0, len(source_rows) - 1)
        action_reserve = max(0.45, min(1.2, unit_duration * 0.09))
        available = unit_duration - gap_total - action_reserve
        source_total = sum(float(row["duration_seconds"]) for row in source_rows)
        targets = fitted_targets(source_rows, available)
        tempo_factors = [float(row["duration_seconds"]) / target for row, target in zip(source_rows, targets)]
        fitted_total = 0.0
        for row, target, speed in zip(source_rows, targets, tempo_factors):
            source_path = ROOT / row["path"]
            output_path = OUT_DIR / source_path.name
            command = [
                str(FFMPEG), "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(source_path), "-filter:a", atempo_chain(speed),
                "-ar", "48000", "-ac", "1", "-c:a", "pcm_s16le", str(output_path),
            ]
            subprocess.run(command, check=True)
            with wave.open(str(output_path), "rb") as wav:
                fitted_duration = wav.getnframes() / wav.getframerate()
            fitted_total += fitted_duration
            rows.append({
                **row,
                "path": relative(output_path),
                "sha256": sha256(output_path),
                "duration_seconds": round(fitted_duration, 3),
                "source_path": row["path"],
                "source_sha256": row["sha256"],
                "tempo_factor": round(speed, 6),
                "fit_policy": "PRESERVE_EVERY_WORD_AND_PITCH_FIT_INSIDE_VIDEO_UNIT",
                "status": "PASS" if speed <= 1.7 else "CONDITIONAL_MACHINE_ADMISSION",
                "conditional_reason": None if speed <= 1.7 else "Exact dialogue requires accelerated delivery; retain source audio as rollback.",
            })
        occupied = fitted_total + gap_total
        status = "PASS" if occupied <= unit_duration - 0.05 else "FAIL"
        if status == "FAIL":
            failures.append({"unit_id": unit_id, "check": "dialogue_fits", "occupied": occupied, "unit_duration": unit_duration})
        unit_reports.append({
            "unit_id": unit_id,
            "unit_duration_seconds": unit_duration,
            "dialogue_line_count": len(source_rows),
            "source_dialogue_seconds": round(source_total, 3),
            "fitted_dialogue_seconds": round(fitted_total, 3),
            "inter_line_gap_seconds": round(gap_total, 3),
            "action_reserve_seconds": round(unit_duration - occupied, 3),
            "tempo_factors": [round(value, 6) for value in tempo_factors],
            "status": status if max(tempo_factors) <= 1.7 else "CONDITIONAL_MACHINE_ADMISSION",
        })

    manifest = {
        "schema": "qingshan.dialogue_audio_reference_manifest.v2",
        "episode": "E31",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "dialogue_line_count": len(rows),
        "remote_call_count": 0,
        "remote_call_credit_known_total": 0,
        "remote_call_credit_unknown_count": 0,
        "credit_policy": "LOCAL_FFMPEG_TRANSFORM_ZERO_REMOTE_CREDIT",
        "rows": rows,
    }
    gate = {
        "schema": "qingshan.dialogue_audio_timeline_gate.v2",
        "episode": "E31",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": manifest["status"],
        "policy": "EVERY_SCRIPT_LINE_BOUND_EXACTLY_ONCE_AND_FITS_UNIT_WITH_ACTION_RESERVE",
        "required_dialogue_lines": len(source["rows"]),
        "bound_dialogue_lines": len(rows),
        "units": unit_reports,
        "failures": failures,
        "rollback": relative(SOURCE),
    }
    OUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    GATE.parent.mkdir(parents=True, exist_ok=True)
    GATE.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": gate["status"],
        "manifest": relative(OUT_MANIFEST),
        "gate": relative(GATE),
        "dialogue_lines": len(rows),
        "conditional_units": [row["unit_id"] for row in unit_reports if row["status"] == "CONDITIONAL_MACHINE_ADMISSION"],
    }, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
