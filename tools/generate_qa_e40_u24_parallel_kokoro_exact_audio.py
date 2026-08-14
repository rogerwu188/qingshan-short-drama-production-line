#!/usr/bin/env python3
"""Generate and machine-QA release-clear local U24 DIA-017 audio candidates."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import generate_qa_e40_u07_v2_kokoro_exact_audio as base
import generate_qa_e40_u12_parallel_kokoro_exact_audio as impl


ROOT = Path(__file__).resolve().parents[1]
TEXT = "你，不是本宫能买的棋子。"
OUT = ROOT / "working_assets/e40_production_20260814/u24_parallel_kokoro_exact_audio_candidates_v1"
PRE_QA = ROOT / "qa/e40_preproduction_20260814/u24_parallel_kokoro_exact_audio_candidates_v1"
PROD_QA = ROOT / "qa/e40_production_20260814/u24_parallel_kokoro_exact_audio_candidates_v1"
RECEIPT = PRE_QA / "E40_U24_PARALLEL_KOKORO_CANDIDATE_GENERATION_RECEIPT_V1.json"
RIGHTS = PRE_QA / "E40_U24_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
QA = PROD_QA / "E40_U24_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
SELECTED = PROD_QA / "E40_U24_PARALLEL_KOKORO_SELECTED_AUDIO_RECEIPT_V1.json"


def configure() -> None:
    base.TEXT = TEXT
    base.VOICES = ("zf_001",)
    base.SPEEDS = (1.1, 1.25, 1.4)
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


def rewrite_generation_receipts() -> None:
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    for item in payload["outputs"]:
        for key in ("source_path", "normalized_path"):
            old = ROOT / item[key]
            new = old.with_name(old.name.replace("E40-DIA010_", "E40-DIA017_"))
            if new.exists():
                raise SystemExit(f"FAIL_CLOSED_OUTPUT_COLLISION:{new}")
            old.rename(new)
            item[key] = str(new.relative_to(ROOT))
            item[key.replace("_path", "_sha256")] = base.sha(new)
    payload.update(
        {
            "schema": "qingshan.e40.u24.parallel.kokoro_candidate_generation.v1",
            "episode": "E40",
            "unit_id": "U24",
            "scene_id": "13-5",
            "dialogue_id": "E40-DIA-017",
            "speaker": "云妃",
            "expected_text": TEXT,
            "mode": "LOCAL_KOKORO_ZERO_PROVIDER_POST",
            "intended_use": "RIGHTS_CLEARED_EXACT_AUDIO_FOR_HIDDEN_FACE_AGENTCUT_ASSEMBLY",
        }
    )
    rights = json.loads(RIGHTS.read_text(encoding="utf-8"))
    rights.update(
        {
            "schema": "qingshan.e40.u24.parallel.kokoro_commercial_rights_evidence.v1",
            "episode": "E40",
            "unit_id": "U24",
            "dialogue_id": "E40-DIA-017",
            "speaker": "云妃",
            "voice_type": "BUILT_IN_MODEL_CHINESE_FEMALE_SPEAKER_NOT_USER_CLONE",
            "continuity_basis": "Preserve admitted E40 U02-U03/U10/U13/U14 Yunfei voice identity with built-in zf_001.",
            "performance_contract": "Unarmed acknowledgment after testing Chenji; controlled noble female register, no threat edge, no announcer delivery.",
        }
    )
    base.atomic_json(RIGHTS, rights)
    payload["rights_evidence_sha256"] = base.sha(RIGHTS)
    base.atomic_json(RECEIPT, payload)


def generate() -> int:
    bind_impl()
    result = impl.generate()
    if result != 0:
        return result
    rewrite_generation_receipts()
    print(json.dumps({"status": "PASS_ZERO_CREDIT_U24_CANDIDATES_GENERATED_QA_PENDING", "candidates": 3}, ensure_ascii=False))
    return 0


def qa() -> int:
    bind_impl()
    result = impl.qa()
    payload = json.loads(QA.read_text(encoding="utf-8"))
    payload.update(
        {
            "schema": "qingshan.e40.u24.parallel.kokoro_exact_audio_machine_qa.v1",
            "episode": "E40",
            "unit_id": "U24",
            "scene_id": "13-5",
            "dialogue_id": "E40-DIA-017",
            "speaker": "云妃",
            "expected_text": TEXT,
            "selection_rule": "exact normalized ASR and audio gates; preserve admitted Yunfei zf_001 identity; duration nearest canonical 3.0s",
            "transport_scope": "FINAL_EXACT_LINE_AUDIO_ALLOWED_FOR_HIDDEN_FACE_AGENTCUT_ASSEMBLY",
        }
    )
    base.atomic_json(QA, payload)
    selected = payload.get("selected")
    if selected:
        base.atomic_json(
            SELECTED,
            {
                "schema": "qingshan.e40.u24.parallel.kokoro_selected_audio_receipt.v1",
                "status": "PASS_MACHINE_SELECTED_FINAL_EXACT_AUDIO",
                "created_at": base.now(),
                "episode": "E40",
                "unit_id": "U24",
                "scene_id": "13-5",
                "dialogue_id": "E40-DIA-017",
                "speaker": "云妃",
                "exact_text": TEXT,
                "selected": selected,
                "machine_qa_path": str(QA.relative_to(ROOT)),
                "machine_qa_sha256": base.sha(QA),
                "rights_evidence_path": str(RIGHTS.relative_to(ROOT)),
                "rights_evidence_sha256": base.sha(RIGHTS),
                "provider_posts": 0,
                "credits": 0,
                "final_video_transport": "HIDDEN_FACE_RIGHTS_CLEARED_EXACT_AUDIO_AGENTCUT_ALLOWED",
            },
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate", action="store_true")
    group.add_argument("--qa", action="store_true")
    args = parser.parse_args()
    return generate() if args.generate else qa()


if __name__ == "__main__":
    raise SystemExit(main())
