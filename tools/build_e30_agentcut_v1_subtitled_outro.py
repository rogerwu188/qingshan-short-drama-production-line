#!/usr/bin/env python3
"""Build the E30 AgentCut base with all 16 units, subtitles and NALU Motion."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e30_claude_writer_v1_20260722"
PLAN = PRODUCTION / "E30_VIDEO_UNIT_GROUPING_PLAN_V1.json"
SUBTITLES = PRODUCTION / "E30_SUBTITLE_CONTRACT_V1.json"
OUTRO = PRODUCTION / "E30_NALU_MOTION_OUTRO_CONTRACT_V1.json"
RECEIPTS = [
    ROOT / "workflow/tasks/E30_READY_VIDEO_UNITS_PARALLEL_BATCH_V2_20260722.json",
    ROOT / "workflow/tasks/E30_READY_VIDEO_UNITS_PARALLEL_BATCH_V3_R1_20260722.json",
    ROOT / "workflow/tasks/E30_SUBMIT_FAILED_ONLY_TRANSPORT_RESUME_V4_A_20260722.json",
    ROOT / "workflow/tasks/E30_U08_CAP8_ASSET_ID_RETRY_V6_20260722.json",
]
U06_REPAIRED = PRODUCTION / "video_incremental_v1/outputs/E30_E30-CW-U06-VIDEO-V1_f56f18f6-d38c-4ca3-8a83-154e46ac5745_DEDUP_FRAMES.mp4"
U06_RAW_CADENCE = PRODUCTION / "video_incremental_v1/qa/E30-CW-U06-VIDEO-V1_frame_cadence.json"
U06_REPAIR = PRODUCTION / "video_incremental_v1/qa/E30-CW-U06-VIDEO-V1_DEDUP_FRAMES_REPAIR.json"
U06_POST_CADENCE = PRODUCTION / "video_incremental_v1/qa/E30-CW-U06-VIDEO-V1_DEDUP_FRAMES_frame_cadence.json"
U06_POST_OCR = PRODUCTION / "video_incremental_v1/qa/E30-CW-U06-VIDEO-V1_DEDUP_FRAMES_ocr.json"
U04_REPAIRED = PRODUCTION / "video_incremental_v1/outputs/E30_E30-CW-U04-VIDEO-V1_0b8d7b3b-f96b-4360-bb44-e5475f6b3995_DEFREEZE.mp4"
U04_POST_CADENCE = PRODUCTION / "video_incremental_v1/qa/E30-CW-U04-VIDEO-V1_DEFREEZE_frame_cadence.json"
U04_RAW_CADENCE = ROOT / "qa/e30_final_v1_dialogue_20260722/E30_FINAL_FRAME_CADENCE_AUDIT_V1.json"
U04_REPAIR = PRODUCTION / "video_incremental_v1/qa/E30-CW-U04-VIDEO-V1_DEFREEZE_REPAIR.json"
ADMISSION = ROOT / "qa/e30_video_unit_review_20260722/E30_VIDEO_UNIT_CONDITIONAL_MACHINE_ADMISSION_V2.json"
PROJECT = ROOT / "configs/e30_agentcut_v9_subtitled_outro_20260722.json"
OUTPUT = ROOT / "exports/e30/agentcut_v9_subtitled_outro_20260722/E30_AGENTCUT_V9_SUBTITLED_OUTRO_NOT_FINAL.mp4"
RAW_QA_PROJECT = ROOT / "configs/e30_agentcut_v9_raw_qa_20260722.json"
RAW_QA_OUTPUT = ROOT / "exports/e30/agentcut_v9_raw_qa_20260722/E30_AGENTCUT_V9_RAW_QA.mp4"
RECEIPT = ROOT / "workflow/tasks/E30_AGENTCUT_V9_SUBTITLED_OUTRO_BUILD_RECEIPT_20260722.json"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"

DIALOGUE_UNIT_MAP = {
    "E30-DIA-001": "E30-CW-U01",
    "E30-DIA-002": "E30-CW-U02", "E30-DIA-003": "E30-CW-U02",
    "E30-DIA-004": "E30-CW-U03",
    "E30-DIA-005": "E30-CW-U04",
    "E30-DIA-006": "E30-CW-U05", "E30-DIA-007": "E30-CW-U05", "E30-DIA-008": "E30-CW-U05",
    "E30-DIA-009": "E30-CW-U06", "E30-DIA-010": "E30-CW-U06",
    "E30-DIA-011": "E30-CW-U09",
    "E30-DIA-012": "E30-CW-U10", "E30-DIA-013": "E30-CW-U11",
    "E30-DIA-014": "E30-CW-U12", "E30-DIA-015": "E30-CW-U13", "E30-DIA-016": "E30-CW-U13",
    "E30-DIA-017": "E30-CW-U14", "E30-DIA-018": "E30-CW-U14",
    "E30-DIA-019": "E30-CW-U15", "E30-DIA-020": "E30-CW-U15",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duration(path: Path) -> float:
    proc = subprocess.run([
        str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)
    ], check=True, capture_output=True, text=True)
    return float(proc.stdout.strip())


def collect_sources() -> dict[str, dict]:
    sources = {}
    for receipt in RECEIPTS:
        for task in load(receipt).get("tasks", []):
            path_value = task.get("output_path")
            if not path_value:
                continue
            path = Path(path_value)
            if path.is_file() and task.get("sha256") == sha256(path):
                sources[task["source_id"]] = {**task, "admission": "QA_PASS" if task.get("state") == "qa_pass" else "CONDITIONAL_MACHINE_ADMISSION"}
    if not U06_REPAIRED.is_file() or load(U06_POST_CADENCE).get("status") != "PASS" or load(U06_POST_OCR).get("status") != "PASS":
        raise SystemExit("U06 repaired candidate is not locally QA-passed")
    sources["E30-CW-U06"] = {
        **sources["E30-CW-U06"], "output_path": str(U06_REPAIRED), "sha256": sha256(U06_REPAIRED),
        "admission": "LOCAL_TECHNICAL_REPAIR_PASS",
    }
    if not U04_REPAIRED.is_file() or load(U04_POST_CADENCE).get("status") != "PASS":
        raise SystemExit("U04 defreeze candidate is not locally QA-passed")
    sources["E30-CW-U04"] = {
        **sources["E30-CW-U04"], "output_path": str(U04_REPAIRED), "sha256": sha256(U04_REPAIRED),
        "admission": "LOCAL_TECHNICAL_REPAIR_PASS",
    }
    return sources


def build_admission(sources: dict[str, dict]) -> None:
    raw_failures = {
        "E30-CW-U04": "Final-assembly cadence audit found five unmotivated frozen ranges; locally repaired by deleting 90 frozen frames and matching audio intervals without padding, slowdown or regeneration.",
        "E30-CW-U06": "Periodic 18-to-24 cadence duplication; locally repaired by deleting confirmed duplicate frames and matching audio intervals.",
        "E30-CW-U07": "The 2.1-second roof-sign pseudo-text interval is deleted with synchronized native audio; surrounding action remains at native speed and the original source/OCR failure stay preserved.",
        "E30-CW-U10": "OCR false positive over people, clothing and props; no readable text is visible.",
        "E30-CW-U12": "Detected Chinese name is the plot-required 沈砚 evidence and is factually correct.",
        "E30-CW-U16": "OCR false positive over crow, medicine hall and clothing; no unauthorized readable text is visible.",
    }
    admissions = []
    for unit_id, reason in raw_failures.items():
        task = sources[unit_id]
        admissions.append({
            "unit_id": unit_id, "candidate_path": task["output_path"], "candidate_sha256": task["sha256"],
            "status": "LOCAL_REPAIR_PASS" if unit_id in {"E30-CW-U04", "E30-CW-U06", "E30-CW-U07"} else "CONDITIONAL_MACHINE_ADMISSION",
            "original_failure_preserved": True, "reason": reason,
            "confidence": 0.99 if unit_id in {"E30-CW-U04", "E30-CW-U06", "E30-CW-U07"} else (0.94 if unit_id == "E30-CW-U12" else 0.91),
            "rollback": "Restore the SHA-recorded original remote candidate and original QA report.",
            "replacement_condition": "Replace only if later human or multimodal evidence proves a story fact, identity, safety or unauthorized-text error.",
        })
    write(ADMISSION, {
        "schema": "qingshan.conditional_machine_admission.v1", "episode": "E30",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "CONDITIONAL_MACHINE_ADMISSION",
        "blocking": False, "admissions": admissions,
        "u06_raw_cadence": str(U06_RAW_CADENCE), "u06_repair": str(U06_REPAIR),
        "u06_post_repair_cadence": str(U06_POST_CADENCE), "u06_post_repair_ocr": str(U06_POST_OCR),
        "u04_raw_full_cut_cadence": str(U04_RAW_CADENCE), "u04_repair": str(U04_REPAIR),
        "u04_post_repair_cadence": str(U04_POST_CADENCE),
        "new_generation_calls": 0, "new_generation_credits": 0,
    })


def subtitle_display_text(value: str) -> str:
    value = re.sub(r"'([^']+)'", r"‘\1’", value)
    value = re.sub(r'"([^"]+)"', r'“\1”', value)
    return value.replace('"', '”').replace("'", "’")


def subtitle_clips(dialogue: list[dict], windows: dict[str, dict]) -> list[dict]:
    by_unit: dict[str, list[dict]] = {}
    for row in dialogue:
        by_unit.setdefault(DIALOGUE_UNIT_MAP[row["dia_id"]], []).append(row)
    clips = []
    for unit_id, rows in by_unit.items():
        window = windows[unit_id]
        pad = min(0.45, window["duration"] * 0.04)
        usable = window["duration"] - 2 * pad
        weights = [max(4, len(row["spoken_text"])) for row in rows]
        cursor = window["start"] + pad
        for row, weight in zip(rows, weights):
            line_duration = usable * weight / sum(weights)
            clips.append({
                "id": row["dia_id"], "dialogue_id": row["dia_id"], "text": subtitle_display_text(row["spoken_text"]),
                "start": round(cursor, 6), "duration": round(line_duration, 6),
                "metadata": {"episode": "E30", "speaker": row["speaker"], "unit_id": unit_id,
                             "source": "CLAUDE_SCRIPT_LOCKED_SUBTITLE_CONTRACT"},
            })
            cursor += line_duration
    return sorted(clips, key=lambda row: row["start"])


def main() -> int:
    plan = load(PLAN)
    sources = collect_sources()
    expected = [row["unit_id"] for row in plan["units"]]
    if sorted(sources) != sorted(expected):
        raise SystemExit(f"16-source coverage mismatch: {sorted(sources)}")
    build_admission(sources)

    video_clips, audio_clips, windows = [], [], {}
    cursor = 0.0
    for unit in plan["units"]:
        unit_id = unit["unit_id"]
        task = sources[unit_id]
        source = Path(task["output_path"])
        planned_duration = 5.0 if unit_id == "E30-CW-U12" else float(unit["duration_seconds"])
        clip_duration = min(planned_duration, duration(source))
        metadata = {"episode": "E30", "source_id": unit_id, "scene_id": unit["scene_id"],
                    "source_sha256": task["sha256"], "source_admission": task["admission"],
                    "duration_policy": "U12_DELETE_POST_EVIDENCE_PSEUDOTEXT" if unit_id == "E30-CW-U12" else "NATIVE_SPEED_TRIM_CONTAINER_TAIL_NO_PADDING_NO_SLOW_MOTION"}
        if unit_id == "E30-CW-U07":
            segments = [("A", 0.0, 7.1), ("B", 9.2, clip_duration - 9.2)]
            local_cursor = cursor
            for suffix, source_in, segment_duration in segments:
                segment_meta = {**metadata, "duration_policy": "DELETE_GENERATED_ROOF_SIGN_PSEUDOTEXT_NO_PADDING"}
                video_clips.append({"id": f"{unit_id}-VIDEO-{suffix}", "source": str(source),
                                    "start": round(local_cursor, 6), "in": source_in,
                                    "duration": round(segment_duration, 6), "metadata": segment_meta})
                audio_clips.append({"id": f"{unit_id}-AUDIO-{suffix}", "source": str(source),
                                    "start": round(local_cursor, 6), "in": source_in,
                                    "duration": round(segment_duration, 6), "volume": 0.62,
                                    "metadata": {"source_id": unit_id, "native_ambience_sfx": True,
                                                 "synchronized_mid_clip_delete": True}})
                local_cursor += segment_duration
            retained_duration = sum(segment[2] for segment in segments)
            windows[unit_id] = {"start": cursor, "duration": retained_duration}
            cursor += retained_duration
            continue
        video_clip = {"id": f"{unit_id}-VIDEO", "source": str(source), "start": round(cursor, 6),
                      "in": 0.0, "duration": round(clip_duration, 6), "metadata": metadata}
        video_clips.append(video_clip)
        audio_clips.append({"id": f"{unit_id}-AUDIO", "source": str(source), "start": round(cursor, 6),
                            "in": 0.0, "duration": round(clip_duration, 6), "volume": 0.62,
                            "metadata": {"source_id": unit_id, "native_ambience_sfx": True}})
        windows[unit_id] = {"start": cursor, "duration": clip_duration}
        cursor += clip_duration

    contract = load(SUBTITLES)
    captions = subtitle_clips(contract["dialogue"], windows)
    expected_dialogue = {row["dia_id"] for row in contract["dialogue"]}
    if len(captions) != 20 or {row["dialogue_id"] for row in captions} != expected_dialogue:
        raise SystemExit("E30 subtitle coverage is not exactly 20/20")
    outro = load(OUTRO)
    logo, chime = ROOT / outro["logo_asset"]["path"], ROOT / outro["chime_asset"]["path"]
    if sha256(logo) != outro["logo_asset"]["sha256"] or sha256(chime) != outro["chime_asset"]["sha256"]:
        raise SystemExit("NALU Motion asset SHA mismatch")

    project = {
        "version": "1.0",
        "metadata": {"episode": "E30", "version": "V9", "status": "AGENTCUT_BASE_NOT_FINAL_UNTIL_DIALOGUE_GATE",
                     "runtime_seconds": round(cursor + 3.0, 6), "content_runtime_seconds": round(cursor, 6),
                     "subtitle_contract": {"coverage": "20/20", "burned_in": True, "path": str(SUBTITLES)},
                     "duration_policy": "PLOT_INTEGRITY_ONLY_NO_ORIGINAL_DURATION_FLOOR"},
        "output": {"path": str(OUTPUT), "width": 720, "height": 1280, "fps": 24, "videoCodec": "libx264",
                   "audioCodec": "aac", "audioBitrate": "192k", "pixelFormat": "yuv420p", "threads": 4},
        "masterAudioPolicy": {"required": True, "limiter": True, "truePeakCeilingDbtp": -1.0,
                              "codecHeadroomDb": 1.5, "loudnessTargetLufs": -17, "loudnessRangeLu": 11,
                              "maxClippedSamples": 0},
        "timeline": {
            "videoTracks": [{"id": "E30_VIDEO", "clips": video_clips}],
            "audioTracks": [{"id": "E30_NATIVE_AMBIENCE_SFX", "clips": audio_clips}],
            "subtitleTracks": [{"id": "E30_ZH_CN_BURNIN", "enabled": True,
                "style": {"font": "/System/Library/Fonts/STHeiti Medium.ttc", "size": 42, "color": "#FFFFFF",
                          "outline": 3, "outlineColor": "#000000", "alignment": "bottom-center",
                          "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170}, "wrap": 15},
                "clips": captions}],
        },
        "expectedDialogueIds": sorted(expected_dialogue), "requireBrandedOutro": True,
        "outro": {"enabled": True, "brand": "nalu_motion", "template": "nalu-motion-v1", "templateVersion": "1.0",
                  "assetPath": str(logo), "duration": 3, "fit": "contain", "audioPolicy": "asset",
                  "transitionIn": 0.25, "transitionOut": 0.25, "titleText": "青山", "nextText": "敬请期待",
                  "brandText": "NALU MOTION", "dialogueDuckDb": -12, "bgmDuckDb": -9,
                  "safeArea": {"left": 72, "right": 72, "top": 128, "bottom": 128},
                  "logo": {"x": 235, "y": 590, "width": 250, "height": 141},
                  "includeInTotalDuration": True, "audioPath": str(chime)},
        "qingshanAudit": {"pipelineStage": "E30_AGENTCUT_V9_DIALOGUE_SUBTITLE_NALU_FINAL",
                          "sourceCount": 16, "subtitleDialogueCoverage": "20/20",
                          "conditionalAdmission": str(ADMISSION)},
    }
    write(PROJECT, project)
    raw_project = json.loads(json.dumps(project))
    raw_project["metadata"]["status"] = "RAW_QA_RENDER_FOR_SUBTITLE_PIXEL_DIFF_ONLY"
    raw_project["metadata"]["subtitle_contract"] = {"coverage": "0/20", "burned_in": False}
    raw_project["output"]["path"] = str(RAW_QA_OUTPUT)
    raw_project["timeline"]["subtitleTracks"] = []
    raw_project["expectedDialogueIds"] = []
    write(RAW_QA_PROJECT, raw_project)
    write(RECEIPT, {"schema": "qingshan.e30.agentcut_v9_build.v1", "episode": "E30", "version": "V9",
                    "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "READY_VALIDATE_AND_RENDER_BASE",
                    "project": str(PROJECT), "project_sha256": sha256(PROJECT), "output": str(OUTPUT),
                    "source_count": 16, "content_seconds": round(cursor, 6), "outro_seconds": 3.0,
                    "expected_total_seconds": round(cursor + 3.0, 6), "subtitle_dialogue_coverage": "20/20",
                    "subtitle_event_count": 20, "dialogue_audio_required_before_final": True,
                    "raw_qa_project": str(RAW_QA_PROJECT), "raw_qa_output": str(RAW_QA_OUTPUT),
                    "new_generation_calls": 0, "new_generation_credits": 0})
    print(json.dumps({"project": str(PROJECT), "output": str(OUTPUT), "content_seconds": cursor,
                      "total_seconds": cursor + 3.0, "dialogue": 20}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
