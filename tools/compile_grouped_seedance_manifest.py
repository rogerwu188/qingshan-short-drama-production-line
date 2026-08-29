#!/usr/bin/env python3
"""Compile editorial Seedance rows into scene-local grouped video-unit preflight rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

try:
    from tools.video_prompt_action_density_gate import validate_action_timeline
    from tools.grouped_camera_contract import (
        camera_signature,
        compile_camera_prompt,
        validate_camera_plan,
        validate_camera_sequence,
    )
    from tools.grouped_performance_contract import (
        compile_performance_clause,
        compile_visual_sound_clause,
        validate_grouped_beat_contract,
    )
    from tools.grouped_transition_contract import (
        compile_transition_prompt,
        validate_transition_sequence,
    )
    from tools.grouped_anchor_semantic_contract import validate_start_anchor_semantics
    from tools.grouped_internal_continuity_contract import (
        compile_internal_transition_prompt,
        validate_internal_transition_sequence,
    )
    from tools.dialogue_cut_safety import compile_dialogue_windows
    from tools.wardrobe_identity_contract import (
        validate_wardrobe_contract,
        wardrobe_prompt_block,
        wardrobe_rows_for_cast,
    )
    from tools.pose_transition_anchor_gate import evaluate as evaluate_pose_anchors
except ModuleNotFoundError:  # Direct CLI execution from tools/.
    from video_prompt_action_density_gate import validate_action_timeline
    from grouped_camera_contract import (
        camera_signature,
        compile_camera_prompt,
        validate_camera_plan,
        validate_camera_sequence,
    )
    from grouped_performance_contract import (
        compile_performance_clause,
        compile_visual_sound_clause,
        validate_grouped_beat_contract,
    )
    from grouped_transition_contract import compile_transition_prompt, validate_transition_sequence
    from grouped_anchor_semantic_contract import validate_start_anchor_semantics
    from grouped_internal_continuity_contract import (
        compile_internal_transition_prompt,
        validate_internal_transition_sequence,
    )
    from dialogue_cut_safety import compile_dialogue_windows
    from wardrobe_identity_contract import (
        validate_wardrobe_contract,
        wardrobe_prompt_block,
        wardrobe_rows_for_cast,
    )
    from pose_transition_anchor_gate import evaluate as evaluate_pose_anchors


ROOT = Path(__file__).resolve().parents[1]
MODEL_PROMPT_POLICY_VERSION = "qingshan.seedance_model_prompt_complete.v6_internal_continuity"
# Giggle accepts prompts up to 10,000 characters.  Keep transport headroom but
# never compact away cinematography, performance, visual, or sound contracts.
MAX_MODEL_PROMPT_CHARS = 8000
FORBIDDEN_MODEL_PROMPT_TOKENS = (
    "sha256",
    "GLOBAL-SPACE-",
    "LOC-",
    "SUB-",
    "PF-",
    "generation_prompt_failure_memory_ref",
    "identity_card_required",
    "【空间层级】",
    "【起始锚点】",
    "【逐节拍完整合同】",
    "【历史失败防复犯绑定】",
)

NATIVE_VIDEO_MODEL_RESOLUTIONS = {
    # Giggle's registered SD2 multi-reference route is provider-native 720p
    # (480p is intentionally not a production target).  Higher delivery
    # rasters must be produced by the release upscaler, never mislabeled here.
    "seedance-2.0-pro": {"720p"},
    "MiniMax-H3": {"768p"},
}


def model_display_name(model: str) -> str:
    return {
        "seedance-2.0-pro": "seedance-2.0-pro（SD2 标准版）",
        "MiniMax-H3": "MiniMax-H3",
    }.get(model, model)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def build_writer_agent_provenance(
    directing_script_path: Path, generation_contract_path: Path
) -> dict[str, str]:
    """Bind immutable Writer sources every time a preflight config is rebuilt."""
    return {
        "status": "PASS",
        "provenance_type": "claude_writer_script",
        "source_script": relative(directing_script_path),
        "source_script_sha256": digest(directing_script_path),
        "production_manifest": relative(generation_contract_path),
        "production_manifest_sha256": digest(generation_contract_path),
    }


def normalized_weather(value: object) -> str:
    return str(value or "").strip().upper()


def action_timeline(unit: dict[str, Any]) -> list[dict[str, Any]]:
    """Expand authored beats into <=3s physical phases for the density gate.

    A long spoken beat is not permission for the model to hold or repeat one
    gesture.  Each phase advances contact -> reaction -> settled result while
    preserving one causal action and one final state.
    """
    rows: list[dict[str, Any]] = []
    cursor = 0.0
    specs = unit["ordered_prompt_specs"]
    for index, spec in enumerate(specs):
        action = spec.get("action") or {}
        source_duration = float(action.get("t1_seconds", 0)) - float(action.get("t0_seconds", 0))
        cast = [str(row.get("character")) for row in spec.get("cast") or [] if row.get("character")]
        props = [str(row.get("prop")) for row in spec.get("props") or [] if row.get("prop")]
        space = spec.get("space") or {}
        subject = "、".join(cast or props) or "场内物件"
        contact = "、".join(props) or str(space.get("subspace") or space.get("location") or "地面与空气")
        primary = str(action.get("primary_action") or action.get("start_state") or "").strip()
        terminal = str(action.get("completion_state") or primary).strip()
        phase_count = max(1, int(math.ceil(source_duration / 3.0)))
        phase_duration = source_duration / phase_count
        for phase_index in range(phase_count):
            start = cursor
            end = round(cursor + phase_duration, 3)
            if index == len(specs) - 1 and phase_index == phase_count - 1:
                end = float(unit["duration_seconds"])
            if phase_count == 1:
                phase_action = primary
                phase_terminal = terminal
                phase_state = f"{action.get('start_state') or primary} -> {terminal}"
            elif phase_index == 0:
                phase_action = f"{primary}；先完成接触或开口起势"
                phase_terminal = "接触点已成立，视线开始承接事件"
                phase_state = f"{action.get('start_state') or primary} -> 接触点成立"
            elif phase_index == phase_count - 1:
                phase_action = "眼神、下颌与肩颈沿既定因果继续响应"
                phase_terminal = terminal
                phase_state = f"接触后的身体响应 -> {terminal}"
            else:
                phase_action = "接触后的眼神与下颌承接事件，重心继续沿既定方向移动"
                phase_terminal = "肩颈与重心抵达终态前的连续中间态"
                phase_state = "接触点成立 -> 身体响应中间态"
            rows.append({
                "start_seconds": start,
                "end_seconds": end,
                "source_spec_index": index,
                "phase_index": phase_index + 1,
                "phase_count": phase_count,
                "actions": [
                    f"主体={subject}；动作={phase_action}；接触点={contact}；"
                    f"方向={action.get('motion_direction') or '由起态连续走向结果态'}；终态={phase_terminal}"
                ],
                "state_change": phase_state,
                "action_budget_seconds": round(end - start, 3),
            })
            cursor = end
    return rows


def beat_timeline(unit: dict[str, Any]) -> list[dict[str, float]]:
    """Return one full prompt span per authored beat, independent of density phases."""
    rows: list[dict[str, float]] = []
    cursor = 0.0
    specs = unit["ordered_prompt_specs"]
    for index, spec in enumerate(specs):
        action = spec.get("action") or {}
        source_duration = float(action.get("t1_seconds", 0)) - float(action.get("t0_seconds", 0))
        end = round(cursor + source_duration, 3)
        if index == len(specs) - 1:
            end = float(unit["duration_seconds"])
        rows.append({"start_seconds": cursor, "end_seconds": end})
        cursor = end
    return rows


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _spoken_text(raw: str) -> str:
    speaker, separator, spoken = raw.partition("：")
    return spoken.strip() if separator and speaker.strip() else raw.strip()


def _same_phrase(left: str, right: str) -> bool:
    punctuation = "，。！？；：、,.!?;:‘’“”\"' "
    return left.strip(punctuation) == right.strip(punctuation)


def _trim_sentence_end(value: str) -> str:
    return value.strip().rstrip("。！？；,.!?; ")


def compact_beat_line(spec: dict[str, Any], timeline: dict[str, Any]) -> str:
    action = spec.get("action") or {}
    dialogue = str(spec.get("dialogue") or "").strip()
    spoken = _spoken_text(dialogue)
    primary = _trim_sentence_end(str(action.get("primary_action") or ""))
    terminal = _trim_sentence_end(str(action.get("completion_state") or ""))
    start = float(timeline["start_seconds"])
    end = float(timeline["end_seconds"])
    cast = _unique([str(row.get("character") or "") for row in spec.get("cast") or []])
    subject = "、".join(cast)
    if dialogue and _same_phrase(primary, spoken):
        visual = terminal or _trim_sentence_end(str(action.get("start_state") or ""))
    else:
        visual = primary or terminal
        if terminal and not _same_phrase(visual, terminal):
            visual = f"{_trim_sentence_end(visual)}，最终{terminal}"
    starts_with_named_cast = any(visual.startswith(name) for name in cast)
    performance = f"{subject}：{visual}" if subject and visual and not starts_with_named_cast else visual or subject
    if dialogue:
        speaker, _, words = dialogue.partition("：")
        words = words.strip()
        performance = f"{_trim_sentence_end(performance)}；{speaker.strip()}说：“{words}”" if performance else f"{speaker.strip()}说：“{words}”"
    suffix = "" if len(performance) >= 2 and performance.endswith("”") and performance[-2] in "。！？" else "。"
    performance_contract = compile_performance_clause(spec)
    physics = (
        f"接触={action['contact_point']}；方向={action['motion_direction']}；"
        f"因果={action['physical_causality']}"
    )
    return (
        f"{start:g}–{end:g}秒：{performance}{suffix} 物理动作链：{physics}。"
        f"表演硬锁：{performance_contract}。"
    )


def validate_model_prompt(text: str, *, source_id: str) -> dict[str, Any]:
    failures: list[str] = []
    if len(text) > MAX_MODEL_PROMPT_CHARS:
        failures.append(f"MODEL_PROMPT_TOO_LONG:{source_id}:{len(text)}>{MAX_MODEL_PROMPT_CHARS}")
    for token in FORBIDDEN_MODEL_PROMPT_TOKENS:
        if token in text:
            failures.append(f"MODEL_PROMPT_CONTAINS_MACHINE_TOKEN:{source_id}:{token}")
    if text.count("【天气硬合同】") != 1:
        failures.append(f"MODEL_PROMPT_WEATHER_CONTRACT_COUNT:{source_id}:{text.count('【天气硬合同】')}")
    required_sections = (
        "【节拍】", "【同任务原生声音】", "【镜头硬合同】",
        "【视觉与现场声硬合同】", "【转场硬合同】", "【节拍内连续性硬合同】",
        "【服装身份硬合同】", "【对白安全切点】",
    )
    if any(section not in text for section in required_sections):
        failures.append(f"MODEL_PROMPT_REQUIRED_SECTION_MISSING:{source_id}")
    for marker in ("入场边界=", "入场预留=", "出场边界=", "片尾转场预留="):
        if text.count(marker) != 1:
            failures.append(f"MODEL_PROMPT_TRANSITION_MARKER_COUNT:{source_id}:{marker}:{text.count(marker)}")
    for phrase in ("镜头随主要动作平稳调整景别", "跟随主要动作", "平稳调整景别"):
        if phrase in text:
            failures.append(f"MODEL_PROMPT_GENERIC_CAMERA_LANGUAGE:{source_id}:{phrase}")
    return {
        "policy": MODEL_PROMPT_POLICY_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "source_id": source_id,
        "character_count": len(text),
        "max_character_count": MAX_MODEL_PROMPT_CHARS,
        "forbidden_tokens": list(FORBIDDEN_MODEL_PROMPT_TOKENS),
        "failures": failures,
    }


def validate_transition_prompt_binding(text: str, unit: dict[str, Any]) -> dict[str, Any]:
    source_id = str(unit.get("unit_id") or "UNKNOWN")
    expected_clause = "【转场硬合同】" + compile_transition_prompt(unit)
    failures: list[str] = []
    if text.count(expected_clause) != 1:
        failures.append(f"TRANSITION_PROMPT_EXACT_BINDING_MISMATCH:{source_id}")
    incoming = unit.get("incoming_transition_contract")
    outgoing = unit.get("outgoing_transition_contract")
    expected_ids = [
        incoming["boundary_id"] if incoming else "SEQUENCE_START",
        outgoing["boundary_id"] if outgoing else "SEQUENCE_END",
    ]
    for boundary in expected_ids:
        if text.count(boundary) != 1:
            failures.append(f"TRANSITION_PROMPT_BOUNDARY_ID_COUNT:{source_id}:{boundary}:{text.count(boundary)}")
    return {
        "schema": "qingshan.transition_prompt_binding.v1",
        "status": "PASS" if not failures else "FAIL",
        "unit_id": source_id,
        "incoming_boundary_id": expected_ids[0],
        "outgoing_boundary_id": expected_ids[1],
        "incoming_transition_present": incoming is not None,
        "outgoing_transition_present": outgoing is not None,
        "failures": failures,
    }


def prompt_text(unit: dict[str, Any], memory_rules: list[dict[str, Any]] | None = None) -> str:
    model = str(unit.get("model") or "seedance-2.0-pro")
    if model != "seedance-2.0-pro":
        raise ValueError(
            f"Seedance prompt compiler cannot serialize {model}; use tools.video_prompt_compiler"
        )
    unit["internal_transition_contracts"] = validate_internal_transition_sequence(unit)
    specs = unit["ordered_prompt_specs"]
    first = specs[0]
    weather = normalized_weather((first.get("scene_state") or {}).get("weather"))
    cast = _unique([
        str(row.get("character") or "")
        for spec in specs
        for row in spec.get("cast") or []
    ])
    props = _unique([
        str(row.get("prop") or "")
        for spec in specs
        for row in spec.get("props") or []
    ])
    palette = str((first.get("scene_state") or {}).get("palette") or "").strip()
    beat_lines = [compact_beat_line(spec, timeline) for spec, timeline in zip(specs, beat_timeline(unit))]
    camera_line = compile_camera_prompt(unit.get("camera_plan"), source_id=str(unit["unit_id"]))
    visual_sound_line = compile_visual_sound_clause(specs)
    wardrobe_line = wardrobe_prompt_block(unit)
    dialogue_windows = compile_dialogue_windows(unit)
    dialogue_safety_line = (
        "本单元无对白；转场预留内只保留现场声与动作结果。"
        if not dialogue_windows
        else "；".join(
            f"节拍{row['spec_index'] + 1}对白仅在{row['start_seconds']:g}–{row['end_seconds']:g}秒，"
            f"随后闭口并至少保留{row['safety_pad_seconds']:g}秒安全尾柄"
            for row in dialogue_windows
        ) + "。任何对白不得进入片尾转场预留，不得以裁字、抢速或硬切完成时长。"
    )
    scene_parts = [weather]
    if palette:
        scene_parts.append(f"综合色调={palette}")
    if cast:
        scene_parts.append("人物=" + "、".join(cast))
    if props:
        scene_parts.append("关键道具=" + "、".join(props))
    resolution = str(unit.get("resolution") or "720p")
    aspect_ratio = str(unit.get("aspect_ratio") or "9:16")
    lines = [
        f"【视频任务】{unit['duration_seconds']}秒，竖屏{aspect_ratio}，{resolution}，{model_display_name(model)}；写实古装悬疑电影质感。",
        f"【天气硬合同】weather={weather}",
        "【场景与人物】" + "；".join(scene_parts) + "。使用随任务传入的参考图保持人物面孔、服装、场景和道具一致。",
        "【服装身份硬合同】" + wardrobe_line,
        "【镜头硬合同】" + camera_line,
        "【转场硬合同】" + compile_transition_prompt(unit),
        "【节拍内连续性硬合同】" + compile_internal_transition_prompt(unit),
        "【视觉与现场声硬合同】" + visual_sound_line,
        "【对白安全切点】" + dialogue_safety_line,
        "【表演连续性】严格按节拍内连续性硬合同执行连续动作、揭示或明确切镜；不得把不同人物变成同一个人，不得用变脸、换衣或同位置替换冒充角色交接；摄影机只执行镜头硬合同声明的运动。",
        "【节拍】",
        *beat_lines,
        "【同任务原生声音】精确保留上述对白及本任务生成的环境声、拟音和动作声；对白只说一次、不改词、不换说话人，无对白人物闭口；禁止 TTS、旧音轨、跨任务音轨和默认 BGM。",
        "【关键限制】无字幕、水印、可读文字、人物身份漂移、静态帧、数字推拉、循环动作、冻结或变速补时；不得漏拍或重排节拍。",
    ]
    text = "\n".join(lines) + "\n"
    validation = validate_model_prompt(text, source_id=str(unit["unit_id"]))
    if validation["status"] != "PASS":
        raise ValueError(";".join(validation["failures"]))
    transition_binding = validate_transition_prompt_binding(text, unit)
    if transition_binding["status"] != "PASS":
        raise ValueError(";".join(transition_binding["failures"]))
    return text


def write_preflight_artifacts(
    manifest: dict[str, Any], grouping_path: Path, prompt_dir: Path,
    scene_authority_path: Path, complete_path: Path, density_path: Path,
    dialogue_path: Path, failure_memory_path: Path, first_pass_policy_path: Path, config_path: Path,
    beat_sheet_path: Path, script_readiness_report_path: Path, script_density_source_path: Path,
    script_density_report_path: Path,
    directing_script_path: Path, generation_contract_path: Path, supervisor_report_path: Path,
) -> None:
    prompt_dir.mkdir(parents=True, exist_ok=True)
    scene_rows: list[dict[str, str]] = []
    seen_scenes: set[str] = set()
    prompt_rows: list[dict[str, Any]] = []
    density_rows: list[dict[str, Any]] = []
    dialogue_rows: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    dialogue_index = 0
    memory = load(failure_memory_path)
    memory_rules = memory.get("rules") or []
    known_failure_ids = [str(row["id"]) for row in memory_rules if row.get("id")]
    for unit in manifest["units"]:
        unit["action_timeline"] = action_timeline(unit)
        density = validate_action_timeline(unit["action_timeline"], unit["duration_seconds"], source_id=unit["unit_id"])
        density_rows.append(density)
        if density["status"] != "PASS":
            raise ValueError(";".join(density["failures"]))
        weather = normalized_weather((unit["ordered_prompt_specs"][0].get("scene_state") or {}).get("weather"))
        if unit["scene_id"] not in seen_scenes:
            seen_scenes.add(unit["scene_id"])
            scene_rows.append({"scene_id": unit["scene_id"], "weather": weather})
        prompt_path = prompt_dir / f"{unit['unit_id']}.txt"
        prompt_path.write_text(prompt_text(unit, memory_rules), encoding="utf-8")
        prompt_sha = digest(prompt_path)
        model_prompt_contract = validate_model_prompt(prompt_path.read_text(encoding="utf-8"), source_id=unit["unit_id"])
        transition_prompt_binding = validate_transition_prompt_binding(
            prompt_path.read_text(encoding="utf-8"), unit
        )
        if transition_prompt_binding["status"] != "PASS":
            raise ValueError(";".join(transition_prompt_binding["failures"]))
        task_dialogue: list[dict[str, str]] = []
        for spec in unit["ordered_prompt_specs"]:
            raw = str(spec.get("dialogue") or "").strip()
            if not raw:
                continue
            dialogue_index += 1
            dia_id = f"{manifest['episode']}-DIA-{dialogue_index:03d}"
            speaker, separator, spoken_text = raw.partition("：")
            if not separator or not speaker.strip() or not spoken_text.strip():
                raise ValueError(f"{unit['unit_id']} dialogue must use speaker：text format: {raw}")
            task_dialogue.append({"dia_id": dia_id, "speaker": speaker.strip(), "spoken_text": spoken_text.strip()})
            dialogue_rows.append({
                "dia_id": dia_id, "video_unit_id": unit["unit_id"], "speaker": speaker.strip(),
                "spoken_text": spoken_text.strip(), "status": "PASS",
                "audio_mode": "RIGHTS_CLEARED_MODEL_NATIVE_TEXT_ONLY",
                "rights_cleared_model_native": True, "external_voice_reference": False,
                "unverified_clone_prohibited": True, "path": None, "remote_asset_id": None,
                "same_video_task_native_audio_required": True,
            })
        prompt_rows.append({
            "unit_id": unit["unit_id"], "scene_id": unit["scene_id"], "weather": weather,
            "prompt_path": relative(prompt_path), "prompt_sha256": prompt_sha,
            "camera_signature": camera_signature(unit["camera_plan"]),
            "camera_plan": unit["camera_plan"],
            "model_prompt_contract": model_prompt_contract,
            "transition_prompt_binding": transition_prompt_binding,
            "machine_contract_location": "GROUPED_MANIFEST_UNIT_FIELDS_NOT_MODEL_PROMPT",
        })
        tasks.append({
            "task_key": f"{unit['unit_id']}-VIDEO-A1", "unit_id": unit["unit_id"],
            "tool_type": "video_generation", "model": unit["model"], "resolution": unit["resolution"],
            "prompt_file": relative(prompt_path), "prompt_sha256": prompt_sha,
            "dialogue": task_dialogue, "native_dialogue_required": bool(task_dialogue),
            "visual_tier": "CORE", "minimum_score_100": 80.0,
            "prompt_failure_modes_applied": known_failure_ids,
            "prompt_failure_modes_not_applicable": [],
            "model_prompt_contract": model_prompt_contract,
            "transition_prompt_binding": transition_prompt_binding,
            "machine_contract": {
                "grouped_manifest_unit_id": unit["unit_id"],
                "scene_id": unit["scene_id"],
                "weather": weather,
                "reference_images": unit["reference_images"],
                "action_timeline": unit["action_timeline"],
                "ordered_prompt_specs": unit["ordered_prompt_specs"],
                "camera_plan": unit["camera_plan"],
                "incoming_transition_contract": unit.get("incoming_transition_contract"),
                "outgoing_transition_contract": unit.get("outgoing_transition_contract"),
                "start_frame_semantic_contract": unit.get("start_frame_semantic_contract"),
                "prompt_failure_mode_ids": known_failure_ids,
            },
            "provider_post_allowed": False, "remote_task_id": None, "paid_attempt": 0,
        })
    scene_authority_path.parent.mkdir(parents=True, exist_ok=True)
    complete_path.parent.mkdir(parents=True, exist_ok=True)
    density_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    scene_authority_path.write_text(json.dumps({
        "schema": "qingshan.scene_state_authority.v1", "episode": manifest["episode"], "scene_state": scene_rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    complete_path.write_text(json.dumps({
        "schema": "qingshan.complete_video_prompt_manifest.v1", "episode": manifest["episode"],
        "status": "PASS", "unit_count": len(prompt_rows), "all_units_have_prompt": True,
        "source_plan": relative(grouping_path), "source_plan_sha256": digest(grouping_path),
        "source_scene_authority": relative(scene_authority_path),
        "source_scene_authority_sha256": digest(scene_authority_path), "rows": prompt_rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    density_path.write_text(json.dumps({
        "schema": "qingshan.video_prompt_action_density_batch.v1", "episode": manifest["episode"],
        "status": "PASS", "unit_count": len(density_rows), "results": density_rows, "failures": [],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dialogue_path.parent.mkdir(parents=True, exist_ok=True)
    dialogue_path.write_text(json.dumps({
        "schema": "qingshan.dialogue_manifest.v1", "episode": manifest["episode"],
        "status": "PASS", "line_count": len(dialogue_rows), "rows": dialogue_rows,
        "audio_policy": "RIGHTS_CLEARED_MODEL_NATIVE_TEXT_ONLY_SAME_VIDEO_TASK_NO_EXTERNAL_REFERENCE",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config_path.write_text(json.dumps({
        "schema": "qingshan.episode_parallel_batch.config.v1", "episode": manifest["episode"],
        "status": "PREFLIGHT_ONLY_NO_PROVIDER_POST", "complete_video_prompt_manifest_ref": relative(complete_path),
        "scene_contract_ref": relative(scene_authority_path), "dialogue_manifest_ref": relative(dialogue_path),
        "generation_first_pass_policy_ref": relative(first_pass_policy_path),
        "generation_first_pass_policy_sha256": digest(first_pass_policy_path),
        "generation_prompt_failure_memory_ref": relative(failure_memory_path),
        "generation_prompt_failure_memory_sha256": digest(failure_memory_path),
        "script_gate": {
            "beat_sheet": relative(beat_sheet_path),
            "report": relative(script_readiness_report_path),
        },
        "script_density_gate": {
            "script": relative(script_density_source_path),
            "review": relative(script_density_report_path),
            "episode": manifest["episode"],
        },
        "writer_agent_provenance": build_writer_agent_provenance(
            directing_script_path, generation_contract_path
        ),
        "supervisor_script_gate_report": relative(supervisor_report_path),
        "tasks": tasks,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compile_manifest(grouping: dict[str, Any], anchors: dict[str, Any], editorial: dict[str, Any]) -> dict[str, Any]:
    anchor_by_unit = {row["unit_id"]: row for row in anchors.get("units") or []}
    shot_by_id = {row["shot_id"]: row for row in editorial.get("shots") or []}
    units: list[dict[str, Any]] = []
    for unit in grouping.get("units") or []:
        unit_id = unit["unit_id"]
        anchor = anchor_by_unit.get(unit_id)
        if not anchor:
            raise ValueError(f"{unit_id} missing anchor decision")
        paths = anchor.get("reference_image_paths") or []
        if len(paths) != int(anchor.get("planned_reference_image_count", -1)):
            raise ValueError(f"{unit_id} anchor count mismatch")
        roles = (anchor.get("anchor_count_decision") or {}).get("anchor_roles") or []
        if len(roles) != len(paths):
            raise ValueError(f"{unit_id} anchor role count mismatch")
        source_transport = str(anchor.get("reference_transport_strategy") or "")
        references = []
        for value, role in zip(paths, roles):
            path = resolve(value)
            if not path.is_file():
                raise ValueError(f"{unit_id} anchor missing: {value}")
            references.append({"path": value, "sha256": digest(path), "role": role})
        shots = [shot_by_id[shot_id] for shot_id in unit["editorial_shot_ids"]]
        models = {str(row.get("model") or "") for row in shots}
        resolutions = {str(row.get("resolution") or "") for row in shots}
        aspect_ratios = {str(row.get("aspect_ratio") or "9:16") for row in shots}
        if len(models) != 1 or len(resolutions) != 1 or len(aspect_ratios) != 1:
            raise ValueError(f"{unit_id} mixes model, resolution, or aspect-ratio contracts")
        model = next(iter(models))
        resolution = next(iter(resolutions))
        aspect_ratio = next(iter(aspect_ratios))
        if model not in NATIVE_VIDEO_MODEL_RESOLUTIONS:
            raise ValueError(f"{unit_id} contains forbidden model: {model}")
        if resolution not in NATIVE_VIDEO_MODEL_RESOLUTIONS[model]:
            raise ValueError(f"{unit_id} contains non-native resolution {resolution} for {model}")
        if aspect_ratio != "9:16":
            raise ValueError(f"{unit_id} must remain vertical 9:16")
        prompt_specs = [row.get("prompt_spec") or {} for row in shots]
        for shot, prompt_spec in zip(shots, prompt_specs):
            validate_grouped_beat_contract(prompt_spec, source_id=str(shot["shot_id"]))
        camera_plan = validate_camera_plan(unit.get("camera_plan"), source_id=unit_id)
        transition_contract = unit.get("transition_contract")
        semantic_contract = validate_start_anchor_semantics(
            anchor.get("start_frame_semantic_contract"),
            unit_id=unit_id,
            first_reference=references[0],
            first_prompt_spec=prompt_specs[0],
            camera_plan=camera_plan,
            required_space_anchors=(transition_contract or {}).get("anchor_semantic_requirements", {}).get(
                "target_space_anchors", anchor.get("required_start_space_anchors") or []
            ),
            root=ROOT,
        )
        compiled_unit = {
            "unit_id": unit_id,
            "scene_id": unit["scene_id"],
            "duration_seconds": unit["duration_seconds"],
            "model": model,
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "editorial_shot_ids": unit["editorial_shot_ids"],
            "narrative_beat": unit["narrative_beat"],
            "reference_images": references,
            # The production contract deliberately exposes one route. Reference count no
            # longer creates separate I2V/Omni admission gates for the operator.
            "reference_transport_strategy": "STANDARD_MULTI_REFERENCE",
            "source_reference_transport_strategy": source_transport or None,
            "semantic_reference_coverage_gate": anchor.get("semantic_reference_coverage_gate"),
            "ordered_prompt_specs": prompt_specs,
            "wardrobe_contract": wardrobe_rows_for_cast(
                {"unit_id": unit_id, "ordered_prompt_specs": prompt_specs},
                grouping.get("wardrobe_bible") or {},
            ),
            "camera_plan": camera_plan,
            "transition_contract": transition_contract,
            "internal_transition_contracts": unit.get("internal_transition_contracts") or [],
            "start_frame_semantic_contract": semantic_contract,
            "native_audio_contract": "SAME_VIDEO_TASK_NATIVE_DIALOGUE_AMBIENCE_FOLEY_ACTION_SOUND",
            "submission_status": "NOT_AUTHORIZED_UNTIL_REGISTERED_GROUPED_PREFLIGHT_PASS",
            "paid_attempt": 0,
            "remote_task_id": None,
        }
        compiled_unit["internal_transition_contracts"] = validate_internal_transition_sequence(compiled_unit)
        wardrobe_report = validate_wardrobe_contract(compiled_unit, source_id=unit_id)
        if wardrobe_report["status"] != "PASS":
            raise ValueError(";".join(wardrobe_report["failures"]))
        compiled_unit["dialogue_cut_safety"] = compile_dialogue_windows(compiled_unit)
        pose_anchor_report = evaluate_pose_anchors(compiled_unit)
        if pose_anchor_report["status"] != "PASS":
            raise ValueError(";".join(pose_anchor_report["failures"]))
        compiled_unit["pose_transition_anchor_gate"] = pose_anchor_report
        units.append(compiled_unit)
    validate_camera_sequence(units)
    validate_transition_sequence(units, require_prompt_specs=True)
    if len(units) != int(grouping.get("video_unit_count", -1)):
        raise ValueError("compiled unit count mismatch")
    runtime = round(sum(float(row["duration_seconds"]) for row in units), 6)
    if runtime != round(float(grouping.get("runtime_seconds", -1)), 6):
        raise ValueError("compiled runtime mismatch")
    return {
        "schema": "qingshan.grouped_seedance_manifest.v3_transition_and_anchor_semantics",
        "episode": grouping.get("episode"),
        "video_unit_count": len(units),
        "runtime_seconds": runtime,
        "grouping_plan_sha256": None,
        "anchor_plan_sha256": None,
        "editorial_seedance_manifest_sha256": None,
        "units": units,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grouping-plan", type=Path, required=True)
    parser.add_argument("--anchor-plan", type=Path, required=True)
    parser.add_argument("--editorial-seedance-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prompt-dir", type=Path)
    parser.add_argument("--scene-authority", type=Path)
    parser.add_argument("--complete-prompt-manifest", type=Path)
    parser.add_argument("--action-density-report", type=Path)
    parser.add_argument("--dialogue-manifest", type=Path)
    parser.add_argument("--failure-memory", type=Path)
    parser.add_argument("--first-pass-policy", type=Path)
    parser.add_argument("--batch-config", type=Path)
    parser.add_argument("--beat-sheet", type=Path)
    parser.add_argument("--script-readiness-report", type=Path)
    parser.add_argument("--script-density-source", type=Path)
    parser.add_argument("--script-density-report", type=Path)
    parser.add_argument("--directing-script", type=Path)
    parser.add_argument("--generation-contract", type=Path)
    parser.add_argument("--supervisor-report", type=Path)
    args = parser.parse_args()
    result = compile_manifest(load(args.grouping_plan), load(args.anchor_plan), load(args.editorial_seedance_manifest))
    result["grouping_plan_sha256"] = digest(args.grouping_plan)
    result["anchor_plan_sha256"] = digest(args.anchor_plan)
    result["editorial_seedance_manifest_sha256"] = digest(args.editorial_seedance_manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    extras = (
        args.prompt_dir, args.scene_authority, args.complete_prompt_manifest, args.action_density_report,
        args.dialogue_manifest, args.failure_memory, args.first_pass_policy, args.batch_config,
        args.beat_sheet, args.script_readiness_report, args.script_density_source, args.script_density_report,
        args.directing_script, args.generation_contract, args.supervisor_report,
    )
    if any(extras) and not all(extras):
        parser.error("all grouped preflight output arguments must be supplied together")
    if all(extras):
        write_preflight_artifacts(
            result, args.grouping_plan, args.prompt_dir, args.scene_authority,
            args.complete_prompt_manifest, args.action_density_report, args.dialogue_manifest,
            args.failure_memory, args.first_pass_policy, args.batch_config,
            args.beat_sheet, args.script_readiness_report, args.script_density_source, args.script_density_report,
            args.directing_script, args.generation_contract, args.supervisor_report,
        )
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "units": len(result["units"]), "runtime_seconds": result["runtime_seconds"], "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
