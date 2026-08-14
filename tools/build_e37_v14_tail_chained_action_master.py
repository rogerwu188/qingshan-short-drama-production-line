#!/usr/bin/env python3
"""Build the E37 V14 fixed-camera action chain and bind it into AgentCut V13."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
BATCH = ROOT / "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/action_replacement_v4/E37_TAIL_CHAINED_ACTION_REPLACEMENT_BATCH_V4.json"
PARENT = ROOT / "configs/e37_agentcut_v13_spectral_masking_repair_20260804.json"
OUT_DIR = ROOT / "working_assets/e37_action_replacement_v4_20260803/accepted_action_sequence_v14"
SEQUENCE = OUT_DIR / "E37_ACCEPTED_TAIL_CHAINED_ACTION_SEQUENCE_V14.mp4"
RAW_SEQUENCE = OUT_DIR / "E37_ACCEPTED_TAIL_CHAINED_ACTION_SEQUENCE_V14_RAW.mp4"
DEDUP_VIDEO = OUT_DIR / "E37_ACCEPTED_TAIL_CHAINED_ACTION_SEQUENCE_V14_DEDUP_VIDEO.mp4"
CONFIG = ROOT / "configs/e37_agentcut_v14_tail_chained_action_bgm_subtitles_outro_20260804.json"
CADENCE = ROOT / "qa/e37_action_replacement_v4_20260803/E37_ACCEPTED_TAIL_CHAINED_ACTION_SEQUENCE_V14_FRAME_CADENCE.json"
FIXED_CUT_DIR = ROOT / "working_assets/e37_dialogue_fixed_composition_recuts_v14_20260804"
OLD_ACTION_END = 93.44
SHOT_WINDOWS = {
    "E37-R-B01": (0.0, 1.8),
    "E37-R-B02": (0.0, 1.8),
    "E37-R-B03": (0.0, 1.8),
    "E37-R-B04": (0.0, 0.75),
    "E37-R-B05": (0.3, 1.0),
    "E37-R-B06": (0.0, 0.25),
    "E37-R-B07": (0.0, 1.5),
    "E37-R-B08": (0.0, 0.9),
}
FIXED_DIALOGUE_CUTS = {
    "E37-L007-PER-CAPTION-VIDEO-V1": {
        "audio_id": "E37-L007-PER-CAPTION-AUDIO-V1",
        "source": ROOT / "working_assets/e37_video_20260803/v7_per_caption_agentcut_assets_v1/E37_L007_PER_CAPTION_NATIVE_V1.mp4",
        "output": FIXED_CUT_DIR / "E37_L007_TWO_FIXED_COMPOSITIONS_V14.mp4",
    },
    "E37-L024-PER-CAPTION-VIDEO-V1": {
        "audio_id": "E37-L024-PER-CAPTION-AUDIO-V1",
        "source": ROOT / "working_assets/e37_video_20260803/v7_per_caption_agentcut_assets_v1/E37_L024_PER_CAPTION_NATIVE_V1.mp4",
        "output": FIXED_CUT_DIR / "E37_L024_TWO_FIXED_COMPOSITIONS_V14.mp4",
    },
}


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


def build_fixed_dialogue_cut(source: Path, output: Path) -> Path:
    """Replace a long static take with two motivated fixed compositions."""
    source_duration = duration(source)
    midpoint = source_duration / 2.0
    output.parent.mkdir(parents=True, exist_ok=True)
    filtergraph = (
        f"[0:v]trim=start=0:end={midpoint:.6f},setpts=PTS-STARTPTS[v0];"
        f"[0:v]trim=start={midpoint:.6f}:end={source_duration:.6f},"
        "crop=600:1066:60:107,scale=720:1280,setpts=PTS-STARTPTS[v1];"
        "[v0][v1]concat=n=2:v=1:a=0,fps=24[v];"
        f"[0:a]atrim=start=0:end={midpoint:.6f},asetpts=PTS-STARTPTS[a0];"
        f"[0:a]atrim=start={midpoint:.6f}:end={source_duration:.6f},asetpts=PTS-STARTPTS[a1];"
        "[a0][a1]concat=n=2:v=0:a=1[a]"
    )
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-y", "-i", str(source),
        "-filter_complex", filtergraph, "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output),
    ], check=True)
    return output


def main() -> None:
    batch = json.loads(BATCH.read_text())
    sources = []
    authored_starts = []
    authored_durations = []
    for task in batch["tasks"]:
        source = task.get("accepted_source") or task.get("accepted_output_path")
        if not source:
            raise SystemExit(f"Missing accepted source: {task['task_key']}")
        path = ROOT / source
        if not path.is_file():
            raise SystemExit(f"Accepted source missing: {path}")
        sources.append(path)
        start, shot_duration = SHOT_WINDOWS[task["source_id"]]
        authored_starts.append(start)
        authored_durations.append(shot_duration)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    command = [str(FFMPEG), "-hide_banner", "-y"]
    for source in sources:
        command += ["-i", str(source)]
    trim_filters = []
    for index, (trim_start, trim_duration) in enumerate(zip(authored_starts, authored_durations)):
        trim_filters.append(
            f"[{index}:v]trim=start={trim_start}:duration={trim_duration},setpts=PTS-STARTPTS[v{index}]"
        )
        trim_filters.append(
            f"[{index}:a]atrim=start={trim_start}:duration={trim_duration},asetpts=PTS-STARTPTS[a{index}]"
        )
    video_inputs = "".join(f"[v{i}]" for i in range(len(sources)))
    audio_inputs = "".join(f"[a{i}]" for i in range(len(sources)))
    filtergraph = ";".join(trim_filters) + ";" + (
        f"{video_inputs}concat=n={len(sources)}:v=1:a=0,fps=24,setpts=PTS-STARTPTS[v];"
        f"{audio_inputs}concat=n={len(sources)}:v=0:a=1,asetpts=PTS-STARTPTS[a]"
    )
    command += [
        "-filter_complex", filtergraph,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(RAW_SEQUENCE),
    ]
    subprocess.run(command, check=True)
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-y", "-i", str(RAW_SEQUENCE),
        "-an", "-vf", "mpdecimate,setpts=N/(24*TB)", "-r", "24",
        "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p",
        str(DEDUP_VIDEO),
    ], check=True)

    fixed_cut_evidence = {}
    for video_id, spec in FIXED_DIALOGUE_CUTS.items():
        output = build_fixed_dialogue_cut(spec["source"], spec["output"])
        report = ROOT / f"qa/e37_agentcut_20260804/{output.stem}_CADENCE.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            str(ROOT / ".agentcut_env/bin/python"), str(ROOT / "tools/frame_cadence_audit.py"),
            "--video", str(output), "--out", str(report),
            "--audit-scope", "VIDEO_ONLY_DIAGNOSTIC",
        ], check=True)
        fixed_cut_evidence[video_id] = {"output": output, "report": report}
    compact_duration = duration(DEDUP_VIDEO)
    tempo = duration(RAW_SEQUENCE) / compact_duration
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-y", "-i", str(DEDUP_VIDEO), "-i", str(RAW_SEQUENCE),
        "-map", "0:v:0", "-map", "1:a:0", "-filter:a", f"atempo={tempo:.9f}",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
        str(SEQUENCE),
    ], check=True)
    action_duration = video_duration(SEQUENCE)
    CADENCE.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(ROOT / ".agentcut_env/bin/python"),
        str(ROOT / "tools/frame_cadence_audit.py"),
        "--video", str(SEQUENCE),
        "--out", str(CADENCE),
        "--audit-scope", "VIDEO_ONLY_DIAGNOSTIC",
    ], check=True)

    project = json.loads(PARENT.read_text())
    project = copy.deepcopy(project)
    project["metadata"]["status"] = "V14_TAIL_CHAINED_ACTION_BOUND_NOT_FINAL"
    project["metadata"]["parent_project"] = str(PARENT)
    project["metadata"]["parent_project_sha256"] = sha256(PARENT)
    project["metadata"]["v14_tail_chained_action"] = {
        "status": "BOUND_ACCEPTED_ONLY",
        "source": str(SEQUENCE),
        "source_sha256": sha256(SEQUENCE),
        "task_order": [task["task_key"] for task in batch["tasks"]],
        "authored_clip_starts_seconds": authored_starts,
        "authored_clip_durations_seconds": authored_durations,
        "tempo": "REAL_TIME_1X",
        "camera_policy": "FIXED_COMPOSITION_NO_GRATUITOUS_ROAM",
        "duration_seconds": action_duration,
        "timeline_delta_seconds": action_duration - 31.16,
        "duplicate_hold_compaction": {"method": "mpdecimate_only", "audio_atempo": tempo},
    }
    project["output"]["path"] = str(
        ROOT / "exports/e37/agentcut_v14_tail_chained_action_20260804/E37_AGENTCUT_V14_TAIL_CHAINED_ACTION_BGM_SUBTITLES_NALU_OUTRO_NOT_FINAL.mp4"
    )

    replaced = 0
    for clip in project["timeline"]["videoTracks"][0]["clips"]:
        if clip["id"] == "E37-U04-U06-S1-ACTION-CANONICAL-REPLACEMENT-V4":
            clip["id"] = "E37-U04-U06-S1-TAIL-CHAINED-ACTION-V14"
            clip["source"] = str(SEQUENCE)
            clip["in"] = 0.0
            clip["duration"] = action_duration
            clip["cutReason"] = "B01-B08 accepted-only tail-frame chained causal action replacement"
            metadata = clip.setdefault("metadata", {})
            metadata["admission"] = "PASS_ACCEPTED_TAIL_CHAINED_ACTION_V14"
            metadata["source_sha256"] = sha256(SEQUENCE)
            metadata["cadence_report_path"] = str(CADENCE)
            metadata["cadence_report_sha256"] = sha256(CADENCE)
            metadata["camera_policy"] = "FIXED_COMPOSITION_NO_OPTICAL_SWAY"
            replaced += 1
    for clip in project["timeline"]["audioTracks"][0]["clips"]:
        if clip["id"] == "E37-U04-U06-S1-ACTION-CANONICAL-REPLACEMENT-V4-AUDIO":
            clip["id"] = "E37-U04-U06-S1-TAIL-CHAINED-ACTION-V14-AUDIO"
            clip["source"] = str(SEQUENCE)
            clip["in"] = 0.0
            clip["duration"] = action_duration - 0.001
            replaced += 1
    if replaced != 2:
        raise SystemExit(f"Expected two action bindings, replaced {replaced}")

    fixed_video_bindings = 0
    for clip in project["timeline"]["videoTracks"][0]["clips"]:
        evidence = fixed_cut_evidence.get(clip["id"])
        if not evidence:
            continue
        clip["source"] = str(evidence["output"])
        clip["cutReason"] = "dialogue beat hard-cut between two fixed compositions; no camera roam"
        metadata = clip.setdefault("metadata", {})
        metadata["source_sha256"] = sha256(evidence["output"])
        metadata["cadence_report_path"] = str(evidence["report"])
        metadata["cadence_report_sha256"] = sha256(evidence["report"])
        metadata["camera_policy"] = "TWO_FIXED_COMPOSITIONS_NO_CONTINUOUS_MOTION"
        fixed_video_bindings += 1
    fixed_audio_bindings = 0
    for clip in project["timeline"]["audioTracks"][0]["clips"]:
        for video_id, spec in FIXED_DIALOGUE_CUTS.items():
            if clip["id"] == spec["audio_id"]:
                clip["source"] = str(fixed_cut_evidence[video_id]["output"])
                fixed_audio_bindings += 1
    if fixed_video_bindings != len(FIXED_DIALOGUE_CUTS) or fixed_audio_bindings != len(FIXED_DIALOGUE_CUTS):
        raise SystemExit(
            f"Expected {len(FIXED_DIALOGUE_CUTS)} fixed dialogue A/V bindings, "
            f"got video={fixed_video_bindings}, audio={fixed_audio_bindings}"
        )

    delta = action_duration - 31.16
    for track_group in ("videoTracks", "audioTracks", "subtitleTracks"):
        for track in project["timeline"].get(track_group, []):
            for clip in track.get("clips", []):
                if clip.get("start", 0.0) >= OLD_ACTION_END:
                    clip["start"] = round(clip["start"] + delta, 6)
    for clip in project["timeline"]["audioTracks"][1]["clips"]:
        if clip["id"] == "E37-BGM-ACTION":
            clip["duration"] = max(0.5, action_duration - 0.16)
    project["metadata"]["runtime_seconds"] = round(project["metadata"]["runtime_seconds"] + delta, 6)
    project["outro"]["duration"] = 2.0

    CONFIG.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({
        "sequence": str(SEQUENCE),
        "sequence_sha256": sha256(SEQUENCE),
        "project": str(CONFIG),
        "project_sha256": sha256(CONFIG),
        "accepted_sources": len(sources),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
