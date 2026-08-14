#!/usr/bin/env python3
"""Render review-ready E27 Seedance prompts from Writer Agent v0.4 contracts."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

from shot_prompt_professionalism_gate import detect_glyph_reveal_failures, validate_video_prompt


ROOT = Path("/Users/rogerwu/qingshan_short_drama")
COMPILED = Path(
    "/Users/rogerwu/Documents/Codex/2026-07-20/"
    "qingshan-professional-writer-agent/outputs/qingshan-writer-agent/"
    "examples/e27.agent-native.compiled.json"
)
SOURCES = ROOT / "workflow/writer_agent/e27_agent_native_v030_20260720/production/video_batch_v1/source_selection_24.json"
VOICES = ROOT / "configs/e27_voice_binding_registry_v1_20260720.json"
OUT_DIR = ROOT / "workflow/writer_agent/e27_agent_native_v040_20260720/review"
PROMPT_DIR = OUT_DIR / "prompts"
OUT_MD = OUT_DIR / "E27_VIDEO_GENERATION_PROMPTS_24_REVIEW.md"
OUT_JSON = OUT_DIR / "E27_VIDEO_GENERATION_PROMPTS_24_REVIEW.json"
QA_PATH = ROOT / "qa/e27_writer_agent_v040_video_prompt_review_20260720/E27_VIDEO_PROMPT_REVIEW_GATE.json"


CHARACTERS = {
    "c_chenji": "陈迹",
    "c_yao": "姚太医",
    "c_spy_leader": "密探头领",
    "c_soldiers": "铁甲兵",
    "c_jiaotu": "皎兔（女性本体及保持女性面容、兔耳状光影轮廓的阴神）",
    "c_baili": "白鲤",
    "c_guards": "王府档房守卫",
    "c_wuyun": "受伤的黑猫乌云",
    "c_scribe": "密谍司文书/文书残影",
}

PROPS = {
    "p_fake_order": "黑底密谍司伪造搜查令（纸面不可生成可读文字）",
    "p_ledger": "太平医馆药账",
    "p_blade": "制式刀",
    "p_register_fragment": "E26名册残页",
    "p_register": "暗册/被改成领赏表的名册",
    "p_key": "守卫腰间铜匙",
    "p_pressed_papers": "两张叠压留痕的纸",
    "p_rubbing": "压痕拓片及时辰签",
    "p_new_page": "文书正在写的新页与朱笔",
}

SCENES = {
    "E27-NATIVE-S01-CLINIC-DAY": "古代太平医馆大堂，白天，木格纸窗斜射清晰日光，干燥室内",
    "E27-NATIVE-S02-ALLEY-NIGHT": "王府档房外深巷，干燥晴夜，仅用檐下灯火与建筑遮蔽形成冷暖层次",
    "E27-NATIVE-S03-ARCHIVE-NIGHT": "王府档房内部，夜间室内，卷架、铜锁柜与烛火构成纵深",
    "E27-NATIVE-S04-ARCHIVE-CORNER-NIGHT": "王府档房卷架角落，夜间室内，门外火把影逼近",
    "E27-NATIVE-S05-CORRIDOR-NIGHT": "王府档房长廊，夜间室内，卷架、木柱与门洞形成深纵深",
    "E27-NATIVE-S06-WINDOW-NIGHT": "文书房窗外与长廊尽头，夜间，窗内实用灯火照亮执笔人剪影",
}

MOTION = {
    "lateral_track_with_subject": "横向平稳跟拍；只随主体位移，不做无动机漂移",
    "handheld_pressure_follow": "克制的手持压迫跟随；动作加速时短促响应，落点立即稳住",
    "snap_pan_to_consequence": "由动作触发快速甩镜至后果；甩镜前后主体清晰，不制造眩晕",
    "rack_focus_evidence_transfer": "以证据传递为因果进行焦点转移；焦点只在人物、道具和结果之间切换",
    "reverse_dolly_reveal": "反向移动揭示空间或真相；主体尺度与背景纵深同步展开",
    "crane_descend_to_action": "从较高地理关系下降至动作落点；下降服务于证据或身体接触",
    "parallax_push_through_foreground": "穿过前景遮挡形成视差推进；停在剧情证据而非人物空表情",
    "overhead_drift_to_evidence": "从俯视关系克制移向证据细节；保持纸面方向和手部动作可读",
}

SFX = {
    "metal blade ring and air cut": "刀刃金属鸣响与破风声",
    "layered armor plate impact": "多层甲片碰撞与受力闷响",
    "costume and surface movement specific to the performed action": "衣料、身体与现场表面的同步摩擦声",
    "paper fiber snap and page friction": "纸纤维脆响、翻页与摩擦声",
    "ice crystal creep and brittle frost crack": "冰晶蔓延与薄霜脆裂声",
    "hinge load and door impact": "门轴受力、门板撞击与木构回声",
    "single paw landing and paper claw contact": "单次猫爪落地及按住纸张的细响",
    "bound paper handling and cover knock": "册页抽动、封皮碰撞与纸张摩擦声",
    "brush tip drag and wet ink contact": "朱笔笔锋拖行与湿墨接触纸面的细声",
    "wood lattice strain and debris impact": "木窗格受力与碎屑碰撞声",
    "footfall matched to surface": "与木廊或窗台材质一致的脚步和落脚声",
}

# These beats remain strictly inside each Writer Agent story_event_boundary.
BEATS = {
    "E27-N01": [
        "超广角从前景药柜横移进入大堂：十余名铁甲兵挤满后景门廊，刀锋同时向诊案压低，先交代人数、空间与威胁方向。",
        "横移在诊案侧停住，假搜查令被密探头领重重拍落，刀尖压住药账；以纸、刀、账册同框的结果位收束。",
    ],
    "E27-N02": [
        "中近景建立姚太医、药账与对面刀锋的三角关系，手持仅保留轻微呼吸感。",
        "姚太医翻开药账，指腹沿批号栏滑动并准确停在尚未启用的空格；镜头短促跟随手部动作。",
        "落在指腹、空格与姚太医坚定目光的近景结果位，刀锋仍在画面边缘施压。",
    ],
    "E27-N03": [
        "中景锁住领头兵、药账和陈迹侧方入口；领头兵抬刀劈向药账。",
        "刀锋下落触发甩镜，陈迹从侧面错步切入，身体轴线清楚，双指在刀锋落案前夹停。",
        "甩镜终止于双指、静止刀锋和未被劈中的药账，保留刀身余颤，不延伸新招式。",
    ],
    "E27-N04": [
        "中近景从陈迹双指夹住刀锋起，焦点先锁刀刃与官印。",
        "冰流沿刀刃因果蔓延到官印，焦点跟随冰线转移；假令从印心脆裂，碎角离纸。",
        "陈迹将碎角弹回领头兵胸甲，焦点落在碎角撞甲的结果，陈迹说完对白后稳停。",
    ],
    "E27-N05": [
        "超广角反向后移揭示深巷尺度：皎兔贴墙闭目，巷道、檐口与远处灯火形成三层纵深。",
        "淡蓝阴神从她肩背完整分离并停住，女性面容和兔耳状光影轮廓清楚；本体位置不变。",
    ],
    "E27-N06": [
        "中近景以檐口作前景，女性阴神贴着屋檐快速追向送令兵，手持跟随保持方向连续。",
        "送令兵收刀转身迈出训练有素的一步，阴神在这一动作节点追平并观察其步法。",
        "镜头稳在送令兵收刀脚步与阴神回望本体的关系位，皎兔低声给出判断。",
    ],
    "E27-N07": [
        "从较高视角下降，建立白鲤、陈迹与两张纸在侧光前的位置关系。",
        "白鲤把假令碎角和E26残页精准叠合，镜头下降到手部与纸纤维层面，帘纹逐渐重合。",
        "落在两纸帘纹严丝合缝的近景证据位，白鲤只说结论并立即收纸。",
    ],
    "E27-N08": [
        "横向跟随陈迹进入屋脊与巷墙形成的狭缝暗影，皎兔与白鲤留在既定空间关系内。",
        "陈迹接过残页并系紧夜行衣腕口，动作利落；镜头停在收紧的腕口与残页被妥善收起的结果。",
    ],
    "E27-N09": [
        "超广角建立档房卷架、铜锁柜、陈迹与女性阴神的空间尺度，焦点先在柜门和第三层位置。",
        "女性阴神保持女性面容和兔耳光弧穿过铜锁柜门，焦点随她进入柜内并转向第三层空格。",
        "她回身将手指落在空格旁的新压封签，焦点停在封签压痕；对白后不展示额外册页内容。",
    ],
    "E27-N10": [
        "中景横向跟随两名守卫从卷架后转出，第一把刀刚出鞘，清楚交代陈迹与二人的距离。",
        "陈迹切入持刀侧，以冰指准确点中持刀腕；镜头随接触横移后停在腕部结霜、刀尚未完成出鞘的结果位，第二名守卫保持后续威胁但不提前攻击。",
    ],
    "E27-N11": [
        "较高视角看第二名守卫冲近、陈迹与卷架侧梁的地理关系。",
        "镜头下降随陈迹借侧梁旋身避开，守卫冲势从他身侧掠过；身体路径清楚、无瞬移。",
        "陈迹反手从第一人腰间摘下铜匙，落在钥匙离腰的近景结果位，不增加额外打斗。",
    ],
    "E27-N12": [
        "反向移动先建立铜锁柜、陈迹手中铜匙和皎兔阴神的位置；陈迹插匙抽出暗册。",
        "暗册离柜时烛光掠过被覆成领赏表的版式，镜头后移揭示裁改边缘；纸面保持无可读生成文字。",
        "皎兔阴神指向未干朱痕，陈迹与皎兔按顺序各说一次对白，最终停在朱痕和两人判断的证据位。",
    ],
    "E27-N13": [
        "超广角横移建立卷架角落、门缝与逼近的火把影，受伤黑猫乌云位于低处前景。",
        "乌云从卷架低处跃下，一爪准确按住两张叠纸；横移随跳跃结束，停在猫爪、叠纸与门影同框。",
    ],
    "E27-N14": [
        "中近景手持跟随陈迹从乌云爪下抽走叠纸，纸角受控不乱飞。",
        "陈迹把叠纸迎向斜光，冰流沿纸背浅铺；镜头保持纸面失焦，只让无字符轮廓的抽象浅凹反光掠过。",
        "焦点转到陈迹骤然收紧的眼神与沿凹痕停住的指尖；真相只由表演和对白传达，镜头不给纸面字形特写。",
    ],
    "E27-N15": [
        "镜头穿过前景卷轴形成视差，靠近叠纸上一处刚亮起的幽蓝命气压痕。",
        "陈迹将这处压痕与死亡拓序末端横向错开，动作直接展示先后不一致。",
        "停在两条序列明确分离的证据位，陈迹抬眼说出活口判断，光效不扩散成奇观。",
    ],
    "E27-N16": [
        "中近景从女性阴神的兔耳状光弧转焦到她伏向门缝的动作，女性身份保持稳定。",
        "焦点穿过门缝落在逐渐盖满缝隙的甲胄影；她急促报讯，画面停在封死退路的结果。",
    ],
    "E27-N17": [
        "超广角反向后移揭示长廊两端与破门守卫，守卫伸手抓住拓片一角。",
        "陈迹以肩抵住对方胸甲，双方发力，拓片被绷成笔直一线；镜头后移保留全身受力关系。",
        "停在肩甲接触、双方手位和完整拓片受力的空间结果，不让纸断裂。",
    ],
    "E27-N18": [
        "中景手持贴近双方僵持位置，陈迹压低重心，守卫仍握紧拓片。",
        "陈迹贴身肘击准确命中护甲接缝，冲击沿甲片传递，碎甲向后爆开但不伤及拓片。",
        "守卫握纸的手在冲击中松开，镜头随手部下坠后立即稳住；动作只完成一次。",
    ],
    "E27-N19": [
        "较高视角跟住松手后下落的拓片，陈迹伸手接住，皎兔阴神和文书残影在空间中可辨。",
        "镜头下降到胸口高度，陈迹将最早一格时辰签贴到文书残影胸前；停在时辰签、残影胸口与陈迹视线的证据位，陈迹说出身份判断。",
    ],
    "E27-N20": [
        "中近景横向跟随女阴神抬起兔耳光弧，将文书残影落笔动作框入光弧。",
        "沿同一方向移动展示落笔先亮、命气随后熄灭的严格先后，陈迹视线跟随证据。",
        "停在两段时间关系清楚的结果位；陈迹把拓片折入袖中并说完结论，阴神不替换成男性或兽形。",
    ],
    "E27-N21": [
        "超广角以长廊柱列和门洞建立纵深，陈迹与女性阴神贴着暗面疾行，焦点先在二人。",
        "二人向纵深尽头移动时，焦点从奔行主体转到亮着的文书房窗；停在窗内执笔人剪影、新页和长廊尺度同框的结果位，不提前写入或冻结朱笔。",
    ],
    "E27-N22": [
        "俯视建立执笔人的手、朱笔与新页第一行的方向关系，纸面不出现可读文字。",
        "朱笔落下并沿第一行移动，镜头克制下移贴近纸背；湿墨和笔锋动作同步。",
        "纸背在同一位置鼓起与活口相同的压痕，焦点停在压痕；皎兔对白来自画外既定位置。",
    ],
    "E27-N23": [
        "中近景从陈迹指尖起势，冰流穿过窗格，动作方向清楚。",
        "冰流接触朱笔尖端触发甩镜，笔尖冻结，未干的一点朱墨悬停在纸面上方；陈迹说完对白即转身。",
    ],
    "E27-N24": [
        "中景横向跟拍，追兵从长廊两端同时合拢，陈迹收回贯穿窗格的冰流，退路和窗台位置清楚。",
        "陈迹借一步冲势跃上窗台；镜头随身体横移并保持全身动作完整，女性阴神先一步穿墙探向窗外。",
        "追兵刀光在陈迹脚下交叉，陈迹越窗离开画面；镜头停在交叉刀光与空窗台后直接切黑，不追加新事件。",
    ],
}

SAFE_PRIMARY_ACTION_OVERRIDES = {
    "E27-N14": "陈迹抽走叠纸迎向斜光；纸背只呈无字符轮廓的抽象浅凹反光，他通过眼神骤变与指尖停顿确认关键线索。",
}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_json(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def weighted_ranges(duration: int, count: int) -> list[str]:
    weights = [0.7, 0.3] if count == 2 else [0.2, 0.55, 0.25]
    raw = [duration * weight for weight in weights]
    boundaries = [0.0]
    for value in raw[:-1]:
        boundaries.append(boundaries[-1] + value)
    boundaries.append(float(duration))
    return [f"{boundaries[i]:.1f}-{boundaries[i + 1]:.1f}s" for i in range(count)]


def render_audio(dialogues: list[dict], voice_registry: dict) -> tuple[str, list[dict]]:
    if not dialogues:
        return "无对白；所有人物仅保留与动作同步的呼吸和受力声，禁止旁白或额外台词。", []

    bound = []
    lines = []
    audio_index = 0
    for dialogue in dialogues:
        speaker_id = dialogue["speaker_id"]
        speaker = CHARACTERS[speaker_id]
        voice = voice_registry["speakers"].get(speaker_id, {})
        asset_id = voice.get("voice_asset_id")
        if asset_id:
            audio_index += 1
            slot = f"@音频{audio_index}"
            bound.append(
                {
                    "speaker_id": speaker_id,
                    "speaker_name": speaker,
                    "audio_slot": slot,
                    "voice_asset_id": asset_id,
                    "status": voice.get("status"),
                }
            )
            lines.append(
                f"{speaker}的台词音色严格参考{slot}（asset_id={asset_id}），只继承音色、年龄、共鸣、语速与气息，"
                f"不得照搬参考音频旧台词或背景声；按“{dialogue['performance']}”以自然普通话只说一次："
                f"“{dialogue['text']}”。"
            )
        else:
            lines.append(
                f"{speaker}当前无不可变声音资产，声音连续性明确为UNSUPPORTED，不得宣称系列声线一致；"
                f"本镜生成单次原生候选，按“{dialogue['performance']}”以自然普通话只说一次："
                f"“{dialogue['text']}”，后续必须通过声线画像QA后方可锁定。"
            )
    lines.append("对白按剧本顺序发生；非说话角色闭口，禁止换声、串声、旁白、复述、改词或增加对白。")
    return "".join(lines), bound


def render_prompt(video: dict, shot: dict, dialogues: list[dict], source: dict, voices: dict) -> tuple[str, list[dict]]:
    shot_id = video["shot_id"]
    duration = int(video["duration_seconds"])
    beats = BEATS[shot_id]
    time_ranges = weighted_ranges(duration, len(beats))
    audio_text, audio_bindings = render_audio(dialogues, voices)
    characters = "、".join(CHARACTERS[item] for item in shot["character_ids"])
    props = "、".join(PROPS[item] for item in shot["prop_ids"]) or "无独立道具"
    scene = SCENES[shot["scene_id"]]
    motion = MOTION[video["camera_motion"]]
    onsite = "；".join(SFX.get(item["cue"], item["cue"]) for item in video["onsite_sound_plan"])
    event_text = SAFE_PRIMARY_ACTION_OVERRIDES.get(shot_id, video["primary_action"])
    dialogue_slot = "对白按本镜对白与声音资产合同执行" if dialogues else "无对白"
    beat_lines = []
    for index, (time_range, beat) in enumerate(zip(time_ranges, beats), 1):
        framing = video["internal_shot_plan"][index - 1]["framing"]
        beat_lines.append(
            f"镜头{index}【{time_range}，景别={framing}，{motion}】：{beat}"
            f"{{{dialogue_slot}}}<现场声按本镜合同与接触点逐帧同步>"
        )

    prompt = (
        f"这是《青山》E27 {shot_id} 的 Seedance 2.0 Pro 多模态分镜视频。\n"
        f"【输入资产】[[image_1]]是本镜唯一构图、人物身份、年龄、性别、服装、妆发、道具、地点、时段、光线与空间轴线锚点；"
        f"不得替换、增删或重设计。人物槽：{characters}。场景槽：{scene}。道具槽：{props}。\n"
        f"【规格】目标时长{duration}s，竖屏9:16，720p，写实国漫古装武侠电影质感；画面锐利、构图稳定、动作连贯自然，"
        f"材质可辨，肤色自然，黑位有层次。禁止外部BGM。\n"
        f"【空间结构】本场的大远景定场由该场 grand-establishing 镜头承担；本镜严格服从已建立地理、景别和轴线。\n"
        f"【唯一剧情事件】{event_text} 只允许完成本镜事件，不得提前消费下一镜剧情，不得添加新人物、新动作或新结果。\n"
        f"【运镜逻辑】{motion}。运镜由主体动作和剪辑功能触发，不得套用缓慢推进，不得无动机漂移。\n"
        + "\n".join(beat_lines)
        + "\n"
        f"【对白与声音资产】{audio_text}\n"
        f"【现场声】{onsite or '与地点和身体动作严格同步的衣料、脚步及空间底噪'}。"
        f"声音必须与接触点、受力和停顿逐帧同步；保留符合{scene}的空间底噪，禁止外部BGM。\n"
        f"【色彩与光影】三角色控制 palette，动机光只来自锁定时段与现场实用光源；材质精细、黑位有层次、肤色自然。\n"
        f"【连续性】保持既定屏幕方向、人物身份、服装、道具归属、光源方向、场景地理、对白与动作因果；"
        f"前景遮挡、行动中景、地点真实后景构成三层纵深。环境次级反应只允许来自现场材质、衣料、火焰、纸张、尘屑或阴影。\n"
        f"力量必须通过人物受力及环境介质反馈呈现，禁止空泛光效替代动作。\n"
        f"【禁止】不得改变地点、时段、天气、人物、性别、年龄、服装、道具或剧情；不得以月亮、夜色、雾气或奇观替代剧情；"
        f"禁止慢动作、补帧感、循环动作、无动机漂移、瞬移、分身、双胞胎、肢体融合、穿模、外形漂移、可读文字、伪文字、"
        f"字幕、水印、Logo、拼贴、分屏、旁白和外部背景音乐。"
    )
    return prompt, audio_bindings


def main() -> None:
    compiled = load_json(COMPILED)
    sources_doc = load_json(SOURCES)
    voices = load_json(VOICES)
    shots = {item["shot_id"]: item for item in compiled["shot_contracts"]}
    sources = {item["shot_id"]: item for item in sources_doc["items"]}
    dialogues_by_shot: dict[str, list[dict]] = {}
    for item in compiled["dialogue_contracts"]:
        dialogues_by_shot.setdefault(item["shot_id"], []).append(item)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    QA_PATH.parent.mkdir(parents=True, exist_ok=True)

    rendered = []
    md = [
        "# E27 全部 24 个视频生成提示词（Writer Agent v0.4.0 审阅稿）",
        "",
        "- 状态：`REVIEW_ONLY_NOT_SUBMITTED`",
        "- Writer Agent：`v0.4.0` / Schema `1.3.0` / prompt `1.3.0`",
        "- 模型目标：`Seedance 2.0 Pro`，`9:16`，`720p`",
        "- 总量：24 镜 / 170 秒 / 16 条对白",
        "- 图片策略：24 张已选静帧全部保留，不重掷；N09 为条件机器采纳，其余 23 张 PASS",
        "- 声音策略：陈迹、白鲤使用锁定资产；皎兔使用 E27 机器采纳的临时不可变资产；姚太医、密探头领明确 UNSUPPORTED",
        "- 生产状态：本文件只供 Roger 检查，未向远端提交新视频生成",
        "",
    ]

    for video in compiled["video_generation_contracts"]:
        shot_id = video["shot_id"]
        shot = shots[shot_id]
        source = sources[shot_id]
        dialogues = dialogues_by_shot.get(shot_id, [])
        prompt, audio_bindings = render_prompt(video, shot, dialogues, source, voices)
        prompt_path = PROMPT_DIR / f"{shot_id}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")
        record = {
            "shot_id": shot_id,
            "duration_seconds": video["duration_seconds"],
            "scene_id": shot["scene_id"],
            "camera_motion": video["camera_motion"],
            "source_image": source,
            "audio_bindings": audio_bindings,
            "dialogue_continuity_status": [
                item["voice_continuity_status"] for item in video["asset_slot_bindings"]["audio"]["dialogue"]
            ],
            "prompt_file": str(prompt_path),
            "prompt_sha256": sha256_text(prompt + "\n"),
            "prompt": prompt,
            "status": "REVIEW_ONLY_NOT_SUBMITTED",
        }
        rendered.append(record)
        md.extend(
            [
                f"## {shot_id} · {video['duration_seconds']}s · {video['camera_motion']}",
                "",
                f"- 输入图：`{source['path']}`",
                f"- 图片 SHA-256：`{source['sha256']}`",
                f"- 图片审核：`{source['admission']}` / `{source['review_id']}`",
                f"- 音频绑定：`{json.dumps(audio_bindings, ensure_ascii=False) if audio_bindings else '无已绑定音频资产'}`",
                "",
                "```text",
                prompt,
                "```",
                "",
            ]
        )

    output = {
        "schema": "qingshan.e27.writer_agent_v040.video_prompt_review.v1",
        "episode": "E27",
        "status": "REVIEW_ONLY_NOT_SUBMITTED",
        "writer_agent_version": compiled["agent_version"],
        "schema_version": compiled["schema_version"],
        "source_compiled": str(COMPILED),
        "source_compiled_sha256": hashlib.sha256(COMPILED.read_bytes()).hexdigest(),
        "count": len(rendered),
        "total_duration_seconds": sum(item["duration_seconds"] for item in rendered),
        "items": rendered,
    }
    OUT_JSON.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    motions = Counter(item["camera_motion"] for item in rendered)
    prompt_texts = [item["prompt"] for item in rendered]
    professionalism_failures = {
        item["shot_id"]: validate_video_prompt(item["prompt"])
        for item in rendered
        if validate_video_prompt(item["prompt"])
    }
    glyph_failures = {
        item["shot_id"]: detect_glyph_reveal_failures(item["prompt"])
        for item in rendered
        if detect_glyph_reveal_failures(item["prompt"])
    }
    checks = {
        "exact_prompt_count_24": len(rendered) == 24,
        "unique_shot_ids_24": len({item["shot_id"] for item in rendered}) == 24,
        "duration_sum_170": sum(item["duration_seconds"] for item in rendered) == 170,
        "all_source_images_exist": all(Path(item["source_image"]["path"]).is_file() for item in rendered),
        "all_source_sha_exact": all(
            hashlib.sha256(Path(item["source_image"]["path"]).read_bytes()).hexdigest() == item["source_image"]["sha256"]
            for item in rendered
        ),
        "no_old_generic_start_phrase": all("从参考图既定姿态起动" not in text for text in prompt_texts),
        "no_subtle_push_in": all("subtle push-in" not in text for text in prompt_texts),
        "movement_class_count_at_least_8": len(motions) >= 8,
        "max_movement_share_le_35_percent": max(motions.values()) / 24 <= 0.35,
        "every_prompt_has_event_boundary": all("【唯一剧情事件】" in text for text in prompt_texts),
        "every_prompt_has_audio_policy": all("【对白与声音资产】" in text for text in prompt_texts),
        "every_prompt_forbids_external_bgm": all("禁止外部BGM" in text for text in prompt_texts),
        "glyph_reveal_visual_directive_zero": not glyph_failures,
        "shared_pre_submit_professionalism_gate_pass_24": not professionalism_failures,
    }
    qa = {
        "schema": "qingshan.e27.video_prompt_review_gate.v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "movement_distribution": dict(sorted(motions.items())),
        "max_movement_share": max(motions.values()) / 24,
        "glyph_reveal_failures": glyph_failures,
        "shared_pre_submit_professionalism_failures": professionalism_failures,
        "output_markdown": str(OUT_MD),
        "output_json": str(OUT_JSON),
        "rollback": "Old v0.3 video batches remain untouched as candidate/rollback evidence; this review set has not been submitted.",
    }
    QA_PATH.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(qa, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
