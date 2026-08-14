#!/usr/bin/env python3
"""Submit materially changed E37 line 6 and 19 failed-only repairs."""

import base64
import hashlib
import importlib.util
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_SCRIPT = Path.home() / ".codex/skills/giggle-seedance2-gen/scripts/generation_api.py"
OUT = ROOT / "workflow/tasks/E37_V9_FAILED_ONLY_PROMPT_REPAIR_SUBMIT_V1_20260803.json"
TASKS = {
    6: {
        "duration": 5,
        "prompt": ROOT / "working_assets/e37_preproduction_20260803/v9_failed_only_prompt_repairs/E37-L006-NO-TITLE-YOUNG-CHENJI-CHANGED-V3.txt",
        "reference": ROOT / "assets/reference/e37_plus_20260729/characters/CHAR-chenji-age20-user-turnaround-canonical-v1-20260729.png",
    },
    19: {
        "duration": 6,
        "prompt": ROOT / "working_assets/e37_preproduction_20260803/v9_failed_only_prompt_repairs/E37-L019-NO-SUBTITLE-EXACT-YUNYANG-CHANGED-V3.txt",
        "reference": ROOT / "assets/reference/e36_20260729/characters/CHAR-yunyang-age17-canonical-v1-20260729.png",
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
    image = base64.b64encode(item["reference"].read_bytes()).decode("ascii")
    result = api.SeedanceClient(key).omni_video(
        prompt=item["prompt"].read_text(encoding="utf-8"),
        images=[{"base64": image}], audios=None, videos=None,
        model="seedance-2.0-pro", duration=item["duration"],
        aspect_ratio="9:16", resolution="720p", generating_count=1,
    )
    task_id = (result.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"line {line}: response missing task_id")
    return {
        "line": line, "task_id": task_id,
        "submitted_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "duration_seconds": item["duration"],
        "prompt": str(item["prompt"].relative_to(ROOT)), "prompt_sha256": sha256(item["prompt"]),
        "reference": str(item["reference"].relative_to(ROOT)), "reference_sha256": sha256(item["reference"]),
        "status": "submitted",
    }


def main() -> None:
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
        "schema": "qingshan.e37.v9_failed_only_prompt_repair_submit.v1", "episode": "E37",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "SUBMITTED" if len(rows) == 2 and not errors else "PARTIAL_OR_FAILED",
        "source_cl2x": "CL2X-936",
        "material_change": "V8 failure-conditioned first-frame speech lock, explicit provider title/audio prohibition, tighter young-identity lock, and full no-subtitle/no-text lock.",
        "tasks": rows, "errors": errors,
        "credits": {"settled_before_submit": {"pay": 9193, "refund": 1433, "net": 7760}, "maximum_projected_new_net": 220, "maximum_projected_episode_net": 7980, "episode_cap": 10000, "minimum_projected_headroom": 2020},
        "next_action": "Poll and harvest both task IDs; reconcile exact charges and run failed-only native-dialogue, identity, mouth, cadence, OCR and direct audiovisual QA without replay.",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(OUT), "receipt_sha256": sha256(OUT), "tasks": rows, "errors": errors}, ensure_ascii=False))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
