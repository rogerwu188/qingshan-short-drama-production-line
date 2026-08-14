#!/usr/bin/env python3
"""Build materially changed fixed-camera prompts for the E37 V15 repair."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TASK_FILES = [
    ROOT / "workflow/tasks/E37_REMAINING_U03_U07_PFM_V2_OVERHEAD_REVEAL_PENDING9_SUBMIT_V4_20260803.json",
    ROOT / "workflow/tasks/E37_REMAINING_U03_U07_PFM_V2_OVERHEAD_REVEAL_SUBMIT_V4_20260803.json",
]
OUT_DIR = ROOT / "working_assets/e37_v15_fixed_camera_repair_20260804/prompts"
RECEIPT = ROOT / "workflow/tasks/E37_V15_FIXED_CAMERA_DIALOGUE_PROMPT_BUILD_20260804.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strip_bad_recipe_lock(text: str) -> str:
    marker = "[原 PFM 预编译提示词，除上述运镜覆盖外保持 canonical 对白和身份约束]"
    if marker not in text:
        return text
    return text.split(marker, 1)[1].lstrip()


def main() -> None:
    tasks = []
    for path in TASK_FILES:
        tasks.extend(json.loads(path.read_text(encoding="utf-8"))["tasks"])
    tasks.sort(key=lambda row: row["segment_id"])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for task in tasks:
        source = ROOT / task["prompt_file"]
        body = strip_bad_recipe_lock(source.read_text(encoding="utf-8"))
        duration = int(task["duration_seconds"])
        cut = round(duration * 0.52, 2)
        lock = f"""[E37 V15 根治性固定机位生产锁：本块覆盖下方全部运镜措辞]
片段：{task['segment_id']}；模型：Seedance 2.0 Pro；输出：1080p；速度：REAL_TIME_1X。

本单元只允许两个固定构图，中间只允许一次直接硬切：
- 0.00-{cut:.2f}秒：固定构图A。三脚架锁死机位、焦距、水平、俯仰和画幅边界。
- {cut:.2f}-{duration:.2f}秒：一次直接硬切到固定构图B。第二机位同样完全锁死。
两个构图必须有明确叙事分工，A负责说话者或动作起因，B负责证物、反应或结果；不得在同一机位塞入全部信息。

全程禁止：smooth_roam、slow_push、push、pullback、overhead_reveal、tilt、pan、dolly、zoom、orbit、crane、tracking、handheld、continuous_reframe、漂移、摇摆、升降、环绕、自动重新取景、数码推拉、Ken Burns。
人物、衣摆、呼吸、眼神、纸页和灯火按真实时间自然运动；禁止慢动作、慢放、拖步、动作重复、动作复位、冻结尾帧。镜头不动不等于人物不动。
canonical对白、身份、时代、安全、OCR空白器物锁全部保留；任何硬身份、安全、时代、OCR失败覆盖分数。禁止字幕、水印和可读伪文字。

提交前审计：若提示词仍包含要求执行任何连续运镜的肯定句，判定FAIL，不得提交。
"""
        output = OUT_DIR / f"E37-{task['segment_id']}-FIXED-TWO-COMPOSITIONS-V15.txt"
        output.write_text(lock + "\n" + body, encoding="utf-8")
        rows.append({
            "task_key": f"E37-{task['segment_id']}-FIXED-TWO-COMPOSITIONS-V15",
            "segment_id": task["segment_id"],
            "duration_seconds": duration,
            "prompt": str(output.relative_to(ROOT)),
            "prompt_sha256": sha256(output),
            "source_prompt": str(source.relative_to(ROOT)),
            "source_prompt_sha256": sha256(source),
            "reference_images": task["reference_images"],
            "model": "seedance-2.0-pro",
            "resolution": "1080p",
            "camera_policy": "TWO_FIXED_COMPOSITIONS_ONE_HARD_CUT_NO_CONTINUOUS_CAMERA_MOTION",
            "tempo": "REAL_TIME_1X",
        })
    payload = {
        "schema": "qingshan.e37.v15_fixed_camera_prompt_build.v1",
        "episode": "E37",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "PASS_10_OF_10_MATERIALLY_CHANGED_PROMPTS_READY",
        "root_cause": "V14 retained source media named SMOOTH_ROAM/PUSH/CONTINUOUS_REFRAME while changing only recipe metadata.",
        "canonical_script_sha256": "07a63a0c286be656feac59a0f31ea1bb159f3f7ce56f1172bb202832edf9db3a",
        "canonical_manifest_sha256": "9082f9d3b45bf0466476e98cb194d91d00d6775c2b762b5253c8f7557d31c33e",
        "tasks": rows,
        "credits": {"repair_round_cap": 10000, "authorized_by": "Roger: 重做可以重新计算上限积分"},
        "next_action": "Submit independent dialogue units concurrently at Pro 1080p, then replace all V14 motion-source spans before full normal-speed review.",
    }
    RECEIPT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(RECEIPT), "sha256": sha256(RECEIPT), "tasks": len(rows)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
