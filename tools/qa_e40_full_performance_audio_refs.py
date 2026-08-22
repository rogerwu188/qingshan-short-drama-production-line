#!/usr/bin/env python3
"""Exact-text ASR and technical QA for E40 Seedance dialogue references."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "workflow/claude_writer_agent/production/e40_remake_v1_20260817/full_performance_native_dialogue_v1/E40_FULL_PERFORMANCE_EXACT_DIALOGUE_AUDIO_REFERENCE_PLAN_V1.json"
EXECUTION = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/audio_refs_v1/E40_FULL_PERFORMANCE_AUDIO_REFERENCE_EXECUTION_V1.json"
OUT = ROOT / "qa/e40_remake_20260822/full_performance_native_dialogue_v1/audio_refs_v1/E40_FULL_PERFORMANCE_AUDIO_REFERENCE_ASR_QA_V1.json"
MODEL = Path("/Users/rogerwu/.cache/faster-whisper/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FFPROBE = "ffprobe"
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(value: str) -> str:
    return "".join(HAN.findall(value)).lower()


def main() -> int:
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    execution = json.loads(EXECUTION.read_text(encoding="utf-8"))
    intents = {row["audio_key"]: row for row in plan["items"]}
    completed = {row["audio_key"]: row for row in execution["items"]}
    model = WhisperModel(str(MODEL), device="cpu", compute_type="int8", local_files_only=True)
    rows = []
    for audio_key, intent in intents.items():
        result = completed[audio_key]
        wav = ROOT / result["wav"]
        probe = json.loads(subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration:stream=codec_name,sample_rate,channels", "-of", "json", str(wav)],
            capture_output=True, text=True, check=True,
        ).stdout)
        segments, _ = model.transcribe(
            str(wav), language="zh", vad_filter=True, beam_size=5,
            initial_prompt="以下是简体中文普通话对白。", hotwords=intent["text"],
        )
        transcript = "".join(segment.text.strip() for segment in segments)
        failures = []
        if norm(transcript) != norm(intent["text"]):
            failures.append("ASR_NORMALIZED_TEXT_NOT_EXACT")
        stream = (probe.get("streams") or [{}])[0]
        if stream.get("sample_rate") != "48000" or int(stream.get("channels") or 0) != 1:
            failures.append("NORMALIZED_AUDIO_NOT_MONO_48KHZ")
        rows.append({
            "audio_key": audio_key,
            "dialogue_id": intent["dialogue_id"],
            "speaker": intent["speaker"],
            "expected_text": intent["text"],
            "asr_transcript": transcript,
            "normalized_exact_match": not failures or "ASR_NORMALIZED_TEXT_NOT_EXACT" not in failures,
            "wav_path": result["wav"],
            "wav_sha256": sha(wav),
            "provider_audio_task_id": result["task_id"],
            "duration_seconds": float(probe["format"]["duration"]),
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
        })
    payload = {
        "schema": "qingshan.e40.full_performance_audio_reference_asr_qa.v1",
        "episode": "E40",
        "gate_id": "EXACT-DIALOGUE-AUDIO-MANIFEST-COVERAGE",
        "status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
        "pass_count": sum(row["status"] == "PASS" for row in rows),
        "item_count": len(rows),
        "rows": rows,
        "purpose": "SEEDANCE_INPUT_REFERENCE_ONLY_NOT_POST_DUB",
        "postproduction_replacement_forbidden": True,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "pass_count": payload["pass_count"], "item_count": payload["item_count"], "out": str(OUT.relative_to(ROOT)), "sha256": sha(OUT)}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
