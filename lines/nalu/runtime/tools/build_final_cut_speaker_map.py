#!/usr/bin/env python3
"""build_final_cut_speaker_map.py — seq=19 (E04 review, C1/C2): who speaks when in the final cut.

The final-cut detectors (tools/final_cut_audience_detectors.py) measure F0 and loudness per ASR
window; to compare a window against a character's pitch band and emotion baseline they need the
CONTRACT's attribution, never a guess from the audio.  This tool derives, for every declared
dialogue line, its expected time on the release timeline:

    time = unit.output_start + (seconds of the unit's earlier shots) + dialogue lead (1.0 s)

from  <assembly>/<EP>_release_timeline.json (unit_id, output_start),
      <preproduction>/<EP>_VIDEO_UNIT_GROUPING_PLAN_V1.json (unit → editorial_shot_ids),
      the generation contract (shots[].target_seconds, audio_contract.dialogue_units[]
      {shot_id, speaker_id, emotion}, scene ids) and, when present, the writer manifest
      structure[] rows typed "action" (→ action windows for the relaxed silent-run limit).

Output {schema, lines:[{time, speaker, emotion, scene, shot_id}], action_windows:[[s,e]],
        undeclared_emotion:[shot_id...]}.

--voice-over-placement (S7 V.O. narration): rows spoken by a VOICE_ONLY_NO_PLATE narrator take the
placement's start/end, carry presence VOICE_OVER, are never attributed native unit-ASR windows, and
are appended to the ASR windows (the narration is real speech in the final cut).
"""
from __future__ import annotations
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))
import nalu_paths as _np  # noqa: F401
if str(_pathlib.Path(__file__).resolve().parents[4] / "tools") not in _sys.path:
    _sys.path.append(str(_pathlib.Path(__file__).resolve().parents[4] / "tools"))  # voice_over_narration

import argparse
import json
from pathlib import Path
from typing import Any

DIALOGUE_LEAD_S = 1.0


def read_json(path: Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def shot_start_times(contract: dict[str, Any], grouping: dict[str, Any],
                     unit_start: dict[str, float]) -> tuple[dict[str, float], dict[str, str]]:
    """Release-timeline start of every shot: unit start + the unit's earlier shots' target_seconds.

    The single source of shot timing for the speaker map and the S7 V.O. placement
    (nalu_pipeline.s7_voice_over), so captions, attribution and narration agree.
    """
    shots = {str(s.get("shot_id")): s for s in contract.get("shots") or []}
    shot_time: dict[str, float] = {}
    unit_of_shot: dict[str, str] = {}
    for unit in grouping.get("units") or []:
        uid = str(unit.get("unit_id"))
        if uid not in unit_start:
            continue
        offset = unit_start[uid]
        for sid in unit.get("editorial_shot_ids") or []:
            sid = str(sid)
            shot_time[sid] = offset
            unit_of_shot[sid] = uid
            offset += float((shots.get(sid) or {}).get("target_seconds") or 0.0)
    return shot_time, unit_of_shot


def _voice_over_rows(contract: dict[str, Any], placement: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    """dialogue_units index -> its V.O. placement row (speaker is a VOICE_ONLY_NO_PLATE narrator)."""
    if not placement:
        return {}
    import voice_over_narration as _vo
    vo_ids = _vo.voice_over_character_ids(contract.get("character_entities") or [], force=True)
    remaining = list(placement.get("rows") or [])
    out: dict[int, dict[str, Any]] = {}
    for index, row in enumerate((contract.get("audio_contract") or {}).get("dialogue_units") or []):
        if str(row.get("speaker_id") or "") not in vo_ids:
            continue
        hit = next((p for p in remaining if str(p.get("shot_id")) == str(row.get("shot_id"))
                    and _vo.norm_text(p.get("text") or "") == _vo.norm_text(row.get("text") or "")), None)
        if hit is not None:
            remaining.remove(hit)
            out[index] = hit
    return out


def build_map(contract: dict[str, Any], grouping: dict[str, Any], timeline: dict[str, Any],
              manifest: dict[str, Any] | None = None,
              voice_over_placement: dict[str, Any] | None = None) -> dict[str, Any]:
    shots = {str(s.get("shot_id")): s for s in contract.get("shots") or []}
    unit_start = {str(seg.get("unit_id")): float(seg.get("output_start") or 0.0)
                  for seg in timeline.get("segments") or []}
    shot_time, unit_of_shot = shot_start_times(contract, grouping, unit_start)
    lines: list[dict[str, Any]] = []
    undeclared: list[str] = []
    dialogue_units = (contract.get("audio_contract") or {}).get("dialogue_units") or []
    voice_over = _voice_over_rows(contract, voice_over_placement)
    for index, row in enumerate(dialogue_units):
        sid = str(row.get("shot_id") or "")
        if sid not in shot_time:
            continue
        emotion = row.get("emotion")
        if not emotion:
            undeclared.append(sid)
        line = {"time": round(shot_time[sid] + DIALOGUE_LEAD_S, 3), "speaker": row.get("speaker_id"),
                "emotion": emotion, "scene": (shots.get(sid) or {}).get("scene_id"), "shot_id": sid,
                "unit_id": unit_of_shot.get(sid)}
        placed = voice_over.get(index)
        if placed is not None:
            # V.O. narration: mixed in at S7 from the S4 wav, timed by the placement, not by unit ASR
            line.update({"time": round(float(placed["start"]), 3), "end": round(float(placed["end"]), 3),
                         "presence": "VOICE_OVER", "time_source": "VOICE_OVER_PLACEMENT"})
        lines.append(line)
    action_windows: list[list[float]] = []
    for beat in (manifest or {}).get("structure") or []:
        if str(beat.get("type") or "") != "action":
            continue
        ids = [str(x) for x in beat.get("shot_ids") or []]
        times = [shot_time[s] for s in ids if s in shot_time]
        if times:
            end = max(shot_time[s] + float((shots.get(s) or {}).get("target_seconds") or 0.0) for s in ids if s in shot_time)
            action_windows.append([round(min(times), 3), round(end, 3)])
    return {"schema": "qingshan.final_cut_speaker_map.v1", "episode": contract.get("episode"),
            "dialogue_lead_seconds": DIALOGUE_LEAD_S, "lines": lines, "action_windows": action_windows,
            "undeclared_emotion": undeclared}


def align_with_unit_asr(result: dict[str, Any], unit_asr: dict[str, Any], contract: dict[str, Any],
                        grouping: dict[str, Any], timeline: dict[str, Any], *, slack_s: float = 0.25) -> dict[str, Any]:
    """Timing from the per-unit ASR, attribution from the contract (seq=19 C1/C2, 2026-09-16 23:30Z).

    Whole-file ASR of a levelled final cut merges speech, wind and music into windows of 10-20 s, so
    F0 / window-LUFS measured on them describe the mix, not the line (E04 v2: 351 Hz "for" a
    173-234 Hz voice).  The pipeline already transcribes every unit clip on its own
    (<EP>_unit_asr.json: {unit_id: [{start, end, text}]}); those windows are offset onto the release
    timeline here and each one is attributed to the contract line whose shot span contains it
    (single-line units: all windows).  ``lines[].time`` becomes the first ASR window of that line
    (``time_source`` ASR) or stays the contract estimate (``CONTRACT_EXPECTED``).  ASR text rides along only for the lexicon detector;
    the detector report drops it (``--keep-asr-text`` off).
    """
    shots = {str(s.get("shot_id")): s for s in contract.get("shots") or []}
    unit_start = {str(seg.get("unit_id")): float(seg.get("output_start") or 0.0)
                  for seg in timeline.get("segments") or []}
    by_unit: dict[str, list[dict[str, Any]]] = {}
    voice_over_lines = [line for line in result.get("lines") or [] if line.get("presence") == "VOICE_OVER"]
    for line in result.get("lines") or []:
        if line.get("presence") == "VOICE_OVER":
            continue  # the native unit audio carries no V.O.; never attribute an ASR window to it
        by_unit.setdefault(str(line.get("unit_id")), []).append(line)
    windows: list[dict[str, Any]] = []
    for unit in grouping.get("units") or []:
        uid = str(unit.get("unit_id"))
        if uid not in unit_start:
            continue
        offset = unit_start[uid]
        spans: dict[str, tuple[float, float]] = {}
        cursor = offset
        for sid in unit.get("editorial_shot_ids") or []:
            sid = str(sid)
            sec = float((shots.get(sid) or {}).get("target_seconds") or 0.0)
            spans[sid] = (cursor, cursor + sec)
            cursor += sec
        ulines = by_unit.get(uid, [])
        first_hit: dict[int, float] = {}
        segs = sorted((s for s in (unit_asr.get(uid) or []) if s.get("start") is not None),
                      key=lambda s: float(s["start"]))
        for seg in segs:
            start = offset + float(seg["start"])
            end = offset + float(seg.get("end") or seg["start"])
            line = None
            if len(ulines) == 1:
                line = ulines[0]
            elif ulines:
                inside = [l for l in ulines
                          if spans.get(str(l.get("shot_id")), (start, start))[0] - slack_s <= start
                          < spans.get(str(l.get("shot_id")), (start, start))[1] + slack_s]
                line = inside[0] if inside else min(ulines, key=lambda l: abs(float(l["time"]) - start))
            row: dict[str, Any] = {"start": round(start, 3), "end": round(end, 3), "unit_id": uid}
            if seg.get("text"):
                row["text"] = str(seg["text"])  # lexicon detector input only; the detector report never keeps text
            if line is not None:
                row["speaker"] = line.get("speaker")
                if line.get("emotion"):
                    row["emotion"] = line["emotion"]
                if line.get("scene"):
                    row["scene"] = line["scene"]
                row["shot_id"] = line.get("shot_id")
                first_hit.setdefault(id(line), start)
            windows.append(row)
        for line in ulines:
            if id(line) in first_hit:
                line["time_contract_expected"] = line["time"]
                line["time"] = round(first_hit[id(line)], 3)
                line["time_source"] = "ASR"
            else:
                line["time_source"] = "CONTRACT_EXPECTED"
    for line in voice_over_lines:
        # the mixed-in narration is real speech in the final cut: detectors and line levelling see it
        row = {"start": line["time"], "end": line["end"], "unit_id": line.get("unit_id"),
               "speaker": line.get("speaker"), "shot_id": line.get("shot_id"), "presence": "VOICE_OVER"}
        if line.get("emotion"):
            row["emotion"] = line["emotion"]
        if line.get("scene"):
            row["scene"] = line["scene"]
        windows.append(row)
    if voice_over_lines:
        windows.sort(key=lambda w: float(w["start"]))
    result["asr_windows"] = windows
    result["speaker_map_time_source"] = "UNIT_ASR"
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--grouping", type=Path, required=True)
    ap.add_argument("--timeline", type=Path, required=True)
    ap.add_argument("--manifest", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--action-windows-out", type=Path)
    ap.add_argument("--unit-asr", type=Path, help="<EP>_unit_asr.json: per-unit ASR windows (timing source)")
    ap.add_argument("--asr-windows-out", type=Path, help="write the attributed release-timeline ASR windows for the detectors")
    ap.add_argument("--voice-over-placement", type=Path,
                    help="<EP>_voice_over_placement.json (S7): V.O. rows take these times, presence VOICE_OVER")
    args = ap.parse_args()
    contract = read_json(args.contract, {}) or {}
    grouping = read_json(args.grouping, {}) or {}
    timeline = read_json(args.timeline, {}) or {}
    placement = (read_json(args.voice_over_placement, {}) or {}) if args.voice_over_placement else None
    result = build_map(contract, grouping, timeline, read_json(args.manifest, {}) if args.manifest else None,
                       voice_over_placement=placement)
    if args.unit_asr and args.unit_asr.is_file():
        result = align_with_unit_asr(result, read_json(args.unit_asr, {}) or {}, contract, grouping, timeline)
        if args.asr_windows_out:
            args.asr_windows_out.parent.mkdir(parents=True, exist_ok=True)
            args.asr_windows_out.write_text(json.dumps(result["asr_windows"], ensure_ascii=False, indent=1), encoding="utf-8")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.action_windows_out:
        args.action_windows_out.write_text(json.dumps(result["action_windows"]), encoding="utf-8")
    print(json.dumps({"lines": len(result["lines"]), "action_windows": len(result["action_windows"]),
                      "undeclared_emotion": len(result["undeclared_emotion"]),
                      "asr_windows": len(result.get("asr_windows") or []),
                      "time_source": result.get("speaker_map_time_source", "CONTRACT_EXPECTED")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
