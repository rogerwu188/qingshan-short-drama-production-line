#!/usr/bin/env python3
"""Dialogue sound bridge / L-cut (CAMERA_GRAMMAR_V1 episodes only; line owner 2026-10-23).

A silent reaction shot that directly follows a dialogue shot may author
``prompt_spec.transition.sound_bridge_from_previous_seconds`` (0.3-2.0 s).  At assembly the
speaker unit's PICTURE is cut that many seconds earlier, while its AUDIO plays out over the start
of the reaction shot: the line ends over the listener's face, as in human-cut dialogue.

The cut is applied where the dialogue tail trim already shapes the unit clips (the AgentCut build,
``--dialogue-sound-bridge``): the speaker clip (video + audio) is shortened by the bridge and every
later clip moves up, so the renderer, captions, V.O., BGM and the release timeline all see the new
cut.  After the render, S7 mixes the speaker's cut-off audio back in over the reaction picture
(``mix_filter``) with the reaction's own native audio ducked to ambience (``DUCK_DB``) under that
window and a short crossfade back; the video stream is copied.  Captions keep the speaker clip's
bridge (clip metadata ``sound_bridge_out``), so the line's subtitle continues over the reaction.

Clamps: the picture is never cut before the speaker's last line starts (its last unit-ASR segment),
the reaction picture outlasts the bridged audio by ``MIN_REACTION_TAIL_SECONDS``, a bridge shorter
than ``MIN_APPLIED_SECONDS`` after clamping is skipped.  A bridge only exists at a unit boundary
(a cut inside one H3 clip cannot be L-cut).  No field -> nothing happens.  Never a gate: every
unusable request is recorded with its reason and assembly continues without it.
"""

from __future__ import annotations

from typing import Any

SCHEMA = "nalu.dialogue_sound_bridge.v1"
FIELD = "sound_bridge_from_previous_seconds"
MIN_SECONDS = 0.3
MAX_SECONDS = 2.0
MIN_APPLIED_SECONDS = 0.1
MIN_REACTION_TAIL_SECONDS = 0.5
DUCK_DB = -18.0
FADE_SECONDS = 0.06
VOICE_ONLY_MODE = "VOICE_ONLY_NO_PLATE"


def requested_seconds(shot: dict[str, Any]) -> float | None:
    """The authored bridge, clamped to [MIN_SECONDS, MAX_SECONDS]; None when absent or unusable."""
    transition = (shot.get("prompt_spec") or {}).get("transition")
    if not isinstance(transition, dict) or transition.get(FIELD) in (None, ""):
        return None
    try:
        value = float(transition[FIELD])
    except (TypeError, ValueError):
        return None
    if value != value or value <= 0:
        return None
    return round(min(MAX_SECONDS, max(MIN_SECONDS, value)), 3)


def plan(contract: dict[str, Any], grouping: dict[str, Any], unit_asr: dict[str, Any]) -> dict[str, Any]:
    """Rows for every authored bridge: status REQUESTED (to apply at the build) or SKIPPED + reason."""
    shots = [s for s in contract.get("shots") or [] if isinstance(s, dict)]
    order = [str(s.get("shot_id")) for s in shots]
    voice_only = {str(e.get("character_id")) for e in contract.get("character_entities") or []
                  if str((e.get("identity_source") or {}).get("mode") or "") == VOICE_ONLY_MODE}
    lines_by_shot: dict[str, list[dict[str, Any]]] = {}
    for row in (contract.get("audio_contract") or {}).get("dialogue_units") or []:
        lines_by_shot.setdefault(str(row.get("shot_id") or ""), []).append(row)
    units = sorted((u for u in grouping.get("units") or []), key=lambda u: str(u.get("unit_id")))
    unit_of = {str(sid): (i, str(u.get("unit_id"))) for i, u in enumerate(units)
               for sid in u.get("editorial_shot_ids") or []}
    rows: list[dict[str, Any]] = []
    for index, shot in enumerate(shots):
        want = requested_seconds(shot)
        if want is None:
            continue
        sid = order[index]
        row: dict[str, Any] = {"to_shot_id": sid, "requested_seconds": want, "status": "SKIPPED",
                               "authored_value": ((shot.get("prompt_spec") or {}).get("transition") or {}).get(FIELD)}
        rows.append(row)
        if index == 0:
            row["reason"] = "NO_PREVIOUS_SHOT"
            continue
        prev_sid = order[index - 1]
        row["from_shot_id"] = prev_sid
        if sid not in unit_of or prev_sid not in unit_of:
            row["reason"] = "SHOT_NOT_GROUPED"
            continue
        (u_index, uid), (p_index, prev_uid) = unit_of[sid], unit_of[prev_sid]
        row.update({"from_unit_id": prev_uid, "to_unit_id": uid})
        first = [str(s) for s in units[u_index].get("editorial_shot_ids") or []][:1]
        last = [str(s) for s in units[p_index].get("editorial_shot_ids") or []][-1:]
        if p_index != u_index - 1 or first != [sid] or last != [prev_sid]:
            row["reason"] = "NOT_AT_UNIT_BOUNDARY"
            continue
        if lines_by_shot.get(sid):
            row["reason"] = "REACTION_SHOT_HAS_DIALOGUE"
            continue
        prev_lines = lines_by_shot.get(prev_sid) or []
        if not prev_lines:
            row["reason"] = "PREVIOUS_SHOT_HAS_NO_DIALOGUE"
            continue
        if any(str(line.get("speaker_id") or "") in voice_only for line in prev_lines):
            row["reason"] = "PREVIOUS_SHOT_HAS_VOICE_OVER"
            continue
        segs = [s for s in unit_asr.get(prev_uid) or []
                if s.get("start") is not None and str(s.get("text") or "").strip()]
        if not segs:
            row["reason"] = "SPEAKER_LINE_START_UNKNOWN"
            continue
        row.update({"status": "REQUESTED", "line_start_seconds": round(max(float(s["start"]) for s in segs), 3)})
    return {"schema": SCHEMA, "episode": contract.get("episode"), "field": f"prompt_spec.transition.{FIELD}",
            "range_seconds": [MIN_SECONDS, MAX_SECONDS], "duck_db": DUCK_DB, "fade_seconds": FADE_SECONDS,
            "requested": sum(1 for r in rows if r["status"] == "REQUESTED"), "rows": rows}


def bridge_seconds(requested: float, speaker_in: float, speaker_duration: float, line_start: float,
                   reaction_duration: float) -> float:
    """Applied bridge after the clamps (0.0 = not applied).

    The picture cut (speaker_in + speaker_duration - bridge) never lands before the line start, and
    the reaction clip lasts at least MIN_REACTION_TAIL_SECONDS longer than the bridge."""
    room_in_line = speaker_in + speaker_duration - max(line_start, speaker_in)
    seconds = min(float(requested), room_in_line, reaction_duration - MIN_REACTION_TAIL_SECONDS,
                  speaker_duration)
    seconds = round(seconds, 6)
    return seconds if seconds >= MIN_APPLIED_SECONDS else 0.0


def apply(video_clips: list[dict[str, Any]], audio_clips: list[dict[str, Any]], report: dict[str, Any]
          ) -> list[dict[str, Any]]:
    """Shorten each bridged speaker clip pair, tag both sides, re-pack every start; returns applied rows.

    Rows carry final-timeline seconds of the native cut: ``picture_cut_seconds`` (reaction picture
    starts) to ``bridge_end_seconds`` (speaker audio ends), plus the speaker's audio source/in/volume."""
    position = {str((c.get("metadata") or {}).get("source_id")): i for i, c in enumerate(video_clips)}
    applied: list[dict[str, Any]] = []
    for row in report.get("rows") or []:
        if row.get("status") != "REQUESTED":
            continue
        i, j = position.get(str(row.get("from_unit_id"))), position.get(str(row.get("to_unit_id")))
        out = dict(row)
        if i is None or j is None or j != i + 1:
            out.update(status="SKIPPED", reason="UNITS_NOT_ADJACENT_ON_TIMELINE")
            applied.append(out)
            continue
        video, audio, reaction = video_clips[i], audio_clips[i], video_clips[j]
        speaker_in, speaker_duration = float(video.get("in") or 0.0), float(video["duration"])
        seconds = bridge_seconds(float(row["requested_seconds"]), speaker_in, speaker_duration,
                                 float(row["line_start_seconds"]), float(reaction["duration"]))
        if seconds <= 0:
            out.update(status="SKIPPED", reason="CLAMPED_BELOW_MINIMUM")
            applied.append(out)
            continue
        kept = round(speaker_duration - seconds, 6)
        audio_in = round(float(audio.get("in") or 0.0) + kept, 6)
        tag = {"seconds": seconds, "speaker_unit_id": row["from_unit_id"], "reaction_unit_id": row["to_unit_id"],
               "picture_seconds_before": speaker_duration, "audio_source": audio.get("source"),
               "audio_in": audio_in, "volume": audio.get("volume", 1.0)}
        for clip in (video, audio):
            clip["duration"] = kept
            clip.setdefault("metadata", {})["sound_bridge_out"] = tag
        for clip in (video_clips[j], audio_clips[j]):
            clip.setdefault("metadata", {})["sound_bridge_in"] = {"seconds": seconds,
                                                                 "speaker_unit_id": row["from_unit_id"]}
        out.update(status="APPLIED", applied_seconds=seconds, audio_source=audio.get("source"),
                   audio_in=audio_in, volume=audio.get("volume", 1.0))
        applied.append(out)
    cursor = 0.0
    for video, audio in zip(video_clips, audio_clips):
        video["start"] = audio["start"] = round(cursor, 6)
        cursor += float(video["duration"])
    starts = {str((c.get("metadata") or {}).get("source_id")): float(c["start"]) for c in video_clips}
    for out in applied:
        if out["status"] == "APPLIED":
            cut = starts[str(out["to_unit_id"])]
            out.update(picture_cut_seconds=round(cut, 6), bridge_end_seconds=round(cut + out["applied_seconds"], 6))
    return applied


def duck_expression(windows: list[tuple[float, float]], duck_db: float = DUCK_DB,
                    fade: float = FADE_SECONDS) -> str:
    """ffmpeg volume expression: native audio at ``duck_db`` from each picture cut to the bridge end,
    ramping back to unity over the last ``fade`` seconds of the window; 1 elsewhere."""
    gain = 10 ** (duck_db / 20.0)
    terms = []
    for cut, end in windows:
        ramp = max(cut, end - fade)
        span = max(end - ramp, 1e-3)
        terms.append(f"if(lt(t,{cut:.6f}),1,if(lt(t,{ramp:.6f}),{gain:.6f},"
                     f"if(lt(t,{end:.6f}),{gain:.6f}+{1 - gain:.6f}*(t-{ramp:.6f})/{span:.6f},1)))")
    return "*".join(terms) or "1"


def mix_filter(bridges: list[dict[str, Any]], fade: float = FADE_SECONDS) -> str:
    """filter_complex: input 0 = rendered native cut; input k = bridge k's speaker source.  The
    speaker audio from ``audio_in`` (exactly where the shortened clip stopped) is laid back in at the
    picture cut at its clip volume and faded out at the bridge end; the native is ducked meanwhile."""
    windows = [(float(b["picture_cut_seconds"]), float(b["bridge_end_seconds"])) for b in bridges]
    chains = ["[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
              f"volume='{duck_expression(windows, fade=fade)}':eval=frame[native]"]
    labels = ["[native]"]
    for k, bridge in enumerate(bridges, 1):
        seconds = float(bridge["applied_seconds"])
        ms = int(round(float(bridge["picture_cut_seconds"]) * 1000))
        chains.append(f"[{k}:a]atrim=start={float(bridge['audio_in']):.6f}:duration={seconds:.6f},"
                      "asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                      f"volume={float(bridge.get('volume', 1.0)):g},"
                      f"afade=t=out:st={max(0.0, seconds - fade):.6f}:d={min(fade, seconds):.6f},"
                      f"adelay={ms}|{ms}[sb{k}]")
        labels.append(f"[sb{k}]")
    chains.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:normalize=0[aout]")
    return ";".join(chains)
