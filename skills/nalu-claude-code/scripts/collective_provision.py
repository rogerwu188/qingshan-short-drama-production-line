#!/usr/bin/env python3
"""Fleet-provisioned collective learning on one device (audit 2026-11-12 §4: nothing provisioned devices).

Called from the 3-minute system tick through ``fleet_sync.sync`` (never from a production stage):

* ``provision``  at most every PROVISION_INTERVAL_S: GET /v1/collective/provision from the fleet service.
  Enabled -> write, only when the bytes changed:
      <reports>/COLLECTIVE_LEARNING_CONFIG.json     (the file runtime_wiring / line_upgrade_gate read)
      <reports>/collective/trust.json               (pinned publisher keys)
      <reports>/collective/s3.env                   (AWS_* + S3CTL_* lines, mode 0600, s3_sync.load_env_file format)
      <reports>/collective/bundle_cache/            (verified bundle cache)
  Disabled / 404 / unreachable / malformed -> touch nothing.
* ``sync_tick``  at most every SYNC_INTERVAL_S: start ``s3_sync.py device-sync`` DETACHED (the tick never waits),
  skipped while the previous run still holds ``collective_logs/device-sync.lock``.  The detached runner kills the
  child after SYNC_TIMEOUT_S and writes ``collective_logs/device-sync.last.json`` (status + counts, no secrets).
  This replaces the macOS-only ``install-device-agent`` (launchd) on the Linux fleet.

Devices never publish: device-sync only uploads the outbox to the inbox and downloads signed packs.  Secret values
are never printed, logged, returned or written anywhere but the 0600 env file.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

PROVISION_INTERVAL_S = 1800
SYNC_INTERVAL_S = 900
SYNC_TIMEOUT_S = 600
CONFIG_NAME = "COLLECTIVE_LEARNING_CONFIG.json"
SUBDIR = "collective"
LOCAL_PATHS = {"trust_store": f"{SUBDIR}/trust.json", "cache_dir": f"{SUBDIR}/bundle_cache",
               "env_file": f"{SUBDIR}/s3.env", "revocations": f"{SUBDIR}/revocations.signed.json"}
STATE_NAME = ".collective_provision.json"
LOG_DIR = "collective_logs"
SECRET_NAMES = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
NONSECRET_ENV = (("endpoint_url", "S3CTL_ENDPOINT_URL"), ("bucket", "S3CTL_BUCKET"),
                 ("public_base_url", "S3CTL_PUBLIC_BASE_URL"))
CHANNELS = ("CANARY", "RELEASED")
TRUST_SCHEMA = "qingshan.collective.trust_store.v1"
REQUIRED_CONFIG = ("tenant_id", "line_id", "engine_api_version", "object_store")


def _now_iso(epoch: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if epoch is None else epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reports_dir(runtime: Path) -> Path:
    """``<runtime>/runtime/reports`` (the same rule knowledge_status / line_upgrade_gate use)."""
    rt = Path(runtime) / "runtime"
    return rt / "runtime" / "reports" if (rt / "runtime").is_dir() else rt / "reports"


def state_path(runtime: Path) -> Path:
    return Path(runtime) / "series" / STATE_NAME


def read_state(runtime: Path) -> dict[str, Any]:
    try:
        data = json.loads(state_path(runtime).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(runtime: Path, state: dict[str, Any]) -> None:
    path = state_path(runtime)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_if_changed(path: Path, data: bytes, *, mode: int | None = None) -> bool:
    """Atomic write only when the bytes differ; ``mode`` is enforced either way (0600 for the env file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        same = path.read_bytes() == data
    except OSError:
        same = False
    if not same:
        tmp = path.with_name(f".{path.name}.tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode if mode is not None else 0o644)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    if mode is not None and (path.stat().st_mode & 0o777) != mode:
        os.chmod(path, mode)
    return not same


def _json_bytes(doc: Any) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def _validate(body: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    config, trust, creds = body.get("config"), body.get("trust"), body.get("credentials")
    if not isinstance(config, dict):
        return ["CONFIG_NOT_OBJECT"]
    problems += [f"CONFIG_MISSING:{k}" for k in REQUIRED_CONFIG if not config.get(k)]
    store = config.get("object_store") if isinstance(config.get("object_store"), dict) else {}
    if not store.get("endpoint_url") or not store.get("bucket"):
        problems.append("OBJECT_STORE_ENDPOINT_OR_BUCKET_MISSING")
    if any(k.lower() in ("access_key", "secret_key", "aws_access_key_id", "aws_secret_access_key") for k in store):
        problems.append("OBJECT_STORE_CARRIES_CREDENTIALS")
    if not isinstance(trust, dict) or trust.get("schema") != TRUST_SCHEMA or not isinstance(trust.get("publishers"), dict) \
            or not trust.get("publishers"):
        problems.append("TRUST_INVALID")
    if not isinstance(creds, dict):
        problems.append("CREDENTIALS_NOT_OBJECT")
    else:
        for name in SECRET_NAMES:
            value = creds.get(name)
            if not isinstance(value, str) or not value.strip() or any(ch in value for ch in "\r\n\0=\"'"):
                problems.append(f"CREDENTIAL_INVALID:{name}")
    channel = body.get("channel") or config.get("channel") or "RELEASED"
    if channel not in CHANNELS:
        problems.append(f"CHANNEL_INVALID:{channel}")
    device_id = body.get("device_id") or config.get("device_id")
    if device_id is not None and (not isinstance(device_id, str) or not device_id or len(device_id) > 120):
        problems.append("DEVICE_ID_INVALID")
    return problems


def build_files(body: dict[str, Any]) -> dict[str, bytes]:
    """The three files' bytes from a validated provision response (relative to the reports dir)."""
    config = dict(body["config"])
    config.update(LOCAL_PATHS)
    config["sync"] = {**(config.get("sync") if isinstance(config.get("sync"), dict) else {}), "mode": "s3"}
    config["device_store"] = True
    config.setdefault("batch_id", "B1")
    config["channel"] = body.get("channel") or config.get("channel") or "RELEASED"
    if body.get("device_id"):
        config["device_id"] = body["device_id"]
    config.setdefault("capabilities", {})
    config["provisioned_by"] = "nalu-fleet"
    store = config["object_store"]
    env_lines = [f"{name}={body['credentials'][name].strip()}" for name in SECRET_NAMES]
    env_lines += [f"{var}={store[key]}" for key, var in NONSECRET_ENV if store.get(key)]
    return {CONFIG_NAME: _json_bytes(config), LOCAL_PATHS["trust_store"]: _json_bytes(body["trust"]),
            LOCAL_PATHS["env_file"]: ("\n".join(env_lines) + "\n").encode("utf-8")}


def provision(runtime: Path, fetch: Callable[[], tuple[int, dict[str, Any]]], *, now: float | None = None,
              force: bool = False, interval_s: int = PROVISION_INTERVAL_S) -> dict[str, Any]:
    """Rate-limited, idempotent provisioning.  Returns names and statuses only (never a secret value)."""
    now = time.time() if now is None else now
    state = read_state(runtime)
    if not force and now - float(state.get("last_fetch_epoch") or 0) < interval_s:
        return {"status": "RATE_LIMITED", "enabled": state.get("enabled")}
    state["last_fetch_epoch"] = now
    state["last_fetch_at"] = _now_iso(now)
    try:
        code, body = fetch()
    except Exception as exc:  # noqa: BLE001 -- the fleet being away changes nothing on the device
        state["last_result"] = f"UNREACHABLE:{type(exc).__name__}"
        _write_state(runtime, state)
        return {"status": "UNREACHABLE"}
    if code == 404 or (code == 200 and isinstance(body, dict) and body.get("enabled") is False):
        state.update({"last_result": "DISABLED", "server_enabled": False})
        _write_state(runtime, state)
        return {"status": "DISABLED", "enabled": state.get("enabled")}
    if code != 200 or not isinstance(body, dict) or body.get("enabled") is not True:
        state["last_result"] = f"HTTP_{code}"
        _write_state(runtime, state)
        return {"status": f"HTTP_{code}"}
    problems = _validate(body)
    if problems:
        state["last_result"] = "INVALID"
        _write_state(runtime, state)
        return {"status": "INVALID", "problems": problems[:8]}
    reports = reports_dir(runtime)
    changed = []
    for rel, data in build_files(body).items():
        secret = rel == LOCAL_PATHS["env_file"]
        if secret:
            (reports / SUBDIR).mkdir(parents=True, exist_ok=True)
            os.chmod(reports / SUBDIR, 0o700)
        if _write_if_changed(reports / rel, data, mode=0o600 if secret else None):
            changed.append(rel)
    (reports / LOCAL_PATHS["cache_dir"]).mkdir(parents=True, exist_ok=True)
    channel = body.get("channel") or body["config"].get("channel") or "RELEASED"
    state.update({"enabled": True, "server_enabled": True, "last_result": "OK", "channel": channel,
                  "device_id": body.get("device_id"), "tenant_id": body["config"].get("tenant_id"),
                  "config_sha256": hashlib.sha256((reports / CONFIG_NAME).read_bytes()).hexdigest()})
    if changed:
        state["last_change_at"] = _now_iso(now)
        state["last_changed"] = changed
    _write_state(runtime, state)
    return {"status": "PROVISIONED" if changed else "UNCHANGED", "changed": changed, "channel": channel}


# --------------------------------------------------------------------------- device-sync (detached)
def _lock_path(runtime: Path) -> Path:
    return reports_dir(runtime) / LOG_DIR / "device-sync.lock"


@contextlib.contextmanager
def _try_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a")  # noqa: SIM115
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def sync_running(runtime: Path) -> bool:
    with _try_lock(_lock_path(runtime)) as got:
        return not got


def venv_python(engine: Path) -> str:
    for candidate in (os.environ.get("NALU_VENV_PYTHON"), str(Path(engine) / ".qingshan-venv" / "bin" / "python")):
        if candidate and Path(candidate).is_file():
            return candidate
    return sys.executable


def sync_tick(runtime: Path, engine: Path, *, now: float | None = None, interval_s: int = SYNC_INTERVAL_S,
              spawn: Callable[[list[str], Path], Any] | None = None) -> dict[str, Any]:
    """Start one detached device-sync when due.  Never waits for it."""
    now = time.time() if now is None else now
    config = reports_dir(runtime) / CONFIG_NAME
    try:
        doc = json.loads(config.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "NOT_CONFIGURED"}
    if str(((doc.get("sync") or {}) if isinstance(doc.get("sync"), dict) else {}).get("mode") or "") != "s3":
        return {"status": "NOT_S3_MODE"}
    state = read_state(runtime)
    if now - float(state.get("sync_last_started_epoch") or 0) < interval_s:
        return {"status": "RATE_LIMITED"}
    if sync_running(runtime):
        return {"status": "SYNC_RUNNING"}
    log_dir = reports_dir(runtime) / LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    argv = [sys.executable, str(Path(__file__).resolve()), "device-sync-run", "--runtime-root", str(runtime),
            "--engine-root", str(engine)]
    (spawn or _spawn_detached)(argv, log_dir / "device-sync.runner.log")
    state["sync_last_started_epoch"] = now
    state["sync_last_started_at"] = _now_iso(now)
    _write_state(runtime, state)
    return {"status": "STARTED"}


def _spawn_detached(argv: list[str], log: Path) -> None:
    with open(log, "a") as out:
        subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,  # noqa: S603
                         start_new_session=True, close_fds=True)


def _summarise(result: dict[str, Any]) -> dict[str, Any]:
    push = result.get("push") if isinstance(result.get("push"), dict) else {}
    pulls = result.get("pull") if isinstance(result.get("pull"), list) else []
    return {"push": {k: push.get(k) for k in ("delivered", "in_flight", "quarantined", "retry") if k in push},
            "pull": [{"channel": p.get("channel"), "status": p.get("status"), "sequence": p.get("sequence"),
                      "fetched": sum(1 for f in p.get("fetched") or [] if f.get("status") == "FETCHED"),
                      "problems": sorted({f.get("status") for f in p.get("fetched") or []
                                          if f.get("status") != "FETCHED"})}
                     for p in pulls if isinstance(p, dict)],
            "cache_entries": sorted(f"{e.get('bundle_id')}@{e.get('version')}:{e.get('release_channel')}"
                                    for e in result.get("cache_entries") or [] if isinstance(e, dict))[:20],
            "device_id": result.get("device_id")}


def run_device_sync(runtime: Path, engine: Path, *, timeout_s: int = SYNC_TIMEOUT_S,
                    argv: list[str] | None = None) -> dict[str, Any]:
    """The detached runner: lock, run s3_sync device-sync with a timeout, write last.json."""
    reports = reports_dir(runtime)
    with _try_lock(_lock_path(runtime)) as got:
        if not got:
            return {"status": "SYNC_RUNNING"}
        argv = argv or [venv_python(engine), str(Path(engine) / "tools" / "collective_learning" / "s3_sync.py"),
                        "device-sync", "--config", str(reports / CONFIG_NAME)]
        started = time.time()
        out: dict[str, Any] = {"schema": "nalu.collective_device_sync.v1", "started_at": _now_iso(started)}
        try:
            done = subprocess.run(argv, cwd=str(engine), capture_output=True, text=True, timeout=timeout_s)  # noqa: S603
            rc, stdout = done.returncode, done.stdout or ""
            try:
                result = json.loads(stdout)
            except ValueError:
                result = {}
            out.update({"rc": rc, "status": result.get("status") or ("ERROR" if rc else "UNPARSEABLE")})
            if result.get("status") == "OK":
                out.update(_summarise(result))
            else:
                out["error_code"] = str(result.get("code") or "")[:80]
                out["error"] = str(result.get("error") or (done.stderr or "")[-300:])[:300]
        except subprocess.TimeoutExpired:
            out.update({"rc": None, "status": "TIMEOUT", "timeout_s": timeout_s})
        except OSError as exc:
            out.update({"rc": None, "status": "ERROR", "error": f"{type(exc).__name__}"})
        out["finished_at"] = _now_iso()
        out["duration_s"] = round(time.time() - started, 1)
        log_dir = reports / LOG_DIR
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "device-sync.last.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n",
                                                       encoding="utf-8")
        with open(log_dir / "device-sync.log", "a", encoding="utf-8") as log:
            log.write(json.dumps({k: out.get(k) for k in ("finished_at", "status", "rc", "duration_s", "push")},
                                 ensure_ascii=False) + "\n")
        if out.get("status") == "OK":
            state = read_state(runtime)
            state.update({"sync_last_ok_at": out["finished_at"]})
            _write_state(runtime, state)
        return out


# --------------------------------------------------------------------------- tick entry + report
def tick(runtime: Path, engine: Path, fetch: Callable[[], tuple[int, dict[str, Any]]], *,
         now: float | None = None) -> dict[str, Any]:
    """Both steps, best-effort; returns a short tick-line summary."""
    out: dict[str, Any] = {}
    try:
        out["provision"] = provision(runtime, fetch, now=now).get("status")
    except Exception as exc:  # noqa: BLE001
        out["provision"] = f"ERROR:{type(exc).__name__}"
    try:
        out["sync"] = sync_tick(runtime, engine, now=now).get("status")
    except Exception as exc:  # noqa: BLE001
        out["sync"] = f"ERROR:{type(exc).__name__}"
    return out


def report(runtime: Path) -> dict[str, Any]:
    """Compact status for the fleet report (no secrets, no paths)."""
    state = read_state(runtime)
    reports = reports_dir(runtime)
    try:
        last = json.loads((reports / LOG_DIR / "device-sync.last.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        last = {}
    try:
        config = json.loads((reports / CONFIG_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        config = {}
    return {"provisioned": bool(state.get("enabled")) and bool(config),
            "configured": bool(config), "channel": config.get("channel"),
            "last_sync_at": last.get("finished_at"), "last_sync_status": last.get("status"),
            "last_sync_ok_at": state.get("sync_last_ok_at"),
            "pack": sorted({e.split(":")[0] for e in last.get("cache_entries") or []})[-3:]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("device-sync-run", help="(detached) one locked, time-limited device-sync")
    run.add_argument("--runtime-root", type=Path, required=True)
    run.add_argument("--engine-root", type=Path, required=True)
    run.add_argument("--timeout", type=int, default=SYNC_TIMEOUT_S)
    st = sub.add_parser("status", help="provisioning + last device-sync (no secrets)")
    st.add_argument("--runtime-root", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "device-sync-run":
        out = run_device_sync(a.runtime_root, a.engine_root, timeout_s=a.timeout)
        print(json.dumps({k: out.get(k) for k in ("status", "rc", "duration_s")}))
        return 0 if out.get("status") == "OK" else 1
    print(json.dumps(report(a.runtime_root), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
