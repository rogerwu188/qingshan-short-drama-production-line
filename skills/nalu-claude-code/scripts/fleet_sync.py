#!/usr/bin/env python3
"""Fleet status + command channel for one device (line owner 2026-11-09, nalu-fleet service).

Called at the end of every tick (the system cron's `tick --system` every 3 min, and the agent heartbeat): it reports this machine's state to the
fleet service and runs the whitelisted commands the superadmin queued for it.  Never raises and never blocks
the tick for long (short timeouts); a machine without network or without the service just skips it.

* identity: the hardware SN (device_sn.py); the device token from first contact lives in
  $NALU_RUNTIME_ROOT/credentials/fleet_token (mode 600) and is never printed.
* report: episode / stage / state / note, the newest CODE_BLOCKER report text when blocked, local credits,
  X2C local counts, engine commit, STATUS.md tail.  No keys, no media.
* commands: diagnose (model-free health check) / agent_task (instruction for the StoryClaw agent) /
  resume (hand the message to Codex) / update (scripted: self_update, set up the pin from the updated
  AGENTS.md, resume a stopped episode when the engine moved) / pause / unpause / query.  Nothing else is executed.

  NALU_FLEET_URL overrides the service URL; NALU_FLEET_URL=off disables the channel.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_URL = "https://2-31-145-227.sslip.io"
TIMEOUT_S = 8
BLOCKER_LIMIT = 20000


def _url() -> str:
    value = (os.environ.get("NALU_FLEET_URL") or DEFAULT_URL).strip().rstrip("/")
    return "" if value.lower() in ("off", "0", "none", "") else value


def _req(method: str, path: str, body: dict | None = None, token: str = "") -> tuple[int, dict]:
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(_url() + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {}


def _token(runtime: Path, sn: str) -> str:
    path = runtime / "credentials" / "fleet_token"
    try:
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    except OSError:
        pass
    code, out = _req("POST", "/v1/register", {"device_sn": sn})
    token = str(out.get("token") or "")
    if code == 200 and token:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(token + "\n", encoding="utf-8")
        os.chmod(path, 0o600)
    return token


def _engine_sha(engine: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(engine), "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _newest_blocker(engine: Path, episode: str) -> str:
    reports = engine / "workflow" / "nalu" / episode / "preproduction" / "reports"
    files = sorted(reports.glob("*CODE_BLOCKER*.md"), key=lambda p: p.stat().st_mtime) if reports.is_dir() else []
    if not files:
        return ""
    try:
        return f"{files[-1].name}\n\n" + files[-1].read_text(encoding="utf-8", errors="replace")[:BLOCKER_LIMIT]
    except OSError:
        return ""


def build_status(cp: Any, tick_result: dict) -> tuple[dict, str, str]:
    engine, runtime = cp.roots()
    ep = cp.current_episode() or ""
    ns: dict = {}
    pipeline: dict = {}
    run = ""
    if ep:
        st = cp.status(ep)
        ns = st["codex"].get("nalu_status") or {}
        pipeline = {k: v.get("status") for k, v in (st.get("pipeline") or {}).items()}
        run = st.get("status") or ""
    stage = next((k for k, v in pipeline.items() if v not in ("PASS", "SKIPPED_ALREADY_PASS")), "") if pipeline else ""
    spent: dict[str, float] = {}
    for row in cp.read_json(runtime / "runtime" / "budget" / "ledger.json").get("entries") or []:
        if row.get("episode") and isinstance(row.get("recorded_total_credits"), (int, float)):
            spent[row["episode"]] = row["recorded_total_credits"]
    x2c: dict[str, Any] = {}
    try:
        import publish_x2c_matrix as mx  # noqa: PLC0415
        if mx.matrix_mode():
            x2c["published"] = len(mx.sent_episodes())
    except Exception:  # noqa: BLE001
        pass
    state = str(ns.get("state") or run or "")
    blocker_text = _newest_blocker(engine, ep) if ep and state == "BLOCKED" else ""
    try:
        lines = (runtime / "series" / "STATUS.md").read_text(encoding="utf-8").splitlines()
        tail = "\n".join([x for x in lines if x.strip()][-15:])
    except OSError:
        tail = ""
    status = {
        "episode": ep, "stage": stage or str(ns.get("stage") or ""), "state": state, "run": run,
        "note": str(ns.get("note") or "")[:500],
        "blocker": (blocker_text.splitlines()[0] if blocker_text else
                    str(tick_result.get("reason") or "") if tick_result.get("action") == "AGENT" else ""),
        "tick_action": tick_result.get("action"), "tick_reason": tick_result.get("reason"),
        "credits_episode": spent.get(ep), "credits_total": round(sum(spent.values()), 2),
        "pipeline": pipeline, "x2c": x2c, "engine_sha": _engine_sha(engine),
        "final_review": (tick_result.get("final_review") or {}).get("status"),
    }
    return status, blocker_text, tail


AGENT_ID = os.environ.get("NALU_AGENT_ID") or "qingshan-ai-drama-factory-minipc"
PIN_RE = re.compile(r'setup_host\.sh"?\s+--pin\s+([0-9a-f]{40})')
RESUMABLE_STATES = ("BLOCKED", "FINAL_REVIEW_REQUIRED")


def disk_pin() -> str:
    """The pin in the newest installed copy of this agent's AGENTS.md (after self_update), or ""."""
    home = Path.home()
    found: list[tuple[float, str]] = []
    for root in (home / ".openclaw", home / ".storyclaw", home):
        if not root.is_dir():
            continue
        for path in list(root.glob("*/AGENTS.md")) + list(root.glob("*/*/AGENTS.md")) + list(root.glob("*/*/*/AGENTS.md")):
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            m = PIN_RE.search(text)
            if m and "nalu" in text.lower():
                found.append((path.stat().st_mtime, m.group(1)))
    try:  # the latest pin the maintainer pushed through the fleet (agents not talenthub-installed never get a
        # newer AGENTS.md, so the next episode's update would set up the old engine again)
        fleet_pin = home / ".nalu_fleet_pin"
        value = fleet_pin.read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{40}", value):
            found.append((fleet_pin.stat().st_mtime, value))
    except OSError:
        pass
    return max(found)[1] if found else ""


def _run(argv: list[str], timeout: int, extra_env: dict | None = None) -> tuple[int, str]:
    try:
        import codex_production  # noqa: PLC0415 -- the same tool directories the executor uses
        dirs = codex_production.tool_dirs()
    except Exception:  # noqa: BLE001
        dirs = [f"{Path.home()}/.local/bin", f"{Path.home()}/.npm-global/bin"]
    env = {**os.environ, **(extra_env or {}), "PATH": ":".join([*dirs, os.environ.get("PATH", "")])}
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
        return done.returncode, (done.stdout or "")[-2000:]
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, f"{type(exc).__name__}: {exc}"


def _setup_diagnostics(out: str) -> dict:
    """status / failed_step / notes from the NALU_SETUP line plus the setup log lines about the failed step, so a
    BLOCKED setup is diagnosable from the fleet dashboard (…1324 2026-11-10: codex_config BLOCKED, cause unseen)."""
    line = next((x for x in reversed(out.splitlines()) if x.startswith("NALU_SETUP: ")), "")
    try:
        state = json.loads(line[len("NALU_SETUP: "):]) if line else {}
    except ValueError:
        state = {}
    diag = {"setup_status": state.get("status"), "setup_failed_step": state.get("failed_step"),
            "setup_steps": state.get("steps"), "setup_notes": (state.get("notes") or [])[:6]}
    if state.get("status") not in (None, "READY") and state.get("log"):
        try:
            lines = Path(str(state["log"])).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        step = str(state.get("failed_step") or "").split("_")[0]
        hits = [x for x in lines if step and step in x.lower()] or lines
        diag["setup_log_tail"] = [x[:300] for x in hits[-8:]]
    return diag


def scripted_update(cp: Any, pin: str) -> tuple[bool, dict, dict]:
    """self_update (no restart) -> setup_host --pin -> resume a stopped episode when the engine moved.

    Deterministic, no model (line owner + boss 2026-11-10): the agent-run FLEET_UPDATE once set up the stale pin
    because it read AGENTS.md before self_update had replaced it (field device …1324 E04)."""
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    engine, _ = cp.roots()
    scripts = Path(__file__).resolve().parent
    su_rc, su_out = _run(["bash", str(scripts / "self_update.sh"), "--agent-id", AGENT_ID], 600)
    if re.fullmatch(r"[0-9a-f]{40}", pin or ""):
        try:
            (Path.home() / ".nalu_fleet_pin").write_text(pin + "\n", encoding="utf-8")
        except OSError:
            pass
    pin = pin or disk_pin()
    if not re.fullmatch(r"[0-9a-f]{40}", pin or ""):
        return False, {"error": "NO_PIN", "self_update": su_out[-300:]}, {}
    before = _engine_sha(engine)
    tmp = Path(tempfile.mkdtemp(prefix="nalu_setup_"))
    # the checkout below may replace the running file, so setup runs from a copy -- of the whole scripts
    # directory: setup_host.sh finds configure_codex.py & co. next to itself, and a lone copy failed every
    # fleet update at codex_install / codex_config (…1324, …1037, …0899 2026-11-10)
    shutil.copytree(scripts, tmp / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    setup = tmp / "scripts" / "setup_host.sh"
    st_rc, st_out = _run(["bash", str(setup), "--pin", pin], 1800)
    shutil.rmtree(tmp, ignore_errors=True)
    after = _engine_sha(engine)
    result = {"pin": pin, "before": before[:12], "after": after[:12], "self_update_rc": su_rc, "setup_rc": st_rc}
    result.update(_setup_diagnostics(st_out))
    ep = cp.current_episode()
    if ep and after and after != before:
        st = cp.status(ep)
        state = str((st["codex"].get("nalu_status") or {}).get("state") or "")
        result["resume_check"] = {"episode": ep, "run": st.get("status"), "state": state}
        if st.get("status") != "RUNNING" and state in RESUMABLE_STATES:
            out = cp.resume(ep, f"引擎已更新到 {after[:7]}（维护者经 fleet 修复），按新版合同从当前阶段继续。")
            result["resumed"] = out.get("status")
    return st_rc == 0, result, {}


AGENT_TASK_FILE = "FLEET_AGENT_TASK.json"


def _short(rc_out: tuple[int, str], lines: int = 3) -> dict:
    rc, out = rc_out
    return {"rc": rc, "tail": [x[:240] for x in out.strip().splitlines()[-lines:]]}


def _cron_jobs() -> list[dict]:
    """name / enabled / model / last status of the OpenClaw scheduled tasks (no prompts, no keys), or []."""
    rc, out = _run(["openclaw", "cron", "list", "--json"], 30)
    if rc != 0:
        return [{"error": f"openclaw cron list rc={rc}", "tail": out.strip()[-200:]}]
    try:
        data = json.loads(out)
    except ValueError:
        return [{"error": "openclaw cron list: not JSON"}]
    jobs = data.get("jobs") if isinstance(data, dict) else data
    rows = []
    for job in jobs if isinstance(jobs, list) else []:
        if not isinstance(job, dict):
            continue
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        state = job.get("state") if isinstance(job.get("state"), dict) else {}
        rows.append({"id": str(job.get("id") or job.get("jobId") or "")[:40], "name": str(job.get("name") or "")[:60],
                     "enabled": job.get("enabled"), "model": payload.get("model") or job.get("model"),
                     "schedule": job.get("schedule") if isinstance(job.get("schedule"), (str, dict)) else None,
                     "last_status": state.get("lastStatus") or state.get("lastRunStatus"),
                     "last_error": str(state.get("lastError") or "")[:200]})
    return rows


def diagnose(cp: Any) -> dict:
    """Scripted, model-free health check for environment / credential blockers (no key is ever read out)."""
    import tempfile  # noqa: PLC0415
    engine, runtime = cp.roots()
    scripts = Path(__file__).resolve().parent
    out: dict[str, Any] = {"engine_sha": _engine_sha(engine)[:12]}
    try:
        out["setup_state"] = {k: v for k, v in json.loads((Path.home() / ".nalu_setup_state.json").read_text())
                              .items() if k in ("status", "failed_step", "pin", "steps", "at")}
    except (OSError, ValueError):
        out["setup_state"] = None
    out["codex_version"] = _short(_run(["codex", "--version"], 20), 1)
    rc, tab = _run(["crontab", "-l"], 10)
    out["system_tick_installed"] = rc == 0 and "nalu-system-tick" in tab
    with tempfile.TemporaryDirectory() as tmp:
        catalog = Path(tmp) / "voices.json"
        out["giggle_voice_catalog"] = _short(_run(["bash", str(scripts / "list_voices.sh"), str(catalog)], 120))
        out["giggle_voice_catalog"]["ok"] = catalog.is_file() and catalog.stat().st_size > 2
    env = {"NALU_ENGINE_ROOT": str(engine), "NALU_RUNTIME_ROOT": str(runtime)}
    out["codex_provider"] = _short(_run(["python3", str(scripts / "configure_codex.py"), "--verify"], 180, env), 1)
    out["cron_jobs"] = _cron_jobs()
    return out


def agent_task(cp: Any, message: str) -> tuple[bool, dict, dict]:
    """Queue a maintainer instruction for the StoryClaw agent (key / config / cron fixes Codex may not do).
    The next agent heartbeat tick hands it over as AGENT / FLEET_AGENT_TASK; the heartbeat is also kicked."""
    from datetime import datetime, timezone  # noqa: PLC0415
    _, runtime = cp.roots()
    path = runtime / "series" / AGENT_TASK_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"message": message, "queued_at": datetime.now(timezone.utc).isoformat(),
                                "delivered": False}, ensure_ascii=False), encoding="utf-8")
    kicked = None
    for job in _cron_jobs():
        name = str(job.get("name") or "")
        if job.get("id") and ("心跳" in name or "heartbeat" in name.lower()):
            kicked = _short(_run(["openclaw", "cron", "run", str(job["id"])], 60), 1) | {"job": name}
            break
    return True, {"status": "QUEUED_FOR_AGENT", "heartbeat_kick": kicked}, {}


def run_command(cp: Any, cmd: dict) -> tuple[bool, dict, dict]:
    """(ok, result, extra tick fields) for one whitelisted command."""
    _, runtime = cp.roots()
    ctype, payload = cmd.get("type"), cmd.get("payload") or {}
    ep = cp.current_episode()
    paused = runtime / "series" / "PAUSED"
    if ctype == "resume":
        if not ep:
            return False, {"error": "NO_EPISODE"}, {}
        out = cp.resume(ep, "（维护者经 fleet 下发）" + str(payload.get("message") or "继续"))
        return out.get("status") == "STARTED", out, {}
    if ctype == "update":
        return scripted_update(cp, str(payload.get("pin") or ""))
    if ctype == "pause":
        paused.parent.mkdir(parents=True, exist_ok=True)
        paused.write_text("paused by fleet superadmin\n", encoding="utf-8")
        return True, {"status": "PAUSED"}, {}
    if ctype == "unpause":
        paused.unlink(missing_ok=True)
        return True, {"status": "UNPAUSED"}, {}
    if ctype == "query":
        return True, {"status": "REPORTED"}, {}
    if ctype == "diagnose":
        return True, diagnose(cp), {}
    if ctype == "agent_task":
        message = str(payload.get("message") or "").strip()
        if not message:
            return False, {"error": "AGENT_TASK_NEEDS_MESSAGE"}, {}
        return agent_task(cp, "（维护者经 fleet 下发）" + message)
    return False, {"error": f"COMMAND_NOT_ALLOWED:{ctype}"}, {}


def sync(cp: Any, tick_result: dict) -> dict:
    """Run queued commands, then report.  Returns extra fields for the tick line (never raises)."""
    extra: dict = {}
    if not _url():
        return extra
    try:
        import device_sn  # noqa: PLC0415
        sn, _source = device_sn.resolve()
        if not sn:
            return {"fleet": "NO_DEVICE_SN"}
        _, runtime = cp.roots()
        token = _token(runtime, sn)
        if not token:
            return {"fleet": "NOT_REGISTERED"}
        code, out = _req("GET", "/v1/commands", token=token)
        if code == 401:
            return {"fleet": "TOKEN_REJECTED"}
        done = []
        for cmd in (out.get("commands") or [])[:5]:
            ok, result, more = run_command(cp, cmd)
            _req("POST", f"/v1/commands/{cmd.get('id')}/ack", {"ok": ok, "result": result}, token=token)
            done.append(f"{cmd.get('type')}:{'ok' if ok else 'fail'}")
            if more.get("action") == "AGENT" and tick_result.get("action") != "AGENT":
                extra.update(more)
        status, blocker, tail = build_status(cp, {**tick_result, **extra})
        status["device_sn"] = sn
        _req("POST", "/v1/report", {"status": status, "blocker": blocker, "status_tail": tail}, token=token)
        extra["fleet"] = "REPORTED" + (f" commands={','.join(done)}" if done else "")
    except Exception as exc:  # noqa: BLE001 -- the channel must never break the heartbeat
        extra["fleet"] = f"ERROR:{type(exc).__name__}"
    return extra
