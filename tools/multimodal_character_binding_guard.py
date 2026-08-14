#!/usr/bin/env python3
"""Block video submission when face, voice, dialogue, props, and abilities are not one entity."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
VOICE_REGISTRY = ROOT / "configs/series_voice_reference_registry_current_20260723.json"
AGENTCUT_VOICE_POLICY = ROOT / "configs/agentcut_character_voice_reference_policy_v1.json"
CHARACTER_REGISTRY = ROOT / "configs/series_character_asset_registry_20260712.json"

ENTITY_ALIASES = {
    "chenji": ("陈迹", "CHAR-陈迹-古装"),
    "baili": ("白鲤", "CHAR-白鲤-古装"),
    "wuyun": ("乌云", "CHAR-乌云-猫"),
    "jiaotu": ("皎兔", "CHAR-皎兔-古装"),
    "yunyang": ("云羊", "CHAR-云羊-古装"),
    "yao_taiyi": ("姚太医", "CHAR-姚太医-古装"),
    "zhangxia": ("张夏", "CHAR-张夏-古装"),
    "yunfei": ("云妃", "CHAR-云妃-古装"),
    "xibing": ("喜饼", "CHAR-喜饼-古装"),
    "fozi": ("佛子", "CHAR-佛子-古装"),
    "dengshi": ("灯使", "CHAR-灯使-古装"),
    "shedengke": ("佘登科", "CHAR-佘登科-古装"),
    "shizi": ("世子", "CHAR-世子-古装"),
    "wangfu_servant": ("王府仆从", "CHAR-王府仆从-古装"),
    "night_watch": ("巡夜人", "CHAR-巡夜人-古装"),
    "passerby_hushed": ("路人低声", "CHAR-路人低声-古装"),
    "yanjing": ("严敬", "CHAR-严敬-古装"),
    "wangfu_messenger": ("王府传话人", "CHAR-王府传话人-古装"),
    "messenger": ("递信人", "CHAR-递信人-E36-古装"),
    "carriage_voice": ("车中人", "CHAR-车中人-古装"),
    "distant_voice": ("远处声音", "CHAR-远处声音-古装"),
    "coroner": ("验尸官", "CHAR-验尸官-古装"),
    "qisan": ("齐三", "CHAR-齐三-古装"),
    "killer": ("巡检司杀手", "CHAR-巡检司杀手-古装"),
}

# These are identity contradictions, not merely wardrobe style preferences.
FORBIDDEN_APPEARANCE_PHRASES = {
    "chenji": ("黑衣年轻陈迹", "黑衣陈迹", "黑袍陈迹"),
    "yunyang": ("灰衣云羊", "灰袍云羊", "灰衣年轻云羊"),
}

DIALOGUE_CHARACTER_LIMIT = 30
GENERIC_TTS_PATTERN = re.compile(r"(?:Azure|Edge\s*TTS|[A-Za-z-]+Neural)", re.I)
AGENTCUT_VOICE_EXEMPTIONS = {"chenji", "baili"}
POSE_FIRST_PATTERN = re.compile(r"先摆(?:出)?姿势|摆好姿势再|定格起手|pose[- ]first", re.I)
SLOW_MOTION_PATTERN = re.compile(r"慢动作|慢镜头|slow[ -]?motion", re.I)
EFFECT_TERMS = ("悬浮", "漂浮", "变色", "光幕", "冰幕", "水幕", "冰流", "阴神", "皮影")
ALLOWED_EFFECT_SOURCES = {"CLAUDE_SCRIPT", "CANONICAL_ABILITY"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _absolute(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def _sha(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _prompt(task: dict) -> str:
    value = task.get("prompt_file") or task.get("prompt_path")
    if value:
        try:
            return _absolute(value).read_text(encoding="utf-8")
        except OSError:
            return ""
    return str(task.get("prompt") or "")


def _positive_motion_directives(prompt: str) -> str:
    """Exclude explicit negative constraints before motion-directive checks."""
    positive = prompt.split("NEGATIVE_PROMPT:", 1)[0]
    positive = re.sub(
        r"(?:禁止|严禁|不得|不可)[^。；\n]*(?:慢动作|慢镜头|slow[ -]?motion)[^。；\n]*",
        " ",
        positive,
        flags=re.I,
    )
    return positive


def _dialogue_length(text: str) -> int:
    """Count spoken CJK/alphanumeric characters while ignoring punctuation."""
    return len(re.findall(r"[\u3400-\u9fffA-Za-z0-9]", text))


def _voice_authority() -> dict[str, dict]:
    return {row["entity_id"]: row for row in _load(VOICE_REGISTRY).get("major_roles", [])}


def _agentcut_voice_policy() -> dict[str, dict]:
    return {row["entity_id"]: row for row in _load(AGENTCUT_VOICE_POLICY).get("roles", [])}


def _performance_brief_sha256(spec: dict) -> str:
    brief = {
        key: spec[key]
        for key in (
            "identity", "social_position", "temperament", "dramatic_function",
            "voice_id", "voice_name", "sample_text", "emotion", "speed",
        )
    }
    return hashlib.sha256(
        json.dumps(brief, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _character_authority() -> dict[str, dict]:
    rows = _load(CHARACTER_REGISTRY).get("characters", {})
    return {entity_id: rows.get(registry_id, {}) for entity_id, (_, registry_id) in ENTITY_ALIASES.items()}


def binding_digest(bindings: list[dict]) -> str:
    payload = json.dumps(bindings, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _named_entities(task: dict, prompt: str) -> set[str]:
    text = [prompt]
    text.extend(str(row.get("speaker") or "") for row in task.get("dialogue") or [])
    text.extend(str(row.get("speaker") or "") for row in task.get("dialogue_audio_assets") or [])
    spec = task.get("performance_spec") or {}
    for beat in spec.get("motion_beats") or []:
        text.extend(str(beat.get(key) or "") for key in ("subject", "action", "end_state", "expression"))
    combined = "\n".join(text)
    named = {
        entity_id
        for entity_id, (name, _) in ENTITY_ALIASES.items()
        if name in combined
    }
    # A dialogue may name an off-screen person, route, or faction without that
    # character appearing in the generated frame. The task must declare those
    # mentions explicitly so they cannot silently suppress a real cast member.
    nonvisual_mentions = {str(value) for value in task.get("nonvisual_entity_mentions") or []}
    spoken_entities = {
        entity_id
        for entity_id, (name, _) in ENTITY_ALIASES.items()
        if any(name == str(row.get("speaker") or "") for row in task.get("dialogue") or [])
    }
    # New pipeline tasks carry an explicit visual cast derived from the locked
    # per-unit performance plan.  Treat it as the visual authority while still
    # forcing every speaker to be bound.  This prevents dialogue, negative
    # constraints, or documentary references to an off-screen character from
    # being mistaken for an on-screen face.
    if "visual_entity_ids" in task:
        visual_entities = {str(value) for value in task.get("visual_entity_ids") or []}
        return named & (visual_entities | spoken_entities)
    motion_text = "\n".join(
        str(beat.get(key) or "")
        for beat in (task.get("performance_spec") or {}).get("motion_beats") or []
        for key in ("subject", "action", "end_state", "expression")
    )
    visibly_authored = {
        entity_id
        for entity_id, (name, _) in ENTITY_ALIASES.items()
        if name in motion_text
    }
    return named - (nonvisual_mentions - spoken_entities - visibly_authored)


def _visual_path(binding: dict) -> str:
    value = binding.get("visual_reference") or binding.get("canonical_visual_reference") or ""
    if isinstance(value, dict):
        return str(value.get("path") or value.get("local_reference") or "")
    return str(value)


def _identity_slots(task: dict) -> dict[str, dict]:
    slots: dict[str, dict] = {}
    for row in task.get("reference_image_sequence") or []:
        role = str(row.get("role") or "").upper()
        if (
            "IDENTITY_REFERENCE" in role
            or "CHARACTER_REFERENCE" in role
            or row.get("identity_reference") is True
        ):
            slots[str(row.get("asset_label") or row.get("slot_id") or "")] = row
    return slots


def _identity_video_slots(task: dict) -> dict[str, dict]:
    slots: dict[str, dict] = {}
    for row in task.get("reference_identity_video_sequence") or []:
        role = str(row.get("role") or "").upper()
        if "IDENTITY_REFERENCE" in role or row.get("identity_reference") is True:
            slots[str(row.get("asset_label") or row.get("slot_id") or "")] = row
    return slots


def _verified_identity_video(row: dict, canonical_path: str, all_reference_videos: set[Path]) -> bool:
    transform = str(row.get("transport_transform") or "")
    source_path = str(row.get("transport_derivative_of") or "")
    video_path = str(row.get("path") or "")
    if transform not in {
        "IMAGE_TO_VIDEO_IDENTITY_HOLD_2S_720X1280",
        "IMAGE_SEQUENCE_TO_VIDEO_IDENTITY_REEL_2S_PER_IMAGE_720X1280",
    } or not source_path or not video_path:
        return False
    if transform == "IMAGE_SEQUENCE_TO_VIDEO_IDENTITY_REEL_2S_PER_IMAGE_720X1280":
        start = row.get("segment_start_seconds")
        end = row.get("segment_end_seconds")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end <= start:
            return False
    canonical = _absolute(canonical_path).resolve()
    video = _absolute(video_path).resolve()
    return (
        _absolute(source_path).resolve() == canonical
        and str(row.get("transport_derivative_source_sha256") or "") == (_sha(canonical) or "")
        and video in all_reference_videos
        and _sha(video) == row.get("sha256")
    )


def _verified_transport_derivative(row: dict, canonical_path: str, all_reference_images: set[Path]) -> bool:
    """Allow a byte-transport derivative without changing identity authority."""
    derivative_of = str(row.get("transport_derivative_of") or "")
    derivative_path = str(row.get("path") or "")
    transform = str(row.get("transport_transform") or "")
    source_sha = str(row.get("transport_derivative_source_sha256") or "")
    if transform not in {
        "JPEG_Q92_S444_NO_RESIZE_UPSCALE",
        "JPEG_Q92_S444_MAX_1440X2560",
        "PNG_RGB_1440X2560_BLURRED_PAD_UPSCALE",
    }:
        return False
    if not derivative_of or not derivative_path:
        return False
    canonical = _absolute(canonical_path).resolve()
    derivative = _absolute(derivative_path).resolve()
    return (
        _absolute(derivative_of).resolve() == canonical
        and source_sha == (_sha(canonical) or "")
        and derivative in all_reference_images
        and _sha(derivative) == row.get("sha256")
    )


def evaluate_task(task: dict) -> dict:
    if task.get("tool_type") != "video_generation":
        return {"task_key": task.get("task_key"), "status": "NOT_APPLICABLE", "failures": []}

    prompt = _prompt(task)
    named = _named_entities(task, prompt)
    bindings = list(task.get("multimodal_entity_bindings") or [])
    by_id = {str(row.get("entity_id") or ""): row for row in bindings if row.get("entity_id")}
    # Character-free units do not need tenant character or voice registries.
    # Loading project authority unconditionally made portable installs fail on
    # generic environment, establishing, prop, and transport-only tasks.
    needs_character_authority = bool(named or bindings)
    voice_authority = _voice_authority() if needs_character_authority else {}
    voice_policy = _agentcut_voice_policy() if needs_character_authority else {}
    character_authority = _character_authority() if needs_character_authority else {}
    failures: list[dict[str, Any]] = []

    if POSE_FIRST_PATTERN.search(prompt):
        failures.append({
            "code": "POSE_FIRST_ACTION_DIRECTIVE",
            "message": "Performance generation must start in continuous motion, not from a staged pose.",
        })
    if SLOW_MOTION_PATTERN.search(_positive_motion_directives(prompt)) and not str(task.get("slow_motion_story_justification") or "").strip():
        failures.append({
            "code": "UNMOTIVATED_SLOW_MOTION_DIRECTIVE",
            "message": "Slow motion requires an explicit story-purpose justification; it may not fill runtime.",
        })

    detected_effects = sorted(term for term in EFFECT_TERMS if term in prompt)
    provenance_rows = list(task.get("effect_provenance") or [])
    for effect in detected_effects:
        provenance = next((row for row in provenance_rows if effect in str(row.get("effect") or "")), None)
        if not provenance:
            failures.append({
                "code": "UNSOURCED_VISUAL_EFFECT",
                "effect": effect,
                "message": "Every generated effect must trace to the Claude script or a canonical character ability.",
            })
            continue
        source_type = str(provenance.get("source_type") or "")
        if source_type not in ALLOWED_EFFECT_SOURCES or not str(provenance.get("source_ref") or "").strip():
            failures.append({
                "code": "INVALID_VISUAL_EFFECT_PROVENANCE",
                "effect": effect,
                "source_type": source_type or "MISSING",
            })

    if not bindings and task.get("character_free_unit") is not True:
        failures.append({
            "code": "MISSING_MULTIMODAL_ENTITY_BINDINGS",
            "entities": sorted(named),
            "message": "Every named recurring character must bind its canonical face, submitted image slot, voice, dialogue, props, and abilities before video submission.",
        })
    if task.get("character_free_unit") is True and named:
        failures.append({
            "code": "CHARACTER_FREE_UNIT_CONTAINS_REGISTERED_CHARACTER",
            "entities": sorted(named),
        })
    expected_digest = binding_digest(bindings)
    if bindings and task.get("multimodal_binding_sha256") != expected_digest:
        failures.append({
            "code": "ENTITY_BINDING_DIGEST_MISMATCH",
            "expected": expected_digest,
            "actual": task.get("multimodal_binding_sha256") or "MISSING",
        })

    identity_slots = _identity_slots(task)
    identity_video_slots = _identity_video_slots(task)
    all_reference_images = {_absolute(value).resolve() for value in task.get("reference_images") or []}
    all_reference_videos = {_absolute(value).resolve() for value in task.get("reference_videos") or []}
    for entity_id in sorted(set(by_id) - set(ENTITY_ALIASES)):
        failures.append({
            "code": "UNREGISTERED_ENTITY_BINDING",
            "entity_id": entity_id,
            "message": "Register the character face and voice authority before generation.",
        })
    for entity_id in sorted(named):
        name, registry_id = ENTITY_ALIASES[entity_id]
        for phrase in FORBIDDEN_APPEARANCE_PHRASES.get(entity_id, ()):
            if phrase in prompt:
                failures.append({
                    "code": "PROMPT_ROLE_APPEARANCE_CONTRADICTION",
                    "entity_id": entity_id,
                    "forbidden_phrase": phrase,
                })
        binding = by_id.get(entity_id)
        if not binding:
            failures.append({"code": "MISSING_ENTITY_BINDING", "entity_id": entity_id, "character": name})
            continue
        if binding.get("character_name") != name or binding.get("registry_id") != registry_id:
            failures.append({
                "code": "ENTITY_REGISTRY_ID_MISMATCH",
                "entity_id": entity_id,
                "expected_name": name,
                "expected_registry_id": registry_id,
            })

        canonical = character_authority.get(entity_id) or {}
        canonical_path = str(
            canonical.get("generation_reference_image")
            or canonical.get("identity_reference_image")
            or canonical.get("reference_image")
            or ""
        )
        supplied_path = _visual_path(binding)
        if not canonical_path or not supplied_path or _absolute(supplied_path).resolve() != _absolute(canonical_path).resolve():
            failures.append({
                "code": "CANONICAL_VISUAL_REFERENCE_MISMATCH",
                "entity_id": entity_id,
                "expected": canonical_path or "MISSING_IN_REGISTRY",
                "actual": supplied_path or "MISSING",
            })
        else:
            expected_visual_sha = _sha(_absolute(canonical_path))
            if expected_visual_sha and binding.get("visual_reference_sha256") != expected_visual_sha:
                failures.append({
                    "code": "CANONICAL_VISUAL_SHA_MISMATCH",
                    "entity_id": entity_id,
                    "expected": expected_visual_sha,
                    "actual": binding.get("visual_reference_sha256") or "MISSING",
                })
            image_slot = str(binding.get("identity_image_slot") or "")
            video_slot = str(binding.get("identity_video_slot") or "")
            image_slot_valid = False
            video_slot_valid = False
            if image_slot and image_slot in identity_slots:
                slot_row = identity_slots[image_slot]
                slot_path = str(slot_row.get("path") or "")
                image_slot_valid = (
                    _absolute(slot_path).resolve() == _absolute(canonical_path).resolve()
                    or _verified_transport_derivative(slot_row, canonical_path, all_reference_images)
                )
            if video_slot and video_slot in identity_video_slots:
                video_slot_valid = _verified_identity_video(
                    identity_video_slots[video_slot], canonical_path, all_reference_videos
                )
            if image_slot and not image_slot_valid:
                failures.append({"code": "IDENTITY_IMAGE_SLOT_PATH_MISMATCH", "entity_id": entity_id, "slot": image_slot})
            if video_slot and not video_slot_valid:
                failures.append({"code": "IDENTITY_VIDEO_SLOT_PATH_MISMATCH", "entity_id": entity_id, "slot": video_slot})
            if not image_slot_valid and not video_slot_valid:
                failures.append({
                    "code": "IDENTITY_VISUAL_SLOT_NOT_VERIFIED",
                    "entity_id": entity_id,
                    "image_slot": image_slot or "MISSING",
                    "video_slot": video_slot or "MISSING",
                })
            canonical_forwarded = _absolute(canonical_path).resolve() in all_reference_images
            derivative_forwarded = any(
                _verified_transport_derivative(row, canonical_path, all_reference_images)
                for row in identity_slots.values()
            )
            video_forwarded = any(
                _verified_identity_video(row, canonical_path, all_reference_videos)
                for row in identity_video_slots.values()
            )
            if not canonical_forwarded and not derivative_forwarded and not video_forwarded:
                failures.append({"code": "CANONICAL_VISUAL_NOT_FORWARDED_TO_MODEL", "entity_id": entity_id})

    dialogue_assets = {str(row.get("dia_id") or ""): row for row in task.get("dialogue_audio_assets") or []}
    for line in task.get("dialogue") or []:
        spoken_text = str(line.get("spoken_text") or line.get("text") or "")
        spoken_length = _dialogue_length(spoken_text)
        if spoken_length > DIALOGUE_CHARACTER_LIMIT:
            failures.append({
                "code": "DIALOGUE_LINE_TOO_LONG",
                "dia_id": str(line.get("dia_id") or ""),
                "length": spoken_length,
                "limit": DIALOGUE_CHARACTER_LIMIT,
            })
        speaker_name = str(line.get("speaker") or "")
        entity_id = next((key for key, (name, _) in ENTITY_ALIASES.items() if name == speaker_name), None)
        if not entity_id:
            failures.append({"code": "UNREGISTERED_SPEAKER", "speaker": speaker_name or "MISSING"})
            continue
        binding = by_id.get(entity_id)
        if not binding:
            continue
        if binding.get("visible_speaker") is not True or binding.get("lip_sync") is not True:
            failures.append({"code": "VISIBLE_SPEAKER_LIPSYNC_NOT_BOUND", "entity_id": entity_id})
        dia_id = str(line.get("dia_id") or "")
        audio = dialogue_assets.get(dia_id)
        slot = str((audio or {}).get("audio_slot") or "")
        rights_cleared_native = (
            binding.get("voice_policy") == "RIGHTS_CLEARED_MODEL_NATIVE_NO_EXTERNAL_REFERENCE"
            and entity_id == "jiaotu"
            and not audio
            and not binding.get("voice_reference")
            and not binding.get("voice_reference_asset_id")
            and not binding.get("dialogue_audio_slots")
        )
        if rights_cleared_native:
            continue
        human_exception_native = (
            binding.get("voice_policy") == "MODEL_NATIVE_TEXT_ONLY_HUMAN_LISTENING_EXCEPTION_NO_EXTERNAL_REFERENCE"
            and dia_id in set(task.get("model_native_text_only_dialogue_ids") or [])
            and not audio
            and not binding.get("voice_reference")
            and not binding.get("voice_reference_asset_id")
            and not binding.get("dialogue_audio_slots")
        )
        if human_exception_native:
            continue
        if not audio or slot not in set(binding.get("dialogue_audio_slots") or []):
            failures.append({"code": "DIALOGUE_AUDIO_SLOT_NOT_BOUND_TO_SPEAKER", "entity_id": entity_id, "dia_id": dia_id, "slot": slot or "MISSING"})
            continue

        authority = voice_authority.get(entity_id) or {}
        authority_status = str(authority.get("status") or "")
        canonical_voice_id = authority.get("remote_asset_id")
        if not canonical_voice_id or authority_status not in {
            "LOCKED_PRODUCTION_READY",
            "AGENTCUT_GENERATED_REGISTERED_PRODUCTION_READY",
        }:
            failures.append({
                "code": "SPEAKER_CANONICAL_VOICE_NOT_PRODUCTION_READY",
                "entity_id": entity_id,
                "status": authority_status or "MISSING",
                "message": "Register a canonical reference voice before new speaking generation; episode-local TTS is forbidden.",
            })
            continue
        if entity_id not in AGENTCUT_VOICE_EXEMPTIONS and (
            authority.get("source_generator") != "AGENTCUT_SPEECH_GENERATION"
            or authority.get("agentcut_capability") != "AGENTCUT-SPEECH-001"
            or not authority.get("generation_task_id")
            or not authority.get("registration_receipt")
            or not authority.get("qa_receipt")
        ):
            failures.append({
                "code": "NONEXEMPT_CANONICAL_VOICE_NOT_AGENTCUT_GENERATED",
                "entity_id": entity_id,
                "message": "Only Chenji and BaiLi may retain legacy native voices; every other character requires an AgentCut speech generation, QA, and registration receipt.",
            })
            continue
        if entity_id not in AGENTCUT_VOICE_EXEMPTIONS:
            role_spec = voice_policy.get(entity_id) or {}
            expected_brief = _performance_brief_sha256(role_spec) if role_spec else None
            if (
                not role_spec
                or authority.get("generation_voice_id") != role_spec.get("voice_id")
                or authority.get("generation_voice_name") != role_spec.get("voice_name")
                or authority.get("performance_brief_sha256") != expected_brief
            ):
                failures.append({
                    "code": "ROLE_SPECIFIC_AGENTCUT_VOICE_POLICY_MISMATCH",
                    "entity_id": entity_id,
                    "message": "The AgentCut voice preset and role-performance brief must match the current story-derived character policy before video submission.",
                })
                continue
        if binding.get("voice_reference_asset_id") != canonical_voice_id:
            failures.append({
                "code": "CANONICAL_VOICE_BINDING_MISMATCH",
                "entity_id": entity_id,
                "expected": canonical_voice_id,
                "actual": binding.get("voice_reference_asset_id") or "MISSING",
            })
        if audio.get("voice_reference_asset_id") != canonical_voice_id or audio.get("voice_derivation_status") != "PASS":
            failures.append({
                "code": "DIALOGUE_AUDIO_CANONICAL_VOICE_PROVENANCE_MISSING",
                "entity_id": entity_id,
                "dia_id": dia_id,
                "expected_voice_asset_id": canonical_voice_id,
            })
        forbidden = authority.get("forbidden_replacements") or []
        source_voice = str(audio.get("source_voice") or audio.get("voice") or "")
        if any(value and value in source_voice for value in forbidden):
            failures.append({"code": "FORBIDDEN_EPISODE_LOCAL_VOICE", "entity_id": entity_id, "source_voice": source_voice})
        if GENERIC_TTS_PATTERN.search(source_voice):
            failures.append({
                "code": "GENERIC_TTS_REFERENCE_FORBIDDEN",
                "entity_id": entity_id,
                "dia_id": dia_id,
                "source_voice": source_voice,
            })
        expected_gender = str(authority.get("gender") or "").lower()
        actual_gender = str(audio.get("voice_gender") or "").lower()
        if expected_gender in {"male", "female"} and actual_gender != expected_gender:
            failures.append({
                "code": "SPEAKER_VOICE_GENDER_MISMATCH",
                "entity_id": entity_id,
                "dia_id": dia_id,
                "expected": expected_gender,
                "actual": actual_gender or "MISSING",
            })

    if len(named) > 1:
        for entity_id in sorted(named):
            binding = by_id.get(entity_id) or {}
            for field in ("prop_owners", "ability_owners"):
                if field not in binding:
                    failures.append({"code": "MULTI_CHARACTER_OWNERSHIP_BINDING_MISSING", "entity_id": entity_id, "field": field})

    return {
        "task_key": task.get("task_key"),
        "unit_id": task.get("unit_id"),
        "status": "PASS" if not failures else "FAIL",
        "named_entities": sorted(named),
        "binding_digest": expected_digest if bindings else None,
        "failures": failures,
    }


def evaluate_batch(config: dict) -> dict:
    results = [evaluate_task(task) for task in config.get("tasks") or [] if task.get("tool_type") == "video_generation"]
    blocked = [row.get("task_key") for row in results if row.get("status") == "FAIL"]
    return {
        "schema": "qingshan.multimodal_character_binding_gate.v1",
        "episode": config.get("episode"),
        "status": "PASS" if not blocked else "FAIL",
        "blocked_tasks": blocked,
        "results": results,
        "policy": "Face, wardrobe, dialogue, props, and abilities must bind to one named entity. Voice uses canonical evidence or an explicit rights-cleared JiaoTu model-native policy with no external reference or clone.",
        "rollback": "Repair only blocked task bindings and prompt; do not resubmit unchanged successful candidates.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out")
    args = parser.parse_args()
    report = evaluate_batch(_load(_absolute(args.config)))
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = _absolute(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
