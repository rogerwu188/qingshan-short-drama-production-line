#!/usr/bin/env python3
"""Build a reversible, deterministic E40 A01 keyframe composite.

No model, network, randomness, inpainting, or generative fill is used.  R8 is
the base; R7 contributes only a real torn-curtain crop; R8 contributes the
single existing arrow, which is rescaled/repositioned as a short crossbow bolt.
The original high arrow is removed with a same-image, same-x curtain clone.
Every mutation is exported as an alpha layer/mask and recorded by SHA-256.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "working_assets/e40_preproduction_20260808/deterministic_compositor_r2"
R6 = ROOT / "working_assets/e40_preproduction_20260808/keyframe_candidates_r6/E40_E40-U18-A01-START-KEYFRAME-R6_4e6cc199-e0b7-4e44-a361-a5b4db347f48.png"
R7 = ROOT / "working_assets/e40_preproduction_20260808/keyframe_candidates_r7_targeted_edit/E40_E40-U18-A01-START-KEYFRAME-R7-TARGETED-EDIT_8bdea076-eade-4878-b0fa-536c6a28b039.png"
R8 = ROOT / "working_assets/e40_preproduction_20260808/keyframe_candidates_r8_masked/E40_E40-U18-A01-START-KEYFRAME-R8-EXACT-MASKED-EDIT_c05e1fa7-9655-4305-9d86-41f33112494c.png"

EXPECTED = {
    R6: "0a22d10a9f4b9befb70fd779a85d8e1874d78c3a9b1d25d13d760ffa2f68f6d2",
    R7: "33a642966bae7d73b3595d5235a4b54c96b368dab9aa94595cbceb8a61bb3b96",
    R8: "953a502376125c4ba8eb0d566baf69105a858ce8f19b9087890e3294628ea0a0",
}

CANVAS = (1440, 2560)
CLEANUP_SOURCE = (930, 1110, 1440, 1210)
CLEANUP_DEST = (930, 1000, 1440, 1100)
TEAR_SOURCE = (1180, 1120, 1440, 1420)
TEAR_SIZE = (120, 220)
TEAR_DEST_XY = (1320, 1365)
ARROW_SOURCE = (930, 1000, 1440, 1100)
ARROW_SIZE = (150, 29)
ARROW_ROTATE_DEGREES = 7.0
ARROW_DEST_XY = (1288, 1544)
ICE_INTERCEPTION_TARGET = (1289, 1592)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def save(image: Image.Image, name: str) -> Path:
    path = OUT / name
    image.save(path)
    return path


def feathered_rect(size: tuple[int, int], inset: int, blur: float) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rectangle((inset, inset, size[0] - inset - 1, size[1] - inset - 1), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(blur))


def arrow_mask() -> Image.Image:
    """Tight deterministic alpha around the only arrow in the R8 crop."""
    mask = Image.new("L", (510, 100), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon([(24, 50), (104, 24), (95, 41), (117, 44), (117, 56), (95, 59), (104, 76)], fill=255)
    draw.polygon([(96, 42), (434, 43), (434, 58), (96, 58)], fill=255)
    draw.polygon([(390, 34), (510, 41), (510, 65), (390, 69), (420, 57), (380, 57), (380, 43), (420, 43)], fill=255)
    return mask.filter(ImageFilter.GaussianBlur(1.2))


def paste_rgba(base: Image.Image, layer: Image.Image, xy: tuple[int, int]) -> Image.Image:
    result = base.copy()
    result.alpha_composite(layer, xy)
    return result


def main() -> int:
    for path, expected in EXPECTED.items():
        actual = sha(path)
        if actual != expected:
            raise SystemExit(f"source SHA mismatch: {path}: {actual} != {expected}")
    OUT.mkdir(parents=True, exist_ok=True)

    r7 = Image.open(R7).convert("RGBA")
    r8 = Image.open(R8).convert("RGBA")
    if r7.size != CANVAS or r8.size != CANVAS:
        raise SystemExit("source canvas mismatch")

    # Step 1: remove the high R8 arrow with a nearby same-x curtain sample.
    cleanup_patch = r8.crop(CLEANUP_SOURCE)
    cleanup_mask_local = feathered_rect(cleanup_patch.size, inset=8, blur=7.0)
    cleanup_layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    cleanup_layer.paste(cleanup_patch, CLEANUP_DEST[:2], cleanup_mask_local)
    step1 = paste_rgba(r8, cleanup_layer, (0, 0))

    # Step 2: restore a real torn-curtain opening from R7, compressed into the
    # right-rear strip so it does not overwrite the low ice or protected cast.
    tear = r7.crop(TEAR_SOURCE).resize(TEAR_SIZE, Image.Resampling.LANCZOS)
    tear_alpha = feathered_rect(TEAR_SIZE, inset=3, blur=3.0)
    tear.putalpha(tear_alpha)
    tear_layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    tear_layer.alpha_composite(tear, TEAR_DEST_XY)
    step2 = paste_rgba(step1, tear_layer, (0, 0))

    # Step 3: reuse the single R8 arrow, make it a short foreshortened bolt,
    # rotate its tip down-left, and place it just before the low ice peak.
    arrow = r8.crop(ARROW_SOURCE)
    arrow.putalpha(arrow_mask())
    arrow = arrow.resize(ARROW_SIZE, Image.Resampling.LANCZOS)
    arrow = arrow.rotate(ARROW_ROTATE_DEGREES, resample=Image.Resampling.BICUBIC, expand=True)
    arrow_layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    arrow_layer.alpha_composite(arrow, ARROW_DEST_XY)
    final = paste_rgba(step2, arrow_layer, (0, 0))

    paths = {
        "cleanup_layer": save(cleanup_layer, "E40_U18_A01_R2_LAYER_01_REMOVE_HIGH_ARROW.png"),
        "step1": save(step1.convert("RGB"), "E40_U18_A01_R2_STEP_01_HIGH_ARROW_REMOVED.png"),
        "tear_layer": save(tear_layer, "E40_U18_A01_R2_LAYER_02_TORN_CURTAIN.png"),
        "step2": save(step2.convert("RGB"), "E40_U18_A01_R2_STEP_02_TEAR_RESTORED.png"),
        "arrow_layer": save(arrow_layer, "E40_U18_A01_R2_LAYER_03_LOW_AXIS_ARROW.png"),
        "final": save(final.convert("RGB"), "E40_U18_A01_DETERMINISTIC_COMPOSITE_R2.png"),
    }

    # Exact union mask and difference visualization make the edit falsifiable.
    union_alpha = Image.new("L", CANVAS, 0)
    for layer in (cleanup_layer, tear_layer, arrow_layer):
        union_alpha = ImageChops.lighter(union_alpha, layer.getchannel("A"))
    paths["union_mask"] = save(union_alpha, "E40_U18_A01_R2_UNION_MUTATION_MASK.png")
    difference = ImageChops.difference(r8.convert("RGB"), final.convert("RGB")).convert("L")
    difference = difference.point(lambda value: min(255, value * 4))
    paths["difference"] = save(difference, "E40_U18_A01_R2_DIFFERENCE_X4.png")

    # QA overlay: red arrow axis, cyan gap, green target. This is evidence only.
    overlay = final.convert("RGB")
    draw = ImageDraw.Draw(overlay)
    alpha_bbox = arrow_layer.getchannel("A").getbbox()
    if alpha_bbox is None:
        raise SystemExit("arrow layer is empty")
    arrow_tip = (alpha_bbox[0], round((alpha_bbox[1] + alpha_bbox[3]) / 2))
    tear_bbox = tear_layer.getchannel("A").getbbox()
    draw.line((1438, 1552, *arrow_tip), fill=(255, 50, 50), width=4)
    draw.line((*arrow_tip, *ICE_INTERCEPTION_TARGET), fill=(0, 255, 255), width=4)
    draw.ellipse((ICE_INTERCEPTION_TARGET[0] - 8, ICE_INTERCEPTION_TARGET[1] - 8, ICE_INTERCEPTION_TARGET[0] + 8, ICE_INTERCEPTION_TARGET[1] + 8), outline=(0, 255, 0), width=4)
    draw.rectangle(alpha_bbox, outline=(255, 0, 0), width=3)
    if tear_bbox:
        draw.rectangle(tear_bbox, outline=(255, 255, 0), width=3)
    paths["qa_overlay"] = save(overlay, "E40_U18_A01_R2_GEOMETRY_QA_OVERLAY.png")

    gap_dx = ICE_INTERCEPTION_TARGET[0] - arrow_tip[0]
    gap_dy = ICE_INTERCEPTION_TARGET[1] - arrow_tip[1]
    changed_bbox = union_alpha.getbbox()
    changed_pixels = sum(1 for value in union_alpha.getdata() if value)
    manifest = {
        "schema": "qingshan.e40.deterministic_compositor_manifest.v2",
        "episode": "E40",
        "unit": "U18_A01",
        "status": "CANDIDATE_ZERO_CREDIT_REQUIRES_HUMAN_QA",
        "determinism": {
            "randomness": False,
            "network": False,
            "generative_model": False,
            "source_sha_verified": True,
            "reversible_layers_exported": True,
        },
        "sources": [
            {"role": "R8_BASE_AND_ARROW_DONOR", "path": rel(R8), "sha256": sha(R8)},
            {"role": "R7_TORN_CURTAIN_DONOR", "path": rel(R7), "sha256": sha(R7)},
            {"role": "R6_GEOMETRY_AND_TEAR_MORPHOLOGY_REFERENCE_ONLY", "path": rel(R6), "sha256": sha(R6)},
        ],
        "transforms": {
            "remove_high_arrow": {"source_xyxy": CLEANUP_SOURCE, "destination_xyxy": CLEANUP_DEST, "method": "same_image_same_x_vertical_clone_feathered"},
            "restore_torn_curtain": {"source_xyxy": TEAR_SOURCE, "resize_wh": TEAR_SIZE, "destination_xy": TEAR_DEST_XY, "method": "lanczos_resize_feathered_alpha"},
            "reposition_arrow": {"source_xyxy": ARROW_SOURCE, "resize_wh": ARROW_SIZE, "rotation_degrees_ccw": ARROW_ROTATE_DEGREES, "destination_xy": ARROW_DEST_XY, "method": "tight_manual_alpha_lanczos_bicubic"},
        },
        "geometry": {
            "arrow_layer_bbox_xyxy": alpha_bbox,
            "arrow_tip_proxy_xy": arrow_tip,
            "ice_interception_target_xy": ICE_INTERCEPTION_TARGET,
            "precontact_gap_vector_xy": [gap_dx, gap_dy],
            "precontact_gap_euclidean_px": round((gap_dx * gap_dx + gap_dy * gap_dy) ** 0.5, 3),
            "tear_layer_bbox_xyxy": tear_bbox,
            "mutation_union_bbox_xyxy": changed_bbox,
            "mutation_union_nonzero_pixels": changed_pixels,
            "canvas_pixels": CANVAS[0] * CANVAS[1],
            "mutation_union_ratio": round(changed_pixels / (CANVAS[0] * CANVAS[1]), 6),
        },
        "preservation_claims_for_qa": [
            "R8 pixels remain the base for Chenji hand/identity/white robe, Ashuan, the unique black cat, shoe-owned floor frost, low ice, camera, lighting and period setting.",
            "No layer overlaps Chenji, Ashuan, the black cat, Chenji's planted shoe, or the low-ice body below the selected interception peak.",
            "The only arrow pixels are reused from R8; no second arrow is authored.",
        ],
        "required_human_qa": [
            "Torn opening reads as one right-rear source rather than a pasted panel.",
            "Short foreshortened bolt still reads as one right-to-left arrow with visible fletching.",
            "Arrow tip, visible air gap and low ice peak read on one causal diagonal axis.",
            "Old high arrow is fully absent with no obvious horizontal clone seam.",
            "R8 hand anatomy, three identities, one black cat, white robe, shoe ice ownership and low ice height remain unchanged outside the mutation mask.",
        ],
        "outputs": {},
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    for key, path in paths.items():
        manifest["outputs"][key] = {"path": rel(path), "sha256": sha(path)}
    manifest_path = OUT / "E40_U18_A01_DETERMINISTIC_COMPOSITE_R2_MANIFEST.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "final": rel(paths["final"]), "final_sha256": sha(paths["final"]), "manifest": rel(manifest_path), "manifest_sha256": sha(manifest_path), "geometry": manifest["geometry"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
