#!/usr/bin/env python3
"""Run the NALU production contract with the OpenAI Codex CLI (the miniPC executor since 2026-10-13).

  start  --episode E02 [--brief <file>]   launch ``codex exec`` in the background with the contract
  resume --episode E02 --message <text>   continue the same Codex thread (``codex exec resume``)
  status --episode E02                    alive?  Codex's last NALU_STATUS?  pipeline stage states
  tick                                    the heartbeat: does every routine step itself and prints one
                                          ``NALU_TICK: {...}`` line telling the agent whether it is needed
  report                                  compact progress summary for the line owner

Line owner 2026-10-12/13: Claude Code is retired on the miniPCs (E01 cost about $208 through the relay);
Codex (gpt-6.1-sol by default) runs S1-S7.  Written and run on 新石头记 E02-E03 by the miniPC agent, folded in here.

Compatibility:
* Runs live in ``$NALU_RUNTIME_ROOT/claude_code/<EP>/`` (session.json + run_<ts>.jsonl).  When Codex exits,
  the runner appends ``{"type":"result","result":<Codex's last message verbatim>,...,"engine":"codex"}``
  so setup_host.sh / self_update.sh (claude_production.parse_log) still recognise an episode in flight.
* Provider: ``$NALU_RUNTIME_ROOT/credentials/llm_provider.json`` (base_url / api_key / model, mode 600,
  written by the agent from the owner's message); ``credentials/codex_api_key`` is the older layout.
  The key reaches codex only as $HOPS_API_KEY (the env_key configure_codex.py writes); the shell
  policy in ~/.codex/config.toml keeps it and GIGGLE_API_KEY out of every command Codex runs.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
STATUS_RE = re.compile(r"NALU_STATUS:\s*(\{.*\})")
KEY_ENV = "HOPS_API_KEY"
QUOTA_RE = re.compile(r"\b(401|402|403|429)\b|quota|insufficient|balance|余额|额度|invalid[_ ]api[_ ]key", re.I)
MAX_NO_STATUS_RESUMES = 3


def roots() -> tuple[Path, Path]:
    engine = Path(os.environ.get("NALU_ENGINE_ROOT") or "~/nalu_engine").expanduser()
    runtime = Path(os.environ.get("NALU_RUNTIME_ROOT") or "~/nalu_runtime").expanduser()
    return engine, runtime


def contract_path() -> Path:
    pinned = roots()[0] / "skills" / "nalu-claude-code" / "CLAUDE_CODE_PRODUCTION.md"
    return pinned if pinned.is_file() else HERE.parent / "CLAUDE_CODE_PRODUCTION.md"


def run_dir(episode: str) -> Path:
    d = roots()[1] / "claude_code" / episode
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:  # a zombie (exited, not yet reaped) is not a live run
        if Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].startswith("Z"):
            return False
    except (OSError, IndexError):
        pass
    return True


CODEX_ADAPTER = """
## 执行者适配（编排代理附加，优先于合同里的工具名）
你是 OpenAI Codex CLI，不是 Claude Code；合同正文按 Claude Code 写成，按下面对应：
- 「用 Read 打开图片」= 用你的 view_image 工具打开图片。审核必须真的打开图片/联系表看过再答，不准凭文件名、提示词或日志推断。
- 视频先用 ffmpeg 抽帧拼联系表，再用 view_image 看。
- **只看缩小后的图**：任何图片（关键帧、身份牌、联系表）先用 ffmpeg 缩到长边 ≤1280 px、存成 JPEG（`-q:v 4`）再 view_image；
  不要直接 view_image 原尺寸 PNG（E02 曾被 128 MB 的全尺寸 PNG 请求体卡成死循环）。
- 编辑文件用 apply_patch 或 shell；长等待用 `sleep 240`（合同 §4 S6）。
- 审核协议 `vlm_review_protocol.py` 在代码里强制 `reviewer` 必须是 `claude-code-nalu-vlm`、`review_method` 必须是
  `CLAUDE_VLM_STRUCTURED_REVIEW`：这是本线「机器审核者」的协议常量，照填；每条审核答案的 observation 末尾加「（执行者：Codex）」以便溯源。
- 记订单时 `--recorded-by codex`（不要写 claude-code）。
- 不要打印、cat、echo 任何 key（.env、credentials/、环境变量）。
- 必须在 `$NALU_ENGINE_ROOT` 下执行。
- 本轮最后一条消息的最后一行必须是合同 §6 的 `NALU_STATUS: {...}`（单行 JSON）。
"""


def provider() -> dict[str, str] | None:
    _, runtime = roots()
    cred = runtime / "credentials"
    p = read_json(cred / "llm_provider.json")
    if p.get("api_key"):
        return {k: str(v) for k, v in p.items()}
    try:
        key = (cred / "codex_api_key").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return {"api_key": key} if key else None


def codex_env() -> dict[str, str] | None:
    p = provider()
    if not p:
        return None
    engine, runtime = roots()
    env = dict(os.environ)
    env.pop("GIGGLE_API_KEY", None)
    env[KEY_ENV] = p["api_key"]
    env.setdefault("NALU_ENGINE_ROOT", str(engine))
    env.setdefault("NALU_RUNTIME_ROOT", str(runtime))
    env.setdefault("NALU_WORK_ROOT", str(engine / "workflow" / "nalu"))
    env.setdefault("NALU_QA_WORKERS", "1")
    env.setdefault("NALU_Q2_WORKERS", "1")
    env["PATH"] = f"{Path.home()}/.local/bin:{Path.home()}/.npm-global/bin:" + env.get("PATH", "")
    return env


def runner(episode: str, log: str, last: str, argv_json: str) -> int:
    """Background runner: run codex, then append its last message verbatim as a Claude-compatible result line."""
    argv = json.loads(argv_json)
    env = codex_env() or dict(os.environ)
    engine, _ = roots()
    with open(log, "a", encoding="utf-8") as out:
        rc = subprocess.call(argv, cwd=engine, stdout=out, stderr=subprocess.DEVNULL, env=env,
                             stdin=subprocess.DEVNULL)
    thread_id = None
    usage: dict[str, int] = {}
    err_msg = None
    for line in Path(log).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "thread.started":
            thread_id = ev.get("thread_id")
        if ev.get("type") == "turn.completed":
            for k, v in (ev.get("usage") or {}).items():
                if isinstance(v, int):
                    usage[k] = usage.get(k, 0) + v
        if ev.get("type") == "turn.failed":
            err_msg = json.dumps(ev.get("error"), ensure_ascii=False)[:500]
    try:
        last_text = Path(last).read_text(encoding="utf-8")
    except FileNotFoundError:
        last_text = ""
    result = {"type": "result", "engine": "codex", "session_id": thread_id, "exit_code": rc,
              "is_error": bool(rc != 0 or err_msg), "error": err_msg,
              "result": last_text[-3000:], "usage": usage,
              "finished_at": datetime.now(timezone.utc).isoformat()}
    with open(log, "a", encoding="utf-8") as out:
        out.write(json.dumps(result, ensure_ascii=False) + "\n")
    d = run_dir(episode)
    s = read_json(d / "session.json")
    if thread_id and not s.get("codex_thread_id"):
        s["codex_thread_id"] = thread_id
        s["session_id"] = thread_id
        write_json(d / "session.json", s)
    return rc


def launch(episode: str, prompt: str, resume_id: str | None) -> dict[str, Any]:
    env = codex_env()
    exe = shutil.which("codex", path=(env or os.environ).get("PATH"))
    if not exe:
        return {"status": "BLOCKED", "reason": "CODEX_NOT_INSTALLED"}
    if env is None:
        return {"status": "BLOCKED", "reason": "LLM_PROVIDER_MISSING"}
    d = run_dir(episode)
    session = read_json(d / "session.json")
    if alive(session.get("pid")):
        return {"status": "ALREADY_RUNNING", "pid": session.get("pid"), "log": session.get("log")}
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log = d / f"run_{ts}.jsonl"
    last = d / f"run_{ts}.last.txt"
    pfile = d / f"run_{ts}.prompt.md"
    pfile.write_text(prompt, encoding="utf-8")
    common = ["--json", "--dangerously-bypass-approvals-and-sandbox", "--skip-git-repo-check", "-o", str(last)]
    argv = [exe, "exec", "resume", *common, resume_id, "-"] if resume_id else [exe, "exec", *common, "-"]
    # the contract is long: feed the prompt on stdin from a file instead of argv
    argv = ["/bin/sh", "-c", 'exec "$0" "$@" < "$NALU_CODEX_PROMPT_FILE"', *argv]
    env["NALU_CODEX_PROMPT_FILE"] = str(pfile)
    log.write_text("", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_run", "--episode", episode,
                             "--log", str(log), "--last", str(last), "--argv", json.dumps(argv)],
                            cwd=roots()[0], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            stdin=subprocess.DEVNULL, env=env, start_new_session=True)
    session.update({"episode": episode, "engine": "codex", "pid": proc.pid, "log": str(log),
                    "started_at": datetime.now(timezone.utc).isoformat(), "resumed_from": resume_id})
    if not resume_id:
        session.pop("codex_thread_id", None)
        session["session_id"] = None
        session["no_status_resumes"] = 0
    write_json(d / "session.json", session)
    return {"status": "STARTED", "engine": "codex", "pid": proc.pid, "log": str(log), "resumed_from": resume_id}


def parse_log(log: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"session_id": None, "result": None, "is_error": None, "nalu_status": None,
                            "last_assistant_text": None, "events": 0, "usage": {}, "last_error": None}
    if not log.is_file():
        return info
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        info["events"] += 1
        t = ev.get("type")
        if t == "thread.started":
            info["session_id"] = ev.get("thread_id")
        elif t == "item.completed":
            it = ev.get("item") or {}
            if it.get("type") == "agent_message" and it.get("text"):
                info["last_assistant_text"] = it["text"][-1500:]
        elif t == "turn.completed":
            for k, v in (ev.get("usage") or {}).items():
                if isinstance(v, int):
                    info["usage"][k] = info["usage"].get(k, 0) + v
        elif t in ("error", "turn.failed"):
            info["last_error"] = (ev.get("message") or json.dumps(ev.get("error"), ensure_ascii=False))[:300]
        elif t == "result":
            info["result"] = str(ev.get("result") or "")[-3000:]
            info["is_error"] = ev.get("is_error")
            info["session_id"] = ev.get("session_id") or info["session_id"]
            if ev.get("engine") != "codex":  # a Claude Code run (before the switch)
                for k in ("input_tokens", "output_tokens"):
                    v = (ev.get("usage") or {}).get(k)
                    if isinstance(v, int):
                        info["usage"][k] = info["usage"].get(k, 0) + v
    text = info["result"] or info["last_assistant_text"] or ""
    found = STATUS_RE.findall(text)
    if found:
        try:
            info["nalu_status"] = json.loads(found[-1])
        except ValueError:
            info["nalu_status"] = {"raw": found[-1]}
    return info


def pipeline_status(episode: str) -> dict[str, Any]:
    _, runtime = roots()
    state = read_json(runtime / "runtime" / "pipeline_state" / f"{episode}.json")
    stages = state.get("stages") or {}
    return {sid: {"status": row.get("status"), "blockers": (row.get("blockers") or [])[:3]}
            for sid, row in stages.items()}


def build_prompt(episode: str, brief: str) -> str:
    return (f"你是 NALU 短剧生产线的生产执行者。严格按照下面的生产合同执行集 {episode}。\n\n"
            + contract_path().read_text(encoding="utf-8") + "\n" + CODEX_ADAPTER
            + (f"\n\n## 本次线主/编排代理附加说明\n{brief}" if brief else ""))


def start(episode: str, brief: str = "") -> dict[str, Any]:
    if not contract_path().is_file():
        return {"status": "BLOCKED", "reason": f"CONTRACT_MISSING:{contract_path()}"}
    out = launch(episode, build_prompt(episode, brief), None)
    if out.get("status") == "STARTED":
        series = roots()[1] / "series"
        series.mkdir(parents=True, exist_ok=True)
        (series / "CURRENT_EPISODE").write_text(episode + "\n", encoding="utf-8")
    return out


def resume(episode: str, message: str) -> dict[str, Any]:
    d = run_dir(episode)
    session = read_json(d / "session.json")
    if session.get("engine") != "codex":
        return {"status": "BLOCKED", "reason": "EPISODE_WAS_NOT_STARTED_WITH_CODEX_USE_start"}
    sid = session.get("codex_thread_id") or parse_log(Path(session.get("log") or "")).get("session_id")
    if not sid:
        return {"status": "BLOCKED", "reason": "NO_CODEX_SESSION_TO_RESUME_RUN_start_FIRST"}
    session["codex_thread_id"] = sid
    write_json(d / "session.json", session)
    return launch(episode, message + "\n（提醒：本轮最后一行仍须是 NALU_STATUS 单行 JSON。）", sid)


def status(episode: str) -> dict[str, Any]:
    session = read_json(run_dir(episode) / "session.json")
    info = parse_log(Path(session.get("log") or ""))
    return {"status": "RUNNING" if alive(session.get("pid")) else "IDLE", "episode": episode,
            "engine": session.get("engine") or "claude", "pid": session.get("pid"), "log": session.get("log"),
            "session_id": session.get("codex_thread_id") or session.get("session_id"),
            "codex": info, "pipeline": pipeline_status(episode)}


# ------------------------------------------------------------------------------------------------ tick
def note(line: str) -> None:
    path = roots()[1] / "series" / "STATUS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:  # a deferral repeats every heartbeat: write it once, not every 15 minutes
        last = [x for x in path.read_text(encoding="utf-8").splitlines() if x.strip()][-1]
        if last.split(" ", 3)[-1] == line:
            return
    except (FileNotFoundError, IndexError):
        pass
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"- {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%MZ')} {line}\n")


def episode_key(ep: str) -> tuple[int, str]:
    m = re.search(r"(\d+)", ep)
    return (int(m.group(1)) if m else 0, ep)


def current_episode() -> str | None:
    runtime = roots()[1]
    try:
        ep = (runtime / "series" / "CURRENT_EPISODE").read_text(encoding="utf-8").strip()
        if ep:
            return ep
    except FileNotFoundError:
        pass
    eps = [p.parent.name for p in (runtime / "claude_code").glob("*/session.json")]
    return max(eps, key=episode_key) if eps else None


def publish_next() -> dict[str, Any] | None:
    """Send the earliest finished-but-unsent episode (one per tick, in episode order)."""
    _, runtime = roots()
    sys.path.insert(0, str(HERE))
    import publish_x2creel as px  # noqa: E402
    sent = px.load_state().get("episodes") or {}
    ready = []
    for sess in (runtime / "claude_code").glob("*/session.json"):
        ep = sess.parent.name
        s = read_json(sess)
        st = (parse_log(Path(s.get("log") or "")).get("nalu_status") or {}).get("state")
        mp4 = runtime / "deliverables" / ep / f"{ep}_final_9x16.mp4"
        if st == "FINAL_CUT_READY" and mp4.is_file() and ep not in sent and not alive(s.get("pid")):
            ready.append(ep)
    if not ready:
        return None
    ep = min(ready, key=episode_key)
    brief = read_json(runtime / "briefs" / f"{ep}_PRODUCTION_BRIEF.json")
    args = argparse.Namespace(episode=ep, title=str(brief.get("title") or ""),
                              description=str(brief.get("synopsis") or ""), category=str(brief.get("genre") or ""),
                              video="", cover="")
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            out = px.cmd_publish(args)
    except SystemExit as exc:  # the publisher reports API failures as SystemExit(<json>)
        try:
            out = json.loads(str(exc.code))
        except ValueError:
            out = {"status": "ERROR", "detail": str(exc.code)[:300]}
    out.setdefault("episode", ep)
    st = out.get("status")
    if st == "PUBLISHED":
        note(f"X2C 发行 {ep}：第 {out.get('episode_number')} 集（{out.get('x2c_status')}）")
    elif st == "DEFERRED_PENDING_REVIEW":
        nums = [str(v.get("episode_number")) for v in out.get("pending_videos") or [] if isinstance(v, dict)]
        note(f"X2C 发行暂缓 {ep}：等待第 {','.join(nums) or '?'} 集过审，避免追加时重复发号顶掉它")
    elif st == "EPISODE_NUMBER_COLLISION":
        note(f"【需要处理】X2C {ep} 拿到第 {out.get('episode_number')} 集，与 {out.get('collides_with')} 撞号（见 SKILL.md §6）")
    else:
        note(f"X2C 发行 {ep} 失败：{json.dumps(out, ensure_ascii=False)[:300]}（下次心跳重试）")
    return out


def engine_modification() -> dict[str, Any] | None:
    """Tracked engine files changed on this host (the executor must never patch the engine).

    The full diff is kept in ``$NALU_RUNTIME_ROOT/engine_patches/<sha12>.patch`` so it survives the
    ``git stash`` setup_host.sh does at the next engine switch and can be reported upstream.  Returns
    {files, patch, sha} or None when the checkout is clean."""
    engine, runtime = roots()
    try:
        files = subprocess.run(["git", "-C", str(engine), "diff", "--name-only", "HEAD"],
                               capture_output=True, text=True, timeout=60).stdout.split()
        if not files:
            return None
        diff = subprocess.run(["git", "-C", str(engine), "diff", "HEAD"], capture_output=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    import hashlib
    sha = hashlib.sha256(diff).hexdigest()[:12]
    out = runtime / "engine_patches" / f"{sha}.patch"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(diff)
    return {"files": files, "patch": str(out), "sha": sha}


def tick() -> dict[str, Any]:
    _, runtime = roots()
    did: list[str] = []
    res: dict[str, Any] = {"action": "NONE", "did": did}
    if (runtime / "series" / "PAUSED").exists():
        res["reason"] = "PAUSED"
        return res
    modified = engine_modification()
    if modified:
        seen = runtime / "engine_patches" / ".reported"
        reported = set(seen.read_text(encoding="utf-8").split()) if seen.is_file() else set()
        if modified["sha"] not in reported:
            seen.write_text("\n".join(sorted(reported | {modified["sha"]})) + "\n", encoding="utf-8")
            note(f"【需要处理】引擎源码被改（{len(modified['files'])} 个文件），完整 diff 已存 {modified['patch']}；"
                 "不要在本机保留补丁，交给维护者修上游")
            res.update(action="AGENT", reason="ENGINE_MODIFIED_ON_HOST", engine_modification=modified)
    pub = publish_next()
    if pub:
        did.append(f"publish:{pub.get('episode')}:{pub.get('status')}")
        if pub.get("status") in ("BLOCKED", "EPISODE_NUMBER_COLLISION"):
            res.update(action="AGENT", reason=f"PUBLISH_{pub.get('status')}", publish=pub)
    ep = current_episode()
    res["episode"] = ep
    if not ep:
        res.setdefault("reason", "NO_EPISODE_STARTED")
        return res
    d = run_dir(ep)
    session = read_json(d / "session.json")
    if alive(session.get("pid")):
        res["state"] = "RUNNING"
        return res
    if session.get("engine") != "codex":  # an earlier Claude Code run, now idle: continue it with Codex
        out = start(ep, "本集此前由 Claude Code 生产、已中断；已完成的阶段流水线会自动跳过，从第一个未 PASS 的阶段继续。")
        did.append(f"start_codex:{out.get('status')}")
        if out.get("status") != "STARTED":
            res.update(action="AGENT", reason=f"START_FAILED:{out.get('reason')}")
        return res
    info = parse_log(Path(session.get("log") or ""))
    ns = info.get("nalu_status") or {}
    state = ns.get("state")
    res["state"] = state
    res["nalu_status"] = ns or None
    notify_key = f"{session.get('log')}|{state}"
    if state is not None and session.get("no_status_resumes"):
        session["no_status_resumes"] = 0
        write_json(d / "session.json", session)
    if state is None:
        err = " ".join(str(x) for x in (info.get("last_error"), info.get("result")) if x)
        if QUOTA_RE.search(err):
            reason = f"PROVIDER_ERROR:{err[:200]}"
        elif int(session.get("no_status_resumes") or 0) < MAX_NO_STATUS_RESUMES:
            out = resume(ep, "继续，并在最后输出 NALU_STATUS 行")
            session = read_json(d / "session.json")
            session["no_status_resumes"] = int(session.get("no_status_resumes") or 0) + 1
            write_json(d / "session.json", session)
            did.append(f"resume_no_status:{out.get('status')}")
            return res
        else:
            reason = f"NO_STATUS_AFTER_{MAX_NO_STATUS_RESUMES}_RESUMES"
    elif state == "WAITING_REMOTE":
        out = resume(ep, "继续")
        did.append(f"resume_waiting_remote:{out.get('status')}")
        return res
    elif state == "FINAL_CUT_READY":
        if (runtime / "series" / "SERIES_DONE").exists():
            res["reason"] = "SERIES_DONE"
            return res
        res.update(action="WRITE_NEXT_EPISODE", reason="FINAL_CUT_READY")
        return res
    else:
        reason = state
    if session.get("tick_notified") == notify_key:  # already handed to the agent once; wait
        res["reason"] = f"WAITING_ON_AGENT_OR_OWNER:{reason}"
        return res
    session["tick_notified"] = notify_key
    write_json(d / "session.json", session)
    res.update(action="AGENT", reason=reason)
    return res


def report() -> dict[str, Any]:
    _, runtime = roots()
    ep = current_episode()
    out: dict[str, Any] = {"episode": ep}
    if ep:
        st = status(ep)
        out.update(run=st["status"], nalu_status=st["codex"].get("nalu_status"),
                   tokens=st["codex"].get("usage"), pipeline={k: v["status"] for k, v in st["pipeline"].items()})
    spent: dict[str, Any] = {}
    for row in read_json(runtime / "runtime" / "budget" / "ledger.json").get("entries") or []:
        if row.get("episode"):
            spent[row["episode"]] = row.get("recorded_total_credits")
    out["local_spent_credits"] = spent
    sys.path.insert(0, str(HERE))
    import publish_x2creel as px  # noqa: E402
    x2c = px.load_state()
    out["x2c_local"] = {e: {"number": r.get("episode_number"), "status": r.get("status")}
                        for e, r in (x2c.get("episodes") or {}).items()}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            if x2c.get("project_id"):
                q = px.call("distribution/query", project_id=x2c["project_id"])
                out["x2c_remote"] = {"episodes": [(e.get("episode_number"), e.get("status")) for e in q.get("episodes") or []],
                                     "pending": [(e.get("episode_number"), e.get("status")) for e in q.get("pending_videos") or []
                                                 if isinstance(e, dict)]}
    except SystemExit as exc:
        out["x2c_remote"] = {"error": str(exc.code)[:200]}
    try:
        lines = (runtime / "series" / "STATUS.md").read_text(encoding="utf-8").splitlines()
        out["status_md_tail"] = [x for x in lines if x.strip()][-5:]
    except FileNotFoundError:
        out["status_md_tail"] = []
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start"); s.add_argument("--episode", required=True); s.add_argument("--brief", default="")
    r = sub.add_parser("resume"); r.add_argument("--episode", required=True); r.add_argument("--message", required=True)
    t = sub.add_parser("status"); t.add_argument("--episode", required=True)
    sub.add_parser("tick")
    sub.add_parser("report")
    x = sub.add_parser("_run")
    for k in ("--episode", "--log", "--last", "--argv"):
        x.add_argument(k, required=True)
    a = ap.parse_args()

    if a.cmd == "_run":
        return runner(a.episode, a.log, a.last, a.argv)
    if a.cmd == "tick":
        print("NALU_TICK: " + json.dumps(tick(), ensure_ascii=False))
        return 0
    if a.cmd == "start":
        out = start(a.episode, Path(a.brief).read_text(encoding="utf-8") if a.brief else "")
    elif a.cmd == "resume":
        out = resume(a.episode, a.message)
    elif a.cmd == "status":
        out = status(a.episode)
    else:
        out = report()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 2 if out.get("status") == "BLOCKED" else 0


if __name__ == "__main__":
    sys.exit(main())
