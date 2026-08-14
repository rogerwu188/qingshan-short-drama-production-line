#!/usr/bin/env python3
"""Verify native Mandarin dialogue and audio presence in one harvested source clip."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

from tools.portable_runtime import resolve_media_binary, resolve_whisper_model


ROOT = Path(__file__).resolve().parents[1]


def chinese(value: str) -> str:
    normalized = value.translate(
        str.maketrans({"開": "开", "請": "请", "門": "门"})
    )
    return "".join(re.findall(r"[\u4e00-\u9fff]", normalized))


def recall(expected: str, actual: str) -> float:
    expected_text, actual_text = chinese(expected), chinese(actual)
    if not expected_text:
        return 1.0
    if expected_text in actual_text:
        return 1.0
    matched = sum(
        block.size
        for block in SequenceMatcher(
            None, expected_text, actual_text
        ).get_matching_blocks()
    )
    return matched / len(expected_text)


def transcription_prompt(expected: str) -> str:
    """Keep punctuation-only cues from turning into Whisper hallucinations."""
    return chinese(expected)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dialogue_rows(payload: object) -> list[dict]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("dialogue") or payload.get("rows") or payload.get("lines") or []
    else:
        rows = []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("dialogue rows must be an array of objects")
    return rows


def probe(video: Path, ffprobe: Path) -> dict:
    process = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(video),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(process.stdout)


def evaluate(
    video: Path,
    rows: list[dict],
    *,
    probe_payload: dict,
    transcript: str,
    segments: list[dict],
    minimum_recall: float,
    require_no_dialogue: bool = False,
) -> dict:
    failures: list[str] = []
    streams = probe_payload.get("streams") or []
    video_stream = any(row.get("codec_type") == "video" for row in streams)
    audio_stream = any(row.get("codec_type") == "audio" for row in streams)
    duration = float((probe_payload.get("format") or {}).get("duration") or 0)
    if not video_stream:
        failures.append("video_stream_missing")
    if not audio_stream:
        failures.append("audio_stream_missing")
    expected_ids = [
        str(row.get("dia_id") or row.get("dialogue_id") or "").strip()
        for row in rows
    ]
    expected_texts = [
        str(row.get("spoken_text") or row.get("text") or "").strip()
        for row in rows
    ]
    if rows and (any(not value for value in expected_ids) or len(set(expected_ids)) != len(expected_ids)):
        failures.append("dialogue_ids_missing_or_duplicate")
    if rows and any(not chinese(value) for value in expected_texts):
        failures.append("expected_mandarin_text_missing")
    expected = "".join(expected_texts)
    score = recall(expected, transcript)
    if rows and not chinese(transcript):
        failures.append("native_mandarin_speech_missing")
    elif rows and score < minimum_recall:
        failures.append(f"dialogue_recall_below_threshold:{score:.3f}")
    if require_no_dialogue and chinese(transcript):
        failures.append("unexpected_native_mandarin_speech_present")
    if rows and segments and float(segments[-1].get("end") or 0) >= duration - 0.05:
        failures.append("dialogue_tail_clipped_or_unverified")
    return {
        "status": "PASS" if not failures else "FAIL",
        "video_stream": video_stream,
        "audio_stream": audio_stream,
        "duration_seconds": round(duration, 3),
        "dialogue_required": bool(rows),
        "no_dialogue_required": require_no_dialogue,
        "dialogue_ids": expected_ids,
        "expected_text": expected,
        "transcript": transcript,
        "segments": segments,
        "recall_score": round(score, 3),
        "minimum_recall": minimum_recall,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--dialogue-json", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model")
    parser.add_argument("--ffprobe")
    parser.add_argument("--minimum-recall", type=float, default=0.55)
    parser.add_argument("--require-no-dialogue", action="store_true")
    args = parser.parse_args()
    video = args.video.expanduser().resolve()
    if not video.is_file():
        raise SystemExit(f"video not found: {video}")
    payload = json.loads(args.dialogue_json.read_text(encoding="utf-8"))
    rows = dialogue_rows(payload)
    ffprobe, ffprobe_source = resolve_media_binary(
        "ffprobe", explicit=args.ffprobe, root=ROOT
    )
    probe_payload = probe(video, ffprobe)
    transcript = ""
    segments_payload: list[dict] = []
    model_source = "not_required"
    model_ref = None
    if (rows or args.require_no_dialogue) and any(
        row.get("codec_type") == "audio" for row in probe_payload.get("streams") or []
    ):
        model_ref, model_source = resolve_whisper_model(args.model)
        from faster_whisper import WhisperModel

        model = WhisperModel(model_ref, device="cpu", compute_type="int8")
        expected = "".join(
            str(row.get("spoken_text") or row.get("text") or "") for row in rows
        )
        segments, _ = model.transcribe(
            str(video),
            language="zh",
            vad_filter=True,
            beam_size=5,
            initial_prompt=transcription_prompt(expected),
        )
        segments_payload = [
            {
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "text": segment.text.strip(),
            }
            for segment in segments
        ]
        transcript = "".join(row["text"] for row in segments_payload)
    report = evaluate(
        video,
        rows,
        probe_payload=probe_payload,
        transcript=transcript,
        segments=segments_payload,
        minimum_recall=args.minimum_recall,
        require_no_dialogue=args.require_no_dialogue,
    )
    report.update(
        {
            "schema": "qingshan.source_video_native_dialogue_gate.v1",
            "video": str(video),
            "video_sha256": sha256(video),
            "dialogue_contract": str(args.dialogue_json.expanduser().resolve()),
            "runtime": {
                "ffprobe": str(ffprobe),
                "ffprobe_source": ffprobe_source,
                "whisper_model": model_ref,
                "whisper_model_source": model_source,
            },
        }
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
