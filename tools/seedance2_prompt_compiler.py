#!/usr/bin/env python3
"""Compile the two approved Seedance 2.0 prompt modes from structured JSON."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

try:
    from .local_lora_memory_sync import auto_sync
    from .human_realism_prompt_contract import build_expression_realism_block
except ImportError:  # Direct script execution from components/pipeline-tools.
    from local_lora_memory_sync import auto_sync
    from human_realism_prompt_contract import build_expression_realism_block


MODES = {"storyboard", "continuous_long_take", "multi_keyframe_long_take"}
DIALOGUE_MODES = {"ON_CAMERA_NATIVE_LIP_SYNC", "CLOSED_MOUTH_VOICE_OVER", "NO_DIALOGUE"}


def default_local_lora_memory() -> Path:
    """Resolve one portable compiler source to its actual deployed memory."""
    explicit = os.environ.get("BACKLOTOS_LOCAL_LORA_MEMORY", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    module = Path(__file__).resolve()
    production_memory = module.parents[1] / "workflow/local_lora/seedance2_prompt_failure_training.jsonl"
    if production_memory.parent.is_dir():
        return production_memory
    return module.parent / "local_lora/seedance2_prompt_failure_training.jsonl"


DEFAULT_LOCAL_LORA_MEMORY = default_local_lora_memory()
STATIC_ACTOR_MOTION_TERMS = (
    "静止", "完全不动", "纹丝不动", "定格", "保持姿势", "保持原位",
    "仍在原区", "尚未启动", "留在安全区", "留在后方", "frozen", "freeze", "motionless",
)
VISUAL_FIELDS = (
    "duration_seconds", "shot_scale", "lens_intent", "camera_height", "camera_motion",
    "depth_layers", "scale_anchor", "palette", "key_light", "atmosphere",
    "environmental_motion", "material_detail", "still_prompt_contract",
    "video_motion_contract", "negative_constraints",
)
SILENT_PERFORMANCE_MARKERS = (
    "全程不开口", "全程闭口", "无人开口", "不生成语音", "无口型台词",
    "独立音频后置", "后配音", "closed-mouth", "no lip sync", "silent performance",
)

CHARACTER_SIMILARITY_LIMITS = {"face": 0.72, "wardrobe": 0.65, "voice": 0.80}
EXPRESSIVE_DIALOGUE_FIELDS = (
    "psychological_state", "emotion", "emotion_intensity", "pace", "pause_map",
    "emphasis_words", "volume_arc", "breath_pattern", "delivery_transition", "body_sync",
)

# Action-camera vocabulary is selected by dramatic function, never sampled as
# decorative motion. Short accents stay short so the action remains readable.
ACTION_CAMERA_TECHNIQUES = {
    "tracking_follow": ("空间跟随", "持续位移、追逐或绕障", "moving", 3.0),
    "arc_orientation": ("弧线定向", "交代双方站位与空间关系", "moving", 2.0),
    "crash_push": ("急速推进", "唯一一次逼近决定性接触", "accent", 0.8),
    "crash_pull": ("急速拉开", "接触后揭示受力结果与环境", "accent", 0.8),
    "low_angle_dolly": ("低机位移动", "强调步法、腾跃起点或压迫感", "moving", 2.0),
    "overhead_crane": ("高位俯拍", "交代多人包围、路线或地形", "moving", 2.0),
    "micro_slow_follow": ("短促慢速强调", "仅强调唯一决定性接触", "accent", 0.6),
    "impact_shake": ("冲击震动", "仅在真实接触瞬间表现冲量", "accent", 0.35),
    "whip_pan_cut": ("甩镜切换", "动作方向匹配的镜间交接", "edit", 0.4),
    "detail_triple_cut": ("三段特写", "起势、接触、结果三个信息点", "edit", 2.4),
    "crane_rise": ("升降揭示", "从局部结果升起交代全局", "moving", 2.0),
    "obstacle_pass": ("穿绕遮挡", "沿真实门柱、人群或障碍维持空间连续", "moving", 2.5),
    "shot_reverse_exchange": ("正反交替", "明确攻守交换与视线轴", "edit", 2.5),
    "bounded_rotation": ("有限旋转", "围绕固定接触点读取一次攻防转换", "moving", 1.5),
    "locked_impact": ("定格机位", "让动作和受力在稳定构图内自行发生", "stable", 3.0),
}
ACTION_CAMERA_EDIT_ONLY = {"whip_pan_cut", "detail_triple_cut", "shot_reverse_exchange"}
ACTION_CAMERA_DYNAMIC_FAMILIES = {"moving", "accent"}


def compile_cinematic_shot_language_contract(spec: dict, shot_count: int) -> tuple[str, dict | None]:
    """Compile a descriptor-first, time-coded shot prompt without mixing concerns."""
    contract = spec.get("cinematic_shot_language_contract")
    if not contract:
        return "", None
    if require(contract.get("version"), "cinematic shot language version is required") != "1.0.0":
        raise ValueError("unsupported cinematic shot language contract version")
    descriptors = require(contract.get("locked_descriptors"), "locked_descriptors are required")
    if not isinstance(descriptors, list) or not descriptors:
        raise ValueError("locked_descriptors must be a non-empty list")
    descriptor_rows, descriptor_ids = [], set()
    for index, row in enumerate(descriptors, start=1):
        descriptor_id = require(row.get("id"), f"descriptor {index} id is required")
        if descriptor_id in descriptor_ids:
            raise ValueError(f"duplicate locked descriptor: {descriptor_id}")
        descriptor_ids.add(descriptor_id)
        kind = require(row.get("kind"), f"descriptor {descriptor_id} kind is required")
        if kind not in {"character", "character_state", "location", "location_state", "prop", "prop_state"}:
            raise ValueError(f"unsupported descriptor kind: {kind}")
        descriptor_text = require(row.get("text"), f"descriptor {descriptor_id} text is required")
        digest = require(row.get("text_sha256"), f"descriptor {descriptor_id} text_sha256 is required")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower()):
            raise ValueError(f"descriptor {descriptor_id} text_sha256 must be lowercase SHA-256")
        if hashlib.sha256(descriptor_text.encode("utf-8")).hexdigest() != digest:
            raise ValueError(f"descriptor {descriptor_id} text does not match text_sha256")
        if row.get("paste_policy") != "VERBATIM_EVERY_SHOT":
            raise ValueError(f"descriptor {descriptor_id} must use VERBATIM_EVERY_SHOT")
        if row.get("stress_test_status") != "PASS":
            raise ValueError(f"descriptor {descriptor_id} must pass its stress test")
        descriptor_rows.append(f"{descriptor_id}({kind},sha256={digest})：{descriptor_text}")

    segments = require(contract.get("segments"), "cinematic shot language segments are required")
    if not isinstance(segments, list) or len(segments) != shot_count:
        raise ValueError("cinematic shot language segments must exactly cover compiled shots")
    duration = float(require(spec.get("duration_seconds"), "duration_seconds is required"))
    cursor, compiled = 0.0, []
    for index, row in enumerate(segments, start=1):
        start = float(require(row.get("start_seconds"), f"segment {index} start_seconds is required"))
        end = float(require(row.get("end_seconds"), f"segment {index} end_seconds is required"))
        if abs(start - cursor) > 0.01 or end <= start or end > duration + 0.01:
            raise ValueError(f"segment {index} must be contiguous and inside duration_seconds")
        if int(require(row.get("shot_index"), f"segment {index} shot_index is required")) != index:
            raise ValueError("cinematic segment shot_index must match compiled shot order")
        geometry = require(row.get("geometry"), f"segment {index} geometry is required")
        geometry_fields = ("subject_anchor", "camera_side", "axis_relation", "scale_anchor")
        for field in geometry_fields:
            require(geometry.get(field), f"segment {index} geometry.{field} is required")
        refs = require(row.get("descriptor_ids"), f"segment {index} descriptor_ids are required")
        if not isinstance(refs, list) or not refs or not set(refs).issubset(descriptor_ids):
            raise ValueError(f"segment {index} references unknown or empty descriptors")
        audio = require(row.get("audio"), f"segment {index} audio is required")
        require(audio.get("diegetic"), f"segment {index} diegetic audio is required")
        dialogue_policy = require(audio.get("dialogue_policy"), f"segment {index} dialogue_policy is required")
        if dialogue_policy not in {"EXACT_QUOTED_LINES_ONLY", "NO_DIALOGUE", "CLOSED_MOUTH_VOICE_OVER"}:
            raise ValueError(f"segment {index} has unsupported dialogue_policy")
        compiled.append({
            "start_seconds": start, "end_seconds": end, "shot_index": index,
            "narrative_purpose": require(row.get("narrative_purpose"), f"segment {index} narrative_purpose is required"),
            "entry_state": require(row.get("entry_state"), f"segment {index} entry_state is required"),
            "exit_state": require(row.get("exit_state"), f"segment {index} exit_state is required"),
            "camera_motivation": require(row.get("camera_motivation"), f"segment {index} camera_motivation is required"),
            "geometry": {field: geometry[field] for field in geometry_fields},
            "descriptor_ids": refs, "audio": audio,
        })
        cursor = end
    if abs(cursor - duration) > 0.01:
        raise ValueError("cinematic shot language segments must cover the full duration")
    rules = require(contract.get("key_rules"), "cinematic shot language key_rules are required")
    if not isinstance(rules, list) or not rules:
        raise ValueError("cinematic shot language key_rules must be a non-empty list")
    atmosphere = require(contract.get("atmosphere_state"), "atmosphere_state is required")
    style = require(contract.get("style_prefix"), "style_prefix is required")
    negatives = require(contract.get("negative_constraints"), "cinematic negative_constraints are required")
    if not isinstance(negatives, list) or not negatives:
        raise ValueError("cinematic negative_constraints must be a non-empty list")
    segment_rows = [
        f"{row['start_seconds']:g}-{row['end_seconds']:g}秒 / 镜头{row['shot_index']}：目的={row['narrative_purpose']}；"
        f"入口={row['entry_state']}；出口={row['exit_state']}；引用={','.join(row['descriptor_ids'])}；"
        f"几何=主体{row['geometry']['subject_anchor']}、机位侧{row['geometry']['camera_side']}、"
        f"轴线{row['geometry']['axis_relation']}、尺度{row['geometry']['scale_anchor']}；"
        f"镜头运动只为{row['camera_motivation']}；现场声={row['audio']['diegetic']}；对白策略={row['audio']['dialogue_policy']}"
        for row in compiled
    ]
    prompt = (
        "\n\n【LOCKED DESCRIPTORS｜逐镜原文复用】" + "；".join(descriptor_rows)
        + "。\n【SCENE PURPOSE / GEOMETRY / TIME-CODED CUTS】\n" + "\n".join(segment_rows)
        + "\n【KEY RULES】" + "；".join(rules)
        + f"。\n【ATMOSPHERE STATE】{atmosphere}。\n【STYLE PREFIX】{style}。"
        + "\n【NEGATIVE CONSTRAINTS】" + " / ".join(negatives) + "。"
        + "\n提示词各区块职责不可互相污染：动作不得夹带台词，风格不得改写角色/场景描述，负面词不得代替正向可见物理事件。"
    )
    return prompt, {
        "version": "1.0.0", "descriptor_count": len(descriptors), "segments": compiled,
        "full_duration_coverage": True, "descriptor_policy": "VERBATIM_EVERY_SHOT",
        "section_order": ["LOCKED_DESCRIPTORS", "PURPOSE_GEOMETRY_TIME_CUTS", "KEY_RULES", "AUDIO", "ATMOSPHERE", "STYLE", "NEGATIVES"],
        "source_method": "HELL_GRIND_LICENSED_PRODUCTION_METHODOLOGY",
    }


def compile_combat_camera_language(
    contract: dict, beats: list[dict], duration: float, actual_mode: str
) -> tuple[str, dict]:
    """Compile motivated action-camera choices without recreating perpetual sway."""
    plan = require(contract.get("camera_language_plan"), "combat camera_language_plan is required")
    mode = require(plan.get("generation_mode"), "combat camera_language_plan.generation_mode is required")
    if mode not in MODES:
        raise ValueError(f"unsupported combat camera generation_mode: {mode}")
    if mode != actual_mode:
        raise ValueError("combat camera generation_mode must match the generation spec mode")
    segments = require(plan.get("segments"), "combat camera_language_plan.segments are required")
    if not isinstance(segments, list) or not 1 <= len(segments) <= 5:
        raise ValueError("combat camera language requires 1 to 5 motivated segments")

    compiled, moving = [], []
    prior_end = 0.0
    for index, row in enumerate(segments, start=1):
        technique = require(row.get("technique_id"), f"combat camera segment {index} technique_id is required")
        if technique not in ACTION_CAMERA_TECHNIQUES:
            raise ValueError(f"unsupported combat camera technique: {technique}")
        label, use_case, family, max_seconds = ACTION_CAMERA_TECHNIQUES[technique]
        start = float(require(row.get("start_seconds"), f"combat camera segment {index} start_seconds is required"))
        end = float(require(row.get("end_seconds"), f"combat camera segment {index} end_seconds is required"))
        if start < prior_end or end <= start or end > duration + 0.01:
            raise ValueError(f"combat camera segment {index} has invalid or overlapping time range")
        if end - start > max_seconds + 0.01:
            raise ValueError(f"combat camera technique {technique} exceeds {max_seconds:g}s limit")
        if technique in ACTION_CAMERA_EDIT_ONLY and mode != "storyboard":
            raise ValueError(f"combat camera technique {technique} requires storyboard mode")
        if technique == "micro_slow_follow" and row.get("contact_is_decisive") is not True:
            raise ValueError("micro_slow_follow requires contact_is_decisive=true")
        beat_index = int(require(row.get("action_beat_index"), f"combat camera segment {index} action_beat_index is required"))
        if not 1 <= beat_index <= len(beats):
            raise ValueError(f"combat camera segment {index} action_beat_index is out of range")
        motivation = require(row.get("narrative_motivation"), f"combat camera segment {index} narrative_motivation is required")
        anchor = require(row.get("subject_anchor"), f"combat camera segment {index} subject_anchor is required")
        axis = require(row.get("axis_relation"), f"combat camera segment {index} axis_relation is required")
        if family in ACTION_CAMERA_DYNAMIC_FAMILIES:
            moving.append((start, end, family, technique))
        compiled.append({
            "technique_id": technique, "label": label, "family": family,
            "start_seconds": start, "end_seconds": end, "action_beat_index": beat_index,
            "narrative_motivation": motivation, "subject_anchor": anchor,
            "axis_relation": axis, "allowed_use": use_case,
        })
        prior_end = end

    is_long_take = mode in {"continuous_long_take", "multi_keyframe_long_take"}
    if is_long_take and len(moving) > 2:
        raise ValueError("combat long take permits at most two dynamic camera techniques")
    for previous, current in zip(compiled, compiled[1:]):
        if previous["technique_id"] == current["technique_id"]:
            raise ValueError("adjacent combat camera segments cannot repeat one technique")
    for previous, current in zip(moving, moving[1:]):
        if is_long_take and current[0] - previous[1] < 1.0:
            raise ValueError("dynamic combat camera techniques require at least 1 second of stable observation between them")
        if is_long_take and previous[2] == current[2]:
            raise ValueError("adjacent dynamic combat camera techniques cannot repeat one motion family")

    rows = [
        f"{row['start_seconds']:g}-{row['end_seconds']:g}秒用{row['label']}，只为{row['narrative_motivation']}；"
        f"绑定动作拍{row['action_beat_index']}，主体锚点{row['subject_anchor']}，轴线{row['axis_relation']}"
        for row in compiled
    ]
    prompt = (
        "\n【动作镜头语言配方】" + "；".join(rows) + "。未声明时段一律稳定机位。"
        "运镜必须服务动作因果和空间读取，不得把跟拍、环绕、推拉、升降、旋转或震动当作持续装饰；"
        "禁止连续摇摆、smooth roam、无动机slow push、重复环绕、用镜头运动掩盖动作缺失。"
    )
    return prompt, {
        "version": "1.0.0", "generation_mode": mode, "segments": compiled,
        "dynamic_segment_count": len(moving),
        "stable_observation_between_dynamic_seconds": 1.0 if is_long_take else 0.0,
        "unplanned_time_policy": "LOCKED_CAMERA", "selection_gate": "PASS_MOTIVATED_ONLY",
    }


def _verified_asset(asset: dict, label: str) -> tuple[Path, str]:
    path = Path(require(asset.get("path"), f"{label} path is required"))
    expected_sha = require(asset.get("sha256"), f"{label} sha256 is required")
    if not path.is_file():
        raise ValueError(f"{label} does not exist: {path}")
    actual_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError(f"{label} SHA mismatch")
    return path, actual_sha


def compile_episode_character_registry(spec: dict, actor_roster: list[str]) -> tuple[str, dict]:
    """Freeze source-grounded, unique character assets before video compilation."""
    registry = require(spec.get("episode_character_registry"), "episode_character_registry is required before video generation")
    if registry.get("frozen_before_video_generation") is not True:
        raise ValueError("episode character registry must be frozen before video generation")
    library_path, library_sha = _verified_asset(
        require(registry.get("historical_library_manifest"), "historical_library_manifest is required"),
        "historical character library manifest",
    )
    rows = require(registry.get("characters"), "episode character registry characters are required")
    if not isinstance(rows, list):
        raise ValueError("episode character registry characters must be a list")
    by_actor = {str(row.get("actor", "")).strip(): row for row in rows}
    if set(by_actor) != set(actor_roster) or len(by_actor) != len(rows):
        raise ValueError("episode character registry must exactly cover actor_roster without duplicates")

    compiled, visual_shas, voice_shas = [], set(), set()
    for actor in actor_roster:
        row = by_actor[actor]
        source = require(row.get("canonical_character_brief"), f"character {actor} canonical_character_brief is required")
        for field in ("source_locator", "era", "age", "social_role", "wardrobe", "face", "hair", "voice"):
            require(source.get(field), f"character {actor} canonical brief {field} is required")
        if source.get("writer_completed_before_asset_generation") is not True:
            raise ValueError(f"character {actor} brief must be completed by the writer before asset generation")
        visual_path, visual_sha = _verified_asset(
            require(row.get("visual_reference"), f"character {actor} visual_reference is required"),
            f"character {actor} visual reference",
        )
        voice_path, voice_sha = _verified_asset(
            require(row.get("voice_reference"), f"character {actor} voice_reference is required"),
            f"character {actor} voice reference",
        )
        if visual_sha in visual_shas or voice_sha in voice_shas:
            raise ValueError("episode characters must use distinct visual and voice references")
        visual_shas.add(visual_sha)
        voice_shas.add(voice_sha)
        audit = require(row.get("historical_uniqueness_audit"), f"character {actor} historical_uniqueness_audit is required")
        if audit.get("status") != "PASS":
            raise ValueError(f"character {actor} historical uniqueness audit must PASS")
        exception = audit.get("narrative_similarity_exception")
        for dimension, limit in CHARACTER_SIMILARITY_LIMITS.items():
            score = float(require(audit.get(f"{dimension}_similarity"), f"character {actor} {dimension}_similarity is required"))
            if score > limit and not exception:
                raise ValueError(f"character {actor} is too similar to historical library in {dimension}")
        compiled.append(
            f"{actor}=原文定位{source['source_locator']}；年代{source['era']}；年龄{source['age']}；身份{source['social_role']}；"
            f"视觉参考{visual_path}；服装{source['wardrobe']}；脸型{source['face']}；发型{source['hair']}；声音{source['voice']}；"
            "镜头全程不得换装、换脸、换发型或借用其他角色声音"
        )

    pairs = registry.get("pairwise_uniqueness_audit")
    if not isinstance(pairs, list):
        raise ValueError("pairwise_uniqueness_audit must be a list")
    expected_pairs = {tuple(sorted((a, b))) for index, a in enumerate(actor_roster) for b in actor_roster[index + 1:]}
    actual_pairs = set()
    for row in pairs:
        pair = tuple(sorted((require(row.get("actor_a"), "pair actor_a is required"), require(row.get("actor_b"), "pair actor_b is required"))))
        actual_pairs.add(pair)
        for dimension, limit in CHARACTER_SIMILARITY_LIMITS.items():
            if float(require(row.get(f"{dimension}_similarity"), f"pair {pair} {dimension}_similarity is required")) > limit:
                raise ValueError(f"episode characters {pair} are too similar in {dimension}")
    if actual_pairs != expected_pairs or len(actual_pairs) != len(pairs):
        raise ValueError("pairwise_uniqueness_audit must cover every actor pair exactly once")

    prompt = "\n【本集角色资产冻结】" + "；".join(compiled) + "。禁止临时随机生成人物，禁止同一角色黑衣变灰衣。"
    return prompt, {
        "historical_library_manifest": {"path": str(library_path), "sha256": library_sha},
        "character_visual_shas": sorted(visual_shas),
        "character_voice_shas": sorted(voice_shas),
        "pairwise_audit_count": len(pairs),
        "frozen_before_video_generation": True,
    }


def compile_combat_choreography_contract(spec: dict, actor_roster: list[str]) -> tuple[str, dict | None]:
    """Compile combat as timed physical exchanges with identity and outcome locks."""
    contract = spec.get("combat_choreography_contract")
    if not contract:
        return "", None
    participants = require(contract.get("participants"), "combat participants are required")
    if not isinstance(participants, list) or len(participants) < 2:
        raise ValueError("combat requires at least two participants")
    names, reference_shas, participant_rows = [], set(), []
    for index, row in enumerate(participants, start=1):
        name = require(row.get("actor"), f"combat participant {index} actor is required")
        if name not in actor_roster:
            raise ValueError(f"combat participant is absent from actor_roster: {name}")
        names.append(name)
        require(row.get("role"), f"combat participant {name} role is required")
        reference = require(
            row.get("independent_identity_reference"),
            f"combat participant {name} requires independent_identity_reference",
        )
        reference_path = Path(require(reference.get("path"), f"combat participant {name} identity path is required"))
        reference_sha = require(reference.get("sha256"), f"combat participant {name} identity sha256 is required")
        if not reference_path.is_file():
            raise ValueError(f"combat participant {name} identity reference does not exist: {reference_path}")
        actual_sha = hashlib.sha256(reference_path.read_bytes()).hexdigest()
        if actual_sha != reference_sha:
            raise ValueError(f"combat participant {name} identity reference SHA mismatch")
        if actual_sha in reference_shas:
            raise ValueError("combat participants must use distinct identity references")
        reference_shas.add(actual_sha)
        wardrobe = require(row.get("wardrobe_silhouette"), f"combat participant {name} wardrobe_silhouette is required")
        face = require(row.get("face_geometry"), f"combat participant {name} face_geometry is required")
        first_second = require(row.get("first_second_displacement"), f"combat participant {name} first_second_displacement is required")
        participant_rows.append(
            f"{name}={row['role']}，身份参考{reference_path}，服装轮廓{wardrobe}，脸型{face}，开场1秒位移{first_second}"
        )
    if len(set(names)) != len(names):
        raise ValueError("combat participants contain duplicates")

    reference_video = require(contract.get("action_reference_video"), "combat action_reference_video is required")
    require(reference_video.get("url"), "combat action_reference_video.url is required")
    if reference_video.get("reference_scope") != "CHOREOGRAPHY_TIMING_AND_BODY_MECHANICS_ONLY":
        raise ValueError("combat action reference scope must exclude identity, wardrobe and outcome")

    beats = require(contract.get("beats"), "combat beats are required")
    if not isinstance(beats, list) or not 3 <= len(beats) <= 6:
        raise ValueError("combat requires 3 to 6 timed beats")
    cursor, signatures, beat_rows = 0.0, set(), []
    required_fields = (
        "initiator", "target", "action", "contact_point", "force_direction",
        "footwork", "target_reaction", "end_state",
    )
    for index, beat in enumerate(beats, start=1):
        start = float(require(beat.get("start_seconds"), f"combat beat {index} start_seconds is required"))
        end = float(require(beat.get("end_seconds"), f"combat beat {index} end_seconds is required"))
        if abs(start - cursor) > 0.01 or end <= start or end - start > 3.0:
            raise ValueError(f"combat beat {index} must be contiguous and no longer than 3 seconds")
        values = {field: require(beat.get(field), f"combat beat {index} {field} is required") for field in required_fields}
        if values["initiator"] not in names or values["target"] not in names:
            raise ValueError(f"combat beat {index} initiator and target must be participants")
        if values["initiator"] == values["target"]:
            raise ValueError(f"combat beat {index} initiator and target must differ")
        signature = (values["initiator"], values["target"], values["action"], values["contact_point"])
        if signature in signatures:
            raise ValueError(f"combat beat {index} repeats an earlier exchange")
        signatures.add(signature)
        beat_rows.append(
            f"{start:g}-{end:g}秒：{values['initiator']}以{values['footwork']}完成{values['action']}，"
            f"接触{values['target']}的{values['contact_point']}，力量朝{values['force_direction']}；"
            f"{values['target']}因受力{values['target_reaction']}；终态{values['end_state']}"
        )
        cursor = end
    if abs(cursor - float(spec["duration_seconds"])) > 0.01:
        raise ValueError("combat beats must cover the full generation duration")

    camera_prompt, camera_contract = compile_combat_camera_language(
        contract, beats, float(spec["duration_seconds"]), spec["mode"]
    )

    winner = require(contract.get("winner"), "combat winner is required")
    restrained = require(contract.get("restrained_actor"), "combat restrained_actor is required")
    if winner not in names or restrained not in names or winner == restrained:
        raise ValueError("combat winner and restrained_actor must be distinct participants")
    terminal = require(contract.get("terminal_identity_hold"), "combat terminal_identity_hold is required")
    prompt = (
        "\n【打斗身份硬锁】" + "；".join(participant_rows) + "。"
        "@视频1只参考动作节拍、真实重心转移和受力反馈，不继承人物、服装、场景、胜负或运镜。"
        "\n【逐拍动作因果】" + "；".join(beat_rows) + "。"
        + camera_prompt
        + f"\n【胜负终态硬锁】胜者={winner}；被制服者={restrained}；终局画面={terminal}。"
        "禁止互换身份、禁止攻守倒置、禁止让胜者被按住、禁止橡皮肢体、假摔、无接触挥舞和重复招式。"
    )
    return prompt, {
        "participants": names,
        "identity_reference_shas": sorted(reference_shas),
        "action_reference_video": reference_video,
        "beats": beats,
        "winner": winner,
        "restrained_actor": restrained,
        "terminal_identity_hold": terminal,
        "camera_language_plan": camera_contract,
    }


def require(value, message: str):
    if value is None or value == "" or value == []:
        raise ValueError(message)
    return value


def enforce_post_only_glyph_contract(prompt: str, spec: dict) -> list[str]:
    """Keep exact audience-facing strings out of provider visual prompts."""
    if spec.get("text_layer_post_only") is not True:
        return []
    glyphs = require(
        spec.get("post_only_glyphs"),
        "text_layer_post_only requires post_only_glyphs",
    )
    if not isinstance(glyphs, list) or any(not str(value).strip() for value in glyphs):
        raise ValueError("post_only_glyphs must be a non-empty list of exact strings")
    leaked = sorted({str(value).strip() for value in glyphs if str(value).strip() in prompt})
    if leaked:
        raise ValueError(
            "PROMPT_LITERAL_GLYPH_SCAN failed; replace exact audience text with opaque PROP_IDs: "
            + ",".join(leaked)
        )
    return [str(value).strip() for value in glyphs]


def enforce_dialogue_mode_consistency(spec: dict) -> str:
    """Reject a silent visual contract that is later presented as lip-synced speech."""
    shots = spec.get("shots") or []
    dialogues = [shot["dialogue"] for shot in shots if shot.get("dialogue")]
    voice_over = spec.get("voice_over_manifest") or []
    declared = spec.get("dialogue_mode")
    mode = declared or ("ON_CAMERA_NATIVE_LIP_SYNC" if dialogues else "NO_DIALOGUE")
    if mode not in DIALOGUE_MODES:
        raise ValueError(f"unsupported dialogue_mode: {mode}")

    authored = json.dumps(spec, ensure_ascii=False).lower()
    silent_markers = [marker for marker in SILENT_PERFORMANCE_MARKERS if marker.lower() in authored]
    if dialogues and silent_markers:
        raise ValueError(
            "DIALOGUE_MODE_CONSISTENCY failed; on-camera dialogue conflicts with silent performance: "
            + ",".join(silent_markers)
        )
    if mode == "ON_CAMERA_NATIVE_LIP_SYNC":
        if not dialogues:
            raise ValueError("ON_CAMERA_NATIVE_LIP_SYNC requires shot dialogue")
        entities = {entity.get("name"): entity for entity in (spec.get("entities") or [])}
        for row in dialogues:
            speaker = require(row.get("speaker"), "dialogue speaker is required")
            entity = entities.get(speaker)
            if not entity or not entity.get("audio_ref"):
                raise ValueError(
                    f"ON_CAMERA_NATIVE_LIP_SYNC requires an audio_ref for visible speaker {speaker}"
                )
    elif mode == "CLOSED_MOUTH_VOICE_OVER":
        if dialogues:
            raise ValueError(
                "CLOSED_MOUTH_VOICE_OVER forbids shot dialogue; move exact speech to voice_over_manifest"
            )
        if not isinstance(voice_over, list) or not voice_over:
            raise ValueError("CLOSED_MOUTH_VOICE_OVER requires voice_over_manifest")
        for index, row in enumerate(voice_over, start=1):
            require(row.get("speaker"), f"voice_over_manifest {index} speaker is required")
            require(row.get("text"), f"voice_over_manifest {index} text is required")
            require(row.get("audio_source"), f"voice_over_manifest {index} audio_source is required")
    elif dialogues or voice_over:
        raise ValueError("NO_DIALOGUE forbids shot dialogue and voice_over_manifest")
    return mode


def compile_expressive_voice_contract(spec: dict, mode: str) -> tuple[str, dict | None]:
    """Compile line-level psychology and prosody before native speech generation."""
    if mode == "NO_DIALOGUE":
        return "", None
    dialogues = [shot["dialogue"] for shot in (spec.get("shots") or []) if shot.get("dialogue")]
    rows = dialogues if mode == "ON_CAMERA_NATIVE_LIP_SYNC" else (spec.get("voice_over_manifest") or [])
    profiles, speaker_signatures = [], {}
    for index, row in enumerate(rows, start=1):
        speaker = require(row.get("speaker"), f"dialogue line {index} speaker is required")
        text = require(row.get("text"), f"dialogue line {index} text is required")
        values = {
            field: require(row.get(field), f"dialogue line {index} {field} is required by expressive voice contract")
            for field in EXPRESSIVE_DIALOGUE_FIELDS
        }
        intensity = int(values["emotion_intensity"])
        if not 1 <= intensity <= 5:
            raise ValueError(f"dialogue line {index} emotion_intensity must be between 1 and 5")
        emphasis = values["emphasis_words"]
        if not isinstance(emphasis, list) or not emphasis or any(not str(word).strip() for word in emphasis):
            raise ValueError(f"dialogue line {index} emphasis_words must be a non-empty list")
        missing_words = [str(word) for word in emphasis if str(word) not in text]
        if missing_words:
            raise ValueError(f"dialogue line {index} emphasis_words are absent from text: {','.join(missing_words)}")
        signature = (
            values["psychological_state"], values["emotion"], intensity, values["pace"],
            values["pause_map"], len(emphasis), values["volume_arc"],
            values["breath_pattern"], values["delivery_transition"],
        )
        speaker_signatures.setdefault(speaker, []).append(signature)
        profiles.append({
            "line_index": index, "speaker": speaker,
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            **values, "emotion_intensity": intensity,
        })
    if spec.get("allow_deliberately_monotone_performance") is not True:
        for speaker, signatures in speaker_signatures.items():
            if len(signatures) > 1 and len(set(signatures)) == 1:
                raise ValueError(
                    f"EXPRESSIVE_VOICE_VARIATION failed; {speaker} repeats one emotion/prosody signature across every line"
                )
    prompt_rows = [
        f"第{row['line_index']}句{row['speaker']}：心理{row['psychological_state']}；情绪{row['emotion']}"
        f"(强度{row['emotion_intensity']}/5)；语速{row['pace']}；停连{row['pause_map']}；"
        f"重音{'、'.join(row['emphasis_words'])}；音量{row['volume_arc']}；气息{row['breath_pattern']}；"
        f"句内转变{row['delivery_transition']}；身体同步{row['body_sync']}"
        for row in profiles
    ]
    prompt = (
        "\n【逐句心理与语音表演硬锁】保持每个角色既定声纹，不改变年龄、音色和口音；"
        + "；".join(prompt_rows)
        + "。语气必须由当句心理和事件变化驱动，禁止新闻播报腔、全句同强度、全场同语速、机械匀速、无重音、无停连。"
    )
    return prompt, {
        "profiles": profiles,
        "speaker_profile_counts": {speaker: len(rows) for speaker, rows in speaker_signatures.items()},
        "variation_gate": "PASS",
        "voice_identity_preserved": True,
    }


def load_local_lora_memory(mode: str, path: Path = DEFAULT_LOCAL_LORA_MEMORY) -> tuple[list[dict], str | None]:
    """Load admitted LoRA-ready examples whose guards apply before paid generation."""
    # Only the configured production dataset participates in centralized sync.
    # Callers may pass a temporary or episode-local memory file containing
    # pending defensive rewrites that are valid for compilation but are not
    # ADMITTED training rows and must never be staged to the collector.
    if path.expanduser().resolve() == DEFAULT_LOCAL_LORA_MEMORY.expanduser().resolve():
        auto_sync(path)
    if not path.is_file():
        return [], None
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("status") not in {"ADMITTED", "ACTIVE_REWRITE_PENDING_POSITIVE"} or mode not in (row.get("applicable_modes") or []):
            continue
        require(row.get("sample_id"), f"local LoRA memory line {line_number} sample_id is required")
        require(row.get("compiler_guard_clause"), f"local LoRA memory line {line_number} compiler_guard_clause is required")
        rows.append(row)
    return rows, hashlib.sha256(path.read_bytes()).hexdigest()


def entity_header(entities: list[dict], setting: str) -> str:
    parts = []
    tokens = set()
    for entity in entities:
        token = require(entity.get("token"), "entity token is required")
        if token in tokens:
            raise ValueError(f"duplicate entity token: {token}")
        tokens.add(token)
        name = require(entity.get("name"), f"entity name is required: {token}")
        description = require(entity.get("description"), f"entity description is required: {token}")
        audio_ref = entity.get("audio_ref")
        audio = f"，音色参考 {audio_ref}" if audio_ref else ""
        parts.append(f"{name}[[{token}]]（{description}{audio}）")
    return "；".join(parts) + f"。整体设定：{require(setting, 'setting is required')}"


def compile_shot(shot: dict, index: int) -> str:
    framing = require(shot.get("framing"), f"shot {index} framing is required")
    camera = require(shot.get("camera"), f"shot {index} camera is required")
    action = require(shot.get("action"), f"shot {index} action is required")
    expression = require(shot.get("expression_arc"), f"shot {index} expression_arc is required")
    cut_reason = require(shot.get("cut_reason"), f"shot {index} cut_reason is required")
    realism = build_expression_realism_block(expression_arc=expression, action=action, framing=framing)
    line = f"镜头{index}：【{framing}，{camera}】{action}。表情弧：{expression}。{realism}"
    dialogue = shot.get("dialogue")
    if dialogue:
        speaker = require(dialogue.get("speaker"), f"shot {index} dialogue speaker is required")
        text = require(dialogue.get("text"), f"shot {index} dialogue text is required")
        line += (
            f" {speaker}清楚说：{{{text}}} 只有{speaker}口型运动；"
            f"心理{dialogue['psychological_state']}，情绪{dialogue['emotion']}强度{dialogue['emotion_intensity']}/5，"
            f"语速{dialogue['pace']}，停连{dialogue['pause_map']}，重音{'、'.join(dialogue['emphasis_words'])}，"
            f"音量{dialogue['volume_arc']}，气息{dialogue['breath_pattern']}，"
            f"句内转变{dialogue['delivery_transition']}，身体同步{dialogue['body_sync']}。"
        )
    if shot.get("sound"):
        line += f" <{shot['sound']}>"
    line += f" 切因：{cut_reason}。"
    return line


def compile_visual_direction(shot: dict, index: int) -> str:
    for field in VISUAL_FIELDS:
        require(shot.get(field), f"shot {index} {field} is required by visual benchmark contract")
    duration = shot["duration_seconds"]
    if not 4 <= duration <= 15:
        raise ValueError(f"shot {index} duration_seconds must be between 4 and 15")
    depth = shot["depth_layers"]
    if len(depth) < 3:
        raise ValueError(f"shot {index} depth_layers requires foreground, midground and background")
    palette = shot["palette"]
    for role in ("dominant", "contrast", "accent"):
        require(palette.get(role), f"shot {index} palette.{role} is required")
    return (
        f"视觉合约：时长{duration}秒；景别{shot['shot_scale']}；镜头意图{shot['lens_intent']}；"
        f"机位高度{shot['camera_height']}；运镜{shot['camera_motion']}；"
        f"空间层次{' / '.join(depth)}；尺度锚点{shot['scale_anchor']}；"
        f"配色主色{palette['dominant']}、对比色{palette['contrast']}、点睛色{palette['accent']}；"
        f"动机光{shot['key_light']}；空气{shot['atmosphere']}；"
        f"环境运动{' / '.join(shot['environmental_motion'])}；材质{' / '.join(shot['material_detail'])}；"
        f"静帧约束{shot['still_prompt_contract']}；视频运动约束{shot['video_motion_contract']}；"
        f"禁止{' / '.join(shot['negative_constraints'])}。"
    )


def scene_lock_header(scene_lock: dict) -> str:
    fields = {name: require(scene_lock.get(name), f"scene_lock.{name} is required")
              for name in ("location", "time_of_day", "weather", "event")}
    return (
        f"剧本场景硬锁：地点{fields['location']}；时段{fields['time_of_day']}；"
        f"天气{fields['weather']}；事件{fields['event']}。以上四项只读，禁止为了电影感改写。"
    )


def compile_actor_motion_coverage(frame: dict, index: int, actor_roster: list[str]) -> tuple[str, list[dict]]:
    """Require an explicit motion or offscreen disposition for every actor."""
    coverage = require(frame.get("actor_motion"), f"keyframe {index} actor_motion is required")
    if not isinstance(coverage, dict):
        raise ValueError(f"keyframe {index} actor_motion must be an object keyed by actor")
    expected, actual = set(actor_roster), set(coverage)
    if actual != expected:
        missing = ",".join(sorted(expected - actual)) or "none"
        extra = ",".join(sorted(actual - expected)) or "none"
        raise ValueError(f"keyframe {index} actor_motion must cover the full actor roster; missing={missing}; extra={extra}")
    compiled, prompt_rows = [], []
    for actor in actor_roster:
        row = coverage[actor]
        if not isinstance(row, dict):
            raise ValueError(f"keyframe {index} actor_motion.{actor} must be an object")
        visible = row.get("visible")
        if visible is False:
            reason = require(row.get("offscreen_reason"), f"keyframe {index} offscreen actor {actor} requires offscreen_reason")
            compiled.append({"actor": actor, "visible": False, "offscreen_reason": reason})
            prompt_rows.append(f"{actor}=已离开画面，原因是{reason}")
            continue
        if visible is not True:
            raise ValueError(f"keyframe {index} actor_motion.{actor}.visible must be true or false")
        micro = require(row.get("continuous_micro_action"), f"keyframe {index} visible actor {actor} requires continuous_micro_action")
        reaction = require(row.get("event_reaction"), f"keyframe {index} visible actor {actor} requires event_reaction")
        motion_cues = require(row.get("motion_cues"), f"keyframe {index} visible actor {actor} requires motion_cues")
        if not isinstance(motion_cues, list) or len(motion_cues) < 2 or any(not str(cue).strip() for cue in motion_cues):
            raise ValueError(f"keyframe {index} visible actor {actor} requires at least two positive motion_cues")
        authored_motion = f"{micro} {reaction} {' '.join(str(cue) for cue in motion_cues)}".lower()
        static_terms = [term for term in STATIC_ACTOR_MOTION_TERMS if term.lower() in authored_motion]
        if static_terms:
            raise ValueError(
                f"keyframe {index} visible actor {actor} authors a static pose instead of continuous motion: {','.join(static_terms)}"
            )
        compiled.append({
            "actor": actor, "visible": True, "continuous_micro_action": micro,
            "event_reaction": reaction, "motion_cues": [str(cue) for cue in motion_cues],
        })
        prompt_rows.append(
            f"{actor}=持续动作({micro})，事件反应({reaction})，可见动势({'、'.join(str(cue) for cue in motion_cues)})"
        )
    return "；".join(prompt_rows), compiled


def compile_multi_keyframe_long_take(spec: dict) -> tuple[str, dict]:
    """Compile a spatially continuous 15-second Omni shot from ordered keyframes."""
    duration = require(spec.get("duration_seconds"), "duration_seconds is required")
    if duration != 15:
        raise ValueError("multi_keyframe_long_take requires exactly 15 seconds")
    if spec.get("model") != "seedance-2.0":
        raise ValueError("multi_keyframe_long_take requires seedance-2.0 (standard)")
    if spec.get("resolution") != "1080p":
        raise ValueError("multi_keyframe_long_take requires native 1080p")
    if spec.get("real_time_1x") is not True:
        raise ValueError("multi_keyframe_long_take requires real_time_1x=true")
    camera_policy = require(spec.get("camera_motion_policy"), "camera_motion_policy is required")
    if camera_policy != "MOTIVATED_TRACK_OR_LOCKED_AXIS_NO_SWAY_NO_ORBIT_NO_ROAM":
        raise ValueError("camera_motion_policy must forbid sway, orbit and roam")
    keyframes = require(spec.get("keyframes"), "keyframes are required")
    if not 3 <= len(keyframes) <= 9:
        raise ValueError("multi_keyframe_long_take requires 3 to 9 keyframes")
    actor_roster = require(spec.get("actor_roster"), "multi_keyframe_long_take actor_roster is required")
    if not isinstance(actor_roster, list) or len(actor_roster) < 1 or any(not str(actor).strip() for actor in actor_roster):
        raise ValueError("multi_keyframe_long_take actor_roster must be a non-empty list")
    actor_roster = [str(actor).strip() for actor in actor_roster]
    if len(set(actor_roster)) != len(actor_roster):
        raise ValueError("multi_keyframe_long_take actor_roster contains duplicates")
    character_prompt, character_registry = compile_episode_character_registry(spec, actor_roster)
    combat_prompt, combat_contract = compile_combat_choreography_contract(spec, actor_roster)
    times, timeline, compiled_frames = [], [], []
    states = set()
    previous_zone = previous_state = None
    previous_camera_side = None
    for index, frame in enumerate(keyframes, start=1):
        timestamp = float(require(frame.get("timestamp_seconds"), f"keyframe {index} timestamp_seconds is required"))
        if times and timestamp <= times[-1]:
            raise ValueError(f"keyframe {index} timestamps must be strictly increasing")
        image_path = Path(require(frame.get("image_path"), f"keyframe {index} image_path is required"))
        expected_sha = require(frame.get("image_sha256"), f"keyframe {index} image_sha256 is required")
        if not image_path.is_file():
            raise ValueError(f"keyframe {index} image does not exist: {image_path}")
        actual_sha = hashlib.sha256(image_path.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise ValueError(f"keyframe {index} image SHA mismatch")
        state = require(frame.get("state_token"), f"keyframe {index} state_token is required")
        if state in states:
            raise ValueError(f"keyframe {index} repeats action state: {state}")
        states.add(state)
        zone = require(frame.get("location_zone"), f"keyframe {index} location_zone is required")
        blocking = require(frame.get("actor_blocking"), f"keyframe {index} actor_blocking is required")
        event = require(frame.get("action_event"), f"keyframe {index} action_event is required")
        actor_motion_prompt, actor_motion = compile_actor_motion_coverage(frame, index, actor_roster)
        reference_role = require(frame.get("reference_role"), f"keyframe {index} reference_role is required")
        camera_side = require(frame.get("camera_side"), f"keyframe {index} camera_side is required")
        camera_position = require(frame.get("camera_position"), f"keyframe {index} camera_position is required")
        camera_facing = require(frame.get("camera_facing"), f"keyframe {index} camera_facing is required")
        preserve = require(frame.get("preserve_from_previous"), f"keyframe {index} preserve_from_previous is required")
        reject_inheritance = require(frame.get("do_not_inherit"), f"keyframe {index} do_not_inherit is required")
        transition = frame.get("transition_from_previous")
        if previous_zone is not None and zone != previous_zone:
            if not transition or transition.get("kind") != "SAME_APERTURE_CROSSING":
                raise ValueError(f"keyframe {index} changes location without SAME_APERTURE_CROSSING")
            require(transition.get("aperture_id"), f"keyframe {index} crossing aperture_id is required")
            require(transition.get("direction"), f"keyframe {index} crossing direction is required")
        if previous_state is not None:
            if not transition:
                raise ValueError(f"keyframe {index} transition_from_previous is required")
            if transition.get("teleport_allowed") is not False:
                raise ValueError(f"keyframe {index} must explicitly forbid teleport")
            if transition.get("action_reset_allowed") is not False:
                raise ValueError(f"keyframe {index} must explicitly forbid action reset")
            require(transition.get("continuous_camera_path"), f"keyframe {index} continuous_camera_path is required")
            if transition.get("camera_axis_reset_allowed") is not False:
                raise ValueError(f"keyframe {index} must explicitly forbid camera-axis reset")
            if transition.get("camera_from_side") != previous_camera_side:
                raise ValueError(f"keyframe {index} camera_from_side does not match the previous keyframe")
            if transition.get("camera_to_side") != camera_side:
                raise ValueError(f"keyframe {index} camera_to_side does not match the current keyframe")
            travel = float(require(transition.get("camera_travel_distance_m"), f"keyframe {index} camera_travel_distance_m is required"))
            axis_change = float(require(transition.get("camera_axis_change_degrees"), f"keyframe {index} camera_axis_change_degrees is required"))
            interval = timestamp - times[-1]
            if travel / interval > 2.5:
                raise ValueError(f"keyframe {index} camera path exceeds 2.5 m/s")
            if axis_change > 90:
                raise ValueError(f"keyframe {index} camera axis change exceeds 90 degrees")
            if transition.get("kind") == "SAME_APERTURE_CROSSING":
                if transition.get("camera_path_kind") != "FOLLOW_THROUGH_SAME_APERTURE":
                    raise ValueError(f"keyframe {index} crossing requires FOLLOW_THROUGH_SAME_APERTURE camera path")
                if transition.get("camera_crosses_with_subjects") is not True:
                    raise ValueError(f"keyframe {index} crossing camera must move with the subjects")
                if transition.get("camera_path_aperture_id") != transition.get("aperture_id"):
                    raise ValueError(f"keyframe {index} camera aperture does not match subject aperture")
        timeline.append(
            f"{timestamp:g}秒到达@图片{index}：该图只负责{reference_role}；{event}；人物站位：{blocking}；"
            f"逐人动作覆盖：{actor_motion_prompt}；"
            f"摄影机位于{camera_side}，位置{camera_position}，朝向{camera_facing}；"
            f"必须继承{preserve}；不得从该图继承{'、'.join(reject_inheritance)}；"
            f"动作状态从{previous_state or '镜头起始'}连续推进到{state}。"
        )
        compiled_frames.append({
            "reference": f"@图片{index}", "timestamp_seconds": timestamp,
            "image_path": str(image_path), "image_sha256": actual_sha,
            "state_token": state, "location_zone": zone,
            "reference_role": reference_role,
            "actor_motion": actor_motion,
            "camera_side": camera_side, "camera_position": camera_position,
            "camera_facing": camera_facing, "preserve_from_previous": preserve,
            "do_not_inherit": reject_inheritance, "transition_from_previous": transition,
        })
        times.append(timestamp)
        previous_zone, previous_state, previous_camera_side = zone, state, camera_side
    if times[0] != 0 or times[-1] != 15:
        raise ValueError("keyframe timeline must start at 0 seconds and end at 15 seconds")
    subject_lock = require(spec.get("subject_and_identity_lock"), "subject_and_identity_lock is required")
    spatial_lock = require(spec.get("spatial_continuity_lock"), "spatial_continuity_lock is required")
    action_axis = require(spec.get("action_axis"), "action_axis is required")
    negative = require(spec.get("negative_constraints"), "negative_constraints are required")
    memory_path = Path(spec.get("local_lora_memory_path") or DEFAULT_LOCAL_LORA_MEMORY)
    memory_rows, memory_sha = load_local_lora_memory("multi_keyframe_long_take", memory_path)
    memory_clause = ""
    if memory_rows:
        memory_clause = "\n【本地LoRA失败记忆预编译】" + "；".join(
            f"{row['sample_id']}：{row['compiler_guard_clause']}" for row in memory_rows
        ) + "。"
    prompt = (
        f"15秒一镜到底，Seedance 2.0 Pro，原生1080p，实时1倍速。{subject_lock}\n"
        f"动作轴：{action_axis}。空间连续硬锁：{spatial_lock}。\n" + "\n".join(timeline)
        + memory_clause
        + character_prompt
        + combat_prompt
        + f"\n镜头只为跟清楚动作因果而移动；禁止无动机摇摆、smooth roam、slow push、orbit、overhead reveal、慢动作、插帧、动作重演、人物瞬移、机位重置、空间跳切。禁止：{' / '.join(negative)}。\n"
    )
    post_only_glyphs = enforce_post_only_glyph_contract(prompt, spec)
    return prompt, {
        "schema": "qingshan.seedance2_multi_keyframe_long_take.v1",
        "mode": "multi_keyframe_long_take", "route": "/api/v1/generation/omni-video",
        "contract": "15s_ordered_multi_keyframe_spatial_continuity", "duration_seconds": 15,
        "model": spec["model"], "resolution": spec["resolution"], "real_time_1x": True,
        "camera_motion_policy": camera_policy, "keyframes": compiled_frames,
        "actor_roster": actor_roster,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "local_lora_memory": {
            "path": str(memory_path), "sha256": memory_sha,
            "applied_sample_ids": [row["sample_id"] for row in memory_rows],
            "precompiled_before_paid_generation": True,
        },
        "gates": ["ORDERED_KEYFRAME_SHA_BINDING", "REFERENCE_ROLE_AND_INHERITANCE_SCOPE",
                  "NO_REPEATED_ACTION_STATE", "NO_TELEPORT_OR_ACTION_RESET",
                  "SAME_APERTURE_LOCATION_CROSSING", "REAL_TIME_1X",
                  "NO_UNMOTIVATED_CAMERA_MOTION", "ADJACENT_CAMERA_TRAJECTORY_REACHABILITY",
                  "FULL_VISIBLE_ACTOR_MOTION_COVERAGE",
                  "EPISODE_CHARACTER_ASSETS_FROZEN_AND_UNIQUE",
                  "COMBAT_IDENTITY_CHOREOGRAPHY_AND_OUTCOME" if combat_contract else "NO_COMBAT_CONTRACT",
                  "LOCAL_LORA_FAILURE_MEMORY_PRECOMPILED",
                  "PROMPT_LITERAL_GLYPH_SCAN" if spec.get("text_layer_post_only") else "NO_POST_ONLY_GLYPH_CONTRACT"],
        "text_layer_post_only": bool(spec.get("text_layer_post_only")),
        "post_only_glyph_count": len(post_only_glyphs),
        "episode_character_registry": character_registry,
        "combat_choreography_contract": combat_contract,
    }


def compile_prompt(spec: dict) -> tuple[str, dict]:
    mode = require(spec.get("mode"), "mode is required")
    if mode not in MODES:
        raise ValueError(f"unsupported mode: {mode}")
    dialogue_mode = enforce_dialogue_mode_consistency(spec)
    expressive_voice_prompt, expressive_voice_contract = compile_expressive_voice_contract(spec, dialogue_mode)
    if mode == "multi_keyframe_long_take":
        prompt, manifest = compile_multi_keyframe_long_take(spec)
        manifest["dialogue_mode"] = dialogue_mode
        manifest["dialogue_mode_gate"] = "PASS"
        manifest["expressive_voice_contract"] = expressive_voice_contract
        manifest["gates"].append("EXPRESSIVE_VOICE_PSYCHOLOGY_AND_PROSODY")
        prompt += expressive_voice_prompt
        manifest["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return prompt, manifest
    entities = require(spec.get("entities"), "entities are required")
    shots = require(spec.get("shots"), "shots are required")
    header = entity_header(entities, spec.get("setting"))
    combat_prompt, combat_contract = "", None
    character_registry = None
    if spec.get("combat_choreography_contract"):
        actor_roster = require(spec.get("actor_roster"), "combat actor_roster is required")
        character_prompt, character_registry = compile_episode_character_registry(spec, actor_roster)
        combat_prompt, combat_contract = compile_combat_choreography_contract(spec, actor_roster)
        header += character_prompt
    tail = require(spec.get("style_and_negative"), "style_and_negative is required")
    visual_contract = spec.get("visual_benchmark_contract")
    if visual_contract:
        version = require(visual_contract.get("version"), "visual_benchmark_contract.version is required")
        header += "\n" + scene_lock_header(require(spec.get("scene_lock"), "scene_lock is required"))
    else:
        version = None

    if mode == "storyboard":
        if len(shots) < 2:
            raise ValueError("storyboard mode requires at least two intentional shots")
        body = "\n\n".join(
            compile_shot(shot, index)
            + ("\n" + compile_visual_direction(shot, index) if visual_contract else "")
            for index, shot in enumerate(shots, 1)
        )
        route = "/api/v1/generation/omni-video"
        contract = "numbered_shots_are_intentional_montage"
    else:
        if len(shots) != 1:
            raise ValueError("continuous_long_take mode requires exactly one shot")
        if not spec.get("start_frame") or not spec.get("end_frame"):
            raise ValueError("continuous_long_take requires start_frame and end_frame")
        shot = shots[0]
        if shot.get("cut_reason"):
            raise ValueError("continuous_long_take cannot declare a cut_reason")
        framing = require(shot.get("framing"), "continuous shot framing is required")
        camera = require(shot.get("camera"), "continuous shot camera is required")
        action = require(shot.get("action"), "continuous shot action is required")
        expression = require(shot.get("expression_arc"), "continuous shot expression_arc is required")
        body = (
            f"镜头1：【15秒一镜到底，{framing}，{camera}】{action}。"
            f"表情弧：{expression}。"
            f"{build_expression_realism_block(expression_arc=expression, action=action, framing=framing)}"
            "全程不得出现切镜、转场、分段镜头编号或机位重置。"
        )
        if visual_contract:
            body += "\n" + compile_visual_direction(shot, 1)
        route = "/api/v1/generation/image-to-video"
        contract = "single_unbroken_shot_first_last_frames"

    cinematic_prompt, cinematic_contract = compile_cinematic_shot_language_contract(spec, len(shots))
    prompt = f"{header}\n\n{body}{combat_prompt}{expressive_voice_prompt}{cinematic_prompt}\n\n{tail.strip()}\n"
    post_only_glyphs = enforce_post_only_glyph_contract(prompt, spec)
    manifest = {
        "schema": "qingshan.seedance2_prompt_compilation.v2" if visual_contract else "qingshan.seedance2_prompt_compilation.v1",
        "mode": mode,
        "route": route,
        "contract": contract,
        "shot_count": len(shots),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "text_layer_post_only": bool(spec.get("text_layer_post_only")),
        "post_only_glyph_count": len(post_only_glyphs),
        "dialogue_mode": dialogue_mode,
        "dialogue_mode_gate": "PASS",
        "expressive_voice_contract": expressive_voice_contract,
        "episode_character_registry": character_registry,
        "combat_choreography_contract": combat_contract,
        "combat_camera_language_gate": "PASS_MOTIVATED_ONLY" if combat_contract else "NOT_APPLICABLE",
        "cinematic_shot_language_contract": cinematic_contract,
        "cinematic_shot_language_gate": "PASS_SECTIONED_AND_TIME_CODED" if cinematic_contract else "NOT_APPLICABLE",
    }
    if version:
        manifest["visual_benchmark_contract_version"] = version
        manifest["script_state_locked"] = True
    if mode == "continuous_long_take":
        manifest["start_frame"] = spec["start_frame"]
        manifest["end_frame"] = spec["end_frame"]
    return prompt, manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    spec = json.loads(Path(args.input).read_text(encoding="utf-8"))
    prompt, manifest = compile_prompt(spec)
    out = Path(args.out)
    receipt = Path(args.manifest)
    out.parent.mkdir(parents=True, exist_ok=True)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(prompt, encoding="utf-8")
    receipt.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
