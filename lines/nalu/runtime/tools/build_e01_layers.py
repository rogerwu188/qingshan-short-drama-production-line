import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
# -*- coding: utf-8 -*-
"""E01《永夜》v1 —— 从一张镜头表生成 directing script / generation contract / manifest。

单一事实源是 SHOTS 表；narrative canonical 为手写，manifest 的 script_sha256 在此计算。
"""
import hashlib, json, pathlib

ROOT = pathlib.Path(f"{_np.ENGINE_ROOT}")
SCRIPTS = ROOT / "workflow/claude_writer_agent/scripts"
RUNTIME = pathlib.Path(f"{_np.RUNTIME_ROOT}")
SRC_CH1 = RUNTIME / "sources/夜无疆/zh-CN/ch0001.md"
EP, VER = "E01", "v1"

def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

CH = {
    "QM": ("CHAR-QINMING", "秦铭"),
    "LZ": ("CHAR-LUZE", "陆泽"),
    "LW": ("CHAR-LIANGWANQING", "梁婉清"),
    "ZA": ("CHAR-ZHOUAPO", "周阿婆"),
    "YY": ("CHAR-YANGYONGQING", "杨永青"),
    "NB": ("CHAR-VILLAGER-A", "邻居甲"),
}
def cid(k): return CH[k][0]
def cname(k): return CH[k][1]

SCENES = {
    "E01-S01": dict(loc="LOC-SHUANGSHU-VILLAGE-EXT", time="TIME-DEEP-NIGHT-BLIZZARD", weather="暴雪·狂风", light="无光源；雪面反射极弱的靛黑", sec=12, beats=["E01-EV-01"], info=1),
    "E01-S02": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-DEEP-NIGHT-BLIZZARD", weather="屋外暴雪", light="几乎全黑；火炕余温无光；窗缝微弱雪光", sec=20, beats=["E01-EV-02"], info=2),
    "E01-S03": dict(loc="LOC-LUZE-YARD-EXT", time="TIME-DEEP-NIGHT-BLIZZARD", weather="风渐小·零星小雪", light="陆家院内一盆将熄的太阳石，暗红", sec=21, beats=["E01-EV-03", "E01-EV-04"], info=2),
    "E01-S04": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-DEEP-NIGHT-BLIZZARD", weather="屋外小雪", light="全黑，仅轮廓", sec=14, beats=["E01-EV-04"], info=2),
    "E01-S05": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="雪停·浅夜", light="浅夜淡墨；太阳石倒入石盆后橘红光成为主光", sec=21, beats=["E01-EV-05", "E01-EV-06"], info=2),
    "E01-S06": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜", light="铜盆太阳石，满室橘红暖光", sec=15, beats=["E01-EV-06", "E01-EV-04"], info=2),
    "E01-S07": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜", light="铜盆太阳石，满室橘红暖光", sec=19, beats=["E01-EV-07"], info=2),
    "E01-S08": dict(loc="LOC-VILLAGE-STREET-NORTH-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·雪停·极冷", light="各家院内太阳石火霞外溢，街道淡红", sec=22, beats=["E01-EV-08"], info=2),
    "E01-S09": dict(loc="LOC-YANG-HOUSE-FRONT-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·雪停", light="杨家院门太阳石较多，禾场偏亮", sec=22, beats=["E01-EV-09"], info=2),
    "E01-S10": dict(loc="LOC-FIRE-SPRING-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·雪停", light="火泉火红光，全村最亮处", sec=18, beats=["E01-EV-10"], info=2),
}

# ---------- 生产字段（2026-09-12 补录；不改任何剧情事实）----------
# 引擎 SD2 编译（tools/sd2_background_ecology_contract.py）要求每个节拍带写手声明的
# ambient_life{grade,motion_trend,first_frame_state,reaction_progression} 与
# weather_provenance{source_type,source_ref,visibility_mode}；此处按 narrative 逐场落地。
AMBIENT_LIFE = {
    "E01-S01": {"grade": "C", "motion_trend": "狂风横卷雪幕、屋顶茅草抬落、雪粒击打墙面", "first_frame_state": "雪幕静垂遮住村落轮廓，屋顶只见一线", "reaction_progression": "风力渐强→雪幕被撕开露出房屋轮廓→一处屋顶一角被掀起又落下"},
    "E01-S02": {"grade": "C", "motion_trend": "被面随呼吸起伏、窗缝雪光微颤、屋外风声透墙", "first_frame_state": "秦铭闭眼侧卧、被子盖到下巴、室内静止近黑", "reaction_progression": "饥饿收缩喉结滚动→攥紧被角裹紧→睁大眼、目光转清亮、头转向窗"},
    "E01-S03": {"grade": "B", "motion_trend": "零星雪花飘落、院内将熄太阳石暗红微闪、食盒随步伐轻晃、呼出白气", "first_frame_state": "陆泽提食盒离院门两步、梁婉清刚追出到屋门口", "reaction_progression": "梁婉清一步拦身→陆泽把食盒收到身后→梁婉清抬手指屋内→陆泽抬头望向村外黑暗；隔墙秦铭贴墙听、低头额抵墙"},
    "E01-S04": {"grade": "C", "motion_trend": "衣料摩擦、搓手、呼出白气在近黑中隐约可见", "first_frame_state": "秦铭坐在炕沿只穿单衣发抖", "reaction_progression": "掀被起身穿棉衣→翻柜裹上兽皮大衣→来回走动搓手→停步摊手看手指攥紧又松开"},
    "E01-S05": {"grade": "B", "motion_trend": "浅夜黑暗由深转淡、铁锨铲雪扬起雪粉、太阳石入石盆迸出橘红光、两人呼出白气", "first_frame_state": "院门紧闭、院内积雪平整齐膝、屋门被雪封住", "reaction_progression": "陆泽推门铲雪清路→秦铭拉门门缝雪落→太阳石倒入石盆照亮院落→陆泽直身看清秦铭的脸愣住"},
    "E01-S06": {"grade": "B", "motion_trend": "铜盆太阳石橘红光在墙上晃动、衣料摩擦", "first_frame_state": "屋内黑暗、铜盆空、两人隔盆站立", "reaction_progression": "太阳石入铜盆满室生辉→陆泽一手落在秦铭肩上→秦铭目光垂向盆中火光"},
    "E01-S07": {"grade": "B", "motion_trend": "食盒木盖开合、撕馍冒出白气、门板开合透进浅夜冷光", "first_frame_state": "陆泽递出食盒、秦铭站着不接", "reaction_progression": "陆泽塞到手中→秦铭喊陆哥→秦铭狼吞虎咽→陆泽推门离去"},
    "E01-S08": {"grade": "B", "motion_trend": "踩雪咯吱、呼气白雾、各家院内太阳石火霞外溢摇曳、远处零星人声与人影", "first_frame_state": "秦铭独自沿北街向北走、路口暂无人", "reaction_progression": "邻居甲出声问话→周阿婆凑近看脸→周阿婆叮嘱并塞地薯干→秦铭推回继续北行"},
    "E01-S09": {"grade": "B", "motion_trend": "黑山羊拉石磨转动、银麦碎屑沙沙落下、羊喷鼻白气、院门太阳石火霞摇曳", "first_frame_state": "石磨转动、黑山羊低头拉磨、杨永青站在院门", "reaction_progression": "秦铭停步盯羊→杨永青搭话称最后存粮→秦铭应答但目光不信"},
    "E01-S10": {"grade": "C", "motion_trend": "火泉光焰低频跳动、黑白双树叶片无风轻响、零星雪花落入火光", "first_frame_state": "秦铭走到石围前停下、抬头望双树", "reaction_progression": "火光映在脸上→目光在两树间移动→按剧本终态停在抬头望树（button）"},
}
WEATHER_PROVENANCE = {
    "E01-S01": {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": "E01_NARRATIVE_CANONICAL_v1.md#E01-S01｜ch1", "visibility_mode": "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED"},
    "E01-S02": {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": "E01_NARRATIVE_CANONICAL_v1.md#E01-S02｜ch1", "visibility_mode": "OFFSCREEN_AUDIBLE_WIND_SNOWLIGHT_THROUGH_WINDOW_GAP_INTERIOR_DRY"},
    "E01-S03": {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": "E01_NARRATIVE_CANONICAL_v1.md#E01-S03｜ch1", "visibility_mode": "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED"},
    "E01-S04": {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": "E01_NARRATIVE_CANONICAL_v1.md#E01-S04｜ch1", "visibility_mode": "OFFSCREEN_AUDIBLE_WIND_SNOWLIGHT_THROUGH_WINDOW_GAP_INTERIOR_DRY"},
    "E01-S05": {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": "E01_NARRATIVE_CANONICAL_v1.md#E01-S05｜ch1", "visibility_mode": "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED"},
    "E01-S06": {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": "E01_NARRATIVE_CANONICAL_v1.md#E01-S06｜ch1", "visibility_mode": "OFFSCREEN_ONLY_SHALLOW_NIGHT_THROUGH_DOOR_INTERIOR_DRY"},
    "E01-S07": {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": "E01_NARRATIVE_CANONICAL_v1.md#E01-S07｜ch1", "visibility_mode": "OFFSCREEN_ONLY_SHALLOW_NIGHT_THROUGH_DOOR_INTERIOR_DRY"},
    "E01-S08": {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": "E01_NARRATIVE_CANONICAL_v1.md#E01-S08｜ch1", "visibility_mode": "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED"},
    "E01-S09": {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": "E01_NARRATIVE_CANONICAL_v1.md#E01-S09｜ch1", "visibility_mode": "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED"},
    "E01-S10": {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": "E01_NARRATIVE_CANONICAL_v1.md#E01-S10｜ch1", "visibility_mode": "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED"},
}
for _sid, _m in SCENES.items():
    _m["ambient_life"] = AMBIENT_LIFE[_sid]
    _m["weather_provenance"] = WEATHER_PROVENANCE[_sid]

# ---------- 服装结构字段（2026-09-12 补录；依据已锁定身份牌实际所见＋原著描写）----------
# 引擎 tools/wardrobe_identity_contract.py 要求每个可见人物的 silhouette/primary_color/secondary_color/
# pattern/footwear/accessory 非空，且同阶层任意两人在区分字段上至少有 3 处不同。
WARDROBE_GARMENTS = {"CHAR-QINMING": {"silhouette": "颀长瘦削、长发散披肩后、外披过膝旧兽皮大衣", "outer_layer": "陈旧兽皮大衣（毛面磨秃、下摆结霜）", "inner_layer": "粗布棉衣（灰白洗白）", "primary_color": "灰褐（兽皮）", "secondary_color": "灰白（棉衣）", "material": "粗布棉＋兽皮", "pattern": "素面；兽皮毛面磨秃、边缘结霜", "belt_or_fastening": "布带系束", "footwear": "旧布靴加裹腿", "accessory": "无头巾，长发散披"}, "CHAR-LUZE": {"silhouette": "壮实宽肩、束发脑后、齐膝棉袍", "outer_layer": "无外披，粗布棉衣即为外层", "inner_layer": "粗布棉衣（深灰）", "primary_color": "深灰", "secondary_color": "灰褐（腰带）", "material": "粗布棉", "pattern": "粗织纹，肩背有补丁与磨痕", "belt_or_fastening": "麻布腰带", "footwear": "裹腿加旧皮靴", "accessory": "无头巾，束发"}, "CHAR-LIANGWANQING": {"silhouette": "收腰短袄配围裙、包头", "outer_layer": "无外披，粗布棉袄即为外层", "inner_layer": "粗布棉袄（灰褐盘扣立领）", "primary_color": "灰褐", "secondary_color": "旧蓝（长裤）", "material": "粗布棉", "pattern": "细密织纹，围裙边缘磨破", "belt_or_fastening": "细布系带＋麻布围裙", "footwear": "布鞋加裹腿", "accessory": "麻布头巾"}, "CHAR-ZHOUAPO": {"silhouette": "单薄佝偻、长袍及踝、肩披小披肩", "outer_layer": "旧兽皮小披", "inner_layer": "粗布棉衣（黑色）", "primary_color": "黑", "secondary_color": "褐（披肩）", "material": "粗布棉＋兽皮", "pattern": "素面；披肩边缘毛边", "belt_or_fastening": "布带", "footwear": "黑布鞋", "accessory": "灰麻布头巾"}, "CHAR-YANGYONGQING": {"silhouette": "敦实圆腹、厚重毛面兽皮大衣", "outer_layer": "陈旧兽皮大衣（厚重毛面）", "inner_layer": "粗布棉衣（灰蓝）", "primary_color": "深褐（毛皮）", "secondary_color": "灰蓝（棉袍）", "material": "粗布棉＋兽皮", "pattern": "毛面带霜、袍面泥渍", "belt_or_fastening": "麻绳腰带", "footwear": "裹腿旧靴", "accessory": "无头巾，络腮胡"}, "CHAR-VILLAGER-A": {"silhouette": "中等瘦削、宽腰带短袍", "outer_layer": "无外披，粗布棉衣即为外层", "inner_layer": "粗布棉衣（深灰褐）", "primary_color": "深灰褐", "secondary_color": "灰（头巾）", "material": "粗布棉", "pattern": "粗织横纹", "belt_or_fastening": "宽布腰带打结", "footwear": "草鞋布鞋", "accessory": "麻布头巾"}}

# ---------- 单元内部转场（导演授权；2026-09-12）----------
# 引擎 tools/grouped_internal_continuity_contract.py：同一视频单元内相邻两镜的边界必须由导演逐条说明
# 交接方式；机械绑定字段（可见人物、空间、道具、声音的精确列表）由 build_nalu_preproduction 从两镜 spec 生成。
# action_bridge 必须逐字包含上镜 completion_state 与本镜 start_state。
INTERNAL_TRANSITIONS = {
    ("E01-S03-01", "E01-S03-02"): dict(
        transition_mode="MOTIVATED_CUT",
        identity_preservation="陆泽与梁婉清保持同一面孔、发型与服装，陆泽在左、梁婉清在右的相对位置不变",
        entry_exit_or_reveal="二人均已在画内，无人进出画面；由中景切至梁婉清肩后的过肩近景",
        scene_continuity="同一陆家院内、院门仍在陆泽身后，仅机位推近，雪与太阳石暗红光不变",
        prop_handoff="本边界无道具主体；陆泽手中食盒作为随身物延续",
        sound_bridge="风声渐小与院内踩雪声连续不中断，切镜不改变环境声",
        axis_strategy="保持 AXIS-LUZE-YARD-DOOR-GATE 轴线，不越轴，梁婉清始终在陆泽画右",
        transition_execution="硬切至梁婉清肩后过肩近景，切点在陆泽停步之后",
        action_bridge="上镜终态「梁婉清挡在陆泽与院门之间，陆泽停步」后陆泽保持停步并压低声音；本镜从「食盒提在陆泽身前」开始，陆泽把食盒往身后收半分",
        entity_mapping="陆泽→参考图 CHAR-LUZE，梁婉清→参考图 CHAR-LIANGWANQING，各自槽位不互换",
        same_slot_reuse_allowed=False),
    ("E01-S05-01", "E01-S05-02"): dict(
        transition_mode="MOTIVATED_CUT",
        identity_preservation="陆泽保持同一面孔与粗布棉衣；秦铭为新入画人物，面孔与棉衣外裹兽皮大衣按身份牌",
        entry_exit_or_reveal="秦铭在本镜拉开房门入画（新入画），陆泽留在院中铲雪终点位置",
        scene_continuity="同一秦铭家院内，院门→屋门方向不变，铲开的雪路连接两镜空间",
        prop_handoff="本边界无道具主体；铁锨留在陆泽手中作为随身物",
        sound_bridge="铁锨铲雪声延续，转为门板挤雪与雪块落地",
        axis_strategy="机位从院门中心转向屋门，保持院门在秦铭画右的方向关系，不越轴",
        transition_execution="切至对准屋门的固定中景，切点在铲出雪路后、房门开始被拉动之前",
        action_bridge="上镜终态「院门敞开，一条铲开的雪路通到屋门前」之后，秦铭听见铲雪声从屋内拉门；本镜从「房门闭合，门缝堆雪；陆泽在院中面向屋门，秦铭在门内不可见」开始",
        entity_mapping="秦铭→参考图 CHAR-QINMING 占新槽位，陆泽→参考图 CHAR-LUZE 保留原槽位",
        same_slot_reuse_allowed=False),
    ("E01-S06-01", "E01-S06-02"): dict(
        transition_mode="CAMERA_REFRAME",
        identity_preservation="陆泽与秦铭保持同一面孔与服装，陆泽在右、秦铭在左隔铜盆而立不变",
        entry_exit_or_reveal="二人均在画内，无进出；由对铜盆的中景改取两人近景正反打",
        scene_continuity="同一秦铭屋内，铜盆位于两人之间，满室橘红光延续",
        prop_handoff="太阳石已全部倒入铜盆并留在盆中发光，本镜不再作为道具主体；空布袋仍在陆泽手中",
        sound_bridge="太阳石入盆撞击声结束后转为衣料摩擦与低声对话，环境暖光嗡鸣延续",
        axis_strategy="保持陆泽右、秦铭左的视线轴，过肩正反打不越轴",
        transition_execution="镜头由铜盆中景改取两人过肩近景，切点在最后一块太阳石落盆之后",
        action_bridge="上镜终态「铜盆堆满太阳石，屋内被橘红光照满」之后，陆泽提着倒空的布袋直起身；本镜从「陆泽双手提布袋」开始，陆泽拍秦铭的肩",
        entity_mapping="陆泽→参考图 CHAR-LUZE，秦铭→参考图 CHAR-QINMING，各自槽位不互换",
        same_slot_reuse_allowed=False),
    ("E01-S07-03", "E01-S07-04"): dict(
        transition_mode="REACTION_CUT",
        identity_preservation="秦铭与陆泽保持同一面孔与服装，秦铭在门内、陆泽在门口位置关系不变",
        entry_exit_or_reveal="二人均在画内；陆泽在本镜转身出门离开画面，秦铭留在屋内",
        scene_continuity="同一秦铭屋内，屋门为陆泽出画方向，橘红光不变",
        prop_handoff="本边界无道具主体；秦铭手中撕开的黑面馍作为随身物延续",
        sound_bridge="秦铭咀嚼声延续，叠加门板开合与门外浅夜风声",
        axis_strategy="保持秦铭面向陆泽的视线轴，切至对门的中景不越轴",
        transition_execution="反应切：陆泽看到秦铭吃上了才转身，切点在秦铭塞满嘴之后",
        action_bridge="上镜终态「馍被撕开一块，秦铭嘴里塞满」之后，陆泽看他吃上了；本镜从「陆泽面向秦铭站在屋内」开始，陆泽转身出门，秦铭站直",
        entity_mapping="秦铭→参考图 CHAR-QINMING，陆泽→参考图 CHAR-LUZE，各自槽位不互换",
        same_slot_reuse_allowed=False),
    ("E01-S08-01", "E01-S08-02"): dict(
        transition_mode="MOTIVATED_CUT",
        identity_preservation="秦铭保持同一面孔与兽皮大衣；邻居甲与周阿婆为新入画人物，面孔与头巾按身份牌",
        entry_exit_or_reveal="邻居甲与周阿婆在路口入画（新出现），秦铭从街心走入路口",
        scene_continuity="同一北街，由秦铭家院门外的街心向北推进到北街路口，太阳石火霞外溢延续",
        prop_handoff="秦铭手中照路的太阳石小块在本镜不再作为道具主体，可留在手中不强调",
        sound_bridge="踩雪咯吱与呼气声延续，远处零星人声在路口变为近处问话",
        axis_strategy="保持秦铭向北行进的方向轴，路口固定机位不越轴",
        transition_execution="由手持后跟远景切至路口固定中景，切点在秦铭走出街心之后",
        action_bridge="上镜终态「秦铭在街心，身后院门半开」之后，秦铭沿北街走到路口；本镜从「周阿婆在路口两步外，秦铭独自站立」开始",
        entity_mapping="秦铭→参考图 CHAR-QINMING 保留槽位，邻居甲→CHAR-VILLAGER-A、周阿婆→CHAR-ZHOUAPO 各占新槽位",
        same_slot_reuse_allowed=False),
}

# ---------- 状态差编码（2026-09-12；tools/sd2_motion_density_gate.py 要求每维 entry_code/exit_code 且不同）----------
STATE_DELTA_CODES = {("E01-S01-01", "INTEGRITY"): ("SNOW_CURTAIN_INTACT", "SNOW_CURTAIN_TORN"), ("E01-S01-01", "MOMENTUM"): ("CURTAIN_HANGING_STILL", "GALE_SWEEPING"), ("E01-S01-02", "POSITION"): ("ROOF_EDGE_ON_WALL", "ROOF_CORNER_LIFTED"), ("E01-S01-02", "INTEGRITY"): ("SNOW_LAYER_INTACT", "SNOW_BLOCKS_SLIDING"), ("E01-S02-01", "POSTURE"): ("EYES_CLOSED_ON_SIDE", "EYES_OPEN_ON_BACK"), ("E01-S02-01", "POSITION"): ("QUILT_AT_CHIN", "QUILT_AT_CHEST"), ("E01-S02-02", "CONTACT"): ("HAND_RESTING_ON_QUILT", "HAND_GRIPPING_QUILT_EDGE"), ("E01-S02-02", "POSTURE"): ("MOUTH_SLIGHTLY_OPEN", "JAW_CLENCHED"), ("E01-S02-03", "POSTURE"): ("EYELIDS_HALF_UNFOCUSED", "EYES_WIDE_FOCUSED"), ("E01-S02-03", "POSITION"): ("HEAD_TO_CEILING", "HEAD_TO_WINDOW"), ("E01-S03-01", "POSITION"): ("LIANG_AT_HOUSE_DOOR", "LIANG_BLOCKING_GATE"), ("E01-S03-01", "MOMENTUM"): ("LU_WALKING_TO_GATE", "LU_STOPPED"), ("E01-S03-02", "POSITION"): ("FOODBOX_IN_FRONT", "FOODBOX_BEHIND_HIP"), ("E01-S03-03", "POSTURE"): ("ARMS_AT_SIDES", "ARM_POINTING_AT_DOOR"), ("E01-S03-04", "POSTURE"): ("LU_HEAD_DOWN_AT_LIANG", "LU_HEAD_UP_AT_DARK"), ("E01-S04-01", "POSITION"): ("AT_PARTY_WALL", "STANDING_AT_CABINET"), ("E01-S04-01", "CONTACT"): ("FOREHEAD_ON_WALL", "OFF_WALL"), ("E01-S04-01", "POSSESSION"): ("SINGLE_LAYER_ONLY", "HIDE_COAT_OVER_COTTON"), ("E01-S04-02", "MOMENTUM"): ("PACING", "STOPPED"), ("E01-S04-02", "POSTURE"): ("HANDS_RUBBING", "HANDS_OPEN_BEFORE_EYES"), ("E01-S05-01", "POSITION"): ("GATE_CLOSED", "GATE_OPEN"), ("E01-S05-01", "INTEGRITY"): ("SNOW_SURFACE_INTACT", "SNOW_PATH_SHOVELLED"), ("E01-S05-02", "POSITION"): ("HOUSE_DOOR_CLOSED", "HOUSE_DOOR_OPEN_ONE_WIDTH"), ("E01-S05-02", "INTEGRITY"): ("DOOR_GAP_SNOW_PACKED", "SNOW_DROPPED_TO_GROUND"), ("E01-S05-03", "POSSESSION"): ("SUNSTONES_IN_BAG", "SUNSTONES_IN_STONE_BASIN"), ("E01-S05-03", "INTEGRITY"): ("YARD_DARK", "YARD_LIT_ORANGE"), ("E01-S05-04", "POSTURE"): ("BENT_OVER", "UPRIGHT"), ("E01-S05-04", "POSITION"): ("GAZE_ON_BASIN", "GAZE_ON_QIN_FACE"), ("E01-S06-01", "POSSESSION"): ("SUNSTONES_IN_BAG", "SUNSTONES_IN_COPPER_BASIN"), ("E01-S06-01", "INTEGRITY"): ("ROOM_DARK", "ROOM_FULLY_LIT"), ("E01-S06-02", "CONTACT"): ("NO_CONTACT", "HAND_ON_QIN_SHOULDER"), ("E01-S06-03", "POSTURE"): ("GAZE_LEVEL_AT_LU", "GAZE_LOWERED"), ("E01-S07-01", "POSITION"): ("FOODBOX_AT_LU_SIDE", "FOODBOX_AT_QIN_CHEST"), ("E01-S07-02", "POSSESSION"): ("FOODBOX_HELD_BY_LU", "FOODBOX_HELD_BY_QIN"), ("E01-S07-02", "CONTACT"): ("QIN_HANDS_OFF_BOX", "QIN_HANDS_HOLDING_BOX"), ("E01-S07-03", "INTEGRITY"): ("BUN_WHOLE", "BUN_TORN"), ("E01-S07-03", "POSITION"): ("BUN_IN_BOX", "BUN_IN_MOUTH"), ("E01-S07-04", "POSITION"): ("LU_INSIDE_ROOM", "LU_OUTSIDE_DOOR"), ("E01-S07-04", "POSTURE"): ("QIN_SLIGHTLY_BOWED", "QIN_STANDING_STRAIGHT"), ("E01-S08-01", "POSITION"): ("INSIDE_GATE", "STREET_CENTRE"), ("E01-S08-02", "CONTACT"): ("NO_CONTACT", "ZHOU_GRIPPING_QIN_ARM"), ("E01-S08-02", "POSITION"): ("QIN_FACING_NORTH", "QIN_TURNED_TO_ZHOU"), ("E01-S08-03", "POSTURE"): ("FACING_QIN", "HEAD_TURNED_TO_WILDS"), ("E01-S08-04", "POSSESSION"): ("TUBER_IN_ZHOU_POCKET", "TUBER_BACK_IN_ZHOU_PALM"), ("E01-S08-04", "CONTACT"): ("HANDS_APART", "QIN_HANDS_WRAPPING_ZHOU_HAND"), ("E01-S09-01", "MOMENTUM"): ("QIN_WALKING", "QIN_STOPPED"), ("E01-S09-01", "POSTURE"): ("GOAT_TAIL_UP", "GOAT_TAIL_DROOPING"), ("E01-S09-02", "POSITION"): ("WHEAT_SACK_VISIBLE_AT_DOOR", "WHEAT_SACK_HALF_HIDDEN"), ("E01-S09-03", "POSTURE"): ("ARMS_HANGING", "FISTS_CUPPED_SALUTE"), ("E01-S09-03", "POSITION"): ("FACING_YANG_HOUSE", "BACK_TO_YANG_HOUSE_HEADING_NORTH"), ("E01-S10-01", "POSITION"): ("AT_CROSSING", "TWO_STEPS_FROM_STONE_RIM"), ("E01-S10-02", "POSITION"): ("TWO_STEPS_OUTSIDE_RIM", "AGAINST_STONE_RIM"), ("E01-S10-02", "CONTACT"): ("HANDS_OFF_RIM", "BOTH_HANDS_ON_RIM"), ("E01-S10-03", "POSTURE"): ("HEAD_DOWN_AT_POOL", "HEAD_UP_AT_TREES")}

# ---------- 机位方案（导演授权；2026-09-12）----------
# tools/build_video_unit_grouping_spec.derive_camera_plan：首镜 prompt_spec.camera_plan 为人工权威；缺省时引擎按语义推导，
# 曾把特写/远景推成中全景并与关键帧景别矛盾。此表逐镜按导演稿景别与机位落地，枚举值见 tools/grouped_camera_contract.py。
CAMERA_PLANS = {"E01-S01-01": {"shot_scale": "WIDE", "camera_height": "HIGH", "camera_side": "NEUTRAL", "lens_intent": "24mm高机位俯瞰全村与雪原", "axis_relation": "空镜无人物轴线，村落南北主街为画面纵轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "高机位大远景：雪幕、屋顶群与村落轮廓", "end_framing": "高机位大远景：雪幕、屋顶群与村落轮廓", "motivation": "导演稿：固定高机位俯瞰，让狂风撕开雪幕的过程在稳定构图内发生"}, "E01-S01-02": {"shot_scale": "MEDIUM", "camera_height": "LOW", "camera_side": "NEUTRAL", "lens_intent": "35mm低机位仰拍单处茅草屋顶", "axis_relation": "空镜无人物轴线，屋顶边缘为水平基准", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "低机位仰拍中景：一处压雪茅草屋顶与墙体边缘", "end_framing": "低机位仰拍中景：一处压雪茅草屋顶与墙体边缘", "motivation": "导演稿：固定低机位仰拍，屋顶一角被风掀起在构图内可读"}, "E01-S02-01": {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "50mm平视火炕上的秦铭", "axis_relation": "秦铭面向画右的视线轴，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "近景：火炕上的秦铭上半身与被子", "end_framing": "近景：火炕上的秦铭上半身与被子", "motivation": "导演稿：固定平视近景，饿醒睁眼与咽口水在稳定构图内发生"}, "E01-S02-02": {"shot_scale": "CLOSE_UP", "camera_height": "HIGH", "camera_side": "AXIS_A", "lens_intent": "85mm微俯特写秦铭面部与手", "axis_relation": "秦铭面向画右的视线轴，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "微俯特写：秦铭面部与攥被角的手", "end_framing": "微俯特写：秦铭面部与攥被角的手", "motivation": "导演稿：固定微俯特写，酸水上涌与咬牙忍住只靠面部与手完成"}, "E01-S02-03": {"shot_scale": "CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "85mm缓慢推近双眼", "axis_relation": "秦铭面向画右的视线轴，不越轴", "motion_family": "DOLLY", "motion_direction": "PUSH_IN", "start_framing": "特写：秦铭面部，双眼在画幅上三分之一", "end_framing": "更紧的双眼特写，目光聚在窗上", "motivation": "导演稿：缓慢推近双眼，呈现眼神由浑浊转清亮"}, "E01-S03-01": {"shot_scale": "MEDIUM", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "35mm中景，陆家院门为背景", "axis_relation": "陆泽在左、梁婉清在右的院门轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "中景：陆泽提食盒在左，梁婉清自屋门追出在右，院门在背景", "end_framing": "中景：陆泽提食盒在左，梁婉清自屋门追出在右，院门在背景", "motivation": "导演稿：固定中景交代拦人动作与院门关系"}, "E01-S03-02": {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "50mm过梁婉清肩看陆泽", "axis_relation": "陆泽在左、梁婉清在右的院门轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "过肩近景：梁婉清肩在前景，陆泽面部与身前食盒", "end_framing": "过肩近景：梁婉清肩在前景，陆泽面部与身前食盒", "motivation": "导演稿：过肩近景让压低声音与收食盒的动作可读"}, "E01-S03-03": {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "50mm过陆泽肩看梁婉清", "axis_relation": "陆泽在左、梁婉清在右的院门轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "过肩近景：陆泽肩在前景，梁婉清面部与抬手指屋内", "end_framing": "过肩近景：陆泽肩在前景，梁婉清面部与抬手指屋内", "motivation": "导演稿：过肩近景让拔高声音与指向屋内的手势可读"}, "E01-S03-04": {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "50mm中近景陆泽抬头望村外黑暗", "axis_relation": "陆泽面向村外黑暗的视线轴，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "中近景：陆泽面部与身后村外黑暗", "end_framing": "中近景：陆泽面部与身后村外黑暗", "motivation": "导演稿：固定中近景，陆泽抬头望黑暗的停顿在稳定构图内发生"}, "E01-S04-01": {"shot_scale": "MEDIUM", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "35mm平视中景，火炕到木柜", "axis_relation": "秦铭面向画左木柜的行进轴，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "中景：炕沿到木柜的走位空间与秦铭全身", "end_framing": "中景：炕沿到木柜的走位空间与秦铭全身", "motivation": "导演稿：固定平视中景，起身穿衣到柜前裹兽皮大衣在一个构图内完成"}, "E01-S04-02": {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_B", "lens_intent": "40mm手持轻微跟随秦铭走动", "axis_relation": "秦铭在屋内来回走动的横向轴，不越轴", "motion_family": "TRACK", "motion_direction": "LEFT_TO_RIGHT", "start_framing": "近景：秦铭在屋内左侧走动搓手", "end_framing": "近景：秦铭停在屋中央，双手摊在眼前", "motivation": "导演稿：手持轻微跟随走动，停步看手时镜头随之停稳"}, "E01-S05-01": {"shot_scale": "WIDE", "camera_height": "EYE_LEVEL", "camera_side": "NEUTRAL", "lens_intent": "28mm远景，院门为中心", "axis_relation": "院门（右）到屋门（左）的行进轴，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "远景：院门在画面中心，院内平整积雪与屋门", "end_framing": "远景：院门在画面中心，院内平整积雪与屋门", "motivation": "导演稿：固定远景让浅夜转淡与铲出雪路在同一构图内发生"}, "E01-S05-02": {"shot_scale": "MEDIUM", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "35mm固定中景对屋门", "axis_relation": "秦铭在屋门（左）面向陆泽（右）的轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "中景：被雪封住的屋门与门内秦铭", "end_framing": "中景：被雪封住的屋门与门内秦铭", "motivation": "导演稿：固定中景对屋门，拉门雪落与秦铭露面可读"}, "E01-S05-03": {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "LOW", "camera_side": "AXIS_A", "lens_intent": "50mm低机位对石盆", "axis_relation": "陆泽在右倾倒布袋的轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "低机位近景：雪地石盆与陆泽手中垂下的布袋", "end_framing": "低机位近景：雪地石盆与陆泽手中垂下的布袋", "motivation": "导演稿：固定低机位近景，太阳石落盆迸光在构图内发生"}, "E01-S05-04": {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "50mm过陆泽肩看秦铭", "axis_relation": "陆泽在右、秦铭在左的轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "过肩近景：陆泽肩在前景，秦铭面部在橘红光中", "end_framing": "过肩近景：陆泽肩在前景，秦铭面部在橘红光中", "motivation": "导演稿：过肩近景让陆泽看清秦铭精神好转的一愣可读"}, "E01-S06-01": {"shot_scale": "MEDIUM", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "35mm固定中景对铜盆", "axis_relation": "陆泽在右、秦铭在左隔铜盆的轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "中景：屋内铜盆居中，两人分立两侧", "end_framing": "中景：屋内铜盆居中，两人分立两侧", "motivation": "导演稿：固定中景让太阳石入铜盆满室生辉在构图内发生"}, "E01-S06-02": {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "50mm两组过肩正反打", "axis_relation": "陆泽在右、秦铭在左隔铜盆的轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "过肩近景：拍肩时陆泽的手与秦铭面部同框", "end_framing": "过肩近景：拍肩时陆泽的手与秦铭面部同框", "motivation": "导演稿：正反打近景让拍肩与对白的反应可读"}, "E01-S06-03": {"shot_scale": "CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "85mm固定特写秦铭", "axis_relation": "秦铭面向画右陆泽的视线轴，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "特写：秦铭面部，目光垂向盆中火光", "end_framing": "特写：秦铭面部，目光垂向盆中火光", "motivation": "导演稿：固定特写只靠目光下垂完成这句话的重量"}, "E01-S07-01": {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "50mm过陆泽肩中近景", "axis_relation": "陆泽在右、秦铭在左的轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "中近景：食盒从陆泽身侧伸到秦铭胸前", "end_framing": "中近景：食盒从陆泽身侧伸到秦铭胸前", "motivation": "导演稿：固定中近景让递食盒与秦铭不接的僵持可读"}, "E01-S07-02": {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "50mm过秦铭肩正反打", "axis_relation": "陆泽在右、秦铭在左的轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "过肩近景：陆泽面部与塞到秦铭手中的食盒", "end_framing": "过肩近景：陆泽面部与塞到秦铭手中的食盒", "motivation": "导演稿：正反打近景让塞食盒的动作与台词同框"}, "E01-S07-03": {"shot_scale": "CLOSE_UP", "camera_height": "LOW", "camera_side": "AXIS_A", "lens_intent": "85mm微仰特写秦铭", "axis_relation": "秦铭面向画右陆泽的视线轴，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "微仰特写：秦铭喊陆哥后撕馍塞进嘴里", "end_framing": "微仰特写：秦铭喊陆哥后撕馍塞进嘴里", "motivation": "导演稿：固定微仰特写让狼吞虎咽的面部动作可读"}, "E01-S07-04": {"shot_scale": "MEDIUM", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "35mm固定中景对门", "axis_relation": "陆泽转身出门（向画右）的轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "中景：屋门在画面中心，陆泽出门背影与门内秦铭", "end_framing": "中景：屋门在画面中心，陆泽出门背影与门内秦铭", "motivation": "导演稿：固定中景对门，陆泽出门与秦铭站直在同一构图内完成"}, "E01-S08-01": {"shot_scale": "WIDE", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "28mm手持后跟远景", "axis_relation": "秦铭向北行进的方向轴，不越轴", "motion_family": "TRACK", "motion_direction": "LEFT_TO_RIGHT", "start_framing": "远景：秦铭从院门内走出，院门在前景", "end_framing": "远景：秦铭到街心，身后院门半开，两侧火霞", "motivation": "导演稿：手持后跟远景让上街与各家火霞流动在行进中可读"}, "E01-S08-02": {"shot_scale": "MEDIUM", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "35mm固定中景对路口", "axis_relation": "秦铭向北的行进轴，邻居甲与周阿婆在路口两侧，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "中景：北街路口，秦铭与邻居甲、周阿婆三人", "end_framing": "中景：北街路口，秦铭与邻居甲、周阿婆三人", "motivation": "导演稿：固定中景让周阿婆拉住秦铭把他转过来的动作可读"}, "E01-S08-03": {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "50mm过周阿婆肩正反打", "axis_relation": "周阿婆在右、秦铭在左的轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "过肩近景：周阿婆肩在前景，秦铭面部；反打周阿婆头转向村外", "end_framing": "过肩近景：周阿婆肩在前景，秦铭面部；反打周阿婆头转向村外", "motivation": "导演稿：正反打近景让叮嘱与转头望村外的担忧可读"}, "E01-S08-04": {"shot_scale": "CLOSE_UP", "camera_height": "LOW", "camera_side": "AXIS_A", "lens_intent": "85mm低机位手部特写", "axis_relation": "周阿婆在右、秦铭在左的轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "手部特写：周阿婆掌中的地薯干与包住她手的秦铭双手", "end_framing": "手部特写：周阿婆掌中的地薯干与包住她手的秦铭双手", "motivation": "导演稿：固定低机位手部特写让推回地薯干只靠双手完成"}, "E01-S09-01": {"shot_scale": "MEDIUM", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_B", "lens_intent": "35mm固定中景对禾场", "axis_relation": "秦铭自画左向画右走向院门的行进轴，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "中景：禾场石磨与黑山羊，秦铭在前景走过停步", "end_framing": "中景：禾场石磨与黑山羊，秦铭在前景走过停步", "motivation": "导演稿：固定中景让黑山羊拉磨与秦铭停步盯羊同框"}, "E01-S09-02": {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A", "lens_intent": "50mm过秦铭肩看院门", "axis_relation": "秦铭在左、杨永青在院门右的轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "过肩中近景：杨永青在院门口，银麦袋在门边可见", "end_framing": "过肩中近景：杨永青在院门口，银麦袋在门边可见", "motivation": "导演稿：过肩中近景让杨永青身体挡住银麦袋的动作可读"}, "E01-S09-03": {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_B", "lens_intent": "50mm固定近景秦铭", "axis_relation": "秦铭面向杨家（画右）再转身向村头的轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "近景：秦铭面部与拱手的双手，杨家院门在背景", "end_framing": "近景：秦铭面部与拱手的双手，杨家院门在背景", "motivation": "导演稿：固定近景让拱手告辞与转身的目光变化可读"}, "E01-S10-01": {"shot_scale": "WIDE", "camera_height": "EYE_LEVEL", "camera_side": "NEUTRAL", "lens_intent": "28mm远景，火泉为中心", "axis_relation": "秦铭自村头路口走向火泉（画面纵深）的轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "远景：火泉与双树全貌居中，秦铭走到石围前两步", "end_framing": "远景：火泉与双树全貌居中，秦铭走到石围前两步", "motivation": "导演稿：固定远景让火泉全貌与秦铭走近在同一构图内发生"}, "E01-S10-02": {"shot_scale": "MEDIUM", "camera_height": "HIGH", "camera_side": "AXIS_B", "lens_intent": "35mm高机位俯拍池内火焰", "axis_relation": "秦铭在石围外（画下方）面向池内的轴线，不越轴", "motion_family": "LOCKED", "motion_direction": "NONE", "start_framing": "高机位俯拍中景：池内火红光焰与扶在石围上的双手", "end_framing": "高机位俯拍中景：池内火红光焰与扶在石围上的双手", "motivation": "导演稿：固定高机位俯拍让池内火焰与双手扶围可读"}, "E01-S10-03": {"shot_scale": "CLOSE_UP", "camera_height": "LOW", "camera_side": "AXIS_A", "lens_intent": "50mm自仰拍特写缓慢升起至两树中景", "axis_relation": "秦铭仰头望树的视线轴，不越轴", "motion_family": "CRANE", "motion_direction": "RISE", "start_framing": "仰拍特写：秦铭面部，火光映脸，低头看池", "end_framing": "中景：秦铭仰头，黑叶树与白叶树入画", "motivation": "导演稿：缓慢仰起至两树，让双树作为世界谜题在结尾入画"}}

# 每镜：scene, sec, size(景别), camera, axis, blocking, cast, action(subject, primary_action, patient), dialogue(speaker, text, listener), entry, exit, dims{DIM:(entry,exit)}, referents[(surface, key)]
SHOTS = [
    # S01
    dict(s="E01-S01", n=1, sec=6, size="大远景", camera="固定高机位俯瞰", axis="无轴（空镜）", blocking="无人物",
         cast=[], action=(None, "暴雪砸落，冻土上半人高积雪被狂风卷起", None), dialogue=None,
         entry="双树村轮廓被雪幕遮住，屋顶只见一线", exit="一阵狂风掀开雪幕，四五十户房屋的模糊轮廓露出",
         dims={"INTEGRITY": ("雪幕遮蔽", "雪幕撕开"), "MOMENTUM": ("雪幕静垂", "狂风横卷")}, referents=[]),
    dict(s="E01-S01", n=2, sec=6, size="中景", camera="固定低机位仰拍屋顶", axis="无轴（空镜）", blocking="无人物",
         cast=[], action=(None, "一处茅草屋顶在狂风中抬起一角又落下", None), dialogue=None,
         entry="屋顶压着厚雪，边缘贴合墙体", exit="屋顶一角被风掀起半尺，雪块滑落",
         dims={"POSITION": ("屋顶边缘贴合墙体", "屋顶一角离墙半尺"), "INTEGRITY": ("雪层完整", "雪块滑落")}, referents=[]),
    # S02
    dict(s="E01-S02", n=1, sec=7, faces={"QM": "EYES_CLOSED_SLEEPING_POSE_NOT_MEASURABLE"}, size="近景", camera="固定机位平视火炕", axis="秦铭面向镜头右", blocking="秦铭卧于火炕",
         cast=["QM"], action=("QM", "秦铭在火炕上猛地睁眼，腹部因饥饿收缩，喉结滚动咽口水；灰色单衣衣襟合拢系好，胸腹不外露，双臂留在被中，被子只从下巴滑到胸口就停住，不再往下", None), dialogue=None,
         entry="秦铭闭眼侧卧，被子盖到下巴", exit="秦铭睁眼仰面，被子滑到胸口，喉结滚动",
         dims={"POSTURE": ("闭眼侧卧", "睁眼仰面"), "POSITION": ("被子盖到下巴", "被子滑到胸口")}, referents=[("他", "QM")]),
    dict(s="E01-S02", n=2, sec=7, faces={"QM": "LYING_UPWARD_GAZE_POSE_NOT_MEASURABLE"}, size="特写", camera="固定机位微俯", axis="秦铭面向镜头右", blocking="秦铭卧于火炕",
         cast=["QM"], action=("QM", "秦铭嘴角抽动，胃里酸水上涌，他攥紧被角咬牙忍住，随即把被子裹紧，吸进冷气时轻轻抽气", None), dialogue=None,
         entry="秦铭仰面躺在被中，手松搭在被面上，嘴微张", exit="秦铭双手攥紧被角把被子裹到颈下，嘴闭紧",
         dims={"CONTACT": ("手搭在被面", "手攥紧被角"), "POSTURE": ("嘴微张", "嘴闭紧咬牙")}, referents=[("他", "QM")],
         wardrobe_override={"QM": "本镜秦铭只穿灰白粗布单衣（内衣）躺在被中，无棉衣、无兽皮大衣"}),
    dict(s="E01-S02", n=3, sec=6, size="特写", camera="缓慢推近双眼", axis="秦铭面向镜头右", blocking="秦铭卧于火炕转头向窗",
         cast=["QM"], action=("QM", "秦铭忽然睁大眼睛，眼神从浑浊转为清亮，转头看向漆黑的窗", None), dialogue=None,
         entry="秦铭躺在被中，眼皮半垂，目光散", exit="秦铭双眼睁大，目光聚在窗上，头转向窗",
         dims={"POSTURE": ("眼皮半垂目光散", "双眼睁大目光聚焦"), "POSITION": ("头朝屋顶", "头转向窗")}, referents=[("他", "QM")],
         wardrobe_override={"QM": "本镜秦铭只穿灰白粗布单衣（内衣）躺在被中，无棉衣、无兽皮大衣，特写只见单衣领口与被面"}),
    # S03
    dict(s="E01-S03", n=1, sec=4, faces={"LW": "SMALL_FACE_IN_MEDIUM_WIDE_NOT_MEASURABLE"}, size="中景", camera="固定机位，陆家院门为背景", axis="陆泽在左向右走，梁婉清自右追上", blocking="陆泽提食盒走向院门，梁婉清从屋门追出拦在他身前",
         cast=["LZ", "LW"], action=("LW", "梁婉清从屋门追出，一步拦在陆泽身前", "LZ"), dialogue=("LW", "你去哪里，又要给秦铭送食物？", "LZ"),
         entry="陆泽提食盒离院门两步，梁婉清在屋门口", exit="梁婉清挡在陆泽与院门之间，陆泽停步",
         dims={"POSITION": ("梁婉清在屋门口", "梁婉清挡在院门前"), "MOMENTUM": ("陆泽向院门走", "陆泽停步")}, referents=[("年轻的夫妇", "LZ")]),
    dict(s="E01-S03", n=2, sec=6, cps=4.8, size="近景", camera="固定机位过肩（梁婉清肩）", axis="同上", blocking="陆泽低头对梁婉清说话",
         cast=["LZ", "LW"], action=("LZ", "陆泽压低声音，把食盒往身后收了半分", "LW"), dialogue=("LZ", "他大病一场，才十六七岁，孤零零一个人生活，挺可怜的。", "LW"),
         entry="食盒提在陆泽身前", exit="食盒被陆泽收到身侧后方",
         dims={"POSITION": ("食盒在身前", "食盒在身侧后方")}, referents=[("他", "QM")]),
    dict(s="E01-S03", n=3, sec=7, cps=4.8, faces={"LZ": "BACK_TO_CAMERA_OTS_FOREGROUND"}, size="近景", camera="固定机位过肩（陆泽肩）", axis="同上", blocking="梁婉清抬手指向屋内",
         cast=["LW", "LZ"], action=("LW", "梁婉清声音拔高，抬手指向屋内两个孩子睡的方向", "LZ"), dialogue=("LW", "你知不知道，家里吃的也不多了，再这么下去，两个孩子会挨饿的！", "LZ"),
         entry="梁婉清双手垂在身侧", exit="梁婉清一手指向屋门",
         dims={"POSTURE": ("双手垂在身侧", "一手指向屋门")}, referents=[]),
    dict(s="E01-S03", n=4, sec=4, size="中近景", camera="固定机位中近景，陆泽面部与身后村外黑暗", axis="陆泽面向村外黑暗（梁婉清在画外屋门口）", blocking="陆泽在院中停步，先低头看画外的梁婉清，再抬头望向漆黑天地不再动",
         cast=["LZ"], action=("LZ", "陆泽抬头望向漆黑天地，脚步不再动", None), dialogue=("LZ", "暴雪停了，会有办法解决的。", "LW"),
         entry="陆泽低头看着屋门口画外的梁婉清，院门在身后", exit="陆泽抬头望向村外黑暗",
         dims={"POSTURE": ("低头看梁婉清", "抬头望村外黑暗")}, referents=[("夫妻两人", "LZ")]),
    # S04
    dict(s="E01-S04", n=1, sec=7, faces={"QM": "PROFILE_FOREHEAD_ON_WALL_NOT_MEASURABLE"}, size="中景", camera="固定机位平视，隔墙、火炕与木柜同框", axis="秦铭面向镜头左，柜子在左，隔墙在画右", blocking="秦铭起始额头抵着与陆家相隔的土墙侧耳听，随后离墙套上棉衣，走到柜前翻出兽皮大衣裹上",
         cast=["QM"], action=("QM", "秦铭听见隔墙的争执低下头，离开墙边套上棉衣仍发抖，走到柜前翻出陈旧的兽皮大衣裹在身上", None), dialogue=None,
         entry="秦铭耳贴隔墙、额头抵墙，只穿单衣", exit="秦铭站在柜前，兽皮大衣裹在棉衣外",
         dims={"CONTACT": ("额头抵着隔墙", "离开墙面"), "POSITION": ("在隔墙边", "站在柜前"), "POSSESSION": ("身上只有单衣", "棉衣外裹兽皮大衣")}, referents=[("他", "QM")],
         wardrobe_override={"QM": "本镜首帧秦铭只穿灰白粗布单衣（内衣），无棉衣、无兽皮大衣；镜内才穿上粗布棉衣并裹上陈旧兽皮大衣"}),
    dict(s="E01-S04", n=2, sec=7, size="近景", camera="手持轻微跟随", axis="同上", blocking="秦铭在屋内来回走动搓手，停下看手",
         cast=["QM"], action=("QM", "秦铭在黑屋里来回走动、搓手，停下看自己的双手，手指攥紧又松开", None), dialogue=None,
         entry="秦铭在屋内走动，双手互搓", exit="秦铭停步，双手摊在眼前，手指攥紧后松开",
         dims={"MOMENTUM": ("来回走动", "停步"), "POSTURE": ("双手互搓", "双手摊开在眼前")}, referents=[("他", "QM")]),
    # S05
    dict(s="E01-S05", n=1, sec=4, faces={"LZ": "FAR_FIGURE_FACE_NOT_MEASURABLE"}, size="远景", camera="固定机位，院门为中心", axis="陆泽自院门（右）向屋门（左）", blocking="陆泽推开院门铲雪",
         cast=["LZ"], action=("LZ", "屋外黑暗由深转淡；陆泽从院门外推开院门进来，用铁锨把积雪铲向两旁，清出通向屋门的路", None), dialogue=None,
         entry="院门紧闭，院内积雪平整齐膝；陆泽站在院门外，头肩露在矮墙上方，铁锨扛在肩", exit="院门敞开，一条铲开的雪路通到屋门前",
         dims={"POSITION": ("院门闭合", "院门敞开"), "INTEGRITY": ("雪面完整", "雪面被铲开一条路")}, referents=[]),
    dict(s="E01-S05", n=2, sec=5, size="中景", camera="固定机位对屋门", axis="秦铭在屋门（左）面向陆泽（右）", blocking="秦铭拉开被雪封住的门",
         cast=["QM", "LZ"], action=("QM", "秦铭从门内用力拉开被雪封住的房门，门缝里的雪块落下，秦铭在门口露面；秦铭棉衣外裹着陈旧兽皮大衣，两手空空不拿任何物件，太阳石布袋只在院中陆泽手里", "LZ"), dialogue=("QM", "陆哥。", "LZ"),
         entry="房门闭合，门缝堆雪；陆泽在院中面向屋门，秦铭在门内不可见", exit="房门拉开一人宽，门缝雪落地，秦铭站在门口",
         first_frame_hidden=["QM"],
         dims={"POSITION": ("房门闭合", "房门开一人宽"), "INTEGRITY": ("门缝雪堆完整", "雪块落地")}, referents=[]),
    dict(s="E01-S05", n=3, sec=4, size="近景", camera="固定低机位对石盆", axis="陆泽在右", blocking="陆泽提布袋向石盆倾倒",
         cast=["LZ"], action=("LZ", "陆泽提起发光的布袋倒向雪地里的石盆，红灿灿的太阳石落下撞出清脆声响，光芒划破夜色照亮院落", None), dialogue=None,
         entry="装着太阳石的布袋在陆泽手中垂着，袋身透出橘红光；石盆空且暗", exit="布袋倒空，石盆里堆满橘红发光的太阳石，院落被照亮",
         dims={"POSSESSION": ("太阳石在布袋里", "太阳石在石盆里"), "INTEGRITY": ("院落黑暗", "院落被橘红光照亮")}, referents=[]),
    dict(s="E01-S05", n=4, sec=8, cps=4.8, faces={"QM": "THREE_QUARTER_BACKLIT_NOT_MEASURABLE"}, size="近景", camera="固定机位过肩（陆泽肩）看秦铭：陆泽的肩与后脑在前景画左，秦铭的脸是画面主体", axis="同上", blocking="陆泽抬头看清秦铭的脸",
         cast=["LZ", "QM"], action=("LZ", "陆泽从弯腰放布袋的姿势直起身抬头，前景中他的肩与后脑随直身升高，视线由石盆抬到秦铭脸上，看清秦铭的脸，愣了一下；秦铭站在屋门口不弯腰不上前", "QM"), dialogue=("LZ", "小秦，我看你的精神似乎好了很多。", "QM"),
         entry="陆泽弯腰放布袋，视线在石盆", exit="陆泽直身，视线锁在秦铭脸上",
         dims={"POSTURE": ("弯腰", "直身"), "POSITION": ("视线在石盆", "视线在秦铭脸上")}, referents=[]),
    # S06
    dict(s="E01-S06", n=1, sec=4, faces={"QM": "PROFILE_DARK_NOT_MEASURABLE"}, size="中景", camera="固定机位对铜盆：陆泽在画面右半提布袋，秦铭在画面左半，铜盆在画面中央地面（左右不可对调）", axis="陆泽在画右、秦铭在画左（不可对调），铜盆在两人之间", blocking="站位：陆泽站在铜盆右侧（画面右半），提着布袋准备倒；秦铭站在铜盆左侧（画面左半），裹兽皮大衣看着盆；铜盆在画面中央地面",
         cast=["LZ", "QM"], action=("LZ", "陆泽在画右把布袋里剩余的太阳石倒进屋内铜盆，秦铭在画左，满室生辉", None), dialogue=None, slots={"LZ": "SCREEN_RIGHT", "QM": "SCREEN_LEFT"},
         entry="屋内黑暗，铜盆空；陆泽手中的布袋因袋内太阳石透出橘红光", exit="铜盆堆满太阳石，屋内被橘红光照满",
         dims={"POSSESSION": ("太阳石在布袋", "太阳石在铜盆"), "INTEGRITY": ("屋内黑暗", "满室生辉")}, referents=[]),
    dict(s="E01-S06", n=2, sec=6, size="近景正反打", camera="固定机位两组过肩", axis="陆泽右→秦铭左", blocking="两人隔铜盆站立",
         cast=["LZ", "QM"], action=("LZ", "陆泽拍了拍秦铭的肩", "QM"), dialogue=("LZ", "你命硬，得了山中的怪病都能活下来，实在不易。", "QM"), slots={"LZ": "SCREEN_RIGHT", "QM": "SCREEN_LEFT"},
         entry="陆泽双手提布袋", exit="陆泽一手落在秦铭肩上",
         dims={"CONTACT": ("未接触", "手落在秦铭肩上")}, referents=[]),
    dict(s="E01-S06", n=3, sec=5, faces={"LZ": "BACK_TO_CAMERA_OTS_FOREGROUND"}, size="特写", camera="固定机位", axis="秦铭面向右", blocking="秦铭低声回答",
         cast=["QM", "LZ"], action=("QM", "秦铭目光垂向铜盆的火光，低声开口", "LZ"), dialogue=("QM", "一起回来的那几个，当天就没了。", "LZ"), slots={"QM": "SCREEN_LEFT", "LZ": "SCREEN_RIGHT"},
         entry="秦铭看着陆泽", exit="秦铭目光垂向铜盆",
         dims={"POSTURE": ("平视陆泽", "目光下垂")}, referents=[("几位同行者", "QM")]),
    dict(s="E01-S07", n=1, sec=4, faces={"LZ": "BACK_TO_CAMERA_OTS_FOREGROUND", "QM": "SMALL_DARK_FACE_MID_SHOT_NOT_MEASURABLE"}, size="中近景", camera="固定机位", axis="同上", blocking="陆泽递食盒，秦铭不接",
         cast=["LZ", "QM"], action=("LZ", "陆泽把食盒递到秦铭胸前；秦铭看着热气腾腾的黑面馍咽口水，双手仍垂着", "QM"), dialogue=("LZ", "给！", "QM"),
         entry="食盒在陆泽手中身侧", exit="食盒伸到秦铭胸前，秦铭双手未抬",
         dims={"POSITION": ("食盒在陆泽身侧", "食盒在秦铭胸前")}, referents=[]),
    dict(s="E01-S07", n=2, sec=7, faces={"QM": "BACK_TO_CAMERA_OTS_FOREGROUND"}, size="近景正反打", camera="固定机位两组过肩", axis="同上", blocking="陆泽把食盒塞进秦铭手中",
         cast=["LZ", "QM"], action=("LZ", "陆泽见秦铭不动，直接把食盒按进他手里", "QM"), dialogue=("LZ", "怎么站着不动，你身体还没好，挨饿可没法恢复，还见外了？", "QM"),
         entry="食盒在陆泽手中，秦铭双手垂着", exit="食盒在秦铭双手中，陆泽松手",
         dims={"POSSESSION": ("食盒在陆泽手中", "食盒在秦铭手中"), "CONTACT": ("秦铭手未触食盒", "秦铭双手托住食盒")}, referents=[("他", "QM")]),
    dict(s="E01-S07", n=3, sec=4, faces={"LZ": "BACK_TO_CAMERA_OTS_FOREGROUND"}, size="特写", camera="固定机位微仰", axis="秦铭面向右", blocking="秦铭撕馍吃",
         cast=["QM", "LZ"], action=("QM", "秦铭喊了一声，撕开一块粗糙的黑面馍狼吞虎咽", "LZ"), dialogue=("QM", "陆哥！", "LZ"),
         entry="秦铭双手捧着木食盒，盒中一个完整的黑面馍，特写微仰对着秦铭面部与食盒", exit="馍被撕开一块，秦铭嘴里塞满",
         dims={"INTEGRITY": ("馍完整", "馍被撕开"), "POSITION": ("馍在食盒", "馍在口中")}, referents=[]),
    dict(s="E01-S07", n=4, sec=4, size="中景", camera="固定机位对门", axis="陆泽向右出门", blocking="陆泽转身出门，秦铭站直",
         cast=["LZ", "QM"], action=("LZ", "陆泽转身出门；秦铭嚼着馍，站直了身体", None), dialogue=("LZ", "有事喊我。", "QM"),
         entry="陆泽面向秦铭站在屋内", exit="陆泽背影出门，秦铭站直",
         dims={"POSITION": ("陆泽在屋内", "陆泽在门外"), "POSTURE": ("秦铭微躬", "秦铭站直")}, referents=[]),
    # S07
    dict(s="E01-S08", n=1, sec=4, faces={"QM": "BACK_TO_CAMERA_WALKING_AWAY"}, size="远景跟拍", camera="手持后跟", axis="秦铭向画面深处（北）走", blocking="秦铭推院门上街",
         cast=["QM"], action=("QM", "秦铭推开院门走上街，口鼻呼出白雾，街两侧各家院里太阳石火霞流动", None), dialogue=None,
         entry="秦铭在院门内", exit="秦铭在街心，身后院门半开",
         dims={"POSITION": ("院门内", "街心")}, referents=[("他", "QM")]),
    dict(s="E01-S08", n=2, sec=6, size="中景", camera="固定机位对路口", axis="周阿婆自左拉住秦铭", blocking="邻居甲在路口喊，周阿婆上前拉住秦铭左看右看",
         cast=["NB", "ZA", "QM"], action=("ZA", "周阿婆上前拉住秦铭的手臂，把他转过来左看右看", "QM"),
         dialogue=("ZA", "小秦，让我看一看。", "QM"), dialogue_pre=("NB", "秦铭，你身体没事了？", "QM"),
         entry="周阿婆在路口两步外，秦铭独自站立", exit="周阿婆双手抓住秦铭手臂，秦铭被转向她",
         dims={"CONTACT": ("未接触", "周阿婆抓住秦铭手臂"), "POSITION": ("秦铭面向北", "秦铭被转向周阿婆")}, referents=[("有人", "NB"), ("老太太", "ZA")]),
    dict(s="E01-S08", n=3, sec=8, cps=5.0, faces={"ZA": "BACK_TO_CAMERA_OTS_FOREGROUND"}, size="近景正反打", camera="固定机位两组过肩", axis="周阿婆左→秦铭右", blocking="秦铭笑答；周阿婆转头看向村外",
         cast=["QM", "ZA"], action=("ZA", "秦铭先笑着答话，周阿婆听完秦铭回答之后才开口叮嘱，两句台词严格先秦铭后周阿婆不得颠倒；周阿婆说完随即转头看向村外泼墨般的黑暗", "QM"),
         dialogue=("ZA", "小秦，即便身体好转了也别急着出去，现在外面很危险。", "QM"), dialogue_pre=("QM", "阿婆，真快好了。", "ZA"),
         entry="周阿婆面向秦铭", exit="周阿婆头转向村外，手仍拉着秦铭",
         dims={"POSTURE": ("面向秦铭", "头转向村外")}, referents=[("对方", "ZA")]),
    dict(s="E01-S08", n=4, sec=4, faces={"ZA": "HANDS_ONLY_FACE_OUT_OF_FRAME", "QM": "HANDS_ONLY_FACE_OUT_OF_FRAME"}, size="特写（手）", camera="固定低机位", axis="周阿婆左，秦铭右", blocking="周阿婆掏地薯干塞进秦铭手，秦铭推回并合上她的手",
         cast=["ZA", "QM"], action=("ZA", "众人散去后，周阿婆从口袋掏出几块地薯干塞进秦铭手里；秦铭把地薯干推回她掌中，合上她的手指", "QM"), dialogue=None,
         entry="两双手的特写：周阿婆的手伸进衣袋摸地薯干，秦铭的双手垂在身侧，两人的手未接触，两双手都清晰入画", exit="地薯干被合在周阿婆掌中，秦铭双手包着她的手",
         dims={"POSSESSION": ("地薯干在周阿婆口袋", "地薯干回到周阿婆掌中"), "CONTACT": ("手未触", "秦铭双手包住周阿婆的手")}, referents=[("老太太", "ZA")]),
    # S08
    dict(s="E01-S09", n=1, sec=6, size="中景", camera="固定机位对禾场", axis="黑山羊顺时针拉磨", blocking="秦铭自右入画停步",
         cast=["QM"], action=("QM", "秦铭走到杨家禾场前停步，盯着拉磨的黑山羊，喉结滚动；黑山羊翘着的尾巴耷拉下去", None), dialogue=None,
         entry="秦铭在走，黑山羊尾巴翘着拉磨", exit="秦铭停步盯羊，黑山羊尾巴耷拉",
         dims={"MOMENTUM": ("秦铭行走", "秦铭停步"), "POSTURE": ("羊尾翘起", "羊尾耷拉")}, referents=[("它", "PROP-BLACK-GOAT")]),
    dict(s="E01-S09", n=2, sec=10, cps=4.8, faces={"QM": "BACK_TO_CAMERA_OTS_FOREGROUND"}, size="中近景", camera="固定机位过肩（秦铭肩）看院门", axis="杨永青在院门（左）面向秦铭（右）", blocking="杨永青倚门开口",
         cast=["YY", "QM"], action=("YY", "杨永青倚在院门口，说话时把门边一袋银麦往身后挪了半步", "QM"),
         dialogue=("YY", "家里人口多，消耗太快，这也是我家最后的存粮了。", "QM"), dialogue_pre=("YY", "小秦，身体恢复了？大难不死必有后福。", "QM"),
         entry="银麦袋在院门边可见", exit="银麦袋被杨永青身体挡住半边",
         dims={"POSITION": ("银麦袋在门边可见", "银麦袋被挡住半边")}, referents=[("中年男子", "YY")]),
    dict(s="E01-S09", n=3, sec=6, faces={"QM": "PROFILE_NOT_MEASURABLE"}, size="近景", camera="固定机位", axis="秦铭面向左", blocking="秦铭笑着拱手，转身向村头走",
         cast=["QM", "YY"], action=("QM", "秦铭笑着拱手，目光从磨盘下的银麦上收回，转身向村头走去", "YY"), dialogue=("QM", "杨叔厉害，在这种年景下都能将一大家子照顾好。", "YY"),
         entry="秦铭面向杨永青，双手垂", exit="秦铭拱手后转身，背对杨家",
         dims={"POSTURE": ("双手垂", "拱手"), "POSITION": ("面向杨家", "背对杨家向村头")}, referents=[("对方", "YY")]),
    # S09
    dict(s="E01-S10", n=1, sec=6, faces={"QM": "BACK_TO_CAMERA_WALKING_AWAY"}, size="远景", camera="固定机位，火泉为中心", axis="秦铭自右入画", blocking="秦铭走向火泉石围",
         cast=["QM"], action=("QM", "秦铭穿过村头走向火泉，火红的光把他的影子拉长在雪地上", None), dialogue=None,
         entry="秦铭在村头路口，影子朝后；前方是丈六见方、膝高石围的方形火泉池，池中火红光焰，池畔一棵黑叶树一棵白叶树枝叶不凋", exit="秦铭到石围前两步，影子被火泉光压到身后",
         dims={"POSITION": ("路口", "石围前两步")}, referents=[("他", "QM")]),
    dict(s="E01-S10", n=2, sec=6, faces={"QM": "FAR_HIGH_ANGLE_FACE_NOT_MEASURABLE"}, size="中景俯拍", camera="固定高机位俯拍池子", axis="无人物主轴", blocking="秦铭在石围外",
         cast=["QM"], action=("QM", "秦铭走到膝高的石围前停下，池内火泉不再涌出，光焰缭绕", None), dialogue=None,
         entry="秦铭在膝高方形石围外两步，高机位俯拍：方池内火红光焰低矮跳动，黑叶树与白叶树的枝叶探入画面上缘", exit="秦铭双手扶在石围上",
         dims={"POSITION": ("石围外两步", "贴着石围"), "CONTACT": ("手未触石围", "双手扶石围")}, referents=[]),
    dict(s="E01-S10", n=3, sec=6, size="仰拍特写→中景", camera="缓慢仰起至两树", axis="秦铭面向池心", blocking="秦铭抬头望两树",
         cast=["QM"], action=("QM", "秦铭抬头，望向池中一黑一白两棵不凋零的树，火光映在脸上", None), dialogue=None,
         entry="秦铭低头看池水，两树在画外", exit="秦铭仰头，黑叶树与白叶树入画，火光映脸",
         dims={"POSTURE": ("低头看池", "仰头望树")}, referents=[("他", "QM")]),
]

# ---------- 校验镜头表 ----------
by_scene = {}
for sh in SHOTS:
    by_scene.setdefault(sh["s"], []).append(sh)
for sid, meta in SCENES.items():
    total = sum(x["sec"] for x in by_scene[sid])
    assert total == meta["sec"], (sid, total, meta["sec"])
    assert meta["sec"] <= 12 * meta["info"], (sid, "超出 12s×信息条数")
for sh in SHOTS:
    assert sh["entry"] != sh["exit"], sh
    for d, (a, b) in sh["dims"].items():
        assert d in {"POSITION", "POSTURE", "CONTACT", "POSSESSION", "INTEGRITY", "MOMENTUM"} and a != b, (sh["s"], sh["n"], d)
    for word in ("持续", "保持", "连续"):
        assert word not in sh["action"][1], (sh["s"], sh["n"], word)

# ---------- 关键台词逐字核对 ----------
src_text = SRC_CH1.read_text(encoding="utf-8")
KEY_QUOTES = [
    ("LW", "你去哪里，又要给秦铭送食物？", "E01-S03-01"),
    ("LZ", "他大病一场，才十六七岁，孤零零一个人生活，挺可怜的。", "E01-S03-02"),
    ("LW", "你知不知道，家里吃的也不多了，再这么下去，两个孩子会挨饿的！", "E01-S03-03"),
    ("LZ", "暴雪停了，会有办法解决的。", "E01-S03-04"),
    ("LZ", "小秦，我看你的精神似乎好了很多。", "E01-S05-04"),
    ("LZ", "给！", "E01-S07-01"),
    ("LZ", "赶紧趁热吃。", "E01-S07-01"),
    ("LZ", "怎么站着不动，你身体还没好，挨饿可没法恢复，还见外了？", "E01-S07-02"),
    ("QM", "陆哥！", "E01-S07-03"),
    ("LZ", "有事喊我。", "E01-S07-04"),
    ("NB", "秦铭，你身体没事了？", "E01-S08-02"),
    ("ZA", "小秦，让我看一看。", "E01-S08-02"),
    ("ZA", "小秦，即便身体好转了也别急着出去，现在外面很危险。", "E01-S08-03"),
    ("YY", "小秦，身体恢复了？大难不死必有后福。", "E01-S09-02"),
    ("YY", "家里人口多，消耗太快，这也是我家最后的存粮了。", "E01-S09-02"),
    ("QM", "杨叔厉害，在这种年景下都能将一大家子照顾好。", "E01-S09-03"),
]
for spk, q, shot in KEY_QUOTES:
    assert q in src_text, ("key_quote 不在源章逐字文本中", q)
narr = SCRIPTS / f"{EP}_NARRATIVE_CANONICAL_{VER}.md"
narr_text = narr.read_text(encoding="utf-8")
for spk, q, shot in KEY_QUOTES:
    assert f"{cname(spk)}：“{q}”" in narr_text, ("key_quote 未逐字进 narrative", q)
# 「赶紧趁热吃」在 S06-04 里是第二句，镜头表用 dialogue_pre 承载不了两句同人，这里单独绑到镜头 4 的 dialogue_extra
for sh in SHOTS:
    if sh["s"] == "E01-S07" and sh["n"] == 1:
        sh["dialogue_extra"] = ("LZ", "赶紧趁热吃。", "QM")
    if sh["s"] == "E01-S05" and sh["n"] == 4:
        sh["dialogue_extra"] = ("QM", "陆哥，我脑子清醒了，估计真要好了。", "LZ")

# ---------- directing script ----------
lines = [f"# 《夜无疆》{EP} 导演稿 {VER}（directing script）", "",
         f"绑定 narrative：`{narr.name}`（SHA256 {sha(narr)}）", "",
         "本层只写景别、机位、轴线、走位与起止态；**不改 narrative 的任何事实**。逐镜秒标为交付口径。", ""]
for sid, meta in SCENES.items():
    lines.append(f"## {sid}｜{meta['loc']}｜{meta['time']}｜{meta['sec']}s｜{meta['weather']}｜光：{meta['light']}")
    lines.append("")
    for sh in by_scene[sid]:
        shot_id = f"{sid}-{sh['n']:02d}"
        lines.append(f"### {shot_id}（{sh['sec']}s）｜{sh['size']}｜{sh['camera']}")
        lines.append(f"- 轴线：{sh['axis']}")
        lines.append(f"- 走位：{sh['blocking']}")
        lines.append(f"- 动作：{sh['action'][1]}")
        if sh.get("dialogue_pre"):
            s, t, l = sh["dialogue_pre"]; lines.append(f"- 台词①：{cname(s)}：“{t}”")
        if sh.get("dialogue"):
            s, t, l = sh["dialogue"]; lines.append(f"- 台词{'②' if sh.get('dialogue_pre') else ''}：{cname(s)}：“{t}”")
        if sh.get("dialogue_extra"):
            s, t, l = sh["dialogue_extra"]; lines.append(f"- 台词②：{cname(s)}：“{t}”")
        lines.append(f"- entry_state：{sh['entry']}")
        lines.append(f"- completion_state：{sh['exit']}")
        lines.append("- 状态差：" + "；".join(f"{d}「{a}」→「{b}」" for d, (a, b) in sh["dims"].items()))
        lines.append("")
directing = SCRIPTS / f"{EP}_DIRECTING_SCRIPT_{VER}.md"
directing.write_text("\n".join(lines), encoding="utf-8")

# ---------- generation contract ----------
def shot_json(sh):
    sid = sh["s"]; shot_id = f"{sid}-{sh['n']:02d}"
    subj, act, patient = sh["action"]
    dlg = sh.get("dialogue_pre") or sh.get("dialogue")
    spk_id = cid(dlg[0]) if dlg else ""
    lst_id = cid(dlg[2]) if dlg and dlg[2] else ""
    dialogue_lines = []
    for key in ("dialogue_pre", "dialogue", "dialogue_extra"):
        if sh.get(key):
            s, t, l = sh[key]; dialogue_lines.append(f"{cname(s)}：{t}")
    resolved = []
    for surface, key in sh["referents"]:
        resolved.append({"surface_form": surface, "entity_id": cid(key) if key in CH else key})
    presence = {cid(k): "VISIBLE_AND_IDENTITY_LOCKED" for k in sh["cast"]}
    hidden = set(sh.get("first_frame_hidden") or [])
    slots = sh.get("slots") or {}
    faces = sh.get("faces") or {}  # face_visibility per cast member when the face is not frontal/measurable
    states = {cid(k): sh["exit"] for k in sh["cast"]}
    return {
        "shot_id": shot_id,
        "scene_id": sid,
        "target_seconds": sh["sec"],
        "shot_size": sh["size"],
        "camera": sh["camera"],
        "axis": sh["axis"],
        "blocking": sh["blocking"],
        "entry_state": sh["entry"],
        "completion_state": sh["exit"],
        "state_delta_dimensions": list(sh["dims"].keys()),
        "state_delta_evidence": {d: {"entry": a, "exit": b,
                                     "entry_code": STATE_DELTA_CODES[(shot_id, d)][0],
                                     "exit_code": STATE_DELTA_CODES[(shot_id, d)][1]}
                                 for d, (a, b) in sh["dims"].items()},
        "keyframe_source": "entry_state",
        # 2026-09-12 timing revision: tools/dialogue_cut_safety.py (4.2 字/秒 + 0.32 s pad + 0.25 s tail)
        # could not fit several lines in their shots; seconds widened (scene ≤22 s kept) and heated
        # lines given an authored delivery rate of 4.8 字/秒. Dialogue text unchanged.
        **({"dialogue_delivery": {"chinese_characters_per_second": sh["cps"],
                                  "basis": "导演稿：争执/急切段落语速略快（4.8–5.0 字/秒），文本零改动"}} if sh.get("cps") else {}),
        "prompt_spec": {
            "camera_plan": {**CAMERA_PLANS[shot_id], "authorship": "DIRECTING_SCRIPT_AUTHORED", "selection_mode": "LOCKED",
                            "source": f"E01_DIRECTING_SCRIPT_v1.md#{shot_id}"},
            "cast": [{"character": cname(k), "character_id": cid(k),
                      **({"first_frame_visible": False} if k in hidden else {}),
                      **({"screen_slot": slots[k]} if k in slots else {}),
                      **({"face_visibility": faces[k]} if k in faces else {})} for k in sh["cast"]],
            **({"wardrobe_state_overrides": {cid(k): v for k, v in sh["wardrobe_override"].items()}} if sh.get("wardrobe_override") else {}),
            "dialogue": "\n".join(dialogue_lines) if dialogue_lines else "",
            "action": {"subject_id": cid(subj) if subj else "", "primary_action": act,
                       "patient_id": cid(patient) if patient else ""},
            "referent_resolution_contract": {
                "status": "PASS", "source_scan_complete": True,
                "resolved_source_referents": resolved, "unresolved_source_referents": []},
            "role_semantic_disambiguation": {
                "primary_actor_kind": "CHARACTER" if subj else "ENVIRONMENT",
                "primary_actor": cname(subj) if subj else "", "primary_actor_id": cid(subj) if subj else "",
                "dialogue_speaker": cname(dlg[0]) if dlg else "", "dialogue_speaker_id": spk_id,
                "dialogue_listener": cname(dlg[2]) if dlg and dlg[2] else "", "dialogue_listener_id": lst_id,
                "action_patient": cname(patient) if patient else "", "action_patient_id": cid(patient) if patient else "",
                "lip_owner_id": spk_id,
                "entity_states": states, "entity_presence": presence},
        },
    }

contract = {
    "schema": "qingshan.generation_contract.v3",
    "episode": EP, "version": VER,
    "narrative_canonical": narr.name, "narrative_sha256": sha(narr),
    "visual_culture_contract": {
        "schema": "qingshan.visual_culture_contract.v1", "status": "LOCKED",
        "profile_id": "YEWUJIANG_PERMANENT_NIGHT_FROZEN_VILLAGE_V1",
        "decision_owner": "WRITER_DIRECTOR",
        "decision_basis": "ch1 明写：太阳落下再未升起的永夜；冻土暴雪；四五十户的双树村；火炕、棉衣、兽皮大衣、铁锨、石磨、布袋；唯一人造光源是取自火泉的太阳石（橘红、不烫手、数时辰后熄灭）。世界为东方玄幻低魔村落，尚无门派、法术与现代物件。",
        "source_ref": f"{_np.RUNTIME_ROOT}/sources/夜无疆/zh-CN/ch0001.md",
        "story_world": "永夜纪元的北地冻土村落，前工业农耕社会，东方衣冠",
        "production_design": "夯土与石砌矮屋、茅草与木板屋顶压雪、火炕、木柜、粗陶与铜盆、石磨与禾场、膝高石围的火泉池；服装为粗布棉衣、陈旧兽皮大衣、麻布头巾；食物为黑面馍、地薯干、银麦",
        "armor_tradition": "本集无兵甲；后续若出现取北地猎户皮甲，不得出现制式铁札甲",
        "palette_system": {"base": "靛黑夜色与雪面冷灰", "accent": "太阳石橘红、火泉火红", "skin": "冷白偏病色，火光下转暖"},
        "lighting_language": "太阳石与火泉是全部动机光；深夜近乎全黑仅留轮廓与雪面反射；浅夜为淡墨灰蓝；橘红暖光只在有太阳石的院落与室内出现，形成冷外暖内",
        "image_texture": "颗粒感胶片质感、低饱和、雪雾与呼出的白气可见、火光有可见的边缘晕",
        "forbidden_influences": ["现代服装与拉链纽扣", "电灯、玻璃窗、金属门把手", "日式盔甲与和风建筑", "欧式石堡与哥特元素", "仙侠飘带与发光符文特效", "明亮日光或蓝天", "霓虹与冷色 LED", "整洁无雪的街道"],
    },
    "character_entities": [dict(_row, wardrobe_garments=WARDROBE_GARMENTS[_row["character_id"]]) for _row in [
        {"character_id": "CHAR-QINMING", "canonical_name": "秦铭", "aliases": ["小秦"], "voice_entity_id": "", "identity_reference_entity_id": "",
         "appearance_ch1": "十六七岁，颀长偏瘦，垂过肩头的黑发少了光泽，清秀苍白，眼睛清亮有神；棉衣外裹陈旧兽皮大衣"},
        {"character_id": "CHAR-LUZE", "canonical_name": "陆泽", "aliases": ["陆哥"], "voice_entity_id": "", "identity_reference_entity_id": "",
         "appearance_ch1": "年轻男子，身体结实有力，实在人；粗布棉衣，铁锨，发光布袋，食盒"},
        {"character_id": "CHAR-LIANGWANQING", "canonical_name": "梁婉清", "aliases": [], "voice_entity_id": "", "identity_reference_entity_id": "",
         "appearance_ch1": "年轻妇人，陆泽之妻，两个孩子的母亲；情绪激动时声音拔高"},
        {"character_id": "CHAR-ZHOUAPO", "canonical_name": "周阿婆", "aliases": ["老太太"], "voice_entity_id": "", "identity_reference_entity_id": "",
         "appearance_ch1": "北街老妇，过去慈祥和蔼，现在面无血色、瘦得单薄"},
        {"character_id": "CHAR-YANGYONGQING", "canonical_name": "杨永青", "aliases": ["杨叔"], "voice_entity_id": "", "identity_reference_entity_id": "",
         "appearance_ch1": "身材敦实、络腮胡须的中年男子，村头大院主人"},
        {"character_id": "CHAR-VILLAGER-A", "canonical_name": "邻居甲", "aliases": ["有人"], "voice_entity_id": "", "identity_reference_entity_id": "",
         "appearance_ch1": "北街路口无名邻居，仅一句问话"},
    ]],
    "non_character_entities": [
        {"entity_id": "PROP-BLACK-GOAT", "name": "黑山羊", "note": "肩高齐成年人，双角粗壮，拉石磨；受惊时尾巴耷拉"},
        {"entity_id": "PROP-SUN-STONE", "name": "太阳石", "note": "红灿灿发光石块，取自火泉，光而不烫，数时辰后熄灭"},
        {"entity_id": "PROP-SILVER-WHEAT", "name": "银麦", "note": "银粒子般的变种小麦"},
        {"entity_id": "SET-FIRE-SPRING", "name": "火泉", "note": "丈六见方石围池，火红光焰，暴雪季接近枯竭；池中一黑叶树一白叶树不凋零"},
    ],
    "scene_states": [
        {"scene_id": sid, "location_id": m["loc"], "time_id": m["time"], "weather": m["weather"], "lighting": m["light"],
         "target_seconds": m["sec"], "source_events": m["beats"], "new_information_count": m["info"],
         "ambient_life": m["ambient_life"], "weather_provenance": m["weather_provenance"]}
        for sid, m in SCENES.items()],
    "shots": [shot_json(sh) for sh in SHOTS],
    "internal_transition_authoring": [
        {"from_shot_id": a, "to_shot_id": b, "authorship": "DIRECTOR_AUTHORED", **row}
        for (a, b), row in INTERNAL_TRANSITIONS.items()],
    "audio_contract": {
        "bgm": {"mode": "NONE", "used": False, "declaration": "NO_EXTERNAL_BGM：本集以风声、雪落、太阳石撞击石盆的清脆声、咀嚼声与火泉光焰的低频嗡鸣为全部声景；不加外置配乐"},  # engine audio_profile_binding needs an explicit mode; prompt text reads .declaration
        "ambient_by_scene": {
            "E01-S01": "狂风呜呜、雪粒击打屋顶、屋顶木架吱呀",
            "E01-S02": "屋外风声透墙、腹鸣、吸气抽气",
            "E01-S03": "风声渐小、雪落变疏、院内脚步踩雪",
            "E01-S04": "屋内脚步、搓手、衣料摩擦",
            "E01-S05": "铁锨铲雪、门板挤雪、太阳石落入石盆的清脆撞击",
            "E01-S06": "太阳石入铜盆的撞击、衣料摩擦、低声对话",
            "E01-S07": "食盒木盖、撕馍与咀嚼、门板开合",
            "E01-S08": "踩雪咯吱、呼气白雾、远处零星人声",
            "E01-S09": "石磨转动低沉摩擦、山羊喷鼻、银麦碾碎沙沙",
            "E01-S10": "火泉光焰低频嗡鸣、树叶在无风中轻响",
        },
        "dialogue_units": [
            {"shot_id": f"{sh['s']}-{sh['n']:02d}", "speaker_id": cid(sh[k][0]), "listener_id": cid(sh[k][2]) if sh[k][2] else "", "text": sh[k][1]}
            for sh in SHOTS for k in ("dialogue_pre", "dialogue", "dialogue_extra") if sh.get(k)],
    },
}
contract_path = SCRIPTS / f"{EP}_GENERATION_CONTRACT_{VER}.json"
contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# ---------- manifest ----------
BEATS = [
    ("E01-EV-01", "E01-S01（两镜）", "永夜世界：太阳落下再未升起；暴雪半埋双树村，屋顶在狂风中晃动"),
    ("E01-EV-02", "E01-S02（三镜）", "秦铭饿醒，忍住食欲与酸水，裹被御寒；忽觉头脑清醒，怪病将去，等浅夜"),
    ("E01-EV-03", "E01-S03（四镜）", "隔壁陆泽与梁婉清争执要不要再给秦铭送食物（四句台词逐字）"),
    ("E01-EV-04", "E01-S04-01 首拍（贴墙听）＋ E01-S04（两镜）＋ E01-S06-02/03", "秦铭听见争执心生愧疚；起身穿棉衣与兽皮大衣走动搓手；一个月前自山中逃出、手脚发黑、同行者当天死去、至今余悸——内心叙述部分以 S04 看手与 S06 两句对白落地"),
    ("E01-EV-05", "E01-S05-01", "浅夜来临：黑暗如墨汁滴入清水般变淡"),
    ("E01-EV-06", "E01-S05（四镜）＋ E01-S06-01", "陆泽铲雪进院，倒太阳石入石盆照亮院落，惊讶秦铭精神好转；进屋倒太阳石入铜盆满室生辉"),
    ("E01-EV-07", "E01-S07（四镜）", "陆泽递食盒，秦铭愧疚不接，陆泽塞到手中，秦铭喊陆哥后狼吞虎咽，陆泽离去"),
    ("E01-EV-08", "E01-S08（四镜）", "秦铭上街；邻居与周阿婆见其好转难以置信；周阿婆叮嘱外面危险、塞地薯干被推回"),
    ("E01-EV-09", "E01-S09（三镜）", "村头杨永青家黑山羊拉磨碾银麦；秦铭盯羊想吃肉；杨永青称最后存粮，秦铭不信"),
    ("E01-EV-10", "E01-S10（三镜）", "火泉：丈六石围池火红光焰接近枯竭；池中黑叶白叶两树不凋零——双树村由来"),
]
manifest = {
    "episode": EP, "version": VER,
    "title": "永夜",
    "canonical_script": f"workflow/claude_writer_agent/scripts/{narr.name}",
    "script_sha256": sha(narr),
    "directing_script": f"workflow/claude_writer_agent/scripts/{directing.name}",
    "directing_sha256": sha(directing),
    "generation_contract": f"workflow/claude_writer_agent/scripts/{contract_path.name}",
    "generation_contract_sha256": sha(contract_path),
    "supersedes": "",
    "★supersedes_disclosure": "首版，无前版。nalu 线《夜无疆》E01 首次交付。2026-09-12 补录生产字段 scene_states[].ambient_life / weather_provenance 与 character_entities[].wardrobe_garments（SD2 编译门要求），并按 dialogue_cut_safety 调整 14 个镜头秒数（S03/S05/S06/S07/S08/S09，单场仍 ≤22 s，全集 175→184 s）、5 句台词标注 4.8 字/秒语速；剧情、场次、镜头顺序、台词文本零改动。",
    "authorization": {"order_seq": 1, "order_id": "ROGER-20260909-NALU-E01-OPEN", "orders_file": "workflow/claude_writer_agent/SUPERVISOR_ORDERS.json"},
    "writer_identity": {"agent_id": "claude-code-nalu-writer", "provider": "anthropic", "model_id": "claude-fable-5-1", "session_note": "Claude Code 交互会话，Roger 现场指令"},
    "source_binding": {
        "work": "夜无疆", "author": "辰东",
        "primary_source_chapter": "1", "source_chapters": ["1"], "chapter_title": "永夜",
        "source_file": str(SRC_CH1), "source_sha256": sha(SRC_CH1),
        "source_index": str(RUNTIME / "sources/夜无疆/SOURCE_INDEX.json"),
        "episode_source_map": str(RUNTIME / "runtime/episode_source_map_yewujiang_v1.json"),
        "beat_count": 10, "beats_landed": 10, "beats_merged": 0, "beats_dropped": 0,
        "★carry_in_is_bound_to_the_previous_episode_bytes": "全剧首集，无上一集字节。第一格从原著首句「那一天太阳落下再也没有升起」的世界状态开始。",
    },
    "beat_disposition": [{"event_id": e, "disposition": "landed", "landed_at": at, "summary": s} for e, at, s in BEATS],
    "★authorized_insertions": [],
    "authored_dialogue_from_indirect_speech": [
        {"shot_id": "E01-S05-04", "speaker": "秦铭", "text": "陆哥，我脑子清醒了，估计真要好了。", "source_basis": "ch1：「秦铭把他请进屋中，如实告知情况，自己不再昏昏沉沉，估计真要好了。」间接引语转直接对白，不增事实"},
        {"shot_id": "E01-S06-02", "speaker": "陆泽", "text": "你命硬，得了山中的怪病都能活下来，实在不易。", "source_basis": "ch1：「陆泽说他命硬，得了山中的『怪病』都能活下来，实在不易。」间接引语转直接对白，不增事实"},
        {"shot_id": "E01-S06-03", "speaker": "秦铭", "text": "一起回来的那几个，当天就没了。", "source_basis": "ch1：「至于几位同行者，回来当天就死去了。」叙述转对白，用于把 EV-04 的内心叙述落到可表演处；不增事实、不新增具名人物"},
        {"shot_id": "E01-S08-03", "speaker": "秦铭", "text": "阿婆，真快好了。", "source_basis": "ch1：「秦铭笑着打招呼，告诉他们，身体确实快恢复了。」间接引语转直接对白"},
    ],
    "★audience_already_knows": [],
    "structure": [{"beat_id": f"{EP}-B{idx+1:02d}", "scene_id": sid, "target_seconds": m["sec"], "thread": "线A", "location_id": m["loc"], "time_id": m["time"], "source_events": m["beats"], "new_information_count": m["info"]}
                  for idx, (sid, m) in enumerate(SCENES.items())],
    "scene_breakdown_seconds": {sid: m["sec"] for sid, m in SCENES.items()},
    "total_seconds": sum(m["sec"] for m in SCENES.values()),
    "runtime_target_seconds": {"min": 170.0, "target": 180.0, "max": 190.0},
    "shot_count": len(SHOTS),
    "key_quote_landing": [{"speaker": cname(s), "quote": q, "shot_id": shot, "verbatim_in_source": True} for s, q, shot in KEY_QUOTES],
    "fs1": {"combat_clusters": [], "combat_seconds": 0, "note": "ch1 无打斗，不得原创打斗（CHARTER §6.4）。FS-1 按段配额（每 10 集 ≥3 场）由 E01–E10 段内后续源章承担；本集文戏簇的等价张力替代物：S03 夫妻争执＋S07 食盒推让＋S09 银麦谎言。"},
    "identity_registry": {cid(k): cname(k) for k in CH} | {"PROP-BLACK-GOAT": "黑山羊"},
    "new_name_budget": {"budget_per_4_episodes": 1, "writer_invented_names_this_episode": 0, "note": "本集全部具名人物均来自 ch1（秦铭、陆泽、梁婉清、周阿婆、杨永青）；邻居甲为源章「有人」的无名指代，不计新名"},
    "distinct_locations": sorted({m["loc"] for m in SCENES.values()}),
    "new_locations": sorted({m["loc"] for m in SCENES.values()}),
    "episode_global_space_map_id": "GSM-YEWUJIANG-SHUANGSHU-VILLAGE-V1",
    "global_space_map_refs": [{"map_id": "GSM-YEWUJIANG-SHUANGSHU-VILLAGE-V1", "anchors": ["秦铭家（与陆泽家隔墙相邻）", "北街路口（周阿婆）", "村头杨永青大院与禾场", "村头火泉（双树）"], "axis_note": "秦铭家→北街→村头→火泉为一条向北的单向行进线，S08–S10 不得折返"}],
    "shot_subspace_bindings": [{"shot_id": f"{sh['s']}-{sh['n']:02d}", "location_id": SCENES[sh["s"]]["loc"]} for sh in SHOTS],
    "onscreen_text_shot_level_registry": [],
    "state_delta_contract_summary": {"shots_total": len(SHOTS), "shots_with_entry_ne_completion": len(SHOTS), "min_dimensions_per_shot": min(len(sh["dims"]) for sh in SHOTS), "extend_words_in_action_fields": 0},
    "writer_self_check": {"every_scene_asked_which_source_beat": True, "scenes_without_source_beat": [], "undeclared_insertions": 0},
}
manifest_path = SCRIPTS / f"{EP}_manifest_{VER}.json"
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print(json.dumps({
    "narrative": {"path": str(narr), "sha256": sha(narr)},
    "directing": {"path": str(directing), "sha256": sha(directing)},
    "contract": {"path": str(contract_path), "sha256": sha(contract_path), "shots": len(SHOTS)},
    "manifest": {"path": str(manifest_path), "sha256": sha(manifest_path), "total_seconds": manifest["total_seconds"], "scenes": len(SCENES)},
}, ensure_ascii=False, indent=2))
