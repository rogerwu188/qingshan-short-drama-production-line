#!/usr/bin/env python3
"""Record direct overview adjudication and publish V23 review-package state."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CL2X = "CL2X-924"
MAILBOX_SHA = "1421e83dd9e802c1a16eaf57df6c757f761d227c6578e85891b35ddb1834e8f7"
CANONICAL_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"
VIDEO_SHA = "89af22464112ec0be2da1fdd8897fd35f46d37cb40c19342422dcd76bb118a83"
VIDEO = ROOT / "working_assets/e36_agentcut_20260801/accepted_only_v23_canonical_dialogue_order/E36_ACCEPTED_ONLY_AGENTCUT_V23_CANONICAL_DIALOGUE_ORDER.mp4"
QA = ROOT / "qa/e36_agentcut_20260730/E36_V23_BOUNDED_NATIVE_SPEED_REVIEW_PACKAGES_QA_V1.json"
WQ = ROOT / "workflow/work_queue.json"
DISPATCH = ROOT / "workflow/tasks/E36_AUTONOMOUS_FOCUSED_CONCURRENT_DISPATCH_V1.json"
RECEIPT = ROOT / "workflow/CODEX_TO_CLAUDE.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_json(path: Path, payload: dict) -> None:
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(name, path)
    except Exception:
        Path(name).unlink(missing_ok=True)
        raise


def main() -> None:
    mailbox = ROOT / "codex_docs/CLAUDE_TO_CODEX.md"
    canonical = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
    manifest_path = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
    manifest = load(manifest_path)
    if sha256(mailbox) != MAILBOX_SHA:
        raise RuntimeError("Mailbox changed")
    if sha256(canonical) != CANONICAL_SHA or manifest.get("sha256") != CANONICAL_SHA:
        raise RuntimeError("Canonical mismatch")
    if sha256(VIDEO) != VIDEO_SHA:
        raise RuntimeError("V23 changed")
    qa = load(QA)
    if qa.get("status") != "PASS_FIVE_CONTIGUOUS_NATIVE_SPEED_REVIEW_PACKAGES_FULL_UNINTERRUPTED_WATCH_NOT_COMPLETE":
        raise RuntimeError("Review package build did not pass")
    if qa["coverage_integrity"].get("package_video_frames_sum") != 7053:
        raise RuntimeError("Frame coverage mismatch")
    if any(row.get("full_decode") != "PASS_ZERO_ERRORS" for row in qa["review_packages"]):
        raise RuntimeError("Review package decode failure")

    qa["direct_visual_review"].update({
        "sampling": "PASS_98_ORDERED_REPRESENTATIVE_SAMPLES_ACROSS_FULL_RUNTIME",
        "identity_age_period_weather": "PASS_REPRESENTATIVE_SAMPLES",
        "causal_order": "PASS_REPRESENTATIVE_SAMPLES",
        "critical_generated_text": "PASS_REPRESENTATIVE_SAMPLES_NO_NEW_CRITICAL_TEXT_OBSERVED",
        "malformed_frames": "PASS_ZERO_OBSERVED_IN_98_SAMPLES",
    })
    qa["gate_results"]["ordered_direct_visual_samples"] = "PASS_98_ACROSS_FULL_RUNTIME"
    atomic_json(QA, qa)
    qa_sha = sha256(QA)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    blocked = qa["blocked_by"]
    next_action = "Use all five contiguous V23 native-speed reels for uninterrupted audiovisual review and continue materially distinct zero-credit source-native recovery for lines4/5/11/12/23/24/27/28; keep V15 canonical and release closed."
    workaround = "Rendered five contiguous V23 native-speed audiovisual reels concurrently, full-decoded all5, verified exact7053/7053 frame coverage with zero timeline gaps or overlaps, generated98 ordered full-runtime samples, and directly inspected the overview with zero severe malformed-frame, identity, period, weather, causal-order, or new critical-text contradiction observed. The representative samples do not clear uninterrupted audiovisual watching."
    note = "V23 now has five contiguous native-speed audiovisual review reels spanning0-293.942646s. All5 fully decode and jointly cover7053/7053 frames;98 ordered overview samples pass representative visual review. Continuous native-speed audiovisual watching and transcript39/47 remain open; V15 stays canonical."
    review_pointer = {"path": rel(QA), "sha256": qa_sha, "status": qa["status"], "directory": "working_assets/e36_agentcut_20260801/v23_bounded_watch_packages_v1"}

    for path in (WQ, DISPATCH):
        payload = load(path)
        payload.update({
            "status": "E36_CL2X924_V23_REVIEW_PACKAGES_READY_FULL_WATCH_ACTIVE",
            "updated_at": now,
            "source_cl2x": SOURCE_CL2X,
            "source_mailbox_sha256": MAILBOX_SHA,
            "updated_note_latest": note,
            "blocked_by": blocked,
            "next_action": next_action,
            "latest_v23_bounded_native_speed_review_packages": review_pointer,
            "latest_cl2x924_v23_review_packages": note,
            "workaround_executed": workaround,
        })
        if path == WQ:
            e36 = payload.setdefault("lines", {}).setdefault("E36", {})
            e36.update({
                "status": payload["status"],
                "current_phase": note,
                "updated_at": now,
                "source_cl2x": SOURCE_CL2X,
                "source_mailbox_sha256": MAILBOX_SHA,
                "blocked_by": blocked,
                "next_action": next_action,
                "latest_v23_bounded_native_speed_review_packages": review_pointer,
                "latest_cl2x924_v23_review_packages": note,
            })
        atomic_json(path, payload)

    artifacts = []
    for row in qa["review_packages"]:
        artifacts.append(f"  - {row['reel']} sha256={row['reel_sha256']}")
        artifacts.append(f"  - {row['contact_sheet']} sha256={row['contact_sheet_sha256']}")
    artifacts.append(f"  - {qa['direct_visual_review']['overview']} sha256={qa['direct_visual_review']['overview_sha256']}")
    artifacts.append(f"  - {rel(QA)} sha256={qa_sha}")
    receipt = f"""
X2CL-20260801-1406
- source_cl2x: {SOURCE_CL2X}
- source_mailbox_sha256: {MAILBOX_SHA}
- blocked_by: {blocked}
- workaround_executed: {workaround}
- artifacts:
{chr(10).join(artifacts)}
- gate_results: canonical_script_manifest=PASS_EXACT; bounded_review_media=PASS_5_OF_5_CONTIGUOUS_PACKAGES_293P942646_SECONDS; video_frame_coverage=PASS_7053_OF_7053; bounded_media_full_decode=PASS_5_OF_5_ZERO_ERRORS; ordered_direct_visual_samples=PASS_98_ACROSS_FULL_RUNTIME; continuous_full_runtime_human_watch=NOT_COMPLETE; transcript=HOLD_39_OF_47; motion=PASS_30_OF_30; V23_promotion=NOT_GRANTED_KEEP_V15_CANONICAL; release=HOLD; platform_action=NONE
- credits: Pay0 / Refund0 / Net0 this action; episode source-attributable Net9976/10000; refunds3084 separate; headroom24; calls135; active0
- next_action: {next_action}
"""
    with RECEIPT.open("a", encoding="utf-8") as handle:
        handle.write(receipt)
    print(json.dumps({"status": "PASS", "qa": rel(QA), "qa_sha256": qa_sha, "updated_at": now}, ensure_ascii=False))


if __name__ == "__main__":
    main()
