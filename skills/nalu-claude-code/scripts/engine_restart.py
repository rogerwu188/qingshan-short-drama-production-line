#!/usr/bin/env python3
"""Restart the in-flight episode from S1 on a new engine (line owner rule 2026-11-23).

Owner: 「新规则（适用于近期就几台在产 查问题阶段）：如果进行了重大引擎改动就比如昨晚，这几台设备立即放弃当前这集的进度，
用新引擎重新做这一集，这样不浪费时间」.  setup_host.sh keeps an episode in flight on the engine it started with; after a
major engine change that is the wrong trade, so the maintainer opts a device in explicitly:

* fleet ``update`` with ``{"pin": <sha>, "restart_in_flight": true}`` (fleet_sync.scripted_update), or
* ``engine_restart.py run --pin <sha> --episode <EP> --apply`` (bootstrap for devices whose running fleet_sync
  predates the flag; it detaches and does the whole sequence itself).

Sequence (stdlib only, no model, no network except ``git fetch`` and the engine's own setup):
  1. eligibility: the episode is the current one, not finished / published, its engine does not yet contain the
     major commit (default: the pin), and (episode, pin) was not restarted before (series/ENGINE_RESTARTS.json);
  2. stop: SIGTERM then SIGKILL the episode's Codex runner, reviewer and every process whose command line names the
     episode (paid_stage.sh / nalu_pipeline.py / codex_production.py / final_audience_review.py / codex), with
     their descendants; unrelated processes are never touched;
  3. archive: MOVE (never delete) every per-episode artefact of the engine workflow and the runtime to
     ~/nalu_archive/<EP>_abandoned_<UTC>_<old7>/ with manifest.json; series-level state stays (briefs, identity
     cards / registries, earlier episodes, X2C list, KB).  Files a series registry still points at are copied back
     so the series library stays whole.  The budget ledger log keeps its history: one entry records the abandoned
     attempt under its own key, one resets the episode to 0 so the cap does not count the abandoned spend twice;
  4. engine: setup_host.sh --pin (nothing is in flight any more, so the checkout is not deferred);
  5. start: ``codex_production.py start --episode <EP>`` of the NEW engine with a restart brief (S1, fresh thread),
     a STATUS.md line「<EP> restarted on <sha7> (owner rule: restart on major engine change)」.
Prints ONE line ``ENGINE_RESTART: {...}`` (CLI).  Never prints keys; never touches ~/.openclaw.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "nalu.engine_restart.v1"
RECORD_NAME = "ENGINE_RESTARTS.json"
REASON = "owner rule 2026-11-23: restart on major engine change"
DONE_STATES = ("FINAL_CUT_READY", "SERIES_DONE")
SHA_RE = re.compile(r"[0-9a-f]{40}")
EP_RE = re.compile(r"[A-Z]{1,3}\d{2,4}")
#: process markers: a process is the episode's when its command line has one of these AND names the episode
PROC_MARKERS = ("paid_stage.sh", "nalu_pipeline.py", "codex_production.py", "final_audience_review.py", "codex",
                "post_generation_qa_runner.py", "video_q2_builder.py", "q2_auto_redo.py")
#: never descended into / never moved (series-level, secrets, our own state)
SKIP_DIRS = {".git", ".qingshan-venv", "node_modules", "__pycache__", "credentials", "briefs", "series",
             "voice_refs", "character_sources", "engine_patches", "studio_assets"}
SCAN_DEPTH = 4


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def roots() -> tuple[Path, Path]:
    engine = Path(os.environ.get("NALU_ENGINE_ROOT") or "~/nalu_engine").expanduser()
    runtime = Path(os.environ.get("NALU_RUNTIME_ROOT") or "~/nalu_runtime").expanduser()
    return engine, runtime


def work_root(engine: Path) -> Path:
    return Path(os.environ.get("NALU_WORK_ROOT") or engine / "workflow" / "nalu").expanduser()


def archive_base() -> Path:
    return Path(os.environ.get("NALU_ARCHIVE_ROOT") or "~/nalu_archive").expanduser()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def git(engine: Path, *args: str, timeout: int = 120) -> tuple[int, str]:
    try:
        done = subprocess.run(["git", "-C", str(engine), *args], capture_output=True, text=True, timeout=timeout)
        return done.returncode, (done.stdout or "").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, f"{type(exc).__name__}"


def engine_sha(engine: Path) -> str:
    rc, out = git(engine, "rev-parse", "HEAD")
    return out if rc == 0 and SHA_RE.fullmatch(out) else ""


def contains(engine: Path, head: str, commit: str) -> bool:
    """True when ``head`` already contains ``commit`` (the episode already runs on an engine with the change)."""
    if not head or not commit:
        return False
    if head == commit:
        return True
    rc, _ = git(engine, "merge-base", "--is-ancestor", commit, head)
    return rc == 0


# ------------------------------------------------------------------------------------------------ state
def record_path(runtime: Path) -> Path:
    return runtime / "series" / RECORD_NAME


def load_record(runtime: Path) -> dict[str, Any]:
    data = read_json(record_path(runtime))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        data = {"schema": SCHEMA, "restarts": []}
    data.setdefault("restarts", [])
    return data


def find_restart(runtime: Path, episode: str, pin: str) -> dict[str, Any] | None:
    for row in load_record(runtime)["restarts"]:
        if row.get("episode") == episode and row.get("pin") == pin:
            return row
    return None


def save_restart(runtime: Path, row: dict[str, Any]) -> None:
    data = load_record(runtime)
    data["restarts"] = [r for r in data["restarts"]
                        if not (r.get("episode") == row["episode"] and r.get("pin") == row["pin"])] + [row]
    write_json(record_path(runtime), data)


def current_episode(runtime: Path) -> str:
    try:
        ep = (runtime / "series" / "CURRENT_EPISODE").read_text(encoding="utf-8").strip()
    except OSError:
        ep = ""
    if ep:
        return ep
    eps = [p.parent.name for p in (runtime / "claude_code").glob("*/session.json")]
    return max(eps, key=lambda e: (int(re.sub(r"\D", "", e) or 0), e)) if eps else ""


STATUS_RE = re.compile(r"NALU_STATUS:\s*(\{.*\})")


def last_state(runtime: Path, episode: str) -> str:
    """The episode's last NALU_STATUS state (claude_production.parse_log semantics), or ''."""
    session = read_json(runtime / "claude_code" / episode / "session.json")
    log = Path(str(session.get("log") or "")) if isinstance(session, dict) else Path("")
    text = ""
    try:
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") == "result":
                text = str(ev.get("result") or "")
            elif ev.get("type") == "item.completed" and (ev.get("item") or {}).get("type") == "agent_message":
                text = str((ev.get("item") or {}).get("text") or "") or text
    except OSError:
        return ""
    found = STATUS_RE.findall(text)
    if not found:
        return ""
    try:
        return str(json.loads(found[-1]).get("state") or "")
    except ValueError:
        return ""


def published(engine: Path, episode: str) -> bool:
    """The episode already went out to X2C (publish_x2c_matrix sent list).  Unknown -> False."""
    scripts = engine / "skills" / "nalu-claude-code" / "scripts"
    try:
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import publish_x2c_matrix as mx  # noqa: PLC0415
        return episode in mx.sent_episodes()
    except Exception:  # noqa: BLE001 -- no publisher state: nothing was sent
        return False


def eligibility(engine: Path, runtime: Path, episode: str, pin: str, major: str = "") -> dict[str, Any]:
    """{"eligible": bool, "reason": ...}: restart only the current, unfinished episode of an engine without the
    major change, at most once per (episode, pin)."""
    head = engine_sha(engine)
    major = major or pin
    out = {"episode": episode, "pin": pin, "major": major, "engine": head}
    if not SHA_RE.fullmatch(pin or ""):
        return {**out, "eligible": False, "reason": "BAD_PIN"}
    if not EP_RE.fullmatch(episode or ""):
        return {**out, "eligible": False, "reason": "NO_EPISODE"}
    if episode != current_episode(runtime):
        return {**out, "eligible": False, "reason": f"NOT_CURRENT_EPISODE:{current_episode(runtime)}"}
    prior = find_restart(runtime, episode, pin)
    if prior and prior.get("phase") != "STOPPING":  # STOPPING = interrupted before anything moved: retry
        return {**out, "eligible": False, "reason": f"ALREADY_RESTARTED:{prior.get('phase')}", "prior": prior}
    if not (runtime / "claude_code" / episode / "session.json").is_file():
        return {**out, "eligible": False, "reason": "NO_SESSION"}
    state = last_state(runtime, episode)
    out["state"] = state
    if state in DONE_STATES or (runtime / "series" / "SERIES_DONE").exists():
        return {**out, "eligible": False, "reason": f"EPISODE_DONE:{state or 'SERIES_DONE'}"}
    if published(engine, episode):
        return {**out, "eligible": False, "reason": "EPISODE_PUBLISHED"}
    if not head:
        return {**out, "eligible": False, "reason": "ENGINE_NOT_A_CHECKOUT"}
    git(engine, "fetch", "-q", "origin", timeout=300)
    if git(engine, "cat-file", "-e", f"{major}^{{commit}}")[0] != 0:
        return {**out, "eligible": False, "reason": "MAJOR_COMMIT_UNKNOWN"}
    if contains(engine, head, major):
        return {**out, "eligible": False, "reason": "ENGINE_ALREADY_HAS_THE_CHANGE"}
    return {**out, "eligible": True, "reason": "OK"}


# ------------------------------------------------------------------------------------------------ stop
def _proc_table() -> dict[int, tuple[int, str]]:
    """pid -> (ppid, command line) from /proc (Linux); {} elsewhere."""
    table: dict[int, tuple[int, str]] = {}
    for d in Path("/proc").glob("[0-9]*"):
        try:
            cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
            stat = (d / "stat").read_text()
            ppid = int(stat.rsplit(") ", 1)[1].split()[1])
            table[int(d.name)] = (ppid, cmd)
        except (OSError, ValueError, IndexError):
            continue
    return table


def episode_processes(episode: str, extra_pids: list[int], table: dict[int, tuple[int, str]] | None = None
                      ) -> list[int]:
    """The episode's processes and their descendants; never this process or its ancestors."""
    table = _proc_table() if table is None else table
    token = re.compile(rf"(?<![A-Za-z0-9]){re.escape(episode)}(?!\d)")
    roots_ = {p for p in extra_pids if p in table}
    for pid, (_, cmd) in table.items():
        if token.search(cmd) and any(m in cmd for m in PROC_MARKERS) and "engine_restart" not in cmd:
            roots_.add(pid)
    children: dict[int, list[int]] = {}
    for pid, (ppid, _) in table.items():
        children.setdefault(ppid, []).append(pid)
    found, stack = set(), list(roots_)
    while stack:
        pid = stack.pop()
        if pid in found:
            continue
        found.add(pid)
        stack.extend(children.get(pid, []))
    protected, pid = set(), os.getpid()
    while pid and pid not in protected:
        protected.add(pid)
        pid = table.get(pid, (0, ""))[0]
    return sorted(found - protected - {1})


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        return not Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].startswith("Z")
    except (OSError, IndexError):
        return True


def stop_episode(runtime: Path, episode: str, *, grace_s: float = 20.0,
                 kill: Callable[[int, int], None] = os.kill) -> dict[str, Any]:
    run = runtime / "claude_code" / episode
    pids = []
    for path in (run / "session.json", run / "final_reviewer" / "reviewer.json"):
        pid = (read_json(path) or {}).get("pid") if path.is_file() else None
        if isinstance(pid, int) and pid > 1:
            pids.append(pid)
    table = _proc_table()
    targets = episode_processes(episode, pids, table)
    rows = [{"pid": p, "cmd": table.get(p, (0, ""))[1][:160]} for p in targets]
    for pid in targets:
        try:
            kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + grace_s
    while time.time() < deadline and any(_alive(p) for p in targets):
        time.sleep(1)
    killed = []
    for pid in targets:
        if _alive(pid):
            try:
                kill(pid, signal.SIGKILL)
                killed.append(pid)
            except OSError:
                pass
    return {"stopped": rows, "sigkill": killed}


# ------------------------------------------------------------------------------------------------ archive
def _matches(name: str, episode: str) -> bool:
    return bool(re.match(rf"^{re.escape(episode)}(?:$|[._-])", name))


def _other_episode_dir(name: str, episode: str) -> bool:
    return bool(EP_RE.fullmatch(name)) and name != episode


def tracked_paths(engine: Path) -> set[Path]:
    """Engine files under workflow/ that git tracks, and their parent directories: never moved (moving them would
    leave the engine checkout modified)."""
    rc, out = git(engine, "ls-files", "workflow")
    out_set: set[Path] = set()
    for rel in out.splitlines() if rc == 0 else []:
        p = engine / rel
        out_set.add(p)
        out_set.update(q for q in p.parents if engine in q.parents)
    return out_set


def select_paths(engine: Path, runtime: Path, episode: str) -> list[Path]:
    """Every per-episode artefact under the engine workflow and the runtime (bounded walk, no symlinks followed).

    A name is the episode's when it is ``<EP>`` or starts with ``<EP>`` + one of ``._-``.  Earlier episodes'
    directories are never entered; series-level directories (SKIP_DIRS) are never entered or moved; files directly
    in ``<runtime>/runtime`` (series registries, the E01 asset-library seed) and the budget ledger stay."""
    found: list[Path] = []
    rt = runtime / "runtime"
    tracked = tracked_paths(engine)

    def walk(d: Path, depth: int) -> None:
        try:
            entries = sorted(d.iterdir())
        except OSError:
            return
        for p in entries:
            if p.name in SKIP_DIRS or p.is_symlink():
                continue
            if _matches(p.name, episode):
                if p.is_file() and p.parent in (runtime, rt):
                    continue  # series registries / seeds live here
                if p in tracked:
                    continue  # part of the engine checkout (e.g. workflow/time_ledger/E17_time_ledger.json)
                found.append(p)
                continue
            if p.is_dir() and depth < SCAN_DEPTH and not _other_episode_dir(p.name, episode):
                walk(p, depth + 1)

    for base in (engine / "workflow", work_root(engine), runtime):
        if base.is_dir():
            walk(base, 1)
    uniq: list[Path] = []
    for p in sorted(set(found), key=lambda x: (len(x.parts), str(x))):
        if not any(q in p.parents for q in uniq):
            uniq.append(p)
    return uniq


def kept_briefs(runtime: Path, episode: str) -> list[Path]:
    return sorted(p for p in (runtime / "briefs").glob(f"{episode}_*") if p.is_file())


def _strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def registry_files(runtime: Path) -> list[Path]:
    rt = runtime / "runtime"
    files = sorted(rt.glob("*.json")) + [runtime / "qingshan.json"]
    for scope in (read_json(rt / "series_scopes.json") or {}).get("scopes", {}).values() \
            if isinstance(read_json(rt / "series_scopes.json"), dict) else []:
        for v in (scope or {}).values() if isinstance(scope, dict) else []:
            if isinstance(v, str) and v.endswith(".json"):
                p = Path(v).expanduser()
                files.append(p if p.is_absolute() else runtime / p)
    return [p for p in dict.fromkeys(files) if p.is_file() and p.stat().st_size < 64 * 1024 * 1024]


def pinned_files(runtime: Path, moved: list[Path]) -> list[Path]:
    """Files inside a to-be-moved path that a series registry still references (absolute path strings)."""
    pinned: set[Path] = set()
    for reg in registry_files(runtime):
        data = read_json(reg)
        for s in _strings(data):
            if not s.startswith("/") or len(s) > 1024:
                continue
            p = Path(s)
            if any(p == m or m in p.parents for m in moved) and p.is_file():
                pinned.add(p)
    return sorted(pinned)


def _size(p: Path) -> int:
    try:
        if p.is_file():
            return p.stat().st_size
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())
    except OSError:
        return -1


def _dest(archive: Path, engine: Path, runtime: Path, src: Path) -> Path:
    for label, base in (("engine", engine), ("runtime", runtime)):
        try:
            return archive / label / src.relative_to(base)
        except ValueError:
            continue
    return archive / "other" / src.name


def ledger_entries(runtime: Path, episode: str, archive: Path, old_sha: str, pin: str) -> dict[str, Any]:
    """Keep the ledger history: the abandoned attempt under its own key (fleet totals stay true), then a reset row
    for the episode (the redo starts at 0; the spend scan itself reads the moved stores, so nothing double counts)."""
    path = runtime / "runtime" / "budget" / "ledger.json"
    ledger = read_json(path)
    if not isinstance(ledger, dict) or not isinstance(ledger.get("entries"), list):
        return {"status": "NO_LEDGER"}
    rows = [r for r in ledger["entries"] if isinstance(r, dict) and r.get("episode") == episode]
    old = rows[-1].get("recorded_total_credits") if rows else None
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    key = f"{episode}_ABANDONED_{archive.name.split('_abandoned_', 1)[-1]}"
    cap = ledger.get("cap_credits_per_episode")
    common = {"recorded_at_utc": stamp, "cap_credits": cap, "planned_credits": 0, "accounting_complete": True,
              "reservation_result": None, "failures": [], "balance_snapshot": None, "network_calls_made": 0,
              "engine_restart": {"archive": str(archive), "old_engine": old_sha, "new_pin": pin, "reason": REASON}}
    ledger["entries"].append({**common, "episode": key, "mode": "ENGINE_RESTART_ARCHIVED", "status": "ARCHIVED",
                              "recorded_total_credits": old if isinstance(old, (int, float)) else 0,
                              "projected_total_credits": old, "headroom_credits": None})
    ledger["entries"].append({**common, "episode": episode, "mode": "ENGINE_RESTART_RESET", "status": "RESET",
                              "recorded_total_credits": 0, "projected_total_credits": 0, "headroom_credits": cap})
    ledger["updated_at_utc"] = stamp
    shutil.copy2(path, archive / "ledger.json.before_restart")
    write_json(path, ledger)
    return {"status": "OK", "abandoned_key": key, "abandoned_credits": old}


def archive_episode(engine: Path, runtime: Path, episode: str, old_sha: str, pin: str,
                    device_sn: str = "", stop: dict | None = None) -> dict[str, Any]:
    stamp = utc_stamp()
    archive = archive_base() / f"{episode}_abandoned_{stamp}_{(old_sha or 'unknown')[:7]}"
    archive.mkdir(parents=True, exist_ok=False)
    paths = select_paths(engine, runtime, episode)
    pinned = pinned_files(runtime, paths)
    manifest: dict[str, Any] = {
        "schema": SCHEMA, "episode": episode, "device_sn": device_sn, "old_engine": old_sha, "new_pin": pin,
        "archived_at": stamp, "reason": REASON, "engine_root": str(engine), "runtime_root": str(runtime),
        "stopped": stop or {}, "moved": [], "restored_for_series_registries": [], "kept_inputs": [],
        "restore_hint": "move each 'dst' back to its 'src' (after stopping the redo) to undo"}
    write_json(archive / "manifest.json", manifest)
    for brief in kept_briefs(runtime, episode):  # inputs of the episode: stay in place, a copy goes with the archive
        dst = archive / "runtime" / brief.relative_to(runtime)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(brief, dst)
        manifest["kept_inputs"].append(str(brief))
    for src in paths:
        dst = _dest(archive, engine, runtime, src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        row = {"src": str(src), "dst": str(dst), "kind": "dir" if src.is_dir() else "file", "bytes": _size(src)}
        try:
            shutil.move(str(src), str(dst))
            row["status"] = "MOVED"
        except OSError as exc:
            row["status"] = f"MOVE_FAILED:{type(exc).__name__}"
        manifest["moved"].append(row)
        write_json(archive / "manifest.json", manifest)
    for p in pinned:
        dst = _dest(archive, engine, runtime, p)
        if dst.is_file() and not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, p)
            manifest["restored_for_series_registries"].append(str(p))
    manifest["ledger"] = ledger_entries(runtime, episode, archive, old_sha, pin)
    manifest["moved_count"] = sum(1 for r in manifest["moved"] if r["status"] == "MOVED")
    write_json(archive / "manifest.json", manifest)
    return {"archive": str(archive), "moved": manifest["moved_count"],
            "move_failed": [r["src"] for r in manifest["moved"] if r["status"] != "MOVED"],
            "restored": len(manifest["restored_for_series_registries"]), "ledger": manifest["ledger"]}


# ------------------------------------------------------------------------------------------------ start
RESTART_BRIEF = """本集 {ep} 按线主规则（2026-11-23「如果进行了重大引擎改动……这几台设备立即放弃当前这集的进度，用新引擎重新做这一集」）
在新引擎 {new7} 上**从 S1 从头重做**。上一次尝试（旧引擎 {old7}）的全部本集产物、任务、审核、订单回执与流水线状态已原样移到
`{archive}`（只是存档：不要读取、复制或复用其中任何文件、任务 ID 或审核结论；新尝试一切重新生成）。
1. 派单 `{dispatch}` 与生产简报 `{brief}` 保留为本集输入：集号、本剧第几集（episode_display_number）、章节范围、时长、
   语言、X2C 分类、预算等条款不变，不要重写派单。
2. 按 `{skill}` §4 用新引擎的规则重新写本集叙事正典（承接上一集结尾，角色、地点沿用；系列身份牌、音色、前几集都还在原处），
   然后按合同从 S1 开始生产 {ep}。
3. 预算：旧尝试的花费已在账本里单独记为 `{abandoned_key}`，本集新尝试从 0 计，不要为旧尝试补记或冲账。
{original}"""


def restart_brief(engine: Path, runtime: Path, episode: str, archive: Path, old_sha: str, pin: str,
                  abandoned_key: str) -> str:
    original = ""
    try:
        text = (archive / "runtime" / "claude_code" / episode / "start_brief.md").read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    if text:
        original = ("\n上一次开工时的附加说明（仅供参考；其中「写派单」一步已完成、派单保留，不要重写）：\n"
                    + (text if len(text) <= 4000 else text[:4000] + "…"))
    return RESTART_BRIEF.format(
        ep=episode, new7=pin[:7], old7=(old_sha or "unknown")[:7], archive=archive,
        dispatch=runtime / "briefs" / f"{episode}_DISPATCH.md", brief=runtime / "briefs" / f"{episode}_PRODUCTION_BRIEF.json",
        skill=engine / "skills" / "nalu-claude-code" / "SKILL.md", abandoned_key=abandoned_key or f"{episode}_ABANDONED",
        original=original)


def tool_env(engine: Path, runtime: Path) -> dict[str, str]:
    home = Path.home()
    dirs = [str(home / ".local/bin"), str(home / ".npm-global/bin")]
    try:
        dirs += [x for x in (home / ".nalu_tool_path").read_text(encoding="utf-8").strip().split(":") if x]
    except OSError:
        pass
    dirs += sorted((str(p) for p in home.glob(".nvm/versions/node/*/bin")), reverse=True)
    return {**os.environ, "NALU_ENGINE_ROOT": str(engine), "NALU_RUNTIME_ROOT": str(runtime),
            "NALU_WORK_ROOT": str(work_root(engine)),
            "PATH": ":".join([*dirs, os.environ.get("PATH", ""), "/usr/local/bin:/usr/bin:/bin"])}


def status_note(runtime: Path, line: str) -> None:
    path = runtime / "series" / "STATUS.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(f"- {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%MZ')} {line}\n")


def start_fresh(engine: Path, runtime: Path, episode: str, archive: Path, old_sha: str, pin: str,
                abandoned_key: str = "") -> dict[str, Any]:
    """``codex_production.py start`` of the engine now on disk (a subprocess: the new code, not this process')."""
    brief = archive / "RESTART_BRIEF.md"
    brief.write_text(restart_brief(engine, runtime, episode, archive, old_sha, pin, abandoned_key), encoding="utf-8")
    script = engine / "skills" / "nalu-claude-code" / "scripts" / "codex_production.py"
    try:
        done = subprocess.run([sys.executable if Path(sys.executable).name.startswith("python") else "python3",
                               str(script), "start", "--episode", episode, "--brief", str(brief)],
                              cwd=str(engine), capture_output=True, text=True, timeout=900,
                              env=tool_env(engine, runtime))
        out = (done.stdout or "").strip()
        start = out[out.find("{"):] if "{" in out else ""
        result = json.loads(start) if start else {"status": f"NO_OUTPUT:rc={done.returncode}"}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {"status": f"START_ERROR:{type(exc).__name__}"}
    return {k: result.get(k) for k in ("status", "reason", "pid", "log") if k in result}


# ------------------------------------------------------------------------------------------------ setup
def run_setup(engine: Path, runtime: Path, pin: str, scripts: Path | None = None) -> dict[str, Any]:
    """setup_host.sh --pin from a temporary copy of the PIN's scripts (``git archive``), or of ``scripts``."""
    tmp = Path(tempfile.mkdtemp(prefix="nalu_restart_setup_"))
    try:
        if scripts is not None:
            shutil.copytree(scripts, tmp / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
            setup = tmp / "scripts" / "setup_host.sh"
        else:
            tar = tmp / "s.tar"
            rc, _ = git(engine, "archive", "-o", str(tar), pin, "skills/nalu-claude-code/scripts")
            if rc != 0 or subprocess.run(["tar", "-xf", str(tar), "-C", str(tmp)], capture_output=True).returncode:
                return {"setup_status": "ARCHIVE_FAILED"}
            setup = tmp / "skills" / "nalu-claude-code" / "scripts" / "setup_host.sh"
        try:
            done = subprocess.run(["bash", str(setup), "--pin", pin], capture_output=True, text=True, timeout=1800,
                                  env=tool_env(engine, runtime))
            out, rc = done.stdout or "", done.returncode
        except (OSError, subprocess.SubprocessError) as exc:
            out, rc = f"{type(exc).__name__}", -1
        line = next((x for x in reversed(out.splitlines()) if x.startswith("NALU_SETUP: ")), "")
        try:
            st = json.loads(line[len("NALU_SETUP: "):]) if line else {}
        except ValueError:
            st = {}
        return {"setup_rc": rc, "setup_status": st.get("status"), "setup_failed_step": st.get("failed_step"),
                "setup_engine_step": (st.get("steps") or {}).get("engine")}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------------------------------------ sequence
def prepare(engine: Path, runtime: Path, episode: str, pin: str, *, major: str = "", device_sn: str = "",
            grace_s: float = 20.0) -> dict[str, Any]:
    """Eligibility -> stop -> archive.  Returns {"phase": ...}; ARCHIVED means the caller sets up + starts."""
    check = eligibility(engine, runtime, episode, pin, major)
    if not check["eligible"]:
        return {"phase": "SKIPPED", **check}
    old_sha = check["engine"]
    row = {"episode": episode, "pin": pin, "major": check["major"], "old_engine": old_sha, "phase": "STOPPING",
           "at": utc_stamp(), "device_sn": device_sn}
    save_restart(runtime, row)
    stop = stop_episode(runtime, episode, grace_s=grace_s)
    arch = archive_episode(engine, runtime, episode, old_sha, pin, device_sn, stop)
    row.update(phase="ARCHIVED", archive=arch["archive"], stopped=len(stop["stopped"]),
               abandoned_key=(arch.get("ledger") or {}).get("abandoned_key"),
               abandoned_credits=(arch.get("ledger") or {}).get("abandoned_credits"))
    save_restart(runtime, row)
    status_note(runtime, f"{episode} 放弃旧引擎 {old_sha[:7]} 上的进度（线主规则：重大引擎改动后重做本集），"
                         f"本集产物已移到 {arch['archive']}")
    return {"phase": "ARCHIVED", **check, **arch, "stopped": stop}


def finish(engine: Path, runtime: Path, episode: str, pin: str) -> dict[str, Any]:
    """After setup: start the episode fresh on the engine now on disk; record the result (once per (EP, pin))."""
    row = find_restart(runtime, episode, pin) or {}
    if row.get("phase") != "ARCHIVED":
        return {"phase": row.get("phase") or "NOT_PREPARED"}
    head = engine_sha(engine)
    started = start_fresh(engine, runtime, episode, Path(row["archive"]), row.get("old_engine") or "", pin,
                          row.get("abandoned_key") or "")
    ok = started.get("status") in ("STARTED", "ALREADY_RUNNING")
    row.update(phase="STARTED" if ok else "START_FAILED", new_engine=head, start=started, started_at=utc_stamp())
    save_restart(runtime, row)
    if ok:
        status_note(runtime, f"{episode} restarted on {head[:7]} (owner rule: restart on major engine change)"
                    + ("" if head == pin else f" [pin {pin[:7]} not reached]"))
    else:
        status_note(runtime, f"{episode} 重做启动失败（{started.get('status')} {started.get('reason') or ''}），"
                             "系统心跳会接手；存档 " + str(row.get("archive")))
    return {"phase": row["phase"], "new_engine": head, "start": started, "archive": row.get("archive")}


def resume_unfinished(engine: Path, runtime: Path, episode: str, pin: str) -> dict[str, Any] | None:
    """A restart interrupted after the archive (crash, reboot): finish it instead of leaving the episode empty."""
    row = find_restart(runtime, episode, pin)
    if row and row.get("phase") == "ARCHIVED":
        return finish(engine, runtime, episode, pin)
    return None


def _tick_lock(runtime: Path, wait_s: float):
    import fcntl  # noqa: PLC0415
    d = runtime / "claude_code"
    d.mkdir(parents=True, exist_ok=True)
    fh = open(d / ".tick.lock", "w")  # noqa: SIM115
    deadline = time.time() + wait_s
    while True:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fh
        except OSError:
            if time.time() > deadline:
                fh.close()
                return None
            time.sleep(5)


def run_all(pin: str, episode: str, *, major: str = "", device_sn: str = "") -> dict[str, Any]:
    """The bootstrap sequence (CLI ``run --apply``): lock -> prepare -> setup (the PIN's scripts) -> start."""
    engine, runtime = roots()
    lock = _tick_lock(runtime, 900)
    if lock is None:
        return {"phase": "SKIPPED", "reason": "TICK_LOCK_BUSY"}
    try:
        again = resume_unfinished(engine, runtime, episode, pin)
        if again is not None:
            return again
        prep = prepare(engine, runtime, episode, pin, major=major, device_sn=device_sn)
        if prep["phase"] != "ARCHIVED":
            return prep
        git(engine, "fetch", "-q", "origin", timeout=300)
        setup = run_setup(engine, runtime, pin)
        fin = finish(engine, runtime, episode, pin)
        return {**fin, "old_engine": prep.get("engine"), "moved": prep.get("moved"),
                "stopped": len((prep.get("stopped") or {}).get("stopped") or []), **setup}
    finally:
        lock.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="restart the episode (dry run unless --apply)")
    r.add_argument("--pin", required=True)
    r.add_argument("--episode", default="")
    r.add_argument("--major", default="", help="restart only when the engine lacks this commit (default: the pin)")
    r.add_argument("--device-sn", default="")
    r.add_argument("--apply", action="store_true")
    r.add_argument("--foreground", action="store_true", help="do not detach (the detached worker uses this)")
    a = ap.parse_args()
    engine, runtime = roots()
    episode = a.episode or current_episode(runtime)
    if not a.apply:
        check = eligibility(engine, runtime, episode, a.pin, a.major)
        plan = [str(p) for p in select_paths(engine, runtime, episode)] if EP_RE.fullmatch(episode or "") else []
        print("ENGINE_RESTART: " + json.dumps({"mode": "DRY_RUN", **check, "would_move": plan[:80],
                                                 "would_move_count": len(plan)}, ensure_ascii=False))
        return 0
    if not a.foreground:
        # detached: an agent shell or exec timeout must not cut the setup (venv rebuild) or the start in half
        log = runtime / "series" / f"engine_restart_{episode}_{utc_stamp()}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        copy = Path(tempfile.mkdtemp(prefix="nalu_restart_")) / "engine_restart.py"
        shutil.copy2(Path(__file__).resolve(), copy)  # the engine checkout below may replace this file
        argv = [sys.executable, str(copy), "run", "--pin", a.pin, "--episode", episode, "--apply", "--foreground"]
        if a.major:
            argv += ["--major", a.major]
        if a.device_sn:
            argv += ["--device-sn", a.device_sn]
        with open(log, "a", encoding="utf-8") as fh:
            proc = subprocess.Popen(argv, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    start_new_session=True, env=tool_env(engine, runtime))
        print("ENGINE_RESTART: " + json.dumps({"mode": "LAUNCHED", "episode": episode, "pin": a.pin,
                                                 "pid": proc.pid, "log": str(log)}, ensure_ascii=False))
        return 0
    out = run_all(a.pin, episode, major=a.major, device_sn=a.device_sn)
    print("ENGINE_RESTART: " + json.dumps(out, ensure_ascii=False, default=str))
    return 0 if out.get("phase") in ("STARTED", "SKIPPED") else 3


if __name__ == "__main__":
    sys.exit(main())
