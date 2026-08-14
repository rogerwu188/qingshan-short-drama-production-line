#!/usr/bin/env python3
"""Compile E20 dialogue performance records into a non-submittable audio skeleton."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


REQUIRED_DELIVERY = {
    "tone_code",
    "subtext_code",
    "pace",
    "volume",
    "breath",
    "temperature",
    "energy",
    "stress",
    "expression_arc",
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--beat-sheet", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    beat_sheet_path = Path(args.beat_sheet)
    beat_sheet_bytes = beat_sheet_path.read_bytes()
    beat_sheet_sha256 = hashlib.sha256(beat_sheet_bytes).hexdigest()
    beat_sheet = json.loads(beat_sheet_bytes)
    if manifest.get("beat_sheet_sha256") != beat_sheet_sha256:
        raise SystemExit("beat sheet SHA256 mismatch")
    lines = manifest.get("lines") or []
    draft = beat_sheet.get("dialogue_draft") or []
    expected_ids = [item["dia_id"] for item in draft]
    actual_ids = [item["dia_id"] for item in lines]
    if actual_ids != expected_ids:
        raise SystemExit("dialogue ID or order mismatch")

    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for line in lines:
        delivery = line.get("delivery") or {}
        missing = sorted(REQUIRED_DELIVERY - set(delivery))
        if missing:
            raise SystemExit(f"{line['dia_id']}: missing delivery fields: {','.join(missing)}")
        if line.get("voice_asset_id") is None and not line.get("voice_gate"):
            raise SystemExit(f"{line['dia_id']}: unresolved voice lacks explicit gate")
        grouped[line["beat_id"]].append(
            {
                "dia_id": line["dia_id"],
                "speaker": line["speaker"],
                "character_id": line["character_id"],
                "voice_asset_id": line.get("voice_asset_id"),
                "voice_gate": line.get("voice_gate"),
                "exact_text": line["text"],
                "text_with_pause": line["text_with_pause"],
                "function": line["function"],
                "delivery": delivery,
            }
        )

    output = {
        "episode": manifest["episode"],
        "created_at": "2026-07-16T03:01:00-07:00",
        "status": "NON_SUBMITTABLE_AUDIO_PROMPT_SKELETON_LOCAL_ONLY",
        "generation_allowed": False,
        "submittable": False,
        "provider_payload": None,
        "beat_sheet_sha256": beat_sheet_sha256,
        "prompt_section": "AUDIO_PROMPT_DIALOGUE_ONLY",
        "visual_prompt_fields_present": False,
        "beats": [
            {
                "beat_id": beat_id,
                "relationship_strategy": manifest["relationship_strategy_by_beat"][beat_id],
                "AUDIO_PROMPT_DIALOGUE_ONLY": grouped[beat_id],
            }
            for beat_id in [beat["beat_id"] for beat in beat_sheet["structure"]]
        ],
        "checks": {
            "dialogue_count": len(lines),
            "dialogue_ids_match_beat_sheet": True,
            "delivery_fields_complete": True,
            "unresolved_voice_assets_explicitly_blocked": True,
            "visual_prompt_dialogue_leak": False,
        },
        "release_rule": "This skeleton may only be joined with reviewed visual prompts inside one multimodal request after every shared and voice gate passes.",
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": output["status"], "beats": len(output["beats"]), "dialogue_count": len(lines)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
