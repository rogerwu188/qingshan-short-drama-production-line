#!/usr/bin/env python3
"""Build a reversible E22 density-repair candidate from the approved v1 sheet."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


DIALOGUE = [
    ("陈迹", "这血的来路不对。", "B01", "冷开"),
    ("白鲤", "不是棺中那个人？", "B01", "追问"),
    ("陈迹", "这块布料也不对。", "B01", "布料异常"),
    ("白鲤", "是白般若叼来的？", "B01", "确认猫线索"),
    ("陈迹", "白般若一路带我。", "B01", "白猫功能"),
    ("白鲤", "乌云却一直低吼。", "B01", "黑猫反应"),
    ("陈迹", "两只猫闻得不同。", "B01", "气味矛盾"),
    ("白鲤", "血源被人换过了。", "B01", "血源掉包"),
    ("陈迹", "先看看它的猫爪。", "B02", "转香灰"),
    ("白鲤", "爪缝沾着香灰。", "B02", "香灰证据"),
    ("陈迹", "这种香灰仅此有。", "B02", "定位佛堂"),
    ("云妃", "我在此等你半日。", "B02", "云妃登场"),
    ("陈迹", "等我还是等这猫？", "B02", "反问"),
    ("云妃", "先看看这张纸吧。", "B03", "递暗号"),
    ("白鲤", "这是景朝的暗号？", "B03", "身份压力"),
    ("云妃", "陈公子果然认得。", "B03", "身份试探"),
    ("陈迹", "可惜是假暗号。", "B03", "识破"),
    ("陈迹", "上面的墨还是新的。", "B03", "新墨证据"),
    ("云妃", "你凭什么断定？", "B03", "对抗"),
    ("陈迹", "水印出自王府内。", "B03", "内造证据"),
    ("陈迹", "真接头人为何不来？", "B03", "反将一军"),
    ("静妃侍", "毒死人的药渣在此！", "B04", "闯入"),
    ("静妃侍", "云妃就是下毒之人。", "B04", "反咬"),
    ("陈迹", "这两味药性相冲。", "B04", "药性矛盾"),
    ("白鲤", "根本不能同炉煎？", "B04", "观众确认"),
    ("陈迹", "下药时辰也不合。", "B04", "时序矛盾"),
    ("陈迹", "药渣来自两家药房。", "B04", "拼接结论"),
    ("云妃", "这又是一份假证？", "B04", "嫌疑翻转"),
    ("白鲤", "采购签的是张夏。", "B05", "第三方"),
    ("陈迹", "第一份是血衣。", "B05", "并证一"),
    ("陈迹", "第二份是暗号。", "B05", "并证二"),
    ("陈迹", "第三份是药渣。", "B05", "并证三"),
    ("陈迹", "三样证据分属三家。", "B05", "并证收口"),
    ("陈迹", "你们彼此互相栽赃。", "B05", "meta洞察"),
    ("陈迹", "证据都是别人喂的。", "B05", "操盘判断"),
    ("云妃", "究竟是谁喂给我们？", "B06", "悬问"),
    ("陈迹", "他能同时操纵三家。", "B06", "抬高幕后"),
    ("陈迹", "这才是我要找的人。", "B06", "尾钩"),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    data = json.loads(args.source.read_text(encoding="utf-8"))
    targets = {"B01": 30, "B02": 28, "B03": 30, "B04": 30, "B05": 34, "B06": 20}
    for beat in data["structure"]:
        beat["target_seconds"] = targets[beat["beat_id"]]

    data["dialogue_draft"] = [
        {
            "dia_id": f"DIA-{index:03d}",
            "speaker": speaker,
            "text": text,
            "beat_id": beat_id,
            "function": function,
        }
        for index, (speaker, text, beat_id, function) in enumerate(DIALOGUE, 1)
    ]
    data["status"] = "V2_DENSITY_REPAIR_CANDIDATE_MACHINE_ADJUDICATION"
    data["generation_allowed"] = False
    data["density_repair"] = {
        "source": str(args.source),
        "strategy": "Preserve approved story beats while matching 172-second structure and splitting exposition into 38 short, audio-clear turns.",
        "rollback": "Delete this candidate only; the approved v1 source remains unchanged.",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "BUILT", "out": str(args.out), "dialogue_lines": len(DIALOGUE)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
