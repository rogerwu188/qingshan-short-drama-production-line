#!/usr/bin/env python3
"""Build a failed-only retry batch with an OCR-safe prompt amendment."""

import argparse
import json
from copy import deepcopy
from pathlib import Path


OCR_SAFE_AMENDMENT = """

【失败项定点修复：OCR-safe 视觉表面硬约束】
本次只修复画面伪文字，不改变剧情、人物、对白、动作因果、场景、时段、天气、景别签名或时长。
所有入镜服装、护腕、腰带、墙面、门窗、柜体、器皿、箱匣和道具表面必须是低对比度纯色素面：无刺绣、无回纹、无边饰、无符号、无数字、无字母、无书法状笔画、无规则竖横线阵列。
任何账册、名册、卷宗、官文或纸张只允许以下状态之一：合拢并以无字纯色封皮背向镜头；只露纸边；被手掌完全遮住；处于强景深虚化。禁止展示正面纸页、封签、标签、印章文字、牌匾、门楣或招幌。
剧情中的文书信息只通过人物拿取位置、不同纯色封皮、断裂的无字蜡封、手势、反应和同步对白交付；画面内绝不出现可读文字或类似文字的纹理。
构图优先人物脸、手部动作、空间关系与环境力量，镜头主动避开所有可能形成文字的平面。禁止字幕、标题、气泡、片头片尾、水印、Logo、UI、随机字符和伪文字。
""".strip()

SILENT_VISUAL_AMENDMENT = """

【无对白纯视觉替换源】
本次只生成供 AgentCut 替换的干净视觉层；原生对白音轨由已准入源复用。全程无人开口、无人做说话口型、不生成语音、不生成字幕。
画面中完全不出现打开的书、纸页、卷宗正面、封签标签或任何带框竖条；文书线索统一替换成无字纯色布包、无纹样蜡块、空手指向与人物反应。所有书册只能在远景货架上以无字书脊虚焦掠过，任何镜头不得推近。
忽略上文中所有要求人物说出台词、展示纸面内容、展示封签或书册正面的句子；只保留人物身份、场景、动作因果、机位、景别、天气、时段与时长。
""".strip()

MOTION_REPAIR_AMENDMENT = """

【短冻结失败项定点修复】
全片保持连续可感运动：人物呼吸、衣摆、视线、手部、火焰、尘粒与摄影机至少一项持续自然变化。禁止定格、静帧复制、暂停动作、0.5秒以上近似重复帧、慢动作拖帧或以空镜停顿凑时长。动作按因果完整推进，仍保持原剧情和原时长。
""".strip()

NO_MOON_AMENDMENT = """

【剧本时空硬约束】
夜景只允许室内烛火、灯笼或无天体的暗色环境光；画面绝不出现月亮、月牙、月光、月形符号、天空发光圆盘或月色光束。不得以任何图标、法术轨迹或窗外景物变相加入月形元素。
""".strip()

SILENT_VISUAL_TEXT_PROP_REWRITES = (
    ("密谍司持搜查令围太平医馆,限时交出陈迹。", "密谍司兵持纯黑无纹金属块围住太平医馆，逼迫交人。"),
    ("搜查令", "纯黑无纹金属块"),
    ("送令兵", "密谍司兵"),
    ("拍令", "将纯黑无纹金属块拍在桌上"),
    ("夺令", "夺走纯黑无纹金属块"),
    ("官印", "无纹样暗红蜡块"),
    ("真印", "真证物"),
    ("假令", "假证物"),
    ("药账", "合拢的纯色布包"),
    ("账册", "合拢的纯色布包"),
    ("药柜", "无抽屉无标签的素面封闭木柜"),
    ("账柜", "无抽屉无标签的素面封闭木柜"),
    ("批号未启用对照", "众人围住桌案"),
    ("普通话口型清晰", "人物表情与动作清晰"),
)


def build_retry(config_path, receipt_path, output_path, prompt_dir, suffix, silent_visual=False, drop_references=False, selected_task_keys=None, motion_repair=False, forbid_moon=False):
    config = json.loads(Path(config_path).read_text())
    receipt = json.loads(Path(receipt_path).read_text())
    failed = set(selected_task_keys or []) or {
        item.get("task_key")
        for item in receipt.get("tasks", [])
        if item.get("status") != "qa_pass"
    }
    by_key = {item.get("task_key"): item for item in config.get("tasks", [])}
    missing = sorted(key for key in failed if key not in by_key)
    if missing:
        raise ValueError(f"failed task keys missing from config: {missing}")

    prompt_dir = Path(prompt_dir)
    prompt_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    for key in sorted(failed):
        task = deepcopy(by_key[key])
        new_key = f"{key}-{suffix}"
        source_prompt = Path(task["prompt_file"])
        source_text = source_prompt.read_text().rstrip()
        if silent_visual:
            kept = []
            for line in source_text.splitlines():
                if line.startswith("角色") and "说：" in line:
                    continue
                if "对白只作为同步语音与口型指令" in line:
                    kept.append("本次不生成对白、说话口型、语音或字幕；只生成动作连续的干净视觉替换源。")
                    continue
                kept.append(line)
            source_text = "\n".join(kept)
            for risky_term, visual_substitute in SILENT_VISUAL_TEXT_PROP_REWRITES:
                source_text = source_text.replace(risky_term, visual_substitute)
        prompt_text = source_text + "\n\n" + OCR_SAFE_AMENDMENT
        if silent_visual:
            prompt_text += "\n\n" + SILENT_VISUAL_AMENDMENT
        if motion_repair:
            prompt_text += "\n\n" + MOTION_REPAIR_AMENDMENT
        if forbid_moon:
            prompt_text += "\n\n" + NO_MOON_AMENDMENT
        prompt_text += "\n"
        prompt_path = prompt_dir / f"{new_key}.txt"
        prompt_path.write_text(prompt_text)
        task["task_key"] = new_key
        task["prompt_file"] = str(prompt_path)
        task["status"] = "READY_FOR_PARALLEL_SUBMIT"
        if drop_references:
            task["reference_images"] = []
        metadata = task.setdefault("metadata", {})
        metadata["retry_of_task_key"] = key
        metadata["retry_reason"] = "REPEATED_OCR_FAILURE_OBJECT_FREE_SURFACE_REWRITE"
        metadata["preserve_story_and_dialogue"] = True
        metadata["ocr_safe_amendment"] = "PLAIN_SURFACES_NO_DRAWERS_NO_LABELS_EDGE_ON_CLOSED_DOCUMENTS_NO_GLYPHLIKE_TEXTURE"
        metadata["silent_visual_replacement"] = silent_visual
        metadata["reuse_admitted_dialogue_audio_in_agentcut"] = silent_visual
        metadata["generation_references_dropped"] = drop_references
        metadata["motion_freeze_repair"] = motion_repair
        metadata["forbid_moon_repair"] = forbid_moon
        tasks.append(task)

    out = deepcopy(config)
    out["status"] = "READY_TO_SUBMIT_FAILED_ONLY_OCR_SAFE"
    out["parallel_submission"] = True
    out["concurrency"] = len(tasks)
    out["max_retries"] = 0
    out["retry_of"] = str(receipt_path)
    out["base_batch_note"] = "Preserve every passing sibling; retry only repeated OCR failures with story-preserving plain-surface prompts."
    out["tasks"] = tasks
    Path(output_path).write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    return {"status": "PASS", "episode": out.get("episode"), "retry_task_count": len(tasks), "output": str(output_path)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--prompt-dir", required=True)
    parser.add_argument("--suffix", default="OCR-SAFE-R3")
    parser.add_argument("--silent-visual", action="store_true")
    parser.add_argument("--drop-references", action="store_true")
    parser.add_argument("--task-key", action="append")
    parser.add_argument("--motion-repair", action="store_true")
    parser.add_argument("--forbid-moon", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build_retry(args.config, args.receipt, args.out, args.prompt_dir, args.suffix, args.silent_visual, args.drop_references, args.task_key, args.motion_repair, args.forbid_moon), ensure_ascii=False))


if __name__ == "__main__":
    main()
