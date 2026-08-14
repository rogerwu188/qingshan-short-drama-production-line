#!/usr/bin/env python3
"""Build the reversible E28 V4 midsection recut from the published V3 project."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/e28_agentcut_v3_writer_agent_v050_release_candidate_20260721.json"
OUTPUT = ROOT / "configs/e28_agentcut_v4_midsection_recut_20260721.json"
RENDER = ROOT / "exports/e28/agentcut_v4_midsection_recut_20260721/E28_AGENTCUT_V4_MIDSECTION_RECUT_NOT_FINAL.mp4"
RECEIPT = ROOT / "workflow/tasks/E28_AGENTCUT_V4_MIDSECTION_RECUT_BUILD_RECEIPT_20260721.json"

U03_VIDEO = "E28-B02-U03-VIDEO"
U04_VIDEO = "E28-B02-U04-VIDEO"
U03_AUDIO = "E28-B02-U03-AUDIO"
U04_AUDIO = "E28-B02-U04-AUDIO"
U03_START = 85.0
NEXT_START_V3 = 113.0
SHIFT = 14.0


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def shifted_start(clip: dict) -> float:
    start = float(clip["start"])
    return round(start - SHIFT, 6) if start >= NEXT_START_V3 else start


def build() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    project = copy.deepcopy(source)
    video_track = project["timeline"]["videoTracks"][0]
    audio_track = project["timeline"]["audioTracks"][0]

    source_video = {clip["id"]: clip for clip in video_track["clips"]}
    u03 = copy.deepcopy(source_video[U03_VIDEO])
    u04 = copy.deepcopy(source_video[U04_VIDEO])

    u03["id"] = "E28-B02-U03-VIDEO-V4-DYNAMIC-AND-EVIDENCE"
    u03["duration"] = 8.0
    u03["metadata"]["cut_reason"] = "V4_KEEP_ATTACK_AND_FIRST_EVIDENCE_BEAT"
    u03["metadata"]["v4_source_window"] = {"in": 0.0, "out": 8.0}
    u03["metadata"]["v4_reason"] = "Retain the attack, counteraction and first concise evidence beat; remove the repeated crouch tail."

    u04["id"] = "E28-B02-U04-VIDEO-V4-DYNAMIC-ESCAPE"
    u04["start"] = 93.0
    u04["in"] = 8.0
    u04["duration"] = 6.0
    u04["metadata"]["cut_reason"] = "V4_SKIP_REPEATED_CROUCH_TO_DYNAMIC_ESCAPE"
    u04["metadata"]["v4_source_window"] = {"in": 8.0, "out": 14.0}
    u04["metadata"]["v4_reason"] = "Skip the repeated crouch, boot and feather inserts; enter on the line snare and window escape."

    rebuilt_video = []
    for clip in video_track["clips"]:
        if clip["id"] == U03_VIDEO:
            rebuilt_video.extend([u03, u04])
        elif clip["id"] == U04_VIDEO:
            continue
        else:
            row = copy.deepcopy(clip)
            row["start"] = shifted_start(row)
            rebuilt_video.append(row)
    video_track["clips"] = rebuilt_video

    source_audio = {clip["id"]: clip for clip in audio_track["clips"]}
    u03_audio = source_audio[U03_AUDIO]
    u04_audio = source_audio[U04_AUDIO]
    dialogue_windows = [
        ("E28-B02-U03-AUDIO-V4-01", u03_audio, 0.0, 3.44, 85.0, "his_blade_and_eave_channel"),
        ("E28-B02-U03-AUDIO-V4-02", u03_audio, 5.04, 5.60, 88.60, "same_form_different_force_and_inward_blade"),
        ("E28-B02-U03-AUDIO-V4-03", u03_audio, 11.92, 2.08, 94.40, "old_framing_method"),
        ("E28-B02-U04-AUDIO-V4-04", u04_audio, 11.0, 2.0, 96.68, "escape_step_line"),
        ("E28-B02-U04-AUDIO-V4-05", u04_audio, 13.0, 0.32, 98.68, "escape_ambience_tail_to_next_scene"),
    ]
    v4_audio = []
    for clip_id, template, source_in, clip_duration, start, reason in dialogue_windows:
        row = copy.deepcopy(template)
        row.update({"id": clip_id, "in": source_in, "duration": clip_duration, "start": start})
        row["metadata"]["cut_reason"] = "V4_SPEECH_SAFE_DIALOGUE_COMPACTION"
        row["metadata"]["v4_reason"] = reason
        row["metadata"]["v4_source_window"] = {"in": source_in, "out": round(source_in + clip_duration, 6)}
        v4_audio.append(row)

    rebuilt_audio = []
    for clip in audio_track["clips"]:
        if clip["id"] == U03_AUDIO:
            rebuilt_audio.extend(v4_audio)
        elif clip["id"] == U04_AUDIO:
            continue
        else:
            row = copy.deepcopy(clip)
            row["start"] = shifted_start(row)
            rebuilt_audio.append(row)
    audio_track["clips"] = rebuilt_audio

    project["output"]["path"] = str(RENDER)
    project["metadata"].update(
        {
            "status": "AGENTCUT_V4_MIDSECTION_RECUT_NOT_FINAL",
            "source_v3_project": str(SOURCE),
            "source_v3_project_sha256": sha256(SOURCE),
            "runtime_seconds": 148.0,
            "contract_runtime_seconds": 162.0,
            "runtime_delta_seconds": -14.0,
            "content_runtime_seconds": 148.0,
            "release_runtime_seconds": 151.0,
            "v4_recut_scope": "85.0-113.0s V3 midsection compressed to a 14.0s action/evidence/escape sequence",
            "v4_dialogue_policy": "Preserve five narrative lines using speech-safe native-audio source windows; remove duplicated pauses and visual padding.",
            "platformUploadAllowed": False,
        }
    )
    project["qingshanAudit"].update(
        {
            "pipelineStage": "WRITER_AGENT_V050_V4_MIDSECTION_RECUT",
            "final": False,
            "platformUploadAllowed": False,
            "expectedRuntimeSeconds": 148.0,
            "contractRuntimeSeconds": 162.0,
            "directedRecutSecondsRemoved": 14.0,
            "nearDuplicateGateRequired": True,
            "rollback": f"Use the published V3 project unchanged: {SOURCE}",
        }
    )
    # Preserve V3's already adjudicated source-level threshold. V4's new
    # full-cut near-freeze/near-duplicate gate is evaluated separately.
    project["sourceAdmissionPolicy"]["maxActionNearDuplicateRatio"] = 0.20
    write(OUTPUT, project)

    receipt = {
        "schema": "qingshan.e28.agentcut-v4-midsection-recut-build.v1",
        "episode": "E28",
        "recorded_at": now(),
        "status": "BUILT_PENDING_VALIDATE_RENDER_QA",
        "source_project": {"path": str(SOURCE), "sha256": sha256(SOURCE)},
        "project": {"path": str(OUTPUT), "sha256": sha256(OUTPUT)},
        "output": str(RENDER),
        "change_scope": {
            "v3_window_seconds": [85.0, 113.0],
            "v4_window_seconds": [85.0, 99.0],
            "removed_seconds": 14.0,
            "removed_visuals": ["repeated crouch", "boot insert", "feather insert", "near-freeze holds"],
            "preserved": ["attack", "counteraction", "force-direction evidence", "old-method conclusion", "window escape", "five narrative dialogue lines"],
        },
        "rollback": str(SOURCE),
        "platform_release": "NOT_AUTHORIZED_FOR_V4",
        "remote_credit": 0,
    }
    write(RECEIPT, receipt)
    print(json.dumps({"ok": True, "project": str(OUTPUT), "receipt": str(RECEIPT)}, ensure_ascii=False))


if __name__ == "__main__":
    build()
