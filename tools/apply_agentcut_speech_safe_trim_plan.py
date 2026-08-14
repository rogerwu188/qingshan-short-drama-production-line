#!/usr/bin/env python3
"""Apply an ASR-proven speech-safe ripple trim plan to an AgentCut project."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def rounded(value: float) -> float:
    return round(value, 3)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--trim-plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--output-video", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    project = load(args.project.resolve())
    plan = load(args.trim_plan.resolve())
    if plan.get("status") != "PASS":
        raise RuntimeError("Trim plan must be PASS before it can be applied")

    audit = project.get("qingshanAudit", {})
    dialogue_order = audit.get("dialogue_order", [])
    plan_items = {item["dialogue_id"]: item for item in plan.get("items", [])}
    if not dialogue_order or set(dialogue_order) != set(plan_items):
        raise RuntimeError("Project dialogue_order and trim-plan items must match exactly")

    audio_tracks = project.get("timeline", {}).get("audioTracks", [])
    dialogue_track_index = next(
        (index for index, track in enumerate(audio_tracks) if track.get("id") == "ordered_dialogue"),
        None,
    )
    dialogue_track = audio_tracks[dialogue_track_index] if dialogue_track_index is not None else None
    if dialogue_track is None or len(dialogue_track.get("clips", [])) != len(dialogue_order):
        raise RuntimeError("ordered_dialogue track must contain one clip per dialogue_order item")

    trim_by_id = {
        dialogue_id: float(item.get("source_head_trim_seconds", 0.0))
        if item.get("eligible")
        else 0.0
        for dialogue_id, item in plan_items.items()
    }
    picture_tail_pad_seconds = 0.02
    old_start_by_id = {
        dialogue_id: float(clip.get("start", 0.0))
        for dialogue_id, clip in zip(dialogue_order, dialogue_track["clips"])
    }

    def trim_before(time_seconds: float) -> float:
        return sum(
            trim_by_id[dialogue_id]
            for dialogue_id in dialogue_order
            if old_start_by_id[dialogue_id] < time_seconds - 1e-6
        )

    transformed = copy.deepcopy(project)
    changes: list[dict] = []

    for index, (dialogue_id, clip) in enumerate(
        zip(
            dialogue_order,
            transformed["timeline"]["audioTracks"][dialogue_track_index]["clips"],
        )
    ):
        old_start = old_start_by_id[dialogue_id]
        head_trim = trim_by_id[dialogue_id]
        if head_trim >= float(clip["duration"]):
            raise RuntimeError(f"Trim consumes the complete clip: {dialogue_id}")
        clip["id"] = f"audio-{index + 1:02d}-{dialogue_id}"
        clip["metadata"] = {
            **clip.get("metadata", {}),
            "dialogue_id": dialogue_id,
            "beat_id": plan_items[dialogue_id]["beat_id"],
            "speech_safe_head_trim_seconds": head_trim,
        }
        clip["start"] = rounded(old_start - trim_before(old_start))
        clip["in"] = rounded(float(clip.get("in", 0.0)) + head_trim)
        clip["duration"] = rounded(float(clip["duration"]) - head_trim)
        if head_trim:
            changes.append(
                {
                    "clip_id": clip["id"],
                    "dialogue_id": dialogue_id,
                    "track": "ordered_dialogue",
                    "head_trim_seconds": head_trim,
                    "old_start": old_start,
                    "new_start": clip["start"],
                }
            )

    for track in transformed.get("timeline", {}).get("videoTracks", []):
        for index, clip in enumerate(track.get("clips", []), start=1):
            old_start = float(clip.get("start", 0.0))
            dialogue_id = next(
                (item for item in sorted(dialogue_order, key=len, reverse=True) if item in Path(clip["source"]).name),
                None,
            )
            head_trim = trim_by_id.get(dialogue_id, 0.0)
            picture_head_trim = rounded(max(0.0, head_trim - picture_tail_pad_seconds))
            clip["id"] = clip.get("id") or f"video-{track.get('id', 'track')}-{index:02d}"
            clip["metadata"] = {
                **clip.get("metadata", {}),
                **({"dialogue_id": dialogue_id} if dialogue_id else {}),
                **({"beat_id": plan_items[dialogue_id]["beat_id"]} if dialogue_id else {}),
            }
            clip["start"] = rounded(old_start - trim_before(old_start))
            if picture_head_trim:
                if picture_head_trim >= float(clip["duration"]):
                    raise RuntimeError(f"Trim consumes the complete picture clip: {dialogue_id}")
                clip["in"] = rounded(float(clip.get("in", 0.0)) + picture_head_trim)
                clip["duration"] = rounded(float(clip["duration"]) - picture_head_trim)
                clip["metadata"]["speech_safe_head_trim_seconds"] = picture_head_trim
                clip["metadata"]["tail_coverage_pad_seconds"] = picture_tail_pad_seconds
                changes.append(
                    {
                        "clip_id": clip["id"],
                        "dialogue_id": dialogue_id,
                        "track": track.get("id"),
                        "head_trim_seconds": picture_head_trim,
                        "old_start": old_start,
                        "new_start": clip["start"],
                    }
                )

    new_audit = transformed.setdefault("qingshanAudit", {})
    for window in new_audit.get("beat_windows", []):
        old_start = float(window["start_seconds"])
        old_end = float(window["end_seconds"])
        window["start_seconds"] = rounded(old_start - trim_before(old_start))
        window["end_seconds"] = rounded(old_end - trim_before(old_end))
        window["actual_seconds"] = rounded(window["end_seconds"] - window["start_seconds"])

    projected_runtime = float(plan["projected_runtime_seconds"])
    new_audit.update(
        {
            "status": "AGENTCUT_TRIAL_V4_SPEECH_SAFE_NOT_FINAL",
            "source_project_ref": str(args.project.resolve()),
            "speech_safe_trim_plan_ref": str(args.trim_plan.resolve()),
            "compiled_runtime_seconds": projected_runtime,
            "trimmed_dialogue_count": int(plan["trimmed_dialogue_count"]),
            "total_trim_seconds": float(plan["total_trim_seconds"]),
            "picture_tail_coverage_pad_seconds": picture_tail_pad_seconds,
            "final_lock": False,
            "package_allowed": False,
            "platform_mutation_allowed": False,
        }
    )
    transformed["output"]["path"] = str(args.output_video.resolve())

    summary = {
        "status": "DRY_RUN_PASS" if args.dry_run else "READY_FOR_AGENTCUT_VALIDATE_NOT_FINAL",
        "source_project": str(args.project.resolve()),
        "trim_plan": str(args.trim_plan.resolve()),
        "output_project": str(args.out.resolve()),
        "output_video": str(args.output_video.resolve()),
        "runtime_seconds": projected_runtime,
        "total_trim_seconds": float(plan["total_trim_seconds"]),
        "trimmed_dialogue_count": int(plan["trimmed_dialogue_count"]),
        "changed_clip_count": len(changes),
        "changes": changes,
        "rollback": str(args.project.resolve()),
    }
    if not args.dry_run:
        args.out.resolve().parent.mkdir(parents=True, exist_ok=True)
        args.out.resolve().write_text(
            json.dumps(transformed, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
