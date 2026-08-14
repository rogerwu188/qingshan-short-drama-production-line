#!/usr/bin/env python3
"""Render U05 V4 from the admitted authority frame and release-clear exact audio."""

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


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "working_assets/e40_preproduction_20260814/u05_v2_imagegen_coherent_exact_start_frame_v1/E40_U05_V2_IMAGEGEN_COHERENT_EXACT_START_FRAME_720X1280_V1.png"
AUDIO = ROOT / "working_assets/e40_production_20260814/u05_v4_kokoro_exact_audio_candidates_v1/E40-DIA004_zm_009_speed1p15_normalized48k.wav"
AUDIO_QA = ROOT / "qa/e40_production_20260814/u05_v4_kokoro_exact_audio_candidates_v1/E40_U05_V4_KOKORO_EXACT_AUDIO_MACHINE_QA_V1.json"
RIGHTS = ROOT / "qa/e40_preproduction_20260814/u05_v4_kokoro_rights_clearance_v1/E40_U05_V4_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
OUT_DIR = ROOT / "working_assets/e40_production_20260814/u05_v4_local_authority_exact_dialogue_v1"
VIDEO = OUT_DIR / "E40-U05-V4-LOCAL-AUTHORITY-EXACT-DIA004.mp4"
QA_DIR = ROOT / "qa/e40_production_20260814/u05_v4_local_authority_exact_dialogue_v1"
FRAME0 = QA_DIR / "frame_0000.png"
CONTACT = QA_DIR / "contact_sheet.png"
QA = QA_DIR / "E40_U05_V4_LOCAL_AUTHORITY_EXACT_DIALOGUE_MACHINE_QA_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U05_V4_LOCAL_AUTHORITY_EXACT_DIALOGUE_RENDER_20260814.json"
EXPECTED = "先请教娘娘——扣他，为何不杀？"
IMAGE_SHA = "4f5205fa8a001b1943a322ee146ec19f4a62c530a9b1286bf921e327c2dbcc7e"
AUDIO_SHA = "457dc79aab993b9d0484132b769552e36aa746b4c9ffb8202ee445deb78afcdc"
WHISPER = Path("/Users/rogerwu/.cache/faster-whisper/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")
FPS = 24
SECONDS = 4.0
FRAMES = int(FPS * SECONDS)
HAN = re.compile(r"[\u3400-\u9fffA-Za-z0-9]")


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(value: str) -> str:
    return "".join(HAN.findall(value)).lower()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def audio_envelope() -> np.ndarray:
    with wave.open(str(AUDIO), "rb") as stream:
        rate = stream.getframerate()
        channels = stream.getnchannels()
        samples = np.frombuffer(stream.readframes(stream.getnframes()), dtype=np.int16).astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    values = []
    for index in range(FRAMES):
        start = int(index * rate / FPS)
        end = min(len(samples), int((index + 1) * rate / FPS))
        values.append(float(np.sqrt(np.mean(np.square(samples[start:end])))) if end > start else 0.0)
    env = np.array(values, dtype=np.float32)
    if env.max() > 0:
        env /= env.max()
    env = np.convolve(env, np.ones(3, dtype=np.float32) / 3.0, mode="same")
    env[:3] *= np.linspace(0.0, 1.0, 3)
    return env


def soft_ellipse(shape: tuple[int, int], center: tuple[int, int], axes: tuple[int, int], blur: int) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    cv2.ellipse(mask, center, axes, 0, 0, 360, 255, -1, cv2.LINE_AA)
    return cv2.GaussianBlur(mask, (blur | 1, blur | 1), 0).astype(np.float32) / 255.0


def mouth_frame(frame: np.ndarray, strength: float) -> np.ndarray:
    if strength <= 0.01:
        return frame
    h, w = frame.shape[:2]
    yy, xx = np.indices((h, w), dtype=np.float32)
    cx, cy = 276.0, 466.0
    radius_x, radius_y = 24.0, 13.0
    radial = ((xx - cx) / radius_x) ** 2 + ((yy - cy) / radius_y) ** 2
    influence = np.clip(1.0 - radial, 0.0, 1.0) ** 2
    open_factor = 0.20 * float(strength)
    map_x = xx
    map_y = yy - (yy - cy) * open_factor * influence
    warped = cv2.remap(frame, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT101)
    mask = soft_ellipse((h, w), (276, 466), (25, 14), 11)[..., None]
    mixed = frame.astype(np.float32) * (1.0 - mask) + warped.astype(np.float32) * mask
    inner = np.zeros((h, w), dtype=np.uint8)
    cv2.ellipse(inner, (276, 468), (9, max(1, int(1 + 2.0 * strength))), 0, 0, 360, 255, -1, cv2.LINE_AA)
    inner = cv2.GaussianBlur(inner, (5, 5), 0).astype(np.float32)[..., None] / 255.0
    mouth_color = np.array([28, 22, 40], dtype=np.float32)
    mixed = mixed * (1.0 - 0.32 * inner) + mouth_color * (0.32 * inner)
    return np.clip(mixed, 0, 255).astype(np.uint8)


def page_hand_motion(frame: np.ndarray, t: float) -> np.ndarray:
    h, w = frame.shape[:2]
    dx = 1.6 * math.sin(2 * math.pi * t / 1.7)
    dy = 1.2 * math.sin(2 * math.pi * t / 1.15 + 0.7)
    moved = cv2.warpAffine(frame, np.float32([[1, 0, dx], [0, 1, dy]]), (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT101)
    mask = np.zeros((h, w), dtype=np.uint8)
    polygon = np.array([[105, 790], [360, 800], [470, 1125], [110, 1140]], dtype=np.int32)
    cv2.fillConvexPoly(mask, polygon, 255, cv2.LINE_AA)
    mask = cv2.GaussianBlur(mask, (41, 41), 0).astype(np.float32)[..., None] / 255.0
    return np.clip(frame.astype(np.float32) * (1.0 - mask) + moved.astype(np.float32) * mask, 0, 255).astype(np.uint8)


def compose(base: np.ndarray, index: int, env: np.ndarray) -> np.ndarray:
    if index == 0:
        return base.copy()
    t = index / FPS
    progress = index / (FRAMES - 1)
    h, w = base.shape[:2]
    scale = 1.0 + 0.006 * (0.5 - 0.5 * math.cos(math.pi * progress))
    camera = cv2.warpAffine(base, cv2.getRotationMatrix2D((w / 2, h / 2), 0, scale), (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT101)
    camera = page_hand_motion(camera, t)
    camera = mouth_frame(camera, float(env[index]))
    flicker = 1.0 + 0.006 * math.sin(2 * math.pi * t * 3.7) + 0.003 * math.sin(2 * math.pi * t * 6.1)
    warm = camera.astype(np.float32)
    warm[:, :, 2] *= flicker
    return np.clip(warm, 0, 255).astype(np.uint8)


def main() -> int:
    if VIDEO.exists() or QA.exists() or RECEIPT.exists():
        raise SystemExit("FAIL_CLOSED_OUTPUT_COLLISION")
    if sha(IMAGE) != IMAGE_SHA or sha(AUDIO) != AUDIO_SHA:
        raise SystemExit("FAIL_CLOSED_AUTHORITY_OR_AUDIO_SHA")
    audio_qa = json.loads(AUDIO_QA.read_text(encoding="utf-8"))
    rights = json.loads(RIGHTS.read_text(encoding="utf-8"))
    if audio_qa.get("status") != "PASS_MACHINE_SELECTION_HUMAN_LISTEN_PENDING" or rights.get("releaseBlocked") is not False:
        raise SystemExit("FAIL_CLOSED_AUDIO_OR_RIGHTS_GATE")
    base = cv2.imread(str(IMAGE), cv2.IMREAD_COLOR)
    if base is None or base.shape[:2] != (1280, 720):
        raise SystemExit("FAIL_CLOSED_IMAGE_GEOMETRY")
    env = audio_envelope()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", "720x1280", "-r", str(FPS), "-i", "-", "-i", str(AUDIO), "-filter_complex", "[1:a]apad=pad_dur=0.5[a]", "-map", "0:v", "-map", "[a]", "-t", str(SECONDS), "-c:v", "libx264rgb", "-crf", "0", "-preset", "medium", "-pix_fmt", "rgb24", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(VIDEO)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE)
    assert process.stdin is not None
    frames = []
    for index in range(FRAMES):
        frame = compose(base, index, env)
        process.stdin.write(frame.tobytes())
        if index in {0, 12, 24, 36, 48, 60, 72, 84}:
            frames.append(frame)
    process.stdin.close()
    if process.wait() != 0:
        raise SystemExit("FAIL_RENDER_FFMPEG")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(VIDEO), "-vf", "select=eq(n\\,0)", "-frames:v", "1", str(FRAME0)], check=True)
    decoded0 = cv2.imread(str(FRAME0), cv2.IMREAD_COLOR)
    mae = float(np.mean(np.abs(base.astype(np.float32) - decoded0.astype(np.float32))))
    exact = bool(np.array_equal(base, decoded0))
    thumbs = [cv2.resize(frame, (180, 320), interpolation=cv2.INTER_AREA) for frame in frames]
    contact = np.concatenate(thumbs[:4], axis=1)
    contact2 = np.concatenate(thumbs[4:], axis=1)
    cv2.imwrite(str(CONTACT), np.concatenate([contact, contact2], axis=0))
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_name,width,height,r_frame_rate,sample_rate,channels", "-of", "json", str(VIDEO)], capture_output=True, text=True, check=True).stdout)
    model = WhisperModel(str(WHISPER), device="cpu", compute_type="int8", local_files_only=True)
    segments, _ = model.transcribe(str(VIDEO), language="zh", vad_filter=True, beam_size=5, initial_prompt="以下是简体中文普通话对白。", hotwords=EXPECTED)
    transcript = "".join(segment.text.strip() for segment in segments)
    similarity = difflib.SequenceMatcher(None, norm(EXPECTED), norm(transcript)).ratio()
    failures = []
    if not exact or mae != 0.0:
        failures.append("DECODED_FRAME0_NOT_PIXEL_EXACT_AUTHORITY")
    if similarity != 1.0:
        failures.append("FINAL_MUX_ASR_NOT_EXACT")
    duration = float(probe["format"]["duration"])
    if not 3.95 <= duration <= 4.05:
        failures.append("DURATION_NOT_4_SECONDS")
    streams = probe.get("streams", [])
    if not any(row.get("codec_name") == "h264" and row.get("width") == 720 and row.get("height") == 1280 for row in streams):
        failures.append("VIDEO_GEOMETRY_OR_CODEC_FAIL")
    if not any(row.get("codec_name") == "aac" for row in streams):
        failures.append("AAC_AUDIO_MISSING")
    qa = {"schema": "qingshan.e40.u05.v4.local_authority_exact_dialogue.machine_qa.v1", "status": "PASS_MACHINE_HUMAN_PERFORMANCE_QA_PENDING" if not failures else "FAIL", "created_at": now(), "video_path": str(VIDEO.relative_to(ROOT)), "video_sha256": sha(VIDEO), "authority_image_path": str(IMAGE.relative_to(ROOT)), "authority_image_sha256": IMAGE_SHA, "decoded_frame0_path": str(FRAME0.relative_to(ROOT)), "decoded_frame0_sha256": sha(FRAME0), "frame0_pixel_exact": exact, "frame0_mae": mae, "audio_path": str(AUDIO.relative_to(ROOT)), "audio_sha256": AUDIO_SHA, "audio_rights_evidence": str(RIGHTS.relative_to(ROOT)), "audio_rights_evidence_sha256": sha(RIGHTS), "final_asr_transcript": transcript, "final_asr_similarity": round(similarity, 4), "probe": probe, "contact_sheet": str(CONTACT.relative_to(ROOT)), "contact_sheet_sha256": sha(CONTACT), "motion_contract": {"frame0_exact": True, "camera_push_percent": 0.6, "mouth_animation": "audio-envelope-local-deformation", "page_hand_motion": "bounded-soft-mask-translation", "provider_pixels_reused": False, "provider_audio_reused": False}, "failures": failures}
    atomic_json(QA, qa)
    atomic_json(RECEIPT, {"schema": "qingshan.e40.u05.v4.local_authority_exact_dialogue.render.v1", "status": qa["status"], "created_at": now(), "video": str(VIDEO.relative_to(ROOT)), "video_sha256": sha(VIDEO), "qa": str(QA.relative_to(ROOT)), "qa_sha256": sha(QA), "provider_posts": 0, "credits": 0})
    print(json.dumps({"status": qa["status"], "video": str(VIDEO.relative_to(ROOT)), "video_sha256": sha(VIDEO), "frame0_exact": exact, "asr": transcript, "failures": failures}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
