#!/usr/bin/env python3
"""Build exact-SHA parallel QA inputs for E27 AgentCut v14."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
PROJECT = ROOT / "configs/e27_agentcut_project_v14_writer_agent_v040_20260720.json"
VIDEO = ROOT / "exports/e27/agentcut_v14_writer_agent_v040_20260720/E27_AGENTCUT_V14_WRITER_AGENT_V040_NOT_FINAL.mp4"
OUT = ROOT / "qa/e27_agentcut_v14_writer_agent_v040_20260720"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    project = json.loads(PROJECT.read_text(encoding="utf-8"))
    clips = project["timeline"]["videoTracks"][0]["clips"]
    shots = [{
        "shot_id": clip["metadata"]["shot_id"],
        "scene_id": clip["metadata"]["scene_id"],
        "start": clip["start"],
        "end": clip["start"] + clip["duration"],
        "source": clip["source"],
        "source_sha256": clip["metadata"]["source_sha256"],
        "dialogue_ids": clip["metadata"].get("dialogue_ids", []),
    } for clip in clips]
    OUT.mkdir(parents=True, exist_ok=True)
    timeline = OUT / "E27_FINAL_TIMELINE_SHOTS.json"
    timeline.write_text(json.dumps({
        "schema": "qingshan.agentcut_shot_timeline.v1",
        "source_track_id": project["timeline"]["videoTracks"][0]["id"],
        "shots": shots,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    request = OUT / "E27_FULL_CUT_AI_REVIEW_REQUEST.json"
    request.write_text(json.dumps({
        "items": [{
            "path": str(VIDEO),
            "scope": "full_cut",
            "kind": "video",
            "importance": "critical",
            "pass_score": 4.5,
            "clip_id": "E27-AGENTCUT-V14-WRITER-AGENT-V040-FULL-CUT",
            "metadata": {
                "episode": "E27",
                "candidate_sha256": sha256(VIDEO),
                "agentcut_project": str(PROJECT),
                "agentcut_project_sha256": sha256(PROJECT),
                "timeline": str(timeline),
                "timeline_sha256": sha256(timeline),
                "review_focus": [
                    "ordinary human viewing experience",
                    "story clarity and pacing across all 24 ordered shots",
                    "character identity and scene continuity",
                    "motivated cuts and native-speed action",
                    "dialogue intelligibility, sentence completeness and source-bound voices",
                    "no readable or pseudo-readable text, black frames, frozen filler or duplicated cadence",
                    "no external background music",
                ],
            },
            "required_capabilities": ["media_probe", "video_analysis", "audio_analysis", "ocr"],
            "run_regression_ci": True,
            "use_existing_tools": True,
        }],
        "workers": 1,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = ROOT / "workflow/tasks/E27_AGENTCUT_V14_WRITER_AGENT_V040_QA_PACKAGE_RECEIPT_20260720.json"
    receipt.write_text(json.dumps({
        "episode": "E27",
        "status": "READY_PARALLEL_QA",
        "video": str(VIDEO),
        "video_sha256": sha256(VIDEO),
        "project": str(PROJECT),
        "project_sha256": sha256(PROJECT),
        "timeline": str(timeline),
        "timeline_sha256": sha256(timeline),
        "review_request": str(request),
        "review_request_sha256": sha256(request),
        "shot_count": len(shots),
        "runtime_seconds": shots[-1]["end"],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "shots": len(shots), "video_sha256": sha256(VIDEO), "request": str(request)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
