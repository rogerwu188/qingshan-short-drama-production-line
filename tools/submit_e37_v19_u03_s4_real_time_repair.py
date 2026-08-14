#!/usr/bin/env python3
"""Submit the materially changed E37 U03-S4 real-time fixed-camera repair."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_SCRIPT = Path.home() / ".codex/skills/giggle-seedance2-gen/scripts/generation_api.py"
PROMPT = ROOT / "working_assets/e37_v19_u03_s4_real_time_repair_20260804/prompts/E37-U03-S4-R2-LOCKED-REALTIME.txt"
OUT = ROOT / "workflow/tasks/E37_V19_U03_S4_R2_REALTIME_SUBMIT_20260804.json"
REFERENCES = [
    ROOT / "working_assets/e37_stills_20260802/candidates/E37_E37-CW-U03-A2-STILL-V2_ZERO_CREDIT_ALT.png",
    ROOT / "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg",
    ROOT / "assets/reference/e37_plus_20260729/characters/CHAR-chenji-age20-user-turnaround-canonical-v1-20260729.png",
]


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
    for path in [PROMPT, *REFERENCES]:
        if not path.is_file():
            raise SystemExit(f"Missing input: {path}")
    api = load_api()
    key = api.check_api_key()
    if not key:
        raise SystemExit("GIGGLE_API_KEY missing")
    images = [{"base64": base64.b64encode(path.read_bytes()).decode("ascii")} for path in REFERENCES]
    result = api.SeedanceClient(key).omni_video(
        prompt=PROMPT.read_text(encoding="utf-8"),
        images=images,
        audios=None,
        videos=None,
        model="seedance-2.0-pro",
        duration=7,
        aspect_ratio="9:16",
        resolution="1080p",
        generating_count=1,
    )
    task_id = (result.get("data") or {}).get("task_id")
    if not task_id:
        raise SystemExit(f"Response missing task_id: {result}")
    payload = {
        "schema": "qingshan.e37.v19_u03_s4_realtime_submit.v1",
        "episode": "E37",
        "task_key": "E37-U03-S4-R2-LOCKED-REALTIME",
        "task_id": task_id,
        "submitted_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "state": "remote_running",
        "prompt": str(PROMPT.relative_to(ROOT)),
        "prompt_sha256": sha256(PROMPT),
        "reference_images": [str(path.relative_to(ROOT)) for path in REFERENCES],
        "reference_sha256_order": [sha256(path) for path in REFERENCES],
        "model": "seedance-2.0-pro",
        "resolution": "1080p",
        "duration_seconds": 7,
        "tempo": "REAL_TIME_1X",
        "camera_policy": "ONE_LOCKED_TRIPOD_COMPOSITION_NO_CUT_NO_CAMERA_MOTION",
        "material_change_from_v15": "TWO_COMPOSITIONS_REPLACED_BY_ONE_LOCKED_COMPOSITION_AND_SUBSECOND_CONTINUOUS_ACTOR_MICROACTIONS",
        "credits": {"pay": 0, "refund": 0, "net": 0, "state": "PENDING_EXACT_TASK_BOUND_RECONCILIATION"},
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"task_id": task_id, "receipt": str(OUT), "receipt_sha256": sha256(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
