#!/usr/bin/env python3
"""Compile E19R's ordered candidate timeline into an AgentCut diagnostic project."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from tools.cut_motivation_gate import required_cut_metadata
except ModuleNotFoundError:  # direct `python tools/compile_e19r_agentcut_project.py`
    from cut_motivation_gate import required_cut_metadata


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def absolute(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def rooted(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def _required_generation_metadata(shot: dict[str, Any]) -> dict[str, Any]:
    """Build the construction-time cut contract; reject incomplete clips."""
    return required_cut_metadata(shot, label=f"shot {shot.get('shot_index')}")


def compile_project(
    script_path: Path,
    skeleton_path: Path,
    overrides_path: Path,
    output_video: Path,
    multimodal_qa_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    script = json.loads(script_path.read_text(encoding="utf-8"))
    skeleton = json.loads(skeleton_path.read_text(encoding="utf-8"))
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    multimodal_map: dict[str, dict[str, Any]] = {}
    if multimodal_qa_path:
        multimodal_qa = json.loads(multimodal_qa_path.read_text(encoding="utf-8"))
        if multimodal_qa.get("status") != "PASS":
            raise ValueError("multimodal QA is not PASS")
        multimodal_map = {
            row["dialogue_id"]: row
            for row in multimodal_qa.get("results", [])
            if row.get("status") == "PASS"
        }
    script_sha = sha256(script_path)

    expected_dialogue = [(row["dia_id"], row["text"]) for row in script["dialogue_draft"]]
    actual_dialogue = [
        (shot.get("dialogue_id"), shot.get("dialogue_text"))
        for shot in skeleton["shots"]
        if shot.get("dialogue_id")
    ]
    if actual_dialogue != expected_dialogue:
        raise ValueError("ordered skeleton dialogue sequence does not match current script")
    if skeleton.get("runtime_frames") != sum(shot["duration_frames"] for shot in skeleton["shots"]):
        raise ValueError("ordered skeleton frame total mismatch")

    override_map = {row["dialogue_id"]: row for row in overrides.get("overrides", [])}
    if len(override_map) != len(overrides.get("overrides", [])):
        raise ValueError("duplicate dialogue override")
    override_failures: list[str] = []
    for dialogue_id, row in override_map.items():
        path = absolute(row["picture_source"])
        if not path.is_file():
            override_failures.append(f"missing:{dialogue_id}")
        elif sha256(path) != row["sha256"]:
            override_failures.append(f"sha256_mismatch:{dialogue_id}")
    if override_failures:
        raise ValueError(";".join(override_failures))

    video_clips: list[dict[str, Any]] = []
    audio_clips: list[dict[str, Any]] = []
    missing_sources: list[str] = []
    override_used: list[str] = []
    multimodal_picture_used: list[str] = []
    multimodal_audio_used: list[str] = []
    for shot in skeleton["shots"]:
        dialogue_id = shot.get("dialogue_id")
        override = override_map.get(dialogue_id)
        multimodal = multimodal_map.get(dialogue_id)
        source = absolute(
            override["picture_source"]
            if override
            else multimodal["path"]
            if multimodal
            else shot["source_path"]
        )
        if not source.is_file():
            missing_sources.append(str(source))
        if override:
            override_used.append(dialogue_id)
        elif multimodal:
            multimodal_picture_used.append(dialogue_id)
        start = shot["timeline_in_frame"] / skeleton["fps"]
        duration = shot["duration_frames"] / skeleton["fps"]
        cut_contract = _required_generation_metadata(shot)
        metadata = {
            "episode": "E19R",
            "shot_index": shot["shot_index"],
            "dialogue_id": dialogue_id,
            "beat_id": shot.get("beat_id"),
            "speaker": shot.get("speaker"),
            "picture_override": bool(override),
            "multimodal_picture": bool(multimodal and not override),
            "script_sha256": script_sha,
            **cut_contract,
        }
        video_clips.append(
            {
                "id": f"E19R-V-{shot['shot_index']:03d}",
                "source": str(source),
                "start": start,
                "in": float(shot.get("source_in_seconds", 0.0)),
                "duration": duration,
                "metadata": metadata,
            }
        )
        binding = shot.get("audio_binding") or {}
        audio_value = binding.get("path")
        if multimodal or (audio_value and str(binding.get("state", "")).startswith("NATIVE")):
            audio_source = absolute(multimodal["path"] if multimodal else audio_value)
            if not audio_source.is_file():
                missing_sources.append(str(audio_source))
            if multimodal:
                multimodal_audio_used.append(dialogue_id)
            audio_clips.append(
                {
                    "id": f"E19R-A-{shot['shot_index']:03d}",
                    "source": str(audio_source),
                    "start": start,
                    "in": 0.0,
                    "duration": duration,
                    "volume": 1.0,
                    "transitionIn": {"type": "fade", "duration": 0.02},
                    "transitionOut": {"type": "fade", "duration": 0.02},
                    "metadata": metadata,
                }
            )
    if missing_sources:
        raise FileNotFoundError("missing sources: " + ", ".join(sorted(set(missing_sources))))
    if set(override_used) != set(override_map):
        raise ValueError("not all declared picture overrides were used")

    project = {
        "version": "1.0",
        "background": "black",
        "output": {
            "path": str(output_video),
            "width": 720,
            "height": 1280,
            "fps": skeleton["fps"],
            "videoCodec": "libx264",
            "audioCodec": "aac",
            "audioBitrate": "192k",
            "pixelFormat": "yuv420p",
            "threads": 4,
        },
        "timeline": {
            "videoTracks": [{"id": "E19R_ORDERED_PICTURE_V1", "clips": video_clips}],
            "audioTracks": [{"id": "E19R_NATIVE_CANDIDATE_AUDIO_V1", "clips": audio_clips}],
        },
        "requireCutReason": True,
    }
    report = {
        "schema": "qingshan.e19r.agentcut_project_compile.v1",
        "status": "PASS_PROJECT_COMPILED_NOT_FINAL_AUDIO_INCOMPLETE",
        "script": str(script_path),
        "script_sha256": script_sha,
        "script_density_gate_ref": "qa/script_density_gate_20260717/E19R_SCRIPT_DENSITY_PREFLIGHT_20260717.json",
        "skeleton": str(skeleton_path),
        "skeleton_declared_approved_sha256": skeleton.get("approved_script_sha256"),
        "skeleton_dialogue_sequence_exact_match": True,
        "video_clip_count": len(video_clips),
        "dialogue_count": len(expected_dialogue),
        "picture_override_count": len(override_used),
        "multimodal_picture_clip_count": len(multimodal_picture_used),
        "multimodal_audio_clip_count": len(multimodal_audio_used),
        "total_audio_clip_count": len(audio_clips),
        "pending_audio_binding_count": len(expected_dialogue) - len(audio_clips),
        "runtime_frames": skeleton["runtime_frames"],
        "runtime_seconds": skeleton["runtime_seconds"],
        "final_lock_allowed": False,
        "package_allowed": False,
        "rollback": "Delete only the V1 project, diagnostic render, and compile report.",
    }
    return project, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--script", type=Path, default=ROOT / "configs/e19r_dialogue_beat_sheet_v3_machine_approved_20260717.json")
    parser.add_argument("--skeleton", type=Path, default=ROOT / "configs/e19r_ordered_timing_audio_skeleton_v1_not_final_20260717.json")
    parser.add_argument("--overrides", type=Path, default=ROOT / "configs/e19r_ordered_picture_source_override_candidates_v1_not_final_20260717.json")
    parser.add_argument("--project", type=Path, default=ROOT / "configs/e19r_agentcut_project_v1_not_final_20260717.json")
    parser.add_argument("--output-video", type=Path, default=ROOT / "exports/e19r/agentcut_trial_v1_not_final_20260717/E19R_AGENTCUT_TRIAL_V1_NOT_FINAL.mp4")
    parser.add_argument("--report", type=Path, default=ROOT / "qa/e19r_agentcut_v1_20260717/E19R_AGENTCUT_PROJECT_V1_COMPILE_REPORT_20260717.json")
    parser.add_argument("--multimodal-qa", type=Path)
    args = parser.parse_args()
    args.script = rooted(args.script)
    args.skeleton = rooted(args.skeleton)
    args.overrides = rooted(args.overrides)
    args.project = rooted(args.project)
    args.output_video = rooted(args.output_video)
    args.report = rooted(args.report)
    if args.multimodal_qa:
        args.multimodal_qa = rooted(args.multimodal_qa)
    project, report = compile_project(
        args.script,
        args.skeleton,
        args.overrides,
        args.output_video,
        args.multimodal_qa,
    )
    args.project.parent.mkdir(parents=True, exist_ok=True)
    args.output_video.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.project.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["project"] = str(args.project)
    report["output_video"] = str(args.output_video)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "project": str(args.project), "report": str(args.report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
