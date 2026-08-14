#!/usr/bin/env python3
"""Build C2+ still tasks so every video unit has ordered state anchors."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def load_json(value: str | Path) -> dict[str, Any]:
    return json.loads(resolve(value).read_text(encoding="utf-8"))


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def relative(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT))


def state_instruction(index: int, total: int) -> str:
    if index == total:
        return "动作或叙事结果已经明确落地，并为下一视频单元留下可连续衔接的最终状态"
    fraction = index / total
    return f"同一事件约推进到 {fraction:.0%}，主体位置、姿态、受力和环境介质相对 C1 已发生清晰可追踪变化"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--production-manifest", required=True)
    parser.add_argument("--base-batch", required=True)
    parser.add_argument("--base-harvest", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--batch-manifest", required=True)
    parser.add_argument("--gate-report", required=True)
    args = parser.parse_args()

    production = load_json(args.production_manifest)
    base_batch = load_json(args.base_batch)
    harvest = load_json(args.base_harvest)
    source_sha = production["source"]["script_sha256"]
    if base_batch.get("source_script_sha256") != source_sha:
        raise ValueError("base batch source SHA mismatch")
    if not harvest.get("all_completed"):
        raise ValueError("base C1 harvest is not complete")

    base_task_by_shot = {row["shot_id"]: row for row in base_batch.get("tasks") or []}
    harvest_by_key = {row["task_key"]: row for row in harvest.get("results") or []}
    policy = production.get("production_policy", {}).get("multi_state_reference_policy") or {}
    default_states = int(policy.get("minimum_states_per_video_unit", 2))
    action_states = int(policy.get("minimum_states_per_action_unit", 3))
    action_shots = set(policy.get("action_shot_ids") or [])

    out_dir = resolve(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tasks: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for shot in production.get("shots") or []:
        shot_id = shot["shot_id"]
        base_task = base_task_by_shot[shot_id]
        base_row = harvest_by_key[base_task["task_key"]]
        base_path = resolve(base_row["output_path"])
        if not base_path.is_file() or digest_file(base_path) != base_row.get("sha256"):
            raise ValueError(f"base C1 binding failed: {shot_id}")
        target = action_states if shot_id in action_shots else default_states
        coverage.append({
            "unit_id": shot_id,
            "target_state_count": target,
            "base_state": {"state_id": f"{shot_id}-C1", "path": relative(base_path), "sha256": base_row["sha256"]},
        })
        original_bindings = base_task["reference_bindings"]
        character_bindings = [row for row in original_bindings if row.get("role") == "character"]
        scene_binding = {
            "role": "scene",
            "entity_id": shot["scene_id"],
            "path": relative(base_path),
            "sha256": base_row["sha256"],
            "qa_status": "PASS",
            "qa_report": relative(resolve(args.base_harvest)),
        }
        bindings = [*character_bindings, scene_binding]
        for index in range(2, target + 1):
            state_id = f"{shot_id}-C{index}"
            instruction = state_instruction(index, target)
            prompt = (
                f"《青山》{production['episode']}《{production['title']}》多状态参考图 {state_id}。\n"
                f"锁源 SHA-256={source_sha}。\n"
                f"原始剧情动作只允许：{shot['action']}\n"
                f"本图是同一视频单元的 C{index}/{target}：{instruction}。\n"
                "@图片中的 C1 是同一地点、同一人物身份、同一服装与同一事件的起始权威锚；"
                "必须延续其空间轴线、光线、人物身份和服装，但不得复制 C1 姿态或只做轻微表情变化。\n"
                "必须呈现动作推进后的一个新决定性瞬间：人物重心、手脚位置、道具位置、接触结果或环境反应至少两项发生可见变化；"
                "不得跳到剧本以外的后续事件，不得新增人物、道具、对白或剧情结果。\n"
                "9:16 竖屏，2K，古装武侠玄幻写实电影感；禁止字幕、伪文字、水印、Logo、分屏、拼贴、分身、融合肢体、慢动作和静帧微动。\n"
            )
            prompt_path = out_dir / f"{state_id}.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            contract = {
                "schema": "qingshan.image_prompt_contract.v2",
                "shot_id": state_id,
                "source_script_sha256": source_sha,
                "source_action": shot["action"],
                "source_action_sha256": digest_bytes(shot["action"].encode("utf-8")),
                "visible_characters": shot.get("visible_characters") or [],
                "character_binding_mode": "EXPLICIT_VISIBLE_CHARACTERS",
                "reference_bindings": bindings,
                "state_role": "result_evidence" if index == target else "internal_action_state",
                "state_index": index,
                "state_count": target,
                "status": "PASS",
                "failures": [],
            }
            tasks.append({
                "task_key": f"{state_id}-STILL-V1",
                "tool_type": "image_generation",
                "scene_id": shot["scene_id"],
                "shot_id": state_id,
                "beat_id": shot_id,
                "prompt_file": relative(prompt_path),
                "prompt_sha256": digest_file(prompt_path),
                "reference_images": [row["path"] for row in bindings],
                "reference_bindings": bindings,
                "prompt_contract": contract,
                "model": "gpt-image-2-pro",
                "aspect_ratio": "9:16",
                "resolution": "2K",
                "status": "READY_FOR_PARALLEL_SUBMIT",
                "source_script_sha256": source_sha,
            })

    gate_path = resolve(args.gate_report)
    gate_path.parent.mkdir(parents=True, exist_ok=True)
    gate = {
        "schema": "qingshan.multi_state_still_coverage_gate.v1",
        "episode": production["episode"],
        "status": "PASS",
        "source_script_sha256": source_sha,
        "unit_count": len(coverage),
        "supplement_task_count": len(tasks),
        "policy": {
            "minimum_states_per_video_unit": default_states,
            "minimum_states_per_action_unit": action_states,
            "one_still_per_video_unit_forbidden": True,
        },
        "coverage": coverage,
    }
    gate_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    batch_path = resolve(args.batch_manifest)
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": production["episode"],
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "source_script_sha256": source_sha,
        "production_manifest_ref": args.production_manifest,
        "machine_gate_reports": [relative(gate_path)],
        "output_dir": f"working_assets/{production['episode'].lower()}_multistate_stills_v1/candidates",
        "qa_dir": f"qa/{production['episode'].lower()}_multistate_stills_v1",
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "consumer_contract": {
            "purpose": "ORDERED_MULTI_STATE_VIDEO_REFERENCE_POOL",
            "one_still_per_video_unit_forbidden": True,
            "video_units_must_bind_reference_image_sequence": True,
        },
        "tasks": tasks,
        "blocked_tasks": [],
    }
    batch_path.write_text(json.dumps(batch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "units": len(coverage), "supplement_tasks": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
