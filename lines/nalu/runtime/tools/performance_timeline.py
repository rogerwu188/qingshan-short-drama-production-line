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

Writer-authored performance (E28 review 2026-11-26, line owner "现在迭代的太慢了"): the lexicon above is only the
FALLBACK.  Under SCREENPLAY_V1 the writer authors, per dialogue line, an ``@演`` block (want / hide / leak / crack /
visible business / end state / listener) and per character per scene an ``@arc`` (entry -> exit); the compiler then
builds the timeline from those (:func:`build_authored`, ``source: writer``) and takes the trigger word from the writer's
stress note (:func:`stress_word`), never from :func:`trigger_word`.  A line without ``@演`` keeps the lexicon timeline,
marked ``source: lexicon_fallback``.

Data: ``configs/PERFORMANCE_EMOTION_LEXICON_v1.json`` ``micro_performance``.  Pure functions, stdlib only.
Timeline beats carry ``from`` / ``to`` as fractions of the line's window; ``{who}`` / ``{listener}`` / ``{trigger}``
placeholders in the English text are filled by the renderer (``tools/bili_carry.py``) with the unit's provider labels.
The H3 prompt carries the English beats untimed and without any reference to the spoken line (E28 2026-11-26: a
time-coded "on the stressed word at about N s" timeline made H3 burn the line as on-screen text); the timing and the
trigger word stay in the data and in the Chinese directing summary only.
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
        carried = {"zh": f"接上一句的状态：{prev['exit_zh']}", "en": f"carried over from the previous shot: {prev['exit_en']}"}
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
    word, index, stress_source = stress_word(line, paren)  # the writer's stress note first (E28 review)
    if not word:
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
         "en": "end frame: " + exit_state["en"] + ("" if "lips" in exit_state["en"] else ", lips closed")},
    ]
    curve.close(who, emotion, emotion_en, exit_state)
    return {"schema": SCHEMA, "source": "lexicon_fallback", "emotion": emotion, "stage": stage_of(emotion),
            "curve": note, "trigger_word": word, "trigger_source": stress_source or "auto", "disfluency": disfluency,
            "beats": beats}


def zh_summary(timeline: dict[str, Any] | None) -> str:
    """One line for the directing script: "0–30%：…｜30–80%：…｜80–100%：…"."""
    if not isinstance(timeline, dict):
        return ""
    return "｜".join(f"{round(b['from'] * 100)}–{round(b['to'] * 100)}%：{b['zh']}" for b in timeline.get("beats") or [])


# --------------------------------------------------------------------------- writer-authored performance (E28)
#: ``@演 要=… | 压=… | 漏=… | 裂=… | 做=… | 收=… | 听=…`` keys (Chinese and English spellings) -> field
PERF_KEYS = {"要": "want", "想要": "want", "want": "want", "目的": "want",
             "压": "hide", "藏": "hide", "hide": "hide", "压着": "hide",
             "漏": "leak", "泄": "leak", "leak": "leak",
             "裂": "crack", "破": "crack", "crack": "crack",
             "做": "visible", "可见": "visible", "visible": "visible", "动作": "visible",
             "收": "end", "结束": "end", "end": "end",
             "听": "listener", "听者": "listener", "listener": "listener"}
PERF_FIELDS = ("want", "hide", "leak", "crack", "visible", "end", "listener")
#: the Chinese directing note may anchor the crack on a word (「到"救他"时……」); the English twin never does (#352)
_ANCHOR = re.compile(r"(?:说到|到|在|念到|讲到)?\s*[「『“\"'‘](?P<word>[^」』”\"'’]{1,12})[」』”\"'’]\s*(?:时|的时候|那里|这里|处|上|前|后)?\s*[，,：:]?\s*")
#: stress / pacing notes in the parenthetical: 「先救他三个字落重」「等不起突然加重」「在一部分前停顿」「天君压到耳语」
_STRESS_NOTE = re.compile(r"(?:在)?(?P<word>[㐀-鿿]{1,8}?)(?:这?[一二两三四五六七八九]?个?字|二字|两字|三字)?\s*"
                          r"(?:突然|明显|狠狠|轻轻)?(?:落重|加重|重读|咬重|咬字|压低|放慢|压到耳语|由轻转稳|拖长|前停顿|停顿|说得清楚|干脆收住)")


#: the same stress / pacing note with its word removed -- what the voice does, never which words (lab A/B 2026-11-26:
#: a Delivery that names or paraphrases the stressed words -- "stresses saving him first", "becomes steady on going to
#: find him" -- went with burned subtitles in 12 of 14 E28 clips; voice-only Delivery: 3 of 8 -- fewer, not none)
_WORDED_NOTE = re.compile(r"(?:在)?(?P<word>[㐀-鿿]{1,8}?)(?:这?[一二两三四五六七八九]?个?字|二字|两字|三字)?\s*前?"
                          r"(?P<voice>(?:突然|明显|狠狠|轻轻)?(?:落重|加重|重读|咬重|咬字|压低|放慢|压到耳语|由轻转稳|拖长|"
                          r"停顿|说得清楚|干脆收住))")


#: a note that points at a part of the line without quoting it (后半句 / 药名 / 最后一句 …) points at the words too
_LINE_PART = re.compile(r"半句|一句|几个字|两个字|句尾|句首|药名|人名|名字|名号|这个词|那个词|称呼")


def voice_only(note: str, line: str = "") -> str:
    """A delivery note without the words of ``line`` it points at: 「截住推想，先救他三个字落重」 -> 「截住推想，落重」
    (「困惑地放慢」 stays: 困惑地 is not in the line); quoted words go too.  The full note stays in the data and the
    directing script (and feeds :func:`stress_word`)."""
    text = _ANCHOR.sub("", str(note or ""))

    def drop(m: re.Match) -> str:
        word = m.group("word")
        return m.group("voice") if _in_line(word, line or "") or _LINE_PART.search(word) else m.group(0)

    clauses = [_WORDED_NOTE.sub(drop, clause.strip()) for clause in re.split(r"[，,；;]", text)]
    return "，".join(c for c in clauses if c)


def parse_authored(body: str) -> dict[str, str]:
    """``要=… | 压=… | …`` -> {want, hide, leak, crack, visible, end, listener} (unknown keys ignored)."""
    out: dict[str, str] = {}
    for part in re.split(r"\s*[|｜]\s*", str(body or "").strip()):
        key, sep, value = part.partition("=")
        if not sep:
            key, sep, value = part.partition("＝")
        field = PERF_KEYS.get(key.strip()) or PERF_KEYS.get(key.strip().lower())
        value = " ".join(value.split())
        if sep and field and value:
            out[field] = "；".join(x for x in (out.get(field), value) if x)
    return out


def strip_anchor(text: str) -> str:
    """The crack without its word anchor (「到"救他"时声音发紧」 -> 「声音发紧」): what goes to the translator / H3."""
    return _ANCHOR.sub("", str(text or "")).strip("，,；; ")


def _in_line(candidate: str, line: str) -> str:
    """``candidate`` if it occurs in ``line``, else its longest substring (>= 2 chars) that does, else ''."""
    if candidate and candidate in line:
        return candidate
    for size in range(len(candidate) - 1, 1, -1):
        for start in range(0, len(candidate) - size + 1):
            piece = candidate[start:start + size]
            if piece in line:
                return piece
    return ""


def stress_word(line: str, paren: str = "", crack: str = "") -> tuple[str, int, str]:
    """(word, index in line, source) from the WRITER's stress note: the crack's quoted anchor first, then the
    parenthetical's stress / pacing note (落重 / 加重 / 压低 / 停顿 …).  ('', 0, '') when the writer gave none."""
    line = line or ""
    for source, text in (("crack", crack), ("paren", paren)):
        pattern = _ANCHOR if source == "crack" else _STRESS_NOTE
        for m in pattern.finditer(str(text or "")):
            word = _in_line(m.group("word"), line)
            if word:
                return word, line.find(word), source
    return "", 0, ""


def build_authored(*, who: str, authored: dict[str, str], authored_en: dict[str, str], line: str,
                   paren: str = "", emotion: str = "", emotion_en: str = "", listener_name: str = "",
                   arc: dict[str, str] | None = None, arc_en: dict[str, str] | None = None,
                   curve: EmotionCurve | None = None, lead_in: bool = False) -> dict[str, Any]:
    """The unit's performance from the writer's ``@演`` block: ENTRY (this character's previous exit in the scene,
    else the ``@arc`` entry, else what they hold back) -> CHANGE (the leak, then the crack) -> EXIT (the end state).
    English beats come from the writer's twins only (no lexicon text); the curve still chains exit -> entry."""
    curve = curve if curve is not None else EmotionCurve()
    arc, arc_en = arc or {}, arc_en or {}
    word, index, source = stress_word(line, paren, authored.get("crack", ""))
    at = _spoken_fraction(line, index) if word else 0.5
    start = 0.3 if lead_in else 0.0
    t_change = round(min(0.6, max(start + 0.15, start + (1.0 - start) * at)), 2)
    t_exit = round(min(0.85, max(t_change + 0.2, 0.75)), 2)
    prev = curve.last.get(who)
    if prev:
        entry = {"zh": f"接上一句的状态：{prev['exit_zh']}", "en": prev.get("exit_en") or ""}
        note = "carried"
    elif arc.get("entry"):
        entry = {"zh": arc["entry"], "en": arc_en.get("entry", "")}
        note = "arc_entry"
    else:
        entry = {"zh": f"压着：{authored.get('hide', '')}" if authored.get("hide") else "",
                 "en": authored_en.get("hide", "")}
        note = "scene_start"
    change_zh = "；".join(x for x in (authored.get("leak"), authored.get("crack")) if x)
    change_en = "; then ".join(x for x in (authored_en.get("leak"), authored_en.get("crack")) if x)
    exit_state = {"zh": authored.get("end") or arc.get("exit") or "",
                  "en": authored_en.get("end") or arc_en.get("exit") or ""}
    beats = [
        {"from": start, "to": t_change, "kind": "ENTRY", "zh": entry["zh"], "en": entry["en"]},
        {"from": t_change, "to": t_exit, "kind": "CHANGE", "trigger_word": word, "trigger_at": t_change,
         "zh": (f"到「{word}」时：" if word else "") + change_zh, "en": change_en},
        {"from": t_exit, "to": 1.0, "kind": "EXIT", "zh": "收尾定格：" + exit_state["zh"], "en": exit_state["en"]},
    ]
    curve.last[who] = {"emotion": emotion, "emotion_en": emotion_en, "stage": stage_of(emotion),
                       "exit_zh": exit_state["zh"], "exit_en": exit_state["en"]}
    return {"schema": SCHEMA, "source": "writer", "emotion": emotion, "stage": stage_of(emotion), "curve": note,
            "trigger_word": word, "trigger_source": source or "none", "disfluency": None, "beats": beats}


__all__ = ["SCHEMA", "EmotionCurve", "PERF_FIELDS", "build", "build_authored", "parse_authored", "strip_anchor",
           "stress_word", "voice_only", "emotion_row", "lexicon", "psychology", "stage_of", "trigger_word",
           "zh_summary"]
