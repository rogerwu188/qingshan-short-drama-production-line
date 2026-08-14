#!/usr/bin/env python3
"""Build the admitted-interior U04 R4 evidence-video manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e39_claude_writer_v3_2726b69b_20260805"
SOURCE = BASE / "independent_video_r3_silent_visual/E39_INDEPENDENT_FAILED_ONLY_R3_SILENT_VISUAL_MANIFEST_V2.json"
PROMPT = BASE / "independent_video_r4_u04/E39-U04-R4-INTERIOR-VIDEO.txt"
REF = ROOT / "working_assets/e39_keyframes_v5/u04_interior_override_r4_candidates/E39-U04-A1-STILL-R4-INTERIOR-FOUR-SILHOUETTES.png"
OUT = BASE / "independent_video_r4_u04/E39_U04_R4_INTERIOR_VIDEO_MANIFEST_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    task = next(row for row in source["tasks"] if row["task_key"] == "E39-U04-R3-SILENT")
    task["task_key"] = "E39-U04-R4-INTERIOR-EVIDENCE"
    task["prompt_file"] = str(PROMPT.relative_to(ROOT))
    task["prompt_sha256"] = sha(PROMPT)
    task["reference_images"] = [str(REF.relative_to(ROOT))]
    task["reference_sha256"] = [sha(REF)]
    task.pop("paid_submit_blocked_by", None)
    task["source_subtitle_policy"] = "FORBID_ALL_SOURCE_TEXT"
    task["repair_strategy"] = "ADMITTED_INTERIOR_KEYFRAME_SILENT_EVIDENCE_AGENTCUT_VOICEOVER"
    manifest = {
        "schema": "qingshan.e39_u04_r4_interior_video_manifest.v1",
        "episode": "E39",
        "status": "AUTHORIZED_READY_FOR_PAID_PREFLIGHT",
        "source_script_sha256": source["source_script_sha256"],
        "canonical_manifest_sha256": source["canonical_manifest_sha256"],
        "output_dir": "working_assets/e39_video_v1/u04_r4_interior",
        "qa_dir": "qa/e39_video_v1/u04_r4_interior",
        "machine_gate_reports": source["machine_gate_reports"] + ["qa/e39_keyframes_v5/E39_U04_R4_INTERIOR_FOUR_SILHOUETTES_KEYFRAME_QA_V1.json"],
        "credit_authorization": {"effective_cap": 16000, "current_net": 13730, "worst_case": 576},
        "tasks": [task]
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(OUT.relative_to(ROOT)), "sha256": sha(OUT)}))


if __name__ == "__main__":
    main()
