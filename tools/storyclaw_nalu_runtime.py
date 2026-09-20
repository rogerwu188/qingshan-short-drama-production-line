#!/usr/bin/env python3
"""StoryClaw adapter for the Qingshan/NALU production line.

This adapter owns deployment concerns only.  It delegates every gate and every
stage verdict to the repository's existing nalu_pipeline.py and never copies or
reimplements engine tools.
"""
from __future__ import annotations

import argparse
import datetime as dt
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:  # package import in tests; sibling import when executed as a script
    from tools import storyclaw_asset_plan_gate as _asset_gate
    from tools import storyclaw_project_intake as _project_intake
    from tools import storyclaw_release_discovery as _release_discovery
    from tools import storyclaw_install as _storyclaw_install
    from tools import storyclaw_upgrade_transaction as _upgrade_transaction
    from tools import storyclaw_writer_workflow as _writer_workflow
except ImportError:  # pragma: no cover - exercised by direct CLI invocation
    import storyclaw_asset_plan_gate as _asset_gate
    import storyclaw_project_intake as _project_intake
    import storyclaw_release_discovery as _release_discovery
    import storyclaw_install as _storyclaw_install
    import storyclaw_upgrade_transaction as _upgrade_transaction
    import storyclaw_writer_workflow as _writer_workflow

MODEL_PRIORITY = (
    "storyclaw/gpt-6-astra",
    "storyclaw/claude-opus-5",
    "storyclaw/gpt-5.6-sol",
)
UPGRADE_BARRIER_RELATIVE = Path("runtime/storyclaw_locks/__engine_upgrade__.lock")


@contextmanager
def _production_barrier(runtime: Path):
    """Hold a shared lock so an engine switch cannot overlap a run/heartbeat."""
    path = runtime / UPGRADE_BARRIER_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        with path.open("a+b") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SystemExit("BLOCKED: engine upgrade is in progress") from exc
            # The journal check is deliberately *after* the shared lock.  If
            # an updater won the race first, either this flock failed or its
            # durable PREPARED journal is now visible.  There is no unchecked
            # gap in which a producer can observe a half-switched pair.
            if not _upgrade_transaction.journal_path(runtime).is_file():
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                return
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise SystemExit("BLOCKED: engine upgrade recovery is in progress") from exc
            try:
                _upgrade_transaction.recover(runtime)
            except _upgrade_transaction.RecoveryBlocked as exc:
                raise SystemExit(
                    f"BLOCKED: interrupted engine upgrade recovery failed ({exc})"
                ) from exc
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        # Re-open/re-acquire SH and re-check journal. Another updater may have
        # started after recovery released EX.


def _assert_selected_engine_unchanged(engine: Path) -> None:
    configured = os.environ.get("NALU_ENGINE_ROOT")
    if not configured:
        return
    try:
        selected = Path(configured).expanduser().resolve(strict=True)
        running = engine.expanduser().resolve(strict=True)
    except OSError as exc:
        raise SystemExit("BLOCKED: selected engine is unavailable; retry after upgrade") from exc
    if selected != running:
        raise SystemExit("BLOCKED: selected engine changed during startup; retry")
ALLOWED_MODELS = set(MODEL_PRIORITY)
POLICY_PROFILE = "CURRENT_PORTABLE"
STAGES = {f"S{i}" for i in range(1, 9)}
_SAFE_SCOPE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
WORKFLOW_POLICY = {
    "script_first": True,
    "asset_matching_after_s1": True,
    "single_confirmation_before_generation": True,
    "no_per_item_user_prompt": True,
    "confirmation_required_from_stage": "S3",
}
PUBLIC_EXCLUDES = {
    ".env", "credentials.json", "secrets.json", "SUPERVISOR_ORDERS.json",
    "STORYCLAW_BUNDLE_MANIFEST.json",
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
    selector_python = runtime / "runtime/storyclaw_host/current-venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    venv = (
        Path(os.environ["NALU_VENV_PYTHON"]).expanduser()
        if os.environ.get("NALU_VENV_PYTHON")
        else selector_python if selector_python.exists()
        else engine / ".qingshan-venv" / "bin" / "python"
    )
    if not venv.exists():
        venv = Path(sys.executable)
    return engine.resolve(), runtime.resolve(), venv.resolve()


def _resolve_production_python(engine: Path, runtime: Path) -> dict[str, str]:
    """Resolve one Python target after acquiring the shared upgrade barrier.

    The configured path may be the project-local ``current-venv`` selector.
    We resolve it once and pass the immutable target to both argv and the child
    environment, so one production attempt cannot observe two dependency sets.
    """
    selector = runtime / "runtime/storyclaw_host/current-venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    configured = (
        Path(os.environ["NALU_VENV_PYTHON"]).expanduser()
        if os.environ.get("NALU_VENV_PYTHON")
        else selector if selector.exists()
        else engine / ".qingshan-venv" / "bin" / "python"
    )
    if not configured.exists() and "NALU_VENV_PYTHON" not in os.environ:
        configured = Path(sys.executable)
    try:
        resolved = configured.resolve(strict=True)
    except OSError as exc:
        raise SystemExit(
            "BLOCKED: selected NALU Python is unavailable; retry after upgrade"
        ) from exc
    if not resolved.is_file():
        raise SystemExit("BLOCKED: selected NALU Python is not a file")
    return {"configured_path": str(configured), "resolved_python": str(resolved)}


def deployment_paths(engine: Path, runtime: Path) -> dict[str, Path]:
    rt = runtime / "runtime"
    return {
        "engine": engine,
        "runtime": runtime,
        "runtime_state": rt / "pipeline_state",
        "logs": rt / "pipeline_logs",
        "reviews": rt / "reviews",
        "ledger": rt / "budget" / "ledger.json",
        # The engine still has legacy, repository-relative path contracts for
        # these two trees.  A StoryClaw deployment mounts private persistent
        # storage at the exact targets below while keeping the rest of the
        # checkout read-only.  Do not relocate or copy the engine tools.
        "workspace": engine / "workflow" / "nalu",
        "transactions": engine / "workflow" / "tasks",
        "workspace_backing": rt / "storyclaw_storage" / "workflow" / "nalu",
        "transactions_backing": rt / "storyclaw_storage" / "workflow" / "tasks",
        "voice_registry": rt / "voice_registry.json",
        "config": runtime / "qingshan.json",
        "run_receipts": rt / "storyclaw_runs",
        "run_locks": rt / "storyclaw_locks",
        "writer_layers": runtime / "writer_layers",
        "authority_receipts": rt / "line_owner_receipts",
        "deployment_receipt": rt / "STORYCLAW_DEPLOYMENT.json",
        "series_scopes": rt / "series_scopes.json",
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


def _strict_private_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("private JSON is missing or linked")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("private JSON is not an object")
    return value


def _first_install_archive_facts(
    engine: Path,
    runtime: Path,
    *,
    manifest: dict[str, Any],
    baseline: dict[str, Any],
    engine_link: Path,
) -> dict[str, Any]:
    """Reopen the exact package-authorized first-install evidence.

    The initial archive is authorized by a TalentHub manifest and one host
    install receipt whose engine facts are
    ``PACKAGE_VERIFIED_RELEASE_ARCHIVE``.  It must not borrow the later upgrade
    receipt path, because an arbitrary release manifest plus a self-authored
    upgrade receipt would otherwise be enough to invent a commit.
    """
    bootstrap_path = (
        runtime / "runtime/receipts/storyclaw_bootstrap/bootstrap.json"
    )
    bootstrap = _strict_private_json(bootstrap_path)
    commit = str(manifest.get("git_commit") or "").strip().lower()
    tag = str(manifest.get("release_tag") or "")
    bootstrap_status = bootstrap.get("status")
    pending_allowed = (
        bootstrap_status == "PREFLIGHT_PENDING"
        and os.environ.get("QINGSHAN_BOOTSTRAP_NO_PROVIDER_POSTS") == "1"
        and os.environ.get("QINGSHAN_PAID_REQUESTS_ENABLED") == "0"
        and not os.environ.get("GIGGLE_API_KEY")
    )
    if (
        bootstrap.get("schema") != "storyclaw.nalu.skill_bootstrap.v1"
        or (bootstrap_status != "PASS" and not pending_allowed)
        or bootstrap.get("git_commit") != commit
        or bootstrap.get("release_tag") != tag
        or bootstrap.get("private_runtime_root") != str(runtime)
        or Path(str(bootstrap.get("project_engine_link") or "")) != engine_link
        or Path(str(bootstrap.get("project_engine") or "")).resolve(strict=True)
        != engine
        or bootstrap.get("provider_posts") != 0
        or bootstrap.get("provider_secret_names_present") != []
    ):
        raise ValueError("bootstrap binding mismatch")

    install_root = (
        runtime / _storyclaw_install.RECEIPT_ROOT_RELATIVE
    ).resolve(strict=True)
    install_path = Path(str(bootstrap.get("host_install_receipt") or ""))
    if (
        not install_path.is_absolute()
        or install_path.is_symlink()
        or install_path.resolve(strict=True).parent != install_root
    ):
        raise ValueError("host install receipt path mismatch")
    if (
        install_path.stat().st_size
        != bootstrap.get("host_install_receipt_size_bytes")
        or sha256(install_path) != bootstrap.get("host_install_receipt_sha256")
    ):
        raise ValueError("host install receipt inventory mismatch")
    install = _strict_private_json(install_path)
    if (
        install.get("schema") != _storyclaw_install.RECEIPT_SCHEMA
        or install.get("status") != "PASS"
        or install.get("isolation_mode")
        != "PER_PROJECT_VERIFIED_ARCHIVE_VIEW"
        or install.get("secret_values_recorded") is not False
        or install.get("source_or_media_paths_touched") != []
    ):
        raise ValueError("host install receipt invalid")

    talenthub_manifest = Path(
        str(bootstrap.get("talenthub_release_manifest") or "")
    )
    package = _storyclaw_install._validate_bootstrap_talenthub_manifest(
        talenthub_manifest,
        release_tag=tag,
        git_commit=commit,
    )
    if (
        baseline.get("release_sequence") != package.get("release_sequence")
        or baseline.get("talenthub_release_manifest_sha256")
        != package.get("sha256")
        or baseline.get("validation_receipt_sha256")
        != package.get("validation_receipt_sha256")
    ):
        raise ValueError("baseline package binding mismatch")
    source_archive = Path(str(bootstrap.get("source_archive") or ""))
    project_home = engine_link.parent.parent.resolve(strict=True)
    archive_resolved = source_archive.resolve(strict=True)
    if (
        source_archive.is_symlink()
        or not source_archive.is_file()
        or not archive_resolved.is_relative_to(project_home)
        or source_archive.stat().st_size
        != bootstrap.get("source_archive_size_bytes")
        or sha256(source_archive) != bootstrap.get("source_archive_sha256")
    ):
        raise ValueError("bootstrap archive binding mismatch")
    facts = _storyclaw_install._bootstrap_archive_facts(
        engine,
        source_archive,
        package,
        release_tag=tag,
        expected_commit=commit,
    )
    initial_tree_receipt_path = (
        runtime
        / _storyclaw_install.UPGRADE_RECEIPT_ROOT_RELATIVE
        / f"{commit}.json"
    )
    initial_tree_receipt = _strict_private_json(initial_tree_receipt_path)
    if (
        initial_tree_receipt.get("schema")
        != _storyclaw_install.UPGRADE_RECEIPT_SCHEMA
        or initial_tree_receipt.get("status") != "PASS"
        or initial_tree_receipt.get("bootstrap_install") is not True
        or initial_tree_receipt.get("release_tag") != tag
        or initial_tree_receipt.get("git_commit") != commit
        or Path(str(initial_tree_receipt.get("current_engine") or ""))
        .resolve(strict=True) != engine
        or initial_tree_receipt.get("candidate_tree_sha256")
        != _storyclaw_install._tree_digest(engine)
        or initial_tree_receipt.get("source_archive_sha256")
        != package["source_archive_sha256"]
        or initial_tree_receipt.get("source_archive_size_bytes")
        != package["source_archive_size_bytes"]
        or initial_tree_receipt.get("talenthub_release_manifest_sha256")
        != package["sha256"]
        or initial_tree_receipt.get("verification_status") != "PASS"
        or initial_tree_receipt.get("release_baseline_status") != "PASS"
        or initial_tree_receipt.get("network_used") is not False
    ):
        raise ValueError("initial archive tree receipt mismatch")

    expected_engine = {
        "root": str(engine),
        "head_commit": commit,
        "release_tag": tag,
        "checkout_kind": "PACKAGE_VERIFIED_RELEASE_ARCHIVE",
        "immutable_tree_verified": True,
        "source_archive_sha256": package["source_archive_sha256"],
    }
    for key in ("engine", "base_engine"):
        row = install.get(key)
        if not isinstance(row, dict) or any(
            row.get(field) != value for field, value in expected_engine.items()
        ):
            raise ValueError(f"host install {key} mismatch")
    project_view = install.get("project_view") or {}
    link_row = install.get("project_engine_link") or {}
    if (
        project_view.get("base_engine_root") != str(engine)
        or project_view.get("engine_root") != str(engine)
        or project_view.get("commit") != commit
        or Path(str(link_row.get("path") or "")) != engine_link
        or Path(str(link_row.get("target") or "")).resolve(strict=True) != engine
        or (install.get("runtime") or {}).get("root") != str(runtime)
    ):
        raise ValueError("host install view mismatch")
    verification = install.get("verification") or {}
    if (
        verification.get("status") != "PASS"
        or verification.get("tag") != tag
        or verification.get("commit") != commit
        or verification.get("storage_probe") != "PASS"
    ):
        raise ValueError("host install verification mismatch")

    selector_path = runtime / _storyclaw_install.VENV_SELECTOR_RELATIVE
    selector = install.get("venv_selector") or {}
    dependencies = install.get("dependencies") or {}
    selector_target = selector_path.resolve(strict=True)
    selector_python = selector_path / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    if (
        not selector_path.is_symlink()
        or not selector_target.is_dir()
        or not selector_target.is_relative_to(runtime)
        or not selector_python.resolve(strict=True).is_file()
        or selector.get("status") != "PASS"
        or Path(str(selector.get("path") or "")) != selector_path
        or Path(str(selector.get("target") or "")).resolve(strict=True)
        != selector_target
        or Path(str(selector.get("python") or "")) != selector_python
        or dependencies.get("status") != "INSTALLED"
        or Path(str(dependencies.get("venv") or "")).resolve(strict=True)
        != selector_target
        or Path(str(dependencies.get("stable_python") or ""))
        != selector_python
    ):
        raise ValueError("host install venv selector mismatch")
    seal = install.get("engine_seal") or {}
    actual_seal = _storyclaw_install._engine_seal_report(engine)
    if (
        seal.get("sealed") is not True
        or seal.get("writable_path_count") != 0
        or actual_seal.get("sealed") is not True
        or actual_seal.get("writable_path_count") != 0
    ):
        raise ValueError("host install engine seal mismatch")
    return facts


def _archive_engine_commit(engine: Path, runtime: Path) -> str | None:
    """Return a commit only from a current, privately verified archive view."""
    try:
        engine = engine.expanduser().resolve(strict=True)
        runtime = runtime.expanduser().resolve(strict=True)
        if (engine / ".git").exists():
            return None
        manifest_path = engine / "RELEASE_MANIFEST.json"
        baseline_path = runtime / _storyclaw_install.CURRENT_RELEASE_STATE_RELATIVE
        config_path = runtime / "qingshan.json"
        marker_path = runtime / "runtime/project.json"
        hidden_marker_path = runtime / ".qingshan-private-runtime.json"
        manifest = _strict_private_json(manifest_path)
        baseline = _strict_private_json(baseline_path)
        config = _strict_private_json(config_path)
        marker = _strict_private_json(marker_path)
        hidden_marker = _strict_private_json(hidden_marker_path)
        commit = str(manifest.get("git_commit") or "").strip().lower()
        tag = str(manifest.get("release_tag") or "")
        configured_link = Path(str(
            (((config.get("storyclaw") or {}).get("storage") or {}).get("engine_root"))
            or ""
        ))
        marker_link = Path(str(marker.get("engine_root") or ""))
        if (
            not re.fullmatch(r"[0-9a-f]{40,64}", commit)
            or manifest.get("schema") != _storyclaw_install.ARCHIVE_RELEASE_SCHEMA
            or manifest.get("private_runtime_included") is not False
            or manifest.get("credentials_included") is not False
            or baseline.get("schema")
            != _storyclaw_install.CURRENT_RELEASE_STATE_SCHEMA
            or baseline.get("status") != "PASS"
            or baseline.get("release_tag") != tag
            or baseline.get("git_commit") != commit
            or baseline.get("signing_key_sha256")
            != _storyclaw_install.RELEASE_SIGNING_PUBLIC_KEY_SHA256
            or marker != hidden_marker
            or configured_link != marker_link
            or not configured_link.is_absolute()
            or not configured_link.is_symlink()
            or configured_link.resolve(strict=True) != engine
        ):
            return None

        bootstrap_path = (
            runtime / "runtime/receipts/storyclaw_bootstrap/bootstrap.json"
        )
        bootstrap = _json(bootstrap_path, {}) or {}
        if (
            bootstrap.get("git_commit") == commit
            and bootstrap.get("release_tag") == tag
        ):
            facts = _first_install_archive_facts(
                engine,
                runtime,
                manifest=manifest,
                baseline=baseline,
                engine_link=configured_link,
            )
        else:
            facts = _storyclaw_install._archive_engine_facts(
                engine,
                runtime,
                release_tag=tag,
                expected_commit=commit,
                require_tag=True,
            )
            upgrade_receipt = _strict_private_json(
                Path(str(facts.get("upgrade_receipt") or ""))
            )
            if upgrade_receipt.get("bootstrap_install") is True:
                return None
        if (
            facts.get("immutable_tree_verified") is not True
            or Path(str(facts.get("root") or "")).resolve(strict=True) != engine
            or facts.get("head_commit") != commit
            or facts.get("release_tag") != tag
        ):
            return None
        return commit
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        _storyclaw_install.InstallBlocked,
    ):
        return None


def _engine_commit(engine: Path, runtime: Path | None = None) -> str | None:
    try:
        raw = subprocess.check_output(
            ["git", "-C", str(engine), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        raw = None
    # Tests and embedding hosts may replace subprocess primitives.  A run
    # receipt is a durable JSON contract, so never let an opaque proxy object
    # leak into it.  A real Git commit is always a lowercase hex string.
    if isinstance(raw, str):
        commit = raw.strip().lower()
        if re.fullmatch(r"[0-9a-f]{40,64}", commit):
            return commit
    if runtime is None:
        return None
    return _archive_engine_commit(engine, runtime)


def init_runtime(
    engine: Path, runtime: Path, *, legacy_default_scope: bool = False
) -> dict[str, Any]:
    p = deployment_paths(engine, runtime)
    for key in (
        "runtime_state", "logs", "reviews", "run_receipts", "run_locks",
        "writer_layers", "authority_receipts",
        "workspace_backing", "transactions_backing",
    ):
        p[key].mkdir(parents=True, exist_ok=True)
    (runtime / "sources").mkdir(parents=True, exist_ok=True)
    (runtime / "deliverables").mkdir(parents=True, exist_ok=True)
    p["ledger"].parent.mkdir(parents=True, exist_ok=True)
    if not p["ledger"].exists():
        _write(p["ledger"], {"schema": "nalu.budget.ledger.v1", "entries": []})
    if not p["voice_registry"].exists():
        _write(p["voice_registry"], {"schema": "nalu.voice_registry.v1", "voices": []})
    storage_contract = {
        "mode": "READ_ONLY_ENGINE_WITH_PRIVATE_WRITABLE_MOUNTS",
        "engine_root": str(engine.resolve()),
        "workspace_mount_target": str(p["workspace"].absolute()),
        "workspace_backing_path": str(p["workspace_backing"].resolve()),
        "transactions_mount_target": str(p["transactions"].absolute()),
        "transactions_backing_path": str(p["transactions_backing"].resolve()),
        "writer_layers_root": str(p["writer_layers"].resolve()),
    }
    initial_scope = "NALU-YEWUJIANG" if legacy_default_scope else "UNCONFIGURED"
    if not p["config"].exists():
        _write(p["config"], {
            "schema": "qingshan.pipeline.config.v1",
            "workspace": str(runtime),
            "project": {"title": "Nalu StoryClaw", "language": "zh-CN", "aspect_ratio": "9:16"},
            "generation": {"provider": "giggle", "video_profile": "SD2_STANDARD_720P_9X16", "paid_requests_enabled": False, "max_parallel_tasks": 1},
            "authorization": {
                "confirmation_receipts_root": str(p["authority_receipts"].resolve()),
                "supervisor_orders_path": "",
                "paid_order_seq": 0,
                "latest_order_seq": 0,
                "line_owner_id": "",
            },
            "quality": {"prompt_preflight_required": True, "post_generation_scope": "TECHNICAL_AND_BASIC_PLOT", "release_fail_closed": True},
            "release": {"automatic_platform_upload_enabled": False},
            "storyclaw": {
                "model_allowlist": sorted(ALLOWED_MODELS),
                "model_priority": list(MODEL_PRIORITY),
                "series_scope_id": initial_scope,
                "policy_profile": POLICY_PROFILE,
                "paid_requests_enabled": False,
                "workflow_policy": WORKFLOW_POLICY,
                "storage": storage_contract,
            },
        })
    else:
        # Upgrade an existing private deployment in place without overwriting
        # its project, provider, budget, or credential settings.
        config = _json(p["config"], {}) or {}
        storyclaw = config.setdefault("storyclaw", {})
        storyclaw.setdefault("workflow_policy", WORKFLOW_POLICY)
        storyclaw.setdefault("model_priority", list(MODEL_PRIORITY))
        # Existing deployments retain their selected scope.  A fresh generic
        # install remains UNCONFIGURED until guided onboarding creates a
        # private project; it must never silently inherit a historical line.
        storyclaw.setdefault("series_scope_id", initial_scope)
        storyclaw.setdefault("policy_profile", POLICY_PROFILE)
        config.setdefault("authorization", {}).setdefault(
            "confirmation_receipts_root", str(p["authority_receipts"].resolve())
        )
        # Paths describe this deployment, so refresh them when a persistent
        # volume is restored at a new location.  Provider and budget settings
        # remain untouched.
        storyclaw["storage"] = storage_contract
        _write(p["config"], config)
    receipt = {
        "schema": "storyclaw.nalu.deployment.v1",
        "created_at": now(),
        "engine_root": str(engine),
        "runtime_root": str(runtime),
        "venv_python": str(roots()[2]),
        "engine_commit": _engine_commit(engine, runtime),
        "private_runtime": True,
        "paid_requests_enabled": bool((_json(p["config"], {}) or {}).get("generation", {}).get("paid_requests_enabled", False)),
        "model_allowlist": sorted(ALLOWED_MODELS),
        "workflow_policy": WORKFLOW_POLICY,
        "storage": storage_contract,
        "secret_values_included": False,
    }
    _write(p["deployment_receipt"], receipt)
    return receipt


def configure_series_scope(runtime: Path, scope_id: str) -> dict[str, Any]:
    """Select a declared private series scope, including when episode numbers repeat."""
    scope_id = str(scope_id or "").strip()
    if not scope_id or not _SAFE_SCOPE_ID.fullmatch(scope_id):
        raise SystemExit("BLOCKED: --scope-id is required")
    p = deployment_paths(Path("."), runtime)
    scopes = _json(p["series_scopes"], {}) or {}
    default_scope = str(scopes.get("default_scope") or "NALU-YEWUJIANG")
    if scope_id != default_scope and scope_id not in (scopes.get("scopes") or {}):
        raise SystemExit(f"BLOCKED: series scope {scope_id!r} is not declared in {p['series_scopes']}")
    config = _json(p["config"], {}) or {}
    config.setdefault("storyclaw", {})["series_scope_id"] = scope_id
    _write(p["config"], config)
    return {
        "schema": "storyclaw.nalu.series_scope_selection.v1",
        "status": "PASS",
        "scope_id": scope_id,
        "series_scopes": str(p["series_scopes"]),
        "config": str(p["config"]),
    }


def _series_scope_check(runtime: Path, config: dict[str, Any]) -> dict[str, Any]:
    p = deployment_paths(Path("."), runtime)
    scope_id = str((config.get("storyclaw") or {}).get("series_scope_id") or "NALU-YEWUJIANG")
    scopes = _json(p["series_scopes"], {}) or {}
    default_scope = str(scopes.get("default_scope") or "NALU-YEWUJIANG")
    declared = scopes.get("scopes") or {}
    exists = scope_id == default_scope or scope_id in declared
    return {
        "status": "PASS" if exists else "BLOCKED",
        "scope_id": scope_id,
        "config_path": str(p["series_scopes"]),
        "declared": exists,
    }


def _selected_series_scope(runtime: Path, config: dict[str, Any] | None = None) -> tuple[str, str]:
    """Return ``(selected, default)`` from private deployment state."""
    if config is None:
        config = _json(runtime / "qingshan.json", {}) or {}
    scopes = _json(runtime / "runtime" / "series_scopes.json", {}) or {}
    default_scope = str(scopes.get("default_scope") or "NALU-YEWUJIANG")
    selected = str((config.get("storyclaw") or {}).get("series_scope_id") or default_scope)
    if not _SAFE_SCOPE_ID.fullmatch(selected):
        raise SystemExit(f"BLOCKED: invalid selected series scope id {selected!r}")
    return selected, default_scope


def _scope_document_path(
    runtime: Path,
    config: dict[str, Any],
    key: str,
    *,
    historical_fallback: Path | None = None,
) -> Path | None:
    """Resolve a selected scope document without reading another series.

    Portable projects declare every registry under ``runtime/series/<scope>``.
    The fallback exists only for the historical default deployment whose scope
    file predates per-series registries.
    """
    selected, _default = _selected_series_scope(runtime, config)
    scopes = _json(runtime / "runtime" / "series_scopes.json", {}) or {}
    declared = (scopes.get("scopes") or {}).get(selected)
    value = declared.get(key) if isinstance(declared, dict) else None
    if not value:
        return historical_fallback if selected == "NALU-YEWUJIANG" else None
    text = str(value).strip()
    if not text or text.startswith("tools:"):
        return None
    candidate = Path(text).expanduser()
    path = candidate if candidate.is_absolute() else runtime / candidate
    try:
        resolved = path.resolve()
        resolved.relative_to(runtime.resolve())
    except (OSError, ValueError):
        return None
    return resolved


def _document_scope(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    direct = value.get("series_scope_id")
    if isinstance(direct, str) and direct:
        return direct
    nested = value.get("series_scope")
    if isinstance(nested, dict):
        scope_id = nested.get("scope_id")
        if isinstance(scope_id, str) and scope_id:
            return scope_id
    return None


def _engine_readonly_probe(engine: Path) -> dict[str, Any]:
    """Prove that both the checkout root and representative code are read-only.

    ``os.access`` is insufficient for ACLs, containers and root-owned
    processes.  An actual create attempt is used for the root, then existing
    tracked code files are opened write-only without writing any bytes.  A
    successful open is enough to reject the deployment.  Nested private mounts
    are tested separately.
    """
    probe: Path | None = None
    try:
        fd, probe_name = tempfile.mkstemp(
            dir=engine, prefix=".storyclaw_engine_write_probe_"
        )
        probe = Path(probe_name)
        os.close(fd)
    except OSError as exc:
        if exc.errno not in {errno.EACCES, errno.EROFS, errno.EPERM}:
            return {
                "status": "BLOCKED",
                "path": str(engine),
                "reason": f"engine_readonly_probe_failed:{exc}",
            }
        checked: list[str] = []
        for candidate in (
            engine / "tools" / "storyclaw_nalu_runtime.py",
            engine / "lines" / "nalu" / "runtime" / "tools" / "nalu_pipeline.py",
        ):
            if not candidate.is_file():
                continue
            try:
                fd = os.open(candidate, os.O_WRONLY | getattr(os, "O_CLOEXEC", 0))
            except OSError as code_exc:
                if code_exc.errno in {errno.EACCES, errno.EROFS, errno.EPERM}:
                    checked.append(str(candidate))
                    continue
                return {
                    "status": "BLOCKED",
                    "path": str(engine),
                    "reason": f"engine_code_readonly_probe_failed:{candidate}:{code_exc}",
                }
            else:
                os.close(fd)
                return {
                    "status": "BLOCKED",
                    "path": str(engine),
                    "reason": f"engine_code_file_is_writable:{candidate}",
                }
        return {
            "status": "PASS",
            "path": str(engine),
            "mode": "READ_ONLY",
            "code_files_checked": checked,
        }
    try:
        probe.unlink()
    except OSError as exc:
        return {
            "status": "BLOCKED",
            "path": str(engine),
            "reason": f"engine_write_probe_created_but_cleanup_failed:{exc}",
        }
    return {
        "status": "BLOCKED",
        "path": str(engine),
        "reason": "engine_checkout_is_writable",
    }


def _writable_flock_probe(path: Path, label: str) -> dict[str, Any]:
    """Perform real write, fsync and POSIX flock operations in ``path``."""
    if not path.is_dir():
        return {
            "status": "BLOCKED",
            "path": str(path),
            "reason": "mount_target_missing_or_not_directory",
        }
    probe: Path | None = None
    operation_error: OSError | None = None
    cleanup_error: OSError | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w+b", dir=path, prefix=f".storyclaw_{label}_probe_", delete=False
        ) as f:
            probe = Path(f.name)
            f.write(b"storyclaw-storage-probe\n")
            f.flush()
            os.fsync(f.fileno())
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        operation_error = exc
    finally:
        if probe is not None:
            try:
                probe.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_error = exc
    if operation_error is not None or cleanup_error is not None:
        return {
            "status": "BLOCKED",
            "path": str(path),
            "writable": probe is not None,
            "flock": operation_error is None,
            "reason": str(operation_error or cleanup_error),
        }
    return {
        "status": "PASS",
        "path": str(path),
        "writable": True,
        "flock": True,
    }


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _private_mount_probe(
    target: Path, backing: Path, runtime: Path, label: str
) -> dict[str, Any]:
    result = {
        "status": "BLOCKED",
        "mount_target": str(target),
        "backing_path": str(backing),
        "private_runtime_backing": _is_within(backing, runtime),
        "same_storage_object": False,
    }
    if not result["private_runtime_backing"]:
        result["reason"] = "backing_path_outside_private_runtime"
        return result
    if not target.is_dir() or not backing.is_dir():
        result["reason"] = "mount_target_or_backing_missing"
        return result
    try:
        result["same_storage_object"] = os.path.samefile(target, backing)
    except OSError as exc:
        result["reason"] = f"mount_identity_probe_failed:{exc}"
        return result
    if not result["same_storage_object"]:
        result["reason"] = "private_bind_mount_not_active"
        return result
    io_probe = _writable_flock_probe(target, label)
    result["writable"] = io_probe.get("writable", False)
    result["flock"] = io_probe.get("flock", False)
    if io_probe["status"] != "PASS":
        result["reason"] = io_probe.get("reason", "write_or_flock_probe_failed")
        return result
    result["status"] = "PASS"
    return result


def _storage_checks(engine: Path, runtime: Path, config: dict[str, Any]) -> dict[str, Any]:
    p = deployment_paths(engine, runtime)
    expected = {
        "mode": "READ_ONLY_ENGINE_WITH_PRIVATE_WRITABLE_MOUNTS",
        "engine_root": str(engine.resolve()),
        "workspace_mount_target": str(p["workspace"].absolute()),
        "workspace_backing_path": str(p["workspace_backing"].resolve()),
        "transactions_mount_target": str(p["transactions"].absolute()),
        "transactions_backing_path": str(p["transactions_backing"].resolve()),
        "writer_layers_root": str(p["writer_layers"].resolve()),
    }
    configured = (config.get("storyclaw") or {}).get("storage")
    contract_ok = isinstance(configured, dict) and all(
        configured.get(key) == value for key, value in expected.items()
    )
    distinct = True
    try:
        distinct = not os.path.samefile(p["workspace_backing"], p["transactions_backing"])
    except OSError:
        distinct = False
    return {
        "storage_contract": {
            "status": "PASS" if contract_ok and distinct else "BLOCKED",
            "configured": configured,
            "expected": expected,
            "distinct_private_stores": distinct,
        },
        "engine_code_read_only": _engine_readonly_probe(engine),
        "workspace_store": _private_mount_probe(
            p["workspace"], p["workspace_backing"], runtime, "workspace"
        ),
        "transaction_store": _private_mount_probe(
            p["transactions"], p["transactions_backing"], runtime, "transactions"
        ),
        "writer_layers_store": _writable_flock_probe(
            p["writer_layers"], "writer_layers"
        ),
    }


def _portable_dependency_checks(engine: Path) -> dict[str, Any]:
    media_path = engine / "lines/nalu/runtime/tools/nalu_media_tools.py"
    audio_path = engine / "tools/storyclaw_audio_provider.py"
    renderer_path = engine / "tools/render_portable_timeline.py"
    media_result: dict[str, Any] = {
        "status": "BLOCKED", "path": str(media_path), "failures": []
    }
    if not media_path.is_file():
        media_result["failures"].append("NALU_MEDIA_TOOLS_MISSING")
    else:
        try:
            spec = importlib.util.spec_from_file_location(
                "_storyclaw_preflight_media_tools", media_path
            )
            if spec is None or spec.loader is None:
                raise RuntimeError("module loader unavailable")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            ffmpeg, ffmpeg_source = module.resolve_media_tool("ffmpeg")
            ffprobe, ffprobe_source = module.resolve_media_tool("ffprobe")
            font, font_source = module.resolve_cjk_font()
            media_result.update({
                "status": "PASS",
                "ffmpeg": ffmpeg, "ffmpeg_source": ffmpeg_source,
                "ffprobe": ffprobe, "ffprobe_source": ffprobe_source,
                "cjk_font": font, "cjk_font_source": font_source,
            })
        except Exception as exc:  # fail closed on missing/invalid host tools
            media_result["failures"].append(str(exc))
    return {
        "portable_media": media_result,
        "portable_audio_provider": {
            "status": "PASS" if audio_path.is_file() else "BLOCKED",
            "path": str(audio_path),
        },
        "portable_renderer": {
            "status": "PASS" if renderer_path.is_file() else "BLOCKED",
            "path": str(renderer_path),
        },
        "stable_release_signature_verifier": _release_discovery.verifier_readiness(engine),
    }


def preflight(engine: Path, runtime: Path) -> dict[str, Any]:
    p = deployment_paths(engine, runtime)
    checks: dict[str, Any] = {}
    checks["engine_root"] = {"status": "PASS" if (engine / "qingshan_engine").is_dir() else "BLOCKED", "path": str(engine)}
    pipeline = engine / "lines" / "nalu" / "runtime" / "tools" / "nalu_pipeline.py"
    paths_tool = pipeline.with_name("nalu_paths.py")
    checks["nalu_pipeline"] = {"status": "PASS" if pipeline.is_file() else "BLOCKED", "path": str(pipeline)}
    checks["nalu_paths"] = {"status": "PASS" if paths_tool.is_file() else "BLOCKED", "path": str(paths_tool)}
    checks["runtime_persistent"] = {"status": "PASS" if p["runtime"].is_dir() else "BLOCKED", "path": str(runtime)}
    config = _json(p["config"], {}) or {}
    checks.update(_storage_checks(engine, runtime, config))
    checks.update(_portable_dependency_checks(engine))
    checks["model"] = _host_model_evidence()
    policy_profile = str((config.get("storyclaw") or {}).get("policy_profile") or "")
    checks["policy_profile"] = {
        "status": "PASS" if policy_profile == POLICY_PROFILE else "BLOCKED",
        "selected": policy_profile,
        "required": POLICY_PROFILE,
    }
    checks["series_scope"] = _series_scope_check(runtime, config)
    paid = bool(config.get("generation", {}).get("paid_requests_enabled", False))
    checks["paid_lock"] = {"status": "PASS" if not paid else "REVIEW_REQUIRED", "paid_requests_enabled": paid, "api_key_present": bool(os.environ.get("GIGGLE_API_KEY"))}
    voice_registry = _scope_document_path(
        runtime, config, "voice_registry", historical_fallback=p["voice_registry"]
    )
    checks["voice_registry"] = {
        "status": "PASS" if voice_registry is not None and voice_registry.is_file() else "BLOCKED",
        "path": str(voice_registry) if voice_registry is not None else None,
        "scope_id": _selected_series_scope(runtime, config)[0],
    }
    failed = [name for name, value in checks.items() if value.get("status") == "BLOCKED"]
    marker = _json(runtime / ".qingshan-private-runtime.json", {}) or {}
    return {
        "schema": "storyclaw.nalu.preflight.v1",
        "status": "PASS" if not failed else "BLOCKED",
        "engine_commit": _engine_commit(engine, runtime),
        "engine_root": str(engine.resolve()),
        "private_runtime_root": str(runtime.resolve()),
        "project_id": str(marker.get("project_id") or ""),
        "series_scope_id": str(
            marker.get("series_scope_id")
            or (config.get("storyclaw") or {}).get("series_scope_id")
            or ""
        ),
        "checks": checks,
        "failures": failed,
    }


def _paid_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("generation", {}).get("paid_requests_enabled", False)) and bool(config.get("storyclaw", {}).get("paid_requests_enabled", False))


def _host_model_evidence() -> dict[str, Any]:
    """Return the model reported by the StoryClaw host invocation.

    A desired model stored in qingshan.json is only policy, not evidence of the
    model that actually executed the chat turn.  Receipts therefore trust only
    the host-provided ``STORYCLAW_MODEL`` value and fail closed when it is
    absent or outside the high-capability allowlist.
    """
    selected = str(os.environ.get("STORYCLAW_MODEL") or "").strip()
    if not selected:
        return {
            "status": "BLOCKED",
            "selected": None,
            "source": "STORYCLAW_MODEL",
            "reason": "host_model_evidence_missing",
            "allowlist": sorted(ALLOWED_MODELS),
        }
    return {
        "status": "PASS" if selected in ALLOWED_MODELS else "BLOCKED",
        "selected": selected,
        "source": "STORYCLAW_MODEL",
        "allowlist": sorted(ALLOWED_MODELS),
        "reason": None if selected in ALLOWED_MODELS else "host_model_not_allowed",
    }


def _writer_layers_dir(runtime: Path, scope_id: str, episode: str,
                       config: dict[str, Any] | None = None) -> Path:
    """Private four-layer handoff path for a read-only engine deployment."""
    configured = str(
        ((((config or {}).get("storyclaw") or {}).get("storage") or {}).get(
            "writer_layers_root"
        )) or ""
    ).strip()
    root = Path(configured).expanduser() if configured else runtime / "writer_layers"
    if not root.is_absolute():
        raise SystemExit("BLOCKED: storyclaw.storage.writer_layers_root must be absolute")
    root = root.resolve()
    try:
        root.relative_to(runtime.resolve())
    except ValueError as exc:
        raise SystemExit(
            "BLOCKED: writer layers must live inside the private project runtime"
        ) from exc
    return root / scope_id / episode


def _asset_plan_path(runtime: Path, episode: str, scope_id: str | None = None) -> Path:
    selected = scope_id or _selected_series_scope(runtime)[0]
    if not _SAFE_SCOPE_ID.fullmatch(selected):
        raise SystemExit(f"BLOCKED: invalid selected series scope id {selected!r}")
    return (
        runtime / "runtime" / "asset_plans" / selected
        / f"{episode}_ASSET_MATCH_PLAN.json"
    )


def _asset_confirmation_path(
    runtime: Path, episode: str, scope_id: str | None = None
) -> Path:
    selected = scope_id or _selected_series_scope(runtime)[0]
    if not _SAFE_SCOPE_ID.fullmatch(selected):
        raise SystemExit(f"BLOCKED: invalid selected series scope id {selected!r}")
    return (
        runtime / "runtime" / "asset_plans" / selected
        / f"{episode}_ASSET_MATCH_CONFIRMATION.json"
    )


def _stage_status(state: Any, stage: str) -> str | None:
    """Read an explicit stage verdict without inferring PASS from progress text."""
    if not isinstance(state, dict):
        return None
    for container_key in ("stages", "stage_results", "stage_verdicts", "gates"):
        container = state.get(container_key)
        if isinstance(container, dict):
            value = container.get(stage) or container.get(stage.lower())
            if isinstance(value, dict):
                value = value.get("status") or value.get("overall_status") or value.get("verdict")
            if isinstance(value, str):
                return value.upper()
    value = state.get(stage) or state.get(stage.lower())
    if isinstance(value, dict):
        value = value.get("status") or value.get("overall_status") or value.get("verdict")
    return value.upper() if isinstance(value, str) else None


def _s1_passed(runtime: Path, episode: str, scope_id: str | None = None) -> bool:
    state = _json(runtime / "runtime" / "pipeline_state" / f"{episode}.json")
    selected_scope, default_scope = _selected_series_scope(runtime)
    scope_id = scope_id or selected_scope
    state_scope = _document_scope(state)
    # Legacy default-series state predates explicit scope receipts.  Reused
    # episode numbers for every non-default series must always carry an exact
    # binding so an old E01 can never authorize a new E01.
    if scope_id != default_scope and state_scope != scope_id:
        return False
    if state_scope is not None and state_scope != scope_id:
        return False
    status = _stage_status(state, "S1")
    return status in {
        "PASS", "PASSED", "ALL_PASS", "ALL 6 GATES PASS", "COMPLETE", "COMPLETED",
        "SKIPPED_ALREADY_PASS",
    }


def _asset_gate_context(runtime: Path, episode: str) -> dict[str, Any]:
    """Resolve exact private script, gate and authority evidence for one plan."""
    config = _json(runtime / "qingshan.json", {}) or {}
    selected_scope, _default_scope = _selected_series_scope(runtime, config)
    state_path = runtime / "runtime" / "pipeline_state" / f"{episode}.json"
    state = _json(state_path)
    if not isinstance(state, dict):
        raise _asset_gate.AssetPlanRefused("S1_EVIDENCE_JSON_INVALID")
    layers = state.get("layers")
    raw_paths = layers.get("paths") if isinstance(layers, dict) else None
    if not isinstance(raw_paths, dict):
        raise _asset_gate.AssetPlanRefused("FOUR_LAYER_PATHS_MISSING_FROM_STATE")
    layer_paths = {
        name: Path(str(raw_paths.get(name) or "")).expanduser()
        for name in _asset_gate.LAYER_NAMES
    }
    s1_row = (state.get("stages") or {}).get("S1")
    details = s1_row.get("details") if isinstance(s1_row, dict) else None
    selfcheck = (
        details.get("writer_selfcheck_seq29") if isinstance(details, dict) else None
    )
    report_text = selfcheck.get("report") if isinstance(selfcheck, dict) else None
    seq29_report = Path(str(report_text or "")).expanduser()
    receipt_row = details.get("s1_gate_receipt") if isinstance(details, dict) else None
    s1_receipt_text = (
        receipt_row.get("path") if isinstance(receipt_row, dict) else None
    )
    s1_evidence_path = Path(str(s1_receipt_text or "")).expanduser()
    s2_evidence_path = (
        runtime / "runtime" / "pipeline_logs" / episode
        / "S2_PREPRODUCTION_RECEIPT.json"
    ).resolve()
    storyclaw = config.get("storyclaw") or {}
    configured_models = storyclaw.get("asset_generation_model_allowlist")
    allowed_models = (
        {str(value).strip() for value in configured_models if str(value).strip()}
        if isinstance(configured_models, list)
        else set(_asset_gate.DEFAULT_ALLOWED_GENERATION_MODELS)
    )
    authorization = config.get("authorization") or {}
    receipt_root_text = str(authorization.get("confirmation_receipts_root") or "").strip()
    receipt_root = Path(receipt_root_text).expanduser() if receipt_root_text else Path()
    return {
        "config": config,
        "series_scope_id": selected_scope,
        "plan_path": _asset_plan_path(runtime, episode, selected_scope),
        "confirmation_path": _asset_confirmation_path(
            runtime, episode, selected_scope
        ),
        "receipt_root": receipt_root,
        "line_owner_id": str(authorization.get("line_owner_id") or "").strip(),
        "plan_kwargs": {
            "episode": episode,
            "series_scope_id": selected_scope,
            "generation_contract_path": layer_paths["generation_contract"],
            "layer_paths": layer_paths,
            "s1_gate_evidence_path": s1_evidence_path,
            "s2_gate_evidence_path": s2_evidence_path,
            "seq29_report_path": seq29_report,
            "private_roots": [runtime.resolve()],
            "allowed_models": allowed_models,
        },
    }


def _asset_gate_reason(report: dict[str, Any], fallback: str) -> str:
    failures = report.get("failures") if isinstance(report, dict) else None
    return str(failures[0]) if isinstance(failures, list) and failures else fallback


def validate_asset_plan(runtime: Path, episode: str) -> tuple[bool, str]:
    """Revalidate the current proposal and its external confirmation for S3+."""
    try:
        context = _asset_gate_context(runtime, episode)
    except (_asset_gate.AssetPlanRefused, SystemExit) as exc:
        return False, str(exc)
    plan_report = _asset_gate.validate_asset_plan(
        context["plan_path"], **context["plan_kwargs"]
    )
    if plan_report["status"] != "PASS":
        return False, _asset_gate_reason(plan_report, "asset_matching_plan_invalid")
    confirmation = _json(context["confirmation_path"])
    if not isinstance(confirmation, dict) or confirmation.get("status") != "CONFIRMED":
        return False, "user_confirmation_missing"
    if confirmation.get("asset_plan_sha256") != plan_report["asset_plan_sha256"]:
        return False, "asset_plan_sha256_mismatch"
    receipt_path_text = str(confirmation.get("receipt_path") or "").strip()
    receipt_sha = str(confirmation.get("receipt_sha256") or "").strip()
    if not receipt_path_text or not receipt_sha:
        return False, "user_confirmation_receipt_missing"
    confirmation_report = _asset_gate.validate_confirmation_receipt(
        Path(receipt_path_text),
        receipt_root=context["receipt_root"],
        expected_receipt_sha256=receipt_sha,
        expected_line_owner_id=context["line_owner_id"],
        plan_path=context["plan_path"],
        **context["plan_kwargs"],
    )
    if confirmation_report["status"] != "PASS":
        return False, _asset_gate_reason(
            confirmation_report, "user_confirmation_receipt_invalid"
        )
    return True, "PASS"


def record_asset_plan(runtime: Path, episode: str, source: Path) -> Path:
    """Store a script-derived proposal; this operation cannot confirm or pay."""
    try:
        context = _asset_gate_context(runtime, episode)
        evidence = _asset_gate.build_script_evidence(
            **{
                key: value
                for key, value in context["plan_kwargs"].items()
                if key != "allowed_models"
            }
        )
    except _asset_gate.AssetPlanRefused as exc:
        raise SystemExit(
            f"BLOCKED: cannot create an asset matching plan before exact S1 evidence passes ({exc})"
        ) from exc
    plan = _json(source)
    if not isinstance(plan, dict):
        raise SystemExit("BLOCKED: asset plan must be a JSON object")
    plan["schema"] = _asset_gate.PLAN_SCHEMA
    plan["episode"] = episode
    plan["series_scope_id"] = context["series_scope_id"]
    plan["status"] = "PROPOSED"
    plan["script_evidence"] = evidence
    plan["script_evidence_sha256"] = evidence["script_evidence_sha256"]
    plan.pop("script_s1_gate_status", None)
    plan.pop("user_confirmation", None)
    destination = context["plan_path"]
    destination.parent.mkdir(parents=True, exist_ok=True)
    candidate = destination.parent / f".{destination.name}.{uuid.uuid4().hex}.candidate"
    _write(candidate, plan)
    try:
        _asset_gate.require_valid_asset_plan(
            candidate, **context["plan_kwargs"]
        )
    except _asset_gate.AssetPlanRefused as exc:
        candidate.unlink(missing_ok=True)
        raise SystemExit(f"BLOCKED: incomplete or invalid asset plan ({exc})") from exc
    os.replace(candidate, destination)
    # A changed proposal always invalidates the previous confirmation.  A new
    # user-authored receipt must bind the exact bytes written above.
    context["confirmation_path"].unlink(missing_ok=True)
    return destination


def confirm_asset_plan(
    runtime: Path,
    episode: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
) -> Path:
    """Bind a separately produced user confirmation receipt to an immutable proposal."""
    context = _asset_gate_context(runtime, episode)
    try:
        report = _asset_gate.require_valid_confirmation(
            receipt_path,
            receipt_root=context["receipt_root"],
            expected_receipt_sha256=expected_receipt_sha256,
            expected_line_owner_id=context["line_owner_id"],
            plan_path=context["plan_path"],
            **context["plan_kwargs"],
        )
    except _asset_gate.AssetPlanRefused as exc:
        raise SystemExit(f"BLOCKED: asset confirmation invalid ({exc})") from exc
    receipt = _json(receipt_path) or {}
    confirmation = {
        "schema": "storyclaw.asset_plan_confirmation.v2",
        "status": "CONFIRMED",
        "episode": episode,
        "series_scope_id": context["series_scope_id"],
        "confirmed_at_utc": receipt.get("confirmed_at_utc"),
        "line_owner_id": context["line_owner_id"],
        "asset_plan_path": str(context["plan_path"].resolve()),
        "asset_plan_sha256": report["asset_plan_sha256"],
        "script_evidence_sha256": report["script_evidence_sha256"],
        "receipt_sha256": report["receipt_sha256"],
        "receipt_path": str(receipt_path.resolve()),
    }
    _write(context["confirmation_path"], confirmation)
    return context["confirmation_path"]


def _enforce_workflow_policy(runtime: Path, episode: str, target_stage: str) -> None:
    """Fail closed at S3+ until script and one complete asset proposal are confirmed."""
    if int(target_stage[1:]) < 3:
        return
    selected_scope, _default_scope = _selected_series_scope(runtime)
    if not _s1_passed(runtime, episode, selected_scope):
        raise SystemExit("BLOCKED: S3+ requires an explicit S1 PASS before asset matching or generation")
    valid, reason = validate_asset_plan(runtime, episode)
    if not valid:
        raise SystemExit(f"BLOCKED: S3+ requires a confirmed script-derived asset matching plan ({reason})")


def run_episode(engine: Path, runtime: Path, episode: str, from_stage: str | None, until: str | None, paid: bool, dry_run: bool) -> int:
    with _production_barrier(runtime):
        _assert_selected_engine_unchanged(engine)
        return _run_episode_locked(
            engine, runtime, episode, from_stage, until, paid, dry_run
        )


def _run_episode_locked(engine: Path, runtime: Path, episode: str, from_stage: str | None, until: str | None, paid: bool, dry_run: bool) -> int:
    python_selection = _resolve_production_python(engine, runtime)
    selected_python = python_selection["resolved_python"]
    if not episode.startswith("E") or not episode[1:].isdigit():
        raise SystemExit("--episode must look like E01")
    if from_stage and from_stage.upper() not in STAGES:
        raise SystemExit("--from must be S1..S8")
    if until and until.upper() not in STAGES:
        raise SystemExit("--until must be S1..S8")
    target_stage = (until or from_stage or "S1").upper()
    p = deployment_paths(engine, runtime)
    config = _json(p["config"], {}) or {}
    model_evidence = _host_model_evidence()
    if model_evidence["status"] != "PASS":
        raise SystemExit(
            "BLOCKED: StoryClaw host model evidence is missing or outside the "
            f"approved high-capability allowlist ({model_evidence.get('reason')})"
        )
    selected_model = str(model_evidence["selected"])
    if paid and not _paid_enabled(config):
        raise SystemExit("BLOCKED: paid requires both config generation.paid_requests_enabled and storyclaw.paid_requests_enabled")
    if paid and not dry_run and not os.environ.get("GIGGLE_API_KEY"):
        raise SystemExit("BLOCKED: GIGGLE_API_KEY is absent; no provider POST allowed")
    scope_check = _series_scope_check(runtime, config)
    if scope_check["status"] != "PASS":
        raise SystemExit(
            f"BLOCKED: selected series scope {scope_check['scope_id']!r} is not declared"
        )
    storage_checks = _storage_checks(engine, runtime, config)
    storage_failures = [
        name for name, result in storage_checks.items()
        if result.get("status") == "BLOCKED"
    ]
    if storage_failures:
        raise SystemExit(
            "BLOCKED: StoryClaw production storage contract failed: "
            + ", ".join(storage_failures)
        )
    dependency_checks = _portable_dependency_checks(engine)
    dependency_failures = [
        name for name, result in dependency_checks.items()
        if result.get("status") == "BLOCKED"
    ]
    if dependency_failures:
        raise SystemExit(
            "BLOCKED: StoryClaw portable dependencies failed: "
            + ", ".join(dependency_failures)
        )
    _enforce_workflow_policy(runtime, episode, target_stage)
    series_scope_id = str((config.get("storyclaw") or {}).get("series_scope_id") or "NALU-YEWUJIANG")
    layers_dir = _writer_layers_dir(runtime, series_scope_id, episode, config)
    layers_dir.mkdir(parents=True, exist_ok=True)
    try:
        active_layers = _writer_workflow.resolve_active_layers(
            runtime, series_scope_id, episode
        )
    except _writer_workflow.WriterWorkflowBlocked as exc:
        raise SystemExit(f"BLOCKED: active private writer handoff is invalid ({exc})") from exc
    if active_layers:
        handoff = _writer_workflow.verify_writer_handoff(
            runtime, episode, expected_layers=active_layers
        )
        if handoff.get("status") != "PASS":
            failures = ",".join((handoff.get("failures") or [])[:8])
            raise SystemExit(
                "BLOCKED: private writer handoff failed provenance/seal verification"
                f" ({failures or 'VERIFY_FAILED'})"
            )
    elif from_stage and int(from_stage[1:]) > 1:
        raise SystemExit(
            "BLOCKED: S2+ cannot bypass the sealed private writer handoff and S1"
        )
    argv = [
        selected_python,
        str(engine / "lines/nalu/runtime/tools/nalu_pipeline.py"),
        "run", "--episode", episode,
        "--layers-dir", str(layers_dir),
    ]
    # A first version uses the conventional v1 names.  Revisions remain
    # immutable v2/v3/... files; the private active-handoff selects them by
    # exact path instead of overwriting a v1 slot.
    if active_layers:
        argv += [
            "--narrative", str(active_layers["narrative_canonical"]),
            "--directing", str(active_layers["directing_script"]),
            "--contract", str(active_layers["generation_contract"]),
            "--manifest", str(active_layers["writer_manifest"]),
        ]
    if dry_run:
        argv.append("--dry-run")
    if paid:
        argv.append("--paid")
    if from_stage:
        argv += ["--from", from_stage.upper()]
    if until:
        argv += ["--until", until.upper()]
    env = os.environ.copy()
    voice_registry = _scope_document_path(
        runtime, config, "voice_registry", historical_fallback=p["voice_registry"]
    )
    if voice_registry is None or not voice_registry.is_file():
        raise SystemExit(
            f"BLOCKED: selected series {series_scope_id!r} has no private voice registry"
        )
    env.update({"NALU_ENGINE_ROOT": str(engine), "NALU_RUNTIME_ROOT": str(runtime), "NALU_VENV_PYTHON": selected_python, "QINGSHAN_VOICE_REGISTRY": str(voice_registry)})
    env["NALU_SERIES_SCOPE_ID"] = series_scope_id
    if active_layers and active_layers.get("project_lexicon"):
        env["NALU_PROJECT_LEXICON"] = str(active_layers["project_lexicon"])
    policy_profile = str((config.get("storyclaw") or {}).get("policy_profile") or "")
    if policy_profile != POLICY_PROFILE:
        raise SystemExit(
            f"BLOCKED: StoryClaw requires policy_profile={POLICY_PROFILE}; got {policy_profile!r}"
        )
    env["NALU_POLICY_PROFILE"] = policy_profile
    provider_posts_allowed = bool(paid and not dry_run)
    if not provider_posts_allowed:
        env.pop("GIGGLE_API_KEY", None)
        env.pop("NALU_PAID_CONFIG_LOCK", None)
    else:
        # The portable audio provider requires evidence that both StoryClaw
        # config locks were enabled by this adapter, in addition to the
        # source-receipted line-owner order supplied by nalu_pipeline.
        env["NALU_PAID_CONFIG_LOCK"] = "1"
    lock_dir = p["run_locks"] / series_scope_id
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / f"{episode}.lock"
    project_marker = _json(runtime / ".qingshan-private-runtime.json", {}) or {}
    receipt = {
        "schema": "storyclaw.nalu.run.v1",
        "started_at": now(),
        "release_commit": _engine_commit(engine, runtime),
        "project_id": str(
            project_marker.get("project_id")
            or (config.get("project") or {}).get("id")
            or ""
        ),
        "episode": episode,
        "from_stage": from_stage.upper() if from_stage else None,
        "until_stage": until.upper() if until else None,
        "target_stage": target_stage,
        "argv": [shlex.quote(x) for x in argv],
        "paid_requested": paid,
        "paid_posts": None if provider_posts_allowed else 0,
        "provider_posts_allowed": provider_posts_allowed,
        "dry_run": dry_run,
        "paid_lock_evidence": {
            "command_paid": paid,
            "dry_run": dry_run,
            "generation_paid_requests_enabled": bool(
                (config.get("generation") or {}).get("paid_requests_enabled")
            ),
            "storyclaw_paid_requests_enabled": bool(
                (config.get("storyclaw") or {}).get("paid_requests_enabled")
            ),
            "both_config_locks_enabled": _paid_enabled(config),
            # Record the exact child environment used for the pipeline.  Dry
            # and unpaid runs remove the key even if the host process happens
            # to have one injected.
            "provider_key_present": bool(env.get("GIGGLE_API_KEY")),
        },
        "model": selected_model,
        "model_evidence": model_evidence,
        "series_scope_id": series_scope_id,
        "policy_profile": policy_profile,
        "writer_layers_dir": str(layers_dir),
        "venv_python": python_selection,
        "singleflight_lock": str(lock_path),
    }
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    receipt_path = p["run_receipts"] / (
        f"{series_scope_id}_{episode}_{stamp}_{uuid.uuid4().hex[:12]}.json"
    )
    p["run_receipts"].mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SystemExit(
                f"BLOCKED: another producer or heartbeat owns {series_scope_id}/{episode}"
            ) from exc
        receipt["singleflight_acquired"] = True
        _write(receipt_path, receipt)
        try:
            result = subprocess.run(argv, cwd=engine, env=env, check=False)
            receipt["exit_code"] = result.returncode
            return_code = result.returncode
        except BaseException as exc:
            receipt["exit_code"] = None
            receipt["exception"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            receipt["finished_at"] = now()
            state_path = p["runtime_state"] / f"{episode}.json"
            state = _json(state_path, {}) or {}
            receipt["pipeline_state_after_run"] = {
                "path": str(state_path),
                "sha256": sha256(state_path) if state_path.is_file() else None,
                "schema": state.get("schema"),
                "overall_status": state.get("overall_status"),
                "current_stage": state.get("current_stage"),
                "stage_statuses": {
                    sid: ((state.get("stages") or {}).get(sid) or {}).get("status")
                    for sid in sorted(STAGES)
                },
            }
            _write(receipt_path, receipt)
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    return return_code


def heartbeat(runtime: Path, episode: str, *, engine: Path | None = None,
              resume: bool = False, paid: bool = False) -> dict[str, Any]:
    with _production_barrier(runtime):
        if engine is not None:
            _assert_selected_engine_unchanged(engine)
        return _heartbeat_locked(
            runtime, episode, engine=engine, resume=resume, paid=paid
        )


def _heartbeat_locked(runtime: Path, episode: str, *, engine: Path | None = None,
                      resume: bool = False, paid: bool = False) -> dict[str, Any]:
    """Inspect or safely resume an interrupted stage.

    Review, gate, approval and explicit waiting states are never auto-resumed.
    ``--resume`` is intended for a 15-minute StoryClaw heartbeat and delegates
    through :func:`run_episode`, so the same single-flight lock, model evidence,
    paid locks and transaction stores still apply.
    """
    path = runtime / "runtime" / "pipeline_state" / f"{episode}.json"
    state = _json(path)
    if not isinstance(state, dict):
        return {"schema": "storyclaw.nalu.heartbeat.v1", "episode": episode, "status": "BLOCKED", "reason": "pipeline_state_missing", "path": str(path)}
    status = str(state.get("overall_status") or "UNKNOWN").upper()
    current_stage = str(state.get("current_stage") or "").upper()
    stop_markers = (
        "REVIEW_REQUIRED", "BLOCKED", "AWAITING", "HARD_STOP",
        "PASS", "COMPLETE", "APPROVAL", "ROUTE_MISSING",
    )
    should_resume = (
        resume
        and current_stage in STAGES
        and not any(marker in status for marker in stop_markers)
    )
    result: dict[str, Any] = {
        "schema": "storyclaw.nalu.heartbeat.v1",
        "episode": episode,
        "status": status,
        "current_stage": current_stage or None,
        "updated_at": state.get("updated_at"),
        "action": "RESUME" if should_resume else "IDLE",
        "reason": (
            "interrupted_nonterminal_stage" if should_resume else
            "review_gate_wait_or_terminal_state"
        ),
    }
    if engine is not None:
        result["venv_python"] = _resolve_production_python(engine, runtime)
    if should_resume:
        if engine is None:
            raise SystemExit("BLOCKED: heartbeat --resume requires NALU_ENGINE_ROOT")
        result["resume_exit_code"] = _run_episode_locked(
            engine, runtime, episode, current_stage, current_stage, paid, False
        )
        result["resumed_at"] = now()
    return result


def _committed_blobs(engine: Path) -> list[tuple[str, str, str]]:
    """List ``(path, object_id, mode)`` for regular files in ``HEAD``.

    Reading blobs by object id prevents modified and untracked working-tree
    files from leaking into a public package.
    """
    try:
        raw = subprocess.check_output(
            ["git", "-C", str(engine), "ls-tree", "-rz", "--full-tree", "HEAD"],
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"BLOCKED: public bundle requires a committed Git HEAD ({exc})") from exc
    blobs: list[tuple[str, str, str]] = []
    for record in raw.split(b"\0"):
        if not record:
            continue
        metadata, raw_name = record.split(b"\t", 1)
        mode, object_type, object_id = metadata.decode("ascii").split()
        if object_type != "blob" or mode == "120000":
            continue
        name = raw_name.decode("utf-8", errors="surrogateescape")
        blobs.append((name, object_id, mode))
    return blobs


def public_bundle(engine: Path, output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    commit = _engine_commit(engine)
    if not commit:
        raise SystemExit("BLOCKED: public bundle requires a committed Git HEAD")
    blobs = [
        (name, object_id, mode)
        for name, object_id, mode in _committed_blobs(engine)
        if not any(Path(name).name == excluded for excluded in PUBLIC_EXCLUDES)
        and not name.startswith(("workflow/nalu/", "workflow/tasks/", "sources/", "deliverables/"))
    ]
    blobs.sort(key=lambda item: item[0])
    names = [name for name, _object_id, _mode in blobs]
    with tempfile.TemporaryDirectory() as td:
        stage = Path(td) / "qingshan-engine"
        for name, object_id, mode in blobs:
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.check_output(
                ["git", "-C", str(engine), "cat-file", "blob", object_id]
            ))
            target.chmod(0o755 if mode.endswith("755") else 0o644)
        manifest = {
            "schema": "storyclaw.nalu.public_bundle.v1",
            "created_at": now(),
            "engine_commit": commit,
            "source": "COMMITTED_GIT_OBJECTS_ONLY",
            "working_tree_used": False,
            "file_count": len(names),
            "private_data_included": False,
            "files": names,
        }
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
    hb.add_argument("--resume", action="store_true")
    hb.add_argument("--paid", action="store_true")
    plan = sub.add_parser("asset-plan")
    plan.add_argument("--episode", required=True)
    plan.add_argument("--plan-file", type=Path, required=True)
    confirm = sub.add_parser("confirm-assets")
    confirm.add_argument("--episode", required=True)
    confirm.add_argument("--receipt-file", type=Path, required=True)
    confirm.add_argument(
        "--receipt-sha256", required=True,
        help="SHA-256 captured from the StoryClaw confirmation event before validation",
    )
    scope = sub.add_parser("configure-series")
    scope.add_argument("--scope-id", required=True)
    bundle = sub.add_parser("bundle")
    bundle.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    engine, runtime, _ = roots()
    if args.command == "init":
        print(json.dumps(init_runtime(engine, runtime), ensure_ascii=False, indent=2)); return 0
    if args.command == "preflight":
        result = preflight(engine, runtime); print(json.dumps(result, ensure_ascii=False, indent=2)); return 0 if result["status"] == "PASS" else 2
    if args.command == "heartbeat":
        print(json.dumps(heartbeat(
            runtime, args.episode, engine=engine,
            resume=args.resume, paid=args.paid,
        ), ensure_ascii=False, indent=2)); return 0
    if args.command == "asset-plan":
        path = record_asset_plan(runtime, args.episode, args.plan_file)
        print(json.dumps({"status": "PROPOSED", "episode": args.episode, "path": str(path)}, ensure_ascii=False, indent=2)); return 0
    if args.command == "confirm-assets":
        path = confirm_asset_plan(
            runtime, args.episode, args.receipt_file, args.receipt_sha256
        )
        print(json.dumps({"status": "CONFIRMED", "episode": args.episode, "path": str(path)}, ensure_ascii=False, indent=2)); return 0
    if args.command == "configure-series":
        print(json.dumps(configure_series_scope(runtime, args.scope_id), ensure_ascii=False, indent=2)); return 0
    if args.command == "bundle":
        print(json.dumps(public_bundle(engine, args.output), ensure_ascii=False, indent=2)); return 0
    return run_episode(engine, runtime, args.episode, args.from_stage, args.until, args.paid, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
