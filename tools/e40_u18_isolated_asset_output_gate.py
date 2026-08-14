#!/usr/bin/env python3
"""Machine admission gate for future U18 isolated curtain/arrow outputs.

The gate is read-only and intentionally reports BLOCKED while output fields are null.
It never performs generation, submission, transaction creation, or admission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/keyframe_precompile/u18_isolated_asset_acquisition_v1/E40_U18_ISOLATED_ASSET_ACQUISITION_NO_SUBMIT_MANIFEST_V1.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def foreground_bbox(image: Image.Image, mask: Image.Image | None) -> tuple[int, int, int, int] | None:
    if mask is not None:
        return mask.convert("L").point(lambda value: 255 if value >= 128 else 0).getbbox()
    if image.mode != "RGBA":
        return None
    return image.getchannel("A").point(lambda value: 255 if value >= 16 else 0).getbbox()


def validate_asset(asset: dict, root: Path) -> list[str]:
    asset_id = asset["asset_id"]
    failures: list[str] = []
    if not asset.get("output_path"):
        return [f"{asset_id}:OUTPUT_PATH_MISSING"]
    output = root / asset["output_path"]
    if not output.is_file():
        return [f"{asset_id}:OUTPUT_FILE_MISSING"]
    if not asset.get("output_sha256"):
        failures.append(f"{asset_id}:OUTPUT_SHA_MISSING")
    elif sha256(output) != asset["output_sha256"]:
        failures.append(f"{asset_id}:OUTPUT_SHA_MISMATCH")
    if not str(asset.get("provenance") or "").strip():
        failures.append(f"{asset_id}:PROVENANCE_MISSING")
    if not str(asset.get("license_or_local_authorship") or "").strip():
        failures.append(f"{asset_id}:RIGHTS_MISSING")

    with Image.open(output) as image:
        image.load()
        width, height = image.size
        mask = None
        if asset.get("output_mask_path"):
            mask_path = root / asset["output_mask_path"]
            if not mask_path.is_file():
                failures.append(f"{asset_id}:MASK_FILE_MISSING")
            else:
                if not asset.get("output_mask_sha256"):
                    failures.append(f"{asset_id}:MASK_SHA_MISSING")
                elif sha256(mask_path) != asset["output_mask_sha256"]:
                    failures.append(f"{asset_id}:MASK_SHA_MISMATCH")
                mask = Image.open(mask_path)
                mask.load()
                if mask.size != image.size:
                    failures.append(f"{asset_id}:MASK_DIMENSION_MISMATCH")
        bbox = foreground_bbox(image, mask)
        if bbox is None:
            failures.append(f"{asset_id}:TRANSPARENCY_OR_EXACT_MASK_MISSING")
            return failures
        box_width, box_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if box_width <= 0 or box_height <= 0:
            failures.append(f"{asset_id}:EMPTY_FOREGROUND")
            return failures

        if asset_id.endswith("TORN-CURTAIN-SOURCE-V1"):
            if width < 512 or height < 512:
                failures.append(f"{asset_id}:CANVAS_BELOW_512PX")
            if box_width < 160 or box_height < 320:
                failures.append(f"{asset_id}:CURTAIN_FOREGROUND_TOO_SMALL")
            if box_height / box_width < 1.25:
                failures.append(f"{asset_id}:CURTAIN_NOT_VERTICAL")
        elif asset_id.endswith("LOW-AXIS-ARROW-V1"):
            if width < 768 or height < 256:
                failures.append(f"{asset_id}:CANVAS_BELOW_768X256")
            if box_width < 512:
                failures.append(f"{asset_id}:ARROW_NOT_DELIVERY_READABLE")
            if box_width / box_height < 4.0:
                failures.append(f"{asset_id}:ARROW_NOT_HORIZONTAL_SIDE_PROFILE")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    manifest_path = args.manifest if args.manifest.is_absolute() else ROOT / args.manifest
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for asset in data["assets"]:
        failures.extend(validate_asset(asset, ROOT))
    missing = [failure for failure in failures if failure.endswith(":OUTPUT_PATH_MISSING")]
    status = (
        "BLOCKED_OUTPUTS_NOT_YET_CREATED"
        if len(missing) == len(data["assets"])
        else "PASS_MACHINE_OUTPUT_GATE_REQUIRES_HUMAN_QA_NO_AUTO_ADMISSION"
        if not failures
        else "FAIL_CLOSED_OUTPUT_GATE"
    )
    print(json.dumps({
        "schema": "qingshan.e40.u18.isolated_asset_output_gate.v1",
        "status": status,
        "manifest_sha256": sha256(manifest_path),
        "failures": failures,
        "automatic_admission": False,
        "provider_calls": 0,
        "transactions": 0,
        "credits": 0,
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
