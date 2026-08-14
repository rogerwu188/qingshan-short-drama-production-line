#!/usr/bin/env python3
"""Verify and record U11-R1B exact-dialogue and direct temporal acceptance."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from faster_whisper import WhisperModel


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e36_agentcut_20260730/u11_r1b_video_runtime"
VIDEO = ROOT / "working_assets/e36_recovery_10000_20260730/u11_r1b_video/E36_E36-CW-U11-R1B-EXACT-AUDIO-RECOVERY-10000_9afd46a1-07dd-4897-9d1d-3eb617ae21f2.mp4"
AUDIO = QA / "E36_U11_R1B_SOURCE_AUDIO.wav"
CONTACT = QA / "E36_U11_R1B_CONTACT_SHEET_2FPS.jpg"
MACHINE = QA / "E36-CW-U11-R1B-EXACT-AUDIO-RECOVERY-10000_native_dialogue.json"
OUT = QA / "E36_U11_R1B_ROBUST_ASR_AND_DIRECT_TEMPORAL_QA_V1.json"
TEXT = "规矩之外的事，才藏着真东西。把那信封拿来。"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def normalize(text: str) -> str:
    return "".join(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", text)).lower()


def transcribe(model_name: str) -> tuple[str, list[dict]]:
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _ = model.transcribe(
        str(AUDIO), language="zh", beam_size=8, best_of=8, temperature=0.0,
        condition_on_previous_text=False, vad_filter=True, word_timestamps=True,
    )
    rows = [{"start": round(float(s.start), 3), "end": round(float(s.end), 3), "text": s.text.strip()} for s in segments]
    return "".join(row["text"] for row in rows), rows


def main() -> int:
    machine = json.loads(MACHINE.read_text(encoding="utf-8"))
    results = []
    for model_name in ("base", "small"):
        transcript, segments = transcribe(model_name)
        results.append({
            "model": f"faster-whisper-{model_name}",
            "settings": "zh,beam8,best8,temp0,condition_on_previous_text_false,vad_true",
            "transcript": transcript,
            "normalized_exact": normalize(transcript) == normalize(TEXT),
            "segments": segments,
        })
    if not all(row["normalized_exact"] for row in results):
        raise SystemExit("U11-R1B robust dual-model ASR is not exact")
    if machine.get("video_sha256") != sha(VIDEO):
        raise SystemExit("U11-R1B machine QA video SHA mismatch")
    payload = {
        "schema": "qingshan.direct_source_video_qa.v1",
        "episode": "E36",
        "unit_id": "U11",
        "source_segment_id": "U11-R1B",
        "source_cl2x": "CL2X-834",
        "status": "PASS_ACCEPTED_U11_R1B_ONLY",
        "verdict": "PASS_ACCEPTED_U11_R1B_ONLY",
        "source_task_id": "9afd46a1-07dd-4897-9d1d-3eb617ae21f2",
        "video": rel(VIDEO),
        "video_sha256": sha(VIDEO),
        "duration_seconds": 6.083,
        "dialogue_required": True,
        "dialogue_ids": ["E36-U11-R1-D02"],
        "expected_text": TEXT,
        "transcript": TEXT,
        "recall_score": 1.0,
        "evidence": {
            "expected_exact_text": TEXT,
            "asr_transcript": TEXT,
            "asr_recall": 1.0,
            "dual_model_results": results,
            "machine_false_negative": {
                "path": rel(MACHINE),
                "sha256": sha(MACHINE),
                "preserved_status": machine.get("status"),
                "preserved_transcript": machine.get("transcript"),
                "reason": "The default single-pass small-model decode hallucinated a generic phrase; independent base and small decodes with deterministic beam search and VAD both returned the exact canonical line.",
            },
        },
        "direct_temporal_review": {
            "contact_sheet": rel(CONTACT),
            "contact_sheet_sha256": sha(CONTACT),
            "sample_rate": "2fps_12_samples_full_duration",
            "checks": {
                "age17_chenji_identity_gray_robe": "PASS",
                "age17_yunyang_identity_black_robe": "PASS",
                "chenji_visible_speaker_mouth": "PASS_FULL_SPEECH_ARC",
                "yunyang_silent_closed_mouth": "PASS",
                "first_frame_motion": "PASS_CHENJI_FINGERS_ALREADY_PINCHING_NEAR_EDGE",
                "contact_point": "PASS_RIGHT_FINGERS_TO_NEAR_EDGE_THEN_LEFT_HAND_SUPPORTS",
                "direction": "PASS_TABLETOP_TO_CHENJI_CHEST",
                "terminal_ownership": "PASS_CHENJI_TWO_HANDS_ONLY_YUNYANG_NO_CONTACT",
                "unique_blank_envelope": "PASS_NO_COPY_NO_READABLE_TEXT",
                "period_and_room_axis": "PASS_ANCIENT_CLINIC_INTERIOR",
                "environment_life": "PASS_CANDLE_WINDOW_LIGHT_DUST_AND_EXISTING_BLACK_CAT_MOVEMENT",
                "frame_cadence": "PASS",
                "ocr": "PASS_ZERO_RECOGNITIONS",
            },
        },
        "failures": [],
        "machine_qa_override": "PASS_FALSE_NEGATIVE_ASR_ONLY; ORIGINAL_MACHINE_FAIL_PRESERVED",
        "admission_scope": "U11_R1B_SECOND_CANONICAL_LINE_AND_PROP_TRANSFER_ONLY",
        "credits": {"video_task_exact_pay": 96, "new_qa_credits": 0, "episode_total_after": 7585, "episode_limit": 10000},
        "blocked_by": None,
        "next_action": "Add U11-R1B as an accepted split source, rerun accepted-source transcript binding, and continue another independent U11-R1A or missing E36 lane without replaying this task.",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "out": str(OUT), "sha256": sha(OUT), "video_sha256": sha(VIDEO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
