#!/usr/bin/env python3
"""Run immediate audio/ASR checks and build a contact sheet for downloaded E19R sources."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import cv2
from faster_whisper import WhisperModel
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "configs/e19r_multimodal_binding_giggle_task_manifest_v1_not_final_20260717.json"
ASSET_DIR = ROOT / "assets/e19r_multimodal_binding_r1_20260717"
OUT = ROOT / "qa/auto_human_timeout_fallback_20260717/E19R_MULTIMODAL_BINDING_R1_PARTIAL_ASR_AUDIO_QA_20260717.json"
CONTACT = ROOT / "qa/auto_human_timeout_fallback_20260717/E19R_MULTIMODAL_BINDING_R1_PARTIAL_CONTACT_20260717.png"
MODEL_PATH = Path("/Users/rogerwu/.cache/huggingface/hub/models--Systran--faster-whisper-small/snapshots/536b0662742c02347bc0e980a01041f333bce120")


def chinese(text: str) -> str:
    return "".join(re.findall(r"[\u4e00-\u9fff]", text))


def recall(expected: str, got: str) -> float:
    a, b = chinese(expected), chinese(got)
    if not a:
        return 1.0
    if a in b:
        return 1.0
    return sum(block.size for block in SequenceMatcher(None, a, b).get_matching_blocks()) / len(a)


def video_metadata(path: Path) -> tuple[float, float, int, int]:
    cap = cv2.VideoCapture(str(path))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    duration = frames / fps if fps > 0 else 0.0
    return fps, duration, width, height


def sample_frames(path: Path) -> list[Image.Image]:
    cap = cv2.VideoCapture(str(path))
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    images: list[Image.Image] = []
    for ratio in (0.15, 0.5, 0.85):
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(count - 1, int(count * ratio))))
        ok, frame = cap.read()
        if not ok:
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        image.thumbnail((180, 320))
        images.append(image)
    cap.release()
    return images


def build_contact(rows: list[tuple[str, list[Image.Image]]], contact: Path) -> None:
    cell_w, cell_h, label_w = 180, 320, 130
    canvas = Image.new("RGB", (label_w + cell_w * 3, max(1, len(rows)) * cell_h), "black")
    draw = ImageDraw.Draw(canvas)
    for row_index, (label, frames) in enumerate(rows):
        y = row_index * cell_h
        draw.text((8, y + 10), label, fill="white")
        for col, frame in enumerate(frames):
            canvas.paste(frame, (label_w + col * cell_w, y))
    contact.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(contact)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--asset-dir", type=Path, default=ASSET_DIR)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--contact", type=Path, default=CONTACT)
    parser.add_argument("--expected-total", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.expanduser().resolve()
    asset_dir = args.asset_dir.expanduser().resolve()
    out = args.out.expanduser().resolve()
    contact = args.contact.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    task_by_id = {item["dialogue_id"]: item for item in manifest["tasks"]}
    videos = sorted(asset_dir.glob("DIA-*.mp4"))
    expected_total = args.expected_total or len(task_by_id)
    model = WhisperModel(str(MODEL_PATH), device="cpu", compute_type="int8")
    results = []
    contact_rows = []
    hard_failures = []
    for path in videos:
        dia_id = path.stem
        task = task_by_id[dia_id]
        segments, _info = model.transcribe(str(path), language="zh", vad_filter=True, beam_size=5)
        transcript = "".join(segment.text.strip() for segment in segments)
        score = recall(task["text"], transcript)
        fps, duration, width, height = video_metadata(path)
        failures = []
        if duration <= 0 or width != 720 or height != 1280:
            failures.append("INVALID_VIDEO_STREAM")
        if not transcript:
            failures.append("NO_RECOGNIZED_SPEECH")
        if score < 0.45:
            failures.append("EXPECTED_DIALOGUE_MISSING_OR_WRONG")
        if failures:
            hard_failures.append(f"{dia_id}:{','.join(failures)}")
        results.append({
            "dialogue_id": dia_id,
            "speaker": task["speaker"],
            "expected_text": task["text"],
            "transcript": transcript,
            "recall_score": round(score, 3),
            "fps": round(fps, 3),
            "duration_seconds": round(duration, 3),
            "resolution": f"{width}x{height}",
            "status": "PASS_MACHINE_AUDIO_ASR" if not failures else "FAIL",
            "failures": failures,
            "visual_review_status": "PENDING_CONTACT_REVIEW",
            "final_bind_allowed": False,
        })
        contact_rows.append((dia_id, sample_frames(path)))
    build_contact(contact_rows, contact)
    payload = {
        "schema": "qingshan.e19r.multimodal_binding_partial_asr_audio_qa.v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "status": "PASS_MACHINE_AUDIO_ASR_VISUAL_PENDING" if not hard_failures else "FAIL",
        "downloaded_count": len(videos),
        "expected_total_count": expected_total,
        "contact_sheet_ref": str(contact.relative_to(ROOT)),
        "results": results,
        "hard_failures": hard_failures,
        "admission": {
            "candidate_bind_allowed": False,
            "final_bind_allowed": False,
            "edit_admission_allowed": False,
            "package_allowed": False,
            "platform_action_allowed": False,
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "downloaded": len(videos), "failures": len(hard_failures), "out": str(out), "contact": str(contact)}, ensure_ascii=False))
    return 0 if not hard_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
