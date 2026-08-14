#!/usr/bin/env python3
"""Replace the E28 U09 hold with the zero-credit local salvage candidate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e28_agentcut_v1_cl2x517_u09_hold_20260721.json"
OUTPUT = ROOT / "configs/e28_agentcut_v4_cl2x517_u09_pure_cut_20260722.json"
VIDEO = ROOT / "working_assets/e28_u09_local_salvage_v3_20260722/E28-CW-U09_LOCAL_SALVAGE_V3_PURE_CUT.mp4"
RENDER = ROOT / "exports/e28/agentcut_v4_cl2x517_u09_pure_cut_20260722/E28_AGENTCUT_V4_CL2X517_U09_PURE_CUT_NOT_FINAL.mp4"
CADENCE = ROOT / "qa/e28_u09_local_salvage_v3_20260722/E28_U09_LOCAL_SALVAGE_V3_FRAME_CADENCE.json"
OCR_ADJ = ROOT / "qa/e28_u09_local_salvage_v3_20260722/E28_U09_LOCAL_SALVAGE_V3_OCR_MACHINE_ADJUDICATION.json"
ADMISSION = ROOT / "workflow/tasks/E28_U09_LOCAL_SALVAGE_V3_ADMISSION_RECEIPT_20260722.json"
U09_DURATION = 12.12
RIPPLE = 13.0 - U09_DURATION


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def insert_after(clips: list[dict], predecessor: str, clip: dict) -> None:
    index = next(i for i, item in enumerate(clips) if item["id"] == predecessor)
    clips.insert(index + 1, clip)


def main() -> int:
    project = json.loads(BASE.read_text(encoding="utf-8"))
    source_sha = sha256(VIDEO)
    project["output"]["path"] = str(RENDER)
    project["metadata"].update(
        {
            "status": "V4_CL2X517_U09_PURE_CUT_NOT_FINAL",
            "hold_reason": None,
            "u09_admission": "PASS_LOCAL_REPAIR_QA",
            "platformUploadAllowed": False,
            "releaseAllowed": False,
            "duration_policy": "PLOT_INTEGRITY_ONLY_NO_ORIGINAL_DURATION_FLOOR",
        }
    )

    video_clip = {
        "id": "E28-CW-U09-VIDEO",
        "source": str(VIDEO),
        "start": 107.0,
        "in": 0.0,
        "duration": U09_DURATION,
        "metadata": {
            "episode": "E28",
            "scene_id": "E28-CW-S04-SCREEN-CORRIDOR-FIGHT",
            "source_id": "E28-CW-U09",
            "unit_id": "E28-CW-U09",
            "source_sha256": source_sha,
            "source_variant": "LOCAL_ZERO_CREDIT_SALVAGE_V3_PURE_CUT",
            "source_admission": "PASS_LOCAL_REPAIR_QA",
            "source_admission_confidence": 0.87,
            "cut_reason": "REPLACE_U09_BLACK_HOLD_WITH_IDENTITY_SAFE_EXISTING_RANGES",
            "narrative_function": "Masked instructor escapes through the broken window; three protagonists remain behind.",
            "new_information": "U09 action and aftermath without the original candidate's Yunyang identity error.",
            "semantic_group": "E28-CW-U09",
            "fallback_only": False,
            "axis_line": "E28-CW-S04-SCREEN-CORRIDOR-FIGHT::LOCKED_ACTION_AXIS",
            "eyeline": "E28-CW-U09::PRIMARY_ACTION_TARGET",
            "light_key": "MOONLESS_SNOW_NIGHT",
            "action_required": True,
            "action_trajectory": {
                "windup": "Masked corridor combat continues.",
                "contact": "The window breaks during the escape.",
                "force": "The masked instructor clears the snowy roofline.",
                "result": "Three protagonists remain and the snow alley is empty."
            },
            "source_reference_mode": "generated_video",
            "cadence_report_path": str(CADENCE),
            "ocr_report_path": str(OCR_ADJ),
            "admission_receipt_path": str(ADMISSION),
        },
    }
    audio_clip = {
        "id": "E28-CW-U09-AUDIO",
        "source": str(VIDEO),
        "start": 107.0,
        "in": 0.0,
        "duration": U09_DURATION,
        "volume": 0.82,
        "metadata": {
            "episode": "E28",
            "unit_id": "E28-CW-U09",
            "source_sha256": source_sha,
            "cut_reason": "NATIVE_AUDIO_FOLLOWS_LOCAL_SALVAGE_UNIT",
            "audio_policy": "NATIVE_MULTIMODAL_DIALOGUE_SFX_AMBIENCE_NO_EXTERNAL_BGM",
        },
    }
    insert_after(project["timeline"]["videoTracks"][0]["clips"], "E28-CW-U08-VIDEO", video_clip)
    insert_after(project["timeline"]["audioTracks"][0]["clips"], "E28-CW-U08-AUDIO", audio_clip)
    for track_type in ("videoTracks", "audioTracks"):
        for clip in project["timeline"][track_type][0]["clips"]:
            if clip["id"].startswith(("E28-CW-U10-", "E28-CW-U11-", "E28-CW-U12-", "E28-CW-U13-")):
                clip["start"] = round(float(clip["start"]) - RIPPLE, 3)

    runtime = round(172.0 - RIPPLE, 3)
    project["metadata"]["runtime_seconds"] = runtime
    project["metadata"]["contract_runtime_seconds"] = runtime

    audit = project["qingshanAudit"]
    audit.update(
        {
            "pipelineStage": "CL2X517_13_UNIT_ROUGH_ASSEMBLY_U09_PURE_CUT",
            "sourceUnitCount": 13,
            "expectedRuntimeSeconds": runtime,
            "contractRuntimeSeconds": runtime,
            "placeholder": None,
            "releaseBlock": "RUN_FULL_CUT_QA_AND_RESOLVE_EXISTING_CONDITIONAL_UNITS",
            "u09AdmissionReceipt": str(ADMISSION),
        }
    )
    OUTPUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "project": str(OUTPUT), "output": str(RENDER), "u09_sha256": source_sha}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
