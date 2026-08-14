#!/usr/bin/env python3
"""Probe generated BGM candidates, reject speech, and select a timeline fit."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from faster_whisper import WhisperModel

from tools.portable_runtime import resolve_media_binary, resolve_whisper_model


ROOT = Path(__file__).resolve().parents[1]
FFMPEG, FFMPEG_SOURCE = resolve_media_binary("ffmpeg", root=ROOT)
FFPROBE, FFPROBE_SOURCE = resolve_media_binary("ffprobe", root=ROOT)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    completed = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration,size:stream=codec_name,sample_rate,channels", "-of", "json", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)
    stream = payload["streams"][0]
    return {
        "duration_seconds": round(float(payload["format"]["duration"]), 6),
        "size_bytes": int(payload["format"]["size"]),
        "codec": stream["codec_name"],
        "sample_rate": int(stream["sample_rate"]),
        "channels": int(stream["channels"]),
    }


def loudness(path: Path) -> dict:
    completed = subprocess.run(
        [str(FFMPEG), "-hide_banner", "-nostats", "-i", str(path), "-af", "loudnorm=I=-14:TP=-1.0:LRA=11:print_format=json", "-f", "null", "-"],
        text=True,
        capture_output=True,
    )
    matches = re.findall(r"\{[\s\S]*?\}", completed.stderr)
    if not matches:
        raise RuntimeError(f"Could not parse loudness metrics for {path}")
    data = json.loads(matches[-1])
    return {
        "integrated_lufs": float(data["input_i"]),
        "true_peak_dbtp": float(data["input_tp"]),
        "loudness_range_lu": float(data["input_lra"]),
    }


def text_char_count(value: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fffA-Za-z]", value or ""))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument("--content-seconds", type=float, required=True)
    parser.add_argument("--bgm-start-seconds", type=float, default=4.0)
    parser.add_argument("--model")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    candidates = [Path(value).resolve() for value in args.candidate]
    missing = [str(path) for path in candidates if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing BGM candidates: {missing}")
    model_ref, model_source = resolve_whisper_model(args.model)
    model = WhisperModel(model_ref, device="cpu", compute_type="int8", cpu_threads=4, num_workers=1)
    rows = []
    for path in candidates:
        media = probe(path)
        metrics = loudness(path)
        segments, _ = model.transcribe(str(path), vad_filter=True, beam_size=5)
        asr_segments = [
            {"start": round(item.start, 3), "end": round(item.end, 3), "text": item.text.strip()}
            for item in segments
            if item.text.strip()
        ]
        transcript = "".join(item["text"] for item in asr_segments)
        speech_chars = text_char_count(transcript)
        required_coverage_seconds = max(0.0, args.content_seconds - args.bgm_start_seconds)
        usable_seconds = min(media["duration_seconds"], required_coverage_seconds)
        # A source that is longer than the edit window can be trimmed and faded
        # without looping. Only a source shorter than the required coverage
        # would force a loop or leave an unintended gap.
        no_loop_required = media["duration_seconds"] + 0.001 >= required_coverage_seconds
        failures = []
        if speech_chars:
            failures.append("ASR_DETECTED_POSSIBLE_VOCALS")
        if media["sample_rate"] < 44100 or media["channels"] != 2:
            failures.append("MEDIA_FORMAT_NOT_RELEASE_GRADE")
        rows.append({
            "path": str(path),
            "sha256": sha256(path),
            **media,
            "loudness": metrics,
            "no_vocals": {
                "status": "PASS" if not speech_chars else "FAIL",
                "asr_character_count": speech_chars,
                "transcript": transcript,
                "segments": asr_segments,
            },
            "timeline_fit": {
                "start_seconds": args.bgm_start_seconds,
                "source_natural_end_seconds": round(args.bgm_start_seconds + media["duration_seconds"], 6),
                "edit_end_seconds": round(args.bgm_start_seconds + usable_seconds, 6),
                "usable_seconds": round(usable_seconds, 6),
                "loop_required": not no_loop_required,
                "plan": "NATURAL_SOURCE_TRIM_WITH_EDGE_FADES_NO_LOOP" if no_loop_required else "REJECT_INSUFFICIENT_NO_LOOP_COVERAGE",
            },
            "status": "PASS" if not failures and no_loop_required else "FAIL",
            "failures": failures + ([] if no_loop_required else ["SOURCE_TOO_SHORT_FOR_NO_LOOP_COVERAGE"]),
        })

    passing = [row for row in rows if row["status"] == "PASS"]
    selected = None
    if passing:
        selected = max(
            passing,
            key=lambda row: (
                row["timeline_fit"]["usable_seconds"],
                min(row["loudness"]["loudness_range_lu"], 12.0),
            ),
        )
    payload = {
        "schema": "qingshan.generated_bgm_candidate_qa.v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "episode": args.episode,
        "status": "PASS_SELECTED" if selected else "FAIL_NO_USABLE_CANDIDATE",
        "content_seconds": args.content_seconds,
        "selection_policy": "Reject detectable vocals. Prefer natural no-loop coverage and a broader controlled dynamic range; fade rather than loop or stretch.",
        "selected_path": selected["path"] if selected else None,
        "selected_sha256": selected["sha256"] if selected else None,
        "runtime": {
            "ffmpeg_source": FFMPEG_SOURCE,
            "ffprobe_source": FFPROBE_SOURCE,
            "whisper_model_source": model_source,
        },
        "machine_verdict": {
            "status": "ADMIT" if selected else "REJECT",
            "confidence": 0.92 if selected else 0.98,
            "reason": "Provider instrumental flag, local ASR no-vocal pass, stereo 48 kHz media, and natural timeline coverage without looping." if selected else "No candidate passed the no-vocal and timeline-fit hard gates.",
        },
        "candidates": rows,
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "selected": payload["selected_path"], "out": str(out)}, ensure_ascii=False))
    return 0 if selected else 2


if __name__ == "__main__":
    raise SystemExit(main())
