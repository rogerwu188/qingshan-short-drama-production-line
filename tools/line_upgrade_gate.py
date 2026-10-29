#!/usr/bin/env python3
"""Line upgrade gate: every production line reads the knowledge base before an
episode and writes it back when the episode closes, on the engine it thinks it runs.

Two calls, line-agnostic (see docs/knowledge/LINE_UPGRADE_PROTOCOL.md):

  preflight --line <id> --episode <EP> --runtime-root <dir> [--engine-root <dir>]
      (i)   engine freshness: git HEAD vs its remote-tracking branch (no network unless
            --fetch), dirty tracked files, and engine modules shadowed by a local
            overlay (scanned: --overlay-dir, PYTHONPATH entries outside the engine,
            ``engine_overlay*`` dirs under/next to the runtime root; declared:
            --declare-overlay or env QINGSHAN_ENGINE_OVERLAY_DIRS).
      (ii)  knowledge read: exports the registry through tools/knowledge_registry.py
            and writes <runtime-root>/reports/<EP>_KNOWLEDGE_BRIEFING.json + .md.
      (iii) receipt <runtime-root>/reports/<EP>_LINE_UPGRADE_PREFLIGHT.json for `close`.

  close --line <id> --episode <EP> --runtime-root <dir> [--engine-root <dir>]
      runs the shared knowledge writer (tools/knowledge_sync_core.py) and verifies the
      preflight briefing for that episode exists (missing -> KNOWLEDGE_NOT_READ).

Statuses are advisory (exit 0) unless --strict, which makes STALE_ENGINE /
UNDECLARED_OVERLAY / KNOWLEDGE_NOT_READ exit 2.  Exit 1 = the tool itself could not
run (unreadable registry, bad arguments).  Standard library only; never fetches
unless asked, never posts to a provider, never authorizes production.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OVERLAY_ENV = "QINGSHAN_ENGINE_OVERLAY_DIRS"
BRIEFING_SCHEMA = "qingshan.knowledge_briefing.v1"
RECEIPT_SCHEMA = "qingshan.line_upgrade_receipt.v1"
CLOSE_SCHEMA = "qingshan.line_upgrade_close.v1"
# Engine sub-trees an overlay file may shadow (overlay/<rel> or overlay/<tree>/<rel>).
ENGINE_TREES = ("", "tools", "qingshan_engine")
BLOCKING = ("STALE_ENGINE", "UNDECLARED_OVERLAY", "KNOWLEDGE_NOT_READ")
# READ is a compatibility status: the briefing file was written.  It is never evidence that a rule
# was applied -- that needs an adoption receipt (tools/collective_learning/adoption.py).
READ_SEMANTICS = "READ=BRIEFING_WRITTEN_NOT_APPLIED"
COLLECTIVE_CONFIG = "COLLECTIVE_LEARNING_CONFIG.json"


# --------------------------------------------------------------------------- helpers
def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _git(engine: Path, *args: str, timeout: int = 30) -> tuple[int, str]:
    try:
        proc = subprocess.run(["git", "-C", str(engine), *args], capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, f"{type(exc).__name__}:{exc}"
    return proc.returncode, (proc.stdout or proc.stderr).strip()


def _load_engine_module(engine: Path, name: str):
    """Import <engine>/tools/<name>.py by path -- the engine being checked, not this file's."""
    path = engine / "tools" / f"{name}.py"
    if not path.is_file():
        raise FileNotFoundError(f"ENGINE_MODULE_MISSING:tools/{name}.py")
    spec = importlib.util.spec_from_file_location(f"_line_upgrade_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _reports(runtime_root: Path) -> Path:
    """Where this gate writes and reads its per-episode receipts.

    Two conventions meet here and they must agree, or close() reads a different
    directory than preflight() wrote and reports KNOWLEDGE_NOT_READ for an episode
    whose briefing is sitting on disk.  nalu_pipeline.py passes its ``RT``, which is
    ``<RUNTIME_ROOT>/runtime`` (nalu_pipeline.py:80), and the knowledge candidates
    reader in knowledge_sync_core looks in both ``<root>/reports`` and
    ``<root>/runtime/reports``.  So: use ``<root>/runtime/reports`` when that is the
    tree this root is shaped like, and ``<root>/reports`` otherwise — accepting a
    root that is already the runtime tree (E11, 2026-10-06: preflight wrote
    runtime/reports/E11_KNOWLEDGE_BRIEFING.json, close looked in reports/ and
    declared the episode had not read the knowledge base).
    """
    candidates = [runtime_root / "runtime" / "reports", runtime_root / "reports"]
    if (runtime_root / "runtime").is_dir():
        return candidates[0]
    existing = next((p for p in candidates if p.is_dir()), None)
    return existing or candidates[1]


# --------------------------------------------------------------------------- (i) engine
def engine_freshness(engine: Path, fetch: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"engine_root": str(engine)}
    code, head = _git(engine, "rev-parse", "HEAD")
    if code != 0:
        out.update(status="ENGINE_NOT_GIT", detail=head[-300:])
        return out
    out["head"] = head
    code, branch = _git(engine, "rev-parse", "--abbrev-ref", "HEAD")
    out["branch"] = branch if code == 0 else None
    code, upstream = _git(engine, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if code != 0:
        code, _ = _git(engine, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main")
        upstream = "origin/main" if code == 0 else None
    out["upstream"] = upstream
    if fetch and upstream:
        remote = upstream.split("/", 1)[0]
        code, msg = _git(engine, "fetch", "--quiet", remote, timeout=120)
        out["fetch"] = "OK" if code == 0 else f"FAILED:{msg[-200:]}"
    else:
        out["fetch"] = "NOT_REQUESTED (tracking ref as last fetched)"
    if upstream:
        _, up_sha = _git(engine, "rev-parse", upstream)
        out["upstream_head"] = up_sha
        code, counts = _git(engine, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")
        if code == 0 and len(counts.split()) == 2:
            ahead, behind = (int(x) for x in counts.split())
            out["ahead"], out["behind"] = ahead, behind
    code, dirty = _git(engine, "diff", "--name-only", "HEAD")
    out["dirty_tracked_files"] = [line for line in dirty.splitlines() if line.strip()] if code == 0 else []
    if not upstream:
        out["status"] = "NO_UPSTREAM"
    elif out.get("behind"):
        out["status"] = "STALE_ENGINE"
    else:
        out["status"] = "PASS"
    return out


def _split_dirs(value: str | None) -> list[Path]:
    return [Path(p).expanduser() for p in (value or "").split(os.pathsep) if p.strip()]


def discover_overlay_dirs(engine: Path, runtime_root: Path, explicit: list[Path]) -> list[Path]:
    """Directories that could shadow engine modules (scanned, not trusted)."""
    found: list[Path] = list(explicit)
    for entry in _split_dirs(os.environ.get("PYTHONPATH")):
        found.append(entry)
    for base in (runtime_root, runtime_root.parent):
        try:
            found.extend(p for p in base.iterdir() if p.is_dir() and p.name.startswith("engine_overlay"))
        except OSError:
            pass
    engine_r = engine.resolve()
    out: list[Path] = []
    for path in found:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if not resolved.is_dir() or resolved == engine_r or engine_r in resolved.parents:
            continue
        if resolved not in out:
            out.append(resolved)
    return out


def scan_overlay(overlay: Path, engine: Path) -> list[dict[str, Any]]:
    """Every overlay .py whose relative path also exists in the engine, with both shas."""
    rows: list[dict[str, Any]] = []
    for path in sorted(overlay.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(overlay)
        for tree in ENGINE_TREES:
            target = engine / tree / rel if tree else engine / rel
            if target.is_file():
                overlay_sha, engine_sha = _sha_file(path), _sha_file(target)
                text = path.read_text(encoding="utf-8", errors="replace")
                rows.append({
                    "module": ".".join(target.relative_to(engine).with_suffix("").parts),
                    "overlay_file": str(path), "engine_file": str(target.relative_to(engine)),
                    "overlay_sha256": overlay_sha, "engine_sha256": engine_sha,
                    "differs": overlay_sha != engine_sha,
                    "swaps_sys_modules": "sys.modules[" in text,
                })
                break
    return rows


def overlay_report(engine: Path, runtime_root: Path, scan: list[Path], declared: list[Path]) -> dict[str, Any]:
    declared_r = []
    for path in declared:
        try:
            declared_r.append(path.expanduser().resolve())
        except OSError:
            pass
    dirs = discover_overlay_dirs(engine, runtime_root, scan + declared_r)
    overlays = []
    for overlay in dirs:
        shadows = [row for row in scan_overlay(overlay, engine) if row["differs"]]
        is_declared = overlay in declared_r
        overlays.append({"dir": str(overlay), "declared": is_declared,
                         "shadowed_modules": shadows,
                         "status": ("NO_SHADOWING" if not shadows
                                    else "DECLARED_OVERLAY" if is_declared else "UNDECLARED_OVERLAY")})
    status = ("UNDECLARED_OVERLAY" if any(o["status"] == "UNDECLARED_OVERLAY" for o in overlays)
              else "DECLARED_OVERLAY" if any(o["status"] == "DECLARED_OVERLAY" for o in overlays)
              else "PASS")
    return {"status": status, "declare_with": f"--declare-overlay <dir> or env {OVERLAY_ENV}",
            "overlays": overlays}


# --------------------------------------------------------------------------- (ii) knowledge
def knowledge_briefing(engine: Path, line: str, episode: str, stage: str | None = None) -> dict[str, Any]:
    kr = _load_engine_module(engine, "knowledge_registry")
    registry_path = engine / kr.REGISTRY
    data = kr.validate(json.loads(registry_path.read_text(encoding="utf-8")), engine)
    context = kr.export_context(data, stage)
    exported_memory = kr.export_failure_memory(data)
    memory_path = engine / "knowledge" / "failure_memory.jsonl"
    file_memory: list[dict[str, Any]] = []
    if memory_path.is_file():
        for raw in memory_path.read_text(encoding="utf-8").splitlines():
            if raw.strip():
                file_memory.append(json.loads(raw))
    return {
        "schema": BRIEFING_SCHEMA,
        "line": line,
        "episode": episode,
        "generated_at": _now(),
        "registry": kr.REGISTRY,
        "registry_version": context["registry_version"],
        "registry_sha256": _sha_file(registry_path),
        "failure_memory_sha256": _sha_file(memory_path),
        "failure_memory_in_sync": file_memory == exported_memory,
        "rule_count": len(context["rules"]),
        "rule_ids": [row["id"] for row in context["rules"]],
        "production_authorization": False,
        "purpose": "READ_BEFORE_WRITING_THE_EPISODE: abstract causes to avoid, not templates to copy",
        "context": context,
        "failure_memory": exported_memory,
    }


def briefing_markdown(brief: dict[str, Any]) -> str:
    lines = [f"# {brief['episode']} knowledge briefing ({brief['line']})", "",
             f"Registry {brief['registry']} v{brief['registry_version']} sha256 `{brief['registry_sha256']}`, "
             f"{brief['rule_count']} rules, {len(brief['failure_memory'])} failure-memory rows. "
             "Read every line before writing the episode: these are causes not to repeat, not text to copy.",
             "", "## Rules", ""]
    for row in brief["context"]["rules"]:
        rule = " ".join(str(row.get("rule", "")).split())
        lines.append(f"- **{row['id']}** [{row['stage']}] ({row['status']}) {rule}")
    lines += ["", "## Failure memory (do not repeat)", ""]
    for row in brief["failure_memory"]:
        lines.append(f"- `{row['failure_code']}` [{row['stage']}] {row['knowledge_id']}: {row['do_not_repeat']}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- commands
def preflight(line: str, episode: str, runtime_root: Path, engine: Path = ROOT, *,
              scan: list[Path] | None = None, declared: list[Path] | None = None,
              fetch: bool = False, strict: bool = False, stage: str | None = None) -> dict[str, Any]:
    engine = engine.resolve()
    runtime_root = runtime_root.resolve()
    declared = list(declared or []) + _split_dirs(os.environ.get(OVERLAY_ENV))
    fresh = engine_freshness(engine, fetch)
    overlays = overlay_report(engine, runtime_root, list(scan or []), declared)
    findings: list[str] = []
    if fresh["status"] == "STALE_ENGINE":
        findings.append("STALE_ENGINE")
    if overlays["status"] == "UNDECLARED_OVERLAY":
        findings.append("UNDECLARED_OVERLAY")
    notes = [code for code in (fresh["status"],) if code in ("NO_UPSTREAM", "ENGINE_NOT_GIT")]
    if fresh.get("dirty_tracked_files"):
        notes.append("DIRTY_TRACKED_FILES")
    if overlays["status"] == "DECLARED_OVERLAY":
        notes.append("DECLARED_OVERLAY")

    reports = _reports(runtime_root)
    briefing_json = reports / f"{episode}_KNOWLEDGE_BRIEFING.json"
    briefing_md = reports / f"{episode}_KNOWLEDGE_BRIEFING.md"
    knowledge: dict[str, Any]
    try:
        brief = knowledge_briefing(engine, line, episode, stage)
        brief["engine_head"] = fresh.get("head")
        _write_json(briefing_json, brief)
        briefing_md.write_text(briefing_markdown(brief), encoding="utf-8")
        knowledge = {"status": "READ", "knowledge_status_semantics": READ_SEMANTICS,
                     "briefing": str(briefing_json), "briefing_md": str(briefing_md),
                     "briefing_sha256": _sha_file(briefing_json),
                     "registry_sha256": brief["registry_sha256"], "rule_count": brief["rule_count"],
                     "failure_memory_rows": len(brief["failure_memory"]),
                     "failure_memory_in_sync": brief["failure_memory_in_sync"]}
        if not brief["failure_memory_in_sync"]:
            notes.append("FAILURE_MEMORY_DRIFT")
    except (ValueError, OSError, KeyError, TypeError) as exc:
        knowledge = {"status": "KNOWLEDGE_REGISTRY_INVALID", "error": f"{type(exc).__name__}:{exc}"}
        findings.append("KNOWLEDGE_REGISTRY_INVALID")

    status = findings[0] if findings else "PASS"
    blocking = strict and any(code in BLOCKING for code in findings)
    receipt = {
        "schema": RECEIPT_SCHEMA, "step": "preflight", "line": line, "episode": episode,
        "generated_at": _now(), "status": status, "findings": findings, "notes": notes,
        "mode": "STRICT" if strict else "ADVISORY", "blocking": blocking,
        "engine": fresh, "overlays": overlays, "knowledge": knowledge,
        "production_authorization": False,
    }
    if (reports / COLLECTIVE_CONFIG).is_file():
        # Opt-in collective learning: lock this run's verified knowledge snapshot.  Advisory like
        # every other part of preflight -- a failure here leaves the run without collective
        # knowledge (recorded), it never blocks production or reaches the network.
        try:
            receipt["collective"] = collective_preflight(line, episode, runtime_root, engine, reports, fresh)
        except Exception as exc:  # noqa: BLE001
            receipt["collective"] = {"status": "ERROR", "error": f"{type(exc).__name__}:{exc}"[:600]}
            notes.append("COLLECTIVE_KNOWLEDGE_NOT_LOCKED")
    _write_json(reports / f"{episode}_LINE_UPGRADE_PREFLIGHT.json", receipt)
    receipt["receipt"] = str(reports / f"{episode}_LINE_UPGRADE_PREFLIGHT.json")
    return receipt


def collective_preflight(line: str, episode: str, runtime_root: Path, engine: Path, reports: Path,
                         fresh: dict[str, Any]) -> dict[str, Any]:
    """Resolve from the local verified cache, write the run knowledge lock once, record SELECTED.

    Config ``<reports>/COLLECTIVE_LEARNING_CONFIG.json`` (paths may be relative to it):
      {tenant_id, line_id, trust_store, cache_dir, channel, engine_api_version,
       capabilities: {model, aspect_ratio, language, ...}, batch_id, device_store: bool,
       revocations?: signed list path, baseline?: {path, digest},
       provider_model_version?, rubric_version?, evaluation_model_version?}
    The run id is ``<line>.<episode>.<batch_id>``: a new episode or an explicit new batch is
    what picks up a newer release; an existing lock is kept as-is.
    """
    if str(engine) not in sys.path:
        sys.path.insert(0, str(engine))
    from tools.collective_learning import adoption, bundles, device_store, runtime_wiring

    config_path = reports / COLLECTIVE_CONFIG
    config = json.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent

    def _path(value: str) -> Path:
        candidate = Path(value).expanduser()
        return candidate if candidate.is_absolute() else base / candidate

    trust_path = _path(config["trust_store"])
    cache_dir = _path(config["cache_dir"])
    trust = bundles.load_trust_store(trust_path)
    cache = bundles.BundleCache(cache_dir, trust)
    revoked: set[str] = set()
    if config.get("revocations") and _path(config["revocations"]).is_file():
        revoked = bundles.verify_revocations(json.loads(_path(config["revocations"]).read_text(encoding="utf-8")),
                                             trust)
    baseline = None
    if config.get("baseline"):
        baseline = bundles.builtin_baseline(_path(config["baseline"]["path"]), config["baseline"]["digest"])
    capabilities = {**(config.get("capabilities") or {}), "engine_api_version": config["engine_api_version"]}
    resolved = bundles.resolve_local(capabilities, cache, channel=config.get("channel", "RELEASED"),
                                     revoked=revoked, baseline=baseline)
    plan_ref = None
    try:
        from tools.collective_learning import director_score  # owned by the evaluation work; optional here
        plan_ref = director_score.latest_improvement_plan(runtime_root, before_episode=episode)
    except Exception as exc:  # noqa: BLE001 -- the plan is an input, never a precondition
        plan_ref = {"status": "UNAVAILABLE", "reason": f"{type(exc).__name__}:{exc}"[:300]}
    run_id = f"{line}.{episode}.{config.get('batch_id', 'B1')}"
    lock = bundles.lock_run(reports / "knowledge_locks", run_id, resolved=resolved,
                            engine_commit=fresh.get("head") or "UNKNOWN",
                            provider_model_version=config.get("provider_model_version", "UNKNOWN"),
                            rubric_version=config.get("rubric_version", "UNKNOWN"),
                            evaluation_model_version=config.get("evaluation_model_version", "UNKNOWN"),
                            improvement_plan_ref=plan_ref)
    store_path = None
    selected_receipts: list[str] = []
    if config.get("device_store"):
        store = device_store.DeviceStore(reports / "COLLECTIVE_DEVICE_STORE.sqlite",
                                         tenant_id=config["tenant_id"], line_id=config["line_id"])
        store_path = store.path
        if lock["lock_status"] == "CREATED":
            identity = {"tenant_id": config["tenant_id"], "line_id": config["line_id"],
                        "device_id": store.device_id, "run_id": run_id}
            for entry in lock["knowledge_bundles"]:
                for rule in entry["rules"]:
                    row = adoption.selected(identity=identity, rule=rule, stage="RUN_START", unit_ids=[],
                                            entrypoint="line_upgrade_gate.preflight", bundle_digest=entry["digest"])
                    store.record_receipt("ADOPTION", row)
                    selected_receipts.append(row["receipt_id"])
    env = runtime_wiring.child_env(lock, cache_dir=cache_dir, trust_path=trust_path,
                                   engine_api_version=config["engine_api_version"], store_path=store_path,
                                   tenant_id=config.get("tenant_id"), line_id=config.get("line_id"))
    return {
        "status": "LOCKED", "lock_status": lock["lock_status"], "run_id": run_id,
        "lock_path": lock["lock_path"], "lock_sha256": lock["lock_sha256"],
        "knowledge_bundle_digest": lock["knowledge_bundle_digest"],
        "bundles": [{k: e.get(k) for k in ("bundle_id", "version", "digest", "release_channel", "label")}
                    for e in lock["knowledge_bundles"]],
        "rejected": [{k: r.get(k) for k in ("bundle_id", "version", "digest", "reason")}
                     for r in resolved["rejected"]],
        "selected_receipt_ids": selected_receipts,
        "improvement_plan_ref": plan_ref,
        "knowledge_status_semantics": READ_SEMANTICS,
        "child_env": env,
    }


def verify_briefing(runtime_root: Path, episode: str) -> dict[str, Any]:
    reports = _reports(runtime_root)
    briefing = reports / f"{episode}_KNOWLEDGE_BRIEFING.json"
    receipt_path = reports / f"{episode}_LINE_UPGRADE_PREFLIGHT.json"
    if not briefing.is_file():
        return {"status": "KNOWLEDGE_NOT_READ", "briefing": str(briefing),
                "detail": "no preflight briefing for this episode: the knowledge base was not read "
                          "before it was written (run `line_upgrade_gate.py preflight` at episode start)"}
    receipt = {}
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    sha = _sha_file(briefing)
    expected = (receipt.get("knowledge") or {}).get("briefing_sha256")
    return {"status": "READ", "knowledge_status_semantics": READ_SEMANTICS,
            "briefing": str(briefing), "briefing_sha256": sha,
            "receipt": str(receipt_path) if receipt else None,
            "receipt_matches": bool(expected) and expected == sha,
            "preflight_status": receipt.get("status")}


def close(line: str, episode: str, runtime_root: Path, engine: Path = ROOT, *,
          extra: list[dict[str, Any]] | None = None, dry_run: bool = False,
          skip_sync: bool = False, strict: bool = False) -> dict[str, Any]:
    engine = engine.resolve()
    runtime_root = runtime_root.resolve()
    read = verify_briefing(runtime_root, episode)
    if skip_sync:
        sync = {"status": "SKIPPED_BY_CALLER"}
    else:
        try:
            core = _load_engine_module(engine, "knowledge_sync_core")
            sync = core.sync(engine, runtime_root, episode, extra=extra, dry_run=dry_run)
        except (ValueError, OSError, KeyError, ImportError) as exc:
            sync = {"status": "FAIL", "error": f"{type(exc).__name__}:{exc}"}
    findings = ["KNOWLEDGE_NOT_READ"] if read["status"] == "KNOWLEDGE_NOT_READ" else []
    if sync.get("status") == "FAIL":
        findings.append("KNOWLEDGE_SYNC_FAILED")
    status = findings[0] if findings else "PASS"
    result = {"schema": CLOSE_SCHEMA, "step": "close", "line": line, "episode": episode,
              "generated_at": _now(), "status": status, "findings": findings,
              "mode": "STRICT" if strict else "ADVISORY",
              "blocking": strict and any(code in BLOCKING for code in findings),
              "knowledge_read": read, "knowledge_sync": sync, "production_authorization": False}
    if not dry_run:
        path = _reports(runtime_root) / f"{episode}_LINE_UPGRADE_CLOSE.json"
        _write_json(path, result)
        result["receipt"] = str(path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("preflight", "close"):
        p = sub.add_parser(name)
        p.add_argument("--line", required=True)
        p.add_argument("--episode", required=True)
        p.add_argument("--runtime-root", type=Path, required=True)
        p.add_argument("--engine-root", type=Path, default=ROOT)
        p.add_argument("--strict", action="store_true", help="findings exit 2 instead of advisory 0")
    pre = sub.choices["preflight"]
    pre.add_argument("--fetch", action="store_true", help="git fetch the tracking remote first")
    pre.add_argument("--overlay-dir", type=Path, action="append", default=[],
                     help="directory to scan for engine modules it shadows (repeatable)")
    pre.add_argument("--declare-overlay", type=Path, action="append", default=[],
                     help=f"overlay the line knowingly runs (repeatable; also env {OVERLAY_ENV})")
    pre.add_argument("--stage", help="export only one registry stage")
    cl = sub.choices["close"]
    cl.add_argument("--from-file", type=Path, help="extra agent-authored knowledge rows (json list)")
    cl.add_argument("--dry-run", action="store_true")
    cl.add_argument("--skip-sync", action="store_true",
                    help="only verify the briefing (the line ran the writer itself)")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "preflight":
            result = preflight(args.line, args.episode, args.runtime_root, args.engine_root,
                               scan=args.overlay_dir, declared=args.declare_overlay, fetch=args.fetch,
                               strict=args.strict, stage=args.stage)
        else:
            extra = json.loads(args.from_file.read_text(encoding="utf-8")) if args.from_file else None
            if extra is not None and not isinstance(extra, list):
                raise ValueError("FROM_FILE_NOT_A_LIST")
            result = close(args.line, args.episode, args.runtime_root, args.engine_root, extra=extra,
                           dry_run=args.dry_run, skip_sync=args.skip_sync, strict=args.strict)
    except (ValueError, OSError) as exc:
        print(json.dumps({"status": "FAIL", "error": f"{type(exc).__name__}:{exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "KNOWLEDGE_REGISTRY_INVALID":
        return 1
    return 2 if result.get("blocking") else 0


if __name__ == "__main__":
    raise SystemExit(main())
