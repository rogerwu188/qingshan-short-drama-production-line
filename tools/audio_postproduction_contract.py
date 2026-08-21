#!/usr/bin/env python3
"""Validate explicit, mutually exclusive AgentCut postproduction audio profiles.

This is contract enforcement used by existing registered audio/BGM gates. It
does not create a new gate id.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROFILE_CONFIG = ROOT / "configs/audio_postproduction_profiles_v1_20260821.json"
REQUIRED_SAMPLE_RATE_HZ = 48000


def load_profiles(path: Path = PROFILE_CONFIG) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _track_ids(project: dict) -> set[str]:
    return {
        str(track.get("id") or "")
        for track in project.get("timeline", {}).get("audioTracks", [])
        if isinstance(track, dict)
    }


def _native_dialogue_binding_failures(project: dict, profile: dict) -> list[str]:
    """Forbid redubbing a speaking multimodal shot with another audio source."""
    failures: list[str] = []
    metadata = project.get("metadata") or {}
    expected_policy = str(profile.get("source_audio_policy") or "")
    if metadata.get("source_audio_policy") != expected_policy:
        failures.append("SOURCE_AUDIO_POLICY_PROFILE_MISMATCH")

    if expected_policy == "NO_NATIVE_DIALOGUE_WITH_EVIDENCE":
        evidence = metadata.get("native_dialogue_absence_evidence") or {}
        if evidence.get("status") != "PASS" or not str(evidence.get("report") or "").strip():
            failures.append("NATIVE_DIALOGUE_ABSENCE_EVIDENCE_REQUIRED")
        return failures
    if expected_policy != "PRESERVE_NATIVE_MULTIMODAL_AUDIO":
        return failures

    video_sources: dict[str, str] = {}
    video_tasks: dict[str, str] = {}
    for track in project.get("timeline", {}).get("videoTracks", []):
        for clip in track.get("clips") or []:
            clip_meta = clip.get("metadata") or {}
            source_id = str(clip_meta.get("source_id") or "")
            if source_id:
                video_sources[source_id] = str(Path(str(clip.get("source") or "")).expanduser().resolve())
                video_tasks[source_id] = str(clip_meta.get("multimodal_task_id") or "")

    for track in project.get("timeline", {}).get("audioTracks", []):
        if str(track.get("id") or "") == "Audio.BGM":
            continue
        for clip in track.get("clips") or []:
            clip_meta = clip.get("metadata") or {}
            dialogue_lines = clip_meta.get("dialogue_lines") or []
            expected_text = str(clip_meta.get("expected_text") or "")
            classification = str(clip_meta.get("dialogue_classification") or "")
            if classification not in {"SPEAKING", "NON_SPEAKING"}:
                failures.append(f"DIALOGUE_CLASSIFICATION_REQUIRED:{str(clip.get('id') or 'UNKNOWN')}")
                continue
            has_dialogue = classification == "SPEAKING"
            if has_dialogue != bool(dialogue_lines or expected_text.strip()):
                failures.append(f"DIALOGUE_CLASSIFICATION_CONTENT_MISMATCH:{str(clip.get('id') or 'UNKNOWN')}")
            if not has_dialogue:
                continue
            source_id = str(clip_meta.get("source_id") or "")
            label = str(clip.get("id") or source_id or "UNKNOWN")
            if clip_meta.get("audio_origin") != "NATIVE_MULTIMODAL_SOURCE":
                failures.append(f"SPEAKING_AUDIO_NOT_NATIVE_MULTIMODAL:{label}")
            video_source = video_sources.get(source_id)
            audio_source = str(Path(str(clip.get("source") or "")).expanduser().resolve())
            if not video_source:
                failures.append(f"SPEAKING_VIDEO_SOURCE_BINDING_MISSING:{label}")
            elif audio_source != video_source:
                failures.append(f"SPEAKING_AUDIO_VIDEO_SOURCE_MISMATCH:{label}")
            video_task_id = video_tasks.get(source_id) or ""
            audio_task_id = str(clip_meta.get("multimodal_task_id") or "")
            if not video_task_id or not audio_task_id:
                failures.append(f"SPEAKING_MULTIMODAL_TASK_ID_MISSING:{label}")
            elif video_task_id != audio_task_id:
                failures.append(f"SPEAKING_AUDIO_VIDEO_TASK_ID_MISMATCH:{label}")
            if clip_meta.get("reused_for_silent_visual"):
                failures.append(f"SPEAKING_AUDIO_REUSED_FROM_OTHER_CANDIDATE:{label}")
    return failures


def validate_audio_profile(project: dict, *, require_music: bool = False) -> list[str]:
    failures: list[str] = []
    metadata = project.get("metadata") or {}
    profile_id = str(metadata.get("audio_profile_id") or "")
    profiles = load_profiles().get("profiles") or {}
    if not profile_id:
        return ["AUDIO_PROFILE_NOT_DECLARED"]
    profile = profiles.get(profile_id)
    if not profile:
        return [f"AUDIO_PROFILE_UNKNOWN:{profile_id}"]

    failures.extend(_native_dialogue_binding_failures(project, profile))

    declared_contract = str(metadata.get("audio_profile_contract") or "")
    expected_contract = str(PROFILE_CONFIG.relative_to(ROOT))
    if declared_contract != expected_contract:
        failures.append("AUDIO_PROFILE_CONTRACT_PATH_MISMATCH")

    output = project.get("output") or {}
    master = project.get("masterAudioPolicy") or {}
    output_rate = output.get("audioSampleRate")
    master_rate = master.get("sampleRateHz")
    if output_rate != REQUIRED_SAMPLE_RATE_HZ:
        failures.append("OUTPUT_AUDIO_SAMPLE_RATE_MUST_BE_48000")
    if master_rate != REQUIRED_SAMPLE_RATE_HZ:
        failures.append("MASTER_AUDIO_SAMPLE_RATE_MUST_BE_48000")

    sound_contract = metadata.get("sound_design_contract") or {}
    if sound_contract.get("mode") != profile.get("sound_design_mode"):
        failures.append("SOUND_DESIGN_MODE_PROFILE_MISMATCH")
    if sound_contract.get("external_bgm_allowed") is not profile.get("external_bgm_allowed"):
        failures.append("EXTERNAL_BGM_PERMISSION_PROFILE_MISMATCH")

    track_ids = _track_ids(project)
    has_bgm_track = "Audio.BGM" in track_ids
    has_bgm_contract = bool(metadata.get("bgm_contract"))
    bgm_mode = str(profile.get("bgm_mode") or "REQUIRED")
    if has_bgm_track != has_bgm_contract:
        failures.append("BGM_TRACK_AND_CONTRACT_MUST_APPEAR_TOGETHER")
    if profile.get("bgm_track_required") and not has_bgm_track:
        failures.append("AUDIO_BGM_TRACK_REQUIRED_BY_PROFILE")
    if not profile.get("external_bgm_allowed") and has_bgm_track:
        failures.append("AUDIO_BGM_TRACK_FORBIDDEN_BY_PROFILE")
    if profile.get("bgm_contract_required") and not has_bgm_contract:
        failures.append("BGM_CONTRACT_REQUIRED_BY_PROFILE")
    if not profile.get("external_bgm_allowed") and has_bgm_contract:
        failures.append("BGM_CONTRACT_FORBIDDEN_BY_PROFILE")
    if require_music and not profile.get("external_bgm_allowed"):
        failures.append("BGM_GATE_CALLED_FOR_NO_EXTERNAL_BGM_PROFILE")
    if require_music and (not has_bgm_track or not has_bgm_contract):
        failures.append("BGM_GATE_REQUIRES_TRACK_AND_CONTRACT")
    if bgm_mode == "SELECTIVE" and has_bgm_contract:
        contract = metadata.get("bgm_contract") or {}
        if contract.get("usage_mode") != "SELECTIVE_NARRATIVE_CUES":
            failures.append("SELECTIVE_BGM_USAGE_MODE_REQUIRED")
        cues = contract.get("cues") or []
        if not cues:
            failures.append("SELECTIVE_BGM_CUES_REQUIRED")
        for index, cue in enumerate(cues, start=1):
            cue_id = str(cue.get("cue_id") or f"ROW-{index}")
            if not str(cue.get("narrative_function") or "").strip():
                failures.append(f"SELECTIVE_BGM_NARRATIVE_FUNCTION_MISSING:{cue_id}")
            for field in ("timeline_start", "duration"):
                value = cue.get(field)
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    failures.append(f"SELECTIVE_BGM_{field.upper()}_INVALID:{cue_id}")
            if isinstance(cue.get("duration"), (int, float)) and cue.get("duration") <= 0:
                failures.append(f"SELECTIVE_BGM_DURATION_NONPOSITIVE:{cue_id}")
    return failures
