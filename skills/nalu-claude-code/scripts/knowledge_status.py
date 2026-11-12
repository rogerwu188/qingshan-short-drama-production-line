#!/usr/bin/env python3
"""On-device knowledge-base status for fleet diagnose: model-free, read-only, never prints a secret.

Answers "is the cloud shared knowledge base (collective learning) actually doing anything on this
device?" from files alone (see docs/collective_learning/DEPLOYMENT_OPERATIONS.md for the design):

  provisioning  fleet-provisioned config + the fleet tick's detached device-sync (collective_provision.py):
                provisioning state, last device-sync time/result, channel (CANARY/RELEASED), cached pack.
  local KB      configs/ENGINEERING_KNOWLEDGE_V1.json (static, shipped with the engine) and the
                per-episode <EP>_KNOWLEDGE_BRIEFING.json written by S1 (line_upgrade_gate preflight).
  collective    opt-in per line by <reports>/COLLECTIVE_LEARNING_CONFIG.json; without it every hook in
                tools/collective_learning/runtime_wiring.py returns None (silent no-op).  With it:
                device store (outbox) -> s3_sync.py device-sync (separate agent) -> bucket inbox;
                bucket channels/<CH>.json -> verified bundle_cache -> S1 run lock -> rules applied to
                the provider prompt contracts (APPLIED adoption receipts beside the lock).

Output: line 1 = full JSON report; line 2 = compact summary (<= 240 chars) that fleet_sync.diagnose()
keeps (it stores only the last stdout line).  ``--full`` prints only the full report, indented.

Network: one or two anonymous GETs of public, signed pointer files (trust.json / channels/RELEASED.json)
under the line's public base URL -- no credentials, no writes.  Skipped with --no-network or
NALU_FLEET_URL=off.  Credentials are reported as booleans only; endpoints as host names only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

SCHEMA = "nalu.knowledge_status.v1"
CONFIG_NAME = "COLLECTIVE_LEARNING_CONFIG.json"
STORE_NAME = "COLLECTIVE_DEVICE_STORE.sqlite"
REGISTRY = "configs/ENGINEERING_KNOWLEDGE_V1.json"
FAILURE_MEMORY = "knowledge/failure_memory.jsonl"
CONFIG_KEYS = ("tenant_id", "line_id", "trust_store", "cache_dir", "channel", "engine_api_version",
               "capabilities", "batch_id", "device_store", "revocations", "baseline", "sync", "object_store",
               "env_file")
CRED_NAMES = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
NONSECRET_ENV = ("S3CTL_ENDPOINT_URL", "S3CTL_BUCKET", "S3CTL_PUBLIC_BASE_URL", "AWS_ENDPOINT_URL",
                 "COLLECTIVE_OBJECT_BUCKET", "COLLECTIVE_OBJECT_PUBLIC_BASE_URL", "AWS_PROFILE")
# DEPLOYMENT_OPERATIONS.md §3a: the line owner's bucket (public-read); used only for the anonymous
# reachability probe when this device has no config of its own.
DEFAULT_PUBLIC_BASE = "https://v.arkfs.co/drama01"
DEFAULT_TENANT = "nalu"
HTTP_TIMEOUT_S = 8


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _iso_mtime(path: Path) -> str | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(microsecond=0).isoformat()
    except OSError:
        return None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _host(url: Any) -> str | None:
    try:
        return urlparse(str(url)).hostname if url else None
    except ValueError:
        return None


def env_file_names(path: Path) -> set[str]:
    """Names (never values) of the non-empty KEY=VALUE lines in an env file."""
    names: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return names
    for line in text.splitlines():
        m = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)
        if m and m.group(2).strip().strip("'\""):
            names.add(m.group(1))
    return names


def reports_dir(runtime: Path) -> Path:
    """Same rule as line_upgrade_gate._reports applied to the pipeline's RT = <runtime>/runtime."""
    rt = runtime / "runtime"
    if (rt / "runtime").is_dir():
        return rt / "runtime" / "reports"
    return rt / "reports"


def current_episode(runtime: Path) -> str | None:
    try:
        ep = (runtime / "series" / "CURRENT_EPISODE").read_text(encoding="utf-8").strip()
        if ep:
            return ep
    except OSError:
        pass
    states = sorted((runtime / "runtime" / "pipeline_state").glob("*.json"), key=lambda p: p.stat().st_mtime)
    return states[-1].stem if states else None


# --------------------------------------------------------------------------- local (static) KB
def local_kb(engine: Path, reports: Path, episode: str | None) -> dict[str, Any]:
    data = _read_json(engine / REGISTRY)
    rules = data.get("rules") if isinstance(data, dict) else None
    try:
        fm_rows = sum(1 for x in (engine / FAILURE_MEMORY).read_text(encoding="utf-8").splitlines() if x.strip())
    except OSError:
        fm_rows = None
    dirty = None
    try:
        proc = subprocess.run(["git", "-C", str(engine), "status", "--porcelain", "--", REGISTRY, FAILURE_MEMORY],
                              capture_output=True, text=True, timeout=20)
        if proc.returncode == 0:
            dirty = bool(proc.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    out: dict[str, Any] = {
        "registry_present": isinstance(rules, list), "registry_rules": len(rules) if isinstance(rules, list) else 0,
        "failure_memory_rows": fm_rows,
        # S8 knowledge_sync appends rows to these tracked files; they never leave the device and the next
        # setup_host --pin stashes them (local-only learning).
        "registry_locally_modified": dirty,
    }
    if episode:
        brief = reports / f"{episode}_KNOWLEDGE_BRIEFING.json"
        doc = _read_json(brief)
        out["briefing"] = {"episode": episode, "present": brief.is_file(), "at": _iso_mtime(brief),
                           "rules": len(doc.get("rules") or []) if isinstance(doc, dict) else 0}
    return out


# --------------------------------------------------------------------------- collective store / cache
def store_stats(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"present": False}
    out: dict[str, Any] = {"present": True}
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    except sqlite3.Error as exc:
        return {"present": True, "error": type(exc).__name__}
    try:
        def one(sql: str) -> Any:
            row = db.execute(sql).fetchone()
            return row[0] if row else None
        meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
        out["device_id_present"] = bool(meta.get("device_id"))
        out["events"] = one("SELECT COUNT(*) FROM events")
        out["newest_event_at"] = one("SELECT MAX(recorded_at) FROM events")
        out["receipts"] = dict(db.execute("SELECT kind, COUNT(*) FROM receipts GROUP BY kind").fetchall())
        out["newest_receipt_at"] = one("SELECT MAX(recorded_at) FROM receipts")
        out["outbox"] = dict(db.execute("SELECT state, COUNT(*) FROM outbox GROUP BY state").fetchall())
        out["last_delivered_at"] = one("SELECT MAX(delivered_at) FROM outbox")
        out["outbox_last_error_present"] = bool(one("SELECT COUNT(*) FROM outbox WHERE last_error IS NOT NULL "
                                                    "AND last_error != ''"))
    except sqlite3.Error as exc:
        out["error"] = f"{type(exc).__name__}:{str(exc)[:80]}"
    finally:
        db.close()
    return out


def cache_stats(cache_dir: Path) -> dict[str, Any]:
    index = _read_json(cache_dir / "index.json")
    entries = index.get("entries") if isinstance(index, dict) else None
    if not isinstance(entries, list):
        return {"present": cache_dir.is_dir(), "entries": 0}
    stamps = [str(e.get("admitted_at")) for e in entries if isinstance(e, dict) and e.get("admitted_at")]
    return {"present": True, "entries": len(entries),
            "bundles": sorted({f"{e.get('bundle_id')}@{e.get('version')}" for e in entries if isinstance(e, dict)})[:10],
            "newest_admitted_at": max(stamps) if stamps else None,
            "from_s3": sum(1 for e in entries if isinstance(e, dict) and str(e.get("source", "")).startswith("s3:"))}


def _mentions_device_sync(path: Path) -> bool:
    try:
        return "device-sync" in path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False


def provisioning(runtime: Path) -> dict[str, Any]:
    """Fleet provisioning state (collective_provision.py, series/.collective_provision.json): no secrets in it."""
    state = _read_json(runtime / "series" / ".collective_provision.json")
    if not isinstance(state, dict):
        return {"state_present": False, "provisioned": False}
    return {"state_present": True, "provisioned": bool(state.get("enabled")),
            "server_enabled": state.get("server_enabled"), "last_result": state.get("last_result"),
            "last_fetch_at": state.get("last_fetch_at"), "last_change_at": state.get("last_change_at"),
            "channel": state.get("channel"), "device_id_set": bool(state.get("device_id")),
            "sync_last_started_at": state.get("sync_last_started_at"), "sync_last_ok_at": state.get("sync_last_ok_at")}


def last_device_sync(reports: Path) -> dict[str, Any]:
    """The fleet tick's detached device-sync result (collective_logs/device-sync.last.json)."""
    last = _read_json(reports / "collective_logs" / "device-sync.last.json")
    if not isinstance(last, dict):
        return {"present": False}
    return {"present": True, "status": last.get("status"), "at": last.get("finished_at"), "rc": last.get("rc"),
            "duration_s": last.get("duration_s"), "push": last.get("push"),
            "error_code": last.get("error_code") or None,
            "pulled": [{k: p.get(k) for k in ("channel", "status", "sequence", "fetched")}
                       for p in last.get("pull") or [] if isinstance(p, dict)],
            "cache_entries": last.get("cache_entries") or []}


def cached_pack(cache: dict[str, Any]) -> str | None:
    """Newest ``bundle@version`` in the verified cache."""
    best: tuple[int, str] | None = None
    for name in cache.get("bundles") or []:
        bundle, _, version = str(name).rpartition("@")
        try:
            key = (int(version), name)
        except ValueError:
            continue
        if best is None or key > best:
            best = key
    return best[1] if best else None


def sync_agent(reports: Path) -> dict[str, Any]:
    """Is anything scheduled to run ``s3_sync.py device-sync``?  The fleet tick (collective_provision.py) on
    the Linux fleet, or a launchd agent / crontab line on hand-built machines."""
    out: dict[str, Any] = {"launchd_plist": False, "crontab": False,
                           "fleet_tick": (reports / "collective_logs" / "device-sync.last.json").is_file()
                           or (reports / "collective_logs" / "device-sync.runner.log").is_file()}
    agents = Path.home() / "Library" / "LaunchAgents"
    if agents.is_dir():
        out["launchd_plist"] = any(_mentions_device_sync(p) for p in agents.glob("*.plist"))
    try:
        proc = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=10)
        out["crontab"] = proc.returncode == 0 and "device-sync" in proc.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    logs = reports / "collective_logs"
    out["last_sync_log_at"] = max(filter(None, (_iso_mtime(p) for p in logs.glob("device-sync*.log"))), default=None)
    return out


def credentials(config: dict[str, Any], base: Path, engine: Path) -> dict[str, Any]:
    """Which credential / endpoint names are resolvable (booleans only, never values)."""
    sources: dict[str, set[str]] = {"process_env": {k for k in (*CRED_NAMES, *NONSECRET_ENV) if os.environ.get(k)}}
    env_file = config.get("env_file")
    if env_file:
        p = Path(str(env_file)).expanduser()
        p = p if p.is_absolute() else base / p
        sources["config_env_file"] = env_file_names(p)
    for label, p in (("engine_dotenv", engine / ".env"), ("home_nalu_dotenv", Path.home() / "nalu" / ".env")):
        if p.is_file():
            sources[label] = env_file_names(p)
    names = set().union(*sources.values())
    profile = (config.get("object_store") or {}).get("profile") if isinstance(config.get("object_store"), dict) else None
    aws_creds = Path.home() / ".aws" / "credentials"
    profile_found = bool(profile) and aws_creds.is_file() and f"[{profile}]" in aws_creds.read_text(errors="ignore")
    return {"present": {k: k in names for k in (*CRED_NAMES, *NONSECRET_ENV)},
            "sources_with_any": sorted(k for k, v in sources.items() if v & set(CRED_NAMES)),
            "aws_profile_configured": bool(profile), "aws_profile_found": profile_found,
            "resolvable": all(k in names for k in CRED_NAMES) or profile_found}


# --------------------------------------------------------------------------- this episode's run
def episode_run(runtime: Path, reports: Path, episode: str | None) -> dict[str, Any]:
    if not episode:
        return {"episode": None}
    state = _read_json(runtime / "runtime" / "pipeline_state" / f"{episode}.json") or {}
    pre = (state.get("line_upgrade_preflight") or {}) if isinstance(state, dict) else {}
    collective = pre.get("collective") or {}
    out: dict[str, Any] = {"episode": episode, "preflight_recorded": bool(pre),
                           "preflight_knowledge_status": (pre.get("knowledge") or {}).get("status")
                           if isinstance(pre.get("knowledge"), dict) else None,
                           "collective_status": collective.get("status") or ("NOT_RUN" if pre else None),
                           "lock_bundles": len(collective.get("bundles") or []),
                           "lock_rejected": len(collective.get("rejected") or [])}
    locks = sorted((reports / "knowledge_locks").glob(f"*.{episode}.*.knowledge_lock.json"))
    out["lock_files"] = len(locks)
    counts: dict[str, int] = {}
    provider_applied = 0
    for lock in locks:
        sidecar = lock.with_suffix(".adoption.jsonl")
        try:
            lines = sidecar.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            st = str(row.get("state") or "?")
            counts[st] = counts.get(st, 0) + 1
            if st == "APPLIED" and row.get("evidence_scope") == "PROVIDER_REQUEST":
                provider_applied += 1
    out["adoption"] = counts
    out["provider_request_applied"] = provider_applied
    # Injection target: provider (H3/SD2) prompt contracts -- not Codex prompts.  APPLIED receipts are the
    # only proof a cloud rule changed a prompt; there is no marker string in the prompt text itself.
    out["kb_injected_in_provider_prompts"] = counts.get("APPLIED", 0) > 0
    brief = runtime / "briefs" / f"{episode}_DISPATCH.md"
    try:
        text = brief.read_text(encoding="utf-8")
        out["codex_dispatch_mentions_briefing"] = "KNOWLEDGE_BRIEFING" in text
    except OSError:
        out["codex_dispatch_mentions_briefing"] = None
    return out


# --------------------------------------------------------------------------- reachability
def probe(url: str) -> int | str:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "nalu-knowledge-status/1"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:  # noqa: S310 -- fixed https URL
            resp.read(65536)
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return type(exc).__name__


def remote(public_base: str, tenant: str, channel: str) -> dict[str, Any]:
    base = f"{public_base.rstrip('/')}/collective/{tenant}"
    return {"host": _host(public_base), "tenant": tenant,
            "trust_json": probe(f"{base}/trust.json"),
            f"channel_{channel.lower()}": probe(f"{base}/channels/{channel}.json")}


# --------------------------------------------------------------------------- report
def report(engine: Path, runtime: Path, *, episode: str | None = None, network: bool = True) -> dict[str, Any]:
    reports = reports_dir(runtime)
    episode = episode or current_episode(runtime)
    config_path = reports / CONFIG_NAME
    raw = _read_json(config_path)
    config: dict[str, Any] = raw if isinstance(raw, dict) else {}
    base = config_path.parent

    def _p(value: Any) -> Path:
        p = Path(str(value)).expanduser()
        return p if p.is_absolute() else base / p

    obj = config.get("object_store") if isinstance(config.get("object_store"), dict) else {}
    collective: dict[str, Any] = {
        "config_present": config_path.is_file(), "config_parseable": bool(config) or not config_path.is_file(),
        "config_path": str(config_path),
        "config_keys": {k: k in config for k in CONFIG_KEYS},
        "device_store_enabled": bool(config.get("device_store")),
        "sync_mode": ((config.get("sync") or {}).get("mode") if isinstance(config.get("sync"), dict) else None)
                     or ("http" if config else None),
        "channel": config.get("channel") or ("RELEASED" if config else None),
        "endpoint_host": _host(obj.get("endpoint_url") or os.environ.get("S3CTL_ENDPOINT_URL")
                               or os.environ.get("AWS_ENDPOINT_URL")),
        "public_base_host": _host(obj.get("public_base_url") or os.environ.get("S3CTL_PUBLIC_BASE_URL")),
        "bucket_set": bool(obj.get("bucket") or os.environ.get("S3CTL_BUCKET") or os.environ.get("COLLECTIVE_OBJECT_BUCKET")),
    }
    if config:
        trust = _read_json(_p(config["trust_store"])) if config.get("trust_store") else None
        collective["trust_store_present"] = isinstance(trust, dict)
        collective["trust_publishers"] = len((trust or {}).get("publishers") or {}) if isinstance(trust, dict) else 0
        collective["cache"] = cache_stats(_p(config["cache_dir"])) if config.get("cache_dir") else {"present": False}
        receipt = _read_json(_p(obj.get("preflight_receipt") or f"S3_PREFLIGHT_{config.get('line_id', 'nalu')}.json"))
        collective["s3_preflight"] = ({"status": receipt.get("status"), "at": receipt.get("finished_at")
                                       or receipt.get("at") or receipt.get("started_at")}
                                      if isinstance(receipt, dict) else None)
        collective["credentials"] = credentials(config, base, engine)
    collective["store"] = store_stats(reports / STORE_NAME)
    collective["sync_agent"] = sync_agent(reports)
    collective["provisioning"] = provisioning(runtime)
    collective["device_sync"] = last_device_sync(reports)
    collective["cached_pack"] = cached_pack(collective.get("cache") or {})

    out: dict[str, Any] = {"schema": SCHEMA, "at": _now(), "episode": episode,
                           "local_kb": local_kb(engine, reports, episode), "collective": collective,
                           "episode_run": episode_run(runtime, reports, episode)}
    if network and os.environ.get("NALU_FLEET_URL", "").strip().lower() != "off":
        public = str(obj.get("public_base_url") or os.environ.get("S3CTL_PUBLIC_BASE_URL") or DEFAULT_PUBLIC_BASE)
        out["remote"] = remote(public, str(config.get("tenant_id") or DEFAULT_TENANT),
                               str(config.get("channel") or "RELEASED"))
    else:
        out["remote"] = {"checked": False}
    out["verdict"], out["gaps"] = verdict(out)
    return out


def verdict(r: dict[str, Any]) -> tuple[str, list[str]]:
    c, run = r["collective"], r["episode_run"]
    gaps: list[str] = []
    if not c["config_present"]:
        gaps.append("NO_COLLECTIVE_LEARNING_CONFIG")
    elif not c["config_parseable"]:
        gaps.append("CONFIG_UNPARSEABLE")
    else:
        if not c.get("trust_store_present"):
            gaps.append("TRUST_STORE_MISSING")
        if not (c.get("credentials") or {}).get("resolvable"):
            gaps.append("S3_CREDENTIALS_NOT_RESOLVABLE")
        if not c.get("endpoint_host"):
            gaps.append("ENDPOINT_NOT_SET")
        if not (c["sync_agent"]["launchd_plist"] or c["sync_agent"]["crontab"] or c["sync_agent"].get("fleet_tick")):
            gaps.append("NO_DEVICE_SYNC_AGENT")
        if (c.get("device_sync") or {}).get("present") and c["device_sync"].get("status") != "OK":
            gaps.append(f"DEVICE_SYNC_{c['device_sync'].get('status')}")
        if not (c.get("cache") or {}).get("entries"):
            gaps.append("BUNDLE_CACHE_EMPTY")
        if not c["device_store_enabled"]:
            gaps.append("DEVICE_STORE_DISABLED")
    rem = r.get("remote") or {}
    chan = next((v for k, v in rem.items() if k.startswith("channel_")), None)
    if rem.get("checked") is not False and chan == 404:
        gaps.append("NO_PUBLISHED_CHANNEL_POINTER")
    if r["local_kb"].get("briefing") and not r["local_kb"]["briefing"]["present"]:
        gaps.append("NO_BRIEFING_THIS_EPISODE")
    if not c["config_present"]:
        return "NOT_CONFIGURED", gaps
    if run.get("kb_injected_in_provider_prompts"):
        return "ACTIVE_APPLIED", gaps
    if run.get("collective_status") == "LOCKED":
        return ("LOCKED_NOT_APPLIED" if run.get("lock_bundles") else "LOCKED_EMPTY"), gaps
    return "CONFIGURED_NOT_LOCKED", gaps


def summary(r: dict[str, Any]) -> dict[str, Any]:
    """<= 240 chars: what fleet diagnose keeps."""
    c, run, rem = r["collective"], r["episode_run"], r.get("remote") or {}
    store = c.get("store") or {}
    outbox = store.get("outbox") or {}
    chan = next((v for k, v in rem.items() if k.startswith("channel_")), "-")
    s = {"v": r["verdict"], "ep": r.get("episode"), "cfg": int(c["config_present"]),
         "cred": int(bool((c.get("credentials") or {}).get("resolvable"))),
         "agent": int(c["sync_agent"]["launchd_plist"] or c["sync_agent"]["crontab"]
                      or bool(c["sync_agent"].get("fleet_tick"))),
         "prov": (c.get("provisioning") or {}).get("last_result") or "-",
         "sync": (c.get("device_sync") or {}).get("status") or "-",
         "ch": c.get("channel") or "-", "pack": c.get("cached_pack") or "-",
         "cache": (c.get("cache") or {}).get("entries", 0), "ev": store.get("events", 0),
         "ob": f"{outbox.get('PENDING', 0)}p/{outbox.get('DELIVERED', 0)}d",
         "lock": run.get("collective_status") or "-", "appl": (run.get("adoption") or {}).get("APPLIED", 0),
         "brief": int(bool((r["local_kb"].get("briefing") or {}).get("present"))),
         "rules": r["local_kb"].get("registry_rules"), "chan": chan}
    text = json.dumps(s, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= 240:
        return s
    short = {k: s[k] for k in ("v", "cfg", "prov", "sync", "ch", "pack", "lock", "appl")}
    return short if len(json.dumps(short, ensure_ascii=False, separators=(",", ":"))) <= 240 else \
        {"v": r["verdict"], "cfg": s["cfg"], "lock": s["lock"], "appl": s["appl"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--engine-root", type=Path)
    ap.add_argument("--runtime-root", type=Path)
    ap.add_argument("--episode")
    ap.add_argument("--no-network", action="store_true")
    ap.add_argument("--full", action="store_true", help="only the full report, indented")
    a = ap.parse_args(argv)
    engine = (a.engine_root or Path(os.environ.get("NALU_ENGINE_ROOT") or "~/nalu_engine")).expanduser()
    runtime = (a.runtime_root or Path(os.environ.get("NALU_RUNTIME_ROOT") or "~/nalu_runtime")).expanduser()
    try:
        r = report(engine, runtime, episode=a.episode, network=not a.no_network)
    except Exception as exc:  # noqa: BLE001 -- diagnose must always get one JSON line
        print(json.dumps({"v": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:160]}"}))
        return 1
    if a.full:
        print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
    else:
        print(json.dumps(r, ensure_ascii=False, default=str))
        print(json.dumps(summary(r), ensure_ascii=False, separators=(",", ":"), default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
