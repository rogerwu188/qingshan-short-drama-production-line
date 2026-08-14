#!/usr/bin/env python3
"""Build the E27 Writer Agent still failed-only R1 batch from real visual QA."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
SOURCE = ROOT / "workflow/writer_agent/e27_agent_native_v020_20260720/production/image_batch.json"
REPORT = ROOT / "qa/e27_writer_agent_stills_v1_ai_review_20260720/E27_WRITER_AGENT_24_STILL_AI_REVIEW_RESULT_V080_CODEX_VISION_V3.json"
DEST = ROOT / "workflow/writer_agent/e27_agent_native_v020_20260720/production/retry_r1"
FAILED = {
    "E27-N01": "动作硬修：假搜查令必须平贴诊案且刚被重重拍下，纸边受冲击微翘，不得被举起或挥动；后景明确显示至少十一名彼此轮廓分离的铁甲兵，十一把刀锋同时朝诊案压入，不得粘连成模糊人团。",
    "E27-N04": "动作硬修：画面锁在冰流沿刀刃抵达朱红官印、无字印面从中心放射裂开的同一瞬间；陈迹指尖已把一枚无字碎角弹向领头兵胸甲。官印、纸张、药柜和全部器物表面必须纯净无字、无印文、无符号、无伪字。",
    "E27-N05": "文字硬修：左侧前景柱、墙、门牌和所有器物必须是纯木纹或纯石纹，彻底移除牌匾、书法、刻痕、字符、符号和伪字；保持皎兔女性阴神半身离体与兔耳光弧。",
    "E27-N08": "场景硬修：干燥晴夜巷道，石板必须哑光干燥、无水迹、无反光湿面、无雨；陈迹正用双手系紧夜行衣腕口。残页折叠藏入腰带，仅露无字纸角；全部纸面、墙面、门牌纯净无字无符号。",
    "E27-N09": "动作硬修：女阴神半身穿过带青铜锁的柜门，透明手指明确指向自上而下第三层唯一空槽；空槽旁刚出现一枚纯几何无字新压封痕，第三层与空槽关系必须一眼可读。",
    "E27-N11": "动作硬修：锁在钥匙尚连着第一名守卫腰带铜环、陈迹两指夹住钥匙并正把它从铜环抽出的瞬间；钥匙来源、腰部位置、抽取方向三者同框，不能让钥匙看起来早已在手中。",
    "E27-N17": "动作硬修：陈迹侧身用左肩明确顶住守卫胸甲接缝，守卫一手抓住拓片角，两人把纯白无字拓片绷成笔直受力线；禁止用手掐颈替代肩抵。拓片、卷轴、书脊、墙面全部无字无符号无伪字。",
    "E27-N19": "文字硬修：拓片改为纯净无字的灰白纤维纸，只用边缘缺口表示物证；时辰签改为纯色无字几何纸片；书脊与背景纸张全部无字、无刻痕、无符号、无伪字。保持拓片、无字签、文书残影胸口三点成线。",
    "E27-N24": "动作硬修：同一决定性瞬间必须同时可见陈迹收回蓝色冰流并跃上窗台、女性兔耳母题阴神的上半身正在穿过右侧实体墙探路、两端追兵的刀光在陈迹脚下交叉；三者空间关系清楚。所有挂纸、书脊、墙面与器物纯净无字无符号无伪字。",
}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def main() -> int:
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    review = json.loads(REPORT.read_text(encoding="utf-8"))
    failed_ids = {f"E27-N{row['index'] + 1:02d}" for row in review["content_failed_items"]}
    if failed_ids != set(FAILED):
        raise SystemExit(f"failed-item drift: {sorted(failed_ids)}")
    prompt_dir = DEST / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    tasks = []
    manifest = ["# E27 Writer Agent 静图 failed-only R1 提示词", "", "仅包含真实 AI 审片失败的九项；15 个通过项不重生。", ""]
    for task in source["tasks"]:
        shot_id = task["shot_id"]
        if shot_id not in FAILED:
            continue
        original = (ROOT / task["prompt_file"]).read_text(encoding="utf-8").rstrip()
        text = original + "\nFAILED_ONLY_R1_CORRECTION: " + FAILED[shot_id] + "\n"
        prompt_path = prompt_dir / f"{shot_id}-R1.txt"
        prompt_path.write_text(text, encoding="utf-8")
        row = dict(task)
        row["task_key"] = task["task_key"].replace("-V1", "-V1-R1")
        row["prompt_file"] = str(prompt_path.relative_to(ROOT))
        row["prompt_sha256"] = digest(text)
        row["status"] = "READY_FAILED_ONLY_PARALLEL_SUBMIT"
        row["retry_reason"] = "AI_REVIEW_0P8P0_CONTENT_FAIL"
        tasks.append(row)
        manifest.extend([f"## {shot_id}", "", text, ""])
    config = dict(source)
    config.update({
        "schema": "qingshan.episode_parallel_batch.v1",
        "status": "READY_FAILED_ONLY_R1_CONCURRENT_SUBMIT",
        "concurrency": len(tasks),
        "max_retries": 1,
        "output_dir": "working_assets/e27_writer_agent_stills_v1_failed_only_r1_20260720/candidates",
        "qa_dir": "qa/e27_writer_agent_stills_v1_failed_only_r1_20260720",
        "base_batch_note": "Retry only nine content-failed Writer Agent stills; retain fifteen passes.",
        "source_ai_review": str(REPORT.relative_to(ROOT)),
        "tasks": tasks,
    })
    manifest_path = DEST / "IMAGE_GENERATION_PROMPTS_FAILED_ONLY_R1.md"
    manifest_path.write_text("\n".join(manifest), encoding="utf-8")
    config["prompt_manifest"] = str(manifest_path.relative_to(ROOT))
    (DEST / "image_batch_failed_only_r1.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "task_count": len(tasks), "config": str((DEST / 'image_batch_failed_only_r1.json').relative_to(ROOT))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
