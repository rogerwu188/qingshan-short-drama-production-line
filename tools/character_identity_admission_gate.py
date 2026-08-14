#!/usr/bin/env python3
"""Block source admission when character identity evidence is incomplete."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def evaluate(manifest: dict, registry: dict) -> dict:
    failures: list[str] = []
    characters = registry.get("characters", {})
    sources = manifest.get("sources", [])
    if not sources:
        failures.append("identity_sources_missing")
    for source in sources:
        source_id = source.get("source_id", "UNKNOWN")
        rows = source.get("characters", [])
        if not rows:
            failures.append(f"source_character_evidence_missing:{source_id}")
        for row in rows:
            character_id = row.get("character_id", "UNKNOWN")
            prefix = f"{source_id}:{character_id}"
            asset = characters.get(character_id)
            if not asset:
                failures.append(f"character_not_registered:{prefix}")
                continue
            if row.get("history_status") == "NEW":
                views = row.get("canonical_reference_paths", [])
                required = {
                    "sex_presentation_lock",
                    "age_band_lock",
                    "face_identity_lock",
                    "body_identity_lock",
                    "wardrobe_variant_id",
                }
                if len(views) < 3:
                    failures.append(f"new_character_views_below_3:{prefix}")
                for field in sorted(required):
                    if not row.get(field):
                        failures.append(f"new_character_field_missing:{prefix}:{field}")
            if int(row.get("reroll_round", 0)) > 0 and not row.get(
                "identity_qa_rerun", False
            ):
                failures.append(f"reroll_identity_qa_missing:{prefix}")
            if len(row.get("sample_frame_paths", [])) < 3:
                failures.append(f"identity_sample_frames_below_3:{prefix}")
            if row.get("manual_identity_review_status") != "PASS":
                failures.append(f"manual_identity_review_not_pass:{prefix}")
            if row.get("cross_source_consistency_status") != "PASS":
                failures.append(f"cross_source_identity_not_pass:{prefix}")
            if row.get("identity_adjacent_styling_warning", False):
                failures.append(f"identity_styling_warning_blocker:{prefix}")
    return {
        "schema": "qingshan.character_identity_admission_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "source_count": len(sources),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = evaluate(
        json.loads(Path(args.manifest).read_text(encoding="utf-8")),
        json.loads(Path(args.registry).read_text(encoding="utf-8")),
    )
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "failures": report["failures"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
