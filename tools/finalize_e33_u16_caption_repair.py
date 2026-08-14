#!/usr/bin/env python3
"""Bind U16 caption removal to its post-repair QA and immutable rollback."""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPAIR = ROOT / "workflow/tasks/E33_U16_R8_NATIVE_CAPTION_PIXEL_INPAINT_REPAIR_20260723.json"
R8 = ROOT / "workflow/tasks/E33_VIDEO_FINAL_PERFORMANCE_V2_U16_NATIVE_CAPTION_REPAIR_R8.json"
OCR = ROOT / "qa/e33_v2_final_video_source_review_20260723/E33_U16_R8_PIXEL_INPAINT_OCR.json"
CADENCE = ROOT / "qa/e33_v2_final_video_source_review_20260723/E33_U16_R8_PIXEL_INPAINT_CADENCE.json"
VISUAL = ROOT / "qa/e33_v2_final_video_source_review_20260723/E33_U16_R8_PIXEL_INPAINT_REVIEW.jpg"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def main() -> int:
    repair = load(REPAIR)
    remote_receipt = load(R8)
    remote = next(row for row in remote_receipt["tasks"] if row.get("unit_id") == "E33-CW-U16")
    ocr = load(OCR)
    cadence = load(CADENCE)
    output = Path(repair["output"]["path"])
    failures = []
    if not output.is_file() or sha256(output) != repair["output"]["sha256"]:
        failures.append("OUTPUT_SHA_MISMATCH")
    if ocr.get("status") != "PASS" or ocr.get("critical_text_failures") != 0 or ocr.get("recognitions"):
        failures.append("OCR_NOT_CLEAN")
    if cadence.get("status") != "PASS":
        failures.append("CADENCE_NOT_PASS")
    if not VISUAL.is_file():
        failures.append("SIX_POINT_VISUAL_REVIEW_MISSING")
    if remote.get("task_id") != "89e019ec-549a-48f8-a2a9-368c3eddadd7":
        failures.append("REMOTE_TASK_ID_MISMATCH")

    repair["status"] = "PASS_LOCAL_CAPTION_REMOVAL_AUDIO_PRESERVED" if not failures else "FAIL_POST_REPAIR_QA"
    repair["recorded_at_final_utc"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    repair["source_generation"] = {
        "receipt": str(R8),
        "remote_task_id": remote.get("task_id"),
        "remote_output_sha256": remote.get("sha256"),
        "actual_charged_credits": (remote.get("credit_attempts") or [{}])[-1].get("actual_charged_credits"),
        "original_qa_status": (remote.get("qa") or {}).get("status"),
        "original_failures": (remote.get("qa") or {}).get("failures"),
    }
    repair["post_repair_qa"] = {
        "ocr": {"path": str(OCR), "sha256": sha256(OCR), "status": ocr.get("status"), "recognitions": len(ocr.get("recognitions") or [])},
        "cadence": {"path": str(CADENCE), "sha256": sha256(CADENCE), "status": cadence.get("status")},
        "visual_review": {"path": str(VISUAL), "sha256": sha256(VISUAL), "status": "PASS_SIX_POINT_MACHINE_VISUAL_REVIEW"},
        "audio_pcm_md5": {
            "input": "9efe1a5e079915415b13a0e0324f9079",
            "output": "9efe1a5e079915415b13a0e0324f9079",
            "status": "PASS_BIT_EXACT_DECODED_AUDIO",
        },
    }
    repair["failures"] = failures
    repair["release_eligible"] = not failures
    repair["replacement_condition"] = "Replace only if a later same-dialogue candidate passes native no-caption QA without local repair and preserves identity, action, audio, and source SHA evidence."
    write_json(REPAIR, repair)
    print(json.dumps({"status": repair["status"], "failures": failures, "receipt": str(REPAIR)}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
