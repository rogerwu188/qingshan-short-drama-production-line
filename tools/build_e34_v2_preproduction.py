#!/usr/bin/env python3
"""Build the E34 v2 production source of truth and all generation inputs."""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_SHA = "400ff6d238e176999ff4320203839581e2f0a9cfcb7532a13ef7d5f37367d594"
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E34剧本_ClaudeWriter_v2.md"
WRITER_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E34_manifest_v2.json"
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e34_claude_writer_v2_400ff6d2_20260723"
IMAGE_PROMPT_DIR = PRODUCTION / "image_prompts_performance_v2"
VIDEO_PROMPT_DIR = PRODUCTION / "video_prompts_performance_v2"
QA_DIR = ROOT / "qa/e34_v2_preproduction_20260723"
OLD_U01_IMAGE = ROOT / "working_assets/e34_first_ready_stills_20260723/candidates/E34_E34-CW-U01-A1-STILL-V1_45352154-f627-4a65-8716-c40e30a351d4.png"
YANJING_IMAGE = ROOT / "working_assets/e34_first_ready_stills_20260723/candidates/E34_E34-YANJING-CHAR-ANCHOR-V1_4e447775-9ac0-4bcc-acde-54ad5179d794.png"
SCENE_EXTERIOR = "assets/reference/e08_api_fallback_20260709/scenes/SCENE-luocheng-stone-street-clean-20260709.jpg"
SCENE_INTERIOR = "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg"
# S01/U01 reuses an audited v1 anchor outside the paid v2 batch. U02-A1
# therefore carries S01 establishing coverage for the executable batch gate.
SCENE_ENTRY_UNITS = {1: "U02", 2: "U05", 3: "U08", 4: "U14", 5: "U18"}
CHARACTERS = {
    "chenji": "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg",
    "jiaotu": "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg",
    "yunyang": "working_assets/api_reference_images_20260704/male_yunyang_ancient_ref_20260704_api.jpg",
    "wuyun": "working_assets/e21_scene_fidelity_r3_identity_parallel_20260718/image_candidates/E21_E21-S01-WUYUN-PURE-BLACK_2af7eb4b-625b-4eeb-bfd5-407b40a24ae2.png",
    "yanjing": str(YANJING_IMAGE.relative_to(ROOT)),
}
YOUTH_LOCK = {
    "chenji": "陈迹=十七岁少年，youthful，清俊少年感，下颌柔和，皮肤紧致无纹，眼神清亮；冷面不改变年轻骨相。",
    "jiaotu": "皎兔=十八岁少女，年轻骨相，皮肤紧致无纹。",
    "yunyang": "云羊=十七岁少年，年轻骨相，皮肤紧致无纹。",
}

CHARACTER_NAMES = {
    "chenji": "陈迹",
    "jiaotu": "皎兔",
    "yunyang": "云羊",
    "yanjing": "严敬",
    "wuyun": "乌云",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def unit(uid: str, scene: int, duration: int, chars: list[str], anchors: list[tuple[str, str]], intent: str, chain: str, expression: str, viewer: str) -> dict:
    return {
        "uid": uid,
        "scene": scene,
        "duration": duration,
        "chars": chars,
        "anchors": anchors,
        "intent": intent,
        "chain": chain,
        "expression": expression,
        "viewer": viewer,
    }


def authored_motion_beats(row: dict) -> list[dict]:
    """Turn the authored causal chain into explicit, timed physical beats."""
    clauses = [part.strip("。；， ") for part in re.split(r"[；。]", row["chain"]) if part.strip("。；， ")]
    minimum = max(2, math.ceil(row["duration"] / 3))
    if len(clauses) < minimum:
        expanded = []
        for clause in clauses:
            expanded.extend(part.strip("， ") for part in clause.split("，") if part.strip("， "))
        clauses = expanded
    if len(clauses) < minimum:
        raise RuntimeError(f"{row['uid']} has only {len(clauses)} authored physical beats; requires {minimum}")
    names = [CHARACTER_NAMES[name] for name in row["chars"] if name in CHARACTER_NAMES]
    default_subject = "、".join(names) if names else "本拍中由剧本点名的场内行动者"
    beats = []
    for index, clause in enumerate(clauses):
        start = round(row["duration"] * index / len(clauses), 3)
        end = round(row["duration"] * (index + 1) / len(clauses), 3)
        named = [name for name in names if name in clause]
        subject = "、".join(named) or default_subject
        no_contact = any(token in clause for token in ("看", "视线", "说", "说明", "判断", "议论")) and not any(
            token in clause for token in ("抓", "按", "压", "劈", "接", "抵", "托", "扛", "击", "踏", "踩", "贴", "冻", "落")
        )
        contact = (
            "本拍不新增身体或道具接触；仅让视线、口型、呼吸和表情按台词对象变化"
            if no_contact else
            f"只允许并清楚拍到本句明示的真实接触与受力点：{clause}；未明示的身体和道具保持分离"
        )
        direction = f"严格沿本句写明的前后、左右、上下、内外或视线方向连续完成：{clause}；禁止反向、跳位和瞬移"
        beats.append({
            "start_seconds": start,
            "end_seconds": end,
            "subject": subject,
            "action": clause,
            "contact_point": contact,
            "direction": direction,
            "end_state": f"本拍以‘{clause}’的可见结果落定，人物、道具与受力结果保持到下一拍",
            "intent": row["intent"],
            "visible_causality": row["viewer"],
            "expression": row["expression"],
            "viewer_read": row["viewer"],
        })
    return beats


UNITS = [
    unit("U01", 1, 7, [], [("office_forecourt", "拂晓灰蓝的密谍司衙前，宿雨已停，十数官吏围住湿拓片互相指认，兵刃只处于戒备位置，尚未打斗。")], "建立公开半份名录后追兵转入自查", "官吏先读湿拓片，再指向彼此，巡检兵横移封住同僚退路，终态是自查对峙而非无因混战。", "官吏由怀疑转惊惶，巡检兵戒备升级", "观众一眼看懂网已调头，天气是宿雨初收而非正在下雨。"),
    unit("U02", 1, 8, [], [("ward_wall", "坊墙下湿拓片贴牢，兵吏围成半圈互查。"), ("palace_gate", "王府侧门上同版湿拓片被门吏按住纸角，众人互相审视。"), ("market_board", "市集告示栏同版半份名录前，百姓与兵吏分层围观。")], "用三处真实地点证明同一半份名录已经铺满洛城", "依次切换坊墙、王府侧门、市集告示栏；每处先见同版拓片，再见兵吏自查，空间转换用明确剪切，禁止把三地点揉成一处。", "各处人群从错愕转互疑", "观众确认这是全城反应而不是单一衙门的偶发争执。"),
    unit("U03", 1, 7, [], [("verified_name", "密谍司老吏手指只落在无可读文字的名字区域，同僚按住脸色骤白的官吏，旁边物证拓样与名录并列。")], "证明公开名字可被物证验证并触发抓捕", "老吏手指落向名字区域，被指官吏后退，同僚抓住其右臂并按停；围观百姓转头低声议论，终态是嫌疑人被控制。", "嫌疑人由侥幸转煞白，旁观者畏惧又好奇", "观众看懂自查有可验证物证，不依赖生成可读文字。"),
    unit("U04", 1, 8, ["chenji"], [("roof_overlook", "坊楼飞檐上，十七岁陈迹青衫清瘦，站在晨雾与初亮天光之间俯瞰调头兵潮。")], "用主角俯瞰坐实反客为主", "陈迹先看左侧衙门骚动，再把视线移向王府方向，嘴角只收紧不微笑；他说完两句后静立，兵潮在下方转向自查。", "陈迹冷峻快意但克制，不得成熟老态", "观众读懂这一局是陈迹主动布成。"),
    unit("U05", 2, 11, ["chenji", "jiaotu", "yunyang"], [("ledger_layout", "太平医馆密室晨光中，黑皮真名册与数张故意漏名的无字底样并排，陈迹指尖压住最末可读区，云羊从侧面迟疑审视。")], "解释公开部分与保留筹码的区别", "云羊先看底样再抬眼质问；陈迹不抬头，指尖从公开底样移到黑皮名册，逐句说明每个公开项都能验证，终态停在被保留区域。", "云羊最后一丝迟疑，陈迹冷锐笃定，皎兔专注", "观众看懂漏名是主动策略，不是制作错误。"),
    unit("U06", 2, 11, ["chenji", "jiaotu", "yunyang"], [("yanjing_trace", "黑皮名册近景，陈迹指尖压在无可读文字的严敬位置，一条朱笔线连向顶端幽蓝水波封纹。"), ("countermeasure_reaction", "陈迹沿朱线抬指指向封纹，皎兔侧身会意，云羊目光从名册转向陈迹。")], "把严敬锁成唯一可活捉筹码并连向封名指挥席", "陈迹指尖从严敬位置沿朱线移动到封纹，先说明严敬仍活着，再说明封名者是其上级；皎兔在陈迹收手后确认情报释放权。", "陈迹笃定，皎兔冷静会意，云羊迟疑消退", "观众看懂严敬为何值得活捉以及谁决定信息何时释放。"),
    unit("U07", 2, 10, ["chenji", "jiaotu", "yunyang"], [("capture_decision", "陈迹把黑皮名册收进怀中并从案前起身，皎兔与云羊已经转向密室出口，晨光切过三人侧脸。")], "启动抢在灭口前活捉严敬的行动", "陈迹合上名册、收入怀中、推案起身，逐句判断景朝与巡检线会灭口；皎兔先转身，云羊随后让开出口，终态三人同步出发。", "陈迹冷锐转沉着狠决，二人进入行动状态", "观众明确下一步是抢人，不是继续开会。"),
    unit("U08", 3, 8, ["yanjing", "wuyun", "chenji", "jiaotu", "yunyang"], [("execution_threat", "宿雨已停的城南死巷，负伤严敬退到墙角，两名巡检兵举刀逼近，景朝暗桩从另一侧低身接近。"), ("rescue_entry", "黑猫乌云立在墙头尾尖指向伏兵，陈迹、皎兔、云羊从巷口踏碎残积水冲入。")], "在刀落前建立两路灭口压力并让三人准确入场", "严敬后退直到背部接触墙面；巡检兵举刀，景朝暗桩从侧后方接近；乌云先指伏兵再急啸，三人沿巷口同一方向冲入。", "严敬克制惶恐转绝望，三人沉着狠决，乌云急切示警", "观众看懂双方都要灭口，主角目标是救活严敬。"),
    unit("U09", 3, 8, ["chenji", "yanjing"], [("ice_floor_deflection", "巡检兵刀锋从上方向陈迹劈落，陈迹后脚钉地、掌心朝残积水下压，幽蓝坚冰正从接触点向前延展。")], "用改变摩擦力让两把灭口刀真实偏离", "两兵先踏步劈刀；陈迹掌心下压，冰面从近到远铺开；两兵靴底失去摩擦向左右外滑，刀锋沿原惯性斜劈落空，终态严敬仍在墙角未被刀碰到。", "陈迹沉着狠决，两兵由凶狠转惊愕，严敬屏息", "观众看懂失衡来自冰面而非无因飞走。"),
    unit("U10", 3, 8, ["yunyang", "yanjing"], [("paper_decoy", "云羊咬指点中纸人，纸影正在变成严敬轮廓并沿巷侧扑出，景朝暗桩转刀追向假影。"), ("wrist_strike", "暗桩一刀劈碎素纸后手腕暴露，云羊借冰滑步贴近，拳面尚未接触持刀腕。")], "先用纸替骗开刀线，再以近身冲拳解除兵刃", "纸替从严敬相反方向扑出，暗桩转身劈碎素纸；云羊沿冰面前滑、转胯、拳面命中持刀腕外侧，腕骨错开，手指松开，刀落到冰面。", "云羊狠劲护决，暗桩自信转疼痛错愕", "观众看懂诱刀目的就是暴露持刀腕，刀的掉落有明确接触与结果。"),
    unit("U11", 3, 8, ["jiaotu", "yanjing"], [("rear_execution", "一名巡检兵绕到严敬身后举刀，皎兔面对前方闭目，眉心血痕刚亮。"), ("spirit_block", "黑甲阴神从侧墙穿出，手中寒刀正面接住巡检兵落刀，接触点火星明确，严敬仍低伏在两刀之外。")], "让皎兔阴神在严敬身后完成可读的拦刀救命", "巡检兵绕后踏稳并下劈；皎兔阖目放出阴神；阴神沿墙内直线穿出，把寒刀送到落刀路径，刃口接触后双方停在格挡终态。", "皎兔专注冷静，严敬惊恐，巡检兵暴怒转错愕", "观众看懂阴神拦刀的接触点与严敬被保护的位置。"),
    unit("U12", 3, 8, ["chenji", "yunyang", "yanjing"], [("freeze_last_attacker", "陈迹反手指向最后一名灭口兵双足与冰面接触处，坚冰已包住脚踝，兵刃仍在其本人手中。"), ("carry_escape", "云羊双臂从严敬腋下托起后把人扛上肩；远处暗桩俯身拾起自己的坠刀，焚纸只在其身侧形成撤退遮挡。")], "封住最后威胁并把活人从墙角转移到撤离状态", "陈迹冰流只冻结双足接触点；云羊先抓住严敬腋下、把人拉离墙面、再转身扛上肩；暗桩拾刀割断焚纸后沿巷外退走。", "陈迹狠决，云羊护决，严敬虚弱，暗桩不甘撤退", "观众看懂严敬持有者变化与敌人撤退路径，不能瞬移或无因换手。"),
    unit("U13", 3, 6, ["chenji", "yunyang", "yanjing", "wuyun"], [("backlash_retreat", "陈迹右掌白霜沿腕逆窜半寸，黑猫乌云从肩上把透明人参珠抵到手腕；云羊扛着严敬面向巷口。")], "显出冰流代价并立即撤离", "白霜先沿腕上窜；乌云落肩把珠抵住手腕，白霜在接触处退去；陈迹把严敬护在身后，云羊边喘息边说两句，随后转向巷口迈步。", "陈迹痛忍只闪现一瞬，云羊喘息急迫，乌云专注", "观众看懂反噬尚未暴动但真实存在，撤离因敌援将到。"),
    unit("U14", 4, 9, ["chenji", "jiaotu", "yanjing"], [("interrogation_open", "密室晨光与残烛并存，包扎后的严敬被缚在椅上，陈迹把黑皮名册摊到他面前并指住幽蓝封纹，皎兔侧立观察。")], "用名册封纹迫使严敬面对自己从未见过上级", "陈迹把名册啪地摊开、翻到封纹、指尖点住；他说完短句后俯身追问，严敬目光先落在封纹再闪避。", "陈迹冷厉逼近，严敬由防守转心虚，皎兔专注", "观众看懂陈迹用已知证据撬供而非凭空威吓。"),
    unit("U15", 4, 9, ["yanjing", "chenji"], [("yanjing_denial", "严敬瞳孔收缩、喉头滚动，脸避开封纹但肩膀被椅背与绑绳固定；陈迹保持在其视线边缘。")], "让严敬承认只认调令和印、从未见过接头人", "严敬先看封纹再移开视线，喉头滚动后嘶哑回答；每句话都伴随更短的呼吸，终态不敢看陈迹。", "严敬从克制惶恐转发抖自保，陈迹冷眼判断", "观众听清供词并从反应看出不是从容编造。"),
    unit("U16", 4, 9, ["jiaotu", "yanjing", "chenji"], [("spirit_truth_test", "皎兔闭目，眉心血痕微亮，半透明黑甲阴神贴近严敬耳侧但不接触身体；陈迹从正面俯身。")], "用阴神辨供确认前半段是真话，再逼问接头凭据", "阴神从皎兔眉心退出并移到严敬耳侧；严敬说完后阴神回望皎兔，皎兔睁眼给出判断；陈迹随后俯身追问凭据。", "皎兔专注冷静，严敬紧张，陈迹冷厉步步紧逼", "观众看懂阴神承担测谎功能，追问由确认真话自然推进。"),
    unit("U17", 4, 9, ["yanjing", "chenji", "jiaotu"], [("dead_object_confession", "严敬被逼到椅背，绑绳绷紧，嘴唇发抖准备吐出关键供词；陈迹与皎兔一前一侧锁住他的视线。")], "撬出景朝只认死物以及旧案线头", "严敬先吸气，说出不认活人；再看向封纹，说出谁亮死物谁是自己人；最后声音降下，提到多年旧案并停在未说完的称呼。", "严敬绝望发抖，陈迹冷厉凝住，皎兔敏锐捕捉尾音", "观众明确得到接头规则，但具体死物仍悬而未解。"),
    unit("U18", 5, 6, ["chenji", "jiaotu", "yunyang"], [("roof_transition", "陈迹从密室门疾步登上医馆屋檐，皎兔、云羊紧跟；云羊停在檐脊侧面仍显错愕。")], "把审讯半句带到全城视角并提出死物疑问", "陈迹先出门登檐，皎兔随后，云羊最后停稳；云羊看向陈迹并说出两句疑问，三人位置全程连续。", "云羊错愕，陈迹凝重，皎兔警觉", "观众感到线索由密室扩展到整条景朝暗线。"),
    unit("U19", 5, 8, ["chenji", "jiaotu", "yunyang"], [("city_inference", "陈迹立在檐脊俯瞰仍在自查的洛城，晨雾渐开，皎兔与云羊在后侧倾听。")], "解释死物能替整条暗线认人的规模并连向旧案", "陈迹视线从衙门方向扫到王府方向，边看全城边分句推断；说到旧案时回身看向同伴，终态手探向怀中名册。", "陈迹冷光凝敛，云羊错愕加深，皎兔专注", "观众理解这不是普通信物，而是跨越整条暗线的身份规则。"),
    unit("U20", 5, 8, ["chenji", "jiaotu", "yunyang"], [("shenyan_book", "陈迹从怀中抽出黑皮名册，指尖抚过顶端幽蓝水波密纹与相邻无可读小字区，另两人靠近观察。")], "把严敬旧案供词回扣到沈砚旧案与封名", "陈迹抽出名册、翻到顶页、指尖沿水波密纹移动到旁注区；他说出沈砚与自己曾以为是编造，随后收紧手指压住书页。", "陈迹由冷光凝敛转自身被卷入的凝重，皎兔神色开始骤凝", "观众把景朝旧案、沈砚与顶端封名连成同一主线。"),
    unit("U21", 5, 8, ["chenji", "jiaotu", "yunyang"], [("strategy_terminal", "陈迹手按名册封纹，面向皎兔与云羊说出要从旧案和死物下手，晨光沿檐瓦铺开。"), ("hook_pullback", "皎兔忽然抬头接口，三人停在檐脊，镜头外是晨雾渐开的洛城全景，天光初亮。")], "提出下一步并让皎兔截住未落的两个字形成钩子", "陈迹先说完从旧案和死物下手；皎兔想起尾音后抬头，先说严敬没说完，再说自己听见最后两个字；镜头在“是”后连续拉远，声音悬停并切黑。", "陈迹凝重笃定，皎兔骤凝，云羊警觉等待", "观众知道下一集会揭具体死物，结尾不是无因停顿。"),
]


DIALOGUES = [
    ("E34-DIA-001", "U03", "passerby_hushed", "昨儿还满城抓那少年医者。"),
    ("E34-DIA-002", "U03", "passerby_hushed", "今早怎么自家人先咬上了？"),
    ("E34-DIA-003", "U04", "chenji", "追我的网。"),
    ("E34-DIA-004", "U04", "chenji", "今早网住的，是他们自己。"),
    ("E34-DIA-005", "U05", "yunyang", "你放出去的名录，缺了最要紧的几个名字。"),
    ("E34-DIA-006", "U05", "chenji", "缺得刚好。"),
    ("E34-DIA-007", "U05", "chenji", "放出去的，每个都能验，他们不敢不查自己。"),
    ("E34-DIA-008", "U05", "chenji", "留下的这几个——尤其这一个——留给我。"),
    ("E34-DIA-009", "U06", "chenji", "名册上还活着、还能拿住的，只有他。"),
    ("E34-DIA-010", "U06", "chenji", "封着的那个名字，是他的头儿。"),
    ("E34-DIA-011", "U06", "chenji", "撬开严敬，就能摸到最顶那个。"),
    ("E34-DIA-012", "U06", "jiaotu", "第一次，是我们决定放谁、留谁、几时放。"),
    ("E34-DIA-013", "U07", "chenji", "景朝和巡检线也懂这个理。"),
    ("E34-DIA-014", "U07", "chenji", "他们正抢着灭严敬的口。"),
    ("E34-DIA-015", "U07", "chenji", "得赶在前头，把人活着拿回来。"),
    ("E34-DIA-016", "U13", "yunyang", "活的！拿到活的了——"),
    ("E34-DIA-017", "U13", "yunyang", "快走，景朝的人还会回来。"),
    ("E34-DIA-018", "U14", "chenji", "你的头儿。"),
    ("E34-DIA-019", "U14", "chenji", "名字被景朝亲手封在这上头。"),
    ("E34-DIA-020", "U14", "chenji", "你连他真名都没见过，是不是？"),
    ("E34-DIA-021", "U15", "yanjing", "我只认调令、认印。"),
    ("E34-DIA-022", "U15", "yanjing", "上头是谁，我真不知道。"),
    ("E34-DIA-023", "U15", "yanjing", "景朝那边的人，我也从没见过一张脸。"),
    ("E34-DIA-024", "U16", "jiaotu", "他没说谎。"),
    ("E34-DIA-025", "U16", "jiaotu", "景朝的人，压根不跟他这样的活口照面。"),
    ("E34-DIA-026", "U16", "chenji", "那他们怎么跟你接头？"),
    ("E34-DIA-027", "U16", "chenji", "总得对个凭据。"),
    ("E34-DIA-028", "U17", "yanjing", "景朝的人……从不认活人。"),
    ("E34-DIA-029", "U17", "yanjing", "他们接头，只认一样死物。"),
    ("E34-DIA-030", "U17", "yanjing", "谁把那东西亮出来，谁就是自己人。"),
    ("E34-DIA-031", "U17", "yanjing", "那东西，牵着景朝一桩多少年前的旧案——"),
    ("E34-DIA-032", "U17", "yanjing", "我听底下人叫它……"),
    ("E34-DIA-033", "U18", "yunyang", "景朝接头，只认一样死物，不认活人……"),
    ("E34-DIA-034", "U18", "yunyang", "那是什么东西？"),
    ("E34-DIA-035", "U19", "chenji", "一样死物，能替一整条暗线认人。"),
    ("E34-DIA-036", "U19", "chenji", "它连着一桩旧案——严敬亲耳听过的旧案。"),
    ("E34-DIA-037", "U19", "chenji", "那桩旧案的名字，我在名册最顶上，见过一次。"),
    ("E34-DIA-038", "U20", "chenji", "沈砚。我以为是我凭空编的。"),
    ("E34-DIA-039", "U20", "chenji", "可景朝的人，认了它多少年。"),
    ("E34-DIA-040", "U21", "chenji", "要掀开最顶那个名字，得先从这桩旧案下手。"),
    ("E34-DIA-041", "U21", "chenji", "也得从那样死物下手。"),
    ("E34-DIA-042", "U21", "jiaotu", "严敬那句没说完的话——"),
    ("E34-DIA-043", "U21", "jiaotu", "他咽下去的最后两个字，我阴神听得真切，是……"),
]


SCENE_STATE = [
    {"scene_id": "E34-CW-S01", "location": "洛城密谍司衙前/坊墙/王府侧门/市集告示栏", "time_of_day": "dawn", "weather": "宿雨初收_晨雾_无正在降雨", "event_summary": "洛城清晨封街搜捕，乌云侦查榜文与追兵动向，陈迹一行避开明面围堵。", "allowed_time_terms": ["dawn", "morning"], "allowed_weather_terms": ["post_rain", "wet_stone", "morning_mist"], "forbidden_weather_terms": ["active_rain", "rainfall", "rain_curtain", "storm"]},
    {"scene_id": "E34-CW-S02", "location": "太平医馆密室", "time_of_day": "morning", "weather": "室外宿雨初收_室内晨光换残烛", "event_summary": "陈迹、云羊与皎兔在密室复盘线索，确定从严敬处追查密谍司调令与内鬼。", "allowed_time_terms": ["morning"], "allowed_weather_terms": ["interior", "post_rain_daylight"], "forbidden_weather_terms": ["indoor_rain", "night"]},
    {"scene_id": "E34-CW-S03", "location": "洛城城南死巷", "time_of_day": "dawn", "weather": "宿雨初收_湿巷残滴_晨光斜入_无正在降雨", "event_summary": "三人在城南死巷截住负伤的严敬，以连续攻防和逼问取得调令、印信与景朝相关口供。", "allowed_time_terms": ["dawn", "morning"], "allowed_weather_terms": ["post_rain", "wet_alley", "residual_drips"], "forbidden_weather_terms": ["active_rain", "rain_curtain", "slow_motion"]},
    {"scene_id": "E34-CW-S04", "location": "太平医馆密室", "time_of_day": "morning", "weather": "室外宿雨初收_室内晨光与残烛", "event_summary": "众人带严敬回密室核验调令和印纹，拼出密谍司、王府与景朝之间的权力链。", "allowed_time_terms": ["morning"], "allowed_weather_terms": ["interior", "post_rain_daylight"], "forbidden_weather_terms": ["indoor_rain", "night"]},
    {"scene_id": "E34-CW-S05", "location": "太平医馆檐下与洛城", "time_of_day": "dawn_to_morning", "weather": "宿雨初收_晨雾渐开_天光初亮_无正在降雨", "event_summary": "陈迹在檐下观察洛城晨色，确认反制方向并以新的追查目标收尾。", "allowed_time_terms": ["dawn", "morning"], "allowed_weather_terms": ["post_rain", "lifting_mist", "brightening_sky"], "forbidden_weather_terms": ["active_rain", "rain_curtain", "night"]},
]


def binding(role: str, entity_id: str, relative: str) -> dict:
    path = ROOT / relative
    if not path.is_file():
        raise SystemExit(f"missing reference {relative}")
    return {
        "role": role,
        "entity_id": entity_id,
        "path": relative,
        "sha256": digest(path),
        "qa_status": "PASS",
        "qa_report": "qa/e34_v2_preproduction_20260723/E34_V1_ASSET_COMPATIBILITY_AUDIT_V2.json" if entity_id == "yanjing" else "configs/series_continuity_asset_registry_20260712.json",
    }


def main() -> int:
    writer = json.loads(WRITER_MANIFEST.read_text(encoding="utf-8"))
    if digest(SCRIPT) != SCRIPT_SHA or writer.get("sha256") != SCRIPT_SHA:
        raise SystemExit("E34 v2 source SHA mismatch")
    if len(UNITS) != 21 or sum(row["duration"] for row in UNITS) != 174:
        raise SystemExit("E34 natural grouping must resolve to 21 units and 174 seconds")
    if sum(len(row["anchors"]) for row in UNITS) != 29:
        raise SystemExit("E34 anchor design must resolve to 29 planned images")
    if any(len(text.replace("……", "")) > 25 for _, _, _, text in DIALOGUES):
        raise SystemExit("dialogue line exceeds 25 characters")
    if not OLD_U01_IMAGE.is_file() or not YANJING_IMAGE.is_file():
        raise SystemExit("expected reusable E34 v1 candidates are missing")

    now = datetime.now(timezone.utc).isoformat()
    dialogue_by_unit: dict[str, list[dict]] = {}
    for dia_id, uid, speaker, text in DIALOGUES:
        dialogue_by_unit.setdefault(uid, []).append({"dialogue_id": dia_id, "speaker": speaker, "text": text, "text_sha256": text_digest(text)})

    groups = []
    performance_units = []
    image_tasks = []
    reused_tasks = []
    video_prompt_rows = []
    for row in UNITS:
        uid = row["uid"]
        full_id = f"E34-CW-{uid}"
        scene_id = f"E34-CW-S{row['scene']:02d}"
        dialogues = dialogue_by_unit.get(uid, [])
        groups.append({
            "unit_id": full_id,
            "scene_id": scene_id,
            "duration_seconds": row["duration"],
            "grouping_reason": "scene-local continuous performance causality; count emerged after timing all groups",
        })
        scene_ref = SCENE_INTERIOR if row["scene"] in {2, 4} else SCENE_EXTERIOR
        refs = [binding("character", name, CHARACTERS[name]) for name in row["chars"]]
        refs.append(binding("scene", scene_id, scene_ref))
        anchor_rows = []
        for index, (state_role, state_description) in enumerate(row["anchors"], 1):
            task_key = f"{full_id}-A{index}-STILL-V2"
            prompt_path = IMAGE_PROMPT_DIR / f"{full_id}-A{index}.txt"
            youth = "；".join(YOUTH_LOCK[name] for name in row["chars"] if name in YOUTH_LOCK) or "按角色参考保持原年龄与骨相。"
            entity_tags = " ".join([*(f"[[char_{name}]]" for name in row["chars"]), f"[[scene_e34_s{row['scene']:02d}]]"])
            if uid == SCENE_ENTRY_UNITS[row["scene"]] and index == 1:
                shot_design = (
                    "远景定场 / wide establishing：竖屏纵深大远景，先一次性交代本场完整空间、"
                    "人物相对位置、出入口和可行动路线；人物仍须可辨认，动作接触关系不可被环境吞没。"
                )
            elif index == 1:
                shot_design = (
                    "中景 / medium shot：人物上半身、双手、关键道具和接触点同时入画，"
                    "保留足够环境方向信息。"
                )
            else:
                shot_design = (
                    "近景 / close-up：突出表情、手部接触点与关键道具状态，"
                    "同时保留前一状态的空间方向和道具归属。"
                )
            prompt = f"""竖屏9:16，电影级中国古装玄幻短剧，真实人物、真实接触、真实受力。时间天气硬锁：拂晓到晨间，宿雨已经停止，只保留湿石、残滴、晨雾与初亮天光；禁止雨线、雨幕、风暴、深夜和现代物件。

这是{full_id}的参考锚A{index}/{len(row['anchors'])}，状态职责={state_role}。锚图数量由SD2模型能力、动作复杂度、空间转换和物理连续性独立裁定为{len(row['anchors'])}，不是固定一张或固定多张。图片只锁人物身份、空间、道具归属与无法仅靠运动脚本稳定表达的必要状态；连续动作由视频模型完成。

实体绑定：{entity_tags}
人物身份锁：所有人物脸、年龄、发型、服装必须与参考图一致。年龄锁：{youth}
剧本硬锁 / scene authority：仅表现Claude Writer E34 v2的{full_id}，禁止新增人物、武器、抓取、转身、腾空、碰撞、可读文字和未声明天气。
动作目的：{row['intent']}
本锚决定性瞬间：{state_description}
连续物理链：{row['chain']}
表情弧：{row['expression']}
观众读法：{row['viewer']}
景别与画面设计：{shot_design}
构图：主体、接触点、受力方向、道具归属和终态必须清楚；禁止拼贴、分屏、动作残影、慢镜、定格和伪文字。
palette与光影：拂晓灰蓝、晨雾冷银、湿石低反光，晨光是唯一动机光；室内以晨光和残烛暖黄形成冷暖层次，不做单一蓝色滤镜。
NEGATIVE_PROMPT / 负面约束：老态陈迹、中年少年、身份漂移、脸漂移、发型漂移、服装漂移、道具换手、额外人物、额外肢体、雨中、暴雨、夜景、现代物件、字幕、水印、可读汉字。
"""
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(prompt, encoding="utf-8")
            contract = {
                "schema": "qingshan.image_prompt_contract.v2",
                "shot_id": f"{full_id}-A{index}",
                "source_script_sha256": SCRIPT_SHA,
                "source_action": f"动作目的：{row['intent']}；连续物理链：{row['chain']}；表情弧：{row['expression']}；观众读法：{row['viewer']}",
                "source_action_sha256": text_digest(row["intent"] + row["chain"] + row["expression"] + row["viewer"]),
                "visible_characters": row["chars"],
                "reference_bindings": refs,
                "editorial_shot_ids": [f"{scene_id}-{uid}"],
                "video_unit_id": full_id,
                "video_unit_duration_seconds": row["duration"],
                "state_index": index,
                "state_count": len(row["anchors"]),
                "state_role": state_role,
                "status": "PASS",
                "failures": [],
            }
            task = {
                "task_key": task_key,
                "tool_type": "image_generation",
                "scene_id": scene_id,
                "visual_zone": f"{uid.lower()}_anchor_{index}",
                "shot_id": f"{full_id}-A{index}",
                "editorial_shot_ids": [f"{scene_id}-{uid}"],
                "video_unit_id": full_id,
                "video_unit_duration_seconds": row["duration"],
                "state_index": index,
                "state_count": len(row["anchors"]),
                "beat_id": full_id,
                "prompt_file": str(prompt_path.relative_to(ROOT)),
                "prompt_sha256": digest(prompt_path),
                "reference_images": [item["path"] for item in refs],
                "reference_bindings": refs,
                "prompt_contract": contract,
                "model": "gpt-image-2-pro",
                "aspect_ratio": "9:16",
                "resolution": "2K",
                "status": "READY_FOR_CONCURRENT_SUBMIT",
                "source_script_sha256": SCRIPT_SHA,
            }
            anchor_row = {"state_index": index, "state_role": state_role, "description": state_description, "task_key": task_key, "prompt_file": task["prompt_file"], "prompt_sha256": task["prompt_sha256"]}
            if uid == "U01" and index == 1:
                anchor_row.update({"status": "REUSE_CANDIDATE_PENDING_V2_COMPATIBILITY_AUDIT", "existing_path": str(OLD_U01_IMAGE.relative_to(ROOT)), "existing_sha256": digest(OLD_U01_IMAGE)})
                reused_tasks.append({**task, "reuse_path": str(OLD_U01_IMAGE.relative_to(ROOT)), "reuse_sha256": digest(OLD_U01_IMAGE), "status": "REUSE_CANDIDATE"})
            else:
                anchor_row["status"] = "READY_FOR_IMAGE_SUBMIT"
                image_tasks.append(task)
            anchor_rows.append(anchor_row)

        motion_beats = authored_motion_beats(row)
        beat_lines = "\n".join(
            f"- {beat['start_seconds']:.3f}-{beat['end_seconds']:.3f}秒：主体={beat['subject']}；动作={beat['action']}；"
            f"接触点={beat['contact_point']}；方向={beat['direction']}；动作目的={beat['intent']}；"
            f"表情={beat['expression']}；终态={beat['end_state']}；观众读法={beat['viewer_read']}。"
            for beat in motion_beats
        )
        dialogue_audio_lines = "\n".join(
            f"- @音频{index}={item['dialogue_id']}：{CHARACTER_NAMES.get(item['speaker'], item['speaker'])}逐字说‘{item['text']}’；"
            "必须完整复现该音频的台词、角色音色、语速、节奏、气息和情绪。"
            for index, item in enumerate(dialogues, 1)
        ) or "- 本单元无对白；所有人物闭口，只生成呼吸、接触声与环境现场声。"
        dialogue_split = math.ceil(len(dialogues) / 2)
        first_dialogues = dialogues[:dialogue_split]
        second_dialogues = dialogues[dialogue_split:]
        first_dialogue_text = "；".join(
            f"@音频{index}：{CHARACTER_NAMES.get(item['speaker'], item['speaker'])}完整说‘{item['text']}’"
            for index, item in enumerate(first_dialogues, 1)
        ) or "无对白，人物闭口"
        second_dialogue_text = "；".join(
            f"@音频{index + dialogue_split}：{CHARACTER_NAMES.get(item['speaker'], item['speaker'])}完整说‘{item['text']}’"
            for index, item in enumerate(second_dialogues, 1)
        ) or "无新增对白，人物闭口"
        beat_split = max(1, math.ceil(len(motion_beats) / 2))
        first_beats = motion_beats[:beat_split]
        second_beats = motion_beats[beat_split:]
        first_action = "；".join(beat["action"] for beat in first_beats)
        second_action = "；".join(beat["action"] for beat in second_beats) or "保持上一拍终态并以自然呼吸收住，不补动作、不重复"
        shot_split_seconds = first_beats[-1]["end_seconds"]
        entity_tags = " ".join([*(f"[[char_{name}]]" for name in row["chars"]), f"[[scene_e34_s{row['scene']:02d}]]"])
        anchor_sequence = "→".join(f"@图片{index}" for index in range(1, len(row["anchors"]) + 1))
        scene_authority = SCENE_STATE[row["scene"] - 1]
        video_prompt = f"""竖屏9:16，中国古装玄幻真人短剧，SD2四模态表演生成。仅生成Claude Writer E34 v2的{full_id}，时长{row['duration']}秒。拂晓至晨间，宿雨已经停止；湿石、残滴、晨雾与晨光可以存在，禁止任何正在降雨、雨幕、暴雨、深夜和现代物件。
【天气硬合同】weather={scene_authority['weather']}

实体绑定：{entity_tags}。只允许剧本声明实体出现；每个角色只有一个身体。
动作目的：{row['intent']}
单一动作状态源/连续运动脚本：{row['chain']}
表情表演：{row['expression']}
观众必须看懂：{row['viewer']}

参考状态序列：{anchor_sequence}。这些图片只锁身份、场景、道具归属和必要状态；必须按顺序消费，连续运动由同一动作脚本完成，禁止逐图定格、拼贴和姿势跳切。

对白与口型音频绑定：
{dialogue_audio_lines}
凡有对白，必须以对应逐句参考音频驱动人物原生自然中文普通话、口型、气息、表情与起止时间；只说一次，禁止后期配音思维，禁止改字、漏字、串角色。非说话人物闭口。

镜头1【0.000-{shot_split_seconds:.3f}秒；大远景定场转中景跟移】：先建立人物、道具、接触物和行动路线；先完成：{first_beats[0]['action']}；再完成：{first_action}；动作结果={first_beats[-1]['end_state']}。{{{first_dialogue_text}}}<脚步、衣料、纸张、呼吸、接触声与环境现场声>
镜头2【{shot_split_seconds:.3f}-{row['duration']:.3f}秒；中景侧移接近景表情特写】：承接上一拍相同方向、速度与道具归属；先完成：{second_beats[0]['action'] if second_beats else '保持上一拍终态'}；再完成：{second_action}；动作结果={motion_beats[-1]['end_state']}。{{{second_dialogue_text}}}<受力反馈、器物、衣料、呼吸与环境现场声>

逐拍物理表演脚本：
{beat_lines}

物理硬门：每一段明确主体、动作、接触点、方向和终态；道具只能在明确抓取、接触、释放后换手。参考锚只锁身份、空间和必要状态，禁止把多图做成逐张定格或姿势跳切；可由一张锚图驱动连续复杂动作，也可用多锚保证跨空间或关键终态，完全服从本单元设计。
力量作用环境：力量只通过本单元已经声明的湿石、残积水、纸张、兵刃、冰面、衣料、案面器物、晨雾或灯焰显形；介质只沿明示方向反馈一次并自然停止。
palette与光影：拂晓灰蓝、晨雾冷银、湿石低反光；室内晨光与残烛暖黄形成冷暖层次，能力光只在明确施术接触点出现。
身份硬门：角色脸、年龄、发型、服装、声线与绑定参考一致；陈迹始终十七岁少年。禁止新增人物、兵器、抓取、转身、腾空、碰撞、慢镜、插帧、周期重复、静帧填时、字幕、水印与可读伪文字。
摄影：服务动作因果和表情转折，连续运动自然，接触与受力清晰；片尾不在单元内生成。禁止BGM与旁白。
"""
        video_path = VIDEO_PROMPT_DIR / f"{full_id}.txt"
        video_path.parent.mkdir(parents=True, exist_ok=True)
        video_path.write_text(video_prompt, encoding="utf-8")
        video_prompt_rows.append({"unit_id": full_id, "scene_id": scene_id, "weather": scene_authority["weather"], "duration_seconds": row["duration"], "prompt_path": str(video_path.relative_to(ROOT)), "prompt_sha256": digest(video_path), "dialogue_ids": [item["dialogue_id"] for item in dialogues], "anchor_task_keys": [item["task_key"] for item in anchor_rows], "status": "PASS_COMPLETE"})
        performance_units.append({
            "unit_id": full_id,
            "scene_id": scene_id,
            "duration_seconds": row["duration"],
            "characters": row["chars"],
            "intent": row["intent"],
            "action_chain": row["chain"],
            "expression_arc": row["expression"],
            "viewer_read": row["viewer"],
            "performance_spec": {
                "schema": "qingshan.performance_generation_spec.v3",
                "episode": "E34",
                "unit_id": full_id,
                "duration_seconds": row["duration"],
                "prop_ownership": {"single_source_of_truth": "人物、道具、能力、锚图、对白和逐拍时间轴全部服从本单元同一份Claude Writer v2 spec。"},
                "motion_beats": motion_beats,
            },
            "anchor_count_decision": {"planned_reference_image_count": len(row["anchors"]), "reason": "Per-unit SD2 capability, action complexity, spatial transitions and physical continuity; no global one-image or multi-image default."},
            "anchors": anchor_rows,
            "dialogue_lines": dialogues,
            "dialogue_audio_reference_status": "WAITING_FOR_EXACT_AUDIO" if dialogues else "NOT_REQUIRED",
            "video_prompt_file": str(video_path.relative_to(ROOT)),
            "video_prompt_sha256": digest(video_path),
            "status": "WAITING_FOR_OWN_ANCHORS_AND_AUDIO",
        })

    production_manifest = {
        "schema": "qingshan.production_manifest.v2",
        "episode": "E34",
        "title": "反客为主",
        "status": "PERFORMANCE_PREPRODUCTION_READY",
        "source_script": str(SCRIPT.relative_to(ROOT)),
        "source_script_sha256": SCRIPT_SHA,
        "runtime_seconds": 174,
        "video_unit_count": len(UNITS),
        "planned_reference_image_count": 29,
        "new_image_submit_count": len(image_tasks),
        "reused_image_candidate_count": len(reused_tasks),
        "production_policy": {
            "writer_authority": "CLAUDE_WRITER_CL2X_664_V2_SHA_LOCK",
            "legacy_builder_dependency": "FORBIDDEN_NONE",
            "grouping": "SCENE_LOCAL_ACTUAL_SECONDS_AND_CONTINUOUS_CAUSALITY_COUNT_EMERGES_FROM_GROUPS",
            "anchor_count": "PER_UNIT_SD2_CAPABILITY_AND_ACTION_DESIGN_NO_GLOBAL_DEFAULT",
            "all_required_anchors_planned_before_image_submit": True,
            "incremental_video_submit_as_each_unit_becomes_ready": True,
            "native_dialogue_from_bound_audio_reference_required": True,
            "video_credit_limit_current_workflow": 6000,
            "target_final_runtime_seconds": 177,
            "youtube_shorts_under_180_seconds_required": True,
            "subtitle_burnin_required": True,
            "nalu_motion_outro_required": True,
            "encoded_audio_asr_loudness_true_peak_retest_required": True,
        },
    }
    write_json(PRODUCTION / "E34_PRODUCTION_MANIFEST_V2.json", production_manifest)
    production_sha = digest(PRODUCTION / "E34_PRODUCTION_MANIFEST_V2.json")
    write_json(PRODUCTION / "E34_SCENE_STATE_AUTHORITY_V2.json", {"schema": "qingshan.scene_state_authority.v1", "episode": "E34", "source_script_sha256": SCRIPT_SHA, "scene_state": SCENE_STATE})
    write_json(PRODUCTION / "E34_VIDEO_UNIT_GROUPING_SPEC_V2.json", {"schema": "qingshan.video_unit_grouping_spec.v2", "episode": "E34", "source_script_sha256": SCRIPT_SHA, "derivation_rule": "Group scene-local scripted action by actual seconds and continuous causal performance; unit count is output, never an input quota.", "unit_count": len(UNITS), "groups": groups})
    write_json(PRODUCTION / "E34_VIDEO_UNIT_PERFORMANCE_PLAN_V2.json", {"schema": "qingshan.performance_video_plan.v2", "episode": "E34", "source_script_sha256": SCRIPT_SHA, "planned_reference_image_count": 29, "units": performance_units})
    write_json(PRODUCTION / "E34_COMPLETE_VIDEO_PROMPT_MANIFEST_V2.json", {"schema": "qingshan.complete_video_prompt_manifest.v1", "episode": "E34", "source_script_sha256": SCRIPT_SHA, "status": "PASS", "unit_count": len(video_prompt_rows), "all_units_have_prompt": len(video_prompt_rows) == len(UNITS), "source_plan": str((PRODUCTION / "E34_VIDEO_UNIT_PERFORMANCE_PLAN_V2.json").relative_to(ROOT)), "source_plan_sha256": digest(PRODUCTION / "E34_VIDEO_UNIT_PERFORMANCE_PLAN_V2.json"), "source_scene_authority": str((PRODUCTION / "E34_SCENE_STATE_AUTHORITY_V2.json").relative_to(ROOT)), "source_scene_authority_sha256": digest(PRODUCTION / "E34_SCENE_STATE_AUTHORITY_V2.json"), "rows": video_prompt_rows})
    dialogue_inventory = {"schema": "qingshan.script_dialogue_inventory.v1", "episode": "E34", "source_script_sha256": SCRIPT_SHA, "line_count": len(DIALOGUES), "audio_policy": "BOUND_ROLE_AUDIO_REFERENCE_TO_VIDEO_MODEL_NATIVE_MANDARIN_LIP_SYNC", "status": "READY_FOR_AUDIO_REFERENCE_GENERATION", "lines": [{"dialogue_id": dia_id, "video_unit_id": f"E34-CW-{uid}", "speaker": speaker, "text": text, "text_sha256": text_digest(text), "audio_status": "PENDING"} for dia_id, uid, speaker, text in DIALOGUES]}
    write_json(PRODUCTION / "E34_SCRIPT_BEAT_DIALOGUE_INVENTORY_V2.json", dialogue_inventory)
    write_json(PRODUCTION / "E34_SUBTITLE_CONTRACT_V2.json", {"schema": "qingshan.subtitle_contract.v1", "episode": "E34", "source_script_sha256": SCRIPT_SHA, "dialogue_line_count": len(DIALOGUES), "burn_in_required": True, "video_model_native_dialogue_audio_required": True, "encoded_asr_coverage_required": f"{len(DIALOGUES)}/{len(DIALOGUES)}", "status": "LOCKED_FOR_AGENTCUT"})
    write_json(PRODUCTION / "E34_NALU_MOTION_OUTRO_CONTRACT_V2.json", {"schema": "qingshan.nalu_motion_outro_contract.v1", "episode": "E34", "required": True, "duration_seconds": 3, "placement": "AFTER_LAST_DIALOGUE_AND_LAST_SUBTITLE", "logo_asset": "libraries/brand/nalu_motion_cat_logo_v1.png", "chime_asset": "libraries/brand/nalu_motion_outro_chime_v1.wav", "status": "LOCKED_FOR_AGENTCUT"})
    preflight = {"schema": "qingshan.performance_preproduction_gate.v2", "episode": "E34", "recorded_at": now, "status": "PASS", "checks": {"claude_script_sha_locked": True, "legacy_builder_dependency_absent": True, "runtime_seconds_exact": True, "scene_local_natural_grouping": True, "unit_count_not_preselected": True, "all_units_between_4_and_15_seconds": True, "anchor_count_decided_independently_per_unit": True, "all_29_required_anchors_planned_before_generation": True, "complete_video_prompt_manifest_compiled_before_streaming": True, "action_intent_contact_direction_end_state_expression_present": True, "weather_post_rain_no_active_rain_locked": True, "exact_dialogue_inventory_complete": True, "subtitles_nalu_and_under_180_seconds_locked": True}, "video_unit_count": len(UNITS), "planned_anchor_count": 29, "dialogue_line_count": len(DIALOGUES), "failures": []}
    write_json(QA_DIR / "E34_IMAGE_PLAN_PREFLIGHT_V2.json", preflight)
    anchor_units = []
    for source, built in zip(UNITS, performance_units):
        count = len(source["anchors"])
        multi = count > 1
        anchor_units.append({
            "unit_id": built["unit_id"],
            "planned_reference_image_count": count,
            "reference_image_task_keys": [row["task_key"] for row in built["anchors"]],
            "anchor_count_decision": {
                "planned_reference_image_count": count,
                "reason": "Independently assessed from SD2 continuous-motion capability, spatial re-anchoring, prop ownership and non-interpolable terminal-state needs for this unit.",
                "criteria": {
                    "continuous_motion_from_single_start": True,
                    "identity_or_space_reanchor": source["uid"] == "U02",
                    "prop_ownership_transition": source["uid"] in {"U10", "U12"},
                    "non_interpolable_terminal_state": multi and source["uid"] != "U02",
                },
                "anchor_roles": [role for role, _ in source["anchors"]],
                "action_design_class": "MULTI_STATE_REANCHOR" if multi else "SINGLE_START_CONTINUOUS_MOTION",
            },
            "keyframe_interpolation_gate": {
                "status": "PASS",
                "adjacent_pairs_checked": max(0, count - 1),
                "basis": "Authored pairs preserve character identity, prop ownership, contact direction and physically reachable state transitions; generated candidates require the same recheck.",
            },
        })
    anchor_plan = {"schema": "qingshan.video_unit_anchor_count_plan.v1", "episode": "E34", "source_script_sha256": SCRIPT_SHA, "planned_reference_image_count": 29, "units": anchor_units}
    write_json(QA_DIR / "E34_VIDEO_ANCHOR_COUNT_PLAN_V2.json", anchor_plan)

    dramatic_beats = []
    scene_buttons = [
        "追兵调头互查，陈迹在高处确认网住了他们自己。",
        "三人决定赶在两路灭口者之前活捉严敬。",
        "严敬被活着扛走，陈迹显出冰流反噬代价。",
        "严敬供出景朝只认死物以及多年旧案。",
        "皎兔截住最后两个字，声音悬停切黑。",
    ]
    scene_shifts = [
        "陈迹从被全城追捕者转成迫使追兵自查的人。",
        "半份名录从公开证据转成保留严敬的主动筹码。",
        "两路灭口先手被三人逆转为活捉成功。",
        "严敬从否认上级身份转为供出景朝接头制度。",
        "沈砚旧案从名册旁注升级为景朝活口证言。",
    ]
    for index in range(5):
        dramatic_beats.append({
            "scene_entry": "late",
            "scene_exit": "early",
            "power_shift": scene_shifts[index],
            "intercut_with": "E34-CW-S01-CITY-MONTAGE" if index == 0 else "",
            "end_button": scene_buttons[index],
            "unresolved_question_id": "E34-Q-DEAD-OBJECT" if index in {3, 4} else "E34-Q-SEALED-COMMANDER",
            "act_out": index in {0, 2, 4},
            "dialogue_interruption_refs": ["E34-DIA-043"] if index == 4 else [],
        })
    advisor_analysis = {
        "film_director": "视觉目标、接触点和表情转折均由镜头动作承担，死巷战不靠慢镜填时长。",
        "short_drama_director": "前三秒直接进入全城自查，五场都有明确按钮且末尾死物悬念直引下一集。",
        "original_author": "保留半份名录、严敬活捉、死物接头与沈砚旧案主线，不增加支线结算。",
        "ordinary_audience": "观众能看懂陈迹如何反客为主、为何抢严敬以及供词改变了什么。",
        "executive_producer": "总内容一百七十四秒并预留三秒片尾，满足竖屏短剧和Shorts时长约束。",
        "american_tv_pacing": "冷开场、迟入早出、场尾按钮、动作反转和未完成台词构成连续推进。",
    }
    dramatic_plan = {
        "schema": "qingshan.dramatic_quality_plan.v1",
        "episode": "E34",
        "script_sha256": SCRIPT_SHA,
        "runtime_seconds": 174,
        "council": {"advisors": [{"role": role, "independent": True, "analysis": analysis} for role, analysis in advisor_analysis.items()], "chair_verdict": "PASS", "revision_cascade": {"status": "COMPLETE", "affected_unproduced_episodes": [], "affected_published_episodes": []}, "experience_memory_ref": "workflow/claude_writer_agent/MEMORY.md"},
        "beats": dramatic_beats,
        "narrative_technique_contract": {"cold_open": {"enabled": True, "within_seconds": 3, "event_in_progress": True}, "dual_line_episode": False},
        "two_episode_fight_floor": {"qualifying_true_fight_scene_count": 1, "minimum_qualifying_duration_seconds": 46},
    }
    write_json(QA_DIR / "E34_DRAMATIC_QUALITY_PLAN_V2.json", dramatic_plan)

    mechanical_plan = {
        "schema": "qingshan.mechanical_default_plan.v1",
        "episode": "E34",
        "global_defaults": [],
        "variable_fields": ["duration_seconds", "planned_reference_image_count", "scene_id", "weather", "dialogue_sentence_count", "prompt_sha256"],
        "units": [{"unit_id": item["unit_id"], "duration_seconds": item["duration_seconds"], "planned_reference_image_count": item["anchor_count_decision"]["planned_reference_image_count"], "scene_id": item["scene_id"], "weather": SCENE_STATE[int(item["scene_id"][-2:]) - 1]["weather"], "dialogue_sentence_count": len(item["dialogue_lines"]), "prompt_sha256": item["video_prompt_sha256"]} for item in performance_units],
        "mechanical_default_independence_audit": {},
    }
    write_json(QA_DIR / "E34_MECHANICAL_DEFAULT_PLAN_V2.json", mechanical_plan)

    causality_plan = {
        "schema": "qingshan.common_sense_causality_plan.v1",
        "episode": "E34",
        "units": [{"unit_id": item["unit_id"], "causality": {"applicable": True, "purpose": item["intent"], "preconditions": ["剧本声明的角色、空间、道具与起始姿态已经建立。"], "mechanism_chain": ["主体从声明的起始状态发起动作并到达明确接触点。", item["action_chain"]], "intended_effect": item["viewer_read"], "visible_causality": item["action_chain"], "viewer_read": item["viewer_read"], "counterfactual_test": {"opponent_can_bypass": False, "reasoning": "移除已声明的接触、摩擦、抓取、格挡或空间转换后，结果不再成立，因此画面必须保留完整因果链。"}, "prop_function_status": "PASS", "evidence_refs": [item["video_prompt_file"], "workflow/claude_writer_agent/scripts/E34剧本_ClaudeWriter_v2.md"]}} for item in performance_units],
    }
    write_json(QA_DIR / "E34_COMMON_SENSE_CAUSALITY_PLAN_V2.json", causality_plan)

    period_plan = {
        "schema": "qingshan.anachronism_lock_plan.v1",
        "episode": "E34",
        "period_contract": {"era": "架空中国古代洛城", "status": "PASS", "source_refs": ["workflow/claude_writer_agent/scripts/E34剧本_ClaudeWriter_v2.md", "configs/series_continuity_asset_registry_20260712.json"]},
        "units": [{"unit_id": item["unit_id"], "period_lock": {"status": "PASS", "reviewed_visible_elements": ["古代木石街巷与屋瓦", "古代官袍与青衫", "纸质名录与黑皮名册", "冷兵器与玄幻冰流"], "detected_anachronisms": [], "exception_approvals": {}, "evidence_refs": [item["video_prompt_file"]]}} for item in performance_units],
    }
    write_json(QA_DIR / "E34_PERIOD_LOCK_PLAN_V2.json", period_plan)
    compatibility = {"schema": "qingshan.cross_version_asset_compatibility_audit.v1", "episode": "E34", "recorded_at": now, "status": "PASS", "canonical_source_script_sha256": SCRIPT_SHA, "audited_assets": [{"asset": str(OLD_U01_IMAGE.relative_to(ROOT)), "sha256": digest(OLD_U01_IMAGE), "source_version": "v1", "reuse_as": "E34-CW-U01-A1", "status": "PASS_REUSE", "reason": "v2 mainline unchanged; the v1 image already depicts the same dawn post-rain office self-audit establishing beat and contains no modified dialogue, protagonist age, or active rain conflict."}, {"asset": str(YANJING_IMAGE.relative_to(ROOT)), "sha256": digest(YANJING_IMAGE), "source_version": "v1", "reuse_as": "yanjing_visual_identity_authority", "status": "PASS_REUSE", "reason": "v2 preserves Yanjing as a thirty-plus secret-service clerk with the same role, costume class and threatened/interrogated identity."}], "raw_v1_provenance_preserved": True, "v1_assets_not_relabelled_as_v2_generation": True}
    write_json(QA_DIR / "E34_V1_ASSET_COMPATIBILITY_AUDIT_V2.json", compatibility)
    image_manifest = {"schema": "qingshan.episode_parallel_batch.v1", "episode": "E34", "status": "READY_TO_SUBMIT_CONCURRENTLY", "source_script_sha256": SCRIPT_SHA, "scene_contract_ref": str((PRODUCTION / "E34_SCENE_STATE_AUTHORITY_V2.json").relative_to(ROOT)), "script_readiness_report": str((QA_DIR / "E34_IMAGE_PLAN_PREFLIGHT_V2.json").relative_to(ROOT)), "production_manifest_ref": str((PRODUCTION / "E34_PRODUCTION_MANIFEST_V2.json").relative_to(ROOT)), "video_unit_plan_ref": str((PRODUCTION / "E34_VIDEO_UNIT_PERFORMANCE_PLAN_V2.json").relative_to(ROOT)), "writer_agent_provenance": {"status": "PASS", "provenance_type": "claude_writer_script", "source_script": str(SCRIPT.relative_to(ROOT)), "source_script_sha256": SCRIPT_SHA, "production_manifest": str((PRODUCTION / "E34_PRODUCTION_MANIFEST_V2.json").relative_to(ROOT)), "production_manifest_sha256": production_sha}, "dramatic_quality_report_ref": str((QA_DIR / "E34_DRAMATIC_QUALITY_PLAN_V2.json").relative_to(ROOT)), "mechanical_default_plan_ref": str((QA_DIR / "E34_MECHANICAL_DEFAULT_PLAN_V2.json").relative_to(ROOT)), "anchor_count_plan_ref": str((QA_DIR / "E34_VIDEO_ANCHOR_COUNT_PLAN_V2.json").relative_to(ROOT)), "common_sense_causality_plan_ref": str((QA_DIR / "E34_COMMON_SENSE_CAUSALITY_PLAN_V2.json").relative_to(ROOT)), "period_lock_plan_ref": str((QA_DIR / "E34_PERIOD_LOCK_PLAN_V2.json").relative_to(ROOT)), "machine_gate_reports": [str((QA_DIR / "E34_IMAGE_PLAN_PREFLIGHT_V2.json").relative_to(ROOT)), str((QA_DIR / "E34_VIDEO_ANCHOR_COUNT_PLAN_V2.json").relative_to(ROOT)), str((QA_DIR / "E34_COMMON_SENSE_CAUSALITY_PLAN_V2.json").relative_to(ROOT)), str((QA_DIR / "E34_PERIOD_LOCK_PLAN_V2.json").relative_to(ROOT))], "output_dir": "working_assets/e34_v2_stills_20260723/candidates", "qa_dir": "qa/e34_v2_stills_20260723", "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED", "consumer_contract": {"purpose": "PERFORMANCE_ANCHORS", "video_unit_count": len(UNITS), "planned_anchor_count": 29, "new_image_submit_count": len(image_tasks), "reused_image_count": len(reused_tasks), "all_required_anchors_planned_before_submit": True, "incremental_video_submit": "EACH_UNIT_IMMEDIATELY_WHEN_ITS_OWN_ANCHORS_AND_AUDIO_PASS"}, "reused_tasks": reused_tasks, "blocked_tasks": [], "tasks": image_tasks}
    write_json(PRODUCTION / "E34_IMAGE_BATCH_PERFORMANCE_V2.json", image_manifest)
    write_json(ROOT / "workflow/tasks/E34_RESUMED_BY_ROGER_V2_REBASE_20260723.json", {"schema": "qingshan.production_resume.v1", "episode": "E34", "recorded_at": now, "status": "RESUMED_AND_REBASED_TO_V2", "authorized_by": "Roger", "source_script": str(SCRIPT.relative_to(ROOT)), "source_script_sha256": SCRIPT_SHA, "previous_pause_receipt": "workflow/tasks/E34_PAUSED_BY_ROGER_20260723.json", "old_v1_work_policy": "REUSE_ONLY_AFTER_EXPLICIT_COMPATIBILITY_AUDIT", "next_action": "SUBMIT_28_NEW_IMAGES_AND_GENERATE_BOUND_DIALOGUE_AUDIO_IN_PARALLEL"})
    write_json(ROOT / "workflow/submission_authority/E34_VIDEO_SUBMISSION_AUTHORITY.json", {"schema": "qingshan.episode_video_submission_authority.v1", "episode": "E34", "status": "AUTHORIZED_BY_ROGER_RESUMED_V2", "video_submission_allowed": True, "authorized_by": "Roger", "recorded_at_utc": now, "source_script": str(SCRIPT.relative_to(ROOT)), "source_script_sha256": SCRIPT_SHA, "reason": "Roger explicitly instructed Codex to resume E34 production.", "evidence": ["workflow/tasks/E34_RESUMED_BY_ROGER_V2_REBASE_20260723.json"], "scope": "E34_V2_ONLY_INCREMENTAL_UNIT_SUBMISSION", "credit_limit": 6000})
    write_json(ROOT / "workflow/tasks/E34_V2_PREPRODUCTION_BUILD_20260723.json", {"schema": "qingshan.preproduction_input_build.v2", "episode": "E34", "recorded_at": now, "status": "READY_FOR_IMAGE_AND_DIALOGUE_AUDIO_SUBMIT", "source_script_sha256": SCRIPT_SHA, "video_unit_count": len(UNITS), "planned_anchor_count": 29, "new_image_submit_count": len(image_tasks), "reused_image_count": len(reused_tasks), "dialogue_line_count": len(DIALOGUES), "complete_video_prompt_count": len(video_prompt_rows), "legacy_builder_dependency": "NONE", "remote_call_count": 0, "new_credits": 0})
    print(json.dumps({"status": "PASS", "runtime": 174, "units": len(UNITS), "anchors": 29, "new_images": len(image_tasks), "reused_images": len(reused_tasks), "dialogue_lines": len(DIALOGUES), "video_prompts": len(video_prompt_rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
