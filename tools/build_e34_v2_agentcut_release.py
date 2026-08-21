#!/usr/bin/env python3
"""Build the E34 v2 AgentCut release from admitted native-performance sources."""

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
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e34_claude_writer_v2_400ff6d2_20260723"
CONFIG = PRODUCTION / "video_performance_v2/E34_VIDEO_STREAMING_PERFORMANCE_V2.json"
MAIN_RECEIPT = ROOT / "workflow/tasks/E34_VIDEO_STREAMING_PERFORMANCE_V2_RECEIPT_20260723.json"
SPLIT_RECEIPT = ROOT / "workflow/tasks/E34_U17_SPLIT_REPAIR1_VIDEO_RECEIPT_20260723.json"
MANIFEST = PRODUCTION / "E34_PRODUCTION_MANIFEST_V2.json"
SUBTITLES = PRODUCTION / "E34_SUBTITLE_CONTRACT_V2.json"
OUTRO = PRODUCTION / "E34_NALU_MOTION_OUTRO_CONTRACT_V2.json"
AUDIO_MANIFEST = ROOT / "working_assets/e34_dialogue_audio_refs_v2_20260723/E34_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
BGM_RECEIPT = ROOT / "workflow/tasks/E34_AGENTCUT_BGM_GENERATION_20260723.json"
BGM_CREDIT = ROOT / "workflow/credit_reports/E34_AGENTCUT_BGM_CREDIT_AUDIT_20260723.json"
BGM_QA = ROOT / "qa/e34_v2_streaming_video_compile_20260723/E34_BGM_CANDIDATE_QA_V1.json"
BGM_SOURCE = ROOT / "working_assets/e34_bgm_agentcut_20260723/bgm_candidate_2.mp3"
OCR_ADMISSIONS = ROOT / "qa/e34_v2_streaming_video_compile_20260723/E34_OCR_ONLY_CONDITIONAL_MACHINE_ADMISSIONS_V2.json"
U15_ASR_ADJUDICATION = ROOT / "qa/e34_v2_streaming_video_compile_20260723/E34_U15_DIA021_ASR_HOMOPHONE_ADJUDICATION_V2.json"
SOURCE_ASR = ROOT / "qa/e34_v2_streaming_video_compile_20260723/E34_NATIVE_DIALOGUE_SOURCE_ASR_V2.json"
RUNTIME_POLICY = ROOT / "configs/youtube_shorts_runtime_policy_v1.json"
SOURCE_LOCK = PRODUCTION / "video_performance_v2/E34_V2_LOCKED_SOURCE_MANIFEST.json"
PROJECT = ROOT / "configs/e34_agentcut_v2_release_20260723.json"
OUTPUT = ROOT / "exports/e34/v2_release_20260723/E34_V2_AGENTCUT_SUBTITLED_BGM_OUTRO_NOT_FINAL.mp4"
EDIT_GATE_EVIDENCE = ROOT / "workflow/agentcut/release_gate_evidence/E34_V2_RELEASE_EDIT_GATE_EVIDENCE_BUNDLE.json"
EDIT_GATE_OUT = ROOT / "qa/e34_v2_streaming_video_compile_20260723/unified_edit_gates"
BGM_STEM = ROOT / "exports/e34/v2_release_20260723/E34_V2_BGM_STEM.wav"
BUILD_RECEIPT = ROOT / "workflow/tasks/E34_AGENTCUT_V2_RELEASE_BUILD_RECEIPT_20260723.json"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"

# Keep all dialogue at native speed. Runtime tightening is limited to reviewed,
# dialogue-free heads/tails whose omitted frames contain no new story fact.
TRIM_PLAN = {
    "E34-CW-U01": {"in": 2.0, "duration": 5.0, "reason": "REMOVE_REPEATED_ESTABLISHING_HEAD_KEEP_CONFRONTATION"},
    "E34-CW-U02": {"in": 0.5, "duration": 7.0, "reason": "TIGHTEN_HEAD_AND_TAIL_KEEP_ALL_THREE_AUTHORED_LOCATIONS"},
    "E34-CW-U08": {"in": 1.0, "duration": 7.0, "reason": "REMOVE_REPEATED_ACTION_SETUP_KEEP_HOSTAGE_RESULT"},
}


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
        raise SystemExit(f"Source must contain timed video and native audio: {path}")
    return max(0.01, min(durations) - 0.001)


def display_text(text: str) -> str:
    return re.sub(r"'([^']+)'", r"“\1”", text)


def unit_number(unit_id: str) -> tuple[int, str]:
    suffix = unit_id.rsplit("U", 1)[1]
    return int(re.match(r"\d+", suffix).group()), suffix


def split_dialogue_unit(row: dict) -> str:
    unit_id = row["video_unit_id"]
    if unit_id != "E34-CW-U17":
        return unit_id
    return "E34-CW-U17A" if int(row["dia_id"].rsplit("-", 1)[1]) <= 30 else "E34-CW-U17B"


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
                "id": row["dia_id"], "dialogue_id": row["dia_id"],
                "text": display_text(row["spoken_text"]),
                "start": round(cursor, 6), "duration": round(line_duration, 6),
                "metadata": {
                    "episode": "E34", "speaker": row["speaker"], "unit_id": unit_id,
                    "source": "ROUGH_UNIT_WINDOW_PENDING_NATIVE_SOURCE_ASR_ALIGNMENT",
                },
            })
            cursor += line_duration + gap
    return sorted(captions, key=lambda row: (row["start"], row["id"]))


def collect_source_tasks(config: dict, main_receipt: dict, split_receipt: dict) -> list[dict]:
    conditional = {
        row["candidate_sha256"]: row
        for row in load(OCR_ADMISSIONS)["selections"]
        if row.get("decision") == "CONDITIONAL_MACHINE_ADMISSION"
    }
    reused = config["reused_video_units"][0]
    rows = [{
        "unit_id": reused["unit_id"], "scene_id": "E34-CW-S01",
        "output_path": str(ROOT / reused["output_path"]), "sha256": reused["sha256"],
        "edit_target_duration_seconds": 7.0, "source_state": "QA_PASS_REUSE_NO_NEW_GENERATION",
        "source_receipt": str(CONFIG),
    }]
    for receipt_path, receipt in ((MAIN_RECEIPT, main_receipt), (SPLIT_RECEIPT, split_receipt)):
        for task in receipt["tasks"]:
            unit_id = task["unit_id"]
            if unit_id == "E34-CW-U17" or not task.get("output_path") or not task.get("sha256"):
                continue
            state = task.get("state") or task.get("status")
            if state == "qa_pass":
                source_state = "QA_PASS"
                evidence = str(receipt_path)
            elif task["sha256"] in conditional:
                source_state = "CONDITIONAL_MACHINE_ADMISSION"
                evidence = str(OCR_ADMISSIONS)
            else:
                raise SystemExit(f"Source is neither QA PASS nor conditionally admitted: {unit_id} ({state})")
            rows.append({
                "unit_id": unit_id, "scene_id": task["scene_id"],
                "output_path": task["output_path"], "sha256": task["sha256"],
                "edit_target_duration_seconds": float(task.get("edit_target_duration_seconds") or task["duration_seconds"]),
                "source_state": source_state, "source_receipt": evidence,
            })
    rows.sort(key=lambda row: unit_number(row["unit_id"]))
    expected = {f"E34-CW-U{index:02d}" for index in range(1, 22)} - {"E34-CW-U17"}
    expected |= {"E34-CW-U17A", "E34-CW-U17B"}
    actual = {row["unit_id"] for row in rows}
    if actual != expected or len(rows) != 22:
        raise SystemExit(f"E34 source coverage mismatch: missing={sorted(expected-actual)}, extra={sorted(actual-expected)}")
    return rows


def build_bgm_stem(segments: list[dict], content_duration: float) -> None:
    filters, labels, sequence = [], [], []
    cursor = 0.0
    for segment in segments:
        if segment["start"] > cursor + 0.0005:
            sequence.append({"kind": "silence", "duration": segment["start"] - cursor})
        sequence.append({"kind": "music", **segment})
        cursor = segment["start"] + segment["duration"]
    if cursor < content_duration - 0.0005:
        sequence.append({"kind": "silence", "duration": content_duration - cursor})
    music_indexes = [index for index, row in enumerate(sequence) if row["kind"] == "music"]
    for index, row in enumerate(sequence):
        label = f"a{index}"
        if row["kind"] == "silence":
            filters.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={row['duration']:.6f}[{label}]")
        else:
            fades = ",afade=t=in:st=0:d=0.5" if index == music_indexes[0] else ""
            if index == music_indexes[-1]:
                fades += f",afade=t=out:st={max(0.0, row['duration'] - 1.0):.6f}:d=1.0"
            filters.append(
                f"[0:a]atrim=start={row['source_in']:.6f}:end={row['source_in'] + row['duration']:.6f},"
                f"asetpts=PTS-STARTPTS,volume={row['volume']:.3f}{fades}[{label}]"
            )
        labels.append(f"[{label}]")
    filters.append(f"{''.join(labels)}concat=n={len(labels)}:v=0:a=1[outa]")
    BGM_STEM.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-i", str(BGM_SOURCE),
        "-filter_complex", ";".join(filters), "-map", "[outa]", "-t", f"{content_duration:.6f}",
        "-ar", "48000", "-ac", "2", str(BGM_STEM),
    ], check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--edit-gate-evidence-bundle", type=Path, default=EDIT_GATE_EVIDENCE)
    parser.add_argument("--edit-gate-out-dir", type=Path, default=EDIT_GATE_OUT)
    args = parser.parse_args()
    require_release_builder_gate_admission(
        episode="E34",
        evidence_bundle=args.edit_gate_evidence_bundle,
        out_dir=args.edit_gate_out_dir,
    )
    required = [
        CONFIG, MAIN_RECEIPT, SPLIT_RECEIPT, MANIFEST, SUBTITLES, OUTRO, AUDIO_MANIFEST,
        BGM_RECEIPT, BGM_CREDIT, BGM_QA, BGM_SOURCE, OCR_ADMISSIONS, U15_ASR_ADJUDICATION,
        SOURCE_ASR, RUNTIME_POLICY, FFPROBE, FFMPEG,
    ]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"Missing E34 v2 contract or evidence: {path}")

    config, main_receipt, split_receipt = load(CONFIG), load(MAIN_RECEIPT), load(SPLIT_RECEIPT)
    manifest, subtitle_contract, outro_contract = load(MANIFEST), load(SUBTITLES), load(OUTRO)
    audio_manifest, bgm_receipt = load(AUDIO_MANIFEST), load(BGM_RECEIPT)
    bgm_credit, bgm_qa, source_asr = load(BGM_CREDIT), load(BGM_QA), load(SOURCE_ASR)
    runtime_policy = load(RUNTIME_POLICY)
    if subtitle_contract.get("status") != "LOCKED_FOR_AGENTCUT" or subtitle_contract.get("dialogue_line_count") != 43:
        raise SystemExit("E34 subtitle contract is not locked at 43 lines")
    if audio_manifest.get("status") != "PASS" or audio_manifest.get("line_count") != 43:
        raise SystemExit("E34 dialogue reference manifest is not complete at 43 lines")
    if bgm_receipt.get("release_eligible") is not True or bgm_credit.get("status") != "PASS_EXACT_ISOLATED_LEDGER_NET":
        raise SystemExit("E34 BGM provenance or exact net credit evidence is incomplete")
    if bgm_qa.get("status") != "PASS_SELECTED" or bgm_qa.get("selected_sha256") != sha256(BGM_SOURCE):
        raise SystemExit("E34 BGM selected candidate SHA does not match its QA")
    if source_asr.get("dialogue_line_count") != 43 or source_asr.get("dialogue_line_pass_count") != 42:
        raise SystemExit("E34 source ASR evidence changed; re-run its adjudication")
    if load(U15_ASR_ADJUDICATION).get("status") != "PASS_MACHINE_HOMOPHONE_ADJUDICATION":
        raise SystemExit("E34 U15 native dialogue second-pass adjudication is not PASS")

    source_tasks = collect_source_tasks(config, main_receipt, split_receipt)
    dialogue_by_unit = defaultdict(list)
    for row in audio_manifest["rows"]:
        dialogue_by_unit[split_dialogue_unit(row)].append(row)

    video_clips, native_audio_clips, source_rows, windows = [], [], [], {}
    cursor = 0.0
    for source_task in source_tasks:
        unit_id = source_task["unit_id"]
        source = Path(source_task["output_path"])
        if not source.is_absolute():
            source = ROOT / source
        if not source.is_file() or sha256(source) != source_task["sha256"]:
            raise SystemExit(f"Missing or SHA-mismatched source: {source}")
        available = admitted_av_duration(source)
        trim = TRIM_PLAN.get(unit_id, {})
        source_in = float(trim.get("in", 0.0))
        planned = float(trim.get("duration", source_task["edit_target_duration_seconds"]))
        if source_in + planned > available + 0.08:
            if expected_rows := dialogue_by_unit.get(unit_id, []):
                raise SystemExit(f"Dialogue source {unit_id} is shorter than its reviewed edit range")
            planned = available - source_in
            trim = {
                "in": source_in,
                "duration": planned,
                "reason": "USE_QA_REPAIRED_AVAILABLE_NATIVE_DURATION_NO_PADDING_OR_STRETCH",
            }
        clip_duration = min(planned, available - source_in)
        expected_rows = dialogue_by_unit.get(unit_id, [])
        expected_ids = [row["dia_id"] for row in expected_rows]
        expected_text = "".join(row["spoken_text"] for row in expected_rows)
        metadata = {
            "episode": "E34", "source_id": unit_id, "scene_id": source_task["scene_id"],
            "source_sha256": source_task["sha256"], "source_admission": source_task["source_state"],
            "admission_evidence": source_task["source_receipt"], "expected_dialogue_ids": expected_ids,
            "expected_text": expected_text,
            "duration_policy": "NATIVE_SPEED_REVIEWED_HEAD_TAIL_TRIM_NO_PADDING_NO_SLOW_MOTION",
            "runtime_trim_reason": trim.get("reason", "LOCKED_NATURAL_EDIT_TARGET"),
            "cut_reason": "CLAUDE_SCRIPT_CONTIGUOUS_SCENE_LOCAL_NATURAL_PERFORMANCE_UNIT",
            "cutReason": "CLAUDE_SCRIPT_CONTIGUOUS_SCENE_LOCAL_NATURAL_PERFORMANCE_UNIT",
            "light_key": f"{source_task['scene_id']}::SCENE_AUTHORITY_LOCK",
            "axis_line": f"{source_task['scene_id']}::LOCKED_ACTION_AXIS",
            "eyeline": f"{unit_id}::PRIMARY_ACTION_TARGET",
        }
        video_clips.append({
            "id": f"{unit_id}-VIDEO", "source": str(source), "start": round(cursor, 6),
            "in": source_in, "duration": round(clip_duration, 6), "metadata": metadata,
        })
        native_audio_clips.append({
            "id": f"{unit_id}-AUDIO", "source": str(source), "start": round(cursor, 6),
            "in": source_in, "duration": round(clip_duration, 6), "volume": 0.75,
            "metadata": {**metadata, "native_dialogue_ambience_sfx": True},
        })
        windows[unit_id] = {"start": cursor, "duration": clip_duration}
        source_rows.append({
            "source_id": unit_id, "scene_id": source_task["scene_id"], "path": str(source),
            "sha256": source_task["sha256"], "source_in_seconds": source_in,
            "duration_seconds": round(clip_duration, 6), "admission": source_task["source_state"],
            "evidence": source_task["source_receipt"], "dialogue_ids": expected_ids,
            "runtime_trim_reason": metadata["runtime_trim_reason"],
        })
        cursor += clip_duration

    content_duration = round(cursor, 6)
    total_duration = round(content_duration + 3.0, 6)
    shorts_target = float(runtime_policy["target_max_seconds"])
    shorts_hard_max = float(runtime_policy["hard_max_seconds"])
    if total_duration > shorts_target:
        raise SystemExit(f"E34 exceeds the locked YouTube Shorts target: {total_duration}")

    bgm_start = float(bgm_receipt["selected_candidate"]["timeline_start_seconds"])
    bgm_end = content_duration
    bgm_clips, bgm_segments = [], []
    for source_row in source_rows:
        window = windows[source_row["source_id"]]
        start = max(window["start"], bgm_start)
        end = min(window["start"] + window["duration"], bgm_end)
        if end <= start + 0.001:
            continue
        has_dialogue = bool(source_row["dialogue_ids"])
        volume = 0.08 if has_dialogue else 0.18
        segment = {"start": start, "source_in": start - bgm_start, "duration": end - start,
                   "volume": volume, "has_dialogue": has_dialogue}
        bgm_segments.append(segment)
        bgm_clips.append({
            "id": f"E34-BGM-{source_row['source_id']}", "source": str(BGM_SOURCE),
            "start": round(start, 6), "in": round(segment["source_in"], 6),
            "duration": round(segment["duration"], 6), "volume": volume,
            "metadata": {"dialogue_duck_db": -7.04 if has_dialogue else 0.0,
                         "source_sha256": sha256(BGM_SOURCE),
                         "timeline_policy": "SOURCE_TRIM_WITH_EDGE_FADES_NO_LOOP_NO_STRETCH"},
        })
    bgm_clips[0]["transitionIn"] = {"type": "fade", "duration": 0.5}
    bgm_clips[-1]["transitionOut"] = {"type": "fade", "duration": 1.0}

    captions = rough_captions(dialogue_by_unit, windows)
    expected_dialogue_ids = {row["dia_id"] for row in audio_manifest["rows"]}
    if len(captions) != 43 or {row["dialogue_id"] for row in captions} != expected_dialogue_ids:
        raise SystemExit("E34 subtitle coverage is not exactly 43/43")
    logo, chime = ROOT / outro_contract["logo_asset"], ROOT / outro_contract["chime_asset"]
    if not logo.is_file() or not chime.is_file():
        raise SystemExit("NALU Motion assets are missing")

    SOURCE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROJECT.parent.mkdir(parents=True, exist_ok=True)
    source_lock = {
        "schema": "qingshan.e34.v2.locked_source_manifest.v1", "episode": "E34",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "LOCKED_FOR_AGENTCUT", "source_count": 22, "dialogue_line_count": 43,
        "content_duration_seconds": content_duration, "runtime_trim_review": {
            "path": "qa/e34_v2_streaming_video_compile_20260723/runtime_trim_review",
            "policy": "DIALOGUE_FREE_REVIEWED_HEAD_TAIL_TRIMS_ONLY",
        }, "sources": source_rows,
    }
    SOURCE_LOCK.write_text(json.dumps(source_lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    project = {
        "version": "1.0",
        "metadata": {
            "episode": "E34", "status": "V2_RELEASE_PENDING_NATIVE_ASR_ALIGNMENT_AND_FINAL_GATES",
            "runtime_seconds": total_duration, "content_runtime_seconds": content_duration,
            "source_script": manifest["source_script"], "source_script_sha256": manifest["source_script_sha256"],
            "source_lock_manifest": str(SOURCE_LOCK),
            "subtitle_contract": {"coverage": "43/43", "burned_in": True, "path": str(SUBTITLES)},
            "duration_policy": "YOUTUBE_SHORTS_TARGET_179_HARD_180_DIALOGUE_AND_PLOT_INTEGRITY_PRESERVED",
            "youtube_shorts_runtime_policy": str(RUNTIME_POLICY.relative_to(ROOT)),
            "bgm_contract": {
                "source_type": "GENERATED_EPISODE_BGM", "license_status": "SELF_GENERATED_ACCOUNT_OWNED",
                "dialogue_duck_db": -7.04, "generation_task_id": bgm_receipt["task_id"],
                "generation_receipt": str(BGM_RECEIPT.relative_to(ROOT)), "source_sha256": sha256(BGM_SOURCE),
                "credit_evidence": str(BGM_CREDIT.relative_to(ROOT)),
                "external_commercial_rights_metadata_required": False,
                "ownership_policy": "configs/agentcut_generated_asset_rights_policy_v1.json",
                "timeline_start_seconds": bgm_start, "timeline_end_seconds": bgm_end, "loop_required": False,
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
            "audioTracks": [{"id": "Audio.NativeDialogueSfxAmbience", "clips": native_audio_clips},
                            {"id": "Audio.BGM", "clips": bgm_clips}],
            "subtitleTracks": [{"id": "Subtitle.ZH-CN.BurnIn", "enabled": True,
                "style": {"font": "/System/Library/Fonts/STHeiti Medium.ttc", "size": 42,
                          "color": "#FFFFFF", "outline": 3, "outlineColor": "#000000",
                          "alignment": "bottom-center",
                          "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170}, "wrap": 15},
                "clips": captions}],
        },
        "expectedDialogueIds": sorted(expected_dialogue_ids), "requireBrandedOutro": True,
        "outro": {"enabled": True, "brand": "nalu_motion", "template": "nalu-motion-v1",
                  "templateVersion": "1.0", "assetPath": str(logo), "duration": 3, "fit": "contain",
                  "audioPolicy": "asset", "transitionIn": 0.25, "transitionOut": 0.25,
                  "titleText": "青山", "nextText": "敬请期待", "brandText": "NALU MOTION",
                  "dialogueDuckDb": -12, "bgmDuckDb": -9,
                  "safeArea": {"left": 72, "right": 72, "top": 128, "bottom": 128},
                  "logo": {"x": 235, "y": 590, "width": 250, "height": 141},
                  "includeInTotalDuration": True, "audioPath": str(chime)},
        "qingshanAudit": {"pipelineStage": "E34_V2_RELEASE_BUILD_ASR_QA_LOCK", "sourceCount": 22,
                          "subtitleDialogueCoverage": "43/43", "nativeDialogueSourceRequired": True,
                          "bgmStem": str(BGM_STEM), "originalReviewFailuresPreserved":
                          [str(OCR_ADMISSIONS), str(SOURCE_ASR), str(U15_ASR_ADJUDICATION)]},
    }
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build_bgm_stem(bgm_segments, content_duration)
    receipt = {
        "schema": "qingshan.e34.agentcut_v2_release_build.v1", "episode": "E34",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "READY_FOR_NATIVE_SOURCE_ASR_ALIGNMENT_VALIDATE_AND_RENDER",
        "project": str(PROJECT), "project_sha256": sha256(PROJECT), "output": str(OUTPUT),
        "source_lock_manifest": str(SOURCE_LOCK), "source_lock_sha256": sha256(SOURCE_LOCK),
        "source_count": 22, "content_seconds": content_duration, "outro_seconds": 3.0,
        "expected_total_seconds": total_duration, "youtube_shorts_target_max_seconds": shorts_target,
        "youtube_shorts_hard_max_seconds": shorts_hard_max, "subtitle_dialogue_coverage": "43/43",
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
