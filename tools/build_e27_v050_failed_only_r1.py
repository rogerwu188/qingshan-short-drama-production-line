#!/usr/bin/env python3
"""Build the two-unit E27 v0.5 failed-only identity/text repair batch."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_CONFIG = ROOT / "configs/E27_remaining_11_entity_reference_sequence_v050_20260720.json"
OUT_CONFIG = ROOT / "configs/E27_v050_failed_only_identity_text_r1_20260721.json"
PROMPT_DIR = ROOT / "workflow/prompts/e27_v050_failed_only_identity_text_r1_20260721"
RECEIPT = ROOT / "workflow/tasks/E27_V050_FAILED_ONLY_IDENTITY_TEXT_R1_BUILD_RECEIPT_20260721.json"
IDENTITY_REF = ROOT / "ref_images/female_jiaotu_ref_20260703.jpg"
LOCAL_GENERATED = ROOT / "workflow/writer_agent/e27_agent_native_v050_20260721/runtime_provenance/e27.agent-native.generated.json"
LOCAL_COMPILED = ROOT / "workflow/writer_agent/e27_agent_native_v050_20260721/runtime_provenance/e27.agent-native.compiled.json"
TARGETS = {
    "E27-B02-U01-ENTITY-REFERENCE-V050": "IDENTITY",
    "E27-B05-U02-ENTITY-REFERENCE-V050": "TEXT_AND_IDENTITY",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def identity_repair(prompt: str) -> str:
    prompt = prompt.replace(
        "锁定场景[[scene_1]]=@图片1，",
        "锁定场景[[scene_1]]=@图片1；皎兔 canonical 女性身份参考=@图片2，@图片2只锁定性别、年龄、脸部身份与克制发冠轮廓，不复制其背景或非本场服装；",
    )
    prompt = prompt.replace(
        "保留女性面容与兔耳状光影轮廓",
        "保留与@图片2一致的女性面容；发冠两侧仅有两道低矮、克制、贴近发冠的淡蓝弧光，每道弧光低于头部高度，不连接成器官、头饰或实体兔耳",
    )
    prompt = prompt.replace(
        "女阴神以兔耳光弧框住",
        "与@图片2同一身份的女阴神以贴近发冠、低于头部高度的两道克制淡蓝弧光框住",
    )
    prompt += (
        "\n皎兔身份硬锁：本体与阴神必须是同一位成年女性、同一张脸、同一年龄带；"
        "兔形母题只能是贴近发冠的低矮淡蓝弧光，绝不生成实体兔耳、巨大兔耳、兔耳头饰、兔女郎造型、"
        "字面兔子、巨兔幻影或动物化面孔。\n"
    )
    return prompt


def text_repair(prompt: str) -> str:
    prompt = prompt.replace(
        "将最早一格时辰签贴到文书残影胸前",
        "将最早位置的纯色无字时辰签贴到文书残影胸前；该签仅以位置和颜色编码先后，表面没有汉字、数字、日期、印章文字或可辨字符",
    )
    prompt = prompt.replace(
        "落笔先亮，命气后灭",
        "无字笔迹区域先出现一粒抽象墨光，命气后灭；纸面始终失焦且不可读，不形成任何字形",
    )
    prompt += (
        "\n文字安全硬锁：所有拓片、时辰签、残页与纸张表面保持纯色、空白、失焦或只有非字符纹理；"
        "不得出现汉字、数字、日期、时辰文字、印章文字、伪字或类似字符的笔画组合。剧情中的先后关系只用位置、"
        "颜色、动作与口头对白表达。\n"
    )
    return prompt


def main() -> int:
    source = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    identity_sha = sha256(IDENTITY_REF)
    tasks = []
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for original in source["tasks"]:
        mode = TARGETS.get(original["task_key"])
        if not mode:
            continue
        task = json.loads(json.dumps(original))
        original_prompt = ROOT / task["prompt_file"]
        prompt = identity_repair(original_prompt.read_text(encoding="utf-8"))
        if mode == "TEXT_AND_IDENTITY":
            prompt = text_repair(prompt)
        base_key = task["task_key"]
        task["task_key"] = f"{base_key}-FAILED-ONLY-R1"
        task["source_id"] = f"{task['source_id']}::FAILED-ONLY-R1"
        task["variant_label"] = f"{task['variant_label']}-FAILED-ONLY-R1"
        prompt_path = PROMPT_DIR / f"{task['batch_id']}-{task['unit_id'].split('::')[-1]}-R1.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        task["prompt_file"] = str(prompt_path.relative_to(ROOT))
        task["prompt_sha256"] = sha256(prompt_path)
        identity_rel = str(IDENTITY_REF.relative_to(ROOT))
        if identity_rel not in task["reference_images"]:
            task["reference_images"].append(identity_rel)
        identity_slot = "IDENTITY::CHAR-皎兔-古装"
        if identity_slot not in task["required_slot_ids"]:
            task["required_slot_ids"].append(identity_slot)
        task["reference_assets"].append(
            {"slot_id": identity_slot, "path": identity_rel, "sha256": identity_sha}
        )
        task["status"] = "READY_FOR_FAILED_ONLY_R1_SUBMIT"
        task["repair_reason"] = mode
        task["credit_policy"] = "API_RETURNED_VALUE_ONLY; failed=0; successful_without_field=UNKNOWN"
        tasks.append(task)
    if len(tasks) != len(TARGETS):
        raise RuntimeError(f"target mismatch: built {len(tasks)} expected {len(TARGETS)}")
    payload = {
        "schema": "qingshan.episode_parallel_batch.config.v1",
        "episode": "E27",
        "status": "READY_FOR_FAILED_ONLY_PARALLEL_SUBMIT",
        "concurrency": len(tasks),
        "max_retries": 0,
        "output_dir": "working_assets/e27_v050_failed_only_identity_text_r1_20260721/candidates",
        "qa_dir": "qa/e27_v050_failed_only_identity_text_r1_20260721",
        "scene_contract_ref": source["scene_contract_ref"],
        "writer_agent_provenance": {
            **source["writer_agent_provenance"],
            "generated_script": str(LOCAL_GENERATED.relative_to(ROOT)),
            "generated_script_sha256": sha256(LOCAL_GENERATED),
            "compiled_script": str(LOCAL_COMPILED.relative_to(ROOT)),
            "compiled_script_sha256": sha256(LOCAL_COMPILED),
        },
        "base_batch_note": "Submit both independent failed-only repairs concurrently. Preserve every other accepted v0.5 unit and do not touch public platforms.",
        "tasks": tasks,
    }
    write_json(OUT_CONFIG, payload)
    write_json(
        RECEIPT,
        {
            "schema": "qingshan.e27.v050-failed-only-r1-build.v1",
            "episode": "E27",
            "recorded_at": datetime.now().astimezone().isoformat(),
            "status": "BUILT_PENDING_SHARED_PREFLIGHT_AND_PARALLEL_SUBMIT",
            "config": str(OUT_CONFIG),
            "config_sha256": sha256(OUT_CONFIG),
            "task_count": len(tasks),
            "task_keys": [task["task_key"] for task in tasks],
            "identity_reference": str(IDENTITY_REF),
            "identity_reference_sha256": identity_sha,
            "remote_credit": 0,
        },
    )
    print(json.dumps({"status": "PASS", "tasks": len(tasks), "config": str(OUT_CONFIG)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
