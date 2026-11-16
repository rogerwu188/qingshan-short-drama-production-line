#!/usr/bin/env python3
"""paid_run_status.py — what the last paid run left behind, and whether anyone needs to think about it.

WHY THIS EXISTS (Codex cost, device …1144 E08/E09, 2026-11-16)
Per episode Codex made ~650 model round trips; about half were a wait loop around S6: `paid_stage.sh E08 S6 S6`
re-run ~50 times with `sleep 240`, ~80 `pgrep`/`ps | rg` probes of the pipeline's children and up to 142 reads of
the run log (single outputs up to 321 KB).  Every one of those round trips re-sent the whole conversation.  None
of them needed judgement: the provider was still rendering.

This module is the cheap, free, stdlib-only answer to "is there anything to do?":

  record  --episode E08 --from S6 --until S6 --rc 1 --log <file> --started <epoch>
          (paid_stage.sh calls it after every stage run) classifies the run, writes
          ``$NALU_RUNTIME_ROOT/runtime/paid_runs/<EP>/last.json`` and prints a short summary ending in ONE line:
              NEXT: END_TURN_WAIT_FOR_TICK (<reason>)   nothing actionable -- report WAITING_REMOTE and end the turn
              NEXT: ACT (<reason>)                      a stage passed, failed or needs a review/order
  status  --episode E08   (``paid_stage.sh --status E08``) a few lines on in-flight work: the paid lock holder,
          the last run's verdict, each stage's status, the newest pipeline log line.  Replaces ps/pgrep/tail loops.

The system tick (skills/nalu-claude-code/scripts/codex_production.py, every 3 min, no model) uses
:func:`tick_decision` while Codex sits at WAITING_REMOTE: in flight -> nothing; still remote-pending -> it re-runs
the SAME ``paid_stage.sh <EP> <FROM> <UNTIL>`` itself (the identical command Codex used to re-run after a
sleep: same order, budget cap, durable store, D-46 -- nothing is bypassed); actionable -> it resumes Codex.

Never reads secrets, never touches a provider, never writes anything except ``paid_runs/<EP>/last.json``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STAGE_IDS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")
OK = {"PASS", "SKIPPED"}
#: Blockers that only mean "the provider is still working" (or a zero-cost provider outage the submitter retries
#: by itself).  A stage whose EVERY blocker is one of these needs no judgement: the same command is simply re-run.
#: interval_s = the wait the contract prescribed between re-runs; max_reruns = how many unattended re-runs before
#: the producer is woken to judge (VIDEO: ~6 h of rendering/queueing; image outage: the contract's 6 tries).
REMOTE_WAIT: dict[str, dict[str, int]] = {
    "VIDEO_NOT_ALL_COMPLETED": {"interval_s": 240, "max_reruns": 90},
    "HOPSAPI_IMAGE_PROVIDER_OUTAGE": {"interval_s": 600, "max_reruns": 6},
}
WAIT, ACT = "WAIT", "ACT"
NEXT_WAIT = "NEXT: END_TURN_WAIT_FOR_TICK"
NEXT_ACT = "NEXT: ACT"
SUMMARY_BLOCKERS = 6
LINE_MAX = 220


def runtime_root(explicit: str | None = None) -> Path:
    root = explicit or os.environ.get("NALU_RUNTIME_ROOT") or os.environ.get("RUNTIME_ROOT") or "~/nalu_runtime"
    return Path(root).expanduser()


def runs_dir(runtime: Path, episode: str) -> Path:
    return runtime / "runtime" / "paid_runs" / episode


def state_path(runtime: Path, episode: str) -> Path:
    return runtime / "runtime" / "pipeline_state" / f"{episode}.json"


def lock_path(runtime: Path, episode: str) -> Path:
    """The same mkdir lock paid_stage.sh takes (one paid run per episode)."""
    return runtime / "runtime" / f".paid_{episode}.lock"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    try:  # an exited, not yet reaped process is not a live run
        return not Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].startswith("Z")
    except (OSError, IndexError):
        return True


def lock_holder(runtime: Path, episode: str) -> dict[str, Any] | None:
    """The live paid run of ``episode`` (pid, age in seconds), or None."""
    lock = lock_path(runtime, episode)
    try:
        pid = int((lock / "pid").read_text().strip())
    except (OSError, ValueError):
        return None
    if not _alive(pid):
        return None
    try:
        age = time.time() - (lock / "pid").stat().st_mtime
    except OSError:
        age = 0.0
    return {"pid": pid, "age_s": int(age)}


def blocker_code(blocker: Any) -> str:
    """``wave3:VIDEO_NOT_ALL_COMPLETED`` / ``VIDEO_NOT_ALL_COMPLETED:detail`` -> ``VIDEO_NOT_ALL_COMPLETED``."""
    text = re.sub(r"^(?:wave\d+:)+", "", str(blocker or "").strip())
    return text.split(":", 1)[0].strip()


def classify(state: dict[str, Any], from_stage: str, until_stage: str) -> dict[str, Any]:
    """WAIT when the first stage of FROM..UNTIL that is not PASS/SKIPPED is BLOCKED on remote work only."""
    try:
        selected = STAGE_IDS[STAGE_IDS.index(from_stage): STAGE_IDS.index(until_stage) + 1]
    except ValueError:
        return {"verdict": ACT, "reason": f"STAGE_RANGE_UNKNOWN:{from_stage}..{until_stage}"}
    stages = state.get("stages") if isinstance(state.get("stages"), dict) else {}
    for sid in selected:
        row = stages.get(sid) if isinstance(stages.get(sid), dict) else {}
        status = str(row.get("status") or "NOT_RUN")
        if status in OK:
            continue
        blockers = [str(b) for b in row.get("blockers") or []]
        out = {"stage": sid, "status": status, "blockers": blockers[:SUMMARY_BLOCKERS]}
        codes = {blocker_code(b) for b in blockers}
        if status == "BLOCKED" and codes and codes <= set(REMOTE_WAIT):
            return {**out, "verdict": WAIT, "reason": "REMOTE_PENDING:" + ",".join(sorted(codes)),
                    "interval_s": max(REMOTE_WAIT[c]["interval_s"] for c in codes),
                    "max_reruns": min(REMOTE_WAIT[c]["max_reruns"] for c in codes)}
        return {**out, "verdict": ACT, "reason": f"{sid}_{status}"}
    return {"verdict": ACT, "reason": f"STAGES_PASS:{from_stage}..{until_stage}", "stage": until_stage,
            "status": "PASS"}


def record(runtime: Path, episode: str, from_stage: str, until_stage: str, rc: int, log: str,
           started: float) -> dict[str, Any]:
    st_path = state_path(runtime, episode)
    state = _read_json(st_path)
    try:
        fresh = st_path.stat().st_mtime >= started - 1
    except OSError:
        fresh = False
    verdict = classify(state, from_stage, until_stage) if fresh else \
        {"verdict": ACT, "reason": "PIPELINE_STATE_NOT_UPDATED_BY_THIS_RUN"}
    rec = {"schema": "nalu.paid_run_record.v1", "episode": episode, "from": from_stage, "until": until_stage,
           "exit_code": rc, "log": log, "started_at": started, "finished_at": time.time(),
           "finished_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **verdict}
    d = runs_dir(runtime, episode)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "last.json.tmp"
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(d / "last.json")
    return rec


def last_record(runtime: Path, episode: str) -> dict[str, Any]:
    return _read_json(runs_dir(runtime, episode) / "last.json")


def next_line(rec: dict[str, Any]) -> str:
    if rec.get("verdict") == WAIT:
        return f"{NEXT_WAIT} ({rec.get('reason')}; the system tick re-runs {rec.get('from')}..{rec.get('until')} " \
               "and resumes you when something needs judgement -- report WAITING_REMOTE now)"
    return f"{NEXT_ACT} ({rec.get('reason')})"


def _clip(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= LINE_MAX else text[:LINE_MAX - 3] + "..."


def _newest_pipeline_log(runtime: Path, episode: str) -> tuple[Path, float] | None:
    logs = runtime / "runtime" / "pipeline_logs" / episode
    try:
        runs = [p for p in logs.glob("run_*.log") if p.is_file()]
    except OSError:
        return None
    if not runs:
        return None
    newest = max(runs, key=lambda p: p.stat().st_mtime)
    return newest, newest.stat().st_mtime


def _last_line(path: Path) -> str:
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 4096))
            lines = [ln for ln in fh.read().decode("utf-8", "replace").splitlines() if ln.strip()]
    except OSError:
        return ""
    return lines[-1] if lines else ""


def status_lines(runtime: Path, episode: str) -> list[str]:
    """At most ~12 short lines: what is in flight, how the last paid run ended, where each stage stands."""
    out: list[str] = []
    holder = lock_holder(runtime, episode)
    out.append(f"paid run: ACTIVE pid {holder['pid']} for {holder['age_s'] // 60} min" if holder
               else "paid run: none active")
    rec = last_record(runtime, episode)
    if rec:
        out.append(_clip(f"last paid run: {rec.get('from')}..{rec.get('until')} rc={rec.get('exit_code')} "
                         f"finished {rec.get('finished_at_utc')} verdict={rec.get('verdict')} ({rec.get('reason')})"))
        out.append(_clip(f"last paid run log: {rec.get('log')}"))
    state = _read_json(state_path(runtime, episode))
    stages = state.get("stages") if isinstance(state.get("stages"), dict) else {}
    if stages:
        out.append("stages: " + " · ".join(f"{sid} {(stages.get(sid) or {}).get('status') or 'NOT_RUN'}"
                                           for sid in STAGE_IDS))
        for sid in STAGE_IDS:
            row = stages.get(sid) or {}
            if row.get("status") not in OK and row.get("blockers"):
                out.append(_clip(f"{sid} blockers: " + ", ".join(str(b) for b in row["blockers"][:SUMMARY_BLOCKERS])))
                details = row.get("details") if isinstance(row.get("details"), dict) else {}
                if details.get("remote_status_counts"):
                    out.append(_clip(f"{sid} remote: {json.dumps(details['remote_status_counts'], ensure_ascii=False)}"))
                if details.get("missing_videos"):
                    out.append(_clip(f"{sid} missing videos: {len(details['missing_videos'])}"))
                break
    else:
        out.append(f"stages: no pipeline state yet ({state_path(runtime, episode)})")
    newest = _newest_pipeline_log(runtime, episode)
    if newest:
        path, mtime = newest
        out.append(_clip(f"pipeline log {path.name} (written {int(time.time() - mtime)} s ago): {_last_line(path)}"))
    if holder or (newest and time.time() - newest[1] < 120):
        out.append(f"{NEXT_WAIT} (work in flight; do not poll, the system tick follows it)")
    elif rec:
        out.append(next_line(rec))
    return out


def tick_decision(runtime: Path, episode: str, *, since: float | None, reruns_done: int,
                  now: float | None = None) -> dict[str, Any]:
    """What the system tick does for an episode Codex left at WAITING_REMOTE.

    IN_FLIGHT  a paid run holds the lock: nothing to do.
    NO_RECORD  no paid run recorded since ``since`` (Codex's turn start): the old behaviour (resume Codex).
    BACKOFF    remote work pending, re-run not due yet.
    RERUN      remote work pending and due: re-run ``paid_stage.sh <EP> <from> <until>`` (``from``/``until``).
    RESUME     actionable (``reason``), or the unattended re-run cap is reached: wake Codex.
    """
    now = time.time() if now is None else now
    holder = lock_holder(runtime, episode)
    if holder:
        return {"action": "IN_FLIGHT", **holder}
    rec = last_record(runtime, episode)
    if not rec or (since is not None and float(rec.get("finished_at") or 0) < since):
        return {"action": "NO_RECORD"}
    if rec.get("verdict") != WAIT:
        return {"action": "RESUME", "reason": rec.get("reason"), "record": rec}
    if reruns_done >= int(rec.get("max_reruns") or 0):
        return {"action": "RESUME", "reason": f"REMOTE_WAIT_CAP:{reruns_done}_RERUNS:{rec.get('reason')}",
                "record": rec}
    due = float(rec.get("finished_at") or 0) + int(rec.get("interval_s") or 240)
    if now < due:
        return {"action": "BACKOFF", "due_in_s": int(due - now), "reason": rec.get("reason")}
    return {"action": "RERUN", "from": rec.get("from"), "until": rec.get("until"), "reason": rec.get("reason")}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runtime-root", default=None)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--episode", required=True)
    r.add_argument("--from", dest="from_stage", required=True)
    r.add_argument("--until", required=True)
    r.add_argument("--rc", type=int, required=True)
    r.add_argument("--log", default="")
    r.add_argument("--started", type=float, required=True)
    s = sub.add_parser("status")
    s.add_argument("--episode", required=True)
    a = ap.parse_args(argv)
    runtime = runtime_root(a.runtime_root)
    if a.cmd == "record":
        rec = record(runtime, a.episode, a.from_stage, a.until, a.rc, a.log, a.started)
        if rec.get("stage"):
            print(_clip(f"paid_stage: {rec['stage']} {rec.get('status')}"
                        + (f" blockers: {', '.join(rec.get('blockers') or [])}" if rec.get("blockers") else "")))
        print(next_line(rec))
        return 0
    for line in status_lines(runtime, a.episode):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
