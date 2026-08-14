#!/usr/bin/env python3
"""Build a materially changed U06 R2 after a fully refunded remote failure."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
SOURCE = PROD / "E36_U06_EPISODE_SINGLE_UNIT_V1.json"
PROMPT = PROD / "video_prompts_repair_v7/E36-CW-U06-R2.txt"
OUT = PROD / "E36_U06_EPISODE_SINGLE_UNIT_RETRY_R2.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


config = json.loads(SOURCE.read_text(encoding="utf-8"))
task = config["tasks"][0]
task.update({
    "task_key": "E36-CW-U06-VIDEO-R2",
    "source_id": "E36-CW-U06-R2",
    "batch_id": "E36-U06-VIDEO-R2",
    "prompt_path": rel(PROMPT),
    "prompt_file": rel(PROMPT),
    "prompt_sha256": sha(PROMPT),
    "status": "READY",
    "max_retries": 0,
    "previous_remote_failure_task_id": "0cfaabaa-a49f-48d7-aea1-a1bef6087745",
    "changed_input_reason": "R2 replaces the long combat wording with concise non-injury film-stunt choreography while preserving the canonical garment-graze, weapon-contact, rebound and uninjured terminal state."
})
task["duration_plan"]["rationale"] = "Five seconds present a concise, non-injury costume-stunt garment graze, visible prop-weapon block, rebound and safe terminal state."
task["performance_spec"]["motion_beats"][0]["action"] = "无刃道具刀擦裂真棋外袍衣摆，阴神以寒铁道具正面格挡并反向推开，皎兔带真棋退半步"
task["performance_spec"]["motion_beats"][0]["contact_point"] = "先为无刃道具刀与外袍衣摆边缘，再为两件古装道具兵器的清楚金属交叉点；均不接触人体"
task["performance_spec"]["motion_beats"][0]["end_state"] = "道具刀远离真棋，寒铁横挡其间，真棋只有衣摆裂开且身体安全完整"

manifest = json.loads((PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V13.json").read_text(encoding="utf-8"))
for row in manifest["rows"]:
    if row["unit_id"] == "U06":
        row["prompt_path"] = rel(PROMPT)
        row["prompt_sha256"] = sha(PROMPT)
(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V14.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
config["complete_video_prompt_manifest_ref"] = rel(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V14.json")
config["tasks"] = [task]
OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(OUT)
