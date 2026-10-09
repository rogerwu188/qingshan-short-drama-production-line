#!/usr/bin/env python3
"""Start, resume and monitor the unattended Claude Code production run for one episode.

The OpenClaw agent owns the conversation with the line owner; Claude Code owns S1-S7.  This tool is
the only bridge between them:

  start  --episode E01 [--brief <file>]   launch a background ``claude -p`` run with the production
                                          contract (CLAUDE_CODE_PRODUCTION.md) as its task
  resume --episode E01 --message <text>   continue the same Claude Code session in the background,
                                          e.g. with the owner's verbatim reply to a decision
  status --episode E01                    is a run alive?  what did Claude Code last report
                                          (its NALU_STATUS line)?  what does the pipeline state say?

Each run streams JSON events to ``$NALU_RUNTIME_ROOT/claude_code/<EP>/run_<ts>.jsonl``; the session
id is kept in ``session.json`` so every resume continues the same Claude Code conversation.
Claude Code ends every turn with one line ``NALU_STATUS: {...}`` (see the contract); ``status``
extracts it so the agent never has to parse prose.
"""
from __future__ import annotations

import argparse
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
CONTRACT = HERE.parent / "CLAUDE_CODE_PRODUCTION.md"
STATUS_RE = re.compile(r"NALU_STATUS:\s*(\{.*\})")


def roots() -> tuple[Path, Path]:
    engine = Path(os.environ.get("NALU_ENGINE_ROOT") or "~/nalu_engine").expanduser()
    runtime = Path(os.environ.get("NALU_RUNTIME_ROOT") or "~/nalu_runtime").expanduser()
    return engine, runtime


def run_dir(episode: str) -> Path:
    d = roots()[1] / "claude_code" / episode
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def launch(episode: str, prompt: str, resume_id: str | None) -> dict[str, Any]:
    exe = shutil.which("claude")
    if not exe:
        return {"status": "BLOCKED", "reason": "CLAUDE_CODE_NOT_INSTALLED"}
    d = run_dir(episode)
    session = read_json(d / "session.json")
    if alive(session.get("pid")):
        return {"status": "ALREADY_RUNNING", "pid": session.get("pid"), "log": session.get("log")}
    engine, _ = roots()
    log = d / f"run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    argv = [exe, "-p", prompt, "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits"]
    if resume_id:
        argv += ["--resume", resume_id]
    env = dict(os.environ)
    env.pop("GIGGLE_API_KEY", None)  # paid steps source $NALU_ENGINE_ROOT/.env themselves
    with open(log, "w", encoding="utf-8") as out:
        proc = subprocess.Popen(argv, cwd=engine, stdout=out, stderr=subprocess.STDOUT, env=env,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    session.update({"episode": episode, "pid": proc.pid, "log": str(log),
                    "started_at": datetime.now(timezone.utc).isoformat(), "resumed_from": resume_id})
    (d / "session.json").write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "STARTED", "pid": proc.pid, "log": str(log), "resumed_from": resume_id}


def parse_log(log: Path) -> dict[str, Any]:
    info: dict[str, Any] = {"session_id": None, "result": None, "is_error": None, "nalu_status": None,
                            "last_assistant_text": None, "events": 0}
    if not log.is_file():
        return info
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        info["events"] += 1
        if ev.get("session_id"):
            info["session_id"] = ev["session_id"]
        if ev.get("type") == "assistant":
            texts = [c.get("text") for c in (ev.get("message") or {}).get("content") or []
                     if isinstance(c, dict) and c.get("type") == "text"]
            if texts:
                info["last_assistant_text"] = texts[-1][-1500:]
        if ev.get("type") == "result":
            info["result"] = str(ev.get("result") or "")[-3000:]
            info["is_error"] = ev.get("is_error")
            info["cost_usd"] = ev.get("total_cost_usd")
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start"); s.add_argument("--episode", required=True); s.add_argument("--brief", default="")
    r = sub.add_parser("resume"); r.add_argument("--episode", required=True); r.add_argument("--message", required=True)
    t = sub.add_parser("status"); t.add_argument("--episode", required=True)
    a = ap.parse_args()

    d = run_dir(a.episode)
    session = read_json(d / "session.json")
    if a.cmd == "start":
        if not CONTRACT.is_file():
            print(json.dumps({"status": "BLOCKED", "reason": f"CONTRACT_MISSING:{CONTRACT}"}))
            return 2
        brief = Path(a.brief).read_text(encoding="utf-8") if a.brief else ""
        prompt = (f"你是 NALU 短剧生产线的生产执行者。严格按照下面的生产合同执行集 {a.episode}。\n\n"
                  + CONTRACT.read_text(encoding="utf-8")
                  + (f"\n\n## 本次线主/编排代理附加说明\n{brief}" if brief else ""))
        out = launch(a.episode, prompt, None)
    elif a.cmd == "resume":
        sid = session.get("session_id") or parse_log(Path(session.get("log") or "")).get("session_id")
        if not sid:
            print(json.dumps({"status": "BLOCKED", "reason": "NO_SESSION_TO_RESUME_RUN_start_FIRST"}))
            return 2
        session["session_id"] = sid
        (d / "session.json").write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
        out = launch(a.episode, a.message, sid)
    else:
        info = parse_log(Path(session.get("log") or ""))
        if info.get("session_id") and not session.get("session_id"):
            session["session_id"] = info["session_id"]
            (d / "session.json").write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
        running = alive(session.get("pid"))
        out = {"status": "RUNNING" if running else "IDLE", "pid": session.get("pid"), "log": session.get("log"),
               "session_id": session.get("session_id"), "claude_code": info, "pipeline": pipeline_status(a.episode)}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
