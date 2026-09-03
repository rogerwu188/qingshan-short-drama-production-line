#!/usr/bin/env python3
"""Fail closed on mechanical time, weather, and scene repetition across episodes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


REQUIRED_SCENE_FIELDS = (
    "scene_id",
    "location",
    "time_of_day",
    "weather",
    "interior_exterior",
    "palette_temperature",
)


def _signature(scene: dict[str, Any]) -> tuple[str, str, str]:
    return tuple(str(scene.get(key) or "").strip().lower() for key in ("location", "time_of_day", "weather"))


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    failures: list[str] = []
    episodes = payload.get("episodes")
    if not isinstance(episodes, list) or len(episodes) < 2:
        failures.append("at_least_two_adjacent_episode_scene_states_required")
        episodes = []

    normalized = []
    for index, episode in enumerate(episodes, start=1):
        episode_id = str(episode.get("episode") or f"EP_{index}")
        scenes = episode.get("scenes") or episode.get("scene_state") or []
        if not isinstance(scenes, list) or not scenes:
            failures.append(f"{episode_id}:scene_state_missing")
            scenes = []
        for scene_index, scene in enumerate(scenes, start=1):
            missing = [field for field in REQUIRED_SCENE_FIELDS if not str(scene.get(field) or "").strip()]
            if missing:
                failures.append(f"{episode_id}:scene_{scene_index}:missing:{','.join(missing)}")
        normalized.append({"episode": episode_id, "scenes": scenes})

    for left, right in zip(normalized, normalized[1:]):
        left_signatures = {_signature(scene) for scene in left["scenes"]}
        for scene in right["scenes"]:
            if _signature(scene) not in left_signatures:
                continue
            if not str(scene.get("continuity_reason") or "").strip():
                failures.append(
                    f"adjacent_episode_scene_time_weather_repeat:{left['episode']}->{right['episode']}:{'|'.join(_signature(scene))}"
                )

    if len(normalized) >= 3:
        window = normalized[-3:]
        times = {str(scene.get("time_of_day") or "").lower() for ep in window for scene in ep["scenes"]}
        weather = {str(scene.get("weather") or "").lower() for ep in window for scene in ep["scenes"]}
        spaces = {str(scene.get("interior_exterior") or "").lower() for ep in window for scene in ep["scenes"]}
        palettes = {str(scene.get("palette_temperature") or "").lower() for ep in window for scene in ep["scenes"]}
        if len(times) < 2:
            failures.append("three_episode_window_lacks_time_diversity")
        if len(weather) < 2:
            failures.append("three_episode_window_lacks_weather_diversity")
        if not ({"interior", "exterior"} <= spaces):
            failures.append("three_episode_window_lacks_interior_exterior_alternation")
        if not ({"warm", "cool"} <= palettes):
            failures.append("three_episode_window_lacks_warm_cool_alternation")
        all_rain = all(
            str(scene.get("weather") or "").lower() == "rain"
            for ep in window
            for scene in ep["scenes"]
        )
        if all_rain:
            failures.append("rain_used_as_three_episode_default_background")

    return {
        "schema": "qingshan.script_scene_diversity_gate.v1",
        "status": "PASS" if not failures else "FAIL",
        "fail_closed": True,
        "episode_count": len(normalized),
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scene-history", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.scene_history.read_text(encoding="utf-8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
