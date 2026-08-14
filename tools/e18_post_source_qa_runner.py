#!/usr/bin/env python3
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "workflow/generation/e18/E18_GENERATION_RECEIPT_ACTUAL_20260714.json"
CHECKLIST = ROOT / "qa/e18_post_source_qa_checklist_20260714.md"
OUT = ROOT / "qa/e18_post_source_qa_runner_latest.json"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    receipt = load_json(RECEIPT)
    jobs = receipt.get("jobs", [])
    checks = []
    submitted = [job for job in jobs if job.get("status") != "NOT_SUBMITTED"]

    checks.append({
        "name": "receipt_exists",
        "status": "PASS" if RECEIPT.exists() else "FAIL",
        "path": str(RECEIPT),
    })
    checks.append({
        "name": "checklist_exists",
        "status": "PASS" if CHECKLIST.exists() else "FAIL",
        "path": str(CHECKLIST),
    })
    checks.append({
        "name": "generation_not_started",
        "status": "PASS" if not submitted and receipt.get("generation_allowed") is False else "INFO",
        "submitted_jobs": [job.get("job_id") for job in submitted],
    })

    for job in jobs:
        download_path = job.get("download_path")
        if not download_path:
            checks.append({
                "name": "job_download_pending",
                "job_id": job.get("job_id"),
                "status": "PENDING",
                "reason": "No download path because job has not completed or has not been submitted.",
            })
            continue

        path = Path(download_path)
        exists = path.exists()
        item = {
            "name": "job_download_exists",
            "job_id": job.get("job_id"),
            "status": "PASS" if exists else "FAIL",
            "path": str(path),
        }
        if exists:
            item["sha256"] = sha256_file(path)
            item["size_bytes"] = path.stat().st_size
        checks.append(item)

    hard_fail = any(check.get("status") == "FAIL" for check in checks)
    overall = "FAIL" if hard_fail else ("PENDING_SOURCE_GENERATION" if not submitted else "NEEDS_QA")

    result = {
        "episode": "E18",
        "status": overall,
        "checked_at": "2026-07-14T22:02:00-07:00",
        "receipt": str(RECEIPT),
        "checklist": str(CHECKLIST),
        "jobs_total": len(jobs),
        "jobs_submitted": len(submitted),
        "checks": checks,
        "next_action": "Run OCR/ASR/visual source gates for all downloaded E18 source files before edit lock.",
    }

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
