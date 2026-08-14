#!/usr/bin/env python3
"""Add story-driven duration plans to video tasks in an episode batch config."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from shot_duration_policy import plan_action_duration, plan_dialogue_duration


ROOT = Path(__file__).resolve().parents[1]


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_path = resolve(args.input)
    output_path = resolve(args.output)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    changed = []
    task_groups = []
    for key in ("tasks", "video_tasks"):
        rows = payload.get(key, [])
        if isinstance(rows, list):
            task_groups.extend(rows)
    for task in task_groups:
        model = str(task.get("model") or "").lower()
        is_video = task.get("tool_type") == "video_generation" or (
            ("duration" in task or "duration_seconds" in task)
            and ("seedance" in model or "video" in str(task.get("source_id") or task.get("task_key") or "").lower())
        )
        if not is_video:
            continue
        metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
        text = str(
            task.get("text")
            or task.get("exact_dialogue")
            or metadata.get("exact_dialogue")
            or ""
        ).strip()
        function = str(task.get("narrative_function") or task.get("visual_zone") or task.get("task_key") or "shot action")
        prompt_path = task.get("prompt_file") or task.get("prompt_path")
        prompt = resolve(Path(prompt_path)).read_text(encoding="utf-8") if prompt_path else ""
        if text:
            plan = plan_dialogue_duration(
                text,
                str(task.get("pace") or metadata.get("pace") or "medium"),
                function,
                performance_context=prompt,
            )
        else:
            plan = plan_action_duration(
                prompt,
                function,
                requested_floor=int(task.get("duration") or 4),
            )
        task["duration"] = plan["duration_seconds"]
        if "duration_seconds" in task:
            task["duration_seconds"] = plan["duration_seconds"]
        task["duration_plan"] = plan
        changed.append({"task_key": task.get("task_key"), "duration": task["duration"]})
    payload["shot_duration_policy"] = {
        "version": "qingshan.shot_generation_duration.v2",
        "rule": "Every video task is planned independently from speech, physical performance, listener reaction and dramatic button; batch concurrency does not set duration.",
        "source_config": str(source_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "video_tasks": len(changed), "changed": changed, "output": str(output_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
