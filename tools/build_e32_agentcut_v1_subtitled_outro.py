#!/usr/bin/env python3
"""Build E32 AgentCut from the admitted native-speed performance units."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v1_20260722"
MANIFEST = PRODUCTION / "E32_PRODUCTION_MANIFEST.json"
SUBTITLES = PRODUCTION / "E32_SUBTITLE_CONTRACT_V1.json"
OUTRO = PRODUCTION / "E32_NALU_MOTION_OUTRO_CONTRACT_V1.json"
AUDIO_MANIFEST = ROOT / "working_assets/e32_dialogue_audio_refs_20260722/E32_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1.json"
RECEIPTS = [
    ROOT / "workflow/tasks/E32_VIDEO_BATCH_INCREMENTAL_READY_V1_RECEIPT_R3.json",
    ROOT / "workflow/tasks/E32_VIDEO_BATCH_S01_READY_R1_RECEIPT.json",
    ROOT / "workflow/tasks/E32_VIDEO_BATCH_U01_AUDIO_PAD_R2_RECEIPT.json",
    ROOT / "workflow/tasks/E32_VIDEO_BATCH_U04_TWO_ANCHOR_R1_RECEIPT.json",
    ROOT / "workflow/tasks/E32_VIDEO_BATCH_REFLOWED_READY_R2_RECEIPT.json",
    ROOT / "workflow/tasks/E32_VIDEO_BATCH_IDENTITY_REPAIRED_READY_R3_RECEIPT.json",
    ROOT / "workflow/tasks/E32_VIDEO_U09_CHANGED_INPUT_R2_RECEIPT.json",
    ROOT / "workflow/tasks/E32_VIDEO_U09_SPLIT_CHANGED_INPUT_R3_RECEIPT.json",
    ROOT / "workflow/tasks/E32_VIDEO_U09A_CORRECT_ANCHOR_R4_RECEIPT.json",
    ROOT / "workflow/tasks/E32_VIDEO_U09B_CONTINUATION_R5_RECEIPT.json",
    ROOT / "workflow/tasks/E32_VIDEO_U10_TWO_ANCHOR_READY_R5_RECEIPT.json",
    ROOT / "workflow/tasks/E32_VIDEO_U10_SPLIT_DIALOGUE_R6_RECEIPT.json",
    ROOT / "workflow/tasks/E32_VIDEO_U10B_PROP_OWNER_REPAIR_R7_RECEIPT.json",
]
ADMISSIONS = [
    PRODUCTION / "video_performance_v1/qa/E32_U01_CONDITIONAL_MACHINE_ADMISSION_R1.json",
    PRODUCTION / "video_performance_v1/qa/E32_U07B_CONDITIONAL_MACHINE_ADMISSION_R2.json",
    PRODUCTION / "video_performance_v1/qa/E32_U09B_CONDITIONAL_MACHINE_ADMISSION_R5.json",
    PRODUCTION / "video_performance_v1/qa/E32_U10A_CONDITIONAL_MACHINE_ADMISSION_R6.json",
    PRODUCTION / "video_performance_v1/qa/E32_U10B_CONDITIONAL_MACHINE_ADMISSION_R7.json",
    PRODUCTION / "video_performance_v1/qa/E32_REFLOWED_AND_IDENTITY_REPAIRED_MACHINE_QA_R3.json",
    PRODUCTION / "video_performance_v1/qa/E32_U10_CONDITIONAL_MACHINE_ADMISSION_R5.json",
]
PROJECT = ROOT / "configs/e32_agentcut_v1_subtitled_outro_20260723.json"
OUTPUT = ROOT / "exports/e32/agentcut_v1_subtitled_outro_20260723/E32_AGENTCUT_V1_SUBTITLED_OUTRO_NOT_FINAL.mp4"
BUILD_RECEIPT = ROOT / "workflow/tasks/E32_AGENTCUT_V1_SUBTITLED_OUTRO_BUILD_RECEIPT_20260723.json"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"

ACTUAL_UNITS = [
    ("E32-CW-U01", "E32-CW-S01"), ("E32-CW-U02", "E32-CW-S01"),
    ("E32-CW-U03", "E32-CW-S01"), ("E32-CW-U04", "E32-CW-S02"),
    ("E32-CW-U05", "E32-CW-S02"), ("E32-CW-U06", "E32-CW-S02"),
    ("E32-CW-U07A", "E32-CW-S02"), ("E32-CW-U07B", "E32-CW-S02"),
    ("E32-CW-U08", "E32-CW-S03"), ("E32-CW-U09A", "E32-CW-S03"),
    ("E32-CW-U09B", "E32-CW-S03"),
    ("E32-CW-U10A", "E32-CW-S03"), ("E32-CW-U10B", "E32-CW-S03"),
    ("E32-CW-U11", "E32-CW-S04"),
    ("E32-CW-U12R", "E32-CW-S04"), ("E32-CW-U13", "E32-CW-S04"),
    ("E32-CW-U14", "E32-CW-S04"), ("E32-CW-U15", "E32-CW-S05"),
    ("E32-CW-U16A", "E32-CW-S05"), ("E32-CW-U16B", "E32-CW-S05"),
    ("E32-CW-U16C", "E32-CW-S05"), ("E32-CW-U17R", "E32-CW-S05"),
]

DIALOGUE_TO_UNIT = {
    "E32-DIA-001": "E32-CW-U01", "E32-DIA-002": "E32-CW-U01",
    "E32-DIA-003": "E32-CW-U02", "E32-DIA-004": "E32-CW-U02",
    "E32-DIA-005": "E32-CW-U03", "E32-DIA-006": "E32-CW-U06",
    "E32-DIA-007": "E32-CW-U07A", "E32-DIA-008": "E32-CW-U07B",
    "E32-DIA-009": "E32-CW-U07B", "E32-DIA-010": "E32-CW-U10A",
    "E32-DIA-011": "E32-CW-U10B", "E32-DIA-012": "E32-CW-U12R",
    "E32-DIA-013": "E32-CW-U13", "E32-DIA-014": "E32-CW-U14",
    "E32-DIA-015": "E32-CW-U15", "E32-DIA-016": "E32-CW-U16A",
    "E32-DIA-017": "E32-CW-U16B", "E32-DIA-018": "E32-CW-U16C",
}

# Seedance preserves the reference speech but may choose a different dramatic
# pause. Burn-in timing must follow the generated performance, not the TTS plan.
POST_GENERATION_ASR_TIMING = {
    "E32-DIA-003": {"offset": 3.34, "duration": 3.90},
    "E32-DIA-004": {"offset": 7.24, "duration": 5.68},
    "E32-DIA-014": {"offset": 1.87, "duration": 4.70},
}


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


def subtitle_display_text(text: str) -> str:
    return re.sub(r"'([^']+)'", r"“\1”", text)


def admitted_shas() -> set[str]:
    values: set[str] = set()
    for path in ADMISSIONS:
        if not path.is_file():
            continue
        payload = load(path)
        if payload.get("decision") == "CONDITIONAL_MACHINE_ADMISSION":
            values.add(payload["candidate_sha256"])
        for row in payload.get("results", []):
            if row.get("status") == "CONDITIONAL_MACHINE_ADMISSION":
                values.add(row["sha256"])
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
    by_unit: dict[str, list[dict]] = defaultdict(list)
    for row in audio_manifest["rows"]:
        by_unit[DIALOGUE_TO_UNIT[row["dia_id"]]].append(row)
    clips: list[dict] = []
    for unit_id, rows in by_unit.items():
        window = windows[unit_id]
        cursor = window["start"] + 0.25
        for row in rows:
            measured = POST_GENERATION_ASR_TIMING.get(row["dia_id"])
            if measured:
                cursor = window["start"] + measured["offset"]
            remaining = window["start"] + window["duration"] - cursor - 0.08
            requested_duration = measured["duration"] if measured else float(row["duration_seconds"])
            line_duration = min(requested_duration, remaining)
            if line_duration <= 0:
                raise SystemExit(f"subtitle does not fit unit: {row['dia_id']}")
            clips.append({
                "id": row["dia_id"], "dialogue_id": row["dia_id"],
                "text": subtitle_display_text(row["spoken_text"]),
                "start": round(cursor, 6), "duration": round(line_duration, 6),
                "metadata": {"episode": "E32", "speaker": row["speaker"], "unit_id": unit_id,
                             "source": "POST_GENERATION_ASR_MEASURED" if measured else
                                       "CLAUDE_SCRIPT_AND_EXACT_AUDIO_REFERENCE_LOCK"},
            })
            cursor += line_duration + 0.14
    return sorted(clips, key=lambda row: (row["start"], row["id"]))


def main() -> int:
    manifest = load(MANIFEST)
    subtitle_contract = load(SUBTITLES)
    audio_manifest = load(AUDIO_MANIFEST)
    sources = collect_sources()
    expected = {unit_id for unit_id, _ in ACTUAL_UNITS}
    missing = sorted(expected - set(sources))
    if missing:
        raise SystemExit(f"source coverage mismatch; missing={missing}")

    video_clips: list[dict] = []
    audio_clips: list[dict] = []
    windows: dict[str, dict] = {}
    cursor = 0.0
    for unit_id, scene_id in ACTUAL_UNITS:
        task = sources[unit_id]
        source = Path(task["output_path"])
        planned = float(task.get("duration_seconds") or task.get("duration") or duration(source))
        clip_duration = min(planned, duration(source))
        metadata = {
            "episode": "E32", "source_id": unit_id, "scene_id": scene_id,
            "source_sha256": task["sha256"], "source_admission": task["admission"],
            "duration_policy": "NATIVE_SPEED_TRIM_CONTAINER_TAIL_NO_PADDING_NO_SLOW_MOTION",
            "cutReason": "CLAUDE_SCRIPT_CONTIGUOUS_SCENE_LOCAL_NATURAL_GROUP",
        }
        video_clips.append({"id": f"{unit_id}-VIDEO", "source": str(source), "start": round(cursor, 6),
                            "in": 0.0, "duration": round(clip_duration, 6), "metadata": metadata})
        audio_clips.append({"id": f"{unit_id}-AUDIO", "source": str(source), "start": round(cursor, 6),
                            "in": 0.0, "duration": round(clip_duration, 6), "volume": 0.9,
                            "metadata": {"source_id": unit_id, "source_sha256": task["sha256"],
                                         "native_dialogue_ambience_sfx": True}})
        windows[unit_id] = {"start": cursor, "duration": clip_duration}
        cursor += clip_duration

    if audio_manifest.get("dialogue_line_count") != 18 or subtitle_contract.get("status") != "LOCKED_FOR_AGENTCUT":
        raise SystemExit("E32 dialogue/subtitle contract is not locked at 18 lines")
    captions = subtitle_clips(audio_manifest, windows)
    expected_dialogue = {row["dia_id"] for row in audio_manifest["rows"]}
    if len(captions) != 18 or {row["dialogue_id"] for row in captions} != expected_dialogue:
        raise SystemExit("E32 subtitle coverage is not exactly 18/18")

    outro = load(OUTRO)
    logo = ROOT / outro["logo_asset"]
    chime = ROOT / outro["chime_asset"]
    if not logo.is_file() or not chime.is_file():
        raise SystemExit("NALU Motion assets are missing")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROJECT.parent.mkdir(parents=True, exist_ok=True)
    project = {
        "version": "1.0",
        "metadata": {
            "episode": "E32", "status": "AGENTCUT_V1_SUBTITLED_OUTRO_NOT_FINAL",
            "runtime_seconds": round(cursor + 3.0, 6), "content_runtime_seconds": round(cursor, 6),
            "source_script": manifest["source_script"], "source_script_sha256": manifest["source_script_sha256"],
            "subtitle_contract": {"coverage": "18/18", "burned_in": True, "path": str(SUBTITLES)},
            "duration_policy": "PLOT_INTEGRITY_ONLY_NO_ORIGINAL_DURATION_FLOOR",
        },
        "output": {"path": str(OUTPUT), "width": 720, "height": 1280, "fps": 24,
                   "videoCodec": "libx264", "audioCodec": "aac", "audioBitrate": "192k",
                   "pixelFormat": "yuv420p", "threads": 4},
        "masterAudioPolicy": {"required": True, "limiter": True, "truePeakCeilingDbtp": -1.0,
                              "codecHeadroomDb": 1.5, "loudnessTargetLufs": -16,
                              "loudnessRangeLu": 11, "maxClippedSamples": 0},
        "timeline": {
            "videoTracks": [{"id": "E32_VIDEO", "clips": video_clips}],
            "audioTracks": [{"id": "E32_NATIVE_DIALOGUE_AMBIENCE_SFX", "clips": audio_clips}],
            "subtitleTracks": [{"id": "E32_ZH_CN_BURNIN", "enabled": True,
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
        "qingshanAudit": {"pipelineStage": "E32_AGENTCUT_V1_RENDER_AND_FULLCUT_QA",
                          "sourceCount": len(video_clips), "subtitleDialogueCoverage": "18/18",
                          "originalReviewFailuresPreserved": [str(path) for path in ADMISSIONS if path.is_file()]},
    }
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema": "qingshan.e32.agentcut_v1_build.v1", "episode": "E32",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "READY_VALIDATE_AND_RENDER",
        "project": str(PROJECT), "project_sha256": sha256(PROJECT), "output": str(OUTPUT),
        "source_count": len(video_clips), "content_seconds": round(cursor, 6), "outro_seconds": 3.0,
        "expected_total_seconds": round(cursor + 3.0, 6), "subtitle_dialogue_coverage": "18/18",
        "subtitle_event_count": len(captions), "logo_sha256": sha256(logo), "chime_sha256": sha256(chime),
    }
    BUILD_RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
