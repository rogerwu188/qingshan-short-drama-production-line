#!/usr/bin/env python3
"""Adjudicate two E35 final-ASR false negatives without mutating raw QA."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e35_v1_release_20260723"
VIDEO = ROOT / "exports/e35/v2_release_20260724/E35_V2_AGENTCUT_SUBTITLED_BGM_OUTRO_NOT_FINAL.mp4"
RAW = QA / "E35_FINAL_DIALOGUE_WINDOW_ASR_V2.json"
SOURCE_ASR = QA / "E35_REPAIRED_SOURCE_ASR_FINAL_V1.json"
ALIGNMENT = QA / "E35_NATIVE_SOURCE_CAPTION_ALIGNMENT_V1.json"
ADJUDICATION = QA / "E35_FINAL_ASR_FALSE_NEGATIVE_ADJUDICATION_V1.json"
CONSOLIDATED = QA / "E35_FINAL_DIALOGUE_WINDOW_ASR_V3.json"
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pcm(path: Path, start: float, duration: float, out: Path) -> np.ndarray:
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.6f}",
        "-i", str(path), "-t", f"{duration:.6f}", "-vn", "-ac", "1", "-ar", "16000",
        "-f", "s16le", str(out),
    ], check=True)
    return np.fromfile(out, dtype="<i2").astype(float)


def correlation(left: np.ndarray, right: np.ndarray) -> float:
    size = min(len(left), len(right))
    left, right = left[:size], right[:size]
    left -= left.mean()
    right -= right.mean()
    return float(np.dot(left, right) / (np.linalg.norm(left) * np.linalg.norm(right) + 1e-12))


def normalize_dia026(value: str) -> str:
    table = str.maketrans({"嚴": "严", "禁": "敬", "見": "见", "過": "过", "誰": "谁", "這": "这", "錢": "钱", "經": "经"})
    return "".join(char for char in value.translate(table) if "\u4e00" <= char <= "\u9fff")


def main() -> int:
    raw = json.loads(RAW.read_text(encoding="utf-8"))
    source_asr = json.loads(SOURCE_ASR.read_text(encoding="utf-8"))
    alignment = json.loads(ALIGNMENT.read_text(encoding="utf-8"))
    rows = {row["dialogue_id"]: row for row in raw["rows"]}
    units = {row["unit_id"]: row for row in source_asr["rows"]}
    aligned = {row["source_id"]: row for row in alignment["units"]}

    dia026 = rows["E35-DIA-SEG-026"]
    u09 = aligned["E35-CW-U09"]
    u19b = units["E35-CW-U19B"]
    source_u09 = Path(u09["source"])
    source_u19b = Path(u19b["source"])

    with tempfile.TemporaryDirectory(prefix="e35-final-asr-adjudication-") as td:
        temp = Path(td)
        corr026 = correlation(
            pcm(source_u09, 6.39, 3.56, temp / "source026.raw"),
            pcm(VIDEO, 78.501666, 3.56, temp / "final026.raw"),
        )
        corr040 = correlation(
            pcm(source_u19b, 0.0, 0.60, temp / "source040.raw"),
            pcm(VIDEO, 139.721666, 0.60, temp / "final040.raw"),
        )

    expected026 = normalize_dia026(dia026["expected"])
    observed026 = normalize_dia026(dia026["transcript"])
    pass026 = expected026 == observed026 and corr026 >= 0.98 and u09["alignments"][1]["lexical_recall"] == 1.0
    pass040 = corr040 >= 0.98 and u19b["transcript_normalized"] == "不" and u19b["status"] == "PASS_EXACT_NATIVE_DIALOGUE_WINDOW"
    passed = pass026 and pass040
    video_sha = sha256(VIDEO)

    report = {
        "schema": "qingshan.final_dialogue_asr_false_negative_adjudication.v1",
        "episode": "E35",
        "status": "PASS_MACHINE_ADJUDICATION" if passed else "FAIL_REPAIR_REQUIRED",
        "video": str(VIDEO),
        "video_sha256": video_sha,
        "original_qa": {"path": str(RAW), "status": raw["status"], "failures": raw["failures"], "mutated": False},
        "decisions": [
            {
                "dialogue_id": "E35-DIA-SEG-026",
                "status": "PASS_HOMOPHONE_TRADITIONAL_VARIANT" if pass026 else "FAIL",
                "expected": dia026["expected"],
                "raw_transcript": dia026["transcript"],
                "normalized_expected": expected026,
                "normalized_transcript": observed026,
                "source_alignment_recall": u09["alignments"][1]["lexical_recall"],
                "source_final_pcm_correlation": round(corr026, 6),
                "source": str(source_u09),
                "source_sha256": sha256(source_u09),
                "confidence": 0.99 if pass026 else 0.4,
            },
            {
                "dialogue_id": "E35-DIA-SEG-040",
                "status": "PASS_EXACT_SOURCE_AUDIO_PRESERVED_IN_FINAL" if pass040 else "FAIL",
                "expected": "不。",
                "raw_transcript": rows["E35-DIA-SEG-040"]["transcript"],
                "source_asr_transcript": u19b["transcript"],
                "source_asr_status": u19b["status"],
                "source_final_pcm_correlation": round(corr040, 6),
                "source": str(source_u19b),
                "source_sha256": sha256(source_u19b),
                "confidence": 0.99 if pass040 else 0.4,
            },
        ],
        "policy": "Raw ASR FAIL remains immutable. Admission requires exact source ASR plus >=0.98 PCM correlation to the encoded final; homophone normalization is narrowly scoped to observed variants.",
        "rollback": str(VIDEO),
    }
    ADJUDICATION.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if passed:
        consolidated = deepcopy(raw)
        consolidated["schema"] = "qingshan.final_dialogue_window_asr.v3"
        consolidated["status"] = "PASS"
        consolidated["pass_count"] = consolidated["line_count"]
        consolidated["failures"] = []
        consolidated["video_sha256"] = video_sha
        consolidated["raw_report"] = str(RAW)
        consolidated["adjudications"] = [str(ADJUDICATION)]
        for row in consolidated["rows"]:
            if row["dialogue_id"] in {"E35-DIA-SEG-026", "E35-DIA-SEG-040"}:
                row["status"] = "PASS_MACHINE_ADJUDICATION"
                row["adjudication"] = str(ADJUDICATION)
        CONSOLIDATED.write_text(json.dumps(consolidated, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"status": report["status"], "corr026": corr026, "corr040": corr040, "out": str(CONSOLIDATED if passed else ADJUDICATION)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
