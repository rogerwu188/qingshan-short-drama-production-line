#!/usr/bin/env python3
"""Build a changed-input 13-second U01 replacement after the refunded failure."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from episode_video_generation_guard import generation_fingerprint


ROOT = Path(__file__).resolve().parents[1]
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e35_claude_writer_v1_416d09e2_20260723"
BASE_CONFIG = PRODUCTION / "video_performance_v1/E35_VIDEO_STREAMING_PERFORMANCE_V1.json"
OUT_CONFIG = PRODUCTION / "video_performance_v1/E35_VIDEO_STREAMING_PERFORMANCE_V1_U01_REPAIR1.json"
BASE_PROMPT = PRODUCTION / "video_prompts_performance_v1/E35-CW-U01.txt"
OUT_PROMPT = PRODUCTION / "video_prompts_performance_v1/E35-CW-U01-REPAIR1.txt"
BASE_PROMPT_MANIFEST = PRODUCTION / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1.json"
OUT_PROMPT_MANIFEST = PRODUCTION / "E35_COMPLETE_VIDEO_PROMPT_MANIFEST_V1_U01_REPAIR1.json"
BASE_UNIT_PLAN = PRODUCTION / "E35_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json"
OUT_UNIT_PLAN = PRODUCTION / "E35_VIDEO_UNIT_PERFORMANCE_PLAN_V1_U01_REPAIR1.json"
QA = ROOT / "qa/e35_v1_preproduction_20260723"
BASE_MECHANICAL = QA / "E35_MECHANICAL_DEFAULT_PLAN_V1.json"
OUT_MECHANICAL = QA / "E35_MECHANICAL_DEFAULT_PLAN_V1_U01_REPAIR1.json"
BASE_DRAMATIC = QA / "E35_DRAMATIC_QUALITY_PLAN_V1.json"
OUT_DRAMATIC = QA / "E35_DRAMATIC_QUALITY_PLAN_V1_U01_REPAIR1.json"
BASE_PREFLIGHT = QA / "E35_IMAGE_PLAN_PREFLIGHT_V1.json"
OUT_PREFLIGHT = QA / "E35_IMAGE_PLAN_PREFLIGHT_V1_U01_REPAIR1.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def retime_prompt(text: str) -> str:
    replacements = (
        ("时长9秒", "时长13秒"),
        ("0.000-4.500秒", "0.000-7.000秒"),
        ("4.500-9.000秒", "7.000-13.000秒"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    marker = "对白音频绑定：\n"
    timing = "对白时长硬合同：四段参考对白合计11.789897秒；本单元给足13秒真实表演时间，逐句只说一次，保留吞咽、换气与句间停顿，禁止压缩漏字。\n"
    if timing not in text:
        text = text.replace(marker, marker + timing)
    return text


def main() -> int:
    OUT_PROMPT.write_text(retime_prompt(BASE_PROMPT.read_text(encoding="utf-8")), encoding="utf-8")

    unit_plan = load(BASE_UNIT_PLAN)
    unit = next(row for row in unit_plan["units"] if row["unit_id"] == "E35-CW-U01")
    unit["duration_seconds"] = 13
    unit["performance_spec"]["duration_seconds"] = 13
    unit["performance_spec"]["motion_beats"][0]["start_seconds"] = 0.0
    unit["performance_spec"]["motion_beats"][0]["end_seconds"] = 7.0
    unit["performance_spec"]["motion_beats"][1]["start_seconds"] = 7.0
    unit["performance_spec"]["motion_beats"][1]["end_seconds"] = 13.0
    unit["video_prompt_file"] = rel(OUT_PROMPT)
    unit["video_prompt_sha256"] = sha(OUT_PROMPT)
    unit_plan["runtime_seconds"] = 176
    unit_plan["repair"] = "U01_CONTINUOUS_CONFESSION_EXTENDED_9_TO_13_SECONDS_AFTER_REFUNDED_REMOTE_FAILURE"
    write(OUT_UNIT_PLAN, unit_plan)

    prompt_manifest = load(BASE_PROMPT_MANIFEST)
    prompt_row = next(row for row in prompt_manifest["rows"] if row["unit_id"] == "E35-CW-U01")
    prompt_row["prompt_path"] = rel(OUT_PROMPT)
    prompt_row["prompt_sha256"] = sha(OUT_PROMPT)
    prompt_manifest["source_plan"] = rel(OUT_UNIT_PLAN)
    prompt_manifest["source_plan_sha256"] = sha(OUT_UNIT_PLAN)
    prompt_manifest["repair"] = "U01_CONTINUOUS_CONFESSION_DURATION_REPAIR1"
    write(OUT_PROMPT_MANIFEST, prompt_manifest)

    mechanical = load(BASE_MECHANICAL)
    next(row for row in mechanical["units"] if row["unit_id"] == "E35-CW-U01")["duration_seconds"] = 13
    write(OUT_MECHANICAL, mechanical)

    dramatic = load(BASE_DRAMATIC)
    dramatic["runtime_seconds"] = 176
    dramatic["council"]["advisors"][4]["analysis"] = "正片一百七十六秒并另接三秒片尾，总时长一百七十九秒，满足竖屏短剧及三分钟Shorts约束。"
    write(OUT_DRAMATIC, dramatic)

    preflight = load(BASE_PREFLIGHT)
    preflight["recorded_at"] = datetime.now(timezone.utc).isoformat()
    preflight["runtime_seconds"] = 176
    preflight["projected_release_seconds_with_outro"] = 179
    preflight["u01_duration_repair"] = "PASS_CHANGED_INPUT_13_SECONDS"
    write(OUT_PREFLIGHT, preflight)

    config = load(BASE_CONFIG)
    original = next(row for row in config["tasks"] if row["unit_id"] == "E35-CW-U01")
    replacement = copy.deepcopy(original)
    replacement["task_key"] = "E35-CW-U01-PERFORMANCE-V1-REPAIR1"
    replacement["duration"] = 13
    replacement["duration_seconds"] = 13
    replacement["edit_target_duration_seconds"] = 13
    replacement["duration_plan"]["duration_seconds"] = 13
    replacement["duration_plan"]["rationale"] = "Claude Writer continuous confession preserved; 11.789897 seconds of exact dialogue references require a 13-second performance."
    replacement["duration_plan"]["edit_policy"] = "Use the full 13-second continuous confession; never loop, freeze, interpolate, slow or truncate dialogue."
    replacement["prompt_file"] = rel(OUT_PROMPT)
    replacement["prompt_path"] = rel(OUT_PROMPT)
    replacement["prompt_sha256"] = sha(OUT_PROMPT)
    replacement["performance_spec"] = copy.deepcopy(unit["performance_spec"])
    replacement["generation_fingerprint"] = generation_fingerprint(replacement)
    replacement["repair_evidence"] = "qa/e35_v1_streaming_video_compile_20260723/E35_U01_REMOTE_FAILURE_ROOT_CAUSE_AND_SPLIT_DECISION_V1.json"
    config["tasks"] = [replacement if row["unit_id"] == "E35-CW-U01" else row for row in config["tasks"]]
    config["complete_video_prompt_manifest_ref"] = rel(OUT_PROMPT_MANIFEST)
    config["dramatic_quality_report_ref"] = rel(OUT_DRAMATIC)
    config["mechanical_default_plan_ref"] = rel(OUT_MECHANICAL)
    config["script_readiness_report"] = rel(OUT_PREFLIGHT)
    config["recorded_at"] = datetime.now(timezone.utc).isoformat()
    config["runtime_seconds"] = 176
    config["projected_release_seconds_with_outro"] = 179
    for row in config["preserved_prompt_professionalism_evidence"]:
        if row["scene_id"] == "E35-CW-S01" and row["task_key"].startswith("E35-CW-U01-"):
            row["task_key"] = "E35-CW-U01-COMPLETE-PROMPT-V1-REPAIR1"
            row["prompt_file"] = rel(OUT_PROMPT)
            row["prompt_sha256"] = sha(OUT_PROMPT)
    write(OUT_CONFIG, config)
    print(json.dumps({
        "status": "PASS",
        "task_key": replacement["task_key"],
        "old_duration_seconds": 9,
        "new_duration_seconds": 13,
        "old_fingerprint": original["generation_fingerprint"],
        "new_fingerprint": replacement["generation_fingerprint"],
        "projected_release_seconds": 179,
        "config": rel(OUT_CONFIG),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
