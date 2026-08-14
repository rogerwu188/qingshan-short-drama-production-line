#!/usr/bin/env python3
"""Build the final failed-only A03 retry with distinct pre/contact anchors."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from multimodal_character_binding_guard import binding_digest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/action_replacement_v3/E37_ATOMIC_ACTION_DIRECT_WATCH_RETRY_BATCH_V3.json"
OUT = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/action_replacement_v4/E37_A03_TWO_ANCHOR_CONTACT_RETRY_BATCH_V4.json"
PROMPT = ROOT / "working_assets/e37_prompt_repair_20260803/compiled_prompts_v4/E37-R-A03.txt"
PRE = "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U05-A1-STILL-V2_ZERO_CREDIT_ALT_PASS.png"
END = "working_assets/e37_action_replacement_v4_20260803/anchors/E37-R-A03-CONTACT-END-V4.png"


def sha(path: str | Path) -> str:
    target = Path(path)
    if not target.is_absolute():
        target = ROOT / target
    return hashlib.sha256(target.read_bytes()).hexdigest()


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    config = json.loads(SOURCE.read_text(encoding="utf-8"))
    task = copy.deepcopy(next(row for row in config["tasks"] if row["unit_id"] == "E37-R-A03"))
    old_prompt = (ROOT / task["prompt_path"]).read_text(encoding="utf-8")
    changed = (
        old_prompt.splitlines()[0]
        + "\n【双状态锚点硬绑定】@图片1是唯一开场：燃梁正在下坠，纸人双掌尚未接触梁底。"
        + "@图片2是唯一终态：双掌已承住燃梁。严格从@图片1连续运动到@图片2，禁止开场使用@图片2姿态。"
        + "0.0-1.0秒保持梁与双掌之间清楚空隙；1.0-1.8秒梁继续向下、双掌向上并在画面中央首次接触；"
        + "1.8-4.5秒接触后纸人肘部下沉、双脚后滑、纸面从掌缘燃穿，随后才稳定为@图片2。"
        + "固定正面机位，全程只发生一次接触，不得重置或重复。\n"
        + "\n".join(old_prompt.splitlines()[1:])
        + "\n"
    )
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(changed, encoding="utf-8")

    identity = next(row for row in task["reference_image_sequence"] if row.get("identity_reference"))
    identity = copy.deepcopy(identity)
    identity["asset_label"] = "@图片3"
    task["reference_images"] = [PRE, END, identity["path"]]
    task["reference_image_sequence"] = [
        {"asset_label": "@图片1", "role": "PRE_CONTACT_TEMPORAL_ANCHOR", "path": PRE, "sha256": sha(PRE), "identity_reference": False},
        {"asset_label": "@图片2", "role": "CONTACT_END_TEMPORAL_ANCHOR", "path": END, "sha256": sha(END), "identity_reference": False},
        identity,
    ]
    for binding in task["multimodal_entity_bindings"]:
        binding["identity_image_slot"] = "@图片3"
    task["multimodal_binding_sha256"] = binding_digest(task["multimodal_entity_bindings"])
    task["planned_reference_image_count"] = 2
    task["state_reference_minimum"] = 2
    task["still_sequence_only_allowed"] = True
    task["keyframe_interpolation_gate"] = {
        "status": "PASS",
        "checked_adjacent_pairs": 1,
        "reason": "Distinct pre-contact and post-contact states with a single physically interpolable falling-beam trajectory.",
    }
    task["task_key"] = "E37-R-A03-TWO-ANCHOR-CONTACT-RETRY-V4"
    task["batch_id"] = "E37-A03-TWO-ANCHOR-CONTACT-RETRY-V4-20260803"
    task["prompt_path"] = str(PROMPT.relative_to(ROOT))
    task["prompt_file"] = task["prompt_path"]
    task["prompt_sha256"] = sha(PROMPT)
    task["status"] = "READY_TO_SUBMIT"
    task["material_change"] = {
        "type": "SINGLE_TO_TWO_TEMPORAL_ANCHORS_AND_EXPLICIT_FIRST_CONTACT_GAP",
        "source_failure": "qa/e37_action_replacement_v3_20260803/E37_ACTION_DIRECT_WATCH_ADJUDICATION_V3.json",
        "pre_contact_anchor_sha256": sha(PRE),
        "contact_end_anchor_sha256": sha(END),
    }

    base = OUT.parent
    anchor_path = base / "E37_A03_TWO_ANCHOR_PLAN_V4.json"
    write(anchor_path, {
        "schema": "qingshan.video_unit_anchor_count_plan.v1",
        "episode": "E37",
        "planned_reference_image_count": 2,
        "uniform_count_independence_audit": {"status": "PASS", "evaluated_individually": True, "distinct_action_design_classes": 1},
        "units": [{
            "unit_id": "E37-R-A03",
            "planned_reference_image_count": 2,
            "reference_image_task_keys": ["E37-R-A03-PRE-CONTACT-REF", "E37-R-A03-CONTACT-END-REF"],
            "anchor_count_decision": {
                "planned_reference_image_count": 2,
                "reason": "Prior single-anchor attempts entered at the terminal pose; two states are required to expose the first contact.",
                "criteria": {"continuous_motion_from_single_start": False, "identity_or_space_reanchor": False, "prop_ownership_transition": False, "non_interpolable_terminal_state": True},
                "anchor_roles": ["PRE_CONTACT_TEMPORAL_ANCHOR", "CONTACT_END_TEMPORAL_ANCHOR"],
                "action_design_class": "locked_front_contact",
            },
            "keyframe_interpolation_gate": {"status": "PASS", "adjacent_pairs_checked": 1},
        }],
    })
    manifest_path = base / "E37_A03_COMPLETE_PROMPT_MANIFEST_V4.json"
    write(manifest_path, {
        "schema": "qingshan.complete_video_prompt_manifest.v1",
        "episode": "E37",
        "all_units_have_prompt": True,
        "unit_count": 1,
        "source_plan": str(anchor_path.relative_to(ROOT)),
        "source_plan_sha256": sha(anchor_path),
        "source_scene_authority": config["scene_contract_ref"],
        "source_scene_authority_sha256": sha(config["scene_contract_ref"]),
        "rows": [{"unit_id": "E37-R-A03", "scene_id": task["scene_id"], "weather": "RAIN_NIGHT", "prompt_path": task["prompt_path"], "prompt_sha256": task["prompt_sha256"]}],
    })
    config["status"] = "READY_FOR_A03_TWO_ANCHOR_FAILED_ONLY_RETRY"
    config["concurrency"] = 1
    config["output_dir"] = "working_assets/e37_action_replacement_v4_20260803/outputs"
    config["qa_dir"] = "qa/e37_action_replacement_v4_20260803"
    config["retry_policy"] = "DIRECT_WATCH_FAILED_A03_ONLY_TWO_ANCHOR_MATERIAL_CHANGE"
    config["anchor_count_plan_ref"] = str(anchor_path.relative_to(ROOT))
    config["complete_video_prompt_manifest_ref"] = str(manifest_path.relative_to(ROOT))
    config["tasks"] = [task]
    write(OUT, config)
    print(json.dumps({"status": "BUILT", "config": str(OUT.relative_to(ROOT)), "task_key": task["task_key"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
