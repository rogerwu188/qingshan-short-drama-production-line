#!/usr/bin/env python3
"""Build E32 U04's necessary second anchor: the separated spirit at the dark tower."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROD = ROOT / "workflow/claude_writer_agent/production/e32_claude_writer_v1_20260722"
SOURCE = PROD / "E32_IMAGE_BATCH_S01_SINGLE_SUBJECT_REPAIR_R2_HARVEST.json"
SOURCE_MANIFEST = PROD / "E32_IMAGE_BATCH_S01_SINGLE_SUBJECT_REPAIR_R2.json"
OUT = PROD / "E32_IMAGE_BATCH_U04_A2_SPIRIT_ARRIVAL_R1.json"
PROMPT = PROD / "image_prompts_performance_r3/E32-CW-U04-A2-SPIRIT-ARRIVAL-R1.txt"
SCRIPT_SHA = "2c7d194af236a50a2141fe59de83c0484d1ec3691637c1d26ca48f48b3ede24b"
SCENE = ROOT / "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    harvest = json.loads(SOURCE.read_text())
    row = next(item for item in harvest["results"] if "U04" in item["task_key"])
    a1 = Path(row["output_path"])
    source_action = (
        "动作目的：观众读懂皎兔的黑甲阴神已经与医馆内肉身完整分离，并跨过雨城抵达西市暗楼侦察；"
        "状态链终点：同一皎兔的黑甲阴神单独悬停在西市暗楼二层窗外，身体前倾收势，右手扶住湿窗框，"
        "视线穿过窗缝锁定室内目标；雨水沿黑甲向下流，窗框只在右手接触处受力；"
        "表情：冷峻、警觉、屏息观察；画面只允许一个皎兔阴神生命主体，医馆肉身已留在远处且不得同框，"
        "不得出现分身、第二个皎兔、路人、刺客、室内人物、倒影人或背景人脸。"
    )
    bindings = [
        {
            "role": "character", "entity_id": "jiaotu", "path": rel(a1), "sha256": sha(a1),
            "qa_status": "PASS", "qa_report": rel(SOURCE),
        },
        {
            "role": "scene", "entity_id": "E32-CW-S02", "path": rel(SCENE), "sha256": sha(SCENE),
            "qa_status": "PASS", "qa_report": "configs/series_continuity_asset_registry_20260712.json",
        },
    ]
    prompt = "\n".join([
        "《青山》E32 U04 第二状态锚，竖屏9:16，2K，电影级中国玄幻雨夜写实画面。",
        "@图片1只锁定皎兔的身份、黑色服装、身形和分离前连续性；本图只画分离后的黑甲阴神，不复制肉身。",
        "@图片2只锁定系列建筑质感；把空间改为洛城西市暗楼二层窗外的雨夜环境。",
        "构图：中近景侧面，黑甲阴神完整单人入画，刚结束高速跨城飞掠，脚不着地但身体有明确惯性收势；"
        "右手真实扶住湿木窗框，左手收在身侧，面部和眼睛清晰，窗内保持黑暗且无人。",
        "可见目的：观众一眼看懂阴神已经抵达暗楼并开始侦察，而不是仍在医馆原地分身。",
        "雨夜冷蓝主色，窗缝一线暖橙油灯光勾出脸部轮廓；雨丝方向统一，湿甲反光服从同一光源。",
        "禁止文字、字幕、水印、Logo、拼图、分镜框；禁止多人物、重复肢体、透明肉身、镜中人、瞬移残影。",
        "源动作（必须逐字绑定）：" + source_action,
    ]) + "\n"
    PROMPT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT.write_text(prompt)
    contract = {
        "schema": "qingshan.image_prompt_contract.v2", "shot_id": "E32-CW-U04-A2-R1",
        "source_script_sha256": SCRIPT_SHA, "source_action": source_action,
        "source_action_sha256": hashlib.sha256(source_action.encode()).hexdigest(),
        "visible_characters": ["jiaotu"], "reference_bindings": bindings,
        "editorial_shot_ids": ["E32-CW-S02-SH01", "E32-CW-S02-SH02"],
        "video_unit_id": "E32-CW-U04", "video_unit_duration_seconds": 14,
        "state_index": 2, "state_count": 2, "state_role": "spirit_arrival_end_anchor",
        "status": "PASS", "failures": [],
    }
    task = {
        "task_key": "E32-CW-U04-A2-SPIRIT-ARRIVAL-R1", "tool_type": "image_generation",
        "scene_id": "E32-CW-S02", "shot_id": "E32-CW-U04-A2-R1",
        "editorial_shot_ids": contract["editorial_shot_ids"], "video_unit_id": "E32-CW-U04",
        "video_unit_duration_seconds": 14, "state_index": 2, "state_count": 2,
        "beat_id": "E32-CW-U04-A2-R1", "prompt_file": rel(PROMPT), "prompt_sha256": sha(PROMPT),
        "reference_images": [item["path"] for item in bindings], "reference_bindings": bindings,
        "prompt_contract": contract, "model": "gpt-image-2-pro", "aspect_ratio": "9:16",
        "resolution": "2K", "status": "READY_FOR_PARALLEL_SUBMIT", "source_script_sha256": SCRIPT_SHA,
    }
    source_manifest = json.loads(SOURCE_MANIFEST.read_text())
    manifest = {
        "schema": source_manifest["schema"], "episode": "E32", "status": "READY_CHANGED_INPUT_SUPPLEMENT",
        "source_script_sha256": SCRIPT_SHA, "output_dir": "working_assets/e32_performance_stills_20260722/u04_a2_r1",
        "qa_dir": "qa/e32_performance_stills_20260722/u04_a2_r1",
        "machine_gate_reports": source_manifest["machine_gate_reports"], "tasks": [task],
    }
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"manifest": rel(OUT), "task": task["task_key"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
