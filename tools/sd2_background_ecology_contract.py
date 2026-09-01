#!/usr/bin/env python3
"""Seedance 2.0-only background ecology and weather-visibility contracts.

The writer may deliberately hold a crowd in position, but a held position is
not a frozen image: breath, weight, gaze, clothing and scene media continue.
This module turns that established directing rule into a prompt/compiler gate.
It is intentionally not imported by the MiniMax-H3 compiler.
"""

from __future__ import annotations

from typing import Any


GROUP_MARKERS = (
    "群", "队", "众", "人群", "赌客", "弩手", "密谍甲乙", "蓑衣", "百姓", "宾客",
)
RAIN_MARKERS = ("雨", "积水", "湿", "水线", "雨幕")
DRY_INTERIOR_MARKERS = (
    "屋里干燥", "厅里干燥", "室内干燥", "屋内干燥", "灯焰不动", "隔着窗纸",
    "雨声只从", "雨声隔着", "闷",
)
THRESHOLD_MARKERS = (
    "门被", "门开", "推开", "踹开", "撞开", "窗纸破", "窗棂", "翻进", "灌进", "斜进",
    "门缝", "窗缝",
)
COMBAT_KINDS = {"COMBAT", "FIGHT", "ACTION_COMBAT"}


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in result:
            result.append(value)
    return result


def _cast(spec: dict[str, Any]) -> list[str]:
    return _unique([
        str(row.get("character") or "") for row in spec.get("cast") or []
    ])


def _primary(spec: dict[str, Any]) -> str:
    role = spec.get("role_semantic_disambiguation") or {}
    primary = str(role.get("primary_actor") or "").strip()
    if primary:
        return primary
    cast = _cast(spec)
    return cast[0] if cast else ""


def _is_group(name: str) -> bool:
    return any(marker in name for marker in GROUP_MARKERS)


def _visual_motion(specs: list[dict[str, Any]]) -> list[str]:
    return _unique([
        str(motion)
        for spec in specs
        for motion in ((spec.get("visual_design") or {}).get("environmental_motion") or [])
    ])


def build_weather_visibility_contract(unit: dict[str, Any]) -> dict[str, Any]:
    specs = unit.get("ordered_prompt_specs") or []
    weather = "；".join(_unique([
        str((spec.get("scene_state") or {}).get("weather") or "") for spec in specs
    ]))
    actions = "；".join(
        str((spec.get("action") or {}).get("primary_action") or "") for spec in specs
    )
    rain_declared = any(marker in weather for marker in RAIN_MARKERS)
    dry_interior = any(marker in weather for marker in DRY_INTERIOR_MARKERS)
    threshold_event = any(marker in actions for marker in THRESHOLD_MARKERS)
    if not rain_declared:
        mode = "NO_UNDECLARED_WEATHER"
        prompt = "只呈现剧本已声明天气；禁止自动添加雨、雪、雾、雷电或湿地反光。"
    elif dry_interior and threshold_event:
        mode = "THRESHOLD_INTRUSION_ONLY"
        prompt = (
            "室内保持干燥；雨只在本镜明确开启或破开的门窗阈值处短暂可见并有受力方向，"
            "不得把整间屋变成雨场、不得让未接触阈值的人物凭空淋湿。"
        )
    elif dry_interior:
        mode = "OFFSCREEN_AUDIBLE_ONLY"
        prompt = (
            "室内保持干燥，画内禁止雨丝、雨帘、积水和新增湿衣；雨只作为门窗外的画外现场声。"
        )
    else:
        mode = "VISIBLE_EXTERIOR"
        prompt = (
            "雨只按剧本既定方向与强度出现在室外；雨滴、衣料、水面与脚步受力连续，"
            "不得把雨当成无来源的默认气氛模板。"
        )
    failures: list[str] = []
    if rain_declared and not weather:
        failures.append("WEATHER_SOURCE_EMPTY")
    provenance_rows = []
    for index, spec in enumerate(specs, start=1):
        provenance = (spec.get("scene_state") or {}).get("weather_provenance")
        if not isinstance(provenance, dict):
            failures.append(f"BEAT_{index}_WEATHER_PROVENANCE_MISSING")
            continue
        required = ("source_type", "source_ref", "visibility_mode")
        if any(not str(provenance.get(key) or "").strip() for key in required):
            failures.append(f"BEAT_{index}_WEATHER_PROVENANCE_INCOMPLETE")
            continue
        normalized = {key: str(provenance[key]).strip() for key in required}
        if normalized not in provenance_rows:
            provenance_rows.append(normalized)
    return {
        "schema": "qingshan.sd2_weather_visibility.v1",
        "status": "PASS" if not failures else "FAIL",
        "declared_weather": weather,
        "mode": mode,
        "prompt": prompt,
        "source_policy": "WRITER_SCENE_STATE_PRESERVED_VISIBILITY_ONLY",
        "writer_weather_provenance": provenance_rows,
        "failures": failures,
    }


def build_background_ecology_contract(unit: dict[str, Any]) -> dict[str, Any]:
    specs = unit.get("ordered_prompt_specs") or []
    rows: list[dict[str, Any]] = []
    group_entities: list[str] = []
    all_cast: list[str] = []
    combat = False
    failures: list[str] = []
    for index, spec in enumerate(specs, start=1):
        cast = _cast(spec)
        all_cast.extend(cast)
        primary = _primary(spec)
        action_kind = str((spec.get("action") or {}).get("action_kind") or "").upper()
        combat = combat or action_kind in COMBAT_KINDS
        entity_rows: list[dict[str, str]] = []
        for entity in cast:
            if _is_group(entity):
                group_entities.append(entity)
                motion = (
                    "保持剧情规定的站位或队形，但近层先做呼吸、握持或承重变化，中层随后错峰转眼或移重心，"
                    "远层最后出现衣摆、斗笠、脚步或器械的低幅惯性；三层不同相位、方向和幅度，不整齐摆动、不冻结"
                )
                role = "PRIMARY_GROUP" if entity == primary else "SECONDARY_GROUP"
            elif entity == primary:
                motion = "只执行本节拍主动作物理链；动作结束后保留呼吸、眼神、衣料或受力余振，不循环复位"
                role = "PRIMARY"
            else:
                motion = (
                    "闭口保持身份与站位；先保留自然呼吸和承重，再只在主事件落点后做一次眼神、下颌、肩颈或衣料反应并保持"
                )
                role = "SECONDARY"
            entity_rows.append({"entity": entity, "role": role, "motion": motion})
        ambient = spec.get("ambient_life") or (spec.get("scene_state") or {}).get("ambient_life")
        if not isinstance(ambient, dict):
            failures.append(f"BEAT_{index}_WRITER_AMBIENT_LIFE_MISSING")
            ambient = {}
        else:
            for field in ("grade", "motion_trend", "first_frame_state", "reaction_progression"):
                if not str(ambient.get(field) or "").strip():
                    failures.append(f"BEAT_{index}_WRITER_AMBIENT_LIFE_{field.upper()}_MISSING")
        rows.append({
            "beat": index,
            "primary_actor": primary,
            "entities": entity_rows,
            "combat": action_kind in COMBAT_KINDS,
            "writer_ambient_life": {
                field: str(ambient.get(field) or "").strip()
                for field in ("grade", "motion_trend", "first_frame_state", "reaction_progression")
            },
        })
    motions = _visual_motion(specs)
    grade = "A" if group_entities else ("B" if len(_unique(all_cast)) > 1 or motions else "C")
    for row in rows:
        cast = _cast(specs[row["beat"] - 1])
        covered = {entity["entity"] for entity in row["entities"]}
        missing = sorted(set(cast) - covered)
        if missing:
            failures.append(f"BEAT_{row['beat']}_VISIBLE_ENTITY_MOTION_MISSING:{','.join(missing)}")
        for entity in row["entities"]:
            if _is_group(entity["entity"]) and not all(
                token in entity["motion"] for token in ("近层", "中层", "远层", "错峰", "不冻结")
            ):
                failures.append(f"BEAT_{row['beat']}_GROUP_PHASE_DIVERSITY_MISSING:{entity['entity']}")
    if grade in {"A", "B"} and not motions:
        failures.append("ENVIRONMENTAL_MOTION_MISSING")
    if combat:
        has_secondary_or_group = any(
            entity["role"] != "PRIMARY" for row in rows for entity in row["entities"]
        )
        has_non_character_patient_or_prop = any(
            (spec.get("props") or [])
            or str((spec.get("role_semantic_disambiguation") or {}).get("action_patient") or "").strip()
            for spec in specs
        )
        if not has_secondary_or_group and not has_non_character_patient_or_prop:
            failures.append("COMBAT_REACTION_LAYER_MISSING")
        if not motions:
            failures.append("COMBAT_ENVIRONMENT_FEEDBACK_MISSING")
    return {
        "schema": "qingshan.sd2_background_ecology.v1",
        "status": "PASS" if not failures else "FAIL",
        "grade": grade,
        "visible_entities": _unique(all_cast),
        "group_entities": _unique(group_entities),
        "beat_motion_rows": rows,
        "environmental_motion": motions,
        "continuity": "所有背景微动延续至桥接尾柄，不循环、不复位、不用静态图或数字推拉补时",
        "failures": failures,
    }


def compile_background_ecology_prompt_block(contract: dict[str, Any]) -> str:
    beat_rows: list[str] = []
    for row in contract.get("beat_motion_rows") or []:
        entities = "；".join(
            f"{entity['entity']}={entity['motion']}" for entity in row.get("entities") or []
        )
        if entities:
            ambient = row.get("writer_ambient_life") or {}
            writer_life = (
                f"；写手环境生命={ambient.get('grade')}|趋势:{ambient.get('motion_trend')}|"
                f"首帧:{ambient.get('first_frame_state')}|反应链:{ambient.get('reaction_progression')}"
            )
            beat_rows.append(f"拍{row['beat']}[{entities}{writer_life}]")
    environment = " / ".join(contract.get("environmental_motion") or [])
    return (
        f"环境生命级别={contract['grade']}；" + "；".join(beat_rows) +
        (f"；场景介质={environment}" if environment else "") +
        f"；{contract['continuity']}。"
    )


def compile_weather_visibility_prompt_block(contract: dict[str, Any]) -> str:
    provenance = " / ".join(
        f"{row['source_type']}@{row['source_ref']}→{row['visibility_mode']}"
        for row in contract.get("writer_weather_provenance") or []
    )
    return (
        f"模式={contract['mode']}；写手天气依据={provenance or 'MISSING'}；"
        f"{contract['prompt']}"
    )


def validate_sd2_ecology_and_weather(unit: dict[str, Any]) -> dict[str, Any]:
    ecology = unit.get("background_ecology_contract") or build_background_ecology_contract(unit)
    weather = unit.get("weather_visibility_contract") or build_weather_visibility_contract(unit)
    failures = list(ecology.get("failures") or []) + list(weather.get("failures") or [])
    return {
        "schema": "qingshan.sd2_ecology_weather_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "unit_id": unit.get("unit_id"),
        "background_ecology": ecology,
        "weather_visibility": weather,
        "failures": failures,
    }
