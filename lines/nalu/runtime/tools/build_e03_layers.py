import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
# -*- coding: utf-8 -*-
"""E03《野外世界》v1 —— 从一张镜头表生成 directing script / generation contract / manifest。

单一事实源是 SHOTS 表；narrative canonical（E03_NARRATIVE_CANONICAL_v1.md）为手写，本层不改其任何事实与对白。
口径：seq=7（唐宋画风、节奏、机位运动）+ seq=10（nalu_prompt_rules 全镜套用、R7/R8 阻断）+ seq=12/13（远景接特写必须身份再锚定、
禁写全黑、儿童特写高风险）+ D-32 选择性配乐（audio_contract.bgm.mode=SELECTIVE）。
"""
import hashlib, json, pathlib, re
import nalu_prompt_rules as NPR

ROOT = pathlib.Path(f"{_np.ENGINE_ROOT}")
SCRIPTS = ROOT / "workflow/claude_writer_agent/scripts"
RUNTIME = pathlib.Path(f"{_np.RUNTIME_ROOT}")
SRC_CH3 = RUNTIME / "sources/夜无疆/zh-CN/ch0003.md"
QM_SOURCE_V2 = RUNTIME / "runtime/character_sources/CHAR-QINMING__SOURCE_V2_TANG.png"
EP, VER = "E03", "v1"
PREV_CONTRACT = SCRIPTS / "E02_GENERATION_CONTRACT_v1.json"

def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

CH = {
    "QM": ("CHAR-QINMING", "秦铭"),
    "LZ": ("CHAR-LUZE", "陆泽"),
    "VA": ("CHAR-VILLAGER-A", "邻居甲"),
    "VB": ("CHAR-VILLAGER-B", "村民乙"),
}
def cid(k): return CH[k][0]
def cname(k): return CH[k][1]

# ---------- 全局风格与节奏口径（沿 E02，seq=7） ----------
STYLE = {
    "profile_id": "YEWUJIANG_PERMANENT_NIGHT_TANGSONG_VILLAGE_V2",
    "era_idiom": "中国唐宋：木构穿斗/抬梁屋架、瓦顶或压雪茅顶带出檐、直棂格窗、夯土院墙与木板门；男子发髻木簪、交领右衽、大袖或窄袖袍、布带束腰、布靴裹腿；器物为粗陶、铜盆、木碗、竹筷、木柜、火炕；猎具为木柄铁头猎叉、直刃短刀、竹木弓与皮箭囊、兽皮袋",
    "night_look": "永夜用暖火光（太阳石橘红、火泉火红）+ 雪面反光 + 月色青蓝三种光写；野外浅夜为深青灰雪野、林木黑压压但轮廓可辨；不做西式暗黑/哥特式冷灰去饱和调色；肤色在火光下暖、在雪光下清",
    "forbidden": ["欧式石堡与哥特元素", "西式暗黑冷灰去饱和调色", "现代服装、拉链纽扣与现代物件", "电灯、玻璃窗、金属门把手", "日式盔甲与和风建筑", "仙侠飘带与发光符文特效", "明亮日光或蓝天", "霓虹与冷色 LED", "整洁无雪的街道", "长发散披不束的男主", "纯黑画面", "现代猎枪与金属机械捕兽夹"],
}
PERIOD_BASE = "唐宋语汇：木构、瓦顶/压雪茅顶、直棂格窗、夯土院墙、木板门；人物交领右衽、发髻木簪或包髻；器物粗陶木碗竹筷；猎具木柄铁头猎叉、直刃短刀、兽皮袋；夜景=暖火光+雪面反光+月色青蓝，不做冷灰去饱和"
PERIOD_BY_LOC = {
    "LOC-QINMING-HOUSE-INT": PERIOD_BASE + "；单间土屋：火炕在北墙、木格糊纸窗、旧木立柜、铜盆盛太阳石为唯一光源；无玻璃、无灯具、无现代家具",
    "LOC-FIRE-SPRING-EXT": PERIOD_BASE + "；火泉石围为粗凿青石，无雕花，无欧式石砌纹样；村道为踩实的雪路，两侧夯土院墙压雪；无人造灯具",
    "LOC-SNOWFIELD-WILDS-EXT": PERIOD_BASE + "；村外雪原：齐胸深的积雪、雪面月色青蓝反光、远处黑压压的林线；无道路、无栅栏、无任何人造物",
    "LOC-FOREST-EDGE-EXT": PERIOD_BASE + "；密林边缘：光秃的阔叶树枝上满是雪，樟子松与白桦树干，雪地；树洞为天然洞，无人工痕迹；无路标、无栅栏、无任何人造物",
    "LOC-LOW-HILL-TOP-EXT": PERIOD_BASE + "；矮山顶：雪石裸露的山顶，身后黑压压的林木，远处群山黑影与夜雾中朦胧的光；无任何人造物",
}
STYLE_RESET_DISCLOSURE = {
    "kind": "STYLE_CONTINUATION_NO_RESET",
    "authority": "SUPERVISOR_ORDERS seq=7 c1/c2/c4（E02 起唐宋画风）；seq=13（E03 沿用）",
    "what_changes": "无画风变化；本集首次进入村外野外（雪原、密林边缘、矮山顶），新地点按同一唐宋/永夜口径出卡",
    "what_stays": "秦铭面孔与发冠服制沿 E02 已锁定的 source_v2 身份牌；冬装、外披旧裘氅、内深青交领袍；同一时间线（E03-S01 直接接 E02-S13 终态）",
    "qinming_identity_source": {"file": str(QM_SOURCE_V2), "sha256": sha(QM_SOURCE_V2) if QM_SOURCE_V2.is_file() else "", "usage": "FACE_IDENTITY_REFERENCE + WARDROBE/HAIR STYLE REFERENCE（E02 已锁定的三视图身份牌直接复用，不重做）"},
    "viewer_facing_note": "E02→E03 画风与造型连续；邻居甲（E01 人物）按唐宋服制重出身份牌，面孔沿 E01",
}
PACING = {
    "authority": "Roger 2026-09-13：整体节奏偏慢 + 尽量加快节奏 + 编剧层固定机位静止段落太多；seq=10 R7/R8 自 E03 起阻断",
    "shot_seconds_default": [3, 5],
    "shot_seconds_max": 7,
    "shot_seconds_max_note": "本集无 7 s 镜；6 s 只用于按 nalu_prompt_rules.min_dialogue_seconds（字数/语速 + 1.0 s 起口 + 0.5 s 尾）确实放不进 5 s 的台词镜（E03-S10-02 / S12-01 / S12-02）",
    "video_unit_seconds_max": 6.0,
    "video_unit_seconds_hard_cap": 7.0,
    "video_unit_note": "写手层意图 ≤6 s；单元实际上限由引擎分组决定（seq=7 c3 硬上限 7 s；e16 偏好 4–6 s）",
    "no_dialogue_static_hold_seconds_max": 2.0,
    "no_dialogue_static_hold_verdict": "REJECT（生成后 QA 静止判定为拒收）",
    "scene_opening_rule": "每场第一镜从进行中的动作开始，不给建立镜头停顿；场与场之间在动作上切",
    "scene_turn_rule": "每场有转折与 button（见 directing script 每场末镜）",
    "hook_rule": "全集前 3 秒 = 短刀入腰带、拎猎叉（E03-S01-01）",
    "episode_total_seconds_target": [170, 185],
    "identity_reanchor_rule": "seq=12/13：同一场内远景小人影之后的同一人物露脸镜必须声明 identity_reanchor（引擎 e19 以角色板生成的关键帧作身份再锚定参考）",
    "no_black_rule": "seq=13：剧本与镜头文字不得写「全黑/极暗」；最暗时刻仍有雪面月色或余光照出轮廓",
    "camera_motion_policy": {
        "authority": "Roger 2026-09-13：「编剧层设计了太多固定机位的静止段落，修改这个问题」；校验器 nalu_runtime/runtime/tools/static_design_gate.py（E03 起 R1–R8 全部阻断）",
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
# ---------- END OF CHUNK 1 ----------

SCENES = {
    "E03-S01": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜·各家取太阳石的脚步与人声", light="铜盆太阳石橘红暖光", sec=12, beats=["E03-EV-01", "E03-EV-02", "E03-EV-03", "E03-EV-05"], info=2),
    "E03-S02": dict(loc="LOC-FIRE-SPRING-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·雪停·极冷", light="村道雪面月色青蓝反光，火泉火红光在村头", sec=11, beats=["E03-EV-06", "E03-EV-07", "E03-EV-08"], info=2),
    "E03-S03": dict(loc="LOC-SNOWFIELD-WILDS-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·极冷·雪原", light="雪面月色青蓝反光为唯一光，远处林线黑压压但轮廓可辨", sec=10, beats=["E03-EV-09", "E03-EV-10"], info=1),
    "E03-S04": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·林中无风·极冷", light="林间雪地反射的青蓝微光，树干轮廓可辨", sec=18, beats=["E03-EV-11", "E03-EV-12"], info=2),
    "E03-S05": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·寒风刮起", light="林间雪地青蓝微光，树冠上方是深青灰的夜空", sec=17, beats=["E03-EV-13", "E03-EV-14"], info=2),
    "E03-S06": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·林中·极冷", light="樟子松白桦林间雪地青蓝微光", sec=13, beats=["E03-EV-15", "E03-EV-16"], info=2),
    "E03-S07": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·地光一闪·寒风渐起", light="先雪地青蓝微光，霞光冲起瞬间整片密林亮成橘红，再回青蓝微光", sec=14, beats=["E03-EV-17", "E03-EV-18", "E03-EV-19"], info=2),
    "E03-S08": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·寒风", light="雪地青蓝微光，树洞内深褐", sec=18, beats=["E03-EV-20", "E03-EV-21"], info=2),
    "E03-S09": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·寒风", light="手中太阳石橘红光照亮树洞与红松鼠，四周仍是青蓝微光", sec=14, beats=["E03-EV-22", "E03-EV-23"], info=2),
    "E03-S10": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·寒风", light="太阳石橘红光随人移动照亮树干与树洞", sec=16, beats=["E03-EV-24"], info=2),
    "E03-S11": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·寒风", light="太阳石橘红光在雪地上，映亮秦铭的脸与倒挂的红松鼠", sec=15, beats=["E03-EV-25", "E03-EV-26"], info=2),
    "E03-S12": dict(loc="LOC-FIRE-SPRING-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·雪停", light="火泉火红光映亮石围旁三人的脸", sec=12, beats=["E03-EV-27"], info=1),
    "E03-S13": dict(loc="LOC-LOW-HILL-TOP-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·山顶寒风·夜雾", light="雪面月色青蓝反光，远处夜雾深处漾出少许朦胧的暖光", sec=12, beats=["E03-EV-28", "E03-EV-29"], info=2),
}
AMBIENT_LIFE = {
    "E03-S01": {"grade": "C", "motion_trend": "屋外脚步与人声、铜盆火霞在墙上晃动、衣料摩擦、猎叉木柄碰炕沿", "first_frame_state": "秦铭已站在炕边，短刀在右手，屋外人声正响", "reaction_progression": "短刀入腰带拎猎叉→看木碗碎渣、背弓走向门→门口回头看炕说一句"},
    "E03-S02": {"grade": "B", "motion_trend": "村道渐静、两位村民迎面走来、呼出白气、火泉火光在村头跳动", "first_frame_state": "秦铭提猎叉正走上村道，两位村民自前方走来", "reaction_progression": "迎面遇村民→笑着抬手打招呼脚步不停→村民愣住他已远去→路过火泉走进雪野"},
    "E03-S03": {"grade": "B", "motion_trend": "积雪随跋涉塌陷、呼出的白雾、眉毛发梢结霜、远处林线轮廓渐近", "first_frame_state": "秦铭已在齐胸深的雪里跋涉", "reaction_progression": "雪没胸口跋涉→白雾结霜→前方林线黑压压显出轮廓"},
    "E03-S04": {"grade": "B", "motion_trend": "跨进林缘落下枝上积雪、停步转身看树洞、怪鸟啼鸣、继续前行", "first_frame_state": "秦铭正跨进密林边缘", "reaction_progression": "跨进林缘→停步看树洞回想→说变异与主巢两句→怪鸟啼鸣继续向前走"},
    "E03-S05": {"grade": "A", "motion_trend": "身体绷紧、持叉扫视、猛然上刺、黑影俯冲、猎叉迎击尖叫、双翼展开冲上夜空", "first_frame_state": "秦铭正走着，身体猛地绷紧", "reaction_progression": "闻腐臭绷紧→双手持叉扫视→猛然向头顶刺去→惨白老人脸俯冲扑来→猎叉迎击尖叫、滑向一旁展翼远去"},
    "E03-S06": {"grade": "B", "motion_trend": "持叉戒备、重新上路走进松桦林、凑近看树洞、直起身握叉攥刀", "first_frame_state": "秦铭持叉戒备，正抬脚重新上路", "reaction_progression": "戒备许久重新上路→「应该就是这里」→树洞边缘干净无霜→皱眉握叉攥刀"},
    "E03-S07": {"grade": "A", "motion_trend": "蹲下看爪印、霞光冲起照亮密林、一惊转身扫视、霞光消失、盯住结冰花的树洞、灿烂笑容", "first_frame_state": "秦铭正蹲下身看雪地上的爪印", "reaction_progression": "蹲下看爪印「有门」→霞光冲起一惊转身→霞光消失盯住另一树洞→洞口冰花、灿烂笑容"},
    "E03-S08": {"grade": "A", "motion_trend": "蹑手蹑脚踏雪、插叉、跳起攀树、挥刀砍洞、生物缩回、树体碎裂、套袋探臂、洞里乱撞、薅出猎物", "first_frame_state": "秦铭正蹑手蹑脚踏雪走向大树", "reaction_progression": "到树前插叉→跳起攀到洞前→挥刀砍洞生物缩回→连挥刀洞变大→套兽皮袋探臂洞里乱撞→一把抓住薅出"},
    "E03-S09": {"grade": "B", "motion_trend": "太阳石光照进树洞、眼中火热、侧头看小兽、火红皮毛发光啃袋、铁丝捆挂、一把把掏干果袋鼓胀", "first_frame_state": "秦铭已举起太阳石正照向树洞深处", "reaction_progression": "照见满洞干果眼中火热→侧头看小兽皮毛发光→它啃兽皮袋→铁丝捆紧挂枝→俯身掏干果袋鼓胀"},
    "E03-S10": {"grade": "B", "motion_trend": "倒挂松鼠瞪眼吱吱、掂袋、挂上猎叉、持太阳石走动找洞、第二第三树洞、最早的树洞满干果", "first_frame_state": "红松鼠倒挂在树枝上正吱吱叫", "reaction_progression": "松鼠瞪眼骂人→掂袋挂猎叉说一句→持太阳石找到第二第三树洞→最早那洞也满干果"},
    "E03-S11": {"grade": "B", "motion_trend": "剥核桃、吃栗子、雪搓红枣入口、笑容、松鼠僵住、摇它、说一句", "first_frame_state": "秦铭正剥开一颗野核桃", "reaction_progression": "剥核桃吃栗子→雪搓红枣吃五颗满嘴甜、笑→松鼠看巢穴搬空僵住不动→诧异摇它「正好煮肉汤」"},
    "E03-S12": {"grade": "B", "motion_trend": "两位村民交谈比划、火泉火光跳动、陆泽走来站住眉头深锁", "first_frame_state": "两位村民已在石围旁说话，村民乙正比划", "reaction_progression": "村民乙说秦铭全副武装去野外→陆泽走来站住皱眉「该不会去猎熊」"},
    "E03-S13": {"grade": "B", "motion_trend": "背袋爬上山顶、寒风吹动裘氅与松鼠、夜雾深处微光漾动", "first_frame_state": "秦铭背着鼓胀的兽皮袋正爬上矮山顶最后几步", "reaction_progression": "爬上山顶→望林木与群山黑影、夜雾深处漾出光→「那里还不是我能去的地方」"},
}
def _wp(sid, mode):
    return {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": f"E03_NARRATIVE_CANONICAL_v1.md#{sid}｜ch3", "visibility_mode": mode}
WEATHER_PROVENANCE = {sid: _wp(sid, "OFFSCREEN_ONLY_SHALLOW_NIGHT_THROUGH_DOOR_INTERIOR_DRY" if m["loc"].endswith("-INT") else "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED") for sid, m in SCENES.items()}
for _sid, _m in SCENES.items():
    _m["ambient_life"] = AMBIENT_LIFE[_sid]
    _m["weather_provenance"] = WEATHER_PROVENANCE[_sid]

# ---------- 服装（唐宋语汇；承接 E02：冬装、外披旧裘氅） ----------
WARDROBE_GARMENTS = {
    "CHAR-QINMING": {"silhouette": "颀长清瘦、高髻木簪、外披过膝旧裘氅、内交领深色袍；本集全副武装外出", "outer_layer": "陈旧兽皮裘氅（毛面磨秃、下摆结霜，无袖披式）", "inner_layer": "深青交领右衽窄袖袍，领缘与袖口银线滚边（旧、洗淡）", "primary_color": "灰褐（裘氅）", "secondary_color": "深青（袍）", "material": "兽皮＋粗麻棉", "pattern": "裘氅素面磨秃；袍领袖银线细纹", "belt_or_fastening": "布带束腰（腰间插直刃短刀），裘氅前襟布带系结", "footwear": "旧布靴加裹腿（雪野中结霜）", "accessory": "发髻木簪（源照片同款发式）；背负竹木弓与皮箭囊"},
    "CHAR-LUZE": {"silhouette": "壮实宽肩、束发裹巾、齐膝交领短褐", "outer_layer": "深灰粗麻交领短褐（外层）", "inner_layer": "灰白中衣", "primary_color": "深灰", "secondary_color": "灰褐（腰带）", "material": "粗麻棉", "pattern": "粗织纹，肩背补丁与磨痕", "belt_or_fastening": "麻布腰带打结", "footwear": "裹腿加旧皮靴", "accessory": "灰布裹巾束发"},
    "CHAR-VILLAGER-A": {"silhouette": "中等瘦削、宽腰带短袍、麻布头巾", "outer_layer": "深灰褐粗麻交领右衽齐膝短褐（外层）", "inner_layer": "灰白粗麻中衣", "primary_color": "深灰褐", "secondary_color": "灰（头巾）", "material": "粗麻棉", "pattern": "粗织横纹", "belt_or_fastening": "宽布腰带打结", "footwear": "布鞋裹腿", "accessory": "麻布头巾包髻"},
    "CHAR-VILLAGER-B": {"silhouette": "矮壮圆脸、皮帽、旧棉袍", "outer_layer": "灰褐粗麻交领右衽棉袍（外层，膝下）", "inner_layer": "褐色粗麻中衣", "primary_color": "灰褐", "secondary_color": "黑褐（皮帽）", "material": "粗麻棉＋兽皮", "pattern": "素面，前襟磨旧", "belt_or_fastening": "布带束腰", "footwear": "旧皮靴裹腿", "accessory": "兽皮护耳帽"},
}

# ---------- 道具与生物（seq=7 c6：关键道具出参考卡；只列 narrative 实际用到的） ----------
PROPS = [
    {"entity_id": "PROP-HUNTING-FORK", "name": "猎叉", "reference_card_required": True, "first_shot": "E03-S01-01",
     "note": "木柄铁头猎叉：长约一人高，硬木直柄，铁制双股或三股叉头，叉头略有磨痕；能插在雪里、能挂猎物", "period_constraints": "唐宋农猎器具语汇，锻铁叉头、麻绳缠柄；无现代金属管、无螺栓"},
    {"entity_id": "PROP-SHORT-KNIFE", "name": "短刀", "reference_card_required": True, "first_shot": "E03-S01-01",
     "note": "直刃短刀：刃长一尺，木柄缠麻绳，无鞘时插在腰间布带里；砍树洞口时刃口向外", "period_constraints": "唐宋直刀形制，无护手大盘、无现代刀具纹样"},
    {"entity_id": "PROP-BOW-ARROWS", "name": "弓箭", "reference_card_required": False, "first_shot": "E03-S01-02",
     "note": "竹木短弓与皮箭囊，斜背在裘氅外；本集只背不用，不单独出卡", "period_constraints": "唐宋竹木弓与皮箭囊，无金属滑轮"},
    {"entity_id": "PROP-HIDE-BAG", "name": "兽皮袋", "reference_card_required": True, "first_shot": "E03-S08-04",
     "note": "厚兽皮缝制的口袋，毛面朝内，袋口有皮绳；先干瘪套在手上作捕兽手套，后装满干果鼓胀，可背", "period_constraints": "手缝皮袋，无拉链、无金属扣"},
    {"entity_id": "PROP-NUT-HOARD", "name": "干果", "reference_card_required": True, "first_shot": "E03-S09-01",
     "note": "树洞里的存粮：野核桃、栗子、红枣混堆，干瘪但饱满，在太阳石橘红光下显出褐、棕、深红三色", "period_constraints": "真实野果，不做卡通化、无包装"},
    {"entity_id": "PROP-HUMANFACE-VULTURE", "name": "人面鹫", "reference_card_required": True, "first_shot": "E03-S05-04",
     "note": "食腐猛禽：灰黑色的鹰身，翼展宽阔强劲，整张面孔除却鸟喙外与带皱纹的惨白老人脸无异，体重不过四十斤；倒吊在高树杈上，俯冲后滑向一旁展翼冲上夜空", "period_constraints": "写实猛禽与惨白人脸的结合，不做卡通或仙侠妖化，不发光"},
    {"entity_id": "PROP-RED-SQUIRREL", "name": "红松鼠", "reference_card_required": True, "first_shot": "E03-S09-02",
     "note": "变异红松鼠：足有两斤多，全身火红晶莹的皮毛在太阳石光下比绸缎还丝滑、微微发光，黑宝石般的圆眼；气性极大，被捆倒挂时吱吱叫个不停，看到巢穴被搬空后直挺挺僵住不动", "period_constraints": "写实松鼠体态，皮毛发光只是柔和的光泽，不做光环特效"},
]
SETS = [
    {"entity_id": "SET-FIRE-SPRING", "name": "火泉", "note": "丈六见方石围池，火红光焰；E01/E02 已建立，本集 S02 路过、S12 石围旁议论，不复证形制"},
    {"entity_id": "SET-FOREST-EDGE-WOODS", "name": "密林边缘林地", "reference_card_required": True, "first_shot": "E03-S04-01",
     "note": "浅夜密林边缘的林地基准：前景光秃阔叶树枝上满雪，中景樟子松与白桦树干，雪地泛月色青蓝反光，林深处黑压压但轮廓可辨；无路、无人造物、无人物", "period_constraints": "天然林地，无任何人造物；不做西式暗黑冷灰去饱和"},
    {"entity_id": "SET-HOLLOW-TREE", "name": "树洞大树", "reference_card_required": True, "first_shot": "E03-S07-04",
     "note": "水桶粗的枯干大树，离地一人多高处有一个树洞，洞口结着冰花；洞口不大，被短刀砍大后露出洞内深褐的干枯木质；旁边雪地上有一串小小的爪印", "period_constraints": "天然枯树，无人工痕迹"},
]
# ---------- END OF CHUNK 2 ----------

# ---------- 机位方案（导演授权；camera_motion_policy：LOCKED ≤35%、不连续、无对白必动、开场必动；R7：无对白 ≥3 s 需身体动词或 ARC/TRACK/CRANE/PAN） ----------
def _cp(scale, height, side, lens, axis, fam, direction, start, end, why):
    if fam == "LOCKED" and end != start:
        why = f"{why}；画内变化：{end}"
        end = start
    return {"shot_scale": scale, "camera_height": height, "camera_side": side, "lens_intent": lens, "axis_relation": axis,
            "motion_family": fam, "motion_direction": direction, "start_framing": start, "end_framing": end, "motivation": why}
CAMERA_PLANS = {
    # S01 屋内出发
    "E03-S01-01": _cp("CLOSE_UP", "LOW", "AXIS_A", "85mm低机位手部特写：只取腰腹局部（右手、短刀、腰间布带、猎叉木柄），不见脸、不见全身、不见屋内全貌；随起身上升到拎起的猎叉", "秦铭面向屋门（画右）的轴线，不越轴", "CRANE", "RISE", "低机位手部特写：画面只有右手把短刀插进腰间布带，裘氅前襟与猎叉木柄在画缘，不见脸、不见全身", "低机位特写偏松：右手拎起靠在炕边的猎叉，叉头入画", "导演稿：开场 3 秒钩子，短刀入腰带、拎猎叉，机位随动作上升"),
    "E03-S01-02": _cp("MEDIUM", "HIGH", "AXIS_B", "35mm俯拍自炕沿木碗横移跟随走向屋门", "炕（画左）到屋门（画右）的行进轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "俯拍中景：炕沿木碗只剩面饼碎渣，秦铭的手拿起弓箭", "俯拍中景：秦铭背上弓箭走向屋门，木碗留在炕沿", "导演稿：横移让「碎渣—没告诉陆泽—走向门」在一个运动里完成"),
    "E03-S01-03": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm门口固定，秦铭回头看炕", "秦铭在门口面向屋内（画左）的视线轴，不越轴", "LOCKED", "NONE", "中近景：秦铭站在屋门口，回头看向炕", "中近景：秦铭说完一句，转回身面向门外", "导演稿：固定（对白镜 ≤5 s），回头与说完转身本身带动"),
    # S02 村道与火泉
    "E03-S02-01": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm手持自身后跟随走上村道", "村内（画左）到村头火泉（画右）的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中全景：秦铭提猎叉走上安静的村道，前方两位村民迎面走来", "中全景：秦铭与两位村民相距两步，村民抬头", "导演稿：跟随走上村道，迎面遇村民在行进中发生"),
    "E03-S02-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm环绕交错的三人", "秦铭向右行进、村民向左行进的相向轴，环绕不越轴", "ARC", "CLOCKWISE", "中近景：秦铭笑着抬手打招呼，脚步不停", "中近景：两位村民愣在原地回头，秦铭的背影已快步远去", "导演稿：环绕把「笑着打招呼—对方没反应过来—已远去」连成一个动作（原著幽默）"),
    "E03-S02-03": _cp("WIDE", "HIGH", "NEUTRAL", "24mm高机位随他走过火泉上升", "火泉（画左）到村外雪野（画右）的行进轴，不越轴", "CRANE", "RISE", "高机位远景：秦铭走过火泉石围，火红光照在他侧身", "高机位远景（升起）：秦铭走出火光范围，进入深青灰的雪野", "导演稿：升起让火光与雪野的边界成为场尾 button"),
    # S03 雪原
    "E03-S03-01": _cp("WIDE", "EYE_LEVEL", "AXIS_A", "24mm横移跟随跋涉", "秦铭向画右跋涉的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "远景：雪原上秦铭只露出胸口以上，猎叉举在雪面之上", "远景：他向前推进几步，身后留下一道雪沟", "导演稿：横移跟随让「雪没胸口」在运动中被读到"),
    "E03-S03-02": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_B", "85mm环绕面部，白雾与霜", "秦铭面向画右的视线轴，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "特写：秦铭呼出的白雾扑在眉毛上", "特写（环绕至侧面）：眉毛和发梢结上冰霜", "导演稿：环绕读白雾结霜，远景之后的露脸镜按 seq=13 声明身份再锚定"),
    "E03-S03-03": _cp("MEDIUM_WIDE", "LOW", "AXIS_A", "28mm低机位随前行升起，露出前方林线", "秦铭向画右的行进轴，不越轴", "CRANE", "RISE", "低机位中全景：秦铭手持猎叉深一脚浅一脚推进", "低机位中全景（升起）：前方黑压压的密林轮廓在雪面上方显出", "导演稿：升起把目的地林线作为场尾 button"),
    # S04 密林边缘
    "E03-S04-01": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm手持跟随跨进林缘", "雪原（画右）到林缘（画左）的行进轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中全景：秦铭跨进密林边缘，枝上积雪被碰落", "中全景：秦铭站在光秃的树间，树枝上满是雪", "导演稿：跟随进林，不给建立停顿"),
    "E03-S04-02": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm横摇自秦铭转向他看的树洞", "秦铭（画左）看向树上树洞（画右）的视线轴，不越轴", "PAN", "LEFT_TO_RIGHT", "中景：秦铭停下脚步转身", "中景（摇到树）：一棵树上的树洞在画右，秦铭在画左盯着它", "导演稿：横摇跟随视线到树洞，读「回想活动轨迹」"),
    "E03-S04-03": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_A", "85mm固定面部特写", "秦铭面向树洞（画右）的视线轴，不越轴", "LOCKED", "NONE", "特写：秦铭盯着树洞开口说话", "特写：一句说完，眼神收回", "导演稿：固定（对白镜 ≤5 s），说话本身带动"),
    "E03-S04-04": _cp("MEDIUM_CLOSE_UP", "LOW", "AXIS_B", "50mm低机位环绕到他继续前行", "秦铭由面向树转为面向林深处（画左）的轴线，环绕不越轴", "ARC", "CLOCKWISE", "低机位中近景：秦铭说第二句，怪鸟啼鸣抬眼", "低机位中近景：秦铭提叉转身继续向林中走", "导演稿：环绕把第二句与继续前行连成一个动作，场尾在动作上切"),
    # S05 人面鹫
    "E03-S05-01": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_A", "85mm环绕面部，鼻翼与眼", "秦铭面向画右的视线轴，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "特写：秦铭走着，鼻翼一动", "特写（环绕）：身体绷紧，脚步停住，眼神收紧", "导演稿：环绕读闻到腐臭的绷紧"),
    "E03-S05-02": _cp("MEDIUM", "LOW", "AXIS_B", "35mm低机位横移跟随扫视", "秦铭转身扫视的动作轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "低机位中景：秦铭双手持猎叉转身向左扫视", "低机位中景：转身向右扫视，叉头随视线转", "导演稿：横移跟随扫视，无对白镜必动"),
    "E03-S05-03": _cp("MEDIUM_CLOSE_UP", "LOW", "AXIS_A", "50mm低机位仰拍随猎叉上刺升起", "秦铭仰头向上（画面纵深向上）的轴线，不越轴", "CRANE", "RISE", "低机位仰拍中近景：秦铭猛地抬头", "低机位仰拍（升起）：猎叉向头顶上方刺去，叉头出画上缘", "导演稿：升起跟随上刺"),
    "E03-S05-04": _cp("MEDIUM", "HIGH", "AXIS_B", "35mm高机位自树杈推向俯冲", "人面鹫自上（树杈）向下（秦铭）的攻击轴，不越轴", "DOLLY", "PUSH_IN", "高机位中景：一道黑影倒吊在十几米高的树杈上，惨白老人脸朝下", "高机位中景（推近）：人面鹫俯冲而下扑向画下方秦铭的头部，猎叉的叉头迎上来", "导演稿：推近配合俯冲，惊悚点"),
    "E03-S05-05": _cp("MEDIUM_WIDE", "LOW", "AXIS_A", "28mm低机位环绕迎击到展翼冲天", "秦铭在下、人面鹫在上的攻击轴，环绕不越轴", "ARC", "CLOCKWISE", "低机位中全景：猎叉迎击，人面鹫在叉头前数米滑向一旁", "低机位中全景（环绕仰起）：人面鹫展开双翼从林隙冲上夜空盘旋远去，秦铭持叉仰望", "导演稿：环绕仰起把迎击、尖叫、展翼远去连成一个动作，场尾 button"),
    # S06 樟子松林、树洞太干净
    "E03-S06-01": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm手持跟随重新上路进入松桦林", "林缘（画右）到松桦林（画左）的行进轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中全景：秦铭持叉戒备站着，四周只有雪与树", "中全景：秦铭重新上路，走进樟子松、阔叶树与白桦的林地", "导演稿：跟随重新上路，戒备许久以叉头放低起步表达"),
    "E03-S06-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm缓推他看树洞的脸", "秦铭面向记忆中的树洞（画右）的视线轴，不越轴", "DOLLY", "PUSH_IN", "中近景：秦铭停在一棵树前抬头", "中近景（推近）：秦铭看着树洞说一句", "导演稿：推近配合「应该就是这里」"),
    "E03-S06-03": _cp("CLOSE_UP", "HIGH", "AXIS_A", "85mm环绕树洞边缘", "秦铭俯身凑近树洞（画右）的视线轴，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "特写：树洞边缘干干净净，没有一点冰霜，秦铭俯身凑近", "特写（环绕）：秦铭的脸在洞口边，眉头微皱", "导演稿：环绕读「太干净」的失望（原著幽默）"),
    "E03-S06-04": _cp("MEDIUM", "LOW", "AXIS_B", "35mm低机位随直起身升起", "秦铭面向林中（画左）的动作轴，不越轴", "CRANE", "RISE", "低机位中景：秦铭从洞口直起身", "低机位中景（升起）：右手握紧猎叉，左手攥住腰间短刀", "导演稿：升起跟随直起身，握叉攥刀是场尾 button"),
    # S07 爪印、地光、另一树洞
    "E03-S07-01": _cp("MEDIUM_CLOSE_UP", "HIGH", "AXIS_A", "50mm随蹲下下降到雪面爪印", "秦铭蹲下看雪地（画下方）的视线轴，不越轴", "CRANE", "FALL", "俯拍中近景：秦铭蹲下身", "俯拍中近景（降到雪面）：雪地上一串小小的爪印在他手边，他说一句", "导演稿：机位随蹲下下降，「有门」落在爪印上"),
    "E03-S07-02": _cp("WIDE", "LOW", "NEUTRAL", "24mm低机位随霞光升起扫过密林", "无固定人物轴，前方山地（画面纵深）为霞光来源", "CRANE", "RISE", "低机位远景：大片橘红霞光在前方山地冲起，瞬间照亮整片密林，秦铭蹲在画下方", "低机位远景（升起）：秦铭一惊站起转身扫视四野，霞光正在消退", "导演稿：升起让地光照亮密林的一瞬有机位反应"),
    "E03-S07-03": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm环绕到他盯住的方向", "秦铭由扫视转为盯住不远处大树（画右）的视线轴，环绕不越轴", "ARC", "CLOCKWISE", "中近景：霞光消失，林中重归青蓝微光，秦铭转身", "中近景（环绕）：秦铭盯住不远处一棵大树上的树洞", "导演稿：环绕跟随视线落到另一树洞；远景之后的露脸镜按 seq=13 声明身份再锚定"),
    "E03-S07-04": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_B", "85mm自洞口冰花环绕到笑脸", "秦铭面向树洞（画右）的视线轴，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "特写：树洞洞口结着冰花", "特写（环绕到人）：秦铭露出发自真心的灿烂笑容", "导演稿：环绕把冰花和笑容连成一个反应，场尾 button"),
    # S08 攀树捕兽
    "E03-S08-01": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm手持横移跟随蹑手蹑脚到树前", "秦铭向大树（画右）的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中全景：秦铭蹑手蹑脚踏雪走向水桶粗的大树", "中全景：秦铭到树前，把猎叉插在雪里", "导演稿：跟随接近，插叉在行进结束时完成"),
    "E03-S08-02": _cp("MEDIUM", "LOW", "AXIS_B", "35mm低机位随跳起攀树升起", "秦铭向上攀（画面纵深向上）的轴线，不越轴", "CRANE", "RISE", "低机位中景：秦铭猛然跳起冲出雪地", "低机位中景（升起）：他抱住树干一攀，身体到了树洞前", "导演稿：升起跟随跳起攀树"),
    "E03-S08-03": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_A", "85mm环绕短刀砍洞口", "秦铭面向树洞（画右）的动作轴，环绕不越轴", "ARC", "CLOCKWISE", "特写：秦铭右手短刀挥出砍在洞口，咚的一声闷响", "特写（环绕）：洞里一个刚要冲出来的黑影缩了回去，刀刃留在洞沿", "导演稿：环绕读砍洞与缩回"),
    "E03-S08-04": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm横移自树洞到套袋的手", "树洞（画左）到秦铭（画右）的轴线，不越轴", "TRACK", "RIGHT_TO_LEFT", "中近景：秦铭连着挥刀，干枯的树体碎裂，树洞变大", "中近景（横移）：他取出兽皮袋套在右手上", "导演稿：横移把砍大树洞与套袋连成准备动作"),
    "E03-S08-05": _cp("MEDIUM", "LOW", "AXIS_A", "35mm低机位随探臂到薅出下降", "秦铭手臂探进树洞（画右）的动作轴，不越轴", "CRANE", "FALL", "低机位中景：秦铭整条手臂探进树洞，洞里一顿乱撞传出慌乱叫声", "低机位中景（下降）：他一把抓住猎物迅速薅了出来，手臂带出一团火红", "导演稿：下降跟随薅出，场尾 button"),
    # S09 太阳石照洞、红松鼠、掏干果
    "E03-S09-01": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_A", "85mm横摇自太阳石到洞内干果", "秦铭手中太阳石（画左）照向树洞深处（画右）的轴线，不越轴", "PAN", "LEFT_TO_RIGHT", "特写：秦铭举起太阳石照向树洞", "特写（摇到洞内）：野核桃、栗子、红枣满满一洞干果在橘红光里", "导演稿：横摇跟随光线进入树洞"),
    "E03-S09-02": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_B", "85mm环绕自眼睛到侧头看的小兽", "秦铭面向树洞转为侧头看右手（画右）的视线轴，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "特写：秦铭的眼睛在橘红光里焕发火热的光彩", "特写（环绕）：他侧头，被抓在右手里的红松鼠入画", "导演稿：环绕把「眼中火热」与「侧头看小兽」连成一个反应"),
    "E03-S09-03": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_A", "85mm横移沿火红皮毛到啃袋的嘴", "红松鼠在秦铭右手（画右）、太阳石在左手（画左）的轴线，不越轴", "TRACK", "RIGHT_TO_LEFT", "特写：红松鼠全身火红的皮毛在太阳石光下比绸缎还丝滑，微微发光", "特写（横移）：它张嘴啃咬套在秦铭手上的兽皮袋", "导演稿：横移读皮毛发光与啃袋"),
    "E03-S09-04": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm随俯身掏干果下降", "秦铭面向树洞（画右）的动作轴，不越轴", "CRANE", "FALL", "中近景：秦铭用铁丝把红松鼠捆紧，挂在树枝上", "中近景（下降）：他俯身一把又一把掏干果，干瘪的兽皮袋渐渐鼓胀", "导演稿：下降跟随俯身掏干果，袋鼓胀是场尾 button"),
    # S10 松鼠骂人、三个树洞
    "E03-S10-01": _cp("CLOSE_UP", "LOW", "AXIS_A", "85mm低机位环绕倒挂的红松鼠", "红松鼠倒挂在树枝（画上方）、秦铭在画下方的轴线，环绕不越轴", "ARC", "CLOCKWISE", "低机位特写：倒挂的红松鼠黑宝石般的眼睛瞪得滚圆", "低机位特写（环绕）：它张嘴吱吱叫个不停，尾巴甩动", "导演稿：环绕读「骂人」（原著幽默）"),
    "E03-S10-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm缓推掂袋的秦铭", "秦铭面向猎叉（画右）的动作轴，不越轴", "DOLLY", "PUSH_IN", "中近景：秦铭掂了掂鼓胀的兽皮袋", "中近景（推近）：他把红松鼠挂在猎叉上，说完一句", "导演稿：推近配合掂袋与一句"),
    "E03-S10-03": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm手持横移跟随持太阳石找树洞", "秦铭向画右的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中全景：秦铭手持太阳石在树间走，光扫过树干", "中全景：光停在第二个树洞上，他再往前，第三个树洞入画", "导演稿：横移跟随找洞"),
    "E03-S10-04": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_B", "85mm横摇自秦铭到最早那个树洞", "秦铭（画右）看向最早发现的树洞（画左）的视线轴，不越轴", "PAN", "RIGHT_TO_LEFT", "特写：秦铭举太阳石照向最早那个没有霜花的树洞", "特写（摇到洞）：洞里同样塞满了干果", "导演稿：横摇落在最早的树洞也满干果，场尾 button"),
    # S11 吃干果、松鼠气死
    "E03-S11-01": _cp("CLOSE_UP", "HIGH", "AXIS_A", "85mm俯拍环绕双手剥核桃", "秦铭低头看手（画下方）的视线轴，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "俯拍特写：秦铭双手剥开一颗野核桃送进嘴里", "俯拍特写（环绕）：他抓起一把栗子吃", "导演稿：环绕读吃干果"),
    "E03-S11-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm随蹲坐下降到他的笑脸", "秦铭面向画右的轴线，不越轴", "CRANE", "FALL", "中近景：秦铭用雪搓洗红枣，蹲下", "中近景（下降）：他连着吃了五颗红枣，秀气的面孔上满是笑容，鼓胀的兽皮袋在身旁", "导演稿：下降跟随蹲下，读满嘴甜与笑"),
    "E03-S11-03": _cp("CLOSE_UP", "LOW", "AXIS_A", "85mm低机位横移沿树枝到倒挂的红松鼠", "红松鼠倒挂在树枝（画上方）的轴线，不越轴", "TRACK", "LEFT_TO_RIGHT", "低机位特写：红松鼠看着被搬空的树洞方向剧烈挣扎", "低机位特写（横移）：它直挺挺地僵在那里，不动了", "导演稿：横移读松鼠僵住（原著幽默：气死）"),
    "E03-S11-04": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm固定，秦铭与倒挂的松鼠同框", "秦铭面向红松鼠（画右）的视线轴，不越轴", "LOCKED", "NONE", "中近景：秦铭诧异地伸手摇了摇倒挂的红松鼠", "中近景：他说完一句，红松鼠仍直挺挺不动", "导演稿：固定（对白镜 ≤5 s），摇它的动作本身带动，场尾 button"),
    # S12 火泉旁议论
    "E03-S12-01": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm横移自火泉石围到两位村民", "村民乙（画右）面向邻居甲（画左）的交谈轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中景：火泉石围旁，村民乙比划着对邻居甲说话", "中景（横移到两人）：村民乙说完一句，邻居甲点头", "导演稿：横移跟随进入议论，6 s 承载一句"),
    "E03-S12-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm缓推走来站住的陆泽", "陆泽自画左走来面向两位村民（画右）的轴线，不越轴", "DOLLY", "PUSH_IN", "中近景：陆泽走过来站住，眉头深锁", "中近景（推近）：陆泽说完一句，望向村外", "导演稿：推近读眉头深锁与「猎熊」一句，场尾 button"),
    # S13 山顶
    "E03-S13-01": _cp("WIDE", "LOW", "AXIS_A", "24mm低机位随爬上山顶升起", "秦铭向山顶（画面纵深向上）的行进轴，不越轴", "CRANE", "RISE", "低机位远景：秦铭背着鼓胀的兽皮袋、猎叉上挂着红松鼠，爬上矮山顶最后几步", "低机位远景（升起）：他站上山顶，身后是黑压压的林木", "导演稿：升起跟随登顶"),
    "E03-S13-02": _cp("WIDE", "EYE_LEVEL", "AXIS_B", "24mm自他的背影横摇向群山", "秦铭背向镜头望向群山（画面纵深）的视线轴，不越轴", "PAN", "LEFT_TO_RIGHT", "远景：秦铭的背影在画左，前方林木黑压压一片", "远景（摇到群山）：莽莽群山只剩模糊黑影，夜雾深处漾出少许朦胧的光", "导演稿：横摇跟随视线到群山深处的光"),
    "E03-S13-03": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_A", "85mm极缓推近面部", "秦铭面向群山（画右）的视线轴，不越轴", "DOLLY", "PUSH_IN", "特写：秦铭望着远处的光，寒风吹动发梢", "特写（推近）：他说完一句，目光没有移开", "导演稿：极缓推近双眼，全集 button 落在决定上；远景之后的露脸镜按 seq=13 声明身份再锚定"),
}
# ---------- END OF CHUNK 3 ----------

# 每镜：s, n, sec, size, camera, axis, blocking, cast, action(subject, primary_action, patient), dialogue(speaker,text,listener),
# entry, exit, dims{DIM:(entry_text, exit_text, ENTRY_CODE, EXIT_CODE)}, referents[(surface,key)], faces, cps, slots, identity_reanchor
D = lambda a, b, ca, cb: (a, b, ca, cb)
SHOTS = [
    # S01 —— 钩子：短刀入腰带、拎猎叉（承接 E02-S13-06 终态：躺在炕上手按胸口眼睁着、决定浅夜一到就走；本集浅夜已到，他已起身）
    dict(s="E03-S01", n=1, sec=3, faces={"QM": "LOW_ANGLE_TORSO_HANDS_FACE_OUT_OF_FRAME"}, size="低机位特写", camera="低机位手部特写：镜头贴近腰部，画面只有秦铭的右手、短刀与腰间布带，裘氅前襟与猎叉的木柄在画缘；不见脸、不见全身、不见屋内全貌；随起身上升到拎起的猎叉", axis="秦铭面向屋门（画右）", blocking="秦铭站在炕边（镜头只取腰腹局部），右手把短刀插进腰间布带，再拎起靠在炕边的猎叉",
         cast=["QM"], action=("QM", "屋外传来各家出门取石的脚步与人声；秦铭站在炕边，右手把短刀插进腰间的布带，随即拎起靠在炕边的猎叉", None), dialogue=None,
         entry="秦铭站在炕边，短刀握在右手，猎叉靠在炕边", exit="短刀插在腰间布带里，猎叉拎在秦铭右手，叉头入画",
         dims={"POSSESSION": D("短刀在手中", "短刀插在腰间、猎叉在手", "KNIFE_IN_HAND", "KNIFE_AT_BELT_FORK_IN_HAND"), "CONTACT": D("猎叉靠在炕边", "猎叉离开炕沿被拎起", "FORK_LEANING_ON_KANG", "FORK_LIFTED")}, referents=[("他", "QM")]),
    dict(s="E03-S01", n=2, sec=4, faces={"QM": "HIGH_ANGLE_TOP_OF_HEAD_WALKING_AWAY_NOT_MEASURABLE"}, size="俯拍中景", camera="俯拍自炕沿木碗横移跟随走向屋门", axis="炕（画左）到屋门（画右）", blocking="秦铭拿起炕边的弓箭背上，走向屋门，木碗留在炕沿",
         cast=["QM"], action=("QM", "炕沿的木碗里只剩面饼的碎渣；秦铭拿起弓箭背上，走向屋门，没有对陆泽说要外出", None), dialogue=None,
         entry="炕沿木碗里只剩碎渣，秦铭的手正拿起弓箭", exit="秦铭背着弓箭走到屋门前，木碗留在炕沿",
         dims={"POSITION": D("秦铭在炕边", "秦铭在屋门前", "QIN_AT_KANG", "QIN_AT_DOOR"), "POSSESSION": D("弓箭在炕边", "弓箭背在秦铭背上", "BOW_AT_KANG", "BOW_ON_BACK")}, referents=[("他", "QM")]),
    dict(s="E03-S01", n=3, sec=5, size="中近景", camera="门口固定，秦铭回头看炕", axis="秦铭在门口面向屋内（画左）", blocking="秦铭站在屋门口回头看炕，说完转回身",
         cast=["QM"], action=("QM", "秦铭在屋门口回头看了一眼炕，轻声说一句，说完转回身面向门外", None), dialogue=("QM", "希望它还在，能够带给我惊喜。", None),
         entry="秦铭站在屋门口，回头看向炕", exit="秦铭说完，转回身面向门外",
         dims={"POSTURE": D("回头看炕", "转回身面向门外", "HEAD_TURNED_TO_KANG", "FACING_DOORWAY")}, referents=[("他", "QM")]),
    # S02 —— 村道打招呼（幽默）、路过火泉
    dict(s="E03-S02", n=1, sec=4, faces={"QM": "BACK_TO_CAMERA_WALKING_NOT_MEASURABLE", "VA": "FAR_FIGURE_FACE_NOT_MEASURABLE", "VB": "FAR_FIGURE_FACE_NOT_MEASURABLE"}, size="中全景", camera="手持自身后跟随走上村道", axis="村内（画左）到村头火泉（画右）", blocking="秦铭提猎叉走上安静的村道，两位村民自前方迎面走来",
         cast=["QM", "VA", "VB"], action=("QM", "村道已经安静下来，各家都已回屋；秦铭提着猎叉走上村道，迎面走来两位村民", None), dialogue=None,
         entry="秦铭提猎叉走上村道，两位村民在前方走来", exit="秦铭与两位村民相距两步，村民抬头看他",
         dims={"POSITION": D("三人相距远", "三人相距两步", "FAR_APART", "TWO_STEPS_APART"), "POSTURE": D("村民低头走路", "村民抬头看秦铭", "VILLAGERS_HEADS_DOWN", "VILLAGERS_LOOKING_AT_QIN")}, referents=[("他", "QM"), ("两位村民", "VA")]),
    dict(s="E03-S02", n=2, sec=4, identity_reanchor=True, faces={"VA": "SMALL_FACE_IN_MEDIUM_TWO_SHOT_NOT_MEASURABLE", "VB": "SMALL_FACE_IN_MEDIUM_TWO_SHOT_NOT_MEASURABLE"}, size="中近景", camera="环绕交错的三人", axis="秦铭向右行进、村民向左行进", blocking="秦铭笑着抬手打招呼脚步不停，从两位村民身边走过，两人愣住回头",
         cast=["QM", "VA", "VB"], action=("QM", "秦铭笑着抬手打招呼，脚步没有停，从两位村民身边走过去；两位村民还没有反应过来，愣在原地回头，他已经快步远去", "VA"), dialogue=None,
         entry="秦铭笑着抬手，两位村民在他身前", exit="两位村民愣在原地回头，秦铭的背影已快步远去",
         dims={"POSITION": D("秦铭在村民身前", "秦铭已走过村民远去", "QIN_IN_FRONT_OF_VILLAGERS", "QIN_PAST_AND_AWAY"), "POSTURE": D("村民面向来路", "村民愣住回头", "VILLAGERS_FACING_FORWARD", "VILLAGERS_TURNED_BACK")}, referents=[("他", "QM"), ("两位村民", "VA")]),
    dict(s="E03-S02", n=3, sec=3, faces={"QM": "FAR_FIGURE_FACE_NOT_MEASURABLE"}, size="高机位远景", camera="高机位随他走过火泉上升", axis="火泉（画左）到村外雪野（画右）", blocking="秦铭走过火泉石围，走出火光范围进入雪野",
         cast=["QM"], action=("QM", "秦铭提着猎叉走过火泉的石围，火红的光照在他侧身，随后他走出火光的范围，进入火光照不到的深青灰雪野", None), dialogue=None,
         entry="秦铭提着猎叉走过火泉石围，火光照在侧身", exit="秦铭走出火光范围，身影在深青灰的雪野上",
         dims={"POSITION": D("在火泉旁", "在村外雪野", "AT_FIRE_SPRING", "IN_SNOWY_WILDS"), "INTEGRITY": D("身上受火红光", "身上只余雪面青蓝反光", "LIT_BY_FIRE_GLOW", "LIT_BY_SNOW_MOONLIGHT")}, referents=[("他", "QM")]),
    # S03 —— 雪原跋涉
    dict(s="E03-S03", n=1, sec=4, faces={"QM": "FAR_FIGURE_FACE_NOT_MEASURABLE"}, size="远景", camera="横移跟随跋涉", axis="秦铭向画右跋涉", blocking="秦铭在齐胸深的积雪里向画右推进，猎叉举在雪面之上",
         cast=["QM"], action=("QM", "野外的积雪没到胸口，秦铭大半截身子都看不到了，他手持猎叉在雪里向前走，身后留下一道雪沟", None), dialogue=None,
         entry="秦铭只露出胸口以上，猎叉举在雪面上", exit="他向前推进几步，身后留下一道雪沟",
         dims={"POSITION": D("在雪沟起点", "推进几步留下雪沟", "AT_TRENCH_START", "ADVANCED_TRENCH_BEHIND"), "MOMENTUM": D("刚起步", "正在推进", "STARTING", "PUSHING_FORWARD")}, referents=[("他", "QM")]),
    dict(s="E03-S03", n=2, sec=3, identity_reanchor=True, size="特写", camera="环绕面部，白雾与霜", axis="秦铭面向画右", blocking="秦铭喘着白气向前挪，白雾扑在眉毛发梢上结霜",
         cast=["QM"], action=("QM", "秦铭呼出的白雾扑在眉毛上，白雾在眉毛和发梢上结成冰霜，他继续向前挪", None), dialogue=None,
         entry="白雾扑在秦铭眉毛上", exit="秦铭的眉毛和发梢结上冰霜",
         dims={"INTEGRITY": D("眉毛发梢无霜", "眉毛发梢结霜", "BROWS_CLEAR", "BROWS_FROSTED"), "MOMENTUM": D("白雾刚呼出", "又呼出一口更浓的白雾", "FIRST_BREATH", "THICKER_BREATH")}, referents=[("他", "QM")]),
    dict(s="E03-S03", n=3, sec=3, faces={"QM": "LOW_ANGLE_MEDIUM_WIDE_FACE_TURNED_AWAY_NOT_MEASURABLE"}, size="低机位中全景", camera="低机位随前行升起，露出前方林线", axis="秦铭向画右", blocking="秦铭深一脚浅一脚推进，前方黑压压的密林轮廓显出",
         cast=["QM"], action=("QM", "秦铭手持猎叉深一脚浅一脚地向前跋涉，前面黑压压一片，密集的林木在雪面上方显出轮廓", None), dialogue=None,
         entry="秦铭手持猎叉在雪里跋涉，前方只有雪面", exit="前方黑压压的密林轮廓在雪面上方显出",
         dims={"INTEGRITY": D("前方只有雪面", "前方显出林线轮廓", "SNOW_ONLY_AHEAD", "TREELINE_VISIBLE"), "POSITION": D("离林线远", "临近林线", "FAR_FROM_TREELINE", "NEAR_TREELINE")}, referents=[("他", "QM")]),
    # S04 —— 进林、回想树洞、两句话
    dict(s="E03-S04", n=1, sec=4, faces={"QM": "MEDIUM_WIDE_WALKING_FACE_NOT_MEASURABLE"}, size="中全景", camera="手持跟随跨进林缘", axis="雪原（画右）到林缘（画左）", blocking="秦铭跨进密林边缘，碰落枝上积雪，站在光秃的树间",
         cast=["QM"], action=("QM", "秦铭跨进密林边缘，树枝上的积雪被他碰落；大多数树木光秃秃的，树枝上满是雪", None), dialogue=None,
         entry="秦铭正跨进林缘，枝上积雪被碰落", exit="秦铭站在光秃的树间，四周树枝满是雪",
         dims={"POSITION": D("在林缘外", "在林缘树间", "OUTSIDE_TREELINE", "INSIDE_TREELINE"), "INTEGRITY": D("枝上积雪完整", "枝上积雪被碰落一片", "BRANCH_SNOW_INTACT", "BRANCH_SNOW_DISTURBED")}, referents=[("他", "QM")]),
    dict(s="E03-S04", n=2, sec=4, faces={"QM": "PROFILE_LOOKING_UP_AT_TREE_NOT_MEASURABLE"}, size="中景", camera="横摇自秦铭转向他看的树洞", axis="秦铭（画左）看向树上树洞（画右）", blocking="秦铭停下脚步转身，盯着一棵树上的树洞",
         cast=["QM"], action=("QM", "秦铭停下脚步，转身盯着一棵树上的树洞，回想当初见到的那个生物的活动轨迹", None), dialogue=None,
         entry="秦铭停下脚步正转身", exit="秦铭盯着画右一棵树上的树洞",
         dims={"POSTURE": D("行走中转身", "站定盯树洞", "TURNING", "STANDING_STARING_AT_HOLLOW"), "POSITION": D("视线在林深处", "视线在树洞上", "GAZE_INTO_FOREST", "GAZE_ON_HOLLOW")}, referents=[("他", "QM")]),
    dict(s="E03-S04", n=3, sec=5, identity_reanchor=True, size="特写", camera="固定面部特写", axis="秦铭面向树洞（画右）", blocking="秦铭盯着树洞说话",
         cast=["QM"], action=("QM", "秦铭盯着树洞，低声说出他的判断", None), dialogue=("QM", "它的体形比同类大，八成变异了。", None),
         entry="秦铭盯着树洞，嘴唇张开", exit="秦铭一句说完，眼神收回",
         dims={"POSTURE": D("盯树洞开口", "说完眼神收回", "STARING_SPEAKING", "GAZE_WITHDRAWN")}, referents=[("他", "QM"), ("它", "PROP-RED-SQUIRREL")]),
    dict(s="E03-S04", n=4, sec=5, size="低机位中近景", camera="低机位环绕到他继续前行", axis="秦铭由面向树转为面向林深处（画左）", blocking="秦铭说第二句，怪鸟啼鸣时抬眼，提叉转身继续向林中走",
         cast=["QM"], action=("QM", "【画面从第一帧到最后一帧禁止出现任何文字、字幕、字幕条、汉字或水印，台词只在声音里】秦铭说第二句；林中偶有怪鸟突兀地啼鸣，他抬眼，提叉转身继续向林中走；画面下方是雪地与树根，没有任何文字（本单元两次因烧录字幕重做）", None), dialogue=("QM", "如果能找到主巢，应该会收获不小。", None),
         entry="秦铭面向树洞开口说第二句", exit="秦铭提叉转身向林中走去",
         dims={"POSTURE": D("站定说话", "转身行走", "STANDING_SPEAKING", "WALKING_ON"), "POSITION": D("面向树洞", "面向林深处", "FACING_HOLLOW", "FACING_DEEP_FOREST")}, referents=[("他", "QM")]),
    # S05 —— 人面鹫来袭（配乐 CUE-01）
    dict(s="E03-S05", n=1, sec=3, size="特写", camera="环绕面部，鼻翼与眼", axis="秦铭面向画右", blocking="秦铭走着，鼻翼一动，身体绷紧停步",
         cast=["QM"], action=("QM", "秦铭走着，鼻翼一动，他闻到淡淡的腐臭味，身体猛地绷紧，脚步停住", None), dialogue=None,
         entry="秦铭走着，鼻翼一动", exit="秦铭身体绷紧停住，眼神收紧",
         dims={"MOMENTUM": D("行走中", "停步绷紧", "WALKING", "FROZEN_TENSE"), "POSTURE": D("放松前行", "身体绷紧", "RELAXED", "TENSED")}, referents=[("他", "QM")]),
    dict(s="E03-S05", n=2, sec=3, faces={"QM": "LOW_ANGLE_MEDIUM_TURNING_FACE_NOT_MEASURABLE"}, size="低机位中景", camera="低机位横移跟随扫视", axis="秦铭转身扫视", blocking="秦铭双手持猎叉转身向左右扫视",
         cast=["QM"], action=("QM", "秦铭双手持猎叉，转身向左扫视，又转身向右扫视，叉头随视线转", None), dialogue=None,
         entry="秦铭双手持猎叉转向左", exit="秦铭转向右，叉头随视线转",
         dims={"POSTURE": D("面向左扫视", "面向右扫视", "SCANNING_LEFT", "SCANNING_RIGHT"), "CONTACT": D("单手持叉", "双手持叉", "ONE_HAND_ON_FORK", "TWO_HANDS_ON_FORK")}, referents=[("他", "QM")]),
    dict(s="E03-S05", n=3, sec=3, faces={"QM": "LOW_ANGLE_HEAD_TILTED_UP_NOT_MEASURABLE"}, size="低机位仰拍中近景", camera="低机位仰拍随猎叉上刺升起", axis="秦铭仰头向上", blocking="秦铭猛地抬头，猎叉向头顶上方刺去",
         cast=["QM"], action=("QM", "猛然间，秦铭抬头，将手中的猎叉向着头顶上方刺去，叉头冲出画面上缘", None), dialogue=None,
         entry="秦铭猛地抬头，猎叉在胸前", exit="猎叉向头顶上方刺出，叉头出画上缘",
         dims={"POSTURE": D("平视持叉", "仰头上刺", "LEVEL_HOLDING_FORK", "THRUSTING_UPWARD"), "POSITION": D("叉头在胸前", "叉头在头顶上方", "FORK_AT_CHEST", "FORK_ABOVE_HEAD")}, referents=[("他", "QM")]),
    dict(s="E03-S05", n=4, sec=4, faces={"QM": "HIGH_ANGLE_TOP_OF_HEAD_NOT_MEASURABLE"}, size="高机位中景", camera="高机位自树杈推向俯冲", axis="人面鹫自上向下攻击秦铭", blocking="人面鹫倒吊在高树杈上，俯冲而下扑向画下方秦铭的头部",
         cast=["QM"], action=("PROP-HUMANFACE-VULTURE", "一道黑影倒吊在十几米高的树杈上，那是人面鹫，拥有一张惨白的老人脸；它俯冲而下，扑向画下方秦铭的头部，秦铭的猎叉叉头迎上来", "QM"), dialogue=None,
         entry="人面鹫倒吊在高树杈上，惨白老人脸朝下", exit="人面鹫俯冲到秦铭头顶上方，猎叉叉头迎上",
         dims={"POSITION": D("人面鹫在树杈上", "人面鹫俯冲到秦铭头顶上方", "VULTURE_ON_BRANCH", "VULTURE_DIVING_AT_HEAD"), "MOMENTUM": D("倒吊静止", "俯冲而下", "HANGING_STILL", "DIVING")}, referents=[("它", "PROP-HUMANFACE-VULTURE"), ("他", "QM")]),
    dict(s="E03-S05", n=5, sec=4, faces={"QM": "LOW_ANGLE_MEDIUM_WIDE_LOOKING_UP_NOT_MEASURABLE"}, size="低机位中全景", camera="低机位环绕迎击到展翼冲天", axis="秦铭在下、人面鹫在上", blocking="猎叉迎击，人面鹫在叉头前数米滑向一旁，展翼从林隙冲上夜空远去，秦铭持叉仰望",
         cast=["QM"], action=("QM", "秦铭的猎叉迎击，一道尖锐的叫声响彻山林；人面鹫在叉头前数米滑向一旁，展开双翼，从林地的空隙间冲上夜空，盘旋后远去，秦铭持叉仰望", "PROP-HUMANFACE-VULTURE"), dialogue=None,
         entry="猎叉迎击，人面鹫在叉头前数米滑向一旁", exit="人面鹫展翼冲上夜空远去，秦铭持叉仰望",
         dims={"POSITION": D("人面鹫在叉头前", "人面鹫冲上夜空远去", "VULTURE_AT_FORK", "VULTURE_GONE_INTO_SKY"), "POSTURE": D("秦铭持叉迎击", "秦铭持叉仰望", "QIN_PARRYING", "QIN_LOOKING_UP")}, referents=[("它", "PROP-HUMANFACE-VULTURE"), ("他", "QM")]),
    # S06 —— 樟子松林，树洞太干净（幽默：失望）
    dict(s="E03-S06", n=1, sec=4, faces={"QM": "MEDIUM_WIDE_WALKING_FACE_NOT_MEASURABLE"}, size="中全景", camera="手持跟随重新上路进入松桦林", axis="林缘（画右）到松桦林（画左）", blocking="秦铭持叉戒备站着，随后重新上路走进樟子松白桦林",
         cast=["QM"], action=("QM", "秦铭持叉戒备了很长时间，那生物没有再出现；他重新上路，走进一片樟子松、阔叶树和白桦为主的林地", None), dialogue=None,
         entry="秦铭持叉戒备站着，四周只有雪与树", exit="秦铭走进樟子松与白桦的林地",
         dims={"POSITION": D("在林缘戒备处", "在松桦林中", "AT_GUARD_SPOT", "IN_PINE_BIRCH_STAND"), "MOMENTUM": D("戒备站立", "重新行走", "STANDING_GUARD", "WALKING_AGAIN")}, referents=[("他", "QM"), ("那生物", "PROP-HUMANFACE-VULTURE")]),
    dict(s="E03-S06", n=2, sec=3, identity_reanchor=True, size="中近景", camera="缓推他看树洞的脸", axis="秦铭面向记忆中的树洞（画右）", blocking="秦铭停在一棵树前抬头看树洞，说一句",
         cast=["QM"], action=("QM", "秦铭停在一棵树前，抬头看着记忆中的那个树洞，说一句", None), dialogue=("QM", "应该就是这里。", None),
         entry="秦铭停步抬头看树洞", exit="秦铭说完，仍看着树洞",
         dims={"MOMENTUM": D("行走中停步", "站定说完", "STOPPING", "STANDING_DONE_SPEAKING")}, referents=[("他", "QM")]),
    dict(s="E03-S06", n=3, sec=3, faces={"QM": "HIGH_ANGLE_PROFILE_AT_HOLLOW_NOT_MEASURABLE"}, size="特写", camera="环绕树洞边缘", axis="秦铭俯身凑近树洞（画右）", blocking="秦铭俯身凑近树洞边缘看，眉头微皱",
         cast=["QM"], action=("QM", "秦铭俯身凑近，树洞边缘很干净，没有一点冰霜；他眉头微微皱起", None), dialogue=None,
         entry="树洞边缘干净无霜，秦铭俯身凑近", exit="秦铭的脸在洞口边，眉头微皱",
         dims={"POSITION": D("脸离洞口一臂", "脸在洞口边", "FACE_ARM_LENGTH_FROM_HOLLOW", "FACE_AT_HOLLOW"), "POSTURE": D("眉头舒展", "眉头微皱", "BROWS_RELAXED", "BROWS_FURROWED")}, referents=[("他", "QM")]),
    dict(s="E03-S06", n=4, sec=3, faces={"QM": "LOW_ANGLE_MEDIUM_FACE_TURNED_NOT_MEASURABLE"}, size="低机位中景", camera="低机位随直起身升起", axis="秦铭面向林中（画左）", blocking="秦铭从洞口直起身，右手握紧猎叉，左手攥住腰间短刀",
         cast=["QM"], action=("QM", "秦铭从洞口直起身，右手握紧猎叉，左手攥住腰间的短刀", None), dialogue=None,
         entry="秦铭低头在洞口，左手空着", exit="秦铭挺直腰背，右手握紧猎叉，左手攥住短刀",
         dims={"POSTURE": D("俯身", "直起身", "BENT_AT_HOLLOW", "STANDING_UPRIGHT"), "CONTACT": D("左手空", "左手攥住短刀", "LEFT_HAND_EMPTY", "LEFT_HAND_ON_KNIFE")}, referents=[("他", "QM")]),
    # S07 —— 爪印「有门」、地光、另一树洞、灿烂笑容
    dict(s="E03-S07", n=1, sec=3, faces={"QM": "HIGH_ANGLE_CROUCHED_LOOKING_DOWN_NOT_MEASURABLE"}, size="俯拍中近景", camera="随蹲下下降到雪面爪印", axis="秦铭蹲下看雪地", blocking="秦铭蹲下身看雪地上一串小小的爪印，说一句",
         cast=["QM"], action=("QM", "秦铭蹲下，看到雪地上一串小小的爪印，说一句", None), dialogue=("QM", "有门！", None),
         entry="秦铭正蹲下身", exit="秦铭蹲在雪地上，爪印在他手边，一句说完",
         dims={"POSTURE": D("站立", "蹲下", "STANDING", "CROUCHED")}, referents=[("他", "QM")]),
    dict(s="E03-S07", n=2, sec=4, faces={"QM": "FAR_FIGURE_FACE_NOT_MEASURABLE"}, size="低机位远景", camera="低机位随霞光升起扫过密林", axis="前方山地为霞光来源", blocking="霞光在前方山地冲起照亮密林，秦铭一惊站起转身扫视四野",
         cast=["QM"], action=("QM", "大片橘红的霞光在前方的山地冲起，瞬息照亮密林；秦铭一惊，站起转身扫视四野，霞光正在消退", None), dialogue=None,
         entry="霞光冲起照亮整片密林，秦铭蹲在画下方", exit="秦铭站起转身扫视四野，霞光消退",
         dims={"INTEGRITY": D("密林被霞光照亮", "霞光消退", "FOREST_LIT_BY_GROUND_LIGHT", "GROUND_LIGHT_FADING"), "POSTURE": D("蹲着", "站起转身扫视", "CROUCHED", "STANDING_SCANNING")}, referents=[("他", "QM")]),
    dict(s="E03-S07", n=3, sec=3, identity_reanchor=True, size="中近景", camera="环绕到他盯住的方向", axis="秦铭由扫视转为盯住不远处大树（画右）", blocking="霞光消失林中重归青蓝微光，秦铭转身盯住不远处一棵大树上的树洞",
         cast=["QM"], action=("QM", "霞光消失，林中重归青蓝微光；秦铭转身，盯住不远处一棵大树上的树洞", None), dialogue=None,
         entry="霞光消失，秦铭正转身", exit="秦铭盯住不远处一棵大树上的树洞",
         dims={"POSTURE": D("转身中", "站定盯住树洞", "TURNING", "FIXED_ON_HOLLOW"), "INTEGRITY": D("残余霞光", "只余青蓝微光", "RESIDUAL_GLOW", "MOONLIT_ONLY")}, referents=[("他", "QM")]),
    dict(s="E03-S07", n=4, sec=4, size="特写", camera="自洞口冰花环绕到笑脸", axis="秦铭面向树洞（画右）", blocking="树洞洞口结着冰花，秦铭露出灿烂笑容",
         cast=["QM"], action=("QM", "那个树洞的洞口结着冰花；秦铭露出发自真心的灿烂笑容", None), dialogue=None,
         entry="树洞洞口结着冰花，秦铭的脸绷着", exit="秦铭露出灿烂笑容",
         dims={"POSTURE": D("面部绷着", "灿烂笑容", "FACE_TENSE", "BEAMING_SMILE"), "POSITION": D("画面在洞口冰花", "画面落在秦铭笑脸", "FRAME_ON_FROST", "FRAME_ON_SMILE")}, referents=[("他", "QM")]),
    # S08 —— 攀树、砍洞、套袋、薅出
    dict(s="E03-S08", n=1, sec=4, faces={"QM": "MEDIUM_WIDE_WALKING_FACE_NOT_MEASURABLE"}, size="中全景", camera="手持横移跟随蹑手蹑脚到树前", axis="秦铭向大树（画右）", blocking="秦铭蹑手蹑脚踏雪走到水桶粗的大树前，把猎叉插在雪里",
         cast=["QM"], action=("QM", "秦铭蹑手蹑脚，踏着雪走到那棵水桶粗的大树前，把猎叉插在雪里", None), dialogue=None,
         entry="秦铭蹑手蹑脚踏雪走向大树", exit="秦铭到树前，猎叉插在雪里",
         dims={"POSITION": D("离大树几步", "在大树前", "STEPS_FROM_TREE", "AT_TREE"), "POSSESSION": D("猎叉在手", "猎叉插在雪里", "FORK_IN_HAND", "FORK_PLANTED_IN_SNOW")}, referents=[("他", "QM")]),
    dict(s="E03-S08", n=2, sec=4, faces={"QM": "LOW_ANGLE_CLIMBING_FACE_TURNED_NOT_MEASURABLE"}, size="低机位中景", camera="低机位随跳起攀树升起", axis="秦铭向上攀", blocking="秦铭猛然跳起冲出雪地，抱住树干一攀到树洞前",
         cast=["QM"], action=("QM", "秦铭猛然跳起冲出雪地，抱住树干用力一攀，身体来到树洞前", None), dialogue=None,
         entry="秦铭猛然跳起冲出雪地", exit="秦铭抱住树干，身体在树洞前",
         dims={"POSITION": D("在雪地上", "在树洞前的树干上", "ON_SNOW", "ON_TRUNK_AT_HOLLOW"), "POSTURE": D("跳起", "抱树攀住", "LEAPING", "CLINGING_TO_TRUNK")}, referents=[("他", "QM")]),
    dict(s="E03-S08", n=3, sec=4, faces={"QM": "PROFILE_AT_HOLLOW_KNIFE_HAND_NOT_MEASURABLE"}, size="特写", camera="环绕短刀砍洞口", axis="秦铭面向树洞（画右）", blocking="秦铭右手短刀砍在洞口，洞里刚要冲出来的黑影缩回去",
         cast=["QM"], action=("QM", "秦铭右手的短刀挥出，砍在洞口，发出咚的一声闷响；洞里一个刚要冲出来的黑影快速缩了回去", None), dialogue=None,
         entry="秦铭的短刀砍在洞口", exit="洞里的黑影缩了回去，刀刃留在洞沿",
         dims={"CONTACT": D("刀刃挥向洞口", "刀刃砍进洞沿", "BLADE_SWINGING", "BLADE_IN_RIM"), "POSITION": D("黑影探到洞口", "黑影缩回洞里", "SHADOW_AT_MOUTH", "SHADOW_WITHDRAWN")}, referents=[("他", "QM")]),
    dict(s="E03-S08", n=4, sec=3, faces={"QM": "PROFILE_HANDS_BUSY_NOT_MEASURABLE"}, size="中近景", camera="横移自树洞到套袋的手", axis="树洞（画左）到秦铭（画右）", blocking="秦铭连着挥刀砍大树洞，取出兽皮袋套在右手上",
         cast=["QM"], action=("QM", "秦铭连着挥刀，干枯的树体碎裂，树洞变大；他取出一个兽皮袋套在右手上", None), dialogue=None,
         entry="秦铭连着挥刀，树体碎裂，兽皮袋在他腰间", exit="树洞变大，兽皮袋套在秦铭右手上",
         dims={"INTEGRITY": D("树洞小", "树洞被砍大", "HOLLOW_SMALL", "HOLLOW_ENLARGED"), "POSSESSION": D("兽皮袋在腰间", "兽皮袋套在手上", "BAG_AT_BELT", "BAG_ON_HAND")}, referents=[("他", "QM")]),
    dict(s="E03-S08", n=5, sec=3, faces={"QM": "LOW_ANGLE_ARM_IN_HOLLOW_FACE_TURNED_NOT_MEASURABLE"}, size="低机位中景", camera="低机位随探臂到薅出下降", axis="秦铭手臂探进树洞（画右）", blocking="秦铭整条手臂探进树洞，洞里乱撞叫声，他一把抓住猎物薅出来",
         cast=["QM"], action=("QM", "秦铭整条手臂探进树洞，洞里一顿乱撞，传出慌乱的叫声；他一把抓住猎物，迅速把它薅了出来，手臂带出一团火红", None), dialogue=None,
         entry="秦铭的手臂探在树洞里，洞里乱撞", exit="秦铭把猎物薅出树洞，手里一团火红",
         dims={"POSITION": D("手臂在洞里", "手臂拉出洞外", "ARM_IN_HOLLOW", "ARM_OUT_WITH_PREY"), "POSSESSION": D("猎物在洞里", "猎物在秦铭手里", "PREY_IN_HOLLOW", "PREY_IN_HAND")}, referents=[("他", "QM"), ("它", "PROP-RED-SQUIRREL")]),
    # S09 —— 太阳石照洞、红松鼠、掏干果
    dict(s="E03-S09", n=1, sec=4, faces={"QM": "PROFILE_HAND_WITH_STONE_NOT_MEASURABLE"}, size="特写", camera="横摇自太阳石到洞内干果", axis="秦铭手中太阳石照向树洞深处（画右）", blocking="秦铭举起太阳石照向树洞深处，洞里满满的干果",
         cast=["QM"], action=("QM", "秦铭举起太阳石向着树洞深处照去，洞里有野核桃、栗子、红枣，满满的干果", None), dialogue=None,
         entry="秦铭举起太阳石照向树洞", exit="太阳石的橘红光照出满洞干果",
         dims={"INTEGRITY": D("洞内深褐看不清", "洞内干果被照亮", "HOLLOW_DARK", "HOLLOW_LIT_NUTS_VISIBLE"), "POSITION": D("画面在太阳石", "画面在洞内干果", "FRAME_ON_STONE", "FRAME_ON_NUTS")}, referents=[("他", "QM")]),
    dict(s="E03-S09", n=2, sec=3, size="特写", camera="环绕自眼睛到侧头看的小兽；秦铭的脸以自然肤色呈现（雪夜青蓝主光），他左手举着的太阳石在画面下缘入画、橘红光自下方映亮下颌与眼睛，五官清晰、正对镜头略偏右；眼睛是正常人眼（眼神明亮、瞳孔映着一点暖光），不是发光的虹膜；脸上不得整体染成橘红色", axis="秦铭面向树洞转为侧头看右手（画右）", blocking="秦铭眼神发亮（太阳石在画面下缘、光自下而上），侧头看被抓在右手里的小兽",
         cast=["QM"], action=("QM", "秦铭的眼睛焕发出火热的光彩（眼神发亮、瞳孔映着太阳石的一点暖光，正常人眼，脸仍是自然肤色）；他侧头，看被抓在右手里的小兽", None), dialogue=None,
         entry="秦铭的眼睛在太阳石的橘红光里发亮，面向树洞，太阳石在画面下缘", exit="秦铭侧头，右手里的小兽入画",
         dims={"POSTURE": D("面向树洞", "侧头看右手", "FACING_HOLLOW", "HEAD_TURNED_TO_HAND"), "POSITION": D("红松鼠在画外", "红松鼠在画内", "SQUIRREL_OUT_OF_FRAME", "SQUIRREL_IN_FRAME")}, referents=[("他", "QM"), ("小兽", "PROP-RED-SQUIRREL")]),
    dict(s="E03-S09", n=3, sec=3, faces={"QM": "HANDS_ONLY_FACE_OUT_OF_FRAME"}, size="特写", camera="横移沿火红皮毛到啃袋的嘴", axis="红松鼠在秦铭右手（画右）、太阳石在左手（画左）", blocking="红松鼠火红皮毛在太阳石光下发光，它啃咬套在秦铭手上的兽皮袋",
         cast=["QM"], action=("PROP-RED-SQUIRREL", "红松鼠全身火红的皮毛在太阳石的照耀下比绸缎还丝滑，微微发光；它张嘴啃咬套在秦铭手上的兽皮袋", "QM"), dialogue=None,
         entry="红松鼠火红的皮毛在太阳石光下发光", exit="红松鼠张嘴啃咬秦铭手上的兽皮袋",
         dims={"CONTACT": D("松鼠嘴闭着", "松鼠啃住兽皮袋", "MOUTH_CLOSED", "BITING_BAG"), "POSITION": D("画面在皮毛", "画面在啃袋的嘴", "FRAME_ON_FUR", "FRAME_ON_MOUTH")}, referents=[("它", "PROP-RED-SQUIRREL"), ("他", "QM")]),
    dict(s="E03-S09", n=4, sec=4, faces={"QM": "PROFILE_BENT_OVER_HANDS_BUSY_NOT_MEASURABLE"}, size="中近景", camera="随俯身掏干果下降", axis="秦铭面向树洞（画右）", blocking="秦铭用铁丝把红松鼠捆紧挂在树枝上，俯身一把把掏干果，兽皮袋鼓胀",
         cast=["QM"], action=("QM", "秦铭取出一根铁丝，麻利地把红松鼠捆紧，挂在树枝上；他俯身一把又一把地把干果掏出来，干瘪的兽皮袋渐渐鼓胀", "PROP-RED-SQUIRREL"), dialogue=None,
         entry="秦铭用铁丝捆红松鼠，兽皮袋干瘪", exit="红松鼠挂在树枝上，秦铭俯身掏干果，兽皮袋鼓胀",
         dims={"POSITION": D("红松鼠在手里", "红松鼠挂在树枝上", "SQUIRREL_IN_HAND", "SQUIRREL_HUNG_ON_BRANCH"), "INTEGRITY": D("兽皮袋干瘪", "兽皮袋鼓胀", "BAG_FLAT", "BAG_BULGING")}, referents=[("他", "QM"), ("它", "PROP-RED-SQUIRREL")]),
    # S10 —— 松鼠骂人、掂袋一句、三个树洞
    dict(s="E03-S10", n=1, sec=4, faces={"QM": "OUT_OF_FRAME_SQUIRREL_ONLY"}, size="低机位特写", camera="低机位环绕倒挂的红松鼠", axis="红松鼠倒挂在树枝（画上方）", blocking="倒挂的红松鼠瞪圆眼睛吱吱叫个不停，尾巴甩动",
         cast=["QM"], action=("PROP-RED-SQUIRREL", "倒挂着的红松鼠黑宝石般的眼睛瞪得滚圆，张嘴吱吱叫个不停，尾巴甩动", None), dialogue=None,
         entry="倒挂的红松鼠瞪圆眼睛", exit="红松鼠张嘴吱吱叫，尾巴甩动",
         dims={"POSTURE": D("嘴闭眼瞪", "张嘴叫、尾巴甩", "MOUTH_CLOSED_EYES_WIDE", "CHATTERING_TAIL_FLICKING"), "MOMENTUM": D("静止倒挂", "挣扎晃动", "HANGING_STILL", "SWINGING_STRUGGLING")}, referents=[("它", "PROP-RED-SQUIRREL")]),
    dict(s="E03-S10", n=2, sec=6, cps=4.8, size="中近景", camera="缓推掂袋的秦铭", axis="秦铭面向猎叉（画右）", blocking="秦铭掂了掂鼓胀的兽皮袋，把红松鼠挂在猎叉上，说一句",
         cast=["QM"], action=("QM", "秦铭掂了掂鼓胀的兽皮袋，把红松鼠挂在猎叉上，对它说一句", "PROP-RED-SQUIRREL"), dialogue=("QM", "你这么重，八斤出头的过冬粮食怎么够你吃？", None),
         entry="秦铭掂着兽皮袋，红松鼠在树枝上", exit="红松鼠挂在猎叉上，秦铭说完一句",
         dims={"POSITION": D("红松鼠在树枝上", "红松鼠挂在猎叉上", "SQUIRREL_ON_BRANCH", "SQUIRREL_ON_FORK"), "CONTACT": D("双手掂袋", "一手提叉", "HANDS_ON_BAG", "HAND_ON_FORK")}, referents=[("他", "QM"), ("它", "PROP-RED-SQUIRREL")]),
    dict(s="E03-S10", n=3, sec=3, faces={"QM": "MEDIUM_WIDE_WALKING_FACE_NOT_MEASURABLE"}, size="中全景", camera="手持横移跟随持太阳石找树洞", axis="秦铭向画右", blocking="秦铭手持太阳石在树间走，光扫过树干，停在第二个树洞，再往前第三个树洞入画",
         cast=["QM"], action=("QM", "秦铭手持太阳石在附近的树间走，光扫过树干，发现第二个树洞，接着是第三个", None), dialogue=None,
         entry="秦铭持太阳石在树间走，光扫过树干", exit="光停在第二个树洞上，第三个树洞在他前方入画",
         dims={"POSITION": D("在第一棵树旁", "走到第二第三树洞前", "AT_FIRST_TREE", "AT_SECOND_THIRD_HOLLOWS"), "INTEGRITY": D("树干无洞", "两个新树洞被照出", "TRUNKS_PLAIN", "TWO_MORE_HOLLOWS_LIT")}, referents=[("他", "QM")]),
    dict(s="E03-S10", n=4, sec=3, faces={"QM": "PROFILE_HAND_WITH_STONE_NOT_MEASURABLE"}, size="特写", camera="横摇自秦铭到最早那个树洞", axis="秦铭（画右）看向最早发现的树洞（画左）", blocking="秦铭举太阳石照向最早那个没有霜花的树洞，洞里同样塞满干果",
         cast=["QM"], action=("QM", "秦铭举太阳石照向最早那个没有霜花的树洞，洞里同样塞满了干果", None), dialogue=None,
         entry="秦铭举太阳石照向最早那个树洞", exit="洞里塞满的干果被橘红光照出",
         dims={"INTEGRITY": D("洞内看不清", "洞内干果被照亮", "HOLLOW_DARK", "HOLLOW_LIT_NUTS_VISIBLE"), "POSITION": D("画面在秦铭", "画面在洞内", "FRAME_ON_QIN", "FRAME_ON_HOLLOW")}, referents=[("他", "QM")]),
    # S11 —— 吃干果、松鼠气死（配乐 CUE-02）
    dict(s="E03-S11", n=1, sec=3, faces={"QM": "HIGH_ANGLE_HANDS_TOP_OF_HEAD_NOT_MEASURABLE"}, size="俯拍特写", camera="俯拍环绕双手剥核桃", axis="秦铭低头看手", blocking="秦铭双手剥开野核桃吃，又抓一把栗子吃",
         cast=["QM"], action=("QM", "秦铭剥开一颗野核桃吃了，又抓起一把栗子吃", None), dialogue=None,
         entry="秦铭双手剥开一颗野核桃", exit="秦铭抓起一把栗子送进嘴里",
         dims={"POSSESSION": D("手里是核桃", "手里是一把栗子", "WALNUT_IN_HAND", "CHESTNUTS_IN_HAND"), "CONTACT": D("核桃壳在指间", "栗子在嘴边", "SHELL_IN_FINGERS", "CHESTNUT_AT_MOUTH")}, referents=[("他", "QM")]),
    dict(s="E03-S11", n=2, sec=4, size="中近景", camera="随蹲坐下降到他的笑脸", axis="秦铭面向画右", blocking="秦铭用雪搓洗红枣蹲下，连吃五颗满嘴甜，面孔上满是笑容，鼓胀的兽皮袋在身旁",
         cast=["QM"], action=("QM", "秦铭用雪搓洗红枣，蹲下，连着吃了五颗，满嘴都是甜味；他秀气的面孔上满是开心的笑容，鼓胀的兽皮袋在身旁", None), dialogue=None,
         entry="秦铭站着用雪搓洗红枣", exit="秦铭蹲着吃完第五颗红枣，满脸笑容，兽皮袋在身旁",
         dims={"POSTURE": D("站着搓枣", "蹲着笑", "STANDING_RUBBING_DATES", "CROUCHED_SMILING"), "POSSESSION": D("红枣在手", "红枣已入口", "DATES_IN_HAND", "DATES_EATEN")}, referents=[("他", "QM")]),
    dict(s="E03-S11", n=3, sec=3, faces={"QM": "OUT_OF_FRAME_SQUIRREL_ONLY"}, size="低机位特写", camera="低机位横移沿树枝到倒挂的红松鼠", axis="红松鼠倒挂在猎叉（画上方）", blocking="倒挂的红松鼠看四个巢穴被搬空，剧烈挣扎后直挺挺僵住不动",
         cast=["QM"], action=("PROP-RED-SQUIRREL", "倒挂的红松鼠看着四个巢穴都被搬空，剧烈挣扎了几下，随后直挺挺地僵在那里，不动了", None), dialogue=None,
         entry="红松鼠剧烈挣扎", exit="红松鼠直挺挺僵住不动",
         dims={"MOMENTUM": D("剧烈挣扎", "僵住不动", "STRUGGLING", "STIFF_MOTIONLESS"), "POSTURE": D("身体扭动", "身体笔直僵硬", "BODY_TWISTING", "BODY_RIGID")}, referents=[("它", "PROP-RED-SQUIRREL")]),
    dict(s="E03-S11", n=4, sec=5, cps=5.0, size="中近景", camera="固定，秦铭与倒挂的松鼠同框", axis="秦铭面向红松鼠（画右）", blocking="秦铭诧异地伸手摇了摇倒挂的红松鼠，说一句",
         cast=["QM"], action=("QM", "秦铭诧异，伸手摇了摇倒挂的红松鼠，它仍直挺挺不动；他自语一句", "PROP-RED-SQUIRREL"), dialogue=("QM", "正好，小文睿说想吃肉了，可以煮一锅肉汤。", None),
         entry="秦铭诧异地伸手摇红松鼠", exit="秦铭说完一句，红松鼠仍直挺挺不动",
         dims={"CONTACT": D("手摇着松鼠", "手收回", "HAND_SHAKING_SQUIRREL", "HAND_WITHDRAWN"), "POSTURE": D("诧异张口", "说完嘴角带笑", "PUZZLED", "AMUSED_DONE_SPEAKING")}, referents=[("他", "QM"), ("它", "PROP-RED-SQUIRREL")]),
    # S12 —— 火泉旁议论、陆泽皱眉
    dict(s="E03-S12", n=1, sec=6, cps=5.0, faces={"VA": "PROFILE_LISTENING_NOT_MEASURABLE"}, size="中景", camera="横移自火泉石围到两位村民", axis="村民乙（画右）面向邻居甲（画左）", blocking="火泉石围旁村民乙比划着对邻居甲说话，邻居甲点头",
         cast=["VB", "VA"], action=("VB", "火泉石围旁，村民乙比划着对邻居甲说话，邻居甲点头", "VA"), dialogue=("VB", "秦铭全副武装去野外了，像是要猎大型猛兽！", "VA"), slots={"VB": "SCREEN_RIGHT", "VA": "SCREEN_LEFT"},
         entry="火泉石围旁，村民乙抬手比划，邻居甲看着他", exit="村民乙说完，邻居甲点头",
         dims={"POSTURE": D("村民乙抬手比划", "村民乙放下手", "GESTURING", "HANDS_DOWN"), "CONTACT": D("邻居甲头正", "邻居甲点头", "HEAD_STILL", "NODDING")}, referents=[("秦铭", "QM")]),
    dict(s="E03-S12", n=2, sec=6, cps=5.0, faces={"VA": "SMALL_FACE_IN_BACKGROUND_NOT_MEASURABLE", "VB": "SMALL_FACE_IN_BACKGROUND_NOT_MEASURABLE"}, size="中近景", camera="缓推走来站住的陆泽", axis="陆泽自画左走来面向两位村民（画右）", blocking="陆泽走过来站住，眉头深锁，说一句后望向村外",
         cast=["LZ", "VA", "VB"], action=("LZ", "陆泽走过来站住，眉头深锁，说一句，说完望向村外", "VB"), dialogue=("LZ", "那小子怎么能一个人冒险外出，该不会去猎熊了吧？", "VB"), slots={"LZ": "SCREEN_LEFT", "VB": "SCREEN_RIGHT"},
         entry="陆泽走过来站住，眉头深锁", exit="陆泽说完，望向村外",
         dims={"POSITION": D("陆泽在走近", "陆泽站住", "LUZE_APPROACHING", "LUZE_STOPPED"), "POSTURE": D("面向村民", "望向村外", "FACING_VILLAGERS", "LOOKING_TO_WILDS")}, referents=[("那小子", "QM")]),
    # S13 —— 山顶望群山（配乐 CUE-03）
    dict(s="E03-S13", n=1, sec=4, faces={"QM": "FAR_FIGURE_FACE_NOT_MEASURABLE"}, size="低机位远景", camera="低机位随爬上山顶升起", axis="秦铭向山顶", blocking="秦铭背着鼓胀的兽皮袋、猎叉上挂着红松鼠，爬上矮山顶站定，身后是黑压压的林木",
         cast=["QM"], action=("QM", "秦铭背着鼓胀的兽皮袋，猎叉上挂着红松鼠，爬上密林外围的矮山顶，站定", None), dialogue=None,
         entry="秦铭背着鼓胀的兽皮袋、猎叉上挂着红松鼠，爬上山顶最后几步", exit="秦铭站上山顶，身后是黑压压的林木",
         dims={"POSITION": D("在山坡上", "在山顶", "ON_SLOPE", "ON_SUMMIT"), "POSTURE": D("攀爬", "站定", "CLIMBING", "STANDING")}, referents=[("他", "QM")]),
    dict(s="E03-S13", n=2, sec=3, faces={"QM": "BACK_TO_CAMERA_FAR_FIGURE_NOT_MEASURABLE"}, size="远景", camera="自他的背影横摇向群山", axis="秦铭背向镜头望向群山", blocking="秦铭的背影在画左望向前方，林木黑压压，群山黑影，夜雾深处漾出朦胧的光",
         cast=["QM"], action=("QM", "秦铭望向前方，林木黑压压一片，莽莽群山只剩模糊的黑影；夜雾深处漾出少许朦胧的光，他站着不动", None), dialogue=None,
         entry="秦铭的背影在画左，前方林木黑压压", exit="画面落在群山黑影与夜雾深处朦胧的光",
         dims={"POSITION": D("画面在秦铭背影", "画面在群山深处的光", "FRAME_ON_BACK", "FRAME_ON_DISTANT_GLOW"), "INTEGRITY": D("只见林木黑压压", "夜雾深处漾出光", "FOREST_ONLY", "GLOW_IN_MIST")}, referents=[("他", "QM")]),
    dict(s="E03-S13", n=3, sec=5, identity_reanchor=True, size="特写", camera="极缓推近面部", axis="秦铭面向群山（画右）", blocking="秦铭望着远处的光，寒风吹动发梢，说一句",
         cast=["QM"], action=("QM", "秦铭望着远处夜雾里的光，寒风吹动他的发梢，他低声说一句，目光没有移开", None), dialogue=("QM", "那里，还不是我能去的地方。", None),
         entry="秦铭望着远处的光，嘴唇闭着", exit="秦铭说完一句，目光仍在远处的光上",
         dims={"POSTURE": D("闭口凝望", "说完凝望", "SILENT_GAZE", "SPOKEN_GAZE")}, referents=[("他", "QM"), ("那里", "LOC-DISTANT-MOUNTAINS")]),
]
# ---------- END OF CHUNK 4 ----------

# 承接：读 E02 合同末镜的实际 completion_state（不是源章推定）
PREV_LAST = json.loads(PREV_CONTRACT.read_text(encoding="utf-8"))["shots"][-1]
assert PREV_LAST["shot_id"] == "E02-S13-06", PREV_LAST["shot_id"]

_ALT = [("ARC", "COUNTERCLOCKWISE"), ("ARC", "CLOCKWISE"), ("TRACK", "LEFT_TO_RIGHT"), ("TRACK", "RIGHT_TO_LEFT"),
        ("CRANE", "RISE"), ("CRANE", "FALL")]
_ZH_FAM = {"ARC": "环绕", "TRACK": "横移", "CRANE": "升降", "DOLLY": "推拉", "PAN": "横摇"}


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

# ---------- 校验镜头表 ----------
def est_spoken(text, cps):
    han = len(re.findall(r"[㐀-鿿]", text)); p = len(re.findall(r"[，。！？；、,.!?;]", text))
    o = len(re.sub(r"[㐀-鿿\s，。！？；、,.!?;]", "", text))
    return han / cps + p * 0.16 + o * 0.08
by_scene = {}
for sh in SHOTS:
    by_scene.setdefault(sh["s"], []).append(sh)
assert list(by_scene) == list(SCENES), "镜头表场次顺序与 SCENES 不一致"
for sid, meta in SCENES.items():
    total = sum(x["sec"] for x in by_scene[sid])
    assert total == meta["sec"], (sid, total, meta["sec"])
    assert meta["sec"] <= 22 and meta["sec"] <= 12 * meta["info"], (sid, "单场 ≤22 s 且 ≤12s×信息条数")
prev_locked = False
for i, sh in enumerate(SHOTS):
    shot_id = f"{sh['s']}-{sh['n']:02d}"
    assert shot_id in CAMERA_PLANS, (shot_id, "缺机位方案")
    assert 3 <= sh["sec"] <= 7, (shot_id, "单镜 3–7 s")
    assert sh["entry"] != sh["exit"], sh
    for d, (a, b, ca, cb) in sh["dims"].items():
        assert d in {"POSITION", "POSTURE", "CONTACT", "POSSESSION", "INTEGRITY", "MOMENTUM"} and a != b and ca != cb, (shot_id, d)
    for word in ("持续", "保持", "连续", "全黑", "极暗", "纯黑"):
        assert word not in sh["action"][1] and word not in sh["entry"] and word not in sh["exit"], (shot_id, word)
    cp = CAMERA_PLANS[shot_id]
    locked = cp["motion_family"] == "LOCKED"
    if sh.get("dialogue"):
        cps = sh.get("cps", 4.2)
        need = max(0.12 + est_spoken(sh["dialogue"][1], cps) + 0.32 + 0.25, NPR.min_dialogue_seconds(sh["dialogue"][1], sh.get("cps")))
        assert need <= sh["sec"], (shot_id, "台词放不进镜头", round(need, 2), sh["sec"])
        assert sh["sec"] <= 5 or need > 5, (shot_id, "只有台词确实放不进 5 s 才允许 >5 s", round(need, 2))
    else:
        assert sh["sec"] <= 5, (shot_id, "无对白镜 ≤5 s")
        assert not locked, (shot_id, "无对白镜必须有机位运动")
        if sh["sec"] >= 3 and cp["motion_family"] not in NPR.MOVING_CAMERA:
            assert any(v in sh["action"][1] for v in NPR.BODY_VERBS), (shot_id, "R7：无对白 ≥3 s 且机位非 ARC/TRACK/CRANE/PAN 时动作须含身体动词")
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
# seq=12/13：同场内远景小人影之后的露脸镜必须声明 identity_reanchor
FAR_MARK = ("FAR_FIGURE", "MEDIUM_WIDE_WALKING", "BACK_TO_CAMERA")
REANCHOR_MISSING: list[str] = []
for sid, shots in by_scene.items():
    seen_far = False
    for sh in shots:
        f = (sh.get("faces") or {}).get("QM", "")
        if "QM" in sh["cast"] and any(m in f for m in FAR_MARK):
            seen_far = True; continue
        if "QM" in sh["cast"] and seen_far and not f:  # 可测脸的镜
            if not sh.get("identity_reanchor"):
                REANCHOR_MISSING.append(f"{sid}-{sh['n']:02d}")
            seen_far = False
assert not REANCHOR_MISSING, ("远景小人影之后的露脸镜须 identity_reanchor", REANCHOR_MISSING)
TOTAL = sum(m["sec"] for m in SCENES.values())
assert 170 <= TOTAL <= 185, TOTAL

# ---------- 关键台词逐字核对（源章 + narrative） ----------
src_text = SRC_CH3.read_text(encoding="utf-8")
narr = SCRIPTS / f"{EP}_NARRATIVE_CANONICAL_{VER}.md"
narr_text = narr.read_text(encoding="utf-8")
AUTHORED_DIALOGUE = {
    "有门！": "ch3：「他在雪地上看到某种动物留下的痕迹，顿时觉得有门！」内心叙述转一声自语，字取自源章",
    "秦铭全副武装去野外了，像是要猎大型猛兽！": "ch3：「有人提及，秦铭全副武装去野外了，看他那种架势，感觉像是要去猎杀大型猛兽！」村民议论的间接引语转村民乙直接对白，压缩不增事实",
    "那小子怎么能一个人冒险外出，该不会去猎熊了吧？": "ch3：「陆泽也得到消息，眉头深锁，那小子怎么能一个人冒险外出，该不会去猎熊了吧？」内心叙述转自语，字取自源章",
    "那里，还不是我能去的地方。": "ch3：「秦铭知道，那里意味着未知，神秘，危险，不是他所能踏足的地界。」叙述转自语，不增事实",
}
SPLIT_QUOTES = {"它的体形比同类大，八成变异了。": "ch3 单句「它的体形比同类大，八成变异了，如果能找到主巢，应该会收获不小。」前半，逗号改句号，字不变",
                "如果能找到主巢，应该会收获不小。": "同一源句后半，字不变"}
KEY_QUOTES, DIALOGUE_UNITS = [], []
for sh in SHOTS:
    if sh.get("dialogue"):
        spk, q, _ = sh["dialogue"]; shot = f"{sh['s']}-{sh['n']:02d}"
        assert f"{cname(spk)}：“{q}”" in narr_text, ("台词未逐字进 narrative", q)
        if q in AUTHORED_DIALOGUE:
            DIALOGUE_UNITS.append((spk, q, shot, False))
        else:
            assert q in src_text or q.rstrip("。！？") in src_text, ("key_quote 不在源章逐字文本中", q)
            KEY_QUOTES.append((spk, q, shot)); DIALOGUE_UNITS.append((spk, q, shot, True))
narr_lines = re.findall(r'^(秦铭|陆泽|邻居甲|村民乙)：“(.+?)”$', narr_text, re.M)
assert [(cname(s), q) for s, q, *_ in DIALOGUE_UNITS] == narr_lines, ("镜头表对白顺序/说话人与 narrative 不一致", narr_lines)

# ---------- 道具扫描（与引擎 editorial scan 同名） ----------
PROP_KEYWORDS = (("PROP-HUNTING-FORK", ["猎叉"]), ("PROP-SHORT-KNIFE", ["短刀"]), ("PROP-BOW-ARROWS", ["弓箭"]), ("PROP-HIDE-BAG", ["兽皮袋"]),
                 ("PROP-NUT-HOARD", ["干果", "野核桃", "栗子", "红枣"]), ("PROP-HUMANFACE-VULTURE", ["人面鹫"]),
                 ("PROP-RED-SQUIRREL", ["红松鼠"]), ("PROP-SUN-STONE", ["太阳石"]), ("SET-HOLLOW-TREE", ["树洞"]), ("SET-FIRE-SPRING", ["火泉"]))
PROP_NAME = {**{p["entity_id"]: p["name"] for p in PROPS}, **{s["entity_id"]: s["name"] for s in SETS}, "PROP-SUN-STONE": "太阳石"}
def _props_in(sh):
    txt = sh["action"][1] + sh["entry"] + sh["exit"]
    return [eid for eid, kws in PROP_KEYWORDS if any(k in txt for k in kws)]
PROP_MISSING: list = []
for sh in SHOTS:  # 出场道具必须在 entry_state 可见：名字出现在 action 里就必须也出现在 entry 里（关键帧＝entry）
    shot_id = f"{sh['s']}-{sh['n']:02d}"
    for eid, kws in PROP_KEYWORDS:
        if eid in ("PROP-SUN-STONE", "SET-HOLLOW-TREE", "SET-FIRE-SPRING"):
            continue
        if any(k in sh["action"][1] for k in kws):
            if not (any(k in sh["entry"] for k in kws) or any(k in sh["exit"] for k in kws)):
                PROP_MISSING.append((shot_id, eid))
assert not PROP_MISSING, ("道具在 action 出现但 entry/exit 未声明", PROP_MISSING)

TRANSITION_NOTES = {
    ("E03-S01-01", "E03-S01-02"): ("MOTIVATED_CUT", "猎叉拎起后切俯拍木碗，切在拎起动作上"),
    ("E03-S01-02", "E03-S01-03"): ("CAMERA_REFRAME", "走到门前后改取门口中近景，切点在回头之前"),
    ("E03-S02-01", "E03-S02-02"): ("MOTIVATED_CUT", "村民抬头后切环绕，切在秦铭抬手上"),
    ("E03-S02-02", "E03-S02-03"): ("CAMERA_REFRAME", "村民回头愣住后改取高机位远景，秦铭已到火泉旁"),
    ("E03-S03-01", "E03-S03-02"): ("CAMERA_REFRAME", "推进几步后改取面部特写，切在呼气上；身份再锚定"),
    ("E03-S03-02", "E03-S03-03"): ("MOTIVATED_CUT", "结霜后切低机位中全景，切在迈步上"),
    ("E03-S04-01", "E03-S04-02"): ("MOTIVATED_CUT", "站定后切横摇，切在停步转身上"),
    ("E03-S04-02", "E03-S04-03"): ("CAMERA_REFRAME", "盯住树洞后改取面部特写"),
    ("E03-S04-03", "E03-S04-04"): ("MOTIVATED_CUT", "第一句说完后切低机位环绕，切在开口第二句之前"),
    ("E03-S05-01", "E03-S05-02"): ("MOTIVATED_CUT", "绷紧停步后切低机位横移，切在转身上"),
    ("E03-S05-02", "E03-S05-03"): ("MOTIVATED_CUT", "扫视到右后切仰拍，切在猛抬头上"),
    ("E03-S05-03", "E03-S05-04"): ("CAMERA_REFRAME", "叉头出画后改取高机位树杈，人面鹫入画"),
    ("E03-S05-04", "E03-S05-05"): ("MOTIVATED_CUT", "俯冲到头顶后切低机位迎击，切在叉与鹫相接上"),
    ("E03-S06-01", "E03-S06-02"): ("MOTIVATED_CUT", "走进松桦林后切停步抬头，切在停步上"),
    ("E03-S06-02", "E03-S06-03"): ("CAMERA_REFRAME", "说完后改取树洞边缘特写，切在俯身上"),
    ("E03-S06-03", "E03-S06-04"): ("MOTIVATED_CUT", "皱眉后切低机位，切在直起身上"),
    ("E03-S07-01", "E03-S07-02"): ("MOTIVATED_CUT", "「有门」说完后切远景，切在霞光冲起的一瞬"),
    ("E03-S07-02", "E03-S07-03"): ("CAMERA_REFRAME", "霞光消退后改取中近景，切在转身上；身份再锚定"),
    ("E03-S07-03", "E03-S07-04"): ("MOTIVATED_CUT", "盯住树洞后切洞口冰花特写"),
    ("E03-S08-01", "E03-S08-02"): ("MOTIVATED_CUT", "猎叉插雪后切低机位，切在跳起上"),
    ("E03-S08-02", "E03-S08-03"): ("CAMERA_REFRAME", "攀到洞前后改取短刀特写，切在挥刀上"),
    ("E03-S08-03", "E03-S08-04"): ("MOTIVATED_CUT", "黑影缩回后切横移，切在再次挥刀上"),
    ("E03-S08-04", "E03-S08-05"): ("MOTIVATED_CUT", "套袋后切低机位，切在探臂上"),
    ("E03-S09-01", "E03-S09-02"): ("REACTION_CUT", "干果被照亮后切眼睛特写"),
    ("E03-S09-02", "E03-S09-03"): ("CAMERA_REFRAME", "红松鼠入画后改取皮毛特写"),
    ("E03-S09-03", "E03-S09-04"): ("MOTIVATED_CUT", "啃袋后切中近景，切在取铁丝上"),
    ("E03-S10-01", "E03-S10-02"): ("REACTION_CUT", "松鼠吱吱叫后切秦铭掂袋"),
    ("E03-S10-02", "E03-S10-03"): ("MOTIVATED_CUT", "一句说完挂上猎叉后切横移，切在迈步上"),
    ("E03-S10-03", "E03-S10-04"): ("CAMERA_REFRAME", "第三个树洞入画后改取最早树洞的特写"),
    ("E03-S11-01", "E03-S11-02"): ("MOTIVATED_CUT", "栗子入口后切中近景，切在搓枣上"),
    ("E03-S11-02", "E03-S11-03"): ("REACTION_CUT", "笑容后切倒挂的红松鼠"),
    ("E03-S11-03", "E03-S11-04"): ("REACTION_CUT", "松鼠僵住后切秦铭伸手摇它"),
    ("E03-S12-01", "E03-S12-02"): ("REACTION_CUT", "邻居甲点头后切陆泽走来"),
    ("E03-S13-01", "E03-S13-02"): ("CAMERA_REFRAME", "站上山顶后改取背影横摇"),
    ("E03-S13-02", "E03-S13-03"): ("CAMERA_REFRAME", "群山深处的光之后改取面部特写；身份再锚定"),
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
LOCKED_IDS = [f"{s['s']}-{s['n']:02d}" for s in SHOTS if CAMERA_PLANS[f"{s['s']}-{s['n']:02d}"]["motion_family"] == "LOCKED"]
lines = [f"# 《夜无疆》{EP} 导演稿 {VER}（directing script）", "",
         f"绑定 narrative：`{narr.name}`（SHA256 {sha(narr)}）", "",
         "本层只写景别、机位、轴线、走位与起止态；**不改 narrative 的任何事实**。逐镜秒标为交付口径。", "",
         "## 本集口径（SUPERVISOR_ORDERS seq=7 / seq=10 / seq=12 / seq=13）", "",
         f"- 全局风格：{STYLE['era_idiom']}",
         f"- 夜景：{STYLE['night_look']}",
         "- 禁用：" + "、".join(STYLE["forbidden"]),
         f"- 节奏：单镜 {PACING['shot_seconds_default'][0]}–{PACING['shot_seconds_default'][1]} s（台词确需时 6 s：E03-S10-02 / S12-01 / S12-02；本集无 7 s 镜）；视频单元 ≤{PACING['video_unit_seconds_max']:g} s（硬上限 {PACING['video_unit_seconds_hard_cap']:g} s）；无对白静止 ≤{PACING['no_dialogue_static_hold_seconds_max']:g} s 否则拒收；全集前 3 s 钩子＝短刀入腰带、拎猎叉；每场首镜从进行中动作开始、场间在动作上切、每场有转折与 button；全集 {PACING['episode_total_seconds_target'][0]}–{PACING['episode_total_seconds_target'][1]} s（本稿 {TOTAL} s，{len(SHOTS)} 镜）",
         f"- 机位运动：LOCKED ≤35%（本稿 {len(LOCKED_IDS)}/{len(SHOTS)}：{'、'.join(LOCKED_IDS)}）、不连续 LOCKED、无对白镜必动、R7 无对白 ≥3 s 须身体动词或 ARC/TRACK/CRANE/PAN、R8 台词镜 ≥ 字数/语速 + 1.5 s、LOCKED 只用于 ≤5 s 对白镜、同轴同景别不连续 >2 镜、开场镜运动",
         "- ★seq=12/13 身份再锚定：E03-S03-02、E03-S07-03、E03-S13-03 为远景小人影之后的露脸镜，声明 identity_reanchor（引擎 e19 以角色板关键帧为身份参考）；不写全黑/极暗；本集无儿童对白",
         "- ★选择性配乐（D-32）：E03-S05（人面鹫来袭）、E03-S11（收获与松鼠气死）、E03-S13（山顶望群山）三处纯器乐，其余原生现场声",
         "- ★承接：E03-S01-01 的 entry_state 接 E02-S13-06 的 completion_state（秦铭手按胸口、眼睛睁着盯窗、决定浅夜一到就走）；本集浅夜已到，他已起身，不复位、不重演", ""]
for sid, meta in SCENES.items():
    lines.append(f"## {sid}｜{meta['loc']}｜{meta['time']}｜{meta['sec']}s｜{meta['weather']}｜光：{meta['light']}")
    lines.append("")
    for sh in by_scene[sid]:
        shot_id = f"{sid}-{sh['n']:02d}"; cp = CAMERA_PLANS[shot_id]
        lines.append(f"### {shot_id}（{sh['sec']}s）｜{sh['size']}｜{sh['camera']}｜{cp['motion_family']}/{cp['motion_direction']}" + ("｜identity_reanchor" if sh.get("identity_reanchor") else ""))
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
# ---------- END OF CHUNK 5 ----------

# ---------- generation contract ----------
NPR_FACE = {"QM": "束发木簪、无胡须的清瘦年轻男子", "LZ": "灰布裹巾的结实青年", "VA": "麻布头巾的瘦削中年村民", "VB": "皮帽圆脸的矮壮村民"}
NPR_APPLIED: dict[str, list[str]] = {}
NPR_BLOCKS: list[str] = []
NON_CHAR_SUBJECTS = {p["entity_id"]: p["name"] for p in PROPS} | {"LOC-DISTANT-MOUNTAINS": "群山深处"}

def ent_name(k):
    return cname(k) if k in CH else NON_CHAR_SUBJECTS.get(k, k)
def ent_id(k):
    # engine character_entity_contract: any non-empty id must resolve to a CHARACTER; creatures/props keep the name, id empty
    return cid(k) if k in CH else ""

def apply_prompt_rules(sh, shot_id, act):  # seq=10：E03 起全部镜头套用
    sid = sh["s"]
    scene_cast = {k for x in by_scene[sid] for k in x["cast"]}
    fam = (CAMERA_PLANS.get(shot_id) or {}).get("motion_family")
    shot = {"shot_id": shot_id, "sec": sh["sec"], "size": sh["size"], "camera_family": fam, "cast": sh["cast"],
            "action": act, "dialogue": sh.get("dialogue"), "entry": sh["entry"], "exit": sh["exit"]}
    ctx = {"scene_cast": scene_cast, "loc": SCENES[sid]["loc"], "cps": sh.get("cps"),
           "names": {k: cname(k) for k in CH}, "face_desc": NPR_FACE,
           "prop_tokens": ["火泉", "太阳石", "铜盆", "食盒", "猎叉", "短刀", "弓箭", "兽皮袋", "干果", "人面鹫", "红松鼠", "树洞"]}
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
    slots = sh.get("slots") or {}; faces = sh.get("faces") or {}
    states = {cid(k): sh["exit"] for k in sh["cast"]}
    subj_is_char = subj in CH
    return {
        "shot_id": shot_id, "scene_id": sid, "target_seconds": sh["sec"],
        "shot_size": sh["size"], "camera": sh["camera"], "axis": sh["axis"], "blocking": sh["blocking"],
        "entry_state": sh["entry"], "completion_state": sh["exit"],
        "state_delta_dimensions": list(sh["dims"].keys()),
        "state_delta_evidence": {d: {"entry": a, "exit": b, "entry_code": ca, "exit_code": cb} for d, (a, b, ca, cb) in sh["dims"].items()},
        "keyframe_source": "entry_state",
        "period_constraints": PERIOD_BY_LOC[SCENES[sid]["loc"]],
        "pacing_flags": {"hook": shot_id == "E03-S01-01", "scene_opener_in_motion": sh["n"] == 1, "scene_button": sh is by_scene[sid][-1],
                         "no_dialogue_static_hold_seconds_max": PACING["no_dialogue_static_hold_seconds_max"] if not dlg else None},
        **({"dialogue_delivery": {"chinese_characters_per_second": sh["cps"], "basis": "导演稿：按 nalu_prompt_rules.min_dialogue_seconds 放不进默认语速的句子标 4.8–5.0 字/秒，文本零改动"}} if sh.get("cps") else {}),
        "prompt_spec": {
            "camera_plan": {**CAMERA_PLANS[shot_id], "authorship": "DIRECTING_SCRIPT_AUTHORED", "selection_mode": "LOCKED", "source": f"E03_DIRECTING_SCRIPT_v1.md#{shot_id}"},
            "cast": [{"character": cname(k), "character_id": cid(k),
                      **({"screen_slot": slots[k]} if k in slots else {}), **({"face_visibility": faces[k]} if k in faces else {})} for k in sh["cast"]],
            "props": [{"prop_id": p, "prop": PROP_NAME[p]} for p in _props_in(sh)],
            "dialogue": f"{cname(dlg[0])}：{dlg[1]}" if dlg else "",
            "action": {"subject_id": ent_id(subj) if subj else "", "primary_action": act, "patient_id": ent_id(patient) if patient else ""},
            **({"identity_reanchor_required": True, "identity_reanchor_reason": "seq=12/13：同场内远景小人影之后的露脸镜；本镜以角色板生成的关键帧作身份再锚定参考（engine e19）"} if sh.get("identity_reanchor") else {}),
            "referent_resolution_contract": {"status": "PASS", "source_scan_complete": True, "resolved_source_referents": resolved, "unresolved_source_referents": []},
            "role_semantic_disambiguation": {
                "primary_actor_kind": "CHARACTER" if subj_is_char else ("CREATURE" if subj else "ENVIRONMENT"),
                "primary_actor": ent_name(subj) if subj else "", "primary_actor_id": ent_id(subj) if subj else "",
                "dialogue_speaker": cname(dlg[0]) if dlg else "", "dialogue_speaker_id": spk_id,
                "dialogue_listener": cname(dlg[2]) if dlg and dlg[2] else "", "dialogue_listener_id": lst_id,
                "action_patient": ent_name(patient) if patient else "", "action_patient_id": ent_id(patient) if patient else "",
                "lip_owner_id": spk_id, "entity_states": states, "entity_presence": presence},
        },
    }

CHARACTER_ROWS = [
    {"character_id": "CHAR-QINMING", "canonical_name": "秦铭", "aliases": ["小秦", "小叔", "秦叔", "那小子"], "voice_entity_id": "", "identity_reference_entity_id": "",
     "identity_source": {"mode": "SOURCE_PHOTO", "file": str(QM_SOURCE_V2), "sha256": STYLE_RESET_DISCLOSURE["qinming_identity_source"]["sha256"], "note": "E02 已按 source_v2 锁定的三视图身份牌直接复用（seq=13）；不重做"},
     "appearance_ch1": "清瘦颀长，面色有血色，眼睛清亮；高髻木簪，外披旧裘氅，内深青交领窄袖袍银线滚边（唐宋语汇；面孔与发冠服制以 CHAR-QINMING__SOURCE_V2_TANG.png 为准）",
     "appearance_ch3": "ch3：全副武装（猎叉、短刀、弓箭）、常年锻炼身体敏捷、雪中跋涉眉毛发梢结霜、秀气的面孔上满是开心的笑容"},
    {"character_id": "CHAR-LUZE", "canonical_name": "陆泽", "aliases": ["陆哥"], "voice_entity_id": "", "identity_reference_entity_id": "", "identity_source": {"mode": "E02_IDENTITY_CARD_REUSE", "note": "沿用 E02 唐宋版身份牌，不重做"},
     "appearance_ch1": "年轻男子，身体结实有力，实在人；深灰交领短褐、灰布裹巾束发", "appearance_ch3": "ch3：得到消息眉头深锁，「该不会去猎熊了吧」"},
    {"character_id": "CHAR-VILLAGER-A", "canonical_name": "邻居甲", "aliases": ["村民甲", "两位村民", "有人"], "voice_entity_id": "", "identity_reference_entity_id": "", "identity_source": {"mode": "E01_IDENTITY_CARD_RESTYLED", "note": "沿用 E01 面孔，服制改唐宋短褐头巾（同 E02 对陆泽/梁婉清的处理）；本集不说话"},
     "appearance_ch1": "北街路口无名邻居；中等瘦削中年男子，麻布头巾包髻", "appearance_ch3": "ch3：村道上迎面遇到秦铭、被笑着打招呼却没反应过来；火泉旁听村民乙议论，点头"},
    {"character_id": "CHAR-VILLAGER-B", "canonical_name": "村民乙", "aliases": ["圆脸村民"], "voice_entity_id": "", "identity_reference_entity_id": "", "identity_source": {"mode": "TEXT_TO_IMAGE", "note": "无源照片；按 appearance 文生图生成身份牌（seq=3 c3）；本集一句台词"},
     "appearance_ch1": "矮壮圆脸的中年村民，兽皮护耳帽、灰褐交领棉袍，说话爱比划", "appearance_ch3": "ch3：村道上被秦铭打招呼没反应过来；火泉旁提及秦铭全副武装去野外像是要猎大型猛兽"},
]
BGM_CUES = [
    {"cue_id": "E03-BGM-01", "scenes": ["E03-S05"], "narrative_function": "THREAT_AMBUSH", "volume": 0.28, "dialogue_duck_db": -8,
     "brief": "Tense cinematic instrumental cue for a night forest ambush in an ancient Chinese Tang-Song setting: low taiko-like drum pulses, muted guzheng tremolo, a sudden dissonant erhu stab, no melody, rising dread then a sharp release, no vocals, 20 seconds"},
    {"cue_id": "E03-BGM-02", "scenes": ["E03-S11"], "narrative_function": "COMIC_RELIEF_HARVEST", "volume": 0.22, "dialogue_duck_db": -8,
     "brief": "Playful warm instrumental cue in ancient Chinese folk style: pizzicato pipa, short bamboo dizi phrases, light hand percussion, gentle humour, a snowy forest picnic, no vocals, 18 seconds"},
    {"cue_id": "E03-BGM-03", "scenes": ["E03-S13"], "narrative_function": "VISTA_RESOLVE_OPEN_QUESTION", "volume": 0.30, "dialogue_duck_db": -8,
     "brief": "Wide mysterious and quietly hopeful instrumental cue: sustained guqin harmonics, slow low string swell, a distant single bell, vast night mountains with a faint glow in the mist, no vocals, 15 seconds"},
]
contract = {
    "schema": "qingshan.generation_contract.v3",
    "episode": EP, "version": VER,
    "narrative_canonical": narr.name, "narrative_sha256": sha(narr),
    "style": {**STYLE, "authority": "SUPERVISOR_ORDERS seq=7 c1/c2；seq=13 沿用；PRODUCTION_LINE_OVERVIEW_v1 §四 3/5", "negative_prompt_fixed": "欧式、哥特、和风、仙侠符文、现代物件、冷灰去饱和、暗黑调色、玻璃窗、电灯、拉链纽扣、纯黑画面"},
    "pacing": PACING,
    "style_reset_disclosure": STYLE_RESET_DISCLOSURE,
    "carry_in": {"previous_episode": "E02", "previous_scene_id": "E02-S13", "previous_shot_id": PREV_LAST["shot_id"],
                 "previous_completion_state": PREV_LAST["completion_state"],
                 "first_shot_id": "E03-S01-01", "first_shot_entry_state": SHOTS[0]["entry"],
                 "rule": "不复位、不重演、不闪回 E02 内容，沿同一方向推进至少一步（决定浅夜出发→浅夜已到、已起身→短刀入腰带、拎猎叉）"},
    "visual_culture_contract": {
        "schema": "qingshan.visual_culture_contract.v1", "status": "LOCKED",
        "profile_id": STYLE["profile_id"], "decision_owner": "WRITER_DIRECTOR",
        "decision_basis": "ch3 明写：猎叉、短刀、弓箭、兽皮袋、铁丝、太阳石、野核桃栗子红枣、人面鹫、变异红松鼠、樟子松阔叶树白桦、地光；Roger 2026-09-13 审片意见：整体画风中国唐宋，不要西式暗黑；seq=13 禁写全黑",
        "source_ref": str(SRC_CH3),
        "story_world": "永夜纪元的北地冻土村落与村外雪野密林，前工业农耕渔猎社会，中国唐宋衣冠与营造",
        "production_design": STYLE["era_idiom"] + "；野外无任何人造物；光源只有太阳石、火泉与雪面月色反光；地光为远方山地冲起的橘红霞光",
        "armor_tradition": "本集无兵甲；猎具为木柄铁头猎叉、直刃短刀、竹木弓与皮箭囊，不得出现制式铁札甲、西式甲胄或现代猎具",
        "palette_system": {"base": "靛黑夜色、雪面月色青蓝、林木深青灰", "accent": "太阳石橘红、火泉火红、地光橘红、红松鼠火红皮毛", "skin": "雪光下清、太阳石光下暖；秦铭有血色"},
        "lighting_language": STYLE["night_look"] + "；野外浅夜以雪面反光写层次，最暗处仍见轮廓；太阳石为手持点光源；地光一闪整片密林亮成橘红后回到青蓝",
        "image_texture": "颗粒感胶片质感、真实材质（兽皮、粗麻、枯木、雪、铁）、雪雾与呼出的白气可见、火光有可见的边缘晕",
        "forbidden_influences": STYLE["forbidden"],
    },
    "character_entities": [dict(row, wardrobe_garments=WARDROBE_GARMENTS[row["character_id"]]) for row in CHARACTER_ROWS],
    "non_character_entities": [
        {"entity_id": "PROP-SUN-STONE", "name": "太阳石", "reference_card_required": False, "note": "红灿灿发光石块，光而不烫；E01 已建立，本集为秦铭怀中取出的手持光源，不单独出卡"},
        *PROPS, *SETS,
    ],
    "props": {"authority": "SUPERVISOR_ORDERS seq=7 c6：关键道具出参考卡入资产库并挂进视频参考列表", "reference_cards": [p for p in PROPS + SETS if p.get("reference_card_required")], "declared_without_card": [p["entity_id"] for p in PROPS if not p["reference_card_required"]]},
    "scene_states": [
        {"scene_id": sid, "location_id": m["loc"], "time_id": m["time"], "weather": m["weather"], "lighting": m["light"],
         "target_seconds": m["sec"], "source_events": m["beats"], "new_information_count": m["info"],
         "ambient_life": m["ambient_life"], "weather_provenance": m["weather_provenance"], "period_constraints": PERIOD_BY_LOC[m["loc"]]}
        for sid, m in SCENES.items()],
    "shots": [shot_json(sh) for sh in SHOTS],
    "internal_transition_authoring": [{"from_shot_id": a, "to_shot_id": b, "authorship": "DIRECTOR_AUTHORED", **row} for (a, b), row in INTERNAL_TRANSITIONS.items()],
    "audio_contract": {
        "bgm": {"mode": "SELECTIVE", "used": True, "authority": "SUPERVISOR_ORDERS seq=13 c2 / D-32",
                "declaration": "SELECTIVE_NARRATIVE_CUES：三处纯器乐配乐（人面鹫来袭、收获与松鼠气死、山顶望群山），覆盖 ≤85%，其余全部原生现场声（≥8 s 纯现场声）；经 AgentCut bgm-generate → giggle generate-music 生成，受预算守卫与事务存档约束",
                "cues": BGM_CUES},
        "ambient_by_scene": {
            "E03-S01": "屋外脚步与人声、铜盆火霞低鸣、衣料摩擦、猎叉木柄碰炕沿", "E03-S02": "村道渐静、踩雪、呼气白雾、火泉低频嗡鸣",
            "E03-S03": "深雪塌陷的闷响、粗重呼吸、寒风", "E03-S04": "枝上落雪、踩雪、怪鸟突兀啼鸣、林中寂静",
            "E03-S05": "寒风刮起、猎叉破风、翅膀扑风、尖锐鸣叫响彻山林", "E03-S06": "踩雪、树皮摩擦、呼气",
            "E03-S07": "蹲下衣料声、地光无声、寒风渐起、树枝吱呀", "E03-S08": "蹑足踩雪、猎叉插雪、跳起攀树、短刀砍木咚响、树体碎裂、洞里乱撞与慌乱叫声",
            "E03-S09": "太阳石无声、松鼠啃咬皮袋、铁丝勒紧、干果哗啦入袋", "E03-S10": "松鼠吱吱叫、皮袋掂动、踩雪、干果哗啦",
            "E03-S11": "核桃壳裂、咀嚼、雪搓红枣、松鼠挣扎后寂静、寒风", "E03-S12": "火泉低频嗡鸣、人声交谈、踩雪走近",
            "E03-S13": "山顶寒风、裘氅猎猎、远处林涛",
        },
        "dialogue_units": [{"shot_id": shot, "speaker_id": cid(s), "listener_id": cid(sh_l) if sh_l else "", "text": q, "verbatim_in_source": v}
                           for (s, q, shot, v), sh_l in zip(DIALOGUE_UNITS, [sh["dialogue"][2] for sh in SHOTS if sh.get("dialogue")])],
    },
}
contract_path = SCRIPTS / f"{EP}_GENERATION_CONTRACT_{VER}.json"
if NPR_BLOCKS:
    raise SystemExit("nalu_prompt_rules BLOCK (restage the shot): " + "; ".join(NPR_BLOCKS))
print("nalu_prompt_rules applied to", len(NPR_APPLIED), "shots")
contract_path.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("contract written", contract_path)
# ---------- END OF CHUNK 6 ----------

# ---------- manifest ----------
BEATS = [  # ch3 实读 26 拍；落点到场次粒度（gate 10 读 landed_at）
    ("E03-EV-01", "landed", "E03-S01-01", "浅夜到来，各家忙着去火泉取太阳石（屋外脚步与人声）"),
    ("E03-EV-02", "landed", "E03-S01-01 至 E03-S01-02", "秦铭随时准备出发，猎叉、短刀、弓箭全副武装"),
    ("E03-EV-03", "landed", "E03-S01-02", "已吃过陆泽送来的面饼（木碗碎渣），没有说要外出，怕被劝阻"),
    ("E03-EV-04", "dropped", "", "并不想以身涉险，打算去相对安全地带碰运气——内心动机不单独占镜，由 S04 两句台词与「不深入」的行动承担"),
    ("E03-EV-05", "landed", "E03-S01-03", "想起秋季山林中看到的一抹踪影，应该栖居在附近；「希望它还在，能够带给我惊喜」"),
    ("E03-EV-06", "landed", "E03-S02-01", "外面逐渐安静，没有人再去取太阳石"),
    ("E03-EV-07", "landed", "E03-S02-01 至 E03-S02-02", "路上遇到两位村民，笑着打招呼，对方还没反应过来他已快速远去"),
    ("E03-EV-08", "landed", "E03-S02-03", "路过火泉所在地，进入漆黑的世界"),
    ("E03-EV-09", "landed", "E03-S03-01 至 E03-S03-02", "积雪没过胸口大半截身子看不到；呼出的白雾在眉毛发梢结成冰霜"),
    ("E03-EV-10", "landed", "E03-S03-03", "手持猎叉艰难跋涉四里路，前面黑压压一片密集林木显出轮廓（「四里路」不演）"),
    ("E03-EV-11", "landed", "E03-S04-01 至 E03-S04-02", "目标是山林边缘不深入；进入密林，大多数树木光秃秃枝上满雪；停下回想那个生物的活动轨迹与树洞"),
    ("E03-EV-12", "landed", "E03-S04-03 至 E03-S04-04", "「它的体形比同类大，八成变异了，如果能找到主巢，应该会收获不小」（拆两镜）；林中怪鸟啼鸣，继续前行"),
    ("E03-EV-13", "landed", "E03-S05-01 至 E03-S05-05", "闻到腐臭绷紧、持叉扫视、猛然向头顶刺去；黑影倒吊树杈惨白老人脸俯冲；钢叉迎击、尖叫、滑向一旁展翼冲上夜空远去"),
    ("E03-EV-14", "dropped", "", "人面鹫习性科普（食腐、四十斤、正常不攻击活人、是否因猎物难寻而反常）——世界观科普不单独占镜（Roger 短剧节奏口径）"),
    ("E03-EV-15", "landed", "E03-S06-01 至 E03-S06-02", "戒备很长时间它没再出现；重新上路；「应该就是这里」，樟子松阔叶树白桦林地，找到曾见的树洞"),
    ("E03-EV-16", "landed", "E03-S06-03 至 E03-S06-04", "树洞边缘很干净没有冰霜，不是好现象（失望）；微微皱眉；右手握猎叉左手攥短刀准备在附近找"),
    ("E03-EV-17", "landed", "E03-S07-01", "半刻钟后在雪地上看到动物痕迹，顿时觉得有门（「半刻钟」不演）"),
    ("E03-EV-18", "landed", "E03-S07-02 至 E03-S07-03", "大片霞光在前方山地冲起瞬息照亮密林；一惊，警觉观察四野；霞光消失天地重归墨色"),
    ("E03-EV-19", "landed", "E03-S07-04", "发现另一个结着冰花的树洞，露出发自真心的灿烂笑容（地光成因与夏季雨云烟霞科普不演）"),
    ("E03-EV-20", "landed", "E03-S08-01 至 E03-S08-03", "蹑手蹑脚到水桶粗大树前放下猎叉，猛然一跃抱树攀到树洞前；短刀砍洞口咚响，刚要冲出的生物缩回"),
    ("E03-EV-21", "landed", "E03-S08-04 至 E03-S08-05", "连着挥刀树体碎裂洞变大；兽皮袋套手捕兽；整条手臂探进被乱撞；一把抓住猎物薅出（「意外之喜」内心不演）"),
    ("E03-EV-22", "landed", "E03-S09-01 至 E03-S09-02", "太阳石照树洞深处，野核桃栗子红枣满满干货；清澈的眼睛焕发火热光彩；侧头看小兽"),
    ("E03-EV-23", "landed", "E03-S09-03 至 E03-S09-04", "红松鼠火红皮毛比绸缎丝滑、发光、两斤多明显变异（体重常识不演）；啃咬兽皮袋；铁丝捆紧挂树上；一把把掏干果袋鼓胀（「超过八斤」由 S10 台词承担）"),
    ("E03-EV-24", "landed", "E03-S10-01 至 E03-S10-04", "倒挂松鼠黑宝石眼瞪圆吱吱叫似在骂人；「你这么重，八斤出头的过冬粮食怎么够你吃」挂在猎叉上；持太阳石找到第二第三树洞，最早那洞也有存粮（不埋地下的常识不演）"),
    ("E03-EV-25", "landed", "E03-S11-01 至 E03-S11-02", "剥核桃吃、吃一把栗子、雪搓红枣连吃五颗满嘴甜；不饿了，秀气面孔满是笑容；四个巢穴三十几斤装了大半袋（数字不演）"),
    ("E03-EV-26", "landed", "E03-S11-03 至 E03-S11-04", "松鼠看到四个巢穴被搬空直挺挺僵住不动；诧异摇它，气死了；「正好，小文睿说想吃肉了，可以煮一锅肉汤」"),
    ("E03-EV-27", "landed", "E03-S12-01 至 E03-S12-02", "双树村村民议论秦铭全副武装去野外像要猎大型猛兽；陆泽得到消息眉头深锁，该不会去猎熊了吧"),
    ("E03-EV-28", "landed", "E03-S13-01", "站在高地离山顶很近，密林最外部的矮山；没再找到其他松鼠洞（不演）；来到山顶"),
    ("E03-EV-29", "landed", "E03-S13-02 至 E03-S13-03", "望向前方林木黑压压、莽莽群山只剩模糊黑影；大山深处有明灿地带被夜雾遮挡只漾出少许朦胧的光；那里未知神秘危险，不是他能踏足的地界"),
]
NEW_GSMS = [
    {"map_id": "GSM-YEWUJIANG-SNOWFIELD-WILDS", "location_id": "LOC-SNOWFIELD-WILDS-EXT", "status": "NAMED_ONLY_NO_GEOMETRY", "scenes": ["E03-S03"],
     "note": "村北火泉以外的雪原：齐胸深积雪，无路，远处林线；几何由 S2 extend_global_space_map 按 new_location_place_spec 生成"},
    {"map_id": "GSM-YEWUJIANG-FOREST-EDGE", "location_id": "LOC-FOREST-EDGE-EXT", "status": "NAMED_ONLY_NO_GEOMETRY", "scenes": ["E03-S04", "E03-S05", "E03-S06", "E03-S07", "E03-S08", "E03-S09", "E03-S10", "E03-S11"],
     "note": "雪原尽头的密林边缘：光秃阔叶树区（S04–S05）、樟子松白桦林与树洞大树区（S06–S11）；不深入"},
    {"map_id": "GSM-YEWUJIANG-LOW-HILL-TOP", "location_id": "LOC-LOW-HILL-TOP-EXT", "status": "NAMED_ONLY_NO_GEOMETRY", "scenes": ["E03-S13"],
     "note": "密林最外部区域的矮山山顶，面向群山深处"},
]
manifest = {
    "episode": EP, "version": VER, "title": "野外世界",
    "canonical_script": f"workflow/claude_writer_agent/scripts/{narr.name}", "script_sha256": sha(narr),
    "directing_script": f"workflow/claude_writer_agent/scripts/{directing.name}", "directing_sha256": sha(directing),
    "generation_contract": f"workflow/claude_writer_agent/scripts/{contract_path.name}", "generation_contract_sha256": sha(contract_path),
    "supersedes": "",
    "★supersedes_disclosure": "首版，无前版。nalu 线《夜无疆》E03 首次交付；按 seq=7/10/12/13 口径编排；narrative 13 场 10 句对白零改动（其中一句源章 29 字长句按单镜 3–7 s 规则拆为两行两镜，字不变，已在 narrative 排版口径与 key_quote_landing 申报）。",
    "authorization": {"order_seq": 13, "order_id": "ROGER-20260914-NALU-E03-START", "also": ["seq=3 ROGER-20260909-NALU-E01-E10-PRODUCTION-AUTHORIZED", "seq=7 ROGER-20260913-NALU-E02-NEW-RULES-TANG-SONG-PACING-SOURCE-V2", "seq=10 root-cause prompt rules", "seq=12 identity re-anchor rule"], "orders_file": "workflow/claude_writer_agent/SUPERVISOR_ORDERS.json"},
    "writer_identity": {"agent_id": "claude-code-nalu-writer", "provider": "anthropic", "model_id": "claude-fable-5-1", "session_note": "Claude Code 交互会话，Roger 2026-09-14 现场指令「开始做e03」「继续做e03」"},
    "source_binding": {
        "work": "夜无疆", "author": "辰东",
        "primary_source_chapter": "3", "source_chapters": ["3"], "chapter_title": "野外世界",
        "source_file": str(SRC_CH3), "source_sha256": sha(SRC_CH3),
        "source_index": str(RUNTIME / "sources/夜无疆/SOURCE_INDEX.json"),
        "episode_source_map": str(RUNTIME / "runtime/episode_source_map_yewujiang_v1.json"),
        "beat_count": len(BEATS), "beats_landed": sum(1 for b in BEATS if b[1] == "landed"), "beats_merged": 0, "beats_dropped": sum(1 for b in BEATS if b[1] == "dropped"),
        "★carry_in_is_bound_to_the_previous_episode_bytes": f"承接 E02_NARRATIVE_CANONICAL_v1.md E02-S13 末段实际字节（narrative 头部逐字引全文五行）与 E02 合同末镜 {PREV_LAST['shot_id']} completion_state「{PREV_LAST['completion_state']}」；E03-S01-01 entry_state 为浅夜已到、已起身、短刀在手；不复位、不重演、不闪回 E02 内容。",
        "carry_in": contract["carry_in"] | {"previous_canonical": "workflow/claude_writer_agent/scripts/E02_NARRATIVE_CANONICAL_v1.md", "previous_canonical_sha256": sha(SCRIPTS / "E02_NARRATIVE_CANONICAL_v1.md"), "previous_contract_sha256": sha(PREV_CONTRACT), "anchor_lines_quoted_in_narrative_header": 5},
    },
    "beat_disposition": [{"event_id": e, "disposition": d, "landed_at": at, "summary": s} for e, d, at, s in BEATS],
    "★authorized_insertions": [],
    "authored_dialogue_from_indirect_speech": [
        {"shot_id": shot, "speaker": cname(s), "text": q, "source_basis": AUTHORED_DIALOGUE[q]} for s, q, shot, v in DIALOGUE_UNITS if not v],
    "★audience_already_knows": ["永夜世界", "太阳石取自火泉", "秦铭怪病将愈与体表银光", "陆泽接济与面饼", "密林有庞然大物出没（E02-S08 陆泽已说）"],
    "★style_reset_disclosure": STYLE_RESET_DISCLOSURE,
    "structure": [{"beat_id": f"{EP}-B{idx+1:02d}", "scene_id": sid, "target_seconds": m["sec"], "thread": "线A", "location_id": m["loc"], "time_id": m["time"], "source_events": m["beats"], "new_information_count": m["info"]}
                  for idx, (sid, m) in enumerate(SCENES.items())],
    "scene_breakdown_seconds": {sid: m["sec"] for sid, m in SCENES.items()},
    "total_seconds": TOTAL,
    "runtime_target_seconds": {"min": 170.0, "target": 178.0, "max": 185.0},
    "shot_count": len(SHOTS),
    "pacing": PACING,
    "key_quote_landing": [{"speaker": cname(s), "quote": q, "shot_id": shot, "verbatim_in_source": True, **({"split_note": SPLIT_QUOTES[q]} if q in SPLIT_QUOTES else {})} for s, q, shot in KEY_QUOTES],
    "fs1": {"combat_clusters": [{"cluster_id": "E03-FS1-VULTURE", "shots": ["E03-S05-03", "E03-S05-04", "E03-S05-05"], "seconds": 11, "source": "ch3 人面鹫俯冲、钢叉迎击（源章明写，非原创打斗）"}], "combat_seconds": 11, "note": "ch3 唯一的动作冲突为人面鹫来袭（一击即走）；捕松鼠为捕猎不计打斗。"},
    "identity_registry": {cid(k): cname(k) for k in CH} | {p["entity_id"]: p["name"] for p in PROPS} | {s["entity_id"]: s["name"] for s in SETS} | {"PROP-SUN-STONE": "太阳石"},
    "new_name_budget": {"budget_per_4_episodes": 1, "writer_invented_names_this_episode": 0, "note": "邻居甲沿 E01；村民乙为源章「有人/一部分村民」的无名指代，不计新名；人面鹫、红松鼠为源章物种名"},
    "distinct_locations": sorted({m["loc"] for m in SCENES.values()}),
    "new_locations": ["LOC-SNOWFIELD-WILDS-EXT", "LOC-FOREST-EDGE-EXT", "LOC-LOW-HILL-TOP-EXT"],
    "episode_global_space_map_id": "GSM-YEWUJIANG-SHUANGSHU-VILLAGE-V1",
    "global_space_map_refs": [
        {"map_id": "GSM-YEWUJIANG-QINMING-LUZE-ADJOINING-HOMESTEAD", "scenes": ["E03-S01"], "anchors": ["火炕", "炕沿木碗", "屋门"], "axis_note": "炕（西）—屋门（东）轴"},
        {"map_id": "GSM-YEWUJIANG-FIRE-SPRING-TWIN-TREES", "scenes": ["E03-S02", "E03-S12"], "anchors": ["村道自南来的进路", "石围池沿", "村外雪野边界（北）"], "axis_note": "S02 秦铭自南向北走过火泉出村；S12 两位村民与陆泽在石围南侧"},
        *NEW_GSMS,
    ],
    "shot_subspace_bindings": [{"shot_id": f"{sh['s']}-{sh['n']:02d}", "location_id": SCENES[sh["s"]]["loc"]} for sh in SHOTS],
    "onscreen_text_shot_level_registry": [],
    "state_delta_contract_summary": {"shots_total": len(SHOTS), "shots_with_entry_ne_completion": len(SHOTS), "min_dimensions_per_shot": min(len(sh["dims"]) for sh in SHOTS), "extend_words_in_action_fields": 0},
    "camera_motion_summary": {"locked_shots": LOCKED_IDS, "locked_share": round(len(LOCKED_IDS) / len(SHOTS), 3), "policy": PACING["camera_motion_policy"], "direction_rebalanced": CAMERA_DIRECTION_REBALANCED},
    "identity_reanchor_shots": [f"{sh['s']}-{sh['n']:02d}" for sh in SHOTS if sh.get("identity_reanchor")],
    "bgm_selective_cues": BGM_CUES,
    "writer_self_check": {"every_scene_asked_which_source_beat": True, "scenes_without_source_beat": [], "undeclared_insertions": 0, "dialogue_lines_total": len(DIALOGUE_UNITS), "dialogue_lines_verbatim_in_source": len(KEY_QUOTES), "dialogue_lines_authored_from_narration": len(DIALOGUE_UNITS) - len(KEY_QUOTES), "dialogue_order_matches_narrative": True},
}
manifest_path = SCRIPTS / f"{EP}_manifest_{VER}.json"
manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

print(json.dumps({
    "narrative": {"path": str(narr), "sha256": sha(narr)},
    "directing": {"path": str(directing), "sha256": sha(directing)},
    "contract": {"path": str(contract_path), "sha256": sha(contract_path), "shots": len(SHOTS)},
    "manifest": {"path": str(manifest_path), "sha256": sha(manifest_path), "total_seconds": manifest["total_seconds"], "scenes": len(SCENES)},
    "camera_direction_rebalanced": CAMERA_DIRECTION_REBALANCED,
}, ensure_ascii=False, indent=2))
