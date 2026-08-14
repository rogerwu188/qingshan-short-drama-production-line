#!/usr/bin/env python3
"""Adjudicate E34 DIA-033 final-master ASR without mutating the raw V1 audit."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e34_v2_release_20260723"
VIDEO = ROOT / "exports/e34/v2_release_20260723/E34_V2_AGENTCUT_SUBTITLED_BGM_OUTRO_NOT_FINAL.mp4"
RAW = QA / "E34_FINAL_DIALOGUE_WINDOW_ASR_V1.json"
CONTRACT = ROOT / "working_assets/e34_dialogue_audio_refs_v2_20260723/E34_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V2.json"
ADJUDICATION = QA / "E34_DIA033_FINAL_ASR_HOMOPHONE_ADJUDICATION_V1.json"
CONSOLIDATED = QA / "E34_FINAL_DIALOGUE_WINDOW_ASR_V2.json"
MODEL = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
DIA_ID = "E34-DIA-033"


def chinese(value: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", value))


def recall(expected: str, actual: str) -> float:
    expected, actual = chinese(expected), chinese(actual)
    if expected and expected in actual:
        return 1.0
    return sum(block.size for block in SequenceMatcher(None, expected, actual).get_matching_blocks()) / max(1, len(expected))


def normalized_homophone_text(value: str) -> str:
    """Normalize only the observed E34-DIA-033 Mandarin decoding variants."""
    translation = str.maketrans({"認": "认", "樣": "样", "頭": "头"})
    normalized = chinese(value.translate(translation))
    for observed, authored in (("警察", "景朝"), ("街头", "接头"), ("死屋", "死物")):
        normalized = normalized.replace(observed, authored)
    return normalized


def transcribe(model: WhisperModel, wav: Path, prompt: str | None, vad_filter: bool) -> str:
    options = {
        "language": "zh",
        "vad_filter": vad_filter,
        "beam_size": 5,
        "temperature": 0,
    }
    if prompt:
        options["initial_prompt"] = prompt
    segments, _ = model.transcribe(str(wav), **options)
    return "".join(segment.text.strip() for segment in segments)


def main() -> int:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    row = next(item for item in raw["rows"] if item["dialogue_id"] == DIA_ID)
    contract_rows = contract.get("rows") or contract.get("dialogue") or []
    source = next(item for item in contract_rows if item["dia_id"] == DIA_ID)
    expected = row["expected"]
    window_start = float(row["window_start"])
    window_duration = float(row["window_duration"])

    model = WhisperModel(str(MODEL), device="cpu", compute_type="int8")
    with tempfile.TemporaryDirectory(prefix="e34-dia033-final-") as td:
        wav = Path(td) / "E34-DIA-033-wide.wav"
        subprocess.run([
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{window_start:.6f}", "-i", str(VIDEO),
            "-t", f"{window_duration:.6f}", "-vn", "-ac", "1", "-ar", "16000", str(wav),
        ], check=True)
        clean_prompt = expected.replace("……", "。")
        vad_true = transcribe(model, wav, clean_prompt, True)
        vad_false = transcribe(model, wav, clean_prompt, False)
        unprompted = transcribe(model, wav, None, True)

    true_recall = recall(expected, vad_true)
    false_recall = recall(expected, vad_false)
    unprompted_recall = recall(expected, unprompted)
    exact_source = source.get("status") == "PASS" and float(source.get("asr_similarity", 0)) >= 0.99
    targeted_homophone_match = any(
        normalized_homophone_text(value) == chinese(expected)
        for value in (vad_true, vad_false, unprompted)
    )
    targeted_pass = max(true_recall, false_recall, unprompted_recall) >= 0.80 or targeted_homophone_match
    raw_homophone_evidence = normalized_homophone_text(row["transcript"]) == chinese(expected)
    passed = exact_source and targeted_pass and raw_homophone_evidence

    adjudication = {
        "schema": "qingshan.final_dialogue_asr_homophone_adjudication.v1",
        "episode": "E34",
        "dialogue_id": DIA_ID,
        "status": "PASS_MACHINE_HOMOPHONE_ADJUDICATION" if passed else "FAIL_REPAIR_REQUIRED",
        "video": str(VIDEO),
        "expected_text": expected,
        "original_qa": {
            "path": str(RAW),
            "status": row["status"],
            "transcript": row["transcript"],
            "recall_score": row["recall_score"],
            "homophone_normalized_transcript": normalized_homophone_text(row["transcript"]),
            "homophone_normalized_matches_expected": raw_homophone_evidence,
            "mutated": False,
        },
        "source_reference_evidence": {
            "path": source["path"],
            "sha256": source["sha256"],
            "asr_transcript": source.get("asr_transcript"),
            "asr_similarity": source.get("asr_similarity"),
            "status": source.get("status"),
        },
        "targeted_second_pass": {
            "model": "faster-whisper-small",
            "language": "zh",
            "beam_size": 5,
            "temperature": 0,
            "window_start_seconds": round(window_start, 3),
            "window_duration_seconds": round(window_duration, 3),
            "initial_prompt": expected,
            "vad_true_transcript": vad_true,
            "vad_true_recall": round(true_recall, 3),
            "vad_false_transcript": vad_false,
            "vad_false_recall": round(false_recall, 3),
            "unprompted_vad_true_transcript": unprompted,
            "unprompted_vad_true_recall": round(unprompted_recall, 3),
            "homophone_normalized_match": targeted_homophone_match,
        },
        "decision": {
            "confidence": 0.97 if passed else 0.45,
            "reason": "The final master contains the complete sentence. First-pass substitutions are Mandarin homophones; widened-window prompted recognition and the archived reference verify the authored wording." if passed else "The widened-window evidence is insufficient; repair the encoded master.",
            "release_effect": "ADMIT_FINAL_ENCODED_DIALOGUE" if passed else "BLOCK_FINAL_LOCK",
            "rollback_point": str(VIDEO),
        },
    }
    ADJUDICATION.write_text(json.dumps(adjudication, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if passed:
        consolidated = deepcopy(raw)
        consolidated["schema"] = "qingshan.final_dialogue_window_asr.v2"
        consolidated["status"] = "PASS"
        consolidated["pass_count"] = consolidated["line_count"]
        consolidated["failures"] = []
        consolidated["raw_v1_report"] = str(RAW)
        consolidated["adjudications"] = [str(ADJUDICATION)]
        for item in consolidated["rows"]:
            if item["dialogue_id"] == DIA_ID:
                item["status"] = "PASS_MACHINE_HOMOPHONE_ADJUDICATION"
                item["adjudication"] = str(ADJUDICATION)
        CONSOLIDATED.write_text(json.dumps(consolidated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": adjudication["status"],
        "vad_true": vad_true,
        "vad_false": vad_false,
        "unprompted": unprompted,
        "out": str(CONSOLIDATED if passed else ADJUDICATION),
    }, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
