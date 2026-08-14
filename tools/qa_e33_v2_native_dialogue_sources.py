#!/usr/bin/env python3
"""ASR-audit every E33 v2 source unit that carries scripted dialogue."""

from __future__ import print_function

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
SELECTION = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723/video_performance_v2/E33_VIDEO_SOURCE_SELECTION_V2.json"
OUT = ROOT / "qa/e33_v2_final_video_source_review_20260723/E33_NATIVE_DIALOGUE_SOURCE_ASR_V1.json"
MODEL = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")


def chinese(text):
    return "".join(re.findall(r"[\u4e00-\u9fff]", text or ""))


def best_recall(expected, transcript):
    source = chinese(expected)
    actual = chinese(transcript)
    if not source:
        return 1.0
    if source in actual:
        return 1.0
    if not actual:
        return 0.0
    minimum = max(1, int(len(source) * 0.65))
    maximum = min(len(actual), max(minimum, int(len(source) * 1.50)))
    best = 0.0
    for width in range(minimum, maximum + 1):
        for start in range(0, len(actual) - width + 1):
            candidate = actual[start:start + width]
            matched = sum(block.size for block in SequenceMatcher(None, source, candidate).get_matching_blocks())
            best = max(best, matched / float(len(source)))
    return best


def main():
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    dialogue_rows = [row for row in selection["rows"] if row.get("dialogue")]
    model = WhisperModel(str(MODEL), device="cpu", compute_type="int8", cpu_threads=4, num_workers=2)

    def audit(row):
        segments, _ = model.transcribe(row["output_path"], language="zh", vad_filter=True, beam_size=5)
        segment_rows = [
            {"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text.strip()}
            for seg in segments
        ]
        transcript = "".join(seg["text"] for seg in segment_rows)
        line_results = []
        failures = []
        advisories = []
        for dialogue in row["dialogue"]:
            score = best_recall(dialogue["spoken_text"], transcript)
            line_status = "PASS" if score >= 0.45 else "FAIL"
            if line_status == "FAIL":
                failures.append({"dialogue_id": dialogue["dia_id"], "reason": "ASR_RECALL_BELOW_0P45", "score": round(score, 3)})
            elif score < 0.70:
                advisories.append({"dialogue_id": dialogue["dia_id"], "reason": "ASR_HOMOPHONE_OR_PARTIAL_REVIEW", "score": round(score, 3)})
            line_results.append({
                "dialogue_id": dialogue["dia_id"],
                "speaker": dialogue["speaker"],
                "expected": dialogue["spoken_text"],
                "recall_score": round(score, 3),
                "status": line_status,
            })
        if not chinese(transcript):
            failures.append({"reason": "NO_RECOGNIZED_CHINESE_SPEECH"})
        return {
            "unit_id": row["unit_id"],
            "source": row["output_path"],
            "sha256": row["sha256"],
            "transcript": transcript,
            "segments": segment_rows,
            "dialogue": line_results,
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
            "advisories": advisories,
        }

    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(audit, row) for row in dialogue_rows]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: row["unit_id"])
    all_lines = [line for row in results for line in row["dialogue"]]
    failures = [row for row in results if row["status"] == "FAIL"]
    payload = {
        "schema": "qingshan.e33.native_dialogue_source_asr.v1",
        "episode": "E33",
        "status": "PASS" if not failures else "FAIL_WITH_ISOLATED_UNITS",
        "unit_count": len(results),
        "dialogue_line_count": len(all_lines),
        "dialogue_line_pass_count": sum(row["status"] == "PASS" for row in all_lines),
        "failed_unit_ids": [row["unit_id"] for row in failures],
        "policy": "Hard fail missing Chinese speech or per-line recall below 0.45; preserve homophone variation as advisory evidence.",
        "selection_sha256": hashlib.sha256(SELECTION.read_bytes()).hexdigest(),
        "results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": payload["status"],
        "unit_count": payload["unit_count"],
        "dialogue_line_pass_count": payload["dialogue_line_pass_count"],
        "dialogue_line_count": payload["dialogue_line_count"],
        "failed_unit_ids": payload["failed_unit_ids"],
        "out": str(OUT),
    }, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
