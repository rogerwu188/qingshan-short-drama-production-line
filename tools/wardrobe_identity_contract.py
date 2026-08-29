#!/usr/bin/env python3
"""Role-aware wardrobe identity contracts shared by still and video compilers.

Clothing is part of character identity, not generic production design.  This
module deliberately fails closed when a visible named human is missing an
itemized wardrobe or when two peer characters collapse to the same visual
signature.
"""

from __future__ import annotations

from typing import Any


SCHEMA = "qingshan.wardrobe_identity_contract.v1_role_and_peer_distinction"
H3_ADULT_FEMALE_VISUAL_POLICY = "qingshan.h3_adult_female_visual.v2_mature_curvy_role_bound"
REQUIRED_FIELDS = (
    "character",
    "social_tier",
    "role_basis",
    "silhouette",
    "outer_layer",
    "inner_layer",
    "primary_color",
    "secondary_color",
    "material",
    "pattern",
    "belt_or_fastening",
    "footwear",
    "accessory",
    "condition",
    "continuity_key",
)
DISTINCTION_FIELDS = (
    "silhouette",
    "primary_color",
    "secondary_color",
    "material",
    "pattern",
    "belt_or_fastening",
    "accessory",
)
ANIMAL_MARKERS = {"ANIMAL", "CAT", "DOG", "HORSE", "BIRD"}
VAGUE_ONLY = {"古装", "古代服装", "布衣", "麻布", "粗布", "朴素", "常服", "默认服装"}
_FEMALE_MARKERS = {"FEMALE", "WOMAN", "女", "女性", "女子", "女人"}
_CONFIRMED_ADULT_MARKERS = {"CONFIRMED_ADULT", "ADULT", "成年", "成年人", "明确成年"}
_EXPLICIT_VISUAL_TERMS = {
    "裸体", "全裸", "裸胸", "露点", "透视露点", "生殖器", "性行为", "色情",
    "nude", "naked", "nipples", "genitals", "pornographic", "sex act",
}


def _text(value: object) -> str:
    return str(value or "").strip()


def _visible_humans(unit: dict[str, Any]) -> list[str]:
    names: list[str] = []
    animal_names = {
        _text(value) for value in ((unit.get("wardrobe_contract") or {}).get("animal_characters") or [])
    }
    for spec in unit.get("ordered_prompt_specs") or []:
        for row in spec.get("cast") or []:
            name = _text(row.get("character"))
            entity_type = _text(row.get("entity_type")).upper()
            if (
                name
                and name not in animal_names
                and _text(row.get("face_visibility")).upper() != "OFFSCREEN_VOICE_ONLY"
                and entity_type not in ANIMAL_MARKERS
                and name not in names
            ):
                names.append(name)
    return names


def _normalize_row(row: dict[str, Any], *, source_id: str) -> dict[str, str]:
    normalized = {field: _text(row.get(field)) for field in REQUIRED_FIELDS}
    missing = [field for field, value in normalized.items() if not value]
    if missing:
        raise ValueError(f"{source_id}:WARDROBE_FIELDS_MISSING:{normalized.get('character')}:{','.join(missing)}")
    for field in REQUIRED_FIELDS[2:]:
        if normalized[field] in VAGUE_ONLY:
            raise ValueError(
                f"{source_id}:WARDROBE_VAGUE_DEFAULT_FORBIDDEN:{normalized['character']}:{field}:{normalized[field]}"
            )
    material = normalized["material"]
    if any(token in material for token in ("麻布", "粗布")) and not _text(row.get("material_justification")):
        raise ValueError(
            f"{source_id}:WARDROBE_LOW_STATUS_MATERIAL_REQUIRES_SCRIPT_JUSTIFICATION:{normalized['character']}"
        )
    normalized["material_justification"] = _text(row.get("material_justification"))
    return normalized


def validate_wardrobe_contract(unit: dict[str, Any], *, source_id: str | None = None) -> dict[str, Any]:
    source_id = source_id or _text(unit.get("unit_id")) or "UNKNOWN"
    contract = unit.get("wardrobe_contract")
    failures: list[str] = []
    if not isinstance(contract, dict):
        return {
            "schema": SCHEMA,
            "status": "FAIL",
            "source_id": source_id,
            "failures": [f"{source_id}:WARDROBE_CONTRACT_MISSING"],
        }
    rows = contract.get("characters")
    if not isinstance(rows, list):
        return {
            "schema": SCHEMA,
            "status": "FAIL",
            "source_id": source_id,
            "failures": [f"{source_id}:WARDROBE_CHARACTER_ROWS_MISSING"],
        }
    normalized: list[dict[str, str]] = []
    for row in rows:
        try:
            normalized.append(_normalize_row(row, source_id=source_id))
        except ValueError as exc:
            failures.append(str(exc))
    by_name = {row["character"]: row for row in normalized}
    expected = _visible_humans(unit)
    if sorted(by_name) != sorted(expected):
        failures.append(
            f"{source_id}:WARDROBE_VISIBLE_CAST_COVERAGE:{sorted(by_name)}!={sorted(expected)}"
        )
    keys: dict[str, str] = {}
    for row in normalized:
        key = row["continuity_key"]
        if key in keys and keys[key] != row["character"]:
            failures.append(f"{source_id}:WARDROBE_CONTINUITY_KEY_COLLISION:{key}")
        keys[key] = row["character"]
    for index, left in enumerate(normalized):
        for right in normalized[index + 1 :]:
            if left["social_tier"] != right["social_tier"]:
                continue
            differences = [field for field in DISTINCTION_FIELDS if left[field] != right[field]]
            if len(differences) < 3:
                failures.append(
                    f"{source_id}:WARDROBE_PEER_DISTINCTION_INSUFFICIENT:"
                    f"{left['character']}:{right['character']}:{len(differences)}<3"
                )
    return {
        "schema": SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "source_id": source_id,
        "visible_human_characters": expected,
        "character_count": len(normalized),
        "characters": normalized,
        "failures": failures,
    }


def wardrobe_prompt_block(unit: dict[str, Any], *, concise: bool = False) -> str:
    report = validate_wardrobe_contract(unit)
    if report["status"] != "PASS":
        raise ValueError(";".join(report["failures"]))
    clauses: list[str] = []
    for row in report["characters"]:
        if concise:
            clauses.append(
                f"{row['character']}={row['social_tier']}；{row['silhouette']}；"
                f"外层{row['outer_layer']}、内层{row['inner_layer']}；"
                f"{row['primary_color']}主色配{row['secondary_color']}；"
                f"{row['material']}，{row['pattern']}；{row['belt_or_fastening']}；"
                f"{row['footwear']}；{row['accessory']}；{row['condition']}"
            )
        else:
            clauses.append(
                f"人物={row['character']}；地位依据={row['role_basis']}；层级={row['social_tier']}；"
                f"轮廓={row['silhouette']}；外层={row['outer_layer']}；内层={row['inner_layer']}；"
                f"主色={row['primary_color']}；辅色={row['secondary_color']}；材质={row['material']}；"
                f"纹样={row['pattern']}；腰带或扣合={row['belt_or_fastening']}；鞋履={row['footwear']}；"
                f"配饰={row['accessory']}；新旧状态={row['condition']}；连续性键={row['continuity_key']}"
            )
    return "；".join(clauses) + "。同阶人物仍须保持各自轮廓、颜色、材质和配饰差异，禁止全员默认麻布或粗布。"


def h3_adult_female_visual_block(unit: dict[str, Any]) -> str:
    """Return H3-only tasteful mature styling for explicitly adult women.

    The Seedance compiler intentionally does not call this function.  A row
    must explicitly establish both female presentation and adult status;
    unknown or ambiguous age silently receives no sensual styling.  Explicit
    sexual or nude directions fail closed rather than entering a model prompt.
    """
    contract = unit.get("wardrobe_contract") or {}
    clauses: list[str] = []
    for row in contract.get("characters") or []:
        gender = _text(row.get("gender_presentation"))
        adult_status = _text(row.get("adult_status"))
        custom = _text(row.get("mature_visual_direction"))
        is_female = gender.upper() in _FEMALE_MARKERS or gender in _FEMALE_MARKERS
        is_adult = adult_status.upper() in _CONFIRMED_ADULT_MARKERS or adult_status in _CONFIRMED_ADULT_MARKERS
        if custom and any(term.lower() in custom.lower() for term in _EXPLICIT_VISUAL_TERMS):
            raise ValueError(
                f"{_text(unit.get('unit_id')) or 'UNKNOWN'}:H3_ADULT_FEMALE_EXPLICIT_VISUAL_FORBIDDEN:"
                f"{_text(row.get('character'))}"
            )
        if not (is_female and is_adult):
            continue
        direction = custom or (
            "明确成年、成熟丰满且比例自然，胸腰臀曲线比默认造型更鲜明但不夸张；"
            "以符合角色身份与时代的合身剪裁、明确腰线、肩颈线、面料垂坠和克制妆发展现健康性感；"
            "保持完整衣着，不裸露、不透视、不低俗"
        )
        clauses.append(f"{_text(row.get('character'))}={direction}")
    if not clauses:
        return ""
    return (
        "成年女性造型锁（仅H3）：" + "；".join(clauses) +
        "。性感只来自成年体态、剪裁、色彩、质感与表演气质，必须服从剧情、身份、年代和角色连续性。"
    )


def model_specific_adult_female_visual_block(
    unit: dict[str, Any], *, target_video_model: str
) -> str:
    """Share the H3 adult-woman style contract with still and video prompts.

    Keyframes that will feed an H3 episode must carry the same character-shape
    authority as the H3 video prompt.  Seedance inputs intentionally return an
    empty block so its established compiler contract is unchanged.
    """
    model = _text(target_video_model).lower()
    if model not in {"minimax-h3", "h3"}:
        return ""
    return h3_adult_female_visual_block(unit)


def wardrobe_rows_for_cast(
    unit: dict[str, Any], episode_bible: dict[str, Any]
) -> dict[str, Any]:
    """Bind the episode wardrobe bible to one unit's visible human cast."""
    source_rows = episode_bible.get("characters") or []
    by_name = {_text(row.get("character")): row for row in source_rows}
    probe = dict(unit)
    probe["wardrobe_contract"] = {
        "animal_characters": list(episode_bible.get("animal_characters") or [])
    }
    names = _visible_humans(probe)
    missing = [name for name in names if name not in by_name]
    if missing:
        raise ValueError(f"{unit.get('unit_id')}:WARDROBE_BIBLE_MISSING:{','.join(missing)}")
    return {
        "schema": SCHEMA,
        "episode_bible_id": _text(episode_bible.get("bible_id")),
        "animal_characters": list(episode_bible.get("animal_characters") or []),
        "characters": [dict(by_name[name]) for name in names],
    }
