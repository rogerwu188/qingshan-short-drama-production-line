"""Production event sources for the collective knowledge base (audit 2026-11-12 §6: zero producers).

The pipeline's judgement points call these helpers; each writes through
``tools/knowledge_event_log.record_event`` (local JSONL + the opt-in DeviceStore outbox mirror with its
``sensitive_findings`` filter), never through DeviceStore directly.

Every helper is best-effort: it returns a status dict and never raises, so a logging failure can never
change what a stage decides.  Re-entry is idempotent: a ``dedupe_key`` that was already recorded is not
recorded again (ledger ``<reports>/KNOWLEDGE_EVENTS_EMITTED.json``, flock-serialised), so a stage that
re-runs on every tick does not flood the log.

Event vocabulary (``evidence.failure_type``; the collector clusters on it):

  Q1_ROUND / Q2_ROUND / POSTGEN_ROUND    one per review round: SUCCESS_OBSERVATION when every unit passed,
                                         FAILURE_OBSERVATION otherwise; opportunity = units / failed units.
                                         Rate facts only -- never clustered into a lesson.
  Q1_REJECT:<CODE> / Q2_REJECT:<CODE> / POSTGEN_FAIL:<CODE>
                                         one per distinct failure code in a round, over the units carrying it
  S7_DETECTOR:<detector>                 final-cut audience detector FAIL (order-carried or not)
  S7_FINAL_REVIEW_REJECT                 the independent final-audience review rejected the cut
  S7_FINAL_GATE:<gate_id>                a final-package gate that did not PASS
  PROVIDER_CONTENT_REJECTION:<image|video>
                                         the same task refused (uncharged HopsAPI 424) at least twice while
                                         other tasks completed around it: content risk control, a lesson
  PROVIDER_OUTAGE:<image|video>          RUN_ANOMALY: an unbroken run of 424s across several tasks with no
                                         completion in between -- an outage, recorded but never a lesson
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

LEDGER_NAME = "KNOWLEDGE_EVENTS_EMITTED.json"
LEDGER_MAX_KEYS = 5000
DETECTED_BY = "nalu_pipeline"
LINE = "nalu"
ROUND_TYPES = ("Q1_ROUND", "Q2_ROUND", "POSTGEN_ROUND")
PROVIDER_ERROR_CODE = 424
CONTENT_MIN_REJECTIONS = 2
HEALTH_WINDOW_S = 3600
OUTAGE_WINDOW_S = 900
OUTAGE_MIN_FAILURES = 3
OUTAGE_MIN_TASKS = 2
_CODE_RE = re.compile(r"[A-Z][A-Z0-9_]{1,59}")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")
_ABS_PATH_RE = re.compile(r"(?:^|[\s=:'\"(])(/(?:[^/\s]+/)+[^/\s]*)")


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def reports_dir(rt: Path) -> Path:
    """Same rule as knowledge_event_log / runtime_wiring: ``<rt>/runtime/reports`` when nested, else ``<rt>/reports``."""
    rt = Path(rt)
    return rt / "runtime" / "reports" if (rt / "runtime").is_dir() else rt / "reports"


def failure_code(text: Any) -> str:
    """``"FACE_COUNT_ZERO:S01-02"`` -> ``FACE_COUNT_ZERO``; free text -> ``OTHER``."""
    head = str(text or "").strip().split(":", 1)[0].strip()
    head = head.upper().replace("-", "_").replace(" ", "_")
    return head if _CODE_RE.fullmatch(head) else "OTHER"


def _scrub(value: Any, depth: int = 0) -> Any:
    """Evidence is shared fleet-wide: absolute paths become basenames, strings and lists are bounded."""
    if depth > 4:
        return None
    if isinstance(value, dict):
        return {str(k)[:60]: _scrub(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, (list, tuple)):
        return [_scrub(v, depth + 1) for v in list(value)[:20]]
    if isinstance(value, str):
        text = _ABS_PATH_RE.sub(lambda m: m.group(0)[: m.start(1) - m.start(0)] + Path(m.group(1)).name, value)
        return text[:300]
    return value


def _unit_ids(values: Iterable[Any]) -> list[str]:
    return sorted({str(v) for v in values if _ID_RE.match(str(v or ""))})[:200]


@contextlib.contextmanager
def _ledger(reports: Path):
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / LEDGER_NAME
    with open(reports / f".{LEDGER_NAME}.lock", "a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("keys"), dict):
                    raise ValueError
            except (OSError, ValueError):
                data = {"schema": "nalu.knowledge_events_emitted.v1", "keys": {}}
            yield data
            keys = data["keys"]
            if len(keys) > LEDGER_MAX_KEYS:
                for old in sorted(keys, key=lambda k: str(keys[k].get("at")))[: len(keys) - LEDGER_MAX_KEYS]:
                    keys.pop(old, None)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            tmp.replace(path)
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _kel():
    import knowledge_event_log  # noqa: PLC0415 -- engine tools/ is on sys.path in the pipeline
    return knowledge_event_log


def emit(rt: Path, *, episode: str, stage: str, failure_type: str, symptom: str, evidence: dict[str, Any],
         dedupe_key: str, unit_ids: Iterable[Any] = (), event_kind: str = "FAILURE_OBSERVATION",
         opportunity: dict[str, int] | None = None, detected_by: str = DETECTED_BY) -> dict[str, Any]:
    """Record one fact once.  Never raises."""
    try:
        reports = reports_dir(rt)
        with _ledger(reports) as ledger:
            if dedupe_key in ledger["keys"]:
                return {"status": "DUPLICATE", "dedupe_key": dedupe_key}
            row = _kel().record_event(
                Path(rt), episode=episode, line=LINE, stage=stage, symptom=symptom,
                evidence={**(_scrub(evidence) or {}), "failure_type": failure_type},
                detected_by=detected_by, unit_ids=_unit_ids(unit_ids), event_kind=event_kind,
                opportunity=opportunity)
            mirror = (row.get("collective_mirror") or {}).get("status")
            ledger["keys"][dedupe_key] = {"at": _now(), "event_id": row.get("event_id"), "mirror": mirror}
        return {"status": "RECORDED", "event_id": row.get("event_id"), "failure_type": failure_type,
                "mirror": mirror}
    except Exception as exc:  # noqa: BLE001 -- the knowledge log must never break production
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}"}


def record_review_round(rt: Path, *, episode: str, stage: str, kind: str, round_key: str,
                        rows: list[dict[str, Any]], evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """One review round: ``rows`` = ``[{unit_id, passed: bool, codes: [...]}, ...]``.

    Writes the round's rate fact (``<kind>_ROUND``) and one FAILURE_OBSERVATION per distinct failure
    code.  ``kind`` is Q1 / Q2 / POSTGEN; ``round_key`` identifies the round (the review file sha)."""
    out: dict[str, Any] = {"status": "OK", "events": []}
    try:
        rows = [r for r in rows or [] if isinstance(r, dict)]
        if not rows:
            return {"status": "NO_ROWS"}
        failed = [r for r in rows if not r.get("passed")]
        base = dict(evidence or {})
        base.update({"round_key": str(round_key)[:80], "units_in_round": len(rows), "units_failed": len(failed)})
        label = {"Q1": "keyframe Q1 admission", "Q2": "video Q2 admission", "POSTGEN": "post-generation QA"}.get(kind, kind)
        out["events"].append(emit(
            rt, episode=episode, stage=stage, failure_type=f"{kind}_ROUND",
            symptom=(f"{label}: all {len(rows)} units passed" if not failed else
                     f"{label}: {len(failed)} of {len(rows)} units not admitted"),
            evidence=base, dedupe_key=f"{episode}:{kind}_ROUND:{round_key}",
            unit_ids=[r.get("unit_id") for r in (failed or rows)],
            event_kind="SUCCESS_OBSERVATION" if not failed else "FAILURE_OBSERVATION",
            opportunity={"applicable_units": len(rows), "observed_units": len(rows) - len(failed) if not failed
                         else len(failed)}))
        by_code: dict[str, list[str]] = {}
        samples: dict[str, list[str]] = {}
        for row in failed:
            codes = [failure_code(x) for x in (row.get("codes") or [])] or ["UNSPECIFIED"]
            for code in sorted(set(codes)):
                by_code.setdefault(code, []).append(str(row.get("unit_id")))
                samples.setdefault(code, []).extend(str(x)[:160] for x in (row.get("codes") or [])
                                                   if failure_code(x) == code)
        prefix = {"Q1": "Q1_REJECT", "Q2": "Q2_REJECT", "POSTGEN": "POSTGEN_FAIL"}.get(kind, f"{kind}_FAIL")
        for code, units in sorted(by_code.items()):
            out["events"].append(emit(
                rt, episode=episode, stage=stage, failure_type=f"{prefix}:{code}",
                symptom=f"{label} failure {code} on {len(units)} of {len(rows)} units",
                evidence={**base, "failure_code": code, "samples": samples.get(code, [])[:5]},
                dedupe_key=f"{episode}:{prefix}:{code}:{round_key}", unit_ids=units,
                opportunity={"applicable_units": len(rows), "observed_units": len(units)}))
    except Exception as exc:  # noqa: BLE001
        out = {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "events": out.get("events")}
    return out


def record_final_cut(rt: Path, *, episode: str, kind: str, items: Iterable[Any], media_sha256: str | None,
                     evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """S7 failures on one final-cut candidate (deduped per candidate sha).  ``kind``:
    ``S7_DETECTOR`` (items = failing detectors), ``S7_FINAL_GATE`` (items = gate ids),
    ``S7_FINAL_REVIEW_REJECT`` (items = reasons; one event)."""
    events: list[dict[str, Any]] = []
    try:
        sha = str(media_sha256 or "NO_MEDIA")
        items = [str(x) for x in items if str(x or "").strip()]
        base = {**(evidence or {}), "final_candidate_sha256": media_sha256}
        if kind == "S7_FINAL_REVIEW_REJECT":
            events.append(emit(rt, episode=episode, stage="S7", failure_type=kind,
                               symptom="independent final-audience review rejected the final cut"
                                       + (f": {'; '.join(items)[:200]}" if items else ""),
                               evidence={**base, "reasons": items[:8]}, dedupe_key=f"{episode}:{kind}:{sha}"))
        else:
            what = {"S7_DETECTOR": "audience detector", "S7_FINAL_GATE": "final-package gate",
                    "S7_FINAL_REVIEW_LOW": "final-review dimension"}.get(kind, "check")
            for item in sorted(set(items)):
                name = item.split(":", 1)[-1] if item.startswith("final:") else item
                code = re.sub(r"[^A-Za-z0-9_.\-]", "_", name)[:60] or "UNKNOWN"
                events.append(emit(rt, episode=episode, stage="S7", failure_type=f"{kind}:{code}",
                                   symptom=f"final cut {what} {name} did not pass",
                                   evidence={**base, "item": name}, dedupe_key=f"{episode}:{kind}:{code}:{sha}"))
        return {"status": "OK", "events": events}
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "events": events}


# --------------------------------------------------------------------------- provider rejections
def _parse(stamp: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp() if stamp else None
    except ValueError:
        return None


def _settled_rows(store: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(Path(store).glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(row, dict) or str(row.get("provider") or "").lower() != "hopsapi":
            continue
        if row.get("reference_isolation_probe") or row.get("hopsapi_health_probe"):
            continue  # diagnosis probes say nothing about a production task's content
        remote = str(row.get("provider_remote_status") or row.get("remote_terminal_state") or "").lower()
        observed = _parse(row.get("remote_terminal_observed_at") or row.get("provider_status_observed_at"))
        if observed is None:
            continue
        key = str(row.get("task_key") or "").strip() or path.stem.split(".terminal-")[0].split("__")[0]
        cost = row.get("provider_cost_credits")
        code = row.get("provider_failure_code")
        is_424 = (remote in ("failed", "cancelled") and not (isinstance(cost, (int, float)) and cost > 0)
                  and (str(code) == str(PROVIDER_ERROR_CODE)
                       or str(row.get("provider_failure") or "").startswith("Provider error")))
        if remote == "completed" or is_424:
            rows.append({"task": key, "completed": remote == "completed", "at": observed,
                         "task_id": str(row.get("task_id") or "")[:80], "model": row.get("provider_model")})
    return sorted(rows, key=lambda r: r["at"])


def classify_424s(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Split uncharged 424s into outage windows and per-task content rejections.

    Outage: >= OUTAGE_MIN_FAILURES 424s from >= OUTAGE_MIN_TASKS tasks inside OUTAGE_WINDOW_S with no
    completion in that span.  Content rejection: a task refused >= CONTENT_MIN_REJECTIONS times outside
    any outage, while some OTHER task completed within HEALTH_WINDOW_S of its last refusal (the channel
    worked; this request did not).  Everything else stays unclassified (no event)."""
    fails = [r for r in rows if not r["completed"]]
    done = [r for r in rows if r["completed"]]
    outages: list[dict[str, Any]] = []
    in_outage: set[int] = set()
    i = 0
    while i < len(fails):
        j = i
        while j + 1 < len(fails) and fails[j + 1]["at"] - fails[i]["at"] <= OUTAGE_WINDOW_S:
            j += 1
        span = fails[i: j + 1]
        start, end = span[0]["at"], span[-1]["at"]
        if (len(span) >= OUTAGE_MIN_FAILURES and len({r["task"] for r in span}) >= OUTAGE_MIN_TASKS
                and not any(start <= d["at"] <= end for d in done)):
            outages.append({"start": start, "end": end, "failures": len(span),
                            "tasks": sorted({r["task"] for r in span})[:10]})
            in_outage.update(range(i, j + 1))
            i = j + 1
        else:
            i += 1
    content: list[dict[str, Any]] = []
    per_task: dict[str, list[dict[str, Any]]] = {}
    for index, row in enumerate(fails):
        if index not in in_outage:
            per_task.setdefault(row["task"], []).append(row)
    for task, refusals in sorted(per_task.items()):
        if len(refusals) < CONTENT_MIN_REJECTIONS:
            continue
        last = refusals[-1]["at"]
        if any(d["task"] != task and abs(d["at"] - last) <= HEALTH_WINDOW_S for d in done):
            content.append({"task": task, "refusals": len(refusals),
                            "task_ids": [r["task_id"] for r in refusals][-5:], "model": refusals[-1].get("model")})
    return {"outages": outages, "content": content}


def scan_provider_rejections(rt: Path, *, episode: str, stores: dict[str, Path]) -> dict[str, Any]:
    """Classify this episode's settled HopsAPI 424s and record each content rejection / outage once.
    ``stores`` = ``{"image": <transaction dir>, "video": <transaction dir>}``.  Never raises."""
    out: dict[str, Any] = {"status": "OK", "events": []}
    try:
        for kind, store in sorted(stores.items()):
            if not Path(store).is_dir():
                continue
            verdict = classify_424s(_settled_rows(Path(store)))
            stage = "S6" if kind == "video" else "S5"
            for row in verdict["content"]:
                out["events"].append(emit(
                    rt, episode=episode, stage=stage, failure_type=f"PROVIDER_CONTENT_REJECTION:{kind}",
                    symptom=(f"HopsAPI {row.get('model') or kind} refused the same {kind} request "
                             f"{row['refusals']} times (uncharged 424) while other tasks completed: "
                             "provider content risk control, not an outage"),
                    evidence={"provider": "hopsapi", "model": row.get("model"), "refusals": row["refusals"],
                              "task_ids": row["task_ids"], "classifier": "nalu_knowledge_events.classify_424s"},
                    unit_ids=[row["task"]], dedupe_key=f"{episode}:content424:{kind}:{row['task']}"))
            for window in verdict["outages"]:
                bucket = int(window["start"] // OUTAGE_WINDOW_S)
                out["events"].append(emit(
                    rt, episode=episode, stage=stage, failure_type=f"PROVIDER_OUTAGE:{kind}",
                    symptom=(f"HopsAPI {kind} outage: {window['failures']} uncharged 424s across "
                             f"{len(window['tasks'])} tasks with no completion in between"),
                    evidence={"provider": "hopsapi", "failures": window["failures"], "tasks": window["tasks"],
                              "window_start": datetime.fromtimestamp(window["start"], timezone.utc).isoformat(),
                              "window_end": datetime.fromtimestamp(window["end"], timezone.utc).isoformat()},
                    event_kind="RUN_ANOMALY", dedupe_key=f"outage424:{kind}:{bucket}"))
    except Exception as exc:  # noqa: BLE001
        out = {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "events": out.get("events")}
    return out


def enabled() -> bool:
    """NALU_KNOWLEDGE_EVENTS=off disables every producer (kill switch; default on)."""
    return str(os.environ.get("NALU_KNOWLEDGE_EVENTS") or "").strip().lower() not in ("off", "0", "false")
