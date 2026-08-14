#!/usr/bin/env python3
"""OCR the bottom band of source videos to catch model-native subtitles."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


HAN_RE = re.compile(r"[\u3400-\u9fff]")
LATIN_WORD_RE = re.compile(r"[A-Za-z]{2,}")
NUMBER_RE = re.compile(r"\d{2,}")


def classify_bottom_text(text: str) -> str:
    """Return critical/warning for OCR hits in subtitle band.

    Single non-Chinese letters such as "m" are common texture false positives
    on cloth, wood grain, and object edges. Real native subtitles are normally
    multi-character Chinese, words, or number strings.
    """
    clean = text.strip()
    if not clean:
        return "ignore"
    if len(clean) == 1 and not HAN_RE.search(clean):
        return "warning"
    if HAN_RE.search(clean) or LATIN_WORD_RE.search(clean) or NUMBER_RE.search(clean):
        return "critical"
    return "warning"


def main() -> int:
    import cv2
    from rapidocr_onnxruntime import RapidOCR

    parser = argparse.ArgumentParser(description="Detect text in the bottom band of source MP4s.")
    parser.add_argument("--video", action="append", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--bottom-band", type=float, default=0.20)
    parser.add_argument("--confidence", type=float, default=0.45)
    args = parser.parse_args()

    engine = RapidOCR()
    recognitions = []
    critical = 0
    samples = 0

    for video_arg in args.video:
        video = Path(video_arg).expanduser().resolve()
        capture = cv2.VideoCapture(str(video))
        if not capture.isOpened():
            recognitions.append({"video": str(video), "error": "open_failed"})
            critical += 1
            continue
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        duration = frame_count / fps if fps else 0
        t = 0.5
        while t < duration:
            capture.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = capture.read()
            if not ok:
                t += args.interval
                continue
            h = frame.shape[0]
            start = max(0, int(h * (1.0 - args.bottom_band)))
            band = frame[start:h, :]
            result, _elapsed = engine(band)
            samples += 1
            for _box, text, confidence in result or []:
                clean = str(text).strip()
                score = float(confidence)
                if not clean or score < args.confidence:
                    continue
                severity = classify_bottom_text(clean)
                if severity == "ignore":
                    continue
                if severity == "critical":
                    critical += 1
                recognitions.append({
                    "video": str(video),
                    "time_seconds": round(t, 3),
                    "text": clean,
                    "confidence": round(score, 6),
                    "band": f"bottom {args.bottom_band:.0%}",
                    "severity": severity,
                })
            t += args.interval
        capture.release()

    payload = {
        "schema": "qingshan.source_video_bottom_text_audit.v1",
        "policy": "Source clips must not contain model-native subtitles or text in the bottom band before local subtitle burn-in.",
        "sample_interval_seconds": args.interval,
        "bottom_band": args.bottom_band,
        "confidence_threshold": args.confidence,
        "sample_count": samples,
        "recognitions": recognitions,
        "critical_text_failures": critical,
        "false_positive_policy": "single non-Chinese character OCR hits are warnings pending human/contact review, not direct FAIL",
        "status": "PASS" if critical == 0 else "FAIL",
    }
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "status": payload["status"], "critical_text_failures": critical}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
