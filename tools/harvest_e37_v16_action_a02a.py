#!/usr/bin/env python3
"""Poll and harvest the first E37 V16 action dependency shot."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
API_SCRIPT = Path.home() / ".codex/skills/giggle-seedance2-gen/scripts/generation_api.py"
FFMPEG = ROOT / ".video_deps/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1"
SUBMIT = ROOT / "workflow/tasks/E37_V16_ACTION_A02A_SUBMIT_20260804.json"
OUT_DIR = ROOT / "working_assets/e37_action_replacement_v16_20260804/outputs"
QA_DIR = ROOT / "qa/e37_action_replacement_v16_20260804/a02a"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_api():
    spec = importlib.util.spec_from_file_location("giggle_seedance_api", API_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {API_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    submit = json.loads(SUBMIT.read_text(encoding="utf-8"))
    api = load_api()
    key = api.check_api_key()
    if not key:
        raise RuntimeError("GIGGLE_API_KEY missing")
    client = api.SeedanceClient(key)
    result = client.query_task(submit["task_id"])
    data = result.get("data", {})
    status = data.get("status", "")
    urls = client.extract_urls(result)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    QA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "qingshan.e37.v16_action_harvest.v1",
        "task_key": submit["task_key"],
        "task_id": submit["task_id"],
        "queried_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": status,
        "err_msg": data.get("err_msg", ""),
        "urls": urls,
    }
    if status == "completed" and urls:
        video = OUT_DIR / f"E37_V16_A02A_ICE_SCREEN_RISE_{submit['task_id']}.mp4"
        if not video.exists():
            response = requests.get(urls[0], timeout=180)
            response.raise_for_status()
            video.write_bytes(response.content)
        tail = OUT_DIR / "E37_V16_A02A_ACCEPTED_TAIL_CANDIDATE.jpg"
        subprocess.run(
            [str(FFMPEG), "-y", "-ss", "3.90", "-i", str(video), "-frames:v", "1", str(tail)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        sheet = QA_DIR / "E37_V16_A02A_2FPS_CONTACT_SHEET.jpg"
        subprocess.run(
            [
                str(FFMPEG), "-y", "-i", str(video), "-vf",
                "fps=2,scale=360:-2,tile=4x2:padding=4:margin=4", "-frames:v", "1", str(sheet),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        payload.update({
            "output": str(video.relative_to(ROOT)),
            "output_sha256": sha256(video),
            "tail_candidate": str(tail.relative_to(ROOT)),
            "tail_candidate_sha256": sha256(tail),
            "contact_sheet": str(sheet.relative_to(ROOT)),
            "contact_sheet_sha256": sha256(sheet),
            "admission": "PENDING_DIRECT_NORMAL_SPEED_AND_FRAME_REVIEW",
        })
    receipt = QA_DIR / "E37_V16_A02A_HARVEST.json"
    receipt.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(receipt), "sha256": sha256(receipt), **payload}, ensure_ascii=False))


if __name__ == "__main__":
    main()
