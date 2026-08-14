#!/usr/bin/env python3
"""Build the E28 Writer Agent v0.5 release candidate with branded outro."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "configs/e28_agentcut_v2_writer_agent_v050_textclean_20260721.json"
CONTENT = ROOT / "exports/e28/agentcut_v2_writer_agent_v050_textclean_20260721/E28_AGENTCUT_V2_WRITER_AGENT_V050_TEXTCLEAN_NOT_FINAL.mp4"
REVIEW = ROOT / "qa/e28_writer_agent_v050_agentcut_v2_textclean_20260721/E28_AGENTCUT_V2_FULLCUT_AI_REVIEW_RESULT_0P9P1.json"
PROJECT = ROOT / "configs/e28_agentcut_v3_writer_agent_v050_release_candidate_20260721.json"
OUTPUT = ROOT / "exports/e28/agentcut_v3_writer_agent_v050_release_candidate_20260721/E28_AGENTCUT_V3_WRITER_AGENT_V050_RELEASE_CANDIDATE.mp4"
RECEIPT = ROOT / "workflow/tasks/E28_AGENTCUT_V3_WRITER_AGENT_V050_RELEASE_BUILD_RECEIPT_20260721.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    review = json.loads(REVIEW.read_text(encoding="utf-8"))
    item = review["items"][0]
    if review.get("status") != "PASS" or item.get("required_capability_failures"):
        raise SystemExit("E28 V2 content review has not passed")
    if item.get("media_sha256") != sha256(CONTENT):
        raise SystemExit("E28 V2 review is not bound to the content SHA")
    if float(item["scoring"]["score"]) != 5.0 or not item["scoring"]["hard_gate_passed"]:
        raise SystemExit("E28 V2 review score or hard gate failed")

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
            "status": "AGENTCUT_V3_RELEASE_CANDIDATE_FINAL_PACKAGE_QA_PENDING",
            "content_project": str(BASE),
            "content_project_sha256": sha256(BASE),
            "content_candidate": str(CONTENT),
            "content_candidate_sha256": sha256(CONTENT),
            "content_review": str(REVIEW),
            "content_review_sha256": sha256(REVIEW),
            "content_runtime_seconds": 162.0,
            "release_runtime_seconds": 165.0,
            "branded_outro_seconds": 3.0,
        }
    )
    project["qingshanAudit"]["pipelineStage"] = "WRITER_AGENT_V050_RELEASE_CANDIDATE"
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "schema": "qingshan.e28.agentcut-release-candidate-build.v1",
        "episode": "E28",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY_VALIDATE_RENDER_FINAL_PACKAGE_QA",
        "agentcut_runtime": "0.9.8",
        "project": str(PROJECT),
        "project_sha256": sha256(PROJECT),
        "output": str(OUTPUT),
        "content_seconds": 162.0,
        "branded_outro_seconds": 3.0,
        "expected_total_seconds": 165.0,
        "logo_sha256": sha256(logo),
        "chime_sha256": sha256(chime),
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "project": str(PROJECT), "output": str(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
