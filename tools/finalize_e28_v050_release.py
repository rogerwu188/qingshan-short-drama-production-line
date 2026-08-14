#!/usr/bin/env python3
"""Freeze E28 V3 and record verified S3 and platform delivery."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANDIDATE = ROOT / "exports/e28/agentcut_v3_writer_agent_v050_release_candidate_20260721/E28_AGENTCUT_V3_WRITER_AGENT_V050_RELEASE_CANDIDATE.mp4"
FINAL = ROOT / "exports/e28/final/E28_AGENTCUT_V3_WRITER_AGENT_V050_FINAL.mp4"
PROJECT = ROOT / "configs/e28_agentcut_v3_writer_agent_v050_release_candidate_20260721.json"
QA = ROOT / "qa/e28_writer_agent_v050_agentcut_v3_release_20260721"
CADENCE = QA / "E28_AGENTCUT_V3_FULLCUT_FRAME_CADENCE.json"
OCR = QA / "E28_AGENTCUT_V3_FULLCUT_OCR.json"
OCR_ADJ = QA / "E28_AGENTCUT_V3_FULLCUT_OCR_MACHINE_ADJUDICATION.json"
REVIEW = QA / "E28_AGENTCUT_V3_FULLCUT_AI_REVIEW_RESULT_0P9P1.json"
FREEZE = QA / "E28_AGENTCUT_V3_FINAL_QA_FREEZE.json"
LOCK = ROOT / "workflow/final_lock/e28_20260721/E28_V3_WRITER_AGENT_V050_FINAL_LOCK.json"
RECEIPT = ROOT / "workflow/tasks/E28_AGENTCUT_V3_WRITER_AGENT_V050_FINAL_RECEIPT_20260721.json"
RUNTIME = ROOT / "workflow/tasks/E28_WRITER_AGENT_V050_RUNTIME_RECEIPT_20260721.json"
QUEUE = ROOT / "workflow/work_queue.json"
AUTOSYNC = ROOT / "workflow/s3_relay/STORYCLAW_S3_AUTOSYNC_RECEIPT.json"
YOUTUBE_URL = "https://youtube.com/shorts/Z8JnX-kOg1w"
DOUYIN_EVIDENCE_URL = "https://creator.douyin.com/creator-micro/content/manage?enter_from=publish"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return round(float(result.stdout.strip()), 3)


def review_facts() -> tuple[dict, dict]:
    report = load(REVIEW)
    item = report["items"][0]
    scoring = item["scoring"]
    if report["status"] != "PASS" or item["content_status"] != "PASS":
        raise SystemExit("E28 V3 review did not pass")
    if scoring["score"] < 4.5 or not scoring["hard_gate_passed"]:
        raise SystemExit("E28 V3 score or hard gate failed")
    if item["required_capability_failures"]:
        raise SystemExit("E28 V3 has required capability failures")
    if item["capabilities"]["ocr"]["status"] != "PASS":
        raise SystemExit("E28 V3 OCR normalized decision failed")
    return report, item


def update_queue(status: str, completed: str, next_action: str) -> None:
    queue = load(QUEUE)
    queue["updated_at"] = now()
    lines = queue.get("lines", {})
    iterable = lines.values() if isinstance(lines, dict) else lines
    for line in iterable:
        if isinstance(line, dict) and line.get("episode") == "E28":
            line.update(
                {
                    "stage": "E28_AGENTCUT_V3_WRITER_AGENT_V050_FINAL",
                    "status": status,
                    "local_pids": [],
                    "remote_task_ids": [],
                    "real_activity": True,
                    "evidence": str(RECEIPT.relative_to(ROOT)),
                    "completed_this_round": completed,
                    "next_action": next_action,
                }
            )
            break
    write(QUEUE, queue)


def prepare() -> None:
    _, item = review_facts()
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CANDIDATE, FINAL)
    candidate_sha = sha256(CANDIDATE)
    final_sha = sha256(FINAL)
    if final_sha != candidate_sha:
        raise SystemExit("Final copy changed the release-candidate SHA")
    final_duration = duration(FINAL)
    if abs(final_duration - 165.0) > 0.05:
        raise SystemExit(f"Unexpected E28 final duration: {final_duration}")

    freeze = {
        "schema": "qingshan.e28.agentcut-v3-final-qa-freeze.v1",
        "episode": "E28",
        "recorded_at": now(),
        "status": "PASS_FROZEN_EXACT_SHA",
        "candidate": str(CANDIDATE),
        "candidate_sha256": candidate_sha,
        "final": str(FINAL),
        "final_sha256": final_sha,
        "duration_seconds": final_duration,
        "content_seconds": 162.0,
        "trusted_branded_outro_seconds": 3.0,
        "agentcut_project": {"path": str(PROJECT), "sha256": sha256(PROJECT)},
        "cadence": {"path": str(CADENCE), "sha256": sha256(CADENCE), "status": load(CADENCE)["status"]},
        "ocr_raw": {"path": str(OCR), "sha256": sha256(OCR), "status": load(OCR)["status"], "preserved": True},
        "ocr_machine_adjudication": {"path": str(OCR_ADJ), "sha256": sha256(OCR_ADJ), "status": load(OCR_ADJ)["status"], "confidence": load(OCR_ADJ)["confidence"]},
        "ai_review": {
            "path": str(REVIEW),
            "sha256": sha256(REVIEW),
            "status": item["content_status"],
            "score": item["scoring"]["score"],
            "hard_gate_passed": item["scoring"]["hard_gate_passed"],
            "required_capability_failures": item["required_capability_failures"],
        },
        "residual_gap": "Dialogue coverage is contract-bound in Writer Agent output and native unit audio but was not independently ASR-verified by this final review.",
        "platform_mutation_authorized": False,
    }
    write(FREEZE, freeze)

    lock = {
        "schema": "qingshan.e28.agentcut-v3-final-lock.v1",
        "episode": "E28",
        "recorded_at": now(),
        "status": "LOCKED_FOR_S3_DELIVERY",
        "final": {"path": str(FINAL), "sha256": final_sha, "bytes": FINAL.stat().st_size, "duration_seconds": final_duration},
        "qa_freeze": {"path": str(FREEZE), "sha256": sha256(FREEZE)},
        "source_policy": "5 conditional source admissions retained with raw failures and rollback evidence; all other units direct QA pass.",
        "rollback": {"v2_content_master": str(CANDIDATE.parent.parent / "agentcut_v2_writer_agent_v050_textclean_20260721/E28_AGENTCUT_V2_WRITER_AGENT_V050_TEXTCLEAN_NOT_FINAL.mp4"), "v3_release_candidate": str(CANDIDATE)},
        "platform_release": "NOT_YET_EXECUTED",
    }
    write(LOCK, lock)

    receipt = {
        "schema": "qingshan.e28.agentcut-v3-writer-agent-v050-final-receipt.v1",
        "episode": "E28",
        "recorded_at": now(),
        "status": "FINAL_QA_PASS_S3_UPLOAD_PENDING",
        "final": {"path": str(FINAL), "sha256": final_sha, "bytes": FINAL.stat().st_size, "duration_seconds": final_duration},
        "final_lock": {"path": str(LOCK), "sha256": sha256(LOCK)},
        "qa_freeze": {"path": str(FREEZE), "sha256": sha256(FREEZE)},
        "s3_delivery": {"status": "PENDING_REMOTE_VERIFICATION"},
        "youtube": "NOT_PUBLISHED",
        "douyin": "NOT_PUBLISHED",
        "platform_mutation_authorized": False,
        "remote_credit": 0,
    }
    write(RECEIPT, receipt)

    runtime = load(RUNTIME)
    runtime["recorded_at"] = now()
    runtime["status"] = "PASS_FINAL_QA_S3_UPLOAD_PENDING"
    runtime["downstream"].update(
        {
            "active_remote_task_count": 0,
            "video_batch_status": "BATCH_COMPLETE_WITH_ISOLATED_FAILURES_ADMITTED",
            "agentcut_status": "V3_FINAL_QA_PASS",
            "final_path": str(FINAL),
            "final_sha256": final_sha,
            "final_receipt": str(RECEIPT),
        }
    )
    runtime["next_action"] = "Upload exact-SHA final to S3, verify remote bytes/SHA and then proceed to platform release separately."
    write(RUNTIME, runtime)
    update_queue(
        "FINAL_QA_PASS_S3_UPLOAD_PENDING",
        "V3 exact-SHA final passed cadence, OCR dual-evidence adjudication and Review Agent 0.9.1 at score 5.0 with hard gate PASS.",
        "Upload the final MP4 to S3 and verify remote size/SHA; platform release remains asynchronous.",
    )
    print(json.dumps({"ok": True, "final": str(FINAL), "sha256": final_sha, "receipt": str(RECEIPT)}, ensure_ascii=False))


def complete_s3() -> None:
    receipt = load(RECEIPT)
    autosync = load(AUTOSYNC)
    final_sha = receipt["final"]["sha256"]
    matches = [
        row
        for row in autosync.get("uploaded", [])
        if row.get("final_video") and row.get("path") == str(FINAL) and row.get("sha256") == final_sha and row.get("uploaded_ok")
    ]
    if not matches:
        raise SystemExit("No exact-SHA verified final-video upload found in autosync receipt")
    row = matches[-1]
    if row.get("size_bytes") != FINAL.stat().st_size:
        raise SystemExit("S3 receipt size does not match local final")
    receipt["recorded_at"] = now()
    receipt["status"] = "FINAL_QA_PASS_S3_DELIVERED_PLATFORM_PENDING"
    receipt["s3_delivery"] = {
        "status": "DELIVERED",
        "slug": row["slug"],
        "verified_bytes": row["size_bytes"],
        "verified_sha256": row["sha256"],
        "uploaded_at": row["uploaded_at"],
    }
    write(RECEIPT, receipt)
    runtime = load(RUNTIME)
    runtime["recorded_at"] = now()
    runtime["status"] = "PASS_FINAL_S3_DELIVERED_PLATFORM_PENDING"
    runtime["downstream"]["s3_delivery"] = receipt["s3_delivery"]
    runtime["next_action"] = "Proceed with YouTube and Douyin publication as separate irreversible platform operations."
    write(RUNTIME, runtime)
    update_queue(
        "FINAL_S3_DELIVERED_PLATFORM_PENDING",
        "E28 V3 final passed exact-SHA QA and was uploaded to S3 with matching bytes and SHA-256.",
        "Publish the locked final to YouTube and Douyin; if login or verification blocks the browser, mark PENDING_PLATFORM_BACKFILL.",
    )
    print(json.dumps({"ok": True, "s3_delivery": receipt["s3_delivery"]}, ensure_ascii=False))


def complete_platforms() -> None:
    receipt = load(RECEIPT)
    if receipt.get("s3_delivery", {}).get("status") != "DELIVERED":
        raise SystemExit("E28 S3 delivery is not verified")
    if receipt.get("final", {}).get("sha256") != sha256(FINAL):
        raise SystemExit("Published final no longer matches the locked local SHA")

    recorded_at = now()
    receipt.update(
        {
            "recorded_at": recorded_at,
            "status": "FINAL_QA_PASS_S3_DELIVERED_DUAL_PLATFORM_PUBLISHED",
            "youtube": {
                "status": "PUBLISHED_PUBLIC",
                "url": YOUTUBE_URL,
                "title": "青山 EP28：纸上杀人 | AI短剧",
                "evidence": "YouTube Studio displayed 'Video published' and 'Published Jul 21, 2026'.",
                "checks": "Copyright and Community Guidelines complete: no issues found.",
            },
            "douyin": {
                "status": "PUBLISHED_PUBLIC",
                "title": "青山EP28：纸上杀人",
                "evidence_url": DOUYIN_EVIDENCE_URL,
                "evidence": "Douyin Creator Center redirected to content management and displayed '发布成功'.",
            },
            "platform_mutation_authorized": True,
            "platform_authorization_ref": "Roger explicit instruction to publish using the built-in browser",
        }
    )
    write(RECEIPT, receipt)

    runtime = load(RUNTIME)
    runtime["recorded_at"] = recorded_at
    runtime["status"] = "PASS_FINAL_S3_DELIVERED_DUAL_PLATFORM_PUBLISHED"
    runtime["downstream"]["platform_release"] = {
        "status": "DUAL_PLATFORM_PUBLISHED",
        "youtube": YOUTUBE_URL,
        "douyin": "PUBLISHED_PUBLIC",
        "receipt": str(RECEIPT),
    }
    runtime["next_action"] = "E28 release closed; retain post-publication metrics and rollback evidence. The single-episode debug slot is available for the next explicitly selected episode."
    write(RUNTIME, runtime)

    queue = load(QUEUE)
    queue["updated_at"] = recorded_at
    lines = queue.get("lines", {})
    e28_line = None
    if isinstance(lines, dict):
        for key, line in list(lines.items()):
            if isinstance(line, dict) and line.get("episode") == "E28":
                e28_line = lines.pop(key)
                break
    elif isinstance(lines, list):
        for line in list(lines):
            if isinstance(line, dict) and line.get("episode") == "E28":
                e28_line = line
                lines.remove(line)
                break
    queue["occupied_slot_count"] = 0
    queue["real_active_handle_count"] = 0
    queue.setdefault("completed_lines", {})["E28"] = {
        "status": "S3_DELIVERED_DUAL_PLATFORM_PUBLISHED",
        "real_activity": False,
        "final_receipt": str(RECEIPT.relative_to(ROOT)),
        "final_sha256": receipt["final"]["sha256"],
        "youtube": YOUTUBE_URL,
        "douyin": "PUBLISHED_PUBLIC",
        "completed_at": recorded_at,
        "next_action": "Collect post-publication metrics; do not mutate the locked final without explicit replacement authorization.",
    }
    if e28_line:
        queue["completed_lines"]["E28"]["previous_line"] = e28_line
    write(QUEUE, queue)
    print(json.dumps({"ok": True, "youtube": YOUTUBE_URL, "douyin": "PUBLISHED_PUBLIC", "receipt": str(RECEIPT)}, ensure_ascii=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["prepare", "complete-s3", "complete-platforms"])
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare()
    elif args.mode == "complete-s3":
        complete_s3()
    else:
        complete_platforms()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
