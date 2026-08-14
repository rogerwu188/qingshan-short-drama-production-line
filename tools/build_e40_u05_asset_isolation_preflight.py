#!/usr/bin/env python3
"""Build a fail-closed U05 source-isolation board and audit manifest.

This deliberately does not composite a shot.  It proves which exact-SHA
sources exist separately and why they cannot truthfully be called a cinematic
U05 start frame without a new natural co-occurrence source.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "working_assets/e40_preproduction_20260808/u05_asset_isolation_preflight_v1"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANONICAL_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
PROMPT = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u01_u16_prompt_precompile_v1/prompts/E40-U05-STANDARD-SEEDANCE2-PROMPT-V1.txt"
BINDING = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/reference_binding/E40_INDEPENDENT_SHOT_REFERENCE_BINDING_MATRIX_V1.json"
IDENTITY = ROOT / "assets/reference/e37_plus_20260729/characters/CHAR-chenji-age20-user-turnaround-canonical-v1-20260729.png"
WARDROBE = ROOT / "assets/reference/e40_wardrobe_variants_20260808/characters/CHAR-chenji-age20-plain-white-fine-linen-turnaround-v1-20260808.png"
HALL = ROOT / "working_assets/e40_preproduction_20260808/scene_assets/SCENE-E40-13-HALL-CURTAIN-AXIS_6ca121ab-f635-4bc4-9f21-8708c58e7cfe.png"
PARTIAL_ACTION = ROOT / "working_assets/e39_keyframes_v2/candidates_r2/E39_E39-U11-A1-STILL-R2_22fbf5dc-a29e-4360-9d8d-a3c7b175bc3f.png"
PARTIAL_ACTION_QA = ROOT / "qa/e39_keyframes_v2/E39_KEYFRAME_R2_AND_FIRST_ATTEMPT_FULL_VISUAL_QA_V1.json"

EXPECTED = {
    SCRIPT: "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
    CANONICAL_MANIFEST: "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
    PROMPT: "52533f54f4df90472e8fdb7ebb465a67ecf3f190a5bc1aef7abced25bbd24dee",
    BINDING: "14881afec26242067f57fd1e5560f75a3ea3b90ef6515341c91b94610ea4ad34",
    IDENTITY: "e5bb8c90683120b2b02e113dc2a12b8530f8c66feaeee7657172807adb8e3373",
    WARDROBE: "f0be95313bbfc29f09b702f31e6b83fef52035117aa41dc551f3c3f02831d021",
    HALL: "affcdf75edd4719b69b3fefad3cffb271c87794fdfc0cba029d8d26af6654b88",
    PARTIAL_ACTION: "c454c7d7f171b93364a5a010a4795db9e0eeedca31c8034b10effa9c0666c42d",
    PARTIAL_ACTION_QA: "92f0d1a22c6142e7767a0afcc977dfbe8dc5cbde8accaabcc2269ed4b22c1eb6",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    names = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for name in names:
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def fit_panel(image: Image.Image, box: tuple[int, int]) -> Image.Image:
    panel = ImageOps.fit(image.convert("RGB"), box, method=Image.Resampling.LANCZOS)
    return ImageEnhance.Contrast(panel).enhance(1.03)


def main() -> int:
    for path, expected in EXPECTED.items():
        actual = sha(path)
        if actual != expected:
            raise SystemExit(f"source SHA mismatch: {rel(path)} {actual} != {expected}")
    OUT.mkdir(parents=True, exist_ok=True)

    canvas = Image.new("RGB", (1440, 2560), (17, 20, 24))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 1440, 172), fill=(98, 18, 22))
    draw.text((55, 34), "E40 U05 - SOURCE ISOLATION ONLY", font=font(54, True), fill=(255, 245, 241))
    draw.text((55, 105), "FAIL-CLOSED: THIS BOARD IS NOT A VIDEO START FRAME", font=font(30, True), fill=(255, 205, 205))

    panels = [
        (HALL, (55, 225, 700, 1075), "A  SCENE AUTHORITY", "Hall/candle/curtain axis exists"),
        (WARDROBE, (740, 225, 1385, 1075), "B  IDENTITY + WARDROBE", "Studio turnaround only; no action hand/pages"),
        (PARTIAL_ACTION, (55, 1150, 700, 2200), "C  ACTION/PROP PARTIAL", "Gray robe + second actor + wrong pages/scene"),
    ]
    for path, (x1, y1, x2, y2), title, subtitle in panels:
        image = Image.open(path)
        canvas.paste(fit_panel(image, (x2 - x1, y2 - y1)), (x1, y1))
        draw.rectangle((x1, y1, x2, y2), outline=(210, 218, 225), width=4)
        draw.rectangle((x1, y2 - 112, x2, y2), fill=(8, 10, 12))
        draw.text((x1 + 20, y2 - 98), title, font=font(28, True), fill=(255, 255, 255))
        draw.text((x1 + 20, y2 - 58), subtitle, font=font(22), fill=(202, 211, 221))

    x1, y1, x2, y2 = (740, 1150, 1385, 2200)
    draw.rectangle((x1, y1, x2, y2), fill=(28, 31, 36), outline=(224, 102, 102), width=5)
    draw.text((x1 + 28, y1 + 28), "MISSING NATURAL CO-OCCURRENCE", font=font(30, True), fill=(255, 166, 166))
    missing = [
        "1. Chenji age-20 white robe in hall",
        "2. Exactly two blank account pages",
        "3. Same right hand owns both pages",
        "4. Page corners 0.5 inch above table",
        "5. Gaze locked to long curtain",
        "6. Speaking face ready for exact lip sync",
        "7. One continuous cinematic light/camera",
    ]
    y = y1 + 112
    for line in missing:
        draw.text((x1 + 34, y), line, font=font(25), fill=(236, 239, 243))
        y += 82
    draw.line((x1 + 30, y + 15, x2 - 30, y + 15), fill=(117, 126, 138), width=2)
    draw.text((x1 + 34, y + 55), "No local source contains all seven.", font=font(27, True), fill=(255, 220, 170))
    draw.text((x1 + 34, y + 105), "Cross-pasting would repeat U04 failure.", font=font(27, True), fill=(255, 220, 170))

    draw.rectangle((55, 2270, 1385, 2495), fill=(11, 13, 16), outline=(226, 90, 90), width=5)
    draw.text((85, 2300), "DECISION  FAIL_CLOSED_NO_NATURAL_LOCAL_EXACT_START_FRAME", font=font(34, True), fill=(255, 150, 150))
    draw.text((85, 2365), "Candidate: NONE  |  Paid submit: BLOCKED  |  Credits: 0", font=font(29, True), fill=(245, 245, 245))
    draw.text((85, 2420), "Allowed next representation: isolated performance source, then human QA >=80.", font=font(25), fill=(202, 211, 221))

    board = OUT / "E40_U05_SOURCE_ISOLATION_BOARD_NOT_A_START_FRAME_V1.png"
    canvas.save(board)

    manifest = {
        "schema": "qingshan.e40.asset_isolation_preflight.v1",
        "episode": "E40",
        "unit": "U05",
        "status": "FAIL_CLOSED_NO_NATURAL_LOCAL_EXACT_START_FRAME",
        "candidate": None,
        "candidate_admitted": False,
        "warning": "The isolation board is QA evidence only and must never be bound as a start frame.",
        "canonical": {
            "script": {"path": rel(SCRIPT), "sha256": sha(SCRIPT)},
            "manifest": {"path": rel(CANONICAL_MANIFEST), "sha256": sha(CANONICAL_MANIFEST)},
            "compiled_prompt": {"path": rel(PROMPT), "sha256": sha(PROMPT)},
            "reference_binding": {"path": rel(BINDING), "sha256": sha(BINDING)},
        },
        "isolated_sources": [
            {"role": "CHENJI_AGE20_IDENTITY_AUTHORITY", "path": rel(IDENTITY), "sha256": sha(IDENTITY), "contains_required_action": False},
            {"role": "CHENJI_E40_WHITE_WARDROBE_AUTHORITY", "path": rel(WARDROBE), "sha256": sha(WARDROBE), "contains_required_action": False},
            {"role": "E40_HALL_SCENE_AUTHORITY", "path": rel(HALL), "sha256": sha(HALL), "contains_required_actor": False},
            {"role": "ADMITTED_ACTION_PROP_PARTIAL_REFERENCE_ONLY", "path": rel(PARTIAL_ACTION), "sha256": sha(PARTIAL_ACTION),
             "admission_qa": {"path": rel(PARTIAL_ACTION_QA), "sha256": sha(PARTIAL_ACTION_QA), "unit": "E39-U11", "score": 83},
             "disqualifiers_for_e40_u05": ["gray robe", "second visible actor", "medicine archive instead of hall", "ledger plus rubbing rather than exactly two blank account pages", "pages already supported by table/book", "no curtain-locked gaze"]},
        ],
        "required_cooccurrence": {
            "visible_actor": "CHAR-chenji-age20 in exact E40 plain-white fine-linen robe",
            "prop_owner_count": "Chenji right hand owns exactly two blank account pages",
            "start_state": "both pages moving downward with corners one-half inch above table",
            "gaze": "Chenji gaze and jaw aimed at long curtain",
            "scene": "admitted E40 hall at fog night with warm interior candle",
            "audio_future_gate": "visible native exact-line audio or verified lip sync for E40-DIA-004",
        },
        "feasibility": {
            "natural_single_source_found": False,
            "deterministic_blank_page_layer_possible": True,
            "deterministic_actor_action_integration_without_collage": False,
            "reason": "No local image contains the required white-robed actor, right-hand page ownership, half-inch precontact state and curtain-directed gaze in one coherent camera/light field.",
            "u04_failure_pattern_forbidden": "Do not paste a studio turnaround and unrelated hand/action donor into the hall.",
        },
        "outputs": {
            "isolation_board_not_a_start_frame": {"path": rel(board), "sha256": sha(board)}
        },
        "credits": {"pay": 0, "refund": 0, "net": 0},
        "paid_submission": False,
        "next_action": "Obtain one isolated cinematic Chenji-white-robe performance source with right hand and two blank pages in the admitted hall geometry; then run original-image human QA >=80 before any video preflight."
    }
    manifest_path = OUT / "E40_U05_ASSET_ISOLATION_PREFLIGHT_MANIFEST_V1.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "candidate": None,
                      "board": rel(board), "board_sha256": sha(board),
                      "manifest": rel(manifest_path), "manifest_sha256": sha(manifest_path),
                      "credits": manifest["credits"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
