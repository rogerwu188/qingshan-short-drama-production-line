#!/usr/bin/env python3
"""Build E21 V11 by repairing DIA-007 truncation and trimming proven silent tails."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e21_agentcut_project_v10_existing_candidate_reuse_20260719.json"
QA = ROOT / "qa/e21_agentcut_v10_existing_candidate_reuse_20260719/E21_FINAL_SENTENCE_COMPLETENESS_V10.json"
OUT_PROJECT = ROOT / "configs/e21_agentcut_project_v11_sentence_and_runtime_repair_20260719.json"
OUT_TIMELINE = ROOT / "qa/e21_agentcut_v11_sentence_and_runtime_repair_20260719/E21_FINAL_TIMELINE_SHOTS_V11.json"
OUT_RECEIPT = ROOT / "workflow/tasks/E21_AGENTCUT_V11_SENTENCE_AND_RUNTIME_REPAIR_20260719.json"
OUT_VIDEO = ROOT / "exports/e21/agentcut_v11_sentence_and_runtime_repair_20260719/E21_AGENTCUT_V11_SENTENCE_AND_RUNTIME_REPAIR_NOT_FINAL.mp4"

# DIA-007 needs its final spoken syllables admitted. The other changes remove
# only ASR-proven post-speech tails while retaining generous visual hold time.
DURATION_DELTAS = {
    "DIA-007": 1.0,
    "DIA-021": -2.0,
    "DIA-020": -1.0,
    "DIA-019": -0.5,
    "DIA-006": -0.5,
}


def dialogue_id(clip: dict) -> str | None:
    return clip.get("metadata", {}).get("dialogue_id") or clip.get("dialogue_id")


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    qa = json.loads(QA.read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in qa["sentences"]}
    if qa.get("failures") != ["DIA-007"]:
        raise SystemExit(f"Expected isolated DIA-007 failure, got {qa.get('failures')}")

    video_clips = project["timeline"]["videoTracks"][0]["clips"]
    original = {dialogue_id(clip): (float(clip["start"]), float(clip["duration"])) for clip in video_clips}
    missing = sorted(set(DURATION_DELTAS) - set(original))
    if missing:
        raise SystemExit(f"Missing timeline clips: {missing}")

    # Prove every trim remains safely after the final recognized speech.
    for dia_id, delta in DURATION_DELTAS.items():
        if delta >= 0:
            continue
        _, old_duration = original[dia_id]
        new_duration = old_duration + delta
        last_speech_end = max(float(segment["end"]) for segment in by_id[dia_id]["segments"])
        if new_duration - last_speech_end < 0.9:
            raise SystemExit(f"Unsafe tail trim for {dia_id}: {new_duration=} {last_speech_end=}")

    boundaries = sorted(
        (start + duration, dia_id, DURATION_DELTAS[dia_id])
        for dia_id, (start, duration) in original.items()
        if dia_id in DURATION_DELTAS
    )

    for track_group in ("videoTracks", "audioTracks", "subtitleTracks"):
        for track in project["timeline"].get(track_group, []):
            for clip in track.get("clips", []):
                dia_id = dialogue_id(clip)
                old_start = float(clip["start"])
                prior_shift = sum(delta for boundary, _, delta in boundaries if boundary <= old_start + 0.001)
                clip["start"] = round(old_start + prior_shift, 6)
                if dia_id in DURATION_DELTAS:
                    new_duration = round(float(clip["duration"]) + DURATION_DELTAS[dia_id], 6)
                    if new_duration <= 0:
                        raise SystemExit(f"Non-positive duration for {dia_id} on {track_group}")
                    clip["duration"] = new_duration
                    clip.setdefault("metadata", {})["v11_duration_delta_seconds"] = DURATION_DELTAS[dia_id]

    total_delta = round(sum(DURATION_DELTAS.values()), 6)
    project["metadata"].update(
        {
            "status": "V11_SENTENCE_AND_RUNTIME_REPAIR_NOT_FINAL",
            "version": "E21_AGENTCUT_V11_SENTENCE_AND_RUNTIME_REPAIR",
            "source_project": str(BASE.relative_to(ROOT)),
            "change_scope": "Extend only DIA-007 to sentence end and remove ASR-proven post-speech tails from four clips to satisfy runtime",
            "duration_deltas_seconds": DURATION_DELTAS,
            "net_runtime_delta_seconds": total_delta,
            "source_qa_evidence": str(QA.relative_to(ROOT)),
            "rollback": str(BASE.relative_to(ROOT)),
        }
    )
    project["output"]["path"] = str(OUT_VIDEO)
    OUT_PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    final_video_clips = project["timeline"]["videoTracks"][0]["clips"]
    OUT_TIMELINE.parent.mkdir(parents=True, exist_ok=True)
    OUT_TIMELINE.write_text(
        json.dumps(
            {
                "schema": "qingshan.final_timeline_shots.v1",
                "episode": "E21",
                "version": "V11",
                "shots": [
                    {
                        "shot_id": clip["id"],
                        "scene_id": clip.get("metadata", {}).get("scene_id"),
                        "start": clip["start"],
                        "end": round(float(clip["start"]) + float(clip["duration"]), 6),
                    }
                    for clip in final_video_clips
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    OUT_RECEIPT.write_text(
        json.dumps(
            {
                "schema": "qingshan.production.task.v1",
                "task_id": "E21_AGENTCUT_V11_SENTENCE_AND_RUNTIME_REPAIR_20260719",
                "episode": "E21",
                "status": "PROJECT_BUILT_PENDING_RENDER",
                "project": str(OUT_PROJECT),
                "output": str(OUT_VIDEO),
                "duration_deltas_seconds": DURATION_DELTAS,
                "net_runtime_delta_seconds": total_delta,
                "source_qa": str(QA),
                "source_project_sha256": hashlib.sha256(BASE.read_bytes()).hexdigest(),
                "rollback": str(BASE),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"status": "PASS", "project": str(OUT_PROJECT), "output": str(OUT_VIDEO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
