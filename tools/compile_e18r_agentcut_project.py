#!/usr/bin/env python3
"""Compile the admitted E18R sources into an AgentCut trial project."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

try:
    from tools.cut_motivation_gate import required_cut_metadata
except ModuleNotFoundError:  # direct `python tools/compile_e18r_agentcut_project.py`
    from cut_motivation_gate import required_cut_metadata


BASE = Path(__file__).resolve().parents[1]


BED_PATHS = {
    "R01": "working_assets/e18_e19_runtime_beds_batch1_video_20260715/E18-BED-R01_NIGHT_ROAD_BOX/result_01.mp4",
    "R02": "working_assets/e18_e19_runtime_beds_batch1_video_20260715/E18-BED-R02_STRETCHER_AFTERBREATH/result_01.mp4",
    "R03": "working_assets/e18_e19_runtime_beds_batch1_video_20260715/E18-BED-R03_CARRIAGE_CURTAIN/result_01.mp4",
    "R04": "working_assets/e18_e19_runtime_beds_batch1_video_20260715/E18-BED-R04_BLACK_CAT_BOX/result_01.mp4",
    "R05": "working_assets/e18_e19_runtime_beds_batch2_video_20260715/E18-BED-R05_BOX_LANTERN_INSERT/result_01.mp4",
    "R06": "working_assets/e18_e19_runtime_beds_batch2_video_20260715/E18-BED-R06_GATE_SHADOWS/result_01.mp4",
    "R07": "working_assets/e18_e19_runtime_beds_batch2_video_20260715/E18-BED-R07_STRETCHER_EMPTY_ROAD/result_01.mp4",
    "R08": "working_assets/e18_e19_runtime_beds_batch2_video_20260715/E18-BED-R08_CURTAIN_HAND_INSERT/result_01.mp4",
    "R10": "working_assets/e18_e19_runtime_beds_batch2_video_20260715/E18-BED-R10_EVIDENCE_TABLE/result_01.mp4",
    "R11": "working_assets/e18_e19_runtime_beds_batch2_video_20260715/E18-BED-R11_NIGHT_PATH_RESET/result_01.mp4",
}

BEAT_BEDS = {
    "B01": ["R11", "R01"],
    "B02": ["R02", "R07"],
    "B03": ["R06", "R10"],
    "B04": ["R03", "R08"],
    "B06": ["R04", "R05"],
}

CUTAWAY_DIALOGUE_IDS = {
    "DIA-002",
    "DIA-008",
    "DIA-013",
    "DIA-014",
    "DIA-017",
    "DIA-027",
}


def load(path: str) -> dict:
    return json.loads((BASE / path).read_text(encoding="utf-8"))


def duration(path: Path, ffmpeg: str) -> float:
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    for line in proc.stderr.splitlines():
        if "Duration:" not in line:
            continue
        clock = line.split("Duration:", 1)[1].split(",", 1)[0].strip()
        hours, minutes, seconds = clock.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    raise RuntimeError(f"Unable to probe duration: {path}")


def clip(source: str, start: float, in_sec: float, duration_sec: float, *, metadata: dict | None = None) -> dict:
    return {
        "source": str((BASE / source).resolve()),
        "start": round(start, 3),
        "in": round(in_sec, 3),
        "duration": round(duration_sec, 3),
        "metadata": metadata or {},
    }


def _video_contract(row: dict, *, label: str) -> dict:
    return required_cut_metadata(row, label=label)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", required=True)
    parser.add_argument("--inventory", required=True)
    parser.add_argument("--b05-plan", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--output-video", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--tolerance", type=float, default=0.10)
    args = parser.parse_args()

    coverage = load(args.coverage)
    inventory = load(args.inventory)
    b05_plan = load(args.b05_plan)
    by_beat: dict[str, list[dict]] = {}
    for item in inventory["items"]:
        by_beat.setdefault(item["beat_id"], []).append(item)

    video_a: list[dict] = []
    video_b: list[dict] = []
    dialogue_audio: list[dict] = []
    beat_windows: list[dict] = []
    cursor = 0.0

    # Bed metadata must come from the coverage plan. A background bed is still
    # an editorial clip; do not invent a reason for it in this compiler.
    bed_contracts = coverage.get("bed_contracts", {})

    for beat in coverage["beats"]:
        beat_id = beat["beat_id"]
        beat_start = cursor
        if beat_id == "B05":
            for row in b05_plan["video_segments"]:
                contract = _video_contract(row, label=f"E18R B05 video row {row.get('order')}")
                video_b.append(
                    clip(
                        row["path"],
                        beat_start + float(row["timeline_in_sec"]),
                        float(row["source_in_sec"]),
                        float(row["duration_sec"]),
                        metadata=contract,
                    )
                )
            for row in b05_plan["audio_segments"]:
                dialogue_audio.append(
                    {
                        **clip(
                            row["path"],
                            beat_start + float(row["timeline_in_sec"]),
                            0.0,
                            float(row["duration_sec"]),
                        ),
                        "volume": 1.0,
                    }
                )
            cursor = beat_start + float(b05_plan["target_runtime_sec"])
        else:
            for bed_id in BEAT_BEDS[beat_id]:
                source = BED_PATHS[bed_id]
                source_duration = duration(BASE / source, args.ffmpeg)
                bed_duration = min(12.0, source_duration)
                contract = _video_contract(
                    bed_contracts.get(bed_id) or {},
                    label=f"E18R bed {bed_id}",
                )
                video_a.append(clip(source, cursor, 0.0, bed_duration, metadata=contract))
                cursor += bed_duration
            cursor = beat_start
            for item in by_beat[beat_id]:
                audio_seconds = duration(BASE / item["audio"], args.ffmpeg)
                picture_seconds = duration(BASE / item["picture"], args.ffmpeg)
                if item["dialogue_id"] not in CUTAWAY_DIALOGUE_IDS:
                    video_b.append(
                        clip(
                            item["picture"], cursor, 0.0,
                            min(audio_seconds, picture_seconds),
                            metadata=_video_contract(item, label=f"E18R {item['dialogue_id']}"),
                        )
                    )
                dialogue_audio.append(
                    {
                        **clip(item["audio"], cursor, 0.0, audio_seconds),
                        "volume": 1.0,
                    }
                )
                cursor += audio_seconds

        beat_windows.append(
            {
                "beat_id": beat_id,
                "start_seconds": round(beat_start, 3),
                "end_seconds": round(cursor, 3),
                "actual_seconds": round(cursor - beat_start, 3),
                "planning_target_seconds": beat["target_seconds"],
            }
        )

    target = float(coverage["runtime_target_seconds"]["target"])
    lower = target * (1.0 - args.tolerance)
    upper = target * (1.0 + args.tolerance)
    if not lower <= cursor <= upper:
        raise RuntimeError(f"AgentCut project duration {cursor:.3f}s is outside {lower:.3f}-{upper:.3f}s")

    project = {
        "version": "1.0",
        "background": "black",
        "output": {
            "path": str((BASE / args.output_video).resolve()),
            "width": 720,
            "height": 1280,
            "fps": 24,
            "videoCodec": "libx264",
            "audioCodec": "aac",
            "audioBitrate": "192k",
            "pixelFormat": "yuv420p",
            "threads": 4,
        },
        "timeline": {
            "videoTracks": [
                {"id": "approved_dynamic_beds", "clips": video_a},
                {"id": "ordered_dialogue_picture", "clips": video_b},
            ],
            "audioTracks": [
                {"id": "ordered_dialogue", "clips": dialogue_audio},
            ],
        },
        "qingshanAudit": {
            "episode": "E18R",
            "status": "AGENTCUT_TRIAL_NOT_FINAL",
            "engine": "AgentCut",
            "worker_target": 4,
            "coverage_ref": args.coverage,
            "inventory_ref": args.inventory,
            "b05_plan_ref": args.b05_plan,
            "dialogue_order": [item["dialogue_id"] for item in inventory["items"]],
            "cutaway_dialogue_ids": sorted(CUTAWAY_DIALOGUE_IDS),
            "bed_sources": BED_PATHS,
            "excluded_bed": "E18-BED-R09_BLACK_CAT_ROOF",
            "runtime_target_seconds": target,
            "runtime_tolerance_fraction": args.tolerance,
            "compiled_runtime_seconds": round(cursor, 3),
            "beat_windows": beat_windows,
            "no_loop": True,
            "no_freeze": True,
            "no_post_speed_change": True,
            "final_lock": False,
            "package_allowed": False,
            "platform_mutation_allowed": False,
        },
        "requireCutReason": True,
    }
    output = BASE / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "READY_FOR_AGENTCUT_VALIDATE_NOT_FINAL",
                "project": str(output),
                "runtime_seconds": round(cursor, 3),
                "allowed_range_seconds": [round(lower, 3), round(upper, 3)],
                "video_clips": len(video_a) + len(video_b),
                "audio_clips": len(dialogue_audio),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
