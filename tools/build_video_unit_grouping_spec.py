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
    for index, group in enumerate(groups, start=1):
        duration = round(sum(float(shot["duration_seconds"]) for shot in group), 6)
        row = {
            "unit_id": f"{episode}-VU-{index:03d}",
            "editorial_shot_ids": [shot["shot_id"] for shot in group],
            "action_unit": any((shot.get("prompt_spec") or {}).get("action") for shot in group),
            "narrative_beat": narrative_beat(group),
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
