#!/usr/bin/env python3
"""SCENE_LOCATION_LOCK_V1 -- one scene, one place (pure, free, no provider call).

Line owner 2026-11-22 (JA-01 anime E08, device 1485): a three-person back-and-forth conversation where every
speaker's shots had a different background -- council hall with a banner, market with an awning, courtyard with
bunting.  The script had split the continuing conversation over scene_ids with different location_ids (the S1 check
for that is ``script_pacing_check.CONVERSATION_SPLIT_ACROSS_LOCATIONS``).  This module holds the downstream half:

* :func:`scene_location_receipt` -- every editorial shot of one scene_id carries that scene's location and scene
  state (``prompt_spec.space.location`` / ``prompt_spec.scene_state`` come from the scene's ``scene_states`` row;
  only a declared ``shot_scene_overrides`` cross-cut may differ).  The receipt names any shot whose place was not
  taken from its scene -- the engine invariant the keyframe scene plate and the H3 setting text rely on.
* :func:`location_reference_for_unit` -- a video unit whose predecessor tail was rejected (#286: it opens on its own
  keyframe, no tail reaches the provider) keeps the scene's place in shot / reverse-shot through one
  "background / location only" reference: the scene's LOCKED location plate (stage 3(a), no people), else the
  earliest keyframe of the same scene that shows nobody outside this unit's cast (never another character's face:
  that is what made H3 morph one speaker into the other in #286).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

SCHEMA = "nalu.scene_location_lock.v1"
POLICY = "SCENE_LOCATION_LOCK_V1"
#: reference role of the scene's location image on a tail-rejected unit (no entity binding: it identifies nobody)
LOCATION_REFERENCE_ROLE = "SCENE_LOCATION_REFERENCE"
TAIL_REJECTED_START_FRAME_SOURCE = "OWN_KEYFRAME_TAIL_REJECTED"
#: scene-state keys the scene row owns (a shot may only change them through shot_scene_overrides)
STATE_KEYS = ("time", "weather", "lighting")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def scene_location_receipt(shots: list[dict[str, Any]], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """{schema, policy, scenes {scene_id: location}, violations [...]} over editorial shots (episode order).  A shot
    whose location / scene state differs from its scene's first shot without a declared override is a violation."""
    overrides = overrides if isinstance(overrides, dict) else {}
    first: dict[str, dict[str, str]] = {}
    violations: list[str] = []
    for shot in shots or []:
        spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
        scene = _clean(shot.get("scene_id"))
        sid = _clean(shot.get("shot_id"))
        state = spec.get("scene_state") if isinstance(spec.get("scene_state"), dict) else {}
        row = {"location": _clean((spec.get("space") or {}).get("location")),
               **{k: _clean(state.get(k)) for k in STATE_KEYS}}
        if sid in overrides:
            continue  # a declared cross-cut keeps its own place
        if scene not in first:
            first[scene] = row
            continue
        for key, value in row.items():
            if value != first[scene][key]:
                violations.append(f"SCENE_{key.upper()}_NOT_SHARED:{scene}:{sid}:{value or '-'}!={first[scene][key] or '-'}")
    return {"schema": SCHEMA, "policy": POLICY, "scenes": {k: v["location"] for k, v in first.items()},
            "violations": violations}


def _visible_ids(spec: dict[str, Any]) -> set[str]:
    return {_clean(m.get("character_id") or m.get("character")) for m in spec.get("cast") or []
            if isinstance(m, dict) and _clean(m.get("face_visibility")).upper() != "OFFSCREEN_VOICE_ONLY"
            and _clean(m.get("character_id") or m.get("character"))}


def _latest_keyframe(keyframe_dir: Path, shot_id: str) -> Path | None:
    candidates = list(Path(keyframe_dir).glob(f"{shot_id}-keyframe-v*.png"))

    def version(path: Path) -> int:
        match = re.search(r"-keyframe-v(\d+)\.png$", path.name)
        return int(match.group(1)) if match else 0

    best = max(candidates, key=version) if candidates else None
    return best if best is not None and best.is_file() else None


def tail_rejected(unit: dict[str, Any]) -> bool:
    return _clean((unit.get("opening_anchor_contract") or {}).get("start_frame_source")) == \
        TAIL_REJECTED_START_FRAME_SOURCE


def location_reference_for_unit(unit: dict[str, Any], unit_shot_ids: list[str], editorial: dict[str, Any], *,
                                scene_plate: Callable[[str], Path | None] | None = None,
                                keyframe_dir: Path | None = None) -> dict[str, Any] | None:
    """The scene location reference of one tail-rejected unit, or None.

    {path, source: LOCKED_SCENE_PLATE | SCENE_KEYFRAME, location_id, scene_id, source_shot_id?}.  ``scene_plate``
    resolves a location id to its LOCKED plate (None = no plate); ``keyframe_dir`` (default: the directory of the
    unit's opening reference) holds ``<shot>-keyframe-vN.png``.  A keyframe is used only when everyone it shows is
    on screen in this unit (an empty establishing view qualifies)."""
    if not tail_rejected(unit):
        return None
    shots = [s for s in editorial.get("shots") or [] if isinstance(s, dict)]
    by_id = {_clean(s.get("shot_id")): s for s in shots}
    own = [by_id[sid] for sid in unit_shot_ids if sid in by_id]
    if not own:
        return None
    scene_id = _clean(own[0].get("scene_id"))
    location = _clean(((own[0].get("prompt_spec") or {}).get("space") or {}).get("location"))
    existing = {str(p) for p in unit.get("reference_image_paths") or []}
    if scene_plate is not None and location:
        plate = scene_plate(location)
        if plate is not None and str(plate) not in existing:
            return {"path": str(plate), "source": "LOCKED_SCENE_PLATE", "location_id": location, "scene_id": scene_id}
    paths = [p for p in unit.get("reference_image_paths") or [] if p]
    folder = Path(keyframe_dir) if keyframe_dir is not None else (Path(str(paths[0])).parent if paths else None)
    if folder is None or not folder.is_dir():
        return None
    cast: set[str] = set()
    for shot in own:
        cast |= _visible_ids(shot.get("prompt_spec") or {})
    for shot in shots:
        sid = _clean(shot.get("shot_id"))
        if _clean(shot.get("scene_id")) != scene_id or sid in unit_shot_ids:
            continue
        spec = shot.get("prompt_spec") or {}
        if _clean((spec.get("space") or {}).get("location")) != location:
            continue  # a cross-cut shot of the scene shows another place
        if not _visible_ids(spec) <= cast:
            continue  # never hand H3 another character's face (#286 in-shot identity swap)
        frame = _latest_keyframe(folder, sid)
        if frame is not None and str(frame) not in existing:
            return {"path": str(frame), "source": "SCENE_KEYFRAME", "location_id": location, "scene_id": scene_id,
                    "source_shot_id": sid}
    return None
