#!/usr/bin/env python3
"""Select the best exact-SHA still candidate without erasing raw QA failures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", action="append", required=True, type=Path)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    candidates: dict[str, list[dict]] = {}
    sources = []
    for review_path in args.review:
        payload = load(review_path)
        sources.append(str(review_path.resolve()))
        for row in payload.get("items", []):
            shot_id = (row.get("agentcut") or {}).get("clip_id")
            if not shot_id:
                continue
            media = Path(row["media_path"])
            if not media.is_file() or sha256(media) != row.get("media_sha256"):
                continue
            if row.get("required_capability_failures"):
                continue
            blocking = [
                issue.get("details", {}).get("check") or issue.get("rule_id")
                for issue in row.get("issues", [])
                if issue.get("blocking")
            ]
            candidates.setdefault(shot_id, []).append({
                "shot_id": shot_id,
                "path": str(media.resolve()),
                "sha256": row["media_sha256"],
                "review_id": row.get("review_id"),
                "raw_status": row.get("status"),
                "score": float((row.get("scoring") or {}).get("score") or 0),
                "blocking_checks": blocking,
                "source_review": str(review_path.resolve()),
            })

    selections = []
    for shot_id in sorted(candidates):
        rows = candidates[shot_id]
        passed = [row for row in rows if row["raw_status"] == "PASS"]
        selected = max(passed or rows, key=lambda row: (row["score"], row["sha256"]))
        conditional = selected["raw_status"] != "PASS"
        selections.append({
            **selected,
            "admission": "CONDITIONAL_MACHINE_ADMISSION" if conditional else "PASS",
            "selection_reason": (
                "Highest-scoring technically valid candidate after one targeted failed-only retry; "
                "raw creative-quality FAIL remains preserved."
                if conditional
                else "Exact-SHA candidate passed required image analysis and OCR."
            ),
            "confidence": round(min(0.99, max(0.5, selected["score"] / 5.0)), 3),
            "rollback_point": selected["sha256"],
            "replacement_condition": (
                "Replace only if a later exact-script candidate passes every remaining blocking check."
                if conditional
                else None
            ),
            "candidate_count": len(rows),
        })

    conditional_count = sum(row["admission"] == "CONDITIONAL_MACHINE_ADMISSION" for row in selections)
    output = {
        "schema": "qingshan.conditional_machine_admission.v1",
        "episode": args.episode.upper(),
        "status": "PASS_WITH_CONDITIONAL_ADMISSION" if conditional_count else "PASS",
        "source_reviews": sources,
        "selection_count": len(selections),
        "direct_pass_count": len(selections) - conditional_count,
        "conditional_admission_count": conditional_count,
        "policy": "Preserve raw FAIL evidence; after one targeted repair, choose the best technically valid candidate and continue the reversible pipeline.",
        "selections": selections,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: output[key] for key in ("status", "selection_count", "direct_pass_count", "conditional_admission_count")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
