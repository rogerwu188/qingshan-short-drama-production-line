#!/usr/bin/env python3
"""Run immediate technical and ASR sentence QA on harvested E19R multimodal clips."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
MODEL = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FFPROBE = Path("/Users/rogerwu/.local/bin/ffprobe")


def chinese_only(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", text))


def recall_score(expected: str, transcript: str) -> float:
    expected_cn = chinese_only(expected)
    transcript_cn = chinese_only(transcript)
    if not expected_cn:
        return 1.0
    if expected_cn in transcript_cn:
        return 1.0
    matcher = SequenceMatcher(None, expected_cn, transcript_cn)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return matched / max(1, len(expected_cn))


def probe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--status-report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    status = json.loads(args.status_report.read_text(encoding="utf-8"))
    tasks = {row["dialogue_id"]: row for row in manifest["tasks"]}
    harvested = {row["dialogue_id"]: row for row in status["results"]}
    model = WhisperModel(str(MODEL), device="cpu", compute_type="int8")
    results: list[dict[str, Any]] = []
    for dialogue_id in sorted(tasks):
        task = tasks[dialogue_id]
        files = harvested.get(dialogue_id, {}).get("downloaded_files") or []
        failures: list[str] = []
        advisories: list[str] = []
        if len(files) != 1:
            failures.append(f"downloaded_file_count:{len(files)}")
            results.append({"dialogue_id": dialogue_id, "status": "FAIL", "failures": failures})
            continue
        path = Path(files[0])
        if not path.is_absolute():
            path = ROOT / path
        info = probe(path)
        streams = info.get("streams", [])
        video = next((row for row in streams if row.get("codec_type") == "video"), None)
        audio = next((row for row in streams if row.get("codec_type") == "audio"), None)
        duration = float((info.get("format") or {}).get("duration") or 0)
        if not video:
            failures.append("video_stream_missing")
        if not audio:
            failures.append("audio_stream_missing")
        if duration < 1.0 or duration > 6.0:
            failures.append(f"duration_out_of_range:{duration:.3f}")
        segments_payload: list[dict[str, Any]] = []
        if audio:
            segments, _ = model.transcribe(str(path), language="zh", vad_filter=True, beam_size=5)
            for segment in segments:
                segments_payload.append(
                    {"start": round(segment.start, 3), "end": round(segment.end, 3), "text": segment.text.strip()}
                )
        transcript = "".join(row["text"] for row in segments_payload)
        recall = recall_score(task["text"], transcript)
        if not chinese_only(transcript):
            failures.append("no_recognized_chinese_speech")
        elif recall < 0.45:
            failures.append(f"expected_dialogue_recall_below_0p45:{recall:.3f}")
        elif recall < 0.75:
            advisories.append(f"homophone_or_partial_asr_review:{recall:.3f}")
        if segments_payload and segments_payload[-1]["end"] >= duration - 0.05:
            advisories.append("speech_reaches_source_tail_sentence_boundary_review")
        results.append(
            {
                "dialogue_id": dialogue_id,
                "speaker": task["speaker"],
                "expected": task["text"],
                "path": str(path),
                "sha256": sha256(path),
                "duration_seconds": round(duration, 3),
                "video_stream": bool(video),
                "audio_stream": bool(audio),
                "transcript": transcript,
                "segments": segments_payload,
                "recall_score": round(recall, 3),
                "status": "PASS" if not failures else "FAIL",
                "failures": failures,
                "advisories": advisories,
            }
        )
    fail_count = sum(row["status"] == "FAIL" for row in results)
    payload = {
        "schema": "qingshan.e19r.multimodal_binding_batch_qa.v1",
        "episode": "E19R",
        "status": "PASS" if fail_count == 0 else "FAIL",
        "script_sha256": "8450c3dc7e139bde6686760f01a5e7f206e767fc9c3c2b4839dd51dc6ffc8f6e",
        "item_count": len(results),
        "pass_count": len(results) - fail_count,
        "fail_count": fail_count,
        "advisory_count": sum(len(row.get("advisories", [])) for row in results),
        "policy": "Audio stream, Chinese speech, and expected-line recall >=0.45 are hard gates. Homophone/partial ASR >=0.45 remains advisory pending final sentence-boundary QA.",
        "results": results,
        "final_lock_allowed": False,
        "rollback": "Remove only this QA report; harvested source files are immutable inputs.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "pass": payload["pass_count"], "fail": fail_count, "out": str(args.out)}, ensure_ascii=False))
    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
