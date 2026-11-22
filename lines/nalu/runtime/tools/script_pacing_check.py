#!/usr/bin/env python3
"""SHORT_DRAMA_PACING_V1 -- free, deterministic script pacing check + bounded writer revision loop.

Line owner 2026-11-22: 「剧情推进太慢。Codex 需要对原著进行改写和删减；现在一集基本就是人物在念台词，一点都不刺激。」
Final reviews kept flagging weak opening hooks, static talking shots, endings without suspense and pacing 2-3/5,
and a typical dispatch adapted ONE chapter into a ~115-120 s episode (every source beat landed, nearly all of it as
dialogue).  The craft standard v1 (lines/nalu/standards/NALU_CRAFT_STANDARD_v1.md S-01..S-10) already says how a
vertical short drama should move; nothing measured the script against it before money was spent.

This module measures the authored generation contract (``qingshan.generation_contract.v3``; shot timeline =
cumulative ``target_seconds``) -- no model, no network, no paid call:

  beats_per_minute         plot turns (``pacing.beat_sheet`` rows + shots with ``prompt_spec.beat_role: PAYOFF``)
  first_conflict_at        min(``pacing.hook.at_seconds``, first turn)              target <= 3 s
  max_turn_gap_seconds     largest gap between 0, the turns and the cliffhanger    target <= 30 s
  dialogue_only_ratio      seconds of speaking shots without a physical action (MOMENTUM / CONTACT / POSSESSION /
                           INTEGRITY state change) / episode seconds                                    <= 0.60
  longest_line             sentences and spoken units of the longest line (<= 2 sentences, language cap)
  monologue runs           one speaker's back-to-back lines > 12 s without an interjection or action
  scenes_without_action    scenes where no shot changes a physical state (talk-only scenes)
  scene_plan               ``pacing.scene_plan`` {scene_id, objective, conflict, physical_action} per scene
  ending                   ``pacing.cliffhanger`` {shot_id, open_question} on the last beat of the episode
  adaptation               ``adaptation_plan`` {source_chapters, plot_events[], cut[]}: the episode's source
                           budget is plot events, not chapters (>= the required turn count)

Activation (do not break in-flight episodes): the check only asks for revisions when the contract declares
``"pacing_policy": "SHORT_DRAMA_PACING_V1"`` -- the dispatch template / contract §2.0 tell the writer to set it from
the next episode's dispatch on.  Every other contract gets the same metrics as an ADVISORY record (never blocks).
``NALU_SCRIPT_PACING=off`` turns the revision request off everywhere (metrics are still recorded).

Revision loop (``decide``): a failing check asks the writer (Codex) to revise the script; each distinct failing
contract sha is one round.  Rounds 1..MAX_REVISIONS return REVISE (S1 reports ``SCRIPT_PACING_REVISE:*`` and the
writer revises its own layers and reruns S1, free); after MAX_REVISIONS failed revisions the script is ADMITTED with
the remaining gaps recorded -- the loop always terminates, never needs a human and never stops the line.

Source coverage (``record_coverage`` / ``coverage``): the chapters each episode adapted are kept in
``$NALU_RUNTIME_ROOT/series/SOURCE_COVERAGE.json`` so the next dispatch continues where the series really is.

Stdlib only (codex_production and the final review load it too).  Language-agnostic (zh / en / ja / ko via
lang_profile) and genre-agnostic (the turn types are structural, not genre words).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import lang_profile as _lang  # noqa: E402

SCHEMA = "nalu.script_pacing_check.v1"
POLICY = "SHORT_DRAMA_PACING_V1"
ENV_SWITCH = "NALU_SCRIPT_PACING"
MAX_REVISIONS = 2
STALL_EVALUATIONS = 3
ROUNDS_SCHEMA = "nalu.script_pacing_rounds.v1"
COVERAGE_SCHEMA = "nalu.source_coverage.v1"

#: structural turn types (genre-agnostic): what flips power, information or danger in front of the viewer
TURN_TYPES = ("HUMILIATION_PAYBACK", "IDENTITY_REVEAL", "POWER_SHIFT", "SECRET_REVEALED", "THREAT_ESCALATION",
              "CONFRONTATION", "ROMANTIC_SPIKE", "REVERSAL", "DISCOVERY")
#: state changes a viewer SEES (POSTURE alone -- sitting up, turning a head -- is not an action beat)
PHYSICAL_DIMENSIONS = frozenset({"MOMENTUM", "CONTACT", "POSSESSION", "POSITION", "INTEGRITY"})
#: a SPEAKING shot carries action only when something is struck, grabbed, handed over, broken or rushed -- a step
#: closer (POSITION) or a turn of the head (POSTURE) while talking is still a talking head
SPEAKING_ACTION_DIMENSIONS = frozenset({"MOMENTUM", "CONTACT", "POSSESSION", "INTEGRITY"})

TARGETS = {
    "first_conflict_max_seconds": 3.0,
    "turn_every_seconds": 25.0,          # required turns = max(MIN_TURNS, floor(D / 25)) (craft S-02)
    "min_turns": 4,
    "max_turn_gap_seconds": 30.0,
    "dialogue_only_ratio_max": 0.60,
    "max_sentences_per_line": 2,
    "monologue_run_max_seconds": 12.0,
    "cliffhanger_window_seconds": 8.0,   # the cliffhanger shot starts inside the last 8 s (or is the last shot)
}

_SENTENCE_END = re.compile(r"[。！？!?…]+|\.(?:\s+|$)")
_OPEN_END = re.compile(r"[？?…—―-]\s*[」』\"'”’]?\s*$")


# --------------------------------------------------------------------------- helpers
def _clean(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def enabled(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return _clean(env.get(ENV_SWITCH)).lower() not in ("off", "0", "false", "no")


def policy_active(contract: dict[str, Any]) -> bool:
    return _clean((contract or {}).get("pacing_policy")).upper() == POLICY


def contract_language(contract: dict[str, Any], language: str | None = None) -> str:
    return (_lang.language_code(language) or _lang.language_code((contract or {}).get("dialogue_language"))
            or _lang.DEFAULT_LANGUAGE)


def _rows(dialogue: Any) -> list[str]:
    if isinstance(dialogue, (list, tuple)):
        rows = [str(x.get("text") if isinstance(x, dict) else x) for x in dialogue]
    else:
        rows = str(dialogue or "").splitlines()
    return [r.strip() for r in rows if str(r).strip()]


def split_line(row: str, language: str) -> tuple[str, str]:
    """``Speaker：words`` -> (speaker, words); a label is at most 24 characters (romanised names included)."""
    for sep in ("：", ":"):
        at = row.find(sep)
        if 0 <= at < 24:
            return row[:at].strip(), row[at + 1:].strip()
    return "", row.strip()


def sentence_count(words: str) -> int:
    parts = [p for p in _SENTENCE_END.split(words) if re.search(r"\w", p)]
    return max(1, len(parts)) if words.strip() else 0


def line_unit_cap(language: str) -> int:
    """Two craft-standard lines (S-08) of the language: zh 28 chars / en 20 words / ja 44 chars / ko 36 syllables."""
    return 2 * int(_lang.profile(language).line_units[1])


# --------------------------------------------------------------------------- timeline
def timeline(contract: dict[str, Any], language: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor = 0.0
    for index, shot in enumerate((contract or {}).get("shots") or []):
        if not isinstance(shot, dict):
            continue
        seconds = max(_num(shot.get("target_seconds")) or 0.0, 0.0)
        spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
        role = spec.get("role_semantic_disambiguation") if isinstance(spec.get("role_semantic_disambiguation"),
                                                                       dict) else {}
        lines = []
        for row in _rows(spec.get("dialogue")):
            speaker, words = split_line(row, language)
            units = _lang.speech_units(words, language)
            if units:
                lines.append({"speaker": speaker, "units": units, "sentences": sentence_count(words),
                              "open_end": bool(_OPEN_END.search(words))})
        dims = {_clean(d).upper() for d in shot.get("state_delta_dimensions") or []}
        speaker = _clean(role.get("dialogue_speaker_id")) or (lines[0]["speaker"] if lines else "")
        out.append({"index": index, "shot_id": _clean(shot.get("shot_id")) or f"SHOT-{index + 1}",
                    "scene_id": _clean(shot.get("scene_id")) or "SCENE", "start": round(cursor, 3),
                    "end": round(cursor + seconds, 3), "seconds": seconds, "lines": lines,
                    "speaker": speaker if lines else "",
                    "physical": bool(dims & PHYSICAL_DIMENSIONS),
                    "speaking_action": bool(dims & SPEAKING_ACTION_DIMENSIONS),
                    "beat_role": _clean(spec.get("beat_role")).upper()})
        cursor += seconds
    return out


def _at(ref: Any, rows: list[dict[str, Any]]) -> float | None:
    """Seconds of a beat reference: ``shot_id`` (start of that shot) or ``at_seconds``."""
    if isinstance(ref, dict):
        sid = _clean(ref.get("shot_id") or ref.get("line_or_shot_id"))
        if sid:
            hit = next((r for r in rows if r["shot_id"] == sid), None)
            if hit is not None:
                return hit["start"]
        return _num(ref.get("at_seconds"))
    return None


# --------------------------------------------------------------------------- measure
def measure(contract: dict[str, Any], language: str | None = None) -> dict[str, Any]:
    """Every pacing number of the authored script.  Pure, never raises on odd input (missing parts -> None)."""
    contract = contract if isinstance(contract, dict) else {}
    lang = contract_language(contract, language)
    rows = timeline(contract, lang)
    duration = round(sum(r["seconds"] for r in rows), 3)
    pacing = contract.get("pacing") if isinstance(contract.get("pacing"), dict) else {}

    turns: list[dict[str, Any]] = []
    unknown_types: list[str] = []
    for entry in pacing.get("beat_sheet") or []:
        if not isinstance(entry, dict):
            continue
        at = _at(entry, rows)
        kind = _clean(entry.get("type")).upper()
        if at is None:
            continue
        if kind not in TURN_TYPES:
            unknown_types.append(kind or "EMPTY")
            continue
        turns.append({"at": round(at, 3), "type": kind, "shot_id": _clean(entry.get("shot_id")) or None,
                      "source": "beat_sheet"})
    declared_shots = {t["shot_id"] for t in turns if t["shot_id"]}
    for r in rows:
        if r["beat_role"] == "PAYOFF" and r["shot_id"] not in declared_shots:
            turns.append({"at": r["start"], "type": "PAYOFF", "shot_id": r["shot_id"], "source": "beat_role"})
    turns.sort(key=lambda t: t["at"])

    hook = pacing.get("hook") if isinstance(pacing.get("hook"), dict) else {}
    hook_at = _num(hook.get("at_seconds"))
    first_turn = turns[0]["at"] if turns else None
    first_conflict = min([v for v in (hook_at, first_turn) if v is not None], default=None)

    cliff = pacing.get("cliffhanger") if isinstance(pacing.get("cliffhanger"), dict) else {}
    cliff_at = _at(cliff, rows) if cliff else None
    last = rows[-1] if rows else None
    cliff_shot = next((r for r in rows if r["shot_id"] == _clean(cliff.get("shot_id"))), None) if cliff else None
    window = TARGETS["cliffhanger_window_seconds"]
    in_window = bool(cliff_shot is not None and (cliff_shot is last or cliff_shot["start"] >= duration - window))
    question = _clean(cliff.get("open_question"))
    last_line = next((ln for r in reversed(rows) for ln in reversed(r["lines"])), None)
    ending = {"declared": bool(cliff), "shot_id": cliff_shot["shot_id"] if cliff_shot else None,
              "at": cliff_at, "in_final_window": in_window, "open_question": bool(question),
              "last_line_open": bool(last_line and last_line["open_end"])}
    ending["unresolved"] = bool((in_window and question) or (not cliff and ending["last_line_open"]))
    ending["basis"] = "declared" if cliff else ("last_line" if ending["last_line_open"] else "none")

    points = [0.0] + [t["at"] for t in turns] + [cliff_at if (cliff_at is not None and in_window) else duration]
    points = sorted(p for p in points if p is not None)
    gaps = [round(b - a, 3) for a, b in zip(points, points[1:])]
    max_gap = max(gaps, default=duration)
    gap_at = None
    if gaps:
        i = gaps.index(max_gap)
        gap_at = [round(points[i], 3), round(points[i + 1], 3)]

    speaking = [r for r in rows if r["lines"]]
    talk_only = [r for r in speaking if not r["speaking_action"]]
    dialogue_only_seconds = round(sum(r["seconds"] for r in talk_only), 3)
    speech_seconds = round(sum(min(r["seconds"], sum(ln["units"] for ln in r["lines"]) /
                                   _lang.profile(lang).rate) for r in speaking), 3)

    cap = line_unit_cap(lang)
    longest = None
    long_lines: list[dict[str, Any]] = []
    for r in rows:
        for ln in r["lines"]:
            if longest is None or ln["units"] > longest["units"]:
                longest = {"shot_id": r["shot_id"], "units": ln["units"], "sentences": ln["sentences"]}
            if ln["sentences"] > TARGETS["max_sentences_per_line"] or ln["units"] > cap:
                long_lines.append({"shot_id": r["shot_id"], "units": ln["units"], "sentences": ln["sentences"]})

    runs: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    for r in rows:
        if r["lines"] and r["speaker"] and not r["speaking_action"] and cur and cur["speaker"] == r["speaker"]:
            cur["seconds"] = round(cur["seconds"] + r["seconds"], 3)
            cur["shots"].append(r["shot_id"])
            continue
        if cur:
            runs.append(cur)
        cur = ({"speaker": r["speaker"], "start": r["start"], "seconds": r["seconds"],
                "shots": [r["shot_id"]]} if r["lines"] and r["speaker"] and not r["speaking_action"] else None)
    if cur:
        runs.append(cur)
    monologues = [{"start": x["start"], "seconds": x["seconds"], "shots": x["shots"]} for x in runs
                  if x["seconds"] > TARGETS["monologue_run_max_seconds"]]

    scenes: dict[str, dict[str, Any]] = {}
    for r in rows:
        s = scenes.setdefault(r["scene_id"], {"scene_id": r["scene_id"], "start": r["start"], "seconds": 0.0,
                                              "physical": False, "shots": 0})
        s["seconds"] = round(s["seconds"] + r["seconds"], 3)
        s["physical"] = s["physical"] or r["physical"]
        s["shots"] += 1
    plan_rows = {(_clean(p.get("scene_id"))): p for p in pacing.get("scene_plan") or [] if isinstance(p, dict)}
    plan_missing = []
    for sid in scenes:
        p = plan_rows.get(sid) or {}
        lacking = [k for k in ("objective", "conflict", "physical_action") if not _clean(p.get(k))]
        if lacking:
            plan_missing.append({"scene_id": sid, "missing": lacking})

    adaptation = contract.get("adaptation_plan") if isinstance(contract.get("adaptation_plan"), dict) else {}
    chapters = sorted({int(c) for c in adaptation.get("source_chapters") or []
                       if _num(c) is not None and float(c) >= 0})
    events = [e for e in adaptation.get("plot_events") or [] if (isinstance(e, dict) and _clean(
        e.get("event") or e.get("summary"))) or (isinstance(e, str) and e.strip())]

    required = max(TARGETS["min_turns"], int(duration // TARGETS["turn_every_seconds"])) if duration else \
        TARGETS["min_turns"]
    return {
        "language": lang, "duration_seconds": duration, "shot_count": len(rows), "scene_count": len(scenes),
        "turns": turns, "turn_count": len(turns), "required_turns": required,
        "beats_per_minute": round(len(turns) * 60.0 / duration, 2) if duration else 0.0,
        "unknown_turn_types": unknown_types,
        "hook_at_seconds": hook_at, "first_conflict_at": first_conflict,
        "max_turn_gap_seconds": round(max_gap, 3), "max_turn_gap_window": gap_at,
        "dialogue_only_seconds": dialogue_only_seconds,
        "dialogue_only_ratio": round(dialogue_only_seconds / duration, 3) if duration else 0.0,
        "speech_share_ref": round(speech_seconds / duration, 3) if duration else 0.0,
        "longest_line": longest, "line_unit_cap": cap, "long_lines": long_lines[:12],
        "long_line_count": len(long_lines), "monologue_runs": monologues[:8],
        "scenes_without_action": [s["scene_id"] for s in scenes.values() if not s["physical"]],
        "scene_plan_missing": plan_missing,
        "ending": ending,
        "adaptation": {"declared": bool(adaptation), "source_chapters": chapters,
                       "source_chapter_count": len(chapters), "plot_event_count": len(events),
                       "cut_count": len([c for c in adaptation.get("cut") or [] if c])},
    }


# --------------------------------------------------------------------------- evaluate
#: failure code -> one-line fix the writer can act on (no story text; language-agnostic)
FIXES = {
    "FIRST_CONFLICT_LATE": "open mid-conflict: the first shot is already the insult / reveal / danger (<= 3 s)",
    "TOO_FEW_TURNS": "pull more plot events into the episode (cut filler, merge scenes, take the next chapters)",
    "TURN_GAP_TOO_LONG": "add an escalation / reversal / reveal inside the longest gap (one turn per 20-30 s)",
    "DIALOGUE_ONLY_TOO_HIGH": "turn exposition lines into visible action and reaction shots",
    "LINE_TOO_LONG": "at most 2 short sentences per line; split or cut the rest",
    "BACK_TO_BACK_MONOLOGUE": "break the run with an interjection, a physical action or a reaction",
    "SCENE_TALK_ONLY": "give the scene a physical action that changes something (grab, shove, hand over, leave)",
    "SCENE_PLAN_MISSING": "write pacing.scene_plan: objective, conflict and physical action per scene",
    "ENDING_NOT_OPEN": "end on the cliffhanger itself (pacing.cliffhanger with an open question, last shot)",
    "ADAPTATION_PLAN_MISSING": "write adaptation_plan: source_chapters, plot_events, cut",
    "ADAPTATION_TOO_THIN": "budget the episode by plot events: cover at least the required turns from the source",
}


def evaluate(contract: dict[str, Any], language: str | None = None,
             environ: dict[str, str] | None = None) -> dict[str, Any]:
    """{status PASS|FAIL, active, failures [codes], warnings, fixes, metrics}.  ``active`` = the contract opted in
    (``pacing_policy``) and the switch is on; an inactive report is ADVISORY whatever its numbers."""
    m = measure(contract, language)
    t = TARGETS
    failures: list[str] = []
    warnings: list[str] = [f"TURN_TYPE_UNKNOWN:{k}" for k in m["unknown_turn_types"][:4]]
    fc = m["first_conflict_at"]
    if fc is None or fc > t["first_conflict_max_seconds"]:
        failures.append(f"FIRST_CONFLICT_LATE:{'none' if fc is None else f'{fc:.1f}s'}")
    if m["turn_count"] < m["required_turns"]:
        failures.append(f"TOO_FEW_TURNS:{m['turn_count']}<{m['required_turns']}")
    if m["max_turn_gap_seconds"] > t["max_turn_gap_seconds"]:
        w = m["max_turn_gap_window"] or [0, m["duration_seconds"]]
        failures.append(f"TURN_GAP_TOO_LONG:{m['max_turn_gap_seconds']:.1f}s@{w[0]:.0f}-{w[1]:.0f}")
    if m["dialogue_only_ratio"] > t["dialogue_only_ratio_max"]:
        failures.append(f"DIALOGUE_ONLY_TOO_HIGH:{m['dialogue_only_ratio']:.2f}")
    if m["long_line_count"]:
        failures.append(f"LINE_TOO_LONG:{m['long_line_count']}")
    if m["monologue_runs"]:
        failures.append(f"BACK_TO_BACK_MONOLOGUE:{len(m['monologue_runs'])}")
    for sid in m["scenes_without_action"][:6]:
        failures.append(f"SCENE_TALK_ONLY:{sid}")
    if m["scene_plan_missing"]:
        failures.append(f"SCENE_PLAN_MISSING:{len(m['scene_plan_missing'])}")
    if not m["ending"]["unresolved"]:
        failures.append(f"ENDING_NOT_OPEN:{m['ending']['basis']}")
    ad = m["adaptation"]
    if not ad["declared"]:
        failures.append("ADAPTATION_PLAN_MISSING")
    elif ad["plot_event_count"] < m["required_turns"]:
        failures.append(f"ADAPTATION_TOO_THIN:{ad['plot_event_count']}<{m['required_turns']}")
    if ad["declared"] and ad["source_chapter_count"] <= 1 and ad["plot_event_count"] < m["required_turns"] + 2:
        warnings.append("SINGLE_CHAPTER_EPISODE")
    active = policy_active(contract) and enabled(environ)
    codes = sorted({c.split(":", 1)[0] for c in failures})
    return {"schema": SCHEMA, "policy": POLICY, "active": active,
            "authority": "WRITER_REVISION_LOOP" if active else "ADVISORY_NOT_A_GATE",
            "status": "PASS" if not failures else "FAIL", "failures": failures, "warnings": warnings,
            "fixes": {c: FIXES[c] for c in codes if c in FIXES}, "targets": dict(TARGETS), "metrics": m}


# --------------------------------------------------------------------------- revision loop
def contract_sha(contract: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(contract, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def decide(report: dict[str, Any], sha: str, rounds_path: Path, *, max_revisions: int = MAX_REVISIONS,
           record: bool = True) -> dict[str, Any]:
    """One S1 decision of the revision loop.

    PASS                     the check passed
    ADVISORY                 the contract did not opt in (or the switch is off): metrics only
    REVISE                   failing, revision round n of ``max_revisions``: the writer revises and reruns S1
    ADMITTED_AFTER_REVISIONS failing after ``max_revisions`` revisions: the script goes on with the gaps recorded

    Each distinct failing contract sha is one round; re-running S1 on the same bytes never uses up a round, but
    the same failing bytes evaluated more than STALL_EVALUATIONS times are admitted (the writer is not revising).
    ``record=False`` (S1 blocked by another gate) reports without counting a round."""
    state = _read(rounds_path) if rounds_path else {}
    rows = [r for r in state.get("rounds") or [] if isinstance(r, dict)]
    failing = [r["contract_sha256"] for r in rows if r.get("status") == "FAIL" and r.get("contract_sha256")]
    same = next((r for r in rows if r.get("contract_sha256") == sha), None)
    evaluations = int((same or {}).get("evaluations") or (1 if same else 0)) + 1
    reason = None
    if not report.get("active"):
        decision = "ADVISORY"
    elif report.get("status") == "PASS":
        decision = "PASS"
    else:
        n = len(dict.fromkeys(failing + [sha]))
        decision = "REVISE" if n <= max_revisions else "ADMITTED_AFTER_REVISIONS"
        reason = "REVISIONS_EXHAUSTED" if decision != "REVISE" else None
        if decision == "REVISE" and evaluations > STALL_EVALUATIONS:
            # the same failing bytes re-run again and again: the writer is not revising -- never stall the line
            decision, reason = "ADMITTED_AFTER_REVISIONS", "SAME_SCRIPT_RERUN"
    if record and rounds_path and report.get("active"):
        if same is None:
            rows.append({"contract_sha256": sha, "status": report.get("status"),
                         "failures": list(report.get("failures") or [])[:12], "evaluations": 1,
                         "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        else:
            same["evaluations"] = evaluations
        _write(rounds_path, {"schema": ROUNDS_SCHEMA, "max_revisions": max_revisions, "rounds": rows})
    failing_now = len(dict.fromkeys(failing + ([sha] if report.get("status") == "FAIL" else [])))
    return {"decision": decision, "revision_round": min(failing_now, max_revisions + 1),
            "max_revisions": max_revisions, "blocks": decision == "REVISE",
            **({"reason": reason} if reason else {})}


def blocker_codes(report: dict[str, Any], decision: dict[str, Any]) -> list[str]:
    if not decision.get("blocks"):
        return []
    head = f"SCRIPT_PACING_REVISE:round={decision['revision_round']}/{decision['max_revisions']}"
    return [head] + [f"SCRIPT_PACING_REVISE:{code}" for code in (report.get("failures") or [])[:8]]


def summary(report: dict[str, Any], decision: dict[str, Any] | None = None) -> dict[str, Any]:
    """The compact episode-record row (pipeline state S1 details, final review context)."""
    m = report.get("metrics") or {}
    return {"policy": report.get("policy"), "active": report.get("active"), "status": report.get("status"),
            **({"decision": decision.get("decision"), "revision_round": decision.get("revision_round")}
               if decision else {}),
            "failures": list(report.get("failures") or [])[:12],
            "metrics": {k: m.get(k) for k in (
                "duration_seconds", "turn_count", "required_turns", "beats_per_minute", "first_conflict_at",
                "max_turn_gap_seconds", "max_turn_gap_window", "dialogue_only_ratio", "speech_share_ref",
                "longest_line", "long_line_count", "scenes_without_action", "scene_count")},
            "ending_unresolved": (m.get("ending") or {}).get("unresolved"),
            "turns": [{"at": t.get("at"), "type": t.get("type")} for t in m.get("turns") or []][:12],
            "adaptation": m.get("adaptation")}


# --------------------------------------------------------------------------- source coverage
def coverage_path(runtime_root: Path) -> Path:
    return Path(runtime_root) / "series" / "SOURCE_COVERAGE.json"


def record_coverage(runtime_root: Path, episode: str, contract: dict[str, Any]) -> dict[str, Any]:
    """Remember which source chapters / how many plot events ``episode`` adapted (from ``adaptation_plan``).
    Re-recording an episode replaces its row.  Never raises; {} when the contract declares no plan."""
    try:
        plan = contract.get("adaptation_plan") if isinstance(contract.get("adaptation_plan"), dict) else {}
        if not plan:
            return {}
        m = measure(contract)["adaptation"]
        path = coverage_path(runtime_root)
        data = _read(path) or {"schema": COVERAGE_SCHEMA, "episodes": {}}
        data.setdefault("episodes", {})[episode] = {
            "source_chapters": m["source_chapters"], "plot_event_count": m["plot_event_count"],
            "cut_count": m["cut_count"], "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        data["schema"] = COVERAGE_SCHEMA
        _write(path, data)
        return coverage(runtime_root)
    except Exception:  # noqa: BLE001 -- bookkeeping must never fail a stage
        return {}


def coverage(runtime_root: Path) -> dict[str, Any]:
    """{episodes, last_chapter, next_chapter, chapters_covered, gaps}: where the series is in the book."""
    data = _read(coverage_path(runtime_root))
    episodes = data.get("episodes") or {}
    covered = sorted({int(c) for row in episodes.values() if isinstance(row, dict)
                      for c in row.get("source_chapters") or [] if _num(c) is not None})
    last = covered[-1] if covered else None
    gaps = [c for c in range(covered[0], last + 1) if c not in covered] if covered else []
    return {"schema": COVERAGE_SCHEMA, "episodes": episodes, "chapters_covered": covered, "last_chapter": last,
            "next_chapter": (last + 1) if last is not None else None, "skipped_chapters": gaps}


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="measure a generation contract (free; exit 0 always unless --strict)")
    c.add_argument("--contract", required=True)
    c.add_argument("--language")
    c.add_argument("--out")
    c.add_argument("--strict", action="store_true", help="exit 3 when the check fails")
    v = sub.add_parser("coverage", help="source chapters covered so far and where the next episode starts")
    v.add_argument("--runtime-root", default=os.environ.get("NALU_RUNTIME_ROOT") or str(Path.home() / "nalu_runtime"))
    args = ap.parse_args(argv)
    if args.cmd == "coverage":
        print(json.dumps(coverage(Path(args.runtime_root).expanduser()), ensure_ascii=False, indent=1))
        return 0
    contract = _read(Path(args.contract))
    report = evaluate(contract, args.language)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        _write(Path(args.out), report)
    print(json.dumps({"status": report["status"], "active": report["active"], "failures": report["failures"],
                      "fixes": report["fixes"]}, ensure_ascii=False) if args.out else text)
    return 3 if (args.strict and report["status"] == "FAIL") else 0


if __name__ == "__main__":
    raise SystemExit(main())
