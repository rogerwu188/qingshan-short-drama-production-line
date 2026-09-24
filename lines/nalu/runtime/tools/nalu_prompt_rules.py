#!/usr/bin/env python3
"""nalu_prompt_rules — reusable prompt-level guards distilled from real E02 reroll causes
(SUPERVISOR_ORDERS seq=10, 2026-09-14: "导致重做的原因要查出来，后面的提示词要避免，不能重犯同样错误").

Each rule = (trigger on the authored shot) -> (a clause appended to the shot's production action text, or a
BLOCK the builder must restage).  Story/dialogue text is never touched; only the production action field.

| rule          | E02 cause                                                                 |
|---------------|---------------------------------------------------------------------------|
| NO_TEXT       | VU-016: provider burned the spoken line into the frame as subtitles       |
| SOLO_FACE     | VU-020: single-character close-up inside a 4-cast scene got 同行者乙's face |
| NO_BLACK      | VU-020/021: 「极暗/全黑」 rendered as ≥95 %-black frames (black_frame FAIL) |
| MOTION        | VU-010: 3 s no-dialogue hold with only micro-motion (嘴角动/换手)          |
| DLG_TIMING    | VU-029: 12-syllable line in a 4 s shot started at 1.3 s → last syllable cut|
| BG_LOCK       | VU-023: close-up's bokeh background drifted from house interior to snow yard|
| FIRE_COLOR    | VU-002: fire-spring splash rendered cool white                            |
| BASIN_NO_FLAME| VU-006: 铜盆 rendered as a wood fire instead of the sun-stone glow          |
| PROP_SHAPE    | VU-014: food box rendered as a round tub (was a rectangular box)          |
| HAIRPIN       | VU-026: 木簪 rendered as an ornate metal hairpiece                         |
| SILVER_FAINT  | VU-028: 「极淡银光」 rendered as bright glowing rings                        |

apply(shot, ctx) -> (action_text, applied, blocks)
  shot: {"shot_id","sec","size","camera_family","cast":[keys],"action":str,"dialogue":str|None,"entry","exit"}
  ctx:  {"scene_cast": set(keys), "loc": "LOC-…", "cps": float|None, "names": {key: display name},
         "face_desc": {key: str}}
"""
from __future__ import annotations
import re

RULE_VERSION = "nalu_prompt_rules.v1 (seq=10)"

BODY_VERBS = ("走", "跨", "转身", "站起", "起身", "蹲下", "跌", "拖", "俯身", "躺", "坐下", "迎上", "退", "奔", "爬",
              "推开", "扑", "跳", "蹦", "冲", "跑", "翻身", "弯腰", "直起", "踏", "踩空", "扔", "甩", "摆开")
MOVING_CAMERA = {"ARC", "TRACK", "CRANE", "HANDHELD", "ORBIT", "PAN", "TILT"}  # PUSH_IN/LOCKED do not rescue a hold
DARK_WORDS = ("全黑", "极暗", "漆黑", "黑下来", "黑暗", "纯黑")
CLOSE_SIZES = ("特写", "近景", "过肩")

BG_LOCK = {
    "LOC-QINMING-HOUSE-INT": "屋内的土墙、木格糊纸窗、旧木立柜与屋内的橘红余光，绝不出现雪地、院墙、屋檐或天空",
    "LOC-QINMING-YARD-EXT": "夯土压雪的院墙、木板院门与院中石盆里的橘红光",
    "LOC-FIRE-SPRING-EXT": "粗凿青石的石围、火红的池光与雪地",
    "LOC-MOUNTAIN-CREVICE-INT": "地缝的岩壁与碎石",
    # E03 (seq=13) wilds
    "LOC-SNOWFIELD-WILDS-EXT": "齐胸深的雪原、雪面的月色青蓝反光与远处黑压压的林线，绝不出现房屋、院墙或火光",
    "LOC-FOREST-EDGE-EXT": "积雪的光秃树枝、樟子松与白桦的树干和雪地，绝不出现房屋、院墙、石围或天空以外的人造物",
    "LOC-LOW-HILL-TOP-EXT": "矮山顶的雪石、身后黑压压的林木与远处群山的黑影",
}
DARK_LIGHT = {
    "LOC-MOUNTAIN-CREVICE-INT": "从缝口透进的青蓝月光把岩壁与人物照成看得清的深青灰",
    "LOC-QINMING-HOUSE-INT": "屋内的橘红余光照出人物轮廓与器物",
    "LOC-QINMING-YARD-EXT": "雪面的月色青蓝反光照出人物轮廓与院墙",
    "LOC-FIRE-SPRING-EXT": "池中的火红余光照出人物轮廓与石围",
    "LOC-SNOWFIELD-WILDS-EXT": "雪面的月色青蓝反光照出人物轮廓与雪原",
    "LOC-FOREST-EDGE-EXT": "雪地与树干上的月色青蓝反光照出人物轮廓与林木",
    "LOC-LOW-HILL-TOP-EXT": "雪面月色青蓝反光与夜雾深处的朦胧微光照出人物轮廓",
}
DEFAULT_CPS = 4.0
#: SUPERVISOR_ORDERS seq=29 规则 5a (Roger 2026-09-18): 对白镜时长 = 台词时长 + 0.5 s 反应余量，向上取整到 0.5 s；
#: 不再套 5–7 s 模板，也不再加 1.0 s 开口提前量（seq=10 的 lead 1.0 + tail 0.5 由此作废）。
DLG_LEAD_S, DLG_TAIL_S = 0.0, 0.5
DLG_ROUND_S = 0.5


EMOTION_DELIVERY = {
    "calm": "这句台词平稳地说，音量与语速都是这个人物的日常基线，不拔高、不拖长",
    "plead": "这句台词是哀求：比日常说话明显更响、更急、带哭腔和抖音，句尾气息不稳，音量至少高出平时一大截",
    "threat": "这句台词是威胁：压低而有力，字字咬紧、比平时更响更慢，尾音收得干脆",
    "mock": "这句台词是嘲弄：语调上挑、带笑意的轻蔑，比平时略快略响",
    "joy": "这句台词是欢喜：明亮、轻快、比平时响而快，带笑声的气息",
    "fear": "这句台词是恐惧：气短、发颤、突然拔高又收住，比平时明显更响更急",
}


def _creature_in_shot(shot: dict, ctx: dict, text: str = "") -> bool:
    ids = set(str(x) for x in (shot.get("props") or ())) | set(str(x) for x in (shot.get("cast") or ()))
    return any(str(c) in ids for c in (ctx.get("creature_ids") or ()))


PROMPT_MEMORY_TRIGGERS = {
    # action beat: the shot belongs to a beat typed "action" or its state delta carries contact/momentum
    "ACTION_NO_OUTCOME": lambda shot, ctx, text: str(shot.get("beat_type") or "") == "action"
                         or bool({"CONTACT", "MOMENTUM"} & set(shot.get("state_delta_dimensions") or ())),
    # first action of a declared antagonist group
    "ANTAGONIST_NO_MOTIVE": lambda shot, ctx, text: str(shot.get("shot_id")) in set(ctx.get("antagonist_first_action_shots") or ()),
    # a payoff shot of a prop that must show its source
    "PROP_NO_SOURCE": lambda shot, ctx, text: str(shot.get("shot_id")) in set(ctx.get("prop_payoff_shots") or ()),
    # any shot that stages a creature with a card
    "CREATURE_FORM_DRIFT": _creature_in_shot,
}


def _spoken_chars(text: str) -> int:
    return len(re.sub(r"[^一-鿿0-9A-Za-z]", "", text or ""))


def min_dialogue_seconds(text: str, cps: float | None) -> float:
    """seq=29 规则 5a：台词秒数 + 0.5 s，向上取整到 0.5 s（10 字 @5.0 字/秒 → 2.5 s）。"""
    import math
    raw = _spoken_chars(text) / float(cps or DEFAULT_CPS) + DLG_LEAD_S + DLG_TAIL_S
    return math.ceil(raw / DLG_ROUND_S - 1e-9) * DLG_ROUND_S


def apply(shot: dict, ctx: dict) -> tuple[str, list[str], list[str]]:
    act = str(shot.get("action") or "")
    text_all = act + str(shot.get("entry") or "") + str(shot.get("exit") or "")
    size = str(shot.get("size") or "")
    cast = list(shot.get("cast") or [])
    names = ctx.get("names") or {}
    face = ctx.get("face_desc") or {}
    loc = str(ctx.get("loc") or "")
    dlg = shot.get("dialogue")
    dlg_text = ""
    if isinstance(dlg, (list, tuple)) and len(dlg) >= 2:
        dlg_text = str(dlg[1] or "")
    elif isinstance(dlg, str):
        dlg_text = dlg
    clauses, applied, blocks = [], [], []

    if dlg_text:
        clauses.append("台词只在声音里，画面任何位置都不出现字幕、文字或水印"); applied.append("NO_TEXT")
        need = min_dialogue_seconds(dlg_text, ctx.get("cps"))
        # seq=29 规则 5b (Roger 2026-09-18): no "说完后口型闭合、动作保持" — the line ends INTO the next body
        # action the writer names (shot["after_line"]); a shot without one falls back to turning to the listener.
        after = str(shot.get("after_line") or "").strip() or "转向对方"
        clauses.append(f"开口不晚于画面第 0.5 秒，台词在画面结束前说完，说完立即{after}"); applied.append("DLG_TIMING_SEQ29")
        if float(shot.get("sec") or 0) < need:
            blocks.append(f"DLG_TOO_SHORT:{shot.get('shot_id')}:sec={shot.get('sec')}<min={need}")
    else:
        sec = float(shot.get("sec") or 0)
        fam = str(shot.get("camera_family") or "").upper()
        if sec >= 3.0 and not any(v in act for v in BODY_VERBS) and fam not in MOVING_CAMERA:
            blocks.append(f"NO_DIALOGUE_HOLD_WITHOUT_BODY_MOTION:{shot.get('shot_id')}:sec={sec:g}:camera={fam or 'NONE'}")
        applied.append("MOTION_CHECK")

    if len(cast) == 1 and any(k in size for k in CLOSE_SIZES) and len(ctx.get("scene_cast") or ()) > 1:
        k = cast[0]
        clauses.append(f"这个特写的主体只有{names.get(k, k)}一个人的脸（{face.get(k, '')}）；画面边缘若有别人，只能是上一镜延续的位置，绝不把主体换成别人的脸")
        applied.append("SOLO_FACE")

    if any(w in text_all for w in DARK_WORDS):
        clauses.append(f"画面最暗的时刻仍有{DARK_LIGHT.get(loc, '微弱的环境余光照出人物轮廓与环境')}，任何一帧都不是纯黑")
        applied.append("NO_BLACK")

    if any(k in size for k in CLOSE_SIZES) and loc in BG_LOCK:
        clauses.append(f"背景自始至终是{BG_LOCK[loc]}"); applied.append("BG_LOCK")

    if loc == "LOC-FIRE-SPRING-EXT" and any(w in text_all for w in ("池", "火泉", "火光")):
        clauses.append("池面的光与溅起的光全部是火红色，没有冷白或蓝光"); applied.append("FIRE_COLOR")
    if loc == "LOC-QINMING-HOUSE-INT":
        clauses.append("屋内唯一的光是橘红色的暖光，盆里没有木柴也没有明火"); applied.append("BASIN_NO_FLAME")
    if "食盒" in text_all:
        clauses.append("食盒是方形提梁木食盒（不是圆桶）"); applied.append("PROP_SHAPE")
    if "QM" in cast and any(k in size for k in CLOSE_SIZES + ("中近景",)):
        clauses.append("秦铭发髻上是一根素木簪，没有任何金属饰件"); applied.append("HAIRPIN")
    if any(w in text_all for w in ("体表银光", "银光初现", "指缝间银光", "银光流过", "极淡银光")):   # 秦铭's body light, not the crevice's silver web
        clauses.append("银光极淡，不成光环、不刺眼、不照亮周围"); applied.append("SILVER_FAINT")

    # nalu D-74 (E07 28 s, Roger「28s居然是4个人在画面里」): the keyframe had the two declared people and
    # the VIDEO model added two more.  Cause: the shot's action text named 杨永青 (「把目光转向杨永青」) while
    # he was not in this shot's cast, so the prompt's entity lock covered only the declared two and the
    # model materialised the named outsider — plus a companion.  A character named in the action/blocking
    # of a shot he is not cast in must be written as off-screen (「转向画外」), never by name.
    if ctx.get("offscreen_name_strict"):
        staged = {names.get(k, k) for k in cast}
        for key, name in names.items():
            if key in cast or not name:
                continue
            if name in act or name in str(shot.get("blocking") or ""):
                blocks.append(f"OFFSCREEN_CHARACTER_NAMED_IN_ACTION:{shot.get('shot_id')}:{name}"
                              f":cast={sorted(staged)}:改写为「画外」或把他写进 cast")
    # seq=19 (E04 review): emotion → delivery clause.  The line is spoken natively by the video
    # model (no TTS parameters exist), so the emotion can only reach the take as performance text.
    emotion = str(shot.get("emotion") or (ctx.get("emotions") or {}).get(shot.get("shot_id")) or "")
    if dlg_text and emotion:
        prose = EMOTION_DELIVERY.get(emotion)
        if prose is None:
            blocks.append(f"EMOTION_UNKNOWN:{shot.get('shot_id')}:{emotion}")
        else:
            clauses.append(prose); applied.append(f"EMOTION:{emotion}")
    elif dlg_text and ctx.get("emotion_required"):
        blocks.append(f"EMOTION_UNDECLARED:{shot.get('shot_id')}")

    # E08 VU-010/011 cause (2026-09-22): a carded creature the script treats as killed prey was rendered
    # as a live animal standing on its legs and led by the rope, contradicting the kill the dialogue states.
    # The creature card and its locomotion field describe a LIVING animal, so the carcass state has to be
    # said in the prompt.  Only tokens the authored text already contains are clause-able (prop-token guard).
    for tok in ctx.get("dead_prey_tokens") or ():
        if str(tok) and str(tok) in text_all:
            clauses.append(f"{tok}是已被猎杀的死体：侧躺在地上、四肢僵直、头颈低垂、眼睛无神，"
                           f"只能被绳索拖行，绝不站立、行走、被牵着走或有任何自主动作")
            applied.append("DEAD_PREY")

    # seq=19: knowledge failure-memory rows with stage == "prompt" (and only those) are injected as
    # do_not_repeat clauses when the shot matches the row's trigger; the applied ids are recorded.
    for row in ctx.get("failure_memory") or ():
        if str(row.get("stage")) != "prompt":
            continue
        code = str(row.get("failure_code") or "")
        trig = PROMPT_MEMORY_TRIGGERS.get(code)
        if trig and trig(shot, ctx, text_all):
            clauses.append(f"【勿重蹈 {code}】{row.get('do_not_repeat')}")
            applied.append(f"KNOWLEDGE:{row.get('knowledge_id') or code}")

    for tok in ctx.get("prop_tokens") or ():
        if tok not in text_all and any(tok in c for c in clauses):
            blocks.append(f"RULE_CLAUSE_INTRODUCES_PROP_TOKEN:{shot.get('shot_id')}:{tok}")
    if ctx.get("split_columns"):
        # seq=29 规则 7a: the rule clauses are CONSTRAINTS; the caller keeps them in action.constraints
        # and leaves primary_action as the performance text.  Returned as a list in the first slot.
        return clauses, applied, blocks
    if clauses:
        act = act.rstrip("；;。") + "；" + "；".join(clauses)
    return act, applied, blocks
