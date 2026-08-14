#!/usr/bin/env python3
"""Add provenance-bound, selective narrative BGM cues to E37 V11."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "configs/e37_agentcut_v11_line14_caption_window_repair_20260803.json"
OUT = ROOT / "configs/e37_agentcut_v12_selective_bgm_repair_20260803.json"
OUTPUT = ROOT / "exports/e37/agentcut_v12_selective_bgm_repair_20260803/E37_AGENTCUT_V12_SELECTIVE_BGM_REPAIR_NOT_FINAL.mp4"
BGM = ROOT / "working_assets/e37_bgm_20260803/a93ff704-f767-44ef-b73d-c89ee9c10e08/bgm_candidate_1.mp3"
BGM_SHA = "594b38924d087e7dee7081ec54196989eb444aa7459055e8e2b811bffe10a27f"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if sha256(BGM) != BGM_SHA:
    raise SystemExit("E37 BGM source SHA mismatch")

project = json.loads(SOURCE.read_text(encoding="utf-8"))
project["output"]["path"] = str(OUTPUT.resolve())
metadata = project.setdefault("metadata", {})
metadata["bgm_contract"] = {
    "source_type": "GENERATED_EPISODE_BGM",
    "license_status": "SELF_GENERATED_ACCOUNT_OWNED",
    "dialogue_duck_db": -8.0,
    "generation_task_id": "a93ff704-f767-44ef-b73d-c89ee9c10e08",
    "generation_receipt": str((ROOT / "workflow/tasks/E37_AGENTCUT_BGM_GENERATION_20260803.json").resolve()),
    "source_sha256": BGM_SHA,
    "credit_evidence": str((ROOT / "workflow/credit_reports/E37_AGENTCUT_BGM_CREDIT_AUDIT_20260803.json").resolve()),
    "external_commercial_rights_metadata_required": False,
    "authorization_ref": "ROGER-STANDING-GENERATED-BGM-PROVENANCE",
}
metadata["bgm_cue_policy"] = {
    "mode": "SELECTIVE_NARRATIVE_CUES",
    "ambience_only_required": True,
    "spectral_masking_gate_required": True,
    "maximum_coverage_ratio": 0.85,
    "minimum_ambience_only_seconds": 8.0,
    "actual_cue_seconds": 93.0,
    "actual_coverage_ratio": round(93.0 / 176.084, 6),
    "actual_ambience_only_seconds": 83.084,
    "dialogue_volume_max": 0.16,
    "non_dialogue_volume_max": 0.32,
    "policy": "No wall-to-wall score. Preserve native rain, fire, movement and impact sound between motivated cues.",
}

cues = [
    ("OPENING", 0.0, 0.0, 8.0, 0.13, "OPENING_MYSTERY", True),
    ("INVESTIGATION", 18.0, 18.0, 9.0, 0.12, "INVESTIGATION_TRANSITION", True),
    ("REVEAL", 55.0, 55.0, 7.0, 0.13, "INVESTIGATION_TRANSITION", True),
    ("ACTION", 62.0, 62.0, 31.0, 0.28, "ACTION_ESCALATION", False),
    ("AFTERMATH", 100.0, 100.0, 8.0, 0.12, "INVESTIGATION_TRANSITION", True),
    ("HOOK", 146.0, 146.0, 30.0, 0.12, "ENDING_HOOK", True),
]
clips = []
for cue_id, start, source_in, duration, volume, role, dialogue_present in cues:
    clips.append({
        "id": f"E37-BGM-{cue_id}",
        "source": str(BGM.resolve()),
        "start": start,
        "in": source_in,
        "duration": duration,
        "volume": volume,
        "transitionIn": {"type": "fade", "duration": 0.5},
        "transitionOut": {"type": "fade", "duration": 0.75},
        "metadata": {
            "cue_role": role,
            "dialogue_present": dialogue_present,
            "dialogue_duck_db": -8.0 if dialogue_present else 0.0,
            "source_sha256": BGM_SHA,
        },
    })

audio_tracks = project["timeline"]["audioTracks"]
audio_tracks[:] = [track for track in audio_tracks if track.get("id") != "Audio.BGM"]
audio_tracks.append({"id": "Audio.BGM", "clips": clips})
metadata["v12_selective_bgm_repair"] = {
    "source_project": str(SOURCE.resolve()),
    "source_project_sha256": sha256(SOURCE),
    "video_source_changed": False,
    "native_audio_source_changed": False,
    "subtitle_source_changed": False,
    "credits": {"pay": 8, "refund": 0, "net": 8},
}

OUT.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"project": str(OUT.relative_to(ROOT)), "sha256": sha256(OUT), "cue_count": len(clips)}, ensure_ascii=False))
