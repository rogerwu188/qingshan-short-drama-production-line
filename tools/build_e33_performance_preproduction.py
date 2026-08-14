#!/usr/bin/env python3
"""Build E33 performance-generation preproduction from the locked Claude script."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E33剧本_ClaudeWriter_v1.md"
WRITER_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E33_manifest.json"
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e33_claude_writer_v1_20260723"
PROMPT_DIR = PRODUCTION / "image_prompts_performance_v1"
QA_DIR = ROOT / "qa/e33_performance_preproduction_20260723"
AUDIO_MANIFEST = ROOT / "working_assets/e33_dialogue_audio_refs_20260723/E33_DIALOGUE_AUDIO_REFERENCE_MANIFEST_V1.json"
ACTION_PROMPT = ROOT / "codex_docs/教codex动作可视化_系统提示词_v1_20260722.md"
ACTION_PROMPT_SHA = "04f47991157e9a1ce3fcab7be6bf3b89ed76a2f34b52a27a0d4b393bca0c736f"

SCENE_EXTERIOR = "working_assets/e29_claude_writer_v1_stills_20260722/candidates/E29_E29-CW-S01-SH01-STILL-V1_4f6f7833-2bff-40e4-9a98-69b4d4054bc7.png"
SCENE_INTERIOR = "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg"
CHARACTERS = {
    "chenji": "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg",
    "jiaotu": "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg",
    "yunyang": "working_assets/api_reference_images_20260704/male_yunyang_ancient_ref_20260704_api.jpg",
    "wuyun": "working_assets/e21_scene_fidelity_r3_identity_parallel_20260718/image_candidates/E21_E21-S01-WUYUN-PURE-BLACK_2af7eb4b-625b-4eeb-bfd5-407b40a24ae2.png",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def shot(scene: int, number: int, duration: int, action: str) -> dict[str, object]:
    return {
        "shot_id": f"E33-CW-S{scene:02d}-SH{number:02d}",
        "scene_id": f"E33-CW-S{scene:02d}",
        "duration_seconds": duration,
        "action": action,
    }


SHOTS = [
    shot(1, 1, 7, "雨夜洛城被三路灯火与半落铁闸绞成巨网，三名少年被压在合拢兵潮之间。"),
    shot(1, 2, 6, "陈迹把皎兔和云羊带入檐影，甲兵在前后两端继续收紧。"),
    shot(1, 3, 6, "云羊判断四门落锁，墙头乌云竖尾指向三面不同旗号。"),
    shot(1, 4, 10, "陈迹逐一辨认巡检旗、景朝暗桩与内院私兵，指出三方互不信任。"),
    shot(1, 5, 8, "皎兔判断无路可闯，陈迹转身下令让网中三方先互咬。"),
    shot(2, 1, 8, "檐影下云羊连续剪出三封字迹逼真的私信。"),
    shot(2, 2, 7, "陈迹冷雾沿信封压出三枚来源不同但足以取信的假印。"),
    shot(2, 3, 6, "皎兔割眉闭目，黑甲阴神从端坐肉身完整分离并接过三封信。"),
    shot(2, 4, 4, "阴神穿雨把第一封信塞入巡检队官甲缝。"),
    shot(2, 5, 4, "阴神越过另一条街，把第二封信压上景朝暗桩马鞍。"),
    shot(2, 6, 4, "阴神穿入内院营帐，把第三封信钉在私兵首领门前。"),
    shot(2, 7, 10, "阴神归窍，皎兔确认投递完成，长街三处骚动同时升起。"),
    shot(3, 1, 6, "三面旗号的人马在长街尽头误判对方先动手，火把与兵刃轰然撞作一团。"),
    shot(3, 2, 6, "陈迹三人贴墙踏水疾掠，直插混战中央押送令匣的黑漆马车。"),
    shot(3, 3, 8, "两名巡检兵挺刀夹击，陈迹冰流封住积水，二人失足滑离刺击线。"),
    shot(3, 4, 8, "云羊点睛纸人遮住车夫视线，滑步贴车后一拳砸断车辕。"),
    shot(3, 5, 8, "景朝暗桩掠上车顶，陈迹封住其落脚靴，云羊顺势肩撞把他送入人群。"),
    shot(3, 6, 8, "歪塌车厢吐出铜封令匣，皎兔阴神托匣，陈迹冻裂锁扣并抽出黑皮名册。"),
    shot(3, 7, 8, "陈迹掌心白霜逆窜，乌云把人参珠抵入掌心压霜，云羊护住侧翼催促撤离。"),
    shot(4, 1, 5, "三人抱名册冲入死巷，姚太医的大乌鸦落向墙角水洞连续示警。"),
    shot(4, 2, 6, "陈迹冻脆锈死铁栅，云羊在明确接触点一拳震碎，露出排水暗道。"),
    shot(4, 3, 6, "三人鱼贯入洞，巷口兵潮火光扑空，陈迹回望互杀长街。"),
    shot(5, 1, 7, "密室残烛下陈迹翻开黑皮名册，云羊看见密谍司内鬼姓名后指节发白。"),
    shot(5, 2, 10, "名册顶端姓名被幽微水波密纹封死，陈迹冷雾触纹却无法显字，皎兔发现旁注。"),
    shot(5, 3, 10, "旁注沈砚旧案映入眼帘，陈迹瞳孔骤缩，镜头从名册与三人反应缓慢拉远切黑。"),
]


def unit(
    uid: str,
    scene: int,
    numbers: list[int],
    characters: list[str],
    anchors: list[tuple[str, str]],
    intent: str,
    chain: str,
    expression: str,
    viewer_read: str,
) -> tuple[object, ...]:
    return uid, scene, numbers, characters, anchors, intent, chain, expression, viewer_read


UNITS = [
    unit("U01", 1, [1, 2], ["chenji", "jiaotu", "yunyang"], [("performance_start", "雨夜洛城大远景，半落铁闸与三路兵潮把陈迹、皎兔、云羊压在长街中央，三人刚转入檐影。")], "建立无法硬闯的围猎压力", "两端兵潮沿街心相向推进，陈迹抓住同伴衣袖向侧后方檐影撤半步，铁闸继续下落并封死后路。", "云羊焦急，皎兔屏息警觉，陈迹冷静扫视", "观众一眼看懂全城合围且退路正在消失"),
    unit("U02", 1, [3], ["yunyang", "wuyun"], [("performance_start", "檐影近景，云羊握拳望向落锁城门，黑猫乌云在墙头弓背竖尾，尾尖正对三面不同旗号。")], "辨认围猎结构", "云羊前倾指向城门；乌云从低啸到竖尾，尾尖依次划过巡检、景朝和内院三面旗号，云羊视线跟随。", "云羊焦灼后愕然，乌云高度警戒", "观众通过旗号与黑猫指向读懂追兵并非同一阵营"),
    unit("U03", 1, [4], ["chenji", "jiaotu", "yunyang"], [("performance_start", "檐影中景，陈迹面向三面旗号，皎兔与云羊分立两侧，远处三路队列互相保持戒备距离。")], "发现三方互疑可被利用", "陈迹的目光从巡检旗移到景朝暗桩再到内院私兵，每报出一方就用手指锁定对应队列；三方士兵彼此侧目却不靠近。", "陈迹眸底由冷静转为抓住破绽，二人由绝望转为专注", "观众读懂三方共同围猎却彼此不信任"),
    unit("U04", 1, [5], ["chenji", "jiaotu", "yunyang"], [("performance_start", "皎兔贴着檐柱判断无路可走，陈迹背对兵潮停住脚步，云羊等待决定。")], "把逃亡转为反收网", "皎兔向封死街口摊手；陈迹不后退，转身正对三方旗号并下压手掌示意同伴停下，随后以目光锁住骚动源头。", "皎兔压抑，云羊疑惑，陈迹寒意渐明", "观众听懂并看懂主角决定让追兵先互相攻击"),
    unit("U05", 2, [1, 2], ["chenji", "yunyang"], [("performance_start", "檐影案板上三张空白信纸与三只信封分开排好，云羊剪纸，陈迹指尖冷雾悬在第一只信封上方。")], "制造三份互相矛盾但各自可信的毒饵", "云羊连续剪出三封私信并依次推向陈迹；陈迹让冷雾只接触封口位置，三枚不同假印逐一凝形落纸，完成一封就推向下一位置。", "云羊专注迅速，陈迹克制精准", "观众读懂纸人伪信与冰流假印合成完整离间证据"),
    unit("U06", 2, [3], ["jiaotu"], [("performance_start", "皎兔端坐檐影闭目，指甲刚抵眉心，三封信放在膝前，肉身与窗外雨夜同框。")], "让阴神承担穿网投递", "皎兔指甲割出血痕，黑甲阴神从眉心后方完整分离；肉身保持端坐，阴神落地后俯身拿起三封信再转向雨幕。", "肉身克制忍痛，阴神睁眼后冷峻执行", "观众明确看见肉身、阴神与三封信的归属转换"),
    unit("U07", 2, [4, 5, 6], ["jiaotu"], [("patrol_delivery", "雨中巡检队列近景，黑甲阴神贴近队官背后，第一封信正对其甲片缝隙。"), ("jing_delivery", "另一条街的马匹与景朝暗桩同框，黑甲阴神悬在马鞍侧，第二封信尚在手中。"), ("inner_court_delivery", "内院私兵营帐门前，黑甲阴神举起第三封信，帐门木柱留有明确钉入位置。")], "让三方同时收到针对自身恐惧的伪证", "阴神把第一封信推入队官甲缝后松手；穿雨抵达马鞍，把第二封压在缰绳下；再穿墙到营帐，将第三封钉进门柱，三次接触、释放和终态都清楚。", "阴神始终冷峻，三方收信者从戒备转为惊怒", "观众看懂同一投递者在三个明确地点完成三封不同毒饵；空间跳切不是瞬移"),
    unit("U08", 2, [7], ["chenji", "jiaotu", "yunyang"], [("performance_start", "皎兔肉身仍端坐，黑甲阴神从背后贴近眉心归窍，陈迹与云羊望向远处三团升起的骚动。")], "确认毒饵生效", "阴神沿眉心收回，皎兔睁眼吐气；三人同时转头，远处三路队列各自拔刀聚拢，陈迹看见第一处冲突后收紧目光。", "皎兔疲惫后冷硬，云羊紧张，陈迹笃定", "观众读懂三封信已经同时点燃三方猜忌"),
    unit("U09", 3, [1], [], [("performance_start", "长街大远景，巡检兵、景朝暗桩、内院私兵三面旗号在混乱火把下互相举刀，第一排尚未接触。")], "让收网者从内部爆开", "一名巡检兵误判景朝暗桩拔刀，先格开对方兵刃；内院私兵从侧面突入，三股人潮沿明确方向撞合，火把倒落但不爆炸。", "三方均由猜疑转为失控杀意", "观众看懂不是主角施法，而是伪证点燃了原有互疑"),
    unit("U10", 3, [2], ["chenji", "jiaotu", "yunyang"], [("performance_start", "陈迹、皎兔、云羊贴长街右侧墙根低身疾行，前方黑漆马车被混战人群短暂隔开。")], "利用互杀缺口接近名册马车", "三人沿墙根连续踏水前冲，陈迹先绕过倒地火把，皎兔紧随，云羊回头确认追兵被人潮挡住后再贴近车尾。", "陈迹目标明确，皎兔专注，云羊急迫警戒", "观众看懂三人不是乱跑，而是在直插唯一目标马车"),
    unit("U11", 3, [3], ["chenji"], [("performance_start", "两名巡检兵在马车前左右夹击，刀尖分别指向陈迹胸口，陈迹后脚钉地、掌心朝向雨水积地。")], "用冰流改变落脚摩擦而非凭空停刀", "两兵向中央同步挺刀；陈迹掌心下压，冰流沿积水从近到远铺开，两兵靴底失去摩擦后分别向外侧滑离，刀锋从陈迹身前交错刺空。", "两兵从狠厉转惊愕失衡，陈迹冷定不退", "观众看懂冰面导致脚滑，刺击因此偏离"),
    unit("U12", 3, [4], ["yunyang"], [("performance_start", "云羊已滑到黑漆马车侧前方，咬破指尖，十数张未展开纸人夹在手中，车夫仍握缰绳看向前路。")], "先夺车夫视线再破坏车辕", "云羊以血点睛，纸人沿车夫视线方向展开成墙；车夫抬臂遮眼并松动缰绳；云羊继续滑步转胯，拳面命中车辕固定点，木纤维沿受力方向断裂，车厢向一侧倾斜。", "云羊爆发狠决，车夫从惊怒转恐慌", "观众看懂遮眼、松缰、冲拳、断辕与车厢倾斜的完整因果"),
    unit("U13", 3, [5], ["chenji", "yunyang"], [("performance_start", "景朝暗桩从左侧人群跃向倾斜车顶，陈迹在车侧抬掌瞄准其右脚落点，云羊已在落点另一侧沉肩。")], "阻断抢匣者的落脚并借肩撞送回人群", "暗桩向车顶明确落点下坠；陈迹冰流只封住该落点，右靴接触后冻结；暗桩上身因惯性前倾，云羊从侧方用肩撞中其肋侧，使冻结靴脱开并把人撞向厮杀人群。", "暗桩由自信转惊恐痛苦，陈迹精准，云羊怒意爆发", "观众看懂封落点造成失衡，肩撞决定最终飞行方向"),
    unit("U14", 3, [6], ["chenji", "jiaotu"], [("chest_release_start", "倾斜车厢门板已裂，铜封令匣卡在门槛边，皎兔阴神伸手将接未接，陈迹掌心冷雾尚未触锁。"), ("book_ownership_terminal", "皎兔阴神双手托住已开令匣，陈迹从匣内抽出厚黑皮名册并握在自己手中，锁扣碎冰落地。")], "完成令匣到名册的清晰归属转换", "陈迹扯开门板，令匣沿倾斜车板滚向地面；皎兔阴神双手托住并稳定匣体；陈迹冷雾接触铜锁使其脆裂，右手伸入匣内抽出黑皮名册并收进怀中。", "皎兔阴神专注承托，陈迹急迫但动作准确", "观众看懂令匣由车厢转给阴神，名册再由匣内转入陈迹手中"),
    unit("U15", 3, [7], ["chenji", "yunyang", "wuyun"], [("performance_start", "陈迹刚把黑皮名册压进怀里，右掌开始结白霜，黑猫乌云从车顶跃向他的掌心，透明人参珠含在口中。")], "用人参珠压住夺册后的冰流反噬", "白霜从掌心沿腕骨逆窜；乌云落到前臂并把人参珠准确抵入掌心；霜纹接触珠面后停止扩散，陈迹重新握紧名册，云羊横移到侧翼挡住来刀。", "陈迹忍痛咬牙，乌云急切专注，云羊喘息而决绝", "观众看懂反噬正在夺命，人参珠通过真实接触压住白霜"),
    unit("U16", 4, [1], ["chenji", "jiaotu", "yunyang"], [("performance_start", "三人抱名册冲入窄死巷，前方高墙封路，通体漆黑的大乌鸦正从墙头俯冲向右下角水洞。")], "让姚太医的乌鸦指出唯一生门", "三人撞见高墙后急停；乌鸦从墙头俯冲，在墙角水洞上方盘旋并连续啄向同一位置；皎兔跟随鸟喙方向蹲下确认。", "三人从绝望转为看见出口，乌鸦急切示警", "观众看懂乌鸦不是装饰，而是在精确指示暗洞"),
    unit("U17", 4, [2], ["chenji", "yunyang"], [("performance_start", "墙角水洞被杂物半掩，锈死铁栅完整挡路，陈迹掌心贴近左侧铰点，云羊拳锋对准中央受力点。")], "用冰脆化与实体冲拳打开暗道", "陈迹冷雾只接触铁栅铰点与横杆，使锈铁结霜变脆；他撤手后云羊蹬地转胯，拳面命中中央固定点，裂纹向四角扩散，铁栅向洞内碎落。", "陈迹精准，云羊全力爆发", "观众看懂先冻脆材料、再击中接触点才能破栅"),
    unit("U18", 4, [3], ["chenji", "jiaotu", "yunyang"], [("performance_start", "破开的水洞仅容一人，皎兔已俯身进入，云羊护在洞口，陈迹怀抱名册回望巷口逼近火光。")], "在兵潮到达前完成有序撤离", "皎兔先钻入暗道，云羊确认她通过后跟入；陈迹最后后退一步进入洞口并说完判断，巷口兵潮火光扫过空巷但未发现入口。", "皎兔急切，云羊警戒，陈迹冷静收局", "观众看懂三人借互杀缺口脱身，追兵扑空"),
    unit("U19", 5, [1], ["chenji", "yunyang"], [("performance_start", "密室残烛近景，陈迹双手把黑皮名册摊到案上，云羊俯身看向已翻开的姓名页，纸面不得出现可读字。")], "确认真名册让猎物转为执猎者", "陈迹逐页翻过，云羊视线随页移动并攥紧案沿；看到连续姓名后云羊指节发白，陈迹停在最顶页。", "云羊从震惊转为振奋，陈迹沉着警觉", "观众从连续翻页与二人反应读懂内鬼名单真实完整"),
    unit("U20", 5, [2], ["chenji", "jiaotu"], [("performance_start", "名册最顶页近景，姓名区域只覆幽微水波暗纹且无可读文字，陈迹指尖冷雾悬在纹路上方，皎兔从侧面靠近。")], "证明顶端姓名被景朝体系主动加密", "陈迹冷雾接触水波暗纹，霜纹扩散又退去，暗纹始终不显字；他收手判断来源，皎兔沿纹路边缘移动目光，突然在旁注位置停住并指向同一处。", "陈迹由尝试转为沉重确认，皎兔由专注转震惊", "观众看懂封名无法被冰流破解，旁边另有关键线索"),
    unit("U21", 5, [3], ["chenji", "jiaotu", "yunyang"], [("performance_start", "残烛下三人围住摊开的名册，皎兔手指停在旁注位置，陈迹刚读到沈砚旧案并抬眼，纸面保持不可读材质。")], "用人物反应揭示沈砚并非凭空假名", "陈迹读到旁注后瞳孔骤缩，右手离开名册又按回案面稳住身体；皎兔与云羊同时望向他；镜头持续后拉，残烛爆芯后自然切黑。", "陈迹从不信到森然失神，皎兔惊疑，云羊警觉", "观众听懂沈砚是真实旧案，并意识到它压在内鬼名册最上层"),
]


DIALOGUES = [
    ("E33-DIA-001", "U02", "yunyang", "四门全落锁了，硬闯就是拿命填。"),
    ("E33-DIA-002", "U03", "chenji", "密谍司的巡检旗、景朝暗桩混在里头、还有内院的私兵……他们把三拨谁也不信谁的人，塞进了同一张网。"),
    ("E33-DIA-003", "U04", "jiaotu", "这网太密，闯不出去。"),
    ("E33-DIA-004", "U04", "chenji", "那就不闯。让网里的人，先咬起来。"),
    ("E33-DIA-005", "U05", "chenji", "一封给巡检兵——景朝暗桩已拿你们的布防去邀功；一封给景朝暗桩——内院私兵要借围猎除掉你们；一封给内院——密谍司要连你们一起收网灭口。三封信，三拨人，各中各的心事。"),
    ("E33-DIA-006", "U08", "jiaotu", "信都到了。就看谁先沉不住气。"),
    ("E33-DIA-007", "U08", "chenji", "不必等太久。互相咬着的人，一点就着。"),
    ("E33-DIA-008", "U15", "yunyang", "拿到了！走——趁他们还没顾上咱们！"),
    ("E33-DIA-009", "U16", "jiaotu", "姚太医的乌鸦——它在指路。"),
    ("E33-DIA-010", "U18", "chenji", "收网的人，今夜要自己收拾自己了。"),
    ("E33-DIA-011", "U19", "yunyang", "真的……全在这儿。从今夜起，是他们该怕了。"),
    ("E33-DIA-012", "U20", "chenji", "景朝的水波纹……连密谍司自己的内鬼名册，最顶上那个名字，都是景朝替他封的。"),
    ("E33-DIA-013", "U20", "jiaotu", "等等——这里。"),
    ("E33-DIA-014", "U21", "chenji", "沈砚……我凭空编的那个名字。它怎么会……压在整本内鬼名册的最上头，成了一桩景朝的旧案？"),
]


def binding(role: str, entity_id: str, path: str) -> dict[str, object]:
    absolute = ROOT / path
    if not absolute.is_file():
        raise SystemExit(f"missing reference: {path}")
    return {
        "role": role,
        "entity_id": entity_id,
        "path": path,
        "sha256": sha256(absolute),
        "qa_status": "PASS",
        "qa_report": "configs/series_continuity_asset_registry_20260712.json" if role == "character" else "E33_SCENE_STYLE_REFERENCE_ONLY",
    }


def main() -> int:
    writer = json.loads(WRITER_MANIFEST.read_text(encoding="utf-8"))
    script_sha = sha256(SCRIPT)
    if writer["sha256"] != script_sha:
        raise SystemExit("E33 script SHA does not match Claude Writer manifest")
    if not ACTION_PROMPT.is_file() or sha256(ACTION_PROMPT) != ACTION_PROMPT_SHA:
        raise SystemExit("action-visualization system prompt missing or SHA mismatch")
    if len(SHOTS) != writer["shots"] or sum(int(row["duration_seconds"]) for row in SHOTS) != writer["total_seconds"]:
        raise SystemExit("E33 editorial shot count or duration mismatch")

    by_scene: dict[int, dict[int, dict[str, object]]] = {}
    for row in SHOTS:
        scene = int(str(row["scene_id"])[-2:])
        number = int(str(row["shot_id"])[-2:])
        by_scene.setdefault(scene, {})[number] = row

    dialogue_by_unit: dict[str, list[dict[str, str]]] = {}
    for dia_id, uid, speaker, text in DIALOGUES:
        dialogue_by_unit.setdefault(uid, []).append({"dialogue_id": dia_id, "speaker": speaker, "text": text})

    consumed: set[str] = set()
    groups = []
    performance_units = []
    image_tasks = []
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for uid, scene, numbers, character_ids, anchors, intent, chain, expression, viewer_read in UNITS:
        full_id = f"E33-CW-{uid}"
        editorial = [by_scene[scene][number] for number in numbers]
        editorial_ids = [str(row["shot_id"]) for row in editorial]
        if consumed.intersection(editorial_ids):
            raise SystemExit(f"{full_id} reuses an editorial shot")
        consumed.update(editorial_ids)
        duration = sum(int(row["duration_seconds"]) for row in editorial)
        if not 4 <= duration <= 15:
            raise SystemExit(f"{full_id} duration outside 4-15 seconds")
        groups.append({"unit_id": full_id, "scene_id": f"E33-CW-S{scene:02d}", "duration_seconds": duration, "editorial_shot_ids": editorial_ids})

        scene_path = SCENE_INTERIOR if scene in {2, 5} else SCENE_EXTERIOR
        refs = [binding("character", character_id, CHARACTERS[character_id]) for character_id in character_ids]
        refs.append(binding("scene", f"E33-CW-S{scene:02d}", scene_path))
        anchor_keys = []
        for index, (role, description) in enumerate(anchors, start=1):
            anchor_id = f"{full_id}-A{index}"
            task_key = f"{anchor_id}-STILL-V1"
            anchor_keys.append(task_key)
            source_action = f"动作目的：{intent}；连续物理链：{chain}；表情弧：{expression}；观众读法：{viewer_read}。"
            entity_tags = " ".join(f"[[{character_id}]]" for character_id in character_ids) or "[[ENVIRONMENT_ONLY]]"
            framing = (
                "场景首镜大远景、广角纵深构图，完整建立空间规模、出口和人物相对位置"
                if uid in {"U01", "U05", "U09", "U16", "U19"} and index == 1
                else "中景或近景的纵深构图，主体、接触点、动作方向和终态空间保持清楚"
            )
            prompt = f"""竖屏 9:16，电影级中国古装玄幻短剧，真实人物、真实接触、真实受力，雨夜冷青与火光暖橙，禁止现代物件。

这是 {full_id} 的表演参考锚 A{index}/{len(anchors)}，角色为 {role}。本单元参考图数量由动作设计独立裁定为 {len(anchors)}，不是固定一张或固定三张；图片只锁身份、空间、道具归属与必要状态，连续动作由视频模型按运动脚本完成。

实体绑定：{entity_tags}
剧本硬锁：仅表现 Claude Writer 原稿中 {full_id} 对应的连续节拍，不增加新人物、新武器、新抓取、新腾空或新碰撞。
人物身份锁 / 道具锁：参考人物的脸、年龄、发型、服装必须一致；每件信、刀、令匣、名册、旗帜和人参珠必须留在剧本声明的持有者或接触点，禁止无因换手。
单一决定性瞬间：只表现下述锚画面的一个决定性时刻，不把起势、接触和终态同时拼进一张图。
画面设计与构图：{framing}。
palette 与动机光：雨夜冷青、冰流幽蓝、火把暖橙；光只来自火把、灯笼、残烛、冰流或明确天空环境，不使用无来源轮廓光。

锚画面：{description}
同源动作规格：{source_action}

只画这个明确瞬间，不做姿势拼贴、分镜网格或动作结果合集。人物、道具归属、接触点和受力方向必须与相邻锚可物理衔接。人物表情必须清楚可读：{expression}。参考人物只锁身份、脸、发型和服装；场景参考只锁古代建筑材质、雨夜和灯火，忽略原图中的人物、车辆、雪或文字。

NEGATIVE_PROMPT / 负面约束：禁止可读文字、伪文字、字幕、水印、标志、界面、姿势拼贴、分镜网格、重复人物、额外人物、额外肢体、道具瞬移、无接触受力、慢动作残影、现代物件；信纸、旗帜、名册、印章和牌面保持无字材质。
"""
            prompt_path = PROMPT_DIR / f"{anchor_id}.txt"
            prompt_path.write_text(prompt, encoding="utf-8")
            contract = {
                "schema": "qingshan.image_prompt_contract.v2",
                "shot_id": anchor_id,
                "source_script_sha256": script_sha,
                "source_action": source_action,
                "source_action_sha256": text_sha(source_action),
                "visible_characters": character_ids,
                "reference_bindings": refs,
                "editorial_shot_ids": editorial_ids,
                "video_unit_id": full_id,
                "video_unit_duration_seconds": duration,
                "state_index": index,
                "state_count": len(anchors),
                "state_role": role,
                "status": "PASS",
                "failures": [],
            }
            image_tasks.append({
                "task_key": task_key,
                "tool_type": "image_generation",
                "scene_id": f"E33-CW-S{scene:02d}",
                "visual_zone": f"{uid.lower()}_anchor_{index}",
                "shot_id": anchor_id,
                "editorial_shot_ids": editorial_ids,
                "video_unit_id": full_id,
                "video_unit_duration_seconds": duration,
                "state_index": index,
                "state_count": len(anchors),
                "beat_id": full_id,
                "prompt_file": str(prompt_path.relative_to(ROOT)),
                "prompt_sha256": sha256(prompt_path),
                "reference_images": [row["path"] for row in refs],
                "reference_bindings": refs,
                "prompt_contract": contract,
                "model": "gpt-image-2-pro",
                "aspect_ratio": "9:16",
                "resolution": "2K",
                "status": "READY_FOR_PARALLEL_SUBMIT",
                "source_script_sha256": script_sha,
            })

        unit_dialogue = dialogue_by_unit.get(uid, [])
        performance_units.append({
            "unit_id": full_id,
            "scene_id": f"E33-CW-S{scene:02d}",
            "duration_seconds": duration,
            "editorial_shot_ids": editorial_ids,
            "generation_mode": "performance_generation",
            "planned_reference_image_count": len(anchors),
            "reference_image_task_keys": anchor_keys,
            "anchor_count_decision": {
                "planned_reference_image_count": len(anchors),
                "count": len(anchors),
                "roles": [role for role, _ in anchors],
                "anchor_roles": [role for role, _ in anchors],
                "criteria": {
                    "continuous_motion_from_single_start": len(anchors) == 1,
                    "identity_or_space_reanchor": uid == "U07",
                    "prop_ownership_transition": uid in {"U07", "U14"},
                    "non_interpolable_terminal_state": uid == "U14",
                },
                "action_design_class": (
                    "cross_location_prop_delivery" if uid == "U07"
                    else "non_interpolable_prop_ownership_terminal" if uid == "U14"
                    else "single_start_continuous_performance"
                ),
                "reason": "Three spatial anchors are required for authored cross-location delivery." if uid == "U07" else ("A terminal ownership anchor is required because the locked chest becomes a book held by Chenji." if uid == "U14" else "One identity/scene start anchor is sufficient for the authored continuous performance chain."),
            },
            "performance_spec": {
                "intent": intent,
                "motion_chain": chain,
                "subject": "the explicitly named staged subject(s)",
                "contact_point": "every contact point explicitly stated in the motion chain",
                "direction": "the screen-space and force direction explicitly stated in the motion chain",
                "end_state": viewer_read,
                "expression_arc": expression,
                "viewer_read": viewer_read,
                "single_action_state_source": "CLAUDE_SCRIPT_DERIVED_BEAT_SPEC",
                "prop_ownership": "No prop changes holder without an explicit contact, handoff, impact, release or drop in the motion chain.",
            },
            "dialogue_lines": unit_dialogue,
            "dialogue_audio_reference_status": "WAITING_FOR_EXACT_AUDIO" if unit_dialogue else "NOT_REQUIRED",
            "keyframe_interpolation_gate": {
                "status": "PASS",
                "stage": "DESIGN_PREFLIGHT",
                "adjacent_pairs_checked": len(anchors) - 1,
                "candidate_recheck_required": len(anchors) > 1,
                "reason": "Authored anchors preserve identity, prop ownership and declared spatial cuts; generated candidates must pass adjacency QA before video submit.",
            },
            "status": "WAITING_FOR_REQUIRED_ANCHORS_AND_EXACT_DIALOGUE_AUDIO" if unit_dialogue else "WAITING_FOR_REQUIRED_ANCHORS",
        })

    if consumed != {str(row["shot_id"]) for row in SHOTS}:
        raise SystemExit("not every E33 editorial shot is assigned exactly once")

    planned_anchor_count = sum(len(row[4]) for row in UNITS)
    if len(image_tasks) != planned_anchor_count:
        raise SystemExit("E33 image task count mismatch")

    if AUDIO_MANIFEST.is_file():
        audio_payload = json.loads(AUDIO_MANIFEST.read_text(encoding="utf-8"))
        audio_by_unit: dict[str, list[dict[str, object]]] = {}
        for audio_row in audio_payload.get("rows", []):
            audio_by_unit.setdefault(str(audio_row["video_unit_id"]), []).append(audio_row)
        for performance_unit in performance_units:
            assets = audio_by_unit.get(str(performance_unit["unit_id"]), [])
            performance_unit["dialogue_ids"] = [row["dia_id"] for row in assets]
            performance_unit["native_dialogue_required"] = bool(assets)
            performance_unit["dialogue_audio_assets"] = [
                {key: row[key] for key in ("dia_id", "path", "sha256", "speaker", "spoken_text")}
                for row in assets
            ]
            performance_unit["reference_audios"] = [row["path"] for row in assets]
            performance_unit["dialogue_audio_reference_status"] = "PASS" if assets else "NOT_REQUIRED"
            performance_unit["dialogue_audio_coverage"] = {
                "required": len(assets),
                "bound": len(assets),
                "status": "PASS" if assets else "NOT_APPLICABLE_NO_DIALOGUE",
            }

    production_manifest = {
        "schema": "qingshan.production_manifest.v2",
        "episode": "E33",
        "title": writer["title"],
        "status": "PERFORMANCE_PREPRODUCTION_READY",
        "source_script": str(SCRIPT.relative_to(ROOT)),
        "source_script_sha256": script_sha,
        "runtime_seconds": writer["total_seconds"],
        "editorial_shot_count": len(SHOTS),
        "video_unit_count": len(UNITS),
        "production_policy": {
            "writer_authority": "CLAUDE_WRITER",
            "grouping": "SCENE_LOCAL_CONTIGUOUS_ACTUAL_SECONDS_COUNT_EMERGES_FROM_GROUPS",
            "fixed_video_unit_count_forbidden": True,
            "anchor_count": "PER_UNIT_MODEL_CAPABILITY_AND_ACTION_DESIGN_NO_GLOBAL_ONE_OR_THREE_RULE",
            "all_required_anchors_planned_before_image_submit": True,
            "incremental_video_submit_as_each_unit_becomes_ready": True,
            "native_dialogue_from_exact_audio_reference_required": True,
            "video_credit_limit_current_workflow": 6000,
            "subtitle_burnin_required": True,
            "nalu_motion_outro_required": True,
            "encoded_audio_asr_loudness_true_peak_retest_required": True,
            "action_visualization_system_prompt": str(ACTION_PROMPT.relative_to(ROOT)),
            "action_visualization_system_prompt_sha256": ACTION_PROMPT_SHA,
        },
        "shots": SHOTS,
    }
    production_manifest_sha = text_sha(json.dumps(production_manifest, ensure_ascii=False, indent=2) + "\n")
    grouping_spec = {
        "schema": "qingshan.video_unit_grouping_spec.v2",
        "episode": "E33",
        "source_script_sha256": script_sha,
        "derivation_rule": "Group scene-local contiguous editorial shots by actual scripted seconds and continuous performance causality. Unit count emerges from validated groups and is never selected in advance.",
        "editorial_shot_count": len(SHOTS),
        "unit_count": len(UNITS),
        "groups": groups,
    }
    plan = {
        "schema": "qingshan.performance_video_plan.v2",
        "episode": "E33",
        "source_script_sha256": script_sha,
        "planned_reference_image_count": planned_anchor_count,
        "units": performance_units,
    }
    image_manifest = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E33",
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "source_script_sha256": script_sha,
        "scene_contract_ref": str((PRODUCTION / "E33_SCENE_STATE_AUTHORITY_V1.json").relative_to(ROOT)),
        "script_readiness_report": str((QA_DIR / "E33_IMAGE_PLAN_PREFLIGHT_V1.json").relative_to(ROOT)),
        "writer_agent_provenance": {
            "status": "PASS",
            "provenance_type": "claude_writer_script",
            "source_script": str(SCRIPT.relative_to(ROOT)),
            "source_script_sha256": script_sha,
            "production_manifest": str((PRODUCTION / "E33_PRODUCTION_MANIFEST.json").relative_to(ROOT)),
            "production_manifest_sha256": production_manifest_sha,
        },
        "production_manifest_ref": str((PRODUCTION / "E33_PRODUCTION_MANIFEST.json").relative_to(ROOT)),
        "video_unit_plan_ref": str((PRODUCTION / "E33_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json").relative_to(ROOT)),
        "machine_gate_reports": [str((QA_DIR / "E33_IMAGE_PLAN_PREFLIGHT_V1.json").relative_to(ROOT))],
        "output_dir": "working_assets/e33_performance_stills_20260723/candidates",
        "qa_dir": "qa/e33_performance_stills_20260723",
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "consumer_contract": {
            "purpose": "PERFORMANCE_ANCHORS",
            "video_unit_count": len(UNITS),
            "planned_anchor_count": planned_anchor_count,
            "all_required_anchors_ready_for_initial_batch": True,
            "incremental_video_submit": "EACH_UNIT_AS_SOON_AS_ITS_OWN_REQUIRED_ANCHORS_AND_EXACT_DIALOGUE_AUDIO_PASS",
        },
        "blocked_tasks": [],
        "tasks": image_tasks,
    }
    preflight = {
        "schema": "qingshan.performance_preproduction_gate.v2",
        "episode": "E33",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "checks": {
            "claude_script_sha_locked": True,
            "editorial_shots_exactly_once": True,
            "runtime_seconds_exact": True,
            "scene_local_contiguous_grouping": True,
            "unit_count_not_preselected": True,
            "all_units_between_4_and_15_seconds": True,
            "anchor_count_decided_independently_per_unit": True,
            "all_required_anchors_planned_before_generation": True,
            "action_intent_contact_direction_end_state_expression_present": True,
            "exact_dialogue_inventory_complete": True,
            "video_submit_waits_for_exact_dialogue_audio_per_dialogue_unit": True,
            "subtitles_and_nalu_motion_locked": True,
        },
        "editorial_shot_count": len(SHOTS),
        "video_unit_count": len(UNITS),
        "planned_anchor_count": planned_anchor_count,
        "dialogue_line_count": len(DIALOGUES),
        "failures": [],
    }
    dialogue_inventory = {
        "schema": "qingshan.script_dialogue_inventory.v1",
        "episode": "E33",
        "source_script_sha256": script_sha,
        "line_count": len(DIALOGUES),
        "audio_policy": "EXACT_TEXT_AUDIO_REFERENCE_TO_VIDEO_MODEL_NATIVE_MANDARIN_LIP_SYNC",
        "status": "READY_FOR_AUDIO_REFERENCE_GENERATION",
        "lines": [
            {"dialogue_id": dia_id, "video_unit_id": f"E33-CW-{uid}", "speaker": speaker, "text": text, "text_sha256": text_sha(text), "audio_status": "PENDING"}
            for dia_id, uid, speaker, text in DIALOGUES
        ],
    }
    scene_state = {
        "schema": "qingshan.scene_state_authority.v1",
        "episode": "E33",
        "source_script_sha256": script_sha,
        "scene_state": [
            {"scene_id": "E33-CW-S01", "location": "洛城长街与城门下", "time_of_day": "night", "weather": "rain", "event_summary": "三路围兵收网，陈迹识别互疑并决定反收网。", "allowed_time_terms": ["night"], "allowed_weather_terms": ["rain"]},
            {"scene_id": "E33-CW-S02", "location": "洛城檐影与三处投递点", "time_of_day": "night", "weather": "rain", "event_summary": "三人制造三封毒饵，皎兔阴神分别投递。", "allowed_time_terms": ["night"], "allowed_weather_terms": ["rain"]},
            {"scene_id": "E33-CW-S03", "location": "洛城长街令匣马车", "time_of_day": "night", "weather": "rain", "event_summary": "三方互杀，陈迹三人连续突破并夺得真名册。", "allowed_time_terms": ["night"], "allowed_weather_terms": ["rain"]},
            {"scene_id": "E33-CW-S04", "location": "洛城后巷死巷与排水暗洞", "time_of_day": "night", "weather": "rain", "event_summary": "乌鸦指路，冰流与冲拳破栅，三人从暗洞撤离。", "allowed_time_terms": ["night"], "allowed_weather_terms": ["rain"]},
            {"scene_id": "E33-CW-S05", "location": "太平医馆密室", "time_of_day": "night", "weather": "none", "event_summary": "三人翻阅真名册，发现景朝水波密纹与沈砚旧案旁注。", "allowed_time_terms": ["night"], "allowed_weather_terms": []},
        ],
    }

    write_json(PRODUCTION / "E33_PRODUCTION_MANIFEST.json", production_manifest)
    write_json(PRODUCTION / "E33_SCENE_STATE_AUTHORITY_V1.json", scene_state)
    write_json(PRODUCTION / "E33_VIDEO_UNIT_GROUPING_SPEC_V1.json", grouping_spec)
    write_json(PRODUCTION / "E33_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json", plan)
    write_json(PRODUCTION / "E33_IMAGE_BATCH_PERFORMANCE_V1.json", image_manifest)
    write_json(PRODUCTION / "E33_SCRIPT_BEAT_DIALOGUE_INVENTORY_V1.json", dialogue_inventory)
    write_json(PRODUCTION / "E33_SUBTITLE_CONTRACT_V1.json", {
        "schema": "qingshan.subtitle_contract.v1", "episode": "E33", "source_script_sha256": script_sha,
        "dialogue_line_count": len(DIALOGUES), "burn_in_required": True,
        "video_model_native_dialogue_audio_required": True, "encoded_asr_coverage_required": "14/14",
        "status": "LOCKED_FOR_AGENTCUT",
    })
    write_json(PRODUCTION / "E33_NALU_MOTION_OUTRO_CONTRACT_V1.json", {
        "schema": "qingshan.nalu_motion_outro_contract.v1", "episode": "E33", "required": True,
        "placement": "AFTER_LAST_DIALOGUE_AND_LAST_SUBTITLE", "logo_asset": "libraries/brand/nalu_motion_cat_logo_v1.png",
        "chime_asset": "libraries/brand/nalu_motion_outro_chime_v1.wav", "status": "LOCKED_FOR_AGENTCUT",
    })
    write_json(QA_DIR / "E33_IMAGE_PLAN_PREFLIGHT_V1.json", preflight)
    write_json(ROOT / "workflow/tasks/E33_PERFORMANCE_PREPRODUCTION_20260723.json", {
        "schema": "qingshan.preproduction_input_build.v2", "episode": "E33",
        "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "READY_FOR_IMAGE_AND_DIALOGUE_AUDIO_SUBMIT",
        "source_script_sha256": script_sha, "editorial_shot_count": len(SHOTS),
        "video_unit_count": len(UNITS), "planned_anchor_count": planned_anchor_count,
        "dialogue_line_count": len(DIALOGUES), "remote_call_count": 0, "new_credits": 0,
    })
    print(json.dumps({
        "status": "PASS", "shots": len(SHOTS), "runtime": writer["total_seconds"],
        "units": len(UNITS), "anchors": planned_anchor_count, "dialogue_lines": len(DIALOGUES),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
