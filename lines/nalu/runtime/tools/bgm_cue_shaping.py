#!/usr/bin/env python3
"""BGM cue shaping on the release timeline (owner 2026-11-19: music played for one or two shots, then stopped).

Why it sounded broken: a SELECTIVE cue is declared on shots, so an authored cue on one 3-5 s shot was placed as a
3-5 s window; ``fit_cues_to_cut`` / ``fit_cues_to_sources`` then shaved entries down to an 8 s floor; every cue
faded in over 0.5 s and out over 0.75 s wherever its last shot happened to end -- mid-scene, mid-phrase -- and two
cues a few seconds apart flickered music / silence / music.  Under dialogue the duck was -6 dB.

Rules (owner 2026-11-19 spec; music MAY change or stop at a scene or mood change, never abruptly or as a fragment):

1. A cue may end or switch only at a scene / location boundary or a mood change the script marks (a PAYOFF shot's
   end, a shot with ``prompt_spec.scene_turn``).  An end within ``SNAP_SECONDS`` of one snaps to it; otherwise the
   cue runs on to the next boundary when its generated source holds that much (no loop, no stretch: the QA gate
   forbids both), else back to the previous boundary, else it ends where it is with the longer fade.
2. Ends: (a) FADE_OUT over ``FADE_OUT_SECONDS`` (``LONG_FADE_OUT_SECONDS`` when the end is not on a boundary);
   (b) CROSSFADE into the next cue, overlapping ``CROSSFADE_SECONDS``, when the next cue starts within
   ``FLICKER_GAP_SECONDS`` (equal-power curves); (c) HIT_STOP only on a marked hit (PAYOFF end, ``music_hit``,
   a sting cue): the music stops on the hit with a ``HIT_DECAY_SECONDS`` decay tail, never a dead cut.
3. Entry: FADE_IN over ``FADE_IN_SECONDS``; a cue entering on a scene cut PRE-LAPs it by ``PRELAP_SECONDS``;
   an instant (``HIT_FADE_IN_SECONDS``) entry only on a marked hit.
4. Minimum length ``min_cue_seconds`` (``NALU_BGM_MIN_CUE_SECONDS``, default 12 s) unless the cue is a sting
   (``"sting": true`` or a narrative function containing STING): a short cue is extended to the next boundary
   (or starts at its scene's start) within its source, else dropped.  Two cues of the same source closer than
   the flicker gap are one cue.
5. Under dialogue the music ducks by ``DUCK_DB`` (-10 dB: the owner's -10..-14 dB meets the authenticity gate's
   -6..-10 dB at -10), never muted.  Audibility under lines (device 1101 E24) comes from the louder bed pad
   (final_cut_audio_bed.PAD_LEVEL_DBFS), not a shallower duck.
6. BILI_V1 (craft_profile.py; WP5-B, Bilibili benchmark 2026-11-23: both benchmarks hold the music in pauses at about
   dialogue level, ours sat at -24..-35 LUFS): the bed plays at ``BILI_V1_BED_VOLUME`` (0.24, was 0.14) with the same
   -10 dB duck, so pauses come up ~4.7 dB, and it reaches full level only ``BILI_V1_DUCK_GUARD_S`` + ``DUCK_RAMP_S``
   (0.4 s) away from a line.  ``bed_volume`` is the one place that decides the cue volume.
7. Hard stop (WP5-C, ``bgm_mood_cues``; ep3 "elevator ding"): ``stops`` (release-timeline seconds of shots the
   writer marked ``music_stop``) end the cue exactly there with a ``HARD_STOP_FADE_SECONDS`` fade; a cue never
   runs, extends or merges across a stop.  No stops (every LEGACY contract) = the rules above unchanged.

Pure functions; the S7 BGM plan (nalu_selective_bgm.cmd_plan) applies them before the coverage policy.
"""
from __future__ import annotations

import os
from typing import Any

SNAP_SECONDS = 1.0
MIN_CUE_SECONDS = 12.0
MIN_CUE_ENV = "NALU_BGM_MIN_CUE_SECONDS"
FLICKER_GAP_SECONDS = 6.0
CROSSFADE_SECONDS = 1.5
FADE_IN_SECONDS = 1.5
HIT_FADE_IN_SECONDS = 0.05
FADE_OUT_SECONDS = 2.5
LONG_FADE_OUT_SECONDS = 3.0
HIT_DECAY_SECONDS = 0.4
PRELAP_SECONDS = 0.75
HIT_TOLERANCE_SECONDS = 0.3
DUCK_DB = -10.0
SOURCE_TAIL_MARGIN_S = 0.5
#: WP5-B (BILI_V1): bed volume 0.14 -> 0.24 (+4.7 dB in pauses) with the same DUCK_DB; full level only when no line
#: is within BILI_V1_DUCK_GUARD_S + the mix ramp (nalu_selective_bgm.DUCK_RAMP_S 0.25) = 0.4 s
LEGACY_BED_VOLUME = 0.14
BILI_V1_BED_VOLUME = 0.24
BILI_V1_DUCK_GUARD_S = 0.15
#: WP5-C hard stop on a story beat (a shot marked music_stop): the cue ends on the shot start with this fade
HARD_STOP_FADE_SECONDS = 0.1

END_TYPES = ("FADE_OUT", "CROSSFADE", "HIT_STOP")
ENTRY_TYPES = ("FADE_IN", "PRELAP", "HIT_ENTRY", "CROSSFADE_IN")


FADE_SCALE_ENV = "NALU_BGM_FADE_SCALE"


def fade_scale(environ: dict[str, str] | None = None) -> float:
    """Multiplier on the fade-in / fade-out lengths (``NALU_BGM_FADE_SCALE``, 1.0..3.0; default 1.0 = unchanged).
    The final fix round (owner 2026-11-20) sets it after a confirmed abrupt music start / stop."""
    env = os.environ if environ is None else environ
    try:
        return min(3.0, max(1.0, float(env.get(FADE_SCALE_ENV) or 1.0)))
    except ValueError:
        return 1.0


def min_cue_seconds(environ: dict[str, str] | None = None) -> float:
    env = os.environ if environ is None else environ
    try:
        return max(4.0, float(env.get(MIN_CUE_ENV) or MIN_CUE_SECONDS))
    except ValueError:
        return MIN_CUE_SECONDS


def bed_volume(authored: Any, *, bili_v1: bool) -> float:
    """The cue volume: LEGACY = the authored value, else 0.14 (unchanged); BILI_V1 = 0.24 when the cue is silent or
    carries the old boilerplate 0.14 (the tool's documented example), else the authored value."""
    if authored is None or authored == "":
        return BILI_V1_BED_VOLUME if bili_v1 else LEGACY_BED_VOLUME
    value = float(authored)
    if bili_v1 and abs(value - LEGACY_BED_VOLUME) < 1e-9:
        return BILI_V1_BED_VOLUME
    return value


def is_sting(cue: dict[str, Any]) -> bool:
    return bool(cue.get("sting")) or "STING" in str(cue.get("narrative_function") or "").upper()


def _role(shot: dict[str, Any]) -> str:
    spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
    return str(spec.get("beat_role") or shot.get("beat_role") or "").strip().upper()


def _flag(shot: dict[str, Any], key: str) -> bool:
    spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
    transition = spec.get("transition") if isinstance(spec.get("transition"), dict) else {}
    return bool(shot.get(key) or spec.get(key) or transition.get(key))


def boundaries(shots_tl: list[dict[str, Any]], content: float) -> dict[str, list[float]]:
    """Release-timeline boundaries from shot windows [{shot_id, t0, t1, scene_id, shot}] in timeline order:
    ``allowed`` (scene changes, marked mood changes, the episode end, 0) and ``hits`` (PAYOFF ends, music_hit)."""
    allowed, hits = {0.0, round(float(content), 3)}, set()
    prev = None
    for row in shots_tl:
        shot = row.get("shot") or {}
        if prev is not None and str(row.get("scene_id") or "") != str(prev.get("scene_id") or ""):
            allowed.add(round(float(row["t0"]), 3))
        if _flag(shot, "scene_turn"):
            allowed.add(round(float(row["t0"]), 3))
        if _role(shot) == "PAYOFF" or _flag(shot, "music_hit"):
            allowed.add(round(float(row["t1"]), 3))
            hits.add(round(float(row["t1"]), 3))
        prev = row
    return {"allowed": sorted(b for b in allowed if 0.0 <= b <= content + 1e-6), "hits": sorted(hits)}


def _near(t: float, points: list[float], tol: float) -> float | None:
    best = min(points, key=lambda b: abs(b - t), default=None)
    return best if best is not None and abs(best - t) <= tol else None


def shape(cues: list[dict[str, Any]], shots_tl: list[dict[str, Any]], content: float,
          source_seconds: dict[str, float], *, min_cue: float | None = None,
          stops: list[float] | None = None) -> dict[str, Any]:
    """Shape cue windows [{cue_id, source_key, t0, t1, narrative_function?, sting?}] -> {cues, dropped, merged}.

    Each output cue carries t0/t1, fade_in_s, fade_out_s, entry_type, end_type, end_at_boundary, sting and
    fade_curve ("qsin" on crossfades).  ``source_seconds``: source_key -> longest generated source (0 = unknown,
    then nothing is extended past the declared window).  ``stops``: hard-stop times (rule 7; None/[] = none)."""
    min_cue = min_cue_seconds() if min_cue is None else float(min_cue)
    scale = fade_scale()
    fade_in, fade_out, long_fade_out = (round(FADE_IN_SECONDS * scale, 3), round(FADE_OUT_SECONDS * scale, 3),
                                        round(LONG_FADE_OUT_SECONDS * scale, 3))
    content = float(content)
    b = boundaries(shots_tl, content)
    allowed, hits = b["allowed"], b["hits"]
    stop_points = sorted({round(float(x), 3) for x in (stops or []) if 0.0 < float(x) <= content})
    if stop_points:
        allowed = sorted(set(allowed) | set(stop_points))
        b = {**b, "stops": stop_points}

    def stop_after(t: float) -> float | None:
        """The first hard stop strictly after t (a cue starting at t may not run past it)."""
        return next((x for x in stop_points if x > t + 1e-6), None)

    def stop_between(a0: float, a1: float) -> bool:
        return any(a0 - 1e-6 <= x <= a1 + 1e-6 for x in stop_points)

    def held(key: str, fallback: float) -> float:
        src = float(source_seconds.get(key) or 0.0) - SOURCE_TAIL_MARGIN_S
        return src if src > 0 else fallback

    work = sorted(({**c, "t0": float(c["t0"]), "t1": min(float(c["t1"]), content)} for c in cues),
                  key=lambda c: c["t0"])
    merged_ids: list[list[str]] = []
    # 0. same source, closer than the flicker gap: one cue (music, gap, the same music is a flicker)
    out: list[dict[str, Any]] = []
    for c in work:
        if (out and c["source_key"] == out[-1]["source_key"] and c["t0"] - out[-1]["t1"] < FLICKER_GAP_SECONDS
                and max(c["t1"], out[-1]["t1"]) - out[-1]["t0"] <= held(c["source_key"], float("inf"))
                and not stop_between(out[-1]["t1"], c["t0"])):
            merged_ids.append([out[-1]["cue_id"], c["cue_id"]])
            out[-1]["t1"] = max(out[-1]["t1"], c["t1"])
            out[-1]["merged_cue_ids"] = out[-1].get("merged_cue_ids", [out[-1]["cue_id"]]) + [c["cue_id"]]
            out[-1]["sting"] = False
            continue
        out.append(dict(c))
    shaped, dropped = [], []
    for c in out:
        sting = is_sting(c)
        limit = held(c["source_key"], c["t1"] - c["t0"])
        t0, t1 = c["t0"], c["t1"]
        cap = stop_after(t0)
        if cap is not None:   # rule 7: never past a hard stop; an end within SNAP_SECONDS of one lands on it
            limit = min(limit, cap - t0)
            if t1 > cap or abs(t1 - cap) <= SNAP_SECONDS and cap - t0 <= limit:
                t1 = cap
        # 1. the end goes to a boundary: snap, else run on to the next one the source can reach, else back
        at = _near(t1, allowed, SNAP_SECONDS)
        if at is not None and at > t0:
            t1 = at
        else:
            nxt = next((x for x in allowed if x > t1), None)
            prv = next((x for x in reversed(allowed) if t0 < x < t1), None)
            if nxt is not None and nxt - t0 <= limit:
                t1 = nxt
            elif prv is not None and (prv - t0 >= min_cue or sting):
                t1 = prv
        # 2. minimum length: extend to later boundaries, else start at an earlier one, else drop
        if t1 - t0 < min_cue and not sting:
            for x in allowed:
                if x > t1 and x - t0 <= limit:
                    t1 = x
                    if t1 - t0 >= min_cue:
                        break
            if t1 - t0 < min_cue:
                for x in reversed(allowed):
                    if x < t0 and t1 - x <= limit:
                        t0 = x
                        if t1 - t0 >= min_cue:
                            break
        if t1 - t0 < min_cue and not sting:
            dropped.append({"cue_id": c["cue_id"], "t0": round(c["t0"], 3), "t1": round(c["t1"], 3),
                            "reason": "FRAGMENT_SHORTER_THAN_MIN_CUE"})
            continue
        end_on_boundary = _near(t1, allowed, 1e-3) is not None
        row = {**c, "t0": round(t0, 3), "t1": round(t1, 3), "sting": sting, "end_at_boundary": end_on_boundary}
        # 3. entry
        if _near(t0, hits, HIT_TOLERANCE_SECONDS) is not None:
            row.update(entry_type="HIT_ENTRY", fade_in_s=HIT_FADE_IN_SECONDS)
        elif t0 > 0 and _near(t0, allowed, 1e-3) is not None:
            row.update(entry_type="PRELAP", fade_in_s=fade_in,
                       t0=round(max(0.0, t0 - PRELAP_SECONDS), 3), prelap_s=PRELAP_SECONDS)
        else:
            row.update(entry_type="FADE_IN", fade_in_s=fade_in)
        # 4. end
        if cap is not None and abs(t1 - cap) <= 1e-3:
            row.update(end_type="HIT_STOP", hard_stop=True, hit_at=round(t1, 3),
                       fade_out_s=HARD_STOP_FADE_SECONDS)
        elif sting or _near(t1, hits, HIT_TOLERANCE_SECONDS) is not None:
            tail_end = min(content, t1 + HIT_DECAY_SECONDS)
            row.update(end_type="HIT_STOP", t1=round(tail_end, 3), fade_out_s=round(max(0.05, tail_end - t1), 3),
                       hit_at=round(t1, 3))
        else:
            row.update(end_type="FADE_OUT", fade_out_s=fade_out if end_on_boundary else long_fade_out)
        shaped.append(row)
    # 5. cues closer than the flicker gap crossfade (energy continues; the mood shift is the boundary)
    for a, b2 in zip(shaped, shaped[1:]):
        gap = b2["t0"] - a["t1"]
        if a["end_type"] == "HIT_STOP":
            if gap < 0:  # a pre-lap never runs over a hit: the next cue enters on the hit's decay tail end
                b2.update(t0=a["t1"], entry_type="FADE_IN")
            continue
        if gap >= FLICKER_GAP_SECONDS:
            continue
        need_end = b2["t0"] + CROSSFADE_SECONDS
        if need_end <= a["t1"]:            # already overlapping (pre-lap) by more than a crossfade
            b2.update(t0=round(a["t1"] - CROSSFADE_SECONDS, 3))
        elif need_end - a["t0"] <= held(a["source_key"], a["t1"] - a["t0"]):
            a.update(t1=round(need_end, 3))
        else:
            b2_start = max(a["t0"] + 1.0, a["t1"] - CROSSFADE_SECONDS)
            if b2["t1"] - b2_start > held(b2["source_key"], b2["t1"] - b2["t0"]):
                a["flicker_unresolved"] = round(gap, 3)
                continue
            b2.update(t0=round(b2_start, 3))
        a.update(end_type="CROSSFADE", fade_out_s=CROSSFADE_SECONDS, fade_curve="qsin")
        b2.update(entry_type="CROSSFADE_IN", fade_in_s=CROSSFADE_SECONDS, fade_curve="qsin")
    for row in shaped:
        row["fade_in_s"] = round(min(row["fade_in_s"], max(0.05, (row["t1"] - row["t0"]) / 3)), 3)
        row["fade_out_s"] = round(min(row["fade_out_s"], max(0.05, (row["t1"] - row["t0"]) / 3)), 3)
    return {"cues": shaped, "dropped": dropped, "merged": merged_ids, "boundaries": b,
            "rule": {"min_cue_seconds": min_cue, "snap_seconds": SNAP_SECONDS, "flicker_gap_seconds": FLICKER_GAP_SECONDS,
                     "crossfade_seconds": CROSSFADE_SECONDS, "fade_in_seconds": fade_in,
                     "fade_out_seconds": fade_out, "long_fade_out_seconds": long_fade_out,
                     **({"fade_scale": scale} if scale != 1.0 else {}),
                     "hit_decay_seconds": HIT_DECAY_SECONDS, "prelap_seconds": PRELAP_SECONDS, "duck_db": DUCK_DB,
                     **({"hard_stop_fade_seconds": HARD_STOP_FADE_SECONDS} if stop_points else {})}}


def allowed_overlap(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Seconds two consecutive cues may overlap: their crossfade, else none."""
    if a.get("end_type") == "CROSSFADE":
        return float(a.get("fade_out_s") or 0.0) + 0.01
    return 0.0
