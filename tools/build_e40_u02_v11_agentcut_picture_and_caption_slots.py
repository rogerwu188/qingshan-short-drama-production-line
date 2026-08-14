#!/usr/bin/env python3
"""Compile the admitted U02 V10 picture into an AgentCut preassembly.

This deliberately leaves audio and subtitle tracks empty until two exact,
commercial-rights-cleared Yunfei line assets have been admitted.  It is a
real renderable picture assembly, not a final U02 or release artifact.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_REL = Path(
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/"
    "u02_v10_rigid_prop_curtain_tail_v1/"
    "E40_U02_V10_RIGID_PROP_CURTAIN_TAIL_CANDIDATE_V1.mp4"
)
SOURCE_SHA = "f8df85a129bd7891127b709e5cb2d215e55eb0c7e09d07ccfcc426119dd8795f"
OUT_REL = Path(
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/"
    "u02_v11_agentcut_picture_audio_slot_preassembly_v1"
)
PROJECT_NAME = "E40_U02_V11_AGENTCUT_PICTURE_AUDIO_SLOT_PROJECT_V1.json"
OUTPUT_NAME = "E40_U02_V11_AGENTCUT_PICTURE_PREASSEMBLY_V1.mp4"
SLOT_NAME = "E40_U02_V11_EXACT_AUDIO_SUBTITLE_SLOT_MANIFEST_V1.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def dump(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main() -> int:
    source = ROOT / SOURCE_REL
    if not source.is_file() or sha256(source) != SOURCE_SHA:
        raise SystemExit("V10 admitted picture source missing or SHA mismatch")

    out_dir = ROOT / OUT_REL
    out_dir.mkdir(parents=True, exist_ok=True)
    output = out_dir / OUTPUT_NAME
    project = out_dir / PROJECT_NAME
    slots = out_dir / SLOT_NAME

    slot_payload = {
        "schema": "qingshan.e40.u02.v11.exact_audio_subtitle_slot_manifest.v1",
        "episode": "E40",
        "unit_id": "U02",
        "status": "PICTURE_COMPILED_AUDIO_AND_CAPTION_TIMES_RIGHTS_BLOCKED",
        "canonical_script_sha256": "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b",
        "canonical_manifest_sha256": "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1",
        "picture": {"path": str(SOURCE_REL), "sha256": SOURCE_SHA, "duration_seconds": 4.0},
        "ordered_slots": [
            {
                "line_id": "E40-DIA-001",
                "speaker": "云妃",
                "exact_text": "阿栓，在本宫手上。",
                "audio_path": None,
                "audio_sha256": None,
                "timeline_start_seconds": None,
                "timeline_duration_seconds": None,
                "subtitle_start_seconds": None,
                "subtitle_duration_seconds": None,
                "status": "BLOCKED_PENDING_COMMERCIAL_RIGHTS_CLEARED_SELECTED_YUNFEI_VOICE",
            },
            {
                "line_id": "E40-DIA-002",
                "speaker": "云妃",
                "exact_text": "拿他，换景朝一个接头人。",
                "audio_path": None,
                "audio_sha256": None,
                "timeline_start_seconds": None,
                "timeline_duration_seconds": None,
                "subtitle_start_seconds": None,
                "subtitle_duration_seconds": None,
                "status": "BLOCKED_PENDING_COMMERCIAL_RIGHTS_CLEARED_SELECTED_YUNFEI_VOICE",
            },
        ],
        "subtitle_style": {
            "font": "/System/Library/Fonts/STHeiti Medium.ttc",
            "size": 42,
            "color": "#FFFFFF",
            "outline": 3,
            "outlineColor": "#000000",
            "alignment": "bottom-center",
            "margins": {"left": 72, "right": 72, "top": 96, "bottom": 170},
            "wrap": 15,
            "background_box": False,
        },
        "timing_policy": "FILL_ONLY_FROM_ADMITTED_AUDIO_MEASURED_AUDIBLE_BOUNDARIES_PLUS_VERIFIED_ASR",
        "rights_gate": {
            "source_receipt": "workflow/tasks/agentcut_character_voice_refs_v1_20260723/yunfei_generation.json",
            "commercialUseMetadata_present": False,
            "releaseBlocked": True,
            "required_to_unlock": "Roger selects/confirms one available Yunfei voice and commercial-rights evidence records present=true and releaseBlocked=false",
        },
        "forbidden": [
            "GENERIC_TTS",
            "RELEASE_BLOCKED_YUNFEI_SOURCE",
            "SCRIPT_ESTIMATE_AS_FINAL_SUBTITLE_TIMING",
            "VIDEO_PROVIDER_RESUBMISSION",
            "RELEASE_OR_UPLOAD",
        ],
    }
    dump(slots, slot_payload)

    project_payload = {
        "version": "1.0",
        "assemblyMode": "STANDARD",
        "background": "black",
        "metadata": {
            "episode": "E40",
            "unit_id": "U02",
            "releaseAllowed": False,
            "platformUploadAllowed": False,
            "finalAssembly": False,
            "purpose": "V11 real AgentCut picture preassembly with exact audio/subtitle slots held fail-closed",
            "canonical_script_sha256": slot_payload["canonical_script_sha256"],
            "canonical_manifest_sha256": slot_payload["canonical_manifest_sha256"],
            "slot_manifest": str(slots),
            "audio_rights_blocker": "YUNFEI_COMMERCIAL_RIGHTS_PRESENT_FALSE_RELEASE_BLOCKED_TRUE",
        },
        "output": {
            "path": str(output),
            "width": 720,
            "height": 1280,
            "fps": 24,
            "videoCodec": "libx264",
            "audioCodec": "aac",
            "audioBitrate": "192k",
            "pixelFormat": "yuv420p",
            "videoBitrate": "20M",
            "threads": 1,
        },
        "timeline": {
            "videoTracks": [
                {
                    "id": "E40_U02_V11_ADMITTED_PICTURE",
                    "clips": [
                        {
                            "id": "E40-U02-V10-ADMITTED-PICTURE",
                            "source": str(source),
                            "start": 0.0,
                            "in": 0.0,
                            "duration": 4.0,
                            "metadata": {
                                "episode": "E40",
                                "unit_id": "U02",
                                "source_sha256": SOURCE_SHA,
                                "source_admission": "PASS_V10_U02_SILENT_VISUAL_FOR_AGENTCUT_ONLY",
                                "dialogue_ids": ["E40-DIA-001", "E40-DIA-002"],
                                "speaker": "云妃",
                                "face_visibility": "HIDDEN_BEHIND_CURTAIN",
                            },
                        }
                    ],
                }
            ],
            "audioTracks": [],
            "subtitleTracks": [],
        },
    }
    dump(project, project_payload)
    print(
        json.dumps(
            {
                "status": "PASS_PICTURE_PROJECT_AND_EXACT_SLOTS_COMPILED",
                "project": str(project),
                "project_sha256": sha256(project),
                "slot_manifest": str(slots),
                "slot_manifest_sha256": sha256(slots),
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
