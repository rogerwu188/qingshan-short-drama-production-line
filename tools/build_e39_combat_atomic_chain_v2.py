#!/usr/bin/env python3
"""Recompile E39 FS-1 as real-time atomic Seedance units under BacklotOS 0.2.36."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PIPELINE = Path("/Users/rogerwu/.local/share/backlotos/share/pipeline-tools")
sys.path.insert(0, str(PIPELINE))
from performance_tempo_gate import evaluate_batch  # noqa: E402

SCRIPT_SHA = "2726b69bd1f91ca4efbcb37cce7664cc17919f2eac7970cc49eb795318d42e0a"
MANIFEST_SHA = "f00015b954ad19f5a56d6cb116823956ee26fa8ec4742a53d443a16b77f2952a"
OUT = ROOT / "workflow/claude_writer_agent/production/e39_claude_writer_v3_2726b69b_20260805/combat_atomic_v2"


BEATS = [
    {
        "key": "E39-FS1-A01",
        "assembly_seconds": 3.6,
        "entry": "四名赭褐暗桩翻落半空，官差乙已向北跑，三名主角同时前倾发力",
        "exit": "0.9米高、0.3米厚、4米长的落地冰垄沿巷中线形成，官差乙进入东侧通道",
        "windows": [
            (0.0, 0.8, "暗桩落地即向账封扑击，官差乙持续北跑"),
            (0.8, 1.8, "陈迹左脚定在东道外，冰流沿积水向北爆发"),
            (1.8, 2.8, "冰垄从地面长成并把攻击者逼向西道"),
            (2.8, 4.0, "官差乙低头通过东道，云羊降重心护住西侧"),
        ],
        "camera": "低机位平行巷轴短跟冰垄前缘，随后锁定东侧通道，不摇摆不环绕",
    },
    {
        "key": "E39-FS1-A02",
        "assembly_seconds": 3.6,
        "entry": "冰垄已落地分巷，官差乙正在东道奔跑，首领已在西道举起短刃",
        "exit": "短刃只剁冰垄一次，云羊已进入两名从者的夹击距离，官差乙离开接触区",
        "windows": [
            (0.0, 0.9, "首领向前一步，短刃斜下剁中冰垄上三分之一"),
            (0.9, 1.8, "冰碴和雨水向西爆开，首领眯眼卸力不重复挥刀"),
            (1.8, 2.9, "两名从者丢刃从左右夹向云羊肩线"),
            (2.9, 4.0, "云羊顺时针转髋进入一身位窄道，官差乙跑出北端"),
        ],
        "camera": "东侧固定动作轴，先锁刃冰接触，再一次硬切到云羊夹击关系",
    },
    {
        "key": "E39-FS1-A03",
        "assembly_seconds": 3.6,
        "entry": "云羊正处左右夹击内，左臂暴露，半垛砖墙在他正前方一臂距离",
        "exit": "一拳擦空击塌半垛墙，从者二已缠住云羊左前臂但云羊仍站立反抗",
        "windows": [
            (0.0, 0.8, "云羊短直拳擦过从者三鬓角，不延长蓄力"),
            (0.8, 1.7, "拳头按原方向击中半垛砖墙，接触点立即碎裂"),
            (1.7, 2.8, "碎砖落雨，从者三抬臂挡碎屑并持续换步"),
            (2.8, 4.0, "从者二从左后一步缠住云羊前臂，云羊转肩抵抗"),
        ],
        "camera": "西道腰平稳定横移半步跟随拳路，接触后锁定砖裂和缠臂，不甩镜",
    },
    {
        "key": "E39-FS1-A04",
        "assembly_seconds": 3.6,
        "entry": "云羊左臂被缠但身体仍站立，两名绕行暗桩正在西岔加速，三个地面锚点清楚可见",
        "exit": "云羊脱缠，三面各1.6米高1.2米宽的落地软纸障封住西岔，两名暗桩分别被缠住仍在挣扎",
        "windows": [
            (0.0, 0.8, "云羊沉肘转腕脱开缠臂并立即指向三处地面锚点"),
            (0.8, 1.8, "三张纸人贴地分别滑向三个锚点"),
            (1.8, 2.9, "三张纸人同时立成三面独立人高软障，不变成人"),
            (2.9, 4.0, "两名绕行暗桩分别撞入不同软障并持续挣扎"),
        ],
        "camera": "固定朝向西岔的宽中景，三锚点始终同框，禁止纸墙形成时环绕展示",
    },
    {
        "key": "E39-FS1-A05",
        "assembly_seconds": 3.6,
        "entry": "三面软纸障已封西岔，追兵从南向北踏入三米乘两米积水区，皎兔阴神在西侧雨幕内移动",
        "exit": "薄冰仅铺地面使追兵互相扶住滑退，阴神臂甲只磕飞一支箭到东墙，首领扶伤撤退，主角全员直立",
        "windows": [
            (0.0, 0.8, "陈迹低拖一掌，薄冰沿三米乘两米地面径向铺开"),
            (0.8, 1.8, "追兵脚掌失去抓地并向北滑，互相抓扶不重复摔倒"),
            (1.8, 2.8, "一支箭射向北侧官差乙，皎兔阴神从西雨幕单次横切"),
            (2.8, 4.0, "臂甲磕箭入东墙，首领立刻示意撤退并扶伤员离开"),
        ],
        "camera": "贴地平行追兵脚步短跟，箭出现后硬切锁定臂甲接触和东墙终点",
    },
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tasks = []
    for index, beat in enumerate(BEATS, 1):
        prompt = (
            "E39雨巷护双证打斗，Seedance 2.0 Pro，原生1080p，4秒，真实时间1倍速。"
            f"入口状态：{beat['entry']}。"
            + "".join(f"{start:.1f}-{end:.1f}秒：{action}。" for start, end, action in beat["windows"])
            + f"终态：{beat['exit']}。摄影机：{beat['camera']}。"
            "打斗动作比日常动作更快更短，接触即产生结果，不蓄力拖延，不停顿摆姿势。"
            "所有可见人物持续执行攻击、闪避、护送、失衡或撤退反应，禁止背景人物冻结。"
            "暗桩统一赭褐短打且四张脸不同；陈迹灰袍，云羊和皎兔为密谍司黑色窄袖制式，禁止换脸换衣。"
            "冰垄必须落地且0.9米高，不是手持盾牌；软纸障三面独立落地；薄冰只铺地面。"
            "禁止慢动作、速度渐变、插帧感、动作重置、重复击打、错误胜负、主角被制服、摇镜、环绕、漫游、伪中文、字幕、水印。"
        )
        prompt_path = OUT / f"{beat['key']}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        previous = BEATS[index - 2]["key"] if index > 1 else None
        windows = [
            {"start_seconds": start, "end_seconds": end, "action": action}
            for start, end, action in beat["windows"]
        ]
        task = {
            "task_key": beat["key"],
            "episode": "E39",
            "unit_id": beat["key"],
            "duration": 4,
            "duration_seconds": 4,
            "assembly_window_seconds": beat["assembly_seconds"],
            "model": "seedance-2.0-pro",
            "resolution": "1080p",
            "action_unit": True,
            "shot_purpose": "雨巷打斗护送两页账的高速原子动作",
            "narrative_function": "combat protection chain",
            "prompt_file": str(prompt_path),
            "prompt_sha256": hashlib.sha256(prompt_path.read_bytes()).hexdigest(),
            "source_script_sha256": SCRIPT_SHA,
            "canonical_manifest_sha256": MANIFEST_SHA,
            "performance_tempo_contract": {
                "playback_speed": "REAL_TIME_1X",
                "entry_action_already_in_progress": True,
                "primary_action_complete_by_seconds": 1.2,
                "result_hold_seconds": 0.0,
                "atomic_action_windows": windows,
                "forbid_duration_filling": ["slow_motion", "replay", "reset", "extended_windup", "pose_hold"],
            },
            "action_sequence_contract": {
                "chain_id": "E39_FS1_12_3_ATOMIC_V2",
                "sequence_index": index,
                "entry_state_token": beat["entry"],
                "exit_state_token": beat["exit"],
                "depends_on_task": previous,
                "predecessor_tail_frame_ref": None if previous is None else f"DEFER_UNTIL_{previous}_ACCEPTED_EXACT_TAIL",
                "tail_to_head_identity_required": index > 1,
                "hidden_inter_shot_events_forbidden": True,
            },
            "status": "READY_TO_SUBMIT" if index == 1 else "BLOCKED_ON_ACCEPTED_PREDECESSOR_TAIL",
        }
        tasks.append(task)

    gate = evaluate_batch(tasks)
    if gate["status"] != "PASS":
        raise SystemExit(json.dumps(gate, ensure_ascii=False, indent=2))
    plan = {
        "schema": "qingshan.e39_combat_atomic_chain.v2",
        "episode": "E39",
        "status": "PASS_FIRST_ATOMIC_UNIT_OPEN_SUCCESSORS_TAIL_BLOCKED",
        "pipeline_release": "BacklotOS-v0.2.36",
        "canonical_script_sha256": SCRIPT_SHA,
        "canonical_manifest_sha256": MANIFEST_SHA,
        "authored_combat_seconds": 18,
        "generated_seconds": 20,
        "assembly_seconds": sum(beat["assembly_seconds"] for beat in BEATS),
        "tasks": tasks,
        "performance_tempo_gate": gate,
    }
    path = OUT / "E39_COMBAT_ATOMIC_CHAIN_V2.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
