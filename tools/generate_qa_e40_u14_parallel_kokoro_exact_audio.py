#!/usr/bin/env python3
"""U14 adapter for local release-clear Kokoro exact audio and machine QA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import generate_qa_e40_u07_v2_kokoro_exact_audio as base
import generate_qa_e40_u12_parallel_kokoro_exact_audio as impl


ROOT = Path(__file__).resolve().parents[1]
TEXT = '替本宫"代办"印的手，就在身侧。'
OUT = ROOT / "working_assets/e40_production_20260814/u14_parallel_kokoro_exact_audio_candidates_v1"
PRE_QA = ROOT / "qa/e40_preproduction_20260814/u14_parallel_kokoro_exact_audio_candidates_v1"
PROD_QA = ROOT / "qa/e40_production_20260814/u14_parallel_kokoro_exact_audio_candidates_v1"
RECEIPT = PRE_QA / "E40_U14_PARALLEL_KOKORO_CANDIDATE_GENERATION_RECEIPT_V1.json"
RIGHTS = PRE_QA / "E40_U14_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
QA = PROD_QA / "E40_U14_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
V2_OUT = ROOT / "working_assets/e40_production_20260814/u14_parallel_kokoro_exact_audio_candidates_v2"
V2_QA = ROOT / "qa/e40_production_20260814/u14_parallel_kokoro_exact_audio_candidates_v2/E40_U14_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V2.json"
FAILURE_MEMORY = PROD_QA / "E40_U14_PARALLEL_KOKORO_V1_FAILURE_MEMORY_AND_V2_REPAIR_CONTRACT.json"


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
    impl.TARGET_DURATION = 3.5
    impl.OUT = OUT
    impl.PRE_QA = PRE_QA
    impl.PROD_QA = PROD_QA
    impl.RECEIPT = RECEIPT
    impl.RIGHTS = RIGHTS
    impl.QA = QA
    impl.V2_OUT = V2_OUT
    impl.V2_QA = V2_QA
    impl.FAILURE_MEMORY = FAILURE_MEMORY
    impl.configure = configure


def rewrite_u14_receipts() -> None:
    generated = json.loads(RECEIPT.read_text(encoding="utf-8"))
    for item in generated["outputs"]:
        for key in ("source_path", "normalized_path"):
            old = ROOT / item[key]
            new = old.with_name(old.name.replace("E40-DIA010_", "E40-DIA012_"))
            if new.exists():
                raise SystemExit(f"FAIL_CLOSED_OUTPUT_COLLISION:{new}")
            old.rename(new)
            item[key] = str(new.relative_to(ROOT))
            item[key.replace("_path", "_sha256")] = base.sha(new)
    generated.update({"schema": "qingshan.e40.u14.parallel.kokoro_candidate_generation.v1", "episode": "E40", "unit_id": "U14", "scene_id": "13-3", "dialogue_id": "E40-DIA-012", "speaker": "云妃", "expected_text": TEXT})
    rights = json.loads(RIGHTS.read_text(encoding="utf-8"))
    rights.update({"schema": "qingshan.e40.u14.parallel.kokoro_commercial_rights_evidence.v1", "episode": "E40", "unit_id": "U14", "dialogue_id": "E40-DIA-012", "speaker": "云妃", "voice_type": "BUILT_IN_MODEL_CHINESE_FEMALE_SPEAKER_NOT_USER_CLONE", "continuity_basis": "Preserve admitted E40 U02-U03/U10/U13 Yunfei voice identity with built-in zf_001."})
    base.atomic_json(RIGHTS, rights)
    generated["rights_evidence_sha256"] = base.sha(RIGHTS)
    base.atomic_json(RECEIPT, generated)


def rewrite_qa(path: Path, version: str) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update({"schema": f"qingshan.e40.u14.parallel.kokoro_exact_audio_machine_qa.{version}", "episode": "E40", "unit_id": "U14", "scene_id": "13-3", "dialogue_id": "E40-DIA-012", "speaker": "云妃", "expected_text": TEXT, "selection_rule": "exact normalized ASR and audio gates; preserve admitted zf_001 identity; duration nearest canonical 3.5s"})
    base.atomic_json(path, payload)
    return 0 if payload.get("selected") else 2


def generate() -> int:
    bind_impl()
    result = impl.generate()
    if result != 0:
        return result
    rewrite_u14_receipts()
    print(json.dumps({"status": "PASS_ZERO_CREDIT_U14_CANDIDATES_GENERATED_QA_PENDING", "candidates": 3}, ensure_ascii=False))
    return 0


def qa() -> int:
    bind_impl()
    impl.qa()
    return rewrite_qa(QA, "v1")


def repair_qa() -> int:
    bind_impl()
    impl.repair_qa()
    return rewrite_qa(V2_QA, "v2")


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate", action="store_true")
    group.add_argument("--qa", action="store_true")
    group.add_argument("--repair-qa", action="store_true")
    args = parser.parse_args()
    return generate() if args.generate else qa() if args.qa else repair_qa()


if __name__ == "__main__":
    raise SystemExit(main())
