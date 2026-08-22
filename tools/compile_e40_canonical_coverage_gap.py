#!/usr/bin/env python3
"""Compile canonical E40 non-dialogue coverage gaps into dispatchable shot work.

This is deliberately conservative: a shot is considered dialogue-bearing only
when a spoken line occurs inside its canonical shot block.  It never converts a
duration deficit into filler, repeated media, or time stretching.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


SCENE_RE = re.compile(r"^\*\*(13-[1-5])．")
SHOT_RE = re.compile(r"^△【([^】]+)】(.*)$")
DURATION_RE = re.compile(r"·(\d+)s(?:·|】)")
DIALOGUE_RE = re.compile(r"^[^△◇〔>\s][^：]{0,20}：（")

# Exact canonical bindings already proved by the production manifests.  These
# are not inferred from filenames; each mapping is the source unit whose
# canonical_script_action matches the canonical shot verbatim.
EXACT_EXISTING_BINDINGS = {
    "E40-13-3-S05": (
        "R05",
        "working_assets/e40_remake_20260821/native_registry_paid_exception_v1/videos/E40-R05-VIDEO-NATIVE-EXCEPTION-V1.mp4",
    ),
    "E40-13-4-S02": (
        "R06A",
        "working_assets/e40_remake_20260821/switch_coverage_wave2_v1/editorial_coverage/E40_R06A_ARROW_CURTAIN_MACRO_SWITCH_COVERAGE_V1.mp4",
    ),
    "E40-13-4-S03": (
        "R06B",
        "working_assets/e40_remake_20260821/native_registry_paid_exception_v1/videos/E40-R06B-VIDEO-NATIVE-EXCEPTION-V1.mp4",
    ),
    "E40-13-4-S04": (
        "R06C",
        "working_assets/e40_remake_20260821/native_registry_paid_exception_v1/videos/E40-R06C-VIDEO-NATIVE-EXCEPTION-V1.mp4",
    ),
    "E40-13-4-S05": (
        "R07",
        "working_assets/e40_remake_20260822/terminal_switch_coverage_v1/E40_R07_THREE_ARROW_EDITORIAL_INSERT_V1.mp4",
    ),
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_shots(script: Path) -> list[dict]:
    scene_id: str | None = None
    scene_index = 0
    shots: list[dict] = []
    current: dict | None = None

    for raw in script.read_text(encoding="utf-8").splitlines():
        scene_match = SCENE_RE.match(raw)
        if scene_match:
            scene_id = scene_match.group(1)
            scene_index = 0
            continue
        shot_match = SHOT_RE.match(raw)
        if shot_match and scene_id:
            scene_index += 1
            duration_match = DURATION_RE.search(shot_match.group(1))
            if not duration_match:
                raise ValueError(f"missing duration in shot heading: {raw}")
            current = {
                "canonical_shot_id": f"E40-{scene_id}-S{scene_index:02d}",
                "scene_id": scene_id,
                "shot_index": scene_index,
                "heading": shot_match.group(1),
                "duration_seconds": int(duration_match.group(1)),
                "canonical_action": shot_match.group(2).strip(),
                "dialogue_lines": [],
            }
            shots.append(current)
            continue
        if current and DIALOGUE_RE.match(raw):
            current["dialogue_lines"].append(raw.strip())

    return shots


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--assembly-qa", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    script = root / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
    assembly_qa_path = root / args.assembly_qa
    assembly_qa = json.loads(assembly_qa_path.read_text(encoding="utf-8"))
    shots = parse_shots(script)
    if len(shots) != 29:
        raise ValueError(f"canonical shot count mismatch: expected 29, got {len(shots)}")

    non_dialogue = [shot for shot in shots if not shot["dialogue_lines"]]
    for shot in non_dialogue:
        binding = EXACT_EXISTING_BINDINGS.get(shot["canonical_shot_id"])
        if binding:
            unit_id, relative_path = binding
            media_path = root / relative_path
            if not media_path.is_file():
                raise FileNotFoundError(media_path)
            shot["existing_binding"] = {
                "source_unit": unit_id,
                "path": relative_path,
                "sha256": sha256(media_path),
            }
            # Native 4.086s clips fully cover 3s action beats. Short editorial
            # inserts remain partial and must not be stretched to nominal time.
            if unit_id in {"R06B", "R06C"}:
                shot["coverage_state"] = "CANONICAL_ACTION_BOUND_COMPLETE"
                shot["paid_submit_allowed"] = False
                shot["required_next_artifact"] = None
            else:
                shot["coverage_state"] = "EXACT_SOURCE_BOUND_PARTIAL_DURATION"
                shot["paid_submit_allowed"] = False
                shot["required_next_artifact"] = "nonduplicative_continuity_coverage"
        else:
            shot["coverage_state"] = "READY_FOR_SOURCE_BINDING"
            shot["paid_submit_allowed"] = False
            shot["required_next_artifact"] = "exact_sha_q1_admitted_source_binding"
        shot["audio_policy"] = (
            "PRESERVE_SAME_TASK_NATIVE_AUDIO_IF_PROVIDER_VIDEO; "
            "NO_EXTERNAL_TTS_FOR_VISIBLE_LIPS; BGM_ONLY_FOR_NAMED_CUE"
        )

    nominal_gap = sum(shot["duration_seconds"] for shot in non_dialogue)
    measured_gap = float(
        assembly_qa["registered_content_gate"]["missing_duration_seconds"]
    )
    payload = {
        "schema": "qingshan.e40.canonical_coverage_gap.v1",
        "episode": "E40",
        "compiled_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "canonical": {
            "script_path": str(script.relative_to(root)),
            "script_sha256": sha256(script),
            "shot_count": len(shots),
            "target_seconds": 163,
        },
        "source_assembly_qa": {
            "path": str(assembly_qa_path.relative_to(root)),
            "sha256": sha256(assembly_qa_path),
            "asset_path": assembly_qa["asset_path"],
            "asset_sha256": assembly_qa["asset_sha256"],
            "duration_seconds": assembly_qa["technical"]["duration_seconds"],
        },
        "policy": {
            "no_padding": True,
            "no_loop": True,
            "no_time_stretch": True,
            "no_duplicate_paid_post": True,
            "video_model": "seedance-2.0-fast",
        },
        "non_dialogue_canonical_shot_count": len(non_dialogue),
        "non_dialogue_nominal_seconds": nominal_gap,
        "measured_episode_gap_seconds": measured_gap,
        "residual_after_nominal_non_dialogue_seconds": round(measured_gap - nominal_gap, 3),
        "completed_canonical_action_bindings": [
            shot["canonical_shot_id"]
            for shot in non_dialogue
            if shot["coverage_state"] == "CANONICAL_ACTION_BOUND_COMPLETE"
        ],
        "dispatchable_ready_task_ids": [
            f"{shot['canonical_shot_id']}-SOURCE-BINDING-V1"
            for shot in non_dialogue
            if shot["coverage_state"] != "CANONICAL_ACTION_BOUND_COMPLETE"
        ],
        "shots": non_dialogue,
        "status": "READY_FOR_PARALLEL_SOURCE_BINDING",
        "next_action": (
            "Bind each shot to an exact-SHA Q1-admitted native asset or compile a new "
            "keyframe task; then submit only newly admitted video tasks in bounded parallel."
        ),
    }

    out = root / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "sha256": sha256(out),
        "shot_count": len(shots),
        "ready_count": len(non_dialogue),
        "nominal_seconds": nominal_gap,
        "measured_gap_seconds": measured_gap,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
