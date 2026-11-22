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
  CRAFT_STD_GAP                          one per top gap the independent final reviewer gave against
                                         NALU_CRAFT_STANDARD_v1 (cluster ``CRAFT_STD_GAP|<item id>``, stage
                                         SCRIPT_AUTHORING for a writer fix, STORYBOARD_AUTHORING for engine / S7);
                                         item id, numbers and a scrubbed fix line only (``record_craft_gaps``)
  QA_DEFECT:<item id>                    one per must-check defect of the final review (line owner 2026-11-19:
                                         QA-BURNED-TEXT / -DIALOGUE-TAIL-CUT / -OVERSIZED-MASK / -LOOKALIKE-CAST /
                                         -SUBTITLE-WRAP / -BGM-DISCONTINUOUS) the reviewer confirmed or the engine
                                         measured (cluster ``QA_DEFECT|<item id>``; item id, routing, timestamps and
                                         counts only -- ``record_qa_defects``); the S3 cross-character similarity
                                         measurement records QA-LOOKALIKE-CAST too (``record_lookalike_cast``)
  FINAL_REVIEW:<kind>                    one per CONFIRMED finding of the independent final review (reviewer
                                         problems, must-check DEFECTs, Gemini findings the reviewer confirmed;
                                         cluster ``FINAL_REVIEW:<kind>|global`` -- the default -- or
                                         ``FINAL_REVIEW:<kind>|<language>`` when ``final_review_scope`` finds the
                                         finding language-dependent; kind = final_fix_round.classify, lesson_route
                                         DIRECTING_GUIDANCE / MODEL_CONSTRAINT / ENGINE; anonymised description and
                                         the scope decision only -- ``record_final_review_findings``)

Evidence quality (first daily review 2026-11-13 rejected all 46 clusters as too thin / bookkeeping):

* every failure event carries ``failure_code`` + ``detail_category`` (normalised cause, e.g.
  ``unexpected_native_mandarin_speech_present``) and ``cluster_key`` = ``<failure_type>|<detail_category>``
  the collector clusters on, plus up to ``MAX_SAMPLES`` structured ``samples``: unit id, scene/shot label,
  the raw reason, the check's measured-vs-threshold values and a <= ``EXCERPT_MAX`` char excerpt (ASR
  transcript, reviewer defect note, detector failure code).  Never absolute paths, URLs or full prompts:
  ``_scrub`` reduces paths to basenames and drops URLs/tokens before ``sensitive_findings`` sees them.
* ``lesson_class`` tags facts a prompt rule cannot fix (``ENGINE_THRESHOLD``: raster/duration/codec checks
  and the S7 mix loudness; the release train lists them as engine items, never as rule candidates).
* ``default_accepted`` marks an S7 failure that a line-owner order already accepted under the default terms
  when it was evaluated (excluded from candidate clustering by default).
* S7 final-package gates are classified before anything is recorded (``classify_final_gate``): gates that
  were never invoked (evidence not produced yet / by design), engine bookkeeping gates, the
  FINAL-CUT-AUDIENCE-DETECTORS row (already one event per detector) and the seven FINAL-CUT-* rows that
  only mirror ONE combined final_cut_quality_gates verdict are not failures of their own and are skipped.
"""
from __future__ import annotations

import contextlib
import fcntl
import hashlib
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
_URL_RE = re.compile(r"(?i)\b(?:https?|s3|gs|file|ftp)://\S+")
_WIN_PATH_RE = re.compile(r"[A-Za-z]:\\(?:[^\\\s]+\\)+([^\\\s]*)")
_SECRET_RE = re.compile(r"(?i)(?:bearer\s+[a-z0-9._\-]{8,}|sk-[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}"
                        r"|api[_-]?key\s*[:=]\s*\S{8,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)")
EXCERPT_MAX = 200
MAX_SAMPLES = 3
#: post-generation technical checks whose FAIL is a raster / container / threshold property of the provider
#: output (or of the engine's tolerance), never something a prompt rule can change -- engine items.
ENGINE_TECHNICAL_CODES = frozenset({"RESOLUTION", "DURATION", "ASPECT_RATIO", "CODEC", "SAMPLE_RATE", "FRAME_RATE",
                                    "AUDIO_STREAM", "AV_SYNC", "DECODE", "DECODE_FAILED", "CORRUPTION",
                                    "MEDIA_MISSING"})
#: S7 audience detectors measured on the engine's own mix (levelling / limiter), not on generated content
ENGINE_DETECTORS = frozenset({"loudness"})
ENGINE_THRESHOLD = "ENGINE_THRESHOLD"


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
    if depth > 6:
        return None
    if isinstance(value, dict):
        return {str(k)[:60]: _scrub(v, depth + 1) for k, v in list(value.items())[:30]}
    if isinstance(value, (list, tuple)):
        return [_scrub(v, depth + 1) for v in list(value)[:20]]
    if isinstance(value, str):
        return _clean_text(value)[:300]
    return value


def _clean_text(value: Any) -> str:
    text = _URL_RE.sub("<url>", str(value))
    text = _SECRET_RE.sub("<redacted>", text)
    text = _WIN_PATH_RE.sub(lambda m: m.group(1), text)
    return _ABS_PATH_RE.sub(lambda m: m.group(0)[: m.start(1) - m.start(0)] + Path(m.group(1)).name, text)


def excerpt(value: Any, limit: int = EXCERPT_MAX) -> str | None:
    """A short, path/URL/secret-free, single-line excerpt (<= ``limit`` chars) or None when empty."""
    if value is None:
        return None
    text = " ".join(_clean_text(value).split())
    if not text:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def detail_category(text: Any) -> str:
    """Normalise a cause fragment: ``unexpected_native_mandarin_speech_present`` stays, ``FAIL`` / numbers /
    ``1.8s`` disappear (they are values, not causes)."""
    cat = re.sub(r"[^a-z0-9_]+", "_", str(text or "").strip().lower()).strip("_")[:60]
    if not cat or cat in ("fail", "failed", "reject", "missing", "none", "true", "false") \
            or re.fullmatch(r"[0-9_.]+(?:s|ms|db|hz)?", cat) \
            or re.fullmatch(r"[a-z]{0,6}_?\d+(?:_[a-z]{0,6}_?\d+)*", cat):  # values / unit or shot ids
        return ""
    return cat


def reason_parts(text: Any) -> tuple[str, str]:
    """``(failure_code, detail_category)`` of one unit failure string.

    ``evidence_3:ACTION-SHOT-DESIGN:registered_gate_not_pass:FAIL_NOT_ADMITTED:P0`` -> the gate, not the
    positional ``EVIDENCE_3``; ``required_registered_gate_not_pass:GATE`` -> the gate;
    ``dialogue:unexpected_native_mandarin_speech_present`` -> ``(DIALOGUE, unexpected_native_...)``."""
    parts = [part.strip() for part in str(text or "").strip().split(":")]
    head = parts[0].lower()
    if re.fullmatch(r"evidence_\d+", head) and len(parts) > 1:
        return failure_code(parts[1]), detail_category(parts[2] if len(parts) > 2 else "")
    if head == "required_registered_gate_not_pass" and len(parts) > 1:
        return failure_code(parts[1]), "registered_gate_not_pass"
    return failure_code(text), detail_category(parts[1] if len(parts) > 1 else "")


def _scalars(row: Any, *, limit: int = 14, skip: Iterable[str] = ()) -> dict[str, Any]:
    """The scalar fields of a check/detector record (numbers, short strings, small scalar lists)."""
    out: dict[str, Any] = {}
    if not isinstance(row, dict):
        return out
    skipped = set(skip) | {"check", "status", "policy", "report", "gate_report", "media", "media_path", "path",
                           "record", "review_file", "stderr_tail", "stdout_tail", "output"}
    for key, value in row.items():
        if len(out) >= limit or key in skipped:
            continue
        if isinstance(value, bool) or isinstance(value, (int, float)) or value is None:
            if value is not None:
                out[key] = value
        elif isinstance(value, str):
            out[key] = excerpt(value, 120)
        elif isinstance(value, (list, tuple)) and value and all(
                isinstance(v, (str, int, float)) and not isinstance(v, bool) for v in value):
            out[key] = [excerpt(v, 80) if isinstance(v, str) else v for v in list(value)[:5]]
    return out


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


# --------------------------------------------------------------------------- per-unit evidence
def _defects(rows: Any, limit: int = 3) -> list[dict[str, Any]]:
    out = []
    for row in (rows if isinstance(rows, list) else [])[:limit]:
        if isinstance(row, dict):
            out.append({k: v for k, v in {
                "code": excerpt(row.get("code"), 60), "severity": row.get("severity"),
                "shot_index": row.get("shot_index") if isinstance(row.get("shot_index"), int) else None,
                "note": excerpt(row.get("description") or row.get("note") or row.get("issue"), 160)}.items()
                if v is not None})
    return out


def _context(row: dict[str, Any]) -> dict[str, Any]:
    """Unit context labels a reviewer can read (scene/shot ids, shot type) -- never paths."""
    out = {}
    for key in ("item_id", "scene_id", "shot_id", "shot_type", "scene_label", "beat_type", "unit_kind"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = excerpt(value, 60)
    return out


def q_unit_detail(row: dict[str, Any]) -> dict[str, Any]:
    """Q1/Q2 admission index row -> the reviewer-readable part (verdict, defects with notes, OCR/identity)."""
    detail = {"vlm_verdict": row.get("vlm_verdict"), "ocr_status": row.get("ocr_status"),
              "identity_method": row.get("identity_method"),
              "blocking_defects": _defects(row.get("blocking_defects")),
              "p2_defects": _defects(row.get("p2_defects"), 2)}
    return {k: v for k, v in detail.items() if v not in (None, [], "")}


def q_unit_pairs(row: dict[str, Any]) -> list[tuple[str, str, str]]:
    """``[(failure_code, detail_category, raw_reason)]`` for one rejected Q1/Q2 unit.  A DEFECT-TIER-TOLERANCE
    failure (and a reject with no failure strings at all) is split by the reviewer's defect codes, so a
    duplicated person and a framing miss do not merge."""
    defects = [str(d.get("code")) for d in row.get("blocking_defects") or [] if isinstance(d, dict) and d.get("code")]
    pairs: list[tuple[str, str, str]] = []
    for raw in row.get("codes") or row.get("failures") or []:
        code, cat = reason_parts(raw)
        if code == "DEFECT_TIER_TOLERANCE" and defects:
            pairs.extend((code, detail_category(d), str(raw)) for d in defects)
        else:
            pairs.append((code, cat, str(raw)))
    if not pairs:
        pairs = [("BLOCKING_DEFECT", detail_category(d), d) for d in defects] or [("UNSPECIFIED", "", "")]
    seen, out = set(), []
    for code, cat, raw in pairs:
        if (code, cat) not in seen:
            seen.add((code, cat))
            out.append((code, cat, raw))
    return out


def postgen_reason_detail(record: dict[str, Any], reason: str) -> tuple[str, dict[str, Any]]:
    """``(category_override, detail)`` for one post-generation QA reason, from the unit's QA record."""
    parts = str(reason or "").split(":")
    name = parts[0]
    technical = ((record.get("technical_qa") or {}).get("checks") or {})
    plot = record.get("basic_plot_qa") or {}
    if name == "dialogue":
        dq = record.get("dialogue_qa") or {}
        return "", {k: v for k, v in {
            "recall_score": dq.get("recall_score"), "minimum_recall": dq.get("minimum_recall"),
            "expected_line_count": dq.get("expected_line_count"), "asr_gate_status": dq.get("gate_status"),
            "language": dq.get("language"), "asr_transcript_excerpt": excerpt(dq.get("transcript"))}.items()
            if v is not None}
    if name in technical:
        check = technical.get(name) or {}
        override = ""
        if name == "freeze":
            override = "frozen_run" if check.get("frozen_runs") else (
                "unmotivated_static_hold" if str(check.get("static_hold_status") or "PASS") != "PASS" else "")
        detail = _scalars(check, skip=("pacing_policy", "frozen_runs"))
        if check.get("frozen_runs"):
            detail["frozen_runs"] = len(check["frozen_runs"])
        return override, detail
    if name.startswith("PLOT_DEFECT"):
        code = parts[1] if len(parts) > 1 else ""
        match = [d for d in plot.get("defects") or [] if isinstance(d, dict) and str(d.get("code")) == code]
        return "", {"defects": _defects(match or plot.get("defects")),
                    "observation_excerpt": excerpt(plot.get("observation"))}
    if name in (plot.get("checks") or {}):
        check = (plot.get("checks") or {}).get(name) or {}
        return "", {k: v for k, v in {"reviewer_answer": check.get("reviewer_answer"),
                                      "observation_excerpt": excerpt(plot.get("observation")),
                                      "defects": _defects(plot.get("defects"), 2)}.items() if v}
    if name == "combat_execution":
        return "", _scalars(record.get("combat_execution_qa") or {})
    if name == "voice":
        return "", _scalars(record.get("voice_consistency_qa") or {})
    return "", {}


def postgen_unit_pairs(row: dict[str, Any]) -> list[tuple[str, str, str, dict[str, Any]]]:
    """``[(code, category, raw_reason, detail)]`` for one rejected post-generation unit (``row["source"]`` =
    the unit's ``*_POST_GENERATION_QA.json`` record when the pipeline could read it)."""
    record = row.get("source") if isinstance(row.get("source"), dict) else {}
    out, seen = [], set()
    for raw in row.get("codes") or []:
        code, cat = reason_parts(raw)
        override, detail = postgen_reason_detail(record, str(raw)) if record else ("", {})
        cat = override or cat
        if (code, cat) in seen:
            continue
        seen.add((code, cat))
        out.append((code, cat, str(raw), detail))
    return out or [("UNSPECIFIED", "", "", {})]


def record_review_round(rt: Path, *, episode: str, stage: str, kind: str, round_key: str,
                        rows: list[dict[str, Any]], evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """One review round: ``rows`` = ``[{unit_id, passed: bool, codes: [...], source?: {...}}, ...]``.

    Writes the round's rate fact (``<kind>_ROUND``) and one FAILURE_OBSERVATION per distinct
    ``(failure_code, detail_category)``.  ``source`` is the raw admission index row (Q1/Q2) or the unit's
    post-generation QA record (POSTGEN); it only feeds the evidence samples.  ``kind`` is Q1 / Q2 / POSTGEN;
    ``round_key`` identifies the round (the review file sha)."""
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
        groups: dict[tuple[str, str], dict[str, Any]] = {}
        for row in failed:
            unit = str(row.get("unit_id"))
            source = row.get("source") if isinstance(row.get("source"), dict) else {}
            if kind == "POSTGEN":
                pairs = postgen_unit_pairs(row)
                context = _context(source)
            else:
                q_row = {**source, "codes": row.get("codes")} if source else row
                q_detail = q_unit_detail(source) if source else {}
                pairs = [(code, cat, raw, q_detail) for code, cat, raw in q_unit_pairs(q_row)]
                context = _context(source)
            for code, cat, raw, detail in pairs:
                group = groups.setdefault((code, cat), {"units": [], "samples": [], "reasons": []})
                group["units"].append(unit)
                if raw and len(group["reasons"]) < 5:
                    group["reasons"].append(excerpt(raw, 160))
                if len(group["samples"]) < MAX_SAMPLES:
                    sample = {"unit_id": unit, **context}
                    if raw:
                        sample["reason"] = excerpt(raw, 160)
                    if detail:
                        sample["detail"] = detail
                    group["samples"].append(sample)
        prefix = {"Q1": "Q1_REJECT", "Q2": "Q2_REJECT", "POSTGEN": "POSTGEN_FAIL"}.get(kind, f"{kind}_FAIL")
        for (code, cat), group in sorted(groups.items()):
            units = group["units"]
            failure_type = f"{prefix}:{code}"
            lesson_class = ENGINE_THRESHOLD if kind == "POSTGEN" and code in ENGINE_TECHNICAL_CODES else None
            first = next((s for s in group["samples"] if s.get("detail")), None)
            hint = _sample_hint(first)
            ev = {**base, "failure_code": code, "detail_category": cat or None,
                  "cluster_key": failure_type + (f"|{cat}" if cat else ""),
                  "samples": group["samples"], "sample_reasons": group["reasons"]}
            if lesson_class:
                ev["lesson_class"] = lesson_class
            out["events"].append(emit(
                rt, episode=episode, stage=stage, failure_type=failure_type,
                symptom=(f"{label} failure {code}" + (f" ({cat})" if cat else "")
                         + f" on {len(units)} of {len(rows)} units" + (f": {hint}" if hint else "")),
                evidence={k: v for k, v in ev.items() if v is not None},
                dedupe_key=f"{episode}:{prefix}:{code}:{round_key}" + (f":{cat}" if cat else ""), unit_ids=units,
                opportunity={"applicable_units": len(rows), "observed_units": len(units)}))
    except Exception as exc:  # noqa: BLE001
        out = {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "events": out.get("events")}
    return out


def _sample_hint(sample: dict[str, Any] | None) -> str | None:
    """One short human line from a sample (the excerpt a reviewer reads first)."""
    if not sample:
        return None
    detail = sample.get("detail") or {}
    for key in ("asr_transcript_excerpt", "observation_excerpt"):
        if detail.get(key):
            return excerpt(f"{sample['unit_id']} {key.split('_')[0]}: {detail[key]}", 160)
    defects = detail.get("blocking_defects") or detail.get("defects") or []
    if defects and defects[0].get("note"):
        return excerpt(f"{sample['unit_id']} {defects[0].get('code')}: {defects[0]['note']}", 160)
    if "measured" in detail or "measured_seconds" in detail:
        measured = detail.get("measured", detail.get("measured_seconds"))
        expected = detail.get("expected", detail.get("planned_seconds"))
        return excerpt(f"{sample['unit_id']} measured {measured} vs expected {expected}", 160)
    return None


# --------------------------------------------------------------------------- S7
def _read(path: Any) -> dict[str, Any]:
    try:
        data = json.loads(Path(str(path)).read_text(encoding="utf-8")) if path else {}
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def detector_items(report: dict[str, Any], failing: Iterable[str]) -> list[dict[str, Any]]:
    """Failing audience detectors with their own failure codes and measured-vs-threshold values."""
    detectors = report.get("detectors") if isinstance(report.get("detectors"), dict) else {}
    items = []
    for name in sorted({str(x) for x in failing if str(x or "").strip()}):
        row = detectors.get(name) if isinstance(detectors.get(name), dict) else {}
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        codes = [str(c) for c in (row.get("failures") or evidence.get("failures") or [])][:6]
        detail = {k: v for k, v in {
            "status": row.get("status"), "failures": [excerpt(c, 120) for c in codes] or None,
            "measured": _scalars(row.get("measured")) or None, "threshold": _scalars(row.get("threshold")) or None,
            "note": excerpt(evidence.get("note"), 160)}.items() if v}
        items.append({"name": name, "category": detail_category(codes[0].split(":")[0]) if codes else "",
                      "detail": detail, "lesson_class": ENGINE_THRESHOLD if name in ENGINE_DETECTORS else None})
    return items


def review_items(report: dict[str, Any], kind: str, items: Iterable[str]) -> list[dict[str, Any]]:
    """Final-audience review reject / low dimensions with the reviewer's own reasons and top problems."""
    reasons = report.get("dimension_reasons") if isinstance(report.get("dimension_reasons"), dict) else {}
    dims = report.get("dimensions") if isinstance(report.get("dimensions"), dict) else {}
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    problems = sorted([p for p in report.get("problems") or [] if isinstance(p, dict)],
                      key=lambda p: order.get(str(p.get("severity")), 9))
    top = [{k: v for k, v in {"severity": p.get("severity"), "shot_index": p.get("shot_index"),
                              "at_seconds": p.get("at_seconds"), "issue": excerpt(p.get("issue"), 160),
                              "fix": excerpt(p.get("fix"), 120)}.items() if v is not None} for p in problems[:3]]
    out = []
    for name in [str(x) for x in items if str(x or "").strip()]:
        if kind == "S7_FINAL_REVIEW_LOW":
            detail = {"score": dims.get(name), "reviewer_reason": excerpt(reasons.get(name)), "top_problems": top}
        else:
            detail = {"overall": report.get("overall"), "overall_reason": excerpt(report.get("overall_reason")),
                      "hard_fail": [str(h) for h in report.get("hard_fail") or []][:6]
                      if isinstance(report.get("hard_fail"), list) else report.get("hard_fail"),
                      "top_problems": top}
        out.append({"name": name, "detail": {k: v for k, v in detail.items() if v not in (None, [], "")}})
    return out


def record_final_cut(rt: Path, *, episode: str, kind: str, items: Iterable[Any], media_sha256: str | None,
                     evidence: dict[str, Any] | None = None, detector_report: str | None = None,
                     review_report: str | None = None, accepted_order_seq: Any = None) -> dict[str, Any]:
    """S7 failures on one final-cut candidate (deduped per candidate sha).  ``kind``:
    ``S7_DETECTOR`` (items = failing detectors), ``S7_FINAL_GATE`` (items = gate ids or classified dicts from
    ``record_final_gates``), ``S7_FINAL_REVIEW_LOW`` (items = dimensions), ``S7_FINAL_REVIEW_REJECT`` (items =
    reasons; one event).  ``detector_report`` / ``review_report`` (local paths, never recorded) enrich the
    evidence; ``accepted_order_seq`` = the line-owner order that already carried this failure when it was
    evaluated (``default_accepted``: excluded from candidate clustering by default)."""
    events: list[dict[str, Any]] = []
    try:
        sha = str(media_sha256 or "NO_MEDIA")
        base = {**(evidence or {}), "final_candidate_sha256": media_sha256}
        if accepted_order_seq is not None:
            base.update({"default_accepted": True, "accepted_order_seq": accepted_order_seq})
        raw_items = [x for x in items if (isinstance(x, dict) and x.get("name")) or str(x or "").strip()]
        names = [str(x["name"]) if isinstance(x, dict) else str(x) for x in raw_items]
        review = _read(review_report) if review_report else {}
        if kind == "S7_FINAL_REVIEW_REJECT":
            detail = review_items(review, kind, ["reject"])[0]["detail"] if review else {}
            events.append(emit(rt, episode=episode, stage="S7", failure_type=kind,
                               symptom="independent final-audience review rejected the final cut"
                                       + (f": {'; '.join(names)[:200]}" if names else ""),
                               evidence={**base, "reasons": names[:8], **({"detail": detail} if detail else {})},
                               dedupe_key=f"{episode}:{kind}:{sha}"))
            return {"status": "OK", "events": events}
        if kind == "S7_DETECTOR" and detector_report:
            enriched = {row["name"]: row for row in detector_items(_read(detector_report), names)}
        elif kind == "S7_FINAL_REVIEW_LOW" and review:
            enriched = {row["name"]: row for row in review_items(review, kind, names)}
        else:
            enriched = {}
        what = {"S7_DETECTOR": "audience detector", "S7_FINAL_GATE": "final-package gate",
                "S7_FINAL_REVIEW_LOW": "final-review dimension"}.get(kind, "check")
        seen = set()
        for item in raw_items:
            info = dict(item) if isinstance(item, dict) else {"name": str(item)}
            item_name = str(info["name"])
            name = item_name.split(":", 1)[-1] if item_name.startswith("final:") else item_name
            info = {**enriched.get(item_name, {}), **{k: v for k, v in info.items() if v not in (None, "", {})}}
            code = re.sub(r"[^A-Za-z0-9_.\-]", "_", name)[:60] or "UNKNOWN"
            if code in seen:
                continue
            seen.add(code)
            cat = str(info.get("category") or "")
            failure_type = f"{kind}:{code}"
            ev = {**base, "item": name, "cluster_key": failure_type + (f"|{cat}" if cat else "")}
            if cat:
                ev["detail_category"] = cat
            if info.get("detail"):
                ev["detail"] = info["detail"]
            if info.get("lesson_class"):
                ev["lesson_class"] = info["lesson_class"]
            hint = _final_hint(info.get("detail") or {})
            events.append(emit(rt, episode=episode, stage="S7", failure_type=failure_type,
                               symptom=f"final cut {what} {name} did not pass" + (f" ({cat})" if cat else "")
                                       + (f": {hint}" if hint else ""),
                               evidence=ev, dedupe_key=f"{episode}:{kind}:{code}:{sha}"))
        return {"status": "OK", "events": events}
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "events": events}


def record_craft_gaps(rt: Path, *, episode: str, craft_path: str | None, media_sha256: str | None = None,
                      language: str = "zh", cast_names: Iterable[Any] = (),
                      dialogue_lines: Iterable[str] = ()) -> dict[str, Any]:
    """The final reviewer's craft-standard top gaps (``<EP>_CRAFT_STANDARD.json`` written by
    final_audience_review submit) as FAILURE_OBSERVATION events, deduped per gap item and final-cut sha, so the
    collector's default clustering turns a recurring gap into a review candidate.  Privacy: the bucket is publicly
    readable -- the event carries the item id, numbers and a fix line scrubbed by exemplars.scrub_text (cast names
    -> 角色A/B, quotes -> 「…」, no dialogue run, sensitive_findings clean).  Best-effort, never raises."""
    events: list[dict[str, Any]] = []
    try:
        parsed = _read(craft_path)
        if not parsed.get("top_gaps"):
            return {"status": "NO_GAPS" if parsed else "NO_CRAFT_STANDARD_BLOCK", "events": events}
        import nalu_craft_standard as _craft  # noqa: PLC0415 -- same directory
        ex = _exemplars()
        from tools.collective_learning import contracts as _c  # noqa: PLC0415
        roles = ex.role_map(list(cast_names), "zh" if str(language).startswith("zh") else "en")
        specs = _craft.gap_events(parsed, roles=roles, dialogue_lines=dialogue_lines, scrub_text=ex.scrub_text,
                                  clean_field=ex._clean_field, sensitive=_c.sensitive_findings)
        sha = str(media_sha256 or (parsed.get("bindings") or {}).get("final_video_sha256") or "NO_MEDIA")
        for spec in specs:
            evidence = {**spec["evidence"], "final_candidate_sha256": sha if sha != "NO_MEDIA" else None,
                        "language": final_review_language(language)}
            events.append(emit(rt, episode=episode, stage=spec["stage"], failure_type=spec["failure_type"],
                               symptom=spec["symptom"], evidence=evidence,
                               dedupe_key=f"{episode}:{spec['failure_type']}:{spec['item_id']}:{sha}"))
        return {"status": "OK", "gaps": len(parsed.get("top_gaps") or []), "events": events}
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "events": events}


def record_qa_defects(rt: Path, *, episode: str, checklist_path: str | None,
                      media_sha256: str | None = None) -> dict[str, Any]:
    """The final review's must-check defects (``<EP>_QA_DEFECT_CHECKLIST.json`` written by final_audience_review
    submit) as FAILURE_OBSERVATION events ``QA_DEFECT|<item id>``, deduped per item and final-cut sha.  The specs
    carry item id, routing, timestamps and counts only (no OCR text, names or dialogue); ``emit`` scrubs again.
    Best-effort, never raises."""
    events: list[dict[str, Any]] = []
    try:
        record = _read(checklist_path)
        if not record.get("items"):
            return {"status": "NO_CHECKLIST", "events": events}
        import nalu_qa_defect_checklist as _qa  # noqa: PLC0415 -- same directory
        sha = str(media_sha256 or (record.get("bindings") or {}).get("final_video_sha256") or "NO_MEDIA")
        for spec in _qa.event_specs(record):
            evidence = {**spec["evidence"], "final_candidate_sha256": sha if sha != "NO_MEDIA" else None}
            events.append(emit(rt, episode=episode, stage=spec["stage"], failure_type=spec["failure_type"],
                               symptom=spec["symptom"], evidence=evidence,
                               dedupe_key=f"{episode}:{spec['failure_type']}:{sha}"))
        return {"status": "OK", "events": events}
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "events": events}


S6_SHEET_LEAK_TYPE = "QA_DEFECT:QA-REFERENCE-SHEET-LEAK"


def record_s6_reference_sheet_leak(rt: Path, *, episode: str, unit_id: str, detection: dict[str, Any] | None = None,
                                   clip_sha256: str | None = None) -> dict[str, Any]:
    """S6 detected that a landed H3 take shows the unit's multi-view identity sheet as its picture
    (tools/h3_reference_sheet_guard, JA-01 E04 VU-007 2026-11-21): one FAILURE_OBSERVATION
    ``QA_DEFECT:QA-REFERENCE-SHEET-LEAK`` -- a MODEL_CONSTRAINT lesson of global scope (the same in every language),
    deduped per take.  Evidence: scores / frame counts only.  Best-effort, never raises."""
    try:
        det = detection if isinstance(detection, dict) else {}
        evidence = {"cluster_key": f"{S6_SHEET_LEAK_TYPE}|{SCOPE_GLOBAL}", "item": "QA-REFERENCE-SHEET-LEAK",
                    "failure_code": "REFERENCE_SHEET_LEAK", "detail_category": SCOPE_GLOBAL,
                    "lesson_route": "MODEL_CONSTRAINT", "kb_scope": SCOPE_GLOBAL,
                    "scope_decision": {"scope": SCOPE_GLOBAL, "basis": "KIND",
                                       "reason": "the video model drew its identity reference sheet: picture-level, "
                                                 "language-independent"},
                    "detector": "h3_reference_sheet_guard.detect_leak",
                    "detail": {k: det.get(k) for k in ("leak_frames", "longest_run", "best_score")
                               if det.get(k) is not None}}
        event = emit(rt, episode=episode, stage="S6", failure_type=S6_SHEET_LEAK_TYPE,
                     symptom="H3 take shows the character's multi-view identity sheet (turnaround views / face inset "
                             "/ duplicated copies) as the picture; retried with the sheet sent as a front-view crop",
                     evidence=evidence, unit_ids=[unit_id],
                     dedupe_key=f"{episode}:{S6_SHEET_LEAK_TYPE}:{unit_id}:{clip_sha256 or 'NO_SHA'}")
        return {"status": "OK", "events": [event]}
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "events": []}


S6_CAMERA_WOBBLE_TYPE = "QA_DEFECT:QA-CAMERA-WOBBLE"


def record_s6_camera_wobble(rt: Path, *, episode: str, unit_id: str, detection: dict[str, Any] | None = None,
                            clip_sha256: str | None = None) -> dict[str, Any]:
    """S6 measured that a landed take of a locked-off unit moves the SET with the actor (tools/h3_camera_wobble, KO
    E05 on device ...0080 2026-11-21: "the person AND the background move together"): one FAILURE_OBSERVATION
    ``QA_DEFECT:QA-CAMERA-WOBBLE`` -- a MODEL_CONSTRAINT lesson of global scope (picture-level, the same in every
    language), deduped per take.  Evidence: the measured numbers only.  Best-effort, never raises."""
    try:
        det = detection if isinstance(detection, dict) else {}
        evidence = {"cluster_key": f"{S6_CAMERA_WOBBLE_TYPE}|{SCOPE_GLOBAL}", "item": "QA-CAMERA-WOBBLE",
                    "failure_code": "CAMERA_WOBBLE", "detail_category": SCOPE_GLOBAL,
                    "lesson_route": "MODEL_CONSTRAINT", "kb_scope": SCOPE_GLOBAL,
                    "scope_decision": {"scope": SCOPE_GLOBAL, "basis": "KIND",
                                       "reason": "the video model moved the whole frame with the actor on a locked-off "
                                                 "shot: picture-level, language-independent"},
                    "detector": "h3_camera_wobble.detect",
                    "detail": {k: det.get(k) for k in ("severity", "reasons", "excursion_pct", "jitter_pct",
                                                       "reversals_per_s", "coupling") if det.get(k) is not None}}
        event = emit(rt, episode=episode, stage="S6", failure_type=S6_CAMERA_WOBBLE_TYPE,
                     symptom="H3 take of a locked-off unit moves the background with the actor (whole-frame wobble); "
                             "retried once with the locked-off tripod sentence",
                     evidence=evidence, unit_ids=[unit_id],
                     dedupe_key=f"{episode}:{S6_CAMERA_WOBBLE_TYPE}:{unit_id}:{clip_sha256 or 'NO_SHA'}")
        return {"status": "OK", "events": [event]}
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "events": []}


def record_lookalike_cast(rt: Path, *, episode: str, report_path: str | None) -> dict[str, Any]:
    """The S3 cross-character similarity (``<EP>_CHARACTER_DISTINCTNESS.json``): one ``QA_DEFECT|QA-LOOKALIKE-CAST``
    event per too-similar pair (character ids and the cosine only), so the knowledge base and the next episode's
    identity design see it.  Deduped per pair and cosine.  Best-effort, never raises."""
    events: list[dict[str, Any]] = []
    try:
        report = _read(report_path)
        rows = list(report.get("too_similar") or [])
        rows += [{"a": r.get("subject_id"), "b": None, "cosine": None} for r in report.get("advisories") or []
                 if r.get("subject_id")]
        for row in rows:
            regen = [r for r in report.get("regenerate") or [] if row.get("a") in (r.get("against") or [])
                     or row.get("b") in (r.get("against") or [])]
            evidence = {"cluster_key": "QA_DEFECT|QA-LOOKALIKE-CAST", "item": "QA-LOOKALIKE-CAST",
                        "detail_category": "QA-LOOKALIKE-CAST", "failure_code": "QA_LOOKALIKE_CAST",
                        "routing": "KNOWLEDGE_BASE_AND_NEXT_EPISODE_IDENTITY_DESIGN",
                        "detail": {"pair": [row.get("a"), row.get("b")], "cosine": row.get("cosine"),
                                   "threshold": report.get("threshold"), "method": report.get("method"),
                                   "action": "REGENERATED_ONCE" if regen else "ACCEPTED_ADVISORY"}}
            events.append(emit(rt, episode=episode, stage="S3", failure_type="QA_DEFECT:QA-LOOKALIKE-CAST",
                               symptom="two different characters' identity cards look alike "
                                       f"({row.get('a')} ~ {row.get('b')}, cosine {row.get('cosine')})",
                               evidence=evidence, unit_ids=[x for x in (row.get("a"), row.get("b")) if x],
                               dedupe_key=f"{episode}:QA_DEFECT:QA-LOOKALIKE-CAST:{row.get('a')}:{row.get('b')}:"
                                          f"{row.get('cosine')}"))
        return {"status": "OK" if rows else "NONE", "events": events}
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "events": events}


#: FINAL_REVIEW:<kind> (line owner 2026-11-20: a very poor KO E01 taught the knowledge base nothing).  The kind is
#: final_fix_round.classify of the finding; the route says who can learn from it:
#:   DIRECTING_GUIDANCE  how the episode is written / directed (Codex: script, storyboard, shot specs)
#:   MODEL_CONSTRAINT    what the video / image model does wrong (a provider-prompt clause may help)
#:   ENGINE              the engine's own S7 cut / mix / captions -- never a rule (lesson_class ENGINE_THRESHOLD)
FINAL_REVIEW = "FINAL_REVIEW"
FINAL_REVIEW_ROUTES = {
    **{k: "DIRECTING_GUIDANCE" for k in ("PACING", "STORY", "LENGTH", "STATIC_SHOT_SPLIT", "OTHER", "SHOT_GRAMMAR",
                                         "HOOK", "EMOTION", "ACTING_MONOTONY")},
    **{k: "MODEL_CONSTRAINT" for k in ("BURNED_TEXT", "FACE_DRIFT", "SKIN_SHEEN", "COSTUME_IDENTITY", "LOOKALIKE",
                                       "VOICE", "ASR_MISMATCH", "HAND_ARTIFACT", "AI_ARTIFACT", "CONTINUITY",
                                       "VOICE_GENDER_MISMATCH", "REFERENCE_SHEET_LEAK", "CAMERA_WOBBLE")},
    **{k: "ENGINE" for k in ("SUBTITLE_WRAP", "BGM_FADES", "AUDIO_SMOOTHING", "DIALOGUE_TAIL_GUARD", "LETTERBOX",
                             "MASK", "SFX", "SUBTITLE_READABILITY", "EDIT_FRAGMENT")},
}
FINAL_REVIEW_ROUTE_STAGE = {"DIRECTING_GUIDANCE": "SCRIPT_AUTHORING", "MODEL_CONSTRAINT": "S6", "ENGINE": "S7"}
FINAL_REVIEW_MAX_FINDINGS = 12
FINAL_REVIEW_TEXT_MAX = 120
_LANG_RE = re.compile(r"[a-z]{2}")

#: Global vs language scope of a confirmed final-review finding (line owner 2026-11-20: "通用的问题不分语言，应该是
#: global 的 lesson 立即生效").  Every finding is GLOBAL unless it is genuinely language-dependent: spoken dialogue
#: wording, pronunciation / ASR / lip match, voice casting and timbre, subtitle text / line breaks / punctuation,
#: translation / register / honorifics, or a culture-specific norm of that language market.  Decided by
#: ``final_review_scope`` in this order: (1) structured signals -- the finding's kind and QA item; (2) the finding's
#: own text when it points one way only (speech / subtitle / translation words vs picture / edit / story words);
#: (3) the independent reviewer's ``kb_scope`` (global|language + one-line reason, written in the same review pass
#: for each problem and each confirmed Gemini finding -- no extra provider call); (3b) the multi-pass Gemini
#: finding's own ``scope_hint``; (4) GLOBAL.
SCOPE_GLOBAL = "global"
SCOPE_LANGUAGE = "language"
#: kinds whose cause lives in the dialogue language (voice casting / timbre, ASR and lip match, subtitle text)
LANGUAGE_KINDS = frozenset({"VOICE", "ASR_MISMATCH", "SUBTITLE_WRAP", "SUBTITLE_READABILITY"})
#: kinds whose cause is the picture, the edit, the model or the mix -- the same in every language
GLOBAL_KINDS = frozenset({"BURNED_TEXT", "FACE_DRIFT", "SKIN_SHEEN", "COSTUME_IDENTITY", "LOOKALIKE", "STATIC_SHOT_SPLIT",
                          "LETTERBOX", "MASK", "BGM_FADES", "AUDIO_SMOOTHING", "DIALOGUE_TAIL_GUARD", "EDIT_FRAGMENT",
                          "HAND_ARTIFACT", "AI_ARTIFACT", "CONTINUITY", "SFX", "SHOT_GRAMMAR", "HOOK", "EMOTION",
                          # 2026-11-20: a woman voiced as a man is a casting / model fault in any language; acting
                          # monotony (talking without business, one stock gesture) is direction, never language
                          "VOICE_GENDER_MISMATCH", "ACTING_MONOTONY",
                          # 2026-11-21 (JA-01 E04): H3 drew the identity sheet as the picture -- a model fault
                          "REFERENCE_SHEET_LEAK",
                          # 2026-11-21 (KO E05): the set moving with the actor on a locked-off shot
                          "CAMERA_WOBBLE"})
LANGUAGE_ITEMS = frozenset({"QA-SUBTITLE-WRAP"})
GLOBAL_ITEMS = frozenset({"QA-BURNED-TEXT", "QA-REFERENCE-SHEET-LEAK", "QA-CAMERA-WOBBLE",
                          "QA-SKIN-SHEEN-DRIFT", "QA-LOOKALIKE-CAST", "QA-OVERSIZED-MASK", "QA-BGM-DISCONTINUOUS",
                          "QA-DIALOGUE-TAIL-CUT", "LETTERBOX", "LOOK-DRIFT"})
#: text signals (lower-case substrings).  Language: what is SAID or WRITTEN in that language.
LANGUAGE_SIGNALS = (
    "wording", "word choice", "phrasing", "phrase", "pronunc", "mispronoun", "accent", "intonation", "asr",
    "transcript", "lip sync", "lip-sync", "lipsync", "subtitle", "caption text", "typo", "spelling", "punctuation",
    "line break", "translat", "register", "honorific", "politeness", "polite form", "formal speech", "speech level",
    "slang", "idiom", "grammar", "grammatical", "unnatural line", "unnatural dialogue", "dialogue sounds",
    "voice cast", "timbre", "dubbing", "native speaker", "cultural", "culture",
    "用词", "措辞", "发音", "读音", "口音", "语调", "字幕", "标点", "错别字", "错字", "翻译", "译文", "语气", "敬语",
    "称谓", "称呼", "口语化", "俚语", "成语", "语法", "病句", "台词不自然", "台词生硬", "音色", "声线", "配音", "文化",
    "习俗", "母语", "존댓말", "반말", "敬語",
)
#: Global: what is SEEN or how it is cut / told.
GLOBAL_SIGNALS = (
    "shot", "camera", "framing", "frame", "composition", "close-up", "closeup", "wide", "angle", "cut", "edit",
    "transition", "static", "frozen", "hold", "continuity", "costume", "face", "lighting", "prop", "blocking",
    "eyeline", "axis", "180", "establishing", "headroom", "crop", "hook", "opening", "ending", "cliffhanger",
    "story", "plot", "logic", "motivation", "reaction", "staging", "action", "movement", "background", "pacing",
    "rhythm", "beat", "reveal", "conflict", "scene", "visual", "on screen", "on-screen",
    "镜头", "运镜", "分镜", "景别", "构图", "特写", "近景", "远景", "全景", "剪辑", "转场", "节奏", "静止", "定格",
    "穿帮", "连贯", "服装", "脸", "光线", "道具", "走位", "视线", "轴线", "建立镜", "开场", "开头", "结尾", "钩子",
    "悬念", "剧情", "逻辑", "动机", "反应", "动作", "背景", "画面", "爽点", "冲突", "场景",
)
SCOPE_REASON_MAX = 120


def _signals(text: str, words: tuple[str, ...]) -> list[str]:
    low = str(text or "").lower()
    return [w for w in words if w in low]


def final_review_scope(finding: dict[str, Any], kind: str) -> dict[str, str]:
    """``{"scope": "global"|"language", "basis": KIND|QA_ITEM|TEXT_SIGNAL|REVIEWER|GEMINI_HINT|DEFAULT, "reason": ...}`` for one
    confirmed final-review finding (see ``SCOPE_GLOBAL`` above).  Pure, never raises."""
    item = str(finding.get("item") or "").upper()
    if kind in LANGUAGE_KINDS:
        return {"scope": SCOPE_LANGUAGE, "basis": "KIND",
                "reason": f"kind {kind}: voice / speech / subtitle text depends on the dialogue language"}
    if item in LANGUAGE_ITEMS:
        return {"scope": SCOPE_LANGUAGE, "basis": "QA_ITEM", "reason": f"{item}: subtitle text of this language"}
    if kind in GLOBAL_KINDS:
        return {"scope": SCOPE_GLOBAL, "basis": "KIND",
                "reason": f"kind {kind}: picture / model / edit / mix, the same in every language"}
    if item in GLOBAL_ITEMS:
        return {"scope": SCOPE_GLOBAL, "basis": "QA_ITEM", "reason": f"{item}: picture / edit, language-independent"}
    text = str(finding.get("text") or "")
    lang_hits, glob_hits = _signals(text, LANGUAGE_SIGNALS), _signals(text, GLOBAL_SIGNALS)
    if lang_hits and not glob_hits:
        return {"scope": SCOPE_LANGUAGE, "basis": "TEXT_SIGNAL",
                "reason": "finding is about dialogue / subtitle / translation (" + ", ".join(lang_hits[:3]) + ")"}
    if glob_hits and not lang_hits:
        return {"scope": SCOPE_GLOBAL, "basis": "TEXT_SIGNAL",
                "reason": "finding is about picture / edit / story (" + ", ".join(glob_hits[:3]) + ")"}
    reviewer = str(finding.get("kb_scope") or "").strip().lower()
    if reviewer in (SCOPE_GLOBAL, SCOPE_LANGUAGE):
        why = re.sub(r"\s+", " ", str(finding.get("kb_scope_reason") or "")).strip()
        return {"scope": reviewer, "basis": "REVIEWER", "reason": ("reviewer: " + why) if why else "reviewer"}
    hint = str(finding.get("scope_hint") or "").strip().lower()
    if hint in (SCOPE_GLOBAL, SCOPE_LANGUAGE):   # the multi-pass Gemini review's own hint, after the reviewer's
        return {"scope": hint, "basis": "GEMINI_HINT", "reason": f"video review scope_hint {hint}"}
    return {"scope": SCOPE_GLOBAL, "basis": "DEFAULT",
            "reason": ("mixed signals" if lang_hits else "no language-dependent signal") + "; default global"}


def final_review_language(language: Any) -> str:
    """``zh-CN`` / ``ko`` / ``ja_JP`` -> ``zh`` / ``ko`` / ``ja``; unknown -> ``zh`` (the historical line)."""
    head = str(language or "").strip().lower()[:2]
    return head if _LANG_RE.fullmatch(head) else "zh"


def record_final_review_findings(rt: Path, *, episode: str, report_path: str | None, checklist_path: str | None = None,
                                 media_sha256: str | None = None, language: str = "zh",
                                 cast_names: Iterable[Any] = (), dialogue_lines: Iterable[str] = (),
                                 review_round: str = "first") -> dict[str, Any]:
    """Every CONFIRMED finding of the independent final review as one FAILURE_OBSERVATION ``FINAL_REVIEW:<kind>``
    (cluster ``FINAL_REVIEW:<kind>|global``, or ``FINAL_REVIEW:<kind>|<language>`` when ``final_review_scope`` finds
    it language-dependent; evidence ``kb_scope`` + ``scope_decision`` {scope, basis, reason}): the reviewer's problems (issue | fix), its must-check DEFECTs, the
    Gemini A/V findings the reviewer CONFIRMED and an identity-colour hard fail -- exactly the set
    final_fix_round.collect_findings acts on (unverified / dismissed Gemini flags are left out).

    Evidence: kind, route (DIRECTING_GUIDANCE / MODEL_CONSTRAINT / ENGINE), source, severity, QA item, time window,
    language, the review round and a short anonymised description (cast names -> 角色A/B, quotes -> 「…」, no
    dialogue run, paths / URLs / ids removed, sensitive_findings clean; dropped when it cannot be cleaned).  ENGINE
    findings carry lesson_class ENGINE_THRESHOLD (release-train engine items, never rule candidates).  Deduped per
    finding and final-cut sha.  Best-effort, never raises."""
    events: list[dict[str, Any]] = []
    try:
        report = _read(report_path)
        if not report:
            return {"status": "NO_REVIEW_REPORT", "events": events}
        checklist = _read(checklist_path) if checklist_path else {}
        sha = str(media_sha256 or report.get("media_sha256") or "NO_MEDIA")
        bound = (checklist.get("bindings") or {}).get("final_video_sha256") if checklist else None
        if bound not in (None, sha):
            checklist = {}  # a must-check list of another cut is not a finding of this one
        import final_fix_round as _ffr  # noqa: PLC0415 -- same directory
        # the review's own findings only: S6 unresolved retries (final_fix_round.S6_SOURCE) are engine measurements
        # with their own S6 events, never "confirmed by the final review"
        findings = [f for f in _ffr.map_findings(_ffr.collect_findings(report, checklist), [])
                    if f.get("source") != getattr(_ffr, "S6_SOURCE", "S6_UNRESOLVED")]
        if not findings:
            return {"status": "NO_FINDINGS", "events": events}
        lang = final_review_language(language)
        ex = _exemplars()
        from tools.collective_learning import contracts as _c  # noqa: PLC0415
        roles = ex.role_map(list(cast_names), "zh" if lang == "zh" else "en")
        import nalu_craft_standard as _craft  # noqa: PLC0415 -- same directory
        lines = list(dialogue_lines)
        def _scrub(value: Any, limit: int) -> str | None:
            out = _craft.scrub_fix(value, roles=roles, dialogue_lines=lines, scrub_text=ex.scrub_text,
                                   clean_field=ex._clean_field)
            return out[: limit - 1].rstrip() + "…" if out and len(out) > limit else out

        for idx, f in enumerate(findings[:FINAL_REVIEW_MAX_FINDINGS]):
            kind = re.sub(r"[^A-Z0-9_]", "_", str(f.get("kind") or "OTHER").upper())[:40] or "OTHER"
            route = FINAL_REVIEW_ROUTES.get(kind, "DIRECTING_GUIDANCE")
            failure_type = f"{FINAL_REVIEW}:{kind}"
            text = _scrub(f.get("text"), FINAL_REVIEW_TEXT_MAX)
            decision = final_review_scope(f, kind)
            if decision["basis"] == "REVIEWER":
                decision["reason"] = _scrub(decision["reason"], SCOPE_REASON_MAX) or "reviewer"
            scope_key = SCOPE_GLOBAL if decision["scope"] == SCOPE_GLOBAL else lang
            detail = {k: v for k, v in {
                "source": f.get("source"), "severity": f.get("severity"), "qa_item": f.get("item"),
                "window": f.get("window"), "fix_class": f.get("class"), "description": text}.items()
                if v not in (None, "", [])}
            evidence: dict[str, Any] = {
                "cluster_key": f"{failure_type}|{scope_key}", "failure_code": kind, "detail_category": scope_key,
                "item": kind, "lesson_route": route, "language": lang, "kb_scope": decision["scope"],
                "scope_decision": decision, "confirmed": True, "confirmed_by": f.get("source"),
                "review_round": review_round, "final_candidate_sha256": sha if sha != "NO_MEDIA" else None,
                "detail": detail}
            if route == "ENGINE":
                evidence["lesson_class"] = ENGINE_THRESHOLD
            if _c.sensitive_findings(evidence):
                detail.pop("description", None)
                decision["reason"] = f"basis {decision['basis']}"
                if _c.sensitive_findings(evidence):
                    continue
            digest = hashlib.sha256(
                f"{f.get('source')}|{f.get('item')}|{f.get('window')}|{f.get('text')}".encode("utf-8")).hexdigest()[:12]
            symptom = (f"final review {str(f.get('source') or 'finding').lower()} {kind} ({route}, {scope_key})"
                       + (f": {text}" if text else ""))
            events.append(emit(rt, episode=episode, stage=FINAL_REVIEW_ROUTE_STAGE[route], failure_type=failure_type,
                               symptom=symptom, evidence=evidence,
                               dedupe_key=f"{episode}:{FINAL_REVIEW}:{kind}:{sha}:{idx}:{digest}"))
        return {"status": "OK", "findings": len(findings), "events": events}
    except Exception as exc:  # noqa: BLE001
        return {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "events": events}


def _final_hint(detail: dict[str, Any]) -> str | None:
    if detail.get("reviewer_reason"):
        return excerpt(f"score {detail.get('score')}: {detail['reviewer_reason']}", 160)
    if detail.get("findings"):
        first = detail["findings"][0]
        return excerpt(f"{first.get('gate')}: {first.get('detail')}", 160)
    if detail.get("failures"):
        return excerpt(", ".join(str(x) for x in detail["failures"][:3]), 160)
    return None


#: final-package gates that check the engine's own paperwork (ledger schema, registry, threshold profile,
#: sign-off that only exists after S8, the package manifest) -- never a property of the film
ENGINE_BOOKKEEPING_GATES = frozenset({"GIGGLE-CREDIT-LEDGER-CLOSURE", "GATE-REGISTRY-INTEGRITY",
                                      "FROZEN-THRESHOLD-PROFILE", "RELEASE-SIGNOFF-INTEGRITY",
                                      "FINAL-PACKAGE-BLOCKERS"})
#: the seven registry ids that all run tools/final_cut_quality_gates.py on the same inputs: the tool returns ONE
#: combined verdict, so one finding (typically G5's ESCALATE "problems reported, adjudication belongs to the
#: supervisor") made all seven rows FAIL.  Each id owns only its own sub-gate findings.
FINAL_CUT_SUBGATES = {
    "FINAL-CUT-VIEWING-EVIDENCE": ("G1_",),
    "FINAL-CUT-PICTURE-REPETITION": ("G2_", "G2B_"),
    "FINAL-CUT-GATE-NAMING-HONESTY": ("G3_",),
    "FINAL-CUT-WEAKEST-LINK-SCORING": ("G4_", "G4B_"),
    "FINAL-CUT-NO-SELF-WAIVER": ("G5_",),
    "FINAL-CUT-EVENT-LEDGER": ("G7_",),
    "FINAL-CUT-DIALOGUE-LEGIBILITY": ("G8_",),
}
BLOCKING_FINDING_SEVERITIES = ("BLOCKER", "INVALID")
#: AUDIENCE-SCORE-PRE-RELEASE failures that only restate another recorded fact: the technical (detector) gate
#: did not PASS, or the reviewer's REJECT_RECUT (already S7_FINAL_REVIEW_REJECT / _LOW)
AUDIENCE_SCORE_CASCADE = ("technical_gate_must_pass_before_audience_gate",)


def classify_final_gate(row: dict[str, Any]) -> dict[str, Any]:
    """One non-PASS row of the final-package stage-gate summary -> ``{"action": RECORD|SKIP, ...}``.

    SKIP reasons: EVIDENCE_NOT_PRODUCED (never invoked: a required input does not exist at S7 -- by design on
    this line, or produced later, e.g. the S8 watch report), ENGINE_BOOKKEEPING, DUPLICATE_OF_DETECTOR_EVENTS,
    COMBINED_VERDICT_NO_OWN_FINDING (a FINAL-CUT-* row whose own sub-gate has no blocking finding),
    CASCADE_OR_REVIEW_DUPLICATE (AUDIENCE-SCORE-PRE-RELEASE restating the detector gate / the review)."""
    gid = str(row.get("gate_id") or "")
    failures = [str(f) for f in row.get("failures") or [] if f]
    if row.get("invoked") is False or (failures and all(
            f.startswith(("required_evidence_missing:", "required_value_missing:", "script_binding_sha_"))
            for f in failures)):
        keys = sorted({f.split(":", 2)[1] for f in failures if f.count(":") >= 1})
        return {"action": "SKIP", "reason": "EVIDENCE_NOT_PRODUCED", "missing": keys[:8]}
    if gid in ENGINE_BOOKKEEPING_GATES:
        return {"action": "SKIP", "reason": "ENGINE_BOOKKEEPING"}
    if gid == "FINAL-CUT-AUDIENCE-DETECTORS":
        return {"action": "SKIP", "reason": "DUPLICATE_OF_DETECTOR_EVENTS"}
    result = _read(row.get("output"))
    if gid in FINAL_CUT_SUBGATES:
        own = [f for f in result.get("findings") or [] if isinstance(f, dict)
               and str(f.get("gate") or "").startswith(FINAL_CUT_SUBGATES[gid])
               and f.get("severity") in BLOCKING_FINDING_SEVERITIES]
        if not own:
            return {"action": "SKIP", "reason": "COMBINED_VERDICT_NO_OWN_FINDING",
                    "combined_status": result.get("gate_status")}
        findings = [{"gate": f.get("gate"), "severity": f.get("severity"), "detail": excerpt(f.get("detail"), 160),
                     **_scalars(f, limit=4, skip=("gate", "severity", "detail"))} for f in own[:3]]
        invalid_only = all(f.get("severity") == "INVALID" for f in own)
        return {"action": "RECORD", "category": detail_category(own[0].get("gate")),
                "detail": {"gate_status": result.get("gate_status"), "findings": findings},
                # INVALID = the reviewer's evidence could not constitute the gate: a process item, not a rule
                "lesson_class": "REVIEW_EVIDENCE_INVALID" if invalid_only else None}
    if gid == "AUDIENCE-SCORE-PRE-RELEASE":
        own = [f for f in result.get("validation_failures") or [] if f not in AUDIENCE_SCORE_CASCADE]
        if not own:
            return {"action": "SKIP", "reason": "CASCADE_OR_REVIEW_DUPLICATE",
                    "combined_status": result.get("gate_status")}
        return {"action": "RECORD", "category": detail_category(str(own[0]).split(":")[0]),
                "detail": {"gate_status": result.get("gate_status"),
                           "failures": [excerpt(f, 120) for f in own[:6]]},
                "lesson_class": "REVIEW_EVIDENCE_INVALID"}
    own = [str(f) for f in (result.get("failures") or result.get("blockers") or failures) if f]
    own = [f for f in own if f != "gate_execution_failed"] or own
    detail = {"gate_status": result.get("status") or result.get("gate_status") or row.get("implementation_status"),
              "failures": [excerpt(f, 120) for f in own[:6]]}
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    if evidence:
        detail["measured"] = _scalars(evidence.get("result") if isinstance(evidence.get("result"), dict) else evidence,
                                      limit=8) or None
    return {"action": "RECORD", "category": detail_category(own[0].split(":")[0]) if own else "",
            "detail": {k: v for k, v in detail.items() if v not in (None, [], "")}}


def record_final_gates(rt: Path, *, episode: str, summary_path: str | None, rows: Iterable[Any],
                       media_sha256: str | None, accepted_order_seq: Any = None,
                       evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify every non-PASS final-package gate row (full rows from ``summary_path``), record only the ones
    that are failures of their own (``S7_FINAL_GATE:<gate>``), and report the skipped ones (never recorded)."""
    out: dict[str, Any] = {"status": "OK", "events": []}
    try:
        summary = _read(summary_path)
        full = {str(r.get("gate_id")): r for r in summary.get("results") or summary.get("gates") or []
                if isinstance(r, dict)}
        items, skipped = [], []
        for row in rows or []:
            if not isinstance(row, dict) or not row.get("gate_id") or row.get("status") == "PASS":
                continue
            gid = str(row["gate_id"])
            verdict = classify_final_gate({**row, **full.get(gid, {})}
                                          if full.get(gid) else {**row, "failures": [row.get("first_failure")]})
            if verdict["action"] == "SKIP":
                skipped.append({"gate_id": gid, **{k: v for k, v in verdict.items() if k != "action"}})
            else:
                items.append({"name": gid, **{k: v for k, v in verdict.items() if k != "action"}})
        if items:
            rec = record_final_cut(rt, episode=episode, kind="S7_FINAL_GATE", items=items, media_sha256=media_sha256,
                                   evidence={**(evidence or {}), "gate": "final_qa_evidence_bundle"},
                                   accepted_order_seq=accepted_order_seq)
            out["events"].extend(rec.get("events") or [])
            if rec.get("status") != "OK":
                out.update({"status": rec.get("status"), "error": rec.get("error")})
        out["events"].extend({"status": "SKIPPED", **s} for s in skipped)
        out["skipped"] = skipped
    except Exception as exc:  # noqa: BLE001
        out = {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "events": out.get("events")}
    return out


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
            refs = row.get("reference_image_sha256s") or row.get("reference_sha256") \
                or row.get("reference_image_asset_ids") or []
            rows.append({"task": key, "completed": remote == "completed", "at": observed,
                         "task_id": str(row.get("task_id") or "")[:80],
                         "model": row.get("provider_model") or row.get("model"),
                         "prompt_sha": str(row.get("prompt_sha256") or "")[:12] or None,
                         "references": len(refs) if isinstance(refs, list) else None,
                         "endpoint": str(row.get("endpoint") or "").rstrip("/").rsplit("/", 1)[-1] or None,
                         "failure": excerpt(re.sub(r"\((?:request id|req(?:uest)?_id)[^)]*\)", "",
                                                   str(row.get("provider_failure") or "")), 160)})
    return sorted(rows, key=lambda r: r["at"])


def asset_kind(task_key: str) -> dict[str, str]:
    """What a refused task generates, from its task key (never from the prompt text)."""
    key = str(task_key or "")
    head, _, view = key.partition("__")
    if head.startswith("CHAR-"):
        kind = "character_reference"
    elif re.match(r"^(?:E\d+-)?VU-\d+", head) or re.match(r"^E\d+-VU-", head):
        kind = "video_unit"
    elif re.match(r"^(?:E\d+-)?S\d+-\d+", head):
        kind = "keyframe"
    elif head.startswith(("SCENE-", "LOC-", "PLATE-", "SET-")):
        kind = "scene_plate"
    elif head.startswith("PROP-"):
        kind = "prop"
    else:
        kind = "other"
    out = {"asset_kind": kind}
    if view:
        out["view"] = detail_category(view) or view[:40]
    return out


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
            prompts = [r.get("prompt_sha") for r in refusals if r.get("prompt_sha")]
            content.append({"task": task, "refusals": len(refusals),
                            "task_ids": [r["task_id"] for r in refusals][-5:], "model": refusals[-1].get("model"),
                            "references": refusals[-1].get("references"), "endpoint": refusals[-1].get("endpoint"),
                            "provider_message": next((r["failure"] for r in reversed(refusals) if r.get("failure")),
                                                     None),
                            "distinct_prompts": len(set(prompts)) if prompts else None})
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
                asset = asset_kind(row["task"])
                attributes = {k: v for k, v in {
                    "endpoint": row.get("endpoint"), "reference_images": row.get("references"),
                    "distinct_prompts_across_refusals": row.get("distinct_prompts"),
                    "identical_prompt_resubmitted": (row.get("distinct_prompts") == 1
                                                     if row.get("distinct_prompts") else None)}.items()
                    if v is not None}
                failure_type = f"PROVIDER_CONTENT_REJECTION:{kind}"
                out["events"].append(emit(
                    rt, episode=episode, stage=stage, failure_type=failure_type,
                    symptom=(f"HopsAPI {row.get('model') or kind} refused the same {kind} request "
                             f"({asset['asset_kind']} {row['task']}) {row['refusals']} times (uncharged 424) while "
                             "other tasks completed: provider content risk control, not an outage"),
                    evidence={"provider": "hopsapi", "model": row.get("model"), "refusals": row["refusals"],
                              "task_ids": row["task_ids"], "classifier": "nalu_knowledge_events.classify_424s",
                              **asset, "detail_category": asset["asset_kind"],
                              "cluster_key": f"{failure_type}|{asset['asset_kind']}",
                              "samples": [{"unit_id": row["task"], **asset,
                                           **({"provider_message": row["provider_message"]}
                                              if row.get("provider_message") else {}),
                                           "detail": attributes}]},
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


# --------------------------------------------------------------------------- 成功样例库 capture (S7)
SUCCESS_EXEMPLAR = "SUCCESS_EXEMPLAR"
#: failure-event prefixes that mean "this unit needed another attempt" (Q1 keyframe, Q2 video, post-gen QA)
REDO_PREFIXES = ("Q1_", "Q2_", "POSTGEN_")
QA_ROUND_TYPES = ("Q2_ROUND", "POSTGEN_ROUND")


def _exemplars():
    try:
        from tools.collective_learning import exemplars  # noqa: PLC0415
    except ImportError:
        import sys as _sys  # noqa: PLC0415
        _sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
        from tools.collective_learning import exemplars  # noqa: PLC0415
    return exemplars


def exemplar_config(rt: Path) -> dict[str, Any]:
    """Capture thresholds: exemplars.DEFAULTS, overridden by ``exemplars`` in COLLECTIVE_LEARNING_CONFIG.json and
    by NALU_EXEMPLAR_MIN_OVERALL."""
    cfg = dict(_exemplars().DEFAULTS)
    config = _read(reports_dir(rt) / "COLLECTIVE_LEARNING_CONFIG.json")
    if isinstance(config.get("exemplars"), dict):
        cfg.update({k: v for k, v in config["exemplars"].items() if k in cfg})
    env = os.environ.get("NALU_EXEMPLAR_MIN_OVERALL")
    if env:
        with contextlib.suppress(ValueError):
            cfg["min_overall"] = float(env)
    return cfg


def redo_history(rt: Path, episode: str) -> dict[str, Any]:
    """From this episode's recorded review rounds: every unit id a Q1/Q2/post-gen failure named, and whether a
    Q2 or post-generation round was recorded at all (without one, "first pass" cannot be claimed)."""
    failed: set[str] = set()
    rounds: set[str] = set()
    for row in _kel().events(Path(rt), episode=episode):
        ft = str((row.get("evidence") or {}).get("failure_type") or "")
        if ft in QA_ROUND_TYPES:
            rounds.add(ft)
        if (row.get("event_kind") or "FAILURE_OBSERVATION") == "FAILURE_OBSERVATION" and ft.startswith(REDO_PREFIXES):
            failed.update(str(u) for u in row.get("unit_ids") or [])
    return {"failed_units": failed, "rounds": sorted(rounds)}


def _first_pass(unit: dict[str, Any], failed: set[str]) -> bool:
    ids = {str(unit.get("unit_id") or "")} | {str(s) for s in unit.get("editorial_shot_ids") or []}
    if ids & failed:
        return False
    attempt = unit.get("paid_attempt")
    if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt > 1:
        return False
    if isinstance(attempt, dict) and isinstance(attempt.get("attempt"), int) and attempt["attempt"] > 1:
        return False
    return True


def record_success_exemplars(rt: Path, *, episode: str, manifest_path: str | None, review_report: str | None,
                             language: str, genre: str, model: str | None = None,
                             media_sha256: str | None = None, render_style: str | None = None) -> dict[str, Any]:
    """S7, after the independent final-audience review: record what went well (best-effort, never raises).

    * always: ``<reports>/EXEMPLAR_SCENE_PROFILE.json`` -- this episode's scene-type counts (local only), which
      the next episode's authoring injection uses to pick matching exemplars;
    * when the review is a PASS with ``overall >= min_overall``, no hard fail and every dimension
      ``>= min_dimension``: one SUCCESS_EXEMPLAR event per chosen unit that passed Q1, Q2 and post-gen QA on the
      first attempt (no failure event named it, no paid re-attempt), at most ``max_shots_per_episode``, one per
      scene type first; plus one EPISODE_PRACTICE per dimension scored ``>= practice_min_score`` (the
      reviewer's own reason, scrubbed).  Every exemplar is built and scrubbed by
      ``tools/collective_learning/exemplars.py`` and refused on any sensitive or control-language hit."""
    out: dict[str, Any] = {"status": "OK", "events": []}
    try:
        ex = _exemplars()
        cfg = exemplar_config(rt)
        manifest = _read(manifest_path)
        units = [u for u in manifest.get("units") or [] if isinstance(u, dict)]
        report = _read(review_report)
        model = str(model or next((u.get("model") for u in units if u.get("model")), "") or "UNKNOWN")
        # render_style: the caller's, else the units' own stamp (an anime unit's visual_culture_contract carries it)
        if not render_style:
            render_style = next((str((u.get("visual_culture_contract") or {}).get("render_style") or "")
                                 for u in units if isinstance(u.get("visual_culture_contract"), dict)
                                 and (u.get("visual_culture_contract") or {}).get("render_style")), "") or None
        candidates = []
        counts: dict[str, dict[str, int]] = {}
        for unit in units:
            specs = [s for s in unit.get("ordered_prompt_specs") or [] if isinstance(s, dict)]
            if not specs:
                continue
            tags = ex.unit_tags(unit, specs[0], language=language, genre=genre, model=model)
            for field in ("action_type", "shot_size", "setting", "time_of_day"):
                counts.setdefault(field, {})
                counts[field][tags[field]] = counts[field].get(tags[field], 0) + 1
            candidates.append((unit, tags))
        if counts:
            reports = reports_dir(rt)
            reports.mkdir(parents=True, exist_ok=True)
            (reports / "EXEMPLAR_SCENE_PROFILE.json").write_text(json.dumps(
                {"schema": "nalu.exemplar_scene_profile.v1", "episode": episode, "at": _now(), "language": language,
                 "genre": genre, "units": len(candidates), "counts": counts}, ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8")
        dims = {k: float(v) for k, v in (report.get("dimensions") or {}).items()
                if isinstance(v, (int, float)) and not isinstance(v, bool)}
        overall = report.get("overall")
        if not isinstance(overall, (int, float)) or isinstance(overall, bool):
            return {**out, "status": "NO_REVIEW_SCORE"}
        if (report.get("verdict") != "PASS" or report.get("hard_fail") or float(overall) < float(cfg["min_overall"])
                or any(v < float(cfg["min_dimension"]) for v in dims.values())):
            return {**out, "status": "BELOW_THRESHOLD", "overall": overall, "min_overall": cfg["min_overall"]}
        sha = str(media_sha256 or report.get("media_sha256") or "NO_MEDIA")
        history = redo_history(rt, episode)
        out["first_pass_basis"] = history["rounds"]
        if not history["rounds"]:
            out["shots"] = "NO_QA_HISTORY"
        else:
            picked, seen_types = [], set()
            first_pass = [(u, t) for u, t in candidates if _first_pass(u, history["failed_units"])]
            for pass_ in (0, 1):
                for unit, tags in first_pass:
                    key = (tags["action_type"], tags["shot_size"], tags["setting"])
                    if len(picked) >= int(cfg["max_shots_per_episode"]) or unit in picked:
                        continue
                    if pass_ == 0 and key in seen_types:
                        continue
                    seen_types.add(key)
                    picked.append(unit)
            out["first_pass_units"] = len(first_pass)
            for unit in picked:
                row = ex.shot_exemplar(unit, language=language, genre=genre, model=model, overall=float(overall),
                                       dimensions=dims, render_style=render_style)
                if row is None:
                    out["events"].append({"status": "SKIPPED", "unit_id": unit.get("unit_id"), "reason": "SCRUBBED_EMPTY"})
                    continue
                out["events"].append(_emit_exemplar(rt, episode, row, sha, [unit.get("unit_id")]))
        cast = [(r.get("character_id") or r.get("character"), r.get("character")) for u, _ in candidates
                for s in (u.get("ordered_prompt_specs") or [])[:1] if isinstance(s, dict)
                for r in s.get("cast") or [] if isinstance(r, dict)]
        cast += [(r.get("entity_id"), r.get("provider_entity_label")) for u, _ in candidates
                 for r in u.get("reference_images") or [] if isinstance(r, dict) and r.get("provider_entity_label")]
        reasons = report.get("dimension_reasons") if isinstance(report.get("dimension_reasons"), dict) else {}
        praised = sorted((d for d, v in dims.items() if v >= float(cfg["practice_min_score"])), key=lambda d: -dims[d])
        for dim in praised[: int(cfg["practices_per_episode"])]:
            row = ex.practice_exemplar(dim, dims[dim], reasons.get(dim), language=language, genre=genre, model=model,
                                       overall=float(overall), cast_names=cast, render_style=render_style)
            if row is not None:
                out["events"].append(_emit_exemplar(rt, episode, row, sha, []))
    except Exception as exc:  # noqa: BLE001
        out = {"status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:200]}", "events": out.get("events")}
    return out


def _emit_exemplar(rt: Path, episode: str, row: dict[str, Any], sha: str, unit_ids: list[Any]) -> dict[str, Any]:
    ex = _exemplars()
    tags = row.get("tags") or {}
    what = (f"{tags.get('action_type')} {tags.get('shot_size')} {tags.get('setting')}" if row["kind"] == "SHOT"
            else f"praised {(row.get('practice') or {}).get('dimension')}")
    return emit(rt, episode=episode, stage="S7", failure_type=SUCCESS_EXEMPLAR,
                symptom=f"success exemplar ({row['kind']}): {what}, final review {row['final_review']['overall']}",
                evidence={"exemplar": row, "cluster_key": f"{SUCCESS_EXEMPLAR}|{ex.type_key(row)}",
                          "final_candidate_sha256": sha if sha != "NO_MEDIA" else None},
                dedupe_key=f"{episode}:exemplar:{row['exemplar_id']}:{sha}", unit_ids=unit_ids,
                event_kind=SUCCESS_EXEMPLAR)
