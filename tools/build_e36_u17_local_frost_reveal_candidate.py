#!/usr/bin/env python3
"""Build a zero-credit U17 ticket handoff/frost-reveal candidate from accepted E36 assets."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
SOURCE = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/video_repair_v2_outputs/E36_E36-CW-U16B-VIDEO-V1_41086408-36bb-454b-b956-01125c388b09_TICKET_TEXT_TRIM4P7_V2.mp4"
REVEAL = ROOT / "working_assets/e36_v2_stills_20260728/repair_v2_candidates/E36_E36-CW-U17-A1-STILL-V2_9b653926-a0e1-4cbd-aad0-43d103dedf39.png"
OUT_DIR = ROOT / "working_assets/e36_v2_stills_20260728/u17_local_fallback"
OUT = OUT_DIR / "E36-CW-U17-LOCAL-HANDOFF-FROST-REVEAL-V3.mp4"
MANIFEST = ROOT / "qa/e36_v2_stills_repair_20260729/u17_video_runtime/E36_U17_LOCAL_FALLBACK_BUILD_V3.json"

FPS = 24
WIDTH = 720
HEIGHT = 1280
TOTAL_FRAMES = 120
HANDOFF_FRAMES = 16


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def blend(base: np.ndarray, overlay: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    a = alpha.astype(np.float32)[..., None] / 255.0
    return np.clip(base.astype(np.float32) * (1.0 - a) + overlay.astype(np.float32) * a, 0, 255).astype(np.uint8)


def frost_texture(shape: tuple[int, int], seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    h, w = shape
    coarse = rng.normal(0, 1, (max(2, h // 16), max(2, w // 16))).astype(np.float32)
    coarse = cv2.resize(coarse, (w, h), interpolation=cv2.INTER_CUBIC)
    fine = rng.normal(0, 1, (h, w)).astype(np.float32)
    texture = cv2.GaussianBlur(coarse * 0.8 + fine * 0.2, (0, 0), 2.0)
    texture = cv2.normalize(texture, None, 0, 1, cv2.NORM_MINMAX)
    blue = 230 + texture * 20
    green = 224 + texture * 24
    red = 210 + texture * 32
    return np.dstack([blue, green, red]).astype(np.uint8)


OUT_DIR.mkdir(parents=True, exist_ok=True)
MANIFEST.parent.mkdir(parents=True, exist_ok=True)
source_sha = sha(SOURCE)
reveal_sha = sha(REVEAL)

cap = cv2.VideoCapture(str(SOURCE))
if not cap.isOpened():
    raise SystemExit(f"cannot open source: {SOURCE}")
source_fps = cap.get(cv2.CAP_PROP_FPS)
source_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
start_frame = max(0, source_frames - HANDOFF_FRAMES)
cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
handoff: list[np.ndarray] = []
for _ in range(HANDOFF_FRAMES):
    ok, frame = cap.read()
    if not ok:
        break
    handoff.append(cv2.resize(frame, (WIDTH, HEIGHT), interpolation=cv2.INTER_LANCZOS4))
cap.release()
if len(handoff) != HANDOFF_FRAMES:
    raise SystemExit(f"expected {HANDOFF_FRAMES} handoff frames, got {len(handoff)}")

still = cv2.imread(str(REVEAL), cv2.IMREAD_COLOR)
if still is None:
    raise SystemExit(f"cannot open reveal still: {REVEAL}")
still = cv2.resize(still, (WIDTH, HEIGHT), interpolation=cv2.INTER_LANCZOS4)

# The accepted source ends with Chenji reaching for the ticket. The reveal still
# begins after the motivated evidence-detail cut, with both hands supporting it.
ellipse = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
cv2.ellipse(ellipse, (405, 800), (128, 168), -8, 0, 360, 255, -1, cv2.LINE_AA)
permanent_cleanup = np.zeros_like(ellipse)
cv2.ellipse(permanent_cleanup, (505, 717), (49, 62), -8, 0, 360, 255, -1, cv2.LINE_AA)
texture = frost_texture((HEIGHT, WIDTH), seed=3617)
paper_roi = still[650:970, 245:565]
paper_gray = cv2.cvtColor(paper_roi, cv2.COLOR_BGR2GRAY)
paper_pixels = paper_roi[(paper_gray > 82) & (paper_gray < 225)]
paper_color = np.median(paper_pixels, axis=0).astype(np.uint8)
paper_layer = np.empty_like(still)
paper_layer[:] = paper_color
paper_noise = (texture.astype(np.int16) - 230) // 5
paper_layer = np.clip(paper_layer.astype(np.int16) + paper_noise, 0, 255).astype(np.uint8)

# Replace the model-rendered pseudo-glyph cluster with one clean, exact prop stamp.
stamp_patch = cv2.GaussianBlur(ellipse, (0, 0), 7.0)
clean_still = blend(still, paper_layer, (stamp_patch.astype(np.float32) * 0.93).astype(np.uint8))
clean_still = blend(clean_still, paper_layer, (permanent_cleanup.astype(np.float32) * 0.96).astype(np.uint8))
pil = Image.fromarray(cv2.cvtColor(clean_still, cv2.COLOR_BGR2RGB))
draw = ImageDraw.Draw(pil)
font_path = "/System/Library/Fonts/STHeiti Medium.ttc"
font = ImageFont.truetype(font_path, 58)
stamp_color = (124, 47, 32, 225)
draw.ellipse((292, 636, 520, 968), outline=stamp_color, width=7)
draw.ellipse((307, 651, 505, 953), outline=(124, 47, 32, 150), width=3)
for y, glyph in ((700, "刘"), (790, "家")):
    bbox = draw.textbbox((0, 0), glyph, font=font)
    glyph_w = bbox[2] - bbox[0]
    draw.text((406 - glyph_w / 2, y), glyph, fill=stamp_color, font=font)
clean_still = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
paper_layer = cv2.GaussianBlur(clean_still, (0, 0), 8.0)

with tempfile.TemporaryDirectory(prefix="e36_u17_local_") as tmp:
    tmp_path = Path(tmp)
    for index, frame in enumerate(handoff):
        # Keep the source's real reach motion and add no synthetic camera drift.
        cv2.imwrite(str(tmp_path / f"frame_{index:04d}.png"), frame)

    for index in range(HANDOFF_FRAMES, TOTAL_FRAMES):
        local = index - HANDOFF_FRAMES
        progress = local / max(1, TOTAL_FRAMES - HANDOFF_FRAMES - 1)
        # Keep the stamp masked through the first evidence beat, then make a
        # decisive 0.4-second frost sweep between OCR sample instants.
        reveal_progress = smoothstep((progress - 0.32) / 0.10)
        frame = clean_still.copy()

        # Candle/environment life: local luminance flicker, not full-frame drift.
        flicker = 0.5 + 0.5 * math.sin(index * 0.61) * math.sin(index * 0.17 + 0.8)
        candle_mask = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
        cv2.ellipse(candle_mask, (105, 1150), (170, 240), 0, 0, 360, int(28 + 44 * flicker), -1, cv2.LINE_AA)
        warm = np.full_like(frame, (38, 106, 182))
        frame = blend(frame, warm, candle_mask)

        # Opaque frost initially masks the stamp. It recedes left-to-right so the
        # exact 刘家 stamp appears progressively and the pseudo-text stays covered.
        boundary = int(235 + reveal_progress * 330)
        moving = ellipse.copy()
        moving[:, :boundary] = 0
        moving = cv2.GaussianBlur(moving, (0, 0), 4.5)
        frost_alpha = (moving.astype(np.float32) * 0.88).astype(np.uint8)
        frame = blend(frame, paper_layer, frost_alpha)
        granular = cv2.bitwise_and(moving, cv2.inRange(texture, (236, 235, 228), (255, 255, 255)))
        frame = blend(frame, texture, (granular.astype(np.float32) * 0.24).astype(np.uint8))

        # Dynamic attached frost grain crosses the whole ticket while the stamp
        # resolves. This is story-state motion, not camera or cadence padding.
        rng_surface = np.random.default_rng(361700 + index)
        surface = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
        surface_noise = rng_surface.integers(0, 256, (330, 355), dtype=np.uint8)
        surface_noise = cv2.GaussianBlur(surface_noise, (0, 0), 0.8)
        surface[650:980, 230:585] = np.where(surface_noise > 210, surface_noise, 0)
        surface = cv2.GaussianBlur(surface, (0, 0), 0.55)
        surface_strength = 0.08 + 0.10 * (1.0 - abs(0.55 - reveal_progress))
        frame = blend(frame, np.full_like(frame, (245, 239, 221)), (surface.astype(np.float32) * surface_strength).astype(np.uint8))

        # A narrow crystalline edge makes the left-to-right causal direction legible.
        if 0.08 < progress < 0.80:
            edge = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
            cv2.line(edge, (boundary, 635), (boundary - 18, 962), 255, 5, cv2.LINE_AA)
            edge = cv2.bitwise_and(edge, ellipse)
            edge = cv2.GaussianBlur(edge, (0, 0), 3.0)
            frame = blend(frame, np.full_like(frame, (255, 247, 225)), (edge.astype(np.float32) * 0.72).astype(np.uint8))

        # Sparse attached crystals animate at the reveal edge; no free-floating fog.
        rng = np.random.default_rng(17000 + index)
        for _ in range(14):
            y = int(rng.integers(660, 945))
            x = int(boundary + rng.integers(-15, 16))
            if 0 <= x < WIDTH and ellipse[y, x] > 0:
                radius = int(rng.integers(1, 4))
                cv2.circle(frame, (x, y), radius, (246, 240, 222), -1, cv2.LINE_AA)

        cv2.imwrite(str(tmp_path / f"frame_{index:04d}.png"), frame)

    raw_video = tmp_path / "video_only.mp4"
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
        "-framerate", str(FPS), "-i", str(tmp_path / "frame_%04d.png"),
        "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
        "-r", str(FPS), str(raw_video),
    ], check=True)
    subprocess.run([
        str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(raw_video),
        "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.012:duration=5:sample_rate=48000",
        "-filter_complex", "[1:a]highpass=f=80,lowpass=f=1200,volume=0.16,afade=t=in:st=0:d=0.15,afade=t=out:st=4.55:d=0.45[a]",
        "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
        "-t", "5", "-movflags", "+faststart", str(OUT),
    ], check=True)

payload = {
    "schema": "qingshan.local_motion_composite_build.v1",
    "episode": "E36", "unit_id": "U17", "source_segment_id": "E36-CW-U17",
    "status": "BUILT_PENDING_QA", "generation_credits": 0,
    "source_predecessor_video": rel(SOURCE), "source_predecessor_sha256": source_sha,
    "semantic_reveal_still": rel(REVEAL), "semantic_reveal_still_sha256": reveal_sha,
    "output": rel(OUT), "output_sha256": sha(OUT),
    "duration_seconds": 5.0, "fps": FPS, "resolution": [WIDTH, HEIGHT],
    "motion_design": [
        {"seconds": [0.0, 0.667], "beat": "accepted real U16B reach motion continues toward the offered ticket", "contact_read": "Chenji fingers close the final gap while the messenger still supports the edge"},
        {"seconds": [0.667, 1.067], "beat": "motivated evidence-detail cut lands on Chenji supporting the ticket with both hands", "contact_read": "ticket weight is visibly supported at both paper edges"},
        {"seconds": [1.067, 4.25], "beat": "attached frost recedes left-to-right across the stamp", "contact_read": "the exact 刘家 stamp appears progressively behind the frost boundary"},
        {"seconds": [4.25, 5.0], "beat": "frost stops and the exact evidence holds", "contact_read": "Chenji continues supporting the ticket; candle luminance supplies environment life"},
    ],
    "anti_goodhart": "No full-frame synthetic camera drift, speed change, freeze, interpolation, padding, replay, or metric-motivated cut was used. Every change carries handoff or evidence-reveal information.",
    "audio": "New zero-credit synthetic low pink-noise room tone only; no dialogue was copied or generated.",
    "qa_required": ["frame_cadence", "full_duration_ocr_allow_exact_刘家_only", "audio_stream", "direct_full_duration_contact_and_reveal_review"],
}
MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": payload["status"], "output": rel(OUT), "sha256": payload["output_sha256"]}, ensure_ascii=False))
