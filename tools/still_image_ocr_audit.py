#!/usr/bin/env python3
"""Run RapidOCR against still images and emit the same text-risk fields as final_video_ocr_audit."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
from rapidocr_onnxruntime import RapidOCR

from final_video_ocr_audit import classify_text


def image_paths(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for item in inputs:
        p = Path(item).expanduser().resolve()
        if p.is_dir():
            paths.extend(sorted(x for x in p.rglob("*") if x.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}))
        elif p.exists():
            paths.append(p)
        else:
            raise SystemExit(f"Missing image input: {p}")
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate still-image OCR audit JSON.")
    parser.add_argument("--image", action="append", required=True, help="Image file or directory; can be repeated.")
    parser.add_argument("--out", required=True)
    parser.add_argument("--confidence", type=float, default=0.50)
    parser.add_argument("--allow-text", action="append", default=[])
    parser.add_argument("--forbid-text", action="append", default=[])
    args = parser.parse_args()

    engine = RapidOCR()
    paths = image_paths(args.image)
    recognitions = []
    latin_chars = 0
    critical_failures = 0
    unlisted_chinese = []
    numeric_strings = []

    for path in paths:
        frame = cv2.imread(str(path))
        if frame is None:
            recognitions.append({"file": str(path), "error": "cv2_imread_failed"})
            critical_failures += 1
            continue
        result, _elapsed = engine(frame)
        for _box, text, confidence in result or []:
            clean = str(text).strip()
            score = float(confidence)
            if not clean or score < args.confidence:
                continue
            classification = classify_text(clean, args.allow_text, args.forbid_text)
            latin_count = classification["latin_chars"]
            latin_chars += latin_count
            if classification["forbidden"] or latin_count:
                critical_failures += 1
            if classification["unlisted_chinese"]:
                unlisted_chinese.append({"file": str(path), "text": clean})
            if classification["numeric_string"]:
                numeric_strings.append({"file": str(path), "text": clean})
            recognitions.append({
                "file": str(path),
                "text": clean,
                "confidence": round(score, 6),
                "allowed": classification["allowed"],
                "forbidden": classification["forbidden"],
                "forbidden_tokens": classification["forbidden_tokens"],
                "latin_chars": latin_count,
                "unlisted_chinese": classification["unlisted_chinese"],
                "numeric_string": classification["numeric_string"],
            })

    lexicon_policy_configured = bool(args.allow_text or args.forbid_text)
    payload = {
        "schema": "qingshan.still_image_ocr_audit.v1",
        "engine": "RapidOCR / ONNX Runtime",
        "source_images": [str(p) for p in paths],
        "confidence_threshold": args.confidence,
        "allow_text": args.allow_text,
        "forbid_text": args.forbid_text,
        "lexicon_policy_configured": lexicon_policy_configured,
        "recognitions": recognitions,
        "latin_chars": latin_chars,
        "unlisted_chinese_warnings": unlisted_chinese,
        "numeric_string_warnings": numeric_strings,
        "critical_text_failures": critical_failures,
        "status": "PASS" if lexicon_policy_configured and latin_chars == 0 and critical_failures == 0 else "FAIL",
    }

    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "status": payload["status"],
        "images": len(paths),
        "recognitions": len(recognitions),
        "latin_chars": latin_chars,
        "critical_text_failures": critical_failures,
    }, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
