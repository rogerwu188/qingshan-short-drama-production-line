#!/usr/bin/env python3
"""U17 adapter for local release-clear Kokoro exact audio and machine QA."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import generate_qa_e40_u07_v2_kokoro_exact_audio as base
import generate_qa_e40_u12_parallel_kokoro_exact_audio as impl


ROOT = Path(__file__).resolve().parents[1]
TEXT = "迹哥！"
OUT = ROOT / "working_assets/e40_production_20260814/u17_parallel_kokoro_exact_audio_candidates_v1"
PRE_QA = ROOT / "qa/e40_preproduction_20260814/u17_parallel_kokoro_exact_audio_candidates_v1"
PROD_QA = ROOT / "qa/e40_production_20260814/u17_parallel_kokoro_exact_audio_candidates_v1"
RECEIPT = PRE_QA / "E40_U17_PARALLEL_KOKORO_CANDIDATE_GENERATION_RECEIPT_V1.json"
RIGHTS = PRE_QA / "E40_U17_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
QA = PROD_QA / "E40_U17_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
V2_OUT = ROOT / "working_assets/e40_production_20260814/u17_parallel_kokoro_exact_audio_candidates_v2"
V2_QA = ROOT / "qa/e40_production_20260814/u17_parallel_kokoro_exact_audio_candidates_v2/E40_U17_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V2.json"
FAILURE_MEMORY = PROD_QA / "E40_U17_PARALLEL_KOKORO_V1_FAILURE_MEMORY_AND_V2_REPAIR_CONTRACT.json"


def configure() -> None:
    base.TEXT = TEXT
    base.VOICES = ("zm_010",)
    base.SPEEDS = (0.8, 0.92, 1.0)
    base.OUT = OUT
    base.RECEIPT = RECEIPT
    base.RIGHTS = RIGHTS
    base.QA = QA


def short_line_failures(similarity: float, audio: dict) -> list[str]:
    failed = []
    if similarity != 1.0:
        failed.append("ASR_NOT_EXACT")
    if not 0.6 <= audio["duration_seconds"] <= 2.0:
        failed.append("DURATION_OUTSIDE_0P6_TO_2P0")
    if audio["integrated_lufs"] is None or not -19.5 <= audio["integrated_lufs"] <= -16.0:
        failed.append("LOUDNESS_FAIL")
    if audio["true_peak_dbfs"] is None or audio["true_peak_dbfs"] > -1.0:
        failed.append("TRUE_PEAK_FAIL")
    return failed


def bind_impl() -> None:
    impl.TEXT = TEXT
    impl.TARGET_DURATION = 1.0
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
    impl.failures = short_line_failures


def rewrite_u17_receipts() -> None:
    generated = json.loads(RECEIPT.read_text(encoding="utf-8"))
    for item in generated["outputs"]:
        for key in ("source_path", "normalized_path"):
            old = ROOT / item[key]
            new = old.with_name(old.name.replace("E40-DIA010_", "E40-DIA015_"))
            if new.exists():
                raise SystemExit(f"FAIL_CLOSED_OUTPUT_COLLISION:{new}")
            old.rename(new)
            item[key] = str(new.relative_to(ROOT))
            item[key.replace("_path", "_sha256")] = base.sha(new)
    generated.update({"schema": "qingshan.e40.u17.parallel.kokoro_candidate_generation.v1", "episode": "E40", "unit_id": "U17", "scene_id": "13-4", "dialogue_id": "E40-DIA-015", "speaker": "阿栓", "expected_text": TEXT})
    rights = json.loads(RIGHTS.read_text(encoding="utf-8"))
    rights.update({"schema": "qingshan.e40.u17.parallel.kokoro_commercial_rights_evidence.v1", "episode": "E40", "unit_id": "U17", "dialogue_id": "E40-DIA-015", "speaker": "阿栓", "voice_type": "BUILT_IN_MODEL_CHINESE_MALE_SPEAKER_NOT_USER_CLONE", "continuity_basis": "First release-clear E40 Ashuan binding; built-in zm_010 chosen for the canonical young, clear male timbre and must remain stable for later Ashuan speech."})
    base.atomic_json(RIGHTS, rights)
    generated["rights_evidence_sha256"] = base.sha(RIGHTS)
    base.atomic_json(RECEIPT, generated)


def rewrite_qa(path: Path, version: str) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update({"schema": f"qingshan.e40.u17.parallel.kokoro_exact_audio_machine_qa.{version}", "episode": "E40", "unit_id": "U17", "scene_id": "13-4", "dialogue_id": "E40-DIA-015", "speaker": "阿栓", "expected_text": TEXT, "selection_rule": "exact normalized ASR and short-line audio gates; establish release-clear Ashuan zm_010 identity; duration nearest canonical 1.0s"})
    base.atomic_json(path, payload)
    return 0 if payload.get("selected") else 2


def generate() -> int:
    bind_impl()
    result = impl.generate()
    if result != 0:
        return result
    rewrite_u17_receipts()
    print(json.dumps({"status": "PASS_ZERO_CREDIT_U17_CANDIDATES_GENERATED_QA_PENDING", "candidates": 3}, ensure_ascii=False))
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
