#!/usr/bin/env python3
"""Fail closed when a paid media prompt leaves character roles ambiguous."""

from __future__ import annotations

import re
from typing import Any


SCHEMA = "qingshan.role_semantic_disambiguation.v1"


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    for marker in ("说这句时", "说完这句时", "台词期间", "对白期间", "本镜头结果", "本节拍"):
        text = text.replace(marker, "")
    return re.sub(r"\s+", " ", text).strip()


def role_semantic_prompt_block(row: dict[str, Any]) -> str:
    """Serialize one role row without asking the provider to infer anything.

    Empty conversational roles are written as explicit ``NONE`` values.  This
    matters for environmental beats: omitting a speaker/actor slot can make a
    multimodal model invent a person to perform the change.
    """
    states = row.get("entity_states") or {}
    state_text = "；".join(
        f"{_clean(entity)}={_clean(state)}" for entity, state in states.items()
    ) or "NONE"
    referents = [
        ("第一人称指代", row.get("first_person_pronoun")),
        ("第二人称指代", row.get("second_person_pronoun")),
        ("动作代词指代", row.get("action_pronoun_referent")),
        ("动作对手指代", row.get("action_counterparty_referent")),
        ("对白第三人称指代", row.get("dialogue_third_person_referent")),
        ("身体局部唯一主人", row.get("body_part_owner")),
    ]
    presence = row.get("entity_presence") or {}
    presence_text = "；".join(
        f"{_clean(entity)}={_clean(value)}" for entity, value in presence.items()
    ) or "NONE"
    return (
        "角色语义消歧硬锁："
        f"镜头ID={_clean(row.get('shot_id')) or 'UNRESOLVED'}；"
        f"唯一主动作执行者={_clean(row.get('primary_actor')) or 'NONE'}；"
        f"主动作执行者类型={_clean(row.get('primary_actor_kind')) or 'CHARACTER'}；"
        f"唯一对白说话人={_clean(row.get('dialogue_speaker')) or 'NONE'}；"
        f"唯一对白听者={_clean(row.get('dialogue_listener')) or 'NONE'}；"
        f"唯一动作承受者={_clean(row.get('action_patient')) or 'NONE'}；"
        + "；".join(f"{label}={_clean(value) or 'NONE'}" for label, value in referents)
        + f"；逐实体状态={state_text}；逐实体出入画状态={presence_text}。"
        "禁止模型根据站位、服装、性别、年龄、镜头中心、参考图顺序或声音来源自行交换、合并、拆分或补造人物；"
        "每句对白只允许具名说话人使用自己的口型和固定声线，听者及背景人物保持闭口；"
        "每个动作只允许具名执行者作用于具名承受者，未具名实体不得接管动作。"
    )


def role_semantic_compact_prompt_block(row: dict[str, Any]) -> str:
    """Serialize the same hard lock for H3 speech-isolation prompts.

    English machine keys reduce the chance that H3 vocalizes directing prose,
    while canonical entity names stay explicit and deterministic.
    """
    presence = row.get("entity_presence") or {}
    presence_text = "|".join(
        f"{_clean(entity)}:{_clean(value)}" for entity, value in presence.items()
    ) or "NONE"
    return (
        f"ROLE_LOCK[{_clean(row.get('shot_id')) or 'UNRESOLVED'}]:"
        f"ACTOR={_clean(row.get('primary_actor')) or 'NONE'};"
        f"ACTOR_KIND={_clean(row.get('primary_actor_kind')) or 'CHARACTER'};"
        f"SPEAKER={_clean(row.get('dialogue_speaker')) or 'NONE'};"
        f"LISTENER={_clean(row.get('dialogue_listener')) or 'NONE'};"
        f"PATIENT={_clean(row.get('action_patient')) or 'NONE'};"
        f"P1={_clean(row.get('first_person_pronoun')) or 'NONE'};"
        f"P2={_clean(row.get('second_person_pronoun')) or 'NONE'};"
        f"ACTION_REF={_clean(row.get('action_pronoun_referent')) or 'NONE'};"
        f"COUNTERPARTY={_clean(row.get('action_counterparty_referent')) or 'NONE'};"
        f"P3={_clean(row.get('dialogue_third_person_referent')) or 'NONE'};"
        f"BODY_OWNER={_clean(row.get('body_part_owner')) or 'NONE'};"
        f"PRESENCE={presence_text};NEVER_SWAP_MERGE_SPLIT_INVENT_OR_REVOICE."
    )


def _episode_number(value: Any) -> int:
    match = re.match(r"E(\d+)", str(value or "").upper())
    return int(match.group(1)) if match else 0


def _role_rows(task: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    direct = task.get("role_semantic_disambiguation")
    if isinstance(direct, dict):
        rows.append(direct)
    contract = task.get("prompt_contract") or {}
    nested = contract.get("role_semantic_disambiguation")
    if isinstance(nested, dict) and nested not in rows:
        rows.append(nested)
    machine = task.get("machine_contract") or {}
    for spec in machine.get("ordered_prompt_specs") or task.get("ordered_prompt_specs") or []:
        row = spec.get("role_semantic_disambiguation") if isinstance(spec, dict) else None
        if isinstance(row, dict):
            rows.append(row)
    return rows


def validate_role_semantics(
    task: dict[str, Any], prompt_text: str, *, required_from_episode: int = 48
) -> list[str]:
    """Return deterministic failures for unresolved or unbound character semantics.

    This gate intentionally checks structured evidence, not only prose tokens.  A
    prompt saying "do not swap roles" is insufficient unless actor, speaker,
    listener, patient, pronoun referents, and per-entity states were resolved by
    the compiler first.
    """
    if _episode_number(task.get("episode")) < required_from_episode:
        return []
    rows = _role_rows(task)
    if not rows:
        return ["ROLE_SEMANTIC_DISAMBIGUATION_MISSING"]
    failures: list[str] = []
    seen_shot_ids: set[str] = set()
    for index, row in enumerate(rows, 1):
        prefix = f"ROLE_{index}"
        if row.get("schema") != SCHEMA:
            failures.append(f"{prefix}_SCHEMA_INVALID")
        if row.get("status") != "PASS":
            failures.append(f"{prefix}_NOT_PASS")
        if row.get("unresolved"):
            failures.append(f"{prefix}_UNRESOLVED:" + ",".join(map(str, row["unresolved"])))
        if row.get("forbidden_role_swaps") is not True:
            failures.append(f"{prefix}_ROLE_SWAP_GUARD_MISSING")

        shot_id = _clean(row.get("shot_id"))
        if not shot_id:
            failures.append(f"{prefix}_SHOT_ID_MISSING")
        elif shot_id in seen_shot_ids:
            failures.append(f"{prefix}_DUPLICATE_SHOT_ID:{shot_id}")
        seen_shot_ids.add(shot_id)

        actor = _clean(row.get("primary_actor"))
        actor_kind = _clean(row.get("primary_actor_kind")) or "CHARACTER"
        speaker = _clean(row.get("dialogue_speaker"))
        listener = _clean(row.get("dialogue_listener"))
        patient = _clean(row.get("action_patient"))
        states = row.get("entity_states") or {}
        presence = row.get("entity_presence") or {}
        if not actor:
            failures.append(f"{prefix}_PRIMARY_ACTOR_MISSING")
        if actor_kind not in {"CHARACTER", "GROUP", "PROP", "ENVIRONMENT", "ANIMAL", "BODY_PART"}:
            failures.append(f"{prefix}_PRIMARY_ACTOR_KIND_INVALID:{actor_kind}")
        body_part_owner = _clean(row.get("body_part_owner"))
        if actor_kind == "BODY_PART" and not body_part_owner:
            failures.append(f"{prefix}_BODY_PART_OWNER_MISSING")
        if speaker and not listener:
            failures.append(f"{prefix}_DIALOGUE_LISTENER_MISSING")
        if listener and not speaker:
            failures.append(f"{prefix}_LISTENER_WITHOUT_SPEAKER")
        if speaker and speaker == listener:
            failures.append(f"{prefix}_SPEAKER_LISTENER_COLLISION:{speaker}")
        if patient and patient == actor and row.get("self_directed_action") is not True:
            failures.append(f"{prefix}_ACTOR_PATIENT_COLLISION:{actor}")
        if actor_kind in {"CHARACTER", "GROUP", "ANIMAL", "BODY_PART"} and actor not in states:
            failures.append(f"{prefix}_ACTOR_STATE_MISSING:{actor}")
        if speaker and speaker not in states:
            failures.append(f"{prefix}_SPEAKER_STATE_MISSING:{speaker}")
        if listener and listener not in states:
            failures.append(f"{prefix}_LISTENER_STATE_MISSING:{listener}")
        if patient and patient not in states:
            failures.append(f"{prefix}_PATIENT_STATE_MISSING:{patient}")
        if body_part_owner and body_part_owner not in states:
            failures.append(f"{prefix}_BODY_PART_OWNER_STATE_MISSING:{body_part_owner}")
        if set(map(str, states)) != set(map(str, presence)):
            failures.append(f"{prefix}_ENTITY_PRESENCE_COVERAGE_MISMATCH")
        allowed_presence = {
            "VISIBLE_AND_IDENTITY_LOCKED",
            "OFFSCREEN_VOICE_ONLY",
            "ABSENT_REFERENCE_ONLY",
            "OWNER_PARTIALLY_OCCLUDED_BUT_ANATOMICALLY_CONTINUOUS",
        }
        for entity, value in presence.items():
            if _clean(value) not in allowed_presence:
                failures.append(f"{prefix}_ENTITY_PRESENCE_INVALID:{entity}:{value}")
        for label, value in (
            ("PRIMARY_ACTOR", actor),
            ("DIALOGUE_SPEAKER", speaker),
            ("DIALOGUE_LISTENER", listener),
            ("ACTION_PATIENT", patient),
        ):
            if value and value not in prompt_text:
                failures.append(f"{prefix}_{label}_NOT_BOUND_IN_PROMPT:{value}")
        for field in (
            "first_person_pronoun",
            "second_person_pronoun",
            "action_pronoun_referent",
            "action_counterparty_referent",
            "dialogue_third_person_referent",
            "body_part_owner",
        ):
            value = _clean(row.get(field))
            if value and value not in prompt_text:
                failures.append(f"{prefix}_{field.upper()}_NOT_BOUND_IN_PROMPT:{value}")
            if value and value not in states:
                failures.append(f"{prefix}_{field.upper()}_NOT_REGISTERED:{value}")
        if len(states) != len(set(map(str, states.keys()))):
            failures.append(f"{prefix}_DUPLICATE_ENTITY_STATE")
        for entity, state in states.items():
            if not _clean(entity) or not _clean(state):
                failures.append(f"{prefix}_EMPTY_ENTITY_STATE")
            elif str(entity) not in prompt_text:
                failures.append(f"{prefix}_ENTITY_STATE_NOT_BOUND_IN_PROMPT:{entity}")

        full_block = role_semantic_prompt_block(row)
        compact_block = role_semantic_compact_prompt_block(row)
        block_count = prompt_text.count(full_block) + prompt_text.count(compact_block)
        if block_count != 1:
            failures.append(f"{prefix}_EXACT_ROLE_BLOCK_COUNT:{block_count}")

    full_lock = all(phrase in prompt_text for phrase in (
        "唯一主动作执行者=", "主动作执行者类型=", "唯一对白说话人=",
        "唯一对白听者=", "唯一动作承受者=", "逐实体出入画状态=",
        "禁止模型根据站位、服装、性别、年龄、镜头中心、参考图顺序或声音来源自行交换",
    ))
    compact_lock = all(phrase in prompt_text for phrase in (
        "ROLE_LOCK[", "ACTOR=", "ACTOR_KIND=", "SPEAKER=", "LISTENER=",
        "PATIENT=", "PRESENCE=", "NEVER_SWAP_MERGE_SPLIT_INVENT_OR_REVOICE",
    ))
    if not (full_lock or compact_lock):
        failures.append("ROLE_PROMPT_HARD_LOCK_MISSING:FULL_OR_COMPACT_ROLE_LOCK")
    return failures


def validate_role_semantics_structure(
    task: dict[str, Any], *, required_from_episode: int = 48
) -> list[str]:
    """Validate the internal role graph without serializing it to the provider.

    MiniMax-H3 Ref2VA prompts must not expose the legacy ``ROLE_LOCK`` prose.
    The ambiguity protection still remains mandatory, so this function runs the
    same structural checks against machine evidence while deliberately omitting
    provider-prompt token/bock-presence checks.
    """
    if _episode_number(task.get("episode")) < required_from_episode:
        return []
    rows = _role_rows(task)
    if not rows:
        return ["ROLE_SEMANTIC_DISAMBIGUATION_MISSING"]
    failures: list[str] = []
    seen_shot_ids: set[str] = set()
    for index, row in enumerate(rows, 1):
        prefix = f"ROLE_{index}"
        if row.get("schema") != SCHEMA:
            failures.append(f"{prefix}_SCHEMA_INVALID")
        if row.get("status") != "PASS":
            failures.append(f"{prefix}_NOT_PASS")
        if row.get("unresolved"):
            failures.append(f"{prefix}_UNRESOLVED:" + ",".join(map(str, row["unresolved"])))
        if row.get("forbidden_role_swaps") is not True:
            failures.append(f"{prefix}_ROLE_SWAP_GUARD_MISSING")
        shot_id = _clean(row.get("shot_id"))
        if not shot_id:
            failures.append(f"{prefix}_SHOT_ID_MISSING")
        elif shot_id in seen_shot_ids:
            failures.append(f"{prefix}_DUPLICATE_SHOT_ID:{shot_id}")
        seen_shot_ids.add(shot_id)
        actor = _clean(row.get("primary_actor"))
        actor_kind = _clean(row.get("primary_actor_kind")) or "CHARACTER"
        speaker = _clean(row.get("dialogue_speaker"))
        listener = _clean(row.get("dialogue_listener"))
        patient = _clean(row.get("action_patient"))
        states = row.get("entity_states") or {}
        presence = row.get("entity_presence") or {}
        body_part_owner = _clean(row.get("body_part_owner"))
        if not actor:
            failures.append(f"{prefix}_PRIMARY_ACTOR_MISSING")
        if actor_kind not in {"CHARACTER", "GROUP", "PROP", "ENVIRONMENT", "ANIMAL", "BODY_PART"}:
            failures.append(f"{prefix}_PRIMARY_ACTOR_KIND_INVALID:{actor_kind}")
        if actor_kind == "BODY_PART" and not body_part_owner:
            failures.append(f"{prefix}_BODY_PART_OWNER_MISSING")
        if speaker and not listener:
            failures.append(f"{prefix}_DIALOGUE_LISTENER_MISSING")
        if listener and not speaker:
            failures.append(f"{prefix}_LISTENER_WITHOUT_SPEAKER")
        if speaker and speaker == listener:
            failures.append(f"{prefix}_SPEAKER_LISTENER_COLLISION:{speaker}")
        if patient and patient == actor and row.get("self_directed_action") is not True:
            failures.append(f"{prefix}_ACTOR_PATIENT_COLLISION:{actor}")
        for label, entity in (
            ("ACTOR", actor if actor_kind in {"CHARACTER", "GROUP", "ANIMAL", "BODY_PART"} else ""),
            ("SPEAKER", speaker), ("LISTENER", listener), ("PATIENT", patient),
            ("BODY_PART_OWNER", body_part_owner),
        ):
            if entity and entity not in states:
                failures.append(f"{prefix}_{label}_STATE_MISSING:{entity}")
        if set(map(str, states)) != set(map(str, presence)):
            failures.append(f"{prefix}_ENTITY_PRESENCE_COVERAGE_MISMATCH")
        for entity, state in states.items():
            if not _clean(entity) or not _clean(state):
                failures.append(f"{prefix}_EMPTY_ENTITY_STATE")
        allowed_presence = {
            "VISIBLE_AND_IDENTITY_LOCKED", "OFFSCREEN_VOICE_ONLY", "ABSENT_REFERENCE_ONLY",
            "OWNER_PARTIALLY_OCCLUDED_BUT_ANATOMICALLY_CONTINUOUS",
        }
        for entity, value in presence.items():
            if _clean(value) not in allowed_presence:
                failures.append(f"{prefix}_ENTITY_PRESENCE_INVALID:{entity}:{value}")
        for field in (
            "first_person_pronoun", "second_person_pronoun", "action_pronoun_referent",
            "action_counterparty_referent", "dialogue_third_person_referent", "body_part_owner",
        ):
            value = _clean(row.get(field))
            if value and value not in states:
                failures.append(f"{prefix}_{field.upper()}_NOT_REGISTERED:{value}")
    return failures
