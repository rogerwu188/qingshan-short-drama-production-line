#!/usr/bin/env python3
"""Check whether an episode release gate is ready for platform upload."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a release gate JSON and candidate file.")
    parser.add_argument("gate_json", help="Path to release gate status JSON.")
    args = parser.parse_args()

    gate_path = Path(args.gate_json).expanduser().resolve()
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    candidate = gate.get("candidate", {})
    candidate_path = Path(candidate.get("path", "")).expanduser()
    expected_sha = candidate.get("sha256")

    checks: list[dict[str, object]] = []

    exists = candidate_path.exists()
    checks.append({"name": "candidate_exists", "status": "PASS" if exists else "FAIL", "path": str(candidate_path)})

    if exists and expected_sha:
        actual_sha = sha256_file(candidate_path)
        checks.append(
            {
                "name": "candidate_sha256",
                "status": "PASS" if actual_sha == expected_sha else "FAIL",
                "expected": expected_sha,
                "actual": actual_sha,
            }
        )

    quality = gate.get("quality_gates", {})
    for key in ("final_ocr", "regression_ci", "brightness", "sentence_completeness"):
        checks.append({"name": key, "status": "PASS" if quality.get(key) == "PASS" else "FAIL", "value": quality.get(key)})

    storyclaw_review = quality.get("storyclaw_review")
    roger_override = quality.get("roger_override")
    review_ok = (
        storyclaw_review == "APPROVED"
        or str(storyclaw_review).startswith("ADVISORY_PASS")
        or roger_override == "APPROVED"
        or roger_override is True
    )
    checks.append(
        {
            "name": "approval",
            "status": "PASS" if review_ok else "HOLD",
            "storyclaw_review": quality.get("storyclaw_review"),
            "roger_override": quality.get("roger_override"),
        }
    )

    publish_allowed = bool(gate.get("platform_release", {}).get("publish_allowed"))
    checks.append({"name": "publish_allowed_flag", "status": "PASS" if publish_allowed else "HOLD", "value": publish_allowed})

    hard_fail = any(item["status"] == "FAIL" for item in checks)
    holds = [item for item in checks if item["status"] == "HOLD"]
    ready = not hard_fail and not holds and publish_allowed

    result = {
        "episode": gate.get("episode"),
        "gate_json": str(gate_path),
        "ready_to_publish": ready,
        "overall_status": gate.get("overall_status"),
        "hold_reason": gate.get("platform_release", {}).get("hold_reason") if not ready else None,
        "checks": checks,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if ready else 2 if not hard_fail else 1


if __name__ == "__main__":
    raise SystemExit(main())
