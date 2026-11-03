#!/usr/bin/env python3
"""throughput_baseline_gate.py — measure one episode's wall clock from its orchestrator run logs and
fail when it exceeds the budget in configs/THROUGHPUT_BASELINE_V1.json.

Data: ``pipeline_logs/<EP>/run_*.log`` only (every orchestrator run writes `[UTC] $ cmd`,
`[UTC]   -> exit=N`, and `[UTC]    Sx => STATUS blockers: ... [Ns, cum Ms]` lines).  The optional
TIME_LEDGER.jsonl is read for cross-checking only.  Nothing here reads credentials, POSTs, or
changes any production state.

Every second between the first run start and the last run end is assigned to exactly one bucket
(see the config's ``measurement.buckets``); waiting time is never excluded from the total.

    throughput_baseline_gate.py --episode E12 --logs-dir <dir> --baseline <json> [--ledger <jsonl>]
                                [--report <out.json>] [--enforce]

Exit codes: 0 within budget (or --enforce not given), 1 over budget, 2 bad input / no runs.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA = "qingshan.throughput_measurement.v1"
TS = re.compile(r"^\[(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)\] ?(.*)$")
STAGE_RESULT = re.compile(r"\s*(S\d)\s+=>\s+(\S+)\s*(?:blockers:\s*(.*?))?\s*\[(\d+)s")
STAGE_HEADER = re.compile(r"^-- (S\d)\b")
HUMAN_MARKERS = ("PAID_STEPS_DISABLED", "DRY_PLANNED", "PAID_AUTHORITY", "AWAITING_ROGER", "OWNER_DECISION",
                 "BUDGET", "CAP_", "HARD_STOP", "ORDER_", "NOT_SUBMITTED")
RENDER_MARKERS = ("NOT_ALL_COMPLETED", "REMOTE_TASKS_RUNNING")
BUCKETS = ("HUMAN_AUTH_WAIT", "PROVIDER_RENDER_WAIT", "PROVIDER_SUBMIT", "PROVIDER_POLL", "CC_REVIEW_WAIT",
           "CC_FIX_WAIT", "PIPELINE_COMPUTE", "RUN_OVERHEAD", "UNATTRIBUTED_IDLE")


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def classify_cmd(cmd: str) -> str:
    if "poll_giggle_submit_report" in cmd:
        return "PROVIDER_POLL"
    if "submit_giggle" in cmd or re.search(r"/submit_[a-z_]+\.py", cmd) or ("bgm.py generate" in cmd and "--paid" in cmd) \
            or ("nalu_selective_bgm.py" in cmd and " generate " in cmd and "--paid" in cmd):
        return "PROVIDER_SUBMIT"
    return "PIPELINE_COMPUTE"


def gap_bucket(status: str | None, blockers: str | None) -> str:
    st, bl = status or "", blockers or ""
    text = f"{st} {bl}"
    if st == "REVIEW_REQUIRED":
        return "CC_REVIEW_WAIT"
    if any(k in text for k in RENDER_MARKERS):
        return "PROVIDER_RENDER_WAIT"
    if st in ("DRY_PLANNED", "AWAITING_ROGER_APPROVAL") or any(k in text for k in HUMAN_MARKERS):
        return "HUMAN_AUTH_WAIT"
    if st == "BLOCKED":
        return "CC_FIX_WAIT"
    return "UNATTRIBUTED_IDLE"


def parse_run(path: str) -> dict[str, Any] | None:
    run: dict[str, Any] = {"path": path, "start": None, "end": None, "cmds": [], "stages": [],
                           "final_status": None, "final_blockers": ""}
    cur_cmd: dict[str, Any] | None = None
    cur_stage: str | None = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = TS.match(line.rstrip("\n"))
            if not m:
                continue
            t, body = parse_ts(m.group(1)), m.group(2)
            run["start"] = run["start"] or t
            run["end"] = t
            mh = STAGE_HEADER.match(body.strip())
            if mh:
                cur_stage = mh.group(1)
            if body.startswith("$ "):
                cur_cmd = {"t0": t, "cmd": body[2:], "stage": cur_stage}
            elif body.strip().startswith("-> exit=") and cur_cmd is not None:
                cur_cmd["t1"] = t
                cur_cmd["kind"] = classify_cmd(cur_cmd["cmd"])
                run["cmds"].append(cur_cmd)
                cur_cmd = None
            ms = STAGE_RESULT.match(body)
            if ms:
                run["stages"].append({"stage": ms.group(1), "status": ms.group(2), "blockers": ms.group(3) or "",
                                      "secs": int(ms.group(4)), "t": t})
                run["final_status"], run["final_blockers"] = ms.group(2), ms.group(3) or ""
                cur_stage = ms.group(1)
    return run if run["start"] else None


def measure(logs_dir: str, ledger: str | None = None) -> dict[str, Any]:
    runs = [r for r in (parse_run(p) for p in sorted(glob.glob(os.path.join(logs_dir, "run_*.log")))) if r]
    if not runs:
        raise ValueError(f"NO_RUN_LOGS_IN:{logs_dir}")
    runs.sort(key=lambda r: r["start"])
    t0, t1 = runs[0]["start"], runs[-1]["end"]
    window = (t1 - t0).total_seconds()
    buckets: dict[str, float] = {b: 0.0 for b in BUCKETS}
    stage_first: dict[str, datetime] = {}
    stage_pass: dict[str, datetime] = {}
    stage_attempts: dict[str, int] = defaultdict(int)
    for i, r in enumerate(runs):
        dur = (r["end"] - r["start"]).total_seconds()
        covered = 0.0
        for c in r["cmds"]:
            d = (c["t1"] - c["t0"]).total_seconds()
            covered += d
            buckets[c["kind"]] += d
        buckets["RUN_OVERHEAD"] += max(0.0, dur - covered)
        for s in r["stages"]:
            stage_attempts[s["stage"]] += 1
            stage_first.setdefault(s["stage"], r["start"])
            if s["status"] == "PASS" and s["stage"] not in stage_pass:
                stage_pass[s["stage"]] = s["t"]
        if i + 1 < len(runs):
            gap = (runs[i + 1]["start"] - r["end"]).total_seconds()
            buckets[gap_bucket(r["final_status"], r["final_blockers"])] += gap
    spans = {s: ((stage_pass.get(s) or t1) - stage_first[s]).total_seconds() / 3600 for s in stage_first}
    ledger_rows = 0
    if ledger and os.path.isfile(ledger):
        with open(ledger, encoding="utf-8") as fh:
            ledger_rows = sum(1 for _ in fh)
    return {"schema": SCHEMA, "window_start": t0.isoformat(), "window_end": t1.isoformat(),
            "window_hours": window / 3600, "runs": len(runs),
            "bucket_hours": {k: v / 3600 for k, v in buckets.items()},
            "stage_span_hours": spans, "stage_attempts": dict(stage_attempts),
            "stage_first_pass_at": {k: v.isoformat() for k, v in stage_pass.items()},
            "time_ledger_rows": ledger_rows}


def evaluate(measurement: dict[str, Any], baseline: dict[str, Any], *, units: int | None = None) -> dict[str, Any]:
    target = baseline["target"]
    classes = baseline["measurement"]["classes"]
    class_hours = {cls: sum(measurement["bucket_hours"].get(b, 0.0) for b in bs) for cls, bs in classes.items()}
    failures: list[str] = []
    if measurement["window_hours"] > target["episode_window_hours_max"]:
        failures.append(f"EPISODE_WINDOW_OVER_BUDGET:{measurement['window_hours']:.2f}h>{target['episode_window_hours_max']}h")
    if units:
        per_unit = measurement["window_hours"] / units
        if per_unit > target["per_unit_hours_max"]:
            failures.append(f"PER_UNIT_WALL_OVER_BUDGET:{per_unit:.2f}h>{target['per_unit_hours_max']}h")
    for cls, limit in target["class_hours_max"].items():
        if class_hours.get(cls, 0.0) > limit:
            failures.append(f"CLASS_OVER_BUDGET:{cls}:{class_hours[cls]:.2f}h>{limit}h")
    for stage, limit in target["stage_span_hours_max"].items():
        actual = measurement["stage_span_hours"].get(stage)
        if actual is not None and actual > limit:
            failures.append(f"STAGE_SPAN_OVER_BUDGET:{stage}:{actual:.2f}h>{limit}h")
    return {"status": "PASS" if not failures else "FAIL", "class_hours": class_hours, "failures": failures,
            "budget": target}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--episode", required=True)
    ap.add_argument("--logs-dir", required=True)
    ap.add_argument("--baseline", default=str(Path(__file__).resolve().parents[1] / "configs/THROUGHPUT_BASELINE_V1.json"))
    ap.add_argument("--ledger")
    ap.add_argument("--units", type=int, help="unit count for the per-unit budget")
    ap.add_argument("--report")
    ap.add_argument("--enforce", action="store_true", help="exit 1 when any budget is exceeded")
    args = ap.parse_args()
    try:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        measurement = measure(args.logs_dir, args.ledger)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
        return 2
    verdict = evaluate(measurement, baseline, units=args.units)
    out = {"episode": args.episode, **measurement, **verdict, "baseline_version": baseline.get("version")}
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("episode", "status", "window_hours", "class_hours", "stage_span_hours", "failures")},
                     ensure_ascii=False, indent=1, default=str))
    return 1 if (args.enforce and verdict["status"] != "PASS") else 0


if __name__ == "__main__":
    sys.exit(main())
