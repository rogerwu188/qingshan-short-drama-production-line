#!/usr/bin/env python3
"""Build the E27 v16 release candidate with the standard branded outro."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
BASE = ROOT / "configs/e27_agentcut_project_v15_writer_agent_v040_native_text_r2_20260720.json"
ADJUDICATION = ROOT / "qa/e27_agentcut_v15_writer_agent_v040_native_text_r2_20260720/E27_AGENTCUT_V15_EVIDENCE_BOUND_QA_ADJUDICATION.json"
PROJECT = ROOT / "configs/e27_agentcut_project_v16_writer_agent_v040_release_candidate_20260720.json"
OUTPUT = ROOT / "exports/e27/agentcut_v16_writer_agent_v040_release_candidate_20260720/E27_AGENTCUT_V16_WRITER_AGENT_V040_RELEASE_CANDIDATE.mp4"
RECEIPT = ROOT / "workflow/tasks/E27_AGENTCUT_V16_WRITER_AGENT_V040_BUILD_RECEIPT_20260720.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    adjudication = json.loads(ADJUDICATION.read_text(encoding="utf-8"))
    if adjudication.get("status") != "CONDITIONAL_MACHINE_ADMISSION" or adjudication.get("blocking") is not False:
        raise SystemExit("v15 content candidate is not admitted")
    project = json.loads(BASE.read_text(encoding="utf-8"))
    logo = ROOT / "libraries/brand/nalu_motion_cat_logo_v1.png"
    chime = ROOT / "libraries/brand/nalu_motion_outro_chime_v1.wav"
    for asset in (logo, chime):
        if not asset.is_file():
            raise SystemExit(f"missing branded outro asset: {asset}")
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    project["requireBrandedOutro"] = True
    project["outro"] = {
        "enabled": True,
        "brand": "nalu_motion",
        "template": "nalu-motion-v1",
        "templateVersion": "1.0",
        "assetPath": str(logo),
        "duration": 3,
        "fit": "contain",
        "audioPolicy": "asset",
        "transitionIn": 0.25,
        "transitionOut": 0.25,
        "titleText": "青山",
        "nextText": "敬请期待",
        "brandText": "NALU MOTION",
        "dialogueDuckDb": -12,
        "bgmDuckDb": -9,
        "safeArea": {"left": 72, "right": 72, "top": 128, "bottom": 128},
        "logo": {"x": 235, "y": 590, "width": 250, "height": 141},
        "includeInTotalDuration": True,
        "audioPath": str(chime),
    }
    project["output"]["path"] = str(OUTPUT)
    project["metadata"].update(
        {
            "status": "AGENTCUT_V16_RELEASE_CANDIDATE_FINAL_PACKAGE_QA_PENDING",
            "content_project": str(BASE),
            "content_project_sha256": sha256(BASE),
            "content_adjudication": str(ADJUDICATION),
            "content_adjudication_sha256": sha256(ADJUDICATION),
            "release_runtime_seconds": 173.0,
            "branded_outro_seconds": 3.0,
        }
    )
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema": "qingshan.agentcut_release_candidate_build.v1",
        "episode": "E27",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY_VALIDATE_COMPILE_RENDER_FINAL_PACKAGE_QA",
        "agentcut_runtime_required": "0.9.7",
        "project": str(PROJECT),
        "project_sha256": sha256(PROJECT),
        "output": str(OUTPUT),
        "content_seconds": 170.0,
        "branded_outro_seconds": 3.0,
        "expected_total_seconds": 173.0,
        "logo_sha256": sha256(logo),
        "chime_sha256": sha256(chime),
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "project": str(PROJECT), "project_sha256": sha256(PROJECT), "output": str(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
