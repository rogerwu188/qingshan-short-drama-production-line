#!/usr/bin/env python3
"""Build zero-POST A2 repairs for the five proven E43 v6 failures.

Four units failed the technical no-readable-text contract.  VU026 failed the
basic plot because the references and prompt let the provider replace the
buyer with the seller in the same screen slot.  This builder changes only
those five tasks and authors every internal beat boundary across cast, map,
props, dialogue, sound, action, camera, and reference identity.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from compile_grouped_seedance_manifest import prompt_text, validate_model_prompt
from grouped_internal_continuity_contract import (
    internal_boundary_id,
    validate_internal_transition_sequence,
)
from shot_media_admission_gate import compute_input_template_id


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e43_v6_20260828"
QA = ROOT / "qa/e43_v6_a2_continuity_repairs"
SOURCE_TASKS = PROD / "E43_V6_TRANSACTIONAL_VIDEO_MANIFEST_AUTHORIZED_V1.json"
SOURCE_GROUPED = PROD / "E43_V6_GROUPED_SEEDANCE_MANIFEST_COMPILED_V1.json"
PROMPT_DIR = PROD / "video_prompts_a2_continuity_repairs"
OUT = PROD / "E43_V6_A2_CONTINUITY_REPAIRS_PRECHECK_V1.json"
TARGETS = ("E43-VU-007", "E43-VU-008", "E43-VU-010", "E43-VU-021", "E43-VU-026")
TEXT_FAILURES = set(TARGETS) - {"E43-VU-026"}
CHENJI_PORTRAIT = "working_assets/e43_v6_keyframes_v1/E43_E43-S04-04-KF-V1_874a7ff5-c702-4130-a91d-235f03d16031.png"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def visible(spec: dict[str, Any]) -> list[str]:
    return sorted({
        str(row.get("character") or "")
        for row in spec.get("cast") or []
        if row.get("character") and row.get("face_visibility") != "OFFSCREEN_VOICE_ONLY"
    })


def props(spec: dict[str, Any]) -> list[str]:
    return sorted({str(row.get("prop") or "") for row in spec.get("props") or [] if row.get("prop")})


def space(spec: dict[str, Any]) -> dict[str, str]:
    source = spec["space"]
    return {key: str(source[key]) for key in ("global", "location", "subspace")}


def sound(spec: dict[str, Any]) -> dict[str, str]:
    source = spec["sound_design"]
    return {key: str(source[key]) for key in ("ambience", "foley", "action_sound")}


def contract(
    uid: str,
    from_id: str,
    to_id: str,
    previous: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    previous_cast, current_cast = visible(previous), visible(current)
    previous_props, current_props = props(previous), props(current)
    previous_space, current_space = space(previous), space(current)
    if previous_cast != current_cast or previous_space != current_space:
        mode = "PAN_REVEAL"
        entry = (
            f"摄影机沿既定人物轴一次性重构图，从{','.join(previous_cast) or '环境'}"
            f"明确揭示{','.join(current_cast) or '环境'}；退场者经画外离开，入场者从真实空间进入"
        )
    else:
        mode = "CONTINUOUS_ACTION"
        entry = "人物构图保持同一轴线，既有人物不退场，新动作从上一结果态直接发生"
    prop_bridge = (
        f"道具从{','.join(previous_props) or '无'}连续到{','.join(current_props) or '无'}；"
        "新增道具必须由人物手部、衣袋或既有桌面真实取出，消失道具必须完成可见交接或离画"
    )
    previous_terminal = str(previous["action"]["completion_state"])
    current_initial = str(current["action"]["start_state"])
    return {
        "boundary_id": internal_boundary_id(uid, from_id, to_id),
        "from_shot_id": from_id,
        "to_shot_id": to_id,
        "transition_mode": mode,
        "authorship": "DIRECTOR_AUTHORED",
        "cast_bridge": {
            "from_visible_characters": previous_cast,
            "to_visible_characters": current_cast,
            "identity_preservation": "所有既有人物面貌、发型、年龄、服装和体型锁定不变，禁止一人变成另一人",
            "entry_exit_or_reveal": entry,
        },
        "scene_bridge": {
            "from_space": previous_space,
            "to_space": current_space,
            "continuity": (
                "保持同一全局地图和地点拓扑，沿画面可见的门、廊、檐、街面或帘幕关系完成空间交接；"
                "固定建筑、光向、天气与时间连续，禁止凭空换景"
            ),
        },
        "prop_bridge": {
            "from_props": previous_props,
            "to_props": current_props,
            "ownership_or_handoff": prop_bridge,
        },
        "sound_bridge": {
            "from_sound": sound(previous),
            "to_sound": sound(current),
            "bridge": "同一环境底声不断裂，上一动作的真实声尾跨过交接，下一次衣料、脚步或道具接触声自然接管",
        },
        "camera_bridge": {
            "axis_strategy": "严格维持既定人物轴同侧；若重构图只沿单一方向移动一次，不反向、不跳轴、不循环运镜",
            "transition_execution": "上一动作结果保持后才执行一次缓慢横移或拉宽，落稳后再开始下一对白或动作",
        },
        "action_bridge": f"上一终态“{previous_terminal}”保持到交接点，下一初态“{current_initial}”从该结果继续，禁止复位重演",
        "reference_bridge": {
            "entity_mapping": "每张参考图只绑定其具名人物、场景或道具；其他偶然入镜者不得被当作交易对象或身份替代",
            "different_character_same_slot_forbidden": True,
            "same_slot_reuse_allowed": False,
        },
    }


def cast_row(character: str, slot: str, plane: str) -> dict[str, Any]:
    return {
        "character": character,
        "screen_slot": slot,
        "depth_plane": plane,
        "face_visibility": "VISIBLE_PER_FRAME_CONTENT",
        "identity_card_required": True,
    }


def prop_row(name: str) -> dict[str, Any]:
    return {"prop": name, "anchor": "PRIMARY_ACTION_PLANE", "continuity_scope": "SCENE_OR_RECURRING_PROP"}


def repair_vu026(unit: dict[str, Any]) -> None:
    """Keep the buyer, seller, and witness distinct throughout the transaction."""
    trio = [
        cast_row("世子", "LEFT_THIRD", "PRIMARY_ACTION_PLANE"),
        cast_row("陈迹", "CENTER", "PRIMARY_ACTION_PLANE"),
        cast_row("小和尚", "RIGHT_THIRD", "REACTION_PLANE"),
    ]
    for index, spec in enumerate(unit["ordered_prompt_specs"]):
        if index == 0:
            # Exact first frame contains only the heir and monk; Chen Ji is
            # revealed from the real street on the first internal handoff.
            continue
        spec["cast"] = copy.deepcopy(trio)
        actors = spec["performance"].setdefault("actor_performance", {})
        for character in ("世子", "陈迹", "小和尚"):
            actors.setdefault(character, {
                "expression_arc": "原有表情因当前交易节点产生一次细微变化并保持",
                "continuous_micro_action": "自然呼吸持续，眼神只在对方台词或道具接触点变化一次",
                "event_reaction": "只对当前买卖动作作角色内反应，不抢先进入下一拍",
                "body_sync": "眼神先行，下颌与肩颈随后，手部或重心最后完成动作",
            })
    unit["ordered_prompt_specs"][1]["props"] = [prop_row("荷包")]
    unit["ordered_prompt_specs"][2]["props"] = [prop_row("荷包"), prop_row("银锭")]
    unit["ordered_prompt_specs"][3]["props"] = [prop_row("银锭")]
    unit["ordered_prompt_specs"][4]["props"] = [prop_row("银锭"), prop_row("纸")]
    unit["narrative_beat"] = (
        "世子与小和尚在街口檐下等到陈迹走近；摄影机拉宽让三人同框，世子只向陈迹问价并出十两，"
        "陈迹只向世子说成交并把无可读字的药方纸递给世子，小和尚始终只在侧后方见证"
    )
    unit["camera_plan"].update({
        "motion_family": "DOLLY",
        "motion_direction": "PULL_OUT",
        "start_framing": "竖屏中景：黑衣世子在左，小和尚在右，街口檐柱和雨湿石路建立真实空间",
        "end_framing": "竖屏三人关系中景：黑衣世子左、灰衣陈迹中、灰衣小和尚右后；银锭与无字纸只在世子和陈迹之间交接",
        "motivation": "陈迹沿真实街道走近触发一次缓慢拉宽；三人同框后镜头落稳，交易只发生在世子与陈迹之间",
        "axis_relation": "固定世子—陈迹交易轴，小和尚永远在反应层；全段不跨轴，不把任一人物替换成另一人物",
        "signature": "DOLLY:PULL_OUT",
    })
    start = unit["reference_images"][0]
    unit["reference_images"] = [
        start,
        {"path": CHENJI_PORTRAIT, "sha256": sha(ROOT / CHENJI_PORTRAIT), "role": "CHARACTER_REFERENCE_CHENJI_ONLY"},
    ]


def add_pixel_text_isolation(text: str) -> str:
    marker = "【节拍内连续性硬合同】"
    isolation = (
        "【像素文字隔离硬合同】所有对白只作为人物现场发声存在于同任务原生音轨；画面从第一帧到最后一帧"
        "不得出现任何汉字、字母、数字、字幕、对白转写、标题卡、匾额、标牌、书写、LOGO或水印。"
        "说话只呈现口型、呼吸、眼神和身体反应，绝不把语句内容可视化。\n"
    )
    if marker not in text:
        raise ValueError("compiled prompt lacks internal continuity section")
    return text.replace(marker, isolation + marker, 1) + "\n【防复犯收束】对白必须听见但绝不可看见；任何可读字符均视为技术失败。"


def main() -> int:
    source = json.loads(SOURCE_TASKS.read_text(encoding="utf-8"))
    grouped = json.loads(SOURCE_GROUPED.read_text(encoding="utf-8"))
    source_tasks = {row["unit_id"]: row for row in source["tasks"]}
    source_units = {row["unit_id"]: row for row in grouped["units"]}
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    tasks: list[dict[str, Any]] = []
    repair_units: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []

    for uid in TARGETS:
        unit = copy.deepcopy(source_units[uid])
        if uid == "E43-VU-026":
            repair_vu026(unit)
        shot_ids = [str(value) for value in unit["editorial_shot_ids"]]
        specs = unit["ordered_prompt_specs"]
        unit["internal_transition_contracts"] = [
            contract(uid, shot_ids[index], shot_ids[index + 1], specs[index], specs[index + 1])
            for index in range(len(specs) - 1)
        ]
        unit["internal_transition_contracts"] = validate_internal_transition_sequence(unit)
        compiled = prompt_text(unit)
        if uid in TEXT_FAILURES:
            compiled = add_pixel_text_isolation(compiled)
        if uid == "E43-VU-026":
            compiled += (
                "\n【交易对象硬锁】黑衣世子是唯一买方，灰衣陈迹是唯一卖方，小和尚只是右后方见证人。"
                "世子向陈迹问价并把银锭递给陈迹；陈迹向世子说成交并把无可读字的纸递给世子。"
                "三人脸、发型、服装、身高始终各自锁定；禁止硬切换人、变脸、换衣、让小和尚收钱或收纸。"
            )
        prompt_path = PROMPT_DIR / f"{uid}.txt"
        prompt_path.write_text(compiled, encoding="utf-8")
        prompt_report = validate_model_prompt(compiled, source_id=f"{uid}-A2")
        if prompt_report["status"] != "PASS":
            raise ValueError(f"{uid} repaired prompt invalid: {prompt_report['failures']}")

        original = source_tasks[uid]
        task = copy.deepcopy(original)
        task.update({
            "task_key": f"{uid}-VIDEO-A2-CONTINUITY-REPAIR",
            "prompt_file": rel(prompt_path),
            "prompt_sha256": sha(prompt_path),
            "model_prompt_contract": prompt_report,
            "provider_post_allowed": False,
            "remote_task_id": None,
            "retry_attempt": 2,
            "creative_attempt_ordinal": 2,
            "paid_attempt": 1,
            "editorial_shot_ids": shot_ids,
            "internal_transition_contracts": unit["internal_transition_contracts"],
            "prior_prompt_sha256": [original["prompt_sha256"]],
            "same_creative_prompt_intentional": False,
            "content_attempt_consumed_by_prior_failure": True,
            "material_change_from_prior_attempt": (
                "Added authored internal beat continuity across cast, exact map space, props and ownership, dialogue speakers, "
                "native ambience/foley, action terminal-to-initial state, camera axis, and reference identity."
            ),
        })
        task["machine_contract"] = {
            **copy.deepcopy(task.get("machine_contract") or {}),
            "camera_plan": unit["camera_plan"],
            "ordered_prompt_specs": specs,
            "editorial_shot_ids": shot_ids,
            "internal_transition_contracts": unit["internal_transition_contracts"],
        }
        if uid in TEXT_FAILURES:
            classification = "PROVIDER_HEALTHY_CONTENT_FAILURE_BURNED_IN_READABLE_TEXT"
            task["prior_failure_classifications"] = [classification]
            task["do_not_repeat"] = [
                "Do not render dialogue as visible characters, captions, signs, title cards, or overlays.",
                "Do not reuse the A1 prompt SHA.",
            ]
        else:
            classification = "BASIC_PLOT_FAILURE_CHARACTER_COUNTERPARTY_REPLACEMENT"
            task["prior_failure_classifications"] = [classification]
            task["reference_images"] = [str(row["path"]) for row in unit["reference_images"]]
            task["reference_sha256"] = [str(row["sha256"]) for row in unit["reference_images"]]
            task["reference_roles"] = [str(row["role"]) for row in unit["reference_images"]]
            task["reference_image_sequence"] = [
                {"entity_id": "CHAR-E43-SHIZI", "role": "CHARACTER_AND_START_FRAME_REFERENCE", "path": task["reference_images"][0], "sha256": task["reference_sha256"][0]},
                {"entity_id": "CHAR-E43-XIAOHESHANG", "role": "CHARACTER_AND_START_FRAME_REFERENCE", "path": task["reference_images"][0], "sha256": task["reference_sha256"][0]},
                {"entity_id": "CHAR-E43-CHENJI", "role": "CHARACTER_REFERENCE", "path": task["reference_images"][1], "sha256": task["reference_sha256"][1]},
            ]
            task["canonical_characters"] = ["CHAR-E43-SHIZI", "CHAR-E43-CHENJI", "CHAR-E43-XIAOHESHANG"]
            # Common hand props are fully constrained in the prompt-level prop
            # bridge.  Do not fabricate a visual anchor binding for them: the
            # two admitted references intentionally cover only the exact start
            # composition and Chen Ji's identity.
            task["canonical_props"] = []
            task["action_end_blocking"]["props"] = []
            task["trajectory_overlays"] = [
                row for row in task.get("trajectory_overlays") or []
                if str(row.get("entity_id") or "").startswith("CHAR-")
            ]
            task["do_not_repeat"] = [
                "Do not use the A1 seller-with-monk transaction references.",
                "Do not replace the heir with Chen Ji in the same slot or make the monk the transaction counterparty.",
                "Do not reuse the A1 prompt SHA.",
            ]
        failure = {
            "schema": "qingshan.video_content_failure_memory.v1",
            "episode": "E43",
            "version": "v6",
            "unit_id": uid,
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "status": "RECORDED_CONTENT_FAILURE_RETRY_ALLOWED",
            "failure_classification": classification,
            "prior_task_key": original["task_key"],
            "prior_prompt_sha256": original["prompt_sha256"],
            "candidate": f"working_assets/e43_v6_video_units_a1/{uid}.mp4",
            "candidate_sha256": sha(ROOT / f"working_assets/e43_v6_video_units_a1/{uid}.mp4"),
            "do_not_repeat": task["do_not_repeat"],
            "creative_attempt_consumed": 1,
            "next_creative_attempt": 2,
            "maximum_creative_attempts": 3,
        }
        failure_path = QA / f"{uid}_A1_FAILURE_MEMORY_V1.json"
        write(failure_path, failure)
        task["failure_memory"] = {"ref": rel(failure_path), "sha256": sha(failure_path)}
        task["input_template_id"] = compute_input_template_id(task)
        tasks.append(task)
        repair_units.append(unit)
        audit_rows.append({
            "unit_id": uid,
            "status": "PASS",
            "prior_prompt_sha256": original["prompt_sha256"],
            "repair_prompt_sha256": sha(prompt_path),
            "materially_changed": original["prompt_sha256"] != sha(prompt_path),
            "editorial_beat_count": len(specs),
            "internal_boundary_count": len(unit["internal_transition_contracts"]),
            "continuity_dimensions": ["CHARACTER_IDENTITY", "SCENE_AND_MAP", "PROPS_AND_OWNERSHIP", "DIALOGUE_SPEAKER", "AMBIENCE_FOLEY_ACTION_SOUND", "ACTION_STATE", "CAMERA_AXIS", "REFERENCE_ENTITY_MAPPING"],
        })

    gate = {
        "schema": "qingshan.e43.v6.a2_full_continuity_prompt_gate.v1",
        "episode": "E43",
        "status": "PASS",
        "task_count": len(tasks),
        "all_materially_changed": all(row["materially_changed"] for row in audit_rows),
        "all_internal_boundaries_authored": True,
        "rows": audit_rows,
        "provider_post_count": 0,
    }
    gate_path = QA / "E43_V6_A2_FULL_CONTINUITY_PROMPT_GATE_V1.json"
    write(gate_path, gate)
    grouped_out = PROD / "E43_V6_A2_CONTINUITY_REPAIRS_GROUPED_MANIFEST_V1.json"
    write(grouped_out, {
        "schema": "qingshan.grouped_seedance_repair_manifest.v1",
        "episode": "E43",
        "status": "PASS",
        "units": repair_units,
    })
    manifest = {
        key: copy.deepcopy(value)
        for key, value in source.items()
        if key not in {"tasks", "authorization_binding"}
    }
    manifest.update({
        "schema": "qingshan.giggle_video_content_retry_manifest.v2_internal_continuity",
        "authorization_ref": "ROGER-20260828-UPGRADE-PIPELINE-THEN-REPAIR-CURRENT-FIVE-E43-UNITS",
        "provider_post_allowed": False,
        "source_grouped_manifest": rel(grouped_out),
        "source_grouped_manifest_sha256": sha(grouped_out),
        "video_unit_count": len(tasks),
        "reference_image_count": sum(len(task["reference_images"]) for task in tasks),
        "runtime_seconds": sum(int(task["duration_seconds"]) for task in tasks),
        "tasks": tasks,
        "machine_gate_reports": [*(source.get("machine_gate_reports") or []), rel(gate_path)],
        "repair_scope": list(TARGETS),
        "partial_repair_scope": True,
        "provider_post_count": 0,
    })
    write(OUT, manifest)
    summary = {
        "status": "PASS_ZERO_POST_BUILD",
        "tasks": len(tasks),
        "runtime_seconds": manifest["runtime_seconds"],
        "manifest": rel(OUT),
        "manifest_sha256": sha(OUT),
        "gate": rel(gate_path),
    }
    write(QA / "E43_V6_A2_CONTINUITY_REPAIR_BUILD_SUMMARY_V1.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
