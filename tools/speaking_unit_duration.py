#!/usr/bin/env python3
"""Speaking-shot duration for CAMERA_GRAMMAR_V1 contracts (line owner, approved 2026-10-24/26).

Lab Holmes E04: a 6-8 s H3 unit around a short line made H3 fill the spare seconds with invented, garbled
speech and pan away; 3-5 s units were clean.  A shot with an on-screen spoken line therefore runs the
estimated line + 0.5 s, at least 4 s and at most 5 s, rounded up to the whole seconds H3 accepts.
HopsAPI (owner 2026-10-29) accepts integer 4-15 s only, so the floor moved from 3 s to 4 s: the writer
fills a speaking shot with ~3.5 s of speech (lab E08: shorter lines made H3 invent speech that S7 then trimmed,
96 s final instead of ~110 s) and merges a short line with the speaker's next line or gives it a performed
action (H3_SCRIPT_ADAPTATION_GUIDE §5); S7 head/tail trims remain the safety net.  Owner 2026-11-02 (lab 化神 E01):
a short line is fine -- S7 cuts to the performance (tools/performance_cut.py); a line estimated under
``SHORT_LINE_WARN_SECONDS`` only carries an ``advisory`` on its report row.  A monologue group's continuation shots
have no per-shot floor (``monologue_group_durations``).

* fits (line + 0.5 <= 5 s): duration = max(4, ceil(line + 0.5)) — shorter or longer than authored;
* a shot with several lines of ONE speaker (owner 2026-11-01, lab E12 long-take test: one continuous 12-14 s take
  of a speaker's consecutive lines played far better than one shot per line) is one speaking group: the same rule
  with the lines' summed estimate, up to ``GROUP_MAX_SECONDS`` (12 s; the H3 request window is
  ``GROUP_HARD_MAX_SECONDS`` = 15 s); longer, the writer splits it with a silent cutaway (§5);
* does not fit: the writer must split the line into two shots (H3_SCRIPT_ADAPTATION_GUIDE §5).  The compiler
  never blocks: it keeps the authored duration, or shortens it to ceil(line + 0.5) when the authored shot runs
  more than line + 1.5 s, and reports ``WRITER_SPLIT_REQUIRED``.

The estimate is tools/dialogue_cut_safety.estimated_spoken_seconds (the same estimate the grouped compiler's
dialogue windows use), at the shot's authored rate when it declares one.  Only stamped contracts call this;
every other episode keeps its authored durations byte-identically.
"""

from __future__ import annotations

import math
from typing import Any

try:
    from tools.dialogue_cut_safety import (
        DEFAULT_CHINESE_CHARACTERS_PER_SECOND,
        DEFAULT_ENGLISH_WORDS_PER_SECOND,
        estimated_spoken_seconds,
    )
except ModuleNotFoundError:  # pragma: no cover - flat sys.path deployments
    from dialogue_cut_safety import (  # type: ignore
        DEFAULT_CHINESE_CHARACTERS_PER_SECOND,
        DEFAULT_ENGLISH_WORDS_PER_SECOND,
        estimated_spoken_seconds,
    )

SCHEMA = "qingshan.speaking_unit_duration.v1"
LINE_PAD_SECONDS = 0.5
MIN_SECONDS = 4  # HopsAPI H3 request floor (owner 2026-10-29; was 3 on Giggle)
MAX_SECONDS = 5
#: one speaker's consecutive lines in one take (owner 2026-11-01): preferred cap / H3 request maximum
GROUP_MAX_SECONDS = 12
GROUP_HARD_MAX_SECONDS = 15
#: the camera-setup fields two consecutive speaking shots must share to be one take (grouping + V2 camera section)
SETUP_FIELDS = ("shot_scale", "camera_height", "camera_side", "motion_family", "motion_direction", "start_framing")
LOCKED_FAMILIES = {"STATIC", "LOCKED"}
SHORTEN_ABOVE_LINE_PLUS = 1.5
#: owner 2026-10-29 (lab E08): a spoken line is written to take ~3.5 s; under it H3 pads the shot with invented speech
SHORT_LINE_WARN_SECONDS = 2.8
#: owner 2026-11-02 (lab 化神 E01): a short line is fine -- generation still requests the 4 s floor and S7 cuts to
#: the performance (tools/performance_cut.py).  The row only carries this advisory; nothing asks for padding.
SHORT_LINE_ADVISORY = "SHORT_LINE_OK_S7_CUTS_TO_PERFORMANCE"
SHORT_LINE_WARNING = SHORT_LINE_ADVISORY  # legacy name
#: a monologue group (one speaker's CONTINUOUS_ACTION same-setup lines, owner 2026-11-02, lab 化神 E01-VU-002):
#: the 4 s floor applies to the generated unit, not to each line -- lines run back to back
GROUP_LEAD_SECONDS = 0.2
GROUP_LINE_GAP_SECONDS = 0.3
GROUP_TAIL_SECONDS = 0.5


def estimated_line_seconds(lines: list[str] | str, language: str = "zh",
                           delivery: dict[str, Any] | None = None) -> float:
    delivery = delivery if isinstance(delivery, dict) else {}
    rows = lines.splitlines() if isinstance(lines, str) else list(lines)
    cps = float(delivery.get("chinese_characters_per_second") or DEFAULT_CHINESE_CHARACTERS_PER_SECOND)
    wps = float(delivery.get("english_words_per_second") or DEFAULT_ENGLISH_WORDS_PER_SECOND)
    return round(sum(estimated_spoken_seconds(row, language=language, chinese_characters_per_second=cps,
                                              english_words_per_second=wps)
                     for row in rows if str(row).strip()), 3)


def _speaker(line: str) -> str:
    head = str(line).strip()[:32]
    for sep in ("：", ":"):
        if sep in head:
            return head.split(sep, 1)[0].strip()
    return ""


def one_speaker_lines(lines: list[str] | str) -> bool:
    """Two or more non-empty lines, all spoken by the same named speaker (``Speaker：line``)."""
    rows = [row for row in (lines.splitlines() if isinstance(lines, str) else list(lines)) if str(row).strip()]
    speakers = {_speaker(row) for row in rows}
    return len(rows) > 1 and len(speakers) == 1 and "" not in speakers


def max_seconds_for(lines: list[str] | str) -> int:
    """MAX_SECONDS for one line, GROUP_MAX_SECONDS for several lines of one speaker."""
    return GROUP_MAX_SECONDS if one_speaker_lines(lines) else MAX_SECONDS


def setup_key(camera_plan: dict[str, Any] | None) -> tuple[str, ...]:
    """The camera setup of a shot: two speaking shots with the same key are one locked take."""
    plan = camera_plan if isinstance(camera_plan, dict) else {}
    return tuple(str(plan.get(field) or "").strip().upper() if field != "start_framing"
                 else str(plan.get(field) or "").strip() for field in SETUP_FIELDS)


def locked_setup(camera_plan: dict[str, Any] | None) -> bool:
    return str((camera_plan or {}).get("motion_family") or "STATIC").strip().upper() in LOCKED_FAMILIES


def group_duration(line_lists: list[list[str] | str], language: str = "zh",
                   delivery: dict[str, Any] | None = None) -> dict[str, Any]:
    """A speaking group (one speaker's consecutive lines in one take): the summed estimate + pad, at least
    MIN_SECONDS, against GROUP_MAX_SECONDS (fits) / GROUP_HARD_MAX_SECONDS (over the preferred cap) / beyond
    (the writer must split it with a cutaway)."""
    line = round(sum(estimated_line_seconds(lines, language, delivery) for lines in line_lists), 3)
    need = float(max(MIN_SECONDS, math.ceil(line + LINE_PAD_SECONDS - 1e-9))) if line > 0 else 0.0
    verdict = ("FITS" if need <= GROUP_MAX_SECONDS else
               "OVER_PREFERRED_CAP" if need <= GROUP_HARD_MAX_SECONDS else "WRITER_SPLIT_REQUIRED")
    return {"estimated_line_seconds": line, "duration_seconds": need, "verdict": verdict,
            "group_max_seconds": GROUP_MAX_SECONDS, "hard_max_seconds": GROUP_HARD_MAX_SECONDS}


def speaking_duration(authored: float, lines: list[str] | str, language: str = "zh",
                      delivery: dict[str, Any] | None = None) -> dict[str, Any]:
    """Report row with the new ``duration_seconds`` for one speaking shot (one line, or one speaker's lines)."""
    authored = float(authored)
    line = estimated_line_seconds(lines, language, delivery)
    need = line + LINE_PAD_SECONDS
    if line <= 0:
        return {"authored_seconds": authored, "estimated_line_seconds": line, "duration_seconds": authored,
                "action": "NO_SPOKEN_LINE"}
    if need <= max_seconds_for(lines) + 1e-9:
        new = float(max(MIN_SECONDS, math.ceil(need - 1e-9)))
        action = "UNCHANGED" if abs(new - authored) < 1e-9 else ("SHORTENED" if new < authored else "LENGTHENED")
    else:
        new = float(math.ceil(need - 1e-9)) if authored > line + SHORTEN_ABOVE_LINE_PLUS else authored
        action = "WRITER_SPLIT_REQUIRED" + ("_SHORTENED" if new < authored else "_KEPT")
    row = {"authored_seconds": authored, "estimated_line_seconds": line, "target_seconds": round(need, 3),
           "duration_seconds": new, "action": action}
    if line < SHORT_LINE_WARN_SECONDS:  # advisory only: keep the source's short line, S7 cuts to the performance
        row["advisory"] = SHORT_LINE_ADVISORY
    return row


def monologue_group_durations(estimates: list[float]) -> list[float]:
    """Shot durations of a monologue group (one speaker's consecutive same-setup lines in one take): line 1 starts
    after GROUP_LEAD_SECONDS, the lines follow back to back GROUP_LINE_GAP_SECONDS apart, GROUP_TAIL_SECONDS after the
    last; the unit total is rounded up to the whole seconds H3 accepts (>= MIN_SECONDS, <= GROUP_HARD_MAX_SECONDS) and
    the rounding goes to the last shot.  No per-line 4 s floor (the floor is the generated unit's)."""
    n = len(estimates)
    raw = [(GROUP_LEAD_SECONDS if i == 0 else 0.0) + float(e)
           + (GROUP_LINE_GAP_SECONDS if i < n - 1 else GROUP_TAIL_SECONDS) for i, e in enumerate(estimates)]
    if not raw:
        return []
    total = sum(raw)
    target = float(max(MIN_SECONDS, math.ceil(total - 1e-9)))
    if target > GROUP_HARD_MAX_SECONDS:  # over the request window: the writer splits it (R12), keep the estimates
        return [round(x, 3) for x in raw]
    out = [round(x, 1) for x in raw[:-1]]  # tenths: readable per-line windows in the prompt
    return out + [round(target - sum(out), 3)]
