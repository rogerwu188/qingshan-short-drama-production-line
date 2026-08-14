#!/usr/bin/env python3
"""Preflight guard for visual prompts that can trigger native subtitles/text."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


REQUIRED_NEGATIVE_TERMS = [
    "subtitles",
    "captions",
    "on-screen text",
    "text overlay",
    "watermark",
    "caption bar",
    "letterbox text",
    "字幕",
    "文字",
    "标题条",
]


VISUAL_MARKERS = ("VISUAL_PROMPT_NO_DIALOGUE_TEXT:", "VISUAL:")
NEGATIVE_MARKERS = ("NEGATIVE_PROMPT:", "NEGATIVE:")
AUDIO_MARKERS = ("AUDIO_PROMPT_DIALOGUE_ONLY:", "AUDIO:")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dialogue_texts(files: list[Path]) -> list[str]:
    texts: list[str] = []
    for path in files:
        data = read_json(path)
        if isinstance(data, dict):
            for item in data.get("dialogue_text_index", []) or []:
                text = str(item.get("text", "")).strip()
                if text:
                    texts.append(text)
            for item in data.get("dialogue_beats", []) or []:
                text = str(item.get("text", "")).strip()
                if text:
                    texts.append(text)
    return sorted(set(texts), key=len, reverse=True)


def extract_sections(text: str) -> tuple[str, str]:
    visual = text
    negative = ""
    for marker in AUDIO_MARKERS:
        if marker in visual:
            visual = visual.split(marker, 1)[0]
    for marker in VISUAL_MARKERS:
        if marker in visual:
            visual = visual.split(marker, 1)[1]
            break
    for marker in NEGATIVE_MARKERS:
        if marker in text:
            negative = text.split(marker, 1)[1]
            for audio_marker in AUDIO_MARKERS:
                negative = negative.split(audio_marker, 1)[0]
            break
    return visual.strip(), negative.strip()


def missing_required_terms(negative: str) -> list[str]:
    lower = negative.lower()
    return [term for term in REQUIRED_NEGATIVE_TERMS if term.lower() not in lower]


def dialogue_leaks(visual: str, dialogues: list[str]) -> list[str]:
    normalized = re.sub(r"\s+", "", visual)
    leaks = []
    for text in dialogues:
        if len(text) < 2:
            continue
        if re.sub(r"\s+", "", text) in normalized:
            leaks.append(text)
    return leaks


def prompt_files(inputs: list[str]) -> list[Path]:
    files: list[Path] = []
    for item in inputs:
        path = Path(item).expanduser().resolve()
        if path.is_dir():
            files.extend(sorted(path.rglob("*_prompt.txt")))
        elif path.exists():
            files.append(path)
        else:
            raise SystemExit(f"Missing prompt input: {path}")
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description="Check visual prompt text/subtitle safety.")
    parser.add_argument("--prompt", action="append", required=True, help="Prompt file or directory.")
    parser.add_argument("--dialogue-json", action="append", default=[], help="JSON containing dialogue_text_index/dialogue_beats.")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    prompts = prompt_files(args.prompt)
    dialogues = dialogue_texts([Path(p).expanduser().resolve() for p in args.dialogue_json])
    results = []
    failure_count = 0
    for path in prompts:
        text = path.read_text(encoding="utf-8")
        visual, negative = extract_sections(text)
        missing = missing_required_terms(negative)
        leaks = dialogue_leaks(visual, dialogues)
        status = "PASS" if not missing and not leaks else "FAIL"
        if status == "FAIL":
            failure_count += 1
        results.append({
            "prompt_file": str(path),
            "status": status,
            "dialogue_leaks": leaks,
            "missing_required_negative_terms": missing,
            "negative_prompt_present": bool(negative),
        })

    payload = {
        "schema": "qingshan.visual_text_prompt_guard.v1",
        "policy": "Visual prompts must contain no dialogue text and negative prompts must explicitly suppress model-native subtitles/text overlays.",
        "required_negative_terms": REQUIRED_NEGATIVE_TERMS,
        "prompt_count": len(prompts),
        "failure_count": failure_count,
        "results": results,
        "status": "PASS" if failure_count == 0 else "FAIL",
    }
    out = Path(args.out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "status": payload["status"], "failure_count": failure_count}, ensure_ascii=False))
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
