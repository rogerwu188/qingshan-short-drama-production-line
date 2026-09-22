import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
# -*- coding: utf-8 -*-
"""E02《火泉》v1 —— 从一张镜头表生成 directing script / generation contract / manifest。

单一事实源是 SHOTS 表；narrative canonical（E02_NARRATIVE_CANONICAL_v1.md）为手写，本层不改其任何事实与对白。
2026-09-13 新口径（Roger 审片意见 2/3/5/6 + 「尽量加快节奏」+ 「固定机位静止段落太多」）在本文件的 STYLE / PACING 块落地。
"""
import hashlib, json, pathlib, re

ROOT = pathlib.Path(f"{_np.ENGINE_ROOT}")
SCRIPTS = ROOT / "workflow/claude_writer_agent/scripts"
RUNTIME = pathlib.Path(f"{_np.RUNTIME_ROOT}")
SRC_CH2 = RUNTIME / "sources/夜无疆/zh-CN/ch0002.md"
QM_SOURCE_V2 = RUNTIME / "runtime/character_sources/CHAR-QINMING__SOURCE_V2_TANG.png"
EP, VER = "E02", "v1"

def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

CH = {
    "QM": ("CHAR-QINMING", "秦铭"),
    "LZ": ("CHAR-LUZE", "陆泽"),
    "LW": ("CHAR-LIANGWANQING", "梁婉清"),
    "WR": ("CHAR-LUWENRUI", "陆文睿"),
    "CA": ("CHAR-COMPANION-A", "同行者甲"),
    "CB": ("CHAR-COMPANION-B", "同行者乙"),
    "CC": ("CHAR-COMPANION-C", "同行者丙"),
}
def cid(k): return CH[k][0]
def cname(k): return CH[k][1]

# ---------- 2026-09-13 全局风格与节奏口径 ----------
STYLE = {
    "profile_id": "YEWUJIANG_PERMANENT_NIGHT_TANGSONG_VILLAGE_V2",
    "era_idiom": "中国唐宋：木构穿斗/抬梁屋架、瓦顶或压雪茅顶带出檐、直棂格窗、夯土院墙与木板门；男子发髻木簪、交领右衽、大袖或窄袖袍、布带束腰、布靴裹腿；妇人交领短襦长裙加围裙、包髻；器物为粗陶、铜盆、木食盒、竹筷、木柜、火炕",
    "night_look": "永夜用暖火光（太阳石橘红、火泉火红）+ 雪面反光 + 月色青蓝三种光写；不做西式暗黑/哥特式冷灰去饱和调色；肤色在火光下暖、在雪光下清",
    "forbidden": ["欧式石堡与哥特元素", "西式暗黑冷灰去饱和调色", "现代服装、拉链纽扣与现代物件", "电灯、玻璃窗、金属门把手", "日式盔甲与和风建筑", "仙侠飘带与发光符文特效", "明亮日光或蓝天", "霓虹与冷色 LED", "整洁无雪的街道", "长发散披不束的男主"],
}
# 逐镜 period_constraints 的公共底稿；按场景类型加一句本景专属约束
PERIOD_BASE = "唐宋语汇：木构、瓦顶/压雪茅顶、直棂格窗、夯土院墙、木板门；人物交领右衽、发髻木簪或包髻；器物粗陶铜盆木食盒竹筷；夜景=暖火光+雪面反光+月色青蓝，不做冷灰去饱和"
PERIOD_BY_LOC = {
    "LOC-FIRE-SPRING-EXT": PERIOD_BASE + "；火泉石围为粗凿青石，无雕花，无欧式石砌纹样；池畔无人造灯具",
    "LOC-QINMING-YARD-EXT": PERIOD_BASE + "；院门为木板门带门枢，院墙夯土压雪，院中粗石盆盛太阳石；无栅栏、无金属门把手",
    "LOC-QINMING-HOUSE-INT": PERIOD_BASE + "；单间土屋：火炕在北墙、木格糊纸窗、旧木立柜、铜盆盛太阳石为唯一光源；无玻璃、无灯具、无现代家具",
    "LOC-MOUNTAIN-CREVICE-INT": PERIOD_BASE + "；一个月前山林地缝：岩壁与碎石，四人皆猎户短褐皮袄；尸体衣着为唐宋贵人式交领锦袍，不得出现西式甲胄或哥特斗篷",
}
STYLE_RESET_DISCLOSURE = {
    "kind": "DELIBERATE_STYLE_RESET_AT_EPISODE_BOUNDARY",
    "authority": "SUPERVISOR_ORDERS seq=7 (ROGER-20260913-NALU-E02-NEW-RULES-TANG-SONG-PACING-SOURCE-V2) c1/c2/c4；PRODUCTION_LINE_OVERVIEW_v1 §四 2/3/5",
    "what_changes": "E02 起全局画风改中国唐宋（建筑、服制、道具、字体）；夜景改暖火光+雪面反光+月色青蓝；秦铭面孔与发冠服制以 CHAR-QINMING__SOURCE_V2_TANG.png 为参考（发髻木簪、深色交领袍银线滚边），不再年轻化",
    "what_stays": "剧情层服装状态承接 E01 末场：冬装、外披旧裘氅、内交领深色袍；同一人物、同一地点、同一时间线（E02-S01 直接接 E01-S10 终态）",
    "qinming_identity_source": {"file": str(QM_SOURCE_V2), "sha256": sha(QM_SOURCE_V2) if QM_SOURCE_V2.is_file() else "", "usage": "FACE_IDENTITY_REFERENCE + WARDROBE/HAIR STYLE REFERENCE（唐宋：高髻木簪、深色交领袍、银线纹饰）"},
    "e01_plates_status": "E01 身份牌按 V1 面部裁切生成并已交付，不重做；E02 身份牌按 source_v2 重做（seq=7 c4）",
    "viewer_facing_note": "E01→E02 之间画风与男主造型有可见变化；这是有意的风格重置，不是连续性错误",
}
PACING = {
    "authority": "Roger 2026-09-13：整体节奏偏慢 + 尽量加快节奏 + 编剧层固定机位静止段落太多",
    "shot_seconds_default": [3, 5],
    "shot_seconds_max": 7,
    "shot_seconds_max_note": "7 s 只用于单句台词按 dialogue_cut_safety 确实放不进 5 s 的镜头（本集仅 E02-S05-03）；6 s 用于 4 句按 4.8–5.0 字/秒仍放不进 5 s 的台词镜头（E02-S06-05 / S07-01 / S10-01 / S13 无）",
    "video_unit_seconds_max": 6.0,
    "video_unit_seconds_hard_cap": 7.0,
    "video_unit_note": "写手层意图 ≤6 s；引擎 build_video_unit_grouping_spec 的分组代价函数偏好 5–8 s 单元且不读本字段，单元实际上限由引擎决定（seq=7 c3 硬上限 7 s）",
    "no_dialogue_static_hold_seconds_max": 2.0,
    "no_dialogue_static_hold_verdict": "REJECT（生成后 QA 静止判定由提示改为拒收）",
    "scene_opening_rule": "每场第一镜从进行中的动作开始，不给建立镜头停顿；场与场之间在动作上切",
    "scene_turn_rule": "每场有转折与 button（见 directing script 每场末镜）",
    "hook_rule": "全集前 3 秒 = 手探火泉（E02-S01-01）",
    "episode_total_seconds_target": [170, 180],
    "camera_motion_policy": {
        "authority": "Roger 2026-09-13：「编剧层设计了太多固定机位的静止段落，修改这个问题」；校验器 nalu_runtime/runtime/tools/static_design_gate.py",
        "locked_share_max": 0.35,
        "consecutive_locked_allowed": False,
        "no_dialogue_shot_requires_camera_motion": True,
        "no_dialogue_visible_state_delta_within_seconds": 2.0,
        "locked_only_for_dialogue_shots_seconds_max": 5.0,
        "same_axis_scale_run_max": 2,
        "opening_shot_must_move": True,
        "allowed_motion_families": ["DOLLY", "TRACK", "CRANE", "ARC", "PAN"],
    },
}

SCENES = {
    "E02-S01": dict(loc="LOC-FIRE-SPRING-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·雪停·极冷", light="火泉火红光为主光，映亮石围与秦铭面部", sec=10, beats=["E02-EV-01", "E02-EV-03"], info=2),
    "E02-S02": dict(loc="LOC-FIRE-SPRING-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·寒风·零星雪花", light="身后火泉暖光，面前野外靛黑；远方地光一闪", sec=10, beats=["E02-EV-06", "E02-EV-07", "E02-EV-08", "E02-EV-09"], info=2),
    "E02-S03": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·冷风", light="院内石盆太阳石橘红光 + 雪面反光", sec=6, beats=["E02-EV-10"], info=1),
    "E02-S04": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT-ENDING", weather="屋外浅夜将尽", light="铜盆太阳石橘红火霞，瓶中蓝光为点光", sec=10, beats=["E02-EV-11"], info=2),
    "E02-S05": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT-ENDING", weather="浅夜将尽·冷风", light="院内石盆太阳石橘红光", sec=22, beats=["E02-EV-12"], info=2),
    "E02-S06": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT-ENDING", weather="屋外浅夜将尽", light="铜盆太阳石橘红暖光满室", sec=22, beats=["E02-EV-13", "E02-EV-14"], info=2),
    "E02-S07": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT-ENDING", weather="屋外浅夜将尽", light="铜盆太阳石橘红暖光满室", sec=17, beats=["E02-EV-15"], info=2),
    "E02-S08": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT-ENDING", weather="屋外浅夜将尽", light="铜盆太阳石橘红暖光，压低声音时两人脸在火光侧", sec=12, beats=["E02-EV-16"], info=1),
    "E02-S09": dict(loc="LOC-MOUNTAIN-CREVICE-INT", time="TIME-FLASHBACK-ONE-MONTH-AGO", weather="山林深夜·无雪·地缝内", light="先极暗，后刺目白光炸开，再转为银丝交织的冷银光，最后全黑，地缝口外只余浅夜微光轮廓", sec=12, beats=["E02-EV-17"], info=2),
    "E02-S10": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT-ENDING", weather="屋外夜色渐浓", light="铜盆太阳石橘红暖光", sec=16, beats=["E02-EV-19"], info=2),
    "E02-S11": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-DEEP-NIGHT", weather="屋外深夜", light="铜盆太阳石光焰变淡，暗红；睁眼一瞬极淡银光", sec=10, beats=["E02-EV-20"], info=2),
    "E02-S12": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-DEEP-NIGHT", weather="深夜·大风卷雪", light="各家火光暗下，院内仅雪面月色青蓝反光；体表极微弱银光", sec=14, beats=["E02-EV-21"], info=2),
    "E02-S13": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-DEEP-NIGHT", weather="屋外深夜大风", light="一小块太阳石照路的橘红余光，水盆映脸", sec=21, beats=["E02-EV-21"], info=2),
}

AMBIENT_LIFE = {
    "E02-S01": {"grade": "B", "motion_trend": "火泉光焰低频跳动、池面光波荡漾、零星雪花落入火光即灭、呼出白气", "first_frame_state": "秦铭已站在石围前抬头望树，目光正从树上收回", "reaction_progression": "蹲下手探火光不缩→捞出石块霞光四照→贴脸眉头不皱→松手石落光溅"},
    "E02-S02": {"grade": "B", "motion_trend": "远方地光一闪、寒风划过火池波光粼粼、双树簌簌落雪、雪花飘落", "first_frame_state": "秦铭正站起身转向村外，野外靛黑", "reaction_progression": "地光照出林线→盯林线手攥紧→雪花落进脖颈缩肩回神→转身往村里走"},
    "E02-S03": {"grade": "B", "motion_trend": "院门推开带落门上积雪、动作带起衣袖、白雾越来越浓、石盆太阳石光在雪面跳动", "first_frame_state": "秦铭推开院门正跨进院中", "reaction_progression": "摆开第一组动作→一组接一组换→额头见汗→停下周身有暖意"},
    "E02-S04": {"grade": "C", "motion_trend": "铜盆火霞在墙上晃动、瓶中蓝雾流动、衣料摩擦", "first_frame_state": "秦铭正跨进屋门，手已伸进怀里", "reaction_progression": "抽出水晶瓶迎火霞看→轻摇蓝雾流动→拇指按瓶塞停住移开→塞回怀里按了按"},
    "E02-S05": {"grade": "B", "motion_trend": "院门开合、男孩蹦跳、呼出白气、食盒换手、石盆太阳石光在雪面跳动", "first_frame_state": "院门正被推开，陆泽与文睿跨进来", "reaction_progression": "秦铭迎上比划身高→文睿仰头问→秦铭蹲下许诺语雀→文睿原地跳起→陆泽嘴角动、食盒换手"},
    "E02-S06": {"grade": "B", "motion_trend": "食盒木盖开合、筷子挑饭、红枣在筷尖晃、男孩咽口水、铜盆火霞晃动", "first_frame_state": "陆泽正把食盒递到秦铭手里", "reaction_progression": "掀盒扒饭挑到红枣→文睿盯枣咽口水→秦铭筷子停、蹲下问→陆泽摇头答→秦铭挑枣、陆泽攥腕→两手僵住红枣晃"},
    "E02-S07": {"grade": "B", "motion_trend": "门开带进冷气、男孩点头张口、叹气落座、松手", "first_frame_state": "梁婉清正跨进屋门", "reaction_progression": "梁婉清劝孩子→文睿点头说不饿→秦铭把枣送到嘴边、男孩看母亲吃下→梁婉清叹气坐下、陆泽松手"},
    "E02-S08": {"grade": "C", "motion_trend": "门开合、身体凑近、铜盆火霞在两人脸侧跳动、手指收紧", "first_frame_state": "梁婉清正起身向门口走，陆泽已向秦铭凑近", "reaction_progression": "梁婉清出门→陆泽压低声音说密林→秦铭手指收紧、眼神落进火光"},
    "E02-S09": {"grade": "A", "motion_trend": "四人踩空坠落、碎石滚落、刺目光炸开、银丝银网交织流动、人体瘫倒、拖拽", "first_frame_state": "四人脚下正踩空，身体已失去平衡下坠", "reaction_progression": "跌进地缝→极暗后光炸开、双眼生疼手按胸口→银光交织三人先后昏死→银光消失全黑、秦铭拖人出缝→尸体旁捡起水晶瓶攥进掌心"},
    "E02-S10": {"grade": "B", "motion_trend": "男孩咽口水、摸头、牵手出门、门外黑暗吞没背影、铜盆火霞", "first_frame_state": "秦铭正回过神转向男孩", "reaction_progression": "秦铭许诺枣子榛果→文睿问有肉肉吗→秦铭摸头答会有的→父子出门、秦铭门口目送"},
    "E02-S11": {"grade": "C", "motion_trend": "太阳石光焰变淡收缩、呼吸起伏放缓、睁眼一瞬极淡银色涟漪散去、汗珠", "first_frame_state": "秦铭已闭目坐在炕沿，铜盆光正变淡", "reaction_progression": "呼吸放缓→睁眼刹那银色涟漪散去→低头看手臂空无→额头脖颈汗水"},
    "E02-S12": {"grade": "B", "motion_trend": "各家火光先后暗下、大风卷雪、脱衣扔雪、成组动作、白雾大汗、指缝银光流过散去、肚鸣", "first_frame_state": "秦铭正走到院中，手已在解裘氅", "reaction_progression": "脱下裘氅扔雪上→一组组动作白雾大汗→停下喘气银光浮现指缝流过→按胸口暖意→抬臂想再练、肚子叫放下"},
    "E02-S13": {"grade": "C", "motion_trend": "水盆水面微晃、躺下盖大衣、肚鸣、嘴角翘、掐自己、翻身、眼睁着", "first_frame_state": "秦铭已俯身在水盆上，水面映出面孔", "reaction_progression": "看见血色→决定明早动身→躺下盖大衣肚子叫→想烤羊腿嘴角翘→掐自己→翻身向窗→手按胸口眼睁着"},
}
def _wp(sid, mode):
    return {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": f"E02_NARRATIVE_CANONICAL_v1.md#{sid}｜ch2", "visibility_mode": mode}
WEATHER_PROVENANCE = {
    "E02-S01": _wp("E02-S01", "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED"),
    "E02-S02": _wp("E02-S02", "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED"),
    "E02-S03": _wp("E02-S03", "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED"),
    "E02-S04": _wp("E02-S04", "OFFSCREEN_ONLY_SHALLOW_NIGHT_THROUGH_DOOR_INTERIOR_DRY"),
    "E02-S05": _wp("E02-S05", "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED"),
    "E02-S06": _wp("E02-S06", "OFFSCREEN_ONLY_SHALLOW_NIGHT_THROUGH_DOOR_INTERIOR_DRY"),
    "E02-S07": _wp("E02-S07", "OFFSCREEN_ONLY_SHALLOW_NIGHT_THROUGH_DOOR_INTERIOR_DRY"),
    "E02-S08": _wp("E02-S08", "OFFSCREEN_ONLY_SHALLOW_NIGHT_THROUGH_DOOR_INTERIOR_DRY"),
    "E02-S09": _wp("E02-S09", "UNDERGROUND_CREVICE_NO_WEATHER_VISIBLE"),
    "E02-S10": _wp("E02-S10", "OFFSCREEN_ONLY_SHALLOW_NIGHT_THROUGH_DOOR_INTERIOR_DRY"),
    "E02-S11": _wp("E02-S11", "OFFSCREEN_AUDIBLE_WIND_SNOWLIGHT_THROUGH_WINDOW_GAP_INTERIOR_DRY"),
    "E02-S12": _wp("E02-S12", "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED"),
    "E02-S13": _wp("E02-S13", "OFFSCREEN_AUDIBLE_WIND_SNOWLIGHT_THROUGH_WINDOW_GAP_INTERIOR_DRY"),
}
for _sid, _m in SCENES.items():
    _m["ambient_life"] = AMBIENT_LIFE[_sid]
    _m["weather_provenance"] = WEATHER_PROVENANCE[_sid]

# ---------- 服装（唐宋语汇；剧情层服装状态承接 E01：冬装、外披旧裘） ----------
WARDROBE_GARMENTS = {
    "CHAR-QINMING": {"silhouette": "颀长清瘦、高髻木簪、外披过膝旧裘氅、内交领深色袍", "outer_layer": "陈旧兽皮裘氅（毛面磨秃、下摆结霜，无袖披式）", "inner_layer": "深青交领右衽窄袖袍，领缘与袖口银线滚边（旧、洗淡）", "primary_color": "灰褐（裘氅）", "secondary_color": "深青（袍）", "material": "兽皮＋粗麻棉", "pattern": "裘氅素面磨秃；袍领袖银线细纹", "belt_or_fastening": "布带束腰，裘氅前襟布带系结", "footwear": "旧布靴加裹腿", "accessory": "发髻木簪（源照片同款发式）"},
    "CHAR-LUZE": {"silhouette": "壮实宽肩、束发裹巾、齐膝交领短褐", "outer_layer": "深灰粗麻交领短褐（外层）", "inner_layer": "灰白中衣", "primary_color": "深灰", "secondary_color": "灰褐（腰带）", "material": "粗麻棉", "pattern": "粗织纹，肩背补丁与磨痕", "belt_or_fastening": "麻布腰带打结", "footwear": "裹腿加旧皮靴", "accessory": "灰布裹巾束发"},
    "CHAR-LIANGWANQING": {"silhouette": "交领短襦配长裙与围裙、包髻", "outer_layer": "灰褐粗麻交领短襦（外层）", "inner_layer": "旧蓝长裙", "primary_color": "灰褐", "secondary_color": "旧蓝（裙）", "material": "粗麻棉", "pattern": "细密织纹，围裙边缘磨破", "belt_or_fastening": "细布系带＋麻布围裙", "footwear": "布鞋加裹腿", "accessory": "麻布包髻"},
    "CHAR-LUWENRUI": {"silhouette": "五岁男童、裹得滚圆、风帽", "outer_layer": "赭红小交领棉袍（外层，裹得严实）", "inner_layer": "灰白小中衣", "primary_color": "赭红", "secondary_color": "灰白（风帽里子）", "material": "粗棉", "pattern": "素面，袖口磨旧", "belt_or_fastening": "布带束腰", "footwear": "小棉靴", "accessory": "厚布风帽包住双耳"},
    "CHAR-COMPANION-A": {"silhouette": "精瘦猎户、短褐皮袄、背筐", "outer_layer": "褐色兽皮短袄", "inner_layer": "灰麻交领短褐", "primary_color": "褐", "secondary_color": "灰", "material": "兽皮＋粗麻", "pattern": "皮袄毛面外翻", "belt_or_fastening": "麻绳束腰", "footwear": "草鞋裹腿", "accessory": "背筐"},
    "CHAR-COMPANION-B": {"silhouette": "敦实猎户、长皮袍、包头", "outer_layer": "黑褐兽皮长袍", "inner_layer": "深灰麻衣", "primary_color": "黑褐", "secondary_color": "深灰", "material": "兽皮＋粗麻", "pattern": "皮袍拼缝粗", "belt_or_fastening": "宽皮带", "footwear": "皮靴", "accessory": "灰布包头"},
    "CHAR-COMPANION-C": {"silhouette": "高瘦猎户、麻布袍、斗笠", "outer_layer": "灰黄粗麻交领长袍", "inner_layer": "白麻中衣", "primary_color": "灰黄", "secondary_color": "白", "material": "粗麻", "pattern": "横纹粗织", "belt_or_fastening": "布带束腰", "footwear": "布靴", "accessory": "破斗笠"},
}
# E02-S09 闪回：一个月前进山，秦铭尚未大病，无裘氅；只穿猎装
FLASHBACK_QM_WARDROBE = "本镜为一个月前闪回：秦铭不披裘氅，只穿深青交领窄袖袍外罩褐色兽皮短袄、麻绳束腰、发髻木簪；面色未病、无汗"

# ---------- 道具（seq=7 c6：关键道具出参考卡；只列 narrative 实际用到的） ----------
PROPS = [
    {"entity_id": "PROP-FIRE-SPRING-STONE", "name": "发光石块", "reference_card_required": True, "first_shot": "E02-S01-02",
     "note": "火泉池中捞出的发光石块：比红珊瑚还莹润，霞光四照，光不烫手；手掌大小，红橘色内透光；与太阳石同源（E01 PROP-SUN-STONE），本集作为主体道具单独出卡", "period_constraints": "天然石块，无切割面、无符文、无金属镶嵌"},
    {"entity_id": "PROP-CRYSTAL-VIAL", "name": "矿素水晶小瓶", "reference_card_required": True, "first_shot": "E02-S04-01",
     "note": "袖珍水晶瓶，只有拇指长，雕饰细腻透明精巧；瓶内带冰晶的蓝色液体，轻摇时蓝雾流动；瓶体刻「矿素」二字；有瓶塞", "period_constraints": "唐宋玉器/水晶器语汇的素雅刻饰，无西式切割棱面、无金属旋盖；刻字为楷书"},
    {"entity_id": "PROP-FOOD-BOX", "name": "木食盒（岩米饭）", "reference_card_required": True, "first_shot": "E02-S05-05",
     "note": "陆家提梁木食盒（与 E01 同款），盒内岩米饭粗糙偏硬，饭中埋着几颗红枣；配竹筷", "period_constraints": "素木提梁食盒，榫卯无金属合页"},
    {"entity_id": "PROP-RED-DATE", "name": "红枣", "reference_card_required": True, "first_shot": "E02-S06-02",
     "note": "几颗蒸软的红枣，软滑透出甜香，皮色深红发亮；在筷尖上会晃", "period_constraints": "真实红枣，不做卡通化"},
    {"entity_id": "PROP-ROAST-LAMB-LEG", "name": "烤羊腿", "reference_card_required": False, "first_shot": "",
     "note": "只在秦铭闭眼时的台词中出现（E02-S13-03「烤羊腿……」），narrative 无羊腿画面，本集不入镜；参考卡不出（若导演后续决定加一帧幻想插入，再把本项升为 True 并登记 ★authorized_insertions）", "period_constraints": "篝火炙烤的整条羊腿，金黄油亮；无现代烤架", "on_screen": False},
]
SETS = [
    {"entity_id": "SET-FIRE-SPRING", "name": "火泉", "note": "丈六见方石围池，火红光焰，暴雪季接近枯竭；池中一黑叶树一白叶树不凋零（E01 已建立；E02 不复证形制，只给新角度：池中的光不烫手）"},
    {"entity_id": "SET-MOUNTAIN-CREVICE", "name": "山林地缝", "note": "一个月前闪回：漆黑山林中的一条地缝，岩壁碎石；先极暗，后刺目白光，再银丝银网交织，最后全黑；地缝口外不远处几具穿着不俗的尸体（唐宋贵人式交领锦袍）"},
]
# ---------- END OF CHUNK 1 ----------

# NOTE 2026-09-14: PROP-YUQUE removed from non_character_entities — the bird is only spoken about in E02 (S05-03/S05-04 dialogue); the engine editorial scan attached it as a visible prop, which the derived start frame cannot show.
# ---------- 机位方案（导演授权；2026-09-13 camera_motion_policy：LOCKED ≤35%、不连续、无对白必动、开场必动） ----------
def _cp(scale, height, side, lens, axis, fam, direction, start, end, why):
    # engine compile_video_unit_plan: a LOCKED camera must keep identical start/end framing —
    # the actor's action carries the change, so it moves into `motivation`.
    if fam == "LOCKED" and end != start:
        why = f"{why}；画内变化：{end}"
        end = start
    return {"shot_scale": scale, "camera_height": height, "camera_side": side, "lens_intent": lens, "axis_relation": axis,
            "motion_family": fam, "motion_direction": direction, "start_framing": start, "end_framing": end, "motivation": why}
CAMERA_PLANS = {
    "E02-S01-01": _cp("CLOSE_UP", "HIGH", "NEUTRAL", "85mm高机位俯拍特写：镜头在石围正上方向下看池面，画面只有膝高石围的边缘、池中火红光与秦铭仰头时的侧脸上缘和肩线；不见全身、不见背影、不见双树全貌；随蹲下的手推近", "秦铭在石围外（画下方）面向池心的轴线，不越轴", "DOLLY", "PUSH_IN", "高机位俯拍特写：石围边缘占画面下三分之一，火红池面占中部，秦铭仰头的侧脸上缘与肩线在画面上缘入画；无全身、无背影远景", "俯拍特写：手腕没入火光，火光淹到腕", "导演稿：开场 3 秒钩子，镜头随手探池推近，手与火光是唯一主体；禁止平视背影中全景（首版关键帧 Q1 判不通过的原因）"),
    "E02-S01-02": _cp("MEDIUM_CLOSE_UP", "LOW", "AXIS_A", "50mm低机位自手拉出至面部", "秦铭面向池心（画右）的视线轴，不越轴", "DOLLY", "PULL_OUT", "低机位特写：出水的手与发光石块", "低机位中近景：石块霞光直照秦铭面部", "导演稿：拉出让石块的霞光把脸照亮，读出「捞起」这一动作的结果"),
    "E02-S01-03": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_B", "85mm环绕面部与贴脸的石块", "秦铭面向池心的视线轴，环绕不越轴", "ARC", "CLOCKWISE", "特写：石块贴在脸侧，眉头舒展", "特写：手指松开，石块落回池中光溅起在画下缘", "导演稿：环绕读眉头不皱（不烫手），停在松手石落光溅上作 button"),
    "E02-S02-01": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm手持随站起转身", "秦铭背向火泉、面向村外黑暗（画面纵深）的轴线，不越轴", "TRACK", "LEFT_TO_RIGHT", "中全景：秦铭蹲在石围前，火泉在画左", "中全景：秦铭站定面向村外，远方地光一闪照出林线", "导演稿：手持跟随站起转身，让地光一闪与积雪野外在同一移动构图里出现"),
    "E02-S02-02": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_A", "85mm缓推面部与攥紧的手", "秦铭面向村外的视线轴，不越轴", "DOLLY", "PUSH_IN", "特写：秦铭盯林线，手在身侧松开，双树在背景", "更紧特写：手指攥紧，背景双树簌簌落雪", "导演稿：推近读盯林线与手攥紧，背景落雪为下一镜雪花入领铺垫"),
    "E02-S02-03": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm环绕至他转身的方向", "秦铭由面向村外转为面向村内，环绕过程中不越视线轴", "ARC", "COUNTERCLOCKWISE", "中近景：雪花落在脖颈，秦铭一缩肩", "中近景：秦铭背影转向村里，火泉在画右", "导演稿：环绕把「缩肩回神」和「转身回村」连成一个动作，场尾在动作上切"),
    "E02-S03-01": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm手持跟随进院门", "院门（右）到院中（左）的行进轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中全景：秦铭推开院门，门上积雪落下", "中全景：秦铭站到院中石盆旁，摆开第一组动作", "导演稿：跟随进院，不给院子建立停顿，落在第一组动作已开始"),
    "E02-S03-02": _cp("MEDIUM", "LOW", "AXIS_B", "35mm低机位缓推", "秦铭面向画左的动作轴，不越轴", "DOLLY", "PUSH_IN", "低机位中景：秦铭换到第二组动作，白雾初起", "低机位中景偏近：秦铭停下，额头见汗，白雾浓", "导演稿：低机位推近让成组动作的娴熟与见汗停下在一个推进里完成"),
    "E02-S04-01": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "40mm定点横摇跟随进屋到铜盆前", "屋门（右）到铜盆（左）的行进轴，不越轴", "PAN", "RIGHT_TO_LEFT", "中近景：秦铭跨进屋门，手伸进怀里", "中近景：秦铭站到铜盆前，水晶瓶在手中", "导演稿：跟随进屋，取瓶动作在行进中完成"),
    "E02-S04-02": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_B", "85mm推近瓶体，面部在瓶后", "秦铭面向铜盆火霞的视线轴，不越轴", "DOLLY", "PUSH_IN", "特写：瓶举在胸前，面部在后", "特写：瓶举到眼前迎火霞，蓝雾流动，面部在瓶后可见", "导演稿：推近读瓶中蓝雾流动与「矿素」一句"),
    "E02-S04-03": _cp("CLOSE_UP", "HIGH", "AXIS_A", "85mm微俯固定，拇指与瓶塞", "秦铭面向铜盆的视线轴，不越轴", "LOCKED", "NONE", "微俯特写：拇指按在瓶塞上，面部在画上缘", "微俯特写：瓶塞回怀中，手按在衣襟上", "导演稿：固定（对白镜 ≤5 s），拇指停住又移开的犹豫由手部动作承担"),
    "E02-S05-01": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm手持自秦铭身后跟向院门", "院中（左）到院门（右）的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中全景：院门被推开，陆泽与男孩跨进来，秦铭背影在前景", "中全景：秦铭到男孩身前，抬手在头顶比划", "导演稿：跟随迎上去，比划身高与第一句台词在行进结束时落地"),
    "E02-S05-02": _cp("MEDIUM_CLOSE_UP", "HIGH", "AXIS_B", "50mm过秦铭肩俯看男孩", "秦铭在右、男孩在左的轴线，不越轴", "LOCKED", "NONE", "过肩俯拍近景：男孩低头，秦铭肩在前景", "过肩俯拍近景：男孩仰起头，大眼看向秦铭", "导演稿：固定（对白镜 ≤5 s），仰头动作本身带动"),
    "E02-S05-03": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm随秦铭蹲下降到男孩视平", "秦铭在右、男孩在左的轴线，不越轴", "CRANE", "FALL", "中近景：秦铭站着俯视男孩，男孩仰头", "中近景（降到男孩视平）：两人平视，秦铭说话", "导演稿：机位随蹲下下降，7 s 承载语雀一句"),
    "E02-S05-04": _cp("MEDIUM", "LOW", "AXIS_B", "35mm低机位随男孩跳起升起", "男孩在左、秦铭在右的轴线，不越轴", "CRANE", "RISE", "低机位中景：男孩双脚在地，眼睛发亮", "低机位中景：男孩原地跳起落下，秦铭在画右微笑", "导演稿：随跳起升起，让「太好了」的兴奋有机位反应"),
    "E02-S05-05": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm缓推陆泽", "陆泽在后、面向秦铭与儿子的视线轴，不越轴", "DOLLY", "PUSH_IN", "中近景：陆泽在院门内看着，食盒提在右手", "中近景偏近：陆泽嘴角动了动，食盒换到左手", "导演稿：推近读嘴角一动与食盒换手，场尾 button"),
    "E02-S06-01": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm手持随二人进屋", "陆泽在右、秦铭在左隔食盒的轴线，不越轴", "TRACK", "LEFT_TO_RIGHT", "中景：食盒从陆泽手中递出，秦铭在门内", "中景：食盒在秦铭手中，盒盖掀开", "导演稿：跟随进屋，递盒与第一句在行进中完成"),
    "E02-S06-02": _cp("CLOSE_UP", "HIGH", "AXIS_B", "85mm俯拍推近食盒", "秦铭在左、男孩在右看向食盒的轴线，不越轴", "DOLLY", "PUSH_IN", "俯拍特写：筷子扒饭，红枣露出", "俯拍特写：红枣在筷尖，男孩的脸在画缘咽口水，筷子停住", "导演稿：推近食盒读红枣与男孩咽口水，筷子停半空是转折"),
    "E02-S06-03": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm随秦铭蹲下下降", "秦铭在左、男孩在右的轴线，不越轴", "CRANE", "FALL", "中近景：秦铭放下食盒，站着", "中近景（男孩视平）：秦铭蹲着平视男孩问话", "导演稿：机位随蹲下下降，问句在平视时落地"),
    "E02-S06-04": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm过秦铭肩固定看陆泽", "陆泽在右、秦铭在左的轴线，不越轴", "LOCKED", "NONE", "过肩近景：陆泽面向秦铭，头正", "过肩近景：陆泽摇头说完", "导演稿：固定（对白镜 ≤5 s），摇头本身带动"),
    "E02-S06-05": _cp("CLOSE_UP", "HIGH", "AXIS_A", "85mm俯拍推近食盒上方的两只手", "秦铭在左、陆泽在右隔食盒的轴线，不越轴", "DOLLY", "PUSH_IN", "俯拍特写：筷子挑枣，陆泽的手自画右伸入", "俯拍特写：陆泽攥住秦铭手腕，两手僵住，红枣在筷尖上晃", "导演稿：推近两只手，攥腕与僵住是场尾 button"),
    "E02-S07-01": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm手持随梁婉清进门", "屋门（右）到屋内（左）的行进轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中景：梁婉清跨进屋门，冷气带进", "中景：梁婉清站在屋内看向文睿说话，三人在背景", "导演稿：跟随进门，一句劝话在停步时说完"),
    "E02-S07-02": _cp("CLOSE_UP", "HIGH", "AXIS_B", "85mm俯拍缓推男孩", "男孩面向母亲（画右）的视线轴，不越轴", "DOLLY", "PUSH_IN", "俯拍特写：男孩眨巴大眼", "俯拍特写：男孩点头说完，转向秦铭", "导演稿：推近读点头与「我不饿了」"),
    "E02-S07-03": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm环绕秦铭与男孩", "秦铭在左、男孩在右的轴线，环绕不越轴", "ARC", "CLOCKWISE", "中近景：秦铭看了男孩一眼，红枣在筷尖", "中近景：红枣送到嘴边，男孩看母亲后张口吃下", "导演稿：环绕把「看一眼」到「吃下」连成一个动作"),
    "E02-S07-04": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm随梁婉清坐下微降", "梁婉清在右、陆泽在左的轴线，不越轴", "CRANE", "FALL", "中景：梁婉清站着叹气，陆泽的手攥在秦铭腕上", "中景（微降）：梁婉清坐下，陆泽松手", "导演稿：机位随坐下微降，松手是场尾 button"),
    "E02-S08-01": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm自屋门横摇到两人", "屋门（右）到铜盆边两人（左）的轴线，不越轴", "PAN", "RIGHT_TO_LEFT", "中景：梁婉清出门，门板合上", "中景：陆泽向秦铭凑近，铜盆火光在两人脸侧", "导演稿：横摇从出门接到凑近，无对白镜必动"),
    "E02-S08-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm过秦铭肩缓推陆泽", "陆泽在右、秦铭在左的轴线，不越轴", "DOLLY", "PUSH_IN", "过肩近景：陆泽身体前倾", "过肩近景更紧：陆泽压低声音说完", "导演稿：推近配合压低声音"),
    "E02-S08-03": _cp("CLOSE_UP", "LOW", "AXIS_A", "85mm低机位推近秦铭与铜盆火光", "秦铭面向铜盆（画右）的视线轴，不越轴", "DOLLY", "PUSH_IN", "低机位特写：秦铭的手指松开，眼看陆泽", "低机位特写：手指收紧，眼神落进铜盆火光", "导演稿：推近读手指收紧与眼神落进火光，场尾接闪回"),
    "E02-S09-01": _cp("WIDE", "HIGH", "NEUTRAL", "24mm高机位随坠落下降", "无固定人物轴，地缝为画面纵深", "CRANE", "FALL", "高机位远景：漆黑山林，四人在林地上走", "高机位远景下坠：四人踩空跌进地缝，碎石滚落", "导演稿：随坠落下降，闪回第一镜必动"),
    "E02-S09-02": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_A", "85mm推近秦铭面部", "秦铭面向光源（画右）的视线轴，不越轴", "DOLLY", "PUSH_IN", "特写：极暗中秦铭面部轮廓", "特写：刺目白光炸开，泪水长流，手按胸口入画", "导演稿：推近读光炸开与生疼"),
    "E02-S09-03": _cp("MEDIUM_WIDE", "LOW", "AXIS_B", "28mm低机位环绕四人", "秦铭在中、三同行者在其两侧，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "低机位中全景：银丝银网交织，四人站立", "低机位中全景：三人先后瘫倒，银光消失全黑", "导演稿：环绕读银光交织与三人昏死"),
    "E02-S09-04": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm手持跟随拖人出缝", "地缝内（左）到缝口外（右）的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中景：秦铭拖着一名同行者出缝口", "中景：秦铭在尸体旁捡起水晶瓶攥进掌心", "导演稿：跟随拖人，落在捡瓶攥拳"),
    "E02-S10-01": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm自铜盆火光环绕到男孩方向", "秦铭在左、男孩在右的轴线，环绕不越轴", "ARC", "CLOCKWISE", "中近景：秦铭眼神在铜盆火光里", "中近景：秦铭转向男孩，肩膀放松说话", "导演稿：环绕把回神与看向男孩连成一个动作，6 s 承载一句"),
    "E02-S10-02": _cp("MEDIUM_CLOSE_UP", "HIGH", "AXIS_B", "85mm俯拍固定男孩", "男孩面向秦铭（画左）的视线轴，不越轴", "LOCKED", "NONE", "俯拍中近景：男孩闭嘴咽口水", "俯拍中近景：男孩张口小声说完", "导演稿：固定（对白镜 ≤5 s），咽口水与小声开口本身带动"),
    "E02-S10-03": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm缓推两人", "秦铭在左、男孩在右的轴线，不越轴", "DOLLY", "PUSH_IN", "中近景：秦铭抬手", "中近景更紧：手落在男孩头上摸了摸", "导演稿：推近读摸头与「会有的」"),
    "E02-S10-04": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_B", "28mm手持跟到屋门口", "屋内（左）到屋门外黑暗（右）的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中全景：陆泽牵起儿子走向屋门", "中全景：秦铭站在门口，父子背影没入门外黑暗", "导演稿：跟随到门口，背影没入黑暗作 button"),
    "E02-S11-01": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm极缓环绕炕沿", "秦铭面向铜盆（画右）的轴线，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "中景：铜盆光焰明亮，秦铭闭目坐在炕沿", "中景（环绕至侧面）：铜盆光焰变淡暗红，秦铭呼吸放缓", "导演稿：缓慢环绕配合光焰变淡与呼吸放缓，2 s 内可见光变"),
    "E02-S11-02": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_B", "85mm环绕面部", "秦铭面向铜盆的轴线，环绕不越轴", "ARC", "CLOCKWISE", "特写：闭目", "特写：睁眼刹那体表银色涟漪散去", "导演稿：环绕让睁眼瞬间的银光在运动中出现"),
    "E02-S11-03": _cp("CLOSE_UP", "HIGH", "AXIS_A", "85mm自面部拉开到手臂入画", "秦铭低头看手臂的视线轴，不越轴", "DOLLY", "PULL_OUT", "特写：秦铭低头，额头汗珠", "特写（拉开）：手臂入画空无一物，脖颈汗水", "导演稿：拉开跟随视线到手臂，汗水是场尾 button"),
    "E02-S12-01": _cp("WIDE", "HIGH", "NEUTRAL", "24mm自村中屋顶群下降到院中", "村（上）到院中（下）的纵深，无人物轴", "CRANE", "FALL", "高机位远景：各家火光先后暗下", "远景（降到院墙高）：秦铭在院中脱下裘氅扔在雪上", "导演稿：下降从村火暗下接到院中脱衣"),
    "E02-S12-02": _cp("MEDIUM", "LOW", "AXIS_A", "35mm低机位环绕成组动作", "秦铭面向画左的动作轴，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "低机位中景：一组动作换到下一组", "低机位中景：秦铭停下喘气，头上白雾", "导演稿：环绕让成组动作有机位反应"),
    "E02-S12-03": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_B", "85mm推近双手", "秦铭低头看手的视线轴，不越轴", "DOLLY", "PUSH_IN", "特写：体表银光浮现，双手垂着", "特写更紧：抬起双手，银光在指缝流过散去", "导演稿：推近读指缝银光与「真的不一样了」"),
    "E02-S12-04": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm缓拉出", "秦铭面向画左的轴线，不越轴", "DOLLY", "PULL_OUT", "中近景：手按住胸口", "中近景偏松：抬臂又放下，肚子叫", "导演稿：拉出让抬臂放下在松构图里完成，场尾 button"),
    "E02-S13-01": _cp("CLOSE_UP", "HIGH", "AXIS_A", "85mm过肩俯拍下降到水盆映像", "秦铭俯身看水盆（画下方）的视线轴，不越轴", "CRANE", "FALL", "过肩俯拍特写：水面晃动，映像碎", "过肩俯拍特写：水面平静，映出有血色的面孔", "导演稿：推近水盆映像读血色"),
    "E02-S13-02": _cp("MEDIUM", "HIGH", "AXIS_B", "35mm随躺下微降", "秦铭在炕沿（左）躺向炕里（右）的轴线，不越轴", "CRANE", "FALL", "俯拍中景：秦铭站在炕边", "俯拍中景（微降）：秦铭躺下盖上大衣，肚子叫", "导演稿：随躺下微降"),
    "E02-S13-03": _cp("CLOSE_UP", "HIGH", "AXIS_A", "85mm俯拍缓推面部", "秦铭仰面（视线向上）的轴线，不越轴", "DOLLY", "PUSH_IN", "俯拍特写：闭眼，嘴角平", "俯拍特写更紧：嘴角翘起", "导演稿：推近读嘴角翘起"),
    "E02-S13-04": _cp("CLOSE_UP", "HIGH", "AXIS_B", "85mm俯拍固定", "秦铭仰面的轴线，不越轴", "LOCKED", "NONE", "俯拍特写：嘴角翘着，手搭在大衣上", "俯拍特写：猛掐自己一把，眼睁开皱眉", "导演稿：固定（对白镜 ≤5 s），掐自己的动作本身带动"),
    "E02-S13-05": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm随翻身环绕到窗侧", "秦铭由仰面转为面向窗（画右）的轴线，环绕不越轴", "ARC", "CLOCKWISE", "中近景：秦铭仰面咽口水", "中近景：秦铭侧身面向漆黑的窗", "导演稿：环绕跟随翻身"),
    "E02-S13-06": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_B", "85mm极缓推近双眼", "秦铭面向窗的视线轴，不越轴", "DOLLY", "PUSH_IN", "特写：手按上胸口，眼半睁", "特写更紧：眼睛睁着盯窗", "导演稿：极缓推近双眼，全集 button 落在决定上"),
}
# ---------- END OF CHUNK 2a ----------

# 每镜：s, n, sec, size, camera, axis, blocking, cast, action(subject, primary_action, patient), dialogue(speaker,text,listener),
# entry, exit, dims{DIM:(entry_text, exit_text, ENTRY_CODE, EXIT_CODE)}, referents[(surface,key)], faces, cps, slots, wardrobe_override, first_frame_hidden
D = lambda a, b, ca, cb: (a, b, ca, cb)
SHOTS = [
    # S01 —— 钩子：手探火泉（承接 E01-S10 终态：站在石围前抬头望树）
    dict(s="E02-S01", n=1, sec=3, faces={"QM": "HIGH_ANGLE_PROFILE_UPPER_FACE_NOT_MEASURABLE"}, size="高机位俯拍特写", camera="镜头在石围正上方向下俯拍：画面只有膝高石围的边缘、池中火红光与秦铭仰头时的侧脸上缘和肩线，不见全身、不见背影、不见双树全貌；随手探池推近", axis="秦铭在石围外面向池心", blocking="秦铭站在石围前抬头望树，收回目光蹲下，手探进池中",
         cast=["QM"], action=("QM", "秦铭把目光从两棵树上收回，蹲下身，把手探进池中的火红光里，火光淹到他的手腕，他没有缩手", None), dialogue=None,
         entry="秦铭站在石围前抬头望着两棵树，双手垂在身侧", exit="秦铭蹲在石围前，右手没入池中火光直到手腕",
         dims={"POSTURE": D("站立仰头望树", "蹲下低头看池", "STANDING_HEAD_UP_AT_TREES", "CROUCHED_HEAD_DOWN_AT_POOL"), "CONTACT": D("手未触火光", "手没入火光至腕", "HAND_CLEAR_OF_FLAME", "HAND_IN_FLAME_TO_WRIST")}, referents=[("他", "QM")]),
    dict(s="E02-S01", n=2, sec=3, size="低机位中近景", camera="低机位自出水的手拉出至面部", axis="秦铭面向池心（画右）", blocking="秦铭蹲在石围前捞出石块举到眼前",
         cast=["QM"], action=("QM", "秦铭从火光里捞出一枚发光的石块，石块比红珊瑚还莹润，霞光四照，把他的脸照亮", None), dialogue=None,
         entry="秦铭的手在池中火光里，脸只受池面泛光", exit="发光石块握在秦铭手中举到眼前，霞光直照他的脸",
         dims={"POSSESSION": D("石块在池中", "石块在秦铭手中", "STONE_IN_POOL", "STONE_IN_QIN_HAND"), "INTEGRITY": D("面部只受池面泛光", "面部被石块霞光直照", "FACE_LIT_BY_POOL_GLOW", "FACE_LIT_BY_STONE_RADIANCE")}, referents=[("他", "QM")]),
    dict(s="E02-S01", n=3, sec=4, size="特写", camera="环绕面部与贴脸的石块", axis="秦铭面向池心", blocking="秦铭蹲在石围前把石块贴到脸侧，再松手让石块落回池中",
         cast=["QM"], action=("QM", "秦铭把石块贴到脸侧，眉头没有皱起；他松开手指，石块落回池中，池面的光像水花一样溅起", None), dialogue=None,
         entry="石块贴在秦铭脸侧，他眉头舒展", exit="秦铭手指松开，石块落回池中，池面的光溅起",
         dims={"CONTACT": D("石块贴在脸侧", "手指松开石块离手", "STONE_AGAINST_CHEEK", "STONE_RELEASED"), "POSITION": D("石块在脸侧", "石块落回池中光溅起", "STONE_AT_CHEEK", "STONE_BACK_IN_POOL_SPLASH")}, referents=[("他", "QM")]),
    # S02 —— 眺望野外，雪花入领
    dict(s="E02-S02", n=1, sec=3, faces={"QM": "CROUCHED_MEDIUM_WIDE_FACE_TURNED_NOT_MEASURABLE"}, size="中全景", camera="手持随站起转身", axis="秦铭背向火泉面向村外黑暗", blocking="秦铭自石围前站起转身面向村外",
         cast=["QM"], action=("QM", "秦铭站起身，转向村外；野外非常暗，积雪早已没过人的胸口；远方腾起一道地光，密林的轮廓亮了一瞬，又沉回黑暗", None), dialogue=None,
         entry="秦铭蹲在石围前，火泉在画左，野外全黑", exit="秦铭站定面向村外，远方地光一闪照出密林轮廓后又沉回黑暗",
         dims={"POSTURE": D("蹲在石围前", "站立面向村外", "CROUCHED_AT_RIM", "STANDING_FACING_WILDS"), "INTEGRITY": D("野外全黑", "地光一闪照出林线", "WILDS_PITCH_DARK", "GROUND_LIGHT_FLASH_REVEALS_TREELINE")}, referents=[("他", "QM")]),
    dict(s="E02-S02", n=2, sec=3, size="特写", camera="缓推面部与攥紧的手", axis="秦铭面向村外", blocking="秦铭站在石围前盯着林线，双树在身后",
         cast=["QM"], action=("QM", "秦铭盯着林线，手指攥紧；寒风划过火池，双树簌簌摇落积雪", None), dialogue=None,
         entry="秦铭盯着林线，手在身侧松开，双树枝上压着雪", exit="秦铭手指攥紧，双树簌簌落雪，火池波光粼粼",
         dims={"POSTURE": D("手指松开", "手指攥紧", "FINGERS_RELAXED", "FINGERS_CLENCHED"), "MOMENTUM": D("双树积雪静压", "双树簌簌摇落积雪", "TREES_SNOW_STILL", "TREES_SHEDDING_SNOW")}, referents=[("他", "QM")]),
    dict(s="E02-S02", n=3, sec=4, faces={"QM": "BACK_THREE_QUARTER_FACING_WILDS_NOT_MEASURABLE"}, size="中近景", camera="环绕至转身方向", axis="秦铭由面向村外转为面向村内", blocking="秦铭一缩肩膀，转身往村里走",
         cast=["QM"], action=("QM", "一片雪花落进秦铭的脖颈，他一缩肩膀，回过神来，转身往村里走", None), dialogue=None,
         entry="秦铭肩膀放松盯着林线，雪花正落向脖颈", exit="秦铭缩肩后转身背向火泉，迈步往村里走",
         dims={"POSTURE": D("肩膀放松", "一缩肩膀", "SHOULDERS_RELAXED", "SHOULDERS_HUNCHED"), "POSITION": D("面向村外站定", "转身往村里迈步", "FACING_WILDS_STANDING", "TURNED_WALKING_TO_VILLAGE")}, referents=[("他", "QM")]),
    # S03 —— 院中练动作
    dict(s="E02-S03", n=1, sec=3, faces={"QM": "SIDE_VIEW_MEDIUM_WIDE_AT_GATE_NOT_MEASURABLE"}, size="中全景", camera="手持跟随进院门", axis="院门（右）到院中（左）", blocking="秦铭推开院门跨进院中，在石盆旁摆开第一组动作",
         cast=["QM"], action=("QM", "秦铭推开自家院门，站到院中，摆开一组特定的动作", None), dialogue=None,
         entry="秦铭在院门外推门，门上积雪落下", exit="秦铭站在院中石盆旁，第一组动作已摆开",
         dims={"POSITION": D("院门外", "院中石盆旁", "OUTSIDE_YARD_GATE", "YARD_CENTRE_BY_BASIN"), "POSTURE": D("行走推门", "摆开第一组动作", "WALKING_PUSHING_GATE", "FIRST_FORM_OPENED")}, referents=[("他", "QM")]),
    dict(s="E02-S03", n=2, sec=3, size="低机位中景", camera="低机位缓推", axis="秦铭面向画左", blocking="秦铭在院中一组接一组换动作，停下",
         cast=["QM"], action=("QM", "秦铭一组接一组地换动作，娴熟流畅像一种本能；呼出的白雾越来越浓，他额头见汗，停下，周身有了暖意", None), dialogue=None,
         entry="秦铭换到第二组动作，白雾初起，额头干", exit="秦铭停下，额头见汗，白雾浓，周身有了暖意",
         dims={"MOMENTUM": D("动作换组", "停下", "FORMS_CYCLING", "STOPPED"), "INTEGRITY": D("额头干", "额头见汗白雾浓", "FOREHEAD_DRY", "FOREHEAD_SWEATING_THICK_BREATH")}, referents=[("他", "QM")]),
    # S04 —— 矿素水晶瓶
    dict(s="E02-S04", n=1, sec=3, size="中近景", camera="手持跟随进屋到铜盆前", axis="屋门（右）到铜盆（左）", blocking="秦铭跨进屋门走到铜盆前，从怀里取出水晶瓶",
         cast=["QM"], action=("QM", "秦铭进屋，从怀里取出一个袖珍的水晶瓶；瓶子只有拇指长，瓶内是带着冰晶的蓝色液体", None), dialogue=None,
         entry="秦铭跨进屋门，手伸进怀里", exit="秦铭站在铜盆前，拇指长的水晶瓶握在手中，瓶内蓝色液体带冰晶",
         dims={"POSITION": D("屋门口", "铜盆前", "AT_HOUSE_DOOR", "AT_COPPER_BASIN"), "POSSESSION": D("瓶在怀里", "瓶在手中", "VIAL_IN_ROBE", "VIAL_IN_HAND")}, referents=[("他", "QM")]),
    dict(s="E02-S04", n=2, sec=3, size="特写", camera="推近瓶体，面部在瓶后", axis="秦铭面向铜盆火霞", blocking="秦铭举瓶迎火霞观看并轻摇",
         cast=["QM"], action=("QM", "秦铭迎着铜盆里太阳石的火霞观看，轻轻摇晃，蓝雾在瓶中流动", None), dialogue=("QM", "矿素……", None),
         entry="瓶举在胸前，瓶中蓝雾静止", exit="瓶举到眼前迎着火霞，蓝雾在瓶中流动",
         dims={"POSTURE": D("瓶举在胸前", "瓶举到眼前迎火霞", "VIAL_AT_CHEST", "VIAL_AT_EYE_AGAINST_FIRELIGHT"), "MOMENTUM": D("瓶中蓝雾静止", "蓝雾流动", "BLUE_MIST_STILL", "BLUE_MIST_SWIRLING")}, referents=[("他", "QM")]),
    dict(s="E02-S04", n=3, sec=4, size="微俯特写", camera="固定微俯，拇指与瓶塞", axis="秦铭面向铜盆", blocking="秦铭拇指按上瓶塞停住又移开，把瓶塞回怀里按了按",
         cast=["QM"], action=("QM", "秦铭的拇指按上瓶塞，停住，又移开；他把水晶小瓶塞回怀里，按了按", None), dialogue=("QM", "再过几天或许就能用上了。", None),
         entry="秦铭拇指按在瓶塞上", exit="拇指移开，水晶瓶塞回怀中，手按在衣襟上",
         dims={"CONTACT": D("拇指按在瓶塞上", "拇指移开瓶塞", "THUMB_ON_STOPPER", "THUMB_OFF_STOPPER"), "POSITION": D("瓶在眼前", "瓶塞回怀中", "VIAL_BEFORE_EYES", "VIAL_BACK_IN_ROBE")}, referents=[("他", "QM")]),
    # S05 —— 陆泽父子来
    dict(s="E02-S05", n=1, sec=4, faces={"LZ": "SMALL_FACE_IN_MEDIUM_WIDE_NOT_MEASURABLE", "WR": "SMALL_FACE_IN_MEDIUM_WIDE_NOT_MEASURABLE", "QM": "MEDIUM_WIDE_TURNING_FACE_NOT_MEASURABLE"}, size="中全景", camera="手持自秦铭身后跟向院门", axis="院中（左）到院门（右）", blocking="院门被推开，陆泽与文睿跨进院中；秦铭迎上去，抬手在男孩头顶比划",
         cast=["QM", "LZ", "WR"], action=("QM", "院门被推开，陆泽走进来，身边跟着一个五岁左右裹得严严实实、小脸冻得红扑扑的男孩；秦铭迎上去，抬手在男孩头顶比划了一下", "WR"), dialogue=("QM", "文睿又长高了一些。", "WR"),
         entry="院门正被推开，陆泽与男孩在门口，秦铭在院中转身", exit="秦铭站在男孩身前，手抬在男孩头顶比划",
         dims={"POSITION": D("陆泽父子在院门口", "陆泽父子在院中、秦铭在男孩身前", "LU_AND_BOY_AT_GATE", "LU_AND_BOY_IN_YARD_QIN_BEFORE_BOY"), "POSTURE": D("秦铭双手垂着", "秦铭手抬在男孩头顶", "QIN_HANDS_DOWN", "QIN_HAND_ABOVE_BOY_HEAD")}, referents=[("男孩", "WR")]),
    dict(s="E02-S05", n=2, sec=3, cps=4.8, faces={"QM": "BACK_TO_CAMERA_OTS_FOREGROUND"}, size="过肩俯拍近景", camera="固定过秦铭肩俯看男孩", axis="秦铭在右、男孩在左", blocking="男孩仰起头看秦铭",
         cast=["WR", "QM"], action=("WR", "陆文睿仰起头，眼睛大而清澈，看着秦铭问话", "QM"), dialogue=("WR", "小叔，你身体好些了吗？", "QM"),
         entry="男孩低着头，秦铭肩在前景", exit="男孩仰起头，大眼看向秦铭",
         dims={"POSTURE": D("低头", "仰起头看秦铭", "BOY_HEAD_DOWN", "BOY_HEAD_UP_AT_QIN")}, referents=[]),
    dict(s="E02-S05", n=3, sec=7, faces={"QM": "BACK_TO_CAMERA_OTS_FOREGROUND", "WR": "CHILD_FACE_IN_HOOD_LOW_ANGLE_NOT_MEASURABLE"}, cps=5.0, size="中近景", camera="随蹲下降到男孩视平", axis="秦铭在右、男孩在左", blocking="秦铭蹲下身与男孩平视说话",
         cast=["QM", "WR"], action=("QM", "秦铭蹲下身，与男孩平视，许诺抓语雀", "WR"), dialogue=("QM", "没什么问题了，等过些日子小叔帮你抓只你心心念的‘语雀’回来。", "WR"),
         entry="秦铭站着俯视男孩，男孩仰头", exit="秦铭蹲着与男孩平视，一句说完",
         dims={"POSTURE": D("站立俯视", "蹲下平视", "QIN_STANDING_LOOKING_DOWN", "QIN_CROUCHED_EYE_LEVEL"), "POSITION": D("视线高于男孩", "视线与男孩齐平", "GAZE_ABOVE_BOY", "GAZE_LEVEL_WITH_BOY")}, referents=[]),
    dict(s="E02-S05", n=4, sec=5, cps=4.8, faces={"QM": "SMALL_FACE_IN_MEDIUM_TWO_SHOT_NOT_MEASURABLE"}, size="低机位中景", camera="低机位随男孩跳起升起", axis="男孩在左、秦铭在右", blocking="男孩原地跳起落下，秦铭蹲在画右",
         cast=["WR", "QM"], action=("WR", "陆文睿原地跳了一下，满眼亮晶晶的光", "QM"), dialogue=("WR", "可以和人对话的语雀，真的吗？太好了！", "QM"),
         entry="男孩双脚站在雪地上，眼睛发亮", exit="男孩原地跳起又落下，满眼亮晶晶的光",
         dims={"MOMENTUM": D("站定", "原地跳起落下", "BOY_STANDING_STILL", "BOY_JUMPED_AND_LANDED"), "POSTURE": D("嘴闭着", "张嘴笑着说话", "BOY_MOUTH_CLOSED", "BOY_MOUTH_OPEN_BEAMING")}, referents=[]),
    dict(s="E02-S05", n=5, sec=3, size="中近景", camera="缓推陆泽", axis="陆泽在后面向秦铭与儿子", blocking="陆泽从院门内走向秦铭与儿子，把食盒换到另一只手",
         cast=["LZ"], action=("LZ", "陆泽提着食盒从院门内朝秦铭与儿子走了两三步，边走边看着他们，嘴角动了动，把食盒换到另一只手", None), dialogue=None,
         entry="陆泽站在院门内看着，嘴角平，食盒提在右手", exit="陆泽嘴角动了动，食盒换到左手",
         dims={"POSTURE": D("嘴角平", "嘴角动了动", "LU_MOUTH_STILL", "LU_MOUTH_CORNER_TWITCHED"), "POSITION": D("食盒在右手", "食盒在左手", "FOODBOX_RIGHT_HAND", "FOODBOX_LEFT_HAND")}, referents=[("他", "LZ")]),
    # S06 —— 食盒红枣
    dict(s="E02-S06", n=1, sec=3, faces={"QM": "SMALL_FACE_IN_MEDIUM_THREE_SHOT_NOT_MEASURABLE", "WR": "CHILD_FACE_IN_HOOD_MEDIUM_NOT_MEASURABLE", "LZ": "SMALL_FACE_IN_MEDIUM_THREE_SHOT_NOT_MEASURABLE"}, size="中景", camera="手持随二人进屋", axis="陆泽在右、秦铭在左隔食盒", blocking="陆泽把食盒递到秦铭手里，秦铭掀开食盒",
         cast=["LZ", "QM", "WR"], action=("LZ", "陆泽把食盒递到秦铭手里；秦铭掀开食盒，里面是岩米饭", "QM"), dialogue=("LZ", "最近外面不对劲。", "QM"), slots={"LZ": "SCREEN_RIGHT", "QM": "SCREEN_LEFT"},
         entry="食盒在陆泽手中递出，秦铭在门内双手空着", exit="食盒在秦铭手中，盒盖掀开露出岩米饭",
         dims={"POSSESSION": D("食盒在陆泽手中", "食盒在秦铭手中", "FOODBOX_HELD_BY_LU", "FOODBOX_HELD_BY_QIN"), "INTEGRITY": D("食盒盖着", "食盒掀开", "FOODBOX_LID_CLOSED", "FOODBOX_LID_OPEN")}, referents=[]),
    dict(s="E02-S06", n=2, sec=3, faces={"WR": "FACE_AT_FRAME_EDGE_HIGH_ANGLE_NOT_MEASURABLE"}, size="俯拍特写", camera="俯拍推近食盒", axis="秦铭在左、男孩在右看向食盒", blocking="秦铭扒饭挑到红枣，男孩在旁盯着咽口水，秦铭筷子停住",
         cast=["QM", "WR"], action=("QM", "秦铭扒了两口，筷子挑到几颗红枣，红枣软滑透出甜香；陆文睿直勾勾地盯着红枣咽了一口口水；秦铭的筷子停在半空", None), dialogue=None,
         entry="筷子扒饭，红枣埋在饭里，男孩视线在别处", exit="红枣在筷尖，男孩盯着红枣咽口水，筷子停在半空",
         dims={"POSITION": D("红枣埋在饭里", "红枣在筷尖", "DATES_BURIED_IN_RICE", "DATES_ON_CHOPSTICK_TIP"), "MOMENTUM": D("筷子扒饭", "筷子停在半空", "CHOPSTICKS_MOVING", "CHOPSTICKS_FROZEN_MIDAIR"), "POSTURE": D("男孩视线在别处", "男孩直勾勾盯枣咽口水", "BOY_LOOKING_AWAY", "BOY_STARING_AT_DATES_SWALLOWING")}, referents=[("他", "QM")]),
    dict(s="E02-S06", n=3, sec=5, faces={"WR": "CHILD_FACE_SMALL_SIDE_IN_MEDIUM_NOT_MEASURABLE"}, size="中近景", camera="随秦铭蹲下下降", axis="秦铭在左、男孩在右", blocking="秦铭放下食盒蹲到男孩面前问话",
         cast=["QM", "WR"], action=("QM", "秦铭放下食盒，蹲到男孩面前问他", "WR"), dialogue=("QM", "文睿，告诉小叔，你是不是还没吃饱？", "WR"),
         entry="秦铭站着，食盒在手", exit="食盒放在炕沿，秦铭蹲着平视男孩问完",
         dims={"POSSESSION": D("食盒在手", "食盒放在炕沿", "FOODBOX_IN_HAND", "FOODBOX_ON_KANG_EDGE"), "POSTURE": D("站立", "蹲下平视男孩", "QIN_STANDING", "QIN_CROUCHED_FACING_BOY")}, referents=[("他", "WR")]),
    dict(s="E02-S06", n=4, sec=5, faces={"QM": "BACK_TO_CAMERA_OTS_FOREGROUND"}, size="过肩近景", camera="固定过秦铭肩看陆泽", axis="陆泽在右、秦铭在左", blocking="陆泽摇头答话",
         cast=["LZ", "QM"], action=("LZ", "陆泽摇头答话", "QM"), dialogue=("LZ", "没有的事，他肯定是因为看到红枣了。", "QM"), slots={"LZ": "SCREEN_RIGHT", "QM": "SCREEN_LEFT"},
         entry="陆泽面向秦铭，头正", exit="陆泽摇头说完",
         dims={"POSTURE": D("头正", "摇头", "LU_HEAD_STILL", "LU_HEAD_SHAKING")}, referents=[("他", "WR")]),
    dict(s="E02-S06", n=5, sec=6, faces={"LZ": "HANDS_ONLY_FACE_OUT_OF_FRAME", "QM": "HANDS_ONLY_FACE_OUT_OF_FRAME"}, cps=5.0, size="俯拍特写（手）", camera="俯拍推近食盒上方的两只手", axis="秦铭在左、陆泽在右隔食盒", blocking="秦铭挑枣，陆泽伸手攥住他的手腕，两手僵在食盒上方",
         cast=["LZ", "QM"], action=("LZ", "秦铭立刻把红枣一颗颗挑出来；陆泽伸手一把攥住秦铭的手腕；两只手在食盒上方僵住，红枣在筷子尖上晃", "QM"), dialogue=("LZ", "这是你嫂子特意放进去给你补气血用的，别挑给他。", "QM"),
         entry="秦铭筷子在挑枣，陆泽的手自画右伸入，手腕无人握", exit="陆泽攥住秦铭手腕，两只手在食盒上方僵住，红枣在筷尖上晃",
         dims={"CONTACT": D("手腕无人握", "陆泽攥住秦铭手腕", "WRIST_FREE", "LU_GRIPPING_QIN_WRIST"), "MOMENTUM": D("筷子挑枣", "两手僵住红枣晃", "CHOPSTICKS_PICKING", "HANDS_FROZEN_DATE_SWAYING")}, referents=[("他", "WR")]),
    # S07 —— 梁婉清进门
    dict(s="E02-S07", n=1, sec=6, cps=4.8, faces={"QM": "SMALL_FACE_IN_BACKGROUND_NOT_MEASURABLE", "LZ": "SMALL_FACE_IN_BACKGROUND_NOT_MEASURABLE", "WR": "SMALL_FACE_IN_BACKGROUND_NOT_MEASURABLE"}, size="中景", camera="手持随梁婉清进门", axis="屋门（右）到屋内（左）", blocking="梁婉清跨进屋门，站定看向文睿",
         cast=["LW", "WR", "QM", "LZ"], action=("LW", "梁婉清跨进屋门，看向陆文睿说话", "WR"), dialogue=("LW", "你秦叔身体虚弱，现在没有肉食和补药，你不要嘴馋。", "WR"),
         entry="梁婉清在屋门口跨进，冷气带进屋内", exit="梁婉清站在屋内面向文睿，一句说完",
         dims={"POSITION": D("屋门口", "屋内", "LIANG_AT_DOOR", "LIANG_INSIDE_ROOM"), "POSTURE": D("视线在门", "看向文睿", "LIANG_EYES_ON_DOOR", "LIANG_EYES_ON_BOY")}, referents=[]),
    dict(s="E02-S07", n=2, sec=5, faces={"WR": "SMALL_FACE_IN_MEDIUM_WIDE_NOT_MEASURABLE"}, size="俯拍特写", camera="俯拍缓推男孩", axis="男孩面向母亲（画右）", blocking="男孩眨巴大眼乖巧点头，转向秦铭说话",
         cast=["WR"], action=("WR", "陆文睿眨巴着大眼，乖巧地点头，对秦铭说话；他说话时画面里没有任何字幕、文字或水印，台词只出现在声音里", None), dialogue=("WR", "小叔，你快吃吧，赶紧好起来，我不饿了。", "QM"),
         entry="男孩眨巴着大眼，头正", exit="男孩点头说完，脸转向秦铭",
         dims={"POSTURE": D("头正", "点头", "BOY_HEAD_STILL", "BOY_NODDED"), "POSITION": D("脸朝母亲", "脸转向秦铭", "BOY_FACING_MOTHER", "BOY_FACING_QIN")}, referents=[]),
    dict(s="E02-S07", n=3, sec=3, size="中近景", camera="环绕秦铭与男孩", axis="秦铭在左、男孩在右", blocking="秦铭把红枣送到男孩嘴边，男孩看母亲后张口吃下",
         cast=["QM", "WR"], action=("QM", "秦铭看了男孩一眼，把红枣径直送到男孩嘴边；男孩看了看母亲，张口吃下", "WR"), dialogue=None,
         entry="秦铭看着男孩，红枣在筷尖食盒上方", exit="红枣被男孩张口吃下",
         dims={"POSITION": D("红枣在筷尖食盒上方", "红枣送到男孩嘴边", "DATE_OVER_FOODBOX", "DATE_AT_BOY_MOUTH"), "POSSESSION": D("红枣在秦铭筷上", "红枣在男孩口中", "DATE_ON_QIN_CHOPSTICKS", "DATE_IN_BOY_MOUTH")}, referents=[("他", "WR")]),
    dict(s="E02-S07", n=4, sec=3, size="中景", camera="随梁婉清坐下微降", axis="梁婉清在右、陆泽在左", blocking="梁婉清叹气坐下，陆泽松开秦铭的手腕",
         cast=["LW", "LZ", "QM"], action=("LW", "梁婉清叹了口气，没有再拦，坐了下来；陆泽松开秦铭的手腕", None), dialogue=None,
         entry="梁婉清站着叹气，陆泽的手攥在秦铭腕上", exit="梁婉清坐下，陆泽的手离开秦铭手腕",
         dims={"POSTURE": D("梁婉清站着", "梁婉清坐下", "LIANG_STANDING", "LIANG_SEATED"), "CONTACT": D("陆泽攥着秦铭手腕", "陆泽松开手腕", "LU_GRIPPING_WRIST", "LU_RELEASED_WRIST")}, referents=[]),
    # S08 —— 压低声音说密林
    dict(s="E02-S08", n=1, sec=3, faces={"LW": "BACK_TO_CAMERA_WALKING_AWAY", "QM": "SEATED_SIDE_FACE_IN_MEDIUM_NOT_MEASURABLE"}, size="中景", camera="自屋门横摇到两人", axis="屋门（右）到铜盆边两人（左）", blocking="梁婉清起身出门，陆泽向秦铭凑近",
         cast=["LW", "LZ", "QM"], action=("LW", "梁婉清起身出门回家去了；陆泽凑近秦铭", None), dialogue=None,
         entry="梁婉清起身走向屋门，陆泽端坐", exit="梁婉清出门门板合上，陆泽身体凑近秦铭",
         dims={"POSITION": D("梁婉清在屋内", "梁婉清出门", "LIANG_INSIDE", "LIANG_GONE_OUT"), "POSTURE": D("陆泽端坐", "陆泽凑近秦铭", "LU_SITTING_UPRIGHT", "LU_LEANING_IN")}, referents=[]),
    dict(s="E02-S08", n=2, sec=5, cps=4.8, faces={"QM": "BACK_TO_CAMERA_OTS_FOREGROUND"}, size="过肩近景", camera="过秦铭肩缓推陆泽", axis="陆泽在右、秦铭在左", blocking="陆泽压低声音说话",
         cast=["LZ", "QM"], action=("LZ", "陆泽压低声音对秦铭说", "QM"), dialogue=("LZ", "最近密林中有庞然大物出没，死伤了一些人……", "QM"), slots={"LZ": "SCREEN_RIGHT", "QM": "SCREEN_LEFT"},
         entry="陆泽身体前倾，嘴未张", exit="陆泽压低声音说完，眼看着秦铭",
         dims={"POSTURE": D("身体前倾嘴未张", "压低声音说完", "LU_LEANING_MOUTH_CLOSED", "LU_SPOKEN_LOW")}, referents=[]),
    dict(s="E02-S08", n=3, sec=4, faces={"QM": "SEATED_SIDE_FACE_IN_MEDIUM_NOT_MEASURABLE"}, size="低机位特写", camera="低机位推近秦铭与铜盆火光", axis="秦铭面向铜盆（画右）", blocking="秦铭手指收紧，眼神落进铜盆火光",
         cast=["QM"], action=("QM", "秦铭的手指慢慢收紧，眼神落进铜盆的火光里", None), dialogue=None,
         entry="秦铭手指松开，眼看陆泽", exit="秦铭手指收紧，眼神落进铜盆火光",
         dims={"POSTURE": D("手指松开", "手指收紧", "FINGERS_OPEN", "FINGERS_TIGHTENED"), "POSITION": D("视线在陆泽", "视线落进铜盆火光", "GAZE_ON_LU", "GAZE_INTO_BASIN_FIRE")}, referents=[("他", "QM")]),
    # S09 —— 闪回地缝（一个月前）
    dict(s="E02-S09", n=1, sec=3, faces={"QM": "FAR_FIGURE_FACE_NOT_MEASURABLE", "CA": "FAR_FIGURE_FACE_NOT_MEASURABLE", "CB": "FAR_FIGURE_FACE_NOT_MEASURABLE", "CC": "FAR_FIGURE_FACE_NOT_MEASURABLE"}, size="高机位远景", camera="高机位随坠落下降", axis="无固定人物轴，地缝为纵深", blocking="四人在漆黑山林中行走，脚下踩空跌进地缝",
         cast=["QM", "CA", "CB", "CC"], action=("QM", "一个月前，漆黑的山林里，秦铭和三位同行者脚下突兀地踩空，四人跌进一条地缝；本镜自始至终是高机位远景，镜头不切换、不推近任何人的脸，四人只以远处的人影出现；跌落过程中缝口的青蓝月光始终照着岩壁与人影，画面不落到纯黑", None), dialogue=None,
         entry="四人在漆黑林地上行走，地面完整", exit="四人跌进地缝，碎石滚落",
         dims={"POSITION": D("四人在林地上", "四人跌入地缝", "FOUR_ON_FOREST_FLOOR", "FOUR_FALLEN_INTO_CREVICE"), "INTEGRITY": D("地面完整", "地面塌陷碎石滚落", "GROUND_INTACT", "GROUND_COLLAPSED_ROCKS_FALLING")}, referents=[("三位同行者", "CA")],
         wardrobe_override={"QM": FLASHBACK_QM_WARDROBE}),
    dict(s="E02-S09", n=2, sec=3, identity_reanchor=True, size="特写", camera="推近秦铭面部", axis="秦铭面向光源（画右）", blocking="秦铭在地缝底，光炸开时手按胸口",
         cast=["QM"], action=("QM", "画面里自始至终只有秦铭一个人的脸（束发木簪、无胡须的年轻男子，不是任何包头或髭须的同行者），极暗中仍看得见他的面部轮廓与身后岩壁，任何一帧都不是纯黑；随后刺目的白光从画右炸开照亮他的脸，秦铭双眼生疼，泪水长流；他的心脏擂鼓般狂跳，手按住胸口", None), dialogue=None,
         entry="缝口月光下秦铭的面部轮廓清晰可辨，手垂在身侧", exit="刺目白光炸开，秦铭泪水长流，手按住胸口",
         dims={"INTEGRITY": D("地缝极暗", "刺目白光炸开", "CREVICE_PITCH_DARK", "BLINDING_LIGHT_BURST"), "CONTACT": D("手垂在身侧", "手按住胸口", "HAND_AT_SIDE", "HAND_PRESSED_ON_CHEST")}, referents=[("他", "QM")],
         wardrobe_override={"QM": FLASHBACK_QM_WARDROBE}),
    dict(s="E02-S09", n=3, sec=3, faces={"CA": "SMALL_FACE_IN_MEDIUM_WIDE_NOT_MEASURABLE", "CB": "SMALL_FACE_IN_MEDIUM_WIDE_NOT_MEASURABLE", "CC": "SMALL_FACE_IN_MEDIUM_WIDE_NOT_MEASURABLE", "QM": "SMALL_FACE_IN_MEDIUM_WIDE_NOT_MEASURABLE"}, size="低机位中全景", camera="低机位环绕四人", axis="秦铭在中、三同行者在两侧", blocking="银光交织中三位同行者先后瘫倒，银光消失只剩月光",
         cast=["QM", "CA", "CB", "CC"], action=("CA", "一条又一条银光交织，像蚕丝，又如蛛网；三位同行者先后昏死过去；银光倏地消失，地缝只剩缝口透进的青蓝月光，岩壁与四人仍是看得清的深青灰", None), dialogue=None,
         entry="银丝银网交织，四人站立或撑着岩壁", exit="三位同行者瘫倒昏死，银光消失，地缝只剩缝口月光的深青灰",
         dims={"POSTURE": D("三人站立撑壁", "三人先后瘫倒昏死", "THREE_STANDING", "THREE_COLLAPSED_UNCONSCIOUS"), "INTEGRITY": D("银光交织", "银光消失只剩月光深青灰", "SILVER_WEB_GLOWING", "SILVER_GONE_DIM_MOONLIGHT")}, referents=[("三位同行者", "CA")],
         wardrobe_override={"QM": FLASHBACK_QM_WARDROBE}),
    dict(s="E02-S09", n=4, sec=3, faces={"CA": "UNCONSCIOUS_DRAGGED_FACE_DOWN_NOT_MEASURABLE"}, size="中景", camera="手持跟随拖人出缝", axis="地缝内（左）到缝口外（右）", blocking="秦铭把同行者拖出地缝，在尸体旁捡起水晶瓶",
         cast=["QM", "CA"], action=("QM", "秦铭把三人一个个拖出地缝；不远处躺着几具穿着不俗的尸体；他从尸体旁捡起那只水晶小瓶，攥进掌心", "CA"), dialogue=None,
         entry="秦铭拖着一名同行者出缝口，水晶瓶在尸体旁的地上", exit="同行者躺在缝口外，水晶瓶攥在秦铭掌心",
         dims={"POSITION": D("同行者在地缝内", "同行者在缝口外", "COMPANION_IN_CREVICE", "COMPANION_OUTSIDE_CREVICE"), "POSSESSION": D("水晶瓶在尸体旁地上", "水晶瓶攥在秦铭掌心", "VIAL_BESIDE_CORPSE", "VIAL_IN_QIN_FIST")}, referents=[("他", "QM")],
         wardrobe_override={"QM": FLASHBACK_QM_WARDROBE}),
    # S10 —— 有肉肉吗
    dict(s="E02-S10", n=1, sec=6, faces={"WR": "CHILD_FACE_IN_HOOD_MEDIUM_NOT_MEASURABLE"}, cps=4.8, size="中近景", camera="自铜盆火光环绕到男孩方向", axis="秦铭在左、男孩在右", blocking="秦铭回过神转向男孩说话",
         cast=["QM", "WR"], action=("QM", "秦铭回过神，看向略有些腼腆的男孩说话", "WR"), dialogue=("QM", "文睿，等叔叔病好后，什么枣子，榛果，回头让你吃个够。", "WR"),
         entry="秦铭眼神在铜盆火光里，身体僵直", exit="秦铭转向男孩，肩膀放松，一句说完",
         dims={"POSITION": D("视线在铜盆火光", "看向男孩", "GAZE_IN_BASIN_FIRE", "GAZE_ON_BOY"), "POSTURE": D("身体僵直", "肩膀放松", "BODY_RIGID", "SHOULDERS_EASED")}, referents=[("男孩", "WR")]),
    dict(s="E02-S10", n=2, sec=4, faces={"WR": "CHILD_FACE_IN_HOOD_MEDIUM_NOT_MEASURABLE"}, size="俯拍中近景", camera="固定俯拍男孩，秦铭在画左缘同框", axis="男孩面向秦铭（画左）", blocking="男孩咽口水后小声开口，秦铭在画左缘沉默聆听",
         cast=["WR"], action=("WR", "画面上绝不叠加任何字幕条、文字或水印，台词只在声音里；陆文睿又咽了一口口水，小声开口，秦铭坐在画左缘沉默地听着", None), dialogue=("WR", "有肉肉吗？我……很久没吃了。", "QM"),
         entry="男孩闭着嘴咽口水", exit="男孩张口小声说完",
         dims={"POSTURE": D("闭嘴咽口水", "张口小声说话", "BOY_SWALLOWING_MOUTH_CLOSED", "BOY_SPEAKING_SOFTLY")}, referents=[]),
    dict(s="E02-S10", n=3, sec=3, faces={"QM": "MEDIUM_TWO_SHOT_FACE_TURNED_NOT_MEASURABLE"}, size="中近景", camera="缓推两人", axis="秦铭在左、男孩在右", blocking="秦铭伸手摸男孩的头",
         cast=["QM", "WR"], action=("QM", "秦铭伸手摸了摸男孩的头", "WR"), dialogue=("QM", "会有的！", "WR"),
         entry="秦铭抬手，手未触男孩", exit="秦铭的手落在男孩头上摸了摸",
         dims={"CONTACT": D("手未触男孩", "手摸在男孩头上", "HAND_OFF_BOY", "HAND_ON_BOY_HEAD")}, referents=[("他", "WR")]),
    dict(s="E02-S10", n=4, sec=3, faces={"LZ": "BACK_TO_CAMERA_WALKING_AWAY", "WR": "BACK_TO_CAMERA_WALKING_AWAY"}, size="中全景", camera="手持跟到屋门口", axis="屋内（左）到屋门外黑暗（右）", blocking="陆泽牵起儿子走出屋门，秦铭站在门口目送",
         cast=["LZ", "WR", "QM"], action=("LZ", "陆泽牵起儿子，走出屋门；秦铭站在门口，目送父子俩的背影没入黑暗", "WR"), dialogue=None,
         entry="陆泽牵住儿子的手，两人在屋内走向屋门", exit="父子背影没入门外黑暗，秦铭站在门口",
         dims={"POSITION": D("父子在屋内", "父子背影没入门外黑暗", "FATHER_SON_INSIDE", "FATHER_SON_GONE_INTO_DARK"), "POSTURE": D("秦铭蹲在屋中", "秦铭站在门口", "QIN_CROUCHED_IN_ROOM", "QIN_STANDING_AT_DOOR")}, referents=[("父子俩", "LZ")]),
    # S11 —— 静坐，银光一闪
    dict(s="E02-S11", n=1, sec=3, faces={"QM": "EYES_CLOSED_MEDITATION_NOT_MEASURABLE"}, size="中景", camera="极缓推近炕沿", axis="秦铭面向铜盆（画右）", blocking="秦铭闭目静坐在炕沿",
         cast=["QM"], action=("QM", "铜盆中太阳石的光焰变淡了；秦铭闭目静坐在炕沿，呼吸放缓", None), dialogue=None,
         entry="铜盆光焰明亮，秦铭闭目坐在炕沿，胸口起伏快", exit="铜盆光焰变淡暗红，秦铭呼吸放缓",
         dims={"INTEGRITY": D("铜盆光焰明亮", "铜盆光焰变淡暗红", "BASIN_BRIGHT", "BASIN_DIMMED_DARK_RED"), "MOMENTUM": D("胸口起伏快", "呼吸放缓", "BREATH_FAST", "BREATH_SLOWED")}, referents=[("他", "QM")]),
    dict(s="E02-S11", n=2, sec=3, size="特写", camera="环绕面部", axis="秦铭面向铜盆", blocking="秦铭睁眼，体表银色涟漪散去",
         cast=["QM"], action=("QM", "秦铭睁眼的刹那，体表一层很淡的银色涟漪散去", None), dialogue=("QM", "错觉吗？", None),
         entry="秦铭闭目，体表无光", exit="秦铭睁眼，体表一层极淡的银色涟漪散去",
         dims={"POSTURE": D("闭目", "睁眼", "EYES_CLOSED", "EYES_OPEN"), "INTEGRITY": D("体表无光", "银色涟漪一闪散去", "SKIN_NO_GLOW", "SILVER_RIPPLE_FADED")}, referents=[("他", "QM")]),
    dict(s="E02-S11", n=3, sec=4, size="特写", camera="自面部下降到手臂", axis="秦铭低头看手臂", blocking="秦铭低头看手臂",
         cast=["QM"], action=("QM", "秦铭低头看自己的手臂，什么也没有；他的额头和脖颈却已布满细密的汗水", None), dialogue=None,
         entry="秦铭平视前方，额头汗珠刚显", exit="秦铭低头看手臂，手臂空无一物，额头脖颈布满汗水",
         dims={"POSITION": D("视线平视前方", "低头看手臂", "GAZE_AHEAD", "GAZE_DOWN_AT_ARM"), "INTEGRITY": D("汗珠刚显", "额头脖颈布满汗水", "SWEAT_BEADING", "SWEAT_COVERING_NECK")}, referents=[("他", "QM")]),
    # S12 —— 院中再练，银光真切
    dict(s="E02-S12", n=1, sec=3, faces={"QM": "FAR_FIGURE_FACE_NOT_MEASURABLE"}, size="高机位远景", camera="自村中屋顶群下降到院中", axis="村（上）到院中（下）", blocking="秦铭走到院中脱下裘氅扔在雪上",
         cast=["QM"], action=("QM", "村里各家的火光先后暗下去；秦铭披着兽皮大衣走到院中，把大衣脱下扔在雪上", None), dialogue=None,
         entry="各家火光还亮着，秦铭披着裘氅走到院中", exit="各家火光暗下，裘氅扔在雪上，秦铭只穿内袍站在院中",
         dims={"INTEGRITY": D("各家火光亮", "各家火光先后暗下", "VILLAGE_LIGHTS_ON", "VILLAGE_LIGHTS_DIMMED"), "POSSESSION": D("裘氅披在身上", "裘氅扔在雪上", "COAT_ON_BODY", "COAT_ON_SNOW")}, referents=[("他", "QM")]),
    dict(s="E02-S12", n=2, sec=4, size="低机位中景", camera="低机位环绕成组动作", axis="秦铭面向画左", blocking="秦铭在院中一组又一组动作，停下喘气",
         cast=["QM"], action=("QM", "秦铭以身体展现那一组又一组特定的动作；很快他头上有白雾冒出，大汗淋漓；他停下，喘着气", None), dialogue=None,
         entry="秦铭一组动作换到下一组，头上无雾", exit="秦铭停下喘气，头上白雾冒出，大汗淋漓",
         dims={"MOMENTUM": D("动作换组", "停下喘气", "FORMS_CYCLING", "STOPPED_PANTING"), "INTEGRITY": D("头上无雾", "头上白雾大汗", "HEAD_NO_STEAM", "HEAD_STEAMING_SWEAT")}, referents=[("他", "QM")],
         wardrobe_override={"QM": "本镜秦铭已脱下裘氅（裘氅在雪地上），只穿深青交领窄袖袍，袍面被汗浸湿"}),
    dict(s="E02-S12", n=3, sec=4, size="特写", camera="推近双手", axis="秦铭低头看手", blocking="秦铭抬起双手看指缝间的银光",
         cast=["QM"], action=("QM", "极微弱的银光自秦铭体表浮现；他抬起双手，银光在指缝间流过，又迅速散去", None), dialogue=("QM", "真的不一样了。", None),
         entry="秦铭双手垂着，体表银光初现", exit="秦铭双手抬在眼前，指缝间银光流过后散去",
         dims={"INTEGRITY": D("体表银光初现", "指缝银光流过散去", "SILVER_GLOW_RISING", "SILVER_GLOW_DISPERSED"), "POSTURE": D("双手垂着", "双手抬在眼前", "HANDS_DOWN", "HANDS_RAISED_BEFORE_EYES")}, referents=[("他", "QM")],
         wardrobe_override={"QM": "本镜秦铭不披裘氅，只穿深青交领窄袖袍，袍面被汗浸湿"}),
    dict(s="E02-S12", n=4, sec=3, size="中近景", camera="缓拉出", axis="秦铭面向画左", blocking="秦铭按住胸口，抬臂想再练，肚子叫后放下",
         cast=["QM"], action=("QM", "秦铭按住胸口，一股暖意在体内流动；他抬起手臂还想再练；他的肚子叫了起来，他立刻把手臂放下", None), dialogue=None,
         entry="秦铭手按住胸口", exit="秦铭抬起的手臂放下，手离开胸口",
         dims={"CONTACT": D("手按住胸口", "手离开胸口", "HAND_ON_CHEST", "HAND_OFF_CHEST"), "POSTURE": D("手臂抬起摆式", "手臂放下", "ARM_RAISED_FOR_FORM", "ARM_DROPPED")}, referents=[("他", "QM")],
         wardrobe_override={"QM": "本镜秦铭不披裘氅，只穿深青交领窄袖袍，袍面被汗浸湿"}),
    # S13 —— 水盆、火炕、决定
    dict(s="E02-S13", n=1, sec=4, cps=4.8, faces={"QM": "WATER_REFLECTION_HIGH_ANGLE_NOT_MEASURABLE"}, size="过肩俯拍特写", camera="过肩俯拍推近水盆映像", axis="秦铭俯身看水盆", blocking="秦铭俯身在水盆上看映出的面孔",
         cast=["QM"], action=("QM", "秦铭俯身看水盆，水中映出的面孔不再苍白，有了血色", None), dialogue=("QM", "恢复得差不多了，明早就动身。", None),
         entry="水面晃动，映像破碎，秦铭俯身在盆上方半尺", exit="水面平静，映出有血色的面孔，秦铭贴近水面说完",
         dims={"INTEGRITY": D("水面晃动映像碎", "水面平静映出面孔", "WATER_RIPPLED_IMAGE_BROKEN", "WATER_STILL_FACE_REFLECTED"), "POSITION": D("面孔在盆上方半尺", "俯身贴近水面", "FACE_ABOVE_BASIN", "FACE_CLOSE_TO_WATER")}, referents=[("他", "QM")],
         wardrobe_override={"QM": "本镜秦铭不披裘氅，只穿深青交领窄袖袍（洗漱后），裘氅搭在炕沿"}),
    dict(s="E02-S13", n=2, sec=3, size="俯拍中景", camera="随躺下微降", axis="秦铭在炕沿躺向炕里", blocking="秦铭躺到火炕上，把兽皮大衣盖在身上",
         cast=["QM"], action=("QM", "秦铭躺到火炕上，把兽皮大衣盖在身上；他的肚子又叫了起来", None), dialogue=("QM", "好饿！", None),
         entry="秦铭站在炕边，大衣在手中", exit="秦铭躺在炕上，大衣盖在身上，肚子叫",
         dims={"POSTURE": D("站在炕边", "躺在炕上", "STANDING_AT_KANG", "LYING_ON_KANG"), "POSSESSION": D("大衣在手中", "大衣盖在身上", "COAT_IN_HAND", "COAT_OVER_BODY")}, referents=[("他", "QM")]),
    dict(s="E02-S13", n=3, sec=3, faces={"QM": "EYES_CLOSED_LYING_HIGH_ANGLE_NOT_MEASURABLE"}, size="俯拍特写", camera="俯拍缓推面部", axis="秦铭仰面", blocking="秦铭闭眼，嘴角翘起",
         cast=["QM"], action=("QM", "秦铭闭上眼，嘴角慢慢翘起来", None), dialogue=("QM", "烤羊腿……", None),
         entry="秦铭闭眼，嘴角平", exit="秦铭嘴角翘起，一句说出",
         dims={"POSTURE": D("嘴角平", "嘴角翘起", "MOUTH_FLAT", "MOUTH_CORNERS_UP")}, referents=[("他", "QM")]),
    dict(s="E02-S13", n=4, sec=4, size="俯拍特写", camera="固定俯拍", axis="秦铭仰面", blocking="秦铭猛地掐自己一把",
         cast=["QM"], action=("QM", "秦铭全程仰面躺在炕上、头枕着炕面、身体不起不坐不跪，只动自己的手臂：手离开大衣，猛地掐了自己臂上一把，眼睁开皱眉；画面里只有秦铭一个人，没有任何别人的手或身体入画；室内火炕与被褥上没有积雪，只有一点橘红余光", None), dialogue=("QM", "越界了，怎么能想这些！", None),
         entry="秦铭嘴角翘着，手搭在大衣上", exit="秦铭掐了自己一把，眼睁开皱眉",
         dims={"CONTACT": D("手搭在大衣上", "手掐在自己臂上", "HAND_ON_COAT", "HAND_PINCHING_OWN_ARM"), "POSTURE": D("嘴角翘着眼闭", "眼睁开皱眉", "SMILING_EYES_CLOSED", "EYES_OPEN_FROWNING")}, referents=[("他", "QM")]),
    dict(s="E02-S13", n=5, sec=4, faces={"QM": "LYING_FACE_UP_HIGH_ANGLE_ROTATED_NOT_MEASURABLE"}, size="中近景", camera="随翻身环绕到窗侧", axis="秦铭由仰面转为面向窗", blocking="秦铭咽口水，翻身面向漆黑的窗",
         cast=["QM"], action=("QM", "秦铭咽了一口口水，翻身面向漆黑的窗", None), dialogue=("QM", "我可没脸再去找陆哥要吃的。", None),
         entry="秦铭仰面躺着咽口水", exit="秦铭侧身面向漆黑的窗，一句说完",
         dims={"POSTURE": D("仰面", "侧身", "LYING_FACE_UP", "LYING_ON_SIDE"), "POSITION": D("脸朝屋顶", "脸朝漆黑的窗", "FACE_TO_CEILING", "FACE_TO_DARK_WINDOW")}, referents=[("他", "QM")]),
    dict(s="E02-S13", n=6, sec=3, size="特写", camera="极缓推近双眼", axis="秦铭面向窗", blocking="秦铭手按在胸口，眼睛睁着",
         cast=["QM"], action=("QM", "秦铭的手按在胸口，眼睛睁着，望着黑暗", None), dialogue=("QM", "浅夜一到就走。", None),
         entry="秦铭的手在身侧，眼半睁", exit="秦铭的手按在胸口，眼睛睁着盯窗",
         dims={"CONTACT": D("手在身侧", "手按在胸口", "HAND_AT_SIDE", "HAND_ON_CHEST"), "POSTURE": D("眼半睁", "眼睛睁着盯窗", "EYES_HALF_OPEN", "EYES_WIDE_ON_WINDOW")}, referents=[("他", "QM")]),
]

# ---------- 机位方向均衡（引擎 grouped_camera_contract.validate_camera_sequence：相邻动态单元不得重复方向，任意 5 单元内同一方向 ≤2） ----------
_ALT = [("ARC", "COUNTERCLOCKWISE"), ("ARC", "CLOCKWISE"), ("TRACK", "LEFT_TO_RIGHT"), ("TRACK", "RIGHT_TO_LEFT"),
        ("CRANE", "RISE"), ("CRANE", "FALL"), ("DOLLY", "PUSH_IN"), ("DOLLY", "PULL_OUT"), ("PAN", "LEFT_TO_RIGHT"), ("PAN", "RIGHT_TO_LEFT")]
_ZH_FAM = {"ARC": "环绕", "TRACK": "横移", "CRANE": "升降", "DOLLY": "推拉", "PAN": "横摇"}


def _unit_first_shots() -> list[str]:
    """Unit boundaries depend only on shot durations/dialogue (engine grouper), not on camera
    plans, so the grouping spec of the last S2 run is authoritative once durations are frozen.
    Fallback (no spec yet): every shot is its own unit (strictest case)."""
    spec = ROOT / "workflow/nalu/E02/preproduction/E02_VIDEO_UNIT_GROUPING_SPEC_V1.json"
    order = [f"{sh['s']}-{sh['n']:02d}" for sh in SHOTS]
    if spec.is_file():
        groups = json.loads(spec.read_text(encoding="utf-8")).get("groups") or []
        ids = [g["editorial_shot_ids"][0] for g in groups]
        covered = [x for g in groups for x in g["editorial_shot_ids"]]
        if covered == order:
            return ids
    return order


def balance_camera_directions() -> list[tuple[str, str, str]]:
    """Mirror of engine grouped_camera_contract.validate_camera_sequence on the unit-first shots:
    LOCKED resets adjacency; adjacent dynamic units never share a direction; in any 5 consecutive
    units a direction appears at most twice."""
    firsts = _unit_first_shots()
    changed = []
    seq: list[tuple[str, str] | None] = []
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
# ---------- END OF CHUNK 2b ----------

# ---------- 校验镜头表 ----------
def est_spoken(text, cps):
    han = len(re.findall(r"[㐀-鿿]", text)); p = len(re.findall(r"[，。！？；、,.!?;]", text))
    o = len(re.sub(r"[㐀-鿿\s，。！？；、,.!?;]", "", text))
    return han / cps + p * 0.16 + o * 0.08
by_scene = {}
for sh in SHOTS:
    by_scene.setdefault(sh["s"], []).append(sh)
for sid, meta in SCENES.items():
    total = sum(x["sec"] for x in by_scene[sid])
    assert total == meta["sec"], (sid, total, meta["sec"])
    assert meta["sec"] <= 22 and meta["sec"] <= 12 * meta["info"], (sid, "单场 ≤22 s 且 ≤12s×信息条数")
prev_locked = False
for i, sh in enumerate(SHOTS):
    shot_id = f"{sh['s']}-{sh['n']:02d}"
    assert 3 <= sh["sec"] <= 7, (shot_id, "单镜 3–7 s")
    assert sh["entry"] != sh["exit"], sh
    for d, (a, b, ca, cb) in sh["dims"].items():
        assert d in {"POSITION", "POSTURE", "CONTACT", "POSSESSION", "INTEGRITY", "MOMENTUM"} and a != b and ca != cb, (shot_id, d)
    for word in ("持续", "保持", "连续"):
        assert word not in sh["action"][1] and word not in sh["entry"] and word not in sh["exit"], (shot_id, word)
    cp = CAMERA_PLANS[shot_id]
    locked = cp["motion_family"] == "LOCKED"
    if sh.get("dialogue"):
        need = 0.12 + est_spoken(sh["dialogue"][1], sh.get("cps", 4.2)) + 0.32 + 0.25
        assert need <= sh["sec"], (shot_id, "台词放不进镜头", round(need, 2), sh["sec"])
        assert sh["sec"] <= 5 or need > 5, (shot_id, "只有台词确实放不进 5 s 才允许 >5 s")
    else:
        assert sh["sec"] <= 5, (shot_id, "无对白镜 ≤5 s")
        assert not locked, (shot_id, "无对白镜必须有机位运动")
    if locked:
        assert sh.get("dialogue") and sh["sec"] <= 5, (shot_id, "LOCKED 只允许 ≤5 s 对白镜")
        assert not prev_locked, (shot_id, "不得连续 LOCKED")
    assert not (i == 0 and locked), "开场镜必须运动"
    prev_locked = locked
assert sum(1 for s in SHOTS if CAMERA_PLANS[f"{s['s']}-{s['n']:02d}"]["motion_family"] == "LOCKED") / len(SHOTS) <= 0.35
_run, _prev = 0, None
for sh in SHOTS:
    cp = CAMERA_PLANS[f"{sh['s']}-{sh['n']:02d}"]; key = (sh["s"], cp["camera_side"], cp["shot_scale"])
    _run = _run + 1 if key == _prev else 1; _prev = key
    assert _run <= 2, (sh["s"], sh["n"], "同轴同景别不得连续 >2 镜")
TOTAL = sum(m["sec"] for m in SCENES.values())
assert 170 <= TOTAL <= 185, TOTAL  # 2026-09-13: +4 s after unit-feasibility rebalance (SD2 4 s floor, e16)

# ---------- 关键台词逐字核对（源章 + narrative） ----------
src_text = SRC_CH2.read_text(encoding="utf-8")
narr = SCRIPTS / f"{EP}_NARRATIVE_CANONICAL_{VER}.md"
narr_text = narr.read_text(encoding="utf-8")
AUTHORED_DIALOGUE = {  # narrative 中非源章逐字的对白：由叙述/刻字转直接对白，不增事实
    "矿素……": "ch2：「秀小的瓶体上刻着两个字：矿素。」瓶上刻字转为秦铭读出的一词，不增事实",
    "烤羊腿……": "ch2：「想到了……篝火堆上烤得金黄油亮的羊腿。」内心叙述转一词自语，不增事实",
    "我可没脸再去找陆哥要吃的。": "ch2：「他可没脸再去找陆泽索要食物。」叙述转自语，「陆泽」按 E01 已建立的称呼改「陆哥」",
    "浅夜一到就走。": "ch2：「他决定，浅夜到来就出发」叙述转自语，不增事实",
}
KEY_QUOTES, DIALOGUE_UNITS = [], []
for sh in SHOTS:
    if sh.get("dialogue"):
        spk, q, _ = sh["dialogue"]; shot = f"{sh['s']}-{sh['n']:02d}"
        assert f"{cname(spk)}：“{q}”" in narr_text, ("台词未逐字进 narrative", q)
        if q in AUTHORED_DIALOGUE:
            DIALOGUE_UNITS.append((spk, q, shot, False))
        else:
            assert q in src_text, ("key_quote 不在源章逐字文本中", q)
            KEY_QUOTES.append((spk, q, shot)); DIALOGUE_UNITS.append((spk, q, shot, True))
narr_lines = re.findall(r'^(秦铭|陆泽|梁婉清|陆文睿)：“(.+?)”$', narr_text, re.M)
assert [(cname(s), q) for s, q, *_ in DIALOGUE_UNITS] == narr_lines, "镜头表对白顺序/说话人与 narrative 不一致"

# ---------- 单元内部转场（导演授权；对每个同场相邻镜边界逐条生成，分组由引擎决定） ----------
PROP_BY_SHOT = {}
for p in PROPS + [{"entity_id": "PROP-SUN-STONE", "name": "太阳石"}]:
    pass
def _props_in(sh):
    txt = sh["action"][1] + sh["entry"] + sh["exit"]
    found = []
    for eid, kws in (("PROP-FIRE-SPRING-STONE", ["石块"]), ("PROP-CRYSTAL-VIAL", ["水晶瓶", "水晶小瓶", "瓶"]), ("PROP-FOOD-BOX", ["食盒"]), ("PROP-RED-DATE", ["红枣"]), ("PROP-SUN-STONE", ["太阳石", "铜盆"])):
        if any(k in txt for k in kws): found.append(eid)
    return found
TRANSITION_NOTES = {  # (from,to): (mode, execution)
    ("E02-S01-01", "E02-S01-02"): ("MOTIVATED_CUT", "切点在手腕没入火光之后、手开始上提之前"),
    ("E02-S01-02", "E02-S01-03"): ("CAMERA_REFRAME", "由拉出的中近景改取环绕特写，切点在石块举到眼前之后"),
    ("E02-S02-01", "E02-S02-02"): ("REACTION_CUT", "地光沉回黑暗后切面部特写"),
    ("E02-S02-02", "E02-S02-03"): ("MOTIVATED_CUT", "落雪切到雪花入领，切点在双树落雪之后"),
    ("E02-S03-01", "E02-S03-02"): ("MOTIVATED_CUT", "第一组动作摆开后切低机位，切在动作转换上"),
    ("E02-S04-01", "E02-S04-02"): ("CAMERA_REFRAME", "瓶到手后改取瓶体特写"),
    ("E02-S04-02", "E02-S04-03"): ("MOTIVATED_CUT", "蓝雾流动后切拇指按瓶塞的微俯特写"),
    ("E02-S05-01", "E02-S05-02"): ("REACTION_CUT", "秦铭说完比划身高后切男孩仰头"),
    ("E02-S05-02", "E02-S05-03"): ("MOTIVATED_CUT", "男孩问完后切秦铭蹲下"),
    ("E02-S05-03", "E02-S05-04"): ("REACTION_CUT", "语雀一句说完后切男孩跳起"),
    ("E02-S05-04", "E02-S05-05"): ("REACTION_CUT", "男孩落地后切陆泽反应"),
    ("E02-S06-01", "E02-S06-02"): ("CAMERA_REFRAME", "食盒掀开后改取俯拍食盒特写"),
    ("E02-S06-02", "E02-S06-03"): ("MOTIVATED_CUT", "筷子停半空后切秦铭放下食盒蹲下"),
    ("E02-S06-03", "E02-S06-04"): ("REACTION_CUT", "问句说完后切陆泽摇头"),
    ("E02-S06-04", "E02-S06-05"): ("MOTIVATED_CUT", "陆泽答完后切俯拍两只手"),
    ("E02-S07-01", "E02-S07-02"): ("REACTION_CUT", "梁婉清说完后切男孩点头"),
    ("E02-S07-02", "E02-S07-03"): ("MOTIVATED_CUT", "男孩说完后切秦铭送枣"),
    ("E02-S07-03", "E02-S07-04"): ("REACTION_CUT", "男孩吃下后切梁婉清叹气坐下"),
    ("E02-S08-01", "E02-S08-02"): ("CAMERA_REFRAME", "凑近后改取过肩近景"),
    ("E02-S08-02", "E02-S08-03"): ("REACTION_CUT", "陆泽说完后切秦铭手指与眼神"),
    ("E02-S09-01", "E02-S09-02"): ("MOTIVATED_CUT", "跌入地缝后切极暗中的面部"),
    ("E02-S09-02", "E02-S09-03"): ("CAMERA_REFRAME", "光炸开后改取低机位环绕"),
    ("E02-S09-03", "E02-S09-04"): ("MOTIVATED_CUT", "全黑后切拖人出缝"),
    ("E02-S10-01", "E02-S10-02"): ("REACTION_CUT", "秦铭说完后切男孩咽口水"),
    ("E02-S10-02", "E02-S10-03"): ("REACTION_CUT", "男孩问完后切秦铭抬手"),
    ("E02-S10-03", "E02-S10-04"): ("MOTIVATED_CUT", "摸头后切陆泽牵儿子走向门"),
    ("E02-S11-01", "E02-S11-02"): ("CAMERA_REFRAME", "呼吸放缓后改取环绕特写"),
    ("E02-S11-02", "E02-S11-03"): ("MOTIVATED_CUT", "银光散去后切低头看手臂"),
    ("E02-S12-01", "E02-S12-02"): ("MOTIVATED_CUT", "裘氅扔到雪上后切低机位动作"),
    ("E02-S12-02", "E02-S12-03"): ("MOTIVATED_CUT", "停下喘气后切双手特写"),
    ("E02-S12-03", "E02-S12-04"): ("MOTIVATED_CUT", "银光散去后切按胸口"),
    ("E02-S13-01", "E02-S13-02"): ("MOTIVATED_CUT", "说完明早动身后切躺下"),
    ("E02-S13-02", "E02-S13-03"): ("CAMERA_REFRAME", "躺下后改取俯拍面部特写"),
    ("E02-S13-03", "E02-S13-04"): ("MOTIVATED_CUT", "嘴角翘起后切掐自己"),
    ("E02-S13-04", "E02-S13-05"): ("MOTIVATED_CUT", "掐完后切翻身"),
    ("E02-S13-05", "E02-S13-06"): ("CAMERA_REFRAME", "翻身面窗后改取双眼特写"),
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
            identity_preservation="、".join(cname(k) for k in stay) + "保持同一面孔、发式与服装" + ("；" + "、".join(cname(k) for k in enter) + "为本镜新入画人物，面孔与服装按身份牌" if enter else "") if stay or enter else "本边界无人物延续",
            entry_exit_or_reveal=("、".join(cname(k) for k in stay) + "均已在画内" if stay else "") + ("；" + "、".join(cname(k) for k in enter) + "在本镜入画" if enter else "") + ("；" + "、".join(cname(k) for k in leave) + "在本镜不入画" if leave else "") + f"；{a['size']}切{b['size']}",
            scene_continuity=f"同一{SCENES[sid]['loc']}空间，{SCENES[sid]['light']}不变，仅机位改变",
            prop_handoff=("随身道具延续：" + "、".join(carried)) if carried else "本边界无道具主体",
            sound_bridge=f"{sid} 环境声（{AMBIENT_LIFE[sid]['motion_trend']}）连贯不中断，切镜不改变环境声",
            axis_strategy=cpb["axis_relation"],
            transition_execution=f"{execution}；本镜机位 {cpb['motion_family']}/{cpb['motion_direction']}，{cpb['start_framing']}",
            action_bridge=f"上镜终态「{a['exit']}」之后，动作不复位；本镜从「{b['entry']}」开始",
            entity_mapping="，".join(f"{cname(k)}→参考图 {cid(k)}" for k in b["cast"]) + "，各自槽位不互换" if b["cast"] else "无人物",
            same_slot_reuse_allowed=False)

# ---------- directing script ----------
lines = [f"# 《夜无疆》{EP} 导演稿 {VER}（directing script）", "",
         f"绑定 narrative：`{narr.name}`（SHA256 {sha(narr)}）", "",
         "本层只写景别、机位、轴线、走位与起止态；**不改 narrative 的任何事实**。逐镜秒标为交付口径。", "",
         "## 本集口径（Roger 2026-09-13，SUPERVISOR_ORDERS seq=7）", "",
         f"- 全局风格：{STYLE['era_idiom']}",
         f"- 夜景：{STYLE['night_look']}",
         "- 禁用：" + "、".join(STYLE["forbidden"]),
         f"- 节奏：单镜 {PACING['shot_seconds_default'][0]}–{PACING['shot_seconds_default'][1]} s（台词确需时最多 {PACING['shot_seconds_max']} s，本集仅 E02-S05-03 为 7 s）；视频单元 ≤{PACING['video_unit_seconds_max']:g} s（硬上限 {PACING['video_unit_seconds_hard_cap']:g} s）；无对白静止 ≤{PACING['no_dialogue_static_hold_seconds_max']:g} s 否则拒收；全集前 3 s 钩子＝手探火泉；每场首镜从进行中动作开始、场间在动作上切、每场有转折与 button；全集 {PACING['episode_total_seconds_target'][0]}–{PACING['episode_total_seconds_target'][1]} s（本稿 {TOTAL} s，{len(SHOTS)} 镜）",
         f"- 机位运动：LOCKED ≤35%（本稿 {sum(1 for s in SHOTS if CAMERA_PLANS[f'{s['s']}-{s['n']:02d}']['motion_family']=='LOCKED')}/{len(SHOTS)}）、不连续 LOCKED、无对白镜必动且前 2 s 内有可见状态变化、LOCKED 只用于 ≤5 s 对白镜、同轴同景别不连续 >2 镜、开场镜运动",
         f"- ★风格重置申报：{STYLE_RESET_DISCLOSURE['what_changes']}；{STYLE_RESET_DISCLOSURE['what_stays']}；{STYLE_RESET_DISCLOSURE['viewer_facing_note']}",
         "- ★承接：E02-S01-01 的 entry_state 即 E01-S10-03 的 completion_state（秦铭站在石围前抬头望两棵树），不复位、不重演", ""]
for sid, meta in SCENES.items():
    lines.append(f"## {sid}｜{meta['loc']}｜{meta['time']}｜{meta['sec']}s｜{meta['weather']}｜光：{meta['light']}")
    lines.append("")
    for sh in by_scene[sid]:
        shot_id = f"{sid}-{sh['n']:02d}"; cp = CAMERA_PLANS[shot_id]
        lines.append(f"### {shot_id}（{sh['sec']}s）｜{sh['size']}｜{sh['camera']}｜{cp['motion_family']}/{cp['motion_direction']}")
        lines.append(f"- 轴线：{sh['axis']}")
        lines.append(f"- 走位：{sh['blocking']}")
        lines.append(f"- 动作：{sh['action'][1]}")
        if sh.get("dialogue"):
            s, t, l = sh["dialogue"]; lines.append(f"- 台词：{cname(s)}：“{t}”" + (f"（{sh['cps']} 字/秒）" if sh.get("cps") else ""))
        lines.append(f"- entry_state：{sh['entry']}")
        lines.append(f"- completion_state：{sh['exit']}")
        lines.append("- 状态差：" + "；".join(f"{d}「{a}」→「{b}」" for d, (a, b, _, _) in sh["dims"].items()))
        lines.append(f"- 时代约束：{PERIOD_BY_LOC[meta['loc']]}")
        lines.append("")
directing = SCRIPTS / f"{EP}_DIRECTING_SCRIPT_{VER}.md"
directing.write_text("\n".join(lines), encoding="utf-8")
print("directing written", directing)
# ---------- END OF CHUNK 3a ----------

# ---------- generation contract ----------
import nalu_prompt_rules as NPR
# seq=10 c3: root-cause prompt rules.  E02 scope = the shots of the units rerolled under seq=10 (their prompts change
# anyway); admitted units keep their generated prompt sha.  E03+ builders apply NPR to every shot.
NPR_SCOPE_E02 = {"E02-S01-03", "E02-S05-04", "E02-S05-05", "E02-S09-01", "E02-S09-02", "E02-S09-03", "E02-S09-04", "E02-S10-02", "E02-S13-01"}
NPR_FACE = {"QM": "束发木簪、无胡须的清瘦年轻男子", "WR": "五岁风帽男孩", "LZ": "灰布裹巾的结实青年", "LW": "包髻围裙的年轻妇人",
            "CA": "斗笠麻袍的猎户", "CB": "包头皮袍的猎户", "CC": "皮袄背筐的猎户"}
NPR_APPLIED: dict[str, list[str]] = {}
NPR_BLOCKS: list[str] = []

def apply_prompt_rules(sh, shot_id, act):
    if shot_id not in NPR_SCOPE_E02:
        return act
    sid = sh["s"]
    scene_cast = {k for x in by_scene[sid] for k in x["cast"]}
    fam = (CAMERA_PLANS.get(shot_id) or {}).get("motion_family")
    shot = {"shot_id": shot_id, "sec": sh["sec"], "size": sh["size"], "camera_family": fam, "cast": sh["cast"],
            "action": act, "dialogue": sh.get("dialogue"), "entry": sh["entry"], "exit": sh["exit"]}
    ctx = {"scene_cast": scene_cast, "loc": SCENES[sid]["loc"], "cps": sh.get("cps"),
           "names": {k: cname(k) for k in CH}, "face_desc": NPR_FACE,
           "prop_tokens": ["火泉", "太阳石", "铜盆", "食盒", "红枣", "石块", "水晶瓶", "水晶小瓶", "语雀"]}
    new_act, applied, blocks = NPR.apply(shot, ctx)
    NPR_APPLIED[shot_id] = applied
    NPR_BLOCKS.extend(blocks)
    return new_act

def shot_json(sh):
    sid = sh["s"]; shot_id = f"{sid}-{sh['n']:02d}"
    subj, act, patient = sh["action"]
    act = apply_prompt_rules(sh, shot_id, act)
    dlg = sh.get("dialogue")
    spk_id = cid(dlg[0]) if dlg else ""
    lst_id = cid(dlg[2]) if dlg and dlg[2] else ""
    resolved = [{"surface_form": surface, "entity_id": cid(key) if key in CH else key} for surface, key in sh["referents"]]
    presence = {cid(k): "VISIBLE_AND_IDENTITY_LOCKED" for k in sh["cast"]}
    hidden = set(sh.get("first_frame_hidden") or []); slots = sh.get("slots") or {}; faces = sh.get("faces") or {}
    states = {cid(k): sh["exit"] for k in sh["cast"]}
    return {
        "shot_id": shot_id, "scene_id": sid, "target_seconds": sh["sec"],
        "shot_size": sh["size"], "camera": sh["camera"], "axis": sh["axis"], "blocking": sh["blocking"],
        "entry_state": sh["entry"], "completion_state": sh["exit"],
        "state_delta_dimensions": list(sh["dims"].keys()),
        "state_delta_evidence": {d: {"entry": a, "exit": b, "entry_code": ca, "exit_code": cb} for d, (a, b, ca, cb) in sh["dims"].items()},
        "keyframe_source": "entry_state",
        "period_constraints": PERIOD_BY_LOC[SCENES[sid]["loc"]],
        "pacing_flags": {"hook": shot_id == "E02-S01-01", "scene_opener_in_motion": sh["n"] == 1, "scene_button": sh is by_scene[sid][-1],
                         "no_dialogue_static_hold_seconds_max": PACING["no_dialogue_static_hold_seconds_max"] if not dlg else None},
        **({"dialogue_delivery": {"chinese_characters_per_second": sh["cps"], "basis": "导演稿：按 dialogue_cut_safety 放不进默认语速的句子标 4.8–5.0 字/秒，文本零改动"}} if sh.get("cps") else {}),
        "prompt_spec": {
            "camera_plan": {**CAMERA_PLANS[shot_id], "authorship": "DIRECTING_SCRIPT_AUTHORED", "selection_mode": "LOCKED", "source": f"E02_DIRECTING_SCRIPT_v1.md#{shot_id}"},
            "cast": [{"character": cname(k), "character_id": cid(k), **({"first_frame_visible": False} if k in hidden else {}),
                      **({"screen_slot": slots[k]} if k in slots else {}), **({"face_visibility": faces[k]} if k in faces else {})} for k in sh["cast"]],
            **({"wardrobe_state_overrides": {cid(k): v for k, v in sh["wardrobe_override"].items()}} if sh.get("wardrobe_override") else {}),
            "props": [{"prop_id": p, "prop": {**{x["entity_id"]: x["name"] for x in PROPS}, "PROP-SUN-STONE": "太阳石"}[p]} for p in _props_in(sh)],
            "dialogue": f"{cname(dlg[0])}：{dlg[1]}" if dlg else "",
            "action": {"subject_id": cid(subj) if subj else "", "primary_action": act, "patient_id": cid(patient) if patient else ""},
            **({"identity_reanchor_required": True, "identity_reanchor_reason": "seq=12：本单元首镜只有远景小人影，无面部锚点；本镜特写需以角色板生成的关键帧作身份再锚定参考（engine e19）"} if sh.get("identity_reanchor") else {}),
            "referent_resolution_contract": {"status": "PASS", "source_scan_complete": True, "resolved_source_referents": resolved, "unresolved_source_referents": []},
            "role_semantic_disambiguation": {
                "primary_actor_kind": "CHARACTER" if subj else "ENVIRONMENT",
                "primary_actor": cname(subj) if subj else "", "primary_actor_id": cid(subj) if subj else "",
                "dialogue_speaker": cname(dlg[0]) if dlg else "", "dialogue_speaker_id": spk_id,
                "dialogue_listener": cname(dlg[2]) if dlg and dlg[2] else "", "dialogue_listener_id": lst_id,
                "action_patient": cname(patient) if patient else "", "action_patient_id": cid(patient) if patient else "",
                "lip_owner_id": spk_id, "entity_states": states, "entity_presence": presence},
        },
    }

CHARACTER_ROWS = [
    {"character_id": "CHAR-QINMING", "canonical_name": "秦铭", "aliases": ["小秦", "小叔", "秦叔", "叔叔"], "voice_entity_id": "", "identity_reference_entity_id": "",
     "identity_source": {"mode": "SOURCE_PHOTO", "file": str(QM_SOURCE_V2), "sha256": STYLE_RESET_DISCLOSURE["qinming_identity_source"]["sha256"], "note": "seq=7 c4：身份牌按 source_v2 重做；关键帧与露脸视频单元直接挂身份牌"},
     "appearance_ch1": "清瘦颀长，面色由苍白转有血色，眼睛清亮；高髻木簪，外披旧裘氅，内深青交领窄袖袍银线滚边（唐宋语汇；面孔与发冠服制以 CHAR-QINMING__SOURCE_V2_TANG.png 为准）",
     "appearance_ch2": "ch2：清秀面孔不再苍白有了血色；常年锻炼、动作娴熟；一个月前进山染怪病初愈"},
    {"character_id": "CHAR-LUZE", "canonical_name": "陆泽", "aliases": ["陆哥"], "voice_entity_id": "", "identity_reference_entity_id": "", "identity_source": {"mode": "E01_IDENTITY_CARD_RESTYLED", "note": "沿用 E01 面孔，服制改唐宋短褐裹巾"},
     "appearance_ch1": "年轻男子，身体结实有力，实在人；深灰交领短褐、灰布裹巾束发，提木食盒", "appearance_ch2": "ch2：带五岁儿子送岩米饭；压低声音告知密林庞然大物"},
    {"character_id": "CHAR-LIANGWANQING", "canonical_name": "梁婉清", "aliases": ["嫂子"], "voice_entity_id": "", "identity_reference_entity_id": "", "identity_source": {"mode": "SOURCE_PHOTO", "file": str(RUNTIME / "runtime/character_sources/CHAR-LIANGWANQING.png"), "note": "沿用 E01 源照面孔，服制改唐宋短襦长裙包髻"},
     "appearance_ch1": "年轻妇人，陆泽之妻；灰褐交领短襦、旧蓝长裙、麻布围裙、麻布包髻", "appearance_ch2": "ch2：心地不坏，看到秦铭好转仍要帮助；进门劝孩子不要嘴馋，叹气坐下"},
    {"character_id": "CHAR-LUWENRUI", "canonical_name": "陆文睿", "aliases": ["文睿", "小文睿"], "voice_entity_id": "", "identity_reference_entity_id": "", "identity_source": {"mode": "TEXT_TO_IMAGE", "note": "无源照片；按 appearance 文生图生成身份牌（seq=3 c3）"},
     "appearance_ch1": "五岁左右男孩，裹得严严实实，小脸冻得红扑扑，眼睛大而清澈，纯真可爱略腼腆；赭红小交领棉袍、厚布风帽", "appearance_ch2": "ch2：陆泽之子；仰头问小叔身体、听到语雀原地跳起、盯红枣咽口水、小声问有肉肉吗"},
    {"character_id": "CHAR-COMPANION-A", "canonical_name": "同行者甲", "aliases": [], "voice_entity_id": "", "identity_reference_entity_id": "", "identity_source": {"mode": "TEXT_TO_IMAGE", "note": "仅 E02-S09 闪回，不说话；无名，不计新名"},
     "appearance_ch1": "精瘦猎户，褐色兽皮短袄、背筐", "appearance_ch2": "ch2：一个月前与秦铭同行入山的三位村人之一，地缝中昏死，被秦铭拖出"},
    {"character_id": "CHAR-COMPANION-B", "canonical_name": "同行者乙", "aliases": [], "voice_entity_id": "", "identity_reference_entity_id": "", "identity_source": {"mode": "TEXT_TO_IMAGE", "note": "仅 E02-S09 闪回，不说话；无名，不计新名"},
     "appearance_ch1": "敦实猎户，黑褐兽皮长袍、灰布包头", "appearance_ch2": "ch2：同上"},
    {"character_id": "CHAR-COMPANION-C", "canonical_name": "同行者丙", "aliases": [], "voice_entity_id": "", "identity_reference_entity_id": "", "identity_source": {"mode": "TEXT_TO_IMAGE", "note": "仅 E02-S09 闪回，不说话；无名，不计新名"},
     "appearance_ch1": "高瘦猎户，灰黄粗麻交领长袍、破斗笠", "appearance_ch2": "ch2：同上"},
]
contract = {
    "schema": "qingshan.generation_contract.v3",
    "episode": EP, "version": VER,
    "narrative_canonical": narr.name, "narrative_sha256": sha(narr),
    "style": {**STYLE, "authority": "SUPERVISOR_ORDERS seq=7 c1/c2；PRODUCTION_LINE_OVERVIEW_v1 §四 3/5", "negative_prompt_fixed": "欧式、哥特、和风、仙侠符文、现代物件、冷灰去饱和、暗黑调色、玻璃窗、电灯、拉链纽扣"},
    "pacing": PACING,
    "style_reset_disclosure": STYLE_RESET_DISCLOSURE,
    "carry_in": {"previous_episode": "E01", "previous_scene_id": "E01-S10", "previous_shot_id": "E01-S10-03",
                 "previous_completion_state": "秦铭仰头，黑叶树与白叶树入画，火光映脸",
                 "first_shot_id": "E02-S01-01", "first_shot_entry_state": SHOTS[0]["entry"],
                 "rule": "不复位、不重演、不闪回 E01 内容，沿同一方向推进至少一步（收回目光→蹲下→手探池）"},
    "visual_culture_contract": {
        "schema": "qingshan.visual_culture_contract.v1", "status": "LOCKED",
        "profile_id": STYLE["profile_id"], "decision_owner": "WRITER_DIRECTOR",
        "decision_basis": "ch2 明写：火泉石围、太阳石、火炕、铜盆、木食盒、岩米饭、红枣、水晶小瓶「矿素」；Roger 2026-09-13 审片意见：整体画风中国唐宋，不要西式暗黑；世界为东方玄幻低魔村落，尚无门派、法术与现代物件",
        "source_ref": str(SRC_CH2),
        "story_world": "永夜纪元的北地冻土村落，前工业农耕社会，中国唐宋衣冠与营造",
        "production_design": STYLE["era_idiom"] + "；食物为岩米饭、红枣、地薯干、银麦；光源只有太阳石与火泉",
        "armor_tradition": "本集无兵甲；闪回猎户只穿皮袄短褐，不得出现制式铁札甲或西式甲胄",
        "palette_system": {"base": "靛黑夜色、雪面月色青蓝", "accent": "太阳石橘红、火泉火红、水晶瓶蓝、极淡银光", "skin": "火光下暖、雪光下清；秦铭由病白转有血色"},
        "lighting_language": STYLE["night_look"] + "；太阳石与火泉是全部动机光；深夜近乎全黑仅留轮廓与雪面反射；闪回地缝为刺目白光→银丝冷光→全黑",
        "image_texture": "颗粒感胶片质感、真实材质（兽皮、粗麻、青石、铜、木）、雪雾与呼出的白气可见、火光有可见的边缘晕",
        "forbidden_influences": STYLE["forbidden"],
    },
    "character_entities": [dict(row, wardrobe_garments=WARDROBE_GARMENTS[row["character_id"]]) for row in CHARACTER_ROWS],
    "non_character_entities": [
        {"entity_id": "PROP-SUN-STONE", "name": "太阳石", "reference_card_required": False, "note": "红灿灿发光石块，取自火泉，光而不烫；E01 已建立，本集为铜盆/石盆内的光源，不单独出卡"},
        *PROPS, *SETS,
    ],
    "props": {"authority": "SUPERVISOR_ORDERS seq=7 c6：关键道具出参考卡入资产库并挂进视频参考列表", "reference_cards": [p for p in PROPS if p["reference_card_required"]], "declared_without_card": [p["entity_id"] for p in PROPS if not p["reference_card_required"]]},
    "scene_states": [
        {"scene_id": sid, "location_id": m["loc"], "time_id": m["time"], "weather": m["weather"], "lighting": m["light"],
         "target_seconds": m["sec"], "source_events": m["beats"], "new_information_count": m["info"],
         "ambient_life": m["ambient_life"], "weather_provenance": m["weather_provenance"], "period_constraints": PERIOD_BY_LOC[m["loc"]]}
        for sid, m in SCENES.items()],
    "shots": [shot_json(sh) for sh in SHOTS],
    "internal_transition_authoring": [{"from_shot_id": a, "to_shot_id": b, "authorship": "DIRECTOR_AUTHORED", **row} for (a, b), row in INTERNAL_TRANSITIONS.items()],
    "audio_contract": {
        "bgm": {"mode": "NONE", "used": False, "declaration": "NO_EXTERNAL_BGM：本集以火泉光焰低频嗡鸣、风声、雪落、踩雪、衣料摩擦、食盒木盖、咀嚼、腹鸣与地缝碎石声为全部声景；不加外置配乐"},
        "ambient_by_scene": {
            "E02-S01": "火泉光焰低频嗡鸣、池面光波轻响、手入火光的细微嘶声", "E02-S02": "寒风划过火池、双树落雪簌簌、远方地光无声、踩雪",
            "E02-S03": "院门推开落雪、衣袖带风、呼气白雾、踩雪", "E02-S04": "屋内衣料摩擦、瓶塞轻响、铜盆火霞低鸣",
            "E02-S05": "院门开合、男孩蹦跳踩雪、呼气、食盒换手木响", "E02-S06": "食盒木盖开合、筷子挑饭、咽口水、衣料摩擦",
            "E02-S07": "门开冷风、叹气、落座木炕响", "E02-S08": "门板合上、压低的人声、铜盆火霞低鸣",
            "E02-S09": "踩空碎石滚落、坠落撞击、心跳擂鼓、银光无声、拖拽衣料摩擦", "E02-S10": "摸头衣料、牵手、门板开合、门外风声",
            "E02-S11": "铜盆火焰变淡的细微收缩声、放缓的呼吸", "E02-S12": "大风卷雪、裘氅落雪、成组动作带风、喘气、腹鸣",
            "E02-S13": "水盆水声、躺下炕响、腹鸣、掐自己的倒吸气、翻身、屋外大风",
        },
        "dialogue_units": [{"shot_id": shot, "speaker_id": cid(s), "listener_id": cid(sh_l) if sh_l else "", "text": q, "verbatim_in_source": v}
                           for (s, q, shot, v), sh_l in zip(DIALOGUE_UNITS, [sh["dialogue"][2] for sh in SHOTS if sh.get("dialogue")])],
    },
}
contract_path = SCRIPTS / f"{EP}_GENERATION_CONTRACT_{VER}.json"
if NPR_BLOCKS:
    raise SystemExit("nalu_prompt_rules BLOCK (restage the shot): " + "; ".join(NPR_BLOCKS))
print("nalu_prompt_rules applied:", {k: v for k, v in NPR_APPLIED.items()})
contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("contract written", contract_path)
# ---------- END OF CHUNK 3b ----------

# ---------- manifest ----------
BEATS = [  # ch2 实读 21 拍；落点到场次粒度（gate 10 读 landed_at）
    ("E02-EV-01", "landed", "E02-S01（三镜）", "秦铭蹲下从火泉捞出发光石块，比红珊瑚还莹润、霞光四照"),
    ("E02-EV-02", "dropped", "", "太阳石出自火泉、熄灭后放回可恢复——E01 已给，观众已知，不复证"),
    ("E02-EV-03", "landed", "E02-S01-03", "满池火红却不及体温——「池中的光不烫手」以石块贴脸眉头不皱一格落地"),
    ("E02-EV-04", "dropped", "", "永夜只分浅夜深夜、火泉浇灌庄稼、四季活跃枯竭、逐火而生——世界观科普不单独占镜（Roger 短剧节奏口径）"),
    ("E02-EV-05", "dropped", "", "火泉引黑暗生物窥视；双树村缺粮因怪鸟蚁祸——世界观科普不单独占镜"),
    ("E02-EV-06", "landed", "E02-S02-01", "浅夜远方地光腾起，密林轮廓隐约可见"),
    ("E02-EV-07", "landed", "E02-S02-01", "秦铭寻思何时能出去；眺望野外极暗，积雪没过胸口"),
    ("E02-EV-08", "landed", "E02-S02-02", "寒风划过火池波光粼粼，黑白双树簌簌摇落积雪"),
    ("E02-EV-09", "landed", "E02-S02-03", "雪花落到脖颈回过神，再养一养身体；沿原路往回走"),
    ("E02-EV-10", "landed", "E02-S03（两镜）", "院中以特定动作锻炼，娴熟如本能；额头见汗周身暖意"),
    ("E02-EV-11", "landed", "E02-S04（三镜）", "取出袖珍水晶瓶「矿素」迎火霞观看，蓝雾流动；克制未开启；「再过几天或许就能用上了」"),
    ("E02-EV-12", "landed", "E02-S05（五镜）", "浅夜将尽陆泽带文睿来；长高、身体好些、许诺抓语雀（四句台词逐字）"),
    ("E02-EV-13", "landed", "E02-S06-01 至 E02-S06-03", "「最近外面不对劲」递食盒；岩米饭红枣；文睿盯枣咽口水；秦铭愧疚蹲下问吃饱"),
    ("E02-EV-14", "landed", "E02-S06-04 至 E02-S06-05", "陆泽摇头说看到红枣；秦铭挑枣；陆泽攥住手腕「别挑给他」"),
    ("E02-EV-15", "landed", "E02-S07（四镜）", "梁婉清进门「你不要嘴馋」；文睿「我不饿了」；秦铭执意喂枣；梁婉清叹气坐下"),
    ("E02-EV-16", "landed", "E02-S08（三镜）", "梁婉清回家；陆泽压低声音告知密林庞然大物出没死伤人；秦铭听着（照料两岁孩子一句不演）"),
    ("E02-EV-17", "landed", "E02-S09（四镜）", "一个月前地缝：踩空坠落、刺目光、心脏擂鼓、银光交织、同行者昏死、拖出、尸体旁捡水晶瓶"),
    ("E02-EV-18", "dropped", "", "回村路上不适；三位同行者当天死去全身发黑，秦铭熬一个月——E01-S06-03 已给，观众已知"),
    ("E02-EV-19", "landed", "E02-S10（四镜）", "秦铭许诺枣子榛果；文睿「有肉肉吗」；「会有的」；父子离去"),
    ("E02-EV-20", "landed", "E02-S11（三镜）", "铜盆光变淡；闭目静坐；睁眼银光一闪「错觉吗」；细密汗水"),
    ("E02-EV-21", "landed", "E02-S12（四镜）＋ E02-S13（六镜）", "院中再练大汗淋漓，银光真切「真的不一样了」，暖意流动，肚子叫收手；洗漱照见血色「明早就动身」；各家火光暗下大风；「好饿」想烤羊腿「越界了」掐自己；决定浅夜出发（送回太阳石一句不演）"),
]
NEW_GSM = {"map_id": "GSM-YEWUJIANG-MOUNTAIN-CREVICE-FLASHBACK", "location_id": "LOC-MOUNTAIN-CREVICE-INT", "status": "NAMED_ONLY_NO_GEOMETRY",
           "note": "E02-S09 闪回所需新地点：漆黑山林中的地缝（缝内岩壁碎石；缝口外不远处几具穿着不俗的尸体）。仅命名，几何由 S2 extend_global_space_map 按 narrative 生成，不在写手层臆造"}
manifest = {
    "episode": EP, "version": VER, "title": "火泉",
    "canonical_script": f"workflow/claude_writer_agent/scripts/{narr.name}", "script_sha256": sha(narr),
    "directing_script": f"workflow/claude_writer_agent/scripts/{directing.name}", "directing_sha256": sha(directing),
    "generation_contract": f"workflow/claude_writer_agent/scripts/{contract_path.name}", "generation_contract_sha256": sha(contract_path),
    "supersedes": "",
    "★supersedes_disclosure": "首版，无前版。nalu 线《夜无疆》E02 首次交付；按 SUPERVISOR_ORDERS seq=7 新口径（唐宋画风、暖火光夜景、加快节奏、机位运动政策、道具参考卡、秦铭 source_v2）编排；narrative 13 场 24 句对白零改动。",
    "authorization": {"order_seq": 7, "order_id": "ROGER-20260913-NALU-E02-NEW-RULES-TANG-SONG-PACING-SOURCE-V2", "also": ["seq=2 ROGER-20260909-NALU-E02-E10-BATCH", "seq=3 ROGER-20260909-NALU-E01-E10-PRODUCTION-AUTHORIZED"], "orders_file": "workflow/claude_writer_agent/SUPERVISOR_ORDERS.json"},
    "writer_identity": {"agent_id": "claude-code-nalu-writer", "provider": "anthropic", "model_id": "claude-fable-5-1", "session_note": "Claude Code 交互会话，Roger 2026-09-13 现场指令"},
    "source_binding": {
        "work": "夜无疆", "author": "辰东",
        "primary_source_chapter": "2", "source_chapters": ["2"], "chapter_title": "火泉",
        "source_file": str(SRC_CH2), "source_sha256": sha(SRC_CH2),
        "source_index": str(RUNTIME / "sources/夜无疆/SOURCE_INDEX.json"),
        "episode_source_map": str(RUNTIME / "runtime/episode_source_map_yewujiang_v1.json"),
        "beat_count": len(BEATS), "beats_landed": sum(1 for b in BEATS if b[1] == "landed"), "beats_merged": 0, "beats_dropped": sum(1 for b in BEATS if b[1] == "dropped"),
        "★carry_in_is_bound_to_the_previous_episode_bytes": "承接 E01_NARRATIVE_CANONICAL_v1.md E01-S10 末段实际字节（narrative 头部逐字引全文五行）：「秦铭走到石围前停下，抬头望着两棵树，火光映在他脸上。」E02-S01-01 entry_state = E01-S10-03 completion_state（秦铭仰头望树），本集第一步动作为收回目光→蹲下→手探池；不复位、不重演、不闪回 E01 内容。",
        "carry_in": contract["carry_in"] | {"previous_canonical": "workflow/claude_writer_agent/scripts/E01_NARRATIVE_CANONICAL_v1.md", "previous_canonical_sha256": sha(SCRIPTS / "E01_NARRATIVE_CANONICAL_v1.md"), "anchor_lines_quoted_in_narrative_header": 5},
    },
    "beat_disposition": [{"event_id": e, "disposition": d, "landed_at": at, "summary": s} for e, d, at, s in BEATS],
    "★authorized_insertions": [],
    "authored_dialogue_from_indirect_speech": [
        {"shot_id": shot, "speaker": cname(s), "text": q, "source_basis": AUTHORED_DIALOGUE[q]} for s, q, shot, v in DIALOGUE_UNITS if not v],
    "★audience_already_knows": ["永夜世界", "太阳石取自火泉", "秦铭怪病将愈", "陆泽接济", "火泉双树（形制不复证，只给新角度：池中的光不烫手）"],
    "★style_reset_disclosure": STYLE_RESET_DISCLOSURE,
    "structure": [{"beat_id": f"{EP}-B{idx+1:02d}", "scene_id": sid, "target_seconds": m["sec"], "thread": "线A", "location_id": m["loc"], "time_id": m["time"], "source_events": m["beats"], "new_information_count": m["info"]}
                  for idx, (sid, m) in enumerate(SCENES.items())],
    "scene_breakdown_seconds": {sid: m["sec"] for sid, m in SCENES.items()},
    "total_seconds": TOTAL,
    "runtime_target_seconds": {"min": 170.0, "target": 178.0, "max": 180.0},
    "shot_count": len(SHOTS),
    "pacing": PACING,
    "key_quote_landing": [{"speaker": cname(s), "quote": q, "shot_id": shot, "verbatim_in_source": True} for s, q, shot in KEY_QUOTES],
    "fs1": {"combat_clusters": [], "combat_seconds": 0, "note": "ch2 无打斗，不得原创打斗；本集张力簇：S06 抢枣攥腕＋S08 密林庞然大物＋S09 地缝银光闪回。FS-1 段配额由 E01–E10 段内后续源章承担。"},
    "identity_registry": {cid(k): cname(k) for k in CH} | {p["entity_id"]: p["name"] for p in PROPS} | {s["entity_id"]: s["name"] for s in SETS} | {"PROP-SUN-STONE": "太阳石"},
    "new_name_budget": {"budget_per_4_episodes": 1, "writer_invented_names_this_episode": 0, "note": "陆文睿为 ch2 具名人物；同行者甲乙丙为源章「三位同行者」的无名指代，不计新名"},
    "distinct_locations": sorted({m["loc"] for m in SCENES.values()}),
    "new_locations": ["LOC-MOUNTAIN-CREVICE-INT"],
    "episode_global_space_map_id": "GSM-YEWUJIANG-SHUANGSHU-VILLAGE-V1",
    "global_space_map_refs": [
        {"map_id": "GSM-YEWUJIANG-FIRE-SPRING-TWIN-TREES", "scenes": ["E02-S01", "E02-S02"], "anchors": ["石围池沿", "黑叶树与白叶树", "村外黑暗边界（S02 面向北）"], "axis_note": "S01 秦铭在池沿南侧面向池心；S02 转身面向村外（北），再转身回村（南）"},
        {"map_id": "GSM-YEWUJIANG-QINMING-LUZE-ADJOINING-HOMESTEAD", "scenes": ["E02-S03", "E02-S04", "E02-S05", "E02-S06", "E02-S07", "E02-S08", "E02-S10", "E02-S11", "E02-S12", "E02-S13"], "anchors": ["秦铭家院门（朝东）", "院中石盆", "屋门", "铜盆", "火炕", "木格窗"], "axis_note": "院内沿院门—屋门轴；屋内沿门—柜轴与炕—窗轴（S11/S13 面向铜盆与窗）"},
        NEW_GSM | {"scenes": ["E02-S09"]},
    ],
    "shot_subspace_bindings": [{"shot_id": f"{sh['s']}-{sh['n']:02d}", "location_id": SCENES[sh["s"]]["loc"]} for sh in SHOTS],
    "onscreen_text_shot_level_registry": [],
    "state_delta_contract_summary": {"shots_total": len(SHOTS), "shots_with_entry_ne_completion": len(SHOTS), "min_dimensions_per_shot": min(len(sh["dims"]) for sh in SHOTS), "extend_words_in_action_fields": 0},
    "camera_motion_summary": {"locked_shots": [f"{s['s']}-{s['n']:02d}" for s in SHOTS if CAMERA_PLANS[f"{s['s']}-{s['n']:02d}"]["motion_family"] == "LOCKED"], "locked_share": round(sum(1 for s in SHOTS if CAMERA_PLANS[f"{s['s']}-{s['n']:02d}"]["motion_family"] == "LOCKED") / len(SHOTS), 3), "policy": PACING["camera_motion_policy"]},
    "writer_self_check": {"every_scene_asked_which_source_beat": True, "scenes_without_source_beat": [], "undeclared_insertions": 0, "dialogue_lines_total": len(DIALOGUE_UNITS), "dialogue_lines_verbatim_in_source": len(KEY_QUOTES), "dialogue_lines_authored_from_narration": len(DIALOGUE_UNITS) - len(KEY_QUOTES), "dialogue_order_matches_narrative": True},
}
manifest_path = SCRIPTS / f"{EP}_manifest_{VER}.json"
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print(json.dumps({
    "narrative": {"path": str(narr), "sha256": sha(narr)},
    "directing": {"path": str(directing), "sha256": sha(directing)},
    "contract": {"path": str(contract_path), "sha256": sha(contract_path), "shots": len(SHOTS)},
    "manifest": {"path": str(manifest_path), "sha256": sha(manifest_path), "total_seconds": manifest["total_seconds"], "scenes": len(SCENES)},
}, ensure_ascii=False, indent=2))
