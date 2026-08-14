#!/usr/bin/env python3
"""Reaudit all pre-OpenCC E36 source failures with one shared model load."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from faster_whisper import WhisperModel
from opencc import OpenCC


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CL2X = "CL2X-842"
T2S = OpenCC("t2s")
V1_PATHS = [
    "qa/e36_agentcut_20260730/u14_r1_video_runtime/E36-U14-R1-D01_UNCONDITIONED_ASR_V1.json",
    "qa/e36_agentcut_20260730/u14_r2_video_runtime/E36-U14-R2-D01_UNCONDITIONED_ASR_V1.json",
    "qa/e36_agentcut_20260730/u14_r4_video_runtime/E36-U14-R4-D01_UNCONDITIONED_ASR_V1.json",
    "qa/e36_agentcut_20260730/u14_r5_video_runtime/E36-U14-R5-D02_UNCONDITIONED_ASR_V1.json",
    "qa/e36_agentcut_20260730/u02_r1_video_runtime/E36-U02-R1-D02_UNCONDITIONED_ASR_V1.json",
    "qa/e36_agentcut_20260730/u02_r1c_video_runtime/E36-U02-R1C-D03A-PRONUNCIATION_UNCONDITIONED_ASR_V1.json",
    "qa/e36_agentcut_20260730/u11_r1_video_runtime/E36-U11-R1-D01_UNCONDITIONED_ASR_V1.json",
]
SUMMARY_PATH = ROOT / (
    "qa/e36_agentcut_20260730/E36_PREFIT_OPENCC_T2S_REVERSE_GOODHART_REAUDIT_V1.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str) -> str:
    return "".join(re.findall(r"[A-Za-z0-9\u3400-\u9fff]", T2S.convert(text))).lower()


def v2_path(v1_path: Path) -> Path:
    return v1_path.with_name(v1_path.name.replace("_V1.json", "_V2.json"))


def main() -> None:
    cases = []
    for relative in V1_PATHS:
        path = ROOT / relative
        old = json.loads(path.read_text())
        cases.append({
            "v1_path": path,
            "v1": old,
            "audio_path": ROOT / old["audio"]["path"],
            "expected": old["expected_text"],
            "results": [],
        })

    for model_name in ("base", "small"):
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        for case in cases:
            for beam_size in (1, 5, 8):
                for vad_filter in (False, True):
                    segments, _ = model.transcribe(
                        str(case["audio_path"]),
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
                    case["results"].append({
                        "model": f"faster-whisper-{model_name}",
                        "beam_size": beam_size,
                        "vad_filter": vad_filter,
                        "transcript": transcript,
                        "normalized_exact": normalize(transcript) == normalize(case["expected"]),
                        "segments": rows,
                    })

    summary_cases = []
    for case in cases:
        exact_count = sum(row["normalized_exact"] for row in case["results"])
        status = (
            "PASS_ROBUST_EXACT_12_OF_12"
            if exact_count == 12
            else "FAIL_ROBUST_NOT_EXACT_PRESERVED"
        )
        out = v2_path(case["v1_path"])
        payload = {
            "schema": "qingshan.dialogue_audio_unconditioned_asr.v1",
            "episode": "E36",
            "unit_id": case["v1"].get("unit_id"),
            "dia_id": case["v1"].get("dia_id"),
            "source_cl2x": SOURCE_CL2X,
            "status": status,
            "verdict": status,
            "expected_text": case["expected"],
            "audio": {
                "path": str(case["audio_path"].relative_to(ROOT)),
                "sha256": sha256(case["audio_path"]),
            },
            "settings": {
                "models": ["base", "small"],
                "beam_sizes": [1, 5, 8],
                "vad_filter_values": [False, True],
                "temperature": 0.0,
                "condition_on_previous_text": False,
                "initial_prompt": None,
                "hotwords": None,
                "han_script_normalization": "OpenCC t2s",
            },
            "results": case["results"],
            "summary": {
                "exact_count": exact_count,
                "decode_count": 12,
                "unique_transcripts": sorted({row["transcript"] for row in case["results"]}),
                "eligible_as_exact_pronunciation_reference": exact_count == 12,
            },
            "credits": {"new_qa_credits": 0},
            "failures": [] if exact_count == 12 else ["UNCONDITIONED_ASR_NOT_EXACT_12_OF_12"],
            "reaudit": {
                "reason": "CL2X-842 reverse-Goodhart check after OpenCC t2s defect fix",
                "preserved_v1_path": str(case["v1_path"].relative_to(ROOT)),
                "preserved_v1_sha256": sha256(case["v1_path"]),
                "preserved_v1_exact_count": case["v1"]["summary"]["exact_count"],
            },
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        summary_cases.append({
            "unit_id": payload["unit_id"],
            "dia_id": payload["dia_id"],
            "v1_path": payload["reaudit"]["preserved_v1_path"],
            "v1_sha256": payload["reaudit"]["preserved_v1_sha256"],
            "v1_exact_count": payload["reaudit"]["preserved_v1_exact_count"],
            "v2_path": str(out.relative_to(ROOT)),
            "v2_sha256": sha256(out),
            "v2_exact_count": exact_count,
            "status": status,
            "flipped_to_pass": exact_count == 12,
        })

    flipped = [row for row in summary_cases if row["flipped_to_pass"]]
    report = {
        "schema": "qingshan.e36.prefit_opencc_t2s_reverse_goodhart_reaudit.v1",
        "episode": "E36",
        "source_cl2x": SOURCE_CL2X,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASS_COMPLETE_7_OF_7",
        "case_count": len(summary_cases),
        "cases": summary_cases,
        "summary": {
            "reaudited": len(summary_cases),
            "survived_fail": len(summary_cases) - len(flipped),
            "flipped_to_pass": len(flipped),
            "flipped_units": [row["unit_id"] for row in flipped],
            "new_qa_credits": 0,
        },
        "gate_results": {
            "all_seven_executed": len(summary_cases) == 7,
            "all_v1_preserved": all((ROOT / row["v1_path"]).is_file() for row in summary_cases),
            "opencc_t2s_applied": True,
            "remote_generation": "PASS_NONE",
            "credits": 0,
        },
        "next_action": (
            "Retain each surviving phonetic FAIL and any pronunciation_hard classification. "
            "If a case flips to exact12/12, restore that source to the next video-readiness review "
            "without retroactively deleting the preserved V1 tool-defect result."
        ),
    }
    SUMMARY_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
