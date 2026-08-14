#!/usr/bin/env python3
"""Build a visual boundary sheet for caption timing diagnostics."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageFont


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frame_at(capture: cv2.VideoCapture, seconds: float) -> Image.Image:
    capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, seconds) * 1000.0)
    ok, frame = capture.read()
    if not ok:
        raise RuntimeError(f"Could not decode frame at {seconds:.3f}s")
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--timing-report", type=Path, required=True)
    parser.add_argument("--out-image", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args()

    report = json.loads(args.timing_report.read_text(encoding="utf-8"))
    flagged = [row for row in report["rows"] if row["status"] == "FAIL"]
    offsets = [(-0.30, "START-0.30"), (0.0, "START"), (0.30, "START+0.30"),
               (-0.30, "END-0.30"), (0.0, "END"), (0.30, "END+0.30")]
    cell_w, cell_h, label_h = 240, 427, 34
    canvas = Image.new("RGB", (cell_w * 6, (cell_h + label_h) * len(flagged)), "black")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    capture = cv2.VideoCapture(str(args.video.resolve()))
    if not capture.isOpened():
        raise SystemExit(f"Could not open {args.video}")
    manifest_rows = []
    for row_index, row in enumerate(flagged):
        starts = [float(row["caption_start"])] * 3 + [float(row["caption_end"])] * 3
        samples = []
        for column, ((offset, label), base) in enumerate(zip(offsets, starts)):
            timestamp = max(0.0, base + offset)
            frame = frame_at(capture, timestamp)
            frame.thumbnail((cell_w, cell_h), Image.Resampling.LANCZOS)
            x = column * cell_w + (cell_w - frame.width) // 2
            y = row_index * (cell_h + label_h)
            canvas.paste(frame, (x, y))
            caption = f"{row['dialogue_id']} {label} {timestamp:.3f}s"
            draw.rectangle((column * cell_w, y + cell_h, (column + 1) * cell_w, y + cell_h + label_h), fill="black")
            draw.text((column * cell_w + 5, y + cell_h + 8), caption, fill="white", font=font)
            samples.append({"label": label, "time_seconds": round(timestamp, 3)})
        manifest_rows.append({"dialogue_id": row["dialogue_id"], "text": row["text"], "samples": samples})
    capture.release()
    args.out_image.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(args.out_image, quality=94)
    payload = {
        "schema": "qingshan.caption_boundary_contact_sheet.v1",
        "status": "READY_FOR_DIRECT_VISUAL_ADJUDICATION",
        "video": str(args.video.resolve()),
        "video_sha256": sha256(args.video),
        "timing_report": str(args.timing_report.resolve()),
        "timing_report_sha256": sha256(args.timing_report),
        "flagged_dialogue_count": len(flagged),
        "rows": manifest_rows,
        "contact_sheet": str(args.out_image.resolve()),
        "contact_sheet_sha256": sha256(args.out_image),
    }
    args.out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "flagged": len(flagged), "image": str(args.out_image)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
