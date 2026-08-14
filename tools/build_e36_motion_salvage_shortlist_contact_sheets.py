#!/usr/bin/env python3
"""Build paired contact sheets for E36 unadmitted-motion salvage review."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "qa/e36_agentcut_20260730/e36_motion_salvage_shortlist_v1"

PAIRS = [
    {
        "unit": "U06",
        "accepted": "working_assets/e36_v2_stills_20260728/local_fight_fallbacks/E36-CW-U06-LOCAL-ACTION-DETAIL-V6.mp4",
        "candidate": "working_assets/e36_v2_stills_20260728/local_fight_fallbacks/E36-CW-U06-LOCAL-ACTION-DETAIL-V1.mp4",
    },
    {
        "unit": "U07",
        "accepted": "working_assets/e36_v2_stills_20260728/local_fight_fallbacks/E36-CW-U07-LOCAL-ACTION-DETAIL-V2.mp4",
        "candidate": "working_assets/e36_v2_stills_20260728/local_fight_fallbacks/E36-CW-U07-LOCAL-ACTION-DETAIL-V1.mp4",
    },
    {
        "unit": "U11",
        "accepted": "working_assets/e36_recovery_10000_20260730/u11_r1b_video/E36_E36-CW-U11-R1B-EXACT-AUDIO-RECOVERY-10000_9afd46a1-07dd-4897-9d1d-3eb617ae21f2.mp4",
        "candidate": "working_assets/e36_recovery_10000_20260730/u11_r1a_video/E36_E36-CW-U11-R1A-EXACT-AUDIO-RECOVERY-10000_ced5c13a-d572-4ab1-a978-4c677cfdead6.mp4",
    },
    {
        "unit": "U16B",
        "accepted": "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/video_repair_v2_outputs/E36_E36-CW-U16B-VIDEO-V1_41086408-36bb-454b-b956-01125c388b09_TICKET_TEXT_TRIM4P7_V2.mp4",
        "candidate": "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/video_repair_v2_outputs/E36_E36-CW-U16B-VIDEO-V1_41086408-36bb-454b-b956-01125c388b09_TICKET_TEXT_TAIL_REPAIR_V2.mp4",
    },
    {
        "unit": "U19B",
        "accepted": "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/video_repair_v2_outputs/E36_E36-CW-U19B-VIDEO-V3_b792796e-d8d5-457b-afdf-f88ca21d49d9.mp4",
        "candidate": "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728/video_repair_v2_outputs/E36_E36-CW-U19B-VIDEO-V1_99c4219e-2341-400e-8b84-a3bd1517a1ee.mp4",
    },
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_samples(path: Path, count: int = 6) -> tuple[list[np.ndarray], list[float], float]:
    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open {path}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 24.0
    frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frames / fps
    times = np.linspace(0.0, max(0.0, duration - 1.0 / fps), count)
    images = []
    for seconds in times:
        capture.set(cv2.CAP_PROP_POS_MSEC, float(seconds) * 1000.0)
        ok, frame = capture.read()
        if not ok:
            raise RuntimeError(f"cannot read {path} at {seconds:.3f}s")
        images.append(frame)
    capture.release()
    return images, [round(float(value), 3) for value in times], duration


def cell(frame: np.ndarray, seconds: float, label: str) -> np.ndarray:
    frame = cv2.resize(frame, (180, 320), interpolation=cv2.INTER_AREA)
    canvas = np.zeros((350, 180, 3), dtype=np.uint8)
    canvas[:320] = frame
    cv2.putText(canvas, label, (5, 334), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(canvas, f"t={seconds:.2f}s", (5, 348), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (190, 220, 255), 1, cv2.LINE_AA)
    return canvas


def build_sheet(unit: str, accepted: Path, candidate: Path) -> tuple[Path, dict]:
    accepted_frames, accepted_times, accepted_duration = read_samples(accepted)
    candidate_frames, candidate_times, candidate_duration = read_samples(candidate)
    accepted_row = np.hstack([cell(frame, seconds, "ACCEPTED") for frame, seconds in zip(accepted_frames, accepted_times)])
    candidate_row = np.hstack([cell(frame, seconds, "CANDIDATE") for frame, seconds in zip(candidate_frames, candidate_times)])
    header = np.zeros((48, accepted_row.shape[1], 3), dtype=np.uint8)
    cv2.putText(header, f"E36 {unit} motion salvage comparison", (12, 31), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    sheet = np.vstack([header, accepted_row, candidate_row])
    out = OUT / f"E36_{unit}_ACCEPTED_VS_UNADMITTED_CONTACT_SHEET_V1.jpg"
    if not cv2.imwrite(str(out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 92]):
        raise RuntimeError(f"cannot write {out}")
    return out, {
        "unit": unit,
        "accepted": {
            "path": str(accepted.relative_to(ROOT)),
            "sha256": sha256(accepted),
            "duration_seconds": round(accepted_duration, 6),
            "sample_times_seconds": accepted_times,
        },
        "candidate": {
            "path": str(candidate.relative_to(ROOT)),
            "sha256": sha256(candidate),
            "duration_seconds": round(candidate_duration, 6),
            "sample_times_seconds": candidate_times,
        },
        "contact_sheet": str(out.relative_to(ROOT)),
        "contact_sheet_sha256": sha256(out),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    records = []
    for pair in PAIRS:
        _, record = build_sheet(
            pair["unit"],
            ROOT / pair["accepted"],
            ROOT / pair["candidate"],
        )
        records.append(record)
    manifest = {
        "schema": "qingshan.e36_motion_salvage_contact_sheet_manifest.v1",
        "episode": "E36",
        "sampling": "six evenly spaced frames per accepted/candidate clip; direct visual review still required",
        "records": records,
    }
    output = OUT / "E36_MOTION_SALVAGE_SHORTLIST_CONTACT_SHEET_MANIFEST_V1.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
