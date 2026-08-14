#!/usr/bin/env python3
"""Run basic signal and Mandarin ASR checks on E18R side-role voice samples."""

from __future__ import annotations

import argparse
import audioop
import json
import re
import wave
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel


def chinese_only(value: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", value))


def recall_score(expected: str, actual: str) -> float:
    expected_cn = chinese_only(expected)
    actual_cn = chinese_only(actual)
    if expected_cn and expected_cn in actual_cn:
        return 1.0
    return SequenceMatcher(None, expected_cn, actual_cn).ratio()


def signal_stats(path: Path) -> dict:
    with wave.open(str(path), "rb") as handle:
        frames = handle.readframes(handle.getnframes())
        width = handle.getsampwidth()
        duration = handle.getnframes() / handle.getframerate()
    return {
        "duration_seconds": round(duration, 3),
        "rms_normalized": round(audioop.rms(frames, width) / 32768.0, 6),
        "peak_normalized": round(audioop.max(frames, width) / 32768.0, 6),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    model = WhisperModel(str(Path(args.model).resolve()), device="cpu", compute_type="int8")
    results = []
    failures = []
    for row in payload.get("samples") or []:
        sample = Path(row["sample_path"]).resolve()
        segments, _ = model.transcribe(str(sample), language="zh", vad_filter=True)
        transcript = "".join(segment.text.strip() for segment in segments)
        score = recall_score(row["sample_text"], transcript)
        stats = signal_stats(sample)
        item_failures = []
        if stats["duration_seconds"] < 0.4:
            item_failures.append("duration_too_short")
        if stats["rms_normalized"] < 0.005:
            item_failures.append("near_silent")
        if score < 0.5:
            item_failures.append("asr_recall_below_0_5")
        results.append(
            {
                "speaker": row["speaker"],
                "sample_path": str(sample),
                "expected": row["sample_text"],
                "transcript": transcript,
                "asr_recall": round(score, 4),
                **stats,
                "status": "PASS" if not item_failures else "FAIL",
                "failures": item_failures,
            }
        )
        failures.extend(f"{row['speaker']}:{failure}" for failure in item_failures)
    report = {
        "schema": "qingshan.e18r_side_role_voice_sample_qa.v1",
        "episode": "E18R",
        "status": "PASS_READY_FOR_REMOTE_REGISTRATION" if not failures else "FAIL",
        "manifest": str(manifest_path),
        "model": str(Path(args.model).resolve()),
        "sample_count": len(results),
        "results": results,
        "failures": failures,
        "human_review": "NOT_REQUIRED_FOR_SINGLE_EPISODE_SIDE_ROLES_PER_CL2X_239_240",
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "failures": failures}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
