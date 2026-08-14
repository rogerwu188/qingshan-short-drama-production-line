#!/usr/bin/env python3
"""Audit an E18R multimodal pilot batch before later beats are released."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel


BASE = Path("/Users/rogerwu/qingshan_short_drama")


def chinese_only(value: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", value))


def recall_score(expected: str, actual: str) -> float:
    expected_cn = chinese_only(expected)
    actual_cn = chinese_only(actual)
    if expected_cn and expected_cn in actual_cn:
        return 1.0
    return SequenceMatcher(None, expected_cn, actual_cn).ratio()


def manual_review_reason(expected: str, actual: str, score: float) -> str | None:
    """Route imperfect ASR to listening without turning homophones into hard fails."""
    expected_cn = chinese_only(expected)
    actual_cn = chinese_only(actual)
    if score < 0.9:
        return "asr_recall_below_0_9_possible_homophone_or_missing_word"
    if expected_cn != actual_cn:
        return "asr_text_differs_possible_homophone"
    return None


def ffmpeg_bin() -> str:
    result = subprocess.run(
        [str(BASE / "tools/find_ffmpeg.sh"), str(BASE)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def media_probe(ffmpeg: str, video: Path) -> tuple[float, int]:
    result = subprocess.run([ffmpeg, "-i", str(video)], capture_output=True, text=True)
    probe = result.stderr + result.stdout
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", probe)
    duration = 0.0
    if match:
        hours, minutes, seconds = match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    audio_streams = len(re.findall(r"Stream #\d+:\d+.*Audio:", probe))
    return duration, audio_streams


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--media-dir", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--beat-id", default="B01")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    media_dir = Path(args.media_dir).resolve()
    model_path = Path(args.model).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tasks = [row for row in manifest.get("tasks", []) if row.get("beat_id") == args.beat_id]
    model = WhisperModel(str(model_path), device="cpu", compute_type="int8")
    ffmpeg = ffmpeg_bin()
    results = []
    hard_failures = []
    manual_reviews = []

    for task in tasks:
        dialogue_id = task["dialogue_id"]
        video = media_dir / f"{dialogue_id}.mp4"
        failures = []
        segments_payload = []
        transcript = ""
        if not video.is_file():
            failures.append("media_missing")
            duration, audio_streams = 0.0, 0
        else:
            duration, audio_streams = media_probe(ffmpeg, video)
            segments, _ = model.transcribe(str(video), language="zh", vad_filter=True, beam_size=5)
            for segment in segments:
                segments_payload.append(
                    {"start": round(segment.start, 2), "end": round(segment.end, 2), "text": segment.text.strip()}
                )
            transcript = "".join(row["text"] for row in segments_payload)
        score = recall_score(task.get("text", ""), transcript)
        latin_words = re.findall(r"[A-Za-z]{2,}", transcript)
        if audio_streams < 1:
            failures.append("audio_stream_missing")
        if not 3.5 <= duration <= 4.5:
            failures.append("duration_outside_3_5_to_4_5_seconds")
        if len(chinese_only(transcript)) < 2:
            failures.append("recognized_chinese_speech_missing")
        if len(latin_words) >= 4:
            failures.append("latin_or_foreign_audio_pollution")
        if score < 0.25:
            failures.append("expected_dialogue_missing_or_wrong")
        review_reason = manual_review_reason(task.get("text", ""), transcript, score)
        if review_reason:
            manual_reviews.append(f"{dialogue_id}:{review_reason}")
        results.append(
            {
                "dialogue_id": dialogue_id,
                "speaker": task.get("speaker"),
                "voice_asset_id": task.get("voice_asset_id"),
                "video": str(video),
                "duration_seconds": round(duration, 2),
                "audio_streams": audio_streams,
                "expected": task.get("text"),
                "transcript": transcript,
                "segments": segments_payload,
                "asr_recall": round(score, 4),
                "status": "PASS_MACHINE" if not failures else "FAIL",
                "failures": failures,
            }
        )
        hard_failures.extend(f"{dialogue_id}:{failure}" for failure in failures)

    report = {
        "schema": "qingshan.e18r_multimodal_pilot_qa.v1",
        "episode": "E18R",
        "beat_id": args.beat_id,
        "status": "FAIL" if hard_failures else "PASS_MACHINE_PENDING_MANUAL_WATCH_LISTEN",
        "manifest": str(manifest_path),
        "media_dir": str(media_dir),
        "model": str(model_path),
        "item_count": len(results),
        "machine_pass_count": sum(row["status"] == "PASS_MACHINE" for row in results),
        "hard_failures": hard_failures,
        "manual_reviews": manual_reviews,
        "results": results,
        "manual_gate": {
            "required": True,
            "checks": [
                "canonical identity and costume continuity",
                "natural lip sync without mouth deformation",
                "Chenji, Wuyun and servant voices are audibly distinct",
                "servant final line is complete and intelligible",
                "no generated visual text or subtitle appears",
            ],
            "release_later_beats_before_manual_gate": False,
        },
        "policy": "ASR homophone substitutions are non-blocking; missing audio, missing/wrong dialogue, foreign pollution, or hard sentence truncation are blocking.",
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "machine_pass_count": report["machine_pass_count"], "out": str(out)}, ensure_ascii=False))
    return 1 if hard_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
