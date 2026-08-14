#!/usr/bin/env python3
"""Local exact-ASR and audio QA for the E40 U03 Yunfei line."""

from __future__ import annotations

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
GEN = ROOT / "workflow/tasks/E40_U03_DIA003_KOKORO_RIGHTS_CLEARED_EXACT_AUDIO_GENERATION_20260814.json"
OUT = ROOT / "qa/e40_production_20260814/u03_v1_kokoro_rights_cleared_exact_audio_v1/E40_U03_DIA003_EXACT_AUDIO_MACHINE_QA_V1.json"
ADMIT = ROOT / "workflow/releases/E40_U03_DIA003_RIGHTS_CLEARED_EXACT_AUDIO_ADMISSION_20260814.json"
MODEL = Path("/Users/rogerwu/.cache/faster-whisper/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
TEXT = "换，还是不换？"
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")


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


def main() -> int:
    generation = json.loads(GEN.read_text(encoding="utf-8"))
    wav = ROOT / generation["output"]
    if generation.get("status") != "PASS_ZERO_CREDIT_GENERATED_QA_PENDING" or sha256(wav) != generation.get("output_sha256"):
        raise SystemExit("FAIL_CLOSED_GENERATION_BINDING")
    model = WhisperModel(str(MODEL), device="cpu", compute_type="int8", local_files_only=True)
    segments, _ = model.transcribe(str(wav), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话古装短剧对白。", hotwords=TEXT)
    transcript = "".join(segment.text.strip() for segment in segments)
    norm = lambda value: "".join(HAN.findall(value)).lower()
    similarity = difflib.SequenceMatcher(None, norm(TEXT), norm(transcript)).ratio()
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(wav)], capture_output=True, text=True, check=True)
    duration = float(probe.stdout.strip())
    loud = subprocess.run(["ffmpeg", "-nostats", "-i", str(wav), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True, check=True)
    summary = loud.stderr.rsplit("Summary:", 1)[-1]
    lufs_match = re.search(r"I:\s+(-?[0-9.]+) LUFS", summary)
    peak_match = re.search(r"Peak:\s+(-?[0-9.]+) dBFS", summary)
    lufs = float(lufs_match.group(1)) if lufs_match else None
    peak = float(peak_match.group(1)) if peak_match else None
    failures = []
    if similarity != 1.0: failures.append("ASR_EXACT_TEXT_FAIL")
    if not 1.0 <= duration <= 3.0: failures.append("DURATION_FAIL")
    if lufs is None or not -20 <= lufs <= -16: failures.append("LOUDNESS_FAIL")
    if peak is None or peak > -1: failures.append("TRUE_PEAK_FAIL")
    status = "PASS_EXACT_AUDIO_ADMITTED" if not failures else "FAIL_AUDIO_NOT_ADMITTED"
    payload = {
        "schema": "qingshan.e40.u03.dia003.exact_audio_machine_qa.v1", "status": status,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "exact_text": TEXT, "asr_transcript": transcript, "asr_similarity": round(similarity, 4),
        "duration_seconds": duration, "integrated_lufs": lufs, "true_peak_dbfs": peak,
        "voice": generation["voice"], "output": generation["output"], "output_sha256": generation["output_sha256"],
        "rights_evidence": generation["rights_evidence"], "rights_evidence_sha256": generation["rights_evidence_sha256"],
        "provider_post_count": 0, "credits": 0, "failures": failures,
    }
    atomic_json(OUT, payload)
    if not failures:
        atomic_json(ADMIT, {
            "schema": "qingshan.e40.u03.dia003.exact_audio_admission.v1",
            "status": "PASS_ADMITTED_FOR_U03_AGENTCUT_ASSEMBLY",
            "created_at": payload["created_at"], "audio": payload["output"], "audio_sha256": payload["output_sha256"],
            "qa": str(OUT.relative_to(ROOT)), "qa_sha256": sha256(OUT), "exact_text": TEXT,
            "next_action": "Bind this audio to the U03 silent visual once a visual candidate passes its own admission gate.",
        })
    print(json.dumps({"status": status, "transcript": transcript, "similarity": round(similarity, 4), "duration": duration, "lufs": lufs, "peak": peak, "failures": failures}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
