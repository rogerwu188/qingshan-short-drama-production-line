#!/usr/bin/env python3
"""Deterministically isolate E40's old-seal motif from the frozen E39 plate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "exports/e39/agentcut_release_20260806/E39_青山_借刀查案_FINAL.mp4"
FINAL_QA = ROOT / "qa/e39_final_20260806/E39_FINAL_QA_FREEZE_V1.json"
SOURCE = ROOT / "working_assets/e39_video_v1/deterministic_text_plates/E39-U11-DATE-SEAL-PLATE-V1.png"
PLAN = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/reusable_asset_acquisition_v1/E40_REUSABLE_ASSET_ACQUISITION_PLAN_V1.json"
OUT_DIR = ROOT / "working_assets/e40_preproduction_20260808/ag03_old_seal_local_extraction_v1"
ASSET = OUT_DIR / "E40_AG03_OLD_SEAL_RUBBING_EXACT_PROP_REFERENCE_V1.png"
MANIFEST = OUT_DIR / "E40_AG03_OLD_SEAL_LOCAL_EXTRACTION_MANIFEST_V1.json"

EXPECTED = {
    MASTER: "3aa09cd7e4a2d3e899cea8aeb88e91053a98841dd487d3b435f4556af77081c3",
    FINAL_QA: "44767e6feaa05d36c3a3351e463541c54909848e106caee3ff581cbcae40ce7f",
    SOURCE: "24435eadf72620a81e9b4e3fce8e3da76f583173cc2991496e08e2f3430af280",
    PLAN: "0f3a735ed73d49575845cc2a40b699e403b1da48ece8070658698514c07328f5",
}

# Exact pixels on the frozen 1080x1920 plate. This rectangle excludes the
# document border and the three numbered boxes; it contains only paper fibre
# and the single red flower seal motif.
CROP_BOX = (288, 982, 793, 1516)
EXPECTED_RED_MOTIF_BBOX = (368, 1062, 712, 1435)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


for path, expected in EXPECTED.items():
    actual = sha256(path)
    if actual != expected:
        raise SystemExit(f"SHA mismatch: {rel(path)} expected={expected} actual={actual}")

source = Image.open(SOURCE).convert("RGB")
if source.size != (1080, 1920):
    raise SystemExit(f"Unexpected frozen plate dimensions: {source.size}")

red_points = []
pixels = source.load()
for y in range(source.height):
    for x in range(source.width):
        red, green, blue = pixels[x, y]
        if red >= 80 and red >= green * 1.45 and red >= blue * 1.35 and green < 120:
            red_points.append((x, y))
red_bbox = (
    min(point[0] for point in red_points),
    min(point[1] for point in red_points),
    max(point[0] for point in red_points),
    max(point[1] for point in red_points),
)
if red_bbox != EXPECTED_RED_MOTIF_BBOX:
    raise SystemExit(f"Unexpected red motif bbox: {red_bbox}")

left, top, right, bottom = CROP_BOX
motif_left, motif_top, motif_right, motif_bottom = red_bbox
if not (left < motif_left < motif_right < right and top < motif_top < motif_bottom < bottom):
    raise SystemExit("Crop box does not safely contain the complete motif")

OUT_DIR.mkdir(parents=True, exist_ok=True)
crop = source.crop(CROP_BOX)
crop.save(ASSET, format="PNG", compress_level=9, optimize=False)

manifest = {
    "schema": "qingshan.e40.local_prop_extraction.v1",
    "episode": "E40",
    "group_id": "E40-AG03-OLD-SEAL-LOCAL-EXTRACTION",
    "status": "EXTRACTED_PENDING_OCR_AND_HUMAN_QA",
    "operation": "PIXEL_EXACT_CROP_ONLY_NO_REDRAW_NO_GENERATION",
    "frozen_e39_authority": {
        "master_path": rel(MASTER),
        "master_sha256": EXPECTED[MASTER],
        "final_qa_path": rel(FINAL_QA),
        "final_qa_sha256": EXPECTED[FINAL_QA],
        "source_plate_path": rel(SOURCE),
        "source_plate_sha256": EXPECTED[SOURCE],
        "source_size": [1080, 1920],
    },
    "plan": {"path": rel(PLAN), "sha256": EXPECTED[PLAN]},
    "crop": {
        "box_left_top_right_bottom": list(CROP_BOX),
        "output_size": list(crop.size),
        "source_red_motif_bbox": list(red_bbox),
        "output_red_motif_bbox": [
            motif_left - left,
            motif_top - top,
            motif_right - left,
            motif_bottom - top,
        ],
        "document_border_excluded": True,
        "numbered_boxes_excluded": True,
    },
    "asset": {
        "path": rel(ASSET),
        "sha256": sha256(ASSET),
        "kind": "OLD_SEAL_RUBBING_EXACT_PROP_REFERENCE",
        "is_start_frame": False,
    },
    "owner_count_transfer": {
        "item": "old-seal rubbing",
        "count": 1,
        "u12_initial_owner": "Chenji",
        "u12_initial": "rolled in Chenji's lapel",
        "u12_transfer": "Chenji→over the curtain→inner table",
        "u12_final_owner": "Yunfei side custody",
        "u12_final": "half-unfolded on inner table, seal motif facing up",
        "u13_u14_transfer": "NONE",
    },
    "immutability": {
        "e39_modified": False,
        "source_write": False,
        "source_sha_after": sha256(SOURCE),
        "master_sha_after": sha256(MASTER),
        "final_qa_sha_after": sha256(FINAL_QA),
    },
    "credits": {"pay": 0, "refund": 0, "net": 0},
    "remote_calls": 0,
    "video_submissions": 0,
    "next_action": "Run OCR/pseudo-Chinese checks and original-image human prop QA at threshold >=80 before admission.",
}
MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print(json.dumps({
    "asset": rel(ASSET),
    "asset_sha256": sha256(ASSET),
    "manifest": rel(MANIFEST),
    "manifest_sha256": sha256(MANIFEST),
    "bytes": ASSET.stat().st_size,
    "credits": {"pay": 0, "refund": 0, "net": 0},
}, ensure_ascii=False))
