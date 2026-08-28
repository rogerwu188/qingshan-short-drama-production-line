#!/usr/bin/env python3
"""Register E44 v5 final content lock after narrow post-generation QA."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MASTER = ROOT / "working_assets/e44_v5_final/E44_V5_SD2_STANDARD_9X16_MASTER_CANDIDATE_A2_REPAIRED_V1.mp4"
TECH = ROOT / "qa/e44_v5_final/E44_V5_MASTER_CANDIDATE_TECHNICAL_QA_V1.json"
AUDIT = ROOT / "qa/e44_v5_final/E44_V5_TECHNICAL_AND_BASIC_PLOT_QA_V1.json"
MEDIA_MAP = ROOT / "qa/e44_v5_final/E44_V5_ACCEPTED_MEDIA_MAP_25_OF_25_A2_REPAIRED_V1.json"
MAP_LOCK = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828/E44_V5_COMPLETE_MAP_MODE_LOCK_V1.json"
OUT = ROOT / "qa/e44_v5_final/E44_V5_FINAL_CONTENT_LOCK_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    tech, audit, media_map, map_lock = load(TECH), load(AUDIT), load(MEDIA_MAP), load(MAP_LOCK)
    if tech.get("status") != "PASS_TECHNICAL_MASTER" or audit.get("status") != "PASS" or not str(media_map.get("status", "")).startswith("PASS_ACCEPTED_MEDIA") or not str(map_lock.get("status", "")).startswith("PASS"):
        raise RuntimeError("E44 content-lock evidence is not PASS")
    visual = subprocess.run([
        "ffmpeg", "-hide_banner", "-i", str(MASTER), "-vf", "blackdetect=d=1.5:pix_th=0.10,freezedetect=n=-45dB:d=2", "-an", "-f", "null", "-",
    ], capture_output=True, text=True).stderr
    audio = subprocess.run([
        "ffmpeg", "-hide_banner", "-i", str(MASTER), "-af", "silencedetect=noise=-50dB:d=2,volumedetect", "-vn", "-f", "null", "-",
    ], capture_output=True, text=True).stderr
    visual_events = [line.strip() for line in visual.splitlines() if "black_start" in line or "freeze_start" in line]
    silence_events = [line.strip() for line in audio.splitlines() if "silence_start" in line]
    failures = []
    if visual_events:
        failures.append("BLACK_OR_FREEZE_EVENT_OVER_THRESHOLD")
    if silence_events:
        failures.append("SILENCE_EVENT_OVER_THRESHOLD")
    payload = {
        "schema": "qingshan.e44.v5.final_content_lock.v1",
        "episode": "E44",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_FINAL_CONTENT_LOCK_25_OF_25_180_SECONDS_COMPLETE_MAP" if not failures else "FAIL",
        "master_candidate": rel(MASTER),
        "master_candidate_sha256": sha(MASTER),
        "unit_count": 25,
        "planned_duration_seconds": 180.0,
        "decoded_duration_seconds": tech["decoded_duration_seconds"],
        "complete_map_mode": True,
        "model": "seedance-2.0-pro",
        "native_resolution": "720p",
        "delivery_resolution": "2K_1440X2560_HIGH_QUALITY_UPSCALE",
        "aspect_ratio": "9:16",
        "native_audio_preserved": True,
        "repaired_units": media_map["replaced_a1_units"],
        "technical_and_basic_plot_qa": {"ref": rel(AUDIT), "sha256": sha(AUDIT)},
        "technical_master_qa": {"ref": rel(TECH), "sha256": sha(TECH)},
        "accepted_media_map": {"ref": rel(MEDIA_MAP), "sha256": sha(MEDIA_MAP)},
        "diagnostics": {"black_or_freeze_events": visual_events, "silence_events": silence_events},
        "failures": failures,
        "release_packaging_allowed": not failures,
        "publication_allowed_after_release_package_qa": not failures,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "content_lock": rel(OUT)}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
