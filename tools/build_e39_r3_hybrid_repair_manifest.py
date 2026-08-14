#!/usr/bin/env python3
"""Build the E39 mixed native-dialogue and silent-cutaway repair wave."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e39_claude_writer_v3_2726b69b_20260805"
R2 = BASE / "independent_video_r2_audio_driven/E39_INDEPENDENT_FAILED_ONLY_R2_MANIFEST_V1.json"
R3 = BASE / "independent_video_r3_silent_visual/E39_INDEPENDENT_FAILED_ONLY_R3_SILENT_VISUAL_MANIFEST_V2.json"
OUT = BASE / "independent_video_r3_hybrid/E39_INDEPENDENT_R3_HYBRID_REPAIR_WAVE_MANIFEST_V1.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    r2 = load(R2)
    r3 = load(R3)
    selected: list[dict] = []
    native = {"E39-U01-R2", "E39-U05-R2", "E39-U13-R2", "E39-U14-R2"}
    silent = {"E39-U10-R3-SILENT", "E39-U11-R3-SILENT", "E39-U15-R3-SILENT"}
    for task in r2["tasks"]:
        if task["task_key"] in native:
            item = copy.deepcopy(task)
            unit = task["task_key"].split("-")[1]
            item["task_key"] = f"E39-{unit}-R3-NATIVE-HYBRID"
            item["repair_strategy"] = "VISIBLE_DIRECT_DIALOGUE_NATIVE_EXACT_LINE_AUDIO"
            selected.append(item)
    for task in r3["tasks"]:
        if task["task_key"] in silent:
            item = copy.deepcopy(task)
            unit = task["task_key"].split("-")[1]
            item["task_key"] = f"E39-{unit}-R3-SILENT-CUTAWAY"
            item["repair_strategy"] = "NO_VISIBLE_SPEAKER_SILENT_VISUAL_AGENTCUT_AUDIO"
            selected.append(item)
    assert len(selected) == 7
    manifest = {
        "schema": "qingshan.e39_independent_r3_hybrid_repair_wave.v1",
        "episode": "E39",
        "status": "AUTHORIZED_READY_FOR_PAID_PREFLIGHT",
        "source_script_sha256": r2["source_script_sha256"],
        "canonical_manifest_sha256": r2["canonical_manifest_sha256"],
        "output_dir": "working_assets/e39_video_v1/independent_r3_hybrid",
        "qa_dir": "qa/e39_video_v1/independent_r3_hybrid",
        "retry_policy": "FAILED_ONLY_MATERIAL_PROMPT_CHANGE_REQUIRED",
        "dialogue_transport_policy": {
            "visible_direct_dialogue": "NATIVE_EXACT_LINE_AUDIO",
            "offscreen_voiceover_or_evidence_narration": "SILENT_VISUAL_AGENTCUT_AUDIO",
            "silent_visible_dialogue": "BLOCKED"
        },
        "credit_authorization": {
            "path": "workflow/approvals/ROGER_E39_REPAIR_CREDIT_BATCH_6000_20260806.json",
            "effective_total_net_cap": 16000,
            "current_effective_net": 9676,
            "wave_worst_case_credits": 4032,
            "headroom_after_reservation": 2292
        },
        "machine_gate_reports": sorted(set(r2["machine_gate_reports"] + r3["machine_gate_reports"])),
        "tasks": selected,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(OUT.relative_to(ROOT)), "sha256": hashlib.sha256(OUT.read_bytes()).hexdigest(), "tasks": len(selected)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
