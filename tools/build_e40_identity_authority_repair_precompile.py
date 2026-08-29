#!/usr/bin/env python3
"""Precompile one identity-authoritative retry and one zero-cost coverage route for E40."""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

try:
    from image_model_adapter import (
        compile_labeled_flat_identity_transport,
        validate_image_model_contract,
    )
except ModuleNotFoundError:
    from tools.image_model_adapter import (
        compile_labeled_flat_identity_transport,
        validate_image_model_contract,
    )


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/canonical_gap_keyframes_wave2_v1/E40_CANONICAL_GAP_KEYFRAMES_WAVE2_V1.json"
Q1 = ROOT / "qa/e40_remake_20260822/canonical_gap_keyframes_wave2_v1/q1_registered/E40_CANONICAL_GAP_KEYFRAMES_WAVE2_Q1_INDEX_V1.json"
OUT = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/identity_authority_repair_precompile_v1"
MANIFEST = OUT / "E40_IDENTITY_AUTHORITY_REPAIR_PRECOMPILE_V1.json"
PREFLIGHT = ROOT / "qa/e40_remake_20260822/identity_authority_repair_precompile_v1/E40_IDENTITY_AUTHORITY_REPAIR_PREFLIGHT_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    q1 = json.loads(Q1.read_text(encoding="utf-8"))
    if q1.get("status") != "ADMITTED_0_FAILED_2":
        raise SystemExit("Corrected wave-two Q1 isolation is required")
    by_key = {row["task_key"]: row for row in source["tasks"]}
    original = copy.deepcopy(by_key["E40-13-2-S03-KEYFRAME-V1"])
    old_prompt = (ROOT / original["prompt_file"]).read_text(encoding="utf-8")
    body = (
        "本次是身份传输缺口修复，不是无变化重掷。陈迹必须以身份权威映射指定的 native-registry 原图为唯一脸部来源；"
        "空间图、子空间、场景和云妃参考只能定义各自范围，绝对不得平均、混合或重塑陈迹面孔。\n"
        + old_prompt
    )
    sequence, identity_contract, effective_prompt = compile_labeled_flat_identity_transport(
        "E40-13-2-S03-KEYFRAME-V2", original["reference_bindings"], body
    )
    prompt_path = OUT / "prompts/E40-13-2-S03-KEYFRAME-V2.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(effective_prompt, encoding="utf-8")
    original.update({
        "task_key": "E40-13-2-S03-KEYFRAME-V2",
        "prompt_file": str(prompt_path.relative_to(ROOT)), "prompt_sha256": sha(prompt_path),
        "reference_bindings": sequence, "reference_image_sequence": sequence,
        "reference_images": [row["path"] for row in sequence],
        "identity_reference_transport": identity_contract,
        "generation_stage": "SCENE_KEYFRAME",
        "subspace_id": next(
            row["entity_id"] for row in sequence if row.get("role") == "subspace_layout"
        ),
        "space_chain_id": "EGSM-E40-WANGFU-SEQUENCE-001->GSM-WANGFU-HALL-001->" + next(
            row["entity_id"] for row in sequence if row.get("role") == "subspace_layout"
        ),
        "canonical_characters": list((original.get("prompt_contract") or {}).get("visible_characters") or []),
        "status": "READY_FOR_RETRY_AND_EPISODE_BUDGET_ADMISSION",
        "provider_post_allowed": False, "maximum_new_submissions": 0,
        "retry_attempt": 2, "paid_attempt_ordinal": 2,
        "retry_of": "E40-13-2-S03-KEYFRAME-V1",
        "failure_memory": ["Attempt1 attached native bytes but lost role/identity authority in flat provider transport; output identity drifted."],
        "material_change_from_prior_attempt": "Added labeled identity-authority sequence, stable prompt token, soft-transport disclosure and mandatory exact-output InsightFace gate.",
        "prior_prompt_sha256": [by_key["E40-13-2-S03-KEYFRAME-V1"]["prompt_sha256"]],
        "failure_attribution": "MISSING_REFERENCE_ANCHOR",
        "changed_variables": ["REFERENCE_ANCHORS", "PROMPT"],
    })
    original["prompt_contract"]["reference_bindings"] = copy.deepcopy(sequence)
    preflight = validate_image_model_contract(
        original, episode="E40", mode="PAID_SUBMIT", prompt_text=effective_prompt
    )
    if preflight.get("status") != "PASS":
        raise SystemExit("Identity-authoritative repair preflight failed: " + ",".join(preflight["failures"]))
    payload = {
        "schema": "qingshan.e40.identity_authority_repair_precompile.v1",
        "episode": "E40", "compiled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PRECOMPILED_NO_PAID_POST",
        "provider_post_allowed": False, "maximum_new_submissions": 0,
        "tasks": [original],
        "zero_cost_routes": [{
            "unit_id": "E40-13-2-S04", "decision": "SWITCH_COVERAGE",
            "reason": "Face must not be visible; omit identity-generating composition and build a table/frost/grey-sleeve insert locally from exact admitted components.",
            "visible_face_allowed": False, "provider_post_allowed": False,
            "required_output_verification": "VLM_STRUCTURED_NO_VISIBLE_FACE_AND_EXACT_FOUR_FROST_MARKS",
        }],
        "paid_admission_pending": "Retry-cap plus episode paid-reroll <=15%; precompile grants no spend authority.",
    }
    write(MANIFEST, payload)
    write(PREFLIGHT, {
        "schema": "qingshan.e40.identity_authority_repair_preflight.v1",
        "status": "PASS", "manifest_ref": str(MANIFEST.relative_to(ROOT)),
        "manifest_sha256": sha(MANIFEST), "image_model_adapter": preflight,
        "paid_post_count": 0,
    })
    print(json.dumps({
        "status": "PASS_PRECOMPILED_NO_POST",
        "manifest": str(MANIFEST.relative_to(ROOT)), "manifest_sha256": sha(MANIFEST),
        "preflight_sha256": sha(PREFLIGHT),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
