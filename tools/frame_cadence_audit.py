#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import tempfile
from pathlib import Path
from typing import Any

try:
    from run_regression_ci import adjacent_motion_values, default_ffmpeg, duration_seconds, freeze_stats
except ModuleNotFoundError:
    from tools.run_regression_ci import adjacent_motion_values, default_ffmpeg, duration_seconds, freeze_stats


def media_fps(ffmpeg: str, path: Path) -> float:
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-i", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    match = re.search(r"(\d+(?:\.\d+)?)\s+fps", proc.stderr + proc.stdout)
    if not match:
        raise SystemExit(f"Could not parse video fps: {path}")
    return float(match.group(1))


def render_plan_source_fps(ffmpeg: str, render_plan: Path | None) -> list[dict[str, Any]]:
    if render_plan is None:
        return []
    payload = json.loads(render_plan.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for segment in payload.get("segments", []):
        raw_path = segment.get("path")
        if not raw_path or raw_path in seen:
            continue
        source = Path(raw_path).expanduser().resolve()
        if not source.is_file():
            continue
        seen.add(raw_path)
        row = {
            "source_id": segment.get("source_id"),
            "path": str(source),
            "fps": media_fps(ffmpeg, source),
        }
        exemption = segment.get("cadence_exempt_reason")
        if exemption:
            row["cadence_exempt_reason"] = exemption
        rows.append(row)
    return rows


def render_plan_motivated_static_ranges(render_plan: Path | None) -> list[dict[str, Any]]:
    if render_plan is None:
        return []
    payload = json.loads(render_plan.read_text(encoding="utf-8"))
    ranges: list[dict[str, Any]] = []
    cursor = 0.0
    for segment in payload.get("segments", []):
        duration = float(segment.get("duration_sec", 0) or 0)
        end = cursor + duration
        if segment.get("source_id") == "NALU_tail" or segment.get("designated_static_beat"):
            ranges.append(
                {
                    "start_seconds": cursor,
                    "end_seconds": end,
                    "reason": segment.get("static_reason") or "declared static title/tail beat",
                }
            )
        cursor = end
    return ranges


def overlaps_declared_range(item: dict[str, Any], ranges: list[dict[str, Any]]) -> bool:
    start = float(item["start_seconds"])
    end = start + float(item["duration_seconds"])
    return any(
        start < float(row["end_seconds"]) and end > float(row["start_seconds"])
        for row in ranges
    )


def periodic_duplicate_stats(
    values: list[float],
    fps: float,
    *,
    duplicate_threshold: float = 0.35,
    min_interval_frames: int = 4,
    max_interval_frames: int = 6,
    min_events: int = 5,
) -> dict[str, Any]:
    duplicate_frames = [index + 1 for index, value in enumerate(values) if value < duplicate_threshold]
    chains: list[list[int]] = []
    current: list[int] = []
    for frame in duplicate_frames:
        if not current:
            current = [frame]
            continue
        interval = frame - current[-1]
        if min_interval_frames <= interval <= max_interval_frames:
            current.append(frame)
            continue
        if len(current) >= min_events:
            chains.append(current)
        current = [frame]
    if len(current) >= min_events:
        chains.append(current)

    rows = []
    for chain in chains:
        intervals = [right - left for left, right in zip(chain, chain[1:])]
        rows.append(
            {
                "start_frame": chain[0],
                "end_frame": chain[-1],
                "start_seconds": chain[0] / fps,
                "end_seconds": chain[-1] / fps,
                "event_count": len(chain),
                "interval_frames": intervals,
                "dominant_interval_frames": statistics.mode(intervals),
            }
        )
    return {
        "duplicate_threshold": duplicate_threshold,
        "min_interval_frames": min_interval_frames,
        "max_interval_frames": max_interval_frames,
        "min_events": min_events,
        "near_duplicate_frame_count": len(duplicate_frames),
        "near_duplicate_ratio": len(duplicate_frames) / len(values) if values else 0.0,
        "near_duplicate_frames": duplicate_frames,
        "yavg_candidate_chains": rows,
        "yavg_candidate_chain_count": len(rows),
        "periodic_chains": [],
        "periodic_chain_count": 0,
        "verification_method": "MPDECIMATE_REQUIRED",
    }


def verify_periodic_duplicates_with_mpdecimate(
    periodic_duplicates: dict[str, Any],
    removed_frames: list[int],
) -> dict[str, Any]:
    """Promote YAVG candidates only when mpdecimate confirms the same cadence."""
    removed = set(removed_frames)
    min_events = int(periodic_duplicates.get("min_events", 5))
    min_interval = int(periodic_duplicates.get("min_interval_frames", 4))
    max_interval = int(periodic_duplicates.get("max_interval_frames", 6))
    verified: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for candidate in periodic_duplicates.get("yavg_candidate_chains", []):
        start = int(candidate["start_frame"])
        end = int(candidate["end_frame"])
        candidate_frames = [
            start + offset
            for offset in range(0, end - start + 1)
            if start + offset in removed
        ]
        runs: list[list[int]] = []
        current: list[int] = []
        for frame in candidate_frames:
            if not current or min_interval <= frame - current[-1] <= max_interval:
                current.append(frame)
            else:
                if len(current) >= min_events:
                    runs.append(current)
                current = [frame]
        if len(current) >= min_events:
            runs.append(current)

        if not runs:
            rejected.append(
                {
                    **candidate,
                    "verification_status": "REJECTED_YAVG_LOW_MOTION_FALSE_POSITIVE",
                    "mpdecimate_matching_frames": candidate_frames,
                    "mpdecimate_matching_event_count": len(candidate_frames),
                }
            )
            continue

        for run in runs:
            intervals = [right - left for left, right in zip(run, run[1:])]
            verified.append(
                {
                    **candidate,
                    "start_frame": run[0],
                    "end_frame": run[-1],
                    "event_count": len(run),
                    "interval_frames": intervals,
                    "dominant_interval_frames": statistics.mode(intervals),
                    "verification_status": "CONFIRMED_MPDECIMATE",
                    "mpdecimate_matching_frames": run,
                }
            )

    return {
        **periodic_duplicates,
        "periodic_chains": verified,
        "periodic_chain_count": len(verified),
        "rejected_yavg_candidates": rejected,
        "verification_method": "ffmpeg mpdecimate source-timestamp frame matching",
        "mpdecimate_removed_frame_count": len(removed_frames),
        "mpdecimate_removed_frames": removed_frames,
    }


def mpdecimate_removed_frames(
    ffmpeg: str,
    video: Path,
    fps: float,
    total_frames: int,
) -> list[int]:
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-i",
            str(video),
            "-vf",
            "mpdecimate,showinfo",
            "-an",
            "-f",
            "null",
            "-",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"mpdecimate verification failed: {video}")
    kept = {
        round(float(match.group(1)) * fps)
        for match in re.finditer(r"pts_time:\s*([0-9]+(?:\.[0-9]+)?)", proc.stderr)
    }
    return [frame for frame in range(total_frames) if frame not in kept]


def cadence_signatures(periodic_duplicates: dict[str, Any]) -> list[dict[str, Any]]:
    signatures: list[dict[str, Any]] = []
    interval_four = [
        row
        for row in periodic_duplicates.get("periodic_chains", [])
        if int(row.get("dominant_interval_frames", 0)) == 4
    ]
    if interval_four:
        signatures.append(
            {
                "signature": "SUSPECTED_18_TO_24_FRAME_DUPLICATION",
            "basis": "mpdecimate-confirmed duplicate events repeat every fourth output frame",
                "chain_count": len(interval_four),
                "event_count": sum(int(row.get("event_count", 0)) for row in interval_four),
                "causal_scope": "GENERATION_OR_DELIVERY_PATH_UNCONFIRMED",
                "prompt_fix_sufficient": False,
            }
        )
    return signatures


def evaluate_cadence(
    output_fps: float,
    source_rows: list[dict[str, Any]],
    freeze: dict[str, Any],
    *,
    fps_tolerance: float = 0.05,
    motivated_static_ranges: list[dict[str, Any]] | None = None,
    audit_scope: str = "FINAL_PACKAGE",
    periodic_duplicates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    motivated_static_ranges = motivated_static_ranges or []
    mismatched_sources = [
        row
        for row in source_rows
        if abs(float(row["fps"]) - output_fps) > fps_tolerance
        and not row.get("cadence_exempt_reason")
    ]
    exempted_mismatches = [
        row
        for row in source_rows
        if abs(float(row["fps"]) - output_fps) > fps_tolerance
        and row.get("cadence_exempt_reason")
    ]
    if mismatched_sources:
        source_rates = sorted({round(float(row["fps"]), 3) for row in mismatched_sources})
        failures.append(
            "output_source_fps_mismatch:"
            f"output={output_fps:.3f}:sources={','.join(str(value) for value in source_rates)}"
        )
    unmotivated_freezes = [
        item
        for item in freeze.get("frozen_runs", [])
        if not overlaps_declared_range(item, motivated_static_ranges)
    ]
    for item in unmotivated_freezes:
        failures.append(
            "short_freeze_detected:"
            f"{float(item['start_seconds']):.3f}+{float(item['duration_seconds']):.3f}"
        )
    periodic_duplicates = periodic_duplicates or {
        "periodic_chains": [],
        "periodic_chain_count": 0,
    }
    signatures = cadence_signatures(periodic_duplicates)
    for item in periodic_duplicates.get("periodic_chains", []):
        failures.append(
            "periodic_duplicate_cadence_detected:"
            f"frames={int(item['start_frame'])}-{int(item['end_frame'])}:"
            f"events={int(item['event_count'])}:"
            f"interval={int(item['dominant_interval_frames'])}"
        )
    return {
        "status": "PASS" if not failures else "FAIL",
        "output_fps": output_fps,
        "source_fps_rows": source_rows,
        "mismatched_source_count": len(mismatched_sources),
        "exempted_mismatch_count": len(exempted_mismatches),
        "exempted_mismatches": exempted_mismatches,
        "freeze": freeze,
        "motivated_static_ranges": motivated_static_ranges,
        "unmotivated_freezes": unmotivated_freezes,
        "periodic_duplicates": periodic_duplicates,
        "cadence_signatures": signatures,
        "failures": failures,
        "audit_scope": audit_scope,
        "audio_scope": "FULL_RELEASE_AUDIO_REQUIRED" if audit_scope == "FINAL_PACKAGE" else "VIDEO_ONLY_DIAGNOSTIC",
        "freeze_run_reporting": "ALL_DETECTED_RUNS_NO_SUMMARY_COLLAPSE",
        "rule": (
            "Final packaging must preserve source cadence unless an approved conversion method is "
            "documented. Any continuous low-motion run of at least 0.5 seconds is release-blocking. "
            "A chain of at least five mpdecimate-confirmed duplicate frames spaced every 4-6 "
            "frames is also release-blocking as a post-retime cadence signature. YAVG is only "
            "a candidate locator and cannot independently prove duplicated frames."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit final video frame cadence and short freezes.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--render-plan")
    parser.add_argument("--out", required=True)
    parser.add_argument("--freeze-motion", type=float, default=0.15)
    parser.add_argument("--min-freeze-seconds", type=float, default=0.5)
    parser.add_argument("--periodic-duplicate-threshold", type=float, default=0.35)
    parser.add_argument("--periodic-min-events", type=int, default=5)
    parser.add_argument("--ffmpeg", default=default_ffmpeg())
    parser.add_argument(
        "--audit-scope",
        choices=["FINAL_PACKAGE", "VIDEO_ONLY_DIAGNOSTIC"],
        default="FINAL_PACKAGE",
    )
    args = parser.parse_args()

    video = Path(args.video).expanduser().resolve()
    render_plan = Path(args.render_plan).expanduser().resolve() if args.render_plan else None
    out = Path(args.out).expanduser().resolve()
    if not video.is_file():
        raise SystemExit(f"Missing video: {video}")
    if render_plan is not None and not render_plan.is_file():
        raise SystemExit(f"Missing render plan: {render_plan}")
    if not args.ffmpeg or not Path(args.ffmpeg).is_file():
        raise SystemExit("Missing ffmpeg. Use --ffmpeg or install ffmpeg.")

    ffmpeg = str(Path(args.ffmpeg).resolve())
    output_fps = media_fps(ffmpeg, video)
    runtime = duration_seconds(video, ffmpeg)
    with tempfile.TemporaryDirectory(prefix="qingshan_frame_cadence_") as tmp:
        values = adjacent_motion_values(ffmpeg, video, Path(tmp) / "motion.txt")
    freeze = freeze_stats(
        values,
        output_fps,
        args.freeze_motion,
        args.min_freeze_seconds,
        runtime,
    )
    periodic_duplicates = periodic_duplicate_stats(
        values,
        output_fps,
        duplicate_threshold=args.periodic_duplicate_threshold,
        min_events=args.periodic_min_events,
    )
    periodic_duplicates = verify_periodic_duplicates_with_mpdecimate(
        periodic_duplicates,
        mpdecimate_removed_frames(ffmpeg, video, output_fps, len(values) + 1),
    )
    report = evaluate_cadence(
        output_fps,
        render_plan_source_fps(ffmpeg, render_plan),
        freeze,
        motivated_static_ranges=render_plan_motivated_static_ranges(render_plan),
        audit_scope=args.audit_scope,
        periodic_duplicates=periodic_duplicates,
    )
    report.update(
        {
            "schema": "qingshan.frame_cadence_audit.v2",
            "video": str(video),
            "render_plan": str(render_plan) if render_plan else None,
            "runtime_seconds": runtime,
            "motion_mean": statistics.mean(values) if values else 0.0,
            "motion_method": (
                "ffmpeg adjacent-frame YAVG candidate localization followed by mandatory "
                "mpdecimate source-timestamp verification"
            ),
        }
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(out), "failures": report["failures"]}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
