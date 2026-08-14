#!/usr/bin/env python3
"""Build E38 from SHA-locked accepted sources with subtitles, BGM, and outro."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "workflow/claude_writer_agent/production/e38_claude_writer_v2_3f08265c_20260804/E38_PRODUCTION_PLAN_V1.json"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E38剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E38_manifest_v2.json"
PROJECT = ROOT / "configs/e38_agentcut_v1_accepted_bgm_subtitles_nulu_outro_20260804.json"
REGISTRY = ROOT / "qa/e38_agentcut_20260804/v1/E38_ACCEPTED_SOURCE_REGISTRY_V1.json"
BUILD_RECEIPT = ROOT / "workflow/tasks/E38_AGENTCUT_V1_BUILD_RECEIPT_20260804.json"
OUTPUT = ROOT / "exports/e38/agentcut_v1_accepted_bgm_subtitles_nulu_outro_20260804/E38_AGENTCUT_V1_ACCEPTED_BGM_SUBTITLES_NULU_OUTRO_NOT_FINAL.mp4"
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"

ACCEPTED_VIDEO = {
    "U01": ROOT / "working_assets/e38_video_20260804/u01_r2_textless_pro/E38-U01-R2.mp4",
    "U02": ROOT / "working_assets/e38_video_20260804/pro_v1/U02.mp4",
    "U03": ROOT / "working_assets/e38_video_20260804/pro_v1/U03.mp4",
    "U04": ROOT / "working_assets/e38_video_20260804/u04_r2_textless_pro/E38-U04-R2-DOF-TEXT-REMOVED.mp4",
    "U05": ROOT / "working_assets/e38_video_20260804/pro_v1/U05.mp4",
    "U06": ROOT / "working_assets/e38_video_20260804/pro_v1/U06.mp4",
    "U07": ROOT / "working_assets/e38_video_20260804/u07_r2_multi_keyframe_pro/E38-U07-R2.mp4",
    "U08": ROOT / "working_assets/e38_video_20260804/u08_r3_all_actor_motion_pro/E38-U08-R3.mp4",
    "U09": ROOT / "working_assets/e38_video_20260804/pro_v1/U09.mp4",
    "U10": ROOT / "working_assets/e38_video_20260804/pro_v1/U10.mp4",
    "U11": ROOT / "working_assets/e38_video_20260804/pro_v1/U11.mp4",
    "U12": ROOT / "working_assets/e38_video_20260804/pro_v1/U12.mp4",
    "U13": ROOT / "working_assets/e38_video_20260804/pro_v1/U13.mp4",
    "U14": ROOT / "working_assets/e38_video_20260804/pro_v1/U14.mp4",
}

# U01/U04 visual repairs intentionally keep the performer silent. Their already-paid
# original character audio is admissible only as explicit closed-mouth voice-over;
# it must never be represented as lip-synced dialogue.
ACCEPTED_AUDIO = {
    **ACCEPTED_VIDEO,
    "U01": ROOT / "working_assets/e38_agentcut_audio_20260804/E38-U01-NATIVE-DIALOGUE-RECOVERED.wav",
    "U04": ROOT / "working_assets/e38_agentcut_audio_20260804/E38-U04-NATIVE-DIALOGUE-RECOVERED.wav",
}

SUPERSEDED = {
    "U01": ROOT / "working_assets/e38_video_20260804/pro_v1/U01.mp4",
    "U04": ROOT / "working_assets/e38_video_20260804/pro_v1/U04.mp4",
    "U07": ROOT / "working_assets/e38_video_20260804/pro_v1/U07.mp4",
    "U08-R2": ROOT / "working_assets/e38_video_20260804/u08_r2_exact_tail_pro/E38-U08-R2.mp4",
}

SOURCE_QA = {
    "U01": ROOT / "qa/e38_video_20260804/u01_r2_textless_pro/E38_U01_R2_ACCEPTANCE_V1.json",
    "U04": ROOT / "qa/e38_video_20260804/u04_r2_textless_pro/E38_U04_R2_DOF_ACCEPTANCE_V1.json",
    "U07": ROOT / "qa/e38_video_20260804/u07_r2_multi_keyframe_pro/E38_U07_R2_LONG_TAKE_REVIEW_V1.json",
    "U08": ROOT / "qa/e38_video_20260804/u08_r3_all_actor_motion_pro/E38_U08_R3_ACTION_REVIEW_V1.json",
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
    value = subprocess.check_output(
        [str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        text=True,
    )
    return float(value.strip())


def caption_lines(dialogue: str) -> list[str]:
    return [line.strip() for line in re.findall(r"\{([^{}]+)\}", dialogue or "") if line.strip()]


def subtitle_clips(units: list[dict], windows: dict[str, dict]) -> list[dict]:
    clips: list[dict] = []
    sequence = 1
    for unit in units:
        unit_id = unit["id"]
        lines = caption_lines(unit.get("dialogue", ""))
        if not lines:
            continue
        window = windows[unit_id]
        start = window["start"] + min(0.65, window["duration"] * 0.08)
        usable = max(0.8, window["duration"] - min(1.0, window["duration"] * 0.14))
        weights = [max(2, len(line)) for line in lines]
        total = sum(weights)
        cursor = start
        for line, weight in zip(lines, weights):
            line_duration = usable * weight / total
            clips.append({
                "id": f"E38-DIA-{sequence:03d}",
                "dialogue_id": f"E38-DIA-{sequence:03d}",
                "text": line,
                "start": round(cursor, 6),
                "duration": round(line_duration, 6),
                "metadata": {"episode": "E38", "unit_id": unit_id, "source": "CANONICAL_V2_DIALOGUE"},
            })
            cursor += line_duration
            sequence += 1
    return clips


def bgm_clips(bgm: Path, runtime: float) -> list[dict]:
    # Motivated cues only. The uncovered windows preserve native room tone and impacts.
    cues = [
        ("OPENING", 0.0, 8.0, 0.06, 0.0),
        ("INVESTIGATION", 21.0, 11.0, 0.055, 20.0),
        ("EVIDENCE", 42.0, 10.0, 0.07, 42.0),
        ("AMBUSH", 56.0, 34.0, 0.14, 65.0),
        ("AFTERMATH", 103.0, 13.0, 0.06, 112.0),
        ("HOOK", 137.0, max(0.1, runtime - 137.0), 0.09, 140.0),
    ]
    result = []
    for cue_id, start, cue_duration, volume, source_in in cues:
        if start >= runtime:
            continue
        result.append({
            "id": f"E38-BGM-{cue_id}", "source": str(bgm), "start": start,
            "in": source_in, "duration": round(min(cue_duration, runtime - start), 6),
            "volume": volume,
            "transitionIn": {"type": "fade", "duration": 0.45},
            "transitionOut": {"type": "fade", "duration": 0.55},
            "metadata": {"episode": "E38", "role": cue_id, "generated_instrumental": True, "source_sha256": sha256(bgm)},
        })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bgm", required=True)
    parser.add_argument("--bgm-task-id", required=True)
    args = parser.parse_args()
    bgm = Path(args.bgm).expanduser().resolve()

    required = [PLAN, SCRIPT, MANIFEST, bgm, *ACCEPTED_VIDEO.values(), *ACCEPTED_AUDIO.values(), *SUPERSEDED.values(), *SOURCE_QA.values()]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise SystemExit("missing required inputs: " + ", ".join(missing))
    plan = load(PLAN)
    units = plan["units"]
    if [row["id"] for row in units] != list(ACCEPTED_VIDEO):
        raise SystemExit("accepted source order does not match canonical unit order")

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    windows: dict[str, dict] = {}
    video_clips = []
    native_audio_clips = []
    registry_rows = []
    cursor = 0.0
    targets = []
    for unit in units:
        unit_id = unit["id"]
        video = ACCEPTED_VIDEO[unit_id]
        audio = ACCEPTED_AUDIO[unit_id]
        video_sha = sha256(video)
        audio_sha = sha256(audio)
        use_duration = min(duration(video), float(unit.get("edit_duration") or unit["duration"]))
        use_duration = max(0.1, round(use_duration - 0.001, 6))
        metadata = {
            "episode": "E38", "unit_id": unit_id, "scene_id": unit["scene"],
            "source_sha256": video_sha, "admission": "PASS_ACCEPTED_ONLY_SOURCE",
            "narrative_function": f"advance canonical beat {unit_id}",
            "new_information": unit["action"],
            "semantic_group": f"E38_{unit_id}_CANONICAL_BEAT",
            "fallback_only": False,
            "replacement_condition": "SATISFIED_BY_SHA_LOCKED_ACCEPTED_SOURCE",
            "duration_policy": "NATIVE_REAL_TIME_1X_NO_PADDING_NO_SLOW_MOTION",
            "camera_policy": "SOURCE_MOTION_UNCHANGED_NO_POST_SWAY",
        }
        if unit_id in SOURCE_QA:
            metadata["source_qa"] = str(SOURCE_QA[unit_id])
            metadata["source_qa_sha256"] = sha256(SOURCE_QA[unit_id])
        clip_id = f"E38-{unit_id}-VIDEO"
        video_clips.append({
            "id": clip_id, "source": str(video), "start": round(cursor, 6),
            "in": 0.0, "duration": use_duration, "cutReason": "canonical unit boundary",
            "metadata": metadata,
        })
        native_audio_clips.append({
            "id": f"E38-{unit_id}-NATIVE-AUDIO", "source": str(audio),
            "start": round(cursor, 6), "in": 0.0,
            "duration": max(0.1, min(use_duration, duration(audio)) - 0.001),
            "volume": 0.82,
            "transitionIn": {"type": "fade", "duration": 0.01},
            "transitionOut": {"type": "fade", "duration": 0.01},
            "metadata": {
                "episode": "E38", "unit_id": unit_id, "source_sha256": audio_sha,
                "audio_source": "ALREADY_PAID_NATIVE_UNIT_AUDIO",
                "dialogue_mode": "CLOSED_MOUTH_VOICE_OVER" if unit_id in {"U01", "U04"} else "SOURCE_SYNCHRONOUS_AUDIO",
                "lip_sync_claimed": False if unit_id in {"U01", "U04"} else None,
            },
        })
        windows[unit_id] = {"start": cursor, "duration": use_duration}
        targets.append({"clipId": clip_id, "replacementSourceSha256": video_sha})
        registry_rows.append({
            "unit_id": unit_id, "video": str(video), "video_sha256": video_sha,
            "audio": str(audio), "audio_sha256": audio_sha,
            "duration_seconds": use_duration,
            "source_qa": str(SOURCE_QA[unit_id]) if unit_id in SOURCE_QA else "ORIGINAL_BATCH_SUPERVISOR_ADMISSION",
        })
        cursor += use_duration

    captions = subtitle_clips(units, windows)
    logo = ROOT / "libraries/brand/nalu_motion_cat_logo_v1.png"
    chime = ROOT / "libraries/brand/nalu_motion_outro_chime_v1.wav"
    for asset in (logo, chime):
        if not asset.is_file():
            raise SystemExit(f"missing brand asset: {asset}")

    forbidden_shas = sorted({sha256(path) for path in SUPERSEDED.values()})
    forbidden_tokens = [str(path).lower() for path in SUPERSEDED.values()]
    runtime = round(cursor, 6)
    bgm_rows = bgm_clips(bgm, runtime)
    bgm_seconds = sum(row["duration"] for row in bgm_rows)
    project = {
        "version": "1.0",
        "releaseProject": False,
        "metadata": {
            "episode": "E38", "status": "ACCEPTED_BGM_SUBTITLES_NULU_OUTRO_NOT_FINAL",
            "agentcut_required_version": "0.9.20", "recorded_at": now,
            "canonical_script": str(SCRIPT), "canonical_script_sha256": sha256(SCRIPT),
            "canonical_manifest": str(MANIFEST), "canonical_manifest_sha256": sha256(MANIFEST),
            "accepted_source_registry": str(REGISTRY), "runtime_seconds": runtime,
            "subtitle_contract": {"coverage": f"{len(captions)}/{len(captions)}", "burned_in": True},
            "bgm_contract": {
                "source_type": "GENERATED_EPISODE_INSTRUMENTAL", "generation_task_id": args.bgm_task_id,
                "source": str(bgm), "source_sha256": sha256(bgm), "license_status": "SELF_GENERATED_ACCOUNT_OWNED",
                "cue_policy": "SELECTIVE_NARRATIVE_CUES", "coverage_ratio": round(bgm_seconds / runtime, 6),
                "no_wall_to_wall_score": True,
            },
            "replacementBindingPolicy": {
                "enabled": True, "expectedTargetCount": len(targets), "targets": targets,
                "forbiddenSourceSha256": forbidden_shas, "forbiddenPathTokens": forbidden_tokens,
            },
        },
        "runtimePolicy": {"paddingForbidden": True, "onCoverageGap": "fail"},
        "output": {
            "path": str(OUTPUT), "width": 1080, "height": 1920, "fps": 24,
            "videoCodec": "libx264", "audioCodec": "aac", "audioBitrate": "192k",
            "pixelFormat": "yuv420p", "threads": 4,
        },
        "masterAudioPolicy": {
            "required": True, "limiter": True, "truePeakCeilingDbtp": -1.0,
            "codecHeadroomDb": 1.5, "loudnessTargetLufs": -17,
            "loudnessRangeLu": 11, "maxClippedSamples": 0,
        },
        "timeline": {
            "videoTracks": [{"id": "E38_ACCEPTED_VIDEO", "clips": video_clips}],
            "audioTracks": [
                {"id": "E38_NATIVE_DIALOGUE_AMBIENCE_SFX", "clips": native_audio_clips},
                {"id": "E38_SELECTIVE_GENERATED_BGM", "clips": bgm_rows},
            ],
            "subtitleTracks": [{
                "id": "E38_ZH_CN_BURNIN", "enabled": True,
                "style": {
                    "font": "/System/Library/Fonts/STHeiti Medium.ttc", "size": 52,
                    "color": "#FFFFFF", "outline": 4, "outlineColor": "#000000",
                    "alignment": "bottom-center",
                    "margins": {"left": 90, "right": 90, "top": 120, "bottom": 240},
                    "wrap": 15,
                },
                "clips": captions,
            }],
        },
        "expectedDialogueIds": [row["dialogue_id"] for row in captions],
        "requireBrandedOutro": True,
        "outro": {
            "enabled": True, "brand": "nalu_motion", "template": "nalu-motion-v1",
            "templateVersion": "1.0", "assetPath": str(logo), "duration": 3,
            "fit": "contain", "audioPolicy": "asset", "audioPath": str(chime),
            "transitionIn": 0.25, "transitionOut": 0.25,
            "titleText": "青山", "nextText": "敬请期待", "brandText": "NALU 影业",
            "dialogueDuckDb": -12, "bgmDuckDb": -9,
            "safeArea": {"left": 90, "right": 90, "top": 160, "bottom": 160},
            "logo": {"x": 352, "y": 850, "width": 376, "height": 212},
            "includeInTotalDuration": True,
        },
        "qingshanAudit": {
            "pipelineStage": "E38_AGENTCUT_V1_RENDER_AND_FULLCUT_QA", "sourceCount": 14,
            "sourceBinding": "SHA_LOCKED_ACCEPTED_ONLY", "supersededSourceShaCount": len(forbidden_shas),
            "generationCredits": {"pay": 9704, "refund": 0, "net": 9704, "cap": 10000, "headroom": 296},
        },
    }

    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    PROJECT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    registry = {
        "schema": "qingshan.e38.accepted_source_registry.v1", "episode": "E38",
        "recorded_at": now, "status": "PASS_ACCEPTED_14_OF_14_SHA_LOCKED",
        "canonical_script_sha256": sha256(SCRIPT), "canonical_manifest_sha256": sha256(MANIFEST),
        "source_count": len(registry_rows), "runtime_seconds": runtime, "sources": registry_rows,
    }
    REGISTRY.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    project["metadata"]["accepted_source_registry_sha256"] = sha256(REGISTRY)
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema": "qingshan.e38.agentcut_v1_build.v1", "episode": "E38", "recorded_at": now,
        "status": "READY_VALIDATE_AND_RENDER", "project": str(PROJECT), "project_sha256": sha256(PROJECT),
        "registry": str(REGISTRY), "registry_sha256": sha256(REGISTRY), "output": str(OUTPUT),
        "content_runtime_seconds": runtime, "total_runtime_seconds": round(runtime + 3.0, 6),
        "source_count": 14, "subtitle_count": len(captions), "bgm_task_id": args.bgm_task_id,
        "bgm_sha256": sha256(bgm), "bgm_coverage_ratio": round(bgm_seconds / runtime, 6),
        "replacement_binding_targets": len(targets), "forbidden_superseded_sha_count": len(forbidden_shas),
    }
    BUILD_RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    BUILD_RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
