#!/usr/bin/env python3
"""Build E21 V9 from V8 by fixing only ASR-proven tail truncations and DIA-026 freeze."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e21_agentcut_project_v8_failed_speech_repair_20260719.json"
OUT_PROJECT = ROOT / "configs/e21_agentcut_project_v9_sentence_tail_repair_20260719.json"
OUT_TIMELINE = ROOT / "qa/e21_agentcut_v9_sentence_tail_repair_20260719/E21_FINAL_TIMELINE_SHOTS_V9.json"
OUT_VIDEO = ROOT / "exports/e21/agentcut_v9_sentence_tail_repair_20260719/E21_AGENTCUT_V9_SENTENCE_TAIL_REPAIR_NOT_FINAL.mp4"
TARGET_VIDEO_DURATIONS = {
    "DIA-004": 5.041667,
    "DIA-032": 5.041667,
    "DIA-017": 5.041667,
    "DIA-020": 6.041667,
    "DIA-021": 8.041667,
    "DIA-026": 6.041667,
}
DIA026_SOURCE = ROOT / "working_assets/e21_v5_boundary_video_parallel_20260719/candidates/E21_E21-DIA-026-VIDEO-V5-BOUNDARY_fbb3d1e4-27ac-4bc0-ace6-40caaab4e40b.mp4"
DIA026_SHA256 = "643f2750cfced57d812c3ad27ae94b6a6d7196a934aaf5b0448520bc4e4f15b1"


def dialogue_id(clip: dict) -> str | None:
    direct = clip.get("metadata", {}).get("dialogue_id") or clip.get("dialogue_id")
    if direct:
        return direct
    clip_id = clip.get("id", "")
    for candidate in TARGET_VIDEO_DURATIONS:
        if candidate in clip_id:
            return candidate
    return None


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    video_clips = project["timeline"]["videoTracks"][0]["clips"]
    old_durations = {dialogue_id(clip): float(clip["duration"]) for clip in video_clips}
    deltas = {key: round(value - old_durations[key], 6) for key, value in TARGET_VIDEO_DURATIONS.items()}
    if any(delta <= 0 for delta in deltas.values()):
        raise SystemExit(f"all V9 sentence-tail adjustments must extend coverage: {deltas}")

    for track_group in ("videoTracks", "audioTracks", "subtitleTracks"):
        for track in project["timeline"][track_group]:
            cumulative_shift = 0.0
            adjusted: set[str] = set()
            for clip in track.get("clips", []):
                clip["start"] = round(float(clip["start"]) + cumulative_shift, 6)
                current_id = dialogue_id(clip)
                delta = deltas.get(current_id, 0.0)
                if not delta:
                    continue
                if track_group == "subtitleTracks":
                    clip["duration"] = round(float(clip["duration"]) + delta, 6)
                else:
                    clip["duration"] = TARGET_VIDEO_DURATIONS[current_id]
                metadata = clip.setdefault("metadata", {})
                metadata["v9_tail_extension_seconds"] = delta
                metadata["v9_tail_extension_reason"] = "V8 final ASR proved missing speech or source-range sentence truncation"
                if current_id == "DIA-026" and track_group != "subtitleTracks":
                    clip["source"] = str(DIA026_SOURCE)
                    metadata["source_qa"] = "PASS_EDIT_ADMISSION_V5_COMPLETE_SPEECH_NO_FREEZE"
                    metadata["v9_source_sha256"] = DIA026_SHA256
                    metadata["v9_source_evidence"] = "qa/e21_agentcut_v5_boundary_repair_20260719/E21_FINAL_SENTENCE_COMPLETENESS_V5_ADJUDICATED.json"
                cumulative_shift += delta
                adjusted.add(current_id)
            if adjusted != set(TARGET_VIDEO_DURATIONS):
                raise SystemExit(f"{track_group} did not adjust exactly the V9 set: {sorted(adjusted)}")

    project["metadata"].update(
        {
            "status": "V9_SENTENCE_TAIL_REPAIR_NOT_FINAL",
            "version": "E21_AGENTCUT_V9_SENTENCE_TAIL_REPAIR",
            "source_project": str(BASE.relative_to(ROOT)),
            "change_scope": "Extend only DIA-004/032/017/020/021/026 to complete speech; restore DIA-026 V5 source to remove V8 freeze; ripple later clips",
            "source_failure_evidence": "qa/e21_agentcut_v8_failed_speech_repair_20260719/E21_FINAL_SENTENCE_COMPLETENESS_V8.json",
            "rollback": str(BASE.relative_to(ROOT)),
        }
    )
    project["output"]["path"] = str(OUT_VIDEO)
    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    OUT_TIMELINE.parent.mkdir(parents=True, exist_ok=True)
    OUT_TIMELINE.write_text(
        json.dumps(
            {
                "schema": "qingshan.final_timeline_shots.v1",
                "episode": "E21",
                "version": "V9",
                "shots": [
                    {
                        "shot_id": clip["id"],
                        "scene_id": clip.get("metadata", {}).get("scene_id"),
                        "start": clip["start"],
                        "end": round(float(clip["start"]) + float(clip["duration"]), 6),
                    }
                    for clip in project["timeline"]["videoTracks"][0]["clips"]
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "project": str(OUT_PROJECT), "timeline": str(OUT_TIMELINE), "deltas": deltas, "output": str(OUT_VIDEO)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
