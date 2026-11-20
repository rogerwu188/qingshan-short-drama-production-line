#!/usr/bin/env python3
"""One automatic fix round after the independent final review (line owner 2026-11-20: "不要等我了，我自己看不过来").

Episodes never stop and wait for the line owner on quality.  When the S7 final review comes back REJECT_RECUT, or
with confirmed must-check DEFECTs (nalu_qa_defect_checklist / the Gemini A/V pass confirmed by the Codex reviewer),
the engine runs exactly ONE fix round before release, then one more final review, and proceeds whatever that second
verdict is (``NALU_FINAL_FIX_ROUNDS``, default 1; 0 disables; values above 1 are clamped to 1 -- never a loop).

Each confirmed finding is mapped to one fix class:

* ``FREE_S7`` -- re-cut / re-mix with the existing S7 tools, zero credits:
    STATIC_SHOT_SPLIT     an over-long static shot is split with a cutaway from a neighbouring unit's unused frames
                          (unit_recut plan; the unit's own sound runs on), else with a punch-in on its second half
    AUDIO_SMOOTHING       audio-bed RMS jump / loudness window too hot -> longer equal-power cut crossfades
    BGM_FADES             music starting / stopping abruptly -> longer cue fades and a longer minimum cue
                          (bgm_cue_shaping)
    SUBTITLE_WRAP         a bad caption wrap -> long lines become sequential cues (--split-long-captions)
    DIALOGUE_TAIL_GUARD   a clipped line tail -> a wider tail guard and post-line beat (dialogue_tail_guard)
* ``PAID_S6_REDO`` -- one re-render of a named unit, only for defects a re-render can plausibly fix:
    BURNED_TEXT (QA-BURNED-TEXT), COSTUME_IDENTITY (costume / identity colour mismatch; the identity card's colours
    are pinned into the redo prompt), FACE_DRIFT (face drift / wrong face) and SKIN_SHEEN (QA-SKIN-SHEEN-DRIFT: oily /
    sweaty / over-sharpened skin, wet hair; 2026-11-20 -- the redo opens on the normalised tail frame and carries the
    matte-skin sentence).  At most one redo per unit in the
    round, through every existing S6 gate (budget ledger and episode cap, D-11, the paid order, the durable store,
    the stale-binding guard).  The round's planned spend is capped by ``NALU_FINAL_FIX_BUDGET_CREDITS`` (default 45)
    and the episode headroom; when they do not cover every redo, burned text goes first, then costume / identity,
    then face drift, then skin sheen, each by on-screen duration.
* ``RECORD_ONLY`` -- pacing, story, length shortfall, voice collision, ASR mismatch, look-alike cast, letterbox,
  oversized mask and anything else: recorded in ``final_fix_round.json`` and the S8 summary, never acted on.

Pure functions (no I/O except :func:`write_record`); nalu_pipeline wires them into S7 / S6 / S8.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA = "nalu.final_fix_round.v1"
REDO_SCHEMA = "nalu.final_fix_redo.v1"
SETTINGS_SCHEMA = "nalu.final_fix_s7_settings.v1"
RECORD_NAME = "final_fix_round.json"
TASK_FIELD = "h3_final_fix"

BUDGET_ENV = "NALU_FINAL_FIX_BUDGET_CREDITS"
DEFAULT_BUDGET = 45
ROUNDS_ENV = "NALU_FINAL_FIX_ROUNDS"
DEFAULT_ROUNDS = 1

FREE = "FREE_S7"
PAID = "PAID_S6_REDO"
RECORD = "RECORD_ONLY"

FREE_KINDS = ("STATIC_SHOT_SPLIT", "AUDIO_SMOOTHING", "BGM_FADES", "SUBTITLE_WRAP", "DIALOGUE_TAIL_GUARD")
PAID_KINDS = ("BURNED_TEXT", "COSTUME_IDENTITY", "FACE_DRIFT", "SKIN_SHEEN")
#: owner order when the round's budget does not cover every paid redo
PAID_PRIORITY = {kind: rank for rank, kind in enumerate(PAID_KINDS)}

#: QA-* / Gemini item -> fix kind (LOOK-DRIFT and OTHER are classified on their text)
ITEM_KIND = {
    "QA-BURNED-TEXT": "BURNED_TEXT",
    "QA-DIALOGUE-TAIL-CUT": "DIALOGUE_TAIL_GUARD",
    "QA-SUBTITLE-WRAP": "SUBTITLE_WRAP",
    "QA-BGM-DISCONTINUOUS": "BGM_FADES",
    "QA-SKIN-SHEEN-DRIFT": "SKIN_SHEEN",
    "QA-OVERSIZED-MASK": "MASK",
    "QA-LOOKALIKE-CAST": "LOOKALIKE",
    "LETTERBOX": "LETTERBOX",
}

#: (kind, keywords) in priority order; the first match wins.  Lower-case English + Chinese.
KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("LOOKALIKE", ("look alike", "lookalike", "look-alike", "same face as", "长得一样", "长得几乎一样", "撞脸")),
    ("BURNED_TEXT", ("burned-in", "burned in", "burnt-in", "burnt in", "burned text", "burned caption",
                     "burned subtitle", "on-screen text", "onscreen text", "stray text", "garbled text",
                     "stray caption", "second subtitle", "text overlay", "stray glyph", "烧进", "烧录", "烧入",
                     "画面里的字", "画面文字", "乱码", "多余字幕", "多出一个", "模型字幕", "字幕重影")),
    ("COSTUME_IDENTITY", ("costume", "wardrobe", "outfit", "clothing", "clothes", "garment", "identity colo",
                          "colour mismatch", "color mismatch", "changes colo", "different colo", "服装", "衣服",
                          "换装", "服色", "衣色", "戏服", "颜色不一致", "颜色变")),
    ("SKIN_SHEEN", ("oily", "greasy", "glossy skin", "shiny skin", "skin sheen", "sweaty", "wet hair",
                    "wet-looking hair", "over-sharpen", "oversharpen", "crunchy texture", "油光", "油腻", "抹了油",
                    "出油", "满脸汗", "冒汗", "头发湿", "湿发", "过锐", "锐化过度", "过度锐化")),
    ("FACE_DRIFT", ("face drift", "face changes", "face changed", "different face", "wrong face", "face swap",
                    "face does not match", "face doesn't match", "identity drift", "looks like a different",
                    "脸变", "换脸", "脸不一样", "长相变", "面部漂移", "不像同一个人", "五官变")),
    ("SUBTITLE_WRAP", ("wrap", "line break", "lone punctuation", "on its own line", "换行", "单独成行", "断行")),
    ("DIALOGUE_TAIL_GUARD", ("cut off", "clipped", "truncated", "last syllable", "tail cut", "no pause",
                             "cuts mid", "尾音", "被剪", "切断", "截断", "没有停顿", "没停顿")),
    ("BGM_FADES", ("bgm", "music", "配乐", "音乐", "背景乐")),
    ("AUDIO_SMOOTHING", ("rms", "loudness", "too loud", "too hot", "volume jump", "level jump", "audio jump",
                         "sudden loud", "louder", "quieter", "audio bed", "room tone", "响度", "音量", "忽大忽小",
                         "突然变响", "突然变大", "爆音", "底噪")),
    ("STATIC_SHOT_SPLIT", ("static shot", "static frame", "static image", "frozen", "freeze", "held too long",
                           "holds too long", "lingers", "定格", "静止", "画面不动", "镜头过长", "镜头太长",
                           "停留太久")),
    ("LETTERBOX", ("letterbox", "pillarbox", "black bar", "黑边")),
    ("MASK", ("blur box", "mask", "cover box", "遮挡", "模糊框")),
    ("VOICE", ("voice", "音色", "声线", "same speaker")),
    ("ASR_MISMATCH", ("lip", "asr", "transcri", "口型", "台词不", "对不上", "mismatch")),
    ("LENGTH", ("too short", "length", "runtime", "duration", "时长", "太短")),
    ("PACING", ("pacing", "pace", "slow", "rhythm", "drag", "节奏", "拖沓", "拖")),
    ("STORY", ("story", "plot", "motivation", "logic", "剧情", "逻辑", "故事")),
)

#: env overrides the re-run of S7 applies for each FREE kind (only where the operator has not set the name)
FREE_SETTINGS: dict[str, dict[str, str]] = {
    "AUDIO_SMOOTHING": {"NALU_S7_CUT_CROSSFADE_SECONDS": "0.16"},
    "BGM_FADES": {"NALU_BGM_MIN_CUE_SECONDS": "16", "NALU_BGM_FADE_SCALE": "1.6"},
    "SUBTITLE_WRAP": {"NALU_S7_SPLIT_LONG_CAPTIONS": "1"},
    "DIALOGUE_TAIL_GUARD": {"NALU_S7_TAIL_GUARD_SECONDS": "0.4", "NALU_S7_POST_LINE_BEAT_SECONDS": "0.7"},
}

STATIC_MIN_SPLIT_SECONDS = 4.0     # a cut shorter than this is not split
CUTAWAY_MIN_SECONDS = 0.8          # borrowed frames shorter than this are not a cutaway
CUTAWAY_MAX_SECONDS = 1.5
PUNCH_IN_FRAME = [0.1, 0.08, 0.8, 0.8]  # x, y, w, h of the second half's punch-in (unit_recut reframe)
GEMINI_MATCH_S = 1.5

#: prompt sentences of the paid redo (plain English, no digits, no all-caps labels: H3 voices labels)
SENTENCES = {
    "BURNED_TEXT": ("Nothing is written anywhere in the picture: no caption, subtitle, sign lettering or text of any "
                    "kind appears in any frame, and the spoken words are only heard."),
    "FACE_DRIFT": ("Each person keeps exactly the face of their identity reference image from the first frame to the "
                   "last: the same face shape, eyes, nose, hairline and age, with no drift toward another face."),
    "COSTUME_IDENTITY": ("Each person wears exactly the costume colours and garments of their identity reference "
                         "image for the whole clip; no garment changes colour or style."),
    "SKIN_SHEEN": ("Every face keeps natural matte skin and dry hair from the first frame to the last: no oily, glossy "
                   "or sweaty sheen, no wet-looking strands and no harsh over-sharpened skin texture."),
}
_ASCII_TEXT = re.compile(r"^[A-Za-z][A-Za-z ,'\-]{0,60}$")


# ------------------------------------------------------------------------------------------------- settings
def budget_credits(env: dict[str, str] | None = None) -> int:
    raw = str((os.environ if env is None else env).get(BUDGET_ENV, DEFAULT_BUDGET)).strip()
    try:
        return max(0, int(float(raw)))
    except ValueError:
        return DEFAULT_BUDGET


def rounds(env: dict[str, str] | None = None) -> int:
    """Fix rounds allowed per episode: 0 (disabled) or 1.  Never more: the second verdict always proceeds."""
    raw = str((os.environ if env is None else env).get(ROUNDS_ENV, DEFAULT_ROUNDS)).strip()
    try:
        return 1 if int(float(raw)) >= 1 else 0
    except ValueError:
        return DEFAULT_ROUNDS


def fix_class(kind: str) -> str:
    return FREE if kind in FREE_KINDS else PAID if kind in PAID_KINDS else RECORD


def classify_text(text: str) -> str:
    low = str(text or "").lower()
    for kind, words in KEYWORDS:
        if any(w in low for w in words):
            return kind
    return "OTHER"


def classify(item: str | None, text: str = "") -> str:
    """Fix kind of one finding: the QA item decides when it names one, else the finding's text."""
    item = str(item or "").upper()
    if item in ITEM_KIND:
        return ITEM_KIND[item]
    if item == "LOOK-DRIFT":
        kind = classify_text(text)
        return kind if kind in ("FACE_DRIFT", "BURNED_TEXT") else "COSTUME_IDENTITY"
    return classify_text(text)


# ------------------------------------------------------------------------------------------------- findings
def _num(value: Any) -> float | None:
    try:
        return None if value is None or isinstance(value, bool) else float(value)
    except (TypeError, ValueError):
        return None


def _span(row: dict[str, Any]) -> tuple[float, float] | None:
    at = _num(row.get("at_seconds"))
    if at is not None:
        return at, at
    window = row.get("window")
    if isinstance(window, (list, tuple)) and len(window) == 2 and _num(window[0]) is not None:
        end = _num(window[1])
        return float(window[0]), float(end if end is not None else window[0])
    start = _num(row.get("start"))
    if start is not None:
        end = _num(row.get("end"))
        return start, end if end is not None else start
    return None


def _kb_scope(row: dict[str, Any]) -> dict[str, Any]:
    """The reviewer's optional knowledge-base scope of a finding (``kb_scope`` global|language + reason): carried
    to the knowledge event, never used by the fix round."""
    scope = str(row.get("kb_scope") or "").strip().lower()
    if scope not in ("global", "language"):
        return {}
    reason = str(row.get("kb_scope_reason") or "").strip()[:200]
    return {"kb_scope": scope, **({"kb_scope_reason": reason} if reason else {})}


def collect_findings(report: dict[str, Any] | None, checklist: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Confirmed findings of one final review: reviewer DEFECTs of the must-check list, Gemini findings the reviewer
    CONFIRMED (not within GEMINI_MATCH_S of a reviewer finding of the same item), the score report's problems and an
    identity-colour hard fail.  Measured-but-unreviewed flags and dismissed / unverified Gemini findings are not
    confirmed and are left out."""
    report = report if isinstance(report, dict) else {}
    checklist = checklist if isinstance(checklist, dict) else {}
    out: list[dict[str, Any]] = []
    for iid, row in (checklist.get("items") or {}).items():
        if (row or {}).get("status") != "DEFECT":
            continue
        for f in row.get("reviewer_findings") or [{}]:
            span = _span(f)
            out.append({"source": "QA_CHECKLIST_REVIEWER", "item": iid, "text": str(f.get("note") or ""),
                        **({"window": [round(span[0], 3), round(span[1], 3)]} if span else {})})
    reviewer = [(f["item"], f.get("window")) for f in out]
    for g in (checklist.get("video_review") or {}).get("findings") or []:
        if g.get("status") != "CONFIRMED":
            continue
        span = _span(g)
        if span and any(item == g.get("item") and w and w[0] - GEMINI_MATCH_S <= span[1]
                        and span[0] <= w[1] + GEMINI_MATCH_S for item, w in reviewer):
            continue
        out.append({"source": "GEMINI_CONFIRMED", "item": str(g.get("item") or "OTHER"),
                    "text": str(g.get("note") or ""), "severity": g.get("severity"),
                    **({"window": [round(span[0], 3), round(span[1], 3)]} if span else {}), **_kb_scope(g)})
    for p in report.get("problems") or []:
        if not isinstance(p, dict):
            continue
        span = _span(p)
        out.append({"source": "REVIEW_PROBLEM", "item": None, "severity": p.get("severity"),
                    "text": f"{p.get('issue') or ''} | {p.get('fix') or ''}".strip(" |"),
                    **({"window": [round(span[0], 3), round(span[1], 3)]} if span else {}), **_kb_scope(p)})
    if "identity_color_mismatch" in (report.get("hard_fail") or []):
        out.append({"source": "REVIEW_HARD_FAIL", "item": None, "text": "identity colour mismatch (hard fail)",
                    "kind_hint": "COSTUME_IDENTITY"})
    return out


def unit_at(segments: list[dict[str, Any]], window: list[float] | None) -> dict[str, Any] | None:
    """The release-timeline segment a finding falls in (largest overlap of its window; a point picks its segment)."""
    if not window:
        return None
    t0, t1 = float(window[0]), float(window[1])
    best, best_overlap = None, -1.0
    for seg in segments or []:
        a, b = _num(seg.get("output_start")), _num(seg.get("output_end"))
        if a is None or b is None or not seg.get("unit_id"):
            continue
        if t0 == t1:
            if a <= t0 < b or (t0 == b and seg is segments[-1]):
                return seg
            continue
        overlap = min(b, t1) - max(a, t0)
        if overlap > best_overlap and overlap > 0:
            best, best_overlap = seg, overlap
    return best


def map_findings(findings: list[dict[str, Any]], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each finding with its kind, fix class and (when it has a time) the unit and that unit's on-screen seconds."""
    out = []
    for f in findings:
        kind = f.get("kind_hint") or classify(f.get("item"), f.get("text") or "")
        row = {**{k: v for k, v in f.items() if k != "kind_hint"}, "kind": kind, "class": fix_class(kind)}
        seg = unit_at(segments, f.get("window"))
        if seg is not None:
            row["unit_id"] = str(seg["unit_id"])
            row["on_screen_seconds"] = round(float(seg["output_end"]) - float(seg["output_start"]), 3)
        out.append(row)
    return out


CONFIRMED_SOURCES = ("QA_CHECKLIST_REVIEWER", "GEMINI_CONFIRMED")


def triggered(rejected: bool, mapped: list[dict[str, Any]]) -> bool:
    """A REJECT_RECUT verdict, or a PASS with a confirmed must-check DEFECT (reviewer DEFECT / confirmed Gemini
    finding).  A PASS whose report merely lists problems is not a trigger."""
    return bool(rejected) or any(f.get("source") in CONFIRMED_SOURCES for f in mapped)


def actionable(mapped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in mapped if f["class"] == FREE or (f["class"] == PAID and f.get("unit_id"))]


def needs_round(rejected: bool, mapped: list[dict[str, Any]]) -> bool:
    """A round runs on a trigger -- but only when something can be acted on (else the line records and proceeds)."""
    return triggered(rejected, mapped) and bool(actionable(mapped))


# ------------------------------------------------------------------------------------------------ paid plan
def plan_paid(mapped: list[dict[str, Any]], *, budget: int, headroom: int | None,
              unit_cost: Callable[[str], int], eligible: Callable[[str], str | None] | None = None,
              unit_order: list[str] | None = None) -> dict[str, Any]:
    """One redo per unit; burned text, then costume / identity, then face drift, each by on-screen duration.

    ``eligible(uid)`` returns a skip reason or None.  The allowance is min(budget, headroom); a unit that does not
    fit is skipped (``BUDGET_CAP``) and cheaper ones after it may still fit.  Pure."""
    order = {uid: i for i, uid in enumerate(unit_order or [])}
    units: dict[str, dict[str, Any]] = {}
    unlocated = []
    for f in mapped:
        if f["class"] != PAID:
            continue
        uid = f.get("unit_id")
        if not uid:
            unlocated.append({"kind": f["kind"], "reason": "NO_UNIT_FOR_FINDING", "source": f.get("source")})
            continue
        row = units.setdefault(uid, {"unit_id": uid, "kinds": [], "on_screen_seconds": f.get("on_screen_seconds") or 0})
        if f["kind"] not in row["kinds"]:
            row["kinds"].append(f["kind"])
    for row in units.values():
        row["kinds"].sort(key=lambda k: PAID_PRIORITY[k])
        row["kind"] = row["kinds"][0]
    ranked = sorted(units.values(), key=lambda r: (PAID_PRIORITY[r["kind"]], -float(r["on_screen_seconds"] or 0),
                                                   order.get(r["unit_id"], 10 ** 6), r["unit_id"]))
    allowance = int(budget) if headroom is None else min(int(budget), max(0, int(headroom)))
    spent = 0
    selected, skipped = [], list(unlocated)
    for row in ranked:
        reason = eligible(row["unit_id"]) if eligible else None
        if reason:
            skipped.append({**row, "reason": reason})
            continue
        cost = int(unit_cost(row["unit_id"]))
        if spent + cost > allowance:
            skipped.append({**row, "reason": "BUDGET_CAP", "cost": cost, "allowance_left": allowance - spent})
            continue
        spent += cost
        selected.append({**row, "cost": cost})
    return {"selected": selected, "skipped": skipped, "planned_credits": spent, "allowance": allowance,
            "budget_cap": int(budget), "headroom": headroom}


# ---------------------------------------------------------------------------------------------- free fixes
def free_settings(kinds: Iterable[str], environ: dict[str, str] | None = None) -> dict[str, Any]:
    """{env: {...}, kept_operator_env: [...]} for the FREE kinds: an env name the operator already set is kept."""
    env = os.environ if environ is None else environ
    out: dict[str, str] = {}
    kept = []
    for kind in sorted(set(kinds)):
        for name, value in FREE_SETTINGS.get(kind, {}).items():
            if str(env.get(name) or "").strip():
                kept.append(name)
            else:
                out[name] = value
    return {"env": out, "kept_operator_env": sorted(set(kept))}


def static_shot_segments(uid: str, window: tuple[float, float], *, neighbours: list[dict[str, Any]]) -> dict[str, Any]:
    """unit_recut segments splitting one over-long static unit.

    ``window`` is the unit's source in/out in the current cut.  ``neighbours`` are [{unit_id, unused: [(a, b), ...]}]
    (source seconds of that unit the cut does not show).  With >= CUTAWAY_MIN_SECONDS of unused neighbour frames the
    middle of the unit is covered by a cutaway (picture from the neighbour, sound from the unit itself, so the line
    and the timing do not move); otherwise the second half is a punch-in on the same take.  Returns
    {status, method, segments} -- status TOO_SHORT_TO_SPLIT for cuts under STATIC_MIN_SPLIT_SECONDS."""
    a, b = float(window[0]), float(window[1])
    length = b - a
    if length < STATIC_MIN_SPLIT_SECONDS:
        return {"status": "TOO_SHORT_TO_SPLIT", "seconds": round(length, 3)}
    for nb in neighbours or []:
        for lo, hi in nb.get("unused") or []:
            span = float(hi) - float(lo)
            if span < CUTAWAY_MIN_SECONDS:
                continue
            c = round(min(CUTAWAY_MAX_SECONDS, span, length / 3), 3)
            m = round(a + (length - c) / 2, 3)
            src = round(float(lo) + (span - c) / 2, 3)
            return {"status": "PLANNED", "method": "CUTAWAY", "borrowed_from": nb["unit_id"], "segments": [
                {"video": [uid, round(a, 3), m], "audio": [uid, round(a, 3), m]},
                {"video": [nb["unit_id"], src, round(src + c, 3)], "audio": [uid, m, round(m + c, 3)]},
                {"video": [uid, round(m + c, 3), round(b, 3)], "audio": [uid, round(m + c, 3), round(b, 3)]}]}
    m = round(a + length / 2, 3)
    return {"status": "PLANNED", "method": "PUNCH_IN", "segments": [
        {"video": [uid, round(a, 3), m], "audio": [uid, round(a, 3), m]},
        {"video": [uid, m, round(b, 3)], "audio": [uid, m, round(b, 3)], "reframe": list(PUNCH_IN_FRAME)}]}


# ------------------------------------------------------------------------------------------- redo sentence
def _english(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip().rstrip(".;,")
    return text if _ASCII_TEXT.match(text) else ""


def costume_sentence(rows: list[dict[str, Any]], character_ids: Iterable[str] | None = None) -> str:
    """The costume-colour pin for a COSTUME_IDENTITY redo, from the identity card's wardrobe rows
    (wardrobe bible: character / english name, primary_color, outer_layer).  Only plain English values are used
    (H3 prompt boundary); without any, the generic sentence."""
    wanted = {str(c) for c in (character_ids or []) if c}
    pins = []
    for row in rows or []:
        if wanted and str(row.get("character_id") or "") not in wanted and str(row.get("character") or "") not in wanted:
            continue
        name = next((_english(row.get(k)) for k in ("english_name", "name_en", "display_name_en", "character")
                     if _english(row.get(k))), "")
        colour = _english(row.get("primary_color"))
        garment = _english(row.get("outer_layer"))
        if name and colour:
            pins.append(f"{name} in {colour}{(' ' + garment) if garment else ''}")
    if not pins:
        return SENTENCES["COSTUME_IDENTITY"]
    return ("Each person wears exactly the costume colours of their identity reference image for the whole clip: "
            + "; ".join(pins[:4]) + "; no garment changes colour or style.")


def redo_sentence(kinds: list[str], *, wardrobe_rows: list[dict[str, Any]] | None = None,
                  character_ids: Iterable[str] | None = None) -> str:
    """One line appended to the unit's provider prompt (the highest-priority kind's sentence, plus the costume pin
    when costume / identity is among the unit's findings)."""
    kinds = sorted(set(kinds), key=lambda k: PAID_PRIORITY.get(k, 9))
    parts = []
    for kind in kinds:
        text = (costume_sentence(wardrobe_rows or [], character_ids) if kind == "COSTUME_IDENTITY"
                else SENTENCES.get(kind, ""))
        if text and text not in parts:
            parts.append(text)
    return " ".join(parts[:2])


def apply_sentence(text: str, sentence: str) -> str:
    """``text`` with the redo sentence as its last line (trailing newlines kept); unchanged when empty / present."""
    if not sentence or sentence in text:
        return text
    core = text.rstrip("\n")
    return core + "\n" + sentence + text[len(core):]


def strip_sentence(text: str, sentence: str) -> tuple[str, bool]:
    """The exact inverse of :func:`apply_sentence`."""
    marker = "\n" + str(sentence or "")
    if sentence and marker in text:
        return text.replace(marker, "", 1), True
    return text, False


def task_sentence(payload: dict[str, Any] | None) -> str:
    value = (payload or {}).get(TASK_FIELD)
    return str(value.get("sentence") or "") if isinstance(value, dict) else ""


# --------------------------------------------------------------------------------------------- the record
def summary(record: dict[str, Any] | None) -> dict[str, Any]:
    """The concise view (S8 details, checkpoint, fleet status)."""
    record = record if isinstance(record, dict) else {}
    paid = record.get("paid") or {}
    return {"status": record.get("status"),
            "first_verdict": (record.get("first_review") or {}).get("verdict"),
            "second_verdict": (record.get("second_review") or {}).get("verdict"),
            "findings": len(record.get("findings") or []),
            "free_fixes": sorted({a.get("kind") for a in record.get("free_actions") or [] if a.get("kind")}),
            "units_redone": [r.get("unit_id") for r in paid.get("selected") or []],
            "planned_credits": paid.get("planned_credits", 0),
            "credits_spent": record.get("credits_spent"),
            "unresolved": len(record.get("unresolved") or [])}


def status_note(record: dict[str, Any] | None) -> str:
    """One line for the fleet status note, '' when there is no round to report."""
    s = summary(record)
    if not s["status"] or s["status"] in ("DISABLED",):
        return ""
    if s["status"] == "NOT_NEEDED":
        return "final-fix: not needed (review clean)"
    parts = [f"final-fix {s['status']}", f"1st {s['first_verdict'] or '?'}"]
    if s["second_verdict"]:
        parts.append(f"2nd {s['second_verdict']}")
    if s["free_fixes"]:
        parts.append("free " + ",".join(s["free_fixes"]))
    if s["units_redone"]:
        parts.append(f"redo {','.join(s['units_redone'])} ({s['planned_credits']} cr)")
    if s["unresolved"]:
        parts.append(f"unresolved {s['unresolved']}")
    return "; ".join(parts)


def unresolved(record: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Findings left for the record after the round (record-only, unlocated / skipped paid, and -- when the second
    review still rejected -- everything the round acted on, marked UNVERIFIED_AFTER_FIX)."""
    record = record if isinstance(record, dict) else {}
    redone = {r.get("unit_id") for r in (record.get("paid") or {}).get("selected") or []}
    second = (record.get("second_review") or {}).get("verdict")
    out = []
    for f in record.get("findings") or []:
        base = {k: f.get(k) for k in ("kind", "class", "unit_id", "window", "source") if f.get(k) is not None}
        if f.get("class") == RECORD:
            out.append({**base, "state": "RECORD_ONLY"})
        elif f.get("class") == PAID and f.get("unit_id") not in redone:
            out.append({**base, "state": "PAID_REDO_NOT_DONE"})
        elif second and second != "PASS":
            out.append({**base, "state": "UNVERIFIED_AFTER_FIX"})
    return out


def checkpoint_lines(record: dict[str, Any] | None) -> list[str]:
    if not isinstance(record, dict) or not record.get("status"):
        return []
    s = summary(record)
    lines = ["## Final fix round (owner policy 2026-11-20: never wait on quality)", "",
             f"* status **{s['status']}** — first review {s['first_verdict'] or '—'}, "
             f"second review {s['second_verdict'] or '—'}",
             f"* free S7 fixes: {', '.join(s['free_fixes']) or 'none'}",
             f"* paid S6 redo: {', '.join(s['units_redone']) or 'none'} (planned {s['planned_credits']} credits, "
             f"cap {(record.get('paid') or {}).get('budget_cap', '—')})"]
    for row in (record.get("paid") or {}).get("skipped") or []:
        lines.append(f"  * not redone `{row.get('unit_id') or '—'}` {row.get('kind')}: {row.get('reason')}")
    rest = record.get("unresolved") or unresolved(record)
    if rest:
        lines.append(f"* unresolved findings ({len(rest)}): " + ", ".join(
            f"{r.get('kind')}{('@' + r['unit_id']) if r.get('unit_id') else ''} [{r.get('state')}]" for r in rest[:12]))
    lines.append("")
    return lines


def write_record(path: Path, record: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"schema": SCHEMA, **record}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path
