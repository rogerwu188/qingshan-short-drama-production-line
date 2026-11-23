#!/usr/bin/env python3
"""S7: trim the video model's own internal cuts out of a unit (device 1101 E24 review, 2026-11-23).

MiniMax-H3 sometimes cuts inside one generated unit.  When the cut leaves a fragment shorter than the minimum shot the
viewer sees a flash: E24 VU-016 0.25 s @42.67 (palace gate -> teahouse, same pose), VU-020 0.37 s @50.63 (a glasses
close-up), VU-004 a 0.87 s teahouse interior before a field wide.  Until now S7 treated every internal cut as
designed and the post-S7 edit measurement only recorded the fragment (P2).

Here every unit clip is scanned with ffmpeg ``scdet`` (``SCDET_THRESHOLD``); inside the unit's kept window
(performance cut in/out) the segment carrying the unit's scripted line is the anchor (silent unit: the segment of its
motion peak, else the longest), the kept window grows over neighbouring segments that are at least the minimum shot
long (H3's designed shots) and stops at a fragment; a fragment that carries the line (speech + the 0.25 s tail) is
never cut away -- it stays and is reported (``left_fragments``; the post-S7 edit measurement makes it a P1 trigger of
the final fix round).  Only head/tail trims are possible (one continuous window per unit), so a fragment between two
kept segments also stays and is reported.

Pure planning (:func:`choose_window`, :func:`apply`) plus the measurement (:func:`scene_cuts`); the S7 caller writes
the result into the performance-cut rows (reason ``TRIM_H3_INTERNAL_CUT``) before the head/tail reports are merged.
Free; never blocks S7.
"""
from __future__ import annotations

import re
import subprocess
from typing import Any, Callable

try:
    import s7_edit_invariants as _inv
except ImportError:  # pragma: no cover - imported as tools.<module>
    from tools import s7_edit_invariants as _inv

SCHEMA = "nalu.h3_internal_cut_trim.v1"
REASON = "TRIM_H3_INTERNAL_CUT"
SCDET_THRESHOLD = 10.0      # E24: every internal cut and unit boundary scored 13-22, in-shot motion < 8
CUT_GUARD_SECONDS = 0.02    # the kept window ends this far before the new shot's first frame
SPEECH_OVERLAP_SECONDS = 0.05
EPS = 1e-6

_SCD_RE = re.compile(r"lavfi\.scd\.score:\s*([0-9.]+),\s*lavfi\.scd\.time:\s*([0-9.]+)")


def scene_cuts(path: Any, *, ffmpeg: str = "ffmpeg", threshold: float = SCDET_THRESHOLD) -> list[float]:
    """Source seconds of the scene cuts ffmpeg ``scdet`` finds in one clip (the first frame of each new shot)."""
    run = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-an",
                          "-vf", f"scdet=threshold={threshold:g}", "-f", "null", "-"],
                         capture_output=True, text=True, check=False)
    if run.returncode != 0:
        raise RuntimeError((run.stderr or "")[-300:])
    return sorted({round(float(t), 4) for _s, t in _SCD_RE.findall(run.stderr or "") if float(t) > 0.05})


def _overlap(a: float, b: float, spans: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(b, y) - max(a, x)) for x, y in spans)


def choose_window(window: tuple[float, float], cuts: list[float], *,
                  speech: list[tuple[float, float]] | None = None, anchor_time: float | None = None,
                  min_shot: float | None = None) -> dict[str, Any]:
    """The kept (in, out) of one unit after removing internal-cut fragments.

    ``window``: the unit's current kept window (source seconds); ``cuts``: scene cuts in the clip; ``speech``: the
    scripted line's spans (with their tail) -- never cut; ``anchor_time``: a silent unit's motion peak."""
    a, b = float(window[0]), float(window[1])
    min_shot = _inv.min_shot_seconds() if min_shot is None else float(min_shot)
    inner = sorted(c for c in (float(x) for x in cuts or []) if a + EPS < c < b - EPS)
    base = {"window": [round(a, 3), round(b, 3)], "internal_cuts": [round(c, 3) for c in inner],
            "min_shot_seconds": min_shot}
    if not inner:
        return {**base, "status": "NO_INTERNAL_CUT", "keep": [round(a, 3), round(b, 3)], "removed": [],
                "left_fragments": []}
    points = [a, *inner, b]
    segs = [(points[i], points[i + 1]) for i in range(len(points) - 1)]
    spans = [(float(x), float(y)) for x, y in speech or [] if float(y) > float(x)]
    talk = [_overlap(x, y, spans) for x, y in segs]
    if any(t > SPEECH_OVERLAP_SECONDS for t in talk):
        anchor, basis = max(range(len(segs)), key=lambda i: (talk[i], segs[i][1] - segs[i][0])), "SCRIPTED_LINE"
    elif anchor_time is not None and a - EPS <= float(anchor_time) <= b + EPS:
        anchor = next(i for i, (x, y) in enumerate(segs) if float(anchor_time) <= y + EPS)
        basis = "MOTION_PEAK"
    else:
        anchor, basis = max(range(len(segs)), key=lambda i: segs[i][1] - segs[i][0]), "LONGEST_SEGMENT"
    lo = hi = anchor
    # the line is never cut: every segment it plays under stays
    speaking = [i for i, t in enumerate(talk) if t > SPEECH_OVERLAP_SECONDS]
    if speaking:
        lo, hi = min(lo, *speaking), max(hi, *speaking)
    # designed shots (>= the minimum shot) next to the kept run stay; the walk stops at a fragment
    while lo > 0 and segs[lo - 1][1] - segs[lo - 1][0] >= min_shot - EPS:
        lo -= 1
    while hi < len(segs) - 1 and segs[hi + 1][1] - segs[hi + 1][0] >= min_shot - EPS:
        hi += 1
    keep_a = segs[lo][0]
    keep_b = segs[hi][1] if hi == len(segs) - 1 else max(segs[hi][0] + EPS, segs[hi][1] - CUT_GUARD_SECONDS)
    removed = [[round(x, 3), round(y, 3)] for i, (x, y) in enumerate(segs) if i < lo or i > hi]
    left = [{"start": round(x, 3), "end": round(y, 3), "seconds": round(y - x, 3),
             "reason": "CARRIES_THE_LINE" if talk[i] > SPEECH_OVERLAP_SECONDS else "BETWEEN_KEPT_SHOTS"}
            # a short anchor kept alone (E24 VU-020 1.13 s) is the unit's picture, not a fragment of it
            for i, (x, y) in enumerate(segs) if lo <= i <= hi and y - x < min_shot - EPS and lo != hi]
    status = "TRIMMED" if removed else ("FRAGMENT_LEFT" if left else "DESIGNED_SHOTS_KEPT")
    return {**base, "status": status, "anchor_basis": basis, "anchor": [round(segs[anchor][0], 3),
                                                                        round(segs[anchor][1], 3)],
            "keep": [round(keep_a, 3), round(keep_b, 3)], "removed": removed, "left_fragments": left}


def line_spans(row: dict[str, Any], unit_asr: list[dict[str, Any]] | None) -> list[tuple[float, float]]:
    """A speaking row's scripted line (performance-cut line start/end, else its ASR words) plus the 0.25 s tail."""
    tail = _inv.TAIL_SECONDS
    if row.get("kind") != "SPEAKING":
        return []
    if row.get("line_start_seconds") is not None and row.get("line_end_seconds") is not None:
        return [(float(row["line_start_seconds"]), float(row["line_end_seconds"]) + tail)]
    out = []
    for seg in unit_asr or []:
        words = seg.get("words") or []
        if words:
            out += [(float(w["start"]), float(w["end"]) + tail) for w in words
                    if w.get("start") is not None and w.get("end") is not None]
        elif seg.get("start") is not None and seg.get("end") is not None:
            out.append((float(seg["start"]), float(seg["end"]) + tail))
    return out


def apply(perf: dict[str, Any], cuts_by_unit: dict[str, list[float]], unit_asr: dict[str, Any] | None = None, *,
          skip_units: set[str] | None = None, min_shot: float | None = None) -> dict[str, Any]:
    """Tighten each performance-cut row to its kept window (in place; reason ``TRIM_H3_INTERNAL_CUT`` appended) and
    return the report.  ``cuts_by_unit``: unit -> scene cuts (source seconds) of its clip."""
    rows_out = []
    for row in perf.get("units") or []:
        uid = str(row.get("unit_id"))
        if uid in (skip_units or set()) or uid not in cuts_by_unit or not row.get("original_seconds"):
            continue
        a, b = float(row.get("after_in") or 0.0), float(row.get("after_out") or row["original_seconds"])
        peak = (row.get("peak_window") or {}).get("peak_at")
        choice = choose_window((a, b), cuts_by_unit[uid], speech=line_spans(row, (unit_asr or {}).get(uid)),
                               anchor_time=float(peak) if peak is not None else None, min_shot=min_shot)
        choice["unit_id"] = uid
        choice["kind"] = row.get("kind")
        rows_out.append(choice)
        if choice["status"] != "TRIMMED":
            continue
        k0, k1 = choice["keep"]
        row["internal_cut_trim"] = {k: choice[k] for k in ("internal_cuts", "removed", "anchor_basis", "keep")}
        row.update(after_in=round(max(a, k0), 3), after_out=round(min(b, k1), 3),
                   kept_seconds=round(min(b, k1) - max(a, k0), 3), changed=True)
        if REASON not in row.setdefault("reasons", []):
            row["reasons"].append(REASON)
    removed = round(sum(y - x for r in rows_out for x, y in r["removed"]), 3)
    return {"schema": SCHEMA, "scdet_threshold": SCDET_THRESHOLD,
            "min_shot_seconds": _inv.min_shot_seconds() if min_shot is None else min_shot,
            "trimmed_units": sorted(r["unit_id"] for r in rows_out if r["status"] == "TRIMMED"),
            "left_fragments": [{"unit_id": r["unit_id"], **f} for r in rows_out for f in r["left_fragments"]],
            "removed_seconds": removed, "units": rows_out}


def measure_all(clips: dict[str, Any], cut_fn: Callable[[Any], list[float]]) -> tuple[dict[str, list[float]],
                                                                                       dict[str, str]]:
    """unit -> scene cuts; a clip that cannot be scanned is left out (recorded) and keeps its window."""
    cuts, errors = {}, {}
    for uid, clip in clips.items():
        try:
            cuts[uid] = cut_fn(clip)
        except Exception as exc:  # noqa: BLE001 -- a scan failure only leaves the unit untrimmed
            errors[uid] = f"{type(exc).__name__}:{str(exc)[:120]}"
    return cuts, errors
