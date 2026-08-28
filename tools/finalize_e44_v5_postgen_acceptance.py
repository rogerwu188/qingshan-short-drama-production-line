#!/usr/bin/env python3
"""Finalize E44's narrow post-generation QA and accepted 25-unit media map."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e44_v5_20260828"
GROUPED = PROD / "E44_V5_GROUPED_SEEDANCE_MANIFEST_COMPILED_V1.json"
A1 = ROOT / "qa/e44_v5_video_units/E44_V5_VIDEO_HARVEST_LATEST.json"
A2 = ROOT / "qa/e44_v5_a2_burned_text_repairs/E44_V5_A2_BURNED_TEXT_HARVEST_LATEST.json"
A3 = ROOT / "qa/e44_v5_a3_vu010_burned_text/E44_V5_VU010_A3_HARVEST_LATEST.json"
VU010_REMEDIATION = ROOT / "qa/e44_v5_a3_vu010_burned_text/E44_V5_VU010_CAPTION_SAFE_MATTE_REMEDIATION_V1.json"
VU011_REMEDIATION = ROOT / "qa/e44_v5_final/E44_V5_VU011_FREEZE_SAFE_DRIFT_REMEDIATION_V1.json"
MANUAL = ROOT / "qa/e44_v5_final/E44_V5_REPAIRS_MANUAL_VISUAL_QA_V1.json"
OUT_DIR = ROOT / "qa/e44_v5_final"
AUDIT = OUT_DIR / "E44_V5_TECHNICAL_AND_BASIC_PLOT_QA_V1.json"
MEDIA_MAP = OUT_DIR / "E44_V5_ACCEPTED_MEDIA_MAP_25_OF_25_A2_REPAIRED_V1.json"
TARGETS = {"E44-VU-003", "E44-VU-010", "E44-VU-011", "E44-VU-022"}
A2_TARGETS = {"E44-VU-003", "E44-VU-022"}
A3_TARGET = "E44-VU-010"


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def probe(path: Path) -> dict:
    info = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height",
        "-of", "json", str(path),
    ], text=True))
    video = next(row for row in info["streams"] if row["codec_type"] == "video")
    audio = next((row for row in info["streams"] if row["codec_type"] == "audio"), None)
    return {
        "duration_seconds": round(float(info["format"]["duration"]), 6),
        "video_codec": video["codec_name"],
        "width": int(video["width"]),
        "height": int(video["height"]),
        "audio_codec": audio["codec_name"] if audio else None,
        "pass": video["codec_name"] == "h264" and video["width"] == 720 and video["height"] == 1280 and bool(audio),
    }


def main() -> int:
    grouped, a1, a2, a3, remediation, vu011_remediation, manual = load(GROUPED), load(A1), load(A2), load(A3), load(VU010_REMEDIATION), load(VU011_REMEDIATION), load(MANUAL)
    if not a1.get("all_completed") or not a2.get("all_completed") or not a3.get("all_completed"):
        raise RuntimeError("E44 A1/A2/A3 harvest is not all completed")
    if manual.get("status") != "PASS" or set(manual.get("reviewed_units") or []) != TARGETS:
        raise RuntimeError("E44 exact A2 manual visual QA is not PASS")
    if remediation.get("status") != "PASS_DETERMINISTIC_CAPTION_SAFE_MATTE":
        raise RuntimeError("E44 VU010 deterministic burned-text remediation is not PASS")
    if vu011_remediation.get("status") != "PASS_DETERMINISTIC_FREEZE_SAFE_DRIFT":
        raise RuntimeError("E44 VU011 deterministic freeze remediation is not PASS")
    remediated_media = ROOT / remediation["output_media_path"]
    vu011_media = ROOT / vu011_remediation["output_media_path"]
    if sha(remediated_media) != remediation["output_media_sha256"]:
        raise RuntimeError("E44 VU010 remediated media SHA mismatch")
    if sha(vu011_media) != vu011_remediation["output_media_sha256"]:
        raise RuntimeError("E44 VU011 remediated media SHA mismatch")
    a1_rows = {row["unit_id"]: row for row in a1["results"]}
    a2_rows = {row["unit_id"]: row for row in a2["results"]}
    a3_rows = {row["unit_id"]: row for row in a3["results"]}
    rows, failures = [], []
    for unit in grouped["units"]:
        uid = unit["unit_id"]
        source = a3_rows[uid] if uid == A3_TARGET else (a2_rows[uid] if uid in A2_TARGETS else a1_rows[uid])
        media = remediated_media if uid == A3_TARGET else (vu011_media if uid == "E44-VU-011" else ROOT / source["video_path"])
        technical = probe(media)
        if not technical["pass"]:
            failures.append(f"{uid}:TECHNICAL_STREAM_OR_GEOMETRY_FAILURE")
        rows.append({
            "unit_id": uid,
            "editorial_shot_ids": unit["editorial_shot_ids"],
            "planned_duration_seconds": float(unit["duration_seconds"]),
            "media_path": rel(media),
            "media_sha256": sha(media),
            "selected_attempt": "A3_PLUS_DETERMINISTIC_CANONICAL_CAPTION_SAFE_MATTE" if uid == A3_TARGET else ("A1_PLUS_DETERMINISTIC_FREEZE_SAFE_DRIFT" if uid == "E44-VU-011" else ("A2_BURNED_TEXT_REPAIR" if uid in A2_TARGETS else "A1")),
            "technical": technical,
            "post_generation_decision": "ACCEPT",
        })
    audit = {
        "schema": "qingshan.e44.v5.technical_and_basic_plot_qa.v1",
        "episode": "E44",
        "created_at": now(),
        "status": "PASS" if not failures else "FAIL",
        "scope": "TECHNICAL_AND_BASIC_PLOT_IDENTITY_ONLY",
        "review_method": "All 25 units sampled across five 4-frame-per-unit contact sheets; the three A2 repairs reviewed again individually across their timelines.",
        "observations": [
            "All retained A1 units preserve the episode's inn, wet street, clinic wall, medicine shop, clinic courtyard, ladder and stone-table basic progression.",
            "Named character identities and transaction/relationship roles remain stable across the 25 selected units.",
            "A1 VU003/VU010/VU022 were rejected solely for provider-burned readable subtitles; VU003/VU022 A2 pass directly. VU010 exhausted its three creative attempts and uses a deterministic opaque caption-safe matte during its exact canonical-dialogue window, with source audio unchanged and the formal canonical caption placed over that matte.",
            "VU011's basic-plot-valid door hold exceeded the technical freeze threshold; a subtle deterministic optical drift removes the freeze without changing action, chronology or native source audio.",
        ],
        "contact_sheets": [
            f"qa/e44_v5_video_units/postgen_contact_sheets/E44_V5_UNITS_{start:03d}_{start + 4:03d}.jpg"
            for start in (1, 6, 11, 16, 21)
        ],
        "a2_manual_visual_qa": {"ref": rel(MANUAL), "sha256": sha(MANUAL)},
        "vu010_deterministic_remediation": {"ref": rel(VU010_REMEDIATION), "sha256": sha(VU010_REMEDIATION)},
        "vu011_deterministic_remediation": {"ref": rel(VU011_REMEDIATION), "sha256": sha(VU011_REMEDIATION)},
        "excluded_remake_reasons": ["action_reasonableness", "microexpression_precision", "gesture_or_choreography_detail", "camera_performance_taste"],
        "failures": failures,
        "rows": rows,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    media_map = {
        "schema": "qingshan.e44.v5.accepted_media_map.v1",
        "episode": "E44",
        "created_at": now(),
        "status": "PASS_ACCEPTED_MEDIA_25_OF_25_A2_REPAIRED" if not failures else "FAIL",
        "selected_unit_count": len(rows),
        "planned_runtime_seconds": round(sum(row["planned_duration_seconds"] for row in rows), 6),
        "replaced_a1_units": sorted(TARGETS),
        "final_attempt_by_replaced_unit": {"E44-VU-003": "A2", "E44-VU-010": "A3_PLUS_DETERMINISTIC_CAPTION_SAFE_MATTE", "E44-VU-011": "A1_PLUS_DETERMINISTIC_FREEZE_SAFE_DRIFT", "E44-VU-022": "A2"},
        "post_generation_qa": {"ref": rel(AUDIT), "sha256": sha(AUDIT)},
        "rows": rows,
    }
    MEDIA_MAP.write_text(json.dumps(media_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": media_map["status"], "units": len(rows), "runtime_seconds": media_map["planned_runtime_seconds"], "media_map": rel(MEDIA_MAP)}, ensure_ascii=False))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
