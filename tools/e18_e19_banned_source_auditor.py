#!/usr/bin/env python3
"""Audit E18/E19 draft timelines for hard-banned source IDs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


BASE = Path("/Users/rogerwu/qingshan_short_drama")

DEFAULTS = {
    "E18": {
        "timeline": BASE / "configs/e18_timeline_draft_v1_20260715.json",
        "coverage": BASE / "configs/e18_timeline_coverage_manifest_v1_20260715.json",
    },
    "E19": {
        "timeline": BASE / "configs/e19_timeline_draft_v2_20260715.json",
        "coverage": BASE / "configs/e19_timeline_coverage_manifest_v2_20260715.json",
    },
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def audit(episode: str) -> dict:
    cfg = DEFAULTS[episode]
    timeline = load(cfg["timeline"])
    coverage = load(cfg["coverage"])
    hard_bans = set(coverage.get("hard_bans_for_default_final_path", []))
    segment_ids = [s.get("source_id") for s in timeline.get("segments", [])]
    violations = [sid for sid in segment_ids if sid in hard_bans]
    return {
        "schema": "qingshan.banned_source_audit.v1",
        "episode": episode,
        "status": "PASS" if not violations else "FAIL",
        "timeline": str(cfg["timeline"]),
        "coverage_manifest": str(cfg["coverage"]),
        "hard_bans": sorted(hard_bans),
        "segment_count": len(segment_ids),
        "violations": violations,
        "policy": "Hard-banned source IDs must not appear in the default final path.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit E18/E19 timelines for banned source return.")
    parser.add_argument("--episode", choices=sorted(DEFAULTS), required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    result = audit(args.episode)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
