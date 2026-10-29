"""Per-unit advisory selection and application through the existing source-contract path.

Order of operations (requirement §7.3):
  1. deterministic applicability: ``contracts.scope_matches`` on capabilities derived
     from the unit itself (never guessed: an unknown capability does not match);
  2. precedence: authorization and the source story are never touched (no rule can
     carry authority, dialogue and narrative fields are never written); an explicit
     scene intent the rule declares as an exception wins over the rule;
  3. rank (validation scope, evidence level, intent match) and cap -- at most
     ``max_rules`` per unit and ``max_added_chars`` of added text;
  4. engineering invariants never become prompt prohibitions: CHECK_ONLY rules are
     returned as ``checks`` for deterministic code to run.

Where advice lands (why this and not a new rules engine): ``video_prompt_compiler.
compile_model_prompt`` accepts ``memory_rules`` but neither renderer reads them, and
the paid boundary (``submit_giggle_video_manifest_v2``) re-compiles every prompt from
``provider_prompt_unit(task)`` and demands byte equality.  So advice must live in the
SOURCE CONTRACT fields the renderers already turn into text, exactly where an authored
fix lives today:
  * SD2 (Chinese grammar):  ``ordered_prompt_specs[i].action.primary_action`` (direction)
                            ``ordered_prompt_specs[i].negative_prompts`` (prohibition)
  * H3 (English grammar):   ``h3_provider_english_contract.beats[i].primary_action``
                            ``h3_provider_english_contract.negative_constraints``
For H3 the Chinese source is NOT touched (that would stale the bound English contract);
the English contract is amended after it is bound.  A rule without a clause in the
grammar's language is DEFERRED -- nothing is machine-translated.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable

from . import contracts as c

DEFAULT_MAX_RULES = 3
DEFAULT_MAX_ADDED_CHARS = 400

_EVIDENCE_RANK = {level: index for index, level in enumerate(c.EVIDENCE_LEVELS)}
_VALIDATION_RANK = {scope: index for index, scope in enumerate(c.VALIDATION_SCOPES)}

# Text that tries to steer money, authority, gates or secrets.  A rule clause that matches
# is never applied: knowledge is data and may only shape direction text.
CONTROL_LANGUAGE = re.compile(
    r"(?i)(budget|credit|paid|pay\b|resubmit|re-submit|reroll|retry|disable|bypass|skip (?:the )?gate|"
    r"api[_ -]?key|secret|token|password|authori[sz]|publish|"
    r"预算|积分|付费|扣费|重做|重发|重新提交|关闭门禁|跳过门|绕过|密钥|授权|发布)")


def model_family(model: Any) -> str:
    return "h3" if str(model or "").lower() in {"minimax-h3", "h3"} else "sd2"


def _specs(unit: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in unit.get("ordered_prompt_specs") or [] if isinstance(s, dict)]


def unit_capabilities(unit: dict[str, Any], *, stage: str, engine_api_version: str) -> dict[str, Any]:
    """Capabilities read from the unit's own contract.  Nothing inferred from ids or names."""
    specs = _specs(unit)
    dialogue = [s for s in specs if str(s.get("dialogue") or "").strip()]
    combat = bool(unit.get("combat_or_chase") or unit.get("fight_or_chase")) or any(
        isinstance(s.get("action"), dict) and s["action"].get("action_kind") == "COMBAT" for s in specs)
    flags: set[str] = set()
    projection = unit.get("provider_scope_projection") or {}
    visible = set(projection.get("visible_character_ids") or [])
    for spec in specs:
        cast_ids = {str(row.get("character_id")) for row in spec.get("cast") or [] if isinstance(row, dict)}
        visible |= cast_ids
    if dialogue:
        flags.add("dialogue_present")
    for spec in dialogue:
        roles = spec.get("role_semantic_disambiguation") or {}
        listener = roles.get("dialogue_listener_id")
        if listener and listener not in visible:
            flags.add("listener_offscreen")
        if listener and (roles.get("dialogue_listener_side") or roles.get("listener_screen_side")):
            flags.add("listener_position_declared")
    if len(visible) == 1:
        flags.add("single_visible_character")
    elif len(visible) > 1:
        flags.add("multi_character")
    if combat:
        flags.add("combat_contact")
    return {
        "model": unit.get("model") or c.UNKNOWN,
        "engine_api_version": engine_api_version or c.UNKNOWN,
        "stage": stage,
        "scene_type": "COMBAT" if combat else "DIALOGUE" if dialogue else "PERFORMANCE",
        "aspect_ratio": unit.get("aspect_ratio") or c.UNKNOWN,
        "language": unit.get("dialogue_language") or "zh",
        "shot_intent": unit.get("shot_intent") or c.UNKNOWN,
        "flags": sorted(flags),
    }


def _rank(rule: dict[str, Any], caps: dict[str, Any]) -> tuple[int, int, int, str]:
    intents = (rule.get("scope") or {}).get("shot_intents") or []
    return (-_VALIDATION_RANK.get(rule.get("validation_scope"), -1),
            -_EVIDENCE_RANK.get(rule.get("evidence_level"), -1),
            0 if caps.get("shot_intent") in intents else 1,
            str(rule.get("rule_id")))


def _clause(rule: dict[str, Any], family: str) -> str | None:
    clause = ((rule.get("application") or {}).get("prompt_clause") or {})
    return clause.get("en" if family == "h3" else "zh")


def select_for_unit(unit: dict[str, Any], rules: list[dict[str, Any]], *, stage: str, engine_api_version: str,
                    max_rules: int = DEFAULT_MAX_RULES,
                    max_added_chars: int = DEFAULT_MAX_ADDED_CHARS) -> dict[str, Any]:
    """Decide, for one unit, which locked rules apply.  Pure: reads, never writes the unit."""
    caps = unit_capabilities(unit, stage=stage, engine_api_version=engine_api_version)
    family = model_family(unit.get("model"))
    decisions: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for rule in rules:
        base = {"rule_id": rule["rule_id"], "rule_version": rule["rule_version"],
                "bundle_digest": rule.get("_bundle_digest")}
        ok, reasons = c.scope_matches(rule.get("scope") or {}, caps)
        if not ok:
            decisions.append({**base, "state": "NOT_APPLICABLE", "reason": ";".join(reasons)})
            continue
        exceptions = rule.get("machine_exceptions") or {}
        hit = ([f"shot_intent={caps['shot_intent']}"] if caps["shot_intent"] in (exceptions.get("shot_intents") or [])
               else []) + [f"flag={f}" for f in exceptions.get("flags") or [] if f in caps["flags"]]
        if hit:
            decisions.append({**base, "state": "NOT_APPLICABLE",
                              "reason": "SCENE_INTENT_PRECEDENCE:" + ",".join(hit)})
            continue
        carrier = (rule.get("application") or {}).get("carrier", "CHECK_ONLY")
        if carrier == "CHECK_ONLY":
            candidates.append({**base, "carrier": carrier, "check_id": (rule.get("application") or {}).get("check_id"),
                               "rank": _rank(rule, caps), "rule": rule})
            continue
        text = _clause(rule, family)
        if not text:
            decisions.append({**base, "state": "DEFERRED",
                              "reason": f"CLAUSE_LANGUAGE_MISSING:{'en' if family == 'h3' else 'zh'}"})
            continue
        if CONTROL_LANGUAGE.search(text):
            decisions.append({**base, "state": "FAILED", "reason": "CONTROL_LANGUAGE_IN_CLAUSE_NOT_APPLIED"})
            continue
        candidates.append({**base, "carrier": carrier, "clause": text, "rank": _rank(rule, caps), "rule": rule})
    candidates.sort(key=lambda row: row["rank"])
    selected: list[dict[str, Any]] = []
    checks: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    added = 0
    chosen_ids: set[str] = set()
    for row in candidates:
        rule = row["rule"]
        clash = sorted(chosen_ids & set(rule.get("conflicts_with") or []))
        clean = {k: v for k, v in row.items() if k not in ("rule", "rank")}
        if clash:
            conflicts.append({"rule_id": row["rule_id"], "kept": clash, "severity": "NON_CRITICAL",
                              "resolution": "HIGHER_RANKED_RULE_KEPT"})
            decisions.append({**clean, "state": "NOT_APPLICABLE", "reason": f"CONFLICT_RESOLVED_BY_RANK:{clash}"})
            continue
        if row["carrier"] == "CHECK_ONLY":
            checks.append(clean)
            decisions.append({**clean, "state": "SELECTED", "reason": "ROUTED_TO_DETERMINISTIC_CHECK"})
            chosen_ids.add(row["rule_id"])
            continue
        if len(selected) >= max_rules:
            decisions.append({**clean, "state": "DEFERRED", "reason": f"UNIT_RULE_CAP:{max_rules}"})
            continue
        if added + len(row["clause"]) > max_added_chars:
            decisions.append({**clean, "state": "DEFERRED", "reason": f"UNIT_ADDED_TEXT_CAP:{max_added_chars}"})
            continue
        added += len(row["clause"])
        selected.append(clean)
        chosen_ids.add(row["rule_id"])
        decisions.append({**clean, "state": "SELECTED"})
    return {"unit_id": unit.get("unit_id"), "family": family, "capabilities": caps, "clauses": selected,
            "checks": checks, "conflicts": conflicts, "decisions": decisions, "added_chars": added,
            "limits": {"max_rules": max_rules, "max_added_chars": max_added_chars}}


# --------------------------------------------------------------------------- application
def dialogue_fingerprint(unit: dict[str, Any]) -> str:
    """Every dialogue-bearing value of the unit, so application can prove it never changed one."""
    def walk(value: Any, path: str, out: list[tuple[str, str]]) -> None:
        if isinstance(value, dict):
            for key, inner in value.items():
                k = str(key)
                if "dialogue" in k.lower() or k in ("spoken_text", "line", "lines"):
                    out.append((f"{path}.{k}", c.canonical_json(inner).decode("utf-8")))
                walk(inner, f"{path}.{k}", out)
        elif isinstance(value, list):
            for index, inner in enumerate(value):
                walk(inner, f"{path}[{index}]", out)
    rows: list[tuple[str, str]] = []
    walk(unit, "$", rows)
    return c.digest(sorted(rows))


def _append(text: str, clause: str, sep: str) -> str:
    text = str(text or "")
    if clause in text:  # idempotent on re-render
        return text
    return (text.rstrip("；;。. ") + sep + clause) if text else clause


def _english_holders(target: dict[str, Any]) -> list[dict[str, Any]]:
    """Every English contract the paid boundary could read for this task/unit (machine first)."""
    holders = []
    machine = target.get("machine_contract")
    if isinstance(machine, dict) and isinstance(machine.get("h3_provider_english_contract"), dict):
        holders.append(machine["h3_provider_english_contract"])
    if isinstance(target.get("h3_provider_english_contract"), dict):
        holders.append(target["h3_provider_english_contract"])
    return holders


def apply_to_unit(target: dict[str, Any], selection: dict[str, Any], *, in_place: bool = False) -> dict[str, Any]:
    """Write the selected clauses into the contract fields the family's renderer reads.

    ``target`` is a grouped unit (SD2 manifest unit) or a video task (H3 final render).
    Returns ``{"unit": amended, "applied": [...], "deferred": [...]}``.  Raises if any
    dialogue value would change (it cannot, by construction; this is the proof).
    """
    unit = target if in_place else copy.deepcopy(target)
    before = dialogue_fingerprint(unit)
    applied: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    family = selection["family"]
    for row in selection.get("clauses") or []:
        carrier, clause = row["carrier"], row["clause"]
        where: list[str] = []
        if family == "h3":
            holders = _english_holders(unit)
            for holder in holders:
                if carrier == "NEGATIVE_CONSTRAINT":
                    items = holder.setdefault("negative_constraints", [])
                    if clause not in items:
                        items.append(clause)
                    where.append("h3_provider_english_contract.negative_constraints")
                else:
                    beats = holder.get("beats") or []
                    if beats:
                        beats[0]["primary_action"] = _append(beats[0].get("primary_action"), clause, "; ")
                        where.append("h3_provider_english_contract.beats[0].primary_action")
        else:
            specs = _specs(unit)
            if specs:
                spec = specs[0]
                if carrier == "NEGATIVE_CONSTRAINT":
                    items = spec.setdefault("negative_prompts", [])
                    if clause not in items:
                        items.append(clause)
                    where.append("ordered_prompt_specs[0].negative_prompts")
                elif isinstance(spec.get("action"), dict) and spec["action"].get("primary_action"):
                    spec["action"]["primary_action"] = _append(spec["action"]["primary_action"], clause, "；")
                    where.append("ordered_prompt_specs[0].action.primary_action")
                elif isinstance(spec.get("performance"), dict) and spec["performance"].get("event_reaction"):
                    spec["performance"]["event_reaction"] = _append(spec["performance"]["event_reaction"], clause, "；")
                    where.append("ordered_prompt_specs[0].performance.event_reaction")
        if where:
            applied.append({**row, "carrier_fields": sorted(set(where))})
        else:
            deferred.append({**row, "state": "DEFERRED", "reason": "NO_CARRIER_FIELD_IN_CONTRACT"})
    if dialogue_fingerprint(unit) != before:
        raise c.ContractError(["ADVICE_APPLICATION_CHANGED_DIALOGUE"])
    return {"unit": unit, "applied": applied, "deferred": deferred}


# --------------------------------------------------------------------------- real adjacency (T19)
def unit_first_last_shot(unit: dict[str, Any]) -> tuple[str | None, str | None]:
    """A unit's real first and last editorial shot, from its own contract."""
    shots = [str(s) for s in unit.get("editorial_shot_ids") or [] if s]
    if not shots:
        internal = unit.get("internal_transition_contracts") or []
        if internal:
            shots = [str(internal[0].get("from_shot_id"))] + [str(t.get("to_shot_id")) for t in internal]
    return (shots[0], shots[-1]) if shots else (None, None)


def declared_adjacency(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Neighbour pairs ONLY from declared transition contracts (unit boundaries and internal shot
    boundaries).  List order and id numbering are never used: a unit with no declared boundary has
    no neighbour, rather than a fabricated one."""
    by_id = {str(u.get("unit_id")): u for u in units}
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for unit in units:
        uid = str(unit.get("unit_id"))
        for key in ("incoming_transition_contract", "outgoing_transition_contract", "transition_contract"):
            contract = unit.get(key)
            if not isinstance(contract, dict):
                continue
            src, dst = str(contract.get("from_unit_id") or ""), str(contract.get("to_unit_id") or "")
            if not src or not dst or uid not in (src, dst) or src not in by_id or dst not in by_id:
                continue
            _, src_last = unit_first_last_shot(by_id[src])
            dst_first, _ = unit_first_last_shot(by_id[dst])
            pairs[(src, dst)] = {"kind": "UNIT_BOUNDARY", "from_unit_id": src, "to_unit_id": dst,
                                 "from_shot_id": src_last, "to_shot_id": dst_first,
                                 "boundary_id": contract.get("boundary_id")}
        for contract in unit.get("internal_transition_contracts") or []:
            src, dst = str(contract.get("from_shot_id") or ""), str(contract.get("to_shot_id") or "")
            if src and dst:
                pairs[(src, dst)] = {"kind": "INTERNAL_SHOT_BOUNDARY", "unit_id": uid, "from_shot_id": src,
                                     "to_shot_id": dst, "boundary_id": contract.get("boundary_id")}
    return sorted(pairs.values(), key=lambda p: (p["kind"], p["from_shot_id"] or "", p["to_shot_id"] or ""))


# --------------------------------------------------------------------------- deterministic checks
def _check_camera_sequence(units: list[dict[str, Any]]) -> list[str]:
    from tools.grouped_camera_contract import validate_camera_sequence
    try:
        validate_camera_sequence(copy.deepcopy(units))
    except ValueError as exc:
        return [f"CAMERA_SEQUENCE:{exc}"]
    return []


def _check_action_restart(units: list[dict[str, Any]]) -> list[str]:
    """Across a DECLARED boundary, the next shot must not restart the action the previous one finished."""
    by_id = {str(u.get("unit_id")): u for u in units}
    findings = []
    for pair in declared_adjacency(units):
        if pair["kind"] != "UNIT_BOUNDARY":
            continue
        prev, nxt = by_id[pair["from_unit_id"]], by_id[pair["to_unit_id"]]
        prev_specs, next_specs = _specs(prev), _specs(nxt)
        if not prev_specs or not next_specs:
            continue
        done = (prev_specs[-1].get("action") or {}) if isinstance(prev_specs[-1].get("action"), dict) else {}
        start = (next_specs[0].get("action") or {}) if isinstance(next_specs[0].get("action"), dict) else {}
        restart = start.get("start_state") and done.get("start_state") == start.get("start_state") and \
            done.get("completion_state") != start.get("start_state")
        if restart and not (nxt.get("incoming_transition_contract") or {}).get("intentional_repeat"):
            findings.append(f"ACTION_RESTART_ACROSS_BOUNDARY:{pair['from_shot_id']}->{pair['to_shot_id']}")
    return findings


EPISODE_CHECKS: dict[str, Callable[[list[dict[str, Any]]], list[str]]] = {
    "CAMERA_SEQUENCE_NO_UNMOTIVATED_REPEAT": _check_camera_sequence,
    "NO_ACTION_RESTART_ACROSS_DECLARED_BOUNDARY": _check_action_restart,
}


def run_checks(check_ids: list[str], units: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Run named deterministic checks.  An unknown check id is reported, never silently passed."""
    out: dict[str, list[str]] = {}
    for check_id in sorted(set(check_ids)):
        fn = EPISODE_CHECKS.get(check_id)
        out[check_id] = fn(units) if fn else [f"CHECK_NOT_REGISTERED:{check_id}"]
    return out


def _check_visible_cast(unit: dict[str, Any], _text: str | None) -> list[str]:
    """Wrong person: every cast member a spec stages must be one the provider projection binds.

    A character who only SPEAKS off-screen (dialogue, not cast) is legitimate and not flagged."""
    projection = unit.get("provider_scope_projection") or {}
    bound = set(projection.get("visible_character_ids") or [])
    if not bound:
        return []
    findings = []
    for index, spec in enumerate(_specs(unit)):
        for row in spec.get("cast") or []:
            cid = str((row or {}).get("character_id") or "")
            if cid and cid not in bound:
                findings.append(f"CAST_NOT_BOUND_TO_PROJECTION:spec{index + 1}:{cid}")
    return findings


def _check_dialogue_in_prompt(unit: dict[str, Any], text: str | None) -> list[str]:
    """Missing dialogue: every authored line must appear in the compiled prompt exactly once."""
    if text is None:
        return ["COMPILED_TEXT_REQUIRED"]
    findings = []
    for index, spec in enumerate(_specs(unit)):
        raw = str(spec.get("dialogue") or "").strip()
        if not raw or spec.get("voice_only_not_in_video"):
            continue
        line = raw.partition("：")[2].strip() or raw
        count = text.count(line)
        if count != 1:
            findings.append(f"DIALOGUE_LINE_COUNT:spec{index + 1}:{count}")
    return findings


UNIT_CHECKS: dict[str, Callable[[dict[str, Any], str | None], list[str]]] = {
    "VISIBLE_CAST_BOUND_TO_PROJECTION": _check_visible_cast,
    "DIALOGUE_LINES_IN_COMPILED_PROMPT": _check_dialogue_in_prompt,
}


def blocked_units(units: list[dict[str, Any]], check_ids: list[str],
                  texts: dict[str, str] | None = None) -> dict[str, list[str]]:
    """Unit-scoped checks: a finding blocks only the unit it was found in, never the batch."""
    out: dict[str, list[str]] = {}
    for unit in units:
        uid = str(unit.get("unit_id"))
        findings: list[str] = []
        for check_id in sorted(set(check_ids)):
            fn = UNIT_CHECKS.get(check_id)
            findings.extend(fn(unit, (texts or {}).get(uid)) if fn else [f"CHECK_NOT_REGISTERED:{check_id}"])
        if findings:
            out[uid] = findings
    return out
