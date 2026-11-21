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
    then face drift, then skin sheen, then hands (HAND_ARTIFACT, multi-pass Gemini QA-HAND-ARTIFACT), each by
    on-screen duration.
* ``RECORD_ONLY`` -- pacing, story, length shortfall, voice collision, ASR mismatch, look-alike cast, letterbox,
  oversized mask and anything else: recorded in ``final_fix_round.json`` and the S8 summary, never acted on.

v2 (2026-11-20, first real run E18 on device 1101):

* findings are DEDUPED (same kind, window +-1 s) across the checklist, confirmed-Gemini and reviewer-problem paths
  before planning and counting (:func:`dedupe`); wording that names model-burned text is BURNED_TEXT on any path
  (:func:`strong_kind`), as is face drift / identity swap / skin sheen wording under a record-only item;
* a BURNED_TEXT redo take is measured with the S6 detector and retried up to twice with an escalated request
  (retry-indexed clean-picture sentence + 1-2 % crop/scale jitter of @Image1 at a new JPEG quality) inside the
  round's budget, keeping the best take (:func:`plan_burn_retry`, :func:`round_budget_left`);
* after the second review every first finding is RESOLVED / PERSISTS / UNVERIFIED and the second review's NEW
  findings are listed (:func:`reconcile`); "unresolved" = PERSISTS + NEW;
* a speaker / voice gender mismatch (VOICE_GENDER_MISMATCH) is checked against the unit's speaker_voice_contract
  (:func:`voice_assignment_check`): a mapping bug is reported, never auto-fixed (H3 voices natively);
* a clipped tail that survives the wider guard gets its measured cause (:func:`tail_cut_cause`).

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
PAID_KINDS = ("BURNED_TEXT", "COSTUME_IDENTITY", "FACE_DRIFT", "SKIN_SHEEN", "HAND_ARTIFACT")
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
    # multi-pass Gemini review classes (gemini_review_passes.py, 2026-11-20).  Picture defects a re-render can fix
    # -> paid redo; sound -> free S7 re-mix where a tool exists, else record; continuity / AI artefacts a redo
    # cannot target reliably and every CRAFT-* (direction, pacing, story) -> record + knowledge base
    "QA-FACE-ARTIFACT": "FACE_DRIFT",
    "QA-IDENTITY-MISMATCH": "FACE_DRIFT",
    "QA-HAND-ARTIFACT": "HAND_ARTIFACT",
    "QA-BODY-MORPH": "AI_ARTIFACT",
    "QA-OBJECT-POP": "AI_ARTIFACT",
    "QA-FLICKER": "AI_ARTIFACT",
    "QA-PHYSICS": "AI_ARTIFACT",
    "QA-PROP-CONTINUITY": "CONTINUITY",
    "QA-LIGHTING-CONTINUITY": "CONTINUITY",
    "QA-POSITION-CONTINUITY": "CONTINUITY",
    "QA-LIPSYNC": "ASR_MISMATCH",
    "QA-VOICE-INCONSISTENT": "VOICE",
    "QA-WRONG-SPEAKER": "VOICE",
    "QA-LOUDNESS-JUMP": "AUDIO_SMOOTHING",
    "QA-AUDIO-ARTIFACT": "AUDIO_SMOOTHING",
    "QA-SFX": "SFX",
    "CRAFT-PACING": "PACING",
    "CRAFT-SHOT-GRAMMAR": "SHOT_GRAMMAR",
    "CRAFT-BEAT-MISSED": "STORY",
    "CRAFT-CLARITY": "STORY",
    "CRAFT-OPENING-HOOK": "HOOK",
    "CRAFT-ENDING-HOOK": "HOOK",
    "CRAFT-EMOTION": "EMOTION",
    "CRAFT-SUBTITLE-READABILITY": "SUBTITLE_READABILITY",
}

#: (kind, keywords) in priority order; the first match wins.  Lower-case English + Chinese.
KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("LOOKALIKE", ("look alike", "lookalike", "look-alike", "same face as", "长得一样", "长得几乎一样", "撞脸")),
    ("BURNED_TEXT", ("burned-in", "burnt-in", "burned text", "burned caption",
                     "burned subtitle", "on-screen text", "onscreen text", "stray text", "garbled text",
                     "stray caption", "second subtitle", "text overlay", "stray glyph", "烧进", "烧录", "烧入",
                     "画面里的字", "画面文字", "乱码", "多余字幕", "多出一行字", "模型字幕", "字幕重影")),
    ("COSTUME_IDENTITY", ("costume", "wardrobe", "outfit", "clothing", "clothes", "garment", "identity colo",
                          "colour mismatch", "color mismatch", "changes colo", "different colo", "服装", "衣服",
                          "换装", "服色", "衣色", "戏服", "颜色不一致", "颜色变")),
    ("SKIN_SHEEN", ("oily", "greasy", "glossy skin", "shiny skin", "skin sheen", "sweaty", "wet hair",
                    "wet-looking hair", "over-sharpen", "oversharpen", "crunchy texture", "油光", "油腻", "抹了油",
                    "出油", "满脸汗", "冒汗", "头发湿", "湿发", "过锐", "锐化过度", "过度锐化")),
    ("FACE_DRIFT", ("face drift", "face changes", "face changed", "different face", "wrong face", "face swap",
                    "face does not match", "face doesn't match", "identity drift", "looks like a different",
                    "脸变", "换脸", "脸不一样", "长相变", "面部漂移", "不像同一个人", "五官变",
                    # in-shot identity swap (JA-01 anime E01 2026-11-20): the person on screen morphs into another
                    "transforms into", "turns into another", "turns into a different", "morphs into",
                    "becomes another character", "becomes a different character", "identity swap",
                    "变成另一个", "变成了另一个", "变成别人", "变成了别人")),
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
    "HAND_ARTIFACT": ("Every hand has a natural shape with five separate fingers from the first frame to the last; "
                      "fingers never merge, bend wrongly or pass through objects."),
    "SKIN_SHEEN": ("Every face keeps natural matte skin and dry hair from the first frame to the last: no oily, glossy "
                   "or sweaty sheen, no wet-looking strands and no harsh over-sharpened skin texture."),
}
#: burned-text redo retry n (escalation, 2026-11-20 E18: three of four redone units burned the same line again):
#: each retry words the clean-picture sentence differently, so the prompt (and the request) differs from every take
#: before it; never the S6 retry sentences (h3_burn_retry.RETRY_SENTENCES) or SENTENCES["BURNED_TEXT"]
BURN_RETRY_SENTENCES = {
    1: ("The image carries no writing of any sort: the spoken line lives only in the soundtrack, and the lower "
        "half of every frame shows only clothing, hands and the set."),
    2: ("Treat the frame as a clean film negative with no titles: no letter, character, caption bar or written "
        "word is ever drawn over the scene, from the first frame to the last."),
}
#: retries of a fix-round burned-text redo (detection-triggered, inside NALU_FINAL_FIX_BUDGET_CREDITS)
FIX_BURN_RETRY_MAX = 2
FIX_BURN_RETRY_ENV = "NALU_FINAL_FIX_BURN_RETRY_MAX"
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


# ------------------------------------------------------------------ strong wording (any path, any item)
#: model-burned on-screen text, whatever the path / item says (E18 2026-11-20: a reviewer problem "model-burned
#: '劳烦师兄了' at 32.75 s" fell through to OTHER / record-only).  Our own subtitles are never "burned" and never
#: "in the picture" in these words, so the patterns stay specific to text the model drew into the frame.
_BURN_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"burn(?:ed|t)-in\b", r"burn(?:ed|t)\s+(?:in(?:to)?|onto)\s+(?:the\s+)?(?:picture|frame|image|video|clip|shot)\b",
    r"model[- ]?(?:burn(?:ed|t)?|drawn|rendered|generated)\b.{0,24}(?:text|caption|subtitle|line|letter|word|glyph|字|[\"'“「『])",
    r"burn(?:ed|t)\s+(?:in(?:to)?\s+)?(?:the\s+)?(?:text|caption|subtitle|line|lettering|words?|glyphs?|dialogue)",
    r"(?:text|caption|subtitle|lettering|words?|glyphs?)\s+(?:is |are |was |were |gets? |got )?burn(?:ed|t)\b",
    r"(?:lettering|text|writing|words)\b.{0,30}\b(?:in|into|on) (?:the |its )?(?:picture|frame|image)\b",
    r"(?:quoted|spoken|dialogue) line\b.{0,30}\b(?:rendered|written|drawn|shown|appears?) (?:on[- ]?screen|in (?:the )?(?:picture|frame))",
    r"(?:rendered|written|drawn|printed|painted) (?:on[- ]?screen|in(?:to)? (?:the )?(?:picture|frame|image))",
    r"on[- ]?screen (?:text|lettering|words?|glyphs?)", r"(?:stray|extra|second|duplicate|garbled|model) (?:caption|subtitle|text)",
    r"text overlay",
    r"烧(?:字|进|入|录|在|上|到|出|着)", r"字幕上叠", r"叠(?:了|着)?(?:一行|一串)?(?:字(?!幕)|文字|台词)",
    r"画面(?:里|中|上|内)(?:的|出现|有|浮现|多出|多了|显示)?(?:了|一行|一串|几个)?(?:字(?!幕)|文字|台词|字样)",
    r"屏幕(?:里|中|上)(?:的|出现|有|浮现|显示)?(?:了|一行)?(?:字(?!幕)|文字|台词)",
    r"(?:出现|浮现|多出|多了)(?:了)?(?:一行|一串|几个)?(?:文字|字样)", r"(?:多余|额外|模型|第二(?:行|条)?)(?:生成)?(?:的)?字幕",
    r"(?:台词|对白)[^。；;]{0,14}(?:显示|出现|写|印)在(?:画面|屏幕)",
))
#: burned-text keywords of KEYWORDS strong enough to override an item ("多出一个" also means an extra person)
_BURN_STRONG_WORDS = tuple(w for w in dict(KEYWORDS)["BURNED_TEXT"]
                           if w not in ("乱码",))
#: our own subtitles are "captions" too: on a subtitle item the burned override needs an explicit model / extra mark
_SUBTITLE_ITEMS = ("QA-SUBTITLE-WRAP", "CRAFT-SUBTITLE-READABILITY")
_MODEL_MARK = re.compile(r"model|模型|stray|extra|second|duplicate|多余|额外|第二|重影|烧", re.IGNORECASE)
#: identity / face drift wording beyond KEYWORDS (also when the item names a record-only class)
_FACE_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"face (?:drift|chang|morph|shift|swap)", r"(?:different|another|wrong) (?:face|person|actor|actress)",
    r"identity (?:drift|swap|change|mismatch)", r"(?:facial )?features (?:change|shift|morph)",
    r"(?:morph|transform|turn)s? into (?:another|a different|someone)", r"no longer looks like",
    r"脸(?:变|型变|不一样|不像|换)", r"(?:相貌|面容|长相|五官)(?:变|不一致|不一样)", r"换(?:了)?(?:一个人|个人|脸)",
    r"(?:变成|成了)(?:了)?(?:另一个|别人|另一人)", r"不像(?:同一个人|本人)", r"身份(?:漂移|错乱|互换)",
))
#: skin sheen wording beyond KEYWORDS
_SHEEN_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"(?:oily|greasy|glossy|shiny|waxy|plastic|sweaty|wet)[- ](?:looking )?(?:skin|face|forehead|complexion|sheen)",
    r"skin (?:sheen|shine|looks (?:oily|greasy|wet|plastic|waxy))", r"(?:wet|damp)[- ](?:looking )?hair",
    r"油(?:光|亮|腻)", r"(?:皮肤|脸上|额头)(?:发亮|反光|油)", r"满脸(?:油|汗)", r"汗津津", r"(?:头发|发丝)(?:湿|潮)",
))
#: speaker / voice gender mismatch (E18 2026-11-20 P1: "a woman on screen is given a low male voice line")
_VOICE_GENDER_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"(?:woman|girl|female|lady|she)\b.{0,40}\b(?:male|man's|men's|masculine|deep|low) voice",
    r"(?:man|boy|male|he)\b.{0,40}\b(?:female|woman's|feminine|girl's|high-pitched) voice",
    r"(?:male|female|masculine|feminine) voice\b.{0,40}\b(?:woman|girl|man|boy|female|male)\b",
    r"voice (?:gender|sex) (?:mismatch|wrong)", r"(?:gender|sex)[- ](?:mismatch|wrong)\b.{0,20}voice",
    r"(?:女|女性|女子|女人|姑娘|女孩|她)[^。；;]{0,16}(?:男声|男性声|男人的声|男子的声|低沉的男)",
    r"(?:男|男性|男子|男人|他)[^。；;]{0,16}(?:女声|女性声|女人的声|女子的声)",
    r"(?:男声|女声)[^。；;]{0,10}(?:配给|配在|给了|安在)", r"声音(?:与|和)?(?:角色)?性别不符", r"性别(?:不符|错)",
))


def _matches(patterns: tuple[re.Pattern[str], ...], text: str) -> bool:
    return any(p.search(text) for p in patterns)


def strong_kind(text: str) -> str | None:
    """The kind a finding's wording names beyond doubt (burned text first, then voice gender, identity / face drift
    and skin sheen), or None.  Used whatever the path or item, so a reviewer-problem / Gemini OTHER finding that
    describes model-burned text is never record-only."""
    text = str(text or "")
    low = text.lower()
    if _matches(_BURN_PATTERNS, text) or any(w in low for w in _BURN_STRONG_WORDS):
        return "BURNED_TEXT"
    if _matches(_VOICE_GENDER_PATTERNS, text):
        return "VOICE_GENDER_MISMATCH"
    if _matches(_FACE_PATTERNS, text):
        return "FACE_DRIFT"
    if _matches(_SHEEN_PATTERNS, text):
        return "SKIN_SHEEN"
    return None


def classify(item: str | None, text: str = "") -> str:
    """Fix kind of one finding.  Wording that names model-burned text wins over any item; otherwise the QA item
    decides when it names an actionable kind, and a record-only / unknown item yields to wording that names voice
    gender, face drift / identity swap or skin sheen."""
    item = str(item or "").upper()
    strong = strong_kind(text)
    if strong == "BURNED_TEXT" and (item not in _SUBTITLE_ITEMS or _MODEL_MARK.search(str(text or ""))):
        return "BURNED_TEXT"
    if strong == "BURNED_TEXT":
        strong = None
    if item == "QA-LOOKALIKE-CAST" and (strong == "FACE_DRIFT" or classify_text(text) == "FACE_DRIFT"):
        return "FACE_DRIFT"  # an in-shot identity swap reported under the look-alike item is a redo, not a record
    if item in ITEM_KIND:
        kind = ITEM_KIND[item]
        if fix_class(kind) == RECORD and strong:
            return strong
        return kind
    if item == "LOOK-DRIFT":
        kind = strong or classify_text(text)
        return kind if kind in ("FACE_DRIFT", "BURNED_TEXT", "SKIN_SHEEN") else "COSTUME_IDENTITY"
    if strong:
        return strong
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
                    **({"window": [round(span[0], 3), round(span[1], 3)]} if span else {}), **_kb_scope(g),
                    **({"scope_hint": g["scope_hint"]} if g.get("scope_hint") in ("global", "language") else {}),
                    **({"pass": g["pass"]} if g.get("pass") else {})})
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


TAIL_OWNER_S = 0.5


def tail_owner(segments: list[dict[str, Any]], window: list[float] | None) -> dict[str, Any] | None:
    """A clipped line tail reported at (or just after) a cut belongs to the OUTGOING unit: a point within
    TAIL_OWNER_S after a segment boundary maps to the segment that ends there."""
    if not window:
        return None
    t = float(window[0])
    for prev, seg in zip(segments or [], (segments or [])[1:]):
        a = _num(seg.get("output_start"))
        if a is not None and prev.get("unit_id") and a <= t <= a + TAIL_OWNER_S:
            return prev
    return None


def map_findings(findings: list[dict[str, Any]], segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each finding with its kind, fix class and (when it has a time) the unit and that unit's on-screen seconds."""
    out = []
    for f in findings:
        kind = f.get("kind_hint") or classify(f.get("item"), f.get("text") or "")
        row = {**{k: v for k, v in f.items() if k != "kind_hint"}, "kind": kind, "class": fix_class(kind)}
        seg = (tail_owner(segments, f.get("window")) if kind == "DIALOGUE_TAIL_GUARD" else None) \
            or unit_at(segments, f.get("window"))
        if seg is not None:
            row["unit_id"] = str(seg["unit_id"])
            row["on_screen_seconds"] = round(float(seg["output_end"]) - float(seg["output_start"]), 3)
        out.append(row)
    return out


CONFIRMED_SOURCES = ("QA_CHECKLIST_REVIEWER", "GEMINI_CONFIRMED")
#: which copy of a duplicated finding is kept (confirmed must-check first, so the trigger rule is unchanged)
SOURCE_RANK = {"QA_CHECKLIST_REVIEWER": 0, "GEMINI_CONFIRMED": 1, "REVIEW_HARD_FAIL": 2, "REVIEW_PROBLEM": 3}
DEDUPE_S = 1.0
_SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _near(a: list[float] | None, b: list[float] | None, tol: float = DEDUPE_S) -> bool:
    """Two windows within ``tol`` seconds of each other (overlap after widening each by tol/2 per side)."""
    if not a or not b:
        return False
    return float(a[0]) - tol <= float(b[1]) and float(b[0]) <= float(a[1]) + tol


def same_finding(a: dict[str, Any], b: dict[str, Any], tol: float = DEDUPE_S) -> bool:
    """Same kind, and the same time window (+-tol) -- or, both without a time, the same unit (or none)."""
    if a.get("kind") != b.get("kind"):
        return False
    if a.get("window") and b.get("window"):
        return _near(a["window"], b["window"], tol)
    if not a.get("window") and not b.get("window"):
        return a.get("unit_id") == b.get("unit_id")
    return False


def dedupe(mapped: list[dict[str, Any]], tol: float = DEDUPE_S) -> list[dict[str, Any]]:
    """One finding per (kind, time window +-1 s): the must-check checklist path, the confirmed Gemini path and the
    score report's problems often describe the same defect (E18 2026-11-20: 15 problems counted as 30).  The copy
    from the highest-ranked source is kept, with every source, the merged count and the most severe severity."""
    ordered = sorted(enumerate(mapped), key=lambda r: (SOURCE_RANK.get(str(r[1].get("source")), 9), r[0]))
    kept: list[tuple[int, dict[str, Any]]] = []
    for index, f in ordered:
        match = next((k for _i, k in kept if same_finding(k, f, tol)), None)
        if match is None:
            kept.append((index, {**f, "sources": list(f.get("sources") or [f.get("source")])}))
            continue
        match["sources"] = list(dict.fromkeys([*match["sources"], *(f.get("sources") or [f.get("source")])]))
        match["merged"] = int(match.get("merged") or 1) + int(f.get("merged") or 1)
        if f.get("text") and f["text"] not in str(match.get("text") or ""):
            match.setdefault("merged_text", []).append(str(f["text"])[:240])
        sev = [x for x in (match.get("severity"), f.get("severity")) if x]
        if sev:
            match["severity"] = min(sev, key=lambda x: _SEVERITY_RANK.get(str(x).upper(), 9))
        if match.get("window") and f.get("window"):
            match["window"] = [min(match["window"][0], f["window"][0]), max(match["window"][1], f["window"][1])]
    return [f for _i, f in sorted(kept, key=lambda r: r[0])]


# --------------------------------------------------------------------------------------- reconciliation
RESOLVED = "RESOLVED"
PERSISTS = "PERSISTS"
UNVERIFIED = "UNVERIFIED"
NEW = "NEW"
RECONCILE_S = 1.5


def _same_defect(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """A second-review finding is the first one again: same kind, and the same unit or a window within
    RECONCILE_S (a re-cut moves timestamps a little; a unit redo keeps the unit id)."""
    if first.get("kind") != second.get("kind"):
        return False
    if first.get("unit_id") and first.get("unit_id") == second.get("unit_id"):
        return True
    if first.get("window") and second.get("window"):
        return _near(first["window"], second["window"], RECONCILE_S)
    return not first.get("window") and not second.get("window") and not first.get("unit_id") \
        and not second.get("unit_id")


def reconcile(first: list[dict[str, Any]], second: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Each (deduped) first-review finding marked RESOLVED / PERSISTS / UNVERIFIED against the (deduped) second
    review, plus the second review's NEW findings.  ``second`` None = no second review of a new cut: everything is
    UNVERIFIED.  A first finding with neither a time nor a unit cannot be matched and stays UNVERIFIED unless a
    second finding of its kind has no time either.  "unresolved" = PERSISTS + NEW (distinct)."""
    rows: list[dict[str, Any]] = []
    used: set[int] = set()
    keep = ("kind", "class", "unit_id", "window", "source", "sources", "severity", "text", "voice_check",
            "tail_cause", "burn_check")

    def view(f: dict[str, Any]) -> dict[str, Any]:
        out = {k: f.get(k) for k in keep if f.get(k) not in (None, [], "")}
        if "text" in out:
            out["text"] = str(out["text"])[:240]
        return out

    for f in first or []:
        if second is None:
            rows.append({**view(f), "status": UNVERIFIED, "reason": "NO_SECOND_REVIEW_OF_A_NEW_CUT"})
            continue
        match = next((i for i, g in enumerate(second) if i not in used and _same_defect(f, g)), None)
        if match is not None:
            used.add(match)
            rows.append({**view(f), "status": PERSISTS, "second": view(second[match])})
        elif not f.get("window") and not f.get("unit_id"):
            rows.append({**view(f), "status": UNVERIFIED, "reason": "NO_TIME_OR_UNIT_TO_MATCH"})
        else:
            rows.append({**view(f), "status": RESOLVED})
    new = [{**view(g), "status": NEW} for i, g in enumerate(second or []) if i not in used]
    counts = {status: sum(1 for r in rows if r["status"] == status) for status in (RESOLVED, PERSISTS, UNVERIFIED)}
    counts[NEW] = len(new)
    unresolved_rows = [r for r in rows if r["status"] == PERSISTS] + new
    return {"first_findings": len(first or []), "second_findings": None if second is None else len(second),
            "counts": counts, "unresolved_count": len(unresolved_rows), "rows": rows, "new": new}


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
                  character_ids: Iterable[str] | None = None, burn_retry: int = 0) -> str:
    """One line appended to the unit's provider prompt (the highest-priority kind's sentence, plus the costume pin
    when costume / identity is among the unit's findings).  ``burn_retry`` n > 0 swaps the burned-text sentence for
    the retry-indexed wording (BURN_RETRY_SENTENCES)."""
    kinds = sorted(set(kinds), key=lambda k: PAID_PRIORITY.get(k, 9))
    parts = []
    for kind in kinds:
        text = (costume_sentence(wardrobe_rows or [], character_ids) if kind == "COSTUME_IDENTITY"
                else burn_retry_sentence(burn_retry) if kind == "BURNED_TEXT" and burn_retry > 0
                else SENTENCES.get(kind, ""))
        if text and text not in parts:
            parts.append(text)
    return " ".join(parts[:2])


def burn_retry_sentence(index: int) -> str:
    if index <= 0:
        return SENTENCES["BURNED_TEXT"]
    return BURN_RETRY_SENTENCES.get(index) or BURN_RETRY_SENTENCES[max(BURN_RETRY_SENTENCES)]


def burn_retry_max(env: dict[str, str] | None = None) -> int:
    raw = str((os.environ if env is None else env).get(FIX_BURN_RETRY_ENV, FIX_BURN_RETRY_MAX)).strip()
    try:
        return max(0, min(FIX_BURN_RETRY_MAX, int(float(raw))))
    except ValueError:
        return FIX_BURN_RETRY_MAX


def plan_burn_retry(rec: dict[str, Any] | None, detection: dict[str, Any], *, retry_max: int,
                    budget_left: float | None, headroom: int | None, cost: int) -> dict[str, Any]:
    """What to do with a freshly landed fix-round redo take of a BURNED_TEXT unit.  Pure.

    ``rec`` is the unit's FINAL_FIX_REDO record ({"burn_retries": [...]}).  KEEP (clean / detector fail-open),
    RETRY n (still burned, retries left, the round's remaining budget AND the episode headroom cover one more
    take) or KEEP_BEST (the take with the fewest burned frames stays)."""
    done = len((rec or {}).get("burn_retries") or [])
    status = detection.get("status")
    if status == "FAIL_OPEN":
        return {"action": "KEEP", "reason": "DETECTOR_FAIL_OPEN", "retry": done}
    if status != "BURNED":
        return {"action": "KEEP", "reason": "RESOLVED" if done else "CLEAN", "retry": done}
    if retry_max <= 0:
        return {"action": "KEEP_BEST", "reason": "RETRY_DISABLED", "retry": done}
    if done >= retry_max:
        return {"action": "KEEP_BEST", "reason": "RETRY_MAX_REACHED", "retry": done}
    if budget_left is None or cost > budget_left:
        return {"action": "KEEP_BEST", "reason": "FINAL_FIX_BUDGET_CAP", "retry": done, "cost": cost,
                "budget_left": budget_left}
    if headroom is None:
        return {"action": "KEEP_BEST", "reason": "BUDGET_HEADROOM_UNKNOWN", "retry": done, "cost": cost}
    if cost > int(headroom):
        return {"action": "KEEP_BEST", "reason": "BUDGET_HEADROOM_SHORT", "retry": done, "cost": cost,
                "headroom": int(headroom)}
    return {"action": "RETRY", "reason": "BURNED_TEXT_STILL_DETECTED", "retry": done + 1, "cost": cost}


def round_budget_left(record: dict[str, Any] | None, redo_state: dict[str, Any] | None,
                      budget: int | None = None) -> float:
    """NALU_FINAL_FIX_BUDGET_CREDITS minus the round's planned redo spend minus every burn retry already
    submitted (all units share the one cap)."""
    cap = budget_credits() if budget is None else int(budget)
    planned = float(((record or {}).get("paid") or {}).get("planned_credits") or 0)
    retries = sum(float(r.get("cost") or 0) for row in ((redo_state or {}).get("units") or {}).values()
                  if isinstance(row, dict) for r in row.get("burn_retries") or [])
    return round(cap - planned - retries, 3)


# ------------------------------------------------------------------------------- voice / speaker gender
_FEMALE = {"female", "f", "woman", "girl", "女", "女性"}
_MALE = {"male", "m", "man", "boy", "男", "男性"}


def _sex(value: Any) -> str | None:
    v = str(value or "").strip().lower()
    return "female" if v in _FEMALE else "male" if v in _MALE else None


def voice_assignment_check(bindings: list[dict[str, Any]], registry_rows: list[dict[str, Any]],
                           character_entities: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Is a speaker / voice gender mismatch a MAPPING bug in the unit's speaker_voice_contract?  Pure.

    For each binding: the speaking character (``character_id``) and the voice entity (``voice_entity_id``) are
    looked up in the voice registry (major_roles: entity_id, character_id, gender) and the character entities.
    MAPPING_BUG when the voice entity belongs to another character or its gender differs from the speaker's;
    CONTRACT_OK when every binding is consistent (the model voiced or lip-synced the wrong person: a generation
    defect, record + KB); UNKNOWN when genders / rows are missing."""
    by_entity = {str(r.get("entity_id")): r for r in registry_rows or [] if r.get("entity_id")}
    by_char = {str(r.get("character_id")): r for r in registry_rows or [] if r.get("character_id")}
    chars = {str(c.get("character_id")): c for c in character_entities or [] if c.get("character_id")}
    rows, bugs, unknown = [], [], []
    for b in bindings or []:
        cid, vid = str(b.get("character_id") or ""), str(b.get("voice_entity_id") or b.get("speaker_entity_id") or "")
        voice = by_entity.get(vid) or {}
        speaker = by_char.get(cid) or {}
        entity = chars.get(cid) or {}
        speaker_sex = _sex(speaker.get("gender") or entity.get("gender") or entity.get("sex")
                           or (entity.get("immutable") or {}).get("gender"))
        voice_sex = _sex(voice.get("gender"))
        row = {"speaker": b.get("speaker"), "character_id": cid or None, "voice_entity_id": vid or None,
               "audio_slot": b.get("audio_slot"), "speaker_gender": speaker_sex, "voice_gender": voice_sex,
               "visible_speaker": b.get("visible_speaker")}
        owner = str(voice.get("character_id") or "")
        if owner and cid and owner != cid:
            row["problem"] = f"VOICE_ENTITY_OF_ANOTHER_CHARACTER:{owner}"
            bugs.append(row)
        elif speaker_sex and voice_sex and speaker_sex != voice_sex:
            row["problem"] = f"VOICE_GENDER_{voice_sex.upper()}_FOR_{speaker_sex.upper()}_SPEAKER"
            bugs.append(row)
        elif not speaker_sex or not voice_sex:
            unknown.append(row)
        rows.append(row)
    status = "MAPPING_BUG" if bugs else "NO_BINDINGS" if not rows else "UNKNOWN" if unknown else "CONTRACT_OK"
    return {"status": status, "bindings": rows, "bugs": bugs}


# ------------------------------------------------------------------------------------ tail-cut causes
CLIP_END_EPS = 0.05


def tail_cut_cause(row: dict[str, Any] | None, next_row: dict[str, Any] | None = None) -> dict[str, Any]:
    """Why a clipped line tail can survive the wider tail guard, from the unit's performance-cut row
    (tools/performance_cut: original_seconds, after_out, tail_guard {word_end, speech_end, guard, cut,
    capped_by_next_speech}) and the next unit's row.  Pure.

    CLIP_END_NO_ROOM      the guard reaches the clip's own end: the line runs to the last frame of the take, so no
                          S7 cut can extend it (hold-last-frame would freeze the picture, not finish the syllable)
    NEXT_SHOT_SPEECH_AT_HEAD  the next unit opens on speech within its first 0.15 s: the cut is a hard audio jump
    NEXT_SPEECH_IN_TAKE   unscripted speech right after the line in the same take (the guard still wins)
    GUARD_APPLIED         the guard was applied with room to spare: the report disagrees with the measurement
    NO_PERFORMANCE_CUT_ROW / NOT_A_MATCHED_LINE"""
    if not isinstance(row, dict):
        return {"cause": "NO_PERFORMANCE_CUT_ROW"}
    tg = row.get("tail_guard") or {}
    if not tg:
        return {"cause": "NOT_A_MATCHED_LINE", "status": row.get("status")}
    original = _num(row.get("original_seconds"))
    out = {k: tg.get(k) for k in ("word_end", "speech_end", "guard", "cut", "capped_by_next_speech")}
    out["original_seconds"] = original
    out["after_out"] = row.get("after_out")
    guard_at = _num(tg.get("guard")) or 0.0
    speech_end_at = _num(tg.get("speech_end"))
    if original is not None and (guard_at >= original - CLIP_END_EPS
                                 or (speech_end_at is None and (_num(row.get("after_out")) or 0) >= original - CLIP_END_EPS)):
        return {**out, "cause": "CLIP_END_NO_ROOM"}
    nxt = next_row if isinstance(next_row, dict) else {}
    head = _num(nxt.get("line_start_seconds"))
    nin = _num(nxt.get("after_in")) or 0.0
    if head is not None and head - nin <= 0.15:
        return {**out, "cause": "NEXT_SHOT_SPEECH_AT_HEAD", "next_unit": nxt.get("unit_id"),
                "next_line_lead_seconds": round(head - nin, 3)}
    if tg.get("capped_by_next_speech"):
        return {**out, "cause": "NEXT_SPEECH_IN_TAKE"}
    return {**out, "cause": "GUARD_APPLIED"}


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
    rec = record.get("reconciliation") or {}
    out = {"status": record.get("status"),
           "first_verdict": (record.get("first_review") or {}).get("verdict"),
           "second_verdict": (record.get("second_review") or {}).get("verdict"),
           "findings": len(record.get("findings") or []),
           "free_fixes": sorted({a.get("kind") for a in record.get("free_actions") or [] if a.get("kind")}),
           "units_redone": [r.get("unit_id") for r in paid.get("selected") or []],
           "planned_credits": paid.get("planned_credits", 0),
           "credits_spent": record.get("credits_spent"),
           "unresolved": len(record.get("unresolved") or [])}
    if rec:
        out["reconciliation"] = dict(rec.get("counts") or {})
        out["second_findings"] = rec.get("second_findings")
    burn = paid.get("burn_checks") or {}
    if burn:
        out["burn_redo"] = {uid: row.get("status") for uid, row in burn.items()}
    bugs = [f.get("unit_id") for f in [*(record.get("findings") or []),
                                       *((record.get("second_review") or {}).get("findings") or [])]
            if (f.get("voice_check") or {}).get("status") == "MAPPING_BUG"]
    if bugs:
        out["voice_mapping_bugs"] = sorted({u for u in bugs if u})
    return out


def status_note(record: dict[str, Any] | None) -> str:
    """One line for the fleet status note, '' when there is no round to report."""
    s = summary(record)
    if not s["status"] or s["status"] in ("DISABLED",):
        return ""
    if s["status"] == "NOT_NEEDED":
        return "final-fix: not needed (review clean)"
    parts = [f"final-fix {s['status']}", f"1st {s['first_verdict'] or '?'} ({s['findings']})"]
    if s["second_verdict"]:
        parts.append(f"2nd {s['second_verdict']}"
                     + (f" ({s['second_findings']})" if s.get("second_findings") is not None else ""))
    if s["free_fixes"]:
        parts.append("free " + ",".join(s["free_fixes"]))
    if s["units_redone"]:
        parts.append(f"redo {','.join(s['units_redone'])} ({s['planned_credits']} cr)")
    if s.get("burn_redo"):
        parts.append("burn " + ",".join(f"{u.rsplit('-', 1)[-1]}={v}" for u, v in s["burn_redo"].items()))
    counts = s.get("reconciliation") or {}
    if counts:
        parts.append(f"resolved {counts.get(RESOLVED, 0)} persists {counts.get(PERSISTS, 0)} "
                     f"new {counts.get(NEW, 0)} unverified {counts.get(UNVERIFIED, 0)}")
    if s["unresolved"]:
        parts.append(f"unresolved {s['unresolved']}")
    if s.get("voice_mapping_bugs"):
        parts.append("VOICE MAPPING BUG " + ",".join(s["voice_mapping_bugs"]))
    return "; ".join(parts)


def unresolved(record: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Distinct findings left after the round.  With a second review reconciled: PERSISTS + NEW.  Without one
    (no actionable fix / disabled / second review not of a new cut): record-only and not-redone paid findings, and
    -- when a second verdict exists but could not be reconciled -- everything acted on, UNVERIFIED_AFTER_FIX."""
    record = record if isinstance(record, dict) else {}
    rec = record.get("reconciliation")
    if isinstance(rec, dict) and rec.get("second_findings") is not None:
        rows = [r for r in rec.get("rows") or [] if r.get("status") == PERSISTS] + list(rec.get("new") or [])
        return [{**{k: r.get(k) for k in ("kind", "class", "unit_id", "window", "source", "severity")
                    if r.get(k) is not None}, "state": r["status"]} for r in rows]
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
             f"* status **{s['status']}** — first review {s['first_verdict'] or '—'} ({s['findings']} distinct "
             f"findings), second review {s['second_verdict'] or '—'}",
             f"* free S7 fixes: {', '.join(s['free_fixes']) or 'none'}",
             f"* paid S6 redo: {', '.join(s['units_redone']) or 'none'} (planned {s['planned_credits']} credits, "
             f"cap {(record.get('paid') or {}).get('budget_cap', '—')})"]
    for row in (record.get("paid") or {}).get("skipped") or []:
        lines.append(f"  * not redone `{row.get('unit_id') or '—'}` {row.get('kind')}: {row.get('reason')}")
    for uid, row in ((record.get("paid") or {}).get("burn_checks") or {}).items():
        lines.append(f"  * burned-text redo `{uid}`: {row.get('status')} after {row.get('retries', 0)} retr"
                     f"{'y' if row.get('retries') == 1 else 'ies'} (kept take burned frames "
                     f"{row.get('kept_burned_frames', '—')})")
    counts = s.get("reconciliation") or {}
    if counts:
        lines.append(f"* after the round: resolved {counts.get(RESOLVED, 0)}, persists {counts.get(PERSISTS, 0)}, "
                     f"new {counts.get(NEW, 0)}, unverified {counts.get(UNVERIFIED, 0)}")
    rest = record.get("unresolved") or unresolved(record)
    if rest:
        lines.append(f"* unresolved findings ({len(rest)}): " + ", ".join(
            f"{r.get('kind')}{('@' + r['unit_id']) if r.get('unit_id') else ''} [{r.get('state')}]" for r in rest[:12]))
    if s.get("voice_mapping_bugs"):
        lines.append(f"* speaker / voice MAPPING BUG in the voice contract: {', '.join(s['voice_mapping_bugs'])}")
    lines.append("")
    return lines


def write_record(path: Path, record: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"schema": SCHEMA, **record}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path
