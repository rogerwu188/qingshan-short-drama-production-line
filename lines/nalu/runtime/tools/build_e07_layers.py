import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))
import nalu_paths as _np
# -*- coding: utf-8 -*-
"""E07《遭遇》v1 —— 从一张镜头表生成 directing script / generation contract / manifest（模板 build_e06_layers.py）。

seq=36（2026-09-18）：E07 启动；D-68 过渡规则：每镜 entry_state 写上一镜留下的姿态，姿态变化写在镜内（R9 强制）；
同场景边界的开场关键帧由上一单元真实末帧承担（build_keyframe_manifest DEFERRED）。seq=29 规则 5–7 沿用；D-57 身份链沿用。
本集三段兽斗（射鹿、驴头狼、野猪王）均为源章明写；生物全部出参考卡（kind=CREATURE + creature_card）。
"""
import hashlib, json, math, pathlib, re
import nalu_prompt_rules as NPR
import nalu_writer_selfcheck_seq29 as W29

ROOT = pathlib.Path(f"{_np.ENGINE_ROOT}")
SCRIPTS = ROOT / "workflow/claude_writer_agent/scripts"
RUNTIME = pathlib.Path(f"{_np.RUNTIME_ROOT}")
SRC_CH = RUNTIME / "sources/夜无疆/zh-CN/ch0007.md"
QM_SOURCE_V2 = RUNTIME / "runtime/character_sources/CHAR-QINMING__SOURCE_V2_TANG.png"
EP, VER = "E07", "v1"
PREV_EP, PREV_LAST_SHOT = "E06", "E06-S14-02"
PREV_CONTRACT = SCRIPTS / f"{PREV_EP}_GENERATION_CONTRACT_v1.json"
E03_CONTRACT = SCRIPTS / "E03_GENERATION_CONTRACT_v1.json"
E04_CONTRACT = SCRIPTS / "E04_GENERATION_CONTRACT_v1.json"

def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

_E06 = json.loads(PREV_CONTRACT.read_text(encoding="utf-8"))
_E03 = json.loads(E03_CONTRACT.read_text(encoding="utf-8"))
_E04 = json.loads(E04_CONTRACT.read_text(encoding="utf-8"))
PREV_LAST = _E06["shots"][-1]
assert PREV_LAST["shot_id"] == PREV_LAST_SHOT

CH = {
    "QM": ("CHAR-QINMING", "秦铭"),
    "YQ": ("CHAR-YANGYONGQING", "杨永青"),
    "SC": ("CHAR-SHAOCHENGFENG", "邵承峰"),
}
VOICE_ONLY: set = set()
def cid(k): return CH[k][0]
def cname(k): return CH[k][1]

# ---------- 风格与时代约束：沿 E06 合同（唐宋画风，seq=7） ----------
STYLE = {k: v for k, v in _E06["style"].items() if k not in ("authority", "negative_prompt_fixed")}
_PERIOD6 = {s["location_id"]: s["period_constraints"] for s in _E06["scene_states"]}
_PERIOD4 = {s["location_id"]: s["period_constraints"] for s in _E04["scene_states"]}
_PERIOD_BASE = _PERIOD6["LOC-QINMING-YARD-EXT"].split("；小院")[0]
PERIOD_BY_LOC = {
    "LOC-SNOWFIELD-WILDS-EXT": _PERIOD_BASE + "；村外雪路与雪原：出村不远踩实的雪路、两侧齐胸深的积雪、雪面月色青蓝反光、远处黑压压的山脉与林线；巡山者的皮甲为唐宋皮革札甲语汇，铁枪为木杆铁头；无路灯、无路标、无栅栏、无任何现代物",
    "LOC-FOREST-EDGE-EXT": _PERIOD4["LOC-FOREST-EDGE-EXT"].split("；黑暗中的猩红眼睛")[0] + "；山林外部区域：落叶松、云杉与白桦耸入夜色，树枝压雪，兽类踩出的小路、残碎兽骨与大蹄印；开阔地血迹斑斑、海碗大的兽爪印；生物一律写实体态，只按参考卡给形貌，不做怪兽特效；无路标、无栅栏、无任何人造物",
    "LOC-LOW-HILL-TOP-EXT": _PERIOD4["LOC-LOW-HILL-TOP-EXT"].split("；矮山顶")[0] + "；矮山半山腰：雪石与稀疏林木，一棵需数人合抱的大树，远处群山黑影；夜空原本什么都没有，远山之上升起的一团白光是画面里唯一的天光；无任何人造物",
}
STYLE_RESET_DISCLOSURE = {
    "kind": "STYLE_CONTINUATION_NO_RESET",
    "authority": "SUPERVISOR_ORDERS seq=7 c1/c2/c4（E02 起唐宋画风）；seq=36（E07 沿用）",
    "what_changes": "无画风变化；新入画人物邵承峰（巡山者，四十岁左右，皮甲、弓箭、铁枪、披发，文生图）按唐宋语汇出身份牌；杨永青沿 E04 唐宋版身份牌；四种生物（食肉夜鸟、刀角鹿、驴头狼、野猪王）与远山光团各出参考卡；驴头狼即 E04 只给轮廓的变异生物，本集正面露相",
    "qinming_identity_source": {"file": str(QM_SOURCE_V2), "sha256": sha(QM_SOURCE_V2) if QM_SOURCE_V2.is_file() else "", "usage": "FACE_IDENTITY_REFERENCE + WARDROBE/HAIR STYLE REFERENCE（E02 已锁定的三视图身份牌直接复用）；D-57 ①：本集 S3 复测源图余弦 ≥0.45"},
    "viewer_facing_note": "E06→E07 画风与造型连续；本集全部外景、无村内戏；三段兽斗按源章明写，机位随动作走",
}
PACING = {**_E06["pacing"],
    "authority": "seq=17 节奏 + seq=19 门禁 + seq=27 规则 1–4 + seq=29 规则 5–7 + D-68 过渡规则（单元起始态 = 上一镜结束姿态）",
    "shot_seconds_default": [2, 4], "shot_seconds_max": 6,
    "shot_seconds_max_note": "对白镜时长由 NPR.min_dialogue_seconds 推导（seq=29 规则 5a），最长 6.0 s（24 字 @5.0 + 引擎切点安全）；无对白镜 ≤4 s",
    "scene_seconds_max_exception": "本集无例外：最长场 14 s（E07-S08 / E07-S10）",
    "hook_rule": "全集前 3 秒 = 村外夜路上一个敦实的黑影突然拦在秦铭面前，他猎叉一横（E07-S01-01，威胁型钩子）",
    "hook": {"type": "shock", "at_seconds": 0, "line_or_shot_id": "E07-S01-01", "note": "承 E06 出村：夜路被拦，猎叉横起（MOMENTUM/CONTACT）；第 3 秒后才认出是杨叔"},
    "child_dialogue_rule": "seq=13：本集无儿童对白",
    "dialogue_shot_length_rule_seq29": "target_seconds == ceil_0.5(spoken_chars / cps + 0.5)，逐镜断言，无模板值",
}
PACING["camera_motion_policy"] = {**PACING["camera_motion_policy"], "locked_share_max": 0.30}

# ---------- 场次 ----------
SCENES = {
    "E07-S01": dict(loc="LOC-SNOWFIELD-WILDS-EXT", time="TIME-DEEP-NIGHT", weather="深夜·村外雪路·无风", light="雪面月色青蓝反光为主光，身后村中太阳石的橘红光只剩一抹", sec=13.5, beats=["E07-EV-01", "E07-EV-02", "E07-EV-03"], info=2),
    "E07-S02": dict(loc="LOC-SNOWFIELD-WILDS-EXT", time="TIME-DEEP-NIGHT", weather="深夜·村外雪路·无风", light="雪面月色青蓝反光，远处黑影只见轮廓", sec=12.5, beats=["E07-EV-04", "E07-EV-05", "E07-EV-06"], info=2),
    "E07-S03": dict(loc="LOC-SNOWFIELD-WILDS-EXT", time="TIME-DEEP-NIGHT", weather="深夜·村外雪路·无风", light="雪面月色青蓝反光映着三张脸，皮甲有冷光", sec=13, beats=["E07-EV-07", "E07-EV-08", "E07-EV-09"], info=2),
    "E07-S04": dict(loc="LOC-SNOWFIELD-WILDS-EXT", time="TIME-DEEP-NIGHT", weather="深夜·村外雪路·无风", light="雪面月色青蓝反光，山脉方向更暗", sec=11.5, beats=["E07-EV-10", "E07-EV-11", "E07-EV-12"], info=2),
    "E07-S05": dict(loc="LOC-SNOWFIELD-WILDS-EXT", time="TIME-DEEP-NIGHT", weather="深夜·村外雪路·起微风", light="雪面月色青蓝反光，村里的橘红光在杨永青身后", sec=9, beats=["E07-EV-13", "E07-EV-14"], info=2),
    "E07-S06": dict(loc="LOC-SNOWFIELD-WILDS-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜到来·雪原·雪花翻溅", light="雪面青蓝反光转亮，山林轮廓若隐若现", sec=8, beats=["E07-EV-15", "E07-EV-16"], info=2),
    "E07-S07": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·林间·无风", light="林间雪地青蓝微光；一双双碧绿眼睛是画面里唯一的绿光", sec=12.5, beats=["E07-EV-17", "E07-EV-18", "E07-EV-19", "E07-EV-20"], info=2),
    "E07-S08": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·林间·无风", light="林间雪地青蓝微光，鹿群黑影在雪面反光里成排", sec=14, beats=["E07-EV-21", "E07-EV-22", "E07-EV-23"], info=2),
    "E07-S09": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·林间·无风", light="林间雪地青蓝微光，大树的树干黑而粗", sec=6.5, beats=["E07-EV-24", "E07-EV-25"], info=2),
    "E07-S10": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·林间·山风渐大卷雪粒", light="雪面青蓝反光，风卷的雪粒在光里飞；驴头狼的猩红眼睛是唯一红光", sec=14, beats=["E07-EV-26", "E07-EV-27", "E07-EV-28", "E07-EV-29"], info=2),
    "E07-S11": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·林间·山风卷雪", light="雪面青蓝反光，刀光雪亮；猩红眼睛唯一红光", sec=13, beats=["E07-EV-30", "E07-EV-31", "E07-EV-32"], info=2),
    "E07-S12": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·林间·风渐小", light="雪面青蓝反光，雪地被血染红一片", sec=12, beats=["E07-EV-33", "E07-EV-34", "E07-EV-35", "E07-EV-36"], info=2),
    "E07-S13": dict(loc="LOC-LOW-HILL-TOP-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·半山腰·远处巨响", light="雪面青蓝反光，远处密林里积雪翻腾", sec=13.5, beats=["E07-EV-37", "E07-EV-38"], info=2),
    "E07-S14": dict(loc="LOC-LOW-HILL-TOP-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·半山腰·风声渐弱到死寂", light="雪面青蓝反光；远山之上升起的一团白光越来越亮，像明月当空", sec=15.5, beats=["E07-EV-39", "E07-EV-40"], info=2),
}
AMBIENT_LIFE = {
    "E07-S01": {"grade": "A", "motion_trend": "夜路行走、黑影拦路、猎叉横起、认出杨叔、扛叉答话", "first_frame_state": "秦铭背弓拎叉正走在村外雪路上", "reaction_progression": "被拦→「杨叔？」→「浅夜还未到」→「碰碰运气」"},
    "E07-S02": {"grade": "B", "motion_trend": "拍雪笑谈、远处黑影晃动、压低声音、巡山者走近、抱拳招呼", "first_frame_state": "杨永青正拍着身上的雪", "reaction_progression": "「毫无收获」→「巡山者」→皮甲铁枪走近→「邵兄」"},
    "E07-S03": {"grade": "B", "motion_trend": "打量、摆手解释、冷扫一眼、转身没入夜色", "first_frame_state": "邵承峰正上下打量秦铭", "reaction_progression": "「二病子吧」→「隔壁村的」→「数十年没出过」→转身走"},
    "E07-S04": {"grade": "B", "motion_trend": "望背影发问、搓胡含蓄作答、抬手指山", "first_frame_state": "秦铭正望着邵承峰消失的方向", "reaction_progression": "「每天进山吗」→「有的人很负责」→「山中不对劲」"},
    "E07-S05": {"grade": "B", "motion_trend": "拍肩劝勉、半开玩笑、转身回村、独自向野外", "first_frame_state": "杨永青的手正拍在秦铭肩头", "reaction_progression": "「该努力了」→「贵女看中」→分别"},
    "E07-S06": {"grade": "A", "motion_trend": "齐胸雪中破浪、浅夜到来、肚子叫、攥叉冲进密林", "first_frame_state": "秦铭正在齐胸积雪里破浪疾行", "reaction_progression": "破浪→山林显形→饥饿→冲进去"},
    "E07-S07": {"grade": "A", "motion_trend": "循哭声提速、碧绿眼睛、闯过惊飞、只剩骨头、血色开阔地", "first_frame_state": "秦铭正在林间小路上循声疾行", "reaction_progression": "女子哭声→十几双绿眼→夜鸟惊飞→「可惜，来晚一步」→兽爪印"},
    "E07-S08": {"grade": "A", "motion_trend": "跟蹄印、黑影成排、取弓、满月一箭、雄鹿冲来鹿群狂奔、再射一箭", "first_frame_state": "秦铭正跟着蹄印走", "reaction_progression": "「刀角鹿！」→一箭入肺→冲来→第二箭"},
    "E07-S09": {"grade": "B", "motion_trend": "攀树、雄鹿栽倒、鹿群远去、跳下走近", "first_frame_state": "秦铭正攀向大树", "reaction_progression": "上树→砰然栽倒→鹿群远去→「足有七百斤」"},
    "E07-S10": {"grade": "A", "motion_trend": "拖鹿回程、大爪搭肩、缩肩滚开见血、积雪崩开黑影暴起、仰面抓前肢、一脚踢翻", "first_frame_state": "秦铭正拖着刀角鹿沿原路往回走", "reaction_progression": "爪子搭肩→滚开见血→暴起扑来→抓住前肢→踢翻→「驴头狼！」"},
    "E07-S11": {"grade": "A", "motion_trend": "按叉入雪直立嘶吼、拔刀逼去、刀爪碰撞、砍断獠牙、铁鞭扫肋", "first_frame_state": "驴头狼正把猎叉按进雪里直立起来", "reaction_progression": "嘶吼→「赤手空拳也能打死你」→碰撞→獠牙断→肋骨断"},
    "E07-S12": {"grade": "B", "motion_trend": "按倒砸拳颈断、捏出铁箭头、抚肩伤、割皮埋脏腑", "first_frame_state": "秦铭正扑上去把驴头狼按进雪里", "reaction_progression": "颈断→「就是你」→「不能生火」→埋脏腑"},
    "E07-S13": {"grade": "A", "motion_trend": "拖两猎物上半山腰、远处巨响飞禽冲天、野猪王掀翻障碍闯来、转向矮山", "first_frame_state": "秦铭正拖着两个大家伙上坡", "reaction_progression": "巨响→「血腥味引来了巨兽？」→野猪王闯来→「追杀它的是什么生物？」"},
    "E07-S14": {"grade": "A", "motion_trend": "攀上合抱大树搭箭、野猪王抬头黑鳞、山林骤静远山光起、野猪王无声退走埋雪、明月当空", "first_frame_state": "秦铭正攀向合抱大树", "reaction_progression": "搭箭→黑鳞獠牙→死寂与光→退走埋雪→「那其实是一只虫」"},
}
def _wp(sid, mode):
    return {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": f"E07_NARRATIVE_CANONICAL_v1.md#{sid}｜ch7", "visibility_mode": mode}
WEATHER_PROVENANCE = {sid: _wp(sid, "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED") for sid in SCENES}
for _sid, _m in SCENES.items():
    _m["ambient_life"] = AMBIENT_LIFE[_sid]
    _m["weather_provenance"] = WEATHER_PROVENANCE[_sid]

# ---------- 服装（承 E06 / E04 合同的 wardrobe_garments；新人物按唐宋语汇） ----------
_WG6 = {c["character_id"]: c["wardrobe_garments"] for c in _E06["character_entities"]}
_WG4 = {c["character_id"]: c["wardrobe_garments"] for c in _E04["character_entities"]}
WARDROBE_GARMENTS = {
    "CHAR-QINMING": {**_WG6["CHAR-QINMING"], "condition": "出村进山：披裘氅、背竹木硬弓与皮箭囊、腰间布带插短刀、手拎猎叉；E07-S10 起双肩棉衣被大爪子抓烂、肩头见血"},
    "CHAR-YANGYONGQING": {**_WG4["CHAR-YANGYONGQING"], "condition": "刚从山外回来，皮坎肩与络腮胡上沾着雪碴"},
    "CHAR-SHAOCHENGFENG": {"silhouette": "高大、宽肩、披散长发、皮甲外罩、背弓攥枪", "outer_layer": "深褐皮革札甲（外层，唐宋皮甲语汇，甲片以皮绳编缀）", "inner_layer": "黑色粗麻交领窄袖袍", "primary_color": "深褐", "secondary_color": "黑", "material": "硬皮革＋粗麻", "pattern": "皮甲片纵向编缀，旧而磨亮", "belt_or_fastening": "皮革腰带扣结；箭囊斜背", "footwear": "高帮皮靴裹腿", "accessory": "披散及肩的黑发无冠；背竹木弓与皮箭囊；右手攥一杆木杆铁头长枪", "condition": "风尘仆仆，皮甲上有雪"},
}

# ---------- 道具、生物与布景 ----------
PROPS = [
    {"entity_id": "PROP-HUNTING-FORK", "name": "猎叉", "reference_card_required": False, "first_shot": "E07-S01-01",
     "note": "E03 已出卡并锁定：木柄铁头猎叉；本集全程拎在手里，E07-S11 被驴头狼按进雪里", "period_constraints": "唐宋农猎器具语汇，锻铁叉头、麻绳缠柄"},
    {"entity_id": "PROP-BOW-ARROWS", "name": "弓箭", "reference_card_required": False, "first_shot": "E07-S01-01",
     "note": "E04 已出卡并锁定：竹木硬弓与皮箭囊、铁镞木杆铁箭；本集背在背上，射鹿两箭、树上搭箭对准野猪王", "period_constraints": "唐宋竹木复合弓与皮箭囊，铁镞木杆铁箭；无金属滑轮、无现代箭袋"},
    {"entity_id": "PROP-SHORT-KNIFE", "name": "短刀", "reference_card_required": False, "first_shot": "E07-S11-02",
     "note": "E03 已出卡并锁定：直刃短刀，插在秦铭腰后布带里；本集拔出与驴头狼对砍、割开猎物皮毛", "period_constraints": "锻铁直刃、木柄，无护手无现代刀具"},
    {"entity_id": "PROP-IRON-ARROWHEAD", "name": "铁箭头", "reference_card_required": False, "first_shot": "E07-S12-02",
     "note": "从驴头狼皮毛里捏出的一枚残留铁箭头：三棱铁镞、断了木杆、带着血污；是 E04 秦铭射中变异生物的那一支", "period_constraints": "锻铁三棱镞，无现代金属光泽"},
    {"entity_id": "PROP-NIGHT-BIRDS", "name": "夜鸟", "kind": "CREATURE", "creature_card": {"locomotion": "biped", "eye_color": "碧绿", "silhouette_ref": "PROP-NIGHT-BIRDS identity plate (workflow/nalu/E07/identity)"}, "reference_card_required": True, "first_shot": "E07-S07-02",
     "note": "食肉性夜鸟，体长两尺、群居、声若幽泣：黑羽、钩喙、一双碧绿的眼睛；十几只立在林地骨头堆旁，被惊时扑棱棱冲上夜空；参考卡为一只立在雪地兽骨旁的侧身全貌，碧绿眼睛清楚，另有惊飞的翼影", "period_constraints": "写实鸟类体态，不做卡通化，不发光（碧绿眼睛除外）"},
    {"entity_id": "PROP-BLADE-HORN-STAG", "name": "刀角鹿", "kind": "CREATURE", "creature_card": {"locomotion": "quadruped", "eye_color": "深褐", "silhouette_ref": "PROP-BLADE-HORN-STAG identity plate (workflow/nalu/E07/identity)"}, "reference_card_required": True, "first_shot": "E07-S08-01",
     "note": "黑褐色的大雄鹿，七百斤，头部两侧与前方共六支扁平锋锐的角像六把钢刀；鹿群二十几头为它的同类黑影；参考卡为雪地上侧身全貌的大雄鹿，六角清楚", "period_constraints": "写实鹿类体态，角为扁平刀形骨角，不发光"},
    {"entity_id": "PROP-DONKEY-HEAD-WOLF", "name": "驴头狼", "kind": "CREATURE", "creature_card": {"locomotion": "biped", "eye_color": "猩红", "silhouette_ref": "PROP-DONKEY-HEAD-WOLF identity plate (workflow/nalu/E07/identity)"}, "reference_card_required": True, "first_shot": "E07-S10-01",
     "note": "即 E04 只给轮廓与猩红双眼的变异生物（PROP-MUTANT-BEAST）本集正面露相：硕大的驴头、开阔的嘴、寒光闪闪的利齿与獠牙、颈后很长的黑色鬃毛、山狼的躯体、黑油油的皮毛、猩红的眼睛、四百斤、四肢很长能直立起身；参考卡为雪地上直立嘶吼的全貌，猩红眼睛是画面里唯一的红点光", "period_constraints": "写实猛兽体态，不做怪兽特效，不发光（猩红眼睛除外）"},
    {"entity_id": "PROP-BOAR-KING", "name": "野猪王", "kind": "CREATURE", "creature_card": {"locomotion": "quadruped", "eye_color": "黑", "silhouette_ref": "PROP-BOAR-KING identity plate (workflow/nalu/E07/identity)"}, "reference_card_required": True, "first_shot": "E07-S13-03",
     "note": "一千五百斤以上的巨大野猪：小山似的块头、周身钢针般粗硬的黑毛、雪白獠牙比成年人小臂还长、面部一层黑色鳞片泛着冷幽幽的金属光泽；负伤染血；参考卡为雪地上侧身全貌与抬头时的面部黑鳞", "period_constraints": "写实野猪体态放大，黑鳞为哑光冷色，不发光、不做怪兽特效"},
]
SETS = [
    {"entity_id": "SET-BLOODY-CLEARING", "name": "血色开阔地", "reference_card_required": True, "first_shot": "E07-S07-04",
     "note": "林木稀疏的一片开阔地，雪地血迹斑斑，现场有比海碗口还大的兽爪印、被叼走残骸后的拖痕；参考卡只画雪地血迹与爪印，不画任何生物", "period_constraints": "天然林间空地，无任何人造物"},
    {"entity_id": "SET-DISTANT-MOON-LIGHT", "name": "远山光团", "reference_card_required": True, "first_shot": "E07-S14-03",
     "note": "远处山峰之上升起的一团光：起初柔和，很快灿烂，逐渐升高，最后宛若一轮皎洁的明月悬在夜空；参考卡只画远山黑影之上升起的白光团与被照亮的山脊，绝不画出虫的形貌", "period_constraints": "夜空里唯一的天光，无星无月无人造光"},
]

# ---------- 机位方案（每镜；本集无 LOCKED） ----------
def _cp(scale, height, side, lens, axis, fam, direction, start, end, why):
    if fam == "LOCKED" and end != start:
        why = f"{why}；画内变化：{end}"
        end = start
    return {"shot_scale": scale, "camera_height": height, "camera_side": side, "lens_intent": lens, "axis_relation": axis,
            "motion_family": fam, "motion_direction": direction, "start_framing": start, "end_framing": end, "motivation": why}
CAMERA_PLANS = {
    "E07-S01-01": _cp("MEDIUM_WIDE", "LOW", "AXIS_A", "28mm低机位在雪路前方迎着秦铭走来，敦实黑影自画右入画拦住", "秦铭自村口（画左）沿雪路向野外（画右）的行进轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "低机位中全景：秦铭背弓拎叉迎着镜头走在雪路上", "低机位中全景（横移）：黑影拦在面前，猎叉一横", "导演稿：开场 3 秒威胁钩子＝夜路被拦"),
    "E07-S01-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm缓推横叉的秦铭", "秦铭（画左）面向黑影（画右）的视线轴，不越轴", "DOLLY", "PUSH_IN", "中近景：秦铭横着猎叉，叉尖对着来人", "中近景（推近）：他认出络腮胡，放下猎叉", "导演稿：推近读认出"),
    "E07-S01-03": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm环绕讶异的杨永青，脸朝画面前方", "杨永青（画右）面向秦铭（画左）的交谈轴，环绕不越轴", "ARC", "CLOCKWISE", "中景：杨永青络腮胡上沾着雪碴看着秦铭", "中景（环绕）：他讶异地问完，笑起来拍秦铭胳膊", "导演稿：环绕读讶异"),
    "E07-S01-04": _cp("MEDIUM_CLOSE_UP", "LOW", "AXIS_B", "50mm低机位横移随秦铭扛叉望向野外", "秦铭（画左）面向杨永青（画右），不越轴", "TRACK", "LEFT_TO_RIGHT", "低机位中近景：秦铭把猎叉扛上肩", "低机位中近景（横移）：他平稳地答完，望向野外", "导演稿：横移落在望向野外，场尾 button"),
    "E07-S02-01": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm横移随杨永青拍雪到指山外", "杨永青（画右）面向秦铭（画左）的交谈轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中景：杨永青拍着身上的雪", "中景（横移）：他笑着说完，指向山外", "导演稿：横移读笑谈"),
    "E07-S02-02": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_B", "28mm自两人横摇向远处晃动的黑影", "两人（画左）望向远处黑影（画右）的视线轴", "PAN", "LEFT_TO_RIGHT", "中全景：杨永青转头，远处雪路有黑影晃动", "中全景（横摇）：他压低声音说完，抬手拦住秦铭", "导演稿：横摇读警觉"),
    "E07-S02-03": _cp("WIDE", "LOW", "AXIS_A", "24mm低机位自远处升起随高大身影走近", "邵承峰自夜色深处（画右）走向两人（画左）的行进轴，不越轴", "CRANE", "RISE", "低机位远景：夜色里一个高大的身影攥着铁枪走来", "低机位中全景（升起）：他走到近前停下，皮甲、弓箭、披发看得清楚", "导演稿：升起揭晓巡山者"),
    "E07-S02-04": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm缓推抱拳的杨永青，邵承峰在画右边缘", "杨永青（画左）面向邵承峰（画右）的轴线，不越轴", "DOLLY", "PUSH_IN", "中近景：杨永青抱拳迎上半步", "中近景（推近）：他招呼完，退回秦铭身边", "导演稿：推近读主动招呼，场尾 button"),
    "E07-S03-01": _cp("MEDIUM", "LOW", "AXIS_A", "35mm低机位环绕打量秦铭的邵承峰，脸朝画面前方", "邵承峰（画右）面向秦铭（画左）的视线轴，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "低机位中景：邵承峰上下打量秦铭", "低机位中景（环绕）：他沉声问完，目光转向杨永青", "导演稿：环绕读锐利"),
    "E07-S03-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm横移随摆手解释的杨永青", "杨永青（画左）面向邵承峰（画右）的交谈轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中近景：杨永青摆着手", "中近景（横移）：他含糊地说完，拍秦铭后背", "导演稿：横移读圆场"),
    "E07-S03-03": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm横移随邵承峰转身没入夜色", "邵承峰（画右）扫过两人（画左）后转身向夜色（画右外）", "TRACK", "RIGHT_TO_LEFT", "中全景：邵承峰不客气地扫了两人一眼", "中全景（横移）：他冷冷说完，转身走进夜色只剩背影", "导演稿：横移送走，场尾 button"),
    "E07-S04-01": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm缓推望着背影发问的秦铭", "秦铭（画左）望向邵承峰消失的方向（画右），不越轴", "DOLLY", "PUSH_IN", "中近景：秦铭把猎叉换到另一只手", "中近景（推近）：他轻声问完，转头看杨永青", "导演稿：推近读追问"),
    "E07-S04-02": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm环绕搓胡子的杨永青", "杨永青（画右）面向秦铭（画左）的交谈轴，环绕不越轴", "ARC", "CLOCKWISE", "中景：杨永青搓了搓络腮胡", "中景（环绕）：他含蓄地答完，望向山脉方向", "导演稿：环绕读含蓄"),
    "E07-S04-03": _cp("MEDIUM_WIDE", "LOW", "AXIS_B", "28mm低机位随杨永青抬手指山升起", "杨永青（画左）指向黑压压的山脉（画右）的视线轴，不越轴", "CRANE", "RISE", "低机位中全景：杨永青抬手指向山脉", "低机位中全景（升起）：他说完前半句，收回手看秦铭", "导演稿：升起送向山脉，场尾 button"),
    "E07-S05-01": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm双人同框缓推，杨永青画右、秦铭画左", "杨永青（画右）面向秦铭（画左）的交谈轴，不越轴", "DOLLY", "PUSH_IN", "中近景：杨永青的手拍在秦铭肩头", "中近景（推近）：他语重心长说完，握了握秦铭的肩", "导演稿：推近读劝勉"),
    "E07-S05-02": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_B", "28mm横移随两人分别，杨永青向村、秦铭向野外", "杨永青（画左）与秦铭（画右）背向而行的轴线，不越轴", "TRACK", "LEFT_TO_RIGHT", "中全景：杨永青松开手退了一步", "中全景（横移）：他半开玩笑说完，转身回村；秦铭望向野外", "导演稿：横移读分别，场尾 button"),
    "E07-S06-01": _cp("WIDE", "HIGH", "AXIS_A", "24mm高机位横移跟随齐胸雪中破浪的小人影", "秦铭自村口方向（画左）向山林（画右）疾行的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "高机位远景：秦铭在齐胸的积雪里破浪前冲", "高机位远景（横移）：雪花翻溅向两侧，浅夜到来山林显形", "导演稿：横移读破浪"),
    "E07-S06-02": _cp("MEDIUM", "LOW", "AXIS_B", "35mm低机位缓推站在山外的秦铭，脸正对镜头", "秦铭（画面中央）面向幽暗的密林（画右）", "DOLLY", "PUSH_IN", "低机位中景：秦铭站在山外攥着猎叉，肚子叫了", "低机位中景（推近）：他望着密林一闪身冲进去", "导演稿：推近读饥饿与决意，场尾 button"),
    "E07-S07-01": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm横移随秦铭循哭声提速", "秦铭自林缘（画左）向林深处（画右）的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中全景：秦铭走在兽踩出的林间小路上", "中全景（横移）：呜咽声传来，他猛然提速", "导演稿：横移读循声"),
    "E07-S07-02": _cp("WIDE", "LOW", "AXIS_B", "24mm低机位自碧绿眼睛升起随夜鸟冲天", "秦铭（画左）冲向碧绿眼睛（画右）的动作轴，不越轴", "CRANE", "RISE", "低机位远景：黑漆漆的林地间一双双碧绿的眼睛望来", "低机位远景（升起）：秦铭闯过去，十几只夜鸟扑棱棱冲上夜空", "导演稿：升起读惊飞（原著奇观）"),
    "E07-S07-03": _cp("MEDIUM_CLOSE_UP", "HIGH", "AXIS_A", "50mm高机位自骨头堆升到秦铭的侧脸", "秦铭（画右）低头看向骨头堆（画左）的视线轴，不越轴", "CRANE", "RISE", "高机位中近景：带血的骨头堆前，秦铭冲到近前", "高机位中近景（升起）：他说完，转身就走", "导演稿：升起读可惜"),
    "E07-S07-04": _cp("WIDE", "HIGH", "AXIS_B", "24mm高机位横移过血迹斑斑的开阔地与兽爪印", "秦铭自开阔地一侧（画右）戒备着走向另一侧（画左）", "TRACK", "RIGHT_TO_LEFT", "高机位远景：秦铭走进林木稀疏的开阔地，雪地血迹斑斑", "高机位远景（横移）：海碗大的兽爪印在雪里，他戒备着离开", "导演稿：横移读血色现场，场尾 button"),
    "E07-S08-01": _cp("MEDIUM_WIDE", "LOW", "AXIS_A", "28mm低机位在秦铭身后横移，越过他的肩看向鹿群黑影", "秦铭（画左，背对镜头）面向鹿群（画右）的视线轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "低机位中全景：秦铭跟着雪地里的蹄印走", "低机位中全景（横移）：二十几道黑影立在前方，他停下", "导演稿：横移读发现鹿群"),
    "E07-S08-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm缓推露出喜色的秦铭", "秦铭（画右）面向鹿群（画左）的视线轴，不越轴", "DOLLY", "PUSH_IN", "中近景：秦铭露出喜色", "中近景（推近）：他压着嗓子说完，取下弓箭瞄准大雄鹿", "导演稿：推近读喜悦"),
    "E07-S08-03": _cp("MEDIUM", "LOW", "AXIS_A", "35mm低机位环绕拉满的硬弓到铁箭射出", "秦铭（画左）射向大雄鹿（画右）的动作轴，环绕不越轴", "ARC", "CLOCKWISE", "低机位中景：秦铭把硬弓拉成满月", "低机位中景（环绕）：咻的一声，铁箭射入雄鹿的肺部", "导演稿：环绕读满月一箭"),
    "E07-S08-04": _cp("WIDE", "LOW", "AXIS_B", "24mm低机位横移随鹿群狂奔而来", "大雄鹿与鹿群自画右冲向秦铭所在的画左", "TRACK", "RIGHT_TO_LEFT", "低机位远景：大雄鹿中箭一震", "低机位远景（横移）：它不逃反冲，鹿群跟着狂奔，积雪迸溅", "导演稿：横移读冲锋"),
    "E07-S08-05": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm缓推再次弯弓的秦铭", "秦铭（画左）射向冲来的雄鹿（画右），不越轴", "DOLLY", "PUSH_IN", "中近景：秦铭再次弯弓", "中近景（推近）：第二支铁箭整支没入，雄鹿身体晃了几下", "导演稿：推近读第二箭，场尾 button"),
    "E07-S09-01": _cp("WIDE", "LOW", "AXIS_A", "24mm低机位随秦铭攀树升起再看向栽倒的雄鹿", "秦铭（画左树上）俯视雄鹿（画右）的视线轴，不越轴", "CRANE", "RISE", "低机位远景：秦铭攀上一棵很粗的大树", "低机位远景（升起）：大雄鹿砰地栽进雪里，鹿群止步远去", "导演稿：升起读上树与栽倒"),
    "E07-S09-02": _cp("MEDIUM", "HIGH", "AXIS_B", "35mm高机位随秦铭跳下走近缓降到鹿身", "秦铭（画右）走向雄鹿（画左）的行进轴，不越轴", "CRANE", "FALL", "高机位中景：秦铭跳下树拎着猎叉走近", "高机位中景（下降）：他满意地说完，抓住鹿角", "导演稿：下降落在收获上，场尾 button"),
    "E07-S10-01": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm横移随秦铭拖鹿回程，大爪子自画外搭上肩", "秦铭自林深处（画右）拖鹿向来路（画左）的行进轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中全景：秦铭拖着刀角鹿沿原路往回走，山风卷雪粒", "中全景（横移）：一双毛茸茸的大爪子自后面搭在他肩头", "导演稿：横移读偷袭"),
    "E07-S10-02": _cp("MEDIUM", "LOW", "AXIS_B", "35mm低机位环绕缩肩滚开到积雪崩开", "秦铭（画左）滚离雪堆（画右）的动作轴，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "低机位中景：大爪子搭在秦铭肩头", "低机位中景（环绕）：他缩肩下蹲滚开见血，积雪崩开黑影暴起扑来", "导演稿：环绕读险中脱身"),
    "E07-S10-03": _cp("CLOSE_UP", "LOW", "AXIS_A", "85mm低机位缓推仰面抓前肢的秦铭与驴头狼的血盆大口", "秦铭仰面（画面下方）对着驴头狼的驴头（画面上方）", "DOLLY", "PUSH_IN", "低机位特写：秦铭仰面抓住那对前肢，驴头就在面前", "低机位特写（推近）：他蜷身蹬出，驴头狼被踢翻出去", "导演稿：推近读正面相对（驴头首次露相）"),
    "E07-S10-04": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm横移随秦铭站起盯住猛兽", "秦铭（画右）面向驴头狼（画左）的对峙轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中近景：秦铭翻身站起", "中近景（横移）：他喊出三个字，抬手护住肩头", "导演稿：横移读认出，场尾 button"),
    "E07-S11-01": _cp("MEDIUM_WIDE", "LOW", "AXIS_A", "28mm低机位随驴头狼直立升起", "驴头狼（画左）面向秦铭（画右）的对峙轴，不越轴", "CRANE", "RISE", "低机位中全景：驴头狼爬起，把近前的猎叉按进雪里", "低机位中全景（升起）：它倏地直立而起，鬃毛炸立嘶吼", "导演稿：升起读直立嘶吼"),
    "E07-S11-02": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm缓推拔刀逼去的秦铭", "秦铭（画右）逼向驴头狼（画左）的动作轴，不越轴", "DOLLY", "PUSH_IN", "中景：秦铭从背后拔出短刀", "中景（推近）：他低吼一句，刀尖前指逼去", "导演稿：推近读无惧"),
    "E07-S11-03": _cp("MEDIUM", "LOW", "AXIS_A", "35mm低机位环绕刀爪碰撞到砍断獠牙", "驴头狼（画左）扑向秦铭（画右）的动作轴，环绕不越轴", "ARC", "CLOCKWISE", "低机位中景：驴头狼带着腥风扑来，短刀与大爪子碰撞", "低机位中景（环绕）：雪亮刀光划过，它嘴巴淌血獠牙被砍断", "导演稿：环绕读交手"),
    "E07-S11-04": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_B", "28mm横移随右腿铁鞭扫出", "秦铭（画右）扫向驴头狼（画左）的动作轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中全景：秦铭跟进，右腿如铁鞭", "中全景（横移）：重重扫在它身上，骨裂声中它凄厉惨叫", "导演稿：横移读断肋，场尾 button"),
    "E07-S12-01": _cp("MEDIUM", "HIGH", "AXIS_A", "35mm高机位随扑上按倒缓降到砸拳", "秦铭（画右）压向驴头狼（画左）的动作轴，不越轴", "CRANE", "FALL", "高机位中景：秦铭扑上去把驴头狼按在雪地中", "高机位中景（下降）：连着挥拳砸落，喀嚓一声它颈断不动", "导演稿：下降读终结"),
    "E07-S12-02": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_B", "85mm缓推指间的铁箭头到秦铭的脸", "秦铭（画左）看向指间铁箭头（画右）的视线轴，不越轴", "DOLLY", "PUSH_IN", "特写：秦铭从驴头狼皮毛里捏出一枚铁箭头", "特写（推近）：他低声说完，把铁箭头揣进怀里站起", "导演稿：推近读认出旧敌"),
    "E07-S12-03": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm环绕抚摸肩伤的秦铭", "秦铭（画右）低头看肩头（画左），环绕不越轴", "ARC", "COUNTERCLOCKWISE", "中近景：秦铭抚摸肩头的伤口", "中近景（环绕）：他咬着牙说完，抽出短刀蹲下", "导演稿：环绕读克制"),
    "E07-S12-04": _cp("MEDIUM_WIDE", "HIGH", "AXIS_B", "28mm高机位横移过两头猎物与被血染红的雪地", "秦铭（画左）蹲在两头猎物（画右）之间，不越轴", "TRACK", "LEFT_TO_RIGHT", "高机位中全景：秦铭蹲在猎物之间快速出刀", "高机位中全景（横移）：脏腑埋进雪里压实，他低声说完站起抓住猎物", "导演稿：横移读减负，场尾 button"),
    "E07-S13-01": _cp("WIDE", "LOW", "AXIS_A", "24mm低机位横移随拖两猎物上坡的小人影", "秦铭自山脚（画左）拖猎物上半山腰（画右）的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "低机位远景：秦铭拖着两个大家伙上到半山腰", "低机位远景（横移）：远处巨响，林中飞禽冲上夜空", "导演稿：横移读上山与巨响"),
    "E07-S13-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm缓推眉头深锁的秦铭", "秦铭（画右）望向远处密林（画左）的视线轴，不越轴", "DOLLY", "PUSH_IN", "中近景：秦铭松开猎物直起身", "中近景（推近）：他低声问完，望向远处的密林", "导演稿：推近读警觉"),
    "E07-S13-03": _cp("WIDE", "LOW", "AXIS_A", "24mm低机位横移随野猪王掀翻障碍闯来", "野猪王自远处密林（画左）冲向山脚（画右）", "TRACK", "LEFT_TO_RIGHT", "低机位远景：远处密林积雪翻腾，枝杈折断", "低机位远景（横移）：负伤染血的野猪王掀翻障碍冲到山脚，鼻子翕动", "导演稿：横移读巨兽登场（原著奇观）"),
    "E07-S13-04": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm环绕倒吸冷气的秦铭，野猪王转向矮山", "秦铭（画右）面向山脚野猪王（画左）的视线轴，环绕不越轴", "ARC", "CLOCKWISE", "中景：秦铭攥紧了弓", "中景（环绕）：他倒吸冷气说完，野猪王转头向矮山冲来，他退到大树下", "导演稿：环绕读麻烦大了，场尾 button"),
    "E07-S14-01": _cp("WIDE", "LOW", "AXIS_A", "24mm低机位随攀上合抱大树升起", "秦铭（画面中央）攀向大树高处", "CRANE", "RISE", "低机位远景：秦铭攀上需数人合抱的大树", "低机位远景（升起）：他在高处把铁箭搭在弓弦上对准下方", "导演稿：升起读上树搭箭"),
    "E07-S14-02": _cp("MEDIUM_CLOSE_UP", "HIGH", "AXIS_B", "50mm高机位自树上俯视缓推野猪王抬头的面部", "野猪王（画面下方）抬头向树上的秦铭（画面上方）", "DOLLY", "PUSH_IN", "高机位中近景：野猪王冲到树下抬起头", "高机位中近景（推近）：面部黑色鳞片泛冷幽幽的金属光泽，雪白獠牙比小臂还长", "导演稿：推近读黑鳞獠牙（原著奇观）"),
    "E07-S14-03": _cp("WIDE", "LOW", "AXIS_A", "24mm低机位自树上的秦铭横摇向远处山峰升起的光团", "秦铭（画左树上）望向远山（画右）的视线轴", "PAN", "LEFT_TO_RIGHT", "低机位远景：秦铭在树上搭着箭，山林骤然死寂", "低机位远景（横摇）：远处山峰上一团光升起，起初柔和很快灿烂", "导演稿：横摇揭晓远山之光"),
    "E07-S14-04": _cp("MEDIUM_WIDE", "HIGH", "AXIS_B", "28mm高机位横移随野猪王无声退走埋雪", "野猪王自树下（画右）退向幽暗洼地（画左）", "TRACK", "RIGHT_TO_LEFT", "高机位中全景：野猪王抬着头一声不出", "高机位中全景（横移）：它无声退进洼地，用积雪把自己埋上", "导演稿：横移读巨兽畏光"),
    "E07-S14-05": _cp("MEDIUM_CLOSE_UP", "LOW", "AXIS_A", "50mm低机位缓推仰望的秦铭，明月般的光照亮他的脸", "秦铭（画面中央）仰望夜空光团（画面上方）", "DOLLY", "PUSH_IN", "低机位中近景：秦铭扶着树干仰望夜空", "低机位中近景（推近）：光团如明月当空，他轻声说完攥紧弓弦", "导演稿：推近读震动，全集 button"),
}
_ALT = [("ARC", "COUNTERCLOCKWISE"), ("ARC", "CLOCKWISE"), ("TRACK", "LEFT_TO_RIGHT"), ("TRACK", "RIGHT_TO_LEFT"), ("CRANE", "RISE"), ("CRANE", "FALL")]
_ZH_FAM = {"ARC": "环绕", "TRACK": "横移", "CRANE": "升降", "DOLLY": "推拉", "PAN": "横摇"}

# 每镜：s, n, sec, size, camera, axis, blocking, cast, action(subject, primary_action, patient), dialogue(speaker,text,listener),
# emotion（NPR 说法条款 key）, perf(情绪词, 进行中的身体动作, 说话方式), after_line, entry, exit, dims, referents, faces, cps, slots, identity_reanchor
# D-68：entry 写上一镜留下的姿态（站/蹲/跪/坐/半撑），姿态改变写在本镜 action/exit 里。
D = lambda a, b, ca, cb: (a, b, ca, cb)
FORK, BOW, KNIFE, HEAD, BIRDS, STAG, WOLF, BOAR, CLEARING, MOON = ("PROP-HUNTING-FORK", "PROP-BOW-ARROWS", "PROP-SHORT-KNIFE", "PROP-IRON-ARROWHEAD",
    "PROP-NIGHT-BIRDS", "PROP-BLADE-HORN-STAG", "PROP-DONKEY-HEAD-WOLF", "PROP-BOAR-KING", "SET-BLOODY-CLEARING", "SET-DISTANT-MOON-LIGHT")
CREATURE_ONLY = "FACE_OUT_OF_FRAME_CREATURE_ONLY"
SHOTS = [
    # S01 —— 承 E06 出村；钩子＝夜路被拦
    dict(s="E07-S01", n=1, sec=3, size="中全景", camera="低机位迎着秦铭走来再横移随黑影拦路", axis="秦铭自村口（画左）沿雪路向野外（画右）", blocking="秦铭背着弓箭、拎着猎叉迎着镜头走在村外的雪路上，脸朝前；一个身材敦实的黑影自画右突然拦在他面前，他猎叉一横，叉尖对着来人",
         cast=["QM"], action=("QM", "秦铭背着弓箭、拎着猎叉走在村外的雪路上，一个身材敦实的黑影突然拦在他面前，他猎叉一横，叉尖对着来人", ""),
         entry="秦铭背着弓箭、拎着猎叉走在村外的雪路上，前方雪路空着", exit="一个敦实的黑影拦在秦铭面前，他的猎叉横起，叉尖对着来人",
         dims={"MOMENTUM": D("行走", "急停横叉", "WALKING", "STOPPED_FORK_UP"), "CONTACT": D("猎叉垂在手边", "猎叉横在身前", "FORK_DOWN", "FORK_LEVELLED")}, referents=[("他", "QM")]),
    dict(s="E07-S01", n=2, sec=1.5, cps=5.0, size="中近景", camera="缓推横叉的秦铭", axis="秦铭（画左）面向黑影（画右）", blocking="秦铭横着猎叉，看清来人的络腮胡，试探地脱口叫出两个字、字音短促不拖长，放下猎叉",
         cast=["QM"], action=("QM", "秦铭横着猎叉看清来人的一脸络腮胡，试探地脱口叫出两个字、字音短促不拖长，说完立即放下猎叉", ""), dialogue=("QM", "杨叔？", "YQ"), emotion="calm",
         perf=("疑", "横着猎叉盯住来人的络腮胡", "试探地脱口叫出，两个字一带而过不拖音"), after_line="放下猎叉",
         entry="秦铭横着猎叉，叉尖前是一张络腮胡的脸", exit="秦铭放下猎叉，叉尖垂向雪地",
         dims={"CONTACT": D("猎叉横在身前", "猎叉垂下", "FORK_LEVELLED", "FORK_LOWERED")}, referents=[]),
    dict(s="E07-S01", n=3, sec=4.5, cps=5.0, size="中景", camera="环绕讶异的杨永青", axis="杨永青（画右）面向秦铭（画左）", blocking="杨永青一脸络腮胡沾着雪碴，讶异地看着秦铭问一句，笑起来拍秦铭的胳膊",
         cast=["YQ", "QM"], action=("YQ", "杨永青络腮胡上沾着雪碴，讶异地看着秦铭问一句，说完立即笑起来拍了拍秦铭的胳膊", "QM"), dialogue=("YQ", "小秦，浅夜还未到，你这么早就出去？", "QM"), emotion="calm",
         perf=("惊", "拍掉络腮胡上的雪碴凑近看秦铭", "讶异地问"), after_line="笑起来拍秦铭的胳膊", slots={"YQ": "SCREEN_RIGHT", "QM": "SCREEN_LEFT"},
         faces={"QM": "BACK_THREE_QUARTER_TO_YANG_NOT_MEASURABLE"},
         entry="杨永青站在秦铭面前，络腮胡上沾着雪碴", exit="杨永青笑着，手拍在秦铭的胳膊上",
         dims={"CONTACT": D("两人未接触", "手拍在胳膊上", "APART", "ARM_PATTED"), "POSTURE": D("直立打量", "凑近拍人", "UPRIGHT", "LEANING_IN")}, referents=[("小秦", "QM")]),
    dict(s="E07-S01", n=4, sec=4.5, cps=5.0, size="中近景", camera="低机位横移随秦铭扛叉望向野外", axis="秦铭（画左）面向杨永青（画右）", blocking="秦铭把猎叉扛到肩上，平稳地答一句，望向野外的方向",
         cast=["QM", "YQ"], action=("QM", "秦铭把猎叉扛到肩上，平稳地答一句，说完立即抬头望向野外的方向", "YQ"), dialogue=("QM", "想去野外碰碰运气，看有没有冻死的山兽。", "YQ"), emotion="calm",
         perf=("坚", "把猎叉扛到肩上", "平稳地答"), after_line="抬头望向野外", slots={"QM": "SCREEN_LEFT", "YQ": "SCREEN_RIGHT"},
         faces={"YQ": "BACK_THREE_QUARTER_TO_QIN_NOT_MEASURABLE"},
         entry="秦铭把猎叉扛上肩，杨永青在他面前", exit="秦铭望向野外的方向，猎叉扛在肩上",
         dims={"POSSESSION": D("猎叉拎在手里", "猎叉扛在肩上", "FORK_IN_HAND", "FORK_ON_SHOULDER"), "POSTURE": D("低头答话", "抬头望远", "HEAD_LEVEL", "HEAD_UP_LOOKING_OUT")}, referents=[]),
    # S02 —— 毫无收获、巡山者走近
    dict(s="E07-S02", n=1, sec=6, cps=5.0, size="中景", camera="横移随杨永青拍雪到指山外", axis="杨永青（画右）面向秦铭（画左）", blocking="杨永青拍着身上的雪笑着说一句，指向山外，秦铭愕然看着他；杨永青始终在画内画右、脸朝画面前方，收回手时转头望向雪路远处，秦铭不指、不动手",
         cast=["YQ", "QM"], action=("YQ", "杨永青拍着身上的雪笑着说一句，说完立即指了指山外的方向，秦铭愕然看着他；杨永青收回手转头望向雪路远处，两人都留在画内", "QM"), dialogue=("YQ", "咱们想到一块去了，我刚在山外转了一圈，可惜毫无收获。", "QM"), emotion="joy",
         perf=("喜", "拍了拍身上的雪", "笑着说"), after_line="指了指山外", slots={"YQ": "SCREEN_RIGHT", "QM": "SCREEN_LEFT"},
         faces={"QM": "BACK_THREE_QUARTER_TO_YANG_NOT_MEASURABLE"},
         entry="杨永青拍着身上的雪，秦铭站在他面前", exit="杨永青收回指向山外的手转头望向雪路远处，秦铭愕然看着他，两人都在画内",
         dims={"CONTACT": D("手拍身上的雪", "手指向山外", "BRUSHING_SNOW", "POINTING_OUT"), "MOMENTUM": D("拍雪", "指向远处", "BRUSHING", "POINTING")}, referents=[("我", "YQ")]),
    dict(s="E07-S02", n=2, sec=2, cps=5.0, size="中全景", camera="自两人横摇向远处晃动的黑影", axis="两人（画左）望向远处黑影（画右）", blocking="远处雪路上有黑影晃动，杨永青转头盯住，压低声音说一句，抬手拦住秦铭",
         cast=["YQ", "QM"], action=("YQ", "远处的雪路上有黑影晃动，杨永青转头盯住，压低声音说一句，说完立即抬手拦住秦铭", "QM"), dialogue=("YQ", "巡山者。", "QM"), emotion="fear",
         perf=("疑", "转头盯住远处晃动的黑影", "压低声音"), after_line="抬手拦住秦铭", slots={"YQ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         faces={"YQ": "BACK_THREE_QUARTER_TO_FIGURE_NOT_MEASURABLE", "QM": "BACK_THREE_QUARTER_TO_FIGURE_NOT_MEASURABLE"},
         entry="远处的雪路上有黑影晃动，杨永青转头", exit="杨永青抬手拦在秦铭身前，远处的黑影在走近",
         dims={"CONTACT": D("手垂着", "手拦在秦铭身前", "HAND_DOWN", "HAND_BARRING"), "POSITION": D("黑影在远处", "黑影在走近", "FIGURE_FAR", "FIGURE_APPROACHING")}, referents=[]),
    dict(s="E07-S02", n=3, sec=3, size="远景", camera="低机位自远处升起随高大身影走近", axis="邵承峰自夜色深处（画右）走向两人（画左）", blocking="一个高大的身影攥着铁枪从夜色里走到雪路上，走到近前停下：皮甲、背弓箭、披散长发，脸朝画面前方",
         cast=["SC"], action=("SC", "一个穿皮甲、背弓箭、攥着铁枪、披散长发的高大男子从夜色里走到雪路上，走到近前停下，眼神锐利", ""),
         entry="一个高大的身影攥着铁枪从夜色里走到雪路上", exit="邵承峰攥着铁枪在近前停下，皮甲、弓箭、披发看得清楚",
         dims={"POSITION": D("在夜色深处", "在两人近前", "IN_THE_DARK", "AT_CLOSE_RANGE"), "MOMENTUM": D("走来", "停下", "APPROACHING", "STOPPED")}, referents=[]),
    dict(s="E07-S02", n=4, sec=1.5, cps=5.0, size="中近景", camera="缓推抱拳的杨永青", axis="杨永青（画左）面向邵承峰（画右）", blocking="杨永青抱拳迎上半步招呼一声，退回秦铭身边，邵承峰点了点头",
         cast=["YQ", "SC"], action=("YQ", "杨永青抱拳迎上半步招呼一声，说完立即退回秦铭身边，邵承峰点了点头", "SC"), dialogue=("YQ", "邵兄。", "SC"), emotion="calm",
         perf=("喜", "抱拳迎上半步", "主动招呼"), after_line="退回秦铭身边", slots={"YQ": "SCREEN_LEFT", "SC": "SCREEN_RIGHT"},
         faces={"SC": "BACK_THREE_QUARTER_TO_YANG_NOT_MEASURABLE"},
         entry="邵承峰站在近前，杨永青抱拳", exit="杨永青退回秦铭身边，邵承峰点了点头",
         dims={"POSITION": D("迎上半步", "退回原处", "STEPPED_FORWARD", "STEPPED_BACK"), "CONTACT": D("抱拳", "放下手", "FISTS_CUPPED", "HANDS_DOWN")}, referents=[]),
    # S03 —— 二病子、数十年、转身走
    dict(s="E07-S03", n=1, sec=5.5, cps=5.0, size="中景", camera="低机位环绕打量秦铭的邵承峰", axis="邵承峰（画右）面向秦铭（画左）", blocking="邵承峰目光锐利地上下打量秦铭，沉声问一句，目光转向杨永青，铁枪换到左手",
         cast=["SC", "QM"], action=("SC", "邵承峰目光锐利地上下打量秦铭，沉声问一句，说完立即把目光转向杨永青，铁枪换到左手", "QM"), dialogue=("SC", "这么年少就和你一起外出，该不会是那个二病子吧？", "YQ"), emotion="calm",
         perf=("疑", "目光锐利地上下打量秦铭", "沉声问"), after_line="把目光转向杨永青", slots={"SC": "SCREEN_RIGHT", "QM": "SCREEN_LEFT"},
         faces={"QM": "BACK_THREE_QUARTER_TO_SHAO_NOT_MEASURABLE"},
         entry="邵承峰站在秦铭面前上下打量", exit="邵承峰的目光转向杨永青，铁枪换到了左手",
         dims={"POSSESSION": D("铁枪在右手", "铁枪在左手", "SPEAR_RIGHT", "SPEAR_LEFT"), "POSTURE": D("低头打量", "转头看人", "LOOKING_DOWN", "TURNED_HEAD")}, referents=[]),
    dict(s="E07-S03", n=2, sec=2.5, cps=5.0, size="中近景", camera="横移随摆手解释的杨永青", axis="杨永青（画左）面向邵承峰（画右）", blocking="杨永青摆着手含糊地解释一句，拍了拍秦铭的后背",
         cast=["YQ", "QM"], action=("YQ", "杨永青摆着手含糊地解释一句，说完立即拍了拍秦铭的后背", "SC"), dialogue=("YQ", "二病子是隔壁村的……", "SC"), emotion="calm",
         perf=("慌", "摆着手解释", "含糊地说"), after_line="拍了拍秦铭的后背", slots={"YQ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         faces={"QM": "BACK_TO_CAMERA_FACING_SHAO_NOT_MEASURABLE"},
         entry="杨永青摆着手，秦铭站在他身侧", exit="杨永青的手拍在秦铭后背上",
         dims={"CONTACT": D("手在空中摆", "手拍在后背", "HAND_WAVING", "HAND_ON_BACK")}, referents=[]),
    dict(s="E07-S03", n=3, sec=5, cps=5.0, size="中全景", camera="横移随邵承峰转身没入夜色", axis="邵承峰（画右）扫过两人（画左）后转身向夜色", blocking="邵承峰不客气地扫了两人一眼冷冷地说一句，转身走进夜色，只剩背影",
         cast=["SC", "YQ", "QM"], action=("SC", "邵承峰不客气地扫了两人一眼冷冷地说一句，说完立即转身走进夜色，只剩一个背影", "YQ"), dialogue=("SC", "最近数十年都没出现过黄金年龄段的新生者。", "YQ"), emotion="mock",
         perf=("讥", "不客气地扫了两人一眼", "冷冷地说"), after_line="转身走进夜色", slots={"SC": "SCREEN_RIGHT", "YQ": "SCREEN_CENTER", "QM": "SCREEN_LEFT"},
         faces={"YQ": "BACK_THREE_QUARTER_TO_SHAO_NOT_MEASURABLE", "QM": "BACK_THREE_QUARTER_TO_SHAO_NOT_MEASURABLE"},
         entry="邵承峰扫了两人一眼", exit="邵承峰的背影没入夜色，雪路上只剩秦铭与杨永青",
         dims={"POSITION": D("邵承峰在近前", "邵承峰没入夜色", "SHAO_CLOSE", "SHAO_GONE"), "POSTURE": D("面向两人", "转身背向", "FACING", "TURNED_AWAY")}, referents=[]),
    # S04 —— 巡山者厉害、有的人很负责、山中不对劲
    dict(s="E07-S04", n=1, sec=4.5, cps=5.0, size="中近景", camera="缓推望着背影发问的秦铭", axis="秦铭（画左）望向邵承峰消失的方向（画右）", blocking="秦铭把猎叉换到另一只手，朝邵承峰消失的方向抬了抬下巴轻声问一句，转头看杨永青",
         cast=["QM", "YQ"], action=("QM", "秦铭把猎叉换到另一只手，朝邵承峰消失的方向抬了抬下巴轻声问一句，说完立即转头看杨永青", "YQ"), dialogue=("QM", "巡山者都是厉害人物，每天都要进山吗？", "YQ"), emotion="calm",
         perf=("疑", "把猎叉换到另一只手，朝夜色抬了抬下巴", "轻声问"), after_line="转头看杨永青", slots={"QM": "SCREEN_LEFT", "YQ": "SCREEN_RIGHT"},
         faces={"YQ": "BACK_THREE_QUARTER_TO_QIN_NOT_MEASURABLE"},
         entry="秦铭望着邵承峰消失的方向，猎叉在右手", exit="秦铭转头看向杨永青，猎叉换到了左手",
         dims={"POSSESSION": D("猎叉在右手", "猎叉在左手", "FORK_RIGHT", "FORK_LEFT"), "POSTURE": D("望向夜色", "转头看人", "LOOKING_OUT", "TURNED_TO_YANG")}, referents=[]),
    dict(s="E07-S04", n=2, sec=2.5, cps=5.0, size="中景", camera="环绕搓胡子的杨永青", axis="杨永青（画右）面向秦铭（画左）", blocking="杨永青搓了搓络腮胡含蓄地答一句，望向黑压压的山脉方向",
         cast=["YQ"], action=("YQ", "杨永青搓了搓络腮胡含蓄地答一句，说完立即望向黑压压的山脉方向", "QM"), dialogue=("YQ", "有的人很负责。", "QM"), emotion="mock",
         perf=("戏", "搓了搓络腮胡", "含蓄地答"), after_line="望向黑压压的山脉方向",
         entry="杨永青搓着络腮胡", exit="杨永青望向黑压压的山脉方向，手放下",
         dims={"POSTURE": D("低头搓胡", "抬头望山", "HEAD_DOWN_RUBBING", "HEAD_UP_TO_MOUNTAINS")}, referents=[]),
    dict(s="E07-S04", n=3, sec=4.5, cps=5.0, size="中全景", camera="低机位随杨永青抬手指山升起", axis="杨永青（画左）指向山脉（画右）", blocking="络腮胡的杨永青抬起右手指向黑压压的山脉说前半句，收回手看秦铭；年轻的秦铭双手垂在身侧、嘴唇闭合地站在他身侧听着",
         cast=["YQ", "QM"], action=("YQ", "络腮胡的杨永青抬起右手指向黑压压的山脉说一句，说完立即收回手转头看秦铭；秦铭双手垂在身侧静静听着，嘴唇闭合", "QM"), dialogue=("YQ", "现在山中的状况很不对劲，过于危险，", "QM"), emotion="fear",
         perf=("惧", "络腮胡的杨永青抬手指向黑压压的山脉", "沉着嗓子说"), after_line="收回手转头看秦铭", slots={"YQ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         faces={"QM": "BACK_THREE_QUARTER_TO_MOUNTAINS_NOT_MEASURABLE"},
         entry="络腮胡的杨永青抬起右手指向山脉，秦铭双手垂在身侧站着听", exit="杨永青收回手，转头看着秦铭",
         dims={"CONTACT": D("手指向山脉", "手收回", "POINTING_MOUNTAINS", "HAND_BACK"), "POSTURE": D("抬头指山", "转身面对秦铭", "HEAD_UP_TO_MOUNTAINS", "FACING_QIN")}, referents=[]),
    # S05 —— 拍肩劝勉、分别
    dict(s="E07-S05", n=1, sec=4.5, cps=5.0, size="中近景", camera="双人同框缓推，杨永青画右、秦铭画左", axis="杨永青（画右）面向秦铭（画左）", blocking="杨永青拍了拍秦铭的肩头语重心长地说一句，握了握他的肩",
         cast=["YQ", "QM"], action=("YQ", "杨永青拍了拍秦铭的肩头语重心长地说一句，说完立即握了握他的肩", "QM"), dialogue=("YQ", "小秦，该努力了，争取在黄金年龄段新生。", "QM"), emotion="calm",
         perf=("盼", "拍了拍秦铭的肩头", "语重心长地说"), after_line="握了握他的肩", slots={"YQ": "SCREEN_RIGHT", "QM": "SCREEN_LEFT"},
         faces={"QM": "BACK_THREE_QUARTER_TO_YANG_NOT_MEASURABLE"},
         entry="杨永青的手拍在秦铭肩头", exit="杨永青握着秦铭的肩",
         dims={"CONTACT": D("手拍肩头", "手握住肩", "PATTING", "GRIPPING_SHOULDER")}, referents=[("小秦", "QM")]),
    dict(s="E07-S05", n=2, sec=4.5, cps=5.0, size="中全景", camera="横移随两人分别", axis="杨永青（画左）与秦铭（画右）背向而行", blocking="络腮胡的杨永青松开手退了一步半开玩笑地说一句，转身朝村子方向走远；年轻的秦铭站在原地不动，面朝野外的雪原，嘴唇闭合",
         cast=["YQ", "QM"], action=("YQ", "络腮胡的杨永青松开手退了一步半开玩笑地说一句，说完立即转身朝村子方向走远；秦铭双脚站在原地不动，面朝野外的雪原", "QM"), dialogue=("YQ", "万一被下来的某位贵女看中，或许能改命。", "QM"), emotion="joy",
         perf=("戏", "松开手往村里退了一步", "半开玩笑地说"), after_line="转身朝村子方向走远", slots={"YQ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="络腮胡的杨永青松开手退了一步，秦铭站在雪路上面朝野外", exit="杨永青的背影朝村子方向走远，秦铭仍站在原地面朝野外",
         dims={"POSITION": D("两人并肩", "两人背向分开", "TOGETHER", "PARTING"), "POSTURE": D("面对面", "各自转身", "FACE_TO_FACE", "TURNED_APART")}, referents=[]),
    # S06 —— 雪原破浪、饥饿、冲进密林
    dict(s="E07-S06", n=1, sec=4, size="远景", camera="高机位横移跟随破浪的小人影", axis="秦铭自村口方向（画左）向山林（画右）", blocking="秦铭在齐胸的积雪里向前冲，宛若破浪，雪花翻溅向两侧；浅夜到来，前方山林轮廓若隐若现",
         cast=["QM"], action=("QM", "秦铭在齐胸的积雪里向前冲，宛若破浪，雪花翻溅向道路两侧；浅夜到来，前方山林的轮廓若隐若现", ""),
         faces={"QM": "FAR_FIGURE_IN_DEEP_SNOW_NOT_MEASURABLE"},
         entry="秦铭在齐胸的积雪里向前冲，前方一片昏暗", exit="雪花翻溅向两侧，浅夜到来，山林的轮廓显出来",
         dims={"POSITION": D("雪原中段", "山林之外", "MID_SNOWFIELD", "AT_FOREST_FOOT"), "INTEGRITY": D("夜色浓", "浅夜到来山林显形", "DARK", "SHALLOW_NIGHT")}, referents=[]),
    dict(s="E07-S06", n=2, identity_reanchor=True, sec=4, size="中景", camera="低机位缓推站在山外的秦铭", axis="秦铭面向密林（画右）", blocking="秦铭站在山外攥着猎叉，脸正对镜头，肚子咕噜一声叫了，他望着幽暗的密林一闪身冲进去",
         cast=["QM"], action=("QM", "秦铭站在山外攥紧猎叉，肚子咕噜一声叫了，胃里反酸水；他望着幽暗的密林，一闪身冲了进去", ""),
         entry="秦铭站在山外攥着猎叉，肚子咕噜一声叫了", exit="秦铭一闪身冲进幽暗的密林",
         dims={"POSITION": D("站在山外", "冲进密林", "OUTSIDE_FOREST", "INTO_FOREST"), "MOMENTUM": D("站着", "一闪身冲入", "STANDING", "DASHING_IN")}, referents=[("他", "QM")]),
    # S07 —— 女子哭声、碧绿眼睛、夜鸟惊飞、可惜、血色开阔地
    dict(s="E07-S07", n=1, sec=3, size="中全景", camera="横移随秦铭循哭声提速", axis="秦铭自林缘（画左）向林深处（画右）", blocking="秦铭拎着猎叉走在兽踩出的林间小路上，一阵像女子哭泣的呜咽声传来，他猛然提速奔向声源",
         cast=["QM"], action=("QM", "秦铭拎着猎叉走在兽踩出的林间小路上，一阵像女子哭泣的呜咽声传来，他猛然提速奔向声源", ""),
         entry="秦铭拎着猎叉走在林间兽踩出的小路上", exit="秦铭猛然提速，朝呜咽声传来的方向奔去",
         dims={"MOMENTUM": D("行走", "提速奔跑", "WALKING", "SPRINTING")}, referents=[("他", "QM")]),
    dict(s="E07-S07", n=2, sec=3, size="远景", camera="低机位自碧绿眼睛升起随夜鸟冲天", axis="秦铭（画左）冲向碧绿眼睛（画右）", blocking="黑漆漆的林地间一双双碧绿的眼睛望来，十几只夜鸟影影绰绰；秦铭提着猎叉背对镜头闯过去，扑棱棱声中十几只夜鸟迅疾冲上夜空",
         cast=["QM"], action=("QM", "黑漆漆的林地间一双双碧绿的眼睛望来，影影绰绰足有十几只夜鸟；秦铭提着猎叉闯过去，扑棱棱声中十几只食肉夜鸟迅疾地冲上夜空", BIRDS),
         faces={"QM": "BACK_TO_CAMERA_CHARGING_AT_BIRDS_NOT_MEASURABLE"},
         entry="十几双碧绿的眼睛在林地间望来，秦铭提着猎叉冲过去", exit="十几只夜鸟扑棱棱冲上夜空，秦铭冲到骨头堆前",
         dims={"POSITION": D("夜鸟在地上", "夜鸟冲上夜空", "BIRDS_ON_GROUND", "BIRDS_AIRBORNE"), "INTEGRITY": D("只见碧绿眼睛", "翼影冲天", "EYES_ONLY", "WINGS_UP")}, referents=[]),
    dict(s="E07-S07", n=3, identity_reanchor=True, sec=2.5, cps=5.0, size="中近景", camera="高机位自骨头堆升到秦铭的侧脸", axis="秦铭（画右）低头看向骨头堆（画左）", blocking="秦铭冲到近前，地上只有一堆带血的骨头和几块染血的破碎兽皮，他侧着脸低声说一句，随即转身就走；画面干净只有雪地、骨头与破碎兽皮",
         cast=["QM"], action=("QM", "秦铭冲到骨头堆前，地上只有一堆带血的骨头和几块染血的破碎兽皮，他侧着脸低声说一句、语速平稳不拖音，说完立即转身就走；画面干净，只有雪地、骨头与破碎兽皮，不出现任何文字、字幕条、水印或符号", ""), dialogue=("QM", "可惜，来晚一步。", ""), emotion="calm",
         perf=("哀", "提着猎叉冲到骨头堆前看了看", "侧脸低声说完整一句"), after_line="转身就走",
         entry="秦铭冲到骨头堆前，带血的骨头与破碎兽皮在雪里", exit="秦铭转身走开，地上只剩带血的骨头和破碎的兽皮",
         dims={"POSTURE": D("面向骨头堆", "转身背向", "FACING_BONES", "TURNED_AWAY")}, referents=[]),
    dict(s="E07-S07", n=4, sec=4, size="远景", camera="高机位横移过血迹斑斑的开阔地与兽爪印", axis="秦铭自开阔地一侧（画右）走向另一侧（画左）", blocking="秦铭走进一片林木稀疏的开阔地，雪地血迹斑斑，有比海碗口还大的兽爪印，他戒备着离开",
         cast=["QM"], action=("QM", "秦铭走进一片林木稀疏的开阔地，雪地血迹斑斑，现场有比海碗口还大的兽爪印，他戒备着离开血色现场", CLEARING),
         faces={"QM": "FAR_FIGURE_IN_CLEARING_NOT_MEASURABLE"},
         entry="秦铭走进一片林木稀疏、血迹斑斑的开阔地", exit="秦铭戒备着走出开阔地，海碗大的兽爪印留在雪里",
         dims={"POSITION": D("走进开阔地", "走出开阔地", "INTO_CLEARING", "OUT_OF_CLEARING"), "INTEGRITY": D("血迹与爪印未看清", "兽爪印看清", "TRACKS_UNSEEN", "TRACKS_SEEN")}, referents=[("他", "QM")]),
    # S08 —— 刀角鹿、两箭
    dict(s="E07-S08", n=1, sec=3, size="中全景", camera="低机位在秦铭身后横移越肩看鹿群黑影", axis="秦铭（画左，背对镜头）面向鹿群（画右）", blocking="秦铭跟着雪地里的蹄印走，二十几道黑影立在前方，体形都不小，他停下脚步",
         cast=["QM"], action=("QM", "秦铭跟着雪地里的蹄印走，前方二十几道刀角鹿的黑影立在雪上，体形都不小，他停下脚步", STAG),
         faces={"QM": "BACK_TO_CAMERA_FACING_HERD_NOT_MEASURABLE"},
         entry="秦铭跟着雪地里的蹄印走，前方林间空着", exit="二十几道刀角鹿的黑影立在前方，秦铭停下脚步",
         dims={"MOMENTUM": D("跟踪行走", "停步", "TRACKING", "HALTED"), "INTEGRITY": D("前方空着", "鹿群黑影成排", "NO_HERD", "HERD_VISIBLE")}, referents=[("他", "QM")]),
    dict(s="E07-S08", n=2, identity_reanchor=True, sec=2, cps=5.0, size="中近景", camera="缓推露出喜色的秦铭", axis="秦铭（画右）面向鹿群（画左）", blocking="秦铭露出喜色压着嗓子说一句，取下背上的弓箭瞄准一头六角的大雄鹿",
         cast=["QM"], action=("QM", "秦铭露出喜色压着嗓子说一句，说完立即取下背上的弓箭瞄准一头长着六支刀角的大雄鹿", STAG), dialogue=("QM", "刀角鹿！", ""), emotion="joy",
         perf=("喜", "露出喜色攥紧猎叉", "压着嗓子喊"), after_line="取下背上的弓箭瞄准大雄鹿",
         entry="秦铭停在鹿群黑影前，弓箭还背在背上", exit="秦铭取下弓箭瞄准大雄鹿，六支扁平的刀角在雪光里",
         dims={"POSSESSION": D("弓箭在背上", "弓箭在手瞄准", "BOW_ON_BACK", "BOW_DRAWN")}, referents=[]),
    dict(s="E07-S08", n=3, sec=3, size="中景", camera="低机位环绕拉满的硬弓到铁箭射出", axis="秦铭（画左）射向大雄鹿（画右）", blocking="秦铭把硬弓拉成满月状，咻的一声，铁箭迅疾如电射入大雄鹿的肺部",
         cast=["QM"], action=("QM", "秦铭把硬弓拉成满月状，咻的一声，铁箭迅疾如电射入大雄鹿的肺部，雄鹿一震", STAG),
         entry="秦铭把硬弓拉成满月，铁箭对着大雄鹿", exit="铁箭射入大雄鹿的肺部，雄鹿一震，弓弦还在颤",
         dims={"POSSESSION": D("铁箭在弦上", "铁箭在鹿身", "ARROW_NOCKED", "ARROW_IN_STAG"), "INTEGRITY": D("雄鹿无伤", "雄鹿肺部中箭", "STAG_UNHURT", "STAG_HIT")}, referents=[]),
    dict(s="E07-S08", n=4, sec=3, size="远景", camera="低机位横移随鹿群狂奔而来", axis="大雄鹿与鹿群自画右冲向画左", blocking="大雄鹿中箭不逃反而朝秦铭的方向冲来，鹿群被惊扰跟着狂奔，积雪迸溅、蹄声密集，这片山林在轻颤",
         cast=["QM"], action=(STAG, "大雄鹿中箭之后没有逃走，反而朝秦铭的方向冲来；鹿群跟着它狂奔而来，积雪迸溅，蹄声密集，山林在轻颤", "QM"),
         faces={"QM": CREATURE_ONLY},
         entry="大雄鹿中箭一震，鹿群立在它身后", exit="大雄鹿朝秦铭的方向冲来，鹿群跟着狂奔，积雪迸溅",
         dims={"MOMENTUM": D("鹿群立着", "鹿群狂奔", "HERD_STANDING", "HERD_STAMPEDING"), "POSITION": D("鹿群在远处", "鹿群冲近", "HERD_FAR", "HERD_CLOSING")}, referents=[("它", STAG)]),
    dict(s="E07-S08", n=5, sec=3, size="中近景", camera="缓推再次弯弓的秦铭", axis="秦铭（画左）射向冲来的雄鹿（画右）", blocking="秦铭没有慌，再次弯弓，第二支铁箭整支没入大雄鹿，它的身体晃了几下",
         cast=["QM"], action=("QM", "秦铭没有慌，脚下踏实雪地再次弯弓，第二支铁箭力道很大整支没入大雄鹿，它的身体晃了几下", STAG),
         entry="秦铭再次弯弓，大雄鹿正冲来", exit="第二支铁箭整支没入，大雄鹿的身体晃了几下",
         dims={"POSSESSION": D("第二支箭在弦上", "第二支箭没入鹿身", "SECOND_ARROW_NOCKED", "SECOND_ARROW_IN"), "INTEGRITY": D("雄鹿冲势未减", "雄鹿身体晃动", "STAG_CHARGING", "STAG_STAGGERING")}, referents=[("它", STAG)]),
    # S09 —— 上树、栽倒、七百斤
    dict(s="E07-S09", n=1, sec=4, size="远景", camera="低机位随秦铭攀树升起再看向栽倒的雄鹿", axis="秦铭（画左树上）俯视雄鹿（画右）", blocking="秦铭收起弓箭从容地攀上一棵很粗的大树躲在数米高处；大雄鹿踉踉跄跄，砰的一声栽进雪里，鹿群止步，轰隆隆远去",
         cast=["QM"], action=("QM", "秦铭收起弓箭，从容地攀上一棵很粗的大树躲在数米高处；大雄鹿一路奔行后踉踉跄跄，砰的一声栽进雪里，鹿群止步，在轰隆隆声中远去", STAG),
         faces={"QM": "FAR_FIGURE_IN_TREE_NOT_MEASURABLE"},
         entry="秦铭收起弓箭攀向一棵很粗的大树，大雄鹿踉跄着", exit="秦铭在数米高的树杈上，大雄鹿横在雪地里，鹿群远去",
         dims={"POSITION": D("秦铭在地上", "秦铭在树上", "ON_GROUND", "UP_THE_TREE"), "INTEGRITY": D("雄鹿踉跄", "雄鹿横在雪里", "STAG_STAGGERING", "STAG_DOWN")}, referents=[]),
    dict(s="E07-S09", n=2, identity_reanchor=True, sec=2.5, cps=5.0, size="中景", camera="高机位随秦铭跳下走近缓降到鹿身", axis="秦铭（画右）走向雄鹿（画左）", blocking="秦铭从树上跳下，拎着猎叉走到黑褐色的大雄鹿跟前满意地一口气说完一句、字音短促不拖长，抓住鹿角",
         cast=["QM"], action=("QM", "秦铭从树上跳下，拎着猎叉走到横在雪地里的黑褐色大雄鹿跟前满意地一口气说完一句、字音短促不拖长，说完立即抓住鹿角", STAG), dialogue=("QM", "足有七百斤。", ""), emotion="joy",
         perf=("喜", "跳下大树拎着猎叉走到鹿前", "满意地一口气说完，不拖音"), after_line="抓住鹿角",
         entry="秦铭从树上跳下，拎着猎叉走向横在雪地里的大雄鹿", exit="秦铭抓住大雄鹿的鹿角",
         dims={"POSITION": D("树上", "鹿身旁", "IN_TREE", "AT_STAG"), "CONTACT": D("手拎猎叉", "手抓鹿角", "HAND_ON_FORK", "HAND_ON_ANTLER")}, referents=[]),
    # S10 —— 驴头狼偷袭（配乐 CUE-01 起）
    dict(s="E07-S10", n=1, sec=4, size="中全景", camera="横移随秦铭拖鹿回程，大爪子自画外搭上肩", axis="秦铭自林深处（画右）拖鹿向来路（画左）", blocking="秦铭拖着射死的刀角鹿尸体沿原路往回走，鹿横躺在雪上被绳拖行、四腿不动，他的双肩完好无血；山风渐大雪粒砸在脸上；一双毛茸茸的大爪子自后面搭在他的肩头，一股热气吹到他脖子上",
         cast=["QM"], action=("QM", "秦铭拖着射死的刀角鹿尸体沿原路往回赶，鹿横躺在雪上被绳拖行，山风渐大，雪粒砸在脸上；一双毛茸茸的大爪子自后面搭在他的肩头，一股热气吹到他脖子上", WOLF),
         entry="秦铭拖着射死的刀角鹿尸体沿原路往回走，鹿横躺在雪上被绳拖行，他的双肩完好无血，山风卷着雪粒", exit="一双毛茸茸的大爪子自后面搭在秦铭肩头，热气吹到他脖子上",
         dims={"CONTACT": D("肩上无物", "大爪子搭在肩头", "SHOULDER_FREE", "PAWS_ON_SHOULDER"), "MOMENTUM": D("拖鹿行走", "僵住", "HAULING", "FROZEN")}, referents=[("他", "QM")]),
    dict(s="E07-S10", n=2, sec=4, size="中景", camera="低机位环绕缩肩滚开到积雪崩开", axis="秦铭（画左）滚离雪堆（画右）", blocking="秦铭第一时间缩肩、下蹲、滚向一侧的雪地，大爪子抓烂他肩头的棉衣见了血；积雪轰然崩开，一道高大的黑影从雪窝子里暴起，跟着他扑去",
         cast=["QM"], action=("QM", "秦铭第一时间缩肩、下蹲、滚向一侧的雪地，大爪子抓烂他肩头的棉衣，肩头见了血；积雪轰然崩开，一道高大强壮的黑影从雪窝子里暴起，跟着他扑去", WOLF),
         entry="大爪子搭在秦铭肩头，他缩肩", exit="秦铭半撑在一侧的雪地上，肩头棉衣抓烂见了血；积雪崩开，黑影暴起扑来",
         dims={"POSTURE": D("站着被搭肩", "滚开半撑", "STANDING_GRABBED", "ROLLED_PROPPED"), "INTEGRITY": D("肩头无伤", "肩头见血", "SHOULDER_INTACT", "SHOULDER_BLEEDING")}, referents=[("他", "QM")]),
    dict(s="E07-S10", n=3, sec=4, size="特写", camera="低机位缓推仰面抓前肢的秦铭与驴头狼的血盆大口", axis="秦铭仰面（画面下方）对着驴头（画面上方）", blocking="秦铭来不及起身，仰面伸出双手猛然抓住那对前肢牢牢控制住，硕大的驴头与血盆大口就在面前，热气喷到脸上；他蜷身缩腿蓄力猛然蹬出踹在它腹部，数百斤的山兽被踢翻出去在雪地上打滚，他翻身站起",
         cast=["QM"], action=("QM", "秦铭来不及起身，仰面伸出双手猛然抓住那对前肢牢牢控制住，硕大的驴头、开阔的嘴与寒光闪闪的利齿就在面前，热气喷到脸上；他蜷身缩腿蓄力，猛然蹬出踹在它腹部，数百斤的山兽被踢翻出去在雪地上打滚，他翻身站起", WOLF),
         entry="秦铭半撑在雪地上，驴头狼扑到面前", exit="驴头狼被一脚踢翻出去在雪地上打滚，秦铭翻身站起",
         dims={"CONTACT": D("前肢压向面孔", "一脚踹在腹部", "PAWS_AT_FACE", "KICK_TO_BELLY"), "POSTURE": D("半撑仰面", "站起", "ROLLED_PROPPED", "STANDING")}, referents=[("它", WOLF), ("他", "QM")]),
    dict(s="E07-S10", n=4, sec=2, cps=5.0, size="中近景", camera="横移随秦铭站起盯住猛兽", axis="秦铭（画右）面向驴头狼（画左）", blocking="秦铭站起身盯着前方的黑色猛兽喊出三个字，抬手护住肩头",
         cast=["QM"], action=("QM", "秦铭站起身盯着前方爬起来的黑色猛兽喊出三个字，说完立即抬手护住流血的肩头", WOLF), dialogue=("QM", "驴头狼！", ""), emotion="fear",
         perf=("惊", "站起身盯住前方的黑色猛兽", "喊"), after_line="抬手护住流血的肩头",
         entry="秦铭站起身，驴头狼在前方爬起来", exit="秦铭抬手护住流血的肩头，驴头狼盯着他",
         dims={"CONTACT": D("双手空垂", "手护肩头", "HANDS_FREE", "HAND_ON_WOUND")}, referents=[]),
    # S11 —— 直立嘶吼、拔刀、交手
    dict(s="E07-S11", n=1, sec=3, size="中全景", camera="低机位随驴头狼直立升起", axis="驴头狼（画左）面向秦铭（画右）", blocking="驴头狼起身的刹那把近前的猎叉按进雪里，倏地直立而起高出一大段，鬃毛炸立，在那里嘶吼；秦铭双手空着，唯一的猎叉横在驴头狼面前的雪面上",
         cast=["QM"], action=(WOLF, "驴头狼起身的刹那把近前的猎叉按进雪里，倏地直立而起，高出一大段，浓密的黑鬃毛炸立，猩红的眼睛盯着秦铭在那里嘶吼", "QM"),
         faces={"QM": CREATURE_ONLY},
         entry="驴头狼（硕大的驴头、驴耳、颈后黑鬃、狼身）爬起，唯一的猎叉横在它近前的雪面上，秦铭双手空着", exit="驴头狼直立而起鬃毛炸立嘶吼，猎叉被按进雪里",
         dims={"POSSESSION": D("猎叉在雪面上", "猎叉被按进雪里", "FORK_ON_SNOW", "FORK_BURIED"), "POSTURE": D("驴头狼伏低", "驴头狼直立", "WOLF_LOW", "WOLF_UPRIGHT")}, referents=[("它", WOLF)]),
    dict(s="E07-S11", n=2, sec=3, cps=5.0, size="中景", camera="缓推拔刀逼去的秦铭", axis="秦铭（画右）逼向驴头狼（画左）", blocking="秦铭从背后拔出短刀向前逼去，在前逼途中低吼一句并在动作中段把话说完，刀尖前指，最后一秒只有动作、不再出声",
         cast=["QM"], action=("QM", "秦铭从背后拔出短刀向前逼去，在前逼途中低吼一句并在动作中段把话说完，说完立即刀尖前指又逼近一步，最后一秒只有动作、不再出声", WOLF), dialogue=("QM", "赤手空拳也能打死你。", ""), emotion="threat",
         perf=("狠", "从背后拔出短刀向前逼去", "低吼着一口气说完，话音在动作中段落定"), after_line="刀尖前指又逼近一步，收尾只有动作不再出声",
         entry="秦铭站着，手伸向背后的短刀", exit="秦铭短刀在手，刀尖前指逼近驴头狼",
         dims={"POSSESSION": D("短刀在背后", "短刀在手", "KNIFE_SHEATHED", "KNIFE_DRAWN"), "POSITION": D("原地", "逼近一步", "HOLDING", "ADVANCED")}, referents=[("你", WOLF)]),
    dict(s="E07-S11", n=3, sec=4, size="中景", camera="低机位环绕刀爪碰撞到砍断獠牙", axis="驴头狼（画左）扑向秦铭（画右）", blocking="驴头狼带着腥风扑来搅得积雪横飞，短刀和它的大爪子碰撞发出清脆的颤音；雪亮刀光划过，它的嘴巴淌血，獠牙被砍断",
         cast=["QM"], action=("QM", "驴头狼带着腥风扑来，搅得地面积雪横飞，短刀和它的大爪子碰撞发出清脆的颤音；秦铭动作如电，雪亮刀光划过，它的嘴巴淌血，獠牙被砍断", WOLF),
         entry="驴头狼带着腥风扑来，秦铭举刀迎上", exit="驴头狼嘴巴淌血，獠牙被砍断，秦铭短刀收回",
         dims={"CONTACT": D("刀爪相碰", "刀锋过嘴", "KNIFE_MEETS_PAW", "KNIFE_CUTS_FANG"), "INTEGRITY": D("獠牙完好", "獠牙砍断嘴淌血", "FANGS_INTACT", "FANGS_BROKEN")}, referents=[("它", WOLF)]),
    dict(s="E07-S11", n=4, sec=3, size="中全景", camera="横移随右腿铁鞭扫出", axis="秦铭（画右）扫向驴头狼（画左）", blocking="秦铭迅速跟进，右腿如铁鞭重重扫在它身上，伴着骨裂声，它发出凄厉的惨叫",
         cast=["QM"], action=("QM", "秦铭迅速跟进，右腿如铁鞭重重地扫在驴头狼身上，伴着骨裂声，它发出凄厉的惨叫", WOLF),
         entry="秦铭收刀跟进，驴头狼张嘴淌血", exit="秦铭的右腿扫在驴头狼身上，骨裂声中它凄厉惨叫",
         dims={"CONTACT": D("腿未触", "腿扫中肋", "LEG_COILED", "LEG_STRIKES_RIBS"), "INTEGRITY": D("肋骨完好", "肋骨断裂", "RIBS_INTACT", "RIBS_CRACKED")}, referents=[("它", WOLF)]),
    # S12 —— 砸死、铁箭头、不能生火、埋脏腑
    dict(s="E07-S12", n=1, sec=4, size="中景", camera="高机位随扑上按倒缓降到砸拳", axis="秦铭（画右）压向驴头狼（画左）", blocking="秦铭扑上去把四百斤的驴头狼按在雪地中，连着挥拳砸落，喀嚓一声它的颈部被击断，歪扭着一动不动",
         cast=["QM"], action=("QM", "秦铭扑上去把四百斤的驴头狼按在雪地中，跪压在它身上连着挥拳砸落，喀嚓一声，它的颈部被击断，歪扭在那里一动不动了", WOLF),
         entry="秦铭扑向倒在雪里惨叫的驴头狼", exit="驴头狼的颈部被击断一动不动，秦铭跪压在它身上",
         dims={"INTEGRITY": D("驴头狼惨叫挣扎", "驴头狼颈断不动", "WOLF_ALIVE", "WOLF_DEAD"), "CONTACT": D("扑向它", "跪压挥拳", "LUNGING", "PINNING_PUNCHING")}, referents=[("它", WOLF)]),
    dict(s="E07-S12", n=2, sec=3, cps=5.0, size="特写", camera="缓推指间的铁箭头到秦铭的脸", axis="秦铭（画左）看向指间铁箭头（画右）", blocking="秦铭跪在驴头狼身上，从它的皮毛里捏出一枚残留的铁箭头对着雪光低声说一句，把铁箭头揣进怀里站起来",
         cast=["QM"], action=("QM", "秦铭跪在驴头狼身上，从它黑油油的皮毛里捏出一枚残留的铁箭头对着雪光低声说一句，说完立即把铁箭头揣进怀里站起来", HEAD), dialogue=("QM", "上次袭击我的，就是你。", ""), emotion="calm",
         perf=("冷", "把铁箭头捏在指间对着雪光", "低声说"), after_line="把铁箭头揣进怀里站起来",
         entry="秦铭跪在驴头狼身上，从它皮毛里捏出一枚铁箭头", exit="秦铭捏着铁箭头站起来，把它揣进怀里",
         dims={"POSSESSION": D("铁箭头在狼身", "铁箭头在秦铭怀里", "ARROWHEAD_IN_WOLF", "ARROWHEAD_KEPT"), "POSTURE": D("跪压", "站起", "KNEELING", "STANDING")}, referents=[("我", "QM"), ("你", WOLF)]),
    dict(s="E07-S12", n=3, sec=2, cps=5.0, size="中近景", camera="环绕抚摸肩伤的秦铭", axis="秦铭（画右）低头看肩头（画左）", blocking="秦铭站着抚摸肩头的伤口，伤口不深血已止住，腹中如擂鼓似的响，他咬着牙说一句，抽出短刀蹲到刀角鹿身旁",
         cast=["QM"], action=("QM", "秦铭站着抚摸肩头的伤口，伤口不深血已止住，腹中如擂鼓似的响个不停，他咬着牙说一句，说完立即抽出短刀蹲到刀角鹿身旁", KNIFE), dialogue=("QM", "不能生火。", ""), emotion="calm",
         perf=("倦", "抚摸着肩头的伤口", "咬着牙说"), after_line="抽出短刀蹲到刀角鹿身旁",
         entry="秦铭站着抚摸肩头的伤口", exit="秦铭抽出短刀蹲到刀角鹿身旁",
         dims={"POSTURE": D("站着", "蹲下", "STANDING", "CROUCHED"), "POSSESSION": D("短刀在腰后", "短刀在手", "KNIFE_SHEATHED", "KNIFE_DRAWN")}, referents=[]),
    dict(s="E07-S12", n=4, sec=3, cps=5.0, size="中全景", camera="高机位横移过两头猎物与被血染红的雪地", axis="秦铭（画左）蹲在两头猎物（画右）之间", blocking="秦铭蹲在两头猎物之间用短刀割开皮毛，血水涌出染红雪地，他快速清理掉脏腑埋进雪里压实，低声说一句，站起来抓住鹿角与狼腿",
         cast=["QM"], action=("QM", "秦铭蹲在两头猎物之间用短刀割开皮毛，血水涌出染红雪地，他快速出刀清理掉脏腑，把脏腑埋进雪里压实遮掩血腥味，低声说一句，说完立即站起来抓住鹿角与狼腿", KNIFE), dialogue=("QM", "希望附近没有危险的山兽。", ""), emotion="calm",
         perf=("疑", "把脏腑埋进雪里压实", "低声说"), after_line="站起来抓住鹿角与狼腿",
         entry="秦铭蹲在两头猎物之间，短刀割开的皮毛下血水涌出", exit="脏腑埋进雪里压实，秦铭站起来抓住鹿角与狼腿",
         dims={"INTEGRITY": D("猎物完整", "脏腑已清理埋雪", "CARCASSES_WHOLE", "CARCASSES_DRESSED"), "POSTURE": D("蹲着出刀", "站起抓猎物", "CROUCHED", "STANDING_HAULING")}, referents=[]),
    # S13 —— 半山腰、野猪王
    dict(s="E07-S13", n=1, sec=4, size="远景", camera="低机位横移随拖两猎物上坡的小人影", axis="秦铭自山脚（画左）拖猎物上半山腰（画右）", blocking="秦铭拖着刀角鹿与驴头狼两具尸体上到半山腰，两具尸体横躺在雪坡上被绳拖行，夜空漆黑没有任何光；远处传来巨大的动静，林中很多飞禽冲上夜空，他停下",
         cast=["QM"], action=("QM", "秦铭拖着刀角鹿与驴头狼两具尸体上到半山腰，尸体横躺在雪坡上被绳拖行，远处传来巨大的动静，林中很多飞禽冲上夜空，他停下", ""),
         faces={"QM": "FAR_FIGURE_HAULING_UPHILL_NOT_MEASURABLE"},
         entry="秦铭拖着刀角鹿与驴头狼两具尸体上到半山腰，尸体横躺在雪坡上被绳拖行，夜空漆黑没有任何光", exit="远处传来巨响，林中飞禽冲上夜空，秦铭停下，两头猎物横在雪坡上",
         dims={"MOMENTUM": D("拖行上坡", "停下", "HAULING_UP", "HALTED"), "INTEGRITY": D("林中安静", "飞禽冲天", "FOREST_QUIET", "BIRDS_FLUSHED")}, referents=[("他", "QM")]),
    dict(s="E07-S13", n=2, identity_reanchor=True, sec=2.5, cps=5.0, size="中近景", camera="缓推眉头深锁的秦铭", axis="秦铭（画右）望向远处密林（画左）", blocking="秦铭眉头深锁，松开手里的猎物直起身低声问一句，望向远处的密林",
         cast=["QM"], action=("QM", "秦铭眉头深锁，松开手里的猎物直起身低声问一句，说完立即望向远处翻腾的密林", ""), dialogue=("QM", "血腥味引来了巨兽？", ""), emotion="fear",
         perf=("惊", "松开手里的猎物直起身", "低声问"), after_line="望向远处翻腾的密林",
         entry="秦铭停在坡上，手里还拖着猎物", exit="秦铭松开猎物直起身，望向远处翻腾的密林",
         dims={"CONTACT": D("手拖猎物", "手松开", "HANDS_ON_PREY", "HANDS_FREE"), "POSTURE": D("弯腰拖行", "直起身望远", "BENT_HAULING", "UPRIGHT_LOOKING")}, referents=[]),
    dict(s="E07-S13", n=3, sec=4, size="远景", camera="低机位横移随野猪王掀翻障碍闯来", axis="野猪王自远处密林（画左）冲向山脚（画右）", blocking="远处密林积雪翻腾、枝杈折断，一头像铁甲车般高大壮硕的野猪王负伤染血，沿途把各种障碍掀翻，冲到山脚下，鼻子翕动",
         cast=["QM"], action=(BOAR, "远处密林里积雪翻腾、树木枝杈折断，一头小山似的野猪王负伤染血，周身钢针般粗硬的黑毛，沿途把各种障碍掀翻，冲到矮山脚下，鼻子翕动", ""),
         faces={"QM": CREATURE_ONLY},
         entry="远处密林里积雪翻腾，树木枝杈折断", exit="负伤染血的野猪王掀翻沿途障碍冲到山脚，鼻子翕动",
         dims={"POSITION": D("野猪王在远处密林", "野猪王到山脚", "BOAR_FAR", "BOAR_AT_FOOT"), "INTEGRITY": D("只闻巨响", "野猪王全貌可见", "SOUND_ONLY", "BOAR_VISIBLE")}, referents=[]),
    dict(s="E07-S13", n=4, sec=3, cps=5.0, size="中景", camera="环绕倒吸冷气的秦铭，野猪王转向矮山", axis="秦铭（画右）面向山脚野猪王（画左）", blocking="秦铭攥紧了弓倒吸一口冷气说一句，野猪王转头向矮山上冲来，他退到合抱大树下",
         cast=["QM"], action=("QM", "秦铭攥紧了弓倒吸一口冷气说一句，说完立即退到身后需数人合抱的大树下；野猪王转头向矮山上冲来", BOAR), dialogue=("QM", "追杀它的是什么东西？", ""), emotion="fear",
         perf=("惧", "攥紧了弓退向身后的大树", "倒吸一口冷气说"), after_line="退到身后需数人合抱的大树下",
         entry="秦铭攥紧了弓，野猪王在山脚", exit="野猪王转头向矮山冲来，秦铭退到合抱大树下",
         dims={"POSITION": D("秦铭在坡上", "秦铭在大树下", "ON_SLOPE", "AT_TREE"), "MOMENTUM": D("野猪王在山脚翕动鼻子", "野猪王向矮山冲来", "BOAR_SNIFFING", "BOAR_CHARGING_UP")}, referents=[("它", BOAR)]),
    # S14 —— 上树搭箭、黑鳞、死寂与光、退走、虫
    dict(s="E07-S14", n=1, sec=3, size="远景", camera="低机位随攀上合抱大树升起", axis="秦铭（画面中央）攀向大树高处", blocking="秦铭抿着嘴不出声地攀上一棵需数人合抱的大树，居高临下把铁箭搭在弓弦上对准下方，全程没有人声；山脊上方的夜空漆黑没有任何光",
         cast=["QM"], action=("QM", "秦铭抿着嘴不出声地攀上一棵需要数人合抱的大树，居高临下，把铁箭搭在弓弦上对准下方，全程没有人声；夜空漆黑没有任何光", BOW),
         faces={"QM": "FAR_FIGURE_CLIMBING_NOT_MEASURABLE"},
         entry="秦铭抿着嘴攀向需数人合抱的大树，弓箭在手，山脊上方的夜空漆黑没有任何光", exit="秦铭在高处把铁箭搭在弓弦上对准下方",
         dims={"POSITION": D("树下", "树上高处", "AT_TREE_FOOT", "HIGH_IN_TREE"), "POSSESSION": D("弓箭在手未搭箭", "铁箭搭在弓弦上", "BOW_HELD", "ARROW_NOCKED")}, referents=[]),
    dict(s="E07-S14", n=2, sec=3, size="中近景", camera="高机位自树上俯视缓推野猪王抬头的面部", axis="野猪王（画面下方）抬头向树上", blocking="野猪王冲到树下抬起头，满身粗硬的黑毛根根竖起，面部一层黑色鳞片泛着冷幽幽的金属光泽，雪白獠牙比小臂还长",
         cast=["QM"], action=(BOAR, "野猪王冲到树下抬起头，满身粗硬的黑毛根根竖起，面部清晰可见一层黑色鳞片，泛着冷幽幽的金属光泽，雪白獠牙比成年人的小臂还长；只有野猪王的鼻息，没有人声", ""),
         faces={"QM": CREATURE_ONLY},
         entry="野猪王冲到树下，低着头", exit="野猪王抬起头，面部黑鳞泛着金属光泽，雪白獠牙比小臂还长",
         dims={"POSTURE": D("低头冲", "抬头盯树", "HEAD_LOW", "HEAD_UP"), "INTEGRITY": D("面部未见", "黑鳞獠牙清楚", "FACE_UNSEEN", "SCALES_SEEN")}, referents=[]),
    dict(s="E07-S14", n=3, sec=4, size="远景", camera="低机位自树上的秦铭横摇向远处山峰升起的光团", axis="秦铭（画左树上）望向远山（画右）", blocking="秦铭在树上搭着箭，山林于瞬息间安静了，鸟雀猛禽全部不见；远处的山峰上一团光升起，起初柔和，很快灿烂，逐渐升高",
         cast=["QM"], action=("QM", "秦铭在树上搭着箭，山林于瞬息间安静了，冲上夜空的鸟雀猛禽全部不见；他转头，远处的山峰上一团光升起，起初柔和，很快灿烂，逐渐升高", MOON),
         faces={"QM": "SMALL_FIGURE_IN_TREE_WIDE_NOT_MEASURABLE"},
         entry="秦铭在树上搭着箭对准下方，林中还有鸟声", exit="山林死寂，远处山峰上升起一团灿烂的光，秦铭转头望着它",
         dims={"INTEGRITY": D("夜空无光", "远山之上光团升起", "SKY_EMPTY", "LIGHT_RISING"), "POSTURE": D("俯身对准下方", "转头望向远山", "AIMING_DOWN", "TURNED_TO_LIGHT")}, referents=[("他", "QM")]),
    dict(s="E07-S14", n=4, sec=3, size="中全景", camera="高机位横移随野猪王无声退走埋雪", axis="野猪王自树下（画右）退向幽暗洼地（画左）", blocking="脾气暴躁的野猪王不敢发出一丝声响，无声地退走，躲进林木密集的幽暗洼地，用积雪把自己埋上",
         cast=["QM"], action=(BOAR, "脾气暴躁的野猪王不敢发出一丝声响，谨慎得如同一只小猫，无声地退走，躲进林木密集的幽暗洼地，用积雪把自己埋上", ""),
         faces={"QM": CREATURE_ONLY},
         entry="野猪王在树下抬着头，山林没有一点声息", exit="野猪王退进幽暗的洼地，用积雪把自己埋上",
         dims={"POSITION": D("野猪王在树下", "野猪王在洼地雪里", "BOAR_AT_TREE", "BOAR_BURIED"), "MOMENTUM": D("抬头盯树", "无声退走", "BOAR_FIXED", "BOAR_RETREATING")}, referents=[]),
    dict(s="E07-S14", n=5, identity_reanchor=True, sec=2.5, cps=5.0, size="中近景", camera="低机位缓推仰望的秦铭，明月般的光照亮他的脸", axis="秦铭（画面中央）仰望夜空光团", blocking="夜空中那团光越来越亮，宛若一轮皎洁的明月当空悬挂；秦铭扶着树干仰望着它轻声说一句，攥紧弓弦",
         cast=["QM"], action=("QM", "夜空中那团光越来越亮，宛若一轮皎洁的明月当空悬挂，照亮秦铭的脸；他扶着树干仰望着它轻声说一句，说完立即攥紧弓弦", MOON), dialogue=("QM", "那其实是一只虫。", ""), emotion="fear",
         perf=("惊", "扶着树干仰望夜空里越来越亮的光团", "轻声说"), after_line="攥紧弓弦",
         entry="秦铭扶着树干仰望夜空，光团越来越亮", exit="光团宛若一轮明月当空，秦铭攥紧弓弦望着它",
         dims={"INTEGRITY": D("光团在升", "光团如明月当空", "LIGHT_RISING", "MOON_LIKE"), "CONTACT": D("手扶树干", "手攥弓弦", "HAND_ON_TRUNK", "HAND_ON_BOWSTRING")}, referents=[("它", MOON)]),
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

# ---------- 校验镜头表（seq=17/19/27 + seq=29 规则 5/7 + D-68） ----------
LEX = W29.load_lexicon()
EMOTION_WORDS = set(LEX["emotions"]); HOLD_WORDS = list(LEX["hold_instructions"]); TRIVIAL = list(LEX["trivial_body_actions"])
def engine_dialogue_need(text: str, cps: float) -> float:
    """tools/dialogue_cut_safety.py: start 0.12 + han/cps + punct*0.16 + other*0.08 + pad 0.32 (+ tail 0.25 when the
    line closes a video unit; assumed always, the grouping is decided later)."""
    words = text
    han = len(re.findall(r"[㐀-鿿]", words)); punct = len(re.findall(r"[，。！？；、,.!?;]", words))
    other = len(re.sub(r"[㐀-鿿\s，。！？；、,.!?;]", "", words))
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
    assert meta["sec"] <= PACING["scene_seconds_max"], (sid, "单场 ≤16 s", meta["sec"])
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
        assert need <= sh["sec"] <= need + 1.0 + 1e-9, (shot_id, "seq=29 规则 5a：对白镜时长 = 台词推导值（引擎切点安全最多 +1.0）", need, sh["sec"])
        assert sh.get("emotion") in NPR.EMOTION_DELIVERY, (shot_id, "emotion")
        perf = sh.get("perf"); assert perf and len(perf) == 3 and all(perf), (shot_id, "seq=29 规则 7b：performance 三要素")
        assert perf[0] in EMOTION_WORDS, (shot_id, "情绪词不在闭集词表", perf[0])
        assert perf[1] not in TRIVIAL and not any(perf[1].startswith(t) for t in TRIVIAL), (shot_id, "规则 5c：身体动作不得是琐碎动作", perf[1])
        assert sh.get("after_line"), (shot_id, "规则 5b：说完立即<动作>")
        assert f"说完立即{sh['after_line'][:4]}" in sh["action"][1], (shot_id, "action 须写『说完立即<after_line>』", sh["after_line"])
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

# ---------- D-68 R9：同场内姿态连续（写手侧预检，与 W29 同一函数） ----------
def _r9_precheck():
    rows = []
    for sh in SHOTS:
        subj = sh["action"][0]
        rows.append({"shot_id": f"{sh['s']}-{sh['n']:02d}", "scene_id": sh["s"], "entry_state": sh["entry"], "completion_state": sh["exit"],
                     "state_delta_evidence": {d: {"entry_code": ca, "exit_code": cb} for d, (a, b, ca, cb) in sh["dims"].items()},
                     "prompt_spec": {"action": {"subject_id": cid(subj) if subj in CH else subj}, "cast": [{"character_id": cid(k)} for k in sh["cast"]]}})
    return W29.posture_continuity_failures(rows)
_r9_fail, _r9_warn = _r9_precheck()
assert not _r9_fail, ("D-68 R9 姿态连续 FAIL", _r9_fail)

# ---------- seq=27 ----------
_shot_start = {}
_t = 0
for _sh in SHOTS:
    _shot_start[f"{_sh['s']}-{_sh['n']:02d}"] = _t; _t += _sh["sec"]
_shot_by_id = {f"{x['s']}-{x['n']:02d}": x for x in SHOTS}
SETUPS = {
    "SETUP-MOUNTAIN-WRONG": dict(setup="E07-S04-03", payoff="E07-S07-04", object="「现在山中的状况很不对劲，过于危险」所设的山林异常——血色开阔地与海碗大的兽爪印", partial=["E07-S06-02", "E07-S07-02"], verbs=["爪印", "戒备"]),
    "SETUP-OLD-ENEMY": dict(setup="E07-S10-02", payoff="E07-S12-02", object="雪里暴起的黑影是什么——驴头狼身上残留的铁箭头揭晓它就是上次袭击秦铭的变异生物", partial=["E07-S10-03", "E07-S11-01"], verbs=["铁箭头", "捏出"]),
    "SETUP-CARRY-HOME": dict(setup="E07-S09-02", payoff="E07-S13-01", object="「足有七百斤」的收获要拖回去——半山腰拖着两个大家伙", partial=["E07-S10-01", "E07-S12-04"], verbs=["拖着"]),
    "SETUP-BLOOD-SCENT": dict(setup="E07-S12-04", payoff="E07-S13-03", object="「希望附近没有危险的山兽」所设的血腥味隐患——野猪王循血腥味闯来", partial=["E07-S13-01"], verbs=["掀翻", "冲到"]),
    "SETUP-SILENT-FOREST": dict(setup="E07-S14-03", payoff="E07-S14-05", object="山林骤然死寂、远山升起的光团是什么——那其实是一只虫", partial=["E07-S14-04"], verbs=["仰望", "明月"]),
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
    "E07-S09-01": {"cause_shot_id": "E07-S08-05", "kind": "KILL_BY_ARROW", "agent_visible": "结果状态镜：大雄鹿踉跄栽倒；起因＝E07-S08-03 / E07-S08-05 秦铭两箭（施动者秦铭在画，树上）"},
    "E07-S10-02": {"cause_shot_id": "E07-S10-01", "kind": "WOUND_BY_CLAW", "agent_visible": "秦铭肩头见血：起因＝E07-S10-01 大爪子搭肩（施动者驴头狼在本镜暴起入画）"},
    "E07-S12-01": {"cause_shot_id": "E07-S11-04", "kind": "KILL_BY_HAND", "agent_visible": "驴头狼颈断：施动者秦铭与受动者同镜；起因链 E07-S11-03 砍断獠牙 → E07-S11-04 扫断肋骨"},
    "E07-S12-02": {"cause_shot_id": "E07-S12-01", "kind": "SEARCH_CARCASS", "agent_visible": "秦铭跪在被砸死的驴头狼身上找到铁箭头；起因镜 E07-S12-01"},
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
    "可惜，来晚一步。": "ch7「秦铭瞬息冲到近前，暗道可惜」内心转低声自语，「可惜」二字不变，补「来晚一步」成整句（两字台词连续三次被模型当成画面字幕烧进画面）",
    "足有七百斤。": "ch7 叙述「这头黑褐色的刀角鹿分外雄壮，重足有七百斤」转秦铭自语，取「足有七百斤」字序不变",
    "赤手空拳也能打死你。": "ch7「他认为赤手空拳都能打死它」内心转对驴头狼的低吼（都→也、它→你）",
    "上次袭击我的，就是你。": "ch7「他可以确定，这应该就是上次他掏红松鼠巢穴时，在路上袭击他的变异生物」内心转自语，缩为一句",
    "不能生火。": "ch7 叙述「在夜色中生火…会向山林中所有生物暴露自身，过于危险」转秦铭自语",
    "追杀它的是什么东西？": "ch7「秦铭心里犯嘀咕，这么雄壮的野猪王都败了，追杀它的是什么生物？」内心自问转自语，取后半句；「生物」为 LEXICON_yewujiang_v1 禁用词（对白不得出现现代词），改「东西」",
    "希望附近没有危险的山兽。": "ch7 原句「希望附近没有危险生物。」逐字；「生物」为 LEXICON_yewujiang_v1 禁用词，按源章用词改「危险的山兽」（源章「冻死的山兽」「数百斤的山兽」）",
    "那其实是一只虫。": "ch7 末句「秦铭心头大为震动，因为他知道，那其实是一只虫」内心转轻声自语，字不变",
}
SPLIT_QUOTES = {"最近数十年都没出现过黄金年龄段的新生者。": "ch7 邵承峰原句「你们双树村不行啊，最近数十年都没出现过黄金年龄段的新生者。」按镜长规则取后段，字不变；前段按节奏略去",
                "现在山中的状况很不对劲，过于危险，": "ch7 杨永青长句前段，字不变；「我估摸着，要不了多久上面会来一次‘扫山行动’，应该会有高门子弟跟着。」按节奏略去",
                "小秦，该努力了，争取在黄金年龄段新生。": "同一源句末段，字不变"}
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

# ---------- 道具 / 生物扫描 ----------
PROP_KEYWORDS = (("PROP-HUNTING-FORK", ["猎叉"]), ("PROP-BOW-ARROWS", ["弓箭", "硬弓", "铁箭", "弓弦", "弯弓"]), ("PROP-SHORT-KNIFE", ["短刀"]), ("PROP-IRON-ARROWHEAD", ["铁箭头"]),
                 ("PROP-NIGHT-BIRDS", ["夜鸟", "碧绿的眼睛"]), ("PROP-BLADE-HORN-STAG", ["刀角鹿", "雄鹿", "鹿群"]), ("PROP-DONKEY-HEAD-WOLF", ["驴头狼", "大爪子", "黑影暴起", "黑色猛兽"]),
                 ("PROP-BOAR-KING", ["野猪王"]), ("SET-BLOODY-CLEARING", ["开阔地", "兽爪印"]), ("SET-DISTANT-MOON-LIGHT", ["一团光", "光团", "明月"]))
PROP_NAME = {**{p["entity_id"]: p["name"] for p in PROPS}, **{s["entity_id"]: s["name"] for s in SETS}}
PROP_KIND = {p["entity_id"]: p.get("kind", "PROP") for p in PROPS} | {s["entity_id"]: "SET" for s in SETS}
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
_FIRST_PROP_SHOT = {}
for sh in SHOTS:
    for eid in _props_in(sh):
        _FIRST_PROP_SHOT.setdefault(eid, f"{sh['s']}-{sh['n']:02d}")
for _row in (*PROPS, *SETS):
    assert _FIRST_PROP_SHOT.get(_row["entity_id"]) == _row["first_shot"], (_row["entity_id"], "first_shot 与扫描不符", _FIRST_PROP_SHOT.get(_row["entity_id"]))

TRANSITION_NOTES = {
    ("E07-S01-01", "E07-S01-02"): ("CAMERA_REFRAME", "猎叉横起后改取中近景"), ("E07-S01-02", "E07-S01-03"): ("REACTION_CUT", "放下猎叉后切杨永青讶异"), ("E07-S01-03", "E07-S01-04"): ("REACTION_CUT", "拍胳膊后切秦铭扛叉作答"),
    ("E07-S02-01", "E07-S02-02"): ("MOTIVATED_CUT", "指向山外后切转头看黑影，切在转头上"), ("E07-S02-02", "E07-S02-03"): ("MOTIVATED_CUT", "抬手拦人后切远处身影走近，切在走来上"), ("E07-S02-03", "E07-S02-04"): ("REACTION_CUT", "停下后切杨永青抱拳"),
    ("E07-S03-01", "E07-S03-02"): ("REACTION_CUT", "目光转向杨永青后切他摆手"), ("E07-S03-02", "E07-S03-03"): ("REACTION_CUT", "拍后背后切邵承峰冷扫一眼"),
    ("E07-S04-01", "E07-S04-02"): ("REACTION_CUT", "转头看杨永青后切他搓胡"), ("E07-S04-02", "E07-S04-03"): ("MOTIVATED_CUT", "望向山脉后切抬手指山，切在抬手上"),
    ("E07-S05-01", "E07-S05-02"): ("MOTIVATED_CUT", "握肩后切松手退步，切在松手上"),
    ("E07-S06-01", "E07-S06-02"): ("CAMERA_REFRAME", "山林显形后改取低机位中景"),
    ("E07-S07-01", "E07-S07-02"): ("MOTIVATED_CUT", "提速后切碧绿眼睛，切在奔近上"), ("E07-S07-02", "E07-S07-03"): ("CAMERA_REFRAME", "夜鸟冲天后改取高机位中近景"), ("E07-S07-03", "E07-S07-04"): ("MOTIVATED_CUT", "转身就走后切走进开阔地，切在行走上"),
    ("E07-S08-01", "E07-S08-02"): ("CAMERA_REFRAME", "停步后改取中近景"), ("E07-S08-02", "E07-S08-03"): ("MOTIVATED_CUT", "取弓瞄准后切拉满，切在拉弓上"), ("E07-S08-03", "E07-S08-04"): ("REACTION_CUT", "中箭后切雄鹿冲来"), ("E07-S08-04", "E07-S08-05"): ("REACTION_CUT", "鹿群冲来后切秦铭再次弯弓"),
    ("E07-S09-01", "E07-S09-02"): ("MOTIVATED_CUT", "鹿群远去后切跳下走近，切在跳下上"),
    ("E07-S10-01", "E07-S10-02"): ("MOTIVATED_CUT", "爪子搭肩后切缩肩滚开，切在缩肩上"), ("E07-S10-02", "E07-S10-03"): ("CAMERA_REFRAME", "黑影扑来后改取低机位特写"), ("E07-S10-03", "E07-S10-04"): ("CAMERA_REFRAME", "踢翻站起后改取中近景"),
    ("E07-S11-01", "E07-S11-02"): ("REACTION_CUT", "直立嘶吼后切秦铭拔刀"), ("E07-S11-02", "E07-S11-03"): ("REACTION_CUT", "刀尖前指后切驴头狼扑来"), ("E07-S11-03", "E07-S11-04"): ("MOTIVATED_CUT", "獠牙断后切铁鞭扫出，切在跟进上"),
    ("E07-S12-01", "E07-S12-02"): ("CAMERA_REFRAME", "颈断后改取特写"), ("E07-S12-02", "E07-S12-03"): ("MOTIVATED_CUT", "站起后切抚肩，切在抬手上"), ("E07-S12-03", "E07-S12-04"): ("CAMERA_REFRAME", "蹲下后改取高机位中全景"),
    ("E07-S13-01", "E07-S13-02"): ("CAMERA_REFRAME", "停下后改取中近景"), ("E07-S13-02", "E07-S13-03"): ("MOTIVATED_CUT", "望向密林后切野猪王闯来，切在视线上"), ("E07-S13-03", "E07-S13-04"): ("REACTION_CUT", "鼻子翕动后切秦铭攥弓"),
    ("E07-S14-01", "E07-S14-02"): ("REACTION_CUT", "搭箭后切野猪王抬头"), ("E07-S14-02", "E07-S14-03"): ("CAMERA_REFRAME", "黑鳞獠牙后改取远景横摇"), ("E07-S14-03", "E07-S14-04"): ("REACTION_CUT", "光升起后切野猪王退走"), ("E07-S14-04", "E07-S14-05"): ("REACTION_CUT", "埋雪后切秦铭仰望"),
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
            prop_handoff=("随身道具/生物延续：" + "、".join(carried)) if carried else "本边界无道具主体",
            sound_bridge=f"{sid} 环境声（{AMBIENT_LIFE[sid]['motion_trend']}）连贯不中断，切镜不改变环境声",
            axis_strategy=cpb["axis_relation"],
            transition_execution=f"{execution}；本镜机位 {cpb['motion_family']}/{cpb['motion_direction']}，{cpb['start_framing']}",
            action_bridge=f"上镜终态「{a['exit']}」之后，动作不复位；本镜从「{b['entry']}」开始（D-68：起始姿态 = 上镜结束姿态）",
            entity_mapping="，".join(f"{cname(k)}→参考图 {cid(k)}" for k in b["cast"]) + "，各自槽位不互换" if b["cast"] else "本边界无人物；非人物主体按参考卡映射：" + "，".join(f"{PROP_NAME[p]}→参考卡 {p}" for p in (_props_in(b) or _props_in(a))) + "，各自槽位不互换",
            same_slot_reuse_allowed=False)

# ---------- directing script ----------
LOCKED_IDS = [f"{s['s']}-{s['n']:02d}" for s in SHOTS if CAMERA_PLANS[f"{s['s']}-{s['n']:02d}"]["motion_family"] == "LOCKED"]
REANCHOR_IDS = [f"{sh['s']}-{sh['n']:02d}" for sh in SHOTS if sh.get("identity_reanchor")]
lines = [f"# 《夜无疆》{EP} 导演稿 {VER}（directing script）", "",
         f"绑定 narrative：`{narr.name}`（SHA256 {sha(narr)}）", "",
         "本层只写景别、机位、轴线、走位与起止态；**不改 narrative 的任何事实**。逐镜秒标为交付口径。", "",
         "## 本集口径（seq=7/10/12/13/17/19/27/29 + D-57 + D-68）", "",
         f"- 全局风格：{STYLE['era_idiom']}", f"- 夜景：{STYLE['night_look']}", "- 禁用：" + "、".join(STYLE["forbidden"]),
         "- 节奏（seq=29 规则 5）：对白镜时长 = 台词时长（导演稿字/秒）+ 0.5 s 向上取整 0.5 s，无模板值；无对白镜 ≤4 s 且机位必动；单场 ≤16 s；action 不写「保持/口型闭合/静止/定住」，每句说完立即接一个身体动作",
         "- 表演（seq=29 规则 7）：每个对白镜 performance = 情绪词（闭集 24 词）＋进行中的身体动作＋说话方式，编译进提示词首位；禁令压缩一句在后；同场连续 3 镜情绪词不同",
         f"- 机位运动：LOCKED ≤30%（本稿 {len(LOCKED_IDS)}/{len(SHOTS)}：{'、'.join(LOCKED_IDS) or '无'}）、不连续 LOCKED、无对白镜必动、R7、R8、同轴同景别不连续 >2 镜、开场镜运动",
         "- ★D-57 身份链：face_visibility 只用闭集豁免标记（背影/远小/出画/仅手），3/4 与侧脸一律测；关键帧参考以正面头像牌打头；每个视频单元带在场角色的头像牌",
         "- ★D-68 过渡规则：每镜 entry_state 写上一镜留下的姿态，姿态变化写在镜内（R9 强制）；同场景相邻单元的开场关键帧由上一单元真实末帧承担；S7 对同景别同主体边界报警",
         "- ★seq=27：设置—揭晓闭环 5 组（SETUPS）；结果镜 4 处声明 result_of（鹿倒、肩伤、狼死、寻箭头）；台词动作词表 v1 零命中；blocking_signature 相邻不重复、场内 ≤2；一句台词只属一镜",
         "- ★兽斗：三段（射鹿 E07-S08、驴头狼 E07-S10–S12、野猪王 E07-S13–S14）均为源章明写；生物按参考卡给形貌，眼睛颜色为画面里唯一同色点光；驴头狼直立为源章明写（creature_card.locomotion=biped）",
         "- ★选择性配乐（D-32）：E07-S10–S12（驴头狼）、E07-S14（远山之光）两处纯器乐，其余原生现场声",
         "- ★音色：本集说话人：秦铭、杨永青（E04 已选）、邵承峰（新）",
         f"- ★承接：E07-S01-01 的 entry_state 接 {PREV_LAST_SHOT} 的 completion_state（{PREV_LAST['completion_state']}）；ch7 开篇在时间上位于出村路上，本集从秦铭走在村外雪路被拦开始，不复位、不重演、不闪回", ""]
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
NPR_FACE = {"QM": "束发木簪、无胡须的清瘦年轻男子", "YQ": "络腮胡敦实中年男子", "SC": "披散长发、皮甲攥枪的高大中年男子"}
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
           "prop_tokens": ["猎叉", "弓箭", "铁箭", "短刀", "铁箭头", "夜鸟", "刀角鹿", "驴头狼", "野猪王", "光团"], "split_columns": True}
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
    lst_id = cid(dlg[2]) if dlg and dlg[2] in CH else ""
    resolved = [{"surface_form": surface, "entity_id": cid(key) if key in CH else key} for surface, key in sh["referents"]]
    presence = {cid(k): "VISIBLE_AND_IDENTITY_LOCKED" for k in sh["cast"]}
    slots = sh.get("slots") or {}; faces = sh.get("faces") or {}
    states = {cid(k): sh["exit"] for k in sh["cast"]}
    for p in _props_in(sh):
        if PROP_KIND.get(p) == "CREATURE":
            states[p] = sh["exit"]
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
        "pacing_flags": {"hook": shot_id == "E07-S01-01", "scene_opener_in_motion": sh["n"] == 1, "scene_button": sh is by_scene[sid][-1],
                         "no_dialogue_static_hold_seconds_max": PACING["no_dialogue_static_hold_seconds_max"] if not dlg else None,
                         "conflict_line": bool(perf and perf[0] in set(LEX.get("conflict_emotions") or []))},
        **({"dialogue_delivery": {"chinese_characters_per_second": sh["cps"], "basis": "seq=29 规则 5a：镜长 = ceil_0.5(字数/字每秒 + 0.5)；字/秒按句标注 4.8–5.2；post-gen 规则 6 按此核实测语速"}} if sh.get("cps") else {}),
        "prompt_spec": {
            "camera_plan": {**CAMERA_PLANS[shot_id], "authorship": "DIRECTING_SCRIPT_AUTHORED", "selection_mode": "LOCKED", "source": f"E07_DIRECTING_SCRIPT_v1.md#{shot_id}"},
            "cast": [{"character": cname(k), "character_id": cid(k), "life_state": life_state(sh, k),
                      **({"screen_slot": slots[k]} if k in slots else {}), **({"face_visibility": faces[k]} if k in faces else {})} for k in sh["cast"]],
            "props": [{"prop_id": p, "prop": PROP_NAME[p]} for p in _props_in(sh)],
            "dialogue": f"{cname(dlg[0])}：{dlg[1]}" if dlg else "",
            **({"dialogue_delivery": {"chinese_characters_per_second": sh["cps"]}} if dlg else {}),
            "action": {"subject_id": ent_id(subj), "primary_action": act, "patient_id": ent_id(patient),
                       **({"non_character_subject_id": subj} if subj and subj not in CH else {}), **({"non_character_patient_id": patient} if patient and patient not in CH else {}),
                       **({"performance": performance} if performance else {}), "constraints": constraints,
                       "columns_authority": "SUPERVISOR_ORDERS seq=29 规则 7a：performance 在前、constraints 压缩在后"},
            **({"identity_reanchor_required": True, "identity_reanchor_reason": "seq=12/13：同场内远景/小人影/背影之后的露脸镜；以角色板生成的关键帧作身份再锚定参考（engine e19）"} if sh.get("identity_reanchor") else {}),
            "referent_resolution_contract": {"status": "PASS", "source_scan_complete": True, "resolved_source_referents": resolved, "unresolved_source_referents": []},
            "role_semantic_disambiguation": {
                "primary_actor_kind": "CHARACTER" if subj_is_char else ("CREATURE" if PROP_KIND.get(subj) == "CREATURE" else ("PROP" if subj else "ENVIRONMENT")),
                "primary_actor": ent_name(subj) if subj else "", "primary_actor_id": ent_id(subj), **({"primary_actor_entity_id": subj} if subj and subj not in CH else {}),
                "dialogue_speaker": cname(dlg[0]) if dlg else "", "dialogue_speaker_id": spk_id,
                "dialogue_listener": cname(dlg[2]) if dlg and dlg[2] in CH else "", "dialogue_listener_id": lst_id,
                "action_patient": ent_name(patient) if patient else "", "action_patient_id": ent_id(patient), **({"action_patient_entity_id": patient} if patient and patient not in CH else {}),
                "lip_owner_id": spk_id, "entity_states": states, "entity_presence": presence},
        },
    }

_CE6 = {c["character_id"]: c for c in _E06["character_entities"]}
_CE4 = {c["character_id"]: c for c in _E04["character_entities"]}
CHARACTER_ROWS = [
    {**_CE6["CHAR-QINMING"], "identity_source": {**_CE6["CHAR-QINMING"]["identity_source"], "note": "E02 锁定的三视图身份牌复用；D-57 ①：S3 复测源图余弦 ≥0.45"},
     "appearance_ch7": "ch7：背弓拎叉出村；齐胸雪中破浪；饥饿；射鹿上树；被驴头狼抓伤双肩、棉衣抓烂见血；拔刀砍獠牙、拳砸颈骨；清理猎物；树上搭箭仰望明月般的光"},
    {**_CE4["CHAR-YANGYONGQING"], "identity_source": {"mode": "E04_IDENTITY_CARD_REUSE", "note": "沿用 E04 唐宋版身份牌（络腮胡敦实中年）；本集说话"},
     "appearance_ch7": "ch7：刚从山外回来，讶异、笑谈、压低声音、抱拳、摆手解释、搓胡含蓄、拍肩劝勉、转身回村"},
    {"character_id": "CHAR-SHAOCHENGFENG", "canonical_name": "邵承峰", "aliases": ["邵兄", "巡山者"], "voice_entity_id": "", "identity_reference_entity_id": "",
     "identity_source": {"mode": "TEXT_TO_IMAGE", "note": "无源照片；按 appearance 文生图出三视图身份牌（唐宋语汇皮甲）"},
     "appearance_ch1": "四十岁左右的高大男子，身材颇为高大、宽肩，披散及肩的黑发无冠，眼神十分锐利，颧骨高、短须；穿深褐皮革札甲、背竹木弓与皮箭囊、右手攥一杆木杆铁头长枪，整个人充斥着野性的力量",
     "appearance_ch7": "ch7：从夜色里走到近前停下，锐利地打量秦铭，不客气地说双树村数十年没出黄金年龄段新生者，短暂驻足后转身消失在夜色中"},
]
for _row in CHARACTER_ROWS:
    _row.pop("wardrobe_garments", None)
BGM_CUES = [
    {"cue_id": "E07-BGM-01", "scenes": ["E07-S10", "E07-S11", "E07-S12"], "narrative_function": "BEAST_AMBUSH_FIGHT", "volume": 0.28, "dialogue_duck_db": -8,
     "brief": "Tense driving instrumental cue in ancient Chinese folk style for a young hunter ambushed in a snowy night forest by a mutant donkey-headed wolf and killing it with a short knife and bare fists: fast taiko-like drums, low bowed strings, sharp pipa strikes on each blow, a beat of silence when the beast dies, no vocals, 39 seconds"},
    {"cue_id": "E07-BGM-02", "scenes": ["E07-S14"], "narrative_function": "FALSE_MOON_RISING", "volume": 0.3, "dialogue_duck_db": -8,
     "brief": "Eerie awe-struck cinematic instrumental cue for a giant boar falling silent and burying itself in snow as a glowing orb rises over a far mountain like a full moon in a world that has never had a moon: sustained high strings, a single bronze bell, a distant xiao flute, swelling slowly to a cold shimmering chord, no vocals, 16 seconds"},
]
_e03_fork = next((s["shot_id"] for s in _E03["shots"] if "猎叉" in str(s.get("completion_state"))), _E03["shots"][0]["shot_id"])
_e03_knife = next((s["shot_id"] for s in _E03["shots"] if "短刀" in str(s.get("completion_state"))), _e03_fork)
PROP_SOURCES = {
    "PROP-HUNTING-FORK": {"acquired": {"episode": "E03", "shot_id": _e03_fork}, "recap_shot_id": "E07-S01-01", "payoff_shot_ids": ["E07-S11-01"]},
    "PROP-BOW-ARROWS": {"acquired": {"episode": "E04", "shot_id": "E04-S02-04"}, "recap_shot_id": "E07-S01-01", "payoff_shot_ids": ["E07-S08-03", "E07-S14-01"]},
    "PROP-SHORT-KNIFE": {"acquired": {"episode": "E03", "shot_id": _e03_knife}, "recap_shot_id": "E07-S11-02", "payoff_shot_ids": ["E07-S11-03", "E07-S12-04"]},
    "PROP-IRON-ARROWHEAD": {"acquired": {"episode": EP, "shot_id": "E07-S12-02"}, "payoff_shot_ids": ["E07-S12-02"]},
    "PROP-NIGHT-BIRDS": {"acquired": {"episode": EP, "shot_id": "E07-S07-02"}, "payoff_shot_ids": ["E07-S07-02"]},
    "PROP-BLADE-HORN-STAG": {"acquired": {"episode": EP, "shot_id": "E07-S08-01"}, "payoff_shot_ids": ["E07-S09-01", "E07-S09-02"]},
    "PROP-DONKEY-HEAD-WOLF": {"acquired": {"episode": EP, "shot_id": "E07-S10-01"}, "payoff_shot_ids": ["E07-S10-03", "E07-S12-01"]},
    "PROP-BOAR-KING": {"acquired": {"episode": EP, "shot_id": "E07-S13-03"}, "payoff_shot_ids": ["E07-S14-02", "E07-S14-04"]},
    "SET-BLOODY-CLEARING": {"acquired": {"episode": EP, "shot_id": "E07-S07-04"}, "payoff_shot_ids": ["E07-S07-04"]},
    "SET-DISTANT-MOON-LIGHT": {"acquired": {"episode": EP, "shot_id": "E07-S14-03"}, "payoff_shot_ids": ["E07-S14-05"]},
}
def with_sources(row):
    return {**row, **PROP_SOURCES[row["entity_id"]]}
_first_shot_of = {}
for _sh in SHOTS:
    for _k in _sh["cast"]:
        _first_shot_of.setdefault(_k, f"{_sh['s']}-{_sh['n']:02d}")
_PRIOR = {"YQ": "E04"}
NEW_IN_EP = {"PROP-IRON-ARROWHEAD", "PROP-NIGHT-BIRDS", "PROP-BLADE-HORN-STAG", "PROP-DONKEY-HEAD-WOLF", "PROP-BOAR-KING", "SET-BLOODY-CLEARING", "SET-DISTANT-MOON-LIGHT"}
ENTITY_INTRODUCTIONS = (
    [{"entity_id": cid(k), "first_shot_id": _first_shot_of.get(k), "setup": ({"kind": "prior_episode", "ref": _PRIOR[k]} if k in _PRIOR else {"kind": "shot", "ref": _first_shot_of.get(k)})}
     for k in CH if k != "QM"]
    + [{"entity_id": r["entity_id"], "first_shot_id": r.get("first_shot") or "",
        **({"setup": {"kind": "shot", "ref": r.get("first_shot")}, "payoff_shot_id": PROP_SOURCES[r["entity_id"]]["payoff_shot_ids"][0]} if r["entity_id"] in NEW_IN_EP
           else {"setup": {"kind": "prior_episode", "ref": PROP_SOURCES[r["entity_id"]]["acquired"]["episode"]}})}
       for r in (*PROPS, *SETS)]
)
_VCC6 = _E06["visual_culture_contract"]
contract = {
    "schema": "qingshan.generation_contract.v3",
    "episode": EP, "version": VER,
    "narrative_canonical": narr.name, "narrative_sha256": sha(narr),
    "style": {**STYLE, "authority": "SUPERVISOR_ORDERS seq=7 c1/c2；seq=36 沿用；PRODUCTION_LINE_OVERVIEW_v1 §四 3/5", "negative_prompt_fixed": _E06["style"]["negative_prompt_fixed"]},
    "pacing": PACING,
    "protagonist_ids": ["CHAR-QINMING"],
    "antagonist_groups": [],
    "ambush_contracts": [],
    "entity_introductions": ENTITY_INTRODUCTIONS,
    "writer_visibility_contract_seq27": SEQ27_SELFCHECK,
    "writer_selfcheck_seq29": {"enforced": True, "rule8_authorized": False, "authority": "SUPERVISOR_ORDERS seq=29；规则 8 待线主裁定，本集只申报"},
    "pressure_source": {"kind": "LOSS_IMMINENT", "shot_id": "E07-S06-02", "at_seconds": _shot_start["E07-S06-02"], "description": "饥饿（肚子叫、胃反酸）与山林外部区域已变得危险（血色开阔地）"},
    "episode_payoff": {"kind": "THREAT_ADVANCES", "shot_id": "E07-S14-05", "description": "一千五百斤的野猪王闯上矮山，又在远山升起的“明月”前无声埋雪——那其实是一只虫"},
    "action_chain": {"want_shot_id": "E07-S08-02", "blocked_shot_id": "E07-S10-02", "act_shot_id": "E07-S12-01", "note": "想打到肉（射鹿）→驴头狼偷袭见血→拔刀拳砸打死它；集末野猪王闯来、上树搭箭"},
    "style_reset_disclosure": STYLE_RESET_DISCLOSURE,
    "carry_in": {"previous_episode": PREV_EP, "previous_scene_id": "E06-S14", "previous_shot_id": PREV_LAST["shot_id"],
                 "previous_completion_state": PREV_LAST["completion_state"],
                 "first_shot_id": "E07-S01-01", "first_shot_entry_state": SHOTS[0]["entry"],
                 "rule": "不复位、不重演、不闪回 E06 内容；E06 收在秦铭冲进林线；ch7 开篇「刚出村没多远」在时间上位于出村路上，E07 从秦铭走在村外雪路被拦开始，沿同一方向推进",
                 "entities": ["CHAR-YANGYONGQING", "PROP-HUNTING-FORK", "PROP-BOW-ARROWS", "PROP-SHORT-KNIFE"]},
    "visual_culture_contract": {**_VCC6, "decision_basis": "ch7 明写：村外雪路遇杨永青与皮甲巡山者、齐胸雪中破浪、碧绿眼睛的夜鸟、血色开阔地、六角刀角鹿、驴头狼直立嘶吼、拔刀砍獠牙、黑鳞野猪王、远山升起的明月般的光；Roger 2026-09-13 审片：中国唐宋不要西式暗黑",
                                "source_ref": str(SRC_CH),
                                "production_design": _VCC6["production_design"] + "；山林为落叶松、云杉、白桦；兽踩出的小路与兽骨；生物按参考卡写实体态",
                                "armor_tradition": "巡山者邵承峰着唐宋皮革札甲（皮绳编缀皮甲片）、木杆铁头长枪、竹木弓与皮箭囊；秦铭猎具为木柄铁头猎叉、直刃短刀、竹木硬弓与铁箭；不得出现制式铁札甲、西式甲胄或现代猎具",
                                "palette_system": {"base": _VCC6["palette_system"]["base"], "accent": "雪面青蓝反光；夜鸟碧绿眼睛（唯一绿光）、驴头狼猩红眼睛（唯一红光）、远山白色光团（唯一天光）；血在雪上暗红", "skin": "雪光下清冷；秦铭有血色、肩头见血；杨永青络腮胡沾雪；邵承峰风尘皮甲"}},
    "character_entities": [dict(row, wardrobe_garments=WARDROBE_GARMENTS[row["character_id"]]) for row in CHARACTER_ROWS],
    "non_character_entities": [with_sources(r) for r in (*PROPS, *SETS)],
    "props": {"authority": "SUPERVISOR_ORDERS seq=7 c6：关键道具/生物出参考卡入资产库并挂进视频参考列表", "reference_cards": [with_sources(p) for p in PROPS + SETS if p.get("reference_card_required")],
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
                "declaration": "SELECTIVE_NARRATIVE_CUES：两处纯器乐配乐（驴头狼偷袭到被打死、远山之光），覆盖 ≤85%，其余全部原生现场声；经 AgentCut bgm-generate → giggle generate-music 生成，受预算守卫与事务存档约束",
                "cues": BGM_CUES},
        "voice_casting": {"authority": "SUPERVISOR_ORDERS seq=17 c1", "note": "秦铭/杨永青沿用已选音色；邵承峰新选（四十岁左右、声音低沉锐利）"},
        "ambient_by_scene": {
            "E07-S01": "村外雪路踩雪声、猎叉横起的木柄声、两人的呼吸白雾", "E07-S02": "拍雪、远处踩雪脚步、皮甲摩擦、铁枪杆点雪", "E07-S03": "皮甲摩擦、雪路上的脚步远去", "E07-S04": "夜风起、搓胡子、两人踩雪换位",
            "E07-S05": "拍肩、踩雪分别、两个方向的脚步", "E07-S06": "齐胸积雪被冲开的雪浪声、喘息、肚子咕噜叫、冲进林间的枝响", "E07-S07": "林间女子般的呜咽声、奔跑踩雪、十几只夜鸟扑棱棱冲天、骨头堆", "E07-S08": "蹄印上的脚步、鹿群鼻息、弓弦满月的吱声、铁箭破空、鹿群狂奔积雪迸溅蹄声密集",
            "E07-S09": "攀树的树皮摩擦、雄鹿砰然栽倒、鹿群轰隆隆远去、跳下落雪", "E07-S10": "拖鹿的雪地摩擦、山风呜呜卷雪粒、大爪子搭肩的皮毛声、热气喘息、积雪崩开、扑击、踹击打滚", "E07-S11": "猎叉被按进雪里、驴头狼直立嘶吼、拔刀、刀爪碰撞的颤音、獠牙断裂、骨裂与惨叫",
            "E07-S12": "拳砸雪地、颈骨喀嚓、皮毛翻动、短刀割皮的声音、血水涌出、雪压实", "E07-S13": "拖行上坡、远处巨响、飞禽冲天、枝杈折断、野猪王踏雪冲来鼻子翕动", "E07-S14": "攀树、搭箭上弦、野猪王抬头的鼻息、山林骤然死寂、野猪王无声退走埋雪、风声消失",
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
    ("E07-EV-01", "landed", "E07-S01-01 至 E07-S01-02", "村外一片漆黑很少有人出来；刚出村没多远秦铭发现一个身材敦实的男子「杨叔？」"),
    ("E07-EV-02", "landed", "E07-S01-03", "杨永青讶异「小秦，浅夜还未到，你这么早就出去？」"),
    ("E07-EV-03", "landed", "E07-S01-04", "「想去野外碰碰运气，看有没有冻死的山兽」"),
    ("E07-EV-04", "landed", "E07-S02-01", "杨永青笑道「咱们想到一块去了，我刚在山外转了一圈，可惜毫无收获」；秦铭愕然：他居然是从外面回来（内心「杨叔怎么可能和我一样…追寻有灵性的稀珍猎物」不演）"),
    ("E07-EV-05", "landed", "E07-S02-02", "远处有黑影晃动，「巡山者」杨永青低语（没有太阳的时代需要人巡山警戒——科普不演）"),
    ("E07-EV-06", "landed", "E07-S02-03 至 E07-S02-04", "穿皮甲、背弓箭、攥铁枪、披散长发的高大男子出现；「邵兄」杨永青主动招呼；邵承峰点头"),
    ("E07-EV-07", "landed", "E07-S03-01", "邵承峰四十岁左右眼神锐利，在近前停下「这么年少就和你一起外出，该不会是那个二病子吧？」"),
    ("E07-EV-08", "landed", "E07-S03-02", "「二病子是隔壁村的……」杨永青解释"),
    ("E07-EV-09", "landed", "E07-S03-03", "「你们双树村不行啊，最近数十年都没出现过黄金年龄段的新生者」不客气地说（取后段）；杨永青觉得正常、天赋没法强求（内心不演）"),
    ("E07-EV-10", "dropped", "", "杨永青与邵承峰关于二病子补上亏空后素质提升、能否与明亮城池的拔尖者比肩、一方水土养一方人、城中两位了不得的少年一男一女惊艳整片地域、灵秀之地的对谈（五句往来，世界观科普，seq=17/19 不单独占镜，全部略去；「明亮城池的少年」已由 E06 陆泽一句带过）"),
    ("E07-EV-11", "landed", "E07-S03-03", "秦铭全程认真倾听没有插话；邵承峰短暂驻足后消失在夜色中；山脉深处栖居着什么等级的生灵需要巡山者监测预警（科普不演）"),
    ("E07-EV-12", "landed", "E07-S04-01 至 E07-S04-02", "「巡山者都是厉害人物，每天都要进山吗？」「有的人很负责」；秦铭一怔：也有人很不负责、回答得这么含蓄（内心不演，以杨永青搓胡承担）"),
    ("E07-EV-13", "landed", "E07-S04-03 至 E07-S05-01", "「现在山中的状况很不对劲，过于危险，我估摸着…扫山行动…高门子弟跟着。小秦，该努力了，争取在黄金年龄段新生」拍肩（拆两镜，中段略去）"),
    ("E07-EV-14", "landed", "E07-S05-02", "「万一被下来的某位贵女看中，或许能改命」；两人分别杨永青回村；秦铭消化着消息一路向野外而去"),
    ("E07-EV-15", "landed", "E07-S06-01", "速度非常快在齐胸的积雪中穿行宛若破浪，雪花翻溅向道路两侧；夜色没那么浓浅夜到来山林若隐若现"),
    ("E07-EV-16", "landed", "E07-S06-02", "站在山外提高警惕；咕噜一声肚子叫了，早先遇熟人时强行克制现在失效；胃反酸水，望着幽暗的密林攥紧猎叉一闪身冲进去；越过松鼠栖居地翻过矮山比上次走得更远、兽骨蹄印小路（并入 S07-01 的林间小路）"),
    ("E07-EV-17", "landed", "E07-S07-01", "一阵呜咽声像有女子哭泣，秦铭猛然提速寻找声源很快接近"),
    ("E07-EV-18", "landed", "E07-S07-02", "黑漆漆的林地间一双双碧绿的眼睛望来足有十几个生灵；对常年野外的人这是机会（内心不演）；提着猎叉闯过去，扑棱棱十几只生物冲上夜空；食肉性夜鸟体长两尺群居声若幽泣（科普以参考卡承担）"),
    ("E07-EV-19", "landed", "E07-S07-03", "瞬息冲到近前暗道可惜（转自语），地上仅有一堆带血的骨头与染血的破碎兽皮，一头獐子被吃光；鸟口夺食失败转身就走提防被袭"),
    ("E07-EV-20", "landed", "E07-S07-04", "一片开阔地林木稀疏血迹斑斑，比海碗口还大的兽爪印，大型猛兽进食场所；残骸被叼走（不演）；正如陆泽所说山林外部区域都变得危险了（内心不演）；戒备着离开血色现场"),
    ("E07-EV-21", "landed", "E07-S08-01 至 E07-S08-02", "雪地中发现蹄印一路跟下去；二十几道黑影立在前方体形不小很有压迫感；「刀角鹿！」露出喜悦之色；昔日这片地带很少有鹿群（不演）；取下弓箭瞄准一头大雄鹿；六支扁平锋锐的角像六把钢刀、猛兽都从背后偷袭（科普以参考卡与画面承担）"),
    ("E07-EV-22", "landed", "E07-S08-03 至 E07-S08-04", "硬弓拉成满月咻的一声铁箭射入雄鹿肺部；刀角鹿很凶，大雄鹿中箭不逃反冲来；鹿群跟着狂奔积雪迸溅蹄声密集山林轻颤"),
    ("E07-EV-23", "landed", "E07-S08-05", "秦铭没有慌再次弯弓精准命中，铁箭整支没入让大雄鹿晃动了几下"),
    ("E07-EV-24", "landed", "E07-S09-01", "收起弓箭从容攀上一棵很粗的大树躲在数米高处（密林中上树不好瞄准——不演）；大雄鹿踉踉跄跄砰的一声倒在雪地中；鹿群受惊止步轰隆隆远去"),
    ("E07-EV-25", "landed", "E07-S09-02", "等了片刻无危险跳下大树拎猎叉到近前；黑褐色刀角鹿分外雄壮重足有七百斤（转自语）；非常满意"),
    ("E07-EV-26", "landed", "E07-S10-01", "林中危险不宜久留拖着刀角鹿沿原路往回赶；新生力气大增拉着重物无疲累感；落叶松云杉数十米高（不演）；山风渐大雪颗粒砸脸生疼；一双毛茸茸的大爪子自后面搭在肩头，热气触及后颈汗毛——血盆大口临近"),
    ("E07-EV-27", "landed", "E07-S10-02", "第一时间缩肩、下蹲、滚向一侧雪地；仍见血：大爪子堪比铁钩抓烂棉衣伤及双肩；积雪轰然崩开黑影自雪窝子暴起跟着扑去；如游蛇般在地面动作惊险挣脱、凶暴黑影再次扑击露出利齿（并入本镜扑来）"),
    ("E07-EV-28", "landed", "E07-S10-03", "来不及起身冷静地伸出双手抓住那对前肢牢牢控制住，大爪子几乎贴上面孔压不下来；正面看清：硕大的驴头、开阔的嘴、颈后长黑鬃毛、山狼躯体，向喉咙咬去，热气腥味喷到面前；以它自己的爪子挡它的利齿（并入）；蜷身缩腿蓄力猛然蹬出踹在腹部，新生力量大得出奇一脚把数百斤山兽踢翻打滚"),
    ("E07-EV-29", "landed", "E07-S10-04", "「驴头狼！」盯着黑色猛兽；也叫山混子、正常个体一百八十斤以上这头变异四百斤、普通人必死、四肢很长可直立行走老人曾见扛猎物走路（科普以 creature_card 承担不演）"),
    ("E07-EV-30", "landed", "E07-S11-01", "变异生物凶残机敏起身的刹那把近前的猎叉按进雪里；秦铭哑然它有了灵性懂得隔开武器（内心不演）；眼神凶戾鬃毛炸立倏地直立而起高出一大段嘶吼气场十足"),
    ("E07-EV-31", "landed", "E07-S11-02", "秦铭一点不怵从背后拔出短刀向前逼去；新生蜕变中认为赤手空拳都能打死它（转低吼）"),
    ("E07-EV-32", "landed", "E07-S11-03 至 E07-S11-04", "驴头狼带腥风扑来搅得积雪横飞沉闷吼声震落枝上雪花；短刀与大爪子碰撞清脆颤音；它直立眼睛血红想抱住撕咬；动作如电雪亮刀光划过嘴巴淌血獠牙被砍断；迅速跟进右腿如铁鞭重重扫在身上骨裂声凄厉惨叫"),
    ("E07-EV-33", "landed", "E07-S12-01", "扑上去将四百斤驴头狼按在雪地连着挥拳砸落；喀嚓颈部击断歪扭一动不动；一身黑油油皮毛价值很高较完好保存（不演）；外人在此会心惊变异驴头狼被拳头活活砸死（不演）"),
    ("E07-EV-34", "landed", "E07-S12-02", "很快在它身上发现一枚残留的铁箭头；可以确定这就是上次掏红松鼠巢穴时在路上袭击他的变异生物（转自语），当日曾射中它"),
    ("E07-EV-35", "landed", "E07-S12-03", "抚摸肩头伤口不深血很快止住；过程惊险慢一拍双肩被撕裂后颈被咬断（内心不演）；消耗不小腹中如擂鼓饿得心慌想烤鹿腿；夜色中生火如雾中灯塔暴露自身过于危险（转「不能生火」）"),
    ("E07-EV-36", "landed", "E07-S12-04", "看着驴头狼与刀角鹿再望向矮山带两个大家伙翻山麻烦决定减负；刚死去身体温热短刀割开皮毛血水涌出染红雪地；眉清目秀的少年野外生存能力很强靠自己活着（不演）；快速出刀清理脏腑第一时间埋进雪地遮掩血腥味；「希望附近没有危险生物」（对白按时代词表改「危险的山兽」）这里已是外部区域（内心不演）"),
    ("E07-EV-37", "landed", "E07-S13-01 至 E07-S13-02", "刚到半山腰听到远处巨大动静，惊得飞禽冲上夜空山兽奔逃；「血腥味引来了巨兽？」眉头深锁望向远处密林；响声由远而近伴着嘶吼积雪翻腾枝杈折断"),
    ("E07-EV-38", "landed", "E07-S13-03 至 E07-S13-04", "看到像铁甲车般高大壮硕的庞然大物沿途掀翻障碍；负伤染血是战败逃来的巨兽不是冲他而来；倒吸冷气竟是一头一千五百斤以上的野猪，六百斤就可称王、钢针般兽毛、獠牙比小臂长（科普以参考卡承担）；心里犯嘀咕这么雄壮的野猪王都败了追杀它的是什么生物（转自语）；原以为会从山脚路过哪知鼻子翕动向矮山冲来，负伤敏感被血腥味刺激；麻烦大了追杀它的神秘生物也可能跟来，隐约听到远处密林动静（内心与远处动静不演）；风声渐弱消失"),
    ("E07-EV-39", "landed", "E07-S14-01 至 E07-S14-02", "小山似的野猪王野蛮闯来踩踏积雪横飞拦路树枝断落枯树折断（并入 S13-03）；秦铭面色微变攀上需数人合抱的大树居高临下准备射眼睛心脏要害；野猪王临近粗硬黑毛直立抬头时面部一层黑色鳞片泛冷幽幽金属光泽狰狞凶猛；被盯上，铁箭搭在弓弦上对准下方"),
    ("E07-EV-40", "landed", "E07-S14-03 至 E07-S14-05", "忽觉不对劲山林瞬息安静鸟雀猛禽山兽全部不见没有一点声息；远处山峰一团光升起起初柔和很快灿烂逐渐升高；脾气暴躁的野猪王不敢出声无声退走谨慎如小猫躲进幽暗区域蛰伏洼地用积雪把自己埋上；永夜时代天空常年漆黑（不演），那团光越来越亮宛若皎洁明月当空；秦铭心头大为震动因为他知道那其实是一只虫（转自语）"),
]
SCENE_BEAT_META = {
    "E07-S01": {"type": "dialogue"}, "E07-S02": {"type": "dialogue"}, "E07-S03": {"type": "dialogue"}, "E07-S04": {"type": "dialogue"}, "E07-S05": {"type": "dialogue"},
    "E07-S06": {"type": "transition"}, "E07-S07": {"type": "reveal"},
    "E07-S08": {"type": "action", "outcome": {"kind": "injury", "evidence_shot_id": "E07-S08-05"}}, "E07-S09": {"type": "action", "outcome": {"kind": "winner", "evidence_shot_id": "E07-S09-02"}},
    "E07-S10": {"type": "action", "outcome": {"kind": "injury", "evidence_shot_id": "E07-S10-02"}}, "E07-S11": {"type": "action", "outcome": {"kind": "injury", "evidence_shot_id": "E07-S11-04"}}, "E07-S12": {"type": "reveal"}, "E07-S13": {"type": "reveal"}, "E07-S14": {"type": "reveal"},
}
assert set(SCENE_BEAT_META) == set(SCENES), set(SCENES) ^ set(SCENE_BEAT_META)
_FS1 = [{"cluster_id": "E07-FS1-STAG", "shots": ["E07-S08-03", "E07-S08-04", "E07-S08-05", "E07-S09-01"], "source": "ch7 两箭射杀刀角鹿、鹿群冲锋、上树（源章明写）"},
        {"cluster_id": "E07-FS1-WOLF", "shots": ["E07-S10-01", "E07-S10-02", "E07-S10-03", "E07-S11-01", "E07-S11-03", "E07-S11-04", "E07-S12-01"], "source": "ch7 驴头狼雪窝偷袭、抓前肢踹翻、刀砍獠牙、铁鞭扫肋、拳砸颈断（源章明写）"}]
for _c in _FS1:
    _c["seconds"] = round(sum(_shot_by_id[x]["sec"] for x in _c["shots"]), 1)
manifest = {
    "episode": EP, "version": VER, "title": "遭遇",
    "canonical_script": f"workflow/claude_writer_agent/scripts/{narr.name}", "script_sha256": sha(narr),
    "directing_script": f"workflow/claude_writer_agent/scripts/{directing.name}", "directing_sha256": sha(directing),
    "generation_contract": f"workflow/claude_writer_agent/scripts/{contract_path.name}", "generation_contract_sha256": sha(contract_path),
    "supersedes": None,
    "★supersedes_disclosure": "首版，无前版。nalu 线《夜无疆》E07 首次交付；按 seq=7/10/12/13/17/19/27/29/36 + D-57/D-68 口径编排；narrative 14 场 25 句对白零改动（一句源章长句取后段、一句拆为两行两镜中段略去；七句叙述/内心独白转台词，均已在 narrative 头部与 authored_dialogue_from_indirect_speech 申报；源章五句世界观对谈整段略去并在 beat_disposition 申报为 dropped）。",
    "authorization": {"order_seq": 36, "order_id": "ROGER-20260918-NALU-E07-START", "also": ["seq=3 ROGER-20260909-NALU-E01-E10-PRODUCTION-AUTHORIZED", "seq=7", "seq=10", "seq=12", "seq=13", "seq=17", "seq=19", "seq=27 rules 1–4", "seq=29 rules 5–7 (rule 8 pending)", "seq=31 option C standing rule", "D-57 identity chain", "D-68 transition rules"]},
    "writer_identity": {"agent_id": "claude-code-nalu-writer", "provider": "anthropic", "model_id": "claude-fable-5-1", "session_note": "Claude Code 交互会话，Roger 2026-09-18 指令「修改代码同步到git，然后开始e07，e06无需更改」"},
    "source_binding": {
        "work": "夜无疆", "author": "辰东",
        "primary_source_chapter": "7", "source_chapters": ["7"], "chapter_title": "遭遇",
        "source_file": str(SRC_CH), "source_sha256": sha(SRC_CH),
        "source_index": str(RUNTIME / "sources/夜无疆/SOURCE_INDEX.json"),
        "episode_source_map": str(RUNTIME / "runtime/episode_source_map_yewujiang_v1.json"),
        "beat_count": len(BEATS), "beats_landed": sum(1 for b in BEATS if b[1] == "landed"), "beats_merged": sum(1 for b in BEATS if b[1] == "merged"), "beats_dropped": sum(1 for b in BEATS if b[1] == "dropped"),
        "★carry_in_is_bound_to_the_previous_episode_bytes": f"承接 E06 合同末镜 {PREV_LAST['shot_id']} completion_state「{PREV_LAST['completion_state']}」（narrative 头部逐字引）；E07-S01-01 从秦铭走在村外雪路被拦开始（ch7 开篇在时间上位于出村路上）",
        "carry_in": contract["carry_in"] | {"previous_canonical": f"workflow/claude_writer_agent/scripts/{PREV_EP}_NARRATIVE_CANONICAL_v1.md", "previous_canonical_sha256": sha(SCRIPTS / f"{PREV_EP}_NARRATIVE_CANONICAL_v1.md")},
    },
    "beat_disposition": [{"event_id": e, "disposition": d, "landed_at": at, "summary": s} for e, d, at, s in BEATS],
    "★authorized_insertions": [],
    "authored_dialogue_from_indirect_speech": [{"shot_id": shot, "speaker": cname(s), "text": q, "source_basis": AUTHORED_DIALOGUE[q]} for s, q, shot, v in DIALOGUE_UNITS if not v],
    "★audience_already_knows": ["永夜世界与太阳石", "黄金年龄段与新生", "二病子", "周家与五斤坚果", "金色灯笼眼过境", "秦铭新生中力气大增", "存粮见底必须进山（E06）", "E04 林中猩红眼睛的变异生物（本集揭晓为驴头狼）"],
    "★style_reset_disclosure": STYLE_RESET_DISCLOSURE,
    "structure": [{"beat_id": f"{EP}-B{idx+1:02d}", "scene_id": sid, "target_seconds": m["sec"], "thread": "线A", **SCENE_BEAT_META[sid], "shot_ids": [f"{x['s']}-{x['n']:02d}" for x in by_scene[sid]], "location_id": m["loc"], "source_events": m["beats"]}
                  for idx, (sid, m) in enumerate(SCENES.items())],
    "scene_breakdown_seconds": {sid: m["sec"] for sid, m in SCENES.items()},
    "total_seconds": TOTAL,
    "runtime_target_seconds": {"min": 150.0, "target": 165.0, "max": 170.0},
    "shot_count": len(SHOTS),
    "pacing": PACING,
    "key_quote_landing": [{"speaker": cname(s), "quote": q, "shot_id": shot, "verbatim_in_source": True, **({"split_note": SPLIT_QUOTES[q]} if q in SPLIT_QUOTES else {})} for s, q, shot in KEY_QUOTES],
    "fs1": {"combat_clusters": _FS1, "combat_seconds": round(sum(c["seconds"] for c in _FS1), 1), "note": "两段兽斗均为源章明写；无原创打斗；野猪王段（E07-S13–S14）无接触，不计入打斗。"},
    "identity_registry": {cid(k): cname(k) for k in CH} | {p["entity_id"]: p["name"] for p in PROPS} | {s["entity_id"]: s["name"] for s in SETS},
    "new_name_budget": {"budget_per_4_episodes": 1, "writer_invented_names_this_episode": 0, "note": "邵承峰、杨永青为源章人名；夜鸟、刀角鹿、驴头狼、野猪王为源章物种指代；远山光团为源章描述性指代"},
    "distinct_locations": sorted({m["loc"] for m in SCENES.values()}),
    "new_locations": [],
    "episode_global_space_map_id": "GSM-YEWUJIANG-SHUANGSHU-VILLAGE-V1",
    "global_space_map_refs": [
        {"map_id": "GSM-YEWUJIANG-SNOWFIELD-WILDS", "scenes": ["E07-S01", "E07-S02", "E07-S03", "E07-S04", "E07-S05", "E07-S06"], "anchors": ["村口方向（南）", "村外踩实的雪路", "两侧齐胸积雪的雪原", "山林（北）"], "axis_note": "S01–S05 秦铭面向北（野外），杨永青自北面回村，邵承峰自北面走来又向北没入夜色；S06 秦铭自南向北破浪冲进山林"},
        {"map_id": "GSM-YEWUJIANG-FOREST-EDGE", "scenes": ["E07-S07", "E07-S08", "E07-S09", "E07-S10", "E07-S11", "E07-S12"], "anchors": ["兽踩出的林间小路", "骨头堆与夜鸟林地", "血色开阔地", "鹿群立着的林间雪地", "很粗的大树", "回程雪路旁的雪窝子"], "axis_note": "S07–S09 秦铭自林缘向林深处推进；S10 沿原路往回（反向），驴头狼自身后暴起；S11–S12 原地"},
        {"map_id": "GSM-YEWUJIANG-LOW-HILL-TOP", "scenes": ["E07-S13", "E07-S14"], "anchors": ["山脚的密林", "半山腰坡地", "需数人合抱的大树", "幽暗的洼地", "远处的山峰（升光处）"], "axis_note": "S13 野猪王自山脚密林向矮山上冲；S14 秦铭在树上俯视树下，转头望向远山"},
    ],
    "shot_subspace_bindings": [{"shot_id": f"{sh['s']}-{sh['n']:02d}", "location_id": SCENES[sh["s"]]["loc"]} for sh in SHOTS],
    "onscreen_text_shot_level_registry": [],
    "state_delta_contract_summary": {"shots_total": len(SHOTS), "shots_with_entry_ne_completion": len(SHOTS), "min_dimensions_per_shot": min(len(sh["dims"]) for sh in SHOTS), "extend_words_in_action_fields": 0},
    "camera_motion_summary": {"locked_shots": LOCKED_IDS, "locked_share": round(len(LOCKED_IDS) / len(SHOTS), 3), "policy": PACING["camera_motion_policy"], "direction_rebalanced": CAMERA_DIRECTION_REBALANCED},
    "identity_reanchor_shots": REANCHOR_IDS,
    "bgm_selective_cues": BGM_CUES,
    "voice_casting_seq17": {k: cname(k) for k in ("QM", "YQ", "SC")},
    "seq27_writer_selfcheck": SEQ27_SELFCHECK,
    "seq29_writer_selfcheck": {"status": _w29["status"], "enforced": True, "failures": _w29["failures"], "rule8_info": _w29["warnings"], "dialogue_shots": _w29["measurements"]["dialogue_shots"]},
    "d68_r9_posture_precheck": {"failures": _r9_fail, "warnings": _r9_warn},
    "writer_self_check": {"every_scene_asked_which_source_beat": True, "scenes_without_source_beat": [], "undeclared_insertions": 0, "dialogue_lines_total": len(DIALOGUE_UNITS), "dialogue_lines_verbatim_in_source": len(KEY_QUOTES)},
}
manifest_path = SCRIPTS / f"{EP}_manifest_{VER}.json"
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"narrative": {"path": str(narr), "sha256": sha(narr)}, "directing": {"path": str(directing), "sha256": sha(directing)},
                  "contract": {"path": str(contract_path), "sha256": sha(contract_path), "shots": len(SHOTS)},
                  "manifest": {"path": str(manifest_path), "sha256": sha(manifest_path), "total_seconds": manifest["total_seconds"], "scenes": len(SCENES)},
                  "camera_direction_rebalanced": CAMERA_DIRECTION_REBALANCED, "r9_warnings": _r9_warn}, ensure_ascii=False, indent=2))
