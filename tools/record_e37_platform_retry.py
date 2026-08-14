#!/usr/bin/env python3
"""Record a fail-closed E37 platform retry and refresh release state."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "workflow/work_queue.json"
TASK = ROOT / "workflow/tasks/E37_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
MAILBOX = ROOT / "workflow/CODEX_TO_CLAUDE.md"
PACKAGE = ROOT / "workflow/releases/E37_RELEASE_PACKAGE_FINAL_V1_20260803.json"
RECEIPT = ROOT / "workflow/releases/E37_PLATFORM_SUBMISSION_BROWSER_CONTROL_RETRY_V6_20260803.json"
PAYLOAD = ROOT / "working_assets/e37_release_prep_20260803/platform_payload_v1"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E37剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E37_manifest_v2.json"
MASTER = ROOT / "exports/e37/agentcut_v1_accepted_only_20260803/E37_AGENTCUT_V1_ACCEPTED_ONLY_PRODUCTION_CANDIDATE.mp4"

EXPECTED = {
    SCRIPT: "07a63a0c286be656feac59a0f31ea1bb159f3f7ce56f1172bb202832edf9db3a",
    MANIFEST: "9082f9d3b45bf0466476e98cb194d91d00d6775c2b762b5253c8f7557d31c33e",
    MASTER: "8a6559bdd19ca1862b580eb35ace00bf2060add58199db20d4cdd9f3c545d76b",
}
MAILBOX_SHA = "70c50d5c57b83eb324721ef9b3e71772e48938cca229e3a86a995fea09d38e01"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected object: {path}")
    return value


def write_json(path: Path, value: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    os.replace(tmp, path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def payload_preflight() -> list[dict]:
    expected_lines = (PAYLOAD / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines()
    expected_sums = {}
    for line in expected_lines:
        digest, rel = line.split("  ", 1)
        expected_sums[rel] = digest

    results = []
    for rel, expected in sorted(expected_sums.items()):
        path = PAYLOAD / rel
        actual = sha256(path)
        results.append({
            "path": str(path.relative_to(ROOT)),
            "sha256": actual,
            "bytes": path.stat().st_size,
            "status": "PASS" if actual == expected else "FAIL",
        })
    if not results or any(item["status"] != "PASS" for item in results):
        raise RuntimeError("Platform payload checksum preflight failed")
    for rel in ("youtube_full/video.mp4", "douyin_full/video.mp4"):
        if sha256(PAYLOAD / rel) != EXPECTED[MASTER]:
            raise RuntimeError(f"Platform video is not exact master bytes: {rel}")
    return results


def main() -> int:
    for path, expected in EXPECTED.items():
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"Exact-SHA gate failed for {path}: {actual}")

    package = load(PACKAGE)
    if package.get("production_complete") is not True or package.get("release_package_complete") is not True:
        raise RuntimeError("Release package is not complete")
    if package.get("platform_submission_complete") is not False:
        raise RuntimeError("Platform state is not pending")

    now = utc_now()
    preflight = payload_preflight()
    package_sha = sha256(PACKAGE)
    receipt = {
        "schema": "qingshan.e37.platform_submission_browser_control_retry.v6",
        "episode": "E37",
        "generated_at": now,
        "status": "PLATFORM_SUBMISSION_RETRY_BLOCKED_BEFORE_MEDIA_SELECTION",
        "source_cl2x": "CL2X-936 + AUTOMATION_E37_HEARTBEAT_20260803T085444Z",
        "canonical": {
            "script_sha256": EXPECTED[SCRIPT],
            "manifest_sha256": EXPECTED[MANIFEST],
            "status": "PASS_EXACT_SHA",
        },
        "release_package": {
            "path": str(PACKAGE.relative_to(ROOT)),
            "sha256": package_sha,
            "production_complete": True,
            "release_package_complete": True,
        },
        "master_sha256": EXPECTED[MASTER],
        "payload_preflight": {
            "status": f"PASS_{len(preflight)}_OF_{len(preflight)}_FILES_EXACT_SHA",
            "files": preflight,
        },
        "attempts": [
            {
                "surface": "Codex in-app browser",
                "target": "https://studio.youtube.com/channel/UCU4dycBEqXgiqEIjSg9zBmQ",
                "visible_target_discovery": "PASS_CHANNEL_DASHBOARD_TITLE_AND_EXACT_CHANNEL_URL",
                "control_result": "FAIL_EXISTING_EXACT_CHANNEL_TAB_CLAIM_TIMEOUT_BEFORE_UPLOAD_UI",
                "media_selected": False,
                "media_transmitted": False,
                "platform_mutation": False,
            },
            {
                "surface": "Chrome extension browser",
                "visible_target_discovery": "PASS_EXTENSION_CONNECTED_GIGGLE_TAB_ONLY_ON_FRESH_ENUMERATION",
                "control_result": "FAIL_FRESH_TAB_CREATION_TIMEOUT_BEFORE_YOUTUBE_NAVIGATION",
                "media_selected": False,
                "media_transmitted": False,
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
        "blocked_by": "PLATFORM_SUBMISSION_ONLY:BROWSER_ACTION_CHANNEL_TIMEOUT_NO_MEDIA_TRANSMITTED",
        "workaround_executed": "Freshly enumerated the exact signed-in YouTube Studio tab and retried its claim in the in-app browser, then independently enumerated Chrome and attempted a new publication tab. Both control actions timed out before the upload UI or file selection, so zero media was transmitted. Revalidated every YouTube and Douyin payload file against the immutable checksum manifest to keep the release payload directly upload-ready.",
        "credits": {"pay": 5273, "refund": 1433, "net": 3840, "episode_cap": 10000, "headroom": 6160, "active": 0},
        "next_action": "On the next heartbeat, retry YouTube Studio tab claim first; once healthy, verify channel UCU4dycBEqXgiqEIjSg9zBmQ, upload exact video bytes publicly and capture readback, then publish the exact Douyin payload to account 45198541560. Keep automation e37 active.",
    }
    write_json(RECEIPT, receipt)
    receipt_sha = sha256(RECEIPT)

    status = "E37_PRODUCTION_COMPLETE_RELEASE_PACKAGE_COMPLETE_PLATFORM_SUBMISSION_RETRY_ACTIVE"
    blocked = receipt["blocked_by"]
    next_action = "RETRY_YOUTUBE_STUDIO_CONTROL_THEN_PUBLIC_UPLOAD_AND_READBACK; THEN_DOUYIN_PUBLIC_UPLOAD_AND_READBACK; KEEP_AUTOMATION_E37_ACTIVE"
    queue = load(QUEUE)
    queue.update({"updated_at": now, "status": status, "blocked_by": blocked, "next_action": next_action})
    line = queue.setdefault("lines", {}).setdefault("E37", {})
    line.update({
        "status": status,
        "current_phase": "E37 production and exact-SHA dual-platform package remain complete. A fresh post-recovery retry found both browser surfaces discoverable but their first control action timed out before file selection; zero media was transmitted. All eight payload files were revalidated exact-SHA and remain directly upload-ready.",
        "blocked_by": blocked,
        "running_or_pending_task_ids": [],
        "production_complete": True,
        "release_package_complete": True,
        "platform_submission_complete": False,
        "latest_platform_submission_receipt": str(RECEIPT.relative_to(ROOT)),
        "next_action": next_action,
    })
    write_json(QUEUE, queue)

    task = load(TASK)
    task.update({
        "updated_at": now,
        "status": status,
        "blocked_by": blocked,
        "workaround_executed": receipt["workaround_executed"],
        "next_action": next_action,
        "active_task_ids": [],
        "real_active_handle_count": 0,
        "production_complete": True,
        "release_package_complete": True,
        "platform_submission_complete": False,
        "latest_platform_submission_receipt": str(RECEIPT.relative_to(ROOT)),
    })
    write_json(TASK, task)

    mailbox_entry = f"""\n\nX2CL-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}-BROWSER-RETRY-V6
- source_cl2x: CL2X-936 + AUTOMATION_E37_HEARTBEAT_20260803T085444Z
- source_mailbox_sha256: {MAILBOX_SHA}
- blocked_by: {blocked}
- workaround_executed: {receipt['workaround_executed']}
- artifacts:
  - {RECEIPT.relative_to(ROOT)} sha256={receipt_sha}
  - {PACKAGE.relative_to(ROOT)} sha256={package_sha}
  - {PAYLOAD.relative_to(ROOT) / 'SHA256SUMS.txt'} sha256={sha256(PAYLOAD / 'SHA256SUMS.txt')}
  - workflow/work_queue.json sha256={sha256(QUEUE)}
  - workflow/tasks/E37_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json sha256={sha256(TASK)}
- gate_results: canonical_script=PASS_EXACT_SHA_07a63a0c;canonical_manifest=PASS_EXACT_SHA_9082f9d3;production_complete=PASS;release_package_complete=PASS;payload_checksum=PASS_{len(preflight)}_OF_{len(preflight)};youtube_target_discovery=PASS_EXACT_CHANNEL_DASHBOARD_FRESH_ENUMERATION;in_app_browser_control=FAIL_CLAIM_TIMEOUT_BEFORE_FILE_SELECTION;chrome_target_discovery=PASS_EXTENSION_CONNECTED_GIGGLE_ONLY;chrome_control=FAIL_NEW_TAB_TIMEOUT_BEFORE_NAVIGATION;youtube_submission=NOT_STARTED_ZERO_MEDIA_TRANSMITTED;douyin_submission=NOT_STARTED_ZERO_MEDIA_TRANSMITTED;platform_mutation=NONE;s3_relay=NONE;active_processes=PASS_ZERO_RELEVANT;automation_e37=PASS_CONTINUES
- credits: Pay0/Refund0/Net0 this heartbeat; cumulative E37 source-attributable Pay5273/Refund1433/Net3840 of10000; headroom6160; active0
- next_action: {receipt['next_action']}
"""
    with MAILBOX.open("a", encoding="utf-8") as stream:
        stream.write(mailbox_entry)

    print(json.dumps({
        "status": status,
        "receipt": str(RECEIPT.relative_to(ROOT)),
        "receipt_sha256": receipt_sha,
        "payload_files_passed": len(preflight),
        "queue_sha256": sha256(QUEUE),
        "task_sha256": sha256(TASK),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
