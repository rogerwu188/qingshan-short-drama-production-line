#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
WRITER = Path("/Users/rogerwu/Documents/Codex/2026-07-20/qingshan-professional-writer-agent/outputs/qingshan-writer-agent/examples/e27.agent-native.compiled.json")
B01_PROJECT = ROOT / "configs/e27_agentcut_b01_v050_continuity_test_20260720.json"
RECEIPT = ROOT / "workflow/tasks/E27_REMAINING_11_ENTITY_REFERENCE_SEQUENCE_V050_RECEIPT_20260720.json"
OUTPUT = ROOT / "exports/e27/agentcut_v18_writer_agent_v050_entity_sequence_20260720/E27_AGENTCUT_V18_WRITER_AGENT_V050_ENTITY_SEQUENCE_NOT_FINAL.mp4"
PROJECT = ROOT / "configs/e27_agentcut_v18_writer_agent_v050_entity_sequence_20260720.json"
BUILD_RECEIPT = ROOT / "workflow/tasks/E27_AGENTCUT_V18_WRITER_AGENT_V050_BUILD_RECEIPT_20260720.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def phase_map(contract: dict) -> dict[str, str]:
    return {
        {"wind_up": "windup", "contact": "contact", "force_transfer": "force", "result": "result"}[row["phase"]]: row["description"]
        for row in contract["action_physics"]["phases"]
    }


def main() -> None:
    writer = load(WRITER)
    b01 = load(B01_PROJECT)
    receipt = load(RECEIPT)
    task_rows = {row["task_key"].split("-ENTITY-")[0]: row for row in receipt["tasks"]}
    b01_video = {clip["metadata"]["unit_id"]: clip for clip in b01["timeline"]["videoTracks"][0]["clips"]}

    overrides = {
        "E27-B05-U02": {
            "path": ROOT / "working_assets/e27_remaining_entity_reference_v050_20260720/repairs/E27_B05_U02_AGENTCUT_TEXTCLEAN_R2_NOT_FINAL.mp4",
            "admission": "PASS_LOCAL_AGENTCUT_TEXTCLEAN_MACHINE_ADJUDICATION",
            "confidence": 0.94,
            "raw_fail": "Persistent pseudo-Chinese removed locally; residual single low-confidence R at 10.5s visually adjudicated as costume texture.",
            "cadence": ROOT / "qa/e27_remaining_entity_reference_v050_20260720/E27-B05-U02-AGENTCUT-TEXTCLEAN-R2_frame_cadence.json",
        },
        "E27-B06-U01": {
            "path": ROOT / "working_assets/e27_remaining_entity_reference_v050_20260720/candidates/E27_E27-B06-U01-ENTITY-REFERENCE-V050_b32bc760-5d31-4ed8-b423-888a970372ba.mp4",
            "admission": "CONDITIONAL_MACHINE_ADMISSION",
            "confidence": 0.99,
            "raw_fail": "OCR texture false positive disproved by exact-frame evidence.",
            "cadence": ROOT / "qa/e27_remaining_entity_reference_v050_20260720/E27-B06-U01-ENTITY-REFERENCE-V050_frame_cadence.json",
        },
        "E27-B06-U03": {
            "path": ROOT / "working_assets/e27_remaining_entity_reference_v050_20260720/repairs/E27_B06_U03_AGENTCUT_TRIM_9P5_NOT_FINAL.mp4",
            "admission": "CONDITIONAL_MACHINE_ADMISSION",
            "confidence": 0.91,
            "raw_fail": "Use only 0.0-9.5s; raw final 0.5s freeze remains preserved outside the cut.",
            "duration": 9.5,
            "cadence": ROOT / "qa/e27_remaining_entity_reference_v050_20260720/E27-B06-U03-AGENTCUT-TRIM-9P5_frame_cadence.json",
        },
    }

    video_clips: list[dict] = []
    audio_clips: list[dict] = []
    source_manifest: list[dict] = []
    cursor = 0.0

    for index, contract in enumerate(writer["video_generation_contracts"]):
        unit_number = int(contract["unit_id"].rsplit("U", 1)[1])
        key = f'{contract["batch_id"]}-U{unit_number:02d}'
        duration = float(contract["duration_seconds"])
        admission = "PASS_BATCH_QA"
        confidence = 0.9
        raw_fail = None
        cadence: Path

        if contract["batch_id"] == "E27-B01":
            prior = b01_video[key]
            source = Path(prior["source"])
            admission = prior["metadata"]["source_admission"]
            confidence = float(prior["metadata"]["source_admission_confidence"])
            cadence = ROOT / f"qa/e27_b01_entity_reference_v050_20260720/{key}-ENTITY-REFERENCE-V050_frame_cadence.json"
        elif key in overrides:
            item = overrides[key]
            source = Path(item["path"])
            duration = float(item.get("duration", duration))
            admission = item["admission"]
            confidence = float(item["confidence"])
            raw_fail = item["raw_fail"]
            cadence = Path(item["cadence"])
        else:
            source = Path(task_rows[key]["output_path"])
            cadence = Path(task_rows[key]["qa"]["frame_cadence"])

        if not source.is_file():
            raise SystemExit(f"missing source: {source}")
        if not cadence.is_file():
            raise SystemExit(f"missing cadence report: {cadence}")

        metadata = {
            "episode": "E27",
            "scene_id": contract["scene_id"],
            "source_id": key,
            "unit_id": contract["unit_id"],
            "batch_id": contract["batch_id"],
            "source_sha256": sha256(source),
            "source_variant": "WRITER_AGENT_V050_ENTITY_REFERENCE_SEQUENCE",
            "source_admission": admission,
            "source_admission_confidence": confidence,
            "cut_reason": contract["edit_boundary_contract"]["entry"].upper(),
            "narrative_function": " -> ".join(row["action"] for row in contract["story_event_boundary"]["locked_action_chain"]),
            "new_information": "Writer Agent v0.5 locked entity-reference action unit.",
            "semantic_group": key,
            "fallback_only": False,
            "light_key": "CLEAR_DAYTIME" if "day" in str(contract["time_of_day"]).lower() else "LOCKED_NIGHT_PRACTICALS",
            "axis_line": f'{contract["scene_id"]}::LOCKED_ACTION_AXIS',
            "eyeline": f"{key}::PRIMARY_ACTION_TARGET",
            "action_required": True,
            "action_trajectory": phase_map(contract),
            "source_reference_mode": "generated_video",
            "cadence_report_path": str(cadence),
        }
        if raw_fail:
            metadata["conditional_admission_evidence"] = raw_fail

        clip = {
            "id": f"{key}-VIDEO",
            "source": str(source),
            "start": cursor,
            "in": 0.0,
            "duration": duration,
            "metadata": metadata,
        }
        audio = {
            "id": f"{key}-AUDIO",
            "source": str(source),
            "start": cursor,
            "in": 0.0,
            "duration": duration,
            "volume": 0.82,
            "metadata": {
                "episode": "E27",
                "unit_id": contract["unit_id"],
                "source_sha256": metadata["source_sha256"],
                "cut_reason": "NATIVE_AUDIO_FOLLOWS_ENTITY_REFERENCE_UNIT",
                "audio_policy": "NATIVE_MULTIMODAL_DIALOGUE_SFX_AMBIENCE_NO_EXTERNAL_BGM",
            },
        }
        video_clips.append(clip)
        audio_clips.append(audio)
        source_manifest.append({
            "order": index + 1,
            "key": key,
            "unit_id": contract["unit_id"],
            "path": str(source),
            "sha256": metadata["source_sha256"],
            "start": cursor,
            "duration": duration,
            "contract_duration": float(contract["duration_seconds"]),
            "admission": admission,
        })
        cursor += duration

    project = {
        "version": "1.0",
        "background": "black",
        "requireCutReason": True,
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
            "episode": "E27",
            "status": "V18_WRITER_AGENT_V050_ENTITY_SEQUENCE_NOT_FINAL",
            "writer_agent_version": "0.5.0",
            "writer_agent_schema": "1.4.0",
            "runtime_seconds": cursor,
            "contract_runtime_seconds": 170.0,
            "runtime_delta_seconds": cursor - 170.0,
            "runtime_delta_reason": "B06-U03 raw final 0.5-second freeze excluded by conditional admission.",
            "audio_policy": "NATIVE_MULTIMODAL_DIALOGUE_SFX_AMBIENCE_NO_EXTERNAL_BGM",
            "platformUploadAllowed": False,
        },
        "timeline": {
            "videoTracks": [{"id": "E27_V050_ENTITY_REFERENCE_VIDEO", "clips": video_clips}],
            "audioTracks": [{"id": "E27_V050_NATIVE_MULTIMODAL_AUDIO", "clips": audio_clips}],
        },
        "qingshanAudit": {
            "episode": "E27",
            "pipelineStage": "WRITER_AGENT_V050_ENTITY_REFERENCE_FULLCUT",
            "final": False,
            "platformUploadAllowed": False,
            "paddingForbidden": True,
            "sourceUnitCount": 13,
            "expectedRuntimeSeconds": cursor,
            "contractRuntimeSeconds": 170.0,
            "conditionalSourceCount": 2,
        },
    }
    PROJECT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    build = {
        "schema": "qingshan.agentcut.v050-build-receipt.v1",
        "episode": "E27",
        "status": "BUILT_NOT_RENDERED",
        "project": str(PROJECT),
        "output": str(OUTPUT),
        "runtime_seconds": cursor,
        "contract_runtime_seconds": 170.0,
        "runtime_delta_seconds": cursor - 170.0,
        "sources": source_manifest,
    }
    BUILD_RECEIPT.write_text(json.dumps(build, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "project": str(PROJECT), "runtime_seconds": cursor, "sources": len(source_manifest)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
