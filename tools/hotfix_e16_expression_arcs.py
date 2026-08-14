#!/usr/bin/env python3
import json
from copy import deepcopy
from pathlib import Path


PATH = Path("/Users/rogerwu/qingshan_short_drama/configs/e16_b_coverage_batch_plan_20260712.json")

ARCS = {
    "E16-B01": ("戒备", "验尸官下令封手", "恼怒"),
    "E16-B02": ("得意", "陈迹说手不是证据", "狐疑"),
    "E16-B03": ("压怒", "白鲤指出来得太快", "失态"),
    "E16-B04": ("得意", "湿针套与干箱同时出现", "僵住"),
    "E16-B05": ("不屑", "证物水迹被当众比较", "惊疑"),
    "E16-B06": ("恼怒", "陈迹以验尸程序反压", "压怒"),
    "E16-B07": ("戒备", "官差逼近", "平静"),
    "E16-B08": ("狐疑", "第二层证据吻合", "警惕"),
    "E16-B09": ("警惕", "有人伸手抢证", "压怒"),
    "E16-B10": ("平静", "验尸官说漏未公开细节", "惊疑"),
    "E16-B11": ("不屑", "腕痕被灯照清", "惊疑"),
    "E16-B12": ("戒备", "陈迹与验尸官对视", "压怒"),
    "E16-B13": ("狐疑", "箱内外状态矛盾", "惊疑"),
    "E16-B14": ("得意", "陈迹摸到异常水迹", "心虚"),
    "E16-B15": ("狐疑", "两处水迹不一致", "震住"),
    "E16-B16": ("不屑", "尸腕出现第二道痕", "惊疑"),
    "E16-B17": ("戒备", "灯光照出水面异物", "震住"),
    "E16-B18": ("狐疑", "铜扣标记显露", "惊疑"),
    "E16-B19": ("戒备", "官差喊出眼白血点", "惊疑"),
    "E16-B20": ("狐疑", "腕上第二道验尸线显露", "震住"),
    "E16-B21": ("狐疑", "水缸浮出新证物", "惊慌"),
    "E16-B22": ("压怒", "白鲤追问来路", "心虚"),
    "E16-B23": ("得意", "瞳孔和颈印共同显示死后造痕", "惊疑"),
    "E16-B24": ("戒备", "陈迹说出人先死刀后补", "震住"),
    "E16-B25": ("不屑", "白鲤追问验过几具", "僵住"),
    "E16-B26": ("压怒", "众人等他解释", "失态"),
    "E16-B27": ("平静", "铜扣背面县字露出", "冷笑"),
    "E16-B28": ("戒备", "验尸官拿县衙旧案遮掩", "狐疑"),
    "E16-B29": ("狐疑", "官差认出县衙标记", "惊慌"),
    "E16-B30": ("平静", "半枚火漆与箱上裂口吻合", "冷笑"),
    "E16-B31": ("警惕", "木箱发出异响", "惊疑"),
    "E16-B32": ("恼怒", "陈迹护住证物", "狐疑"),
    "E16-B33": ("压怒", "验尸官再次催促抢证", "恼怒"),
    "E16-B34": ("惊疑", "不该知道的细节被说漏", "警惕"),
    "E16-B35": ("戒备", "众人同时逼近", "压怒"),
    "E16-B36": ("狐疑", "刀口新却没有外渗血", "惊疑"),
}

CROWD_REACTION_IDS = {"E16-B11", "E16-B20", "E16-B21", "E16-B29"}

SERVES_OVERRIDES = {
    "E16-B20": ["D52"],
    "E16-B24": ["D51", "D54"],
    "E16-B27": ["D15"],
    "E16-B28": ["D56"],
}

ACTION_OVERRIDES = {
    "E16-B19": ["官差停止封手", "众人靠近确认眼白血点"],
    "E16-B20": ["众人看见腕上第二道验尸线"],
    "E16-B23": ["验尸官被迫拨灯看瞳孔", "验尸官避开颈侧无血处"],
    "E16-B24": ["验尸官握刀的手停住", "验尸官话音断住"],
    "E16-B25": ["验尸官后退半步", "验尸官无言"],
    "E16-B27": ["白鲤翻转铜扣"],
    "E16-B28": ["官差互看", "官差开始怀疑旧案说法"],
    "E16-B34": ["陈迹与白鲤同时抬眼"],
    "E16-B36": ["白鲤转向新鲜刀口", "官差看见刀口无外渗血"],
}


def main():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    if not any(clip["coverage_source_id"] == "E16-B36" for clip in data["clips"]):
        template = deepcopy(next(clip for clip in data["clips"] if clip["coverage_source_id"] == "E16-B20"))
        template.update({
            "coverage_source_id": "E16-B36",
            "serves_dialogue_beats": ["D49", "D50"],
            "listener": "众人",
            "coverage": "crowd_reaction",
            "status": "PLANNED_NO_SOURCE",
        })
        data["clips"].append(template)
    for clip in data["clips"]:
        start, trigger, end = ARCS[clip["coverage_source_id"]]
        if "reaction_arc" in clip:
            clip["action_arc"] = clip.pop("reaction_arc")
        clip["serves_dialogue_beats"] = SERVES_OVERRIDES.get(
            clip["coverage_source_id"], clip["serves_dialogue_beats"]
        )
        clip["action_arc"] = ACTION_OVERRIDES.get(
            clip["coverage_source_id"], clip["action_arc"]
        )
        clip["expression_arc"] = {"start": start, "trigger": trigger, "end": end}
        clip["performance_priority"] = "facial_delta > eyeline_delta > body_action"
        clip["expression_prompt"] = (
            f"facial expression changes visibly from {start} to {end} exactly when {trigger}; "
            "one readable emotional turn, natural micro-expression buildup, no frozen stare"
        )
        if end in {"失态", "惊慌", "震住", "恼怒"}:
            clip["large_expression_unlock"] = "exaggerated expression allowed, identity must remain stable"
        posture = clip["scale_and_posture"].get("chenji_posture", "")
        clip["scale_and_posture"]["chenji_posture"] = posture.replace(
            ", calm controlled confidence", ""
        )
        if clip["coverage_source_id"] == "E16-B34":
            clip["listener"] = "陈迹与白鲤"
        if clip["coverage_source_id"] == "E16-B28":
            clip["listener"] = "众官差"
        if clip["coverage_source_id"] in CROWD_REACTION_IDS:
            clip["coverage"] = "crowd_reaction"
    data["planned_new_sources"] = len(data["clips"])
    data["expression_arc_schema"] = "/Users/rogerwu/qingshan_short_drama/configs/expression_arc_vocabulary_20260712.json"
    data["expression_arc_hotfix"] = "APPLIED_20260712_CLAUDE_REDLINE_FIXED_PENDING_GENERATION"
    PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"updated={len(data['clips'])}")


if __name__ == "__main__":
    main()
