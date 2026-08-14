#!/usr/bin/env python3
"""Run local ASR/audio QA and select one Kokoro voice for E40 U02."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "workflow/tasks/E40_U02_V12_KOKORO_RIGHTS_CLEARED_CANDIDATE_GENERATION_20260814.json"
RIGHTS = ROOT / "qa/e40_preproduction_20260814/u02_v12_kokoro_rights_clearance_v1/E40_U02_V12_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
OUT = ROOT / "qa/e40_production_20260814/u02_v12_kokoro_rights_cleared_audio_candidates_v1/E40_U02_V12_KOKORO_CANDIDATE_MACHINE_QA_V1.json"
MODEL = Path("/Users/rogerwu/.cache/faster-whisper/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")
VOICE_ORDER = ("zf_001", "zf_021", "zf_083")
TARGETS = {
    "E40-DIA-001": "阿栓，在本宫手上。",
    "E40-DIA-002": "拿他，换景朝一个接头人。",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def norm(text: str) -> str:
    return "".join(HAN.findall(text)).lower()


def metrics(path: Path) -> dict:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,sample_rate,channels", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    loud = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(path), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, check=True,
    )
    summary = loud.stderr.rsplit("Summary:", 1)[-1]
    integrated = re.search(r"I:\s+(-?[0-9.]+) LUFS", summary)
    peak = re.search(r"Peak:\s+(-?[0-9.]+) dBFS", summary)
    data = json.loads(probe.stdout)
    return {
        "duration_seconds": float(data["format"]["duration"]),
        "integrated_lufs": float(integrated.group(1)) if integrated else None,
        "true_peak_dbfs": float(peak.group(1)) if peak else None,
        "probe": data,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generation", type=Path, default=GEN)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    generation_path = args.generation if args.generation.is_absolute() else ROOT / args.generation
    out_path = args.out if args.out.is_absolute() else ROOT / args.out
    generation = json.loads(generation_path.read_text(encoding="utf-8"))
    rights = json.loads(RIGHTS.read_text(encoding="utf-8"))
    if generation.get("status") != "PASS_ZERO_CREDIT_CANDIDATES_GENERATED_QA_PENDING":
        raise SystemExit("FAIL_CLOSED_GENERATION_RECEIPT_STATUS")
    if rights.get("status") != "PASS_RELEASE_CLEAR_APACHE_2_0_BUILT_IN_VOICES" or rights.get("releaseBlocked") is not False:
        raise SystemExit("FAIL_CLOSED_RIGHTS_GATE")
    if not MODEL.joinpath("model.bin").is_file():
        raise SystemExit("FAIL_CLOSED_LOCAL_ASR_MODEL_MISSING")

    asr = WhisperModel(str(MODEL), device="cpu", compute_type="int8", local_files_only=True)
    results = []
    for item in generation["outputs"]:
        path = ROOT / item["normalized_path"]
        if sha256(path) != item["normalized_sha256"]:
            raise SystemExit(f"FAIL_CLOSED_AUDIO_SHA_MISMATCH:{path}")
        segments, _ = asr.transcribe(
            str(path), language="zh", vad_filter=True, beam_size=5,
            initial_prompt="以下是简体中文普通话古装短剧对白。",
            hotwords=item["exact_text"],
        )
        transcript = "".join(segment.text.strip() for segment in segments)
        similarity = difflib.SequenceMatcher(None, norm(item["exact_text"]), norm(transcript)).ratio()
        audio = metrics(path)
        failures = []
        if similarity != 1.0:
            failures.append("ASR_NORMALIZED_EXACT_TEXT_SIMILARITY_NOT_1P0")
        if audio["integrated_lufs"] is None or not -20.0 <= audio["integrated_lufs"] <= -16.0:
            failures.append("NORMALIZED_LOUDNESS_OUTSIDE_MINUS20_TO_MINUS16_LUFS")
        if audio["true_peak_dbfs"] is None or audio["true_peak_dbfs"] > -1.0:
            failures.append("TRUE_PEAK_ABOVE_MINUS1_DBFS_OR_UNKNOWN")
        results.append({**item, "asr_transcript": transcript, "asr_similarity": round(similarity, 4), "audio_metrics": audio, "failures": failures})

    voice_summaries = []
    for voice in VOICE_ORDER:
        pair = [item for item in results if item["voice"] == voice]
        total = sum(item["audio_metrics"]["duration_seconds"] for item in pair) + 0.12
        exact_count = sum(item["asr_similarity"] == 1.0 for item in pair)
        failures = [failure for item in pair for failure in item["failures"]]
        if total > 3.88:
            failures.append("PAIR_RUNTIME_EXCEEDS_3P88_SECONDS_FOR_FOUR_SECOND_PICTURE")
        voice_summaries.append({
            "voice": voice,
            "exact_asr_count": exact_count,
            "pair_duration_with_gap_seconds": round(total, 3),
            "failures": failures,
            "status": "PASS" if not failures and exact_count == 2 else "FAIL",
        })

    passing = [item for item in voice_summaries if item["status"] == "PASS"]
    selected = passing[0]["voice"] if passing else None
    status = "PASS_SELECTED_RIGHTS_CLEARED_VOICE" if selected else "FAIL_RUNTIME_OR_MACHINE_QA_REPAIR_REQUIRED"
    atomic_json(out_path, {
        "schema": "qingshan.e40.u02.kokoro_candidate_machine_qa.v1",
        "status": status,
        "created_at": utc_now(),
        "provider_post_count": 0,
        "credits": 0,
        "rights_evidence": str(RIGHTS.relative_to(ROOT)),
        "rights_evidence_sha256": sha256(RIGHTS),
        "candidates": results,
        "voice_summaries": voice_summaries,
        "selected_voice": selected,
        "generation_receipt": str(generation_path.relative_to(ROOT)),
        "generation_receipt_sha256": sha256(generation_path),
        "selection_policy": "Require exact normalized ASR for both lines, loudness and peak pass, and total spoken runtime plus 120ms gap <=3.88s; tie-break by official sample voice then stable candidate order.",
    })
    print(json.dumps({"status": status, "selected_voice": selected, "voice_summaries": voice_summaries}, ensure_ascii=False))
    return 0 if selected else 2


if __name__ == "__main__":
    raise SystemExit(main())
