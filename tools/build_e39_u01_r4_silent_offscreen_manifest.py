#!/usr/bin/env python3
"""Build the changed-input U01 silent offscreen repair manifest."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e39_claude_writer_v3_2726b69b_20260805"
SOURCE = BASE / "independent_video_r3_silent_visual/E39_INDEPENDENT_FAILED_ONLY_R3_SILENT_VISUAL_MANIFEST_V2.json"
PROMPT = BASE / "independent_video_r4_u01/E39-U01-R4-SILENT-OFFSCREEN.txt"
OUT = BASE / "independent_video_r4_u01/E39_U01_R4_SILENT_OFFSCREEN_MANIFEST_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    task = next(row for row in source["tasks"] if row["task_key"] == "E39-U01-R3-SILENT")
    task["task_key"] = "E39-U01-R4-SILENT-OFFSCREEN"
    task["prompt_file"] = str(PROMPT.relative_to(ROOT))
    task["prompt_sha256"] = sha(PROMPT)
    task["repair_strategy"] = "OFFSCREEN_EXACT_AGENTCUT_LINES_NO_VISIBLE_SPEAKING_FACE"
    manifest = {
        "schema": "qingshan.e39_u01_r4_silent_offscreen_manifest.v1",
        "episode": "E39",
        "status": "PREPARED_WAIT_U04_QA_AND_CREDIT_RESERVATION",
        "source_script_sha256": source["source_script_sha256"],
        "canonical_manifest_sha256": source["canonical_manifest_sha256"],
        "output_dir": "working_assets/e39_video_v1/u01_r4_silent_offscreen",
        "qa_dir": "qa/e39_video_v1/u01_r4_silent_offscreen",
        "machine_gate_reports": source["machine_gate_reports"],
        "credit_authorization": {"effective_cap": 16000, "projected_net_after_u04": 14306, "worst_case": 720, "projected_headroom_after": 974},
        "tasks": [task]
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(OUT.relative_to(ROOT)), "sha256": sha(OUT)}))


if __name__ == "__main__":
    main()
