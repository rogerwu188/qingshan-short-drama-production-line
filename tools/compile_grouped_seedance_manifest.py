#!/usr/bin/env python3
"""Compile editorial Seedance rows into scene-local grouped video-unit preflight rows."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from tools.video_prompt_action_density_gate import validate_action_timeline
except ModuleNotFoundError:  # Direct CLI execution from tools/.
    from video_prompt_action_density_gate import validate_action_timeline


ROOT = Path(__file__).resolve().parents[1]


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def normalized_weather(value: object) -> str:
    return str(value or "").strip().upper()


def action_timeline(unit: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor = 0.0
    specs = unit["ordered_prompt_specs"]
    for index, spec in enumerate(specs):
        action = spec.get("action") or {}
        source_duration = float(action.get("t1_seconds", 0)) - float(action.get("t0_seconds", 0))
        end = round(cursor + source_duration, 3)
        if index == len(specs) - 1:
            end = float(unit["duration_seconds"])
        cast = [str(row.get("character")) for row in spec.get("cast") or [] if row.get("character")]
        props = [str(row.get("prop")) for row in spec.get("props") or [] if row.get("prop")]
        space = spec.get("space") or {}
        subject = "、".join(cast or props) or "场内物件"
        contact = "、".join(props) or str(space.get("subspace") or space.get("location") or "地面与空气")
        primary = str(action.get("primary_action") or action.get("start_state") or "").strip()
        terminal = str(action.get("completion_state") or primary).strip()
        rows.append({
            "start_seconds": cursor,
            "end_seconds": end,
            "actions": [
                f"主体={subject}；动作={primary}；接触点={contact}；方向=由起态连续走向所述结果；终态={terminal}"
            ],
            "state_change": f"{action.get('start_state') or primary} -> {terminal}",
            "action_budget_seconds": round(end - cursor, 3),
        })
        cursor = end
    return rows


def prompt_text(unit: dict[str, Any], memory_rules: list[dict[str, Any]]) -> str:
    specs = unit["ordered_prompt_specs"]
    first = specs[0]
    weather = normalized_weather((first.get("scene_state") or {}).get("weather"))
    dialogue = [str(spec.get("dialogue") or "").strip() for spec in specs if str(spec.get("dialogue") or "").strip()]
    lines = [
        f"【视频单元】{unit['unit_id']} scene={unit['scene_id']} duration={unit['duration_seconds']}s",
        "【模型硬合同】model=seedance-2.0-fast resolution=720p",
        f"【天气硬合同】weather={weather}",
        f"【空间层级】{json.dumps([spec.get('space') for spec in specs], ensure_ascii=False)}",
        f"【起始锚点】{json.dumps(unit['reference_images'], ensure_ascii=False)}",
        f"【连续动作轨迹】{json.dumps(unit['action_timeline'], ensure_ascii=False)}",
        f"【精确原生对白】{json.dumps(dialogue, ensure_ascii=False)}",
        "【同任务原生声场】上述对白、环境声、拟音、动作声必须由本次同一视频 task 原生生成并保留；禁止 TTS、旧 candidate、跨 task 音轨或默认 BGM 覆盖。无对白人物闭口；对白只说一次、不改词、不换说话人。",
        f"【逐节拍完整合同】{json.dumps(specs, ensure_ascii=False)}",
        "【禁止】静态帧、数字推拉替代表演、循环动作、噪声音轨、可读字幕与水印、人物身份漂移、漏拍或重排节拍。",
        "【历史失败防复犯绑定】rules=" + ",".join(str(row.get("id")) for row in memory_rules if row.get("id"))
        + "；完整规则由 batch config 中 generation_prompt_failure_memory_ref+SHA 锁定；本 prompt 已落实精确单次对白、说话人/闭口锁、全时段物理动作、身份/道具/空间连续性、禁静帧循环噪音与文字。",
    ]
    return "\n".join(lines) + "\n"


def write_preflight_artifacts(
    manifest: dict[str, Any], grouping_path: Path, prompt_dir: Path,
    scene_authority_path: Path, complete_path: Path, density_path: Path,
    dialogue_path: Path, failure_memory_path: Path, first_pass_policy_path: Path, config_path: Path,
    beat_sheet_path: Path, script_readiness_report_path: Path, script_density_source_path: Path,
    script_density_report_path: Path,
    directing_script_path: Path, generation_contract_path: Path, supervisor_report_path: Path,
) -> None:
    prompt_dir.mkdir(parents=True, exist_ok=True)
    scene_rows: list[dict[str, str]] = []
    seen_scenes: set[str] = set()
    prompt_rows: list[dict[str, Any]] = []
    density_rows: list[dict[str, Any]] = []
    dialogue_rows: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    dialogue_index = 0
    memory = load(failure_memory_path)
    memory_rules = memory.get("rules") or []
    known_failure_ids = [str(row["id"]) for row in memory_rules if row.get("id")]
    for unit in manifest["units"]:
        unit["action_timeline"] = action_timeline(unit)
        density = validate_action_timeline(unit["action_timeline"], unit["duration_seconds"], source_id=unit["unit_id"])
        density_rows.append(density)
        if density["status"] != "PASS":
            raise ValueError(";".join(density["failures"]))
        weather = normalized_weather((unit["ordered_prompt_specs"][0].get("scene_state") or {}).get("weather"))
        if unit["scene_id"] not in seen_scenes:
            seen_scenes.add(unit["scene_id"])
            scene_rows.append({"scene_id": unit["scene_id"], "weather": weather})
        prompt_path = prompt_dir / f"{unit['unit_id']}.txt"
        prompt_path.write_text(prompt_text(unit, memory_rules), encoding="utf-8")
        prompt_sha = digest(prompt_path)
        task_dialogue: list[dict[str, str]] = []
        for spec in unit["ordered_prompt_specs"]:
            raw = str(spec.get("dialogue") or "").strip()
            if not raw:
                continue
            dialogue_index += 1
            dia_id = f"{manifest['episode']}-DIA-{dialogue_index:03d}"
            speaker, separator, spoken_text = raw.partition("：")
            if not separator or not speaker.strip() or not spoken_text.strip():
                raise ValueError(f"{unit['unit_id']} dialogue must use speaker：text format: {raw}")
            task_dialogue.append({"dia_id": dia_id, "speaker": speaker.strip(), "spoken_text": spoken_text.strip()})
            dialogue_rows.append({
                "dia_id": dia_id, "video_unit_id": unit["unit_id"], "speaker": speaker.strip(),
                "spoken_text": spoken_text.strip(), "status": "PASS",
                "audio_mode": "RIGHTS_CLEARED_MODEL_NATIVE_TEXT_ONLY",
                "rights_cleared_model_native": True, "external_voice_reference": False,
                "unverified_clone_prohibited": True, "path": None, "remote_asset_id": None,
                "same_video_task_native_audio_required": True,
            })
        prompt_rows.append({
            "unit_id": unit["unit_id"], "scene_id": unit["scene_id"], "weather": weather,
            "prompt_path": relative(prompt_path), "prompt_sha256": prompt_sha,
        })
        tasks.append({
            "task_key": f"{unit['unit_id']}-VIDEO-A1", "unit_id": unit["unit_id"],
            "tool_type": "video_generation", "model": "seedance-2.0-fast", "resolution": "720p",
            "prompt_file": relative(prompt_path), "prompt_sha256": prompt_sha,
            "dialogue": task_dialogue, "native_dialogue_required": bool(task_dialogue),
            "visual_tier": "CORE", "minimum_score_100": 80.0,
            "prompt_failure_modes_applied": known_failure_ids,
            "prompt_failure_modes_not_applicable": [],
            "provider_post_allowed": False, "remote_task_id": None, "paid_attempt": 0,
        })
    scene_authority_path.parent.mkdir(parents=True, exist_ok=True)
    complete_path.parent.mkdir(parents=True, exist_ok=True)
    density_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    scene_authority_path.write_text(json.dumps({
        "schema": "qingshan.scene_state_authority.v1", "episode": manifest["episode"], "scene_state": scene_rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    complete_path.write_text(json.dumps({
        "schema": "qingshan.complete_video_prompt_manifest.v1", "episode": manifest["episode"],
        "status": "PASS", "unit_count": len(prompt_rows), "all_units_have_prompt": True,
        "source_plan": relative(grouping_path), "source_plan_sha256": digest(grouping_path),
        "source_scene_authority": relative(scene_authority_path),
        "source_scene_authority_sha256": digest(scene_authority_path), "rows": prompt_rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    density_path.write_text(json.dumps({
        "schema": "qingshan.video_prompt_action_density_batch.v1", "episode": manifest["episode"],
        "status": "PASS", "unit_count": len(density_rows), "results": density_rows, "failures": [],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    dialogue_path.parent.mkdir(parents=True, exist_ok=True)
    dialogue_path.write_text(json.dumps({
        "schema": "qingshan.dialogue_manifest.v1", "episode": manifest["episode"],
        "status": "PASS", "line_count": len(dialogue_rows), "rows": dialogue_rows,
        "audio_policy": "RIGHTS_CLEARED_MODEL_NATIVE_TEXT_ONLY_SAME_VIDEO_TASK_NO_EXTERNAL_REFERENCE",
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config_path.write_text(json.dumps({
        "schema": "qingshan.episode_parallel_batch.config.v1", "episode": manifest["episode"],
        "status": "PREFLIGHT_ONLY_NO_PROVIDER_POST", "complete_video_prompt_manifest_ref": relative(complete_path),
        "scene_contract_ref": relative(scene_authority_path), "dialogue_manifest_ref": relative(dialogue_path),
        "generation_first_pass_policy_ref": relative(first_pass_policy_path),
        "generation_first_pass_policy_sha256": digest(first_pass_policy_path),
        "generation_prompt_failure_memory_ref": relative(failure_memory_path),
        "generation_prompt_failure_memory_sha256": digest(failure_memory_path),
        "script_gate": {
            "beat_sheet": relative(beat_sheet_path),
            "report": relative(script_readiness_report_path),
        },
        "script_density_gate": {
            "script": relative(script_density_source_path),
            "review": relative(script_density_report_path),
            "episode": manifest["episode"],
        },
        "writer_agent_provenance": {
            "generated_script": relative(directing_script_path),
            "compiled_script": relative(generation_contract_path),
        },
        "supervisor_script_gate_report": relative(supervisor_report_path),
        "tasks": tasks,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compile_manifest(grouping: dict[str, Any], anchors: dict[str, Any], editorial: dict[str, Any]) -> dict[str, Any]:
    anchor_by_unit = {row["unit_id"]: row for row in anchors.get("units") or []}
    shot_by_id = {row["shot_id"]: row for row in editorial.get("shots") or []}
    units: list[dict[str, Any]] = []
    for unit in grouping.get("units") or []:
        unit_id = unit["unit_id"]
        anchor = anchor_by_unit.get(unit_id)
        if not anchor:
            raise ValueError(f"{unit_id} missing anchor decision")
        paths = anchor.get("reference_image_paths") or []
        if len(paths) != int(anchor.get("planned_reference_image_count", -1)):
            raise ValueError(f"{unit_id} anchor count mismatch")
        roles = (anchor.get("anchor_count_decision") or {}).get("anchor_roles") or []
        if len(roles) != len(paths):
            raise ValueError(f"{unit_id} anchor role count mismatch")
        transport = str(anchor.get("reference_transport_strategy") or "")
        if transport not in {"IMAGE_TO_VIDEO_EXACT_FIRST_FRAME", "OMNI_MULTI_REFERENCE"}:
            raise ValueError(f"{unit_id} unsupported reference transport strategy: {transport}")
        references = []
        for value, role in zip(paths, roles):
            path = resolve(value)
            if not path.is_file():
                raise ValueError(f"{unit_id} anchor missing: {value}")
            references.append({"path": value, "sha256": digest(path), "role": role})
        shots = [shot_by_id[shot_id] for shot_id in unit["editorial_shot_ids"]]
        if any(row.get("model") != "seedance-2.0-fast" for row in shots):
            raise ValueError(f"{unit_id} contains forbidden model")
        if any(row.get("resolution") != "720p" for row in shots):
            raise ValueError(f"{unit_id} contains forbidden resolution")
        prompt_specs = [row.get("prompt_spec") or {} for row in shots]
        units.append({
            "unit_id": unit_id,
            "scene_id": unit["scene_id"],
            "duration_seconds": unit["duration_seconds"],
            "model": "seedance-2.0-fast",
            "resolution": "720p",
            "editorial_shot_ids": unit["editorial_shot_ids"],
            "narrative_beat": unit["narrative_beat"],
            "reference_images": references,
            "reference_transport_strategy": transport,
            "semantic_reference_coverage_gate": anchor.get("semantic_reference_coverage_gate"),
            "ordered_prompt_specs": prompt_specs,
            "native_audio_contract": "SAME_VIDEO_TASK_NATIVE_DIALOGUE_AMBIENCE_FOLEY_ACTION_SOUND",
            "submission_status": "NOT_AUTHORIZED_UNTIL_REGISTERED_GROUPED_PREFLIGHT_PASS",
            "paid_attempt": 0,
            "remote_task_id": None,
        })
    if len(units) != int(grouping.get("video_unit_count", -1)):
        raise ValueError("compiled unit count mismatch")
    runtime = round(sum(float(row["duration_seconds"]) for row in units), 6)
    if runtime != round(float(grouping.get("runtime_seconds", -1)), 6):
        raise ValueError("compiled runtime mismatch")
    return {
        "schema": "qingshan.grouped_seedance_manifest.v1",
        "episode": grouping.get("episode"),
        "video_unit_count": len(units),
        "runtime_seconds": runtime,
        "grouping_plan_sha256": None,
        "anchor_plan_sha256": None,
        "editorial_seedance_manifest_sha256": None,
        "units": units,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--grouping-plan", type=Path, required=True)
    parser.add_argument("--anchor-plan", type=Path, required=True)
    parser.add_argument("--editorial-seedance-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prompt-dir", type=Path)
    parser.add_argument("--scene-authority", type=Path)
    parser.add_argument("--complete-prompt-manifest", type=Path)
    parser.add_argument("--action-density-report", type=Path)
    parser.add_argument("--dialogue-manifest", type=Path)
    parser.add_argument("--failure-memory", type=Path)
    parser.add_argument("--first-pass-policy", type=Path)
    parser.add_argument("--batch-config", type=Path)
    parser.add_argument("--beat-sheet", type=Path)
    parser.add_argument("--script-readiness-report", type=Path)
    parser.add_argument("--script-density-source", type=Path)
    parser.add_argument("--script-density-report", type=Path)
    parser.add_argument("--directing-script", type=Path)
    parser.add_argument("--generation-contract", type=Path)
    parser.add_argument("--supervisor-report", type=Path)
    args = parser.parse_args()
    result = compile_manifest(load(args.grouping_plan), load(args.anchor_plan), load(args.editorial_seedance_manifest))
    result["grouping_plan_sha256"] = digest(args.grouping_plan)
    result["anchor_plan_sha256"] = digest(args.anchor_plan)
    result["editorial_seedance_manifest_sha256"] = digest(args.editorial_seedance_manifest)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    extras = (
        args.prompt_dir, args.scene_authority, args.complete_prompt_manifest, args.action_density_report,
        args.dialogue_manifest, args.failure_memory, args.first_pass_policy, args.batch_config,
        args.beat_sheet, args.script_readiness_report, args.script_density_source, args.script_density_report,
        args.directing_script, args.generation_contract, args.supervisor_report,
    )
    if any(extras) and not all(extras):
        parser.error("all grouped preflight output arguments must be supplied together")
    if all(extras):
        write_preflight_artifacts(
            result, args.grouping_plan, args.prompt_dir, args.scene_authority,
            args.complete_prompt_manifest, args.action_density_report, args.dialogue_manifest,
            args.failure_memory, args.first_pass_policy, args.batch_config,
            args.beat_sheet, args.script_readiness_report, args.script_density_source, args.script_density_report,
            args.directing_script, args.generation_contract, args.supervisor_report,
        )
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "units": len(result["units"]), "runtime_seconds": result["runtime_seconds"], "out": str(args.out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
