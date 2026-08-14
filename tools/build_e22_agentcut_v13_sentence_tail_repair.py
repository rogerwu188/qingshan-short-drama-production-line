#!/usr/bin/env python3
"""Build E22 V13 by extending only two V12 clips with ASR-proven tail truncation."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e22_agentcut_project_v12_repeat_repair_20260719.json"
OUT_PROJECT = ROOT / "configs/e22_agentcut_project_v13_sentence_tail_repair_20260719.json"
OUT_TIMELINE = ROOT / "qa/e22_agentcut_v13_sentence_tail_repair_20260719/E22_FINAL_TIMELINE_SHOTS_V13.json"
OUT_VIDEO = ROOT / "exports/e22/agentcut_v13_sentence_tail_repair_20260719/E22_AGENTCUT_V13_SENTENCE_TAIL_REPAIR_NOT_FINAL.mp4"
EXTENSIONS = {"DIA-020": 1.0, "DIA-029": 1.0}


def dialogue_id(clip: dict) -> str | None:
    metadata_id = clip.get("metadata", {}).get("dialogue_id")
    if metadata_id:
        return metadata_id
    direct_id = clip.get("dialogue_id")
    if direct_id:
        return direct_id
    clip_id = clip.get("id", "")
    for candidate in EXTENSIONS:
        if candidate in clip_id:
            return candidate
    return None


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))

    for track_group in ("videoTracks", "audioTracks", "subtitleTracks"):
        for track in project["timeline"][track_group]:
            cumulative_shift = 0.0
            extended: set[str] = set()
            for clip in track.get("clips", []):
                clip["start"] = round(float(clip["start"]) + cumulative_shift, 6)
                current_id = dialogue_id(clip)
                extension = EXTENSIONS.get(current_id, 0.0)
                if extension:
                    clip["duration"] = round(float(clip["duration"]) + extension, 6)
                    clip.setdefault("metadata", {})["v13_tail_extension_seconds"] = extension
                    clip["metadata"]["v13_tail_extension_reason"] = "V12 final ASR proved source-range sentence truncation"
                    cumulative_shift += extension
                    extended.add(current_id)
            if extended != set(EXTENSIONS):
                raise SystemExit(f"{track_group} did not extend exactly {sorted(EXTENSIONS)}: {sorted(extended)}")

    project["metadata"].update(
        {
            "status": "V13_SENTENCE_TAIL_REPAIR_NOT_FINAL",
            "version": "E22_AGENTCUT_V13_SENTENCE_TAIL_REPAIR",
            "source_project": str(BASE.relative_to(ROOT)),
            "change_scope": "Extend DIA-020 and DIA-029 by 1.0s each and ripple all later clips; no source replacement, retime, padding, or new cuts",
            "source_failure_evidence": "qa/e22_agentcut_v12_repeat_repair_20260719/E22_FINAL_SENTENCE_COMPLETENESS_V12.json",
            "rollback": str(BASE.relative_to(ROOT)),
        }
    )
    project["output"]["path"] = str(OUT_VIDEO)
    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    video_clips = project["timeline"]["videoTracks"][0]["clips"]
    OUT_TIMELINE.parent.mkdir(parents=True, exist_ok=True)
    OUT_TIMELINE.write_text(
        json.dumps(
            {
                "schema": "qingshan.final_timeline_shots.v1",
                "episode": "E22",
                "version": "V13",
                "shots": [
                    {
                        "shot_id": clip["id"],
                        "scene_id": clip.get("metadata", {}).get("scene_id"),
                        "start": clip["start"],
                        "end": round(float(clip["start"]) + float(clip["duration"]), 6),
                    }
                    for clip in video_clips
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "project": str(OUT_PROJECT), "timeline": str(OUT_TIMELINE), "output": str(OUT_VIDEO)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
