#!/usr/bin/env python3
"""Verify every subtitle line against speech decoded from the final MP4."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tempfile
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel

from tools.portable_runtime import resolve_media_binary, resolve_whisper_model


ROOT = Path(__file__).resolve().parents[1]


def chinese(value: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", value))


def recall(expected: str, actual: str) -> float:
    expected, actual = chinese(expected), chinese(actual)
    if expected and expected in actual:
        return 1.0
    return sum(block.size for block in SequenceMatcher(None, expected, actual).get_matching_blocks()) / max(1, len(expected))


def dialogue_rows(contract: dict) -> list[dict]:
    """Accept both flat dialogue contracts and Claude Writer scene inventories."""
    if isinstance(contract.get("dialogue"), list):
        return contract["dialogue"]
    if isinstance(contract.get("rows"), list):
        return contract["rows"]
    if isinstance(contract.get("lines"), list):
        return contract["lines"]
    return [
        row
        for scene in contract.get("scenes", [])
        for beat in scene.get("beats", [])
        for row in beat.get("dialogue", [])
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--ffmpeg")
    parser.add_argument("--minimum-recall", type=float, default=0.55)
    args = parser.parse_args()

    project = json.loads(args.project.read_text(encoding="utf-8"))
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    rows = dialogue_rows(contract)
    expected = {row.get("dia_id") or row.get("dialogue_id"): row for row in rows}
    if None in expected:
        raise SystemExit("dialogue contract row is missing dia_id/dialogue_id")
    if not expected:
        raise SystemExit("dialogue contract contains no dialogue rows")
    captions = [clip for track in project["timeline"]["subtitleTracks"] for clip in track.get("clips", [])]
    if len(captions) != len(expected) or {row["dialogue_id"] for row in captions} != set(expected):
        raise SystemExit("subtitle and dialogue contracts do not have exact coverage")

    model_ref, model_source = resolve_whisper_model(args.model)
    ffmpeg, ffmpeg_source = resolve_media_binary(
        "ffmpeg", explicit=args.ffmpeg, root=ROOT
    )
    model = WhisperModel(model_ref, device="cpu", compute_type="int8")
    rows = []
    with tempfile.TemporaryDirectory(prefix="qingshan-final-asr-") as td:
        temp = Path(td)
        for caption in sorted(captions, key=lambda row: float(row["start"])):
            dia_id = caption["dialogue_id"]
            source = expected[dia_id]
            start = max(0.0, float(caption["start"]) - 0.30)
            duration = float(caption["duration"]) + 0.60
            wav = temp / f"{dia_id}.wav"
            subprocess.run([
                str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.6f}",
                "-i", str(args.video), "-t", f"{duration:.6f}", "-vn", "-ac", "1", "-ar", "16000", str(wav),
            ], check=True)
            text = source.get("spoken_text") or source.get("text") or ""
            segments, _ = model.transcribe(
                str(wav), language="zh", vad_filter=True, beam_size=5,
                initial_prompt=text,
            )
            transcript = "".join(segment.text.strip() for segment in segments)
            transcription_mode = "VAD_FILTERED"
            if not chinese(transcript):
                fallback, _ = model.transcribe(
                    str(wav), language="zh", vad_filter=False, beam_size=5,
                    initial_prompt=text,
                )
                transcript = "".join(segment.text.strip() for segment in fallback)
                transcription_mode = "VAD_DISABLED_SHORT_LINE_FALLBACK"
            score = recall(text, transcript)
            if score < args.minimum_recall:
                unprompted, _ = model.transcribe(
                    str(wav), language="zh", vad_filter=True, beam_size=5,
                )
                unprompted_transcript = "".join(segment.text.strip() for segment in unprompted)
                unprompted_score = recall(text, unprompted_transcript)
                if unprompted_score > score:
                    transcript = unprompted_transcript
                    score = unprompted_score
                    transcription_mode = "VAD_FILTERED_UNPROMPTED_HIGHER_RECALL_RETRY"
            speech = bool(chinese(transcript))
            rows.append({
                "dialogue_id": dia_id,
                "speaker": source.get("speaker"),
                "expected": text,
                "window_start": round(start, 3),
                "window_duration": round(duration, 3),
                "transcript": transcript,
                "transcription_mode": transcription_mode,
                "recall_score": round(score, 3),
                "speech_present": speech,
                "status": "PASS" if speech and score >= args.minimum_recall else "FAIL",
            })
    failures = [row["dialogue_id"] for row in rows if row["status"] != "PASS"]
    payload = {
        "schema": "qingshan.final_dialogue_window_asr.v1",
        "video": str(args.video.resolve()),
        "status": "PASS" if not failures else "FAIL",
        "policy": "Every subtitle line must be heard in the final encoded MP4 with Chinese speech and lexical recall at or above the configured threshold.",
        "minimum_recall": args.minimum_recall,
        "runtime": {
            "ffmpeg_source": ffmpeg_source,
            "whisper_model_source": model_source,
        },
        "line_count": len(rows),
        "pass_count": len(rows) - len(failures),
        "failures": failures,
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "pass_count": payload["pass_count"], "failures": failures}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
