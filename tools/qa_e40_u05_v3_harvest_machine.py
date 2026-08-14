#!/usr/bin/env python3
"""Machine audiovisual QA for harvested E40 U05 V3."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
from faster_whisper import WhisperModel
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "working_assets/e40_production_20260814/u05_v3_fast720/E40-U05-V3-FAST720-ADMITTED-FRAME-NATIVE-EXACT-DIA004-V1_36e91c3b-0c31-4e65-9146-a2d6c26bf092.mp4"
QA_DIR = ROOT / "qa/e40_production_20260814/u05_v3_fast720_harvest_qa_v1"
OUT = QA_DIR / "E40_U05_V3_MACHINE_AUDIOVISUAL_QA_V1.json"
CONTACT = QA_DIR / "E40_U05_V3_ORIGINAL_RES_CONTACT_SHEET_V1.jpg"
EXPECTED = "先请教娘娘——扣他，为何不杀？"
MODEL_PATH = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", text))


def main() -> int:
    QA_DIR.mkdir(parents=True, exist_ok=True)
    capture = cv2.VideoCapture(str(VIDEO))
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = count / fps if fps else 0.0
    samples: list[Image.Image] = []
    sampled_rows = []
    for index, ratio in enumerate(np.linspace(0.0, 0.95, 8)):
        frame_number = min(max(count - 1, 0), int(round((count - 1) * float(ratio))))
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ok, frame = capture.read()
        if not ok:
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        image.thumbnail((270, 480))
        samples.append(image)
        sampled_rows.append({"frame": frame_number, "time_seconds": round(frame_number / fps, 3) if fps else 0.0})
    capture.release()
    canvas = Image.new("RGB", (270 * 4, 520 * 2), "black")
    draw = ImageDraw.Draw(canvas)
    for index, (image, row) in enumerate(zip(samples, sampled_rows)):
        x = (index % 4) * 270
        y = (index // 4) * 520
        canvas.paste(image, (x, y))
        draw.text((x + 6, y + 486), f"{row['time_seconds']:.3f}s", fill="white")
    canvas.save(CONTACT, quality=94)

    model = WhisperModel(str(MODEL_PATH), device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(VIDEO), language="zh", vad_filter=True, beam_size=5)
    transcript = "".join(segment.text.strip() for segment in segments)
    expected_norm = normalize(EXPECTED)
    transcript_norm = normalize(transcript)
    similarity = SequenceMatcher(None, expected_norm, transcript_norm).ratio()

    pcm = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(VIDEO), "-map", "0:a:0", "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    audio = np.frombuffer(pcm, dtype=np.float32)
    rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    failures = []
    if width != 720 or height != 1280 or not (23.9 <= fps <= 24.1) or not (3.9 <= duration <= 4.2):
        failures.append("TECHNICAL_STREAM_CONTRACT_FAIL")
    if rms < 0.001 or peak < 0.01:
        failures.append("PROVIDER_NATIVE_AUDIO_ABSENT_OR_TOO_LOW")
    if transcript_norm != expected_norm:
        failures.append("EXACT_NATIVE_DIALOGUE_ASR_FAIL")
    payload = {
        "schema": "qingshan.e40.u05.v3.machine_audiovisual_qa.v1",
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_MACHINE_PENDING_HUMAN" if not failures else "FAIL",
        "video": str(VIDEO.relative_to(ROOT)),
        "video_sha256": sha256(VIDEO),
        "technical": {"fps": fps, "frame_count": count, "duration_seconds": duration, "width": width, "height": height},
        "audio": {"sample_rate_hz": 16000, "mono_sample_count": int(audio.size), "rms": rms, "peak": peak, "language_probability": getattr(info, "language_probability", None)},
        "dialogue": {"speaker": "陈迹", "expected_text": EXPECTED, "expected_normalized": expected_norm, "transcript": transcript, "transcript_normalized": transcript_norm, "similarity": similarity, "exact_match": transcript_norm == expected_norm},
        "contact_sheet": str(CONTACT.relative_to(ROOT)),
        "contact_sheet_sha256": sha256(CONTACT),
        "sampled_frames": sampled_rows,
        "human_review_required": ["single visible Chenji speaker", "visible mouth synchronized to the one exact line", "exactly two blank pages", "natural 1x action", "no owner/count drift", "no readable text"],
        "failures": failures,
        "admission_allowed": False,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "transcript": transcript, "similarity": similarity, "failures": failures, "out": str(OUT)}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
