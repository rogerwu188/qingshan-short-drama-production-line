#!/usr/bin/env python3
import json
import math
import os
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


VIDEO = Path("/Users/rogerwu/Downloads/参考视频1.mp4")
OUT = Path("/Users/rogerwu/qingshan_short_drama/qa/reference_video_1_20260712")
FFMPEG = Path("/tmp/qingshan_video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1")
W, H, SAMPLE_FPS = 213, 120, 2.0


def frame_stream():
    command = [
        str(FFMPEG), "-v", "error", "-i", str(VIDEO), "-an",
        "-vf", f"fps={SAMPLE_FPS},scale={W}:{H}", "-pix_fmt", "rgb24",
        "-f", "rawvideo", "pipe:1",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE)
    size = W * H * 3
    index = 0
    while True:
        data = process.stdout.read(size)
        if len(data) != size:
            break
        yield index / SAMPLE_FPS, np.frombuffer(data, np.uint8).reshape(H, W, 3)
        index += 1
    process.stdout.close()
    process.wait()


def save_frame(frame, timestamp, label):
    image = Image.fromarray(frame)
    canvas = Image.new("RGB", (W * 2, H * 2 + 28), "white")
    canvas.paste(image.resize((W * 2, H * 2)), (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((6, H * 2 + 6), f"{timestamp:08.1f}s  {label}", fill="black")
    path = OUT / "frames" / f"{label}_{timestamp:08.1f}.jpg"
    canvas.save(path, quality=90)
    return path


def make_contact_sheet(paths, output, columns=4):
    if not paths:
        return
    thumbs = [Image.open(path).convert("RGB") for path in paths]
    cell_w = max(image.width for image in thumbs)
    cell_h = max(image.height for image in thumbs)
    rows = math.ceil(len(thumbs) / columns)
    sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "white")
    for index, image in enumerate(thumbs):
        sheet.paste(image, ((index % columns) * cell_w, (index // columns) * cell_h))
    sheet.save(output, quality=92)


def main():
    (OUT / "frames").mkdir(parents=True, exist_ok=True)
    metrics = []
    minute_frames = []
    segment_frames = []
    detail_frames = []
    prev_gray = None
    prev_hist = None
    last_minute = -1
    last_segment = -1

    for timestamp, frame in frame_stream():
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        hist = cv2.calcHist([gray], [0], None, [32], [0, 256])
        cv2.normalize(hist, hist)
        if prev_gray is None:
            pixel_diff = 0.0
            hist_diff = 0.0
        else:
            pixel_diff = float(cv2.absdiff(gray, prev_gray).mean())
            hist_diff = float(cv2.compareHist(prev_hist, hist, cv2.HISTCMP_BHATTACHARYYA))
        metrics.append((timestamp, pixel_diff, hist_diff, float(gray.mean())))

        minute = int(timestamp // 60)
        if minute != last_minute:
            minute_frames.append(save_frame(frame, timestamp, "minute"))
            last_minute = minute
        segment = int(timestamp // 600)
        if segment != last_segment:
            segment_frames.append(save_frame(frame, timestamp, "segment"))
            last_segment = segment
        if timestamp <= 1200 and abs(timestamp % 10.0) < 0.01:
            detail_frames.append(save_frame(frame, timestamp, "detail"))

        prev_gray, prev_hist = gray, hist

    array = np.array(metrics, dtype=np.float64)
    pixel = array[:, 1]
    hist = array[:, 2]
    cut_score = pixel / max(np.percentile(pixel, 95), 1e-6) + hist / max(np.percentile(hist, 95), 1e-6)
    threshold = float(np.percentile(cut_score, 94))
    raw_cuts = array[cut_score >= threshold, 0].tolist()
    cuts = []
    for timestamp in raw_cuts:
        if not cuts or timestamp - cuts[-1] >= 0.75:
            cuts.append(float(timestamp))

    intervals = np.diff([0.0] + cuts + [float(array[-1, 0])])
    summary = {
        "source": str(VIDEO),
        "sample_fps": SAMPLE_FPS,
        "duration_seconds": float(array[-1, 0]),
        "sample_count": int(len(array)),
        "cut_threshold_percentile": 94,
        "estimated_cut_count": int(len(cuts)),
        "estimated_asl_seconds": float(np.mean(intervals)),
        "median_shot_seconds": float(np.median(intervals)),
        "shots_under_1_5s_ratio": float(np.mean(intervals < 1.5)),
        "shots_under_3s_ratio": float(np.mean(intervals < 3.0)),
        "motion_mean": float(np.mean(pixel)),
        "motion_p50": float(np.percentile(pixel, 50)),
        "motion_p90": float(np.percentile(pixel, 90)),
        "brightness_mean": float(np.mean(array[:, 3])),
        "brightness_p10": float(np.percentile(array[:, 3], 10)),
        "brightness_p90": float(np.percentile(array[:, 3], 90)),
        "estimated_cuts_seconds": cuts,
    }
    segment_stats = []
    duration = float(array[-1, 0])
    for start in np.arange(0.0, duration, 600.0):
        end = min(start + 600.0, duration)
        sample_mask = (array[:, 0] >= start) & (array[:, 0] < end)
        local_cuts = [value for value in cuts if start <= value < end]
        local_bounds = [start] + local_cuts + [end]
        local_intervals = np.diff(local_bounds)
        segment_stats.append({
            "start_seconds": float(start),
            "end_seconds": float(end),
            "estimated_cut_count": len(local_cuts),
            "estimated_asl_seconds": float(np.mean(local_intervals)),
            "median_shot_seconds": float(np.median(local_intervals)),
            "motion_mean": float(np.mean(array[sample_mask, 1])),
            "brightness_mean": float(np.mean(array[sample_mask, 3])),
        })
    summary["segments_10min"] = segment_stats
    (OUT / "analysis.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # Select high-confidence cut frames spread across the whole sample.
    ranked = sorted(zip(array[:, 0], cut_score), key=lambda item: item[1], reverse=True)
    selected = []
    for timestamp, score in ranked:
        if all(abs(timestamp - old) > 20 for old in selected):
            selected.append(float(timestamp))
        if len(selected) == 48:
            break
    selected.sort()

    cut_paths = []
    selected_set = {round(value * SAMPLE_FPS) for value in selected}
    for timestamp, frame in frame_stream():
        if round(timestamp * SAMPLE_FPS) in selected_set:
            cut_paths.append(save_frame(frame, timestamp, "cut"))

    make_contact_sheet(segment_frames, OUT / "contact_10min.jpg", columns=3)
    make_contact_sheet(minute_frames, OUT / "contact_1min.jpg", columns=4)
    make_contact_sheet(cut_paths, OUT / "contact_cuts.jpg", columns=4)
    for index in range(0, len(detail_frames), 60):
        make_contact_sheet(
            detail_frames[index:index + 60],
            OUT / f"contact_detail_{index // 60 + 1:02d}.jpg",
            columns=4,
        )
    print(json.dumps({key: value for key, value in summary.items() if key != "estimated_cuts_seconds"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
