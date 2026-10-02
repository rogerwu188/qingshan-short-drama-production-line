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
    return runtime_root / "reports"


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
        knowledge = {"status": "READ", "briefing": str(briefing_json), "briefing_md": str(briefing_md),
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
    _write_json(reports / f"{episode}_LINE_UPGRADE_PREFLIGHT.json", receipt)
    receipt["receipt"] = str(reports / f"{episode}_LINE_UPGRADE_PREFLIGHT.json")
    return receipt


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
    return {"status": "READ", "briefing": str(briefing), "briefing_sha256": sha,
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
