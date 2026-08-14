#!/usr/bin/env python3
"""Build the local-only U29C Jiaotu/Yunyang exact-start-frame candidate.

The builder is deterministic and source bounded.  It never contacts a provider.
Only the admitted clean hall plate, canonical Jiaotu card, and admitted Yunyang
wardrobe authority are read.  Transparent character layers are retained as QA
evidence before the integrated RGB candidate is written.  V2 materially changes
the Jiaotu matte after V1 was rejected for retained source-room and floor blocks.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / (
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/"
    "u29c_v5_two_identity_depth_layer_v1"
)
LAYERS = OUT / "layers"
QA = ROOT / "qa/e40_preproduction_20260808/u29c_v5_two_identity_depth_layer_v1"

CLEAN_HALL = ROOT / (
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/"
    "full25_next_unit_audit_v1/u29c_v5_clean_hall_plate_v1/"
    "E40_U29C_V5_EMPTY_HALL_TWO_DEPTH_STAGING_PLATE_V1.png"
)
JIAOTU = ROOT / "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg"
YUNYANG = ROOT / (
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/"
    "u25_u28_u29_v3_split_implementation_v1/"
    "zero_cost_source_plate_acquisition_v1/changed_representation_audit_v1/"
    "acquisition_preflight_v1/harvest_v1/admitted_helpers/"
    "E40-U29C-V4-YUNYANG-DISTINCT-WARDROBE-AUTH-IMAGE-ACQ-V1_"
    "a4b1f62c-cd32-4949-b349-b8ec1c9b1656.png"
)

EXPECTED = {
    CLEAN_HALL: "2d18e76c9989618d46c699d976d2f5491e9d662df3c3f40c81f5dd76f6c011a2",
    JIAOTU: "964ec3cd77fd3b51c2c5643e077cd8520c256341d00f6451a9d7044c1866d750",
    YUNYANG: "98f724638f4f873ccc3e28f3be308c5c2be4e1e21fa7ccdf04fedd9418bd2218",
}

FAILURE_MEMORY = QA / "E40_U29C_V5_LOCAL_DEPTH_LAYER_HARD_FAIL_MEMORY_V1.json"
FAILURE_MEMORY_SHA256 = "72004a7122deec1766b88a49151d701d6af14303fd2c2c066e310399a75e587c"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def raw_sha(image: Image.Image, mode: str) -> str:
    return hashlib.sha256(image.convert(mode).tobytes()).hexdigest()


def grabcut(image: Image.Image, rect: tuple[int, int, int, int], iterations: int = 9) -> Image.Image:
    rgb = np.asarray(image.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    mask = np.zeros(bgr.shape[:2], np.uint8)
    background = np.zeros((1, 65), np.float64)
    foreground = np.zeros((1, 65), np.float64)
    cv2.setRNGSeed(40)
    cv2.grabCut(bgr, mask, rect, background, foreground, iterations, cv2.GC_INIT_WITH_RECT)
    alpha = np.where(
        (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
    ).astype(np.uint8)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    alpha = cv2.GaussianBlur(alpha, (5, 5), 0)
    return Image.fromarray(np.dstack([rgb, alpha]), "RGBA")


def crop_to_alpha(image: Image.Image, pad: int = 3) -> Image.Image:
    alpha = np.asarray(image.getchannel("A"))
    ys, xs = np.where(alpha > 8)
    if not len(xs):
        raise RuntimeError("empty alpha after segmentation")
    box = (
        max(0, int(xs.min()) - pad),
        max(0, int(ys.min()) - pad),
        min(image.width, int(xs.max()) + pad + 1),
        min(image.height, int(ys.max()) + pad + 1),
    )
    return image.crop(box)


def refine_jiaotu_matte(layer: Image.Image) -> Image.Image:
    """Remove the two V1 hard-failure regions with a contour-bounded matte.

    The V1 GrabCut result is 201x676 after alpha crop.  It retained a dark room
    block attached to the hair and a rectangular floor bridge between the boots.
    This pass intersects the learned matte with explicit source-coordinate
    exclusions, separates both legs, and keeps the subject pixels otherwise
    unchanged.  It is deliberately deterministic and source bounded.
    """

    if layer.size != (201, 676):
        raise RuntimeError(f"unexpected Jiaotu matte geometry: {layer.size}")
    alpha = np.asarray(layer.getchannel("A"), dtype=np.uint8).copy()

    # Definite source-room exclusion to the viewer-right of the true hair edge.
    head_room = np.array(
        [
            (144, 0), (201, 0), (201, 195), (196, 190), (192, 180),
            (188, 170), (182, 160), (174, 146), (166, 122), (158, 96),
            (153, 68), (149, 42), (145, 20),
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(alpha, [head_room], 0)

    # V1 retained a source-floor rectangle below the skirt.  Clear that region
    # and restore only two independently bounded boot/leg silhouettes.
    original = alpha.copy()
    alpha[535:, :] = 0
    left_leg = np.zeros_like(alpha)
    right_leg = np.zeros_like(alpha)
    cv2.fillPoly(
        left_leg,
        [np.array([(82, 526), (128, 526), (116, 553), (115, 626),
                   (113, 675), (88, 675), (84, 624)], dtype=np.int32)],
        255,
    )
    cv2.fillPoly(
        right_leg,
        [np.array([(153, 526), (195, 526), (194, 675), (163, 675),
                   (162, 553)], dtype=np.int32)],
        255,
    )
    leg_keep = cv2.bitwise_or(left_leg, right_leg)
    alpha[526:, :] = cv2.bitwise_and(original[526:, :], leg_keep[526:, :])

    # Remove the thin prop remnant to viewer-left of the empty hand.
    prop_exclusion = np.zeros_like(alpha)
    cv2.line(prop_exclusion, (0, 361), (34, 329), 255, 10, cv2.LINE_AA)
    cv2.line(prop_exclusion, (0, 374), (30, 340), 255, 7, cv2.LINE_AA)
    alpha = cv2.subtract(alpha, prop_exclusion)

    # Detached bright prop fragments are not part of the connected figure.
    binary = np.where(alpha > 8, 255, 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    if count > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        alpha[labels != largest] = 0

    # Feather only the revised contour and verify the failed regions stay clear.
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0)
    # Re-apply the definite exclusions after feathering so edge blur cannot
    # reintroduce source pixels into either hard-failure region.
    cv2.fillPoly(alpha, [head_room], 0)
    alpha[545:, 110:169] = 0
    alpha[646:, :] = 0
    if np.count_nonzero(alpha[545:, 135:149] > 8):
        raise RuntimeError("rectangular floor bridge survived Jiaotu matte repair")
    if np.count_nonzero(alpha[:150, 184:] > 8):
        raise RuntimeError("source-room head block survived Jiaotu matte repair")
    layer.putalpha(Image.fromarray(alpha, "L"))
    return crop_to_alpha(layer)


def isolate_jiaotu() -> Image.Image:
    # The canonical card's top-right panel is the sole full-front wardrobe view.
    panel = Image.open(JIAOTU).convert("RGB").crop((492, 0, 768, 700))
    rgb = np.asarray(panel)
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    mask = np.full(bgr.shape[:2], cv2.GC_BGD, dtype=np.uint8)
    silhouette = np.array(
        [
            (136, 3), (188, 8), (209, 44), (212, 118), (228, 151),
            (242, 205), (249, 286), (246, 350), (231, 383), (230, 510),
            (229, 603), (214, 640), (220, 698), (151, 698), (139, 620),
            (106, 620), (92, 698), (56, 698), (61, 641), (47, 609),
            (58, 505), (50, 414), (34, 356), (38, 280), (52, 210),
            (75, 162), (96, 138), (96, 60), (111, 20),
        ],
        dtype=np.int32,
    )
    cv2.fillPoly(mask, [silhouette], cv2.GC_PR_FGD)
    # Definite source-subject seeds: hair/face, torso, sleeves, skirt and legs.
    cv2.ellipse(mask, (177, 106), (31, 47), 0, 0, 360, cv2.GC_FGD, -1)
    cv2.ellipse(mask, (178, 58), (30, 42), 0, 0, 360, cv2.GC_FGD, -1)
    cv2.rectangle(mask, (142, 183), (219, 302), cv2.GC_FGD, -1)
    cv2.fillPoly(mask, [np.array([(122, 326), (229, 326), (211, 570), (139, 570)], np.int32)], cv2.GC_FGD)
    cv2.rectangle(mask, (126, 545), (154, 680), cv2.GC_FGD, -1)
    cv2.rectangle(mask, (187, 545), (216, 680), cv2.GC_FGD, -1)
    background = np.zeros((1, 65), np.float64)
    foreground = np.zeros((1, 65), np.float64)
    cv2.setRNGSeed(40)
    cv2.grabCut(bgr, mask, None, background, foreground, 10, cv2.GC_INIT_WITH_MASK)
    alpha = np.where(
        (mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0
    ).astype(np.uint8)
    alpha = cv2.morphologyEx(alpha, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    alpha = cv2.GaussianBlur(alpha, (5, 5), 0)
    layer = Image.fromarray(np.dstack([rgb, alpha]), "RGBA")
    alpha = np.asarray(layer.getchannel("A"), dtype=np.uint8).copy()

    # The source view has a thin baton below the viewer-left hand.  Remove only
    # that prop's alpha; all retained figure pixels remain verbatim card pixels.
    prop_mask = np.zeros_like(alpha)
    cv2.line(prop_mask, (19, 441), (52, 377), 255, 11, cv2.LINE_AA)
    cv2.line(prop_mask, (15, 450), (45, 390), 255, 7, cv2.LINE_AA)
    prop_mask = cv2.GaussianBlur(prop_mask, (7, 7), 0)
    alpha = cv2.subtract(alpha, prop_mask)
    layer.putalpha(Image.fromarray(alpha, "L"))
    return refine_jiaotu_matte(crop_to_alpha(layer))


def isolate_yunyang() -> Image.Image:
    source = Image.open(YUNYANG).convert("RGB")
    return crop_to_alpha(grabcut(source, (205, 110, 610, 1605), 10))


def grade(layer: Image.Image, *, brightness: float, saturation: float,
          warmth: tuple[float, float, float], blur: float) -> Image.Image:
    alpha = layer.getchannel("A")
    rgb = np.asarray(layer.convert("RGB"), dtype=np.float32)
    rgb *= np.array(warmth, dtype=np.float32)[None, None, :]
    rgb = np.clip(rgb, 0, 255).astype(np.uint8)
    work = Image.fromarray(rgb, "RGB")
    work = ImageEnhance.Color(work).enhance(saturation)
    work = ImageEnhance.Brightness(work).enhance(brightness)
    work = Image.merge("RGBA", (*work.split(), alpha))
    if blur > 0:
        work = work.filter(ImageFilter.GaussianBlur(blur))
    return work


def resize_to_height(image: Image.Image, height: int) -> Image.Image:
    width = max(1, round(image.width * height / image.height))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def placed_mask(layer: Image.Image, xy: tuple[int, int], size=(1008, 1792)) -> np.ndarray:
    canvas = Image.new("L", size, 0)
    canvas.paste(layer.getchannel("A"), xy)
    return np.asarray(canvas)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def strict_ocr_text(path: Path) -> tuple[str, str]:
    engine = shutil.which("tesseract")
    if not engine:
        raise RuntimeError("tesseract is required for the strict OCR0 machine gate")
    result = subprocess.run(
        [engine, str(path), "stdout"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return engine, result.stdout.strip()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    LAYERS.mkdir(parents=True, exist_ok=True)
    QA.mkdir(parents=True, exist_ok=True)
    for path, expected in EXPECTED.items():
        actual = sha256(path)
        if actual != expected:
            raise RuntimeError(f"source SHA mismatch: {path}: {actual} != {expected}")
    if sha256(FAILURE_MEMORY) != FAILURE_MEMORY_SHA256:
        raise RuntimeError("V1 hard-failure memory missing or changed; repair forbidden")

    base = Image.open(CLEAN_HALL).convert("RGBA")
    if base.size != (1008, 1792):
        raise RuntimeError(f"unexpected clean-hall dimensions: {base.size}")

    jiaotu = resize_to_height(
        grade(isolate_jiaotu(), brightness=0.73, saturation=0.72,
              warmth=(1.10, 0.96, 0.78), blur=0.15),
        1040,
    )
    yunyang = resize_to_height(
        grade(isolate_yunyang(), brightness=0.56, saturation=0.68,
              warmth=(1.07, 0.94, 0.80), blur=0.65),
        760,
    )
    jiaotu_xy = (58, 707)
    yunyang_xy = (617, 756)

    jiaotu_mask = placed_mask(jiaotu, jiaotu_xy)
    yunyang_mask = placed_mask(yunyang, yunyang_xy)
    overlap = int(np.count_nonzero((jiaotu_mask > 8) & (yunyang_mask > 8)))
    if overlap:
        raise RuntimeError(f"character alpha overlap: {overlap} pixels")

    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(shadow)
    draw.ellipse((100, 1640, 426, 1750), fill=(15, 7, 3, 105))
    draw.ellipse((668, 1432, 899, 1502), fill=(12, 6, 3, 70))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    base.alpha_composite(shadow)
    base.alpha_composite(yunyang, yunyang_xy)
    base.alpha_composite(jiaotu, jiaotu_xy)

    jiaotu_path = LAYERS / "E40_U29C_V5_JIAOTU_NEAR_DEPTH_LAYER_V2.png"
    yunyang_path = LAYERS / "E40_U29C_V5_YUNYANG_FAR_DEPTH_LAYER_V2.png"
    candidate_path = OUT / "E40_U29C_V5_JIAOTU_YUNYANG_EXACT_START_FRAME_CANDIDATE_V2.png"
    jiaotu.save(jiaotu_path, "PNG", compress_level=9, optimize=False)
    yunyang.save(yunyang_path, "PNG", compress_level=9, optimize=False)
    candidate = base.convert("RGB")
    candidate.save(candidate_path, "PNG", compress_level=9, optimize=False)
    ocr_engine, ocr_text = strict_ocr_text(candidate_path)
    if ocr_text:
        raise RuntimeError(f"OCR0 hard gate failed: {ocr_text!r}")

    machine = {
        "schema": "qingshan.e40.u29c.v5.local_depth_layer.machine_qa.v2",
        "status": "PASS_LOCAL_BUILD_PENDING_ORIGINAL_RESOLUTION_HUMAN_QA",
        "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
        "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
        "source_authorities": [
            {"path": str(CLEAN_HALL.relative_to(ROOT)), "sha256": EXPECTED[CLEAN_HALL], "role": "ADMITTED_CLEAN_HALL"},
            {"path": str(JIAOTU.relative_to(ROOT)), "sha256": EXPECTED[JIAOTU], "role": "CANONICAL_JIAOTU_IDENTITY_WARDROBE"},
            {"path": str(YUNYANG.relative_to(ROOT)), "sha256": EXPECTED[YUNYANG], "role": "ADMITTED_YUNYANG_DISTINCT_WARDROBE"},
        ],
        "predecessor_failure_memory": {
            "path": str(FAILURE_MEMORY.relative_to(ROOT)),
            "sha256": FAILURE_MEMORY_SHA256,
            "rejected_candidate_sha256": "d1413ad3811ea73dad33c2c0e209e3e8f7c4304f5f82bb3a54de318f8308a434",
        },
        "layers": {
            "jiaotu_near": {"path": str(jiaotu_path.relative_to(ROOT)), "sha256": sha256(jiaotu_path), "raw_rgba_sha256": raw_sha(jiaotu, "RGBA"), "xy": list(jiaotu_xy), "size": list(jiaotu.size)},
            "yunyang_far": {"path": str(yunyang_path.relative_to(ROOT)), "sha256": sha256(yunyang_path), "raw_rgba_sha256": raw_sha(yunyang, "RGBA"), "xy": list(yunyang_xy), "size": list(yunyang.size)},
        },
        "candidate": {"path": str(candidate_path.relative_to(ROOT)), "sha256": sha256(candidate_path), "raw_rgb_sha256": raw_sha(candidate, "RGB"), "mode": candidate.mode, "dimensions": list(candidate.size)},
        "deterministic_gates": {
            "source_sha_exact": True,
            "visible_person_count_contract": 2,
            "depth_order": "JIAOTU_NEAR_YUNYANG_FAR",
            "nonoverlapping_alpha_pixels": overlap == 0,
            "alpha_overlap_pixel_count": overlap,
            "jiaotu_weapon_alpha_removed": True,
            "jiaotu_source_background_block_removed": True,
            "jiaotu_rectangular_floor_bridge_removed": True,
            "materially_changed_matte_extraction": True,
            "ocr0": True,
            "ocr_engine": ocr_engine,
            "ocr_text": ocr_text,
            "new_provider_pixels": 0,
            "provider_calls": 0,
            "transactions": 0,
            "credits": 0,
        },
        "human_hard_gates_pending": [
            "two people only", "canonical Jiaotu", "canonical Yunyang",
            "distinct period wardrobe", "two empty hands per person", "no Chenji",
            "no animal or weapon", "OCR0", "era", "light direction",
            "occlusion/halo/seam", "score >=80"
        ],
    }
    write_json(QA / "E40_U29C_V5_LOCAL_DEPTH_LAYER_MACHINE_QA_V2.json", machine)
    print(json.dumps(machine, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
