#!/usr/bin/env python3
"""Build a 4 fps visual probe around the only V19-new insertion window."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "working_assets/e36_agentcut_20260731/accepted_only_v19_v18c_plus_line10/E36_ACCEPTED_ONLY_AGENTCUT_V19_V18C_PLUS_LINE10.mp4"
OUT = ROOT / "qa/e36_agentcut_20260730/v19_line10_quarter_second_probe_v1"
START = 68.928
END = 80.011
STEP = 0.25


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(VIDEO))
    if not cap.isOpened():
        raise SystemExit("cannot open V19")
    font = ImageFont.load_default()
    samples = []
    times = []
    t = START
    while t <= END + 1e-6:
        times.append(round(t, 3))
        t += STEP
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, frame = cap.read()
        if not ok:
            raise SystemExit(f"decode failed at {t}")
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb).resize((180, 320), Image.Resampling.LANCZOS)
        samples.append((t, image))
    cap.release()

    sheets = []
    for page, offset in enumerate(range(0, len(samples), 15), start=1):
        batch = samples[offset : offset + 15]
        sheet = Image.new("RGB", (900, 1005), "#111111")
        draw = ImageDraw.Draw(sheet)
        for i, (t, image) in enumerate(batch):
            row, col = divmod(i, 5)
            x, y = col * 180, row * 335
            sheet.paste(image, (x, y))
            draw.rectangle((x, y + 320, x + 180, y + 335), fill="#111111")
            draw.text((x + 5, y + 321), f"V19 {t:07.3f}s", fill="white", font=font)
        path = OUT / f"E36_V19_LINE10_QUARTER_SECOND_CONTACT_{page:02d}.jpg"
        sheet.save(path, quality=94)
        sheets.append({"path": str(path.relative_to(ROOT)), "sha256": sha256(path), "sample_times": [t for t, _ in batch]})

    manifest = {
        "schema": "e36_v19_line10_quarter_second_probe_v1",
        "candidate": {"path": str(VIDEO.relative_to(ROOT)), "sha256": sha256(VIDEO)},
        "window_seconds": [START, END],
        "sample_interval_seconds": STEP,
        "sample_rate_fps": 1 / STEP,
        "sample_count": len(samples),
        "purpose": "Resolve CL2X-912 advisory by exposing the only V19-new insertion and both edit boundaries at 0.25-second cadence; this is a localized diagnostic and cannot clear full-runtime realtime comfort.",
        "sheets": sheets,
    }
    path = OUT / "E36_V19_LINE10_QUARTER_SECOND_PROBE_MANIFEST_V1.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"manifest": str(path.relative_to(ROOT)), "sha256": sha256(path), "sheets": sheets}))


if __name__ == "__main__":
    main()
