#!/usr/bin/env python3
"""Build E33 AgentCut from admitted native-speed performance units."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v1_20260723"
GROUPING = PRODUCTION / "E33_VIDEO_UNIT_GROUPING_SPEC_V1.json"
MANIFEST = PRODUCTION / "E33_PRODUCTION_MANIFEST.json"
SUBTITLES = PRODUCTION / "E33_SUBTITLE_CONTRACT_V1.json"
OUTRO = PRODUCTION / "E33_NALU_MOTION_OUTRO_CONTRACT_V1.json"
AUDIO_MANIFEST = ROOT / "working_assets/e33_dialogue_audio_refs_20260723/E33_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
NATIVE_DIALOGUE_TIMINGS = PRODUCTION / "E33_NATIVE_DIALOGUE_TIMINGS_V1.json"
RECEIPTS = [
    ROOT / "workflow/tasks/E33_VIDEO_BATCH_PERFORMANCE_READY_V3_RECEIPT.json",
    ROOT / "workflow/tasks/E33_U02_FAILED_ONLY_PERFORMANCE_R4_RECEIPT.json",
]
ADMISSIONS = [
    PRODUCTION / "video_performance_v1/qa/E33-CW-U19-CONDITIONAL-MACHINE-ADMISSION-V1.json",
    PRODUCTION / "video_performance_v1/qa/E33_OCR_ONLY_CONDITIONAL_MACHINE_ADMISSIONS_V1.json",
]
PROJECT = ROOT / "configs/e33_agentcut_v1_subtitled_outro_20260723.json"
OUTPUT = ROOT / "exports/e33/agentcut_v1_subtitled_outro_20260723/E33_AGENTCUT_V2_NATIVE_TIMED_SUBTITLES_NOT_FINAL.mp4"
BUILD_RECEIPT = ROOT / "workflow/tasks/E33_AGENTCUT_V1_SUBTITLED_OUTRO_BUILD_RECEIPT_20260723.json"
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
    proc = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(proc.stdout.strip())


def subtitle_text(text: str) -> str:
    return re.sub(r"'([^']+)'", r"“\1”", text)


def admitted_shas() -> set[str]:
    values: set[str] = set()
    for path in ADMISSIONS:
        payload = load(path)
        if payload.get("decision") == "CONDITIONAL_MACHINE_ADMISSION" and payload.get("candidate_sha256"):
            values.add(payload["candidate_sha256"])
        for row in payload.get("rows", []):
            if payload.get("decision") == "CONDITIONAL_MACHINE_ADMISSION":
                values.add(row["candidate_sha256"])
    return values


def collect_sources() -> dict[str, dict]:
    conditional = admitted_shas()
    sources: dict[str, dict] = {}
    for receipt_path in RECEIPTS:
        if not receipt_path.is_file():
            continue
        for task in load(receipt_path).get("tasks", []):
            if not task.get("output_path") or not task.get("sha256"):
                continue
            path = Path(task["output_path"])
            if not path.is_file() or sha256(path) != task["sha256"]:
                raise SystemExit(f"missing or SHA-mismatched source: {path}")
            state = task.get("state") or task.get("status")
            if state == "qa_pass":
                admission = "QA_PASS"
            elif task["sha256"] in conditional:
                admission = "CONDITIONAL_MACHINE_ADMISSION"
            else:
                continue
            sources[task["unit_id"]] = {**task, "admission": admission}
    return sources


def subtitle_clips(audio_manifest: dict, windows: dict[str, dict]) -> list[dict]:
    native_timings = load(NATIVE_DIALOGUE_TIMINGS) if NATIVE_DIALOGUE_TIMINGS.is_file() else {}
    timing_rows = native_timings.get("dialogue", {})
    by_unit: dict[str, list[dict]] = defaultdict(list)
    for row in audio_manifest["rows"]:
        by_unit[row["video_unit_id"]].append(row)
    clips: list[dict] = []
    for unit_id, rows in by_unit.items():
        window = windows[unit_id]
        cursor = window["start"] + 0.25
        for row in rows:
            measured = timing_rows.get(row["dia_id"])
            if measured:
                cursor = window["start"] + float(measured["source_start_seconds"])
                line_duration = float(measured["duration_seconds"])
            else:
                remaining = window["start"] + window["duration"] - cursor - 0.08
                line_duration = min(float(row["duration_seconds"]), remaining)
            remaining = window["start"] + window["duration"] - cursor - 0.02
            line_duration = min(line_duration, remaining)
            if line_duration <= 0:
                raise SystemExit(f"subtitle does not fit unit: {row['dia_id']}")
            clips.append({
                "id": row["dia_id"], "dialogue_id": row["dia_id"],
                "text": subtitle_text(row["spoken_text"]),
                "start": round(cursor, 6), "duration": round(line_duration, 6),
                "metadata": {"episode": "E33", "speaker": row["speaker"], "unit_id": unit_id,
                             "source": "FINAL_NATIVE_AUDIO_ASR_MEASURED" if measured else
                                       "CLAUDE_SCRIPT_AND_EXACT_AUDIO_REFERENCE_LOCK"},
            })
            cursor += line_duration + 0.14
    return sorted(clips, key=lambda row: (row["start"], row["id"]))


def main() -> int:
    grouping = load(GROUPING)
    manifest = load(MANIFEST)
    subtitle_contract = load(SUBTITLES)
    audio_manifest = load(AUDIO_MANIFEST)
    units = [(row["unit_id"], row["scene_id"]) for row in grouping["groups"]]
    sources = collect_sources()
    missing = sorted({unit_id for unit_id, _ in units} - set(sources))
    if missing:
        raise SystemExit(f"source coverage mismatch; missing={missing}")

    video_clips: list[dict] = []
    audio_clips: list[dict] = []
    windows: dict[str, dict] = {}
    cursor = 0.0
    for unit_id, scene_id in units:
        task = sources[unit_id]
        source = Path(task["output_path"])
        clip_duration = min(float(task.get("duration_seconds") or task.get("duration")), duration(source))
        metadata = {
            "episode": "E33", "source_id": unit_id, "scene_id": scene_id,
            "source_sha256": task["sha256"], "source_admission": task["admission"],
            "duration_policy": "NATIVE_SPEED_TRIM_CONTAINER_TAIL_NO_PADDING_NO_SLOW_MOTION",
            "cut_reason": "CLAUDE_SCRIPT_CONTIGUOUS_SCENE_LOCAL_NATURAL_GROUP",
            "light_key": f"{scene_id}::LOCKED_MOTIVATED_LIGHT",
            "axis_line": f"{scene_id}::LOCKED_ACTION_AXIS",
            "eyeline": f"{unit_id}::PRIMARY_ACTION_TARGET",
        }
        video_clips.append({"id": f"{unit_id}-VIDEO", "source": str(source), "start": round(cursor, 6),
                            "in": 0.0, "duration": round(clip_duration, 6), "metadata": metadata})
        audio_clips.append({"id": f"{unit_id}-AUDIO", "source": str(source), "start": round(cursor, 6),
                            "in": 0.0, "duration": round(clip_duration, 6), "volume": 0.9,
                            "metadata": {"source_id": unit_id, "source_sha256": task["sha256"],
                                         "native_dialogue_ambience_sfx": True}})
        windows[unit_id] = {"start": cursor, "duration": clip_duration}
        cursor += clip_duration

    if audio_manifest.get("dialogue_line_count") != 14 or subtitle_contract.get("status") != "LOCKED_FOR_AGENTCUT":
        raise SystemExit("E33 dialogue/subtitle contract is not locked at 14 lines")
    captions = subtitle_clips(audio_manifest, windows)
    expected_dialogue = {row["dia_id"] for row in audio_manifest["rows"]}
    if len(captions) != 14 or {row["dialogue_id"] for row in captions} != expected_dialogue:
        raise SystemExit("E33 subtitle coverage is not exactly 14/14")

    outro = load(OUTRO)
    logo = ROOT / outro["logo_asset"]
    chime = ROOT / outro["chime_asset"]
    if not logo.is_file() or not chime.is_file():
        raise SystemExit("NALU Motion assets are missing")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROJECT.parent.mkdir(parents=True, exist_ok=True)
    project = {
        "version": "1.0",
        "metadata": {"episode": "E33", "status": "AGENTCUT_V2_NATIVE_TIMED_SUBTITLES_NOT_FINAL",
                     "runtime_seconds": round(cursor + 3.0, 6), "content_runtime_seconds": round(cursor, 6),
                     "source_script": manifest["source_script"], "source_script_sha256": manifest["source_script_sha256"],
                     "subtitle_contract": {"coverage": "14/14", "burned_in": True, "path": str(SUBTITLES)},
                     "duration_policy": "PLOT_INTEGRITY_ONLY_NO_ORIGINAL_DURATION_FLOOR"},
        "output": {"path": str(OUTPUT), "width": 720, "height": 1280, "fps": 24,
                   "videoCodec": "libx264", "audioCodec": "aac", "audioBitrate": "192k",
                   "pixelFormat": "yuv420p", "threads": 4},
        "masterAudioPolicy": {"required": True, "limiter": True, "truePeakCeilingDbtp": -1.0,
                              "codecHeadroomDb": 1.5, "loudnessTargetLufs": -16,
                              "loudnessRangeLu": 11, "maxClippedSamples": 0},
        "timeline": {
            "videoTracks": [{"id": "E33_VIDEO", "clips": video_clips}],
            "audioTracks": [{"id": "E33_NATIVE_DIALOGUE_AMBIENCE_SFX", "clips": audio_clips}],
            "subtitleTracks": [{"id": "E33_ZH_CN_BURNIN", "enabled": True,
                "style": {"font": "/System/Library/Fonts/STHeiti Medium.ttc", "size": 42,
                          "color": "#FFFFFF", "outline": 3, "outlineColor": "#000000",
                          "alignment": "bottom-center",
                          "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170}, "wrap": 15},
                "clips": captions}],
        },
        "expectedDialogueIds": sorted(expected_dialogue), "requireBrandedOutro": True,
        "outro": {"enabled": True, "brand": "nalu_motion", "template": "nalu-motion-v1",
                  "templateVersion": "1.0", "assetPath": str(logo), "duration": 3, "fit": "contain",
                  "audioPolicy": "asset", "transitionIn": 0.25, "transitionOut": 0.25,
                  "titleText": "青山", "nextText": "敬请期待", "brandText": "NALU MOTION",
                  "dialogueDuckDb": -12, "bgmDuckDb": -9,
                  "safeArea": {"left": 72, "right": 72, "top": 128, "bottom": 128},
                  "logo": {"x": 235, "y": 590, "width": 250, "height": 141},
                  "includeInTotalDuration": True, "audioPath": str(chime)},
        "qingshanAudit": {"pipelineStage": "E33_AGENTCUT_V1_RENDER_AND_FULLCUT_QA",
                          "sourceCount": len(video_clips), "subtitleDialogueCoverage": "14/14",
                          "originalReviewFailuresPreserved": [str(path) for path in ADMISSIONS]},
    }
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {"schema": "qingshan.e33.agentcut_v1_build.v1", "episode": "E33",
               "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "READY_VALIDATE_AND_RENDER",
               "project": str(PROJECT), "project_sha256": sha256(PROJECT), "output": str(OUTPUT),
               "source_count": len(video_clips), "content_seconds": round(cursor, 6), "outro_seconds": 3.0,
               "expected_total_seconds": round(cursor + 3.0, 6), "subtitle_dialogue_coverage": "14/14",
               "subtitle_event_count": len(captions), "logo_sha256": sha256(logo), "chime_sha256": sha256(chime)}
    BUILD_RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
