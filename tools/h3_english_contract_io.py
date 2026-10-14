#!/usr/bin/env python3
"""Request / bind the per-unit English contract that MiniMax-H3 prompts are rendered from.

H3 receives English machine text (Chinese only inside ``<d>[Chinese]...</d>`` dialogue), rendered from
``unit["h3_provider_english_contract"]`` — an authored translation of the unit's Chinese execution
plan, bound to that plan by ``execution_semantics_sha256`` (tools/h3_provider_english_contract.py).

The NALU line has no human translator in the loop, so the grouped compiler uses this module:

* ``apply_answers(unit, answers)`` binds an answer whose ``execution_semantics_sha256`` still equals the
  unit's current plan; otherwise it returns a request row (missing, or stale because the Chinese
  source changed) and binds nothing.
* ``request_row(unit)`` is what the translator gets: the Chinese ``source`` and an ``english`` template
  of exactly the shape the renderer validates (beat / sound / shot-state / camera counts included).

The executor fills ``english`` for every requested unit and stores it in the answers file under the
row's ``answer_key`` (``<unit_id>@<first 16 hex of the source sha>``):
``{"schema": ANSWERS_SCHEMA, "units": {<answer_key>: {"execution_semantics_sha256": ..., "english": {...}}}}``;
the next compile binds it.  Keying by source sha lets the planning compile and the post-finalize render
of the same unit (whose execution plans can differ) each keep their own translation.  Nothing here calls a provider.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

REQUEST_SCHEMA = "nalu.h3_english_contract_request.v1"
ANSWERS_SCHEMA = "nalu.h3_english_contracts.v1"
CJK = re.compile(r"[㐀-鿿]")
OPTIONAL_BEAT_FIELDS = ("contact_point", "force_feedback", "primary_feedback", "force_origin",
                        "microexpression_cue", "body_sync_cue", "internal_transition_after")
CAMERA_TEXT_FIELDS = ("start_framing", "end_framing", "follow_subject", "subject_to_keep")
SOUND_KEYS = ("ambience", "foley", "action_sound")


def is_h3(unit: dict[str, Any]) -> bool:
    return str(unit.get("model") or "").lower() in {"minimax-h3", "h3"}


def plan_for(unit: dict[str, Any]) -> dict[str, Any]:
    try:
        from tools.video_execution_plan_compiler import compile_video_execution_plan
    except ModuleNotFoundError:
        from video_execution_plan_compiler import compile_video_execution_plan
    probe = deepcopy(unit)
    probe.pop("h3_provider_english_contract", None)
    return compile_video_execution_plan(probe)


def _camera_rows(unit: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        from tools.h3_provider_prompt_renderer import _shot_rows
    except ModuleNotFoundError:
        from h3_provider_prompt_renderer import _shot_rows
    action_beats = (plan.get("action_ir") or {}).get("causal_chains") or plan.get("beats") or []
    try:
        return _shot_rows(unit, plan, action_beats)
    except ValueError:
        return []


def _camera_slots(camera_plan: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    source = {k: str(camera_plan[k]) for k in CAMERA_TEXT_FIELDS
              if camera_plan.get(k) and CJK.search(str(camera_plan[k])) and not camera_plan.get(f"{k}_en")}
    return source, {k: "" for k in source}


def request_row(unit: dict[str, Any], plan: dict[str, Any] | None = None) -> dict[str, Any]:
    plan = plan or plan_for(unit)
    src: dict[str, Any] = {}
    tpl: dict[str, Any] = {}
    for key in ("identity_prop_fact", "space_weather_fact"):
        src[key] = plan.get(key) or ""
        tpl[key] = ""
    if plan.get("persistent_state_contract"):
        src["persistent_state_lock"] = plan["persistent_state_contract"]
        tpl["persistent_state_lock"] = ""
    shot_states = plan.get("shot_state_contracts") or []
    if shot_states:
        src["shot_state_locks"] = shot_states
        tpl["shot_state_locks"] = [""] * len(shot_states)
    src_beats, tpl_beats = [], []
    action_beats = (plan.get("action_ir") or {}).get("causal_chains") or plan.get("beats") or []
    for index, beat in enumerate(plan.get("beats") or []):
        rendered = action_beats[index] if index < len(action_beats) else beat
        merged = {**beat, **{k: v for k, v in rendered.items() if v}}
        s = {k: merged.get(k) for k in ("entry_state", "primary_action", "exit_state", *OPTIONAL_BEAT_FIELDS,
                                        "dialogue") if merged.get(k)}
        s["secondary_feedback"] = list(merged.get("secondary_feedback") or [])
        t = {k: "" for k in ("entry_state", "primary_action", "exit_state")}
        for key in OPTIONAL_BEAT_FIELDS:
            if merged.get(key):
                t[key] = ""
        t["secondary_feedback"] = [""] * len(beat.get("secondary_feedback") or [])
        src_beats.append(s)
        tpl_beats.append(t)
    src["beats"], tpl["beats"] = src_beats, tpl_beats
    sounds = plan.get("sounds") or {}
    src["sounds"] = {k: list(sounds.get(k) or []) for k in SOUND_KEYS}
    tpl["sounds"] = {k: [""] * len(sounds.get(k) or []) for k in SOUND_KEYS}
    env = plan.get("environment_motion") or []
    src["environment_motion"], tpl["environment_motion"] = list(env), [""] * len(env)
    transition = plan.get("transition") or {}
    src["transition"] = {k: transition[k] for k in ("incoming", "outgoing") if transition.get(k)}
    tpl["transition"] = {k: "" for k in src["transition"]}
    rows = _camera_rows(unit, plan)
    if rows:
        pairs = [_camera_slots(row.get("camera_plan") or {}) for row in rows]
        src["camera_plans"], tpl["camera_plans"] = [p[0] for p in pairs], [p[1] for p in pairs]
    else:
        src["camera_plan"], tpl["camera_plan"] = _camera_slots(plan.get("camera_plan") or {})
    return {
        "unit_id": str(unit.get("unit_id")),
        "answer_key": answer_key(unit, plan),
        "source_digest": source_digest(src, tpl),
        "execution_semantics_sha256": plan["execution_semantics_sha256"],
        "duration_seconds": plan.get("duration_seconds"),
        "source": src,
        "english": tpl,
    }


def source_digest(source: dict[str, Any], template: dict[str, Any]) -> str:
    """Digest of the text to translate and the answer shape.  Two plans of one unit can differ only in
    metadata (e.g. a rolling wave's event-boundary decision); then the translation is reused."""
    import hashlib
    return hashlib.sha256(json.dumps([source, template], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def answer_key(unit: dict[str, Any], plan: dict[str, Any]) -> str:
    return f"{unit.get('unit_id')}@{str(plan['execution_semantics_sha256'])[:16]}"


def english_problems(english: dict[str, Any], template: dict[str, Any], path: str = "english") -> list[str]:
    """Shape and language check of an answer against the request template (empty list == usable)."""
    problems: list[str] = []
    if isinstance(template, dict):
        if not isinstance(english, dict):
            return [f"{path}:NOT_AN_OBJECT"]
        for key, sub in template.items():
            if key not in english:
                problems.append(f"{path}.{key}:MISSING")
            else:
                problems.extend(english_problems(english[key], sub, f"{path}.{key}"))
    elif isinstance(template, list):
        if not isinstance(english, list) or len(english) != len(template):
            return [f"{path}:COUNT:{len(english) if isinstance(english, list) else 'n/a'}!={len(template)}"]
        for index, (value, sub) in enumerate(zip(english, template)):
            problems.extend(english_problems(value, sub, f"{path}[{index}]"))
    else:
        text = str(english or "").strip()
        if not text:
            problems.append(f"{path}:EMPTY")
        elif CJK.search(text):
            problems.append(f"{path}:CHINESE_TEXT")
    return problems


def apply_answers(unit: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any] | None:
    """Bind the unit's answer if it matches the current plan; else return the request row."""
    plan = plan_for(unit)
    row = request_row(unit, plan)
    rows = (answers or {}).get("units") or {}
    answer = rows.get(row["answer_key"]) or rows.get(str(unit.get("unit_id"))) or {}
    if not answer.get("english") or answer.get("execution_semantics_sha256") != plan["execution_semantics_sha256"]:
        # same source text, different plan metadata: reuse that translation for this plan
        reuse = next((r for k, r in rows.items() if (k == str(unit.get("unit_id")) or k.startswith(f"{unit.get('unit_id')}@"))
                      and r.get("source_digest") == row["source_digest"] and r.get("english")), None)
        if reuse:
            answer = {"execution_semantics_sha256": plan["execution_semantics_sha256"], "english": reuse["english"]}
    english = answer.get("english")
    if answer.get("execution_semantics_sha256") != plan["execution_semantics_sha256"] or not english:
        uid = str(unit.get("unit_id"))
        older = english or any(key == uid or key.startswith(uid + "@") for key in rows)
        row["reason"] = "STALE_SOURCE_CHANGED" if older else "MISSING"
        return row
    problems = english_problems(english, row["english"])
    if problems:
        row["reason"] = "ANSWER_INVALID"
        row["problems"] = problems[:20]
        row["previous_english"] = english
        return row
    contract = deepcopy(english)
    contract["schema"] = "qingshan.h3_provider_english_contract.v1_source_sha_bound"
    contract["source_execution_semantics_sha256"] = plan["execution_semantics_sha256"]
    unit["h3_provider_english_contract"] = contract
    return None


def bind_or_request(units: list[dict[str, Any]], answers_path: Path) -> list[dict[str, Any]]:
    """Bind every H3 unit it can; write ``<answers>.REQUEST.json`` for the rest and return them."""
    try:
        answers = json.loads(answers_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        answers = {}
    pending = [row for row in (apply_answers(unit, answers) for unit in units if is_h3(unit)) if row]
    request_path = answers_path.with_name(answers_path.stem + ".REQUEST.json")
    if pending:
        request_path.parent.mkdir(parents=True, exist_ok=True)
        request_path.write_text(json.dumps({
            "schema": REQUEST_SCHEMA,
            "answers_file": str(answers_path),
            "answers_schema": ANSWERS_SCHEMA,
            "instructions": (
                "For every unit below, fill `english` (same shape, every string non-empty, no Chinese "
                "characters) as a faithful English rendering of `source`: concrete visible states, actions, "
                "framings and sounds; character names in pinyin as in the identity references; never add or "
                "drop an event. Dialogue stays out of these fields (it is rendered verbatim in Chinese). "
                "Write the answers file as {\"schema\": answers_schema, \"units\": {<answer_key>: "
                "{\"execution_semantics_sha256\": <copied>, \"source_digest\": <copied>, \"english\": {...}}}} — keep "
                "every existing entry, add one per requested answer_key — then re-run the same stage."),
            "units": pending,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    elif request_path.is_file():
        request_path.unlink()
    return pending
