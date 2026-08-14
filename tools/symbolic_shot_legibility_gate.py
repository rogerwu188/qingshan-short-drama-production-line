#!/usr/bin/env python3
"""Validate symbolic-shot declaration, differentiation and blind-read evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SYMBOLIC_KINDS = {"metaphor", "avatar", "illusion", "dream", "vision", "symbolic"}


def evaluate(payload: dict) -> dict:
    failures: list[str] = []
    shots = payload.get("shots", [])
    for shot in shots:
        shot_id = shot.get("shot_id", "UNKNOWN")
        kind = shot.get("shot_kind")
        symbolic = bool(shot.get("symbolic_shot", False))
        if kind in SYMBOLIC_KINDS and not symbolic:
            failures.append(f"symbolic_declaration_missing:{shot_id}")
            continue
        if not symbolic:
            continue
        if not shot.get("intended_read"):
            failures.append(f"intended_read_missing:{shot_id}")
        spec = shot.get("differentiation_spec", {})
        dimensions = spec.get("dimensions", [])
        if len(set(dimensions)) < 3:
            failures.append(f"differentiation_dimensions_below_3:{shot_id}")
        entities = spec.get("entities", [])
        labels = [str(item.get("visual_label", "")).strip() for item in entities]
        if not entities or any(not label for label in labels):
            failures.append(f"symbolic_entity_label_missing:{shot_id}")
        if len(labels) != len(set(labels)):
            failures.append(f"symbolic_entity_labels_not_unique:{shot_id}")
        if not spec.get("separate_prompt_segment_per_entity", False):
            failures.append(f"symbolic_entities_not_separate_prompts:{shot_id}")
        blind = shot.get("script_hidden_visual_blind_test", {})
        if blind.get("status") != "PASS":
            failures.append(f"script_hidden_visual_blind_test_not_pass:{shot_id}")
        if blind.get("observed_read") != shot.get("intended_read"):
            failures.append(f"blind_read_mismatch:{shot_id}")
    return {
        "schema": "qingshan.symbolic_shot_legibility_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "shot_count": len(shots),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = evaluate(json.loads(Path(args.input).read_text(encoding="utf-8")))
    Path(args.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": report["status"], "failures": report["failures"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
