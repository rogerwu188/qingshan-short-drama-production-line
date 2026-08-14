#!/usr/bin/env python3
"""Prepare and run immediate QA for downloaded E18/E19 omni candidates."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


BASE = Path("/Users/rogerwu/qingshan_short_drama")
STATUS = BASE / "workflow/generation/e18_e19/E18_E19_FINAL_OMNI_MULTIMODAL_REMOTE_STATUS_20260715.json"
QA_DIR = BASE / "qa/e18_e19_final_omni_multimodal_candidates_v1_20260715"
QUEUE = QA_DIR / "E18_E19_POST_OMNI_DOWNLOAD_QA_QUEUE_20260715.json"
SUMMARY = QA_DIR / "E18_E19_POST_OMNI_DOWNLOAD_QA_QUEUE_20260715.md"
OCR_TOOL = BASE / "tools/final_video_ocr_audit.py"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def ffmpeg_bin() -> str:
    proc = subprocess.run(
        [str(BASE / "tools/find_ffmpeg.sh"), str(BASE)],
        text=True,
        capture_output=True,
        check=True,
    )
    return proc.stdout.strip()


def make_contact(ffmpeg: str, video: Path, out: Path) -> bool:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-y",
        "-i",
        str(video),
        "-vf",
        "fps=1,scale=180:-1,tile=5x4",
        "-frames:v",
        "1",
        str(out),
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    return proc.returncode == 0 and out.exists()


def run_ocr(video: Path, out: Path) -> dict[str, Any]:
    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "python3",
            str(OCR_TOOL),
            "--video",
            str(video),
            "--out",
            str(out),
            "--allow-text",
            "纳鲁影业",
            "--forbid-text",
            "字幕",
            "--forbid-text",
            "English",
        ],
        text=True,
        capture_output=True,
    )
    if out.exists():
        payload = read_json(out)
        return {
            "status": payload.get("status"),
            "critical_text_failures": payload.get("critical_text_failures"),
            "latin_chars": payload.get("latin_chars"),
        }
    return {"status": "NOT_RUN", "stderr": proc.stderr[-1000:], "stdout": proc.stdout[-1000:]}


def load_manual_ocr_clearance(episode: str, shot_id: str, source_id: str) -> dict[str, Any] | None:
    token = source_id.replace("/", "_")
    candidates = sorted(QA_DIR.glob(f"{episode}_{shot_id}_*_MANUAL_OCR_CLEARANCE_*.json"))
    candidates += sorted(QA_DIR.glob(f"*{token}*MANUAL_OCR_CLEARANCE_*.json"))
    for path in candidates:
        try:
            payload = read_json(path)
        except Exception:
            continue
        if (
            payload.get("status") == "PASS"
            and payload.get("episode") == episode
            and payload.get("shot_id") == shot_id
            and payload.get("source_id") == source_id
        ):
            return {"path": str(path), "payload": payload}
    return None


def main() -> int:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    data = read_json(STATUS)
    ffmpeg = ffmpeg_bin()
    items = []
    downloaded = 0
    ocr_failures = 0
    for result in data.get("results", []):
        files = [Path(p) for p in result.get("downloaded_files") or []]
        video = files[0] if files else None
        item = {
            "episode": result.get("episode"),
            "shot_id": result.get("shot_id"),
            "source_id": result.get("source_id"),
            "task_id": result.get("task_id"),
            "remote_status": result.get("remote_status"),
            "video": str(video) if video else None,
            "contact_status": "PENDING_DOWNLOAD",
            "ocr_status": "PENDING_DOWNLOAD",
            "asr_status": "PENDING_DOWNLOAD",
            "watch_gate_status": "PENDING_DOWNLOAD",
        }
        if video and video.exists():
            downloaded += 1
            safe_name = f"{result.get('episode')}_{result.get('shot_id')}_{result.get('source_id')}"
            contact = QA_DIR / f"{safe_name}_contact.jpg"
            ocr = QA_DIR / f"{safe_name}_ocr.json"
            item["contact_path"] = str(contact)
            item["contact_status"] = "PASS" if make_contact(ffmpeg, video, contact) else "FAIL"
            ocr_result = run_ocr(video, ocr)
            item["ocr_path"] = str(ocr)
            item["ocr_status"] = ocr_result.get("status")
            item["ocr_result"] = ocr_result
            clearance = None
            if item["ocr_status"] != "PASS":
                clearance = load_manual_ocr_clearance(
                    str(result.get("episode")),
                    str(result.get("shot_id")),
                    str(result.get("source_id")),
                )
            if clearance:
                item["ocr_status"] = "PASS_WITH_MANUAL_CLEARANCE"
                item["manual_ocr_clearance"] = {
                    "status": "PASS",
                    "path": clearance["path"],
                    "decision": clearance["payload"].get("manual_review", {}).get("decision"),
                }
            elif item["ocr_status"] != "PASS":
                ocr_failures += 1
            item["asr_status"] = "PENDING_ASR_SENTENCE_COMPLETENESS"
            item["watch_gate_status"] = "PENDING_MANUAL_CONTACT_REVIEW"
        items.append(item)
    manual_clearances = sum(1 for item in items if item.get("ocr_status") == "PASS_WITH_MANUAL_CLEARANCE")
    if downloaded == 0:
        status = "PENDING_REMOTE_DOWNLOADS"
    elif ocr_failures:
        status = "QA_HAS_FAILURES"
    elif manual_clearances:
        status = "OCR_PASS_WITH_MANUAL_CLEARANCE__PENDING_ASR_AND_MANUAL_WATCH"
    else:
        status = "QA_PARTIAL_READY"
    payload = {
        "schema": "qingshan.e18_e19_post_omni_download_qa_queue.v1",
        "remote_status": str(STATUS),
        "status": status,
        "task_count": len(items),
        "downloaded_count": downloaded,
        "ocr_failures": ocr_failures,
        "manual_ocr_clearances": manual_clearances,
        "items": items,
        "next_action": "Poll remote generation, download completed files, then run ASR sentence completeness and manual contact/watch gate.",
    }
    QUEUE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# E18/E19 Post-Omni Download QA Queue",
        "",
        f"Status: `{payload['status']}`",
        f"Tasks: `{payload['task_count']}`",
        f"Downloaded: `{payload['downloaded_count']}`",
        f"OCR failures: `{payload['ocr_failures']}`",
        f"Manual OCR clearances: `{payload['manual_ocr_clearances']}`",
        "",
        "Next: poll remote generation; completed files will enter contact, OCR, ASR and manual watch gates.",
        "",
    ]
    SUMMARY.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "downloaded": downloaded, "queue": str(QUEUE)}, ensure_ascii=False))
    return 1 if payload["status"] == "QA_HAS_FAILURES" else 0


if __name__ == "__main__":
    raise SystemExit(main())
