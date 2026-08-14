#!/usr/bin/env python3
import json
import subprocess
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
from rapidocr_onnxruntime import RapidOCR


VIDEO = Path("/Users/rogerwu/Downloads/参考视频1.mp4")
OUT = Path("/Users/rogerwu/qingshan_short_drama/qa/reference_video_1_20260712")
FFMPEG = Path("/tmp/qingshan_video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1")
W, H, FPS = 426, 240, 0.5


def frames():
    command = [
        str(FFMPEG), "-v", "error", "-ss", "0", "-t", "1200", "-i", str(VIDEO),
        "-an", "-vf", f"fps={FPS},scale={W}:{H}", "-pix_fmt", "bgr24", "-f", "rawvideo", "pipe:1",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    size = W * H * 3
    index = 0
    while True:
        data = process.stdout.read(size)
        if len(data) != size:
            break
        yield index / FPS, np.frombuffer(data, np.uint8).reshape(H, W, 3)
        index += 1
    process.stdout.close()
    process.wait()


def normalize(text):
    return "".join(character for character in text.strip() if not character.isspace())


def main():
    engine = RapidOCR()
    records = []
    previous = ""
    for timestamp, frame in frames():
        crop = frame[int(H * 0.55):H, :]
        crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        result, _ = engine(crop)
        if not result:
            continue
        candidates = []
        for box, text, confidence in result:
            clean = normalize(text)
            if confidence >= 0.55 and len(clean) >= 2:
                candidates.append((float(np.mean(np.array(box)[:, 1])), clean, float(confidence)))
        if not candidates:
            continue
        candidates.sort()
        text = normalize("".join(item[1] for item in candidates))
        if len(text) < 2:
            continue
        if previous and SequenceMatcher(None, previous, text).ratio() >= 0.82:
            continue
        records.append({"timestamp": timestamp, "text": text, "confidence": min(item[2] for item in candidates)})
        previous = text

    (OUT / "subtitles_first20min.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [f"{item['timestamp']:07.1f}s\t{item['text']}" for item in records]
    (OUT / "subtitles_first20min.txt").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"records": len(records), "output": str(OUT / 'subtitles_first20min.txt')}, ensure_ascii=False))


if __name__ == "__main__":
    main()
