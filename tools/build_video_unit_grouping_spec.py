#!/usr/bin/env python3
"""Build semantic, scene-local video units from an editorial-shot manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def scene_key(shot: dict[str, Any]) -> str:
    if shot.get("scene_id"):
        return str(shot["scene_id"])
    match = re.match(r"E\d+-(S\d+)-", str(shot.get("shot_id") or ""), re.I)
    if match:
        return match.group(1).upper()
    prompt = shot.get("prompt_spec") or {}
    space = prompt.get("space") or {}
    return "|".join(str(value) for value in (space.get("global"), space.get("location")))


def duration_cost(duration: float) -> float:
    if 5 <= duration <= 8:
        return 1.0
    if 3 <= duration < 5:
        return 4.0 + (5 - duration)
    if 8 < duration <= 12:
        return 3.0 + (duration - 8)
    return 1000.0


def partition_scene(shots: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Dynamic programming chooses no target count; duration and continuity determine groups."""
    count = len(shots)
    best: list[tuple[float, list[list[dict[str, Any]]]] | None] = [None] * (count + 1)
    best[0] = (0.0, [])
    for end in range(1, count + 1):
        duration = 0.0
        for start in range(end - 1, -1, -1):
            duration = round(duration + float(shots[start]["duration_seconds"]), 6)
            if duration > 12:
                break
            if best[start] is None:
                continue
            cost = duration_cost(duration)
            if cost >= 1000 and not (start == 0 and end == count):
                continue
            candidate = (best[start][0] + cost, best[start][1] + [shots[start:end]])
            if best[end] is None or candidate[0] < best[end][0]:
                best[end] = candidate
    if best[count] is None:
        raise ValueError(f"scene {scene_key(shots[0])} cannot be partitioned within 3-12 seconds")
    return best[count][1]


def narrative_beat(group: list[dict[str, Any]]) -> str:
    beats: list[str] = []
    for shot in group:
        prompt = shot.get("prompt_spec") or {}
        action = prompt.get("action") or {}
        value = action.get("primary_action") or prompt.get("dialogue") or shot.get("shot_id")
        if value and str(value) not in beats:
            beats.append(str(value).strip())
    return " → ".join(beats)


def derive_camera_plan(
    group: list[dict[str, Any]], *, unit_index: int, previous_dynamic_direction: str | None
) -> tuple[dict[str, str], str | None]:
    """Create a conservative, motivated camera plan from editorial semantics.

    Dialogue and small prop interactions default to a locked composition.  A
    moving camera is admitted only when the authored action contains physical
    travel or a reveal, and its direction alternates against the previous
    dynamic unit.  A human-authored ``camera_plan`` on the first shot remains
    authoritative and is validated downstream.
    """
    explicit = (group[0].get("prompt_spec") or {}).get("camera_plan")
    if explicit:
        direction = str(explicit.get("motion_direction") or "")
        return dict(explicit), direction if direction != "NONE" else None

    specs = []
    for shot in group:
        prompt_spec = shot.get("prompt_spec")
        if prompt_spec:
            specs.append(prompt_spec)
            continue
        # Writer generation contracts keep performance fields at shot level;
        # normalize them instead of treating the misleading legacy ``camera``
        # action slug as cinematography.
        specs.append({
            "action": {"primary_action": shot.get("frame_content") or ""},
            "dialogue": shot.get("dialogue") or "",
            "cast": shot.get("cast") or [],
            "props": shot.get("props") or [],
        })
    actions = [str((spec.get("action") or {}).get("primary_action") or "") for spec in specs]
    dialogue = [str(spec.get("dialogue") or "").strip() for spec in specs]
    text = " ".join(actions + dialogue).lower()
    cast = {
        str(row.get("character") or "").strip()
        for spec in specs for row in spec.get("cast") or [] if row.get("character")
    }
    props = {
        str(row.get("prop") or "").strip()
        for spec in specs for row in spec.get("props") or [] if row.get("prop")
    }
    travel_terms = ("走", "穿过", "跑", "奔", "追", "离开", "进入", "跨", "行进", "walk", "run", "cross", "enter", "leave")
    reveal_terms = ("揭开", "掀开", "挑开", "打开", "抬头", "显出", "露出", "看见", "reveal", "open", "discover")
    has_dialogue = any(dialogue)
    has_travel = any(term in text for term in travel_terms)
    has_reveal = any(term in text for term in reveal_terms)

    axis = "保持既定人物视线轴，不越轴"
    if has_travel:
        direction = "RIGHT_TO_LEFT" if previous_dynamic_direction == "LEFT_TO_RIGHT" else "LEFT_TO_RIGHT"
        start = "人物进入通道并保留前方空间"
        end = "人物抵达动作终点且行进方向仍清楚"
        return ({
            "shot_scale": "MEDIUM_WIDE",
            "lens_intent": "35mm交代人物与行进空间",
            "camera_height": "EYE_LEVEL",
            "camera_side": "AXIS_A" if unit_index % 2 else "AXIS_B",
            "axis_relation": axis,
            "motion_family": "TRACK",
            "motion_direction": direction,
            "start_framing": start,
            "end_framing": end,
            "motivation": "只为保持人物真实行进及其空间终点连续可读",
            "authorship": "SEMANTIC_MOTIVATED_DERIVATION",
        }, direction)

    if has_reveal:
        direction = "PULL_OUT" if previous_dynamic_direction == "PUSH_IN" else "PUSH_IN"
        return ({
            "shot_scale": "MEDIUM",
            "lens_intent": "50mm以主体反应带出揭示信息",
            "camera_height": "EYE_LEVEL",
            "camera_side": "AXIS_A",
            "axis_relation": axis,
            "motion_family": "DOLLY",
            "motion_direction": direction,
            "start_framing": "主体动作与被遮蔽信息同框",
            "end_framing": "揭示对象清晰进入构图并停稳",
            "motivation": "只在揭示发生时移动一次以呈现新增叙事信息",
            "authorship": "SEMANTIC_MOTIVATED_DERIVATION",
        }, direction)

    if has_dialogue or props:
        framing = "双人腰部与视线关系" if len(cast) > 1 else "人物胸像与手部动作"
        return ({
            "shot_scale": "MEDIUM" if len(cast) > 1 else "MEDIUM_CLOSE_UP",
            "lens_intent": "50mm自然透视",
            "camera_height": "EYE_LEVEL",
            "camera_side": "AXIS_A",
            "axis_relation": axis,
            "motion_family": "LOCKED",
            "motion_direction": "NONE",
            "start_framing": framing,
            "end_framing": framing,
            "motivation": "让对白、眼神和手部表演在稳定构图内自行发生",
            "authorship": "SEMANTIC_SAFE_DEFAULT",
        }, None)

    framing = "人物与主要环境关系"
    return ({
        "shot_scale": "MEDIUM_WIDE" if cast else "WIDE",
        "lens_intent": "40mm自然空间关系",
        "camera_height": "EYE_LEVEL",
        "camera_side": "NEUTRAL" if not cast else "AXIS_A",
        "axis_relation": axis,
        "motion_family": "LOCKED",
        "motion_direction": "NONE",
        "start_framing": framing,
        "end_framing": framing,
        "motivation": "让场面调度和环境变化在稳定构图内自行发生",
        "authorship": "SEMANTIC_SAFE_DEFAULT",
    }, None)


def build(manifest: dict[str, Any], source_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    shots = manifest.get("shots") or []
    if not shots:
        raise ValueError("manifest has no editorial shots")
    groups: list[list[dict[str, Any]]] = []
    start = 0
    while start < len(shots):
        key = scene_key(shots[start])
        end = start + 1
        while end < len(shots) and scene_key(shots[end]) == key:
            end += 1
        groups.extend(partition_scene(shots[start:end]))
        start = end

    episode = str(manifest.get("episode") or "")
    production = {
        "episode": episode,
        "runtime_seconds": round(sum(float(shot["duration_seconds"]) for shot in shots), 6),
        "source": {"script_sha256": source_sha},
        "shots": [
            {"shot_id": shot["shot_id"], "scene_id": scene_key(shot),
             "duration_seconds": shot["duration_seconds"]}
            for shot in shots
        ],
    }
    spec_groups = []
    previous_dynamic_direction: str | None = None
    for index, group in enumerate(groups, start=1):
        duration = round(sum(float(shot["duration_seconds"]) for shot in group), 6)
        camera_plan, new_dynamic_direction = derive_camera_plan(
            group, unit_index=index, previous_dynamic_direction=previous_dynamic_direction
        )
        if new_dynamic_direction:
            previous_dynamic_direction = new_dynamic_direction
        row = {
            "unit_id": f"{episode}-VU-{index:03d}",
            "editorial_shot_ids": [shot["shot_id"] for shot in group],
            "action_unit": any((shot.get("prompt_spec") or {}).get("action") for shot in group),
            "narrative_beat": narrative_beat(group),
            "camera_plan": camera_plan,
        }
        if not 5 <= duration <= 8:
            row["duration_exception_reason"] = (
                "SCENE_LOCAL_REMAINDER" if duration < 5 else "CONTINUOUS_CAUSAL_ACTION"
            )
        spec_groups.append(row)
    spec = {
        "episode": episode,
        "source_script_sha256": source_sha,
        "duration_policy_seconds": {"minimum": 3, "maximum": 12, "authority": "ROGER-20260825"},
        "preferred_duration_seconds": {"minimum": 5, "maximum": 8},
        "groups": spec_groups,
        "transition_authoring_required": [
            {
                "from_unit_id": spec_groups[index - 1]["unit_id"],
                "to_unit_id": spec_groups[index]["unit_id"],
                "status": "BLOCKED_UNTIL_DIRECTOR_OR_EDITOR_AUTHORS_TRANSITION_CONTRACT",
            }
            for index in range(1, len(spec_groups))
        ],
    }
    return production, spec


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--editorial-manifest", required=True)
    parser.add_argument("--production-out", required=True)
    parser.add_argument("--grouping-spec-out", required=True)
    args = parser.parse_args()
    source = Path(args.editorial_manifest)
    source = source if source.is_absolute() else ROOT / source
    manifest = json.loads(source.read_text(encoding="utf-8"))
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    production, spec = build(manifest, source_sha)
    for name, payload in ((args.production_out, production), (args.grouping_spec_out, spec)):
        path = Path(name)
        path = path if path.is_absolute() else ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "editorial_shots": len(production["shots"]),
                      "video_units": len(spec["groups"]), "runtime_seconds": production["runtime_seconds"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
