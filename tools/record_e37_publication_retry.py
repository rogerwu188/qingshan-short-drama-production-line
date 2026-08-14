#!/usr/bin/env python3
"""Record an E37 dual-platform publication retry without losing draft state."""

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
DRAFT_RECEIPT = ROOT / "workflow/releases/E37_YOUTUBE_DRAFT_UPLOAD_RECEIPT_V1_20260803.json"
RECEIPT = ROOT / "workflow/releases/E37_YOUTUBE_PUBLICATION_DOUYIN_SUBMISSION_RETRY_V3_20260803.json"
PAYLOAD = ROOT / "working_assets/e37_release_prep_20260803/platform_payload_v1"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E37剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E37_manifest_v2.json"
MASTER = ROOT / "exports/e37/agentcut_v1_accepted_only_20260803/E37_AGENTCUT_V1_ACCEPTED_ONLY_PRODUCTION_CANDIDATE.mp4"

EXPECTED = {
    SCRIPT: "07a63a0c286be656feac59a0f31ea1bb159f3f7ce56f1172bb202832edf9db3a",
    MANIFEST: "9082f9d3b45bf0466476e98cb194d91d00d6775c2b762b5253c8f7557d31c33e",
    MASTER: "8a6559bdd19ca1862b580eb35ace00bf2060add58199db20d4cdd9f3c545d76b",
    PACKAGE: "3441d923e3d4bd76fe00d0f601ba8e2bffe6a352e041888f9510df0c78618673",
    DRAFT_RECEIPT: "66707eb1d917ecad64d746f6d7f376ed1473df7c8e17f456609f39d6a32c07b2",
}


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


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def preflight() -> list[dict]:
    results = []
    for line in (PAYLOAD / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        expected, rel = line.split("  ", 1)
        path = PAYLOAD / rel
        actual = sha256(path)
        results.append({"path": rel, "sha256": actual, "status": "PASS" if actual == expected else "FAIL"})
    if not results or any(item["status"] != "PASS" for item in results):
        raise RuntimeError("Payload preflight failed")
    for rel in ("youtube_full/video.mp4", "douyin_full/video.mp4"):
        if sha256(PAYLOAD / rel) != EXPECTED[MASTER]:
            raise RuntimeError(f"Payload is not exact master: {rel}")
    return results


def main() -> int:
    for path, expected in EXPECTED.items():
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"Exact SHA mismatch for {path}: {actual}")

    now = now_utc()
    checked = preflight()
    status = "E37_PRODUCTION_COMPLETE_RELEASE_PACKAGE_COMPLETE_YOUTUBE_DRAFT_UPLOADED_PUBLICATION_AND_DOUYIN_RETRY_ACTIVE"
    blocked = "PLATFORM_SUBMISSION_ONLY:YOUTUBE_DRAFT_FINAL_PUBLICATION_CONTROL_TIMEOUT;DOUYIN_UPLOAD_PAGE_CONTROL_TIMEOUT"
    next_action = "Retry exact YouTube draft nfzySvwFgXg final PUBLIC action and capture public readback; independently resume the exact Douyin upload page and submit to account 45198541560; keep automation e37 active."
    workaround = (
        "Enumerated the existing signed-in YouTube Studio channel dashboard for UCU4dycBEqXgiqEIjSg9zBmQ and attempted to claim it for the exact draft publication path; control timed out before a safe unique Publish action could be observed, so no duplicate upload or metadata mutation occurred. "
        "Independently created a fresh browser tab for the direct Douyin Creator upload URL; the tab was created successfully but navigation timed out and the transient tab was absent on readback before file selection. "
        "Tried the connected Chrome extension as a second control surface after the in-app browser failures; the connection initialized but timed out while naming the release session and listing tabs, before navigation or any platform mutation. "
        "Preserved the existing exact-SHA YouTube draft and its video id, independently reprobed the public watch page as still private, and reran all eight YouTube/Douyin payload checksums with both platform videos byte-identical to the production master."
    )
    receipt = {
        "schema": "qingshan.e37.youtube_publication_douyin_submission_retry.v3",
        "episode": "E37",
        "generated_at": now,
        "status": "PUBLICATION_RETRY_ACTIVE_NO_DUPLICATE_UPLOAD",
        "source_cl2x": "CL2X-936 + AUTOMATION_E37_HEARTBEAT_20260803T094451Z",
        "canonical": {
            "script_sha256": EXPECTED[SCRIPT],
            "manifest_sha256": EXPECTED[MANIFEST],
            "status": "PASS_EXACT_SHA",
        },
        "production_master_sha256": EXPECTED[MASTER],
        "release_package": {"path": str(PACKAGE.relative_to(ROOT)), "sha256": EXPECTED[PACKAGE]},
        "youtube_draft_receipt": {"path": str(DRAFT_RECEIPT.relative_to(ROOT)), "sha256": EXPECTED[DRAFT_RECEIPT]},
        "payload_preflight": {"status": f"PASS_{len(checked)}_OF_{len(checked)}", "files": checked},
        "youtube": {
            "channel_id": "UCU4dycBEqXgiqEIjSg9zBmQ",
            "video_id": "nfzySvwFgXg",
            "shorts_url": "https://youtube.com/shorts/nfzySvwFgXg",
            "draft": "PASS_PRESERVED_EXACT_UPLOAD",
            "retry": "FAIL_CONTROL_TIMEOUT_BEFORE_SAFE_UNIQUE_PUBLISH_ACTION",
            "public_probe": "FAIL_PRESERVED_LOGIN_REQUIRED_THIS_IS_A_PRIVATE_VIDEO",
            "duplicate_upload": False,
        },
        "douyin": {
            "account": "迷雾剧场·AI连载",
            "douyin_id": "45198541560",
            "target": "https://creator.douyin.com/creator-micro/content/upload",
            "retry": "FAIL_CONTROL_TIMEOUT_BEFORE_FILE_SELECTION",
            "media_selected": False,
            "media_transmitted": False,
        },
        "blocked_by": blocked,
        "workaround_executed": workaround,
        "credits": {"pay": 5273, "refund": 1433, "net": 3840, "episode_cap": 10000, "headroom": 6160, "active": 0},
        "next_action": next_action,
    }
    write_json(RECEIPT, receipt)
    receipt_sha = sha256(RECEIPT)

    queue = load(QUEUE)
    queue.update({"updated_at": now, "status": status, "blocked_by": blocked, "next_action": next_action})
    line = queue.setdefault("lines", {}).setdefault("E37", {})
    line.update({
        "status": status,
        "current_phase": "Production and release package complete; exact YouTube draft nfzySvwFgXg preserved. Fresh final-publication and independent Douyin-upload control retries timed out before additional platform mutation; exact payloads remain verified and ready.",
        "blocked_by": blocked,
        "running_or_pending_task_ids": [],
        "production_complete": True,
        "release_package_complete": True,
        "platform_submission_complete": False,
        "youtube_submission": "DRAFT_UPLOAD_COMPLETE_PRIVATE_PUBLICATION_RETRY_ACTIVE",
        "douyin_submission": "NOT_STARTED_UPLOAD_PAGE_CONTROL_RETRY_ACTIVE",
        "latest_platform_submission_receipt": str(RECEIPT.relative_to(ROOT)),
        "next_action": next_action,
    })
    write_json(QUEUE, queue)

    task = load(TASK)
    task.update({
        "updated_at": now,
        "status": status,
        "blocked_by": blocked,
        "workaround_executed": workaround,
        "next_action": next_action,
        "active_task_ids": [],
        "real_active_handle_count": 0,
        "production_complete": True,
        "release_package_complete": True,
        "platform_submission_complete": False,
        "youtube_submission": "DRAFT_UPLOAD_COMPLETE_PRIVATE_PUBLICATION_RETRY_ACTIVE",
        "douyin_submission": "NOT_STARTED_UPLOAD_PAGE_CONTROL_RETRY_ACTIVE",
        "latest_platform_submission_receipt": str(RECEIPT.relative_to(ROOT)),
    })
    write_json(TASK, task)

    entry = f"""

X2CL-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}-PUBLICATION-RETRY-V3
- source_cl2x: CL2X-936 + AUTOMATION_E37_HEARTBEAT_20260803T094451Z
- blocked_by: {blocked}
- workaround_executed: {workaround}
- artifacts:
  - {RECEIPT.relative_to(ROOT)} sha256={receipt_sha}
  - {DRAFT_RECEIPT.relative_to(ROOT)} sha256={EXPECTED[DRAFT_RECEIPT]}
  - {PACKAGE.relative_to(ROOT)} sha256={EXPECTED[PACKAGE]}
  - {PAYLOAD.relative_to(ROOT) / 'youtube_full/video.mp4'} sha256={sha256(PAYLOAD / 'youtube_full/video.mp4')}
  - {PAYLOAD.relative_to(ROOT) / 'douyin_full/video.mp4'} sha256={sha256(PAYLOAD / 'douyin_full/video.mp4')}
  - {PAYLOAD.relative_to(ROOT) / 'SHA256SUMS.txt'} sha256={sha256(PAYLOAD / 'SHA256SUMS.txt')}
  - workflow/work_queue.json sha256={sha256(QUEUE)}
  - workflow/tasks/E37_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json sha256={sha256(TASK)}
- gate_results: canonical_script=PASS_EXACT_SHA_07a63a0c;canonical_manifest=PASS_EXACT_SHA_9082f9d3;production_complete=PASS;release_package_complete=PASS;payload_checksum=PASS_{len(checked)}_OF_{len(checked)};youtube_draft=PASS_PRESERVED_VIDEO_ID_nfzySvwFgXg;youtube_duplicate_upload=NONE;youtube_public_probe=FAIL_PRESERVED_PRIVATE;youtube_publication_retry=FAIL_CONTROL_TIMEOUT_BEFORE_SAFE_UNIQUE_PUBLISH;douyin_retry=FAIL_CONTROL_TIMEOUT_BEFORE_FILE_SELECTION;platform_submission_complete=FALSE;s3_relay=NONE;automation_e37=PASS_CONTINUES
- credits: Pay0/Refund0/Net0 this heartbeat; cumulative E37 source-attributable Pay5273/Refund1433/Net3840 of10000; headroom6160; active0
- next_action: {next_action}
"""
    with MAILBOX.open("a", encoding="utf-8") as stream:
        stream.write(entry)

    print(json.dumps({
        "status": status,
        "receipt": str(RECEIPT.relative_to(ROOT)),
        "receipt_sha256": receipt_sha,
        "payload_files_passed": len(checked),
        "queue_sha256": sha256(QUEUE),
        "task_sha256": sha256(TASK),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
