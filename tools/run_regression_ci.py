#!/usr/bin/env python3
"""
Run regression CI for Qingshan final packages.

The script measures the final release MP4 only. Motion uses the same adjacent
frame-difference signalstats baseline as the 2026-07-11 hit-video calibration;
scene timing uses scene-change cut detection rather than package source
segments. It writes JSON and exits non-zero when hard gates fail.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List

try:
    from tools.gate_registry_v3_check import validate as validate_gate_registry
except ModuleNotFoundError:
    from gate_registry_v3_check import validate as validate_gate_registry

FROZEN_THRESHOLD_PROFILE = "v2-final+v2.1+v2.2+v2.3-frozen"
FROZEN_THRESHOLDS = {
    "min_motion": 3.0,
    "redline_motion": 2.5,
    "max_asl": 3.5,
    "redline_asl": 5.0,
    "max_single_shot": 6.0,
    "max_unmotivated_long_shots": 2,
    "under1_min": 0.05,
    "under1_max": 0.15,
    "freeze_ratio_max": 0.03,
    "freeze_motion": 0.15,
    "min_freeze_seconds": 1.5,
    "near_duplicate_ratio_max": 0.10,
    "repeat_cluster_max": 2,
    "nonfight_under08_max": 0.05,
    "digital_zero_db": -90.0,
    "max_adjacent_rms_jump_db": 12.0,
    "min_unmotivated_silence_seconds": 1.0,
    "static_hold_motion_max": 1.5,
    "static_hold_seconds_max": 4.0,
}
DEFAULT_GATE_REGISTRY = (
    Path(__file__).resolve().parents[1] / "configs/GATE_REGISTRY_v3_20260716.json"
)

RUNTIME_GATE_IDS = frozenset({
    "GATE-REGISTRY-INTEGRITY",
    "SOURCE-BRIGHTNESS-JUMP",
    "FINAL-AUDIO-BED-CONTINUITY",
    "FINAL-STATIC-HOLD",
    "FROZEN-THRESHOLD-PROFILE",
    "FINAL-AUDIT-COMPLETENESS",
})
RUNTIME_GATE_BINDINGS = {
    "GATE-REGISTRY-INTEGRITY": "gate_registry_integrity_stats",
    "SOURCE-BRIGHTNESS-JUMP": "source_brightness_audit_stats",
    "FINAL-AUDIO-BED-CONTINUITY": "audio_bed_continuity_stats",
    "FINAL-STATIC-HOLD": "static_hold_stats",
    "FROZEN-THRESHOLD-PROFILE": "threshold_override_audit",
    "FINAL-AUDIT-COMPLETENESS": "build_parser",
}
assert frozenset(RUNTIME_GATE_BINDINGS) == RUNTIME_GATE_IDS


def gate_registry_integrity_stats(registry_path: Path) -> Dict[str, Any]:
    if not registry_path.is_file():
        return {
            "status": "FAIL",
            "registry": str(registry_path),
            "failures": ["gate_registry_missing"],
        }
    try:
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "FAIL",
            "registry": str(registry_path),
            "failures": [f"gate_registry_unreadable:{type(exc).__name__}"],
        }
    report = validate_gate_registry(payload, Path(__file__).resolve().parents[1])
    return {**report, "registry": str(registry_path)}


def default_ffmpeg() -> str | None:
    bundled = Path(".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1")
    if bundled.exists():
        return str(bundled.resolve())
    found = shutil.which("ffmpeg")
    return found


def run(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if check and proc.returncode != 0:
        raise SystemExit(proc.stderr.strip() or proc.stdout.strip())
    return proc


def duration_seconds(path: Path, ffmpeg: str) -> float:
    proc = run([
        ffmpeg,
        "-hide_banner",
        "-i",
        str(path),
    ], check=False)
    text = proc.stderr + proc.stdout
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if not match:
        raise SystemExit(f"Could not parse duration for {path}")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def source_video_fps(path: Path, ffmpeg: str) -> float:
    """Read the encoded source frame rate; never invent a 30 fps default."""
    proc = run([ffmpeg, "-hide_banner", "-i", str(path)], check=False)
    text = proc.stderr + proc.stdout
    video_line = next((line for line in text.splitlines() if " Video: " in line), "")
    match = re.search(r"(?:,|\s)(\d+(?:\.\d+)?)\s+fps(?:,|\s)", video_line)
    if not match:
        raise SystemExit(f"Could not parse source video fps for {path}; pass --fps explicitly")
    fps = float(match.group(1))
    if fps <= 0:
        raise SystemExit(f"Invalid source video fps for {path}: {fps}")
    return fps


def audio_window_mean_db(ffmpeg: str, video: Path, start: float, end: float) -> float:
    proc = run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{max(0.05, end - start):.3f}",
            "-i",
            str(video),
            "-vn",
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        ],
        check=False,
    )
    match = re.search(r"mean_volume:\s*(-?inf|-?[0-9.]+)\s*dB", proc.stderr + proc.stdout)
    if not match or match.group(1) == "-inf":
        return -120.0
    return float(match.group(1))


def audio_silence_segments(
    ffmpeg: str,
    video: Path,
    runtime: float,
    noise_db: float = -70.0,
    minimum_seconds: float = 1.0,
) -> List[Dict[str, float]]:
    proc = run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(video),
            "-vn",
            "-af",
            f"silencedetect=noise={noise_db}dB:d={minimum_seconds}",
            "-f",
            "null",
            "-",
        ],
        check=False,
    )
    text = proc.stderr + proc.stdout
    starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9.]+)", text)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9.]+)", text)]
    rows = []
    for index, start in enumerate(starts):
        end = ends[index] if index < len(ends) else runtime
        rows.append({"start_sec": start, "end_sec": end, "duration_sec": max(0.0, end - start)})
    return rows


def evaluate_audio_bed_rows(
    rows: List[Dict[str, float]],
    silence_segments: List[Dict[str, float]],
    motivated_intervals: List[Dict[str, float]],
    digital_zero_db: float,
    max_adjacent_rms_jump_db: float,
) -> Dict[str, Any]:
    def motivated(start: float, end: float) -> bool:
        midpoint = (start + end) / 2.0
        return any(
            float(item.get("start_sec", 0.0)) <= midpoint < float(item.get("end_sec", 0.0))
            for item in motivated_intervals
        )

    failures = []
    digital_zero_shots = []
    for row in rows:
        if row["mean_volume_db"] <= digital_zero_db and not motivated(row["start_sec"], row["end_sec"]):
            digital_zero_shots.append(row)
            failures.append(f"audio_digital_zero_shot:{int(row['shot_index'])}")

    unmotivated_silences = []
    for row in silence_segments:
        if not motivated(row["start_sec"], row["end_sec"]):
            unmotivated_silences.append(row)
            failures.append(
                f"audio_unmotivated_silence:{row['start_sec']:.2f}-{row['end_sec']:.2f}"
            )

    excessive_jumps = []
    for left, right in zip(rows, rows[1:]):
        jump = abs(right["mean_volume_db"] - left["mean_volume_db"])
        if jump > max_adjacent_rms_jump_db and not motivated(left["end_sec"], right["start_sec"]):
            item = {
                "left_shot": int(left["shot_index"]),
                "right_shot": int(right["shot_index"]),
                "jump_db": jump,
            }
            excessive_jumps.append(item)
            failures.append(
                f"audio_adjacent_rms_jump:{item['left_shot']}-{item['right_shot']}:{jump:.1f}"
            )

    return {
        "status": "PASS" if not failures else "FAIL",
        "shot_rows": rows,
        "digital_zero_shots": digital_zero_shots,
        "silence_segments": silence_segments,
        "unmotivated_silence_segments": unmotivated_silences,
        "excessive_adjacent_rms_jumps": excessive_jumps,
        "motivated_silence_intervals": motivated_intervals,
        "failures": failures,
    }


def audio_bed_continuity_stats(
    ffmpeg: str,
    video: Path,
    cuts: List[float],
    runtime: float,
    coverage_payload: Any,
    digital_zero_db: float,
    max_adjacent_rms_jump_db: float,
    min_unmotivated_silence_seconds: float,
) -> Dict[str, Any]:
    points = [0.0, *[cut for cut in cuts if 0.0 < cut < runtime], runtime]
    rows = [
        {
            "shot_index": index,
            "start_sec": start,
            "end_sec": end,
            "duration_sec": end - start,
            "mean_volume_db": audio_window_mean_db(ffmpeg, video, start, end),
        }
        for index, (start, end) in enumerate(zip(points, points[1:]), start=1)
        if end - start > 0.05
    ]
    motivated = []
    if isinstance(coverage_payload, dict):
        motivated = coverage_payload.get("motivated_silence_intervals") or []
    silences = audio_silence_segments(
        ffmpeg,
        video,
        runtime,
        minimum_seconds=min_unmotivated_silence_seconds,
    )
    result = evaluate_audio_bed_rows(
        rows,
        silences,
        motivated,
        digital_zero_db,
        max_adjacent_rms_jump_db,
    )
    result["thresholds"] = {
        "digital_zero_db": digital_zero_db,
        "max_adjacent_rms_jump_db": max_adjacent_rms_jump_db,
        "min_unmotivated_silence_seconds": min_unmotivated_silence_seconds,
    }
    return result


def resolve_audio_cut_times(payload: Any, visual_cuts: List[float], runtime: float) -> tuple[List[float], str]:
    """Use real audio-edit boundaries when picture inserts do not alter audio.

    Visual scene detection is a valid fallback for simple edits, but it creates
    false RMS discontinuities when an AgentCut picture-only insert lands inside
    one continuous native dialogue clip.
    """
    if payload is None:
        return visual_cuts, "detected_visual_cuts_fallback"
    raw = payload.get("boundaries", payload.get("cut_times", [])) if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        raise ValueError("audio boundary evidence must be a list or contain boundaries/cut_times")
    cuts = sorted({float(value) for value in raw if 0.0 < float(value) < runtime})
    if not cuts:
        raise ValueError("audio boundary evidence contains no in-range boundaries")
    return cuts, "declared_audio_edit_boundaries"


def adjacent_motion_values(ffmpeg: str, video: Path, metadata_file: Path) -> List[float]:
    run([
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(video),
        "-vf", f"tblend=all_mode=difference,signalstats,metadata=print:file={metadata_file}",
        "-an",
        "-f", "null",
        "-",
    ])
    values: List[float] = []
    for line in metadata_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = re.search(r"lavfi\.signalstats\.YAVG=([0-9.]+)", line)
        if match:
            values.append(float(match.group(1)))
    return values


def perceptual_hashes(ffmpeg: str, video: Path, sample_fps: float = 2.0) -> List[int]:
    """Sample 32x32 average hashes without erasing real facial/camera motion."""
    width = height = 32
    proc = subprocess.run([
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(video),
        "-vf", f"fps={sample_fps},scale={width}:{height}:flags=area,format=gray",
        "-an",
        "-f", "rawvideo",
        "-pix_fmt", "gray",
        "-",
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.stderr.decode("utf-8", "ignore").strip() or "Frame-hash sampling failed")
    frame_size = width * height
    raw = proc.stdout
    hashes: List[int] = []
    for offset in range(0, len(raw) - frame_size + 1, frame_size):
        frame = raw[offset:offset + frame_size]
        mean = sum(frame) / frame_size
        value = 0
        for pixel in frame:
            value = (value << 1) | int(pixel >= mean)
        hashes.append(value)
    return hashes


def hamming(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def frame_repeat_stats(hashes: List[int], max_distance: int = 12) -> Dict[str, Any]:
    if len(hashes) < 2:
        return {
            "sample_count": len(hashes),
            "near_duplicate_pairs": 0,
            "near_duplicate_ratio": 0.0,
            "max_nonadjacent_repeat_cluster": len(hashes),
        }
    near_pairs = sum(1 for index in range(1, len(hashes)) if hamming(hashes[index - 1], hashes[index]) <= max_distance)
    clusters: List[List[int]] = []
    for index, value in enumerate(hashes):
        placed = False
        for cluster in clusters:
            if hamming(value, hashes[cluster[0]]) <= max_distance:
                cluster.append(index)
                placed = True
                break
        if not placed:
            clusters.append([index])
    nonadjacent_counts = []
    for cluster in clusters:
        selected: List[int] = []
        for index in cluster:
            if not selected or index - selected[-1] > 1:
                selected.append(index)
        nonadjacent_counts.append(len(selected))
    return {
        "sample_count": len(hashes),
        "near_duplicate_pairs": near_pairs,
        "near_duplicate_ratio": near_pairs / (len(hashes) - 1),
        "max_nonadjacent_repeat_cluster": max(nonadjacent_counts, default=0),
        "hash_hamming_threshold": max_distance,
    }


def pure_black_frame_stats(ffmpeg: str, video: Path) -> Dict[str, Any]:
    proc = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-v",
            "info",
            "-i",
            str(video),
            "-vf",
            "blackframe=amount=95:threshold=32",
            "-an",
            "-f",
            "null",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return {
            "status": "FAIL",
            "frames": [],
            "failures": ["pure_black_frame_scan_failed"],
        }
    rows = [
        {
            "frame": int(match.group(1)),
            "percent_black": int(match.group(2)),
            "time_seconds": float(match.group(3)),
        }
        for match in re.finditer(
            r"frame:(\d+)\s+pblack:(\d+).*?\bt:([0-9.]+)",
            proc.stderr,
        )
    ]
    failures = [f"unintended_pure_black_frames:{len(rows)}"] if rows else []
    return {
        "status": "PASS" if not rows else "FAIL",
        "policy": "Every frame with at least 95 percent pixels below luma threshold 32 blocks final admission.",
        "frames": rows,
        "failures": failures,
    }


def load_json_optional(path: str | None) -> Any:
    if not path:
        return None
    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise SystemExit(f"Missing QA evidence JSON: {target}")
    return json.loads(target.read_text(encoding="utf-8"))


def load_text_files(paths: List[str] | None) -> str:
    chunks = []
    for path in paths or []:
        target = Path(path).expanduser().resolve()
        if not target.exists():
            raise SystemExit(f"Missing approval audit file: {target}")
        chunks.append(target.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def approval_reference_valid(approval_ref: str, episode_id: str, audit_text: str) -> bool:
    """Require one mailbox section to contain the ref, episode, and an explicit approval marker."""
    if not approval_ref or not episode_id or not audit_text:
        return False
    if not re.fullmatch(r"(?:SC2X|CL2X)-[A-Za-z0-9_-]+|ROGER-[A-Za-z0-9_-]+", approval_ref):
        return False
    lines = audit_text.splitlines()
    heading_pattern = re.compile(r"^#{1,2}\s+")
    approval_marker = re.compile(
        r"(?mi)^\s*(?:[-*]\s*)?(?:APPROVED_EXEMPTION|批准豁免)\s*:"
    )
    for index, line in enumerate(lines):
        if not heading_pattern.match(line) or approval_ref not in line:
            continue
        end = index + 1
        while end < len(lines) and not heading_pattern.match(lines[end]):
            end += 1
        section = "\n".join(lines[index:end])
        if episode_id.casefold() in section.casefold() and approval_marker.search(section):
            return True
    return False


def threshold_override_audit(
    args: argparse.Namespace,
    approval_audit_text: str,
) -> Dict[str, Any]:
    overrides = {
        key: {"frozen": frozen, "actual": getattr(args, key)}
        for key, frozen in FROZEN_THRESHOLDS.items()
        if getattr(args, key) != frozen
    }
    if not overrides:
        return {
            "status": "PASS",
            "profile": FROZEN_THRESHOLD_PROFILE,
            "overrides": {},
            "authorization_ref": None,
            "failures": [],
        }

    authorization_ref = str(args.threshold_authorization_ref or "").strip()
    episode_id = str(args.episode_id or "").strip()
    failures = []
    if not authorization_ref:
        failures.append("threshold_override_missing_authorization_ref")
    elif not approval_reference_valid(authorization_ref, episode_id, approval_audit_text):
        failures.append(
            f"threshold_override_unverified_authorization:{authorization_ref}:{episode_id or 'MISSING_EPISODE'}"
        )
    return {
        "status": "PASS_WITH_AUTHORIZED_OVERRIDE" if not failures else "FAIL",
        "profile": FROZEN_THRESHOLD_PROFILE,
        "overrides": overrides,
        "authorization_ref": authorization_ref or None,
        "episode_id": episode_id or None,
        "failures": failures,
    }


def source_manifest_stats(payload: Any, required: bool = False) -> Dict[str, Any]:
    """Validate forward-only source-span and cross-beat reuse declarations."""
    if not isinstance(payload, dict):
        failures = ["coverage_manifest_missing"] if required else []
        return {"status": "FAIL" if failures else "NOT_REQUESTED", "rows": [], "failures": failures}

    segments = payload.get("segments") or []
    failures: List[str] = []
    normalized: List[Dict[str, Any]] = []
    sequence_beats: Dict[str, set[str]] = {}
    sequence_rows: Dict[str, List[Dict[str, Any]]] = {}
    for index, row in enumerate(segments, start=1):
        if not isinstance(row, dict):
            failures.append(f"coverage_segment_invalid:{index}")
            continue
        source_id = str(row.get("source_id", "")).strip()
        sequence_id = str(row.get("source_sequence_id", source_id)).strip()
        beat_id = str(row.get("beat_id", "")).strip()
        source_duration = row.get("source_duration_sec")
        source_in = row.get("source_in_sec")
        source_out = row.get("source_out_sec")
        reason = str(row.get("declared_dramatic_reason", "")).strip()
        motivated_flashback = bool(row.get("motivated_flashback", False))
        missing = [
            field for field, value in (
                ("source_id", source_id),
                ("source_sequence_id", sequence_id),
                ("beat_id", beat_id),
                ("source_duration_sec", source_duration),
                ("source_in_sec", source_in),
                ("source_out_sec", source_out),
            ) if value in (None, "")
        ]
        if required and missing:
            failures.append(f"coverage_segment_missing_fields:{index}:{','.join(missing)}")
            continue
        if missing:
            continue
        try:
            source_duration_value = float(source_duration)
            source_in_value = float(source_in)
            source_out_value = float(source_out)
        except (TypeError, ValueError):
            failures.append(f"coverage_segment_invalid_times:{index}")
            continue
        used_duration = max(0.0, source_out_value - source_in_value)
        used_ratio = used_duration / source_duration_value if source_duration_value > 0 else 0.0
        item = {
            "order": row.get("order", index),
            "source_id": source_id,
            "source_sequence_id": sequence_id,
            "beat_id": beat_id,
            "source_duration_sec": source_duration_value,
            "source_in_sec": source_in_value,
            "source_out_sec": source_out_value,
            "used_duration_sec": used_duration,
            "used_ratio": used_ratio,
            "declared_dramatic_reason": reason,
            "motivated_flashback": motivated_flashback,
        }
        normalized.append(item)
        sequence_beats.setdefault(sequence_id, set()).add(beat_id)
        sequence_rows.setdefault(sequence_id, []).append(item)
        if source_duration_value >= 10.0 and used_ratio >= 0.90 and not reason:
            failures.append(f"untrimmed_source_missing_dramatic_reason:{source_id}:{used_ratio:.3f}")

    for sequence_id, beats in sequence_beats.items():
        if len(beats) <= 1:
            continue
        rows = sequence_rows[sequence_id]
        if not all(row["motivated_flashback"] and row["declared_dramatic_reason"] for row in rows):
            failures.append(f"cross_beat_source_reuse_unmotivated:{sequence_id}:{','.join(sorted(beats))}")
    if required and not segments:
        failures.append("coverage_manifest_segments_missing")
    return {"status": "PASS" if not failures else "FAIL", "rows": normalized, "failures": failures}


def nonfight_short_shot_stats(
    cuts: List[float], runtime: float, coverage_payload: Any, threshold_seconds: float = 0.8
) -> Dict[str, Any]:
    intervals = []
    if isinstance(coverage_payload, dict):
        for row in coverage_payload.get("fight_intervals") or []:
            if not isinstance(row, dict):
                continue
            start = float(row.get("start_sec", 0.0))
            end = float(row.get("end_sec", start))
            if end > start:
                intervals.append((start, end))
    points = [0.0, *[cut for cut in cuts if 0.0 < cut < runtime], runtime]
    durations = []
    for start, end in zip(points, points[1:]):
        midpoint = (start + end) / 2.0
        if any(fight_start <= midpoint < fight_end for fight_start, fight_end in intervals):
            continue
        if end - start > 0.05:
            durations.append(end - start)
    short_count = sum(1 for duration in durations if duration < threshold_seconds)
    return {
        "threshold_seconds": threshold_seconds,
        "nonfight_shot_count": len(durations),
        "short_shot_count": short_count,
        "short_shot_ratio": short_count / len(durations) if durations else 0.0,
        "fight_intervals": [{"start_sec": start, "end_sec": end} for start, end in intervals],
    }


def manifest_shot_reconciliation(
    cuts: List[float],
    runtime: float,
    coverage_payload: Any,
    required: bool = False,
    approval_audit_text: str = "",
) -> Dict[str, Any]:
    """Reconcile detected final-film shots with declared manifest segments."""
    detected_shot_count = len([cut for cut in cuts if 0.0 < cut < runtime]) + (1 if runtime > 0 else 0)
    segments = coverage_payload.get("segments") if isinstance(coverage_payload, dict) else None
    manifest_segment_count = len(segments) if isinstance(segments, list) else 0
    exemption = coverage_payload.get("shot_reconciliation_exemption") if isinstance(coverage_payload, dict) else None
    exemption_reason = ""
    exemption_approved_by = ""
    approval_ref = ""
    episode_id = str(coverage_payload.get("episode_id", "")).strip() if isinstance(coverage_payload, dict) else ""
    if isinstance(exemption, dict):
        exemption_reason = str(exemption.get("reason", "")).strip()
        exemption_approved_by = str(exemption.get("approved_by", "")).strip()
        approval_ref = str(exemption.get("approval_ref", "")).strip()

    mismatch = detected_shot_count != manifest_segment_count
    mismatch_count = abs(detected_shot_count - manifest_segment_count)
    max_exempt_count = min(2, max(1, math.ceil(detected_shot_count * 0.05)))
    allowed_approvers = {
        "roger",
        "storyclaw",
        "storyclaw supervisor",
        "storyclaw监制",
        "claude",
        "claude supervisor",
        "claude监制",
    }
    approver_allowed = exemption_approved_by.casefold() in allowed_approvers
    exemption_within_limit = mismatch_count <= max_exempt_count
    approval_ref_valid = approval_reference_valid(approval_ref, episode_id, approval_audit_text)
    exemption_valid = bool(
        exemption_reason and approver_allowed and exemption_within_limit and approval_ref_valid
    )
    failures: List[str] = []
    if required and mismatch and not exemption_valid:
        failures.append(
            f"manifest_shot_count_mismatch:detected={detected_shot_count}:manifest={manifest_segment_count}"
        )
    if required and mismatch and isinstance(exemption, dict) and not exemption_valid:
        if not exemption_reason or not exemption_approved_by:
            failures.append("shot_reconciliation_exemption_incomplete:reason,approved_by")
        if exemption_approved_by and not approver_allowed:
            failures.append(f"shot_reconciliation_exemption_invalid_approver:{exemption_approved_by}")
        if not exemption_within_limit:
            failures.append(
                f"shot_reconciliation_exemption_scope_exceeded:difference={mismatch_count}:max={max_exempt_count}"
            )
        if not approval_ref or not episode_id:
            failures.append("shot_reconciliation_exemption_missing_trace:episode_id,approval_ref")
        elif not approval_ref_valid:
            failures.append(f"shot_reconciliation_exemption_unverified_ref:{approval_ref}:{episode_id}")

    if failures:
        status = "FAIL"
    elif mismatch and exemption_valid:
        status = "PASS_WITH_EXEMPTION"
    elif required:
        status = "PASS"
    else:
        status = "NOT_REQUESTED"
    return {
        "status": status,
        "detected_shot_count": detected_shot_count,
        "manifest_segment_count": manifest_segment_count,
        "mismatch_count": mismatch_count,
        "max_exempt_count": max_exempt_count,
        "count_matches": not mismatch,
        "exemption": {
            "reason": exemption_reason,
            "approved_by": exemption_approved_by,
            "approval_ref": approval_ref,
            "approval_ref_valid": approval_ref_valid,
            "approver_allowed": approver_allowed,
            "within_limit": exemption_within_limit,
            "valid": exemption_valid,
        },
        "failures": failures,
    }


def action_realtime_stats(payload: Any) -> Dict[str, Any]:
    if payload is None:
        return {"status": "MISSING", "rows": [], "failures": ["action_realtime_evidence_missing"]}
    rows = payload.get("actions", payload if isinstance(payload, list) else [])
    failures: List[str] = []
    normalized = []
    for row in rows:
        start = float(row.get("observed_action_start", row.get("start", 0.0)))
        end = float(row.get("observed_action_end", row.get("end", start)))
        expected = float(row.get("expected_action_duration_seconds", 1.5))
        observed = max(0.0, end - start)
        passed = expected <= 1.5 and observed <= expected + 0.2 and row.get("speed_mode", "real_time") == "real_time"
        item = {**row, "observed_action_duration_seconds": observed, "pass": passed}
        normalized.append(item)
        if not passed:
            failures.append(f"action_not_realtime:{row.get('id', 'unknown')}:{observed:.2f}s")
    return {"status": "PASS" if not failures else "FAIL", "rows": normalized, "failures": failures}


def sentence_audit_stats(payload: Any) -> Dict[str, Any]:
    if payload is None:
        return {"status": "MISSING", "rows": [], "failures": ["asr_sentence_audit_missing"]}
    if isinstance(payload, list):
        rows = payload
    else:
        rows = payload.get("sentences") or payload.get("groups") or []
    failures: List[str] = []
    normalized = []
    for row in rows:
        complete = bool(row.get("complete", row.get("speech_present", False)))
        cut_inside = bool(row.get("cut_inside_sentence", False))
        passed = complete and not cut_inside
        normalized.append({**row, "pass": passed})
        if not passed:
            row_id = row.get("id", row.get("source_id", "unknown"))
            failures.append(f"sentence_incomplete_or_cut:{row_id}")
    return {"status": "PASS" if rows and not failures else "FAIL", "rows": normalized, "failures": failures}


def scene_brightness_stats(payload: Any, max_jump: float = 25.0) -> Dict[str, Any]:
    if payload is None:
        return {"status": "MISSING", "rows": [], "failures": ["scene_brightness_audit_missing"]}
    rows = payload.get("shots", payload if isinstance(payload, list) else [])
    adjudications = payload.get("transition_adjudications", []) if isinstance(payload, dict) else []
    adjudications_by_pair = {
        (row.get("left_shot"), row.get("right_shot")): row
        for row in adjudications
        if isinstance(row, dict)
    }
    failures: List[str] = []
    comparisons = []
    adjudicated_count = 0
    for left, right in zip(rows, rows[1:]):
        if left.get("scene_id") != right.get("scene_id"):
            continue
        left_luma = float(left.get("end_luma", left.get("mean_luma", 0.0)))
        right_luma = float(right.get("start_luma", right.get("mean_luma", 0.0)))
        jump = abs(right_luma - left_luma)
        measured_pass = jump <= max_jump
        adjudication = adjudications_by_pair.get(
            (left.get("shot_id"), right.get("shot_id"))
        )
        evidence_path = ""
        adjudication_valid = False
        if isinstance(adjudication, dict):
            evidence_path = str(adjudication.get("evidence", "")).strip()
            evidence_exists = bool(evidence_path and Path(evidence_path).expanduser().is_file())
            adjudication_valid = bool(
                adjudication.get("status") == "PASS_ADJUDICATED"
                and str(adjudication.get("reason", "")).strip()
                and float(adjudication.get("confidence", 0.0)) >= 0.9
                and adjudication.get("raw_jump_preserved") is True
                and evidence_exists
            )
        passed = measured_pass or adjudication_valid
        if not measured_pass and adjudication_valid:
            adjudicated_count += 1
        comparisons.append({
            "scene_id": left.get("scene_id"),
            "left_shot": left.get("shot_id"),
            "right_shot": right.get("shot_id"),
            "luma_jump": jump,
            "measured_pass": measured_pass,
            "adjudication_valid": adjudication_valid,
            "adjudication": adjudication,
            "pass": passed,
        })
        if not passed:
            failures.append(f"scene_luma_jump:{left.get('shot_id')}->{right.get('shot_id')}:{jump:.2f}")
    return {
        "status": (
            "PASS_WITH_ADJUDICATION"
            if rows and not failures and adjudicated_count
            else "PASS" if rows and not failures else "FAIL"
        ),
        "max_luma_jump": max_jump,
        "rows": rows,
        "comparisons": comparisons,
        "adjudicated_count": adjudicated_count,
        "failures": failures,
    }


def source_brightness_audit_stats(payloads: List[Any], required: bool) -> Dict[str, Any]:
    failures: List[str] = []
    if required and not payloads:
        failures.append("source_brightness_audits_missing")
    rows = []
    for index, payload in enumerate(payloads):
        if not isinstance(payload, dict):
            failures.append(f"source_brightness_audit_invalid:{index}")
            continue
        status = payload.get("status")
        threshold = payload.get("fail_threshold")
        rows.append(
            {
                "video": payload.get("video"),
                "status": status,
                "fail_threshold": threshold,
                "max_adjacent_jump": payload.get("max_adjacent_jump"),
            }
        )
        if status != "PASS":
            failures.append(f"source_brightness_audit_not_pass:{index}:{status}")
        if threshold is None:
            failures.append(f"source_brightness_threshold_missing:{index}")
        elif float(threshold) > 25.0:
            failures.append(
                f"source_brightness_threshold_relaxed:{index}:{float(threshold):.3f}"
            )
    return {
        "status": "PASS" if not failures else "FAIL",
        "required": required,
        "audit_count": len(rows),
        "audits": rows,
        "failures": failures,
    }


def ocr_audit_stats(payload: Any) -> Dict[str, Any]:
    if payload is None:
        return {"status": "MISSING", "failures": ["ocr_audit_missing"]}
    uncommon_raw = payload.get("uncommon_chinese_chars", payload.get("uncommon_chars"))
    uncommon = int(uncommon_raw) if uncommon_raw is not None else None
    latin = int(payload.get("latin_chars", 0))
    critical_latin = int(payload.get("critical_latin_chars", latin))
    critical = int(payload.get("critical_text_failures", 0))
    failures: List[str] = []
    if uncommon is not None and uncommon:
        failures.append(f"ocr_uncommon_chinese_chars:{uncommon}")
    if uncommon is None and payload.get("uncommon_chinese_check") not in {
        "NOT_IMPLEMENTED_LEXICON_GATE_USED",
        "ALLOWLIST_CONTINUITY_GATE",
        "STRICT_MULTI_HAN_OR_CONTINUITY_GATE",
    }:
        failures.append("ocr_uncommon_chinese_check_missing")
    if not payload.get("lexicon_policy_configured", False):
        failures.append("ocr_lexicon_policy_missing")
    if critical_latin:
        failures.append(f"ocr_critical_latin_chars:{critical_latin}")
    if critical:
        failures.append(f"ocr_critical_text_failures:{critical}")
    return {
        **payload,
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
    }


def opening_audio_metrics(ffmpeg: str, video: Path, asr_payload: Any, seconds: float = 10.0) -> Dict[str, Any]:
    proc = run([
        ffmpeg, "-hide_banner", "-t", str(seconds), "-i", str(video),
        "-af", "volumedetect", "-f", "null", "-",
    ], check=False)
    text = proc.stderr + proc.stdout
    match = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", text)
    mean_volume = float(match.group(1)) if match else -99.0
    segments = []
    if isinstance(asr_payload, dict):
        segments = asr_payload.get("segments") or []
        if not segments and "rows" in asr_payload:
            for row in asr_payload.get("rows") or []:
                segments.extend(row.get("segments") or [])
    opening_speech_segments = [segment for segment in segments if float(segment.get("start", 9999)) < seconds]
    completed_opening_segments = [segment for segment in opening_speech_segments if float(segment.get("end", 9999)) <= seconds]
    completed_opening_cjk = sum(
        len(re.findall(r"[\u4e00-\u9fff]", str(segment.get("text", ""))))
        for segment in completed_opening_segments
    )
    return {
        "window_seconds": seconds,
        "mean_volume_db": mean_volume,
        "opening_speech_segment_count": len(opening_speech_segments),
        "completed_opening_speech_segments": len(completed_opening_segments),
        "completed_opening_cjk_chars": completed_opening_cjk,
        "status": "PASS" if mean_volume >= -32.0 and completed_opening_cjk >= 6 else "FAIL",
    }


def flatten_asr_segments(asr_payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(asr_payload, dict):
        return []
    segments = asr_payload.get("segments") or []
    if segments:
        return [segment for segment in segments if isinstance(segment, dict)]
    flattened: List[Dict[str, Any]] = []
    for row in asr_payload.get("rows") or []:
        flattened.extend(segment for segment in (row.get("segments") or []) if isinstance(segment, dict))
    return flattened


def speech_density_stats(
    asr_payload: Any,
    runtime: float,
    minimum_segments_per_minute: float = 15.0,
    redline_segments_per_minute: float = 10.0,
) -> Dict[str, Any]:
    segments = flatten_asr_segments(asr_payload)
    valid = []
    for segment in segments:
        text = str(segment.get("text", ""))
        if not re.search(r"[\u4e00-\u9fff]", text):
            continue
        start = max(0.0, float(segment.get("start", 0.0)))
        end = min(runtime, float(segment.get("end", start)))
        if end > start:
            valid.append({"start": start, "end": end, "text": text})
    density = len(valid) / (runtime / 60.0) if runtime else 0.0
    intervals = sorted((item["start"], item["end"]) for item in valid)
    merged: List[List[float]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    speech_seconds = sum(end - start for start, end in merged)
    coverage = speech_seconds / runtime if runtime else 0.0
    if not valid:
        status = "MISSING"
        failures = ["asr_speech_segments_missing"]
    elif density < redline_segments_per_minute:
        status = "FAIL"
        failures = [f"speech_density_redline:{density:.2f}"]
    elif density < minimum_segments_per_minute:
        status = "FAIL"
        failures = [f"speech_density_below_threshold:{density:.2f}"]
    else:
        status = "PASS"
        failures = []
    return {
        "status": status,
        "segment_count": len(valid),
        "segments_per_minute": density,
        "speech_coverage_ratio": coverage,
        "minimum_segments_per_minute": minimum_segments_per_minute,
        "redline_segments_per_minute": redline_segments_per_minute,
        "failures": failures,
    }


def zero_dialogue_contract_stats(adjustment_payload: Any, asr_payload: Any) -> Dict[str, Any]:
    """Constitute the strict zero-dialogue exception to speech-only CI checks."""
    policy = adjustment_payload.get("spoken_dialogue_policy") if isinstance(adjustment_payload, dict) else None
    transcript = asr_payload.get("transcript_segments") if isinstance(asr_payload, dict) else None
    valid = (
        isinstance(policy, dict)
        and policy.get("spoken_dialogue_count") == 0
        and policy.get("burned_dialogue_subtitle_count") == 0
        and adjustment_payload.get("canonical_script_unchanged") is True
        and str(adjustment_payload.get("status") or "").startswith("ACTIVE_SCRIPT_EQUIVALENT_NO_SPOKEN_DIALOGUE")
        and transcript == []
        and asr_payload.get("detected_spoken_dialogue_count") == 0
        and asr_payload.get("postdub_used") is False
    )
    return {
        "status": "PASS_NOT_APPLICABLE_ZERO_DIALOGUE" if valid else "NOT_REQUESTED_OR_INVALID",
        "valid": valid,
        "spoken_dialogue_count": policy.get("spoken_dialogue_count") if isinstance(policy, dict) else None,
        "asr_segment_count": len(transcript) if isinstance(transcript, list) else None,
    }


def freeze_stats(values: List[float], fps: float, freeze_motion: float, min_freeze_seconds: float, runtime: float) -> Dict[str, Any]:
    min_frames = max(1, int(round(fps * min_freeze_seconds)))
    frozen_runs: List[Dict[str, float]] = []
    run_start: int | None = None
    for index, value in enumerate(values):
        if value < freeze_motion:
            if run_start is None:
                run_start = index
        elif run_start is not None:
            length = index - run_start
            if length >= min_frames:
                frozen_runs.append({
                    "start_seconds": run_start / fps,
                    "duration_seconds": length / fps,
                })
            run_start = None
    if run_start is not None:
        length = len(values) - run_start
        if length >= min_frames:
            frozen_runs.append({
                "start_seconds": run_start / fps,
                "duration_seconds": length / fps,
            })
    frozen_total = sum(item["duration_seconds"] for item in frozen_runs)
    return {
        "freeze_motion_threshold": freeze_motion,
        "min_freeze_seconds": min_freeze_seconds,
        "frozen_runs": frozen_runs,
        "frozen_total_seconds": frozen_total,
        "freeze_ratio": frozen_total / runtime if runtime else 0.0,
    }


def scene_cut_times(ffmpeg: str, video: Path) -> List[float]:
    proc = run([
        ffmpeg,
        "-hide_banner",
        "-i", str(video),
        "-vf", "select='gt(scene,0.3)',showinfo",
        "-an",
        "-f", "null",
        "-",
    ], check=False)
    text = proc.stderr + proc.stdout
    times: List[float] = []
    for match in re.finditer(r"pts_time:([0-9.]+)", text):
        value = float(match.group(1))
        if value > 0.05:
            times.append(value)
    deduped: List[float] = []
    for value in sorted(times):
        if not deduped or abs(value - deduped[-1]) > 0.2:
            deduped.append(value)
    return deduped


def asl_stats(cuts: List[float], runtime: float) -> Dict[str, Any]:
    points = [0.0, *[cut for cut in cuts if 0.0 < cut < runtime], runtime]
    durations = [max(0.0, points[index + 1] - points[index]) for index in range(len(points) - 1)]
    durations = [item for item in durations if item > 0.05]
    if not durations:
        return {"segment_count": 0, "mean": None, "variance": None, "under_1s": None, "under_1s_ratio": None}
    return {
        "segment_count": len(durations),
        "mean": statistics.mean(durations),
        "variance": statistics.pvariance(durations) if len(durations) > 1 else 0.0,
        "under_1s": sum(1 for d in durations if d < 1.0),
        "under_1s_ratio": sum(1 for d in durations if d < 1.0) / len(durations),
        "durations": durations,
        "cut_times": cuts,
    }


def static_hold_stats(
    motion_values: List[float],
    fps: float,
    cuts: List[float],
    runtime: float,
    asr_payload: Any,
    motion_max: float = 1.5,
    seconds_max: float = 4.0,
) -> Dict[str, Any]:
    points = [0.0, *[cut for cut in cuts if 0.0 < cut < runtime], runtime]
    speech = flatten_asr_segments(asr_payload)
    failures: List[str] = []
    rows: List[Dict[str, Any]] = []
    for index in range(len(points) - 1):
        start = points[index]
        end = points[index + 1]
        duration = end - start
        if duration <= 0.05:
            continue
        has_speech = any(
            float(segment.get("start", 0.0)) < end
            and float(segment.get("end", segment.get("start", 0.0))) > start
            and re.search(r"[\u4e00-\u9fff]", str(segment.get("text", "")))
            for segment in speech
        )
        first = max(0, int(math.floor(start * fps)))
        last = min(len(motion_values), int(math.ceil(end * fps)))
        values = motion_values[first:last]
        mean_motion = statistics.mean(values) if values else 0.0
        row = {
            "shot_index": index + 1,
            "start_seconds": start,
            "end_seconds": end,
            "duration_seconds": duration,
            "mean_motion": mean_motion,
            "has_speech": has_speech,
        }
        if not has_speech and duration > seconds_max and mean_motion < motion_max:
            row["status"] = "FAIL_STATIC_HOLD"
            failures.append(
                f"unmotivated_static_hold:{index + 1}:{start:.3f}+{duration:.3f}:motion={mean_motion:.3f}"
            )
        else:
            row["status"] = "PASS"
        rows.append(row)
    return {
        "status": "PASS" if not failures else "FAIL",
        "motion_max": motion_max,
        "seconds_max": seconds_max,
        "shot_rows": rows,
        "failures": failures,
        "rule": "No-dialogue shot with mean adjacent-frame motion below 1.5 may exceed 4 seconds.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Qingshan final package regression CI.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--gate-registry", default=str(DEFAULT_GATE_REGISTRY))
    parser.add_argument("--episode-id")
    parser.add_argument("--segments-dir", help="Deprecated; ignored. CI measures final MP4 scene cuts.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--min-runtime", type=float, help="Optional canonical-manifest lower bound; no global runtime default.")
    parser.add_argument("--max-runtime", type=float, help="Optional canonical-manifest upper bound; no global runtime default.")
    parser.add_argument("--min-motion", type=float, default=FROZEN_THRESHOLDS["min_motion"])
    parser.add_argument("--redline-motion", type=float, default=FROZEN_THRESHOLDS["redline_motion"])
    parser.add_argument("--max-asl", type=float, default=FROZEN_THRESHOLDS["max_asl"])
    parser.add_argument("--redline-asl", type=float, default=FROZEN_THRESHOLDS["redline_asl"])
    parser.add_argument("--max-single-shot", type=float, default=FROZEN_THRESHOLDS["max_single_shot"])
    parser.add_argument(
        "--max-unmotivated-long-shots",
        type=int,
        default=FROZEN_THRESHOLDS["max_unmotivated_long_shots"],
    )
    parser.add_argument("--under1-min", type=float, default=FROZEN_THRESHOLDS["under1_min"])
    parser.add_argument("--under1-max", type=float, default=FROZEN_THRESHOLDS["under1_max"])
    parser.add_argument(
        "--report-only-metric",
        action="append",
        choices=("motion", "asl", "under1", "nonfight_under08"),
        default=[],
        help=(
            "Keep the frozen threshold and measured value, but record this metric as "
            "diagnostic instead of adding it to blocking failures. Repeatable."
        ),
    )
    parser.add_argument(
        "--freeze-ratio-max",
        type=float,
        default=FROZEN_THRESHOLDS["freeze_ratio_max"],
    )
    parser.add_argument("--freeze-motion", type=float, default=FROZEN_THRESHOLDS["freeze_motion"])
    parser.add_argument(
        "--min-freeze-seconds",
        type=float,
        default=FROZEN_THRESHOLDS["min_freeze_seconds"],
    )
    parser.add_argument(
        "--fps",
        type=float,
        help="Explicit canonical-manifest fps. If omitted, use the encoded source fps; never assume 30.",
    )
    parser.add_argument(
        "--near-duplicate-ratio-max",
        type=float,
        default=FROZEN_THRESHOLDS["near_duplicate_ratio_max"],
    )
    parser.add_argument(
        "--repeat-cluster-max",
        type=int,
        default=FROZEN_THRESHOLDS["repeat_cluster_max"],
    )
    parser.add_argument("--coverage-manifest-json")
    parser.add_argument("--require-forward-source-gates", action="store_true")
    parser.add_argument(
        "--approval-audit-file",
        action="append",
        help="Mailbox or Roger decision log used to verify shot-reconciliation approval_ref; repeatable.",
    )
    parser.add_argument("--threshold-authorization-ref")
    parser.add_argument(
        "--nonfight-under08-max",
        type=float,
        default=FROZEN_THRESHOLDS["nonfight_under08_max"],
    )
    parser.add_argument(
        "--digital-zero-db",
        type=float,
        default=FROZEN_THRESHOLDS["digital_zero_db"],
    )
    parser.add_argument(
        "--max-adjacent-rms-jump-db",
        type=float,
        default=FROZEN_THRESHOLDS["max_adjacent_rms_jump_db"],
    )
    parser.add_argument(
        "--min-unmotivated-silence-seconds",
        type=float,
        default=FROZEN_THRESHOLDS["min_unmotivated_silence_seconds"],
    )
    parser.add_argument(
        "--audio-boundary-json",
        help="Actual audio edit boundaries; prevents picture-only cuts from being misread as audio edits.",
    )
    parser.add_argument(
        "--static-hold-motion-max",
        type=float,
        default=FROZEN_THRESHOLDS["static_hold_motion_max"],
    )
    parser.add_argument(
        "--static-hold-seconds-max",
        type=float,
        default=FROZEN_THRESHOLDS["static_hold_seconds_max"],
    )
    parser.add_argument("--action-audit-json")
    parser.add_argument("--sentence-audit-json")
    parser.add_argument("--asr-json")
    parser.add_argument("--zero-dialogue-adjustment-json")
    parser.add_argument("--zero-dialogue-asr-json")
    parser.add_argument("--scene-brightness-json")
    parser.add_argument(
        "--source-brightness-audit-json",
        action="append",
        help="Source-level brightness-jump audit JSON; repeat for every admitted source.",
    )
    parser.add_argument("--require-source-brightness-audits", action="store_true")
    parser.add_argument("--ocr-audit-json")
    parser.add_argument("--min-speech-segments-per-minute", type=float, default=15.0)
    parser.add_argument("--redline-speech-segments-per-minute", type=float, default=10.0)
    parser.add_argument("--ffmpeg", default=default_ffmpeg())
    return parser


def main() -> int:
    args = build_parser().parse_args()
    gate_registry_integrity = gate_registry_integrity_stats(
        Path(args.gate_registry).expanduser().resolve()
    )

    video = Path(args.video).expanduser().resolve()
    if not video.exists():
        raise SystemExit(f"Missing video: {video}")
    if not args.ffmpeg or not Path(args.ffmpeg).exists():
        raise SystemExit("Missing ffmpeg. Use --ffmpeg or install ffmpeg.")
    ffmpeg = str(Path(args.ffmpeg).resolve())
    effective_fps = args.fps if args.fps is not None else source_video_fps(video, ffmpeg)

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="qingshan_regression_ci_") as tmp:
        tmp_root = Path(tmp)
        whole_duration = duration_seconds(video, ffmpeg)
        motion_metadata = tmp_root / "motion_metadata.txt"
        motion_values = adjacent_motion_values(ffmpeg, video, motion_metadata)
        whole_motion = statistics.mean(motion_values) if motion_values else 0.0
        freeze = freeze_stats(motion_values, effective_fps, args.freeze_motion, args.min_freeze_seconds, whole_duration)
        cuts = scene_cut_times(ffmpeg, video)
        asl = asl_stats(cuts, whole_duration)
        repeats = frame_repeat_stats(perceptual_hashes(ffmpeg, video))
        pure_black_frames = pure_black_frame_stats(ffmpeg, video)

    action_realtime = action_realtime_stats(load_json_optional(args.action_audit_json))
    sentence_audit = sentence_audit_stats(load_json_optional(args.sentence_audit_json))
    asr_payload = load_json_optional(args.asr_json)
    zero_dialogue_contract = zero_dialogue_contract_stats(
        load_json_optional(args.zero_dialogue_adjustment_json),
        load_json_optional(args.zero_dialogue_asr_json),
    )
    opening_audio = opening_audio_metrics(ffmpeg, video, asr_payload)
    speech_density = speech_density_stats(
        asr_payload,
        whole_duration,
        args.min_speech_segments_per_minute,
        args.redline_speech_segments_per_minute,
    )
    static_holds = static_hold_stats(
        motion_values,
        effective_fps,
        cuts,
        whole_duration,
        asr_payload,
        args.static_hold_motion_max,
        args.static_hold_seconds_max,
    )
    scene_brightness = scene_brightness_stats(load_json_optional(args.scene_brightness_json))
    source_brightness_audits = source_brightness_audit_stats(
        [
            load_json_optional(path)
            for path in (args.source_brightness_audit_json or [])
        ],
        args.require_source_brightness_audits,
    )
    ocr_audit = ocr_audit_stats(load_json_optional(args.ocr_audit_json))
    if zero_dialogue_contract["valid"] and ocr_audit.get("failures"):
        # A zero-dialogue cut has no dialogue-subtitle lexicon to configure.
        # OCR still blocks on unwanted Latin/numeric/critical text; only the
        # subtitle-specific lexicon prerequisite becomes not applicable.
        ocr_audit["failures"] = [
            failure for failure in ocr_audit["failures"]
            if failure != "ocr_lexicon_policy_missing"
        ]
        ocr_audit["status"] = "PASS_ZERO_DIALOGUE_NO_SUBTITLE_LEXICON" if not ocr_audit["failures"] else "FAIL"
    coverage_payload = load_json_optional(args.coverage_manifest_json)
    approval_audit_text = load_text_files(args.approval_audit_file)
    threshold_override = threshold_override_audit(args, approval_audit_text)
    source_manifest = source_manifest_stats(coverage_payload, args.require_forward_source_gates)
    nonfight_short_shots = nonfight_short_shot_stats(cuts, whole_duration, coverage_payload)
    shot_reconciliation = manifest_shot_reconciliation(
        cuts,
        whole_duration,
        coverage_payload,
        args.require_forward_source_gates,
        approval_audit_text,
    )
    audio_cuts, audio_boundary_source = resolve_audio_cut_times(
        load_json_optional(args.audio_boundary_json), cuts, whole_duration
    )
    audio_bed_continuity = audio_bed_continuity_stats(
        ffmpeg,
        video,
        audio_cuts,
        whole_duration,
        coverage_payload,
        args.digital_zero_db,
        args.max_adjacent_rms_jump_db,
        args.min_unmotivated_silence_seconds,
    )
    audio_bed_continuity["boundary_source"] = audio_boundary_source
    audio_bed_continuity["boundary_count"] = len(audio_cuts)

    failures: List[str] = []
    report_only_metrics = set(args.report_only_metric)
    report_only_findings: List[str] = []
    failures.extend(gate_registry_integrity["failures"])
    if args.min_runtime is not None and whole_duration < args.min_runtime:
        failures.append(f"runtime_below_canonical_minimum:{whole_duration:.2f}")
    if args.max_runtime is not None and whole_duration > args.max_runtime:
        failures.append(f"runtime_above_canonical_maximum:{whole_duration:.2f}")
    if whole_motion < args.redline_motion:
        finding = f"motion_redline:{whole_motion:.2f}"
        (report_only_findings if "motion" in report_only_metrics else failures).append(finding)
    elif whole_motion < args.min_motion:
        finding = f"motion_below_threshold:{whole_motion:.2f}"
        (report_only_findings if "motion" in report_only_metrics else failures).append(finding)
    if asl.get("mean") is not None:
        mean_asl = float(asl["mean"])
        if mean_asl > args.redline_asl:
            finding = f"asl_redline:{mean_asl:.2f}"
            (report_only_findings if "asl" in report_only_metrics else failures).append(finding)
        elif mean_asl > args.max_asl:
            finding = f"asl_above_threshold:{mean_asl:.2f}"
            (report_only_findings if "asl" in report_only_metrics else failures).append(finding)
    long_shots = [item for item in asl.get("durations", []) if item > args.max_single_shot]
    if len(long_shots) > args.max_unmotivated_long_shots:
        failures.append(f"too_many_long_shots:{len(long_shots)}")
    under1_ratio = asl.get("under_1s_ratio")
    if under1_ratio is not None and (under1_ratio < args.under1_min or under1_ratio > args.under1_max):
        finding = f"under1_ratio_out_of_range:{under1_ratio:.2f}"
        (report_only_findings if "under1" in report_only_metrics else failures).append(finding)
    if freeze["freeze_ratio"] > args.freeze_ratio_max:
        failures.append(f"freeze_ratio_above_threshold:{freeze['freeze_ratio']:.3f}")
    if repeats["near_duplicate_ratio"] > args.near_duplicate_ratio_max:
        failures.append(f"near_duplicate_ratio_above_threshold:{repeats['near_duplicate_ratio']:.3f}")
    if repeats["max_nonadjacent_repeat_cluster"] > args.repeat_cluster_max:
        failures.append(f"repeated_frame_cluster:{repeats['max_nonadjacent_repeat_cluster']}")
    failures.extend(pure_black_frames["failures"])
    if nonfight_short_shots["short_shot_ratio"] > args.nonfight_under08_max:
        finding = f"nonfight_under08_ratio_above_threshold:{nonfight_short_shots['short_shot_ratio']:.3f}"
        (report_only_findings if "nonfight_under08" in report_only_metrics else failures).append(finding)
    failures.extend(source_manifest["failures"])
    failures.extend(shot_reconciliation["failures"])
    failures.extend(threshold_override["failures"])
    failures.extend(audio_bed_continuity["failures"])
    failures.extend(action_realtime["failures"])
    if not zero_dialogue_contract["valid"]:
        failures.extend(sentence_audit["failures"])
        if opening_audio["status"] != "PASS":
            failures.append("opening_10s_speech_energy_fail")
        failures.extend(speech_density["failures"])
    failures.extend(static_holds["failures"])
    failures.extend(scene_brightness["failures"])
    failures.extend(source_brightness_audits["failures"])
    failures.extend(ocr_audit["failures"])

    report = {
        "schema": "qingshan.regression_ci.v1",
        "gate_registry_integrity": gate_registry_integrity,
        "video": str(video),
        "runtime_seconds": whole_duration,
        "fps": effective_fps,
        "fps_source": "canonical_manifest_override" if args.fps is not None else "encoded_source",
        "motion_mean": whole_motion,
        "motion_method": "ffmpeg tblend=all_mode=difference + signalstats YAVG on final MP4 native frames",
        "asl": asl,
        "freeze": freeze,
        "frame_repeat": repeats,
        "pure_black_frames": pure_black_frames,
        "source_manifest": source_manifest,
        "manifest_shot_reconciliation": shot_reconciliation,
        "nonfight_under08": nonfight_short_shots,
        "action_realtime": action_realtime,
        "asr_sentence_audit": sentence_audit,
        "opening_10s_speech_energy": opening_audio,
        "speech_density": speech_density,
        "zero_dialogue_contract": zero_dialogue_contract,
        "static_hold_gate": static_holds,
        "scene_brightness": scene_brightness,
        "source_brightness_audits": source_brightness_audits,
        "ocr_audit": ocr_audit,
        "audio_bed_continuity": audio_bed_continuity,
        "threshold_profile": FROZEN_THRESHOLD_PROFILE,
        "threshold_override_audit": threshold_override,
        "report_only_metrics": sorted(report_only_metrics),
        "report_only_findings": report_only_findings,
        "thresholds": {
            "min_runtime": args.min_runtime,
            "max_runtime": args.max_runtime,
            "min_motion": args.min_motion,
            "redline_motion": args.redline_motion,
            "max_asl": args.max_asl,
            "redline_asl": args.redline_asl,
            "max_single_shot": args.max_single_shot,
            "max_unmotivated_long_shots": args.max_unmotivated_long_shots,
            "under1_min": args.under1_min,
            "under1_max": args.under1_max,
            "freeze_ratio_max": args.freeze_ratio_max,
            "near_duplicate_ratio_max": args.near_duplicate_ratio_max,
            "repeat_cluster_max": args.repeat_cluster_max,
            "nonfight_under08_max": args.nonfight_under08_max,
            "digital_zero_db": args.digital_zero_db,
            "max_adjacent_rms_jump_db": args.max_adjacent_rms_jump_db,
            "min_unmotivated_silence_seconds": args.min_unmotivated_silence_seconds,
            "static_hold_motion_max": args.static_hold_motion_max,
            "static_hold_seconds_max": args.static_hold_seconds_max,
            "forward_source_gates_required": args.require_forward_source_gates,
            "source_brightness_audits_required": args.require_source_brightness_audits,
            "freeze_motion": args.freeze_motion,
            "min_freeze_seconds": args.min_freeze_seconds,
            "min_speech_segments_per_minute": args.min_speech_segments_per_minute,
            "redline_speech_segments_per_minute": args.redline_speech_segments_per_minute,
            "asl_variance": "report_only",
        },
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(out_path), "failures": failures}, ensure_ascii=False))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
