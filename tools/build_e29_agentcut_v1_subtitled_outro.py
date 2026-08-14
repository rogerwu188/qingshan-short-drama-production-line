#!/usr/bin/env python3
"""Build E29 AgentCut V1 from all admitted native-speed video units."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e29_claude_writer_v1_20260722"
PLAN = PRODUCTION / "E29_VIDEO_UNIT_PLAN_V2_CL2X581.json"
SUBTITLES = PRODUCTION / "E29_SUBTITLE_CONTRACT_V1.json"
OUTRO = PRODUCTION / "E29_NALU_MOTION_OUTRO_CONTRACT_V1.json"
RECEIPTS = [
    ROOT / "workflow/tasks/E29_15_VIDEO_UNIT_PARALLEL_BATCH_V1_20260722.json",
    ROOT / "workflow/tasks/E29_3_VIDEO_UNIT_SUBMIT_TIMEOUT_RETRY_V2_20260722.json",
    ROOT / "workflow/tasks/E29_2_VIDEO_UNIT_REMOTE_FAILED_RETRY_V3_20260722.json",
]
ADJUDICATIONS = [
    ROOT / "qa/e29_video_unit_ai_review_v1_20260722/E29_13_VIDEO_UNIT_OCR_TAIL_GAP_CONDITIONAL_MACHINE_ADMISSION.json",
    ROOT / "qa/e29_video_unit_ai_review_v1_20260722/E29_U07_U11_OCR_TAIL_GAP_CONDITIONAL_MACHINE_ADMISSION.json",
]
PROJECT = ROOT / "configs/e29_agentcut_v1_subtitled_outro_20260722.json"
OUTPUT = ROOT / "exports/e29/agentcut_v1_subtitled_outro_20260722/E29_AGENTCUT_V1_SUBTITLED_OUTRO_NOT_FINAL.mp4"
BUILD_RECEIPT = ROOT / "workflow/tasks/E29_AGENTCUT_V1_SUBTITLED_OUTRO_BUILD_RECEIPT_20260722.json"

# The dialogue is bound to the Claude-script unit that depicts that exact beat.
DIALOGUE_UNIT_MAP = {
    "E29-DIA-001": "E29-CW-U03",
    "E29-DIA-002": "E29-CW-U04",
    "E29-DIA-003": "E29-CW-U06",
    "E29-DIA-004": "E29-CW-U07",
    "E29-DIA-005": "E29-CW-U07",
    "E29-DIA-006": "E29-CW-U08",
    "E29-DIA-007": "E29-CW-U09",
    "E29-DIA-008": "E29-CW-U09",
    "E29-DIA-009": "E29-CW-U10",
    "E29-DIA-010": "E29-CW-U11",
    "E29-DIA-011": "E29-CW-U12",
    "E29-DIA-012": "E29-CW-U12",
    "E29-DIA-013": "E29-CW-U14",
    "E29-DIA-014": "E29-CW-U15",
    "E29-DIA-015": "E29-CW-U15",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_sources(admitted: set[str]) -> dict[str, dict]:
    latest = {}
    for receipt_path in RECEIPTS:
        for task in load(receipt_path).get("tasks", []):
            if not task.get("output_path") or not task.get("sha256"):
                continue
            path = Path(task["output_path"])
            if not path.is_file() or sha256(path) != task.get("sha256"):
                raise ValueError(f"missing or SHA-mismatched source: {path}")
            if task["sha256"] in admitted:
                latest[task["source_id"]] = task
    return latest


def admitted_shas() -> set[str]:
    result = set()
    for path in ADJUDICATIONS:
        payload = load(path)
        if payload.get("status") != "CONDITIONAL_MACHINE_ADMISSION" or payload.get("blocking") is not False:
            raise ValueError(f"adjudication is not open: {path}")
        result.update(row["candidate_sha256"] for row in payload["admissions"])
    return result


def subtitle_clips(dialogue: list[dict], unit_windows: dict[str, dict]) -> list[dict]:
    by_unit: dict[str, list[dict]] = {}
    for row in dialogue:
        by_unit.setdefault(DIALOGUE_UNIT_MAP[row["dia_id"]], []).append(row)

    clips = []
    for unit_id, rows in by_unit.items():
        window = unit_windows[unit_id]
        start = float(window["start"])
        duration = float(window["duration"])
        usable_start = start + min(0.8, duration * 0.08)
        usable_duration = duration - min(1.2, duration * 0.12)
        line_weights = [max(1, len(row["spoken_text"])) for row in rows]
        line_total = sum(line_weights)
        line_cursor = usable_start
        for row, line_weight in zip(rows, line_weights):
            line_duration = usable_duration * line_weight / line_total
            clips.append({
                "id": row["dia_id"],
                "dialogue_id": row["dia_id"],
                "text": row["spoken_text"],
                "start": round(line_cursor, 6),
                "duration": round(line_duration, 6),
                "metadata": {
                    "episode": "E29",
                    "speaker": row["speaker"],
                    "source": "CLAUDE_SCRIPT_LOCKED_SUBTITLE_CONTRACT",
                    "unit_id": unit_id,
                    "wrap_segments": row["subtitle_segments"],
                },
            })
            line_cursor += line_duration
    return sorted(clips, key=lambda row: (row["start"], row["id"]))


def main() -> int:
    plan = load(PLAN)
    admitted = admitted_shas()
    sources = collect_sources(admitted)
    expected_units = [row["unit_id"] for row in plan["units"]]
    if sorted(sources) != sorted(expected_units):
        raise SystemExit(f"source coverage mismatch: {sorted(sources)}")
    if {task["sha256"] for task in sources.values()} != admitted:
        raise SystemExit("15-source admission SHA coverage mismatch")

    video_clips = []
    audio_clips = []
    unit_windows = {}
    cursor = 0.0
    for unit in plan["units"]:
        unit_id = unit["unit_id"]
        task = sources[unit_id]
        source = Path(task["output_path"])
        duration = float(unit["duration_seconds"])
        metadata = {
            "episode": "E29",
            "source_id": unit_id,
            "scene_id": unit["scene_id"],
            "source_sha256": task["sha256"],
            "source_admission": "CONDITIONAL_MACHINE_ADMISSION",
            "duration_policy": "NATIVE_SPEED_TRIM_CONTAINER_TAIL_NO_PADDING_NO_SLOW_MOTION",
            "cutReason": "CLAUDE_SCRIPT_CONTIGUOUS_SCENE_LOCAL_VIDEO_UNIT",
            "continuity": {"identity": "locked", "scene": "locked", "action": "locked", "time": "locked"},
        }
        video_clips.append({
            "id": f"{unit_id}-VIDEO", "source": str(source), "start": round(cursor, 6),
            "in": 0.0, "duration": duration, "metadata": metadata,
        })
        audio_clips.append({
            "id": f"{unit_id}-AUDIO", "source": str(source), "start": round(cursor, 6),
            "in": 0.0, "duration": duration, "volume": 0.9,
            "metadata": {"source_id": unit_id, "source_sha256": task["sha256"], "native_ambience_sfx": True},
        })
        unit_windows[unit_id] = {"start": cursor, "duration": duration}
        cursor += duration

    subtitle_contract = load(SUBTITLES)
    captions = subtitle_clips(subtitle_contract["dialogue"], unit_windows)
    covered = {row["dialogue_id"] for row in captions}
    expected_dialogue = {row["dia_id"] for row in subtitle_contract["dialogue"]}
    if covered != expected_dialogue:
        raise SystemExit("subtitle coverage mismatch")

    outro_contract = load(OUTRO)
    logo = ROOT / outro_contract["logo_asset"]["path"]
    chime = ROOT / outro_contract["chime_asset"]["path"]
    if sha256(logo) != outro_contract["logo_asset"]["sha256"] or sha256(chime) != outro_contract["chime_asset"]["sha256"]:
        raise SystemExit("NALU MOTION asset SHA mismatch")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROJECT.parent.mkdir(parents=True, exist_ok=True)
    project = {
        "version": "1.0",
        "metadata": {
            "episode": "E29", "status": "AGENTCUT_V1_SUBTITLED_OUTRO_NOT_FINAL",
            "runtime_seconds": round(cursor + 3.0, 6), "content_runtime_seconds": round(cursor, 6),
            "source_script": subtitle_contract["source_script"],
            "source_script_sha256": subtitle_contract["source_script_sha256"],
            "subtitle_contract": {"coverage": "15/15", "burned_in": True, "path": str(SUBTITLES)},
            "duration_policy": "PLOT_INTEGRITY_ONLY_NO_ORIGINAL_DURATION_FLOOR",
        },
        "output": {"path": str(OUTPUT), "width": 720, "height": 1280, "fps": 24,
                   "videoCodec": "libx264", "audioCodec": "aac", "audioBitrate": "192k",
                   "pixelFormat": "yuv420p", "threads": 4},
        "masterAudioPolicy": {"required": True, "limiter": True, "truePeakCeilingDbtp": -1.0,
                              "codecHeadroomDb": 1.5, "loudnessTargetLufs": -16,
                              "loudnessRangeLu": 11, "maxClippedSamples": 0},
        "timeline": {
            "videoTracks": [{"id": "E29_VIDEO", "clips": video_clips}],
            "audioTracks": [{"id": "E29_NATIVE_AMBIENCE_SFX", "clips": audio_clips}],
            "subtitleTracks": [{"id": "E29_ZH_CN_BURNIN", "enabled": True,
                "style": {"font": "/System/Library/Fonts/STHeiti Medium.ttc", "size": 42,
                          "color": "#FFFFFF", "outline": 3, "outlineColor": "#000000",
                          "alignment": "bottom-center", "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170},
                          "wrap": 15}, "clips": captions}],
        },
        "expectedDialogueIds": [row["dia_id"] for row in subtitle_contract["dialogue"]],
        "requireBrandedOutro": True,
        "outro": {"enabled": True, "brand": "nalu_motion", "template": "nalu-motion-v1",
                  "templateVersion": "1.0", "assetPath": str(logo), "duration": 3, "fit": "contain",
                  "audioPolicy": "asset", "transitionIn": 0.25, "transitionOut": 0.25,
                  "titleText": "青山", "nextText": "敬请期待", "brandText": "NALU MOTION",
                  "dialogueDuckDb": -12, "bgmDuckDb": -9,
                  "safeArea": {"left": 72, "right": 72, "top": 128, "bottom": 128},
                  "logo": {"x": 235, "y": 590, "width": 250, "height": 141},
                  "includeInTotalDuration": True, "audioPath": str(chime)},
        "qingshanAudit": {"pipelineStage": "E29_AGENTCUT_V1_RENDER_AND_FULLCUT_QA",
                          "sourceCount": 15, "subtitleDialogueCoverage": "15/15",
                          "originalReviewFailuresPreserved": [str(path) for path in ADJUDICATIONS]},
    }
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema": "qingshan.e29.agentcut_v1_build.v1", "episode": "E29",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "READY_VALIDATE_AND_RENDER",
        "project": str(PROJECT), "project_sha256": sha256(PROJECT), "output": str(OUTPUT),
        "source_count": 15, "content_seconds": round(cursor, 6), "outro_seconds": 3.0,
        "expected_total_seconds": round(cursor + 3.0, 6), "subtitle_dialogue_coverage": "15/15",
        "subtitle_event_count": len(captions), "logo_sha256": sha256(logo), "chime_sha256": sha256(chime),
    }
    BUILD_RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
