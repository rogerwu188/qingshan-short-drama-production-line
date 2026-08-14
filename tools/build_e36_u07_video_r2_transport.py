#!/usr/bin/env python3
"""Build U07 R2 with one accepted action anchor and reduced multimodal transport."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_stills_repair_20260729/u07_video_runtime"

def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))

def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))

prompt = PROD / "video_prompts_repair_v9/E36-CW-U07-R2.txt"
anchor = ROOT / "working_assets/e36_v2_stills_20260728/u07_candidates_v4/E36-CW-U07-A4-STILL-V4_2047b9ac-5635-410a-b5c3-b29a196eaf67.png"
config = read(PROD / "E36_U07_EPISODE_SINGLE_UNIT_V1.json")
config["status"] = "READY_FOR_SUPERVISOR_PRECHECK"
prompt_manifest = read(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V15.json")
for row in prompt_manifest["rows"]:
    if row["unit_id"] == "U07":
        row["prompt_path"] = rel(prompt)
        row["prompt_sha256"] = sha(prompt)
write(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V16.json", prompt_manifest)
config["complete_video_prompt_manifest_ref"] = rel(PROD / "E36_COMPLETE_VIDEO_PROMPT_MANIFEST_V16.json")
task = copy.deepcopy(config["tasks"][0])
task.update({
    "status": "READY",
    "task_key": "E36-CW-U07-VIDEO-R2",
    "batch_id": "E36-U07-VIDEO-R2",
    "prompt_path": rel(prompt),
    "prompt_file": rel(prompt),
    "prompt_sha256": sha(prompt),
    "max_retries": 0
})
task["duration_plan"]["rationale"] = "Five seconds cover the same canonical action using one accepted composite authority and reduced transport complexity."
config["tasks"] = [task]
config["base_batch_note"] = "MATERIAL_CHANGE_AFTER_REMOTE_FAILURE: concise three-beat no-dialogue choreography replaces the verbose R1 prompt while canonical identity and accepted action anchors remain bound."
write(PROD / "E36_U07_EPISODE_SINGLE_UNIT_RETRY_R2.json", config)
print(PROD / "E36_U07_EPISODE_SINGLE_UNIT_RETRY_R2.json")
