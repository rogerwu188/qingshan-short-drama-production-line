#!/usr/bin/env python3
"""camera_move_lint — flag camera-move verbs in the rendered prompt of a DIALOGUE unit.

Roger 2026-10-30 (E12 成片审看 item 2): dialogue units default to a locked-off camera; a move is allowed
only when the directing script's own camera text asks for one, and a move never reverses direction inside
a unit.  This lint reads the rendered H3 video prompt (English) and the keyframe prompt (Chinese) and
returns the offending tokens, so prompt_batch_qa can record
  vp_dialogue_unit_locked_camera   FAIL  <tokens>          (dialogue unit, no authored move, move verbs present)
  vp_camera_move_single_direction  FAIL  <dir_a>→<dir_b>   (two shots of one unit with opposite directions)

Pure functions, no I/O.  Proposed home: lines/nalu/runtime/tools/camera_move_lint.py
"""
from __future__ import annotations

import re

# English (H3 renderer _MOTION_MAPPING + free text) and Chinese (keyframe / directing script) move verbs.
EN_MOVE = re.compile(
    r"\b(dolly(?: move)?|push(?:es|ed|ing)? in|pull(?:s|ed|ing)? out|pan(?:s|ning)?|tilt(?:s|ing)?|"
    r"track(?:s|ing)?(?: shot| move)?|lateral track|truck|arc move|orbit(?:s|ing)?|crane|handheld|"
    r"zoom(?:s|ing)? (?:in|out)|follow(?:s|ing)? (?:the|him|her|them)|whip|axial follow|vertical move)\b",
    re.IGNORECASE)
ZH_MOVE = re.compile(r"(推近|推进|推镜|拉远|拉出|拉镜|横摇|竖摇|摇镜|摇到|跟拍|跟随|跟移|横移|移动机位|环绕|弧形|升镜|降镜|升起|下降|手持|变焦|推拉)")
#: wording the H3 renderer emits for a locked plan and the explicit grammar lock — never offences
LOCK_WORDS = re.compile(r"(locked camera|fixed camera position|固定机位|locked-off|tripod)", re.IGNORECASE)
#: a directing-script camera slug / lens_intent that AUTHORS a move (the only thing that may unlock a dialogue shot)
AUTHORED_MOVE = re.compile(r"(推近|推进|推拉|拉开|拉远|拉出|摇|跟|移|环绕|弧|升|降|手持|dolly|push|pull|pan|tilt|track|arc|crane|orbit)", re.IGNORECASE)

OPPOSITES = {("PUSH_IN", "PULL_OUT"), ("LEFT_TO_RIGHT", "RIGHT_TO_LEFT"), ("RISE", "FALL"),
             ("CLOCKWISE", "COUNTERCLOCKWISE")}


#: a move verb that is being FORBIDDEN is not a move ("no push in, no pull out, no pan, no tilt, no tracking";
#: "never reverses"; 「不得推拉」) — the renderer's own lock wording must not trip the lint
NEGATED_MOVE = re.compile(
    r"\b(?:no|never|without|not)\s+(?:any\s+)?(?:push(?:es|ed|ing)?\s+in|pull(?:s|ed|ing)?\s+out|pan(?:s|ning)?|tilt(?:s|ing)?|"
    r"track(?:s|ing)?(?:\s+shot|\s+move)?|dolly(?:\s+move)?|zoom(?:s|ing)?(?:\s+(?:in|out))?|orbit(?:s|ing)?|crane|handheld|"
    r"reverses?|oscillates?|drifts?\s+back)\b", re.IGNORECASE)
ZH_NEGATED_MOVE = re.compile(r"(不得|不要|不|禁止|无)(推近|推进|推拉|拉远|拉出|拉镜|横摇|竖摇|摇镜|跟拍|跟随|横移|环绕|升降|手持|变焦|运镜|机位移动)")


def strip_negated_moves(text: str) -> str:
    return ZH_NEGATED_MOVE.sub("", NEGATED_MOVE.sub("", text or ""))


def move_tokens(text: str) -> list[str]:
    """Distinct camera-move tokens found in a prompt (English + Chinese), lower-cased, in order; forbidden moves
    ("no pan", 「不得推拉」) are not counted."""
    seen: list[str] = []
    text = strip_negated_moves(text)
    for m in [*EN_MOVE.finditer(text or ""), *ZH_MOVE.finditer(text or "")]:
        tok = m.group(0).lower()
        if tok not in seen:
            seen.append(tok)
    return seen


def authored_move(camera_text: str | None) -> bool:
    """True when the writer's own camera text (directing script slug / lens_intent) asks for a move."""
    return bool(camera_text) and bool(AUTHORED_MOVE.search(str(camera_text)))


def dialogue_unit_locked_camera(prompt_text: str, *, has_dialogue: bool, authored_camera_text: str | None) -> dict:
    """Check one rendered prompt.  PASS when the unit has no dialogue, or the move was authored, or no move
    verb appears; FAIL lists the tokens.  A locked plan with the lock words present never fails."""
    if not has_dialogue:
        return {"id": "vp_dialogue_unit_locked_camera", "status": "PASS", "detail": "no dialogue"}
    if authored_move(authored_camera_text):
        return {"id": "vp_dialogue_unit_locked_camera", "status": "PASS",
                "detail": f"move authored by directing script: {authored_camera_text}"}
    toks = move_tokens(prompt_text)
    if LOCK_WORDS.search(prompt_text or "") and not toks:
        return {"id": "vp_dialogue_unit_locked_camera", "status": "PASS", "detail": "locked camera"}
    if toks:
        return {"id": "vp_dialogue_unit_locked_camera", "status": "FAIL",
                "detail": "dialogue unit prompt asks for a camera move without an authored one: " + ", ".join(toks)}
    return {"id": "vp_dialogue_unit_locked_camera", "status": "PASS", "detail": "no camera-move verb"}


def single_direction(per_shot_plans: list[dict]) -> dict:
    """Two shots of one unit must not move in opposite directions of the same family (a reversal inside the clip)."""
    dirs = [(str(p.get("motion_family") or "").upper(), str(p.get("motion_direction") or "").upper()) for p in per_shot_plans]
    for (fa, da), (fb, db) in zip(dirs, dirs[1:]):
        if fa == fb and ((da, db) in OPPOSITES or (db, da) in OPPOSITES):
            return {"id": "vp_camera_move_single_direction", "status": "FAIL", "detail": f"{fa}:{da}→{db}"}
    return {"id": "vp_camera_move_single_direction", "status": "PASS", "detail": "/".join(f"{f}:{d}" for f, d in dirs) or "n/a"}


# --------------------------------------------------------------------------- silent beats (K138)
#: the renderer's per-beat sentence for a beat of a dialogue unit that carries no dialogue literal
NO_SPEECH_SENTENCE = "No speech in this beat"
D_TAG = re.compile(r"<d>\[(?:Chinese|English)\]")
BEAT_LINE = re.compile(r"^\[\d+(?:\.\d+)?s-\d+(?:\.\d+)?s\]", re.MULTILINE)


def silent_beats_declared(prompt_text: str, *, has_dialogue: bool) -> dict:
    """K138 (H3 vocalises beats without a dialogue literal): in a dialogue unit every timed beat line that
    carries no <d> literal must carry the explicit no-speech sentence.  Units without dialogue already get the
    unit-wide closed-mouth rule from the renderer and PASS here."""
    if not has_dialogue:
        return {"id": "vp_silent_beats_declared", "status": "PASS", "detail": "no dialogue unit"}
    text = prompt_text or ""
    starts = [m.start() for m in BEAT_LINE.finditer(text)]
    if not starts:
        return {"id": "vp_silent_beats_declared", "status": "PASS", "detail": "no timed beat lines (legacy prompt)"}
    missing = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        beat = text[start:end]
        if not D_TAG.search(beat) and NO_SPEECH_SENTENCE not in beat:
            missing.append(beat[:beat.find("]") + 1])
    if missing:
        return {"id": "vp_silent_beats_declared", "status": "FAIL",
                "detail": "beats without a dialogue literal and without the no-speech instruction: " + ", ".join(missing)}
    return {"id": "vp_silent_beats_declared", "status": "PASS", "detail": f"{len(starts)} beats"}
