#!/usr/bin/env python3
"""Build exact-SHA full-cut visual QA input for E27 AgentCut V17."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
PROJECT = ROOT / "configs/e27_agentcut_project_v17_n01_baseline_repair_20260720.json"
VIDEO = ROOT / "exports/e27/agentcut_v17_n01_baseline_repair_20260720/E27_AGENTCUT_V17_N01_BASELINE_REPAIR_NOT_FINAL.mp4"
OUT = ROOT / "qa/e27_agentcut_v17_n01_baseline_repair_20260720"
RECEIPT = ROOT / "workflow/tasks/E27_AGENTCUT_V17_QA_PACKAGE_RECEIPT_20260720.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    project = json.loads(PROJECT.read_text(encoding="utf-8"))
    clips = project["timeline"]["videoTracks"][0]["clips"]
    shots = [
        {
            "shot_id": clip["metadata"]["shot_id"],
            "scene_id": clip["metadata"]["scene_id"],
            "start": clip["start"],
            "end": clip["start"] + clip["duration"],
            "source": clip["source"],
            "source_sha256": clip["metadata"]["source_sha256"],
            "dialogue_ids": clip["metadata"].get("dialogue_ids", []),
            "expected_text": clip["metadata"].get("expected_text", ""),
        }
        for clip in clips
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    timeline = OUT / "E27_V17_FINAL_TIMELINE_SHOTS.json"
    timeline.write_text(
        json.dumps({"schema": "qingshan.agentcut_shot_timeline.v1", "shots": shots}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    request = OUT / "E27_V17_FULL_CUT_AI_REVIEW_REQUEST.json"
    request.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "path": str(VIDEO),
                        "scope": "full_cut",
                        "kind": "video",
                        "importance": "critical",
                        "pass_score": 4.5,
                        "clip_id": "E27-AGENTCUT-V17-N01-BASELINE-REPAIR-FULL-CUT",
                        "metadata": {
                            "episode": "E27",
                            "candidate_sha256": sha256(VIDEO),
                            "agentcut_project": str(PROJECT),
                            "agentcut_project_sha256": sha256(PROJECT),
                            "timeline": str(timeline),
                            "timeline_sha256": sha256(timeline),
                            "supervisor_instruction": "CL2X-467",
                            "review_focus": [
                                "ordinary human viewing experience across the exact full cut",
                                "scene authority and story action clarity across all 24 ordered shots",
                                "N01 uses the cadence-PASS V1 baseline and does not show periodic duplicate motion",
                                "N03 and N04 action inserts are readable in context",
                                "no readable or pseudo-readable text on books, papers, tags, seals or props",
                                "character identity, location, time-of-day and event continuity",
                                "native-speed action with no black frames, frozen filler or duplicated cadence",
                                "dialogue intelligibility only where expected_text is non-empty",
                                "no external background music",
                            ],
                        },
                        "required_capabilities": ["media_probe", "video_analysis", "audio_analysis", "ocr"],
                        "run_regression_ci": True,
                        "use_existing_tools": True,
                    }
                ],
                "workers": 1,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    receipt = {
        "schema": "qingshan.full_cut_qa_package.v1",
        "episode": "E27",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY_EXACT_SHA_FULL_CUT_VISUAL_REVIEW",
        "video": str(VIDEO),
        "video_sha256": sha256(VIDEO),
        "project": str(PROJECT),
        "project_sha256": sha256(PROJECT),
        "timeline": str(timeline),
        "timeline_sha256": sha256(timeline),
        "review_request": str(request),
        "review_request_sha256": sha256(request),
        "shot_count": len(shots),
        "runtime_seconds": 173.0,
        "remote_credit": 0,
        "remote_credit_reason": "LOCAL_AI_REVIEW_RUNTIME",
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "request": str(request), "video_sha256": sha256(VIDEO)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
