#!/usr/bin/env python3
"""Extend E37 line 14's caption window to its complete native utterance."""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/e37_agentcut_v10_line19_two_fixed_compositions_20260803.json"
OUT = ROOT / "configs/e37_agentcut_v11_line14_caption_window_repair_20260803.json"
OUTPUT = ROOT / "exports/e37/agentcut_v11_line14_caption_window_repair_20260803/E37_AGENTCUT_V11_LINE14_CAPTION_WINDOW_REPAIR_NOT_FINAL.mp4"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


project = json.loads(SOURCE.read_text(encoding="utf-8"))
matched = []
for subtitle in project["timeline"]["subtitleTracks"][0]["clips"]:
    if subtitle.get("metadata", {}).get("line_id") == 14:
        matched.append({"old_start": subtitle["start"], "old_duration": subtitle["duration"]})
        subtitle["start"] = 59.85
        subtitle["duration"] = 2.35
        subtitle.setdefault("metadata", {})["timing_repair"] = "COMPLETE_NATIVE_UTTERANCE_TWO_CLAUSES"
if len(matched) != 1:
    raise SystemExit(f"expected one line14 subtitle, found {len(matched)}")
project["output"]["path"] = str(OUTPUT.resolve())
project.setdefault("metadata", {})["v11_line14_caption_window_repair"] = {
    "source_project": str(SOURCE.resolve()),
    "source_project_sha256": sha256(SOURCE),
    "old": matched[0],
    "new": {"start": 59.85, "duration": 2.35},
    "audio_source_changed": False,
    "video_source_changed": False,
    "credits": {"pay": 0, "refund": 0, "net": 0}
}
OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"project": str(OUT.relative_to(ROOT)), "sha256": sha256(OUT)}, ensure_ascii=False))
