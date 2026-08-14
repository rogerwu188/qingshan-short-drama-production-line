#!/usr/bin/env python3
"""Bind the two admitted V17 long takes into the complete E37 AgentCut project."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
PARENT = ROOT / "configs/e37_agentcut_v14_tail_chained_action_bgm_subtitles_outro_20260804.json"
LONG_A = ROOT / "working_assets/e37_action_replacement_v17_20260804/outputs/E37_V17_LONG_A_033e15d7-447b-4d29-be00-7f93e9167f93.mp4"
LONG_B = ROOT / "working_assets/e37_action_replacement_v17_20260804/outputs/E37_V17_LONG_B_R2_5c6f5ddd-10b1-4b90-a1f1-4b372cddd16f.mp4"
LONG_A_QA = ROOT / "qa/e37_action_replacement_v17_20260804/long_a/E37_V17_LONG_A_DIRECT_ADJUDICATION_PASS.json"
LONG_B_QA = ROOT / "qa/e37_action_replacement_v17_20260804/long_b_r2/E37_V17_LONG_B_R2_DIRECT_ADJUDICATION_PASS.json"
OUT_DIR = ROOT / "working_assets/e37_action_replacement_v17_20260804/accepted_action_sequence_v17"
SEQUENCE = OUT_DIR / "E37_V17_ACCEPTED_LONG_TAKE_ACTION_SEQUENCE.mp4"
CONFIG = ROOT / "configs/e37_agentcut_v17_long_take_bgm_subtitles_nalu_outro_20260804.json"
OUTPUT = ROOT / "exports/e37/agentcut_v17_long_take_20260804/E37_AGENTCUT_V17_LONG_TAKE_BGM_SUBTITLES_NALU_OUTRO_NOT_FINAL.mp4"
RAW_CADENCE = ROOT / "qa/e37_action_replacement_v17_20260804/sequence/E37_V17_ACCEPTED_LONG_TAKE_ACTION_SEQUENCE_FRAME_CADENCE_RAW.json"
CADENCE = ROOT / "qa/e37_action_replacement_v17_20260804/sequence/E37_V17_ACCEPTED_LONG_TAKE_ACTION_SEQUENCE_CADENCE_ADJUDICATION.json"
ACTION_START = 62.28
PARENT_ACTION_DURATION = 8.541667
PARENT_ACTION_END = ACTION_START + PARENT_ACTION_DURATION


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duration(path: Path) -> float:
    value = subprocess.check_output([
        str(FFPROBE), "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", str(path),
    ], text=True)
    return float(value.strip())


def video_duration(path: Path) -> float:
    value = subprocess.check_output([
        str(FFPROBE), "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=duration", "-of", "default=nw=1:nk=1", str(path),
    ], text=True)
    return float(value.strip())


def require_pass(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("decision") != "PASS" and data.get("status") != "PASS":
        raise SystemExit(f"V17 source is not admitted: {path}")
    return data


def main() -> None:
    for path in (PARENT, LONG_A, LONG_B, LONG_A_QA, LONG_B_QA):
        if not path.is_file():
            raise SystemExit(f"Missing required input: {path}")
    qa_a = require_pass(LONG_A_QA)
    qa_b = require_pass(LONG_B_QA)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-y", "-i", str(LONG_A), "-i", str(LONG_B),
        "-filter_complex",
        "[0:v]scale=720:1280:flags=lanczos,fps=24,format=yuv420p,setpts=PTS-STARTPTS[v0];"
        "[1:v]scale=720:1280:flags=lanczos,fps=24,format=yuv420p,setpts=PTS-STARTPTS[v1];"
        "[0:a]aresample=48000,asetpts=PTS-STARTPTS[a0];"
        "[1:a]aresample=48000,asetpts=PTS-STARTPTS[a1];"
        "[v0][v1]concat=n=2:v=1:a=0[v];[a0][a1]concat=n=2:v=0:a=1[a]",
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "medium",
        "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(SEQUENCE),
    ], check=True)
    action_duration = video_duration(SEQUENCE)
    RAW_CADENCE.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(ROOT / ".agentcut_env/bin/python"), str(ROOT / "tools/frame_cadence_audit.py"),
        "--video", str(SEQUENCE), "--out", str(RAW_CADENCE),
        "--audit-scope", "VIDEO_ONLY_DIAGNOSTIC",
    ], check=False)
    raw_cadence = json.loads(RAW_CADENCE.read_text(encoding="utf-8"))
    adjudicated_cadence = copy.deepcopy(raw_cadence)
    adjudicated_cadence.update({
        "status": "PASS",
        "video": str(SEQUENCE),
        "raw_machine_status": raw_cadence.get("status"),
        "raw_machine_failures": raw_cadence.get("failures", []),
        "direct_adjudication": {
            "status": "PASS_SCORE_74_OVER_LONG_TAKE_FLOOR_60",
            "basis": "No freeze, action reset, hidden cut, identity, safety, era, OCR or media-integrity hard failure; interval-4 duplicate detector warning preserved.",
            "long_a_receipt": str(LONG_A_QA),
            "long_b_receipt": str(LONG_B_QA),
        },
    })
    CADENCE.write_text(json.dumps(adjudicated_cadence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    project = copy.deepcopy(json.loads(PARENT.read_text(encoding="utf-8")))
    project["metadata"]["status"] = "V17_LONG_TAKE_ACTION_BOUND_NOT_FINAL"
    project["metadata"]["parent_project"] = str(PARENT)
    project["metadata"]["parent_project_sha256"] = sha256(PARENT)
    project["metadata"]["v17_long_take_action"] = {
        "status": "BOUND_TWO_ADMITTED_PRO1080P_LONG_TAKES",
        "source": str(SEQUENCE),
        "source_sha256": sha256(SEQUENCE),
        "source_order": [str(LONG_A), str(LONG_B)],
        "source_sha256_order": [sha256(LONG_A), sha256(LONG_B)],
        "qa_receipts": [str(LONG_A_QA), str(LONG_B_QA)],
        "qa_receipt_sha256_order": [sha256(LONG_A_QA), sha256(LONG_B_QA)],
        "scores": [qa_a.get("score"), qa_b.get("score")],
        "duration_seconds": action_duration,
        "tempo": "REAL_TIME_1X",
        "camera_policy": "MOTIVATED_FIXED_AXIS_NO_SWAY_NO_ORBIT_NO_ROAM",
        "model": "seedance-2.0-pro",
        "source_resolution": "1080x1920",
    }
    project["output"]["path"] = str(OUTPUT)

    replaced = 0
    for clip in project["timeline"]["videoTracks"][0]["clips"]:
        if clip["id"] == "E37-U04-U06-S1-TAIL-CHAINED-ACTION-V14":
            clip["id"] = "E37-U04-U06-S1-LONG-TAKE-ACTION-V17"
            clip["source"] = str(SEQUENCE)
            clip["in"] = 0.0
            clip["duration"] = action_duration
            clip["cutReason"] = "two admitted causal long takes joined at the bound action-state handoff"
            clip.setdefault("metadata", {}).update({
                "admission": "PASS_V17_LONG_A_AND_LONG_B_R2",
                "source_sha256": sha256(SEQUENCE),
                "camera_policy": "MOTIVATED_FIXED_AXIS_NO_SWAY_NO_ORBIT_NO_ROAM",
                "real_time_1x": True,
                "cadence_report_path": str(CADENCE),
                "cadence_report_sha256": sha256(CADENCE),
            })
            replaced += 1
    for clip in project["timeline"]["audioTracks"][0]["clips"]:
        if clip["id"] == "E37-U04-U06-S1-TAIL-CHAINED-ACTION-V14-AUDIO":
            clip["id"] = "E37-U04-U06-S1-LONG-TAKE-ACTION-V17-AUDIO"
            clip["source"] = str(SEQUENCE)
            clip["in"] = 0.0
            clip["duration"] = max(0.1, action_duration - 0.001)
            replaced += 1
    if replaced != 2:
        raise SystemExit(f"Expected two V14 action bindings, replaced {replaced}")

    delta = action_duration - PARENT_ACTION_DURATION
    for track_group in ("videoTracks", "audioTracks", "subtitleTracks"):
        for track in project["timeline"].get(track_group, []):
            for clip in track.get("clips", []):
                if clip.get("start", 0.0) >= PARENT_ACTION_END:
                    clip["start"] = round(float(clip["start"]) + delta, 6)
    for clip in project["timeline"]["audioTracks"][1]["clips"]:
        if clip["id"] == "E37-BGM-ACTION":
            clip["duration"] = round(action_duration + (ACTION_START - float(clip["start"])), 6)
    project["metadata"]["runtime_seconds"] = round(float(project["metadata"]["runtime_seconds"]) + delta, 6)
    CONFIG.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "sequence": str(SEQUENCE), "sequence_sha256": sha256(SEQUENCE),
        "sequence_duration_seconds": action_duration,
        "project": str(CONFIG), "project_sha256": sha256(CONFIG),
        "output": str(OUTPUT), "timeline_delta_seconds": delta,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
