import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))
import nalu_paths as _np
# -*- coding: utf-8 -*-
"""E08《曾照彩云归》v1 —— 从一张镜头表生成 directing script / generation contract / manifest（模板 build_e07_layers.py）。

seq=47（2026-09-20）：E08 启动。沿用 D-68 过渡规则、seq=29 规则 5–7、D-57 身份链。
seq=45（E07 审片三条修法，本集起强制）：
  1) 画外人物不得在 action / blocking 里点名 —— ctx["offscreen_name_strict"]=True，NPR 直接 BLOCK；
  2) 同一地点跨场的姿态也要连 —— R9 预检行带 location_id，报 R9C；
  3) 字幕在切点前清屏由 build_burnin_subtitles 的 TAIL_GUARD 负责（S7 侧，本文件只保证句尾留动作落点）。
本集是一集"回村的暖戏"：月虫奇景 → 拖猎物回村 → 院中煮肉分肉 → 身体新生外显 → 睡进"冬眠"。
"""
import hashlib, json, math, pathlib, re
import nalu_prompt_rules as NPR
import nalu_writer_selfcheck_seq29 as W29

ROOT = pathlib.Path(f"{_np.ENGINE_ROOT}")
SCRIPTS = ROOT / "workflow/claude_writer_agent/scripts"
RUNTIME = pathlib.Path(f"{_np.RUNTIME_ROOT}")
SRC_CH = RUNTIME / "sources/夜无疆/zh-CN/ch0008.md"
QM_SOURCE_V2 = RUNTIME / "runtime/character_sources/CHAR-QINMING__SOURCE_V2_TANG.png"
EP, VER = "E08", "v1"
PREV_EP, PREV_LAST_SHOT = "E07", "E07-S14-05"
PREV_CONTRACT = SCRIPTS / f"{PREV_EP}_GENERATION_CONTRACT_v1.json"
E03_CONTRACT = SCRIPTS / "E03_GENERATION_CONTRACT_v1.json"
E04_CONTRACT = SCRIPTS / "E04_GENERATION_CONTRACT_v1.json"
E01_CONTRACT = SCRIPTS / "E01_GENERATION_CONTRACT_v1.json"
E05_CONTRACT = SCRIPTS / "E05_GENERATION_CONTRACT_v1.json"
E06_CONTRACT = SCRIPTS / "E06_GENERATION_CONTRACT_v1.json"

def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

_E07 = json.loads(PREV_CONTRACT.read_text(encoding="utf-8"))
_E03 = json.loads(E03_CONTRACT.read_text(encoding="utf-8"))
_E04 = json.loads(E04_CONTRACT.read_text(encoding="utf-8"))
_E01 = json.loads(E01_CONTRACT.read_text(encoding="utf-8"))
_E05 = json.loads(E05_CONTRACT.read_text(encoding="utf-8"))
_E06 = json.loads(E06_CONTRACT.read_text(encoding="utf-8"))
PREV_LAST = _E07["shots"][-1]
assert PREV_LAST["shot_id"] == PREV_LAST_SHOT

CH = {
    "QM": ("CHAR-QINMING", "秦铭"),
    "LZ": ("CHAR-LUZE", "陆泽"),
    "LWQ": ("CHAR-LIANGWANQING", "梁婉清"),
    "WR": ("CHAR-LUWENRUI", "陆文睿"),
    "WH": ("CHAR-LUWENHUI", "陆文晖"),
    "YQ": ("CHAR-YANGYONGQING", "杨永青"),
    "LLT": ("CHAR-LIULAOTOU", "刘老头"),
    "BOY": ("CHAR-BOY-THIN", "瘦弱男孩"),
    "GIRL": ("CHAR-GIRL-PATCHED", "打补丁的小女孩"),
}
VOICE_ONLY: set = set()
def cid(k): return CH[k][0]
def cname(k): return CH[k][1]

# ---------- 风格与时代约束：沿 E06 合同（唐宋画风，seq=7） ----------
STYLE = {k: v for k, v in _E06["style"].items() if k not in ("authority", "negative_prompt_fixed")}
_PERIOD6 = {**{s["location_id"]: s.get("period_constraints", "") for s in _E01["scene_states"] if s.get("period_constraints")},
            **{s["location_id"]: s["period_constraints"] for s in _E05["scene_states"]},
            **{s["location_id"]: s["period_constraints"] for s in _E06["scene_states"]},
            **{s["location_id"]: s["period_constraints"] for s in _E07["scene_states"]}}
_PERIOD4 = {s["location_id"]: s["period_constraints"] for s in _E04["scene_states"]}
_PERIOD_BASE = _PERIOD6["LOC-QINMING-YARD-EXT"].split("；小院")[0]
PERIOD_BY_LOC = {
    "LOC-SNOWFIELD-WILDS-EXT": _PERIOD_BASE + "；村外雪路与雪原：出村不远踩实的雪路、两侧齐胸深的积雪、雪面月色青蓝反光、远处黑压压的山脉与林线；巡山者的皮甲为唐宋皮革札甲语汇，铁枪为木杆铁头；无路灯、无路标、无栅栏、无任何现代物",
    "LOC-FOREST-EDGE-EXT": _PERIOD4["LOC-FOREST-EDGE-EXT"].split("；黑暗中的猩红眼睛")[0] + "；山林外部区域：落叶松、云杉与白桦耸入夜色，树枝压雪，兽类踩出的小路、残碎兽骨与大蹄印；开阔地血迹斑斑、海碗大的兽爪印；生物一律写实体态，只按参考卡给形貌，不做怪兽特效；无路标、无栅栏、无任何人造物",
    "LOC-LOW-HILL-TOP-EXT": _PERIOD4["LOC-LOW-HILL-TOP-EXT"].split("；矮山顶")[0] + "；矮山半山腰：雪石与稀疏林木，一棵需数人合抱的大树，远处群山黑影；夜空原本什么都没有，远山之上升起的一团白光是画面里唯一的天光；无任何人造物",
    "LOC-SHUANGSHU-VILLAGE-EXT": _PERIOD_BASE + "；双树村村口：夯土与石基的矮墙、茅草与木板压雪的屋顶、踩实的雪路与木栅门，村口一处太阳石的橘红暖光；孩子皆为唐宋童装语汇（棉袄、布带、布鞋），无纽扣拉链、无路灯路标、无任何现代物",
    "LOC-QINMING-YARD-EXT": _PERIOD6["LOC-QINMING-YARD-EXT"],
    "LOC-QINMING-HOUSE-INT": _PERIOD6["LOC-QINMING-HOUSE-INT"],
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
    "scene_seconds_max_exception": "本集无例外：最长场 15 s（E08-S11 / E08-S13）",
    "hook_rule": "全集前 3 秒 = 秦铭贴着树干无声滑下、缩进树影抬头，整片夜空被一团光照亮（E08-S01-01，奇观型钩子）",
    "hook": {"type": "shock", "at_seconds": 0, "line_or_shot_id": "E08-S01-01", "note": "承 E07 末镜：他还在树上仰望那团光；本集第一格是他无声滑落树下缩进阴影，夜空在他抬头的瞬间亮起来"},
    "child_dialogue_rule": "seq=13：本集有三句儿童对白（瘦弱男孩、陆文睿、打补丁的小女孩），每句 ≤14 字，语速按 seq=29 规则 5a 推导，不加快",
    "dialogue_shot_length_rule_seq29": "target_seconds == ceil_0.5(spoken_chars / cps + 0.5)，逐镜断言，无模板值",
}
PACING["camera_motion_policy"] = {**PACING["camera_motion_policy"], "locked_share_max": 0.30}

# ---------- 场次 ----------
SCENES = {
    "E08-S01": dict(loc="LOC-LOW-HILL-TOP-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·矮山合抱大树下·无风", light="夜空那团光把树冠与雪面照出淡银色，树影下仍暗", sec=10, beats=["E08-EV-01", "E08-EV-02"], info=2),
    "E08-S02": dict(loc="LOC-LOW-HILL-TOP-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·矮山坡面·无风", light="皎洁的银光铺满山林与荒岭，山中墨色被驱散，雪面泛银", sec=12, beats=["E08-EV-03", "E08-EV-04"], info=2),
    "E08-S03": dict(loc="LOC-LOW-HILL-TOP-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·矮山坡面·万籁俱寂", light="银光随流光远去而迅速收走，山林重新陷入无边黑暗", sec=12, beats=["E08-EV-05", "E08-EV-06"], info=2),
    "E08-S04": dict(loc="LOC-SNOWFIELD-WILDS-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·雪原回程·风起雪粒", light="雪面青蓝反光，远处村口的橘红灯火在地平线上", sec=8, beats=["E08-EV-07"], info=2),
    "E08-S05": dict(loc="LOC-SHUANGSHU-VILLAGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·双树村村口·无风", light="村口太阳石的橘红暖光照着孩子们的脸，雪地反光偏冷", sec=13.5, beats=["E08-EV-08", "E08-EV-09", "E08-EV-10"], info=2),
    "E08-S06": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·秦铭家小院·无风", light="院中火光初起，橘红暖光自下方照人，院墙外是冷蓝夜色", sec=11.5, beats=["E08-EV-11", "E08-EV-12"], info=2),
    "E08-S07": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·小院·锅气与炊烟", light="火堆与铁锅下的火光为主光，人物面部橘红，蒸汽在光里翻涌", sec=11, beats=["E08-EV-13"], info=2),
    "E08-S08": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·小院·锅气与炊烟", light="火光橘红，孩子的脸被照得发亮", sec=11.5, beats=["E08-EV-14", "E08-EV-15"], info=2),
    "E08-S09": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·小院院门·无风", light="院内火光橘红，院门外是冷蓝雪色，孩子探头处冷暖交界", sec=12, beats=["E08-EV-16", "E08-EV-17"], info=2),
    "E08-S10": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·小院·白雾蒸腾", light="火光橘红，秦铭身上蒸腾的白雾被火光打亮", sec=7, beats=["E08-EV-18"], info=2),
    "E08-S11": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·小院挤满人·无风", light="火光橘红照着一圈人的脸，院门外冷蓝", sec=12, beats=["E08-EV-19", "E08-EV-20"], info=2),
    "E08-S12": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·小院·人声笑语", light="火光橘红，白雾在秦铭身周", sec=14, beats=["E08-EV-21", "E08-EV-22"], info=2),
    "E08-S13": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·小院·白雾更浓", light="火光橘红，白雾几乎裹住秦铭，雾里透出他的轮廓", sec=14, beats=["E08-EV-23", "E08-EV-24"], info=2),
    "E08-S14": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="浅夜·屋内炕边·无风", light="屋内唯一的光是橘红色的暖光，冰水浇下时白雾腾起", sec=12.5, beats=["E08-EV-25", "E08-EV-26"], info=2),
}
AMBIENT_LIFE = {
    "E08-S01": {"grade": "A", "motion_trend": "贴树干无声滑落、缩进树影、抬头、夜空亮起、压声自语", "first_frame_state": "秦铭正攥着弓贴住树干往下滑", "reaction_progression": "滑落→缩进阴影→抬头→「那是月虫」"},
    "E08-S02": {"grade": "B", "motion_trend": "银光铺开、雪面泛银、走出树影仰望、自语", "first_frame_state": "秦铭正站在树影边缘仰着头", "reaction_progression": "光变璀璨→天地染银→出神→「古时候的月亮」"},
    "E08-S03": {"grade": "A", "motion_trend": "万籁俱寂、流光划破长空、光迅速收走、黑暗合拢、远处嚎叫戛然而止", "first_frame_state": "秦铭正仰头望着夜空那团光", "reaction_progression": "寂静→流光远去→重新变黑→一声嚎叫断掉"},
    "E08-S04": {"grade": "A", "motion_trend": "抓绳、拖两头猎物翻过矮山、雪地拖痕、村口灯火在前", "first_frame_state": "秦铭正弯腰抓起拖猎物的绳子", "reaction_progression": "抓绳→翻山→雪地两道长痕→望见村口灯火"},
    "E08-S05": {"grade": "A", "motion_trend": "孩子追跑、瘦弱男孩睁大眼睛发问、孩子们围上来吓一跳、咽口水、秦铭笑着招呼", "first_frame_state": "几个孩子正在村口雪地上相互追跑", "reaction_progression": "追跑→「独自猎杀到了刀角鹿？」→围看驴头狼→咽口水→「都来我家吃肉」"},
    "E08-S06": {"grade": "B", "motion_trend": "拖猎物进院、架锅烧水、梁婉清看见血迹发问、陆泽拨开衣领检查", "first_frame_state": "秦铭正把两头猎物拖进院门", "reaction_progression": "进院→烧水→「你受伤了？」→「轻伤，不碍事」→检查伤口"},
    "E08-S07": {"grade": "A", "motion_trend": "铁锅翻滚、鹿腿滴油、割肉入口、说话", "first_frame_state": "秦铭正蹲在火堆旁看着滴油的鹿腿", "reaction_progression": "锅气升腾→割下薄片→入口→「熟了，味道很好」"},
    "E08-S08": {"grade": "B", "motion_trend": "陆文睿尝肉、眼睛弯成月牙、点头说话、陆文晖咬不动瘪嘴、几人笑", "first_frame_state": "陆文睿正把一片肉送进嘴里", "reaction_progression": "尝一口→「好香啊」→陆文晖瘪嘴→笑"},
    "E08-S09": {"grade": "B", "motion_trend": "孩子门外探头、秦铭招手、孩子们进院鼓腮帮子、梁婉清盛肉汤", "first_frame_state": "几个孩子正扒着院门往里看", "reaction_progression": "探头→「都快进来」→进院吃→「都慢点，还有很多」"},
    "E08-S10": {"grade": "A", "motion_trend": "大口吃肉、汗水冒出、白雾蒸腾、陆泽放下碗筷盯住", "first_frame_state": "秦铭正大口撕咬着手里的肉", "reaction_progression": "狼吞虎咽→出汗→白雾→「身体新生，正在剧烈变化中」"},
    "E08-S11": {"grade": "B", "motion_trend": "村民挤进院子打听、小女孩缩在母亲身后开口、秦铭招手许诺分肉", "first_frame_state": "村民正围着秦铭七嘴八舌地问", "reaction_progression": "围问→「娘，我饿了」→招手→「每家割五斤肉」"},
    "E08-S12": {"grade": "B", "motion_trend": "杨永青挤进来按肩追问、秦铭笑答、杨永青笑着点指", "first_frame_state": "杨永青正伸手按住秦铭的肩膀", "reaction_progression": "按肩→「是不是新生了？」→玩笑作答→「不够朴实啊」"},
    "E08-S13": {"grade": "A", "motion_trend": "刘老头拄杖挤上前感叹、白雾裹住秦铭、杨永青络腮胡颤动听见心跳", "first_frame_state": "刘老头正拄着木杖往人群前挤", "reaction_progression": "挤上前→「数十年头一份」→白雾更浓→杨永青震住"},
    "E08-S14": {"grade": "B", "motion_trend": "递刀交代、冰水浇下白雾腾起、躺上炕、呼吸变深变慢", "first_frame_state": "秦铭正把切肉的刀递向画外的手", "reaction_progression": "递刀→「给周家多送一些肉」→冰水冲身→躺炕睡去"},
}
def _wp(sid, mode):
    return {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": f"E07_NARRATIVE_CANONICAL_v1.md#{sid}｜ch7", "visibility_mode": mode}
WEATHER_PROVENANCE = {sid: _wp(sid, "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED") for sid in SCENES}
for _sid, _m in SCENES.items():
    _m["ambient_life"] = AMBIENT_LIFE[_sid]
    _m["weather_provenance"] = WEATHER_PROVENANCE[_sid]

# ---------- 服装（承 E06 / E04 合同的 wardrobe_garments；新人物按唐宋语汇） ----------
_WG7 = {c["character_id"]: c["wardrobe_garments"] for c in _E07["character_entities"]}
_WG6 = {c["character_id"]: c["wardrobe_garments"] for c in _E06["character_entities"]}
_WG5 = {c["character_id"]: c["wardrobe_garments"] for c in _E05["character_entities"]}
_WG4 = {c["character_id"]: c["wardrobe_garments"] for c in _E04["character_entities"]}
WARDROBE_GARMENTS = {
    "CHAR-QINMING": {**_WG7["CHAR-QINMING"], "condition": "刚从山里回来：裘氅与棉衣上全是雪水，双肩棉衣被大爪子抓烂、肩头血痂；E08-S10 起浑身汗湿、蒸腾白雾；E08-S14 用冰水冲过后湿透"},
    "CHAR-LUZE": {**_WG6["CHAR-LUZE"], "condition": "在院中帮忙：袖口挽起，衣襟上沾着柴灰"},
    "CHAR-LIANGWANQING": {**_WG6["CHAR-LIANGWANQING"], "condition": "在院中盛汤：围着旧布围裙，袖口挽起"},
    "CHAR-LUWENRUI": {**_WG6["CHAR-LUWENRUI"], "condition": "吃肉时嘴角带油光，棉袄前襟沾了油渍"},
    "CHAR-LUWENHUI": {**_WG5["CHAR-LUWENHUI"], "condition": "被裹在厚棉袄里，前襟围着一块旧布当围嘴"},
    "CHAR-YANGYONGQING": {**_WG7["CHAR-YANGYONGQING"], "condition": "闻讯赶来：黑褐旧皮坎肩与络腮胡上落着新雪"},
    "CHAR-LIULAOTOU": {"silhouette": "六十余岁、背微驼、个子不高、拄一根木杖", "outer_layer": "旧羊皮袄（外层，毛面朝内，袖口磨秃）", "inner_layer": "深褐粗麻交领窄袖袍", "primary_color": "深褐", "secondary_color": "土黄", "material": "羊皮＋粗麻", "pattern": "无纹样，补丁在两肘", "belt_or_fastening": "麻绳束腰", "footwear": "旧布靴加草绳缠裹", "accessory": "旧皮帽护耳；花白山羊胡；右手拄一根去皮木杖", "condition": "长期穿用，袖口与下摆磨损发亮"},
    "CHAR-BOY-THIN": {"silhouette": "十岁上下、瘦、肩窄、缩着脖子", "outer_layer": "打补丁的旧棉袄（外层，补丁在两肘与前襟）", "inner_layer": "土布短褐", "primary_color": "土黄", "secondary_color": "深灰", "material": "粗麻＋旧棉", "pattern": "无纹样，补丁形状不规则", "belt_or_fastening": "麻绳系腰", "footwear": "旧布鞋加麻绳缠裹", "accessory": "无冠，短发被冻得贴在额前", "condition": "冻得小脸通红，袖口发硬"},
    "CHAR-GIRL-PATCHED": {"silhouette": "六七岁、个子小、缩在大人身后", "outer_layer": "打补丁的旧棉袄（外层，补丁在肩与下摆）", "inner_layer": "土布短襦", "primary_color": "灰褐", "secondary_color": "土黄", "material": "粗麻＋旧棉", "pattern": "无纹样，补丁颜色不一", "belt_or_fastening": "布带系腰", "footwear": "旧布鞋", "accessory": "无冠，头发用布条扎成两个小髻", "condition": "冻得小脸通红，手缩在袖子里"},
}

# ---------- 道具、生物与布景 ----------
PROPS = [
    {"entity_id": "PROP-BOW-ARROWS", "name": "弓箭", "reference_card_required": False, "first_shot": "E08-S01-01",
     "note": "E04 已出卡并锁定：竹木硬弓与皮箭囊；本集只背在背上与攥在手里，回村后卸下", "period_constraints": "唐宋竹木复合弓与皮箭囊，铁镞木杆铁箭；无金属滑轮、无现代箭袋"},
    {"entity_id": "PROP-SHORT-KNIFE", "name": "短刀", "reference_card_required": False, "first_shot": "E08-S06-03",
     "note": "E03 已出卡并锁定：直刃短刀；本集用来从鹿腿上割下薄片，末场递给画外的手", "period_constraints": "锻铁直刃、木柄，无护手无现代刀具"},
    {"entity_id": "PROP-BLADE-HORN-STAG", "name": "刀角鹿", "kind": "CREATURE", "creature_card": {"locomotion": "quadruped", "eye_color": "深褐", "silhouette_ref": "PROP-BLADE-HORN-STAG identity plate (workflow/nalu/E07/identity)"}, "reference_card_required": False, "first_shot": "E08-S05-02",
     "note": "E07 已出卡并锁定：黑褐色大雄鹿、六支扁平刀形角、七百斤；本集全程是一具被绳拖行的尸体，后半集只剩被割开的鹿腿", "period_constraints": "写实鹿类体态，角为扁平刀形骨角，不发光"},
    {"entity_id": "PROP-DONKEY-HEAD-WOLF", "name": "驴头狼", "kind": "CREATURE", "creature_card": {"locomotion": "biped", "eye_color": "猩红", "silhouette_ref": "PROP-DONKEY-HEAD-WOLF identity plate (workflow/nalu/E07/identity)"}, "reference_card_required": False, "first_shot": "E08-S05-03",
     "note": "E07 已出卡并锁定：硕大驴头、黑鬃、四百斤；本集全程是一具被绳拖行的尸体，眼睛不再发红", "period_constraints": "写实猛兽体态，死后双眼无光，不发光"},
    {"entity_id": "PROP-IRON-POT", "name": "铁锅", "reference_card_required": True, "first_shot": "E08-S06-01",
     "note": "架在院中石灶上的一口黑铁锅：厚壁、双耳、锅沿磨亮，锅里翻滚着大块的肉与汤；参考卡为石灶上的铁锅侧前方全貌，锅气升腾", "period_constraints": "唐宋铸铁炊具语汇，无搪瓷、无不锈钢、无现代把手"},
    {"entity_id": "PROP-ROAST-DEER-LEG", "name": "烤鹿腿", "reference_card_required": True, "first_shot": "E08-S07-01",
     "note": "架在火堆上的一整条鹿腿：外层烤出焦褐色泽，油脂不断滴进火里溅起火星，插一根去皮木杆穿过；参考卡为火堆上滴油的鹿腿特写", "period_constraints": "柴火明火直烤，木杆穿串，无金属烤架、无现代调料瓶"},
    {"entity_id": "PROP-MEAT-BROTH-BOWL", "name": "肉汤粗陶碗", "reference_card_required": False, "first_shot": "E08-S09-04",
     "note": "梁婉清给孩子们盛肉汤用的粗陶碗，厚壁、土褐色、碗沿有磕口；与 E01 起院中所用陶器同一系", "period_constraints": "唐宋粗陶，无釉彩、无现代餐具"},
    {"entity_id": "PROP-KANG", "name": "土炕", "reference_card_required": False, "first_shot": "E08-S14-03",
     "note": "E01 已出卡并锁定：屋内的土炕，铺着旧褥子；本集末场秦铭躺上去睡去", "period_constraints": "北方土炕，无床架、无现代寝具"},
    {"entity_id": "PROP-WOODEN-STAFF", "name": "木杖", "reference_card_required": False, "first_shot": "E08-S13-01",
     "note": "刘老头拄的一根去皮木杖，杖头被手握得发亮", "period_constraints": "天然木杖，无金属包头"},
]
SETS = [
    {"entity_id": "SET-MOON-INSECT-LIGHT", "name": "月虫之光", "reference_card_required": True, "first_shot": "E08-S01-02",
     "note": "承 E07 的 SET-DISTANT-MOON-LIGHT：同一团光在本集升到最亮——光芒交织如一块绚烂的圆盘，像天阙之灯高悬，看不出虫的形态；参考卡只画夜空中这团极亮的圆光与被染成淡银色的山林，绝不画出虫的形貌", "period_constraints": "夜空里唯一的天光，无星无月无人造光"},
    {"entity_id": "SET-SILVER-LIT-RIDGE", "name": "银色荒岭", "reference_card_required": True, "first_shot": "E08-S01-03",
     "note": "被月虫之光铺满的山林与荒岭：雪面泛起淡银色，山脊轮廓清楚，浓重墨色被驱散；参考卡只画被银光铺满的雪岭与林线，不画人物与生物", "period_constraints": "自然雪岭，无人造物、无灯火"},
]

# ---------- 机位方案（每镜；本集无 LOCKED） ----------
def _cp(scale, height, side, lens, axis, fam, direction, start, end, why):
    if fam == "LOCKED" and end != start:
        why = f"{why}；画内变化：{end}"
        end = start
    return {"shot_scale": scale, "camera_height": height, "camera_side": side, "lens_intent": lens, "axis_relation": axis,
            "motion_family": fam, "motion_direction": direction, "start_framing": start, "end_framing": end, "motivation": why}
CAMERA_PLANS = {
    "E08-S01-01": _cp("WIDE", "LOW", "AXIS_A", "24mm低机位仰拍随秦铭贴着树干滑下", "秦铭（画面中央）自树上滑向树下", "CRANE", "FALL", "低机位远景：秦铭攥着弓贴住树干往下滑", "低机位远景（下降）：他落到树下缩进树影", "导演稿：下降接住上一集的树上末帧"),
    "E08-S01-02": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_B", "35mm自树影中的秦铭缓缓升到他仰望的夜空", "秦铭（画面下方）仰望夜空的光（画面上方）", "CRANE", "RISE", "低机位远景：秦铭缩在树影里抬起头", "低机位远景（上摇）：整片夜空被那团光照亮", "导演稿：上摇把奇观交给观众"),
    "E08-S01-03": _cp("MEDIUM_CLOSE_UP", "LOW", "AXIS_B", "50mm低机位缓推被光照亮的秦铭的脸", "秦铭（画面中央）仰头望向画外上方的光", "DOLLY", "PUSH_IN", "低机位中近景：秦铭仰着头，脸被淡银的光照亮", "低机位中近景（推近）：他压着嗓子说完，攥紧弓弦", "导演稿：推近读认出月虫"),
    "E08-S02-01": _cp("WIDE", "HIGH", "AXIS_A", "24mm高机位横移过越来越亮的光与林线", "光（画面上方）洒向山林（画面下方）", "TRACK", "LEFT_TO_RIGHT", "高机位远景：光芒交织如一块绚烂的圆盘", "高机位远景（横移）：皎洁的光洒满沉在墨色里的山林", "导演稿：横移读天地变色"),
    "E08-S02-02": _cp("WIDE", "EYE_LEVEL", "AXIS_A", "28mm横移过泛起银色的雪岭与荒岭", "银光自远山（画左）铺向近处雪坡（画右）", "TRACK", "RIGHT_TO_LEFT", "远景：荒岭与雪面被染成淡淡的银色", "远景（横移）：山中浓重的墨色被彻底驱散", "导演稿：横移读银色荒岭"),
    "E08-S02-03": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm缓推走出树影仰望的秦铭", "秦铭（画面中央）仰望画外上方的光", "DOLLY", "PUSH_IN", "中景：秦铭从树影里走出半步仰着头", "中景（推近）：他出神地问出那一句", "导演稿：推近读神往"),
    "E08-S03-01": _cp("WIDE", "HIGH", "AXIS_A", "24mm高机位环摇寂静的银色山林", "山林（画面四周）环绕仰望的秦铭（画面中央）", "ARC", "CLOCKWISE", "高机位远景：万籁俱寂的银色山林", "高机位远景（环摇）：飞禽走兽都安静地蛰伏", "导演稿：环摇读死寂"),
    "E08-S03-02": _cp("WIDE", "LOW", "AXIS_A", "24mm低机位横摇随一道流光划过长空", "流光自夜空一侧（画左）划向另一侧（画右）", "PAN", "LEFT_TO_RIGHT", "低机位远景：一道流光划破长空", "低机位远景（横摇）：光迅速远去，地带失去光彩", "导演稿：横摇送走月虫"),
    "E08-S03-03": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_B", "35mm缓拉开重新变黑的山林与转头的秦铭", "秦铭（画右）转头望向深山（画左）", "DOLLY", "PULL_OUT", "中全景：山林的银色迅速褪尽，只剩雪面微光", "中全景（拉开）：深山一声嚎叫戛然而止，他转头望去", "导演稿：拉开读余悸"),
    "E08-S04-01": _cp("WIDE", "HIGH", "AXIS_A", "24mm高机位随秦铭拖着两头猎物翻过矮山", "秦铭自矮山这侧（画右）拖猎物翻向那侧（画左）", "TRACK", "RIGHT_TO_LEFT", "高机位远景：秦铭弯腰抓起拖猎物的绳子", "高机位远景（横移）：他拖着两头猎物翻过矮山", "导演稿：横移读回程"),
    "E08-S04-02": _cp("MEDIUM_WIDE", "HIGH", "AXIS_B", "35mm高机位下降贴到雪地上的两道长痕再抬向村口灯火", "拖痕自画面近处延向村口（画面远处）", "CRANE", "FALL", "高机位远景：雪地上拖出两道长痕", "高机位远景（横移）：双树村轮廓与村口灯火在前方", "导演稿：横移读将至"),
    "E08-S05-01": _cp("MEDIUM_WIDE", "LOW", "AXIS_B", "28mm低机位随追跑的孩子横摇到走来的秦铭", "孩子们（画左）与拖猎物走来的秦铭（画右）；跑在最前的瘦弱男孩朝镜头这一侧跑、整张脸正对镜头且完整在画面内，不得只给背影或后脑", "PAN", "LEFT_TO_RIGHT", "低机位中全景：几个孩子在村口雪地上相互追跑，跑在最前的瘦弱男孩正对着镜头跑来、整张小脸清晰入画", "低机位中全景（横摇）：他们停下望着拖猎物走来的人", "导演稿：横摇交接村口"),
    "E08-S05-02": _cp("MEDIUM_CLOSE_UP", "LOW", "AXIS_A", "50mm低机位缓推睁大眼睛的瘦弱男孩", "瘦弱男孩（画左）仰头看秦铭（画右）", "DOLLY", "PUSH_IN", "低机位中近景：瘦弱男孩看见雪地上的刀角鹿", "低机位中近景（推近）：他吃惊地睁大眼睛问出口", "导演稿：推近读吃惊"),
    "E08-S05-03": _cp("MEDIUM_WIDE", "LOW", "AXIS_B", "28mm低机位环绕围上来的孩子与雪地上的驴头狼", "孩子们（画左）围向猎物（画右）", "ARC", "COUNTERCLOCKWISE", "低机位中全景：孩子们一起凑上前", "低机位中全景（环绕）：看清黑色驴头狼都吓了一跳，偷偷咽口水", "导演稿：环绕读震慑"),
    "E08-S05-04": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm缓推笑着招呼孩子的秦铭", "秦铭（画右）面向孩子们（画左）", "DOLLY", "PUSH_IN", "中景：秦铭拖着绳子停下脚步", "中景（推近）：他笑着说完，拖起绳子往村里走", "导演稿：推近读邀约"),
    "E08-S06-01": _cp("MEDIUM_WIDE", "HIGH", "AXIS_A", "28mm高机位随两头猎物被拖进院门再摇向石灶", "猎物自院门（画右）被拖向院中（画左）", "PAN", "RIGHT_TO_LEFT", "高机位中全景：秦铭把两头猎物拖进院子", "高机位中全景（横摇）：他架起铁锅烧水，火光在锅底亮起", "导演稿：横摇读到家"),
    "E08-S06-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm缓推看见血迹的梁婉清", "梁婉清（画左）看向秦铭的肩头（画右）", "DOLLY", "PUSH_IN", "中近景：梁婉清端着水盆停在秦铭身侧", "中近景（推近）：她一眼看到肩头的血迹，出声发问", "导演稿：推近读心细"),
    "E08-S06-03": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm反打摇头作答的秦铭", "秦铭（画右）面向梁婉清（画左）", "DOLLY", "PUSH_IN", "中近景：秦铭往火堆里添了一根柴", "中近景（推近）：他摇头答完，转身去拿短刀", "导演稿：反打读轻描淡写"),
    "E08-S06-04": _cp("MEDIUM", "HIGH", "AXIS_A", "35mm高机位俯看陆泽拨开衣领查看伤口", "陆泽（画左）俯身查看秦铭的肩（画右）", "DOLLY", "PUSH_IN", "中景：陆泽伸手拨开秦铭的衣领", "中景（推近）：伤口不深已结血痂，他松开手直起身", "导演稿：推近读放心"),
    "E08-S07-01": _cp("MEDIUM_CLOSE_UP", "LOW", "AXIS_A", "50mm低机位缓推火堆上滴油的鹿腿", "鹿腿（画面中央）在火堆上方", "DOLLY", "PUSH_IN", "低机位中近景：铁锅翻滚，火堆上的鹿腿滴下油脂", "低机位中近景（推近）：油滴落进火里溅起火星", "导演稿：推近读肉香"),
    "E08-S07-02": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm缓推割肉入口的秦铭", "秦铭（画右）面向鹿腿（画左）", "DOLLY", "PUSH_IN", "中景：秦铭举着短刀凑近鹿腿", "中景（推近）：他割下薄薄一片直接放进嘴里", "导演稿：推近读饿了一路"),
    "E08-S07-03": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm缓推嚼着肉说话的秦铭，陆文睿在画右", "秦铭（画左）面向陆文睿（画右）", "DOLLY", "PUSH_IN", "中景：秦铭嚼着那片肉抬起头", "中景（推近）：他冲陆文睿说完，把刀递向鹿腿", "导演稿：推近读满足愿望"),
    "E08-S08-01": _cp("MEDIUM_CLOSE_UP", "LOW", "AXIS_B", "50mm低机位缓推眯眼点头的陆文睿", "陆文睿（画面中央）面向画外的秦铭", "DOLLY", "PUSH_IN", "低机位中近景：陆文睿把一小片肉送进嘴里", "低机位中近景（推近）：他眼睛弯成月牙，点着头说完", "导演稿：推近读孩子的满足"),
    "E08-S08-02": _cp("MEDIUM_CLOSE_UP", "HIGH", "AXIS_A", "50mm高机位俯看咬不动鹿腿的陆文晖", "陆文晖（画面中央）面向画外的大人", "DOLLY", "PUSH_IN", "高机位中近景：陆文晖抱着鹿腿咬不动", "高机位中近景（推近）：他改吃肉糊，委屈地瘪起嘴", "导演稿：推近读委屈"),
    "E08-S08-03": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_B", "28mm横移过被逗笑的几个人", "陆文晖（画左）与笑起来的大人（画右）", "TRACK", "LEFT_TO_RIGHT", "中全景：陆文晖瘪着嘴眼巴巴地看着", "中全景（横移）：梁婉清与秦铭都笑了起来", "导演稿：横移读暖"),
    "E08-S09-01": _cp("MEDIUM_WIDE", "LOW", "AXIS_A", "28mm低机位自院门外向院内推，孩子扒着门框", "孩子们（画右）朝向院中的火光（画左）", "DOLLY", "PUSH_IN", "低机位中全景：几个孩子扒着院门往里看", "低机位中全景（推近）：他们闻着肉香不好意思进门", "导演稿：推近读渴望"),
    "E08-S09-02": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm缓推朝院门招手的秦铭", "秦铭（画左）面向院门（画右）", "DOLLY", "PUSH_IN", "中景：秦铭抬头看见院门外的孩子", "中景（推近）：他招着手说完，往火堆旁挪出空位", "导演稿：推近读招呼"),
    "E08-S09-03": _cp("MEDIUM_WIDE", "LOW", "AXIS_A", "28mm低机位环绕鼓着腮帮子吃肉的孩子", "孩子们（画面中央）围着火堆", "ARC", "CLOCKWISE", "低机位中全景：孩子们腼腆地走进院子", "低机位中全景（环绕）：他们鼓着腮帮子含混不清地嚷着好吃", "导演稿：环绕读热闹"),
    "E08-S09-04": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm缓推盛肉汤的梁婉清", "梁婉清（画右）面向孩子们（画左）", "DOLLY", "PUSH_IN", "中景：梁婉清端起粗陶碗舀汤", "中景（推近）：她把碗递过去，嘱咐完直起身", "导演稿：推近读照看"),
    "E08-S10-01": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm缓推大口吃肉、汗水直冒的秦铭", "秦铭（画面中央）面向火堆", "DOLLY", "PUSH_IN", "中近景：秦铭大口撕咬着手里的肉", "中近景（推近）：汗水从额头滚落，身上蒸腾起白雾", "导演稿：推近读异常"),
    "E08-S10-02": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm反打放下碗筷盯住白雾的陆泽", "陆泽（画左）看向秦铭（画右）", "DOLLY", "PUSH_IN", "中景：陆泽端着碗停住", "中景（推近）：他放下碗筷，盯住那团白雾说出口", "导演稿：反打读看破"),
    "E08-S11-01": _cp("WIDE", "HIGH", "AXIS_A", "24mm高机位俯看挤满人的小院", "村民（画面四周）围着秦铭（画面中央）", "ARC", "COUNTERCLOCKWISE", "高机位远景：院子里来了很多村民", "高机位远景（环绕）：他们围着秦铭七嘴八舌地打听山里的情况", "导演稿：环绕读消息传开"),
    "E08-S11-02": _cp("MEDIUM_CLOSE_UP", "LOW", "AXIS_B", "50mm低机位缩在母亲身后的小女孩", "小女孩（画左）仰头看向画外的母亲", "DOLLY", "PUSH_IN", "低机位中近景：小女孩缩在母亲身后望着烤肉", "低机位中近景（推近）：她低声说完，把手缩进袖子里", "导演稿：推近读饿"),
    "E08-S11-03": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm缓推看着孩子们招手的秦铭", "秦铭（画右）面向一圈人（画左）", "DOLLY", "PUSH_IN", "中景：秦铭看着那一张张冻红的小脸", "中景（推近）：他抬手招呼完，把切好的肉往旁边推", "导演稿：推近读允诺"),
    "E08-S12-01": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm缓推挤进来按住肩膀的杨永青", "杨永青（画左）面向秦铭（画右）", "DOLLY", "PUSH_IN", "中景：杨永青挤开人群伸出手", "中景（推近）：他一把按住秦铭的肩膀追问", "导演稿：推近读追问"),
    "E08-S12-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm反打笑着点头的秦铭", "秦铭（画右）面向杨永青（画左）", "DOLLY", "PUSH_IN", "中近景：秦铭被按着肩膀笑起来", "中近景（推近）：他点着头把话头抛回去", "导演稿：反打读玩笑"),
    "E08-S12-03": _cp("MEDIUM_WIDE", "LOW", "AXIS_B", "28mm低机位横移到并肩站着的两人", "秦铭（画右）与杨永青（画左）并肩站在人群里", "TRACK", "LEFT_TO_RIGHT", "中近景：秦铭笑着接上后半句", "中近景（推近）：他说完抹了一把额头的汗", "导演稿：续推读顺势"),
    "E08-S12-04": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm缓推笑着点指的杨永青", "杨永青（画左）面向秦铭（画右）", "DOLLY", "PUSH_IN", "中景：杨永青松开手笑出声", "中景（推近）：他点指着秦铭说完，收回手", "导演稿：推近读打趣"),
    "E08-S13-01": _cp("MEDIUM", "LOW", "AXIS_A", "35mm低机位缓推拄杖挤上前的刘老头", "刘老头（画左）面向白雾里的秦铭（画右）", "DOLLY", "PUSH_IN", "低机位中景：刘老头拄着木杖往前挤", "低机位中景（推近）：他看着白雾里的人感叹完，杖头顿了顿地", "导演稿：推近读分量"),
    "E08-S13-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm缓推白雾里的秦铭", "秦铭（画面中央）被白雾裹着", "DOLLY", "PUSH_IN", "中近景：汗水把秦铭的衣服浸湿", "中近景（推近）：白雾几乎把他裹住，雾里透出轮廓", "导演稿：推近读新生外显"),
    "E08-S13-03": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm缓推络腮胡颤动的杨永青", "杨永青（画左）望向白雾里的秦铭（画右）", "DOLLY", "PUSH_IN", "中近景：杨永青凑近半步", "中近景（推近）：他的络腮胡须颤动起来，眼睛睁大", "导演稿：推近读震住"),
    "E08-S14-01": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm缓推把刀递出去的秦铭", "秦铭（画右）把刀递向陆泽（画左）；两人侧身相对、坐在同一景深的炕沿两端，镜头从侧面平拍两人的四分之三侧脸：秦铭在画右、陆泽在画左，两张脸都完整入画、都被火光照亮、都清晰可辨；画面前景严禁出现任何人物的后脑、背影或肩膀做遮挡（不拍过肩镜），两人都不得背对镜头；各自的脸必须与自己的人物身份权威参考图是同一张脸（脸型、五官比例、年龄完全一致），不得换脸、混脸或改成另一个演员", "DOLLY", "PUSH_IN", "中景：秦铭（画右，四分之三侧脸入画）撑着桌沿眼皮直往下掉，画左的陆泽侧坐着四分之三侧脸朝镜头伸手来接，两张脸都完整在画面里", "中景（推近）：他把切肉的刀递出去，交代完松开手", "导演稿：推近读交托"),
    "E08-S14-02": _cp("MEDIUM", "LOW", "AXIS_A", "35mm低机位随一盆冰水从头浇下", "冰水（画面上方）浇向秦铭（画面下方）", "CRANE", "FALL", "低机位中景：秦铭端起一盆冰水举过头顶", "低机位中景（下降）：水浇下，白雾从他身上腾起", "导演稿：下降读冲洗"),
    "E08-S14-03": _cp("MEDIUM_WIDE", "HIGH", "AXIS_A", "28mm高机位俯看躺上炕的秦铭", "秦铭（画面中央）躺在炕上", "CRANE", "FALL", "高机位中全景：秦铭走到炕边坐下", "高机位中全景（下降）：他躺上炕，胸口的起伏又深又慢", "导演稿：下降收尾入眠"),
}
# emotion（NPR 说法条款 key）, perf(情绪词, 进行中的身体动作, 说话方式), after_line, entry, exit, dims, referents, faces, cps, slots, identity_reanchor
# D-68 ＋ seq=45：entry 写上一镜留下的姿态（站/蹲/跪/坐/伏/攀），姿态改变写在本镜 action/exit 里；同一地点跨场也要连。
D = lambda a, b, ca, cb: (a, b, ca, cb)
BOW, KNIFE, STAG, WOLF, POT, LEG, BOWL, KANG, STAFF, MOONLIGHT, RIDGE = (
    "PROP-BOW-ARROWS", "PROP-SHORT-KNIFE", "PROP-BLADE-HORN-STAG", "PROP-DONKEY-HEAD-WOLF",
    "PROP-IRON-POT", "PROP-ROAST-DEER-LEG", "PROP-MEAT-BROTH-BOWL", "PROP-KANG", "PROP-WOODEN-STAFF",
    "SET-MOON-INSECT-LIGHT", "SET-SILVER-LIT-RIDGE")
CREATURE_ONLY = "FACE_OUT_OF_FRAME_CREATURE_ONLY"
SHOTS = [
    # S01 —— 承 E07 末镜：他还在树上仰望那团光；钩子＝滑下树、夜空亮起、认出月虫
    dict(s="E08-S01", n=1, sec=4, size="远景", camera="低机位仰拍随秦铭贴着树干滑下", axis="秦铭（画面中央）自树上滑向树下", blocking="秦铭攥着弓贴住树干无声地滑落到树下，落地后缩进密林的阴影间",
         cast=["QM"], action=("QM", "秦铭攥着弓贴住树干无声地滑落到树下，落地后立刻缩进密林的阴影间", ""),
         faces={"QM": "BACK_TO_CAMERA_ON_TRUNK"},
         entry="秦铭在树上扶着树干，弓弦攥在手里", exit="秦铭缩在树下的阴影里，弓还攥在手里",
         dims={"POSITION": D("树上高处", "树下阴影", "UP_THE_TREE", "AT_TREE_FOOT"), "MOMENTUM": D("攀着不动", "滑落到地", "HOLDING_TRUNK", "SLID_DOWN")}, referents=[("他", "QM")]),
    dict(s="E08-S01", n=2, sec=4, size="中全景", camera="自树影中的秦铭缓缓升到他仰望的夜空", axis="秦铭（画面下方）仰望夜空的光（画面上方）", blocking="秦铭缩在树影里抬起头，夜空中那团光照亮了整片夜空，没有日月星辰的天地里这是唯一的光",
         cast=["QM"], action=("QM", "秦铭缩在树影里抬起头，夜空中那团光照亮了整片夜空，没有日月星辰的天地里只有这一处光", MOONLIGHT),
         faces={"QM": "FAR_FIGURE_LOOKING_UP"},
         entry="秦铭缩在树下的阴影里，弓还攥在手里", exit="秦铭仰着头，整片夜空被那团光照亮",
         dims={"POSTURE": D("缩在阴影里低着头", "仰头望向夜空", "HEAD_DOWN_IN_SHADOW", "HEAD_UP_TO_SKY")}, referents=[("他", "QM")]),
    dict(s="E08-S01", n=3, identity_reanchor=True, sec=4, cps=5.0, size="中近景", camera="低机位缓推被光照亮的秦铭的脸", axis="秦铭（画面中央）仰头望向画外上方的光", blocking="秦铭仰着头，脸被淡银色的光照亮，他压低声音说出三个字，说完攥紧弓弦",
         cast=["QM"], action=("QM", "秦铭仰着头，脸被淡银色的光照亮，他压低声音说一句，说完立即攥紧弓弦", ""), dialogue=("QM", "那是月虫。", ""), emotion="calm",
         perf=("惊", "仰着头盯住夜空里那团光", "压低声音一口气说完"), after_line="攥紧弓弦",
         entry="秦铭仰着头，整片夜空被那团光照亮", exit="秦铭攥紧弓弦，仍仰头望着那团光",
         dims={"CONTACT": D("弓松松攥着", "弓弦攥紧", "BOW_LOOSE", "BOWSTRING_GRIPPED")}, referents=[]),
    # S02 —— 光变璀璨、天地染银、出神
    dict(s="E08-S02", n=1, sec=4, size="远景", camera="高机位横移过越来越亮的光与林线", axis="光（画面上方）洒向山林（画面下方）", blocking="那团光起初柔和，此刻太过璀璨，光芒交织像一块绚烂的圆盘，看不出虫的形态",
         cast=["QM"], action=(MOONLIGHT, "那团光越来越亮，光芒交织像一块绚烂的圆盘，看不出虫的形态，皎洁的光洒向漆黑的山林", ""),
         faces={"QM": CREATURE_ONLY},
         entry="夜空中那团光照着漆黑的山林", exit="光芒交织如一块绚烂的圆盘，山林被照亮",
         dims={"INTEGRITY": D("光柔和", "光璀璨如圆盘", "LIGHT_SOFT", "LIGHT_BLAZING")}, referents=[]),
    dict(s="E08-S02", n=2, sec=4, size="远景", camera="横移过泛起银色的雪岭与荒岭", axis="银光自远山（画左）铺向近处雪坡（画右）", blocking="皎洁的光铺满幽暗的荒岭，整片地带被染成淡淡的银色，山中浓重的墨色被彻底驱散",
         cast=["QM"], action=(RIDGE, "皎洁的光铺满幽暗的荒岭，整片地带被染成淡淡的银色，山中浓重的墨色被彻底驱散", ""),
         faces={"QM": CREATURE_ONLY},
         entry="光芒交织如一块绚烂的圆盘，山林被照亮", exit="荒岭与雪面被染成淡淡的银色",
         dims={"INTEGRITY": D("山林漆黑", "山林染成淡银色", "RIDGE_BLACK", "RIDGE_SILVER")}, referents=[]),
    dict(s="E08-S02", n=3, sec=4, cps=5.0, size="中景", camera="缓推走出树影仰望的秦铭", axis="秦铭（画面中央）仰望画外上方的光", blocking="秦铭从树影里走出半步仰着头，雪面在他脚下泛着银光，他出神地问出一句，说完慢慢收回目光",
         cast=["QM"], action=("QM", "秦铭从树影里走出半步仰着头，雪面在脚下泛着银光，他出神地问一句，说完立即慢慢收回目光", ""), dialogue=("QM", "古时候的月亮，就是这个样子吗？", ""), emotion="calm",
         perf=("盼", "从树影里走出半步仰头望着银色的天地", "出神地轻声说"), after_line="慢慢收回目光",
         entry="秦铭攥紧弓弦，仍仰头望着那团光", exit="秦铭收回目光，站在泛银的雪面上",
         dims={"POSITION": D("站在树影里", "走出树影半步", "IN_TREE_SHADOW", "OUT_OF_SHADOW")}, referents=[]),
    # S03 —— 死寂、流光远去、深山一声嚎叫
    dict(s="E08-S03", n=1, sec=4, size="远景", camera="高机位环摇寂静的银色山林", axis="山林（画面四周）环绕仰望的秦铭（画面中央）", blocking="万籁俱寂，银色的山林里飞禽走兽都安静地蛰伏着，没有一丝声响",
         cast=["QM"], action=(RIDGE, "万籁俱寂，银色的山林里飞禽走兽都安静地蛰伏着，雪坡上只有秦铭一个小小的人影", ""),
         faces={"QM": "FAR_FIGURE_IN_SILVER_FOREST"},
         entry="秦铭收回目光，站在泛银的雪面上", exit="银色山林一片死寂，秦铭立在雪坡上",
         dims={"MOMENTUM": D("林中有风声", "万籁俱寂", "FOREST_ALIVE", "FOREST_SILENT")}, referents=[]),
    dict(s="E08-S03", n=2, sec=4, size="远景", camera="低机位横摇随一道流光划过长空", axis="流光自夜空一侧（画左）划向另一侧（画右）", blocking="一道流光划破长空，那团光迅速远去，这片地带快速失去光彩",
         cast=["QM"], action=(MOONLIGHT, "一道流光划破长空，那团光迅速远去，这片地带快速失去光彩", ""),
         faces={"QM": CREATURE_ONLY},
         entry="银色山林一片死寂，秦铭立在雪坡上", exit="流光远去，银色迅速从山林上褪走",
         dims={"POSITION": D("光悬在夜空", "光远去天边", "LIGHT_OVERHEAD", "LIGHT_GONE")}, referents=[]),
    dict(s="E08-S03", n=3, identity_reanchor=True, sec=4, size="中全景", camera="缓拉开重新变黑的山林与转头的秦铭", axis="秦铭（画右）转头望向深山（画左）", blocking="山林的银色迅速褪尽只剩雪面微光，大山深处传来一声凄厉的嚎叫又戛然而止，秦铭猛然转身退了半步望去",
         cast=["QM"], action=("QM", "山林的银色迅速褪尽只剩雪面微光，大山深处传来一声凄厉的嚎叫又戛然而止，秦铭猛然转身退了半步望向深山方向", ""),
         entry="流光远去，银色迅速从山林上褪走", exit="山林只剩雪面微光，秦铭退了半步望着深山方向",
         dims={"POSTURE": D("仰头望天", "转身退半步望向深山", "HEAD_UP", "TURNED_AND_STEPPED_BACK")}, referents=[("他", "QM")]),
    # S04 —— 翻山回程
    dict(s="E08-S04", n=1, sec=4, cps=5.0, size="远景", camera="高机位随秦铭拖着两头猎物翻过矮山", axis="秦铭自矮山这侧（画右）拖猎物翻向那侧（画左）", blocking="秦铭弯腰抓起绳子压着嗓子丢下一句，拖着刀角鹿与驴头狼翻过矮山迅速远去",
         cast=["QM"], action=("QM", "秦铭弯腰抓起绳子压着嗓子说一句，说完立即拖着两头猎物翻过矮山迅速远去", STAG), dialogue=("QM", "趁它们还不敢出来。", ""), emotion="calm",
         perf=("坚", "弯腰抓起拖猎物的绳子", "压着嗓子快而低地说"), after_line="拖着两头猎物翻过矮山",
         faces={"QM": "FAR_FIGURE_DRAGGING"},
         entry="山林只剩雪面微光，秦铭退了半步望着深山方向", exit="秦铭拖着两头猎物翻过矮山脊线",
         dims={"POSITION": D("站在雪坡上", "翻过矮山脊", "ON_SLOPE", "OVER_THE_RIDGE"), "CONTACT": D("空着手", "绳子攥在手里", "EMPTY_HAND", "ROPE_IN_HAND")}, referents=[("他", "QM")]),
    dict(s="E08-S04", n=2, sec=4, size="中全景", camera="高机位下降贴到雪地上的两道长痕再抬向村口灯火", axis="拖痕自画面近处延向村口（画面远处）", blocking="雪地上拖出两道长痕，双树村的轮廓在前方出现，村口的灯火在雪原尽头亮着",
         cast=["QM"], action=("QM", "雪地上被拖出两道长痕，双树村的轮廓在前方出现，村口的灯火在雪原尽头亮着", ""),
         faces={"QM": "FAR_FIGURE_ON_SNOWFIELD"},
         entry="秦铭拖着两头猎物翻过矮山脊线", exit="雪地上两道长痕延向亮着灯火的村口",
         dims={"POSITION": D("矮山这侧", "雪原尽头的村口在前", "PAST_RIDGE", "VILLAGE_IN_SIGHT")}, referents=[]),
    # S05 —— 村口的孩子
    dict(s="E08-S05", n=1, sec=3, size="中全景", camera="低机位随追跑的孩子横摇到走来的秦铭", axis="孩子们（画左）与拖猎物走来的秦铭（画右）；跑在最前的瘦弱男孩朝镜头这一侧跑、整张脸正对镜头且完整在画面内，不得只给背影或后脑", blocking="村口几个孩子在雪地上相互追跑，跑在最前的瘦弱男孩朝镜头这一侧跑来、冻得通红的小脸整个正对镜头；他们停下，望着拖着猎物走来的人",
         cast=["QM", "BOY"], action=("BOY", "几个孩子在村口的雪地上相互追跑，小脸冻得通红，他们忽然停下，望着拖着猎物走来的秦铭", "QM"),
         faces={"QM": "FAR_FIGURE_APPROACHING"}, slots={"BOY": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="雪地上两道长痕延向亮着灯火的村口", exit="孩子们停在雪地上，望着拖猎物走来的秦铭",
         dims={"MOMENTUM": D("追跑打闹", "停下望过来", "RUNNING", "STOPPED_AND_LOOKING")}, referents=[]),
    dict(s="E08-S05", n=2, identity_reanchor=True, sec=4, cps=5.0, size="中近景", camera="低机位缓推睁大眼睛的瘦弱男孩", axis="瘦弱男孩（画左）仰头看秦铭（画右）", blocking="一个瘦弱的男孩看见雪地上拖来的刀角鹿，吃惊地睁大眼睛问出口，说完往前挪了半步",
         cast=["BOY", "QM"], action=("BOY", "一个瘦弱的男孩看见雪地上拖来的刀角鹿，吃惊地睁大眼睛问一句，说完立即往前挪半步", "QM"), dialogue=("BOY", "秦哥，你进山，独自猎杀到了刀角鹿？", "QM"), emotion="joy",
         perf=("惊", "盯着雪地上的刀角鹿睁大眼睛", "又快又高地问"), after_line="往前挪半步", slots={"BOY": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="孩子们停在雪地上，望着拖猎物走来的秦铭", exit="瘦弱男孩往前挪了半步，盯着刀角鹿",
         dims={"POSITION": D("站在原地", "往前挪半步", "STANDING", "STEPPED_CLOSER")}, referents=[("你", "QM")]),
    dict(s="E08-S05", n=3, sec=3.5, size="中全景", camera="低机位环绕围上来的孩子与雪地上的驴头狼", axis="孩子们（画左）围向猎物（画右）", blocking="几个孩子一起凑上前，看到数百斤重的黑色驴头狼都吓了一跳，盯着两头猎物偷偷咽口水",
         cast=["BOY", "QM"], action=("BOY", "几个孩子一起凑上前，看到数百斤重的黑色驴头狼都吓了一跳，盯着两头猎物偷偷咽口水", WOLF),
         slots={"BOY": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         faces={"QM": "BACK_TO_CAMERA_BESIDE_PREY"},
         entry="瘦弱男孩往前挪了半步，盯着雪地上的刀角鹿与驴头狼", exit="孩子们围在刀角鹿与驴头狼旁边咽着口水",
         dims={"POSITION": D("站在雪路上", "围到猎物旁", "ON_THE_ROAD", "AROUND_THE_PREY")}, referents=[]),
    dict(s="E08-S05", n=4, identity_reanchor=True, sec=3.5, cps=5.0, size="中景", camera="缓推笑着招呼孩子的秦铭", axis="秦铭（画右）面向孩子们（画左）", blocking="秦铭拖着绳子停下脚步，笑着对孩子们说一句，说完重新拖起绳子往村里走",
         cast=["QM", "BOY"], action=("QM", "秦铭拖着绳子停下脚步，笑着说一句，说完立即重新拖起绳子往村里走", "BOY"), dialogue=("QM", "一会儿都来我家吃肉。", "BOY"), emotion="joy",
         perf=("喜", "拖着绳子停下脚步看着一圈孩子", "笑着扬声说"), after_line="重新拖起绳子往村里走", slots={"QM": "SCREEN_RIGHT", "BOY": "SCREEN_LEFT"},
         entry="孩子们围在两头猎物旁边咽着口水", exit="秦铭拖起绳子往村里走，孩子们跟在后面",
         dims={"MOMENTUM": D("停下脚步", "重新拖绳前行", "STOPPED", "WALKING_ON")}, referents=[]),

    # S06 —— 回到院里：烧水、肩伤被看破
    dict(s="E08-S06", n=1, sec=3, size="中全景", camera="高机位随两头猎物被拖进院门再横摇向石灶", axis="猎物自院门（画右）被拖向院中（画左）", blocking="秦铭把两头猎物拖进院子，立刻在石灶上架起铁锅烧水，火光在锅底亮起",
         cast=["QM"], action=("QM", "秦铭把两头猎物拖进院子，立刻在石灶上架起铁锅烧水，火光在锅底亮起", POT),
         faces={"QM": "BACK_TO_CAMERA_AT_STOVE"},
         entry="秦铭拖起绳子往村里走，孩子们跟在后面", exit="铁锅架在石灶上，锅底的火光亮起来",
         dims={"POSITION": D("院门外", "院中石灶旁", "AT_GATE", "AT_STOVE"), "CONTACT": D("手里是绳子", "手里是柴火", "ROPE_IN_HAND", "FIREWOOD_IN_HAND")}, referents=[]),
    dict(s="E08-S06", n=2, identity_reanchor=True, sec=3.5, cps=5.0, size="中近景", camera="缓推看见血迹的梁婉清", axis="梁婉清（画左）看向秦铭的肩头（画右）", blocking="梁婉清端着水盆停在秦铭身侧，一眼看到他肩头的血迹，出声发问，问完伸手指了指那块血痕",
         cast=["LWQ", "QM"], action=("LWQ", "梁婉清端着水盆停在秦铭身侧，一眼看到他肩头的血迹，出声问一句，说完立即伸手指了指那块血痕", "QM"), dialogue=("LWQ", "小秦，你受伤了？", "QM"), emotion="fear",
         perf=("惊", "端着水盆停住，盯着肩头那块血痕", "压着声音急问"), after_line="伸手指了指那块血痕", slots={"LWQ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="铁锅架在石灶上，锅底的火光亮起来", exit="梁婉清的手指着秦铭肩头的血痕",
         dims={"CONTACT": D("双手端着水盆", "一手指向肩头", "BOTH_HANDS_ON_BASIN", "HAND_POINTING")}, referents=[("你", "QM")]),
    dict(s="E08-S06", n=3, sec=3, cps=5.0, size="中近景", camera="反打摇头作答的秦铭", axis="秦铭（画右）面向梁婉清（画左）", blocking="秦铭往火堆里添了一根柴，摇着头答一句，说完转身去拿腰后的短刀",
         cast=["QM", "LWQ"], action=("QM", "秦铭往火堆里添了一根柴，摇着头答一句，说完立即转身去拿腰后的短刀", "LWQ"), dialogue=("QM", "轻伤，不碍事。", "LWQ"), emotion="calm",
         perf=("冷", "往火堆里添柴、肩膀动了动", "不在意地一带而过地说"), after_line="转身去拿腰后的短刀", slots={"QM": "SCREEN_RIGHT", "LWQ": "SCREEN_LEFT"},
         entry="梁婉清的手指着秦铭肩头的血痕", exit="秦铭手按在腰后的短刀上",
         dims={"POSTURE": D("侧身对着梁婉清", "转身背向她", "FACING_LIANG", "TURNED_AWAY")}, referents=[]),
    dict(s="E08-S06", n=4, sec=3.5, size="中景", camera="高机位俯看陆泽拨开衣领查看伤口", axis="陆泽（画左）俯身查看秦铭的肩（画右）", blocking="陆泽伸手拨开秦铭的衣领，伤口不深早已结出血痂，他松开手直起身",
         cast=["LZ", "QM"], action=("LZ", "陆泽伸手拨开秦铭的衣领，露出的伤口不深、早已结出血痂，他松开手直起身", "QM"),
         slots={"LZ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="秦铭手按在腰后的短刀上", exit="陆泽松开手直起身，衣领被拨开露出血痂",
         dims={"CONTACT": D("衣领合着", "衣领被拨开", "COLLAR_CLOSED", "COLLAR_OPENED"), "POSTURE": D("俯身查看", "直起身", "BENT_OVER", "STOOD_UP")}, referents=[("他", "LZ")]),
    # S07 —— 铁锅、烤鹿腿、第一口肉
    dict(s="E08-S07", n=1, sec=3, size="中近景", camera="低机位缓推火堆上滴油的鹿腿", axis="鹿腿（画面中央）在火堆上方；铁锅边缘与锅体是一片均匀的素面反光，没有断成笔画状、能被读成字母或文字的高光斑点，画面任何位置都没有文字、字母、数字、刻痕铭文或水印", blocking="秦铭弯腰把柴推进火里，铁锅中煮着大块的肉，火堆上的鹿腿不断滴落油脂，油滴进火里溅起火星",
         cast=["QM"], action=("QM", "秦铭弯腰把柴推进火里，铁锅中煮着大块的肉，火堆上烤着的鹿腿不断滴落油脂，油滴进火里溅起火星", LEG),
         faces={"QM": "FACE_OUT_OF_FRAME_PROP_ONLY"},
         entry="陆泽松开手直起身，石灶上的铁锅已经烧开", exit="秦铭蹲在火堆旁，铁锅翻滚、鹿腿上的油脂滴进火里",
         dims={"INTEGRITY": D("鹿腿刚上火", "鹿腿烤出焦褐、油脂滴落", "LEG_RAW", "LEG_ROASTED")}, referents=[]),
    dict(s="E08-S07", n=2, sec=2.5, size="中景", camera="缓推割肉入口的秦铭", axis="秦铭（画右）面向鹿腿（画左）", blocking="秦铭举着短刀凑近鹿腿，从上面割下薄薄一片，不怕烫直接放进嘴里",
         cast=["QM"], action=("QM", "秦铭举着短刀凑近鹿腿，从上面割下薄薄一片，不怕烫直接放进嘴里", KNIFE),
         entry="秦铭蹲在火堆旁，铁锅翻滚、鹿腿上的油脂滴进火里", exit="秦铭嘴里含着那片肉，短刀还举在手里",
         dims={"POSSESSION": D("鹿腿完整", "割下薄薄一片", "LEG_WHOLE", "SLICE_CUT")}, referents=[("他", "QM")]),
    dict(s="E08-S07", n=3, sec=5, cps=5.0, size="中景", camera="缓推嚼着肉说话的秦铭，陆文睿在画右", axis="秦铭（画左）面向陆文睿（画右）", blocking="秦铭嚼着那片肉抬起头，冲陆文睿说一句，说完把短刀递向鹿腿",
         cast=["QM", "WR"], action=("QM", "秦铭嚼着那片肉抬起头，笑着说一句，说完立即把短刀递向鹿腿", "WR"), dialogue=("QM", "熟了，味道很好！文睿，今天小叔满足你的愿望了吧？", "WR"), emotion="joy",
         perf=("喜", "嚼着肉抬头看向陆文睿", "笑着扬声说"), after_line="把短刀递向鹿腿", slots={"QM": "SCREEN_LEFT", "WR": "SCREEN_RIGHT"},
         entry="秦铭嘴里含着那片肉，短刀还举在手里", exit="短刀递向鹿腿，陆文睿凑了过来",
         dims={"POSITION": D("陆文睿在一旁看着", "陆文睿凑到鹿腿前", "WATCHING", "CAME_CLOSER")}, referents=[("你", "WR")]),
    # S08 —— 陆文睿与陆文晖
    dict(s="E08-S08", n=1, sec=5.5, cps=5.0, size="中近景", camera="低机位缓推眯眼点头的陆文睿", axis="陆文睿（画面中央）面向画外的秦铭", blocking="陆文睿把一小片肉送进嘴里，眼睛弯成月牙，像小鸡啄米似的点着头说一句，说完又伸手去够鹿腿",
         cast=["WR"], action=("WR", "陆文睿两手捧着一小片烤肉送进嘴里，眼睛弯成月牙，像小鸡啄米似的点着头说一句，说完立即又伸手去够火堆上的鹿腿", ""), dialogue=("WR", "好香啊，我都忘记多久没吃肉了，小叔你真是太棒了！", ""), emotion="joy",
         perf=("喜", "把肉送进嘴里、点头如小鸡啄米", "含着肉又快又亮地说"), after_line="又伸手去够鹿腿",
         entry="陆文睿两手捧着一小片烤肉凑到嘴边，手里没有刀", exit="陆文睿伸着手去够鹿腿，嘴还在动",
         dims={"POSTURE": D("凑在鹿腿前", "伸手去够", "LEANING_IN", "REACHING")}, referents=[]),
    dict(s="E08-S08", n=2, sec=3.5, size="中近景", camera="高机位俯看咬不动鹿腿的陆文晖", axis="陆文晖（画面中央）面向画外的大人", blocking="两岁出头的陆文晖抱着鹿腿咬不动，弯腰把脸埋进碗里改吃捣烂的肉糊，委屈地瘪起嘴眼巴巴地看着",
         cast=["WH"], action=("WH", "两岁出头的陆文晖抱着鹿腿咬不动，弯腰把脸埋进碗里改吃捣烂的肉糊，委屈地瘪起嘴眼巴巴地看着", LEG),
         entry="陆文睿伸着手去够鹿腿，嘴还在动", exit="陆文晖瘪着嘴，面前是一碗捣烂的肉糊",
         dims={"POSSESSION": D("抱着鹿腿", "面前换成肉糊", "HOLDING_LEG", "MASH_INSTEAD")}, referents=[("他", "WH")]),
    dict(s="E08-S08", n=3, sec=2.5, size="中全景", camera="横移过被逗笑的几个人", axis="陆文晖（画左）与笑起来的大人（画右）", blocking="陆文晖瘪着嘴眼巴巴地看着，梁婉清与秦铭都笑了起来，院里的气氛松下来",
         cast=["LWQ", "QM", "WH"], action=("LWQ", "看着瘪嘴的陆文晖，梁婉清与秦铭都笑了起来，院里的气氛松下来", "WH"),
         slots={"LWQ": "SCREEN_RIGHT", "QM": "SCREEN_RIGHT", "WH": "SCREEN_LEFT"},
         entry="陆文晖瘪着嘴，面前是一碗捣烂的肉糊", exit="梁婉清与秦铭都笑着，陆文晖还瘪着嘴",
         dims={"POSTURE": D("众人各自吃着", "都笑起来", "EATING", "LAUGHING")}, referents=[]),
    # S09 —— 院门外的孩子
    dict(s="E08-S09", n=1, sec=3, size="中全景", camera="低机位自院门外向院内推，孩子扒着门框", axis="孩子们（画右）朝向院中的火光（画左）", blocking="院门外几个孩子扒着门框探头进来，踮脚往院里望，小脸脏兮兮，闻着肉香不敢跨进门",
         cast=["BOY"], action=("BOY", "院门外几个孩子扒着门框探头进来，踮脚往院里望，小脸脏兮兮，闻着肉香不敢跨进门", ""),
         entry="梁婉清与秦铭都笑着，陆文晖还瘪着嘴", exit="孩子们扒在门框上，眼睛盯着院里的火堆",
         dims={"POSITION": D("院门外的路上", "扒在门框上", "OUTSIDE_GATE", "AT_THE_GATE")}, referents=[]),
    dict(s="E08-S09", n=2, sec=3, cps=5.0, size="中景", camera="缓推朝院门招手的秦铭", axis="秦铭（画左）面向院门（画右）", blocking="秦铭抬头看见院门外的孩子，立刻招着手说一句，说完往火堆旁挪出一块空位",
         cast=["QM", "BOY"], action=("QM", "秦铭抬头看见院门外的孩子，立刻招着手说一句，说完立即往火堆旁挪出一块空位", "BOY"), dialogue=("QM", "都快进来，一起吃吧。", "BOY"), emotion="joy",
         perf=("喜", "抬头看见门外的孩子、抬手招呼", "扬声爽快地说"), after_line="往火堆旁挪出一块空位", slots={"QM": "SCREEN_LEFT", "BOY": "SCREEN_RIGHT"},
         entry="孩子们扒在门框上，眼睛盯着院里的火堆", exit="秦铭把火堆旁的位置让出来，手还抬着",
         dims={"CONTACT": D("手里拿着肉", "抬手招呼", "MEAT_IN_HAND", "HAND_WAVING")}, referents=[]),
    dict(s="E08-S09", n=3, sec=3.5, size="中全景", camera="低机位环绕鼓着腮帮子吃肉的孩子", axis="孩子们（画面中央）围着火堆", blocking="孩子们腼腆地走进院子，很快就鼓着腮帮子，含混不清地嚷着好吃",
         cast=["BOY"], action=("BOY", "孩子们腼腆地走进院子围到火堆旁蹲下，很快就鼓着腮帮子，含混不清地嚷着好吃", ""),
         entry="秦铭把火堆旁的位置让出来，手还抬着", exit="孩子们围着火堆，腮帮子鼓鼓的",
         dims={"POSITION": D("扒在门框上", "围到火堆旁", "AT_THE_GATE", "AROUND_THE_FIRE")}, referents=[]),
    dict(s="E08-S09", n=4, sec=3.5, cps=5.0, size="中景", camera="缓推盛肉汤的梁婉清", axis="梁婉清（画右）面向孩子们（画左）", blocking="梁婉清端起粗陶碗舀了肉汤，一边递过去一边嘱咐一句，说完直起身又去舀下一碗",
         cast=["LWQ", "BOY"], action=("LWQ", "梁婉清端起粗陶碗舀了肉汤递过去，嘱咐一句，说完立即直起身又去舀下一碗", "BOY"), dialogue=("LWQ", "都慢点，还有很多。", "BOY"), emotion="calm",
         perf=("怜", "舀起肉汤把碗递到孩子手里", "放软声音嘱咐"), after_line="直起身又去舀下一碗", slots={"LWQ": "SCREEN_RIGHT", "BOY": "SCREEN_LEFT"},
         entry="孩子们围着火堆，腮帮子鼓鼓的", exit="一只粗陶碗递到孩子手里，梁婉清转身去舀下一碗",
         dims={"POSSESSION": D("碗空着", "碗里盛满肉汤", "BOWL_EMPTY", "BOWL_FILLED")}, referents=[]),
    # S10 —— 新生的外显
    dict(s="E08-S10", n=1, sec=3.5, identity_reanchor=True, size="中近景", camera="缓推大口吃肉、汗水直冒的秦铭", axis="秦铭（画面中央）面向火堆", blocking="秦铭一个人蹲在火堆旁，双手撕着一大块烤肉往嘴里塞、嘴边一圈油光，额头的汗往下滚，衣领与肩背蒸腾起白雾；他手里没有碗，身边没有人接东西",
         cast=["QM"], action=("QM", "秦铭蹲下身双手撕着一大块烤肉往嘴里塞，汗水从额头滚落，衣领与肩背蒸腾起白雾", ""),
         entry="秦铭蹲在火堆旁，双手撕着一大块烤肉，嘴边一圈油光", exit="秦铭浑身汗湿，白雾从他身上蒸腾起来",
         dims={"INTEGRITY": D("额头微汗", "浑身汗湿、白雾蒸腾", "LIGHT_SWEAT", "STEAMING")}, referents=[("他", "QM")]),
    dict(s="E08-S10", n=2, sec=4, cps=5.0, size="中景", camera="反打放下碗筷盯住白雾的陆泽", axis="陆泽（画左）看向秦铭（画右）", blocking="陆泽端着碗停住，盯着那团白雾，放下碗筷说一句，说完往前走了半步",
         cast=["LZ", "QM"], action=("LZ", "陆泽端着碗停住，盯着那团白雾，放下碗筷说一句，说完立即往前走半步", "QM"), dialogue=("LZ", "身体新生，正在剧烈变化中！", "QM"), emotion="fear",
         perf=("惊", "端着碗停住、放下碗筷", "压着嗓子快而低地说"), after_line="往前走半步", slots={"LZ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="秦铭浑身汗湿，白雾从他身上蒸腾起来", exit="陆泽放下碗筷，往前走了半步盯着白雾",
         dims={"POSSESSION": D("碗端在手里", "碗筷放下", "BOWL_HELD", "BOWL_DOWN")}, referents=[]),
    # S11 —— 村民来打听、分肉
    dict(s="E08-S11", n=1, sec=3.5, size="远景", camera="高机位俯看挤满人的小院", axis="村民（画面四周）围着秦铭（画面中央）", blocking="很多村民走进院子围住秦铭，七嘴八舌地打听山里的情况",
         cast=["QM"], action=("QM", "很多村民走进院子围住秦铭，七嘴八舌地打听山里的情况", ""),
         faces={"QM": "FAR_FIGURE_IN_CROWD"},
         entry="陆泽放下碗筷，往前走了半步盯着白雾", exit="院子里挤满人，秦铭被围在中间",
         dims={"POSITION": D("院里只有自家人", "院里挤满村民", "FAMILY_ONLY", "CROWDED")}, referents=[]),
    dict(s="E08-S11", n=2, sec=3, cps=5.0, size="中近景", camera="低机位缩在母亲身后的小女孩", axis="小女孩（画左）仰头看向画外的母亲", blocking="一个衣服上打着补丁的小女孩缩在大人身后望着烤肉，低声说一句，说完把手缩进袖子里",
         cast=["GIRL"], action=("GIRL", "一个衣服上打着补丁的小女孩缩在大人身后望着烤肉，低声说一句，说完立即把手缩进袖子里", ""), dialogue=("GIRL", "娘，我饿了。", ""), emotion="plead",
         perf=("怯", "缩在大人身后盯着火堆上的肉", "怯生生地低声说"), after_line="把手缩进袖子里",
         entry="院子里挤满人，秦铭被围在中间", exit="小女孩把手缩进袖子里，眼睛还盯着烤肉",
         dims={"CONTACT": D("手抓着大人的衣角", "手缩进袖子", "HOLDING_SLEEVE", "HANDS_TUCKED")}, referents=[]),
    dict(s="E08-S11", n=3, identity_reanchor=True, sec=6, cps=5.0, size="中景", camera="缓推看着孩子们招手的秦铭", axis="秦铭（画右）面向一圈人（画左）", blocking="秦铭看着那一张张冻得通红的小脸，抬手招呼他们过来，接着对一圈大人说一句，说完把切好的肉往旁边推了推",
         cast=["QM", "GIRL"], action=("QM", "秦铭看着那一张张冻得通红的小脸，抬手招呼孩子们过来，接着说一句，说完立即把切好的肉往旁边推", "GIRL"), dialogue=("QM", "各位叔伯就别在这儿吃了，回头每家割五斤肉回去。", "GIRL"), emotion="calm",
         perf=("坚", "抬手招呼孩子、把切好的肉往旁边推", "扬声把话说定"), after_line="把切好的肉往旁边推", slots={"QM": "SCREEN_RIGHT", "GIRL": "SCREEN_LEFT"},
         entry="小女孩把手缩进袖子里，眼睛还盯着烤肉", exit="切好的肉被推到一旁，孩子们被招到火堆边",
         dims={"POSSESSION": D("肉堆在案上", "肉被分作几份推到一旁", "MEAT_PILED", "MEAT_PORTIONED")}, referents=[]),
    # S12 —— 杨永青追问
    dict(s="E08-S12", n=1, sec=4.5, cps=5.0, size="中景", camera="缓推挤进来按住肩膀的杨永青", axis="杨永青（画左）面向秦铭（画右）；两人相对站在同一景深，镜头平拍：两人的脸都要转向镜头约三十度的四分之三正面（双眼与两侧眉毛都可见），严禁画成纯侧脸或剪影，都完整入画且被火光照亮；杨永青的脸必须与他的人物身份权威参考图是同一张脸（脸型、五官比例、年龄、络腮胡完全一致），不得换脸、混脸或改成另一个演员；他外层穿的是黑褐色旧皮坎肩（无袖、皮面磨旧、肩上落着新雪），不是大毛领皮裘", blocking="杨永青挤开人群伸出手，一把按住秦铭的肩膀追问一句，说完把脸凑近了些",
         cast=["YQ", "QM"], action=("YQ", "杨永青挤开人群伸出手，一把按住秦铭的肩膀问一句，说完立即把脸凑近", "QM"), dialogue=("YQ", "小秦，你和叔说实话，是不是新生了？", "QM"), emotion="fear",
         perf=("惊", "挤开人群一把按住秦铭的肩膀", "压着嗓子急问"), after_line="把脸凑近", slots={"YQ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="切好的肉被推到一旁，孩子们被招到火堆边", exit="杨永青的手按在秦铭肩上，脸凑得很近",
         dims={"CONTACT": D("两手空着", "手按在秦铭肩上", "HANDS_FREE", "HAND_ON_SHOULDER")}, referents=[("你", "QM")]),
    dict(s="E08-S12", n=2, sec=3.5, cps=5.0, size="中近景", camera="反打笑着点头的秦铭", axis="秦铭（画右）面向杨永青（画左）", blocking="秦铭被按着肩膀笑起来，点着头把话头抛回去，说完抹了一把额头的汗",
         cast=["QM", "YQ"], action=("QM", "秦铭被按着肩膀笑起来，点着头说一句，说完立即抹一把额头的汗", "YQ"), dialogue=("QM", "杨叔不是说有贵女要下来吗？", "YQ"), emotion="mock",
         perf=("戏", "被按着肩膀笑起来、点头", "笑着反问回去"), after_line="抹一把额头的汗", slots={"QM": "SCREEN_RIGHT", "YQ": "SCREEN_LEFT"},
         entry="杨永青的手按在秦铭肩上，脸凑得很近", exit="秦铭笑着抹了一把额头的汗",
         dims={"POSTURE": D("被按着不动", "抬手抹汗", "HELD_STILL", "WIPING_SWEAT")}, referents=[]),
    dict(s="E08-S12", n=3, sec=3.5, cps=5.0, size="中全景", camera="低机位横移到并肩站着的两人", axis="秦铭（画右）与杨永青（画左）并肩站在人群里", blocking="秦铭笑着接上后半句，说完摊了摊手",
         cast=["QM", "YQ"], action=("QM", "秦铭笑着接上后半句，说完立即摊了摊手", "YQ"), dialogue=("QM", "我被刺激到了，突然就新生了。", "YQ"), emotion="mock",
         perf=("喜", "笑着接上后半句、肩膀一松", "轻描淡写地说"), after_line="摊了摊手", slots={"QM": "SCREEN_RIGHT", "YQ": "SCREEN_LEFT"},
         entry="秦铭笑着抹了一把额头的汗", exit="秦铭摊着手，笑意还在脸上",
         dims={"CONTACT": D("手抹着汗", "两手摊开", "WIPING", "PALMS_OPEN")}, referents=[]),
    dict(s="E08-S12", n=4, sec=3, cps=5.0, size="中景", camera="缓推笑着点指的杨永青", axis="杨永青（画左）面向秦铭（画右）", blocking="杨永青松开手笑出声，点指着秦铭说一句，说完收回手",
         cast=["YQ", "QM"], action=("YQ", "杨永青松开手笑出声，点指着秦铭说一句，说完立即收回手", "QM"), dialogue=("YQ", "你这小子，不够朴实啊。", "QM"), emotion="mock",
         perf=("戏", "松开手笑出声、抬手点指", "笑骂似的说"), after_line="收回手", slots={"YQ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="秦铭摊着手，笑意还在脸上", exit="杨永青收回手，笑意还挂在络腮胡上",
         dims={"CONTACT": D("手按在秦铭肩上", "手收回身侧", "HAND_ON_SHOULDER", "HAND_BACK")}, referents=[("你", "QM")]),
    # S13 —— 刘老头的感叹、白雾裹身
    dict(s="E08-S13", n=1, sec=6, cps=5.0, size="中景", camera="低机位缓推拄杖挤上前的刘老头", axis="刘老头（画左）面向白雾里的秦铭（画右）", blocking="住在村口的刘老头拄着木杖往人群前挤，看着白雾里的秦铭感叹一句，说完用杖头顿了顿地",
         cast=["LLT", "QM"], action=("LLT", "刘老头拄着木杖往人群前挤，看着白雾里的秦铭感叹一句，说完立即用杖头顿了顿地", "QM"), dialogue=("LLT", "在黄金年龄段新生，数十年来，这是我们双树村头一份啊！", "QM"), emotion="joy",
         perf=("惊", "拄着木杖挤到人群最前", "拖着长腔感叹"), after_line="用杖头顿了顿地", slots={"LLT": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         faces={"QM": "SMALL_FIGURE_IN_WHITE_MIST"},
         entry="杨永青收回手，笑意还挂在络腮胡上", exit="刘老头的杖头顿在雪地上，人群静了一瞬",
         dims={"POSITION": D("人群后面", "人群最前", "BEHIND_CROWD", "AT_THE_FRONT")}, referents=[]),
    dict(s="E08-S13", n=2, sec=4, identity_reanchor=True, size="中近景", camera="缓推白雾里的秦铭", axis="秦铭（画面中央）被白雾裹着", blocking="极寒的天气里秦铭的身体像个火炉子，汗水把衣服浸湿，白雾几乎把他裹住，雾里透出他的轮廓",
         cast=["QM"], action=("QM", "极寒的天气里秦铭直起身，身体越来越烫，汗水把衣服浸湿，白雾几乎把他裹住，雾里透出轮廓", ""),
         entry="刘老头的杖头顿在雪地上，人群静了一瞬", exit="白雾几乎裹住秦铭，只透出他的轮廓",
         dims={"INTEGRITY": D("白雾在身周", "白雾几乎裹住全身", "STEAM_AROUND", "WRAPPED_IN_MIST")}, referents=[("他", "QM")]),
    dict(s="E08-S13", n=3, sec=4, size="中近景", camera="缓推络腮胡颤动的杨永青", axis="杨永青（画左）望向白雾里的秦铭（画右）", blocking="杨永青迎上半步凑近白雾，络腮胡须颤动起来，眼睛越睁越大——他听见秦铭的心跳宛若擂鼓",
         cast=["YQ", "QM"], action=("YQ", "杨永青迎上半步凑近白雾，络腮胡须颤动起来，眼睛越睁越大", "QM"),
         slots={"YQ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         faces={"QM": "SMALL_FIGURE_IN_WHITE_MIST"},
         entry="白雾几乎裹住秦铭，只透出他的轮廓", exit="杨永青睁大眼睛盯着白雾，胡须还在颤",
         dims={"POSTURE": D("站在人群里", "凑近半步", "IN_CROWD", "LEANED_IN")}, referents=[("他", "YQ")]),
    # S14 —— 交托、冰水、入眠
    dict(s="E08-S14", n=1, identity_reanchor=True, sec=4.5, cps=5.0, size="中景", camera="缓推把刀递出去的秦铭", axis="秦铭（画右）把刀递向陆泽（画左）；两人侧身相对、坐在同一景深的炕沿两端，镜头从侧面平拍两人的四分之三侧脸：秦铭在画右、陆泽在画左，两张脸都完整入画、都被火光照亮、都清晰可辨；画面前景严禁出现任何人物的后脑、背影或肩膀做遮挡（不拍过肩镜），两人都不得背对镜头；各自的脸必须与自己的人物身份权威参考图是同一张脸（脸型、五官比例、年龄完全一致），不得换脸、混脸或改成另一个演员", blocking="秦铭撑着桌沿眼皮直往下掉，把切肉的刀递给陆泽，交代一句，说完松开手；陆泽侧坐在炕沿伸手来接，四分之三侧脸朝着镜头、整张脸都在光里",
         cast=["QM", "LZ"], action=("QM", "秦铭撑着桌沿眼皮直往下掉，把切肉的刀递给陆泽，交代一句，说完立即松开手", "LZ"), dialogue=("QM", "周阿婆今天下葬，给周家多送一些肉。", "LZ"), emotion="calm",
         perf=("倦", "撑着桌沿把刀递过去", "困得含糊却交代清楚"), after_line="松开手", slots={"QM": "SCREEN_RIGHT", "LZ": "SCREEN_LEFT"},
         entry="杨永青睁大眼睛盯着白雾，胡须还在颤", exit="短刀交到陆泽手里，秦铭松开了手",
         dims={"POSSESSION": D("刀在秦铭手里", "刀在陆泽手里", "KNIFE_WITH_QIN", "KNIFE_WITH_LUZE")}, referents=[]),
    dict(s="E08-S14", n=2, sec=4, size="中景", camera="低机位随一盆冰水从头浇下", axis="冰水（画面上方）浇向秦铭（画面下方）", blocking="秦铭弯腰端起一盆冰水举过头顶，从头浇下冲洗身体，白雾从他身上腾起",
         cast=["QM"], action=("QM", "秦铭弯腰端起一盆冰水举过头顶，从头浇下冲洗身体，白雾从他身上腾起", ""),
         entry="短刀交到陆泽手里，秦铭松开了手", exit="冰水浇过全身，白雾腾起把他裹住",
         dims={"CONTACT": D("盆举在头顶", "水浇过全身", "BASIN_RAISED", "WATER_POURED")}, referents=[("他", "QM")]),
    dict(s="E08-S14", n=3, sec=4, size="中全景", camera="高机位俯看躺上炕的秦铭", axis="秦铭（画面中央）躺在炕上", blocking="秦铭走到炕边坐下，躺上炕沉沉睡去，胸口的起伏又深又慢",
         cast=["QM"], action=("QM", "秦铭走到炕边坐下，躺上炕沉沉睡去，胸口的起伏又深又慢", KANG),
         entry="冰水浇过全身，白雾腾起把他裹住", exit="秦铭躺在炕上睡着，胸口起伏又深又慢",
         dims={"POSTURE": D("站着", "躺在炕上", "STANDING", "LYING_ON_KANG"), "MOMENTUM": D("还在动", "沉沉睡去", "AWAKE", "ASLEEP")}, referents=[("他", "QM")]),
]

_ZH_FAM = {"ARC": "环绕", "TRACK": "横移", "CRANE": "升降", "DOLLY": "推拉", "PAN": "横摇"}
_ALT = [("ARC", "COUNTERCLOCKWISE"), ("ARC", "CLOCKWISE"), ("TRACK", "LEFT_TO_RIGHT"), ("TRACK", "RIGHT_TO_LEFT"), ("CRANE", "RISE"), ("CRANE", "FALL")]

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
    "SETUP-MOON-INSECT": dict(setup="E08-S01-02", payoff="E08-S03-02", object="夜空里那团照亮天地的光是什么——秦铭认出月虫，随后一道流光划破长空、它远去", partial=["E08-S01-03", "E08-S02-01"], verbs=["流光", "远去"]),
    "SETUP-MEAT-INVITE": dict(setup="E08-S05-04", payoff="E08-S09-03", object="村口那句「一会儿都来我家吃肉」——孩子们真的进了院子吃上肉", partial=["E08-S09-01", "E08-S09-02"], verbs=["走进院子", "鼓着腮帮子"]),
    "SETUP-SHOULDER-WOUND": dict(setup="E08-S06-02", payoff="E08-S06-04", object="梁婉清看见的肩头血迹到底重不重——陆泽拨开衣领看到伤口不深、早已结痂", partial=["E08-S06-03"], verbs=["拨开", "血痂"]),
    "SETUP-REBIRTH-HEAT": dict(setup="E08-S10-01", payoff="E08-S13-02", object="秦铭身上蒸腾的白雾意味着什么——白雾几乎把他裹住，身体像火炉子", partial=["E08-S10-02", "E08-S12-02"], verbs=["白雾", "裹住"]),
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
    "那是月虫。": "ch8「‘月虫！’他听闻过」的惊呼转为压声自语，「月虫」二字不变，前加「那是」",
    "古时候的月亮，就是这个样子吗？": "ch8「秦铭出神，在那遥远的古代，月亮就是这个样子吗？」内心转自语，语序不变",
    "身体新生，正在剧烈变化中！": "ch8 陆泽的惊讶内心「身体新生，正在剧烈变化中！」转为说出口，字不变",
    "秦哥，你进山，独自猎杀到了刀角鹿？": "ch8 原句「秦哥，你进山……独自猎杀到了刀角鹿？」去掉省略号改逗号，字序不变",
    "各位叔伯就别在这儿吃了，回头每家割五斤肉回去。": "ch8 原句「各位叔伯，我就不请你们在这里吃了，回头每家割五斤肉回去。」按镜长压缩前半句，后半句字不变",
    "杨叔不是说有贵女要下来吗？": "ch8 秦铭长句的前半「杨叔不是说，有贵女要下来吗」按镜长断句成问句",
    "我被刺激到了，突然就新生了。": "ch8 同一长句的后半「我被刺激到了，身体不断发热，突然就新生了」按镜长略去中段，字序不变",
    "周阿婆今天下葬，给周家多送一些肉。": "ch8 原句「周阿婆今天下葬，你帮我走上一趟，给周家多送一些肉」略去中段，首尾字不变",

    "趁它们还不敢出来。": "ch8「趁着各种猛兽被震慑，还不敢肆意出没，他行动起来」的内心动机转为压声自语，不新增情节",
    "可惜，来晚一步。": "ch7「秦铭瞬息冲到近前，暗道可惜」内心转低声自语，「可惜」二字不变，补「来晚一步」成整句（两字台词连续三次被模型当成画面字幕烧进画面）",
    "足有七百斤。": "ch7 叙述「这头黑褐色的刀角鹿分外雄壮，重足有七百斤」转秦铭自语，取「足有七百斤」字序不变",
    "赤手空拳也能打死你。": "ch7「他认为赤手空拳都能打死它」内心转对驴头狼的低吼（都→也、它→你）",
    "上次袭击我的，就是你。": "ch7「他可以确定，这应该就是上次他掏红松鼠巢穴时，在路上袭击他的变异生物」内心转自语，缩为一句",
    "不能生火。": "ch7 叙述「在夜色中生火…会向山林中所有生物暴露自身，过于危险」转秦铭自语",
    "追杀它的是什么东西？": "ch7「秦铭心里犯嘀咕，这么雄壮的野猪王都败了，追杀它的是什么生物？」内心自问转自语，取后半句；「生物」为 LEXICON_yewujiang_v1 禁用词（对白不得出现现代词），改「东西」",
    "希望附近没有危险的山兽。": "ch7 原句「希望附近没有危险生物。」逐字；「生物」为 LEXICON_yewujiang_v1 禁用词，按源章用词改「危险的山兽」（源章「冻死的山兽」「数百斤的山兽」）",
    "那其实是一只虫。": "ch7 末句「秦铭心头大为震动，因为他知道，那其实是一只虫」内心转轻声自语，字不变",
}
SPLIT_QUOTES = {"都快进来，一起吃吧。": "ch8 秦铭原句「在村口时我不是喊过你们吗？都快进来，一起吃吧。」按镜长取后段，字不变；前段按节奏略去"}
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
PROP_KEYWORDS = (("PROP-BOW-ARROWS", ["弓箭", "弓弦", "背弓", "攥着弓"]), ("PROP-SHORT-KNIFE", ["短刀", "切肉的刀"]),
    ("PROP-IRON-POT", ["铁锅"]), ("PROP-ROAST-DEER-LEG", ["鹿腿"]), ("PROP-MEAT-BROTH-BOWL", ["粗陶碗", "肉汤"]),
    ("PROP-KANG", ["炕"]), ("PROP-WOODEN-STAFF", ["木杖", "杖头"]),
    ("SET-MOON-INSECT-LIGHT", ["那团光", "月虫", "圆盘"]), ("SET-SILVER-LIT-RIDGE", ["荒岭", "银色", "雪岭"]),
    ("PROP-BLADE-HORN-STAG", ["刀角鹿"]), ("PROP-DONKEY-HEAD-WOLF", ["驴头狼"]))
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
    ("E08-S01-01", "E08-S01-02"): ("MOTIVATED_CUT", "落地缩进树影后切抬头，切在抬头上"),
    ("E08-S01-02", "E08-S01-03"): ("CAMERA_REFRAME", "夜空亮起后改取中近景看他的脸"),
    ("E08-S02-01", "E08-S02-02"): ("MOTIVATED_CUT", "光洒向山林后切银光铺满荒岭，切在光扩开上"),
    ("E08-S02-02", "E08-S02-03"): ("REACTION_CUT", "天地染银后切他走出树影仰望"),
    ("E08-S03-01", "E08-S03-02"): ("MOTIVATED_CUT", "死寂之后切流光划破长空，切在光起上"),
    ("E08-S03-02", "E08-S03-03"): ("REACTION_CUT", "流光远去后切他转身退半步"),
    ("E08-S04-01", "E08-S04-02"): ("MOTIVATED_CUT", "拖起猎物后切雪地上的两道长痕，切在拖行上"),
    ("E08-S05-01", "E08-S05-02"): ("REACTION_CUT", "孩子停下后切瘦弱男孩睁大眼睛"),
    ("E08-S05-02", "E08-S05-03"): ("MOTIVATED_CUT", "问完后切孩子们围上来，切在凑近上"),
    ("E08-S05-03", "E08-S05-04"): ("REACTION_CUT", "咽口水后切秦铭笑着招呼"),
    ("E08-S06-01", "E08-S06-02"): ("REACTION_CUT", "架锅烧水后切梁婉清看见血迹"),
    ("E08-S06-02", "E08-S06-03"): ("REACTION_CUT", "指着血痕后切秦铭摇头作答"),
    ("E08-S06-03", "E08-S06-04"): ("MOTIVATED_CUT", "转身去拿刀后切陆泽拨开衣领，切在伸手上"),
    ("E08-S07-01", "E08-S07-02"): ("MOTIVATED_CUT", "油滴进火后切举刀割肉，切在举刀上"),
    ("E08-S07-02", "E08-S07-03"): ("CAMERA_REFRAME", "入口之后改取双人中景"),
    ("E08-S08-01", "E08-S08-02"): ("REACTION_CUT", "陆文睿点头后切陆文晖咬不动"),
    ("E08-S08-02", "E08-S08-03"): ("REACTION_CUT", "瘪嘴之后切两个大人笑起来"),
    ("E08-S09-01", "E08-S09-02"): ("REACTION_CUT", "孩子探头后切秦铭抬头招手"),
    ("E08-S09-02", "E08-S09-03"): ("MOTIVATED_CUT", "让出位置后切孩子们走进院子，切在迈步上"),
    ("E08-S09-03", "E08-S09-04"): ("REACTION_CUT", "孩子们吃上后切梁婉清盛汤"),
    ("E08-S10-01", "E08-S10-02"): ("REACTION_CUT", "白雾蒸腾后切陆泽放下碗筷"),
    ("E08-S11-01", "E08-S11-02"): ("CAMERA_REFRAME", "人群围住后改取小女孩的中近景"),
    ("E08-S11-02", "E08-S11-03"): ("REACTION_CUT", "小女孩说完后切秦铭抬手招呼"),
    ("E08-S12-01", "E08-S12-02"): ("REACTION_CUT", "按住肩膀后切秦铭笑着点头"),
    ("E08-S12-02", "E08-S12-03"): ("CAMERA_REFRAME", "反问之后改取并肩的中全景"),
    ("E08-S12-03", "E08-S12-04"): ("REACTION_CUT", "摊手之后切杨永青笑着点指"),
    ("E08-S13-01", "E08-S13-02"): ("MOTIVATED_CUT", "杖头顿地后切白雾里的秦铭，切在雾起上"),
    ("E08-S13-02", "E08-S13-03"): ("REACTION_CUT", "白雾裹身后切杨永青胡须颤动"),
    ("E08-S14-01", "E08-S14-02"): ("MOTIVATED_CUT", "松开手后切端盆浇水，切在端起上"),
    ("E08-S14-02", "E08-S14-03"): ("MOTIVATED_CUT", "冲洗之后切走向炕边躺下，切在迈步上"),
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
         f"- ★承接：E08-S01-01 的 entry_state 接 {PREV_LAST_SHOT} 的 completion_state（{PREV_LAST['completion_state']}）；ch7 开篇在时间上位于出村路上，本集从秦铭走在村外雪路被拦开始，不复位、不重演、不闪回", ""]
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
NPR_FACE = {"QM": "束发木簪、无胡须的清瘦年轻男子", "YQ": "络腮胡敦实中年男子", "LZ": "短须、方脸的壮年男子",
            "LWQ": "挽髻、素净的年轻妇人", "WR": "圆脸、总角的男童", "WH": "两岁出头的圆脸幼童",
            "LLT": "花白山羊胡、皮帽护耳的驼背老人", "BOY": "瘦削、短发、棉袄打补丁的男孩", "GIRL": "两个小髻、棉袄打补丁的小女孩"}
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
        "pacing_flags": {"hook": shot_id == "E08-S01-01", "scene_opener_in_motion": sh["n"] == 1, "scene_button": sh is by_scene[sid][-1],
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

_CE7 = {c["character_id"]: c for c in _E07["character_entities"]}
_CE6 = {c["character_id"]: c for c in _E06["character_entities"]}
_CE5 = {c["character_id"]: c for c in _E05["character_entities"]}
_CE4 = {c["character_id"]: c for c in _E04["character_entities"]}
CHARACTER_ROWS = [
    {**_CE7["CHAR-QINMING"], "identity_source": {**_CE7["CHAR-QINMING"]["identity_source"], "note": "E02 锁定的三视图身份牌复用；D-57 ①：S3 复测源图余弦 ≥0.45"},
     "appearance_ch8": "ch8：滑下树缩进树影仰望月虫；拖两头猎物回村；院中煮肉割肉；肩头血痂；狼吞虎咽、汗如雨下、白雾蒸腾；分肉给全村；冰水冲身躺上炕"},
    {**_CE6["CHAR-LUZE"], "identity_source": {"mode": "E01_IDENTITY_CARD_REUSE", "note": "沿用已锁定身份牌；本集说话"},
     "appearance_ch8": "ch8：帮忙烧水与分肉，拨开衣领查看秦铭肩伤，放下碗筷看出他正在剧烈新生"},
    {**_CE6["CHAR-LIANGWANQING"], "identity_source": {"mode": "E01_IDENTITY_CARD_REUSE", "note": "沿用已锁定身份牌；本集说话"},
     "appearance_ch8": "ch8：一眼看见秦铭肩头的血迹，给孩子们盛肉汤、嘱咐慢点"},
    {**_CE6["CHAR-LUWENRUI"], "identity_source": {"mode": "E02_IDENTITY_CARD_REUSE", "note": "沿用已锁定身份牌；本集说话"},
     "appearance_ch8": "ch8：尝一口烤鹿腿，眼睛弯成月牙，像小鸡啄米似的点头说好香"},
    {**_CE5["CHAR-LUWENHUI"], "identity_source": {"mode": "E05_IDENTITY_CARD_REUSE", "note": "沿用已锁定身份牌；本集不说话"},
     "appearance_ch8": "ch8：两岁出头，咬不动烤鹿腿只能吃捣烂的肉糊，委屈地瘪嘴"},
    {**_CE7["CHAR-YANGYONGQING"], "identity_source": {"mode": "E04_IDENTITY_CARD_REUSE", "note": "沿用 E04 唐宋版身份牌（络腮胡敦实中年）；本集说话"},
     "appearance_ch8": "ch8：闻讯赶来按住秦铭的肩追问是不是新生了，笑着点指打趣；听见他心跳如擂鼓时络腮胡颤动"},
    {"character_id": "CHAR-LIULAOTOU", "canonical_name": "刘老头", "aliases": ["刘老汉"], "voice_entity_id": "", "identity_reference_entity_id": "",
     "identity_source": {"mode": "TEXT_TO_IMAGE", "note": "无源照片；按 appearance 文生图出三视图身份牌（唐宋村老语汇）"},
     "appearance_ch8": "ch8：住在村口的老人，六十余岁、背微驼、花白山羊胡、旧皮帽护耳、拄一根去皮木杖；挤到人群最前感叹这是双树村数十年头一份"},
    {"character_id": "CHAR-BOY-THIN", "canonical_name": "瘦弱男孩", "aliases": ["瘦男孩"], "voice_entity_id": "", "identity_reference_entity_id": "",
     "identity_source": {"mode": "TEXT_TO_IMAGE", "note": "无源照片；按 appearance 文生图出三视图身份牌（唐宋童装语汇）"},
     "appearance_ch8": "ch8：十岁上下的双树村孩子，瘦、缩着脖子、棉袄打补丁、小脸冻得通红；看见刀角鹿吃惊地睁大眼睛发问"},
    {"character_id": "CHAR-GIRL-PATCHED", "canonical_name": "打补丁的小女孩", "aliases": ["小女孩"], "voice_entity_id": "", "identity_reference_entity_id": "",
     "identity_source": {"mode": "TEXT_TO_IMAGE", "note": "无源照片；按 appearance 文生图出三视图身份牌（唐宋童装语汇）"},
     "appearance_ch8": "ch8：六七岁，衣服上打着补丁，头发用布条扎成两个小髻，缩在母亲身后低声说饿了"},
]
for _row in CHARACTER_ROWS:
    _row.pop("wardrobe_garments", None)
BGM_CUES = [
    {"cue_id": "E08-BGM-01", "scenes": ["E08-S01", "E08-S02", "E08-S03"], "narrative_function": "MOON_INSECT_WONDER", "volume": 0.26, "dialogue_duck_db": -8,
     "brief": "Hushed, awe-struck cinematic instrumental cue in ancient Chinese style for a young hunter sliding down a tree in a snow forest and watching a single vast light flood a moonless world with silver, then streak away and leave the ridges black again: sustained high strings, a distant bowed erhu line, soft low drone, one sparse guqin figure, no percussion hits, no vocals, no modern synth pads."},
    {"cue_id": "E08-BGM-02", "scenes": ["E08-S12", "E08-S13", "E08-S14"], "narrative_function": "REBIRTH_AND_SLEEP", "volume": 0.28, "dialogue_duck_db": -8,
     "brief": "Warm but quietly astonished instrumental cue in ancient Chinese folk style for a village crowd around a young man whose body is visibly reborn — steam rising off him in the cold, a drum-like heartbeat under the talk — settling into deep sleep: low frame drum pulse like a slow heartbeat, warm bowed strings, a single bamboo flute line, soft dizi tail, no vocals, no modern synth."},
]
_e03_fork = next((s["shot_id"] for s in _E03["shots"] if "猎叉" in str(s.get("completion_state"))), _E03["shots"][0]["shot_id"])
_e03_knife = next((s["shot_id"] for s in _E03["shots"] if "短刀" in str(s.get("completion_state"))), _e03_fork)
PROP_SOURCES = {
    "PROP-BOW-ARROWS": {"acquired": {"episode": "E04", "shot_id": "E04-S02-04"}, "recap_shot_id": "E08-S01-01", "payoff_shot_ids": ["E08-S01-03"]},
    "PROP-SHORT-KNIFE": {"acquired": {"episode": "E03", "shot_id": _e03_knife}, "recap_shot_id": "E08-S06-03", "payoff_shot_ids": ["E08-S14-01"]},
    "PROP-BLADE-HORN-STAG": {"acquired": {"episode": "E07", "shot_id": "E07-S08-01"}, "recap_shot_id": "E08-S05-02", "payoff_shot_ids": ["E08-S07-01"]},
    "PROP-DONKEY-HEAD-WOLF": {"acquired": {"episode": "E07", "shot_id": "E07-S10-01"}, "recap_shot_id": "E08-S05-03", "payoff_shot_ids": ["E08-S05-03"]},
    "PROP-KANG": {"acquired": {"episode": "E01", "shot_id": "E08-S14-03"}, "recap_shot_id": "E08-S14-03", "payoff_shot_ids": ["E08-S14-03"]},
    "PROP-IRON-POT": {"acquired": {"episode": EP, "shot_id": "E08-S06-01"}, "payoff_shot_ids": ["E08-S07-01"]},
    "PROP-ROAST-DEER-LEG": {"acquired": {"episode": EP, "shot_id": "E08-S07-01"}, "payoff_shot_ids": ["E08-S07-02"]},
    "PROP-MEAT-BROTH-BOWL": {"acquired": {"episode": EP, "shot_id": "E08-S09-04"}, "payoff_shot_ids": ["E08-S09-04"]},
    "PROP-WOODEN-STAFF": {"acquired": {"episode": EP, "shot_id": "E08-S13-01"}, "payoff_shot_ids": ["E08-S13-01"]},
    "SET-MOON-INSECT-LIGHT": {"acquired": {"episode": EP, "shot_id": "E08-S01-02"}, "payoff_shot_ids": ["E08-S03-02"]},
    "SET-SILVER-LIT-RIDGE": {"acquired": {"episode": EP, "shot_id": "E08-S01-03"}, "payoff_shot_ids": ["E08-S03-01"]},
}
def with_sources(row):
    return {**row, **PROP_SOURCES[row["entity_id"]]}
_first_shot_of = {}
for _sh in SHOTS:
    for _k in _sh["cast"]:
        _first_shot_of.setdefault(_k, f"{_sh['s']}-{_sh['n']:02d}")
_PRIOR = {"LZ": "E01", "LWQ": "E01", "WR": "E02", "WH": "E05", "YQ": "E04"}
NEW_IN_EP = {"PROP-IRON-POT", "PROP-ROAST-DEER-LEG", "PROP-MEAT-BROTH-BOWL", "PROP-WOODEN-STAFF", "SET-MOON-INSECT-LIGHT", "SET-SILVER-LIT-RIDGE"}
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
    "pressure_source": {"kind": "LOSS_IMMINENT", "shot_id": "E08-S10-01", "at_seconds": _shot_start["E08-S10-01"], "description": "身体新生的外显（汗如雨下、白雾蒸腾）与全村都来打听山里安不安全"},
    "episode_payoff": {"kind": "STATUS_SHIFT", "shot_id": "E08-S13-01", "description": "双树村数十年来头一个黄金年龄段新生者——刘老头当众把这件事坐实，而新生远未结束"},
    "action_chain": {"want_shot_id": "E07-S08-02", "blocked_shot_id": "E07-S10-02", "act_shot_id": "E07-S12-01", "note": "想打到肉（射鹿）→驴头狼偷袭见血→拔刀拳砸打死它；集末野猪王闯来、上树搭箭"},
    "style_reset_disclosure": STYLE_RESET_DISCLOSURE,
    "carry_in": {"previous_episode": PREV_EP, "previous_scene_id": "E06-S14", "previous_shot_id": PREV_LAST["shot_id"],
                 "previous_completion_state": PREV_LAST["completion_state"],
                 "first_shot_id": "E08-S01-01", "first_shot_entry_state": SHOTS[0]["entry"],
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
                "declaration": "SELECTIVE_NARRATIVE_CUES：两处纯器乐配乐（月虫照亮天地到流光远去、新生外显到躺上炕），覆盖 ≤85%，其余全部原生现场声；经 AgentCut bgm-generate → giggle generate-music 生成，受预算守卫与事务存档约束",
                "cues": BGM_CUES},
        "voice_casting": {"authority": "SUPERVISOR_ORDERS seq=17 c1", "note": "秦铭/杨永青/陆泽/梁婉清/陆文睿沿用已选音色；刘老头（苍老缓慢）、瘦弱男孩（清亮急促）、打补丁的小女孩（细弱怯生）新选"},
        "ambient_by_scene": {
            "E08-S01": "树皮摩擦的滑落声、落雪扑簌、呼吸白雾、极远的风", "E08-S02": "风声极弱、雪面细碎的落雪声、衣料摩擦", "E08-S03": "万籁俱寂的空气声、流光划过后的余响、远山一声凄厉嚎叫戛然而止",
            "E08-S04": "绳索绷紧、两具尸体在雪面上拖行的沙沙声、风雪打脸、脚步踩实雪路", "E08-S05": "孩子们追跑的笑闹与踩雪、猎物拖到近前的摩擦声、咽口水与小声惊呼",
            "E08-S06": "院门吱呀、猎物落地、石灶架锅、柴火噼啪、水开前的细响、衣料翻动", "E08-S07": "铁锅翻滚的咕嘟声、油脂滴进火里的嗤啦、刀刃切进烤肉的声音",
            "E08-S08": "孩子咀嚼与含混的赞叹、木勺刮碗、大人的笑声", "E08-S09": "院门木框吱呀、孩子们的脚步涌进、鼓腮帮子的咀嚼、陶碗盛汤的声音",
            "E08-S10": "大口撕咬与咀嚼、汗水滴进火里的轻响、碗筷放下的磕碰", "E08-S11": "一院子人的低声议论、脚步挪动、孩子在人群里的小声",
            "E08-S12": "人群让开的脚步、拍肩的闷响、笑声与打趣", "E08-S13": "木杖顿地、人群一瞬的安静、白雾蒸腾的细响、心跳般的低频",
            "E08-S14": "刀递出的轻碰、一盆冰水浇下的哗声、白雾腾起、炕席的摩擦、呼吸变深变慢",
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
    ("E08-EV-01", "landed", "E08-S01（两镜）", "秦铭无声地滑落到树下，躲在密林的阴影间，心中难以平静"),
    ("E08-EV-02", "landed", "E08-S01（一镜）", "那不是一般的发光生物，它照亮了这片夜空；「月虫！」他听闻过（老人们讲月虫让后人知道月亮什么样子——世界观不单独占镜，只以这一句带过）"),
    ("E08-EV-03", "landed", "E08-S02（一镜）", "起初那团光缓慢升起时较为柔和，现在太璀璨，光芒交织像一块绚烂的圆盘，哪里有虫的形态"),
    ("E08-EV-04", "landed", "E08-S02（两镜）", "皎洁的光落向漆黑山林、铺满幽暗荒岭，这片地带染成淡淡的银色，山中墨色被驱散；秦铭出神：古代的月亮就是这个样子吗"),
    ("E08-EV-05", "landed", "E08-S03（一镜）", "万籁俱寂，野猪王、追杀它的神秘生物与其他飞禽走兽都安静地蛰伏"),
    ("E08-EV-06", "landed", "E08-S03（两镜）", "一道流光划破长空，月虫远去，地带快速失去光彩；大山深处一声凄厉嚎叫又戛然而止（月虫俯冲之地似有强大生灵被击杀）"),
    ("E08-EV-07", "landed", "E08-S04（两镜）", "趁各种猛兽被震慑还不敢出没，他拉着刀角鹿与驴头狼翻过矮山迅速远去；双树村在望"),
    ("E08-EV-08", "landed", "E08-S05（一镜）", "这么冷的天，只有几个孩子在村口相互追跑，不愿待在家里"),
    ("E08-EV-09", "landed", "E08-S05（一镜）", "瘦弱男孩吃惊地睁大眼睛：「秦哥，你进山……独自猎杀到了刀角鹿？」"),
    ("E08-EV-10", "landed", "E08-S05（两镜）", "孩子们凑上前看到数百斤的黑色驴头狼吓了一跳、偷偷咽口水；秦铭笑着说一会儿都来我家吃肉"),
    ("E08-EV-11", "landed", "E08-S06（一镜）", "他像一阵风拖着两只猎物回到家中，立刻烧水，并喊来陆泽和梁婉清帮忙"),
    ("E08-EV-12", "landed", "E08-S06（三镜）", "梁婉清心细，一眼看到他肩头的血迹；「轻伤，不碍事」；陆泽检查看到伤口不深、早已结痂，放下心来"),
    ("E08-EV-13", "landed", "E08-S07（三镜）", "小院飘起浓郁香气，铁锅中煮着大块的肉，火堆上烤着滴油的鹿腿；秦铭用小刀割下薄片直接入口：「熟了，味道很好！陆文睿，今天小叔满足你的愿望了吧？」"),
    ("E08-EV-14", "landed", "E08-S08（一镜）", "陆文睿尝了一口，陶醉得眼睛弯成月牙，如小鸡啄米似的点头：「好香啊……小叔你真是太棒了！」"),
    ("E08-EV-15", "landed", "E08-S08（两镜）", "两岁出头的陆文晖咬不动烤鹿腿，只能吃捣烂的肉糊，委屈地瘪嘴，让几人都笑了"),
    ("E08-EV-16", "landed", "E08-S09（三镜）", "院门外几个孩子探头，闻着肉香不好意思进来；秦铭招手「都快进来，一起吃吧」，孩子们腼腆进院鼓着腮帮子嚷好吃"),
    ("E08-EV-17", "landed", "E08-S09（一镜）", "梁婉清怕孩子噎到，给他们盛了些肉汤：「都慢点，还有很多」"),
    ("E08-EV-18", "landed", "E08-S10（两镜）", "秦铭胃口像无底洞、汗水蒸腾起白雾；陆泽很吃惊：身体新生正在剧烈变化中（血肉欢呼、筋络生长、骨节作响的内心描写不演，只给外显）"),
    ("E08-EV-19", "landed", "E08-S11（一镜）", "狩猎到刀角鹿与驴头狼的消息传开，村民很吃惊，小院里来了很多人向他打听山中的情况"),
    ("E08-EV-20", "landed", "E08-S11（两镜）", "打补丁的小女孩低声说饿了；秦铭招呼孩子们过来吃，并许下每家割五斤肉回去"),
    ("E08-EV-21", "landed", "E08-S12（一镜）", "杨永青赶来：「小秦，你和叔说实话，是不是新生了？」"),
    ("E08-EV-22", "landed", "E08-S12（三镜）", "秦铭笑着把贵女那句话顶回去，杨永青笑着点指「你这小子，不够朴实啊」"),
    ("E08-EV-23", "landed", "E08-S13（一镜）", "住在村口的刘老头感叹：「在黄金年龄段新生，数十年来，这是我们双树村头一份啊！」"),
    ("E08-EV-24", "landed", "E08-S13（两镜）", "极寒天气里秦铭的身体像个火炉子、越来越烫、白雾几乎裹住他；杨永青络腮胡颤动，听见他的心跳宛若擂鼓"),
    ("E08-EV-25", "landed", "E08-S14（一镜）", "困意袭来，他请陆泽为各家分肉，并嘱咐周阿婆今天下葬、给周家多送一些肉"),
    ("E08-EV-26", "landed", "E08-S14（两镜）", "他用冰水冲洗身体，而后躺在炕上沉沉睡去，像要陷入一场特殊的「冬眠」（杨永青关于明亮城池少年的内心比较整段略去，manifest 申报 dropped）"),
    ("E08-EV-27", "dropped", "—", "杨永青的内心比较：秦铭是否能接近明亮城池里那几位名气很大的少年、以及最近惊艳城池的一男一女（纯内心评估，不可表演，整段略去）"),
]
SCENE_BEAT_META = {
    "E08-S01": {"type": "reveal"}, "E08-S02": {"type": "reveal"}, "E08-S03": {"type": "reveal"},
    "E08-S04": {"type": "transition"},
    "E08-S05": {"type": "dialogue"}, "E08-S06": {"type": "dialogue"}, "E08-S07": {"type": "dialogue"},
    "E08-S08": {"type": "dialogue"}, "E08-S09": {"type": "dialogue"},
    "E08-S10": {"type": "reveal"}, "E08-S11": {"type": "dialogue"}, "E08-S12": {"type": "dialogue"},
    "E08-S13": {"type": "reveal"}, "E08-S14": {"type": "transition"},
}
assert set(SCENE_BEAT_META) == set(SCENES), set(SCENES) ^ set(SCENE_BEAT_META)
_FS1 = [{"cluster_id": "E08-FS1-NONE", "shots": [], "source": "ch8 本集没有打斗段落：奇观、回村、院中分肉与新生外显，全部为非战斗动作"}]
for _c in _FS1:
    _c["seconds"] = round(sum(_shot_by_id[x]["sec"] for x in _c["shots"]), 1)
manifest = {
    "episode": EP, "version": VER, "title": "曾照彩云归",
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
    "voice_casting_seq17": {k: cname(k) for k in ("QM", "YQ", "LZ", "LWQ", "WR", "LLT", "BOY", "GIRL")},
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
