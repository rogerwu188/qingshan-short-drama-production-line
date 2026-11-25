#!/usr/bin/env python3
"""Per-unit micro-performance timeline (E27 review, device 1101, 2026-11-25; zero credits, no gate).

E27's dialogue units carried one emotion word + one body action + one delivery cue each, and H3 played every line
as the same posture reciting.  The acting tutorials the line owner collected (``小红书教程学习.md``: second-by-second
micro-performance, the protective layer failing gradually, disfluency chosen by psychology, the grief formula, FACS
AU as an auxiliary tag) are turned into data here, so the screenplay compiler can expand each speaking unit into a
2-3 beat, time-coded micro-performance that the H3 renderers write into the prompt:

  entry state  ->  a visible change triggered by one specific word of the line  ->  the end frame.

Per character per scene an :class:`EmotionCurve` carries each unit's exit state into the same character's next unit
as its entry state, and marks a jump across more than one stage of the protective ladder (protective -> justify ->
crack -> break) so the entry is written as the old state starting to give way (never a cut from anger to tears).

A disfluency is chosen by psychology (shame -> failed start; misunderstood -> hard stress; sudden cruel realisation
-> silence + one failed inhale; hiding intent -> hesitation and a corrected course), placed on the hardest word only,
at most ``disfluency_max_per_scene`` per scene, and written as body -- never as added or repeated words, so the line
stays verbatim for the burned subtitles and the ASR match.

Data: ``configs/PERFORMANCE_EMOTION_LEXICON_v1.json`` ``micro_performance``.  Pure functions, stdlib only.
Timeline beats carry ``from`` / ``to`` as fractions of the line's window; ``{who}`` / ``{listener}`` / ``{trigger}``
placeholders in the English text are filled by the renderer (``tools/bili_carry.py``) with the unit's provider labels
and "the stressed word at about N s" -- the H3 boundary admits no Chinese outside the dialogue tags, so the English
never quotes the trigger word; the CHANGE beat's ``trigger_at`` is the word's position as a fraction of the window.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

LEXICON_PATH = Path(__file__).resolve().parent.parent / "configs" / "PERFORMANCE_EMOTION_LEXICON_v1.json"
SCHEMA = "nalu.performance_timeline.v1"
_CJK = re.compile(r"[㐀-鿿]")
_PUNCT = re.compile(r"[，。！？、；：,.!?;:…—\-「」“”\"'（）()\s]")


@lru_cache(maxsize=1)
def lexicon() -> dict[str, Any]:
    try:
        data = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    block = data.get("micro_performance")
    return block if isinstance(block, dict) else {}


def emotion_row(emotion: str) -> dict[str, Any]:
    row = (lexicon().get("emotions") or {}).get(emotion)
    return row if isinstance(row, dict) else {}


def stage_of(emotion: str) -> int | None:
    stage = emotion_row(emotion).get("stage")
    return stage if isinstance(stage, int) else None


# --------------------------------------------------------------------------- trigger word
def trigger_word(line: str, names: list[str] | None = None) -> tuple[str, int]:
    """(word, character index) of the hardest word of ``line``: a person's name, else the strongest hard word of the
    lexicon, else the last two characters of the line's last clause."""
    text = line or ""
    for name in sorted({n for n in names or [] if n}, key=len, reverse=True):
        at = text.find(name)
        if at >= 0:
            return name, at
    for word in lexicon().get("hard_words_zh") or []:
        at = text.find(word)
        if at >= 0:
            return word, at
    chars = [(i, ch) for i, ch in enumerate(text) if _CJK.match(ch)]
    if not chars:
        return "", 0
    clause_end = len(text.rstrip("。！？!?…").rstrip())
    tail = [(i, ch) for i, ch in chars if i < clause_end][-2:] or chars[-2:]
    return "".join(ch for _, ch in tail), tail[0][0]


def _spoken_fraction(line: str, index: int) -> float:
    spoken = [i for i, ch in enumerate(line or "") if not _PUNCT.match(ch)]
    if not spoken:
        return 0.5
    before = sum(1 for i in spoken if i < index)
    return before / len(spoken)


# --------------------------------------------------------------------------- psychology / disfluency
def psychology(emotion: str, paren: str, line: str) -> str:
    """shame | misunderstood | realisation | hiding | '' -- an explicit parenthetical cue wins over the emotion."""
    table = lexicon().get("psychology") or {}
    for name, row in table.items():
        if any(cue and cue in (paren or "") for cue in row.get("cues") or []):
            return name
    for name, row in table.items():
        if emotion in (row.get("emotions") or []):
            if row.get("needs_negation") and not any(n in (line or "") for n in lexicon().get("negations_zh") or []):
                continue
            return name
    return ""


def _fill(template: str, **values: str) -> str:
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", value)
    return out


# --------------------------------------------------------------------------- emotion curve
class EmotionCurve:
    """One scene's per-character emotion state: the exit state of a character's unit is the entry state of that
    character's next unit; jumps across more than one stage of the protective ladder are softened and recorded."""

    def __init__(self) -> None:
        self.last: dict[str, dict[str, Any]] = {}
        self.disfluencies = 0
        self.jumps: list[str] = []

    def entry_for(self, who: str, emotion: str) -> tuple[dict[str, str], str]:
        """({zh, en} entry, curve note) for ``who`` about to play ``emotion``."""
        row = emotion_row(emotion)
        base = {"zh": row.get("entry_zh") or "", "en": row.get("entry_en") or ""}
        prev = self.last.get(who)
        if not prev:
            return base, "scene_start"
        carried = {"zh": f"接上一句的状态：{prev['exit_zh']}", "en": f"carried over from the last line: {prev['exit_en']}"}
        a, b = prev.get("stage"), stage_of(emotion)
        if isinstance(a, int) and isinstance(b, int) and abs(b - a) > 1:
            names = lexicon().get("stage_names") or []
            label = f"{names[a] if a < len(names) else a}->{names[b] if b < len(names) else b}"
            self.jumps.append(f"{who}:{prev['emotion']}->{emotion}:{label}")
            carried["zh"] += f"；{prev['emotion']}还挂在脸上，但开始撑不住"
            carried["en"] += f"; the old {prev.get('emotion_en') or 'state'} still on the face but starting to give way"
            return carried, "softened_jump"
        return carried, "carried"

    def close(self, who: str, emotion: str, emotion_en: str, exit_state: dict[str, str]) -> None:
        self.last[who] = {"emotion": emotion, "emotion_en": emotion_en, "stage": stage_of(emotion),
                          "exit_zh": exit_state["zh"], "exit_en": exit_state["en"]}


# --------------------------------------------------------------------------- the timeline
def build(*, who: str, emotion: str, emotion_en: str, line: str, paren: str = "", listener_name: str = "",
          names: list[str] | None = None, hardest: bool = False, curve: EmotionCurve | None = None,
          lead_in: bool = False) -> dict[str, Any] | None:
    """The unit's micro-performance (None when the emotion has no lexicon row).

    ``who``: the speaker's entity id (the curve key); ``names``: the other cast names (a name is the strongest
    trigger word); ``hardest``: the scene's hardest line (always gets its psychology's disfluency); ``lead_in``: the
    unit opens on an authored lead-in reaction (the entry beat then starts after it)."""
    row = emotion_row(emotion)
    if not row or not line:
        return None
    curve = curve if curve is not None else EmotionCurve()
    word, index = trigger_word(line, names)
    at = _spoken_fraction(line, index)
    start = 0.3 if lead_in else 0.0
    t_change = round(min(0.6, max(start + 0.15, start + (1.0 - start) * at)), 2)
    t_exit = round(min(0.85, max(t_change + 0.2, 0.75)), 2)
    entry, note = curve.entry_for(who, emotion)
    listener = listener_name or "对方"
    psych = psychology(emotion, paren, line)
    cap = int(lexicon().get("disfluency_max_per_scene") or 2)
    disfluency = None
    if psych and word and (hardest or curve.disfluencies == 0) and curve.disfluencies < cap:
        spec = (lexicon().get("psychology") or {}).get(psych) or {}
        disfluency = {"psychology": psych, "word": word,
                      "zh": _fill(spec.get("zh") or "", word=word), "en": spec.get("en") or ""}
        curve.disfluencies += 1
    change_zh = _fill(row.get("change_zh") or "", listener=listener)
    change_en = row.get("change_en") or ""
    if disfluency:
        change_zh = f"{disfluency['zh']}；{change_zh}"
        change_en = f"{disfluency['en']}; {change_en}"
    trigger_zh = f"说到「{word}」时：" if word else "说这句时："
    trigger_en = "on {trigger}: " if word else "during the line: "
    exit_state = {"zh": _fill(row.get("exit_zh") or "", listener=listener), "en": row.get("exit_en") or ""}
    beats = [
        {"from": start, "to": t_change, "kind": "ENTRY",
         "zh": _fill(entry["zh"], listener=listener), "en": entry["en"]},
        {"from": t_change, "to": t_exit, "kind": "CHANGE", "trigger_word": word,
         "trigger_at": t_change,
         "zh": trigger_zh + change_zh, "en": trigger_en + change_en},
        {"from": t_exit, "to": 1.0, "kind": "EXIT", "zh": "收尾定格：" + exit_state["zh"],
         "en": "end frame: " + exit_state["en"] + ", lips closed after the last word"},
    ]
    curve.close(who, emotion, emotion_en, exit_state)
    return {"schema": SCHEMA, "emotion": emotion, "stage": stage_of(emotion), "curve": note,
            "trigger_word": word, "disfluency": disfluency, "beats": beats}


def zh_summary(timeline: dict[str, Any] | None) -> str:
    """One line for the directing script: "0–30%：…｜30–80%：…｜80–100%：…"."""
    if not isinstance(timeline, dict):
        return ""
    return "｜".join(f"{round(b['from'] * 100)}–{round(b['to'] * 100)}%：{b['zh']}" for b in timeline.get("beats") or [])


__all__ = ["SCHEMA", "EmotionCurve", "build", "emotion_row", "lexicon", "psychology", "stage_of", "trigger_word",
           "zh_summary"]
