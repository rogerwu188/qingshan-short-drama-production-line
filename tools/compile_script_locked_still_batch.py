#!/usr/bin/env python3
"""Compile script-locked still prompts while preserving reusable candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from tools.compile_video_unit_plan import validate_compiled_plan
    from tools.image_model_adapter import compile_labeled_flat_identity_transport
except ModuleNotFoundError:
    from compile_video_unit_plan import validate_compiled_plan
    from image_model_adapter import compile_labeled_flat_identity_transport


ROOT = Path(__file__).resolve().parents[1]


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(resolve(path).read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def unique_existing(paths: list[str], limit: int = 4) -> list[str]:
    result: list[str] = []
    for value in paths:
        if value not in result and resolve(value).is_file():
            result.append(value)
        if len(result) == limit:
            break
    return result


def validate(manifest: dict[str, Any], scenes: dict[str, Any]) -> tuple[Path, dict[str, dict[str, Any]]]:
    source = resolve(manifest["source"]["script"])
    expected_sha = manifest["source"]["script_sha256"]
    if sha256(source) != expected_sha:
        raise ValueError("source script SHA mismatch")
    shots = manifest.get("shots") or []
    if len(shots) != manifest.get("shot_count"):
        raise ValueError("shot_count mismatch")
    if sum(int(item["duration_seconds"]) for item in shots) != manifest.get("runtime_seconds"):
        raise ValueError("runtime total mismatch")
    if len({item["shot_id"] for item in shots}) != len(shots):
        raise ValueError("duplicate shot_id")
    # Editorial cuts may be shorter than the generation API minimum. The
    # compiled video-unit plan separately enforces 4-15 second generation
    # units, so rejecting 1-3 second cuts here would erase valid montage beats.
    if any(not 1 <= int(item["duration_seconds"]) <= 15 for item in shots):
        raise ValueError("editorial shot duration outside 1-15 seconds")
    scene_items = scenes.get("scene_state") or []
    scene_by_id = {item["scene_id"]: item for item in scene_items}
    if len(scene_by_id) != manifest.get("scene_count"):
        raise ValueError("scene_count mismatch")
    missing = sorted({item["scene_id"] for item in shots} - set(scene_by_id))
    if missing:
        raise ValueError(f"unknown scenes: {missing}")
    return source, scene_by_id


def render_prompt(
    manifest: dict[str, Any],
    shot: dict[str, Any],
    scene: dict[str, Any],
    source_sha: str,
    video_unit_id: str,
    video_unit_duration_seconds: int,
    state_index: int = 1,
    state_count: int = 1,
    repair_feedback: dict[str, Any] | None = None,
) -> str:
    characters = ", ".join(shot.get("visible_characters") or shot.get("characters") or []) or "no foreground character"
    forbidden = ", ".join(scene.get("forbidden_prompt_tokens") or [])
    repair_clause = ""
    if repair_feedback:
        instructions = repair_feedback["instructions"]
        repair_clause = (
            "\n本轮仅修复上一候选的明确失败项："
            + "；".join(instructions)
            + "。必须重新构图解决这些问题，不得复刻上一候选。"
        )
    state_clause = ""
    if state_count > 1:
        if state_index == 1:
            phase = "同一视频单元的起始决定性状态，必须为后续动作留出清晰位移和受力空间"
        elif state_index == state_count:
            phase = "同一视频单元的结果决定性状态，动作结果必须已经落地并可衔接下一单元"
        else:
            phase = f"同一视频单元约推进到 {state_index / state_count:.0%} 的中间决定性状态"
        state_clause = (
            f"本图是该视频单元 C{state_index}/{state_count}：{phase}。"
            "它必须与同单元其他状态图保持地点、人物身份、服装、光线和动作轴一致，"
            "同时在人物重心、肢体位置、道具位置、接触结果或环境介质反应中至少两项具有明确差异。\n"
        )
    return (
        f"《青山》{manifest['episode']}《{manifest['title']}》锁源 SHA-256={source_sha}。\n"
        f"编辑镜头 {shot['shot_id']}，属于连续分镜视频单元 {video_unit_id}；"
        f"该单元由源剧本逐镜秒数自然分组为 {video_unit_duration_seconds} 秒，本镜头为 {shot['duration_seconds']} 秒。"
        f"地点={scene['location']}；时段={scene['time_of_day']}；天气={scene['weather']}。\n"
        f"剧情动作只允许：{shot['action']} 不增加人物、道具、对白或后续结果。\n"
        f"{state_clause}"
        f"人物身份参考：{characters}。附图仅用于身份、服装材质和场景连续性，禁止照搬附图中的旧剧情动作。\n"
        f"镜头语言：景别={shot['scale']}；机位与运动意图={shot['camera']}。"
        f"画面建立清晰前中后景，动作轴与视线轴一致，关键接触点一眼可读；画面恢弘、精美、写实电影质感，"
        f"古装武侠玄幻美剧式调度，真实材质、自然肤质、克制光效。\n"
        f"色彩={scene.get('palette', '')}；现场声音参考={shot['sound']}，本次只生成静帧但构图须为后续动作留出明确运动空间。\n"
        "硬约束：9:16 竖屏，2K；不得生成字幕、可读文字、水印、Logo；不得角色分身、重复肢体、额外手指；"
        "不得用站桩合影代替剧情动作；不得擅改地点、时段、天气、人物身份和事件。"
        "本任务只生成一张参考状态图；后续同一视频单元可同时使用多张状态图和多个内部镜头，本图不构成一图一视频限制。"
        f"禁止项={forbidden}。"
        f"{repair_clause}"
    )


def validate_repair_feedback(
    bundle: dict[str, Any], shot: dict[str, Any], source_sha: str, state_id: str
) -> None:
    required = {
        "schema", "shot_id", "source_script_sha256", "source_action_sha256",
        "candidate_sha256", "binding_method", "failed_checks", "visible_characters",
        "character_binding_mode", "instructions", "instructions_sha256",
    }
    if not isinstance(bundle, dict) or required - set(bundle):
        raise ValueError(f"{shot['shot_id']} repair feedback is not a complete bound v2 contract")
    if bundle["schema"] != "qingshan.bound_image_repair_feedback.v2":
        raise ValueError(f"{shot['shot_id']} repair feedback schema is not v2")
    if bundle["shot_id"] != state_id or bundle["binding_method"] != "EXACT_CANDIDATE_SHA_AND_SHOT_ID":
        raise ValueError(f"{state_id} repair feedback shot binding mismatch")
    if bundle.get("source_shot_id", shot["shot_id"]) != shot["shot_id"]:
        raise ValueError(f"{state_id} repair feedback source-shot binding mismatch")
    if bundle["source_script_sha256"] != source_sha or bundle["source_action_sha256"] != text_sha256(shot["action"]):
        raise ValueError(f"{shot['shot_id']} repair feedback source action mismatch")
    visible = shot.get("visible_characters") or shot.get("characters") or []
    if bundle["visible_characters"] != visible:
        raise ValueError(f"{shot['shot_id']} repair feedback visible-character mismatch")
    instructions = bundle["instructions"]
    if not isinstance(instructions, list) or not instructions or any(not isinstance(value, str) or not value.strip() for value in instructions):
        raise ValueError(f"{shot['shot_id']} repair feedback instructions are invalid")
    if bundle["instructions_sha256"] != text_sha256("\n".join(instructions)):
        raise ValueError(f"{shot['shot_id']} repair feedback instruction SHA mismatch")


def asset_binding(value: Any, *, role: str, entity_id: str) -> dict[str, Any]:
    if isinstance(value, str):
        path_value = value
        status = "UNVERIFIED_LEGACY_PATH"
        qa_report = None
    elif isinstance(value, dict):
        path_value = value.get("path")
        status = value.get("qa_status")
        qa_report = value.get("qa_report")
        if value.get("entity_id") != entity_id:
            raise ValueError(f"asset entity binding mismatch for {entity_id}")
    else:
        raise ValueError(f"asset binding missing for {entity_id}")
    path = resolve(path_value or "")
    if not path.is_file():
        raise ValueError(f"asset file missing for {entity_id}: {path}")
    return {
        "role": role,
        "entity_id": entity_id,
        "path": str(path.relative_to(ROOT)),
        "sha256": sha256(path),
        "qa_status": status,
        "qa_report": qa_report,
    }


def image_tier(manifest: dict[str, Any], shot_id: str) -> tuple[str, int, float]:
    policy = manifest.get("production_policy", {}).get("image_validation", {})
    core = shot_id in set(policy.get("core_shot_ids") or [])
    score_100 = int(policy.get("core_min_score" if core else "non_core_min_score", 80 if core else 60))
    return ("CORE" if core else "NON_CORE", score_100, score_100 / 20.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--video-unit-plan", required=True)
    parser.add_argument("--scene-state", required=True)
    parser.add_argument("--asset-map", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--batch-manifest", required=True)
    parser.add_argument("--gate-report", required=True)
    parser.add_argument("--candidate-output-dir")
    parser.add_argument("--qa-dir")
    parser.add_argument("--reuse-review-request")
    parser.add_argument("--only-shot-id", action="append", default=[])
    parser.add_argument("--only-state-id", action="append", default=[])
    parser.add_argument("--force-generate-shot-id", action="append", default=[])
    parser.add_argument("--repair-feedback")
    parser.add_argument("--task-version", default="V1")
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    video_unit_plan = load_json(args.video_unit_plan)
    validate_compiled_plan(manifest, video_unit_plan)
    scenes = load_json(args.scene_state)
    assets = load_json(args.asset_map)
    source, scene_by_id = validate(manifest, scenes)
    out_dir = resolve(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks: list[dict[str, Any]] = []
    reuse: list[dict[str, Any]] = []
    source_sha = manifest["source"]["script_sha256"]
    selected = set(args.only_shot_id)
    selected_states = set(args.only_state_id)
    forced = set(args.force_generate_shot_id)
    repair_feedback = load_json(args.repair_feedback) if args.repair_feedback else {}
    known_ids = {shot["shot_id"] for shot in manifest["shots"]}
    state_policy = manifest.get("production_policy", {}).get("multi_state_reference_policy") or {}
    minimum_states = int(state_policy.get("minimum_states_per_video_unit", 1))
    minimum_action_states = int(state_policy.get("minimum_states_per_action_unit", minimum_states))
    action_shots = set(state_policy.get("action_shot_ids") or [])
    unit_by_id = {unit["unit_id"]: unit for unit in video_unit_plan["units"]}
    shot_to_unit: dict[str, str] = {}
    for unit in video_unit_plan["units"]:
        for shot_id in unit["editorial_shot_ids"]:
            shot_to_unit[shot_id] = unit["unit_id"]
    shot_state_counts: dict[str, int] = {}
    if selected and selected_states:
        raise ValueError("--only-shot-id and --only-state-id are mutually exclusive")
    if selected - known_ids or forced - known_ids:
        raise ValueError("unknown --only-shot-id or --force-generate-shot-id")
    known_state_ids = {
        (shot["shot_id"] if count == 1 else f"{shot['shot_id']}-C{index}")
        for shot in manifest["shots"]
        for count in [minimum_action_states if shot["shot_id"] in action_shots else minimum_states]
        for index in range(1, count + 1)
    }
    if selected_states - known_state_ids:
        raise ValueError("unknown --only-state-id")
    if set(repair_feedback) - known_state_ids:
        raise ValueError("repair feedback contains unknown state_id")
    for shot in manifest["shots"]:
        video_unit_id = shot_to_unit[shot["shot_id"]]
        video_unit = unit_by_id[video_unit_id]
        target_state_count = minimum_action_states if shot["shot_id"] in action_shots else minimum_states
        first_generated_state = 1
        if shot["production_action"] == "REVIEW_REUSE" and shot["shot_id"] not in forced:
            candidate = shot["reuse_candidate"]
            candidate_path = resolve(candidate["path"])
            reuse.append({
                "shot_id": shot["shot_id"],
                "editorial_shot_id": shot["shot_id"],
                "video_unit_id": video_unit_id,
                "status": "PENDING_EXACT_SHOT_MACHINE_REVIEW",
                "candidate": candidate,
                "candidate_exists": candidate_path.is_file(),
                "candidate_sha_matches": candidate_path.is_file() and sha256(candidate_path) == candidate["sha256"],
                "expected_action": shot["action"],
            })
            if target_state_count == 1:
                continue
            first_generated_state = 2
        state_indexes = list(range(first_generated_state, target_state_count + 1))
        if selected and shot["shot_id"] not in selected:
            continue
        if selected_states:
            state_indexes = [
                index for index in state_indexes
                if (shot["shot_id"] if target_state_count == 1 else f"{shot['shot_id']}-C{index}") in selected_states
            ]
            if not state_indexes:
                continue
        shot_state_counts[shot["shot_id"]] = len(state_indexes)
        scene = scene_by_id[shot["scene_id"]]
        visible_characters = shot.get("visible_characters") or shot.get("characters") or []
        character_mode = "EXPLICIT_VISIBLE_CHARACTERS" if "visible_characters" in shot else "LEGACY_CHARACTERS_FIELD"
        reference_bindings = [
            asset_binding(assets["characters"].get(key), role="character", entity_id=key)
            for key in visible_characters
        ]
        reference_bindings.append(
            asset_binding(assets["scene_references"].get(shot["scene_id"]), role="scene", entity_id=shot["scene_id"])
        )
        references = [binding["path"] for binding in reference_bindings]
        identity_assets_verified = all(
            binding["qa_status"] == "PASS" for binding in reference_bindings if binding["role"] == "character"
        )
        contract_ready = character_mode == "EXPLICIT_VISIBLE_CHARACTERS" and identity_assets_verified
        for state_index in state_indexes:
            state_id = shot["shot_id"] if target_state_count == 1 else f"{shot['shot_id']}-C{state_index}"
            repair_bundle = repair_feedback.get(state_id)
            if repair_bundle:
                validate_repair_feedback(repair_bundle, shot, source_sha, state_id)
            prompt_path = out_dir / f"{state_id}.txt"
            prompt_body = render_prompt(
                    manifest,
                    shot,
                    scene,
                    source_sha,
                    video_unit_id,
                    int(video_unit["duration_seconds"]),
                    state_index,
                    target_state_count,
                    repair_bundle,
            )
            transport_bindings, identity_transport, effective_prompt = (
                compile_labeled_flat_identity_transport(
                    f"{state_id}-STILL-{args.task_version}", reference_bindings, prompt_body
                ) if visible_characters else (reference_bindings, {}, prompt_body)
            )
            references = [binding["path"] for binding in transport_bindings]
            prompt_path.write_text(effective_prompt + "\n", encoding="utf-8")
            prompt_contract = {
                "schema": "qingshan.image_prompt_contract.v2",
                "shot_id": state_id,
                "source_script_sha256": source_sha,
                "source_action": shot["action"],
                "source_action_sha256": text_sha256(shot["action"]),
                "visible_characters": visible_characters,
                "character_binding_mode": character_mode,
                "reference_bindings": transport_bindings,
                "editorial_shot_id": shot["shot_id"],
                "video_unit_id": video_unit_id,
                "video_unit_duration_seconds": video_unit["duration_seconds"],
                "state_index": state_index,
                "state_count": target_state_count,
                "state_role": "start_state" if state_index == 1 else "result_evidence" if state_index == target_state_count else "internal_action_state",
                "repair_feedback_sha256": text_sha256(json.dumps(repair_bundle, ensure_ascii=False, sort_keys=True)) if repair_bundle else None,
                "status": "PASS" if contract_ready else "FAIL",
                "failures": [
                    reason for condition, reason in (
                        (character_mode != "EXPLICIT_VISIBLE_CHARACTERS", "VISIBLE_CHARACTERS_NOT_EXPLICIT"),
                        (not identity_assets_verified, "CHARACTER_IDENTITY_ASSET_NOT_QA_VERIFIED"),
                    ) if condition
                ],
            }
            tasks.append({
                "task_key": f"{state_id}-STILL-{args.task_version}",
                "tool_type": "image_generation",
                "scene_id": shot["scene_id"],
                "shot_id": state_id,
                "editorial_shot_id": shot["shot_id"],
                "video_unit_id": video_unit_id,
                "video_unit_duration_seconds": video_unit["duration_seconds"],
                "state_index": state_index,
                "state_count": target_state_count,
                "beat_id": shot["scene_id"],
                "prompt_file": rel(prompt_path),
                "prompt_sha256": sha256(prompt_path),
                "reference_images": references,
                "reference_image_sequence": transport_bindings,
                "reference_bindings": transport_bindings,
                "identity_reference_transport": identity_transport or None,
                "generation_stage": "SCENE_KEYFRAME",
                "canonical_characters": visible_characters,
                "prompt_contract": prompt_contract,
                "model": "gpt-image-2-pro",
                "aspect_ratio": "9:16",
                "resolution": "2K",
                "status": "READY_FOR_PARALLEL_SUBMIT" if contract_ready else "BLOCKED_PROMPT_CONTRACT",
                "source_script_sha256": source_sha,
            })

    gate_path = resolve(args.gate_report)
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    coverage: list[dict[str, Any]] = []
    for unit in video_unit_plan["units"]:
        included_shots = [shot_id for shot_id in unit["editorial_shot_ids"] if shot_id in shot_state_counts]
        if not included_shots:
            continue
        coverage.append({
            "video_unit_id": unit["unit_id"],
            "scene_id": unit["scene_id"],
            "duration_seconds": unit["duration_seconds"],
            "editorial_shot_ids": included_shots,
            "action_unit": bool(unit.get("action_unit")),
            "required_state_count": sum(shot_state_counts[shot_id] for shot_id in included_shots),
            "per_editorial_shot_state_count": {
                shot_id: shot_state_counts[shot_id] for shot_id in included_shots
            },
        })
    planned_state_count = sum(row["required_state_count"] for row in coverage)
    coverage_complete = len(tasks) + len(reuse) == planned_state_count
    gate = {
        "schema": "qingshan.script_locked_still_preflight.v1",
        "episode": manifest["episode"],
        "status": "PASS" if coverage_complete else "FAIL",
        "source_script": rel(source),
        "source_script_sha256": source_sha,
        "video_unit_plan": rel(resolve(args.video_unit_plan)),
        "video_unit_plan_sha256": sha256(resolve(args.video_unit_plan)),
        "shot_count": len(manifest["shots"]),
        "runtime_seconds": sum(item["duration_seconds"] for item in manifest["shots"]),
        "generate_new_count": len(tasks),
        "editorial_shot_count": len(shot_state_counts),
        "video_unit_count": len(coverage),
        "planned_state_count": planned_state_count,
        "covered_state_count": len(tasks) + len(reuse),
        "multi_state_coverage_by_video_unit": coverage,
        "reuse_review_count": len(reuse),
        "reuse_candidates": reuse,
        "media_relationship": {
            "script_shots_to_reference_stills": "MANY_TO_MANY",
            "reference_stills_to_video_units": "MANY_TO_MANY",
            "one_reference_still_is_one_readable_state": True,
            "one_video_unit_may_bind_multiple_reference_stills": True,
            "one_video_unit_may_contain_multiple_internal_shots": True,
            "video_unit_duration_seconds": video_unit_plan["duration_policy_seconds"],
            "video_unit_grouping_method": "SCENE_LOCAL_CONTIGUOUS_NARRATIVE_GROUPING_FIRST",
            "unit_count_is_derived_from_validated_groups": True,
            "runtime_division_or_target_count_forbidden": True,
            "forbid_one_still_equals_one_video_assumption": True,
        },
        "rules": ["4_TO_15_SECONDS", "REUSE_BEFORE_REGENERATE", "NO_OLD_FINAL_OVERWRITE"],
    }
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if args.reuse_review_request:
        review_path = resolve(args.reuse_review_request)
        review_path.parent.mkdir(parents=True, exist_ok=True)
        review_items = []
        for item in reuse:
            if not item["candidate_exists"] or not item["candidate_sha_matches"]:
                raise ValueError(f"reuse candidate binding failed: {item['shot_id']}")
            scene_id = next(row["scene_id"] for row in manifest["shots"] if row["shot_id"] == item["shot_id"])
            scene = scene_by_id[scene_id]
            tier, minimum_100, pass_score = image_tier(manifest, item["shot_id"])
            review_items.append({
                "path": str(resolve(item["candidate"]["path"])),
                "scope": "shot",
                "kind": "image",
                "importance": "critical",
                "pass_score": pass_score,
                "clip_id": item["shot_id"],
                "metadata": {
                    "episode": manifest["episode"],
                    "scene_id": scene_id,
                    "candidate_sha256": item["candidate"]["sha256"],
                    "source_script_sha256": source_sha,
                    "image_tier": tier,
                    "minimum_score_100": minimum_100,
                    "review_focus": [
                        f"location must read as {scene['location']}",
                        f"time of day must read as {scene['time_of_day']}",
                        f"weather/environment must read as {scene['weather']}",
                        f"story action must clearly depict: {item['expected_action']}",
                        "canonical character identity, age, gender and costume continuity",
                        "single continuous cinematic frame, not a collage, contact sheet or storyboard grid",
                        "no readable or pseudo-readable text, watermark, logo, duplicated identity, fused limbs or extra people",
                    ],
                },
                "required_capabilities": ["image_analysis", "ocr"],
                "run_regression_ci": True,
                "use_existing_tools": True,
            })
        review_path.write_text(json.dumps({"items": review_items, "workers": 4}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    batch_path = resolve(args.batch_manifest)
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    blocked_tasks = [task["task_key"] for task in tasks if task["status"] != "READY_FOR_PARALLEL_SUBMIT"]
    batch = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": manifest["episode"],
        "status": "READY_TO_SUBMIT_CONCURRENTLY" if not blocked_tasks and coverage_complete else "BLOCKED_STATE_COVERAGE_OR_PROMPT_CONTRACT",
        "source_script_sha256": source_sha,
        "scene_contract_ref": args.scene_state,
        "production_manifest_ref": args.manifest,
        "video_unit_plan_ref": args.video_unit_plan,
        "video_unit_plan_sha256": sha256(resolve(args.video_unit_plan)),
        "machine_gate_reports": [rel(gate_path)],
        "output_dir": args.candidate_output_dir or f"working_assets/{manifest['episode'].lower()}_claude_writer_v1_stills/candidates",
        "qa_dir": args.qa_dir or f"qa/{manifest['episode'].lower()}_claude_writer_v1_stills",
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "consumer_contract": {
            "purpose": "REFERENCE_STATE_POOL_ONLY",
            "not_a_video_call_plan": True,
            "video_compilation_mode": "entity_reference_sequence",
            "video_units_must_bind_reference_stills_by_timeline_segment": True,
            "video_units_may_reuse_approved_stills": True,
            "editorial_shot_count": sum(len(row["editorial_shot_ids"]) for row in coverage),
            "video_unit_count": len(coverage),
            "video_unit_count_source": "LEN_OF_VALIDATED_SEMANTIC_GROUPS",
            "video_unit_plan_required_before_image_submit": True,
            "video_unit_plan_required_before_video_submit": True,
            "planned_state_count": planned_state_count,
            "one_still_per_video_unit_forbidden": minimum_states > 1,
        },
        "tasks": tasks,
        "blocked_tasks": blocked_tasks,
    }
    batch_path.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "generate_new": len(tasks), "reuse_review": len(reuse)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
