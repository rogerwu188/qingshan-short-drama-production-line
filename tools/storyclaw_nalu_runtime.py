#!/usr/bin/env python3
"""StoryClaw adapter for the Qingshan/NALU production line.

This adapter owns deployment concerns only.  It delegates every gate and every
stage verdict to the repository's existing nalu_pipeline.py and never copies or
reimplements engine tools.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import shlex
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

ALLOWED_MODELS = {"storyclaw/gpt-6-astra", "storyclaw/claude-opus-5"}
STAGES = {f"S{i}" for i in range(1, 9)}
PUBLIC_EXCLUDES = {
    ".env", "credentials.json", "secrets.json", "SUPERVISOR_ORDERS.json",
}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def roots() -> tuple[Path, Path, Path]:
    here = Path(__file__).resolve()
    engine = Path(os.environ.get("NALU_ENGINE_ROOT", "")).expanduser() if os.environ.get("NALU_ENGINE_ROOT") else None
    if engine is None:
        for candidate in (here, *here.parents):
            if (candidate / "qingshan_engine").is_dir() and (candidate / "tools").is_dir():
                engine = candidate
                break
    if engine is None:
        raise RuntimeError("NALU_ENGINE_ROOT is required when adapter is outside the engine checkout")
    runtime = Path(os.environ.get("NALU_RUNTIME_ROOT", "")).expanduser() if os.environ.get("NALU_RUNTIME_ROOT") else None
    if runtime is None:
        runtime = Path.home() / ".qingshan-storyclaw-runtime"
    venv = Path(os.environ.get("NALU_VENV_PYTHON", "")).expanduser() if os.environ.get("NALU_VENV_PYTHON") else engine / ".qingshan-venv" / "bin" / "python"
    if not venv.exists():
        venv = Path(sys.executable)
    return engine.resolve(), runtime.resolve(), venv.resolve()


def deployment_paths(engine: Path, runtime: Path) -> dict[str, Path]:
    rt = runtime / "runtime"
    return {
        "engine": engine,
        "runtime": runtime,
        "runtime_state": rt / "pipeline_state",
        "logs": rt / "pipeline_logs",
        "reviews": rt / "reviews",
        "ledger": rt / "budget" / "ledger.json",
        "transactions": engine / "workflow" / "tasks",
        "voice_registry": rt / "voice_registry.json",
        "config": runtime / "qingshan.json",
        "run_receipts": rt / "storyclaw_runs",
        "deployment_receipt": rt / "STORYCLAW_DEPLOYMENT.json",
    }


def _json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _engine_commit(engine: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(engine), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def init_runtime(engine: Path, runtime: Path) -> dict[str, Any]:
    p = deployment_paths(engine, runtime)
    for key in ("runtime_state", "logs", "reviews", "run_receipts"):
        p[key].mkdir(parents=True, exist_ok=True)
    (runtime / "sources").mkdir(parents=True, exist_ok=True)
    (runtime / "deliverables").mkdir(parents=True, exist_ok=True)
    p["ledger"].parent.mkdir(parents=True, exist_ok=True)
    if not p["ledger"].exists():
        _write(p["ledger"], {"schema": "nalu.budget.ledger.v1", "entries": []})
    if not p["voice_registry"].exists():
        _write(p["voice_registry"], {"schema": "nalu.voice_registry.v1", "voices": []})
    if not p["config"].exists():
        _write(p["config"], {
            "schema": "qingshan.pipeline.config.v1",
            "workspace": str(runtime),
            "project": {"title": "Nalu StoryClaw", "language": "zh-CN", "aspect_ratio": "9:16"},
            "generation": {"provider": "giggle", "video_profile": "SD2_STANDARD_720P_9X16", "paid_requests_enabled": False, "max_parallel_tasks": 1},
            "quality": {"prompt_preflight_required": True, "post_generation_scope": "TECHNICAL_AND_BASIC_PLOT", "release_fail_closed": True},
            "release": {"order": ["youtube", "douyin"], "youtube": {"mode": "interactive_browser"}, "douyin": {"mode": "interactive_browser"}},
            "storyclaw": {"model_allowlist": sorted(ALLOWED_MODELS), "selected_model": "storyclaw/gpt-6-astra", "paid_requests_enabled": False},
        })
    receipt = {
        "schema": "storyclaw.nalu.deployment.v1",
        "created_at": now(),
        "engine_root": str(engine),
        "runtime_root": str(runtime),
        "venv_python": str(roots()[2]),
        "engine_commit": _engine_commit(engine),
        "private_runtime": True,
        "paid_requests_enabled": bool((_json(p["config"], {}) or {}).get("generation", {}).get("paid_requests_enabled", False)),
        "model_allowlist": sorted(ALLOWED_MODELS),
        "secret_values_included": False,
    }
    _write(p["deployment_receipt"], receipt)
    return receipt


def _flock_probe(runtime: Path) -> dict[str, Any]:
    path = runtime / "runtime" / ".storyclaw_flock_probe"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            return {"status": "PASS", "path": str(path)}
        except OSError as exc:
            return {"status": "BLOCKED", "path": str(path), "reason": str(exc)}


def preflight(engine: Path, runtime: Path) -> dict[str, Any]:
    p = deployment_paths(engine, runtime)
    checks: dict[str, Any] = {}
    checks["engine_root"] = {"status": "PASS" if (engine / "qingshan_engine").is_dir() else "BLOCKED", "path": str(engine)}
    pipeline = engine / "lines" / "nalu" / "runtime" / "tools" / "nalu_pipeline.py"
    paths_tool = pipeline.with_name("nalu_paths.py")
    checks["nalu_pipeline"] = {"status": "PASS" if pipeline.is_file() else "BLOCKED", "path": str(pipeline)}
    checks["nalu_paths"] = {"status": "PASS" if paths_tool.is_file() else "BLOCKED", "path": str(paths_tool)}
    checks["runtime_persistent"] = {"status": "PASS" if p["runtime"].is_dir() else "BLOCKED", "path": str(runtime)}
    checks["flock"] = _flock_probe(runtime)
    config = _json(p["config"], {}) or {}
    selected = config.get("storyclaw", {}).get("selected_model") or os.environ.get("STORYCLAW_MODEL", "storyclaw/gpt-6-astra")
    checks["model"] = {"status": "PASS" if selected in ALLOWED_MODELS else "BLOCKED", "selected": selected, "allowlist": sorted(ALLOWED_MODELS)}
    paid = bool(config.get("generation", {}).get("paid_requests_enabled", False))
    checks["paid_lock"] = {"status": "PASS" if not paid else "REVIEW_REQUIRED", "paid_requests_enabled": paid, "api_key_present": bool(os.environ.get("GIGGLE_API_KEY"))}
    checks["voice_registry"] = {"status": "PASS" if p["voice_registry"].is_file() else "BLOCKED", "path": str(p["voice_registry"])}
    failed = [name for name, value in checks.items() if value.get("status") == "BLOCKED"]
    return {"schema": "storyclaw.nalu.preflight.v1", "status": "PASS" if not failed else "BLOCKED", "checks": checks, "failures": failed}


def _paid_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("generation", {}).get("paid_requests_enabled", False)) and bool(config.get("storyclaw", {}).get("paid_requests_enabled", False))


def run_episode(engine: Path, runtime: Path, episode: str, from_stage: str | None, until: str | None, paid: bool, dry_run: bool) -> int:
    if not episode.startswith("E") or not episode[1:].isdigit():
        raise SystemExit("--episode must look like E06")
    if from_stage and from_stage.upper() not in STAGES:
        raise SystemExit("--from must be S1..S8")
    if until and until.upper() not in STAGES:
        raise SystemExit("--until must be S1..S8")
    p = deployment_paths(engine, runtime)
    config = _json(p["config"], {}) or {}
    selected_model = config.get("storyclaw", {}).get("selected_model") or os.environ.get("STORYCLAW_MODEL", "storyclaw/gpt-6-astra")
    if selected_model not in ALLOWED_MODELS:
        raise SystemExit(f"BLOCKED: model {selected_model!r} is not in the GPT-6/Claude Opus allowlist")
    if paid and not _paid_enabled(config):
        raise SystemExit("BLOCKED: paid requires both config generation.paid_requests_enabled and storyclaw.paid_requests_enabled")
    if paid and not os.environ.get("GIGGLE_API_KEY"):
        raise SystemExit("BLOCKED: GIGGLE_API_KEY is absent; no provider POST allowed")
    argv = [str(roots()[2]), str(engine / "lines/nalu/runtime/tools/nalu_pipeline.py"), "run", "--episode", episode]
    if dry_run:
        argv.append("--dry-run")
    if paid:
        argv.append("--paid")
    if from_stage:
        argv += ["--from", from_stage.upper()]
    if until:
        argv += ["--until", until.upper()]
    env = os.environ.copy()
    env.update({"NALU_ENGINE_ROOT": str(engine), "NALU_RUNTIME_ROOT": str(runtime), "NALU_VENV_PYTHON": str(roots()[2]), "QINGSHAN_VOICE_REGISTRY": str(p["voice_registry"])})
    if not paid:
        env.pop("GIGGLE_API_KEY", None)
    receipt = {
        "schema": "storyclaw.nalu.run.v1",
        "started_at": now(),
        "episode": episode,
        "argv": [shlex.quote(x) for x in argv],
        "paid_requested": paid,
        "paid_posts": None if paid else 0,
        "provider_posts_allowed": bool(paid),
        "dry_run": dry_run,
        "model": selected_model,
    }
    receipt_path = p["run_receipts"] / f"{episode}_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    _write(receipt_path, receipt)
    result = subprocess.run(argv, cwd=engine, env=env, check=False)
    receipt["finished_at"] = now()
    receipt["exit_code"] = result.returncode
    _write(receipt_path, receipt)
    return result.returncode


def heartbeat(runtime: Path, episode: str) -> dict[str, Any]:
    path = runtime / "runtime" / "pipeline_state" / f"{episode}.json"
    state = _json(path)
    if not isinstance(state, dict):
        return {"schema": "storyclaw.nalu.heartbeat.v1", "episode": episode, "status": "BLOCKED", "reason": "pipeline_state_missing", "path": str(path)}
    return {"schema": "storyclaw.nalu.heartbeat.v1", "episode": episode, "status": state.get("overall_status", "UNKNOWN"), "current_stage": state.get("current_stage"), "updated_at": state.get("updated_at"), "next_action": "resume from current_stage; stop for REVIEW_REQUIRED/BLOCKED/AWAITING"}


def public_bundle(engine: Path, output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    names = subprocess.check_output(["git", "-C", str(engine), "ls-files", "-z"], text=False).decode().split("\0")
    # Include this adapter even when a deployer runs the command from a
    # worktree before committing it.  Private episode/runtime paths remain
    # excluded by both the prefix and basename filters.
    adapter_root = Path(__file__).resolve().parent
    for path in adapter_root.rglob("*"):
        if path.is_file() and path.name != "BUNDLE_MANIFEST.json":
            names.append(path.relative_to(engine).as_posix())
    names = sorted({n for n in names if n and not any(Path(n).name == x for x in PUBLIC_EXCLUDES) and not n.startswith(("workflow/nalu/", "workflow/tasks/", "sources/", "deliverables/"))})
    with tempfile.TemporaryDirectory() as td:
        stage = Path(td) / "qingshan-engine"
        for name in names:
            src = engine / name
            if not src.is_file() or src.is_symlink():
                continue
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(src.read_bytes())
        manifest = {"schema": "storyclaw.nalu.public_bundle.v1", "created_at": now(), "engine_commit": _engine_commit(engine), "file_count": len(names), "private_data_included": False, "files": names}
        (stage / "tools").mkdir(parents=True, exist_ok=True)
        (stage / "tools/STORYCLAW_BUNDLE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with tarfile.open(output, "w:gz") as tar:
            tar.add(stage, arcname="qingshan-engine")
    return {"schema": "storyclaw.nalu.public_bundle_receipt.v1", "status": "PASS", "archive": str(output), "sha256": sha256(output), "private_data_included": False, "file_count": len(names)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("preflight")
    run = sub.add_parser("run")
    run.add_argument("--episode", required=True)
    run.add_argument("--from", dest="from_stage")
    run.add_argument("--until")
    run.add_argument("--paid", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    hb = sub.add_parser("heartbeat")
    hb.add_argument("--episode", required=True)
    bundle = sub.add_parser("bundle")
    bundle.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    engine, runtime, _ = roots()
    if args.command == "init":
        print(json.dumps(init_runtime(engine, runtime), ensure_ascii=False, indent=2)); return 0
    if args.command == "preflight":
        result = preflight(engine, runtime); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["status"] == "PASS" else 2
    if args.command == "heartbeat":
        print(json.dumps(heartbeat(runtime, args.episode), ensure_ascii=False, indent=2)); return 0
    if args.command == "bundle":
        print(json.dumps(public_bundle(engine, args.output), ensure_ascii=False, indent=2)); return 0
    return run_episode(engine, runtime, args.episode, args.from_stage, args.until, args.paid, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
