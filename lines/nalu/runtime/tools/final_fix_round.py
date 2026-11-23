#!/usr/bin/env python3
"""One automatic fix round after the independent final review (line owner 2026-11-20: "不要等我了，我自己看不过来").

Episodes never stop and wait for the line owner on quality.  When the S7 final review comes back REJECT_RECUT, or
with confirmed must-check DEFECTs (nalu_qa_defect_checklist / the Gemini A/V pass confirmed by the Codex reviewer),
the engine runs exactly ONE fix round before release, then one more final review, and proceeds whatever that second
verdict is (``NALU_FINAL_FIX_ROUNDS``, default 1; 0 disables; values above 1 are clamped to 1 -- never a loop).

Each confirmed finding is mapped to one fix class:

* ``FREE_S7`` -- re-cut / re-mix with the existing S7 tools, zero credits:
    STATIC_SHOT_SPLIT     an over-long static shot is split with a cutaway from a neighbouring SILENT unit's unused
                          frames (unit_recut plan; the unit's own sound runs on), else with a punch-in on its second
                          half -- only at line boundaries, never into pieces under the minimum shot (s7_edit_invariants)
    EDIT_FRAGMENT         the post-S7 measurement (or a reviewer) found fragments under the minimum shot, a speaker
                          on screen who does not speak, or a line cut off at the cut -> S7 re-edit with a longer
                          minimum shot / pacing floor and a wider tail guard (s7_edit_invariants)
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
  (:func:`voice_assignment_check`, the voice's gender from voice_gender.py): a mapping / casting bug is reported and
  recorded, never redone (the same reference would voice it the same way; the S4 casting check recasts it for the
  next episode); with a consistent contract it is a paid redo (2026-11-20, last in PAID_KINDS) carrying the
  own-voice sentence;
* a clipped tail that survives the wider guard gets its measured cause (:func:`tail_cut_cause`).

v3 (2026-11-21, JA-01 anime E04 on device 1485: both reviews flagged a character model sheet drawn as the picture (P0)
and two stacked identical subtitle lines (H3 burned the line under ours), yet the round redid six other units):

* findings are classified on their CONTENT (note + evidence), not only the class label: a picture showing a character
  reference / setting sheet, turnaround, three-view, 设定图 / 三视图 / 立绘 / model sheet or duplicated copies of a
  character is REFERENCE_SHEET_LEAK (paid redo; the submitter sends each identity sheet as its front-view crop,
  tools/h3_reference_sheet_guard.py) whatever the class; two stacked identical / near-identical subtitle lines,
  a duplicated / ghost caption, 字幕重复叠加 are BURNED_TEXT (the model's line under ours) even under
  QA-SUBTITLE-WRAP (:func:`sheet_leak_text`, :func:`stacked_subtitle_text`);
* paid redos are ranked by SEVERITY first (P0 > P1 > P2 > P3; a finding without one counts as P1), then by the
  kind order, then by the defect's on-screen seconds (:func:`plan_paid`): a P0 is redone before anything else that
  competes for the budget;
* S6 burned-text / sheet-leak retries that stayed UNRESOLVED (``s6_burn_unresolved`` of the must-check list) join the
  round as findings of their unit (source S6_UNRESOLVED; never a trigger on their own -- except, from v5, burned
  text in our subtitle band that stacks with our caption).

v5 (2026-11-22, JA-01 E07 on device 1485: H3 burned 「言わないでくださいまし！」 into VU-004, S6 retries stayed
UNRESOLVED, S7 drew our copy of the line just above it, the final review flagged only another burn and the round did
not redo VU-004):

* the S6 rows no longer depend on the must-check list file alone: nalu_pipeline reads them from the S6 wave state when
  the list is missing, bound to another cut or written without them (as S8 already did);
* an in-band burned line that IS the cue's line is suppressed in S7 (build_burnin_subtitles, free) and joins as P2;
  any other in-band burned text stacks with our caption: P1 and a TRIGGER of the round on its own;
* the post-S7 OCR of the final cut's caption band (av_evidence_pack ``stacked_subtitle_runs``: two rows saying the
  same line) joins as BURNED_TEXT P1 at its window, a trigger too (:func:`stacked_subtitle_findings`).

v4 (2026-11-21, KO E05 on device ...0080: "the camera shakes along with a character's small movements -- the person
AND the background move together"):

* CAMERA_WOBBLE (QA-CAMERA-WOBBLE, or wording "background moves with the actor" / 镜头晃 / 背景跟着动 under any item)
  is a paid redo carrying the steady-camera sentence, ranked right after the P0 classes (burned text, reference
  sheet); an S6 wobble retry that stayed unresolved and was not stabilised in S7 (``s6_wobble_unresolved``) joins
  the round as a P2 finding of its unit.

v6 (2026-11-23, device 1101 E24: everything shipped although the delivered shots did not match the plan -- wrong
locations, reversed roles, invented people, missing beats, 56 s against a 110 s brief):

* the multi-pass review's pass D answers per unit whether the PLANNED content was delivered (gemini_review_passes
  ``plan_parity``, kept by the must-check list); a NO unit is a PLAN_MISMATCH finding of its unit (paid redo carrying
  the plan sentence, ranked with the P0 classes) and a P0 NO is a TRIGGER of the round on its own
  (:func:`plan_parity_findings`); a planned unit missing from the cut is recorded (a redo cannot put it back);
* the record carries the OBJECTIVE defects left at release -- runtime vs target, unresolved burned text, stray
  voices in planned-silent units, plan NO units (:func:`objective_defects`) -- and the release policy
  (:func:`release_policy`; owner 2026-11-23, option iii: ``release_block_objective_defects`` ON, scoped to
  RELEASE_BLOCK_CLASSES = runtime < 0.85 x target and unresolved burned text that is not ACCEPT_CORRECT).  A hold
  never stalls the line: RELEASE_HELD:<classes> is recorded, the X2C publisher skips the episode, it is queued as a
  redo candidate and production moves on to the next episode.

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

FREE_KINDS = ("STATIC_SHOT_SPLIT", "AUDIO_SMOOTHING", "BGM_FADES", "SUBTITLE_WRAP", "DIALOGUE_TAIL_GUARD",
              "EDIT_FRAGMENT")
PAID_KINDS = ("BURNED_TEXT", "REFERENCE_SHEET_LEAK", "PLAN_MISMATCH", "CAMERA_WOBBLE", "COSTUME_IDENTITY", "FACE_DRIFT", "SKIN_SHEEN", "HAND_ARTIFACT", "VOICE_GENDER_MISMATCH")
#: owner order when the round's budget does not cover every paid redo
PAID_PRIORITY = {kind: rank for rank, kind in enumerate(PAID_KINDS)}

#: QA-* / Gemini item -> fix kind (LOOK-DRIFT and OTHER are classified on their text)
ITEM_KIND = {
    "QA-BURNED-TEXT": "BURNED_TEXT",
    "QA-REFERENCE-SHEET-LEAK": "REFERENCE_SHEET_LEAK",
    # 2026-11-23 (device 1101 E24): the unit did not deliver its planned content (pass D unit_parity NO)
    "QA-PLAN-MISMATCH": "PLAN_MISMATCH",
    # 2026-11-21 (KO E05, device ...0080): the set moves with the actor on a locked-off shot -> one paid redo with the
    # locked-off sentence (below the P0 classes)
    "QA-CAMERA-WOBBLE": "CAMERA_WOBBLE",
    "QA-DIALOGUE-TAIL-CUT": "DIALOGUE_TAIL_GUARD",
    "QA-EDIT-FRAGMENT": "EDIT_FRAGMENT",
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
    "QA-VOICE-GENDER": "VOICE_GENDER_MISMATCH",
    "CRAFT-ACTING-MONOTONY": "ACTING_MONOTONY",
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
    ("CAMERA_WOBBLE", ("camera wobble", "camera shake", "camera shakes", "frame shakes", "frame wobbles",
                       "background moves with", "background shifts with", "background sways", "jello", "rolling shutter",
                       "whole frame moves", "镜头晃", "镜头抖", "画面晃", "画面抖", "背景跟着", "背景也跟着",
                       "背景一起动", "背景晃", "果冻")),
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
    ("ACTING_MONOTONY", ("same gesture", "repeated gesture", "stock gesture", "spread their hands", "spreads her hands",
                         "spreads his hands", "hands spread", "palms spread", "spread both hands",
                         "spreads both", "both hands outward", "both palms outward", "open-arm", "no gestures",
                         "without gestures", "stands stiff", "stiff while talking", "frozen while speaking",
                         "index finger", "raised finger", "raises a finger", "pointing gesture", "keeps pointing",
                         "same pointing", "竖起食指", "食指", "指指点点", "同一个手指",
                         "摊手", "同一个手势", "重复的手势", "手势重复", "动作单一", "说话时没有动作", "干站着", "僵着说话")),
    ("SUBTITLE_WRAP", ("wrap", "line break", "lone punctuation", "on its own line", "换行", "单独成行", "断行")),
    ("DIALOGUE_TAIL_GUARD", ("cut off", "clipped", "truncated", "last syllable", "tail cut", "no pause",
                             "cuts mid", "尾音", "被剪", "切断", "截断", "没有停顿", "没停顿")),
    ("EDIT_FRAGMENT", ("cuts too fast", "cut too fast", "cutting too fast", "cuts away too fast", "too many cuts",
                       "flash cut", "choppy edit", "choppy cut", "doesn't say anything", "does not say anything",
                       "says nothing before", "without speaking", "切得太快", "切太快", "切镜太快", "镜头太碎",
                       "剪得太碎", "一闪而过", "没说话就切", "不说话就切", "还没说话就")),
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
    # the default sentence-end guard is already 0.4 s (dialogue_tail_guard.SENTENCE_END_GUARD_SECONDS): widen past it
    "DIALOGUE_TAIL_GUARD": {"NALU_S7_TAIL_GUARD_SECONDS": "0.55", "NALU_S7_POST_LINE_BEAT_SECONDS": "0.7"},
    # S7 edit invariants 2 + 3 (owner 2026-11-21, E21): longer minimum shot, higher median pacing floor
    "EDIT_FRAGMENT": {"NALU_S7_MIN_SHOT_SECONDS": "1.5", "NALU_S7_MEDIAN_SHOT_FLOOR_SECONDS": "2.5"},
}

STATIC_MIN_SPLIT_SECONDS = 4.0     # a cut shorter than this is not split
#: a cutaway is a motivated reaction: at least the reaction minimum (s7_edit_invariants.REACTION_MIN_SECONDS), never
#: the 0.8-1.5 s flash it used to be (owner 2026-11-21, E21: "1-2 s shots ... cuts away")
CUTAWAY_MIN_SECONDS = 1.5
CUTAWAY_MAX_SECONDS = 2.0
PUNCH_IN_FRAME = [0.1, 0.08, 0.8, 0.8]  # x, y, w, h of the second half's punch-in (unit_recut reframe)
GEMINI_MATCH_S = 1.5

#: prompt sentences of the paid redo (plain English, no digits, no all-caps labels: H3 voices labels)
SENTENCES = {
    "BURNED_TEXT": ("Nothing is written anywhere in the picture: no caption, subtitle, sign lettering or text of any "
                    "kind appears in any frame, and the spoken words are only heard."),
    "REFERENCE_SHEET_LEAK": ("The identity reference images only show who each person is: the picture is one "
                             "ordinary moment of the scene, with each person appearing once, and never shows a "
                             "character sheet, turnaround views, a face close-up inset or extra copies of anyone."),
    "PLAN_MISMATCH": ("The clip shows exactly the planned moment: only the people named in it, in the named place, "
                      "each doing their own planned action with the named objects, nobody added, missing or swapped "
                      "into another person's role."),
    "FACE_DRIFT": ("Each person keeps exactly the face of their identity reference image from the first frame to the "
                   "last: the same face shape, eyes, nose, hairline and age, with no drift toward another face."),
    "COSTUME_IDENTITY": ("Each person wears exactly the costume colours and garments of their identity reference "
                         "image for the whole clip; no garment changes colour or style."),
    "HAND_ARTIFACT": ("Every hand has a natural shape with five separate fingers from the first frame to the last; "
                      "fingers never merge, bend wrongly or pass through objects."),
    "VOICE_GENDER_MISMATCH": ("Every line is spoken in the speaker's own voice from their audio reference: a woman "
                              "speaks with a woman's voice and a man with a man's voice; nobody borrows another "
                              "person's voice."),
    "CAMERA_WOBBLE": ("The camera never shakes, sways or warps: the background and the edges of the frame stay "
                      "solid and still unless the camera makes its one declared move, and no nod, gesture or step "
                      "of a person ever moves the frame."),
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
#: the set / whole frame moving with the actor (KO E05 2026-11-21) beyond KEYWORDS -- whatever the item says
_WOBBLE_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"(?:background|set|frame|picture|whole (?:frame|image))\b.{0,30}\b(?:moves?|moving|shifts?|sways?|shakes?|"
    r"wobbles?|jitters?|drifts?)\b.{0,20}\b(?:with|along with|together with)\b",
    r"(?:camera|frame) (?:shake|wobble|jitter|sway)", r"jello|rubber[- ]?sheet|whole[- ]frame warp",
    r"(?:背景|画面|整个画面|镜头)[^。；;]{0,8}(?:跟着|随着|一起)[^。；;]{0,6}(?:动|晃|抖|移|摇)",
    r"(?:镜头|画面)(?:在)?(?:晃|抖|摇晃|抖动)", r"果冻(?:效应|感)?",
))
#: a character reference / model sheet drawn AS the picture (JA-01 E04 VU-007 2026-11-21: H3 copied the multi-view
#: identity sheet -- bust, big face close-up, front / side / back full bodies -- over the background; reviewed as
#: CRAFT-SHOT-GRAMMAR "对白中突兀切入角色设定三视图静态立绘" and "重复人物叠影和设定卡式静态构图")
_SHEET_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"(?:character|reference|model|design|setting|concept|turnaround)[- ]?(?:sheet|board)", r"setting card",
    r"turn-?around", r"three[- ]view", r"multi[- ]?view", r"(?:front|side|back)[ ,/]+(?:and |/ )?(?:side|back)[ ,/]+"
    r"(?:and |/ )?(?:back|front)\s+(?:view|full[- ]body)", r"(?:orthographic|reference) views?",
    r"(?:duplicat|repeat|multiple|several|extra|two|three|four)\w*\s+(?:copies|copy|instances?|clones?)\s+of\s+(?:the\s+)?"
    r"(?:same\s+)?(?:character|person|actor|actress|him|her)",
    r"(?:same|one) (?:character|person) (?:appears|shown|drawn) (?:twice|several times|multiple times|three times)",
    r"close-?up inset", r"(?:face|portrait) inset",
    r"设定(?:图|卡|稿|画|表)", r"三视图", r"多视图", r"转面图", r"立绘", r"人设(?:图|卡)", r"角色卡", r"定妆照",
    r"(?:重复|多个|两个|几个)(?:的)?(?:同一)?(?:个)?(?:人物|角色|人)(?:叠影|重影|分身|副本)", r"人物(?:叠影|分身)",
    r"同一(?:个)?(?:人物|角色|人)(?:出现|画了)?(?:两次|多次|三次)",
))
#: two stacked identical / near-identical subtitle lines = the model's burned line under our caption (JA-01 E04 VU-004:
#: Gemini QA-SUBTITLE-WRAP "字幕行重复叠加显示", reviewer "同一句字幕在底部重复叠加")
_STACKED_SUBTITLE_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"(?:stacked|doubled|duplicated?|repeated|ghost(?:ed)?|double)\s+(?:subtitle|caption)s?",
    r"(?:subtitle|caption)s?\s+(?:line\s+)?(?:is |are )?(?:stacked|doubled|duplicated|repeated|shown twice|appears? twice)",
    r"two\s+(?:identical|near[- ]identical|matching|same)\s+(?:subtitle\s+|caption\s+)?lines",
    r"same\s+(?:subtitle|caption|line)\s+(?:appears|shown|displayed)\s+twice",
    r"字幕(?:行)?[^。；;]{0,6}(?:重复|叠加|重叠|叠在一起|出现两次|两遍|双行)", r"(?:重复|双重|两行相同|两行一样)(?:的)?字幕",
    r"同一(?:句|行|条)(?:台词|字幕)[^。；;]{0,10}(?:重复|叠|两次|两遍)", r"字幕重影", r"重复叠加",
    r"两行(?:几乎)?(?:相同|一样|一模一样)",
))


#: "differs from the design sheet" compares a character WITH its card -- not a sheet in the picture ...
_SHEET_COMPARE = re.compile(r"不符|不一致|不像|不对|偏离|对照|对比|相比|跟.{0,8}不|和.{0,8}不(?:同|一样)|与.{0,8}不(?:同|一样)|"
                            r"\bmatch|differ|mismatch|deviat|compar|consisten|on-model|off-model", re.IGNORECASE)
#: ... unless the wording also says the sheet is what is shown
_SHEET_SHOWN = re.compile(r"切入|插入|出现|画面(?:是|变成|里是|中是|成了)|式|静态|叠影|分身|\bcopied|\bcuts? to|\binsert|"
                          r"appears?\b|\bshown\b|drawn as|as the (?:picture|frame|shot)|in the (?:picture|frame|shot)|"
                          r"\bstatic\b|\bagain\b", re.IGNORECASE)


def sheet_leak_text(text: str) -> bool:
    """The wording describes a character reference / model sheet (or duplicated copies of a character) IN the
    picture.  A comparison with the character's card ("hair differs from the design sheet") is not one, unless the
    wording also says the sheet is what is shown."""
    text = str(text or "")
    if not _matches(_SHEET_PATTERNS, text):
        return False
    return not _SHEET_COMPARE.search(text) or bool(_SHEET_SHOWN.search(text))


def stacked_subtitle_text(text: str) -> bool:
    """The wording describes two stacked identical / near-identical subtitle lines (model-burned line under ours)."""
    return _matches(_STACKED_SUBTITLE_PATTERNS, str(text or ""))


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
    if sheet_leak_text(text):
        return "REFERENCE_SHEET_LEAK"
    if stacked_subtitle_text(text):
        return "BURNED_TEXT"
    if _matches(_BURN_PATTERNS, text) or any(w in low for w in _BURN_STRONG_WORDS):
        return "BURNED_TEXT"
    if _matches(_VOICE_GENDER_PATTERNS, text):
        return "VOICE_GENDER_MISMATCH"
    if _matches(_FACE_PATTERNS, text):
        return "FACE_DRIFT"
    if _matches(_SHEEN_PATTERNS, text):
        return "SKIN_SHEEN"
    if _matches(_WOBBLE_PATTERNS, text):
        return "CAMERA_WOBBLE"
    return None


def classify(item: str | None, text: str = "") -> str:
    """Fix kind of one finding.  Wording that names model-burned text wins over any item; otherwise the QA item
    decides when it names an actionable kind, and a record-only / unknown item yields to wording that names voice
    gender, face drift / identity swap or skin sheen."""
    item = str(item or "").upper()
    strong = strong_kind(text)
    if strong == "REFERENCE_SHEET_LEAK":
        return strong  # the picture IS the identity sheet: whatever the class label says (E04 VU-007)
    if strong == "BURNED_TEXT" and stacked_subtitle_text(text):
        return strong  # two stacked identical lines = the model's line under ours, even under QA-SUBTITLE-WRAP
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
        note = str(g.get("note") or "")
        evidence = str(g.get("evidence") or "")
        out.append({"source": "GEMINI_CONFIRMED", "item": str(g.get("item") or "OTHER"),
                    # the evidence is classified with the note (E04: "two identical lines" under QA-SUBTITLE-WRAP)
                    "text": note + (f" | {evidence}" if evidence and evidence not in note else ""),
                    "severity": g.get("severity"),
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
    out.extend(s6_unresolved_findings(checklist.get("s6_burn_unresolved")))
    out.extend(stacked_subtitle_findings(checklist.get("stacked_subtitles")))
    out.extend(edit_measure_findings(checklist.get("s7_edit_measure")))
    out.extend(s6_unresolved_findings(checklist.get("s6_wobble_unresolved")))
    out.extend(plan_parity_findings(checklist.get("plan_parity")))
    return out


S6_SOURCE = "S6_UNRESOLVED"
EDIT_SOURCE = "S7_EDIT_MEASURE"
STACKED_SOURCE = "S7_STACKED_SUBTITLE"
PLAN_SOURCE = "GEMINI_PLAN_PARITY"
#: a planned unit with no window in the release timeline: recorded (a redo cannot put it back into the cut)
PLAN_NOT_IN_CUT = "PLAN_UNIT_NOT_IN_CUT"


def stacked_subtitle_findings(rows: Any) -> list[dict[str, Any]]:
    """The post-S7 measurement of the final cut's caption band (av_evidence_pack OCR, kept by the must-check list as
    ``stacked_subtitles``): two stacked rows saying the same line at once -- H3's burned copy and ours (JA-01 E07
    VU-004 2026-11-22) -> BURNED_TEXT P1 at that window, a trigger of the round (measured, not opinion)."""
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        w = row.get("window") or [row.get("start"), row.get("end")]
        a, b = (_num(w[0]), _num(w[1])) if isinstance(w, (list, tuple)) and len(w) == 2 else (None, None)
        if a is None:
            continue
        texts = " / ".join(str(t) for t in (row.get("texts") or [])[:2])
        out.append({"source": STACKED_SOURCE, "item": "QA-BURNED-TEXT", "kind_hint": "BURNED_TEXT", "severity": "P1",
                    "trigger": True, "window": [round(a, 3), round(b if b is not None else a, 3)],
                    "text": f"S7 measured: two stacked identical subtitle lines on screen ({texts}; similarity "
                            f"{row.get('similarity')}) -- model-burned line under ours"})
    return out


def edit_measure_findings(measure: Any) -> list[dict[str, Any]]:
    """The post-S7 edit measurement (s7_edit_invariants.measure_cut, kept by the must-check list as
    ``s7_edit_measure``) as findings of the round: fragments under the minimum shot and speakers on screen who do not
    speak -> EDIT_FRAGMENT, lines ending < 0.15 s before a cut and cuts inside a line -> DIALOGUE_TAIL_GUARD.  Free
    fixes (S7 re-edit); a finding at a cut S7 made itself (``s7_cut``) is a trigger of the round
    (:func:`triggered`), one inside the video model's own take is recorded with it."""
    if not isinstance(measure, dict):
        return []
    out = []
    for key, kind, what in (("fragments", "EDIT_FRAGMENT", "shot shorter than the minimum shot"),
                            ("speaker_not_speaking", "EDIT_FRAGMENT", "speaker on screen who does not speak"),
                            ("tail_gaps", "DIALOGUE_TAIL_GUARD", "line ends right at the cut"),
                            ("mid_line_cuts", "DIALOGUE_TAIL_GUARD", "cut inside a spoken line")):
        for row in (measure.get(key) or [])[:20]:
            if not isinstance(row, dict):
                continue
            if key in ("fragments", "speaker_not_speaking"):
                a, b = _num(row.get("start")), _num(row.get("end"))
                detail = f"{row.get('seconds')} s, speech {row.get('speech_seconds')} s"
            elif key == "tail_gaps":
                a = b = _num(row.get("next_cut"))
                detail = f"gap {row.get('gap_seconds')} s after the line ending at {row.get('line_end')}"
            else:
                a = b = _num(row.get("at"))
                detail = f"line {row.get('line_start')}-{row.get('line_end')}"
            out.append({"source": EDIT_SOURCE, "item": "QA-EDIT-FRAGMENT" if kind == "EDIT_FRAGMENT"
                        else "QA-DIALOGUE-TAIL-CUT", "kind_hint": kind, "severity": "P2",
                        "s7_cut": bool(row.get("s7_cut")),
                        "text": f"S7 measured: {what} ({detail})" + ("" if row.get("s7_cut") else
                                                                       " inside the video model's own take"),
                        **({"window": [round(a, 3), round(b if b is not None else a, 3)]} if a is not None else {}),
                        **({"unit_id": str(row["unit_id"])} if row.get("unit_id") else {})})
    return out


def s6_unresolved_findings(rows: Any) -> list[dict[str, Any]]:
    """S6 retries that did not clear the unit (``s6_burn_unresolved`` of the must-check list, from the S6 wave state):
    the kept take still shows the identity sheet (REFERENCE_SHEET_LEAK, P0) or model-burned text -- in our subtitle
    band P1 (it stacks under our caption, E04 VU-004) and a trigger (E07 VU-004), elsewhere -- or when S7 suppressed
    our copy because the strict check proved the burned line is exactly the cue's line (``duplicate_suppressed`` with
    ``strict_burn_verdicts`` ACCEPT_CORRECT, 2026-11-23) -- P2.  Findings of their unit."""
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("unit_id"):
            continue
        if row.get("camera_wobble") and not row.get("burned_text"):
            # the kept take of a locked-off unit still moves the set with the actor (S6 wobble retry exhausted)
            out.append({"source": S6_SOURCE, "item": "QA-CAMERA-WOBBLE", "unit_id": str(row["unit_id"]),
                        "severity": "P2", "kind_hint": "CAMERA_WOBBLE",
                        "text": "S6: the kept take still moves the background with the actor (camera wobble, "
                                f"{row.get('severity') or 'measured'}) after {int(row.get('retries') or 0)} retries "
                                f"({row.get('reason') or 'unresolved'})"})
            continue
        sheet = bool(row.get("sheet_leak"))
        in_band = bool(row.get("residual_in_subtitle_band"))
        # JA-01 E07 VU-004 (2026-11-22): the burned line IS the cue's line -> S7 suppressed our copy, the viewer reads
        # it once (P2, a redo only if the budget is left); any other in-band text stacks next to our caption (P1, and
        # a trigger of the round on its own: the round must not depend on a reviewer noticing it)
        # owner 2026-11-23 (E24 review): "suppressed" only on the STRICT verdict -- S7 proved the burned text is
        # exactly the cue's line (ACCEPT_CORRECT) and rejected no line of the unit; a wrong / unstable / unchecked
        # burned line in the band stacks with our kept caption: P1 and a trigger
        verdicts = [str(v) for v in row.get("strict_burn_verdicts") or []]
        suppressed = (bool(row.get("duplicate_suppressed")) and "ACCEPT_CORRECT" in verdicts
                      and not any(v.startswith("REJECT") for v in verdicts))
        stacks = in_band and not suppressed and not sheet
        out.append({"source": S6_SOURCE, "item": "QA-REFERENCE-SHEET-LEAK" if sheet else "QA-BURNED-TEXT",
                    "unit_id": str(row["unit_id"]),
                    "severity": "P0" if sheet else "P1" if stacks else "P2",
                    "kind_hint": "REFERENCE_SHEET_LEAK" if sheet else "BURNED_TEXT",
                    **({"trigger": True} if stacks else {}),
                    # #303's strict decisions travel with the finding: the release hold reads them (burn_accepted)
                    **({"strict_burn_verdicts": verdicts} if verdicts else {}),
                    **({"duplicate_suppressed": True} if suppressed else {}),
                    "text": ("S6: the kept take still shows the identity reference sheet" if sheet else
                             "S6: the kept take still carries model-burned text"
                             + (" in the subtitle band" if in_band else "")
                             + (" (the burned line is the cue's line: our copy was suppressed in S7)"
                                if suppressed else " (it stacks with our caption)" if stacks else ""))
                    + f" after {int(row.get('retries') or 0)} retries ({row.get('reason') or 'unresolved'})"})
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
        if seg is None and f.get("unit_id"):  # a unit-level finding (S6): its segment gives the window
            seg = next((s for s in segments or [] if str(s.get("unit_id")) == str(f["unit_id"])
                        and _num(s.get("output_start")) is not None and _num(s.get("output_end")) is not None), None)
            if seg is not None and not f.get("window"):
                row["window"] = [round(float(seg["output_start"]), 3), round(float(seg["output_end"]), 3)]
        if seg is not None:
            row["unit_id"] = str(seg["unit_id"])
            row["on_screen_seconds"] = round(float(seg["output_end"]) - float(seg["output_start"]), 3)
        out.append(row)
    return out


CONFIRMED_SOURCES = ("QA_CHECKLIST_REVIEWER", "GEMINI_CONFIRMED")
#: which copy of a duplicated finding is kept (confirmed must-check first, so the trigger rule is unchanged)
SOURCE_RANK = {"QA_CHECKLIST_REVIEWER": 0, "GEMINI_CONFIRMED": 1, "REVIEW_HARD_FAIL": 2, "REVIEW_PROBLEM": 3,
               S6_SOURCE: 4, STACKED_SOURCE: 5, EDIT_SOURCE: 6, PLAN_SOURCE: 7}
DEDUPE_S = 1.0
_SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
#: a confirmed finding without a severity (must-check DEFECT, hard fail) ranks as P1
DEFAULT_SEVERITY = "P1"
_SEVERITY_WORDS = {"CRITICAL": "P0", "BLOCKER": "P0", "BLOCKING": "P0", "SEVERE": "P1", "HIGH": "P1", "MAJOR": "P1",
                   "MEDIUM": "P2", "MODERATE": "P2", "NORMAL": "P2", "LOW": "P3", "MINOR": "P3", "TRIVIAL": "P3"}


def severity_of(value: Any) -> str:
    """P0..P3 of a finding's severity (P-labels, or critical / high / medium / low words); DEFAULT_SEVERITY if none."""
    raw = str(value or "").strip().upper()
    if raw in _SEVERITY_RANK:
        return raw
    m = re.match(r"^P\s*([0-3])\b", raw)
    if m:
        return f"P{m.group(1)}"
    return _SEVERITY_WORDS.get(raw, DEFAULT_SEVERITY)


def _defect_seconds(f: dict[str, Any]) -> float:
    """On-screen seconds of one finding: its window (clipped to its unit), else its unit's on-screen seconds."""
    unit_s = float(f.get("on_screen_seconds") or 0)
    w = f.get("window")
    if isinstance(w, (list, tuple)) and len(w) == 2 and _num(w[0]) is not None and _num(w[1]) is not None:
        span = max(0.0, float(w[1]) - float(w[0]))
        if span > 0:
            return round(min(span, unit_s) if unit_s else span, 3)
    return unit_s


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
    finding), or a post-S7 edit measurement at a cut S7 made (a fragment / silent speaker / clipped line the free
    re-edit can fix), or a MEASURED visible duplicate line (JA-01 E07 VU-004 2026-11-22: an S6-UNRESOLVED burned line
    stacking with our caption, two stacked identical caption rows in the final cut -- ``trigger``).  A PASS whose
    report merely lists problems is not a trigger."""
    return bool(rejected) or any(f.get("source") in CONFIRMED_SOURCES
                                 or (f.get("source") == EDIT_SOURCE and f.get("s7_cut"))
                                 or (f.get("source") in (S6_SOURCE, STACKED_SOURCE, PLAN_SOURCE)
                                     and f.get("trigger"))
                                 for f in mapped)


def actionable(mapped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [f for f in mapped if f["class"] == FREE or (f["class"] == PAID and f.get("unit_id"))]


def needs_round(rejected: bool, mapped: list[dict[str, Any]]) -> bool:
    """A round runs on a trigger -- but only when something can be acted on (else the line records and proceeds)."""
    return triggered(rejected, mapped) and bool(actionable(mapped))


# ------------------------------------------------------------------------------------------------ paid plan
def plan_paid(mapped: list[dict[str, Any]], *, budget: int, headroom: int | None,
              unit_cost: Callable[[str], int], eligible: Callable[[str], str | None] | None = None,
              unit_order: list[str] | None = None) -> dict[str, Any]:
    """One redo per unit, ranked by severity first (P0 before anything else; the unit's most severe finding), then
    by the owner's kind order (burned text, reference sheet, costume / identity, face drift, ...), then by the
    defect's on-screen seconds (the unit's finding windows summed, capped at the unit), then the cut order (JA-01 E04
    2026-11-21: two P0 units lost the budget to P2 burned-text units).

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
        row = units.setdefault(uid, {"unit_id": uid, "kinds": [], "on_screen_seconds": f.get("on_screen_seconds") or 0,
                                     "severity": "P3", "defect_seconds": 0.0})
        if f["kind"] not in row["kinds"]:
            row["kinds"].append(f["kind"])
        sev = severity_of(f.get("severity"))
        if _SEVERITY_RANK[sev] < _SEVERITY_RANK[row["severity"]]:
            row["severity"] = sev
        row["defect_seconds"] = round(float(row["defect_seconds"]) + _defect_seconds(f), 3)
    for row in units.values():
        row["kinds"].sort(key=lambda k: PAID_PRIORITY[k])
        row["kind"] = row["kinds"][0]
        if row["on_screen_seconds"]:
            row["defect_seconds"] = min(float(row["defect_seconds"]), float(row["on_screen_seconds"]))
    ranked = sorted(units.values(), key=lambda r: (_SEVERITY_RANK[r["severity"]], PAID_PRIORITY[r["kind"]],
                                                   -float(r["defect_seconds"] or 0), order.get(r["unit_id"], 10 ** 6),
                                                   r["unit_id"]))
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


def _invariants():
    try:
        from tools import s7_edit_invariants as inv  # noqa: PLC0415
    except ImportError:  # flat sys.path (engine tools dir)
        import s7_edit_invariants as inv  # type: ignore  # noqa: PLC0415
    return inv


def _free_spans(spans: list[tuple[float, float]], busy: list[tuple[float, float]], pad: float) -> list[tuple[float, float]]:
    """``spans`` minus every ``busy`` interval widened by ``pad`` (a neighbour's speech is never borrowed)."""
    out = []
    for lo, hi in spans:
        cur = [(float(lo), float(hi))]
        for b0, b1 in busy:
            nxt = []
            for a, b in cur:
                if b1 + pad <= a or b0 - pad >= b:
                    nxt.append((a, b))
                    continue
                if b0 - pad > a:
                    nxt.append((a, b0 - pad))
                if b1 + pad < b:
                    nxt.append((b1 + pad, b))
            cur = nxt
        out.extend(cur)
    return [(round(a, 3), round(b, 3)) for a, b in out if b - a > 0]


def static_shot_segments(uid: str, window: tuple[float, float], *, neighbours: list[dict[str, Any]],
                         speech: list[dict[str, Any]] | None = None, speaking: bool = False,
                         min_seconds: float | None = None) -> dict[str, Any]:
    """unit_recut segments splitting one over-long static unit, under the S7 edit invariants (tools/
    s7_edit_invariants; owner 2026-11-21, device 1101 E21: 1-2 s shots of a character who says nothing).

    ``window`` is the unit's source in/out in the current cut; ``speech`` the unit's ASR segments (source seconds,
    word timestamps when present); ``speaking`` the unit carries an on-screen scripted line.  ``neighbours`` are
    [{unit_id, unused: [(a, b), ...], speaking?, speech?}] (source seconds of that unit the cut does not show).

    * every cut sits at a line boundary (never inside a word, a line's tail kept) and every piece is >= the minimum
      shot (``min_seconds``, default s7_edit_invariants.min_shot_seconds());
    * CUTAWAY: only from a neighbour WITHOUT an on-screen line (a speaking neighbour's unused frames show a speaker
      who does not say what is heard), only from its frames with no speech in them, CUTAWAY_MIN_SECONDS..
      CUTAWAY_MAX_SECONDS long (a motivated reaction); the unit's own sound runs on under it;
    * PUNCH_IN otherwise: the second piece is a punch-in on the same take, split at a line boundary; for a speaking
      unit each piece carries part of the line (or is a >= 1.5 s reaction hold);
    * no such split -> status NO_LINE_BOUNDARY_SPLIT (nothing is cut).
    Returns {status, method, segments, cuts}; status TOO_SHORT_TO_SPLIT for cuts under STATIC_MIN_SPLIT_SECONDS."""
    inv = _invariants()
    a, b = float(window[0]), float(window[1])
    length = b - a
    if length < STATIC_MIN_SPLIT_SECONDS:
        return {"status": "TOO_SHORT_TO_SPLIT", "seconds": round(length, 3)}
    min_s = inv.min_shot_seconds() if min_seconds is None else float(min_seconds)
    reaction_s = max(inv.reaction_min_seconds(), min_s)
    words = inv.speech_words(speech)
    safe = inv.safe_intervals(words, a, b)

    def is_safe(t: float) -> bool:
        return any(lo - 1e-6 <= t <= hi + 1e-6 for lo, hi in safe)

    def piece_ok(x0: float, x1: float) -> bool:
        if x1 - x0 < min_s - 1e-6:
            return False
        return (not speaking or inv.speech_in(words, x0, x1) >= inv.SPEECH_OVERLAP_SECONDS
                or x1 - x0 >= reaction_s - 1e-6)

    for nb in neighbours or []:
        if nb.get("speaking"):
            continue
        busy = inv.spans(nb.get("speech"))
        for lo, hi in _free_spans([(float(x), float(y)) for x, y in nb.get("unused") or []], busy, inv.HEAD_LEAD_SECONDS):
            span = hi - lo
            c = round(min(CUTAWAY_MAX_SECONDS, span, length - 2 * min_s), 3)
            if c < CUTAWAY_MIN_SECONDS - 1e-6:
                continue
            centre = a + (length - c) / 2.0
            starts = []
            x = a + min_s
            while x + c <= b - min_s + 1e-6:
                m = round(x, 3)
                if is_safe(m) and is_safe(round(m + c, 3)) and piece_ok(a, m) and piece_ok(m + c, b):
                    starts.append(m)
                x += inv.STEP_SECONDS
            if not starts:
                continue
            m = min(starts, key=lambda v: (abs(v - centre), v))
            src = round(lo + (span - c) / 2, 3)
            return {"status": "PLANNED", "method": "CUTAWAY", "borrowed_from": nb["unit_id"], "cuts": [m, round(m + c, 3)],
                    "segments": [
                        {"video": [uid, round(a, 3), m], "audio": [uid, round(a, 3), m]},
                        {"video": [nb["unit_id"], src, round(src + c, 3)], "audio": [uid, m, round(m + c, 3)]},
                        {"video": [uid, round(m + c, 3), round(b, 3)], "audio": [uid, round(m + c, 3), round(b, 3)]}]}
    point = inv.split_points(words, a, b, min_s=min_s, speaking=speaking, reaction_s=reaction_s)
    if not point:
        return {"status": "NO_LINE_BOUNDARY_SPLIT", "seconds": round(length, 3)}
    m = round(point[0], 3)
    return {"status": "PLANNED", "method": "PUNCH_IN", "cuts": [m], "segments": [
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
        speaker_sex = _sex(speaker.get("character_gender") or speaker.get("gender") or entity.get("gender")
                           or entity.get("sex") or (entity.get("immutable") or {}).get("gender"))
        if not speaker_sex and entity:
            try:
                import voice_gender as _vg  # noqa: PLC0415
                speaker_sex = _vg.character_gender(entity)["gender"]
            except Exception:  # noqa: BLE001
                speaker_sex = None
        # the VOICE's gender: its recorded voice_gender (S4 rows since 2026-11-20; legacy rows: "gender"), else
        # voice_gender.py (system-voice table / voice name / reference F0)
        voice_sex = _sex(voice.get("voice_gender") or voice.get("gender"))
        if not voice_sex and voice:
            try:
                import voice_gender as _vg  # noqa: PLC0415 - same directory
                voice_sex = _vg.voice_gender(voice.get("voice_id") or voice.get("generation_voice_id"),
                                             voice_name=voice.get("voice_name"),
                                             f0=voice.get("reference_f0_hz"))["gender"]
            except Exception:  # noqa: BLE001
                voice_sex = None
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
    out.update(objective_summary(record))
    return out


def status_note(record: dict[str, Any] | None) -> str:
    """One line for the fleet status note, '' when there is nothing to report: the round, then the plan parity and
    the objective defects left at release (2026-11-23)."""
    return "; ".join(x for x in (_round_note(record), objective_note(record)) if x)


def _round_note(record: dict[str, Any] | None) -> str:
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
    lines += objective_lines(record)
    lines.append("")
    return lines


# ---------------------------------------------------------------------- plan parity + objective defects (v6)
def plan_parity_findings(parity: Any) -> list[dict[str, Any]]:
    """Pass D's per-unit plan parity (gemini_review_passes.plan_parity_record) as findings of the round: a NO unit
    is PLAN_MISMATCH of that unit (paid redo with the plan sentence), at its window, with its severity; a P0 NO is
    a trigger of the round on its own (2026-11-23, E24: role reversed, wrong location, invented people, missing
    beats -- and nothing triggered).  A planned unit not in the cut is recorded (PLAN_UNIT_NOT_IN_CUT)."""
    out: list[dict[str, Any]] = []
    for row in (parity.get("units") or []) if isinstance(parity, dict) else []:
        if not isinstance(row, dict) or not row.get("unit_id"):
            continue
        decision = row.get("delivered")
        if decision == "NO":
            sev = severity_of(row.get("severity") or "P1")
            a, b = _num(row.get("start")), _num(row.get("end"))
            out.append({"source": PLAN_SOURCE, "item": "QA-PLAN-MISMATCH", "kind_hint": "PLAN_MISMATCH",
                        "unit_id": str(row["unit_id"]), "severity": sev, **({"trigger": True} if sev == "P0" else {}),
                        **({"window": [round(a, 3), round(b if b is not None else a, 3)]} if a is not None else {}),
                        "reasons": list(row.get("reasons") or []),
                        "text": f"plan parity NO ({', '.join(row.get('reasons') or []) or 'not delivered'}): "
                                f"{row.get('seen') or ''} {row.get('why') or ''}".strip()[:240]})
        elif decision == "NOT_IN_CUT":
            out.append({"source": PLAN_SOURCE, "item": "QA-PLAN-MISMATCH", "kind_hint": PLAN_NOT_IN_CUT,
                        "unit_id": str(row["unit_id"]), "severity": "P2",
                        "text": "planned unit is not in the release timeline (its beat is missing from the cut)"})
    return out


def plan_parity_summary(parity: Any) -> dict[str, Any]:
    """The concise per-unit parity for the record, the episode record and the fleet note."""
    if not isinstance(parity, dict) or not parity.get("units"):
        return {}
    keep = ("unit_id", "start", "end", "delivered", "reasons", "severity", "seen")
    return {"status": parity.get("status"), "delivered": parity.get("delivered"), "total": parity.get("total"),
            "counts": dict(parity.get("counts") or {}), "note": parity.get("note"),
            "no_units": [r.get("unit_id") for r in parity["units"] if r.get("delivered") == "NO"],
            "p0_no_units": [r.get("unit_id") for r in parity["units"]
                            if r.get("delivered") == "NO" and severity_of(r.get("severity") or "P1") == "P0"],
            "units": [{k: r.get(k) for k in keep if r.get(k) not in (None, [], "")} for r in parity["units"]],
            **({"stale": parity["stale"]} if parity.get("stale") else {})}


RELEASE_POLICY_ENV = "NALU_RELEASE_BLOCK_OBJECTIVE_DEFECTS"
RELEASE_CLASSES_ENV = "NALU_RELEASE_BLOCK_CLASSES"
#: owner decision 2026-11-23 (option iii): the release is HELD only for these objective defects; every other one is
#: recorded.  A hold never stalls the line: the episode is finished as usual (S7 / S8), not sent to X2C, recorded as
#: RELEASE_HELD:<classes> and queued as a redo candidate; production moves on to the next episode.
RELEASE_BLOCK_OBJECTIVE_DEFECTS = True
RELEASE_BLOCK_CLASSES = frozenset({"RUNTIME_SHORT", "BURN_UNRESOLVED"})
OBJECTIVE_CLASSES = ("RUNTIME_SHORT", "BURN_UNRESOLVED", "STRAY_VOICES", "PLAN_NO_UNITS")
RELEASE_HELD = "RELEASE_HELD"
#: a cut shorter than this share of the brief's target runtime is an objective defect (E24: 56 s of 110 s)
RUNTIME_MIN_RATIO = 0.85
_BURN_KINDS = ("BURNED_TEXT", "REFERENCE_SHEET_LEAK")
#: a burn the S7 burned-text handling accepted (the burned line IS the correct cue) does not hold the release
BURN_ACCEPTED = "ACCEPT_CORRECT"


def release_block_objective_defects(env: dict[str, str] | None = None) -> bool:
    raw = str((os.environ if env is None else env).get(RELEASE_POLICY_ENV) or "").strip().lower()
    if raw in ("1", "on", "true", "yes"):
        return True
    if raw in ("0", "off", "false", "no"):
        return False
    return RELEASE_BLOCK_OBJECTIVE_DEFECTS


def release_block_classes(env: dict[str, str] | None = None) -> frozenset[str]:
    """The classes that hold the release: RELEASE_BLOCK_CLASSES, or ``NALU_RELEASE_BLOCK_CLASSES`` (comma list of
    OBJECTIVE_CLASSES, ``all`` or ``none``) to narrow or widen it."""
    raw = str((os.environ if env is None else env).get(RELEASE_CLASSES_ENV) or "").strip()
    if not raw:
        return RELEASE_BLOCK_CLASSES
    if raw.lower() == "all":
        return frozenset(OBJECTIVE_CLASSES)
    if raw.lower() == "none":
        return frozenset()
    return frozenset(c.strip().upper() for c in raw.split(",") if c.strip().upper() in OBJECTIVE_CLASSES)


def _suspect_decision(row: dict[str, Any]) -> str:
    """The reviewer's decision on a local suspect when it gave one, else Gemini's (checklist or Gemini record)."""
    return str(row.get("reviewer") or row.get("decision") or row.get("gemini") or "NOT_ANSWERED").upper()


def burn_accepted(row: dict[str, Any] | None) -> bool:
    """A burn the S7 strict burned-line check accepted (#303, owner 2026-11-23): the row's ``strict_burn_verdicts``
    (S6 rows / their findings, from ``burned_line_checks`` of <EP>_BURNIN_SUBTITLES.json) hold ACCEPT_CORRECT and no
    REJECT_*; or a single ``burn_verdict``/``verdict``/... field (a ``burned_line_checks`` row) says ACCEPT_CORRECT.
    ``duplicate_suppressed`` counts only with an accepting strict verdict (the strict check is the only thing that
    may suppress our copy); the S6 finding's "our copy was suppressed in S7" text is the legacy marker of the same."""
    row = row if isinstance(row, dict) else {}
    verdicts = [str(v).upper() for v in row.get("strict_burn_verdicts") or []]
    if verdicts:
        return BURN_ACCEPTED in verdicts and not any(v.startswith("REJECT") for v in verdicts)
    fields = [str(row.get(k) or "").upper() for k in ("burn_verdict", "verdict", "decision", "status", "state",
                                                      "resolution")]
    if any(v.startswith("REJECT") for v in fields):
        return False
    if BURN_ACCEPTED in fields or row.get("accept_correct"):
        return True
    return "our copy was suppressed in S7" in str(row.get("text") or "")


def _burn_source(record: dict[str, Any], row: dict[str, Any]) -> dict[str, Any] | None:
    """The finding an unresolved burn row came from (same kind and unit, or a window within DEDUPE_S)."""
    pool = [*(record.get("findings") or []), *((record.get("second_review") or {}).get("findings") or [])]
    for f in pool:
        if f.get("kind") != row.get("kind"):
            continue
        if (row.get("unit_id") and f.get("unit_id") == row.get("unit_id")) or \
                (row.get("window") and f.get("window") and _near(row["window"], f["window"], DEDUPE_S)):
            return f
    return None


def objective_defects(record: dict[str, Any] | None, *, runtime_s: float | None = None,
                      target_s: float | None = None, plan_parity: dict[str, Any] | None = None,
                      suspect_checks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The objective (measured, not opinion) defects left at release:

    runtime           the cut's content runtime vs the brief's target (short below RUNTIME_MIN_RATIO)
    unresolved_burns  burned text / sheet leak findings the round left unresolved, plus local OCR text runs that
                      neither Gemini nor the reviewer dismissed (not within 1 s of one already listed); ``blocking``:
                      not ACCEPT_CORRECT (:func:`burn_accepted`) and, for an OCR run, CONFIRMED by a reviewer
    stray_voices      ASR speech in planned-silent units nobody dismissed
    plan_no_units     units pass D judged NOT delivered (plan_not_in_cut: planned units missing from the cut,
                      listed, not counted)
    ``count`` sums the four; ``classes`` names those present; ``blocking_classes`` those that may hold the release
    (RUNTIME_SHORT when short, BURN_UNRESOLVED when a blocking burn is left -- the policy decides)."""
    record = record if isinstance(record, dict) else {}
    runtime: dict[str, Any] = {}
    if _num(runtime_s) is not None and _num(target_s):
        ratio = round(float(runtime_s) / float(target_s), 3)
        runtime = {"runtime_seconds": round(float(runtime_s), 2), "target_seconds": round(float(target_s), 2),
                   "ratio": ratio, "min_ratio": RUNTIME_MIN_RATIO, "short": ratio < RUNTIME_MIN_RATIO}
    burns = []
    for r in (record.get("unresolved") or unresolved(record)):
        if r.get("kind") not in _BURN_KINDS:
            continue
        accepted = burn_accepted(r) or burn_accepted(_burn_source(record, r))
        burns.append({**{k: r.get(k) for k in ("kind", "unit_id", "window", "state") if r.get(k) is not None},
                      "source": "FINAL_FIX_UNRESOLVED", "blocking": not accepted,
                      **({"accepted": BURN_ACCEPTED} if accepted else {})})
    stray = []
    for row in suspect_checks or []:
        sus = row.get("suspect") or {}
        decision = _suspect_decision(row)
        if decision == "DISMISSED":
            continue
        if sus.get("kind") == "burned_text":
            w = sus.get("window")
            if any(_near(w, b.get("window"), DEDUPE_S) for b in burns if b.get("window")):
                continue
            accepted = burn_accepted(row) or burn_accepted(sus)
            burns.append({"kind": "BURNED_TEXT", "window": w, "text": sus.get("text"), "where": sus.get("where"),
                          "decision": decision, "source": "LOCAL_OCR",
                          "blocking": decision == "CONFIRMED" and not accepted,
                          **({"accepted": BURN_ACCEPTED} if accepted else {})})
        elif sus.get("kind") == "stray_voice":
            stray.append({"unit": sus.get("unit"), "window": sus.get("window"), "heard": sus.get("heard"),
                          "decision": decision, "source": "LOCAL_ASR"})
    units = (plan_parity or {}).get("units") or []
    no_units = [{k: r.get(k) for k in ("unit_id", "window", "reasons", "severity") if r.get(k) is not None}
                | ({"window": [r.get("start"), r.get("end")]} if r.get("start") is not None else {})
                for r in units if r.get("delivered") == "NO"]
    missing = [r.get("unit_id") for r in units if r.get("delivered") == "NOT_IN_CUT"]
    present = {"RUNTIME_SHORT": bool(runtime.get("short")), "BURN_UNRESOLVED": bool(burns),
               "STRAY_VOICES": bool(stray), "PLAN_NO_UNITS": bool(no_units)}
    blocking = {"RUNTIME_SHORT": bool(runtime.get("short")),
                "BURN_UNRESOLVED": any(b.get("blocking") for b in burns),
                "STRAY_VOICES": bool(stray), "PLAN_NO_UNITS": bool(no_units)}
    return {"runtime": runtime, "unresolved_burns": burns, "stray_voices": stray, "plan_no_units": no_units,
            "plan_not_in_cut": missing,
            "count": int(bool(runtime.get("short"))) + len(burns) + len(stray) + len(no_units),
            "classes": [c for c in OBJECTIVE_CLASSES if present[c]],
            "blocking_classes": [c for c in OBJECTIVE_CLASSES if blocking[c]]}


def release_policy(objective: dict[str, Any] | None, env: dict[str, str] | None = None) -> dict[str, Any]:
    """The release decision on the objective defects (owner 2026-11-23, option iii).  ``blocks`` = the switch is ON
    and a defect of a blocking class is present; ``hold`` is then RELEASE_HELD:<classes>.  A hold is recorded and
    the episode skipped by the X2C publisher and queued for a redo -- it never stops the line."""
    on = release_block_objective_defects(env)
    scope = release_block_classes(env)
    held = [c for c in (objective or {}).get("blocking_classes") or [] if c in scope]
    blocks = on and bool(held)
    return {"release_block_objective_defects": on, "block_classes": sorted(scope), "held_classes": held,
            "would_block": bool(held), "blocks": blocks, "classes": list((objective or {}).get("classes") or []),
            "action": RELEASE_HELD if blocks else "RELEASE",
            **({"hold": f"{RELEASE_HELD}:{','.join(held)}"} if blocks else {}),
            "switch": f"{RELEASE_POLICY_ENV} on|off, {RELEASE_CLASSES_ENV}=<classes>|all|none "
                      "(final_fix_round.RELEASE_BLOCK_OBJECTIVE_DEFECTS / RELEASE_BLOCK_CLASSES)",
            "note": "owner 2026-11-23: hold the X2C release only for a short runtime or unresolved burned text; "
                    "the line never waits (redo candidate, next episode proceeds)"}


def release_hold(record: dict[str, Any] | None) -> str:
    """'RELEASE_HELD:<classes>' when the record's release policy holds the episode, else ''."""
    policy = (record or {}).get("release_policy") if isinstance(record, dict) else None
    return str((policy or {}).get("hold") or "") if (policy or {}).get("blocks") else ""


def objective_summary(record: dict[str, Any] | None) -> dict[str, Any]:
    record = record if isinstance(record, dict) else {}
    out: dict[str, Any] = {}
    parity = record.get("plan_parity") or {}
    if parity:
        out["plan_parity"] = {k: parity.get(k) for k in ("delivered", "total", "note", "no_units") if k in parity}
    obj = record.get("objective_defects") or {}
    if obj:
        out["objective_defects"] = {"count": obj.get("count", 0), "classes": obj.get("classes") or [],
                                    **({"runtime_ratio": obj["runtime"].get("ratio")} if obj.get("runtime") else {})}
    policy = record.get("release_policy") or {}
    if policy:
        out["release_policy"] = {k: policy.get(k) for k in ("release_block_objective_defects", "would_block", "blocks")}
        if policy.get("blocks"):
            out["release_hold"] = policy.get("hold")
    return out


def objective_note(record: dict[str, Any] | None) -> str:
    """'plan parity: n/m delivered; objective defects k (...)' for the fleet note, '' when not recorded."""
    s = objective_summary(record)
    parts = []
    if s.get("plan_parity"):
        parts.append(str(s["plan_parity"].get("note") or ""))
    obj = s.get("objective_defects") or {}
    if obj.get("count"):
        parts.append(f"objective defects {obj['count']} ({','.join(obj.get('classes') or [])})")
    if s.get("release_hold"):
        parts.append(f"{s['release_hold']} (not sent to X2C; redo candidate)")
    return "; ".join(p for p in parts if p)


def objective_lines(record: dict[str, Any] | None) -> list[str]:
    """CHECKPOINT lines: per-unit plan parity and the objective defects at release with the policy switch."""
    record = record if isinstance(record, dict) else {}
    parity, obj, policy = (record.get("plan_parity") or {}, record.get("objective_defects") or {},
                           record.get("release_policy") or {})
    lines: list[str] = []
    if parity:
        lines.append(f"* {parity.get('note')}" + (f" — NO: {', '.join(parity.get('no_units') or [])}"
                                                  if parity.get("no_units") else ""))
        for row in [r for r in parity.get("units") or [] if r.get("delivered") not in ("YES", None)][:20]:
            lines.append(f"  * `{row.get('unit_id')}` {row.get('delivered')} {row.get('severity') or ''} "
                         f"{', '.join(row.get('reasons') or [])} {str(row.get('seen') or '')[:60]}".rstrip())
    if obj:
        rt = obj.get("runtime") or {}
        lines.append(f"* objective defects at release: {obj.get('count', 0)}"
                     + (f" — runtime {rt.get('runtime_seconds')} s vs target {rt.get('target_seconds')} s "
                        f"({rt.get('ratio')}{', SHORT' if rt.get('short') else ''})" if rt else "")
                     + f"; unresolved burns {len(obj.get('unresolved_burns') or [])} "
                       f"(blocking {sum(1 for b in obj.get('unresolved_burns') or [] if b.get('blocking'))}), stray voices "
                       f"{len(obj.get('stray_voices') or [])}, plan NO units {len(obj.get('plan_no_units') or [])}"
                     + (f", not in cut {len(obj['plan_not_in_cut'])}" if obj.get("plan_not_in_cut") else ""))
    if policy:
        lines.append(f"* release policy `release_block_objective_defects` = "
                     f"{'ON' if policy.get('release_block_objective_defects') else 'OFF'} for "
                     f"{', '.join(policy.get('block_classes') or []) or 'no class'} — "
                     + (f"**{policy.get('hold')}**: not sent to X2C, queued as a redo candidate; the line goes on"
                        if policy.get("blocks") else "release")
                     + f" ({policy.get('switch')})")
    return lines


def write_record(path: Path, record: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"schema": SCHEMA, **record}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path
