# -*- coding: utf-8 -*-
"""DELIVERY-BINDING-BROKEN 机器门（CL2X-1069 §③ / CL2X-1070 §③ ask③，owner=Claude Writer）

★存在理由（一句话）：批13 的绑定断裂窗口 01:28:21→01:32:44 存在了 4 分 23 秒，
然后**自愈**——而自愈动作同时把它抹得一干二净。监制之所以看见它，只因为取样恰好
落在窗口里（差 18 秒）。**一个只能靠取样相位的运气才能被看见的缺陷，等于没有观测。**

本件把观测从「某一轮恰好取样」改成「每次发布留一条断言结果」：

  ① `check_pair()`  —— 对一集判两条硬断言：
        A. `manifest.script_sha256 == sha256(script)`（双向绑定）
        B. `manifest.mtime >= script.mtime`（交付信号不得早于被交付物）
     任一不成立 = `DELIVERY_BINDING_BROKEN`。
  ② `scan_dir()`    —— 扫全目录，逐集出判据（供前置门/生产线/云端在消费前自检）。
  ③ `append_ledger()` —— 每次判定追加一行 JSONL。★**这是唯一能在窗口闭合后仍留下
     记录的东西**：窗口会自愈，台账不会。

★本门刻意**不**把 `delivery_state` 列为必填：E53–E76 全部发布于该字段存在之前，
把它设成必填等于用一条新规矩追溯判旧件全红（M-090 只读纪律）。它只作正向信号报出。

CLI：
    python3 delivery_binding_gate.py <scripts_dir> [--ledger <path>] [--json]
    退出码 0 = 全 PASS；1 = 有 BROKEN；2 = 有孤件（正文无 manifest / manifest 无正文）
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import re
import sys
from typing import Any, Dict, List, Optional

SCRIPT_RE = re.compile(r"^E(\d+)剧本_ClaudeWriter_v(\d+)\.md$")
MANIFEST_FMT = "{ep}_manifest_v{ver}.json"

# ★键名有两代，必须两代都读（SM-METHOD-022 自检落地）：
#   E53–E72 一代写 `sha256`，E73 起改写 `script_sha256`。
# 首版本件只读 `script_sha256`，实跑 scripts/ 得到 **E54–E70 满屏 MISSING**——
# 那份输出长得跟"历史件全线断绑"一模一样，而它是**我调错了键**，不是件坏了。
# 同 CL2X-1066 §③ 的 `:None`：一个误调用产生的 FAIL，比一个真 FAIL 更像大事故。
SHA_KEYS = ("script_sha256", "sha256")
SHA_KEY = SHA_KEYS[0]

# Roger 终裁弃集：不得恢复、不得重排，也不得为了让本门变绿而给它补一份 manifest。
ABANDONED = frozenset({"E32", "E33", "E34"})

VERDICT_PASS = "PASS"
VERDICT_BROKEN = "DELIVERY_BINDING_BROKEN"
VERDICT_ORPHAN = "ORPHAN_NO_MANIFEST"
VERDICT_UNREADABLE = "MANIFEST_UNREADABLE"


def sha256_file(p) -> str:
    return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()


def check_pair(script_path, manifest_path, sha_key: str = SHA_KEY) -> Dict[str, Any]:
    """对一集判两条硬断言。返回可入台账的记录（不落盘）。"""
    s = pathlib.Path(script_path)
    m = pathlib.Path(manifest_path)
    rec: Dict[str, Any] = {
        "script": s.name,
        "manifest": m.name,
        "checked_at_utc": _iso(datetime.datetime.now(datetime.timezone.utc).timestamp()),
    }
    if not s.exists():
        rec.update(verdict=VERDICT_ORPHAN, reason="正文不存在")
        return rec
    if not m.exists():
        rec.update(
            verdict=VERDICT_ORPHAN,
            reason="manifest 不存在（★注意：这也是「正在写」的表现，交付信号是一个缺席）",
            script_sha256=sha256_file(s),
            script_mtime_utc=_iso(s.stat().st_mtime),
        )
        return rec

    s_st, m_st = s.stat(), m.stat()
    rec["script_mtime_utc"] = _iso(s_st.st_mtime)
    rec["manifest_mtime_utc"] = _iso(m_st.st_mtime)
    rec["script_bytes"] = s_st.st_size
    rec["manifest_bytes"] = m_st.st_size

    actual = sha256_file(s)
    rec["script_sha256_actual"] = actual

    try:
        obj = json.loads(m.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        rec.update(verdict=VERDICT_UNREADABLE, reason=f"manifest JSON 解析失败：{e}")
        return rec

    keys = (sha_key,) + tuple(k for k in SHA_KEYS if k != sha_key)
    recorded, used_key = None, None
    for k in keys:
        if isinstance(obj.get(k), str):
            recorded, used_key = obj[k], k
            break
    rec["script_sha256_recorded"] = recorded
    rec["sha_key_used"] = used_key
    rec["delivery_state"] = obj.get("delivery_state")  # 正向信号，缺席不判 FAIL

    problems: List[str] = []
    # A. 双向绑定
    if recorded is None:
        problems.append("MISSING_SHA_KEY:" + "|".join(keys))
    elif recorded != actual:
        problems.append("SHA_MISMATCH")
    # B. 交付信号不得早于被交付物（毫秒级同秒视为同刻，容差 0）
    if m_st.st_mtime < s_st.st_mtime:
        problems.append(
            "MANIFEST_OLDER_THAN_SCRIPT:%.3fs" % (s_st.st_mtime - m_st.st_mtime)
        )

    rec["problems"] = problems
    rec["verdict"] = VERDICT_PASS if not problems else VERDICT_BROKEN
    return rec


def scan_dir(dirpath, sha_key: str = SHA_KEY) -> List[Dict[str, Any]]:
    """扫目录里全部 `E<NN>剧本_ClaudeWriter_v<K>.md`，逐集判。按集号排序。"""
    d = pathlib.Path(dirpath)
    out: List[Dict[str, Any]] = []
    for p in sorted(d.iterdir()):
        mm = SCRIPT_RE.match(p.name)
        if not mm:
            continue
        ep, ver = mm.group(1), mm.group(2)
        rec = check_pair(p, d / MANIFEST_FMT.format(ep=f"E{ep}", ver=ver), sha_key)
        rec["episode"] = f"E{ep}"
        rec["version"] = f"v{ver}"
        out.append(rec)

    # ★孤件要分两种，否则本门每轮都会用几十条历史 v1 把当批那一条真问题淹掉：
    #   盘上 E28–E67 存着 v1 正文（v1 时代不产 manifest）——它们不是"正在写"，是历史件。
    newest = {}
    for r in out:
        ep = r["episode"]
        newest[ep] = max(newest.get(ep, 0), int(r["version"][1:]))
    for r in out:
        if r.get("verdict") != VERDICT_ORPHAN:
            continue
        v = int(r["version"][1:])
        if r["episode"] in ABANDONED:
            r["orphan_class"] = "ABANDONED_BY_ROGER_FINAL"  # 不得恢复、不得重排、不补 manifest
        elif v < newest[r["episode"]]:
            r["orphan_class"] = "SUPERSEDED_OLD_VERSION"
        elif v == 1:
            r["orphan_class"] = "V1_HISTORICAL_NO_MANIFEST"
        else:
            r["orphan_class"] = "ACTIVE_MISSING_MANIFEST"  # ★只有这一类要人管
    return sorted(out, key=lambda r: (int(r["episode"][1:]), r["version"]))


def scan_inflight_final_path(dirpath, markers=("@@AUDIT@@", "@@SCENE@@", "@@")) -> List[Dict[str, Any]]:
    """★CL2X-1068 §① 的直接检测：最终路径上是否有半截态（未替换占位符）。

    区分「在写」与「已交」的信号不该是一个缺席；在拿到正向信号之前，这是次优替代。
    """
    d = pathlib.Path(dirpath)
    hits = []
    for p in sorted(d.iterdir()):
        if not SCRIPT_RE.match(p.name):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        found = {mk: text.count(mk) for mk in markers if text.count(mk)}
        if found:
            hits.append({"file": p.name, "markers": found})
    return hits


def append_ledger(ledger_path, records: List[Dict[str, Any]], context: Optional[Dict[str, Any]] = None) -> int:
    """把判定结果逐行追加进 JSONL 台账。返回写入行数。

    ★只追加、不改写：窗口会自愈，台账不会。
    """
    lp = pathlib.Path(ledger_path)
    lp.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(lp, "a", encoding="utf-8") as f:
        for r in records:
            row = dict(r)
            if context:
                row["_ctx"] = context
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
        f.flush()
        os.fsync(f.fileno())
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="交付绑定门（sha 双向绑定 + manifest 不得早于正文）")
    ap.add_argument("dirpath", nargs="?", default=".")
    ap.add_argument("--ledger", default=None, help="JSONL 台账路径；给了才写")
    ap.add_argument("--round", dest="round_tag", default="MANUAL")
    ap.add_argument("--json", action="store_true", help="只打 JSON")
    a = ap.parse_args(argv)

    recs = scan_dir(a.dirpath)
    inflight = scan_inflight_final_path(a.dirpath)

    broken = [r for r in recs if r.get("verdict") == VERDICT_BROKEN]
    orphan = [
        r for r in recs
        if r.get("verdict") == VERDICT_UNREADABLE
        or (r.get("verdict") == VERDICT_ORPHAN
            and r.get("orphan_class") == "ACTIVE_MISSING_MANIFEST")
    ]
    historical = [r for r in recs if r.get("verdict") == VERDICT_ORPHAN and r not in orphan]

    if a.ledger:
        append_ledger(a.ledger, recs, {"round": a.round_tag, "dir": str(a.dirpath)})

    summary = {
        "dir": str(a.dirpath),
        "round": a.round_tag,
        "checked": len(recs),
        "pass": len(recs) - len(broken) - len(orphan) - len(historical),
        "broken": [r["episode"] for r in broken],
        "orphan_active": [r["episode"] for r in orphan],
        "orphan_historical_v1_or_superseded": len(historical),
        "inflight_placeholders_on_final_path": inflight,
        "delivery_state_present": [r["episode"] for r in recs if r.get("delivery_state")],
    }
    if a.json:
        print(json.dumps({"summary": summary, "records": recs}, ensure_ascii=False, indent=1))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        for r in broken + orphan:
            print("  !", r["episode"], r["version"], r.get("verdict"),
                  r.get("problems") or r.get("orphan_class") or r.get("reason"))

    if broken:
        return 1
    if orphan:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
