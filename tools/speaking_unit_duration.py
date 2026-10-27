#!/usr/bin/env python3
"""Speaking-shot duration for CAMERA_GRAMMAR_V1 contracts (line owner, approved 2026-10-24/26).

Lab Holmes E04: a 6-8 s H3 unit around a short line made H3 fill the spare seconds with invented, garbled
speech and pan away; 3-5 s units were clean.  A shot with an on-screen spoken line therefore runs the
estimated line + 0.5 s, at least 3 s and at most 5 s, rounded up to the whole seconds H3 accepts.

* fits (line + 0.5 <= 5 s): duration = max(3, ceil(line + 0.5)) — shorter or longer than authored;
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
MIN_SECONDS = 3
MAX_SECONDS = 5
SHORTEN_ABOVE_LINE_PLUS = 1.5


def estimated_line_seconds(lines: list[str] | str, language: str = "zh",
                           delivery: dict[str, Any] | None = None) -> float:
    delivery = delivery if isinstance(delivery, dict) else {}
    rows = lines.splitlines() if isinstance(lines, str) else list(lines)
    cps = float(delivery.get("chinese_characters_per_second") or DEFAULT_CHINESE_CHARACTERS_PER_SECOND)
    wps = float(delivery.get("english_words_per_second") or DEFAULT_ENGLISH_WORDS_PER_SECOND)
    return round(sum(estimated_spoken_seconds(row, language=language, chinese_characters_per_second=cps,
                                              english_words_per_second=wps)
                     for row in rows if str(row).strip()), 3)


def speaking_duration(authored: float, lines: list[str] | str, language: str = "zh",
                      delivery: dict[str, Any] | None = None) -> dict[str, Any]:
    """Report row with the new ``duration_seconds`` for one speaking shot."""
    authored = float(authored)
    line = estimated_line_seconds(lines, language, delivery)
    need = line + LINE_PAD_SECONDS
    if line <= 0:
        return {"authored_seconds": authored, "estimated_line_seconds": line, "duration_seconds": authored,
                "action": "NO_SPOKEN_LINE"}
    if need <= MAX_SECONDS + 1e-9:
        new = float(max(MIN_SECONDS, math.ceil(need - 1e-9)))
        action = "UNCHANGED" if abs(new - authored) < 1e-9 else ("SHORTENED" if new < authored else "LENGTHENED")
    else:
        new = float(math.ceil(need - 1e-9)) if authored > line + SHORTEN_ABOVE_LINE_PLUS else authored
        action = "WRITER_SPLIT_REQUIRED" + ("_SHORTENED" if new < authored else "_KEPT")
    return {"authored_seconds": authored, "estimated_line_seconds": line, "target_seconds": round(need, 3),
            "duration_seconds": new, "action": action}
