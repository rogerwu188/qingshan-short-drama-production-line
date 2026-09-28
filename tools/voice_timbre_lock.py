#!/usr/bin/env python3
"""Voice-timbre lock shared by the SD2 renderer, the writer self-check and post-gen QA.

E09 (2026-09-28): SD2 re-synthesises every unit's voice from the bound reference audio as a
weak hint.  The only binding was one ``X使用@音频N固定声线`` clause at the end of 【声音】, and
delivery directions such as 压着嗓子 / 扯着嗓子 / 声音发颤 asked the model to change the voice
itself, so one character's per-scene F0 median ranged 119–250 Hz.  Policy lives in
``configs/VOICE_TIMBRE_LOCK_V1.json``; a missing file disables every rule (older behaviour).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "configs" / "VOICE_TIMBRE_LOCK_V1.json"
SCHEMA = "nalu.voice_timbre_lock.v1"

_CACHE: dict[str, Any] = {}


def load_policy(path: Path | None = None) -> dict[str, Any]:
    target = Path(path or POLICY_PATH)
    key = str(target)
    if key not in _CACHE:
        if not target.is_file():
            _CACHE[key] = {}
        else:
            data = json.loads(target.read_text(encoding="utf-8"))
            if data.get("schema") != SCHEMA:
                raise ValueError(f"VOICE_TIMBRE_LOCK_SCHEMA_INVALID:{target}")
            _CACHE[key] = data
    return _CACHE[key]


def episode_number(value: Any) -> int | None:
    match = re.search(r"(?:^|[^A-Z])E(\d+)", str(value or "").upper())
    return int(match.group(1)) if match else None


def active_for(episode_or_unit: Any, policy: dict[str, Any] | None = None) -> bool:
    policy = load_policy() if policy is None else policy
    start = policy.get("active_from_episode")
    number = episode_number(episode_or_unit)
    return bool(policy) and start is not None and number is not None and number >= int(start)


def terms_in(text: str, policy: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Timbre-changing delivery terms found in ``text``, longest match first, no overlaps."""
    policy = load_policy() if policy is None else policy
    rows = sorted(policy.get("timbre_modifier_terms") or [], key=lambda r: -len(str(r.get("term") or "")))
    found: list[dict[str, str]] = []
    taken: list[tuple[int, int]] = []
    for row in rows:
        term = str(row.get("term") or "")
        if not term:
            continue
        for match in re.finditer(re.escape(term), str(text or "")):
            span = match.span()
            if any(span[0] < b and a < span[1] for a, b in taken):
                continue
            taken.append(span)
            found.append({"term": term, "tone": str(row.get("tone") or ""), "at": span[0]})
    return sorted(found, key=lambda r: r["at"])


def line_binding(speaker: str, slot: str, policy: dict[str, Any] | None = None) -> str:
    policy = load_policy() if policy is None else policy
    template = (policy.get("prompt") or {}).get("per_line_binding_template") or "{speaker}（音色严格同{slot}）"
    return template.format(speaker=speaker, slot=slot)


def sound_header(bindings: list[str], policy: dict[str, Any] | None = None) -> str:
    policy = load_policy() if policy is None else policy
    template = (policy.get("prompt") or {}).get("sound_block_header_template") or "声线锁定：{bindings}"
    return template.format(bindings="；".join(bindings))


# a speech verb or 地/的 right after a replaced term keeps the phrase grammatical without a comma
_JOINERS = "地的"
_SPEECH_VERBS = "说问喊道念叫答嚷骂"


def rewrite_delivery(text: str, policy: dict[str, Any] | None = None) -> str:
    """Replace every timbre-changing delivery term with its tone-only wording.

    Roger 2026-09-28: 表演指令只写语气，不写嗓音 — 压着嗓子 becomes 语速放慢、一字一顿，音色不变.
    The voice-changing words are removed from the provider text, not merely annotated.
    """
    policy = load_policy() if policy is None else policy
    suffix = (policy.get("prompt") or {}).get("timbre_replacement_suffix") or "音色不变"
    source = str(text or "")
    out: list[str] = []
    cursor = 0
    rows = terms_in(source, policy)
    for index, row in enumerate(rows):
        start, term = row["at"], row["term"]
        end = start + len(term)
        out.append(source[cursor:start])
        # adjacent terms (屏着气轻声) share one trailing 音色不变
        if index + 1 < len(rows) and rows[index + 1]["at"] == end:
            out.append(f"{row['tone']}、")
            cursor = end
            continue
        replacement = f"{row['tone']}、{suffix}"
        following = source[end:end + 1]
        if term.endswith("地"):
            replacement += "地"
        elif following in _SPEECH_VERBS:
            replacement += "地"
        elif following and following not in _JOINERS and following not in "，。；、）":
            replacement += "，"
        out.append(replacement)
        cursor = end
    out.append(source[cursor:])
    return "".join(out)
