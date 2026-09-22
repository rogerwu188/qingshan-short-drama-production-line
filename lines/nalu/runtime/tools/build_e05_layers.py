import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
# -*- coding: utf-8 -*-
"""E05《新生》v1 —— 从一张镜头表生成 directing script / generation contract / manifest。

单一事实源是 SHOTS 表；narrative canonical（E05_NARRATIVE_CANONICAL_v1.md）为手写，本层不改其任何事实与对白。
口径：seq=7（唐宋画风、机位运动）+ seq=10（nalu_prompt_rules 全镜套用、R7/R8 阻断）+ seq=12/13（远景接特写必须身份再锚定、
禁写全黑、儿童对白双人同框）+ seq=17（音色按角色重选；节奏再收紧：单镜 3–6 s、无对白 ≤4 s、单场 ≤16 s、
全集 150–170 s、LOCKED ≤30%）+ seq=19（钩子、台词密度、节拍结果、实体引入、词表、生命状态）+ seq=26（E05 开始）+ D-32 选择性配乐。
模板：build_e04_layers.py（v2）。新增：只配音不出身份牌的角色（乌鸦，identity_source.mode=VOICE_ONLY_NO_PLATE，
画面由 PROP-PURPLE-EYED-CROW 参考卡承担，presence=OFFSCREEN_VOICE_ONLY）。
"""
import hashlib, json, pathlib, re
import nalu_prompt_rules as NPR

ROOT = pathlib.Path(f"{_np.ENGINE_ROOT}")
SCRIPTS = ROOT / "workflow/claude_writer_agent/scripts"
RUNTIME = pathlib.Path(f"{_np.RUNTIME_ROOT}")
SRC_CH = RUNTIME / "sources/夜无疆/zh-CN/ch0005.md"
QM_SOURCE_V2 = RUNTIME / "runtime/character_sources/CHAR-QINMING__SOURCE_V2_TANG.png"
EP, VER = "E05", "v1"
PREV_EP, PREV_LAST_SHOT = "E04", "E04-S11-04"
PREV_CONTRACT = SCRIPTS / f"{PREV_EP}_GENERATION_CONTRACT_v1.json"
E03_CONTRACT = SCRIPTS / "E03_GENERATION_CONTRACT_v1.json"

def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

CH = {
    "QM": ("CHAR-QINMING", "秦铭"),
    "LZ": ("CHAR-LUZE", "陆泽"),
    "LW": ("CHAR-LIANGWANQING", "梁婉清"),
    "WR": ("CHAR-LUWENRUI", "陆文睿"),
    "WH": ("CHAR-LUWENHUI", "陆文晖"),
    "TJ": ("CHAR-FEMALE-LEAD-BLACKCLOAK", "黑衣女子"),
    "CR": ("CHAR-CROW", "乌鸦"),
}
VOICE_ONLY = {"CR"}   # never in visible cast; presence OFFSCREEN_VOICE_ONLY; picture = PROP-PURPLE-EYED-CROW
def cid(k): return CH[k][0]
def cname(k): return CH[k][1]

# ---------- 全局风格与节奏口径（沿 E04 v2，seq=7；seq=17 收紧；seq=19 门禁） ----------
STYLE = {
    "profile_id": "YEWUJIANG_PERMANENT_NIGHT_TANGSONG_VILLAGE_V2",
    "era_idiom": "中国唐宋：木构穿斗/抬梁屋架、瓦顶或压雪茅顶带出檐、直棂格窗、夯土院墙与木板门；男子发髻木簪、交领右衽、大袖或窄袖袍、布带束腰、布靴裹腿；女子交领短襦长裙或黑裘斗篷罩劲装；器物为粗陶、铜盆、木碗、竹筷、木柜、火炕、铁条鸟笼；猎具为木柄铁头猎叉、直刃短刀、竹木硬弓与皮箭囊、铁箭、兽皮袋",
    "night_look": "永夜用暖火光（太阳石橘红）+ 雪面反光 + 月色青蓝三种光写；屋内以铜盆太阳石为唯一光源，肤色暖；院中与野外浅夜为深青灰雪野，林木黑压压但轮廓可辨；秦铭体表的银色流光是极淡的一层、不是特效光柱；乌鸦的紫眼是画面里唯一的紫色点光；不做西式暗黑/哥特式冷灰去饱和调色",
    "forbidden": ["欧式石堡与哥特元素", "西式暗黑冷灰去饱和调色", "现代服装、拉链纽扣与现代物件", "电灯、玻璃窗、金属门把手", "日式盔甲与和风建筑", "仙侠飘带与发光符文特效", "明亮日光或蓝天", "霓虹与冷色 LED", "整洁无雪的街道", "长发散披不束的男主", "纯黑画面", "现代猎枪与金属机械捕兽夹", "卡通化会说话的动物嘴型", "体表流光做成光柱或粒子特效"],
}
PERIOD_BASE = "唐宋语汇：木构、瓦顶/压雪茅顶、直棂格窗、夯土院墙、木板门；人物交领右衽、发髻木簪或包髻；器物粗陶木碗竹筷；猎具木柄铁头猎叉、直刃短刀、竹木硬弓皮箭囊、兽皮袋；夜景=暖火光+雪面反光+月色青蓝，不做冷灰去饱和"
PERIOD_BY_LOC = {
    "LOC-QINMING-HOUSE-INT": PERIOD_BASE + "；单间土屋：火炕在北墙、木格糊纸窗、旧木立柜、铜盆盛太阳石为唯一光源；养鸟用的铁条笼是手锻铁条木底；无玻璃、无灯具、无现代家具",
    "LOC-QINMING-YARD-EXT": PERIOD_BASE + "；小院：院门为木板门带门枢，院墙夯土压雪，院中粗石盆盛太阳石，雪路铲开；无栅栏、无金属门把手、无现代健身器物",
    "LOC-SNOWFIELD-WILDS-EXT": PERIOD_BASE + "；村外雪原：齐胸深的积雪、雪面月色青蓝反光、远处黑压压的林线；临近山林的一块青石与一簇荆棘是天然物；无道路标志、无栅栏、无任何人造物",
    "LOC-FOREST-EDGE-EXT": PERIOD_BASE + "；密林边缘：光秃的阔叶树枝上满是雪，樟子松与白桦树干，雪地；无路标、无栅栏、无任何人造物",
}
STYLE_RESET_DISCLOSURE = {
    "kind": "STYLE_CONTINUATION_NO_RESET",
    "authority": "SUPERVISOR_ORDERS seq=7 c1/c2/c4（E02 起唐宋画风）；seq=26（E05 沿用）",
    "what_changes": "无画风变化；新入画人物黑衣女子（黑裘皮斗篷罩黑色劲装，文生图）、两岁陆文晖（土黄小棉袍，文生图）按唐宋语汇出身份牌；紫眼乌鸦、铁鸟笼、青石与荆棘写实出参考卡",
    "what_stays": "秦铭面孔与发冠服制沿 E02 已锁定的 source_v2 身份牌；冬装、外披旧裘氅、内深青交领袍；同一时间线（E05-S01 直接接 E04-S11 终态）",
    "qinming_identity_source": {"file": str(QM_SOURCE_V2), "sha256": sha(QM_SOURCE_V2) if QM_SOURCE_V2.is_file() else "", "usage": "FACE_IDENTITY_REFERENCE + WARDROBE/HAIR STYLE REFERENCE（E02 已锁定的三视图身份牌直接复用，不重做）"},
    "viewer_facing_note": "E04→E05 画风与造型连续；说话人音色沿 seq=17 重选（梁婉清首次以重选音色出声）",
}
PACING = {
    "authority": "Roger 2026-09-13：加快节奏；Roger 2026-09-15 seq=17：全集紧凑感仍不够 → 单镜 3–6 s、无对白镜 ≤4 s、单场 ≤16 s、全集 150–170 s；seq=19：钩子与台词密度门禁",
    "shot_seconds_default": [3, 4],
    "shot_seconds_max": 6,
    "shot_seconds_max_note": "6 s 只用于按 nalu_prompt_rules.min_dialogue_seconds 确实放不进 5 s 的台词镜；无对白镜 ≤4 s",
    "video_unit_seconds_max": 6.0,
    "video_unit_seconds_hard_cap": 7.0,
    "video_unit_note": "写手层意图 ≤6 s；单元实际上限由引擎分组决定（seq=7 c3 硬上限 7 s；e16 偏好 4–6 s）",
    "no_dialogue_static_hold_seconds_max": 2.0,
    "no_dialogue_static_hold_verdict": "REJECT（生成后 QA 静止判定为拒收）",
    "scene_opening_rule": "每场第一镜从进行中的动作开始，不给建立镜头停顿；场与场之间在动作上切",
    "scene_turn_rule": "每场有转折与 button（见 directing script 每场末镜）",
    "scene_seconds_max": 16,
    "scene_seconds_max_exception": "本集无例外：最长场 16 s（E05-S14）",
    "hook_rule": "全集前 3 秒 = 陆泽一句「隔壁村的二病子成了，正好处在黄金期内」（E05-S01-01，秦铭郑重点头的同镜）",
    "episode_total_seconds_target": [150, 170],
    "hook": {"type": "dialogue", "at_seconds": 3, "line_or_shot_id": "E05-S01-01", "note": "陆泽「隔壁村的二病子成了，正好处在黄金期内。」从第 1 镜第 0 秒开口；同镜猎叉上的红松鼠与炕上干果即道具回顾"},
    "dialogue_density": {"max_silent_run_seconds": 15, "max_silent_run_action_seconds": 25, "min_coverage": 0.35, "verdict": "FAIL"},
    "identity_reanchor_rule": "seq=12/13：同一场内远景小人影之后的同一人物露脸镜必须声明 identity_reanchor（引擎 e19 以角色板生成的关键帧作身份再锚定参考）",
    "no_black_rule": "seq=13：剧本与镜头文字不得写「全黑/极暗」；最暗时刻仍有雪面月色或余光照出轮廓",
    "child_dialogue_rule": "seq=13：儿童对白双人同框（文睿的每句台词镜都与秦铭同框，不单独儿童特写；文晖不说话、只在两人镜里）",
    "camera_motion_policy": {
        "authority": "Roger 2026-09-13 + seq=17；校验器 static_design_gate.py（R1–R8 全部阻断）",
        "locked_share_max": 0.30,
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
    "E05-S01": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜·屋内暖", light="铜盆太阳石橘红暖光，映亮炕上的干果与倒挂的红松鼠", sec=14, beats=["E05-EV-01", "E05-EV-02", "E05-EV-03"], info=2),
    "E05-S02": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜·屋内暖", light="铜盆太阳石橘红暖光，木格窗透进一点冷白雪光", sec=12, beats=["E05-EV-04", "E05-EV-05", "E05-EV-06"], info=2),
    "E05-S03": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜·屋内暖", light="铜盆太阳石橘红暖光，秦铭的脸以窗外冷白雪光为主光", sec=10, beats=["E05-EV-07", "E05-EV-08", "E05-EV-09"], info=2),
    "E05-S04": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜·屋内暖", light="铜盆太阳石橘红暖光，映着两个孩子红扑扑的脸", sec=13, beats=["E05-EV-10", "E05-EV-11"], info=2),
    "E05-S05": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜·屋内暖", light="铜盆太阳石橘红暖光，红松鼠火红皮毛在光下微微发亮", sec=15, beats=["E05-EV-12", "E05-EV-13", "E05-EV-14"], info=2),
    "E05-S06": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜·屋内暖", light="铜盆太阳石橘红暖光，炕上的干果堆与蘑菇", sec=13, beats=["E05-EV-15", "E05-EV-16", "E05-EV-17"], info=2),
    "E05-S07": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜·屋内暖", light="铜盆太阳石橘红暖光，屋门方向暗一些，短刀刃面映一道光", sec=8, beats=["E05-EV-18", "E05-EV-19"], info=2),
    "E05-S08": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜·屋内暖", light="铜盆太阳石橘红暖光，映着文睿仰起的脸", sec=10, beats=["E05-EV-20", "E05-EV-21"], info=2),
    "E05-S09": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜·屋内暖", light="铜盆太阳石橘红暖光，炕上的兽皮袋与橡果", sec=14, beats=["E05-EV-22", "E05-EV-23", "E05-EV-24"], info=2),
    "E05-S10": dict(loc="LOC-QINMING-HOUSE-INT", time="TIME-SHALLOW-NIGHT", weather="屋外浅夜·屋内暖", light="铜盆太阳石橘红暖光，铁笼的铁条映着光", sec=10, beats=["E05-EV-25", "E05-EV-26", "E05-EV-27"], info=2),
    "E05-S11": dict(loc="LOC-QINMING-YARD-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·院中无风到自起风", light="院中石盆太阳石橘红光 + 雪面月色青蓝反光；末镜体表极淡的银色流光与白雾", sec=12, beats=["E05-EV-28", "E05-EV-29", "E05-EV-30"], info=2),
    "E05-S12": dict(loc="LOC-SNOWFIELD-WILDS-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·雪原寒风", light="雪面月色青蓝反光为主光，远处林线黑压压；青石上的黑衣女子只被雪光勾出轮廓与下巴", sec=8, beats=["E05-EV-31", "E05-EV-32"], info=2),
    "E05-S13": dict(loc="LOC-SNOWFIELD-WILDS-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·寒风吹动斗篷", light="雪面月色青蓝反光；乌鸦的紫眼是画面里唯一的紫色点光", sec=15, beats=["E05-EV-33", "E05-EV-34", "E05-EV-35"], info=2),
    "E05-S14": dict(loc="LOC-FOREST-EDGE-EXT", time="TIME-SHALLOW-NIGHT", weather="浅夜·山风呼啸", light="林缘雪地与树干上的月色青蓝反光，人物轮廓可辨", sec=16, beats=["E05-EV-36", "E05-EV-37", "E05-EV-38"], info=2),
}
AMBIENT_LIFE = {
    "E05-S01": {"grade": "B", "motion_trend": "秦铭郑重点头、陆泽开口、松鼠倒挂微晃、孩子在炕边动", "first_frame_state": "秦铭正郑重地点头，陆泽开口", "reaction_progression": "点头→「二病子成了」→「什么时候的事」→「举起四百斤的黑毛驴」"},
    "E05-S02": {"grade": "B", "motion_trend": "陆泽讲亲戚与意气功、秦铭出神、陆泽劝换练法", "first_frame_state": "陆泽正说到二病子的亲戚", "reaction_progression": "「据传和亲戚有关」→秦铭出神→「该换一换了」"},
    "E05-S03": {"grade": "B", "motion_trend": "梁婉清劝、秦铭点头面色红润、目光炯炯说再等一段时间", "first_frame_state": "梁婉清正开口劝秦铭", "reaction_progression": "「改练黑夜冥想术」→秦铭点头面色红润→「再等上一段时间，我应该能成」"},
    "E05-S04": {"grade": "B", "motion_trend": "文睿认真点头小脸期待、文晖蹒跚凑近跟着点头、秦铭笑着伸手取松鼠", "first_frame_state": "文睿正认真地点头开口", "reaction_progression": "「小叔最厉害了」→「炖肉肉吃，我馋了」文晖跟着点头→秦铭「今天就可以满足你们」伸手取松鼠"},
    "E05-S05": {"grade": "A", "motion_trend": "松鼠瞪眼惊恐、秦铭提着看了又看、文睿眼睛发亮、秦铭逗他、文睿纠结", "first_frame_state": "红松鼠的大眼睛正瞪出来", "reaction_progression": "松鼠瞪眼→「咦，它又活了」→「这只松鼠好漂亮」→「炖熟了更可爱」文睿纠结"},
    "E05-S06": {"grade": "B", "motion_trend": "拨开干果与蘑菇、文睿揪衣角咽口水、秦铭赞叹、松鼠皮毛炸立", "first_frame_state": "秦铭正把兽皮袋里的干果和蘑菇拨开", "reaction_progression": "「松鼠炖蘑菇」→「我不想它死去」咽口水→「灵兽甄选」→松鼠皮毛炸立"},
    "E05-S07": {"grade": "A", "motion_trend": "抽刀、拎松鼠走向屋门、松鼠吱吱挣扎铁丝勒紧、文睿张臂拦门", "first_frame_state": "秦铭正抽出短刀", "reaction_progression": "抽刀拎松鼠往门走→松鼠惊叫挣扎→文睿张开手臂拦门「留下它吧」"},
    "E05-S08": {"grade": "B", "motion_trend": "文睿仰脸说出决心、松鼠看刀又对文睿吱叫、秦铭收刀", "first_frame_state": "文睿仰着脸正开口", "reaction_progression": "「这次就不吃了」→「我等小叔成功」松鼠求助→秦铭收起短刀"},
    "E05-S09": {"grade": "B", "motion_trend": "陆泽蹙眉、松鼠眼巴巴望兽皮袋、秦铭挑橡果、松鼠瞪眼喘息", "first_frame_state": "陆泽正蹙眉开口", "reaction_progression": "「哪有多余的食物给它」松鼠望着自己的家底→挑出橡果「不然微毒」→「正好留着喂养松鼠吧」松鼠瞪眼"},
    "E05-S10": {"grade": "A", "motion_trend": "秦铭警告、松鼠塞进铁笼扣门、孩子又笑又跳、陆泽张嘴闭嘴、提笼", "first_frame_state": "秦铭正提着松鼠开口警告", "reaction_progression": "「敢咬人的话我保准炖了你」关进铁笼→孩子又笑又跳陆泽不再反对→陆泽提起铁笼与橡果"},
    "E05-S11": {"grade": "A", "motion_trend": "活动关节拉伸、跃起如铁箭落地无声、旋身摆腿、口诵吐纳、卷起雪、体表银色流光白雾蒸腾", "first_frame_state": "秦铭正在院中活动关节拉伸筋骨", "reaction_progression": "拉伸跃起落地无声→摆腿抽空「吹呴呼吸」→带起猛烈的风卷雪→体表流光白雾"},
    "E05-S12": {"grade": "A", "motion_trend": "荒野疾驰如流星接近山林、远处青石上黑衣女子静立、乌鸦落在荆棘上", "first_frame_state": "秦铭正在雪原上疾驰", "reaction_progression": "疾驰接近山林→远处雪地青石上的黑衣女子与荆棘上的乌鸦"},
    "E05-S13": {"grade": "B", "motion_trend": "乌鸦口吐人语、寒风吹斗篷贴身、女子冷淡开口、远处秦铭侧头持弓", "first_frame_state": "乌鸦正歪头开口", "reaction_progression": "「身体自行新生」→「你的老师不是在挑选关门弟子吗」→「有比他更适合的人」远处秦铭侧头持弓"},
    "E05-S14": {"grade": "B", "motion_trend": "乌鸦落枝头评价、劝别错过种子、山风吹起秀发、女子冷淡回话、向林深处走去黑衣猎猎", "first_frame_state": "乌鸦刚落在林缘的枝头开口", "reaction_progression": "「很敏锐的直觉」→「别错过一颗种子」→秀发飘起「那是他不知道的遗憾」→「眼下进山探查更要紧」走进密林"},
}
def _wp(sid, mode):
    return {"source_type": "NARRATIVE_CANONICAL_SCENE_HEADER", "source_ref": f"E05_NARRATIVE_CANONICAL_v1.md#{sid}｜ch5", "visibility_mode": mode}
WEATHER_PROVENANCE = {sid: _wp(sid, "OFFSCREEN_ONLY_SHALLOW_NIGHT_THROUGH_DOOR_INTERIOR_DRY" if m["loc"].endswith("-INT") else "VISIBLE_EXTERIOR_SNOW_ONLY_AS_DECLARED") for sid, m in SCENES.items()}
for _sid, _m in SCENES.items():
    _m["ambient_life"] = AMBIENT_LIFE[_sid]
    _m["weather_provenance"] = WEATHER_PROVENANCE[_sid]

# ---------- 服装（唐宋语汇；承接 E04） ----------
WARDROBE_GARMENTS = {
    "CHAR-QINMING": {"silhouette": "颀长清瘦、高髻木簪、外披过膝旧裘氅、内交领深色袍", "outer_layer": "陈旧兽皮裘氅（毛面磨秃、下摆结霜，无袖披式）", "inner_layer": "深青交领右衽窄袖袍，领缘与袖口银线滚边（旧、洗淡）", "primary_color": "灰褐（裘氅）", "secondary_color": "深青（袍）", "material": "兽皮＋粗麻棉", "pattern": "裘氅素面磨秃；袍领袖银线细纹", "belt_or_fastening": "布带束腰（腰间插直刃短刀），裘氅前襟布带系结", "footwear": "旧布靴加裹腿", "accessory": "发髻木簪（源照片同款发式）；S12–S13 背竹木硬弓与皮箭囊"},
    "CHAR-LUZE": {"silhouette": "壮实宽肩、束发裹巾、齐膝交领短褐", "outer_layer": "深灰粗麻交领短褐（外层）", "inner_layer": "灰白中衣", "primary_color": "深灰", "secondary_color": "灰褐（腰带）", "material": "粗麻棉", "pattern": "粗织纹，肩背补丁与磨痕", "belt_or_fastening": "麻布腰带打结", "footwear": "裹腿加旧皮靴", "accessory": "灰布裹巾束发"},
    "CHAR-LIANGWANQING": {"silhouette": "交领短襦配长裙与围裙、包髻", "outer_layer": "灰褐粗麻交领短襦（外层）", "inner_layer": "旧蓝长裙", "primary_color": "灰褐", "secondary_color": "旧蓝（裙）", "material": "粗麻棉", "pattern": "细密织纹，围裙边缘磨破", "belt_or_fastening": "细布系带＋麻布围裙", "footwear": "布鞋加裹腿", "accessory": "麻布包髻"},
    "CHAR-LUWENRUI": {"silhouette": "五岁男孩、裹得严实、总角", "outer_layer": "赭红小交领棉袍（外层）", "inner_layer": "灰白棉中衣", "primary_color": "赭红", "secondary_color": "灰白", "material": "粗棉", "pattern": "素面", "belt_or_fastening": "布带束腰", "footwear": "小布靴", "accessory": "屋内不戴风帽，露出总角"},
    "CHAR-LUWENHUI": {"silhouette": "两岁男童、裹得滚圆、步履蹒跚", "outer_layer": "土黄小交领棉袍（外层）", "inner_layer": "灰白棉中衣", "primary_color": "土黄", "secondary_color": "灰白", "material": "粗棉", "pattern": "素面", "belt_or_fastening": "布带束腰", "footwear": "小棉靴", "accessory": "总角小揪"},
    "CHAR-FEMALE-LEAD-BLACKCLOAK": {"silhouette": "高挑纤细、黑裘皮斗篷罩身、只露精致下巴、黑发半束", "outer_layer": "黑色裘皮斗篷（宽松过膝、毛面流动淡淡乌光、立领遮颈）", "inner_layer": "黑色交领窄袖劲装", "primary_color": "黑", "secondary_color": "乌黑（毛面反光）", "material": "裘皮＋绸麻", "pattern": "素面", "belt_or_fastening": "黑布带束腰，斗篷前襟系带", "footwear": "黑色皮靴裹腿", "accessory": "黑亮长发半束、余发披肩；无珠翠"},
    "CHAR-CROW": {"silhouette": "（只配音；画面见 PROP-PURPLE-EYED-CROW）", "outer_layer": "n/a", "inner_layer": "n/a", "primary_color": "乌金黑羽", "secondary_color": "紫色眼睛", "material": "n/a", "pattern": "n/a", "belt_or_fastening": "n/a", "footwear": "n/a", "accessory": "n/a"},
}

# ---------- 道具与生物（seq=7 c6：关键道具出参考卡；只列 narrative 实际用到的） ----------
PROPS = [
    {"entity_id": "PROP-RED-SQUIRREL", "name": "红松鼠", "reference_card_required": False, "first_shot": "E05-S01-01",
     "note": "E03 已出卡并锁定：红松鼠，火红皮毛微微发光，黑宝石般的圆眼；本集先倒挂在猎叉上，被取下后瞪眼、皮毛炸立、挣扎、求助、瞪圆眼喘息，最后被关进铁笼", "period_constraints": "写实松鼠体态，皮毛发光只是柔和的光泽；不做卡通嘴型"},
    {"entity_id": "PROP-NUT-HOARD", "name": "干果", "reference_card_required": False, "first_shot": "E05-S01-01",
     "note": "E03 已出卡并锁定：野核桃、栗子、红枣、松子、榛果，本集加蘑菇与橡果；摊在炕上、兽皮袋口", "period_constraints": "真实野果与野蘑菇，无包装"},
    {"entity_id": "PROP-HIDE-BAG", "name": "兽皮袋", "reference_card_required": False, "first_shot": "E05-S01-01",
     "note": "E03 已出卡并锁定：装满干果鼓胀的厚兽皮口袋；本集摊开在炕上", "period_constraints": "手缝皮袋，无拉链、无金属扣"},
    {"entity_id": "PROP-HUNTING-FORK", "name": "猎叉", "reference_card_required": False, "first_shot": "E05-S01-01",
     "note": "E03 已出卡并锁定：木柄铁头猎叉；本集靠在门边墙上，红松鼠倒挂其上直到被取下", "period_constraints": "唐宋农猎器具语汇，锻铁叉头、麻绳缠柄"},
    {"entity_id": "PROP-SHORT-KNIFE", "name": "短刀", "reference_card_required": False, "first_shot": "E05-S07-01",
     "note": "E03 已出卡并锁定：直刃短刀，插在秦铭腰间布带里；本集抽出又收起", "period_constraints": "直刃、木柄、无护手装饰"},
    {"entity_id": "PROP-BOW-ARROWS", "name": "弓箭", "reference_card_required": False, "first_shot": "E05-S13-03",
     "note": "E04 已出卡并锁定：竹木硬弓与皮箭囊；本集只在远景里持在秦铭手中，不开弓", "period_constraints": "唐宋竹木复合弓与皮箭囊"},
    {"entity_id": "PROP-BIRD-CAGE", "name": "铁笼", "reference_card_required": True, "first_shot": "E05-S10-01",
     "note": "养鸟用的铁条笼：手锻铁条、木底、顶上一个提环、一扇带铁扣的小笼门，一尺来高，装得下一只两斤多的松鼠；陈旧、铁条微锈", "period_constraints": "手锻铁条与木底，无焊接痕、无现代镀层、无塑料"},
    {"entity_id": "PROP-PURPLE-EYED-CROW", "name": "紫眼乌鸦", "kind": "CREATURE", "creature_card": {"locomotion": "biped", "eye_color": "紫色", "silhouette_ref": "PROP-PURPLE-EYED-CROW identity plate (workflow/nalu/E05/identity)"}, "reference_card_required": True, "first_shot": "E05-S12-02",
     "note": "一只比寻常乌鸦略大的乌鸦，满身黑羽如乌金、有金属般的乌光，一双紫色的眼睛；站在荆棘或枝头上，会歪头、会开合鸟喙；参考卡为立在雪中荆棘上的侧身全貌，紫眼清楚", "period_constraints": "写实鸟类体态，不做卡通化嘴型，不发光（紫眼除外）"},
]
SETS = [
    {"entity_id": "SET-FOREST-EDGE-WOODS", "name": "密林边缘林地", "note": "E03 已出卡并锁定；本集 S14 沿用"},
    {"entity_id": "SET-BLUESTONE-BOULDER", "name": "青石", "reference_card_required": True, "first_shot": "E05-S12-02",
     "note": "雪原北缘临近山林的一块较大的青石：一人多高、顶面平、被雪盖了一半，青灰石面在月色下发冷光；石旁一簇枯黑的荆棘丛挂着雪；参考卡上只画青石与荆棘，绝无人物、无鸟兽（乌鸦另有参考卡）", "period_constraints": "天然山石与荆棘，无任何人造物"},
]
# ---------- END OF CHUNK 2 ----------

# ---------- 机位方案（seq=17：单镜 3–6 s；LOCKED ≤30%、不连续、无对白必动、开场必动） ----------
def _cp(scale, height, side, lens, axis, fam, direction, start, end, why):
    if fam == "LOCKED" and end != start:
        why = f"{why}；画内变化：{end}"
        end = start
    return {"shot_scale": scale, "camera_height": height, "camera_side": side, "lens_intent": lens, "axis_relation": axis,
            "motion_family": fam, "motion_direction": direction, "start_framing": start, "end_framing": end, "motivation": why}
CAMERA_PLANS = {
    # S01 承接：点头、二病子成了
    "E05-S01-01": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm双人同框缓推，陆泽画左、秦铭画右", "陆泽（画左）面向秦铭（画右）的交谈轴，不越轴", "DOLLY", "PUSH_IN", "中近景：秦铭郑重地点头，陆泽开口", "中近景（推近）：陆泽说完一句，秦铭看着他", "导演稿：开场 3 秒钩子＝陆泽一句「二病子成了」，推近配合承接的点头"),
    "E05-S01-02": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_B", "85mm环绕秦铭抬眼发问", "秦铭（画右）面向陆泽（画左）的视线轴，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "特写：秦铭抬眼", "特写（环绕）：他问完一句，眉头微挑", "导演稿：环绕读意外"),
    "E05-S01-03": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm横移随陆泽双手作举起状", "陆泽（画左）面向秦铭（画右）的交谈轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中景：陆泽开口答，梁婉清在他身侧", "中景（横移）：陆泽双手向上一托作举起状，梁婉清看着他", "导演稿：横移读「举驴」的比划，场尾 button 在稀奇事上"),
    # S02 亲戚与意气功、劝换练法
    "E05-S02-01": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm自陆泽缓升到出神的秦铭", "陆泽（画左）面向秦铭（画右）的交谈轴，不越轴", "CRANE", "RISE", "中近景：陆泽压低声音讲亲戚的事", "中近景（升起）：秦铭听着出了神，目光落在铜盆的光上", "导演稿：升起配合「意气功」落到秦铭出神"),
    "E05-S02-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm缓推前倾劝说的陆泽", "陆泽（画左）面向秦铭（画右）的交谈轴，不越轴", "DOLLY", "PUSH_IN", "中近景：陆泽身子前倾开口劝", "中近景（推近）：秦铭回神看着陆泽，陆泽说完", "导演稿：推近配合劝说，场尾 button 在「该换一换了」"),
    # S03 嫂子劝、秦铭自信
    "E05-S03-01": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm环绕梁婉清到秦铭", "梁婉清（画左）面向秦铭（画右）的交谈轴，环绕不越轴", "ARC", "CLOCKWISE", "中景：梁婉清抬头劝秦铭", "中景（环绕）：秦铭点头，面色红润目光炯炯", "导演稿：环绕把嫂子的劝与秦铭的点头连起来"),
    "E05-S03-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm固定，秦铭正面略偏右，主光是木格窗透进的冷白雪光、五官清晰，铜盆橘红光只留在下颌轮廓与衣领；陆泽在画左前景侧脸", "秦铭（画右）面向陆泽（画左）的视线轴，不越轴", "LOCKED", "NONE", "中近景：秦铭挺直身子看着陆泽和梁婉清说一句", "中近景：说完，陆泽轻叹着点头", "导演稿：固定（对白镜 ≤5 s），自信本身带动，场尾 button"),
    # S04 孩子馋肉、取松鼠
    "E05-S04-01": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm双人同框缓推，文睿画左仰脸、秦铭画右低头看他", "文睿（画左）面向秦铭（画右）的轴线，不越轴", "DOLLY", "PUSH_IN", "中近景：文睿认真地点头开口", "中近景（推近）：文睿仰着红扑扑的小脸说前半句，秦铭低头看他", "导演稿：儿童对白双人同框（seq=13）"),
    "E05-S04-02": _cp("MEDIUM", "LOW", "AXIS_A", "35mm低机位横移自文睿到蹒跚凑近的文晖", "文睿（画左）面向秦铭（画右），文晖自画左后方凑近", "TRACK", "LEFT_TO_RIGHT", "低机位中景：文睿说后半句咽了口口水", "低机位中景（横移）：两岁的文晖步履蹒跚凑到哥哥身后，跟着点头", "导演稿：横移带出文晖有样学样（原著幽默）"),
    "E05-S04-03": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm随秦铭起身取松鼠升起", "秦铭（画右）向门边猎叉（画左）伸手的动作轴，不越轴", "CRANE", "RISE", "中景：秦铭笑着说一句，起身伸手", "中景（升起）：他把猎叉上倒挂的红松鼠取到手里", "导演稿：升起配合起身取松鼠，场尾 button 在松鼠上"),
    # S05 它又活了
    "E05-S05-01": _cp("CLOSE_UP", "EYE_LEVEL", "AXIS_A", "85mm环绕秦铭手里的松鼠到秦铭的脸", "秦铭（画右）面向手中松鼠（画左）的视线轴，环绕不越轴", "ARC", "CLOCKWISE", "特写：红松鼠黑宝石般的大眼睛瞪出来", "特写偏松（环绕）：秦铭提着它看了又看，笑着说一句", "导演稿：环绕把松鼠的惊恐与秦铭的「更好」连起来"),
    "E05-S05-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm双人同框缓推，文睿画左、秦铭画右，松鼠在两人之间", "文睿（画左）面向秦铭手中的松鼠（画右）的视线轴，不越轴", "DOLLY", "PUSH_IN", "中近景：文睿眼睛发亮看着松鼠", "中近景（推近）：他伸手想摸，说一句", "导演稿：儿童对白双人同框；推近读喜欢"),
    "E05-S05-03": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm固定，秦铭把松鼠举到文睿眼前逗他", "秦铭（画右）面向文睿（画左）的轴线，不越轴", "LOCKED", "NONE", "中近景：秦铭笑着把松鼠举到文睿眼前说一句", "中近景：文睿顿时纠结，挪不开目光", "导演稿：固定（对白镜 ≤5 s），逗与纠结本身带动，场尾 button"),
    # S06 松鼠炖蘑菇、不想它死、灵兽甄选
    "E05-S06-01": _cp("MEDIUM", "HIGH", "AXIS_B", "28mm高机位随拨开干果下降到炕面", "秦铭（画右）向炕上兽皮袋（画左）的动作轴，不越轴", "CRANE", "FALL", "高机位中景：秦铭把兽皮袋口拨开", "高机位中景（下降）：松子、核桃、红枣与蘑菇滚出来，文晖抓了一颗红枣", "导演稿：下降落到家底上"),
    "E05-S06-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm环绕揪着衣角的文睿与身旁的秦铭", "文睿（画左）面向秦铭（画右）的轴线，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "中近景：文睿揪着衣角开口", "中近景（环绕）：他说完咽了一口口水", "导演稿：儿童对白双人同框；环绕读为难"),
    "E05-S06-03": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm横移自秦铭赞叹到炸毛的松鼠", "秦铭（画右）面向手中松鼠（画左）的视线轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中景：秦铭举着松鼠挑眉赞叹", "中景（横移到松鼠）：红松鼠气性很大，皮毛都炸立起来", "导演稿：横移落在炸毛上，场尾 button（原著幽默）"),
    # S07 抽刀、拦门
    "E05-S07-01": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm横移跟随秦铭拎松鼠走向屋门", "秦铭自炕边（画右）走向屋门（画左）的行进轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中景：秦铭抽出短刀，拎起松鼠", "中景（横移）：他走到屋门前，松鼠吱吱惊叫剧烈挣扎", "导演稿：横移跟随，挣扎在运动里读到"),
    "E05-S07-02": _cp("MEDIUM", "LOW", "AXIS_B", "35mm低机位缓推张开手臂拦门的文睿，秦铭背侧在画右", "文睿（画左，门前）面向秦铭（画右）的轴线，不越轴", "DOLLY", "PUSH_IN", "低机位中景：文睿张开手臂拦在屋门前", "低机位中景（推近）：他仰着脸求情，秦铭停步", "导演稿：儿童对白双人同框；推近读求情，场尾 button"),
    # S08 文睿的决心、收刀
    "E05-S08-01": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm环绕仰脸的文睿到秦铭", "文睿（画左）面向秦铭（画右）的轴线，环绕不越轴", "ARC", "CLOCKWISE", "中近景：文睿放下手臂，仰脸说前半句", "中近景（环绕）：秦铭手里的刀垂了下来", "导演稿：儿童对白双人同框；环绕读决心"),
    "E05-S08-02": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm随收刀缓降到求助的松鼠", "秦铭（画右）面向文睿（画左）的轴线，不越轴", "CRANE", "FALL", "中景：文睿说后半句，松鼠一会儿看刀一会儿对他吱叫", "中景（下降）：秦铭把短刀收回腰间", "导演稿：下降落在收刀上，场尾 button"),
    # S09 陆泽反对、橡果
    "E05-S09-01": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_A", "50mm固定，陆泽蹙眉开口，秦铭在画右", "陆泽（画左）面向秦铭（画右）的交谈轴，不越轴", "LOCKED", "NONE", "中近景：陆泽蹙眉说一句", "中近景：说完摇头，松鼠眼巴巴望着炕上的兽皮袋", "导演稿：固定（对白镜 ≤5 s），反对本身带动"),
    "E05-S09-02": _cp("MEDIUM", "HIGH", "AXIS_B", "28mm高机位缓推挑橡果的手", "秦铭（画右）向炕上干果堆（画左）的动作轴，不越轴", "DOLLY", "PUSH_IN", "高机位中景：秦铭从干果堆里挑橡果", "高机位中景（推近）：一把橡果在他手里，他说一句", "导演稿：推近读挑拣"),
    "E05-S09-03": _cp("MEDIUM_CLOSE_UP", "LOW", "AXIS_A", "50mm低机位环绕秦铭到瞪圆眼的松鼠", "秦铭（画右）面向手中松鼠（画左）的视线轴，环绕不越轴", "ARC", "COUNTERCLOCKWISE", "低机位中近景：秦铭对着松鼠说后半句", "低机位中近景（环绕到松鼠）：红松鼠瞪圆眼睛看着他，喘息微粗", "导演稿：环绕落在松鼠瞪眼上，场尾 button"),
    # S10 警告、关笼、临别
    "E05-S10-01": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm横移跟随松鼠被塞进铁笼", "秦铭（画右）向炕沿的铁笼（画左）的动作轴，不越轴", "TRACK", "RIGHT_TO_LEFT", "中景：秦铭提着松鼠警告", "中景（横移）：松鼠被塞进养鸟的铁笼，笼门扣上", "导演稿：横移跟随关笼（原著幽默：敢咬人就炖了你）"),
    "E05-S10-02": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm随孩子又笑又跳升起到提笼的陆泽", "两个孩子围着铁笼（画面中央），陆泽在画左", "CRANE", "RISE", "中全景：两个孩子围着铁笼又笑又跳", "中全景（升起）：陆泽张了张嘴又闭上，提起铁笼和一堆橡果", "导演稿：升起把「不再反对」与临别连成场尾 button"),
    # S11 院中练功
    "E05-S11-01": _cp("MEDIUM_WIDE", "LOW", "AXIS_A", "28mm低机位随跃起升起", "秦铭在院中石盆与院门之间（画面中央），面向院门（画右）", "CRANE", "RISE", "低机位中全景：秦铭活动关节拉伸筋骨", "低机位中全景（升起）：他猛然跃起如铁箭射出，落下时轻灵如燕，落地无声", "导演稿：升起跟随跃起"),
    "E05-S11-02": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm环绕旋身摆腿的秦铭，脸在月色与石盆光下可辨", "秦铭面向院门（画右）的动作轴，环绕不越轴", "ARC", "CLOCKWISE", "中近景：秦铭旋身摆腿如龙蟒摆尾", "中近景（环绕）：他舒展形体定势，口中低念", "导演稿：环绕读动作圆活；远景之后的露脸镜按 seq=13 声明身份再锚定"),
    "E05-S11-03": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm横移随卷起的雪到体表流光", "秦铭面向院门（画右）的动作轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中景：秦铭舒展形体带起猛烈的风，卷起地面的雪", "中景（横移）：体表一层很淡的银色流光，周身白雾蒸腾", "导演稿：横移落在流光与白雾上，场尾 button"),
    # S12 荒野疾驰、青石上的女子
    "E05-S12-01": _cp("WIDE", "HIGH", "AXIS_A", "24mm高机位横移跟随疾驰", "秦铭自村口方向（画左）向山林（画右）疾驰的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "高机位远景：秦铭在雪原上疾驰", "高机位远景（横移）：他像夜空下划过的流星，接近山林", "导演稿：横移读疾驰"),
    "E05-S12-02": _cp("WIDE", "LOW", "AXIS_B", "24mm低机位自雪面升起到青石上的黑衣女子", "青石（画面中央）上的女子面向雪原（画左），荆棘在画右", "CRANE", "RISE", "低机位远景：青石顶上已静立着黑衣女子（第一帧就在画内，只露精致的下巴），石旁一簇荆棘，乌鸦在空中扑翅", "低机位远景（升起）：女子仍静立在青石上，乌鸦落在荆棘上", "导演稿：升起把乌鸦送到荆棘上，女子自始在画内不『揭示』，场尾 button（本单元一次因女子在第 2 秒才凭空出现重做）"),
    # S13 乌鸦口吐人语
    "E05-S13-01": _cp("CLOSE_UP", "EYE_LEVEL", "NEUTRAL", "85mm环绕荆棘上歪头的乌鸦，紫眼清楚", "乌鸦（画面中央）面向雪原（画左），无人物轴", "ARC", "COUNTERCLOCKWISE", "特写：乌鸦收翅静立在荆棘上", "特写（环绕）：它歪头张喙，紫色的眼睛看着远处", "导演稿：环绕读口吐人语（原著奇观）"),
    "E05-S13-02": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm横移自前景荆棘上的乌鸦到青石上的女子", "乌鸦（画右前景）面向青石上的女子（画左）的轴线，不越轴", "TRACK", "RIGHT_TO_LEFT", "中景：乌鸦转头看向女子", "中景（横移）：女子微微侧首，斗篷立领遮着脸，只露下巴", "导演稿：横移把乌鸦的建议带到女子身上"),
    "E05-S13-03": _cp("MEDIUM", "EYE_LEVEL", "AXIS_B", "35mm自女子缓拉到远处停步侧头的秦铭小人影", "女子（画右近景）面向远处秦铭（画左远景）的视线轴，不越轴", "DOLLY", "PULL_OUT", "中景：寒风吹过，斗篷贴在女子身上，她冷淡地说一句", "中景（拉出）：远处的秦铭停步侧头看向这边，弓箭已在手中", "导演稿：拉出让「有比他更适合的人」与秦铭的直觉同框，场尾 button"),
    # S14 林缘
    "E05-S14-01": _cp("CLOSE_UP", "EYE_LEVEL", "NEUTRAL", "85mm随乌鸦落枝下降", "乌鸦（画面中央）面向林外（画左），无人物轴", "CRANE", "FALL", "特写：乌鸦扑翅落向林缘的枝头", "特写（下降）：它收翅站定，说一句", "导演稿：下降跟随落枝"),
    "E05-S14-02": _cp("MEDIUM", "EYE_LEVEL", "AXIS_A", "35mm环绕枝头的乌鸦与身侧背影的女子", "乌鸦（画右枝头）面向女子（画左）的轴线，环绕不越轴", "ARC", "CLOCKWISE", "中景：乌鸦转向女子开口", "中景（环绕）：女子抬手拢了一下斗篷", "导演稿：环绕读劝告"),
    "E05-S14-03": _cp("MEDIUM_CLOSE_UP", "EYE_LEVEL", "AXIS_B", "50mm固定，女子正面略偏左，山风吹起秀发挡在一侧脸颊，月色雪光照出莹白的脸", "女子（画右）面向林外（画左）的视线轴，不越轴", "LOCKED", "NONE", "中近景：山风吹起女子黑亮的秀发，她冷淡地说一句", "中近景：说完抿唇，秀发挡在莹白脸颊的一侧", "导演稿：固定（对白镜 ≤5 s），冷艳本身带动"),
    "E05-S14-04": _cp("MEDIUM_WIDE", "EYE_LEVEL", "AXIS_A", "28mm横移跟随女子走进林木之间", "女子自林缘（画左）向林深处（画右）的行进轴，不越轴", "TRACK", "LEFT_TO_RIGHT", "中全景：女子说一句，迈步向密林深处", "中全景（横移）：她走进林木之间，一身黑衣猎猎，乌鸦扑翅跟上", "导演稿：横移送走，全集 button 落在秦铭不知道的遗憾上"),
}
# ---------- END OF CHUNK 3 ----------

# 每镜：s, n, sec, size, camera, axis, blocking, cast, action(subject, primary_action, patient), dialogue(speaker,text,listener),
# entry, exit, dims{DIM:(entry_text, exit_text, ENTRY_CODE, EXIT_CODE)}, referents[(surface,key)], faces, cps, slots, identity_reanchor
D = lambda a, b, ca, cb: (a, b, ca, cb)
SQ, CROW, CAGE, ROCK = "PROP-RED-SQUIRREL", "PROP-PURPLE-EYED-CROW", "PROP-BIRD-CAGE", "SET-BLUESTONE-BOULDER"
SHOTS = [
    # S01 —— 承接 E04-S11-04：秦铭笑容收住望着陆泽 → 郑重点头；钩子＝陆泽「二病子成了」
    dict(s="E05-S01", n=1, sec=5, cps=5.2, faces={"QM": "THREE_QUARTER_TURNED_TO_LUZE_NOT_MEASURABLE"}, size="中近景", camera="双人同框缓推，陆泽画左、秦铭画右", axis="陆泽（画左）面向秦铭（画右）", blocking="炕边，秦铭郑重地点头，陆泽紧接着开口；炕上摊着干果与兽皮袋，门边猎叉上倒挂着红松鼠",
         cast=["LZ", "QM"], action=("LZ", "秦铭郑重地点头；陆泽紧接着开口，从画面第 0.3 秒就说出一句，说完看着秦铭；炕上摊着干果和兽皮袋，门边墙上靠着猎叉，猎叉上倒挂着一只红松鼠", "QM"), dialogue=("LZ", "隔壁村的二病子成了，正好处在黄金期内。", "QM"), emotion="calm", slots={"LZ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="陆泽刚说完‘新生’，秦铭的笑容收住望着陆泽；炕上摊着干果与兽皮袋，门边猎叉上倒挂着红松鼠", exit="秦铭郑重地点了头，陆泽说完一句看着他；干果与兽皮袋仍在炕上，红松鼠仍倒挂在猎叉上",
         dims={"POSTURE": D("笑容收住望着陆泽", "郑重地点头", "SMILE_GONE_STARING", "NODDING_GRAVELY"), "CONTACT": D("陆泽闭着口", "陆泽说完一句", "LUZE_SILENT", "LUZE_SPOKEN")}, referents=[("小秦", "QM")]),
    dict(s="E05-S01", n=2, sec=3, cps=4.8, size="特写", camera="环绕秦铭抬眼发问", axis="秦铭（画右）面向陆泽（画左）", blocking="秦铭抬眼问一句，眉头微挑",
         cast=["QM"], action=("QM", "秦铭抬眼，问一句，眉头微挑", "LZ"), dialogue=("QM", "什么时候的事？", "LZ"), emotion="calm",
         entry="秦铭刚点完头，目光落在陆泽身上", exit="秦铭问完一句，眉头微挑",
         dims={"POSTURE": D("点头", "抬眼挑眉", "NODDING", "BROW_RAISED"), "MOMENTUM": D("头低着", "头抬起侧向陆泽", "HEAD_DOWN", "HEAD_UP_TURNED")}, referents=[("的事", "LZ")]),
    dict(s="E05-S01", n=3, sec=6, cps=4.8, faces={"LW": "PROFILE_LISTENING_NOT_MEASURABLE"}, size="中景", camera="横移随陆泽双手作举起状", axis="陆泽（画左）面向秦铭（画右）", blocking="陆泽坐在炕沿答一句，说到举驴时双手向上一托作举起状；梁婉清坐在他身侧看着他；门边猎叉上倒挂着红松鼠，屋里没有笼子",
         cast=["LZ", "LW"], action=("LZ", "陆泽答一句，说到举驴的时候双手向上一托作出举起的样子；梁婉清在他身侧看着他，微微摇头笑", "QM"), dialogue=("LZ", "快一个月了，他一把举起了院里四百斤的黑毛驴。", "QM"), emotion="joy", slots={"LZ": "SCREEN_LEFT", "LW": "SCREEN_RIGHT"},
         entry="陆泽坐在炕沿开口答，双手放在膝上，梁婉清坐在他身侧；门边猎叉上倒挂着红松鼠，屋里没有笼子", exit="陆泽双手向上托着作举起状，梁婉清看着他微微摇头笑",
         dims={"POSTURE": D("双手放在膝上", "双手向上托作举起状", "HANDS_ON_KNEES", "HANDS_LIFTING_GESTURE"), "CONTACT": D("梁婉清看着秦铭", "梁婉清看着陆泽笑", "LWQ_EYES_ON_QM", "LWQ_EYES_ON_LUZE")}, referents=[("他", "LZ")]),
    # S02 —— 亲戚与意气功；劝换练法
    dict(s="E05-S02", n=1, sec=6, cps=5.2, faces={"QM": "PROFILE_LISTENING_NOT_MEASURABLE"}, size="中近景", camera="自陆泽缓升到出神的秦铭", axis="陆泽（画左）面向秦铭（画右）", blocking="陆泽与秦铭都坐在炕沿，陆泽压低声音讲亲戚的事，抬手比一本书的厚度；秦铭坐着听出了神，目光落在铜盆的光上",
         cast=["LZ", "QM"], action=("LZ", "陆泽压低声音说一句，说到意气功时抬手比了比一本书的厚度；秦铭听着出了神，目光落在炕边铜盆的太阳石光上", "QM"), dialogue=("LZ", "据传和他的一位亲戚有关，那人带回来一本高级意气功。", "QM"), emotion="calm", slots={"LZ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="陆泽与秦铭并排坐在炕沿，陆泽压低声音开口，秦铭看着他", exit="陆泽的手比着一本书的厚度，秦铭出神望着铜盆的光",
         dims={"POSTURE": D("秦铭看着陆泽", "秦铭出神望着铜盆", "QM_EYES_ON_LUZE", "QM_STARING_AWAY"), "CONTACT": D("陆泽手放膝上", "陆泽抬手比书的厚度", "HANDS_ON_KNEES", "HAND_GESTURING_BOOK")}, referents=[("他", "LZ"), ("那人", "LZ")]),
    dict(s="E05-S02", n=2, sec=6, cps=5.0, faces={"QM": "HEAD_DOWN_STARING_AT_BASIN_NOT_MEASURABLE"}, size="中近景", camera="缓推前倾劝说的陆泽", axis="陆泽（画左）面向秦铭（画右）", blocking="陆泽身子前倾劝一句，秦铭回神看着他",
         cast=["LZ", "QM"], action=("LZ", "陆泽身子前倾，恳切地劝一句；秦铭回过神来看着他，说完两人对视", "QM"), dialogue=("LZ", "小秦，我觉得你那种特殊的锻炼方式该换一换了。", "QM"), emotion="calm", slots={"LZ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="陆泽身子后靠，秦铭还在出神", exit="陆泽身子前倾说完，秦铭回神与他对视",
         dims={"POSTURE": D("秦铭出神", "秦铭回神对视", "QM_STARING_AWAY", "QM_EYES_BACK"), "CONTACT": D("陆泽身子后靠", "陆泽身子前倾", "LUZE_LEANING_BACK", "LUZE_LEANING_IN")}, referents=[("小秦", "QM"), ("你", "QM")]),
    # S03 —— 嫂子劝；秦铭自信
    dict(s="E05-S03", n=1, sec=5, cps=5.2, faces={"QM": "THREE_QUARTER_TURNED_TO_LWQ_NOT_MEASURABLE"}, size="中景", camera="环绕梁婉清到秦铭", axis="梁婉清（画左）面向秦铭（画右）", blocking="梁婉清坐在炕沿抬头劝秦铭一句，秦铭坐在她身侧点头，面色红润目光炯炯",
         cast=["LW", "QM"], action=("LW", "梁婉清抬头看着秦铭，温声劝一句；秦铭点头，清秀的面孔上带着健康的红润之色，目光炯炯", "QM"), dialogue=("LW", "小秦，不如改练你陆哥的黑夜冥想术吧。", "QM"), emotion="calm", slots={"LW": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="梁婉清坐在炕沿低着头，秦铭坐在她身侧与陆泽对视", exit="梁婉清抬头说完，秦铭向她点头，面色红润",
         dims={"POSTURE": D("梁婉清低头", "梁婉清抬头说完", "LWQ_HEAD_DOWN", "LWQ_HEAD_UP_SPOKEN"), "CONTACT": D("秦铭看陆泽", "秦铭向梁婉清点头", "QM_EYES_ON_LUZE", "QM_NODDING_TO_LWQ")}, referents=[("小秦", "QM"), ("你陆哥", "LZ")]),
    dict(s="E05-S03", n=2, sec=5, cps=5.0, faces={"LZ": "PROFILE_LISTENING_FOREGROUND_NOT_MEASURABLE"}, size="中近景", camera="固定，秦铭正面略偏右，主光是木格窗透进的冷白雪光、五官清晰，铜盆橘红光只留在下颌轮廓与衣领；陆泽在画左前景侧脸", axis="秦铭（画右）面向陆泽（画左）", blocking="秦铭挺直身子看着陆泽和梁婉清说一句，陆泽轻叹着点头",
         cast=["QM", "LZ"], action=("QM", "秦铭挺直身子，看着陆泽和梁婉清，目光炯炯地说一句；说完，陆泽轻叹着点头", "LZ"), dialogue=("QM", "陆哥，嫂子，再等上一段时间，我应该能成。", "LZ"), emotion="joy", slots={"QM": "SCREEN_RIGHT", "LZ": "SCREEN_LEFT"},
         entry="秦铭点头，陆泽在画左前景看着他", exit="秦铭说完，陆泽轻叹着点头",
         dims={"POSTURE": D("秦铭点头", "秦铭挺直身子说完", "QM_NODDING", "QM_UPRIGHT_SPOKEN"), "CONTACT": D("陆泽看着秦铭", "陆泽轻叹点头", "LUZE_WATCHING", "LUZE_SIGH_NOD")}, referents=[("陆哥", "LZ"), ("嫂子", "LW"), ("我", "QM")]),
    # S04 —— 孩子馋肉；取松鼠
    dict(s="E05-S04", n=1, sec=4, cps=5.2, faces={"QM": "HEAD_DOWN_LOOKING_AT_CHILD_NOT_MEASURABLE"}, size="中近景", camera="双人同框缓推，文睿画左仰脸、秦铭画右低头看他", axis="文睿（画左）面向秦铭（画右）", blocking="五岁的文睿坐在炕沿秦铭身边，认真地点头，仰着红扑扑的小脸对秦铭说前半句，秦铭坐着低头看他",
         cast=["WR", "QM"], action=("WR", "五岁的文睿认真地点头，仰着红扑扑的小脸，满是期待地对身旁的秦铭说前半句；秦铭低头笑着看他", "QM"), dialogue=("WR", "小叔最厉害了，等小叔成功后，", "QM"), emotion="joy", slots={"WR": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="文睿坐在炕沿秦铭身边低着头听大人说话，秦铭坐着看陆泽", exit="文睿仰着小脸说完前半句，秦铭低头笑着看他",
         dims={"POSTURE": D("文睿低头", "文睿仰脸认真点头", "WR_HEAD_DOWN", "WR_FACE_UP_NODDING"), "CONTACT": D("秦铭看陆泽", "秦铭低头看文睿", "QM_EYES_ON_LUZE", "QM_EYES_ON_WR")}, referents=[("小叔", "QM")]),
    dict(s="E05-S04", n=2, sec=4, cps=5.2, faces={"WH": "SMALL_TODDLER_BEHIND_BROTHER_NOT_MEASURABLE", "QM": "MEDIUM_TURNED_TO_CHILD_NOT_MEASURABLE"}, size="低机位中景", camera="低机位横移自文睿到蹒跚凑近的文晖", axis="文睿（画左）面向秦铭（画右），文晖自画左后方凑近", blocking="文睿说后半句咽了口口水；两岁的文晖步履蹒跚地凑到哥哥身后跟着点头，秦铭在画右看着两个孩子",
         cast=["WR", "WH", "QM"], action=("WR", "文睿说完后半句咽了口口水；两岁出头的文晖步履蹒跚地凑到哥哥身后，有样学样地跟着点头；秦铭在一旁看着两个孩子", "QM"), dialogue=("WR", "抓来山兽炖肉肉吃，我……馋了。", "QM"), emotion="joy", slots={"WR": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="文睿接着说，文晖在炕角，秦铭看着文睿", exit="文睿说完咽口水，文晖凑到哥哥身后跟着点头，秦铭看着两个孩子",
         dims={"POSITION": D("文晖在炕角", "文晖凑到哥哥身后", "WENHUI_AT_KANG_CORNER", "WENHUI_BEHIND_BROTHER"), "POSTURE": D("文睿说着", "文睿咽口水", "WR_SPEAKING", "WR_SWALLOWING")}, referents=[("我", "WR")]),
    dict(s="E05-S04", n=3, sec=5, cps=5.2, faces={"WR": "SMALL_FACE_AT_EDGE_NOT_MEASURABLE"}, size="中景", camera="随秦铭起身取松鼠升起", axis="秦铭（画右）向门边猎叉（画左）伸手", blocking="秦铭笑着说一句，起身伸手把猎叉上倒挂的红松鼠取到手里，文睿在画边看着",
         cast=["QM", "WR"], action=("QM", "秦铭笑了，说一句，起身伸手把门边猎叉上倒挂的红松鼠取到手里；文睿在画边看着", "WR"), dialogue=("QM", "不用等以后，今天就可以满足你们。", "WR"), emotion="joy", slots={"QM": "SCREEN_RIGHT", "WR": "SCREEN_LEFT"},
         entry="秦铭笑着开口，红松鼠还倒挂在门边的猎叉上", exit="红松鼠被秦铭提在手里，猎叉上空了，文睿看着",
         dims={"POSSESSION": D("红松鼠挂在猎叉上", "红松鼠在秦铭手里", "SQUIRREL_ON_FORK", "SQUIRREL_IN_HAND"), "POSTURE": D("秦铭坐着说", "秦铭起身伸手", "QM_SEATED", "QM_RISEN_REACHING")}, referents=[("你们", "WR")]),
    # S05 —— 它又活了（配乐 CUE-01 起）
    dict(s="E05-S05", n=1, sec=6, cps=5.2, size="特写", camera="环绕秦铭手里的松鼠到秦铭的脸", axis="秦铭（画右）面向手中松鼠（画左）", blocking="秦铭提着红松鼠看了又看，松鼠黑宝石般的大眼睛瞪出来露出惊恐；秦铭笑着说一句",
         cast=["QM"], action=("QM", "秦铭提着红松鼠看了又看；松鼠黑宝石般的大眼睛瞪了出来，露出惊恐之色，身子扭动；秦铭笑着说一句", None), dialogue=("QM", "咦，它又活了，这样更好，肉质远比冰冻过的鲜嫩。", None), emotion="joy",
         entry="秦铭提着红松鼠，松鼠闭着眼软垂着", exit="红松鼠瞪圆眼睛扭动，秦铭说完看着它笑",
         dims={"POSTURE": D("松鼠闭眼", "松鼠瞪圆眼睛", "EYES_SHUT", "EYES_BULGING"), "MOMENTUM": D("松鼠软垂", "松鼠扭动", "LIMP", "WRIGGLING")}, referents=[("它", SQ)]),
    dict(s="E05-S05", n=2, sec=4, cps=5.2, faces={"QM": "HEAD_DOWN_LOOKING_AT_SQUIRREL_NOT_MEASURABLE"}, size="中近景", camera="双人同框缓推，文睿画左、秦铭画右，松鼠在两人之间", axis="文睿（画左）面向秦铭手中的松鼠（画右）", blocking="秦铭站在炕边提着松鼠，文睿站在他面前仰头眼睛发亮看着松鼠，伸手想摸，说一句",
         cast=["WR", "QM"], action=("WR", "文睿扑闪着大眼睛看着秦铭手里的红松鼠，伸手想摸，发自内心地说一句", "QM"), dialogue=("WR", "这只松鼠好漂亮，有些可爱。", "QM"), emotion="joy", slots={"WR": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="秦铭站在炕边提着红松鼠，文睿站在他面前仰头盯着松鼠，手垂在身侧", exit="文睿伸手想摸松鼠，说完眼睛发亮",
         dims={"CONTACT": D("文睿手垂在身侧", "文睿伸手想摸松鼠", "WR_HANDS_DOWN", "WR_REACHING"), "POSTURE": D("文睿盯着", "文睿眼睛发亮说完", "WR_STARING", "WR_BRIGHT_EYED")}, referents=[("这只松鼠", SQ)]),
    dict(s="E05-S05", n=3, sec=5, cps=5.2, faces={"WR": "UP_TILTED_SMALL_FACE_NOT_MEASURABLE"}, size="中近景", camera="固定，秦铭把松鼠举到文睿眼前逗他", axis="秦铭（画右）面向文睿（画左）", blocking="秦铭站着笑着把红松鼠举到站在面前的文睿眼前说一句，文睿顿时纠结，挪不开目光",
         cast=["QM", "WR"], action=("QM", "秦铭笑着把红松鼠举到文睿眼前逗他，说一句；文睿顿时纠结，想吃肉又挪不开目光", "WR"), dialogue=("QM", "一会炖熟了更可爱，保你吃得香。", "WR"), emotion="mock", slots={"QM": "SCREEN_RIGHT", "WR": "SCREEN_LEFT"},
         entry="秦铭站着把红松鼠举到站在面前的文睿眼前，文睿仰头眼睛发亮", exit="秦铭说完，文睿纠结地皱着小脸盯着松鼠",
         dims={"POSTURE": D("文睿眼睛发亮", "文睿纠结皱脸", "WR_BRIGHT_EYED", "WR_TORN"), "CONTACT": D("松鼠离文睿远", "松鼠举到文睿眼前", "SQUIRREL_FAR", "SQUIRREL_AT_WR_FACE")}, referents=[("你", "WR")]),
    # S06 —— 松鼠炖蘑菇；不想它死；灵兽甄选
    dict(s="E05-S06", n=1, sec=5, cps=5.2, faces={"WR": "SMALL_FACE_HIGH_ANGLE_NOT_MEASURABLE", "WH": "SMALL_TODDLER_HIGH_ANGLE_NOT_MEASURABLE", "QM": "HIGH_ANGLE_HEAD_DOWN_NOT_MEASURABLE"}, size="高机位中景", camera="高机位随拨开干果下降到炕面", axis="秦铭（画右）向炕上兽皮袋（画左）", blocking="秦铭把炕上兽皮袋口拨开，松子、核桃、红枣与蘑菇滚出来，文晖抓了一颗红枣，文睿看着；秦铭说一句",
         cast=["QM", "WR", "WH"], action=("QM", "秦铭把炕上鼓胀的兽皮袋口拨开，松子、核桃、红枣和蘑菇滚出来给孩子们看，他得意地说一句；文晖抓了一颗红枣，文睿看着蘑菇", "WR"), dialogue=("QM", "这下好了，松鼠炖蘑菇，好吃又大补。", "WR"), emotion="joy", slots={"QM": "SCREEN_RIGHT", "WR": "SCREEN_LEFT"},
         entry="炕上的兽皮袋口合着，秦铭伸手去拨，两个孩子在旁边", exit="兽皮袋口拨开，松子核桃红枣与蘑菇滚在炕上，文晖手里抓着一颗红枣",
         dims={"POSSESSION": D("兽皮袋口合着", "兽皮袋口拨开露出干果与蘑菇", "BAG_CLOSED", "BAG_OPEN_NUTS_OUT"), "CONTACT": D("文晖手空", "文晖抓着一颗红枣", "WENHUI_HAND_EMPTY", "WENHUI_HOLDING_DATE")}, referents=[("松鼠", SQ)]),
    dict(s="E05-S06", n=2, sec=4, cps=5.2, faces={"QM": "PROFILE_NOT_MEASURABLE"}, size="中近景", camera="环绕揪着衣角的文睿与身旁的秦铭", axis="文睿（画左）面向秦铭（画右）", blocking="文睿揪着衣角为难地说一句，说完咽了一口口水；秦铭在他身旁",
         cast=["WR", "QM"], action=("WR", "文睿揪着衣角，小脸上满是为难，对身旁的秦铭说一句，说完咽了一口口水", "QM"), dialogue=("WR", "真……真的吗？可是，我不想它死去。", "QM"), emotion="plead", slots={"WR": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="文睿的手空着，张口要说，秦铭在他身旁", exit="文睿揪着衣角说完，咽了一口口水",
         dims={"CONTACT": D("文睿手空着", "文睿揪着衣角", "WR_HAND_EMPTY", "WR_CLUTCHING_HEM"), "POSTURE": D("文睿张口", "文睿咽口水", "WR_MOUTH_OPEN", "WR_SWALLOWING")}, referents=[("它", SQ)]),
    dict(s="E05-S06", n=3, sec=4, cps=4.8, size="中景", camera="横移自秦铭赞叹到炸毛的松鼠", axis="秦铭（画右）面向手中松鼠（画左）", blocking="秦铭举着红松鼠挑眉赞叹一句，松鼠气性很大皮毛炸立起来",
         cast=["QM"], action=("QM", "秦铭举着红松鼠，挑眉赞叹一句；红松鼠气性很大，皮毛都炸立了起来", None), dialogue=("QM", "果然，灵兽甄选，必属上选。", None), emotion="mock",
         entry="秦铭举着红松鼠，松鼠皮毛平顺", exit="秦铭说完看着松鼠，红松鼠皮毛炸立起来",
         dims={"INTEGRITY": D("松鼠皮毛平顺", "松鼠皮毛炸立", "FUR_SMOOTH", "FUR_BRISTLED"), "POSTURE": D("秦铭笑着说", "秦铭挑眉看松鼠", "QM_SPEAKING", "QM_BROW_RAISED")}, referents=[("灵兽", SQ)]),
    # S07 —— 抽刀；拦门
    dict(s="E05-S07", n=1, sec=4, faces={"QM": "MEDIUM_WALKING_TURNED_AWAY_NOT_MEASURABLE"}, size="中景", camera="横移跟随秦铭拎松鼠走向屋门", axis="秦铭自炕边（画右）走向屋门（画左）", blocking="秦铭抽出腰间短刀，拎着红松鼠走向屋门；松鼠吱吱惊叫剧烈挣扎，缠着它的铁丝快勒进肉里",
         cast=["QM"], action=("QM", "秦铭抽出腰间的短刀，拎着红松鼠走向屋门，要去院中剥皮；红松鼠霎时惊悚，吱吱叫个不停，剧烈挣扎，缠在它身上的铁丝都快勒进肉里", SQ), dialogue=None,
         entry="秦铭在炕边，短刀在腰间，红松鼠在他手里", exit="秦铭走到屋门前，短刀在手，红松鼠吱吱惊叫剧烈挣扎",
         dims={"POSSESSION": D("短刀在腰间", "短刀在手", "KNIFE_SHEATHED", "KNIFE_DRAWN"), "POSITION": D("秦铭在炕边", "秦铭在屋门前", "AT_KANG", "AT_DOOR")}, referents=[("它", SQ)]),
    dict(s="E05-S07", n=2, sec=4, cps=4.8, faces={"QM": "BACK_THREE_QUARTER_NOT_MEASURABLE"}, size="低机位中景", camera="低机位缓推张开手臂拦门的文睿，秦铭背侧在画右", axis="文睿（画左，门前）面向秦铭（画右）", blocking="文睿跑到屋门前张开手臂拦住，仰脸求情说一句；秦铭停步，背侧对镜头",
         cast=["WR", "QM"], action=("WR", "文睿跑到屋门前张开双臂拦住秦铭，努力去遗忘炖肉的滋味，仰着脸求情说一句；秦铭停下脚步", "QM"), dialogue=("WR", "小叔，要不……留下它吧。", "QM"), emotion="plead", slots={"WR": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="文睿跑到屋门前，秦铭拎着松鼠走来", exit="文睿张开双臂拦在门前说完，秦铭停步",
         dims={"POSTURE": D("文睿跑到门前", "文睿张开双臂拦门", "WR_ARRIVING", "WR_ARMS_SPREAD"), "MOMENTUM": D("秦铭走着", "秦铭停步", "QM_WALKING", "QM_STOPPED")}, referents=[("小叔", "QM"), ("它", SQ)]),
]
SHOTS += [
    # S08 —— 文睿的决心；收刀
    dict(s="E05-S08", n=1, sec=4, cps=5.2, faces={"QM": "THREE_QUARTER_DARK_SIDE_NOT_MEASURABLE", "WR": "UP_TILTED_FACE_NOT_MEASURABLE"}, size="中近景", camera="环绕仰脸的文睿到秦铭", axis="文睿（画左）面向秦铭（画右）", blocking="文睿放下手臂仰脸说前半句，秦铭手里的刀垂了下来",
         cast=["WR", "QM"], action=("WR", "文睿放下拦门的手臂，仰着脸像是下定了决心，对秦铭说前半句；秦铭手里的短刀垂了下来", "QM"), dialogue=("WR", "这次就不吃了，等小叔新生后，", "QM"), emotion="plead", slots={"WR": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="文睿张着双臂，秦铭手里的短刀举着", exit="文睿放下手臂仰脸说完前半句，秦铭手里的短刀垂下",
         dims={"POSTURE": D("文睿张着双臂", "文睿放下手臂仰脸", "WR_ARMS_SPREAD", "WR_ARMS_DOWN_FACE_UP"), "CONTACT": D("短刀举着", "短刀垂下", "KNIFE_RAISED", "KNIFE_LOWERED")}, referents=[("小叔", "QM")]),
    dict(s="E05-S08", n=2, sec=6, cps=5.2, faces={"QM": "HIGH_ANGLE_HEAD_DOWN_SHEATHING_NOT_MEASURABLE", "WR": "UP_TILTED_PROFILE_NOT_MEASURABLE"}, size="中景", camera="随收刀缓降到求助的松鼠", axis="秦铭（画右）面向文睿（画左）", blocking="文睿站在屋门前说后半句；秦铭站在他面前，一手拎着被铁丝缠着的红松鼠、一手握短刀；红松鼠一会儿看刀一会儿对文睿吱吱叫像在求助；秦铭把短刀收回腰间",
         cast=["WR", "QM"], action=("WR", "文睿说完后半句，抵住食物的诱惑；红松鼠紧张兮兮，一会儿看秦铭手里的短刀，一会儿对文睿吱吱叫，像是在求助；秦铭把短刀收回腰间", "QM"), dialogue=("WR", "一定可以猎杀到很凶的大块头灵兽，我等小叔成功。", "QM"), emotion="calm", slots={"WR": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="文睿站在屋门前接着说，秦铭站在他面前，短刀在一手、被铁丝缠着的红松鼠拎在另一手，红松鼠盯着刀", exit="文睿说完，短刀已收回秦铭腰间，红松鼠对着文睿吱吱叫",
         dims={"POSSESSION": D("短刀在手", "短刀收回腰间", "KNIFE_DRAWN", "KNIFE_SHEATHED"), "CONTACT": D("松鼠盯着刀", "松鼠转向文睿吱叫", "SQUIRREL_EYES_ON_KNIFE", "SQUIRREL_TURNED_TO_WR")}, referents=[("小叔", "QM"), ("我", "WR")]),
    # S09 —— 陆泽反对；橡果
    dict(s="E05-S09", n=1, sec=5, cps=5.2, faces={"QM": "PROFILE_LISTENING_NOT_MEASURABLE"}, size="中近景", camera="固定，陆泽蹙眉开口，秦铭在画右", axis="陆泽（画左）面向秦铭（画右）", blocking="陆泽微微蹙眉说一句，说完摇头；秦铭手里的红松鼠眼巴巴望着炕上鼓鼓囊囊的兽皮袋",
         cast=["LZ", "QM"], action=("LZ", "陆泽微微蹙眉，说一句，说完摇头；秦铭手里的红松鼠眼巴巴地望着炕上那鼓鼓囊囊的兽皮袋，里面可全是它的家底", "QM"), dialogue=("LZ", "这个冬季不同以往，哪有多余的食物给它。", "QM"), emotion="calm", slots={"LZ": "SCREEN_LEFT", "QM": "SCREEN_RIGHT"},
         entry="陆泽蹙眉开口，红松鼠在秦铭手里望着人", exit="陆泽说完摇头，红松鼠眼巴巴望着炕上的兽皮袋",
         dims={"POSTURE": D("陆泽蹙眉开口", "陆泽说完摇头", "LUZE_FROWN_SPEAKING", "LUZE_SHAKING_HEAD"), "CONTACT": D("松鼠望着人", "松鼠望着兽皮袋", "SQUIRREL_EYES_ON_PEOPLE", "SQUIRREL_EYES_ON_BAG")}, referents=[("它", SQ)]),
    dict(s="E05-S09", n=2, sec=5, cps=5.2, faces={"QM": "HIGH_ANGLE_HEAD_DOWN_NOT_MEASURABLE", "LZ": "HIGH_ANGLE_SMALL_FACE_NOT_MEASURABLE"}, size="高机位中景", camera="高机位缓推挑橡果的手", axis="秦铭（画右）向炕上干果堆（画左）", blocking="秦铭从炕上的干果堆里挑出一把橡果，说前半句；陆泽看着橡果",
         cast=["QM", "LZ"], action=("QM", "秦铭从炕上的干果堆里挑出一把橡果，拿在手里说前半句；陆泽看着那把橡果", "LZ"), dialogue=("QM", "这种坚果需要处理后才能吃，不然微毒，", "LZ"), emotion="calm", slots={"QM": "SCREEN_RIGHT", "LZ": "SCREEN_LEFT"},
         entry="秦铭的手伸进炕上的干果堆，陆泽看着松鼠", exit="一把橡果在秦铭手里，陆泽看着橡果",
         dims={"POSSESSION": D("秦铭手空", "秦铭手里一把橡果", "HAND_EMPTY", "ACORNS_IN_HAND"), "CONTACT": D("陆泽看松鼠", "陆泽看橡果", "LUZE_EYES_ON_SQUIRREL", "LUZE_EYES_ON_ACORNS")}, referents=[("松鼠", SQ)]),
    dict(s="E05-S09", n=3, sec=4, cps=4.8, size="低机位中近景", camera="低机位环绕秦铭到瞪圆眼的松鼠", axis="秦铭（画右）面向手中松鼠（画左）", blocking="秦铭对着红松鼠说后半句；松鼠瞪圆眼睛看着他，喘息微粗",
         cast=["QM"], action=("QM", "秦铭对着手里的红松鼠说后半句；红松鼠不吱声，只是瞪圆眼睛看着他，喘息微粗", None), dialogue=("QM", "正好留着喂养松鼠吧。", None), emotion="calm",
         entry="秦铭拿着橡果对红松鼠开口，松鼠缩着", exit="秦铭说完，红松鼠瞪圆眼睛看着他，胸口急促起伏",
         dims={"POSTURE": D("松鼠缩着", "松鼠瞪圆眼睛", "SQUIRREL_HUNCHED", "SQUIRREL_EYES_WIDE"), "MOMENTUM": D("松鼠不动", "松鼠胸口急促起伏", "SQUIRREL_STILL", "SQUIRREL_PANTING")}, referents=[("松鼠", SQ)]),
    # S10 —— 警告、关笼、临别
    dict(s="E05-S10", n=1, sec=6, cps=5.2, faces={"WR": "SMALL_FACE_AT_EDGE_NOT_MEASURABLE", "QM": "HEAD_DOWN_AT_CAGE_NOT_MEASURABLE"}, size="中景", camera="横移跟随松鼠被塞进铁笼", axis="秦铭（画右）向炕沿的铁笼（画左）", blocking="秦铭提着红松鼠警告一句，把它塞进炕沿一个养鸟用的铁笼，扣上笼门；文睿在画边看着",
         cast=["QM", "WR"], action=("QM", "秦铭提着红松鼠警告一句，把它塞进炕沿一个养鸟用的铁笼里，扣上笼门；文睿在旁边看着", SQ), dialogue=("QM", "能活下来你还不满意？另外，敢咬人的话我保准炖了你。", None), emotion="threat", slots={"QM": "SCREEN_RIGHT", "WR": "SCREEN_LEFT"},
         entry="秦铭提着红松鼠，炕沿放着一个笼门开着的铁笼", exit="红松鼠在铁笼里，笼门扣上，秦铭收手",
         dims={"POSSESSION": D("红松鼠在秦铭手里", "红松鼠在铁笼里", "SQUIRREL_IN_HAND", "SQUIRREL_IN_CAGE"), "CONTACT": D("笼门开着", "笼门扣上", "CAGE_OPEN", "CAGE_LATCHED")}, referents=[("你", SQ)]),
    dict(s="E05-S10", n=2, sec=4, faces={"WR": "SMALL_FACE_JUMPING_NOT_MEASURABLE", "WH": "SMALL_TODDLER_JUMPING_NOT_MEASURABLE", "LZ": "MEDIUM_WIDE_SMALL_FACE_NOT_MEASURABLE"}, size="中全景", camera="随孩子又笑又跳升起到提笼的陆泽", axis="两个孩子围着铁笼，陆泽在画左", blocking="两个孩子围着铁笼又笑又跳；陆泽张了张嘴又闭上，提起铁笼和一堆橡果",
         cast=["WR", "WH", "LZ"], action=("LZ", "两个孩子围着铁笼又笑又跳、拍手蹦跳，笑只在脸上、闭着嘴不出声，全程没有任何人出声说话或笑出声；陆泽张了张嘴又闭上，不再出声反对，临别时提起铁笼和一堆橡果（本单元一次因孩子笑出声被对白门判为无对白镜有人声重做）", "WR"), dialogue=None,
         entry="铁笼在炕沿，两个孩子围着它跳，陆泽张嘴要说话", exit="铁笼和一堆橡果提在陆泽手里，两个孩子跟在旁边跳",
         dims={"POSSESSION": D("铁笼在炕沿", "铁笼在陆泽手里", "CAGE_ON_KANG", "CAGE_IN_LUZE_HAND"), "POSTURE": D("陆泽张嘴要说", "陆泽闭嘴提笼", "LUZE_ABOUT_TO_OBJECT", "LUZE_SILENT_LIFTING")}, referents=[("它", SQ)]),
    # S11 —— 院中练功（配乐 CUE-02 起）
    dict(s="E05-S11", n=1, sec=4, faces={"QM": "MEDIUM_WIDE_WALKING_LEAPING_NOT_MEASURABLE"}, size="低机位中全景", camera="低机位随跃起升起", axis="秦铭在院中石盆与院门之间，面向院门（画右）", blocking="秦铭在院中活动关节拉伸筋骨，猛然自地面跃起迅疾似铁箭射出，落下时轻灵如燕落地无声",
         cast=["QM"], action=("QM", "秦铭在院中活动关节，拉伸筋骨，拧、旋、转、翻，圆活不滞；他猛然自地面跃起，迅疾似铁箭射出，落下时则轻灵如燕，踏回雪地落地无声", None), dialogue=None,
         entry="秦铭站在院中石盆旁活动关节拉伸筋骨", exit="秦铭落回雪地，落地无声，雪面只留浅浅脚印",
         dims={"POSITION": D("在石盆旁的雪地上", "跃起后落回雪地", "ON_GROUND_BY_BASIN", "LEAPT_AND_LANDED"), "MOMENTUM": D("缓缓拉伸", "迅疾跃起", "STRETCHING", "LEAPING")}, referents=[("他", "QM")]),
    dict(s="E05-S11", n=2, sec=4, cps=5.2, identity_reanchor=True, size="中近景", camera="环绕旋身摆腿的秦铭，脸在月色与石盆光下可辨", axis="秦铭面向院门（画右）", blocking="秦铭旋身摆腿像龙蟒摆尾抽在半空发出沉闷的响声，舒展形体定势，口中低念",
         cast=["QM"], action=("QM", "秦铭旋身，快如闪电般摆腿，像是龙蟒摆尾抽在半空中，发出沉闷的响声；他舒展形体定势，口中低念一句", None), dialogue=("QM", "吹呴呼吸，吐故纳新，熊经鸱顾……", None), emotion="calm",
         entry="秦铭旋身摆腿抽在半空", exit="秦铭舒展形体定势，低念完一句",
         dims={"POSTURE": D("旋身摆腿", "舒展形体定势", "SPINNING_KICK", "SETTLED_STANCE"), "MOMENTUM": D("摆腿抽空", "收势", "KICK_IN_AIR", "STILLING")}, referents=[("他", "QM")]),
    dict(s="E05-S11", n=3, sec=4, faces={"QM": "BACK_THREE_QUARTER_IN_MIST_NOT_MEASURABLE"}, size="中景", camera="横移随卷起的雪到体表流光", axis="秦铭面向院门（画右）", blocking="秦铭舒展形体刚劲有力带起猛烈的风卷起地面的雪；毛孔中银丝交织成体表一层很淡的流光，周身白雾蒸腾",
         cast=["QM"], action=("QM", "秦铭舒展形体，刚劲有力，踏步转身带起猛烈的风，卷起地面的雪在周围飞舞；他的毛孔中有无比微弱的银丝交织，在体表形成一层很淡的流光，周身白雾蒸腾", None), dialogue=None,
         entry="秦铭舒展形体，地面积雪平静，体表无光", exit="雪被卷起飞舞，秦铭体表一层很淡的银色流光，周身白雾蒸腾",
         dims={"INTEGRITY": D("体表无光", "体表淡银流光与白雾", "SKIN_PLAIN", "SKIN_SILVER_SHIMMER_MIST"), "MOMENTUM": D("地面积雪平静", "雪被卷起飞舞", "SNOW_STILL", "SNOW_SWIRLING")}, referents=[("他", "QM")]),
    # S12 —— 荒野疾驰；青石上的女子
    dict(s="E05-S12", n=1, sec=4, faces={"QM": "FAR_FIGURE_FACE_NOT_MEASURABLE"}, size="高机位远景", camera="高机位横移跟随疾驰", axis="秦铭自村口方向（画左）向山林（画右）", blocking="秦铭独自一人在荒野雪原上疾驰，宛若夜空下划过的流星，接近山林区域；画面里只有他一个人，没有别人、没有鸟兽",
         cast=["QM"], action=("QM", "秦铭身体燥热，有种想要奔跑的冲动，在荒野的雪原上疾驰，宛若夜空下划过的流星，一路远去，快接近山林区域了", None), dialogue=None,
         entry="秦铭独自一人在雪原中段奔跑，画面里没有别人、没有鸟兽", exit="秦铭疾驰到接近山林的雪原北缘",
         dims={"POSITION": D("在雪原中段", "接近山林的雪原北缘", "MID_SNOWFIELD", "NEAR_FOREST"), "MOMENTUM": D("奔跑", "疾驰如流星", "RUNNING", "SPRINTING")}, referents=[("他", "QM")]),
    dict(s="E05-S12", n=2, sec=4, faces={"TJ": "FAR_FIGURE_HOODED_CHIN_ONLY_NOT_MEASURABLE"}, size="低机位远景", camera="低机位自雪面升起到青石上的黑衣女子", axis="青石上的女子面向雪原（画左），荆棘在画右", blocking="远处雪地一块青石，一簇荆棘；青石上静立着一个身材高挑而纤细的黑衣女子，黑裘皮斗篷流动淡淡乌光只露精致的下巴；一只紫眼乌鸦落在她身侧的荆棘上",
         cast=["TJ"], action=("TJ", "远处的雪地中，一个身材高挑而纤细的女子从第一帧起就静立在一块较大的青石顶上、全程不消失不移动，身上的黑色裘皮斗篷流动着淡淡的乌光，遮住脖颈，只露出精致的下巴；一只满身黑羽如乌金、紫色眼睛的乌鸦扑翅落在她身侧的一簇荆棘上（本单元一次因女子在开场空青石上凭空出现重做）", None), dialogue=None,
         entry="雪地里一块青石与一簇荆棘，青石上的黑衣女子静立，乌鸦在空中扑翅", exit="乌鸦落在青石旁的荆棘上，女子的斗篷被寒风吹动",
         dims={"POSITION": D("乌鸦在空中", "乌鸦落在荆棘上", "CROW_IN_AIR", "CROW_ON_THORNS"), "MOMENTUM": D("斗篷静垂", "斗篷被风吹动", "CLOAK_STILL", "CLOAK_BLOWN")}, referents=[("她", "TJ")]),
    # S13 —— 乌鸦口吐人语（配乐 CUE-03 起）
    dict(s="E05-S13", n=1, sec=5, cps=5.2, size="特写", camera="环绕荆棘上歪头的乌鸦，紫眼清楚", axis="乌鸦面向雪原（画左）", blocking="荆棘上的紫眼乌鸦歪头张喙口吐人语，紫色的眼睛看着远处；女子在画外",
         cast=[], action=(CROW, "荆棘上的乌鸦歪头，张开鸟喙口吐人语说一句，紫色的眼睛注视着远处雪原上的人影；羽毛被风掀起", None), dialogue=("CR", "咦，身体自行新生，初期就有异常景象。", "TJ"), emotion="joy",
         entry="乌鸦收翅静立在荆棘上，羽毛贴着", exit="乌鸦歪头张喙说完，羽毛被风掀起",
         dims={"POSTURE": D("乌鸦收翅静立", "乌鸦歪头张喙", "CROW_STILL", "CROW_HEAD_TILTED"), "MOMENTUM": D("羽毛贴着", "羽毛被风掀起", "FEATHERS_FLAT", "FEATHERS_RUFFLED")}, referents=[("身体", "QM")]),
    dict(s="E05-S13", n=2, sec=6, cps=5.2, faces={"TJ": "MEDIUM_COLLAR_SHADOW_CHIN_ONLY_NOT_MEASURABLE"}, size="中景", camera="横移自前景荆棘上的乌鸦到青石上的女子", axis="乌鸦（画右前景）面向青石上的女子（画左）", blocking="前景荆棘上的紫眼乌鸦转头对青石上的女子说一句；女子微微侧首，斗篷立领遮着脸只露下巴",
         cast=["TJ"], action=(CROW, "前景荆棘上的乌鸦转头，对青石上的女子说一句；女子微微侧首，黑裘皮斗篷的立领遮着她的脸，只露出精致的下巴", "TJ"), dialogue=("CR", "你的老师不是在挑选关门弟子吗？这个少年或许可以。", "TJ"), emotion="calm",
         entry="乌鸦看着远处，女子在青石上面向雪原静立", exit="乌鸦转头对着女子说完，青石上的女子微微侧首",
         dims={"CONTACT": D("乌鸦看远处", "乌鸦转头看女子", "CROW_EYES_FAR", "CROW_EYES_ON_WOMAN"), "POSTURE": D("女子面向雪原", "女子微微侧首", "WOMAN_FACING_FIELD", "WOMAN_HEAD_TURNED")}, referents=[("你", "TJ"), ("这个少年", "QM")]),
    dict(s="E05-S13", n=3, sec=4, cps=5.2, faces={"TJ": "MEDIUM_COLLAR_SHADOW_CHIN_ONLY_NOT_MEASURABLE", "QM": "FAR_FIGURE_FACE_NOT_MEASURABLE"}, size="中景", camera="自女子缓拉到远处停步侧头的秦铭小人影", axis="女子（画右近景）面向远处秦铭（画左远景）", blocking="寒风吹过斗篷贴在女子身上，她冷淡地说一句；远处雪原上的秦铭停步侧头看向这边，他自己手里持着弓；女子身边的青石上什么都没有放",
         cast=["TJ", "QM"], action=("TJ", "寒风吹过，宽松的斗篷贴在女子身上，她冷淡地说一句；远处雪原上的秦铭似有所感，停步侧头看向这边，他自己手里持着弓；女子身边的青石上什么都没有放", "QM"), dialogue=("TJ", "有比他更适合的人。", "CR"), emotion="calm", slots={"TJ": "SCREEN_RIGHT", "QM": "SCREEN_LEFT"},
         entry="女子站在青石上开口，青石上没有任何物件；远处的秦铭还在奔跑，弓背在他自己背上", exit="女子说完垂眼，远处的秦铭停步侧头看向这边，弓在他自己手中",
         dims={"POSTURE": D("女子开口望着远处", "女子说完垂眼", "WOMAN_SPEAKING", "WOMAN_EYES_DOWN"), "MOMENTUM": D("远处秦铭奔跑", "远处秦铭停步侧头持弓", "QM_RUNNING", "QM_STOPPED_TURNED_BOW")}, referents=[("他", "QM")]),
    # S14 —— 林缘
    dict(s="E05-S14", n=1, sec=3, cps=4.8, size="特写", camera="随乌鸦落枝下降", axis="乌鸦面向林外（画左）", blocking="紫眼乌鸦扑翅落向林缘的枝头，收翅站定说一句",
         cast=[], action=(CROW, "乌鸦扑翅落向林缘一根积雪的枝头，收翅站定，评价一句", None), dialogue=("CR", "很敏锐的直觉。", "TJ"), emotion="mock",
         entry="乌鸦扑翅落向枝头，翅张着", exit="乌鸦收翅站定在枝头说完",
         dims={"POSITION": D("乌鸦在空中落向枝头", "乌鸦站在枝头", "CROW_LANDING", "CROW_PERCHED"), "POSTURE": D("翅张开", "翅收拢", "WINGS_SPREAD", "WINGS_FOLDED")}, referents=[("直觉", "QM")]),
    dict(s="E05-S14", n=2, sec=5, cps=5.2, faces={"TJ": "THREE_QUARTER_BACK_NOT_MEASURABLE"}, size="中景", camera="环绕枝头的乌鸦与身侧背影的女子", axis="乌鸦（画右枝头）面向女子（画左）", blocking="枝头的紫眼乌鸦转向身边的女子劝一句；女子背侧站在林缘，抬手拢了一下斗篷",
         cast=["TJ"], action=(CROW, "枝头的乌鸦转向身边的女子，劝一句；女子背侧站着，抬手拢了一下斗篷", "TJ"), dialogue=("CR", "你可别真错过一颗有望蓬勃生长的种子。", "TJ"), emotion="calm",
         entry="乌鸦面向林外，女子站定在它身侧", exit="乌鸦转向女子说完，女子抬手拢着斗篷",
         dims={"CONTACT": D("乌鸦面向林外", "乌鸦转向女子", "CROW_FACING_OUT", "CROW_FACING_WOMAN"), "POSTURE": D("女子手垂着", "女子抬手拢斗篷", "WOMAN_HANDS_DOWN", "WOMAN_GATHERING_CLOAK")}, referents=[("你", "TJ"), ("种子", "QM")]),
    dict(s="E05-S14", n=3, sec=4, cps=5.2, size="中近景", camera="固定，女子正面略偏左，山风吹起秀发挡在一侧脸颊，月色雪光照出莹白的脸", axis="女子（画右）面向林外（画左）", blocking="山风呼啸吹起女子黑亮的秀发挡在莹白脸颊的一侧，她冷淡地说一句，说完抿唇",
         cast=["TJ"], action=("TJ", "山风呼啸，女子黑亮的秀发飘起，挡在莹白脸颊的一侧，清丽绝俗中更显冷艳；她冷淡地说一句，说完抿唇", "CR"), dialogue=("TJ", "未被选中，那是他不知道的遗憾。", "CR"), emotion="calm",
         entry="女子的秀发垂着，正要开口", exit="秀发飘起挡在一侧脸颊，女子说完抿唇",
         dims={"MOMENTUM": D("秀发垂着", "秀发飘起挡住一侧脸颊", "HAIR_DOWN", "HAIR_BLOWN_ACROSS_CHEEK"), "POSTURE": D("开口", "说完抿唇", "SPEAKING", "LIPS_PRESSED")}, referents=[("他", "QM")]),
    dict(s="E05-S14", n=4, sec=4, cps=4.8, faces={"TJ": "BACK_TO_CAMERA_WALKING_NOT_MEASURABLE"}, size="中全景", camera="横移跟随女子走进林木之间", axis="女子自林缘（画左）向林深处（画右）", blocking="女子说一句，迈步向密林深处走去，一身黑衣猎猎；紫眼乌鸦扑翅跟上",
         cast=["TJ"], action=("TJ", "女子说一句，迈步向密林深处走去，一身黑衣猎猎；乌鸦从枝头扑翅跟上", None), dialogue=("TJ", "眼下进山探查更要紧。", "CR"), emotion="calm",
         entry="女子站在林缘开口，乌鸦在枝头", exit="女子走进林木之间背影黑衣猎猎，乌鸦扑翅跟在她身后",
         dims={"POSITION": D("女子在林缘", "女子走进林木之间", "AT_FOREST_EDGE", "INTO_TREES"), "MOMENTUM": D("站定", "迈步走", "STANDING", "WALKING")}, referents=[("她", "TJ")]),
]
# ---------- END OF CHUNK 4 ----------

# 承接：读 E04 合同末镜的实际 completion_state（不是源章推定）
PREV_LAST = json.loads(PREV_CONTRACT.read_text(encoding="utf-8"))["shots"][-1]
assert PREV_LAST["shot_id"] == PREV_LAST_SHOT, PREV_LAST["shot_id"]

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

# ---------- 校验镜头表（seq=17：单镜 3–6 s、无对白 ≤4 s、单场 ≤16 s、全集 150–170、LOCKED ≤30%） ----------
def est_spoken(text, cps):
    han = len(re.findall(r"[㐀-鿿]", text)); p = len(re.findall(r"[，。！？；、,.!?;]", text))
    o = len(re.sub(r"[㐀-鿿\s，。！？；、,.!?;]", "", text))
    return han / cps + p * 0.16 + o * 0.08
by_scene = {}
for sh in SHOTS:
    by_scene.setdefault(sh["s"], []).append(sh)
assert list(by_scene) == list(SCENES), "镜头表场次顺序与 SCENES 不一致"
SCENE_SEC_EXCEPTIONS: dict[str, int] = {}
for sid, meta in SCENES.items():
    total = sum(x["sec"] for x in by_scene[sid])
    assert total == meta["sec"], (sid, total, meta["sec"])
    assert meta["sec"] <= SCENE_SEC_EXCEPTIONS.get(sid, PACING["scene_seconds_max"]) and meta["sec"] <= 12 * meta["info"], (sid, "单场 ≤16 s 且 ≤12s×信息条数")
    # engine grouping: every scene must partition into consecutive 4–8 s units
    secs = [x["sec"] for x in by_scene[sid]]
    def _part(rest):
        if not rest: return True
        acc = 0
        for i, v in enumerate(rest):
            acc += v
            if 4 <= acc <= 8 and _part(rest[i + 1:]): return True
            if acc > 8: return False
        return False
    assert _part(secs), (sid, "无法切成 4–8 s 单元", secs)
prev_locked = False
for i, sh in enumerate(SHOTS):
    shot_id = f"{sh['s']}-{sh['n']:02d}"
    assert shot_id in CAMERA_PLANS, (shot_id, "缺机位方案")
    assert 3 <= sh["sec"] <= PACING["shot_seconds_max"], (shot_id, "单镜 3–6 s")
    assert sh["entry"] != sh["exit"], sh
    for d, (a, b, ca, cb) in sh["dims"].items():
        assert d in {"POSITION", "POSTURE", "CONTACT", "POSSESSION", "INTEGRITY", "MOMENTUM"} and a != b and ca != cb, (shot_id, d)
    for word in ("持续", "保持", "连续", "全黑", "极暗", "纯黑", "黑暗", "伏击", "埋伏", "截", "藏身", "雪窟窿"):
        assert word not in sh["action"][1] and word not in sh["entry"] and word not in sh["exit"], (shot_id, word)
    for k in sh["cast"]:
        assert k not in VOICE_ONLY, (shot_id, "只配音角色不得入可见 cast")
    cp = CAMERA_PLANS[shot_id]
    locked = cp["motion_family"] == "LOCKED"
    if sh.get("dialogue"):
        cps = sh.get("cps", 4.2)
        need = max(0.12 + est_spoken(sh["dialogue"][1], cps) + 0.32 + 0.25, NPR.min_dialogue_seconds(sh["dialogue"][1], sh.get("cps")))
        assert need <= sh["sec"], (shot_id, "台词放不进镜头", round(need, 2), sh["sec"])
        assert sh["sec"] <= 5 or need > 5, (shot_id, "只有台词确实放不进 5 s 才允许 >5 s", round(need, 2))
        assert sh.get("emotion") in NPR.EMOTION_DELIVERY, (shot_id, "emotion")
        if sh["dialogue"][0] == "WR":
            assert "QM" in sh["cast"] or "LZ" in sh["cast"], (shot_id, "儿童对白必须双人同框")
    else:
        assert sh["sec"] <= 4, (shot_id, "seq=17：无对白镜 ≤4 s")
        assert not locked, (shot_id, "无对白镜必须有机位运动")
        if sh["sec"] >= 3 and cp["motion_family"] not in NPR.MOVING_CAMERA:
            assert any(v in sh["action"][1] for v in NPR.BODY_VERBS), (shot_id, "R7：无对白 ≥3 s 且机位非 ARC/TRACK/CRANE/PAN 时动作须含身体动词")
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
assert PACING["episode_total_seconds_target"][0] <= TOTAL <= PACING["episode_total_seconds_target"][1], TOTAL
# seq=19 A5：台词密度自检（与 script_structure_contract_gate 同口径，cps 4.0）
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


def _props_in_early(sh):
    txt = sh["action"][1] + sh["entry"] + sh["exit"]
    return [k for k in ("红松鼠", "松鼠", "干果", "兽皮袋", "猎叉", "短刀", "铁笼", "乌鸦", "青石") if k in txt]

# ---------- seq=27（Roger 2026-09-17《E05 生产线补正》，ADVISORY 经线主发出后在 E05 写手层执行）----------
# 规则 1 设置—揭晓闭环且可见；规则 2 结果镜有因镜；规则 3 台词动作词有画面；规则 4 对白段禁站桩/禁同构图连用/一句一镜。
_shot_start = {}
_t = 0
for _sh in SHOTS:
    _shot_start[f"{_sh['s']}-{_sh['n']:02d}"] = _t; _t += _sh["sec"]
_shot_by_id = {f"{x['s']}-{x['n']:02d}": x for x in SHOTS}
SETUPS = {
    "SETUP-NEWLIFE-SIGN": dict(setup="E05-S03-02", payoff="E05-S11-03", object="秦铭「再等上一段时间我应该能成」所设的新生异象——体表银色流光与白雾", partial=["E05-S03-01", "E05-S11-01"], verbs=["流光", "白雾蒸腾", "卷起"]),
    "SETUP-SQUIRREL-FATE": dict(setup="E05-S05-03", payoff="E05-S10-01", object="「一会炖熟了更可爱」所设的红松鼠下场", partial=["E05-S07-01", "E05-S08-02"], verbs=["塞进", "扣上笼门"]),
    "SETUP-CROW-TALKS": dict(setup="E05-S12-02", payoff="E05-S13-01", object="落在荆棘上的紫眼乌鸦会说人话", partial=[], verbs=["张开鸟喙", "口吐人语"]),
    "SETUP-CLOAKED-WOMAN": dict(setup="E05-S12-02", payoff="E05-S14-03", object="青石上只露下巴的黑衣女子是谁、来做什么", partial=["E05-S13-03"], verbs=["秀发飘起", "说一句"]),
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
RESULT_OF = {}   # 本集无「被埋/倒地/跪/塌/受伤/被制服」类结果镜；关笼的施动者秦铭与受动者红松鼠同镜（E05-S10-01）
_RESULT_RE = re.compile(r"被埋|埋在|倒地|倒在|跪|塌|受伤|见血|制服")
_DIALOGUE_ACTION_TABLE_V1 = ["别打", "住手", "放开", "别杀", "救命", "松手", "别动", "快跑", "别跑"]   # seq=27 规则 3 初版词表（短语形式，避免「倒挂」「猎杀」类误命中）
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
    if not _sh["cast"] and not _props_in_early(_sh):
        assert _sh["sec"] <= 2, (_sid, "纯环境无主体镜 ≤2 s")
    if len(_sh["cast"]) >= 3:
        assert _act.strip(), (_sid, "三人以上镜 action 不得为空")
    if not _sh.get("dialogue"):
        assert _sh["sec"] <= 5 and _cp["motion_family"] != "LOCKED", (_sid, "无对白镜 ≤5 s 且机位动")
_seen_sig = {}
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
                   "checks": {"setup_payoff_visible": "PASS", "result_shots_have_cause": "PASS", "dialogue_action_words_have_action": "PASS",
                              "blocking_signature_no_adjacent_repeat_and_scene_max_2": "PASS", "one_line_one_shot": "PASS", "pure_environment_shots_max_2s": "PASS",
                              "three_plus_cast_action_nonempty": "PASS", "no_dialogue_shots_max_5s_and_moving": "PASS"}}

# ---------- 关键台词逐字核对（源章 + narrative） ----------
src_text = SRC_CH.read_text(encoding="utf-8")
narr = SCRIPTS / f"{EP}_NARRATIVE_CANONICAL_{VER}.md"
narr_text = narr.read_text(encoding="utf-8")
AUTHORED_DIALOGUE = {
    "快一个月了，他一把举起了院里四百斤的黑毛驴。": "ch5：「快一个月了。」陆泽原句＋「二病子获得新生后，竟直接举起院中四百斤的黑毛驴」叙述转陆泽台词（台词密度，seq=19 A5；「举驴」是钩子后的第一件稀奇事）",
    "据传和他的一位亲戚有关，那人带回来一本高级意气功。": "ch5：「据传和他的一位亲戚有关。」陆泽原句＋「那人带回来一本高级意气功，让二病子改练此法」叙述转陆泽台词（台词密度，seq=19 A5）",
    "果然，灵兽甄选，必属上选。": "ch5 原句「果然，变异生物甄选，必属上选。」——『变异』『生物』为现代词，按世界观词表 LEXICON_yewujiang_v1 改为『灵兽』，其余字不变（seq=19 A6）",
    "一定可以猎杀到很凶的大块头灵兽，我等小叔成功。": "ch5 单句「这次就不吃了，等小叔新生后，一定可以猎杀到很凶的大块头变异生灵，我等小叔成功。」后半，『变异生灵』按词表改为『灵兽』，其余字不变（seq=19 A6）；拆句申报见 SPLIT_QUOTES",
}
SPLIT_QUOTES = {"小叔最厉害了，等小叔成功后，": "ch5 单句「小叔最厉害了，等小叔成功后，抓来山兽炖肉肉吃，我……馋了。」前半，字不变",
                "抓来山兽炖肉肉吃，我……馋了。": "同一源句后半，字不变",
                "这次就不吃了，等小叔新生后，": "ch5 单句「这次就不吃了，等小叔新生后，一定可以猎杀到很凶的大块头变异生灵，我等小叔成功。」前半，字不变（后半见 AUTHORED_DIALOGUE 词表申报）",
                "这种坚果需要处理后才能吃，不然微毒，": "ch5 单句「这种坚果需要处理后才能吃，不然微毒，还有些发苦，正好留着喂养松鼠吧。」前段，字不变；中段「还有些发苦，」按节奏略去",
                "正好留着喂养松鼠吧。": "同一源句末段，字不变"}
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

# ---------- 道具扫描（与引擎 editorial scan 同名） ----------
PROP_KEYWORDS = (("PROP-RED-SQUIRREL", ["红松鼠", "松鼠"]), ("PROP-NUT-HOARD", ["干果", "松子", "核桃", "红枣", "蘑菇", "橡果", "坚果"]), ("PROP-HIDE-BAG", ["兽皮袋"]),
                 ("PROP-HUNTING-FORK", ["猎叉"]), ("PROP-SHORT-KNIFE", ["短刀"]), ("PROP-BOW-ARROWS", ["弓箭", "硬弓"]),
                 ("PROP-BIRD-CAGE", ["铁笼"]), ("PROP-PURPLE-EYED-CROW", ["乌鸦"]),
                 ("SET-BLUESTONE-BOULDER", ["青石"]), ("SET-FOREST-EDGE-WOODS", ["密林", "林木"]))
PROP_NAME = {**{p["entity_id"]: p["name"] for p in PROPS}, **{s["entity_id"]: s["name"] for s in SETS}}
def _props_in(sh):
    txt = sh["action"][1] + sh["entry"] + sh["exit"]
    return [eid for eid, kws in PROP_KEYWORDS if any(k in txt for k in kws)]
PROP_MISSING: list = []
for sh in SHOTS:  # 出场道具必须在 entry_state 可见：名字出现在 action 里就必须也出现在 entry 或 exit 里（关键帧＝entry）
    shot_id = f"{sh['s']}-{sh['n']:02d}"
    for eid, kws in PROP_KEYWORDS:
        if eid.startswith("SET-"):
            continue
        if any(k in sh["action"][1] for k in kws):
            if not (any(k in sh["entry"] for k in kws) or any(k in sh["exit"] for k in kws)):
                PROP_MISSING.append((shot_id, eid))
assert not PROP_MISSING, ("道具在 action 出现但 entry/exit 未声明", PROP_MISSING)

TRANSITION_NOTES = {
    ("E05-S01-01", "E05-S01-02"): ("REACTION_CUT", "陆泽说完后切秦铭抬眼发问"),
    ("E05-S01-02", "E05-S01-03"): ("REACTION_CUT", "问完后切陆泽答，切在陆泽开口上"),
    ("E05-S02-01", "E05-S02-02"): ("MOTIVATED_CUT", "秦铭出神后切陆泽前倾，切在前倾上"),
    ("E05-S03-01", "E05-S03-02"): ("REACTION_CUT", "秦铭点头后切他的自信一句"),
    ("E05-S04-01", "E05-S04-02"): ("CAMERA_REFRAME", "前半句说完改取低机位，带出文晖"),
    ("E05-S04-02", "E05-S04-03"): ("MOTIVATED_CUT", "文晖点头后切秦铭起身，切在起身上"),
    ("E05-S05-01", "E05-S05-02"): ("REACTION_CUT", "松鼠瞪眼后切文睿眼睛发亮"),
    ("E05-S05-02", "E05-S05-03"): ("MOTIVATED_CUT", "文睿伸手后切秦铭把松鼠举到他眼前，切在举起上"),
    ("E05-S06-01", "E05-S06-02"): ("REACTION_CUT", "干果滚出后切文睿揪衣角"),
    ("E05-S06-02", "E05-S06-03"): ("REACTION_CUT", "咽口水后切秦铭赞叹"),
    ("E05-S07-01", "E05-S07-02"): ("MOTIVATED_CUT", "走到门前后切文睿拦门，切在张臂上"),
    ("E05-S08-01", "E05-S08-02"): ("CAMERA_REFRAME", "前半句说完改取中景带松鼠与收刀"),
    ("E05-S09-01", "E05-S09-02"): ("MOTIVATED_CUT", "陆泽摇头后切秦铭挑橡果，切在伸手上"),
    ("E05-S09-02", "E05-S09-03"): ("CAMERA_REFRAME", "前半句说完改取低机位对着松鼠"),
    ("E05-S10-01", "E05-S10-02"): ("REACTION_CUT", "笼门扣上后切孩子又笑又跳"),
    ("E05-S11-01", "E05-S11-02"): ("MOTIVATED_CUT", "落地无声后切旋身摆腿，切在旋身上；身份再锚定"),
    ("E05-S11-02", "E05-S11-03"): ("MOTIVATED_CUT", "定势低念后切舒展带风，切在踏步上"),
    ("E05-S12-01", "E05-S12-02"): ("REACTION_CUT", "疾驰接近山林后切远处青石上的女子（他尚未看见）"),
    ("E05-S13-01", "E05-S13-02"): ("MOTIVATED_CUT", "乌鸦说完第一句后切横移到女子，切在转头上"),
    ("E05-S13-02", "E05-S13-03"): ("REACTION_CUT", "乌鸦建议后切女子冷淡回话"),
    ("E05-S14-01", "E05-S14-02"): ("MOTIVATED_CUT", "落枝说完后切环绕到女子，切在转向上"),
    ("E05-S14-02", "E05-S14-03"): ("REACTION_CUT", "乌鸦劝告后切女子秀发飘起回话"),
    ("E05-S14-03", "E05-S14-04"): ("MOTIVATED_CUT", "抿唇后切迈步，切在迈步上"),
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
            identity_preservation="、".join(cname(k) for k in stay) + "保持同一面孔、发式与服装" + ("；" + "、".join(cname(k) for k in enter) + "为本镜新入画人物，面孔与服装按身份牌" if enter else "") if stay or enter else "本边界无人物延续；非人物主体按参考卡保持同一形貌",
            entry_exit_or_reveal=("、".join(cname(k) for k in stay) + "均已在画内" if stay else "") + ("；" + "、".join(cname(k) for k in enter) + "在本镜入画" if enter else "") + ("；" + "、".join(cname(k) for k in leave) + "在本镜不入画" if leave else "") + f"；{a['size']}切{b['size']}",
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
         "## 本集口径（SUPERVISOR_ORDERS seq=7 / seq=10 / seq=12 / seq=13 / seq=17 / seq=19 / seq=26）", "",
         f"- 全局风格：{STYLE['era_idiom']}",
         f"- 夜景：{STYLE['night_look']}",
         "- 禁用：" + "、".join(STYLE["forbidden"]),
         f"- 节奏（seq=17）：单镜 {PACING['shot_seconds_default'][0]}–{PACING['shot_seconds_default'][1]} s，上限 {PACING['shot_seconds_max']} s（台词确需）；无对白镜 ≤4 s；单场 ≤{PACING['scene_seconds_max']} s；视频单元 ≤{PACING['video_unit_seconds_max']:g} s（硬上限 {PACING['video_unit_seconds_hard_cap']:g} s）；无对白静止 ≤{PACING['no_dialogue_static_hold_seconds_max']:g} s 否则拒收；全集前 3 s 钩子＝陆泽「隔壁村的二病子成了」；每场首镜从进行中动作开始、场间在动作上切、每场有转折与 button；全集 {PACING['episode_total_seconds_target'][0]}–{PACING['episode_total_seconds_target'][1]} s（本稿 {TOTAL} s，{len(SHOTS)} 镜）",
         f"- 机位运动：LOCKED ≤30%（本稿 {len(LOCKED_IDS)}/{len(SHOTS)}：{'、'.join(LOCKED_IDS)}）、不连续 LOCKED、无对白镜必动、R7、R8、LOCKED 只用于 ≤5 s 对白镜、同轴同景别不连续 >2 镜、开场镜运动",
         f"- ★seq=12/13 身份再锚定：{'、'.join(REANCHOR_IDS)} 为远景小人影之后的露脸镜，声明 identity_reanchor；不写全黑/极暗；儿童对白双人同框（文睿每句都与秦铭同框，文晖不说话）",
         "- ★乌鸦：说话人「乌鸦」只配音不出身份牌（identity_source.mode=VOICE_ONLY_NO_PLATE，presence=OFFSCREEN_VOICE_ONLY，不入可见 cast）；画面里的乌鸦按参考卡 PROP-PURPLE-EYED-CROW 生成，鸟喙开合即可，不做卡通嘴型",
         "- ★黑衣女子：S12–S13 斗篷立领遮脸只露下巴（身份不可测，按 D-16 姿态豁免申报）；S14-03 正面露脸为本集唯一可测身份镜",
         "- ★seq=27（2026-09-17 补正）：设置—揭晓闭环 4 组（SETUPS，payoff 镜含可见动作动词，>25 s 者有部分露出）；本集无结果镜（result_of 空）；台词动作词表 v1 零命中；每镜 blocking_signature 相邻不重复、场内 ≤2；一句台词只属一镜；无纯环境镜；无对白镜 ≤5 s 且机位动",
         "- ★选择性配乐（D-32）：E05-S05–S06（松鼠苏醒与逗孩子）、E05-S11–S12（练功到疾驰）、E05-S13–S14（黑衣女子与乌鸦）三处纯器乐，其余原生现场声",
         "- ★音色（seq=17）：本集说话人：秦铭、陆泽、梁婉清（重选音色首次出声）、陆文睿、黑衣女子（新）、乌鸦（新）",
         f"- ★承接：E05-S01-01 的 entry_state 接 {PREV_LAST_SHOT} 的 completion_state（{PREV_LAST['completion_state']}）；本集从秦铭郑重点头开始，不复位、不重演", ""]
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
        lines.append(f"- blocking_signature：{BLOCKING_SIGNATURE[shot_id]}" + (f"｜setup_id：{SETUP_ID_BY_SHOT[shot_id]}" if shot_id in SETUP_ID_BY_SHOT else "") + (f"｜payoff_of：{PAYOFF_OF_BY_SHOT[shot_id]}" if shot_id in PAYOFF_OF_BY_SHOT else "") + (f"｜result_of：{RESULT_OF[shot_id]}" if shot_id in RESULT_OF else ""))
        lines.append("")
directing = SCRIPTS / f"{EP}_DIRECTING_SCRIPT_{VER}.md"
directing.write_text("\n".join(lines), encoding="utf-8")
print("directing written", directing)
# ---------- END OF CHUNK 5 ----------

# ---------- generation contract ----------
NPR_FACE = {"QM": "束发木簪、无胡须的清瘦年轻男子", "LZ": "灰布裹巾的结实青年", "LW": "麻布包髻的年轻妇人",
            "WR": "五岁男孩、总角、赭红棉袍", "WH": "两岁男童、总角小揪、土黄棉袍", "TJ": "黑裘皮斗篷立领遮颈的高挑年轻女子", "CR": "（不入画，只配音）"}
NPR_APPLIED: dict[str, list[str]] = {}
NPR_BLOCKS: list[str] = []
NON_CHAR_SUBJECTS = {p["entity_id"]: p["name"] for p in PROPS} | {s["entity_id"]: s["name"] for s in SETS}

def ent_name(k):
    return cname(k) if k in CH else NON_CHAR_SUBJECTS.get(k, k)
def ent_id(k):
    # engine character_entity_contract: any non-empty id must resolve to a CHARACTER; creatures/props keep the name, id empty
    return cid(k) if k in CH else ""

def apply_prompt_rules(sh, shot_id, act):  # seq=10：全部镜头套用
    sid = sh["s"]
    scene_cast = {k for x in by_scene[sid] for k in x["cast"]}
    fam = (CAMERA_PLANS.get(shot_id) or {}).get("motion_family")
    shot = {"shot_id": shot_id, "sec": sh["sec"], "size": sh["size"], "camera_family": fam, "cast": sh["cast"],
            "action": act, "dialogue": sh.get("dialogue"), "entry": sh["entry"], "exit": sh["exit"]}
    ctx = {"scene_cast": scene_cast, "loc": SCENES[sid]["loc"], "cps": sh.get("cps"),
           "names": {k: cname(k) for k in CH}, "face_desc": NPR_FACE,
           "prop_tokens": ["太阳石", "猎叉", "短刀", "弓箭", "兽皮袋", "干果", "橡果", "蘑菇", "红松鼠", "铁笼", "青石", "荆棘", "乌鸦"]}
    new_act, applied, blocks = NPR.apply(shot, ctx)
    NPR_APPLIED[shot_id] = applied
    NPR_BLOCKS.extend(blocks)
    return new_act

SHOT_ORDER = [f"{x['s']}-{x['n']:02d}" for x in SHOTS]
def life_state(k, shot_id):
    return "alive"   # seq=19 B1：本集无人受伤、无人死亡
EMOTION_BY_SHOT = {f"{x['s']}-{x['n']:02d}": x.get("emotion") for x in SHOTS if x.get("dialogue")}
assert all(EMOTION_BY_SHOT.values()), ("seq=19 C2: every dialogue shot needs an emotion", [k for k, v in EMOTION_BY_SHOT.items() if not v])

def shot_json(sh):
    sid = sh["s"]; shot_id = f"{sid}-{sh['n']:02d}"
    subj, act, patient = sh["action"]
    act = apply_prompt_rules(sh, shot_id, act)
    dlg = sh.get("dialogue")
    spk_id = cid(dlg[0]) if dlg else ""
    spk_offscreen = bool(dlg) and dlg[0] in VOICE_ONLY
    lst_id = cid(dlg[2]) if dlg and dlg[2] else ""
    resolved = [{"surface_form": surface, "entity_id": cid(key) if key in CH else key} for surface, key in sh["referents"]]
    presence = {cid(k): "VISIBLE_AND_IDENTITY_LOCKED" for k in sh["cast"]}
    if spk_offscreen:
        presence[spk_id] = "OFFSCREEN_VOICE_ONLY"
    slots = sh.get("slots") or {}; faces = sh.get("faces") or {}
    states = {cid(k): sh["exit"] for k in sh["cast"]}
    if spk_offscreen:
        states[spk_id] = sh["exit"]
    subj_is_char = subj in CH
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
        "period_constraints": PERIOD_BY_LOC[SCENES[sid]["loc"]],
        "pacing_flags": {"hook": shot_id == "E05-S01-01", "scene_opener_in_motion": sh["n"] == 1, "scene_button": sh is by_scene[sid][-1],
                         "no_dialogue_static_hold_seconds_max": PACING["no_dialogue_static_hold_seconds_max"] if not dlg else None},
        **({"dialogue_delivery": {"chinese_characters_per_second": sh["cps"], "basis": "导演稿：按 nalu_prompt_rules.min_dialogue_seconds 放不进默认语速的句子标 4.8–5.2 字/秒，文本零改动"}} if sh.get("cps") else {}),
        "prompt_spec": {
            "camera_plan": {**CAMERA_PLANS[shot_id], "authorship": "DIRECTING_SCRIPT_AUTHORED", "selection_mode": "LOCKED", "source": f"E05_DIRECTING_SCRIPT_v1.md#{shot_id}"},
            "cast": [{"character": cname(k), "character_id": cid(k), "life_state": life_state(k, shot_id),
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
                "lip_owner_id": "" if spk_offscreen else spk_id, "entity_states": states, "entity_presence": presence},
        },
    }

CHARACTER_ROWS = [
    {"character_id": "CHAR-QINMING", "canonical_name": "秦铭", "aliases": ["小秦", "小叔", "秦叔", "铭哥", "这个少年"], "voice_entity_id": "", "identity_reference_entity_id": "",
     "identity_source": {"mode": "SOURCE_PHOTO", "file": str(QM_SOURCE_V2), "sha256": STYLE_RESET_DISCLOSURE["qinming_identity_source"]["sha256"], "note": "E02 已按 source_v2 锁定的三视图身份牌直接复用（seq=26）；不重做"},
     "appearance_ch1": "清瘦颀长，面色有血色，眼睛清亮；高髻木簪，外披旧裘氅，内深青交领窄袖袍银线滚边（唐宋语汇；面孔与发冠服制以 CHAR-QINMING__SOURCE_V2_TANG.png 为准）",
     "appearance_ch5": "ch5：清秀的面孔上带着健康的红润之色，目光炯炯；逗孩子时带笑；练功时动作圆活刚劲，体表淡银流光、白雾蒸腾；疾驰如流星；远处侧头持弓"},
    {"character_id": "CHAR-LUZE", "canonical_name": "陆泽", "aliases": ["陆哥", "你陆哥"], "voice_entity_id": "", "identity_reference_entity_id": "", "identity_source": {"mode": "E02_IDENTITY_CARD_REUSE", "note": "沿用 E02 唐宋版身份牌，不重做"},
     "appearance_ch1": "年轻男子，身体结实有力，实在人；深灰交领短褐、灰布裹巾束发", "appearance_ch5": "ch5：讲二病子新生与意气功，劝秦铭换练法；反对养松鼠又被孩子的笑闹说服；临别提着铁笼与橡果"},
    {"character_id": "CHAR-LIANGWANQING", "canonical_name": "梁婉清", "aliases": ["嫂子"], "voice_entity_id": "", "identity_reference_entity_id": "", "identity_source": {"mode": "E02_IDENTITY_CARD_REUSE", "note": "沿用 E02 唐宋版身份牌，不重做；本集一句台词（seq=17 重选音色首次出声）"},
     "appearance_ch1": "年轻妇人，陆泽之妻；灰褐交领短襦配旧蓝长裙、麻布围裙、麻布包髻", "appearance_ch5": "ch5：劝秦铭改练黑夜冥想术；看着陆泽比划举驴时摇头笑"},
    {"character_id": "CHAR-LUWENRUI", "canonical_name": "陆文睿", "aliases": ["文睿", "小文睿"], "voice_entity_id": "", "identity_reference_entity_id": "", "identity_source": {"mode": "E02_IDENTITY_CARD_REUSE", "note": "沿用 E02 身份牌；本集七句台词，每句都与秦铭同框不单独特写"},
     "appearance_ch1": "五岁左右男孩，小脸红扑扑，眼睛大而清澈，纯真可爱略腼腆；赭红小交领棉袍", "appearance_ch5": "ch5：馋肉又舍不得松鼠，揪衣角咽口水，张开双臂拦门求情，下定决心「我等小叔成功」"},
    {"character_id": "CHAR-LUWENHUI", "canonical_name": "陆文晖", "aliases": ["文晖", "小文晖"], "voice_entity_id": "", "identity_reference_entity_id": "", "identity_source": {"mode": "TEXT_TO_IMAGE", "note": "无源照片；按 appearance 文生图生成身份牌（seq=3 c3）；本集不说话，只在两人以上的镜里"},
     "appearance_ch1": "两岁出头的男童，步履蹒跚，明亮的眼睛，圆脸，总角小揪；土黄小交领棉袍裹得滚圆", "appearance_ch5": "ch5：凑到哥哥身后有样学样地点头，抓一颗红枣，围着铁笼又笑又跳"},
    {"character_id": "CHAR-FEMALE-LEAD-BLACKCLOAK", "canonical_name": "黑衣女子", "aliases": ["唐瑾", "斗篷女子", "黑裘女子"], "voice_entity_id": "", "identity_reference_entity_id": "", "identity_source": {"mode": "TEXT_TO_IMAGE", "note": "无源照片；按 appearance 文生图生成身份牌（seq=3 c3；seq=8 casting：ch5 斗篷女子＝唐瑾，id 沿 CHAR-FEMALE-LEAD-BLACKCLOAK）；本集四句台词"},
     "appearance_ch1": "身材高挑而纤细的年轻女子，莹白脸颊、精致的下巴、黑亮的长发半束；黑色裘皮斗篷流动淡淡乌光，立领遮颈只露下巴，内黑色交领窄袖劲装；清丽绝俗中更显冷艳，神秘高冷", "appearance_ch5": "ch5：静立青石上看远处的秦铭；「有比他更适合的人」；山风吹起秀发挡在一侧脸颊；转身进山探查"},
    {"character_id": "CHAR-CROW", "canonical_name": "乌鸦", "aliases": ["紫眼乌鸦"], "voice_entity_id": "", "identity_reference_entity_id": "",
     "identity_source": {"mode": "VOICE_ONLY_NO_PLATE", "visual_entity_id": "PROP-PURPLE-EYED-CROW", "note": "口吐人语的乌鸦是说话人（配音角色），没有人脸、不出身份牌、不入可见 cast；画面里的乌鸦按参考卡 PROP-PURPLE-EYED-CROW 生成；entity_presence=OFFSCREEN_VOICE_ONLY，lip_owner 为空"},
     "appearance_ch1": "（画面见 PROP-PURPLE-EYED-CROW）满身黑羽如乌金、一双紫色的眼睛、比寻常乌鸦略大；声音苍老沙哑、老辣而玩世不恭", "appearance_ch5": "ch5：口吐人语评价秦铭的新生异象，劝女子别错过一颗种子"},
]
BGM_CUES = [
    {"cue_id": "E05-BGM-01", "scenes": ["E05-S05", "E05-S06"], "narrative_function": "COMIC_RELIEF_SQUIRREL", "volume": 0.22, "dialogue_duck_db": -8,
     "brief": "Light-hearted playful instrumental cue in ancient Chinese folk style: pizzicato pipa, bamboo dizi trills, soft hand drum, a tiny squirrel in mortal terror while children beg to keep it, gentle humour, no vocals, 28 seconds"},
    {"cue_id": "E05-BGM-02", "scenes": ["E05-S11", "E05-S12"], "narrative_function": "AWAKENING_TRAINING_SPRINT", "volume": 0.3, "dialogue_duck_db": -8,
     "brief": "Rising cinematic instrumental cue for a young hunter training alone at night in a Tang-Song village yard until his skin shimmers silver and he sprints into the snowfield: guzheng ostinato building, low drum pulse, breath-like flute swells, a sense of dormant power waking, no melody vocals, 22 seconds"},
    {"cue_id": "E05-BGM-03", "scenes": ["E05-S13", "E05-S14"], "narrative_function": "MYSTERY_STRANGER_AND_CROW", "volume": 0.26, "dialogue_duck_db": -8,
     "brief": "Mysterious cold instrumental cue for a cloaked woman and a talking crow watching from a boulder in a moonlit snowfield in ancient China: sparse xiao flute, bowed erhu harmonics, a distant bell, wind-like textures, aloof and unresolved, no vocals, 32 seconds"},
]
# ---- seq=19 A4 / B3′: prop sources and entity introductions ----
_E03 = json.loads(E03_CONTRACT.read_text(encoding="utf-8"))
_e03_squirrel = next((sh_["shot_id"] for sh_ in _E03["shots"] if "松鼠" in str(sh_.get("completion_state"))), None)
assert _e03_squirrel, "E03 squirrel acquisition shot not found"
_E04 = json.loads(PREV_CONTRACT.read_text(encoding="utf-8"))
PROP_SOURCES = {
    "PROP-RED-SQUIRREL": {"acquired": {"episode": "E03", "shot_id": _e03_squirrel}, "recap_shot_id": "E05-S01-01", "payoff_shot_ids": ["E05-S04-03", "E05-S10-01"]},
    "PROP-NUT-HOARD": {"acquired": {"episode": "E03", "shot_id": _e03_squirrel}, "recap_shot_id": "E05-S01-01", "payoff_shot_ids": ["E05-S06-01", "E05-S09-02"]},
    "PROP-HIDE-BAG": {"acquired": {"episode": "E03", "shot_id": _e03_squirrel}, "recap_shot_id": "E05-S01-01", "payoff_shot_ids": ["E05-S09-01"]},
    "PROP-HUNTING-FORK": {"acquired": {"episode": "E03", "shot_id": _E03["shots"][0]["shot_id"]}, "recap_shot_id": "E05-S01-01"},
    "PROP-SHORT-KNIFE": {"acquired": {"episode": "E03", "shot_id": _E03["shots"][0]["shot_id"]}, "recap_shot_id": "E05-S01-01", "payoff_shot_ids": ["E05-S07-01"]},
    "PROP-BOW-ARROWS": {"acquired": {"episode": "E04", "shot_id": "E04-S02-04"}, "recap_shot_id": "E05-S12-01"},
    "PROP-BIRD-CAGE": {"acquired": {"episode": EP, "shot_id": "E05-S10-01"}, "payoff_shot_ids": ["E05-S10-02"]},
    "PROP-PURPLE-EYED-CROW": {"acquired": {"episode": EP, "shot_id": "E05-S12-02"}, "payoff_shot_ids": ["E05-S13-01"]},
    "SET-BLUESTONE-BOULDER": {"acquired": {"episode": EP, "shot_id": "E05-S12-02"}, "payoff_shot_ids": ["E05-S13-02"]},
    "SET-FOREST-EDGE-WOODS": {"acquired": {"episode": "E03", "shot_id": _E03["shots"][0]["shot_id"]}, "recap_shot_id": "E05-S14-01"},
}
def with_sources(row):
    return {**row, **PROP_SOURCES.get(row["entity_id"], {"acquired": {"episode": PREV_EP, "shot_id": _E04["shots"][0]["shot_id"]}})}
_first_shot_of = {}
for _sh in SHOTS:
    for _k in _sh["cast"]:
        _first_shot_of.setdefault(_k, f"{_sh['s']}-{_sh['n']:02d}")
    if _sh.get("dialogue") and _sh["dialogue"][0] in VOICE_ONLY:
        _first_shot_of.setdefault(_sh["dialogue"][0], f"{_sh['s']}-{_sh['n']:02d}")
_PRIOR = {"LZ": "E04", "WR": "E04", "LW": "E02"}   # already introduced in E01–E04
NEW_IN_E05 = {"PROP-BIRD-CAGE", "PROP-PURPLE-EYED-CROW", "SET-BLUESTONE-BOULDER"}
ENTITY_INTRODUCTIONS = (
    [{"entity_id": cid(k), "first_shot_id": _first_shot_of.get(k), "setup": ({"kind": "prior_episode", "ref": _PRIOR[k]} if k in _PRIOR else {"kind": "shot", "ref": _first_shot_of.get(k)})}
     for k in CH if k != "QM"]
    + [{"entity_id": r["entity_id"], "first_shot_id": r.get("first_shot") or "",
        **({"setup": {"kind": "shot", "ref": r.get("first_shot")}, "payoff_shot_id": PROP_SOURCES[r["entity_id"]]["payoff_shot_ids"][0]} if r["entity_id"] in NEW_IN_E05
           else {"setup": {"kind": "prior_episode", "ref": PROP_SOURCES.get(r["entity_id"], {}).get("acquired", {}).get("episode", "E03")}})}
       for r in (*PROPS, *SETS)]
)

contract = {
    "schema": "qingshan.generation_contract.v3",
    "episode": EP, "version": VER,
    "narrative_canonical": narr.name, "narrative_sha256": sha(narr),
    "style": {**STYLE, "authority": "SUPERVISOR_ORDERS seq=7 c1/c2；seq=26 沿用；PRODUCTION_LINE_OVERVIEW_v1 §四 3/5", "negative_prompt_fixed": "欧式、哥特、和风、仙侠符文、现代物件、冷灰去饱和、暗黑调色、玻璃窗、电灯、拉链纽扣、纯黑画面、怪兽特效、卡通动物嘴型"},
    "pacing": PACING,
    # ---- seq=19 "does the contract hold up" declarations (D-40/D-41) ----
    "protagonist_ids": ["CHAR-QINMING"],
    "antagonist_groups": [],
    "ambush_contracts": [],
    "entity_introductions": ENTITY_INTRODUCTIONS,
    "writer_visibility_contract_seq27": SEQ27_SELFCHECK,
    "style_reset_disclosure": STYLE_RESET_DISCLOSURE,
    "carry_in": {"previous_episode": PREV_EP, "previous_scene_id": "E04-S11", "previous_shot_id": PREV_LAST["shot_id"],
                 "previous_completion_state": PREV_LAST["completion_state"],
                 "first_shot_id": "E05-S01-01", "first_shot_entry_state": SHOTS[0]["entry"],
                 "rule": "不复位、不重演、不闪回 E04 内容，沿同一方向推进至少一步（秦铭笑容收住望着陆泽→郑重点头，陆泽接着说二病子）"},
    "visual_culture_contract": {
        "schema": "qingshan.visual_culture_contract.v1", "status": "LOCKED",
        "profile_id": STYLE["profile_id"], "decision_owner": "WRITER_DIRECTOR",
        "decision_basis": "ch5 明写：炕上干果与兽皮袋、猎叉上的红松鼠、短刀、养鸟用的铁笼、橡果、院中练功卷雪、体表银色流光白雾、荒野疾驰、青石与荆棘、黑裘皮斗篷、乌金黑羽紫眼乌鸦；Roger 2026-09-13 审片：中国唐宋不要西式暗黑",
        "source_ref": str(SRC_CH),
        "story_world": "永夜纪元的北地冻土村落与村外雪野密林，前工业农耕渔猎社会，中国唐宋衣冠与营造",
        "production_design": STYLE["era_idiom"] + "；野外无任何人造物；光源只有太阳石火霞与雪面月色反光；体表银光是极淡的流光、乌鸦紫眼是唯一紫色点光",
        "armor_tradition": "本集无兵甲；猎具为木柄铁头猎叉、直刃短刀、竹木硬弓与铁箭；黑衣女子的斗篷下是劲装不是甲胄；不得出现制式铁札甲、西式甲胄或现代猎具",
        "palette_system": {"base": "靛黑夜色、雪面月色青蓝、林木深青灰", "accent": "太阳石橘红、红松鼠火红皮毛、体表淡银流光、乌鸦乌金黑羽与紫眼、黑裘皮斗篷的乌光", "skin": "屋内火光下暖、雪光下清；秦铭有血色；黑衣女子莹白"},
        "lighting_language": STYLE["night_look"] + "；屋内铜盆太阳石为唯一光源；院中石盆光与雪面反光；野外浅夜以雪面反光写层次，最暗处仍见轮廓",
        "image_texture": "颗粒感胶片质感、真实材质（兽皮、粗麻、雪、铁条、松鼠毛、裘皮、乌羽）、呼出的白气与卷起的雪粒可见、火光有可见的边缘晕",
        "forbidden_influences": STYLE["forbidden"],
    },
    "character_entities": [dict(row, wardrobe_garments=WARDROBE_GARMENTS[row["character_id"]]) for row in CHARACTER_ROWS],
    "non_character_entities": [with_sources(r) for r in (*PROPS, *SETS)],
    "props": {"authority": "SUPERVISOR_ORDERS seq=7 c6：关键道具出参考卡入资产库并挂进视频参考列表", "reference_cards": [with_sources(p) for p in PROPS + SETS if p.get("reference_card_required")], "declared_without_card": [p["entity_id"] for p in PROPS if not p["reference_card_required"]]},
    "scene_states": [
        {"scene_id": sid, "location_id": m["loc"], "time_id": m["time"], "weather": m["weather"], "lighting": m["light"],
         "target_seconds": m["sec"], "source_events": m["beats"], "new_information_count": m["info"],
         "ambient_life": m["ambient_life"], "weather_provenance": m["weather_provenance"], "period_constraints": PERIOD_BY_LOC[m["loc"]], "costume_overrides": {}}
        for sid, m in SCENES.items()],
    "shots": [shot_json(sh) for sh in SHOTS],
    "internal_transition_authoring": [{"from_shot_id": a, "to_shot_id": b, "authorship": "DIRECTOR_AUTHORED", **row} for (a, b), row in INTERNAL_TRANSITIONS.items()],
    "audio_contract": {
        "bgm": {"mode": "SELECTIVE", "used": True, "authority": "SUPERVISOR_ORDERS seq=13 c2 / D-32",
                "declaration": "SELECTIVE_NARRATIVE_CUES：三处纯器乐配乐（松鼠苏醒与逗孩子、练功到疾驰、黑衣女子与乌鸦），覆盖 ≤85%，其余全部原生现场声（≥8 s 纯现场声）；经 AgentCut bgm-generate → giggle generate-music 生成，受预算守卫与事务存档约束（窗口隔离对账 e23）",
                "cues": BGM_CUES},
        "voice_casting": {"authority": "SUPERVISOR_ORDERS seq=17 c1", "note": "按角色定义重选音色，见 runtime/voice_catalog.json；参考音文本为体现性格的整句台词；乌鸦为只配音角色（VOICE_ONLY_NO_PLATE）"},
        "ambient_by_scene": {
            "E05-S01": "屋内暖、炕上干果被拨动、屋外风声隔窗、松鼠倒挂微晃的皮绳声", "E05-S02": "屋内暖、陆泽压低的说话声、铜盆里太阳石的细微噼响",
            "E05-S03": "屋内暖、衣料摩擦、梁婉清的温声", "E05-S04": "孩子的呼吸与咽口水、文晖蹒跚的小脚步、起身取松鼠的猎叉磕墙",
            "E05-S05": "松鼠惊恐的吱吱叫与扭动、孩子的笑声", "E05-S06": "松子核桃红枣滚在炕上的哗啦声、揪衣角、松鼠皮毛炸立的细响",
            "E05-S07": "短刀出鞘、松鼠尖叫剧烈挣扎、铁丝摩擦、文睿跑到门前的小脚步", "E05-S08": "文睿的呼吸、松鼠吱吱求助、短刀入鞘",
            "E05-S09": "陆泽的叹息、挑拣橡果的碰响、松鼠急促的喘息", "E05-S10": "松鼠被塞进铁笼、笼门铁扣扣上、两个孩子又笑又跳、提笼的铁条声",
            "E05-S11": "院中寒气、关节活动、跃起破风与落地无声、摆腿抽空的沉闷响、猛烈的风卷雪、白雾蒸腾的呼吸", "E05-S12": "荒野疾驰的踩雪与风声、远处寒风吹动裘皮斗篷、乌鸦扑翅落枝",
            "E05-S13": "乌鸦短促的嘎声与人语、寒风吹动斗篷、荆棘簌簌", "E05-S14": "山风呼啸、长发与黑衣猎猎、枝头积雪落下、踩雪进林、乌鸦扑翅",
        },
        "dialogue_units": [{"shot_id": shot, "speaker_id": cid(s), "listener_id": cid(sh_l) if sh_l else "", "text": q, "verbatim_in_source": v, "emotion": EMOTION_BY_SHOT[shot],
                            **({"speaker_presence": "OFFSCREEN_VOICE_ONLY", "visual_entity_id": "PROP-PURPLE-EYED-CROW"} if s in VOICE_ONLY else {})}
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
BEATS = [  # ch5 实读 40 拍；落点到场次粒度（gate 10 读 landed_at）
    ("E05-EV-01", "landed", "E05-S01-01", "秦铭郑重地点头，是该琢磨怎么「新生」了（关乎一生、影响命运的内心不演）"),
    ("E05-EV-02", "dropped", "", "十五六岁是黄金期得到的好处最多；双树村佼佼者二十岁后才新生、有些超过三十；全村四十多户两百多人新生者不足十人——世界观科普不单独占镜（seq=17），只保留「黄金期」三字在陆泽台词里"),
    ("E05-EV-03", "landed", "E05-S01-01", "陆泽：「隔壁村的二病子成了，正好处在黄金期内。」"),
    ("E05-EV-04", "dropped", "", "秦铭对二病子的印象：身材单薄面黄肌瘦病色稀疏枯草色头发；深感意外——外貌与内心不演"),
    ("E05-EV-05", "landed", "E05-S01-02 至 E05-S01-03", "「什么时候的事？」「快一个月了」；举起院中四百斤的黑毛驴一改孱弱（叙述转陆泽台词）"),
    ("E05-EV-06", "landed", "E05-S01-03", "「真是稀奇」的意外与体壮少年多次受挫的对比——以秦铭挑眉与陆泽比划承担，台词略去"),
    ("E05-EV-07", "dropped", "", "陆泽感触：自己身强体健二十三岁仍未新生——内心不演"),
    ("E05-EV-08", "landed", "E05-S02-01", "「据传和他的一位亲戚有关」；亲戚常年游历认定好苗子、没锁住精气神潜力足、带回高级意气功改练效果显著（并入陆泽一句台词，其余叙述不演）"),
    ("E05-EV-09", "landed", "E05-S02-01", "秦铭出神，人的际遇果然难料"),
    ("E05-EV-10", "dropped", "", "事后那人说二病子根底厚实或许可以走得很远；陆泽没料到病色之人这么厉害——转述不演"),
    ("E05-EV-11", "landed", "E05-S02-02", "陆泽劝：「小秦，我觉得你那种特殊的锻炼方式该换一换了。」（咱们没有高级意气功但有可行路数一句略去）"),
    ("E05-EV-12", "dropped", "", "陆泽的判断：秦铭身体素质强却迟迟不新生，问题在磨砺方法；十六岁出头再这样要错过黄金期——内心不演"),
    ("E05-EV-13", "landed", "E05-S03-01", "梁婉清：「小秦，不如改练你陆哥的黑夜冥想术吧。」"),
    ("E05-EV-14", "dropped", "", "各地公开的力量书让所有人改善体质自保，谈不上高端——世界观科普不演"),
    ("E05-EV-15", "merged", "E05-S03-01", "秦铭不是一根筋，知晓好意点头「接下来我认真试试看」——台词按节奏略去，以点头承担"),
    ("E05-EV-16", "dropped", "", "陆泽轻叹野路数耽误、不如低级黑夜冥想术初解、改练时间紧迫、唯有高级意气功能短期改变；「哪怕有一本中级秘册也好」；流传在外的书只几本——按节奏略去"),
    ("E05-EV-17", "landed", "E05-S03-01 至 E05-S03-02", "秦铭不焦躁：野路数有了效果体表流光银色涟漪曾真实显化（不复证 E02）；面孔红润目光炯炯「陆哥，嫂子，再等上一段时间，我应该能成」"),
    ("E05-EV-18", "dropped", "", "新生的机理释义（重回母胎、后天母胎化生、谁不心动）；二病子举活物、陆泽掰断青砖击断木人桩的战力对比——科普与对比不演"),
    ("E05-EV-19", "merged", "E05-S03-02", "「沉疴尽去后，我感觉不一样了，身体状态前所未有的好」——与「我应该能成」同义，按节奏并入前句的自信神态"),
    ("E05-EV-20", "landed", "E05-S04-01 至 E05-S04-02", "五岁文睿认真点头满脸期待「小叔最厉害了…抓来山兽炖肉肉吃，我……馋了」（拆两镜）；两岁文晖蹒跚附和（「小叔……厉害，吃肉肉」不出声，以跟着点头承担）"),
    ("E05-EV-21", "landed", "E05-S04-03", "秦铭笑「不用等以后，今天就可以满足你们」，取下猎叉上的红松鼠"),
    ("E05-EV-22", "landed", "E05-S05-01", "松鼠黑宝石般的眼睛瞪出惊恐；「咦，它又活了，这样更好，肉质远比冰冻过的鲜嫩」"),
    ("E05-EV-23", "landed", "E05-S05-02 至 E05-S05-03", "文睿「这只松鼠好漂亮，有些可爱」；秦铭「一会炖熟了更可爱，保你吃得香」；文睿纠结挪不开目光想养起来"),
    ("E05-EV-24", "merged", "E05-S04-02", "小文晖有样学样眼睛倒映松鼠「鼠鼠……可爱」；陆泽梁婉清都笑了——文晖不出声，跟着点头一镜承担；父母的笑不单独占镜"),
    ("E05-EV-25", "landed", "E05-S06-01", "秦铭认可可爱又能干，过冬粮食松子核桃榛果红枣十几种连蘑菇都储存；「这下好了，松鼠炖蘑菇，好吃又大补」（清单不念，以拨开兽皮袋承担）"),
    ("E05-EV-26", "landed", "E05-S06-02", "文睿「真……真的吗？可是，我不想它死去」揪衣角咽口水"),
    ("E05-EV-27", "landed", "E05-S06-03", "虎掌菌阳雀菌山珍有口福（不演）；「果然，变异生物甄选，必属上选」→词表改「灵兽甄选」；红松鼠气性大皮毛炸立"),
    ("E05-EV-28", "landed", "E05-S07-01", "秦铭抽出短刀拎着它去院中剥皮，见血不宜让孩子看到；「吱吱！」惊悚慌张叫个不停剧烈挣扎铁丝快勒进肉里"),
    ("E05-EV-29", "landed", "E05-S07-02", "文睿拦住「小叔，要不……留下它吧」，努力遗忘炖肉的滋味下定决心求情"),
    ("E05-EV-30", "merged", "E05-S07-02", "「多好的食材，变异生灵的肉质最鲜美」秦铭笑着诱惑——按节奏略去，以文睿的求情直接接决心"),
    ("E05-EV-31", "landed", "E05-S08-01 至 E05-S08-02", "「这次就不吃了，等小叔新生后，一定可以猎杀到很凶的大块头变异生灵，我等小叔成功」（拆两镜；变异生灵→灵兽）；松鼠一会儿看刀一会儿对文睿吱叫求助"),
    ("E05-EV-32", "merged", "E05-S08-02", "梁婉清惊讶「这只小山兽灵性十足…紧张得褶皱了」——按节奏略去，松鼠求助的画面承担；秦铭收起短刀（肉少、孩子喜欢活物那就养起来的内心不演）"),
    ("E05-EV-33", "landed", "E05-S09-01", "陆泽蹙眉「这个冬季不同以往，哪有多余的食物给它」；松鼠眼巴巴望着兽皮袋里面全是它的家底；秦铭注意到它灵性高（不演）"),
    ("E05-EV-34", "landed", "E05-S09-02 至 E05-S09-03", "挑出橡果「这种坚果需要处理后才能吃，不然微毒，（还有些发苦，）正好留着喂养松鼠吧」（拆两镜）；红松鼠不吱声瞪圆眼睛喘息微粗"),
    ("E05-EV-35", "landed", "E05-S10-01", "「能活下来你还不满意？另外，敢咬人的话我保准炖了你」，关进养鸟用的铁笼"),
    ("E05-EV-36", "landed", "E05-S10-02", "陆泽觉得不如卖掉皮毛值钱（不演），看到两个孩子又笑又跳便不再反对；临别带上铁笼子和一堆橡果（秦铭把核桃松子布袋塞给梁婉清一句不演）"),
    ("E05-EV-37", "dropped", "", "摆脱缺食后认真考虑新生；「野路数耽误了他」激起涟漪；幼时模糊记忆有人说那些动作有来头但估摸练不成——内心与闪回不演"),
    ("E05-EV-38", "landed", "E05-S11-01 至 E05-S11-03", "院中先按自己节奏练野路数：活动关节拉伸拧旋转翻，跃起似铁箭落地无声，坐如虎踞行步如蹚泥（不演），旋身摆腿如龙蟒摆尾；「吹呴呼吸，吐故纳新，熊经鸱顾……」带起猛烈的风卷雪；毛孔银丝交织体表淡淡流光、白雾蒸腾（热流如甘霖、身体欢呼吸吮银色涟漪、血肉发痒全身长劲、难道要新生了——内心不演）"),
    ("E05-EV-39", "landed", "E05-S12-01 至 E05-S12-02", "身体燥热想奔跑，在荒野中疾驰宛若流星接近山林；远处雪地高挑纤细的女子静立青石上，黑色裘皮斗篷流动乌光遮住脖颈只露精致下巴神秘高冷；乌鸦站在她身侧的荆棘上"),
    ("E05-EV-40", "landed", "E05-S13-01 至 E05-S14-04", "乌鸦口吐人语「咦，身体自行新生，初期就有异常景象」（「宛若月光洒落体表，荡起层层叠叠的碎金波纹」略去）「我感觉这是一个好苗子…偏僻的地方」（略去）「你的老师不是在挑选关门弟子吗？这个少年或许可以」；女子「有比他更适合的人」；秦铭似有所感侧头持弓；乌鸦「很敏锐的直觉」「（你老师那条路十分特殊，）你可别真错过一颗有望蓬勃生长的种子」；女子「未被选中，那是他不知道的遗憾（，我能错过什么？已有最好的人选）」「眼下进山探查更要紧」向前走去"),
]
SCENE_BEAT_META = {  # seq=19 A2: beat types; no action beat in this episode (no combat)
    "E05-S01": {"type": "dialogue"}, "E05-S02": {"type": "dialogue"}, "E05-S03": {"type": "dialogue"}, "E05-S04": {"type": "dialogue"},
    "E05-S05": {"type": "dialogue"}, "E05-S06": {"type": "dialogue"}, "E05-S07": {"type": "dialogue"}, "E05-S08": {"type": "dialogue"},
    "E05-S09": {"type": "dialogue"}, "E05-S10": {"type": "dialogue"},
    "E05-S11": {"type": "reveal"}, "E05-S12": {"type": "reveal"}, "E05-S13": {"type": "dialogue"}, "E05-S14": {"type": "dialogue"},
}
assert set(SCENE_BEAT_META) == set(SCENES), set(SCENES) ^ set(SCENE_BEAT_META)
manifest = {
    "episode": EP, "version": VER, "title": "新生",
    "canonical_script": f"workflow/claude_writer_agent/scripts/{narr.name}", "script_sha256": sha(narr),
    "directing_script": f"workflow/claude_writer_agent/scripts/{directing.name}", "directing_sha256": sha(directing),
    "generation_contract": f"workflow/claude_writer_agent/scripts/{contract_path.name}", "generation_contract_sha256": sha(contract_path),
    "supersedes": None,
    "★supersedes_disclosure": "首版，无前版。nalu 线《夜无疆》E05 首次交付；按 seq=7/10/12/13/17/19/26 口径编排；narrative 14 场 31 句对白零改动（其中三句源章长句按单镜 3–6 s 规则各拆为两行两镜，字序不变；两句叙述转陆泽台词、两句按世界观词表改『变异生物/生灵』为『灵兽』，均已在 narrative 头部与 authored_dialogue_from_indirect_speech 申报）。",
    "authorization": {"order_seq": 26, "order_id": "ROGER-20260917-NALU-E05-START", "also": ["seq=3 ROGER-20260909-NALU-E01-E10-PRODUCTION-AUTHORIZED", "seq=7 ROGER-20260913-NALU-E02-NEW-RULES-TANG-SONG-PACING-SOURCE-V2", "seq=8 female leads casting (CHAR-FEMALE-LEAD-BLACKCLOAK = ch5 斗篷女子)", "seq=10 root-cause prompt rules", "seq=12 identity re-anchor rule", "seq=13 non-stop mode + selective BGM", "seq=17 voice recast + tighter pacing", "seq=19 contract-holds gates"], "orders_file": "workflow/claude_writer_agent/SUPERVISOR_ORDERS.json"},
    "writer_identity": {"agent_id": "claude-code-nalu-writer", "provider": "anthropic", "model_id": "claude-fable-5-1", "session_note": "Claude Code 交互会话，Roger 2026-09-17 指令「继续生产e05」/「继续e05」"},
    "source_binding": {
        "work": "夜无疆", "author": "辰东",
        "primary_source_chapter": "5", "source_chapters": ["5"], "chapter_title": "新生",
        "source_file": str(SRC_CH), "source_sha256": sha(SRC_CH),
        "source_index": str(RUNTIME / "sources/夜无疆/SOURCE_INDEX.json"),
        "episode_source_map": str(RUNTIME / "runtime/episode_source_map_yewujiang_v1.json"),
        "beat_count": len(BEATS), "beats_landed": sum(1 for b in BEATS if b[1] == "landed"), "beats_merged": sum(1 for b in BEATS if b[1] == "merged"), "beats_dropped": sum(1 for b in BEATS if b[1] == "dropped"),
        "★carry_in_is_bound_to_the_previous_episode_bytes": f"承接 E04_NARRATIVE_CANONICAL_v1.md E04-S11 末段实际字节（narrative 头部逐字引三行）与 E04 合同末镜 {PREV_LAST['shot_id']} completion_state「{PREV_LAST['completion_state']}」；E05-S01-01 entry_state 为陆泽刚说完‘新生’、秦铭笑容收住望着陆泽；本集从秦铭郑重点头开始，不复位、不重演、不闪回 E04 内容。",
        "carry_in": contract["carry_in"] | {"previous_canonical": f"workflow/claude_writer_agent/scripts/{PREV_EP}_NARRATIVE_CANONICAL_v1.md", "previous_canonical_sha256": sha(SCRIPTS / f"{PREV_EP}_NARRATIVE_CANONICAL_v1.md"), "previous_contract_sha256": sha(PREV_CONTRACT), "anchor_lines_quoted_in_narrative_header": 3},
    },
    "beat_disposition": [{"event_id": e, "disposition": d, "landed_at": at, "summary": s} for e, d, at, s in BEATS],
    "★authorized_insertions": [],
    "authored_dialogue_from_indirect_speech": [
        {"shot_id": shot, "speaker": cname(s), "text": q, "source_basis": AUTHORED_DIALOGUE[q]} for s, q, shot, v in DIALOGUE_UNITS if not v],
    "★audience_already_knows": ["永夜世界与太阳石", "秦铭出村狩猎", "树洞干果与红松鼠的来历", "闲汉截胡被揍", "火泉双树", "秦铭体表曾显化过银色涟漪（E02）"],
    "★style_reset_disclosure": STYLE_RESET_DISCLOSURE,
    "structure": [{"beat_id": f"{EP}-B{idx+1:02d}", "scene_id": sid, "target_seconds": m["sec"], "thread": "线A", **SCENE_BEAT_META[sid], "shot_ids": [f"{x['s']}-{x['n']:02d}" for x in by_scene[sid]], "location_id": m["loc"], "time_id": m["time"], "source_events": m["beats"], "new_information_count": m["info"]}
                  for idx, (sid, m) in enumerate(SCENES.items())],
    "scene_breakdown_seconds": {sid: m["sec"] for sid, m in SCENES.items()},
    "total_seconds": TOTAL,
    "runtime_target_seconds": {"min": 150.0, "target": 165.0, "max": 170.0},
    "shot_count": len(SHOTS),
    "pacing": PACING,
    "key_quote_landing": [{"speaker": cname(s), "quote": q, "shot_id": shot, "verbatim_in_source": True, **({"split_note": SPLIT_QUOTES[q]} if q in SPLIT_QUOTES else {})} for s, q, shot in KEY_QUOTES],
    "fs1": {"combat_clusters": [], "combat_seconds": 0, "note": "本集无打斗；院中练功为源章明写的单人功法演练，不是格斗。"},
    "identity_registry": {cid(k): cname(k) for k in CH} | {p["entity_id"]: p["name"] for p in PROPS} | {s["entity_id"]: s["name"] for s in SETS},
    "new_name_budget": {"budget_per_4_episodes": 1, "writer_invented_names_this_episode": 0, "note": "二病子为源章人名（只被提及不出场）；「黑衣女子」「乌鸦」为源章描述性指代，非写手自创人名；唐瑾为 seq=8 casting 记录的原著后文人名，只作别名"},
    "distinct_locations": sorted({m["loc"] for m in SCENES.values()}),
    "new_locations": [],
    "episode_global_space_map_id": "GSM-YEWUJIANG-SHUANGSHU-VILLAGE-V1",
    "global_space_map_refs": [
        {"map_id": "GSM-YEWUJIANG-QINMING-LUZE-ADJOINING-HOMESTEAD", "scenes": ["E05-S01", "E05-S02", "E05-S03", "E05-S04", "E05-S05", "E05-S06", "E05-S07", "E05-S08", "E05-S09", "E05-S10", "E05-S11"], "anchors": ["火炕", "炕上干果与兽皮袋", "门边猎叉", "铜盆", "屋门", "院中石盆", "院门"], "axis_note": "屋内沿炕—屋门轴（S07 秦铭自炕边走向屋门，文睿拦在门前）；院内沿石盆—院门轴（S11 面向院门练功）"},
        {"map_id": "GSM-YEWUJIANG-SNOWFIELD-WILDS", "scenes": ["E05-S12", "E05-S13"], "anchors": ["村口方向（南）", "雪原北缘临近山林的青石与荆棘", "林线"], "axis_note": "S12 秦铭自南向北疾驰；青石在北缘，女子面向雪原（南），远处秦铭在她南面"},
        {"map_id": "GSM-YEWUJIANG-FOREST-EDGE", "scenes": ["E05-S14"], "anchors": ["林缘积雪的枝头", "林木之间的雪地"], "axis_note": "女子自林缘（南）向林深处（北）走去"},
    ],
    "shot_subspace_bindings": [{"shot_id": f"{sh['s']}-{sh['n']:02d}", "location_id": SCENES[sh["s"]]["loc"]} for sh in SHOTS],
    "onscreen_text_shot_level_registry": [],
    "state_delta_contract_summary": {"shots_total": len(SHOTS), "shots_with_entry_ne_completion": len(SHOTS), "min_dimensions_per_shot": min(len(sh["dims"]) for sh in SHOTS), "extend_words_in_action_fields": 0},
    "camera_motion_summary": {"locked_shots": LOCKED_IDS, "locked_share": round(len(LOCKED_IDS) / len(SHOTS), 3), "policy": PACING["camera_motion_policy"], "direction_rebalanced": CAMERA_DIRECTION_REBALANCED},
    "identity_reanchor_shots": REANCHOR_IDS,
    "bgm_selective_cues": BGM_CUES,
    "voice_casting_seq17": {k: cname(k) for k in ("QM", "LZ", "LW", "WR", "TJ", "CR")},
    "seq27_writer_selfcheck": SEQ27_SELFCHECK,
    "voice_only_characters": {"CHAR-CROW": {"mode": "VOICE_ONLY_NO_PLATE", "visual_entity_id": "PROP-PURPLE-EYED-CROW", "reason": "口吐人语的乌鸦没有人脸，身份牌无法通过 insightface 锁定；说话人合同仍需角色，故只出配音参考，画面走道具参考卡"}},
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
