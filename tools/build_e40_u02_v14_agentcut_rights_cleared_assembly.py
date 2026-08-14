#!/usr/bin/env python3
"""Build the admitted E40 U02 AgentCut audiovisual assembly project."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA = ROOT / "qa/e40_production_20260814/u02_v13_kokoro_pace_repair_audio_candidates_v1/E40_U02_V13_KOKORO_PACE_REPAIR_MACHINE_QA_V1.json"
RIGHTS = ROOT / "qa/e40_preproduction_20260814/u02_v12_kokoro_rights_clearance_v1/E40_U02_V12_KOKORO_COMMERCIAL_RIGHTS_EVIDENCE_V1.json"
PICTURE = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v10_rigid_prop_curtain_tail_v1/E40_U02_V10_RIGID_PROP_CURTAIN_TAIL_CANDIDATE_V1.mp4"
OUT_DIR = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u02_v14_agentcut_rights_cleared_assembly_v1"
PROJECT = OUT_DIR / "E40_U02_V14_AGENTCUT_RIGHTS_CLEARED_ASSEMBLY_PROJECT_V1.json"
OUTPUT = OUT_DIR / "E40_U02_V14_AGENTCUT_RIGHTS_CLEARED_ASSEMBLY_NOT_FINAL.mp4"
SLOTS = OUT_DIR / "E40_U02_V14_ADMITTED_AUDIO_SUBTITLE_SLOT_MANIFEST_V1.json"
RECEIPT = ROOT / "workflow/tasks/E40_U02_V14_AGENTCUT_RIGHTS_CLEARED_ASSEMBLY_BUILD_20260814.json"
PICTURE_SHA = "f8df85a129bd7891127b709e5cb2d215e55eb0c7e09d07ccfcc426119dd8795f"
CANON_SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
CANON_MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise


def main() -> int:
    qa = json.loads(QA.read_text(encoding="utf-8"))
    rights = json.loads(RIGHTS.read_text(encoding="utf-8"))
    if sha256(PICTURE) != PICTURE_SHA:
        raise SystemExit("FAIL_CLOSED_PICTURE_SHA_MISMATCH")
    if qa.get("status") != "PASS_SELECTED_RIGHTS_CLEARED_VOICE" or qa.get("selected_voice") != "zf_001":
        raise SystemExit("FAIL_CLOSED_AUDIO_QA_NOT_ADMITTED")
    if rights.get("releaseBlocked") is not False:
        raise SystemExit("FAIL_CLOSED_RIGHTS_NOT_RELEASE_CLEAR")
    selected = sorted((item for item in qa["candidates"] if item["voice"] == "zf_001"), key=lambda item: item["line_id"])
    if [item["line_id"] for item in selected] != ["E40-DIA-001", "E40-DIA-002"]:
        raise SystemExit("FAIL_CLOSED_EXACT_DIALOGUE_SET_MISMATCH")

    start = 0.08
    slots = []
    audio_clips = []
    captions = []
    for index, item in enumerate(selected, 1):
        duration = item["audio_metrics"]["duration_seconds"]
        path = ROOT / item["normalized_path"]
        if sha256(path) != item["normalized_sha256"] or item["asr_similarity"] != 1.0:
            raise SystemExit("FAIL_CLOSED_SELECTED_AUDIO_BINDING_OR_ASR")
        audio_clips.append({
            "id": f"{item['line_id']}-RIGHTS-CLEARED-VOICE",
            "source": str(path),
            "start": round(start, 6),
            "in": 0.0,
            "duration": round(duration, 6),
            "volume": 1.0,
            "metadata": {
                "dialogue_id": item["line_id"],
                "speaker": "云妃",
                "voice": "zf_001",
                "source_sha256": item["normalized_sha256"],
                "rights_evidence_sha256": sha256(RIGHTS),
                "exact_asr_pass": True,
            },
        })
        captions.append({
            "id": f"E40-U02-CAP-{index:03d}",
            "dialogue_id": item["line_id"],
            "text": item["exact_text"],
            "start": round(start, 6),
            "duration": round(duration, 6),
            "metadata": {"speaker": "云妃", "source": "canonical_exact_text"},
        })
        slots.append({
            "line_id": item["line_id"],
            "exact_text": item["exact_text"],
            "audio_path": item["normalized_path"],
            "audio_sha256": item["normalized_sha256"],
            "timeline_start_seconds": round(start, 6),
            "timeline_duration_seconds": round(duration, 6),
            "subtitle_start_seconds": round(start, 6),
            "subtitle_duration_seconds": round(duration, 6),
            "status": "ADMITTED_EXACT_ASR_AND_RIGHTS_CLEAR",
        })
        start += duration + 0.12
    if start - 0.12 > 3.92:
        raise SystemExit("FAIL_CLOSED_AUDIO_RUNTIME_EXCEEDS_PICTURE")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    atomic_json(SLOTS, {
        "schema": "qingshan.e40.u02.v14.admitted_audio_subtitle_slots.v1",
        "status": "PASS_TWO_OF_TWO_ADMITTED",
        "canonical_script_sha256": CANON_SCRIPT_SHA,
        "canonical_manifest_sha256": CANON_MANIFEST_SHA,
        "picture_sha256": PICTURE_SHA,
        "voice": "zf_001",
        "rights_evidence": str(RIGHTS.relative_to(ROOT)),
        "rights_evidence_sha256": sha256(RIGHTS),
        "ordered_slots": slots,
    })
    project = {
        "version": "1.0",
        "background": "black",
        "metadata": {
            "episode": "E40", "unit_id": "U02", "status": "AGENTCUT_UNIT_ASSEMBLY_NOT_FINAL",
            "releaseAllowed": False, "platformUploadAllowed": False, "finalAssembly": False,
            "canonical_script_sha256": CANON_SCRIPT_SHA,
            "canonical_manifest_sha256": CANON_MANIFEST_SHA,
            "rights_evidence_sha256": sha256(RIGHTS),
            "subtitle_contract": {"coverage": "2/2", "burned_in": True},
        },
        "output": {
            "path": str(OUTPUT), "width": 720, "height": 1280, "fps": 24,
            "videoCodec": "libx264", "audioCodec": "aac", "audioBitrate": "192k",
            "pixelFormat": "yuv420p", "threads": 4,
        },
        "masterAudioPolicy": {
            "required": True, "limiter": True, "truePeakCeilingDbtp": -1.0,
            "codecHeadroomDb": 1.5, "loudnessTargetLufs": -16, "loudnessRangeLu": 11,
            "maxClippedSamples": 0,
        },
        "expectedDialogueIds": ["E40-DIA-001", "E40-DIA-002"],
        "timeline": {
            "videoTracks": [{"id": "E40_U02_V14_ADMITTED_PICTURE", "clips": [{
                "id": "E40-U02-V10-ADMITTED-PICTURE", "source": str(PICTURE),
                "start": 0.0, "in": 0.0, "duration": 4.0,
                "metadata": {"source_sha256": PICTURE_SHA, "source_admission": "PASS_V10_U02_SILENT_VISUAL_FOR_AGENTCUT_ONLY"},
            }]}],
            "audioTracks": [{"id": "E40_U02_EXACT_DIALOGUE_VOICE", "clips": audio_clips}],
            "subtitleTracks": [{
                "id": "E40_U02_ZH_CN_BURNIN", "enabled": True,
                "style": {
                    "font": "/System/Library/Fonts/STHeiti Medium.ttc", "size": 42,
                    "color": "#FFFFFF", "outline": 3, "outlineColor": "#000000",
                    "alignment": "bottom-center",
                    "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170}, "wrap": 15,
                },
                "clips": captions,
            }],
        },
    }
    atomic_json(PROJECT, project)
    atomic_json(RECEIPT, {
        "schema": "qingshan.e40.u02.v14.agentcut_assembly_build.v1",
        "status": "READY_VALIDATE_AND_RENDER",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project": str(PROJECT.relative_to(ROOT)), "project_sha256": sha256(PROJECT),
        "output": str(OUTPUT.relative_to(ROOT)),
        "slot_manifest": str(SLOTS.relative_to(ROOT)), "slot_manifest_sha256": sha256(SLOTS),
        "selected_voice": "zf_001", "dialogue_coverage": "2/2",
        "provider_post_count": 0, "credits": 0,
    })
    print(json.dumps({"status": "READY_VALIDATE_AND_RENDER", "project": str(PROJECT), "output": str(OUTPUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
