#!/usr/bin/env python3
"""Restore the complete U03-S1 model-native dialogue before E37 promotion."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/e37_agentcut_v4_schema_reconciled_20260803.json"
OUTPUT = ROOT / "configs/e37_agentcut_v5_canonical_dialogue_restored_20260803.json"
RESTORED = ROOT / "working_assets/e37_video_20260803/remaining_u03_u07_pfm_v2_overhead_reveal_v4/E37_U03_S1_ZERO_CREDIT_SMOOTH_ROAM_V3.mp4"
CADENCE = ROOT / "qa/e37_agentcut_20260803/v5_dialogue_binding_repair/E37_U03_S1_RESTORED_CADENCE.json"
FINAL = ROOT / "exports/e37/agentcut_v5_canonical_dialogue_restored_subtitled_outro_20260803/E37_AGENTCUT_V5_CANONICAL_DIALOGUE_RESTORED_SUBTITLED_OUTRO_NOT_FINAL.mp4"

LINE_MAP = {
    "U01-S1": [1, 2], "U02-S1": [3, 4], "U02-S2": [5, 6], "U03-S1": [7, 8],
    "U03-S2": [9, 10], "U03-S3": [11, 12], "U03-S4": [13, 14], "U06-S2": [15, 16],
    "U07-S1": [17, 18], "U07-S2": [19], "U07-S3": [20, 21], "U07-S4": [22, 23],
    "U07-S5": [24, 25], "U07-S6": [26], "U08-S1": [27, 28], "U08-S2": [29],
    "U08-S3": [30], "U08-S4": [31],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if not RESTORED.is_file() or not CADENCE.is_file():
        raise SystemExit("restored source or cadence report missing")
    project = deepcopy(json.loads(SOURCE.read_text(encoding="utf-8")))
    restored_sha = sha256(RESTORED)
    cadence_sha = sha256(CADENCE)
    replaced_video = replaced_audio = 0

    for clip in project["timeline"]["videoTracks"][0]["clips"]:
        if clip["metadata"].get("segment_id") != "U03-S1":
            continue
        clip["id"] = "E37-U03-S1-CANONICAL-DIALOGUE-RESTORED-V5"
        clip["source"] = str(RESTORED)
        clip["in"] = 0.0
        clip["duration"] = 8.04
        clip["metadata"].update({
            "canonical_lines": [7, 8],
            "admission": "PASS_ACCEPTED_SOURCE_NATIVE_FULL_CANONICAL_DIALOGUE_V5",
            "source_sha256": restored_sha,
            "source_reference_mode": "generated_video",
            "cadence_report_path": str(CADENCE),
            "cadence_report_sha256": cadence_sha,
            "cut_reason": "RESTORE_OMITTED_CANONICAL_CLAUSE_WITH_ORIGINAL_MODEL_NATIVE_LIPSYNC_SOURCE",
            "new_information": "U03-S1 complete canonical lines7-8 including 我在另一处见过",
            "semantic_group": "E37_U03-S1_COMPLETE_DIALOGUE_V5",
        })
        replaced_video += 1

    for clip in project["timeline"]["audioTracks"][0]["clips"]:
        segment_id = clip["metadata"].get("segment_id")
        line_numbers = LINE_MAP.get(segment_id, [])
        clip["metadata"]["source_id"] = clip["id"]
        clip["metadata"]["expected_dialogue_ids"] = [f"E37-L{number:03d}" for number in line_numbers]
        if segment_id != "U03-S1":
            continue
        clip["id"] = "E37-U03-S1-CANONICAL-DIALOGUE-RESTORED-V5-AUDIO"
        clip["source"] = str(RESTORED)
        clip["in"] = 0.0
        clip["duration"] = 8.039
        clip["metadata"].update({
            "source_id": "E37-U03-S1-CANONICAL-DIALOGUE-RESTORED-V5-AUDIO",
            "audio_source": "MODEL_NATIVE_FROM_ACCEPTED_SOURCE_WITH_FULL_CANONICAL_LINES7_8",
            "source_sha256": restored_sha,
            "expected_dialogue_ids": ["E37-L007", "E37-L008"],
        })
        replaced_audio += 1

    if replaced_video != 1 or replaced_audio != 1:
        raise SystemExit(f"unexpected replacement counts: video={replaced_video} audio={replaced_audio}")
    project["metadata"]["status"] = "E37_V5_CANONICAL_DIALOGUE_RESTORED_PENDING_ASR_ALIGNMENT_RENDER_QA"
    project["metadata"]["v5_dialogue_repair"] = {
        "segment_id": "U03-S1",
        "restored_source": str(RESTORED),
        "restored_source_sha256": restored_sha,
        "reason": "V4 replacement omitted the canonical clause 我在另一处见过; V5 restores the accepted model-native source with visible lips and complete lines7-8.",
        "credits": {"pay": 0, "refund": 0, "net": 0},
    }
    project["output"]["path"] = str(FINAL)
    project["qingshanAudit"]["releaseEligible"] = False
    project["qingshanAudit"]["releaseBlock"] = "V5 requires caption alignment, native render and full final gates."
    OUTPUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "project": str(OUTPUT), "restored_source_sha256": restored_sha}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
