#!/usr/bin/env python3
"""Cut to the performance (CAMERA_GRAMMAR_V1 episodes only; line owner 2026-11-02, lab 化神 E01).

HopsAPI H3 clips are at least 4 s (API floor), so a short line ("叫您干嘛？" ~1.5 s) leaves slack that H3 fills
with invented speech: an extra made-up sentence after the line (VU-020), the line said twice (VU-018), gibberish
before the line (VU-002), characters talking in a unit with no scripted dialogue (VU-011/VU-014).  At S7 each unit
is cut like a human editor would cut it -- only at its head and tail, never inside the take:

* speaking unit (on-screen scripted lines): the whole scripted text of the unit (all its on-screen lines in order) is
  aligned to the ASR words (zh: characters, traditional folded to simplified; en: words, misspellings folded onto the
  scripted word; homophones such as 战帖/战铁 or 评价/凭驾 are tolerated as substitutions inside the alignment).
  Kept window: [first scripted word - HEAD_LEAD, last scripted word + TAIL_PAD]; unscripted speech right before /
  after it moves the cut to that speech's end / start - SPEECH_GAP (TRIM_HEAD_UNSCRIPTED / TRIM_TAIL_UNSCRIPTED).
  A scripted text said more than once keeps its LAST complete occurrence (DROP_REPEAT; the earlier, partial or
  complete, performance is at the head and is cut there).  A head (tail) cut that is not driven by unscripted speech
  is applied only when the unit's first (last) shot carries a line, so an authored silent beat at either end of
  the take is kept.
* silent unit (no on-screen line; V.O.-only units included): ASR segments are gated by audio energy (a Whisper
  hallucination such as "字幕by索兰娅" / "Thanks for watching" on near-silence is not speech); when real speech is
  present only the longest contiguous window without speech is kept (SILENT_SPEECH_WINDOW).  A unit carrying V.O.
  lines keeps at least the V.O. it carries when the following placement would otherwise run into dialogue.
  Speech is never muted under moving lips: it is cut away or kept.
* every unit keeps at least MIN_KEEP_SECONDS; a cut that would go below keeps MIN_KEEP_SECONDS centred on the line
  (speaking) / the cleanest window (silent) and records a viewer-visible warning (MIN_LENGTH_HOLD; never blocks).

Pure functions: the S7 caller supplies the contract, grouping plan, unit ASR with word timestamps, clip durations,
per-unit energy and the existing tail/head trim reports; ``merge`` writes the decided in/out points into those two
reports, which the AgentCut build, push-in compensation and unit levelling already follow, and ``cut_unit_asr``
gives the ASR (source seconds, words outside the kept window dropped) for captions, V.O. and BGM.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

SCHEMA = "nalu.performance_cut.v1"
HEAD_LEAD = 0.15
TAIL_PAD = 0.4
SPEECH_GAP = 0.05
MIN_KEEP_SECONDS = 1.2
MIN_CUT_SECONDS = 0.05
MATCH_COVERAGE = 0.5
REPEAT_COVERAGE = 0.85
EDGE_BLOCK_MAX = 2          # an isolated match this small at the edge of the alignment is noise
EDGE_GAP_EXCESS = 3         # ... when it sits this many more heard tokens away than script tokens
SUBST_MAX = 3               # unmatched script tokens at an edge filled by adjacent heard tokens (homophones)
SUBST_GAP_SECONDS = 0.35
WORD_FOLD = 0.75
ENERGY_HOP = 0.02
SPEECH_BELOW_LEVEL_DB = 10.0
SPEECH_FLOOR_DB = -35.0
DEFAULT_SPEECH_LEVEL_DB = -14.0
SPEECH_FRAME_FRACTION = 0.25
SPEECH_MIN_SECONDS = 0.15
SPEECH_RUN_MERGE = 0.2
SPEECH_SEARCH_PAD = 0.3
SPEECH_PAD = 0.05
VOICE_ONLY_MODE = "VOICE_ONLY_NO_PLATE"
VO_LEAD_IN = 0.3            # tools/voice_over_narration.LEAD_IN_SECONDS
VO_LINE_GAP = 0.25          # tools/voice_over_narration.LINE_GAP_SECONDS
VO_SEPARATION = 0.2         # tools/voice_over_narration.MIN_SEPARATION_SECONDS

REASONS = ("TRIM_TAIL_UNSCRIPTED", "TRIM_HEAD_UNSCRIPTED", "DROP_REPEAT", "SILENT_SPEECH_WINDOW", "MIN_LENGTH_HOLD",
           "TRIM_HEAD_TO_LINE", "TRIM_TAIL_TO_LINE")  # the last two: plain [first word - lead, last word + pad]

try:  # traditional -> simplified (faster-whisper often answers zh in traditional characters)
    import opencc as _opencc  # type: ignore
    _T2S = _opencc.OpenCC("t2s").convert
except Exception:  # noqa: BLE001 -- optional; alignment still works char-for-char
    _T2S = None


def _simp(text: str) -> str:
    return _T2S(text) if _T2S else text


def _is_cjk(ch: str) -> bool:
    return "一" <= ch <= "鿿"


def _norm_en(word: str) -> str:
    return re.sub(r"[^0-9a-z]+", "", str(word).lower().replace("'", "").replace("’", ""))


def _body(text: str) -> str:
    text = str(text)
    return re.split(r"[：:]", text, maxsplit=1)[-1] if re.match(r"^[^：:]{1,24}[：:]", text) else text


def script_tokens(lines: list[str], cjk_mode: bool) -> list[str]:
    out: list[str] = []
    for line in lines:
        body = _body(line)
        if cjk_mode:
            out.extend(ch for ch in _simp(body) if _is_cjk(ch))
        else:
            out.extend(w for w in (_norm_en(w) for w in re.split(r"\s+|[-—–]", body)) if w)
    return out


def heard_tokens(segments: list[dict[str, Any]], cjk_mode: bool) -> list[dict[str, Any]]:
    """ASR words -> tokens [{tok, start, end}] (zh: one per character, times interpolated inside the word)."""
    out: list[dict[str, Any]] = []
    for seg in segments or []:
        words = seg.get("words") or []
        for word in words:
            if word.get("start") is None or word.get("end") is None:
                continue
            ws, we, text = float(word["start"]), float(word["end"]), str(word.get("word") or "")
            if cjk_mode:
                chars = [ch for ch in _simp(text) if _is_cjk(ch)]
                for i, ch in enumerate(chars):
                    step = (we - ws) / len(chars)
                    out.append({"tok": ch, "start": round(ws + i * step, 3), "end": round(ws + (i + 1) * step, 3)})
            else:
                norm = _norm_en(text)
                if norm:
                    out.append({"tok": norm, "start": ws, "end": we})
    return out


def _fold_en(script: list[str], heard: list[str]) -> list[str]:
    """English: a heard word close to a scripted word (ASR misspelling) is compared as that word."""
    vocab = set(script)
    out = []
    for word in heard:
        if word in vocab or len(word) < 4:
            out.append(word)
            continue
        best = max(vocab, key=lambda v: difflib.SequenceMatcher(None, v, word).ratio(), default=None)
        out.append(best if best and difflib.SequenceMatcher(None, best, word).ratio() >= WORD_FOLD else word)
    return out


def align(script: list[str], heard: list[dict[str, Any]], cjk_mode: bool, lo: int = 0
          ) -> dict[str, Any] | None:
    """Best span of ``heard[lo:]`` that performs ``script``: {first, last, coverage} (heard indices) or None."""
    tail = heard[lo:]
    toks = [h["tok"] for h in tail]
    if not cjk_mode:
        toks = _fold_en(script, toks)
    if not script or not toks:
        return None
    blocks = [b for b in difflib.SequenceMatcher(None, script, toks, autojunk=False).get_matching_blocks() if b.size]
    if not blocks:
        return None
    # isolated tiny matches at either edge (a common character inside the gibberish) are not the line
    while len(blocks) > 1 and blocks[0].size <= EDGE_BLOCK_MAX and (
            (blocks[1].b - blocks[0].b - blocks[0].size) - (blocks[1].a - blocks[0].a - blocks[0].size) > EDGE_GAP_EXCESS):
        blocks.pop(0)
    while len(blocks) > 1 and blocks[-1].size <= EDGE_BLOCK_MAX and (
            (blocks[-1].b - blocks[-2].b - blocks[-2].size) - (blocks[-1].a - blocks[-2].a - blocks[-2].size)
            > EDGE_GAP_EXCESS):
        blocks.pop()
    matched = sum(b.size for b in blocks)
    coverage = matched / len(script)
    if coverage < MATCH_COVERAGE:
        return {"first": None, "last": None, "coverage": round(coverage, 3)}
    first, last = blocks[0].b, blocks[-1].b + blocks[-1].size - 1
    # unmatched script tokens before the first / after the last match: misheard words (叫/教, 帖/铁) said right
    # there, so the adjacent heard tokens of the same phrase belong to the line
    for _ in range(min(SUBST_MAX, blocks[0].a)):
        if first > 0 and tail[first]["start"] - tail[first - 1]["end"] <= SUBST_GAP_SECONDS:
            first -= 1
    for _ in range(min(SUBST_MAX, len(script) - blocks[-1].a - blocks[-1].size)):
        if last + 1 < len(tail) and tail[last + 1]["start"] - tail[last]["end"] <= SUBST_GAP_SECONDS:
            last += 1
    return {"first": lo + first, "last": lo + last, "coverage": round(coverage, 3)}


def _resembles_script(removed: list[str], script: list[str]) -> bool:
    """Removed head/tail speech that repeats the scripted text (a second take of the line), not new words."""
    if not removed:
        return False
    sm = difflib.SequenceMatcher(None, script, removed, autojunk=False)
    return sum(b.size for b in sm.get_matching_blocks()) >= max(2, 0.4 * len(removed))


# ------------------------------------------------------------------------------------------------ energy / speech
def speech_threshold(level_db: float | None) -> float:
    level = DEFAULT_SPEECH_LEVEL_DB if level_db is None else float(level_db)
    return max(SPEECH_FLOOR_DB, level - SPEECH_BELOW_LEVEL_DB)


def _frames(frames: list[float], a: float, b: float) -> list[float]:
    return frames[max(0, int(a / ENERGY_HOP)):max(0, int(round(b / ENERGY_HOP)))]


def episode_speech_level(spans: list[tuple[list[float], float, float]]) -> float | None:
    """Median of the 75th-percentile frame energy inside scripted speech spans (dBFS); None when unmeasured."""
    values = []
    for frames, a, b in spans:
        seg = sorted(_frames(frames, a, b))
        if len(seg) >= 5:
            values.append(seg[int(0.75 * (len(seg) - 1))])
    if not values:
        return None
    values.sort()
    return values[len(values) // 2]


def speech_intervals(segments: list[dict[str, Any]], frames: list[float] | None, threshold: float,
                     duration: float) -> tuple[list[tuple[float, float]], list[dict[str, Any]]]:
    """Real speech in a unit: ASR segments whose span carries speech-level energy, narrowed / extended to the
    above-threshold energy runs around them.  Returns (merged intervals, per-segment verdicts)."""
    verdicts, out = [], []
    for seg in segments or []:
        text = str(seg.get("text") or "").strip()
        if not text or seg.get("start") is None or seg.get("end") is None:
            continue
        a, b = float(seg["start"]), float(seg["end"])
        row = {"start": a, "end": b, "text": text}
        if not frames:
            row["speech"] = False
            row["verdict"] = "NO_ENERGY_MEASURED"
            verdicts.append(row)
            continue
        inside = _frames(frames, a, b)
        loud = sum(1 for v in inside if v > threshold)
        is_speech = bool(inside) and loud >= max(SPEECH_MIN_SECONDS / ENERGY_HOP, SPEECH_FRAME_FRACTION * len(inside))
        row.update(speech=is_speech, loud_fraction=round(loud / max(1, len(inside)), 3),
                   verdict="SPEECH" if is_speech else "ASR_ON_NEAR_SILENCE_IGNORED")
        verdicts.append(row)
        if not is_speech:
            continue
        lo = max(0, int((a - SPEECH_SEARCH_PAD) / ENERGY_HOP))
        hi = min(len(frames), int(round((b + SPEECH_SEARCH_PAD) / ENERGY_HOP)))
        runs: list[list[float]] = []
        for i in range(lo, hi):
            if frames[i] > threshold:
                t = i * ENERGY_HOP
                if runs and t - runs[-1][1] <= SPEECH_RUN_MERGE:
                    runs[-1][1] = t + ENERGY_HOP
                else:
                    runs.append([t, t + ENERGY_HOP])
        for r0, r1 in runs or [[a, b]]:
            out.append((max(0.0, r0 - SPEECH_PAD), min(duration, r1 + SPEECH_PAD)))
    out.sort()
    merged: list[tuple[float, float]] = []
    for a, b in out:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged, verdicts


def clean_window(speech: list[tuple[float, float]], duration: float, need: float = 0.0
                 ) -> tuple[float, float]:
    """Longest window without speech; when ``need`` is longer, the ``need``-long window with the least speech."""
    gaps, cursor = [], 0.0
    for a, b in speech:
        if a > cursor:
            gaps.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < duration:
        gaps.append((cursor, duration))
    best = max(gaps, key=lambda g: g[1] - g[0], default=(0.0, 0.0))
    if need <= 0 or best[1] - best[0] >= need:
        return best
    need = min(need, duration)

    def overlap(s: float) -> float:
        return sum(max(0.0, min(b, s + need) - max(a, s)) for a, b in speech)
    starts = sorted({0.0, duration - need, *[max(0.0, min(duration - need, b)) for _, b in speech],
                     *[max(0.0, min(duration - need, a - need)) for a, _ in speech]})
    s = min(starts, key=lambda x: (round(overlap(x), 3), x))
    return (round(s, 3), round(s + need, 3))


# ------------------------------------------------------------------------------------------------------- plan
def _unit_lines(contract: dict[str, Any], grouping: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    voice_only = {str(e.get("character_id")) for e in contract.get("character_entities") or []
                  if str((e.get("identity_source") or {}).get("mode") or "") == VOICE_ONLY_MODE}
    lines_by_shot: dict[str, list[dict[str, Any]]] = {}
    for row in (contract.get("audio_contract") or {}).get("dialogue_units") or []:
        lines_by_shot.setdefault(str(row.get("shot_id") or ""), []).append(row)
    return lines_by_shot, voice_only


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def _speaking_row(row: dict[str, Any], script: list[str], first_has_line: bool, last_has_line: bool,
                  heard: list[dict[str, Any]], original: float, cjk_mode: bool) -> None:
    hit = align(script, heard, cjk_mode)
    if hit is None or hit["first"] is None:
        row.update(status="NOT_MATCHED", coverage=(hit or {}).get("coverage", 0.0))
        return
    reasons: list[str] = []
    # a later complete performance of the whole scripted text: keep the LAST one (the earlier is at the head)
    while hit["last"] + 1 < len(heard):
        again = align(script, heard, cjk_mode, lo=hit["last"] + 1)
        if not again or again["first"] is None or again["coverage"] < REPEAT_COVERAGE:
            break
        hit = again
        if "DROP_REPEAT" not in reasons:
            reasons.append("DROP_REPEAT")
    first, last = heard[hit["first"]], heard[hit["last"]]
    before, after = heard[:hit["first"]], heard[hit["last"] + 1:]
    cut_in, cut_out = 0.0, float(original)
    if before:
        cut_in = min(first["start"], max(before[-1]["end"], first["start"] - HEAD_LEAD))
        _add_reason(reasons, "DROP_REPEAT" if _resembles_script([h["tok"] for h in before], script)
                    else "TRIM_HEAD_UNSCRIPTED")
    elif first_has_line:
        cut_in = max(0.0, first["start"] - HEAD_LEAD)
        if cut_in >= MIN_CUT_SECONDS:
            reasons.append("TRIM_HEAD_TO_LINE")
    if after:
        cut_out = max(last["end"], min(last["end"] + TAIL_PAD, after[0]["start"] - SPEECH_GAP))
        _add_reason(reasons, "DROP_REPEAT" if _resembles_script([h["tok"] for h in after], script)
                    else "TRIM_TAIL_UNSCRIPTED")
    elif last_has_line:
        cut_out = min(float(original), last["end"] + TAIL_PAD)
        if float(original) - cut_out >= MIN_CUT_SECONDS:
            reasons.append("TRIM_TAIL_TO_LINE")
    cut_in, cut_out = max(0.0, cut_in), min(float(original), cut_out)
    row.update(status="MATCHED", coverage=hit["coverage"], line_start_seconds=round(first["start"], 3),
               line_end_seconds=round(last["end"], 3),
               kept_text="".join(h["tok"] if cjk_mode else h["tok"] + " " for h in heard[hit["first"]:hit["last"] + 1]).strip(),
               removed_head_text=("" if cjk_mode else " ").join(h["tok"] for h in before),
               removed_tail_text=("" if cjk_mode else " ").join(h["tok"] for h in after))
    if cut_out - cut_in < MIN_KEEP_SECONDS:
        centre = (first["start"] + last["end"]) / 2.0
        cut_in = max(0.0, min(float(original) - MIN_KEEP_SECONDS, centre - MIN_KEEP_SECONDS / 2.0))
        cut_out = min(float(original), cut_in + MIN_KEEP_SECONDS)
        reasons.append("MIN_LENGTH_HOLD")
    row.update(after_in=round(cut_in, 3), after_out=round(cut_out, 3), reasons=reasons)


def plan(contract: dict[str, Any], grouping: dict[str, Any], unit_asr: dict[str, Any],
         clip_seconds: dict[str, float], unit_energy: dict[str, list[float]] | None = None,
         tail_report: dict[str, Any] | None = None, head_report: dict[str, Any] | None = None,
         vo_seconds: dict[str, list[float]] | None = None) -> dict[str, Any]:
    """Per-unit performance cut: rows {unit_id, kind, before_in/out (the earlier head/tail plan), after_in/out,
    reasons, warnings}.  ``vo_seconds``: unit -> durations of the V.O. lines it carries (S4 manifest)."""
    language = str(contract.get("dialogue_language") or "zh").lower()
    lines_by_shot, voice_only = _unit_lines(contract, grouping)
    energy = unit_energy or {}
    tail = {str(r.get("unit_id")): r for r in (tail_report or {}).get("units") or []}
    head = {str(r.get("unit_id")): r for r in (head_report or {}).get("units") or []}
    rows: list[dict[str, Any]] = []
    speaking: dict[str, dict[str, Any]] = {}
    for unit in grouping.get("units") or []:
        uid = str(unit.get("unit_id"))
        shot_ids = [str(s) for s in unit.get("editorial_shot_ids") or []]
        original = clip_seconds.get(uid)
        t, h = tail.get(uid) or {}, head.get(uid) or {}
        before_out = float(t["kept_seconds"]) if t.get("trimmed") and t.get("kept_seconds") else original
        before_in = float(h["head_cut_seconds"]) if h.get("trimmed") else 0.0
        row: dict[str, Any] = {"unit_id": uid, "original_seconds": original, "before_in": before_in,
                               "before_out": before_out, "after_in": before_in, "after_out": before_out,
                               "reasons": [], "warnings": []}
        rows.append(row)
        if not original or original <= 0:
            row.update(kind="UNKNOWN", status="CLIP_DURATION_UNKNOWN")
            continue
        on_screen = {sid: [ln for ln in lines_by_shot.get(sid, []) if str(ln.get("speaker_id") or "") not in voice_only]
                     for sid in shot_ids}
        texts = [str(ln.get("text") or "") for sid in shot_ids for ln in on_screen[sid]]
        joined = "".join(texts)
        cjk_mode = language.startswith("zh") or (bool(re.search(r"[一-鿿]", joined))
                                                 and not re.search(r"[A-Za-z]", joined))
        if texts:
            row["kind"] = "SPEAKING"
            row["expected_text"] = " / ".join(texts)
            script = script_tokens(texts, cjk_mode)
            heard = heard_tokens(unit_asr.get(uid) or [], cjk_mode)
            if not heard:
                row["status"] = "NO_ASR_WORDS"
                continue
            _speaking_row(row, script, bool(on_screen[shot_ids[0]]), bool(on_screen[shot_ids[-1]]), heard,
                          float(original), cjk_mode)
            if row.get("status") == "MATCHED":
                speaking[uid] = row
        else:
            row["kind"] = "SILENT"
            row["vo_seconds"] = list((vo_seconds or {}).get(uid) or [])
    # speech level of this episode's own scripted performances -> the energy gate for silent units
    level = episode_speech_level([(energy[uid], r["line_start_seconds"], r["line_end_seconds"])
                                  for uid, r in speaking.items() if energy.get(uid)])
    threshold = speech_threshold(level)
    for row in rows:
        if row.get("kind") != "SILENT":
            continue
        uid, original = row["unit_id"], float(row["original_seconds"])
        speech, verdicts = speech_intervals(unit_asr.get(uid) or [], energy.get(uid), threshold, original)
        row["asr_segments"] = verdicts
        row["speech_intervals"] = [[round(a, 3), round(b, 3)] for a, b in speech]
        if not speech:
            row["status"] = "NO_SPEECH" if not verdicts else "ASR_HALLUCINATION_IGNORED"
            continue
        a, b = clean_window(speech, original)
        reasons = ["SILENT_SPEECH_WINDOW"]
        if b - a < MIN_KEEP_SECONDS:
            a, b = clean_window(speech, original, MIN_KEEP_SECONDS)
            reasons.append("MIN_LENGTH_HOLD")
        row.update(status="SPEECH_CUT", after_in=round(a, 3), after_out=round(b, 3), reasons=reasons,
                   clean_window_seconds=round(b - a, 3))
    _vo_guard(rows, speaking)
    for row in rows:
        orig = row.get("original_seconds") or 0.0
        if row["reasons"]:
            if row["after_in"] < MIN_CUT_SECONDS:
                row["after_in"] = 0.0
            if orig - row["after_out"] < MIN_CUT_SECONDS:
                row["after_out"] = orig
        row["changed"] = bool(row["reasons"]) and (abs(row["after_in"] - (row["before_in"] or 0.0)) > 1e-6
                                                   or abs(row["after_out"] - (row["before_out"] or 0.0)) > 1e-6)
        row["kept_seconds"] = round(row["after_out"] - row["after_in"], 3) if orig else None
        if "MIN_LENGTH_HOLD" in row["reasons"]:
            row["warnings"].append(
                f"MIN_LENGTH_HOLD:{row['unit_id']}:kept {MIN_KEEP_SECONDS:g} s around the "
                + ("line" if row.get("kind") == "SPEAKING" else "cleanest window")
                + " -- unscripted speech may still be audible; consider a redo")
    before_total = round(sum(float(r["before_out"] or 0) - float(r["before_in"] or 0) for r in rows), 3)
    after_total = round(sum(float(r["after_out"] or 0) - float(r["after_in"] or 0) for r in rows), 3)
    return {"schema": SCHEMA, "episode": contract.get("episode"),
            "rule": {"head_lead_seconds": HEAD_LEAD, "tail_pad_seconds": TAIL_PAD, "speech_gap_seconds": SPEECH_GAP,
                     "min_keep_seconds": MIN_KEEP_SECONDS, "match_coverage": MATCH_COVERAGE,
                     "repeat_coverage": REPEAT_COVERAGE, "reasons": list(REASONS)},
            "speech_level_dbfs": level, "speech_threshold_dbfs": threshold,
            "changed_units": sum(1 for r in rows if r["changed"]),
            "before_total_seconds": before_total, "after_total_seconds": after_total,
            "removed_seconds": round(before_total - after_total, 3),
            "warnings": [w for r in rows for w in r["warnings"]], "units": rows}


def _vo_guard(rows: list[dict[str, Any]], speaking: dict[str, dict[str, Any]]) -> None:
    """V.O. lines are placed from their unit's start and cascade (tools/voice_over_narration.place); a silent unit
    shortened under its V.O. pushes the narration into the next units.  When that cascade would reach in-video
    dialogue, the V.O. unit keeps at least what its own V.O. needs (least-speech window of that length)."""
    def simulate() -> bool:
        start, prev_end = 0.0, None
        for row in rows:
            dur = float(row["after_out"] or 0) - float(row["after_in"] or 0)
            if row["unit_id"] in speaking:
                r = speaking[row["unit_id"]]
                s0 = start + max(0.0, r["line_start_seconds"] - row["after_in"])
                if prev_end is not None and prev_end > s0:
                    return False
            for i, sec in enumerate(row.get("vo_seconds") or []):
                t = start + VO_LEAD_IN if i == 0 else prev_end + VO_LINE_GAP
                if prev_end is not None:
                    t = max(t, prev_end + VO_SEPARATION)
                prev_end = t + float(sec)
            start += dur
        return prev_end is None or prev_end <= start + 1e-6

    if simulate():
        return
    for row in rows:
        if row.get("kind") == "SILENT" and row.get("vo_seconds") and row["reasons"]:
            vo = row["vo_seconds"]
            need = VO_LEAD_IN + sum(vo) + VO_LINE_GAP * (len(vo) - 1) + VO_SEPARATION
            if row["after_out"] - row["after_in"] < need:
                speech = [tuple(x) for x in row.get("speech_intervals") or []]
                a, b = clean_window(speech, float(row["original_seconds"]), need)
                row.update(after_in=a, after_out=b)
                row["warnings"].append(f"VO_HOLD:{row['unit_id']}:kept {b - a:.2f} s for its V.O.; "
                                       "on-screen speech may remain under the narration")


# ------------------------------------------------------------------------------------------------ apply
def merge(tail_report: dict[str, Any], head_report: dict[str, Any], report: dict[str, Any]
          ) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write the performance-cut in/out points into the tail/head trim reports (the AgentCut build's inputs)."""
    rows = {r["unit_id"]: r for r in report.get("units") or [] if r.get("reasons")}
    tail = {**tail_report, "units": [dict(r) for r in tail_report.get("units") or []]}
    head = {**head_report, "units": [dict(r) for r in head_report.get("units") or []]}
    for t in tail["units"]:
        row = rows.get(str(t.get("unit_id")))
        if row is None:
            continue
        orig = float(row["original_seconds"])
        out = float(row["after_out"])
        cut = orig - out >= MIN_CUT_SECONDS
        t.update(trimmed=cut, kept_seconds=round(out if cut else orig, 3),
                 trimmed_seconds=round(orig - out, 3) if cut else 0.0,
                 line_end_seconds=row.get("line_end_seconds", round(out, 3)),
                 reason="PERFORMANCE_CUT:" + "+".join(row["reasons"]) if cut else t.get("reason"),
                 performance_cut=True)
    for h in head["units"]:
        row = rows.get(str(h.get("unit_id")))
        if row is None:
            continue
        a = float(row["after_in"])
        cut = a >= MIN_CUT_SECONDS
        h.update(trimmed=cut, head_cut_seconds=round(a if cut else 0.0, 3),
                 kept_seconds=round(float(row["after_out"]) - (a if cut else 0.0), 3),
                 reason="PERFORMANCE_CUT:" + "+".join(row["reasons"]) if cut else h.get("reason"),
                 performance_cut=True)
    for rep in (tail, head):
        trimmed = [r for r in rep["units"] if r.get("trimmed")]
        rep["trimmed_units"] = len(trimmed)
        rep["performance_cut"] = report.get("schema")
    tail["removed_seconds"] = round(sum(float(r.get("trimmed_seconds") or 0) for r in tail["units"] if r.get("trimmed")), 3)
    head["removed_seconds"] = round(sum(float(r.get("head_cut_seconds") or 0) for r in head["units"] if r.get("trimmed")), 3)
    return tail, head


def windows(tail_report: dict[str, Any], head_report: dict[str, Any], clip_seconds: dict[str, float]
            ) -> dict[str, tuple[float, float]]:
    """unit -> (source in, source out) after the merged head/tail reports."""
    tail = {str(r.get("unit_id")): r for r in tail_report.get("units") or []}
    head = {str(r.get("unit_id")): r for r in head_report.get("units") or []}
    out = {}
    for uid, seconds in clip_seconds.items():
        end = float(seconds or 0.0)
        t = tail.get(uid) or {}
        if t.get("trimmed") and t.get("kept_seconds"):
            end = min(end, float(t["kept_seconds"])) if end else float(t["kept_seconds"])
        h = head.get(uid) or {}
        out[uid] = (float(h["head_cut_seconds"]) if h.get("trimmed") else 0.0, end)
    return out


def cut_unit_asr(unit_asr: dict[str, Any], cut: dict[str, tuple[float, float]],
                 report: dict[str, Any] | None = None) -> dict[str, Any]:
    """Unit ASR in SOURCE seconds with everything outside each unit's kept window removed (segments rebuilt from
    their kept words; speech the performance cut classified as unscripted dropped).  The S7 consumers (captions,
    V.O. windows, sound bridge, burst mute) map source seconds through the clip in-point themselves."""
    rows = {r["unit_id"]: r for r in (report or {}).get("units") or []}
    out: dict[str, Any] = {}
    for uid, segs in unit_asr.items():
        a, b = cut.get(uid, (0.0, float("inf")))
        row = rows.get(uid) or {}
        if row.get("kind") == "SILENT" and row.get("reasons"):
            out[uid] = []  # the speech was cut away; nothing in the kept window is a line
            continue
        line_end = row.get("line_end_seconds") if row.get("reasons") else None
        lo = a - 1e-6
        hi = min(b, float(line_end) + TAIL_PAD) if line_end is not None else b
        kept = []
        for seg in segs or []:
            s0, s1 = float(seg.get("start") or 0.0), float(seg.get("end") or 0.0)
            words = seg.get("words")
            if words:
                inside = [w for w in words if w.get("start") is not None
                          and float(w["start"]) >= lo and float(w["start"]) < hi]
                if not inside:
                    continue
                if len(inside) == len(words):
                    kept.append(dict(seg, start=max(s0, a), end=min(s1, b)))
                    continue
                kept.append(dict(seg, text="".join(str(w.get("word") or "") for w in inside).strip(),
                                 start=round(max(a, float(inside[0]["start"])), 3),
                                 end=round(min(b, float(inside[-1]["end"])), 3), words=inside))
            elif s1 > a and s0 < hi:
                kept.append(dict(seg, start=max(s0, a), end=min(s1, b)))
        out[uid] = kept
    return out


def shift_to_cut(unit_asr: dict[str, Any], cut: dict[str, tuple[float, float]]) -> dict[str, Any]:
    """Source-second ASR -> seconds from each unit's cut in-point (the unit audio levelling convention)."""
    out = {}
    for uid, segs in (unit_asr or {}).items():
        a = cut.get(uid, (0.0, 0.0))[0]
        out[uid] = [dict(s, start=round(max(0.0, float(s["start"]) - a), 3), end=round(float(s["end"]) - a, 3))
                    for s in segs or [] if float(s.get("end") or 0) > a]
    return out
