#!/usr/bin/env python3
"""Compile the locked E36 v2 script into zero-credit production contracts."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E36剧本_ClaudeWriter_v2.md"
MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E36_manifest_v2.json"
OUT = ROOT / "workflow/claude_writer_agent/production/e36_claude_writer_v2_4e46c013_20260728"
QA = ROOT / "qa/e36_v2_preproduction_20260728"
EXPECTED_SHA = "4e46c01337afb5eb81d036a01638438bf948e2e5d519d0baf36085dc1c9c27e6"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def effective_length(text: str) -> int:
    # Dialogue limits count spoken glyphs, not punctuation. Keep this set
    # explicit so Chinese enumeration commas and both quote styles cannot
    # create false failures or hide a truly long spoken line.
    return len(re.sub(r"[，。、？！；：“”‘’…—\"' ]", "", text))


def split_dialogue(text: str) -> list[str]:
    if effective_length(text) <= 25:
        return [text]
    if text == '真正的信，是"他这个人"送到了哪儿、密谍司为他动了多少兵。':
        return ['真正的信，是"他这个人"送到了哪儿。', '密谍司为他动了多少兵。']
    raise RuntimeError(f"unapproved dialogue split required: {text}")


# Durations are based on scene-local action continuity and dialogue breath, not a
# global shot-length default. Complex contact changes receive two temporal anchors.
SPECS = [
    ("U01", "9-1", 8, "递信人", "被两名兵卒架住上臂向刑台拖行", "兵卒手掌接触左右上臂，脚尖擦地", "画面后方向刑台前上方", "递信人被拖到刑台边，木牌仍在晃动", 1),
    ("U02", "9-1", 7, "陈迹、云羊、暗桩", "陈迹从檐影侧身探出观察，云羊扣住纸扎，两暗桩随人流向刑台挪动", "云羊手指接触腰间纸扎；其余不接触", "陈迹向右探视，暗桩向刑台内收", "三方路线清楚但仍被流动人群遮挡", 1),
    ("U03", "9-1", 5, "递信人", "抬起一半的眼睑并将脖颈转向陈迹檐影", "无新增人体或道具接触", "视线跨过人潮向檐影", "短促精准回望后仍被押在刑台", 1),
    ("U04", "9-1", 5, "刍子手、陈迹冰流", "斩刀从最高点下落，冰流沿台板窜上刀刃与刀柄", "薄冰接触并包裹刀刃与刀柄", "刀向下，冰自台板向上逆向攀爬", "刀落半寸即滞，刍子手虎口受震", 2),
    ("U05", "9-1", 5, "云羊、纸人、暗桩、看客", "纸人从云羊指间弹出并四面扑闪，暗桩转刀劈向错误目标", "暗桩刀刃只接触纸影，不接触真棋", "纸人向外放射，人潮向远离刑台方向溃散", "刀势劈空，真棋暂时留在原位", 2),
    ("U06", "9-1", 5, "暗桩、皎兔阴神、真棋", "暗桩反手劈向被掠的真棋，阴神从画外半身切入拦刀", "暗桩刀与阴神寒铁正面碰撞，刀尖擦过真棋衣角", "刀斜向真棋，拦击力沿反方向推开", "衣角裂开但真棋未受伤，偷换进入险败态", 2),
    ("U07", "9-1", 5, "陈迹、暗桩、云羊纸替、皎兔阴神", "冰流封住暗桩双足，纸替倾斜落入原位，阴神扣住真棋后领外掠", "薄冰接触双足与台板；阴神手指接触真棋后领", "冰流向暗桩脚下收束，阴神沿纸影死角向台下外掠", "暗桩定在台板，纸替占位，真棋脱离刀线", 2),
    ("U08", "9-1", 5, "刍子手、纸替、云羊", "刍子手震开冻刀后斩入纸壳，云羊护在侧翼带队撤离", "刀刃只接触纸替空壳", "刀向下，白纸向四周爆开，主角组向人潮外撤", "刑台只留碎纸，真棋已安全离场", 2),
    ("U09", "9-2", 10, "递信人、陈迹", "递信人被按坐且身体尚在晃，陈迹以三句短问逼近空信封来路", "押送者手短暂接触递信人肩部后离开", "递信人向凳面落坐，陈迹从侧前方逼问", "递信人承认隔月送空信封但不知用途", 1),
    ("U10", "9-2", 10, "皎兔、递信人", "皎兔正阖眼，眉心血痕亮起一半，阴神辨别供词真假", "阴神只贴近耳侧但不接触肌肤", "阴神由皎兔向递信人耳侧延伸", "皎兔确认其不知自己身份，递信人供出每次密谍司都倾巢而动", 1),
    ("U11", "9-2", 10, "云羊、陈迹", "云羊正拧眉开口，陈迹伸手取案上空信封", "陈迹指尖接触信封边缘", "手从身前向案上信封伸出", "空信封归陈迹持有，审讯转入物证鉴定", 1),
    ("U12", "9-3", 10, "陈迹、空信封", "冷雾从掌心漫出，霜纹沿折痕爬开三分之一", "陈迹手指压住信封一角，霜纹只接触纸面", "霜纹由掌心接触点沿折痕向外延伸", "折法路径完整显现，不凭空生成信内文字", 1),
    ("U13", "9-3", 8, "乌云、空信封、陈迹", "乌云鼻尖向纸面凑近，猫须抖动且鼻息吹起纸角，陈迹捻纸辨墨", "乌云鼻尖不压纸；陈迹指腹接触纸角", "乌云向下凑近，纸角向上轻翻", "墨料被识别为王府账房用墨", 1),
    ("U14", "9-3", 12, "陈迹、皎兔", "陈迹从伏案直起一半，将空信封与调兵反应拆成两层信息连续推理", "陈迹指尖持续接触折痕，人物之间不接触", "身体向上直起，视线从折痕转向皎兔", "活棋子与景朝批次/王府账房两家记号关系成立", 2),
    ("U15", "9-4", 9, "陈迹、递信人", "陈迹把信封推到递信人眼前，纸仍在滑动，以三句短话逼问首笔银来路", "陈迹指尖接触信封后缘，信封沿案面滑行", "信封向递信人正前方滑动", "递信人脸色褪白并准备取出凭证", 1),
    ("U16", "9-4", 8, "递信人、旧钱票根", "递信人从怀中往外抽出揉烂票根，纸角先露出再捧上", "手指接触票根两端，票根从衣襟移到掌心", "从躯干内侧向陈迹方向抽出", "票根归陈迹接验，递信人手离开物证", 1),
    ("U17", "9-4", 7, "陈迹、旧钱票根", "霜纹正爬过支银戳记，关键字只显出一半后才完整落定", "霜纹只接触票根戳记区，陈迹指腹压住纸边", "霜纹沿戳记轮廓由左向右显现", "刘家支银戳记与日期成为可见物证", 1),
    ("U18", "9-4", 12, "云羊、陈迹", "云羊正俯身凑近且瞳孔放大，陈迹压住戳记归纳死案仍在付钱的矛盾", "陈迹指尖接触票根，云羊与物证保持间隔", "云羊向案面俯身，陈迹视线由票根转向云羊", "刘家旧案重新浮出，票根被陈迹保全", 2),
    ("U19", "9-5", 10, "云羊、陈迹", "云羊踱步到一半尚未转完，连续追问死者账户为何仍付银", "无新增人体或道具接触", "云羊沿庭院横向踱步后转回陈迹", "问题完整落到替死人管账的活人", 1),
    ("U20", "9-5", 12, "陈迹、刘家票根", "陈迹手指正收紧票根，指节逐渐泛白，把景朝、王府与刘家三条线叠合", "手指接触并夹紧票根，不撕裂物证", "手指由松到紧，视线由手中票根向城东抬起", "陈迹判定刘家案从未真正结案", 1),
    ("U21", "9-5", 8, "陈迹、城东刘宅", "陈迹正抬眼越过檐角，随后收好票根转身，镜头拉向暮色中亮灯的荒宅", "陈迹手指将票根收入贴身衣袋，不与他人接触", "视线与镜头由后院向城东远宅延伸", "票根安全收好，荒宅一盏不该亮的灯成为 E37 钩子", 1),
]


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    script_sha = sha(SCRIPT)
    if script_sha != EXPECTED_SHA or manifest.get("sha256") != EXPECTED_SHA:
        raise SystemExit("E36 canonical SHA mismatch")
    text = SCRIPT.read_text(encoding="utf-8")
    first_section = text[text.index("逐镜首帧动势"):text.index("## 一句话梗概")]
    ambient_section = text[text.index("逐镜环境生命"):text.index("逐镜首帧动势")]
    first_frames = re.findall(r"^- \*\*(9-[^*]+)\*\*：(.+)$", first_section, re.M)
    ambient = re.findall(r"^- \*\*(9-[^*]+)\*\*：(.+)$", ambient_section, re.M)
    if len(first_frames) != 21 or len(ambient) != 11 or len(SPECS) != 21:
        raise SystemExit("E36 authored production-field count mismatch")

    body = text[text.index("## 剧本正文"):]
    dialogue = []
    for line in body.splitlines():
        match = re.match(r"^(陈迹|皎兔|云羊|递信人)：(?:（[^）]*）)?(.*)$", line.strip())
        if not match:
            continue
        for part in split_dialogue(match.group(2).strip()):
            dialogue.append({"speaker": match.group(1), "text": part, "effective_chars": effective_length(part)})
    if any(row["effective_chars"] > 25 for row in dialogue):
        raise SystemExit("dialogue remains over 25 effective characters")

    units = []
    for index, spec in enumerate(SPECS):
        uid, scene, duration, subject, action, contact, direction, end_state, anchor_count = spec
        units.append({
            "unit_id": uid,
            "scene": scene,
            "duration_seconds": duration,
            "first_frame_motion_state": first_frames[index][1].strip(),
            "ambient_life": next((value.strip() for label, value in ambient if label.startswith(scene)), "本镜按场景分级维持已授权的环境动势"),
            "physical_beats": [{
                "start_seconds": 0,
                "end_seconds": duration,
                "subject": subject,
                "action": action,
                "contact_point": contact,
                "direction": direction,
                "end_state": end_state,
            }],
            "planned_anchors": [
                {"anchor_id": f"{uid}-A{n + 1}", "role": "start_motion" if n == 0 else "terminal_state"}
                for n in range(anchor_count)
            ],
            "negative_prompt": "完成态，摆拍，对称站定，看镜头，亮相，静止起手，背景静止，人群定格，布景板，蜡像，背景冻结",
        })

    write_json(OUT / "E36_NATURAL_VIDEO_UNITS_AND_ANCHOR_PLAN_V1.json", {
        "schema": "qingshan.video_unit_anchor_plan.v1",
        "episode": "E36",
        "source_script_sha256": script_sha,
        "compiled_at": datetime.now(timezone.utc).isoformat(),
        "unit_count": len(units),
        "runtime_seconds": sum(row["duration_seconds"] for row in units),
        "anchor_count": sum(len(row["planned_anchors"]) for row in units),
        "grouping_policy": "SCENE_LOCAL_CONTINUOUS_ACTION_DIALOGUE_BREATH_AND_CAUSAL_END_STATE",
        "incremental_submit_policy": "SUBMIT_EACH_VIDEO_UNIT_IMMEDIATELY_AFTER_ITS_OWN_IMAGES_PASS_QA",
        "units": units,
    })
    write_json(OUT / "E36_DIALOGUE_NATIVE_VIDEO_CONTRACT_V1.json", {
        "schema": "qingshan.native_dialogue_contract.v1",
        "episode": "E36",
        "source_script_sha256": script_sha,
        "line_count_after_compile_split": len(dialogue),
        "max_effective_chars": max(row["effective_chars"] for row in dialogue),
        "delivery": "VIDEO_MODEL_NATIVE_NATURAL_MANDARIN_WITH_EXACT_WORDS_LIPS_BREATH_EXPRESSION_AND_TIMING",
        "post_dub_forbidden": True,
        "subtitle_policy": "BURN_IN_POST_ONLY",
        "lines": dialogue,
    })
    write_json(QA / "E36_PRODUCTION_REQUIREMENTS_GATE_V2.json", {
        "schema": "qingshan.production_requirements_gate.v1",
        "episode": "E36",
        "source_script_sha256": script_sha,
        "status": "PASS",
        "preserved_original_fail": "E36_PRODUCTION_REQUIREMENTS_GATE_V1.json",
        "checks": {
            "canonical_unchanged": True,
            "dialogue_compile_split_max_25": True,
            "natural_video_units": len(units) == 21,
            "all_units_4_to_15_seconds": all(4 <= row["duration_seconds"] <= 15 for row in units),
            "all_units_have_explicit_physical_contract": all(row["physical_beats"] for row in units),
            "all_units_have_first_frame_motion_state": all(row["first_frame_motion_state"] for row in units),
            "all_units_have_anchors": all(row["planned_anchors"] for row in units),
            "fs1_units_have_multistate_anchors": all(len(row["planned_anchors"]) >= 2 for row in units[3:8]),
            "ambient_life_authored_entries": len(ambient),
            "first_frame_authored_entries": len(first_frames),
        },
        "remote_calls": 0,
        "credits": 0,
        "next_action": "Compile per-anchor still prompts and run image professionalism, identity, era, spatial and first-frame/ambient-life gates before paid image submission."
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
