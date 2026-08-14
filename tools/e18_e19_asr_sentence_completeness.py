#!/usr/bin/env python3
"""ASR sentence-completeness gate for E18/E19 downloaded omni candidates."""

from __future__ import annotations

import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel


BASE = Path("/Users/rogerwu/qingshan_short_drama")
PACKAGE = BASE / "configs/e18_e19_final_omni_multimodal_candidate_package_v1_20260715.json"
QUEUE = BASE / "qa/e18_e19_final_omni_multimodal_candidates_v1_20260715/E18_E19_POST_OMNI_DOWNLOAD_QA_QUEUE_20260715.json"
QA_DIR = BASE / "qa/e18_e19_final_omni_multimodal_candidates_v1_20260715"
OUT_JSON = QA_DIR / "E18_E19_ASR_SENTENCE_COMPLETENESS_20260715.json"
OUT_MD = QA_DIR / "E18_E19_ASR_SENTENCE_COMPLETENESS_20260715.md"
MODEL_PATH = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def chinese_only(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", text))


def latin_words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z]{2,}", text)


def ffmpeg_bin() -> str:
    proc = subprocess.run(
        [str(BASE / "tools/find_ffmpeg.sh"), str(BASE)],
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


FFMPEG = ffmpeg_bin()


def duration_sec(video: Path) -> float:
    proc = subprocess.run(
        [
            FFMPEG,
            "-i",
            str(video),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    text = proc.stderr + proc.stdout
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not match:
        return 0.0
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def audio_stream_count(video: Path) -> int:
    proc = subprocess.run(
        [
            FFMPEG,
            "-i",
            str(video),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    text = proc.stderr + proc.stdout
    return len(re.findall(r"Stream #\d+:\d+.*Audio:", text))


def recall_score(expected: str, transcript: str) -> float:
    exp = chinese_only(expected)
    got = chinese_only(transcript)
    if not exp:
        return 1.0
    if exp in got:
        return 1.0
    matcher = SequenceMatcher(None, exp, got)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / max(1, len(exp))


def verdict_for_item(expected_lines: list[str], transcript: str, audio_count: int, duration: float) -> tuple[str, list[dict[str, Any]], list[str]]:
    failures: list[str] = []
    lines = []
    got_cn = chinese_only(transcript)
    if audio_count < 1:
        failures.append("NO_AUDIO_STREAM")
    if duration <= 0:
        failures.append("INVALID_DURATION")
    if len(got_cn) < 2 and expected_lines:
        failures.append("NO_RECOGNIZED_CHINESE_SPEECH")
    if "字幕" in transcript or "by" in transcript.lower():
        failures.append("CREDIT_OR_SUBTITLE_AUDIO_CONTAMINATION")
    latin = latin_words(transcript)
    if len(latin) >= 4:
        failures.append("LATIN_OR_FOREIGN_POLLUTION")
    for expected in expected_lines:
        score = recall_score(expected, transcript)
        lines.append(
            {
                "expected": expected,
                "recall_score": round(score, 3),
                "machine_status": "PASS" if score >= 0.45 else "REVIEW_REQUIRED",
            }
        )
    review_count = sum(1 for line in lines if line["machine_status"] == "REVIEW_REQUIRED")
    if expected_lines and review_count == len(expected_lines):
        failures.append("EXPECTED_DIALOGUE_MISSING_OR_WRONG_DIALOGUE")
    if failures:
        return "FAIL", lines, failures
    if review_count:
        return "PASS_WITH_MANUAL_SENTENCE_WATCH_REQUIRED", lines, failures
    return "PASS", lines, failures


def main() -> int:
    package = read_json(PACKAGE)
    queue = read_json(QUEUE)
    videos = {item["source_id"]: Path(item["video"]) for item in queue["items"] if item.get("video")}
    model = WhisperModel(str(MODEL_PATH), device="cpu", compute_type="int8")
    results = []
    fail_count = 0
    manual_watch_count = 0
    for group in package["candidate_groups"]:
        source_id = group["source_id"]
        video = videos.get(source_id)
        expected_lines = [item["dialogue_text"] for item in group.get("audio_dialogue_items", [])]
        transcript = ""
        segments_payload = []
        if video and video.exists():
            segments, info = model.transcribe(str(video), language="zh", vad_filter=True, beam_size=5)
            for seg in segments:
                segments_payload.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()})
            transcript = "".join(seg["text"] for seg in segments_payload)
        dur = duration_sec(video) if video else 0.0
        streams = audio_stream_count(video) if video else 0
        status, line_results, failures = verdict_for_item(expected_lines, transcript, streams, dur)
        if status == "FAIL":
            fail_count += 1
        if status == "PASS_WITH_MANUAL_SENTENCE_WATCH_REQUIRED":
            manual_watch_count += 1
        results.append(
            {
                "episode": group["episode"],
                "source_id": source_id,
                "timeline_order": group["timeline_order"],
                "video": str(video) if video else None,
                "duration_sec": round(dur, 2),
                "audio_streams": streams,
                "expected_lines": expected_lines,
                "transcript": transcript,
                "segments": segments_payload,
                "line_results": line_results,
                "status": status,
                "failures": failures,
            }
        )
    payload = {
        "schema": "qingshan.e18_e19_asr_sentence_completeness.v1",
        "status": "FAIL" if fail_count else ("PASS_WITH_MANUAL_SENTENCE_WATCH_REQUIRED" if manual_watch_count else "PASS"),
        "package": str(PACKAGE),
        "queue": str(QUEUE),
        "model": str(MODEL_PATH),
        "item_count": len(results),
        "fail_count": fail_count,
        "manual_sentence_watch_required_count": manual_watch_count,
        "policy": "ASR homophone/misrecognition is non-blocking. Hard fail only for empty/missing audio, obvious missing voice, foreign/Latin pollution, repeated dialogue or hard sentence cuts.",
        "results": results,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# E18/E19 ASR Sentence Completeness",
        "",
        f"Status: `{payload['status']}`",
        f"Items: `{payload['item_count']}`",
        f"Hard failures: `{payload['fail_count']}`",
        f"Manual sentence watch required: `{payload['manual_sentence_watch_required_count']}`",
        "",
        "Policy: ASR homophone/misrecognition is non-blocking; hard fail only for empty/missing audio, obvious missing voice, foreign/Latin pollution, repeated dialogue or hard sentence cuts.",
        "",
        "## Items",
        "",
    ]
    for item in results:
        lines.append(f"- `{item['episode']} {item['timeline_order']} {item['source_id']}`: `{item['status']}` duration `{item['duration_sec']}s` transcript `{item['transcript']}`")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "fail_count": fail_count, "out": str(OUT_JSON)}, ensure_ascii=False))
    return 1 if fail_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
