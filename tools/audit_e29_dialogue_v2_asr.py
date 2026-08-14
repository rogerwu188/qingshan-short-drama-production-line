#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel
from opencc import OpenCC


BASE = Path("/Users/rogerwu/qingshan_short_drama")
MODEL = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
MANIFEST = BASE / "qa/e29_final_v2_dialogue_20260722/E29_DIALOGUE_AUDIO_MANIFEST_V2.json"
OUT = BASE / "qa/e29_final_v2_dialogue_20260722/E29_DIALOGUE_ASR_AUDIT_V2.json"
CC = OpenCC("t2s")


def chinese(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", CC.convert(text)))


def recall(expected: str, actual: str) -> float:
    expected = chinese(expected)
    actual = chinese(actual)
    if expected in actual:
        return 1.0
    return sum(
        block.size for block in SequenceMatcher(None, expected, actual).get_matching_blocks()
    ) / max(1, len(expected))


def main() -> int:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    model = WhisperModel(str(MODEL), device="cpu", compute_type="int8")
    rows = []
    for source in payload["rows"]:
        segments, _ = model.transcribe(
            source["fitted_file"], language="zh", vad_filter=False, beam_size=5
        )
        transcript = "".join(segment.text.strip() for segment in segments)
        score = recall(source["text"], transcript)
        rows.append({
            "dialogue_id": source["dialogue_id"],
            "speaker": source["speaker"],
            "expected": source["text"],
            "transcript": transcript,
            "recall_score": round(score, 3),
            "speech_present": bool(chinese(transcript)),
            "status": "PASS" if chinese(transcript) and score >= 0.55 else "FAIL",
        })
    failures = [row["dialogue_id"] for row in rows if row["status"] != "PASS"]
    report = {
        "schema": "qingshan.e29_dialogue_asr_audit.v1",
        "episode": "E29",
        "version": "V2",
        "status": "PASS" if not failures else "FAIL",
        "policy": "All 15 generated role-bound lines must contain recognized Chinese speech with simplified-Chinese lexical recall >= 0.55. Raw failures are preserved; deterministic TTS pronunciation aliases remain explicit in the audio manifest.",
        "line_count": len(rows),
        "pass_count": len(rows) - len(failures),
        "failures": failures,
        "rows": rows,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "pass_count": report["pass_count"], "failures": failures}, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
