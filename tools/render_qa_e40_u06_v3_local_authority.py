#!/usr/bin/env python3
"""Render U06 V3 local exact-dialogue sequential-frost performance."""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import wave
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from faster_whisper import WhisperModel
from rapidocr_onnxruntime import RapidOCR


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "working_assets/e40_preproduction_20260814/u06_v2_imagegen_sequential_frost_exact_start_frame_v1/E40_U06_V2_IMAGEGEN_SEQUENTIAL_FROST_EXACT_START_FRAME_720X1280_V1.png"
AUDIO = ROOT / "working_assets/e40_production_20260814/u06_v3_kokoro_exact_audio_candidates_v1/E40-DIA005_zm_009_speed0p92_normalized48k.wav"
AUDIO_QA = ROOT / "qa/e40_production_20260814/u06_v3_kokoro_exact_audio_candidates_v1/E40_U06_V3_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
RIGHTS = ROOT / "qa/e40_preproduction_20260814/u06_v3_kokoro_rights_clearance_v1/E40_U06_V3_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
OUT_DIR = ROOT / "working_assets/e40_production_20260814/u06_v3_local_authority_exact_dialogue_v1"
VIDEO = OUT_DIR / "E40-U06-V3-LOCAL-AUTHORITY-EXACT-DIA005-SEQUENTIAL-FROST.mp4"
QA_DIR = ROOT / "qa/e40_production_20260814/u06_v3_local_authority_exact_dialogue_v1"
FRAME0 = QA_DIR / "frame_0000.png"
CONTACT = QA_DIR / "contact_sheet.png"
OCR_QA = QA_DIR / "E40_U06_V3_FULL_DURATION_OCR_AUDIT_V1.json"
QA = QA_DIR / "E40_U06_V3_LOCAL_AUTHORITY_EXACT_DIALOGUE_MACHINE_QA_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U06_V3_LOCAL_AUTHORITY_EXACT_DIALOGUE_RENDER_20260814.json"
EXPECTED = "当铺、法场、药房、火场——活口一个没留。"
IMAGE_SHA = "0ad054893a14042fefbd3914380d9a889966ec206969482073d4a8150a723e49"
AUDIO_SHA = "bdce82a0157a7286c23d3e307b9959001623dff4d6487170f268e1ced7d0e193"
WHISPER = Path("/Users/rogerwu/.cache/faster-whisper/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FPS, SECONDS = 24, 7.0
FRAMES = int(FPS * SECONDS)
AUDIO_DELAY = 0.4
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")


def now() -> str: return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
def sha(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()
def norm(value: str) -> str: return "".join(HAN.findall(value)).lower()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True); data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode(); fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream: stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    except Exception: Path(temp).unlink(missing_ok=True); raise


def audio_envelope() -> np.ndarray:
    with wave.open(str(AUDIO), "rb") as stream:
        rate, channels = stream.getframerate(), stream.getnchannels(); samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype=np.int16).astype(np.float32)
    if channels > 1: samples = samples.reshape(-1, channels).mean(axis=1)
    values = []
    for index in range(FRAMES):
        local = index / FPS - AUDIO_DELAY
        if local < 0: values.append(0.0); continue
        start, end = int(local * rate), min(len(samples), int((local + 1 / FPS) * rate)); values.append(float(np.sqrt(np.mean(samples[start:end] ** 2))) if end > start else 0.0)
    env = np.asarray(values, dtype=np.float32)
    if env.max() > 0: env /= env.max()
    return np.convolve(env, np.ones(3, dtype=np.float32) / 3.0, mode="same")


def soft_ellipse(shape: tuple[int, int], center: tuple[int, int], axes: tuple[int, int], blur: int) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8); cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1, cv2.LINE_AA); return cv2.GaussianBlur(mask, (blur | 1, blur | 1), 0).astype(np.float32) / 255.0


def mouth(frame: np.ndarray, strength: float) -> np.ndarray:
    if strength <= 0.01: return frame
    h, w = frame.shape[:2]; yy, xx = np.indices((h, w), dtype=np.float32); cx, cy = 363.0, 523.0; radial = ((xx - cx) / 24.0) ** 2 + ((yy - cy) / 13.0) ** 2; influence = np.clip(1.0 - radial, 0.0, 1.0) ** 2
    warped = cv2.remap(frame, xx, yy - (yy - cy) * 0.19 * float(strength) * influence, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT101); mask = soft_ellipse((h, w), (363, 523), (25, 14), 11)[..., None]
    mixed = frame.astype(np.float32) * (1 - mask) + warped.astype(np.float32) * mask; inner = np.zeros((h, w), dtype=np.uint8); cv2.ellipse(inner, (363, 525), (9, max(1, int(1 + 2 * strength))), 0, 0, 360, 255, -1, cv2.LINE_AA); inner = cv2.GaussianBlur(inner, (5, 5), 0).astype(np.float32)[..., None] / 255.0
    return np.clip(mixed * (1 - .32 * inner) + np.array([28, 22, 40], dtype=np.float32) * (.32 * inner), 0, 255).astype(np.uint8)


def progress(t: float, start: float, end: float) -> float:
    if t <= start: return 0.0
    if t >= end: return 1.0
    value = (t - start) / (end - start); return value * value * (3 - 2 * value)


def frost_template(center: tuple[int, int], seed: int, radius: int = 45) -> np.ndarray:
    rng = np.random.default_rng(seed); canvas = np.zeros((1280, 720), dtype=np.float32); cx, cy = center
    arms = 9
    for arm in range(arms):
        angle = 2 * math.pi * arm / arms + rng.uniform(-0.12, .12); points = [(cx, cy)]
        for step in range(1, 7):
            distance = radius * step / 6; points.append((int(cx + math.cos(angle) * distance + rng.uniform(-2, 2)), int(cy + math.sin(angle) * distance * .52 + rng.uniform(-1.5, 1.5))))
        cv2.polylines(canvas, [np.asarray(points, np.int32)], False, 1.0, 2, cv2.LINE_AA)
        for branch in (3, 5):
            bx, by = points[branch]; branch_angle = angle + rng.choice([-1, 1]) * rng.uniform(.55, .85); length = radius * rng.uniform(.18, .30); endpoint = (int(bx + math.cos(branch_angle) * length), int(by + math.sin(branch_angle) * length * .55)); cv2.line(canvas, (bx, by), endpoint, .75, 1, cv2.LINE_AA)
    return cv2.GaussianBlur(canvas, (5, 5), 0)


FROST = [frost_template((330, 1068), 62, 52), frost_template((445, 1066), 63, 50), frost_template((557, 1063), 64, 47)]


def add_frost(frame: np.ndarray, template: np.ndarray, reveal: float) -> np.ndarray:
    if reveal <= 0: return frame
    ys, xs = np.nonzero(template > .01); center_x = float(xs.mean()) if len(xs) else 0; reveal_mask = np.clip((center_x + (reveal * 2 - 1) * 60 - np.indices(template.shape)[1]) / 16 + .5, 0, 1); alpha = np.clip(template * reveal_mask * .85, 0, .75)[..., None]
    color = np.zeros_like(frame, dtype=np.float32); color[:] = (238, 232, 210)
    glow = cv2.GaussianBlur(alpha[..., 0], (19, 19), 0)[..., None]; result = frame.astype(np.float32) * (1 - alpha) + color * alpha; result[:, :, 0] += glow[..., 0] * 18; result[:, :, 1] += glow[..., 0] * 10; return np.clip(result, 0, 255).astype(np.uint8)


def compose(base: np.ndarray, index: int, env: np.ndarray) -> np.ndarray:
    if index == 0: return base.copy()
    t = index / FPS; p = index / (FRAMES - 1); h, w = base.shape[:2]; scale = 1 + .005 * (.5 - .5 * math.cos(math.pi * p)); frame = cv2.warpAffine(base, cv2.getRotationMatrix2D((w / 2, h / 2), 0, scale), (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT101)
    frame = add_frost(frame, FROST[0], progress(t, .35, 1.2)); frame = add_frost(frame, FROST[1], progress(t, 1.55, 2.65)); frame = add_frost(frame, FROST[2], progress(t, 2.85, 4.0)); frame = mouth(frame, float(env[index]))
    warm = frame.astype(np.float32); warm[:, :, 2] *= 1 + .005 * math.sin(2 * math.pi * t * 3.9); return np.clip(warm, 0, 255).astype(np.uint8)


def main() -> int:
    if VIDEO.exists() or QA.exists() or RECEIPT.exists(): raise SystemExit("FAIL_CLOSED_OUTPUT_COLLISION")
    if sha(IMAGE) != IMAGE_SHA or sha(AUDIO) != AUDIO_SHA: raise SystemExit("FAIL_CLOSED_AUTHORITY_OR_AUDIO_SHA")
    if json.loads(AUDIO_QA.read_text(encoding="utf-8")).get("status") != "PASS_MACHINE_SELECTION" or json.loads(RIGHTS.read_text(encoding="utf-8")).get("releaseBlocked") is not False: raise SystemExit("FAIL_CLOSED_AUDIO_OR_RIGHTS")
    base = cv2.imread(str(IMAGE)); env = audio_envelope(); OUT_DIR.mkdir(parents=True, exist_ok=True); QA_DIR.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "720x1280", "-r", str(FPS), "-i", "-", "-i", str(AUDIO), "-filter_complex", f"[1:a]adelay={int(AUDIO_DELAY*1000)}|{int(AUDIO_DELAY*1000)},apad=pad_dur=2[a]", "-map", "0:v", "-map", "[a]", "-t", str(SECONDS), "-c:v", "libx264rgb", "-crf", "0", "-preset", "medium", "-pix_fmt", "rgb24", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(VIDEO)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE); assert process.stdin is not None; selected_frames = []
    for index in range(FRAMES):
        frame = compose(base, index, env); process.stdin.write(frame.tobytes())
        if index in {0, 24, 48, 72, 96, 120, 144, 167}: selected_frames.append(frame)
    process.stdin.close()
    if process.wait() != 0: raise SystemExit("FAIL_RENDER_FFMPEG")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(VIDEO), "-vf", "select=eq(n\\,0)", "-frames:v", "1", str(FRAME0)], check=True); decoded0 = cv2.imread(str(FRAME0)); mae = float(np.mean(np.abs(base.astype(np.float32) - decoded0.astype(np.float32)))); exact = bool(np.array_equal(base, decoded0))
    thumbs = [cv2.resize(frame, (180, 320), interpolation=cv2.INTER_AREA) for frame in selected_frames]; cv2.imwrite(str(CONTACT), np.concatenate([np.concatenate(thumbs[:4], axis=1), np.concatenate(thumbs[4:], axis=1)], axis=0))
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height,r_frame_rate,sample_rate,channels", "-of", "json", str(VIDEO)], capture_output=True, text=True, check=True).stdout)
    model = WhisperModel(str(WHISPER), device="cpu", compute_type="int8", local_files_only=True); segments, _ = model.transcribe(str(VIDEO), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=EXPECTED); transcript = "".join(segment.text.strip() for segment in segments); similarity = difflib.SequenceMatcher(None, norm(EXPECTED), norm(transcript)).ratio()
    ocr_engine = RapidOCR(); recognitions = []
    for idx, frame in enumerate(selected_frames):
        result, _ = ocr_engine(frame)
        for row in result or []:
            box, text, confidence = row
            if float(confidence) >= .5: recognitions.append({"frame_index": [0,24,48,72,96,120,144,167][idx], "box": box, "text": text, "confidence": float(confidence)})
    atomic_json(OCR_QA, {"schema": "qingshan.e40.u06.v3.full_duration_ocr_audit.v1", "status": "PASS" if not recognitions else "FAIL", "engine": "RapidOCR / ONNX Runtime", "sampled_frame_indices": [0,24,48,72,96,120,144,167], "recognitions": recognitions, "confidence_threshold": .5})
    failures = []
    if not exact or mae != 0: failures.append("FRAME0_NOT_PIXEL_EXACT")
    if similarity != 1.0: failures.append("FINAL_MUX_ASR_NOT_EXACT")
    if recognitions: failures.append("OCR_NONZERO")
    if not 6.95 <= float(probe["format"]["duration"]) <= 7.05: failures.append("DURATION_NOT_7S")
    qa = {"schema": "qingshan.e40.u06.v3.local_authority_exact_dialogue.machine_qa.v1", "status": "PASS_MACHINE_HUMAN_PERFORMANCE_QA_PENDING" if not failures else "FAIL", "created_at": now(), "video_path": str(VIDEO.relative_to(ROOT)), "video_sha256": sha(VIDEO), "authority_image_path": str(IMAGE.relative_to(ROOT)), "authority_image_sha256": IMAGE_SHA, "decoded_frame0_path": str(FRAME0.relative_to(ROOT)), "decoded_frame0_sha256": sha(FRAME0), "frame0_pixel_exact": exact, "frame0_mae": mae, "audio_path": str(AUDIO.relative_to(ROOT)), "audio_sha256": AUDIO_SHA, "rights_evidence": str(RIGHTS.relative_to(ROOT)), "rights_evidence_sha256": sha(RIGHTS), "final_asr_transcript": transcript, "final_asr_similarity": round(similarity, 4), "probe": probe, "ocr_qa": str(OCR_QA.relative_to(ROOT)), "ocr_qa_sha256": sha(OCR_QA), "contact_sheet": str(CONTACT.relative_to(ROOT)), "contact_sheet_sha256": sha(CONTACT), "motion_contract": {"frame0_exact": True, "second_frost_completion_seconds": [0.35,1.2], "third_frost_growth_seconds": [1.55,2.65], "fourth_frost_growth_seconds": [2.85,4.0], "mouth_animation": "delayed-audio-envelope-local-deformation", "provider_pixels_reused": False, "provider_audio_reused": False}, "failures": failures}
    atomic_json(QA, qa); atomic_json(RECEIPT, {"schema": "qingshan.e40.u06.v3.local_authority_exact_dialogue.render.v1", "status": qa["status"], "created_at": now(), "video": str(VIDEO.relative_to(ROOT)), "video_sha256": sha(VIDEO), "qa": str(QA.relative_to(ROOT)), "qa_sha256": sha(QA), "provider_posts": 0, "credits": 0})
    print(json.dumps({"status": qa["status"], "video_sha256": sha(VIDEO), "frame0_exact": exact, "asr": transcript, "ocr": len(recognitions), "failures": failures}, ensure_ascii=False)); return 0 if not failures else 2


if __name__ == "__main__": raise SystemExit(main())
