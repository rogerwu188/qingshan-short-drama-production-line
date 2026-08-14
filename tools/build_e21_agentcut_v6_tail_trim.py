#!/usr/bin/env python3
"""Build E21 V6 by removing only the proven frozen tail after DIA-037."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/e21_agentcut_project_v5_boundary_repair_20260719.json"
OUTPUT = ROOT / "configs/e21_agentcut_project_v6_tail_trim_20260719.json"
RENDER = ROOT / "exports/e21/agentcut_v6_tail_trim_20260719/E21_AGENTCUT_V6_TAIL_TRIM_NOT_FINAL.mp4"
TARGET_DURATION = 3.333333
CAPTION_DURATION = 3.093333


def main() -> int:
    original = json.loads(SOURCE.read_text(encoding="utf-8"))
    project = copy.deepcopy(original)
    video = project["timeline"]["videoTracks"][0]["clips"]
    audio = project["timeline"]["audioTracks"][0]["clips"]
    captions = project["timeline"]["subtitleTracks"][0]["clips"]
    if video[-1]["metadata"].get("dialogue_id") != "DIA-037":
        raise SystemExit("last video clip is not DIA-037")
    if audio[-1].get("id") != "E21-DIA-037-AUDIO" or captions[-1].get("dialogue_id") != "DIA-037":
        raise SystemExit("DIA-037 audio/subtitle binding changed")
    if float(video[-1]["duration"]) < TARGET_DURATION or float(audio[-1]["duration"]) < TARGET_DURATION:
        raise SystemExit("source is already shorter than the verified trim point")

    video[-1]["duration"] = TARGET_DURATION
    video[-1].setdefault("metadata", {})["tail_trim_reason"] = "Remove frozen run beginning at final timeline 175.875s; dialogue ends at source 2.34s."
    audio[-1]["duration"] = TARGET_DURATION
    captions[-1]["duration"] = CAPTION_DURATION
    project["output"]["path"] = str(RENDER)
    project.setdefault("metadata", {})["version"] = "E21_AGENTCUT_V6_TAIL_TRIM"
    project["metadata"]["source_project"] = str(SOURCE)
    project["metadata"]["change_scope"] = "DIA-037 frozen tail only"

    for index in range(len(video) - 1):
        if video[index] != original["timeline"]["videoTracks"][0]["clips"][index]:
            raise SystemExit(f"unexpected video mutation at index {index}")
    for index in range(len(audio) - 1):
        if audio[index] != original["timeline"]["audioTracks"][0]["clips"][index]:
            raise SystemExit(f"unexpected audio mutation at index {index}")
    for index in range(len(captions) - 1):
        if captions[index] != original["timeline"]["subtitleTracks"][0]["clips"][index]:
            raise SystemExit(f"unexpected subtitle mutation at index {index}")

    OUTPUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "project": str(OUTPUT), "render": str(RENDER), "tail_trim_seconds": round(4.041667 - TARGET_DURATION, 6)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
