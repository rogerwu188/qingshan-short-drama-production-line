#!/usr/bin/env python3
"""Fail-closed unconditioned ASR audit for the U02-R1C source dialogue audio."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / "working_assets/e36_dialogue_audio_refs_20260730/u02_r1/E36-U02-R1-D03.wav"
PRIOR_QA = ROOT / "qa/e36_agentcut_20260730/u02_r1_video_runtime/E36-U02-R1-D03_EXACT_DIALOGUE_AUDIO_QA_V1.json"
VIDEO_QA = ROOT / "qa/e36_agentcut_20260730/u02_r1c_video_runtime/E36_U02_R1C_ROBUST_ASR_AND_DIRECT_TEMPORAL_QA_V1.json"
OUT = ROOT / "qa/e36_agentcut_20260730/u02_r1c_video_runtime/E36_U02_R1C_SOURCE_AUDIO_ROBUST_ASR_AUDIT_V1.json"
TEXT = "伤一个，咱们就是劫法场的钦犯。人，只能从刀下换走。"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def normalize(text: str) -> str:
    return "".join(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", text)).lower()


def transcribe(model: WhisperModel, model_name: str, beam_size: int, vad_filter: bool) -> dict:
    segments, _ = model.transcribe(
        str(AUDIO),
        language="zh",
        beam_size=beam_size,
        best_of=max(beam_size, 1),
        temperature=0.0,
        condition_on_previous_text=False,
        vad_filter=vad_filter,
        word_timestamps=True,
    )
    rows = [
        {
            "start": round(float(segment.start), 3),
            "end": round(float(segment.end), 3),
            "text": segment.text.strip(),
        }
        for segment in segments
    ]
    transcript = "".join(row["text"] for row in rows)
    return {
        "model": f"faster-whisper-{model_name}",
        "beam_size": beam_size,
        "vad_filter": vad_filter,
        "temperature": 0.0,
        "condition_on_previous_text": False,
        "initial_prompt": None,
        "hotwords": None,
        "transcript": transcript,
        "normalized_transcript": normalize(transcript),
        "normalized_exact": normalize(transcript) == normalize(TEXT),
        "segments": rows,
    }


def main() -> int:
    if not AUDIO.is_file() or not PRIOR_QA.is_file() or not VIDEO_QA.is_file():
        raise SystemExit("required U02-R1C source evidence is missing")
    if sha(AUDIO) != "4143088107c56500f1c63675792d6ec05635fcbbf0fe250bdb1374f7e111ad0d":
        raise SystemExit("U02-R1C D03 source audio SHA drift")

    results = []
    for model_name in ("base", "small"):
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        for beam_size in (1, 5, 8):
            for vad_filter in (False, True):
                results.append(transcribe(model, model_name, beam_size, vad_filter))

    exact_count = sum(row["normalized_exact"] for row in results)
    transcripts_by_model = {
        model_name: sorted({row["transcript"] for row in results if row["model"].endswith(model_name)})
        for model_name in ("base", "small")
    }
    source_is_robust = exact_count == len(results)
    status = "PASS_SOURCE_AUDIO_ROBUST_EXACT" if source_is_robust else "FAIL_SOURCE_AUDIO_PHONETIC_AMBIGUITY_PRESERVED"
    payload = {
        "schema": "qingshan.dialogue_source_audio_robust_asr_audit.v1",
        "episode": "E36",
        "unit_id": "U02-R1C",
        "source_cl2x": "CL2X-837",
        "status": status,
        "verdict": status,
        "expected_text": TEXT,
        "source_audio": {
            "path": rel(AUDIO),
            "sha256": sha(AUDIO),
            "prior_contextual_qa": rel(PRIOR_QA),
            "prior_contextual_qa_sha256": sha(PRIOR_QA),
        },
        "method": {
            "models": ["faster-whisper-base", "faster-whisper-small"],
            "beam_sizes": [1, 5, 8],
            "vad_filter_values": [False, True],
            "temperature": 0.0,
            "condition_on_previous_text": False,
            "expected_text_prompting": False,
            "decode_count": len(results),
        },
        "results": results,
        "summary": {
            "exact_count": exact_count,
            "decode_count": len(results),
            "transcripts_by_model": transcripts_by_model,
            "source_audio_eligible_for_unchanged_video_reuse": source_is_robust,
            "source_audio_eligible_for_changed_input_video_repair": source_is_robust,
        },
        "prior_video_fail_evidence": {
            "path": rel(VIDEO_QA),
            "sha256": sha(VIDEO_QA),
        },
        "admission": False,
        "credits": {
            "new_credits": 0,
            "episode_total_after": 7713,
            "episode_limit": 10000,
        },
        "blocked_by": None,
        "next_action": (
            "Do not spend the sole U02-R1C changed-input video repair on this unchanged source audio. "
            "Create separately synthesized, independently unconditioned-ASR-exact pronunciation references for the ambiguous clauses before any changed video request; "
            "otherwise move to another independent missing-line lane."
            if not source_is_robust
            else "Build one materially changed U02-R1C video repair around this independently verified exact source audio."
        ),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "out": str(OUT), "sha256": sha(OUT), "exact_count": exact_count, "decode_count": len(results)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
