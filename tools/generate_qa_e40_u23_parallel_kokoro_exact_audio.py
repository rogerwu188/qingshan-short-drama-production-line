#!/usr/bin/env python3
"""Generate and QA zero-credit U23 DIA-016 Kokoro audition/reference audio."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import generate_qa_e40_u07_v2_kokoro_exact_audio as base
import generate_qa_e40_u12_parallel_kokoro_exact_audio as impl


ROOT = Path(__file__).resolve().parents[1]
TEXT = "你护的，是给帘后那位看。"
OUT = ROOT / "working_assets/e40_production_20260814/u23_parallel_kokoro_exact_audio_candidates_v1"
PRE_QA = ROOT / "qa/e40_preproduction_20260814/u23_parallel_kokoro_exact_audio_candidates_v1"
PROD_QA = ROOT / "qa/e40_production_20260814/u23_parallel_kokoro_exact_audio_candidates_v1"
RECEIPT = PRE_QA / "E40_U23_PARALLEL_KOKORO_CANDIDATE_GENERATION_RECEIPT_V1.json"
RIGHTS = PRE_QA / "E40_U23_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
QA = PROD_QA / "E40_U23_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
SELECTED = PROD_QA / "E40_U23_PARALLEL_KOKORO_SELECTED_AUDIO_RECEIPT_V1.json"
FAILURE_MEMORY = PROD_QA / "E40_U23_PARALLEL_KOKORO_V1_FAILURE_MEMORY_AND_V2_REPAIR_CONTRACT.json"
V2_OUT = ROOT / "working_assets/e40_production_20260814/u23_parallel_kokoro_exact_audio_candidates_v2"
V2_PRE_QA = ROOT / "qa/e40_preproduction_20260814/u23_parallel_kokoro_exact_audio_candidates_v2"
V2_PROD_QA = ROOT / "qa/e40_production_20260814/u23_parallel_kokoro_exact_audio_candidates_v2"
V2_RECEIPT = V2_PRE_QA / "E40_U23_PARALLEL_KOKORO_CANDIDATE_GENERATION_RECEIPT_V2.json"
V2_RIGHTS = V2_PRE_QA / "E40_U23_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V2.json"
V2_QA = V2_PROD_QA / "E40_U23_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V2.json"
V2_SELECTED = V2_PROD_QA / "E40_U23_PARALLEL_KOKORO_SELECTED_AUDIO_RECEIPT_V2.json"


def configure() -> None:
    base.TEXT = TEXT
    base.VOICES = ("zm_020",)
    base.SPEEDS = (0.92, 1.0, 1.08)
    base.OUT = OUT
    base.RECEIPT = RECEIPT
    base.RIGHTS = RIGHTS
    base.QA = QA


def bind_impl() -> None:
    impl.TEXT = TEXT
    impl.TARGET_DURATION = 3.0
    impl.OUT = OUT
    impl.PRE_QA = PRE_QA
    impl.PROD_QA = PROD_QA
    impl.RECEIPT = RECEIPT
    impl.RIGHTS = RIGHTS
    impl.QA = QA
    impl.configure = configure


def configure_v2() -> None:
    base.TEXT = TEXT
    base.VOICES = ("zm_020",)
    base.SPEEDS = (1.25, 1.4, 1.55)
    base.OUT = V2_OUT
    base.RECEIPT = V2_RECEIPT
    base.RIGHTS = V2_RIGHTS
    base.QA = V2_QA


def bind_impl_v2() -> None:
    impl.TEXT = TEXT
    impl.TARGET_DURATION = 3.0
    impl.OUT = V2_OUT
    impl.PRE_QA = V2_PRE_QA
    impl.PROD_QA = V2_PROD_QA
    impl.RECEIPT = V2_RECEIPT
    impl.RIGHTS = V2_RIGHTS
    impl.QA = V2_QA
    impl.configure = configure_v2


def failures(similarity: float, audio: dict) -> list[str]:
    failed = []
    if similarity != 1.0:
        failed.append("ASR_NOT_EXACT")
    if not 2.2 <= audio["duration_seconds"] <= 4.2:
        failed.append("DURATION_OUTSIDE_2P2_TO_4P2")
    if audio["integrated_lufs"] is None or not -19.5 <= audio["integrated_lufs"] <= -16.0:
        failed.append("LOUDNESS_FAIL")
    if audio["true_peak_dbfs"] is None or audio["true_peak_dbfs"] > -1.0:
        failed.append("TRUE_PEAK_FAIL")
    return failed


def rewrite_generation_receipts() -> None:
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    for item in payload["outputs"]:
        for key in ("source_path", "normalized_path"):
            old = ROOT / item[key]
            new = old.with_name(old.name.replace("E40-DIA010_", "E40-DIA016_"))
            if new.exists():
                raise SystemExit(f"FAIL_CLOSED_OUTPUT_COLLISION:{new}")
            old.rename(new)
            item[key] = str(new.relative_to(ROOT))
            item[key.replace("_path", "_sha256")] = base.sha(new)
    payload.update(
        {
            "schema": "qingshan.e40.u23.parallel.kokoro_candidate_generation.v1",
            "episode": "E40",
            "unit_id": "U23",
            "scene_id": "13-4",
            "dialogue_id": "E40-DIA-016",
            "speaker": "云羊",
            "expected_text": TEXT,
            "mode": "LOCAL_KOKORO_ZERO_PROVIDER_POST",
            "intended_use": "AUDITION_AND_DIALOGUE_REFERENCE_ONLY_NATIVE_VIDEO_LIP_SYNC_REMAINS_REQUIRED",
        }
    )
    rights = json.loads(RIGHTS.read_text(encoding="utf-8"))
    rights.update(
        {
            "schema": "qingshan.e40.u23.parallel.kokoro_commercial_rights_evidence.v1",
            "episode": "E40",
            "unit_id": "U23",
            "dialogue_id": "E40-DIA-016",
            "speaker": "云羊",
            "voice_type": "BUILT_IN_MODEL_CHINESE_MALE_SPEAKER_NOT_USER_CLONE",
            "continuity_basis": "First release-clear local Yunyang binding. zm_020 is the only remaining built-in Chinese male voice not already bound to Chenji (zm_009) or Ashuan (zm_010), preserving cast separation while matching a bright young male baseline.",
            "performance_contract": "17-year-old male medium register, bright and quick; low breath after combat, dawning understanding, no mature baritone or announcer delivery.",
        }
    )
    base.atomic_json(RIGHTS, rights)
    payload["rights_evidence_sha256"] = base.sha(RIGHTS)
    base.atomic_json(RECEIPT, payload)


def rewrite_v2_generation_receipts() -> None:
    payload = json.loads(V2_RECEIPT.read_text(encoding="utf-8"))
    for item in payload["outputs"]:
        for key in ("source_path", "normalized_path"):
            old = ROOT / item[key]
            new = old.with_name(old.name.replace("E40-DIA006_", "E40-DIA016_"))
            if new.exists():
                raise SystemExit(f"FAIL_CLOSED_V2_OUTPUT_COLLISION:{new}")
            old.rename(new)
            item[key] = str(new.relative_to(ROOT))
            item[key.replace("_path", "_sha256")] = base.sha(new)
    payload.update(
        {
            "schema": "qingshan.e40.u23.parallel.kokoro_candidate_generation.v2",
            "episode": "E40",
            "unit_id": "U23",
            "scene_id": "13-4",
            "dialogue_id": "E40-DIA-016",
            "speaker": "云羊",
            "expected_text": TEXT,
            "mode": "LOCAL_KOKORO_ZERO_PROVIDER_POST_DURATION_REPAIR",
            "failure_memory_path": str(FAILURE_MEMORY.relative_to(ROOT)),
            "failure_memory_sha256": base.sha(FAILURE_MEMORY),
            "intended_use": "AUDITION_AND_DIALOGUE_REFERENCE_ONLY_NATIVE_VIDEO_LIP_SYNC_REMAINS_REQUIRED",
        }
    )
    rights = json.loads(V2_RIGHTS.read_text(encoding="utf-8"))
    rights.update(
        {
            "schema": "qingshan.e40.u23.parallel.kokoro_commercial_rights_evidence.v2",
            "episode": "E40",
            "unit_id": "U23",
            "dialogue_id": "E40-DIA-016",
            "speaker": "云羊",
            "voice_type": "BUILT_IN_MODEL_CHINESE_MALE_SPEAKER_NOT_USER_CLONE",
            "continuity_basis": "Preserve the newly established release-clear Yunyang zm_020 identity while changing only pace/prosody after duration-only V1 failure.",
            "performance_contract": "17-year-old male medium register, bright and quick; low breath after combat, dawning understanding, no mature baritone or announcer delivery.",
        }
    )
    base.atomic_json(V2_RIGHTS, rights)
    payload["rights_evidence_sha256"] = base.sha(V2_RIGHTS)
    base.atomic_json(V2_RECEIPT, payload)


def generate() -> int:
    bind_impl()
    result = impl.generate()
    if result != 0:
        return result
    rewrite_generation_receipts()
    print(json.dumps({"status": "PASS_ZERO_CREDIT_U23_CANDIDATES_GENERATED_QA_PENDING", "candidates": 3}, ensure_ascii=False))
    return 0


def repair_existing_receipts() -> int:
    if not RECEIPT.is_file() or QA.exists():
        raise SystemExit("FAIL_CLOSED_PARTIAL_RECEIPT_MISSING_OR_QA_ALREADY_EXISTS")
    rewrite_generation_receipts()
    print(json.dumps({"status": "PASS_EXISTING_U23_CANDIDATES_REBOUND_NO_REGENERATION", "candidates": 3}, ensure_ascii=False))
    return 0


def generate_v2() -> int:
    if not FAILURE_MEMORY.is_file() or not QA.is_file() or V2_RECEIPT.exists():
        raise SystemExit("FAIL_CLOSED_V2_PREREQUISITE_MISSING_OR_COLLISION")
    v1 = json.loads(QA.read_text(encoding="utf-8"))
    if v1.get("status") != "FAIL_NO_CANDIDATE" or any(row.get("failures") != ["DURATION_OUTSIDE_2P2_TO_4P2"] for row in v1.get("candidates", [])):
        raise SystemExit("FAIL_CLOSED_V1_NOT_DURATION_ONLY")
    configure_v2()
    result = base.generate()
    if result != 0:
        return result
    rewrite_v2_generation_receipts()
    print(json.dumps({"status": "PASS_ZERO_CREDIT_U23_V2_CANDIDATES_GENERATED_QA_PENDING", "candidates": 3}, ensure_ascii=False))
    return 0


def qa() -> int:
    bind_impl()
    impl.failures = failures
    result = impl.qa()
    payload = json.loads(QA.read_text(encoding="utf-8"))
    payload.update(
        {
            "schema": "qingshan.e40.u23.parallel.kokoro_exact_audio_machine_qa.v1",
            "episode": "E40",
            "unit_id": "U23",
            "scene_id": "13-4",
            "dialogue_id": "E40-DIA-016",
            "speaker": "云羊",
            "expected_text": TEXT,
            "selection_rule": "exact normalized ASR and audio gates; preserve distinct release-clear Yunyang zm_020 identity; duration nearest canonical 3.0s",
            "transport_scope": "AUDITION_REFERENCE_ONLY_MODEL_NATIVE_EXACT_LINE_AND_VISIBLE_LIP_SYNC_STILL_REQUIRED",
        }
    )
    base.atomic_json(QA, payload)
    selected = payload.get("selected")
    if selected:
        base.atomic_json(
            SELECTED,
            {
                "schema": "qingshan.e40.u23.parallel.kokoro_selected_audio_receipt.v1",
                "status": "PASS_MACHINE_SELECTED_REFERENCE_AUDIO",
                "created_at": base.now(),
                "episode": "E40",
                "unit_id": "U23",
                "scene_id": "13-4",
                "dialogue_id": "E40-DIA-016",
                "speaker": "云羊",
                "exact_text": TEXT,
                "selected": selected,
                "machine_qa_path": str(QA.relative_to(ROOT)),
                "machine_qa_sha256": base.sha(QA),
                "rights_evidence_path": str(RIGHTS.relative_to(ROOT)),
                "rights_evidence_sha256": base.sha(RIGHTS),
                "provider_posts": 0,
                "credits": 0,
                "final_video_transport": "MODEL_NATIVE_EXACT_LINE_REQUIRED_REFERENCE_AUDIO_NOT_AGENTCUT_OVERLAY",
            },
        )
    return result


def qa_v2() -> int:
    bind_impl_v2()
    impl.failures = failures
    result = impl.qa()
    payload = json.loads(V2_QA.read_text(encoding="utf-8"))
    payload.update(
        {
            "schema": "qingshan.e40.u23.parallel.kokoro_exact_audio_machine_qa.v2",
            "episode": "E40",
            "unit_id": "U23",
            "scene_id": "13-4",
            "dialogue_id": "E40-DIA-016",
            "speaker": "云羊",
            "expected_text": TEXT,
            "failure_memory_path": str(FAILURE_MEMORY.relative_to(ROOT)),
            "failure_memory_sha256": base.sha(FAILURE_MEMORY),
            "selection_rule": "exact normalized ASR and audio gates; preserve Yunyang zm_020 identity; duration nearest canonical 3.0s after substantive pace repair",
            "transport_scope": "AUDITION_REFERENCE_ONLY_MODEL_NATIVE_EXACT_LINE_AND_VISIBLE_LIP_SYNC_STILL_REQUIRED",
        }
    )
    base.atomic_json(V2_QA, payload)
    selected = payload.get("selected")
    if selected:
        base.atomic_json(
            V2_SELECTED,
            {
                "schema": "qingshan.e40.u23.parallel.kokoro_selected_audio_receipt.v2",
                "status": "PASS_MACHINE_SELECTED_REFERENCE_AUDIO",
                "created_at": base.now(),
                "episode": "E40",
                "unit_id": "U23",
                "scene_id": "13-4",
                "dialogue_id": "E40-DIA-016",
                "speaker": "云羊",
                "exact_text": TEXT,
                "selected": selected,
                "machine_qa_path": str(V2_QA.relative_to(ROOT)),
                "machine_qa_sha256": base.sha(V2_QA),
                "rights_evidence_path": str(V2_RIGHTS.relative_to(ROOT)),
                "rights_evidence_sha256": base.sha(V2_RIGHTS),
                "provider_posts": 0,
                "credits": 0,
                "final_video_transport": "MODEL_NATIVE_EXACT_LINE_REQUIRED_REFERENCE_AUDIO_NOT_AGENTCUT_OVERLAY",
            },
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate", action="store_true")
    group.add_argument("--repair-existing-receipts", action="store_true")
    group.add_argument("--qa", action="store_true")
    group.add_argument("--generate-v2", action="store_true")
    group.add_argument("--qa-v2", action="store_true")
    args = parser.parse_args()
    if args.generate:
        return generate()
    if args.repair_existing_receipts:
        return repair_existing_receipts()
    if args.generate_v2:
        return generate_v2()
    if args.qa_v2:
        return qa_v2()
    return qa()


if __name__ == "__main__":
    raise SystemExit(main())
