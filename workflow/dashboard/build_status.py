#!/usr/bin/env python3
"""制片人&监制工作台 - 状态生成器 (producer.dashboard.v1)

扫描项目真实文件, 合并人工阶段标注, 产出 status.json(机器) + status.js(供 file:// 打开的网页读取)。
可移植: 所有项目相关路径集中在 CONFIG; 其他项目只需改 CONFIG 与 pipeline_state.json。
标准工作流: 监制每轮巡检/会话收尾运行本脚本一次。
用法: python3 build_status.py [--root /path/to/project]
"""
import json, re, sys, time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(sys.argv[sys.argv.index("--root") + 1]) if "--root" in sys.argv else HERE.parent.parent

CONFIG = {
    "mail_in": ROOT / "workflow/CODEX_TO_CLAUDE.md",        # 工厂 -> 监制
    "mail_out": ROOT / "codex_docs/CLAUDE_TO_CODEX.md",     # 监制 -> 工厂
    "gate_registry": ROOT / "configs/GATE_REGISTRY_v3_20260716.json",
    "gate_results_dir": ROOT / "qa/gate_results",   # 每集每门真实运行结果契约(codex 运行时写)
    "exports_dir": ROOT / "exports",
    "qa_dir": ROOT / "qa",
    "metrics_dir": ROOT / "workflow/platform_metrics",
    "credits_dir": ROOT / "workflow/credit_reports",
    "time_ledger_dir": ROOT / "workflow/time_ledger",
    "script_review_dir": ROOT / "workflow/script_review/reviews",
    "script_review_memory": ROOT / "workflow/script_review/剧本审核_经验记忆_MEMORY.md",
    "full_series_map": ROOT / "configs/full_series_information_node_map_v0_20260716.json",
    "pipeline_state": HERE / "pipeline_state.json",
    "max_mail": 6,
}

MSG_ID = r"\[?((?:CL2X|SC2X|C2C|C2SC)-\d+)\]?"

def mail_headers(path: Path, limit: int):
    """解析信箱头部(兼容 '# [ID] ...'、'## [ID] ...'、'## ID｜title｜date｜STATUS'), 按 ID 降序返回最新 limit 条。
    未读数不在此计算(见 unread_count: 以对方信箱的回执引用为读取标记)。"""
    rows, esc = [], []
    if not path.exists():
        return rows, esc, ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    for h in re.findall(r"^(#{1,6} .*)$", text, re.M):
        hid = re.search(MSG_ID, h)
        if not hid:
            continue  # 非信件标题(如文件 H1)
        rows.append({"id": hid.group(1), "title": re.sub(r"\s+", " ", h)[:160]})
    for m in re.finditer(r"^.*ESCALATE_TO_ROGER.*$", text, re.M):
        line = re.sub(r"\s+", " ", m.group(0)).strip()[:200]
        if line not in esc:
            esc.append(line)
    rows.sort(key=lambda r: int(re.search(r"-(\d+)$", r["id"]).group(1)), reverse=True)
    return rows, esc[-8:], text

def unread_count(own_rows_sorted, own_prefix: str, counterpart_text: str):
    """未读 = 本箱中 ID 大于对方信箱正文所引用的本箱最大 ID 的消息数。
    (读取标记 = 对方在回执/正文中引用编号, 而非本箱标题里的 NEW 字样——历史 NEW 字样不代表未读)"""
    refs = [int(n) for n in re.findall(own_prefix + r"-(\d+)", counterpart_text)]
    high = max(refs) if refs else -1
    def num(r):
        return int(re.search(r"-(\d+)$", r["id"]).group(1))
    return sum(1 for r in own_rows_sorted if r["id"].startswith(own_prefix) and num(r) > high)

def latest_ci(qa_dir: Path, ep: str, override: str = None):
    """找该集最新 regression CI JSON, 返回 status 与 failure 数。
    排除 *_BASE.json(回测冻结底片, 非现行成片 CI, 不得覆盖发布态);
    pipeline_state 中该集可用 ci_file 手工指定事实源。"""
    best = None
    if override:
        p = ROOT / override
        best = p if p.exists() else None
    else:
        for p in qa_dir.rglob(f"*{ep}*REGRESSION_CI*.json"):
            if p.name.upper().endswith("_BASE.JSON"):
                continue
            if best is None or p.stat().st_mtime > best.stat().st_mtime:
                best = p
    if not best:
        return None
    try:
        d = json.loads(best.read_text())
        return {"file": best.name, "status": d.get("status"),
                "failures": len(d.get("failures") or []),
                "asl": round((d.get("asl") or {}).get("mean", 0), 2),
                "motion": round(d.get("motion_mean", 0), 2)}
    except Exception:
        return {"file": best.name, "status": "UNREADABLE", "failures": -1}

def latest_export(exports_dir: Path, ep: str):
    d = exports_dir / ep.lower()
    if not d.is_dir():
        return None
    subs = sorted([p for p in d.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime)
    return subs[-1].name if subs else None

def latest_metrics(metrics_dir: Path, ep: str):
    best = None
    for p in metrics_dir.glob(f"{ep}_metrics_*.json"):
        if best is None or p.stat().st_mtime > best.stat().st_mtime:
            best = p
    if not best:
        return None
    try:
        d = json.loads(best.read_text())
        flat = json.dumps(d, ensure_ascii=False)
        plays = re.search(r'"plays"\s*:\s*"?(\d+)', flat)
        likes = re.search(r'"likes"\s*:\s*"?(\d+)', flat)
        return {"file": best.name, "plays": int(plays.group(1)) if plays else None,
                "likes": int(likes.group(1)) if likes else None}
    except Exception:
        return None

def latest_credits(credits_dir: Path, ep: str):
    """该集最新积分账本。任务数不是积分代理，actual 只能来自真账。"""
    best = None
    for p in credits_dir.glob(f"{ep}_*.json"):
        try:
            candidate = json.loads(p.read_text())
        except Exception:
            continue
        if "actual_credits_total" not in candidate:
            continue
        if best is None or p.stat().st_mtime > best.stat().st_mtime:
            best = p
    if not best:
        return None
    try:
        d = json.loads(best.read_text())
        total = d.get("actual_credits_total")
        out = {"file": best.name,
               "video_tasks": d.get("video_task_count"),
               "image_tasks": d.get("image_task_count"),
               "submitted_tasks": d.get("submitted_task_count")}
        out["credits"] = total if isinstance(total, (int, float)) else None
        out["reconciled"] = isinstance(total, (int, float))
        # 重做账本独立分账(E##R_*), 与原版并列显示
        rbest = None
        for p in credits_dir.glob(f"{ep}R_*.json"):
            if rbest is None or p.stat().st_mtime > rbest.stat().st_mtime:
                rbest = p
        if rbest:
            try:
                rd = json.loads(rbest.read_text())
                rt = rd.get("actual_credits_total")
                out["remake"] = {"file": rbest.name,
                                 "video_tasks": rd.get("video_task_count"),
                                 "image_tasks": rd.get("image_task_count"),
                                 "credits": rt if isinstance(rt, (int, float)) else None}
            except Exception:
                pass
        return out
    except Exception:
        return None

def _episode_id(value):
    m = re.search(r"(E\d{2})", str(value or "").upper())
    return m.group(1) if m else None

def _duration_from_json(value):
    if isinstance(value, dict):
        direct = value.get("duration_seconds")
        if isinstance(direct, (int, float)) and direct > 0:
            return float(direct)
        for child in value.values():
            found = _duration_from_json(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _duration_from_json(child)
            if found:
                return found
    return None

def latest_release_duration(release_dir: Path, ep: str):
    episode_dir = release_dir / ep.lower()
    candidates = sorted(episode_dir.rglob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if episode_dir.exists() else []
    for path in candidates:
        try:
            duration = _duration_from_json(json.loads(path.read_text()))
        except Exception:
            continue
        if duration:
            return {"seconds": round(duration, 3), "file": path.name}
    return None

def generation_accounting(credits_dir: Path, tasks_dir: Path, release_dir: Path):
    """Build per-episode cost rows from real receipts; never infer credits from task counts."""
    action_ledger_path = credits_dir / "REMOTE_GENERATION_ACTION_CREDIT_LEDGER.json"
    action_episodes = {}
    if action_ledger_path.exists():
        try:
            action_ledger = json.loads(action_ledger_path.read_text())
            if isinstance(action_ledger.get("episodes"), dict):
                action_episodes = action_ledger["episodes"]
        except Exception:
            action_episodes = {}
    episodes = set()
    for path in credits_dir.glob("E*.json"):
        ep = _episode_id(path.name)
        if ep:
            episodes.add(ep)
    task_files = list(tasks_dir.glob("E*.json")) if tasks_dir.exists() else []
    for path in task_files:
        ep = _episode_id(path.name)
        if ep:
            episodes.add(ep)

    # 工作台只从 E28 起显示(Claude 剧本 + 新架构起点,历史集不显示;Roger 2026-07-22)
    episodes = {ep for ep in episodes if int(ep[1:]) >= 28}
    rows = []
    for ep in sorted(episodes, key=lambda value: int(value[1:])):
        seen = set()
        video_tasks = image_tasks = rerolls = 0
        workflow_hints = []
        for path in task_files:
            if _episode_id(path.name) != ep:
                continue
            upper_name = path.name.upper()
            if "STANDARD_STORYBOARD" in upper_name:
                workflow_hints.append("SECTION_2_STANDARD_STORYBOARD")
            elif "FULL_DIALOGUE" in upper_name or "DIALOGUE" in upper_name:
                workflow_hints.append("LEGACY_FULL_DIALOGUE")
            try:
                payload = json.loads(path.read_text())
            except Exception:
                continue
            tasks = payload.get("tasks") if isinstance(payload, dict) else None
            if not isinstance(tasks, list):
                continue
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                task_key = str(task.get("task_key") or task.get("key") or task.get("source_id") or "")
                task_id = str(task.get("task_id") or task.get("remote_task_id") or "")
                identity = task_id or f"{path.name}:{task_key}"
                if identity in seen:
                    continue
                seen.add(identity)
                tool_type = str(task.get("tool_type") or "").lower()
                output = str(task.get("output_path") or task.get("path") or "").lower()
                status = str(task.get("status") or "").lower()
                if "image" in tool_type or output.endswith((".png", ".jpg", ".jpeg", ".webp")) or status == "image_pass":
                    image_tasks += 1
                elif "video" in tool_type or output.endswith((".mp4", ".mov", ".webm")) or task_id:
                    video_tasks += 1
                metadata = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
                if re.search(r"(?:^|[-_])R\d+(?:[-_]|$)", task_key, re.I) or "FAILED-ONLY" in task_key.upper() or metadata.get("retry_of_task_key"):
                    rerolls += 1

        credits = latest_credits(credits_dir, ep)
        actual = credits.get("credits") if credits else None
        action_cost = action_episodes.get(ep) if isinstance(action_episodes.get(ep), dict) else None
        known_actual = action_cost.get("known_actual_credits") if action_cost else None
        unknown_success_count = int(action_cost.get("unknown_success_count") or 0) if action_cost else 0
        failed_zero_charge_count = int(action_cost.get("failed_zero_charge_count") or 0) if action_cost else 0
        actual_complete = bool(action_cost) and unknown_success_count == 0
        if actual_complete and isinstance(known_actual, (int, float)):
            actual = known_actual
        duration = latest_release_duration(release_dir, ep)
        duration_seconds = duration.get("seconds") if duration else None
        if "SECTION_2_STANDARD_STORYBOARD" in workflow_hints or int(ep[1:]) >= 24:
            workflow = "SECTION_2_STANDARD_STORYBOARD"
        elif "LEGACY_FULL_DIALOGUE" in workflow_hints:
            workflow = "LEGACY_FULL_DIALOGUE"
        else:
            workflow = "UNCLASSIFIED"
        rows.append({
            "episode": ep,
            "actual_credits": actual if isinstance(actual, (int, float)) else "PENDING_ACCOUNT_RECONCILIATION",
            "reconciled": isinstance(actual, (int, float)) and (not action_cost or actual_complete),
            "known_actual_credits": known_actual if isinstance(known_actual, (int, float)) else None,
            "unknown_success_count": unknown_success_count,
            "failed_zero_charge_count": failed_zero_charge_count,
            "video_tasks": video_tasks,
            "image_tasks": image_tasks,
            "rerolls": rerolls,
            "workflow": workflow,
            "final_duration_seconds": duration_seconds,
            "roi_credits_per_final_second": round(actual / duration_seconds, 4) if isinstance(actual, (int, float)) and duration_seconds else None,
            "credit_source": action_ledger_path.name if action_cost else (credits.get("file") if credits else None),
            "duration_source": duration.get("file") if duration else None,
        })

    comparison = {}
    for workflow in ("LEGACY_FULL_DIALOGUE", "SECTION_2_STANDARD_STORYBOARD"):
        values = [row["roi_credits_per_final_second"] for row in rows if row["workflow"] == workflow and row["roi_credits_per_final_second"] is not None]
        comparison[workflow] = {
            "reconciled_episode_count": len(values),
            "average_roi": round(sum(values) / len(values), 4) if values else None,
            "status": "READY" if values else "PENDING_ACCOUNT_RECONCILIATION",
        }
    return {"rows": rows, "comparison": comparison, "credit_policy": "ACTUAL_ONLY_FROM_PER_ACTION_API_CREDIT_OR_VERIFIED_LEDGER; FAILED_ACTIONS_ZERO; UNKNOWN_NEVER_ESTIMATED"}

def time_ledger(ledger_dir: Path, ep: str):
    """时间账: 周期起点、当前阶段、阶段停留时长、是否超 SLA (schema qingshan.episode_time_ledger.v1)。"""
    p = ledger_dir / f"{ep}_time_ledger.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
        events = d.get("events") or []
        def ts(s):
            return time.mktime(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S"))
        start = ts(events[0]["at"]) if events else None
        last = ts(events[-1]["at"]) if events else None
        now = time.time()
        out = {
            "phase": d.get("current_phase", ""),
            "cycle_hours": round((now - start) / 3600, 1) if start else None,
            "phase_dwell_min": round((now - last) / 60) if last else None,
            "cycle_target_hours": round(float(d.get("cycle_target_seconds", 0)) / 3600, 1) or None,
            "parallel_lines": d.get("parallel_lines") or [],
        }
        # 超 SLA 判定: 当前阶段停留 > 最长单阶段 SLA(粗判), 或周期 > 目标
        slas = list((d.get("phase_sla_seconds") or {}).values())
        max_sla_min = max(slas) / 60 if slas else None
        out["sla_breach"] = bool(
            (max_sla_min and out["phase_dwell_min"] and out["phase_dwell_min"] > max_sla_min) or
            (out["cycle_target_hours"] and out["cycle_hours"] and out["cycle_hours"] > out["cycle_target_hours"]))
        return out
    except Exception:
        return None

def parallel_line_sla_breaches(lines, now=None, idle_seconds=1800, remote_seconds=4800):
    """Return executable heartbeat breaches for active three-line production."""
    now = now or datetime.now().astimezone()
    allowed = {
        "REMOTE_GENERATION", "AWAITING_ROGER", "AWAITING_SUPERVISOR_REPLY", "SESSION_ENDED", "NONE",
        "SCRIPT_DENSITY_GATE", "HUMAN_REVIEW", "VOICE_ISOLATION",
        "REMOTE_VOICE_ASSET_REGISTRATION", "PROVIDER_TIMEOUT", "PLATFORM_BACKFILL", "CREDIT_OR_QUOTA",
    }
    breaches = []
    for line in lines:
        line_id = line.get("line_id") or line.get("episode") or "UNKNOWN"
        blocked_by = line.get("blocked_by")
        heartbeat = line.get("last_heartbeat_at")
        if blocked_by not in allowed:
            breaches.append({"line_id": line_id, "kind": "MISSING_OR_INVALID_BLOCKED_BY", "blocked_by": blocked_by})
            continue
        if not heartbeat:
            breaches.append({"line_id": line_id, "kind": "MISSING_LAST_HEARTBEAT_AT", "blocked_by": blocked_by})
            continue
        try:
            observed = datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=now.tzinfo)
            age_seconds = max(0, int((now - observed).total_seconds()))
        except Exception:
            breaches.append({"line_id": line_id, "kind": "INVALID_LAST_HEARTBEAT_AT", "blocked_by": blocked_by})
            continue
        if blocked_by == "NONE" and age_seconds > idle_seconds:
            breaches.append({"line_id": line_id, "kind": "IDLE_WITHOUT_BLOCKER", "age_seconds": age_seconds, "blocked_by": blocked_by})
        elif blocked_by == "REMOTE_GENERATION" and age_seconds > remote_seconds:
            breaches.append({"line_id": line_id, "kind": "REMOTE_GENERATION_UNHARVESTED", "age_seconds": age_seconds, "blocked_by": blocked_by})
    return breaches

def gates(path: Path):
    if not path.exists():
        return {"count": 0, "items": []}
    try:
        d = json.loads(path.read_text())
        items = d.get("gates") or d.get("items") or []
        out = []
        for g in items:
            out.append({"name": str(g.get("gate_id") or g.get("name") or g.get("gate") or "?")[:60],
                        "stage": g.get("stage", ""),
                        "kind": g.get("implementation_type", g.get("kind", g.get("type", "")))})
        return {"count": len(items), "items": out}
    except Exception:
        return {"count": -1, "items": [], "error": "unreadable"}

def gate_matrix(registry_path: Path, results_dir: Path, episodes: list):
    """每集×每门 强制执行矩阵。行=注册表全部门,列=每集,格默认'未运行'。
    只有拿到该集该门的真实结果契约才变 PASS/FAIL/分数 —— 从根上让'登记≠执行'现形。
    数据契约(codex 运行门时写):qa/gate_results/E{NN}/{GATE_ID}.json
      = {"gate_id","episode","invoked":true,"status":"PASS|FAIL|N_A|PENDING_MANUAL","score":<可选>,"ran_at","evidence"}
    也兼容单文件形式 qa/gate_results/E{NN}.json = {GATE_ID:{...}, ...}。
    """
    reg = gates(registry_path)
    gate_items = reg.get("items", [])
    eps = [e["id"] if isinstance(e, dict) else e for e in episodes]

    def load_ep_results(ep):
        """返回 {GATE_ID: result_dict}。目录形式优先,单文件形式兜底。"""
        out = {}
        single = results_dir / f"{ep}.json"
        if single.exists():
            try:
                d = json.loads(single.read_text())
                if isinstance(d, dict):
                    out.update({k: v for k, v in d.items() if isinstance(v, dict)})
            except Exception:
                pass
        epdir = results_dir / ep
        if epdir.is_dir():
            for f in epdir.glob("*.json"):
                try:
                    r = json.loads(f.read_text())
                    gid = r.get("gate_id") or f.stem
                    out[gid] = r
                except Exception:
                    pass
        return out

    STATUS_MAP = {  # 契约 status -> (显示符, 语义类)
        "PASS": ("✓", "pass"), "FAIL": ("✗", "fail"),
        "N_A": ("·", "na"), "NA": ("·", "na"),
        "PENDING_MANUAL": ("◔", "pending"), "PENDING": ("◔", "pending"),
    }

    cells = {}          # gate_id -> {ep -> cell}
    ep_summary = {ep: dict(ran=0, passed=0, failed=0, not_run=0, pending=0, na=0) for ep in eps}
    per_ep_results = {ep: load_ep_results(ep) for ep in eps}

    for g in gate_items:
        gid = g["name"]
        cells[gid] = {}
        for ep in eps:
            r = per_ep_results[ep].get(gid)
            s = ep_summary[ep]
            if not r or not r.get("invoked"):
                cells[gid][ep] = {"sym": "—", "cls": "notrun", "title": "未运行/无结果证据"}
                s["not_run"] += 1
                continue
            st = str(r.get("status", "")).upper()
            score = r.get("score")
            if score is not None and st not in ("FAIL", "N_A", "NA"):
                sym = str(score)
                cls = "pass" if (isinstance(score, (int, float)) and score >= 3) else "fail"
            else:
                sym, cls = STATUS_MAP.get(st, ("?", "pending"))
            cells[gid][ep] = {"sym": sym, "cls": cls,
                              "title": f"{st} {('· '+str(score)) if score is not None else ''}· {r.get('ran_at','')}"}
            s["ran"] += 1
            if cls == "pass":
                s["passed"] += 1
            elif cls == "fail":
                s["failed"] += 1
            elif cls == "pending":
                s["pending"] += 1
            elif cls == "na":
                s["na"] += 1

    # 孤儿门 = 在所有已显示集里从未运行过
    orphans = [g["name"] for g in gate_items
               if all(cells[g["name"]][ep]["cls"] == "notrun" for ep in eps)] if eps else []

    return {
        "note": "行=注册表全部门, 列=每集; 格默认'未运行(—)', 有真实结果契约才变 ✓/✗/分数。孤儿门=整行未运行。",
        "contract_path": "qa/gate_results/E{NN}/{GATE_ID}.json",
        "gate_count": len(gate_items),
        "episodes": eps,
        "gates": gate_items,
        "cells": cells,
        "episode_summary": ep_summary,
        "orphans": orphans,
        "orphan_count": len(orphans),
    }

def main():
    state = json.loads(CONFIG["pipeline_state"].read_text())
    inbox, esc_in, in_text = mail_headers(CONFIG["mail_in"], CONFIG["max_mail"])
    outbox, esc_out, out_text = mail_headers(CONFIG["mail_out"], CONFIG["max_mail"])
    new_in = unread_count(inbox, "C2SC", out_text)
    new_out = unread_count(outbox, "CL2X", in_text)
    eps = []
    for e in state.get("episodes", []):
        ep = dict(e)
        ep["latest_export"] = latest_export(CONFIG["exports_dir"], e["id"])
        ep["ci"] = latest_ci(CONFIG["qa_dir"], e["id"], e.get("ci_file"))
        ep["metrics"] = latest_metrics(CONFIG["metrics_dir"], e["id"])
        ep["credits"] = latest_credits(CONFIG["credits_dir"], e["id"])
        ep["time"] = time_ledger(CONFIG["time_ledger_dir"], e["id"])
        eps.append(ep)
    parallel_lines = []
    for ep in eps:
        if ep.get("time"):
            parallel_lines.extend(ep["time"].get("parallel_lines") or [])
    status = {
        "schema": "producer.dashboard.status.v1",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "project": state.get("project", {}),
        "stages": state.get("stages", []),
        "episodes": eps,
        "escalations": esc_in + esc_out + [
            {"manual": n} for n in state.get("decisions_pending_roger", [])],
        "manual_notes": state.get("manual_notes", []),
        "mailboxes": {
            "new_basis": "未读=ID 大于对方信箱回执引用的最大编号(标题内历史 NEW 字样不代表未读)",
            "factory_to_supervisor": {"latest": inbox[:CONFIG["max_mail"]], "new": new_in},
            "supervisor_to_factory": {"latest": outbox[:CONFIG["max_mail"]], "new": new_out},
        },
        "gate_registry": gates(CONFIG["gate_registry"]),
        "gate_matrix": gate_matrix(CONFIG["gate_registry"], CONFIG["gate_results_dir"], eps),
        "sla_breaches": parallel_line_sla_breaches(parallel_lines),
        "cost_accounting": generation_accounting(
            CONFIG["credits_dir"], ROOT / "workflow/tasks", ROOT / "workflow/release"),
    }
    (HERE / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=1))
    (HERE / "status.js").write_text("window.DASHBOARD_STATUS=" + json.dumps(status, ensure_ascii=False) + ";")
    print("dashboard status written:", HERE / "status.json")

if __name__ == "__main__":
    main()
