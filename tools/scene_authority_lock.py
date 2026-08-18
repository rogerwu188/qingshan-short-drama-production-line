#!/usr/bin/env python3
"""Block generation prompts that invent scene facts not declared by the script."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

try:
    from global_space_layout_gate import evaluate_batch as evaluate_global_space_map
except ModuleNotFoundError:
    from tools.global_space_layout_gate import evaluate_batch as evaluate_global_space_map


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SCENE_FIELDS = ("scene_id", "location", "time_of_day", "weather", "event_summary")

TIME_TERMS = {
    "night": ("night", "moon", "moonlight", "moonbeam", "moonbeams"),
    "dawn": ("dawn", "sunrise"),
    "day": ("daylight", "afternoon", "noon", "daytime", "golden sun", "sunlight"),
    "dusk": ("dusk", "sunset", "twilight"),
}
WEATHER_TERMS = {
    "rain": ("rain", "rainy", "downpour", "drizzle"),
    "snow": ("snow", "snowy", "blizzard"),
    "fog": ("fog", "foggy", "mist"),
    "storm": ("storm", "thunder", "lightning"),
    "clear": ("clear sky", "clear weather"),
}


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def abs_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_json(value: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return json.loads(abs_path(value).read_text(encoding="utf-8"))


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _positive_prompt(prompt: str) -> str:
    """Keep affirmative visual instructions and remove explicit negative clauses."""
    visual = prompt.split("NEGATIVE_PROMPT:", 1)[0]
    visual = visual.split("AUDIO_PROMPT", 1)[0]
    # Structured weather contracts use underscore-delimited negation. Remove
    # the negated rain token before lexical weather detection so NO_RAIN is
    # never misread as an affirmative rain instruction.
    visual = re.sub(
        r"\b(?:interior[_-])?clear[_-]no[_-]rain\b|\bno[_-]rain\b",
        "interior clear",
        visual,
        flags=re.IGNORECASE,
    )
    terms = sorted(
        {term for values in (*TIME_TERMS.values(), *WEATHER_TERMS.values()) for term in values},
        key=len,
        reverse=True,
    )
    joined = "|".join(re.escape(term) for term in terms)
    patterns = (
        rf"\b(?:no|without)\s+(?:[a-z-]+\s+){{0,2}}(?:{joined})s?\b",
        r"\bdo\s+not\s+(?:show|include|add|use|invent|introduce)\b[^.;\n]*",
        rf"\bkeep\s+(?:the\s+)?(?:{joined})s?[^.;\n]*(?:outside|out\s+of)\s+(?:the\s+)?frame\b",
    )
    for pattern in patterns:
        visual = re.sub(pattern, " ", visual, flags=re.IGNORECASE)
    return _normalized(visual)


def _categories(text: str, vocabulary: dict[str, tuple[str, ...]]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    padded = f" {text} "
    for category, terms in vocabulary.items():
        hits = [term for term in terms if f" {_normalized(term)} " in padded]
        if hits:
            found[category] = hits
    return found


def _allowed_time_categories(scene: dict[str, Any]) -> set[str]:
    source = _normalized(" ".join([str(scene.get("time_of_day", "")), *scene.get("allowed_time_terms", [])]))
    allowed = set(_categories(source, TIME_TERMS))
    if "deep night" in source or source.endswith("night"):
        allowed.add("night")
    return allowed


def _allowed_weather_categories(scene: dict[str, Any]) -> set[str]:
    source = _normalized(" ".join([str(scene.get("weather", "")), *scene.get("allowed_weather_terms", [])]))
    allowed = set(_categories(source, WEATHER_TERMS))
    # Scene-state commonly stores the canonical category itself (for example
    # `weather: clear`) while prompts use a natural phrase (`clear weather`).
    # Treat exact declared categories as authoritative instead of requiring the
    # scene file to repeat every vocabulary phrase.
    for category in WEATHER_TERMS:
        if category in source.split():
            allowed.add(category)
    return allowed


def evaluate_batch(
    state_bible: str | Path | dict[str, Any],
    batch_config: str | Path | dict[str, Any],
) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    try:
        state = load_json(state_bible)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "gate_id": "SCENE-AUTHORITY-LOCK",
            "status": "FAIL",
            "failures": [{"check": "state_bible_load", "reason": str(exc)}],
            "evidence": [],
            "rollback": "Do not submit generation; restore the last script-approved scene_state.",
            "recorded_at": now(),
        }
    config = load_json(batch_config)
    global_space_map = evaluate_global_space_map(
        config.get("episode_global_space_map_ref"),
        config.get("tasks") or [],
        episode=config.get("episode"),
        required=config.get("global_space_map_gate_required"),
    )
    if global_space_map.get("status") == "FAIL":
        failures.extend(
            {"check": "global_space_map", **row}
            for row in global_space_map.get("failures") or []
        )
    scenes = state.get("scene_state")
    if not isinstance(scenes, list) or not scenes:
        failures.append({"check": "scene_state", "reason": "missing_or_empty"})
        scenes = []
    scene_by_id: dict[str, dict[str, Any]] = {}
    for index, scene in enumerate(scenes):
        missing = [field for field in REQUIRED_SCENE_FIELDS if not scene.get(field)]
        if missing:
            failures.append({"check": "scene_state_required_fields", "index": index, "missing": missing})
            continue
        scene_by_id[scene["scene_id"]] = scene

    previous: dict[str, Any] | None = None
    for index, task in enumerate(config.get("tasks", [])):
        key = task.get("task_key") or f"task-{index + 1}"
        scene_id = task.get("scene_id")
        visual_zone = task.get("visual_zone")
        if not scene_id:
            failures.append({"task_key": key, "check": "scene_id", "reason": "missing"})
            continue
        if not visual_zone:
            failures.append({"task_key": key, "check": "visual_zone", "reason": "missing"})
        scene = scene_by_id.get(scene_id)
        if not scene:
            failures.append({"task_key": key, "check": "scene_id", "reason": "undeclared", "value": scene_id})
            continue
        is_declared_variant = (
            previous
            and previous.get("variant_group")
            and previous.get("variant_group") == task.get("variant_group")
            and previous.get("variant_label")
            and task.get("variant_label")
            and previous.get("variant_label") != task.get("variant_label")
        )
        if previous and previous.get("scene_id") == scene_id and previous.get("visual_zone") == visual_zone and not is_declared_variant:
            failures.append({
                "task_key": key,
                "check": "adjacent_visual_zone",
                "reason": "repeated_in_same_scene",
                "visual_zone": visual_zone,
            })
        previous = task

        prompt_file = task.get("prompt_file")
        if not prompt_file or not abs_path(prompt_file).is_file():
            failures.append({"task_key": key, "check": "prompt_file", "reason": "missing", "value": prompt_file})
            continue
        prompt = abs_path(prompt_file).read_text(encoding="utf-8")
        positive = _positive_prompt(prompt)
        actual_times = _categories(positive, TIME_TERMS)
        actual_weather = _categories(positive, WEATHER_TERMS)
        allowed_times = _allowed_time_categories(scene)
        allowed_weather = _allowed_weather_categories(scene)
        for category, terms in actual_times.items():
            if category not in allowed_times:
                failures.append({
                    "task_key": key,
                    "check": "undeclared_time_term",
                    "category": category,
                    "terms": terms,
                    "scene_time_of_day": scene.get("time_of_day"),
                })
        for category, terms in actual_weather.items():
            if category not in allowed_weather:
                failures.append({
                    "task_key": key,
                    "check": "undeclared_weather_term",
                    "category": category,
                    "terms": terms,
                    "scene_weather": scene.get("weather"),
                })
        location_tokens = [_normalized(item) for item in scene.get("location_prompt_tokens", []) if item]
        if location_tokens and not any(token in positive for token in location_tokens):
            failures.append({
                "task_key": key,
                "check": "location_binding",
                "reason": "no_declared_location_token_in_prompt",
                "expected_any": scene.get("location_prompt_tokens", []),
            })
        evidence.append({
            "task_key": key,
            "scene_id": scene_id,
            "visual_zone": visual_zone,
            "variant_group": task.get("variant_group"),
            "variant_label": task.get("variant_label"),
            "time_of_day": scene.get("time_of_day"),
            "weather": scene.get("weather"),
            "detected_time_categories": sorted(actual_times),
            "detected_weather_categories": sorted(actual_weather),
        })

    return {
        "schema": "qingshan.scene_authority_lock.v1",
        "gate_id": "SCENE-AUTHORITY-LOCK",
        "episode": config.get("episode"),
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "evidence": evidence,
        "global_space_map": global_space_map,
        "confidence": 0.98 if not failures else 0.99,
        "rollback": "No remote submission occurs on FAIL; correct the prompt or restore the last approved scene_state.",
        "recorded_at": now(),
    }


def evaluate_sequence(state_bibles: list[str | Path]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    run: list[dict[str, Any]] = []
    for source in state_bibles:
        state = load_json(source)
        scenes = state.get("scene_state") or []
        if not scenes:
            continue
        first = scenes[0]
        is_night = "night" in _normalized(str(first.get("time_of_day", "")))
        if is_night:
            run.append({
                "episode": state.get("episode"),
                "scene_id": first.get("scene_id"),
                "reason": first.get("time_continuity_reason"),
            })
            if len(run) >= 3 and any(not item.get("reason") for item in run[-3:]):
                failures.append({"check": "three_episode_night_run", "episodes": [item.get("episode") for item in run[-3:]], "reason": "missing_time_continuity_reason"})
        else:
            run = []
    return {"status": "PASS" if not failures else "FAIL", "failures": failures, "recorded_at": now()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-bible", required=True)
    parser.add_argument("--batch-config", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    report = evaluate_batch(args.state_bible, args.batch_config)
    destination = abs_path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
