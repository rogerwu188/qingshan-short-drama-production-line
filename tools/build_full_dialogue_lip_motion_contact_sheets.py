#!/usr/bin/env python3
"""Build dense, timestamp-bound dialogue review sheets from an AgentCut master."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageFont


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frame_at(cap, seconds: float) -> Image.Image:
    cap.set(cv2.CAP_PROP_POS_MSEC, max(seconds, 0.0) * 1000.0)
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError(f"unable to decode frame at {seconds:.3f}s")
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--audit", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--prefix", default="DIALOGUE_LIP_MOTION_REVIEW")
    args = parser.parse_args()

    audit = json.loads(args.audit.read_text())
    rows = audit["rows"]
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(args.video))
    if not cap.isOpened():
        raise RuntimeError(f"unable to open {args.video}")

    font = ImageFont.load_default()
    cell_w, cell_h, label_h = 180, 320, 34
    pages = []
    for page_index, page_rows in enumerate(
        (rows[index : index + 8] for index in range(0, len(rows), 8)), start=1
    ):
        canvas = Image.new("RGB", (cell_w * 6, (cell_h + label_h) * len(page_rows)), "white")
        samples = []
        for row_index, row in enumerate(page_rows):
            start = float(row["expected_timeline_start"])
            end = float(row["expected_timeline_end"])
            duration = max(end - start, 0.001)
            times = [start + duration * fraction for fraction in (0.05, 0.23, 0.41, 0.59, 0.77, 0.95)]
            for column, seconds in enumerate(times):
                image = frame_at(cap, seconds)
                image.thumbnail((cell_w, cell_h), Image.Resampling.LANCZOS)
                x = column * cell_w + (cell_w - image.width) // 2
                y = row_index * (cell_h + label_h)
                canvas.paste(image, (x, y))
                draw = ImageDraw.Draw(canvas)
                draw.rectangle((column * cell_w, y + cell_h, (column + 1) * cell_w, y + cell_h + label_h), fill="white")
                draw.text((column * cell_w + 4, y + cell_h + 3), f"{row['dialogue_id']} {seconds:.2f}s", fill="black", font=font)
            samples.append({"dialogue_id": row["dialogue_id"], "start": start, "end": end, "sample_times": times})
        output = args.output_dir / f"{args.prefix}_P{page_index}.jpg"
        canvas.save(output, quality=92, subsampling=0)
        pages.append({"path": str(output), "sha256": sha256(output), "rows": samples})

    cap.release()
    manifest = {
        "schema": "qingshan.dialogue_lip_motion_review_package.v1",
        "recorded_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "READY_FOR_DIRECT_VISUAL_REVIEW_NOT_A_LIPSYNC_PASS",
        "video": str(args.video),
        "video_sha256": sha256(args.video),
        "source_audit": str(args.audit),
        "source_audit_sha256": sha256(args.audit),
        "dialogue_count": len(rows),
        "sample_count": len(rows) * 6,
        "pages": pages,
        "scope_limit": "Static within-line samples expose visible mouth and expression evolution but do not prove phoneme-level synchronization, breath timing, or uninterrupted whole-cut causality.",
    }
    manifest_path = args.output_dir / f"{args.prefix}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"manifest": str(manifest_path), "sha256": sha256(manifest_path), "pages": len(pages), "samples": len(rows) * 6}))


if __name__ == "__main__":
    main()
