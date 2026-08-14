#!/usr/bin/env python3
"""Record the exact E37 YouTube draft upload and keep publication retries active."""

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
RECEIPT = ROOT / "workflow/releases/E37_YOUTUBE_DRAFT_UPLOAD_RECEIPT_V1_20260803.json"
PAYLOAD = ROOT / "working_assets/e37_release_prep_20260803/platform_payload_v1"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E37剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E37_manifest_v2.json"
MASTER = ROOT / "exports/e37/agentcut_v1_accepted_only_20260803/E37_AGENTCUT_V1_ACCEPTED_ONLY_PRODUCTION_CANDIDATE.mp4"

EXPECTED = {
    SCRIPT: "07a63a0c286be656feac59a0f31ea1bb159f3f7ce56f1172bb202832edf9db3a",
    MANIFEST: "9082f9d3b45bf0466476e98cb194d91d00d6775c2b762b5253c8f7557d31c33e",
    MASTER: "8a6559bdd19ca1862b580eb35ace00bf2060add58199db20d4cdd9f3c545d76b",
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def payload_preflight() -> list[dict]:
    expected_sums = {}
    for line in (PAYLOAD / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
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
    if sha256(PAYLOAD / "youtube_full/video.mp4") != EXPECTED[MASTER]:
        raise RuntimeError("YouTube payload is not exact master bytes")
    return results


def main() -> int:
    for path, expected in EXPECTED.items():
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"Exact-SHA gate failed for {path}: {actual}")

    package = load(PACKAGE)
    if package.get("production_complete") is not True:
        raise RuntimeError("Production is not complete")
    if package.get("release_package_complete") is not True:
        raise RuntimeError("Release package is not complete")

    now = utc_now()
    preflight = payload_preflight()
    package_sha = sha256(PACKAGE)
    blocked = "PLATFORM_SUBMISSION_ONLY:YOUTUBE_DRAFT_FINAL_PUBLICATION_CONTROL_TIMEOUT;DOUYIN_PUBLIC_SUBMISSION_PENDING"
    next_action = "Resume exact YouTube draft nfzySvwFgXg, publish PUBLIC and capture public readback; then upload and publish the exact Douyin payload to account 45198541560. Keep automation e37 active."
    workaround = (
        "Recovered the exact signed-in YouTube channel and completed the previously blocked media transmission: "
        "the exact-SHA 47 MB E37 master was uploaded, title and canonical description were saved, audience was set "
        "to not made for kids, YouTube reported upload complete and no copyright issue, and video id nfzySvwFgXg "
        "was created. The draft workflow reached Visibility with Public selected, but the final Publish control became "
        "unresponsive before authoritative public readback. Verified independently that the watch page still reports "
        "the video private, so no false release claim is made. Opened the exact Studio draft edit URL and confirmed "
        "the title, 2:57 duration, filename video.mp4, not-made-for-kids setting, exact Shorts URL, and explicit draft state."
    )
    receipt = {
        "schema": "qingshan.e37.youtube_draft_upload_receipt.v1",
        "episode": "E37",
        "generated_at": now,
        "status": "YOUTUBE_DRAFT_UPLOAD_COMPLETE_PUBLICATION_PENDING",
        "source_cl2x": "CL2X-936 + AUTOMATION_E37_HEARTBEAT_20260803T090514Z",
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
        "youtube": {
            "account": "拉努影业 Nalu Motion Picture / @NaluMotion-P",
            "channel_id": "UCU4dycBEqXgiqEIjSg9zBmQ",
            "payload": "working_assets/e37_release_prep_20260803/platform_payload_v1/youtube_full/video.mp4",
            "payload_sha256": EXPECTED[MASTER],
            "title": "青山 EP37：刘家余波｜灭门三年，谁还在领看守银？",
            "video_id": "nfzySvwFgXg",
            "studio_edit_url": "https://studio.youtube.com/video/nfzySvwFgXg/edit",
            "shorts_url": "https://youtube.com/shorts/nfzySvwFgXg",
            "duration": "2:57",
            "audience": "NOT_MADE_FOR_KIDS",
            "upload": "PASS_COMPLETE",
            "copyright": "PASS_NO_ISSUES_FOUND",
            "media_selected": True,
            "media_transmitted": True,
            "draft_created": True,
            "visibility_intent": "PUBLIC_SELECTED_IN_DRAFT_WORKFLOW",
            "authoritative_current_visibility": "PRIVATE_DRAFT",
            "public_readback": False,
            "independent_watch_page_probe": "LOGIN_REQUIRED_THIS_IS_A_PRIVATE_VIDEO",
        },
        "douyin": {
            "account": "迷雾剧场·AI连载",
            "douyin_id": "45198541560",
            "payload": "working_assets/e37_release_prep_20260803/platform_payload_v1/douyin_full/video.mp4",
            "submission": "NOT_STARTED_PENDING_YOUTUBE_PUBLIC_READBACK",
        },
        "blocked_by": blocked,
        "workaround_executed": workaround,
        "credits": {"pay": 5273, "refund": 1433, "net": 3840, "episode_cap": 10000, "headroom": 6160, "active": 0},
        "next_action": next_action,
    }
    write_json(RECEIPT, receipt)
    receipt_sha = sha256(RECEIPT)

    status = "E37_PRODUCTION_COMPLETE_RELEASE_PACKAGE_COMPLETE_YOUTUBE_DRAFT_UPLOADED_PUBLICATION_RETRY_ACTIVE"
    queue = load(QUEUE)
    queue.update({"updated_at": now, "status": status, "blocked_by": blocked, "next_action": next_action})
    line = queue.setdefault("lines", {}).setdefault("E37", {})
    line.update({
        "status": status,
        "current_phase": "Production and release package are complete. Exact E37 master is uploaded to the bound YouTube channel as private draft nfzySvwFgXg with canonical metadata; final public readback and Douyin submission remain open.",
        "blocked_by": blocked,
        "running_or_pending_task_ids": [],
        "production_complete": True,
        "release_package_complete": True,
        "platform_submission_complete": False,
        "youtube_submission": "DRAFT_UPLOAD_COMPLETE_PRIVATE_PUBLICATION_PENDING",
        "youtube_video_id": "nfzySvwFgXg",
        "youtube_shorts_url": "https://youtube.com/shorts/nfzySvwFgXg",
        "douyin_submission": "NOT_STARTED_PENDING_YOUTUBE_PUBLIC_READBACK",
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
        "youtube_submission": "DRAFT_UPLOAD_COMPLETE_PRIVATE_PUBLICATION_PENDING",
        "youtube_video_id": "nfzySvwFgXg",
        "youtube_shorts_url": "https://youtube.com/shorts/nfzySvwFgXg",
        "douyin_submission": "NOT_STARTED_PENDING_YOUTUBE_PUBLIC_READBACK",
        "latest_platform_submission_receipt": str(RECEIPT.relative_to(ROOT)),
    })
    write_json(TASK, task)

    mailbox_entry = f"""

X2CL-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M')}-YOUTUBE-DRAFT-UPLOAD-V1
- source_cl2x: CL2X-936 + AUTOMATION_E37_HEARTBEAT_20260803T090514Z
- blocked_by: {blocked}
- workaround_executed: {workaround}
- artifacts:
  - {RECEIPT.relative_to(ROOT)} sha256={receipt_sha}
  - {PACKAGE.relative_to(ROOT)} sha256={package_sha}
  - {PAYLOAD.relative_to(ROOT) / 'youtube_full/video.mp4'} sha256={sha256(PAYLOAD / 'youtube_full/video.mp4')}
  - {PAYLOAD.relative_to(ROOT) / 'SHA256SUMS.txt'} sha256={sha256(PAYLOAD / 'SHA256SUMS.txt')}
  - workflow/work_queue.json sha256={sha256(QUEUE)}
  - workflow/tasks/E37_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json sha256={sha256(TASK)}
- gate_results: canonical_script=PASS_EXACT_SHA_07a63a0c;canonical_manifest=PASS_EXACT_SHA_9082f9d3;production_complete=PASS;release_package_complete=PASS;payload_checksum=PASS_{len(preflight)}_OF_{len(preflight)};youtube_channel=PASS_EXACT_UCU4dycBEqXgiqEIjSg9zBmQ;youtube_media_transmission=PASS_EXACT_MASTER_SHA;youtube_upload=PASS_COMPLETE;youtube_metadata=PASS_TITLE_DESCRIPTION_AUDIENCE;youtube_copyright=PASS_NO_ISSUES_FOUND;youtube_draft_readback=PASS_VIDEO_ID_nfzySvwFgXg;youtube_public_readback=FAIL_PRESERVED_PRIVATE_DRAFT;douyin_submission=NOT_STARTED_PENDING_YOUTUBE_PUBLIC_READBACK;platform_submission_complete=FALSE;s3_relay=NONE;automation_e37=PASS_CONTINUES
- credits: Pay0/Refund0/Net0 this heartbeat; cumulative E37 source-attributable Pay5273/Refund1433/Net3840 of10000; headroom6160; active0
- next_action: {next_action}
"""
    with MAILBOX.open("a", encoding="utf-8") as stream:
        stream.write(mailbox_entry)

    print(json.dumps({
        "status": status,
        "receipt": str(RECEIPT.relative_to(ROOT)),
        "receipt_sha256": receipt_sha,
        "youtube_video_id": "nfzySvwFgXg",
        "queue_sha256": sha256(QUEUE),
        "task_sha256": sha256(TASK),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
