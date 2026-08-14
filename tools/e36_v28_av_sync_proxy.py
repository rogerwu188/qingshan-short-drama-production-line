#!/usr/bin/env python3
"""Read-only audiovisual sync proxy for E36 V28.

This is intentionally a proxy, not a promotion gate: it measures visible lower-face
motion against the audio envelope and records exact-candidate provenance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import tempfile
import wave
from pathlib import Path

import cv2
import numpy as np


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audio_envelope(video: Path, sample_rate: int, sample_times: np.ndarray) -> np.ndarray:
    with tempfile.TemporaryDirectory(prefix="e36-av-sync-") as tmpdir:
        wav_path = Path(tmpdir) / "audio.wav"
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(video),
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-c:a",
                "pcm_s16le",
                str(wav_path),
            ],
            check=True,
        )
        with wave.open(str(wav_path), "rb") as wav_file:
            pcm = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)
    audio = pcm.astype(np.float32) / 32768.0
    window = max(1, int(sample_rate * 0.10))
    values = []
    for timestamp in sample_times:
        center = int(timestamp * sample_rate)
        start = max(0, center - window // 2)
        end = min(len(audio), center + window // 2)
        if end <= start:
            values.append(0.0)
            continue
        chunk = audio[start:end]
        values.append(float(np.sqrt(np.mean(chunk * chunk) + 1e-12)))
    return np.asarray(values, dtype=np.float32)


def normalized(values: np.ndarray) -> np.ndarray:
    if len(values) == 0:
        return values
    lo, hi = np.percentile(values, [5, 95])
    return np.clip((values - lo) / max(float(hi - lo), 1e-6), 0.0, 1.0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--sample-fps", type=float, default=8.0)
    args = parser.parse_args()

    cap = cv2.VideoCapture(str(args.video))
    source_fps = float(cap.get(cv2.CAP_PROP_FPS))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = frame_count / source_fps
    detection_width = min(width, 480)
    detection_height = max(1, int(round(height * detection_width / width)))
    detector = cv2.FaceDetectorYN.create(
        str(args.model), "", (detection_width, detection_height), 0.75, 0.3, 5000
    )

    sample_stride = max(1, int(round(source_fps / args.sample_fps)))
    sampled_frame_numbers = np.arange(0, frame_count, sample_stride, dtype=np.int64)
    sample_times = sampled_frame_numbers.astype(np.float64) / source_fps
    mouth_motion = np.full(len(sample_times), np.nan, dtype=np.float32)
    face_scores = np.full(len(sample_times), np.nan, dtype=np.float32)
    previous_mouth = None
    previous_center = None
    previous_time = None
    face_frames = 0
    tracked_pairs = 0

    next_sample = 0
    frame_number = 0
    while next_sample < len(sample_times):
        ok, frame = cap.read()
        if not ok:
            break
        if frame_number != int(sampled_frame_numbers[next_sample]):
            frame_number += 1
            continue
        index = next_sample
        timestamp = float(sample_times[index])
        next_sample += 1
        frame_number += 1
        detection_frame = cv2.resize(
            frame, (detection_width, detection_height), interpolation=cv2.INTER_AREA
        )
        _, faces = detector.detect(detection_frame)
        if faces is None or len(faces) == 0:
            previous_mouth = previous_center = previous_time = None
            continue
        face = max(faces, key=lambda item: float(item[2] * item[3]))
        x, y, w, h = [float(value) for value in face[:4]]
        face_scores[index] = float(face[-1])
        face_frames += 1
        mouth_x = (float(face[10]) + float(face[12])) / 2.0
        mouth_y = (float(face[11]) + float(face[13])) / 2.0
        roi_w = max(12, int(w * 0.42))
        roi_h = max(10, int(h * 0.25))
        x0 = min(detection_frame.shape[1] - 1, max(0, int(mouth_x - roi_w / 2)))
        x1 = min(detection_frame.shape[1], x0 + roi_w)
        y0 = min(detection_frame.shape[0] - 1, max(0, int(mouth_y - roi_h * 0.30)))
        y1 = min(detection_frame.shape[0], y0 + roi_h)
        mouth = cv2.cvtColor(detection_frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        if mouth.size == 0:
            previous_mouth = previous_center = previous_time = None
            continue
        mouth = cv2.resize(mouth, (64, 32), interpolation=cv2.INTER_AREA)
        mouth = cv2.equalizeHist(mouth)
        center = np.asarray([x + w / 2.0, y + h / 2.0], dtype=np.float32)
        stable_track = (
            previous_mouth is not None
            and previous_time is not None
            and timestamp - previous_time <= (1.5 / args.sample_fps)
            and np.linalg.norm(center - previous_center) <= max(w, h) * 0.18
        )
        if stable_track:
            mouth_motion[index] = float(np.mean(cv2.absdiff(mouth, previous_mouth)) / 255.0)
            tracked_pairs += 1
        previous_mouth = mouth
        previous_center = center
        previous_time = timestamp
    cap.release()

    audio_rms = audio_envelope(args.video, 16000, sample_times)
    valid = np.isfinite(mouth_motion)
    motion_norm = normalized(mouth_motion[valid])
    audio_norm = normalized(audio_rms[valid])
    correlation = float(np.corrcoef(motion_norm, audio_norm)[0, 1]) if valid.sum() > 10 else None
    speech_threshold = float(np.percentile(audio_norm, 55)) if len(audio_norm) else 1.0
    speech = audio_norm >= speech_threshold
    speech_motion = float(np.mean(motion_norm[speech])) if np.any(speech) else None
    silence_motion = float(np.mean(motion_norm[~speech])) if np.any(~speech) else None
    ratio = (
        float(speech_motion / max(silence_motion, 1e-6))
        if speech_motion is not None and silence_motion is not None
        else None
    )

    lag_results = []
    if len(motion_norm) > 20:
        max_shift = int(round(args.sample_fps * 0.5))
        for shift in range(-max_shift, max_shift + 1):
            if shift < 0:
                left, right = motion_norm[-shift:], audio_norm[:shift]
            elif shift > 0:
                left, right = motion_norm[:-shift], audio_norm[shift:]
            else:
                left, right = motion_norm, audio_norm
            if len(left) > 10:
                lag_results.append((shift / args.sample_fps, float(np.corrcoef(left, right)[0, 1])))
    best_lag = max(lag_results, key=lambda item: item[1]) if lag_results else (None, None)

    face_coverage = face_frames / max(len(sample_times), 1)
    tracked_coverage = tracked_pairs / max(len(sample_times), 1)
    proxy_status = "INCONCLUSIVE"
    if tracked_coverage >= 0.15 and ratio is not None:
        proxy_status = "PASS_PROXY" if ratio >= 1.05 and abs(best_lag[0] or 0.0) <= 0.375 else "REVIEW_PROXY"

    result = {
        "schema": "qingshan.e36.av_sync_proxy.v1",
        "candidate": {
            "path": str(args.video),
            "sha256": sha256(args.video),
            "duration_seconds": duration,
            "source_fps": source_fps,
            "frame_count": frame_count,
            "resolution": [width, height],
        },
        "detector": {
            "kind": "opencv_yunet_lower_face_motion_audio_envelope_proxy",
            "model_path": str(args.model),
            "model_sha256": sha256(args.model),
            "sample_fps": args.sample_fps,
            "detection_resolution": [detection_width, detection_height],
        },
        "measurements": {
            "sample_count": len(sample_times),
            "face_frames": face_frames,
            "face_coverage": face_coverage,
            "tracked_mouth_motion_pairs": tracked_pairs,
            "tracked_coverage": tracked_coverage,
            "mouth_audio_zero_lag_correlation": correlation,
            "speech_motion_mean_normalized": speech_motion,
            "silence_motion_mean_normalized": silence_motion,
            "speech_to_silence_motion_ratio": ratio,
            "best_audio_relative_lag_seconds": best_lag[0],
            "best_lag_correlation": best_lag[1],
        },
        "gate_results": {
            "proxy_status": proxy_status,
            "promotion_clearance": "NOT_GRANTED",
            "continuous_human_audiovisual_watch": "STILL_REQUIRED",
        },
        "limitations": [
            "Largest detected face is used and may not always be the active speaker.",
            "Lower-face pixel motion is a proxy, not phoneme-level audiovisual synchronization.",
            "This result cannot override a human intuitive audiovisual FAIL or clear promotion.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["measurements"], indent=2))
    print(proxy_status)


if __name__ == "__main__":
    main()
