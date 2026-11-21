#!/usr/bin/env python3
"""PERFORMANCE_VARIETY_V1: concrete, varied physical business for every dialogue beat (pure, free, planner level).

Line owner 2026-11-20 (JA-01 anime E02): "while characters speak there are almost no small movements, and when
there are, they're all the same -- in this episode it's always both hands spread out to the sides."  H3 fills an
unspecified speaking beat with one stock gesture.  The writer's ``performance.body_action`` is Chinese (the H3
DIRECTOR_PROMPT_V2 never sees it) and ``delivery_en`` directs only the voice, so the prompt gave H3 nothing to do
with the body.

This module walks an episode's shots in order and gives each dialogue shot

* ``action.performance_business_en`` -- one beat-motivated physical business + micro-expression for the speaker
  (e.g. "glances away for a beat, then looks back"), chosen from a gesture vocabulary keyed by the line's intent /
  emotion and the shot scale (a close-up gets face business, hands only from a medium shot outward), preferring the
  character's own ``mannerisms`` (optional English phrases on the character entity);
* ``action.listener_business_en`` -- {character_id: reactive business} for every other visible person (nods once,
  shifts weight, eyes track the speaker ...) instead of a frozen pose;

with an episode-level tracker: no gesture family repeats within ``WINDOW`` (4) consecutive dialogue units, no family
is used more than ``SCENE_CAP`` (2) times in one scene, and the stock "both palms spread outward / open-arms shrug" is
never chosen unless the beat itself calls for it (shrug / helpless / pleading wording).  An authored English
``performance.business_en`` always wins (its family is still counted); a Chinese ``body_action`` is mapped to its
family's English phrase when its words name one.

Only English, language- and style-agnostic wording; nothing here gates anything.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any, Iterable

SCHEMA = "qingshan.performance_variety.v1"
POLICY = "PERFORMANCE_VARIETY_V1"
WINDOW = 4
SCENE_CAP = 2
STOCK_FAMILY = "palms_open"
#: Never-line item of a prompt that carries business (h3_director_prompt_v2)
NEVER_STOCK = "repeated stock hand-spreading gestures (both palms spread outward, open-arms shrugs)"

FACE, HANDS, BODY = "face", "hands", "body"
#: family -> (phrase, framing need, intents).  Phrases are body-only: they never invent a prop or a garment detail.
VOCAB: dict[str, tuple[str, str, tuple[str, ...]]] = {
    "glance_away": ("glances away for a beat, then looks back", FACE, ("doubt", "sad", "fear", "shy", "neutral")),
    "head_tilt": ("tilts the head slightly", FACE, ("doubt", "smug", "neutral", "pleading")),
    "exhale": ("lets out a small exhale through the nose before the words", FACE, ("cold", "sad", "smug", "neutral")),
    "jaw_set": ("sets the jaw", FACE, ("anger", "determined", "cold")),
    "brow_raise": ("raises one eyebrow", FACE, ("doubt", "smug", "surprise")),
    "lip_press": ("presses the lips together for a beat before speaking", FACE, ("sad", "fear", "determined", "anger")),
    "eyes_narrow": ("narrows the eyes", FACE, ("doubt", "anger", "cold")),
    "small_nod": ("gives one small nod on the key word", FACE, ("determined", "neutral", "smug")),
    "chin_lift": ("lifts the chin a little", FACE, ("cold", "smug", "determined", "anger")),
    "cuff": ("adjusts one cuff with the other hand", HANDS, ("cold", "smug", "neutral", "determined")),
    "fold_arms": ("folds the arms across the chest", HANDS, ("cold", "smug", "doubt", "anger")),
    "throat_touch": ("touches the base of the throat with two fingers", HANDS, ("fear", "sad", "shy", "doubt")),
    "fist": ("slowly closes one hand into a fist at the side", HANDS, ("anger", "determined", "fear")),
    "point": ("points once with one finger, then lowers the hand", HANDS, ("anger", "determined")),
    "hand_chest": ("presses one hand flat to the chest", HANDS, ("pleading", "sad", "surprise", "shy")),
    "finger_rub": ("rubs the thumb against the fingertips", HANDS, ("fear", "doubt", "shy")),
    "step_closer": ("takes a half step closer", BODY, ("anger", "determined", "pleading", "smug")),
    "lean_in": ("leans in slightly from the waist", BODY, ("anger", "pleading", "determined", "doubt")),
    "lean_back": ("leans back a little", BODY, ("smug", "cold", "surprise")),
    "shoulders_drop": ("lets the shoulders drop slightly", BODY, ("sad", "neutral", "fear")),
    "weight_shift": ("shifts weight onto one foot", BODY, ("neutral", "doubt", "shy")),
    STOCK_FAMILY: ("spreads both palms outward", HANDS, ("pleading",)),
}
#: listeners: reactive, mouth closed (never a mouth movement H3 could lip-sync)
LISTENER_VOCAB: dict[str, str] = {
    "nod": "nods once, slowly",
    "eyes_track": "keeps the eyes on the speaker, blinking once",
    "weight_shift": "shifts weight, the shoulders settling",
    "brow_knit": "draws the brows together a little",
    "breath": "takes a slow breath",
    "look_down": "looks down for a moment, then back up",
    "head_turn": "turns the head slightly toward the speaker",
    "stillness_hands": "tightens the fingers slightly at the side",
}
#: shot scales: which framing needs are visible
_FACE_ONLY = {"EXTREME_CLOSE_UP", "ECU", "CLOSE_UP", "CU", "INSERT"}
_NO_BODY = _FACE_ONLY | {"MEDIUM_CLOSE_UP", "MCU"}

#: intent words (lower-case en / zh / ja / ko; zh singles follow PERFORMANCE_EMOTION_LEXICON_v1)
_INTENT_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("anger", ("angry", "anger", "furious", "rage", "fierce", "怒", "狠", "急", "恨", "怒り", "화")),
    ("fear", ("afraid", "fear", "scared", "panic", "frighten", "nervous", "anxious", "惧", "怕", "慌", "怯", "恐", "不安",
              "두려")),
    ("sad", ("sad", "grief", "grieving", "sorrow", "weary", "regret", "hurt", "哀", "悲", "悔", "倦", "愧", "怜", "悲し",
             "슬")),
    ("pleading", ("plead", "beg", "implor", "helpless", "盼", "求", "頼", "부탁")),
    ("doubt", ("doubt", "suspicious", "question", "probing", "puzzled", "skeptic", "疑", "問", "의심")),
    ("smug", ("smug", "mock", "tease", "amused", "playful", "haughty", "contempt", "讥", "嘲", "傲", "戏", "喜", "乐",
              "得意", "笑")),
    ("cold", ("cold", "icy", "flat", "deadpan", "detached", "冷", "厌", "淡")),
    ("determined", ("resolute", "determined", "firm", "insist", "commanding", "坚", "定", "決")),
    ("surprise", ("surprise", "shock", "startled", "stunned", "惊", "驚", "놀")),
    ("shy", ("shy", "embarrass", "bashful", "羞", "照れ", "수줍")),
)
#: the beat itself asks for the stock gesture
_STOCK_CALLED = re.compile(r"shrug|helpless|spread(?:s|ing)? (?:both |his |her |their )?(?:hands|palms|arms)"
                           r"|open[- ]arm|摊手|摊开双手|耸肩|无奈|肩をすく|両手を広げ|어깨를 으쓱", re.IGNORECASE)
#: any text that names the stock gesture (authored business is counted as that family)
_STOCK_TEXT = re.compile(r"(?:spread|open|throw)s?\w* (?:out )?(?:both |his |her |their )?(?:hands|palms|arms)"
                         r"|palms? (?:spread|out|up)|open[- ]arm|shrug|摊手|摊开|張開雙手|张开双手|张开双臂|両手を広げ",
                         re.IGNORECASE)
#: authored body text -> family (zh / en keywords)
_FAMILY_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("cuff", ("cuff", "sleeve", "袖")),
    ("fold_arms", ("fold", "cross the arms", "crossed arms", "抱臂", "抱胸", "环抱", "腕を組")),
    ("fist", ("fist", "clench", "握拳", "攥", "捏紧")),
    ("point", ("point", "指着", "指向")),
    ("glance_away", ("glance away", "looks away", "移开视线", "别过脸", "侧过脸", "目を逸ら")),
    ("head_tilt", ("tilt", "歪头", "偏头")),
    ("exhale", ("exhale", "sigh", "叹", "呼出", "吐气", "ため息")),
    ("jaw_set", ("jaw", "咬牙", "咬紧")),
    ("brow_raise", ("eyebrow", "挑眉")),
    ("lip_press", ("press the lips", "presses the lips", "抿嘴", "抿唇", "咬唇")),
    ("eyes_narrow", ("narrow", "眯眼", "眯起")),
    ("step_closer", ("step closer", "steps closer", "step forward", "上前", "逼近", "走近", "踏前")),
    ("lean_in", ("lean in", "leans in", "lean forward", "前倾", "凑近", "俯身")),
    ("lean_back", ("lean back", "leans back", "后仰", "往后靠")),
    ("hand_chest", ("hand to the chest", "hand on the chest", "按住胸口", "捂胸", "抚胸")),
    ("throat_touch", ("throat", "necklace", "collar", "领口", "项链", "喉")),
    ("shoulders_drop", ("shoulders drop", "slump", "垂肩", "肩膀一垮", "塌肩")),
    ("small_nod", ("nod", "点头")),
    ("chin_lift", ("chin", "抬下巴", "扬起下巴", "仰头")),
    ("weight_shift", ("shift weight", "shifts weight", "重心")),
    ("finger_rub", ("fingertip", "搓手指", "捻")),
)
_CJK = re.compile(r"[぀-ヿ㐀-鿿가-힣]")


def intent_of(*texts: Any) -> str:
    """The beat's intent key from emotion / delivery / line text; '?' -> doubt, '!' -> anger; else neutral."""
    joined = " ".join(str(t or "") for t in texts)
    low = joined.lower()
    hits = [(low.find(w.lower()), key) for key, words in _INTENT_WORDS for w in words if w.lower() in low]
    if hits:
        return sorted(hits)[0][1]
    if re.search(r"[？?]", joined):
        return "doubt"
    if re.search(r"[！!]", joined):
        return "anger"
    return "neutral"


def family_of(text: Any) -> str | None:
    """The gesture family an authored business / body text names (stock first), or None."""
    value = str(text or "")
    if _STOCK_TEXT.search(value):
        return STOCK_FAMILY
    low = value.lower()
    for family, words in _FAMILY_WORDS:
        if any(w.lower() in low for w in words):
            return family
    return None


def _scale_allows(need: str, scale: str) -> bool:
    scale = str(scale or "").upper()
    if need == FACE:
        return True
    if need == HANDS:
        return scale not in _FACE_ONLY
    return scale not in _NO_BODY


def _english(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split()).strip().rstrip(".;, ")
    if not text or _CJK.search(text):
        return ""
    return text[:limit]


def _seed(*parts: Any) -> int:
    return int(hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:8], 16)


class Tracker:
    """Episode-level gesture memory: the last WINDOW dialogue units' families and the per-scene counts."""

    def __init__(self, window: int = WINDOW, scene_cap: int = SCENE_CAP) -> None:
        self.window, self.scene_cap = int(window), int(scene_cap)
        self.recent: list[str] = []
        self.scene_counts: dict[str, Counter] = {}
        self.listener_recent: list[str] = []

    def blocked(self, family: str, scene: str) -> bool:
        return family in self.recent[-(self.window - 1):] if self.window > 1 else False

    def capped(self, family: str, scene: str) -> bool:
        return self.scene_counts.get(scene, Counter())[family] >= self.scene_cap

    def use(self, family: str | None, scene: str) -> None:
        if not family:
            return
        self.recent.append(family)
        self.scene_counts.setdefault(scene, Counter())[family] += 1

    def choose(self, *, intent: str, scale: str, scene: str, seed: int, stock_called: bool = False,
               mannerisms: Iterable[str] = ()) -> tuple[str, str]:
        """(family, phrase).  Order: the character's mannerisms, then the families of this intent, then any family
        the framing shows; within each tier the first one neither repeated in the window nor capped in the scene
        (rotated by ``seed`` so equal beats differ); last resort the least-used allowed family."""
        tiers: list[list[tuple[str, str]]] = []
        own = [(f"mannerism:{i}", m) for i, m in enumerate(_english(x) for x in mannerisms or []) if m]
        if own:
            tiers.append(own)
        allowed = [(f, VOCAB[f][0]) for f in VOCAB
                   if _scale_allows(VOCAB[f][1], scale) and (f != STOCK_FAMILY or stock_called)]
        if stock_called:
            tiers.append([(f, p) for f, p in allowed if f == STOCK_FAMILY])
        tiers.append([(f, p) for f, p in allowed if intent in VOCAB[f][2]])
        tiers.append(allowed)
        for tier in tiers:
            if not tier:
                continue
            start = seed % len(tier)
            for f, p in tier[start:] + tier[:start]:
                if not self.blocked(f, scene) and not self.capped(f, scene):
                    return f, p
        pool = [x for x in allowed if x[0] != STOCK_FAMILY] or allowed
        counts = self.scene_counts.get(scene, Counter())
        return min(pool, key=lambda fp: (fp[0] in self.recent[-(self.window - 1):], counts[fp[0]], fp[0]))

    def choose_listener(self, seed: int, scale: str) -> tuple[str, str]:
        keys = [k for k in LISTENER_VOCAB if scale.upper() not in _FACE_ONLY or k not in ("weight_shift", "stillness_hands")]
        start = seed % len(keys)
        for k in keys[start:] + keys[:start]:
            if k not in self.listener_recent[-2:]:
                self.listener_recent.append(k)
                return k, LISTENER_VOCAB[k]
        k = keys[start]
        self.listener_recent.append(k)
        return k, LISTENER_VOCAB[k]


def _speaker_id(spec: dict[str, Any]) -> str:
    role = spec.get("role_semantic_disambiguation") or {}
    return str(role.get("lip_owner_id") or role.get("dialogue_speaker_id") or "")


def assign_episode(shots: list[dict[str, Any]], entities: dict[str, dict[str, Any]] | None = None, *,
                   window: int = WINDOW, scene_cap: int = SCENE_CAP) -> dict[str, Any]:
    """In place over editorial shots (``{shot_id, scene_id, prompt_spec}``, episode order): every dialogue shot whose
    speaker is on screen gets ``prompt_spec.action.performance_business_en`` (+ ``performance_business_family``) and,
    when other people are visible, ``listener_business_en``.  Returns the receipt (one row per dialogue shot)."""
    entities = entities or {}
    tracker = Tracker(window, scene_cap)
    rows: list[dict[str, Any]] = []
    for shot in shots or []:
        spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
        dialogue = str(spec.get("dialogue") or "").strip()
        action = spec.get("action") if isinstance(spec.get("action"), dict) else None
        if not dialogue or action is None:
            continue
        sid, scene = str(shot.get("shot_id") or ""), str(shot.get("scene_id") or "")
        speaker = _speaker_id(spec)
        cast = [m for m in spec.get("cast") or [] if isinstance(m, dict)]
        visible = [str(m.get("character_id") or "") for m in cast
                   if str(m.get("face_visibility") or "").upper() != "OFFSCREEN_VOICE_ONLY" and m.get("character_id")]
        if not speaker or speaker not in visible:
            continue  # an offscreen / V.O. speaker has no body on screen
        performance = action.get("performance") if isinstance(action.get("performance"), dict) else {}
        scale = str((spec.get("camera_plan") or {}).get("shot_scale") or shot.get("shot_size") or "")
        beat_text = " ".join(str(x or "") for x in (performance.get("delivery_en"), performance.get("body_action"),
                                                    action.get("primary_action"), dialogue))
        intent = intent_of(performance.get("emotion"), performance.get("delivery_en"), dialogue)
        stock_called = bool(_STOCK_CALLED.search(beat_text))
        authored = _english(performance.get("business_en"))
        source = "AUTHORED_BUSINESS_EN"
        family = family_of(authored) if authored else None
        if authored and family == STOCK_FAMILY and not stock_called:
            authored, family, source = "", None, "AUTHORED_STOCK_REPLACED"
        if not authored:
            mapped = family_of(performance.get("body_action"))
            if (mapped and mapped in VOCAB and _scale_allows(VOCAB[mapped][1], scale)
                    and (mapped != STOCK_FAMILY or stock_called)
                    and not tracker.blocked(mapped, scene) and not tracker.capped(mapped, scene)):
                family, authored, source = mapped, VOCAB[mapped][0], "AUTHORED_BODY_ACTION_MAPPED"
        if not authored:
            ent = entities.get(speaker) or {}
            family, authored = tracker.choose(intent=intent, scale=scale, scene=scene, seed=_seed(sid, speaker),
                                              stock_called=stock_called, mannerisms=ent.get("mannerisms") or [])
            source = ("MANNERISM" if family.startswith("mannerism:") else
                      source if source == "AUTHORED_STOCK_REPLACED" else "VOCABULARY")
            if family.startswith("mannerism:"):
                family = f"mannerism:{speaker}:{family.split(':', 1)[1]}"
        tracker.use(family, scene)
        action["performance_business_en"] = authored
        action["performance_business_family"] = family
        listeners: dict[str, str] = {}
        if not action.get("listener_reaction_en"):
            for index, cid in enumerate(c for c in visible if c != speaker):
                _key, phrase = tracker.choose_listener(_seed(sid, cid, index), scale)
                listeners[cid] = phrase
            if listeners:
                action["listener_business_en"] = listeners
        rows.append({"shot_id": sid, "scene_id": scene, "speaker_id": speaker, "intent": intent, "scale": scale,
                     "family": family, "business_en": authored, "source": source,
                     **({"listeners": listeners} if listeners else {})})
    return {"schema": SCHEMA, "policy": POLICY, "window": window, "scene_cap": scene_cap, "rows": rows,
            "violations": variety_violations(rows, window=window, scene_cap=scene_cap)}


def variety_violations(rows: list[dict[str, Any]], *, window: int = WINDOW, scene_cap: int = SCENE_CAP) -> list[str]:
    """Repeats inside the window, per-scene overuse and unmotivated stock gestures in an assignment receipt
    (authored business may cause them; the receipt reports, nothing blocks)."""
    out: list[str] = []
    fams = [str(r.get("family") or "") for r in rows]
    for i, fam in enumerate(fams):
        if fam and fam in fams[max(0, i - window + 1):i]:
            out.append(f"REPEAT_WITHIN_{window}:{rows[i]['shot_id']}:{fam}")
    per_scene: dict[str, Counter] = {}
    for r in rows:
        per_scene.setdefault(str(r.get("scene_id")), Counter())[str(r.get("family"))] += 1
    for scene, counts in per_scene.items():
        out.extend(f"SCENE_CAP:{scene}:{fam}:{n}" for fam, n in counts.items() if fam and n > scene_cap)
    out.extend(f"STOCK_GESTURE:{r['shot_id']}" for r in rows
               if r.get("family") == STOCK_FAMILY and r.get("source") != "AUTHORED_BUSINESS_EN")
    return out


def business_sentence(label: str, business: Any) -> str:
    """"While speaking, <label> <business>." ('' without English business)."""
    text = _english(business)
    if not text or not label:
        return ""
    text = re.sub(rf"^{re.escape(label)}\s+", "", text, flags=re.IGNORECASE)
    return f"While speaking, {label} {text[0].lower() + text[1:]}."


def listener_sentence(label: str, business: Any) -> str:
    text = _english(business)
    if not text or not label:
        return ""
    return f"{label} listens without speaking and {text[0].lower() + text[1:]}."
