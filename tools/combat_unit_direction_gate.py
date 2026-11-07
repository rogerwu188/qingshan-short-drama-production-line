#!/usr/bin/env python3
"""COMBAT_UNIT_DIRECTION_V1 — paid-boundary gate for fight units (Roger 2026-11-06, E15 成片审看).

E15 shipped a 70 s fight in which no weapon ever visibly met another: every fight unit was a tripod
medium close-up that also carried a spoken tactical line, the writer's authored camera moves had been
replaced by K148's dialogue lock, two-shots were composed with both fighters facing the lens, and the
renderer told each 1.5–2.5 s exchange to "settle and hold".  Each of those passed every existing gate.

Rules (BLOCK, per video unit in a transaction manifest):
  CU1 COMBAT_UNIT_CAMERA_LOCKED          a combat unit is rendered on a locked / tripod camera
  CU2 COMBAT_UNIT_CARRIES_DIALOGUE       a combat unit carries an on-screen spoken line (lines go to their
                                         own units, before/after the exchange, or to V.O.)
  CU3 COMBAT_UNIT_PROMPT_HOLD_LANGUAGE   a combat beat in the rendered prompt tells the model to hold/settle
  CU4 FIGHT_SCENE_NARRATED               in a scene that contains combat, combat units are < 50 % of the
                                         scene's seconds: the fight is told in lines instead of shown
  CU5 FIGHT_TWO_SHOT_FACING_CAMERA       a fight-scene unit composes the fighters with their faces turned to
                                         the lens (they read as posing side by side, not as opponents)
  CU0 COMBAT_CLASSIFICATION_MISSING      a manifest that may post to a provider carries a task with no combat
                                         classification at all; the gate fails closed instead of passing a
                                         fight it cannot see (E15 2026-11-07 staged manifest: 8 tasks without
                                         combat_or_chase / camera_plan / dialogue_lines passed vacuously)

Never retroactive: active for episodes >= configs/COMBAT_UNIT_DIRECTION_V1.json enabled_from_episode, or
when the manifest declares combat_unit_direction_policy=COMBAT_UNIT_DIRECTION_V1.
exit 0 PASS / NOT_ACTIVE, 3 BLOCK, 2 unreadable.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

POLICY_ID = "COMBAT_UNIT_DIRECTION_V1"
POLICY_PATH = Path(__file__).resolve().parents[1] / "configs" / f"{POLICY_ID}.json"
LOCKED_FAMILIES = {"", "LOCKED", "STATIC"}
MIN_FIGHT_SCENE_COMBAT_SHARE = 0.5
HOLD_LANGUAGE = re.compile(
    r"\b(?:then holds?\b|finish(?:es)? last and hold|settles? and holds?|plays through and settles)",
    re.IGNORECASE)
#: a rendered beat line "[0s-1.5s] Start from ..."; a combat beat is one that carries the authored
#: attack/defence chain ("Force origin:") or a timed contact ("interaction point is reached at")
BEAT_LINE = re.compile(r"^\[\d+(?:\.\d+)?s-\d+(?:\.\d+)?s\].*$", re.MULTILINE)
COMBAT_BEAT_MARKERS = ("Force origin:", "interaction point is reached at")


def combat_beat_hold_phrases(prompt: str) -> list[str]:
    hits: set[str] = set()
    for beat in BEAT_LINE.findall(prompt):
        if any(marker in beat for marker in COMBAT_BEAT_MARKERS):
            hits.update(m.group(0) for m in HOLD_LANGUAGE.finditer(beat))
    return sorted(hits)
FACES_TO_CAMERA = re.compile(r"(都转向镜头|脸都转向镜头|都朝向镜头|脸都朝镜头|都面向镜头|都面朝镜头)")


def _episode_number(value: Any) -> int | None:
    match = re.match(r"E(\d+)", str(value or "").strip().upper())
    return int(match.group(1)) if match else None


def active(manifest: dict[str, Any]) -> bool:
    if str(manifest.get("combat_unit_direction_policy") or "").strip().upper() == POLICY_ID:
        return True
    try:
        config = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    start = _episode_number(config.get("enabled_from_episode"))
    episode = _episode_number(manifest.get("episode"))
    return start is not None and episode is not None and episode >= start


def is_combat_task(task: dict[str, Any]) -> bool:
    if task.get("combat_or_chase") is True or task.get("fight_or_chase") is True:
        return True
    return str(task.get("action_classification") or "").upper() == "COMBAT"


def _dialogue_lines(task: dict[str, Any]) -> list[str]:
    lines = task.get("dialogue_lines")
    if isinstance(lines, list):
        return [str(line).strip() for line in lines if str(line).strip()]
    return [str(row.get("spoken_text") or "").strip() for row in task.get("dialogue") or []
            if isinstance(row, dict) and str(row.get("spoken_text") or "").strip()]


def _seconds(task: dict[str, Any]) -> float:
    for name in ("authorized_content_seconds", "duration_seconds"):
        try:
            value = float(task.get(name) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value
    return 0.0


def _prompt(task: dict[str, Any], root: Path | None) -> str:
    value = task.get("prompt_file")
    if not value:
        return str(task.get("prompt") or task.get("prompt_text") or "")
    path = Path(str(value)).expanduser()
    if not path.is_absolute() and root is not None:
        path = root / path
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _camera_text(task: dict[str, Any]) -> str:
    plan = task.get("camera_plan") or {}
    return " ".join(str(plan.get(k) or "") for k in ("axis_relation", "start_framing", "end_framing", "lens_intent"))


CLASSIFICATION_FIELDS = ("combat_or_chase", "fight_or_chase", "action_classification")


def _classified(task: dict[str, Any]) -> bool:
    return any(task.get(name) is not None for name in CLASSIFICATION_FIELDS)


def evaluate_manifest(manifest: dict[str, Any], *, root: str | Path | None = None) -> dict[str, Any]:
    root_path = Path(root).resolve() if root is not None else None
    tasks = [t for t in manifest.get("tasks") or [] if isinstance(t, dict)]
    if not active(manifest):
        return {"gate_id": POLICY_ID, "status": "NOT_ACTIVE", "failures": [], "units": []}
    failures: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    scenes: dict[str, dict[str, float]] = {}
    for task in tasks:
        scene = str(task.get("scene_id") or "")
        bucket = scenes.setdefault(scene, {"seconds": 0.0, "combat_seconds": 0.0})
        bucket["seconds"] += _seconds(task)
        if is_combat_task(task):
            bucket["combat_seconds"] += _seconds(task)
    fight_scenes = {scene for scene, b in scenes.items() if b["combat_seconds"] > 0}
    if manifest.get("provider_post_allowed") is True:
        for task in tasks:
            if not _classified(task):
                failures.append({"code": "COMBAT_CLASSIFICATION_MISSING",
                                 "task_key": str(task.get("task_key") or task.get("unit_id") or "UNKNOWN"),
                                 "scene_id": str(task.get("scene_id") or "")})
    for task in tasks:
        key = str(task.get("task_key") or task.get("unit_id") or "UNKNOWN")
        combat = is_combat_task(task)
        scene = str(task.get("scene_id") or "")
        codes: list[str] = []
        if combat:
            family = str((task.get("camera_plan") or {}).get("motion_family") or "").upper()
            if family in LOCKED_FAMILIES:
                codes.append("COMBAT_UNIT_CAMERA_LOCKED")
            if _dialogue_lines(task):
                codes.append("COMBAT_UNIT_CARRIES_DIALOGUE")
            hits = combat_beat_hold_phrases(_prompt(task, root_path))
            if hits:
                codes.append("COMBAT_UNIT_PROMPT_HOLD_LANGUAGE")
        if scene in fight_scenes and FACES_TO_CAMERA.search(_camera_text(task)):
            codes.append("FIGHT_TWO_SHOT_FACING_CAMERA")
        for code in codes:
            failure = {"code": code, "task_key": key, "scene_id": scene}
            if code == "COMBAT_UNIT_PROMPT_HOLD_LANGUAGE":
                failure["phrases"] = hits
            if code == "COMBAT_UNIT_CARRIES_DIALOGUE":
                failure["lines"] = _dialogue_lines(task)
            failures.append(failure)
        rows.append({"task_key": key, "scene_id": scene, "combat": combat, "failures": codes})
    for scene in sorted(fight_scenes):
        b = scenes[scene]
        share = b["combat_seconds"] / b["seconds"] if b["seconds"] else 0.0
        if share < MIN_FIGHT_SCENE_COMBAT_SHARE:
            failures.append({"code": "FIGHT_SCENE_NARRATED", "scene_id": scene,
                             "combat_share": round(share, 3), "minimum": MIN_FIGHT_SCENE_COMBAT_SHARE})
    return {
        "gate_id": POLICY_ID,
        "status": "PASS" if not failures else "BLOCK",
        "authority": "Roger 2026-11-06 E15 成片审看：打斗像静态 PPT",
        "fight_scenes": {s: {k: round(v, 3) for k, v in scenes[s].items()} for s in sorted(fight_scenes)},
        "failures": failures,
        "units": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"UNREADABLE: {exc}", file=sys.stderr)
        return 2
    report = evaluate_manifest(manifest, root=args.root)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 3 if report["status"] == "BLOCK" else 0


if __name__ == "__main__":
    raise SystemExit(main())
