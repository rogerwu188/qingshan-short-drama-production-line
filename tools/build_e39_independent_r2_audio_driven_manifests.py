#!/usr/bin/env python3
"""Compile failed-only E39 R2 video manifests with exact-line audio transport."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "workflow/claude_writer_agent/production/e39_claude_writer_v3_2726b69b_20260805"
R1_DIR = BASE / "independent_video_v1"
R2_DIR = BASE / "independent_video_r2_audio_driven"
AUDIO = ROOT / "workflow/tasks/E39_INDEPENDENT_R2_EXACT_DIALOGUE_AUDIO_ASSETS_20260806.json"
WAVES = [
    R1_DIR / "E39_INDEPENDENT_VIDEO_WAVE1_MANIFEST_V1.json",
    R1_DIR / "E39_INDEPENDENT_VIDEO_WAVE2_MANIFEST_V1.json",
]
OUT = R2_DIR / "E39_INDEPENDENT_FAILED_ONLY_R2_MANIFEST_V1.json"
DIAGNOSTIC_OUT = R2_DIR / "E39_INDEPENDENT_U01_R2_DIAGNOSTIC_MANIFEST_V1.json"
BOUNDED_WAVE_OUT = R2_DIR / "E39_INDEPENDENT_R2_PRO_BOUNDED_WAVE1_MANIFEST_V1.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def strip_literal_dialogue(prompt: str, lines: list[str]) -> str:
    value = prompt
    for index, line in enumerate(lines, 1):
        audio_ref = f"@音频{index}"
        value = value.replace(f"说准确台词“{line}”", f"完整复现{audio_ref}中的唯一对白，口型逐音节同步")
        value = value.replace(f"说“{line}”", f"完整复现{audio_ref}中的唯一对白，口型逐音节同步")
        value = value.replace(f"台词“{line}”", f"{audio_ref}中的唯一对白")
    leaked = [line for line in lines if re.sub(r"\s+", "", line) in re.sub(r"\s+", "", value)]
    if leaked:
        raise ValueError(f"literal dialogue remains: {leaked}")
    return value


def corrections(unit: str) -> str:
    shared = (
        "声音与画面分轨：@音频编号均为逐句准确对白本体，只在指定说话者动作窗播放；"
        "画面生成阶段不得把声音内容转写为任何字形、字幕、题词或装饰文字。"
        "说话者口型逐音节同步，非说话者闭口并持续做有动机的呼吸、视线和手部反应。"
    )
    unit_specific = {
        "U01": "保持首帧三名主角的脸、年龄、性别和服装不变；先押送持续移动，再发生扣腕拦阻，叙事顺序不得倒置或合并。",
        "U02": "官差离画、松腕、望向长街三步按顺序各发生一次；两句对白分别绑定@音频1与@音频2，不复用同一声音片段。",
        "U03": "乌云只完成一次肩头起跳、依次嗅甲乙下风口、回肩并用尾尖指出两路；押送两路始终同时向不同出口移动，不插入空街。",
        "U04": "账页只允许来源绑定标题“药柜更换日期”、阿拉伯数字、短横与印记；其他区域保持空白纸纤维。陈迹保持首帧灰袍身份；乌云撞卷、卷册脱手、双方俯身、封套互换、起身归还必须连续可读。",
        "U05": "皎兔实体保持唯一；眉心逸出的女性半透明投影保持皎兔同脸同服装，并在连续运动中分为两缕方向明确的薄影；不得插入空街或第二实体。",
        "U10": "两页账摹本只用阿拉伯数字、短横和来源绑定印记，绝不生成任何汉字；甲页、乙页和手指指向全程清晰，证据因果不得被浅焦抹掉。",
        "U11": "纸面仅保留三个阿拉伯数字日期格、绘线和一方来源绑定花瓣旧印，其他区域为空白纸纤维；先逐格托亮三个日期，再展开拓影显印，两件证据各只发生一次。",
        "U12": "单一群像机位；云羊和陈迹严格各说一条对应音频，口型不可互换；画内所有纸面朝下或出焦到不可辨字，但人物面部必须清晰。",
        "U13": "乌云维持真实成年猫比例并稳伏陈迹肩头，不放大、不漂浮；陈迹素白细布直裰从首帧到尾帧不变灰，守卫保持不同面孔。",
        "U14": "陈迹全程素白细布直裰；拓影沿衣襟开口一次完整收入并露出空手，随后抬脚、短停不超过0.35秒、落上石阶，动作连续不可跳步。",
        "U15": "陈迹全程素白细布直裰并正常步速上阶；朱门和牌匾为无字木构，不生成任何汉字、符号或伪文字；唯一运镜只随登阶匀速升高。",
    }
    return shared + unit_specific[unit]


def main() -> int:
    audio = json.loads(AUDIO.read_text(encoding="utf-8"))
    if audio.get("status") != "PASS":
        raise SystemExit("exact dialogue audio receipt is not PASS")
    audio_by_unit: dict[str, list[str]] = {}
    for row in audio["results"]:
        audio_by_unit.setdefault(row["unit_id"], []).append(row["registered_asset_id"])

    source_manifests = [json.loads(path.read_text(encoding="utf-8")) for path in WAVES]
    tasks = []
    R2_DIR.mkdir(parents=True, exist_ok=True)
    for manifest in source_manifests:
        for original in manifest["tasks"]:
            unit = original["task_key"].split("-")[1]
            lines = original["dialogue_lines"]
            exact_assets = audio_by_unit[unit]
            if len(lines) != len(exact_assets):
                raise ValueError(f"{unit} dialogue/audio count mismatch")
            source_prompt = ROOT / original["prompt_file"]
            prompt = strip_literal_dialogue(source_prompt.read_text(encoding="utf-8"), lines)
            prompt = corrections(unit) + prompt
            prompt = re.sub(r"@音频\d+锁定[^。]+。", "", prompt)
            prompt_path = R2_DIR / f"E39-{unit}-R2.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            task = dict(original)
            task.update({
                "task_key": f"E39-{unit}-R2",
                "model": "seedance-2.0-pro",
                "prompt_file": str(prompt_path.relative_to(ROOT)),
                "prompt_sha256": sha(prompt_path),
                "source_subtitle_policy": "FORBID",
                "dialogue_transport": "EXACT_LINE_AUDIO_REFERENCE",
                "exact_dialogue_audio_asset_ids": exact_assets,
                "reference_audio_asset_ids": [],
            })
            tasks.append(task)

    gates = []
    for manifest in source_manifests:
        for gate in manifest.get("machine_gate_reports") or []:
            if gate not in gates:
                gates.append(gate)
    result = {
        "schema": "qingshan.e39_independent_failed_only_video_r2.v1",
        "episode": "E39",
        "status": "READY_FOR_PAID_PREFLIGHT",
        "source_script_sha256": source_manifests[0]["source_script_sha256"],
        "canonical_manifest_sha256": source_manifests[0]["canonical_manifest_sha256"],
        "exact_dialogue_audio_receipt": str(AUDIO.relative_to(ROOT)),
        "exact_dialogue_audio_receipt_sha256": sha(AUDIO),
        "machine_gate_reports": gates,
        "tasks": tasks,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    diagnostic = dict(result)
    diagnostic["tasks"] = result["tasks"][:1]
    DIAGNOSTIC_OUT.write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bounded_wave = dict(result)
    bounded_wave["tasks"] = result["tasks"][:4]
    BOUNDED_WAVE_OUT.write_text(json.dumps(bounded_wave, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "tasks": len(tasks), "manifest": str(OUT), "sha256": sha(OUT)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
