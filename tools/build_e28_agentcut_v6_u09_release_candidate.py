#!/usr/bin/env python3
"""Replace E28 U09 with the fixed-input native-speed escape shot."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e28_agentcut_v5_cl2x572_action_dense_20260722.json"
OUTPUT = ROOT / "configs/e28_agentcut_v6_u09_fixed_input_release_candidate_20260722.json"
RENDER = ROOT / "exports/e28/agentcut_v6_u09_fixed_input_release_candidate_20260722/E28_AGENTCUT_V6_U09_FIXED_INPUT_RELEASE_CANDIDATE.mp4"
U09 = ROOT / "working_assets/e28_u09_fixed_input_cl2x569_20260722/E28-CW-U09_e49f28eb-4f75-44a4-9a4e-f8bdaaaf6bdb.mp4"
U09_DURATION = 8.057
U09_START = 107.0
OLD_U09_DURATION = 12.12
SHIFT = OLD_U09_DURATION - U09_DURATION
CADENCE = ROOT / "qa/e28_u09_fixed_input_cl2x569_20260722/E28_CW_U09_FRAME_CADENCE.json"
OCR = ROOT / "qa/e28_u09_fixed_input_cl2x569_20260722/E28_CW_U09_OCR.json"
REVIEW = ROOT / "qa/e28_u09_fixed_input_cl2x569_20260722/E28_CW_U09_MACHINE_VISUAL_REVIEW.json"
RECEIPT = ROOT / "workflow/tasks/E28_U09_FIXED_INPUT_CL2X569_SUBMIT_RECEIPT_20260722.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    required = (BASE, U09, CADENCE, OCR, REVIEW, RECEIPT)
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"Missing V6 input: {missing}")
    if json.loads(CADENCE.read_text(encoding="utf-8"))["status"] != "PASS":
        raise SystemExit("U09 cadence did not pass")
    if json.loads(OCR.read_text(encoding="utf-8"))["status"] != "PASS":
        raise SystemExit("U09 OCR did not pass")
    if json.loads(REVIEW.read_text(encoding="utf-8"))["status"] != "PASS":
        raise SystemExit("U09 visual review did not pass")

    project = json.loads(BASE.read_text(encoding="utf-8"))
    for track_type in ("videoTracks", "audioTracks"):
        for track in project["timeline"][track_type]:
            for clip in track.get("clips", []):
                unit_id = str(clip.get("id", "")).rsplit("-", 1)[0]
                if unit_id == "E28-CW-U09":
                    clip["source"] = str(U09)
                    clip["in"] = 0.0
                    clip["duration"] = U09_DURATION
                    metadata = clip.setdefault("metadata", {})
                    metadata.update(
                        {
                            "source_sha256": sha256(U09),
                            "source_variant": "U09_FIXED_INPUT_CL2X569",
                            "source_admission": "PASS",
                            "cadence_report_path": str(CADENCE),
                            "ocr_report_path": str(OCR),
                            "visual_review_path": str(REVIEW),
                            "admission_receipt_path": str(RECEIPT),
                            "cut_reason": "REPLACE_SALVAGE_PADDING_WITH_NATIVE_SPEED_CANONICAL_ESCAPE",
                            "duration_policy": "PLOT_INTEGRITY_ONLY_NO_SLOW_MOTION_OR_STATIC_PADDING",
                        }
                    )
                elif float(clip.get("start", 0.0)) > U09_START:
                    clip["start"] = round(float(clip["start"]) - SHIFT, 3)

    runtime = round(float(project["metadata"]["runtime_seconds"]) - SHIFT, 3)
    project["output"]["path"] = str(RENDER)
    project["metadata"].update(
        {
            "status": "V6_U09_FIXED_INPUT_RELEASE_CANDIDATE",
            "runtime_seconds": runtime,
            "contract_runtime_seconds": runtime,
            "platformUploadAllowed": False,
            "releaseAllowed": False,
            "duration_policy": "PLOT_INTEGRITY_ONLY_NO_ORIGINAL_DURATION_FLOOR",
            "u09_admission": "PASS_FIXED_INPUT_NATIVE_SPEED",
        }
    )
    project["qingshanAudit"].update(
        {
            "pipelineStage": "V6_U09_FIXED_INPUT_FINAL_FULLCUT_QA",
            "expectedRuntimeSeconds": runtime,
            "contractRuntimeSeconds": runtime,
            "releaseBlock": "RUN_V6_FULL_CUT_QA",
        }
    )
    project["qingshanAudit"]["roughAssemblyException"].update(
        {
            "reason": "U09 is strict PASS. Existing reversible conditional admissions remain preserved with original raw QA and rollback evidence.",
            "releaseCondition": "V6 full-cut technical and plot-integrity QA must pass before final lock.",
        }
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RENDER.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "PASS",
                "project": str(OUTPUT),
                "output": str(RENDER),
                "runtime_seconds": runtime,
                "u09_sha256": sha256(U09),
                "removed_padding_seconds": SHIFT,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
