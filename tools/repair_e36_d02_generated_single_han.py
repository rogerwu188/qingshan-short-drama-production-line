#!/usr/bin/env python3
"""Remove the generated single-Han overlay from the accepted E36 D02 join preview."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    args = parser.parse_args()

    source = args.input.resolve()
    output = args.output.resolve()
    report_path = args.report.resolve()
    ffmpeg = args.ffmpeg.resolve()
    if not source.is_file() or not ffmpeg.is_file():
        raise SystemExit("input video or ffmpeg runtime missing")

    capture = cv2.VideoCapture(str(source))
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if abs(fps - 24.0) > 0.01 or (width, height) != (720, 1280):
        raise SystemExit(f"unexpected media geometry: fps={fps}, size={width}x{height}")

    clean_frame_index = round(4.50 * fps)
    capture.set(cv2.CAP_PROP_POS_FRAMES, clean_frame_index)
    ok, clean_frame = capture.read()
    if not ok:
        raise SystemExit("could not read clean pre-overlay frame")
    y0, y1, x0, x1 = 925, 1005, 320, 402
    clean_patch = clean_frame[y0:y1, x0:x1].astype(np.float32)
    patch_height, patch_width = clean_patch.shape[:2]
    yy, xx = np.ogrid[:patch_height, :patch_width]
    edge_distance = np.maximum(
        np.abs(xx - (patch_width - 1) / 2) / (patch_width / 2),
        np.abs(yy - (patch_height - 1) / 2) / (patch_height / 2),
    )
    alpha = (np.clip((1 - edge_distance) / 0.28, 0, 1) ** 1.6)[..., None]

    output.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    repaired_indices: list[int] = []
    with tempfile.TemporaryDirectory(prefix="e36_d02_textclean_") as temporary:
        intermediate = Path(temporary) / "picture_ffv1.mkv"
        writer = cv2.VideoWriter(
            str(intermediate),
            cv2.VideoWriter_fourcc(*"FFV1"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            raise SystemExit("could not open lossless FFV1 writer")
        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            timestamp = index / fps
            if 4.55 <= timestamp <= 5.75:
                target = frame[y0:y1, x0:x1].astype(np.float32)
                frame[y0:y1, x0:x1] = (
                    clean_patch * alpha + target * (1 - alpha)
                ).astype(np.uint8)
                repaired_indices.append(index)
            writer.write(frame)
            index += 1
        writer.release()
        capture.release()
        if index != total_frames:
            raise SystemExit(f"frame count changed while repairing: {index} != {total_frames}")

        subprocess.run(
            [
                str(ffmpeg),
                "-hide_banner",
                "-y",
                "-i",
                str(intermediate),
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-r",
                "24",
                "-c:a",
                "copy",
                "-movflags",
                "+faststart",
                str(output),
            ],
            check=True,
        )

    report = {
        "schema": "qingshan.local_generated_text_repair.v1",
        "episode": "E36",
        "status": "PASS_REPAIRED_NOT_FINAL",
        "source": str(source),
        "source_sha256": sha256(source),
        "output": str(output),
        "output_sha256": sha256(output),
        "repair_scope": "generated single Han character `的` on U20B2B1A robe only",
        "method": "TEMPORALLY_BOUNDED_CLEAN_PREOVERLAY_ROBE_PATCH_FEATHERED_ALPHA_COMPOSITE",
        "clean_source_frame_index": clean_frame_index,
        "clean_source_time_seconds": round(clean_frame_index / fps, 3),
        "repair_window_seconds": [4.55, 5.75],
        "repaired_frame_indices": repaired_indices,
        "repaired_frame_count": len(repaired_indices),
        "video_geometry": {"width": width, "height": height, "fps": fps},
        "audio_policy": "BITSTREAM_COPY_FROM_UNCHANGED_JOIN_PREVIEW",
        "new_generation_credits": 0,
        "rollback": str(source),
        "next_action": "Run decode, cadence, OCR, no-prompt ordered ASR and visual join QA on the repaired preview.",
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "output": str(output), "report": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
