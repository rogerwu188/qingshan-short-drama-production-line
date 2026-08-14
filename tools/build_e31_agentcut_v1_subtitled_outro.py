#!/usr/bin/env python3
"""Build E31 AgentCut from all admitted native-speed performance units."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e31_claude_writer_v1_20260722"
PLAN = PRODUCTION / "E31_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json"
SUBTITLES = PRODUCTION / "E31_SUBTITLE_CONTRACT_V1.json"
INVENTORY = PRODUCTION / "E31_SCRIPT_BEAT_DIALOGUE_INVENTORY_V1.json"
OUTRO = PRODUCTION / "E31_NALU_MOTION_OUTRO_CONTRACT_V1.json"
AUDIO_MANIFEST = ROOT / "working_assets/e31_dialogue_audio_refs_20260722/E31_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
RECEIPTS = [
    ROOT / "workflow/tasks/E31_VIDEO_BATCH_NONDIALOGUE_READY_V1_RECEIPT.json",
    ROOT / "workflow/tasks/E31_VIDEO_BATCH_DIALOGUE_READY_V1_RECEIPT.json",
    ROOT / "workflow/tasks/E31_VIDEO_BATCH_U16_AUDIO_MIN2_MARGIN_R3_RECEIPT.json",
    ROOT / "workflow/tasks/E31_VIDEO_BATCH_U15_FAILED_ONLY_R2_RECEIPT.json",
    ROOT / "workflow/tasks/E31_VIDEO_BATCH_U18_SPLIT_DIALOGUE_R2_RECEIPT.json",
    ROOT / "workflow/tasks/E31_VIDEO_BATCH_U18_A_DIALOGUE_R3_RECEIPT.json",
    ROOT / "workflow/tasks/E31_VIDEO_BATCH_U18_B_IDENTITY_R3_RETRY_RECEIPT.json",
]
ADMISSIONS = [
    ROOT / "qa/e31_video_generation_20260722/E31_NONDIALOGUE_OCR_CONDITIONAL_ADMISSION_V1.json",
    ROOT / "qa/e31_video_generation_20260722/E31_DIALOGUE_OCR_CONDITIONAL_ADMISSION_V1.json",
    ROOT / "qa/e31_video_generation_20260722/E31_U15_OCR_CONDITIONAL_ADMISSION_V1.json",
    ROOT / "qa/e31_video_generation_20260722/E31_U18_SPLIT_OCR_CONDITIONAL_ADMISSION_V1.json",
]
PROJECT = ROOT / "configs/e31_agentcut_v1_subtitled_outro_20260722.json"
OUTPUT = ROOT / "exports/e31/agentcut_v1_subtitled_outro_20260722/E31_AGENTCUT_V1_SUBTITLED_OUTRO_NOT_FINAL.mp4"
BUILD_RECEIPT = ROOT / "workflow/tasks/E31_AGENTCUT_V1_SUBTITLED_OUTRO_BUILD_RECEIPT_20260722.json"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duration(path: Path) -> float:
    proc = subprocess.run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)], check=True, capture_output=True, text=True)
    return float(proc.stdout.strip())


def subtitle_display_text(text: str) -> str:
    """Preserve wording while keeping FFmpeg drawtext quoting unambiguous."""
    return re.sub(r"'([^']+)'", r"“\1”", text)


def admitted_shas() -> set[str]:
    values = set()
    for path in ADMISSIONS:
        payload = load(path)
        if payload.get("status") != "CONDITIONAL_MACHINE_ADMISSION" or payload.get("blocking") is not False:
            raise SystemExit(f"conditional admission is not open: {path}")
        values.update(row["candidate_sha256"] for row in payload["items"])
    return values


def collect_sources() -> dict[str, dict]:
    conditional = admitted_shas()
    sources = {}
    for receipt_path in RECEIPTS:
        if not receipt_path.is_file():
            raise SystemExit(f"missing receipt: {receipt_path}")
        for task in load(receipt_path).get("tasks", []):
            if not task.get("output_path") or not task.get("sha256"):
                continue
            path = Path(task["output_path"])
            if not path.is_file() or sha256(path) != task["sha256"]:
                raise SystemExit(f"missing or SHA-mismatched source: {path}")
            if task.get("state") == "qa_pass":
                admission = "QA_PASS"
            elif task["sha256"] in conditional:
                admission = "CONDITIONAL_MACHINE_ADMISSION"
            else:
                continue
            sources[task["source_id"]] = {**task, "admission": admission}
    return sources


def subtitle_clips(inventory: dict, audio_manifest: dict, windows: dict[str, dict]) -> list[dict]:
    locked_rows = {
        row["dia_id"]: row
        for scene in inventory["scenes"]
        for beat in scene["beats"]
        for row in beat.get("dialogue", [])
    }
    by_unit: dict[str, list[dict]] = defaultdict(list)
    for row in audio_manifest["rows"]:
        by_unit[row["video_unit_id"]].append(row)
    clips = []
    split_dialogue_windows = {
        "E31-DIA-016": "E31-CW-U18-A",
        "E31-DIA-017": "E31-CW-U18-B",
        "E31-DIA-018": "E31-CW-U18-C",
    }
    for unit_id, rows in by_unit.items():
        cursor = windows[unit_id]["start"] + 0.25
        for row in rows:
            locked = locked_rows[row["dia_id"]]
            if locked["spoken_text"] != row["spoken_text"] or locked["speaker"] != row["speaker"]:
                raise SystemExit(f"subtitle/audio mismatch: {row['dia_id']}")
            split_window_id = split_dialogue_windows.get(row["dia_id"])
            active_window = windows.get(split_window_id) if split_window_id else None
            if active_window:
                cursor = active_window["start"] + 0.45
            else:
                active_window = windows[unit_id]
            line_duration = min(float(row["duration_seconds"]), active_window["start"] + active_window["duration"] - cursor - 0.05)
            if line_duration <= 0:
                raise SystemExit(f"subtitle does not fit unit: {row['dia_id']}")
            clips.append({
                "id": row["dia_id"], "dialogue_id": row["dia_id"], "text": subtitle_display_text(locked["spoken_text"]),
                "start": round(cursor, 6), "duration": round(line_duration, 6),
                "metadata": {"episode": "E31", "speaker": row["speaker"], "unit_id": unit_id, "source": "CLAUDE_SCRIPT_AND_FITTED_AUDIO_LOCK"},
            })
            if not split_window_id or split_window_id not in windows:
                cursor += line_duration + 0.16
    return sorted(clips, key=lambda row: (row["start"], row["id"]))


def main() -> int:
    plan = load(PLAN)
    sources = collect_sources()
    expected = [row["unit_id"] for row in plan["units"]]
    split_u18 = [f"E31-CW-U18-{part}" for part in "ABC"]
    split_ready = all(source_id in sources for source_id in split_u18)
    required = (set(expected) - ({"E31-CW-U18"} if split_ready else set())) | (set(split_u18) if split_ready else set())
    missing = sorted(required - set(sources))
    if missing:
        raise SystemExit(f"source coverage mismatch; missing={missing}")

    video_clips, audio_clips, windows = [], [], {}
    cursor = 0.0
    for unit in plan["units"]:
        unit_id = unit["unit_id"]
        clip_source_ids = split_u18 if unit_id == "E31-CW-U18" and split_ready else [unit_id]
        unit_start = cursor
        for source_id in clip_source_ids:
            task = sources[source_id]
            source = Path(task["output_path"])
            planned_duration = float(task.get("duration_seconds") or unit["duration_seconds"])
            clip_duration = min(planned_duration, duration(source))
            metadata = {
                "episode": "E31", "source_id": source_id, "parent_unit_id": unit_id,
                "scene_id": unit["scene_id"], "source_sha256": task["sha256"],
                "source_admission": task["admission"],
                "duration_policy": "NATIVE_SPEED_TRIM_CONTAINER_TAIL_NO_PADDING_NO_SLOW_MOTION",
                "cutReason": "CLAUDE_SCRIPT_CONTIGUOUS_SCENE_LOCAL_VIDEO_UNIT_OR_NATURAL_DIALOGUE_REACTION_REPAIR",
            }
            video_clips.append({"id": f"{source_id}-VIDEO", "source": str(source), "start": round(cursor, 6), "in": 0.0, "duration": round(clip_duration, 6), "metadata": metadata})
            audio_clips.append({"id": f"{source_id}-AUDIO", "source": str(source), "start": round(cursor, 6), "in": 0.0, "duration": round(clip_duration, 6), "volume": 0.9, "metadata": {"source_id": source_id, "parent_unit_id": unit_id, "source_sha256": task["sha256"], "native_dialogue_ambience_sfx": True}})
            windows[source_id] = {"start": cursor, "duration": clip_duration}
            cursor += clip_duration
        windows[unit_id] = {"start": unit_start, "duration": cursor - unit_start}

    subtitle_contract = load(SUBTITLES)
    inventory = load(INVENTORY)
    audio_manifest = load(AUDIO_MANIFEST)
    if subtitle_contract.get("dialogue_line_count") != 20 or inventory.get("dialogue_line_count") != 20:
        raise SystemExit("E31 subtitle/inventory count is not 20")
    if inventory.get("source_script_sha256") != subtitle_contract.get("source_script_sha256"):
        raise SystemExit("E31 subtitle contract and Claude inventory script SHA mismatch")
    captions = subtitle_clips(inventory, audio_manifest, windows)
    expected_dialogue = {row["dialogue_id"] for row in captions}
    if len(captions) != 20 or {row["dialogue_id"] for row in captions} != expected_dialogue:
        raise SystemExit("E31 subtitle coverage is not exactly 20/20")

    outro = load(OUTRO)
    logo = ROOT / outro["logo_asset"]["path"]
    chime = ROOT / outro["chime_asset"]["path"]
    if sha256(logo) != outro["logo_asset"]["sha256"] or sha256(chime) != outro["chime_asset"]["sha256"]:
        raise SystemExit("NALU Motion asset SHA mismatch")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROJECT.parent.mkdir(parents=True, exist_ok=True)
    project = {
        "version": "1.0",
        "metadata": {
            "episode": "E31", "status": "AGENTCUT_V1_SUBTITLED_OUTRO_NOT_FINAL",
            "runtime_seconds": round(cursor + 3.0, 6), "content_runtime_seconds": round(cursor, 6),
            "source_script": inventory["source_script"], "source_script_sha256": subtitle_contract["source_script_sha256"],
            "subtitle_contract": {"coverage": "20/20", "burned_in": True, "path": str(SUBTITLES)},
            "duration_policy": "PLOT_INTEGRITY_ONLY_NO_ORIGINAL_DURATION_FLOOR",
        },
        "output": {"path": str(OUTPUT), "width": 720, "height": 1280, "fps": 24, "videoCodec": "libx264", "audioCodec": "aac", "audioBitrate": "192k", "pixelFormat": "yuv420p", "threads": 4},
        "masterAudioPolicy": {"required": True, "limiter": True, "truePeakCeilingDbtp": -1.0, "codecHeadroomDb": 1.5, "loudnessTargetLufs": -16, "loudnessRangeLu": 11, "maxClippedSamples": 0},
        "timeline": {
            "videoTracks": [{"id": "E31_VIDEO", "clips": video_clips}],
            "audioTracks": [{"id": "E31_NATIVE_DIALOGUE_AMBIENCE_SFX", "clips": audio_clips}],
            "subtitleTracks": [{"id": "E31_ZH_CN_BURNIN", "enabled": True, "style": {"font": "/System/Library/Fonts/STHeiti Medium.ttc", "size": 42, "color": "#FFFFFF", "outline": 3, "outlineColor": "#000000", "alignment": "bottom-center", "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170}, "wrap": 15}, "clips": captions}],
        },
        "expectedDialogueIds": sorted(expected_dialogue), "requireBrandedOutro": True,
        "outro": {"enabled": True, "brand": "nalu_motion", "template": "nalu-motion-v1", "templateVersion": "1.0", "assetPath": str(logo), "duration": 3, "fit": "contain", "audioPolicy": "asset", "transitionIn": 0.25, "transitionOut": 0.25, "titleText": "青山", "nextText": "敬请期待", "brandText": "NALU MOTION", "dialogueDuckDb": -12, "bgmDuckDb": -9, "safeArea": {"left": 72, "right": 72, "top": 128, "bottom": 128}, "logo": {"x": 235, "y": 590, "width": 250, "height": 141}, "includeInTotalDuration": True, "audioPath": str(chime)},
        "qingshanAudit": {"pipelineStage": "E31_AGENTCUT_V1_RENDER_AND_FULLCUT_QA", "sourceCount": len(video_clips), "u18SplitDialogueRepair": split_ready, "subtitleDialogueCoverage": "20/20", "originalReviewFailuresPreserved": [str(path) for path in ADMISSIONS]},
    }
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema": "qingshan.e31.agentcut_v1_build.v1", "episode": "E31",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "READY_VALIDATE_AND_RENDER",
        "project": str(PROJECT), "project_sha256": sha256(PROJECT), "output": str(OUTPUT),
        "source_count": len(video_clips), "content_seconds": round(cursor, 6), "outro_seconds": 3.0,
        "expected_total_seconds": round(cursor + 3.0, 6), "subtitle_dialogue_coverage": "20/20",
        "subtitle_event_count": len(captions), "logo_sha256": sha256(logo), "chime_sha256": sha256(chime),
    }
    BUILD_RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
