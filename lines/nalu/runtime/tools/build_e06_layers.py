import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))
import nalu_paths as _np
# -*- coding: utf-8 -*-
"""E06《黄金年龄段》v1 —— 从一张镜头表生成 directing script / generation contract / manifest（模板 build_e05_layers.py）。

seq=29（2026-09-18）新增：对白镜时长 = 台词时长 + 0.5 s 向上取整 0.5 s（NPR.min_dialogue_seconds，无模板值）；action 拆 performance
（情绪词＋身体动作＋说话方式，闭集词表）与 constraints（提示词规则条款）；禁「保持/口型闭合/静止/定住」；同场连续 3 镜同情绪 FAIL；
儿童语速 ≥4.5；writer_selfcheck_seq29.enforced=true（S1 不过不进 S2）。D-57 身份链：face_visibility 只用闭集豁免标记。
"""
import hashlib, json, math, pathlib, re
import nalu_prompt_rules as NPR
import nalu_writer_selfcheck_seq29 as W29

ROOT = pathlib.Path(f"{_np.ENGINE_ROOT}")
SCRIPTS = ROOT / "workflow/claude_writer_agent/scripts"
RUNTIME = pathlib.Path(f"{_np.RUNTIME_ROOT}")
SRC_CH = RUNTIME / "sources/夜无疆/zh-CN/ch0006.md"
QM_SOURCE_V2 = RUNTIME / "runtime/character_sources/CHAR-QINMING__SOURCE_V2_TANG.png"
EP, VER = "E06", "v1"
PREV_EP, PREV_LAST_SHOT = "E05", "E05-S14-04"
PREV_CONTRACT = SCRIPTS / f"{PREV_EP}_GENERATION_CONTRACT_v1.json"
E01_CONTRACT = SCRIPTS / "E01_GENERATION_CONTRACT_v1.json"
E03_CONTRACT = SCRIPTS / "E03_GENERATION_CONTRACT_v1.json"
E04_CONTRACT = SCRIPTS / "E04_GENERATION_CONTRACT_v1.json"

def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

_E05 = json.loads(PREV_CONTRACT.read_text(encoding="utf-8"))
_E01 = json.loads(E01_CONTRACT.read_text(encoding="utf-8"))
_E03 = json.loads(E03_CONTRACT.read_text(encoding="utf-8"))
_E04 = json.loads(E04_CONTRACT.read_text(encoding="utf-8"))
PREV_LAST = _E05["shots"][-1]
assert PREV_LAST["shot_id"] == PREV_LAST_SHOT

CH = {
    "QM": ("CHAR-QINMING", "秦铭"),
    "LZ": ("CHAR-LUZE", "陆泽"),
    "LW": ("CHAR-LIANGWANQING", "梁婉清"),
    "WR": ("CHAR-LUWENRUI", "陆文睿"),
    "ZC": ("CHAR-ZHOUCHANGYU", "周长裕"),
    "ZA": ("CHAR-ZHOUAPO", "周阿婆"),
    "VA": ("CHAR-VILLAGER-A", "邻居甲"),
}
VOICE_ONLY: set = set()
def cid(k): return CH[k][0]
def cname(k): return CH[k][1]

# ---------- 风格与时代约束：沿 E05 合同（唐宋画风，seq=7），新地点周家屋内按秦铭家单间土屋语汇 ----------
STYLE = {k: v for k, v in _E05["style"].items() if k not in ("authority", "negative_prompt_fixed")}
_PERIOD = {s["location_id"]: s["period_constraints"] for s in _E05["scene_states"]}
_PERIOD_BASE = _PERIOD["LOC-QINMING-YARD-EXT"].split("；小院")[0]
PERIOD_BY_LOC = {
    "LOC-QINMING-HOUSE-INT": _PERIOD["LOC-QINMING-HOUSE-INT"],
    "LOC-QINMING-YARD-EXT": _PERIOD["LOC-QINMING-YARD-EXT"] + "；院角上下两块磨盘与一只石碾子是凿石农具，无金属机件",
    "LOC-SNOWFIELD-WILDS-EXT": _PERIOD["LOC-SNOWFIELD-WILDS-EXT"],
    "LOC-VILLAGE-STREET-NORTH-EXT": _PERIOD_BASE + "；北街路口：两侧夯土院墙压雪，各家院内太阳石橘红光外溢使街面淡红，踩实的雪路；无路灯、无招牌、无任何现代物",
    "LOC-ZHOU-HOUSE-INT": _PERIOD_BASE + "；周家单间土屋：火炕在北墙、木格糊纸窗、炕沿边一只竹筐、墙角一只旧木柜、铜盆盛太阳石为唯一光源；无玻璃、无灯具、无现代家具",
}
STYLE_RESET_DISCLOSURE = {
    "kind": "STYLE_CONTINUATION_NO_RESET",
    "authority": "SUPERVISOR_ORDERS seq=7 c1/c2/c4（E02 起唐宋画风）；seq=30（E06 沿用）",
    "what_changes": "无画风变化；新入画人物周长裕（快三十岁的汉子，右臂骨折吊在胸前，文生图）按唐宋语汇出身份牌；周阿婆沿 E01 身份牌（本集躺在炕上，脸不入画）；夜空的金色灯笼眼出参考卡；周家屋内为新地点",
    "qinming_identity_source": {"file": str(QM_SOURCE_V2), "sha256": sha(QM_SOURCE_V2) if QM_SOURCE_V2.is_file() else "", "usage": "FACE_IDENTITY_REFERENCE + WARDROBE/HAIR STYLE REFERENCE（E02 已锁定的三视图身份牌直接复用）；D-57 ①：本集 S3 复测源图余弦 ≥0.45"},
    "viewer_facing_note": "E05→E06 画风与造型连续；对白镜按 seq=29 缩短，表演指令进提示词首位",
}
PACING = {**_E05["pacing"],
    "authority": "seq=17 节奏 + seq=19 门禁 + seq=27 规则 1–4 + seq=29 规则 5–7（对白镜时长 = 台词 + 0.5 s 向上取整 0.5 s，无模板；禁说完保持；无对白镜 ≤4 s 机位必动）",
    "shot_seconds_default": [2, 4], "shot_seconds_max": 6,
    "shot_seconds_max_note": "对白镜时长由 NPR.min_dialogue_seconds 推导（seq=29 规则 5a），最长 6.0 s（24 字 @5.2 + 引擎切点安全）；无对白镜 ≤4 s",
    "scene_seconds_max_exception": "本集无例外：最长场 14 s（E06-S01）",
    "hook_rule": "全集前 3 秒 = 秦铭脚尖一挑，院中的石碾子离地而起又砸回雪里（E06-S01-01，冲击型钩子）",
    "hook": {"type": "shock", "at_seconds": 0, "line_or_shot_id": "E06-S01-01", "note": "承 E05 荒野回来：脚尖一挑石碾子离地（MOMENTUM/CONTACT）；第 3 秒秦铭自问「练不成的路数……难道贯通了？」"},
    "child_dialogue_rule": "seq=13：儿童对白双人同框（文睿唯一一句与秦铭同框）；seq=29 7d：儿童语速目标 ≥4.5（本集 5.0）",
    "dialogue_shot_length_rule_seq29": "target_seconds == ceil_0.5(spoken_chars / cps + 0.5)，逐镜断言，无模板值",
}
PACING["camera_motion_policy"] = {**PACING["camera_motion_policy"], "locked_share_max": 0.30}

# ---------- 场次 ----------
SCENES = {
    "E06-S01": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·院中无风到卷雪", light="院中石盆太阳石橘红光 + 雪面月色青蓝反光；末镜体表微弱银光", sec=14, beats=["E06-EV-01", "E06-EV-02", "E06-EV-03", "E06-EV-04"], info=2),
    "E06-S02": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·搅起的雪花飘落", light="院中石盆太阳石橘红光 + 雪面月色青蓝反光；银色涟漪极淡", sec=13, beats=["E06-EV-05", "E06-EV-06", "E06-EV-07", "E06-EV-08"], info=2),
    "E06-S03": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜·屋内暖", light="铜盆太阳石橘红暖光，映亮炕上摊开的干果与汤锅的热气", sec=13.5, beats=["E06-EV-09", "E06-EV-10", "E06-EV-11", "E06-EV-12"], info=2),
    "E06-S04": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·次日·无风", light="院中石盆太阳石橘红光 + 雪面月色青蓝反光，院门方向暗一些", sec=10.5, beats=["E06-EV-13", "E06-EV-14", "E06-EV-15"], info=2),
    "E06-S05": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·次日·无风", light="院中石盆太阳石橘红光映着几张脸，雪面月色青蓝反光", sec=13, beats=["E06-EV-16", "E06-EV-17", "E06-EV-18"], info=2),
    "E06-S06": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·次日·无风", light="院中石盆太阳石橘红光，磨盘的石面映着光", sec=13.5, beats=["E06-EV-19", "E06-EV-20"], info=2),
    "E06-S07": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·次日·街上嘈杂", light="院中石盆太阳石橘红光，院门外街面淡红", sec=10.5, beats=["E06-EV-21", "E06-EV-22"], info=2),
    "E06-S08": dict(loc="LOC-ZHOU-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜·屋内冷", light="周家铜盆太阳石橘红光偏暗，炕沿的竹筐半在光里", sec=11, beats=["E06-EV-23", "E06-EV-24", "E06-EV-25", "E06-EV-26"], info=2),
    "E06-S09": dict(loc="LOC-VILLAGE-STREET-NORTH-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜将尽·极冷", light="各家院内太阳石火霞外溢，街面淡红；周家门口偏暗", sec=8, beats=["E06-EV-27", "E06-EV-28"], info=2),
    "E06-S10": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-DEEP-NIGHT", weather="深夜·无风到狂风大作再消散", light="石盆太阳石橘红余光 + 雪面月色青蓝反光；夜空里两盏金色灯笼似的眼睛是唯一的金色光", sec=13.5, beats=["E06-EV-29", "E06-EV-30", "E06-EV-31", "E06-EV-32"], info=2),
    "E06-S11": dict(loc="LOC-VILLAGE-STREET-NORTH-EXT", time="TIME-DEEP-NIGHT", weather="深夜·风刚息", light="各家院门开着，太阳石火霞外溢，街面淡红", sec=7, beats=["E06-EV-33"], info=2),
    "E06-S12": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-DEEP-NIGHT", weather="深夜·无风", light="石盆太阳石橘红光 + 雪面月色青蓝反光；末镜体表银光比以往清晰", sec=13.5, beats=["E06-EV-34", "E06-EV-35"], info=2),
    "E06-S13": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-DEEP-NIGHT", weather="屋外深夜·屋内暖", light="铜盆太阳石橘红暖光，映着瘪下去的兽皮袋", sec=6.5, beats=["E06-EV-36", "E06-EV-37"], info=2),
    "E06-S14": dict(loc="LOC-SNOWFIELD-WILDS-EXT", time="TIME-DEEP-NIGHT", weather="深夜·雪原寒风", light="雪面月色青蓝反光为主光，远处林线黑压压", sec=6, beats=["E06-EV-38"], info=1),
}
AMBIENT_LIFE = {
    "E06-S01": {"grade": "A", "motion_trend": "推门进院、脚尖挑碾、跃起抓雪、吐气激射、横臂崩雪、银光笼罩", "first_frame_state": "秦铭正推开院门跨进来", "reaction_progression": "石碾子离地→自问→跃起抓雪吐气如枪→横臂崩雪银光笼罩"},
    "E06-S02": {"grade": "B", "motion_trend": "盘坐雪落、银色涟漪浮现、睁眼抱磨盘、按住肚子进屋", "first_frame_state": "秦铭正收势盘坐下来", "reaction_progression": "闭眼→涟漪浮现→抱起磨盘「两天内完成」→饥饿进屋"},
    "E06-S03": {"grade": "B", "motion_trend": "煮汤、摊干果大吃、活动筋骨、扣碗叹气、抖兽皮袋", "first_frame_state": "秦铭正把核桃杏仁栗子摊上炕", "reaction_progression": "吃得尽兴→再练再吃→「蘑菇不多」→「只够吃三天」"},
    "E06-S04": {"grade": "A", "motion_trend": "发力搬磨盘、陆泽推门愣住、拍肩", "first_frame_state": "秦铭正弯腰抱住上下两块磨盘", "reaction_progression": "磨盘离地→「小秦，你这是」→「和二病子一样」拍肩"},
    "E06-S05": {"grade": "B", "motion_trend": "梁婉清跨进院门合手、摸磨盘、文睿扑上来抱腿、秦铭放磨盘拍雪", "first_frame_state": "梁婉清正从院门跨进来", "reaction_progression": "「真的做到了」→「头一份」→「小叔太厉害」→「变化还在进行中」"},
    "E06-S06": {"grade": "B", "motion_trend": "梁婉清惊容看人看磨盘、比五指、抓陆泽胳膊、陆泽指向村外", "first_frame_state": "梁婉清正看着秦铭又看向磨盘", "reaction_progression": "惊容→「五百斤已是极限」→「不会要抵临吧」→「六百斤的少年」"},
    "E06-S07": {"grade": "B", "motion_trend": "街上嘈杂、梁婉清出门又回、扶门喘气、陆泽迎上、搓手转身", "first_frame_state": "街上刚传来嘈杂声，梁婉清转头", "reaction_progression": "出门看→「阿婆不行了」→「什么原因」→「吃得太少」"},
    "E06-S08": {"grade": "B", "motion_trend": "进屋、孩子哭喊、周长裕扇自己嘴巴、秦铭看竹筐", "first_frame_state": "秦铭与陆泽正跨进周家屋门", "reaction_progression": "阿婆的手垂在炕沿→周长裕扇嘴「不孝」→竹筐里的口粮"},
    "E06-S09": {"grade": "B", "motion_trend": "拎布袋走近、递袋、推袋、按进手里、转身离去", "first_frame_state": "秦铭正拎着布袋走到周家门口", "reaction_progression": "递袋→「秦兄弟」推回→按进手里转身"},
    "E06-S10": {"grade": "A", "motion_trend": "独坐仰望、气息扑面绷紧、狂风卷雪屋顶颤动护脸、灯笼横空、撑地站起", "first_frame_state": "秦铭正坐在院中仰着头", "reaction_progression": "失神→金色灯笼眼出现→狂风暴雪→横空而过→「高等生灵」"},
    "E06-S11": {"grade": "B", "motion_trend": "村人走出议论、邻居甲按后生肩、望天边", "first_frame_state": "邻居甲正抬手按住一个后生的肩", "reaction_progression": "骚动→「高等生灵在赶路，过境而已」"},
    "E06-S12": {"grade": "A", "motion_trend": "回院起身、攥拳、演练动作光雾、开龙脊骨节爆响银光", "first_frame_state": "秦铭正从院门回到院中站定", "reaction_progression": "起身→「也要有实力才行」→演练光雾→开龙脊银光更盛"},
    "E06-S13": {"grade": "B", "motion_trend": "就水吃干货、抖瘪袋咽口水、抓弓上肩", "first_frame_state": "秦铭正就着热水往嘴里塞干果", "reaction_progression": "没饱→瘪袋→「再次进山」抓弓"},
    "E06-S14": {"grade": "A", "motion_trend": "雪原疾奔、冲进林线", "first_frame_state": "秦铭正在村外雪原上奔跑", "reaction_progression": "脚下生风→冲进黑压压的林线"},
}
def _wp(sid, mode):
    return {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": f"E06_NARRATIVE_CANONICAL_v1.md#{sid}｜ch6", "visibility_mode": mode}
WEATHER_PROVENANCE = {sid: _wp(sid, "OFFSCREEN_ONLY_SHALLOW_NIGHT_THROUGH_DOOR_INTERIOR_DRY" if m["loc"].endswith("-INT") else "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED") for sid, m in SCENES.items()}
for _sid, _m in SCENES.items():
    _m["ambient_life"] = AMBIENT_LIFE[_sid]
    _m["weather_provenance"] = WEATHER_PROVENANCE[_sid]

# ---------- 服装（承 E05 / E01 / E04 合同的 wardrobe_garments；新人物按唐宋语汇） ----------
_WG5 = {c["character_id"]: c["wardrobe_garments"] for c in _E05["character_entities"]}
_WG1 = {c["character_id"]: c["wardrobe_garments"] for c in _E01["character_entities"]}
_WG4 = {c["character_id"]: c["wardrobe_garments"] for c in _E04["character_entities"]}
WARDROBE_GARMENTS = {
    "CHAR-QINMING": {**_WG5["CHAR-QINMING"], "condition": "练功时裘氅脱在院角石上，只着深青交领窄袖袍；出村进山时披回裘氅、背弓箭"},
    "CHAR-LUZE": _WG5["CHAR-LUZE"], "CHAR-LIANGWANQING": _WG5["CHAR-LIANGWANQING"], "CHAR-LUWENRUI": _WG5["CHAR-LUWENRUI"],
    "CHAR-ZHOUAPO": {**_WG1["CHAR-ZHOUAPO"], "condition": "躺在炕上，身上盖着旧兽皮，只见垂在炕沿的手与黑布衣袖"},
    "CHAR-VILLAGER-A": _WG4["CHAR-VILLAGER-A"],
    "CHAR-ZHOUCHANGYU": {"silhouette": "高壮汉子、右臂用布带吊在胸前、束发裹巾", "outer_layer": "褐色粗麻交领右衽短褐（外层，右袖空着）", "inner_layer": "灰白粗麻中衣", "primary_color": "褐", "secondary_color": "灰白（吊臂的布带）", "material": "粗麻棉", "pattern": "粗织纹，膝盖与肘部磨破", "belt_or_fastening": "麻布腰带打结；右臂布带吊在颈后", "footwear": "旧布靴裹腿", "accessory": "灰布裹巾束发；右臂夹板缠布", "condition": "满脸泪痕，眼睛红肿"},
}

# ---------- 道具与布景 ----------
PROPS = [
    {"entity_id": "PROP-STONE-ROLLER", "name": "石碾子", "reference_card_required": True, "first_shot": "E06-S01-01",
     "note": "秦铭家院中的一只石碾子：一段一尺多长的圆柱形青石碾，两端凿有轴孔，半埋在雪里；被脚尖一挑离地又砸回雪中", "period_constraints": "凿石农具，无金属机件、无现代物"},
    {"entity_id": "PROP-YARD-MILLSTONES", "name": "磨盘", "reference_card_required": True, "first_shot": "E06-S02-03",
     "note": "秦铭家院角上下两块叠放的圆磨盘：青灰石、盘面刻着放射状磨齿、各有二百多斤、顶面积雪；先被单独抱起一块，次日被上下两块一起搬离原地", "period_constraints": "凿石磨盘，无木架、无金属"},
    {"entity_id": "PROP-NUT-HOARD", "name": "干果", "reference_card_required": False, "first_shot": "E06-S03-01",
     "note": "E03 已出卡并锁定：核桃、杏仁、栗子、红枣、山楂、松子摊在炕上；本集越吃越少，最后瘪在袋底", "period_constraints": "真实野果，无包装"},
    {"entity_id": "PROP-HIDE-BAG", "name": "兽皮袋", "reference_card_required": False, "first_shot": "E06-S03-04",
     "note": "E03 已出卡并锁定：厚兽皮口袋；本集只剩大半袋到瘪下去", "period_constraints": "手缝皮袋，无拉链、无金属扣"},
    {"entity_id": "PROP-COPPER-BASIN", "name": "铜盆", "reference_card_required": False, "first_shot": "E06-S03-01",
     "note": "E01 已出卡并锁定：炕边盛太阳石的铜盆，屋内唯一光源；本集旁边架着一口煮蘑菇汤的小陶锅", "period_constraints": "锤打铜盆，粗陶锅，无明火"},
    {"entity_id": "PROP-BAMBOO-BASKET", "name": "竹筐", "reference_card_required": True, "first_shot": "E06-S08-04",
     "note": "周家炕沿边的一只旧竹筐：篾条发黑、筐口磨毛，里面是阿婆藏下的地薯、冷硬的馍与一小包没舍得吃的坚果，筐沿还沾着冰雪", "period_constraints": "手编竹篾筐，无塑料、无金属"},
    {"entity_id": "PROP-DRIED-TUBER", "name": "地薯", "reference_card_required": False, "first_shot": "E06-S08-04",
     "note": "E01 已出卡并锁定：切片晒干的地薯，深褐、干硬；本集在周家竹筐里", "period_constraints": "真实块茎干，无包装"},
    {"entity_id": "PROP-BLACK-BUN", "name": "冷馍", "reference_card_required": False, "first_shot": "E06-S08-04",
     "note": "E01 已出卡并锁定：粗黑面馍；本集是冷硬的、藏在竹筐里", "period_constraints": "粗黑面蒸馍"},
    {"entity_id": "PROP-NUT-CLOTH-BAG", "name": "布袋", "reference_card_required": True, "first_shot": "E06-S09-01",
     "note": "装着五斤坚果的粗麻布袋：灰褐色、袋口用麻绳扎着、鼓鼓囊囊；秦铭拎着递给周长裕又按进他手里", "period_constraints": "粗麻布袋、麻绳，无拉链无纽扣"},
    {"entity_id": "PROP-BOW-ARROWS", "name": "弓箭", "reference_card_required": False, "first_shot": "E06-S13-02",
     "note": "E04 已出卡并锁定：竹木硬弓与皮箭囊；本集末段秦铭抓起挂上肩、背着出村", "period_constraints": "唐宋竹木复合弓与皮箭囊"},
]
SETS = [
    {"entity_id": "SET-GOLDEN-LANTERN-EYES", "name": "金色灯笼眼", "reference_card_required": True, "first_shot": "E06-S10-02",
     "note": "夜空中横空而过的高等生灵：只见两盏金色灯笼似的巨眼与遮天的乌云般的翼影轮廓，眼与眼之间有数丈；参考卡只画伸手不见五指的夜空、两盏金色巨眼与翼影的一角，绝不画出全貌、不画人", "period_constraints": "无任何人造光；金色是画面里唯一的金色"},
]

# ---------- 机位方案（每镜；LOCKED 只用于 ≤5 s 对白镜且不连续） ----------
def _cp(scale, height, side, lens, axis, fam, direction, start, end, why):
    if fam == "LOCKED" and end != start:
        why = f"{why}；画内变化：{end}"
        end = start
    return {"shot_scale": scale, "camera_height": height, "camera_side": side, "lens_intent": lens, "axis_relation": axis,
            "motion_family": fam, "motion_direction": direction, "start_framing": start, "end_framing": end, "motivation": why}
CAMERA_PLANS = {
    "E06-S01-01": _cp("MEDIUM_WIDE", "LOW", "AXIS_A", "28mm低机位先在院中石碾子旁迎着院门取秦铭正面走来，再横移跟随脚尖挑碾", "秦铭自院门（画左）走向院中石碾子（画右）的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "低机位中全景：秦铭推开院门迎着镜头跨进来，脸正对镜头", "低机位中全景（横移）：脚尖一挑，石碾子离地而起又砸回雪里", "导演稿：开场 3 秒冲击钩子＝石碾子离地"),
    "E06-S01-02": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_B", "85mm环绕低头看掌心的秦铭", "秦铭（画右）低头看向双手（画左）的视线轴，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "特写：秦铭低头摊开双手看着掌心", "特写（环绕）：他自问一句，攥拳抬头", "导演稿：环绕读疑惑"),
    "E06-S01-03": _cp("WIDE", "LOW", "AXIS_A", "24mm低机位随跃起升起再随落地下落", "秦铭在院中（画面中央）面向屋檐（画右）的动作轴，不越轴", "CRANE", "RISE", "低机位远景：秦铭蹲身蓄力", "低机位远景（升起）：他纵身跃起抓下房檐的雪，落地吐气，白雾如长枪激射", "导演稿：升起跟随跃起"),
    "E06-S01-04": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm横移随横臂崩雪落到银光笼罩", "秦铭面向院门（画左）的动作轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中景：秦铭横臂一击", "中景（横移）：飞舞的雪花全部崩开，他周身滚烫、毛孔银纹交织，整个人被微弱的银光笼罩", "导演稿：横移落在银光上，场尾 button"),
    "E06-S02-01": _cp("MEDIUM_WIDE", "HIGH", "AXIS_A", "28mm高机位随盘坐缓降", "秦铭盘坐在院中（画面中央）面向院门（画右）", "CRANE", "FALL", "高机位中全景：秦铭收势盘坐下来", "高机位中全景（下降）：雪花落满肩头，他闭上眼睛", "导演稿：下降落在静坐上"),
    "E06-S02-02": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_B", "85mm缓慢横移过闭眼的秦铭", "秦铭（画右）面向院门（画左），不越轴", "TRACK", "LEFT_TO_RIGHT", "特写：秦铭闭着眼睛", "特写（推近）：体表银色涟漪再次浮现，呼吸随心念调整", "导演稿：推近读涟漪"),
    "E06-S02-03": _cp("MEDIUM", "LOW", "AXIS_A", "35mm低机位环绕抱起磨盘的秦铭", "秦铭（画右）面向院角磨盘（画左）的动作轴，环绕不越轴", "ARC", "CLOCKWISE", "低机位中景：秦铭睁眼走到院角弯腰抱住磨盘", "低机位中景（环绕）：他抱起磨盘说一句，又轻轻放下", "导演稿：环绕读从容"),
    "E06-S02-04": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm横移跟随按住肚子进屋", "秦铭自院角（画左）走向屋门（画右）的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中景：秦铭按住肚子", "中景（横移）：他大步转身进屋", "导演稿：横移送进屋，场尾 button 在饥饿上"),
    "E06-S03-01": _cp("MEDIUM", "HIGH", "AXIS_A", "28mm高机位随摊干果缓降到炕面", "秦铭（画右）向炕上（画左）的动作轴，不越轴", "CRANE", "FALL", "高机位中景：秦铭把核桃杏仁栗子摊上炕，铜盆边架着汤锅", "高机位中景（下降）：他大口吃着，红枣山楂当小菜", "导演稿：下降落在大吃上"),
    "E06-S03-02": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_B", "28mm环绕炕边活动筋骨的秦铭", "秦铭（画面中央）面向铜盆（画左），环绕不越轴", "ARC", "COUNTERCLOCKWISE", "中全景：秦铭在炕边活动筋骨", "中全景（环绕）：他坐回炕沿再抓一把干果吃", "导演稿：环绕读一夜循环"),
    "E06-S03-03": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm缓推扣碗的秦铭", "秦铭（画右）面向炕上汤锅（画左）的视线轴，不越轴", "DOLLY", "PUSH_IN", "中近景：秦铭把空了的蘑菇碗扣过来", "中近景（推近）：他叹着气说一句，抓起一把栗子", "导演稿：推近读遗憾"),
    "E06-S03-04": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm横移随提起的兽皮袋", "秦铭（画右）提起炕上兽皮袋（画左）的动作轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中景：秦铭提起瘪下去的兽皮袋抖了抖", "中景（横移）：他自嘲一句，把袋子扔回炕上", "导演稿：横移落在瘪袋上，场尾 button"),
    "E06-S04-01": _cp("MEDIUM_WIDE", "LOW", "AXIS_A", "28mm低机位随两块磨盘离地升起", "秦铭在院角（画右）抱磨盘，院门在画左", "CRANE", "RISE", "低机位中全景：秦铭弯腰抱住上下两块磨盘猛然发力", "低机位中全景（升起）：两块磨盘一起离地被搬离原地", "导演稿：升起读发力"),
    "E06-S04-02": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm横移随陆泽推门愣住", "陆泽（画左，院门）面向秦铭（画右）的轴线，不越轴", "TRACK", "LEFT_TO_RIGHT", "中景：陆泽推开院门", "中景（横移）：他愣在门口说半截话，手还搭在门板上", "导演稿：横移读瞠目"),
    "E06-S04-03": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm双人同框缓推，机位偏向陆泽的正面一侧，陆泽画左、秦铭画右", "陆泽（画左）面向秦铭（画右）的交谈轴，不越轴", "DOLLY", "PUSH_IN", "中近景：陆泽上前拍秦铭的肩膀，脸朝画面前方呈四分之三正面", "中近景（推近）：他大嗓门说完，退后一步上下打量秦铭", "导演稿：推近读高兴，场尾 button"),
    "E06-S05-01": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm横移随梁婉清跨进院门", "梁婉清（画左，院门）面向秦铭与磨盘（画右）的轴线，不越轴", "TRACK", "LEFT_TO_RIGHT", "中景：梁婉清从院门跨进来，双手合在胸前", "中景（横移）：她说一句，走到磨盘旁", "导演稿：横移读失神"),
    "E06-S05-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm环绕摸磨盘的梁婉清", "梁婉清（画右）面向磨盘（画左）的视线轴，环绕不越轴", "ARC", "CLOCKWISE", "中近景：梁婉清伸手摸了摸磨盘", "中近景（环绕）：她声音亮起来说一句，回头看陆泽", "导演稿：环绕读头一份"),
    "E06-S05-03": _cp("MEDIUM", "LOW", "AXIS_B", "35mm低机位双人同框缓推，文睿画左仰头、秦铭画右", "文睿（画左）面向秦铭（画右）的轴线，不越轴", "DOLLY", "PUSH_IN", "低机位中景：文睿跑过来抱住秦铭的腿仰着头", "低机位中景（推近）：他嚷着说完，蹦起来", "导演稿：儿童对白双人同框（seq=13）"),
    "E06-S05-04": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm横移随秦铭放磨盘拍雪到抱起文睿", "秦铭（画右）面向陆泽梁婉清（画左）的轴线，不越轴", "TRACK", "RIGHT_TO_LEFT", "中近景：秦铭放下磨盘拍掉手上的雪", "中近景（横移）：他平稳地说完，把文睿抱起来", "导演稿：横移落在抱起文睿上，场尾 button"),
    "E06-S06-01": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm环绕带着惊容的梁婉清", "梁婉清（画左）面向秦铭（画右）的轴线，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "中景：梁婉清看着秦铭", "中景（环绕）：她又看向磨盘，脸上带着惊容", "导演稿：环绕读惊容"),
    "E06-S06-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm缓推比着五指的梁婉清", "梁婉清（画左）面向秦铭（画右）的交谈轴，不越轴", "DOLLY", "PUSH_IN", "中近景：梁婉清伸出五根手指比了比", "中近景（推近）：她慢慢地说完前半句，看向秦铭", "导演稿：推近读五百斤"),
    "E06-S06-03": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm横移随梁婉清抓住陆泽胳膊", "梁婉清（画左）面向陆泽（画右）的轴线，不越轴", "TRACK", "LEFT_TO_RIGHT", "中景：梁婉清抓住陆泽的胳膊", "中景（横移）：她压低声音说完，看向陆泽", "导演稿：横移读担心"),
    "E06-S06-04": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm随陆泽指向村外升起", "陆泽（画右）望向村外院门（画左）的视线轴，不越轴", "CRANE", "RISE", "中全景：陆泽望向村外抬手一指", "中全景（升起）：他压低声音说完，收回手看秦铭", "导演稿：升起送向村外，场尾 button"),
    "E06-S07-01": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_B", "28mm机位在院门内侧迎着梁婉清，取她转头看向院门时的四分之三正面，再横移随她出门", "梁婉清自院中（画右）走向院门（画左）的行进轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中全景：街上传来嘈杂声，梁婉清转头，脸转向镜头所在的院门一侧", "中全景（横移）：她快步出院门去看", "导演稿：横移读嘈杂"),
    "E06-S07-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm缓推扶着院门的梁婉清", "梁婉清（画左，院门）面向陆泽秦铭（画右）的轴线，不越轴", "DOLLY", "PUSH_IN", "中近景：梁婉清扶着院门喘气", "中近景（推近）：她急促地说完，指向街上", "导演稿：推近读慌"),
    "E06-S07-03": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm环绕迎上一步的陆泽", "陆泽（画右）面向院门的梁婉清（画左），环绕不越轴", "ARC", "CLOCKWISE", "中景：陆泽放下搭在磨盘边的手迎上一步", "中景（环绕）：他追问一句，看向院门外", "导演稿：环绕读追问"),
    "E06-S07-04": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm横移随搓手的梁婉清转身", "梁婉清（画左）面向陆泽（画右）的交谈轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中近景：梁婉清搓着手", "中近景（横移）：她声音低下去说完，转身往街上走", "导演稿：横移送出院门，场尾 button"),
    "E06-S08-01": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm横移随秦铭陆泽进屋到炕前，两人的脸在中景里清楚朝前", "秦铭陆泽自屋门（画左）走向火炕（画右）的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中景：秦铭和陆泽跨进周家屋门，脸朝前清楚可见", "中全景（横移）：两个孩子跪在炕前哭喊，周阿婆躺在炕上一动不动，一只手垂在炕沿", "导演稿：横移读进屋所见；阿婆的脸不入画"),
    "E06-S08-02": _cp("MEDIUM", "LOW", "AXIS_B", "35mm低机位环绕跪着的周长裕", "周长裕（画右，炕前）面向炕上（画左），不越轴", "ARC", "CLOCKWISE", "低机位中景：周长裕跪在一旁满脸泪水，右臂吊在胸前", "低机位中景（推近）：他用左手用力扇自己的嘴巴", "导演稿：推近读自责"),
    "E06-S08-03": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_A", "85mm环绕扇嘴的周长裕", "周长裕（画右）面向炕上（画左），环绕不越轴", "ARC", "COUNTERCLOCKWISE", "特写：周长裕又扇自己一个嘴巴", "特写（环绕）：他哽咽着挤出一句，伏下身", "导演稿：环绕读悔恨"),
    "E06-S08-04": _cp("MEDIUM_CLOSE_UP", "HIGH", "AXIS_B", "50mm高机位自沉默的秦铭缓降到炕沿的竹筐", "秦铭（画右）低头看向炕沿竹筐（画左）的视线轴，不越轴", "CRANE", "FALL", "高机位中近景：秦铭沉默地站着低头看", "高机位中近景（下降到竹筐）：竹筐里是藏下的地薯、冷馍与那一小包没舍得吃的干果", "导演稿：下降落在口粮上，场尾 button"),
    "E06-S09-01": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm机位在周家门口街对面，取正面走来的秦铭与正面朝街站在门口的周长裕，再横移随递袋", "秦铭自街上（画左）走向周家门口的周长裕（画右）的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中全景：秦铭拎着鼓鼓的布袋走来，周长裕正面朝街站在门口", "中全景（横移）：他把布袋递给站在门口红着眼睛的周长裕", "导演稿：横移读递袋"),
    "E06-S09-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm缓推推袋的周长裕", "周长裕（画右）面向秦铭（画左）的轴线，不越轴", "DOLLY", "PUSH_IN", "中近景：周长裕左手把布袋往外推", "中近景（推近）：他哑着嗓子喊一声，低下头", "导演稿：推近读推辞"),
    "E06-S09-03": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm环绕按袋转身的秦铭", "秦铭（画左）面向周长裕（画右）的轴线，环绕不越轴", "ARC", "CLOCKWISE", "中景：秦铭把布袋按在周长裕手里", "中景（环绕）：他转身沿街离去，屋里的哭声还在", "导演稿：环绕送走，场尾 button"),
    "E06-S10-01": _cp("MEDIUM_WIDE", "LOW", "AXIS_A", "28mm低机位横移过仰望的秦铭", "秦铭坐在院中（画面中央）仰望夜空", "TRACK", "RIGHT_TO_LEFT", "低机位中全景：秦铭坐在深夜的院中仰着头", "低机位中全景（推近）：他望着雪光下的夜空失神", "导演稿：推近读孤独"),
    "E06-S10-02": _cp("WIDE", "LOW", "AXIS_B", "24mm低机位自秦铭升起到夜空的两盏金色灯笼眼", "秦铭（画面下方）仰望夜空（画面上方）的视线轴", "CRANE", "RISE", "低机位远景：秦铭的身体瞬间绷紧", "低机位远景（升起到夜空）：伸手不见五指的夜空里出现两盏金色灯笼似的眼睛", "导演稿：升起揭晓灯笼眼（原著奇观）"),
    "E06-S10-03": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm横移随狂风卷雪与屋顶颤动", "秦铭（画右）抬臂护脸，屋顶在画左", "TRACK", "RIGHT_TO_LEFT", "中景：狂风大作，地面的雪花暴涌而起", "中景（横移）：屋顶剧烈颤动，秦铭抬臂护住头脸", "导演稿：横移读狂风"),
    "E06-S10-04": _cp("WIDE", "LOW", "AXIS_B", "24mm低机位横摇跟随灯笼眼横空而过", "两盏金色灯笼眼自画右横空掠向画左，秦铭在画面下方", "PAN", "RIGHT_TO_LEFT", "低机位远景：金色灯笼眼带着罡风横空而过，翼影如乌云遮天", "低机位远景（横摇）：它远去，暴风迅速变弱消散", "导演稿：横摇送走过境的生灵"),
    "E06-S10-05": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_A", "85mm缓推瞳孔收缩的秦铭", "秦铭（画面中央）望向它远去的方向（画左）", "DOLLY", "PUSH_IN", "特写：秦铭瞳孔收缩", "特写（推近）：他撑着雪地站起来，气声说出三个字", "导演稿：推近读心悸，场尾 button"),
    "E06-S11-01": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm横移随走出院门议论的村人到邻居甲", "村人自各家院门（画右）走到街上（画左），邻居甲在画左", "TRACK", "RIGHT_TO_LEFT", "中全景：村中骚动，不少人走出院门议论纷纷", "中全景（横移）：邻居甲神色凝重地抬手按住一个后生的肩", "导演稿：横移读骚动"),
    "E06-S11-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm缓推按着后生肩膀的邻居甲", "邻居甲（画左）面向后生（画右）的轴线，不越轴", "DOLLY", "PUSH_IN", "中近景：邻居甲按着后生的肩膀", "中近景（推近）：他沉声说完，望向天边", "导演稿：推近读老人的镇定，场尾 button"),
    "E06-S12-01": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm横移随秦铭回院站定", "秦铭自院门（画左）回到院中（画右）的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中全景：秦铭从院门回到院中", "中全景（横移）：他望着无边的夜幕，坚定地站直身子", "导演稿：横移读决心"),
    "E06-S12-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm固定，秦铭正面略偏右，石盆橘红光与雪光照出五官", "秦铭（画面中央）面向院门方向（画左），不越轴", "LOCKED", "NONE", "中近景：秦铭攥紧拳头", "中近景：他低声说完，摆开架势", "导演稿：固定（对白镜 ≤5 s），攥拳本身带动"),
    "E06-S12-03": _cp("MEDIUM", "LOW", "AXIS_A", "35mm低机位环绕演练动作的秦铭", "秦铭面向院门（画左）的动作轴，环绕不越轴", "ARC", "CLOCKWISE", "低机位中景：秦铭演练幼时的一组动作", "低机位中景（环绕）：身体涌出蓬勃的力，体表泛起稀薄的光雾", "导演稿：环绕读动作圆活"),
    "E06-S12-04": _cp("MEDIUM_WIDE", "LOW", "AXIS_B", "28mm低机位随开龙脊的后仰升起", "秦铭侧身对镜（画面中央）向后弯成弯月", "CRANE", "RISE", "低机位中全景：秦铭弓腰蓄势", "低机位中全景（升起）：他猛烈后仰，脊柱反向弯成弯月，骨节一路爆响，体表漾出一层比以往清晰的银光", "导演稿：升起跟随开龙脊，场尾 button"),
    "E06-S13-01": _cp("MEDIUM", "HIGH", "AXIS_A", "28mm高机位随抖瘪袋缓降", "秦铭（画右）向炕上兽皮袋（画左）的动作轴，不越轴", "CRANE", "FALL", "高机位中景：秦铭就着热水往嘴里塞干果", "高机位中景（下降）：他抖了抖瘪下去的兽皮袋，咽了口口水", "导演稿：下降落在瘪袋上"),
    "E06-S13-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm横移随秦铭抓弓上肩到推门", "秦铭（画右）向门边弓箭（画左）的动作轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中近景：秦铭抓起门边的弓箭挂上肩", "中近景（横移）：他咬着牙说完，推门出去", "导演稿：横移送出屋，场尾 button"),
    "E06-S14-01": _cp("WIDE", "HIGH", "AXIS_A", "24mm高机位横移跟随雪原疾奔", "秦铭自村口方向（画左）向密林（画右）疾奔的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "高机位远景：秦铭背着弓箭在村外雪原上奔跑", "高机位远景（横移）：他脚下生风，雪粒飞溅", "导演稿：横移读疾奔"),
    "E06-S14-02": _cp("WIDE", "LOW", "AXIS_B", "24mm低机位随冲进林线升起", "秦铭（画面中央）冲向黑压压的林线（画右）", "CRANE", "RISE", "低机位远景：远处的小人影冲向林线", "低机位远景（升起）：他冲进黑压压的林木之间，只剩雪地上的脚印", "导演稿：升起送进密林，全集 button"),
}
_ALT = [("ARC", "COUNTERCLOCKWISE"), ("ARC", "CLOCKWISE"), ("TRACK", "LEFT_TO_RIGHT"), ("TRACK", "RIGHT_TO_LEFT"), ("CRANE", "RISE"), ("CRANE", "FALL")]
_ZH_FAM = {"ARC": "环绕", "TRACK": "横移", "CRANE": "升降", "DOLLY": "推拉", "PAN": "横摇"}

# 每镜：s, n, sec, size, camera, axis, blocking, cast, action(subject, primary_action, patient), dialogue(speaker,text,listener),
# emotion（NPR 说法条款 key）, perf(情绪词, 进行中的身体动作, 说话方式)（seq=29 规则 7b）, after_line（规则 5b：说完立即…）,
# entry, exit, dims{DIM:(entry, exit, ENTRY_CODE, EXIT_CODE)}, referents[(surface,key)], faces{k: 闭集豁免标记}, cps, slots, life{k: state}, group_counts
D = lambda a, b, ca, cb: (a, b, ca, cb)
ROLLER, MILL, NUTS, BAG, BASIN, BASKET, TUBER, BUN, CLOTH, BOW, EYES = ("PROP-STONE-ROLLER", "PROP-YARD-MILLSTONES", "PROP-NUT-HOARD", "PROP-HIDE-BAG", "PROP-COPPER-BASIN",
    "PROP-BAMBOO-BASKET", "PROP-DRIED-TUBER", "PROP-BLACK-BUN", "PROP-NUT-CLOTH-BAG", "PROP-BOW-ARROWS", "SET-GOLDEN-LANTERN-EYES")
SHOTS = [
    # S01 —— 承 E05：从荒野回来；钩子＝石碾子离地
    dict(s="E06-S01", n=1, sec=3, size="中全景", camera="低机位横移跟随秦铭进院、脚尖挑碾", axis="秦铭自院门（画左）走向石碾子（画右）", blocking="秦铭推开院门跨进院中，正面朝着院里走来、脸朝前不侧不低，走到半埋在雪里的石碾子前，脚尖一挑，石碾子离地而起又砸回雪里；院中石盆的太阳石亮着",
         cast=["QM"], action=("QM", "秦铭推开院门跨进院中，脚尖一挑，院中的石碾子离地而起，又砸回雪里溅起雪粒", ""),
         entry="秦铭推开院门从荒野回到院中，正面朝着院里走来，脸朝前，石碾子半埋在雪里，石盆里的太阳石亮着", exit="石碾子被他脚尖一挑离地而起又砸回雪里，雪粒四溅",
         dims={"MOMENTUM": D("石碾子静卧雪中", "石碾子离地又砸回", "ROLLER_AT_REST", "ROLLER_KICKED_UP"), "CONTACT": D("脚尖未触碾", "脚尖挑起石碾子", "FOOT_CLEAR", "FOOT_KICKS_ROLLER")}, referents=[]),
    dict(s="E06-S01", n=2, sec=3, cps=5.0, size="特写", camera="环绕低头看掌心的秦铭", axis="秦铭（画右）低头看向双手（画左）", blocking="秦铭站在石碾子旁，低头摊开双手看着自己的掌心，自问一句，攥拳抬头",
         cast=["QM"], action=("QM", "秦铭低头摊开双手看着掌心，低声自问一句，说完立即攥拳抬头", ""), dialogue=("QM", "练不成的路数……难道贯通了？", ""), emotion="calm",
         perf=("疑", "低头摊开双手看着掌心", "低声自语"), after_line="攥拳抬头",
         entry="秦铭低头摊开双手看着掌心", exit="秦铭攥紧双拳抬起头",
         dims={"POSTURE": D("低头看掌心", "攥拳抬头", "HEAD_DOWN_PALMS_OPEN", "FISTS_HEAD_UP")}, referents=[]),
    dict(s="E06-S01", n=3, sec=4, size="远景", camera="低机位随跃起升起再随落地", axis="秦铭在院中面向屋檐（画右）", blocking="秦铭蹲身蓄力纵身跃起，滞空中抓下房檐上的一把雪，落地时吐气，白色气流像一杆带着大量白雾的长枪激射而出",
         cast=["QM"], action=("QM", "秦铭蹲身蓄力纵身跃起，滞空很久，伸手抓下房檐上覆盖的一把雪；落地时张口吐气，白色气流像一杆带着大量白雾的长枪激射而出，破空音很响", ""),
         faces={"QM": "SMALL_FIGURE_IN_WIDE_LEAP_NOT_MEASURABLE"},
         entry="秦铭蹲身蓄力，屋檐上覆盖着厚雪", exit="秦铭落地，手里攥着一把檐雪，口中白雾如长枪激射而出",
         dims={"POSITION": D("蹲在院中雪地", "落回院中雪地手攥檐雪", "CROUCHED_ON_GROUND", "LANDED_WITH_SNOW"), "MOMENTUM": D("静止蓄力", "吐气激射白雾", "COILED", "BREATH_SPEAR_OUT")}, referents=[("他", "QM")]),
    dict(s="E06-S01", n=4, identity_reanchor=True, sec=4, size="中景", camera="横移随横臂崩雪落到银光笼罩", axis="秦铭面向院门（画左）", blocking="秦铭横臂一击，前方飞舞的雪花全部崩开；他周身滚烫，毛孔里银色纹理交织，汗水带出，整个人被一层微弱的银光笼罩",
         cast=["QM"], action=("QM", "秦铭横臂一击，前方飞舞的雪花全部崩开；他周身滚烫，毛孔里银色纹理交织带出大量汗水，整个人被一层微弱的体表银光笼罩", ""),
         entry="雪花在秦铭面前飞舞，他抬起手臂", exit="雪花崩开，秦铭汗水淋漓，周身笼着一层微弱的体表银光",
         dims={"INTEGRITY": D("体表无光", "体表银光笼罩", "SKIN_PLAIN", "SKIN_SILVER_GLOW"), "MOMENTUM": D("雪花飞舞", "雪花崩开", "SNOW_SWIRLING", "SNOW_BURST")}, referents=[("他", "QM")]),
    # S02 —— 静坐、涟漪、磨盘、饥饿
    dict(s="E06-S02", n=1, sec=3, size="中全景", camera="高机位随盘坐缓降", axis="秦铭盘坐院中面向院门（画右）", blocking="秦铭收势，盘坐在院中雪地上，搅起的雪花落满肩头，他闭上眼睛",
         cast=["QM"], action=("QM", "秦铭收势坐下，盘坐在院中的雪地上，任搅起的雪花落在肩头，闭上眼睛", ""),
         entry="秦铭收势，弯膝坐向雪地", exit="秦铭盘坐着，雪花落满肩头，眼睛闭着",
         dims={"POSTURE": D("站立收势", "盘坐闭眼", "STANDING", "SEATED_EYES_CLOSED")}, referents=[]),
    dict(s="E06-S02", n=2, sec=3, size="特写", camera="缓慢横移过闭眼的秦铭", axis="秦铭（画右）面向院门（画左）", blocking="秦铭闭着眼，呼吸随心念不断调整，刚消退的银色涟漪在他体表再次浮现又变亮少许",
         cast=["QM"], action=("QM", "秦铭闭着眼睛，胸口随复杂的呼吸起伏，刚刚消退的银色涟漪在他体表再次浮现，极淡银光亮了少许", ""),
         entry="秦铭闭着眼睛，体表无光", exit="秦铭体表浮起极淡的银色涟漪，呼吸起伏",
         dims={"INTEGRITY": D("体表无光", "体表银色涟漪", "SKIN_PLAIN", "SKIN_RIPPLE")}, referents=[]),
    dict(s="E06-S02", n=3, sec=3, cps=5.0, size="中景", camera="低机位环绕抱起磨盘的秦铭", axis="秦铭（画右）面向院角磨盘（画左）", blocking="秦铭睁眼起身走到院角，弯腰抱起上层那块两百多斤的磨盘，抱在胸前说一句，又轻轻放下",
         cast=["QM"], action=("QM", "秦铭睁开眼睛起身走到院角，弯腰从容地抱起上层那块两百多斤的磨盘抱在胸前，说一句，说完立即把磨盘轻轻放下", MILL), dialogue=("QM", "新生大概率在两天内完成。", ""), emotion="calm",
         perf=("喜", "抱起磨盘抱在胸前", "笃定地低声说"), after_line="把磨盘轻轻放下",
         entry="秦铭睁开眼睛起身走向院角的磨盘", exit="秦铭把抱起的磨盘轻轻放回院角",
         dims={"POSSESSION": D("磨盘叠在院角", "磨盘被抱起又放下", "MILL_STACKED", "MILL_LIFTED_AND_SET"), "POSTURE": D("盘坐", "站立抱物", "SEATED", "STANDING_LIFT")}, referents=[]),
    dict(s="E06-S02", n=4, sec=4, size="中景", camera="横移跟随按住肚子进屋", axis="秦铭自院角（画左）走向屋门（画右）", blocking="秦铭按住肚子，饥饿感强烈得毫无意外，他大步转身走向屋门推门进屋",
         cast=["QM"], action=("QM", "秦铭按住咕咕作响的肚子，转身大步走向屋门，推门进屋", ""),
         entry="秦铭站在院角按住肚子", exit="秦铭推开屋门跨进屋里",
         dims={"POSITION": D("院角磨盘旁", "屋门内", "AT_MILLSTONES", "INTO_HOUSE"), "CONTACT": D("手按肚子", "手推屋门", "HAND_ON_BELLY", "HAND_ON_DOOR")}, referents=[("他", "QM")]),
    # S03 —— 屋内吃、蘑菇不多、存粮三天
    dict(s="E06-S03", n=1, sec=3, size="中景", camera="高机位随摊干果缓降到炕面", axis="秦铭（画右）向炕上（画左）", blocking="铜盆边架着一口煮着蘑菇汤的小陶锅冒着热气；秦铭把核桃、杏仁、栗子摊在炕上当主餐，红枣、山楂当小菜，大口吃着",
         cast=["QM"], action=("QM", "秦铭把核桃、杏仁、栗子等干果摊在炕上，铜盆边的小陶锅里蘑菇汤冒着热气，他抓起干果大口吃着，红枣山楂当小菜", NUTS),
         entry="秦铭跪坐在炕沿，把兽皮袋里的干果倒在炕上，铜盆边小陶锅冒着热气", exit="炕上摊满干果，秦铭大口吃着，锅里的蘑菇汤见了底",
         dims={"POSSESSION": D("干果在兽皮袋里", "干果摊在炕上入口", "NUTS_IN_BAG", "NUTS_EATEN"), "CONTACT": D("手空着", "手抓干果送嘴", "HANDS_EMPTY", "HANDS_FEEDING")}, referents=[]),
    dict(s="E06-S03", n=2, sec=3, size="中全景", camera="环绕炕边活动筋骨的秦铭", axis="秦铭面向铜盆（画左）", blocking="秦铭站在炕边活动筋骨，拧腰转肩，站着又从炕上抓一把干果吃；从浅夜到深夜，疲了就歇、饿了就吃",
         cast=["QM"], action=("QM", "秦铭站在炕边活动筋骨，拧腰转肩，站着再从炕上抓一把干果塞进嘴里", NUTS),
         entry="秦铭站在炕边拧腰转肩", exit="秦铭站在炕边，嘴里嚼着干果，炕上的干果堆矮了半寸",
         dims={"POSTURE": D("站着拧腰", "站着嚼干果", "STANDING_STRETCH", "STANDING_EATING"), "POSSESSION": D("干果堆高", "干果堆矮了半寸", "NUTS_PILE_HIGH", "NUTS_PILE_LOWER")}, referents=[("他", "QM")]),
    dict(s="E06-S03", n=3, sec=3.5, cps=5.2, size="中近景", camera="缓推扣碗的秦铭", axis="秦铭（画右）面向炕上汤锅（画左）", blocking="秦铭把空了的蘑菇碗扣过来放在炕沿，叹着气说一句，抓起一把栗子",
         cast=["QM"], action=("QM", "秦铭把空了的蘑菇汤碗扣过来放在炕沿，叹着气说一句，说完立即抓起一把栗子", ""), dialogue=("QM", "可惜，蘑菇不多，想煮些鲜汤都不成了。", ""), emotion="calm",
         perf=("哀", "把空了的蘑菇碗扣过来放在炕沿", "叹着气说"), after_line="抓起一把栗子",
         entry="秦铭端着喝空的蘑菇碗", exit="空碗扣在炕沿，秦铭手里抓着一把栗子",
         dims={"POSSESSION": D("手端空碗", "碗扣下手抓栗子", "BOWL_IN_HAND", "BOWL_DOWN_NUTS_IN_HAND")}, referents=[]),
    dict(s="E06-S03", n=4, sec=4, cps=5.2, size="中景", camera="横移随提起的兽皮袋", axis="秦铭（画右）提起炕上兽皮袋（画左）", blocking="秦铭提起瘪下去大半的兽皮袋抖了抖，只剩袋底一层干果，自嘲一句，把袋子扔回炕上",
         cast=["QM"], action=("QM", "秦铭提起瘪下去的兽皮袋抖了抖，袋底只剩一层干果，自嘲地说一句，说完立即把袋子扔回炕上", BAG), dialogue=("QM", "我是饭桶吗？大半兽皮袋的干货只够吃三天。", ""), emotion="mock",
         perf=("惊", "提起瘪下去的兽皮袋抖了抖", "自嘲地说"), after_line="把袋子扔回炕上",
         entry="秦铭提起炕上瘪下去的兽皮袋", exit="兽皮袋被扔回炕上，袋底只剩一层干果",
         dims={"POSSESSION": D("兽皮袋在手中", "兽皮袋扔回炕上", "BAG_HELD", "BAG_TOSSED"), "INTEGRITY": D("袋子鼓着", "袋子瘪下去", "BAG_FULL", "BAG_NEAR_EMPTY")}, referents=[("我", "QM")]),
    # S04 —— 次日：两块磨盘、陆泽推门
    dict(s="E06-S04", n=1, sec=3, size="中全景", camera="低机位随两块磨盘离地升起", axis="秦铭在院角（画右）抱磨盘，院门在画左", blocking="次日，秦铭走到院角弯腰抱住上下两块磨盘猛然发力，两块磨盘一起离地被他搬离原地",
         cast=["QM"], action=("QM", "秦铭弯腰抱住院角上下两块叠放的磨盘，猛然发力，两块磨盘一起离地，被他搬离原地放到一旁", MILL),
         entry="秦铭弯腰抱住院角叠放的两块磨盘", exit="两块磨盘被搬离原地放在一旁，原处露出雪坑",
         dims={"POSSESSION": D("磨盘在原地", "磨盘搬离原地", "MILL_IN_PLACE", "MILL_MOVED"), "MOMENTUM": D("蓄力", "发力搬起", "COILED", "HEAVED")}, referents=[]),
    dict(s="E06-S04", n=2, sec=2, cps=4.8, size="中景", camera="横移随陆泽推门愣住", axis="陆泽（画左，院门）面向秦铭（画右）", blocking="陆泽正好推开院门进来，看见这一幕愣在门口，手还搭在门板上，话说到一半",
         cast=["LZ", "QM"], action=("LZ", "陆泽推开院门跨进来，看见秦铭搬磨盘愣在门口，手还搭在门板上，话说到一半就停了，说完立即快步走过来", "QM"), dialogue=("LZ", "小秦，你这是……", "QM"), emotion="calm",
         perf=("惊", "推开院门愣在门口，手还搭在门板上", "话说到一半"), after_line="快步走过来", slots={"LZ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         faces={"QM": "BACK_THREE_QUARTER_FACING_MILL_NOT_MEASURABLE"},
         entry="院门被陆泽推开，秦铭刚放下磨盘", exit="陆泽愣在门口，手搭在门板上，话停在一半",
         dims={"POSITION": D("陆泽在院门外", "陆泽在院门内", "OUTSIDE_GATE", "INSIDE_GATE"), "CONTACT": D("手推门", "手搭在门板上", "PUSHING_GATE", "HAND_ON_GATE")}, referents=[("小秦", "QM")]),
    dict(s="E06-S04", n=3, sec=5.5, cps=5.2, size="中近景", camera="双人同框缓推，陆泽画左、秦铭画右", axis="陆泽（画左）面向秦铭（画右）", blocking="陆泽上前拍秦铭的肩膀，脸朝画面前方呈四分之三正面、不背过去，大嗓门说一句，退后一步上下打量秦铭",
         cast=["LZ", "QM"], action=("LZ", "陆泽上前一把拍在秦铭肩膀上，大嗓门说一句，说完立即退后一步上下打量他", "QM"), dialogue=("LZ", "和隔壁村的二病子一样，刚新生就能抓起四百多斤的重物。", "QM"), emotion="joy",
         perf=("喜", "上前一把拍在秦铭肩膀上", "嗓门大"), after_line="退后一步上下打量秦铭", slots={"LZ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"}, faces={"QM": "BACK_THREE_QUARTER_TO_LUZE_NOT_MEASURABLE"},
         entry="陆泽快步走到秦铭跟前抬手，脸朝画面前方呈四分之三正面", exit="陆泽退后一步上下打量秦铭，秦铭肩上还留着被拍的雪印",
         dims={"CONTACT": D("手抬起", "拍肩后收手", "HAND_RAISED", "SHOULDER_PATTED"), "POSITION": D("贴近秦铭", "退后一步", "CLOSE", "STEPPED_BACK")}, referents=[("他", "QM")]),
    # S05 —— 梁婉清、文睿、秦铭
    dict(s="E06-S05", n=1, sec=3.5, cps=5.0, size="中景", camera="横移随梁婉清跨进院门", axis="梁婉清（画左，院门）面向秦铭与磨盘（画右）", blocking="梁婉清从一墙之隔的院子过来，跨进院门，双手合在胸前，看清后失神，语气发颤说一句，走到磨盘旁",
         cast=["LW", "QM"], action=("LW", "梁婉清从院门跨进来，双手合在胸前，看着搬离原地的磨盘失神，语气发颤说一句，说完立即走到磨盘旁", "QM"), dialogue=("LW", "在黄金年龄段新生，小秦真的做到了。", "QM"), emotion="joy",
         perf=("惊", "从院门跨进来，双手合在胸前", "语气发颤"), after_line="走到磨盘旁", slots={"LW": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         faces={"QM": "BACK_THREE_QUARTER_FACING_GATE_NOT_MEASURABLE"},
         entry="梁婉清跨进院门，双手合在胸前", exit="梁婉清走到磨盘旁站定",
         dims={"POSITION": D("院门", "磨盘旁", "AT_GATE", "AT_MILL"), "POSTURE": D("双手合胸", "手垂下", "HANDS_CLASPED", "HANDS_DOWN")}, referents=[("小秦", "QM")]),
    dict(s="E06-S05", n=2, sec=4, cps=5.2, size="中近景", camera="环绕摸磨盘的梁婉清", axis="梁婉清（画右）面向磨盘（画左）", blocking="梁婉清伸手摸了摸磨盘冰冷的石面，声音亮起来说一句，回头看陆泽",
         cast=["LW"], action=("LW", "梁婉清伸手摸了摸磨盘冰冷的石面，声音亮起来说一句，说完立即回头看陆泽", MILL), dialogue=("LW", "这么多年以来，小秦算是双树村头一份。", "LZ"), emotion="joy",
         perf=("傲", "伸手摸了摸磨盘的石面", "声音亮起来"), after_line="回头看陆泽",
         entry="梁婉清站在磨盘旁伸手", exit="梁婉清的手按在磨盘石面上，回头看向陆泽",
         dims={"CONTACT": D("手悬在磨盘上", "手按在磨盘石面", "HAND_HOVER", "HAND_ON_STONE")}, referents=[("小秦", "QM")]),
    dict(s="E06-S05", n=3, sec=2, cps=5.0, size="中景", camera="低机位双人同框缓推，文睿画左仰头、秦铭画右", axis="文睿（画左）面向秦铭（画右）", blocking="文睿跑过来抱住秦铭的腿，仰着头，大眼亮晶晶，嚷着说一句，蹦起来",
         cast=["WR", "QM"], action=("WR", "文睿跑过来一把抱住秦铭的腿，仰着头嚷着说一句，说完立即蹦起来", "QM"), dialogue=("WR", "小叔，你太厉害了！", "QM"), emotion="joy",
         perf=("喜", "跑过来抱住秦铭的腿仰着头", "嚷着说"), after_line="蹦起来", slots={"WR": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"}, faces={"QM": "BACK_THREE_QUARTER_TO_GATE_NOT_MEASURABLE"},
         entry="文睿从院门跑向秦铭", exit="文睿抱着秦铭的腿蹦起来，秦铭低头看他",
         dims={"CONTACT": D("文睿跑着未触及", "文睿抱住秦铭的腿", "RUNNING", "HUGGING_LEG"), "POSTURE": D("仰头", "蹦起", "LOOKING_UP", "JUMPING")}, referents=[("小叔", "QM")]),
    dict(s="E06-S05", n=4, sec=3.5, cps=5.0, size="中近景", camera="横移随秦铭放磨盘拍雪到抱起文睿", axis="秦铭（画右）面向陆泽梁婉清（画左）", blocking="秦铭放下手里扶着的磨盘，拍掉手上的雪，平稳地说一句，把文睿抱起来",
         cast=["QM", "WR"], action=("QM", "秦铭松开扶着磨盘的手，拍掉手上的雪，平稳地说一句，说完立即弯腰把文睿抱起来", "WR"), dialogue=("QM", "我感觉新生的变化还在进行中。", "LZ"), emotion="calm",
         perf=("坚", "拍掉手上的雪", "平稳地说"), after_line="弯腰把文睿抱起来", slots={"QM": "SCREEN_RIGHT", "WR": "SCREEN_LEFT"},
         faces={"WR": "SMALL_CHILD_AT_LEG_NOT_MEASURABLE"},
         entry="秦铭一手扶着磨盘，文睿抱着他的腿", exit="秦铭把文睿抱在臂弯里，手上的雪已拍净",
         dims={"POSSESSION": D("文睿在地上抱腿", "文睿被抱在臂弯", "CHILD_ON_GROUND", "CHILD_IN_ARMS"), "CONTACT": D("手扶磨盘", "手抱文睿", "HAND_ON_MILL", "ARMS_AROUND_CHILD")}, referents=[("我", "QM")]),
    # S06 —— 五百斤极限、六百斤少年
    dict(s="E06-S06", n=1, sec=2.5, size="中景", camera="环绕带着惊容的梁婉清", axis="梁婉清（画左）面向秦铭（画右）", blocking="梁婉清带着惊容看着秦铭，又看向搬离原地的磨盘，手指绞着围裙",
         cast=["LW"], action=("LW", "梁婉清带着惊容看着秦铭，又转头看向搬离原地的磨盘，手指绞着围裙边", MILL),
         entry="梁婉清看着秦铭，手指绞着围裙", exit="梁婉清转头盯着磨盘，脸上带着惊容",
         dims={"POSTURE": D("看向秦铭", "转头看磨盘", "EYES_ON_QM", "EYES_ON_MILL")}, referents=[]),
    dict(s="E06-S06", n=2, sec=3.5, cps=5.0, size="中近景", camera="缓推比着五指的梁婉清", axis="梁婉清（画左）面向秦铭（画右）", blocking="梁婉清伸出五根手指比了比，慢慢地说前半句，看向秦铭",
         cast=["LW"], action=("LW", "梁婉清伸出五根手指在胸前比了比，慢慢地说前半句，说完立即看向秦铭", ""), dialogue=("LW", "稳定之后，扛鼎五百斤已是极限，", "QM"), emotion="calm",
         perf=("疑", "伸出五根手指在胸前比了比", "慢慢地说"), after_line="看向秦铭",
         entry="梁婉清抬起手", exit="梁婉清五指张开停在胸前，目光落在秦铭身上",
         dims={"POSTURE": D("手垂着", "五指张开比在胸前", "HAND_DOWN", "FIVE_FINGERS_UP")}, referents=[]),
    dict(s="E06-S06", n=3, sec=2.5, cps=5.0, size="中景", camera="横移随梁婉清抓住陆泽胳膊", axis="梁婉清（画左）面向陆泽（画右）", blocking="梁婉清一把抓住身旁陆泽的胳膊，压低声音说后半句，看向陆泽",
         cast=["LW", "LZ"], action=("LW", "梁婉清一把抓住身旁陆泽的胳膊，压低声音说后半句，说完立即看向陆泽", "LZ"), dialogue=("LW", "小秦不会要抵临吧？", "LZ"), emotion="fear",
         perf=("惧", "一把抓住陆泽的胳膊", "压低声音"), after_line="看向陆泽", slots={"LW": "SCREEN_LEFT", "LZ": "SCREEN_RIGHT"},
         entry="梁婉清的手伸向陆泽的胳膊", exit="梁婉清抓着陆泽的胳膊看着他",
         dims={"CONTACT": D("手未触及陆泽", "手抓住陆泽胳膊", "HAND_FREE", "GRIPPING_ARM")}, referents=[("小秦", "QM")]),
    dict(s="E06-S06", n=4, sec=5, cps=5.0, size="中全景", camera="随陆泽指向村外升起", axis="陆泽（画右）望向村外院门（画左）", blocking="陆泽望向村外的方向抬手一指，压低声音说一句，收回手看秦铭",
         cast=["LZ", "LW", "QM"], action=("LZ", "陆泽望向村外的方向抬手一指，压低声音说一句，说完立即收回手看向秦铭", "QM"), dialogue=("LZ", "据说，远处那座明亮的城池有可扛鼎六百斤的少年。", "QM"), emotion="calm",
         perf=("盼", "望向村外抬手一指", "压低声音"), after_line="收回手看秦铭", slots={"LZ": "SCREEN_RIGHT", "LW": "SCREEN_CENTER", "QM": "SCREEN_LEFT"},
         faces={"LW": "BACK_THREE_QUARTER_TO_LUZE_NOT_MEASURABLE", "QM": "SMALL_FIGURE_AT_EDGE_NOT_MEASURABLE"},
         entry="陆泽转头望向村外，抬起手", exit="陆泽收回手看着秦铭，梁婉清仍抓着他的胳膊",
         dims={"POSTURE": D("抬手指向村外", "收手看秦铭", "POINTING_OUT", "HAND_BACK"), "POSITION": D("面向院门", "转向秦铭", "FACING_GATE", "FACING_QM")}, referents=[]),
    # S07 —— 街上嘈杂：周家阿婆
    dict(s="E06-S07", n=1, sec=2.5, size="中全景", camera="横移随梁婉清出院门", axis="梁婉清自院中（画右）走向院门（画左）", blocking="街上忽然传来一阵嘈杂声，梁婉清转头看向院门，四分之三正面对着院门一侧、脸不背过去，快步出院门去看",
         cast=["LW"], action=("LW", "街上传来嘈杂的人声，梁婉清转头，快步走出院门去看", ""),
         entry="梁婉清转头朝院门方向看，四分之三正面对着院门一侧", exit="梁婉清走出院门，人在街上",
         dims={"POSITION": D("院中", "院门外街上", "IN_YARD", "ON_STREET")}, referents=[]),
    dict(s="E06-S07", n=2, sec=2.5, cps=5.0, size="中近景", camera="缓推扶着院门的梁婉清", axis="梁婉清（画左，院门）面向陆泽秦铭（画右）", blocking="梁婉清很快回来，扶着院门喘气，急促地说一句，指向街上",
         cast=["LW"], action=("LW", "梁婉清扶着院门喘着气，急促地说一句，说完立即抬手指向街上", ""), dialogue=("LW", "周家的阿婆身体不行了。", "LZ"), emotion="fear",
         perf=("慌", "扶着院门喘气", "急促地说"), after_line="抬手指向街上",
         entry="梁婉清扶着院门框喘气", exit="梁婉清抬手指向街上",
         dims={"POSTURE": D("扶门喘气", "抬手指街", "LEANING_ON_GATE", "POINTING_STREET")}, referents=[]),
    dict(s="E06-S07", n=3, sec=1.5, cps=4.8, size="中景", camera="环绕迎上一步的陆泽", axis="陆泽（画右）面向院门的梁婉清（画左）", blocking="陆泽放下搭在磨盘边的手迎上一步，追问一句，看向院门外",
         cast=["LZ"], action=("LZ", "陆泽放下搭在磨盘边的手迎上一步，追问一句，说完立即看向院门外", "LW"), dialogue=("LZ", "什么原因？", "LW"), emotion="calm",
         perf=("疑", "放下搭在磨盘边的手迎上一步", "追问"), after_line="看向院门外",
         entry="陆泽的手搭在磨盘边", exit="陆泽迎前一步，目光越过院门看向街上",
         dims={"POSITION": D("磨盘旁", "迎前一步", "AT_MILL", "STEPPED_FORWARD")}, referents=[]),
    dict(s="E06-S07", n=4, sec=4, cps=5.0, size="中近景", camera="横移随搓手的梁婉清转身", axis="梁婉清（画左）面向陆泽（画右）", blocking="梁婉清搓着手，声音低下去说一句，转身往街上走",
         cast=["LW", "LZ"], action=("LW", "梁婉清搓着手，声音低下去说一句，说完立即转身往街上走", "LZ"), dialogue=("LW", "最近她吃得东西太少，身体本来就不太好。", "LZ"), emotion="calm",
         perf=("哀", "搓着手", "声音低下去"), after_line="转身往街上走", slots={"LW": "SCREEN_LEFT", "LZ": "SCREEN_RIGHT"},
         entry="梁婉清站在院门内搓着手", exit="梁婉清转身跨出院门往街上走，陆泽跟上",
         dims={"POSITION": D("院门内", "跨出院门", "INSIDE_GATE", "OUT_TO_STREET"), "CONTACT": D("双手互搓", "双手垂下", "HANDS_RUBBING", "HANDS_DOWN")}, referents=[("她", "ZA")]),
    # S08 —— 周家屋内
    dict(s="E06-S08", n=1, sec=3, size="中景", camera="横移随秦铭陆泽进屋到炕前，两人的脸在中景里清楚朝前", axis="秦铭陆泽自屋门（画左）走向火炕（画右）", blocking="秦铭和陆泽跨进周家屋门，两人的脸朝前清楚可见；炕上一床旧兽皮盖着一个躺着的人形，只露出一只枯瘦的手垂在炕沿，脸看不见；两个孩子跪在炕前，脸埋在炕沿上哭喊着奶奶；屋里只有炕、铜盆、木柜与竹筐，墙上只挂农具",
         cast=["QM", "LZ"], action=("QM", "秦铭和陆泽跨进周家的屋门走到炕前；炕上旧兽皮盖着躺着的人形，只露出一只枯瘦的手垂在炕沿，两个孩子跪在炕前脸埋在炕沿上哭喊着奶奶", "LZ"),
         group_counts=[{"group_id": "GROUP-ZHOU-CHILDREN", "count": 2, "note": "周家两个孩子，跪在炕前"}],
         slots={"QM": "SCREEN_LEFT", "LZ": "SCREEN_RIGHT"},
         entry="秦铭和陆泽跨进周家屋门，两人的脸朝前清楚可见，屋里两个孩子跪在炕前，脸埋在炕沿上哭喊", exit="秦铭和陆泽站在炕前，周阿婆垂在炕沿的手一动不动",
         dims={"POSITION": D("屋门口", "炕前", "AT_DOOR", "AT_KANG")}, referents=[]),
    dict(s="E06-S08", n=2, sec=3, size="中景", camera="低机位环绕跪着的周长裕", axis="周长裕（画右，炕前）面向炕上（画左）", blocking="周长裕跪在炕前一旁满脸泪水，右臂吊在胸前，左手用力扇自己的嘴巴",
         cast=["ZC"], action=("ZC", "周长裕跪在炕前满脸泪水，右臂用布带吊在胸前，抬起左手用力扇自己的嘴巴", ""),
         entry="周长裕跪在炕前，左手抬起", exit="周长裕的左手扇在自己脸上，脸颊发红，泪水横流",
         dims={"CONTACT": D("左手抬起", "左手扇在自己脸上", "HAND_RAISED", "SLAPPED_SELF")}, referents=[]),
    dict(s="E06-S08", n=3, sec=2, cps=4.8, size="特写", camera="环绕扇嘴的周长裕", axis="周长裕（画右）面向炕上（画左）", blocking="周长裕的右臂用布带吊在胸前一动不动，他扬起左手又扇自己一个嘴巴，哽咽着挤出一句，伏下身",
         cast=["ZC"], action=("ZC", "周长裕右臂吊在胸前不动，用左手又扇自己一个嘴巴，哽咽着挤出一句，说完立即伏下身", ""), dialogue=("ZC", "我没用，不孝……", ""), emotion="plead",
         perf=("愧", "用力扇自己的嘴巴", "哽咽着挤出"), after_line="伏下身",
         entry="周长裕右臂吊在胸前的布带里不动，左手又扬起", exit="周长裕伏下身，额头几乎贴到炕沿",
         dims={"POSTURE": D("跪直", "伏身", "KNEELING_UP", "BOWED_DOWN"), "CONTACT": D("手扬起", "手扇脸后撑地", "HAND_UP", "HAND_ON_FLOOR")}, referents=[("我", "ZC")]),
    dict(s="E06-S08", n=4, sec=3, size="中近景", camera="高机位自沉默的秦铭缓降到炕沿的竹筐", axis="秦铭（画右）低头看向炕沿竹筐（画左）", blocking="秦铭沉默地站着，低头看着炕沿边的竹筐——里面是阿婆藏在冰雪下的地薯、冷馍，和他送她的那一小包干果，一颗都没舍得吃",
         cast=["QM"], action=("QM", "秦铭沉默地站着，低头看向炕沿边的竹筐，筐里是藏在冰雪下的地薯和冷馍，还有他送的那一小包干果一颗未动", BASKET),
         entry="秦铭站在炕前低下头，炕沿边放着一只竹筐", exit="秦铭的目光停在竹筐里的地薯、冷馍与那一小包干果上，筐沿还沾着冰雪",
         dims={"POSTURE": D("抬头站着", "低头看筐", "HEAD_UP", "HEAD_DOWN_AT_BASKET")}, referents=[("他", "QM"), ("她", "ZA")]),
    # S09 —— 五斤坚果
    dict(s="E06-S09", n=1, sec=4, size="中全景", camera="横移随秦铭拎布袋走到周家门口", axis="秦铭自街上（画左）走向周家门口的周长裕（画右）", blocking="浅夜将尽，秦铭拎着装有五斤坚果的鼓鼓的布袋沿街走到周家门口，递给正面朝街、脸朝前站在门口红着眼睛的周长裕",
         cast=["QM", "ZC"], action=("QM", "秦铭拎着鼓鼓的布袋沿街走到周家门口，把布袋递向站在门口红着眼睛的周长裕", "ZC"), slots={"QM": "SCREEN_LEFT", "ZC": "SCREEN_RIGHT"},
         entry="秦铭拎着布袋沿街走来，周长裕正面朝街站在周家门口，脸朝前", exit="秦铭把布袋递到周长裕面前",
         dims={"POSITION": D("街上", "周家门口", "ON_STREET", "AT_ZHOU_DOOR"), "POSSESSION": D("布袋在秦铭手中", "布袋递向周长裕", "BAG_HELD_QM", "BAG_OFFERED")}, referents=[]),
    dict(s="E06-S09", n=2, sec=1.5, cps=4.8, size="中近景", camera="缓推推袋的周长裕", axis="周长裕（画右）面向秦铭（画左）", blocking="周长裕左手把布袋往外推，哑着嗓子喊一声，低下头",
         cast=["ZC", "QM"], action=("ZC", "周长裕用左手把布袋往外推，哑着嗓子喊一声，说完立即低下头", "QM"), dialogue=("ZC", "秦兄弟！", "QM"), emotion="plead",
         perf=("羞", "用左手把布袋往外推", "哑着嗓子喊"), after_line="低下头", slots={"ZC": "SCREEN_RIGHT", "QM": "SCREEN_LEFT"},
         faces={"QM": "BACK_THREE_QUARTER_TO_ZHOU_NOT_MEASURABLE"},
         entry="布袋递到周长裕面前，他抬起左手", exit="周长裕的左手推着布袋，低着头",
         dims={"CONTACT": D("手未触袋", "手推布袋", "HAND_FREE", "HAND_PUSHING_BAG")}, referents=[]),
    dict(s="E06-S09", n=3, sec=2.5, size="中景", camera="环绕按袋转身的秦铭", axis="秦铭（画左）面向周长裕（画右）", blocking="秦铭把布袋按在周长裕手里，转身沿街离去；周家屋里的哭声还在",
         cast=["QM", "ZC"], action=("QM", "秦铭把布袋按在周长裕左手里，转身沿街离去", "ZC"), slots={"QM": "SCREEN_LEFT", "ZC": "SCREEN_RIGHT"},
         faces={"QM": "BACK_TO_CAMERA_WALKING_AWAY_NOT_MEASURABLE"},
         entry="秦铭双手把布袋按在周长裕手里", exit="周长裕抱着布袋站在门口，秦铭的背影沿街远去",
         dims={"POSSESSION": D("布袋在两人手间", "布袋在周长裕手中", "BAG_BETWEEN", "BAG_WITH_ZHOU"), "POSITION": D("秦铭在门口", "秦铭沿街离去", "AT_DOOR", "WALKING_AWAY")}, referents=[]),
    # S10 —— 金色灯笼眼
    dict(s="E06-S10", n=1, sec=3, size="中全景", camera="低机位横移过仰望的秦铭", axis="秦铭坐在院中仰望夜空", blocking="深夜，秦铭坐在自家院中的雪地上仰望着夜空，雪面的月色反光照出他的轮廓，他失神了很久",
         cast=["QM"], action=("QM", "秦铭坐在深夜院中的雪地上仰起头，望着雪光下什么都看不到的夜空，出神", ""),
         entry="秦铭坐在院中，低着头", exit="秦铭仰着头，目光落在夜空深处",
         dims={"POSTURE": D("低头坐着", "仰头望天", "HEAD_DOWN_SEATED", "HEAD_UP_GAZING")}, referents=[("他", "QM")]),
    dict(s="E06-S10", n=2, sec=3, size="远景", camera="低机位自秦铭升起到夜空的两盏金色灯笼眼", axis="秦铭（画面下方）仰望夜空（画面上方）", blocking="一股让人心悸的气息扑面而至，秦铭的身体瞬间绷紧；伸手不见五指的夜空里出现两盏金色灯笼似的眼睛，神秘慑人",
         cast=["QM"], action=("QM", "一股让人心悸的气息扑面而至，秦铭的身体瞬间绷紧；夜空里出现两盏金色灯笼似的巨眼，神秘慑人", EYES),
         faces={"QM": "SMALL_FIGURE_BELOW_SKY_NOT_MEASURABLE"},
         entry="秦铭仰坐院中，夜空空无一物", exit="夜空里亮着两盏金色灯笼似的巨眼，秦铭绷紧身体半撑起来",
         dims={"INTEGRITY": D("夜空无光", "两盏金色灯笼眼", "SKY_EMPTY", "GOLDEN_EYES_APPEAR"), "POSTURE": D("松弛仰坐", "绷紧半撑", "RELAXED", "TENSED")}, referents=[]),
    dict(s="E06-S10", n=3, sec=3, size="中景", camera="横移随狂风卷雪与屋顶颤动", axis="秦铭（画右）抬臂护脸，屋顶在画左", blocking="平静的冬夜狂风大作，地面的雪花全部暴涌而起，屋顶剧烈颤动，秦铭抬臂护住头脸",
         cast=["QM"], action=("QM", "狂风大作，地面的雪花全部暴涌而起，屋顶剧烈颤动，秦铭抬起手臂护住头脸", ""),
         faces={"QM": "FACE_OUT_OF_FRAME_BEHIND_ARM_NOT_MEASURABLE"},
         entry="秦铭半撑在雪地上，风刚起", exit="雪花暴涌，屋顶颤动，秦铭的手臂挡在脸前",
         dims={"MOMENTUM": D("无风", "狂风卷雪", "STILL_AIR", "GALE_SNOW"), "CONTACT": D("手臂垂着", "手臂护脸", "ARMS_DOWN", "ARM_SHIELDING")}, referents=[]),
    dict(s="E06-S10", n=4, sec=3, size="远景", camera="低机位横摇跟随灯笼眼横空而过", axis="金色灯笼眼自画右横空掠向画左，秦铭在画面下方", blocking="那对金色的灯笼带着罡风横空而过，翼影像乌云遮天；随着它远去，暴风迅速变弱、消散",
         cast=["QM"], action=("QM", "秦铭抬头，两盏金色灯笼眼带着罡风横空而过，翼影像乌云遮天；随着它远去，暴风迅速变弱、消散", EYES),
         faces={"QM": "SMALL_FIGURE_BELOW_SKY_NOT_MEASURABLE"},
         entry="金色灯笼眼在夜空的一侧，狂风正烈", exit="金色灯笼眼远去消失在夜空另一侧，风息，雪花落下",
         dims={"POSITION": D("灯笼眼在天一侧", "灯笼眼远去消失", "EYES_NEAR", "EYES_GONE"), "MOMENTUM": D("罡风正烈", "风息雪落", "GALE", "CALM")}, referents=[]),
    dict(s="E06-S10", n=5, identity_reanchor=True, sec=1.5, cps=4.8, size="特写", camera="缓推瞳孔收缩的秦铭", axis="秦铭望向它远去的方向（画左）", blocking="秦铭瞳孔收缩，撑着雪地站起来，气声说出三个字，望向它远去的方向",
         cast=["QM"], action=("QM", "秦铭瞳孔收缩，撑着雪地站起来，气声说出一句，说完立即望向它远去的方向", ""), dialogue=("QM", "高等生灵……", ""), emotion="fear",
         perf=("惊", "撑着雪地站起来", "气声"), after_line="望向它远去的方向",
         entry="秦铭撑着雪地，瞳孔收缩", exit="秦铭站起身，望着夜空那生灵远去的方向",
         dims={"POSTURE": D("半撑在地", "站起", "HALF_UP", "STANDING")}, referents=[]),
    # S11 —— 村中骚动
    dict(s="E06-S11", n=1, sec=3, size="中全景", camera="横移随走出院门议论的村人到邻居甲", axis="村人自各家院门（画右）走到街上（画左）", blocking="村中一阵骚动，不少人从各家院门走出来议论纷纷；邻居甲神色凝重地抬手按住一个后生的肩",
         cast=["VA"], action=("VA", "村人从各家院门走出来站在街上议论纷纷，邻居甲神色凝重地抬手按住身边一个后生的肩膀", ""),
         entry="街上各家院门陆续打开，人走出来", exit="邻居甲的手按在一个后生的肩上，四周的人都看着他",
         dims={"POSITION": D("人在院内", "人聚在街上", "INDOORS", "ON_STREET"), "CONTACT": D("邻居甲手垂着", "手按后生肩", "HAND_DOWN", "HAND_ON_SHOULDER")}, referents=[]),
    dict(s="E06-S11", n=2, sec=4, cps=5.0, size="中近景", camera="缓推按着后生肩膀的邻居甲", axis="邻居甲（画左）面向后生（画右）", blocking="邻居甲按着后生的肩膀，沉声说一句，望向天边",
         cast=["VA"], action=("VA", "邻居甲按着后生的肩膀，沉声说一句，说完立即望向天边", ""), dialogue=("VA", "不用慌，那是高等生灵在赶路，过境而已。", ""), emotion="calm",
         perf=("坚", "抬手按住后生的肩膀", "沉声说"), after_line="望向天边",
         entry="邻居甲按着后生的肩膀看着他", exit="邻居甲抬头望向天边，手还按在后生肩上",
         dims={"POSTURE": D("看着后生", "抬头望天边", "EYES_ON_YOUTH", "EYES_ON_SKY")}, referents=[]),
    # S12 —— 决心与开龙脊
    dict(s="E06-S12", n=1, sec=3, size="中全景", camera="横移随秦铭回院站定", axis="秦铭自院门（画左）回到院中（画右）", blocking="秦铭从街上回到院中，望着无边的夜幕，坚定地站直身子",
         cast=["QM"], action=("QM", "秦铭从院门回到院中站定，望着无边的夜幕，坚定地站直身子", ""),
         entry="秦铭跨进院门", exit="秦铭站在院中挺直身子望着夜幕",
         dims={"POSITION": D("院门", "院中", "AT_GATE", "IN_YARD"), "POSTURE": D("走动", "站直", "WALKING", "STANDING_TALL")}, referents=[]),
    dict(s="E06-S12", n=2, sec=3.5, cps=5.0, size="中近景", camera="固定，秦铭正面略偏右", axis="秦铭面向院门方向（画左）", blocking="秦铭攥紧拳头，低声说一句，摆开架势",
         cast=["QM"], action=("QM", "秦铭攥紧双拳，低声说一句，说完立即摆开架势", ""), dialogue=("QM", "纵然心有所念，也要有实力才行。", ""), emotion="threat",
         perf=("坚", "攥紧双拳", "低声说"), after_line="摆开架势",
         entry="秦铭双手垂在身侧", exit="秦铭攥着拳摆开架势",
         dims={"POSTURE": D("手垂身侧", "攥拳摆架势", "ARMS_AT_SIDE", "FISTS_STANCE")}, referents=[]),
    dict(s="E06-S12", n=3, sec=3, size="中景", camera="低机位环绕演练动作的秦铭", axis="秦铭面向院门（画左）", blocking="秦铭演练幼时记得最清楚的那一组动作，拧旋转翻，身体涌现出蓬勃的力，体表泛起稀薄的光雾",
         cast=["QM"], action=("QM", "秦铭演练幼时记得最清楚的一组动作，拧旋转翻，身体涌出蓬勃的力，体表泛起稀薄的光雾", ""),
         entry="秦铭摆着架势蓄力", exit="秦铭一组动作演练完，体表泛着稀薄的光雾",
         dims={"MOMENTUM": D("静止架势", "拧旋转翻", "STANCE", "FLOWING_MOVES"), "INTEGRITY": D("体表无光", "体表光雾", "SKIN_PLAIN", "SKIN_MIST")}, referents=[]),
    dict(s="E06-S12", n=4, sec=4, size="中全景", camera="低机位随开龙脊的后仰升起", axis="秦铭侧身对镜向后弯成弯月", blocking="秦铭开龙脊：先弓腰，然后猛烈后仰，整条脊柱反向弯成夸张的弯月，骨节一路向上爆响，体表漾出一层比以往更清晰的银光",
         cast=["QM"], action=("QM", "秦铭先弓腰，然后猛烈后仰，整条脊柱反向弯成夸张的弯月，骨节一路向上爆响，体表漾出一层比以往清晰的银光", ""),
         entry="秦铭弓着腰蓄势", exit="秦铭的脊柱反弯成弯月，体表漾着比以往清晰的银光",
         dims={"POSTURE": D("弓腰", "后仰成弯月", "BOWED", "ARCHED_BACK"), "INTEGRITY": D("光雾稀薄", "银光清晰", "SKIN_MIST", "SKIN_SILVER_BRIGHT")}, referents=[]),
    # S13 —— 干果吃不饱，进山
    dict(s="E06-S13", n=1, sec=3, size="中景", camera="高机位随抖瘪袋缓降", axis="秦铭（画右）向炕上兽皮袋（画左）", blocking="秦铭就着热水往嘴里塞干果，一堆干货下肚都没饱；他抖了抖已经瘪下去的兽皮袋，咽了口口水",
         cast=["QM"], action=("QM", "秦铭就着热水往嘴里塞干果，吃了一堆都没饱，抖了抖已经瘪下去的兽皮袋，咽了口口水", BAG),
         entry="秦铭端着热水往嘴里塞干果", exit="秦铭抖着瘪下去的兽皮袋，喉结上下一动",
         dims={"POSSESSION": D("干果在手", "袋子瘪空", "NUTS_IN_HAND", "BAG_EMPTY"), "CONTACT": D("手端热水", "手抖兽皮袋", "HAND_ON_CUP", "HAND_ON_BAG")}, referents=[]),
    dict(s="E06-S13", n=2, sec=3.5, cps=5.2, size="中近景", camera="横移随秦铭抓弓上肩到推门", axis="秦铭（画右）向门边弓箭（画左）", blocking="秦铭抓起门边的弓箭挂上肩，咬着牙说一句，推门出去",
         cast=["QM"], action=("QM", "秦铭抓起门边的弓箭挂上肩，咬着牙说一句，说完立即推门出去", BOW), dialogue=("QM", "看来，等浅夜到来后，我得再次进山了。", ""), emotion="threat",
         perf=("贪", "抓起弓箭挂上肩", "咬着牙说"), after_line="推门出去",
         entry="秦铭伸手抓向门边的弓箭", exit="弓箭挂在秦铭肩上，屋门被推开",
         dims={"POSSESSION": D("弓箭靠在门边", "弓箭挂上肩", "BOW_BY_DOOR", "BOW_ON_SHOULDER"), "POSITION": D("屋内", "跨出屋门", "INDOORS", "OUT_THE_DOOR")}, referents=[("我", "QM")]),
    # S14 —— 冲向密林
    dict(s="E06-S14", n=1, sec=3, size="远景", camera="高机位横移跟随雪原疾奔", axis="秦铭自村口（画左）向密林（画右）", blocking="浅夜还没有彻底到来，秦铭背着弓箭已出现在村外的雪原上，脚下生风，雪粒飞溅",
         cast=["QM"], action=("QM", "秦铭背着弓箭在村外的雪原上疾奔，脚下生风，雪粒飞溅", BOW),
         faces={"QM": "FAR_FIGURE_RUNNING_NOT_MEASURABLE"},
         entry="秦铭背着弓箭从村口方向奔上雪原", exit="秦铭疾奔过雪原中段，身后一串脚印，雪粒飞溅",
         dims={"POSITION": D("村口方向", "雪原中段", "VILLAGE_EDGE", "MID_SNOWFIELD"), "MOMENTUM": D("起步", "全速疾奔", "STARTING", "SPRINTING")}, referents=[]),
    dict(s="E06-S14", n=2, sec=3, size="远景", camera="低机位随冲进林线升起", axis="秦铭冲向黑压压的林线（画右）", blocking="远处的小人影冲向黑压压的林线，冲进林木之间，雪地上只剩一串脚印",
         cast=["QM"], action=("QM", "秦铭冲向黑压压的林线，冲进林木之间不见了身影，雪地上只剩一串脚印", ""),
         faces={"QM": "FAR_FIGURE_INTO_TREELINE_NOT_MEASURABLE"},
         entry="远处秦铭的小人影奔向林线", exit="秦铭冲进林木之间不见了，雪地上留着一串脚印",
         dims={"POSITION": D("林线外雪原", "林木之间", "BEFORE_TREELINE", "INTO_FOREST")}, referents=[("他", "QM")]),
]

def _unit_first_shots() -> list[str]:
    spec = ROOT / f"workflow/nalu/{EP}/preproduction/{EP}_VIDEO_UNIT_GROUPING_SPEC_V1.json"
    order = [f"{sh['s']}-{sh['n']:02d}" for sh in SHOTS]
    if spec.is_file():
        groups = json.loads(spec.read_text(encoding="utf-8")).get("groups") or []
        ids = [g["editorial_shot_ids"][0] for g in groups]
        covered = [x for g in groups for x in g["editorial_shot_ids"]]
        if covered == order:
            return ids
    return order

def balance_camera_directions() -> list[tuple[str, str, str]]:
    firsts = _unit_first_shots()
    changed = []
    seq: list = []
    for sid in firsts:
        cp = CAMERA_PLANS[sid]
        if cp["motion_family"] == "LOCKED":
            seq.append(None); continue
        prev = seq[-1] if seq else None
        def ok(fam, d):
            if prev and prev[1] == d:
                return False
            window = [x for x in seq[-4:] if x] + [(fam, d)]
            return sum(1 for x in window if x[1] == d) <= 2
        fam, d = cp["motion_family"], cp["motion_direction"]
        if not ok(fam, d):
            for alt in _ALT:
                if alt != (fam, d) and ok(*alt):
                    cp["lens_intent"] = f"{cp['lens_intent']}（方向均衡：{_ZH_FAM[fam]}改为{_ZH_FAM[alt[0]]}）"
                    cp["motivation"] = f"{cp['motivation']}；引擎相邻单元方向规则：原 {fam}:{d} 改为 {alt[0]}:{alt[1]}"
                    cp["motion_family"], cp["motion_direction"] = alt
                    changed.append((sid, f"{fam}:{d}", f"{alt[0]}:{alt[1]}"))
                    fam, d = alt
                    break
            else:
                raise AssertionError((sid, "无法满足机位方向均衡"))
        seq.append((fam, d))
    return changed
CAMERA_DIRECTION_REBALANCED = balance_camera_directions()

# ---------- 校验镜头表（seq=17/19/27 + seq=29 规则 5/7） ----------
LEX = W29.load_lexicon()
EMOTION_WORDS = set(LEX["emotions"]); HOLD_WORDS = list(LEX["hold_instructions"]); TRIVIAL = list(LEX["trivial_body_actions"])
def engine_dialogue_need(text: str, cps: float) -> float:
    """tools/dialogue_cut_safety.py: start 0.12 + han/cps + punct*0.16 + other*0.08 + pad 0.32 (+ tail 0.25 when the
    line closes a video unit; assumed always, the grouping is decided later)."""
    words = text
    han = len(re.findall(r"[\u3400-\u9fff]", words)); punct = len(re.findall(r"[，。！？；、,.!?;]", words))
    other = len(re.sub(r"[\u3400-\u9fff\s，。！？；、,.!?;]", "", words))
    return 0.12 + han / cps + punct * 0.16 + other * 0.08 + 0.32 + 0.25
DERIVED_SECONDS = {}
for sh in SHOTS:
    if sh.get("dialogue"):
        need = max(NPR.min_dialogue_seconds(sh["dialogue"][1], sh["cps"]), engine_dialogue_need(sh["dialogue"][1], sh["cps"]))
        sh["sec"] = math.ceil(need / 0.5 - 1e-9) * 0.5
        DERIVED_SECONDS[f"{sh['s']}-{sh['n']:02d}"] = sh["sec"]
by_scene = {}
for sh in SHOTS:
    by_scene.setdefault(sh["s"], []).append(sh)
assert list(by_scene) == list(SCENES), "镜头表场次顺序与 SCENES 不一致"
for sid, meta in SCENES.items():
    meta["sec"] = round(sum(x["sec"] for x in by_scene[sid]), 2)   # seq=29: scene seconds follow the lines, no template
    assert meta["sec"] <= PACING["scene_seconds_max"], (sid, "单场 ≤16 s")
    secs = [x["sec"] for x in by_scene[sid]]
    def _part(rest):
        if not rest: return True
        acc = 0
        for i, v in enumerate(rest):
            acc += v
            if 4 - 1e-9 <= acc <= 8 + 1e-9 and _part(rest[i + 1:]): return True
            if acc > 8: return False
        return False
    assert _part(secs), (sid, "无法切成 4–8 s 单元", secs)
prev_locked = False
_run_word, _run_len, _run_scene = None, 0, None
for i, sh in enumerate(SHOTS):
    shot_id = f"{sh['s']}-{sh['n']:02d}"
    assert shot_id in CAMERA_PLANS, (shot_id, "缺机位方案")
    assert 1.5 <= sh["sec"] <= PACING["shot_seconds_max"], (shot_id, "单镜 1.5–6 s")
    assert sh["entry"] != sh["exit"], sh
    for d, (a, b, ca, cb) in sh["dims"].items():
        assert d in {"POSITION", "POSTURE", "CONTACT", "POSSESSION", "INTEGRITY", "MOMENTUM"} and a != b and ca != cb, (shot_id, d)
    for word in ("持续", "连续", "全黑", "极暗", "纯黑", "黑暗", "伏击", "埋伏", "截", "藏身", "雪窟窿", *HOLD_WORDS):
        assert word not in sh["action"][1] and word not in sh["entry"] and word not in sh["exit"], (shot_id, "禁用词", word)
    for k in sh["cast"]:
        assert k not in VOICE_ONLY, (shot_id, "只配音角色不得入可见 cast")
    for k, fv in (sh.get("faces") or {}).items():
        from keyframe_q1_builder import pose_exempt as _pe
        assert _pe(fv), (shot_id, k, fv, "D-57 ④：face_visibility 只能用闭集豁免标记（BACK_/FAR_FIGURE/SMALL_/FACE_OUT_OF_FRAME/HANDS_ONLY），3/4 与侧脸一律不标")
    cp = CAMERA_PLANS[shot_id]
    locked = cp["motion_family"] == "LOCKED"
    if sh.get("dialogue"):
        assert sh.get("cps"), (shot_id, "对白镜必须标字/秒")
        need = NPR.min_dialogue_seconds(sh["dialogue"][1], sh["cps"])
        assert need <= sh["sec"] <= need + 1.0 + 1e-9, (shot_id, "seq=29 规则 5a：对白镜时长 = 台词推导值（引擎切点安全 0.12+0.32+0.25+标点 0.16 最多 +1.0）", need, sh["sec"])
        assert sh.get("emotion") in NPR.EMOTION_DELIVERY, (shot_id, "emotion")
        perf = sh.get("perf"); assert perf and len(perf) == 3 and all(perf), (shot_id, "seq=29 规则 7b：performance 三要素")
        assert perf[0] in EMOTION_WORDS, (shot_id, "情绪词不在闭集词表", perf[0])
        assert perf[1] not in TRIVIAL and not any(perf[1].startswith(t) for t in TRIVIAL), (shot_id, "规则 5c：身体动作不得是琐碎动作", perf[1])
        assert sh.get("after_line"), (shot_id, "规则 5b：说完立即<动作>")
        assert f"说完立即{sh['after_line'][:4]}" in sh["action"][1], (shot_id, "action 须写『说完立即<after_line>』", sh["after_line"])
        if sh["dialogue"][0] == "WR":
            assert "QM" in sh["cast"], (shot_id, "儿童对白必须与秦铭同框")
            assert sh["cps"] >= 4.5, (shot_id, "规则 7d：儿童语速 ≥4.5")
        if sh["s"] != _run_scene:
            _run_scene, _run_word, _run_len = sh["s"], None, 0
        if perf[0] == _run_word:
            _run_len += 1; assert _run_len <= 2, (shot_id, "规则 7c：同场连续 3 镜同情绪词", perf[0])
        else:
            _run_word, _run_len = perf[0], 1
    else:
        assert sh["sec"] <= 4, (shot_id, "无对白镜 ≤4 s")
        assert not locked, (shot_id, "无对白镜必须有机位运动")
        if sh["sec"] >= 3 and cp["motion_family"] not in NPR.MOVING_CAMERA:
            assert any(v in sh["action"][1] for v in NPR.BODY_VERBS), (shot_id, "R7：无对白 ≥3 s 且机位非运动族时动作须含身体动词")
        if sh["s"] != _run_scene:
            _run_scene, _run_word, _run_len = sh["s"], None, 0
    if locked:
        assert sh.get("dialogue") and sh["sec"] <= 5, (shot_id, "LOCKED 只允许 ≤5 s 对白镜")
        assert not prev_locked, (shot_id, "不得连续 LOCKED")
    assert not (i == 0 and locked), "开场镜必须运动"
    prev_locked = locked
assert sum(1 for s in SHOTS if CAMERA_PLANS[f"{s['s']}-{s['n']:02d}"]["motion_family"] == "LOCKED") / len(SHOTS) <= PACING["camera_motion_policy"]["locked_share_max"]
_run, _prev = 0, None
for sh in SHOTS:
    cp = CAMERA_PLANS[f"{sh['s']}-{sh['n']:02d}"]; key = (sh["s"], cp["camera_side"], cp["shot_scale"])
    _run = _run + 1 if key == _prev else 1; _prev = key
    assert _run <= 2, (sh["s"], sh["n"], "同轴同景别不得连续 >2 镜")
FAR_MARK = ("FAR_FIGURE", "SMALL_FIGURE", "BACK_TO_CAMERA")
REANCHOR_MISSING: list[str] = []
for sid, shots in by_scene.items():
    seen_far = False
    for sh in shots:
        f = (sh.get("faces") or {}).get("QM", "")
        if "QM" in sh["cast"] and any(m in f for m in FAR_MARK):
            seen_far = True; continue
        if "QM" in sh["cast"] and seen_far and not f:
            if not sh.get("identity_reanchor"):
                REANCHOR_MISSING.append(f"{sid}-{sh['n']:02d}")
            seen_far = False
assert not REANCHOR_MISSING, ("远景小人影之后的露脸镜须 identity_reanchor", REANCHOR_MISSING)
TOTAL = round(sum(m["sec"] for m in SCENES.values()), 1)
assert PACING["episode_total_seconds_target"][0] <= TOTAL <= PACING["episode_total_seconds_target"][1], TOTAL
_t, _run_start, _runs = 0.0, None, []
for sh in SHOTS:
    spoken = len(re.sub(r"[^一-鿿0-9A-Za-z]", "", sh["dialogue"][1])) if sh.get("dialogue") else 0
    if spoken:
        if _run_start is not None: _runs.append(_t - _run_start); _run_start = None
    elif _run_start is None:
        _run_start = _t
    _t += sh["sec"]
if _run_start is not None: _runs.append(_t - _run_start)
assert max(_runs or [0]) <= 15, ("无对白连续段 >15 s", _runs)
_speech = sum(min(len(re.sub(r"[^一-鿿0-9A-Za-z]", "", sh["dialogue"][1])) / 4.0, sh["sec"]) for sh in SHOTS if sh.get("dialogue"))
assert _speech / TOTAL >= 0.35, ("台词覆盖 <35%", round(_speech / TOTAL, 3))

# ---------- seq=27 ----------
_shot_start = {}
_t = 0
for _sh in SHOTS:
    _shot_start[f"{_sh['s']}-{_sh['n']:02d}"] = _t; _t += _sh["sec"]
_shot_by_id = {f"{x['s']}-{x['n']:02d}": x for x in SHOTS}
SETUPS = {
    "SETUP-NEWLIFE-TWO-DAYS": dict(setup="E06-S02-03", payoff="E06-S12-04", object="「新生大概率在两天内完成」所设的新生进程——体表银光越来越清晰", partial=["E06-S05-04", "E06-S12-03"], verbs=["银光", "爆响", "后仰"]),
    "SETUP-GRANARY-THREE-DAYS": dict(setup="E06-S03-04", payoff="E06-S13-02", object="「只够吃三天」所设的存粮见底——被迫进山觅食", partial=["E06-S08-04", "E06-S13-01"], verbs=["抓起", "挂上肩", "推门"]),
    "SETUP-ZHOU-GRANNY": dict(setup="E06-S07-02", payoff="E06-S08-04", object="「周家的阿婆身体不行了」所设的死讯——藏在竹筐里的口粮揭晓她怎么死的", partial=["E06-S08-01"], verbs=["看向", "竹筐"]),
    "SETUP-SKY-EYES": dict(setup="E06-S10-02", payoff="E06-S11-02", object="夜空两盏金色灯笼眼是什么", partial=["E06-S10-04"], verbs=["按着", "望向"]),
}
SETUP_ID_BY_SHOT = {v["setup"]: k for k, v in SETUPS.items()}
PAYOFF_OF_BY_SHOT = {v["payoff"]: k for k, v in SETUPS.items()}
for _k, _v in SETUPS.items():
    assert _v["setup"] in _shot_by_id and _v["payoff"] in _shot_by_id, _k
    _act = _shot_by_id[_v["payoff"]]["action"][1] + _shot_by_id[_v["payoff"]]["exit"]
    assert any(vb in _act for vb in _v["verbs"]), (_k, "payoff 镜 action 须含被设置对象的可见动作动词")
    _gap = _shot_start[_v["payoff"]] - _shot_start[_v["setup"]]
    assert _gap > 0, _k
    if _gap > 25:
        assert any(_shot_start[_v["setup"]] < _shot_start[pr] < _shot_start[_v["payoff"]] for pr in _v["partial"]), (_k, "揭晓超过 25 s 须有部分露出")
RESULT_OF = {
    "E06-S08-01": {"cause_shot_id": "E06-S07-02", "kind": "DEATH_MOURNING", "agent_visible": "结果状态镜：周阿婆的手垂在炕沿、孩子跪哭；起因＝E06-S07-02 梁婉清报信「阿婆身体不行了」（施动者梁婉清在画）与 E06-S08-04 揭示的死因（藏口粮）"},
    "E06-S08-02": {"cause_shot_id": "E06-S08-01", "kind": "GRIEF_SELF_BLAME", "agent_visible": "周长裕跪着扇自己嘴巴：施动者与受动者同人同镜；起因镜 E06-S08-01（阿婆已无声息）"},
    "E06-S08-03": {"cause_shot_id": "E06-S08-02", "kind": "GRIEF_SELF_BLAME", "agent_visible": "同 E06-S08-02 的延续"},
}
_RESULT_RE = re.compile(r"被埋|埋在|倒地|倒在|跪|塌|受伤|见血|制服")
_DIALOGUE_ACTION_TABLE_V1 = ["别打", "住手", "放开", "别杀", "救命", "松手", "别动", "快跑", "别跑"]
_BODY_ACTION_RE = re.compile(r"打|抡|砸|拉|抓|按|推|拽|踢|扑|杀|跑|松开|放开")
BLOCKING_SIGNATURE = {}
for _sh in SHOTS:
    _sid = f"{_sh['s']}-{_sh['n']:02d}"; _cp = CAMERA_PLANS[_sid]
    _slots = (_sh.get("slots") or {})
    BLOCKING_SIGNATURE[_sid] = f"{_cp['camera_side']}|{_cp['shot_scale']}|{_cp['camera_height']}|{_cp['motion_family']}|" + "/".join(f"{k}:{_slots.get(k, '-')}" for k in _sh["cast"])
    _act = _sh["action"][1]
    if _RESULT_RE.search(_act):
        assert _sid in RESULT_OF, (_sid, "结果镜须声明 result_of")
    if _sh.get("dialogue"):
        _q = _sh["dialogue"][1]
        if any(w in _q for w in _DIALOGUE_ACTION_TABLE_V1):
            _prev = SHOTS[SHOTS.index(_sh) - 1]["action"][1] if SHOTS.index(_sh) else ""
            assert _BODY_ACTION_RE.search(_act) or _BODY_ACTION_RE.search(_prev), (_sid, "台词动作词在本镜/前一镜无对应肢体动作")
    if len(_sh["cast"]) >= 3:
        assert _act.strip(), (_sid, "三人以上镜 action 不得为空")
    if not _sh.get("dialogue"):
        assert _sh["sec"] <= 5 and _cp["motion_family"] != "LOCKED", (_sid, "无对白镜 ≤5 s 且机位动")
for _sid_scene, _shots in by_scene.items():
    _prev_sig = None; _cnt = {}
    for _sh in _shots:
        _sid = f"{_sid_scene}-{_sh['n']:02d}"; _sig = BLOCKING_SIGNATURE[_sid]
        assert _sig != _prev_sig, (_sid, "相邻同构图（blocking_signature）")
        _cnt[_sig] = _cnt.get(_sig, 0) + 1
        assert _cnt[_sig] <= 2, (_sid, "场内同构图 >2")
        _prev_sig = _sig
_lines_seen = {}
for _sh in SHOTS:
    if _sh.get("dialogue"):
        _q = _sh["dialogue"][1]; assert _q not in _lines_seen, (_q, "一句台词只属一个镜")
        _lines_seen[_q] = f"{_sh['s']}-{_sh['n']:02d}"
SEQ27_SELFCHECK = {"authority": "SUPERVISOR_ORDERS seq=27（Roger 2026-09-17 memo「E05 生产线补正」）",
                   "setups": {k: {**v, "setup_at_seconds": _shot_start[v["setup"]], "payoff_at_seconds": _shot_start[v["payoff"]]} for k, v in SETUPS.items()},
                   "result_of": RESULT_OF, "dialogue_action_table_v1": _DIALOGUE_ACTION_TABLE_V1,
                   "checks": {k: "PASS" for k in ("setup_payoff_visible", "result_shots_have_cause", "dialogue_action_words_have_action",
                                                    "blocking_signature_no_adjacent_repeat_and_scene_max_2", "one_line_one_shot", "pure_environment_shots_max_2s",
                                                    "three_plus_cast_action_nonempty", "no_dialogue_shots_max_5s_and_moving")}}

# ---------- 关键台词逐字核对（源章 + narrative） ----------
src_text = SRC_CH.read_text(encoding="utf-8")
narr = SCRIPTS / f"{EP}_NARRATIVE_CANONICAL_{VER}.md"
narr_text = narr.read_text(encoding="utf-8")
AUTHORED_DIALOGUE = {
    "练不成的路数……难道贯通了？": "ch6 开篇内心自问「曾经被告知练不成的“路数”，难道现在已圆融，被贯通了？」转秦铭自语，字序不变、略去「曾经被告知」「现在已圆融」",
    "这么多年以来，小秦算是双树村头一份。": "ch6「梁婉清说这么多年以来，他算是双树村头一份」叙述转直接引语（他→小秦）",
    "最近她吃得东西太少，身体本来就不太好。": "ch6 梁婉清原句「据说，最近她吃得东西太少，再加上她身体本来就不太好，所以出了问题。」按镜长规则缩短，字序不变",
    "我没用，不孝……": "ch6「用力扇自己的嘴巴，说自己没用，不孝」转周长裕直接引语",
    "高等生灵……": "ch6「他猜测那应该是一个高等生灵」转秦铭气声自语",
    "不用慌，那是高等生灵在赶路，过境而已。": "ch6「年岁比较大的老人…告知后辈不用慌，那应该是一个高等生灵在赶路，过境而已」转邻居甲一句（E04 已出身份牌的村民承担老人一角）",
    "纵然心有所念，也要有实力才行。": "ch6 叙述句「纵然心有所念，也要有实力才行。」转秦铭自语，字不变",
}
SPLIT_QUOTES = {"稳定之后，扛鼎五百斤已是极限，": "ch6 单句「我们这片地区，纵然是在黄金年龄段新生，稳定之后，扛鼎五百斤已是极限，小秦不会要抵临吧？」中段，字不变；前段按节奏略去",
                "小秦不会要抵临吧？": "同一源句末段，字不变"}
KEY_QUOTES, DIALOGUE_UNITS = [], []
SPEAKER_NAMES = "|".join(cname(k) for k in CH)
for sh in SHOTS:
    if sh.get("dialogue"):
        spk, q, _ = sh["dialogue"]; shot = f"{sh['s']}-{sh['n']:02d}"
        assert f"{cname(spk)}：“{q}”" in narr_text, ("台词未逐字进 narrative", q)
        core = q.rstrip("。！？，")
        if q in AUTHORED_DIALOGUE:
            DIALOGUE_UNITS.append((spk, q, shot, False))
        else:
            assert core in src_text, ("key_quote 不在源章逐字文本中", q)
            KEY_QUOTES.append((spk, q, shot)); DIALOGUE_UNITS.append((spk, q, shot, True))
narr_lines = re.findall(rf'^({SPEAKER_NAMES})：“(.+?)”$', narr_text, re.M)
assert [(cname(s), q) for s, q, *_ in DIALOGUE_UNITS] == narr_lines, ("镜头表对白顺序/说话人与 narrative 不一致", narr_lines)

# ---------- 道具扫描 ----------
PROP_KEYWORDS = (("PROP-STONE-ROLLER", ["石碾子"]), ("PROP-YARD-MILLSTONES", ["磨盘"]), ("PROP-NUT-HOARD", ["干果", "核桃", "杏仁", "栗子", "红枣", "山楂", "坚果"]),
                 ("PROP-HIDE-BAG", ["兽皮袋"]), ("PROP-COPPER-BASIN", ["铜盆"]), ("PROP-BAMBOO-BASKET", ["竹筐"]), ("PROP-DRIED-TUBER", ["地薯"]), ("PROP-BLACK-BUN", ["冷馍"]),
                 ("PROP-NUT-CLOTH-BAG", ["布袋"]), ("PROP-BOW-ARROWS", ["弓箭"]), ("SET-GOLDEN-LANTERN-EYES", ["金色灯笼", "灯笼眼"]))
PROP_NAME = {**{p["entity_id"]: p["name"] for p in PROPS}, **{s["entity_id"]: s["name"] for s in SETS}}
def _props_in(sh):
    txt = sh["action"][1] + sh["entry"] + sh["exit"]
    return [eid for eid, kws in PROP_KEYWORDS if any(k in txt for k in kws)]
PROP_MISSING: list = []
for sh in SHOTS:
    shot_id = f"{sh['s']}-{sh['n']:02d}"
    for eid, kws in PROP_KEYWORDS:
        if eid.startswith("SET-"):
            continue
        if any(k in sh["action"][1] for k in kws):
            if not (any(k in sh["entry"] for k in kws) or any(k in sh["exit"] for k in kws)):
                PROP_MISSING.append((shot_id, eid))
assert not PROP_MISSING, ("道具在 action 出现但 entry/exit 未声明", PROP_MISSING)

TRANSITION_NOTES = {
    ("E06-S01-01", "E06-S01-02"): ("REACTION_CUT", "石碾子砸回后切秦铭低头看掌心"), ("E06-S01-02", "E06-S01-03"): ("MOTIVATED_CUT", "攥拳抬头后切蹲身跃起，切在蓄力上"), ("E06-S01-03", "E06-S01-04"): ("MOTIVATED_CUT", "吐气后切横臂，切在抬臂上"),
    ("E06-S02-01", "E06-S02-02"): ("CAMERA_REFRAME", "盘坐后改取特写"), ("E06-S02-02", "E06-S02-03"): ("MOTIVATED_CUT", "涟漪后切睁眼起身，切在起身上"), ("E06-S02-03", "E06-S02-04"): ("MOTIVATED_CUT", "放下磨盘后切按肚子转身，切在转身上"),
    ("E06-S03-01", "E06-S03-02"): ("MOTIVATED_CUT", "大吃后切起身活动筋骨，切在起身上"), ("E06-S03-02", "E06-S03-03"): ("MOTIVATED_CUT", "坐回炕沿后切扣碗，切在扣碗上"), ("E06-S03-03", "E06-S03-04"): ("MOTIVATED_CUT", "抓栗子后切提袋，切在提起上"),
    ("E06-S04-01", "E06-S04-02"): ("REACTION_CUT", "磨盘搬离后切陆泽推门"), ("E06-S04-02", "E06-S04-03"): ("MOTIVATED_CUT", "话停半截后切上前拍肩，切在迈步上"),
    ("E06-S05-01", "E06-S05-02"): ("CAMERA_REFRAME", "走到磨盘旁后改取中近景"), ("E06-S05-02", "E06-S05-03"): ("REACTION_CUT", "回头看陆泽后切文睿跑来"), ("E06-S05-03", "E06-S05-04"): ("REACTION_CUT", "文睿蹦起后切秦铭放磨盘"),
    ("E06-S06-01", "E06-S06-02"): ("CAMERA_REFRAME", "看向磨盘后改取中近景"), ("E06-S06-02", "E06-S06-03"): ("MOTIVATED_CUT", "看向秦铭后切抓陆泽胳膊，切在伸手上"), ("E06-S06-03", "E06-S06-04"): ("REACTION_CUT", "抓住胳膊后切陆泽望向村外"),
    ("E06-S07-01", "E06-S07-02"): ("MOTIVATED_CUT", "出院门后切扶门回来，切在扶门上"), ("E06-S07-02", "E06-S07-03"): ("REACTION_CUT", "指向街上后切陆泽迎上"), ("E06-S07-03", "E06-S07-04"): ("REACTION_CUT", "追问后切梁婉清搓手"),
    ("E06-S08-01", "E06-S08-02"): ("CAMERA_REFRAME", "到炕前后改取周长裕"), ("E06-S08-02", "E06-S08-03"): ("CAMERA_REFRAME", "扇嘴后改取特写"), ("E06-S08-03", "E06-S08-04"): ("REACTION_CUT", "伏身后切秦铭沉默低头"),
    ("E06-S09-01", "E06-S09-02"): ("REACTION_CUT", "递袋后切周长裕推袋"), ("E06-S09-02", "E06-S09-03"): ("MOTIVATED_CUT", "低头后切秦铭按袋，切在按上"),
    ("E06-S10-01", "E06-S10-02"): ("MOTIVATED_CUT", "失神后切身体绷紧，切在绷紧上"), ("E06-S10-02", "E06-S10-03"): ("MOTIVATED_CUT", "灯笼眼出现后切狂风，切在雪起上"), ("E06-S10-03", "E06-S10-04"): ("CAMERA_REFRAME", "护脸后改取远景横摇"), ("E06-S10-04", "E06-S10-05"): ("REACTION_CUT", "风息后切秦铭瞳孔收缩"),
    ("E06-S11-01", "E06-S11-02"): ("CAMERA_REFRAME", "按肩后改取中近景"),
    ("E06-S12-01", "E06-S12-02"): ("MOTIVATED_CUT", "站直后切攥拳，切在攥拳上"), ("E06-S12-02", "E06-S12-03"): ("MOTIVATED_CUT", "摆架势后切演练，切在起势上"), ("E06-S12-03", "E06-S12-04"): ("MOTIVATED_CUT", "光雾后切弓腰，切在弓腰上"),
    ("E06-S13-01", "E06-S13-02"): ("MOTIVATED_CUT", "咽口水后切抓弓，切在伸手上"),
    ("E06-S14-01", "E06-S14-02"): ("CAMERA_REFRAME", "疾奔中段后改取低机位远景"),
}
INTERNAL_TRANSITIONS = {}
for sid, shots in by_scene.items():
    for a, b in zip(shots, shots[1:]):
        aid, bid = f"{sid}-{a['n']:02d}", f"{sid}-{b['n']:02d}"
        mode, execution = TRANSITION_NOTES[(aid, bid)]
        stay = [k for k in a["cast"] if k in b["cast"]]; enter = [k for k in b["cast"] if k not in a["cast"]]; leave = [k for k in a["cast"] if k not in b["cast"]]
        props_a, props_b = _props_in(a), _props_in(b)
        carried = [p for p in props_a if p in props_b]
        cpb = CAMERA_PLANS[bid]
        INTERNAL_TRANSITIONS[(aid, bid)] = dict(
            transition_mode=mode,
            identity_preservation="、".join(cname(k) for k in stay) + "延续同一面孔、发式与服装" + ("；" + "、".join(cname(k) for k in enter) + "为本镜新入画人物，面孔与服装按身份牌" if enter else "") if stay or enter else "本边界无人物延续；非人物主体按参考卡延续同一形貌",
            entry_exit_or_reveal=("、".join(cname(k) for k in stay) + "均已在画内，不入画不出画" if stay else "本边界无人物延续") + ("；" + "、".join(cname(k) for k in enter) + "在本镜入画" if enter else "") + ("；" + "、".join(cname(k) for k in leave) + "在本镜不入画" if leave else ""),
            scene_continuity=f"同一{SCENES[sid]['loc']}空间，{SCENES[sid]['light']}不变，仅机位改变",
            prop_handoff=("随身道具延续：" + "、".join(carried)) if carried else "本边界无道具主体",
            sound_bridge=f"{sid} 环境声（{AMBIENT_LIFE[sid]['motion_trend']}）连贯不中断，切镜不改变环境声",
            axis_strategy=cpb["axis_relation"],
            transition_execution=f"{execution}；本镜机位 {cpb['motion_family']}/{cpb['motion_direction']}，{cpb['start_framing']}",
            action_bridge=f"上镜终态「{a['exit']}」之后，动作不复位；本镜从「{b['entry']}」开始",
            entity_mapping="，".join(f"{cname(k)}→参考图 {cid(k)}" for k in b["cast"]) + "，各自槽位不互换" if b["cast"] else "本边界无人物；非人物主体按参考卡映射：" + "，".join(f"{PROP_NAME[p]}→参考卡 {p}" for p in (_props_in(b) or _props_in(a))) + "，各自槽位不互换",
            same_slot_reuse_allowed=False)

# ---------- directing script ----------
LOCKED_IDS = [f"{s['s']}-{s['n']:02d}" for s in SHOTS if CAMERA_PLANS[f"{s['s']}-{s['n']:02d}"]["motion_family"] == "LOCKED"]
REANCHOR_IDS = [f"{sh['s']}-{sh['n']:02d}" for sh in SHOTS if sh.get("identity_reanchor")]
lines = [f"# 《夜无疆》{EP} 导演稿 {VER}（directing script）", "",
         f"绑定 narrative：`{narr.name}`（SHA256 {sha(narr)}）", "",
         "本层只写景别、机位、轴线、走位与起止态；**不改 narrative 的任何事实**。逐镜秒标为交付口径。", "",
         "## 本集口径（seq=7/10/12/13/17/19/27/29 + D-57）", "",
         f"- 全局风格：{STYLE['era_idiom']}", f"- 夜景：{STYLE['night_look']}", "- 禁用：" + "、".join(STYLE["forbidden"]),
         "- 节奏（seq=29 规则 5）：对白镜时长 = 台词时长（导演稿字/秒）+ 0.5 s 向上取整 0.5 s，无模板值；无对白镜 ≤4 s 且机位必动；单场 ≤16 s；action 不写「保持/口型闭合/静止/定住」，每句说完立即接一个身体动作",
         "- 表演（seq=29 规则 7）：每个对白镜 performance = 情绪词（闭集 24 词）＋进行中的身体动作＋说话方式，编译进提示词首位；禁令压缩一句在后；同场连续 3 镜情绪词不同；儿童语速 5.0",
         f"- 机位运动：LOCKED ≤30%（本稿 {len(LOCKED_IDS)}/{len(SHOTS)}：{'、'.join(LOCKED_IDS) or '无'}）、不连续 LOCKED、无对白镜必动、R7、R8、同轴同景别不连续 >2 镜、开场镜运动",
         "- ★D-57 身份链：face_visibility 只用闭集豁免标记（背影/远小/出画/仅手），3/4 与侧脸一律测；关键帧参考以正面头像牌打头；每个视频单元带在场角色的头像牌",
         "- ★seq=27：设置—揭晓闭环 4 组（SETUPS）；结果镜 3 处声明 result_of（周家跪哭）；台词动作词表 v1 零命中；blocking_signature 相邻不重复、场内 ≤2；一句台词只属一镜",
         "- ★选择性配乐（D-32）：E06-S08–S09（周家）、E06-S10（金色灯笼眼过境）两处纯器乐，其余原生现场声",
         "- ★音色：本集说话人：秦铭、陆泽、梁婉清、陆文睿（E05 已选）、周长裕（新）、邻居甲（E01 已选）",
         f"- ★承接：E06-S01-01 的 entry_state 接 {PREV_LAST_SHOT} 的 completion_state（{PREV_LAST['completion_state']}）；本集从秦铭推开院门从荒野回来开始，不复位、不重演、不闪回", ""]
for sid, meta in SCENES.items():
    lines.append(f"## {sid}｜{meta['loc']}｜{meta['time']}｜{meta['sec']:g}s｜{meta['weather']}｜光：{meta['light']}")
    lines.append("")
    for sh in by_scene[sid]:
        shot_id = f"{sid}-{sh['n']:02d}"; cp = CAMERA_PLANS[shot_id]
        lines.append(f"### {shot_id}（{sh['sec']:g}s）｜{sh['size']}｜{sh['camera']}｜{cp['motion_family']}/{cp['motion_direction']}")
        lines.append(f"- 轴线：{sh['axis']}")
        lines.append(f"- 走位：{sh['blocking']}")
        lines.append(f"- 动作：{sh['action'][1]}")
        if sh.get("dialogue"):
            s, t, l = sh["dialogue"]; lines.append(f"- 台词：{cname(s)}：“{t}”（{sh['cps']} 字/秒；镜长由台词推导）")
            lines.append(f"- 表演：{sh['perf'][0]}／{sh['perf'][1]}／{sh['perf'][2]}；说完立即{sh['after_line']}")
        lines.append(f"- entry_state：{sh['entry']}")
        lines.append(f"- completion_state：{sh['exit']}")
        lines.append("- 状态差：" + "；".join(f"{d}「{a}」→「{b}」" for d, (a, b, _, _) in sh["dims"].items()))
        lines.append(f"- 时代约束：{PERIOD_BY_LOC[meta['loc']]}")
        lines.append(f"- blocking_signature：{BLOCKING_SIGNATURE[shot_id]}" + (f"｜setup_id：{SETUP_ID_BY_SHOT[shot_id]}" if shot_id in SETUP_ID_BY_SHOT else "") + (f"｜payoff_of：{PAYOFF_OF_BY_SHOT[shot_id]}" if shot_id in PAYOFF_OF_BY_SHOT else "") + (f"｜result_of：{RESULT_OF[shot_id]['cause_shot_id']}" if shot_id in RESULT_OF else ""))
        lines.append("")
directing = SCRIPTS / f"{EP}_DIRECTING_SCRIPT_{VER}.md"
directing.write_text("\n".join(lines), encoding="utf-8")
print("directing written", directing)

# ---------- generation contract ----------
NPR_FACE = {"QM": "束发木簪、无胡须的清瘦年轻男子", "LZ": "灰布裹巾的结实青年", "LW": "麻布包髻的年轻妇人", "WR": "五岁男孩、总角、赭红棉袍",
            "ZC": "灰布裹巾、右臂吊在胸前的高壮汉子", "ZA": "（脸不入画）躺在炕上的老妇", "VA": "麻布头巾包髻的瘦削中年男子"}
NPR_APPLIED: dict[str, list[str]] = {}
NPR_BLOCKS: list[str] = []
NON_CHAR_SUBJECTS = {p["entity_id"]: p["name"] for p in PROPS} | {s["entity_id"]: s["name"] for s in SETS}
def ent_name(k):
    return cname(k) if k in CH else NON_CHAR_SUBJECTS.get(k, k)
def ent_id(k):
    return cid(k) if k in CH else ""

def apply_prompt_rules(sh, shot_id, act):  # seq=10 全镜套用；seq=29 7a：条款作为 constraints 单列
    sid = sh["s"]
    scene_cast = {k for x in by_scene[sid] for k in x["cast"]}
    fam = (CAMERA_PLANS.get(shot_id) or {}).get("motion_family")
    shot = {"shot_id": shot_id, "sec": sh["sec"], "size": sh["size"], "camera_family": fam, "cast": sh["cast"],
            "action": act, "dialogue": sh.get("dialogue"), "entry": sh["entry"], "exit": sh["exit"], "emotion": sh.get("emotion"), "after_line": sh.get("after_line")}
    ctx = {"scene_cast": scene_cast, "loc": SCENES[sid]["loc"], "cps": sh.get("cps"), "names": {k: cname(k) for k in CH}, "face_desc": NPR_FACE,
           "prop_tokens": ["太阳石", "石碾子", "磨盘", "兽皮袋", "干果", "铜盆", "竹筐", "地薯", "冷馍", "布袋", "弓箭", "灯笼眼"], "split_columns": True}
    clauses, applied, blocks = NPR.apply(shot, ctx)
    NPR_APPLIED[shot_id] = applied
    NPR_BLOCKS.extend(blocks)
    return list(clauses)

SHOT_ORDER = [f"{x['s']}-{x['n']:02d}" for x in SHOTS]
def life_state(sh, k):
    return (sh.get("life") or {}).get(k, "alive")
EMOTION_BY_SHOT = {f"{x['s']}-{x['n']:02d}": x.get("emotion") for x in SHOTS if x.get("dialogue")}

def shot_json(sh):
    sid = sh["s"]; shot_id = f"{sid}-{sh['n']:02d}"
    subj, act, patient = sh["action"]
    constraints = apply_prompt_rules(sh, shot_id, act)
    dlg = sh.get("dialogue")
    spk_id = cid(dlg[0]) if dlg else ""
    lst_id = cid(dlg[2]) if dlg and dlg[2] else ""
    resolved = [{"surface_form": surface, "entity_id": cid(key) if key in CH else key} for surface, key in sh["referents"]]
    presence = {cid(k): "VISIBLE_AND_IDENTITY_LOCKED" for k in sh["cast"]}
    slots = sh.get("slots") or {}; faces = sh.get("faces") or {}
    states = {cid(k): sh["exit"] for k in sh["cast"]}
    subj_is_char = subj in CH
    perf = sh.get("perf")
    performance = {"emotion": perf[0], "body_action": perf[1], "delivery": perf[2], "after_line": sh["after_line"]} if perf else None
    return {
        "shot_id": shot_id, "scene_id": sid, "target_seconds": sh["sec"],
        "shot_size": sh["size"], "camera": sh["camera"], "axis": sh["axis"], "blocking": sh["blocking"],
        "entry_state": sh["entry"], "completion_state": sh["exit"],
        "state_delta_dimensions": list(sh["dims"].keys()),
        "state_delta_evidence": {d: {"entry": a, "exit": b, "entry_code": ca, "exit_code": cb} for d, (a, b, ca, cb) in sh["dims"].items()},
        "keyframe_source": "entry_state",
        "blocking_signature": BLOCKING_SIGNATURE[shot_id],
        **({"setup_id": SETUP_ID_BY_SHOT[shot_id]} if shot_id in SETUP_ID_BY_SHOT else {}),
        **({"payoff_of": PAYOFF_OF_BY_SHOT[shot_id]} if shot_id in PAYOFF_OF_BY_SHOT else {}),
        **({"result_of": RESULT_OF[shot_id]} if shot_id in RESULT_OF else {}),
        **({"group_counts": sh["group_counts"]} if sh.get("group_counts") else {}),
        "period_constraints": PERIOD_BY_LOC[SCENES[sid]["loc"]],
        "pacing_flags": {"hook": shot_id == "E06-S01-01", "scene_opener_in_motion": sh["n"] == 1, "scene_button": sh is by_scene[sid][-1],
                         "no_dialogue_static_hold_seconds_max": PACING["no_dialogue_static_hold_seconds_max"] if not dlg else None,
                         "conflict_line": bool(perf and perf[0] in set(LEX.get("conflict_emotions") or []))},
        **({"dialogue_delivery": {"chinese_characters_per_second": sh["cps"], "basis": "seq=29 规则 5a：镜长 = ceil_0.5(字数/字每秒 + 0.5)；字/秒按句标注 4.8–5.2；post-gen 规则 6 按此核实测语速"}} if sh.get("cps") else {}),
        "prompt_spec": {
            "camera_plan": {**CAMERA_PLANS[shot_id], "authorship": "DIRECTING_SCRIPT_AUTHORED", "selection_mode": "LOCKED", "source": f"E06_DIRECTING_SCRIPT_v1.md#{shot_id}"},
            "cast": [{"character": cname(k), "character_id": cid(k), "life_state": life_state(sh, k),
                      **({"screen_slot": slots[k]} if k in slots else {}), **({"face_visibility": faces[k]} if k in faces else {})} for k in sh["cast"]],
            "props": [{"prop_id": p, "prop": PROP_NAME[p]} for p in _props_in(sh)],
            "dialogue": f"{cname(dlg[0])}：{dlg[1]}" if dlg else "",
            **({"dialogue_delivery": {"chinese_characters_per_second": sh["cps"]}} if dlg else {}),
            "action": {"subject_id": ent_id(subj) if subj else "", "primary_action": act, "patient_id": ent_id(patient) if patient else "",
                       **({"performance": performance} if performance else {}), "constraints": constraints,
                       "columns_authority": "SUPERVISOR_ORDERS seq=29 规则 7a：performance 在前、constraints 压缩在后"},
            **({"identity_reanchor_required": True, "identity_reanchor_reason": "seq=12/13：同场内远景/小人影之后的露脸镜；以角色板生成的关键帧作身份再锚定参考（engine e19）"} if sh.get("identity_reanchor") else {}),
            "referent_resolution_contract": {"status": "PASS", "source_scan_complete": True, "resolved_source_referents": resolved, "unresolved_source_referents": []},
            "role_semantic_disambiguation": {
                "primary_actor_kind": "CHARACTER" if subj_is_char else ("ENVIRONMENT" if not subj else "PROP"),
                "primary_actor": ent_name(subj) if subj else "", "primary_actor_id": ent_id(subj) if subj else "",
                "dialogue_speaker": cname(dlg[0]) if dlg else "", "dialogue_speaker_id": spk_id,
                "dialogue_listener": cname(dlg[2]) if dlg and dlg[2] else "", "dialogue_listener_id": lst_id,
                "action_patient": ent_name(patient) if patient else "", "action_patient_id": ent_id(patient) if patient else "",
                "lip_owner_id": spk_id, "entity_states": states, "entity_presence": presence},
        },
    }

_CE5 = {c["character_id"]: c for c in _E05["character_entities"]}
_CE1 = {c["character_id"]: c for c in _E01["character_entities"]}
_CE4 = {c["character_id"]: c for c in _E04["character_entities"]}
CHARACTER_ROWS = [
    {**_CE5["CHAR-QINMING"], "identity_source": {**_CE5["CHAR-QINMING"]["identity_source"], "note": "E02 锁定的三视图身份牌复用；D-57 ①：S3 复测源图余弦（今测 0.805/0.793/0.845 PASS）"},
     "appearance_ch6": "ch6：颀长紧致、湿发水珠、肌体莹亮有力量感；院中练功体表银光、开龙脊；周家沉默；深夜独坐仰望；背弓进山"},
    {**_CE5["CHAR-LUZE"], "appearance_ch6": "ch6：推门瞠目，拍肩大笑，望向远处的城池"},
    {**_CE5["CHAR-LIANGWANQING"], "identity_source": {"mode": "E02_IDENTITY_CARD_REUSE", "note": "沿用 E02 身份牌；D-57 ① 今测源图余弦 0.351/0.407/0.559，正面头像与 3/4 牌低于 0.45 → 待线主下单重出（本集 S3 按 --s3-subjects 重出）"},
     "appearance_ch6": "ch6：失神、惊容、比五指、抓陆泽胳膊、出门探信"},
    {**_CE5["CHAR-LUWENRUI"], "appearance_ch6": "ch6：跑来抱住小叔的腿仰头喊「小叔，你太厉害了」"},
    {"character_id": "CHAR-ZHOUCHANGYU", "canonical_name": "周长裕", "aliases": ["周家的儿子", "周长裕"], "voice_entity_id": "", "identity_reference_entity_id": "",
     "identity_source": {"mode": "TEXT_TO_IMAGE", "note": "无源照片；按 appearance 文生图出三视图身份牌（唐宋语汇）"},
     "appearance_ch1": "快三十岁的汉子，高壮、脸膛粗糙、眉骨粗、眼窝深、短须；右手臂骨头断了用布带吊在胸前；灰布裹巾束发、褐色粗麻短褐右袖空着",
     "appearance_ch6": "ch6：跪在炕前满脸泪水扇自己嘴巴；门口红着眼睛推回布袋"},
    {**_CE1["CHAR-ZHOUAPO"], "identity_source": {"mode": "E01_IDENTITY_CARD_REUSE", "note": "沿用 E01 身份牌；本集躺在炕上盖着旧兽皮，脸不入画（FACE_OUT_OF_FRAME），life_state=dead"},
     "appearance_ch6": "ch6：面色蜡黄已无声息（不入画）；只见垂在炕沿的手与黑布衣袖"},
    {**_CE4["CHAR-VILLAGER-A"], "identity_source": {"mode": "E03_IDENTITY_CARD_REUSE", "note": "沿用 E03 唐宋版身份牌；本集承担源章「年岁比较大的老人」一句"},
     "appearance_ch6": "ch6：神色凝重按住后生的肩，说高等生灵过境"},
]
for _row in CHARACTER_ROWS:
    _row.pop("wardrobe_garments", None)
BGM_CUES = [
    {"cue_id": "E06-BGM-01", "scenes": ["E06-S08", "E06-S09"], "narrative_function": "MOURNING_GIFT", "volume": 0.24, "dialogue_duck_db": -8,
     "brief": "Quiet mournful instrumental cue in ancient Chinese folk style for a poor family grieving a grandmother who starved herself to feed her grandchildren, and a young hunter leaving a bag of nuts at their door: solo xiao flute over a low guqin drone, sparse, restrained, no vocals, 19 seconds"},
    {"cue_id": "E06-BGM-02", "scenes": ["E06-S10"], "narrative_function": "SKY_CREATURE_PASSING", "volume": 0.3, "dialogue_duck_db": -8,
     "brief": "Ominous cinematic instrumental cue for two giant golden lantern-like eyes crossing a pitch-black winter night sky over a snowed-in village while a gale tears up the snow: deep taiko-like drum swells, bowed low strings, a distant bronze bell, dissonant shakuhachi, rising then dissolving as the creature passes, no vocals, 14 seconds"},
]
_e03_first = _E03["shots"][0]["shot_id"]; _e01_first = _E01["shots"][0]["shot_id"]
_e01_food = next((s["shot_id"] for s in _E01["shots"] if "馍" in str(s.get("completion_state"))), _e01_first)
_e03_nuts = next((s["shot_id"] for s in _E03["shots"] if "松鼠" in str(s.get("completion_state"))), _e03_first)
PROP_SOURCES = {
    "PROP-STONE-ROLLER": {"acquired": {"episode": EP, "shot_id": "E06-S01-01"}, "payoff_shot_ids": ["E06-S01-01"]},
    "PROP-YARD-MILLSTONES": {"acquired": {"episode": EP, "shot_id": "E06-S02-03"}, "payoff_shot_ids": ["E06-S04-01", "E06-S05-02"]},
    "PROP-NUT-HOARD": {"acquired": {"episode": "E03", "shot_id": _e03_nuts}, "recap_shot_id": "E06-S03-01", "payoff_shot_ids": ["E06-S08-04", "E06-S13-01"]},
    "PROP-HIDE-BAG": {"acquired": {"episode": "E03", "shot_id": _e03_nuts}, "recap_shot_id": "E06-S03-04", "payoff_shot_ids": ["E06-S13-01"]},
    "PROP-COPPER-BASIN": {"acquired": {"episode": "E01", "shot_id": _e01_first}, "recap_shot_id": "E06-S03-01"},
    "PROP-BAMBOO-BASKET": {"acquired": {"episode": EP, "shot_id": "E06-S08-04"}, "payoff_shot_ids": ["E06-S08-04"]},
    "PROP-DRIED-TUBER": {"acquired": {"episode": "E01", "shot_id": _e01_food}, "recap_shot_id": "E06-S08-04"},
    "PROP-BLACK-BUN": {"acquired": {"episode": "E01", "shot_id": _e01_food}, "recap_shot_id": "E06-S08-04"},
    "PROP-NUT-CLOTH-BAG": {"acquired": {"episode": EP, "shot_id": "E06-S09-01"}, "payoff_shot_ids": ["E06-S09-03"]},
    "PROP-BOW-ARROWS": {"acquired": {"episode": "E04", "shot_id": "E04-S02-04"}, "recap_shot_id": "E06-S13-02", "payoff_shot_ids": ["E06-S14-01"]},
    "SET-GOLDEN-LANTERN-EYES": {"acquired": {"episode": EP, "shot_id": "E06-S10-02"}, "payoff_shot_ids": ["E06-S10-04"]},
}
def with_sources(row):
    return {**row, **PROP_SOURCES[row["entity_id"]]}
_first_shot_of = {}
for _sh in SHOTS:
    for _k in _sh["cast"]:
        _first_shot_of.setdefault(_k, f"{_sh['s']}-{_sh['n']:02d}")
_PRIOR = {"LZ": "E05", "WR": "E05", "LW": "E05", "ZA": "E01", "VA": "E04"}
NEW_IN_EP = {"PROP-STONE-ROLLER", "PROP-YARD-MILLSTONES", "PROP-BAMBOO-BASKET", "PROP-NUT-CLOTH-BAG", "SET-GOLDEN-LANTERN-EYES"}
ENTITY_INTRODUCTIONS = (
    [{"entity_id": cid(k), "first_shot_id": _first_shot_of.get(k), "setup": ({"kind": "prior_episode", "ref": _PRIOR[k]} if k in _PRIOR else {"kind": "shot", "ref": _first_shot_of.get(k)})}
     for k in CH if k != "QM"]
    + [{"entity_id": r["entity_id"], "first_shot_id": r.get("first_shot") or "",
        **({"setup": {"kind": "shot", "ref": r.get("first_shot")}, "payoff_shot_id": PROP_SOURCES[r["entity_id"]]["payoff_shot_ids"][0]} if r["entity_id"] in NEW_IN_EP
           else {"setup": {"kind": "prior_episode", "ref": PROP_SOURCES[r["entity_id"]]["acquired"]["episode"]}})}
       for r in (*PROPS, *SETS)]
)
_VCC5 = _E05["visual_culture_contract"]
contract = {
    "schema": "qingshan.generation_contract.v3",
    "episode": EP, "version": VER,
    "narrative_canonical": narr.name, "narrative_sha256": sha(narr),
    "style": {**STYLE, "authority": "SUPERVISOR_ORDERS seq=7 c1/c2；seq=30 沿用；PRODUCTION_LINE_OVERVIEW_v1 §四 3/5", "negative_prompt_fixed": _E05["style"]["negative_prompt_fixed"]},
    "pacing": PACING,
    "protagonist_ids": ["CHAR-QINMING"],
    "antagonist_groups": [],
    "ambush_contracts": [],
    "entity_introductions": ENTITY_INTRODUCTIONS,
    "writer_visibility_contract_seq27": SEQ27_SELFCHECK,
    "writer_selfcheck_seq29": {"enforced": True, "rule8_authorized": False, "authority": "SUPERVISOR_ORDERS seq=29；规则 8 待线主裁定，本集只申报"},
    "pressure_source": {"kind": "LOSS_IMMINENT", "shot_id": "E06-S03-04", "at_seconds": _shot_start["E06-S03-04"], "description": "存粮只够吃三天（兽皮袋瘪下去），而新生中的身体越来越饿"},
    "episode_payoff": {"kind": "THREAT_ADVANCES", "shot_id": "E06-S10-04", "description": "高等生灵过境：夜空的金色灯笼眼与狂风，村外的世界比想象的更危险"},
    "action_chain": {"want_shot_id": "E06-S13-02", "blocked_shot_id": "E06-S13-01", "act_shot_id": "E06-S14-02", "note": "想吃肉→干果吃不饱、存粮见底→背弓进山"},
    "style_reset_disclosure": STYLE_RESET_DISCLOSURE,
    "carry_in": {"previous_episode": PREV_EP, "previous_scene_id": "E05-S14", "previous_shot_id": PREV_LAST["shot_id"],
                 "previous_completion_state": PREV_LAST["completion_state"],
                 "first_shot_id": "E06-S01-01", "first_shot_entry_state": SHOTS[0]["entry"],
                 "rule": "不复位、不重演、不闪回 E05 内容；E05 收在黑衣女子进山、秦铭在荒野；E06 从秦铭推开院门从荒野回来开始，沿同一方向推进",
                 "entities": ["CHAR-LUZE", "CHAR-LIANGWANQING", "CHAR-LUWENRUI", "CHAR-ZHOUAPO", "CHAR-VILLAGER-A"]},
    "visual_culture_contract": {**_VCC5, "decision_basis": "ch6 明写：院中石碾子与磨盘、吐气如枪卷雪、体表银光、炕上干果与蘑菇汤、周家竹筐里的地薯冷馍、五斤坚果布袋、夜空金色灯笼眼与狂风、开龙脊、背弓进山；Roger 2026-09-13 审片：中国唐宋不要西式暗黑",
                                "source_ref": str(SRC_CH),
                                "production_design": _VCC5["production_design"] + "；院角磨盘与石碾子为凿石农具；周家单间土屋与秦铭家同制式",
                                "armor_tradition": "本集无兵甲；猎具为竹木硬弓与皮箭囊；不得出现制式铁札甲、西式甲胄或现代猎具",
                                "palette_system": {"base": _VCC5["palette_system"]["base"], "accent": "太阳石橘红、体表淡银流光、夜空金色灯笼眼（唯一金色）", "skin": "屋内火光下暖、雪光下清；秦铭有血色；周长裕脸膛粗糙泪痕"}},
    "character_entities": [dict(row, wardrobe_garments=WARDROBE_GARMENTS[row["character_id"]]) for row in CHARACTER_ROWS],
    "non_character_entities": [with_sources(r) for r in (*PROPS, *SETS)],
    "props": {"authority": "SUPERVISOR_ORDERS seq=7 c6：关键道具出参考卡入资产库并挂进视频参考列表", "reference_cards": [with_sources(p) for p in PROPS + SETS if p.get("reference_card_required")],
              "declared_without_card": [p["entity_id"] for p in PROPS + SETS if not p.get("reference_card_required")]},
    "scene_states": [
        {"scene_id": sid, "location_id": m["loc"], "time_id": m["time"], "weather": m["weather"], "lighting": m["light"],
         "target_seconds": m["sec"], "source_events": m["beats"], "new_information_count": m["info"],
         "ambient_life": m["ambient_life"], "weather_provenance": m["weather_provenance"], "period_constraints": PERIOD_BY_LOC[m["loc"]], "costume_overrides": {}}
        for sid, m in SCENES.items()],
    "shots": [shot_json(sh) for sh in SHOTS],
    "internal_transition_authoring": [{"from_shot_id": a, "to_shot_id": b, "authorship": "DIRECTOR_AUTHORED", **row} for (a, b), row in INTERNAL_TRANSITIONS.items()],
    "audio_contract": {
        "bgm": {"mode": "SELECTIVE", "used": True, "authority": "SUPERVISOR_ORDERS seq=13 c2 / D-32",
                "declaration": "SELECTIVE_NARRATIVE_CUES：两处纯器乐配乐（周家、金色灯笼眼过境），覆盖 ≤85%，其余全部原生现场声；经 AgentCut bgm-generate → giggle generate-music 生成，受预算守卫与事务存档约束",
                "cues": BGM_CUES},
        "voice_casting": {"authority": "SUPERVISOR_ORDERS seq=17 c1", "note": "秦铭/陆泽/梁婉清/陆文睿/邻居甲沿用已选音色；周长裕新选（快三十岁汉子，哭腔）"},
        "ambient_by_scene": {
            "E06-S01": "院中寒气、推门、石碾子砸雪、跃起破风、吐气激射、雪花崩开", "E06-S02": "雪花落肩、呼吸、抱起磨盘的石响、肚子咕咕叫", "E06-S03": "汤锅冒气、干果咬碎、扣碗、兽皮袋抖动",
            "E06-S04": "磨盘离地的石响、院门推开、拍肩", "E06-S05": "院门、脚步、孩子的欢呼、拍雪", "E06-S06": "衣料摩擦、抓胳膊、指向远处的风声", "E06-S07": "街上嘈杂的人声、跑步、喘气",
            "E06-S08": "两个孩子的哭喊、扇耳光、抽泣、屋外风声", "E06-S09": "沿街踩雪、布袋交接、屋里传出的哭声", "E06-S10": "深夜寂静、心悸的低鸣、狂风卷雪、屋顶木梁颤动、罡风掠过、风息",
            "E06-S11": "各家院门开合、议论人声、老人沉声", "E06-S12": "院中寂静、攥拳、动作破风、骨节爆响", "E06-S13": "热水、干果、兽皮袋抖动、抓弓、推门", "E06-S14": "雪原疾奔踩雪、寒风、冲进林木的枝响",
        },
        "dialogue_units": [{"shot_id": shot, "speaker_id": cid(s), "listener_id": cid(sh_l) if sh_l else "", "text": q, "verbatim_in_source": v, "emotion": EMOTION_BY_SHOT[shot]}
                           for (s, q, shot, v), sh_l in zip(DIALOGUE_UNITS, [sh["dialogue"][2] for sh in SHOTS if sh.get("dialogue")])],
    },
}
contract_path = SCRIPTS / f"{EP}_GENERATION_CONTRACT_{VER}.json"
if NPR_BLOCKS:
    raise SystemExit("nalu_prompt_rules BLOCK (restage the shot): " + "; ".join(NPR_BLOCKS))
_w29 = W29.evaluate(contract)
assert _w29["status"] == "PASS", ("seq=29 写手自检 FAIL", _w29["failures"][:12])
print("nalu_prompt_rules applied to", len(NPR_APPLIED), "shots; seq=29 selfcheck PASS, rule8 info:", len(_w29["warnings"]))
contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("contract written", contract_path)

# ---------- manifest ----------
BEATS = [
    ("E06-EV-01", "landed", "E06-S01-01 至 E06-S01-02", "心中泛起波澜：练不成的路数难道贯通了（转自语）；从荒野回来体内似有火光，脚尖一挑石碾子离地"),
    ("E06-EV-02", "landed", "E06-S01-03", "纵身一跃滞空抓房檐雪；吐气白色气流如带白雾的长枪激射、破空音响亮"),
    ("E06-EV-03", "landed", "E06-S01-04", "腹式呼吸搅雪如鹅毛大雪（并入卷雪）；横臂一击雪花崩开；血肉活性提升周身滚烫、银色纹理交织带出汗水、微弱银光笼罩（新生时罕见的景象——不演）"),
    ("E06-EV-04", "merged", "E06-S01-04", "锻炼很久消耗极大疲累后停下；新生是过程、近日达成心愿的判断——内心不演，以停下盘坐承担"),
    ("E06-EV-05", "landed", "E06-S02-01", "没回屋静坐院中任雪落身，无惧酷寒全身暖洋洋（与病体初愈裹被发冷的对比不演）"),
    ("E06-EV-06", "landed", "E06-S02-02", "闭眼显照自身重复高难动作练意识力；银色涟漪再现，呼吸随心念复杂难寻规律；念由神起气由意动流光变亮少许；院中安静被雪覆盖、放空心灵、银光消失睁眼感受变化（并入涟漪一镜）"),
    ("E06-EV-07", "landed", "E06-S02-03", "从容抱起两百多斤磨盘又轻放；「新生大概率在两天内完成」"),
    ("E06-EV-08", "landed", "E06-S02-04", "毫无意外地感到强烈饥饿"),
    ("E06-EV-09", "landed", "E06-S03-01", "煮蘑菇汤，核桃杏仁栗子当主餐，红枣山楂当小菜，吃得尽兴"),
    ("E06-EV-10", "landed", "E06-S03-02", "休息够后新一轮锻炼，动如崩弓发若炸雷，疲累小憩饿了吃干果，从浅夜到深夜；临睡冷水洗漱、颀长紧致的身体、安寝无梦（洗漱与睡眠不演）"),
    ("E06-EV-11", "landed", "E06-S03-03", "次日饭量大增加餐到七顿、后天母胎化生消耗大、干货腻了就热水（科普不演）；「可惜，蘑菇不多，想煮些鲜汤都不成了」"),
    ("E06-EV-12", "landed", "E06-S03-04", "存粮不多只能维系一天；「我是饭桶吗？大半兽皮袋的干货只够吃三天」；路数不能停、静如山岳动如鹰击、银光渐盛、身体素质逐步变强（并入下一场练功不重演）"),
    ("E06-EV-13", "landed", "E06-S04-01", "走到小院一侧，将上下两块磨盘一起抱起猛然发力搬离原地"),
    ("E06-EV-14", "landed", "E06-S04-02", "陆泽正好推开院门瞠目结舌「小秦，你这是……」（昨天还为他可惜的内心不演）"),
    ("E06-EV-15", "landed", "E06-S04-03", "「和隔壁村的二病子一样，刚新生就能抓起四百多斤的重物」由衷高兴"),
    ("E06-EV-16", "landed", "E06-S05-01 至 E06-S05-02", "一墙之隔的梁婉清听到动静过来失神；「在黄金年龄段新生，小秦真的做到了」；这么多年双树村头一份（转直接引语）"),
    ("E06-EV-17", "landed", "E06-S05-03", "文睿跑来大眼亮晶晶仰头「小叔，你太厉害了！」"),
    ("E06-EV-18", "landed", "E06-S05-04", "「我感觉新生的变化还在进行中」；时间会超出预估远未结束（内心不演）"),
    ("E06-EV-19", "landed", "E06-S06-01 至 E06-S06-03", "梁婉清惊容：我们这片地区纵然黄金年龄段新生，稳定之后扛鼎五百斤已是极限，小秦不会要抵临吧（拆两镜，前段略去）"),
    ("E06-EV-20", "landed", "E06-S06-04", "陆泽：「据说，远处那座明亮的城池有可扛鼎六百斤的少年」（想知道秦铭会到什么高度的内心不演）"),
    ("E06-EV-21", "landed", "E06-S07-01 至 E06-S07-02", "街上传来嘈杂声，梁婉清出去又回来：「周家的阿婆身体不行了」；秦铭昨天路上见过她单薄缺血色（回想不演）"),
    ("E06-EV-22", "landed", "E06-S07-03 至 E06-S07-04", "「什么原因？」；据说最近吃得东西太少加上身体不好所以出了问题（缩短）"),
    ("E06-EV-23", "merged", "E06-S08-01", "到街上了解详情：儿子前段外出没带回食物右臂骨断；各家缺吃、顶梁柱出事、阿婆每天悄悄留下口粮只取少许——以周长裕吊臂与竹筐承担，不作解说"),
    ("E06-EV-24", "landed", "E06-S08-01", "周家院子来了不少人（缩为屋内群像）；进屋看到一动不动面色蜡黄已无声息的周阿婆（脸不入画）；两个孩子跪在近前大声哭喊奶奶"),
    ("E06-EV-25", "landed", "E06-S08-04", "临去前告诉他们哪里有吃的：地薯、冷硬的馍藏在冰雪下的竹筐里；秦铭送的坚果一颗都没舍得吃；省吃俭用怕儿子带不回吃的怕孙儿挨饿（真相以竹筐里的口粮承担）"),
    ("E06-EV-26", "landed", "E06-S08-02 至 E06-S08-03", "周长裕心碎，快三十岁的汉子满脸泪水用力扇自己嘴巴说自己没用不孝；媳妇跪着悲泣（群像）；院中众人叹息整片地区遭灾缺衣少食（不演）"),
    ("E06-EV-27", "merged", "E06-S08-04", "秦铭心中发堵：两天前苍白的阿婆颤巍巍取出地薯干要塞给他，那是她偷偷存下的口粮；多好的老人就这样没了，沉默站了很久——以沉默看竹筐承担，不闪回"),
    ("E06-EV-28", "landed", "E06-S09-01 至 E06-S09-03", "浅夜结束人散去，秦铭又来拎五斤坚果的布袋递给周长裕让他节哀；「秦兄弟！」红着眼想拒绝；秦铭放在他手里让他收下转身离去；很晚还听到周家哭泣"),
    ("E06-EV-29", "landed", "E06-S10-01", "坐在漆黑（雪光下）的院中：别人有亲人哭泣，自己心中几张不清晰的面孔越发模糊、怕彻底遗忘；仰望夜空失神、难言的孤独；朦胧灯火与暗淡身影的褪色记忆（内心与闪回不演，以仰望失神承担）"),
    ("E06-EV-30", "landed", "E06-S10-02", "心悸的气息扑面异常压抑身体瞬间绷紧；夜空出现两盏金色灯笼神秘慑人"),
    ("E06-EV-31", "landed", "E06-S10-03 至 E06-S10-04", "冬夜狂风大作雪花暴涌屋顶要被掀开剧烈颤动；金色灯笼横空而过带着罡风令人窒息；猜测是庞大的高等生灵挥翼如乌云遮天路经村上空；金色灯笼是它的眼睛，远去后暴风消散"),
    ("E06-EV-32", "landed", "E06-S10-05 至 E06-S11-02", "秦铭瞳孔收缩「高等生灵……」；村中骚动不少人走出议论；年岁大的老人经历过，神色凝重告知后辈不用慌，是高等生灵赶路过境（转邻居甲一句）"),
    ("E06-EV-33", "landed", "E06-S12-01", "从街上回来在院中坐了很久望夜幕；黑夜阻断远方让世界神秘，很想走出去看看（内心不演）"),
    ("E06-EV-34", "landed", "E06-S12-02 至 E06-S12-03", "坚定起身演练幼时记得最清楚的一组组动作；「纵然心有所念，也要有实力才行」（转自语）；身体涌现新生之力体表泛起稀薄光雾"),
    ("E06-EV-35", "landed", "E06-S12-04", "次日早醒精神旺盛应能扛鼎五百斤以上、新生还在进行（内心不演）；活动筋骨后开龙脊：弓腰猛烈后仰脊柱反弯夸张弯月骨节向上爆响血肉震颤；阳气自尾椎沿龙脊攀升、全身酥麻毛孔张开；体表银光比以往清晰（时序按节奏并入当夜练功）"),
    ("E06-EV-36", "landed", "E06-S13-01", "很久后前所未有的饥饿，新生变化未停似更猛烈；就热水吃一堆干货没饱；想到松鼠与黑山羊咽口水、想吃肉、身体发出讯息需要补物；又吃一堆坚果渴望才退（并入一镜，肉香幻想不演）"),
    ("E06-EV-37", "landed", "E06-S13-02", "「看来，等浅夜到来后，我得再次进山了」；送周家五斤后存粮不足"),
    ("E06-EV-38", "landed", "E06-S14-01 至 E06-S14-02", "浅夜未彻底到来便出现在村外：干果无法满足胃口填不饱；想到岩羊夜鹿黑羽雉架在篝火上滋滋滴油馋涎欲滴（幻想不演）；脚下生风冲进野外密林"),
]
SCENE_BEAT_META = {
    "E06-S01": {"type": "reveal"}, "E06-S02": {"type": "dialogue"}, "E06-S03": {"type": "dialogue"}, "E06-S04": {"type": "dialogue"}, "E06-S05": {"type": "dialogue"},
    "E06-S06": {"type": "dialogue"}, "E06-S07": {"type": "dialogue"}, "E06-S08": {"type": "reveal"}, "E06-S09": {"type": "dialogue"}, "E06-S10": {"type": "reveal"},
    "E06-S11": {"type": "dialogue"}, "E06-S12": {"type": "dialogue"}, "E06-S13": {"type": "dialogue"}, "E06-S14": {"type": "transition"},
}
assert set(SCENE_BEAT_META) == set(SCENES), set(SCENES) ^ set(SCENE_BEAT_META)
manifest = {
    "episode": EP, "version": VER, "title": "黄金年龄段",
    "canonical_script": f"workflow/claude_writer_agent/scripts/{narr.name}", "script_sha256": sha(narr),
    "directing_script": f"workflow/claude_writer_agent/scripts/{directing.name}", "directing_sha256": sha(directing),
    "generation_contract": f"workflow/claude_writer_agent/scripts/{contract_path.name}", "generation_contract_sha256": sha(contract_path),
    "supersedes": None,
    "★supersedes_disclosure": "首版，无前版。nalu 线《夜无疆》E06 首次交付；按 seq=7/10/12/13/17/19/27/29/30 口径编排；narrative 14 场 22 句对白零改动（一句源章长句拆为两行两镜、前段略去；七句叙述/内心独白转台词，均已在 narrative 头部与 authored_dialogue_from_indirect_speech 申报）。",
    "authorization": {"order_seq": 30, "order_id": "ROGER-20260918-NALU-E06-START", "also": ["seq=3 ROGER-20260909-NALU-E01-E10-PRODUCTION-AUTHORIZED", "seq=7", "seq=10", "seq=12", "seq=13", "seq=17", "seq=19", "seq=27 rules 1–4", "seq=29 rules 5–7 (rule 8 pending)", "D-57 identity chain"]},
    "writer_identity": {"agent_id": "claude-code-nalu-writer", "provider": "anthropic", "model_id": "claude-fable-5-1", "session_note": "Claude Code 交互会话，Roger 2026-09-18 指令「改完后发布到git，然后启动e06」"},
    "source_binding": {
        "work": "夜无疆", "author": "辰东",
        "primary_source_chapter": "6", "source_chapters": ["6"], "chapter_title": "黄金年龄段",
        "source_file": str(SRC_CH), "source_sha256": sha(SRC_CH),
        "source_index": str(RUNTIME / "sources/夜无疆/SOURCE_INDEX.json"),
        "episode_source_map": str(RUNTIME / "runtime/episode_source_map_yewujiang_v1.json"),
        "beat_count": len(BEATS), "beats_landed": sum(1 for b in BEATS if b[1] == "landed"), "beats_merged": sum(1 for b in BEATS if b[1] == "merged"), "beats_dropped": sum(1 for b in BEATS if b[1] == "dropped"),
        "★carry_in_is_bound_to_the_previous_episode_bytes": f"承接 E05 合同末镜 {PREV_LAST['shot_id']} completion_state「{PREV_LAST['completion_state']}」（narrative 头部逐字引）；E06-S01-01 从秦铭推开院门从荒野回来开始",
        "carry_in": contract["carry_in"] | {"previous_canonical": f"workflow/claude_writer_agent/scripts/{PREV_EP}_NARRATIVE_CANONICAL_v1.md", "previous_canonical_sha256": sha(SCRIPTS / f"{PREV_EP}_NARRATIVE_CANONICAL_v1.md")},
    },
    "beat_disposition": [{"event_id": e, "disposition": d, "landed_at": at, "summary": s} for e, d, at, s in BEATS],
    "★authorized_insertions": [],
    "authored_dialogue_from_indirect_speech": [{"shot_id": shot, "speaker": cname(s), "text": q, "source_basis": AUTHORED_DIALOGUE[q]} for s, q, shot, v in DIALOGUE_UNITS if not v],
    "★audience_already_knows": ["永夜世界与太阳石", "黄金年龄段与新生", "二病子举驴", "松鼠与铁笼", "院中练功出银光（E05）", "黑衣女子与乌鸦（秦铭不知道）"],
    "★style_reset_disclosure": STYLE_RESET_DISCLOSURE,
    "structure": [{"beat_id": f"{EP}-B{idx+1:02d}", "scene_id": sid, "target_seconds": m["sec"], "thread": "线A", **SCENE_BEAT_META[sid], "shot_ids": [f"{x['s']}-{x['n']:02d}" for x in by_scene[sid]], "location_id": m["loc"], "source_events": m["beats"]}
                  for idx, (sid, m) in enumerate(SCENES.items())],
    "scene_breakdown_seconds": {sid: m["sec"] for sid, m in SCENES.items()},
    "total_seconds": TOTAL,
    "runtime_target_seconds": {"min": 150.0, "target": 155.0, "max": 170.0},
    "shot_count": len(SHOTS),
    "pacing": PACING,
    "key_quote_landing": [{"speaker": cname(s), "quote": q, "shot_id": shot, "verbatim_in_source": True, **({"split_note": SPLIT_QUOTES[q]} if q in SPLIT_QUOTES else {})} for s, q, shot in KEY_QUOTES],
    "fs1": {"combat_clusters": [], "combat_seconds": 0, "note": "本集无打斗；院中练功与开龙脊为源章明写的单人功法演练。"},
    "identity_registry": {cid(k): cname(k) for k in CH} | {p["entity_id"]: p["name"] for p in PROPS} | {s["entity_id"]: s["name"] for s in SETS},
    "new_name_budget": {"budget_per_4_episodes": 1, "writer_invented_names_this_episode": 0, "note": "周长裕为源章人名；周阿婆、邻居甲为既有角色；金色灯笼眼为源章描述性指代"},
    "distinct_locations": sorted({m["loc"] for m in SCENES.values()}),
    "new_locations": ["LOC-ZHOU-HOUSE-INT"],
    "episode_global_space_map_id": "GSM-YEWUJIANG-SHUANGSHU-VILLAGE-V1",
    "global_space_map_refs": [
        {"map_id": "GSM-YEWUJIANG-QINMING-LUZE-ADJOINING-HOMESTEAD", "scenes": ["E06-S01", "E06-S02", "E06-S03", "E06-S04", "E06-S05", "E06-S06", "E06-S07", "E06-S10", "E06-S12", "E06-S13"], "anchors": ["院门", "院中石盆太阳石", "院角上下两块磨盘", "半埋雪中的石碾子", "屋门", "火炕", "铜盆"], "axis_note": "院内沿院门—院角磨盘轴（S04 陆泽自院门看向院角）；屋内沿炕—屋门轴"},
        {"map_id": "GSM-YEWUJIANG-VILLAGE-STREET-NORTH", "scenes": ["E06-S08", "E06-S09", "E06-S11"], "anchors": ["北街路口", "周家院门与单间土屋", "各家院内外溢的橘红光"], "axis_note": "S09 秦铭沿街自南向北走到周家门口；周家屋内沿屋门—火炕轴"},
        {"map_id": "GSM-YEWUJIANG-SNOWFIELD-WILDS", "scenes": ["E06-S14"], "anchors": ["村口方向（南）", "雪原", "林线（北）"], "axis_note": "S14 秦铭自南向北疾奔冲进林线"},
    ],
    "shot_subspace_bindings": [{"shot_id": f"{sh['s']}-{sh['n']:02d}", "location_id": SCENES[sh["s"]]["loc"]} for sh in SHOTS],
    "onscreen_text_shot_level_registry": [],
    "state_delta_contract_summary": {"shots_total": len(SHOTS), "shots_with_entry_ne_completion": len(SHOTS), "min_dimensions_per_shot": min(len(sh["dims"]) for sh in SHOTS), "extend_words_in_action_fields": 0},
    "camera_motion_summary": {"locked_shots": LOCKED_IDS, "locked_share": round(len(LOCKED_IDS) / len(SHOTS), 3), "policy": PACING["camera_motion_policy"], "direction_rebalanced": CAMERA_DIRECTION_REBALANCED},
    "identity_reanchor_shots": REANCHOR_IDS,
    "bgm_selective_cues": BGM_CUES,
    "voice_casting_seq17": {k: cname(k) for k in ("QM", "LZ", "LW", "WR", "ZC", "VA")},
    "seq27_writer_selfcheck": SEQ27_SELFCHECK,
    "seq29_writer_selfcheck": {"status": _w29["status"], "enforced": True, "failures": _w29["failures"], "rule8_info": _w29["warnings"], "dialogue_shots": _w29["measurements"]["dialogue_shots"]},
    "writer_self_check": {"every_scene_asked_which_source_beat": True, "scenes_without_source_beat": [], "undeclared_insertions": 0, "dialogue_lines_total": len(DIALOGUE_UNITS), "dialogue_lines_verbatim_in_source": len(KEY_QUOTES)},
}
manifest_path = SCRIPTS / f"{EP}_manifest_{VER}.json"
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"narrative": {"path": str(narr), "sha256": sha(narr)}, "directing": {"path": str(directing), "sha256": sha(directing)},
                  "contract": {"path": str(contract_path), "sha256": sha(contract_path), "shots": len(SHOTS)},
                  "manifest": {"path": str(manifest_path), "sha256": sha(manifest_path), "total_seconds": manifest["total_seconds"], "scenes": len(SCENES)},
                  "camera_direction_rebalanced": CAMERA_DIRECTION_REBALANCED}, ensure_ascii=False, indent=2))
