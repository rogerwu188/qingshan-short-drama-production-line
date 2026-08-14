#!/usr/bin/env python3
"""ASR-audit every admitted E34 v2 source unit carrying scripted dialogue."""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "workflow/tasks/E34_VIDEO_STREAMING_PERFORMANCE_V2_RECEIPT_20260723.json"
SPLIT = ROOT / "workflow/tasks/E34_U17_SPLIT_REPAIR1_VIDEO_RECEIPT_20260723.json"
CONFIG = ROOT / "workflow/claude_writer_agent/production/e34_claude_writer_v2_400ff6d2_20260723/video_performance_v2/E34_VIDEO_STREAMING_PERFORMANCE_V2.json"
SPLIT_CONFIG = ROOT / "workflow/claude_writer_agent/production/e34_claude_writer_v2_400ff6d2_20260723/video_performance_v2/u17_split_repair/E34_U17_SPLIT_VIDEO_BATCH.json"
ADMISSION = ROOT / "qa/e34_v2_streaming_video_compile_20260723/E34_OCR_ONLY_CONDITIONAL_MACHINE_ADMISSIONS_V2.json"
OUT = ROOT / "qa/e34_v2_streaming_video_compile_20260723/E34_NATIVE_DIALOGUE_SOURCE_ASR_V2.json"
MODEL = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def chinese(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", text or ""))


def best_recall(expected: str, transcript: str) -> float:
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


def main() -> int:
    admitted = {row["unit_id"] for row in load(ADMISSION)["selections"]}
    task_specs = {row["unit_id"]: row for row in load(CONFIG)["tasks"] if row["unit_id"] != "E34-CW-U17"}
    task_specs.update({row["unit_id"]: row for row in load(SPLIT_CONFIG)["tasks"]})
    sources = {}
    for receipt in (MAIN, SPLIT):
        for row in load(receipt)["tasks"]:
            if row.get("unit_id") == "E34-CW-U17":
                continue
            if row.get("status") == "qa_pass" or row.get("unit_id") in admitted:
                sources[row["unit_id"]] = row
    rows = []
    for unit_id, spec in task_specs.items():
        if not spec.get("dialogue"):
            continue
        source = sources.get(unit_id)
        if not source:
            raise SystemExit(f"missing admitted dialogue source: {unit_id}")
        rows.append({
            "unit_id": unit_id,
            "output_path": source["output_path"],
            "sha256": source["sha256"],
            "dialogue": spec["dialogue"],
        })
    model = WhisperModel(str(MODEL), device="cpu", compute_type="int8", cpu_threads=4, num_workers=2)

    def audit(row: dict) -> dict:
        segments, _ = model.transcribe(row["output_path"], language="zh", vad_filter=True, beam_size=5)
        segment_rows = [{"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text.strip()} for seg in segments]
        transcript = "".join(seg["text"] for seg in segment_rows)
        line_results = []
        failures = []
        advisories = []
        for dialogue in row["dialogue"]:
            score = best_recall(dialogue["spoken_text"], transcript)
            status = "PASS" if score >= 0.45 else "FAIL"
            if status == "FAIL":
                failures.append({"dialogue_id": dialogue["dia_id"], "reason": "ASR_RECALL_BELOW_0P45", "score": round(score, 3)})
            elif score < 0.70:
                advisories.append({"dialogue_id": dialogue["dia_id"], "reason": "ASR_HOMOPHONE_OR_PARTIAL_REVIEW", "score": round(score, 3)})
            line_results.append({**dialogue, "recall_score": round(score, 3), "status": status})
        if not chinese(transcript):
            failures.append({"reason": "NO_RECOGNIZED_CHINESE_SPEECH"})
        return {
            "unit_id": row["unit_id"], "source": row["output_path"], "sha256": row["sha256"],
            "transcript": transcript, "segments": segment_rows, "dialogue": line_results,
            "status": "PASS" if not failures else "FAIL", "failures": failures, "advisories": advisories,
        }

    results = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(audit, row) for row in rows]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: row["unit_id"])
    lines = [line for result in results for line in result["dialogue"]]
    failed = [result for result in results if result["status"] == "FAIL"]
    payload = {
        "schema": "qingshan.e34.native_dialogue_source_asr.v2", "episode": "E34",
        "status": "PASS" if not failed else "FAIL_WITH_ISOLATED_UNITS",
        "unit_count": len(results), "dialogue_line_count": len(lines),
        "dialogue_line_pass_count": sum(line["status"] == "PASS" for line in lines),
        "failed_unit_ids": [result["unit_id"] for result in failed],
        "policy": "Missing Chinese speech or per-line recall below 0.45 blocks release; subtitles cannot replace native dialogue.",
        "source_receipts": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in (MAIN, SPLIT)],
        "results": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": payload["status"], "unit_count": payload["unit_count"],
        "dialogue_line_pass_count": payload["dialogue_line_pass_count"],
        "dialogue_line_count": payload["dialogue_line_count"], "failed_unit_ids": payload["failed_unit_ids"], "out": str(OUT),
    }, ensure_ascii=False))
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
