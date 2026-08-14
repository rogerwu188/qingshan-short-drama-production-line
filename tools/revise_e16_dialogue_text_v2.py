#!/usr/bin/env python3
"""Apply the supervisor-directed professional dialogue rewrite to E16."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "configs" / "e16_dialogue_beat_sheet_20260711.json"

TEXT = {
    "D01": "本官办差，先封他的手。",
    "D02": "先看尸。手跑不了。",
    "D03": "一个学徒，也敢拦本官？",
    "D04": "我碰过。腕上两道。",
    "D05": "两道？哪儿呢？",
    "D06": "灯近点。这里。",
    "D07": "泡了三日，什么褶没有？",
    "D08": "还没看，先认成褶了？",
    "D09": "大人来得，倒比雨还快。",
    "D10": "灯再近些。",
    "D11": "这、这是两道啊。",
    "D12": "验尸格目写得清楚。",
    "D13": "褶会乱。线不会。",
    "D14": "这铜扣，也会自己来？",
    "D15": "县衙杂物，算什么官物。",
    "D16": "背面一个县字。",
    "D17": "没错，是仵作扣。",
    "D18": "尸先验。人，随后再封。",
    "D19": "昨夜后门，谁替大人开的？",
    "D20": "你凭什么问本官？",
    "D21": "凭这个。半枚火漆。",
    "D22": "县衙火漆，外头多的是。",
    "D23": "是么？裂口怎么只合这一枚？",
    "D24": "另一半，粘在你箱角。",
    "D25": "放肆。县衙的箱子也敢碰？",
    "D26": "我还没说怕。大人先急了。",
    "D27": "乌云，回来。",
    "D28": "哎，这猫比咱们先找着了。",
    "D29": "铜针套。",
    "D30": "医馆没有铜针？笑话。",
    "D31": "针套湿。",
    "D32": "箱底却干净得很。",
    "D33": "可大人的袍角，也是干的。",
    "D34": "雨里来的？不像。",
    "D35": "拿来。本官要验。",
    "D36": "放那儿。谁都别碰。",
    "D37": "还愣着？夺回来！",
    "D38": "让、让开！",
    "D39": "办案，还是抢证？",
    "D40": "小的只是奉命……",
    "D41": "谁的命？",
    "D42": "大胆！给本官按住他！",
    "D43": "谁抢证，谁心虚。",
    "D44": "再走一步，我记名。",
    "D45": "大人……要不先停手？",
    "D46": "先看瞳孔。散了，不收。",
    "D47": "眼白还有血点。",
    "D48": "脖上有印，指下没血。",
    "D49": "泡过水，这些都不作数。",
    "D50": "刀口新，血却没往外走。",
    "D51": "人先死，刀后补。",
    "D52": "腕上……又一道验尸线。",
    "D53": "不、不可能……前一具没有——",
    "D54": "前一具？",
    "D55": "大人验过几具？",
    "D56": "本官说的是县衙旧案。",
    "D57": "旧案也有这道线？",
    "D58": "后院……是不是有水声？",
    "D59": "不是雨。水缸里。",
    "D60": "别动。灯照过去。",
    "D61": "又一块裹尸布！",
    "D62": "大人，下一具在哪儿？"
}

METADATA = {
    "D28": {
        "function": "comic_discovery",
        "listener_reaction": "众人先瞥官差一眼，再低头看猫叼出的针套"
    },
    "D46": {"function": "autopsy_sign_pupil", "listener_reaction": "验尸官被迫拨灯看瞳孔"},
    "D47": {"speaker": "官差", "listener": "众人", "function": "autopsy_sign_eye", "listener_reaction": "众人靠近确认眼白血点"},
    "D48": {"function": "autopsy_sign_neck", "listener_reaction": "验尸官避开颈侧无血痕处"},
    "D49": {"speaker": "验尸官", "listener": "众人", "function": "institutional_bluff", "listener_reaction": "白鲤转向新鲜刀口"},
    "D50": {"speaker": "白鲤", "listener": "众人", "function": "autopsy_sign_wound", "listener_reaction": "官差看见刀口无外渗血"},
    "D51": {"function": "mechanism_conclusion", "listener_reaction": "验尸官握刀的手停住"},
    "D52": {"function": "autopsy_sign_wrist", "listener_reaction": "众人发现第二道验尸线"},
    "D53": {"listener": "陈迹与白鲤", "function": "knowledge_slip", "listener_reaction": "陈迹与白鲤同时抬眼"},
    "D54": {"listener": "验尸官", "function": "catch_slip", "listener_reaction": "验尸官话音断住"},
    "D55": {"function": "pressure_question", "listener_reaction": "验尸官后退半步"},
    "D56": {"function": "cover_story", "listener_reaction": "官差开始怀疑旧案说法"},
    "D57": {"function": "lock_contradiction", "listener_reaction": "验尸官无言"}
}


def main() -> None:
    data = json.loads(PATH.read_text(encoding="utf-8"))
    for line in data["lines"]:
        line["text"] = TEXT[line["id"]]
        line.update(METADATA.get(line["id"], {}))
        line.pop("delivery", None)
        line["delivery_status"] = "PENDING_CLAUDE_DIALOGUE_APPROVAL"
    data["dialogue_rewrite_standard"] = "/Users/rogerwu/qingshan_short_drama/codex_docs/短剧台词设计规范_爆款语料实测_20260712.md"
    data["performance_bible"] = "/Users/rogerwu/qingshan_short_drama/configs/character_performance_bible_20260712.json"
    data["performance_transmission_required"] = True
    data["performance_status"] = "PERFORMANCE_BIBLE_APPROVED_DIALOGUE_PENDING_CLAUDE_APPROVAL"
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"rewritten={len(data['lines'])}")


if __name__ == "__main__":
    main()
