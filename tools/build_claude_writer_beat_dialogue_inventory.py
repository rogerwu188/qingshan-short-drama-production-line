#!/usr/bin/env python3
"""Extract Claude Writer visual beats and exact native-dialogue ownership."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


SCENE_RE = re.compile(r"^\*\*(\d+-\d+)\s*[．。.]\s*(.+?)\*\*(?:\s*.*)?$")
DIALOGUE_RE = re.compile(r"^([^△◇〔>\-#][^：]{0,20})：(?:（([^）]*)）)?(.*)$")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse(script: Path, manifest: dict) -> dict:
    episode = str(manifest["episode"])
    scenes: list[dict] = []
    current_scene: dict | None = None
    current_beat: dict | None = None
    dialogue_count = 0
    for raw in script.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        match = SCENE_RE.match(line)
        if match:
            current_scene = {
                "scene_number": match.group(1),
                "heading": match.group(2),
                "target_seconds": int(manifest["scene_breakdown_seconds"][match.group(1)]),
                "beats": [],
            }
            scenes.append(current_scene)
            current_beat = None
            continue
        # Claude Writer scripts append production notes and audits after the
        # screenplay. Never let full-width colons in those sections leak into
        # the final scene's dialogue inventory.
        if scenes and line.startswith("## "):
            current_scene = None
            current_beat = None
            continue
        if current_scene is None:
            continue
        if line.startswith("△") or line.startswith("—"):
            beat_id = f"{episode}-CW-S{len(scenes):02d}-B{len(current_scene['beats']) + 1:02d}"
            current_beat = {
                "beat_id": beat_id,
                "source_text": line,
                "dialogue": [],
                "motion_beats": [],
                "motion_gate": "REQUIRES_AUTHORED_SUBJECT_ACTION_CONTACT_DIRECTION_END_STATE",
            }
            current_scene["beats"].append(current_beat)
            continue
        dialogue_match = DIALOGUE_RE.match(line)
        if dialogue_match and current_beat is not None:
            speaker = dialogue_match.group(1).strip()
            spoken_text = dialogue_match.group(3).strip()
            if speaker and spoken_text and speaker != "人物":
                dialogue_count += 1
                current_beat["dialogue"].append({
                    "dia_id": f"{episode}-DIA-{dialogue_count:03d}",
                    "speaker": speaker,
                    "performance": (dialogue_match.group(2) or "自然表演").strip(),
                    "spoken_text": spoken_text,
                    "generation_policy": "VIDEO_MODEL_NATIVE_MANDARIN_LIP_SYNC",
                })
    if len(scenes) != int(manifest["scenes"]):
        raise RuntimeError(f"scene count mismatch: {len(scenes)} != {manifest['scenes']}")
    visual_beat_count = sum(len(scene["beats"]) for scene in scenes)
    if not visual_beat_count or not dialogue_count:
        raise RuntimeError("script extraction produced no visual beats or dialogue")
    return {
        "schema": "qingshan.claude_writer_beat_dialogue_inventory.v1",
        "episode": episode,
        "title": manifest["title"],
        "status": "READY_FOR_AUTHORED_SHOT_TREATMENT",
        "source_script": str(script),
        "source_script_sha256": sha256(script),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "scene_count": len(scenes),
        "visual_beat_count": visual_beat_count,
        "dialogue_line_count": dialogue_count,
        "native_dialogue_required": True,
        "post_dubbing_forbidden_as_primary_dialogue": True,
        "duration_policy": "AUTHOR_ACTUAL_SECONDS_PER_CONTIGUOUS_BEAT_THEN_GROUP_NATURALLY",
        "motion_policy": "EVERY_SEGMENT_REQUIRES_SUBJECT_ACTION_CONTACT_POINT_DIRECTION_END_STATE",
        "scenes": scenes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    script = Path(args.script).resolve()
    manifest_path = Path(args.manifest).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if sha256(script) != manifest["sha256"]:
        raise SystemExit("Claude Writer script SHA does not match manifest")
    result = parse(script, manifest)
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "episode": result["episode"],
        "scenes": result["scene_count"],
        "visual_beats": result["visual_beat_count"],
        "dialogue_lines": result["dialogue_line_count"],
        "out": str(out),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
