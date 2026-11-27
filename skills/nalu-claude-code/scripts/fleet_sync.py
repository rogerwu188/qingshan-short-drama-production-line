#!/usr/bin/env python3
"""Fleet status + command channel for one device (line owner 2026-11-09, nalu-fleet service).

Called at the end of every tick (the system cron's `tick --system` every 3 min, and the agent heartbeat): it reports this machine's state to the
fleet service and runs the whitelisted commands the superadmin queued for it.  Never raises and never blocks
the tick for long (short timeouts); a machine without network or without the service just skips it.

* identity: the hardware SN (device_sn.py); the device token from first contact lives in
  $NALU_RUNTIME_ROOT/credentials/fleet_token (mode 600) and is never printed.
* report: episode / stage / state / note, the newest CODE_BLOCKER report text when blocked, local credits,
  X2C local counts, engine commit, STATUS.md tail, and the HopsAPI account balance (GET /v1/account/credits,
  free, at most every 10 min).  No keys, no media.
* collective knowledge base (audit 2026-11-12): ``collective_tick`` fetches this device's collective-learning config
  from GET /v1/collective/provision (at most every 30 min) and starts a detached ``s3_sync.py device-sync`` (at most
  every 15 min, skipped while one runs); see collective_provision.py.  Disabled on the server = nothing touched.
* commands: review_upload (fixed review files of one episode -> HopsAPI storage, URLs in the result) /
  diagnose (model-free health check) / agent_task (instruction for the StoryClaw agent) /
  resume (hand the message to Codex) / update (scripted: self_update, set up the pin from the updated
  AGENTS.md, resume a stopped episode when the engine moved; ``restart_in_flight: true`` first abandons the
  in-flight episode and redoes it from S1 on the new engine, engine_restart.py) / pause / unpause / query.  Nothing else is executed.

  NALU_FLEET_URL overrides the service URL; NALU_FLEET_URL=off disables the channel.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
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


CREDITS_CACHE_S = 600
CREDITS_DEFAULT_BASE = "https://hopsapi.com/v1"


def _env_value(path: Path, name: str) -> str:
    try:
        m = re.search(rf"^\s*(?:export\s+)?{re.escape(name)}=(.*)$", path.read_text(encoding="utf-8"), re.M)
    except OSError:
        return ""
    return m.group(1).strip().strip("'\"") if m else ""


def hopsapi_key(engine: Path, runtime: Path) -> str:
    """The line's HopsAPI key, as paid_stage.sh resolves it: engine .env HOPSAPI_API_KEY, else the Codex provider
    key when the provider is HopsAPI.  Never printed or reported."""
    key = _env_value(engine / ".env", "HOPSAPI_API_KEY")
    if not key:
        try:
            p = json.loads((runtime / "credentials" / "llm_provider.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            p = {}
        if "hopsapi" in str(p.get("base_url") or "").lower():
            key = str(p.get("api_key") or "").strip()
    return key


def hopsapi_credits(engine: Path, runtime: Path, *, now: float | None = None) -> dict | None:
    """The HopsAPI account balance this device bills (line owner 2026-11-12: one credit pool for the whole
    fleet; when it hits 0 every S6 video fails at zero cost).  ``GET /v1/account/credits`` is free and needs no
    model; cached for CREDITS_CACHE_S so the 3-minute tick asks at most every 10 minutes.  The key is the one
    paid_stage.sh uses (engine .env HOPSAPI_API_KEY, else the Codex provider key when it is HopsAPI); it is
    never printed or reported.  Returns {"credits", "outstanding", "key_remaining", "at"} or {"error", "at"}."""
    import time  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415
    if os.environ.get("NALU_FLEET_URL", "").strip().lower() == "off":
        return None  # fleet channel disabled: no outbound probe either
    now = time.time() if now is None else now
    cache = runtime / "series" / ".hopsapi_credits.json"
    try:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if now - float(cached.get("_epoch") or 0) < CREDITS_CACHE_S:
            return {k: v for k, v in cached.items() if not k.startswith("_")}
    except (OSError, ValueError):
        pass
    key = hopsapi_key(engine, runtime)
    base = _env_value(engine / ".env", "HOPSAPI_BASE_URL") or CREDITS_DEFAULT_BASE
    if not key:
        return None
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    req = urllib.request.Request(base.rstrip("/") + "/account/credits",
                                 headers={"Authorization": "Bearer " + key, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = (json.loads(resp.read().decode("utf-8") or "{}") or {}).get("data") or {}
        limit = data.get("key_limit") or {}
        out = {"credits": data.get("credits"), "outstanding": data.get("outstanding"),
               "key_remaining": limit.get("remaining") if isinstance(limit, dict) else None, "at": stamp}
    except urllib.error.HTTPError as exc:
        out = {"error": f"HTTP {exc.code}", "at": stamp}
    except (OSError, ValueError) as exc:
        out = {"error": type(exc).__name__, "at": stamp}
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({**out, "_epoch": now}), encoding="utf-8")
    except OSError:
        pass
    return out


COVER_CHECK_S = 1800
COVER_WIDTH = 360
COVER_MAX_BYTES = 150_000  # base64 of it must fit the fleet service body limit (256 KiB)


def _final_cuts(engine: Path, runtime: Path) -> list[Path]:
    """Final cuts of this line, newest first: promoted deliverables, else the latest S7 candidates."""
    found: list[Path] = []
    for root in (runtime / "runtime" / "deliverables", runtime / "deliverables"):
        found += [p for p in root.glob("*/*_final_9x16.mp4") if p.is_file()]
    if not found:
        found += [p for p in (engine / "workflow" / "nalu").glob("*/assembly/*final_candidate*9x16*.mp4") if p.is_file()]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def series_cover(engine: Path, runtime: Path) -> tuple[bytes, dict] | None:
    """A dashboard cover for this series (line owner 2026-11-13, option A: a still from the latest final cut, free).
    Three candidate frames (30 / 45 / 60 % in), 360 px wide JPEG; the most detailed one wins (largest JPEG: not a
    black, faded or flat frame).  None when there is no final cut yet or ffmpeg is missing."""
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    cuts = _final_cuts(engine, runtime)
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not cuts or not ffmpeg or not ffprobe:
        return None
    src = cuts[0]
    rc, out = _run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)], 30)
    try:
        duration = float(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None
    best: bytes = b""
    with tempfile.TemporaryDirectory() as tmp:
        for i, frac in enumerate((0.30, 0.45, 0.60)):
            jpg = Path(tmp) / f"c{i}.jpg"
            _run([ffmpeg, "-v", "error", "-y", "-ss", f"{duration * frac:.2f}", "-i", str(src), "-frames:v", "1",
                  "-vf", f"scale={COVER_WIDTH}:-2", "-q:v", "5", str(jpg)], 60)
            data = jpg.read_bytes() if jpg.is_file() else b""
            if len(data) > len(best) and len(data) <= COVER_MAX_BYTES:
                best = data
    if not best:
        return None
    return best, {"source": src.name, "episode": src.name.split("_", 1)[0]}


def cover_tick(cp: Any, token: str, *, now: float | None = None) -> str | None:
    """Upload the series cover when it changed (checked every COVER_CHECK_S): the series poster thumbnail
    ``series/cover/cover_thumb.jpg`` when present (tools/series_poster.py), else a still of the latest final cut."""
    import base64  # noqa: PLC0415
    import hashlib  # noqa: PLC0415
    import time  # noqa: PLC0415
    engine, runtime = cp.roots()
    now = time.time() if now is None else now
    state_path = runtime / "series" / ".fleet_cover.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if now - float(state.get("checked") or 0) < COVER_CHECK_S:
        return None
    state["checked"] = now
    thumb = runtime / "series" / "cover" / "cover_thumb.jpg"  # the series poster (tools/series_poster.py)
    try:
        poster = thumb.read_bytes() if thumb.is_file() else b""
    except OSError:
        poster = b""
    if poster and poster.startswith(b"\xff\xd8") and len(poster) <= COVER_MAX_BYTES:
        digest = hashlib.sha256(poster).hexdigest()
        key = f"poster:{digest}"
        result = "UNCHANGED"
        if key != state.get("uploaded_key"):
            code, _ = _req("POST", "/v1/cover", {"episode": "SERIES_POSTER", "source": thumb.name, "sha256": digest,
                                                  "image_b64": base64.b64encode(poster).decode("ascii")}, token=token)
            result = f"UPLOADED_POSTER:{code}"
            if code == 200:
                state["uploaded_key"] = key
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            pass
        return result
    cuts = _final_cuts(engine, runtime)
    key = f"{cuts[0]}|{cuts[0].stat().st_size}|{int(cuts[0].stat().st_mtime)}" if cuts else ""
    result = "NO_FINAL_CUT" if not cuts else "UNCHANGED"
    if cuts and key != state.get("uploaded_key"):
        cover = series_cover(engine, runtime)
        if cover is None:
            result = "NO_FRAME"
        else:
            data, meta = cover
            code, _ = _req("POST", "/v1/cover", {"episode": meta["episode"], "source": meta["source"],
                                                  "sha256": hashlib.sha256(data).hexdigest(),
                                                  "image_b64": base64.b64encode(data).decode("ascii")}, token=token)
            result = f"UPLOADED:{code}"
            if code == 200:
                state["uploaded_key"] = key
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass
    return result


DIALOGUE_LANGUAGES = ("zh", "en", "ja", "ko")


def dialogue_language(runtime: Path) -> str | None:
    """The series' spoken-dialogue language for the fleet dashboard's 中文/英文/日文/韩文剧 groups:
    ``<runtime>/qingshan.json`` ``project.language`` ("zh-CN" / "en-US" / "ja-JP" / "ko-KR" / "ja" ...) as the
    2-letter code, the same normalisation as nalu_pipeline.resolve_dialogue_language.  None when it is not set
    or unreadable (the server then falls back to its series-title heuristic); never raises."""
    try:
        cfg = json.loads((runtime / "qingshan.json").read_text(encoding="utf-8"))
        project = cfg.get("project") if isinstance(cfg, dict) else None
        value = project.get("language") if isinstance(project, dict) else None
        text = str(value or "").strip().lower().replace("_", "-")
        return next((c for c in DIALOGUE_LANGUAGES if text == c or text.startswith(c + "-")), None)
    except Exception:  # noqa: BLE001 -- a missing / broken config only costs the dashboard grouping
        return None


def final_fix_note(engine: Path, episode: str) -> tuple[dict | None, str]:
    """The episode's final fix round (owner 2026-11-20; workflow/nalu/<EP>/assembly/final_qa/final_fix_round.json):
    (concise summary, one-line note) or (None, "").  Never raises."""
    if not episode:
        return None, ""
    try:
        work = Path(os.environ.get("NALU_WORK_ROOT") or (engine / "workflow" / "nalu"))
        path = work / episode / "assembly" / "final_qa" / "final_fix_round.json"
        if not path.is_file():
            return None, ""
        record = json.loads(path.read_text(encoding="utf-8"))
        tools = engine / "lines" / "nalu" / "runtime" / "tools"
        if str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        import final_fix_round as ffr  # noqa: PLC0415
        return ffr.summary(record), ffr.status_note(record)
    except Exception:  # noqa: BLE001 -- the report never fails on this
        return None, ""


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
            x2c["api_mode"] = "matrix"
            x2c["published"] = len(mx.sent_episodes())
        else:
            x2c["api_mode"] = "open"
    except Exception:  # noqa: BLE001
        pass
    try:
        import deployment_mode as dm  # noqa: PLC0415  (single-machine vs fleet, owner 2026-11-25)
        deployment = dm.mode(runtime)
    except Exception:  # noqa: BLE001
        deployment = "fleet"
    state = str(ns.get("state") or run or "")
    fix_summary, fix_note = final_fix_note(engine, ep)
    blocker_text = _newest_blocker(engine, ep) if ep and state == "BLOCKED" else ""
    try:
        lines = (runtime / "series" / "STATUS.md").read_text(encoding="utf-8").splitlines()
        tail = "\n".join([x for x in lines if x.strip()][-15:])
    except OSError:
        tail = ""
    status = {
        "episode": ep, "stage": stage or str(ns.get("stage") or ""), "state": state, "run": run,
        "note": " | ".join(x for x in (str(ns.get("note") or ""), fix_note) if x)[:500],
        "final_fix_round": fix_summary,
        "blocker": (blocker_text.splitlines()[0] if blocker_text else
                    str(tick_result.get("reason") or "") if tick_result.get("action") == "AGENT" else ""),
        "tick_action": tick_result.get("action"), "tick_reason": tick_result.get("reason"),
        "credits_episode": spent.get(ep), "credits_total": round(sum(spent.values()), 2),
        "pipeline": pipeline, "x2c": x2c, "engine_sha": _engine_sha(engine),
        "final_review": (tick_result.get("final_review") or {}).get("status"),
        "dialogue_language": dialogue_language(runtime),
        "deployment_mode": deployment,
    }
    try:
        status["hopsapi_credits"] = hopsapi_credits(engine, runtime)
    except Exception:  # noqa: BLE001 -- the report never fails on the balance probe
        status["hopsapi_credits"] = None
    try:
        import collective_provision  # noqa: PLC0415
        status["collective"] = collective_provision.report(runtime)
    except Exception:  # noqa: BLE001
        status["collective"] = None
    return status, blocker_text, tail


AGENT_ID = os.environ.get("NALU_AGENT_ID") or "qingshan-ai-drama-factory-minipc"
PIN_RE = re.compile(r'setup_host\.sh"?\s+--pin\s+([0-9a-f]{40})')
RESUMABLE_STATES = ("BLOCKED", "FINAL_REVIEW_REQUIRED")


def _git_is_ancestor(engine: Path | None, older: str, newer: str) -> bool | None:
    """True / False when the engine clone knows both commits (one fetch is tried for an unknown one), None when not."""
    if engine is None or not (Path(engine) / ".git").exists():
        return None
    for attempt in (0, 1):
        try:
            done = subprocess.run(["git", "-C", str(engine), "merge-base", "--is-ancestor", older, newer],
                                  capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError):
            return None
        if done.returncode in (0, 1):
            return done.returncode == 0
        if attempt == 0:  # rc 128: a commit the clone has not fetched yet
            try:
                subprocess.run(["git", "-C", str(engine), "fetch", "-q", "origin"], capture_output=True, timeout=120)
            except (OSError, subprocess.SubprocessError):
                return None
    return None


def disk_pin(engine: Path | None = None) -> str:
    """The pin the next episode sets up: the latest pin the maintainer pushed through the fleet (~/.nalu_fleet_pin),
    unless an installed AGENTS.md names a commit that is strictly newer in the engine's history.

    Not newest-by-mtime: the between-episode self_update rewrites AGENTS.md with whatever TalentHub version it sees
    (that version may still carry an older pin than the fleet sent), and the fresh mtime then beat the fleet pin --
    …1437 KO E01->E02 2026-11-24 02:09Z set up 2787448 again although update #1866 had sent 8e84065, while …1485,
    whose self_update was UP_TO_DATE, moved to 8e84065.  ``setup_host.sh`` separately never moves HEAD back."""
    home = Path.home()
    if engine is None:
        engine = Path(os.environ.get("NALU_ENGINE_ROOT") or home / "nalu_engine").expanduser()
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
    fleet = ""
    try:  # the latest pin the maintainer pushed through the fleet (agents not talenthub-installed never get a
        # newer AGENTS.md, so the next episode's update would set up the old engine again)
        value = (home / ".nalu_fleet_pin").read_text(encoding="utf-8").strip()
        if re.fullmatch(r"[0-9a-f]{40}", value):
            fleet = value
    except OSError:
        pass
    ordered = [pin for _, pin in sorted(found, reverse=True)]
    best = fleet or (ordered[0] if ordered else "")
    for pin in ordered:  # a strictly newer commit (by history, never by file time) replaces the choice
        if pin != best and _git_is_ancestor(engine, best, pin):
            best = pin
    return best


def _run(argv: list[str], timeout: int, extra_env: dict | None = None) -> tuple[int, str]:
    """rc and the last 2000 characters of stdout (enough for a status line or a log tail)."""
    rc, out = _run_full(argv, timeout, extra_env)
    return rc, out[-2000:]


def _run_full(argv: list[str], timeout: int, extra_env: dict | None = None) -> tuple[int, str]:
    """rc and the whole stdout, for output that is parsed (a cut-off JSON document is not JSON)."""
    try:
        import codex_production  # noqa: PLC0415 -- the same tool directories (and newest node) the executor uses
        dirs = codex_production.tool_dirs()
        best = codex_production.newest_node_dir([*dirs, *os.environ.get("PATH", "").split(":")])
        dirs = [best, *dirs] if best else dirs
    except Exception:  # noqa: BLE001 -- keep the essentials: user bins + any nvm node (system node may be v12)
        home = Path.home()
        dirs = [str(home / ".local/bin"), str(home / ".npm-global/bin"),
                *sorted((str(p) for p in home.glob(".nvm/versions/node/*/bin")), reverse=True)]
    env = {**os.environ, **(extra_env or {}), "PATH": ":".join([*dirs, os.environ.get("PATH", "")])}
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
        return done.returncode, done.stdout or ""
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


def scripted_update(cp: Any, pin: str, restart_in_flight: bool = False, major: str = "") -> tuple[bool, dict, dict]:
    """self_update (no restart) -> setup_host --pin -> resume a stopped episode when the engine moved.

    Deterministic, no model (line owner + boss 2026-11-10): the agent-run FLEET_UPDATE once set up the stale pin
    because it read AGENTS.md before self_update had replaced it (field device …1324 E04).

    ``restart_in_flight`` (fleet ``update`` payload, line owner 2026-11-23 「重大引擎改动后……放弃当前这集的进度，用新引擎
    重新做这一集」): before the setup, the current episode -- when its engine lacks ``major`` (default: the pin) and it
    was not restarted for this pin before -- is stopped and archived (engine_restart.prepare), so the setup is not
    deferred; after it the episode starts again from S1 on the new engine (engine_restart.finish)."""
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
    pin = pin or disk_pin(engine)
    if not re.fullmatch(r"[0-9a-f]{40}", pin or ""):
        return False, {"error": "NO_PIN", "self_update": su_out[-300:]}, {}
    before = _engine_sha(engine)
    restart: dict = {}
    if restart_in_flight:
        restart = _restart_prepare(cp, pin, major)
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
    if restart:
        if restart.get("phase") == "ARCHIVED":
            restart = {**restart, **_restart_finish(cp, ep, pin)}
        result["restart"] = {k: restart.get(k) for k in ("phase", "reason", "episode", "engine", "archive", "moved",
                                                          "move_failed", "new_engine", "start") if k in restart}
        if restart.get("phase") in ("STARTED", "START_FAILED"):
            return st_rc == 0 and restart.get("phase") == "STARTED", result, {}
    if ep and after and after != before:
        st = cp.status(ep)
        state = str((st["codex"].get("nalu_status") or {}).get("state") or "")
        result["resume_check"] = {"episode": ep, "run": st.get("status"), "state": state}
        if st.get("status") != "RUNNING" and state in RESUMABLE_STATES:
            out = cp.resume(ep, f"引擎已更新到 {after[:7]}（维护者经 fleet 修复），按新版合同从当前阶段继续。")
            result["resumed"] = out.get("status")
    return st_rc == 0, result, {}


def _restart_module(engine: Path, pin: str) -> Any:
    """engine_restart as of the PIN (``git show``), else the running copy.

    The restart decision belongs to the engine being installed: this fleet_sync runs from the old checkout, and an
    in-flight episode defers the setup, so a fixed eligibility in the pin could otherwise never reach the device
    (…1101 E27, 2026-11-24: the running c41d582 copy judged by the HEAD and skipped)."""
    import importlib.util  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    rel = "skills/nalu-claude-code/scripts/engine_restart.py"
    try:
        subprocess.run(["git", "-C", str(engine), "fetch", "-q", "origin"], capture_output=True, timeout=300)
        done = subprocess.run(["git", "-C", str(engine), "show", f"{pin}:{rel}"], capture_output=True, text=True,
                              timeout=30)
        if done.returncode == 0 and "def prepare(" in done.stdout:
            path = Path(tempfile.mkdtemp(prefix="nalu_restart_mod_")) / "engine_restart_pin.py"
            path.write_text(done.stdout, encoding="utf-8")
            spec = importlib.util.spec_from_file_location(f"engine_restart_pin_{pin[:12]}", path)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
    except Exception:  # noqa: BLE001 -- the running copy still restarts
        pass
    import engine_restart  # noqa: PLC0415
    return engine_restart


def _restart_prepare(cp: Any, pin: str, major: str) -> dict:
    """engine_restart.prepare for the current episode (never raises: a failed restart leaves a normal update)."""
    try:
        import device_sn  # noqa: PLC0415
        engine, runtime = cp.roots()
        engine_restart = _restart_module(engine, pin)
        ep = cp.current_episode() or ""
        again = engine_restart.find_restart(runtime, ep, pin) if ep else None
        if again and again.get("phase") == "ARCHIVED":  # interrupted after the archive: only the start is left
            return {"phase": "ARCHIVED", "episode": ep, "archive": again.get("archive"), "resumed_restart": True}
        return engine_restart.prepare(engine, runtime, ep, pin, major=major, device_sn=device_sn.resolve()[0] or "")
    except Exception as exc:  # noqa: BLE001
        return {"phase": "ERROR", "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _restart_finish(cp: Any, ep: str | None, pin: str) -> dict:
    try:
        engine, runtime = cp.roots()
        return _restart_module(engine, pin).finish(engine, runtime, ep or "", pin)
    except Exception as exc:  # noqa: BLE001
        return {"phase": "START_FAILED", "reason": f"{type(exc).__name__}: {str(exc)[:200]}"}


AGENT_TASK_FILE = "FLEET_AGENT_TASK.json"


def _short(rc_out: tuple[int, str], lines: int = 3) -> dict:
    rc, out = rc_out
    return {"rc": rc, "tail": [x[:240] for x in out.strip().splitlines()[-lines:]]}


def _cron_jobs() -> list[dict]:
    """name / enabled / model / last status of the OpenClaw scheduled tasks (no prompts, no keys), or []."""
    # the whole stdout: the job list carries every prompt and is far longer than _run's 2000-character tail, so
    # the cut-off document was never JSON and agent_task could not find the heartbeat job to kick (…1324, …0030,
    # …0841 2026-11-15: heartbeat_kick null, the task waited for the 6-hourly heartbeat)
    rc, out = _run_full(["openclaw", "cron", "list", "--json"], 30)
    if rc != 0:
        return [{"error": f"openclaw cron list rc={rc}", "tail": out.strip()[-200:]}]
    starts = [i for i in (out.find("{"), out.find("[")) if i >= 0]
    try:
        data, _ = json.JSONDecoder().raw_decode(out[min(starts):]) if starts else (None, 0)
    except ValueError:
        data = None
    if data is None:
        return [{"error": "openclaw cron list: not JSON", "chars": len(out)}]
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
    # which account production bills (line owner 2026-11-12: never StoryClaw); provenance only, no values
    out["billing_keys"] = _short(_run(["python3", str(scripts / "billing_key_guard.py"), "report"], 30, env), 1)
    # cloud shared knowledge base (collective learning): configured / synced / applied? booleans + counts only
    out["knowledge"] = _short(_run(["python3", str(scripts / "knowledge_status.py")], 60, env), 1)
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


REVIEW_FILES = ("final_cut", "contract", "timeline", "gemini_review")
REVIEW_EPISODE_RE = re.compile(r"E\d{2,3}")
REVIEW_MAX_BYTES = 200 * 1024 * 1024
REVIEW_UPLOAD_PATH = "maint-review"
HELD_CUT_SUFFIX = "_held_cut.mp4"


def _contract_candidates(engine: Path, runtime: Path, ep: str) -> list[Path]:
    """Where this episode's generation contract can live, most authoritative first: the path the pipeline
    recorded for the episode (only if it is named for this episode), the writer's v1 slot, the episode work dir
    (and one level below), then other versions in the writer dir."""
    name = re.compile(rf"{ep}_GENERATION_CONTRACT(_v\d+)?\.json")
    out: list[Path] = []
    try:
        state = json.loads((runtime / "runtime" / "pipeline_state" / f"{ep}.json").read_text(encoding="utf-8"))
        recorded = str(((state.get("layers") or {}).get("paths") or {}).get("generation_contract") or "")
        if recorded and name.fullmatch(Path(recorded).name):
            out.append(Path(recorded).expanduser())
    except (OSError, ValueError, AttributeError):
        pass
    scripts = engine / "workflow" / "claude_writer_agent" / "scripts"
    work = Path(os.environ.get("NALU_WORK_ROOT") or engine / "workflow" / "nalu") / ep
    out.append(scripts / f"{ep}_GENERATION_CONTRACT_v1.json")
    for d in (work, *sorted(p for p in work.glob("*") if p.is_dir())):
        out += sorted((p for p in d.glob(f"{ep}_GENERATION_CONTRACT*.json") if name.fullmatch(p.name)), reverse=True)
    out += sorted((p for p in scripts.glob(f"{ep}_GENERATION_CONTRACT_v*.json") if name.fullmatch(p.name)),
                  reverse=True)
    seen, uniq = set(), []
    for p in out:
        if str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq


def _json_episode(path: Path) -> str | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return str(doc.get("episode") or "").strip().upper() if isinstance(doc, dict) else None


def review_files(engine: Path, runtime: Path, ep: str) -> dict[str, tuple[Path | None, str]]:
    """{kind: (path or None, upload file name or the reason it is missing)} by fixed rules; no caller paths."""
    work = Path(os.environ.get("NALU_WORK_ROOT") or engine / "workflow" / "nalu") / ep
    out: dict[str, tuple[Path | None, str]] = {}
    cut = next((p for p in (runtime / "deliverables" / ep / f"{ep}_final_9x16.mp4",
                            runtime / "runtime" / "deliverables" / ep / f"{ep}_final_9x16.mp4") if p.is_file()), None)
    if cut:
        out["final_cut"] = (cut, f"{ep}_final_9x16.mp4")
    else:
        # a RELEASE_HELD episode has no deliverable (2026-11-27, 1101 E29): the newest assembly cut instead -- the
        # S7 final candidate (the final-fix round's output, the cut the second review watched) or the subbed
        # end-card + BGM cut -- uploaded as <EP>_held_cut.mp4 (review_upload marks it ``held``)
        held = [p for p in (work / "assembly" / f"{ep}_final_candidate_9x16.mp4",
                            work / "assembly" / f"{ep}_picture_native_subbed_endcard_bgm.mp4") if p.is_file()]
        held.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        out["final_cut"] = (held[0], f"{ep}{HELD_CUT_SUFFIX}") if held else (None, "NOT_FOUND")
    contract, wrong = None, []
    for p in _contract_candidates(engine, runtime, ep):
        if p.is_file():
            got = _json_episode(p)
            if got == ep:
                contract = p
                break
            wrong.append(f"{p.name}:episode={got}")
    out["contract"] = (contract, contract.name) if contract else (
        None, "EPISODE_MISMATCH:" + ",".join(wrong)[:200] if wrong else "NOT_FOUND")
    timeline = work / "assembly" / f"{ep}_release_timeline.json"
    out["timeline"] = (timeline, timeline.name) if timeline.is_file() else (None, "NOT_FOUND")
    review = runtime / "claude_code" / ep / "final_reviewer" / "gemini_review.json"
    out["gemini_review"] = (review, f"{ep}_gemini_review.json") if review.is_file() else (None, "NOT_FOUND")
    return out


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    real = path.resolve()
    return any(real == r.resolve() or r.resolve() in real.parents for r in roots)


def review_upload(cp: Any, payload: dict) -> tuple[bool, dict, dict]:
    """Upload fixed review files of one episode for the maintainers' daily deep review (owner 2026-11-23): the final
    cut, its generation contract, the release timeline and the device's Gemini final review.  A held episode (no
    deliverable) uploads its newest assembly cut as ``<EP>_held_cut.mp4`` with ``held: true``.  System code, no
    model, no shell; only these files (resolved by fixed rules, never a caller path), <= REVIEW_MAX_BYTES each, to
    HopsAPI file storage (free) with the line's key (never printed).  Read-only for production."""
    ep = str(payload.get("episode") or "").strip().upper()
    if not REVIEW_EPISODE_RE.fullmatch(ep):
        return False, {"error": "REVIEW_UPLOAD_BAD_EPISODE"}, {}
    kinds = payload.get("files") or list(REVIEW_FILES)
    if not isinstance(kinds, list) or not all(k in REVIEW_FILES for k in kinds):
        return False, {"error": "REVIEW_UPLOAD_BAD_FILES"}, {}
    engine, runtime = cp.roots()
    result: dict[str, Any] = {"episode": ep, "engine_sha": _engine_sha(engine)[:12], "files": {}, "missing": []}
    key = hopsapi_key(engine, runtime) or str(os.environ.get("HOPSAPI_API_KEY") or "").strip()
    if not key:
        return False, {**result, "error": "NO_HOPSAPI_KEY"}, {}
    tools = engine / "tools"
    if str(tools) not in sys.path:
        sys.path.insert(0, str(tools))
    try:
        import hopsapi_video_client as hv  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        return False, {**result, "error": f"UPLOAD_CLIENT_UNAVAILABLE:{type(exc).__name__}"}, {}
    found = review_files(engine, runtime, ep)
    failed = False
    old_key = os.environ.get(hv.API_KEY_ENV)
    os.environ[hv.API_KEY_ENV] = key
    try:
        for kind in (k for k in REVIEW_FILES if k in kinds):
            path, name = found[kind]
            if path is None:
                result["missing"].append({"file": kind, "reason": name})
                continue
            if not _inside(path, (engine, runtime)):
                result["missing"].append({"file": kind, "reason": "OUTSIDE_ENGINE_OR_RUNTIME"})
                continue
            size = path.stat().st_size
            if size > REVIEW_MAX_BYTES:
                result["missing"].append({"file": kind, "reason": f"TOO_LARGE:{size}"})
                continue
            mime = "video/mp4" if kind == "final_cut" else "application/json"
            try:
                up = hv.upload_bytes(path.read_bytes(), file_name=name, upload_path=REVIEW_UPLOAD_PATH, mime=mime)
            except (Exception, SystemExit) as exc:  # noqa: BLE001 -- one file failing never aborts the others
                failed = True
                result["missing"].append({"file": kind, "reason": f"UPLOAD_FAILED:{str(exc)[:160]}"})
                continue
            result["files"][kind] = {k: up.get(k) for k in ("url", "sha256", "bytes", "expires_at", "file_name")}
            if kind == "final_cut" and name.endswith(HELD_CUT_SUFFIX):
                result["files"][kind].update(held=True, source=path.name)
                result["held"] = True
    finally:
        if old_key is None:
            os.environ.pop(hv.API_KEY_ENV, None)
        else:
            os.environ[hv.API_KEY_ENV] = old_key
    for row in result["missing"]:  # error text must never carry the key
        row["reason"] = row["reason"].replace(key, "***")
    return not failed, result, {}


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
        major = str(payload.get("major") or "")
        return scripted_update(cp, str(payload.get("pin") or ""), restart_in_flight=payload.get("restart_in_flight") is True,
                               major=major if re.fullmatch(r"[0-9a-f]{40}", major) else "")
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
    if ctype == "review_upload":
        return review_upload(cp, payload if isinstance(payload, dict) else {})
    return False, {"error": f"COMMAND_NOT_ALLOWED:{ctype}"}, {}


def collective_tick(cp: Any, token: str) -> dict:
    """Provision the collective-learning config from the fleet and start a detached device-sync when due.
    Never raises, never waits for the sync (collective_provision.py)."""
    try:
        import collective_provision  # noqa: PLC0415
        engine, runtime = cp.roots()
        return collective_provision.tick(runtime, engine,
                                         lambda: _req("GET", "/v1/collective/provision", token=token))
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__}


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
        kb = collective_tick(cp, token)
        if kb:
            extra["collective"] = kb
        try:
            cover = cover_tick(cp, token)
            if cover:
                extra["cover"] = cover
        except Exception:  # noqa: BLE001 -- a cover is cosmetic; never break the report
            pass
        status, blocker, tail = build_status(cp, {**tick_result, **extra})
        status["device_sn"] = sn
        _req("POST", "/v1/report", {"status": status, "blocker": blocker, "status_tail": tail}, token=token)
        extra["fleet"] = "REPORTED" + (f" commands={','.join(done)}" if done else "")
    except Exception as exc:  # noqa: BLE001 -- the channel must never break the heartbeat
        extra["fleet"] = f"ERROR:{type(exc).__name__}"
    return extra
