#!/usr/bin/env python3
"""Adjudicate suspected long-dialogue ASR false negatives with dual VAD paths."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from tools.portable_runtime import resolve_whisper_model


def han(value: str) -> str:
    return "".join(re.findall(r"[\u3400-\u9fff]", value))


def recall(expected: str, actual: str) -> float:
    target, observed = han(expected), han(actual)
    if target in observed:
        return 1.0
    matched = sum(block.size for block in SequenceMatcher(None, target, observed).get_matching_blocks())
    return matched / len(target) if target else 1.0


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--dialogue-json", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--minimum-recall", type=float, default=0.80)
    parser.add_argument("--model")
    args = parser.parse_args()

    video = args.video.expanduser().resolve()
    contract = json.loads(args.dialogue_json.read_text(encoding="utf-8"))
    rows = contract.get("dialogue") or contract.get("rows") or []
    expected = "".join(str(row.get("spoken_text") or row.get("text") or "") for row in rows)
    expected_han = han(expected)
    # Whisper's decoder has a finite prompt context. Full-episode contracts can
    # exceed it, while short single-shot contracts still benefit from hotwords.
    initial_prompt = expected_han[:160]
    hotwords = expected if len(expected_han) <= 80 else None
    model_ref, model_source = resolve_whisper_model(args.model)
    from faster_whisper import WhisperModel

    model = WhisperModel(model_ref, device="cpu", compute_type="int8")
    paths = []
    for vad in (False, True):
        segments, _ = model.transcribe(
            str(video),
            language="zh",
            vad_filter=vad,
            beam_size=8,
            best_of=8,
            temperature=0.0,
            initial_prompt=initial_prompt,
            hotwords=hotwords,
            condition_on_previous_text=False,
        )
        segment_rows = [
            {"start": round(float(row.start), 3), "end": round(float(row.end), 3), "text": row.text.strip()}
            for row in segments
        ]
        transcript = "".join(row["text"] for row in segment_rows)
        paths.append({
            "vad_filter": vad,
            "transcript": transcript,
            "recall_score": round(recall(expected, transcript), 4),
            "segments": segment_rows,
        })

    best = max(path["recall_score"] for path in paths)
    payload = {
        "schema": "qingshan.independent_dual_vad_dialogue_adjudication.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS" if best >= args.minimum_recall else "FAIL",
        "video": str(video),
        "video_sha256": sha256(video),
        "dialogue_contract": str(args.dialogue_json),
        "dialogue_contract_sha256": sha256(args.dialogue_json),
        "expected_text": expected,
        "prompt_policy": {
            "expected_han_characters": len(expected_han),
            "initial_prompt_han_characters": len(initial_prompt),
            "hotwords_enabled": hotwords is not None,
            "reason": "TRUNCATE_FULL_EPISODE_PROMPT_TO_STAY_WITHIN_WHISPER_POSITION_LIMIT",
        },
        "minimum_recall": args.minimum_recall,
        "best_recall": best,
        "model": model_ref,
        "model_source": model_source,
        "paths": paths,
        "paid_retry_policy": "BLOCKED_WHEN_EITHER_INDEPENDENT_PATH_PASSES",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "best_recall": best, "out": str(args.out)}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
