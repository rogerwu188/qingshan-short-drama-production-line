#!/usr/bin/env python3
"""Must-check defect list of the final audience review (line owner 2026-11-19, after watching published episodes of
《摄政王她又来找茬了》 on device …0841).

The independent final reviewer is asked SPECIFICALLY, with timestamps, about six defects the owner saw on screen:

  QA-BURNED-TEXT          model-burned text or subtitles inside the picture (a stray big 「能」 under our subtitle)
  QA-DIALOGUE-TAIL-CUT    a line's last syllable cut off at a cut, or no natural pause after a line ends
  QA-OVERSIZED-MASK       an oversized blur / cover box over the picture (S7 text cover gone wrong)
  QA-LOOKALIKE-CAST       two different characters who look alike
  QA-SUBTITLE-WRAP        our subtitle wrapping badly (a lone 「！」 on its own line)
  QA-BGM-DISCONTINUOUS    music that plays for a shot or two and stops, or starts / stops abruptly at a cut

Where the engine can measure something for free, the reviewer gets the measurement (``measure``): OCR hits from the
S7 burned-text scan / verify, the gap between each line's ASR end and the next cut, the cover-band area per burned
run, the S3 cross-character similarity, the wrapped rows of every caption (from the burned ASS file) and the music
segments of the S7 BGM plan / audio-bed report.  Every input is READ ONLY (the S7 subtitle, mask, trim and BGM code is
owned elsewhere); a missing file just leaves its measurement out.

Authority: ADVISORY.  Nothing here changes the review's validity, verdict or exit code -- the answer block
``qa_defect_checklist`` is optional and parsed leniently, like ``craft_standard``.  Findings are recorded with
timestamps (``<EP>_QA_DEFECT_CHECKLIST.json``), as ``QA_DEFECT|<item id>`` knowledge events, and listed in the S8
owner-approval checkpoint.  Routing: S7-fixable items (tail cut, mask, wrap, BGM, burned text when maskable) have no
cheap automatic re-cut hook in S7 today (``s7_unit_recut`` renders an AUTHORED plan only), so they are recorded and
surfaced to the owner before approval; QA-LOOKALIKE-CAST feeds the knowledge base and the next episode's identity
design (character_distinctness).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "nalu.qa_defect_checklist.v1"
BLOCK_SCHEMA = "nalu.qa_defect_checklist_review.v1"
FAILURE_TYPE = "QA_DEFECT"
AUTHORITY = "OPTIONAL_ADVISORY_NOT_A_GATE: a missing or malformed block never changes the review"
VERDICTS = ("PASS", "DEFECT", "NA")

#: id -> (zh title, reviewer question, S7-fixable, owner of the fix, related craft-standard item)
ITEMS: dict[str, dict[str, Any]] = {
    "QA-BURNED-TEXT": {
        "title_zh": "画面里模型烧进去的文字/字幕（如字幕下方多出一个大字「能」）",
        "question": "Is there any text or subtitle burned into the PICTURE by the video model (not our caption): stray "
                    "glyphs, a second subtitle line, a big single character under or over our caption?  Give each "
                    "timestamp.  Use measurements.burned_text (OCR hits) as leads, confirm by eye.",
        "s7_fixable": "WHEN_MASKABLE", "fix_owner": "S7", "craft_item": "C-04"},
    "QA-DIALOGUE-TAIL-CUT": {
        "title_zh": "台词尾音被剪断，或句末没有自然停顿就切走",
        "question": "Is any line's last syllable cut off mid-word at a cut, or does a cut land with no natural pause "
                    "after a line ends?  Give each timestamp.  measurements.dialogue_tail lists every line whose ASR "
                    "end is within 0.25 s of the next cut.",
        "s7_fixable": True, "fix_owner": "S7", "craft_item": "C-08"},
    "QA-OVERSIZED-MASK": {
        "title_zh": "遮挡/模糊框过大，盖住画面（S7 文字遮盖出错）",
        "question": "Is any blur or dark cover box larger than the caption area, covering faces, hands or the action "
                    "(the S7 burned-text cover gone wrong)?  Give each timestamp.  measurements.masks lists the "
                    "cover band of every burned-text run with its share of the frame.",
        "s7_fixable": True, "fix_owner": "S7", "craft_item": "C-13"},
    "QA-LOOKALIKE-CAST": {
        "title_zh": "两个不同角色长得几乎一样",
        "question": "Do two DIFFERENT characters look alike (same face: jaw, nose, eyes, smile) so a viewer could "
                    "confuse them?  Name the shots (timestamps) where each appears.  measurements.lookalike_cast is "
                    "the S3 face-embedding similarity of the identity cards (>= 0.38 = not separable).",
        "s7_fixable": False, "fix_owner": "engine", "craft_item": "C-12"},
    "QA-SUBTITLE-WRAP": {
        "title_zh": "我们的字幕换行不当（如「！」单独成行）",
        "question": "Does any of OUR captions wrap badly: a lone punctuation mark or a single character on its own "
                    "row, a word split across rows, more than two rows?  Give each timestamp.  "
                    "measurements.subtitle_wrap lists the wrapped rows the engine drew.",
        "s7_fixable": True, "fix_owner": "S7", "craft_item": "S-08"},
    "QA-BGM-DISCONTINUOUS": {
        "title_zh": "配乐断续：只响一两个镜头就停，或在切点生硬起停",
        "question": "Does background music play for only one or two shots and then stop, or start / stop abruptly "
                    "at a cut (no fade)?  Give each timestamp.  measurements.bgm lists the measured music segments "
                    "(start, end, duration, fades) and the flagged runs / edges.",
        "s7_fixable": True, "fix_owner": "S7", "craft_item": "C-16"},
}
ITEM_IDS = tuple(ITEMS)

# measurement thresholds (advisory flags handed to the reviewer, never verdicts)
TAIL_CLIPPED_S = 0.08        # line end within 80 ms of the cut (or past it): the last syllable is likely clipped
TAIL_NO_PAUSE_S = 0.25       # < 250 ms between the line's end and the cut: no natural pause
#: the caption band of the burned-text cover policy is 0.88 x 0.15 = 0.13 of the frame; a cover over 20 % of the
#: frame or taller than 20 % of its height is larger than any caption needs
OVERSIZED_MASK_AREA = 0.20
OVERSIZED_MASK_HEIGHT = 0.20
BGM_SHORT_RUN_S = 8.0        # a music run shorter than ~2 shots
BGM_ABRUPT_FADE_S = 0.30     # an edge with less fade than this ...
BGM_EDGE_AT_CUT_S = 0.15     # ... within this of a cut is "abrupt at a cut"
BGM_MERGE_GAP_S = 0.30       # segments closer than this are one continuous run
LONE_ROW_RE = re.compile(r"^[\s，。！？；：、,.!?;:…—\-「」『』“”\"'()（）]*$")


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _read(path: Any) -> Any:
    try:
        return json.loads(Path(str(path)).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _cuts(shots: list[dict[str, Any]]) -> list[float]:
    return sorted({round(float(s["end_seconds"]), 3) for s in shots or [] if _num(s.get("end_seconds")) is not None})


# --------------------------------------------------------------------------- measurements
def measure_burned_text(scan: Any, verify: Any) -> dict[str, Any]:
    """OCR hits per timestamp from the S7 burned-text scan (runs it covered) and verify (text still readable)."""
    out: dict[str, Any] = {"source": "S7 burned_text_cover scan/verify (read only)"}
    if isinstance(verify, dict):
        rows = []
        for key, kind in (("text_outside_bar", "OUTSIDE_CAPTION_BAR"),
                          ("text_inside_bar_not_the_caption", "INSIDE_BAR_NOT_OUR_CAPTION")):
            for row in verify.get(key) or []:
                if isinstance(row, dict):
                    rows.append({"t": row.get("t"), "kind": kind, "chars": len(str(row.get("text") or "")),
                                 "text": str(row.get("text") or "")[:12], "box": row.get("box")})
        out["verify_status"] = verify.get("status")
        out["hits"] = sorted(rows, key=lambda r: _num(r.get("t")) or 0.0)[:40]
    if isinstance(scan, dict):
        out["covered_runs"] = [[_num(a), _num(b)] for a, b in (scan.get("intervals") or [])][:40]
        out["covered_seconds"] = scan.get("seconds")
    return out if len(out) > 1 else {}


def measure_masks(scan: Any) -> dict[str, Any]:
    """Cover band per burned-text run (as a share of the frame) -- the S7 mask report, read only."""
    if not isinstance(scan, dict):
        return {}
    intervals, bands = scan.get("intervals") or [], scan.get("bands") or []
    rows = []
    for (start, end), band in zip(intervals, bands):
        if not isinstance(band, dict):
            continue
        w = max(0.0, float(band.get("x1", 0)) - float(band.get("x0", 0)))
        h = max(0.0, float(band.get("y1", 0)) - float(band.get("y0", 0)))
        area = round(w * h, 4)
        rows.append({"start": _num(start), "end": _num(end), "band": band, "area_frac": area,
                     "height_frac": round(h, 4),
                     "oversized": area > OVERSIZED_MASK_AREA or h > OVERSIZED_MASK_HEIGHT})
    return {"source": "S7 burned_text_cover scan bands (read only)", "runs": rows[:40],
            "oversized": [r for r in rows if r["oversized"]][:20],
            "thresholds": {"area_frac": OVERSIZED_MASK_AREA, "height_frac": OVERSIZED_MASK_HEIGHT}}


def measure_dialogue_tail(asr: Any, shots: list[dict[str, Any]]) -> dict[str, Any]:
    """For every final-cut ASR line window: the gap between its end and the next cut of the decoded final MP4."""
    rows_in = asr if isinstance(asr, list) else ((asr or {}).get("segments") or (asr or {}).get("windows") or []
                                                 if isinstance(asr, dict) else [])
    cuts = _cuts(shots)
    if not rows_in or not cuts:
        return {}
    rows = []
    for row in rows_in:
        if not isinstance(row, dict) or str(row.get("presence") or "") == "VOICE_OVER":
            continue
        start, end = _num(row.get("start")), _num(row.get("end"))
        if start is None or end is None:
            continue
        nxt = next((c for c in cuts if c >= end - 0.02), None)
        if nxt is None:
            continue
        gap = round(nxt - end, 3)
        flag = "LIKELY_CLIPPED" if gap < TAIL_CLIPPED_S else "NO_PAUSE" if gap < TAIL_NO_PAUSE_S else None
        rows.append({"line_start": round(start, 3), "line_end": round(end, 3), "next_cut": nxt,
                     "gap_seconds": gap, "unit_id": row.get("unit_id"), **({"flag": flag} if flag else {})})
    flagged = [r for r in rows if r.get("flag")]
    return {"source": "final-cut ASR windows vs measured shot cuts", "lines": len(rows), "flagged": flagged[:40],
            "thresholds": {"likely_clipped_s": TAIL_CLIPPED_S, "no_pause_s": TAIL_NO_PAUSE_S}}


_ASS_TIME = re.compile(r"(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")


def _ass_seconds(value: str) -> float | None:
    m = _ASS_TIME.fullmatch(value.strip())
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else None


def measure_subtitle_wrap(ass_text: str | None) -> dict[str, Any]:
    """The wrapped rows of every caption the engine drew (``\\N`` in the burned ASS file): a lone punctuation row,
    a one-character row or more than two rows are flagged."""
    if not ass_text:
        return {}
    rows, flagged = 0, []
    for line in ass_text.splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        start, end = _ass_seconds(parts[1]), _ass_seconds(parts[2])
        text = re.sub(r"\{[^}]*\}", "", parts[9])
        wrapped = [r for r in text.split("\\N")]
        rows += 1
        reasons = []
        if len(wrapped) > 1 and any(LONE_ROW_RE.match(r) for r in wrapped):
            reasons.append("LONE_PUNCTUATION_ROW")
        if len(wrapped) > 1 and any(len(r.strip()) == 1 and not LONE_ROW_RE.match(r) for r in wrapped):
            reasons.append("ONE_CHARACTER_ROW")
        if len(wrapped) > 2:
            reasons.append("MORE_THAN_TWO_ROWS")
        if reasons:
            flagged.append({"start": start, "end": end, "rows": wrapped, "reasons": reasons})
    return {"source": "burned subtitle ASS (read only)", "captions": rows, "flagged": flagged[:40]}


def measure_bgm(plan: Any, bed: Any, shots: list[dict[str, Any]]) -> dict[str, Any]:
    """Music segments of the S7 BGM plan (paid cues) and the audio-bed report (pad regions), read only: each with
    start, end, duration and fades; contiguous segments merged into runs; runs shorter than BGM_SHORT_RUN_S and
    run edges with < BGM_ABRUPT_FADE_S of fade landing within BGM_EDGE_AT_CUT_S of a cut are flagged."""
    segments = []
    for cue in ((plan or {}).get("cues") or []) if isinstance(plan, dict) else []:
        start, dur = _num(cue.get("timeline_start")), _num(cue.get("duration"))
        if start is None or dur is None or dur <= 0:
            continue
        segments.append({"kind": "CUE", "id": cue.get("cue_id"), "start": round(start, 3),
                         "end": round(start + dur, 3), "duration": round(dur, 3),
                         "fade_in_s": _num(cue.get("fade_in_s")), "fade_out_s": _num(cue.get("fade_out_s"))})
    if isinstance(bed, dict):
        pad_fade = _num(((bed.get("params") or {}).get("pad_edge_fade_s")))
        for region in bed.get("pad_regions") or []:
            start, end = _num(region.get("start")), _num(region.get("end"))
            if start is None or end is None or end <= start:
                continue
            segments.append({"kind": "PAD", "id": region.get("before_cue") or region.get("after_cue"),
                             "start": round(start, 3), "end": round(end, 3), "duration": round(end - start, 3),
                             "fade_in_s": pad_fade, "fade_out_s": pad_fade})
        mode = (bed.get("params") or {}).get("music_mode")
    else:
        mode = None
    if not segments:
        return {}
    segments.sort(key=lambda s: s["start"])
    runs: list[dict[str, Any]] = []
    for seg in segments:
        if runs and seg["start"] - runs[-1]["end"] <= BGM_MERGE_GAP_S:
            runs[-1]["end"] = max(runs[-1]["end"], seg["end"])
            runs[-1]["fade_out_s"] = seg["fade_out_s"]
            runs[-1]["segments"] += 1
        else:
            runs.append({"start": seg["start"], "end": seg["end"], "fade_in_s": seg["fade_in_s"],
                         "fade_out_s": seg["fade_out_s"], "segments": 1})
    cuts = _cuts(shots)
    duration_end = max((float(s.get("end_seconds") or 0) for s in shots or []), default=None)
    flagged = []
    for run in runs:
        run["duration"] = round(run["end"] - run["start"], 3)
        reasons = []
        if run["duration"] < BGM_SHORT_RUN_S:
            reasons.append("SHORT_RUN")
        for edge, fade_key, label in ((run["start"], "fade_in_s", "ABRUPT_START_AT_CUT"),
                                      (run["end"], "fade_out_s", "ABRUPT_STOP_AT_CUT")):
            fade = run.get(fade_key)
            at_cut = any(abs(edge - c) <= BGM_EDGE_AT_CUT_S for c in cuts)
            at_film_edge = edge <= 0.05 or (duration_end is not None and edge >= duration_end - 0.05)
            if at_cut and not at_film_edge and (fade is None or fade < BGM_ABRUPT_FADE_S):
                reasons.append(label)
        if reasons:
            flagged.append({**run, "reasons": reasons})
    return {"source": "S7 BGM plan cues + audio-bed pad regions (read only)", "music_mode": mode,
            "segments": segments[:40], "runs": runs[:40], "flagged": flagged[:20],
            "thresholds": {"short_run_s": BGM_SHORT_RUN_S, "abrupt_fade_s": BGM_ABRUPT_FADE_S,
                           "edge_at_cut_s": BGM_EDGE_AT_CUT_S}}


def measure_lookalike(report: Any) -> dict[str, Any]:
    """The S3 cross-character similarity (character_distinctness report)."""
    if not isinstance(report, dict) or not report:
        return {}
    pairs = [{k: r.get(k) for k in ("a", "b", "cosine")} for r in (report.get("pairs") or [])[:12]]
    out = {"source": "S3 identity cards, InsightFace cosine between different characters",
           "method": report.get("method"), "threshold": report.get("threshold"), "status": report.get("status"),
           "pairs": pairs, "too_similar": [{k: r.get(k) for k in ("a", "b", "cosine")}
                                           for r in report.get("too_similar") or []],
           "advisories": report.get("advisories") or []}
    if report.get("method") and "ANIME" in str(report.get("method")):
        out["answers"] = report.get("answers") or []
    return out


def measure_s6_burn_unresolved(state: Any) -> dict[str, Any]:
    """Units whose S6 burned-text retries (h3_burn_retry, line owner 2026-11-19) did not clear the burn: the kept
    take still carries model-burned text.  Read only from the S6 wave state ``s6_burn_retry``; {} when none."""
    rows = []
    for uid, rec in sorted(((state or {}).get("s6_burn_retry") or {}).items()):
        if not isinstance(rec, dict) or not rec.get("burned_text_unresolved"):
            continue
        rows.append({"unit_id": uid, "reason": rec.get("unresolved_reason"),
                     "retries": len(rec.get("attempts") or []),
                     "kept_take_burned_frames": rec.get("kept_take_burned_frames"),
                     "kept_take_sha256": rec.get("kept_take_sha256")})
    return {"source": "S6 wave state s6_burn_retry (read only)", "units": rows} if rows else {}


def measure(*, shots: list[dict[str, Any]], asr: Any = None, scan_path: Any = None, verify_path: Any = None,
            ass_path: Any = None, distinctness_path: Any = None, bgm_plan_path: Any = None,
            audio_bed_path: Any = None, s6_wave_state_path: Any = None) -> dict[str, Any]:
    """All free measurements, each best-effort ({} when its input is missing).  Never raises."""
    out: dict[str, Any] = {}
    steps = (
        ("burned_text", lambda: measure_burned_text(_read(scan_path), _read(verify_path))),
        ("masks", lambda: measure_masks(_read(scan_path))),
        ("dialogue_tail", lambda: measure_dialogue_tail(asr, shots)),
        ("subtitle_wrap", lambda: measure_subtitle_wrap(
            Path(str(ass_path)).read_text(encoding="utf-8") if ass_path and Path(str(ass_path)).is_file() else None)),
        ("lookalike_cast", lambda: measure_lookalike(_read(distinctness_path))),
        ("bgm", lambda: measure_bgm(_read(bgm_plan_path), _read(audio_bed_path), shots)),
        ("s6_burn_unresolved", lambda: measure_s6_burn_unresolved(_read(s6_wave_state_path))),
    )
    for key, fn in steps:
        try:
            value = fn()
        except Exception as exc:  # noqa: BLE001 -- advisory measurement
            value = {"error": f"{type(exc).__name__}:{str(exc)[:120]}"}
        if value:
            out[key] = value
    return out


#: measurement key -> item id
MEASUREMENT_ITEM = {"burned_text": "QA-BURNED-TEXT", "masks": "QA-OVERSIZED-MASK",
                    "dialogue_tail": "QA-DIALOGUE-TAIL-CUT", "subtitle_wrap": "QA-SUBTITLE-WRAP",
                    "lookalike_cast": "QA-LOOKALIKE-CAST", "bgm": "QA-BGM-DISCONTINUOUS",
                    "s6_burn_unresolved": "QA-BURNED-TEXT"}


def reviewer_request(measurements: dict[str, Any]) -> dict[str, Any]:
    """The ``qa_defect_checklist_request`` block of the final-audience request."""
    return {
        "authority": AUTHORITY,
        "instruction": (
            "MUST-CHECK (line owner 2026-11-19): in the same viewing passes, check each item below SPECIFICALLY and "
            "fill the optional answer block qa_defect_checklist: items {item id: {verdict PASS|DEFECT|NA, findings "
            "[{at_seconds or window [a, b], note}]}}.  Every DEFECT needs at least one timestamp.  The numbers in "
            "measurements were measured on this cut for free: use them as leads and confirm or reject them by eye / "
            "ear; a measured flag you could not see or hear is PASS with a note.  Also list a confirmed defect in "
            "problems with its severity (P0-P3) as usual."),
        "items": [{"id": iid, "title_zh": row["title_zh"], "question": row["question"],
                   "s7_fixable": row["s7_fixable"], "craft_item": row["craft_item"]} for iid, row in ITEMS.items()],
        "measurements": measurements,
        "answer_block": {"items": {iid: {"verdict": "PASS|DEFECT|NA",
                                         "findings": [{"at_seconds": 0.0, "note": "what, where"}]}
                                   for iid in ITEM_IDS}},
    }


# --------------------------------------------------------------------------- lenient parse + findings
def _clean(value: Any, limit: int = 200) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _normalise_id(value: Any) -> str | None:
    key = re.sub(r"[^A-Z]+", "-", str(value or "").upper()).strip("-")
    key = key if key.startswith("QA-") else f"QA-{key}"
    return key if key in ITEMS else None


def parse_block(block: Any, *, duration: float | None = None) -> dict[str, Any]:
    """Lenient: keep what is well formed, drop the rest with a note.  Never raises."""
    out: dict[str, Any] = {"schema": BLOCK_SCHEMA, "notes": [], "items": {}}
    if block is None:
        return {**out, "status": "MISSING"}
    if not isinstance(block, dict):
        return {**out, "status": "MALFORMED", "notes": [f"block_not_object:{type(block).__name__}"]}
    raw = block.get("items") if isinstance(block.get("items"), dict) else block
    verification = block.get("gemini_verification")
    if isinstance(verification, list):
        out["gemini_verification"] = {}
        for row in verification:
            if not isinstance(row, dict) or not re.fullmatch(r"[GS]\d{1,3}", str(row.get("id") or "")):
                continue
            decision = _clean(row.get("decision"), 12).upper()
            out["gemini_verification"][str(row["id"])] = {
                "decision": decision if decision in ("CONFIRMED", "DISMISSED") else "UNSURE",
                "reason": _clean(row.get("reason"))}
    for key, row in (raw or {}).items():
        if key == "gemini_verification":
            continue
        iid = _normalise_id(key)
        if iid is None:
            out["notes"].append(f"unknown_item:{_clean(key, 30)}")
            continue
        row = row if isinstance(row, dict) else {"verdict": row}
        verdict = _clean(row.get("verdict"), 10).upper()
        if verdict not in VERDICTS:
            out["notes"].append(f"{iid}:invalid_verdict")
            continue
        findings = []
        for pos, f in enumerate(row.get("findings") if isinstance(row.get("findings"), list) else []):
            if not isinstance(f, dict):
                continue
            entry: dict[str, Any] = {"note": _clean(f.get("note") or f.get("issue"))}
            at = _num(f.get("at_seconds") if f.get("at_seconds") is not None else f.get("t"))
            if at is not None and at >= 0 and (not duration or at <= duration + 0.5):
                entry["at_seconds"] = round(at, 3)
            window = f.get("window")
            if isinstance(window, (list, tuple)) and len(window) == 2:
                a, b = _num(window[0]), _num(window[1])
                if a is not None and b is not None and 0 <= a <= b:
                    entry["window"] = [round(a, 3), round(b, 3)]
            if "at_seconds" not in entry and "window" not in entry:
                out["notes"].append(f"{iid}.findings.{pos}:no_timestamp")
            findings.append(entry)
        if verdict == "DEFECT" and not any("at_seconds" in f or "window" in f for f in findings):
            out["notes"].append(f"{iid}:defect_without_timestamp")
        out["items"][iid] = {"verdict": verdict, "findings": findings[:12]}
    out["status"] = "OK" if not out["notes"] else "PARTIAL"
    return out


def _measured_findings(measurements: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for row in (measurements.get("burned_text") or {}).get("hits") or []:
        out.append({"item_id": "QA-BURNED-TEXT", "at_seconds": _num(row.get("t")), "source": "MEASURED",
                    "detail": row.get("kind")})
    for row in (measurements.get("masks") or {}).get("oversized") or []:
        out.append({"item_id": "QA-OVERSIZED-MASK", "window": [row.get("start"), row.get("end")],
                    "source": "MEASURED", "detail": f"cover {row.get('area_frac')} of frame"})
    for row in (measurements.get("dialogue_tail") or {}).get("flagged") or []:
        out.append({"item_id": "QA-DIALOGUE-TAIL-CUT", "at_seconds": row.get("line_end"), "source": "MEASURED",
                    "detail": f"{row.get('flag')} gap {row.get('gap_seconds')} s"})
    for row in (measurements.get("subtitle_wrap") or {}).get("flagged") or []:
        out.append({"item_id": "QA-SUBTITLE-WRAP", "at_seconds": row.get("start"), "source": "MEASURED",
                    "detail": ",".join(row.get("reasons") or [])})
    for row in (measurements.get("lookalike_cast") or {}).get("too_similar") or []:
        out.append({"item_id": "QA-LOOKALIKE-CAST", "source": "MEASURED",
                    "detail": f"{row.get('a')}~{row.get('b')} cosine {row.get('cosine')}"})
    for row in (measurements.get("bgm") or {}).get("flagged") or []:
        out.append({"item_id": "QA-BGM-DISCONTINUOUS", "window": [row.get("start"), row.get("end")],
                    "source": "MEASURED", "detail": ",".join(row.get("reasons") or [])})
    for row in (measurements.get("s6_burn_unresolved") or {}).get("units") or []:
        out.append({"item_id": "QA-BURNED-TEXT", "source": "S6_BURN_UNRESOLVED", "unit_id": row.get("unit_id"),
                    "detail": f"{row.get('unit_id')}: kept take has {row.get('kept_take_burned_frames')} burned "
                              f"frame(s) after {row.get('retries')} retry(ies) ({row.get('reason')})"})
    # the local A/V evidence pack (av_evidence_pack.py, video-native final review 2026-11-19)
    pack = measurements.get("av_evidence_pack") or {}
    for row in pack.get("burned_text_runs") or []:
        out.append({"item_id": "QA-BURNED-TEXT", "window": row.get("window"), "source": "AV_PACK_OCR",
                    "detail": "GARBLED" if row.get("garbled") else "BURNED_TEXT_RUN"})
    for row in pack.get("tail_cut_suspects") or []:
        out.append({"item_id": "QA-DIALOGUE-TAIL-CUT", "at_seconds": row.get("cut"), "source": "AV_PACK_AUDIO",
                    "detail": f"gap {row.get('gap_s')} s, {row.get('level_db')} dB at the cut"})
    if not str(pack.get("bgm_source") or "").startswith("S7"):  # S7 plan segments are already flagged above
        for row in pack.get("bgm_suspects") or []:
            out.append({"item_id": "QA-BGM-DISCONTINUOUS", "window": row.get("window"), "source": "AV_PACK_AUDIO",
                        "detail": ",".join(row.get("reasons") or [])})
    for row in pack.get("wrap_suspects") or []:
        if "PIXEL_LONE_SHORT_ROW" in (row.get("reasons") or []):
            out.append({"item_id": "QA-SUBTITLE-WRAP", "window": row.get("window"), "source": "AV_PACK_PIXELS",
                        "detail": "PIXEL_LONE_SHORT_ROW"})
    for row in (pack.get("lookalike") or {}).get("suspects") or []:
        out.append({"item_id": "QA-LOOKALIKE-CAST", "source": "AV_PACK_FACES",
                    **({"window": [row.get("start"), row.get("end")]} if row.get("start") is not None else {}),
                    "detail": f"{row.get('kind')} cosine {row.get('cosine')}"})
    return out


GEMINI_MATCH_S = 1.5


def _finding_time(f: dict[str, Any]) -> tuple[float, float] | None:
    if _num(f.get("at_seconds")) is not None:
        return float(f["at_seconds"]), float(f["at_seconds"])
    window = f.get("window") or []
    if len(window) == 2 and _num(window[0]) is not None:
        return float(window[0]), float(_num(window[1]) if _num(window[1]) is not None else window[0])
    return None


def gemini_block(gemini: dict[str, Any] | None, parsed: dict[str, Any],
                 reviewer_findings: list[dict[str, Any]]) -> dict[str, Any]:
    """The video-native pass (gemini_video_review.py) with the Codex reviewer's verdict on each finding: CONFIRMED
    (named in qa_defect_checklist.gemini_verification, or a reviewer DEFECT of the same item within GEMINI_MATCH_S),
    DISMISSED (with the reviewer's reason) or UNVERIFIED."""
    if not isinstance(gemini, dict) or not gemini:
        return {}
    verification = parsed.get("gemini_verification") or {}
    rows = []
    for f in gemini.get("findings") or []:
        decision = verification.get(str(f.get("id"))) or {}
        status = decision.get("decision")
        if status not in ("CONFIRMED", "DISMISSED"):
            near = any(r["item_id"] == f.get("item") and (_finding_time(r) or (-99, -99))[0] - GEMINI_MATCH_S
                       <= float(f.get("end") or f.get("start") or 0) and float(f.get("start") or 0)
                       <= (_finding_time(r) or (-99, -99))[1] + GEMINI_MATCH_S for r in reviewer_findings)
            status = "CONFIRMED" if near else "UNVERIFIED"
        rows.append({"id": f.get("id"), "item": f.get("item"), "window": [f.get("start"), f.get("end")],
                     "severity": f.get("severity"), "status": status, "note": _clean(f.get("description"), 160),
                     **({"reviewer_reason": decision.get("reason")} if decision.get("reason") else {})})
    checks = [{"id": c.get("id"), "gemini": c.get("decision"),
               "reviewer": (verification.get(str(c.get("id"))) or {}).get("decision"),
               "suspect": c.get("suspect")} for c in gemini.get("suspect_checks") or []]
    count = {k: sum(1 for r in rows if r["status"] == k) for k in ("CONFIRMED", "DISMISSED", "UNVERIFIED")}
    return {"status": gemini.get("status"), "reason": gemini.get("reason"), "model": gemini.get("model"),
            "cost_credits": gemini.get("cost_credits"), "findings": rows, "suspect_checks": checks[:40],
            "counts": count, "verdict": gemini.get("verdict")}


def routing(item_id: str, *, maskable: bool = True) -> str:
    row = ITEMS[item_id]
    if item_id == "QA-LOOKALIKE-CAST":
        return "KNOWLEDGE_BASE_AND_NEXT_EPISODE_IDENTITY_DESIGN"
    fixable = row["s7_fixable"] is True or (row["s7_fixable"] == "WHEN_MASKABLE" and maskable)
    # S7 has no cheap automatic re-cut hook (s7_unit_recut renders an authored plan only): record + owner summary
    return "S7_FIXABLE_RECORDED_FOR_OWNER_NO_AUTO_RECUT_HOOK" if fixable else "RECORDED"


def build_record(parsed: dict[str, Any], measurements: dict[str, Any], *, episode: str,
                 bindings: dict[str, Any] | None = None, gemini: dict[str, Any] | None = None) -> dict[str, Any]:
    """The checklist record: per item the reviewer verdict + findings and the measured flags, with routing."""
    findings: list[dict[str, Any]] = []
    for iid, row in (parsed.get("items") or {}).items():
        if row.get("verdict") != "DEFECT":
            continue
        for f in row.get("findings") or [{}]:
            findings.append({"item_id": iid, "source": "REVIEWER", **f})
    measured = _measured_findings(measurements or {})
    video = gemini_block(gemini, parsed, findings)
    items = {}
    for iid in ITEM_IDS:
        reviewer = (parsed.get("items") or {}).get(iid) or {}
        own = [f for f in findings if f["item_id"] == iid]
        flags = [f for f in measured if f["item_id"] == iid]
        status = ("DEFECT" if reviewer.get("verdict") == "DEFECT" else
                  reviewer.get("verdict") or ("MEASURED_FLAG_UNREVIEWED" if flags else "NOT_REVIEWED"))
        items[iid] = {"title_zh": ITEMS[iid]["title_zh"], "status": status, "reviewer_findings": own,
                      "measured_flags": flags[:12], "routing": routing(iid),
                      "craft_item": ITEMS[iid]["craft_item"],
                      **({"gemini_findings": [g for g in video["findings"] if g["item"] == iid][:12]}
                         if video else {})}
    defects = [iid for iid, row in items.items() if row["status"] == "DEFECT"]
    return {"schema": SCHEMA, "episode": episode, "authority": AUTHORITY, "parse": {
                "status": parsed.get("status"), "notes": parsed.get("notes") or []},
            "bindings": bindings or {}, "items": items, "defects": defects,
            "flagged_unreviewed": [iid for iid, row in items.items() if row["status"] == "MEASURED_FLAG_UNREVIEWED"],
            **({"video_review": video} if video else {}),
            **({"s6_burn_unresolved": ((measurements or {}).get("s6_burn_unresolved") or {}).get("units")}
               if ((measurements or {}).get("s6_burn_unresolved") or {}).get("units") else {}),
            **({"letterbox_measured": ((measurements or {}).get("av_evidence_pack") or {}).get("letterbox_shots")}
               if ((measurements or {}).get("av_evidence_pack") or {}).get("letterbox_shots") else {}),
            "auto_recut": {"status": "NO_HOOK", "note": (
                "S7 re-cut renders only an authored UNIT_RECUT_PLAN; no free automatic re-cut exists for these "
                "items, so they are listed in the S8 owner-approval checkpoint instead")}}


def event_specs(record: dict[str, Any]) -> list[dict[str, Any]]:
    """One knowledge-event spec per item that is a DEFECT (reviewer) or carries a measured flag: item id, routing,
    timestamps and counts only -- no text, no names, no dialogue (privacy scrub is the event layer's too)."""
    out = []
    for iid, row in (record.get("items") or {}).items():
        if row.get("status") not in ("DEFECT", "MEASURED_FLAG_UNREVIEWED"):
            continue
        times = [f.get("at_seconds") if f.get("at_seconds") is not None else (f.get("window") or [None])[0]
                 for f in (row.get("reviewer_findings") or []) + (row.get("measured_flags") or [])]
        times = sorted({round(float(t), 2) for t in times if _num(t) is not None})[:12]
        stage = "S3" if iid == "QA-LOOKALIKE-CAST" else "S7"
        out.append({"item_id": iid, "stage": stage, "failure_type": f"{FAILURE_TYPE}:{iid}",
                    "symptom": f"final review must-check {iid} ({row.get('status')}): {ITEMS[iid]['title_zh']}",
                    "evidence": {"cluster_key": f"{FAILURE_TYPE}|{iid}", "item": iid, "detail_category": iid,
                                 "failure_code": iid.replace("-", "_"), "routing": row.get("routing"),
                                 "craft_item": row.get("craft_item"), "status": row.get("status"),
                                 "detail": {"at_seconds": times,
                                            "reviewer_findings": len(row.get("reviewer_findings") or []),
                                            "measured_flags": len(row.get("measured_flags") or []),
                                            "gemini_confirmed": sum(1 for g in row.get("gemini_findings") or []
                                                                    if g.get("status") == "CONFIRMED")}}})
    return out


def checkpoint_lines(record: dict[str, Any] | None) -> list[str]:
    """The S8 owner-approval checkpoint section (markdown lines)."""
    if not isinstance(record, dict) or not record.get("items"):
        return []
    lines = ["## Final-review must-check defects (line owner 2026-11-19)", "",
             "| item | what | status | timestamps | routing |", "|---|---|---|---|---|"]
    for iid, row in record["items"].items():
        stamps = []
        for f in (row.get("reviewer_findings") or []) + (row.get("measured_flags") or []):
            if f.get("at_seconds") is not None:
                stamps.append(f"{float(f['at_seconds']):.1f}s")
            elif f.get("window") and _num(f["window"][0]) is not None:
                stamps.append(f"{float(f['window'][0]):.1f}-{float(f['window'][1] or f['window'][0]):.1f}s")
        lines.append(f"| `{iid}` | {row.get('title_zh')} | **{row.get('status')}** | "
                     f"{', '.join(stamps[:8]) or '—'} | {row.get('routing')} |")
    video = record.get("video_review") or {}
    if video:
        counts = video.get("counts") or {}
        lines += ["", f"Video-native pass ({video.get('model')}, {video.get('cost_credits')} credits, "
                      f"{video.get('status')}): {len(video.get('findings') or [])} findings -- confirmed by the reviewer "
                      f"{counts.get('CONFIRMED', 0)}, dismissed {counts.get('DISMISSED', 0)}, unverified "
                      f"{counts.get('UNVERIFIED', 0)}"]
        for g in [g for g in video.get("findings") or [] if g.get("status") != "DISMISSED"][:10]:
            window = g.get("window") or [None, None]
            lines.append(f"- `{g.get('id')}` {g.get('item')} {window[0]}-{window[1]}s {g.get('severity')} "
                         f"**{g.get('status')}**: {g.get('note')}")
    lines += s6_burn_unresolved_lines(record.get("s6_burn_unresolved"))
    if record.get("letterbox_measured"):
        lines += ["", "Letterboxed / pillarboxed shots measured in the final cut: " + ", ".join(
            f"{(r.get('window') or [0, 0])[0]}-{(r.get('window') or [0, 0])[1]}s" for r in record["letterbox_measured"])]
    lines += ["", f"S7 auto re-cut: {record.get('auto_recut', {}).get('note', '')}", ""]
    return lines


def s6_burn_unresolved_lines(units: Any) -> list[str]:
    """Checkpoint lines for units whose S6 burned-text retries did not clear the burn (QA-BURNED-TEXT)."""
    if not units:
        return []
    return ["", "`QA-BURNED-TEXT` S6 burned text unresolved after the automatic retries (best take kept, no cover): "
            + ", ".join(f"{r.get('unit_id')} ({r.get('kept_take_burned_frames')} burned frame(s), "
                        f"{r.get('retries')} retry(ies), {r.get('reason')})" for r in units)]


def craft_mapping() -> dict[str, str]:
    return {iid: row["craft_item"] for iid, row in ITEMS.items()}


def items_present(request: dict[str, Any]) -> list[str]:
    block = request.get("qa_defect_checklist_request") or {}
    return [row.get("id") for row in block.get("items") or [] if isinstance(row, dict)]
