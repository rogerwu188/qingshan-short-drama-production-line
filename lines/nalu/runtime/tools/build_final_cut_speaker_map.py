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
"""
from __future__ import annotations
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))
import nalu_paths as _np  # noqa: F401

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


def build_map(contract: dict[str, Any], grouping: dict[str, Any], timeline: dict[str, Any],
              manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    shots = {str(s.get("shot_id")): s for s in contract.get("shots") or []}
    unit_start = {str(seg.get("unit_id")): float(seg.get("output_start") or 0.0)
                  for seg in timeline.get("segments") or []}
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
    lines: list[dict[str, Any]] = []
    undeclared: list[str] = []
    dialogue_units = (contract.get("audio_contract") or {}).get("dialogue_units") or []
    for row in dialogue_units:
        sid = str(row.get("shot_id") or "")
        if sid not in shot_time:
            continue
        emotion = row.get("emotion")
        if not emotion:
            undeclared.append(sid)
        lines.append({"time": round(shot_time[sid] + DIALOGUE_LEAD_S, 3), "speaker": row.get("speaker_id"),
                      "emotion": emotion, "scene": (shots.get(sid) or {}).get("scene_id"), "shot_id": sid,
                      "unit_id": unit_of_shot.get(sid)})
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--contract", type=Path, required=True)
    ap.add_argument("--grouping", type=Path, required=True)
    ap.add_argument("--timeline", type=Path, required=True)
    ap.add_argument("--manifest", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--action-windows-out", type=Path)
    args = ap.parse_args()
    result = build_map(read_json(args.contract, {}) or {}, read_json(args.grouping, {}) or {},
                       read_json(args.timeline, {}) or {}, read_json(args.manifest, {}) if args.manifest else None)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.action_windows_out:
        args.action_windows_out.write_text(json.dumps(result["action_windows"]), encoding="utf-8")
    print(json.dumps({"lines": len(result["lines"]), "action_windows": len(result["action_windows"]),
                      "undeclared_emotion": len(result["undeclared_emotion"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
