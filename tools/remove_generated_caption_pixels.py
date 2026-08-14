#!/usr/bin/env python3
"""Remove model-generated white caption glyphs from a bounded video region."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
AGENTCUT_VENDOR = next((ROOT / ".agentcut_env").glob("lib/python*/site-packages/agentcut/vendor/darwin-arm64"))
FFMPEG = AGENTCUT_VENDOR / "ffmpeg"
FFPROBE = AGENTCUT_VENDOR / "ffprobe"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe(path: Path) -> dict:
    completed = subprocess.run(
        [
            str(FFPROBE),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,nb_frames,duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    stream = json.loads(completed.stdout)["streams"][0]
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": float(Fraction(stream["r_frame_rate"])),
        "duration": float(stream.get("duration") or 0),
        "nb_frames": int(stream["nb_frames"]) if stream.get("nb_frames") else None,
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--start", type=float, required=True)
    parser.add_argument("--end", type=float, required=True)
    parser.add_argument("--x", type=int, required=True)
    parser.add_argument("--y", type=int, required=True)
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--value-min", type=int, default=185)
    parser.add_argument("--saturation-max", type=int, default=90)
    parser.add_argument("--dilate", type=int, default=2)
    parser.add_argument("--inpaint-radius", type=float, default=4.0)
    args = parser.parse_args()

    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    receipt = Path(args.receipt).resolve()
    if not source.is_file():
        raise SystemExit(f"Input video does not exist: {source}")
    if output.exists():
        raise SystemExit(f"Output already exists: {output}")
    if args.end <= args.start:
        raise SystemExit("--end must be greater than --start")

    media = probe(source)
    x1, y1 = args.x, args.y
    x2, y2 = x1 + args.width, y1 + args.height
    if not (0 <= x1 < x2 <= media["width"] and 0 <= y1 < y2 <= media["height"]):
        raise SystemExit("Caption ROI lies outside the video frame")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.partial.mp4")
    temporary.unlink(missing_ok=True)
    frame_bytes = media["width"] * media["height"] * 3
    decoder = subprocess.Popen(
        [str(FFMPEG), "-v", "error", "-i", str(source), "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"],
        stdout=subprocess.PIPE,
    )
    encoder = subprocess.Popen(
        [
            str(FFMPEG),
            "-v",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{media['width']}x{media['height']}",
            "-r",
            f"{media['fps']:.12g}",
            "-i",
            "pipe:0",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "1:a?",
            "-c:v",
            "libx264",
            "-preset",
            "slow",
            "-crf",
            "16",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            "-y",
            str(temporary),
        ],
        stdin=subprocess.PIPE,
    )

    repaired_frames = 0
    masked_pixels = []
    frame_index = 0
    kernel = np.ones((3, 3), np.uint8)
    try:
        assert decoder.stdout is not None
        assert encoder.stdin is not None
        while True:
            raw = decoder.stdout.read(frame_bytes)
            if not raw:
                break
            if len(raw) != frame_bytes:
                raise RuntimeError(f"Truncated decoded frame {frame_index}: {len(raw)} bytes")
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((media["height"], media["width"], 3)).copy()
            timestamp = frame_index / media["fps"]
            if args.start <= timestamp <= args.end:
                region = frame[y1:y2, x1:x2]
                hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
                mask = cv2.inRange(
                    hsv,
                    np.array([0, 0, args.value_min], dtype=np.uint8),
                    np.array([179, args.saturation_max, 255], dtype=np.uint8),
                )
                if args.dilate:
                    mask = cv2.dilate(mask, kernel, iterations=args.dilate)
                count = int(np.count_nonzero(mask))
                if count:
                    frame[y1:y2, x1:x2] = cv2.inpaint(region, mask, args.inpaint_radius, cv2.INPAINT_TELEA)
                    repaired_frames += 1
                    masked_pixels.append(count)
            encoder.stdin.write(frame.tobytes())
            frame_index += 1
    finally:
        if decoder.stdout:
            decoder.stdout.close()
        if encoder.stdin:
            encoder.stdin.close()
    decoder_code = decoder.wait()
    encoder_code = encoder.wait()
    if decoder_code or encoder_code or not temporary.is_file() or temporary.stat().st_size == 0:
        temporary.unlink(missing_ok=True)
        raise SystemExit(f"Video repair failed: decoder={decoder_code}, encoder={encoder_code}")
    temporary.replace(output)

    output_media = probe(output)
    payload = {
        "schema": "qingshan.generated_caption_pixel_inpaint_receipt.v1",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "REPAIRED_PENDING_VISUAL_OCR_ASR_QA",
        "input": {"path": str(source), "sha256": sha256(source), **media},
        "output": {"path": str(output), "sha256": sha256(output), **output_media},
        "repair": {
            "time_window_seconds": [args.start, args.end],
            "roi": {"x": x1, "y": y1, "width": args.width, "height": args.height},
            "white_glyph_mask": {
                "value_min": args.value_min,
                "saturation_max": args.saturation_max,
                "dilate_iterations": args.dilate,
                "inpaint_radius": args.inpaint_radius,
            },
            "decoded_frames": frame_index,
            "repaired_frames": repaired_frames,
            "masked_pixels_min": min(masked_pixels) if masked_pixels else 0,
            "masked_pixels_max": max(masked_pixels) if masked_pixels else 0,
        },
        "audio": {"operation": "BITSTREAM_COPY_FROM_INPUT", "content_changed": False},
        "rollback": str(source),
        "release_eligible": False,
    }
    write_json(receipt, payload)
    print(json.dumps({"status": payload["status"], "output": str(output), "repaired_frames": repaired_frames}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
