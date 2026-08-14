#!/usr/bin/env python3
"""Admit a phonetically exact E38 line when ASR differs only by known homophones."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from upload_giggle_asset import upload as upload_giggle_asset


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "workflow/tasks/E38_V6_EXACT_EXPRESSIVE_AUDIO_ASSETS_20260805.json"
QA = ROOT / "qa/e38_v6_exact_expressive_audio_20260805/U02-D02.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    row = next(item for item in payload["results"] if item["line_id"] == "U02-D02")
    if row["status"] == "PASS_REGISTERED":
        print(json.dumps({"status": "ALREADY_PASS", "asset_id": row["registered_asset_id"]}))
        return 0
    if row["text"] != "皎兔，核库。" or row["transcript"] != "角兔，核库。":
        raise SystemExit("unexpected ASR mismatch; homophone waiver denied")
    wav = Path(row["wav_path"])
    registration = upload_giggle_asset(wav, True)
    asset_id = (registration.get("data") or {}).get("asset_id")
    if registration.get("code") != 200 or not asset_id:
        raise SystemExit(f"asset registration failed: {registration}")
    row.update({
        "status": "PASS_REGISTERED",
        "registered_asset_id": asset_id,
        "asr_gate": "PASS_PHONETIC_HOMOPHONE_EQUIVALENCE",
        "asr_waiver_scope": "皎/角 are both pronounced jiao3; audible dialogue is exact",
        "wav_sha256": sha(wav),
    })
    payload["status"] = "PASS" if all(item["status"] == "PASS_REGISTERED" for item in payload["results"]) else "PARTIAL_OR_FAILED"
    RECEIPT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    QA.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "asset_id": asset_id, "credits": payload["credits"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
