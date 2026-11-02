#!/usr/bin/env python3
"""Validate H3's English-only machine-instruction projection.

MiniMax H3 receives English machine metadata.  Chinese is permitted only in
literal dialogue inside ``<d>[Chinese]...</d>`` (English-dialogue episodes tag
their literals ``<d>[English]...</d>``).  The English projection is a
translation layer over the immutable shared execution plan; it never replaces
or mutates the Chinese directing contract used by SD2.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


SCHEMA = "qingshan.h3_provider_english_contract.v1_source_sha_bound"
CJK = re.compile(r"[\u3400-\u9fff]")
DIALOGUE_TAG = re.compile(r"<d>\[(?:Chinese|English)\]\s*(.*?)</d>", re.DOTALL)
QUOTED_CJK = re.compile(r"(?:\"[^\"\n]*[\u3400-\u9fff][^\"\n]*\"|[“”「」『』][^\n]*[\u3400-\u9fff])")

#: The only Chinese allowed outside the dialogue tags: the MiniMax-H3 provider expert's constraint sentences,
#: verbatim, rendered when a CAMERA_GRAMMAR_V1 unit opts in with ``h3_constraint_language: "zh"`` (owner-approved
#: Chinese-vs-English A/B, 2026-10-26).  Everything else in an H3 prompt stays English; any other CJK still fails.
H3_CONSTRAINT_ZH = {
    "one_take": "全程一镜到底，中间不要出现切镜或拼接",
    "fixed_camera": "机位固定，不推、不拉、不摇、不移",
    "silent": "本段没有任何对白、画外音、旁白或人声，人物都不说话。",
    "only_this_line": "只说这一句台词，只说一次；台词前后没有任何其他对白、画外音、旁白或人声。",
    "only_these_lines": "只说以下这几句台词，每句只说一次，按顺序；台词前后和之间没有任何其他对白、画外音、旁白或人声。",
    "no_duplicate": ("视频全程禁止出现外形、着装、配饰完全一致的人物，禁止生成同款分身、双胞胎效果，"
                     "同一画面中仅保留单个对应人物，不出现人物重复复刻。"),
}
H3_CONSTRAINT_LANGUAGE_FIELD = "h3_constraint_language"


def h3_constraint_language(payload: dict[str, Any] | None) -> str:
    """"zh" when a unit/contract opts into Chinese constraint sentences, else "en" (the default)."""
    # Retired for production (owner, lab 武松 E01 2026-11-02): with Chinese dialogue H3 reads these Chinese
    # constraint sentences aloud as speech ("只说这一句台词，只说一次…" in 9 of 17 speaking units).  A contract-level
    # "zh" is ignored; only an explicit A/B variant task (tools/h3_constraint_ab_variant.py) may still render them.
    payload = payload or {}
    value = str(payload.get(H3_CONSTRAINT_LANGUAGE_FIELD) or "").strip().lower()
    if not payload.get("ab_variant_schema"):
        return "en"
    return "zh" if value in {"zh", "zh-cn", "chinese"} else "en"


#: Strict camera lock (owner A/B, lab Holmes E06 2026-10-26: locked units still pushed in, face width
#: 0.41 -> 0.81; with the lock wording VU-008 push-in 65% -> 15%, VU-001 98% -> 39%).  DEFAULT for every
#: CAMERA_GRAMMAR_V1 single-take locked-camera unit (owner 2026-10-26).  Since 2026-11-01 (owner, lab E12 long-take
#: test: H3 read the old all-caps "CAMERA LOCK — ABSOLUTE RULE:" top block aloud as invented speech) the rule is an
#: ordinary sentence at the end of the Camera section (CAMERA_LOCK_TRIPOD) plus extra Never items; no all-caps
#: label anywhere.  The V1 director renders CAMERA_LOCK_FROZEN_CLAUSE in its camera line.
#: ``h3_camera_lock: "standard"`` opts a unit/contract out; ``"strict"`` forces it (refused on a moving camera).
#: Unstamped units never get it.
H3_CAMERA_LOCK_FIELD = "h3_camera_lock"
#: LEGACY (2026-10-26 .. 2026-11-01): the old top block, kept only so prompts submitted with it are still
#: recognized as DIRECTOR_PROMPT_V2 text (DIRECTOR_V2_TEXT_START); never rendered any more.
CAMERA_LOCK_STRICT = (
    "CAMERA LOCK \u2014 ABSOLUTE RULE: the camera is bolted to a tripod for the whole clip. No zoom, no push-in, "
    "no dolly, no crop change. The subject's size in the frame stays exactly the same from the first frame to the "
    "last; the face never gets bigger or smaller. Any move closer is a failed shot."
)
#: LEGACY camera sentence of the same period (replaced by CAMERA_LOCK_TRIPOD)
CAMERA_LOCK_FROZEN_FRAME = "Frame size is frozen: same shot size as @Image1 at every moment."
#: the strict camera lock as one plain Camera-section sentence (owner 2026-11-01)
CAMERA_LOCK_TRIPOD = ("The camera stays on a tripod for the whole clip: no zoom, no push-in, no dolly, no crop change; "
                      "the subject keeps the same size in frame as in @Image1 from the first frame to the last.")
CAMERA_LOCK_NEVER = "zooming in, pushing in, dollying in, moving closer to the face, tightening the frame"
#: where a DIRECTOR_PROMPT_V2 text starts: "References:", optionally after the legacy camera-lock block
DIRECTOR_V2_TEXT_START = re.compile(r"(?:" + re.escape(CAMERA_LOCK_STRICT) + r"\n\n)?References:\n")
#: an all-caps label H3 could read aloud ("CAMERA LOCK — ABSOLUTE RULE:"); DIRECTOR_PROMPT_V2 never renders one
ALL_CAPS_LABEL = re.compile(r"\b[A-Z]{2,}(?:[ \t]+[A-Z]{2,})*[ \t]*(?:[\u2014\u2013-][^:\n]{0,40})?:")


#: V1 director (key: value) camera-line clause of the same rule
CAMERA_LOCK_FROZEN_CLAUSE = ("frame size is frozen: the subject stays exactly the same size in frame from the first "
                             "frame to the last, never closer, no zoom-in, no crop change")
CAMERA_LOCK_MODES = ("strict", "standard")

#: Engine redo after an objective Q2 FAIL (q2_auto_redo ``h3_redo_findings``; line owner 2026-10-29, lab E08 VU-017
#: pushed in +90%): the redo prompt states the measured problem in plain words, on top of the strict camera lock.
#: CAMERA_GRAMMAR_V1 locked-camera units only; absent field = no sentence.
H3_REDO_FINDINGS_FIELD = "h3_redo_findings"
REDO_FINDING_SENTENCES = {
    "push_in": ("The previous take pushed in on the face; this take must keep exactly the @Image1 shot size "
                "for the whole clip."),
}


def redo_finding_sentences(payload: dict[str, Any] | None) -> list[str]:
    """The plain-words sentences of a unit's declared redo findings (unknown findings are ignored)."""
    raw = (payload or {}).get(H3_REDO_FINDINGS_FIELD) or []
    raw = [raw] if isinstance(raw, str) else list(raw)
    return [REDO_FINDING_SENTENCES[f] for f in dict.fromkeys(str(v).strip().lower() for v in raw)
            if f in REDO_FINDING_SENTENCES]


def h3_camera_lock(payload: dict[str, Any] | None) -> str:
    """The declared camera-lock mode of a unit/contract: "strict", "standard" (opt-out) or "" (not declared)."""
    value = str((payload or {}).get(H3_CAMERA_LOCK_FIELD) or "").strip().lower()
    return value if value in CAMERA_LOCK_MODES else ""


def strict_camera_lock_applies(payload: dict[str, Any] | None, *, stamped: bool, locked_single_take: bool) -> bool:
    """Whether a unit renders the strict camera lock: CAMERA_GRAMMAR_V1 only; declared "standard" opts out,
    declared "strict" forces it (the renderer refuses it on a moving camera), otherwise (the default) every
    locked-camera single-take unit gets it."""
    if not stamped:
        return False
    declared = h3_camera_lock(payload)
    if declared == "standard":
        return False
    return declared == "strict" or locked_single_take


def is_director_v2_text(text: str) -> bool:
    """A DIRECTOR_PROMPT_V2 prompt (tools/h3_director_prompt_v2.py), with or without the camera-lock block."""
    return bool(DIRECTOR_V2_TEXT_START.match(text)) and "\n\nWho is in frame" in text


def _outside_allowed_text(text: str) -> str:
    outside = DIALOGUE_TAG.sub("", text)
    for phrase in sorted(H3_CONSTRAINT_ZH.values(), key=len, reverse=True):
        outside = outside.replace(phrase, "")
    return outside


def validate_h3_provider_text_boundary(text: str, *, source_id: str) -> dict[str, Any]:
    failures: list[str] = []
    outside = _outside_allowed_text(text)
    if CJK.search(outside):
        failures.append(f"H3_CJK_OUTSIDE_DIALOGUE:{source_id}")
    # quoted Chinese is only forbidden OUTSIDE the dialogue tags: a line like 「好，走吧。」 or a book-title
    # quote inside <d>[Chinese]...</d> is the permitted dialogue itself (401122 《新石头记》 E13, 2026-10-16)
    if QUOTED_CJK.search(outside):
        failures.append(f"H3_QUOTED_CJK_FORBIDDEN:{source_id}")
    return {
        "schema": SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "source_id": source_id,
        "cjk_outside_dialogue_count": len(CJK.findall(outside)),
        "failures": failures,
    }


def require_h3_provider_english_contract(
    unit: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    uid = str(plan.get("unit_id") or "UNKNOWN")
    contract = deepcopy(unit.get("h3_provider_english_contract") or {})
    failures: list[str] = []
    if contract.get("schema") != SCHEMA:
        failures.append(f"H3_ENGLISH_CONTRACT_SCHEMA:{uid}")
    if contract.get("source_execution_semantics_sha256") != plan.get("execution_semantics_sha256"):
        failures.append(f"H3_ENGLISH_CONTRACT_SOURCE_SHA_MISMATCH:{uid}")
    for key in ("identity_prop_fact", "space_weather_fact"):
        value = str(contract.get(key) or "").strip()
        if not value:
            failures.append(f"H3_ENGLISH_CONTRACT_FIELD_MISSING:{uid}:{key}")
        elif CJK.search(value):
            failures.append(f"H3_ENGLISH_CONTRACT_CJK:{uid}:{key}")
    if plan.get("persistent_state_contract"):
        value = str(contract.get("persistent_state_lock") or "").strip()
        if not value:
            failures.append(f"H3_ENGLISH_CONTRACT_FIELD_MISSING:{uid}:persistent_state_lock")
        elif CJK.search(value):
            failures.append(f"H3_ENGLISH_CONTRACT_CJK:{uid}:persistent_state_lock")
    source_shot_states = plan.get("shot_state_contracts") or []
    translated_shot_states = contract.get("shot_state_locks") or []
    if len(translated_shot_states) != len(source_shot_states):
        failures.append(
            f"H3_ENGLISH_CONTRACT_SHOT_STATE_COUNT:{uid}:"
            f"{len(translated_shot_states)}!={len(source_shot_states)}"
        )
    for index, value in enumerate(translated_shot_states):
        if not str(value or "").strip():
            failures.append(f"H3_ENGLISH_CONTRACT_SHOT_STATE_MISSING:{uid}:{index + 1}")
        elif CJK.search(str(value)):
            failures.append(f"H3_ENGLISH_CONTRACT_CJK:{uid}:shot_state_locks[{index}]")
    source_beats = plan.get("beats") or []
    translated_beats = contract.get("beats") or []
    if len(translated_beats) != len(source_beats):
        failures.append(
            f"H3_ENGLISH_CONTRACT_BEAT_COUNT:{uid}:{len(translated_beats)}!={len(source_beats)}"
        )
    required = ("entry_state", "primary_action", "exit_state")
    optional_if_source = (
        "contact_point", "force_feedback", "microexpression_cue", "body_sync_cue",
        "internal_transition_after",
    )
    for index, source in enumerate(source_beats):
        row = translated_beats[index] if index < len(translated_beats) else {}
        for key in required:
            if not str(row.get(key) or "").strip():
                failures.append(f"H3_ENGLISH_CONTRACT_BEAT_FIELD_MISSING:{uid}:{index + 1}:{key}")
        for key in optional_if_source:
            if source.get(key) and not str(row.get(key) or "").strip():
                failures.append(f"H3_ENGLISH_CONTRACT_BEAT_FIELD_MISSING:{uid}:{index + 1}:{key}")
        source_secondary = source.get("secondary_feedback") or []
        translated_secondary = row.get("secondary_feedback") or []
        if len(translated_secondary) != len(source_secondary):
            failures.append(
                f"H3_ENGLISH_CONTRACT_SECONDARY_FEEDBACK_COUNT:{uid}:{index + 1}:"
                f"{len(translated_secondary)}!={len(source_secondary)}"
            )
        for key, value in row.items():
            if isinstance(value, str) and CJK.search(value):
                failures.append(f"H3_ENGLISH_CONTRACT_CJK:{uid}:beats[{index}].{key}")
    source_spatial = [
        role for role in (plan.get("role_bindings") or []) if role.get("spatial_dialogue")
    ]
    if source_spatial:
        translated_spatial = contract.get("spatial_dialogue") or []
        if len(translated_spatial) != len(source_spatial):
            failures.append(
                f"H3_ENGLISH_CONTRACT_SPATIAL_COUNT:{uid}:"
                f"{len(translated_spatial)}!={len(source_spatial)}"
            )
        for index, row in enumerate(translated_spatial):
            if not isinstance(row, dict):
                failures.append(f"H3_ENGLISH_CONTRACT_SPATIAL_INVALID:{uid}:{index + 1}")
                continue
            for key, value in row.items():
                if isinstance(value, str) and CJK.search(value):
                    failures.append(
                        f"H3_ENGLISH_CONTRACT_CJK:{uid}:spatial_dialogue[{index}].{key}"
                    )
    for section in ("sounds", "environment_motion", "negative_constraints", "transition"):
        value = contract.get(section)
        if value is None:
            continue
        strings: list[str] = []
        if isinstance(value, dict):
            for child in value.values():
                strings.extend(child if isinstance(child, list) else [child])
        elif isinstance(value, list):
            strings.extend(value)
        else:
            strings.append(value)
        if any(CJK.search(str(row or "")) for row in strings):
            failures.append(f"H3_ENGLISH_CONTRACT_CJK:{uid}:{section}")
    if failures:
        raise ValueError(";".join(failures))
    return contract


def bind_h3_provider_english_contract(
    unit: dict[str, Any], translated_fields: dict[str, Any]
) -> dict[str, Any]:
    """Bind an authored English translation to the current shared semantics.

    This helper is intended for the writer/director build stage.  It computes
    the source SHA locally; provider submission still revalidates that binding.
    """
    try:
        from tools.video_execution_plan_compiler import compile_video_execution_plan
    except ModuleNotFoundError:
        from video_execution_plan_compiler import compile_video_execution_plan
    probe = deepcopy(unit)
    probe.pop("h3_provider_english_contract", None)
    plan = compile_video_execution_plan(probe)
    contract = deepcopy(translated_fields)
    contract["schema"] = SCHEMA
    contract["source_execution_semantics_sha256"] = plan["execution_semantics_sha256"]
    unit["h3_provider_english_contract"] = contract
    return unit
