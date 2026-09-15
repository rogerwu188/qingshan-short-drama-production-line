#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""青山 · 构建器出件前断言：注册门门限不得被当作构建器自限；manifest 版本号三方一致。

授权来源
--------
SUPERVISOR_ORDERS.json seq=47 / CL2X-1290（2026-08-28T22:17Z）

  conditions[1] REGISTERED_THRESHOLD_IS_NEVER_A_BUILDER_SELF_LIMIT (RULING)
    处方：「E51 起构建器加一条 assert：凡 manifest 出现 self_limit_* 字段，
           其值不得宽于对应注册门门限，宽于即不出件。不要回头改 E50 v5 字节。」

  conditions[2] MANIFEST_VERSION_FIELD_MUST_MATCH_FILENAME_AND_CONTRACT (ADVISORY)
    处方：「E51 起构建器加 assert：manifest.version 必须同时等于文件名版本号
           与 generation contract.version。」

生效范围
--------
E51 起（EFFECTIVE_FROM_EPISODE = 51）。对 E50 及以前只做 DIAGNOSTIC 报告，
**永不改历史字节**（seq=47 body 明写「本条不改 E50 v5 的任何字节」）。

为什么这条断言不是多余的（本轮实测发现，R416）
------------------------------------------------
注册门 tools/us_drama_event_density_gate.py 只读 event_density.max_information_gap_seconds
这一个字段；E50 v5 里那个 30.0 躺在写手自建的诊断块 ★two_rulers_side_by_side 内，
**任何注册门都看不见它**。v4 之所以被判 FAIL，是因为当时 29.3 写进了门真读的那个字段；
v5 把数字改对了，但「这把尺的自限归我、可放宽到 30」的说法留在了门看不见的地方。
⇒ 现存 66 道门里没有一道能看见 self_limit_* 字段。本模块补的是这个洞，不是重复既有门。

用法
----
  库：  from manifest_self_limit_and_version_assert import assert_manifest_ok
        assert_manifest_ok(manifest_path)          # 违规抛 SelfLimitViolation，即不出件
  CLI： python3 tools/manifest_self_limit_and_version_assert.py <manifest.json> [...]
        python3 tools/manifest_self_limit_and_version_assert.py --scan-all --json out.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

EFFECTIVE_FROM_EPISODE = 51
AUTHORIZATION = "CL2X-1290 / SUPERVISOR_ORDERS seq=47 conditions[1],[2]"

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
US_DRAMA_GATE = os.path.join(REPO_ROOT, "tools", "us_drama_event_density_gate.py")


class SelfLimitViolation(AssertionError):
    """出件阻断：自限宽于注册门门限，或版本号三方不一致。"""


# ---------------------------------------------------------------------------
# 注册门门限表
#
# `probe` 是该门限在门源码里的字面量特征串。导入时逐条实查；任何一条查不到，
# 本模块立即拒绝工作（而不是拿陈旧的数字继续比对）。门限值只能由注册表改，
# 本表只是它的只读镜像。
# ---------------------------------------------------------------------------
REGISTERED_LIMITS: Dict[str, Dict[str, Any]] = {
    "MAX_INFORMATION_GAP_SECONDS": {
        "bound": "max", "value": 20.0, "gate": US_DRAMA_GATE,
        "probe": "if max_gap > 20:",
        "failure": "maximum_information_gap_exceeds_20s",
        "gate_reads": ("event_density.max_information_gap_seconds",
                       "dialogue_pacing.max_no_progress_gap_seconds"),
    },
    "NON_ADVANCING_PERCENTAGE": {
        "bound": "max", "value": 15.0, "gate": US_DRAMA_GATE,
        "probe": "if non_advancing > 15.0:",
        "failure": "non_advancing_atmosphere_percentage_exceeds_15",
        "gate_reads": ("event_density.non_advancing_percentage",),
    },
    "MAX_SCENE_SECONDS": {
        "bound": "max", "value": 22.0, "gate": US_DRAMA_GATE,
        "probe": "if max_scene_seconds > 22:", "failure": "SCENE_TOO_LONG",
        "gate_reads": ("pacing.max_scene_seconds",),
    },
    "MAX_CONSECUTIVE_SAME_LOCATION": {
        "bound": "max", "value": 2, "gate": US_DRAMA_GATE,
        "probe": "if max_consecutive > 2:", "failure": "LOCATION_STAGNATION",
        "gate_reads": ("pacing.max_consecutive_same_location",),
    },
    "NEW_LOCATIONS_ADDED": {
        "bound": "max", "value": 2, "gate": US_DRAMA_GATE,
        "probe": "if new_locations > 2:", "failure": "LOCATION_BUDGET_EXCEEDED",
        "gate_reads": ("pacing.new_locations_added",),
    },
    "DIALOGUE_RATIO": {
        "bound": "max", "value": 0.35, "gate": US_DRAMA_GATE,
        "probe": "elif dialogue_ratio > 0.35:", "failure": "DIALOGUE_RATIO_EXCEEDED",
        "gate_reads": ("dialogue_pacing.dialogue_ratio",),
    },
    "ACTION_SCENE_DIALOGUE_RATIO": {
        "bound": "max", "value": 0.20, "gate": US_DRAMA_GATE,
        "probe": "elif action_ratio > 0.20:", "failure": "DIALOGUE_RATIO_EXCEEDED",
        "gate_reads": ("dialogue_pacing.action_scene_dialogue_ratio",),
    },
    "MAX_NARRATIVE_CHARACTERS_PER_MINUTE": {
        "bound": "max", "value": 1400, "gate": US_DRAMA_GATE,
        "probe": "MAX_NARRATIVE_CHARACTERS_PER_MINUTE = 1400", "failure": "narrative_too_long",
        "gate_reads": ("narrative.characters_per_minute",),
    },
    "MAX_CONSECUTIVE_DISCOVERY_MOVES": {
        "bound": "max", "value": 1, "gate": US_DRAMA_GATE,
        "probe": "MAX_CONSECUTIVE_DISCOVERY_MOVES = 1", "failure": "consecutive_discovery_moves",
        "gate_reads": ("narrative.max_consecutive_discovery_moves",),
    },
    "MIN_STORY_MOVES_PER_MINUTE": {
        "bound": "min", "value": 3.2, "gate": US_DRAMA_GATE,
        "probe": "MIN_STORY_MOVES_PER_MINUTE = 3.2", "failure": "event_density_below_hard_minimum",
        "gate_reads": ("event_density.story_moves_per_minute",),
    },
    "MIN_AGENCY_MOVE_RATIO": {
        "bound": "min", "value": 0.50, "gate": US_DRAMA_GATE,
        "probe": "MIN_AGENCY_MOVE_RATIO = 0.50", "failure": "agency_move_ratio_below_minimum",
        "gate_reads": ("narrative.agency_move_ratio",),
    },
    "MIN_PARALLEL_THREADS": {
        "bound": "min", "value": 2, "gate": US_DRAMA_GATE,
        "probe": "if parallel_threads < 2:", "failure": "NO_PARALLEL_THREAD",
        "gate_reads": ("pacing.parallel_threads",),
    },
}

# self_limit_* → 注册门门限 的关键词映射。按顺序首个命中者生效。
# 匹配基准 = 「JSON 路径 + 同级观测字段名」的小写串，因此
# `self_limit_in_scene` 能经同级 `in_scene_silence_seconds` 命中 silence。
_KEYWORD_MAP: List[Tuple[Tuple[str, ...], str]] = [
    (("action_ratio", "action_scene_dialogue"), "ACTION_SCENE_DIALOGUE_RATIO"),
    (("dialogue_ratio", "dialogue_pacing"), "DIALOGUE_RATIO"),
    (("information_gap", "no_progress", "silence", "无台词", "静默"), "MAX_INFORMATION_GAP_SECONDS"),
    (("non_advancing", "atmosphere", "氛围"), "NON_ADVANCING_PERCENTAGE"),
    (("consecutive_same_location", "location_stagnation"), "MAX_CONSECUTIVE_SAME_LOCATION"),
    (("new_location",), "NEW_LOCATIONS_ADDED"),
    (("scene_seconds", "scene_length", "max_scene"), "MAX_SCENE_SECONDS"),
    (("characters_per_minute", "char_per_minute", "正文可见字"), "MAX_NARRATIVE_CHARACTERS_PER_MINUTE"),
    (("agency",), "MIN_AGENCY_MOVE_RATIO"),
    (("parallel_thread",), "MIN_PARALLEL_THREADS"),
    (("discovery_move",), "MAX_CONSECUTIVE_DISCOVERY_MOVES"),
    (("story_move", "moves_per_minute", "event_density"), "MIN_STORY_MOVES_PER_MINUTE"),
]

# 写手声明「本自限无注册门对应物」的字段名（可带 ★ 前缀）。
_NO_COUNTERPART_TOKEN = "NO_REGISTERED_COUNTERPART"
_REGISTRY_REF_KEYS = ("self_limit_registry_ref", "★self_limit_registry_ref")

_SELF_LIMIT_KEY = re.compile(r"^★?self_limit(_|$)")
_MANIFEST_NAME = re.compile(r"^E(\d+)_manifest_v(\d+)\.json$")


def _verify_limit_table_against_gate_source() -> None:
    """门限表漂移守卫：任何一条 probe 在门源码里查不到就拒绝工作。"""
    try:
        with open(US_DRAMA_GATE, encoding="utf-8") as handle:
            src = handle.read()
    except OSError as exc:  # pragma: no cover
        raise SelfLimitViolation(f"REGISTERED_GATE_SOURCE_UNREADABLE: {US_DRAMA_GATE}: {exc}")
    missing = [k for k, v in REGISTERED_LIMITS.items() if v["probe"] not in src]
    if missing:
        raise SelfLimitViolation(
            "REGISTERED_LIMIT_TABLE_DRIFTED — 下列门限的源码特征串已查不到，"
            "说明注册门改过而本镜像未同步；请先同步再出件：" + ", ".join(sorted(missing))
        )


def _walk(node: Any, path: str = ""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield path + "/" + str(k), k, v, node
            yield from _walk(v, path + "/" + str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def _classify(path: str, key: str, parent: Dict[str, Any]) -> Optional[str]:
    stem = _SELF_LIMIT_KEY.sub("", key).strip("_")
    basis = [path.lower(), key.lower()]
    # 同级观测字段：名字以同一 stem 开头的兄弟键，最能说明这把尺量的是什么
    if stem:
        basis += [sib.lower() for sib in parent if sib != key and stem.lower() in sib.lower()]
    basis += [sib.lower() for sib in parent if not _SELF_LIMIT_KEY.match(sib)]
    blob = " ".join(basis)
    for keywords, limit_id in _KEYWORD_MAP:
        if any(kw in blob for kw in keywords):
            return limit_id
    return None


def _declared_no_counterpart(parent: Dict[str, Any]) -> Optional[str]:
    for k in parent:
        if k.lstrip("★") in [r.lstrip("★") for r in _REGISTRY_REF_KEYS]:
            val = str(parent[k])
            if _NO_COUNTERPART_TOKEN in val:
                return val
    return None


def check_self_limits(manifest: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    _verify_limit_table_against_gate_source()
    blocks: List[Dict[str, Any]] = []
    oks: List[Dict[str, Any]] = []
    for path, key, value, parent in _walk(manifest):
        if not _SELF_LIMIT_KEY.match(str(key)):
            continue
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue  # 说明性文本自限（如 ★self_limit_note）不参与数值比对
        if not math.isfinite(value):
            blocks.append({"path": path, "value": str(value),
                           "verdict": "BLOCK_NONFINITE_SELF_LIMIT"})
            continue
        limit_id = _classify(path, str(key), parent)
        if limit_id is None:
            ref = _declared_no_counterpart(parent)
            rec = {"path": path, "value": value, "limit_id": None, "declared_ref": ref}
            if ref:
                rec["verdict"] = "OK_DECLARED_NO_COUNTERPART"
                oks.append(rec)
            else:
                rec["verdict"] = "BLOCK_UNMAPPED_SELF_LIMIT"
                rec["reason"] = (
                    "该 self_limit_* 无法对应到任何注册门门限，且未声明 "
                    f"{_REGISTRY_REF_KEYS[0]}={_NO_COUNTERPART_TOKEN}。"
                    "堵住『改个名字就绕开门限』这条路：要么映射到注册门，要么明写它没有对应物及理由。"
                )
                blocks.append(rec)
            continue
        lim = REGISTERED_LIMITS[limit_id]
        looser = (value > lim["value"]) if lim["bound"] == "max" else (value < lim["value"])
        rec = {
            "path": path, "value": value, "limit_id": limit_id,
            "limit_value": lim["value"], "bound": lim["bound"],
            "gate_failure": lim["failure"],
        }
        if looser:
            rec["verdict"] = "BLOCK_SELF_LIMIT_LOOSER_THAN_REGISTERED_THRESHOLD"
            rec["reason"] = (
                f"自限 {value} 宽于注册门门限 {lim['value']}（{lim['bound']}）。"
                "注册门门限不是构建器自限，只能由注册表改。自限可以更严，永远不可以更宽。"
            )
            blocks.append(rec)
        else:
            rec["verdict"] = "OK_TIGHTER_OR_EQUAL"
            oks.append(rec)
    return {"blocks": blocks, "ok": oks}


def check_version_triple(manifest_path: str, manifest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """manifest.version == 文件名版本号 == generation contract.version。"""
    problems: List[Dict[str, Any]] = []
    name = os.path.basename(manifest_path)
    m = _MANIFEST_NAME.match(name)
    if not m:
        return [{"verdict": "BLOCK_MANIFEST_FILENAME_UNPARSEABLE", "filename": name,
                 "reason": "文件名不符 E{NN}_manifest_v{n}.json，无法核对版本三方一致。"}]
    ep, fname_ver = int(m.group(1)), int(m.group(2))
    mver = manifest.get("version")
    norm = _normalize_version(mver)
    if norm is not None and norm == fname_ver and not isinstance(mver, int):
        problems.append({
            "verdict": "WARN_MANIFEST_VERSION_NOT_AN_INTEGER",
            "manifest_version": mver, "filename_version": fname_ver, "filename": name,
            "reason": "版本号数值正确但形态非整数；v3 流水线的约定是整数。不阻断。",
        })
    elif norm != fname_ver:
        problems.append({
            "verdict": "BLOCK_MANIFEST_VERSION_NE_FILENAME",
            "manifest_version": mver, "filename_version": fname_ver, "filename": name,
            "reason": "manifest.version 必须等于文件名版本号。",
        })
    contract_path = os.path.join(os.path.dirname(os.path.abspath(manifest_path)),
                                 f"E{ep}_GENERATION_CONTRACT_v{fname_ver}.json")
    if not os.path.exists(contract_path):
        problems.append({
            "verdict": "BLOCK_GENERATION_CONTRACT_MISSING",
            "expected": os.path.relpath(contract_path, REPO_ROOT),
            "reason": "同版本 generation contract 不存在，版本三方一致无法成立。",
        })
        return problems
    try:
        with open(contract_path, encoding="utf-8") as handle:
            cver = json.load(handle).get("version")
    except (OSError, ValueError) as exc:
        problems.append({"verdict": "BLOCK_GENERATION_CONTRACT_UNREADABLE",
                         "path": contract_path, "reason": str(exc)})
        return problems
    if _normalize_version(cver) != fname_ver:
        problems.append({
            "verdict": "BLOCK_CONTRACT_VERSION_NE_FILENAME",
            "contract_version": cver, "filename_version": fname_ver,
            "contract": os.path.basename(contract_path),
            "reason": "generation contract.version 必须等于文件名版本号。",
        })
    return problems


def _normalize_version(v: Any) -> Optional[int]:
    """接受 5 / "5" / "v5" 三种形态，取其整数值；无法解析返回 None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        m = re.fullmatch(r"[vV]?(\d+)", v.strip())
        if m:
            return int(m.group(1))
    return None


def episode_of(manifest_path: str) -> Optional[int]:
    m = _MANIFEST_NAME.match(os.path.basename(manifest_path))
    return int(m.group(1)) if m else None


def evaluate(manifest_path: str, enforcing: bool = True) -> Dict[str, Any]:
    """enforcing=False ⇒ 纯回测口径，任何集号都只报 DIAGNOSTIC。

    ★这条区分是本模块的边界：seq=47 的处方是**构建器出件前的一条 assert**，
    不是一道扫全库的门。已落盘的旧件（尤其 rebase 之前的旧集号 manifest）
    只做诊断，永远不因本模块被改写或被判不合格。
    """
    with open(manifest_path, encoding="utf-8") as handle:
        manifest = json.load(handle)
    ep = episode_of(manifest_path)
    sl = check_self_limits(manifest)
    ver = check_version_triple(manifest_path, manifest)
    blocks = sl["blocks"] + [f for f in ver if not f["verdict"].startswith("WARN_")]
    in_force = enforcing and ep is not None and ep >= EFFECTIVE_FROM_EPISODE
    return {
        "manifest": os.path.relpath(os.path.abspath(manifest_path), REPO_ROOT),
        "episode": ep,
        "effective_from_episode": EFFECTIVE_FROM_EPISODE,
        "in_force": in_force,
        "authorization": AUTHORIZATION,
        "self_limit_findings": sl["blocks"],
        "self_limit_ok": sl["ok"],
        "version_findings": ver,
        # E50 及以前只诊断，不阻断，不改历史字节
        "verdict": ("BLOCK" if blocks else "PASS") if in_force
        else ("DIAGNOSTIC_ONLY_WOULD_BLOCK" if blocks else "DIAGNOSTIC_ONLY_CLEAN"),
    }


def assert_manifest_ok(manifest_path: str) -> Dict[str, Any]:
    """构建器出件前调用。E51+ 违规即抛异常 ⇒ 不出件。"""
    res = evaluate(manifest_path, enforcing=True)
    if res["verdict"] == "BLOCK":
        lines = [f"{AUTHORIZATION} — 出件阻断：{res['manifest']}"]
        for f in res["self_limit_findings"] + res["version_findings"]:
            lines.append(f"  [{f['verdict']}] {f.get('path') or f.get('filename') or ''} :: "
                         f"{f.get('reason', '')}")
        raise SelfLimitViolation("\n".join(lines))
    return res


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("manifests", nargs="*")
    ap.add_argument("--scan-all", action="store_true",
                    help="扫描 workflow/claude_writer_agent/scripts 下全部 E*_manifest_v*.json")
    ap.add_argument("--json", help="把完整结果写到该路径")
    args = ap.parse_args(argv)

    paths = list(args.manifests)
    if args.scan_all:
        import glob
        paths += sorted(glob.glob(os.path.join(
            REPO_ROOT, "workflow", "claude_writer_agent", "scripts", "E*_manifest_v*.json")))
    if not paths:
        ap.error("未给 manifest，也未给 --scan-all")

    results, worst = [], 0
    for p in paths:
        try:
            r = evaluate(p, enforcing=not args.scan_all)
        except Exception as exc:                                   # noqa: BLE001
            r = {"manifest": p, "verdict": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
        results.append(r)
        if r["verdict"] == "BLOCK":
            worst = max(worst, 2)
        elif r["verdict"] in ("ERROR", "DIAGNOSTIC_ONLY_WOULD_BLOCK"):
            worst = max(worst, 1)
        n = len(r.get("self_limit_findings", [])) + len(r.get("version_findings", []))
        print(f"{r['verdict']:<30} ep={str(r.get('episode')):<5} findings={n:<3} "
              f"{os.path.basename(r['manifest'])}")
        for f in r.get("self_limit_findings", []) + r.get("version_findings", []):
            print(f"    [{f['verdict']}] {f.get('path') or f.get('filename') or ''} "
                  f"value={f.get('value', f.get('manifest_version', f.get('contract_version')))} "
                  f"limit={f.get('limit_value')}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump({"authorization": AUTHORIZATION,
                       "effective_from_episode": EFFECTIVE_FROM_EPISODE,
                       "results": results}, fh, ensure_ascii=False, indent=1)
        print(f"\n[written] {args.json}")
    # 退出码：2=有 E51+ 真阻断（不出件）／1=历史诊断命中或读取错误／0=干净
    return 2 if worst == 2 else (1 if worst == 1 else 0)


if __name__ == "__main__":
    sys.exit(main())
