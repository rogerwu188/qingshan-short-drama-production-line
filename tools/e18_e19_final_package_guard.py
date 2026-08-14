#!/usr/bin/env python3
"""Guard E18/E19 final package execution.

This script is intentionally a gate, not a renderer. It prevents draft previews
or package skeletons from being mistaken for final packages.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


BASE = Path("/Users/rogerwu/qingshan_short_drama")

EPISODES = {
    "E18": {
        "prep": BASE / "qa/e18_e19_timeline_draft_v0_20260715/E18_FINAL_LOCK_PREP_STATUS_20260715.json",
        "artifact": BASE / "qa/e18_final_package_pending_20260715/E18_FINAL_PACKAGE_ARTIFACT_MANIFEST_20260715.json",
    },
    "E19": {
        "prep": BASE / "qa/e18_e19_timeline_draft_v0_20260715/E19_FINAL_LOCK_PREP_STATUS_20260715.json",
        "artifact": BASE / "qa/e19_final_package_pending_20260715/E19_FINAL_PACKAGE_ARTIFACT_MANIFEST_20260715.json",
    },
}


def load_json(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate_episode(episode: str) -> dict:
    cfg = EPISODES[episode]
    prep = load_json(cfg["prep"])
    artifact = load_json(cfg["artifact"])
    blockers = []

    if prep.get("status") != "FINAL_LOCK_PREP_READY__NOT_FINAL_LOCKED":
        blockers.append(f"unexpected prep status: {prep.get('status')}")
    if artifact.get("status") != "ARTIFACT_SKELETON_READY_NOT_RENDERED_NOT_FINAL_LOCKED":
        blockers.append(f"unexpected artifact status: {artifact.get('status')}")
    if artifact.get("final_video"):
        blockers.append("artifact manifest already points to a final_video; manual audit required")

    for gate in artifact.get("blocked_or_pending", []):
        blockers.append(f"pending gate: {gate}")

    global_blocker = artifact.get("global_order_blocker")
    if global_blocker:
        blockers.append(global_blocker)

    return {
        "episode": episode,
        "status": "BLOCKED_FOR_FINAL_PACKAGE" if blockers else "READY_FOR_FINAL_PACKAGE",
        "blockers": blockers,
        "prep_status": prep.get("status"),
        "artifact_status": artifact.get("status"),
        "runtime_sec": prep.get("runtime_sec"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check E18/E19 final package gate.")
    parser.add_argument("--episode", choices=sorted(EPISODES), required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    result = evaluate_episode(args.episode)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["status"] == "READY_FOR_FINAL_PACKAGE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
