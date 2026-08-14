#!/usr/bin/env python3
"""Submit the first regenerated E37 V16 action dependency shot."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_SCRIPT = Path.home() / ".codex/skills/giggle-seedance2-gen/scripts/generation_api.py"
PROMPT = ROOT / "working_assets/e37_action_replacement_v16_20260804/prompts/E37-V16-A02A-ICE-SCREEN-RISE.txt"
START = ROOT / "working_assets/e37_action_replacement_v3_20260803/predecessor_tails/E37-R-B01_TAIL.png"
OUT = ROOT / "workflow/tasks/E37_V16_ACTION_A02A_SUBMIT_20260804.json"


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
    api = load_api()
    key = api.check_api_key()
    if not key:
        raise RuntimeError("GIGGLE_API_KEY missing")
    image = {"base64": base64.b64encode(START.read_bytes()).decode("ascii")}
    response = api.SeedanceClient(key).omni_video(
        prompt=PROMPT.read_text(encoding="utf-8"),
        images=[image],
        audios=None,
        videos=None,
        model="seedance-2.0-pro",
        duration=4,
        aspect_ratio="9:16",
        resolution="1080p",
        generating_count=1,
    )
    task_id = response.get("data", {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"response missing task_id: {response}")
    payload = {
        "schema": "qingshan.e37.v16_action_submit.v1",
        "episode": "E37",
        "task_key": "E37-V16-A02A-ICE-SCREEN-RISE",
        "task_id": task_id,
        "submitted_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "state": "remote_running",
        "model": "seedance-2.0-pro",
        "resolution": "1080p",
        "duration_seconds": 4,
        "generation_schedule_mode": "TAIL_CHAINED_SERIAL",
        "predecessor": "E37-R-B01-TAIL-ACCEPTED",
        "start_frame": str(START.relative_to(ROOT)),
        "start_frame_sha256": sha256(START),
        "prompt": str(PROMPT.relative_to(ROOT)),
        "prompt_sha256": sha256(PROMPT),
        "credits": {"pay": 0, "refund": 0, "net": 0, "state": "PENDING_EXACT_TASK_BOUND_RECONCILIATION", "repair_round_cap": 10000},
        "next_action": "Poll and harvest; run fixed-camera, real-time, prop-function, relational-scale, and tail-state gates. Only PASS extracts the exact final frame for A02B collision generation.",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(OUT), "sha256": sha256(OUT), "task_id": task_id}, ensure_ascii=False))


if __name__ == "__main__":
    main()
