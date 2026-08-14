#!/usr/bin/env python3
"""Build the E37 zero-credit AgentCut replacement-map project.

The generated project is intentionally PREVIS_ONLY. It materializes director
recipes and timing provenance without admitting static previs as production
video, dialogue, lipsync, or motion evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QA_PATH = ROOT / "qa/e37_preproduction_20260802/E37_FULL_EPISODE_TIMING_PREVIS_QA_V1.json"
BINDING_PATH = ROOT / (
    "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/"
    "E37_COMPLETE_VIDEO_PROMPT_BINDING_REGISTRY_V1.json"
)
UNIT_PLAN_PATH = ROOT / (
    "workflow/claude_writer_agent/production/e37_claude_writer_v2_4a738459_20260802/"
    "E37_NATURAL_VIDEO_UNITS_AND_ANCHOR_PLAN_V1.json"
)
SCRIPT_PATH = ROOT / "workflow/claude_writer_agent/scripts/E37剧本_ClaudeWriter_v2.md"
MANIFEST_PATH = ROOT / "workflow/claude_writer_agent/scripts/E37_manifest_v2.json"
OUT_PATH = ROOT / "configs/e37_agentcut_previs_replacement_project_v1_20260802.json"

EXPECTED_SCRIPT_SHA = "07a63a0c286be656feac59a0f31ea1bb159f3f7ce56f1172bb202832edf9db3a"
EXPECTED_MANIFEST_SHA = "9082f9d3b45bf0466476e98cb194d91d00d6775c2b762b5253c8f7557d31c33e"
EXPECTED_REEL_SHA = "bcc8295365fecee837e93a23c458b4972e39283aac6a6a0ce0483af08fbbe923"

RECIPE_BY_UNIT = {
    "U01": "camera.crane_rise_reveal",
    "U02": "camera.overhead_reveal",
    "U03": "camera.slow_push_in",
    "U04": "rhythm.interrupt_reset",
    "U05": "rhythm.domino_cascade",
    "U06": "rhythm.trailer_tension_release",
    "U07": "camera.slow_push_in",
    "U08": "camera.pull_back_isolation",
}

LIGHT_BY_SCENE = {
    "10-1": "NIGHT_CLEAR_DRY_EXTERIOR_AND_LONELY_LAMP_INTERIOR",
    "10-2": "NIGHT_CLEAR_DRY_INTERIOR_LONELY_LAMP",
    "10-3": "NIGHT_SUDDEN_RAIN_FIRE_INTERACTION",
    "10-4": "NEXT_NIGHT_RAIN_STOPPED_INTERIOR",
    "10-5": "DEEP_NIGHT_AFTER_RAIN_WARM_CLINIC_INTERIOR",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    if sha256(SCRIPT_PATH) != EXPECTED_SCRIPT_SHA:
        raise SystemExit("canonical script SHA mismatch")
    if sha256(MANIFEST_PATH) != EXPECTED_MANIFEST_SHA:
        raise SystemExit("canonical manifest SHA mismatch")

    qa = load_json(QA_PATH)
    bindings = load_json(BINDING_PATH)
    unit_plan = load_json(UNIT_PLAN_PATH)
    if qa.get("reel_sha256") != EXPECTED_REEL_SHA:
        raise SystemExit("full-episode timing previs SHA mismatch")

    binding_by_segment = {row["segment_id"]: row for row in bindings["segment_bindings"]}
    unit_by_id = {row["unit_id"]: row for row in unit_plan["units"]}
    clips = []
    replacement_registry = []

    for index, row in enumerate(qa["clips"], start=1):
        segment_id = row["segment_id"]
        unit_id = segment_id.split("-", 1)[0]
        binding = binding_by_segment[segment_id]
        unit = unit_by_id[unit_id]
        prompt_path = ROOT / binding["prompt_file"]
        source_path = ROOT / row["previs_clip"]
        if sha256(source_path) != row["previs_clip_sha256"]:
            raise SystemExit(f"previs source SHA mismatch: {segment_id}")
        if not prompt_path.is_file():
            raise SystemExit(f"missing prompt: {segment_id}")

        recipe_id = RECIPE_BY_UNIT[unit_id]
        metadata = {
            "episode": "E37",
            "scene_id": unit["scene"],
            "beat_id": segment_id,
            "segment_id": segment_id,
            "wave": row["wave"],
            "canonical_lines": binding["canonical_lines"],
            "prompt_path": str(prompt_path),
            "prompt_sha256": sha256(prompt_path),
            "previs_source_sha256": row["previs_clip_sha256"],
            "accepted_still_path": str(ROOT / row["accepted_still"]),
            "accepted_still_sha256": row["accepted_still_sha256"],
            "importance": unit["importance"],
            "pass_score": unit["pass_score"],
            "purpose": unit["purpose"],
            "narrative_function": "causal_progress",
            "new_information": f"{segment_id}:{unit['purpose']}",
            "semantic_group": f"E37_{segment_id}_UNIQUE",
            "fallback_only": False,
            "physical_chain": unit["physical_chain"],
            "first_frame_motion_state": unit["first_frame_motion_state"],
            "ambient_life": unit["ambient_life"],
            "source_qa": "PASS_PREVIS_SCOPE_ONLY_NOT_EDIT_ADMISSION",
            "admission": "PREVIS_ONLY_NOT_PRODUCTION_VIDEO_NOT_DIALOGUE_NOT_LIPSYNC_NOT_MOTION_EVIDENCE",
            "replacement_required": True,
            "replacement_condition": "Bind one independently QA-accepted generated production clip with exact candidate SHA before production assembly.",
            "cut_reason": "ESTABLISH_ONCE" if index == 1 else "CAUSAL_PROGRESS",
            "light_key": LIGHT_BY_SCENE[unit["scene"]],
            "axis_line": f"E37_{unit['scene']}_PRIMARY_180_AXIS",
            "eyeline": f"{segment_id}_PRIMARY_SUBJECT_TO_CAUSAL_TARGET",
            "shot_recipe": {
                "recipe_id": recipe_id,
                "version": "1.0.0",
                "override": {
                    "dramatic_intent": unit["purpose"],
                    "motion_arc": {
                        "phases": [
                            {
                                "phase_id": "setup",
                                "start_ratio": 0.0,
                                "end_ratio": 0.22,
                                "description": "establish the readable causal setup",
                                "camera_state": {"energy": 0.25},
                            },
                            {
                                "phase_id": "contact",
                                "start_ratio": 0.22,
                                "end_ratio": 0.70,
                                "description": "execute the visible physical contact and causal change",
                                "camera_state": {"energy": 0.72},
                            },
                            {
                                "phase_id": f"beat_{segment_id.lower()}",
                                "start_ratio": 0.70,
                                "end_ratio": 0.72,
                                "description": "unique exact-frame beat anchor for this timeline clip",
                                "camera_state": {"energy": 0.72},
                            },
                            {
                                "phase_id": "result",
                                "start_ratio": 0.72,
                                "end_ratio": 1.0,
                                "description": "hold the visibly changed state long enough to read",
                                "camera_state": {"energy": 0.60},
                            },
                        ]
                    },
                    "action": {
                        "setup": unit["first_frame_motion_state"],
                        "contact": unit["physical_chain"],
                        "result": f"Land and hold the readable end state for {segment_id} before the next causal handoff.",
                    },
                    "planned_hold": {
                        "windows": [{
                            "phase_id": "result_read",
                            "hold_id": "result_read",
                            "start_ratio": 0.82,
                            "end_ratio": 1.0,
                            "reason": f"{segment_id} result and information readability",
                        }]
                    },
                    "beat_anchor": {
                        "phase_id": f"beat_{segment_id.lower()}",
                        "semantic": f"{segment_id.lower()}_primary_contact",
                    },
                    "sfx_cues": [{
                        "cue_id": f"{segment_id.lower()}_primary_contact",
                        "semantic": "symbolic motivated action contact; no audio asset bound in previs",
                        "phase_id": f"beat_{segment_id.lower()}",
                        "offset_seconds": 0,
                        "asset_path": None,
                        "license": None,
                        "license_status": "symbolic_only",
                    }],
                },
            },
        }
        clips.append({
            "id": f"E37-{segment_id}-PREVIS-REPLACEMENT-SLOT",
            "source": str(source_path),
            "start": row["timeline_start_seconds"],
            "in": 0.0,
            "duration": row["duration_seconds"],
            "metadata": metadata,
        })
        replacement_registry.append({
            "clip_id": clips[-1]["id"],
            "segment_id": segment_id,
            "timeline_start_seconds": row["timeline_start_seconds"],
            "timeline_end_seconds": row["timeline_end_seconds"],
            "placeholder_sha256": row["previs_clip_sha256"],
            "expected_candidate_sha256": None,
            "status": "AWAITING_INDEPENDENTLY_QA_ACCEPTED_GENERATED_VIDEO",
            "importance": unit["importance"],
            "pass_score": unit["pass_score"],
            "hard_fail_overrides_score": ["IDENTITY", "SAFETY", "ERA", "OCR", "MEDIA_INTEGRITY"],
        })

    project = {
        "version": "1.0",
        "background": "black",
        "releaseProject": False,
        "requireCutReason": True,
        "requireBurnedSubtitles": False,
        "runtimePolicy": {"allowShorter": False, "paddingForbidden": True, "onCoverageGap": "fail"},
        "assemblyMode": "STANDARD",
        "sourceAdmissionPolicy": {"enabled": False},
        "shotRecipePolicy": {
            "enabled": True,
            "registryId": "agentcut.short_drama.director_recipes",
            "registryVersion": "1.0.0",
            "projectOverrides": {},
        },
        "releaseGate": {"required": False},
        "metadata": {
            "episode": "E37",
            "status": "NOT_FINAL_PREVIS_ONLY_REPLACEMENT_MAP",
            "production_profile": "E37_PREVIS_ONLY_ZERO_CREDIT",
            "agentcut_required_version": "0.9.17",
            "canonical_script": str(SCRIPT_PATH),
            "canonical_script_sha256": EXPECTED_SCRIPT_SHA,
            "canonical_manifest": str(MANIFEST_PATH),
            "canonical_manifest_sha256": EXPECTED_MANIFEST_SHA,
            "source_timing_qa": str(QA_PATH),
            "source_timing_qa_sha256": sha256(QA_PATH),
            "source_reel": str(ROOT / qa["reel"]),
            "source_reel_sha256": EXPECTED_REEL_SHA,
            "prompt_binding_registry": str(BINDING_PATH),
            "prompt_binding_registry_sha256": sha256(BINDING_PATH),
            "unit_plan": str(UNIT_PLAN_PATH),
            "unit_plan_sha256": sha256(UNIT_PLAN_PATH),
            "hard_scope_limit": "NOT_PRODUCTION_VIDEO_NOT_NATIVE_DIALOGUE_NOT_LIPSYNC_NOT_MOTION_ADMISSION",
            "replacement_registry": replacement_registry,
            "credits": {"pay": 0, "refund": 0, "net": 0},
        },
        "qingshanAudit": {
            "releaseEligible": False,
            "releaseBlock": "All 22 PREVIS_ONLY placeholders require exact-SHA production-video replacement and full production QA.",
            "platformMutationAuthorized": False,
        },
        "output": {
            "path": str(ROOT / qa["reel"]),
            "width": 720,
            "height": 1280,
            "fps": 24,
            "videoCodec": "libx264",
            "audioCodec": "aac",
            "pixelFormat": "yuv420p",
            "threads": 4,
        },
        "timeline": {
            "videoTracks": [{"id": "E37_PREVIS_REPLACEMENT_MAP", "clips": clips}],
            "audioTracks": [],
            "subtitleTracks": [],
        },
    }
    OUT_PATH.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT_PATH), "clips": len(clips), "sha256": sha256(OUT_PATH)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
