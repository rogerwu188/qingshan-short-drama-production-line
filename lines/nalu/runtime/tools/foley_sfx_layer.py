#!/usr/bin/env python3
"""foley_sfx_layer.py — free sound-effects (foley) bus for the S7 final mix, keyed to the generation contract.

Line owner 2026-11-23 (option approved): "a free licensed foley library keyed to verbs in the contract
(blade, footsteps, coins, crowd), engineering time only".  No provider call, no paid generation.

Library
  A small curated CC0 pack (Kenney "RPG sounds" via OpenGameArt + Freesound clips whose licence is
  Creative Commons 0; per-clip source, author and licence in ``configs/FOLEY_LIBRARY_CC0_V1.json``).
  The pack is NOT vendored: it is a release asset of this repository, pinned by size + sha256 in that
  config, and every extracted clip is pinned by its own sha256.  ``ensure_library`` downloads it once into
  ``<RUNTIME_ROOT>/runtime/assets/foley/<pack_id>/`` (or ``NALU_FOLEY_DIR``), verifies, and caches.  Any
  failure (offline, bad digest, missing clip) is FAIL-OPEN: the clips that verify are used, the rest are
  skipped, and with no usable clip the episode ships exactly the mix it had before (status recorded).

Mapping (per video unit → its editorial shots)
  Contract text is scanned with a zh/en/ja/ko keyword lexicon (``LEXICON``): authored ``prompt_spec.sound.sfx``
  first, then ``action.contact_point`` / ``force_feedback`` / ``primary_action`` / ``body_action`` /
  ``physical_causality``, ``blocking``, ``completion_state``, prop names; ``performance.emotion`` feeds the
  heartbeat / stinger events only.  A negation just before a keyword ("no", "not", 不/没/未, 無, 안/못)
  suppresses it.  Each scene gets at most two AMBIENCE BED layers (weather + place) from
  ``scene_states`` (location_id, weather, time_id, ambient_life), ``audio_contract.ambient_by_scene`` and
  ``prompt_spec.sound.ambience`` (``BED_LEXICON``); interiors without a match get no bed (the synthetic
  room tone of final_cut_audio_bed already covers them).

Placement
  Shot spans inside a unit are proportional to the shots' ``target_seconds``.  Event time = authored beat
  offset when the contract carries one (``sound.sfx[].at_s|offset_s``, ``action.beats[].t|at_s``); else
  the action onset AFTER the shot's dialogue (end of the last line window in the shot + 0.12 s) when that
  leaves room, else shot start + min(0.35 s, 25 %).  Several events in one shot are staggered 0.22 s;
  at most ``MAX_EVENTS_PER_SHOT`` spots per shot; heartbeat / stinger / thunder at most twice per episode.
  Variation: a seeded picker never repeats the same clip back-to-back for an event; walking footsteps are
  composed from single steps with timing / gain jitter.

Levels (BS.1770 K-weighted, measured here on each clip)
  ambience beds −30 LUFS (band −32…−28) under dialogue, ducked up to 4 dB more under speech;
  spot SFX −20…−15 LUFS by event class (soft / medium / hard), ducked under speech by the native-dialogue
  envelope (up to 12 dB) and by ≥ 10 dB inside line windows, 5 ms fade-in, 40–150 ms fade-out;
  each event is scaled down if it would lift the summed programme above ``PEAK_CEIL_DBFS``.  The final
  programme gain / loudness check of final_cut_audio_bed still runs after the sum.

Switch: ``NALU_SFX`` (default ON; ``0/off/false/no`` disables).  ``NALU_SFX_FETCH=0`` forbids the download.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

import numpy as np

SCHEMA = "nalu.foley_sfx_layer.v1"
SR = 48000
CONFIG_PATH = Path(__file__).resolve().parents[1] / "configs" / "FOLEY_LIBRARY_CC0_V1.json"
ALLOWED_PACK_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
MAX_PACK_BYTES = 40 * 1024 * 1024
DOWNLOAD_TIMEOUT_S = 90

BED_TARGET_LUFS = -30.0
BED_DUCK_MAX_DB = 4.0
BED_FADE_S = 1.5
BED_LOOP_XFADE_S = 2.0
SPOT_DUCK_MAX_DB = 12.0
SPOT_WINDOW_DUCK_DB = 10.0
DUCK_THRESHOLD_DBFS = -32.0
DUCK_ATTACK_S = 0.08
DUCK_RELEASE_S = 0.45
PEAK_CEIL_DBFS = -2.0
MAX_EVENTS_PER_SHOT = 3
STAGGER_S = 0.22
SAME_EVENT_MIN_GAP_S = 0.5
EPISODE_CAPS = {"heartbeat": 2, "stinger": 2, "thunder": 2, "riser": 1}

SOFT, MEDIUM, HARD = -20.0, -18.0, -15.0
#: spot event → level class (LUFS), max length (s), fade-out (s); "steps" composes single steps
EVENT_RULES: dict[str, dict[str, Any]] = {
    "footsteps_indoor": {"lufs": SOFT, "max_s": 0.6, "fade_s": 0.04, "steps": (4, 0.48)},
    "footsteps_outdoor": {"lufs": SOFT, "max_s": 2.4, "fade_s": 0.15},
    "footsteps_snow": {"lufs": SOFT, "max_s": 2.4, "fade_s": 0.15},
    "footsteps_heels": {"lufs": SOFT, "max_s": 2.4, "fade_s": 0.15},
    "running": {"lufs": MEDIUM, "max_s": 2.2, "fade_s": 0.15},
    "door_open": {"lufs": MEDIUM, "max_s": 1.6, "fade_s": 0.1},
    "door_close": {"lufs": MEDIUM, "max_s": 1.2, "fade_s": 0.08},
    "knock": {"lufs": MEDIUM, "max_s": 1.8, "fade_s": 0.08},
    "cloth": {"lufs": SOFT, "max_s": 0.9, "fade_s": 0.08},
    "blade_draw": {"lufs": MEDIUM, "max_s": 1.4, "fade_s": 0.1},
    "blade_clash": {"lufs": HARD, "max_s": 1.6, "fade_s": 0.12},
    "punch": {"lufs": HARD, "max_s": 0.8, "fade_s": 0.06},
    "slap": {"lufs": HARD, "max_s": 0.8, "fade_s": 0.06},
    "body_fall": {"lufs": HARD, "max_s": 1.4, "fade_s": 0.1},
    "cup": {"lufs": SOFT, "max_s": 0.8, "fade_s": 0.06},
    "glass_break": {"lufs": HARD, "max_s": 2.0, "fade_s": 0.15},
    "paper": {"lufs": SOFT, "max_s": 1.0, "fade_s": 0.08},
    "coins": {"lufs": SOFT, "max_s": 1.2, "fade_s": 0.1},
    "phone_notify": {"lufs": MEDIUM, "max_s": 1.5, "fade_s": 0.08},
    "phone_vibrate": {"lufs": SOFT, "max_s": 1.6, "fade_s": 0.08},
    "car_pass": {"lufs": MEDIUM, "max_s": 4.5, "fade_s": 0.4},
    "car_door": {"lufs": MEDIUM, "max_s": 1.0, "fade_s": 0.08},
    "horse_gallop": {"lufs": MEDIUM, "max_s": 3.5, "fade_s": 0.4},
    "horse_neigh": {"lufs": MEDIUM, "max_s": 1.8, "fade_s": 0.15},
    "magic_whoosh": {"lufs": MEDIUM, "max_s": 1.8, "fade_s": 0.15},
    "magic_impact": {"lufs": HARD, "max_s": 2.0, "fade_s": 0.2},
    "whoosh": {"lufs": MEDIUM, "max_s": 1.0, "fade_s": 0.08},
    "heartbeat": {"lufs": SOFT, "max_s": 4.0, "fade_s": 0.4},
    "stinger": {"lufs": HARD, "max_s": 3.0, "fade_s": 0.6},
    "riser": {"lufs": MEDIUM, "max_s": 3.0, "fade_s": 0.2},
    "thunder": {"lufs": MEDIUM, "max_s": 5.0, "fade_s": 0.8},
}
BED_EVENTS = ("amb_rain", "amb_wind", "amb_crowd_indoor", "amb_crowd_outdoor", "amb_office", "amb_city",
              "amb_fire", "amb_insects", "amb_birds")
WEATHER_BEDS = ("amb_rain", "amb_wind")

# ----------------------------------------------------------------------------- lexicon
# en patterns are matched case-insensitively with a leading word boundary (stems: "walk" ⊂ walks/walked);
# zh/ja/ko patterns are plain regex substrings.  Order inside an event does not matter.
LEXICON: dict[str, dict[str, tuple[str, ...]]] = {
    "footsteps": {
        "en": ("walk", "step", "stride", "pace", "approach", "enter", "comes? in", "strolls?", "tiptoe", "heads? (?:to|toward)",
               r"backs? (?:away|off)", "retreat", r"leads? (?:\w+ ){0,3}(?:into|out|through|to)"),
        "zh": ("走[向进来近去过到出入]", "迈步", "踱步", "缓步", "快步", "步入", "走近", "进门", "来到", "离开", "上前", "后退", "退后", "押着", "带着[^，。]{0,4}走"),
        "ja": ("歩", "近づ", "入って", "立ち去"),
        "ko": ("걷", "걸어", "다가", "들어오", "들어가"),
    },
    "footsteps_heels": {"en": ("high heels?", "heels click"), "zh": ("高跟",), "ja": ("ハイヒール",), "ko": ("하이힐",)},
    "running": {
        "en": ("run", "rush", "flee", "dash", "sprint", "chase", "races? "),
        "zh": ("跑", "奔", "逃", "冲[向进出过上]", "追[赶上]"),
        "ja": ("走って", "走り", "駆け", "逃げ"),
        "ko": ("달리", "뛰어", "도망"),
    },
    "door_open": {
        "en": (r"(?:open|push|throw|swing|fling)\w*\s+(?:\w+\s+){0,2}doors?", r"doors?\s+(?:\w+\s+){0,2}(?:open|swing)"),
        "zh": ("推门", "开门", "推开[^，。]{0,3}门", "门[^，。]{0,2}被?推开", "破门", "门开"),
        "ja": ("(?:ドア|扉|戸)を開", "(?:ドア|扉|戸)が開"),
        "ko": ("문을 열", "문이 열"),
    },
    "door_close": {
        "en": (r"(?:close|shut|slam)\w*\s+(?:\w+\s+){0,2}doors?", r"doors?\s+(?:\w+\s+){0,2}(?:close|shut|slam)"),
        "zh": ("关门", "关上[^，。]{0,3}门", "摔门", "门[^，。]{0,2}关上", "合上门"),
        "ja": ("(?:ドア|扉|戸)を閉", "(?:ドア|扉|戸)が閉"),
        "ko": ("문을 닫", "문이 닫"),
    },
    "knock": {"en": ("knock",), "zh": ("敲门", "叩门", "敲了敲"), "ja": ("ノック", "戸を叩"), "ko": ("노크", "문을 두드")},
    "cloth": {
        "en": ("bows?", "kneel", "rises", "stands? up", "sits? down", "turns", "turned", "grab", "tugs?", "adjust",
               "robe", "sleeve", "cloak", "embrace", "hugs?", "shrug", "clutch", "pulls? (?:him|her)", "drags?", "twists?",
               "handkerchief", "binds?", "raises? (?:both|his|her) (?:hands|arms)"),
        "zh": ("起身", "站起", "坐下", "跪", "拱手", "作揖", "行礼", "转身", "抓住", "拉住", "揪住", "衣袖", "拂袖",
               "披风", "衣襟", "抱住", "拥入", "整理衣", "拖", "捆", "绑", "手帕", "绣帕", "帕子"),
        "ja": ("立ち上が", "座", "跪", "振り向", "お辞儀", "袖", "抱き"),
        "ko": ("일어나", "앉", "무릎", "돌아서", "소매", "껴안", "붙잡"),
    },
    "blade_draw": {
        "en": (r"draw\w*\s+(?:\w+\s+){0,2}(?:sword|blade|knife|dagger|saber|sabre)", "unsheath", r"(?:sword|blade)\s+(?:is\s+)?drawn"),
        "zh": ("拔剑", "拔刀", "出鞘", "抽出[^，。]{0,2}[剑刀匕]", "亮剑", "拔出[^，。]{0,2}[剑刀匕]"),
        "ja": ("抜刀", "(?:剣|刀)を抜"),
        "ko": ("칼을 뽑", "검을 뽑", "칼을 빼"),
    },
    "blade_clash": {
        "en": ("clash", "parr(?:y|ies|ied)", r"(?:swords?|blades?)\s+(?:\w+\s+){0,2}(?:strike|meet|cross|lock|ring)",
               "slash", "swordfight", "blocks? the (?:blade|sword|strike)", "duel"),
        "zh": ("交锋", "格挡", "刀剑", "剑锋", "挥剑", "砍", "劈", "斩", "刺向", "过招", "兵刃"),
        "ja": ("斬", "剣戟", "切りかか", "鍔迫り"),
        "ko": ("칼싸움", "막아내", "베어", "검을 휘두"),
    },
    "punch": {
        "en": ("punch", r"kick(?:s|ed)?\b", "strikes? (?:him|her|them|the)", r"hits? (?:him|her|them)", "fist"),
        "zh": ("一拳", "出拳", "挥拳", "拳头", "揍", "殴打", "踢", "一脚", "击中", "打中", "重击"),
        "ja": ("殴", "パンチ", "蹴"),
        "ko": ("주먹", "때리", "발로 차", "걷어차"),
    },
    "slap": {"en": ("slap",), "zh": ("耳光", "巴掌", "掌掴", "扇了", "扇[他她你]"), "ja": ("平手打ち", "ビンタ"), "ko": ("뺨", "따귀")},
    "body_fall": {
        "en": (r"(?<!night )(?<!silence )(?<!darkness )(?<!snow )(?<!rain )(?<!dusk )falls? (?:down|over|backwards?|forwards?|to the|onto|off|from|hard)",
               "collapse", r"drops? to (?:his|her|their|the) (?:knees|floor|ground)", r"knock(?:s|ed)? (?:\w+ )?down", r"hits? the (?:floor|ground)", "topple", "faint", "slumps?"),
        "zh": ("倒地", "摔倒", "跌倒", "栽倒", "倒下", "昏倒", "瘫倒", "跌坐", "摔在地"),
        "ja": ("倒れ", "崩れ落"),
        "ko": ("쓰러", "넘어지"),
    },
    "cup": {
        "en": ("teacup", r"cups?\b", r"glass(?:es)?\b(?! (?:shatter|break))", "goblet", r"bowls?\b", r"mugs?\b", "toast", "pours? (?:tea|wine)", "sips?"),
        "zh": ("茶杯", "酒杯", "茶盏", "举杯", "斟茶", "倒茶", "敬酒", "喝茶", "饮酒", "放下杯", "碗"),
        "ja": ("湯呑", "茶碗", "杯", "グラス", "乾杯"),
        "ko": ("찻잔", "술잔", "컵", "건배"),
    },
    "glass_break": {
        "en": ("shatter", r"smash\w*\s+(?:\w+\s+){0,2}(?:cup|glass|bottle|vase|bowl|jar)", r"break\w*\s+(?:\w+\s+){0,2}(?:cup|glass|bottle|vase|bowl|jar)"),
        "zh": ("摔碎", "打碎", "碎裂", "砸碎", "摔杯", "粉碎", "碎了一地"),
        "ja": ("割れ", "砕け"),
        "ko": ("깨지", "깨뜨", "산산조각"),
    },
    "paper": {
        "en": (r"papers?\b", r"letters?\b", "scroll", "ledger", "register", "document", r"pages?\b", "envelope", "roster",
               "contract", r"books?\b", r"notes?\b", r"maps?\b", "portrait"),
        "zh": ("纸", "书信", "信件", "信封", "来信", "密信", "密函", "卷轴", "名册", "账本", "册子", "文书", "契约", "地图",
               "翻开", "翻阅", "翻书", "告示", "画像"),
        "ja": ("紙", "手紙", "巻物", "帳簿", "書類", "名簿"),
        "ko": ("종이", "편지", "두루마리", "장부", "서류", "명부"),
    },
    "coins": {
        "en": (r"coins?\b", "silver", "money", "purse", r"pays?\b", "paid", "tael", "gold pieces?", "cash", "bribe"),
        "zh": ("铜钱", "银子", "银两", "银票", "钱袋", "金锭", "元宝", "赏钱", "付钱", "掏出[^，。]{0,4}钱", "给钱", "打赏", "碎银"),
        "ja": ("小判", "銭", "金貨", "財布"),
        "ko": ("동전", "은자", "돈주머니", "엽전"),
    },
    "phone_notify": {
        "en": (r"phones?\s+(?:\w+\s+){0,1}(?:buzz|ring|chime|light|ding)", r"(?:text|message|notification)s?\s+(?:\w+\s+){0,1}(?:arrive|pop|come|ping)",
               "notification", "incoming call"),
        "zh": ("手机[^，。]{0,2}响", "消息提示", "收到[^，。]{0,4}(?:消息|短信|微信)", "来电", "手机屏幕亮", "提示音"),
        "ja": ("着信", "通知", "メッセージが届"),
        "ko": ("알림", "문자가 오", "메시지가 도착", "전화가 울"),
    },
    "phone_vibrate": {"en": ("vibrat",), "zh": ("震动", "振动"), "ja": ("振動", "バイブ"), "ko": ("진동",)},
    "car_pass": {
        "en": (r"cars?\s+(?:\w+\s+){0,1}(?:pull|drive|arrive|speed|screech|pass)", r"drives? (?:off|away|up|past)", "engine roar", "traffic passes"),
        "zh": ("汽车", "轿车", "开车", "驶来", "驶过", "驶离", "刹车", "车子[^，。]{0,2}停"),
        "ja": ("車が", "運転", "ブレーキ"),
        "ko": ("자동차", "차가 ", "운전", "브레이크"),
    },
    "car_door": {"en": ("car door",), "zh": ("车门",), "ja": ("車のドア",), "ko": ("차 문", "차문")},
    "horse_gallop": {
        "en": ("gallop", r"horses?\b", "hooves", r"rides? (?:in|up|off|away|out)", "on horseback"),
        "zh": ("马蹄", "骑马", "策马", "纵马", "马背", "马车", "战马", "快马", "疾驰"),
        "ja": ("馬", "蹄"),
        "ko": ("말을 타", "말발굽", "마차"),
    },
    "horse_neigh": {"en": ("neigh", "whinn"), "zh": ("嘶鸣", "马嘶"), "ja": ("いななき", "嘶"), "ko": ("울음소리를 내는 말", "히힝")},
    "magic_whoosh": {
        "en": ("spell", "magic", r"\bqi\b", "aura", "talisman", "rune", "spiritual power", "cultivat", "glows? with"),
        "zh": ("灵力", "真气", "内力", "法术", "法力", "符咒", "符箓", "剑气", "施法", "结印", "灵气", "法阵", "阵法", "掌风", "御剑"),
        "ja": ("魔法", "術を", "結界", "霊力", "気を"),
        "ko": ("마법", "주문을", "기운", "영력", "결계"),
    },
    "magic_impact": {
        "en": ("blast", "shockwave", "explod", "explosion", r"bursts?\b"),
        "zh": ("轰", "爆", "冲击", "震飞", "炸开", "气浪"),
        "ja": ("爆発", "衝撃"),
        "ko": ("폭발", "충격파"),
    },
    "whoosh": {
        "en": (r"swings?\b", "dodge", "leap", r"jumps?\b", "somersault", "backflip", "lunge", "whirl", "swipe", r"throws?\b", "hurls?"),
        "zh": ("闪身", "闪避", "闪开", "挥", "跃", "掠", "翻身", "飞身", "腾空", "扑向", "甩", "掷", "扔"),
        "ja": ("かわ", "跳", "飛び", "投げ"),
        "ko": ("휘두르", "피하", "뛰어오르", "던지"),
    },
    "heartbeat": {
        "en": (r"fear(?:s|ful|ed)?\b", "afraid", "terrified", "panic", "dread", "heart pound", "heartbeat"),
        "zh": ("恐惧", "害怕", "惊恐", "慌张", "心跳", "惊慌", "心慌"),
        "ja": ("恐怖", "怯え", "ドキドキ", "心臓"),
        "ko": ("두려", "공포", "심장", "겁에"),
    },
    "stinger": {
        "en": (r"reveal(?:s|ed)?\b", "realizes", "stunned", "shocked", "gasps?", "freezes", "the truth"),
        "zh": ("震惊", "愣住", "惊愕", "大惊", "骇然", "揭穿", "真相", "瞳孔[^，。]{0,2}(?:收缩|骤缩|一缩|放大)", "如遭雷击"),
        "ja": ("驚愕", "愕然", "凍りつ"),
        "ko": ("경악", "충격을 받", "얼어붙"),
    },
    "riser": {"en": ("standoff", "tension builds?", "killing intent"), "zh": ("杀气", "气氛凝固", "对峙", "剑拔弩张"),
              "ja": ("殺気", "睨み合"), "ko": ("살기", "대치")},
    "thunder": {"en": ("thunder", "lightning"), "zh": ("雷声", "雷鸣", "闪电", "惊雷", "打雷"), "ja": ("雷", "稲妻"), "ko": ("천둥", "번개")},
}
#: lexicon event → library event (footsteps resolve by interior/exterior/snow at placement time)
EVENT_ALIASES = {"footsteps": None}
#: emotion strings (performance.emotion / dialogue emotion) feeding heartbeat / stinger only
EMOTION_EVENTS = ("heartbeat", "stinger")

BED_LEXICON: dict[str, dict[str, tuple[str, ...]]] = {
    "amb_rain": {"en": ("rain", "storm", "downpour", "drizzle"), "zh": ("雨",), "ja": ("雨",), "ko": ("비가", "빗")},
    "amb_wind": {"en": ("wind", "snow", "blizzard", "gale", "cliff", "desert"), "zh": ("风", "雪"), "ja": ("風", "吹雪", "雪"), "ko": ("바람", "눈보라")},
    "amb_crowd_indoor": {
        "en": ("teahouse", "tavern", r"\binn\b", "restaurant", r"\bbar\b", "banquet", "brothel", "casino", "canteen", "cafe", r"\bpub\b", "feast"),
        "zh": ("茶楼", "茶馆", "酒楼", "客栈", "饭馆", "酒馆", "宴", "青楼", "红楼", "赌坊", "餐厅", "酒吧", "茶肆"),
        "ja": ("酒場", "宿屋", "料亭", "宴会", "居酒屋"),
        "ko": ("객잔", "주막", "식당", "연회"),
    },
    "amb_crowd_outdoor": {
        "en": ("market", "street", r"\bfair\b", "square", "plaza", "bazaar", "crowd", "town", "festival"),
        "zh": ("集市", "街", "市集", "人群", "广场", "闹市", "庙会", "城门", "围观"),
        "ja": ("市場", "通り", "広場", "祭"),
        "ko": ("시장", "거리", "광장", "군중"),
    },
    "amb_office": {"en": ("office", "company", "corporate", "meeting room", "lobby"), "zh": ("办公室", "公司", "会议室", "写字楼"),
                   "ja": ("オフィス", "会社", "会議室"), "ko": ("사무실", "회사", "회의실")},
    "amb_city": {"en": ("city", "traffic", "downtown", "highway", "parking"), "zh": ("城市", "马路", "车流", "都市", "停车场"),
                 "ja": ("都会", "交差点", "駐車場"), "ko": ("도시", "도로", "교통")},
    "amb_fire": {"en": ("fireplace", "hearth", "campfire", "bonfire", "torch", "forge", "burning", "stove", "blaze"),
                 "zh": ("篝火", "火堆", "炉", "火盆", "火把", "燃烧", "火光"), "ja": ("焚き火", "炎", "暖炉"), "ko": ("모닥불", "불길", "화로")},
    "amb_insects": {"en": ("cricket", "cicada", "insect"), "zh": ("虫", "蝉", "蛐蛐"), "ja": ("虫", "蝉"), "ko": ("벌레", "귀뚜라미", "매미")},
    "amb_birds": {
        "en": ("forest", "woods", "bamboo", "garden", "park", "field", "meadow", "mountain", "village", "courtyard", "valley", "river", "birds?"),
        "zh": ("林", "竹", "花园", "园", "田", "山", "村", "院", "河", "溪", "鸟"),
        "ja": ("森", "竹", "庭", "村", "山", "鳥"),
        "ko": ("숲", "대나무", "정원", "마을", "산", "새"),
    },
}
NIGHT_WORDS = re.compile(r"night|midnight|evening|dusk|夜|晚|深夜|黄昏|夕|밤|저녁", re.I)
INTERIOR_WORDS = re.compile(r"\bINT\b|INT[-_ ]|ROOM|HALL|HOUSE|CHAMBER|CABIN|OFFICE|TEAHOUSE|TAVERN|INN\b|SHOP|PALACE|TEMPLE|"
                            r"STUDY|BEDROOM|KITCHEN|CELL|室|屋|房|楼|殿|堂|厅|馆|店|宫|部屋|館|방|실|관", re.I)
EXTERIOR_WORDS = re.compile(r"\bEXT\b|EXT[-_ ]|STREET|FOREST|ROAD|FIELD|MOUNTAIN|MARKET|SQUARE|GATE|COURTYARD|GARDEN|RIVER|"
                            r"VILLAGE|BAMBOO|CLIFF|BRIDGE|PARK|街|林|山|田|院|园|河|桥|村|竹|외부|거리|숲", re.I)
PRIVATE_ROOM_WORDS = re.compile(r"BEDROOM|ROOM|CHAMBER|STUDY|BOUDOIR|CELL|卧房|房间|闺房|书房|厢房|内室|寝|部屋|寝室|침실|방", re.I)
SNOW_WORDS = re.compile(r"snow|雪|눈보라|吹雪", re.I)
NEGATION_EN = re.compile(r"\b(?:no|not|never|without|don't|doesn't|didn't|nor|neither)\b[^.;,]{0,14}$", re.I)
NEGATION_CJK = re.compile(r"[不没未無无別别勿안못非]")


# ----------------------------------------------------------------------------- switches / io helpers
def enabled(env: dict[str, str] | None = None) -> bool:
    value = str((env if env is not None else os.environ).get("NALU_SFX", "1")).strip().lower()
    return value not in {"0", "off", "false", "no", "disabled"}


def fetch_allowed(env: dict[str, str] | None = None) -> bool:
    env = env if env is not None else os.environ
    if str(env.get("NALU_SFX_FETCH", "1")).strip().lower() in {"0", "off", "false", "no"}:
        return False
    return not env.get("PYTEST_CURRENT_TEST")  # offline tests never reach the network


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def db_to_lin(db: float) -> float:
    return 10.0 ** (db / 20.0)


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    """The pinned library manifest (``NALU_FOLEY_MANIFEST`` overrides the repository config)."""
    return json.loads(Path(path or os.environ.get("NALU_FOLEY_MANIFEST") or CONFIG_PATH).read_text(encoding="utf-8"))


def default_cache_dir(manifest: dict[str, Any]) -> Path:
    explicit = os.environ.get("NALU_FOLEY_DIR")
    if explicit:
        return Path(explicit)
    try:
        import nalu_paths as _np  # noqa: PLC0415 — runtime layout, absent in some test harnesses
        base = Path(_np.RUNTIME_DIR) / "assets" / "foley"
    except Exception:  # pragma: no cover - fallback outside the runtime layout
        base = Path.home() / ".cache" / "nalu" / "foley"
    return base / str(manifest.get("pack_id") or "foley")


# ----------------------------------------------------------------------------- library delivery (fail-open)
def verify_library(lib_dir: Path, manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Clips whose file exists under lib_dir with the pinned sha256; plus the reasons for the rest."""
    ok: list[dict[str, Any]] = []
    problems: list[str] = []
    for clip in manifest.get("clips") or []:
        rel = PurePosixPath(str(clip.get("file") or ""))
        if rel.is_absolute() or ".." in rel.parts or not rel.parts:
            problems.append(f"CLIP_PATH_INVALID:{clip.get('clip_id')}")
            continue
        path = Path(lib_dir) / Path(*rel.parts)
        if not path.is_file():
            problems.append(f"CLIP_MISSING:{clip.get('clip_id')}")
            continue
        if str(clip.get("sha256") or "") and sha256_file(path) != str(clip["sha256"]):
            problems.append(f"CLIP_SHA_MISMATCH:{clip.get('clip_id')}")
            continue
        ok.append({**clip, "path": str(path)})
    return ok, problems


def _download(url: str, expected_size: int) -> bytes:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_PACK_HOSTS:
        raise RuntimeError(f"PACK_URL_NOT_ALLOWED:{url}")
    request = urllib.request.Request(url, headers={"User-Agent": "nalu-foley-sfx/1"})
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as response:  # noqa: S310 - https github only
        body = response.read(min(expected_size, MAX_PACK_BYTES) + 1)
    if len(body) != expected_size:
        raise RuntimeError(f"PACK_SIZE_MISMATCH:{len(body)}!={expected_size}")
    return body


def install_pack(archive: bytes, manifest: dict[str, Any], lib_dir: Path) -> None:
    """Extract ONLY the manifest's clip files (+ licence texts) from a verified pack into lib_dir (atomic)."""
    wanted = {str(c["file"]): str(c.get("sha256") or "") for c in manifest.get("clips") or []}
    extras = {str(x) for x in (manifest.get("pack") or {}).get("extra_files") or []}
    lib_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".foley_staging_", dir=str(lib_dir.parent)))
    try:
        with tempfile.TemporaryFile() as handle:
            handle.write(archive)
            handle.seek(0)
            with zipfile.ZipFile(handle) as zf:
                for name in zf.namelist():
                    if name not in wanted and name not in extras:
                        continue
                    rel = PurePosixPath(name)
                    if rel.is_absolute() or ".." in rel.parts:
                        continue
                    data = zf.read(name)
                    if wanted.get(name) and hashlib.sha256(data).hexdigest() != wanted[name]:
                        raise RuntimeError(f"PACK_MEMBER_SHA_MISMATCH:{name}")
                    target = staging / Path(*rel.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
        if lib_dir.exists():
            shutil.rmtree(lib_dir)
        staging.replace(lib_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def ensure_library(manifest: dict[str, Any] | None = None, lib_dir: Path | None = None, *,
                   allow_fetch: bool | None = None, fetcher=_download) -> dict[str, Any]:
    """{status, dir, clips:[verified clip rows], problems}.  Never raises."""
    try:
        manifest = manifest if manifest is not None else load_manifest()
    except Exception as exc:  # noqa: BLE001
        return {"status": "MANIFEST_UNREADABLE", "dir": None, "clips": [], "problems": [repr(exc)[:300]]}
    lib_dir = Path(lib_dir) if lib_dir else default_cache_dir(manifest)
    clips, problems = verify_library(lib_dir, manifest)
    total = len(manifest.get("clips") or [])
    if total and len(clips) == total:
        return {"status": "READY", "dir": str(lib_dir), "clips": clips, "problems": []}
    allow_fetch = fetch_allowed() if allow_fetch is None else allow_fetch
    pack = manifest.get("pack") or {}
    fetch_note: list[str] = []
    if allow_fetch and pack.get("url") and pack.get("sha256") and pack.get("size_bytes"):
        try:
            body = fetcher(str(pack["url"]), int(pack["size_bytes"]))
            if hashlib.sha256(body).hexdigest() != str(pack["sha256"]):
                raise RuntimeError("PACK_SHA_MISMATCH")
            install_pack(body, manifest, lib_dir)
            clips, problems = verify_library(lib_dir, manifest)
            if len(clips) == total:
                return {"status": "READY_FETCHED", "dir": str(lib_dir), "clips": clips, "problems": []}
        except Exception as exc:  # noqa: BLE001 - fail-open
            fetch_note.append(f"FETCH_FAILED:{str(exc)[:200]}")
    elif not allow_fetch:
        fetch_note.append("FETCH_DISABLED")
    status = "PARTIAL" if clips else "LIBRARY_MISSING"
    return {"status": status, "dir": str(lib_dir), "clips": clips, "problems": (fetch_note + problems)[:40]}


# ----------------------------------------------------------------------------- loudness (BS.1770 K-weighting)
_K1 = (np.array([1.53512485958697, -2.69169618940638, 1.19839281085285]), np.array([1.0, -1.69065929318241, 0.73248077421585]))
_K2 = (np.array([1.0, -2.0, 1.0]), np.array([1.0, -1.99004745483398, 0.99007225036621]))


def _k_weight(x: np.ndarray) -> np.ndarray:
    from scipy.signal import lfilter
    y = lfilter(_K1[0], _K1[1], x, axis=0)
    return lfilter(_K2[0], _K2[1], y, axis=0)


def loudness_lufs(x: np.ndarray, *, block_s: float = 0.4, gated: bool = True) -> float | None:
    """Gated loudness of a (n,) or (n, ch) signal.  gated=True: BS.1770 integrated (400 ms, 75 % overlap,
    −70 / −10 gates); gated=False: 'active' loudness for short spots (100 ms blocks within 20 dB of the
    loudest block).  None for silence."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    if len(x) == 0:
        return None
    y = _k_weight(x)
    n = max(1, int(block_s * SR))
    hop = max(1, n // 4)
    if len(y) < n:
        y = np.concatenate([y, np.zeros((n - len(y), y.shape[1]))])
    starts = np.arange(0, len(y) - n + 1, hop)
    ms = np.array([float(np.sum(np.mean(y[s:s + n] ** 2, axis=0))) for s in starts])
    ms = ms[ms > 0]
    if not len(ms):
        return None
    lk = -0.691 + 10.0 * np.log10(ms)
    if gated:
        keep = ms[lk > -70.0]
        if not len(keep):
            return None
        rel = -0.691 + 10.0 * math.log10(float(np.mean(keep))) - 10.0
        keep = ms[(lk > -70.0) & (lk > rel)]
    else:
        keep = ms[lk >= float(lk.max()) - 20.0]
    return float(-0.691 + 10.0 * math.log10(float(np.mean(keep))))


# ----------------------------------------------------------------------------- lexicon matching
def _compile() -> dict[str, list[tuple[str, re.Pattern[str]]]]:
    out: dict[str, list[tuple[str, re.Pattern[str]]]] = {}
    for table in (LEXICON, BED_LEXICON):
        for event, langs in table.items():
            rows = out.setdefault(event, [])
            for lang, patterns in langs.items():
                for pat in patterns:
                    rows.append((lang, re.compile((r"\b" + pat) if lang == "en" else pat, re.I if lang == "en" else 0)))
    return out


_COMPILED = _compile()


def _negated(text: str, start: int, lang: str) -> bool:
    before = text[max(0, start - 24):start]
    if lang == "en":
        return bool(NEGATION_EN.search(before))
    return bool(NEGATION_CJK.search(before[-2:]))


def match_events(text: str, events: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """[{event, lang, keyword, pos}] for every lexicon event found (first non-negated hit per event),
    ordered by position in the text."""
    hits: list[dict[str, Any]] = []
    if not text:
        return hits
    for event in (events if events is not None else LEXICON.keys()):
        best = None
        for lang, rx in _COMPILED.get(event, []):
            for m in rx.finditer(text):
                if _negated(text, m.start(), lang):
                    continue
                if best is None or m.start() < best["pos"]:
                    best = {"event": event, "lang": lang, "keyword": m.group(0).strip(), "pos": m.start()}
                break
        if best:
            hits.append(best)
    return sorted(hits, key=lambda h: h["pos"])


# ----------------------------------------------------------------------------- contract reading
def _s(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ; ".join(_s(v) for v in value)
    if isinstance(value, dict):
        return " ; ".join(_s(v) for v in value.values())
    return str(value)


def shot_texts(shot: dict[str, Any]) -> list[tuple[str, str]]:
    """(field, text) in priority order."""
    spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
    action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
    perf = action.get("performance") if isinstance(action.get("performance"), dict) else {}
    props = spec.get("props") or shot.get("props") or []
    prop_text = _s([p.get("name") or p.get("prop_id") or p.get("description") if isinstance(p, dict) else p for p in props])
    rows = [
        ("contact_point", _s(action.get("contact_point"))),
        ("force_feedback", _s(action.get("force_feedback"))),
        ("primary_action", _s(action.get("primary_action"))),
        ("body_action", _s(perf.get("body_action"))),
        ("physical_causality", _s(action.get("physical_causality"))),
        ("blocking", _s(shot.get("blocking"))),
        ("completion_state", _s(shot.get("completion_state"))),
        ("props", prop_text),
    ]
    return [(f, t) for f, t in rows if t.strip()]


def authored_sfx(shot: dict[str, Any]) -> list[dict[str, Any]]:
    spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
    sound = spec.get("sound") if isinstance(spec.get("sound"), dict) else {}
    rows = sound.get("sfx") or shot.get("sfx") or []
    out = []
    for row in rows if isinstance(rows, list) else [rows]:
        if isinstance(row, dict):
            text = _s(row.get("event") or row.get("name") or row.get("description") or row.get("sfx"))
            at = row.get("at_s", row.get("offset_s"))
        else:
            text, at = _s(row), None
        if text.strip():
            out.append({"text": text, "at_s": float(at) if isinstance(at, (int, float)) else None})
    return out


def shot_beats(shot: dict[str, Any]) -> list[dict[str, Any]]:
    spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
    action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
    out = []
    for row in action.get("beats") or shot.get("beats") or []:
        if not isinstance(row, dict):
            continue
        at = row.get("t", row.get("at_s", row.get("offset_s")))
        text = _s(row.get("text") or row.get("action") or row.get("description"))
        if isinstance(at, (int, float)) and text.strip():
            out.append({"at_s": float(at), "text": text})
    return out


def shot_emotion(shot: dict[str, Any]) -> str:
    spec = shot.get("prompt_spec") if isinstance(shot.get("prompt_spec"), dict) else {}
    action = spec.get("action") if isinstance(spec.get("action"), dict) else {}
    perf = action.get("performance") if isinstance(action.get("performance"), dict) else {}
    return _s(perf.get("emotion"))


def scene_profile(scene: dict[str, Any], contract: dict[str, Any], shots: list[dict[str, Any]]) -> dict[str, Any]:
    """{interior, night, snow, beds:[{event, trigger}]} for one scene."""
    sid = str(scene.get("scene_id") or "")
    loc = _s(scene.get("location_id")).replace("-", " ").replace("_", " ")
    audio = contract.get("audio_contract") if isinstance(contract.get("audio_contract"), dict) else {}
    amb_scene = _s((audio.get("ambient_by_scene") or {}).get(sid)) if isinstance(audio.get("ambient_by_scene"), dict) else ""
    shot_amb = " ; ".join(_s(((s.get("prompt_spec") or {}).get("sound") or {}).get("ambience")) for s in shots
                          if isinstance((s.get("prompt_spec") or {}).get("sound"), dict))
    weather = _s(scene.get("weather"))
    time_id = _s(scene.get("time_id")) + " " + _s(scene.get("lighting"))
    ambient_life = _s(scene.get("ambient_life"))
    interior = bool(INTERIOR_WORDS.search(loc)) and not re.search(r"\bEXT\b|EXT[-_ ]", loc, re.I)
    if not interior and not EXTERIOR_WORDS.search(loc) and INTERIOR_WORDS.search(loc + " " + amb_scene):
        interior = True
    night = bool(NIGHT_WORDS.search(time_id))
    beds: list[dict[str, Any]] = []
    # weather layer: weather field + authored ambience strings only (never the location name)
    for event in WEATHER_BEDS:
        hit = match_events(weather, [event]) or (match_events(shot_amb, [event]) if not interior else [])
        if hit:
            beds.append({"event": event, "trigger": {"field": "weather" if match_events(weather, [event]) else "sound.ambience",
                                                     "lang": hit[0]["lang"], "keyword": hit[0]["keyword"]}})
            break
    # place layer: location id first, then authored ambience text; time of day turns birds into insects
    place = None
    for source, text in (("location_id", loc), ("ambient_by_scene", amb_scene), ("sound.ambience", shot_amb),
                         ("ambient_life", ambient_life)):
        for event in ("amb_crowd_indoor", "amb_crowd_outdoor", "amb_office", "amb_city", "amb_fire", "amb_insects", "amb_birds"):
            if interior and event in ("amb_birds", "amb_insects", "amb_crowd_outdoor", "amb_city"):
                continue
            if not interior and event in ("amb_crowd_indoor", "amb_office"):
                continue
            if event in ("amb_crowd_indoor", "amb_office") and PRIVATE_ROOM_WORDS.search(loc):
                continue  # a private room inside an inn / office building is not the busy hall
            hit = match_events(text, [event])
            if hit:
                place = {"event": event, "trigger": {"field": source, "lang": hit[0]["lang"], "keyword": hit[0]["keyword"]}}
                break
        if place:
            break
    if place and place["event"] == "amb_birds" and night:
        place = {"event": "amb_insects", "trigger": {**place["trigger"], "night": True}}
    if place:
        beds.append(place)
    snow = bool(SNOW_WORDS.search(weather + " " + loc))
    return {"scene_id": sid, "location_id": scene.get("location_id"), "interior": interior, "night": night, "snow": snow,
            "beds": beds}


# ----------------------------------------------------------------------------- picker / clip cache
class ClipPicker:
    """Seeded, never the same clip twice in a row for an event (when the event has ≥ 2 clips)."""

    def __init__(self, clips: list[dict[str, Any]], seed: int):
        self.by_event: dict[str, list[dict[str, Any]]] = {}
        for clip in sorted(clips, key=lambda c: str(c.get("clip_id"))):
            self.by_event.setdefault(str(clip.get("event")), []).append(clip)
        self.rng = np.random.default_rng(seed)
        self.last: dict[str, str] = {}

    def has(self, event: str) -> bool:
        return bool(self.by_event.get(event))

    def pick(self, event: str) -> dict[str, Any] | None:
        pool = self.by_event.get(event) or []
        if not pool:
            return None
        choices = [c for c in pool if c["clip_id"] != self.last.get(event)] or pool
        clip = choices[int(self.rng.integers(0, len(choices)))]
        self.last[event] = clip["clip_id"]
        return clip


def decode_clip(path: str | Path) -> np.ndarray:
    """(n, 2) float32 at 48 kHz.  48 kHz PCM16 WAV is read natively; anything else through ffmpeg."""
    if str(path).lower().endswith(".wav"):
        import wave  # noqa: PLC0415
        try:
            with wave.open(str(path), "rb") as w:
                if w.getframerate() == SR and w.getsampwidth() == 2:
                    ch = w.getnchannels()
                    x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768.0
                    x = x.reshape(-1, ch)
                    return np.repeat(x, 2, axis=1) if ch == 1 else x[:, :2].copy()
        except wave.Error:
            pass
    res = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=False)
    if res.returncode:
        raise RuntimeError("ffmpeg decode failed: " + res.stderr.decode("utf-8", "replace")[-500:])
    return np.frombuffer(res.stdout, dtype=np.float32).reshape(-1, 2).copy()


# ----------------------------------------------------------------------------- planning
def unit_shot_map(segments: list[dict[str, Any]], grouping: dict[str, Any] | None,
                  contract: dict[str, Any]) -> dict[str, list[str]]:
    shots = [str(s.get("shot_id")) for s in contract.get("shots") or [] if isinstance(s, dict)]
    out: dict[str, list[str]] = {}
    for unit in (grouping or {}).get("units") or []:
        ids = [s if isinstance(s, str) else str(s.get("shot_id")) for s in
               (unit.get("editorial_shot_ids") or unit.get("shots") or unit.get("shot_ids") or [])]
        if ids:
            out[str(unit.get("unit_id"))] = ids
    if not out and len(segments) == len(shots):  # 1:1 editorial units (no grouping plan at hand)
        out = {str(seg["unit_id"]): [shot] for seg, shot in zip(segments, shots)}
    return out


def shot_spans(segments: list[dict[str, Any]], unit_shots: dict[str, list[str]],
               shot_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """[{shot_id, unit_id, scene_id, start, end}] on the release timeline."""
    rows: list[dict[str, Any]] = []
    for seg in segments:
        uid = str(seg["unit_id"])
        a, b = float(seg["output_start"]), float(seg["output_end"])
        ids = [s for s in unit_shots.get(uid, []) if s in shot_by_id]
        if not ids or b <= a:
            continue
        weights = [max(float(shot_by_id[s].get("target_seconds") or 0.0), 0.1) for s in ids]
        total = sum(weights)
        cur = a
        for sid, w in zip(ids, weights):
            end = cur + (b - a) * w / total
            rows.append({"shot_id": sid, "unit_id": uid, "scene_id": str(shot_by_id[sid].get("scene_id") or ""),
                         "start": round(cur, 4), "end": round(end, 4)})
            cur = end
    return rows


def speech_in(windows: list[tuple[float, float]], a: float, b: float) -> list[tuple[float, float]]:
    return [(max(s, a), min(e, b)) for s, e in windows if e > a and s < b]


def energy_speech_windows(native: np.ndarray, *, threshold_dbfs: float = -35.0, frame_s: float = 0.05,
                          bridge_s: float = 0.3, min_s: float = 0.25) -> list[tuple[float, float]]:
    """Fallback speech windows from the native track's energy (no line windows at hand)."""
    mono = native.mean(axis=1) if native.ndim == 2 else native
    hop = int(frame_s * SR)
    k = len(mono) // hop
    if k == 0:
        return []
    rms = 20 * np.log10(np.sqrt(np.mean(mono[: k * hop].reshape(k, hop).astype(np.float64) ** 2, axis=1)) + 1e-12)
    rows: list[list[float]] = []
    for i in np.flatnonzero(rms > threshold_dbfs):
        s, e = i * frame_s, (i + 1) * frame_s
        if rows and s - rows[-1][1] <= bridge_s:
            rows[-1][1] = e
        else:
            rows.append([s, e])
    return [(round(s, 3), round(e, 3)) for s, e in rows if e - s >= min_s]


def onset_after_dialogue(span: dict[str, Any], windows: list[tuple[float, float]]) -> tuple[float, str]:
    a, b = span["start"], span["end"]
    speech = speech_in(windows, a, b)
    if speech:
        last_end = max(e for _, e in speech)
        if last_end + 0.12 <= b - 0.35:
            return last_end + 0.12, "AFTER_DIALOGUE"
        return a + 0.15, "UNDER_DIALOGUE_DUCKED"
    return a + min(0.35, 0.25 * (b - a)), "SHOT_ONSET"


def resolve_footsteps(event: str, profile: dict[str, Any]) -> str:
    if event != "footsteps":
        return event
    if profile.get("snow"):
        return "footsteps_snow"
    return "footsteps_indoor" if profile.get("interior") else "footsteps_outdoor"


def plan_events(contract: dict[str, Any], spans: list[dict[str, Any]], windows: list[tuple[float, float]],
                profiles: dict[str, dict[str, Any]], available: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(events, skipped).  Pure: no audio, no library files — only which events exist (``available``)."""
    shot_by_id = {str(s.get("shot_id")): s for s in contract.get("shots") or [] if isinstance(s, dict)}
    audio = contract.get("audio_contract") if isinstance(contract.get("audio_contract"), dict) else {}
    line_emotion = {}
    for row in audio.get("dialogue_units") or []:
        if isinstance(row, dict):
            line_emotion.setdefault(str(row.get("shot_id")), []).append(_s(row.get("emotion")))
    events: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    episode_counts: dict[str, int] = {}
    last_time: dict[str, float] = {}
    for span in spans:
        shot = shot_by_id.get(span["shot_id"]) or {}
        profile = profiles.get(span["scene_id"], {})
        found: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in authored_sfx(shot):
            for hit in match_events(row["text"]) or ([{"event": row["text"].strip(), "lang": "id", "keyword": row["text"].strip(), "pos": 0}]
                                                     if row["text"].strip() in EVENT_RULES else []):
                if hit["event"] not in seen:
                    seen.add(hit["event"])
                    found.append({**hit, "field": "sound.sfx", "at_s": row["at_s"]})
        for beat in shot_beats(shot):
            for hit in match_events(beat["text"]):
                if hit["event"] not in seen:
                    seen.add(hit["event"])
                    found.append({**hit, "field": "action.beats", "at_s": beat["at_s"]})
        for field, text in shot_texts(shot):
            for hit in match_events(text):
                if hit["event"] not in seen:
                    seen.add(hit["event"])
                    found.append({**hit, "field": field, "at_s": None})
        emo_text = " ; ".join([shot_emotion(shot)] + line_emotion.get(span["shot_id"], []))
        for hit in match_events(emo_text, EMOTION_EVENTS):
            if hit["event"] not in seen:
                seen.add(hit["event"])
                found.append({**hit, "field": "emotion", "at_s": None})
        # heels override generic footsteps; running overrides walking
        if "footsteps_heels" in seen or "running" in seen:
            found = [h for h in found if h["event"] != "footsteps"]
        onset, onset_rule = onset_after_dialogue(span, windows)
        k = 0
        for hit in found:
            event = resolve_footsteps(hit["event"], profile)
            reason = None
            if event not in EVENT_RULES:
                reason = "NOT_A_SPOT_EVENT"
            elif event not in available:
                reason = "NO_CLIP_IN_LIBRARY"
            elif k >= MAX_EVENTS_PER_SHOT:
                reason = "SHOT_EVENT_CAP"
            elif episode_counts.get(event, 0) >= EPISODE_CAPS.get(event, 10 ** 6):
                reason = "EPISODE_CAP"
            if hit["at_s"] is not None:
                t, rule = span["start"] + max(0.0, float(hit["at_s"])), "AUTHORED_OFFSET"
            else:
                t, rule = onset + STAGGER_S * k, onset_rule
            if reason is None and t >= span["end"] - 0.08:
                reason = "NO_ROOM_IN_SHOT"
            if reason is None and t - last_time.get(event, -1e9) < SAME_EVENT_MIN_GAP_S:
                reason = "SAME_EVENT_TOO_CLOSE"
            row = {"event": event, "lexicon_event": hit["event"], "shot_id": span["shot_id"], "unit_id": span["unit_id"],
                   "scene_id": span["scene_id"], "t": round(t, 3), "placement": rule,
                   "trigger": {"field": hit["field"], "lang": hit["lang"], "keyword": hit["keyword"]}}
            if reason:
                skipped.append({**row, "reason": reason})
                continue
            events.append(row)
            episode_counts[event] = episode_counts.get(event, 0) + 1
            last_time[event] = t
            k += 1
    return events, skipped


def plan_beds(spans: list[dict[str, Any]], profiles: dict[str, dict[str, Any]], total_s: float,
              available: set[str]) -> list[dict[str, Any]]:
    """[{event, scene_id, start, end, trigger}] — scene spans on the timeline, one row per layer."""
    scene_spans: list[dict[str, Any]] = []
    for span in spans:
        if scene_spans and scene_spans[-1]["scene_id"] == span["scene_id"]:
            scene_spans[-1]["end"] = span["end"]
        else:
            scene_spans.append({"scene_id": span["scene_id"], "start": span["start"], "end": span["end"]})
    if scene_spans:
        scene_spans[-1]["end"] = max(scene_spans[-1]["end"], total_s)
    beds = []
    for row in scene_spans:
        for layer in profiles.get(row["scene_id"], {}).get("beds", []):
            if layer["event"] in available:
                beds.append({"event": layer["event"], "scene_id": row["scene_id"], "start": round(row["start"], 3),
                             "end": round(row["end"], 3), "trigger": layer["trigger"]})
    return beds


# ----------------------------------------------------------------------------- rendering
def envelope_db(mono: np.ndarray, *, hop_ms: int = 5) -> tuple[np.ndarray, int]:
    hop = SR * hop_ms // 1000
    n = len(mono) // hop
    if n == 0:
        return np.full(1, -120.0), hop
    peaks = np.max(np.abs(mono[: n * hop].reshape(n, hop)), axis=1)
    a_att = math.exp(-hop * math.log(10.0) / (DUCK_ATTACK_S * SR))
    a_rel = math.exp(-hop * math.log(10.0) / (DUCK_RELEASE_S * SR))
    env = np.empty(n)
    cur = 0.0
    for i in range(n):
        p = peaks[i]
        cur = a_att * cur + (1 - a_att) * p if p > cur else a_rel * cur + (1 - a_rel) * p
        env[i] = cur
    return 20.0 * np.log10(env + 1e-9), hop


def duck_curve(native_mono: np.ndarray, windows: list[tuple[float, float]], max_db: float,
               window_db: float) -> np.ndarray:
    """Per-sample linear gain: envelope duck (speech level over −32 dBFS) and a fixed duck inside line windows
    (80 ms ramps), whichever is deeper."""
    env, hop = envelope_db(native_mono)
    duck = -np.minimum(np.maximum(env - DUCK_THRESHOLD_DBFS, 0.0) * 0.95, max_db)
    per = np.repeat(duck, hop)
    n = len(native_mono)
    per = np.concatenate([per, np.full(max(0, n - len(per)), per[-1] if len(per) else 0.0)])[:n]
    if window_db > 0 and windows:
        win = np.zeros(n)
        for s, e in windows:
            a, b = max(0, int(s * SR)), min(n, int(e * SR))
            if b > a:
                win[a:b] = 1.0
        ramp = int(0.08 * SR)
        if ramp > 1:
            kernel = np.ones(ramp) / ramp
            win = np.clip(np.convolve(win, kernel, mode="same") * 1.0, 0.0, 1.0)
        per = np.minimum(per, -window_db * win)
    return np.power(10.0, per / 20.0).astype(np.float32)


def _fade(x: np.ndarray, fade_in_s: float, fade_out_s: float) -> np.ndarray:
    x = x.copy()
    fi, fo = min(len(x), int(fade_in_s * SR)), min(len(x), int(fade_out_s * SR))
    if fi > 1:
        x[:fi] *= np.linspace(0.0, 1.0, fi)[:, None]
    if fo > 1:
        x[-fo:] *= np.linspace(1.0, 0.0, fo)[:, None]
    return x


def _trim_lead(x: np.ndarray, threshold_db: float = -50.0) -> np.ndarray:
    mono = np.abs(x).max(axis=1)
    idx = np.flatnonzero(mono > db_to_lin(threshold_db))
    return x[max(0, int(idx[0]) - int(0.005 * SR)):] if len(idx) else x


def _loop(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) >= n:
        return x[:n].copy()
    xf = min(int(BED_LOOP_XFADE_S * SR), len(x) // 3)
    out = np.zeros((n, 2), dtype=np.float32)
    out[: len(x)] = x
    pos = len(x)
    up = np.sin(np.linspace(0, math.pi / 2, xf))[:, None] if xf > 1 else None
    while pos < n:
        start = pos - xf if xf > 1 else pos
        take = min(len(x), n - start)
        seg = x[:take].copy()
        if xf > 1:
            m = min(xf, take)
            out[start:start + m] = out[start:start + m] * np.cos(np.linspace(0, math.pi / 2, xf))[:m, None] + seg[:m] * up[:m]
            out[start + m:start + take] = seg[m:take]
        else:
            out[start:start + take] = seg
        pos = start + take
    return out


def _fit_under_ceiling(base: np.ndarray, ev: np.ndarray, ceil: float) -> float:
    """Largest scale in (0, 1] with max|base + s·ev| ≤ ceil (1.0 when it already fits or base alone is over)."""
    if float(np.max(np.abs(base + ev))) <= ceil:
        return 1.0
    if float(np.max(np.abs(base))) >= ceil:
        return 1.0 if float(np.max(np.abs(ev))) < 1e-6 else 0.25
    lo, hi = 0.0, 1.0
    for _ in range(14):
        mid = (lo + hi) / 2
        if float(np.max(np.abs(base + mid * ev))) <= ceil:
            lo = mid
        else:
            hi = mid
    return max(lo, 0.05)


def render_layer(native: np.ndarray, events: list[dict[str, Any]], beds: list[dict[str, Any]], picker: ClipPicker,
                 windows: list[tuple[float, float]], *, base: np.ndarray | None = None, seed: int = 12,
                 decoder=decode_clip) -> tuple[np.ndarray, list[dict[str, Any]], list[dict[str, Any]]]:
    """(sfx stereo (n, 2), placed events, placed beds).  ``base`` = what the SFX sums onto (peak ceiling)."""
    n = len(native)
    native_mono = native.mean(axis=1) if native.ndim == 2 else native
    spot_gain = duck_curve(native_mono, windows, SPOT_DUCK_MAX_DB, SPOT_WINDOW_DUCK_DB)
    bed_gain = duck_curve(native_mono, windows, BED_DUCK_MAX_DB, 0.0)
    rng = np.random.default_rng(seed + 7)
    cache: dict[str, np.ndarray] = {}
    loud_cache: dict[tuple[str, bool], float | None] = {}

    def audio(clip: dict[str, Any]) -> np.ndarray:
        if clip["clip_id"] not in cache:
            cache[clip["clip_id"]] = decoder(clip["path"])
        return cache[clip["clip_id"]]

    def loud(clip: dict[str, Any], x: np.ndarray, gated: bool) -> float | None:
        key = (clip["clip_id"], gated)
        if key not in loud_cache:
            loud_cache[key] = loudness_lufs(x, block_s=0.4 if gated else 0.1, gated=gated)
        return loud_cache[key]

    placed_beds = []
    bed_bus = np.zeros((n, 2), dtype=np.float32)
    for bed in beds:
        clip = picker.pick(bed["event"])
        if clip is None:
            continue
        a = max(0, int((bed["start"] - BED_FADE_S / 2) * SR))
        b = min(n, int((bed["end"] + BED_FADE_S / 2) * SR))
        if b - a < int(0.5 * SR):
            continue
        src = audio(clip)
        lufs = loud(clip, src, True)
        if lufs is None:
            continue
        gain_db = BED_TARGET_LUFS - lufs
        offset = int(rng.integers(0, max(1, len(src) // 2)))
        chunk = _loop(np.concatenate([src[offset:], src[:offset]]), b - a) * db_to_lin(gain_db)
        chunk = _fade(chunk, BED_FADE_S, BED_FADE_S)
        bed_bus[a:b] += chunk.astype(np.float32)
        placed_beds.append({**bed, "clip_id": clip["clip_id"], "clip_lufs": round(lufs, 2), "target_lufs": BED_TARGET_LUFS,
                            "gain_db": round(gain_db, 2)})
    bed_bus *= bed_gain[:, None]

    under = np.asarray(base if base is not None else native, dtype=np.float32)
    if under.ndim == 1:
        under = under[:, None]
    if under.shape[1] == 1:
        under = np.repeat(under, 2, axis=1)
    under = under[:n] + bed_bus            # what each spot sums onto (programme + beds + earlier spots)
    spots = np.zeros((n, 2), dtype=np.float32)
    ceil = db_to_lin(PEAK_CEIL_DBFS)
    placed: list[dict[str, Any]] = []
    for ev in sorted(events, key=lambda e: e["t"]):
        rule = EVENT_RULES[ev["event"]]
        steps = rule.get("steps")
        hits = []
        if steps:
            count, interval = steps
            for i in range(count):
                hits.append((ev["t"] + i * interval + float(rng.uniform(-0.04, 0.04)) if i else ev["t"], float(rng.uniform(-1.5, 1.0))))
        else:
            hits.append((ev["t"], 0.0))
        clips_used, gains = [], []
        for t, jitter_db in hits:
            clip = picker.pick(ev["event"])
            if clip is None:
                break
            src = _trim_lead(audio(clip))[: int(rule["max_s"] * SR)]
            src = _fade(src, 0.005, rule["fade_s"])
            lufs = loud(clip, src, False)
            if lufs is None:
                continue
            gain_db = rule["lufs"] - lufs + jitter_db
            a = int(t * SR)
            if a >= n:
                continue
            seg = (src[: n - a] * db_to_lin(gain_db)) * spot_gain[a:a + min(len(src), n - a), None]
            scale = _fit_under_ceiling(under[a:a + len(seg)] + spots[a:a + len(seg)], seg, ceil)
            seg = seg * scale
            spots[a:a + len(seg)] += seg.astype(np.float32)
            clips_used.append(clip["clip_id"])
            duck_db = 20.0 * math.log10(max(float(np.median(spot_gain[a:a + len(seg)])), 1e-6))
            gains.append({"t": round(t, 3), "clip_id": clip["clip_id"], "clip_lufs": round(lufs, 2), "gain_db": round(gain_db, 2),
                          "duck_db_median": round(duck_db, 1), "peak_scale": round(scale, 3)})
        if clips_used:
            placed.append({**ev, "target_lufs": rule["lufs"], "hits": gains})
    return (bed_bus + spots).astype(np.float32), placed, placed_beds


# ----------------------------------------------------------------------------- top level (the S7 hook)
def build_sfx_layer(native: np.ndarray, segments: list[dict[str, Any]], grouping: dict[str, Any] | None,
                    contract: dict[str, Any], line_windows: list[dict[str, Any]] | None, *,
                    base: np.ndarray | None = None, library: dict[str, Any] | None = None,
                    seed: int = 12, env: dict[str, str] | None = None, decoder=decode_clip) -> tuple[np.ndarray, dict[str, Any]]:
    """The SFX bus for one episode (stereo float32, same length as ``native``) + its record.  Never raises:
    any failure returns silence and a record whose status says why (the mix is then unchanged)."""
    n = len(native)
    silent = np.zeros((n, 2), dtype=np.float32)
    record: dict[str, Any] = {"schema": SCHEMA, "switch": "NALU_SFX", "enabled": enabled(env)}
    if not record["enabled"]:
        return silent, {**record, "status": "DISABLED"}
    try:
        lib = library if library is not None else ensure_library()
        record["library"] = {k: lib.get(k) for k in ("status", "dir", "problems")} | {"clip_count": len(lib.get("clips") or [])}
        clips = lib.get("clips") or []
        if not clips:
            return silent, {**record, "status": "LIBRARY_MISSING"}
        picker = ClipPicker(clips, seed)
        available = set(picker.by_event)
        windows = [(float(w["start"]), float(w["end"])) for w in (line_windows or []) if isinstance(w, dict)
                   and "start" in w and "end" in w]
        record["speech_windows_source"] = "LINE_WINDOWS" if windows else "NATIVE_ENERGY"
        if not windows:
            windows = energy_speech_windows(native)
        shot_by_id = {str(s.get("shot_id")): s for s in contract.get("shots") or [] if isinstance(s, dict)}
        spans = shot_spans(segments, unit_shot_map(segments, grouping, contract), shot_by_id)
        shots_by_scene: dict[str, list[dict[str, Any]]] = {}
        for s in shot_by_id.values():
            shots_by_scene.setdefault(str(s.get("scene_id") or ""), []).append(s)
        profiles = {str(sc.get("scene_id")): scene_profile(sc, contract, shots_by_scene.get(str(sc.get("scene_id")), []))
                    for sc in contract.get("scene_states") or [] if isinstance(sc, dict)}
        events, skipped = plan_events(contract, spans, windows, profiles, available)
        beds = plan_beds(spans, profiles, n / SR, available)
        sfx, placed, placed_beds = render_layer(native, events, beds, picker, windows, base=base, seed=seed, decoder=decoder)
        rms = float(np.sqrt(np.mean(sfx.astype(np.float64) ** 2))) if n else 0.0
        record.update({
            "status": "APPLIED" if (placed or placed_beds) else "NO_EVENTS",
            "levels": {"bed_target_lufs": BED_TARGET_LUFS, "bed_duck_max_db": BED_DUCK_MAX_DB,
                       "spot_lufs": {"soft": SOFT, "medium": MEDIUM, "hard": HARD},
                       "spot_duck_max_db": SPOT_DUCK_MAX_DB, "spot_window_duck_db": SPOT_WINDOW_DUCK_DB,
                       "peak_ceiling_dbfs": PEAK_CEIL_DBFS},
            "shot_spans": len(spans), "scene_profiles": list(profiles.values()),
            "events": placed, "beds": placed_beds, "skipped": skipped,
            "counts": {"events": len(placed), "hits": sum(len(e["hits"]) for e in placed), "beds": len(placed_beds),
                       "skipped": len(skipped)},
            "sfx_rms_dbfs": round(20 * math.log10(max(rms, 1e-12)), 2),
        })
        return sfx.astype(np.float32), record
    except Exception as exc:  # noqa: BLE001 - fail-open: the episode keeps its previous mix
        return silent, {**record, "status": "ERROR_FAIL_OPEN", "error": repr(exc)[:500]}


def record_path_for(report: Path) -> Path:
    name = report.name
    if name.endswith("_AUDIO_BED.json"):
        return report.with_name(name[: -len("_AUDIO_BED.json")] + "_SFX_LAYER.json")
    return report.with_name(report.stem + ".sfx_layer.json")


def write_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)
