#!/usr/bin/env python3
"""Build E22 V17 concurrent whole-film QA from the proven V16 gate set."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "workflow/tasks/E22_V16_PARALLEL_QA_CONFIG_20260719.json"
OUT = ROOT / "configs/E22_agentcut_v17_standard_storyboard_parallel_qa_20260719.json"


def main() -> int:
    raw = TEMPLATE.read_text(encoding="utf-8")
    replacements = {
        "V16": "V17",
        "v16_dia016_luma_repair": "v17_standard_storyboard_coverage",
        "e22_agentcut_project_v16_dia016_luma_repair": "e22_agentcut_project_v17_standard_storyboard_coverage",
        "E22_AGENTCUT_V16_DIA016_LUMA_REPAIR": "E22_AGENTCUT_V17_STANDARD_STORYBOARD_COVERAGE",
    }
    for old, new in replacements.items():
        raw = raw.replace(old, new)
    config = json.loads(raw)
    video = "exports/e22/agentcut_v17_standard_storyboard_coverage_20260719/E22_AGENTCUT_V17_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4"
    config["base_batch_note"] = "V17 whole-film QA after six reviewed standard-storyboard sources were admitted. Run all independent gates concurrently."
    for task in config["tasks"]:
        task["video"] = video
    OUT.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "config": str(OUT), "task_count": len(config["tasks"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
