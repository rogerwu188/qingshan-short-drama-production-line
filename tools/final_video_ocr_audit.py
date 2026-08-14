#!/usr/bin/env python3
"""Run reproducible OCR against sampled frames from a final audience-facing MP4."""

from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
from pathlib import Path

LATIN_RE = re.compile(r"[A-Za-z]")
HAN_RE = re.compile(r"[\u3400-\u9fff]")
NUMBER_RE = re.compile(r"\d{2,}")


def critical_latin_count(latin_count: int) -> int:
    """Treat isolated one-letter OCR hits as warnings, not release failures."""
    return latin_count if latin_count >= 2 else 0


def resolve_sampling_policy(
    *, interval: float, exclude_final_seconds: float, source_mode: bool
) -> tuple[float, float, str]:
    if source_mode:
        return min(interval, 0.5), 0.0, "SOURCE_FULL_DURATION"
    return interval, exclude_final_seconds, "FINAL_AUDIENCE_FACING"


def choose_media_duration(container_duration: float | None, frame_duration: float) -> float:
    candidates = [value for value in (container_duration, frame_duration) if value and math.isfinite(value) and value > 0]
    return max(candidates, default=0.0)


def probe_container_duration(video: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(video),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        value = float(json.loads(result.stdout)["format"]["duration"])
        return value if math.isfinite(value) and value > 0 else None
    except (FileNotFoundError, KeyError, TypeError, ValueError, subprocess.CalledProcessError, json.JSONDecodeError):
        return None


def classify_text(text: str, allow_text: list[str], forbid_text: list[str]) -> dict:
    allowed = text in {token for token in allow_text if token}
    forbidden_tokens = [token for token in forbid_text if token and token in text]
    latin_count = len(LATIN_RE.findall(text)) if not allowed else 0
    return {
        "allowed": allowed,
        "forbidden": bool(forbidden_tokens),
        "forbidden_tokens": forbidden_tokens,
        "latin_chars": latin_count,
        "unlisted_chinese": len(HAN_RE.findall(text)) >= 2 and not allowed and not forbidden_tokens,
        "numeric_string": bool(NUMBER_RE.search(text)) and not allowed,
    }


def continuous_runs(
    samples: list[dict], interval: float, *, immediate_multi_han: bool = False
) -> tuple[list[dict], list[dict]]:
    merged: list[dict] = []
    for sample in samples:
        if merged and sample["time_seconds"] == merged[-1]["time_seconds"]:
            merged[-1]["text"] = f'{merged[-1]["text"]} | {sample["text"]}'
        else:
            merged.append(dict(sample))
    runs: list[list[dict]] = []
    for sample in merged:
        if runs and sample["time_seconds"] - runs[-1][-1]["time_seconds"] <= interval * 1.5:
            runs[-1].append(sample)
        else:
            runs.append([sample])
    critical = []
    warnings = []
    for run in runs:
        payload = {
            "start_seconds": run[0]["time_seconds"],
            "end_seconds": run[-1]["time_seconds"],
            "sample_count": len(run),
            "texts": [item["text"] for item in run],
        }
        has_multi_han = immediate_multi_han and any(
            len(HAN_RE.findall(str(item.get("text") or ""))) >= 2 for item in run
        )
        (critical if len(run) >= 2 or has_multi_han else warnings).append(payload)
    return critical, warnings


def main() -> int:
    import cv2
    from rapidocr_onnxruntime import RapidOCR

    parser = argparse.ArgumentParser(description="Generate final-MP4 OCR audit JSON.")
    parser.add_argument("--video", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--subtitle-band", type=float, default=0.20)
    parser.add_argument("--exclude-final-seconds", type=float, default=4.0)
    parser.add_argument("--confidence", type=float, default=0.50)
    parser.add_argument(
        "--source-mode",
        action="store_true",
        help="Audit a generated source across its full duration at least every 0.5 seconds.",
    )
    parser.add_argument("--allow-text", action="append", default=[])
    parser.add_argument("--forbid-text", action="append", default=[])
    args = parser.parse_args()
    args.interval, args.exclude_final_seconds, audit_mode = resolve_sampling_policy(
        interval=args.interval,
        exclude_final_seconds=args.exclude_final_seconds,
        source_mode=args.source_mode,
    )

    video = Path(args.video).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    if not video.exists():
        raise SystemExit(f"Missing final video: {video}")
    if not 0 <= args.subtitle_band < 0.5:
        raise SystemExit("--subtitle-band must be in [0, 0.5).")

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise SystemExit(f"Could not open final video: {video}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    frame_duration = frame_count / fps
    duration = choose_media_duration(probe_container_duration(video), frame_duration)
    audit_end = max(0.0, duration - args.exclude_final_seconds)
    engine = RapidOCR()

    recognitions = []
    unlisted_samples = []
    numeric_samples = []
    latin_samples = []
    latin_chars = 0
    critical_latin_chars = 0
    isolated_latin_warnings = []
    critical_failures = 0
    sample_count = 0
    timestamp = 0.5
    while timestamp < audit_end:
        capture.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
        ok, frame = capture.read()
        if not ok:
            timestamp += args.interval
            continue
        keep_height = max(1, int(frame.shape[0] * (1.0 - args.subtitle_band)))
        cropped = frame[:keep_height, :]
        result, _elapsed = engine(cropped)
        sample_count += 1
        for box, text, confidence in result or []:
            clean = str(text).strip()
            score = float(confidence)
            if not clean or score < args.confidence:
                continue
            normalized_box = [
                [round(float(point[0]), 3), round(float(point[1]), 3)]
                for point in (box or [])
                if len(point) >= 2
            ]
            box_height = (
                max(point[1] for point in normalized_box) - min(point[1] for point in normalized_box)
                if normalized_box else 0.0
            )
            # OCR occasionally labels a face, window lattice, or document plane
            # as a few Latin glyphs. Such regions are much taller than rendered
            # text. Preserve the recognition as evidence, but do not let a large
            # texture region become a release failure.
            geometric_text_candidate = bool(normalized_box) and box_height <= cropped.shape[0] * 0.07
            classification = classify_text(clean, args.allow_text, args.forbid_text)
            allowed = classification["allowed"]
            forbidden = classification["forbidden"]
            latin_count = classification["latin_chars"]
            if latin_count:
                latin_chars += latin_count
                if geometric_text_candidate:
                    latin_samples.append({"time_seconds": round(timestamp, 3), "text": clean})
                if latin_count == 1 and geometric_text_candidate:
                    isolated_latin_warnings.append({
                        "time_seconds": round(timestamp, 3),
                        "text": clean,
                        "confidence": round(score, 6),
                    })
            if forbidden and geometric_text_candidate:
                critical_failures += 1
            recognitions.append({
                "time_seconds": round(timestamp, 3),
                "text": clean,
                "confidence": round(score, 6),
                "box": normalized_box,
                "box_height": round(box_height, 3),
                "geometric_text_candidate": geometric_text_candidate,
                "allowed": allowed,
                "forbidden": forbidden,
                "forbidden_tokens": classification["forbidden_tokens"],
                "latin_chars": latin_count,
                "unlisted_chinese": classification["unlisted_chinese"],
                "numeric_string": classification["numeric_string"],
            })
            if classification["unlisted_chinese"] and geometric_text_candidate:
                unlisted_samples.append({"time_seconds": round(timestamp, 3), "text": clean})
            if classification["numeric_string"] and geometric_text_candidate:
                numeric_samples.append({"time_seconds": round(timestamp, 3), "text": clean})
        timestamp += args.interval
    capture.release()

    lexicon_policy_configured = bool(args.allow_text and args.forbid_text)
    # A multi-character non-allowlisted Han string is audience-readable text even
    # when OCR sees it in only one sampled frame. Persistence remains necessary
    # for isolated glyphs and numeric texture noise.
    unlisted_hits, unlisted_warnings = continuous_runs(
        unlisted_samples, args.interval, immediate_multi_han=True
    )
    numeric_hits, numeric_warnings = continuous_runs(numeric_samples, args.interval)
    latin_hits, latin_warnings = continuous_runs(latin_samples, args.interval)
    critical_latin_chars = sum(
        len(LATIN_RE.findall(text))
        for hit in latin_hits
        for text in hit["texts"]
    )
    critical_failures += len(unlisted_hits) + len(numeric_hits) + len(latin_hits)
    status = "PASS" if not critical_latin_chars and not critical_failures else "FAIL"
    lexicon_policy_status = "CONFIGURED" if lexicon_policy_configured else "ADVISORY_NOT_CONFIGURED"
    payload = {
        "schema": "qingshan.final_video_ocr_audit.v4",
        "policy_version": "qingshan.ocr.geometry-persistence.v5",
        "source_final_mp4": str(video),
        "audit_mode": audit_mode,
        "audit_scope": {
            "main_content_start_seconds": 0.0,
            "main_content_end_seconds": round(audit_end, 6),
            "sampled_through_seconds": round(audit_end, 6),
            "last_sample_time_seconds": round(min(max(0.0, timestamp - args.interval), audit_end), 6),
        },
        "sampled_through_seconds": round(audit_end, 6),
        "engine": "RapidOCR 1.4.4 / ONNX Runtime",
        "sample_interval_seconds": args.interval,
        "sample_count": sample_count,
        "confidence_threshold": args.confidence,
        "subtitle_exclusion": f"bottom {args.subtitle_band:.0%} excluded before OCR",
        "end_card_exclusion_seconds": args.exclude_final_seconds,
        "allow_text": args.allow_text,
        "forbid_text": args.forbid_text,
        "lexicon_policy_configured": lexicon_policy_configured,
        "lexicon_policy_status": lexicon_policy_status,
        "recognitions": recognitions,
        "latin_chars": latin_chars,
        "critical_latin_chars": critical_latin_chars,
        "persistent_latin_hits": latin_hits,
        "isolated_or_nontext_latin_warnings": latin_warnings,
        "isolated_latin_warnings": isolated_latin_warnings,
        "unlisted_chinese_hits": unlisted_hits,
        "numeric_string_hits": numeric_hits,
        "isolated_unlisted_chinese_warnings": unlisted_warnings,
        "isolated_numeric_warnings": numeric_warnings,
        "uncommon_chinese_check": "STRICT_MULTI_HAN_OR_CONTINUITY_GATE",
        "critical_text_failures": critical_failures,
        "status": status,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "status": payload["status"],
        "samples": sample_count,
        "recognitions": len(recognitions),
        "latin_chars": latin_chars,
        "critical_latin_chars": critical_latin_chars,
        "critical_text_failures": critical_failures,
        "lexicon_policy_configured": lexicon_policy_configured,
        "unlisted_chinese_hits": len(unlisted_hits),
        "numeric_string_hits": len(numeric_hits),
    }, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
