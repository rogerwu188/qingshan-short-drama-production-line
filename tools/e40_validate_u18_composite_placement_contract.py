#!/usr/bin/env python3
"""Static validator for the U18 deterministic placement contract."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/keyframe_precompile/u18_isolated_asset_acquisition_v1/E40_U18_DETERMINISTIC_COMPOSITE_PLACEMENT_CONTRACT_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def intersects(a: list[int], b: list[int]) -> bool:
    return max(a[0], b[0]) < min(a[2], b[2]) and max(a[1], b[1]) < min(a[3], b[3])


def main() -> None:
    data = json.loads(CONTRACT.read_text(encoding="utf-8"))
    failures: list[str] = []
    canvas = data["canvas"]
    if (canvas["width"], canvas["height"], canvas["delivery_width"], canvas["delivery_height"]) != (1440, 2560, 720, 1280):
        failures.append("CANVAS_OR_DELIVERY_SIZE_MISMATCH")
    base = ROOT / data["base_plate"]["path"]
    if not base.is_file() or sha(base) != data["base_plate"]["sha256"]:
        failures.append("BASE_PLATE_MISSING_OR_SHA_MISMATCH")
    for name, placement in data["placement_zones"].items():
        box = placement["allowed_bbox_envelope"]
        if not (0 <= box[0] < box[2] <= 1440 and 0 <= box[1] < box[3] <= 2560):
            failures.append(f"{name}:OUT_OF_CANVAS")
        for protected in data["protected_zones"]:
            if intersects(box, protected["bbox"]):
                failures.append(f"{name}:ENVELOPE_OVERLAPS_PROTECTED:{protected['name']}")
    arrow = data["placement_zones"]["low_axis_arrow"]
    if arrow["arrowhead_side"] != "LEFT" or arrow["fletching_side"] != "RIGHT":
        failures.append("ARROW_DIRECTION_CONTRACT_WRONG")
    if arrow["minimum_visible_bbox"][0] < 520:
        failures.append("ARROW_MINIMUM_WIDTH_TOO_SMALL")
    policy = data["mutation_policy"]
    if policy["maximum_union_ratio"] > 0.12 or policy["protected_zone_overlap_allowed"]:
        failures.append("MUTATION_POLICY_TOO_PERMISSIVE")
    if data["output"] != {
        "path": None,
        "sha256": None,
        "union_mask_path": None,
        "union_mask_sha256": None,
        "admitted": False,
        "video_binding_allowed": False,
    }:
        failures.append("OUTPUT_NOT_EXACTLY_NULL_FAIL_CLOSED")
    print(json.dumps({
        "schema": "qingshan.e40.u18.composite_placement_contract_validation.v1",
        "status": "PASS_STATIC_PLACEMENT_CONTRACT_NO_OUTPUT" if not failures else "FAIL_CLOSED",
        "contract_sha256": sha(CONTRACT),
        "failures": failures,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
