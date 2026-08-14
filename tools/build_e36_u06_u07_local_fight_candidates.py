#!/usr/bin/env python3
"""Build zero-credit U06/U07 action-detail composites from their accepted anchors."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import tempfile
import wave
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
FFMPEG = ROOT / ".agentcut_env/lib/python3.14/site-packages/agentcut/vendor/darwin-arm64/ffmpeg"
U06_ANCHOR = ROOT / "working_assets/e36_v2_stills_20260728/repair_v2_candidates/E36_E36-CW-U06-A1-STILL-V2_08e2197e-46e5-4861-b358-b17da87cd630.png"
U07_ANCHOR = ROOT / "working_assets/e36_v2_stills_20260728/u07_candidates_v4/E36-CW-U07-A4-STILL-V4_2047b9ac-5635-410a-b5c3-b29a196eaf67.png"
OUT_DIR = ROOT / "working_assets/e36_v2_stills_20260728/local_fight_fallbacks"
QA_DIR = ROOT / "qa/e36_v2_stills_repair_20260729/local_fight_runtime"
FPS = 24
WIDTH = 720
HEIGHT = 1280
FRAMES = 120


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def smooth(value: float) -> float:
    value = clamp(value)
    return value * value * (3.0 - 2.0 * value)


def ease_out(value: float) -> float:
    value = clamp(value)
    return 1.0 - (1.0 - value) ** 3


def focus_transform(
    image: np.ndarray,
    focus: tuple[float, float],
    zoom: float,
    rotation: float = 0.0,
    offset: tuple[float, float] = (0.0, 0.0),
) -> np.ndarray:
    # Clamp the virtual camera window inside the accepted anchor. This avoids
    # reflected-edge duplicates when an action detail sits close to frame edge.
    crop_w = max(2, int(round(WIDTH / zoom)))
    crop_h = max(2, int(round(HEIGHT / zoom)))
    target_x = focus[0] - offset[0] / zoom
    target_y = focus[1] - offset[1] / zoom
    left = int(round(target_x - crop_w / 2))
    top = int(round(target_y - crop_h / 2))
    left = max(0, min(WIDTH - crop_w, left))
    top = max(0, min(HEIGHT - crop_h, top))
    crop = image[top:top + crop_h, left:left + crop_w]
    result = cv2.resize(crop, (WIDTH, HEIGHT), interpolation=cv2.INTER_LANCZOS4)
    if abs(rotation) > 0.01:
        matrix = cv2.getRotationMatrix2D((WIDTH / 2, HEIGHT / 2), rotation, 1.0)
        result = cv2.warpAffine(result, matrix, (WIDTH, HEIGHT), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT_101)
    return result


def u06_deflected_terminal(anchor: np.ndarray) -> np.ndarray:
    """Remove the dagger tip from the robe and redraw it visibly deflected up-left."""
    mask = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    cv2.line(mask, (420, 536), (572, 578), 255, 26, cv2.LINE_AA)
    cv2.ellipse(mask, (548, 568), (35, 30), 0, 0, 360, 255, -1, cv2.LINE_AA)
    mask = cv2.dilate(mask, np.ones((9, 9), np.uint8), iterations=1)
    terminal = cv2.inpaint(anchor, mask, 7, cv2.INPAINT_TELEA)
    # The hilt remains in the attacker's fist. The silver blade now points
    # sharply up-left and terminates well outside the messenger silhouette.
    pivot = (424, 542)
    tip = (468, 470)
    cv2.line(terminal, pivot, tip, (66, 72, 77), 7, cv2.LINE_AA)
    cv2.line(terminal, (425, 540), (468, 470), (184, 191, 193), 2, cv2.LINE_AA)
    cv2.fillConvexPoly(terminal, np.array([[468, 470], [462, 483], [475, 479]], dtype=np.int32), (105, 112, 116), cv2.LINE_AA)
    # Shift the messenger's connected silhouette right/rear after the block.
    # A broad feathered remap avoids a cutout edge while preserving Jiaotu.
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH].astype(np.float32)
    pull_mask = np.exp(-(((xx - 595.0) / 150.0) ** 2 + ((yy - 650.0) / 360.0) ** 2) * 2.2).astype(np.float32)
    map_x = xx - 38.0 * pull_mask
    map_y = yy + 12.0 * pull_mask
    pulled = cv2.remap(terminal, map_x, map_y, cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REFLECT_101)
    alpha = np.clip(pull_mask * 255.0, 0, 255).astype(np.uint8)
    return blend(terminal, pulled, alpha)


def directional_blur(frame: np.ndarray, dx: int, dy: int, copies: int = 8) -> np.ndarray:
    result = np.zeros_like(frame, dtype=np.float32)
    weight = 0.0
    for i in range(copies):
        alpha = 1.0 - 0.65 * i / max(1, copies - 1)
        matrix = np.float32([[1, 0, dx * i / max(1, copies - 1)], [0, 1, dy * i / max(1, copies - 1)]])
        shifted = cv2.warpAffine(frame, matrix, (WIDTH, HEIGHT), borderMode=cv2.BORDER_REFLECT_101)
        result += shifted.astype(np.float32) * alpha
        weight += alpha
    return np.clip(result / weight, 0, 255).astype(np.uint8)


def blend(base: np.ndarray, overlay: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    layer = alpha.astype(np.float32)[..., None] / 255.0
    return np.clip(base * (1.0 - layer) + overlay * layer, 0, 255).astype(np.uint8)


def add_dust(frame: np.ndarray, seed: int, origin: tuple[int, int], strength: float, direction: tuple[float, float]) -> np.ndarray:
    rng = np.random.default_rng(seed)
    ox, oy = origin
    for _ in range(int(35 * max(0.0, strength))):
        age = float(rng.random())
        x = int(ox + direction[0] * age + rng.normal(0, 38 + 46 * age))
        y = int(oy + direction[1] * age + rng.normal(0, 26 + 35 * age))
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            radius = int(rng.integers(1, 5))
            color = (int(115 + 45 * age), int(135 + 45 * age), int(155 + 45 * age))
            cv2.circle(frame, (x, y), radius, color, -1, cv2.LINE_AA)
    return frame


def add_shadow_intercept(frame: np.ndarray, phase: float, seed: int) -> np.ndarray:
    """Attach a short black-silver counterforce arc to Jiaotu and the blade contact."""
    phase = clamp(phase)
    mask = np.zeros((HEIGHT, WIDTH), dtype=np.uint8)
    # The arc starts at Jiaotu's leading forearm and ends at the weapon/robe contact.
    start = (360, 548)
    end = (535, 560)
    control = (442, 500 - int(22 * phase))
    points = []
    for i in range(31):
        t = i / 30.0
        x = int((1 - t) ** 2 * start[0] + 2 * (1 - t) * t * control[0] + t * t * end[0])
        y = int((1 - t) ** 2 * start[1] + 2 * (1 - t) * t * control[1] + t * t * end[1])
        points.append((x, y))
    cv2.polylines(mask, [np.array(points)], False, 210, 10, cv2.LINE_AA)
    mask = cv2.GaussianBlur(mask, (0, 0), 5.0)
    shadow = np.full_like(frame, (32, 30, 28))
    frame = blend(frame, shadow, (mask.astype(np.float32) * (0.28 + 0.46 * phase)).astype(np.uint8))
    edge = np.zeros_like(mask)
    cv2.polylines(edge, [np.array(points)], False, 255, 3, cv2.LINE_AA)
    edge = cv2.GaussianBlur(edge, (0, 0), 1.7)
    frame = blend(frame, np.full_like(frame, (245, 226, 190)), (edge.astype(np.float32) * (0.18 + 0.52 * phase)).astype(np.uint8))
    rng = np.random.default_rng(seed)
    for _ in range(int(18 * phase)):
        angle = rng.uniform(-2.6, -0.4)
        length = rng.uniform(10, 48) * phase
        x1 = int(end[0] + rng.normal(0, 12))
        y1 = int(end[1] + rng.normal(0, 10))
        x2 = int(x1 + math.cos(angle) * length)
        y2 = int(y1 + math.sin(angle) * length)
        cv2.line(frame, (x1, y1), (x2, y2), (225, 214, 188), 1, cv2.LINE_AA)
    return frame


def add_frost_rime(frame: np.ndarray, center: tuple[int, int], radius: float, seed: int, strength: float) -> np.ndarray:
    rng = np.random.default_rng(seed)
    overlay = frame.copy()
    cx, cy = center
    for _ in range(int(42 * strength)):
        angle = rng.uniform(0, 2 * math.pi)
        r = rng.uniform(radius * 0.3, radius)
        x = int(cx + math.cos(angle) * r * 1.35)
        y = int(cy + math.sin(angle) * r * 0.45)
        length = int(rng.integers(4, 19))
        cv2.line(overlay, (x - length, y), (x + length, y), (245, 238, 221), int(rng.integers(1, 4)), cv2.LINE_AA)
    return cv2.addWeighted(frame, 1.0, overlay, 0.24 * strength, 0)


def make_audio(path: Path, impacts: list[tuple[float, float]], duration: float = 5.0) -> None:
    sample_rate = 48000
    count = int(sample_rate * duration)
    rng = np.random.default_rng(360607)
    audio = rng.normal(0, 0.004, count).astype(np.float32)
    time = np.arange(count) / sample_rate
    audio += 0.004 * np.sin(2 * math.pi * 73 * time)
    for at, power in impacts:
        start = int(at * sample_rate)
        length = min(int(0.34 * sample_rate), count - start)
        if length <= 0:
            continue
        t = np.arange(length) / sample_rate
        env = np.exp(-t * 15.0)
        hit = (0.26 * np.sin(2 * math.pi * 74 * t) + 0.11 * rng.normal(0, 1, length)) * env * power
        audio[start:start + length] += hit.astype(np.float32)
    peak = max(1e-6, float(np.max(np.abs(audio))))
    pcm = np.int16(np.clip(audio / max(1.0, peak / 0.88), -1, 1) * 32767)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())


def write_video(frames: list[np.ndarray], out: Path, impacts: list[tuple[float, float]]) -> None:
    with tempfile.TemporaryDirectory(prefix=f"{out.stem}_") as tmp:
        tmp_path = Path(tmp)
        for index, frame in enumerate(frames):
            cv2.imwrite(str(tmp_path / f"frame_{index:04d}.png"), frame)
        raw = tmp_path / "video.mp4"
        audio = tmp_path / "audio.wav"
        make_audio(audio, impacts)
        subprocess.run([
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
            "-framerate", str(FPS), "-i", str(tmp_path / "frame_%04d.png"),
            "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p",
            "-r", str(FPS), str(raw),
        ], check=True)
        subprocess.run([
            str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(raw), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-t", "5",
            "-movflags", "+faststart", str(out),
        ], check=True)


def build_u06(anchor: np.ndarray, continuation_anchor: np.ndarray) -> tuple[list[np.ndarray], list[dict[str, object]]]:
    terminal = u06_deflected_terminal(anchor)
    frames: list[np.ndarray] = []
    for index in range(FRAMES):
        if index < 32:
            p = index / 31.0
            burst = math.sin(math.pi * p)
            focus = (520 - 35 * p, 558 - 18 * p)
            frame = focus_transform(anchor, focus, 1.20 + 0.17 * ease_out(p), rotation=-1.8 * burst)
            frame = add_dust(frame, 61000 + index, (535, 560), 0.25 + 0.95 * p, (-105, 62))
        elif index < 56:
            p = (index - 32) / 23.0
            recoil = math.sin(p * math.pi * 3.0) * (1.0 - p)
            focus = (482 + 25 * p, 548 - 30 * p)
            frame = focus_transform(anchor, focus, 1.37 - 0.13 * p, rotation=2.2 * recoil, offset=(9 * recoil, -5 * recoil))
            frame = add_shadow_intercept(frame, smooth(p), 62000 + index)
        elif index < 64:
            p = (index - 56) / 7.0
            start = focus_transform(anchor, (440 - 55 * p, 535 - 42 * p), 1.24 + 0.18 * p, rotation=-4.0 + 8.0 * p)
            end = focus_transform(terminal, (440 - 55 * p, 535 - 42 * p), 1.24 + 0.18 * p, rotation=-4.0 + 8.0 * p)
            frame = cv2.addWeighted(start, 1.0 - smooth(p), end, smooth(p), 0)
            frame = add_shadow_intercept(frame, 1.0, 63000 + index)
            frame = directional_blur(frame, int(-28 + 56 * p), -12, 10)
        elif index < 94:
            p = (index - 64) / 29.0
            recoil = math.sin(math.pi * p)
            focus = (420 - 34 * p, 525 - 35 * p)
            frame = focus_transform(terminal, focus, 1.40 - 0.09 * p, rotation=3.2 * recoil, offset=(-18 * p, -8 * recoil))
            frame = add_shadow_intercept(frame, 1.0, 64000 + index)
            frame = add_dust(frame, 65000 + index, (500, 550), 1.15 - 0.4 * p, (-155, -62))
        elif index < 102:
            p = (index - 94) / 7.0
            start = focus_transform(terminal, (395, 495), 1.26, rotation=-2.5 + 5.0 * p)
            end = focus_transform(continuation_anchor, (525, 210), 3.0, rotation=2.5 - 5.0 * p, offset=(18 * p, -8 * p))
            frame = cv2.addWeighted(start, 1.0 - smooth(p), end, smooth(p), 0)
            frame = directional_blur(frame, int(-30 + 60 * p), -16, 10)
        else:
            p = (index - 102) / 17.0
            pull = ease_out(p)
            focus = (525 + 12 * pull, 210 - 8 * pull)
            frame = focus_transform(continuation_anchor, focus, 3.0 - 0.18 * p, rotation=-2.0 + 1.4 * p, offset=(22 * pull, -12 * pull))
            frame = add_dust(frame, 67000 + index, (345, 735), 0.26 - 0.12 * p, (45, 22))
        frames.append(frame)
    beats = [
        {"seconds": [0.0, 1.33], "subject_action": "attacker drives the blade from left toward the messenger's right outer shoulder", "contact_point": "blade edge catches cloth only", "direction": "left-to-right and slightly downward", "terminal_state": "outer robe tears; skin remains untouched"},
        {"seconds": [1.33, 2.67], "subject_action": "Jiaotu's attached black-silver counterforce rises from her leading arm into the weapon", "contact_point": "counterforce meets the blade beside the torn shoulder", "direction": "center-to-left/up against the attack", "terminal_state": "weapon line is arrested and starts recoiling"},
        {"seconds": [2.67, 3.92], "subject_action": "the blocked weapon recoils while Jiaotu tracks the messenger", "contact_point": "intercept remains attached to the blade line", "direction": "weapon retreats left/up; messenger track moves right/rear", "terminal_state": "blade clears the body line"},
        {"seconds": [3.92, 5.0], "subject_action": "Jiaotu completes the defensive pull into the crowd-side blind angle", "contact_point": "counterforce keeps the blade outside the messenger silhouette", "direction": "right/rear for messenger, left for attacker", "terminal_state": "messenger remains upright and uninjured behind Jiaotu"},
    ]
    return frames, beats


def build_u07(anchor: np.ndarray) -> tuple[list[np.ndarray], list[dict[str, object]]]:
    frames: list[np.ndarray] = []
    for index in range(FRAMES):
        if index < 31:
            p = index / 30.0
            focus = (150 + 18 * p, 735 - 25 * p)
            frame = focus_transform(anchor, focus, 1.48 + 0.12 * math.sin(math.pi * p), rotation=-2.0 + 2.6 * p, offset=(-18 * p, 10 * math.sin(math.pi * p)))
            frame = add_frost_rime(frame, (340, 690), 155 + 35 * p, 71000 + index, 0.55 + 0.65 * p)
        elif index < 39:
            p = (index - 31) / 7.0
            focus = (170 + 180 * p, 710 - 120 * p)
            frame = focus_transform(anchor, focus, 1.52 - 0.15 * p, rotation=1.0 - 6.0 * p)
            frame = directional_blur(frame, int(-36 + 72 * p), -18, 10)
        elif index < 70:
            p = (index - 39) / 30.0
            focus = (350 + 26 * p, 625 + 55 * p)
            swing = math.sin(math.pi * p)
            frame = focus_transform(anchor, focus, 1.34 + 0.16 * swing, rotation=-3.5 + 6.5 * p, offset=(16 * swing, 28 * p))
            frame = add_dust(frame, 72000 + index, (350, 645), 0.45 + 0.7 * swing, (68, 120))
        elif index < 78:
            p = (index - 70) / 7.0
            focus = (370 + 160 * p, 660 - 380 * p)
            frame = focus_transform(anchor, focus, 1.43 + 0.1 * p, rotation=3.0 - 6.5 * p)
            frame = directional_blur(frame, int(-30 + 60 * p), int(34 - 68 * p), 10)
        elif index < 105:
            p = (index - 78) / 26.0
            focus = (520 + 18 * p, 250 - 18 * p)
            pull = ease_out(p)
            frame = focus_transform(anchor, focus, 1.55 - 0.10 * p, rotation=-3.0 + 2.0 * p, offset=(24 * pull, -18 * pull))
            frame = add_dust(frame, 73000 + index, (365, 725), 0.28 + 0.25 * (1.0 - p), (35, 25))
        else:
            p = (index - 105) / 14.0
            focus = (510 - 150 * ease_out(p), 310 + 330 * ease_out(p))
            frame = focus_transform(anchor, focus, 1.45 - 0.39 * ease_out(p), rotation=-1.0 + 1.0 * p, offset=(8 * (1.0 - p), -5 * (1.0 - p)))
            frame = add_frost_rime(frame, (150, 760), 90, 74000 + index, 0.36)
        frames.append(frame)
    beats = [
        {"seconds": [0.0, 1.29], "subject_action": "Jiaotu's dry rime locks the adult male hidden stake's boots to the platform", "contact_point": "powder-white frost shell attaches around both soles and plank seams", "direction": "outward from both boots", "terminal_state": "both feet are fixed; no liquid water or splash"},
        {"seconds": [1.29, 2.92], "subject_action": "the blank paper substitute tips into the exposed execution line", "contact_point": "paper body crosses the attacker-facing foreground lane", "direction": "upper-right to lower-left/down", "terminal_state": "paper substitute occupies the dangerous line"},
        {"seconds": [2.92, 4.38], "subject_action": "Jiaotu closes five fingers on the messenger's rear collar and pulls", "contact_point": "right hand grips the rear collar fabric", "direction": "right/rear away from the paper substitute", "terminal_state": "messenger's torso tilts safely away from the attack lane"},
        {"seconds": [4.38, 5.0], "subject_action": "the camera releases to the complete substitution tableau", "contact_point": "frozen feet, blank paper double and collar grip remain visible together", "direction": "pullback only after the three causal contacts", "terminal_state": "true messenger is behind Jiaotu; paper double remains in the exposed line"},
    ]
    return frames, beats


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    u06 = cv2.imread(str(U06_ANCHOR), cv2.IMREAD_COLOR)
    u07 = cv2.imread(str(U07_ANCHOR), cv2.IMREAD_COLOR)
    if u06 is None or u07 is None:
        raise SystemExit("accepted anchor missing or unreadable")
    u06 = cv2.resize(u06, (WIDTH, HEIGHT), interpolation=cv2.INTER_LANCZOS4)
    u07 = cv2.resize(u07, (WIDTH, HEIGHT), interpolation=cv2.INTER_LANCZOS4)

    builds = []
    for unit, anchor_path, frames, beats, impacts in (
        ("U06", U06_ANCHOR, *build_u06(u06, u07), [(0.12, 0.7), (1.38, 1.0), (2.66, 1.15), (3.94, 0.75)]),
        ("U07", U07_ANCHOR, *build_u07(u07), [(0.10, 0.55), (1.30, 0.85), (2.94, 1.0), (4.36, 0.55)]),
    ):
        version = "V6" if unit == "U06" else "V2"
        out = OUT_DIR / f"E36-CW-{unit}-LOCAL-ACTION-DETAIL-{version}.mp4"
        manifest = QA_DIR / f"E36_{unit}_LOCAL_ACTION_DETAIL_BUILD_{version}.json"
        if out.exists() and manifest.exists():
            builds.append({"unit": unit, "output": rel(out), "sha256": sha(out), "manifest": rel(manifest), "reused_existing": True})
            continue
        write_video(frames, out, impacts)
        payload = {
            "schema": "qingshan.local_action_detail_composite_build.v1",
            "episode": "E36",
            "unit_id": unit,
            "status": "BUILT_PENDING_QA",
            "generation_credits": 0,
            "accepted_single_anchor": rel(anchor_path),
            "accepted_single_anchor_sha256": sha(anchor_path),
            "accepted_continuation_anchor": rel(U07_ANCHOR) if unit == "U06" else None,
            "accepted_continuation_anchor_sha256": sha(U07_ANCHOR) if unit == "U06" else None,
            "output": rel(out),
            "output_sha256": sha(out),
            "duration_seconds": 5.0,
            "fps": FPS,
            "resolution": [WIDTH, HEIGHT],
            "dialogue_required": False,
            "motion_design": beats,
            "edit_structure": "Four motivated action-detail beats; each cut or camera move changes the visible causal contact. No unrelated coverage cut is used.",
            "audio": "Zero-credit locally synthesized crowd-bed/impact design only; no dialogue or remote generation.",
            "limitations": [
                "This fallback is an action-detail composite from the sole accepted first-frame authority, not a new generative performance.",
                "U06 uses a tight final collar-contact detail from the accepted immediately following U07 anchor; the crop excludes U07's paper/frost contacts and serves only as the chronological pull terminal.",
                "Admission requires cadence, motion-floor, OCR, media and direct full-duration human contact/terminal-state review; build status alone is not acceptance.",
            ],
            "qa_required": ["frame_cadence", "fight_motion_floor_v2_1", "full_duration_ocr", "media_probe", "direct_full_duration_contact_and_terminal_state_review"],
        }
        manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        builds.append({"unit": unit, "output": rel(out), "sha256": payload["output_sha256"], "manifest": rel(manifest)})
    print(json.dumps({"status": "BUILT_PENDING_QA", "generation_credits": 0, "builds": builds}, ensure_ascii=False))


if __name__ == "__main__":
    main()
