#!/usr/bin/env python3
"""Record U06 V3 OCR failure and render V4 with irregular non-glyph frost."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

import render_qa_e40_u06_v3_local_authority as renderer


ROOT = Path(__file__).resolve().parents[1]
V3_VIDEO = ROOT / "working_assets/e40_production_20260814/u06_v3_local_authority_exact_dialogue_v1/E40-U06-V3-LOCAL-AUTHORITY-EXACT-DIA005-SEQUENTIAL-FROST.mp4"
V3_QA = ROOT / "qa/e40_production_20260814/u06_v3_local_authority_exact_dialogue_v1/E40_U06_V3_LOCAL_AUTHORITY_EXACT_DIALOGUE_MACHINE_QA_V1.json"
V3_OCR = ROOT / "qa/e40_production_20260814/u06_v3_local_authority_exact_dialogue_v1/E40_U06_V3_FULL_DURATION_OCR_AUDIT_V1.json"
MEMORY = ROOT / "qa/e40_production_20260814/u06_v3_local_authority_exact_dialogue_v1/E40_U06_V3_OCR_FAILURE_MEMORY_V1.json"
OUT_DIR = ROOT / "working_assets/e40_production_20260814/u06_v4_local_irregular_frost_exact_dialogue_v1"
QA_DIR = ROOT / "qa/e40_production_20260814/u06_v4_local_irregular_frost_exact_dialogue_v1"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True); raise


def irregular_frost(center: tuple[int, int], seed: int, width: int = 78) -> np.ndarray:
    rng = np.random.default_rng(seed); canvas = np.zeros((1280, 720), dtype=np.float32); cx, cy = center
    for path_index in range(13):
        x = cx + rng.uniform(-8, 8); y = cy + rng.uniform(-5, 5); angle = rng.uniform(-1.05, 1.05) + (0 if path_index < 9 else math.pi); points = [(int(x), int(y))]
        steps = int(rng.integers(4, 9))
        for step in range(steps):
            angle += rng.normal(0, .42); distance = rng.uniform(5, 12); x += math.cos(angle) * distance; y += math.sin(angle) * distance * .42; points.append((int(x), int(y)))
            if step > 1 and rng.random() < .35:
                branch_angle = angle + rng.choice([-1, 1]) * rng.uniform(.65, 1.2); length = rng.uniform(6, 15); cv2.line(canvas, points[-1], (int(x + math.cos(branch_angle) * length), int(y + math.sin(branch_angle) * length * .45)), rng.uniform(.35, .65), 1, cv2.LINE_AA)
        cv2.polylines(canvas, [np.asarray(points, np.int32)], False, rng.uniform(.55, .95), int(rng.choice([1, 1, 2])), cv2.LINE_AA)
    noise = rng.random(canvas.shape).astype(np.float32); noise = cv2.GaussianBlur(noise, (0, 0), 2.2); region = np.zeros_like(canvas); cv2.ellipse(region, center, (width // 2, 24), rng.uniform(-12, 12), 0, 360, 1.0, -1); canvas += region * np.clip((noise - .49) * 1.7, 0, .22)
    return cv2.GaussianBlur(np.clip(canvas, 0, 1), (5, 5), 0)


def main() -> int:
    if MEMORY.exists() or (OUT_DIR / "E40-U06-V4-LOCAL-AUTHORITY-EXACT-DIA005-IRREGULAR-FROST.mp4").exists():
        raise SystemExit("FAIL_CLOSED_MEMORY_OR_OUTPUT_COLLISION")
    qa = json.loads(V3_QA.read_text(encoding="utf-8")); ocr = json.loads(V3_OCR.read_text(encoding="utf-8"))
    if qa.get("status") != "FAIL" or qa.get("failures") != ["OCR_NONZERO"] or ocr.get("status") != "FAIL":
        raise SystemExit("FAIL_CLOSED_V3_NOT_EXACT_OCR_ONLY_FAILURE")
    atomic_json(MEMORY, {"schema": "qingshan.e40.local_video_failure_memory.v1", "status": "ACTIVE_V3_QUARANTINED", "created_at": now(), "episode": "E40", "unit": "U06", "version": "V3", "video_path": str(V3_VIDEO.relative_to(ROOT)), "video_sha256": sha(V3_VIDEO), "failure": "RapidOCR detected repeated 米-like pseudo-glyphs in symmetric radial frost overlays", "ocr_recognitions": ocr["recognitions"], "replay_forbidden": True, "material_change_required": "Replace radial/symmetric frost templates with non-radial irregular random-walk crack networks; new V4 output paths and SHA; retain only admitted authority frame and independently passed exact audio.", "paid_provider_retry": False, "credits": 0})
    renderer.OUT_DIR = OUT_DIR
    renderer.VIDEO = OUT_DIR / "E40-U06-V4-LOCAL-AUTHORITY-EXACT-DIA005-IRREGULAR-FROST.mp4"
    renderer.QA_DIR = QA_DIR
    renderer.FRAME0 = QA_DIR / "frame_0000.png"
    renderer.CONTACT = QA_DIR / "contact_sheet.png"
    renderer.OCR_QA = QA_DIR / "E40_U06_V4_FULL_DURATION_OCR_AUDIT_V1.json"
    renderer.QA = QA_DIR / "E40_U06_V4_LOCAL_AUTHORITY_EXACT_DIALOGUE_MACHINE_QA_V1.json"
    renderer.RECEIPT = ROOT / "workflow/tasks/E40_U06_V4_LOCAL_AUTHORITY_EXACT_DIALOGUE_RENDER_20260814.json"
    renderer.FROST = [irregular_frost((330, 1068), 406, 70), irregular_frost((445, 1066), 407, 76), irregular_frost((557, 1063), 408, 72)]
    return renderer.main()


if __name__ == "__main__":
    raise SystemExit(main())
