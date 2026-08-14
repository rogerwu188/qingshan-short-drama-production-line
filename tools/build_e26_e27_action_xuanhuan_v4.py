#!/usr/bin/env python3
"""Create the E26/E27 action-xuanhuan V4 scripts required by CL2X-383/384."""

from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


UPGRADES = {
    "E26": {
        "B01": ("陈迹推药柜封门，清洗者破窗突入，双方在火把与药架间短打争门。", "陈迹冰流沿泼洒药水结霜，照出潜入者脚印。", "火焰被冰流劈开，药水结晶沿敌人脚步爆亮。"),
        "B02": ("陈迹格挡火把、翻过燃烧箱笼抢出闭合布包册，再把袭击者撞离火场。", "冰流封住布包焦边，保住残留气味与压痕。", "火星撞上冰雾骤熄，焦边冻结成清晰轮廓。"),
        "B03": ("清洗者反锁前后门并泼油，白鲤推柜筑障，陈迹带众人边打边退入内堂。", "乌云开口示警屋梁伏兵，玄幻身份第一次被众人听见。", "乌云声落时烛火逆风压低，屋梁灰尘显出伏兵移动。"),
        "B04": ("乌云穿药架扑咬夺册者，陈迹接力擒腕，完成夺回证物的连续搏斗。", "乌云灵猫妖气短暂护住残页并开口喊出内应方向。", "黑色妖气贴地卷起药粉，勾出袭击者逃跑路线。"),
        "B05": ("陈迹追着药粉痕撞开侧柜，逼出藏在柜后的内应，双方争夺药钥。", "陈迹以冰流冻结药味挥发轨迹，反向锁定内应藏身处。", "冷雾沿同源药香凝成冰线，从残页一路连到侧柜。"),
        "B06": ("姚太医推账堵门，众人传递伤猫与证物组成撤离链，合力压住最后一名闯入者。", "乌云以人言点出未散的第二股药味，留下下一集假令来源。", "冰线与烛火在账柜前交汇，第二股药味化作短暂蓝雾指向门外。"),
    },
    "E27": {
        "B01": ("送令兵拍令压人并拔刀抢账，姚太医护账，陈迹在桌案翻倒间完成格挡夺令。", "陈迹冰流扫过官印，真印应显的灵纹没有出现，假令当场崩裂。", "冰霜爬过印面却不生官气，伪墨裂成黑屑。"),
        "B02": ("送令兵败退，皎兔追出医馆跃墙跟踪，陈迹换装从侧巷切入王府。", "皎兔阴神出窍穿墙追踪，回看送令兵受训步法。", "半透明阴神穿过雨墙，脚步残影在水面逐格重现。"),
        "B03": ("陈迹潜入档房移灯开锁，被守卫发现后在卷宗架间短打夺钥。", "皎兔阴神穿过柜壁指向被改名册的暗格。", "纸页被交锋气流卷成纸浪，阴神冷光在暗格边缘聚拢。"),
        "B04": ("乌云跃上卷宗架按住叠纸，陈迹边躲追兵边以侧光拓出凹痕。", "乌云开口报出活人气息，陈迹冰流让压痕以霜纹浮现。", "霜纹沿无字纸背扩散成死亡顺序的抽象高低轨迹，不出现文字。"),
        "B05": ("文书房守卫夺走拓片，陈迹追入长廊完成擒拿并抢回证物。", "皎兔阴神回放落笔当夜的死亡残影，证明名单先于死亡。", "雨水倒影里闪回朱笔落下与命灯熄灭的同步异象。"),
        "B06": ("新名单送入文书房，陈迹破窗闯入，与执笔人及护卫交锋，打飞朱笔救下首名活口。", "冰流封住飞散朱墨并显出下一名目标的命气，倒计时启动。", "朱墨在空中冻成黑冰碎片，纸浪与窗外雨幕同时炸开。"),
    },
}


def build(episode: str, source_name: str, out_name: str) -> Path:
    source = json.loads((ROOT / source_name).read_text(encoding="utf-8"))
    payload = copy.deepcopy(source)
    payload["supersedes"] = source_name
    payload["revision_ref"] = "CL2X-383/384_ACTION_XUANHUAN_HARD_GATE"
    payload["status"] = "ACTION_XUANHUAN_V4_COUNCIL_REVIEW_READY"
    payload["review_status"] = "PENDING_COUNCIL_ACTION_XUANHUAN_REVIEW"
    payload["generation_allowed"] = False
    payload["final_lock_blocked_until"] = "ACTION_XUANHUAN_GATE_AND_COUNCIL_PASS"
    for beat in payload["structure"]:
        action, xuanhuan, visualization = UPGRADES[episode][beat["beat_id"]]
        beat["payload_delivery"] = "ACTION_XUANHUAN"
        beat["action_spine"] = action
        beat["xuanhuan_element"] = xuanhuan
        beat["power_visualization"] = visualization
    out = ROOT / out_name
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> int:
    outputs = [
        build("E26", "configs/e26_dialogue_beat_sheet_v3_readiness_repair_20260719.json", "configs/e26_dialogue_beat_sheet_v4_action_xuanhuan_20260719.json"),
        build("E27", "configs/e27_dialogue_beat_sheet_v3_readiness_repair_20260719.json", "configs/e27_dialogue_beat_sheet_v4_action_xuanhuan_20260719.json"),
    ]
    print(json.dumps({"status": "PASS", "outputs": [str(path) for path in outputs]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
