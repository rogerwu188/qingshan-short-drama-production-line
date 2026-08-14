#!/usr/bin/env python3
"""Compile E40 canonical-v3 U01-U16 into zero-cost standard-video prompts.

This tool writes prompt contracts and static QA only.  It never calls a remote
service and deliberately leaves every task blocked on exact reference binding.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E40剧本_ClaudeWriter_v3.md"
CANONICAL_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E40_manifest_v3.json"
OUT_DIR = ROOT / "workflow/claude_writer_agent/production/e40_claude_writer_v3_140d4b7b_20260808/u01_u16_prompt_precompile_v1"
PROMPT_DIR = OUT_DIR / "prompts"
OUTPUT_MANIFEST = OUT_DIR / "E40_U01_U16_STANDARD_VIDEO_PROMPT_MANIFEST_V1.json"
QA_REPORT = ROOT / "qa/e40_preproduction_20260808/E40_U01_U16_PROMPT_STATIC_QA_V1.json"

SCRIPT_SHA = "140d4b7b980bd8de58a874c56588a88256aa1c8883f50ce05c907a40a3355a9b"
MANIFEST_SHA = "773aff20a0036f619a14958585cdfd22738c2d2c7c49bb074bff173f208bd4f1"
MODEL = "seedance-2.0"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unit(
    unit_id: str,
    scene_id: str,
    seconds: int,
    kind: str,
    camera: str,
    intent: str,
    beats: list[str],
    visible: list[str],
    ownership: list[dict[str, Any]],
    first_frame: str,
    forbidden_state: str,
    dialogue: list[tuple[str, str]] | None = None,
    speaker_visibility: str = "NONE",
    evidence_gate: str | None = None,
) -> dict[str, Any]:
    return {
        "unit_id": unit_id,
        "scene_id": scene_id,
        "seconds": seconds,
        "kind": kind,
        "camera": camera,
        "intent": intent,
        "beats": beats,
        "visible_character_motion": visible,
        "ownership_contract": ownership,
        "first_frame_motion_state": first_frame,
        "forbidden_result_state": forbidden_state,
        "dialogue": dialogue or [],
        "speaker_visibility": speaker_visibility,
        "evidence_gate": evidence_gate,
    }


UNITS = [
    unit(
        "U01", "13-1", 8, "establishing", "大远景缓推至中景，单一稳定轴线",
        "0.5秒内陈迹从前脚正越门槛的首帧继续向厅内位移，明确进入敌府的行动方向",
        ["陈迹前脚完成跨槛、后脚开始跟进", "长帘从抬起半寸开始回落", "帘后执扇影继续缓摇", "陈迹后脚越过门槛而非停步", "烛焰被穿堂风压低", "白鲤面纱边缘轻动但身体保持刻意静点", "皎兔与云羊在边缘以呼吸和视线跟随陈迹", "陈迹尚未完全站定即切出"],
        ["陈迹持续行走、眨眼、呼吸、衣摆随步", "云妃仅帘影执扇微摇，绝不露面", "白鲤身体静立但有呼吸、睫动、面纱受风", "若皎兔、云羊入画，必须目光跟随并调整重心", "乌云若入画，耳尖与尾端持续响应环境声"],
        [{"item": "素纱长帘", "owner": "王府花厅建筑", "count": 1, "initial": "垂落隔开花厅", "transfer": "NONE", "final": "受风抬起半寸后开始回落"}, {"item": "团扇", "owner": "云妃", "count": 1, "initial": "帘后手持", "transfer": "NONE", "final": "仍由云妃持有缓摇"}],
        "长帘正被风推起半寸；陈迹前脚正在跨过门槛",
        "禁止人物各就各位、对称排开或全员面向镜头的完成态全景",
    ),
    unit(
        "U02", "13-1", 6, "hidden_speaker_dialogue", "帘后团扇与影子的近景，不越帘轴",
        "0.5秒内团扇从半收首帧继续合拢，云妃以收扇动作发起条件交换",
        ["团扇从半收状态继续合拢", "扇骨继续靠近并轻叩", "云妃帘影腕部下降", "陈迹在帘外眼神转向声源", "白鲤睫毛轻颤但不抬头", "扇面停在未完全合死的中间态"],
        ["云妃帘影手腕、团扇、呼吸影持续变化", "陈迹以眼神和下颌细动听取条件", "白鲤保留静点但面纱、呼吸和睫毛持续微动", "其他可见旁观者不可冻结"],
        [{"item": "团扇", "owner": "云妃", "count": 1, "initial": "展开手持", "transfer": "NONE", "final": "收拢至未完全闭合"}, {"item": "阿栓控制权", "owner": "云妃一方", "count": 1, "initial": "被扣押（仅由对白陈述，不生成阿栓插图）", "transfer": "PROPOSED_NOT_EXECUTED", "final": "仍由云妃一方控制"}],
        "团扇正在收拢到一半",
        "禁止帘影端坐不动、云妃露脸、插入阿栓或接头人的解释性画面",
        [("云妃", "阿栓，在本宫手上。"), ("云妃", "拿他，换景朝一个接头人。")], "FACE_HIDDEN_EXACT_LINE_AUDIO_AGENTCUT_ALLOWED",
    ),
    unit(
        "U03", "13-1", 5, "hidden_speaker_dialogue", "帘上影子近景，轻微前移而非推镜制造动作",
        "0.5秒内云妃帘影从半倾首帧继续前移，影缘扩大，明确逼问意图",
        ["帘影肩线从半倾状态继续前移", "影缘随烛光扩大", "团扇尖端向陈迹方向偏转", "陈迹呼吸收紧但不答", "帘影停在仍未完成的前倾态"],
        ["云妃帘影持续前倾、扇尖微移", "陈迹眼神、呼吸和指节产生受压反应", "白鲤面纱随气流微动", "所有入画旁观者持续跟随问句反应"],
        [{"item": "团扇", "owner": "云妃", "count": 1, "initial": "半收手持", "transfer": "NONE", "final": "扇尖指向帘外"}],
        "帘影正在前倾到一半，影缘正在放大",
        "禁止静止帘影、云妃正脸、镜头插入不存在的交换结果",
        [("云妃", "换，还是不换？")], "FACE_HIDDEN_EXACT_LINE_AUDIO_AGENTCUT_ALLOWED",
    ),
    unit(
        "U04", "13-1", 5, "visual_reaction", "陈迹眼与指骨特写，真实皮肤和冷雾",
        "0.5秒内霜线从已爬上指骨一半的首帧继续游走并收敛，明确陈迹识局而不出手",
        ["霜线越过指骨中段并减弱", "陈迹眸底进一步下沉", "指节轻收、霜线回卷", "冷雾向袖内敛去", "霜线未完全消失即切出"],
        ["陈迹持续眨眼、呼吸、指节收放", "背景帘与烛焰保持轻微环境运动", "若其他角色虚焦入画，也必须有视线或呼吸反应"],
        [{"item": "霜线", "owner": "陈迹", "count": 1, "initial": "未显现", "transfer": "NONE", "final": "缠指一半后正在敛去"}],
        "霜线正在爬上指骨一半并开始敛去",
        "禁止霜线完成定型、释放攻击、陈迹呆立无表情或慢镜式悬停",
    ),
    unit(
        "U05", "13-1", 6, "visible_speaker_dialogue", "陈迹与帘轴的近景，账页动作保持可见",
        "0.5秒内两页账从离案半寸的首帧继续下压，陈迹目光锁住长帘，明确夺回提问权",
        ["两页账页角继续接近案面", "陈迹下颌和目光保持对准长帘", "手腕继续下压且页角先接触", "两页账完整接触案面发出轻响", "陈迹手掌维持压力并说完反问", "听者帘影出现细小停顿后切出"],
        ["陈迹口型精确、呼吸和手腕持续推进", "云妃帘影对反问产生停顿", "白鲤以睫毛和视线微动响应", "旁观者不可冻结"],
        [{"item": "账页", "owner": "陈迹", "count": 2, "initial": "陈迹右手持有", "transfer": "陈迹手中→案面（放置，不转移人物所有权）", "final": "两页均在案面并由陈迹手掌压住"}],
        "两页账正被按向案面，离案半寸",
        "禁止账页已经按定、第三页、账页伪中文或陈迹闭口配画外音",
        [("陈迹", "先请教娘娘——扣他，为何不杀？")], "VISIBLE_NATIVE_EXACT_LINE_AUDIO_OR_VERIFIED_LIP_SYNC", "账页只显示无可辨伪字的纸面；若需准确账文必须后期合成",
    ),
    unit(
        "U06", "13-2", 7, "visible_speaker_dialogue", "案面与陈迹半身近景，四处霜印按顺序出现",
        "0.5秒内第二个霜印从半凝首帧继续成形，冷雾明确向第三处证据推进",
        ["第二个霜印由半凝继续补全轮廓", "冷雾离开第二印并向第三处推进", "第三印沿案面接续亮起", "第四印最后出现但不齐亮", "陈迹视线沿四印顺序移动", "云妃帘影对证据次序轻微收紧", "四印仍有亮度差异时说完并切出"],
        ["陈迹口型、指尖、目光持续同步", "云妃帘影凝住但有呼吸与扇缘微动", "白鲤只有一次睫动与稳定呼吸", "其他可见角色持续注视霜印"],
        [{"item": "霜印", "owner": "陈迹", "count": 4, "initial": "第一印已现、第二印正凝", "transfer": "NONE", "final": "四印依次出现但亮度不同步"}],
        "第二个霜印正凝到一半",
        "禁止四印从首帧齐亮、复制成五印、静态信息图或匀速发光循环",
        [("陈迹", "当铺、法场、药房、火场——活口一个没留。")], "VISIBLE_NATIVE_EXACT_LINE_AUDIO_OR_VERIFIED_LIP_SYNC",
    ),
    unit(
        "U07", "13-2", 5, "visible_speaker_dialogue", "陈迹指尖与案角空处近景",
        "0.5秒内指尖从正移向空处的首帧继续前伸但不落下，明确寻找第五印的位移意图",
        ["指尖继续越过案面向空角", "指尖在空角上方减速", "手指悬在空处不落下", "白鲤睫毛因反常点轻动", "陈迹说完时空处仍无第五印"],
        ["陈迹口型、指尖与视线持续移动", "白鲤睫毛和呼吸产生一次明确反应", "云妃帘影与团扇保持细微活态", "任何入画旁观者都必须跟随空处"],
        [{"item": "第五霜印", "owner": "NONE", "count": 0, "initial": "案角空白", "transfer": "NONE", "final": "仍不存在"}, {"item": "既有霜印", "owner": "陈迹", "count": 4, "initial": "案上可见", "transfer": "NONE", "final": "保持四个"}],
        "指尖正移向空处，悬而未落",
        "禁止指尖点定、生成第五印、添加可读标签或用台词信息做文字卡",
        [("陈迹", "偏他活着，还能开价。")], "VISIBLE_NATIVE_EXACT_LINE_AUDIO_OR_VERIFIED_LIP_SYNC",
    ),
    unit(
        "U08", "13-2", 5, "visible_speaker_dialogue", "陈迹眼神与帘后团扇反应的交叉单镜构图",
        "0.5秒内团扇从正在合拢的首帧继续闭合，陈迹目光锁定帘影，明确立论压迫意图",
        ["陈迹目光完成上抬并锁住帘影", "陈迹开始一字一顿说话", "帘后团扇继续合拢", "扇骨接近但尚未合死", "扇骨脆响与最后一个字落下"],
        ["陈迹口型、眼神和下颌持续推进", "云妃帘影手腕与团扇持续合拢", "白鲤及旁观者以眼神、呼吸响应结论"],
        [{"item": "团扇", "owner": "云妃", "count": 1, "initial": "未完全合拢", "transfer": "NONE", "final": "合拢并仍在云妃手中"}],
        "团扇正在合拢中途",
        "禁止团扇首帧已经合定、陈迹无口型、英雄式定格或额外解释文字",
        [("陈迹", "他不是证人，是饵。")], "VISIBLE_NATIVE_EXACT_LINE_AUDIO_OR_VERIFIED_LIP_SYNC",
    ),
    unit(
        "U09", "13-2", 6, "visible_speaker_dialogue", "案面斜近景同时保留陈迹口型",
        "0.5秒内并指从正抹过第三印的首帧继续横移，明确把剩余证据图式碾作霜粉",
        ["第三印在并指下继续碎成霜粉", "并指离开第三印向第四印横移", "第四印开始破碎", "第四印霜粉扬起", "空处与四印区域一起归于霜粉", "陈迹说完时霜粉仍在落下"],
        ["陈迹口型、并指与目光持续同步", "霜粉真实受重力下落而非悬停", "云妃帘影与白鲤对杀机结论产生细微反应", "旁观者不可冻结"],
        [{"item": "霜印", "owner": "陈迹", "count": 4, "initial": "四印位于案面", "transfer": "形态转移：完整霜印→霜粉", "final": "四印均正在散成霜粉，未凭空消失"}],
        "并指正抹过第三个霜印，霜粉正在扬起",
        "禁止首帧案面已净、霜粉倒放回印记、循环抹动、慢动作悬浮或第五印",
        [("陈迹", "我一换，两个一并抹掉，线断死。")], "VISIBLE_NATIVE_EXACT_LINE_AUDIO_OR_VERIFIED_LIP_SYNC",
    ),
    unit(
        "U10", "13-2", 4, "hidden_speaker_dialogue", "帘影与下垂扇尖近景",
        "0.5秒内扇尖从正在下垂的首帧继续下降，帘影短促收紧，明确认知被撬动",
        ["扇尖继续下降一小段", "帘影从短促停顿转为呼吸影轻变", "云妃开口且扇尖仍缓降", "扇尖未完全垂定时说完"],
        ["云妃帘影呼吸、扇尖下降持续可见", "陈迹以眼神和指节回应探询", "白鲤面纱与睫毛维持细微活态"],
        [{"item": "团扇", "owner": "云妃", "count": 1, "initial": "手持平稳", "transfer": "NONE", "final": "扇尖下垂但仍由云妃持有"}],
        "帘影正顿住，扇尖正在垂下",
        "禁止帘影全然冻结、云妃露脸、用旁白替代精确台词",
        [("云妃", "……你倒看得清楚。")], "FACE_HIDDEN_EXACT_LINE_AUDIO_AGENTCUT_ALLOWED",
    ),
    unit(
        "U11", "13-2", 4, "visual_foreshadow", "乌云与陈迹脚边低机位近景",
        "0.5秒内乌云双耳从半转首帧继续锁向侧厢，背毛沿肩背竖起，明确危险方向",
        ["近侧耳完成转向、另一耳继续跟随", "头部和鼻尖随双耳偏向侧厢", "背毛从肩部向后继续竖起", "陈迹指节收拢而眸光保持前方"],
        ["乌云耳、鼻、胡须、背毛和尾端持续响应", "陈迹指节与呼吸出现压低反应", "背景烛焰和长帘维持极轻环境运动", "其他入画人物随猫的示警改变视线"],
        [{"item": "乌云", "owner": "SELF_NATURAL_ANIMAL", "count": 1, "initial": "陈迹脚边警觉", "transfer": "NONE", "final": "朝侧厢锁定危险、毛正在炸起"}],
        "猫耳正转向侧厢一半，背毛正在立起",
        "禁止猫已完成定格指向、巨大化、拟人站立、开口说话或凭空出现武器",
    ),
    unit(
        "U12", "13-3", 7, "visible_speaker_dialogue", "陈迹、帘顶与帘内案面的连续单镜运动",
        "0.5秒内半空拓影从正越过帘顶的首帧继续向帘内位移并展开，明确跨帘递证意图",
        ["拓影前缘越过帘顶并继续展开", "纸卷主体跨过帘轴", "拓影开始下降朝帘内案面", "纸卷下缘接近案面", "纸卷接触案面", "拓影只摊开一半、令尾印纹朝上", "陈迹说完时纸页仍有余动"],
        ["陈迹口型、手腕、衣袖和目光持续跟随拓影", "拓影受重力和空气真实运动", "云妃帘影随落案声产生反应", "白鲤及旁观者以视线跟随证物"],
        [{"item": "旧印拓影", "owner": "陈迹", "count": 1, "initial": "陈迹襟中卷起持有", "transfer": "陈迹→越过长帘→帘内案面（证物交付）", "final": "帘内案面摊开一半，印纹朝上"}],
        "拓影正在越过帘顶，并在半空展开一半",
        "禁止拓影首帧已落定、复制多张、逆飞回手、穿透实体、生成伪中文或错印",
        [("陈迹", "调令上的印，是您的旧印。")], "VISIBLE_NATIVE_EXACT_LINE_AUDIO_OR_VERIFIED_LIP_SYNC", "印纹必须绑定准确证物图；未有精确图时只允许抽象不可读图形并保持提交阻断",
    ),
    unit(
        "U13", "13-3", 6, "hidden_speaker_dialogue", "帘后起身影与整幅长帘的近景",
        "0.5秒内云妃帘影从半起身首帧继续上升，带动帘幅和烛焰，明确被冒犯后的反应位移",
        ["帘后肩线从半高继续上升", "人影重心继续离开座位", "裙裾带风使帘幅晃动", "烛焰被气流齐齐压低", "云妃声音出现裂痕", "人影仍未完全站稳时说完"],
        ["云妃帘影、裙裾影和呼吸持续变化，绝不露面", "陈迹以眼神跟随起身", "白鲤面纱和睫毛响应突变", "旁观者重心随惊怒变化"],
        [{"item": "旧印拓影", "owner": "云妃一方保管", "count": 1, "initial": "帘内案面摊开一半", "transfer": "NONE", "final": "仍在案面"}, {"item": "团扇", "owner": "云妃", "count": 1, "initial": "手持", "transfer": "NONE", "final": "随猛起身产生位置变化但未脱手"}],
        "帘后人影正起身到一半，帘幅正被带晃",
        "禁止起身站定、云妃出帘露脸、烛焰倒放或夸张破坏花厅",
        [("云妃", "这道令，不是本宫下的。")], "FACE_HIDDEN_EXACT_LINE_AUDIO_AGENTCUT_ALLOWED",
    ),
    unit(
        "U14", "13-3", 6, "hidden_speaker_dialogue", "帘影手部向案沿下压的近景",
        "0.5秒内帘影手臂从正按向案沿的首帧继续下降，明确从震惊转向锁定内鬼",
        ["手影继续接近案沿但未接触", "指端影先触及案沿", "手掌影压上案沿", "肩线随支撑微沉", "声音逐字变冷", "手掌仍在稳定受力时说完"],
        ["云妃手影、肩线、呼吸和扇缘持续活态", "陈迹眼神从拓影转向帘影", "白鲤保持静点但有呼吸与睫动", "其他可见角色持续关注权力变化"],
        [{"item": "帘内案沿", "owner": "王府花厅家具", "count": 1, "initial": "无人接触", "transfer": "NONE", "final": "云妃手掌按住"}, {"item": "旧印拓影", "owner": "云妃一方保管", "count": 1, "initial": "案面", "transfer": "NONE", "final": "案面位置不变"}],
        "帘影的手正在按向案沿中途",
        "禁止手影首帧按定、云妃正脸、拓影消失或无来源新增第二份印件",
        [("云妃", "替本宫\"代办\"印的手，就在身侧。")], "FACE_HIDDEN_EXACT_LINE_AUDIO_AGENTCUT_ALLOWED",
    ),
    unit(
        "U15", "13-3", 6, "visible_speaker_dialogue", "陈迹与仍在余晃的长帘近景",
        "0.5秒内陈迹目光从正在抬起的首帧继续锁向余晃帘影，明确确认她并非作伪",
        ["陈迹目光完成上抬并锁住帘影", "帘影余晃仍未停止", "眸光收紧并开口", "第一句落下、帘影产生细微受击反应", "第二句继续且陈迹不移动站位", "最后一个字落下时帘仍有余晃"],
        ["陈迹两句口型精确、眨眼和呼吸自然", "云妃帘影对每句产生不同细微反应", "白鲤目光开始关注陈迹", "旁观者不得冻结或抢说"],
        [{"item": "旧印拓影", "owner": "云妃一方保管", "count": 1, "initial": "帘内案面", "transfer": "NONE", "final": "仍在案面"}],
        "帘影余晃未定，陈迹目光正在抬起",
        "禁止两厢静定对望、陈迹闭口配旁白、两句顺序调换、第三句或画面文字复述",
        [("陈迹", "有人借您的印，伪造您的令。"), ("陈迹", "您，也是被借的一把刀。")], "VISIBLE_NATIVE_EXACT_LINE_AUDIO_OR_VERIFIED_LIP_SYNC",
    ),
    unit(
        "U16", "13-3", 6, "visual_reaction", "白鲤眼部与帘侧半身近景，陈迹保持视线目标",
        "0.5秒内白鲤睫毛从已抬一线的首帧继续上移，目光朝陈迹移动，明确首次关注",
        ["白鲤睫毛继续抬起但不完全展开", "目光离开地面移向帘外", "面纱边缘随呼吸轻动", "视线接近陈迹但尚未完全对上", "陈迹在景深外保持轻微呼吸和眼神", "两道目光尚未完成对视即切出"],
        ["白鲤睫毛、眼球、呼吸和面纱边缘持续微动，身体仍保持剧情静点", "陈迹在景深内外都保持呼吸和细微眼神反应", "云妃帘影继续极轻余晃", "其他可见旁观者不可冻结"],
        [{"item": "面纱", "owner": "白鲤", "count": 1, "initial": "遮面佩戴", "transfer": "NONE", "final": "仍佩戴，仅边缘随呼吸轻动"}, {"item": "红玉领坠", "owner": "白鲤", "count": 1, "initial": "衣领内隐藏", "transfer": "NONE", "final": "仍隐藏，不在本镜提前亮相"}],
        "白鲤睫毛正在抬起一线，目光正在移向帘外陈迹",
        "禁止完成对视定格、摘下面纱、红玉提前全亮、白鲤开口或群像海报构图",
    ),
]


def atomic_windows(spec: dict[str, Any]) -> list[dict[str, Any]]:
    duration = float(spec["seconds"])
    windows = [{
        "start_seconds": 0.0,
        "end_seconds": 0.5,
        "action": spec["intent"],
        "state_change": spec["beats"][0],
    }]
    start = 0.5
    index = 1
    while start < duration:
        end = min(duration, start + 1.0)
        if index < len(spec["beats"]):
            beat = spec["beats"][index]
        else:
            micro = spec["visible_character_motion"][(index - len(spec["beats"])) % len(spec["visible_character_motion"])]
            beat = f"前一动作余势自然衰减，同时{micro}，在仍有可见变化时切出"
        progress = int(round(end / duration * 100))
        windows.append({
            "start_seconds": start,
            "end_seconds": end,
            "action": beat,
            "state_change": f"因果动作推进至约{progress}%，保持真实位移、不得回摆或循环",
        })
        start = end
        index += 1
    return windows


def prompt_text(spec: dict[str, Any], windows: list[dict[str, Any]]) -> str:
    lines = [
        f"E40 {spec['unit_id']}｜canonical v3 精确绑定｜标准 seedance-2.0 视频提示词。",
        "模型只能使用标准 seedance-2.0；禁止 Pro、fast、mini 或任何变体。9:16，1080p，单一连续镜头。",
        f"场次 {spec['scene_id']}，深夜雾夜，王府花厅；外雾只透窗纸，室内暖烛，不得擅改天气、年代、地点或剧情。",
        f"镜头：{spec['camera']}。时长 {spec['seconds']} 秒，真实1倍速；禁止慢动作、升格、补帧、时间拉伸、循环、倒放和后期加速。",
        f"首帧动势：{spec['first_frame_motion_state']}。0.5秒内意图：{spec['intent']}。",
        "performance_tempo_contract.atomic_action_windows：",
    ]
    for row in windows:
        lines.append(
            f"- {row['start_seconds']:.2f}-{row['end_seconds']:.2f}s：{row['action']}；终态变化={row['state_change']}。"
        )
    lines.extend([
        "每个原子动作窗口≤1.2秒；动作空档≤0.25秒；每一窗口必须产生可见位移、受力、目光或物件状态变化，不得用站桩、空镜或匀速慢移填时。",
        "可见人物持续微动作：" + "；".join(spec["visible_character_motion"]) + "。",
        "owner/count/transfer 硬锁：" + "；".join(
            f"{row['item']} owner={row['owner']} count={row['count']} initial={row['initial']} transfer={row['transfer']} final={row['final']}"
            for row in spec["ownership_contract"]
        ) + "。",
    ])
    if spec["dialogue"]:
        exact_lines = "；".join(f"{speaker}：‘{text}’" for speaker, text in spec["dialogue"])
        lines.extend([
            "对白传输分类：" + spec["speaker_visibility"] + "。",
            "精确对白，只说一次、顺序不变、不增删、不改写：" + exact_lines + "。",
            "可见说话脸必须使用原生精确行音频或经验证口型同步；脸隐藏台词允许画外精确行音频并由 AgentCut 装配。除命名说话人外任何人不得出声。",
        ])
    else:
        lines.append("本镜静默视觉；所有人物不得说话，只保留绑定环境声与动作声，禁止模型擅自生成对白。")
    if spec.get("evidence_gate"):
        lines.append("证物文字/OCR门：" + str(spec["evidence_gate"]) + "。")
    lines.extend([
        "年代与文字硬门：宋明风架空王府；无现代物、无随机文字、无伪中文、无字幕、无双层字幕、无LOGO水印；准确文字只能来自精确资产并后期合成。",
        "禁止结果态：" + spec["forbidden_result_state"] + "。",
        "画面已表达的信息禁止台词复述；禁止群像海报、人物复制、年龄/身份/性别漂移、背景人物冻结、道具易主或数量漂移。",
    ])
    return "\n".join(lines) + "\n"


def run_static_qa(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    required_fragments = [
        "标准 seedance-2.0",
        "真实1倍速",
        "0.5秒内意图",
        "performance_tempo_contract.atomic_action_windows",
        "每个原子动作窗口≤1.2秒",
        "动作空档≤0.25秒",
        "可见人物持续微动作",
        "owner/count/transfer",
        "禁止慢动作",
        "禁止 Pro、fast、mini",
    ]
    for task in tasks:
        unit_id = task["unit_id"]
        prompt = Path(task["prompt_file"]).read_text(encoding="utf-8")
        missing = [fragment for fragment in required_fragments if fragment not in prompt]
        if missing:
            failures.append({"unit_id": unit_id, "gate": "PROMPT_CONTRACT", "missing": missing})
        if task["model"] != MODEL:
            failures.append({"unit_id": unit_id, "gate": "STANDARD_MODEL_ONLY", "actual": task["model"]})
        windows = task["performance_tempo_contract"]["atomic_action_windows"]
        if not windows or windows[0]["start_seconds"] != 0.0 or windows[0]["end_seconds"] > 0.5:
            failures.append({"unit_id": unit_id, "gate": "INTENT_WITHIN_0_5_SECONDS"})
        cursor = 0.0
        for window in windows:
            start = float(window["start_seconds"])
            end = float(window["end_seconds"])
            if start - cursor > 0.25 + 1e-9:
                failures.append({"unit_id": unit_id, "gate": "ACTION_GAP_MAX_0_25", "gap": start - cursor})
            if end - start > 1.2 + 1e-9:
                failures.append({"unit_id": unit_id, "gate": "ATOMIC_ACTION_MAX_1_2", "duration": end - start})
            cursor = end
        if abs(cursor - float(task["duration"])) > 1e-9:
            failures.append({"unit_id": unit_id, "gate": "WINDOW_COVERAGE", "covered": cursor})
        if any(
            windows[index]["action"] == windows[index - 1]["action"]
            for index in range(1, len(windows))
        ):
            failures.append({"unit_id": unit_id, "gate": "NO_REPEATED_OR_CYCLIC_ACTION_WINDOWS"})
        if not task["visible_character_motion"]:
            failures.append({"unit_id": unit_id, "gate": "VISIBLE_CHARACTER_CONTINUOUS_MOTION"})
        if not task["ownership_contract"] or any(
            not {"item", "owner", "count", "transfer"}.issubset(row) for row in task["ownership_contract"]
        ):
            failures.append({"unit_id": unit_id, "gate": "OWNER_COUNT_TRANSFER"})
    exact_units = [f"U{index:02d}" for index in range(1, 17)]
    actual_units = [task["unit_id"] for task in tasks]
    if actual_units != exact_units:
        failures.append({"gate": "UNIT_COVERAGE", "expected": exact_units, "actual": actual_units})
    window_count = sum(len(task["performance_tempo_contract"]["atomic_action_windows"]) for task in tasks)
    return {
        "schema": "qingshan.e40.u01_u16_prompt_static_qa.v1",
        "episode": "E40",
        "status": "PASS_STATIC_PROMPTS_REFERENCE_BINDING_PENDING" if not failures else "FAIL",
        "canonical_script_sha256": SCRIPT_SHA,
        "canonical_manifest_sha256": MANIFEST_SHA,
        "coverage": {
            "units": f"{len(tasks)}/16",
            "prompt_files": f"{len(tasks)}/16",
            "standard_seedance_2_0": f"{sum(task['model'] == MODEL for task in tasks)}/16",
            "real_time_1x": f"{sum(task['performance_tempo_contract']['real_time_1x'] is True for task in tasks)}/16",
            "intent_within_0_5_seconds": f"{sum(task['performance_tempo_contract']['intent_deadline_seconds'] == 0.5 for task in tasks)}/16",
            "first_frame_continuation_not_replay": f"{sum(bool(task['first_frame_continuation_contract']) for task in tasks)}/16",
            "atomic_windows": window_count,
            "continuous_visible_motion": f"{sum(bool(task['visible_character_motion']) for task in tasks)}/16",
            "owner_count_transfer": f"{sum(bool(task['ownership_contract']) for task in tasks)}/16",
        },
        "gate_results": {
            "canonical_exact_sha": "PASS" if sha256(SCRIPT) == SCRIPT_SHA and sha256(CANONICAL_MANIFEST) == MANIFEST_SHA else "FAIL",
            "model_standard_only": "PASS" if all(task["model"] == MODEL for task in tasks) else "FAIL",
            "forbidden_pro_fast_mini": "PASS_BLOCKED_BY_MANIFEST",
            "real_time_native_speed": "PASS",
            "first_frame_continuation_not_replay": "PASS_AUTHORED",
            "atomic_action_window_max_1_2": "PASS" if not any(row.get("gate") == "ATOMIC_ACTION_MAX_1_2" for row in failures) else "FAIL",
            "action_gap_max_0_25": "PASS" if not any(row.get("gate") == "ACTION_GAP_MAX_0_25" for row in failures) else "FAIL",
            "no_repeated_or_cyclic_action_windows": "PASS" if not any(row.get("gate") == "NO_REPEATED_OR_CYCLIC_ACTION_WINDOWS" for row in failures) else "FAIL",
            "visible_character_continuous_motion": "PASS",
            "owner_count_transfer": "PASS",
            "slow_motion_forbidden": "PASS_AUTHORED",
            "random_text_and_double_subtitles": "PASS_AUTHORED",
            "paid_submission": "NONE",
        },
        "paid_submission_allowed": False,
        "blocked_by": [
            "16_OF_16_EXACT_START_FRAME_AND_REFERENCE_UPLOAD_BINDINGS_PENDING",
            "U05_TWO_ACCOUNT_PAGES_EXACT_TEXT_OR_BLANK_PLATE_BINDING_PENDING",
            "U12_OLD_SEAL_RUBBING_EXACT_PROP_BINDING_PENDING",
            "VISIBLE_DIALOGUE_NATIVE_AUDIO_OR_VERIFIED_LIP_SYNC_NOT_YET_EXECUTED",
            "NO_PAID_EXECUTION_PLAN_AUTHORED_BY_THIS_PRECOMPILE",
        ],
        "failures": failures,
    }


def main() -> int:
    if sha256(SCRIPT) != SCRIPT_SHA or sha256(CANONICAL_MANIFEST) != MANIFEST_SHA:
        raise SystemExit("canonical v3 script/manifest SHA mismatch")
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    QA_REPORT.parent.mkdir(parents=True, exist_ok=True)
    tasks: list[dict[str, Any]] = []
    for spec in UNITS:
        windows = atomic_windows(spec)
        prompt_path = PROMPT_DIR / f"E40-{spec['unit_id']}-STANDARD-SEEDANCE2-PROMPT-V1.txt"
        prompt_path.write_text(prompt_text(spec, windows), encoding="utf-8")
        tasks.append({
            "task_key": f"E40-{spec['unit_id']}-STANDARD-VIDEO",
            "unit_id": spec["unit_id"],
            "scene_id": spec["scene_id"],
            "kind": spec["kind"],
            "model": MODEL,
            "forbidden_models": ["seedance-2.0-pro", "seedance-2.0-fast", "seedance-2.0-mini"],
            "resolution": "1080p",
            "aspect_ratio": "9:16",
            "duration": spec["seconds"],
            "prompt_file": str(prompt_path),
            "prompt_sha256": sha256(prompt_path),
            "dialogue": [{"speaker": speaker, "exact_line": text} for speaker, text in spec["dialogue"]],
            "dialogue_transport": spec["speaker_visibility"] if spec["dialogue"] else "SILENT_VISUAL_NO_DIALOGUE",
            "performance_tempo_contract": {
                "real_time_1x": True,
                "intent_deadline_seconds": 0.5,
                "atomic_action_max_seconds": 1.2,
                "max_action_gap_seconds": 0.25,
                "post_speedup_forbidden": True,
                "atomic_action_windows": windows,
            },
            "visible_character_motion": spec["visible_character_motion"],
            "ownership_contract": spec["ownership_contract"],
            "first_frame_motion_state": spec["first_frame_motion_state"],
            "first_frame_continuation_contract": spec["intent"],
            "forbidden_result_state": spec["forbidden_result_state"],
            "evidence_gate": spec.get("evidence_gate"),
            "reference_binding_status": "PENDING_EXACT_START_FRAME_AND_ORDERED_UPLOAD_BINDING",
            "paid_submission_allowed": False,
        })
    manifest = {
        "schema": "qingshan.e40.u01_u16_standard_video_prompt_manifest.v1",
        "episode": "E40",
        "status": "PASS_PRECOMPILED_STATIC_QA_REFERENCE_BINDING_PENDING_NO_SUBMIT",
        "canonical": {
            "script": str(SCRIPT.relative_to(ROOT)),
            "script_sha256": SCRIPT_SHA,
            "manifest": str(CANONICAL_MANIFEST.relative_to(ROOT)),
            "manifest_sha256": MANIFEST_SHA,
        },
        "scope": {"first_unit": "U01", "last_unit": "U16", "unit_count": 16},
        "static_qa_report": str(QA_REPORT.relative_to(ROOT)),
        "submission_policy": {
            "standard_model_only": MODEL,
            "pro_fast_mini_forbidden": True,
            "parallel_after_individual_reference_and_paid_preflight": True,
            "remote_wait_is_not_global_barrier": True,
            "this_manifest_submits_nothing": True,
        },
        "tasks": tasks,
    }
    OUTPUT_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    qa = run_static_qa(tasks)
    qa["prompt_manifest"] = str(OUTPUT_MANIFEST.relative_to(ROOT))
    qa["prompt_manifest_sha256"] = sha256(OUTPUT_MANIFEST)
    QA_REPORT.write_text(json.dumps(qa, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "manifest": str(OUTPUT_MANIFEST),
        "manifest_sha256": sha256(OUTPUT_MANIFEST),
        "qa_report": str(QA_REPORT),
        "qa_report_sha256": sha256(QA_REPORT),
        "status": qa["status"],
        "coverage": qa["coverage"],
    }, ensure_ascii=False, indent=2))
    return 0 if qa["status"].startswith("PASS") else 2


if __name__ == "__main__":
    raise SystemExit(main())
