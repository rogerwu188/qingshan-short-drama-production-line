#!/usr/bin/env python3
"""Wake the OpenClaw agent heartbeat now instead of waiting up to 6 h (line owner 2026-11-28「这么慢？」).

Machines with the system cron (``tick --system`` every 3 min, no model) run the LLM heartbeat only every 6 hours.
Whatever the system tick hands to the agent (``AGENT_PENDING``) or a maintainer queues for it (fleet ``agent_task``)
then sat for hours: device …1205 E17 waited ~6 h before S3, …1101 E28 S1 waited hours for an agent task.

* ``request(key)`` (called by the tick, which holds the tick lock): rate-limit check, then a detached
  ``heartbeat_kick.py run`` child; returns at once.  At most one kick per ``MIN_INTERVAL_S`` (15 min) machine-wide
  and at most ``MAX_PER_KEY`` kicks for the same hand-off, so a hand-off the agent never consumes cannot buy a
  model turn every 15 minutes forever (the regular heartbeat still comes).
* the child waits until the tick lock is free (the heartbeat's own ``tick`` would otherwise answer
  TICK_ALREADY_RUNNING and drop the hand-off), finds the NALU heartbeat job (``openclaw cron list --json``) and runs
  it (``openclaw cron run <id>``: queues a forced run and returns).
* the OpenClaw CLI under cron: ``cron.run`` needs an operator-admin connection, and the CLI run from the crontab
  lacked the gateway credentials the agent's own shell inherits (…1101 2026-11-25..27: ``missing scope:
  operator.read``; every agent_task ack said ``heartbeat_kick: null``).  The CLI therefore runs with the
  ``OPENCLAW_*`` environment of this user's running gateway process (Linux /proc; values are never logged).
* the outcome (ok / error tail, never a secret) is kept in ``~/.nalu_heartbeat_kick.json`` and reported to the
  fleet (``status.heartbeat_kick``), so a broken kick is visible instead of ``null``.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

MIN_INTERVAL_S = 15 * 60
MAX_PER_KEY = 4
LOCK_WAIT_S = 600
#: environment names copied from the running gateway (credentials / state dir / profile); values never printed
GATEWAY_ENV_PREFIXES = ("OPENCLAW_", "CLAWDBOT_")
GATEWAY_ENV_NAMES = ("XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME")


def state_path() -> Path:
    return Path.home() / ".nalu_heartbeat_kick.json"


def load_state() -> dict[str, Any]:
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(data: dict[str, Any]) -> None:
    try:
        tmp = state_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(state_path())
    except OSError:
        pass


def _unit_env() -> dict[str, str]:
    """OPENCLAW_* ``Environment=`` lines of the user's systemd gateway unit (the gateway's environment when /proc
    shows none), {} otherwise."""
    env: dict[str, str] = {}
    for unit in sorted((Path.home() / ".config" / "systemd" / "user").glob("openclaw-gateway*.service")):
        try:
            lines = unit.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip().startswith("Environment="):
                continue
            for item in line.split("=", 1)[1].strip().split():
                name, sep, value = item.strip('"').partition("=")
                if sep and name.startswith(GATEWAY_ENV_PREFIXES):
                    env[name] = value.strip('"')
        if env:
            break
    return env


def gateway_env() -> dict[str, str]:
    """OPENCLAW_* (and XDG_*) variables of this user's running OpenClaw gateway, {} when none is found."""
    env = _proc_env()
    return env if any(k.startswith(GATEWAY_ENV_PREFIXES) for k in env) else {**env, **_unit_env()}


def _proc_env() -> dict[str, str]:
    proc = Path("/proc")
    if not proc.is_dir():
        return {}
    uid = os.getuid()
    me = os.getpid()
    for pid_dir in proc.iterdir():
        if not pid_dir.name.isdigit() or int(pid_dir.name) == me:
            continue
        try:
            if pid_dir.stat().st_uid != uid:
                continue
            cmd = (pid_dir / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="ignore")
            if "openclaw" not in cmd or "gateway" not in cmd:
                continue
            raw = (pid_dir / "environ").read_bytes().split(b"\0")
        except OSError:
            continue
        env: dict[str, str] = {}
        for item in raw:
            name, sep, value = item.decode(errors="ignore").partition("=")
            if sep and (name.startswith(GATEWAY_ENV_PREFIXES) or name in GATEWAY_ENV_NAMES):
                env[name] = value
        if env:
            return env
    return {}


def _run_full(argv: list[str], timeout: int, extra_env: dict | None = None) -> tuple[int, str]:
    import fleet_sync  # noqa: PLC0415 -- same tool directories / newest node as every other fleet command
    return fleet_sync._run_full(argv, timeout, extra_env)


def openclaw(args: list[str], timeout: int = 60) -> tuple[int, str]:
    """``openclaw <args>`` with the gateway's environment (rc, stdout+stderr tail are what callers see)."""
    return _run_full(["openclaw", *args], timeout, gateway_env())


def _tail(out: str, n: int = 200) -> str:
    return " ".join(out.strip().split())[-n:]


def find_job() -> tuple[dict[str, Any] | None, str]:
    import fleet_sync  # noqa: PLC0415
    jobs = fleet_sync._cron_jobs()
    errors = [j for j in jobs if j.get("error")]
    for job in jobs:
        name = str(job.get("name") or "")
        if job.get("id") and ("心跳" in name or "heartbeat" in name.lower()) and job.get("enabled") is not False:
            return job, ""
    if errors:
        return None, f"{errors[0].get('error')}: {_tail(str(errors[0].get('tail') or ''))}"
    return None, "NO_HEARTBEAT_JOB"


def kick_now(key: str = "", reason: str = "") -> dict[str, Any]:
    """Find and run the heartbeat job now (no rate limit; ``request`` does that).  Records the outcome."""
    job, err = find_job()
    out: dict[str, Any] = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "key": key, "reason": reason}
    if job is None:
        out.update(ok=False, error=err)
    else:
        rc, text = openclaw(["cron", "run", str(job["id"])], 60)
        ok = rc == 0 and not re.search(r'"ok"\s*:\s*false', text)
        out.update(ok=ok, job=job.get("name"), rc=rc)
        if not ok:
            out["error"] = _tail(text)
    data = load_state()
    data["last_result"] = out
    save_state(data)
    return out


def _allowed(data: dict[str, Any], key: str, now: float) -> str:
    """'' when a kick for ``key`` may go now, else why not."""
    last = float(data.get("last_at") or 0)
    if now - last < MIN_INTERVAL_S:
        return f"RATE_LIMITED:{int(MIN_INTERVAL_S - (now - last))}s"
    if int((data.get("counts") or {}).get(key) or 0) >= MAX_PER_KEY:
        return f"MAX_KICKS_FOR_HAND_OFF:{MAX_PER_KEY}"
    return ""


def request(key: str, reason: str = "", *, lock: Path | None = None, now: float | None = None,
            spawn: bool = True) -> dict[str, Any]:
    """Schedule one kick for the hand-off ``key`` (rate-limited); never raises, never waits."""
    try:
        now = time.time() if now is None else now
        data = load_state()
        why = _allowed(data, key, now)
        if why:
            return {"status": "SKIPPED", "why": why, "last": data.get("last_result")}
        counts = dict(data.get("counts") or {})
        if len(counts) > 50:  # old hand-offs: keep the file small
            counts = {key: counts.get(key, 0)}
        counts[key] = int(counts.get(key) or 0) + 1
        data.update(last_at=now, counts=counts)
        save_state(data)
        if not spawn:
            return {"status": "SCHEDULED", "key": key}
        argv = [sys.executable if Path(sys.executable).name.startswith("python") else "python3",
                str(Path(__file__).resolve()), "run", "--key", key, "--reason", reason]
        if lock is not None:
            argv += ["--lock", str(lock)]
        log = Path.home() / ".nalu_heartbeat_kick.log"
        with open(log, "a", encoding="utf-8") as fh:
            subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=fh, stderr=fh, start_new_session=True,
                             cwd=str(Path(__file__).resolve().parent))
        return {"status": "SCHEDULED", "key": key, "kick_number": counts[key]}
    except Exception as exc:  # noqa: BLE001 -- waking the agent is best effort; the tick never breaks on it
        return {"status": "ERROR", "error": type(exc).__name__}


def wait_for_lock(lock: Path | None, timeout_s: float = LOCK_WAIT_S) -> bool:
    """Block until the tick lock is free (then release it at once), up to ``timeout_s``."""
    if lock is None or not lock.parent.is_dir():
        return True
    import fcntl  # noqa: PLC0415
    deadline = time.time() + timeout_s
    with open(lock, "a") as fh:  # noqa: SIM115
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(fh, fcntl.LOCK_UN)
                return True
            except OSError:
                if time.time() > deadline:
                    return False
                time.sleep(2)


def report() -> dict[str, Any] | None:
    """The last kick's outcome for the fleet status (no secrets), or None."""
    last = load_state().get("last_result")
    if not isinstance(last, dict):
        return None
    return {k: last.get(k) for k in ("at", "ok", "job", "reason", "error") if last.get(k) is not None}


def main() -> int:
    import argparse  # noqa: PLC0415
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--key", default="")
    r.add_argument("--reason", default="")
    r.add_argument("--lock", default="")
    sub.add_parser("now")
    a = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    if a.cmd == "run":
        wait_for_lock(Path(a.lock) if a.lock else None)
        out = kick_now(a.key, a.reason)
    else:
        out = kick_now("manual", "manual")
    print("HEARTBEAT_KICK: " + json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
