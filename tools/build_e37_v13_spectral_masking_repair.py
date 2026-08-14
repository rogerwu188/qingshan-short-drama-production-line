#!/usr/bin/env python3
"""Repair only E37 V12 BGM levels and the reveal-to-action cue handoff."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/e37_agentcut_v12_selective_bgm_repair_20260803.json"
OUT = ROOT / "configs/e37_agentcut_v13_spectral_masking_repair_20260804.json"
OUTPUT = ROOT / "exports/e37/agentcut_v13_spectral_masking_repair_20260804/E37_AGENTCUT_V13_SPECTRAL_MASKING_REPAIR_NOT_FINAL.mp4"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


project = json.loads(SOURCE.read_text(encoding="utf-8"))
project["output"]["path"] = str(OUTPUT.resolve())
tracks = project["timeline"]["audioTracks"]
bgm = next(track for track in tracks if track.get("id") == "Audio.BGM")
repairs = {
    "E37-BGM-OPENING": {"volume": 0.10},
    "E37-BGM-INVESTIGATION": {"volume": 0.06},
    "E37-BGM-ACTION": {"volume": 0.23, "transition_in": 1.0},
    "E37-BGM-HOOK": {"volume": 0.09},
}
for clip in bgm["clips"]:
    repair = repairs.get(clip.get("id"))
    if not repair:
        continue
    clip["volume"] = repair["volume"]
    if "transition_in" in repair:
        clip["transitionIn"] = {"type": "fade", "duration": repair["transition_in"]}

metadata = project.setdefault("metadata", {})
metadata["v13_spectral_masking_repair"] = {
    "source_project": str(SOURCE.resolve()),
    "source_project_sha256": sha256(SOURCE),
    "failed_gate": "E37_V12_BGM_AUTHENTICITY_CUE_AND_SPECTRAL_GATE_V2",
    "failed_gate_path": str((ROOT / "qa/e37_agentcut_20260803/v12_selective_bgm_repair/E37_V12_BGM_AUTHENTICITY_CUE_AND_SPECTRAL_GATE_V2.json").resolve()),
    "video_source_changed": False,
    "native_audio_source_changed": False,
    "subtitle_source_changed": False,
    "bgm_source_changed": False,
    "zero_credit_mix_only": True,
    "repairs": repairs,
}

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"project": str(OUT.relative_to(ROOT)), "sha256": sha256(OUT)}, ensure_ascii=False))
