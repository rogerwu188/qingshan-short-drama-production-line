#!/usr/bin/env python3
"""Compile E18R's approved 41-line script against immutable voice assets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--beat-sheet", required=True)
    parser.add_argument("--voice-contract", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    beat_path = Path(args.beat_sheet).resolve()
    contract_path = Path(args.voice_contract).resolve()
    base = Path(__file__).resolve().parents[1]
    beat = json.loads(beat_path.read_text(encoding="utf-8"))
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    bindings = dict(contract.get("principal_voice_bindings") or {})
    receipts = {}
    for row in contract.get("side_role_candidates") or []:
        receipt_path = (base / row["register_receipt"]).resolve()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        asset_id = (receipt.get("data") or {}).get("asset_id")
        if not asset_id:
            raise SystemExit(f"Registration receipt has no asset_id: {receipt_path}")
        bindings[row["speaker"]] = asset_id
        receipts[row["speaker"]] = str(receipt_path)

    source_lines = beat.get("dialogue_draft") or []
    if len(source_lines) != 41:
        raise SystemExit(f"Expected 41 approved lines, found {len(source_lines)}")
    lines = []
    failures = []
    for order, row in enumerate(source_lines, 1):
        voice_asset_id = bindings.get(row["speaker"])
        if not voice_asset_id:
            failures.append(f"unbound_speaker:{row['speaker']}:{row['dia_id']}")
        lines.append(
            {
                "order": order,
                "dia_id": row["dia_id"],
                "speaker": row["speaker"],
                "text": row["text"],
                "voice_asset_id": voice_asset_id,
                "candidate_audio_allowed": False,
            }
        )
    if bindings.get("乌云") != "z8048tlie3t":
        failures.append("wuyun_voice_binding_mismatch")
    report = {
        "schema": "qingshan.e18r_dialogue_voice_binding_manifest.v1",
        "episode": "E18R",
        "status": "PASS_41_LINES_BOUND" if not failures else "FAIL",
        "beat_sheet": str(beat_path),
        "voice_contract": str(contract_path),
        "line_count": len(lines),
        "speaker_count": len(bindings),
        "speaker_bindings": bindings,
        "registration_receipts": receipts,
        "lines": lines,
        "failures": failures,
        "next_action": "Compile multimodal coverage tasks and measure ASR segment density after source audio is generated.",
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "line_count": len(lines), "failures": failures}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
