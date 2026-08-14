#!/usr/bin/env python3
"""Bind accepted V19 action long takes and the real-time U03-S4 repair."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FFPROBE = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffprobe"
PARENT = ROOT / "configs/e37_agentcut_v18_full_episode_fixed_camera_long_take_bgm_subtitles_nalu_outro_20260804.json"
ACTION = ROOT / "working_assets/e37_action_replacement_v19_20260804/accepted_action_sequence_v19/E37_V19_ACCEPTED_LONG_TAKE_ACTION_SEQUENCE.mp4"
ACTION_CADENCE = ROOT / "qa/e37_action_replacement_v19_20260804/sequence/E37_V19_ACCEPTED_LONG_TAKE_ACTION_SEQUENCE_CADENCE.json"
ACTION_QA = [
    ROOT / "qa/e37_action_replacement_v19_20260804/E37_V19_A1_15S_PRO_OMNI_DIRECT_ADJUDICATION_PASS.json",
    ROOT / "qa/e37_action_replacement_v19_20260804/E37_V19_A2_15S_PRO_OMNI_DIRECT_ADJUDICATION_PASS.json",
    ROOT / "qa/e37_action_replacement_v19_20260804/E37_V19_B_15S_PRO_OMNI_DIRECT_ADJUDICATION_PASS.json",
]
U03 = ROOT / "working_assets/e37_v19_u03_s4_real_time_repair_20260804/video/E37-U03-S4-R2-LOCKED-REALTIME.mp4"
U03_QA = ROOT / "qa/e37_v19_u03_s4_real_time_repair_20260804/E37_U03_S4_R2_DIRECT_ADJUDICATION_PASS.json"
U03_CADENCE = ROOT / "qa/e37_v19_u03_s4_real_time_repair_20260804/E37_U03_S4_R2_FRAME_CADENCE.json"
CONFIG = ROOT / "configs/e37_agentcut_v19_action_realtime_repair_bgm_subtitles_nalu_outro_20260804.json"
OUTPUT = ROOT / "exports/e37/agentcut_v19_action_realtime_repair_20260804/E37_AGENTCUT_V19_ACTION_REALTIME_REPAIR_NOT_FINAL.mp4"
ACTION_CLIP_ID = "E37-U04-U06-S1-LONG-TAKE-ACTION-V17"
ACTION_AUDIO_ID = "E37-U04-U06-S1-LONG-TAKE-ACTION-V17-AUDIO"
U03_CLIP_ID = "E37-U03-S4-CANONICAL-REPLACEMENT-V4"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def duration(path: Path) -> float:
    value = subprocess.check_output(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=duration",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        text=True,
    )
    return float(value.strip())


def require_pass(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    status = str(data.get("status") or data.get("decision") or "")
    if not status.startswith("PASS"):
        raise SystemExit(f"Source is not admitted: {path}: {status}")
    return data


def purge_superseded_path_provenance(value: object) -> None:
    """Remove stale path-bearing provenance from a release project in place."""
    if isinstance(value, dict):
        value.pop("v18_original_source", None)
        value.pop("v17_long_take_action", None)
        for child in value.values():
            purge_superseded_path_provenance(child)
    elif isinstance(value, list):
        for child in value:
            purge_superseded_path_provenance(child)


def assert_live_sources(project: dict, forbidden_shas: set[str]) -> None:
    checked = 0
    for group in ("videoTracks", "audioTracks"):
        for track in project["timeline"].get(group, []):
            for clip in track.get("clips", []):
                source = Path(str(clip.get("source") or ""))
                if not source.is_file():
                    raise SystemExit(f"Missing live source in {group}/{track.get('id')}: {source}")
                source_sha = sha256(source)
                if source_sha in forbidden_shas:
                    raise SystemExit(
                        f"Superseded source is still live in {group}/{track.get('id')}: "
                        f"{clip.get('id')} -> {source} ({source_sha})"
                    )
                checked += 1
    project.setdefault("metadata", {})["liveSourceBindingGate"] = {
        "status": "PASS",
        "checked_clip_count": checked,
        "policy": "EVERY_LIVE_VIDEO_AND_AUDIO_SOURCE_EXISTS_AND_NO_SHA_MATCHES_A_SUPERSEDED_SOURCE",
    }


def main() -> None:
    required = [PARENT, ACTION, ACTION_CADENCE, U03, U03_QA, U03_CADENCE, *ACTION_QA]
    for path in required:
        if not path.is_file():
            raise SystemExit(f"Missing required input: {path}")
    action_cadence = require_pass(ACTION_CADENCE)
    action_qa = [require_pass(path) for path in ACTION_QA]
    u03_qa = require_pass(U03_QA)

    project = copy.deepcopy(json.loads(PARENT.read_text(encoding="utf-8")))
    purge_superseded_path_provenance(project)
    action_duration = duration(ACTION)
    parent_action_duration = None
    replaced_action = 0
    replaced_u03 = 0
    forbidden_shas: set[str] = set()

    for track in project["timeline"]["videoTracks"]:
        for clip in track.get("clips", []):
            if clip.get("id") == ACTION_CLIP_ID:
                old_source = Path(clip["source"])
                if old_source.is_file():
                    forbidden_shas.add(sha256(old_source))
                parent_action_duration = float(clip["duration"])
                clip.update(
                    {
                        "id": "E37-U04-U06-S1-LONG-TAKE-ACTION-V19",
                        "source": str(ACTION),
                        "in": 0.0,
                        "duration": action_duration,
                        "cutReason": "three admitted causal long takes joined only at SHA-bound action-state handoffs",
                    }
                )
                clip.setdefault("metadata", {}).update(
                    {
                        "admission": "PASS_V19_A1_A2_B",
                        "source_sha256": sha256(ACTION),
                        "camera_policy": "LOCKED_OR_SINGLE_MOTIVATED_SAME_APERTURE_CROSSING_NO_SWAY_NO_ROAM",
                        "real_time_1x": True,
                        "cadence_report_path": str(ACTION_CADENCE),
                        "cadence_report_sha256": sha256(ACTION_CADENCE),
                        "qa_receipts": [str(path) for path in ACTION_QA],
                        "qa_scores": [row.get("score") for row in action_qa],
                        "narrative_action_present": True,
                        "motivated_hold_reason": "SHA-bound V19 long-take action passed direct scores 84/76/82 and zero-freeze cadence",
                    }
                )
                replaced_action += 1
            elif clip.get("id") == U03_CLIP_ID:
                old_source = Path(clip["source"])
                if old_source.is_file():
                    forbidden_shas.add(sha256(old_source))
                clip["source"] = str(U03)
                clip["in"] = 0.0
                clip["duration"] = 7.0
                clip.setdefault("metadata", {}).update(
                    {
                        "admission": "PASS_V19_REALTIME_NO_FREEZE",
                        "source_sha256": sha256(U03),
                        "camera_policy": "ONE_LOCKED_TRIPOD_COMPOSITION_NO_CUT_NO_CAMERA_MOTION",
                        "real_time_1x": True,
                        "cadence_report_path": str(U03_CADENCE),
                        "cadence_report_sha256": sha256(U03_CADENCE),
                        "direct_qa_receipt": str(U03_QA),
                        "direct_qa_receipt_sha256": sha256(U03_QA),
                        "camera_generation": "V19_ONE_LOCKED_COMPOSITION_REALTIME",
                        "replacement_condition": "SATISFIED_BY_V19_REALTIME_NO_FREEZE_SHA",
                        "v19_replaces_v15_freeze": True,
                    }
                )
                replaced_u03 += 1

    for track in project["timeline"]["audioTracks"]:
        for clip in track.get("clips", []):
            if clip.get("id") == ACTION_AUDIO_ID:
                clip.update(
                    {
                        "id": "E37-U04-U06-S1-LONG-TAKE-ACTION-V19-AUDIO",
                        "source": str(ACTION),
                        "in": 0.0,
                        "duration": max(0.1, action_duration - 0.001),
                    }
                )
                replaced_action += 1

    if replaced_action != 2 or replaced_u03 != 1 or parent_action_duration is None:
        raise SystemExit(
            f"Binding coverage mismatch: action={replaced_action}/2 u03={replaced_u03}/1"
        )

    delta = action_duration - parent_action_duration
    action_start = 62.28
    parent_action_end = action_start + parent_action_duration
    for group in ("videoTracks", "audioTracks", "subtitleTracks"):
        for track in project["timeline"].get(group, []):
            for clip in track.get("clips", []):
                if float(clip.get("start", 0.0)) >= parent_action_end - 0.001:
                    clip["start"] = round(float(clip["start"]) + delta, 6)
    for clip in project["timeline"]["audioTracks"][1]["clips"]:
        if clip.get("id") == "E37-BGM-ACTION":
            clip["duration"] = round(action_duration + (action_start - float(clip["start"])), 6)

    for group in ("videoTracks", "audioTracks", "subtitleTracks"):
        for track in project["timeline"].get(group, []):
            ordered = sorted(track.get("clips", []), key=lambda item: float(item.get("start", 0.0)))
            for left, right in zip(ordered, ordered[1:]):
                left_end = float(left.get("start", 0.0)) + float(left.get("duration", 0.0))
                if float(right.get("start", 0.0)) < left_end - 0.002:
                    raise SystemExit(
                        f"Unintended overlap in {group}/{track.get('id')}: "
                        f"{left.get('id')} ends {left_end:.6f}, "
                        f"{right.get('id')} starts {float(right.get('start', 0.0)):.6f}"
                    )

    metadata = project.setdefault("metadata", {})
    metadata.update(
        {
            "version": "V19_ACTION_REALTIME_REPAIR",
            "parent_project": str(PARENT),
            "parent_project_sha256": sha256(PARENT),
            "runtime_seconds": round(float(metadata["runtime_seconds"]) + delta, 6),
            "v19_action": {
                "source": str(ACTION),
                "source_sha256": sha256(ACTION),
                "duration_seconds": action_duration,
                "source_order": [
                    "E37-V19-A1-15S-PRO-OMNI",
                    "E37-V19-A2-15S-PRO-OMNI",
                    "E37-V19-B-15S-PRO-OMNI",
                ],
                "scores": [row.get("score") for row in action_qa],
                "cadence_status": action_cadence.get("status"),
            },
            "v19_u03_s4": {
                "source": str(U03),
                "source_sha256": sha256(U03),
                "score": u03_qa.get("score"),
                "camera_policy": "ONE_LOCKED_TRIPOD_COMPOSITION_NO_CUT_NO_CAMERA_MOTION",
                "tempo": "REAL_TIME_1X",
            },
            "release_status": "NOT_FINAL_PENDING_FRESH_RENDER_AND_FULL_EPISODE_QA",
        }
    )

    policy = metadata.setdefault("replacementBindingPolicy", {})
    targets = policy.setdefault("targets", [])
    for target in targets:
        if target.get("clipId") == U03_CLIP_ID:
            target["replacementSourceSha256"] = sha256(U03)
            target["segmentId"] = "U03-S4"
    targets.append(
        {
            "clipId": "E37-U04-U06-S1-LONG-TAKE-ACTION-V19",
            "replacementSourceSha256": sha256(ACTION),
            "segmentId": "U04-U06-S1-ACTION",
        }
    )
    policy["expectedTargetCount"] = len(targets)
    policy["forbiddenSourceSha256"] = sorted(
        set(policy.get("forbiddenSourceSha256", [])) | forbidden_shas
    )
    policy["failureAction"] = "BLOCK_COMPILE_RENDER_FINAL_VISUAL_RELEASE_AND_UPLOAD"

    project["finalVisualPolicy"] = {
        "enabled": True,
        "required": True,
        "sampleFps": 2.0,
        "cropBottomRatio": 0.22,
        "maxNearFreezeSeconds": 4.0,
        "allowedIntervals": [
            {
                "start": 28.12,
                "end": 62.24,
                "reason": "SHA-bound V15/V16/V19 fixed-camera dialogue sources passed per-source cadence and direct visual review",
            },
            {
                "start": action_start,
                "end": round(action_start + action_duration, 6),
                "reason": "V19 A1/A2/B long takes passed direct scores 84/76/82 at the authorized 60-point threshold and zero-freeze cadence",
            },
            {
                "start": round(99.403008 + delta, 6),
                "end": round(145.643008 + delta, 6),
                "reason": "SHA-bound V15/V16 fixed-camera dialogue sources passed per-source cadence and direct visual review",
            },
        ],
    }

    assert_live_sources(project, forbidden_shas)

    project["output"]["path"] = str(OUTPUT)
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS",
                "project": str(CONFIG),
                "project_sha256": sha256(CONFIG),
                "output": str(OUTPUT),
                "action_source_sha256": sha256(ACTION),
                "u03_source_sha256": sha256(U03),
                "timeline_delta_seconds": delta,
                "binding_target_count": len(targets),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
