#!/usr/bin/env python3
"""Submit E37 V17 Long B after SHA, memory, model and credit gates pass."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API_SCRIPT = Path.home() / ".codex/skills/giggle-seedance2-gen/scripts/generation_api.py"
COMPILED = ROOT / "workflow/tasks/E37_V17_LONG_B_R2_FIXED_AXIS_MULTI_KEYFRAME_COMPILED_20260804.json"
PROMPT = ROOT / "working_assets/e37_action_replacement_v17_20260804/prompts/E37-V17-LONG-B-R2-15S-PRO-OMNI.txt"
CREDITS = ROOT / "workflow/tasks/E37_V15_V16_EXACT_CREDIT_RECONCILIATION_20260804.json"
OUT = ROOT / "workflow/tasks/E37_V17_LONG_B_R2_15S_PRO_OMNI_SUBMIT_20260804.json"


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
    compiled = json.loads(COMPILED.read_text(encoding="utf-8"))
    credits = json.loads(CREDITS.read_text(encoding="utf-8"))
    memory = compiled.get("local_lora_memory") or {}
    required_memories = {
        "LORA-SD2-001-REFERENCE-GEOMETRY-LEAK",
        "LORA-SD2-002-UNIQUE-PROP-GROUP-REACTION",
        "LORA-SD2-003-ADJACENT-CAMERA-TRAJECTORY",
    }
    if compiled.get("contract") != "15s_ordered_multi_keyframe_spatial_continuity":
        raise RuntimeError("compiled contract is not the V17 long-take contract")
    if compiled.get("model") != "seedance-2.0-pro" or compiled.get("resolution") != "1080p":
        raise RuntimeError("compiled model/resolution gate failed")
    if memory.get("precompiled_before_paid_generation") is not True:
        raise RuntimeError("local LoRA failure memory was not precompiled")
    if not required_memories.issubset(set(memory.get("applied_sample_ids") or [])):
        raise RuntimeError("required admitted prompt memories are missing")
    if not credits.get("within_cap") or int(credits.get("net", 0)) >= int(credits.get("repair_round_cap", 0)):
        raise RuntimeError("repair-round credit gate failed")

    images = []
    refs = []
    for row in compiled["keyframes"]:
        path = ROOT / row["image_path"]
        if sha256(path) != row["image_sha256"]:
            raise RuntimeError(f"keyframe SHA changed: {path}")
        images.append({"base64": base64.b64encode(path.read_bytes()).decode("ascii")})
        refs.append({"reference": row["reference"], "path": row["image_path"], "sha256": row["image_sha256"]})

    api = load_api()
    key = api.check_api_key()
    if not key:
        raise RuntimeError("GIGGLE_API_KEY missing")
    response = api.SeedanceClient(key).omni_video(
        prompt=PROMPT.read_text(encoding="utf-8"),
        images=images,
        audios=None,
        videos=None,
        model="seedance-2.0-pro",
        duration=15,
        aspect_ratio="9:16",
        resolution="1080p",
        generating_count=1,
    )
    task_id = (response.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"response missing task_id: {response}")
    payload = {
        "schema": "qingshan.e37.v17_long_take_submit.v1",
        "episode": "E37",
        "task_key": "E37-V17-LONG-B-R2-FIXED-EXTERIOR-AXIS-SAME-BREACH",
        "task_id": task_id,
        "submitted_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "state": "remote_running",
        "model": "seedance-2.0-pro",
        "resolution": "1080p",
        "duration_seconds": 15,
        "generation_mode": "omni_multi_keyframe_long_take",
        "compiled_manifest": str(COMPILED.relative_to(ROOT)),
        "compiled_manifest_sha256": sha256(COMPILED),
        "prompt": str(PROMPT.relative_to(ROOT)),
        "prompt_sha256": sha256(PROMPT),
        "local_lora_memory_sha256": memory["sha256"],
        "applied_memory_sample_ids": memory["applied_sample_ids"],
        "references": refs,
        "credits_before_submit": {
            "pay": credits["pay"],
            "refund": credits["refund"],
            "net": credits["net"],
            "repair_round_cap": credits["repair_round_cap"]
        },
        "credits": {"pay": 0, "refund": 0, "net": 0, "state": "PENDING_EXACT_TASK_BOUND_RECONCILIATION"},
        "qa_policy": "PASS_AT_60_UNLESS_IDENTITY_SAFETY_ERA_OCR_OR_MEDIA_INTEGRITY_HARD_FAILURE",
        "next_action": "Poll and harvest, then score physical causality, same-aperture crossing, unique ledger ownership, real-time cadence and motivated camera motion."
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(OUT), "task_id": task_id, "sha256": sha256(OUT)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
