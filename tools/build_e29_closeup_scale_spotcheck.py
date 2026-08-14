#!/usr/bin/env python3
"""Build an exact-SHA shot-scale spot check for selected E29 close-up states."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e29_claude_writer_v1_20260722"
ADMISSION = PRODUCTION / "E29_VIDEO_UNIT_STATE_POOL_ADMISSION_V1.json"
OUT = ROOT / "qa/e29_closeup_scale_spotcheck_20260722"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prompt_path(state_id: str) -> Path:
    if re.search(r"-C\d+$", state_id):
        return PRODUCTION / "image_prompts_full_plan_v2" / f"{state_id}.txt"
    return PRODUCTION / "image_prompts_v1" / f"{state_id}.txt"


def main() -> int:
    admission = json.loads(ADMISSION.read_text(encoding="utf-8"))
    items = []
    inventory = []
    for unit in admission.get("units", []):
        for state in unit.get("selected_states", []):
            state_id = state["state_id"]
            prompt = prompt_path(state_id)
            if not prompt.is_file():
                raise FileNotFoundError(prompt)
            prompt_text = prompt.read_text(encoding="utf-8")
            match = re.search(r"景别\s*[=:：]\s*([^；。\n]+)", prompt_text, re.I)
            scale = match.group(1).strip() if match else "UNKNOWN"
            if not re.search(r"close|macro|tight|特写|近景", scale, re.I):
                continue
            media = Path(state["absolute_path"])
            digest = sha256(media)
            if digest != state["sha256"]:
                raise RuntimeError(f"SHA drift: {state_id}")
            metadata = {
                "episode": "E29",
                "unit_id": unit["unit_id"],
                "scene_id": unit["scene_id"],
                "state_id": state_id,
                "candidate_sha256": digest,
                "expected_shot_scale": scale,
                "source_prompt": str(prompt.relative_to(ROOT)),
                "source_admission": state["admission"],
                "review_focus": [
                    f"shot scale must visually read as {scale}, not a generic medium or wide composition",
                    "the intended close subject, prop, body part, or facial reaction must dominate the frame",
                    "foreground/midground/background boilerplate must not dilute the requested close framing",
                    "the decisive story action or recognition detail must remain immediately readable",
                    "canonical identity, anatomy, prop ownership, location and time of day must remain intact",
                ],
            }
            items.append({
                "path": str(media),
                "scope": "shot",
                "kind": "image",
                "importance": "critical",
                "pass_score": 4.0,
                "clip_id": state_id,
                "metadata": metadata,
                "required_capabilities": ["image_analysis"],
                "run_regression_ci": True,
                "use_existing_tools": True,
            })
            inventory.append({
                "state_id": state_id,
                "unit_id": unit["unit_id"],
                "expected_shot_scale": scale,
                "path": str(media),
                "sha256": digest,
                "source_admission": state["admission"],
            })

    OUT.mkdir(parents=True, exist_ok=True)
    request = OUT / "E29_SELECTED_CLOSEUP_STATE_SCALE_REVIEW_REQUEST.json"
    inventory_path = OUT / "E29_SELECTED_CLOSEUP_STATE_SCALE_INVENTORY.json"
    request.write_text(json.dumps({"items": items, "workers": 4}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    inventory_path.write_text(json.dumps({
        "schema": "qingshan.e29.closeup_scale_inventory.v1",
        "episode": "E29",
        "status": "READY_FOR_EXACT_SHA_SCALE_REVIEW",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "item_count": len(inventory),
        "items": inventory,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "items": len(items),
        "request": str(request),
        "request_sha256": sha256(request),
        "inventory": str(inventory_path),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
