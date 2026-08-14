#!/usr/bin/env python3
"""Summarize the current short-drama production line state.

This script is read-only. It does not publish, delete, approve, or upload.
It turns the current bridge receipt, E17 release gate, and E16 metrics schedule
into a compact patrol JSON for heartbeat checks.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def latest_sc2x_from_receipt(path: Path) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    matches = re.findall(r"SC2X-\d+(?:-[A-Z]+)?", text)
    return matches[-1] if matches else None


def episode_summary(manifest: dict, release_gate: dict) -> dict:
    """Prefer current release facts over the older package-ready manifest."""
    if release_gate.get("status"):
        douyin = release_gate.get("douyin", {})
        return {
            "status": release_gate.get("status"),
            "release_authorization": release_gate.get("release_gate"),
            "final_video": release_gate.get("final_video") or manifest.get("final_video"),
            "youtube": release_gate.get("youtube", {}),
            "douyin": douyin,
            "blocker": release_gate.get("blocker"),
            "next_safe_action": douyin.get("next_required_action")
            or "Continue post-publish monitoring; do not re-upload published episodes.",
        }
    return {
        "status": manifest.get("status"),
        "release_authorization": manifest.get("release_authorization"),
        "final_video": manifest.get("final_video"),
        "next_safe_action": manifest.get("next_safe_action"),
    }


def queue_next_safe_action(ordered_queue: dict) -> str:
    items = ordered_queue.get("queue", [])
    if items and all("PUBLISHED_PUBLIC" in str(item.get("status", "")) for item in items):
        return (
            "All ordered releases are public. Continue post-publish monitoring, capture due metrics, "
            "and do not re-upload published episodes."
        )
    return (
        "Poll StoryClaw and continue the first incomplete ordered platform action; "
        "later local preparation may continue without releasing out of order."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a production-line patrol status JSON.")
    parser.add_argument("--out", default=str(ROOT / "workflow/production_line/PRODUCTION_LINE_PATROL_LATEST.json"))
    args = parser.parse_args()

    now = datetime.now().astimezone().isoformat(timespec="seconds")
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    storyclaw_receipt = ROOT / "workflow/storyclaw_outbox/STORYCLAW_OUTBOX_POLLER_RECEIPT.md"
    e17_gate = read_json(ROOT / "workflow/release/e17/E17_RELEASE_GATE_STATUS_20260714.json")
    e17_gate_check = read_json(ROOT / "workflow/release/e17/E17_RELEASE_GATE_CHECK_RESULT_20260714.json")
    e17_live = read_json(ROOT / "workflow/release/e17/E17_LIVE_MONITOR_STATUS_20260714.json")
    e18_manifest = read_json(ROOT / "qa/e18_final_package_pending_20260715/E18_FINAL_PACKAGE_ARTIFACT_MANIFEST_20260715.json")
    e19_manifest = read_json(ROOT / "qa/e19_final_package_pending_20260715/E19_FINAL_PACKAGE_ARTIFACT_MANIFEST_20260715.json")
    e18_release = read_json(ROOT / "workflow/release/e18/E18_RELEASE_GATE_STATUS_20260715.json")
    e19_release = read_json(ROOT / "workflow/release/e19/E19_RELEASE_GATE_STATUS_20260715.json")
    e16_metrics = read_json(ROOT / "workflow/platform_metrics/E16_metrics_20260714.json")
    ordered_queue = read_json(ROOT / "workflow/release/ORDERED_PLATFORM_RELEASE_QUEUE_20260715.json")

    e17_checks = e17_gate_check.get("checks", [])
    e17_failed = [c for c in e17_checks if c.get("status") == "FAIL"]
    e17_holds = [c for c in e17_checks if c.get("status") == "HOLD"]

    status = {
        "updated_at": now,
        "storyclaw": {
            "latest_known_sc2x": latest_sc2x_from_receipt(storyclaw_receipt),
            "receipt": str(storyclaw_receipt),
        },
        "e16": {
            "publish_state": e16_metrics.get("publish_state"),
            "youtube": e16_metrics.get("youtube", {}).get("status"),
            "youtube_url": e16_metrics.get("youtube_url") or e16_metrics.get("youtube", {}).get("shorts_url"),
            "douyin": e16_metrics.get("douyin", {}).get("status"),
            "next_metric_due": "T+24h 2026-07-15 08:54 PDT",
            "cleanup_allowed": False,
            "cleanup_reason": "E16 is not yet 24h post-publish and Douyin URL/comment follow-up remains pending.",
        },
        "e17": {
            "ready_to_publish": bool(e17_gate_check.get("ready_to_publish")),
            "overall_status": e17_gate_check.get("overall_status"),
            "release_gate_status": e17_gate.get("overall_status"),
            "platform_release": e17_gate.get("platform_release", {}),
            "current_blocker": e17_live.get("current_blocker"),
            "hold_reason": e17_gate_check.get("hold_reason"),
            "failed_checks": e17_failed,
            "hold_checks": e17_holds,
        },
        "e18": episode_summary(e18_manifest, e18_release),
        "e19": episode_summary(e19_manifest, e19_release),
        "ordered_platform_release_queue": ordered_queue,
        "release_order": [
            f"{item.get('episode')} {item.get('platform')} {item.get('action')}: {item.get('status')}"
            for item in ordered_queue.get("queue", [])
        ]
        or [
            "E17 YouTube platform backfill first",
            "E17 Douyin after YouTube state is captured",
            "E18 platform release after E17",
            "E19 platform release after E18",
        ],
        "next_safe_action": queue_next_safe_action(ordered_queue),
    }

    out.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out), "e17_ready_to_publish": status["e17"]["ready_to_publish"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
