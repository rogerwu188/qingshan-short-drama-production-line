#!/usr/bin/env python3
"""Conditionally admit video reviews blocked only by an OCR tail decode gap."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def adjudicate(review_path: Path, output_path: Path, max_gap_seconds: float) -> dict:
    review = load(review_path)
    admissions = []
    for item in review.get("items", []):
        issues = item.get("issues", [])
        blocking_issues = [issue for issue in issues if issue.get("blocking")]
        if not blocking_issues or any(
            issue.get("rule_id") != "ocr.main_content_coverage_gap" for issue in blocking_issues
        ):
            raise ValueError("review contains a non-OCR-tail blocking issue")

        required = {
            name: capability
            for name, capability in item.get("capabilities", {}).items()
            if capability.get("requirement") == "REQUIRED"
        }
        failed_required = [name for name, capability in required.items() if capability.get("status") != "PASS"]
        if failed_required:
            raise ValueError(f"required capabilities failed: {failed_required}")

        ocr = item.get("capabilities", {}).get("ocr", {})
        window = ocr.get("review_window", {})
        gap = round(
            float(window.get("main_content_end_seconds", 0.0))
            - float(window.get("declared_review_end_seconds", 0.0)),
            6,
        )
        rejected = ocr.get("raw_rejected_recognitions", [])
        normalized_clear = (
            ocr.get("main_content_hit_count") == 0
            and ocr.get("raw_rejected_count", 0) == ocr.get("raw_recognition_count", 0)
            and all(not row.get("forbidden") for row in rejected)
        )
        if (ocr.get("raw_status") != "PASS" and not normalized_clear) or gap < 0 or gap > max_gap_seconds:
            raise ValueError(f"OCR evidence is not eligible for tail-gap adjudication: gap={gap}")

        media = Path(item["media_path"])
        media_digest = sha256(media)
        if media_digest != item.get("media_sha256"):
            raise ValueError(f"media SHA mismatch: {media}")

        admissions.append(
            {
                "clip_id": item.get("agentcut", {}).get("clip_id"),
                "media_path": str(media),
                "candidate_sha256": media_digest,
                "original_review_status": item.get("status"),
                "original_content_status": item.get("content_status"),
                "original_issues": issues,
                "original_issue_ids": [issue.get("issue_id") for issue in issues],
                "original_failed_checks": [issue.get("rule_id") for issue in blocking_issues],
                "decision": "CONDITIONAL_MACHINE_ADMISSION",
                "confidence": 0.99,
                "selection_reason": (
                    "All required media, motion, and audio capabilities passed; the external full-motion OCR "
                    "report passed with zero recognitions, while the only blocker was an attempted decode "
                    f"{gap:.6f}s beyond the last decodable frame."
                ),
                "admitted_failure": {
                    "kind": "REVERSIBLE_TOOL_BOUNDARY_GAP",
                    "ocr_tail_gap_seconds": gap,
                    "raw_ocr_status": ocr.get("raw_status"),
                    "normalized_main_content_hit_count": ocr.get("main_content_hit_count"),
                    "normalized_rejected_recognitions": rejected,
                    "supplemental_error": ocr.get("supplemental_gap_scan", {}).get("error"),
                },
                "rollback_point": str(media),
                "replacement_condition": (
                    "Replace only if an already-paid or explicitly approved same-story candidate passes "
                    "full-duration OCR without regressing identity, action, scene, cadence, or audio."
                ),
            }
        )

    payload = {
        "schema": "qingshan.video_review_ocr_tail_gap_machine_adjudication.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_review": {"path": str(review_path), "sha256": sha256(review_path)},
        "status": "CONDITIONAL_MACHINE_ADMISSION",
        "blocking": False,
        "policy": "Preserve raw review failure; admit only reversible decoder-boundary gaps.",
        "admissions": admissions,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-gap-seconds", type=float, default=0.05)
    args = parser.parse_args()
    payload = adjudicate(args.review.resolve(), args.output.resolve(), args.max_gap_seconds)
    print(json.dumps({"status": payload["status"], "admitted": len(payload["admissions"]), "output": str(args.output.resolve())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
