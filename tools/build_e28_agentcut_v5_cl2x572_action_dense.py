#!/usr/bin/env python3
"""Replace E28 U02/U03/U11 with the CL2X-572 action-dense candidates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e28_agentcut_v4_cl2x517_u09_pure_cut_20260722.json"
OUTPUT = ROOT / "configs/e28_agentcut_v5_cl2x572_action_dense_20260722.json"
RENDER = ROOT / "exports/e28/agentcut_v5_cl2x572_action_dense_20260722/E28_AGENTCUT_V5_CL2X572_ACTION_DENSE_NOT_FINAL.mp4"
ADMISSION = ROOT / "qa/e28_cl2x572_action_dense_r1_20260722/E28_CL2X572_ACTION_DENSE_R1_MACHINE_ADMISSION.json"
AGENTCUT_RAW_REVIEW = ROOT / "qa/e28_cl2x572_action_dense_r1_20260722/E28_CL2X572_AGENTCUT_RAW_REVIEW.json"
AGENTCUT_ADMISSION = ROOT / "qa/e28_cl2x572_action_dense_r1_20260722/E28_CL2X572_AGENTCUT_CONDITIONAL_ADMISSION.json"
LEGACY_ADMISSION = ROOT / "qa/e28_13_video_unit_v3_ai_review_20260721/E28_13_VIDEO_UNIT_V3_CONDITIONAL_ADMISSION.json"

REPLACEMENTS = {
    "E28-CW-U02": {
        "source": ROOT / "working_assets/e28_cl2x572_action_dense_r1_20260722/E28-CW-U02_6d6803b0-b137-4065-b88e-ed1d2287a121.mp4",
        "duration": 15.0,
        "decision": "CONDITIONAL_MACHINE_ADMISSION",
        "confidence": 0.86,
        "raw_failure": "ocr.unlisted_diegetic_text",
        "cadence": ROOT / "qa/e28_cl2x572_action_dense_r1_20260722/E28-CW-U02_FRAME_CADENCE.json",
        "ocr": ROOT / "qa/e28_cl2x572_action_dense_r1_20260722/E28-CW-U02_OCR.json",
    },
    "E28-CW-U11": {
        "source": ROOT / "working_assets/e28_cl2x572_action_dense_r1_20260722/E28-CW-U11_0ce8cdf6-2352-4868-a1c0-2143b42f3016.mp4",
        "duration": 13.0,
        "decision": "PASS",
        "cadence": ROOT / "qa/e28_cl2x572_action_dense_r1_20260722/E28-CW-U11_FRAME_CADENCE.json",
        "ocr": ROOT / "qa/e28_cl2x572_action_dense_r1_20260722/E28-CW-U11_OCR.json",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    raw_review_items = []
    conditional_items = []
    for unit_id, replacement in REPLACEMENTS.items():
        if replacement["decision"] != "CONDITIONAL_MACHINE_ADMISSION":
            continue
        candidate = replacement["source"]
        candidate_sha = sha256(candidate)
        failure = replacement["raw_failure"]
        raw_review_items.append(
            {
                "media_path": str(candidate),
                "media_sha256": candidate_sha,
                "status": "FAIL",
                "issues": [{"rule_id": failure, "blocking": True}],
            }
        )
        conditional_items.append(
            {
                "unit_id": unit_id,
                "candidate_path": str(candidate),
                "candidate_sha256": candidate_sha,
                "raw_qa_status": "FAIL",
                "raw_failures": [failure],
                "decision": "CONDITIONAL_MACHINE_ADMISSION",
                "confidence": replacement["confidence"],
                "selection_reason": (
                    "Action-density and cadence repair passed. The remaining OCR finding is reversible, "
                    "does not alter character identity or plot facts, and is preserved without rewriting raw QA."
                ),
                "rollback_point": str(candidate),
                "replacement_condition": "Replace only if full-cut review finds the retained OCR condition narratively distracting.",
            }
        )
    legacy_admission = json.loads(LEGACY_ADMISSION.read_text(encoding="utf-8"))
    legacy_raw_path = Path(legacy_admission["raw_review"])
    legacy_raw = json.loads(legacy_raw_path.read_text(encoding="utf-8"))
    for legacy_unit_id in ("E28-CW-U03", "E28-CW-U06"):
        legacy_item = next(item for item in legacy_admission["items"] if item.get("unit_id") == legacy_unit_id)
        legacy_path = str(Path(legacy_item["candidate_path"]).resolve())
        legacy_raw_item = next(
            item
            for item in legacy_raw["items"]
            if str(Path(item.get("media_path", "")).resolve()) == legacy_path
        )
        conditional_items.append(legacy_item)
        raw_review_items.append(legacy_raw_item)
    raw_review = {
        "schema": "qingshan.raw_media_review.v1",
        "episode": "E28",
        "status": "FAIL",
        "items": raw_review_items,
    }
    AGENTCUT_RAW_REVIEW.write_text(json.dumps(raw_review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    agentcut_admission = {
        "schema": "qingshan.conditional_machine_admission.v1",
        "episode": "E28",
        "raw_review": str(AGENTCUT_RAW_REVIEW),
        "raw_review_sha256": sha256(AGENTCUT_RAW_REVIEW),
        "items": conditional_items,
    }
    AGENTCUT_ADMISSION.write_text(json.dumps(agentcut_admission, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    project = json.loads(BASE.read_text(encoding="utf-8"))
    for track_type in ("videoTracks", "audioTracks"):
        for clip in project["timeline"][track_type][0]["clips"]:
            unit_id = str(clip.get("id", "")).rsplit("-", 1)[0]
            replacement = REPLACEMENTS.get(unit_id)
            if replacement:
                clip["source"] = str(replacement["source"])
                clip["in"] = 0.0
                clip["duration"] = replacement["duration"]
                metadata = clip.setdefault("metadata", {})
                metadata.update(
                    {
                        "source_sha256": sha256(replacement["source"]),
                        "source_variant": "CL2X572_ACTION_DENSE_R1",
                        "source_admission": replacement["decision"],
                        "cadence_report_path": str(replacement["cadence"]),
                        "ocr_report_path": str(replacement["ocr"]),
                        "admission_receipt_path": str(ADMISSION),
                        "cut_reason": "CL2X572_ACTION_DENSITY_REPAIR",
                    }
                )
    prior_runtime = float(project["metadata"]["runtime_seconds"])
    runtime = prior_runtime
    project["output"]["path"] = str(RENDER)
    project["metadata"].update(
        {
            "status": "V5_CL2X572_ACTION_DENSE_NOT_FINAL",
            "runtime_seconds": runtime,
            "contract_runtime_seconds": runtime,
            "platformUploadAllowed": False,
            "releaseAllowed": False,
            "duration_policy": "PLOT_INTEGRITY_ONLY_NO_ORIGINAL_DURATION_FLOOR",
            "cl2x572_admission": str(ADMISSION),
        }
    )
    project["qingshanAudit"].update(
        {
            "pipelineStage": "CL2X576_TRUE_IMPROVEMENTS_U02_U11_RECUT_U03_RETAINED",
            "expectedRuntimeSeconds": runtime,
            "contractRuntimeSeconds": runtime,
            "releaseBlock": "RUN_FULL_CUT_QA_AND_COMPLETE_U09_FIXED_INPUT_REPLACEMENT",
            "cl2x572AdmissionReceipt": str(ADMISSION),
        }
    )
    project["qingshanAudit"]["roughAssemblyException"].update(
        {
            "reason": (
                "U02 diegetic OCR, retained U03 legacy cadence raw FAIL, and U06 designed-silence "
                "raw FAIL remain visible in this non-release review; U11 is now strict PASS."
            ),
            "affectedConditionalUnits": ["E28-CW-U02", "E28-CW-U03", "E28-CW-U06"],
            "releaseCondition": (
                "Complete U09 fixed-input replacement and final full-cut QA before release."
            ),
        }
    )
    project["sourceAdmissionPolicy"].update(
        {
            "conditionalAdmissionEvidencePath": str(AGENTCUT_ADMISSION),
            "allowConditionalCadenceFailForRoughAssembly": True,
            "allowedConditionalFailureCodes": [
                "video.periodic_duplicate",
                "audio.long_silence",
                "ocr.unlisted_diegetic_text",
                "ocr.lexicon_unconfigured_zero_recognition",
            ],
        }
    )

    OUTPUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS",
                "project": str(OUTPUT),
                "output": str(RENDER),
                "runtime_seconds": runtime,
                "u03_removed_seconds": 0.0,
                "replacements": {
                    unit_id: {
                        "source": str(item["source"]),
                        "sha256": sha256(item["source"]),
                        "duration": item["duration"],
                    }
                    for unit_id, item in REPLACEMENTS.items()
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
