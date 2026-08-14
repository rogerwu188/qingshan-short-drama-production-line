#!/usr/bin/env python3
"""Build the E29 V1 whole-cut QA batch without claiming absent dialogue audio."""

from __future__ import annotations

import json
from pathlib import Path

from build_standard_storyboard_agentcut_qa_batch import build


ROOT = Path(__file__).resolve().parents[1]
VIDEO = ROOT / "exports/e29/agentcut_v1_subtitled_outro_20260722/E29_AGENTCUT_V1_SUBTITLED_OUTRO_NOT_FINAL.mp4"
PROJECT = ROOT / "configs/e29_agentcut_v1_subtitled_outro_20260722.json"
PLAN = ROOT / "workflow/claude_writer_agent/production/e29_claude_writer_v1_20260722/E29_VIDEO_UNIT_PLAN_V2_CL2X581.json"
SCENE_STATE = ROOT / "workflow/claude_writer_agent/production/e29_claude_writer_v1_20260722/E29_SCENE_AUTHORITY_STATE_V1.json"
QA = ROOT / "qa/e29_agentcut_v1_subtitled_outro_20260722"
CONFIG = ROOT / "configs/e29_agentcut_v1_fullcut_qa_batch_20260722.json"


def main() -> int:
    result = build("E29", VIDEO, PROJECT, PLAN, SCENE_STATE, QA, CONFIG)
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    config["tasks"] = [task for task in config["tasks"] if task["task_key"] != "E29-ASR-SENTENCE"]
    config["concurrency"] = len(config["tasks"])
    config["base_batch_note"] = (
        "Run action, cadence, full-duration OCR, and whole-cut experience review concurrently. "
        "Dialogue is carried by the locked 15/15 burned-subtitle contract; do not fabricate an ASR pass."
    )
    request = QA / "E29_FULL_CUT_AI_REVIEW_REQUEST.json"
    payload = json.loads(request.read_text(encoding="utf-8"))
    item = payload["items"][0]
    item["required_capabilities"] = ["media_probe", "video_analysis", "audio_analysis"]
    item["metadata"]["subtitle_delivery"] = {
        "mode": "BURNED_IN_LOCKED_SCRIPT_TEXT",
        "coverage": "15/15",
        "project": str(PROJECT),
        "dialogue_audio_claimed": False,
    }
    item["metadata"]["review_focus"] = [
        "ordinary human viewing experience",
        "story clarity through visuals and burned subtitles",
        "subtitle readability and safe-area placement",
        "character identity continuity",
        "motivated native-speed cuts with no static padding",
        "NALU MOTION outro after all narrative subtitles",
    ]
    request.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result.update({"tasks": len(config["tasks"]), "request": str(request)})
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
