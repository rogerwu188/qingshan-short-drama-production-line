#!/usr/bin/env python3
"""Build an E28 V2 project with one reversible generated-text cleanup."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/e28_agentcut_v1_writer_agent_v050_entity_sequence_20260721.json"
PROJECT = ROOT / "configs/e28_agentcut_v2_writer_agent_v050_textclean_20260721.json"
OUTPUT = ROOT / "exports/e28/agentcut_v2_writer_agent_v050_textclean_20260721/E28_AGENTCUT_V2_WRITER_AGENT_V050_TEXTCLEAN_NOT_FINAL.mp4"
RECEIPT = ROOT / "workflow/tasks/E28_AGENTCUT_V2_WRITER_AGENT_V050_TEXTCLEAN_BUILD_RECEIPT_20260721.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    project = json.loads(SOURCE.read_text(encoding="utf-8"))
    target = next(
        clip
        for track in project["timeline"]["videoTracks"]
        for clip in track["clips"]
        if clip["metadata"]["unit_id"] == "E28-S02::U02"
    )
    target["cleanupRegions"] = [
        {"x": 488, "y": 400, "width": 108, "height": 250, "start": 3.0, "duration": 0.9, "mode": "delogo"},
        {"x": 405, "y": 450, "width": 115, "height": 265, "start": 3.8, "duration": 3.0, "mode": "delogo"},
    ]
    target["metadata"]["cut_reason"] = "LOCAL_REVERSIBLE_GENERATED_TEXT_CLEANUP"
    target["metadata"]["cleanup_reason"] = "Remove readable generated book-label text at full-cut 73.5-75.5s."
    project["output"]["path"] = str(OUTPUT)
    project["metadata"]["status"] = "V2_WRITER_AGENT_V050_TEXTCLEAN_NOT_FINAL"
    project["metadata"]["source_v1_project"] = str(SOURCE)
    project["metadata"]["source_v1_project_sha256"] = sha256(SOURCE)
    project["metadata"]["targeted_cleanup_units"] = ["E28-S02::U02"]
    project["qingshanAudit"]["pipelineStage"] = "WRITER_AGENT_V050_ENTITY_REFERENCE_FULLCUT_TEXTCLEAN"
    project["qingshanAudit"]["rollback"] = "Remove E28-S02::U02 cleanupRegions and return to the preserved V1 full cut."

    PROJECT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROJECT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    RECEIPT.write_text(
        json.dumps(
            {
                "schema": "qingshan.e28.agentcut-v050-textclean-build-receipt.v1",
                "episode": "E28",
                "status": "BUILT_NOT_RENDERED",
                "source_project": str(SOURCE),
                "source_project_sha256": sha256(SOURCE),
                "project": str(PROJECT),
                "output": str(OUTPUT),
                "targeted_unit": "E28-S02::U02",
                "targeted_fullcut_range_seconds": [73.0, 76.8],
                "raw_ocr_fail_preserved": True,
                "rollback": "Remove cleanupRegions and use the preserved V1 candidate.",
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"ok": True, "project": str(PROJECT), "output": str(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
