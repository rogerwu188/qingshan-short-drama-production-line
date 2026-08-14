#!/usr/bin/env python3
"""Batch-check existing E21 alternatives for semantic and cadence-safe reuse."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
MODEL = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
TARGETS = ("DIA-007", "DIA-024", "DIA-026", "DIA-031", "DIA-032")


def chinese(text: str) -> str:
    table = str.maketrans({"陳": "陈", "時": "时", "來": "来", "對": "对", "賬": "账", "個": "个", "線": "线", "認": "认", "得": "得"})
    return "".join(re.findall(r"[\u4e00-\u9fff]", text.translate(table)))


def recall(expected: str, actual: str) -> float:
    left, right = chinese(expected), chinese(actual)
    if not left:
        return 1.0
    if left in right:
        return 1.0
    return sum(block.size for block in SequenceMatcher(None, left, right).get_matching_blocks()) / len(left)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    project = json.loads(args.project.read_text(encoding="utf-8"))
    clips = project["timeline"]["videoTracks"][0]["clips"]
    current = {
        clip["metadata"]["dialogue_id"]: {
            "source": str(Path(clip["source"]).resolve()),
            "expected": clip["metadata"]["exact_dialogue"],
        }
        for clip in clips
        if clip.get("metadata", {}).get("dialogue_id") in TARGETS
    }
    model = WhisperModel(str(MODEL), device="cpu", compute_type="int8")
    rows = []
    cadence_dir = args.out.parent / "candidate_cadence"
    cadence_dir.mkdir(parents=True, exist_ok=True)

    for dia_id in TARGETS:
        candidates = sorted(ROOT.glob(f"working_assets/e21*/candidates/*{dia_id}*.mp4"))
        for candidate in candidates:
            segments, _ = model.transcribe(str(candidate), language="zh", vad_filter=False, beam_size=5)
            transcript = "".join(segment.text.strip() for segment in segments)
            cadence = cadence_dir / f"{candidate.stem}_frame_cadence.json"
            proc = subprocess.run(
                [
                    "python3",
                    "tools/frame_cadence_audit.py",
                    "--video",
                    str(candidate),
                    "--out",
                    str(cadence),
                    "--audit-scope",
                    "VIDEO_ONLY_DIAGNOSTIC",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            cadence_payload = json.loads(cadence.read_text(encoding="utf-8"))
            semantic_recall = recall(current[dia_id]["expected"], transcript)
            is_current = str(candidate.resolve()) == current[dia_id]["source"]
            rows.append(
                {
                    "dialogue_id": dia_id,
                    "expected": current[dia_id]["expected"],
                    "candidate": str(candidate.resolve()),
                    "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                    "is_current": is_current,
                    "transcript": transcript,
                    "semantic_recall": round(semantic_recall, 3),
                    "cadence_status": cadence_payload["status"],
                    "motion_mean": cadence_payload.get("motion_mean"),
                    "near_duplicate_ratio": cadence_payload.get("periodic_duplicates", {}).get("near_duplicate_ratio"),
                    "eligible_alternative": not is_current and semantic_recall >= 0.75 and cadence_payload["status"] == "PASS",
                    "cadence_report": str(cadence),
                    "cadence_exit_code": proc.returncode,
                }
            )

    eligible = [row for row in rows if row["eligible_alternative"]]
    payload = {
        "schema": "qingshan.existing_candidate_reuse_qa.v1",
        "episode": "E21",
        "status": "PASS_WITH_ELIGIBLE_ALTERNATIVES" if eligible else "PASS_NO_ELIGIBLE_ALTERNATIVES",
        "target_dialogue_ids": list(TARGETS),
        "candidate_count": len(rows),
        "eligible_count": len(eligible),
        "policy": "Source reuse requires both semantic_recall >= 0.75 and frame-cadence PASS; current sources are not alternatives.",
        "eligible_alternatives": eligible,
        "results": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "candidates": len(rows), "eligible": len(eligible), "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
