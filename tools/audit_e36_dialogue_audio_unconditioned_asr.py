#!/usr/bin/env python3
"""Audit one E36 dialogue reference with deterministic unconditioned ASR."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from faster_whisper import WhisperModel
from opencc import OpenCC


ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / os.environ["E36_ASR_AUDIO"]
EXPECTED = os.environ["E36_ASR_EXPECTED"]
OUT = ROOT / os.environ["E36_ASR_OUT"]
UNIT_ID = os.environ.get("E36_ASR_UNIT_ID", "UNKNOWN")
DIA_ID = os.environ.get("E36_ASR_DIA_ID", "UNKNOWN")
SOURCE_CL2X = os.environ.get("E36_ASR_SOURCE_CL2X", "CL2X-837")
MATCH_MODE = os.environ.get("E36_ASR_MATCH_MODE", "exact")
T2S = OpenCC("t2s")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def normalize(text: str) -> str:
    script_normalized = T2S.convert(text)
    return "".join(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", script_normalized)).lower()


def main() -> int:
    if not AUDIO.is_file():
        raise SystemExit(f"audio missing: {AUDIO}")
    results = []
    for model_name in ("base", "small"):
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        for beam_size in (1, 5, 8):
            for vad_filter in (False, True):
                segments, _ = model.transcribe(
                    str(AUDIO), language="zh", beam_size=beam_size,
                    best_of=max(beam_size, 1), temperature=0.0,
                    condition_on_previous_text=False, vad_filter=vad_filter,
                    word_timestamps=True,
                )
                rows = [
                    {"start": round(float(segment.start), 3), "end": round(float(segment.end), 3), "text": segment.text.strip()}
                    for segment in segments
                ]
                transcript = "".join(row["text"] for row in rows)
                normalized_transcript = normalize(transcript)
                normalized_expected = normalize(EXPECTED)
                matched = (
                    normalized_expected in normalized_transcript
                    if MATCH_MODE == "contains"
                    else normalized_transcript == normalized_expected
                )
                results.append({
                    "model": f"faster-whisper-{model_name}",
                    "beam_size": beam_size,
                    "vad_filter": vad_filter,
                    "transcript": transcript,
                    "normalized_exact": matched,
                    "segments": rows,
                })
    exact_count = sum(row["normalized_exact"] for row in results)
    status = "PASS_ROBUST_EXACT_12_OF_12" if exact_count == 12 else "FAIL_ROBUST_NOT_EXACT_PRESERVED"
    payload = {
        "schema": "qingshan.dialogue_audio_unconditioned_asr.v1",
        "episode": "E36",
        "unit_id": UNIT_ID,
        "dia_id": DIA_ID,
        "source_cl2x": SOURCE_CL2X,
        "status": status,
        "verdict": status,
        "expected_text": EXPECTED,
        "audio": {"path": rel(AUDIO), "sha256": sha(AUDIO)},
        "settings": {
            "models": ["base", "small"],
            "beam_sizes": [1, 5, 8],
            "vad_filter_values": [False, True],
            "temperature": 0.0,
            "condition_on_previous_text": False,
            "initial_prompt": None,
            "hotwords": None,
            "match_mode": MATCH_MODE,
            "han_script_normalization": "OpenCC t2s",
        },
        "results": results,
        "summary": {
            "exact_count": exact_count,
            "decode_count": 12,
            "unique_transcripts": sorted({row["transcript"] for row in results}),
            "eligible_as_exact_pronunciation_reference": exact_count == 12,
        },
        "credits": {"new_qa_credits": 0},
        "failures": [] if exact_count == 12 else ["UNCONDITIONED_ASR_NOT_EXACT_12_OF_12"],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "exact_count": exact_count, "out": str(OUT), "sha256": sha(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
