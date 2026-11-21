"""Free declared-cast check of a predecessor tail as a unit's start frame (PR #286, shared 2026-11-21).

Pure metadata (no image is read).  Shared by nalu_pipeline (S6, the stamped tail-materialise path) and
build_keyframe_manifest (S5 plan time): the check only reads the editorial manifest and the grouping plan,
so a tail it rejects at S6 is known to be rejected when S5 plans the episode's keyframes.  A unit whose
tail this check rejects opens on its OWN keyframe, which S5 then generates with the rest (device 0080 E05
VU-001, 2026-11-21: the keyframe was only discovered at S6, one unit at a time).
"""
from __future__ import annotations

from typing import Any


#: start-frame cast check (metadata, free): the declared cast of the predecessor's last shot vs this unit's first shot
TAIL_CAST_METHOD = "DECLARED_CAST_TAIL_VS_FIRST_SHOT"


def _shot_in_frame_cast(row: dict[str, Any]) -> list[str]:
    """Character ids a storyboard shot declares in frame (every cast member except an OFFSCREEN_VOICE_ONLY voice)."""
    out: list[str] = []
    for member in ((row or {}).get("prompt_spec") or {}).get("cast") or []:
        cid = str(member.get("character_id") or member.get("character") or "").strip()
        if cid and str(member.get("face_visibility") or "").upper() != "OFFSCREEN_VOICE_ONLY" and cid not in out:
            out.append(cid)
    return out


def _shot_on_screen_speaker(row: dict[str, Any]) -> str:
    """Character id of the shot's dialogue speaker when the storyboard shows that speaker in frame, else ""."""
    spec = (row or {}).get("prompt_spec") or {}
    raw = str(spec.get("dialogue") or "").strip()
    if not raw:
        return ""
    name = raw.partition("：")[0] if "：" in raw else raw.partition(":")[0]
    name = name.strip()
    speaker_id = str((spec.get("role_semantic_disambiguation") or {}).get("dialogue_speaker_id") or "").strip()
    for member in spec.get("cast") or []:
        cid = str(member.get("character_id") or member.get("character") or "").strip()
        if cid and (str(member.get("character") or "").strip() == name or cid == speaker_id):
            return "" if str(member.get("face_visibility") or "").upper() == "OFFSCREEN_VOICE_ONLY" else cid
    return ""


def tail_cast_mismatch(editorial: dict[str, Any], plan: dict[str, Any], unit_id: str,
                       previous_unit_id: str | None) -> dict[str, Any]:
    """Free metadata check of a predecessor tail as ``unit_id``'s start frame (line owner 2026-11-20, JA-01 anime E01:
    "the scene and angle stay the same but the character transforms in place into the one who is speaking").

    A tail-started unit opens on the predecessor's REAL final frame, which shows the predecessor's last shot.  When the
    storyboard's first shot of this unit shows an on-screen speaker who is not in that shot (or a wholly different
    cast), H3 is told the speaker is "already in @Image1" and morphs the visible person into the speaker.  The
    InsightFace start-frame check catches that for live action; for anime it is NOT_APPLICABLE, so nothing did.

    Returns ``{"verdict": "REJECT" | "ACCEPT" | "NOT_MEASURED", "reasons": [...], ...}`` (no image is read)."""
    units = {str(u.get("unit_id") or ""): u for u in plan.get("units") or []}
    shots = {str(r.get("shot_id") or ""): r for r in editorial.get("shots") or []}
    cur_ids = list((units.get(str(unit_id)) or {}).get("editorial_shot_ids") or [])
    prev_ids = list((units.get(str(previous_unit_id or "")) or {}).get("editorial_shot_ids") or [])
    base = {"method": TAIL_CAST_METHOD, "previous_unit_id": previous_unit_id}
    if not cur_ids or not prev_ids or cur_ids[0] not in shots or prev_ids[-1] not in shots:
        return {**base, "verdict": "NOT_MEASURED", "status": "NOT_MEASURED", "reason": "SHOT_ROWS_MISSING",
                "reasons": []}
    tail_cast = _shot_in_frame_cast(shots[prev_ids[-1]])
    first_cast = _shot_in_frame_cast(shots[cur_ids[0]])
    speaker = _shot_on_screen_speaker(shots[cur_ids[0]])
    unit_cast: set[str] = set()
    for sid in cur_ids:
        unit_cast.update(_shot_in_frame_cast(shots.get(sid) or {}))
    reasons = [f"TAIL_SHOWS_OFF_UNIT_CHARACTER:{cid}" for cid in tail_cast if cid not in unit_cast]
    if speaker and speaker not in tail_cast:
        reasons.append(f"ON_SCREEN_SPEAKER_NOT_IN_TAIL:{speaker}")
    if tail_cast and first_cast and not set(tail_cast) & set(first_cast):
        reasons.append("TAIL_SHOWS_A_DIFFERENT_CAST")
    return {**base, "verdict": "REJECT" if reasons else "ACCEPT", "status": "MEASURED", "reasons": reasons,
            "tail_shot_id": prev_ids[-1], "first_shot_id": cur_ids[0], "tail_cast": tail_cast,
            "first_shot_cast": first_cast, "speaker_ids": [speaker] if speaker else []}


def previous_unit_ids(plan: dict[str, Any]) -> dict[str, str | None]:
    """unit_id -> the previous unit in the grouping plan's order (None for the first)."""
    order = [str(u.get("unit_id") or "") for u in plan.get("units") or []]
    return {uid: (order[i - 1] if i > 0 else None) for i, uid in enumerate(order) if uid}
