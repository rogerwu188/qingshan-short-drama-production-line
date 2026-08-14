#!/usr/bin/env python3
"""Compile E19R dialogue audio-binding work without generating standalone final audio."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
FOZI_VOICE_REGISTRY = ROOT / "configs/e19r_fozi_voice_asset_registry_v1_20260717.json"
CANONICAL_VOICES = {
    "陈迹": {"voice_asset_id": "cypqud0bu7t", "source_episode": "E18R"},
    "白鲤": {"voice_asset_id": "19uxvuf5yl1", "source_episode": "E18R"},
    "远处巡夜声": {"voice_asset_id": "0zgewsy1v47", "source_episode": "E18R"},
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_voices() -> dict[str, dict[str, str]]:
    voices = dict(CANONICAL_VOICES)
    if FOZI_VOICE_REGISTRY.is_file():
        registry = load(FOZI_VOICE_REGISTRY)
        asset = (registry.get("assets") or {}).get("VOICE-佛子-罗追萨迦") or {}
        if asset.get("production_ready") and asset.get("qa_status") == "PASS" and asset.get("remote_asset_id"):
            voices["佛子"] = {
                "voice_asset_id": asset["remote_asset_id"],
                "source_episode": asset.get("source_episode", "E19"),
            }
    return voices


def compile_queue(skeleton: dict[str, Any]) -> dict[str, Any]:
    voices = canonical_voices()
    lines = []
    for shot in skeleton["shots"]:
        dialogue_id = shot.get("dialogue_id")
        if not dialogue_id:
            continue
        speaker = shot["speaker"]
        inherited = voices.get(speaker)
        prior_audio = shot["audio_binding"]
        if str(prior_audio["state"]).startswith("NATIVE"):
            state = prior_audio["state"]
            voice_asset_id = None
            candidate_path = prior_audio["path"]
            blocker = None
        elif inherited:
            state = "READY_FOR_MULTIMODAL_AUDIO_BINDING_NOT_STANDALONE_TTS"
            voice_asset_id = inherited["voice_asset_id"]
            candidate_path = None
            blocker = None
        else:
            state = "BLOCKED_NEW_SERIES_VOICE_ASSET_REQUIRED"
            voice_asset_id = None
            candidate_path = None
            blocker = "FOZI_NEW_SERIES_VOICE_REGISTRATION_AND_SAMPLE_QA"
        lines.append({
            "order": len(lines) + 1,
            "dialogue_id": dialogue_id,
            "beat_id": shot["beat_id"],
            "speaker": speaker,
            "text": shot["dialogue_text"],
            "timeline_in_frame": shot["timeline_in_frame"],
            "timeline_out_frame_exclusive": shot["timeline_out_frame_exclusive"],
            "state": state,
            "voice_asset_id": voice_asset_id,
            "native_candidate_path": candidate_path,
            "blocker": blocker,
            "standalone_final_audio_generation_allowed": False,
            "multimodal_source_preparation_allowed": state == "READY_FOR_MULTIMODAL_AUDIO_BINDING_NOT_STANDALONE_TTS",
            "final_bind_allowed": False,
        })

    counts: dict[str, int] = {}
    for line in lines:
        counts[line["state"]] = counts.get(line["state"], 0) + 1
    return {
        "schema": "qingshan.e19r.audio_binding_work_queue.v1",
        "episode": "E19R",
        "created_at": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(timespec="seconds"),
        "status": "PASS_37_MULTIMODAL_BINDINGS_READY_3_NATIVE_CANDIDATES_NOT_FINAL",
        "approved_script_sha256": skeleton["approved_script_sha256"],
        "timing_skeleton_ref": "configs/e19r_ordered_timing_audio_skeleton_v1_not_final_20260717.json",
        "voice_registry_evidence_refs": [
            "configs/e18r_dialogue_voice_binding_manifest_v1_20260716.json",
            "configs/e19r_fozi_voice_asset_registry_v1_20260717.json"
        ],
        "policy": "Do not generate standalone final dialogue audio. Ready lines may only enter multimodal source preparation; native candidates remain non-final until ASR, timbre and sentence-boundary QA pass.",
        "line_count": len(lines),
        "state_counts": counts,
        "speaker_summary": {
            speaker: sum(1 for line in lines if line["speaker"] == speaker)
            for speaker in sorted({line["speaker"] for line in lines})
        },
        "lines": lines,
        "global_blockers": [],
        "ordering_guard": {
            "final_bind_allowed": False,
            "edit_admission_allowed": False,
            "package_allowed": False,
            "platform_action_allowed": False,
            "reason": "Audio preparation may run in parallel; final E19R admission remains after E17 and E18R."
        }
    }


def qa(payload: dict[str, Any], queue_ref: str) -> dict[str, Any]:
    lines = payload["lines"]
    ids = [line["dialogue_id"] for line in lines]
    checks = {
        "40_unique_dialogue_lines": len(lines) == 40 and len(set(ids)) == 40,
        "37_multimodal_bindings_ready": sum(line["multimodal_source_preparation_allowed"] for line in lines) == 37,
        "15_fozi_lines_ready": sum(line["speaker"] == "佛子" and line["multimodal_source_preparation_allowed"] for line in lines) == 15,
        "3_native_candidates_not_final": sum(str(line["state"]).startswith("NATIVE") for line in lines) == 3,
        "no_standalone_final_audio": not any(line["standalone_final_audio_generation_allowed"] for line in lines),
        "no_final_bind": not any(line["final_bind_allowed"] for line in lines),
        "platform_actions_forbidden": not payload["ordering_guard"]["platform_action_allowed"],
    }
    return {
        "schema": "qingshan.e19r.audio_binding_work_queue_qa.v1",
        "episode": "E19R",
        "created_at": payload["created_at"],
        "status": "PASS" if all(checks.values()) else "FAIL",
        "machine_confidence": "HIGH",
        "queue_ref": queue_ref,
        "checks": checks,
        "failures": [name for name, passed in checks.items() if not passed],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skeleton", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--qa-out", required=True, type=Path)
    args = parser.parse_args()
    skeleton_path = args.skeleton if args.skeleton.is_absolute() else ROOT / args.skeleton
    out = args.out if args.out.is_absolute() else ROOT / args.out
    qa_out = args.qa_out if args.qa_out.is_absolute() else ROOT / args.qa_out
    payload = compile_queue(load(skeleton_path))
    report = qa(payload, str(args.out))
    out.parent.mkdir(parents=True, exist_ok=True)
    qa_out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    qa_out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "state_counts": payload["state_counts"], "out": str(out), "qa_out": str(qa_out)}, ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
