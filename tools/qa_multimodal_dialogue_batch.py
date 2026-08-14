#!/usr/bin/env python3
"""Run portable technical and Mandarin ASR checks on harvested dialogue clips."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

from tools.portable_runtime import resolve_media_binary, resolve_whisper_model


ROOT = Path(__file__).resolve().parents[1]


def chinese(text: str) -> str:
    normalized = text.translate(
        str.maketrans({"開": "开", "請": "请", "門": "门"})
    )
    return "".join(re.findall(r"[\u4e00-\u9fff]", normalized))


def recall(expected: str, got: str) -> float:
    source, actual = chinese(expected), chinese(got)
    if not source:
        return 1.0
    if source in actual:
        return 1.0
    matched = sum(
        block.size
        for block in SequenceMatcher(None, source, actual).get_matching_blocks()
    )
    return matched / len(source)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path, ffprobe: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def transcribe_payload(model: Any, path: Path, expected: str) -> list[dict[str, Any]]:
    segments, _ = model.transcribe(
        str(path),
        language="zh",
        vad_filter=True,
        beam_size=5,
        initial_prompt=expected,
    )
    return [
        {
            "start": round(segment.start, 3),
            "end": round(segment.end, 3),
            "text": segment.text.strip(),
        }
        for segment in segments
    ]


def review_dialogue(
    dialogue_id: str,
    task: dict[str, Any],
    harvested: dict[str, Any],
    *,
    model: Any,
    ffprobe: Path,
    minimum_recall: float,
    probe_fn: Callable[[Path, Path], dict[str, Any]] = probe,
) -> dict[str, Any]:
    files = harvested.get("downloaded_files") or []
    failures: list[str] = []
    advisories: list[str] = []
    if len(files) != 1:
        return {
            "dialogue_id": dialogue_id,
            "status": "FAIL",
            "failures": [f"downloaded_file_count:{len(files)}"],
            "advisories": [],
        }
    path = Path(files[0]).expanduser().resolve()
    if not path.is_file():
        return {
            "dialogue_id": dialogue_id,
            "status": "FAIL",
            "failures": ["downloaded_file_missing"],
            "advisories": [],
        }
    try:
        info = probe_fn(path, ffprobe)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        return {
            "dialogue_id": dialogue_id,
            "status": "FAIL",
            "path": str(path),
            "failures": [f"media_probe_failed:{type(exc).__name__}"],
            "advisories": [],
        }
    streams = info.get("streams", [])
    video = next((row for row in streams if row.get("codec_type") == "video"), None)
    audio = next((row for row in streams if row.get("codec_type") == "audio"), None)
    duration = float((info.get("format") or {}).get("duration") or 0)
    if not video:
        failures.append("video_stream_missing")
    if not audio:
        failures.append("audio_stream_missing")
    planned_duration = float(task.get("duration") or 0)
    if not 4.0 <= planned_duration <= 15.0:
        failures.append(f"planned_duration_out_of_range:{planned_duration:.3f}")
    elif abs(duration - planned_duration) > 0.20:
        failures.append(
            f"duration_deviates_from_story_plan:{duration:.3f}!={planned_duration:.3f}"
        )
    segments = transcribe_payload(model, path, str(task.get("text") or "")) if audio else []
    transcript = "".join(row["text"] for row in segments)
    score = recall(str(task.get("text") or ""), transcript)
    if not chinese(transcript):
        failures.append("no_recognized_chinese_speech")
    elif score < minimum_recall:
        failures.append(f"expected_dialogue_recall_below_threshold:{score:.3f}")
    elif score < max(minimum_recall, 0.75):
        advisories.append(f"homophone_or_partial_asr_review:{score:.3f}")
    if segments and segments[-1]["end"] >= duration - 0.05:
        advisories.append("speech_reaches_source_tail_sentence_boundary_review")
    return {
        "dialogue_id": dialogue_id,
        "speaker": task.get("speaker"),
        "expected": task.get("text"),
        "path": str(path),
        "sha256": sha256(path),
        "duration_seconds": round(duration, 3),
        "video_stream": bool(video),
        "audio_stream": bool(audio),
        "transcript": transcript,
        "segments": segments,
        "recall_score": round(score, 3),
        "status": "PASS" if not failures else "FAIL",
        "failures": failures,
        "advisories": advisories,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--status-report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--model")
    parser.add_argument("--ffprobe")
    parser.add_argument("--minimum-recall", type=float, default=0.55)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    status = json.loads(args.status_report.read_text(encoding="utf-8"))
    tasks = {row["dialogue_id"]: row for row in manifest.get("tasks", [])}
    harvested = {row["dialogue_id"]: row for row in status.get("results", [])}
    if not tasks:
        raise SystemExit("dialogue manifest contains no tasks")
    if not 0.0 < args.minimum_recall <= 1.0:
        raise SystemExit("minimum recall must be in (0, 1]")

    ffprobe, ffprobe_source = resolve_media_binary(
        "ffprobe", explicit=args.ffprobe, root=ROOT
    )
    model_ref, model_source = resolve_whisper_model(args.model)
    from faster_whisper import WhisperModel

    model = WhisperModel(
        model_ref,
        device="cpu",
        compute_type="int8",
        cpu_threads=max(1, args.workers),
        num_workers=max(1, args.workers),
    )

    results = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = [
            pool.submit(
                review_dialogue,
                dialogue_id,
                tasks[dialogue_id],
                harvested.get(dialogue_id, {}),
                model=model,
                ffprobe=ffprobe,
                minimum_recall=args.minimum_recall,
            )
            for dialogue_id in sorted(tasks)
        ]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: row["dialogue_id"])
    fail_count = sum(row["status"] == "FAIL" for row in results)
    payload = {
        "schema": "qingshan.multimodal_dialogue_batch_qa.v2",
        "episode": manifest.get("episode"),
        "status": "PASS" if fail_count == 0 else "FAIL_WITH_ISOLATED_ITEMS",
        "item_count": len(results),
        "pass_count": len(results) - fail_count,
        "fail_count": fail_count,
        "advisory_count": sum(len(row.get("advisories", [])) for row in results),
        "minimum_recall": args.minimum_recall,
        "workers": args.workers,
        "runtime": {
            "ffprobe": str(ffprobe),
            "ffprobe_source": ffprobe_source,
            "whisper_model": model_ref,
            "whisper_model_source": model_source,
        },
        "policy": "Passed siblings are preserved. Only failed dialogue IDs may be corrected and resubmitted.",
        "results": results,
        "final_lock_allowed": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": payload["status"],
                "pass": payload["pass_count"],
                "fail": fail_count,
                "out": str(args.out),
            },
            ensure_ascii=False,
        )
    )
    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
