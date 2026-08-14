#!/usr/bin/env python3
"""Build the E27 Writer Agent v0.5 release candidate with the standard outro."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
BASE = ROOT / "configs/e27_agentcut_v18_writer_agent_v050_entity_sequence_20260720.json"
AI_REVIEW = ROOT / "qa/e27_remaining_entity_reference_v050_20260720/E27_AGENTCUT_V18_FULLCUT_AI_REVIEW_RESULT_0P9P1_PRODUCTION.json"
PROJECT = ROOT / "configs/e27_agentcut_v19_writer_agent_v050_release_candidate_20260720.json"
OUTPUT = ROOT / "exports/e27/agentcut_v19_writer_agent_v050_release_candidate_20260720/E27_AGENTCUT_V19_WRITER_AGENT_V050_RELEASE_CANDIDATE.mp4"
RECEIPT = ROOT / "workflow/tasks/E27_AGENTCUT_V19_WRITER_AGENT_V050_BUILD_RECEIPT_20260720.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    review = json.loads(AI_REVIEW.read_text(encoding="utf-8"))
    if review.get("status") != "PASS" or review.get("content_status") != "PASS":
        raise SystemExit("V18 production AI review has not passed")
    item = review["items"][0]
    if item.get("required_capability_failures"):
        raise SystemExit("V18 production AI review still has capability failures")
    if item.get("media_sha256") != "f93dc1cec8ae4d815f495c6e8988a7d03db944707de9edb1b381e46095b9b1a1":
        raise SystemExit("V18 production AI review is not bound to the expected candidate SHA")

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
            "status": "V19_WRITER_AGENT_V050_RELEASE_CANDIDATE_FINAL_QA_PENDING",
            "platformUploadAllowed": False,
            "content_project": str(BASE),
            "content_project_sha256": sha256(BASE),
            "content_ai_review": str(AI_REVIEW),
            "content_ai_review_sha256": sha256(AI_REVIEW),
            "content_ai_review_score": item["scoring"]["score"],
            "content_seconds": 169.5,
            "release_runtime_seconds": 172.5,
            "branded_outro_seconds": 3.0,
        }
    )
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    receipt = {
        "schema": "qingshan.agentcut_release_candidate_build.v1",
        "episode": "E27",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY_VALIDATE_COMPILE_RENDER_FINAL_PACKAGE_QA",
        "source": str(BASE),
        "source_sha256": sha256(BASE),
        "source_ai_review": str(AI_REVIEW),
        "source_ai_review_sha256": sha256(AI_REVIEW),
        "project": str(PROJECT),
        "project_sha256": sha256(PROJECT),
        "output": str(OUTPUT),
        "content_seconds": 169.5,
        "branded_outro_seconds": 3.0,
        "expected_total_seconds": 172.5,
        "logo_sha256": sha256(logo),
        "chime_sha256": sha256(chime),
        "platform_upload_allowed": False,
    }
    RECEIPT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "project": str(PROJECT), "project_sha256": sha256(PROJECT), "output": str(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
