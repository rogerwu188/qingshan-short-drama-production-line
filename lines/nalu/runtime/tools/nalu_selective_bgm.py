#!/usr/bin/env python3
"""nalu_selective_bgm — selective narrative BGM for the nalu line (Roger 2026-09-14: 启用选择性配乐，
BGM 通过 giggle 接口生成；E02 不加).

The writer/director declares music in the generation contract (engine rule K016 / audio_profile_binding):

    "audio_contract": {"bgm": {"mode": "SELECTIVE", "cues": [
        {"cue_id": "FLASHBACK", "scenes": ["E03-S04"],          # or "shots": ["E03-S04-02", ...]
         "narrative_function": "FLASHBACK_DREAD",                  # required by the engine gate
         "brief": "low sustained strings and a distant bowed metal drone, ...",   # exact Giggle music prompt
         "volume": 0.14, "dialogue_duck_db": -8.0}]}}

Sub-commands (all offline except `generate --paid`):

  source-plan
            contract only -> preproduction/bgm/<EP>_BGM_SOURCE_PLAN.json.  This is deliberately
            independent of the S7 release timeline so every provider POST can happen in paid S6.
  generate  Use the portable StoryClaw audio provider (``tools/storyclaw_audio_provider.py``).
            Each source has an absolute durable transaction path; ``--paid`` is the only route
            that may POST, and the caller must also supply the paid-authority environment.
  verify    Require every source-plan transaction to be completed, prompt-bound, and backed by
            on-disk candidates whose SHA-256 still matches.  Never contacts the provider.
  plan      source plan + release timeline + grouping + unit ASR -> assembly/<EP>_BGM_PLAN.json
            (cue windows on the release timeline, dialogue windows for ducking, one generation per
            distinct brief, coverage policy from E37 v12: <= 85 % coverage, >= 8 s ambience-only)
            S7 uses this only after ``verify``; it cannot submit or regenerate music.
  qa        engine tools/qa_bgm_candidates.py per generation (no vocals, media probe, natural
            no-loop coverage of the longest cue that uses that source) -> selection
  mix       ducked stem + mix onto the rendered picture (video stream copied bit-exact); writes the
            solo stem (bgm_authenticity_gate needs an audible solo track), extends the AgentCut project
            with an `Audio.BGM` track + metadata.bgm_contract / bgm_cue_policy so
            audio_postproduction_contract.validate_audio_profile and bgm_authenticity_gate can PASS.
  status    what exists / what is missing for this episode.
"""
from __future__ import annotations

import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)
import nalu_media_tools as _media
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE = Path(f"{_np.ENGINE_ROOT}")
VENV = Path(f"{_np.VENV_PYTHON}")
AUDIO_PROVIDER = ENGINE / "tools/storyclaw_audio_provider.py"
PLANNED_CREDITS_PER_TASK = 8          # E37 v12 selective BGM: {"pay": 8, "refund": 0, "net": 8}
MAX_COVERAGE_RATIO = 0.85             # E37 bgm_cue_policy
MIN_AMBIENCE_ONLY_SECONDS = 8.0
DUCK_RANGE_DB = (-10.0, -6.0)         # bgm_authenticity_gate: dialogue_duck_db must be -10..-6
DUCK_RAMP_S = 0.25
FADE_IN_S, FADE_OUT_S = 0.5, 0.75
TX_DIR = ENGINE / "workflow/tasks/giggle_bgm_transactions"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def probe_duration(path: Path) -> float:
    out = subprocess.run([_media.require_ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=False).stdout.strip()
    return float(out or 0.0)


class Paths:
    def __init__(self, episode: str, *, contract: Path | None = None, assembly: Path | None = None,
                 grouping: Path | None = None, project: Path | None = None, work: Path | None = None,
                 transactions: Path | None = None) -> None:
        self.episode = episode
        self.contract = contract or ENGINE / f"workflow/claude_writer_agent/scripts/{episode}_GENERATION_CONTRACT_v1.json"
        self.assembly = assembly or ENGINE / f"workflow/nalu/{episode}/assembly"
        self.grouping = grouping or ENGINE / f"workflow/nalu/{episode}/preproduction/{episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json"
        self.project = project or self.assembly / f"{episode}_agentcut_project.json"
        self.release_timeline = self.assembly / f"{episode}_release_timeline.json"
        self.unit_asr = self.assembly / f"{episode}_unit_asr.json"
        self.plan = self.assembly / f"{episode}_BGM_PLAN.json"
        self.selection = self.assembly / f"{episode}_BGM_SELECTION.json"
        self.stem = self.assembly / f"{episode}_bgm_stem.wav"                    # solo music, cue-only, unity gain (gate)
        self.stem_timeline = self.assembly / f"{episode}_bgm_stem_timeline.wav"  # placed, scaled, ducked (what the mix adds)
        self.mix_report = self.assembly / f"{episode}_BGM_MIX.json"
        self.work = work or ENGINE / f"workflow/nalu/{episode}/preproduction/bgm"
        self.source_plan = self.work / f"{episode}_BGM_SOURCE_PLAN.json"
        if transactions is not None and not transactions.is_absolute():
            raise SystemExit("--bgm-transactions-dir must be an absolute private path")
        self.tx = transactions or ((work / "_transactions") if work else TX_DIR / episode)


# --------------------------------------------------------------------------------------------- plan
def declaration(contract: dict) -> dict:
    bgm = (contract.get("audio_contract") or {}).get("bgm")
    if not isinstance(bgm, dict):
        raise SystemExit("audio_contract.bgm must be an object with mode/cues for the selective route")
    mode = str(bgm.get("mode") or bgm.get("usage_mode") or "").upper()
    if mode not in {"SELECTIVE", "SELECTIVE_NARRATIVE_CUES"}:
        raise SystemExit(f"audio_contract.bgm.mode is {mode or 'MISSING'}; selective BGM applies only to SELECTIVE")
    cues = bgm.get("cues") or []
    if not cues:
        raise SystemExit("audio_contract.bgm.cues is empty")
    return bgm


def _source_plan_payload(p: Paths, episode: str) -> dict[str, Any]:
    if not p.contract.is_file():
        raise SystemExit(f"generation contract missing: {p.contract}")
    contract = read_json(p.contract, {})
    if not isinstance(contract, dict):
        raise SystemExit(f"generation contract is not a JSON object: {p.contract}")
    bgm = declaration(contract)
    contract_shots = [row for row in (contract.get("shots") or []) if isinstance(row, dict)]
    shot_by_id = {str(row.get("shot_id") or ""): row for row in contract_shots
                  if str(row.get("shot_id") or "")}
    if not shot_by_id:
        raise SystemExit("generation contract has no shot_id rows")

    cues_out: list[dict[str, Any]] = []
    sources: dict[str, dict[str, Any]] = {}
    cue_ids: set[str] = set()
    for cue in bgm["cues"]:
        if not isinstance(cue, dict):
            raise SystemExit("every audio_contract.bgm.cues row must be an object")
        cue_id = str(cue.get("cue_id") or "").strip()
        func = str(cue.get("narrative_function") or "").strip()
        brief = str(cue.get("brief") or "").strip()
        if not cue_id or not func or not brief:
            raise SystemExit(f"cue needs cue_id, narrative_function and brief: {cue}")
        if cue_id in cue_ids:
            raise SystemExit(f"duplicate BGM cue_id: {cue_id}")
        cue_ids.add(cue_id)

        requested = [str(value) for value in (cue.get("shots") or []) if str(value)]
        for scene in cue.get("scenes") or []:
            matched = [sid for sid, row in shot_by_id.items() if str(row.get("scene_id") or "") == str(scene)]
            if not matched:
                raise SystemExit(f"cue {cue_id} scene has no contract shots: {scene}")
            requested.extend(matched)
        shots = list(dict.fromkeys(requested))
        if not shots:
            raise SystemExit(f"cue {cue_id} names no shots/scenes")
        unknown = [sid for sid in shots if sid not in shot_by_id]
        if unknown:
            raise SystemExit(f"cue {cue_id} names unknown contract shots: {unknown}")

        duck = float(cue.get("dialogue_duck_db", -8.0))
        if not DUCK_RANGE_DB[0] <= duck <= DUCK_RANGE_DB[1]:
            raise SystemExit(f"cue {cue_id}: dialogue_duck_db {duck} outside {DUCK_RANGE_DB}")
        volume = float(cue.get("volume", 0.14))
        if not 0.05 <= volume <= 0.35:
            raise SystemExit(f"cue {cue_id}: volume {volume} outside 0.05..0.35")
        authored_seconds = round(sum(float(shot_by_id[sid].get("target_seconds") or 0) for sid in shots), 3)
        if authored_seconds <= 0:
            raise SystemExit(f"cue {cue_id} has no positive authored duration")

        key = sha256_text(brief)[:16]
        source = sources.setdefault(
            key,
            {"source_key": key, "prompt": brief, "prompt_sha256": sha256_text(brief),
             "cue_ids": [], "authored_coverage_seconds_required": 0.0},
        )
        source["cue_ids"].append(cue_id)
        source["authored_coverage_seconds_required"] = round(
            max(float(source["authored_coverage_seconds_required"]), authored_seconds), 3)
        cues_out.append({
            "cue_id": cue_id,
            "narrative_function": func,
            "source_key": key,
            "shots": shots,
            "authored_duration_seconds": authored_seconds,
            "volume": volume,
            "dialogue_duck_db": duck,
        })

    return {
        "schema": "nalu.selective_bgm_source_plan.v1",
        "episode": episode,
        "recorded_at": now(),
        "contract": str(p.contract),
        "contract_sha256": sha256_file(p.contract),
        "policy": {
            "mode": "SELECTIVE_NARRATIVE_CUES",
            "maximum_coverage_ratio": MAX_COVERAGE_RATIO,
            "minimum_ambience_only_seconds": MIN_AMBIENCE_ONLY_SECONDS,
            "dialogue_duck_db_range": list(DUCK_RANGE_DB),
        },
        "cues": cues_out,
        "generations": list(sources.values()),
        "planned_credits": PLANNED_CREDITS_PER_TASK * len(sources),
        "planned_credits_basis": "current provider observation: 8 credits per distinct instrumental music prompt",
        "timeline_dependency": "NONE_S6_SOURCE_GENERATION",
        "status": "PASS",
    }


def cmd_source_plan(a: argparse.Namespace) -> int:
    p = Paths(a.episode, contract=a.contract, assembly=a.assembly, grouping=a.grouping,
              project=a.project, work=a.work, transactions=a.bgm_transactions_dir)
    plan = _source_plan_payload(p, a.episode)
    write_json(p.source_plan, plan)
    print(json.dumps({"status": "PASS", "cues": len(plan["cues"]),
                      "generations": len(plan["generations"]),
                      "planned_credits": plan["planned_credits"],
                      "out": str(p.source_plan)}, ensure_ascii=False))
    return 0


def _load_current_source_plan(p: Paths, episode: str) -> dict[str, Any]:
    plan = read_json(p.source_plan, {})
    if not isinstance(plan, dict) or plan.get("status") != "PASS":
        raise SystemExit(f"run `source-plan` in S6 first: {p.source_plan}")
    if plan.get("schema") != "nalu.selective_bgm_source_plan.v1" or plan.get("episode") != episode:
        raise SystemExit("BGM source plan schema/episode mismatch")
    if not p.contract.is_file() or plan.get("contract_sha256") != sha256_file(p.contract):
        raise SystemExit("BGM source plan is stale for the current generation contract; rerun S6")
    return plan


def _transaction_candidates(tx: dict[str, Any]) -> list[dict[str, Any]]:
    result = tx.get("result") if isinstance(tx.get("result"), dict) else {}
    rows = result.get("files") or []
    return [row for row in rows if isinstance(row, dict)]


def _completed_transaction(tx_path: Path, generation: dict[str, Any]) -> tuple[bool, list[str]]:
    tx = read_json(tx_path, {})
    failures: list[str] = []
    if not isinstance(tx, dict) or tx.get("schema") != "qingshan.storyclaw_audio_transaction.v1":
        return False, ["TRANSACTION_MISSING_OR_SCHEMA_INVALID"]
    if tx.get("state") != "TERMINAL_COMPLETED":
        failures.append(f"STATE_{tx.get('state') or 'MISSING'}")
    request = tx.get("request") if isinstance(tx.get("request"), dict) else {}
    if request.get("prompt_sha256") != generation.get("prompt_sha256"):
        failures.append("PROMPT_SHA256_MISMATCH")
    if request.get("instrumental") is not True:
        failures.append("INSTRUMENTAL_BINDING_MISSING")
    authority = tx.get("paid_authority") if isinstance(tx.get("paid_authority"), dict) else {}
    if (authority.get("config_lock") != "1" or not authority.get("authorization_ref")
            or not str(authority.get("order_seq") or "").isdigit()
            or not re.fullmatch(r"[0-9a-f]{64}", str(authority.get("orders_sha256") or ""))):
        failures.append("PAID_AUTHORITY_BINDING_INVALID")
    if not str(tx.get("task_id") or "").strip():
        failures.append("TASK_ID_MISSING")
    candidates = _transaction_candidates(tx)
    if not candidates:
        failures.append("CANDIDATES_MISSING")
    for row in candidates:
        path = Path(str(row.get("path") or ""))
        if not path.is_file():
            failures.append(f"CANDIDATE_MISSING:{path}")
        elif not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256") or "")):
            failures.append(f"CANDIDATE_SHA256_MISSING:{path}")
        elif sha256_file(path) != row.get("sha256"):
            failures.append(f"CANDIDATE_SHA256_MISMATCH:{path}")
    return not failures, failures


def _generation_transaction_state(p: Paths, generation: dict[str, Any]) -> tuple[str, list[str]]:
    key = str(generation.get("source_key") or "")
    tx_path = p.tx / f"{key}.json"
    if not tx_path.exists():
        return "NEW_SUBMISSION", []
    tx = read_json(tx_path, {})
    if not isinstance(tx, dict) or tx.get("schema") != "qingshan.storyclaw_audio_transaction.v1":
        return "BLOCKED", ["TRANSACTION_SCHEMA_INVALID"]
    request = tx.get("request") if isinstance(tx.get("request"), dict) else {}
    if request.get("prompt_sha256") != generation.get("prompt_sha256"):
        return "BLOCKED", ["TRANSACTION_PROMPT_SHA256_MISMATCH"]
    if tx.get("state") == "TERMINAL_COMPLETED":
        ok, failures = _completed_transaction(tx_path, generation)
        return ("COMPLETED", []) if ok else ("BLOCKED", failures)
    if tx.get("state") in {"TASK_ID_BOUND_QUERY_PENDING", "TASK_ID_BOUND_COMPLETED_DOWNLOAD_PENDING"}:
        return "RESUME_WITHOUT_POST", []
    return "BLOCKED", [f"TRANSACTION_STATE_{tx.get('state') or 'MISSING'}_REQUIRES_RECONCILIATION"]


def _pending_generations(
    p: Paths, source_plan: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]]]:
    pending: list[dict[str, Any]] = []
    completed: list[str] = []
    blocked: list[dict[str, Any]] = []
    for generation in source_plan.get("generations") or []:
        key = str(generation.get("source_key") or "")
        state, failures = _generation_transaction_state(p, generation)
        generation["transaction_route"] = state
        if state == "COMPLETED":
            completed.append(key)
        elif state in {"NEW_SUBMISSION", "RESUME_WITHOUT_POST"}:
            pending.append(generation)
        else:
            blocked.append({"source_key": key, "failures": failures,
                            "transaction": str(p.tx / f"{key}.json")})
    return pending, completed, blocked


def cmd_pending(a: argparse.Namespace) -> int:
    p = Paths(a.episode, contract=a.contract, assembly=a.assembly, grouping=a.grouping,
              project=a.project, work=a.work, transactions=a.bgm_transactions_dir)
    source_plan = _load_current_source_plan(p, a.episode)
    pending, completed, blocked = _pending_generations(p, source_plan)
    new_posts = [row["source_key"] for row in pending if row["transaction_route"] == "NEW_SUBMISSION"]
    resumes = [row["source_key"] for row in pending if row["transaction_route"] == "RESUME_WITHOUT_POST"]
    status = "PASS" if not blocked else "BLOCKED"
    print(json.dumps({"status": status, "pending": [row["source_key"] for row in pending],
                      "new_post_candidates": new_posts, "resume_without_post": resumes,
                      "completed": completed, "blocked": blocked,
                      "planned_credits": PLANNED_CREDITS_PER_TASK * len(new_posts)}, ensure_ascii=False))
    return 0 if not blocked else 2


def cmd_verify(a: argparse.Namespace) -> int:
    p = Paths(a.episode, contract=a.contract, assembly=a.assembly, grouping=a.grouping,
              project=a.project, work=a.work, transactions=a.bgm_transactions_dir)
    source_plan = _load_current_source_plan(p, a.episode)
    rows: list[dict[str, Any]] = []
    for generation in source_plan.get("generations") or []:
        key = str(generation.get("source_key") or "")
        ok, failures = _completed_transaction(p.tx / f"{key}.json", generation)
        rows.append({"source_key": key, "status": "PASS" if ok else "FAIL", "failures": failures,
                     "transaction": str(p.tx / f"{key}.json")})
    good = bool(rows) and all(row["status"] == "PASS" for row in rows)
    print(json.dumps({"status": "PASS" if good else "FAIL", "rows": rows,
                      "source_plan": str(p.source_plan)}, ensure_ascii=False))
    return 0 if good else 2


def cmd_plan(a: argparse.Namespace) -> int:
    p = Paths(a.episode, contract=a.contract, assembly=a.assembly, grouping=a.grouping,
              project=a.project, work=a.work, transactions=a.bgm_transactions_dir)
    contract = read_json(p.contract, {})
    source_plan = _load_current_source_plan(p, a.episode)
    timeline = read_json(p.release_timeline, {})
    grouping = read_json(p.grouping, {})
    asr = read_json(p.unit_asr, {}) or {}
    if not timeline or not grouping:
        raise SystemExit(f"release timeline / grouping plan missing: {p.release_timeline} {p.grouping}")
    seg_by_unit = {s["unit_id"]: s for s in timeline["segments"]}
    unit_shots = {u["unit_id"]: list(u["editorial_shot_ids"]) for u in grouping["units"]}
    shot_unit = {sid: uid for uid, shots in unit_shots.items() for sid in shots}
    shot_secs = {s["shot_id"]: float(s.get("target_seconds") or 0) for s in contract.get("shots") or []}
    content = float(timeline["content_runtime_seconds"])

    def window_for_shots(shot_ids: list[str]) -> tuple[float, float]:
        # a shot inside a unit: proportional share of the unit's rendered window
        starts, ends = [], []
        for sid in shot_ids:
            uid = shot_unit.get(sid)
            if not uid or uid not in seg_by_unit:
                raise SystemExit(f"cue shot {sid} is not on the release timeline")
            seg = seg_by_unit[uid]
            u0, u1 = float(seg["output_start"]), float(seg["output_end"])
            shots = unit_shots[uid]
            total = sum(shot_secs.get(s, 0) for s in shots) or 1.0
            before = sum(shot_secs.get(s, 0) for s in shots[:shots.index(sid)])
            s0 = u0 + (u1 - u0) * before / total
            s1 = s0 + (u1 - u0) * (shot_secs.get(sid, 0) / total)
            starts.append(s0); ends.append(s1)
        return round(min(starts), 3), round(max(ends), 3)

    cues_out = []
    for cue in source_plan["cues"]:
        cue_id = cue["cue_id"]
        func = cue["narrative_function"]
        shots = list(cue["shots"])
        t0, t1 = window_for_shots(shots)
        t1 = min(t1, content)
        duck = float(cue["dialogue_duck_db"])
        volume = float(cue["volume"])
        # dialogue windows inside the cue, from the per-unit ASR (assembly), on the release timeline
        dialogue = []
        for uid, seg in seg_by_unit.items():
            u0 = float(seg["output_start"])
            for row in asr.get(uid) or []:
                ds, de = u0 + float(row["start"]), u0 + float(row["end"])
                if de > t0 and ds < t1:
                    dialogue.append({"start": round(max(ds, t0), 3), "end": round(min(de, t1), 3), "unit_id": uid})
        cues_out.append({"cue_id": cue_id, "narrative_function": func, "source_key": cue["source_key"],
                         "shots": shots, "timeline_start": t0, "duration": round(t1 - t0, 3),
                         "volume": volume, "dialogue_duck_db": duck, "dialogue_windows": dialogue,
                         "dialogue_present": bool(dialogue)})
    cues_out.sort(key=lambda c: c["timeline_start"])
    covered = sum(c["duration"] for c in cues_out)
    failures = []
    for x, y in zip(cues_out, cues_out[1:]):
        if y["timeline_start"] < x["timeline_start"] + x["duration"]:
            failures.append(f"CUES_OVERLAP:{x['cue_id']}->{y['cue_id']}")
    ratio = round(covered / content, 6) if content else 0.0
    if ratio > MAX_COVERAGE_RATIO:
        failures.append(f"COVERAGE_RATIO_{ratio}_OVER_{MAX_COVERAGE_RATIO}")
    if content - covered < MIN_AMBIENCE_ONLY_SECONDS:
        failures.append(f"AMBIENCE_ONLY_SECONDS_{round(content - covered, 3)}_UNDER_{MIN_AMBIENCE_ONLY_SECONDS}")
    exact_seconds: dict[str, float] = {}
    for cue in cues_out:
        exact_seconds[cue["source_key"]] = max(exact_seconds.get(cue["source_key"], 0.0), float(cue["duration"]))
    generations = [{**row, "coverage_seconds_required": round(exact_seconds.get(row["source_key"], 0.0), 3)}
                   for row in source_plan["generations"]]
    plan = {"schema": "nalu.selective_bgm_plan.v1", "episode": a.episode, "recorded_at": now(),
            "contract": str(p.contract), "contract_sha256": sha256_file(p.contract),
            "source_plan": str(p.source_plan), "source_plan_sha256": sha256_file(p.source_plan),
            "release_timeline": str(p.release_timeline), "content_runtime_seconds": content,
            "policy": {"mode": "SELECTIVE_NARRATIVE_CUES", "maximum_coverage_ratio": MAX_COVERAGE_RATIO,
                       "minimum_ambience_only_seconds": MIN_AMBIENCE_ONLY_SECONDS, "dialogue_duck_db_range": DUCK_RANGE_DB,
                       "policy": "No wall-to-wall score. Native ambience, foley and dialogue stay; music only on the declared narrative cues, ducked under every spoken line."},
            "cues": cues_out, "generations": generations,
            "actual_cue_seconds": round(covered, 3), "actual_coverage_ratio": ratio,
            "actual_ambience_only_seconds": round(content - covered, 3),
            "planned_credits": source_plan["planned_credits"],
            "planned_credits_basis": source_plan["planned_credits_basis"],
            "status": "PASS" if not failures else "FAIL", "failures": failures}
    write_json(p.plan, plan)
    print(json.dumps({"status": plan["status"], "cues": len(cues_out), "generations": len(generations),
                      "coverage_ratio": ratio, "planned_credits": plan["planned_credits"], "failures": failures,
                      "out": str(p.plan)}, ensure_ascii=False))
    return 0 if not failures else 2


# ----------------------------------------------------------------------------------------- generate
def cmd_generate(a: argparse.Namespace) -> int:
    p = Paths(a.episode, contract=a.contract, assembly=a.assembly, grouping=a.grouping,
              project=a.project, work=a.work, transactions=a.bgm_transactions_dir)
    source_plan = _load_current_source_plan(p, a.episode)
    pending, completed, blocked = _pending_generations(p, source_plan)
    if blocked:
        print(json.dumps({"status": "BLOCKED", "blocked": blocked,
                          "note": "reconcile or repair the existing durable transaction; no new POST is allowed"},
                         ensure_ascii=False))
        return 2
    if not pending:
        print(json.dumps({"status": "NOTHING_TO_SUBMIT", "generations": len(source_plan["generations"]),
                          "completed": completed}, ensure_ascii=False))
        return 0
    planned = PLANNED_CREDITS_PER_TASK * sum(
        1 for row in pending if row.get("transaction_route") == "NEW_SUBMISSION")
    if not AUDIO_PROVIDER.is_file():
        raise SystemExit(f"portable StoryClaw audio provider missing: {AUDIO_PROVIDER}")
    results = []
    for gen in pending:
        key = gen["source_key"]
        out_dir = p.work / key
        tx_path = p.tx / f"{key}.json"
        argv = [str(VENV), str(AUDIO_PROVIDER), "bgm-generate", gen["prompt"],
                "--output-dir", str(out_dir.resolve()), "--transaction", str(tx_path.resolve()),
                "--poll-interval", "20", "--timeout", "1500"]
        if a.paid:
            argv.append("--paid")
        run = subprocess.run(argv, capture_output=True, text=True, check=False)
        payload = None
        for line in reversed((run.stdout or "").strip().splitlines()):
            try:
                payload = json.loads(line); break
            except Exception:  # noqa: BLE001
                continue
        results.append({
            "source_key": key,
            "exit_code": run.returncode,
            "status": (payload or {}).get("status") or "NO_JSON_RESULT",
            "ok": bool((payload or {}).get("ok")),
            "task_id": (payload or {}).get("taskId"),
            "candidates": len((payload or {}).get("files") or []),
            "transaction": str(tx_path.resolve()),
            "error": (payload or {}).get("error") or ((run.stderr or "")[-500:] if run.returncode else None),
        })
        if a.paid and (run.returncode != 0 or (payload or {}).get("status") != "completed"):
            # A response-lost or task-bound-pending transaction must be resolved
            # before another source can POST.  The next run resumes the same
            # absolute transaction and the budget ledger carries its provisional
            # 8-credit reservation; it never advances blindly to the next prompt.
            break
    if not a.paid:
        status = "DRY_RUN"
        good = all(row["exit_code"] == 0 and row["status"] == "DRY_RUN" for row in results)
    else:
        status = "PASS"
        good = all(row["exit_code"] == 0 and row["status"] == "completed" for row in results)
        if not good:
            status = "BLOCKED"
    print(json.dumps({"status": status, "results": results,
                      "pending": [g["source_key"] for g in pending], "completed_before": completed,
                      "new_post_candidates": [g["source_key"] for g in pending
                                              if g.get("transaction_route") == "NEW_SUBMISSION"],
                      "resume_without_post": [g["source_key"] for g in pending
                                              if g.get("transaction_route") == "RESUME_WITHOUT_POST"],
                      "planned_credits": planned,
                      "provider": "tools/storyclaw_audio_provider.py",
                      "note": "the S6 caller owns the budget check; credit statements are reconciled in S7"},
                     ensure_ascii=False))
    return 0 if good else 2


# ----------------------------------------------------------------------------------------------- qa
def cmd_qa(a: argparse.Namespace) -> int:
    p = Paths(a.episode, contract=a.contract, assembly=a.assembly, grouping=a.grouping,
              project=a.project, work=a.work, transactions=a.bgm_transactions_dir)
    plan = read_json(p.plan, {})
    selection = {"schema": "nalu.selective_bgm_selection.v1", "episode": a.episode, "recorded_at": now(), "sources": {}}
    failures = []
    for gen in plan.get("generations") or []:
        key = gen["source_key"]
        tx = read_json(p.tx / f"{key}.json", {})
        files = [Path(f["path"]) for f in _transaction_candidates(tx)
                 if Path(f.get("path", "")).is_file()]
        if a.candidate:   # offline test route: explicit candidate files
            files = [Path(x) for x in a.candidate]
        if not files:
            failures.append(f"NO_CANDIDATES:{key}"); continue
        out = p.work / key / "QA_BGM_CANDIDATES.json"
        argv = [str(VENV), str(ENGINE / "tools/qa_bgm_candidates.py"), "--episode", a.episode,
                "--content-seconds", str(gen["coverage_seconds_required"]), "--bgm-start-seconds", "0", "--out", str(out)]
        for f in files:
            argv += ["--candidate", str(f)]
        run = subprocess.run(argv, capture_output=True, text=True, check=False, cwd=str(ENGINE),
                             env={**os.environ, "PYTHONPATH": str(ENGINE)})
        report = read_json(out, {})
        sel = report.get("selected_path") or report.get("selected")
        sel_path = (sel.get("path") or sel.get("candidate")) if isinstance(sel, dict) else (sel if isinstance(sel, str) else None)
        if run.returncode != 0 or not sel_path:
            failures.append(f"QA_REJECTED_ALL:{key}:{(run.stdout or run.stderr)[-200:]}")
            selection["sources"][key] = {"status": "FAIL", "report": str(out)}
            continue
        selection["sources"][key] = {"status": "PASS", "report": str(out), "selected": str(sel_path),
                                     "selected_sha256": sha256_file(Path(sel_path)), "task_id": tx.get("task_id"),
                                     "transaction": str(p.tx / f"{key}.json")}
    selection["status"] = "PASS" if not failures else "FAIL"; selection["failures"] = failures
    write_json(p.selection, selection)
    print(json.dumps({"status": selection["status"], "failures": failures, "out": str(p.selection)}, ensure_ascii=False))
    return 0 if not failures else 2


# ---------------------------------------------------------------------------------------------- mix
def duck_expr(cue: dict) -> str:
    """volume expression: 1 outside dialogue, 10^(duck/20) inside, 0.25 s linear ramps (t relative to the cue)."""
    lin = 10 ** (float(cue["dialogue_duck_db"]) / 20.0)
    parts = []
    for w in cue["dialogue_windows"]:
        s = float(w["start"]) - float(cue["timeline_start"]); e = float(w["end"]) - float(cue["timeline_start"])
        r = DUCK_RAMP_S
        # trapezoid 0..1 over [s-r, s] up, [e, e+r] down
        parts.append(f"max(0,min(1,min((t-({s - r:.3f}))/{r},(({e + r:.3f})-t)/{r})))")
    if not parts:
        return "1"
    env = "max(" * (len(parts) - 1) + parts[0] + "".join(f",{x})" for x in parts[1:]) if len(parts) > 1 else parts[0]
    return f"1-(1-{lin:.4f})*({env})"


def cmd_mix(a: argparse.Namespace) -> int:
    p = Paths(a.episode, contract=a.contract, assembly=a.assembly, grouping=a.grouping,
              project=a.project, work=a.work, transactions=a.bgm_transactions_dir)
    plan = read_json(p.plan, {}); selection = read_json(p.selection, {})
    if plan.get("status") != "PASS" or selection.get("status") != "PASS":
        raise SystemExit("plan and qa must both be PASS before mix")
    source = Path(a.source)
    if not source.is_file():
        raise SystemExit(f"picture missing: {source}")
    out = Path(a.out)
    release = probe_duration(source)
    inputs = [str(source)]
    srcs = {}
    for key, row in selection["sources"].items():
        srcs[key] = len(inputs); inputs.append(row["selected"])
    filters, labels = [], []
    for i, cue in enumerate(plan["cues"]):
        idx = srcs[cue["source_key"]]
        dur = float(cue["duration"]); start = float(cue["timeline_start"])
        filters.append(
            f"[{idx}:a]atrim=start=0:end={dur:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
            f"aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"afade=t=in:st=0:d={FADE_IN_S},afade=t=out:st={max(dur - FADE_OUT_S, 0):.3f}:d={FADE_OUT_S},"
            f"volume='{duck_expr(cue)}':eval=frame,volume={float(cue['volume']):.3f},"
            f"adelay={int(round(start * 1000))}|{int(round(start * 1000))}[c{i}]")
        labels.append(f"[c{i}]")
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
                   f"apad=whole_dur={release:.3f},atrim=duration={release:.3f},asetpts=N/SR/TB[stem]")
    filters.append("[stem]asplit=2[stem_out][stem_mix]")
    filters.append("[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[native]")
    filters.append("[native][stem_mix]amix=inputs=2:duration=first:normalize=0[aout]")
    argv = [_media.require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y"]
    for x in inputs:
        argv += ["-i", x]
    argv += ["-filter_complex", ";".join(filters),
             "-map", "0:v:0", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
             "-movflags", "+faststart", str(out),
             "-map", "[stem_out]", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(p.stem_timeline)]
    run = subprocess.run(argv, capture_output=True, text=True, check=False)
    if run.returncode != 0 or not out.is_file():
        raise SystemExit("mix failed: " + (run.stderr or "")[-1500:])
    # solo stem for bgm_authenticity_gate: the music that actually plays (each cue's source segment, unity
    # gain, edge fades), concatenated without the silent gaps — the gate measures audible energy over the
    # whole file, and a selective score is silent for most of the runtime by design.
    solo_filters, solo_labels = [], []
    for i, cue in enumerate(plan["cues"]):
        idx = srcs[cue["source_key"]]; dur = float(cue["duration"])
        solo_filters.append(f"[{idx}:a]atrim=start=0:end={dur:.3f},asetpts=PTS-STARTPTS,aresample=48000,"
                            f"aformat=sample_fmts=fltp:channel_layouts=stereo,afade=t=in:st=0:d={FADE_IN_S},"
                            f"afade=t=out:st={max(dur - FADE_OUT_S, 0):.3f}:d={FADE_OUT_S}[s{i}]")
        solo_labels.append(f"[s{i}]")
    solo_filters.append("".join(solo_labels) + f"concat=n={len(solo_labels)}:v=0:a=1[solo]")
    solo_argv = [_media.require_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y"]
    for x in inputs:
        solo_argv += ["-i", x]
    solo_argv += ["-filter_complex", ";".join(solo_filters), "-map", "[solo]", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(p.stem)]
    solo = subprocess.run(solo_argv, capture_output=True, text=True, check=False)
    if solo.returncode != 0 or not p.stem.is_file():
        raise SystemExit("solo stem failed: " + (solo.stderr or "")[-800:])
    # video stream must be bit-exact
    def vhash(path: Path) -> str:
        r = subprocess.run([_media.require_ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "md5", "-"],
                           capture_output=True, text=True, check=False)
        return r.stdout.strip()
    if vhash(source) != vhash(out):
        out.unlink(missing_ok=True)
        raise SystemExit("video stream changed during mix")
    # AgentCut project: Audio.BGM track + bgm_contract (engine gates read these)
    project = read_json(p.project, {})
    clips = []
    for cue in plan["cues"]:
        row = selection["sources"][cue["source_key"]]
        clips.append({"id": f"{a.episode}-BGM-{cue['cue_id']}", "source": row["selected"], "start": cue["timeline_start"],
                      "in": 0.0, "duration": cue["duration"], "volume": cue["volume"],
                      "transitionIn": {"type": "fade", "duration": FADE_IN_S},
                      "transitionOut": {"type": "fade", "duration": FADE_OUT_S},
                      "metadata": {"cue_role": cue["narrative_function"], "dialogue_present": cue["dialogue_present"],
                                   "dialogue_duck_db": cue["dialogue_duck_db"] if cue["dialogue_present"] else 0.0,
                                   "source_sha256": row["selected_sha256"]}})
    tracks = (project.setdefault("timeline", {})).setdefault("audioTracks", [])
    tracks[:] = [t for t in tracks if t.get("id") != "Audio.BGM"]
    tracks.append({"id": "Audio.BGM", "clips": clips})
    first = next(iter(selection["sources"].values()))
    first_transaction = read_json(Path(str(first.get("transaction") or "")), {})
    paid_authority = (first_transaction.get("paid_authority")
                      if isinstance(first_transaction.get("paid_authority"), dict) else {})
    authorization_ref = str(paid_authority.get("authorization_ref") or "").strip()
    if not authorization_ref:
        raise SystemExit("BGM_TRANSACTION_PAID_AUTHORIZATION_MISSING")
    meta = project.setdefault("metadata", {})
    meta["bgm_contract"] = {
        "source_type": "GENERATED_EPISODE_BGM", "license_status": "SELF_GENERATED_ACCOUNT_OWNED",
        "usage_mode": "SELECTIVE_NARRATIVE_CUES",
        "cues": [{"cue_id": c["cue_id"], "narrative_function": c["narrative_function"],
                  "timeline_start": c["timeline_start"], "duration": c["duration"]} for c in plan["cues"]],
        "dialogue_duck_db": float(plan["cues"][0]["dialogue_duck_db"]),
        "generation_task_id": first.get("task_id") or "OFFLINE_TEST_NO_TASK",
        "generation_receipt": first.get("transaction") or "OFFLINE_TEST_NO_RECEIPT",
        "source_sha256": first["selected_sha256"],
        "credit_evidence": str(p.work / next(iter(selection["sources"])) / "CREDIT_EVIDENCE.json"),
        "generations": selection["sources"], "stem": str(p.stem),
        "authorization_ref": authorization_ref,
        "authorization_status": "BOUND_TO_GENERATION_TRANSACTION",
        "authorization_order_seq": paid_authority.get("order_seq"),
        "authorization_orders_sha256": paid_authority.get("orders_sha256"),
    }
    meta["bgm_cue_policy"] = {"mode": "SELECTIVE_NARRATIVE_CUES", **{k: v for k, v in plan["policy"].items() if k != "mode"},
                              "actual_cue_seconds": plan["actual_cue_seconds"], "actual_coverage_ratio": plan["actual_coverage_ratio"],
                              "actual_ambience_only_seconds": plan["actual_ambience_only_seconds"]}
    write_json(p.project, project)
    report = {"schema": "nalu.selective_bgm_mix.v1", "episode": a.episode, "recorded_at": now(),
              "source_picture": str(source), "source_sha256": sha256_file(source), "output": str(out),
              "output_sha256": sha256_file(out), "stem": str(p.stem), "stem_sha256": sha256_file(p.stem),
              "stem_timeline": str(p.stem_timeline), "stem_timeline_sha256": sha256_file(p.stem_timeline),
              "stem_note": "stem = cue-only solo music at unity gain (gate audibility); stem_timeline = placed, scaled and dialogue-ducked signal that was mixed",
              "video_stream_bit_exact": True, "cues": len(clips), "project_updated": str(p.project)}
    write_json(p.mix_report, report)
    print(json.dumps({"status": "PASS", "output": str(out), "stem": str(p.stem), "cues": len(clips)}, ensure_ascii=False))
    return 0


# ------------------------------------------------------------------------------- window isolation (music)
def _iso(ts: str):
    import datetime as _dt
    value = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)


def _window_isolated_ledger(tx: dict, all_tx: list, statements: list) -> dict:
    """giggle.pro books GenerateMusic Pay/Refund rows with an EMPTY project_id (observed 2026-09-15, sunoV5), so the
    exact per-task query can never match a music task.  Fallback: the rows whose created_at (provider clock, UTC)
    fall inside THIS task's own submit window [intent_recorded_at, finished_at]; the episode's music tasks
    are submitted sequentially (the portable provider polls each to completion), so the windows never overlap.  The evidence is
    labelled PASS_WINDOW_ISOLATED_LEDGER_NET — a distinct label, never presented as the exact method."""
    import datetime as _dt
    # Half-open [intent, finished): generation calls are sequential, so windows do not overlap;
    # the Pay row is booked 1-2 s after intent (observed), so no leading slack is needed and none is allowed
    slack = _dt.timedelta(seconds=0)
    try:
        end_stamp = tx.get("finished_at") or tx.get("task_id_bound_at")
        start, end = _iso(tx["intent_recorded_at"]) - slack, _iso(end_stamp) + slack
    except Exception as exc:  # noqa: BLE001
        return {"status": "FAIL_WINDOW_TIMESTAMPS_MISSING", "error": str(exc), "net_charged_credits": None}
    for other in all_tx:
        if other.get("source_key") == tx.get("source_key") or not other.get("intent_recorded_at") \
                or not (other.get("finished_at") or other.get("task_id_bound_at")):
            continue
        o0 = _iso(other["intent_recorded_at"]) - slack
        o1 = _iso(other.get("finished_at") or other.get("task_id_bound_at")) + slack
        if o0 < end and start < o1:
            return {"status": "FAIL_WINDOW_OVERLAP", "overlaps": other.get("source_key"), "net_charged_credits": None}

    def _ts(row):
        return _dt.datetime.strptime(str(row.get("created_at")), "%Y-%m-%d %H:%M:%S").replace(tzinfo=_dt.timezone.utc)
    stamped = [r for r in statements if r.get("created_at")]
    if not stamped or min(_ts(r) for r in stamped) > start:
        return {"status": "FAIL_STATEMENT_PAGE_TOO_SHORT", "net_charged_credits": None}
    inside = [r for r in stamped if start <= _ts(r) < end]
    music = [r for r in inside if r.get("event_description") == "GenerateMusic" and r.get("event_type") in ("Pay", "Refund")]
    other_events = sorted({str(r.get("event_description")) for r in inside if r not in music})
    pays = [r for r in music if r["event_type"] == "Pay"]
    if len(pays) != 1:
        return {"status": f"FAIL_WINDOW_PAY_ROW_COUNT_{len(pays)}", "statement_rows": music, "net_charged_credits": None}
    paid = sum(abs(float(r["credit"])) for r in pays)
    refunded = sum(abs(float(r["credit"])) for r in music if r["event_type"] == "Refund")
    net = paid - refunded
    status = "PASS_ZERO_REFUNDED" if net == 0 else ("PASS_CHARGED" if net > 0 else "INVALID_NEGATIVE_NET")
    return {"status": status, "isolation": "SUBMIT_WINDOW", "endpoint": "/api/v1/payment/credit-statements",
            "method": "WINDOW_ISOLATED_GENERATE_MUSIC_PAY_MINUS_REFUND", "task_id": tx.get("task_id"),
            "window_utc": [start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")],
            "paid_credits": paid, "refunded_credits": refunded, "net_charged_credits": net,
            "matched_count": len(music), "statement_rows": music, "other_events_in_window": other_events,
            "note": "provider books GenerateMusic rows with empty project_id; the exact per-task query returned no row"}


# ----------------------------------------------------------------------------------------- reconcile
def cmd_reconcile(a: argparse.Namespace) -> int:
    """Credit provenance for every completed S6 music transaction.

    Prefer exact per-task Pay-minus-Refund.  Where the provider leaves the
    music project id empty, use the already documented sequential submit-window
    isolation and label it distinctly; never present that fallback as exact.
    """
    p = Paths(a.episode, contract=a.contract, assembly=a.assembly, grouping=a.grouping,
              project=a.project, work=a.work, transactions=a.bgm_transactions_dir)
    if not os.environ.get("GIGGLE_API_KEY"):
        raise SystemExit("GIGGLE_API_KEY not set (read-only statement query)")
    sys.path.insert(0, str(ENGINE))
    from tools.giggle_credit_statements import fetch_task_credit_net_by_task_id, _get, STATEMENT_PATH  # type: ignore
    rows = []
    all_tx = []
    for path in (sorted(p.tx.glob("*.json")) if p.tx.is_dir() else []):
        row = read_json(path, {})
        if isinstance(row, dict):
            all_tx.append({**row, "source_key": path.stem})
    statements = None
    for tx_path in (sorted(p.tx.glob("*.json")) if p.tx.is_dir() else []):
        tx = read_json(tx_path, {})
        if tx.get("state") != "TERMINAL_COMPLETED" or not tx.get("task_id"):
            continue
        ledger = fetch_task_credit_net_by_task_id(str(tx["task_id"]))
        isolation = "EXACT_PROJECT_ID"
        if str(ledger.get("status")) == "INCOMPLETE" and not ledger.get("statement_rows"):
            if statements is None:
                resp = _get(STATEMENT_PATH, {"page": 1, "page_size": 100, "project_id": ""})
                statements = ((resp.get("data") or {}).get("list") or []) if resp.get("code") == 200 else []
            ledger = {"exact_query": ledger,
                      **_window_isolated_ledger({**tx, "source_key": tx_path.stem}, all_tx, statements)}
            isolation = "SUBMIT_WINDOW"
        ok = str(ledger.get("status") or "").startswith("PASS_")
        label = "PASS_EXACT_ISOLATED_LEDGER_NET" if isolation == "EXACT_PROJECT_ID" else "PASS_WINDOW_ISOLATED_LEDGER_NET"
        net = ledger.get("net_credits", ledger.get("net_charged_credits"))
        tx["credit"] = {"net_charged_credits": net, "paid_credits": ledger.get("paid_credits"),
                        "refunded_credits": ledger.get("refunded_credits"), "statement_status": ledger.get("status"),
                        "isolation": isolation, "reconciled_at": now()}
        # The engine authenticity gate consumes ``files`` at receipt top level.
        # Keep the portable provider's canonical result untouched and expose the
        # same SHA-bound rows as a compatibility projection for that consumer.
        tx["files"] = _transaction_candidates(tx)
        write_json(tx_path, tx)
        source_key = tx_path.stem
        evidence = p.work / source_key / "CREDIT_EVIDENCE.json"
        write_json(evidence, {"schema": "nalu.bgm_credit_evidence.v1", "episode": a.episode, "task_id": tx["task_id"],
                              "status": label if ok else f"FAIL_{ledger.get('status')}", "isolation": isolation,
                              "net_charged_credits": net, "ledger": ledger, "recorded_at": now(),
                              "method": ("GET /api/v1/payment/credit-statements?project_id=<task_id>: Pay minus Refund for this task only"
                                         if isolation == "EXACT_PROJECT_ID" else
                                         "GET /api/v1/payment/credit-statements (page 1): GenerateMusic Pay minus Refund rows inside this "
                                         "task's own submit window; windows sequential and non-overlapping; provider leaves project_id empty for music")})
        rows.append({"source_key": source_key, "task_id": tx["task_id"], "status": ledger.get("status"),
                     "isolation": isolation, "net": net})
    good = bool(rows) and all(str(r["status"]).startswith("PASS_") for r in rows)
    print(json.dumps({"status": "PASS" if good else "FAIL", "rows": rows}, ensure_ascii=False))
    return 0 if good else 2


def cmd_status(a: argparse.Namespace) -> int:
    p = Paths(a.episode, contract=a.contract, assembly=a.assembly, grouping=a.grouping,
              project=a.project, work=a.work, transactions=a.bgm_transactions_dir)
    contract = read_json(p.contract, {})
    bgm = (contract.get("audio_contract") or {}).get("bgm")
    mode = (bgm.get("mode") if isinstance(bgm, dict) else str(bgm)[:40]) if bgm else None
    print(json.dumps({"episode": a.episode, "declared_mode": mode,
                      "source_plan": p.source_plan.is_file(), "plan": p.plan.is_file(),
                      "selection": p.selection.is_file(), "stem": p.stem.is_file(),
                      "transactions": sorted(x.name for x in p.tx.glob("*.json")) if p.tx.is_dir() else []}, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("source-plan", cmd_source_plan), ("pending", cmd_pending),
                     ("generate", cmd_generate), ("verify", cmd_verify), ("plan", cmd_plan),
                     ("reconcile", cmd_reconcile), ("qa", cmd_qa), ("mix", cmd_mix),
                     ("status", cmd_status)):
        s = sub.add_parser(name)
        s.add_argument("--episode", required=True)
        s.add_argument("--contract", type=Path); s.add_argument("--assembly", type=Path)
        s.add_argument("--grouping", type=Path); s.add_argument("--project", type=Path)
        s.add_argument("--work", type=Path, help="candidate/transaction work dir override (offline tests)")
        s.add_argument("--bgm-transactions-dir", type=Path,
                       help="absolute private durable transaction directory; current portable runs pass scope/Episode")
        s.set_defaults(fn=fn)
        if name == "generate":
            s.add_argument("--paid", action="store_true")
        if name == "qa":
            s.add_argument("--candidate", action="append", default=[], help="offline test: explicit candidate files")
        if name == "mix":
            s.add_argument("--source", required=True); s.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        return a.fn(a)
    except _media.MediaToolBlocked as exc:
        print(str(exc), file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
