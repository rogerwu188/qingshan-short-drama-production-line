#!/usr/bin/env python3
"""Fail H3 media that speaks text outside the canonical dialogue whitelist.

This gate is deliberately narrow: it does not judge acting quality.  It blocks
prompt narration, added dialogue, repeated lines, missing speech, and speech
that reaches the physical end of a clip.  ASR homophones remain advisory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from tools.portable_runtime import resolve_whisper_model


SCHEMA = "qingshan.h3_native_audio_dialogue_whitelist.v1"
PROMPT_LEAK_MARKERS = (
    "本镜头结果", "本节拍", "保持为", "动作完成", "说这句时", "台词期间",
    "镜头", "提示词", "摄影机", "画面", "角色", "场景", "对白",
)


def chinese(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", str(text or "")))


def canonical_dialogue(unit: dict[str, Any]) -> str:
    rows: list[str] = []
    for spec in unit.get("ordered_prompt_specs") or []:
        raw = str(spec.get("dialogue") or "").strip()
        if not raw:
            continue
        _speaker, separator, words = raw.partition("：")
        if not separator or not words.strip():
            raise ValueError(f"invalid speaker：dialogue row: {raw}")
        rows.append(words.strip())
    return "".join(rows)


def inserted_chunks(expected: str, observed: str) -> list[str]:
    source, actual = chinese(expected), chinese(observed)
    chunks: list[str] = []
    for tag, _i1, _i2, j1, j2 in SequenceMatcher(None, source, actual).get_opcodes():
        if tag in {"insert", "replace"}:
            value = actual[j1:j2]
            if value:
                chunks.append(value)
    return chunks


def evaluate_transcript(
    expected: str,
    observed: str,
    *,
    final_speech_end: float | None = None,
    media_duration: float | None = None,
    minimum_recall: float = 0.55,
    minimum_extra_chunk: int = 4,
) -> dict[str, Any]:
    source, actual = chinese(expected), chinese(observed)
    matching = sum(block.size for block in SequenceMatcher(None, source, actual).get_matching_blocks())
    recall = 1.0 if not source else matching / len(source)
    extras = inserted_chunks(source, actual)
    significant_extras = [row for row in extras if len(row) >= minimum_extra_chunk]
    marker_hits = [marker for marker in PROMPT_LEAK_MARKERS if marker in actual and marker not in source]
    failures: list[str] = []
    advisories: list[str] = []
    if source and not actual:
        failures.append("EXPECTED_DIALOGUE_MISSING")
    if not source and actual:
        failures.append("UNAUTHORED_SPEECH_IN_SILENT_UNIT")
    if source and recall < minimum_recall:
        failures.append(f"CANONICAL_DIALOGUE_RECALL_LOW:{recall:.3f}")
    if significant_extras:
        failures.append("NON_WHITELIST_SPEECH:" + "|".join(significant_extras))
    if marker_hits:
        failures.append("PROMPT_TEXT_NARRATION:" + "|".join(marker_hits))
    if source and actual.count(source) > 1:
        failures.append("CANONICAL_DIALOGUE_REPEATED")
    if (
        final_speech_end is not None and media_duration is not None and actual
        and final_speech_end >= media_duration - 0.08
    ):
        failures.append("SPEECH_REACHES_MEDIA_TAIL_HARD_CUT_RISK")
    if source and recall < 0.80 and recall >= minimum_recall:
        advisories.append(f"ASR_HOMOPHONE_OR_PARTIAL_REVIEW:{recall:.3f}")
    return {
        "schema": SCHEMA,
        "status": "PASS" if not failures else "FAIL",
        "expected": expected,
        "observed": observed,
        "normalized_expected": source,
        "normalized_observed": actual,
        "recall": round(recall, 3),
        "extra_chunks": extras,
        "significant_extra_chunks": significant_extras,
        "prompt_leak_marker_hits": marker_hits,
        "failures": failures,
        "advisories": advisories,
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", type=Path, required=True)
    parser.add_argument("--media", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model")
    args = parser.parse_args()
    unit = json.loads(args.unit.read_text(encoding="utf-8"))
    model_ref, model_source = resolve_whisper_model(args.model)
    from faster_whisper import WhisperModel

    model = WhisperModel(model_ref, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        str(args.media), language="zh", vad_filter=True, beam_size=5,
        initial_prompt=canonical_dialogue(unit),
    )
    rows = [
        {"start": round(row.start, 3), "end": round(row.end, 3), "text": row.text.strip()}
        for row in segments
    ]
    observed = "".join(row["text"] for row in rows)
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    report = evaluate_transcript(
        canonical_dialogue(unit), observed,
        final_speech_end=rows[-1]["end"] if rows else None,
        media_duration=duration,
    )
    report.update({
        "unit_id": str(unit.get("unit_id") or "UNKNOWN"),
        "media": str(args.media.resolve()),
        "media_sha256": sha256(args.media),
        "media_duration_seconds": round(duration, 3),
        "segments": rows,
        "runtime": {"whisper_model": model_ref, "model_source": model_source},
        "acceptance_allowed": report["status"] == "PASS",
    })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "out": str(args.out)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
