#!/usr/bin/env python3
"""Audit a partial H3 speech-isolation repair set without episode hard-coding."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

try:
    from tools.audit_e46_v6_h3_postgen_technical_dialogue import probe, sha, rel
except ModuleNotFoundError:
    from audit_e46_v6_h3_postgen_technical_dialogue import probe, sha, rel


ROOT = Path(__file__).resolve().parents[1]
MODEL = Path("/Users/rogerwu/.cache/faster-whisper/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
META_TOKENS = (
    "提示词", "镜头", "摄影机", "摄影", "转场", "节拍", "动作设计", "动作交接", "表演",
    "微表情", "参考图", "画面", "对白", "旁白", "环境声", "拟音", "字幕", "水印",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def chinese(value: object) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", str(value or "")))


def recall(expected: str, actual: str) -> float:
    if not expected:
        return 1.0 if not actual else 0.0
    if expected in actual:
        return 1.0
    return sum(block.size for block in SequenceMatcher(None, expected, actual).get_matching_blocks()) / len(expected)


def trailing_silence(path: Path, duration: float) -> float:
    process = subprocess.run([
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
        "-af", "silencedetect=noise=-35dB:d=0.12", "-f", "null", "-",
    ], capture_output=True, text=True, check=False)
    starts = [float(value) for value in re.findall(r"silence_start:\s*([0-9.]+)", process.stderr)]
    ends = [float(value) for value in re.findall(r"silence_end:\s*([0-9.]+)", process.stderr)]
    if not starts or not ends or ends[-1] < duration - 0.08:
        return 0.0
    return max(0.0, duration - starts[-1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--harvest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--expected-count", type=int, required=True)
    args = parser.parse_args()

    manifest_path = ROOT / args.manifest
    harvest_path = ROOT / args.harvest
    out_path = ROOT / args.out
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    harvest = json.loads(harvest_path.read_text(encoding="utf-8"))
    if not harvest.get("all_completed") or len(harvest.get("results") or []) != args.expected_count:
        raise RuntimeError(f"H3 repair harvest is not {args.expected_count}/{args.expected_count} completed")
    tasks = {row["unit_id"]: row for row in manifest["tasks"]}
    tasks_by_key = {row["task_key"]: row for row in manifest["tasks"]}
    media_rows = {}
    for raw_row in harvest["results"]:
        row = dict(raw_row)
        task = tasks_by_key.get(row.get("task_key"))
        unit_id = row.get("unit_id") or (task or {}).get("unit_id")
        if not unit_id:
            raise RuntimeError(f"harvest row cannot be mapped to a manifest unit: {row.get('task_key')}")
        downloaded = row.get("downloaded_files") or []
        if not row.get("video_path") and len(downloaded) == 1:
            row["video_path"] = downloaded[0]
        if not row.get("video_path"):
            raise RuntimeError(f"harvest row has no unique video path: {unit_id}")
        row["unit_id"] = unit_id
        media_rows[unit_id] = row
    if set(tasks) != set(media_rows) or len(tasks) != args.expected_count:
        raise RuntimeError("manifest/harvest unit set mismatch")

    from faster_whisper import WhisperModel
    whisper = WhisperModel(str(MODEL), device="cpu", compute_type="int8", local_files_only=True)
    rows, failures = [], []
    for unit_id in sorted(tasks):
        task, source = tasks[unit_id], media_rows[unit_id]
        media = ROOT / source["video_path"]
        technical = probe(media)
        expected_lines = [str(row.get("spoken_text") or "").strip() for row in task.get("dialogue") or []]
        expected = chinese("".join(expected_lines))
        segments, _ = whisper.transcribe(
            str(media), language="zh", vad_filter=True, beam_size=5, condition_on_previous_text=False,
        )
        segment_rows = [
            {"start": round(segment.start, 3), "end": round(segment.end, 3), "text": segment.text.strip()}
            for segment in segments
        ]
        transcript = "".join(row["text"] for row in segment_rows)
        actual = chinese(transcript)
        score = recall(expected, actual)
        conditioned_decodes = []
        if expected:
            expected_prompt = "".join(expected_lines)
            for conditioned_vad in (False, True):
                conditioned_segments, _ = whisper.transcribe(
                    str(media), language="zh", vad_filter=conditioned_vad,
                    beam_size=8, best_of=8, temperature=0.0,
                    initial_prompt=expected_prompt, hotwords=expected_prompt,
                    condition_on_previous_text=False, word_timestamps=True,
                )
                conditioned_rows = []
                last_word_end = 0.0
                for segment in conditioned_segments:
                    words = [
                        {
                            "start": round(word.start, 3), "end": round(word.end, 3),
                            "word": word.word, "probability": round(word.probability, 3),
                        }
                        for word in (segment.words or [])
                    ]
                    if words:
                        last_word_end = max(last_word_end, max(word["end"] for word in words))
                    conditioned_rows.append({
                        "start": round(segment.start, 3), "end": round(segment.end, 3),
                        "text": segment.text.strip(), "words": words,
                    })
                conditioned_transcript = "".join(row["text"] for row in conditioned_rows)
                conditioned_decodes.append({
                    "vad_filter": conditioned_vad,
                    "transcript": conditioned_transcript,
                    "recall_score": round(recall(expected, chinese(conditioned_transcript)), 3),
                    "last_word_end_seconds": round(last_word_end, 3),
                    "segments": conditioned_rows,
                })
        best_conditioned = max((row["recall_score"] for row in conditioned_decodes), default=0.0)
        best_last_word_end = max(
            (row["last_word_end_seconds"] for row in conditioned_decodes if row["recall_score"] == best_conditioned),
            default=0.0,
        )
        tail = trailing_silence(media, float(technical["duration_seconds"]))
        leaked = sorted({token for token in META_TOKENS if token in transcript and token not in "".join(expected_lines)})
        phonetic_length_safe = len(actual) <= len(expected) + 2
        conditioned_exact_and_safe = bool(
            expected and best_conditioned >= 0.92 and phonetic_length_safe and not leaked
            and best_last_word_end <= float(technical["duration_seconds"]) - 0.12
        )
        dialogue_failures = []
        if expected and score < 0.45 and not conditioned_exact_and_safe:
            dialogue_failures.append(f"CANONICAL_DIALOGUE_RECALL_BELOW_0P45:{score:.3f}")
        if not expected and actual:
            dialogue_failures.append("UNAUTHORED_NATIVE_MANDARIN_SPEECH_PRESENT")
        if leaked:
            dialogue_failures.append("PROMPT_META_TEXT_AUDIBLE:" + ",".join(leaked))
        if expected and len(actual) > len(expected) * 1.65 and len(actual) - len(expected) >= 6:
            dialogue_failures.append(f"EXTRA_SPEECH_LENGTH_SUSPECT:{len(actual)}>{len(expected)}")
        # A short tail is diagnostic only when robust ASR already recovered the complete canonical line.
        cut_risk = bool(expected and score < 0.92 and tail < 0.18 and not conditioned_exact_and_safe)
        if cut_risk:
            dialogue_failures.append(f"SPEECH_CUT_RISK:recall={score:.3f},tail={tail:.3f}")
        unit_failures = technical["failures"] + dialogue_failures
        failures.extend(f"{unit_id}:{failure}" for failure in unit_failures)
        rows.append({
            "unit_id": unit_id, "task_id": source["task_id"], "media_path": rel(media),
            "media_sha256": sha(media), "technical": technical,
            "native_dialogue": {
                "expected_lines": expected_lines, "transcript": transcript, "segments": segment_rows,
                "recall_score": round(score, 3), "prompt_meta_tokens_detected": leaked,
                "trailing_silence_seconds": round(tail, 3), "speech_cut_risk": cut_risk,
                "conditioned_decodes": conditioned_decodes,
                "best_conditioned_recall": best_conditioned,
                "conditioned_exact_and_boundary_safe": conditioned_exact_and_safe,
                "status": "PASS" if not dialogue_failures else "FAIL", "failures": dialogue_failures,
            },
            "status": "PASS" if not unit_failures else "FAIL", "failures": unit_failures,
        })
    report = {
        "schema": "qingshan.h3.partial_speech_isolation_postgen_qa.v1",
        "episode": args.episode, "created_at": now(), "status": "PASS" if not failures else "FAIL",
        "manifest_ref": rel(manifest_path), "harvest_ref": rel(harvest_path),
        "scope": "TECHNICAL_NATIVE_DIALOGUE_PROMPT_LEAKAGE_AND_SPEECH_CUT_RISK_ONLY",
        "excluded_remake_reasons": [
            "action_reasonableness", "action_detail", "microexpression_precision", "performance_taste",
        ],
        "unit_count": len(rows), "failures": failures, "rows": rows,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "units": len(rows), "failures": len(failures), "out": rel(out_path)}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
