#!/usr/bin/env python3
"""Apply Roger's 60-point long-take admission rule with hard-fact overrides."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


THRESHOLD = 60
HARD_FAILURES = {"IDENTITY", "SAFETY", "ERA", "OCR", "MEDIA_INTEGRITY"}


def adjudicate(score: float, hard_failures: list[str] | None = None) -> dict:
    hard = sorted(set(hard_failures or []))
    unknown = sorted(set(hard) - HARD_FAILURES)
    if unknown:
        raise ValueError(f"unsupported hard failures: {', '.join(unknown)}")
    passed = score >= THRESHOLD and not hard
    return {
        "schema": "qingshan.long_take_score_gate.v1",
        "score_100": score,
        "minimum_score_100": THRESHOLD,
        "hard_failures": hard,
        "hard_failures_override_score": True,
        "decision": "PASS" if passed else "FAIL",
        "paid_regeneration_allowed": not passed,
        "at_threshold_retained": score == THRESHOLD and not hard,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--score", type=float, required=True)
    parser.add_argument("--hard-failure", action="append", default=[])
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    result = adjudicate(args.score, args.hard_failure)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
