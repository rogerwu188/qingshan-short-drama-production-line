#!/usr/bin/env python3
"""Build the E35 AgentCut release from the locked 24 native-performance units."""

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
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e35_claude_writer_v1_416d09e2_20260723"
RECEIPT = ROOT / "workflow/tasks/E35_V1_VIDEO_STREAMING_RECEIPT_R2_20260723.json"
MANIFEST = PRODUCTION / "E35_PRODUCTION_MANIFEST_V1.json"
SUBTITLES = PRODUCTION / "E35_SUBTITLE_CONTRACT_V1.json"
OUTRO = PRODUCTION / "E35_NALU_MOTION_OUTRO_CONTRACT_V1.json"
AUDIO_MANIFEST = ROOT / "working_assets/e35_dialogue_audio_refs_v1_20260723/E35_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1_U01_SPLIT_REPAIR2.json"
OCR_ADMISSIONS = ROOT / "qa/e35_v1_streaming_video_compile_20260723/E35_OCR_ONLY_CONDITIONAL_MACHINE_ADMISSIONS_V1.json"
BGM_RECEIPT = ROOT / "workflow/tasks/E35_AGENTCUT_BGM_GENERATION_20260723.json"
BGM_CREDIT = ROOT / "workflow/credit_reports/E35_AGENTCUT_BGM_CREDIT_AUDIT_20260723.json"
BGM_QA = ROOT / "qa/e35_v1_release_20260723/E35_BGM_CANDIDATE_QA_V1.json"
RUNTIME_POLICY = ROOT / "configs/youtube_shorts_runtime_policy_v1.json"
SOURCE_LOCK = PRODUCTION / "video_performance_v1/E35_V1_LOCKED_SOURCE_MANIFEST.json"
PROJECT = ROOT / "configs/e35_agentcut_v1_release_20260723.json"
OUTPUT = ROOT / "exports/e35/v1_release_20260723/E35_V1_AGENTCUT_SUBTITLED_BGM_OUTRO_NOT_FINAL.mp4"
EDIT_GATE_EVIDENCE = ROOT / "workflow/agentcut/release_gate_evidence/E35_V1_RELEASE_EDIT_GATE_EVIDENCE_BUNDLE.json"
EDIT_GATE_OUT = ROOT / "qa/e35_v1_release_20260723/unified_edit_gates"
BGM_STEM = ROOT / "exports/e35/v1_release_20260723/E35_V1_BGM_STEM.wav"
BUILD_RECEIPT = ROOT / "workflow/tasks/E35_AGENTCUT_V1_RELEASE_BUILD_RECEIPT_20260723.json"
U19_CLEAN = ROOT / "working_assets/e35_agentcut_repairs_20260723/E35_CW_U19_LOWER_EDGE_TEXT_CROP.mp4"
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
        check=True, text=True, capture_output=True,
    )
    streams = json.loads(completed.stdout).get("streams", [])
    durations = [
        float(row["duration"]) for row in streams
        if row.get("codec_type") in {"video", "audio"} and row.get("duration")
    ]
    if len(durations) < 2:
        raise SystemExit(f"source lacks timed native audio and video: {path}")
    return max(0.01, min(durations) - 0.001)


def display_text(text: str) -> str:
    return re.sub(r"'([^']+)'", r"“\1”", text)


def unit_key(unit_id: str) -> tuple[int, str]:
    suffix = unit_id.rsplit("U", 1)[1]
    return int(re.match(r"\d+", suffix).group()), suffix


def prepare_u19(source: Path) -> Path:
    """Remove the model-added lower-edge subtitle with a small 9:16 center crop."""
    if U19_CLEAN.is_file() and U19_CLEAN.stat().st_mtime >= source.stat().st_mtime:
        return U19_CLEAN
    U19_CLEAN.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-vf", "crop=675:1200:22:0,scale=720:1280:flags=lanczos",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "copy", "-movflags", "+faststart", str(U19_CLEAN),
    ], check=True)
    return U19_CLEAN


def collect_sources(receipt: dict, admissions: dict) -> list[dict]:
    conditional = {
        row["candidate_sha256"]: row for row in admissions["selections"]
        if row.get("decision") == "CONDITIONAL_MACHINE_ADMISSION"
    }
    selected = {}
    for task in receipt["tasks"]:
        unit_id = task.get("unit_id")
        if unit_id == "E35-CW-U01" or not task.get("output_path") or not task.get("sha256"):
            continue
        state = task.get("state") or task.get("status")
        if state == "qa_pass":
            admission, evidence = "QA_PASS", str(RECEIPT)
        elif task["sha256"] in conditional:
            admission, evidence = "CONDITIONAL_MACHINE_ADMISSION", str(OCR_ADMISSIONS)
        else:
            raise SystemExit(f"unadmitted source {unit_id}: {state}")
        selected[unit_id] = {
            "unit_id": unit_id,
            "scene_id": task["scene_id"],
            "path": Path(task["output_path"]),
            "sha256": task["sha256"],
            "duration": float(task.get("edit_target_duration_seconds") or task["duration_seconds"]),
            "admission": admission,
            "evidence": evidence,
        }
    expected = {"E35-CW-U01A", "E35-CW-U01B"} | {f"E35-CW-U{i:02d}" for i in range(2, 24)}
    if set(selected) != expected or len(selected) != 24:
        raise SystemExit(f"E35 source coverage mismatch: missing={sorted(expected-set(selected))}, extra={sorted(set(selected)-expected)}")
    return sorted(selected.values(), key=lambda row: unit_key(row["unit_id"]))


def rough_captions(rows_by_unit: dict[str, list[dict]], windows: dict[str, dict]) -> list[dict]:
    captions = []
    for unit_id, rows in rows_by_unit.items():
        window = windows[unit_id]
        weights = [max(1, len(re.findall(r"[\u4e00-\u9fff]", row["spoken_text"]))) for row in rows]
        gap = 0.10
        speech_budget = max(0.5, window["duration"] - 0.50 - gap * (len(rows) - 1))
        cursor = window["start"] + 0.25
        for row, weight in zip(rows, weights):
            duration = speech_budget * weight / sum(weights)
            captions.append({
                "id": row["dia_id"], "dialogue_id": row["dia_id"],
                "text": display_text(row["spoken_text"]),
                "start": round(cursor, 6), "duration": round(duration, 6),
                "metadata": {"episode": "E35", "speaker": row["speaker"], "unit_id": unit_id,
                             "source": "ROUGH_UNIT_WINDOW_PENDING_NATIVE_SOURCE_ASR_ALIGNMENT"},
            })
            cursor += duration + gap
    return sorted(captions, key=lambda row: (row["start"], row["id"]))


def build_bgm_stem(source: Path, start: float, content_duration: float) -> None:
    BGM_STEM.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(source),
        "-filter_complex",
        f"anullsrc=r=48000:cl=stereo,atrim=duration={start:.6f}[sil];"
        f"[0:a]atrim=start=0:end={content_duration-start:.6f},asetpts=PTS-STARTPTS,"
        f"afade=t=in:st=0:d=0.5,afade=t=out:st={content_duration-start-1.0:.6f}:d=1.0[m];"
        "[sil][m]concat=n=2:v=0:a=1[outa]",
        "-map", "[outa]", "-t", f"{content_duration:.6f}", "-ar", "48000", "-ac", "2", str(BGM_STEM),
    ], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edit-gate-evidence-bundle", type=Path, default=EDIT_GATE_EVIDENCE)
    parser.add_argument("--edit-gate-out-dir", type=Path, default=EDIT_GATE_OUT)
    args = parser.parse_args()
    require_release_builder_gate_admission(
        episode="E35",
        evidence_bundle=args.edit_gate_evidence_bundle,
        out_dir=args.edit_gate_out_dir,
    )
    required = [RECEIPT, MANIFEST, SUBTITLES, OUTRO, AUDIO_MANIFEST, OCR_ADMISSIONS,
                BGM_RECEIPT, BGM_CREDIT, BGM_QA, RUNTIME_POLICY, FFPROBE, FFMPEG]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"missing E35 release contract or evidence: {path}")

    receipt, manifest, subtitle_contract, outro_contract = load(RECEIPT), load(MANIFEST), load(SUBTITLES), load(OUTRO)
    audio_manifest, admissions, bgm_receipt, bgm_credit, bgm_qa = (
        load(AUDIO_MANIFEST), load(OCR_ADMISSIONS), load(BGM_RECEIPT), load(BGM_CREDIT), load(BGM_QA)
    )
    runtime_policy = load(RUNTIME_POLICY)
    if subtitle_contract.get("status") != "LOCKED_FOR_AGENTCUT" or subtitle_contract.get("dialogue_line_count") != 47:
        raise SystemExit("subtitle contract is not locked at 47 lines")
    if audio_manifest.get("status") != "PASS" or audio_manifest.get("line_count") != 47:
        raise SystemExit("dialogue reference manifest is not complete at 47 lines")
    if bgm_receipt.get("release_eligible") is not True or bgm_credit.get("status") != "PASS_EXACT_ISOLATED_LEDGER_NET":
        raise SystemExit("BGM generation or exact net credit evidence is incomplete")
    bgm_source = Path(bgm_qa["selected_path"])
    if bgm_qa.get("status") != "PASS_SELECTED" or bgm_qa.get("selected_sha256") != sha256(bgm_source):
        raise SystemExit("selected BGM SHA does not match QA")

    sources = collect_sources(receipt, admissions)
    dialogue_by_unit = defaultdict(list)
    for row in audio_manifest["rows"]:
        dialogue_by_unit[row["video_unit_id"]].append(row)

    video_clips, audio_clips, source_rows, windows = [], [], [], {}
    cursor = 0.0
    for row in sources:
        source = row["path"]
        if not source.is_file() or sha256(source) != row["sha256"]:
            raise SystemExit(f"missing or SHA-mismatched source: {source}")
        rendered_source = prepare_u19(source) if row["unit_id"] == "E35-CW-U19" else source
        available = admitted_av_duration(rendered_source)
        duration = min(row["duration"], available)
        if duration + 0.08 < row["duration"] and dialogue_by_unit.get(row["unit_id"]):
            raise SystemExit(f"dialogue source shorter than locked window: {row['unit_id']}")
        expected_rows = dialogue_by_unit.get(row["unit_id"], [])
        expected_ids = [item["dia_id"] for item in expected_rows]
        metadata = {
            "episode": "E35", "source_id": row["unit_id"], "scene_id": row["scene_id"],
            "source_sha256": sha256(rendered_source), "original_source_sha256": row["sha256"],
            "source_admission": row["admission"], "admission_evidence": row["evidence"],
            "expected_dialogue_ids": expected_ids,
            "expected_text": "".join(item["spoken_text"] for item in expected_rows),
            "duration_policy": "NATIVE_SPEED_NO_PADDING_NO_STRETCH",
            "runtime_trim_reason": "LOCKED_NATURAL_EDIT_TARGET",
            "cut_reason": "CLAUDE_SCRIPT_CONTIGUOUS_SCENE_LOCAL_NATURAL_PERFORMANCE_UNIT",
            "cutReason": "CLAUDE_SCRIPT_CONTIGUOUS_SCENE_LOCAL_NATURAL_PERFORMANCE_UNIT",
            "light_key": f"{row['scene_id']}::SCENE_AUTHORITY_LOCK",
            "axis_line": f"{row['scene_id']}::LOCKED_ACTION_AXIS",
            "eyeline": f"{row['unit_id']}::PRIMARY_ACTION_TARGET",
        }
        if row["unit_id"] == "E35-CW-U19":
            metadata["visual_repair"] = "LOWER_EDGE_MODEL_SUBTITLE_REMOVED_BY_SMALL_9X16_CENTER_CROP"
        clip = {"source": str(rendered_source), "start": round(cursor, 6), "in": 0.0,
                "duration": round(duration, 6), "metadata": metadata}
        video_clips.append({"id": f"{row['unit_id']}-VIDEO", **clip})
        audio_clips.append({"id": f"{row['unit_id']}-AUDIO", **clip, "volume": 0.82})
        windows[row["unit_id"]] = {"start": cursor, "duration": duration}
        source_rows.append({"source_id": row["unit_id"], "scene_id": row["scene_id"],
                            "path": str(rendered_source), "sha256": sha256(rendered_source),
                            "duration_seconds": round(duration, 6), "admission": row["admission"],
                            "evidence": row["evidence"], "dialogue_ids": expected_ids})
        cursor += duration

    content_duration = round(cursor, 6)
    total_duration = round(content_duration + 3.0, 6)
    if total_duration > float(runtime_policy["target_max_seconds"]):
        raise SystemExit(f"E35 exceeds YouTube Shorts target: {total_duration}")
    if content_duration < 175.5:
        raise SystemExit(f"unexpected E35 source loss: {content_duration}")

    bgm_start = float(bgm_receipt["selected_candidate"]["timeline_start_seconds"])
    bgm_clips = []
    for source_row in source_rows:
        window = windows[source_row["source_id"]]
        start = max(window["start"], bgm_start)
        end = window["start"] + window["duration"]
        if end <= start + 0.001:
            continue
        has_dialogue = bool(source_row["dialogue_ids"])
        bgm_clips.append({
            "id": f"E35-BGM-{source_row['source_id']}", "source": str(bgm_source),
            "start": round(start, 6), "in": round(start - bgm_start, 6),
            "duration": round(end - start, 6), "volume": 0.06 if has_dialogue else 0.15,
            "metadata": {"dialogue_duck_db": -8.52 if has_dialogue else 0.0,
                         "source_sha256": sha256(bgm_source),
                         "timeline_policy": "SOURCE_TRIM_WITH_EDGE_FADES_NO_LOOP_NO_STRETCH"},
        })
    bgm_clips[0]["transitionIn"] = {"type": "fade", "duration": 0.5}
    bgm_clips[-1]["transitionOut"] = {"type": "fade", "duration": 1.0}

    captions = rough_captions(dialogue_by_unit, windows)
    expected_ids = {row["dia_id"] for row in audio_manifest["rows"]}
    if len(captions) != 47 or {row["dialogue_id"] for row in captions} != expected_ids:
        raise SystemExit("subtitle coverage is not exactly 47/47")
    logo, chime = ROOT / outro_contract["logo_asset"], ROOT / outro_contract["chime_asset"]
    if not logo.is_file() or not chime.is_file():
        raise SystemExit("NALU Motion assets are missing")

    SOURCE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    source_lock = {
        "schema": "qingshan.e35.v1.locked_source_manifest.v1", "episode": "E35",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "LOCKED_FOR_AGENTCUT", "source_count": 24, "dialogue_line_count": 47,
        "content_duration_seconds": content_duration, "sources": source_rows,
    }
    SOURCE_LOCK.write_text(json.dumps(source_lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    project = {
        "version": "1.0",
        "metadata": {
            "episode": "E35", "status": "V1_RELEASE_PENDING_NATIVE_ASR_ALIGNMENT_AND_FINAL_GATES",
            "runtime_seconds": total_duration, "content_runtime_seconds": content_duration,
            "source_script": manifest["source_script"], "source_script_sha256": manifest["source_script_sha256"],
            "source_lock_manifest": str(SOURCE_LOCK),
            "subtitle_contract": {"coverage": "47/47", "burned_in": True, "path": str(SUBTITLES)},
            "duration_policy": "YOUTUBE_SHORTS_TARGET_179_HARD_180_DIALOGUE_AND_PLOT_INTEGRITY_PRESERVED",
            "bgm_contract": {
                "source_type": "GENERATED_EPISODE_BGM", "license_status": "SELF_GENERATED_ACCOUNT_OWNED",
                "dialogue_duck_db": -8.52, "generation_task_id": bgm_receipt["task_id"],
                "generation_receipt": str(BGM_RECEIPT.relative_to(ROOT)), "source_sha256": sha256(bgm_source),
                "credit_evidence": str(BGM_CREDIT.relative_to(ROOT)),
                "external_commercial_rights_metadata_required": False,
                "ownership_policy": "configs/agentcut_generated_asset_rights_policy_v1.json",
                "timeline_start_seconds": bgm_start, "timeline_end_seconds": content_duration,
                "loop_required": False,
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
            "audioTracks": [{"id": "Audio.NativeDialogueSfxAmbience", "clips": audio_clips},
                            {"id": "Audio.BGM", "clips": bgm_clips}],
            "subtitleTracks": [{"id": "Subtitle.ZH-CN.BurnIn", "enabled": True,
                "style": {"font": "/System/Library/Fonts/STHeiti Medium.ttc", "size": 42,
                          "color": "#FFFFFF", "outline": 3, "outlineColor": "#000000",
                          "alignment": "bottom-center",
                          "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170}, "wrap": 15},
                "clips": captions}],
        },
        "expectedDialogueIds": sorted(expected_ids), "requireBrandedOutro": True,
        "outro": {"enabled": True, "brand": "nalu_motion", "template": "nalu-motion-v1",
                  "templateVersion": "1.0", "assetPath": str(logo), "duration": 3, "fit": "contain",
                  "audioPolicy": "asset", "transitionIn": 0.25, "transitionOut": 0.25,
                  "titleText": "青山", "nextText": "敬请期待", "brandText": "NALU MOTION",
                  "dialogueDuckDb": -12, "bgmDuckDb": -9,
                  "safeArea": {"left": 72, "right": 72, "top": 128, "bottom": 128},
                  "logo": {"x": 235, "y": 590, "width": 250, "height": 141},
                  "includeInTotalDuration": True, "audioPath": str(chime)},
        "qingshanAudit": {"pipelineStage": "E35_V1_RELEASE_BUILD_ASR_QA_LOCK", "sourceCount": 24,
                          "subtitleDialogueCoverage": "47/47", "nativeDialogueSourceRequired": True,
                          "bgmStem": str(BGM_STEM),
                          "originalReviewFailuresPreserved": [str(OCR_ADMISSIONS)]},
    }
    PROJECT.parent.mkdir(parents=True, exist_ok=True)
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build_bgm_stem(bgm_source, bgm_start, content_duration)
    build_receipt = {
        "schema": "qingshan.e35.agentcut_v1_release_build.v1", "episode": "E35",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "READY_FOR_NATIVE_SOURCE_ASR_ALIGNMENT_VALIDATE_AND_RENDER",
        "project": str(PROJECT), "project_sha256": sha256(PROJECT), "output": str(OUTPUT),
        "source_lock_manifest": str(SOURCE_LOCK), "source_lock_sha256": sha256(SOURCE_LOCK),
        "source_count": 24, "content_seconds": content_duration, "outro_seconds": 3.0,
        "expected_total_seconds": total_duration,
        "youtube_shorts_target_max_seconds": float(runtime_policy["target_max_seconds"]),
        "subtitle_dialogue_coverage": "47/47", "subtitle_event_count": len(captions),
        "bgm_source_sha256": sha256(bgm_source), "bgm_start_seconds": bgm_start,
        "bgm_end_seconds": content_duration, "bgm_looped": False,
        "bgm_stem": str(BGM_STEM), "bgm_stem_sha256": sha256(BGM_STEM),
        "logo_sha256": sha256(logo), "chime_sha256": sha256(chime),
    }
    BUILD_RECEIPT.write_text(json.dumps(build_receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(build_receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
