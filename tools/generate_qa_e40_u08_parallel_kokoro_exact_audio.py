#!/usr/bin/env python3
"""Generate and machine-QA release-clear local U08 DIA-007 audio candidates.

This is a thin, fail-closed U08 adapter over the already admitted U07 Kokoro
pipeline.  It changes only the dialogue, isolated output paths, schemas, and
the canonical 2.5-second selection target.  No provider API is contacted.
"""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
from pathlib import Path

import generate_qa_e40_u07_v2_kokoro_exact_audio as base


ROOT = Path(__file__).resolve().parents[1]
TEXT = "他不是证人，是饵。"
OUT = ROOT / "working_assets/e40_production_20260814/u08_parallel_kokoro_exact_audio_candidates_v1"
PRE_QA = ROOT / "qa/e40_preproduction_20260814/u08_parallel_kokoro_exact_audio_candidates_v1"
PROD_QA = ROOT / "qa/e40_production_20260814/u08_parallel_kokoro_exact_audio_candidates_v1"
RECEIPT = PRE_QA / "E40_U08_PARALLEL_KOKORO_CANDIDATE_GENERATION_RECEIPT_V1.json"
RIGHTS = PRE_QA / "E40_U08_PARALLEL_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
QA = PROD_QA / "E40_U08_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
V2_OUT = ROOT / "working_assets/e40_production_20260814/u08_parallel_kokoro_exact_audio_candidates_v2"
V2_QA = ROOT / "qa/e40_production_20260814/u08_parallel_kokoro_exact_audio_candidates_v2/E40_U08_PARALLEL_KOKORO_EXACT_AUDIO_MACHINE_QA_V2.json"
FAILURE_MEMORY = PROD_QA / "E40_U08_PARALLEL_KOKORO_V1_FAILURE_MEMORY_AND_V2_REPAIR_CONTRACT.json"


def configure() -> None:
    base.TEXT = TEXT
    base.OUT = OUT
    base.RECEIPT = RECEIPT
    base.RIGHTS = RIGHTS
    base.QA = QA


def rewrite_generation_receipts() -> None:
    payload = json.loads(RECEIPT.read_text(encoding="utf-8"))
    for item in payload["outputs"]:
        for key in ("source_path", "normalized_path"):
            old = ROOT / item[key]
            new = old.with_name(old.name.replace("E40-DIA006_", "E40-DIA007_"))
            if new.exists():
                raise SystemExit(f"FAIL_CLOSED_OUTPUT_COLLISION:{new}")
            old.rename(new)
            item[key] = str(new.relative_to(ROOT))
            item[key.replace("_path", "_sha256")] = base.sha(new)
    payload.update(
        {
            "schema": "qingshan.e40.u08.parallel.kokoro_candidate_generation.v1",
            "episode": "E40",
            "unit_id": "U08",
            "dialogue_id": "E40-DIA-007",
            "expected_text": TEXT,
            "mode": "LOCAL_KOKORO_ZERO_PROVIDER_POST",
        }
    )
    base.atomic_json(RECEIPT, payload)

    rights = json.loads(RIGHTS.read_text(encoding="utf-8"))
    rights.update(
        {
            "schema": "qingshan.e40.u08.parallel.kokoro_commercial_rights_evidence.v1",
            "episode": "E40",
            "unit_id": "U08",
            "dialogue_id": "E40-DIA-007",
            "continuity_basis": "Preserve admitted U05-U07 Chenji voice identity with built-in zm_009.",
        }
    )
    base.atomic_json(RIGHTS, rights)

    payload["rights_evidence_sha256"] = base.sha(RIGHTS)
    base.atomic_json(RECEIPT, payload)


def generate() -> int:
    configure()
    base.generate()
    rewrite_generation_receipts()
    print(
        json.dumps(
            {
                "status": "PASS_ZERO_CREDIT_U08_CANDIDATES_GENERATED_QA_PENDING",
                "dialogue_id": "E40-DIA-007",
                "candidates": len(json.loads(RECEIPT.read_text(encoding="utf-8"))["outputs"]),
            },
            ensure_ascii=False,
        )
    )
    return 0


def qa() -> int:
    configure()
    base.qa()
    payload = json.loads(QA.read_text(encoding="utf-8"))
    passes = [row for row in payload["candidates"] if row["status"] == "PASS_MACHINE"]
    passes.sort(key=lambda row: (abs(row["audio_metrics"]["duration_seconds"] - 2.5), row["speed"]))
    selected = passes[0] if passes else None
    payload.update(
        {
            "schema": "qingshan.e40.u08.parallel.kokoro_exact_audio_machine_qa.v1",
            "episode": "E40",
            "unit_id": "U08",
            "dialogue_id": "E40-DIA-007",
            "expected_text": TEXT,
            "status": "PASS_MACHINE_SELECTION" if selected else "FAIL_NO_CANDIDATE",
            "selected": selected,
            "selection_rule": "exact ASR and audio gates; preserve admitted zm_009 identity; duration nearest canonical 2.5s",
            "mode": "LOCAL_KOKORO_ZERO_PROVIDER_POST",
        }
    )
    base.atomic_json(QA, payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "passes": len(passes),
                "selected": selected and selected["normalized_path"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if selected else 2


def repair_qa() -> int:
    """Repair only the V1 mono loudness failure, then rerun full machine QA."""
    from faster_whisper import WhisperModel

    configure()
    if not RECEIPT.is_file() or not QA.is_file() or not FAILURE_MEMORY.is_file() or V2_QA.exists():
        raise SystemExit("FAIL_CLOSED_V1_RECEIPT_QA_MEMORY_MISSING_OR_V2_QA_COLLISION")
    v1 = json.loads(QA.read_text(encoding="utf-8"))
    if any(row["asr_similarity"] != 1.0 or row["failures"] != ["LOUDNESS_FAIL"] for row in v1["candidates"]):
        raise SystemExit("FAIL_CLOSED_V1_NOT_LOUDNESS_ONLY")
    V2_OUT.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(str(base.WHISPER), device="cpu", compute_type="int8", local_files_only=True)
    rows = []
    audio_filter = "volume=4.2dB,alimiter=limit=0.794328:attack=5:release=50:level=false"
    for item in v1["candidates"]:
        source = ROOT / item["normalized_path"]
        output = V2_OUT / source.name.replace("_normalized48k.wav", "_mono_compensated48k_v2a.wav")
        if output.exists():
            raise SystemExit(f"FAIL_CLOSED_V2_OUTPUT_COLLISION:{output}")
        subprocess.run(
            [
                base.FFMPEG,
                "-y",
                "-v",
                "error",
                "-i",
                str(source),
                "-af",
                audio_filter,
                "-ar",
                "48000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(output),
            ],
            check=True,
        )
        segments, _ = model.transcribe(
            str(output), language="zh", vad_filter=True, beam_size=5,
            initial_prompt="以下是简体中文普通话对白。", hotwords=TEXT
        )
        transcript = "".join(segment.text.strip() for segment in segments)
        similarity = difflib.SequenceMatcher(None, base.norm(TEXT), base.norm(transcript)).ratio()
        audio = base.metrics(output)
        failures = []
        if similarity != 1.0:
            failures.append("ASR_NOT_EXACT")
        if not 2.0 <= audio["duration_seconds"] <= 4.2:
            failures.append("DURATION_OUTSIDE_2P0_TO_4P2")
        if audio["integrated_lufs"] is None or not -19.5 <= audio["integrated_lufs"] <= -16.0:
            failures.append("LOUDNESS_FAIL")
        if audio["true_peak_dbfs"] is None or audio["true_peak_dbfs"] > -1.0:
            failures.append("TRUE_PEAK_FAIL")
        rows.append(
            {
                "voice": item["voice"],
                "speed": item["speed"],
                "v1_input_path": item["normalized_path"],
                "v1_input_sha256": item["normalized_sha256"],
                "normalized_path": str(output.relative_to(ROOT)),
                "normalized_sha256": base.sha(output),
                "voice_file_sha256": item["voice_file_sha256"],
                "asr_transcript": transcript,
                "asr_similarity": round(similarity, 4),
                "audio_metrics": audio,
                "status": "PASS_MACHINE" if not failures else "FAIL",
                "failures": failures,
            }
        )
    passes = [row for row in rows if row["status"] == "PASS_MACHINE"]
    passes.sort(key=lambda row: (abs(row["audio_metrics"]["duration_seconds"] - 2.5), row["speed"]))
    selected = passes[0] if passes else None
    payload = {
        "schema": "qingshan.e40.u08.parallel.kokoro_exact_audio_machine_qa.v2",
        "episode": "E40",
        "unit_id": "U08",
        "dialogue_id": "E40-DIA-007",
        "status": "PASS_MACHINE_SELECTION" if selected else "FAIL_NO_CANDIDATE",
        "created_at": base.now(),
        "expected_text": TEXT,
        "failure_memory": str(FAILURE_MEMORY.relative_to(ROOT)),
        "failure_memory_sha256": base.sha(FAILURE_MEMORY),
        "rights_evidence": str(RIGHTS.relative_to(ROOT)),
        "rights_evidence_sha256": base.sha(RIGHTS),
        "repair_processing_contract": audio_filter,
        "candidates": rows,
        "selected": selected,
        "selection_rule": "exact ASR and audio gates; preserve admitted zm_009 identity; duration nearest canonical 2.5s",
        "provider_posts": 0,
        "credits": 0,
    }
    base.atomic_json(V2_QA, payload)
    print(json.dumps({"status": payload["status"], "passes": len(passes), "selected": selected and selected["normalized_path"]}, ensure_ascii=False))
    return 0 if selected else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--generate", action="store_true")
    group.add_argument("--qa", action="store_true")
    group.add_argument("--repair-qa", action="store_true")
    args = parser.parse_args()
    if args.generate:
        return generate()
    if args.qa:
        return qa()
    return repair_qa()


if __name__ == "__main__":
    raise SystemExit(main())
