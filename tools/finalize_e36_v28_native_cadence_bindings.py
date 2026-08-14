#!/usr/bin/env python3
"""Replace the invalid interpolated E36 line-28 binding with the native VFR repair."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e36_agentcut_20260730"
SOURCE_V12 = QA / "E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V12.json"
SOURCE_V13 = QA / "E36_AGENTCUT_ACCEPTED_ONLY_SOURCE_MAP_V13.json"
BINDING_V16 = QA / "E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V16.json"
BINDING_V17 = QA / "E36_ACCEPTED_SOURCE_TRANSCRIPT_BINDING_AUDIT_V17.json"

MEDIA = (
    "qa/e36_agentcut_20260730/budget_extension_11000_focused_native_dialogue_v1/"
    "E36_L28_CADENCE_REPAIR_NATIVE_VFR_V2.mp4"
)
MEDIA_SHA = "fa6bb9db8d680414926e172fc9cb3d49b8452c52b27a27b01ee0be6195f6c211"
ACCEPTANCE = (
    "qa/e36_agentcut_20260730/budget_extension_11000_focused_native_dialogue_v1/"
    "E36_L28_CADENCE_REPAIR_NATIVE_VFR_ACCEPTANCE_QA_V3.json"
)
ACCEPTANCE_SHA = "5965b619e3cee217ea4c9f3ef2fb0f6e4f65308b3b028cb996b163a297cb568c"
DIALOGUE = (
    "qa/e36_agentcut_20260730/budget_extension_11000_focused_native_dialogue_v1/"
    "E36_L28_CADENCE_REPAIR_NATIVE_VFR_DIALOGUE_GATE_V2.json"
)
DIALOGUE_SHA = "bf2d0ab3a918926a604d9b3e2debea8ed332bffc8fe2d973d32723f1434c068f"
OLD_SOURCE_ID = "U14_L28_G2728_V6"
NEW_SOURCE_ID = "U14_L28_NATIVE_VFR_V2"
EXPECTED = "这尺上还叠着两家的记。批次，是景朝的；折法，是王府账房的。"
TRANSCRIPT = "这尺上还叠着两家的记 批次是景朝的 折法是王府账房的"
COVERAGE = "这尺上还叠着两家的记批次是景朝的折法是王府账房的"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    assert sha256(ROOT / MEDIA) == MEDIA_SHA
    assert sha256(ROOT / ACCEPTANCE) == ACCEPTANCE_SHA
    assert sha256(ROOT / DIALOGUE) == DIALOGUE_SHA
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    source_map = copy.deepcopy(load(SOURCE_V12))
    source_map["schema"] = "e36_agentcut_accepted_only_source_map_v13"
    source_map["generated_at"] = generated_at
    source_map["source_cl2x"] = "CL2X-924"
    source_map["status"] = "PASS_MOTION_30_OF_30_TRANSCRIPT_47_OF_47_NATIVE_CADENCE_AGENTCUT_READY"
    target = next(item for item in source_map["sources"] if item["source_id"] == OLD_SOURCE_ID)
    assert "MINTERPOLATE" in target["media"]
    target.clear()
    target.update(
        {
            "source_id": NEW_SOURCE_ID,
            "canonical_units": ["U14"],
            "admission": "PASS_ACCEPTED_ONLY_CANONICAL_LINE28_NATIVE_DIALOGUE_NATIVE_VFR_CADENCE_NO_INTERPOLATION",
            "media": MEDIA,
            "media_sha256": MEDIA_SHA,
            "qa_authority": ACCEPTANCE,
            "qa_sha256": ACCEPTANCE_SHA,
            "duration_seconds": 6.082993,
            "accepted_only_timeline_seconds": [320.362961, 326.445954],
            "probe": {
                "streams": [
                    {
                        "index": 0,
                        "codec_name": "h264",
                        "codec_type": "video",
                        "width": 720,
                        "height": 1280,
                        "r_frame_rate": "24/1",
                        "avg_frame_rate": "2976/145",
                    },
                    {
                        "index": 1,
                        "codec_name": "aac",
                        "codec_type": "audio",
                        "sample_rate": "44100",
                        "channels": 2,
                        "r_frame_rate": "0/0",
                    },
                ],
                "format": {"duration": "6.082993"},
            },
        }
    )
    source_map["accepted_only_runtime_seconds"] = 326.445954
    source_map["credits"] = {
        "new_generation_credits": 2224,
        "episode_total": 10900,
        "cap": 11000,
        "headroom": 100,
    }
    source_map["blocked_by"] = (
        "PROMOTION_ONLY:V28_CONTINUOUS_AUDIOVISUAL_WATCH_AND_INDEPENDENT_LOCAL_CLAUDE_REVIEW_INCOMPLETE;"
        "PLATFORM_SUBMISSION_ONLY:ACCOUNT_IDENTITY_AND_CREDENTIALS_NOT_LOCALLY_DECLARED"
    )
    source_map["next_action"] = (
        "Complete the uninterrupted V28 audiovisual watch and independent local Claude review; "
        "then bind the accepted-only V28 release package without any additional paid generation."
    )
    assert not any("MINTERPOLATE" in item.get("media", "") for item in source_map["sources"])
    write(SOURCE_V13, source_map)

    binding = copy.deepcopy(load(BINDING_V16))
    binding["schema"] = "qingshan.e36_accepted_source_transcript_binding_audit.v17"
    binding["generated_at"] = generated_at
    binding["inputs"]["accepted_only_source_map"] = {
        "path": str(SOURCE_V13.relative_to(ROOT)),
        "sha256": sha256(SOURCE_V13),
    }
    source = next(item for item in binding["source_results"] if item["source_id"] == OLD_SOURCE_ID)
    evidence = {
        "path": DIALOGUE,
        "sha256": DIALOGUE_SHA,
        "status": "PASS",
        "dialogue_required": True,
        "dialogue_ids": ["E36-L28"],
        "expected_text": EXPECTED,
        "transcript": TRANSCRIPT,
        "recall_score": 1.0,
        "direct_canonical_adjudication": (
            "PASS_LINE28_PRONUNCIATION_HARD_HUMAN_LISTENING_EXEMPTION_VISIBLE_CHENJI_"
            "NATIVE_VFR_CADENCE_NO_INTERPOLATION_CORE_SCORE_88_GE80"
        ),
        "coverage_text": COVERAGE,
    }
    source.update(
        {
            "source_id": NEW_SOURCE_ID,
            "media": MEDIA,
            "media_sha256": MEDIA_SHA,
            "dialogue_evidence_status": "PASS_BOUND_MANUAL_LISTENING_EXEMPTION_NATIVE_VFR",
            "selected_evidence": evidence,
            "all_matching_evidence": [copy.deepcopy(evidence)],
        }
    )
    binding["gate_results"]["accepted_source_sha_binding"] = "PASS_55_SOURCES_INDEXED_V13"
    binding["gate_results"]["dialogue_QA_binding"] = "PASS_55_OF_55_NATIVE_VFR_LINE28"
    binding["gate_results"]["agentcut_dialogue_gate"] = "PASS_COMPLETE_47_OF_47_V28"
    binding["blocked_by"] = source_map["blocked_by"]
    binding["next_action"] = source_map["next_action"]
    binding["workaround_executed"] = (
        "Replaced the invalid interpolated line-28 binding with a model-native Mandarin source; "
        "removed only provider cadence duplicates at zero credit while preserving real-time VFR PTS and native audio."
    )
    binding["credits"] = {
        "pay_this_action": 0,
        "refund_this_action": 0,
        "net_this_action": 0,
        "episode_source_net": 10900,
        "episode_cap": 11000,
        "remaining_headroom": 100,
    }
    assert not any("MINTERPOLATE" in item.get("media", "") for item in binding["source_results"])
    write(BINDING_V17, binding)

    print(
        json.dumps(
            {
                "source_map": str(SOURCE_V13.relative_to(ROOT)),
                "source_map_sha256": sha256(SOURCE_V13),
                "transcript_binding": str(BINDING_V17.relative_to(ROOT)),
                "transcript_binding_sha256": sha256(BINDING_V17),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
