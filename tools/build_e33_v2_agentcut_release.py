#!/usr/bin/env python3
"""Build E33 v2 from the locked 23 native-performance sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from tools.episode_stage_gate_runner import require_release_builder_gate_admission
except ModuleNotFoundError:
    from episode_stage_gate_runner import require_release_builder_gate_admission


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v2_e19276d4_20260723"
CONFIG = PRODUCTION / "video_performance_v2/E33_VIDEO_FINAL_PERFORMANCE_V2.json"
SELECTION = PRODUCTION / "video_performance_v2/E33_VIDEO_SOURCE_SELECTION_V2.json"
MANIFEST = PRODUCTION / "E33_PRODUCTION_MANIFEST_V2.json"
SUBTITLES = PRODUCTION / "E33_SUBTITLE_CONTRACT_V2.json"
OUTRO = PRODUCTION / "E33_NALU_MOTION_OUTRO_CONTRACT_V2.json"
AUDIO_MANIFEST = ROOT / "working_assets/e33_dialogue_audio_refs_v2_20260723/E33_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
BGM_RECEIPT = ROOT / "workflow/tasks/E33_AGENTCUT_BGM_GENERATION_20260723.json"
BGM_CREDIT = ROOT / "workflow/credit_reports/E33_AGENTCUT_BGM_CREDIT_AUDIT_20260723.json"
BGM_QA = ROOT / "qa/e33_v2_final_video_source_review_20260723/E33_BGM_CANDIDATE_QA_V1.json"
BGM_SOURCE = ROOT / "working_assets/e33_bgm_agentcut_20260723/bgm_candidate_2.mp3"
OCR_ADMISSIONS = PRODUCTION / "video_performance_v2/qa/E33_V2_OCR_ONLY_CONDITIONAL_MACHINE_ADMISSIONS_V1.json"
U16_REPAIR = ROOT / "workflow/tasks/E33_U16_R8_NATIVE_CAPTION_PIXEL_INPAINT_REPAIR_20260723.json"
RUNTIME_POLICY = ROOT / "configs/youtube_shorts_runtime_policy_v1.json"
SOURCE_LOCK = PRODUCTION / "video_performance_v2/E33_V2_LOCKED_SOURCE_MANIFEST.json"
PROJECT = ROOT / "configs/e33_agentcut_v2_release_20260723.json"
OUTPUT = ROOT / "exports/e33/v2_release_20260723/E33_V2_AGENTCUT_SUBTITLED_BGM_OUTRO_NOT_FINAL.mp4"
EDIT_GATE_EVIDENCE = ROOT / "workflow/agentcut/release_gate_evidence/E33_V2_RELEASE_EDIT_GATE_EVIDENCE_BUNDLE.json"
EDIT_GATE_OUT = ROOT / "qa/e33_v2_final_video_source_review_20260723/unified_edit_gates"
BGM_STEM = ROOT / "exports/e33/v2_release_20260723/E33_V2_BGM_STEM.wav"
BUILD_RECEIPT = ROOT / "workflow/tasks/E33_AGENTCUT_V2_RELEASE_BUILD_RECEIPT_20260723.json"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def admitted_av_duration(path: Path) -> float:
    completed = subprocess.run(
        [str(FFPROBE), "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", str(path)],
        check=True,
        text=True,
        capture_output=True,
    )
    streams = json.loads(completed.stdout).get("streams", [])
    durations = [float(row["duration"]) for row in streams if row.get("codec_type") in {"video", "audio"} and row.get("duration")]
    if len(durations) < 2:
        raise SystemExit(f"Source must contain timed video and native audio: {path}")
    return max(0.01, min(durations) - 0.001)


def display_text(text: str) -> str:
    return re.sub(r"'([^']+)'", r"“\1”", text)


def rough_captions(rows_by_unit: dict[str, list[dict]], windows: dict[str, dict]) -> list[dict]:
    captions = []
    for unit_id, rows in rows_by_unit.items():
        window = windows[unit_id]
        available = window["duration"] - 0.50
        weights = [max(1, len(re.findall(r"[\u4e00-\u9fff]", row["spoken_text"]))) for row in rows]
        gap = 0.12
        speech_budget = max(0.5, available - gap * (len(rows) - 1))
        cursor = window["start"] + 0.25
        for row, weight in zip(rows, weights):
            line_duration = speech_budget * weight / sum(weights)
            captions.append({
                "id": row["dia_id"],
                "dialogue_id": row["dia_id"],
                "text": display_text(row["spoken_text"]),
                "start": round(cursor, 6),
                "duration": round(line_duration, 6),
                "metadata": {
                    "episode": "E33",
                    "speaker": row["speaker"],
                    "unit_id": unit_id,
                    "source": "ROUGH_UNIT_WINDOW_PENDING_NATIVE_SOURCE_ASR_ALIGNMENT",
                },
            })
            cursor += line_duration + gap
    return sorted(captions, key=lambda row: (row["start"], row["id"]))


def build_bgm_stem(segments: list[dict], content_duration: float) -> None:
    filters = []
    labels = []
    cursor = 0.0
    sequence = []
    for segment in segments:
        if segment["start"] > cursor + 0.0005:
            sequence.append({"kind": "silence", "duration": segment["start"] - cursor})
        sequence.append({"kind": "music", **segment})
        cursor = segment["start"] + segment["duration"]
    if cursor < content_duration - 0.0005:
        sequence.append({"kind": "silence", "duration": content_duration - cursor})

    music_indexes = [index for index, row in enumerate(sequence) if row["kind"] == "music"]
    first_music = music_indexes[0]
    last_music = music_indexes[-1]
    for index, row in enumerate(sequence):
        label = f"a{index}"
        if row["kind"] == "silence":
            filters.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={row['duration']:.6f}[{label}]")
        else:
            fades = ""
            if index == first_music:
                fades += ",afade=t=in:st=0:d=0.5"
            if index == last_music:
                fades += f",afade=t=out:st={max(0.0, row['duration'] - 1.0):.6f}:d=1.0"
            filters.append(
                f"[0:a]atrim=start={row['source_in']:.6f}:end={row['source_in'] + row['duration']:.6f},"
                f"asetpts=PTS-STARTPTS,volume={row['volume']:.3f}{fades}[{label}]"
            )
        labels.append(f"[{label}]")
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[outa]")
    BGM_STEM.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(BGM_SOURCE),
            "-filter_complex", ";".join(filters), "-map", "[outa]", "-t", f"{content_duration:.6f}",
            "-ar", "48000", "-ac", "2", str(BGM_STEM),
        ],
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edit-gate-evidence-bundle", type=Path, default=EDIT_GATE_EVIDENCE)
    parser.add_argument("--edit-gate-out-dir", type=Path, default=EDIT_GATE_OUT)
    args = parser.parse_args()
    require_release_builder_gate_admission(
        episode="E33",
        evidence_bundle=args.edit_gate_evidence_bundle,
        out_dir=args.edit_gate_out_dir,
    )
    required = [
        CONFIG, SELECTION, MANIFEST, SUBTITLES, OUTRO, AUDIO_MANIFEST, BGM_RECEIPT,
        BGM_CREDIT, BGM_QA, BGM_SOURCE, OCR_ADMISSIONS, U16_REPAIR, RUNTIME_POLICY,
    ]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"Missing E33 v2 contract or evidence: {path}")

    config = load(CONFIG)
    selection = load(SELECTION)
    manifest = load(MANIFEST)
    subtitle_contract = load(SUBTITLES)
    outro_contract = load(OUTRO)
    audio_manifest = load(AUDIO_MANIFEST)
    bgm_receipt = load(BGM_RECEIPT)
    bgm_credit = load(BGM_CREDIT)
    bgm_qa = load(BGM_QA)
    runtime_policy = load(RUNTIME_POLICY)
    if len(config.get("tasks") or []) != 23 or selection.get("source_count") != 23:
        raise SystemExit("E33 v2 source coverage is not exactly 23/23")
    if not selection.get("all_sources_have_audio_stream"):
        raise SystemExit("At least one selected E33 source has no native audio stream")
    if subtitle_contract.get("status") != "LOCKED_FOR_AGENTCUT" or subtitle_contract.get("dialogue_line_count") != 25:
        raise SystemExit("E33 v2 subtitle contract is not locked at 25 lines")
    if audio_manifest.get("status") != "PASS" or audio_manifest.get("line_count") != 25:
        raise SystemExit("E33 v2 dialogue audio manifest is not complete at 25 lines")
    if bgm_receipt.get("release_eligible") is not True or bgm_credit.get("status") != "PASS_EXACT_ISOLATED_LEDGER_NET":
        raise SystemExit("E33 BGM provenance or exact credit evidence is incomplete")
    if bgm_qa.get("status") != "PASS_SELECTED" or bgm_qa.get("selected_sha256") != sha256(BGM_SOURCE):
        raise SystemExit("E33 BGM selected candidate SHA does not match its QA")

    selected = {row["unit_id"]: row for row in selection["rows"]}
    dialogue_by_unit = defaultdict(list)
    for row in audio_manifest["rows"]:
        dialogue_by_unit[row["video_unit_id"]].append(row)

    video_clips = []
    native_audio_clips = []
    source_rows = []
    windows = {}
    cursor = 0.0
    for task in config["tasks"]:
        unit_id = task["unit_id"]
        source_row = selected.get(unit_id)
        if not source_row:
            raise SystemExit(f"Missing selected source: {unit_id}")
        source = Path(source_row["output_path"])
        if not source.is_file() or sha256(source) != source_row["sha256"]:
            raise SystemExit(f"Missing or SHA-mismatched source: {source}")
        planned = float(task.get("edit_target_duration_seconds") or task.get("duration_seconds") or task.get("duration"))
        available = admitted_av_duration(source)
        if planned > available + 0.08:
            raise SystemExit(f"Source {unit_id} is shorter than its locked natural edit target")
        clip_duration = min(planned, available)
        expected_rows = dialogue_by_unit.get(unit_id, [])
        expected_ids = [row["dia_id"] for row in expected_rows]
        expected_text = "".join(row["spoken_text"] for row in expected_rows)
        metadata = {
            "episode": "E33",
            "source_id": unit_id,
            "scene_id": task["scene_id"],
            "source_sha256": source_row["sha256"],
            "source_admission": source_row["source_state"],
            "admission_evidence": source_row["source_receipt"],
            "expected_dialogue_ids": expected_ids,
            "expected_text": expected_text,
            "duration_policy": "NATIVE_SPEED_LOCKED_TARGET_TRIM_CONTAINER_TAIL_NO_PADDING_NO_SLOW_MOTION",
            "cut_reason": "CLAUDE_SCRIPT_CONTIGUOUS_SCENE_LOCAL_NATURAL_PERFORMANCE_UNIT",
            "cutReason": "CLAUDE_SCRIPT_CONTIGUOUS_SCENE_LOCAL_NATURAL_PERFORMANCE_UNIT",
            "light_key": f"{task['scene_id']}::SCENE_AUTHORITY_LOCK",
            "axis_line": f"{task['scene_id']}::LOCKED_ACTION_AXIS",
            "eyeline": f"{unit_id}::PRIMARY_ACTION_TARGET",
        }
        video_clips.append({
            "id": f"{unit_id}-VIDEO", "source": str(source), "start": round(cursor, 6),
            "in": 0.0, "duration": round(clip_duration, 6), "metadata": metadata,
        })
        native_audio_clips.append({
            "id": f"{unit_id}-AUDIO", "source": str(source), "start": round(cursor, 6),
            "in": 0.0, "duration": round(clip_duration, 6), "volume": 0.75,
            "metadata": {**metadata, "native_dialogue_ambience_sfx": True},
        })
        windows[unit_id] = {"start": cursor, "duration": clip_duration}
        source_rows.append({
            "source_id": unit_id, "scene_id": task["scene_id"], "path": str(source),
            "sha256": source_row["sha256"], "duration_seconds": round(clip_duration, 6),
            "admission": source_row["source_state"], "evidence": source_row["source_receipt"],
            "dialogue_ids": expected_ids,
        })
        cursor += clip_duration

    content_duration = round(cursor, 6)
    manifest_runtime = float(manifest["runtime_seconds"])
    if abs(content_duration - manifest_runtime) > 0.01:
        raise SystemExit(
            "E33 v2 locked content runtime does not match the Claude production manifest: "
            f"timeline={content_duration}, manifest={manifest_runtime}"
        )
    total_duration = content_duration + 3.0
    shorts_target = float(runtime_policy["target_max_seconds"])
    shorts_hard_max = float(runtime_policy["hard_max_seconds"])
    if total_duration > shorts_hard_max:
        raise SystemExit(f"E33 v2 exceeds the YouTube Shorts hard runtime: {total_duration}")

    bgm_start = float(bgm_receipt["selected_candidate"]["timeline_start_seconds"])
    bgm_end = min(content_duration, float(bgm_receipt["selected_candidate"]["natural_end_seconds"]))
    bgm_clips = []
    bgm_segments = []
    for source_row in source_rows:
        window = windows[source_row["source_id"]]
        start = max(window["start"], bgm_start)
        end = min(window["start"] + window["duration"], bgm_end)
        if end <= start + 0.001:
            continue
        has_dialogue = bool(source_row["dialogue_ids"])
        volume = 0.08 if has_dialogue else 0.18
        segment = {
            "start": start,
            "source_in": start - bgm_start,
            "duration": end - start,
            "volume": volume,
            "has_dialogue": has_dialogue,
        }
        bgm_segments.append(segment)
        clip = {
            "id": f"E33-BGM-{source_row['source_id']}", "source": str(BGM_SOURCE),
            "start": round(start, 6), "in": round(segment["source_in"], 6),
            "duration": round(segment["duration"], 6), "volume": volume,
            "metadata": {
                "dialogue_duck_db": -7.04 if has_dialogue else 0.0,
                "source_sha256": sha256(BGM_SOURCE),
                "timeline_policy": "NATURAL_DURATION_NO_LOOP_NO_STRETCH",
            },
        }
        bgm_clips.append(clip)
    if not bgm_clips:
        raise SystemExit("E33 BGM timeline is empty")
    bgm_clips[0]["transitionIn"] = {"type": "fade", "duration": 0.5}
    bgm_clips[-1]["transitionOut"] = {"type": "fade", "duration": 1.0}

    captions = rough_captions(dialogue_by_unit, windows)
    expected_dialogue_ids = {row["dia_id"] for row in audio_manifest["rows"]}
    if len(captions) != 25 or {row["dialogue_id"] for row in captions} != expected_dialogue_ids:
        raise SystemExit("E33 subtitle coverage is not exactly 25/25")

    logo = ROOT / outro_contract["logo_asset"]
    chime = ROOT / outro_contract["chime_asset"]
    if not logo.is_file() or not chime.is_file():
        raise SystemExit("NALU Motion assets are missing")

    SOURCE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROJECT.parent.mkdir(parents=True, exist_ok=True)
    source_lock = {
        "schema": "qingshan.e33.v2.locked_source_manifest.v1",
        "episode": "E33",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "LOCKED_FOR_AGENTCUT",
        "source_count": len(source_rows),
        "dialogue_line_count": 25,
        "content_duration_seconds": content_duration,
        "sources": source_rows,
    }
    SOURCE_LOCK.write_text(json.dumps(source_lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    project = {
        "version": "1.0",
        "metadata": {
            "episode": "E33",
            "status": "V2_RELEASE_PENDING_NATIVE_ASR_ALIGNMENT_AND_FINAL_GATES",
            "runtime_seconds": total_duration,
            "content_runtime_seconds": content_duration,
            "source_script": manifest["source_script"],
            "source_script_sha256": manifest["source_script_sha256"],
            "source_lock_manifest": str(SOURCE_LOCK),
            "subtitle_contract": {"coverage": "25/25", "burned_in": True, "path": str(SUBTITLES)},
            "duration_policy": "YOUTUBE_SHORTS_TARGET_179_HARD_180_PLOT_AND_DIALOGUE_INTEGRITY_PRESERVED",
            "youtube_shorts_runtime_policy": str(RUNTIME_POLICY.relative_to(ROOT)),
            "bgm_contract": {
                "source_type": "GENERATED_EPISODE_BGM",
                "license_status": "SELF_GENERATED_ACCOUNT_OWNED",
                "dialogue_duck_db": -7.04,
                "generation_task_id": bgm_receipt["task_id"],
                "generation_receipt": str(BGM_RECEIPT.relative_to(ROOT)),
                "source_sha256": sha256(BGM_SOURCE),
                "credit_evidence": str(BGM_CREDIT.relative_to(ROOT)),
                "external_commercial_rights_metadata_required": False,
                "ownership_policy": "configs/agentcut_generated_asset_rights_policy_v1.json",
                "timeline_start_seconds": bgm_start,
                "timeline_end_seconds": bgm_end,
                "loop_required": False,
            },
        },
        "output": {
            "path": str(OUTPUT), "width": 720, "height": 1280, "fps": 24,
            "videoCodec": "libx264", "audioCodec": "aac", "audioBitrate": "192k",
            "pixelFormat": "yuv420p", "threads": 4,
        },
        "masterAudioPolicy": {
            "required": True, "limiter": True, "truePeakCeilingDbtp": -1.0,
            "codecHeadroomDb": 1.5, "loudnessTargetLufs": -16,
            "loudnessRangeLu": 11, "maxClippedSamples": 0,
        },
        "timeline": {
            "videoTracks": [{"id": "Video.Main", "clips": video_clips}],
            "audioTracks": [
                {"id": "Audio.NativeDialogueSfxAmbience", "clips": native_audio_clips},
                {"id": "Audio.BGM", "clips": bgm_clips},
            ],
            "subtitleTracks": [{
                "id": "Subtitle.ZH-CN.BurnIn", "enabled": True,
                "style": {
                    "font": "/System/Library/Fonts/STHeiti Medium.ttc", "size": 42,
                    "color": "#FFFFFF", "outline": 3, "outlineColor": "#000000",
                    "alignment": "bottom-center",
                    "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170}, "wrap": 15,
                },
                "clips": captions,
            }],
        },
        "expectedDialogueIds": sorted(expected_dialogue_ids),
        "requireBrandedOutro": True,
        "outro": {
            "enabled": True, "brand": "nalu_motion", "template": "nalu-motion-v1",
            "templateVersion": "1.0", "assetPath": str(logo), "duration": 3,
            "fit": "contain", "audioPolicy": "asset", "transitionIn": 0.25,
            "transitionOut": 0.25, "titleText": "青山", "nextText": "敬请期待",
            "brandText": "NALU MOTION", "dialogueDuckDb": -12, "bgmDuckDb": -9,
            "safeArea": {"left": 72, "right": 72, "top": 128, "bottom": 128},
            "logo": {"x": 235, "y": 590, "width": 250, "height": 141},
            "includeInTotalDuration": True, "audioPath": str(chime),
        },
        "qingshanAudit": {
            "pipelineStage": "E33_V2_RELEASE_BUILD_ASR_QA_LOCK",
            "sourceCount": 23,
            "subtitleDialogueCoverage": "25/25",
            "nativeDialogueSourceRequired": True,
            "bgmStem": str(BGM_STEM),
            "originalReviewFailuresPreserved": [str(OCR_ADMISSIONS), str(U16_REPAIR)],
        },
    }
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build_bgm_stem(bgm_segments, content_duration)
    receipt = {
        "schema": "qingshan.e33.agentcut_v2_release_build.v1",
        "episode": "E33",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "READY_FOR_NATIVE_SOURCE_ASR_ALIGNMENT_VALIDATE_AND_RENDER",
        "project": str(PROJECT), "project_sha256": sha256(PROJECT), "output": str(OUTPUT),
        "source_lock_manifest": str(SOURCE_LOCK), "source_lock_sha256": sha256(SOURCE_LOCK),
        "source_count": 23, "content_seconds": content_duration, "outro_seconds": 3.0,
        "expected_total_seconds": total_duration, "youtube_shorts_target_max_seconds": shorts_target,
        "youtube_shorts_hard_max_seconds": shorts_hard_max, "subtitle_dialogue_coverage": "25/25",
        "subtitle_event_count": len(captions), "bgm_source_sha256": sha256(BGM_SOURCE),
        "bgm_start_seconds": bgm_start, "bgm_end_seconds": bgm_end, "bgm_looped": False,
        "bgm_stem": str(BGM_STEM), "bgm_stem_sha256": sha256(BGM_STEM),
        "logo_sha256": sha256(logo), "chime_sha256": sha256(chime),
    }
    BUILD_RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
