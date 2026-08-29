#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""E44 v5 四层与九门证据的构建器第一段（Writer 自用，R395）。

canonical → directing → generation contract。所有 SHA 逐件实算，不写声明值。
数据源＝workflow/claude_writer_agent/scripts/_gen_e44_v5_data.py（手写逐镜表，随仓库落盘）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import sys
from pathlib import Path

# ★★R394-F01 处方落地（本集第一次执行）：**构建器最后一次写盘必须在 dispatcher finish 之前**。
# 第二段（manifest／门证据）要在 finish 之后才能绑 receipt，而它 import 本段。
# 因此本段带 READ_ONLY 模式：被第二段 import 时只重算并**逐字节校验盘上文件**，一个字节也不重写。
READ_ONLY = os.environ.get("E44_V5_BUILDER_READ_ONLY") == "1"


def write_or_verify(path: Path, content: str) -> None:
    """READ_ONLY 时不写盘，只断言盘上内容与本次重算逐字节相同（确定性证明）。"""
    if READ_ONLY:
        assert path.is_file(), f"READ_ONLY 模式下文件不存在：{path}"
        on_disk = path.read_text(encoding="utf-8")
        assert on_disk == content, f"★盘上内容与重算不一致（构建器非确定性或文件被改动）：{path}"
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workflow/claude_writer_agent/scripts"))
from _gen_e44_v5_data import S as SCENES  # noqa: E402
from _gen_e44_v5_data import KEY_QUOTES  # noqa: E402
from _gen_e44_v5_data import AUDIENCE_ALREADY_KNOWS  # noqa: E402

SCRIPTS = ROOT / "workflow/claude_writer_agent/scripts"
QA = ROOT / "qa/e44_v5_script_phase_20260828"
SRCMAP = ROOT / "qa/source_realread_map_e44_v5_20260828"
EVID = QA / "evidence"
RATE = 4.9
TARGET = 180.0
# ★对白占比：注册门门限 0.35。E43 v6 已按 seq=39 c5 把自限从 0.28 放宽到 0.33，本集沿用 0.33。
SELF_LIMIT_RATIO = 0.33
AUTH = (
    "SUPERVISOR_ORDERS seq=38 conditions[3] (ROGER-20260827 修正合并表：新E44＝ch48《金豬》＋ch49《上三位》，"
    "且明写『砍掉的只有密谍司等级俸禄与十二生肖编制科普』)"
    " + seq=37 (压缩令＋忠实门改口径：主线因果链完整性＋源章关键转折与关键台词是否落地；取舍三标准；禁机械模板)"
    " + seq=36 conditions[4] (CL2X-1275 O2 裁定，BLOCK：源章 key_quote 逐字落地优先，数值自限不得压过源章绑定)"
    " + seq=35 (ROGER-20260823-NO-ASKING-JUST-REWRITE：不对就整集重写、不请示、不打补丁)"
    " + ROGER-20260827-CHARACTERIZATION-NOT-COMPRESSIBLE"
    " + ROGER-20260827-FS1-CLUSTER-QUOTA"
)
PUNCT = r"[\s，。？！、；：,.!?;:—－·]"


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(p: Path) -> str:
    return sha_bytes(p.read_bytes())


def dump(p: Path, obj) -> str:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sha_file(p)


def spoken(text: str) -> int:
    return len(re.sub(PUNCT, "", text))


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


# ---------------------------------------------------------------- 逐镜展开
flat = []
idx = 0
for scene in SCENES:
    for j, row in enumerate(scene["lines"]):
        text, dur, speaker, kind, cam, sub, motion, mtype = row
        body = f"{speaker}：{text}" if speaker else text
        flat.append(
            dict(
                n=idx + 1,
                scene=scene,
                scene_id=scene["scene_id"],
                shot_id=f"{scene['scene_id']}-{j + 1:02d}",
                text=text,
                body=body,
                dur=dur,
                speaker=speaker,
                kind=kind,
                camera=cam,
                subspace=sub,
                motion=motion,
                move_type=mtype,
            )
        )
        idx += 1

total = round(sum(s["dur"] for s in flat), 6)
assert abs(total - TARGET) < 1e-6, f"总时长 {total} != {TARGET}"

start = 0.0
for s in flat:
    s["start"] = round(start, 3)
    start = round(start + s["dur"], 6)

scene_seconds = {sc["scene_id"]: round(sum(l[1] for l in sc["lines"]), 3) for sc in SCENES}
assert max(scene_seconds.values()) <= 22.0, scene_seconds

# ★逐镜台词时长下限断言
for s in flat:
    if s["speaker"]:
        assert s["dur"] >= spoken(s["text"]) / RATE, (s["shot_id"], s["dur"], spoken(s["text"]))

# ★camera 与 subspace 全片唯一
assert len({s["camera"] for s in flat}) == len(flat), "camera 串有重复"
assert len({s["subspace"] for s in flat}) == len(flat), "subspace 串有重复"

# ---------------------------------------------------------------- 一层 canonical
head = [
    "# 《青山》E44 叙事权威 v5（narrative canonical）",
    "",
    "集号 E44｜片名《金豬／上三位》｜目标时长 180 秒",
    f"授权 {AUTH}",
    "ch48＋ch49 逐拍落点、六条 key_quote 的逐字落点、合并与舍弃逐条申报，见 `E44_manifest_v5.json`。",
    "唯一剧情来源 原著第 48 章《金豬》（实读记录对象，8 拍）＋第 49 章《上三位》（实读记录对象，9 拍）。",
    "源绑定依据 configs/episode_source_map_v2_observed_20260821.json（OBSERVED）＋ SUPERVISOR_ORDERS seq=38 conditions[3] 修正合并表：新E44＝ch48＋ch49。"
    "★本集是**一夜之间他从卖东西的人变成被人买下的人**：白天他还在推掉一门稳赚的买卖，"
    "半夜有人隔着门板报出名号，把一份他没有议过价的差事放在了他面前。"
    "**这一次没有人问他要多少钱。**",
    "季位 第一季第四十四集（第一季＝E01–E76 收在 ch78；ch42＋ch43＋ch44 已由 E41 v17 承载，ch45 已由 E42 v11 承载，ch46＋ch47 已由 E43 v6 承载）。",
    "承接（取自 E43 v6 终局）：街口檐下世子开价十两买那半句诗，他答『成交。』，把那张药方递了过去。"
    "★E44 从**药方刚离手的那一刻**接上：三个人回到面馆里，那一顿还没有吃完。",
    "",
    "★★**观众已知，本集不得复证**（承 E41 v17 断点收口）：『云羊与皎兔已下狱』与『情报已递到百鹿阁后院的司曹』"
    "两条 ch48 既定事实**已在 E41 交给过观众**。本集因此不把它们当新揭示："
    "S07 让金猪把入狱这条当见面礼递出来，而**他的脸没有动**——"
    "这一格真正的新信息是『金猪发现他早就知道』；递情报那条则一个字也不复述，"
    "只留 S05 那一句两个字的自语与一眼城北。",
    "",
    "★本集是两章合并的第二集（seq=38 conditions[3]）。合并的两条前提逐条守住："
    "①**不影响任何动作戏或高潮戏**——ch48／ch49 全无 set-piece 打斗，无高潮章被压；"
    "②**不让观众看得莫名其妙**——按该条明令，被砍的只有**密谍司等级俸禄**与**十二生肖甲乙丙丁编制**两段纯世界观科普；"
    "编制那条的落点靠源章自己的 key_quote『铁打的上三，流水的下九』一句承载，"
    "**规矩留下了，课堂删掉了**。",
    "",
    "本集终局：他刚在街口把一门长期生意推掉，半夜就被人无价买断；"
    "而密谍司交给他的第一件差事，是去盯住今夜替他挡过话的那个人。"
    "**推掉一笔小买卖的人，被一笔他不能拒绝的买卖买走了。**",
    "全集梗概（本段为概述，逐格事实以下方分场正文为准）：面馆里世子解释王府送膳要走一炷香、饭到面前早凉了，"
    "小和尚顺手把他的碗端去灶口热；那十两诗钱世子摸了两下荷包没摸出来，"
    "白鲤把一粒金瓜子按在桌上说她来付，敞开的荷包里不是金瓜子就是银花生——"
    "陈迹当场看破世子的钱袋一直是空的。门口告辞时世子提出以后他的诗全买，"
    "被『佳句天成，妙手偶得』推了回去，那锭银子原样回到掌心。"
    "三个人走进街尾的暗处之后，世子问他到底图什么，小和尚说他有赌性、赌的不是钱而是命，"
    "世子的脚步停在街心。子夜医馆后院，他用刀背刮墙根的白霜装进竹筒，"
    "竹筒沉了半截，他把今晚两个字说出了口，抬头看了一眼城北；乌云从墙头跳下来蹲在筒边。"
    "门板上响了三下，他把竹筒塞进袖子；门外的人报出『密谍司，金猪』——"
    "比他预估的整整早了一个月。门开处站着一个戴斗笠穿草鞋的人，笑容和煦，"
    "第一句话是他来洛城第一件事就是来找他；他递出云羊皎兔下狱这条见面礼，"
    "而陈迹的表情一分未变，金猪的笑容因此停了半瞬，只确认了一句他已经知道。"
    "进堂之后金猪摘下斗笠，陈迹试探他从京城走了几日，得到的回答是他根本不是从京城来的——"
    "那两个人进洛城那天他就在孟津大营，这一句让他撑在长案上的指节失了血色。"
    "金猪接着揭底：内相早知道那两个成事不足，他在城外等的就是这一天；"
    "陈迹看透提拔就是为了这一刻；金猪给了他一句『铁打的上三，流水的下九』，"
    "并宣布内相特批他入司。后院有东西倒了，金猪瞬间从堂上消失，房梁上多了一道影。"
    "后院里挂在墙头的是白鲤，她为省过路费不肯用梯子，摔进菜畦，"
    "把四枚银花生拍在石桌上骂他陈黑心；跟着下墙的还有三个人。"
    "妹妹朱灵韵当面把他定成王府养着的下人，白鲤与世子先后回嘴，"
    "朱灵韵红着眼睛扶梯翻回王府；陈迹退还一枚银花生，说不该赚的他不赚，"
    "又叫猫儿带上狗儿陪世子去喝酒。人都散了以后金猪从房梁上落下来，"
    "以听见那位郡主替他说话为由，派下第一件差事：盯住世子，行踪全报。"
    "院子里传来世子的笑声，他隔着袖子攥住了那支竹筒。",
    "",
    "本文件是本集唯一剧情事实源，只写事实、可表演行动与必要对白。",
    "",
]
lines_md = list(head)
for scene in SCENES:
    lines_md.append(
        f"## {scene['scene_id']}｜{scene['location_id']}｜{scene['time_block_id']}｜{scene['thread']}"
    )
    lines_md.append("")
    for s in [x for x in flat if x["scene_id"] == scene["scene_id"]]:
        lines_md.append(s["body"])
        lines_md.append("")
canonical_md = "\n".join(lines_md).rstrip("\n") + "\n"

BANNED = [
    "shot_treatment", "first_frame_motion_state", "ambient_life", "spatial_action_contract",
    "voice_asset_id", "SUBSPACE-ID", "GLOBAL-SPACE-MAP-ID", "首帧动势", "景别", "运镜",
    "palette", "负向提示词",
]
for term in BANNED:
    assert term not in canonical_md, f"canonical 含生产字段：{term}"

# ★上游硬约束：E43 v6 已交付的终局事实，本集承接段必须逐项点住
E43_CARRY_LOCKS = ["成交", "药方", "十两", "世子", "小和尚", "白鲤"]
for token in E43_CARRY_LOCKS:
    assert token in canonical_md, f"E43 承接项缺失：{token}"

# ★★观众已知项必须在正文里被明确标注为不复证（防下一轮写手把它当新揭示）
assert "观众已知，本集不得复证" in canonical_md
assert len(AUDIENCE_ALREADY_KNOWS) == 2

# ★★本轮头号硬约束：ch48／ch49 六条 key_quote 逐字落地（seq=36 c4，BLOCK）。跑不过就不出件。
for kid, kq in KEY_QUOTES.items():
    assert kq["landed"] in canonical_md, f"key_quote 未逐字落地：{kid} {kq['landed']}"
    hit = [x for x in flat if x["shot_id"] == kq["shot"]]
    assert len(hit) == 1 and kq["landed"] in hit[0]["text"], f"key_quote 落点不符：{kid}"
    assert hit[0]["speaker"] == kq["speaker"], f"key_quote 说话人不符：{kid}"

canonical_path = SCRIPTS / "E44_NARRATIVE_CANONICAL_v5.md"
write_or_verify(canonical_path, canonical_md)
S_SCRIPT = sha_file(canonical_path)
visible_chars = len(re.sub(r"\s+", "", canonical_md))
CHAR_LIMIT = int(1400 * (TARGET / 60))
assert visible_chars <= CHAR_LIMIT, (visible_chars, CHAR_LIMIT)
for s in flat:
    assert canonical_md.count(s["body"]) == 1, f"evidence_text 不唯一：{s['body']}"

# ---------------------------------------------------------------- story moves
moves = []
prev_result = "STATE-E44-CARRY-IN-FROM-E43-V6"
for i, s in enumerate(flat):
    mid = f"MOVE-E44-{i + 1:03d}"
    result = f"STATE-E44-{i + 1:03d}"
    moves.append(
        dict(
            story_move_id=mid,
            scene_id=s["scene_id"],
            move_type=s["move_type"],
            causal_cluster_id=f"CLUSTER-E44-{i + 1:03d}",
            cause_state_token=prev_result,
            result_state_token=result,
            action=s["text"],
            external_change=s["motion"],
            predecessor_move_ids=[] if i == 0 else [f"MOVE-E44-{i:03d}"],
            forces_next_story_move_id="" if i == len(flat) - 1 else f"MOVE-E44-{i + 2:03d}",
            evidence_text=s["body"],
        )
    )
    s["story_move_id"] = mid
    prev_result = result

AGENCY = {"IRREVERSIBLE_ACTION", "POWER_SHIFT", "RELATIONSHIP_SHIFT", "FORCED_CHOICE"}
agency_moves = sum(1 for m in moves if m["move_type"] in AGENCY)
run = best = 0
for m in moves:
    run = 0 if m["move_type"] in AGENCY else run + 1
    best = max(best, run)
assert best <= 1, f"连续非 agency 步 {best}"
assert agency_moves / len(moves) >= 0.5

# ---------------------------------------------------------------- 静默与对白读数
SILENCE_REASON: dict[str, str] = {
    "E44-S05": "★8.2 秒无台词是**本集把一个念头变成一件活的那段过程**：墙根泛白 → 刀背刮过去 → 竹筒沉了半截。"
               "★这三格必须没有台词：上一集他只是在墙根上刮了一下、在拇指上捻散；"
               "**本集观众要自己看出来他现在是有计划、有工具、有存货的**——"
               "一句解释就会把『他在做什么』变成『他在说他在做什么』，火药线的起点就泄了。",
    "E44-S10": "★9.2 秒无台词是**全集唯一一次纯身体的喜剧**：墙头挂着一个人 → 掉进菜畦 → "
               "梯子就在三尺外 → 四枚银花生拍在石桌上。"
               "★这一段不许补任何台词：**观众必须先在暗处看见『有东西翻进来了』的杀机**（金猪正在梁上听），"
               "**再自己发现那只是一个不肯付过路费的郡主**。"
               "任何一句提前出口的台词都会把这个落差拆成两件事。",
}
sil_windows = []
for scene in SCENES:
    ss = [x for x in flat if x["scene_id"] == scene["scene_id"]]
    cur = 0.0
    longest = 0.0
    for x in ss:
        if x["speaker"]:
            longest = max(longest, cur)
            cur = 0.0
        else:
            cur += x["dur"]
    longest = max(longest, cur)
    sil_windows.append(
        dict(
            scene_id=scene["scene_id"],
            duration_seconds=round(longest, 3),
            ruler="场内最长无台词区间（E61–E90 既有口径）",
            reason=SILENCE_REASON.get(scene["scene_id"], ""),
        )
    )
max_in_scene_silence = max(w["duration_seconds"] for w in sil_windows)
long_windows = [w for w in sil_windows if w["duration_seconds"] > 8.0]
for w in long_windows:
    assert w["reason"], f"{w['scene_id']} 长静默缺理由"
assert len(long_windows) <= 3, len(long_windows)

cross = 0.0
worst_cross = 0.0
for x in flat:
    if x["speaker"]:
        worst_cross = max(worst_cross, cross)
        cross = 0.0
    else:
        cross += x["dur"]
worst_cross = round(max(worst_cross, cross), 3)
assert max_in_scene_silence <= 20.0 and worst_cross <= 20.0

dialogue = [x for x in flat if x["speaker"]]
spoken_chars = sum(spoken(x["text"]) for x in dialogue)
median_line = float(statistics.median(spoken(x["text"]) for x in dialogue))
max_line = max(spoken(x["text"]) for x in dialogue)
assert 6 <= median_line <= 9, median_line
# ★单句上限：key_quote 不受限（seq=36 c4）；其余 ≤16（seq=37 c4 爆发段口径，宪章硬线 ≤25）
KEY_TEXTS = {kq["landed"] for kq in KEY_QUOTES.values()}
non_key = [x for x in dialogue if not any(k in x["text"] for k in KEY_TEXTS)]
assert max(spoken(x["text"]) for x in non_key) <= 16, "非 key_quote 单句超过 16 字"
dialogue_ratio = round(spoken_chars / RATE / TARGET, 5)
assert dialogue_ratio <= SELF_LIMIT_RATIO, dialogue_ratio
assert dialogue_ratio <= 0.35, dialogue_ratio  # 注册门门限，双侧都跑

scene_dialogue_ratio = {}
for scene in SCENES:
    ss = [x for x in flat if x["scene_id"] == scene["scene_id"]]
    c = sum(spoken(x["text"]) for x in ss if x["speaker"])
    scene_dialogue_ratio[scene["scene_id"]] = round(c / RATE / scene_seconds[scene["scene_id"]], 5)

ACTION_SCENE = "E44-S05"
action_ratio = scene_dialogue_ratio[ACTION_SCENE]
assert action_ratio <= 0.20, action_ratio
# ★申报纪律：申报的动作场必须**有台词**，不得申报零台词场去换余量（R375 立的口径）
assert any(x["speaker"] for x in flat if x["scene_id"] == ACTION_SCENE), "申报的动作场不得零台词"

order = [sc["scene_id"] for sc in SCENES]
locs = [sc["location_id"] for sc in SCENES]
threads = [sc["thread"] for sc in SCENES]
tbs = [sc["time_block_id"] for sc in SCENES]
max_same_loc = 1
run = 1
for a, b in zip(locs, locs[1:]):
    run = run + 1 if a == b else 1
    max_same_loc = max(max_same_loc, run)
assert max_same_loc <= 2, max_same_loc
cross_cuts = sum(1 for a, b in zip(threads, threads[1:]) if a != b)
time_jumps = sum(1 for a, b in zip(tbs, tbs[1:]) if a != b)
assert cross_cuts >= 3
# ★time_jumps＝1：酉时末的那一顿面 → 子夜的医馆。源章 ch48 自带（『夜深後陳跡起身刮取院牆牆霜』）。
assert time_jumps == 1, time_jumps
assert 8 <= len(SCENES) <= 12, len(SCENES)
assert len(SCENES) == 12, "★本集 12 场：两章十七拍，场数由内容决定（seq=37 c5 禁 ~10 场模板）"
# ★地点预算：新增 1 处（门限 2，余量 1）。
NEW_LOCATIONS = {
    "LOC-TAIPING-YIGUAN-ZHENGTANG",
}
EXISTING_LOCATIONS = {
    "LOC-ZHENGHEJIE-MUXINZHAI",
    "LOC-ZHENGHEJIE",
    "LOC-TAIPING-YIGUAN-HOUYUAN",
    "LOC-TAIPING-YIGUAN-MENKOU",
}
assert set(locs) == NEW_LOCATIONS | EXISTING_LOCATIONS, set(locs)
assert len(NEW_LOCATIONS) <= 2, NEW_LOCATIONS
assert len(set(locs)) == 5, set(locs)

non_advancing = [x for x in flat if x["kind"] == "F"]
non_advancing_pct = round(100.0 * len(non_advancing) / len(flat), 3)
assert non_advancing_pct <= 15.0

# ★爆发段双侧断言（注册门要求 20≤时长≤40 且段 ASL ≤2）
BURST_SCENES = ("E44-S06", "E44-S07")
burst_seconds = round(sum(scene_seconds[s] for s in BURST_SCENES), 3)
burst_shots = len([x for x in flat if x["scene_id"] in BURST_SCENES])
burst_asl = round(burst_seconds / burst_shots, 4)
assert 20.0 <= burst_seconds <= 40.0, burst_seconds
assert burst_asl <= 2.0, burst_asl

# ★全集 ASL 必须落回 2.5–3.5s 基线（seq=37 c5）
EPISODE_ASL = round(TARGET / len(flat), 4)
assert 2.5 <= EPISODE_ASL <= 3.5, EPISODE_ASL

# ---------------------------------------------------------------- 二层 导演稿
d = []
d.append("# 《青山》E44 导演稿 v5（directing script）")
d.append(
    f"集号 E44｜片名《金豬／上三位》｜目标时长 {TARGET} 秒｜{len(SCENES)} 场｜{len(flat)} 镜｜"
    f"ASL {EPISODE_ASL} 秒（seq=37 c5：对话段 2.5–3.5s 基线，禁 ~100 镜／ASL 1.5s 模板）"
)
d.append(f"授权 {AUTH}")
d.append(
    f"上游唯一来源 `E44_NARRATIVE_CANONICAL_v5.md`（sha256 {S_SCRIPT}）。"
    "本稿是**单向派生**：不新增、不删改任何剧情事实；本稿只决定怎么拍。"
)
d.append(
    "★空间纪律：先整集空间图 → 地点图 → 子空间 → 人物／道具站位 → 动作轨迹，逐层收窄；关键帧前须查 native registry。"
)
d.append(
    "★声音纪律：可见人物说话的镜一律用同一多模态任务的原生声画，不设计后配音覆盖口型。"
    "★本集全片无 BGM，理由：**本集的声音本身就是结构**——"
    "前四场是热闹（灶火、人声、街上的风），后八场是一间只点一盏灯的屋子和一个院子。"
    "任何铺底旋律都会把那道门槛抹平，而**观众能不能感到冷，全靠那道门槛**。"
    "★需要单独设计的有四处："
    "一是 S05 全场——**只有刀背刮墙的声音**，这是全集最安静也最危险的一段；"
    "二是 S06 那三下敲门——**第一次三下要实，第二次三下一下比一下轻**，"
    "轻不是礼貌，是他知道屋里的人已经听见了；"
    "三是 S09 末尾『后院有一样东西倒了。』——**那一声必须比敲门更小**，"
    "小到观众和陈迹同时怀疑自己听错了，金猪却已经上梁；"
    "四是 S12 那阵笑声——**院子里的世子在笑，堂上刚接到盯住他的命令**，"
    "笑声要穿门进来，不做任何衰减。"
)
d.append(
    "★本集最容易拍错的三件事："
    "**第一，金猪不许有一秒钟的反派相。**他是佃户：草鞋、斗笠、粗布、笑容和煦。"
    "全集他只有两次不笑——S07-06 笑容停半瞬、S12-01 落地无声；"
    "**其余每一格他都在笑，包括说『铁打的上三，流水的下九』的时候**。"
    "不给阴影打光、不给低角度仰拍、不给眼神特写；**他的可怕全部来自内容与和煦的落差**。"
    "**第二，S05 的墙霜不许拍成仪式。**刀背刮墙就是一件粗活："
    "不给慢镜、不给特效、不给发光，**不许闪回到上一集的墙根**。"
    "观众该看见的只是一个人半夜在自家墙根上干活，而**这活的意义要到很多集之后才兑现**。"
    "**第三，S10 不许拍成打斗前戏。**墙头那个悬着的影子必须先被当成危险（因为梁上有人在听），"
    "**但落地之后一格就要塌成喜剧**：她坐在菜畦里，一只鞋掉在半尺外，梯子在三尺外。"
    "不给慢动作、不给紧张音效——**紧张来自我们知道梁上有人，而她不知道**。"
)
d.append(
    f"★静默口径（两把尺都算）：场内最长无台词区间 **{max_in_scene_silence} 秒**，跨场界最长 **{worst_cross} 秒**，"
    f"两者都 ≤20；>8 秒的场内窗口共 **{len(long_windows)}** 条。"
)
d.append(
    "★表情弧（ROGER-20260827：人物刻画不属于可压缩项）——"
    "**陈迹**：S02 看破钱袋时只把自己的碗转了半圈——**他从不当众拆穿人**；"
    "S03 推掉长期生意时两手一直笼在袖子里，**他连碰都不碰那锭银子**；"
    "S05 是全集他唯一一次独处，**手上有活、眼睛在城北**，这是他最完整的一次；"
    "S06 手停在门闩上——**全集唯一一次犹豫**，只有一格半；"
    "S07-05 脸上没有动，**这一格是他这一晚最大的失误**，因为金猪看见了；"
    "S08 手指压白在案沿上，**惊讶被他压在手上而不是脸上**；"
    "S09 听完规矩之后退了半步背贴药柜——**他在一间自己的屋子里退了一步**；"
    "S11 退还银花生时把剩下三枚收进袖子，**他分得清哪一枚不该拿**；"
    "S12 隔着袖子攥住竹筒——**全集最后一格，他攥的是唯一一样没有人知道的东西**。"
    "**金猪**：从头到尾一个笑容，只在 S07-06 停了半瞬（那是他这一夜唯一一次没算到）；"
    "S09 用两根手指讲规矩——**一根按住不动，一根划过案面**，这比任何台词都清楚；"
    "S12 落地无声，**这是他第一次让陈迹知道他一直能做到这件事**。"
    "**白鲤**：S02 按下金瓜子时看的是陈迹不是世子；S10 坐在菜畦里骂人，**骂的时候她在笑**；"
    "S11 光着一只脚站起来替他说话——**她是全集第一个站起来的人**。"
    "**世子**：S01 说饭凉了的时候手指在桌上划了一道长线（那是他每天等饭的距离）；"
    "S03 被推回银子时手还托着；S04 脚步停在街心——**那是他第一次真正想懂这个人**；"
    "S11 挡在两人中间。"
    "**小和尚**：S01 一言不发把碗端去热；S04 说完那句判词头都没有转向世子——"
    "**他不是在评价，他是在陈述**。"
    "**朱灵韵**：S11 说『下人』时一直在拍自己袖子上的土，**她没有看被她定性的那个人**；"
    "上梯时眼睛是红的——**她不是坏，她是第一次被两个人同时驳回**。"
)
d.append("")
d.append("## 整集空间图")
d.append("| 层 | 内容 |")
d.append("|---|---|")
d.append("| 政和街穆新斋堂内（S01／S02） | 灶口、长桌与条凳、碗摞、门框那一条亮边。**承 E43 同一间铺子，但灯火压低了一档，因为夜已经深了** |")
d.append("| 政和街·穆新斋门口与街尾（S03／S04） | 门里铺出三尺暖光、幌子、巷口的风、街尾没有灯只有天光。**告辞在光里，判词在暗里** |")
d.append("| 太平医馆后院（S05／S10／S11） | 西墙墙根与碱花、井台、石桌、菜畦、东墙墙头与靠在三尺外的梯子、堂屋那扇一直开着的门 |")
d.append("| 太平医馆临街门（S06／S07） | 门板、门闩、门缝那条冷白细线、门槛。**全集的转折就发生在这道门槛的两侧** |")
d.append("| 太平医馆正堂（S08／S09／S12） | 药柜一面墙、长案一张、门后的木钉、一盏将尽的油灯、**照不到的房梁** |")
d.append(
    "★两半之间的唯一通道是**那道门槛**：S07 门开之前这部戏是他的城，门开之后这座城里多了一个一直在的人。"
    "★180°轴：面馆沿长桌东西向，灶口恒在画面左侧（承 E43 同一轴）；"
    "门口以门板法线为轴，**陈迹恒在门内画左、金猪恒在门外画右，门开之后两人不换边**；"
    "后院以西墙—东墙连线为轴，梯子恒在画右、堂屋门恒在画左后方；"
    "正堂以长案为轴，药柜恒在画左，**房梁恒在画框上缘之外——直到 S09-07 才第一次进画**。"
    "★光：面馆是灶火暖橙自侧后；街上只有天光与门里漏出的暖边；"
    "后院是半个月亮的冷白加堂屋门里那一小片暖；正堂只有一盏油灯，**S12 灯油见底、焰头开始跳**。"
)
d.append("")
d.append("## 逐场设计")
for scene in SCENES:
    ss = [x for x in flat if x["scene_id"] == scene["scene_id"]]
    dl = [x for x in ss if x["speaker"]]
    d.append("")
    d.append(
        f"### {scene['scene_id']}｜{scene['title']}｜{scene_seconds[scene['scene_id']]}s｜{len(ss)} 镜｜{scene['thread']}"
    )
    d.append(
        f"- 地点 ID `{scene['location_id']}`｜时间块 `{scene['time_block_id']}`｜内外景 {scene['interior_exterior']}"
        f"｜色温 {scene['palette']}"
    )
    d.append(
        f"- 时段状态 `{scene['time_of_day']}`｜天气状态 `{scene['weather']}`（★时段与天气只能从 scene_state 注入，本稿无权改动）"
    )
    d.append(f"- 本场转折（power shift）：{scene['turn']}")
    d.append(
        f"- 本场台词 {len(dl)} 句／{sum(spoken(x['text']) for x in dl)} 可听字；"
        f"场内最长无台词区间 {[w['duration_seconds'] for w in sil_windows if w['scene_id'] == scene['scene_id']][0]} 秒；"
        f"本场对白占比 {scene_dialogue_ratio[scene['scene_id']]}"
    )
    d.append("")
    d.append("| 镜 | 起 | 长 | 机位 | 子空间 | 画面 | 台词 |")
    d.append("|---|---|---|---|---|---|---|")
    for x in ss:
        pic = x["text"] if not x["speaker"] else f"{x['speaker']}把这句说出来"
        say = f"{x['speaker']}：{x['text']}" if x["speaker"] else "—"
        d.append(
            f"| {x['shot_id']} | {x['start']} | {x['dur']} | {x['camera']} | {x['subspace']} | {pic} | {say} |"
        )
directing_md = "\n".join(d) + "\n"
directing_path = SCRIPTS / "E44_DIRECTING_SCRIPT_v5.md"
write_or_verify(directing_path, directing_md)
S_DIR = sha_file(directing_path)

# ---------------------------------------------------------------- 三层 生成合同
contract = {
    "schema": "qingshan.generation_contract.v3",
    "episode": "E44",
    "version": 5,
    "title": "金豬／上三位",
    "authorization": AUTH,
    "derived_from": {
        "directing_script": rel(directing_path),
        "directing_script_sha256": S_DIR,
        "narrative_canonical": rel(canonical_path),
        "narrative_canonical_sha256": S_SCRIPT,
    },
    "vendor_and_model_bound": False,
    "paid_tasks_authorized": False,
    "global_space_map_id": "GLOBAL-SPACE-E44-MUXINZHAI-ZHENGHEJIE-YIGUAN-MENKOU-ZHENGTANG-HOUYUAN-YOUSHIMO-DAO-ZIYE",
    "runtime_seconds": TARGET,
    "scenes": len(SCENES),
    "asl_seconds": EPISODE_ASL,
    "shots": [
        {
            "shot_id": x["shot_id"],
            "scene_id": x["scene_id"],
            "start_seconds": x["start"],
            "duration_seconds": x["dur"],
            "duration_plan": {
                "basis": "台词语速＋动作完成点＋反应余量逐镜单算（ROGER-20260718 逐镜生成时长硬门）",
                "spoken_characters": spoken(x["text"]) if x["speaker"] else 0,
                "speech_seconds": round(spoken(x["text"]) / RATE, 3) if x["speaker"] else 0.0,
                "action_completion": x["motion"],
            },
            "camera": x["camera"],
            "subspace_id": x["subspace"],
            "frame_content": x["text"],
            "dialogue": (f"{x['speaker']}：{x['text']}" if x["speaker"] else ""),
            "native_av": bool(x["speaker"]),
            "first_frame_motion_state": x["motion"],
            "negative_prompts": [
                "画面内不得出现可读中文长句、匾额文字、药柜抽屉的药名、招牌名目或任何可读字号",
                "不得出现近静止站桩形态（无对白且无动作 >4 秒）",
                "不得用后期变速或冻结帧补足时长",
                "★金猪不得有任何反派视觉标记：不给低角度仰拍、不给阴影打光、不给眼神特写、不给兵器",
                "★S05 刀背刮墙不得做成特效或发光：白霜只是返碱，不得预示爆炸、不得闪回上一集的墙根",
                "★S10 白鲤落地之后不得用慢动作或紧张音效：紧张来自梁上有人在听，不来自镜头",
            ],
        }
        for x in flat
    ],
    "audio_contract": {
        "bgm": "NONE_WHOLE_EPISODE",
        "bgm_reason": "本集的声音本身就是结构：前四场是灶火、人声与街风，后八场是一盏灯的屋子与一个院子。"
                      "铺底旋律会把那道门槛抹平，而观众能不能感到冷全靠那道门槛。",
        "native_dialogue_only": True,
        "diegetic_anchors": [
            "S01 灶口与蒸汽压低一档的堂内声；碗被端走时瓷底擦过木面的一声",
            "S02 金瓜子被按进木纹的闷响；荷包敞口时金银互碰的细响",
            "S03 门里的暖光与门外的风声在门槛上分层；银锭落回掌心的一声",
            "S04 ★街尾无灯：更夫的梆子响过一次，风把幌子的声音从背后带过来",
            "S05 ★全场只有刀背刮墙的声音与白粉落进竹筒的沙沙；猫落地几乎无声",
            "S06 ★三下敲门要实，第二次三下一下比一下轻——轻不是礼貌，是他知道屋里已经听见",
            "S07 门开时夜气与药气对冲的空气声；草鞋踏过门槛没有声音",
            "S08 油灯焰头被余风推偏又立回；碗底与木案相碰的一声",
            "S09 ★『后院有一样东西倒了。』那一声必须比敲门更小；金猪上梁全程无声",
            "S10 人体落进松土的闷响；四枚银粒在石面上各弹一次",
            "S11 梯身随重量晃两次；三枚银粒被收进袖子的细响",
            "S12 ★院子里的笑声穿门进来，不做任何衰减；灯油见底时焰头的爆响",
        ],
        "ambient_by_scene": {sc["scene_id"]: sc["weather"] for sc in SCENES},
        "★the_one_cut_that_changes_the_night": "★S04→S05 是全集唯一一次时间跳（酉时末→子夜），"
                                                "它同时是声音上唯一一次硬换底床。"
                                                "★**这一刀不许用交叉淡化**：观众必须在同一帧里从"
                                                "『街上还有人声』掉进『一个人在自家墙根上干活』。",
    },
    "space_chain": {
        "level_1_global": "GLOBAL-SPACE-E44-MUXINZHAI-ZHENGHEJIE-YIGUAN-MENKOU-ZHENGTANG-HOUYUAN-YOUSHIMO-DAO-ZIYE",
        "level_2_locations": sorted({sc["location_id"] for sc in SCENES}),
        "level_3_subspaces": sorted({x["subspace"] for x in flat}),
        "★level_2_is_five_and_one_of_them_is_new": "★本集 distinct_locations＝**5**，高于门的参考值 4。"
                                                    "★新增 **1** 处：`LOC-TAIPING-YIGUAN-ZHENGTANG`（太平医馆正堂），"
                                                    "由 ch48／ch49 的 locations 字段明列（『太平醫館後院與正堂』）。"
                                                    "**门限 2，余量 1**。"
                                                    "★四处复用：`LOC-ZHENGHEJIE-MUXINZHAI` 与 `LOC-ZHENGHEJIE`（E43 v6）、"
                                                    "`LOC-TAIPING-YIGUAN-HOUYUAN` 与 `LOC-TAIPING-YIGUAN-MENKOU`（E41 v17）。"
                                                    "★★**一条溯源披露**：`LOC-TAIPING-YIGUAN-ZHENGTANG` 在盘上并非首次出现——"
                                                    "旧映射下的 E46 v5（已按 seq=38 封存、不得进生产）与 E70 v1 用过同名 ID。"
                                                    "**我按『在可进生产的集次里是第一次』计为新增 1 处**，取严不取松。",
    },
    "identity_registry_check": {
        "existing_cards_required": ["陈迹", "白鲤", "世子", "小和尚", "梁猫儿", "乌云（黑猫）"],
        "new_cards_required": [
            "金猪／宋乾（密谍司十二生肖之一，有姓名、8 句台词，本集首次出场，后续主线反派）",
            "朱灵韵（白鲤之妹，有姓名、1 句台词，本集首次出场）",
            "穆新斋掌柜与食客若干（群体，无台词）",
        ],
        "new_card_note": "★★本集**新增有姓名角色 2 个**：金猪（宋乾）与朱灵韵。"
                         "★**这超过了宪章『新名字每 4 集 ≤1 个』的自设预算，我不掩饰，理由写在这里**："
                         "两人都是源章 characters_present 明列的人物，且都是主线承重件——"
                         "**金猪是接下来整段密谍司高压戏的对手方**（seq=38 c4 净效果里 ch53–56 密谍司段整体提前三集），"
                         "**朱灵韵是本集因果链的扳机**（她的『下人』二字直接触发白鲤替他说话，"
                         "而金猪给出的派任务理由就是『那位郡主替你说话了』）。"
                         "★按 seq=36 conditions[4] 的权威层级：数值自限是第 4 层 DIAGNOSTIC，"
                         "**不得压过第 2 层的源章绑定**；砍掉任一人都会砍断本集的收尾因果。"
                         "★**若监制认为该预算应作硬约束，请判 REVISE，我按合并人物重写。**",
        "★jinzhu_must_not_look_like_a_villain": "★★**金猪的建卡是本集最高风险的一件事**："
                                                 "他必须是一个**憨厚佃户**——草鞋、斗笠、粗布短褐、面色晒黑、笑容和煦，"
                                                 "**没有任何兵器、没有任何官服元素、没有阴翳眼神**。"
                                                 "★他与云羊／皎兔（已建卡的密谍司同僚）**必须在视觉上完全不同群**："
                                                 "那两个人是杀气，他是农人。"
                                                 "**这张脸一旦做成反派相，本集全部张力当场作废**——"
                                                 "源章的写法就是『笑容和煦却步步紧逼』。",
        "★the_cat_is_a_returning_asset": "★乌云（黑猫）在 S05-06 出场一格。**必须复用既有黑猫资产**，"
                                          "不得新建；猫高／人高 ≤0.25 的老基线照旧。",
        "★the_tube_is_the_prop_of_the_episode": "★★本集的关键道具是**那支竹筒**："
                                                 "S05 被白粉装进半截、S06 被塞进袖子、S12 被隔着袖子攥住。"
                                                 "★**它全集只出现三次，三次都在陈迹身上**；"
                                                 "**不得给它任何特写以外的强调，不得让任何其他角色看见它**。",
    },
    "onscreen_text_policy": {
        "policy": "画面内一律图形化无可读字，本集零例外",
        "shots_with_text": [
            "E44-S01／E44-S02（面馆：★不得出现幌子、菜牌、价目上的可读字——承 E43 同一条老账）",
            "E44-S03（★不得出现面馆招牌可读字）",
            "E44-S06／E44-S07（★医馆门口：不得出现『太平醫館』或任何招牌可读字，这是全剧欠了多集的老账）",
            "E44-S08／E44-S09／E44-S12（★正堂药柜：**抽屉上的药名一律纹样或失焦到不可辨**，这是本集新增的最高风险面）",
            "E44-S11（银花生与碎银：★不得出现任何可读铸字）",
        ],
        "requirement": "★本集**零 OCR 例外**。"
                       "★★**新增最高风险是正堂那面药柜**：抽屉标签是真实中药铺的默认美术，"
                       "一整面墙全是字，**一旦出字就是一次性大面积失守**。"
                       "处理：抽屉面一律做成素木、铜环与纹样，或压在灯照不到的暗部；"
                       "**宁可看不清是药柜，也不许出一个可读汉字**。",
    },
    "scene_states": [
        {
            "scene_id": sc["scene_id"],
            "location_id": sc["location_id"],
            "time_block_id": sc["time_block_id"],
            "time_of_day_state": sc["time_of_day"],
            "weather_state": sc["weather"],
            "interior_exterior": sc["interior_exterior"],
            "palette_temperature": sc["palette"],
            "thread": sc["thread"],
            "seconds": scene_seconds[sc["scene_id"]],
            "authority": "scene_state 由本合同锁定；生产线只能改怎么拍，不能改地点/时段/天气/事件（ROGER-20260718-SCENE-AUTHORITY-LOCK）",
        }
        for sc in SCENES
    ],
    "★audience_already_knows": AUDIENCE_ALREADY_KNOWS,
}
contract_path = SCRIPTS / "E44_GENERATION_CONTRACT_v5.json"
write_or_verify(contract_path, json.dumps(contract, ensure_ascii=False, indent=2) + "\n")
S_GEN = sha_file(contract_path)

if __name__ == "__main__":
    print(json.dumps({
        "canonical_sha256": S_SCRIPT,
        "directing_sha256": S_DIR,
        "generation_contract_sha256": S_GEN,
        "total_seconds": total,
        "shots": len(flat),
        "scenes": len(SCENES),
        "episode_asl": EPISODE_ASL,
        "visible_chars": visible_chars,
        "char_limit": CHAR_LIMIT,
        "dialogue_lines": len(dialogue),
        "spoken_chars": spoken_chars,
        "median_line_chars": median_line,
        "max_line_chars": max_line,
        "dialogue_ratio": dialogue_ratio,
        "action_scene_dialogue_ratio": action_ratio,
        "max_in_scene_silence": max_in_scene_silence,
        "max_cross_scene_silence": worst_cross,
        "agency_ratio": round(agency_moves / len(moves), 4),
        "max_consecutive_same_location": max_same_loc,
        "cross_cuts": cross_cuts,
        "time_jumps": time_jumps,
        "non_advancing_pct": non_advancing_pct,
        "max_scene_seconds": max(scene_seconds.values()),
        "distinct_locations": len(set(locs)),
        "burst_seconds": burst_seconds,
        "burst_asl": burst_asl,
    }, ensure_ascii=False, indent=1))
