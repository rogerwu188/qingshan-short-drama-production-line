#!/usr/bin/env python3
"""Compile grouped short-drama units into MiniMax-H3 native prompt grammar.

This module is intentionally separate from the Seedance compiler.  It consumes
the same model-neutral directing contract, but serializes it using MiniMax-H3's
native audiovisual structure and fails closed when non-dialogue text can be
mistaken for speech.
"""

from __future__ import annotations

import re
from typing import Any

try:
    from tools.dialogue_cut_safety import compile_dialogue_windows
    from tools.wardrobe_identity_contract import validate_wardrobe_contract, wardrobe_prompt_block
except ModuleNotFoundError:
    from dialogue_cut_safety import compile_dialogue_windows
    from wardrobe_identity_contract import validate_wardrobe_contract, wardrobe_prompt_block


H3_MODEL_PROMPT_POLICY_VERSION = "qingshan.minimax_h3_prompt.v1_native_audiovisual"
MAX_H3_PROMPT_CHARS = 7000
H3_CORE_FIELDS = (
    "subject_definitions:",
    "summary:",
    "retention_analysis:",
    "detailed_description:",
    "overall_soundscape:",
    "non_diegetic_music:",
)
SD2_ONLY_MARKERS = (
    "【视频任务】",
    "【镜头硬合同】",
    "【节拍】",
    "【同任务原生声音】",
    "物理动作链：",
    "表演硬锁：",
)
_DIALOGUE_TAG = re.compile(r"<d>\[Chinese\]\s*(.*?)</d>", re.DOTALL)


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _dialogue_parts(raw: str) -> tuple[str, str]:
    speaker, separator, words = str(raw or "").partition("：")
    if not separator or not speaker.strip() or not words.strip():
        raise ValueError(f"H3 dialogue must use speaker：text format: {raw}")
    return speaker.strip(), words.strip()


def _dialogues(unit: dict[str, Any]) -> list[tuple[str, str]]:
    return [
        _dialogue_parts(str(spec.get("dialogue") or ""))
        for spec in unit.get("ordered_prompt_specs") or []
        if str(spec.get("dialogue") or "").strip()
    ]


def _speaker_ids(unit: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for speaker, _ in _dialogues(unit):
        if speaker not in result:
            result[speaker] = f"S{len(result) + 1}"
    return result


def _timeline(unit: dict[str, Any]) -> list[tuple[float, float]]:
    specs = unit.get("ordered_prompt_specs") or []
    raw_durations = []
    for spec in specs:
        action = spec.get("action") or {}
        duration = float(action.get("t1_seconds", 0)) - float(action.get("t0_seconds", 0))
        raw_durations.append(max(duration, 0.001))
    target = float(unit.get("duration_seconds") or sum(raw_durations))
    scale = target / sum(raw_durations) if raw_durations else 1.0
    cursor = 0.0
    result: list[tuple[float, float]] = []
    for index, duration in enumerate(raw_durations):
        end = target if index == len(raw_durations) - 1 else cursor + duration * scale
        result.append((round(cursor, 3), round(end, 3)))
        cursor = end
    return result


def _clock(seconds: float) -> str:
    minutes = int(seconds // 60)
    remainder = seconds - minutes * 60
    return f"{minutes:02d}:{remainder:06.3f}"


def _trim(value: object) -> str:
    return str(value or "").strip().rstrip("。！？；,.!?; ")


def _camera_motion(plan: dict[str, Any] | None) -> str:
    plan = plan or {}
    family = str(plan.get("motion_family") or "STATIC").upper()
    direction = str(plan.get("motion_direction") or "").upper()
    mapping = {
        ("DOLLY", "PUSH_IN"): "摄影机以小幅、慢速推近主体",
        ("DOLLY", "PULL_OUT"): "摄影机以小幅、慢速后拉",
        ("PAN", "LEFT"): "摄影机以小幅、慢速向左摇摄",
        ("PAN", "RIGHT"): "摄影机以小幅、慢速向右摇摄",
        ("TRUCK", "LEFT"): "摄影机以小幅、慢速向左横移",
        ("TRUCK", "RIGHT"): "摄影机以小幅、慢速向右横移",
        ("CRANE", "RISE"): "摄影机以小幅、慢速升高",
        ("CRANE", "FALL"): "摄影机以小幅、慢速下降",
        ("TILT", "UP"): "摄影机以小幅、慢速向上俯仰",
        ("TILT", "DOWN"): "摄影机以小幅、慢速向下俯仰",
        ("ARC", "LEFT"): "摄影机以小幅、慢速沿主体左侧弧线移动",
        ("ARC", "RIGHT"): "摄影机以小幅、慢速沿主体右侧弧线移动",
        ("TRACKING", "FORWARD"): "摄影机以小幅、正常速度跟随主体前行",
    }
    if family in {"STATIC", "LOCKED", "NONE"}:
        return "摄影机保持固定机位"
    return mapping.get((family, direction), "摄影机按既定单一方向平稳移动")


def _shot_scale(plan: dict[str, Any] | None) -> str:
    value = str((plan or {}).get("shot_scale") or "MEDIUM").upper()
    return {
        "EXTREME_WIDE": "大全景",
        "WIDE": "全景",
        "MEDIUM_WIDE": "中全景",
        "MEDIUM": "中景",
        "MEDIUM_CLOSE_UP": "中近景",
        "CLOSE_UP": "近景",
        "EXTREME_CLOSE_UP": "特写",
    }.get(value, "中景")


def _reference_role(role: str, index: int) -> str:
    role = role.upper()
    if index == 1 or "START" in role:
        return "目标视频在0.00秒完整采用的首帧，锁定开场构图、人物、服装、道具、场景和光向"
    if "RESULT" in role or "TERMINAL" in role or "END" in role:
        return "结果状态参考，锁定本段结束前必须到达的人物、道具和构图状态"
    if "IDENTITY" in role or "CHARACTER" in role:
        return "人物身份参考，只提供该人物的面孔、年龄、发型、体型和服装"
    if "PROP" in role:
        return "道具参考，只提供具名道具的形制、材质和当前状态"
    return "过程关键帧参考，锁定对应节拍的构图、空间关系和动作状态"


def _transition_notes(unit: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    incoming = unit.get("incoming_transition_contract")
    if incoming:
        target = incoming.get("target_initial_state") or {}
        handle = float(incoming.get("incoming_handle_seconds") or 0.8)
        notes.append(
            f"开场前{handle:g}秒承接上一视频单元的现场声与因果结果，从{_trim(target.get('blocking'))}继续，"
            "不复位、不重演，也不新增无关动作；呼吸、衣料惯性、环境风声和既定视线从上一段残余运动自然接续"
        )
    outgoing = unit.get("outgoing_transition_contract")
    if outgoing:
        source = outgoing.get("source_terminal_state") or {}
        handle = float(outgoing.get("outgoing_handle_seconds") or 1.0)
        notes.append(
            f"结尾最后{handle:g}秒完成并保持{_trim(source.get('blocking'))}，"
            f"让{_trim(outgoing.get('sound_bridge'))}，为下一视频单元留下可剪辑声画接点；"
            "动作结果落稳后仍保持自然呼吸、衣料惯性和环境微动，禁止冻结、循环或另起新动作"
        )
    return notes


def _internal_transition(unit: dict[str, Any], index: int) -> str:
    rows = unit.get("internal_transition_contracts") or []
    row = rows[index - 1] if 0 <= index - 1 < len(rows) else {}
    mode = str(row.get("transition_mode") or "MOTIVATED_CUT").upper()
    if "CUT" in mode:
        return "镜头在前一动作结果落稳后明确切换，切换以固定空间物和真实现场声重新建立方向"
    return "摄影机在前一动作结果落稳后连续重新构图，不切断动作与现场声"


def _performance_sentence(spec: dict[str, Any]) -> str:
    cast = _unique([str(row.get("character") or "") for row in spec.get("cast") or []])
    if not cast:
        return ""
    performance = spec.get("performance") or {}
    expression = _trim(performance.get("expression_arc"))
    micro = _trim(performance.get("continuous_micro_action"))
    body = _trim(performance.get("body_sync"))
    clauses = [value for value in (expression, micro, body) if value]
    return f"{'、'.join(cast)}的表演保持克制；" + "；".join(clauses[:3]) if clauses else ""


def _visual_action(spec: dict[str, Any]) -> str:
    action = spec.get("action") or {}
    start = _trim(action.get("start_state"))
    primary = _trim(action.get("primary_action"))
    result = _trim(action.get("completion_state"))
    raw_dialogue = str(spec.get("dialogue") or "").strip()
    if raw_dialogue:
        _, spoken = _dialogue_parts(raw_dialogue)
        if primary == _trim(spoken):
            # Some source manifests repeat the spoken words in primary_action.
            # H3 must see literal dialogue only inside <d>; keep the physical
            # start/result chain and omit the duplicate speakable text here.
            primary = ""
    if start and result and start != result:
        if primary:
            return f"从{start}开始，{primary}，动作连续到达{result}并保持"
        return f"从{start}开始，动作连续到达{result}并保持"
    return f"{primary or result}；{result}保持为本镜头结果" if result else primary


def _soundscape(unit: dict[str, Any]) -> str:
    specs = unit.get("ordered_prompt_specs") or []
    weather = _trim(((specs[0].get("scene_state") or {}).get("weather")) if specs else "")
    sound_rows = [spec.get("sound_design") or {} for spec in specs]
    ambience = _unique([_trim(row.get("ambience")) for row in sound_rows])
    foley = _unique([_trim(row.get("foley")) for row in sound_rows])
    action = _unique([_trim(row.get("action_sound")) for row in sound_rows])
    parts = []
    if weather:
        parts.append(f"环境持续呈现{weather}对应的自然底声")
    if ambience:
        parts.append(ambience[0])
    if foley:
        parts.append(foley[0])
    if action:
        parts.append(action[0])
    return "。".join(parts[:4]) + "。"


def compile_h3_prompt(unit: dict[str, Any]) -> str:
    """Serialize a model-neutral grouped unit as H3 full-reference prompt text."""
    if str(unit.get("model") or "MiniMax-H3").lower() not in {"minimax-h3", "h3"}:
        raise ValueError("compile_h3_prompt only accepts MiniMax-H3 units")
    specs = unit.get("ordered_prompt_specs") or []
    if not specs:
        raise ValueError("H3 unit has no ordered_prompt_specs")
    references = unit.get("reference_images") or []
    if not references or len(references) > 9:
        raise ValueError("H3 full-reference prompt requires 1-9 reference images")
    speakers = _speaker_ids(unit)
    timeline = _timeline(unit)
    dialogue_windows = {
        int(row["spec_index"]): row for row in compile_dialogue_windows(unit)
    }
    wardrobe = wardrobe_prompt_block(unit, concise=True)
    first_scene = specs[0].get("scene_state") or {}
    cast = _unique([
        str(row.get("character") or "")
        for spec in specs for row in spec.get("cast") or []
    ])
    props = _unique([
        str(row.get("prop") or "")
        for spec in specs for row in spec.get("props") or []
    ])

    definitions = [
        f"@图片{index}：{_reference_role(str(ref.get('role') or ''), index)}。"
        for index, ref in enumerate(references, 1)
    ]
    summary_parts = [
        f"[reference generation + keyframe completion] 生成{float(unit['duration_seconds']):g}秒9:16真人实拍古装悬疑短剧",
        f"人物为{'、'.join(cast)}" if cast else "本段以场景和道具为主体",
        f"关键道具为{'、'.join(props)}" if props else "不新增无关道具",
        "@图片1锁定首帧，其余参考图只锁定各自对应的人物、道具或结果状态",
    ]
    retention = [
        f"@图片{index}：fully_preserved - {_reference_role(str(ref.get('role') or ''), index)}。"
        for index, ref in enumerate(references, 1)
    ]

    description: list[str] = [
        "目标视频为真人实拍、写实古装悬疑电影质感，保持同一人物身份、服装、场景地图、道具、天气和光向。",
        f"服装身份锁：{wardrobe}",
        f"[Shot 1] {_shot_scale(unit.get('camera_plan'))}从@图片1的构图和状态开始。"
        f"场景时间与空间状态为{_trim(first_scene.get('time'))}；{_trim(first_scene.get('weather'))}。"
        f"{_camera_motion(unit.get('camera_plan'))}。",
    ]
    for index, (spec, (start, end)) in enumerate(zip(specs, timeline), start=1):
        prefix = "" if index == 1 else (
            f"[Shot {index}] At {_clock(start)}, {_internal_transition(unit, index)}。"
        )
        action = _visual_action(spec)
        performance = _performance_sentence(spec)
        sentence = f"{prefix}{action}。"
        if performance:
            sentence += performance + "。"
        raw_dialogue = str(spec.get("dialogue") or "").strip()
        if raw_dialogue:
            speaker, words = _dialogue_parts(raw_dialogue)
            delivery = spec.get("dialogue_delivery") or {}
            pace = _trim(delivery.get("pace")) or "自然克制"
            window = dialogue_windows[index - 1]
            sentence += (
                f"{speaker}（{speakers[speaker]}）只在{window['start_seconds']:g}至"
                f"{window['end_seconds']:g}秒之间，以{pace}的现场音量说"
                f"：<d>[Chinese] {words}</d>。说完立即闭口，台词不跨越本节拍。"
            )
        description.append(sentence)
    if speakers:
        description.append(
            "唯一的人声事件是上述<d>标签内的逐字台词；人物只在自己的台词时段张口，其他人物和其他时段全部闭口，"
            "没有旁白、画外解释、歌唱、补充对白或对动作文字的朗读。"
        )
    else:
        description.append(
            "本段没有人声事件；所有人物全程闭口，仅保留环境声、呼吸、衣料和真实动作接触声，没有对白、旁白或歌唱。"
        )
    description.extend(note + "。" for note in _transition_notes(unit))
    description.append(
        "画面不出现字幕、水印、LOGO或可读文字；不变脸、不换人、不换衣、不改变地图方向，不用循环、冻结或变速补足时长。"
    )

    text = "\n".join([
        "subject_definitions:",
        *definitions,
        "",
        "summary:",
        "；".join(summary_parts) + "。",
        "",
        "retention_analysis:",
        *retention,
        "",
        "detailed_description:",
        *description,
        "",
        "overall_soundscape:",
        _soundscape(unit),
        "",
        "non_diegetic_music:",
        "N/A",
        "",
    ])
    report = validate_h3_prompt(text, source_id=str(unit.get("unit_id") or "UNKNOWN"), unit=unit)
    if report["status"] != "PASS":
        raise ValueError(";".join(report["failures"]))
    return text


def validate_h3_transition_prompt_binding(text: str, unit: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    expected = _transition_notes(unit)
    for index, note in enumerate(expected, start=1):
        if text.count(note) != 1:
            failures.append(f"H3_TRANSITION_NOTE_COUNT:{index}:{text.count(note)}")
    return {
        "schema": "qingshan.minimax_h3_transition_prompt_binding.v1",
        "status": "PASS" if not failures else "FAIL",
        "unit_id": str(unit.get("unit_id") or "UNKNOWN"),
        "incoming_transition_present": unit.get("incoming_transition_contract") is not None,
        "outgoing_transition_present": unit.get("outgoing_transition_contract") is not None,
        "failures": failures,
    }


def validate_h3_prompt(
    text: str,
    *,
    source_id: str,
    unit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    if len(text) > MAX_H3_PROMPT_CHARS:
        failures.append(f"H3_PROMPT_TOO_LONG:{source_id}:{len(text)}>{MAX_H3_PROMPT_CHARS}")
    positions = []
    for field in H3_CORE_FIELDS:
        count = text.count(field)
        if count != 1:
            failures.append(f"H3_CORE_FIELD_COUNT:{source_id}:{field}:{count}")
        positions.append(text.find(field))
    if any(value < 0 for value in positions) or positions != sorted(positions):
        failures.append(f"H3_CORE_FIELD_ORDER:{source_id}")
    for marker in SD2_ONLY_MARKERS:
        if marker in text:
            failures.append(f"H3_CONTAINS_SD2_PROMPT_MARKER:{source_id}:{marker}")
    if "non_diegetic_music:\nN/A" not in text:
        failures.append(f"H3_NON_DIEGETIC_MUSIC_NOT_EXPLICIT_NA:{source_id}")

    tagged_dialogue = _DIALOGUE_TAG.findall(text)
    outside_dialogue = _DIALOGUE_TAG.sub("", text)
    if any(mark in outside_dialogue for mark in ("“", "”")):
        failures.append(f"H3_NON_DIALOGUE_TEXT_QUOTED:{source_id}")
    if unit is not None:
        wardrobe = validate_wardrobe_contract(unit, source_id=source_id)
        failures.extend(wardrobe["failures"])
        if wardrobe["status"] == "PASS" and "服装身份锁：" not in text:
            failures.append(f"H3_WARDROBE_IDENTITY_BLOCK_MISSING:{source_id}")
        expected = [words for _, words in _dialogues(unit)]
        if tagged_dialogue != expected:
            failures.append(f"H3_DIALOGUE_TAG_CONTENT_MISMATCH:{source_id}")
        for speaker, words in _dialogues(unit):
            if outside_dialogue.count(f"{speaker}："):
                failures.append(f"H3_SPEAKER_COLON_OUTSIDE_DIALOGUE:{source_id}:{speaker}")
            if text.count(words) != 1:
                failures.append(f"H3_DIALOGUE_LITERAL_COUNT:{source_id}:{speaker}:{text.count(words)}")
        if expected:
            if "唯一的人声事件是上述<d>标签内的逐字台词" not in text:
                failures.append(f"H3_EXCLUSIVE_DIALOGUE_RULE_MISSING:{source_id}")
        else:
            if tagged_dialogue:
                failures.append(f"H3_UNAUTHORED_DIALOGUE_PRESENT:{source_id}")
            if "本段没有人声事件；所有人物全程闭口" not in text:
                failures.append(f"H3_SILENT_UNIT_RULE_MISSING:{source_id}")
        transition = validate_h3_transition_prompt_binding(text, unit)
        failures.extend(transition["failures"])
    return {
        "policy": H3_MODEL_PROMPT_POLICY_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "source_id": source_id,
        "character_count": len(text),
        "max_character_count": MAX_H3_PROMPT_CHARS,
        "dialogue_tag_count": len(tagged_dialogue),
        "failures": failures,
    }
