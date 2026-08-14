#!/usr/bin/env python3
"""Materialize successor image anchors as soon as their real A1 dependency completes."""

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


def relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(resolved)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_release_manifest(
    source: dict[str, Any], harvest: dict[str, Any], prompt_dir: Path
) -> dict[str, Any]:
    completed = {
        row["task_key"]: row
        for row in harvest.get("results", [])
        if row.get("remote_status") == "completed" and row.get("output_path")
    }
    source_tasks = {row["task_key"]: row for row in source.get("tasks", [])}
    released: list[dict[str, Any]] = []
    waiting: list[str] = []
    prompt_dir.mkdir(parents=True, exist_ok=True)

    for spec in source.get("dependent_anchor_specs", []):
        dependency_key = spec["depends_on_task_key"]
        dependency = completed.get(dependency_key)
        if dependency is None:
            waiting.append(spec["task_key"])
            continue
        base = source_tasks[dependency_key]
        a1_path = resolve(dependency["output_path"])
        if not a1_path.is_file() or sha256(a1_path) != dependency.get("sha256"):
            raise ValueError(f"{dependency_key} completed output is missing or SHA-mismatched")

        source_action = spec["source_action"]
        continuity_mode = spec.get("continuity_mode", "SAME_LOCATION_TERMINAL_REANCHOR")
        continuity_instruction = (
            "第一张参考图只锁人物身份、服装和动作起点。该动作包含剧本明确的跨地点运动，允许切换到终点场景和新机位；不得把起点肉身错误复制到终点。"
            if continuity_mode == "CROSS_LOCATION_IDENTITY_REANCHOR"
            else "第一张参考图锁同一人物、服装、机位、场景、道具归属和屏幕方向；不得另起构图或重新选角。"
        )
        prompt = f"""竖屏 9:16，电影级中国古装玄幻短剧，真实人物、真实接触、真实受力，禁止现代物件。

第一张参考图是 {spec['video_unit_id']} 已完成的真实 A1 锚。{continuity_instruction}

这是动作设计证明必需的后继锚 A{spec['state_index']}/{spec['state_count']}，状态职责为 {spec['state_role']}。终态画面：{spec['terminal_description']}
同源动作规格：{source_action}

只把 A1 沿同源动作的起势、接触、传力、结果推进到上述单一终态，不添加链外动作。主体位移只能由明确受力产生；禁止新增或删除人物、身份交换、道具瞬移、无因转身、腾空或碰撞、机位反打、拼贴、多格分镜、可读文字、伪文字、字幕、水印、标志和界面。
"""
        prompt_path = prompt_dir / f"{spec['task_key']}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        continuity_binding = {
            "role": "continuity_anchor",
            "entity_id": f"{spec['video_unit_id']}-A1-COMPLETED",
            "path": relative(a1_path),
            "sha256": sha256(a1_path),
            "qa_status": "PASS",
            "qa_report": source.get("harvest_report_ref", "DEPENDENCY_COMPLETION_RECEIPT"),
        }
        base_bindings = list(base["reference_bindings"])
        if continuity_mode == "CROSS_LOCATION_IDENTITY_REANCHOR":
            destination_path = resolve(spec["destination_scene_reference"])
            if not destination_path.is_file():
                raise ValueError(f"Missing destination scene reference: {destination_path}")
            base_bindings = [row for row in base_bindings if row.get("role") != "scene"]
            base_bindings.append({
                "role": "destination_scene",
                "entity_id": spec["destination_scene_id"],
                "path": relative(destination_path),
                "sha256": sha256(destination_path),
                "qa_status": "PASS",
                "qa_report": "AUTHORED_DESTINATION_SPACE_REFERENCE",
            })
        bindings = [continuity_binding, *base_bindings]
        shot_id = f"{spec['video_unit_id']}-A{spec['state_index']}"
        contract = {
            **base["prompt_contract"],
            "shot_id": shot_id,
            "source_action": source_action,
            "source_action_sha256": text_sha(source_action),
            "reference_bindings": bindings,
            "state_index": spec["state_index"],
            "state_count": spec["state_count"],
            "state_role": spec["state_role"],
            "continuity_anchor_is_first_real_reference": True,
            "status": "PASS",
            "failures": [],
            "spatial_continuity": {
                "mode": "CROSS_SPACE_TRANSITION" if continuity_mode == "CROSS_LOCATION_IDENTITY_REANCHOR" else "SAME_SPACE_CONTINUOUS",
                "policy_source": "PER_UNIT_SCRIPT_CONTENT",
                "origin_scene_id": spec.get("origin_scene_id", base.get("scene_id")),
                "destination_scene_id": spec.get("destination_scene_id", base.get("scene_id")),
                "anchor_scope": "DESTINATION_REANCHOR" if continuity_mode == "CROSS_LOCATION_IDENTITY_REANCHOR" else "SAME_SPACE_TERMINAL_REANCHOR",
                "camera_policy": "ALLOW_AUTHORED_DESTINATION_CAMERA" if continuity_mode == "CROSS_LOCATION_IDENTITY_REANCHOR" else "PRESERVE_AXIS_ONLY_WHEN_REQUIRED_BY_ACTION",
            },
        }
        released.append({
            **base,
            "task_key": spec["task_key"],
            "shot_id": shot_id,
            "state_index": spec["state_index"],
            "state_count": spec["state_count"],
            "prompt_file": relative(prompt_path),
            "prompt_sha256": sha256(prompt_path),
            "reference_images": [row["path"] for row in bindings],
            "reference_bindings": bindings,
            "prompt_contract": contract,
            "status": "READY_FOR_PARALLEL_SUBMIT",
            "depends_on_task_key": dependency_key,
            "dependency_output_sha256": dependency["sha256"],
            "continuity_mode": continuity_mode,
        })

    return {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": source.get("episode"),
        "status": "READY_TO_SUBMIT_CONCURRENTLY" if released else "WAITING_FOR_DEPENDENCIES",
        "source_script_sha256": source.get("source_script_sha256"),
        "machine_gate_reports": source.get("machine_gate_reports", []),
        "output_dir": source.get("output_dir"),
        "qa_dir": source.get("qa_dir"),
        "retry_policy": source.get("retry_policy"),
        "consumer_contract": {
            "purpose": "DEPENDENT_SUCCESSOR_ANCHORS",
            "release_policy": "EACH_DEPENDENT_ANCHOR_RELEASES_IMMEDIATELY_WHEN_ITS_OWN_A1_COMPLETES",
            "released_count": len(released),
            "waiting_count": len(waiting),
            "continuity_anchor_is_first_real_reference": True,
        },
        "blocked_tasks": waiting,
        "tasks": released,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--harvest", required=True)
    parser.add_argument("--prompt-dir", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    source_path = resolve(args.source_manifest)
    harvest_path = resolve(args.harvest)
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["harvest_report_ref"] = relative(harvest_path)
    payload = build_release_manifest(source, json.loads(harvest_path.read_text(encoding="utf-8")), resolve(args.prompt_dir))
    write_json(resolve(args.out), payload)
    print(json.dumps({"status": payload["status"], "released": len(payload["tasks"]), "waiting": len(payload["blocked_tasks"])}, ensure_ascii=False))
    return 0 if payload["tasks"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
