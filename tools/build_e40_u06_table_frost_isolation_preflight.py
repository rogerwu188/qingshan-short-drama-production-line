#!/usr/bin/env python3
"""Build the zero-credit U06 table/frost component and fail-closed audit.

The output is explicitly a scene/VFX component, not a start frame: no local
natural source contains the required white-robed Chenji speaking half-body in
the same hall/table light field.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "working_assets/e40_preproduction_20260808/u06_table_frost_isolation_v1"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANONICAL_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
PROMPT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u01_u16_prompt_precompile_v1/prompts/E40-U06-STANDARD-SEEDANCE2-PROMPT-V1.txt"
BINDING = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/reference_binding/E40_INDEPENDENT_SHOT_REFERENCE_BINDING_MATRIX_V1.json"
HALL = ROOT / "working_assets/e40_preproduction_20260808/scene_assets/SCENE-E40-13-HALL-CURTAIN-AXIS_6ca121ab-f635-4bc4-9f21-8708c58e7cfe.png"
IDENTITY = ROOT / "assets/reference/e37_plus_20260729/characters/CHAR-chenji-age20-user-turnaround-canonical-v1-20260729.png"
WARDROBE = ROOT / "assets/reference/e40_wardrobe_variants_20260808/characters/CHAR-chenji-age20-plain-white-fine-linen-turnaround-v1-20260808.png"

EXPECTED = {
    SCRIPT: "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
    CANONICAL_MANIFEST: "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
    PROMPT: "49da3de9fc01520ec1d9d9e87a2887d86b71d3685aca36e1d9ff462ddc1f7398",
    BINDING: "14881afec26242067f57fd1e5560f75a3ea3b90ef6515341c91b94610ea4ad34",
    HALL: "affcdf75edd4719b69b3fefad3cffb271c87794fdfc0cba029d8d26af6654b88",
    IDENTITY: "e5bb8c90683120b2b02e113dc2a12b8530f8c66feaeee7657172807adb8e3373",
    WARDROBE: "f0be95313bbfc29f09b702f31e6b83fef52035117aa41dc551f3c3f02831d021",
}

CANVAS = (1440, 2560)
TABLE_CROP = (180, 760, 1260, 1660)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def frost_cluster(size: tuple[int, int], full: bool) -> Image.Image:
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    cx, cy = size[0] // 2, size[1] // 2
    branches = [
        ((cx - 92, cy + 5), (cx + 92, cy - 4)),
        ((cx - 55, cy + 3), (cx - 29, cy - 27)),
        ((cx - 10, cy + 1), (cx + 16, cy + 29)),
        ((cx + 40, cy - 2), (cx + 66, cy - 24)),
    ]
    if not full:
        branches = [((a[0], a[1]), ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)) for a, b in branches]
    for a, b in branches:
        draw.line((*a, *b), fill=(211, 245, 255, 205), width=4)
        mx, my = (a[0] + b[0]) // 2, (a[1] + b[1]) // 2
        draw.line((mx, my, mx - 20, my - 18), fill=(188, 234, 250, 190), width=3)
        draw.line((mx, my, mx + 17, my + 20), fill=(188, 234, 250, 190), width=3)
    glow = layer.filter(ImageFilter.GaussianBlur(8))
    return Image.alpha_composite(glow, layer)


def main() -> int:
    for path, expected in EXPECTED.items():
        actual = sha(path)
        if actual != expected:
            raise SystemExit(f"source SHA mismatch: {rel(path)} {actual} != {expected}")
    OUT.mkdir(parents=True, exist_ok=True)

    hall = Image.open(HALL).convert("RGB")
    background = ImageEnhance.Brightness(hall.filter(ImageFilter.GaussianBlur(7))).enhance(0.58).convert("RGBA")
    close = hall.crop(TABLE_CROP).resize((1440, 1200), Image.Resampling.LANCZOS)
    close = ImageEnhance.Contrast(close).enhance(1.10).convert("RGBA")
    close_layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    feather = Image.new("L", (1440, 1200), 255)
    fd = ImageDraw.Draw(feather)
    fd.rectangle((0, 0, 1439, 1199), outline=0, width=30)
    feather = feather.filter(ImageFilter.GaussianBlur(28))
    close.putalpha(feather)
    close_layer.alpha_composite(close, (0, 690))

    frost_layer = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    frost_layer.alpha_composite(frost_cluster((220, 90), True), (460, 1435))
    frost_layer.alpha_composite(frost_cluster((220, 90), False), (760, 1435))
    mist = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    md = ImageDraw.Draw(mist)
    md.ellipse((490, 1260, 1110, 1680), fill=(184, 228, 242, 35))
    mist = mist.filter(ImageFilter.GaussianBlur(86))

    plate = background.copy()
    for layer in (close_layer, mist, frost_layer):
        plate = Image.alpha_composite(plate, layer)
    plate_path = OUT / "E40_U06_TABLE_FROST_COMPONENT_NOT_A_START_FRAME_V1.png"
    close_layer.save(OUT / "E40_U06_LAYER_01_SAME_SCENE_TABLE_CLOSEUP.png")
    frost_layer.save(OUT / "E40_U06_LAYER_02_FIRST_FULL_SECOND_HALF_FROST.png")
    plate.convert("RGB").save(plate_path)

    manifest = {
        "schema": "qingshan.e40.asset_isolation_preflight.v1",
        "episode": "E40",
        "unit": "U06",
        "status": "FAIL_CLOSED_MISSING_NATURAL_ACTOR_PERFORMANCE_SOURCE",
        "candidate": None,
        "candidate_admitted": False,
        "warning": "The table/frost plate is an isolated VFX feasibility component, not a start frame.",
        "canonical": {
            "script": {"path": rel(SCRIPT), "sha256": sha(SCRIPT)},
            "manifest": {"path": rel(CANONICAL_MANIFEST), "sha256": sha(CANONICAL_MANIFEST)},
            "compiled_prompt": {"path": rel(PROMPT), "sha256": sha(PROMPT)},
            "reference_binding": {"path": rel(BINDING), "sha256": sha(BINDING)},
        },
        "sources": [
            {"role": "E40_HALL_AND_TABLE_AUTHORITY", "path": rel(HALL), "sha256": sha(HALL)},
            {"role": "CHENJI_AGE20_IDENTITY_AUTHORITY_NOT_COMPOSITED", "path": rel(IDENTITY), "sha256": sha(IDENTITY)},
            {"role": "CHENJI_WHITE_WARDROBE_AUTHORITY_NOT_COMPOSITED", "path": rel(WARDROBE), "sha256": sha(WARDROBE)},
        ],
        "local_component": {
            "table_crop_xyxy": TABLE_CROP,
            "frost_count_visible_at_start": 2,
            "frost_1_state": "formed",
            "frost_2_state": "half_formed",
            "frost_3_state": "not_yet_visible",
            "frost_4_state": "not_yet_visible",
            "owner": "Chenji future action; actor source absent from component",
            "output": {"path": rel(plate_path), "sha256": sha(plate_path)},
            "is_start_frame": False,
        },
        "feasibility": {
            "same_scene_table_closeup": "FAIL_SURFACE_PLANE_TOO_THIN_FOR_READABLE_FOUR_MARKS",
            "deterministic_first_and_half_second_frost_geometry": "PASS_AS_REVERSIBLE_LAYER_FAIL_AS_SURFACE_CONTACT_READ",
            "four_mark_temporal_order_can_be_authored": "PASS",
            "natural_white_robed_chenji_half_body_in_same_light": "FAIL_MISSING_SOURCE",
            "visible_speaking_face_and_lip_sync_readiness": "FAIL_MISSING_SOURCE",
            "curtain_shadow_listener_response": "FAIL_MISSING_SOURCE",
            "overall_exact_start_frame": "FAIL_CLOSED",
        },
        "forbidden_workaround": "Do not paste the studio wardrobe turnaround into this plate; that repeats U04 collage/anatomy failure.",
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "paid_submission": False,
        "next_action": "Acquire one natural cinematic performance source of white-robed Chenji at this table, with visible face/fingertip and matching curtain light; then combine only same-camera VFX and run human QA >=80."
    }
    manifest_path = OUT / "E40_U06_TABLE_FROST_ASSET_ISOLATION_MANIFEST_V1.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "component": rel(plate_path),
                      "component_sha256": sha(plate_path), "manifest": rel(manifest_path),
                      "manifest_sha256": sha(manifest_path), "credits": manifest["credits"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
