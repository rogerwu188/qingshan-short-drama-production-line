#!/usr/bin/env python3
"""Build the corrected E32 release from the locked V2 native-performance sources."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723"
MANIFEST = PRODUCTION / "E32_PRODUCTION_MANIFEST.json"
GROUPING = PRODUCTION / "E32_VIDEO_UNIT_GROUPING_SPEC_V2.json"
SUBTITLES = PRODUCTION / "E32_SUBTITLE_CONTRACT_V2.json"
OUTRO = PRODUCTION / "E32_NALU_MOTION_OUTRO_CONTRACT_V2.json"
AUDIO_MANIFEST = ROOT / "working_assets/e32_dialogue_audio_refs_v2_20260723/E32_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
BGM_RECEIPT = ROOT / "workflow/tasks/E32_AGENTCUT_BGM_GENERATION_20260723.json"
BGM_CREDIT = ROOT / "workflow/credit_reports/E32_AGENTCUT_BGM_CREDIT_AUDIT_20260723.json"
BGM_SOURCE = ROOT / "working_assets/e32_corrected_release_v2_20260723/bgm/E32_BGM_AGENTCUT_CANDIDATE_1_LOCKED.mp3"
SOURCE_LOCK = PRODUCTION / "video_performance_v2/E32_V2_LOCKED_SOURCE_MANIFEST.json"
PROJECT = ROOT / "configs/e32_agentcut_v2_corrected_release_20260723.json"
OUTPUT = ROOT / "exports/e32/corrected_release_v2_20260723/QINGSHAN_E32_CORRECTED_RELEASE_V2.mp4"
BGM_STEM = ROOT / "exports/e32/corrected_release_v2_20260723/E32_CORRECTED_RELEASE_V2_BGM_STEM.wav"
BUILD_RECEIPT = ROOT / "workflow/tasks/E32_AGENTCUT_V2_CORRECTED_RELEASE_BUILD_RECEIPT_20260723.json"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"


SOURCES = [
    ("E32-CW-U01", "E32-CW-S01", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U01-PERFORMANCE-V3_8d3c7040-ba27-4b09-a22b-1e4abd7abe03_DEDUP_FRAMES.mp4", "165397f6e159e1a7967c47914e47bdc2ce2ade95d4265a775aeba0ab929e2621", "QA_PASS_LOCAL_DEDUP_STATIC_FRAME_REMOVAL", "workflow/tasks/E32_VIDEO_REMAINING_13_NATIVE_VOICE_V3_SUPERVISOR_R2.json"),
    ("E32-CW-U02", "E32-CW-S01", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U02-PERFORMANCE-V9-IDENTITY-VIDEO_3a0b9d5d-4be3-4c1a-be8d-f051decf558c.mp4", "d88f59857e01f60e73919cedf9e8f4c250d49dcd2d97cf56cbc61fd8dd2ad3c5", "ROGER_VISUAL_ADMISSION", "workflow/tasks/E32_CW_U02_V9_ROGER_VISUAL_ADMISSION_20260723.json"),
    ("E32-CW-U03", "E32-CW-S01", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U03-PERFORMANCE-V3_456ba6d8-f642-4656-8651-c289ea27cc25.mp4", "6ed0dd6006f179f2eca02ca218392186a03ca593f8d8f09823dae53e3f3c1d0e", "CONDITIONAL_MACHINE_ADMISSION_OCR_FALSE_POSITIVE", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/qa/E32_U03_U13_OCR_CONDITIONAL_MACHINE_ADMISSION_V1.json"),
    ("E32-CW-U04", "E32-CW-S02", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U04-PERFORMANCE-V2_176afa4a-0569-4e68-8d03-6af68e166c88.mp4", "9b041039a0a299d04194e83deb7e125144c11bb708f84b3de369e7889009a74c", "QA_PASS", "workflow/tasks/E32_VIDEO_U04_CROSS_SPACE_V2_SUPERVISOR.json"),
    ("E32-CW-U05", "E32-CW-S02", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U05-PERFORMANCE-V2_80a96ff6-80d3-491f-ac61-2df68f84e997.mp4", "b03a77334d38fe72edac28262f8c1fd113a98f9e674a491d196dd9eedd481ae5", "QA_PASS", "workflow/tasks/E32_VIDEO_U05_SINGLE_ANCHOR_V2_SUPERVISOR.json"),
    ("E32-CW-U06", "E32-CW-S02", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U06-PERFORMANCE-V3_4e599a07-deda-4914-936f-8713d7699fae.mp4", "da8e528392981808e3f9a64909d501e954eb0c3aa094d1d604e59cef7af72cbe", "QA_PASS", "workflow/tasks/E32_VIDEO_REMAINING_13_NATIVE_VOICE_V3_SUPERVISOR_R2.json"),
    ("E32-CW-U07", "E32-CW-S02", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U07-PERFORMANCE-V2_117792b0-549c-42ef-b9f2-34e73a05d541.mp4", "f8a8395b5315d559e2925a1a7379396c1205dae49e1583f2de1b78c60692cf06", "QA_PASS", "workflow/tasks/E32_VIDEO_U07_EXACT_DIALOGUE_V2_SUPERVISOR.json"),
    ("E32-CW-U08", "E32-CW-S03", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U08-PERFORMANCE-V3_85b01d6a-ce87-47ae-b74c-7f1bd9e41c7c.mp4", "5ba24b087cdc64c4919844682021e2bb2ebdc3e1caec78c0c87ad0e5da89b280", "QA_PASS", "workflow/tasks/E32_VIDEO_REMAINING_13_NATIVE_VOICE_V3_SUPERVISOR_R2.json"),
    ("E32-CW-U09", "E32-CW-S03", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U09-PERFORMANCE-V9-IDENTITY-VIDEO_496ec14d-2758-4795-9e5e-904c02949870.mp4", "028a423104f0c13263d79c0e96de6cedf5f1827d8440b8ae6000349730c61fb6", "CONDITIONAL_MACHINE_ADMISSION", "workflow/tasks/E32_CW_U09_V9_CONDITIONAL_MACHINE_ADMISSION_20260723.json"),
    ("E32-CW-U10", "E32-CW-S03", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U10-PERFORMANCE-V10-IDENTITY-STATE-REEL_20f5719e-9c36-4594-ba28-4ce3c2f80861.mp4", "3184e4d46e4613551712f4ebe74fdb0f259ca3992a068fd1ed8f5e9c4b813c83", "QA_PASS", "workflow/tasks/E32_VIDEO_IDENTITY_STATE_REEL_TRANSPORT_V10_SUPERVISOR.json"),
    ("E32-CW-U11", "E32-CW-S04", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U11-PERFORMANCE-V3_7b7c29f9-07db-4ec9-8a66-32876d855120.mp4", "e6ac28c040b685a6f1dfbaff32e1900df792a65208d89d65a356fd35ed6bcf67", "QA_PASS", "workflow/tasks/E32_VIDEO_REMAINING_13_NATIVE_VOICE_V3_SUPERVISOR_R2.json"),
    ("E32-CW-U12", "E32-CW-S04", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U12-PERFORMANCE-V2_fa11fe7c-c1d4-4da6-9b8c-e998bc3fe96d.mp4", "35ba81dc63f5c0615acd86cf1402cb0edb32bc4b95c8dd0378c645cdf69f0439", "QA_PASS", "workflow/tasks/E32_VIDEO_U12_EXACT_DIALOGUE_V2_SUPERVISOR.json"),
    ("E32-CW-U13", "E32-CW-S04", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U13-PERFORMANCE-V3_89628d90-bc28-4270-963a-3690bdc2682f.mp4", "1fa5b23781c0e0750c602f65d7b31a4d4281f088a7e948be796f67eb471343ef", "CONDITIONAL_MACHINE_ADMISSION_OCR_FALSE_POSITIVE", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/qa/E32_U03_U13_OCR_CONDITIONAL_MACHINE_ADMISSION_V1.json"),
    ("E32-CW-U14", "E32-CW-S04", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U14-PERFORMANCE-V3_f647a949-7fcb-45a7-9fa4-9e4dd2039dea.mp4", "cdae2577317d7dfb86780611d753244efcde80bee154c06781af91c4244971a3", "QA_PASS", "workflow/tasks/E32_VIDEO_REMAINING_13_NATIVE_VOICE_V3_SUPERVISOR_R2.json"),
    ("E32-CW-U15", "E32-CW-S05", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U15-PERFORMANCE-V10-IDENTITY-STATE-REEL_c3848c63-53cc-45be-a041-ca432390ebc1.mp4", "176067c9b2e5faca53d8eb4cf5a2bcdcc9d692561faadacd4e7eb9cb557192cc", "QA_PASS", "workflow/tasks/E32_VIDEO_IDENTITY_STATE_REEL_TRANSPORT_V10_SUPERVISOR.json"),
    ("E32-CW-U16A", "E32-CW-S05", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U16A-PERFORMANCE-V13-CONTIGUOUS-AUDIO_1140762c-b8ab-4514-84d7-62fa6c3b77a0.mp4", "214619b5369b07fcc25f7ca7adcb061495df917be89ee7a4e3d9c587e018beb6", "CONDITIONAL_MACHINE_ADMISSION_PRESENTATION_DEBT", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/qa/E32_U16_NATURAL_SPLIT_SOURCE_ADMISSION_V1.json"),
    ("E32-CW-U16B", "E32-CW-S05", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U16B-PERFORMANCE-V12-SPLIT_c8c0a36e-7686-45b0-8347-d0aa8a558602.mp4", "6bbf1993b2062dc827c55eabd789ecced8004f33ddbaa10df5f3881dbb2a37e0", "QA_PASS", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/qa/E32_U16_NATURAL_SPLIT_SOURCE_ADMISSION_V1.json"),
    ("E32-CW-U17", "E32-CW-S05", "workflow/claude_writer_agent/production/e32_claude_writer_v2_20260723/video_performance_v2/outputs/E32_E32-CW-U17-PERFORMANCE-V10-IDENTITY-STATE-REEL_9a96541a-07ab-4b95-be76-c0ccac3a7522.mp4", "fe408d3440a438cd3f46a96ac47531f85e361a9b2cdfba1277373c27797e8cf7", "QA_PASS", "workflow/tasks/E32_VIDEO_IDENTITY_STATE_REEL_TRANSPORT_V10_SUPERVISOR.json"),
]

SPLIT_DIALOGUE = {
    "E32-CW-U16A": ["E32-DIA-023", "E32-DIA-024"],
    "E32-CW-U16B": ["E32-DIA-025"],
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
    completed = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(completed.stdout.strip())


def admitted_av_duration(path: Path) -> float:
    completed = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    streams = json.loads(completed.stdout).get("streams", [])
    durations = [float(row["duration"]) for row in streams if row.get("codec_type") in {"video", "audio"} and row.get("duration")]
    if not durations:
        raise SystemExit(f"source has no timed audio/video streams: {path}")
    return max(0.01, min(durations) - 0.001)


def display_text(text: str) -> str:
    return re.sub(r"'([^']+)'", r"“\1”", text)


def dialogue_by_source(audio_manifest: dict) -> dict[str, list[dict]]:
    rows = defaultdict(list)
    for row in audio_manifest["rows"]:
        if row["dia_id"] in SPLIT_DIALOGUE["E32-CW-U16A"]:
            rows["E32-CW-U16A"].append(row)
        elif row["dia_id"] in SPLIT_DIALOGUE["E32-CW-U16B"]:
            rows["E32-CW-U16B"].append(row)
        else:
            rows[row["video_unit_id"]].append(row)
    return rows


def rough_captions(rows_by_source: dict[str, list[dict]], windows: dict[str, dict]) -> list[dict]:
    captions = []
    for source_id, rows in rows_by_source.items():
        window = windows[source_id]
        available = window["duration"] - 0.50
        weights = [max(1, len(re.findall(r"[\u4e00-\u9fff]", row["spoken_text"]))) for row in rows]
        gap = 0.12
        speech_budget = max(0.5, available - gap * (len(rows) - 1))
        cursor = window["start"] + 0.25
        for row, weight in zip(rows, weights):
            line_duration = speech_budget * weight / sum(weights)
            captions.append({
                "id": row["dia_id"], "dialogue_id": row["dia_id"],
                "text": display_text(row["spoken_text"]),
                "start": round(cursor, 6), "duration": round(line_duration, 6),
                "metadata": {"episode": "E32", "speaker": row["speaker"], "unit_id": source_id,
                             "source": "ROUGH_UNIT_WINDOW_PENDING_NATIVE_SOURCE_ASR_ALIGNMENT"},
            })
            cursor += line_duration + gap
    return sorted(captions, key=lambda row: (row["start"], row["id"]))


def build_bgm_stem(windows: list[dict], content_duration: float) -> None:
    filters = []
    labels = []
    for index, window in enumerate(windows):
        volume = 0.12 if window["has_dialogue"] else 0.30
        fade_in = ",afade=t=in:st=0:d=0.5" if index == 0 else ""
        fade_out = f",afade=t=out:st={max(0.0, window['duration'] - 1.0):.6f}:d=1.0" if index == len(windows) - 1 else ""
        filters.append(
            f"[0:a]atrim=start={window['start']:.6f}:end={window['start'] + window['duration']:.6f},"
            f"asetpts=PTS-STARTPTS,volume={volume:.3f}{fade_in}{fade_out}[a{index}]"
        )
        labels.append(f"[a{index}]")
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[outa]")
    BGM_STEM.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(BGM_SOURCE),
        "-filter_complex", ";".join(filters), "-map", "[outa]", "-t", f"{content_duration:.6f}",
        "-ar", "48000", "-ac", "2", str(BGM_STEM),
    ], check=True)


def main() -> int:
    for contract in (MANIFEST, GROUPING, SUBTITLES, OUTRO, AUDIO_MANIFEST, BGM_RECEIPT, BGM_CREDIT):
        if not contract.is_file():
            raise SystemExit(f"missing contract: {contract}")
    if sha256(BGM_SOURCE) != "ed3d5daa9ca963c60385b9a9632616f2cfed9bd6ae892cb55e7ebfaba1f7498b":
        raise SystemExit("BGM source SHA mismatch")

    manifest = load(MANIFEST)
    subtitle_contract = load(SUBTITLES)
    audio_manifest = load(AUDIO_MANIFEST)
    if subtitle_contract.get("status") != "LOCKED_FOR_AGENTCUT" or audio_manifest.get("line_count") != 28:
        raise SystemExit("E32 V2 subtitle/dialogue contract is not locked at 28 lines")
    rows_by_source = dialogue_by_source(audio_manifest)

    source_rows = []
    video_clips = []
    native_audio_clips = []
    bgm_clips = []
    windows = {}
    bgm_windows = []
    cursor = 0.0
    for source_id, scene_id, relative, expected_sha, admission, evidence in SOURCES:
        source = ROOT / relative
        if not source.is_file() or sha256(source) != expected_sha:
            raise SystemExit(f"missing or SHA-mismatched source: {source}")
        clip_duration = admitted_av_duration(source)
        expected_rows = rows_by_source.get(source_id, [])
        expected_ids = [row["dia_id"] for row in expected_rows]
        expected_text = "".join(row["spoken_text"] for row in expected_rows)
        metadata = {
            "episode": "E32", "source_id": source_id, "scene_id": scene_id,
            "source_sha256": expected_sha, "source_admission": admission,
            "admission_evidence": evidence, "expected_dialogue_ids": expected_ids,
            "expected_text": expected_text,
            "duration_policy": "NATIVE_SPEED_MINIMUM_AUDIO_VIDEO_STREAM_DURATION_MINUS_1MS_CONTAINER_TAIL_NO_PADDING_NO_SLOW_MOTION",
            "cutReason": "CLAUDE_SCRIPT_CONTIGUOUS_SCENE_LOCAL_NATURAL_PERFORMANCE_UNIT_OR_APPROVED_NATURAL_SPLIT",
        }
        video_clips.append({"id": f"{source_id}-VIDEO", "source": str(source), "start": round(cursor, 6),
                            "in": 0.0, "duration": round(clip_duration, 6), "metadata": metadata})
        native_audio_clips.append({"id": f"{source_id}-AUDIO", "source": str(source), "start": round(cursor, 6),
                                   "in": 0.0, "duration": round(clip_duration, 6), "volume": 0.92,
                                   "metadata": {**metadata, "native_dialogue_ambience_sfx": True}})
        has_dialogue = bool(expected_rows)
        bgm_volume = 0.12 if has_dialogue else 0.30
        bgm_clips.append({"id": f"E32-BGM-{source_id}", "source": str(BGM_SOURCE), "start": round(cursor, 6),
                          "in": round(cursor, 6), "duration": round(clip_duration, 6), "volume": bgm_volume,
                          "transitionIn": ({"type": "fade", "duration": 0.5} if not bgm_clips else None),
                          "metadata": {"dialogue_duck_db": -7.96 if has_dialogue else 0.0,
                                       "source_sha256": sha256(BGM_SOURCE)}})
        if bgm_clips[-1]["transitionIn"] is None:
            del bgm_clips[-1]["transitionIn"]
        windows[source_id] = {"start": cursor, "duration": clip_duration}
        bgm_windows.append({"start": cursor, "duration": clip_duration, "has_dialogue": has_dialogue})
        source_rows.append({"source_id": source_id, "scene_id": scene_id, "path": str(source),
                            "sha256": expected_sha, "duration_seconds": round(clip_duration, 6),
                            "admission": admission, "evidence": evidence, "dialogue_ids": expected_ids})
        cursor += clip_duration

    bgm_clips[-1]["transitionOut"] = {"type": "fade", "duration": 1.0}
    captions = rough_captions(rows_by_source, windows)
    if len(captions) != 28 or {row["dialogue_id"] for row in captions} != {row["dia_id"] for row in audio_manifest["rows"]}:
        raise SystemExit("subtitle coverage is not exactly 28/28")

    outro = load(OUTRO)
    logo = ROOT / outro["logo_asset"]
    chime = ROOT / outro["chime_asset"]
    if not logo.is_file() or not chime.is_file():
        raise SystemExit("NALU Motion assets are missing")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROJECT.parent.mkdir(parents=True, exist_ok=True)
    source_lock = {
        "schema": "qingshan.e32.v2.locked_source_manifest.v1", "episode": "E32",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "LOCKED_FOR_AGENTCUT", "source_count": len(source_rows), "dialogue_line_count": 28,
        "content_duration_seconds": round(cursor, 6), "sources": source_rows,
    }
    SOURCE_LOCK.write_text(json.dumps(source_lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    project = {
        "version": "1.0",
        "metadata": {
            "episode": "E32", "status": "CORRECTED_RELEASE_V2_PENDING_ASR_ALIGNMENT_AND_FINAL_GATES",
            "runtime_seconds": round(cursor + 3.0, 6), "content_runtime_seconds": round(cursor, 6),
            "source_script": manifest["source_script"], "source_script_sha256": manifest["source_script_sha256"],
            "source_lock_manifest": str(SOURCE_LOCK),
            "subtitle_contract": {"coverage": "28/28", "burned_in": True, "path": str(SUBTITLES)},
            "duration_policy": "PLOT_INTEGRITY_ONLY_NO_ORIGINAL_DURATION_FLOOR",
            "bgm_contract": {
                "source_type": "GENERATED_EPISODE_BGM", "license_status": "SELF_GENERATED_ACCOUNT_OWNED",
                "dialogue_duck_db": -7.96, "generation_task_id": "dfa1a061-644c-49a3-a498-f3173f7db72f",
                "generation_receipt": str(BGM_RECEIPT.relative_to(ROOT)),
                "source_sha256": sha256(BGM_SOURCE), "credit_evidence": str(BGM_CREDIT.relative_to(ROOT)),
                "external_commercial_rights_metadata_required": False,
                "authorization_ref": "ROGER-20260723-AGENT-GENERATED-BGM-PROVENANCE",
            },
        },
        "output": {"path": str(OUTPUT), "width": 720, "height": 1280, "fps": 24,
                   "videoCodec": "libx264", "audioCodec": "aac", "audioBitrate": "192k",
                   "pixelFormat": "yuv420p", "threads": 4},
        "masterAudioPolicy": {"required": True, "limiter": True, "truePeakCeilingDbtp": -1.0,
                              "codecHeadroomDb": 1.5, "loudnessTargetLufs": -16,
                              "loudnessRangeLu": 11, "maxClippedSamples": 0},
        "timeline": {
            "videoTracks": [{"id": "Video.Main", "clips": video_clips}],
            "audioTracks": [
                {"id": "Audio.NativeDialogueSfxAmbience", "clips": native_audio_clips},
                {"id": "Audio.BGM", "clips": bgm_clips},
            ],
            "subtitleTracks": [{"id": "Subtitle.ZH-CN.BurnIn", "enabled": True,
                "style": {"font": "/System/Library/Fonts/STHeiti Medium.ttc", "size": 42,
                          "color": "#FFFFFF", "outline": 3, "outlineColor": "#000000",
                          "alignment": "bottom-center",
                          "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170}, "wrap": 15},
                "clips": captions}],
        },
        "expectedDialogueIds": sorted(row["dia_id"] for row in audio_manifest["rows"]),
        "requireBrandedOutro": True,
        "outro": {"enabled": True, "brand": "nalu_motion", "template": "nalu-motion-v1",
                  "templateVersion": "1.0", "assetPath": str(logo), "duration": 3, "fit": "contain",
                  "audioPolicy": "asset", "transitionIn": 0.25, "transitionOut": 0.25,
                  "titleText": "青山", "nextText": "敬请期待", "brandText": "NALU MOTION",
                  "dialogueDuckDb": -12, "bgmDuckDb": -9,
                  "safeArea": {"left": 72, "right": 72, "top": 128, "bottom": 128},
                  "logo": {"x": 235, "y": 590, "width": 250, "height": 141},
                  "includeInTotalDuration": True, "audioPath": str(chime)},
        "qingshanAudit": {"pipelineStage": "E32_CORRECTED_RELEASE_V2_BUILD_ASR_QA_LOCK",
                          "sourceCount": len(video_clips), "subtitleDialogueCoverage": "28/28",
                          "nativeDialogueSourceRequired": True, "bgmStem": str(BGM_STEM)},
    }
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build_bgm_stem(bgm_windows, cursor)
    receipt = {
        "schema": "qingshan.e32.agentcut_v2_corrected_release_build.v1", "episode": "E32",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "READY_FOR_NATIVE_SOURCE_ASR_ALIGNMENT_VALIDATE_AND_RENDER",
        "project": str(PROJECT), "project_sha256": sha256(PROJECT), "output": str(OUTPUT),
        "source_lock_manifest": str(SOURCE_LOCK), "source_lock_sha256": sha256(SOURCE_LOCK),
        "source_count": len(video_clips), "content_seconds": round(cursor, 6), "outro_seconds": 3.0,
        "expected_total_seconds": round(cursor + 3.0, 6), "subtitle_dialogue_coverage": "28/28",
        "subtitle_event_count": len(captions), "bgm_source_sha256": sha256(BGM_SOURCE),
        "bgm_stem": str(BGM_STEM), "bgm_stem_sha256": sha256(BGM_STEM),
        "logo_sha256": sha256(logo), "chime_sha256": sha256(chime),
    }
    BUILD_RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
