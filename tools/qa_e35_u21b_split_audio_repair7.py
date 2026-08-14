#!/usr/bin/env python3
"""Verify E35 U21B split reference audio and record exact task credits."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from faster_whisper import WhisperModel

from giggle_api_client import _get


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa/e35_v1_release_20260723/E35_U21B_SPLIT_AUDIO_REPAIR7_QA.json"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
MODEL = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
ITEMS = (
    {
        "dialogue_id": "E35-DIA-SEG-045A",
        "text": "照他们的规矩，",
        "task_id": "421fe744-7d76-4658-aa59-cc9649c5d103",
        "path": ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/repair7_wav/E35-DIA-SEG-045A.wav",
    },
    {
        "dialogue_id": "E35-DIA-SEG-045B",
        "text": "假谍探是要当街处决的！",
        "task_id": "223a2d0e-7793-4261-b7db-004e0cfaa3e4",
        "path": ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/repair7_wav/E35-DIA-SEG-045B.wav",
    },
)
COMBINED = {
    "dialogue_id": "E35-DIA-SEG-045",
    "text": "照他们的规矩，假谍探是要当街处决的！",
    "path": ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/repair7_wav/E35-DIA-SEG-045_EXACT_REPAIR7.wav",
}


def normalized(text: str) -> str:
    return "".join(re.findall(r"[\u3400-\u9fffA-Za-z0-9]", text)).lower()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def duration(path: Path) -> float:
    result = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    return float(result.stdout.strip())


def exact_credit(task_id: str) -> dict:
    errors = []
    for _ in range(7):
        try:
            response = _get("/api/v1/payment/credit-statements", {"credit_type": "Pay", "page": 1, "page_size": 40, "project_id": task_id})
            rows = [
                row for row in ((response.get("data") or {}).get("list") or [])
                if str(row.get("project_id") or "") == task_id and row.get("event_type") == "Pay"
            ]
            if rows:
                total = sum(abs(Decimal(str(row["credit"]))) for row in rows)
                return {"status": "KNOWN_EXACT_TASK_STATEMENT", "charged_credits": int(total), "statement_rows": rows}
        except BaseException as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        time.sleep(2)
    return {"status": "UNKNOWN_NOT_ESTIMATED", "charged_credits": None, "statement_rows": [], "errors": errors}


def main() -> int:
    model = WhisperModel(str(MODEL), device="cpu", compute_type="int8")
    rows = []
    for spec in ITEMS:
        segments = list(model.transcribe(
            str(spec["path"]), language="zh", vad_filter=True, beam_size=5,
            initial_prompt=spec["text"], word_timestamps=True,
        )[0])
        transcript = "".join(segment.text.strip() for segment in segments)
        expected_norm = normalized(spec["text"])
        transcript_norm = normalized(transcript)
        similarity = difflib.SequenceMatcher(None, expected_norm, transcript_norm).ratio()
        exact = expected_norm == transcript_norm
        credit = exact_credit(spec["task_id"])
        rows.append({
            "dialogue_id": spec["dialogue_id"],
            "expected": spec["text"],
            "asr_transcript": transcript,
            "normalized_exact_match": exact,
            "asr_similarity": round(similarity, 4),
            "duration_seconds": round(duration(spec["path"]), 6),
            "path": str(spec["path"]),
            "sha256": sha(spec["path"]),
            "task_id": spec["task_id"],
            "credit": credit,
            "status": "PASS" if exact and credit["status"] == "KNOWN_EXACT_TASK_STATEMENT" else "FAIL",
        })
    segments = list(model.transcribe(
        str(COMBINED["path"]), language="zh", vad_filter=True, beam_size=5,
        initial_prompt=COMBINED["text"], word_timestamps=True,
    )[0])
    transcript = "".join(segment.text.strip() for segment in segments)
    exact = normalized(COMBINED["text"]) == normalized(transcript)
    rows.append({
        "dialogue_id": COMBINED["dialogue_id"],
        "expected": COMBINED["text"],
        "asr_transcript": transcript,
        "normalized_exact_match": exact,
        "asr_similarity": round(difflib.SequenceMatcher(None, normalized(COMBINED["text"]), normalized(transcript)).ratio(), 4),
        "duration_seconds": round(duration(COMBINED["path"]), 6),
        "path": str(COMBINED["path"]),
        "sha256": sha(COMBINED["path"]),
        "derived_from_task_ids": [spec["task_id"] for spec in ITEMS],
        "credit": {"status": "DERIVED_FROM_EXACT_COMPONENT_STATEMENTS", "charged_credits": sum(row["credit"]["charged_credits"] for row in rows)},
        "status": "PASS_DIAGNOSTIC_ONLY" if exact else "FAIL_NOT_USED_AS_SINGLE_REFERENCE",
    })
    component_rows = [row for row in rows if row["dialogue_id"] in {"E35-DIA-SEG-045A", "E35-DIA-SEG-045B"}]
    payload = {
        "schema": "qingshan.e35.u21b.split_audio_repair7_qa.v1",
        "episode": "E35",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_COMPONENTS" if all(row["status"] == "PASS" for row in component_rows) else "FAIL",
        "policy": "Each submitted reference component requires exact normalized ASR equality and an exact payment statement. A failed combined diagnostic is never used as a single reference.",
        "rows": rows,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "rows": [{"id": row["dialogue_id"], "asr": row["asr_transcript"], "credit": row["credit"]["charged_credits"]} for row in rows]}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS_COMPONENTS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
