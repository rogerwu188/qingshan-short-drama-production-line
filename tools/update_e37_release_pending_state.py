#!/usr/bin/env python3
"""Advance E37 state to production-complete, platform-submission pending."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "workflow/work_queue.json"
TASK = ROOT / "workflow/tasks/E37_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
PACKAGE = ROOT / "workflow/releases/E37_RELEASE_PACKAGE_FINAL_V1_20260803.json"
RECEIPT = ROOT / "workflow/releases/E37_PLATFORM_SUBMISSION_BROWSER_CONTROL_BLOCK_RECEIPT_V1_20260803.json"
MASTER = ROOT / "exports/e37/agentcut_v1_accepted_only_20260803/E37_AGENTCUT_V1_ACCEPTED_ONLY_PRODUCTION_CANDIDATE.mp4"
MASTER_SHA = "8a6559bdd19ca1862b580eb35ace00bf2060add58199db20d4cdd9f3c545d76b"
SCRIPT_SHA = "07a63a0c286be656feac59a0f31ea1bb159f3f7ce56f1172bb202832edf9db3a"
MANIFEST_SHA = "9082f9d3b45bf0466476e98cb194d91d00d6775c2b762b5253c8f7557d31c33e"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def write_json(path: Path, value: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(tmp, path)


def main() -> int:
    if sha256(MASTER) != MASTER_SHA:
        raise RuntimeError("E37 master SHA mismatch")
    package = load(PACKAGE)
    if package.get("production_complete") is not True or package.get("release_package_complete") is not True:
        raise RuntimeError("E37 release package is not complete")
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    package_sha = sha256(PACKAGE)
    receipt = {
        "schema": "qingshan.e37.platform_submission_browser_control_block.v1",
        "episode": "E37",
        "generated_at": timestamp,
        "status": "PLATFORM_SUBMISSION_PENDING_BROWSER_CONTROL_CHANNEL_TIMEOUT",
        "production_complete": True,
        "release_package_complete": True,
        "release_package": "workflow/releases/E37_RELEASE_PACKAGE_FINAL_V1_20260803.json",
        "release_package_sha256": package_sha,
        "master_sha256": MASTER_SHA,
        "attempts": [
            {
                "surface": "Codex in-app browser",
                "target": "https://studio.youtube.com/channel/UCU4dycBEqXgiqEIjSg9zBmQ",
                "result": "PAGE_TITLE_AND_TARGET_URL_LOADED_THEN_DOM_AND_SCREENSHOT_CONTROL_TIMED_OUT",
                "media_selected": False,
                "platform_mutation": False,
            },
            {
                "surface": "Chrome extension browser",
                "target": "https://studio.youtube.com/channel/UCU4dycBEqXgiqEIjSg9zBmQ",
                "result": "ONLY_GIGGLE_TAB_DISCOVERED_NEW_STUDIO_NAVIGATION_CONTROL_TIMED_OUT",
                "media_selected": False,
                "platform_mutation": False,
            },
        ],
        "youtube": {
            "account": "拉努影业 Nalu Motion Picture / @NaluMotion-P",
            "channel_id": "UCU4dycBEqXgiqEIjSg9zBmQ",
            "payload": "working_assets/e37_release_prep_20260803/platform_payload_v1/youtube_full",
            "submission": "NOT_STARTED_ZERO_MEDIA_TRANSMITTED",
        },
        "douyin": {
            "account": "迷雾剧场·AI连载",
            "douyin_id": "45198541560",
            "payload": "working_assets/e37_release_prep_20260803/platform_payload_v1/douyin_full",
            "submission": "NOT_STARTED_HELD_BEHIND_YOUTUBE_ORDER_ZERO_MEDIA_TRANSMITTED",
        },
        "blocked_by": "PLATFORM_SUBMISSION_ONLY:BROWSER_CONTROL_CHANNEL_TIMEOUT_NO_MEDIA_TRANSMITTED",
        "workaround_executed": "Completed all reversible production, QA, AgentCut release validation, exact-SHA package construction, target binding, and platform payload preparation; checked for repository API/CLI alternatives and found none. Preserved zero-transmission state for a clean browser retry.",
        "credits": {"pay": 5273, "refund": 1433, "net": 3840, "episode_cap": 10000, "headroom": 6160, "active": 0},
        "next_action": "Retry YouTube Studio control on the exact channel, verify visible account identity, upload the bound payload publicly and capture readback; then publish the bound Douyin payload and capture readback. Do not regenerate, recut, or repeat final QA unless master SHA changes.",
    }
    write_json(RECEIPT, receipt)

    status = "E37_PRODUCTION_COMPLETE_RELEASE_PACKAGE_COMPLETE_PLATFORM_SUBMISSION_RETRY_ACTIVE"
    blocked = "PLATFORM_SUBMISSION_ONLY:BROWSER_CONTROL_CHANNEL_TIMEOUT_NO_MEDIA_TRANSMITTED"
    next_action = "RETRY_EXACT_YOUTUBE_STUDIO_PUBLIC_SUBMISSION_THEN_DOUYIN; VERIFY_VISIBLE_ACCOUNT_IDENTITY_AND_CAPTURE_PLATFORM_READBACK; NO_REGENERATION_OR_QA_REPEAT_UNLESS_MASTER_SHA_CHANGES"
    queue = load(QUEUE)
    queue.update({"updated_at": timestamp, "status": status, "blocked_by": blocked, "next_action": next_action})
    line = queue.setdefault("lines", {}).setdefault("E37", {})
    line.update({
        "status": status,
        "current_phase": "Canonical and manifest remain exact-SHA locked. All 22 accepted-only native-video segments are admitted, AgentCut production master is rendered unchanged, full-cut visual/aHash/cadence/dialogue/OCR-adjudication gates pass, cleanRelease=true, and exact-SHA YouTube/Douyin public payloads are complete. Platform submission alone remains pending because both browser control surfaces timed out before file selection; zero media was transmitted.",
        "blocked_by": blocked,
        "canonical_script_sha256": SCRIPT_SHA,
        "canonical_manifest_sha256": MANIFEST_SHA,
        "running_or_pending_task_ids": [],
        "accepted_source_count": 22,
        "production_complete": True,
        "release_package_complete": True,
        "platform_submission_complete": False,
        "production_master": str(MASTER.relative_to(ROOT)),
        "production_master_sha256": MASTER_SHA,
        "latest_agentcut_release_validate": "qa/e37_agentcut_20260803/v1_accepted_only/E37_AGENTCUT_V1_RELEASE_VALIDATE_RAW.json",
        "latest_release_package": str(PACKAGE.relative_to(ROOT)),
        "latest_release_package_sha256": package_sha,
        "latest_platform_submission_receipt": str(RECEIPT.relative_to(ROOT)),
        "credits": "E37 source-attributable Pay5273/Refund1433/Net3840 of10000; headroom6160; active0",
        "next_action": next_action,
    })
    write_json(QUEUE, queue)

    task = load(TASK)
    task.update({
        "updated_at": timestamp,
        "status": status,
        "blocked_by": blocked,
        "next_action": next_action,
        "active_task_ids": [],
        "real_active_handle_count": 0,
        "accepted_source_count": 22,
        "production_complete": True,
        "release_package_complete": True,
        "platform_submission_complete": False,
        "production_master": str(MASTER.relative_to(ROOT)),
        "production_master_sha256": MASTER_SHA,
        "latest_release_package": str(PACKAGE.relative_to(ROOT)),
        "latest_release_package_sha256": package_sha,
        "latest_platform_submission_receipt": str(RECEIPT.relative_to(ROOT)),
        "credits": {"pay": 5273, "refund": 1433, "net": 3840, "episode_cap": 10000, "headroom": 6160},
    })
    write_json(TASK, task)
    print(json.dumps({"status": status, "receipt": str(RECEIPT.relative_to(ROOT)), "receipt_sha256": sha256(RECEIPT), "package_sha256": package_sha}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
