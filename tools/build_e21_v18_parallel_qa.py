#!/usr/bin/env python3
"""Build the concurrent whole-film QA batch for E21 AgentCut V18."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "workflow/tasks/E21_V12_PARALLEL_QA_CONFIG_20260719.json"
OUT = ROOT / "configs/E21_agentcut_v18_standard_storyboard_parallel_qa_20260719.json"


def main() -> int:
    config = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    replacements = {
        "V12": "V18",
        "v12_dia007_audio_tail_repair": "v18_standard_storyboard_coverage",
        "e21_agentcut_project_v12_dia007_audio_tail_repair": "e21_agentcut_project_v18_standard_storyboard_coverage",
        "E21_AGENTCUT_V12_DIA007_AUDIO_TAIL_REPAIR": "E21_AGENTCUT_V18_STANDARD_STORYBOARD_COVERAGE",
    }
    raw = json.dumps(config, ensure_ascii=False)
    for old, new in replacements.items():
        raw = raw.replace(old, new)
    config = json.loads(raw)
    video = "exports/e21/agentcut_v18_standard_storyboard_coverage_20260719/E21_AGENTCUT_V18_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4"
    for task in config["tasks"]:
        task["video"] = video
    config["base_batch_note"] = (
        "V18 whole-film QA after six reviewed standard-storyboard sources were admitted. "
        "Run all independent gates concurrently and preserve individual passing evidence."
    )
    OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "config": str(OUT), "task_count": len(config["tasks"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
