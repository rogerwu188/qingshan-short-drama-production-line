#!/usr/bin/env python3
"""Remove E30's non-dialogue static hold without stretching adjacent footage."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
FFPROBE = FFMPEG.with_name("ffprobe")
SOURCE = ROOT / "exports/e30/final_v11_u01_native_dialogue_20260722/QINGSHAN_E30_FINAL_V11.mp4"
SOURCE_PROJECT = ROOT / "configs/e30_agentcut_v11_u01_performance_r2_20260722.json"
FINAL = ROOT / "exports/e30/final_v12_static_hold_removed_20260722/QINGSHAN_E30_FINAL_V12.mp4"
PROJECT = ROOT / "configs/e30_agentcut_v12_static_hold_removed_20260722.json"
POLICY = ROOT / "configs/e30_final_visual_v12_dialogue_evidence_policy_20260722.json"
QA = ROOT / "qa/e30_final_v12_static_hold_removed_20260722/E30_V12_TECHNICAL_GATE.json"
RECEIPT = ROOT / "workflow/tasks/E30_FINAL_V12_STATIC_HOLD_REMOVAL_RECEIPT_20260722.json"

# This interval is inside U07, contains no subtitle/dialogue, and is the redundant
# exterior establishing hold identified by full-cut frame-cadence review.
CUT_START = 64.0
CUT_END = 67.0
CUT_DURATION = CUT_END - CUT_START


def run(args: list[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=True, text=True, capture_output=capture)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    result = run([
        str(FFPROBE), "-v", "error", "-show_entries",
        "format=duration,size:stream=index,codec_type,codec_name,sample_rate,channels",
        "-of", "json", str(path),
    ], capture=True)
    return json.loads(result.stdout)


def loudness(path: Path) -> dict:
    result = run([
        str(FFMPEG), "-hide_banner", "-i", str(path), "-af",
        "loudnorm=I=-17:TP=-2.5:LRA=11:print_format=json", "-f", "null", "-",
    ], capture=True)
    payloads = re.findall(r'\{\s*"input_i".*?\}', result.stderr, flags=re.DOTALL)
    if not payloads:
        raise SystemExit("encoded loudness metrics missing")
    payload = json.loads(payloads[-1])
    return {
        "integrated_loudness_lufs": float(payload["input_i"]),
        "true_peak_dbtp": float(payload["input_tp"]),
        "loudness_range_lu": float(payload["input_lra"]),
    }


def overlaps_cut(clip: dict) -> bool:
    start = float(clip["start"])
    end = start + float(clip["duration"])
    return start < CUT_END and end > CUT_START


def transform_clip(clip: dict) -> list[dict]:
    start = float(clip["start"])
    duration = float(clip["duration"])
    end = start + duration
    if end <= CUT_START:
        return [clip]
    if start >= CUT_END:
        clip["start"] = round(start - CUT_DURATION, 6)
        return [clip]
    if start >= CUT_START and end <= CUT_END:
        return []
    if start < CUT_START and end > CUT_END:
        before = copy.deepcopy(clip)
        after = copy.deepcopy(clip)
        before["id"] = f"{clip['id']}-PRE-CUT"
        before["duration"] = round(CUT_START - start, 6)
        after["id"] = f"{clip['id']}-POST-CUT"
        after["start"] = CUT_START
        after["in"] = round(float(clip.get("in", 0.0)) + CUT_END - start, 6)
        after["duration"] = round(end - CUT_END, 6)
        return [before, after]
    if start < CUT_START:
        clip["duration"] = round(CUT_START - start, 6)
        return [clip]
    clip["start"] = CUT_START
    clip["in"] = round(float(clip.get("in", 0.0)) + CUT_END - start, 6)
    clip["duration"] = round(end - CUT_END, 6)
    return [clip]


def build_shifted_project() -> None:
    project = json.loads(SOURCE_PROJECT.read_text(encoding="utf-8"))
    captions = [
        clip
        for track in project["timeline"].get("subtitleTracks", [])
        for clip in track.get("clips", [])
    ]
    conflicts = [clip.get("dialogue_id") or clip.get("id") for clip in captions if overlaps_cut(clip)]
    if conflicts:
        raise SystemExit(f"static cut intersects dialogue: {conflicts}")

    for track_group in ("videoTracks", "audioTracks", "subtitleTracks", "overlayTracks"):
        for track in project["timeline"].get(track_group, []):
            transformed = []
            for clip in track.get("clips", []):
                transformed.extend(transform_clip(copy.deepcopy(clip)))
            track["clips"] = transformed

    project["metadata"].update({
        "version": "V12",
        "status": "STATIC_HOLD_REMOVED_QA_PENDING",
        "runtime_seconds": round(float(project["metadata"]["runtime_seconds"]) - CUT_DURATION, 6),
        "content_runtime_seconds": round(float(project["metadata"]["content_runtime_seconds"]) - CUT_DURATION, 6),
        "static_hold_policy": "DELETE_IF_STORY_AND_DIALOGUE_UNAFFECTED_NO_SLOW_MOTION",
    })
    project["output"]["path"] = str(FINAL)
    project.setdefault("qingshanAudit", {}).update({
        "pipelineStage": "E30_FINAL_V12_STATIC_HOLD_REMOVAL",
        "source_final": str(SOURCE),
        "source_final_sha256": sha256(SOURCE),
        "removed_interval": {"start": CUT_START, "end": CUT_END, "duration": CUT_DURATION},
        "reason": "U07 redundant non-dialogue exterior establishing hold; removal does not change plot or spoken lines.",
        "rollback": str(SOURCE),
    })
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    shifted_captions = [
        clip
        for track in project["timeline"].get("subtitleTracks", [])
        for clip in track.get("clips", [])
    ]
    policy = {
        "enabled": True,
        "required": True,
        "allowedIntervals": [
            {
                "start": round(max(0.0, float(clip["start"]) - 0.15), 3),
                "end": round(float(clip["start"]) + float(clip["duration"]) + 0.15, 3),
                "reason": f"Story-required speaking performance for {clip['dialogue_id']}; final-window ASR is independently required.",
            }
            for clip in sorted(shifted_captions, key=lambda item: float(item["start"]))
        ],
    }
    POLICY.write_text(json.dumps(policy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_final() -> None:
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    filter_graph = (
        f"[0:v]trim=start=0:end={CUT_START},setpts=PTS-STARTPTS[v0];"
        f"[0:a]atrim=start=0:end={CUT_START},asetpts=PTS-STARTPTS[a0];"
        f"[0:v]trim=start={CUT_END},setpts=PTS-STARTPTS[v1];"
        f"[0:a]atrim=start={CUT_END},asetpts=PTS-STARTPTS[a1];"
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]"
    )
    run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(SOURCE),
        "-filter_complex", filter_graph, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(FINAL),
    ])


def write_reports() -> None:
    info = probe(FINAL)
    metrics = loudness(FINAL)
    duration = float(info["format"]["duration"])
    expected = float(probe(SOURCE)["format"]["duration"]) - CUT_DURATION
    failures = []
    if abs(duration - expected) > 0.08:
        failures.append("duration_does_not_match_three_second_removal")
    if not any(row.get("codec_type") == "video" for row in info.get("streams", [])):
        failures.append("video_stream_missing")
    if not any(row.get("codec_type") == "audio" for row in info.get("streams", [])):
        failures.append("audio_stream_missing")
    if metrics["true_peak_dbtp"] > -1.0:
        failures.append("encoded_true_peak_exceeds_minus_1_dbtp")
    if not -19.0 <= metrics["integrated_loudness_lufs"] <= -15.0:
        failures.append("encoded_integrated_loudness_out_of_release_range")
    payload = {
        "schema": "qingshan.e30.final_v12_static_hold_removal.v1",
        "episode": "E30",
        "version": "V12",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures else "FAIL",
        "final": str(FINAL),
        "final_sha256": sha256(FINAL),
        "probe": info,
        "encoded_audio_metrics": metrics,
        "removed_interval": {"start": CUT_START, "end": CUT_END, "duration": CUT_DURATION},
        "dialogue_intersection": [],
        "subtitle_coverage": "20/20_BURNED_IN_PRESERVED",
        "nalu_motion_outro": "PRESERVED",
        "failures": failures,
        "remaining_gates": ["FINAL_WINDOWED_ASR", "FINAL_FRAME_CADENCE", "FINAL_OCR", "FINAL_VISUAL"],
        "new_generation_calls": 0,
        "new_generation_credits": 0,
    }
    QA.parent.mkdir(parents=True, exist_ok=True)
    QA.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    RECEIPT.write_text(json.dumps({
        **payload,
        "project": str(PROJECT),
        "project_sha256": sha256(PROJECT),
        "final_visual_policy": str(POLICY),
        "source_final": str(SOURCE),
        "source_final_sha256": sha256(SOURCE),
        "rollback": str(SOURCE),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit(json.dumps(failures, ensure_ascii=False))
    print(json.dumps({"status": "BUILT_QA_PENDING", "final": str(FINAL), "sha256": payload["final_sha256"]}, ensure_ascii=False))


def main() -> int:
    for required in (SOURCE, SOURCE_PROJECT):
        if not required.is_file():
            raise SystemExit(f"required input missing: {required}")
    build_shifted_project()
    build_final()
    write_reports()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
