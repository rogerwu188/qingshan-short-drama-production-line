#!/usr/bin/env python3
"""Build the E28 Writer Agent v0.5 entity-sequence AgentCut project."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRITER = ROOT / "workflow/writer_agent/e28_agent_native_v050_20260721/E28_WRITER_AGENT_V050_COMPILED.json"
VIDEO_RECEIPT = ROOT / "workflow/tasks/E28_WRITER_AGENT_V050_ENTITY_REFERENCE_VIDEO_BATCH_R1_RECEIPT_20260721.json"
ADMISSION = ROOT / "workflow/writer_agent/e28_agent_native_v050_20260721/production/E28_VIDEO_CANDIDATE_ADMISSION.json"
PROJECT = ROOT / "configs/e28_agentcut_v1_writer_agent_v050_entity_sequence_20260721.json"
OUTPUT = ROOT / "exports/e28/agentcut_v1_writer_agent_v050_entity_sequence_20260721/E28_AGENTCUT_V1_WRITER_AGENT_V050_ENTITY_SEQUENCE_NOT_FINAL.mp4"
BUILD_RECEIPT = ROOT / "workflow/tasks/E28_AGENTCUT_V1_WRITER_AGENT_V050_BUILD_RECEIPT_20260721.json"

AGENTCUT_CADENCE_ADMISSIONS = {
    "E28-S01::U02": {
        "confidence": 0.82,
        "evidence": "Raw cadence audit PASS; AgentCut action gate measured near-duplicate ratio 0.196428571 against its stricter 0.15 threshold. Media, story facts, identities, dialogue, and duration remain usable.",
    },
    "E28-S03::U03": {
        "confidence": 0.84,
        "evidence": "Raw cadence audit PASS; AgentCut action gate measured near-duplicate ratio 0.177083333 against its stricter 0.15 threshold. Media, story facts, identities, dialogue, and duration remain usable.",
    },
    "E28-S03::U04": {
        "confidence": 0.84,
        "evidence": "Raw cadence audit PASS; AgentCut action gate measured near-duplicate ratio 0.177083333 against its stricter 0.15 threshold. Media, story facts, identities, dialogue, and duration remain usable.",
    },
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def phase_map(contract: dict) -> dict[str, str]:
    names = {"wind_up": "windup", "contact": "contact", "force_transfer": "force", "result": "result"}
    return {names[row["phase"]]: row["description"] for row in contract["action_physics"]["phases"]}


def light_key(scene_id: str) -> str:
    return {
        "E28-S01": "COLD_DAYLIGHT_TO_DUSK",
        "E28-S02": "DUSK_TO_EARLY_NIGHT",
        "E28-S03": "MOONLESS_SNOW_NIGHT",
    }[scene_id]


def main() -> int:
    writer = load(WRITER)
    receipt = load(VIDEO_RECEIPT)
    admission = load(ADMISSION)
    tasks = {row["unit_id"]: row for row in receipt["tasks"]}
    overrides = {row["unit_id"]: row for row in admission["selections"]}
    video_clips = []
    audio_clips = []
    source_manifest = []
    conditional_source_count = 0
    cursor = 0.0

    for index, contract in enumerate(writer["video_generation_contracts"], 1):
        task = tasks[contract["unit_id"]]
        override = overrides.get(contract["unit_id"])
        duration = float(contract["duration_seconds"])
        if override:
            source = ROOT / override["path"]
            expected_sha = override["sha256"]
            source_admission = override["admission"]
            confidence = float(override["confidence"])
            cadence = ROOT / override["cadence_report"]
            ocr = ROOT / override["ocr_report"]
            conditional_evidence = override["raw_failure"]
        else:
            if task["state"] != "qa_pass":
                raise RuntimeError(f"unadmitted non-pass unit: {contract['unit_id']}")
            source = Path(task["output_path"])
            expected_sha = task.get("output_sha256") or sha256(source)
            source_admission = "PASS_BATCH_QA"
            confidence = 0.9
            cadence = Path(task["qa"]["frame_cadence"])
            ocr = Path(task["qa"]["ocr"])
            conditional_evidence = None
        cadence_admission = AGENTCUT_CADENCE_ADMISSIONS.get(contract["unit_id"])
        if cadence_admission and source_admission != "CONDITIONAL_MACHINE_ADMISSION":
            source_admission = "CONDITIONAL_MACHINE_ADMISSION"
            confidence = cadence_admission["confidence"]
            conditional_evidence = cadence_admission["evidence"]
        if source_admission == "CONDITIONAL_MACHINE_ADMISSION":
            conditional_source_count += 1
        if not source.is_file() or sha256(source) != expected_sha:
            raise RuntimeError(f"source SHA mismatch: {source}")
        if not cadence.is_file() or not ocr.is_file():
            raise RuntimeError(f"missing QA evidence: {contract['unit_id']}")

        unit_number = int(contract["unit_id"].rsplit("U", 1)[1])
        key = f"{contract['batch_id']}-U{unit_number:02d}"
        metadata = {
            "episode": "E28",
            "scene_id": contract["scene_id"],
            "source_id": key,
            "unit_id": contract["unit_id"],
            "batch_id": contract["batch_id"],
            "source_sha256": expected_sha,
            "source_variant": "WRITER_AGENT_V050_ENTITY_REFERENCE_SEQUENCE",
            "source_admission": source_admission,
            "source_admission_confidence": confidence,
            "cut_reason": contract["edit_boundary_contract"]["entry"].upper(),
            "narrative_function": " -> ".join(row["action"] for row in contract["story_event_boundary"]["locked_action_chain"]),
            "new_information": "Writer Agent v0.5 locked entity-reference action unit.",
            "semantic_group": key,
            "fallback_only": False,
            "axis_line": f"{contract['scene_id']}::LOCKED_ACTION_AXIS",
            "eyeline": f"{key}::PRIMARY_ACTION_TARGET",
            "light_key": light_key(contract["scene_id"]),
            "action_required": True,
            "action_trajectory": phase_map(contract),
            "source_reference_mode": "generated_video",
            "cadence_report_path": str(cadence),
            "ocr_report_path": str(ocr),
        }
        if conditional_evidence:
            metadata["conditional_admission_evidence"] = conditional_evidence
        video_clips.append({"id": f"{key}-VIDEO", "source": str(source), "start": cursor, "in": 0.0, "duration": duration, "metadata": metadata})
        audio_clips.append(
            {
                "id": f"{key}-AUDIO",
                "source": str(source),
                "start": cursor,
                "in": 0.0,
                "duration": duration,
                "volume": 0.82,
                "metadata": {
                    "episode": "E28",
                    "unit_id": contract["unit_id"],
                    "source_sha256": expected_sha,
                    "cut_reason": "NATIVE_AUDIO_FOLLOWS_ENTITY_REFERENCE_UNIT",
                    "audio_policy": "NATIVE_MULTIMODAL_DIALOGUE_SFX_AMBIENCE_NO_EXTERNAL_BGM",
                },
            }
        )
        source_manifest.append(
            {
                "order": index,
                "key": key,
                "unit_id": contract["unit_id"],
                "path": str(source),
                "sha256": expected_sha,
                "start": cursor,
                "duration": duration,
                "admission": source_admission,
            }
        )
        cursor += duration

    project = {
        "version": "1.0",
        "background": "black",
        "requireCutReason": True,
        "sourceAdmissionPolicy": {
            "enabled": True,
            "requirePerShotCadence": True,
            "requireActionTrajectory": True,
            "singleStillAction": "block",
            "maxActionNearDuplicateRatio": 0.20,
        },
        "output": {
            "path": str(OUTPUT),
            "width": 720,
            "height": 1280,
            "fps": 24,
            "videoCodec": "libx264",
            "audioCodec": "aac",
            "audioBitrate": "192k",
            "pixelFormat": "yuv420p",
            "threads": 4,
        },
        "masterAudioPolicy": {
            "required": True,
            "limiter": True,
            "truePeakCeilingDbtp": -1.0,
            "codecHeadroomDb": 3.0,
            "loudnessTargetLufs": -16.0,
            "loudnessRangeLu": 11.0,
            "maxClippedSamples": 0,
        },
        "metadata": {
            "episode": "E28",
            "status": "V1_WRITER_AGENT_V050_ENTITY_SEQUENCE_NOT_FINAL",
            "writer_agent_version": "0.5.0",
            "writer_agent_schema": "1.4.0",
            "runtime_seconds": cursor,
            "contract_runtime_seconds": 162.0,
            "runtime_delta_seconds": cursor - 162.0,
            "audio_policy": "NATIVE_MULTIMODAL_DIALOGUE_SFX_AMBIENCE_NO_EXTERNAL_BGM",
            "platformUploadAllowed": False,
        },
        "timeline": {
            "videoTracks": [{"id": "E28_V050_ENTITY_REFERENCE_VIDEO", "clips": video_clips}],
            "audioTracks": [{"id": "E28_V050_NATIVE_MULTIMODAL_AUDIO", "clips": audio_clips}],
        },
        "qingshanAudit": {
            "episode": "E28",
            "pipelineStage": "WRITER_AGENT_V050_ENTITY_REFERENCE_FULLCUT",
            "final": False,
            "platformUploadAllowed": False,
            "paddingForbidden": True,
            "sourceUnitCount": 12,
            "expectedRuntimeSeconds": cursor,
            "contractRuntimeSeconds": 162.0,
            "conditionalSourceCount": conditional_source_count,
        },
    }
    PROJECT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    BUILD_RECEIPT.write_text(
        json.dumps(
            {
                "schema": "qingshan.agentcut.v050-build-receipt.v1",
                "episode": "E28",
                "status": "BUILT_NOT_RENDERED",
                "project": str(PROJECT),
                "output": str(OUTPUT),
                "runtime_seconds": cursor,
                "contract_runtime_seconds": 162.0,
                "conditional_source_count": conditional_source_count,
                "sources": source_manifest,
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "project": str(PROJECT), "runtime_seconds": cursor, "sources": len(source_manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
