#!/usr/bin/env python3
"""Materially amplify the V6 deterministic representation after PF-035."""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
BASE_SCRIPT = ROOT / "tools/build_e40_u02_v6_deterministic_source_authority_video.py"
MEMORY = ROOT / "workflow/claude_writer_agent/GENERATION_PROMPT_FAILURE_MEMORY.json"
OUT_DIR = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v7_amplified_deterministic_authority_v1"
VIDEO = OUT_DIR / "E40_U02_V7_AMPLIFIED_DETERMINISTIC_AUTHORITY_CANDIDATE_V1.mp4"
SPEC = OUT_DIR / "E40_U02_V7_AMPLIFIED_DETERMINISTIC_AUTHORITY_SPEC_V1.json"
CONTACT = ROOT / "qa/e40_production_20260814/u02_v7_amplified_deterministic_authority_v1/E40_U02_V7_CONTACT_SHEET_V1.png"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def linear_window(t: float, start: float, end: float) -> float:
    return min(1.0, max(0.0, (t - start) / (end - start)))


def amplified_frame(base: np.ndarray, index: int, xx: np.ndarray, yy: np.ndarray) -> np.ndarray:
    if index == 0:
        return base.copy()
    t = index / 24.0
    close = linear_window(t, 0.0, 0.50)
    settle = linear_window(t, 0.50, 1.80)
    turn = linear_window(t, 1.80, 3.00)
    breath = linear_window(t, 3.00, 4.00)

    fan_weight = np.exp(-(((xx - 518.0) / 83.0) ** 2 + ((yy - 770.0) / 220.0) ** 2) * 1.9)
    map_x = xx + fan_weight * (xx - 493.0) * (0.18 * close)
    map_y = yy.copy()

    hand_weight = np.exp(-(((xx - 553.0) / 195.0) ** 2 + ((yy - 1015.0) / 335.0) ** 2) * 1.25)
    map_x -= hand_weight * (-20.0 * settle)
    map_y -= hand_weight * (48.0 * settle)

    angle = math.radians(-6.0 * turn)
    px, py = 520.0, 950.0
    dx, dy = xx - px, yy - py
    src_x = math.cos(angle) * dx + math.sin(angle) * dy + px
    src_y = -math.sin(angle) * dx + math.cos(angle) * dy + py
    turn_weight = np.exp(-(((xx - 525.0) / 150.0) ** 2 + ((yy - 910.0) / 305.0) ** 2) * 1.5)
    map_x = map_x * (1.0 - turn_weight) + src_x * turn_weight
    map_y = map_y * (1.0 - turn_weight) + src_y * turn_weight

    # Continuous non-looping curtain life prevents a global static interval.
    ambient = min(1.0, t / 4.0)
    curtain_weight = np.exp(-(((xx - 315.0) / 285.0) ** 2 + ((yy - 640.0) / 470.0) ** 2) * 1.0)
    curtain_weight *= np.clip((1165.0 - yy) / 240.0, 0.0, 1.0)
    map_x += curtain_weight * (
        12.0 * ambient * np.sin((yy / 120.0) + 0.55)
        + 9.0 * breath * np.sin((yy / 88.0) + 1.25)
    )

    return cv2.remap(
        base,
        map_x.astype(np.float32),
        map_y.astype(np.float32),
        interpolation=cv2.INTER_LANCZOS4,
        borderMode=cv2.BORDER_REFLECT_101,
    )


def main() -> None:
    memory = json.loads(MEMORY.read_text(encoding="utf-8"))
    if not any(row.get("id") == "PF-035" for row in memory.get("rules", [])):
        raise SystemExit("PF-035 must be durable before V7")
    module_spec = importlib.util.spec_from_file_location("e40_u02_v6_base", BASE_SCRIPT)
    if module_spec is None or module_spec.loader is None:
        raise SystemExit("cannot import V6 renderer")
    base = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(base)
    base.OUT_DIR = OUT_DIR
    base.VIDEO = VIDEO
    base.SPEC = SPEC
    base.CONTACT = CONTACT
    base.frame_at = amplified_frame
    with contextlib.redirect_stdout(io.StringIO()):
        base.main()

    payload = json.loads(SPEC.read_text(encoding="utf-8"))
    payload.update({
        "schema": "qingshan.e40.u02.v7.amplified_deterministic_authority_spec.v1",
        "variant": "V7",
        "created_at": "2026-08-14T07:01:00Z",
        "failure_memory": {"path": str(MEMORY.relative_to(ROOT)), "sha256": sha(MEMORY), "rule_id": "PF-035"},
        "material_change_from_v6": "Fan compression 5.2%->18%; wrist settle 13px/7px->48px/20px; turn 1.6deg->6deg; linear non-pausing windows; continuous source-authority curtain life plus final localized breath.",
        "beats": [
            {"window": "0.00-0.50", "action": "same half-closed fan visibly compresses another 18 percent"},
            {"window": "0.50-1.80", "action": "same wrist/fan/sleeve settles 48px down and 20px inward"},
            {"window": "1.80-3.00", "action": "same wrist turns inward 6 degrees"},
            {"window": "0.00-4.00", "action": "continuous non-looping curtain life with bottom hem pinned"},
            {"window": "3.00-4.00", "action": "one additional localized curtain breath"},
        ],
        "status": "CANDIDATE_RENDERED_REQUIRES_EXACT_FRAME_CADENCE_OCR_AND_HUMAN_QA",
    })
    base.atomic_json(SPEC, payload)
    print(json.dumps({"status": "PASS_V7_RENDERED", "video": str(VIDEO.relative_to(ROOT)), "video_sha256": sha(VIDEO), "spec_sha256": sha(SPEC), "contact_sheet_sha256": sha(CONTACT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
