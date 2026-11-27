#!/usr/bin/env python3
"""Multi-pass video-native final review (line owner 2026-11-20: "既然 gemini 可以'看'视频，需要做的非常细致").

``gemini_video_review.run`` (mode ``multipass``, the default) sends FOUR specialist ``generateContent`` calls in
parallel instead of the single checklist call ("Pass B"), each with its own focused prompt, media settings and JSON
answer, and merges them into the same ``gemini_review.json`` the Codex reviewer, the must-check list, the final fix
round and the knowledge base already read (ids G1.. / S1.., ``item``, ``start``/``end``, ``severity`` ...).

  A  PICTURE / AI ARTEFACTS   720x1280, no audio, fps 2, media_resolution HIGH (~264 tokens / frame instead of 66):
                              faces, eyes, teeth, hands, skin turning glossy / oily / plastic between shots, wet hair,
                              body / limb morphing, objects popping, flicker, the set moving with the actor on a
                              locked-off shot (QA-CAMERA-WOBBLE, 2026-11-21), physics, burned-in text, blur boxes,
                              letterbox.  Local OCR leads + letterbox / skin-sheen / wobble suspects to confirm.
  B  IDENTITY / CONTINUITY    720x1280, no audio, fps 2 (degraded first to 1), HIGH, plus the episode's identity
                              cards as inline images labelled 角色A/B.. (names never sent) and the scene list (scene id
                              + time windows + who is in it): each character vs their card; inside a scene costume
                              colours, hair, accessories, props, light direction / colour temperature, positions;
                              look-alike different characters.
  C  SOUND                    432x768 with audio, fps 1: lip sync, voice consistency / fit (sex, age), wrong speaker,
                              clipped last syllable / no natural pause, loudness jumps, BGM hard starts / stops, SFX,
                              audio artefacts.  The local tail (C2) / music (C6) suspects to confirm or dismiss.
  D  DIRECTOR / CRAFT         432x768 with audio, fps 2: the script beats + shot list (anonymised) and the key items
                              of NALU_CRAFT_STANDARD_v1 (pacing first): beat delivered, shot grammar, pacing per
                              beat, 3-second hook, ending hook, clarity of who / what / why, emotional beat, subtitle
                              readability.  PLAN PARITY (2026-11-23, device 1101 E24: everything shipped although the
                              delivered shots did not match the plan -- wrong locations, reversed roles, invented
                              people, missing beats, 56 s vs 110 s): D also gets each unit's PLANNED action, cast,
                              location, props and dialogue (generation contract + release-timeline window) and
                              answers ``unit_parity`` per unit: delivered YES / PARTIAL / NO with reasons
                              (ROLE_REVERSED, WRONG_LOCATION, MISSING_PERSON, MISSING_PROP, INVENTED_PERSON,
                              MISSING_BEAT ...).  A NO unit becomes a QA-PLAN-MISMATCH finding; the merged record
                              carries ``plan_parity`` (every planned unit, n/m delivered) for the final fix round
                              (P0 NO -> paid redo class PLAN_MISMATCH) and final_cut_shot_plan_parity.
  E  TAIL (2026-11-23)        720x1280 with audio, fps 8 HIGH, only the last 28 s (end card included): out-of-order
                              strings of 1-2 s silent shots, voices where no line is planned, set shake / push-ins on
                              locked shots, in-shot identity morphs, burned text, the ending hook.  Owner: "many
                              problems cannot be seen at 2 frames a second" (ZH E25 / JA E10 endings).  Pass A's
                              preferred step is 3 fps HIGH (was 2).

Local suspects (2026-11-23, E24: Gemini missed burned text and stray voices that local OCR / ASR caught): the OCR
text runs of the evidence pack (model-burned text anywhere in the frame + stacked lines in our subtitle band) are
pass-A suspects (``burned_text``) and the ASR speech heard inside units the plan gives NO dialogue are pass-C
suspects (``stray_voice``) -- each must be CONFIRMED / DISMISSED, not merely read as a lead.

Per-shot checklist (2026-11-21, line owner: "the Gemini final review should be more detailed"): passes A and B
answer ``shot_log`` as one row per measured shot with the classes that shot FAILED (``fail``: [] = every class of
the pass checked and passed), so coverage is systematic rather than free-form; a failed class without its finding
becomes a P3 ``from_checklist`` finding.  Pass B also compares every same-sex pair of characters (``cast_compare``);
a pair judged not distinct without a QA-LOOKALIKE-CAST finding becomes a P2 one with both characters' times.

Models per pass (owner 2026-11-23, E24 A/B: gemini-3.1-pro-preview found 30 picture / story findings vs 19 on
gemini-3.8-flash -- Flash missed burned text and several character / location details -- while the sound pass with
the local ASR suspects was as good on Flash): A, B, D on ``gemini-3.1-pro-preview``, C on ``gemini-3.8-flash``.
``NALU_GEMINI_REVIEW_MODEL_A`` .. ``_D`` override one pass; ``NALU_GEMINI_REVIEW_MODEL`` (or ``--model``) applies
to every pass without its own override.  A Pro pass answered with a 4xx policy / model-unavailable status is
retried once on gemini-3.8-flash (``model_fallback`` in the pass record); each pass records its ``model``.

Budget: ``NALU_GEMINI_REVIEW_BUDGET`` (alias ``NALU_GEMINI_REVIEW_MAX_CREDITS``; default 80.0 since 2026-11-23 -- A at 3 fps + tail pass E --,
review cost is not a concern during the quality-fix period) per episode, split across the passes, each priced at
its own model (Pro: + an expected ~8k thinking tokens per pass, billed as output).  55 runs A, B, D on Pro at their
preferred settings up to ~120 s (estimate ~42 credits at 60 s, ~51 at 110 s); longer episodes step down the
model-aware ladder (pass_ladder).  Every pass is
estimated before anything is sent; while the total is over the cap the lowest-priority pass that can still step
down is degraded (D, then C, then B, then A: fps and media resolution), and when no pass can step down any more the
lowest-priority pass is skipped (D -> C -> B; A last).  The recorded cost is computed from each response's usage.

Authority: ADVISORY, exactly like the single pass: each pass fails open on its own (an error in C leaves A, B, D
intact); the record is OK when at least one pass answered.  Codex verifies every finding.
"""
from __future__ import annotations

import base64
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

SCHEMA_PASSES = "nalu.gemini_video_review.multipass.v1"
MODE_ENV = "NALU_GEMINI_REVIEW_MODE"
#: 80 since 2026-11-23 (owner: "many problems cannot be seen at 2 frames a second"): A at 3 fps + the tail pass E
MAX_CREDITS_DEFAULT = 80.0
BUDGET_ENVS = ("NALU_GEMINI_REVIEW_BUDGET", "NALU_GEMINI_REVIEW_MAX_CREDITS")
PRO_MODEL = "gemini-3.1-pro-preview"
FLASH_MODEL = "gemini-3.8-flash"
MODEL_ENV = "NALU_GEMINI_REVIEW_MODEL"
#: owner 2026-11-23 (E24 A/B): picture, identity and director passes on Pro, sound on Flash
PASS_MODELS: dict[str, str] = {"A": PRO_MODEL, "B": PRO_MODEL, "C": FLASH_MODEL, "D": PRO_MODEL, "E": PRO_MODEL}
#: credits per 1M tokens (input, output incl. thinking) -- HopsAPI list prices (2026-11-23)
MODEL_PRICES: dict[str, tuple[float, float]] = {FLASH_MODEL: (50.25, 251.25), PRO_MODEL: (134.0, 804.0)}
#: thinking tokens a model spends per pass ON TOP of ``expected_out`` (which already holds Flash's ~1.2k).  Pro
#: thinks dynamically (no thinkingBudget sent): E24 2026-11-23 2-7.9k per call, ~8k on a full pass
THINKING_TOKENS: dict[str, int] = {PRO_MODEL: 8000}
#: a Pro pass answered with one of these (policy / permission / model unavailable; HopsAPI 424) is retried once
#: on FALLBACK_MODEL.  401 (key) and 429 / 5xx (retried with backoff) are not model problems.
FALLBACK_MODEL = FLASH_MODEL
FALLBACK_STATUSES = (400, 403, 404, 424, 451)
PASS_IDS = ("A", "B", "C", "D", "E")
#: lowest priority first: degraded first, skipped first
DEGRADE_ORDER = ("D", "C", "E", "B", "A")
#: video tokens per frame by media resolution (measured on HopsAPI gemini-3.8-flash, 2026-11-19/20: 66 default,
#: 264 high), image tokens by resolution (Gemini 3 documentation), audio 25 tokens / s
#: DEFAULT = no mediaResolution sent (video: same 66 tokens / frame as LOW; images: the model's default, high)
VIDEO_TOKENS = {"LOW": 66, "DEFAULT": 66, "HIGH": 264}
IMAGE_TOKENS = {"LOW": 280, "DEFAULT": 1120, "HIGH": 1120}
AUDIO_TOKENS_PER_S = 25
MAX_OUTPUT_TOKENS = 16384
MAX_UPLOAD_BYTES = 14_500_000
MEDIA_RESOLUTION = {"LOW": "MEDIA_RESOLUTION_LOW", "DEFAULT": None, "HIGH": "MEDIA_RESOLUTION_HIGH"}
CARD_MAX_SIDE = 768
MAX_CARDS = 6
LOG_MAX_ROWS = 80
#: HopsAPI / Vertex answers RESOURCE_EXHAUSTED (429) in bursts -- even for a 36-token text request (benchmark
#: 2026-11-20) -- so a 429 and transient 5xx are retried with backoff (~2 min in all), then the pass fails open
RETRY_STATUSES = (0, 429, 500, 502, 503, 504)
RETRY_BACKOFF_S = (8.0, 20.0, 40.0, 60.0)
STAGGER_S = 2.0
#: the whole review must finish (and write its record) inside codex_production.run_gemini_review's 900 s subprocess
#: timeout: each call gets at most the time left, and no retry starts without a minute to spare
DEADLINE_S = 780.0
CALL_TIMEOUT_S = 600.0

#: per pass: label, audio kept, upload scale, ladder of (fps, media resolution) from preferred to cheapest,
#: expected answer + thinking tokens (benchmark 2026-11-20 mean x ~1.3, so the estimate errs high)
PASSES: dict[str, dict[str, Any]] = {
    # 3 fps first (owner 2026-11-23: identity morphs, shake and 1-2 s fragments are not visible at 2 frames a second)
    "A": {"name": "PICTURE_AI_ARTEFACTS", "audio": False, "scale": (720, 1280), "expected_out": 3700,
          "ladder": ((3.0, "HIGH"), (2.0, "HIGH"), (1.5, "HIGH"), (1.0, "HIGH"), (2.0, "LOW"), (1.0, "LOW"))},
    "B": {"name": "IDENTITY_CONTINUITY", "audio": False, "scale": (720, 1280), "expected_out": 4900,
          # dynamic thinking spent 0 tokens on B once (empty card comparison); thinkingLevel "high" ran to the
          # 16k output cap (truncated JSON, 6.9 credits) -- a fixed budget bounds it (Flash only: Pro thinks
          # dynamically, see THINKING_TOKENS)
          "thinking_budget": 3072,
          "ladder": ((2.0, "HIGH"), (1.5, "HIGH"), (1.0, "HIGH"), (2.0, "LOW"), (1.0, "LOW"))},
    "C": {"name": "SOUND", "audio": True, "scale": (432, 768), "expected_out": 3000,
          "ladder": ((2.0, "LOW"), (1.0, "LOW"))},
    # + one unit_parity row per unit (2026-11-23) in place of the craft_summary beat rows: +400 for the "seen" text.
    # The budget split is unchanged: at 100 s A keeps 2 fps HIGH, at 110 s 1.5 fps HIGH (as before plan parity)
    # 2026-11-23: on Pro at the default media resolution (432p, 2 fps), as in the E24 A/B
    "D": {"name": "DIRECTOR_CRAFT", "audio": True, "scale": (432, 768), "expected_out": 2800,
          "ladder": ((2.0, "DEFAULT"), (1.0, "DEFAULT"))},
    # 2026-11-23 (owner, ZH E25 / JA E10): "near the end the camera is strange, no subtitles, people talk nonsense,
    # many very short cuts" -- the last ~25 s held an out-of-order montage of 1.5 s silent units that the 2-fps
    # passes passed.  The tail window (last TAIL_SECONDS of the cut, end card included) at 8 fps, picture + sound.
    "E": {"name": "TAIL_HIGH_FPS", "audio": True, "scale": (720, 1280), "expected_out": 2600, "tail_seconds": 28.0,
          "ladder": ((8.0, "HIGH"), (6.0, "HIGH"), (8.0, "DEFAULT"), (4.0, "DEFAULT"))},
}
TAIL_CLASSES = ("QA-EDIT-FRAGMENT", "QA-WRONG-SPEAKER", "QA-CAMERA-WOBBLE", "QA-IDENTITY-MISMATCH", "QA-BODY-MORPH",
                "QA-FACE-ARTIFACT", "QA-BURNED-TEXT", "QA-DIALOGUE-TAIL-CUT", "CRAFT-ENDING-HOOK", "CRAFT-CLARITY",
                "CRAFT-ACTING-MONOTONY", "QA-PLAN-MISMATCH", "QA-SILENT-MOUTH")

#: class -> (pass, Chinese checklist text).  Existing ids (QA-*, LETTERBOX, LOOK-DRIFT, OTHER) keep their meaning.
CLASS_TEXT: dict[str, tuple[str, str]] = {
    # A -- picture / AI artefacts
    "QA-FACE-ARTIFACT": ("A", "脸部 AI 瑕疵：脸融化/变形/左右不对称/五官漂移；眼睛（视线乱飘、两眼瞳孔或虹膜不一致、眼睛畸形）；"
                              "牙齿/嘴（牙齿糊成一片、嘴型畸形、多一排牙）。"),
    "QA-HAND-ARTIFACT": ("A", "手：手指数量不对（多指/少指）、手指融合或弯折变形、手和物体互相穿透、手凭空出现/消失。"
                              "画框外伸进来一只看不到主人的手/手臂（和画面里的角色握手、拉手、抓手腕、递东西）不是手部瑕疵，"
                              "是多出来的人：报 QA-PLAN-MISMATCH（P1）。"),
    # 2026-11-24 (KO E01 0:32, device ...1437): the face was oily in the shot itself, not only compared with its
    # neighbours -- the drift wording let a consistently oily face pass
    "QA-SKIN-SHEEN-DRIFT": ("A", "皮肤/头发油光：任何一个镜头里人物的脸看起来油亮、出汗、湿漉漉或塑料感反光（额头、鼻梁、脸颊上有"
                                 "白亮的高光块），或头发湿亮、皮肤过度锐化/磨皮——只要剧情没有雨水、汗水、泪水的理由就报，"
                                 "即使前后镜头也一样油（整集都油也要报，写出每个出现的时间点）；同一角色相邻镜头之间突然变油亮"
                                 "也算。P1。"),
    # 2026-11-24 (KO E01 0:39, device ...1437): a man in an office talks and points at the camera with no sound -- the
    # engine muted the voice H3 had generated in a unit with no line, the lips kept moving
    "QA-SILENT-MOUTH": ("A", "嘴动没声音：画面里有人嘴在一张一合、明显在说话（或喃喃自语），但这里听不到他的台词——计划里"
                             "这个单元没有台词（分镜表/逐单元计划），或 silent_mouth 嫌疑点（引擎把模型生成的人声静音了）。"
                             "张嘴惊讶、喘气、咬牙这类不说话的表情不算。P1，写出是谁、哪个时间窗。"),
    "QA-BODY-MORPH": ("A", "身体/四肢变形：肢体扭曲、多出或缺少肢体、身体比例突变、衣服与身体融在一起。"),
    "QA-OBJECT-POP": ("A", "物体凭空出现/消失/变形（道具、家具、饰品在同一镜头内跳变）。"),
    "QA-FLICKER": ("A", "时间闪烁：画面或局部纹理闪动/抖动、首尾帧闪一下。（背景跟着人物整体晃动/果冻扭曲报 QA-CAMERA-WOBBLE。）"),
    # 2026-11-21 (KO E05 on device ...0080): "the camera shakes along with a character's small movements -- the person
    # AND the background move together"
    "QA-CAMERA-WOBBLE": ("A", "镜头随人晃动：本该固定的机位里，人物做小动作（点头、抬手、转身、半步）时整个画面——墙、门框、窗框、"
                              "家具、人物身后的布景——跟着一起平移/摇晃/上下颠/缩放，像手持跟拍；或画面像果冻一样扭曲（直线变弯、"
                              "背景局部蠕动）。判断方法：盯住背景里一条固定的直线或物体（门框、墙角、桌沿）看它相对画框边缘有没有动。"
                              "平滑、单一方向、有动机的运镜不算。每个镜头单独列，写出背景里哪个参照物在动、跟谁的什么动作一起动。"),
    "QA-PHYSICS": ("A", "物理错误：物体悬空、穿模、不合理的运动或重力、液体/布料行为异常。"),
    "QA-BURNED-TEXT": ("A", "画面里视频模型自己烧进去的文字：大号台词字、第二行字幕、乱码字、字幕上下多出的单个大字（片头剧名卡和片尾卡不算）。"
                            "底部出现上下两行相同或几乎相同的字幕（同一句台词叠了两遍）也是这一类：那是模型烧进画面的台词压在我方字幕下面，"
                            "不是 QA-SUBTITLE-WRAP。"
                            "每一段文字（每个短语）出现到消失单独列一条，不要把多段合成一个长时间窗。"),
    # 2026-11-21 (JA-01 anime E04 VU-007): H3 drew the multi-view identity sheet itself as the picture -- reported as
    # CRAFT-SHOT-GRAMMAR "角色设定三视图静态立绘" and never re-rendered
    "QA-REFERENCE-SHEET-LEAK": ("A", "角色设定图泄漏进画面：画面变成角色设定图/人设卡/三视图/转面图（正面、侧面、背面全身像并排，"
                                     "常带一个大脸特写小窗、纯色背景），或同一个角色在同一画面里出现多个副本/叠影、静态立绘式构图。"
                                     "这是视频模型把身份参考图画进了画面，一律 P0（不要归到 CRAFT-SHOT-GRAMMAR）。"),
    "QA-OVERSIZED-MASK": ("A", "过大的遮罩/模糊框：明显的矩形模糊、马赛克或遮挡块，比字幕区大，盖住脸、手或动作。"),
    "LETTERBOX": ("A", "画幅：竖屏 9:16 成片里混入横版镜头（上下黑边）或左右黑边。"),
    # in A, not D: the benchmark's low-resolution D pass caught 1 of 4 lone-punctuation wraps, the 2-fps single
    # pass 4 of 4 (2026-11-20)
    "QA-SUBTITLE-WRAP": ("A", "我方字幕排版：标点（！？。）或一两个字单独占一行、超过两行、我方字幕和画面里其它文字重叠压字。"
                              "（两行相同的字幕上下叠在一起不是排版问题，报 QA-BURNED-TEXT。）"),
    # B -- identity / continuity
    "QA-IDENTITY-MISMATCH": ("B", "角色和其身份卡不符：脸型/五官/年龄/发型明显不是卡上那个人，或同一角色前后镜头换了一张脸；或景别机位不变时画面里的人在镜头内逐渐变成另一个角色（常是正在说话的那个）；"
                                "或性别特征/年龄感和卡上写的 gender/age 不符（女性角色长出胡子、男性角色被画成女性、"
                                "年龄差出一代）——这些至少 P1，不是妆造问题。"),
    "LOOK-DRIFT": ("B", "同一场内同一角色造型前后不一致：服装颜色/款式、发型、胡子、配饰变了。"),
    "QA-PROP-CONTINUITY": ("B", "同一场内道具不连续：道具位置、数量、状态前后跳变。"),
    "QA-LIGHTING-CONTINUITY": ("B", "同一场内光线不连续：主光方向、色温、昼夜前后镜头不一致。"),
    "QA-POSITION-CONTINUITY": ("B", "同一场内人物站位/左右关系前后跳变（不是走位造成的）。"),
    "QA-LOOKALIKE-CAST": ("B", "两个不同角色看起来像同一个人：对照身份卡，脸型、五官、发型发色、年龄感、眼镜/胡子、体型都差不多，"
                               "观众只能靠衣服或站位分清（尤其是同性别、同年龄段、轮流说话的两个人）。start/end 写其中一人出镜的时间，"
                               "evidence 写另一人出镜的时间点和两人相同的特征；同时在 cast_compare 里给结论。"),
    # C -- sound
    "QA-LIPSYNC": ("C", "口型不同步：说话时嘴不动、嘴动没声音、口型明显超前或滞后。"),
    "QA-VOICE-INCONSISTENT": ("C", "同一角色前后声音不一致（音色、年龄感明显变了），或声音与角色性别/年龄不符。"),
    "QA-WRONG-SPEAKER": ("C", "说话人错了：台词声音出自画面里另一个人，或该说话的人没开口。"),
    # 2026-11-20 (JA-01 E02 ~1:13, 摄政王 E18 ~40 s): a woman on screen speaking with a man's voice, or the reverse
    "QA-VOICE-GENDER": ("C", "声音性别不对：画面里正在说话的是女性却是男声（或男性却是女声），或声音年龄感明显和角色不符；"
                             "写明画面里是谁、听到的是什么样的声音。"),
    "QA-DIALOGUE-TAIL-CUT": ("C", "台词尾音被切：一句话最后一个字在切镜处被截断，或一句说完没有自然停顿就切走/下一句立刻压上。"),
    "QA-LOUDNESS-JUMP": ("C", "响度跳变：相邻两句或相邻镜头之间音量突然变大/变小、底噪突然变化。"),
    "QA-BGM-DISCONTINUOUS": ("C", "背景音乐突兀：音乐只响一两个镜头就停，或在切镜处生硬起停、没有淡入淡出。"),
    "QA-SFX": ("C", "音效：明显该有的音效缺失（打、摔、开门）或音效与画面不符/突兀。"),
    "QA-AUDIO-ARTIFACT": ("C", "音频瑕疵：咔哒声、爆音、机器人声、金属声、回声/混响异常、电流声。"),
    # D -- director / craft
    "CRAFT-BEAT-MISSED": ("D", "该镜头没有交代它的剧情节拍（对照分镜表），或节拍被拍成别的意思。"),
    "CRAFT-SHOT-GRAMMAR": ("D", "镜头语法：对白时静止长镜头不切、连续同景别、跳切、越轴/视线方向混乱、缺反应镜、无动机运镜、单调重复。"),
    # 2026-11-21 (device 1101 E21): "1-2 s shots where the character says nothing before it cuts away"
    "QA-EDIT-FRAGMENT": ("D", "剪辑碎片：不到约 1.2 秒的碎镜头；画面里是正在说话的角色却一句没说就切走（1-2 秒的空镜头）；"
                              "一句话没说完就切到别的镜头（台词被剪断）；整体切得太快（参考实测镜长中位数，低于约 2 秒就是太快）。"
                              "写出每处时间点。"),
    "CRAFT-PACING": ("D", "节奏：某个节拍拖沓或过快（无台词镜头超过约 4 秒、平均镜长过长、爽点间隔超过 25 秒）。"),
    "CRAFT-OPENING-HOOK": ("D", "开头钩子：前 3 秒没有冲突/揭示/危险，或以空镜、建立镜开场。"),
    "CRAFT-ENDING-HOOK": ("D", "结尾钩子：最后 2-3 秒没有落在揭示或威胁上（解决了、抒情、淡出、无悬念）。"),
    "CRAFT-CLARITY": ("D", "清晰度：观众看不懂谁在说话、谁对谁做了什么、为什么。"),
    "CRAFT-EMOTION": ("D", "情绪节拍没落地：该有的反应/情绪高点没拍出来或表演不到位。"),
    # 2026-11-20 (line owner, JA-01 anime E02): characters talk with almost no small movements, and what there is is
    # always the same stock gesture (both hands spread outward)
    # 2026-11-22 (JA-01 E08): the same raised right index finger in many shots, by three different speakers
    "CRAFT-ACTING-MONOTONY": ("D", "表演单调：人物说话时几乎没有小动作/身体戏（干站着念台词），或多个镜头反复用同一个手势"
                                   "（如双手向两侧摊开、竖起一根食指/指着对方、同一个耸肩）——不论是不是同一个角色，"
                                   "不同人物用同一个手势也算；听的人僵住不动没有反应。写出重复的是什么动作、谁、出现在哪些时间点。"),
    "CRAFT-SUBTITLE-READABILITY": ("D", "字幕可读性：我方字幕停留太短读不完、压在复杂背景上看不清、与画面里其它文字重叠。"),
    # 2026-11-23 (device 1101 E24): the blade at the heroine's own throat, a field instead of the rouge shop, a toy
    # skull on a tray instead of a skeleton on a boat, an armoured stranger instead of the demon -- and it shipped
    "QA-PLAN-MISMATCH": ("D", "成片和计划不符：对照逐单元计划，这个单元没拍出计划的内容——主被动/角色关系反了（谁拿刀对着谁、谁打谁）、"
                              "地点不对、计划里的人物或关键道具不在、多出计划里没有的人（包括从画框外伸进来、看不到主人的手或"
                              "手臂：和角色握手、拉手、递东西，动画也一样）、计划的动作节拍没有发生。"
                              "unit_parity 里判 NO 的单元每个单独列一条（start/end 用该单元的时间窗）。"),

    "OTHER": ("*", "其它任何观众会注意到的问题。"),
}
CLASSES = tuple(CLASS_TEXT)
SEVERITIES = ("P0", "P1", "P2", "P3")
SCOPES = ("global", "language")
#: default knowledge-base scope per class when the model gives none (PR #283: global unless it depends on the
#: dialogue language)
LANGUAGE_CLASSES = frozenset({"QA-LIPSYNC", "QA-VOICE-INCONSISTENT", "QA-WRONG-SPEAKER", "QA-SUBTITLE-WRAP",
                              "CRAFT-SUBTITLE-READABILITY"})
#: legacy single-pass shorthand
LEGACY_IDS = {"C1": "QA-BURNED-TEXT", "C2": "QA-DIALOGUE-TAIL-CUT", "C3": "QA-OVERSIZED-MASK",
              "C4": "QA-LOOKALIKE-CAST", "C5": "QA-SUBTITLE-WRAP", "C6": "QA-BGM-DISCONTINUOUS"}


DOMAINS = {"A": "画面瑕疵/烧字/黑边/字幕排版", "B": "身份/服装/场内连贯", "C": "声音/口型/配乐", "D": "节奏/镜头语法/剧情/字幕可读性",
           "E": "片尾高帧率复查"}


def pass_classes(pid: str) -> list[str]:
    if pid == "E":  # the tail pass re-checks the other passes' classes that a 2-fps look misses
        return [c for c in CLASS_TEXT if c in TAIL_CLASSES or c == "OTHER"]
    return [c for c, (p, _) in CLASS_TEXT.items() if p in (pid, "*")]


def tail_window(pid: str, duration: float) -> tuple[float, float] | None:
    """(start, end) of a tail-only pass, None for a whole-episode pass."""
    tail = PASSES.get(pid, {}).get("tail_seconds")
    if not tail or duration <= 0:
        return None
    return (round(max(0.0, duration - float(tail)), 2), round(duration, 2))


def _num(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


# ============================================================================================== episode context
def _read_json(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def _labels(n: int) -> list[str]:
    return [f"角色{chr(ord('A') + i)}" for i in range(n)]


_QUOTE = re.compile(r"[「“\"『][^」”\"』]{0,80}[」”\"』]")


def anonymise(text: Any, names: dict[str, str], limit: int = 90) -> str:
    """Names -> 角色A/B, quoted dialogue -> 「…」, whitespace squeezed, cut to ``limit``."""
    out = _QUOTE.sub("「…」", " ".join(str(text or "").split()))
    for name in sorted(names, key=len, reverse=True):
        if name:
            out = out.replace(name, names[name])
    return out[:limit]


def short_unit(uid: Any) -> str:
    """``E19-VU-004`` -> ``VU-004`` (the episode prefix carries nothing for the model)."""
    return "-".join(str(uid or "").split("-")[-2:])


def _pick_plate(plates: Path, episode: str, char_id: str) -> Path | None:
    """The character's identity card: the full sheet (``<EP>_<CHAR>_<uuid>``) else the front headshot."""
    found = sorted(p for p in plates.glob(f"{episode}_{char_id}_*") if p.suffix.lower() in (".png", ".jpg", ".jpeg"))
    sheets = [p for p in found if "__" not in p.name[len(episode) + len(char_id) + 1:]]
    heads = [p for p in found if "FRONT_NEUTRAL_HEADSHOT" in p.name]
    return (sheets or heads or found or [None])[0]


def _card_view(card: dict[str, Any], *, wardrobe: bool = True) -> dict[str, Any]:
    """The prompt row of one identity card: label plus whichever of gender / age / appearance / wardrobe it has."""
    keys = ("gender", "age", "appearance") + (("wardrobe",) if wardrobe else ())
    return {"label": card["label"], **{k: card[k] for k in keys if card.get(k)}}


def episode_context(episode: str, *, work_root: Path | None = None, assembly: Path | None = None,
                    contract_path: Path | None = None) -> dict[str, Any]:
    """Free, local context for passes B and D from the episode's own files (best effort, {} parts when missing):

    cards   [{label, character_id, image, gender, age, appearance, wardrobe}] -- identity plates of the characters the episode
            shows (S3), names replaced by 角色A/B.. everywhere
    scenes  [{scene, start, end, cast}] -- release-timeline windows of each scene
    shots   [{unit, scene, start, end, scale, beat}] -- the storyboard per video unit (anonymised beat)
    plan_units  [{unit_id, unit, start, end, location, cast, action, props, dialogue, silent, beat}] -- each unit's
            PLANNED content from the generation contract (:func:`plan_units`; start/end None = not in the cut)"""
    ctx: dict[str, Any] = {"cards": [], "scenes": [], "shots": [], "plan_units": [], "source": {}}
    try:
        work = Path(work_root) if work_root else None
        if work is None:
            try:
                import nalu_qa_common as _qa  # noqa: PLC0415
                p = _qa.QaPaths(episode)
                work, assembly = Path(p.work), Path(p.assembly)
                contract_path = contract_path or getattr(p, "contract", None)
            except BaseException:  # noqa: BLE001 -- SystemExit from scope resolution included
                return ctx
        assembly = Path(assembly) if assembly else work / "assembly"
        pre = work / "preproduction"
        grouping = _read_json(pre / f"{episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json") or {}
        editorial = _read_json(pre / f"{episode}_EDITORIAL_SEEDANCE_MANIFEST_V1.json") or {}
        timeline = _read_json(assembly / f"{episode}_release_timeline.json") or {}
        contract = next((c for c in (_read_json(Path(x)) for x in ([contract_path] if contract_path else [
            pre / f"{episode}_GENERATION_CONTRACT_v1.json", work / f"{episode}_GENERATION_CONTRACT_v1.json"]))
            if isinstance(c, dict)), {})
        # characters in order of first appearance (the editorial manifest first; contract-only casts appended)
        order: list[tuple[str, str]] = []
        shot_cast: dict[str, list[str]] = {}
        for shot in [*(editorial.get("shots") or []), *((contract.get("shots") or []) if contract else [])]:
            ids = []
            for row in ((shot.get("prompt_spec") or {}).get("cast") or []):
                cid, name = str(row.get("character_id") or ""), str(row.get("character") or "")
                if cid and cid not in [c for c, _ in order]:
                    order.append((cid, name))
                if cid:
                    ids.append(cid)
            shot_cast.setdefault(str(shot.get("shot_id")), ids)
        labels = dict(zip([c for c, _ in order], _labels(len(order))))
        names = {n: labels[c] for c, n in order if n}
        bible = {str(r.get("character_id")): r for r in ((grouping.get("wardrobe_bible") or editorial.get(
            "wardrobe_bible") or {}).get("characters") or []) if isinstance(r, dict)}
        # 2026-11-27 (deep review 1101 E26): the card carries the contract's gender / apparent age -- without them
        # pass B graded a FEMALE character with a moustache as "P3 rough make-up" and a 45-55 magistrate played by a
        # ~25-year-old went unreported
        entities = {str(r.get("character_id")): r for r in (contract.get("character_entities") or [])
                    if isinstance(r, dict) and r.get("character_id")}
        plates = work / "identity" / "plates"
        for cid, _name in order[:MAX_CARDS]:
            img = _pick_plate(plates, episode, cid) if plates.is_dir() else None
            row, ent = bible.get(cid) or {}, entities.get(cid) or {}
            ctx["cards"].append({"label": labels[cid], "character_id": cid, "image": str(img) if img else None,
                                 "gender": str(ent.get("gender") or row.get("gender") or "").strip(),
                                 "age": str(ent.get("apparent_age_range") or row.get("apparent_age_range") or "").strip(),
                                 "appearance": anonymise(row.get("appearance_ch1") or ent.get("appearance_ch1")
                                                         or row.get("role_basis"), names, 80),
                                 "wardrobe": anonymise(row.get("authored_description"), names, 80)})
        windows = {str(s.get("unit_id")): (float(s["output_start"]), float(s["output_end"]))
                   for s in timeline.get("segments") or [] if _num(s.get("output_start")) is not None
                   and _num(s.get("output_end")) is not None}
        scenes: dict[str, dict[str, Any]] = {}
        for unit in grouping.get("units") or []:
            uid = str(unit.get("unit_id"))
            if uid not in windows:
                continue
            a, b = windows[uid]
            scene = str(unit.get("scene_id") or "")
            cast = sorted({labels[c] for sid in unit.get("editorial_shot_ids") or [] for c in shot_cast.get(str(sid), [])
                           if c in labels})
            ctx["shots"].append({"unit": short_unit(uid), "scene": scene.split("-")[-1], "start": round(a, 1),
                                 "end": round(b, 1), "scale": (unit.get("camera_plan") or {}).get("shot_scale"),
                                 "cast": cast, "beat": anonymise(unit.get("narrative_beat"), names, 90)})
            row = scenes.setdefault(scene, {"scene": scene.split("-")[-1], "start": a, "end": b, "cast": set()})
            row["start"], row["end"] = min(row["start"], a), max(row["end"], b)
            row["cast"].update(cast)
        ctx["shots"].sort(key=lambda r: r["start"])
        ctx["scenes"] = sorted(({**r, "start": round(r["start"], 1), "end": round(r["end"], 1),
                                 "cast": sorted(r["cast"])} for r in scenes.values()), key=lambda r: r["start"])
        ctx["plan_units"] = plan_units(contract, grouping, windows, labels, names, order)
        ctx["source"] = {"grouping": bool(grouping), "editorial": bool(editorial), "timeline": bool(timeline),
                         "contract": bool(contract), "plates": sum(1 for c in ctx["cards"] if c["image"])}
    except Exception as exc:  # noqa: BLE001 -- advisory
        ctx["source"]["error"] = f"{type(exc).__name__}:{str(exc)[:120]}"
    return ctx


def craft_items(engine: Path | None = None) -> list[dict[str, str]]:
    """The craft-standard items pass D checks (pacing first): id, title, reviewer check."""
    root = Path(engine) if engine else Path(__file__).resolve().parents[4]
    data = _read_json(root / "lines" / "nalu" / "standards" / "NALU_CRAFT_STANDARD_v1.items.json") or {}
    wanted = ("S-01", "S-03", "S-02", "S-05", "S-06", "S-09", "S-04", "C-07", "C-05", "C-06", "C-08", "C-10",
              "C-14", "C-11")
    rows = {str(i.get("id")): i for i in data.get("items") or [] if isinstance(i, dict)}
    return [{"id": i, "title": str(rows[i].get("title_zh") or ""), "check": str(rows[i].get("reviewer_check_zh")
                                                                                 or "")[:140]}
            for i in wanted if i in rows]


# ============================================================================================== plan parity
#: pass D's per-unit answer (2026-11-23, device 1101 E24)
PARITY_SCHEMA = "nalu.gemini_plan_parity.v1"
PARITY_DECISIONS = ("YES", "PARTIAL", "NO")
PARITY_REASONS = ("ROLE_REVERSED", "WRONG_LOCATION", "MISSING_PERSON", "MISSING_PROP", "INVENTED_PERSON",
                  "MISSING_BEAT", "WRONG_ACTION", "MISSING_DIALOGUE", "OTHER")
#: a NO unit with one of these reasons breaks the story: P0 unless the model gave a severity itself
PARITY_P0_REASONS = frozenset({"ROLE_REVERSED", "WRONG_LOCATION", "INVENTED_PERSON", "MISSING_PERSON", "MISSING_BEAT"})
NOT_IN_CUT = "NOT_IN_CUT"
NOT_ANSWERED = "NOT_ANSWERED"
PLAN_TEXT_MAX = 150


def _alias_patterns(order: list[tuple[str, str]], labels: dict[str, str]) -> list[tuple[re.Pattern[str], str]]:
    """Romanised names in the contract's English action text (``CHAR-WANGDEFA`` -> "Wang Defa", any case / spacing)
    -> 角色X; ids shorter than four letters are left alone (too many false hits)."""
    out = []
    for cid, _name in order:
        suffix = re.sub(r"[^A-Za-z]", "", cid.split("-", 1)[-1])
        if len(suffix) >= 4 and cid in labels:
            out.append((re.compile(r"(?<![A-Za-z])" + r"[\s\-']?".join(map(re.escape, suffix)) + r"(?![A-Za-z])",
                                   re.IGNORECASE), labels[cid]))
    return out


def plan_text(text: Any, names: dict[str, str], aliases: list[tuple[re.Pattern[str], str]] | None = None,
              limit: int = PLAN_TEXT_MAX) -> str:
    """Names (Chinese and romanised) -> 角色A/B, whitespace squeezed, cut to ``limit``; dialogue kept (pass D must
    hear whether the planned line is spoken)."""
    out = " ".join(str(text or "").split())
    for name in sorted(names, key=len, reverse=True):
        if name:
            out = out.replace(name, names[name])
    for pattern, label in aliases or []:
        out = pattern.sub(label, out)
    return out[:limit]


def _humanise_location(loc: Any) -> str:
    """``LOC-ANCHENG-TEAHOUSE`` -> ``ancheng teahouse`` (the contract carries ids, the model needs words)."""
    raw = str(loc or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"^LOC[-_]", "", raw, flags=re.IGNORECASE)
    return " ".join(w for w in re.split(r"[-_\s]+", raw) if w).lower()[:60]


def _prop_names(props: Any) -> list[str]:
    out = []
    for row in props if isinstance(props, list) else []:
        name = (row if isinstance(row, str) else (row.get("name") or row.get("label") or row.get("description")
                                                  or row.get("prop_id") or "") if isinstance(row, dict) else "")
        name = " ".join(str(name).split())[:40]
        if name and name not in out:
            out.append(name)
    return out[:6]


def _dialogue_lines(spec: dict[str, Any]) -> list[str]:
    raw = spec.get("dialogue")
    rows = raw if isinstance(raw, list) else [raw]
    out = []
    for r in rows:
        text = (r.get("text") or r.get("line") or "") if isinstance(r, dict) else str(r or "")
        if isinstance(r, dict) and r.get("speaker") and text:
            text = f"{r['speaker']}：{text}"
        text = " ".join(str(text).split())
        if text:
            out.append(text)
    return out


def _spoken(line: str) -> str:
    """The spoken part of ``角色：台词`` (the plan's speaker prefix dropped)."""
    return re.split(r"[:：]", line, maxsplit=1)[-1].strip()


def plan_units(contract: dict[str, Any] | None, grouping: dict[str, Any] | None,
               windows: dict[str, tuple[float, float]], labels: dict[str, str], names: dict[str, str],
               order: list[tuple[str, str]] | None = None) -> list[dict[str, Any]]:
    """Each video unit's PLANNED content from the generation contract (the unit's editorial shots), in grouping
    order, with its release-timeline window (None = the unit is not in the cut):

    unit_id, unit, start, end, planned_seconds, scene, location, cast (角色X), action, props, dialogue (角色X：line),
    silent (no planned line), beat; ``_lines`` (the raw spoken lines, never sent) feeds the stray-voice check."""
    contract, grouping = contract or {}, grouping or {}
    shots = {str(s.get("shot_id")): s for s in contract.get("shots") or [] if isinstance(s, dict)}
    if not shots:
        return []
    aliases = _alias_patterns(order or [], labels)
    out = []
    for unit in grouping.get("units") or []:
        uid = str(unit.get("unit_id") or "")
        rows = [shots[str(sid)] for sid in unit.get("editorial_shot_ids") or [] if str(sid) in shots]
        if not uid or not rows:
            continue
        cast, actions, props, lines, places = [], [], [], [], []
        for shot in rows:
            spec = shot.get("prompt_spec") or {}
            for c in spec.get("cast") or []:
                label = labels.get(str(c.get("character_id") or "")) or plan_text(c.get("character"), names, aliases, 12)
                if label and label not in cast:
                    cast.append(label)
            action = (spec.get("action") or {}).get("primary_action") or shot.get("blocking") or ""
            action = plan_text(action, names, aliases)
            if action and action not in actions:
                actions.append(action)
            props += [x for x in _prop_names(spec.get("props") or shot.get("props")) if x not in props]
            lines += _dialogue_lines(spec)
            place = _humanise_location(shot.get("location_id") or spec.get("location_id"))
            if place and place not in places:
                places.append(place)
        window = windows.get(uid)
        planned = _num(unit.get("duration_seconds"))
        if planned is None:
            planned = sum(_num(r.get("target_seconds")) or 0.0 for r in rows)
        out.append({"unit_id": uid, "unit": short_unit(uid),
                    "start": round(window[0], 2) if window else None, "end": round(window[1], 2) if window else None,
                    "planned_seconds": round(planned, 2), "scene": str(unit.get("scene_id") or "").split("-")[-1],
                    "location": " / ".join(places), "cast": cast, "action": " / ".join(actions)[:PLAN_TEXT_MAX * 2],
                    "props": props, "dialogue": [plan_text(x, names, aliases, 80) for x in lines],
                    "silent": not lines, "beat": plan_text(unit.get("narrative_beat"), names, aliases, 90),
                    "_lines": [_spoken(x) for x in lines]})
    return out


def plan_prompt_rows(units: list[dict[str, Any]], window: tuple[float, float] | None = None) -> list[dict[str, Any]]:
    """The units in the cut (or in the chunk), as pass D reads them: short keys, no internal fields."""
    rows = [{"unit": u["unit"], "start": u["start"], "end": u["end"], "where": u.get("location") or "",
             "who": u.get("cast") or [], "does": u.get("action") or "",
             **({"props": u["props"]} if u.get("props") else {}),
             "says": u.get("dialogue") or "无台词"} for u in units or [] if u.get("start") is not None]
    return _clip_rows(rows, window)


def _norm_unit(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if re.fullmatch(r"\d{1,3}", raw):
        return f"VU-{int(raw):03d}"
    return short_unit(raw)


def parse_unit_parity(rows: Any) -> list[dict[str, Any]]:
    """Lenient parse of pass D's ``unit_parity`` rows: unit (VU-nnn), delivered YES|PARTIAL|NO (None if anything
    else), known reasons only (unknown -> OTHER), seen / why text, severity P0..P3 or None."""
    out: list[dict[str, Any]] = []
    for row in rows[:120] if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("unit"):
            continue
        decision = str(row.get("delivered") or "").strip().upper()
        raw = row.get("reasons") if isinstance(row.get("reasons"), list) else [row.get("reasons")] \
            if row.get("reasons") else []
        reasons: list[str] = []
        for r in raw:
            code = re.sub(r"[\s\-]+", "_", str(r or "").strip().upper())
            code = code if code in PARITY_REASONS else "OTHER"
            if code not in reasons:
                reasons.append(code)
        sev = str(row.get("severity") or "").strip().upper()
        pacing = str(row.get("pacing") or "").strip().lower()
        out.append({"unit": _norm_unit(row.get("unit")),
                    "delivered": decision if decision in PARITY_DECISIONS else None, "reasons": reasons,
                    "seen": str(row.get("seen") or "")[:120], "why": str(row.get("why") or "")[:200],
                    "severity": sev if sev in SEVERITIES else None,
                    **({"pacing": pacing} if pacing in ("ok", "slow", "rushed") else {})})
    return out


_PARITY_RANK = {"NO": 0, "PARTIAL": 1, "YES": 2, None: 3}


def fold_unit_parity(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per unit (a unit answered in two chunks: the worse answer wins)."""
    best: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        prior = best.get(row["unit"])
        if prior is None or _PARITY_RANK[row.get("delivered")] < _PARITY_RANK[prior.get("delivered")]:
            best[row["unit"]] = row
    return list(best.values())


def parity_severity(row: dict[str, Any]) -> str | None:
    if row.get("severity"):
        return row["severity"]
    if row.get("delivered") == "NO":
        return "P0" if set(row.get("reasons") or []) & PARITY_P0_REASONS else "P1"
    return "P2" if row.get("delivered") == "PARTIAL" else None


def promote_unit_parity(rows: list[dict[str, Any]], units: list[dict[str, Any]],
                        findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A unit pass D judged NOT delivered with no QA-PLAN-MISMATCH finding over its window becomes one (at the
    unit's window, its severity), so the Codex reviewer verifies it like any other finding."""
    windows = {u["unit"]: (u.get("start"), u.get("end")) for u in units or [] if u.get("start") is not None}
    out: list[dict[str, Any]] = []
    for row in rows or []:
        win = windows.get(row["unit"])
        if row.get("delivered") != "NO" or not win:
            continue
        s, e = float(win[0]), float(win[1])
        if any(f["item"] == "QA-PLAN-MISMATCH" and f["start"] - 0.5 <= e and s <= f["end"] + 0.5 for f in findings):
            continue
        out.append({"item": "QA-PLAN-MISMATCH", "start": round(s, 1), "end": round(e, 1),
                    "severity": parity_severity(row) or "P1",
                    "description": f"unit_parity: {row['unit']} NO ({','.join(row.get('reasons') or []) or '?'})"
                                   + (f" {row.get('why')}" if row.get("why") else ""),
                    "evidence": row.get("seen") or "", "scope_hint": "global", "pass": "D", "unit": row["unit"],
                    "from_parity": True})
    return out


def plan_parity_record(rows: list[dict[str, Any]] | None, units: list[dict[str, Any]] | None, *,
                       answered: bool) -> dict[str, Any]:
    """Every planned unit with its verdict: YES / PARTIAL / NO (pass D), NOT_IN_CUT (no release-timeline window:
    measured locally) or NOT_ANSWERED; counts and the one-line note ``plan parity: n/m delivered`` (n = YES)."""
    by = {r["unit"]: r for r in fold_unit_parity(rows or [])}
    out = []
    for u in units or []:
        base = {"unit_id": u.get("unit_id"), "unit": u["unit"], "start": u.get("start"), "end": u.get("end"),
                "planned_seconds": u.get("planned_seconds")}
        if u.get("start") is None:
            out.append({**base, "delivered": NOT_IN_CUT, "reasons": [NOT_IN_CUT]})
            continue
        r = by.get(u["unit"])
        if not r or r.get("delivered") is None:
            out.append({**base, "delivered": NOT_ANSWERED})
            continue
        sev = parity_severity(r)
        out.append({**base, "delivered": r["delivered"], "reasons": r.get("reasons") or [],
                    **{k: r[k] for k in ("seen", "why", "pacing") if r.get(k)}, **({"severity": sev} if sev else {})})
    counts = {k: sum(1 for r in out if r["delivered"] == k) for k in (*PARITY_DECISIONS, NOT_IN_CUT, NOT_ANSWERED)}
    delivered, total = counts["YES"], len(out)
    return {"schema": PARITY_SCHEMA, "status": "OK" if answered and any(
                r["delivered"] in PARITY_DECISIONS for r in out) else "NOT_ANSWERED",
            "units": out, "counts": counts, "delivered": delivered, "total": total,
            "no_units": [r["unit_id"] for r in out if r["delivered"] == "NO"],
            "note": f"plan parity: {delivered}/{total} delivered" if answered else
            f"plan parity: not reviewed ({counts[NOT_IN_CUT]}/{total} units not in the cut)"}


# ============================================================================================== local suspects
def _window(value: Any) -> tuple[float, float] | None:
    if isinstance(value, (list, tuple)) and len(value) == 2 and _num(value[0]) is not None:
        b = _num(value[1])
        return float(value[0]), float(b if b is not None else value[0])
    return None


def ocr_text_suspects(pack_summary: dict[str, Any] | None, start_id: int, limit: int = 20) -> list[dict[str, Any]]:
    """The evidence pack's OCR text runs as pass-A suspects (``kind`` burned_text): model-burned text anywhere in
    the frame (``burned_text_runs``) and two stacked lines in our subtitle band (``stacked_subtitle_runs``).
    E24 (2026-11-23): Gemini missed burned text local OCR had read; a lead is skimmed, a suspect is answered."""
    pack_summary = pack_summary or {}
    out: list[dict[str, Any]] = []
    for r in (pack_summary.get("stacked_subtitle_runs") or [])[:10]:
        w = _window(r.get("window"))
        if w:
            out.append({"kind": "burned_text", "window": [round(w[0], 2), round(w[1], 2)], "where": "字幕带",
                        "text": " / ".join(str(t) for t in (r.get("texts") or [])[:2])[:40],
                        "why": "本地 OCR：字幕带里上下两行是同一句（模型烧进的台词压在我方字幕下）"})
    for r in pack_summary.get("burned_text_runs") or []:
        w = _window(r.get("window"))
        if w and len(out) < limit:
            out.append({"kind": "burned_text", "window": [round(w[0], 2), round(w[1], 2)], "where": "画面",
                        "text": str(r.get("text") or "")[:16],
                        "why": "本地 OCR：画面里有不是我方字幕的字" + ("（乱码）" if r.get("garbled") else "")})
    for i, row in enumerate(out[:limit]):
        row["id"] = f"S{start_id + i + 1}"
    return out[:limit]


def asr_rows(asr: Any) -> list[dict[str, Any]]:
    """{start, end, text, words[(w, s, e)]} from the final-cut ASR windows (list or {segments|windows}); voice-over
    rows are left out (narration is not an on-screen voice)."""
    rows = asr if isinstance(asr, list) else ((asr.get("segments") or asr.get("windows") or [])
                                              if isinstance(asr, dict) else [])
    out = []
    for r in rows:
        if not isinstance(r, dict) or str(r.get("presence") or "") == "VOICE_OVER":
            continue
        s, e = _num(r.get("start")), _num(r.get("end"))
        if s is None or e is None:
            continue
        words = [(str(w.get("w") or w.get("word") or w.get("text") or ""), _num(w.get("s", w.get("start"))),
                  _num(w.get("e", w.get("end")))) for w in r.get("words") or [] if isinstance(w, dict)]
        out.append({"start": s, "end": e, "text": str(r.get("text") or ""),
                    "words": [(w, a, b) for w, a, b in words if a is not None and b is not None]})
    return out


_NON_TEXT = re.compile(r"[\s\W_]+", re.UNICODE)
STRAY_MIN_OVERLAP_S = 0.4
STRAY_MIN_CHARS = 2
#: heard text whose characters mostly belong to one planned line is that line spilling over a cut, not a stray voice
STRAY_PLANNED_SHARE = 0.6


def stray_voice_suspects(units: list[dict[str, Any]] | None, asr: Any, start_id: int,
                         limit: int = 12) -> list[dict[str, Any]]:
    """Speech the final-cut ASR hears inside units the plan gives NO line (``kind`` stray_voice, pass C): words
    whose midpoint falls in the unit's window (whole rows overlapping >= STRAY_MIN_OVERLAP_S when there are no word
    times), at least STRAY_MIN_CHARS characters, not mostly a planned line of the episode (a J-cut tail).
    E24 (2026-11-23): 「丁师兄/去死吧」 in silent units -- the ASR heard them, Gemini did not report them."""
    rows = asr_rows(asr)
    planned = [set(_NON_TEXT.sub("", line)) for u in units or [] for line in u.get("_lines") or []]
    out: list[dict[str, Any]] = []
    for u in units or []:
        if not u.get("silent") or u.get("start") is None or len(out) >= limit:
            continue
        a, b = float(u["start"]), float(u["end"])
        heard, span = [], [None, None]
        for r in rows:
            if r["words"]:
                hits = [(w, s, e) for w, s, e in r["words"] if a <= (s + e) / 2 <= b]
            else:
                hits = [(r["text"], r["start"], r["end"])] if min(b, r["end"]) - max(a, r["start"]) >= \
                    STRAY_MIN_OVERLAP_S else []
            for w, s, e in hits:
                heard.append(w)
                span = [s if span[0] is None else min(span[0], s), e if span[1] is None else max(span[1], e)]
        text = _NON_TEXT.sub("", "".join(heard))
        if len(text) < STRAY_MIN_CHARS:
            continue
        chars = set(text)
        if any(len(chars & line) / len(chars) >= STRAY_PLANNED_SHARE for line in planned if line):
            continue
        out.append({"kind": "stray_voice", "unit": u["unit"],
                    "window": [round(max(a, span[0]), 2), round(min(b, span[1]), 2)], "heard": text[:30],
                    "why": "本地 ASR：计划里这个单元没有台词，却识别到人声（不是本集任何一句计划台词）"})
    for i, row in enumerate(out):
        row["id"] = f"S{start_id + i + 1}"
    return out


# ============================================================================================== prompts
def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _clip_rows(rows: list[dict[str, Any]], window: tuple[float, float] | None) -> list[dict[str, Any]]:
    """Rows overlapping ``window`` with times shifted to the chunk's own clock."""
    if not window:
        return rows
    a, b = window
    out = []
    for r in rows:
        s, e = _num(r.get("start")), _num(r.get("end"))
        if s is None or e is None or e < a or s > b:
            continue
        out.append({**r, "start": round(max(s, a) - a, 1), "end": round(min(e, b) - a, 1)})
    return out


def _clip_suspects(rows: list[dict[str, Any]], window: tuple[float, float] | None) -> list[dict[str, Any]]:
    if not window:
        return rows
    a, b = window
    out = []
    for r in rows:
        at = _num(r.get("at"))
        w = r.get("window") or []
        if at is not None and a <= at <= b:
            out.append({**r, "at": round(at - a, 2)})
        elif len(w) == 2 and _num(w[0]) is not None and _num(w[1]) is not None and float(w[1]) >= a and float(w[0]) <= b:
            out.append({**r, "window": [round(max(float(w[0]), a) - a, 2), round(min(float(w[1]), b) - a, 2)]})
    return out


ANSWER_SHAPE = ('{"findings":[{"class":"<清单里的类别>","start":0.0,"end":0.0,"severity":"P0|P1|P2|P3",'
                '"description":"","evidence":"你具体看到/听到了什么（画面位置、谁、前后对比）",'
                '"scope_hint":"global|language"}],')


def build_pass_prompt(pid: str, *, duration: float, context: dict[str, Any] | None = None,
                      leads: dict[str, Any] | None = None, suspects: dict[str, list[dict[str, Any]]] | None = None,
                      anime: bool = False, window: tuple[float, float] | None = None,
                      craft: list[dict[str, str]] | None = None, measured_pacing: dict[str, Any] | None = None) -> str:
    """The focused prompt of one pass (``window``: a chunk of the episode, times on the chunk's own clock)."""
    context, leads, suspects = context or {}, leads or {}, suspects or {}
    span = (f"这是全集 {window[0]:.0f}-{window[1]:.0f} 秒的片段（约 {window[1] - window[0]:.0f} 秒），时间从片段开头算起。"
            if window else f"全集约 {duration:.0f} 秒。")
    role = {
        "A": "画面与 AI 生成瑕疵专审：只看画面（不需要声音），逐镜头、逐秒盯细节，特别是脸、眼、牙、手、皮肤质感，"
             "并把每个镜头和前一个镜头对比（同一角色皮肤是否突然变油亮/塑料感、头发是否突然变湿），画面里有没有多余的字，"
             "画面是不是变成了角色设定图/三视图（同一角色多个副本、大脸特写小窗），"
             "以及固定机位镜头里背景是否跟着人物的小动作一起晃（盯住门框、墙角等直线看它相对画框动没动）；"
             "看手时顺带记下：不论是哪个角色，是否很多镜头都是同一个手势（竖起食指、指着对方、双手摊开），"
             "有就报 OTHER，写明手势、角色和时间点（表演单调由导演专审定性，这里只给线索）。",
        "B": "身份与连贯性专审：对照下面附的角色身份卡（图片按顺序是 " +
             "、".join(c["label"] for c in context.get("cards") or [] if c.get("_sent")) +
             "），检查每个镜头里每个角色是否就是卡上的人；在每一场内部检查服装颜色、发型、配饰、道具、光线方向和色温、"
             "人物站位是否前后一致；不同角色是否长得几乎一样——把本集所有同性别角色两两对比（脸型、五官、发型发色、年龄感、"
             "眼镜/胡子、体型），只靠衣服才能分清的就是 QA-LOOKALIKE-CAST。没有身份卡的角色（配角）按他在本集第一次出场的样子作为基准。"
             "身份卡写了 gender 和 age：逐个角色核对画面里的性别特征和年龄感——女性角色有胡子/八字胡、男性角色被画成女性、"
             "卡上 50 岁的人画成 20 多岁（或反过来）都报 QA-IDENTITY-MISMATCH，至少 P1，不要当成妆造粗糙报 OTHER/P3。",
        "C": "声音专审：认真听完整条音轨并看口型。逐句检查口型同步、每个角色前后声音是否一致且符合性别年龄、说话人是否对、"
             "句尾是否被切或没有自然停顿、相邻台词响度是否跳变、背景音乐起停是否生硬、音效是否缺失或突兀、音频瑕疵。",
        "D": "导演/剪辑专审：按分镜表逐镜头判断它有没有交代它的剧情节拍，镜头语法是否成立，每个节拍的节奏，"
             "开头 3 秒钩子、结尾钩子，观众能否看懂谁/做什么/为什么，情绪节拍是否落地，字幕是否好读。节奏优先。",
        "E": "片尾高帧率复查：这是全集最后一段，按高帧率逐帧看、带声音听。逐个镜头检查：是否有一串很短（约 2 秒以内）的碎镜头"
             "接连切换、和前面剧情脱节（像被拼到片尾的蒙太奇）；没有字幕的地方是否有人在说话或发出含混不清的人声；"
             "固定机位里背景是否抖动、推拉；人物是否在镜头内变脸/变成另一个人、身体变形；画面里有没有多余的字；"
             "结尾是否落在悬念上。每处写出精确到 0.1 秒的时间点和看到/听到的内容。",
    }[pid]
    lines = [f"你是竖屏 9:16 短剧平台的终审审片员（{PASSES[pid]['name']}）。{span}{role}",
             "每发现一处单独列一条，不合并、不编造；没有就不列；宁可具体也不要笼统。时间用秒，保留 1 位小数。",
             "我方字幕：画面底部居中的小号白字黑边，一到两行。除此之外画面里的字都不是我方加的。" +
             ("本剧是 2D 动画风格，画风本身不算问题，只查崩坏、走形、跳变。" if anime else ""),
             "", "清单（class 只能用这些）："]
    lines += [f"{c}：{CLASS_TEXT[c][1]}" for c in pass_classes(pid)]
    others = "、".join(v for k, v in DOMAINS.items() if k != pid)
    lines += [f"只报本清单里的问题（OTHER 只放本专审范围内但清单没写到的）；{others}由其它专审负责，不要报。"]
    cuts = _clip_rows(context.get("cuts") or [], window)
    if cuts and pid in ("A", "B", "D", "E"):
        lines += ["", "实测镜头切点（逐镜头检查用）：", _json([[r["start"], r["end"]] for r in cuts])]
    if pid == "E":
        tail_plan = plan_prompt_rows(context.get("plan_units") or [], window)
        if tail_plan:
            lines += ["", "这一段的逐单元计划（start/end 是片段内时间；says 为空的单元计划无台词，不该有人说话）：",
                      _json(tail_plan)]
    if pid == "A" and leads.get("burned_text_ocr") and not suspects.get("burned_text"):  # else a suspect below
        lines += ["", "本地 OCR 线索（可能有误，以你看到的为准）：", _json(_clip_rows(
            [{"start": (r.get("window") or [None, None])[0], "end": (r.get("window") or [None, None])[1],
              "text": r.get("text"), **({"garbled": True} if r.get("garbled") else {})}
             for r in leads["burned_text_ocr"]], window))]
    if pid == "A" and leads.get("subtitle_wrap"):
        lines += ["", "本地字幕折行线索：", _json(_clip_rows(
            [{"start": (r.get("window") or [None, None])[0], "end": (r.get("window") or [None, None])[1]}
             for r in leads["subtitle_wrap"] if isinstance(r, dict)], window))]
    if pid == "B":
        cards = [_card_view(c) for c in context.get("cards") or []
                 if c.get("_sent") or c.get("appearance") or c.get("gender") or c.get("age")]
        if cards:
            lines += ["", "角色身份卡（图片已附，名字已隐去）：", _json(cards)]
        if context.get("scenes"):
            lines += ["", "分场（场次、时间窗、出场角色）：", _json(_clip_rows(context["scenes"], window))]
        elif context.get("shots"):
            lines += ["", "镜头时间窗：", _json(_clip_rows(context["shots"], window))]
        if leads.get("lookalike_faces"):
            lines += ["", "本地人脸相似度线索：", _json(leads["lookalike_faces"])]
    if pid == "C":
        cards = [_card_view(c, wardrobe=False) for c in context.get("cards") or []
                 if c.get("appearance") or c.get("gender") or c.get("age")]
        if cards:
            lines += ["", "角色（用于判断声音是否符合性别年龄）：", _json(cards)]
    plan_rows = plan_prompt_rows(context.get("plan_units") or [], window) if pid == "D" else []
    if pid == "D":
        if plan_rows:  # 2026-11-23 (device 1101 E24): the plan per unit, answered per unit (unit_parity)
            cast = [_card_view(c) for c in context.get("cards") or []
                    if c.get("appearance") or c.get("wardrobe") or c.get("gender") or c.get("age")]
            lines += ["", "逐单元计划（生成合同；start/end 是这个单元在成片里的时间窗；where 地点、who 计划出场的人、does 计划的动作、"
                      "props 道具、says 计划台词；名字已隐去）：", _json(plan_rows)]
            if cast:
                lines += ["角色外观（用来认人）：", _json(cast)]
            lines += ["逐单元对照（本专审最重要的一项）：每个单元先看画面里实际是谁、在什么地方、在做什么、听到谁在说话，再和计划比："
                      "地点像不像计划的地方；计划的人在不在，主被动/谁对谁做有没有反（例如计划是角色A拿刀逼角色B，画面却是刀架在"
                      "角色A自己脖子上）；有没有多出计划里没有的人（或换成了别人）；关键道具在不在、是不是那个东西；计划的动作节拍"
                      "有没有发生；计划无台词的单元有没有人说话。delivered：YES 计划内容拍出来了 / PARTIAL 只拍出一部分 / NO 没拍出来"
                      "或拍成了别的意思。"]
        elif context.get("shots"):
            lines += ["", "分镜表（每个视频单元：场次、时间窗、景别、出场角色、剧情节拍；名字已隐去）：",
                      _json(_clip_rows(context["shots"], window))]
        if craft:
            lines += ["", "成片标准 v1 要点（节奏优先）：", _json(craft)]
        if measured_pacing:
            cut = {k: v for k, v in measured_pacing.items() if k != "script_plan"}
            if cut:
                lines += ["", "成片上量出来的节奏数据（直接用）：", _json(cut)]
            if measured_pacing.get("script_plan"):  # SHORT_DRAMA_PACING_V1 (S1, free)
                lines += ["", "剧本阶段计划的节奏（S1 对剧本合同的测量，是计划不是成片；剧本里就慢的问题写清是剧本节奏问题）：",
                          _json(measured_pacing["script_plan"])]
    own = {k: v for k, v in suspects.items() if v}
    if own:
        lines += ["", "本地测量的可疑点，必须逐个用耳朵/眼睛核实并在 suspect_checks 里给结论（CONFIRMED 确有其事 / "
                  "DISMISSED 听看都正常 / UNSURE），给出你听到或看到的理由：",
                  _json({k: _clip_suspects(v, window) for k, v in own.items()})]
        if own.get("burned_text"):
            lines += ["burned_text：本地 OCR 读到的字。到那个时间窗看：除了我方字幕和片头片尾卡，画面里真有字（含乱码、第二行字幕）就是"
                      "CONFIRMED，同时报 QA-BURNED-TEXT。"]
        if own.get("silent_mouth"):
            lines += ["silent_mouth：计划这里没有台词，引擎已把模型生成的人声静音。到那个时间窗看画面：有人嘴在一张一合、像在说话"
                      "（不是惊讶张嘴、喘气）就是 CONFIRMED，写出是谁，并报 QA-SILENT-MOUTH（P1）。"]
        if own.get("stray_voice"):
            lines += ["stray_voice：计划这里没有台词，本地 ASR 却听到人声。到那个时间窗听：确有人在说话（不是环境声、不是上一句台词"
                      "的尾音）就是 CONFIRMED，写出听到了什么、画面里谁的嘴在动，并报 QA-WRONG-SPEAKER 或 OTHER。"]
    extra = ""
    if pid == "A":
        extra = ('"shot_log":[{"shot":1,"start":0.0,"end":0.0,"fail":["<本清单里这一镜没通过的类别>"],'
                 '"note":"≤20字：这一镜里的人脸/手/皮肤/背景与上一镜相比"}],')
    if pid == "B":
        extra = ('"shot_log":[{"shot":1,"start":0.0,"end":0.0,"who":["角色A"],"fail":["<本清单里这一镜没通过的类别>"],'
                 '"note":"≤20字：脸与身份卡、服装/发型/配饰/光线与本场上一镜相比"}],'
                 '"cast_compare":[{"a":"角色A","b":"角色B","distinct":true,"a_at":[0.0],"b_at":[0.0],'
                 '"note":"≤30字：两人不同在哪 / 哪些特征一样"}],')
    if pid == "C":
        extra = ('"line_log":[{"start":0.0,"end":0.0,"speaker":"角色A|男|女|旁白","tail":"ok|clipped|no_pause",'
                 '"lipsync":"ok|off|offscreen","level":"ok|jump"}],')
    if pid == "D" and plan_rows:  # the per-unit rows replace the beat rows (same output budget)
        extra = ('"craft_summary":{"opening_hook":{"at":0.0,"ok":true,"note":""},"ending_hook":{"ok":true,"note":""}},'
                 '"unit_parity":[{"unit":"VU-001","delivered":"YES|PARTIAL|NO","reasons":["' +
                 "|".join(PARITY_REASONS) + '"],"seen":"≤25字：画面里实际是谁、在哪、做什么","pacing":"ok|slow|rushed",'
                 '"severity":"P0|P1|P2|P3"}],')
    elif pid == "D":
        extra = ('"craft_summary":{"opening_hook":{"at":0.0,"ok":true,"note":""},"ending_hook":{"ok":true,"note":""},'
                 '"beats":[{"start":0.0,"end":0.0,"delivered":true,"pacing":"ok|slow|rushed","note":""}]},')
    lines += ["", "只输出 JSON：", ANSWER_SHAPE +
              ('"suspect_checks":[{"id":"S1","decision":"CONFIRMED|DISMISSED|UNSURE","reason":""}],' if own else "") +
              extra + '"verdict":"PASS|REJECT_RECUT"}',
              ("shot_log 是逐镜头清单：每个镜头一行（按实测切点，一个不漏），对本清单每个类别逐项检查，fail 写这一镜没通过的"
               "类别，全部通过就写 []；先逐镜头写完再汇总 findings，fail 里出现的类别必须在 findings 里有对应条目。"
               + ("cast_compare 把本集同性别角色两两各列一行（distinct=false 表示看起来像同一个人，必须同时报 "
                  "QA-LOOKALIKE-CAST）。" if pid == "B" else "") if pid in ("A", "B") else
               "line_log 每句台词一行，先逐句听完再汇总 findings。" if pid == "C" else
               ("unit_parity 每个计划单元一行，一个不漏（YES 的也写）；reasons 只写不符的原因（YES 写 []）；判 NO 的单元同时在 "
                "findings 里报一条 QA-PLAN-MISMATCH。主被动反了、地点不对、计划的人不在或换成了别人、多出的人改变了剧情、"
                "计划的关键节拍没发生 → P0；其余不符按观众影响给 P1-P3。") if plan_rows else ""),
              "severity：P0 必须返工 / P1 严重 / P2 一般 / P3 轻微。scope_hint：换成任何对白语言都会出现的问题（画面、剪辑、"
              "节奏、身份、服装、音乐）写 global；只和这种对白语言有关的（台词用词、口型、配音音色、字幕文字/断行）写 language。"]
    return "\n".join(lines)


# ============================================================================================== models + budget
def resolve_pass_models(environ: Any = None, override: str | None = None,
                        passes: tuple[str, ...] = PASS_IDS) -> dict[str, str]:
    """{pass: model}: ``NALU_GEMINI_REVIEW_MODEL_<P>`` > ``override`` (``--model``) > ``NALU_GEMINI_REVIEW_MODEL``
    > PASS_MODELS."""
    env = os.environ if environ is None else environ
    common = str(override or env.get(MODEL_ENV) or "").strip()
    return {p: str(env.get(f"{MODEL_ENV}_{p}") or "").strip() or common or PASS_MODELS[p] for p in passes}


def _models(model: str | dict[str, str] | None, passes: tuple[str, ...] = PASS_IDS) -> dict[str, str]:
    """A single model for every pass (the pre-2026-11-23 call shape), a per-pass map, or the defaults."""
    if isinstance(model, dict):
        return {p: model.get(p) or PASS_MODELS[p] for p in passes}
    return {p: model or PASS_MODELS[p] for p in passes}


def budget_cap(environ: Any = None, default: float = MAX_CREDITS_DEFAULT) -> float:
    env = os.environ if environ is None else environ
    for name in BUDGET_ENVS:
        value = _num(env.get(name))
        if value is not None and value > 0:
            return value
    return default


def thinking_budget(pid: str, model: str) -> int | None:
    """The fixed thinkingBudget sent for a pass: Flash keeps the pass's own (B 3072); Pro thinks dynamically."""
    return None if model in THINKING_TOKENS else PASSES[pid].get("thinking_budget")


def expected_output_tokens(pid: str, model: str) -> int:
    return int(PASSES[pid]["expected_out"]) + int(THINKING_TOKENS.get(model, 0))


def pass_ladder(pid: str, model: str) -> tuple[tuple[str, float, str], ...]:
    """(model, fps, media resolution) from preferred to cheapest.  A pass on a model other than FALLBACK_MODEL keeps
    that model only for its top fps steps (>= 1.5 fps at the preferred resolution) and then steps down to
    FALLBACK_MODEL's full ladder: a Pro pass's cost is mostly its answer + thinking, so dropping its fps saves little
    while a Flash pass at full resolution still sees the burned text / faces (2026-11-23)."""
    ladder = PASSES[pid]["ladder"]
    if model == FALLBACK_MODEL:
        return tuple((model, f, r) for f, r in ladder)
    top = tuple((model, f, r) for f, r in ladder if r == ladder[0][1] and f >= 1.5)
    return top + tuple((FALLBACK_MODEL, f, r) for f, r in ladder)


def estimate_pass(model: str, prices: dict[str, tuple[float, float]], *, pid: str, duration: float, fps: float,
                  res: str, prompt_chars: int, images: int = 0) -> float:
    pin, pout = prices.get(model) or MODEL_PRICES.get(model) or next(iter(prices.values()))
    win = tail_window(pid, duration)
    if win:
        duration = win[1] - win[0]
    tokens = duration * fps * VIDEO_TOKENS[res] + images * IMAGE_TOKENS[res] + prompt_chars / 1.6 + 300
    if PASSES[pid]["audio"]:
        tokens += duration * AUDIO_TOKENS_PER_S
    return round(tokens * pin / 1e6 + expected_output_tokens(pid, model) * pout / 1e6, 3)


def plan_budget(model: str | dict[str, str] | None, prices: dict[str, tuple[float, float]], *, duration: float,
                cap: float, prompt_chars: dict[str, int], images: dict[str, int] | None = None,
                passes: tuple[str, ...] = PASS_IDS) -> dict[str, Any]:
    """{pass: {model, fps, res, estimate} | {skipped: reason}} and the total.  Degrade D, C, B, A (one pass_ladder
    step at a time, lowest priority first) until the estimate fits ``cap``; then skip D, C, B.  A is never skipped
    while it alone fits."""
    images = images or {}
    models = _models(model, passes)
    ladders = {p: pass_ladder(p, models[p]) for p in passes}
    step = {p: 0 for p in passes}
    active = list(passes)

    def est(p: str) -> float:
        use, fps, res = ladders[p][step[p]]
        return estimate_pass(use, prices, pid=p, duration=duration, fps=fps, res=res,
                             prompt_chars=prompt_chars.get(p, 2000), images=images.get(p, 0))

    skipped: dict[str, str] = {}
    while active and sum(est(p) for p in active) > cap:
        movable = [p for p in DEGRADE_ORDER if p in active and step[p] + 1 < len(ladders[p])]
        if movable:
            step[movable[0]] += 1
            continue
        victim = next((p for p in DEGRADE_ORDER if p in active and p != "A"), None)
        if victim is None:
            break
        active.remove(victim)
        skipped[victim] = "BUDGET_SKIPPED"
    # the greedy descent can overshoot (a whole Pro step at once): give the slack back, highest priority first --
    # but never Pro to a lower-priority pass while a higher-priority one was stepped down to FALLBACK_MODEL
    demoted = False
    for p in reversed(DEGRADE_ORDER):
        while p in active and step[p] > 0:
            step[p] -= 1
            if sum(est(q) for q in active) <= cap and not (demoted and ladders[p][step[p]][0] != FALLBACK_MODEL
                                                           and ladders[p][step[p] + 1][0] == FALLBACK_MODEL):
                continue
            step[p] += 1
            break
        if p in active and ladders[p][step[p]][0] != models[p]:
            demoted = True
    plan: dict[str, Any] = {}
    for p in passes:
        if p in skipped:
            plan[p] = {"skipped": skipped[p]}
        elif p in active:
            use, fps, res = ladders[p][step[p]]
            plan[p] = {"model": use, "fps": fps, "res": res, "estimate": est(p), "degraded_steps": step[p],
                       **({"model_planned": models[p]} if use != models[p] else {})}
    total = round(sum(v.get("estimate", 0.0) for v in plan.values()), 3)
    if active and total > cap:   # even A alone at its cheapest does not fit
        plan = {p: {"skipped": "ESTIMATE_OVER_BUDGET"} for p in passes}
        total = 0.0
    return {"passes": plan, "estimated_credits": total, "cap": cap}


# ============================================================================================== media
def ffmpeg() -> str:
    return os.environ.get("FFMPEG_BIN") or shutil.which("ffmpeg") or "ffmpeg"


def transcode_pass(video: Path, out: Path, *, scale: tuple[int, int], audio: bool, crf: int = 30,
                   start: float | None = None, length: float | None = None) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg(), "-v", "error", "-y"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(video)]
    if length is not None:
        cmd += ["-t", f"{length:.3f}"]
    cmd += ["-vf", f"scale={scale[0]}:{scale[1]}", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
            "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-b:a", "64k", "-ac", "1"] if audio else ["-an"]
    cmd += ["-movflags", "+faststart", str(out)]
    run = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if run.returncode != 0 or not out.is_file():
        raise RuntimeError(f"transcode failed: {(run.stderr or '')[-300:]}")
    return out


def card_jpeg(image: Path, out: Path) -> Path:
    """An identity card downscaled to CARD_MAX_SIDE (JPEG) for the inline request."""
    out.parent.mkdir(parents=True, exist_ok=True)
    vf = (f"scale='if(gt(iw,ih),min({CARD_MAX_SIDE},iw),-2)':'if(gt(iw,ih),-2,min({CARD_MAX_SIDE},ih))'")
    run = subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(image), "-vf", vf, "-q:v", "4", str(out)],
                         capture_output=True, text=True, timeout=120)
    if run.returncode != 0 or not out.is_file():
        raise RuntimeError("card downscale failed")
    return out


Transcoder = Callable[..., Path]


def prepare_media(video: Path, pid: str, workdir: Path, *, duration: float,
                  transcoder: Transcoder | None = None) -> list[dict[str, Any]]:
    """[{path, window|None}] for one pass: the whole episode, or time windows when one file would not fit the
    inline limit (each window ``duration / n``)."""
    meta = PASSES[pid]
    tc = transcoder or transcode_pass
    tag = f"{meta['scale'][0]}x{meta['scale'][1]}_{'av' if meta['audio'] else 'v'}"
    win = tail_window(pid, duration)
    if win:
        tail = workdir / f"{tag}_tail{win[0]:.0f}.mp4"
        if not tail.is_file():
            tc(video, tail, scale=meta["scale"], audio=meta["audio"], start=win[0], length=win[1] - win[0])
        return [{"path": tail, "window": win}]
    whole = workdir / f"{tag}.mp4"
    if not whole.is_file():
        tc(video, whole, scale=meta["scale"], audio=meta["audio"])
    size = whole.stat().st_size
    if size <= MAX_UPLOAD_BYTES:
        return [{"path": whole, "window": None}]
    n = int(size // MAX_UPLOAD_BYTES) + 1
    length = duration / n
    out = []
    for i in range(n):
        part = workdir / f"{tag}_part{i}.mp4"
        if not part.is_file():
            tc(video, part, scale=meta["scale"], audio=meta["audio"], start=i * length, length=length)
        out.append({"path": part, "window": (round(i * length, 2), round(min(duration, (i + 1) * length), 2))})
    return out


# ============================================================================================== call + parse
def request_body(*, video_bytes: bytes, prompt: str, fps: float, res: str,
                 images: list[bytes] | None = None, thinking_budget: int | None = None) -> dict[str, Any]:
    parts: list[dict[str, Any]] = [{"inline_data": {"mime_type": "video/mp4",
                                                    "data": base64.b64encode(video_bytes).decode()},
                                    "video_metadata": {"fps": fps}}]
    parts += [{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(b).decode()}} for b in images or []]
    parts.append({"text": prompt})
    return {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json",
                                 "maxOutputTokens": MAX_OUTPUT_TOKENS,
                                 **({"mediaResolution": MEDIA_RESOLUTION[res]} if MEDIA_RESOLUTION[res] else {}),
                                 **({"thinkingConfig": {"thinkingBudget": int(thinking_budget)}}
                                    if thinking_budget else {})}}


def parse_pass(text: str, *, pid: str, duration: float | None, offset: float = 0.0,
               window_len: float | None = None, known_suspects: dict[str, dict[str, Any]] | None = None
               ) -> dict[str, Any]:
    """Lenient parse of one pass's answer; times shifted by ``offset`` (chunks).  Raises ValueError when the answer
    is not a JSON object."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except ValueError:
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else None
    if not isinstance(data, dict):
        raise ValueError("answer is not a JSON object")
    allowed = set(pass_classes(pid))
    findings, notes = [], []
    limit = window_len if window_len else duration
    for pos, row in enumerate(data.get("findings") or []):
        if not isinstance(row, dict):
            continue
        cls = str(row.get("class") or "").strip().upper()
        cls = LEGACY_IDS.get(cls, cls)
        if cls not in CLASS_TEXT:
            notes.append(f"findings.{pos}:unknown_class")
            cls = "OTHER"
        elif cls not in allowed:
            notes.append(f"findings.{pos}:class_of_other_pass:{cls}")
        start, end = _num(row.get("start")), _num(row.get("end"))
        if start is None or start < 0 or (limit and start > limit + 1):
            notes.append(f"findings.{pos}:bad_start")
            continue
        end = start if end is None or end < start else end
        sev = str(row.get("severity") or "P2").strip().upper()
        scope = str(row.get("scope_hint") or "").strip().lower()
        findings.append({"item": cls, "start": round(start + offset, 1), "end": round(end + offset, 1),
                         "severity": sev if sev in SEVERITIES else "P2",
                         "description": str(row.get("description") or "")[:300],
                         "evidence": str(row.get("evidence") or "")[:300],
                         "scope_hint": scope if scope in SCOPES else
                         ("language" if cls in LANGUAGE_CLASSES else "global"),
                         "pass": pid})
    checks = []
    known = known_suspects or {}
    for row in data.get("suspect_checks") or []:
        if isinstance(row, dict) and str(row.get("id")) in known:
            decision = str(row.get("decision") or "").strip().upper()
            checks.append({"id": str(row["id"]), "decision": decision if decision in ("CONFIRMED", "DISMISSED",
                                                                                          "UNSURE") else "UNSURE",
                           "reason": str(row.get("reason") or "")[:300], "suspect": known[str(row["id"])],
                           "pass": pid})
    verdict = str(data.get("verdict") or "").strip().upper()
    out = {"findings": findings[:80], "suspect_checks": checks, "parse_notes": notes,
           "verdict": verdict if verdict in ("PASS", "REJECT_RECUT") else None}
    if pid == "D" and isinstance(data.get("craft_summary"), dict):
        out["craft_summary"] = data["craft_summary"]
    if pid == "D" and isinstance(data.get("unit_parity"), list):
        out["unit_parity"] = parse_unit_parity(data["unit_parity"])
    if pid == "B" and isinstance(data.get("cast_compare"), list):
        out["cast_compare"] = [cast_compare_row(r, offset) for r in data["cast_compare"][:30] if isinstance(r, dict)]
    for log, keys in (("shot_log", ("shot", "who", "fail", "note")),
                      ("line_log", ("speaker", "tail", "lipsync", "level"))):
        if isinstance(data.get(log), list):
            out[f"{log}_rows"] = len(data[log])
            out[log] = [{"start": round((_num(r.get("start")) or 0.0) + offset, 1),
                         "end": round((_num(r.get("end")) or 0.0) + offset, 1),
                         **{k: (str(r.get(k))[:60] if k == "note" else _fail_list(r.get(k), pid) if k == "fail"
                                else r.get(k)) for k in keys if r.get(k) is not None}}
                        for r in data[log][:LOG_MAX_ROWS] if isinstance(r, dict)]
    return out


def _fail_list(value: Any, pid: str) -> list[str]:
    """The failed classes of one per-shot checklist row: known classes of this pass only, upper-cased, deduped."""
    raw = value if isinstance(value, list) else [value] if isinstance(value, str) and value else []
    allowed = set(pass_classes(pid))
    out = []
    for v in raw:
        cls = LEGACY_IDS.get(str(v).strip().upper(), str(v).strip().upper())
        if cls in allowed and cls != "OTHER" and cls not in out:
            out.append(cls)
    return out


def cast_compare_row(row: dict[str, Any], offset: float = 0.0) -> dict[str, Any]:
    """One pass-B pairwise cast comparison: labels, distinct (bool | None), the two characters' on-screen times."""
    distinct = row.get("distinct")
    if isinstance(distinct, str):
        distinct = {"true": True, "false": False}.get(distinct.strip().lower())
    times = {k: [round(float(t) + offset, 1) for t in (row.get(k) or []) if _num(t) is not None][:6]
             for k in ("a_at", "b_at")}
    return {"a": str(row.get("a") or "")[:12], "b": str(row.get("b") or "")[:12],
            "distinct": distinct if isinstance(distinct, bool) else None, **times,
            "note": str(row.get("note") or "")[:80]}


def promote_shot_checklist(log: list[dict[str, Any]], findings: list[dict[str, Any]], pid: str) -> list[dict[str, Any]]:
    """A class a per-shot checklist row marks failed that the pass did not also list as a finding (overlapping the
    shot +-1 s) becomes a P3 finding marked ``from_checklist`` -- the per-shot rows make the coverage systematic,
    so a fail is never silently dropped."""
    out: list[dict[str, Any]] = []
    for row in log:
        s, e = float(row.get("start") or 0.0), float(row.get("end") or 0.0)
        for cls in row.get("fail") or []:
            if any(f["item"] == cls and f["start"] - 1.0 <= e and s <= f["end"] + 1.0 for f in findings + out):
                continue
            out.append({"item": cls, "start": round(s, 1), "end": round(max(s, e), 1), "severity": "P3",
                        "description": f"shot_log: shot {row.get('shot')} fail {cls}"
                                       + (f" ({row.get('note')})" if row.get("note") else ""),
                        "evidence": "", "scope_hint": "language" if cls in LANGUAGE_CLASSES else "global",
                        "pass": pid, "from_checklist": True})
    return out


def promote_cast_compare(rows: list[dict[str, Any]], findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A pass-B pair judged NOT distinct with no QA-LOOKALIKE-CAST finding becomes a P2 finding at the first
    on-screen time of either character, the other's times in the evidence."""
    out: list[dict[str, Any]] = []
    if any(f["item"] == "QA-LOOKALIKE-CAST" for f in findings):
        return out
    for row in rows:
        if row.get("distinct") is not False:
            continue
        times = (row.get("a_at") or []) + (row.get("b_at") or [])
        at = min(times) if times else 0.0
        out.append({"item": "QA-LOOKALIKE-CAST", "start": at, "end": at, "severity": "P2",
                    "description": f"cast_compare: {row.get('a')} and {row.get('b')} look like the same person"
                                   + (f" ({row.get('note')})" if row.get("note") else ""),
                    "evidence": f"{row.get('a')} at {row.get('a_at')} s; {row.get('b')} at {row.get('b_at')} s",
                    "scope_hint": "global", "pass": "B", "from_cast_compare": True})
    return out


#: line_log flag -> class.  A flagged line the model did not also list as a finding becomes a P3 finding marked
#: ``from_log`` (the sound pass tends to dismiss in its summary what it flagged line by line).
LINE_LOG_FLAGS = (("tail", ("clipped", "no_pause"), "QA-DIALOGUE-TAIL-CUT"), ("lipsync", ("off",), "QA-LIPSYNC"),
                  ("level", ("jump",), "QA-LOUDNESS-JUMP"))


def promote_line_log(log: list[dict[str, Any]], findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in log:
        for field, values, cls in LINE_LOG_FLAGS:
            if str(row.get(field) or "").strip().lower() not in values:
                continue
            s, e = float(row.get("start") or 0.0), float(row.get("end") or 0.0)
            if any(f["item"] == cls and f["start"] - 1.0 <= e and s <= f["end"] + 1.0 for f in findings + out):
                continue
            at = e if cls == "QA-DIALOGUE-TAIL-CUT" else s
            out.append({"item": cls, "start": round(at, 1), "end": round(max(at, e), 1), "severity": "P3",
                        "description": f"line_log: {field}={row.get(field)}", "evidence": "",
                        "scope_hint": "language" if cls in LANGUAGE_CLASSES else "global", "pass": "C",
                        "from_log": True})
    return out


# ============================================================================================== merge
MERGE_TOLERANCE_S = 0.5


def merge(results: dict[str, dict[str, Any]], suspects: dict[str, list[dict[str, Any]]],
          plan: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One backward-compatible record body from the passes' parsed results: findings (ids G1.. by time; the same class
    reported by two passes overlapping within MERGE_TOLERANCE_S folded, highest severity kept), suspect checks (every S id,
    NOT_ANSWERED when no pass answered it), class summary, the strictest verdict, craft summary."""
    rows = [f for pid in PASS_IDS for f in (results.get(pid) or {}).get("findings") or []]
    rows.sort(key=lambda f: (f["start"], PASS_IDS.index(f.get("pass", "A")), f["item"]))
    merged: list[dict[str, Any]] = []
    for f in rows:
        # only a DIFFERENT pass reporting the same class at the same time is a duplicate; two findings of one pass
        # are two instances (e.g. two burned-text phrases back to back)
        twin = next((m for m in merged if m["item"] == f["item"] and m.get("pass") != f.get("pass")
                     and f.get("pass") not in (m.get("also_pass") or [])
                     and m["start"] - MERGE_TOLERANCE_S <= f["end"] and f["start"] <= m["end"] + MERGE_TOLERANCE_S),
                    None)
        if twin is None:
            merged.append(dict(f))
            continue
        twin["start"], twin["end"] = min(twin["start"], f["start"]), max(twin["end"], f["end"])
        if SEVERITIES.index(f["severity"]) < SEVERITIES.index(twin["severity"]):
            twin["severity"] = f["severity"]
        if f.get("pass") != twin.get("pass"):
            twin["also_pass"] = sorted(set(twin.get("also_pass") or []) | {f.get("pass")})
        if f["description"] and f["description"] not in twin["description"]:
            twin["description"] = (twin["description"] + " / " + f["description"])[:300]
    for i, f in enumerate(merged):
        f["id"] = f"G{i + 1}"
    checks = [c for pid in PASS_IDS for c in (results.get(pid) or {}).get("suspect_checks") or []]
    seen: dict[str, dict[str, Any]] = {}
    for c in checks:   # a suspect answered in two chunks: CONFIRMED wins over UNSURE / DISMISSED
        prior = seen.get(c["id"])
        if prior is None or (c["decision"] == "CONFIRMED" and prior["decision"] != "CONFIRMED"):
            seen[c["id"]] = c
    known = {row["id"]: row for rows_ in suspects.values() for row in rows_}
    checks = list(seen.values()) + [{"id": sid, "decision": "NOT_ANSWERED", "suspect": row}
                                    for sid, row in known.items() if sid not in seen]
    checks.sort(key=lambda c: int(c["id"][1:]))
    summary = {c: ("found" if any(f["item"] == c for f in merged) else "not_found") for c in CLASSES
               if any(CLASS_TEXT[c][0] == p and (results.get(p) or {}).get("status") == "OK" for p in PASS_IDS)}
    verdicts = [(results.get(p) or {}).get("verdict") for p in PASS_IDS]
    verdict = ("REJECT_RECUT" if "REJECT_RECUT" in verdicts else "PASS" if "PASS" in verdicts else None)
    out = {"findings": merged[:120], "suspect_checks": checks, "class_summary": summary, "verdict": verdict,
           "parse_notes": [f"{p}:{n}" for p in PASS_IDS for n in (results.get(p) or {}).get("parse_notes") or []]}
    craft = (results.get("D") or {}).get("craft_summary")
    if craft:
        out["craft_summary"] = craft
    if plan:  # every planned unit's parity verdict (2026-11-23): final fix round + final_cut_shot_plan_parity read it
        d = results.get("D") or {}
        out["plan_parity"] = plan_parity_record(d.get("unit_parity"), plan,
                                                answered=d.get("status") == "OK" and d.get("unit_parity") is not None)
    return out


def skin_sheen_suspects(measured: dict[str, Any] | None, context: dict[str, Any],
                        start_id: int) -> list[dict[str, Any]]:
    """PR #284's S6 skin-sheen drift units (``measurements.skin_sheen.units``) as pass-A suspects with their
    on-screen window (release timeline via the context's storyboard rows); ids continue after ``start_id``."""
    windows = {short_unit(r.get("unit")): (r.get("start"), r.get("end")) for r in context.get("shots") or []}
    out = []
    for row in ((measured or {}).get("units") or [])[:20]:
        uid = str(row.get("unit_id") or "")
        win = windows.get(short_unit(uid))
        out.append({"unit": short_unit(uid), **({"window": list(win)} if win and win[0] is not None else {}),
                    "why": "S6 实测：" + ",".join(str(x) for x in row.get("reasons") or [])[:120],
                    "id": f"S{start_id + len(out) + 1}"})
    return out


def camera_wobble_suspects(measured: dict[str, Any] | None, context: dict[str, Any],
                           start_id: int) -> list[dict[str, Any]]:
    """S6 camera-wobble units (``measurements.camera_wobble.measured``, tools/h3_camera_wobble) as pass-A suspects with
    their on-screen window; ids continue after ``start_id``."""
    windows = {short_unit(r.get("unit")): (r.get("start"), r.get("end")) for r in context.get("shots") or []}
    out, seen = [], set()
    for row in ((measured or {}).get("measured") or [])[:20]:
        uid = short_unit(row.get("unit_id"))
        if uid in seen:
            continue
        seen.add(uid)
        win = windows.get(uid)
        out.append({"unit": uid, **({"window": list(win)} if win and win[0] is not None else {}),
                    "why": f"S6 实测：背景随人物移动 {row.get('excursion_pct')}% 画宽"
                           + (f"，与人物动作相关 {row.get('coupling')}" if row.get("coupling") is not None else ""),
                    "id": f"S{start_id + len(out) + 1}"})
    return out


def silent_mouth_suspects(measured: dict[str, Any] | None, start_id: int, limit: int = 12) -> list[dict[str, Any]]:
    """S7 muted a voice H3 generated in a unit with no line (``measurements.silent_mouth``, the S7 stray-speech report):
    the lips may keep moving in silence (line owner 2026-11-24, KO E01 0:39).  Pass A / E must confirm by eye;
    ``kind`` silent_mouth, ids continue after ``start_id``."""
    out = []
    for row in ((measured or {}).get("units") or [])[:limit]:
        win = row.get("window")
        if not isinstance(win, (list, tuple)) or len(win) != 2 or _num(win[0]) is None or _num(win[1]) is None:
            continue
        out.append({"kind": "silent_mouth", "unit": short_unit(row.get("unit_id")),
                    "window": [round(float(win[0]), 2), round(float(win[1]), 2)],
                    "why": f"S7 实测：计划无台词的单元里模型生成了 {row.get('speech_seconds')} 秒人声，已被静音——"
                           "看这个时间窗里有没有人嘴在动/像在说话",
                    "id": f"S{start_id + len(out) + 1}"})
    return out


def split_suspects(suspects: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """The S-ids each pass must answer: sound suspects (line tails, music) -> C; letterbox shots -> A; measured edit
    fragments / silent-speaker shots (s7_edit_invariants.measure_cut) -> D."""
    return {"A": {"letterbox": suspects.get("letterbox") or [], "skin_sheen": suspects.get("skin_sheen") or [],
                  "camera_wobble": suspects.get("camera_wobble") or [],
                  # local OCR text runs (2026-11-23, E24): answered, not skimmed as a lead
                  **({"burned_text": suspects["burned_text"]} if suspects.get("burned_text") else {}),
                  # S7-muted voices in units with no line (2026-11-24, KO E01): lips moving in silence
                  **({"silent_mouth": suspects["silent_mouth"]} if suspects.get("silent_mouth") else {})},
            "B": {}, "C": {"tail": suspects.get("tail") or [], "bgm": suspects.get("bgm") or [],
                           # ASR speech inside units the plan gives no line (2026-11-23, E24)
                           **({"stray_voice": suspects["stray_voice"]} if suspects.get("stray_voice") else {})},
            "D": {"fragment": suspects.get("fragment") or []} if suspects.get("fragment") else {},
            # the tail pass re-answers the suspects of its window (clipped by build_pass_prompt)
            "E": {k: suspects[k] for k in ("fragment", "stray_voice", "camera_wobble", "burned_text", "silent_mouth")
                  if suspects.get(k)}}


# ============================================================================================== run
def run_passes(*, video: Path, duration: float, model: str | dict[str, str] | None,
               prices: dict[str, tuple[float, float]], cap: float,
               key: str, base_url: str, post: Callable[..., tuple[int, bytes]], context: dict[str, Any],
               leads: dict[str, Any], suspects: dict[str, list[dict[str, Any]]], anime: bool,
               craft: list[dict[str, str]], measured_pacing: dict[str, Any] | None,
               transcoder: Transcoder | None = None, passes: tuple[str, ...] = PASS_IDS,
               card_maker: Callable[[Path, Path], Path] | None = None,
               redact: Callable[[str, str], str] = lambda t, k: t.replace(k, "<redacted>") if k else t,
               response_text: Callable[[dict[str, Any]], str] | None = None,
               actual_credits: Callable[[str, dict[str, Any]], float] | None = None,
               sleep: Callable[[float], None] | None = None, deadline_s: float = DEADLINE_S,
               clock: Callable[[], float] = time.monotonic) -> dict[str, Any]:
    """Plan, prepare, call (parallel) and merge.  Never raises for a single pass: each pass records its own
    status (OK | SKIPPED | ERROR) and reason.  ``model``: one model for every pass or {pass: model}
    (resolve_pass_models)."""
    sleep = sleep or (lambda seconds: time.sleep(seconds))
    models = _models(model, passes)
    t_end = clock() + deadline_s
    per_pass_suspects = split_suspects(suspects)
    cards = [dict(c) for c in context.get("cards") or []]
    ctx = {**context, "cards": cards}
    with tempfile.TemporaryDirectory(prefix="nalu_gemini_mp_") as tmp:
        work = Path(tmp)
        card_bytes: list[bytes] = []
        for i, card in enumerate(cards):
            if not card.get("image") or not Path(card["image"]).is_file():
                continue
            try:
                jpg = (card_maker or card_jpeg)(Path(card["image"]), work / f"card{i}.jpg")
                card_bytes.append(jpg.read_bytes())
                card["_sent"] = True
            except Exception:  # noqa: BLE001 -- a card that cannot be prepared is left out
                continue
        prompts = {p: build_pass_prompt(p, duration=duration, context=ctx, leads=leads,
                                        suspects=per_pass_suspects[p], anime=anime, craft=craft,
                                        measured_pacing=measured_pacing) for p in passes}
        plan = plan_budget(models, prices, duration=duration, cap=cap,
                           prompt_chars={p: len(t) for p, t in prompts.items()},
                           images={"B": len(card_bytes)}, passes=passes)
        results: dict[str, dict[str, Any]] = {}
        jobs: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        for p in passes:
            cfg = plan["passes"][p]
            if cfg.get("skipped"):
                results[p] = {"status": "SKIPPED", "reason": cfg["skipped"]}
                continue
            try:
                media = prepare_media(video, p, work, duration=duration, transcoder=transcoder)
            except Exception as exc:  # noqa: BLE001
                results[p] = {"status": "ERROR", "reason": f"MEDIA:{type(exc).__name__}:{str(exc)[:160]}"}
                continue
            results[p] = {"status": "PENDING", "model": cfg["model"], "fps": cfg["fps"], "media_resolution": cfg["res"],
                          **({"model_planned": cfg["model_planned"]} if cfg.get("model_planned") else {}),
                          "estimated_credits": cfg["estimate"], "chunks": len(media),
                          "upload_bytes": sum(m["path"].stat().st_size for m in media)}
            for m in media:
                jobs.append((p, cfg, m))

        def call(indexed: tuple[int, tuple[str, dict[str, Any], dict[str, Any]]]
                 ) -> tuple[str, dict[str, Any], dict[str, Any]]:
            index, (p, cfg, m) = indexed
            if index:
                sleep(STAGGER_S * index)
            window = m["window"]
            prompt = prompts[p] if window is None else build_pass_prompt(
                p, duration=duration, context=ctx, leads=leads, suspects=per_pass_suspects[p], anime=anime,
                window=window, craft=craft, measured_pacing=measured_pacing)
            video_bytes = m["path"].read_bytes()
            started = time.time()
            retries = 0

            def attempt(use: str) -> tuple[int, bytes]:
                nonlocal retries
                body = request_body(video_bytes=video_bytes, prompt=prompt, fps=cfg["fps"], res=cfg["res"],
                                    images=card_bytes if p == "B" else None,
                                    thinking_budget=thinking_budget(p, use))
                data = json.dumps(body).encode()
                tries = 0
                while True:
                    left = t_end - clock()
                    if left < 30:
                        return 0, b"DEADLINE"
                    try:
                        status, raw = post(f"{base_url.rstrip('/')}/models/{use}:generateContent", data,
                                           {"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                                           min(CALL_TIMEOUT_S, left))
                    except Exception as exc:  # noqa: BLE001
                        status, raw = 0, f"{type(exc).__name__}:{str(exc)[:200]}".encode()
                    if status == 200 or status not in RETRY_STATUSES or tries >= len(RETRY_BACKOFF_S):
                        return status, raw
                    if t_end - clock() < RETRY_BACKOFF_S[tries] + 60:
                        return status, raw
                    sleep(RETRY_BACKOFF_S[tries])
                    tries += 1
                    retries += 1

            used = cfg["model"]
            status, raw = attempt(used)
            fallback = None
            if status in FALLBACK_STATUSES and used != FALLBACK_MODEL:
                # 2026-11-23: a Pro pass refused (policy / model unavailable) is answered once on Flash
                fallback = {"from": used, "to": FALLBACK_MODEL, "http_status": status,
                            "error": redact(raw.decode("utf-8", errors="replace")[:300], key)}
                used = FALLBACK_MODEL
                status, raw = attempt(used)
            try:
                payload = json.loads(raw.decode("utf-8", errors="replace") or "{}") if status == 200 else {}
            except ValueError:
                payload = {}
            return p, m, {"http_status": status, "payload": payload, "latency_s": round(time.time() - started, 1),
                          "prompt_chars": len(prompt), "retries": retries, "model": used,
                          **({"model_fallback": fallback} if fallback else {}),
                          "error": None if status == 200 else redact(raw.decode("utf-8", errors="replace")[:600], key)}

        answers: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
        started = time.time()
        if jobs:
            with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(jobs))) as pool:
                for p, m, res in pool.map(call, list(enumerate(jobs))):
                    answers.setdefault(p, []).append((m, res))
        wall = round(time.time() - started, 1)
    known = {row["id"]: row for rows_ in suspects.values() for row in rows_}
    for p, rows in answers.items():
        rec = results[p]
        usage_sum: dict[str, int] = {}
        cost = 0.0
        found: list[dict[str, Any]] = []
        checks: list[dict[str, Any]] = []
        notes: list[str] = []
        errors: list[str] = []
        verdicts: list[str | None] = []
        craft_summary = None
        parity: list[dict[str, Any]] | None = None
        for m, res in sorted(rows, key=lambda r: (r[0]["window"] or (0, 0))[0]):
            usage = (res.get("payload") or {}).get("usageMetadata") or {}
            for k in ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount", "totalTokenCount"):
                usage_sum[k] = usage_sum.get(k, 0) + int(usage.get(k) or 0)
            if usage and actual_credits:
                cost += actual_credits(res.get("model") or rec["model"], usage)
            if res.get("model_fallback"):
                rec["model_fallback"] = res["model_fallback"]
                if res.get("http_status") == 200:
                    rec["model"] = res["model"]
            rec["latency_s"] = max(rec.get("latency_s") or 0, res.get("latency_s") or 0)
            rec["retries"] = (rec.get("retries") or 0) + int(res.get("retries") or 0)
            if res.get("http_status") != 200:
                errors.append(f"HTTP_{res.get('http_status')}")
                rec.setdefault("error_body", res.get("error"))
                continue
            text = response_text(res.get("payload") or {}) if response_text else ""
            window = m["window"]
            try:
                parsed = parse_pass(text, pid=p, duration=duration, offset=window[0] if window else 0.0,
                                    window_len=(window[1] - window[0]) if window else None, known_suspects=known)
            except (ValueError, TypeError) as exc:
                errors.append(f"UNPARSABLE_ANSWER:{type(exc).__name__}")
                rec.setdefault("raw_text", text[:1500])
                continue
            found += parsed["findings"]
            found += promote_line_log(parsed.get("line_log") or [], parsed["findings"])
            found += promote_shot_checklist(parsed.get("shot_log") or [], parsed["findings"], p)
            if parsed.get("cast_compare"):
                found += promote_cast_compare(parsed["cast_compare"], found)
                rec["cast_compare"] = ((rec.get("cast_compare") or []) + parsed["cast_compare"])[:30]
            for log in ("shot_log", "line_log"):
                if parsed.get(log) is not None:
                    rec[f"{log}_rows"] = (rec.get(f"{log}_rows") or 0) + parsed[f"{log}_rows"]
                    rec[log] = ((rec.get(log) or []) + parsed[log])[:LOG_MAX_ROWS]
            checks += parsed["suspect_checks"]
            notes += parsed["parse_notes"]
            verdicts.append(parsed["verdict"])
            craft_summary = craft_summary or parsed.get("craft_summary")
            if parsed.get("unit_parity") is not None:
                parity = (parity or []) + parsed["unit_parity"]
        rec.update({"usage": usage_sum, "cost_credits": round(cost, 3)})
        ok_chunks = len(rows) - len(errors)
        if ok_chunks == 0:
            rec.update({"status": "ERROR", "reason": errors[0] if errors else "NO_ANSWER"})
            continue
        if parity is not None:
            rec["unit_parity"] = fold_unit_parity(parity)
            found += promote_unit_parity(rec["unit_parity"], ctx.get("plan_units") or [], found)
        rec.update({"status": "OK", "findings": found, "suspect_checks": checks, "parse_notes": notes,
                    "verdict": "REJECT_RECUT" if "REJECT_RECUT" in verdicts else
                    ("PASS" if "PASS" in verdicts else None),
                    **({"partial_errors": errors} if errors else {}),
                    **({"craft_summary": craft_summary} if craft_summary else {})})
    merged = merge(results, suspects, ctx.get("plan_units") or None)
    summary = {p: {k: v for k, v in (results.get(p) or {}).items() if k not in ("findings", "suspect_checks",
                                                                                   "craft_summary", "unit_parity")}
               | {"findings": len((results.get(p) or {}).get("findings") or [])} for p in passes}
    return {"plan": plan, "passes": summary, "merged": merged, "wall_s": wall,
            "cost_credits": round(sum((results.get(p) or {}).get("cost_credits") or 0.0 for p in passes), 3),
            "usage": {k: sum(int(((results.get(p) or {}).get("usage") or {}).get(k) or 0) for p in passes)
                      for k in ("promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount", "totalTokenCount")},
            "ok_passes": [p for p in passes if (results.get(p) or {}).get("status") == "OK"],
            "cards_sent": sum(1 for c in cards if c.get("_sent"))}
