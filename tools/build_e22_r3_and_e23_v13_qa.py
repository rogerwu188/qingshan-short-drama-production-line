#!/usr/bin/env python3
"""Build failed-only E22 retries and the E23 V13 parallel final-QA batch."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def build_e22() -> Path:
    base_path = ROOT / "configs/E22_standard_storyboard_rework_r2_textsafe_20260719.json"
    out_path = ROOT / "configs/E22_standard_storyboard_rework_r3_b05_b06_object_free_20260719.json"
    prompt_dir = ROOT / "workflow/prompts/e22_standard_storyboard_rework_r3_b05_b06_object_free_20260719"
    config = json.loads(base_path.read_text(encoding="utf-8"))
    prompts = {
        "B05": """这是《青山》E22 B05 的 Seedance 2.0 纯视觉动作母版。场景严格为 Buddhist hall 室内，clear afternoon，暖色自然日光从格窗侧面进入。以参考图人物身份、脸、服装、左右轴线和室内空间为唯一视觉锚点。禁止夜景、月亮、月光、雨、雾和改换地点。

本段只表现：白鲤把三件没有文字的证物依次放到素面木桌上，陈迹观察三件证物的材质差异后迅速看穿有人在向三方投喂假证据，云妃从镇定转为警觉。三件证物只能是素色布片、封闭小盒和无字药包，禁止纸张、书页、账册、签名、牌匾、佛幡、经文、墙字、印章、数字或任何文字载体。

15 秒六镜头：室内三人中景建立位置；白鲤依次放下三件素面证物；陈迹视线在三物之间快速移动；云妃反应近景；陈迹把三物推成一线形成推理；三人形成新的对峙关系收束。无对白、无人声、无口型台词，只保留脚步、衣料、木桌轻响和室内环境声，后续 AgentCut 复用已通过对白音轨。

写实美剧式古装悬疑短剧，动作原生速度，镜头由动作和新信息驱动。禁止慢动作、静止补时、循环、分身、额外肢体、穿模和身份漂移。画面上中下全程禁止字幕、标题、可读文字、伪文字、数字、字母、水印、Logo和背景音乐；所有背景和道具必须为无图案素面材质。
""",
        "B06": """这是《青山》E22 B06 的 Seedance 2.0 纯视觉动作母版。场景严格为 Buddhist hall 室内，clear afternoon，暖色自然日光从格窗侧面进入。以参考图人物身份、脸、服装、左右轴线和室内空间为唯一视觉锚点。禁止夜景、月亮、月光、雨、雾和改换地点。

本段只表现：陈迹确认三方都被同一只更高层的手操纵。他把三件没有文字的素面证物分别推向三个方向，再把它们重新汇聚到桌心；白鲤与云妃沿着他的手势意识到幕后者另有其人。不要出现密谍司文字、官文、书信、书页、账册、地图、牌匾、佛幡、经文、墙字、印章、数字或任何文字载体。

15 秒六镜头：陈迹俯视桌面三件素面证物；三物被推向三个方向；白鲤跟随动作观察；云妃警觉回望门外但镜头不拍门楣；陈迹将三物重新汇聚到桌心；三人同时抬眼看向同一画外方向，以发现更高层幕后者的反应结束。无对白、无人声、无口型台词，只保留手掌、木桌、衣料和室内环境声，后续 AgentCut 复用已通过对白音轨。

写实美剧式古装悬疑短剧，动作原生速度，镜头由动作和新信息驱动。禁止慢动作、静止补时、循环、分身、额外肢体、穿模和身份漂移。画面上中下全程禁止字幕、标题、可读文字、伪文字、数字、字母、水印、Logo和背景音乐；所有背景和道具必须为无图案素面材质。
""",
    }
    prompt_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for source in config["tasks"]:
        beat = source.get("source_id")
        if beat not in prompts:
            continue
        prompt_path = prompt_dir / f"E22-{beat}-STANDARD-STORYBOARD-V1-R3-OBJECT-FREE.txt"
        prompt_path.write_text(prompts[beat], encoding="utf-8")
        task = dict(source)
        task.update({
            "task_key": f"E22-{beat}-STANDARD-STORYBOARD-V1-R3-OBJECT-FREE",
            "prompt_file": str(prompt_path.relative_to(ROOT)),
            "metadata": dict(source.get("metadata") or {}, retry_reason="persistent generated text; visual-only object-free failed-item retry"),
        })
        tasks.append(task)
    config.update({
        "max_retries": 0,
        "base_batch_note": "Failed-only R3 for B05/B06; preserve B01/B02/B03/B04 passes.",
        "output_dir": "working_assets/e22_standard_storyboard_rework_r3_b05_b06_object_free_20260719/candidates",
        "qa_dir": "qa/e22_standard_storyboard_rework_r3_b05_b06_object_free_20260719",
        "tasks": tasks,
    })
    out_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def build_e23() -> Path:
    base_path = ROOT / "configs/E23_agentcut_v2_parallel_qa_20260719.json"
    out_path = ROOT / "configs/E23_agentcut_v13_standard_storyboard_parallel_qa_20260719.json"
    config = json.loads(base_path.read_text(encoding="utf-8"))
    old_project = "configs/e23_agentcut_project_v2_v4_135s_20260719.json"
    new_project = "configs/e23_agentcut_project_v13_standard_storyboard_coverage_20260719.json"
    old_video = "exports/e23/agentcut_v2_v4_135s_20260719/E23_AGENTCUT_V2_V4_135S_NOT_FINAL.mp4"
    new_video = "exports/e23/agentcut_v13_standard_storyboard_coverage_20260719/E23_AGENTCUT_V13_STANDARD_STORYBOARD_COVERAGE_NOT_FINAL.mp4"
    old_qa = "qa/e23_agentcut_v2_v4_135s_20260719"
    new_qa = "qa/e23_agentcut_v13_standard_storyboard_coverage_20260719"
    config["output_dir"] = new_qa
    config["qa_dir"] = new_qa
    for task in config["tasks"]:
        task["task_key"] = task["task_key"].replace("V2", "V13")
        if task.get("project"):
            task["project"] = task["project"].replace(old_project, new_project)
        if task.get("video"):
            task["video"] = task["video"].replace(old_video, new_video)
        if task.get("report"):
            task["report"] = task["report"].replace(old_qa, new_qa)
        if task.get("command"):
            task["command"] = [part.replace(old_project, new_project).replace(old_video, new_video).replace(old_qa, new_qa) for part in task["command"]]
    out_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out_path


def main() -> int:
    print(json.dumps({"status": "PASS", "e22": str(build_e22()), "e23": str(build_e23())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
