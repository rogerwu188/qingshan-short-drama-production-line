#!/usr/bin/env python3
"""Build E31 performance-generation preproduction from the locked Claude script."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "workflow/claude_writer_agent/scripts/E31剧本_ClaudeWriter_v1.md"
WRITER_MANIFEST = ROOT / "workflow/claude_writer_agent/scripts/E31_manifest.json"
PRODUCTION = ROOT / "workflow/claude_writer_agent/production/e31_claude_writer_v1_20260722"
PROMPT_DIR = PRODUCTION / "image_prompts_performance_v1"
SCENE_EXTERIOR = "working_assets/e29_claude_writer_v1_stills_20260722/candidates/E29_E29-CW-S01-SH01-STILL-V1_4f6f7833-2bff-40e4-9a98-69b4d4054bc7.png"
SCENE_INTERIOR = "assets/reference/e08_api_fallback_20260709/scenes/SCENE-taiping-front-hall-clean-20260709.jpg"
ACTION_VISUALIZATION_PROMPT = "codex_docs/教codex动作可视化_系统提示词_v1_20260722.md"
ACTION_VISUALIZATION_PROMPT_SHA256 = "04f47991157e9a1ce3fcab7be6bf3b89ed76a2f34b52a27a0d4b393bca0c736f"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def shot(scene: int, number: int, duration: int, action: str) -> dict[str, object]:
    return {
        "shot_id": f"E31-CW-S{scene:02d}-SH{number:02d}",
        "scene_id": f"E31-CW-S{scene:02d}",
        "duration_seconds": duration,
        "action": action,
    }


SHOTS = [
    shot(1, 1, 8, "雪夜靖王府前庭航拍定场，火把与乱众把恢弘建筑切成失序战场。"),
    shot(1, 2, 7, "云妃与静妃两拨侍从扭打争抢名单，纸页在相反拉力下撕裂。"),
    shot(1, 3, 7, "落地灯笼被踩碎，火舌沿檐柱上窜，两名侍从对峙喊话。"),
    shot(1, 4, 10, "内院家丁隐在廊柱暗处筛看飞散残页，只寻找沈砚并准备焚毁。"),
    shot(2, 1, 12, "陈迹把三卷缺不同页的名单封好推给皎兔，两人说明缺页试反应。"),
    shot(2, 2, 8, "皎兔割破眉心，黑甲倒持长刀的阴神从血痕逸出并穿窗。"),
    shot(2, 3, 4, "阴神穿入云妃阁，侍从只因缺页咒骂，没有恐惧。"),
    shot(2, 4, 4, "阴神穿入静妃院，静妃冷笑搁下名单。"),
    shot(2, 5, 4, "阴神潜入内院，枯手见沈砚后僵住掐纸，烛焰骤灭。"),
    shot(2, 6, 4, "阴神沿原路穿墙归窍，皎兔肉身睁眼。"),
    shot(2, 7, 4, "皎兔与陈迹确认真正害怕景朝的是沉默内院。"),
    shot(3, 1, 6, "陈迹与云羊横穿雪夜回廊，三名杀手从檐上、柱后、假山同时扑落。"),
    shot(3, 2, 2, "乌云在墙头弓背竖尾尖啸示警。"),
    shot(3, 3, 4, "第一杀手短刃刺喉，陈迹顿足翻掌引爆冰流。"),
    shot(3, 4, 4, "冰流封住地砖栏杆檐水，第一杀手刺空并失足滑开。"),
    shot(3, 5, 4, "第二杀手贴冰侧滑，云羊咬指点睛令纸人展开遮眼。"),
    shot(3, 6, 8, "云羊冲拳砸碎冰栏，冰屑定向掀翻杀手撞柱；第三人转向火盆。"),
    shot(3, 7, 10, "第三人焚纸遁烟，陈迹冻住半片纸角；云羊与陈迹判断景朝要灭沈砚线。"),
    shot(4, 1, 7, "灰衣门客在侧阁孤灯下起身作揖，陈迹站立不坐。"),
    shot(4, 2, 7, "两人以沈砚旧疮互相试探，门客平静，陈迹冷硬。"),
    shot(4, 3, 10, "门客从袖中取骨牌推到案心，以密谍司内鬼身份交换完整名单。"),
    shot(4, 4, 9, "陈迹拒绝伸手追问来源，门客退后微笑揭示见过围猎调令印。"),
    shot(5, 1, 7, "陈迹把骨牌递给云羊，云羊翻到印纹后脸色骤变。"),
    shot(5, 2, 7, "云羊与陈迹确认发令者高过直属上司，信任圈坍缩。"),
    shot(5, 3, 8, "陈迹指尖冷雾凝散，凝视骨牌追问它是投名状还是陷阱。"),
    shot(5, 4, 8, "镜头拉成雪夜王府残火大远景，火光在重檐下明灭并切黑。"),
]


UNITS = [
    ("U01", 1, 8, [1], [], "航拍俯瞰靖王府雪夜前庭，重檐叠院、火把乱星与抢夺名单的人潮同框。", "乱局建立", "火把与撕纸动作把平静王府变成失控战场", "惊惶与贪婪在人群脸上交替", "观众一眼读懂假名单点燃王府"),
    ("U02", 1, 14, [2, 3], [], "两拨侍从在中景争抢同一卷名单，纸页已绷紧，灯笼倒在脚边尚未破裂。", "争抢升级", "双方相反拉力撕裂纸页，后退者踩碎灯笼，火舌上窜迫使人群散开", "两名领头侍从从愤怒转为被火光惊到但仍不松手", "观众读懂云妃与静妃公开撕破脸"),
    ("U03", 1, 10, [4], [], "廊柱阴影中三个内院家丁贴墙站立，前景残页飞过，领头者盯住纸面。", "暗线找名", "领头者截住残页、快速扫视、低声命令同伴，未找到时把纸推走继续搜", "压抑焦躁，眼神只追纸页不看乱斗", "观众读懂内院不抢名单，只怕一个特定名字"),
    ("U04", 2, 12, [1], ["chenji", "jiaotu"], "医馆暖灯下，陈迹与皎兔隔案对坐，三卷封好的名单并排，陈迹手掌正把最后一卷推向皎兔。", "缺页试反应", "陈迹依次点明三卷缺页差异并推卷，皎兔接卷后用指尖抵住眉心提出亲眼查验", "陈迹冷静笃定，皎兔从审视转为决断", "观众读懂三份名单是可追踪反应的实验"),
    ("U05", 2, 8, [2], ["jiaotu"], "皎兔端坐医馆灯下闭目，右手指甲刚抵眉心，身后窗扇与衣带静止。", "阴神出窍", "指甲划出细血痕，黑甲阴神从眉心血线后方完整分离，倒持长刀转身穿窗，肉身始终端坐不动", "皎兔肉身克制忍痛，阴神睁眼后冷峻警觉", "观众明确看到一具肉身与一个黑甲分身分离"),
    ("U06", 2, 4, [3], [], "云妃阁锦红帐幔内，侍从双手展开缺页名单，黑甲阴神半透明地停在屏风边观察。", "云妃无惧", "侍从发现关键位置缺页后拍纸咒骂，阴神贴墙观察后穿墙离开", "侍从烦躁愤怒但没有恐惧", "观众读懂云妃一方只是恼怒"),
    ("U07", 2, 4, [4], [], "静妃院素青内室，静妃坐在案边扫视名单，黑甲阴神隐在帘后。", "静妃无惧", "静妃扫到目标位置后冷笑，把名单平放到茶盏旁，阴神转身离开", "轻蔑冷淡，呼吸和手势都不慌", "观众读懂沈砚对静妃如陌路"),
    ("U08", 2, 4, [5], [], "深黛内院孤灯下，枯瘦的手悬在名单上方，黑甲阴神在暗处凝视。", "内院失态", "食指触到目标位置后骤停，五指掐皱纸面，手腕发抖；无风烛焰随惊惧抽气骤灭", "从强装平静突变为失控恐惧", "观众看不到文字也能从掐纸与灭灯读懂名字击中要害"),
    ("U09", 2, 8, [6, 7], ["chenji", "jiaotu"], "医馆暖灯下皎兔肉身端坐，黑甲阴神正从背后贴近归窍，陈迹在对面凝视。", "取证归来", "阴神收回眉心，皎兔睁眼吐气复述三院反应；陈迹垂眸完成推断", "皎兔疲惫后转寒，陈迹由确认转为更深戒备", "观众读懂沉默内院才是真正怕景朝的一方"),
    ("U10", 3, 8, [1, 2], ["chenji", "yunyang", "wuyun"], "雪夜王府回廊，陈迹与云羊向内院疾行，墙头黑猫乌云弓背竖尾，三处黑影正蓄势扑落。", "伏击爆发", "乌云尖啸，陈迹和云羊同时转头；三名杀手分别从檐、柱、假山沿明确落点扑向陈迹怀中名单", "陈迹瞬间警觉，云羊咬紧牙关，乌云炸毛", "观众清楚看见三路伏击共同目标是名单"),
    ("U11", 3, 8, [3, 4], ["chenji"], "回廊中第一杀手短刃已进入陈迹喉前半臂距离，陈迹后脚钉地、掌心朝下，地砖尚未结冰。", "冰流挡刺", "杀手沿直线刺喉；陈迹顿足翻掌，幽蓝冰流从掌下沿地砖向前炸开并攀上栏杆檐水；杀手因脚底突然结冰刺空滑向侧方", "杀手从狠厉转为惊愕失衡，陈迹目光冷定毫不后仰", "观众看懂冰流改变摩擦与落脚点，从而让刺杀落空"),
    ("U12", 3, 4, [5], ["yunyang"], "第二杀手贴着幽蓝冰面侧滑逼近，云羊在其前方咬破指尖，数张未展开纸人夹在指间。", "纸屏遮眼", "云羊以血点睛，纸人从指间依次腾空展开并在杀手面前合成纸影屏障，遮断其视线但不缠绕四肢", "云羊专注狠决，杀手在遮眼瞬间慌乱抬臂", "观众读懂纸人用途是夺取视觉而不是无因束缚"),
    ("U13", 3, 8, [6], ["yunyang"], "云羊拳锋距冰封栏杆一掌，失明杀手贴近栏杆，第三名杀手已朝火盆转身。", "碎栏传力", "云羊蹬地转胯冲拳命中冰栏固定接触点，冲击沿栏杆传开使其定向爆裂；冰屑沿拳锋方向掀翻贴近杀手并将其撞上廊柱", "云羊爆发怒意，杀手从失明惊慌转为撞柱痛苦", "观众读懂拳击栏杆、栏杆碎裂、冰屑击人、撞柱的完整传力链"),
    ("U14", 3, 10, [7], ["chenji", "yunyang"], "火盆旁第三名杀手捏着字纸准备投入火中，陈迹正从冰面一步扑近，云羊在后方收拳喘息。", "焚证与截证", "杀手把纸投入火盆后借烟后退；陈迹沿最短路线扑到火盆边放出冷雾，只冻结灰烬边缘的半片纸角；他拾起纸角与云羊判断景朝要烧掉沈砚线", "杀手仓皇决绝，云羊喘息中愤怒，陈迹由急迫转为寒意", "观众看懂敌人宁可焚证，以及陈迹只抢回半片证据"),
    ("U15", 4, 14, [1, 2], ["chenji"], "侧阁孤灯下，灰衣门客刚从座位从容起身作揖，陈迹站在门内不坐，两人隔案对视。", "交易试探", "门客作揖后以掌示座，陈迹拒绝前进并指出内院灭灯；门客保持距离不回答", "门客温和无懈可击，陈迹冷眼带压迫", "观众读懂双方都在试探，陈迹不接受对方节奏"),
    ("U16", 4, 10, [3], ["chenji"], "灰衣门客袖口已露出一枚冷白骨牌，案心空着，陈迹视线锁住骨牌但双手垂在身侧。", "以内鬼换名单", "门客从袖中取牌并用两指推到案心，提出以内鬼姓名换完整名单；陈迹始终不碰骨牌", "门客克制自信，陈迹警惕且不露贪念", "观众从推牌与拒碰读懂交易诱饵和权力博弈"),
    ("U17", 4, 9, [4], ["chenji"], "骨牌停在案心，陈迹俯视骨牌追问，灰衣门客已退后半步、半张脸藏在暗里。", "调令印钩子", "陈迹追问内鬼来源；门客微笑退后，抬眼揭示主子见过围猎调令的印，随后停在门边不再解释", "陈迹眼神收紧，门客笑意平和却危险", "观众读懂门客掌握的是发令链证据而非普通传闻"),
    ("U18", 5, 14, [1, 2], ["chenji", "yunyang"], "雪夜外廊近景，陈迹把冷白骨牌递到云羊掌前，云羊尚未看清背面印纹，庭中残火在后景。", "印纹越级", "云羊接牌翻面，看到印纹后屏息变色；他用指腹确认刻痕并说明发令者高过直属上司，陈迹望向火光补全推断", "云羊从疑惑突变为震骇与自我怀疑，陈迹沉冷", "观众从云羊的骤变读懂这枚印触碰禁区"),
    ("U19", 5, 8, [3], ["chenji"], "陈迹独立外廊，骨牌平放掌心，指尖一缕冷雾刚凝出，眼睛低垂看牌。", "投名状还是陷阱", "冷雾在指尖凝聚又自行散去；陈迹先低声质疑投名状，再抬眼直视暗处说出假名单陷阱", "从克制思索转为寒冷警觉，最后眼神锁定未知敌人", "观众读懂他没有被证据牵着走，主动怀疑交易本身"),
    ("U20", 5, 8, [4], [], "靖王府雪夜大远景，重檐静立，满庭残火未熄，风雪重新增强。", "森然收尾", "镜头持续后拉，残火被风压低又抬起，人物缩成微小黑点，最后自然切黑", "建筑无表情，以残火与风雪制造庞大压迫", "观众读懂敌人已从院中升到更高权力层"),
]


CHARACTERS = {
    "chenji": "assets/reference/e10_20260709/characters/CHAR-chenji-young-apprentice-canonical-v2-20260709.jpg",
    "jiaotu": "assets/reference/characters_canonical_20260709/images/CHAR-jiaotu-ancient-card-20260709.jpg",
    "yunyang": "working_assets/api_reference_images_20260704/male_yunyang_ancient_ref_20260704_api.jpg",
    "wuyun": "working_assets/e21_scene_fidelity_r3_identity_parallel_20260718/image_candidates/E21_E21-S01-WUYUN-PURE-BLACK_2af7eb4b-625b-4eeb-bfd5-407b40a24ae2.png",
}


ABILITY_LOGIC = {
    "U05": "皎兔的能力是阴神出窍，因此无形的侦察意志必须以黑甲分身从肉身完整分离并穿墙来外化。",
    "U06": "阴神以无实体观察者逻辑贴墙、穿墙，不与房内人物发生物理碰撞。",
    "U07": "阴神以无实体观察者逻辑藏在帘后并穿墙离开，不用通用隐身闪光。",
    "U08": "阴神只负责见证；真正的恐惧由掐纸、手抖和烛灭这些人物及环境反馈外化。",
    "U09": "阴神归窍表现为黑甲分身沿眉心收回肉身，符合皎兔五感回传的能力逻辑。",
    "U11": "陈迹的冰流沿地砖、栏杆和檐水传导，改变接触面的摩擦与结构状态，使刺杀失足而非让刀无因停下。",
    "U12": "云羊的能力通过血点睛激活纸人，纸影遮断视线而非凭空束缚人体。",
    "U13": "云羊以实体冲拳把力传入已经被冰流冻结的栏杆，栏杆碎裂和冰屑飞向明确方向是力量的可见介质。",
    "U14": "陈迹的冷雾只能冻结实际触及的灰烬边缘，因此只救回半片纸角，不能隔空恢复整张证据。",
}


INVISIBLE_ELEMENTS = {
    "U01": "名单造成的集体失控与王府秩序崩塌",
    "U02": "双方都认为名单关系自身生死的争夺意图",
    "U03": "内院只害怕一个名字的隐藏目标",
    "U04": "缺页实验如何追踪三方真实恐惧",
    "U05": "肉眼不可见的阴神出窍与远程侦察",
    "U06": "云妃一方对沈砚并不恐惧",
    "U07": "静妃对沈砚完全陌生",
    "U08": "内院对沈砚的真实恐惧",
    "U09": "阴神把三院感知带回肉身并形成结论",
    "U10": "三路杀手共同夺取完整名单的意图",
    "U11": "冰流如何阻断刺杀并改变杀手受力",
    "U12": "纸人如何夺走杀手视觉",
    "U13": "冲拳如何经冰栏传力并击倒目标",
    "U14": "景朝宁可焚证也不让沈砚线留下",
    "U15": "双方都在试探而不接受对方节奏",
    "U16": "骨牌是诱使陈迹交出完整名单的交易筹码",
    "U17": "调令印意味着内鬼位于发令链而非普通办事层",
    "U18": "印纹触及云羊从未能接近的权力层级",
    "U19": "证据可能既是投名状也是诱饵",
    "U20": "敌人已经从一座院落上升到庞大权力结构",
}


FORCE_FEEDBACK = {
    "U11": "刀锋刺空、杀手脚底横滑、握刀腕与上身被惯性带偏；陈迹后脚稳定不退。",
    "U12": "纸屏扑面后杀手抬臂护眼、滑行方向失准；纸张随迎面气流向后绷紧。",
    "U13": "拳面压入冰栏、裂纹沿接触点扩散、冰屑按拳向激射、杀手背部撞柱并反弹落地。",
    "U14": "火焰吞纸并卷起烟，冷雾接触灰烬后结霜收缩，陈迹只抓到半片硬化纸角。",
}


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
        "qa_report": "configs/series_continuity_asset_registry_20260712.json" if role == "character" else "E31_SCENE_STYLE_REFERENCE_ONLY",
    }


def main() -> int:
    writer = json.loads(WRITER_MANIFEST.read_text(encoding="utf-8"))
    script_sha = sha256(SCRIPT)
    if writer["sha256"] != script_sha:
        raise SystemExit("E31 script SHA does not match Claude Writer manifest")
    action_prompt_path = ROOT / ACTION_VISUALIZATION_PROMPT
    if not action_prompt_path.is_file() or sha256(action_prompt_path) != ACTION_VISUALIZATION_PROMPT_SHA256:
        raise SystemExit("CL2X-605 action-visualization system prompt missing or SHA mismatch")
    if len(SHOTS) != writer["shots"] or sum(int(row["duration_seconds"]) for row in SHOTS) != writer["total_seconds"]:
        raise SystemExit("E31 shot count or duration mismatch")
    if sum(unit[2] for unit in UNITS) != writer["total_seconds"]:
        raise SystemExit("E31 video-unit duration mismatch")
    if any(not 4 <= unit[2] <= 15 for unit in UNITS):
        raise SystemExit("E31 video-unit duration outside 4-15 seconds")

    scene_shots: dict[int, list[dict[str, object]]] = {}
    for row in SHOTS:
        scene_shots.setdefault(int(str(row["scene_id"])[-2:]), []).append(row)

    grouping = []
    consumed: set[str] = set()
    for unit_id, scene, duration, numbers, *_ in UNITS:
        ids = [f"E31-CW-S{scene:02d}-SH{number:02d}" for number in numbers]
        actual = sum(int(row["duration_seconds"]) for row in scene_shots[scene] if row["shot_id"] in ids)
        if actual != duration:
            raise SystemExit(f"{unit_id} duration {duration} does not match shots {actual}")
        if consumed.intersection(ids):
            raise SystemExit(f"{unit_id} reuses editorial shots")
        consumed.update(ids)
        grouping.append({"unit_id": f"E31-CW-{unit_id}", "scene_id": f"E31-CW-S{scene:02d}", "duration_seconds": duration, "editorial_shot_ids": ids})
    if consumed != {str(row["shot_id"]) for row in SHOTS}:
        raise SystemExit("not every E31 editorial shot is assigned exactly once")

    production_manifest = {
        "schema": "qingshan.production_manifest.v2",
        "episode": "E31",
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
            "generation_mode": "performance_generation",
            "reference_image_policy": "ONE_OR_TWO_IDENTITY_SCENE_ANCHORS_AS_REQUIRED_BY_MODEL_AND_ACTION_DESIGN_NO_FIXED_MINIMUM_ABOVE_ONE",
            "multi_pose_state_sheets_forbidden_as_default": True,
            "single_action_state_source_required": True,
            "native_dialogue_audio_reference_required": True,
            "incremental_video_submit_as_each_unit_becomes_ready": True,
            "video_credit_limit_current_workflow": 6000,
            "subtitle_burnin_required": True,
            "nalu_motion_outro_required": True,
            "encoded_audio_asr_loudness_true_peak_retest_required": True,
            "action_visualization_system_prompt": ACTION_VISUALIZATION_PROMPT,
            "action_visualization_system_prompt_sha256": ACTION_VISUALIZATION_PROMPT_SHA256,
            "action_readability_gate_30": "BLIND_VIEWER_CAN_READ_ACTION_PURPOSE_AND_CAUSALITY",
        },
        "shots": SHOTS,
    }
    grouping_spec = {
        "schema": "qingshan.video_unit_grouping_spec.v2",
        "episode": "E31",
        "source_script_sha256": script_sha,
        "derivation_rule": "Group only scene-local contiguous editorial shots by actual scripted seconds and continuous performance causality. The count is the validated group count, never a target selected in advance.",
        "unit_count": len(UNITS),
        "groups": grouping,
    }

    performance_units = []
    tasks = []
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    for unit_id, scene, duration, numbers, character_ids, anchor, intent, causality, expression, viewer_read in UNITS:
        full_id = f"E31-CW-{unit_id}"
        scene_path = SCENE_INTERIOR if scene in {2, 4} else SCENE_EXTERIOR
        refs = [binding("character", char_id, CHARACTERS[char_id]) for char_id in character_ids]
        refs.append(binding("scene", f"E31-CW-S{scene:02d}", scene_path))
        source_action = f"{intent}：{causality}；表情弧：{expression}；观众读法：{viewer_read}。"
        shot_id = f"{full_id}-A1"
        prompt = f"""竖屏 9:16，电影级中国古装玄幻短剧，真实人物与真实物理，雪夜冷蓝、火光暖橙，禁止现代物件。

这是 {full_id} 的唯一身份/场景起始锚图，不是姿势拼贴，不是分镜网格。视频模型将从这张图按连续表演脚本生成完整动作。

起始画面：{anchor}
源动作（必须逐字绑定）：{source_action}

只画动作开始前或刚起势的单一瞬间。人物、道具归属、空间距离必须支持后续真实连续运动；不要把后续动作结果提前画进起始帧。人物表情必须清楚可读：{expression}。
参考图中的人物只用于锁定身份、脸、发型与服装；场景参考只用于锁定古代雪夜建筑、材质和灯光，忽略其中原有人物与车辆。画面不得出现可读文字、伪文字、字幕、水印、标志或界面。纸张与牌面保持无字材质。
"""
        prompt_path = PROMPT_DIR / f"{shot_id}.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        contract = {
            "schema": "qingshan.image_prompt_contract.v2",
            "shot_id": shot_id,
            "source_script_sha256": script_sha,
            "source_action": source_action,
            "source_action_sha256": text_sha(source_action),
            "visible_characters": character_ids,
            "character_binding_mode": "EXPLICIT_CANONICAL_IDENTITIES_ONLY",
            "reference_bindings": refs,
            "editorial_shot_ids": [f"E31-CW-S{scene:02d}-SH{number:02d}" for number in numbers],
            "video_unit_id": full_id,
            "video_unit_duration_seconds": duration,
            "state_index": 1,
            "state_count": 1,
            "state_role": "performance_start_anchor",
            "status": "PASS",
            "failures": [],
        }
        tasks.append({
            "task_key": f"{full_id}-A1-STILL-V1",
            "tool_type": "image_generation",
            "scene_id": f"E31-CW-S{scene:02d}",
            "shot_id": shot_id,
            "editorial_shot_ids": contract["editorial_shot_ids"],
            "video_unit_id": full_id,
            "video_unit_duration_seconds": duration,
            "state_index": 1,
            "state_count": 1,
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
        performance_units.append({
            "unit_id": full_id,
            "scene_id": f"E31-CW-S{scene:02d}",
            "duration_seconds": duration,
            "editorial_shot_ids": contract["editorial_shot_ids"],
            "generation_mode": "performance_generation",
            "planned_reference_image_count": 1,
            "reference_image_task_keys": [f"{full_id}-A1-STILL-V1"],
            "still_sequence_only_allowed": True,
            "performance_spec": {
                "motion_beats": [{
                    "subject": "the explicitly staged principal subject(s)",
                    "action": causality,
                    "contact_point": "the stated hand, foot, weapon, paper, railing, token or floor contact point",
                    "direction": "the explicit screen-space and force direction stated in the action chain",
                    "end_state": viewer_read,
                    "intent": intent,
                    "invisible_element": INVISIBLE_ELEMENTS[unit_id],
                    "externalized_visible_phenomenon": causality,
                    "ability_logic": ABILITY_LOGIC.get(unit_id, "该节拍使用真实身体、道具、环境与社会反应建立因果，不调用无来源的通用特效。"),
                    "force_feedback": FORCE_FEEDBACK.get(unit_id, causality),
                    "visible_causality": causality,
                    "expression": expression,
                    "viewer_read": viewer_read,
                }],
                "prop_ownership": "Every paper, blade, token and weapon remains with its declared holder until an explicit handoff, impact or drop.",
            },
            "keyframe_interpolation_gate": {"status": "PASS", "adjacent_pairs_checked": 0, "reason": "Single performance start anchor; continuous motion is authored in the motion spec."},
            "dialogue_policy": "VIDEO_MODEL_NATIVE_MANDARIN_FROM_EXACT_AUDIO_REFERENCE_WHEN_DIALOGUE_PRESENT",
            "status": "WAITING_FOR_ANCHOR_AND_DIALOGUE_AUDIO",
        })

    gate_path = ROOT / "qa/e31_performance_preproduction_20260722/E31_IMAGE_PLAN_PREFLIGHT_V1.json"
    gate = {
        "schema": "qingshan.performance_preproduction_gate.v1",
        "episode": "E31",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS",
        "checks": {
            "claude_script_sha_locked": True,
            "editorial_shots_exactly_once": True,
            "runtime_seconds_exact": True,
            "scene_local_contiguous_grouping": True,
            "unit_count_not_preselected": True,
            "all_units_between_4_and_15_seconds": True,
            "one_start_anchor_per_unit_intentional": True,
            "fixed_multi_state_minimum_removed": True,
            "single_action_state_source": True,
            "action_intent_visible_causality_expression_viewer_read_present": True,
            "video_submission_waits_for_exact_dialogue_audio_references": True,
        },
        "editorial_shot_count": len(SHOTS),
        "video_unit_count": len(UNITS),
        "planned_image_count": len(tasks),
        "failures": [],
    }
    image_manifest = {
        "schema": "qingshan.episode_parallel_batch.v1",
        "episode": "E31",
        "status": "READY_TO_SUBMIT_CONCURRENTLY",
        "source_script_sha256": script_sha,
        "production_manifest_ref": str((PRODUCTION / "E31_PRODUCTION_MANIFEST.json").relative_to(ROOT)),
        "video_unit_plan_ref": str((PRODUCTION / "E31_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json").relative_to(ROOT)),
        "machine_gate_reports": [str(gate_path.relative_to(ROOT))],
        "output_dir": "working_assets/e31_performance_stills_20260722/candidates",
        "qa_dir": "qa/e31_performance_stills_20260722",
        "retry_policy": "FAILED_ITEMS_ONLY_CHANGED_INPUT_REQUIRED",
        "consumer_contract": {
            "purpose": "PERFORMANCE_START_ANCHORS",
            "video_unit_count": len(UNITS),
            "planned_anchor_count": len(tasks),
            "fixed_state_minimum_above_one": False,
            "incremental_video_submit": "EACH_UNIT_AS_SOON_AS_ITS_ANCHOR_AND_EXACT_DIALOGUE_AUDIO_ARE_READY",
        },
        "blocked_tasks": [],
        "tasks": tasks,
    }
    subtitle = {
        "schema": "qingshan.subtitle_contract.v1",
        "episode": "E31",
        "source_script_sha256": script_sha,
        "dialogue_line_count": 20,
        "burn_in_required": True,
        "video_model_native_dialogue_audio_required": True,
        "encoded_asr_coverage_required": "20/20",
        "status": "LOCKED_FOR_AGENTCUT",
    }
    outro = {
        "schema": "qingshan.nalu_motion_outro_contract.v1",
        "episode": "E31",
        "required": True,
        "placement": "AFTER_LAST_DIALOGUE_AND_LAST_SUBTITLE",
        "logo_asset": "libraries/brand/nalu_motion_cat_logo_v1.png",
        "chime_asset": "libraries/brand/nalu_motion_outro_chime_v1.wav",
        "status": "LOCKED_FOR_AGENTCUT",
    }

    write_json(PRODUCTION / "E31_PRODUCTION_MANIFEST.json", production_manifest)
    write_json(PRODUCTION / "E31_VIDEO_UNIT_GROUPING_SPEC_V1.json", grouping_spec)
    write_json(PRODUCTION / "E31_VIDEO_UNIT_PERFORMANCE_PLAN_V1.json", {"schema": "qingshan.performance_video_plan.v1", "episode": "E31", "source_script_sha256": script_sha, "units": performance_units})
    write_json(PRODUCTION / "E31_IMAGE_BATCH_PERFORMANCE_V1.json", image_manifest)
    write_json(PRODUCTION / "E31_SUBTITLE_CONTRACT_V1.json", subtitle)
    write_json(PRODUCTION / "E31_NALU_MOTION_OUTRO_CONTRACT_V1.json", outro)
    write_json(gate_path, gate)
    write_json(ROOT / "workflow/tasks/E31_PERFORMANCE_PREPRODUCTION_20260722.json", {
        "schema": "qingshan.preproduction_input_build.v2",
        "episode": "E31",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY_FOR_IMAGE_SUBMIT",
        "source_script_sha256": script_sha,
        "editorial_shot_count": len(SHOTS),
        "video_unit_count": len(UNITS),
        "planned_anchor_count": len(tasks),
        "remote_call_count": 0,
        "new_credits": 0,
    })
    print(json.dumps({"status": "PASS", "shots": len(SHOTS), "runtime": 173, "units": len(UNITS), "anchors": len(tasks)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
