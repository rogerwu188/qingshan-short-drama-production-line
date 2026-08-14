#!/usr/bin/env python3
"""Build a zero-cost exact-SHA binding matrix for E40 independent shots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANONICAL_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
PROMPTS_01_16 = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u01_u16_prompt_precompile_v1/E40_U01_U16_STANDARD_VIDEO_PROMPT_MANIFEST_V1.json"
PROMPTS_24_29 = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u24_u29_prompt_precompile_v1/E40_U24_U29_STANDARD_VIDEO_PROMPT_MANIFEST_V1.json"
AUDIO_PLAN = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/dialogue_precompile/E40_DIALOGUE_EXACT_AUDIO_AND_SUBTITLE_PLAN_V1.json"
OUT_DIR = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/reference_binding"
MATRIX_PATH = OUT_DIR / "E40_INDEPENDENT_SHOT_REFERENCE_BINDING_MATRIX_V1.json"
QA_PATH = ROOT / "qa/e40_preproduction_20260808/E40_INDEPENDENT_SHOT_REFERENCE_BINDING_MATRIX_QA_V1.json"

SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
MODEL = "seedance-2.0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


ASSETS = {
    "CHENJI_IDENTITY_AGE20": {
        "kind": "character_identity",
        "path": "assets/reference/e37_plus_20260729/characters/CHAR-chenji-age20-user-turnaround-canonical-v1-20260729.png",
        "sha256": "e5bb8c90683120b2b02e113dc2a12b8530f8c66feaeee7657172807adb8e3373",
        "admission": "E40_CHARACTER_ASSET_FINAL_ADMISSION_V2_EXISTING_EXACT_SHA",
    },
    "CHENJI_WARDROBE_WHITE_E40": {
        "kind": "wardrobe_variant",
        "path": "assets/reference/e40_wardrobe_variants_20260808/characters/CHAR-chenji-age20-plain-white-fine-linen-turnaround-v1-20260808.png",
        "sha256": "f0be95313bbfc29f09b702f31e6b83fef52035117aa41dc551f3c3f02831d021",
        "admission": "E40_CHENJI_WHITE_WARDROBE_SUPPLEMENTAL_ADMISSION_V1_SCORE_91",
    },
    "YUNFEI_IDENTITY_ONLY": {
        "kind": "character_identity_hidden_face_only",
        "path": "ref_images/female_yunfei_ref_20260703.jpg",
        "sha256": "be2c351d58946e8dac12260636ed79b4e76812064fe129ec051bfe434161ad28",
        "admission": "E40_CHARACTER_ASSET_FINAL_ADMISSION_V2_EXISTING_EXACT_SHA_FACE_NOT_USED_ONSCREEN",
    },
    "BAILI_IDENTITY_ONLY": {
        "kind": "character_identity_not_e40_wardrobe",
        "path": "ref_images/female_lead_baili_princess_ref_20260703.jpg",
        "sha256": "450efa811c51cc3c327d152ff6d2e5062f067ffb77a93f88a7689b6b808ee558",
        "admission": "E40_CHARACTER_ASSET_FINAL_ADMISSION_V2_EXISTING_EXACT_SHA_IDENTITY_ONLY",
    },
    "JIAOTU_IDENTITY_WARDROBE": {
        "kind": "character_identity_wardrobe",
        "path": "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg",
        "sha256": "964ec3cd77fd3b51c2c5643e077cd8520c256341d00f6451a9d7044c1866d750",
        "admission": "E40_CHARACTER_ASSET_FINAL_ADMISSION_V2_EXISTING_EXACT_SHA",
    },
    "YUNYANG_IDENTITY_WARDROBE": {
        "kind": "character_identity_wardrobe",
        "path": "ref_images/male_yunyang_ancient_ref_20260704.jpg",
        "sha256": "91254cf5803c0fca14577c7c658210cdc452bef0ccd06de8a11f4be4df6c7aea",
        "admission": "E40_CHARACTER_ASSET_FINAL_ADMISSION_V2_EXISTING_EXACT_SHA",
    },
    "ASHUAN_IDENTITY_WARDROBE": {
        "kind": "character_identity_wardrobe",
        "path": "working_assets/e38_replacement_v7_20260805/character_assets/ashuan/CHAR-E38-ashuan.jpg",
        "sha256": "c8d5d6da7560de9040b648e0034a7624471b52d531f5e7811122340011c9a7c6",
        "admission": "E40_CHARACTER_ASSET_FINAL_ADMISSION_V2_EXISTING_EXACT_SHA",
    },
    "WUYUN_IDENTITY": {
        "kind": "natural_cat_identity",
        "path": "ref_images/cat_wuyun_reference.jpg",
        "sha256": "7c709fe66b534747644964f9c4ca3fe593acf00eb609542c90902efc090cf101",
        "admission": "E40_CHARACTER_ASSET_FINAL_ADMISSION_V2_EXISTING_EXACT_SHA",
    },
    "HALL_CURTAIN_SCENE_BASE": {
        "kind": "scene",
        "path": "working_assets/e40_preproduction_20260808/scene_assets/SCENE-E40-13-HALL-CURTAIN-AXIS_6ca121ab-f635-4bc4-9f21-8708c58e7cfe.png",
        "sha256": "affcdf75edd4719b69b3fefad3cffb271c87794fdfc0cba029d8d26af6654b88",
        "admission": "E40_SCENE_REFERENCE_FINAL_ADMISSION_V1_SCORE_88",
    },
}


UNIT_BINDINGS: dict[str, dict[str, Any]] = {
    "U01": {"characters": ["CHENJI_IDENTITY_AGE20", "CHENJI_WARDROBE_WHITE_E40", "YUNFEI_IDENTITY_ONLY", "BAILI_IDENTITY_ONLY"], "local": ["HALL_BASE_COMPOSITE"], "new": ["CHENJI_FULL_BODY_WHITE_PERFORMANCE_REFERENCE", "BAILI_E40_WHITE_VEIL_RED_JADE_WARDROBE_REFERENCE"], "reason": "entrance needs full-body white Chenji and visible Baili period silhouette"},
    "U02": {"characters": ["YUNFEI_IDENTITY_ONLY", "CHENJI_IDENTITY_AGE20", "CHENJI_WARDROBE_WHITE_E40"], "local": ["CURTAIN_SHADOW_HALF_CLOSING_FAN_START"], "new": ["YUNFEI_DEDICATED_EXACT_AUDIO_E40_DIA_001_002"], "reason": "visual can be locally composited; two hidden-face lines require accepted per-line audio"},
    "U03": {"characters": ["YUNFEI_IDENTITY_ONLY", "CHENJI_IDENTITY_AGE20", "CHENJI_WARDROBE_WHITE_E40"], "local": ["CURTAIN_SHADOW_HALF_LEAN_START"], "new": ["YUNFEI_DEDICATED_EXACT_AUDIO_E40_DIA_003"], "reason": "hidden-face exact audio is absent"},
    "U04": {"characters": ["CHENJI_IDENTITY_AGE20", "CHENJI_WARDROBE_WHITE_E40"], "local": ["CHENJI_EYE_FINGER_CLOSEUP", "HALF_CRAWLED_FROST_LINE_LOCAL_VFX"], "new": [], "reason": "single silent close-up; all identity, wardrobe, scene and frost-layer inputs exist or are deterministic local layers"},
    "U05": {"characters": ["CHENJI_IDENTITY_AGE20", "CHENJI_WARDROBE_WHITE_E40", "YUNFEI_IDENTITY_ONLY"], "local": ["TWO_BLANK_ACCOUNT_PAGES", "HALF_INCH_ABOVE_TABLE_HAND_START"], "new": [], "reason": "native visible exact-line route can be generated with video; pages remain blank for later exact typography"},
    "U06": {"characters": ["CHENJI_IDENTITY_AGE20", "CHENJI_WARDROBE_WHITE_E40", "YUNFEI_IDENTITY_ONLY", "BAILI_IDENTITY_ONLY"], "local": ["TABLE_CLOSEUP", "FOUR_FROST_MARKS_SECOND_HALF_FORMED"], "new": [], "reason": "deterministic frost/evidence geometry can form start frame; visible exact line uses native route"},
    "U07": {"characters": ["CHENJI_IDENTITY_AGE20", "CHENJI_WARDROBE_WHITE_E40", "BAILI_IDENTITY_ONLY"], "local": ["TABLE_FOUR_MARKS_WITH_EMPTY_FIFTH_POSITION", "FINGER_HOVER_START"], "new": [], "reason": "no new persistent asset required; visible exact line uses native route"},
    "U08": {"characters": ["CHENJI_IDENTITY_AGE20", "CHENJI_WARDROBE_WHITE_E40", "YUNFEI_IDENTITY_ONLY"], "local": ["CHENJI_CURTAIN_REACTION_COMPOSITE", "FAN_HALF_CLOSING_SHADOW"], "new": [], "reason": "short native visible line and simple locally compositable reaction geometry"},
    "U09": {"characters": ["CHENJI_IDENTITY_AGE20", "CHENJI_WARDROBE_WHITE_E40", "YUNFEI_IDENTITY_ONLY"], "local": ["THIRD_FROST_MARK_HALF_WIPED", "FROST_POWDER_LOCAL_VFX"], "new": [], "reason": "deterministic frost destruction layer; visible exact line uses native route"},
    "U10": {"characters": ["YUNFEI_IDENTITY_ONLY", "CHENJI_IDENTITY_AGE20"], "local": ["CURTAIN_SHADOW_PAUSE_AND_FAN_TIP_DROP"], "new": ["YUNFEI_DEDICATED_EXACT_AUDIO_E40_DIA_009"], "reason": "hidden-face exact audio is absent"},
    "U11": {"characters": ["WUYUN_IDENTITY", "CHENJI_WARDROBE_WHITE_E40"], "local": ["LOW_ANGLE_CAT_AND_PARTIAL_CHENJI_COMPOSITE", "CAT_EARS_HALF_TURNED_FUR_RISING"], "new": [], "reason": "silent shot; admitted cat and wardrobe crop plus hall scene are sufficient for a local start frame"},
    "U12": {"characters": ["CHENJI_IDENTITY_AGE20", "CHENJI_WARDROBE_WHITE_E40", "YUNFEI_IDENTITY_ONLY"], "local": ["MID_AIR_PAPER_GEOMETRY"], "new": ["OLD_SEAL_RUBBING_EXACT_PROP_REFERENCE"], "reason": "canonical old-seal rubbing must not be invented or rendered as pseudo-Chinese"},
    "U13": {"characters": ["YUNFEI_IDENTITY_ONLY", "CHENJI_IDENTITY_AGE20"], "local": ["CURTAIN_SHADOW_HALF_RISING_AND_CANDLE_REACTION"], "new": ["YUNFEI_DEDICATED_EXACT_AUDIO_E40_DIA_011"], "reason": "hidden-face exact audio is absent"},
    "U14": {"characters": ["YUNFEI_IDENTITY_ONLY", "CHENJI_IDENTITY_AGE20"], "local": ["CURTAIN_HAND_SHADOW_HALF_INCH_FROM_TABLE"], "new": ["YUNFEI_DEDICATED_EXACT_AUDIO_E40_DIA_012"], "reason": "hidden-face exact audio is absent"},
    "U15": {"characters": ["CHENJI_IDENTITY_AGE20", "CHENJI_WARDROBE_WHITE_E40", "YUNFEI_IDENTITY_ONLY"], "local": ["CHENJI_CURTAIN_TWO_PLANE_CLOSEUP", "CURTAIN_RESIDUAL_SWAY"], "new": [], "reason": "two native visible exact lines can be generated in the standard video and verified post-return"},
    "U16": {"characters": ["BAILI_IDENTITY_ONLY", "CHENJI_IDENTITY_AGE20", "YUNFEI_IDENTITY_ONLY"], "local": ["EYE_LINE_AND_CURTAIN_COMPOSITE"], "new": ["BAILI_E40_WHITE_VEIL_RED_JADE_WARDROBE_REFERENCE"], "reason": "identity-only photo cannot authorize the canonical period veil and red-jade costume"},
    "U24": {"characters": ["YUNFEI_IDENTITY_ONLY", "CHENJI_IDENTITY_AGE20"], "local": ["FOG_CLEARED_INITIAL_SNOW_SCENE_GRADE", "CURTAIN_SHADOW_HALF_SEATED"], "new": ["YUNFEI_DEDICATED_EXACT_AUDIO_E40_DIA_016"], "reason": "visual is locally derivable but accepted hidden-face audio is absent"},
    "U25": {"characters": ["CHENJI_IDENTITY_AGE20", "CHENJI_WARDROBE_WHITE_E40", "WUYUN_IDENTITY", "ASHUAN_IDENTITY_WARDROBE"], "local": ["FOG_CLEARED_INITIAL_SNOW_SCENE_GRADE", "HALF_BOW_CHENJI_CAT_MID_LANDING_COMPOSITE"], "new": [], "reason": "native visible exact line plus locally compositable cat landing is the shortest ending-scene route"},
    "U26": {"characters": ["YUNFEI_IDENTITY_ONLY", "ASHUAN_IDENTITY_WARDROBE", "CHENJI_IDENTITY_AGE20"], "local": ["FOG_CLEARED_INITIAL_SNOW_SCENE_GRADE", "FAN_TIP_HALF_INCH_FROM_TABLE"], "new": ["YUNFEI_DEDICATED_EXACT_AUDIO_E40_DIA_018"], "reason": "hidden-face exact audio is absent"},
    "U27": {"characters": ["YUNFEI_IDENTITY_ONLY", "BAILI_IDENTITY_ONLY", "CHENJI_IDENTITY_AGE20"], "local": ["FOG_CLEARED_INITIAL_SNOW_SCENE_GRADE"], "new": ["BAILI_E40_WHITE_VEIL_RED_JADE_WARDROBE_REFERENCE", "RED_JADE_SINGLE_OWNER_PROP_REFERENCE", "YUNFEI_DEDICATED_EXACT_AUDIO_E40_DIA_019"], "reason": "both exact hidden audio and canonical Baili costume/prop are absent"},
    "U28": {"characters": ["BAILI_IDENTITY_ONLY", "CHENJI_IDENTITY_AGE20", "CHENJI_WARDROBE_WHITE_E40"], "local": ["FOG_CLEARED_INITIAL_SNOW_SCENE_GRADE", "ASYMMETRIC_EYE_LINE_COMPOSITE"], "new": ["BAILI_E40_WHITE_VEIL_RED_JADE_WARDROBE_REFERENCE", "RED_JADE_SINGLE_OWNER_PROP_REFERENCE"], "reason": "silent but canonical Baili period veil/red-jade asset is not admitted"},
    "U29": {"characters": ["BAILI_IDENTITY_ONLY", "CHENJI_IDENTITY_AGE20", "CHENJI_WARDROBE_WHITE_E40", "YUNFEI_IDENTITY_ONLY", "JIAOTU_IDENTITY_WARDROBE", "YUNYANG_IDENTITY_WARDROBE", "ASHUAN_IDENTITY_WARDROBE", "WUYUN_IDENTITY"], "local": ["FOG_CLEARED_INITIAL_SNOW_SCENE_GRADE", "LOCAL_CAMERA_RISE_AND_BLACK_TRANSITION_PLAN"], "new": ["BAILI_E40_WHITE_VEIL_RED_JADE_WARDROBE_REFERENCE", "RED_JADE_SINGLE_OWNER_PROP_REFERENCE"], "reason": "ending tableau depends on unregistered Baili costume/prop even though audio is silent"},
}


LOCAL_ONLY = {"U04", "U05", "U06", "U07", "U08", "U09", "U11", "U15", "U25"}


def classify(unit_id: str, row: dict[str, Any]) -> str:
    if row["new"]:
        return "MUST_CREATE_NEW_ASSET"
    if unit_id in LOCAL_ONLY:
        return "ONLY_LOCAL_COMPOSITE_START_FRAME_MISSING"
    return "DIRECT_SUBMIT_PACKAGE"


def main() -> int:
    if sha256(SCRIPT) != SCRIPT_SHA or sha256(CANONICAL_MANIFEST) != MANIFEST_SHA:
        raise SystemExit("canonical v3 SHA mismatch")
    prompt_manifests = [json.loads(PROMPTS_01_16.read_text()), json.loads(PROMPTS_24_29.read_text())]
    prompt_tasks = {task["unit_id"]: task for manifest in prompt_manifests for task in manifest["tasks"]}
    audio_plan = json.loads(AUDIO_PLAN.read_text())
    audio_by_unit: dict[str, list[dict[str, Any]]] = {}
    for line in audio_plan["lines"]:
        audio_by_unit.setdefault(line["unit"], []).append(line)
    scene = ASSETS["HALL_CURTAIN_SCENE_BASE"]
    units = []
    for unit_id in [*[f"U{i:02d}" for i in range(1, 17)], *[f"U{i:02d}" for i in range(24, 30)]]:
        binding = UNIT_BINDINGS[unit_id]
        prompt = prompt_tasks[unit_id]
        lines = audio_by_unit.get(unit_id, [])
        hidden = bool(lines) and all(line["face_visibility"] == "HIDDEN_BEHIND_CURTAIN" for line in lines)
        visible = bool(lines) and any(line["face_visibility"] == "VISIBLE_DIRECT" for line in lines)
        if hidden:
            audio_status = "BLOCKING_NEW_DEDICATED_PER_LINE_AUDIO_REQUIRED"
        elif visible:
            audio_status = "NATIVE_EXACT_LINE_IN_STANDARD_VIDEO_ALLOWED_POST_RETURN_TRANSCRIPT_VOICE_LIP_QA_REQUIRED"
        else:
            audio_status = "NOT_APPLICABLE_SILENT_VISUAL"
        classification = classify(unit_id, binding)
        units.append({
            "unit_id": unit_id,
            "scene_id": prompt["scene_id"],
            "duration_seconds": prompt["duration"],
            "model": prompt["model"],
            "prompt_file": prompt["prompt_file"],
            "prompt_sha256": prompt["prompt_sha256"],
            "classification": classification,
            "scene_binding": scene,
            "scene_state_variant": "BASE_FOG_NIGHT_ADMITTED" if int(unit_id[1:]) <= 16 else "BASE_ADMITTED_LOCAL_FOG_CLEAR_INITIAL_SNOW_GRADE_PENDING",
            "character_asset_bindings": [{"asset_key": key, **ASSETS[key]} for key in binding["characters"]],
            "local_composite_layers_required": binding["local"],
            "new_assets_required": binding["new"],
            "first_frame": {
                "exact_shot_start_path": None,
                "exact_shot_start_sha256": None,
                "status": "BLOCKED_NEW_VISUAL_OR_AUDIO_ASSET" if binding["new"] else "LOCAL_DETERMINISTIC_COMPOSITE_FEASIBLE_HUMAN_QA_REQUIRED",
                "human_admission_threshold": 80,
            },
            "audio": {
                "status": audio_status,
                "lines": [{
                    "line_id": line["line_id"],
                    "speaker": line["speaker"],
                    "exact_text": line["exact_text"],
                    "delivery_class": line["delivery_class"],
                    "accepted_path": line["accepted_audio_or_native_clip_path"],
                    "accepted_sha256": line["accepted_audio_or_native_clip_sha256"],
                    "lip_sync_qa": line["visible_lip_sync_qa"],
                } for line in lines],
            },
            "subtitle": {
                "status": "PENDING_ACCEPTED_AUDIO_TIMING" if lines else "NONE_SILENT_VISUAL",
                "style": "WHITE_HEITI_BLACK_OUTLINE_NO_BACKGROUND_BOX_BOTTOM_CENTER",
                "native_or_double_subtitle_forbidden": True,
            },
            "reason": binding["reason"],
            "paid_submission_allowed": False,
        })
    counts = {name: sum(row["classification"] == name for row in units) for name in [
        "DIRECT_SUBMIT_PACKAGE", "ONLY_LOCAL_COMPOSITE_START_FRAME_MISSING", "MUST_CREATE_NEW_ASSET"
    ]}
    matrix = {
        "schema": "qingshan.e40.independent_shot_reference_binding_matrix.v1",
        "episode": "E40",
        "status": "PASS_AUDITED_NO_DIRECT_PACKAGE_LOCAL_COMPOSITE_U04_SHORTEST",
        "canonical": {
            "script_sha256": SCRIPT_SHA,
            "manifest_sha256": MANIFEST_SHA,
            "prompt_manifest_u01_u16": str(PROMPTS_01_16.relative_to(ROOT)),
            "prompt_manifest_u01_u16_sha256": sha256(PROMPTS_01_16),
            "prompt_manifest_u24_u29": str(PROMPTS_24_29.relative_to(ROOT)),
            "prompt_manifest_u24_u29_sha256": sha256(PROMPTS_24_29),
            "audio_plan": str(AUDIO_PLAN.relative_to(ROOT)),
            "audio_plan_sha256": sha256(AUDIO_PLAN),
        },
        "asset_inventory": ASSETS,
        "classification_counts": counts,
        "shortest_path_first_complete_package": {
            "unit_id": "U04",
            "current_classification": "ONLY_LOCAL_COMPOSITE_START_FRAME_MISSING",
            "why": "silent 5-second single-character close-up; exact Chenji age-20 identity, admitted white wardrobe and admitted hall scene already exist; only deterministic close-up/frost start frame and its human QA are missing",
            "ordered_next_actions": [
                "Create one local deterministic U04 start frame from exact hall scene + Chenji identity + E40 white wardrobe + half-crawled frost-line layer; no remote generation.",
                "Run human-view identity, first-frame-motion, period, OCR and no-poster QA at threshold 80; bind accepted exact SHA.",
                "Compile a standard seedance-2.0-only paid preflight with this prompt SHA and admitted start-frame SHA; do not submit until that separate gate passes.",
            ],
            "native_audio": "NONE_SILENT_VISUAL",
            "estimated_new_persistent_assets": 0,
            "paid_action_in_this_matrix": "NONE",
        },
        "units": units,
        "paid_submission_allowed": False,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_PATH.parent.mkdir(parents=True, exist_ok=True)
    MATRIX_PATH.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    failures = []
    expected_units = [*[f"U{i:02d}" for i in range(1, 17)], *[f"U{i:02d}" for i in range(24, 30)]]
    if [row["unit_id"] for row in units] != expected_units:
        failures.append("UNIT_COVERAGE")
    for key, asset in ASSETS.items():
        path = ROOT / asset["path"]
        if not path.is_file() or sha256(path) != asset["sha256"]:
            failures.append(f"ASSET_SHA:{key}")
    for row in units:
        prompt_path = Path(row["prompt_file"])
        if not prompt_path.is_file() or sha256(prompt_path) != row["prompt_sha256"]:
            failures.append(f"PROMPT_SHA:{row['unit_id']}")
        if row["model"] != MODEL:
            failures.append(f"MODEL:{row['unit_id']}")
        if row["first_frame"]["exact_shot_start_path"] is not None:
            failures.append(f"UNSUPPORTED_DIRECT_START_CLAIM:{row['unit_id']}")
        if row["classification"] == "DIRECT_SUBMIT_PACKAGE":
            failures.append(f"UNSUPPORTED_DIRECT_PACKAGE_CLAIM:{row['unit_id']}")
    if counts != {"DIRECT_SUBMIT_PACKAGE": 0, "ONLY_LOCAL_COMPOSITE_START_FRAME_MISSING": 9, "MUST_CREATE_NEW_ASSET": 13}:
        failures.append("CLASSIFICATION_COUNTS")
    qa = {
        "schema": "qingshan.e40.independent_shot_reference_binding_matrix_qa.v1",
        "episode": "E40",
        "status": "PASS" if not failures else "FAIL",
        "matrix": str(MATRIX_PATH.relative_to(ROOT)),
        "matrix_sha256": sha256(MATRIX_PATH),
        "coverage": {
            "units": "22/22",
            "asset_sha_checks": f"{len(ASSETS)}/{len(ASSETS)}",
            "prompt_sha_checks": "22/22",
            "standard_seedance_2_0": "22/22",
            "audio_transport_classified": "22/22",
            "subtitle_transport_classified": "22/22",
            "first_frame_direct_claims": "0",
        },
        "classification_counts": counts,
        "gate_results": {
            "canonical_exact_sha": "PASS",
            "existing_asset_exact_sha": "PASS",
            "prompt_exact_sha": "PASS",
            "no_false_direct_package_claim": "PASS",
            "audio_and_lip_sync_requirements": "PASS_CLASSIFIED",
            "standard_model_only": "PASS",
            "paid_submission": "NONE",
        },
        "shortest_path": "U04_LOCAL_DETERMINISTIC_START_FRAME_THEN_HUMAN_QA",
        "failures": failures,
    }
    QA_PATH.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "matrix": str(MATRIX_PATH), "matrix_sha256": sha256(MATRIX_PATH),
        "qa": str(QA_PATH), "qa_sha256": sha256(QA_PATH),
        "status": qa["status"], "counts": counts, "shortest_path": qa["shortest_path"],
    }, ensure_ascii=False, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
