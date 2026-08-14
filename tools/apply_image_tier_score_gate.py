#!/usr/bin/env python3
"""Apply core/non-core image score thresholds while preserving fact hard gates."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
HARD_FACT_CHECKS = {
    "canonical_identity_continuity",
    "scene_authority",
    "story_action_clarity",
    "no_text_or_pseudotext",
    "native_anatomy",
    "no_extra_or_duplicated_bodies",
}


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tier_policy(manifest: dict[str, Any], shot_id: str) -> tuple[str, float]:
    policy = manifest["production_policy"]["image_validation"]
    core = shot_id in set(policy.get("core_shot_ids") or [])
    return ("CORE" if core else "NON_CORE", float(policy["core_min_score" if core else "non_core_min_score"]))


def report_candidate_sha(report: dict[str, Any]) -> str:
    capabilities = report.get("capabilities") or {}
    values = {
        str((capabilities.get(name) or {}).get("candidate_sha256"))
        for name in ("image_analysis", "ocr", "composition", "visual_continuity")
        if (capabilities.get(name) or {}).get("candidate_sha256")
    }
    if len(values) != 1:
        raise ValueError(f"review item has ambiguous candidate SHA values: {sorted(values)}")
    return next(iter(values))


def bind_review_reports(reports: list[dict[str, Any]], requests: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    by_sha: dict[str, dict[str, Any]] = {}
    for report in reports:
        candidate_sha = report_candidate_sha(report)
        if candidate_sha in by_sha:
            raise ValueError(f"duplicate review candidate SHA: {candidate_sha}")
        by_sha[candidate_sha] = report
    bound = []
    for expected in requests:
        expected_sha = str(expected["metadata"]["candidate_sha256"])
        report = by_sha.pop(expected_sha, None)
        if report is None:
            raise ValueError(f"review result missing exact candidate SHA: {expected_sha}")
        bound.append((expected, report))
    if by_sha:
        raise ValueError(f"review result contains unexpected candidate SHAs: {sorted(by_sha)}")
    return bound


def adjudicate(review: dict[str, Any], request: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    reports = review.get("items") or []
    requests = request.get("items") or []
    rows = []
    for expected, report in bind_review_reports(reports, requests):
        shot_id = expected["clip_id"]
        source_shot_id = expected.get("metadata", {}).get("source_shot_id", shot_id)
        path = resolve(expected["path"])
        expected_sha = expected["metadata"]["candidate_sha256"]
        integrity_pass = path.is_file() and sha256(path) == expected_sha and path.stat().st_size > 0
        tier, threshold = tier_policy(manifest, source_shot_id)
        score_100 = round(float(report.get("scoring", {}).get("score", 0)) * 20, 2)
        image_analysis = report.get("capabilities", {}).get("image_analysis", {})
        failed_checks = sorted({
            str(item.get("check")) for item in image_analysis.get("failures") or []
            if str(item.get("check")) in HARD_FACT_CHECKS
        })
        ocr_pass = report.get("capabilities", {}).get("ocr", {}).get("status") == "PASS"
        capability_failures = set(report.get("required_capability_failures") or [])
        tolerated_capability_only = capability_failures <= {"media_probe"}
        passed = integrity_pass and ocr_pass and not failed_checks and tolerated_capability_only and score_100 >= threshold
        rows.append({
            "shot_id": shot_id,
            "source_shot_id": source_shot_id,
            "tier": tier,
            "score_100": score_100,
            "minimum_score_100": threshold,
            "decision": "PASS" if passed else "FAIL",
            "candidate_path": str(path),
            "candidate_sha256": expected_sha,
            "media_integrity": "PASS" if integrity_pass else "FAIL",
            "ocr": "PASS" if ocr_pass else "FAIL",
            "hard_fact_failures": failed_checks,
            "tolerated_capability_failures": sorted(capability_failures) if tolerated_capability_only else [],
            "blocking_capability_failures": [] if tolerated_capability_only else sorted(capability_failures),
        })
    failed = [row for row in rows if row["decision"] == "FAIL"]
    return {
        "schema": "qingshan.image_tier_score_gate.v1",
        "episode": manifest["episode"],
        "status": "PASS" if not failed else "FAILED_ITEMS_ONLY",
        "policy": manifest["production_policy"]["image_validation"],
        "passed_count": len(rows) - len(failed),
        "failed_count": len(failed),
        "items": rows,
        "failed_shot_ids": [row["shot_id"] for row in failed],
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-result", required=True)
    parser.add_argument("--review-request", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    review = json.loads(resolve(args.review_result).read_text(encoding="utf-8"))
    request = json.loads(resolve(args.review_request).read_text(encoding="utf-8"))
    manifest = json.loads(resolve(args.manifest).read_text(encoding="utf-8"))
    result = adjudicate(review, request, manifest)
    out = resolve(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("status", "passed_count", "failed_count")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
