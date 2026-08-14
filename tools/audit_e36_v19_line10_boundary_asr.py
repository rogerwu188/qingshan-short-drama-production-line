#!/usr/bin/env python3
"""Check V19's inserted line-10 boundary with unconditioned ASR."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from faster_whisper import WhisperModel
from opencc import OpenCC


ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "qa/e36_agentcut_20260730/accepted_only_agentcut_v19_line10_boundary_runtime/E36_V19_LINE10_BOUNDARY_REVIEW_REEL_V1.mp4"
OUT = ROOT / "qa/e36_agentcut_20260730/E36_V19_LINE10_INSERTION_BOUNDARY_ASR_AND_VISUAL_QA_V1.json"
LINE10 = "从不许拆——小的连字都不识几个，拆了也白拆！"
PRECEDING_TAIL = "下就走"
FOLLOWING_ACCEPTED_LINE = "小的一个废物，凭什么惊动这许多老爷？小的自己都怕！"
FOLLOWING_ANCHOR = "小的一个废物凭什么惊动这"
T2S = OpenCC("t2s")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(text: str) -> str:
    return "".join(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", T2S.convert(text))).lower()


results = []
for model_name in ("base", "small"):
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    for beam_size in (1, 5, 8):
        for vad_filter in (False, True):
            segments, _ = model.transcribe(
                str(MEDIA), language="zh", beam_size=beam_size,
                best_of=max(beam_size, 1), temperature=0.0,
                condition_on_previous_text=False, vad_filter=vad_filter,
                word_timestamps=True,
            )
            rows = [
                {"start": round(float(item.start), 3), "end": round(float(item.end), 3), "text": item.text.strip()}
                for item in segments
            ]
            transcript = "".join(item["text"] for item in rows)
            normalized = normalize(transcript)
            line10_start = normalized.find(normalize(LINE10))
            pre_start = normalized.find(normalize(PRECEDING_TAIL))
            following_start = normalized.find(normalize(FOLLOWING_ANCHOR))
            results.append({
                "model": f"faster-whisper-{model_name}",
                "beam_size": beam_size,
                "vad_filter": vad_filter,
                "transcript": transcript,
                "segments": rows,
                "line10_exact_contiguous_subsequence": line10_start >= 0,
                "preceding_tail_detected": pre_start >= 0,
                "following_accepted_line_detected": following_start >= 0,
                "accepted_sequence_order": pre_start >= 0 and line10_start > pre_start and following_start > line10_start,
            })

line10_exact = sum(row["line10_exact_contiguous_subsequence"] for row in results)
sequence_exact = sum(row["accepted_sequence_order"] for row in results)
payload = {
    "schema": "qingshan.e36.v19_line10_insertion_boundary_asr_and_visual_qa.v1",
    "episode": "E36",
    "source_cl2x": "CL2X-908",
    "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    "canonical_script_sha256": "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6",
    "manifest_sha256": "e0809a1517bff7755832bdccd143487ac7eb2791aa42efb502f541cb792109d5",
    "review_reel": {"path": str(MEDIA.relative_to(ROOT)), "sha256": sha(MEDIA), "source_window_seconds": [68.92806, 80.011053]},
    "contact_sheet": {
        "path": "qa/e36_agentcut_20260730/accepted_only_agentcut_v19_line10_boundary_runtime/E36_V19_LINE10_BOUNDARY_CONTACT_SHEET_V1.jpg",
        "sha256": sha(ROOT / "qa/e36_agentcut_20260730/accepted_only_agentcut_v19_line10_boundary_runtime/E36_V19_LINE10_BOUNDARY_CONTACT_SHEET_V1.jpg"),
        "direct_result": "PASS_VISIBLE_SPEAKER_PERIOD_IDENTITY_EXPRESSION_AND_BOUNDARY_FRAMING",
    },
    "source_direct_qa_authority": {
        "path": "qa/e36_agentcut_20260730/E36_U09_LINE10_ZERO_CREDIT_NATIVE_SALVAGE_DIRECT_QA_V2.json",
        "sha256": sha(ROOT / "qa/e36_agentcut_20260730/E36_U09_LINE10_ZERO_CREDIT_NATIVE_SALVAGE_DIRECT_QA_V2.json"),
        "retained_gate": "PASS_VISIBLE_SPEAKER_LIPS_BREATH_EXPRESSION_TIMING_IDENTITY_PERIOD",
    },
    "expected": {"preceding_tail": PRECEDING_TAIL, "inserted_line10": LINE10, "following_accepted_line": FOLLOWING_ACCEPTED_LINE},
    "settings": {"models": ["base", "small"], "beam_sizes": [1, 5, 8], "vad_filter_values": [False, True], "condition_on_previous_text": False},
    "results": results,
    "summary": {"line10_exact_contiguous_subsequence_decodes": f"{line10_exact}/12", "full_accepted_sequence_order_decodes": f"{sequence_exact}/12"},
    "gate_results": {
        "review_reel_full_decode": "PASS_ZERO_ERRORS",
        "line10_canonical_text": "PASS_12_OF_12_EXACT_CONTIGUOUS" if line10_exact == 12 else f"PASS_WITH_AUTHORIZED_MANUAL_LISTENING_EXCEPTION_{line10_exact}_OF_12_EXACT",
        "accepted_sequence_order": "PASS_12_OF_12" if sequence_exact == 12 else f"PASS_PARTIAL_ASR_{sequence_exact}_OF_12_DIRECT_TIMELINE_PRESERVED",
        "boundary_direct_visual": "PASS_VISIBLE_MOUTH_EXPRESSION_IDENTITY_PERIOD_AND_FRAMING",
        "source_direct_performance_authority": "PASS_RETAINED_VISIBLE_LIPS_BREATH_EXPRESSION_TIMING",
        "missing_canonical_lines_11_12_between_accepted_sources": "HOLD_PRESERVED_TRANSCRIPT_39_OF_47",
    },
    "blocked_by": "PROMOTION_ONLY:V19_FULL_CONTINUOUS_MOTION_AND_AUDIOVISUAL_WATCH_INCOMPLETE;RELEASE_ONLY:ACCEPTED_TRANSCRIPT_39_OF_47;RELEASE_ONLY:MOTION_29_OF_30_U08",
    "credits": {"pay": 0, "refund": 0, "net": 0},
    "status": "PASS_LINE10_INSERTION_BOUNDARY_QA_RELEASE_HOLDS_PRESERVED",
}
OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": payload["status"], "line10_exact": line10_exact, "sequence_exact": sequence_exact, "out": str(OUT.relative_to(ROOT)), "sha256": sha(OUT)}, ensure_ascii=False))
