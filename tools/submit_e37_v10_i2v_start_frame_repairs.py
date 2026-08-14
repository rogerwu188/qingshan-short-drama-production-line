#!/usr/bin/env python3
"""Submit E37 V10 failed-only repairs through exact-scene start-frame I2V."""

import base64
import hashlib
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_SCRIPT = Path.home() / ".codex/skills/giggle-seedance2-gen/scripts/generation_api.py"
OUT = ROOT / "workflow/tasks/E37_V10_I2V_START_FRAME_REPAIR_SUBMIT_V1_20260803.json"
BASE = ROOT / "working_assets/e37_preproduction_20260803/v10_i2v_start_frame_repairs"
TASKS = {
    6: {
        "duration": 5,
        "prompt": BASE / "E37-L006-I2V-EXACT-SCENE-START-CHANGED-V4.txt",
        "start_frame": BASE / "E37-L006-V10-EXACT-START-FRAME.png",
        "source_failure": "V9 dialogue recall 0.2 and hard Chenji age/identity drift",
    },
    19: {
        "duration": 6,
        "prompt": BASE / "E37-L019-I2V-EXACT-SCENE-START-CHANGED-V4.txt",
        "start_frame": BASE / "E37-L019-V10-EXACT-START-FRAME.png",
        "source_failure": "V9 terminal copyright restriction after omni reference route",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_api():
    spec = importlib.util.spec_from_file_location("giggle_seedance_api", API_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def submit(line: int, item: dict) -> dict:
    api = load_api()
    key = api.check_api_key()
    if not key:
        raise RuntimeError("GIGGLE_API_KEY missing")
    start_frame = base64.b64encode(item["start_frame"].read_bytes()).decode("ascii")
    result = api.SeedanceClient(key).image_to_video(
        prompt=item["prompt"].read_text(encoding="utf-8"),
        start_frame={"base64": start_frame}, end_frame=None,
        model="seedance-2.0-pro", duration=item["duration"],
        aspect_ratio="9:16", resolution="720p", generating_count=1,
    )
    task_id = (result.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"line {line}: response missing task_id: {result}")
    return {
        "line": line,
        "task_id": task_id,
        "submitted_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "duration_seconds": item["duration"],
        "model": "seedance-2.0-pro",
        "route": "image_to_video_exact_scene_start_frame",
        "prompt": str(item["prompt"].relative_to(ROOT)),
        "prompt_sha256": sha256(item["prompt"]),
        "start_frame": str(item["start_frame"].relative_to(ROOT)),
        "start_frame_sha256": sha256(item["start_frame"]),
        "source_failure": item["source_failure"],
        "status": "submitted",
    }


def main() -> None:
    for item in TASKS.values():
        for path in (item["prompt"], item["start_frame"]):
            if not path.is_file():
                raise RuntimeError(f"missing input: {path}")
    rows, errors = [], []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(submit, line, item): line for line, item in TASKS.items()}
        for future in as_completed(futures):
            try:
                rows.append(future.result())
            except Exception as exc:
                errors.append({"line": futures[future], "error": str(exc)})
    rows.sort(key=lambda row: row["line"])
    payload = {
        "schema": "qingshan.e37.v10_i2v_start_frame_repair_submit.v1",
        "episode": "E37",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "SUBMITTED" if len(rows) == 2 and not errors else "PARTIAL_OR_FAILED",
        "source_cl2x": "CL2X-936",
        "material_change": "Changed provider route from omni character-reference generation to image-to-video using exact clean scene frames extracted from prior local E37 footage; prompts are failure-conditioned and explicitly rights-cleared.",
        "tasks": rows,
        "errors": errors,
        "credits": {
            "settled_before_submit": {"pay": 9413, "refund": 1553, "net": 7860},
            "maximum_projected_new_net": 220,
            "maximum_projected_episode_net": 8080,
            "episode_cap": 10000,
            "minimum_projected_headroom": 1920,
        },
        "next_action": "Poll and harvest both task IDs; reconcile exact credits and run failed-only native-dialogue, identity, mouth, cadence, OCR and direct audiovisual QA.",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(OUT), "receipt_sha256": sha256(OUT), "tasks": rows, "errors": errors}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
