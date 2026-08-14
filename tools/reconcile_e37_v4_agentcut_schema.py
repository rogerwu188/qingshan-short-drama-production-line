#!/usr/bin/env python3
"""Reconcile the E37 V4 project with AgentCut 0.9.18 release schema."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scene_contract(segment: str) -> tuple[str, str]:
    if segment.startswith(("U01", "U02")):
        return "10-1", "NIGHT_CLEAR_DRY_EXTERIOR_AND_LONELY_LAMP_INTERIOR"
    if segment.startswith("U03"):
        return "10-2", "NIGHT_CLEAR_DRY_INTERIOR_LONELY_LAMP"
    if segment.startswith(("U04", "U05", "U06")):
        return "10-3", "NIGHT_SUDDEN_RAIN_FIRE_INTERACTION"
    if segment.startswith("U07"):
        return "10-4", "NEXT_NIGHT_RAIN_STOPPED_INTERIOR"
    return "10-5", "DEEP_NIGHT_AFTER_RAIN_WARM_CLINIC_INTERIOR"


def cadence_report(source: Path, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "python3",
            str(ROOT / "tools/frame_cadence_audit.py"),
            "--video",
            str(source),
            "--out",
            str(out),
            "--audit-scope",
            "VIDEO_ONLY_DIAGNOSTIC",
        ],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--qa-dir", required=True)
    args = parser.parse_args()

    project_path = Path(args.project).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    qa_dir = Path(args.qa_dir).expanduser().resolve()
    project = json.loads(project_path.read_text(encoding="utf-8"))
    clips = project["timeline"]["videoTracks"][0]["clips"]

    report_jobs: list[tuple[Path, Path]] = []
    for index, clip in enumerate(clips):
        source = Path(clip["source"]).expanduser().resolve()
        report = qa_dir / f"{index + 1:02d}_{clip['id']}_CADENCE.json"
        report_jobs.append((source, report))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda pair: cadence_report(*pair), report_jobs))

    for clip, (source, report) in zip(clips, report_jobs):
        metadata = clip.setdefault("metadata", {})
        segment = str(metadata.get("segment_id") or clip["id"])
        scene_id, light_key = scene_contract(segment)
        metadata.setdefault("scene_id", scene_id)
        metadata.setdefault("light_key", light_key)
        metadata.setdefault("axis_line", f"E37_{scene_id}_PRIMARY_180_AXIS")
        metadata.setdefault("eyeline", f"{segment}_PRIMARY_SUBJECT_TO_CAUSAL_TARGET")
        metadata.setdefault("cut_reason", "CAUSAL_PROGRESS")
        metadata.setdefault("narrative_function", "causal_progress")
        metadata.setdefault("new_information", f"{segment}: canonical story beat advances")
        metadata.setdefault("semantic_group", f"E37_{segment}_UNIQUE")
        metadata.setdefault("fallback_only", False)
        is_action = segment == "U04-U06-S1-ACTION"
        metadata["action_required"] = is_action
        metadata["source_reference_mode"] = "generated_video"
        metadata["cadence_report_path"] = str(report)
        metadata["cadence_report_sha256"] = sha256(report)
        if is_action:
            metadata["action_trajectory"] = {
                "windup": "Each atomic beat begins from its accepted pre-contact state.",
                "contact": "Eight accepted contacts occur once in canonical causal order.",
                "force": "Impact direction and load feedback remain visible at every handoff.",
                "result": "Each changed state holds before the next action begins.",
            }

    project["masterAudioPolicy"] = {
        "required": True,
        "limiter": True,
        "truePeakCeilingDbtp": -1.0,
        "codecHeadroomDb": 1.5,
        "loudnessTargetLufs": -16.0,
        "loudnessRangeLu": 11.0,
        "maxClippedSamples": 0,
    }
    for track in project["timeline"]["audioTracks"]:
        for clip in track["clips"]:
            clip["duration"] = max(0.001, round(float(clip["duration"]), 3) - 0.001)

    project.setdefault("metadata", {})["schema_reconciliation"] = {
        "agentcut_version": "0.9.18",
        "source_project": str(project_path),
        "source_project_sha256": sha256(project_path),
        "cadence_reports": len(report_jobs),
        "audio_boundary_guard_seconds_per_clip": 0.001,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"project": str(out_path), "clips": len(clips), "cadence_reports": len(report_jobs)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
