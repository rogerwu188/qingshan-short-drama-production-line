#!/usr/bin/env python3
"""Build the zero-credit, reversible E40 U04 exact start-frame candidate.

The compositor uses only exact-SHA local sources.  It extracts one front-view
Chenji identity/wardrobe plate, one admitted Chenji frost-hand topology crop,
and the admitted E40 hall.  No network, model inference, inpainting, random
sampling, or text rendering is involved.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "working_assets/e40_preproduction_20260808/u04_exact_start_frame_v1"
IDENTITY = ROOT / "assets/reference/e37_plus_20260729/characters/CHAR-chenji-age20-user-turnaround-canonical-v1-20260729.png"
WARDROBE = ROOT / "assets/reference/e40_wardrobe_variants_20260808/characters/CHAR-chenji-age20-plain-white-fine-linen-turnaround-v1-20260808.png"
HALL = ROOT / "working_assets/e40_preproduction_20260808/scene_assets/SCENE-E40-13-HALL-CURTAIN-AXIS_6ca121ab-f635-4bc4-9f21-8708c58e7cfe.png"
HAND = ROOT / "working_assets/e39_keyframes_v3/candidates/E39_E39-U02-A1-STILL-R3_144cbcab-86eb-4ff1-856f-0123e29d47f5.png"
PROMPT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u01_u16_prompt_precompile_v1/prompts/E40-U04-STANDARD-SEEDANCE2-PROMPT-V1.txt"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANONICAL_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"

EXPECTED = {
    IDENTITY: "e5bb8c90683120b2b02e113dc2a12b8530f8c66feaeee7657172807adb8e3373",
    WARDROBE: "f0be95313bbfc29f09b702f31e6b83fef52035117aa41dc551f3c3f02831d021",
    HALL: "affcdf75edd4719b69b3fefad3cffb271c87794fdfc0cba029d8d26af6654b88",
    HAND: "5b3ad2337e400653fb3067557f438fa6c9cb7295c35398774b2a494d12760293",
    SCRIPT: "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
    CANONICAL_MANIFEST: "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
}

CANVAS = (1440, 2560)
WARDROBE_FRONT_CROP = (0, 0, 557, 941)
WARDROBE_RESIZE = (1120, 1892)
WARDROBE_DEST = (-75, 235)
HAND_CROP = (0, 790, 925, 2520)
HAND_RESIZE = (805, 1507)
HAND_ROTATION = -8.0
HAND_DEST = (610, 1000)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def save(image: Image.Image, name: str) -> Path:
    path = OUT / name
    image.save(path)
    return path


def grabcut_person(image: Image.Image) -> Image.Image:
    """Extract the single front-view person, with fixed GrabCut seeds."""
    rgb = np.array(image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    h, w = bgr.shape[:2]
    mask = np.full((h, w), cv2.GC_PR_BGD, dtype=np.uint8)
    # Definite background strips; probable foreground follows the silhouette.
    mask[:, :18] = cv2.GC_BGD
    mask[:, w - 18 :] = cv2.GC_BGD
    mask[:15, :] = cv2.GC_BGD
    fg_poly = np.array(
        [[205, 47], [350, 47], [413, 116], [425, 245], [490, 347],
         [532, 520], [526, 920], [30, 920], [32, 520], [72, 350],
         [140, 245], [145, 120]], dtype=np.int32
    )
    cv2.fillPoly(mask, [fg_poly], cv2.GC_PR_FGD)
    cv2.circle(mask, (279, 177), 105, cv2.GC_FGD, -1)
    cv2.rectangle(mask, (135, 285), (420, 705), cv2.GC_FGD, -1)
    cv2.setRNGSeed(0)
    bgd = np.zeros((1, 65), np.float64)
    fgd = np.zeros((1, 65), np.float64)
    cv2.grabCut(bgr, mask, None, bgd, fgd, 5, cv2.GC_INIT_WITH_MASK)
    alpha = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    alpha = cv2.GaussianBlur(alpha, (0, 0), 1.4)
    rgba = np.dstack((rgb, alpha))
    return Image.fromarray(rgba, "RGBA")


def hand_alpha(size: tuple[int, int]) -> Image.Image:
    """Fixed feathered silhouette for the admitted close hand topology."""
    w, h = size
    points = [
        (0, 55), (355, 78), (478, 212), (500, 405), (650, 555),
        (815, 820), (900, 1110), (905, 1430), (770, 1660),
        (545, 1710), (305, 1660), (130, 1515), (24, 1290), (0, 1020),
    ]
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).polygon(points, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(7.0))


def warm_cinematic(image: Image.Image, brightness: float = 0.82) -> Image.Image:
    arr = np.array(image.convert("RGBA"), dtype=np.float32)
    arr[..., 0] *= 0.91
    arr[..., 1] *= 0.82
    arr[..., 2] *= 0.78
    arr[..., :3] *= brightness
    arr[..., :3] = np.clip(arr[..., :3], 0, 255)
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def main() -> int:
    for path, expected in EXPECTED.items():
        actual = sha(path)
        if actual != expected:
            raise SystemExit(f"source SHA mismatch: {path}: {actual} != {expected}")
    OUT.mkdir(parents=True, exist_ok=True)

    hall = Image.open(HALL).convert("RGB")
    if hall.size != CANVAS:
        raise SystemExit(f"hall canvas mismatch: {hall.size}")
    background = ImageEnhance.Brightness(hall.filter(ImageFilter.GaussianBlur(5.5))).enhance(0.72).convert("RGBA")

    wardrobe_full = Image.open(WARDROBE).convert("RGB")
    actor = grabcut_person(wardrobe_full.crop(WARDROBE_FRONT_CROP))
    actor = actor.resize(WARDROBE_RESIZE, Image.Resampling.LANCZOS)
    actor = warm_cinematic(actor, 0.90)
    actor_layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    actor_layer.alpha_composite(actor, WARDROBE_DEST)

    # Add an off-axis eye-shadow so the expression reads as active recognition,
    # without redrawing facial identity or changing anatomy.
    expression_layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    expr = ImageDraw.Draw(expression_layer)
    expr.ellipse((292, 540, 785, 782), fill=(18, 25, 34, 54))
    expression_layer = expression_layer.filter(ImageFilter.GaussianBlur(64))

    hand_source = Image.open(HAND).convert("RGBA").crop(HAND_CROP)
    hand_source.putalpha(hand_alpha(hand_source.size))
    hand_source = hand_source.resize(HAND_RESIZE, Image.Resampling.LANCZOS)
    hand_source = hand_source.rotate(HAND_ROTATION, resample=Image.Resampling.BICUBIC, expand=True)
    hand_source = warm_cinematic(hand_source, 0.88)
    hand_layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    hand_layer.alpha_composite(hand_source, HAND_DEST)

    # White sleeve bridge: a reversible, texture-bearing polygon sampled from
    # the exact E40 white wardrobe, placed behind the admitted hand topology.
    sleeve_tex = wardrobe_full.crop((80, 345, 520, 925)).resize((760, 930), Image.Resampling.LANCZOS).convert("RGBA")
    sleeve_mask = Image.new("L", sleeve_tex.size, 0)
    ImageDraw.Draw(sleeve_mask).polygon([(0, 70), (520, 0), (755, 425), (620, 790), (300, 920), (0, 710)], fill=235)
    sleeve_mask = sleeve_mask.filter(ImageFilter.GaussianBlur(10))
    sleeve_tex.putalpha(sleeve_mask)
    sleeve_tex = sleeve_tex.rotate(-20, resample=Image.Resampling.BICUBIC, expand=True)
    sleeve_tex = warm_cinematic(sleeve_tex, 0.82)
    sleeve_layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    sleeve_layer.alpha_composite(sleeve_tex, (480, 1100))

    # Exactly one thin frost trace, beginning mid-finger and visibly fading
    # toward the sleeve.  Separate glow/core layers keep the effect count clear.
    frost_glow = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    glow = ImageDraw.Draw(frost_glow)
    frost_path = [(1168, 1728), (1133, 1752), (1098, 1778), (1068, 1805), (1046, 1835), (1030, 1870)]
    glow.line(frost_path, fill=(137, 220, 255, 150), width=18, joint="curve")
    frost_glow = frost_glow.filter(ImageFilter.GaussianBlur(11))
    frost_core = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    core = ImageDraw.Draw(frost_core)
    core.line(frost_path, fill=(224, 249, 255, 232), width=4, joint="curve")
    for x, y in frost_path[1:-1]:
        core.line((x, y, x - 10, y - 14), fill=(203, 241, 255, 185), width=2)
    frost_layer = Image.alpha_composite(frost_glow, frost_core)

    mist_layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    mist = ImageDraw.Draw(mist_layer)
    mist.ellipse((875, 1590, 1335, 2065), fill=(180, 226, 241, 24))
    mist_layer = mist_layer.filter(ImageFilter.GaussianBlur(88))

    vignette = Image.new("L", CANVAS, 0)
    vd = ImageDraw.Draw(vignette)
    vd.rectangle((55, 70, 1385, 2490), fill=170)
    vignette = ImageChops.invert(vignette.filter(ImageFilter.GaussianBlur(115)))
    vignette_layer = Image.new("RGBA", CANVAS, (3, 5, 8, 0))
    vignette_layer.putalpha(vignette.point(lambda p: int(p * 0.54)))

    final = background.copy()
    for layer in (actor_layer, expression_layer, sleeve_layer, hand_layer, mist_layer, frost_layer, vignette_layer):
        final = Image.alpha_composite(final, layer)

    paths = {
        "background": save(background.convert("RGB"), "E40_U04_LAYER_00_HALL_BLURRED_GRADED.png"),
        "actor": save(actor_layer, "E40_U04_LAYER_01_CHENJI_WHITE_FRONT.png"),
        "expression": save(expression_layer, "E40_U04_LAYER_02_RECOGNITION_EYE_SHADOW.png"),
        "sleeve": save(sleeve_layer, "E40_U04_LAYER_03_WHITE_SLEEVE_BRIDGE.png"),
        "hand": save(hand_layer, "E40_U04_LAYER_04_ADMITTED_HAND_TOPOLOGY.png"),
        "mist": save(mist_layer, "E40_U04_LAYER_05_COLD_MIST.png"),
        "frost": save(frost_layer, "E40_U04_LAYER_06_SINGLE_HALF_FROST_TRACE.png"),
        "vignette": save(vignette_layer, "E40_U04_LAYER_07_VIGNETTE.png"),
        "final": save(final.convert("RGB"), "E40_U04_EXACT_START_FRAME_CANDIDATE_V1.png"),
    }

    manifest = {
        "schema": "qingshan.e40.exact_start_frame_manifest.v1",
        "episode": "E40",
        "unit": "U04",
        "status": "CANDIDATE_ZERO_CREDIT_REQUIRES_HUMAN_QA",
        "canonical": {
            "script": {"path": rel(SCRIPT), "sha256": sha(SCRIPT)},
            "manifest": {"path": rel(CANONICAL_MANIFEST), "sha256": sha(CANONICAL_MANIFEST)},
            "compiled_prompt": {"path": rel(PROMPT), "sha256": sha(PROMPT)},
        },
        "sources": [
            {"role": "CHENJI_AGE20_IDENTITY_AUTHORITY", "path": rel(IDENTITY), "sha256": sha(IDENTITY)},
            {"role": "CHENJI_E40_WHITE_WARDROBE_AND_VISIBLE_ACTOR", "path": rel(WARDROBE), "sha256": sha(WARDROBE)},
            {"role": "E40_HALL_SCENE_AUTHORITY", "path": rel(HALL), "sha256": sha(HALL)},
            {"role": "ADMITTED_CHENJI_HAND_POSE_TOPOLOGY_ONLY", "path": rel(HAND), "sha256": sha(HAND),
             "upstream_admission": "qa/e39_keyframes_v3/E39_FAILED8_R3_R2_VISUAL_QA_V1.json", "upstream_score": 67},
        ],
        "determinism": {"network": False, "generative_model": False, "randomness": False,
                        "opencv_rng_seed": 0, "reversible_layers_exported": True, "source_sha_verified": True},
        "composition": {
            "canvas_wh": CANVAS,
            "wardrobe_front_crop_xyxy": WARDROBE_FRONT_CROP,
            "wardrobe_resize_wh": WARDROBE_RESIZE,
            "wardrobe_destination_xy": WARDROBE_DEST,
            "hand_crop_xyxy": HAND_CROP,
            "hand_resize_wh": HAND_RESIZE,
            "hand_rotation_degrees_ccw": HAND_ROTATION,
            "hand_destination_xy": HAND_DEST,
            "frost_path_xy": frost_path,
            "frost_owner": "CHAR-chenji-age20",
            "frost_count": 1,
            "frost_start_state": "already_halfway_up_visible_finger_and_beginning_to_recede",
            "frost_transfer": "NONE",
        },
        "hard_gates_for_human_qa": [
            "single visible actor and no turnaround/collage residue",
            "Chenji age20 identity and exact plain-white wardrobe remain recognizable",
            "one visible Chenji hand owns exactly one thin frost trace",
            "trace is halfway on a finger and can continue inward/recede within 0.5 seconds",
            "expression reads as recognizing poison-game stakes, not blank posing",
            "hall period, warm candle/cold mist contrast, no modern objects",
            "no visible text, pseudo-Chinese, subtitle, logo, or watermark",
            "cinematic insert rather than character-card/poster composition",
        ],
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "paid_submission": False,
        "outputs": {},
    }
    for key, path in paths.items():
        manifest["outputs"][key] = {"path": rel(path), "sha256": sha(path)}
    manifest_path = OUT / "E40_U04_EXACT_START_FRAME_MANIFEST_V1.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"candidate": rel(paths["final"]), "candidate_sha256": sha(paths["final"]),
                      "manifest": rel(manifest_path), "manifest_sha256": sha(manifest_path),
                      "credits": manifest["credits"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
