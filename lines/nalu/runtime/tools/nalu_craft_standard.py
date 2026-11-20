#!/usr/bin/env python3
"""NALU_CRAFT_STANDARD_v1 in the engine (line owner 2026-11-17, option A: no added per-episode cost, shot count
unchanged).  The standard scores and guides; it never becomes a gate.

The standard itself is ``lines/nalu/standards/NALU_CRAFT_STANDARD_v1.md`` with its machine-readable item list
``NALU_CRAFT_STANDARD_v1.items.json`` (id, layer, CORE/NICE, zh + en principle, reviewer check, Codex line, the
compressed zh text injected into Codex's start prompt).  Both stay in the engine repository; nothing here uploads
them anywhere.

This module is stdlib only (``codex_production`` loads it by path):

``codex_section``      the 「NALU 成片标准 v1」 section of Codex's episode start prompt (<= 1500 chars), separate
                       from the collective 「本集导演经验」 section (PR #248, its own 1500 cap).
``measure_pacing``     pacing numbers computed locally from the final cut's measured shot windows and ASR windows,
                       handed to the final reviewer so it does not guess them.
``reviewer_request``   the ``craft_standard_request`` block of the final-audience review request.
``parse_block``        lenient parse of the reviewer's optional ``craft_standard`` answer block: whatever is
                       malformed is dropped with a note; a missing or broken block never invalidates the review.
``gap_events``         the reviewer's top gaps as privacy-scrubbed knowledge events
                       (``CRAFT_STD_GAP|<item id>``; item id, numbers and a short scrubbed fix line only).
"""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable

STANDARD_VERSION = "NALU_CRAFT_STANDARD_v1"
STANDARD_MD = "lines/nalu/standards/NALU_CRAFT_STANDARD_v1.md"
ITEMS_JSON = "lines/nalu/standards/NALU_CRAFT_STANDARD_v1.items.json"
BLOCK_SCHEMA = "nalu.craft_standard_review.v1"
ENV_SWITCH = "NALU_CRAFT_STANDARD"
MAX_CODEX_SECTION_CHARS = 1500
SECTION_TITLE = "## NALU 成片标准 v1（写作自查，独立于「本集导演经验」）"
FAILURE_TYPE = "CRAFT_STD_GAP"
VERDICTS = ("PASS", "GAP", "NA")
FIX_OWNERS = ("writer", "engine", "S7")
OWNER_STAGE = {"writer": "SCRIPT_AUTHORING", "engine": "STORYBOARD_AUTHORING", "S7": "STORYBOARD_AUTHORING"}
LAYER_KEYS = ("pacing_structure", "clarity_grammar")
MAX_TOP_GAPS = 3
FIX_MAX_CHARS = 80
TEXT_MAX_CHARS = 300
SILENT_SPEECH_OVERLAP_S = 0.2
SILENT_SHOT_MAX_S = 4.0
PAYOFF_EVERY_S = 25.0
_ID_RE = re.compile(r"^\s*([SCsc])\s*[-_]?\s*0?(\d{1,2})\s*$")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")

#: the final review's must-check defects (nalu_qa_defect_checklist, line owner 2026-11-19) -> the craft item a top
#: gap cites when one of them is also among the cut's worst retention gaps
QA_DEFECT_CRAFT_ITEMS = {"QA-BURNED-TEXT": "C-04", "QA-DIALOGUE-TAIL-CUT": "C-08", "QA-OVERSIZED-MASK": "C-13",
                         "QA-LOOKALIKE-CAST": "C-12", "QA-SUBTITLE-WRAP": "S-08", "QA-BGM-DISCONTINUOUS": "C-16",
                         "QA-SKIN-SHEEN-DRIFT": "C-12"}

#: what the author is told about the optional beat_role field (S7 cuts reactions to their v1 length from it)
BEAT_ROLE_LINE = ("爽点表里的镜头填 `prompt_spec.beat_role`：SETUP 铺垫 | PAYOFF 爽点 | REACTION 爽点后的反应；"
                  "S7 把无台词反应镜按动作峰值剪到 1.5–2.5 s，其它无台词镜 2–3 s。")


def engine_root() -> Path:
    env = os.environ.get("NALU_ENGINE_ROOT")
    if env and (Path(env).expanduser() / ITEMS_JSON).is_file():
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[4]


def enabled(environ: dict[str, str] | None = None) -> bool:
    """``NALU_CRAFT_STANDARD=off`` removes the Codex section and the reviewer request block (default on)."""
    env = os.environ if environ is None else environ
    return str(env.get(ENV_SWITCH) or "").strip().lower() not in ("off", "0", "false", "no")


def load_items(engine: Path | None = None) -> dict[str, Any]:
    """The machine-readable standard, or {} when it is missing or unreadable.  Never raises."""
    try:
        data = json.loads((Path(engine or engine_root()) / ITEMS_JSON).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) and isinstance(data.get("items"), list) else {}


def item_index(standard: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("id")): row for row in standard.get("items") or [] if isinstance(row, dict) and row.get("id")}


def normalise_item_id(value: Any) -> str | None:
    """``"S-02"`` / ``"s2"`` / ``"S02"`` -> ``"S-02"``; anything else -> None."""
    m = _ID_RE.match(str(value or ""))
    return f"{m.group(1).upper()}-{int(m.group(2)):02d}" if m else None


# --------------------------------------------------------------------------- Codex start prompt
def _anime_note() -> str:
    """render_style.CODEX_NOTE_ZH, loaded by path (this module is loaded by path itself, stdlib only)."""
    import importlib.util  # noqa: PLC0415
    try:
        spec = importlib.util.spec_from_file_location("nalu_render_style_for_craft",
                                                      Path(__file__).resolve().parent / "render_style.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return str(module.CODEX_NOTE_ZH)
    except Exception:  # noqa: BLE001 -- the start prompt must never fail on an advisory section
        return ""


def codex_section(engine: Path | None = None, *, limit: int = MAX_CODEX_SECTION_CHARS,
                  render_style: str | None = None) -> str:
    """The standard's own section of Codex's start prompt (<= ``limit`` chars) or '' when off / missing.

    The compressed zh standard plus where to look things up: the full text is grepped by item id, never read whole
    (PR #250: no large files re-read).  render_style=anime appends the short anime note (anime acting conventions,
    one consistent character design) inside the same cap; live-action is unchanged."""
    if str(render_style or "").strip().lower() == "anime":
        note = _anime_note()
        if note:
            standard = _codex_section(engine, limit=limit - len(note) - 2)
            return f"{standard}\n\n{note}" if standard else note
    return _codex_section(engine, limit=limit)


def _codex_section(engine: Path | None = None, *, limit: int = MAX_CODEX_SECTION_CHARS) -> str:
    if not enabled():
        return ""
    standard = load_items(engine)
    body = str(standard.get("codex_compressed_zh") or "").strip()
    if not body:
        return ""
    head = f"{SECTION_TITLE}\n全文 `{STANDARD_MD}` 不整份读，按条目号取：`rg -n -A8 '^### S-03' <全文>`。"
    tail = BEAT_ROLE_LINE
    room = limit - len(head) - len(tail) - 4
    if room < 200:
        return ""
    if len(body) > room:
        body = body[: room - 1].rstrip() + "…"
    return f"{head}\n\n{body}\n\n{tail}"[:limit]


# --------------------------------------------------------------------------- local pacing metrics
def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        try:
            value = float(str(value).strip())
        except (TypeError, ValueError):
            return None
    value = float(value)
    return value if math.isfinite(value) else None


def asr_windows(payload: Any) -> list[tuple[float, float]]:
    """[(start, end)] from the S7 final-cut ASR (a list of line windows, or {segments|windows: [...]})."""
    rows = payload if isinstance(payload, list) else (
        (payload or {}).get("segments") or (payload or {}).get("windows") or [] if isinstance(payload, dict) else [])
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        a, b = _num(row.get("start")), _num(row.get("end"))
        if a is not None and b is not None and b > a >= 0:
            out.append((a, b))
    return sorted(out)


def measure_pacing(shots: list[dict[str, Any]], asr: Any, duration: float) -> dict[str, Any]:
    """Pacing numbers of the delivered cut, measured, not judged: shot lengths from the measured shot windows
    (scene cuts of the decoded final MP4; title and end cards are shots too), speech from the final-cut ASR."""
    windows = asr_windows(asr)
    rows = []
    for shot in shots or []:
        a, b = _num(shot.get("start_seconds")), _num(shot.get("end_seconds"))
        if a is None or b is None or b <= a:
            continue
        speech = sum(max(0.0, min(b, w1) - max(a, w0)) for w0, w1 in windows)
        rows.append({"shot_index": shot.get("shot_index"), "at": round(a, 3), "seconds": round(b - a, 3),
                     "silent": speech < SILENT_SPEECH_OVERLAP_S})
    duration = float(duration or 0.0)
    out: dict[str, Any] = {"basis": "measured shot windows of the decoded final MP4 + final-cut ASR windows",
                           "duration_seconds": round(duration, 3), "shot_count": len(rows),
                           "payoff_required": int(duration // PAYOFF_EVERY_S) if duration > 0 else 0}
    if rows:
        lengths = sorted(r["seconds"] for r in rows)
        out["mean_shot_seconds"] = round(sum(lengths) / len(lengths), 3)
        out["median_shot_seconds"] = lengths[len(lengths) // 2]
        longest = max(rows, key=lambda r: r["seconds"])
        out["longest_shot"] = {k: longest[k] for k in ("shot_index", "seconds", "at")}
        silent = [r for r in rows if r["silent"]]
        if silent:
            hold = max(silent, key=lambda r: r["seconds"])
            out["longest_silent_shot"] = {k: hold[k] for k in ("shot_index", "seconds", "at")}
        over = [{k: r[k] for k in ("shot_index", "seconds", "at")} for r in silent if r["seconds"] > SILENT_SHOT_MAX_S]
        out["silent_shots_over_4s"] = over[:12]
        out["silent_shots_over_4s_count"] = len(over)
    if windows:
        out["first_speech_at"] = round(windows[0][0], 3)
        out["last_speech_end"] = round(windows[-1][1], 3)
        if duration > 0:
            out["dialogue_share_ref"] = round(min(1.0, sum(b - a for a, b in windows) / duration), 3)
    return out


def reviewer_request(measured: dict[str, Any], engine: Path | None = None) -> dict[str, Any]:
    """The ``craft_standard_request`` block of the final-audience request ({} when off / missing)."""
    if not enabled():
        return {}
    standard = load_items(engine)
    if not standard:
        return {}
    items = [{"id": row["id"], "severity": row.get("severity"), "layer": row.get("layer"),
              "title": row.get("title_zh"), "check": row.get("reviewer_check_zh"),
              **({"applies_from_episode": row["applies_from_episode"]}
                 if int(row.get("applies_from_episode") or 1) > 1 else {})}
             for row in standard.get("items") or [] if isinstance(row, dict)]
    return {
        "standard_version": STANDARD_VERSION,
        "standard_md": STANDARD_MD,
        "authority": "OPTIONAL_ADVISORY_NOT_A_GATE: a missing or malformed block never changes the review",
        "instruction": (
            "In the same viewing passes, fill the optional answer block craft_standard: layer_scores "
            "(pacing_structure, clarity_grammar: score 1-5 holistic + core_pass 'n/m' + reason), items {item id: "
            "{verdict PASS|GAP|NA, evidence with numbers}} for every CORE item, top_gaps (at most 3 CORE GAPs ranked "
            "by harm to retention; pacing items first unless a clarity gap makes the story unreadable; each with "
            "item_id, at_seconds or window [a, b] or shot_index, metric with numbers, fix, fix_owner writer|engine|S7) "
            "and pacing_metrics (first_conflict_at, payoffs [{t, type, setup_t, reaction_shot}], cliffhanger_at, "
            "prev_payoff_at).  A payoff is a visible power/information flip of one of payoff_types.  The numbers in "
            "measured_pacing were measured on this cut: use them, do not re-estimate them.  Write fixes as craft "
            "directions (no dialogue quotes, no character names)."),
        "qa_defect_crosswalk": {
            "note": "a must-check defect (qa_defect_checklist_request) that is also a top retention gap is cited "
                    "under this craft item id in top_gaps, with the same timestamp",
            "map": dict(QA_DEFECT_CRAFT_ITEMS)},
        "payoff_types": standard.get("payoff_types_zh") or [],
        "pacing_targets": standard.get("pacing_targets") or {},
        "measured_pacing": measured,
        "items": items,
        "answer_block": {
            "standard_version": STANDARD_VERSION,
            "layer_scores": {k: {"score": "1..5", "core_pass": "n/m", "reason": "evidence"} for k in LAYER_KEYS},
            "items": {"S-01": {"verdict": "PASS|GAP|NA", "evidence": "what, when, how much"}},
            "top_gaps": [{"rank": 1, "item_id": "S-02", "window": [14.2, 71.0], "metric": "56.8 s without a payoff",
                          "fix": "move the reveal to ~35 s and add a counter-strike at 45-60 s",
                          "fix_owner": "writer|engine|S7"}],
            "pacing_metrics": {"first_conflict_at": 0.6, "payoffs": [{"t": 14.2, "type": "打脸", "setup_t": 6.0,
                                                                      "reaction_shot": 7}],
                               "cliffhanger_at": 106.9, "prev_payoff_at": 2.1}},
    }


# --------------------------------------------------------------------------- lenient parse of the answer block
def _text(value: Any, limit: int = TEXT_MAX_CHARS) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _seconds(value: Any, duration: float | None) -> float | None:
    t = _num(value)
    if t is None or t < 0 or (duration and t > duration + 0.5):
        return None
    return round(t, 3)


def _score(value: Any) -> int | None:
    s = _num(value)
    return int(round(s)) if s is not None and 1 <= s <= 5 else None


def parse_block(block: Any, *, standard: dict[str, Any] | None = None, duration: float | None = None,
                shot_count: int | None = None, measured: dict[str, Any] | None = None) -> dict[str, Any]:
    """Lenient: keep what is well formed, drop the rest with a note.  Never raises.

    status: MISSING (no block), MALFORMED (not an object), OK (nothing dropped) or PARTIAL."""
    standard = standard if standard is not None else load_items()
    index = item_index(standard)
    out: dict[str, Any] = {"schema": BLOCK_SCHEMA, "standard_version": STANDARD_VERSION, "notes": [],
                           "authority": "ADVISORY_NOT_A_GATE", "measured_pacing": measured or {}}
    if block is None:
        return {**out, "status": "MISSING"}
    if not isinstance(block, dict):
        return {**out, "status": "MALFORMED", "notes": [f"block_not_object:{type(block).__name__}"]}
    notes: list[str] = out["notes"]
    try:
        version = _text(block.get("standard_version"), 60)
        if version and version != STANDARD_VERSION:
            notes.append(f"standard_version:{version}")
        layers = {}
        raw_layers = block.get("layer_scores") if isinstance(block.get("layer_scores"), dict) else {}
        for key in LAYER_KEYS:
            row = raw_layers.get(key)
            if row is None:
                continue
            row = row if isinstance(row, dict) else {"score": row}
            score = _score(row.get("score"))
            if score is None:
                notes.append(f"layer_scores.{key}:invalid_score")
                continue
            layers[key] = {"score": score, "core_pass": _text(row.get("core_pass"), 12) or None,
                           "reason": _text(row.get("reason")) or None}
        out["layer_scores"] = layers
        items: dict[str, dict[str, Any]] = {}
        raw_items = block.get("items") if isinstance(block.get("items"), dict) else {}
        if block.get("items") is not None and not isinstance(block.get("items"), dict):
            notes.append("items:not_object")
        for key, row in raw_items.items():
            iid = normalise_item_id(key)
            if iid is None or (index and iid not in index):
                notes.append(f"items:unknown_id:{_text(key, 12)}")
                continue
            row = row if isinstance(row, dict) else {"verdict": row}
            verdict = _text(row.get("verdict"), 8).upper()
            if verdict not in VERDICTS:
                notes.append(f"items.{iid}:invalid_verdict")
                continue
            items[iid] = {"verdict": verdict, "evidence": _text(row.get("evidence")) or None}
        out["items"] = items
        core = [iid for iid, row in index.items() if row.get("severity") == "CORE"]
        for layer, prefix in (("pacing_structure", "S-"), ("clarity_grammar", "C-")):
            ids = [i for i in core if i.startswith(prefix)]
            judged = [i for i in ids if items.get(i, {}).get("verdict") in ("PASS", "GAP")]
            out.setdefault("core_pass", {})[layer] = {
                "pass": sum(1 for i in ids if items.get(i, {}).get("verdict") == "PASS"),
                "gap": sum(1 for i in ids if items.get(i, {}).get("verdict") == "GAP"), "judged": len(judged),
                "core_items": len(ids)}
        gaps = []
        raw_gaps = block.get("top_gaps") if isinstance(block.get("top_gaps"), list) else []
        if block.get("top_gaps") is not None and not isinstance(block.get("top_gaps"), list):
            notes.append("top_gaps:not_array")
        for pos, row in enumerate(raw_gaps):
            if not isinstance(row, dict):
                notes.append(f"top_gaps.{pos}:not_object")
                continue
            iid = normalise_item_id(row.get("item_id") or row.get("id"))
            if iid is None or (index and iid not in index):
                notes.append(f"top_gaps.{pos}:unknown_item_id")
                continue
            owner_raw = _text(row.get("fix_owner") or row.get("owner"), 12)
            owner = next((o for o in FIX_OWNERS if o.lower() == owner_raw.lower()), None)
            if owner is None:
                owner = str((index.get(iid) or {}).get("default_fix_owner") or "writer")
                notes.append(f"top_gaps.{pos}:fix_owner_defaulted:{owner}")
            gap: dict[str, Any] = {"rank": int(_num(row.get("rank")) or pos + 1), "item_id": iid, "fix_owner": owner}
            at = _seconds(row.get("at_seconds"), duration)
            if at is not None:
                gap["at_seconds"] = at
            window = row.get("window")
            if isinstance(window, (list, tuple)) and len(window) == 2:
                a, b = _seconds(window[0], duration), _seconds(window[1], duration)
                if a is not None and b is not None and b >= a:
                    gap["window"] = [a, b]
            shot = row.get("shot_index")
            if isinstance(shot, int) and not isinstance(shot, bool) and shot >= 0 and (
                    shot_count is None or shot < shot_count):
                gap["shot_index"] = shot
            gap["metric"] = _text(row.get("metric"), 160) or None
            gap["fix"] = _text(row.get("fix"), 200) or None
            if items.get(iid, {}).get("verdict") not in (None, "GAP"):
                notes.append(f"top_gaps.{pos}:item_verdict_not_gap:{iid}")
            if not gap["fix"]:
                notes.append(f"top_gaps.{pos}:fix_missing")
            gaps.append(gap)
        gaps.sort(key=lambda g: g["rank"])
        if len(gaps) > MAX_TOP_GAPS:
            notes.append(f"top_gaps:truncated_from:{len(gaps)}")
        out["top_gaps"] = gaps[:MAX_TOP_GAPS]
        pm = block.get("pacing_metrics") if isinstance(block.get("pacing_metrics"), dict) else {}
        reviewer: dict[str, Any] = {}
        for key in ("first_conflict_at", "cliffhanger_at", "prev_payoff_at"):
            if pm.get(key) is not None:
                value = _seconds(pm.get(key), duration)
                if value is None:
                    notes.append(f"pacing_metrics.{key}:invalid")
                else:
                    reviewer[key] = value
        payoffs = []
        for pos, row in enumerate(pm.get("payoffs") if isinstance(pm.get("payoffs"), list) else []):
            t = _seconds((row or {}).get("t") if isinstance(row, dict) else None, duration)
            if t is None:
                notes.append(f"pacing_metrics.payoffs.{pos}:invalid_t")
                continue
            entry: dict[str, Any] = {"t": t, "type": _text(row.get("type"), 12) or None}
            setup = _seconds(row.get("setup_t"), duration)
            if setup is not None:
                entry["setup_t"] = setup
            if isinstance(row.get("reaction_shot"), int) and not isinstance(row.get("reaction_shot"), bool):
                entry["reaction_shot"] = row["reaction_shot"]
            payoffs.append(entry)
        payoffs.sort(key=lambda p: p["t"])
        if payoffs or "payoffs" in pm:
            reviewer["payoffs"] = payoffs
            reviewer["payoff_count"] = len(payoffs)
            times = [0.0] + [p["t"] for p in payoffs] + ([float(duration)] if duration else [])
            gaps_s = [round(b - a, 3) for a, b in zip(times, times[1:])]
            if gaps_s:
                reviewer["max_payoff_gap_seconds"] = max(gaps_s)
        out["pacing_metrics"] = reviewer
        breakdown = block.get("director_score_breakdown")
        if isinstance(breakdown, dict):
            out["director_score_breakdown"] = {_text(k, 40): [_text(x, 24) for x in v[:12]]
                                               for k, v in list(breakdown.items())[:8] if isinstance(v, list)}
    except Exception as exc:  # noqa: BLE001 -- lenient by contract
        notes.append(f"parse_error:{type(exc).__name__}")
    out["status"] = "OK" if not notes else "PARTIAL"
    return out


# --------------------------------------------------------------------------- top gaps -> knowledge events
def metric_values(text: Any, limit: int = 6) -> list[float]:
    return [float(x) for x in _NUM_RE.findall(str(text or ""))[:limit]]


def _leaks(text: str, lines: Iterable[str], run: int = 6) -> bool:
    """True when ``text`` repeats ``run``+ consecutive characters of a dialogue line (story text)."""
    squash = re.sub(r"\s+", "", text)
    for line in lines:
        body = re.sub(r"\s+", "", re.split(r"[：:]", str(line), maxsplit=1)[-1])
        for i in range(0, max(0, len(body) - run + 1)):
            if body[i:i + run] in squash:
                return True
    return False


def scrub_fix(fix: Any, *, roles: dict[str, str] | None = None, dialogue_lines: Iterable[str] = (),
              scrub_text=None, clean_field=None) -> str | None:
    """A short fix line safe for the publicly readable bucket, or None.  Quoted text -> 「…」, cast names (``roles``)
    -> 角色A/B, ids/paths/URLs removed, <= FIX_MAX_CHARS; dropped when it still repeats dialogue or trips the
    sensitive / control-language filters.  ``scrub_text`` / ``clean_field`` / ``roles``: from
    tools/collective_learning/exemplars (scrub_text, _clean_field, role_map); no scrubber -> no fix line."""
    if not fix or scrub_text is None:
        return None
    text = scrub_text(fix, roles=roles or {}, limit=FIX_MAX_CHARS)
    if len(text) < 4 or _leaks(text, dialogue_lines) or (clean_field is not None and not clean_field(text)):
        return None
    return text


def gap_events(parsed: dict[str, Any], *, standard: dict[str, Any] | None = None, roles: dict[str, str] | None = None,
               dialogue_lines: Iterable[str] = (), scrub_text=None, clean_field=None,
               sensitive=None) -> list[dict[str, Any]]:
    """One knowledge-event spec per top gap: {item_id, stage, failure_type, symptom, evidence}.

    Evidence carries only the item id (+ its layer/severity), the owner, timestamps / shot index, the metric's
    numbers, the cut's measured pacing numbers and a scrubbed fix line -- never dialogue or story text.
    ``sensitive(payload) -> list`` (contracts.sensitive_findings) drops the fix, then the whole event, on a hit."""
    standard = standard if standard is not None else load_items()
    index = item_index(standard)
    measured = parsed.get("measured_pacing") if isinstance(parsed.get("measured_pacing"), dict) else {}
    pace = {k: measured.get(k) for k in ("mean_shot_seconds", "shot_count", "duration_seconds",
                                         "silent_shots_over_4s_count") if measured.get(k) is not None}
    if isinstance(measured.get("longest_silent_shot"), dict):
        pace["longest_silent_shot_seconds"] = measured["longest_silent_shot"].get("seconds")
    dialogue_lines = list(dialogue_lines)
    out = []
    for gap in parsed.get("top_gaps") or []:
        iid = normalise_item_id(gap.get("item_id"))
        if iid is None or (index and iid not in index):
            continue
        item = index.get(iid) or {}
        owner = gap.get("fix_owner") if gap.get("fix_owner") in FIX_OWNERS else "writer"
        # ``detail`` is what the release-train review shows per sample (release_train.evidence_sample)
        detail: dict[str, Any] = {
            "fix_owner": owner, "rank": gap.get("rank"),
            **{k: gap[k] for k in ("at_seconds", "window", "shot_index") if gap.get(k) is not None},
            "metric_values": metric_values(gap.get("metric")),
            **({"measured_pacing": pace} if pace else {}),
        }
        evidence: dict[str, Any] = {
            "cluster_key": f"{FAILURE_TYPE}|{iid}", "item": iid, "detail_category": iid, "failure_code": iid,
            "standard_version": STANDARD_VERSION, "layer": item.get("layer"), "severity": item.get("severity"),
            "fix_owner": owner, "detail": detail}
        fix = scrub_fix(gap.get("fix"), roles=roles, dialogue_lines=dialogue_lines, scrub_text=scrub_text,
                        clean_field=clean_field)
        if fix:
            detail["fix"] = fix
        if sensitive is not None and sensitive(evidence):
            detail.pop("fix", None)
            if sensitive(evidence):
                continue
        out.append({"item_id": iid, "stage": OWNER_STAGE[owner], "failure_type": FAILURE_TYPE,
                    "symptom": f"craft standard gap {iid} ({item.get('title_en') or iid}); fix owner {owner}",
                    "evidence": evidence})
    return out
