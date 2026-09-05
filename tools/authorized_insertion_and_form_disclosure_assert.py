#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""青山 · 构建器出件前断言：写手自发插入场的三件准入要件；落地形态自述的精确性。

授权来源
--------
SUPERVISOR_ORDERS.json seq=50 / CL2X-1293（2026-08-29T08:20Z）

  conditions[3] INS_E48_01_WRITER_INITIATED_SCENE_ADOPT (RULING)
    「采纳的是手法不是借口：今后『把上一集留下的悬置状态用一场推进一步』
      转为常规手法，但必须同时满足 ——
        ① 不新增事件/人物/地点
        ② 至少一件可指认的新信息
        ③ 在 manifest 的 authorized_insertions 里显式登记并自扣分。
      只为满足地点或时长门限、不带新信息的场，不在本次采纳范围内。」

  conditions[4] KEY_QUOTE_PUNCTUATION_DISCLOSURE_P2 (P2)
    「不返修、不扣分，只提醒今后自述精确到『繁→简转写＋句末标点规范化』。」

SUPERVISOR_ORDERS.json seq=51 / CL2X-1294（2026-08-29T09:16Z）—— 本版改判据的授权

  conditions[1] C3_NOT_RETROACTIVE_TO_FROZEN_PASSED_INSERTIONS (RULING)
    「seq=50 c3 的三件准入要件**不溯及**已冻结且已裁 PASS 的既有插入项……
      c3/c4 原文都写了不返修，这一点不因为后来长出一个探测器而改变。」
    ⇒ 落法：E51 之前的条目在报告里同时出现在 `p2_disclosures`，
      并带 `retroactivity` 块写明它们不是违规、不产生返修。

  conditions[2] NEW_INFORMATION_IS_TESTED_ON_THE_LANDED_SCENE_NOT_ONLY_ON_THE_WHY_FIELD (RULING)
    「c3 ② 的判据是『落地场次正文里能不能指认出一件新事实』，
      不是『why/new_information 字段里写没写』。字段仍然必须写（缺字段仍是形式违规），
      但**拒绝条款只能打在落地正文也拿不出新事实的场上**。
      ……只差把后者的分母从 why 字段换成场次正文。」
    ⇒ 落法：拒绝条款的分母改为 **narrative canonical 里该 scene_id 的正文**。
      R421 版用的是 manifest 散文（_NEW_INFO_PROSE_TOKENS）——那仍然是「写没写」，
      只是从一个字段换到另一个字段，没有换到正文。本版换到正文。

  conditions[3] SELF_DEDUCTION_SIGN_AND_FORM_DISCLOSURE_PRECISION (ADVISORY)
    「self_deduction 从 E51 起统一写负值并带单位；E48／E49 的号差**不回头改**。」

为什么这两条要落成代码而不是又一条备忘（承 R416 的 seq=47 落地形态）
--------------------------------------------------------------------
c3 把一个**一次性采纳**升格成**常规手法**。常规手法的危险面在于：三件要件里
只有第 ③ 件（登记＋自扣分）是自我披露就算数的，第 ①② 件要对着生成合同实查才
知道真假。而『披露充分』恰恰是 E48 v5 被采纳的主要理由 —— 一旦手法常规化，
下一个写手可以照抄那段披露的**措辞**而不复制它的**事实**，监制在下一轮才看得见。
c4 就是这个形态的小样本：E48 v5 的 ★form_disclosure 自述「标点未增删」，
而 KEY-CH53-02／-03 的句末各补了一个句号 —— 措辞是从「一字未改」那条真实的
断言里长出来的，只是多说了半句。**自述与事实的偏离，机器一比就知道；
留给人读，就得靠监制逐字校。**

生效范围
--------
E51 起（EFFECTIVE_FROM_EPISODE = 51）出件阻断。
E50 及以前只做 DIAGNOSTIC 报告，**永不改历史字节**
（seq=50 c3/c4 均明写不返修、不扣分、不产生返修）。

本模块不是新门
--------------
seq=50 c3 末句：「不是新门、不进注册表、不产生返修。」
本模块是**我自己构建器的出件前自检**，与注册门无关，不得被任何人当作门引用，
也不得阻断除我出件之外的任何环节（铁律一）。

用法
----
  库：  from authorized_insertion_and_form_disclosure_assert import assert_manifest_ok
        assert_manifest_ok(manifest_path, contract_path)   # 违规抛 InsertionDisclosureViolation
  CLI： python3 tools/authorized_insertion_and_form_disclosure_assert.py <manifest.json> [...]
        python3 tools/authorized_insertion_and_form_disclosure_assert.py --scan-all --json out.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

EFFECTIVE_FROM_EPISODE = 51
# seq=51 c3：self_deduction 自 E51 起统一负值带单位；E48／E49 的号差不回头改。
SELF_DEDUCTION_SIGN_EFFECTIVE_FROM = 51
AUTHORIZATION = ("CL2X-1293 / SUPERVISOR_ORDERS seq=50 conditions[3],[4]"
                 " ＋ CL2X-1294 / seq=51 conditions[1],[2],[3]")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS_DIR = os.path.join(REPO_ROOT, "workflow", "claude_writer_agent", "scripts")

_MANIFEST_NAME = re.compile(r"^E(\d+)_manifest_v(\d+)\.json$")


class InsertionDisclosureViolation(AssertionError):
    """出件阻断：自发插入场不满足三件准入要件，或落地形态自述与事实不符。"""


# ---------------------------------------------------------------------------
# 字段名解析
#
# manifest 里同一件事历来有带 ★ 与不带 ★ 两种写法（★ 是写手用来给监制标重点的，
# 不是 schema 的一部分）。一律按去掉前导 ★ 后的名字匹配，避免「换个星号就绕过」。
# ---------------------------------------------------------------------------
def _plain(key: str) -> str:
    return str(key).lstrip("★ ").strip()


INSERTION_KEYS = (
    "authorized_insertions",
    "authorized_insertions_not_from_this_chapter",
    "writer_initiated_insertions",
)
ZERO_INSERTION_NOTE_KEYS = ("zero_insertions_note",)
KEY_QUOTE_KEYS = ("key_quote_landing",)
FORM_DISCLOSURE_KEYS = ("form_disclosure", "landing_form_disclosure")

# c3 ② 的可指认新信息。写成一组同义字段名而不是单一硬编码名字，是为了
# 不让一个字段名的品味差异变成出件阻断；但**必须是独立字段**，
# 不接受埋在 why/reason 散文里 —— 散文里的一句话没法被下一轮机器复核。
NEW_INFORMATION_KEYS = (
    "new_information",
    "new_information_delivered",
    "new_fact_delivered",
)

# c3 ① 的「不新增事件/人物/地点」声明位
NOT_INTRODUCED_KEYS = (
    "what_it_does_not_do",
    "introduces_nothing_new",
    "no_new_event_person_location",
)

SELF_DEDUCTION_KEYS = ("self_deduction", "self_deduction_points")

# 散文里「这一场交出了一件新信息」的说法。
#
# ★seq=51 c2 之后，这组词**降级为兜底**：只有在落地场次正文根本取不到时才用。
#   监制的原话是「只差把后者的分母从 why 字段换成场次正文」—— R421 版把分母从
#   new_information 字段换成了 why 散文，那仍然是「写没写」，只是换了个字段。
#   真正的分母是 narrative canonical 里那一场的正文（见 _landed_scene_finding）。
_NEW_INFO_PROSE_TOKENS = ("新信息", "新事实", "new_information", "观众知道", "一件真新")

# c3 末句点名的两类「不构成采纳理由」的动机。命中其一且拿不出新信息 = 拒绝。
_GATE_THRESHOLD_MOTIVE_TOKENS = (
    "location_stagnation",
    "consecutive_same_location",
    "distinct_locations",
    "location_variety",
    "new_locations",
    "max_information_gap",
    "information_gap",
    "runtime_seconds",
    "凑时长",
    "补时长",
    "门限",
    "硬失败",
    "地点门",
    "时长门",
)

# c4：自述里「标点一个没动」的三种说法。事实不符时不得出现。
_PUNCT_UNCHANGED_CLAIMS = ("标点未增删", "标点未改", "未增删标点", "标点一字未动", "标点不变")
# c4：监制要求的精确说法所必须含有的成分
_PUNCT_NORMALIZED_TOKENS = ("标点规范化", "句末标点", "补句号", "标点补", "标点增", "标点调整")
# 「字面一字未改」类说法
_CHARS_UNCHANGED_CLAIMS = ("一字未改", "字序与字面", "逐字一致", "字面未改")


def _is_punct(ch: str) -> bool:
    """标点 = Unicode P* / S* 类，或空白。汉字与假名等一律不算。"""
    if ch.isspace():
        return True
    return unicodedata.category(ch)[0] in ("P", "S")


def _punct_multiset(text: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for ch in text or "":
        if _is_punct(ch):
            out[ch] = out.get(ch, 0) + 1
    return out


def _strip_punct(text: str) -> str:
    return "".join(ch for ch in (text or "") if not _is_punct(ch))


def _walk(node: Any, path: str = ""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield path + "/" + str(k), k, v, node
            yield from _walk(v, path + "/" + str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def _find_by_key(root: Any, names: Tuple[str, ...]) -> List[Tuple[str, Any]]:
    wanted = {n.lower() for n in names}
    hits: List[Tuple[str, Any]] = []
    for path, key, val, _parent in _walk(root):
        if _plain(key).lower() in wanted:
            hits.append((path, val))
    return hits


def _get_field(entry: Dict[str, Any], names: Tuple[str, ...]) -> Optional[Any]:
    wanted = {n.lower() for n in names}
    for k, v in entry.items():
        if _plain(k).lower() in wanted:
            return v
    return None


def _blob(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False).lower() if not isinstance(value, str) else value.lower()


def _parse_deduction(value: Any) -> Optional[float]:
    """'D4（−3.0）' → -3.0。取字符串里第一个数值，负号含 U+2212。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace("−", "-").replace("−", "-")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    val = float(m.group(0))
    # 'D4（3.0）' 这种把负号省掉的写法，按扣分语义仍取负
    return -abs(val) if "扣" in str(value) or "D" in str(value) or val > 0 else val


# ---------------------------------------------------------------------------
# 生成合同侧实查：c3 ① 的三项里，地点与人物是可以对着合同证伪的
# ---------------------------------------------------------------------------
def _contract_facts(contract: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not contract:
        return {}
    states = contract.get("scene_states") or []
    loc_by_scene = {s.get("scene_id"): s.get("location_id") for s in states if isinstance(s, dict)}
    space = contract.get("space_chain") or {}
    new_cards = ((contract.get("identity_registry_check") or {}).get("new_cards_required")) or []
    return {
        "loc_by_scene": loc_by_scene,
        "scene_order": [s.get("scene_id") for s in states if isinstance(s, dict)],
        "declared_new_locations": space.get("new_locations_added"),
        "distinct_locations": space.get("distinct_locations"),
        "new_cards_required": [str(c) for c in new_cards],
        "shots": contract.get("shots") or [],
    }


def _series_known_locations(episode: Optional[int], scripts_dir: str = SCRIPTS_DIR) -> set:
    """本集之前**全series**已建立过的 location_id 集合。

    c3 ① 的「不新增地点」说的是**故事世界里的新地点**，不是「本集场次表里的新条目」。
    E48-S03 的太平医馆正堂在本集只出现一次，但它承 E41–E47 —— 按「本集内是否复用」
    判会把它误判成新增。所以往前扫所有更早集的生成合同，取它们的 level_2_locations。
    （本模块首版就是照「本集内唯一」写的，在 E48 v5 真件上当场误报，
      测试把它抓了出来 —— 记在这里，免得下一版又写回去。）
    """
    known: set = set()
    if episode is None or not os.path.isdir(scripts_dir):
        return known
    for path in glob.glob(os.path.join(scripts_dir, "E*_GENERATION_CONTRACT_v*.json")):
        m = re.match(r"^E(\d+)_GENERATION_CONTRACT_v(\d+)\.json$", os.path.basename(path))
        if not m or int(m.group(1)) >= episode:
            continue
        try:
            with open(path, encoding="utf-8") as fh:
                other = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        for loc in ((other.get("space_chain") or {}).get("level_2_locations") or []):
            known.add(str(loc))
    return known


# ---------------------------------------------------------------------------
# seq=51 c2 —— 落地场次正文侧：拒绝条款的分母
#
# 这一段是本版唯一的实质改动。要说清楚它**能证明什么、不能证明什么**：
#
#   能证明的（可反驳、可复算）：这一场的正文**整段都能在更早的正文里找到**
#     —— 即它的每一格、每一个内容三元组都已经出现过 ⇒ 它是复述，拿不出新事实。
#     这是拒绝条款唯一站得住的机器判据：证「无」只有在「全部被覆盖」时才成立。
#
#   不能证明的：反过来「有新事实」。词面新 ≠ 事实新（换个说法也词面新）。
#     所以正向只输出**候选新事实（逐格取证）**交给监制读，不自己下判。
#     监制 seq=51 c2 自己就是这么读 E49-S05 的：他指认了两格，一格是
#     「观众此刻知道而陈迹不知道」，一格是「对已建立事实的一次可指认的改变」——
#     这两种判断机器做不了，我不假装能做。
#
# 于是拒绝条款的形态变成：命中门限动机 ＋ 落地正文判定为 PURE_RESTATEMENT ⇒ 拒绝。
# 正文取不到（canonical 不在盘上）⇒ UNRESOLVABLE，回落到 R421 的散文兜底，
# 并明写「ruling 级分母不可用」——不让「查不到」悄悄变成「没有」。
# ---------------------------------------------------------------------------
_SCENE_HEADING = re.compile(r"^#{1,6}\s*(E\d+-S\d+)")
_CANONICAL_NAME = re.compile(r"^E(\d+)_NARRATIVE_CANONICAL_v(\d+)\.md$")


def _ngrams(text: str, n: int = 3) -> set:
    """去标点后的内容三元组。中文按字切，短于 n 的整串自成一个。"""
    s = _strip_punct(text)
    if len(s) < n:
        return {s} if s else set()
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def _split_canonical_scenes(text: str) -> "collections.OrderedDict":
    """canonical 全文 → {scene_id: 正文（不含标题行）}，保持出现次序。"""
    import collections as _c
    out = _c.OrderedDict()
    cur = None
    buf: List[str] = []
    for line in (text or "").splitlines():
        m = _SCENE_HEADING.match(line.strip())
        if m:
            if cur:
                out[cur] = "\n".join(buf).strip()
            cur, buf = m.group(1), []
            continue
        if cur is not None:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf).strip()
    return out


def _cells(scene_text: str) -> List[str]:
    """一格 = 一个非空行（本项目 canonical 的既有写法，E49-S05 就是三格）。"""
    return [ln.strip() for ln in (scene_text or "").splitlines() if ln.strip()]


def _guess_canonical(manifest_path: str) -> Optional[str]:
    m = _MANIFEST_NAME.match(os.path.basename(manifest_path))
    if not m:
        return None
    cand = os.path.join(os.path.dirname(manifest_path),
                        f"E{m.group(1)}_NARRATIVE_CANONICAL_v{m.group(2)}.md")
    return cand if os.path.exists(cand) else None


def _previous_episode_canonical_text(episode: Optional[int], scripts_dir: str) -> str:
    """紧邻上一集 canonical 的最高版本全文。

    只取**紧邻一集**，不取全库：改基前有 60 份 canonical 绑在别集源章上
    （seq=49 c1 的血统认证键裁定），把它们塞进先验语料会把新事实洗成旧事实，
    而拒绝条款是本模块最重的一顶帽子 —— 宁可少扣，不可错扣。
    """
    if episode is None or not os.path.isdir(scripts_dir):
        return ""
    best: Tuple[int, str] = (-1, "")
    for path in glob.glob(os.path.join(scripts_dir, "E*_NARRATIVE_CANONICAL_v*.md")):
        m = _CANONICAL_NAME.match(os.path.basename(path))
        if not m or int(m.group(1)) != episode - 1:
            continue
        ver = int(m.group(2))
        if ver > best[0]:
            try:
                with open(path, encoding="utf-8") as fh:
                    best = (ver, fh.read())
            except OSError:
                continue
    return best[1]


def _landed_scene_finding(scene_id: str,
                          canonical_text: Optional[str],
                          episode: Optional[int],
                          scripts_dir: str) -> Dict[str, Any]:
    """seq=51 c2 的分母。返回 verdict ∈ UNRESOLVABLE / PURE_RESTATEMENT / NEW_FACT_CANDIDATES。"""
    if not canonical_text or not scene_id:
        return {"verdict": "UNRESOLVABLE", "reason": "落地 canonical 不在盘上或未声明 scene_id"}
    scenes = _split_canonical_scenes(canonical_text)
    if scene_id not in scenes:
        return {"verdict": "UNRESOLVABLE",
                "reason": f"canonical 里找不到 {scene_id}",
                "scenes_present": list(scenes)[:20]}

    cells = _cells(scenes[scene_id])
    if not cells:
        return {"verdict": "PURE_RESTATEMENT", "reason": f"{scene_id} 正文为空 —— 一件事实也没有",
                "cells": [], "novel_cells": []}

    prior_parts = []
    for sid, body in scenes.items():
        if sid == scene_id:
            break
        prior_parts.append(body)
    prior_parts.append(_previous_episode_canonical_text(episode, scripts_dir))
    prior_grams = set()
    for part in prior_parts:
        prior_grams |= _ngrams(part)

    novel = []
    for cell in cells:
        unseen = sorted(_ngrams(cell) - prior_grams)
        if unseen:
            novel.append({"cell": cell, "novel_trigrams": unseen[:8],
                          "novel_trigram_count": len(unseen)})

    return {
        "verdict": "NEW_FACT_CANDIDATES" if novel else "PURE_RESTATEMENT",
        "scene_id": scene_id,
        "cells": cells,
        "novel_cells": novel,
        "prior_corpus": "本集该场之前的全部场次正文 ＋ 紧邻上一集 canonical 最高版本",
        "caveat": "词面新 ≠ 事实新。正向只列候选，交监制读；反向（全覆盖）才用于拒绝条款。",
    }


# seq=49 c1（CL2X-1292）血统认证键：抬头自报的源绑定依据映射。
# 抬头写着这张旧表的 canonical 一律是 pre-rebase 历史件。
_PRE_REBASE_MAP_TOKEN = "episode_source_map_v2_observed_20260821"
_REBASE_MAP_TOKEN = "episode_source_map_rebase_v1_20260828"


def _lineage(canonical_text: Optional[str]) -> Dict[str, Any]:
    """本件是改基前的历史件，还是改基后的新件？

    为什么必须问这一句：本模块的生效窗口写的是 `episode >= 51`，而 episode 取自
    **文件名**。改基后文件名与集号脱钩 —— 盘上 68 份编号 ≥E51 的 manifest 全是
    改基前的旧稿（seq=49 c1 已裁：文件名不足以认归属）。照文件名判，这 68 份会被
    当成「新集」而进入阻断档，同时拿不到 seq=51 c1 给冻结历史件的那把伞 ——
    伞恰好被从最需要它的人手里抽走。所以生效窗口改用血统认证键，不用文件名。
    """
    head = (canonical_text or "")[:4000]
    if _PRE_REBASE_MAP_TOKEN in head:
        return {"era": "PRE_REBASE", "self_reported_map": _PRE_REBASE_MAP_TOKEN,
                "basis": "canonical 抬头自报源绑定依据 = 改基前旧表（seq=49 c1 血统认证键）"}
    if _REBASE_MAP_TOKEN in head:
        return {"era": "POST_REBASE", "self_reported_map": _REBASE_MAP_TOKEN,
                "basis": "canonical 抬头自报源绑定依据 = 改基 sidecar"}
    return {"era": "UNDECLARED", "self_reported_map": None,
            "basis": "canonical 不在盘上或抬头未写源绑定依据 ⇒ 回落到文件名集号"}


def _anchor_ratio(claim: str, scene_text: str) -> Tuple[int, float]:
    """申报的新信息与落地正文的三元组交集。0 交集 ＝ 这句话不在这一场里。"""
    cg, sg = _ngrams(claim), _ngrams(scene_text)
    if not cg:
        return 0, 0.0
    shared = cg & sg
    return len(shared), len(shared) / len(cg)


def _max_consecutive(seq: List[Any]) -> int:
    best = cur = 1 if seq else 0
    for a, b in zip(seq, seq[1:]):
        cur = cur + 1 if a == b else 1
        best = max(best, cur)
    return best


def _location_effect_of_insertion(facts: Dict[str, Any], scene_id: str) -> Dict[str, Any]:
    """这一场对地点读数的实际影响 —— 用来把『声称的动机』和『真实效果』分开看。

    不是判违规用的，是给监制的取证：写手说这场顺带避开了 LOCATION_STAGNATION，
    这里算出「有它」与「没它」两种情况下的最长同地点连场数与去重地点数，
    自述与算出来的数对不上时报 DIAGNOSTIC。
    """
    order = facts.get("scene_order") or []
    loc = facts.get("loc_by_scene") or {}
    if not order or scene_id not in order:
        return {}
    with_it = [loc.get(s) for s in order]
    without = [loc.get(s) for s in order if s != scene_id]
    return {
        "max_consecutive_same_location_with_insertion": _max_consecutive(with_it),
        "max_consecutive_same_location_without_insertion": _max_consecutive(without),
        "distinct_locations_with_insertion": len(set(with_it)),
        "distinct_locations_without_insertion": len(set(without)),
    }


# ---------------------------------------------------------------------------
# 检查 A —— seq=50 c3 三件准入要件
# ---------------------------------------------------------------------------
def check_insertions(manifest: Dict[str, Any],
                     contract: Optional[Dict[str, Any]] = None,
                     episode: Optional[int] = None,
                     scripts_dir: str = SCRIPTS_DIR,
                     canonical_text: Optional[str] = None) -> Tuple[List[Dict], List[Dict]]:
    violations: List[Dict] = []
    diagnostics: List[Dict] = []
    facts = _contract_facts(contract)
    known_locations = _series_known_locations(episode, scripts_dir)

    entries: List[Tuple[str, Dict[str, Any]]] = []
    for path, val in _find_by_key(manifest, INSERTION_KEYS):
        if isinstance(val, list):
            for i, e in enumerate(val):
                if isinstance(e, dict):
                    entries.append((f"{path}[{i}]", e))
        elif isinstance(val, dict):
            entries.append((path, val))

    writer_initiated = []
    for path, e in entries:
        kind = str(_get_field(e, ("kind",)) or "").upper()
        directed = bool(_get_field(e, ("supervisor_directed",)))
        if directed:
            continue
        if kind and "WRITER_INITIATED" not in kind:
            continue
        writer_initiated.append((path, e))

    for path, e in writer_initiated:
        ins_id = str(_get_field(e, ("insertion_id",)) or path)
        scene_id = str(_get_field(e, ("scene_id",)) or "")

        # ③ 登记 + 自扣分
        ded_raw = _get_field(e, SELF_DEDUCTION_KEYS)
        ded = _parse_deduction(ded_raw)
        if ded is None or ded == 0:
            violations.append({
                "code": "INSERTION_MISSING_SELF_DEDUCTION",
                "insertion_id": ins_id, "path": path,
                "detail": "seq=50 c3 ③：自发插入必须在 authorized_insertions 里显式登记**并自扣分**。"
                          f"实测 self_deduction={ded_raw!r} 解析为 {ded!r}。",
            })
        elif episode is not None and episode >= SELF_DEDUCTION_SIGN_EFFECTIVE_FROM:
            # seq=51 c3：E51 起统一写负值并带单位。E48（−3.0 无单位）与
            # E49（1.0 分 无负号）的号差按同条明文**不回头改**，故只在 ≥E51 生效。
            raw = str(ded_raw)
            has_sign = ("-" in raw) or ("−" in raw) or ("﹣" in raw) or ("－" in raw)
            has_unit = ("分" in raw) or ("point" in raw.lower()) or ("pts" in raw.lower())
            missing = [n for n, ok in (("负号", has_sign), ("单位", has_unit)) if not ok]
            if missing:
                violations.append({
                    "code": "SELF_DEDUCTION_SIGN_OR_UNIT_MISSING",
                    "insertion_id": ins_id, "path": path,
                    "detail": f"seq=51 c3：self_deduction 自 E{SELF_DEDUCTION_SIGN_EFFECTIVE_FROM} 起"
                              f"统一写负值并带单位，实测 {ded_raw!r} 缺 {missing}。"
                              "（E48／E49 的号差按同条明文不回头改。）",
                })

        # ② 至少一件可指认的新信息（必须是独立字段，不接受埋在散文里）
        new_info = _get_field(e, NEW_INFORMATION_KEYS)
        has_new_info = bool(new_info) and bool(str(new_info).strip())
        if not has_new_info:
            violations.append({
                "code": "INSERTION_MISSING_NEW_INFORMATION_FIELD",
                "insertion_id": ins_id, "path": path,
                "detail": "seq=50 c3 ②：必须交出至少一件可指认的新信息，且写成独立字段"
                          f"（{'/'.join(NEW_INFORMATION_KEYS)}）而非埋在 why/reason 散文里 ——"
                          "散文里的一句话没法被下一轮机器复核。",
            })

        # ① 不新增事件/人物/地点：先要有声明，再对合同实查地点与人物
        declared = _get_field(e, NOT_INTRODUCED_KEYS)
        if not declared or not str(declared).strip():
            violations.append({
                "code": "INSERTION_MISSING_NO_NEW_ELEMENTS_DECLARATION",
                "insertion_id": ins_id, "path": path,
                "detail": f"seq=50 c3 ①：必须显式声明不新增事件/人物/地点（{'/'.join(NOT_INTRODUCED_KEYS)}）。",
            })

        if facts and scene_id:
            loc = (facts["loc_by_scene"] or {}).get(scene_id)
            other_locs = {v for k, v in (facts["loc_by_scene"] or {}).items() if k != scene_id}
            if loc and loc not in other_locs:
                if loc in known_locations:
                    diagnostics.append({
                        "code": "INSERTION_USES_SERIES_KNOWN_LOCATION_UNIQUE_TO_THIS_EPISODE",
                        "insertion_id": ins_id, "path": path,
                        "detail": f"{loc} 在本集只有插入场 {scene_id} 用到，"
                                  "但它在更早集的生成合同里已经建立过 ⇒ 不是新增地点。",
                    })
                else:
                    violations.append({
                        "code": "INSERTION_INTRODUCES_NEW_LOCATION",
                        "insertion_id": ins_id, "path": path,
                        "detail": f"seq=50 c3 ①：插入场 {scene_id} 的 location_id={loc} "
                                  "在本集其余场次与全部更早集里都查不到 ⇒ 这一场自己带进了一个地点。",
                    })
            # 人物：只在插入场出现、且同时挂在 new_cards_required 上 = 这一场带进了新人物
            ins_speakers = {
                str(s.get("speaker") or "").strip()
                for s in (facts.get("shots") or [])
                if s.get("scene_id") == scene_id and s.get("speaker")
            }
            other_speakers = {
                str(s.get("speaker") or "").strip()
                for s in (facts.get("shots") or [])
                if s.get("scene_id") != scene_id and s.get("speaker")
            }
            only_here = {s for s in ins_speakers if s and s not in other_speakers}
            newcards = " ".join(facts.get("new_cards_required") or [])
            brought_in = sorted(s for s in only_here if s and s in newcards)
            if brought_in:
                violations.append({
                    "code": "INSERTION_INTRODUCES_NEW_CHARACTER",
                    "insertion_id": ins_id, "path": path,
                    "detail": f"seq=50 c3 ①：{brought_in} 只在插入场 {scene_id} 出现且列于 "
                              "new_cards_required ⇒ 这一场自己带进了新人物。",
                })

        # 拒绝条款：只为满足地点或时长门限、不带新信息
        motive_blob = " ".join(
            _blob(_get_field(e, (k,))) for k in
            ("why", "reason", "motive", "source_basis", "supervisor_ruling_requested",
             "what_it_does_not_do", "self_deduction")
            if _get_field(e, (k,)) is not None
        )
        gate_motive = [t for t in _GATE_THRESHOLD_MOTIVE_TOKENS if t in motive_blob]

        # ★seq=51 c2：拒绝条款的分母 = 落地场次正文，不是 why 字段、也不是散文。
        scene = _landed_scene_finding(scene_id, canonical_text, episode, scripts_dir)
        prose_has_new_info = any(t in motive_blob for t in _NEW_INFO_PROSE_TOKENS)

        if scene["verdict"] == "UNRESOLVABLE":
            # 查不到不等于没有。回落到 R421 的散文兜底，并把「ruling 级分母不可用」写在明处。
            scene_says_no_new_fact = not (has_new_info or prose_has_new_info)
            diagnostics.append({
                "code": "LANDED_SCENE_TEXT_UNRESOLVABLE_FELL_BACK_TO_PROSE",
                "insertion_id": ins_id, "path": path,
                "detail": f"{scene.get('reason')} ⇒ seq=51 c2 的 ruling 级分母（场次正文）本次不可用，"
                          "退回 R421 的 manifest 散文兜底。出件时正文必然在盘上，"
                          "这条只应出现在离线扫描与合成用例里。",
            })
        else:
            scene_says_no_new_fact = scene["verdict"] == "PURE_RESTATEMENT"
            diagnostics.append({
                "code": "LANDED_SCENE_NEW_FACT_SCREEN",
                "insertion_id": ins_id, "path": path,
                "detail": json.dumps({
                    "verdict": scene["verdict"],
                    "cells": scene.get("cells"),
                    "novel_cells": scene.get("novel_cells"),
                    "caveat": scene.get("caveat"),
                }, ensure_ascii=False),
            })

        if gate_motive and scene_says_no_new_fact:
            violations.append({
                "code": "INSERTION_JUSTIFIED_ONLY_BY_GATE_THRESHOLD",
                "insertion_id": ins_id, "path": path,
                "detail": "seq=50 c3 末句 ＋ seq=51 c2：只为满足地点或时长门限、"
                          f"而**落地正文也拿不出新事实**的场不在采纳范围内。命中门限动机 {gate_motive}；"
                          f"落地正文判读 = {scene['verdict']}（{scene.get('reason','每一格都能在更早正文里找到')}）。",
            })
        elif gate_motive:
            diagnostics.append({
                "code": "INSERTION_HAS_GATE_MOTIVE_BUT_ALSO_NEW_INFORMATION",
                "insertion_id": ins_id, "path": path,
                "detail": f"动机里含门限成分 {gate_motive}，但落地正文拿得出新事实 ⇒ 在采纳范围内。"
                          "这是 E48 v5 INS-E48-01 与 E49 v5 INS-E49-01 的形态：动机双重、写在明处。",
            })

        # 申报的新信息必须在**这一场的正文里**找得到 —— 「判在落地场次上」的另一半。
        if has_new_info and scene["verdict"] != "UNRESOLVABLE":
            shared, ratio = _anchor_ratio(str(new_info), "\n".join(scene.get("cells") or []))
            if shared == 0:
                violations.append({
                    "code": "INSERTION_NEW_INFORMATION_NOT_ANCHORED_IN_LANDED_SCENE",
                    "insertion_id": ins_id, "path": path,
                    "detail": f"seq=51 c2：申报的新信息在 {scene_id} 正文里一个内容三元组也对不上 ⇒ "
                              "这句话写在 manifest 里、没写进戏里。字段漂亮而正文不交货，"
                              "正是本条要防的形态。",
                })
            elif ratio < 0.15:
                diagnostics.append({
                    "code": "INSERTION_NEW_INFORMATION_WEAKLY_ANCHORED",
                    "insertion_id": ins_id, "path": path,
                    "detail": f"申报新信息与 {scene_id} 正文的三元组重合率 {ratio:.2f}（共 {shared} 个）——"
                              "可能只是措辞不同，也可能是没落地，请人读一眼。",
                })

        eff = _location_effect_of_insertion(facts, scene_id) if facts else {}
        if eff:
            diagnostics.append({
                "code": "INSERTION_LOCATION_EFFECT_MEASURED",
                "insertion_id": ins_id, "path": path, "detail": json.dumps(eff, ensure_ascii=False),
            })

    # 「零插入」自述必须限定范围，否则与实际登记项自相矛盾
    for path, val in _find_by_key(manifest, ZERO_INSERTION_NOTE_KEYS):
        text = str(val)
        claims_zero = "零" in text or "zero" in text.lower()
        scoped = ("监制指定" in text or "supervisor_directed" in text
                  or "supervisor-directed" in text.lower())
        if writer_initiated and claims_zero and not scoped:
            violations.append({
                "code": "ZERO_INSERTION_CLAIM_CONTRADICTS_REGISTERED_INSERTIONS",
                "path": path,
                "detail": f"自述『零插入』未限定范围，而本 manifest 登记了 "
                          f"{len(writer_initiated)} 条写手自发插入。若本意是『零监制指定插入』，"
                          "请把范围写进这句话。",
            })

    return violations, diagnostics


# ---------------------------------------------------------------------------
# 检查 B —— seq=50 c4 落地形态自述精确性
# ---------------------------------------------------------------------------
def check_form_disclosure(manifest: Dict[str, Any]) -> Tuple[List[Dict], List[Dict]]:
    violations: List[Dict] = []
    diagnostics: List[Dict] = []

    for kq_path, kq in _find_by_key(manifest, KEY_QUOTE_KEYS):
        if not isinstance(kq, dict):
            continue
        disclosure = _get_field(kq, FORM_DISCLOSURE_KEYS)
        landed = _get_field(kq, ("landed",))
        if not isinstance(landed, dict):
            continue

        punct_changed: List[Dict[str, Any]] = []
        chars_changed: List[Dict[str, Any]] = []
        for qid, item in landed.items():
            if not isinstance(item, dict):
                continue
            src = str(item.get("source") or "")
            dst = str(item.get("landed") or "")
            if not src or not dst:
                continue
            if _punct_multiset(src) != _punct_multiset(dst):
                punct_changed.append({
                    "quote_id": qid,
                    "source_punctuation": "".join(sorted(_punct_multiset(src))) or "(无)",
                    "landed_punctuation": "".join(sorted(_punct_multiset(dst))) or "(无)",
                })
            if len(_strip_punct(src)) != len(_strip_punct(dst)):
                chars_changed.append({
                    "quote_id": qid,
                    "source_chars": len(_strip_punct(src)),
                    "landed_chars": len(_strip_punct(dst)),
                })

        text = str(disclosure or "")
        if punct_changed:
            overclaim = [c for c in _PUNCT_UNCHANGED_CLAIMS if c in text]
            if overclaim:
                violations.append({
                    "code": "FORM_DISCLOSURE_OVERCLAIMS_PUNCTUATION_UNCHANGED",
                    "path": kq_path,
                    "detail": f"自述含 {overclaim}，但实测标点确有增删：{punct_changed}。"
                              "seq=50 c4：自述需精确到『繁→简转写＋句末标点规范化』。",
                })
            elif not any(t in text for t in _PUNCT_NORMALIZED_TOKENS):
                violations.append({
                    "code": "FORM_DISCLOSURE_OMITS_PUNCTUATION_NORMALIZATION",
                    "path": kq_path,
                    "detail": f"实测标点有增删：{punct_changed}，而 form_disclosure 未提及标点规范化。",
                })
        if chars_changed:
            overclaim = [c for c in _CHARS_UNCHANGED_CLAIMS if c in text]
            if overclaim:
                violations.append({
                    "code": "FORM_DISCLOSURE_OVERCLAIMS_CHARACTERS_UNCHANGED",
                    "path": kq_path,
                    "detail": f"自述含 {overclaim}，但去标点后字数不等：{chars_changed}。",
                })
            else:
                diagnostics.append({
                    "code": "KEY_QUOTE_CHARACTER_COUNT_DIFFERS",
                    "path": kq_path, "detail": json.dumps(chars_changed, ensure_ascii=False),
                })
        if not punct_changed and not chars_changed and disclosure:
            diagnostics.append({
                "code": "FORM_DISCLOSURE_MATCHES_MEASUREMENT",
                "path": kq_path,
                "detail": "逐条实测：标点与去标点字数均与源一致，自述可成立。",
            })

    return violations, diagnostics


# ---------------------------------------------------------------------------
# 顶层
# ---------------------------------------------------------------------------
def _episode_of(manifest_path: str, manifest: Dict[str, Any]) -> Optional[int]:
    m = _MANIFEST_NAME.match(os.path.basename(manifest_path))
    if m:
        return int(m.group(1))
    ep = manifest.get("episode")
    if isinstance(ep, str) and ep.upper().startswith("E") and ep[1:].isdigit():
        return int(ep[1:])
    return None


def _guess_contract(manifest_path: str) -> Optional[str]:
    m = _MANIFEST_NAME.match(os.path.basename(manifest_path))
    if not m:
        return None
    cand = os.path.join(os.path.dirname(manifest_path),
                        f"E{m.group(1)}_GENERATION_CONTRACT_v{m.group(2)}.json")
    return cand if os.path.exists(cand) else None


def evaluate(manifest_path: str, contract_path: Optional[str] = None) -> Dict[str, Any]:
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
    contract = None
    cpath = contract_path or _guess_contract(manifest_path)
    if cpath and os.path.exists(cpath):
        try:
            with open(cpath, encoding="utf-8") as fh:
                contract = json.load(fh)
        except (OSError, json.JSONDecodeError):
            contract = None

    episode = _episode_of(manifest_path, manifest)
    scripts_dir = os.path.dirname(os.path.abspath(manifest_path))

    canonical_text = None
    kpath = _guess_canonical(manifest_path)
    if kpath:
        try:
            with open(kpath, encoding="utf-8") as fh:
                canonical_text = fh.read()
        except OSError:
            canonical_text = None

    v1, d1 = check_insertions(manifest, contract, episode=episode,
                              scripts_dir=scripts_dir, canonical_text=canonical_text)
    v2, d2 = check_form_disclosure(manifest)
    violations, diagnostics = v1 + v2, d1 + d2

    lineage = _lineage(canonical_text)
    blocking = episode is not None and episode >= EFFECTIVE_FROM_EPISODE
    if blocking and lineage["era"] == "PRE_REBASE":
        # 改基前的历史件即使编号 ≥E51 也是冻结历史件 ⇒ 降为诊断，并给 c1 的伞。
        blocking = False

    report = {
        "manifest": os.path.relpath(manifest_path, REPO_ROOT),
        "contract": os.path.relpath(cpath, REPO_ROOT) if cpath else None,
        "canonical": os.path.relpath(kpath, REPO_ROOT) if kpath else None,
        "episode": episode,
        "lineage": lineage,
        "authorization": AUTHORIZATION,
        "effective_from_episode": EFFECTIVE_FROM_EPISODE,
        "enforcement": "BLOCKING" if blocking else "DIAGNOSTIC_ONLY",
        "violations": violations,
        "diagnostics": diagnostics,
        "ok": not (blocking and violations),
    }
    if not blocking:
        # ★seq=51 c1：三件要件不溯及已冻结、已裁 PASS 的既有插入项。
        # 报告里这些条目仍列在 violations（历史读数不动，测试与既有消费者据此复算），
        # 但同时镜到 p2_disclosures 并附本块 —— 任何人拿这份报告去要返修都拿不到依据。
        report["p2_disclosures"] = violations
        report["retroactivity"] = {
            "applies": False,
            "authority": "CL2X-1294 / SUPERVISOR_ORDERS seq=51 conditions[1]",
            "reading": "seq=50 c3 的三件准入要件不溯及已冻结且已裁 PASS 的既有插入项；"
                       f"本件（E{episode if episode is not None else '?'}，血统 {lineage['era']}）"
                       "的条目一律是 P2 披露，不是违规、不升版、不删场、不动一个字节。",
            "shelter_basis": ("血统认证键：canonical 抬头自报改基前旧表 ⇒ 冻结历史件"
                              if lineage["era"] == "PRE_REBASE"
                              else f"集号 < E{EFFECTIVE_FROM_EPISODE}"),
            "named_examples": "E49 v5 INS-E49-01（seq=51 c2 已裁有新信息）、E45／E46 三条插入项。",
        }
    return report


def assert_manifest_ok(manifest_path: str, contract_path: Optional[str] = None) -> Dict[str, Any]:
    """出件前调用。E51 起违规即抛异常（＝不出件）；E50 及以前只返回诊断。"""
    report = evaluate(manifest_path, contract_path)
    if not report["ok"]:
        lines = [f"[{v['code']}] {v.get('insertion_id') or v.get('path')}: {v['detail']}"
                 for v in report["violations"]]
        raise InsertionDisclosureViolation(
            f"{os.path.basename(manifest_path)} 未通过 seq=50 c3/c4 ＋ seq=51 c2/c3 出件前自检"
            f"（授权 {AUTHORIZATION}）：\n  " + "\n  ".join(lines)
        )
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="seq=50 c3/c4 构建器出件前自检")
    ap.add_argument("manifests", nargs="*", help="manifest json 路径")
    ap.add_argument("--scan-all", action="store_true", help=f"扫描 {SCRIPTS_DIR} 下全部 manifest")
    ap.add_argument("--json", help="把完整报告写到这个路径")
    args = ap.parse_args(argv)

    paths = list(args.manifests)
    if args.scan_all:
        paths += sorted(glob.glob(os.path.join(SCRIPTS_DIR, "E*_manifest_v*.json")))
    if not paths:
        ap.error("需要 manifest 路径或 --scan-all")

    reports = [evaluate(p) for p in dict.fromkeys(paths)]
    bad = [r for r in reports if r["violations"]]
    blocked = [r for r in reports if not r["ok"]]

    for r in reports:
        if not r["violations"]:
            continue
        print(f"\n=== {r['manifest']}  episode={r['episode']}  {r['enforcement']}")
        for v in r["violations"]:
            print(f"  [{v['code']}] {v.get('insertion_id') or v.get('path')}")
            print(f"      {v['detail']}")

    print(f"\n扫描 {len(reports)} 份 manifest：有违规 {len(bad)} 份，其中出件阻断 {len(blocked)} 份"
          f"（阻断自 E{EFFECTIVE_FROM_EPISODE} 起）。")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"authorization": AUTHORIZATION,
                       "effective_from_episode": EFFECTIVE_FROM_EPISODE,
                       "reports": reports}, fh, ensure_ascii=False, indent=1)
        print(f"报告已写入 {args.json}")

    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
