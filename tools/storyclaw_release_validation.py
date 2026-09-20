#!/usr/bin/env python3
"""Build and re-verify a private StoryClaw release-acceptance receipt.

The public TalentHub package must never contain the acceptance project.  This
tool therefore runs against the private project runtime and writes only a
private, SHA-bound receipt.  It does not execute a production stage, read a
credential, or call a provider.  A PASS is derived from the engine's real
install, intake, writer, gate, transaction, finance, QA, and checkpoint files;
callers cannot supply a free-form PASS assertion.

``build`` is intended to run on the StoryClaw host after the two-unit trial.
``verify`` reruns every check against the same private runtime.  The release
builder calls ``verify_receipt`` and publishes only the final receipt SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import giggle_credit_closure_gate as _credit_closure  # noqa: E402
from tools import storyclaw_asset_plan_gate as _asset_gate  # noqa: E402
from tools import storyclaw_guided_onboarding as _guided  # noqa: E402
from tools import storyclaw_writer_workflow as _writer  # noqa: E402
from tools import submit_giggle_character_asset_plan as _identity_submitter  # noqa: E402
from tools import submit_giggle_image_manifest as _image_submitter  # noqa: E402
from tools import submit_giggle_video_manifest_v2 as _video_submitter  # noqa: E402
from lines.nalu.runtime.tools import roger_gate_acceptance as _gate_acceptance  # noqa: E402


INPUT_SCHEMA = "storyclaw.nalu.release_validation_inputs.v1"
RECEIPT_SCHEMA = "storyclaw.nalu.release_validation.v1"
VALIDATOR_SCHEMA = "storyclaw.nalu.release_validation_verification.v1"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40,64}\Z")
EPISODE_RE = re.compile(r"E[0-9]+\Z")
TERMINAL_STAGE_STATUSES = {"PASS", "SKIPPED_ALREADY_PASS"}
ALLOWED_MODELS = {
    "storyclaw/gpt-6-astra",
    "storyclaw/claude-opus-5",
    "storyclaw/gpt-5.6-sol",
}
VALIDATION_CHECKS = (
    "install_preflight",
    "source_intake",
    "s1_s2",
    "asset_plan_confirmation",
    "s5_dry_run",
    "two_unit_paid_trial",
    "paid_authority",
    "transaction_integrity",
    "ledger_reconciliation",
    "final_qa",
    "checkpoint",
)


class ValidationBlocked(RuntimeError):
    """The live private evidence does not satisfy release acceptance."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValidationBlocked(f"{label}_JSON_INVALID:{path}:{exc}") from exc
    if not isinstance(value, dict):
        raise ValidationBlocked(f"{label}_NOT_OBJECT:{path}")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class PrivatePaths:
    """Resolve evidence only through the private runtime or its wired aliases."""

    def __init__(self, runtime: Path, config: Mapping[str, Any]) -> None:
        raw = runtime.expanduser()
        if not raw.is_absolute() or raw.is_symlink() or not raw.is_dir():
            raise ValidationBlocked(f"PRIVATE_RUNTIME_ROOT_INVALID:{raw}")
        self.runtime_input = raw.absolute()
        self.runtime = raw.resolve(strict=True)
        self.aliases: list[tuple[Path, Path]] = []
        storage = ((config.get("storyclaw") or {}).get("storage") or {})
        for target_key, backing_key in (
            ("workspace_mount_target", "workspace_backing_path"),
            ("transactions_mount_target", "transactions_backing_path"),
        ):
            target_text = str(storage.get(target_key) or "").strip()
            backing_text = str(storage.get(backing_key) or "").strip()
            if not target_text or not backing_text:
                continue
            target = Path(target_text).expanduser()
            backing = Path(backing_text).expanduser()
            if not target.is_absolute() or not backing.is_absolute():
                raise ValidationBlocked(f"PRIVATE_STORAGE_ALIAS_NOT_ABSOLUTE:{target_key}")
            backing_resolved = backing.resolve(strict=True)
            if not _inside(backing_resolved, self.runtime):
                raise ValidationBlocked(f"PRIVATE_STORAGE_BACKING_ESCAPES_RUNTIME:{backing}")
            self.aliases.append((target.absolute(), backing_resolved))

    def _map_alias(self, raw: Path) -> Path:
        absolute = raw.absolute()
        for target, backing in self.aliases:
            try:
                relative = absolute.relative_to(target)
            except ValueError:
                continue
            return backing / relative
        return absolute

    def file(self, value: str | Path, label: str) -> Path:
        raw = Path(value).expanduser()
        if not raw.is_absolute():
            raise ValidationBlocked(f"{label}_PATH_NOT_ABSOLUTE:{raw}")
        candidate = self._map_alias(raw)
        relative = None
        cursor = None
        for base in (self.runtime_input, self.runtime):
            try:
                relative = candidate.relative_to(base)
                cursor = base
                break
            except ValueError:
                continue
        if relative is None or cursor is None:
            # macOS exposes /var through /private/var.  Canonical containment
            # is still required below; this branch only normalizes such a
            # parent alias, never a symlink inside the private runtime.
            canonical = candidate.resolve(strict=False)
            try:
                relative = canonical.relative_to(self.runtime)
                cursor = self.runtime
            except ValueError as exc:
                raise ValidationBlocked(
                    f"{label}_PATH_ESCAPES_PRIVATE_RUNTIME:{candidate}"
                ) from exc
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValidationBlocked(f"{label}_SYMLINK_REFUSED:{cursor}")
        resolved = candidate.resolve(strict=True)
        if not _inside(resolved, self.runtime) or not resolved.is_file():
            raise ValidationBlocked(f"{label}_FILE_INVALID:{candidate}")
        return resolved

    def directory(self, value: str | Path, label: str) -> Path:
        raw = Path(value).expanduser()
        if not raw.is_absolute():
            raise ValidationBlocked(f"{label}_PATH_NOT_ABSOLUTE:{raw}")
        candidate = self._map_alias(raw)
        relative = None
        cursor = None
        for base in (self.runtime_input, self.runtime):
            try:
                relative = candidate.relative_to(base)
                cursor = base
                break
            except ValueError:
                continue
        if relative is None or cursor is None:
            canonical = candidate.resolve(strict=False)
            try:
                relative = canonical.relative_to(self.runtime)
                cursor = self.runtime
            except ValueError as exc:
                raise ValidationBlocked(
                    f"{label}_PATH_ESCAPES_PRIVATE_RUNTIME:{candidate}"
                ) from exc
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise ValidationBlocked(f"{label}_SYMLINK_REFUSED:{cursor}")
        resolved = candidate.resolve(strict=True)
        if not _inside(resolved, self.runtime) or not resolved.is_dir():
            raise ValidationBlocked(f"{label}_DIRECTORY_INVALID:{candidate}")
        return resolved


def _binding(path: Path, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _check(primary: Path, bindings: Iterable[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    rows = list(bindings)
    if not rows:
        raise ValidationBlocked("VALIDATION_CHECK_HAS_NO_EVIDENCE")
    return {
        "status": "PASS",
        "evidence_path": str(primary),
        "evidence_sha256": sha256_file(primary),
        "evidence_bindings": rows,
        **extra,
    }


def _require_fields_equal(document: Mapping[str, Any], expected: Mapping[str, Any], label: str) -> None:
    for key, value in expected.items():
        if document.get(key) != value:
            raise ValidationBlocked(
                f"{label}_{key.upper()}_MISMATCH:{document.get(key)!r}!={value!r}"
            )


def _git_acceptance(engine: Path, release_commit: str) -> dict[str, Any]:
    if not engine.is_absolute() or not engine.is_dir():
        raise ValidationBlocked(f"REMOTE_ENGINE_ROOT_INVALID:{engine}")
    engine = engine.resolve(strict=True)
    if not (engine / ".git").exists():
        release = _json(engine / "RELEASE_MANIFEST.json", "ARCHIVE_RELEASE_MANIFEST")
        _require_fields_equal(release, {
            "schema": "qingshan.storyclaw.release.v1",
            "git_commit": release_commit,
            "private_runtime_included": False,
            "credentials_included": False,
        }, "ARCHIVE_RELEASE_MANIFEST")
        return {
            "remote_engine_commit": release_commit,
            "remote_worktree_clean": True,
            "remote_diff_sha256": EMPTY_SHA256,
            "remote_checkout_kind": "VERIFIED_RELEASE_ARCHIVE",
        }
    try:
        head = subprocess.check_output(
            ["git", "-C", str(engine), "rev-parse", "HEAD"], text=True,
            stderr=subprocess.STDOUT,
        ).strip()
        status = subprocess.check_output(
            ["git", "-C", str(engine), "status", "--porcelain=v1", "--untracked-files=all"],
            text=True, stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValidationBlocked(f"REMOTE_ENGINE_GIT_AUDIT_FAILED:{exc}") from exc
    if head != release_commit:
        raise ValidationBlocked(f"REMOTE_ENGINE_COMMIT_MISMATCH:{head}!={release_commit}")
    if status.strip():
        raise ValidationBlocked("REMOTE_ENGINE_WORKTREE_NOT_CLEAN")
    return {
        "remote_engine_commit": head,
        "remote_worktree_clean": True,
        "remote_diff_sha256": EMPTY_SHA256,
    }


def _context(inputs: Mapping[str, Any]) -> tuple[Path, Path, dict[str, Any], dict[str, Any], str, str, str]:
    release_commit = str(inputs.get("release_commit") or "").lower()
    episode = str(inputs.get("episode") or "").upper()
    project_id = str(inputs.get("project_id") or "")
    scope = str(inputs.get("series_scope_id") or "")
    if not COMMIT_RE.fullmatch(release_commit):
        raise ValidationBlocked("RELEASE_COMMIT_INVALID")
    if not EPISODE_RE.fullmatch(episode):
        raise ValidationBlocked("EPISODE_INVALID")
    if not project_id or not scope:
        raise ValidationBlocked("PROJECT_OR_SERIES_SCOPE_MISSING")
    runtime = Path(str(inputs.get("private_runtime_root") or "")).expanduser()
    engine = Path(str(inputs.get("remote_engine_root") or "")).expanduser()
    if not runtime.is_absolute() or runtime.is_symlink() or not runtime.is_dir():
        raise ValidationBlocked(f"PRIVATE_RUNTIME_ROOT_INVALID:{runtime}")
    runtime = runtime.resolve(strict=True)
    marker_path = runtime / ".qingshan-private-runtime.json"
    config_path = runtime / "qingshan.json"
    if marker_path.is_symlink() or config_path.is_symlink():
        raise ValidationBlocked("PROJECT_MARKER_OR_CONFIG_SYMLINK_REFUSED")
    marker = _json(marker_path, "PROJECT_MARKER")
    config = _json(config_path, "PROJECT_CONFIG")
    _require_fields_equal(marker, {
        "schema": "storyclaw.nalu.private_project.v1",
        "project_id": project_id,
        "series_scope_id": scope,
    }, "PROJECT_MARKER")
    if episode not in (marker.get("episodes") or []):
        raise ValidationBlocked("EPISODE_NOT_DECLARED_BY_PROJECT")
    if str((config.get("project") or {}).get("id") or "") != project_id:
        raise ValidationBlocked("PROJECT_CONFIG_ID_MISMATCH")
    if str((config.get("storyclaw") or {}).get("series_scope_id") or "") != scope:
        raise ValidationBlocked("PROJECT_CONFIG_SCOPE_MISMATCH")
    if Path(str(marker.get("engine_root") or "")).resolve(strict=True) != engine.resolve(strict=True):
        raise ValidationBlocked("PROJECT_MARKER_ENGINE_ROOT_MISMATCH")
    storage = ((config.get("storyclaw") or {}).get("storage") or {})
    configured_engine = Path(str(storage.get("engine_root") or "")).expanduser()
    if not configured_engine.is_absolute() \
            or configured_engine.resolve(strict=True) != engine.resolve(strict=True):
        raise ValidationBlocked("PROJECT_CONFIG_ENGINE_ROOT_MISMATCH")
    if Path(str(storage.get("workspace_mount_target") or "")) != configured_engine / "workflow/nalu" \
            or Path(str(storage.get("transactions_mount_target") or "")) != configured_engine / "workflow/tasks":
        raise ValidationBlocked("PROJECT_CONFIG_ENGINE_MOUNT_TARGET_MISMATCH")
    return runtime, engine, marker, config, project_id, scope, episode


def _evidence(inputs: Mapping[str, Any], key: str) -> Any:
    evidence = inputs.get("evidence")
    if not isinstance(evidence, dict) or key not in evidence:
        raise ValidationBlocked(f"VALIDATION_EVIDENCE_MISSING:{key}")
    return evidence[key]


def _validate_install_preflight(
    inputs: Mapping[str, Any], guard: PrivatePaths, release_commit: str,
    project_id: str, scope: str, engine: Path,
) -> dict[str, Any]:
    install_path = guard.file(str(_evidence(inputs, "install_receipt")), "INSTALL_RECEIPT")
    preflight_path = guard.file(str(_evidence(inputs, "preflight")), "PREFLIGHT")
    install = _json(install_path, "INSTALL_RECEIPT")
    _require_fields_equal(install, {
        "schema": "storyclaw.nalu.host_install_receipt.v1",
        "status": "PASS",
    }, "INSTALL_RECEIPT")
    isolation_mode = str(install.get("isolation_mode") or "")
    if isolation_mode not in {
        "PER_PROJECT_WORKTREE_VIEW", "PER_PROJECT_VERIFIED_ARCHIVE_VIEW"
    }:
        raise ValidationBlocked(f"INSTALL_RECEIPT_ISOLATION_MODE_MISMATCH:{isolation_mode}")
    if str((install.get("engine") or {}).get("head_commit") or "") != release_commit:
        raise ValidationBlocked("INSTALL_ENGINE_COMMIT_MISMATCH")
    installed_engine = Path(str((install.get("engine") or {}).get("root") or ""))
    if not installed_engine.is_absolute() \
            or installed_engine.resolve(strict=True) != engine.resolve(strict=True):
        raise ValidationBlocked("INSTALL_ENGINE_ROOT_MISMATCH")
    engine_link = install.get("project_engine_link") or {}
    link_path = Path(str(engine_link.get("path") or ""))
    link_target = Path(str(engine_link.get("target") or ""))
    if not link_path.is_absolute() or not link_path.is_symlink() \
            or link_path.resolve(strict=True) != engine.resolve(strict=True) \
            or link_target.resolve(strict=True) != engine.resolve(strict=True):
        raise ValidationBlocked("INSTALL_PROJECT_ENGINE_LINK_MISMATCH")
    verification = install.get("verification") or {}
    if verification.get("status") != "PASS" or verification.get("commit") != release_commit:
        raise ValidationBlocked("INSTALL_VERIFICATION_NOT_BOUND_TO_RELEASE")
    wiring = install.get("wiring")
    if not isinstance(wiring, list):
        raise ValidationBlocked("INSTALL_WIRING_MISSING")
    by_name = {str(row.get("name")): row for row in wiring if isinstance(row, dict)}
    for name in ("episode_workspace", "transaction_store"):
        row = by_name.get(name) or {}
        probe = row.get("storage_probe") or {}
        if row.get("same_storage_object") is not True or any(
            probe.get(field) != "PASS" for field in ("write", "fsync", "flock_nonblocking")
        ):
            raise ValidationBlocked(f"INSTALL_PRIVATE_STORAGE_OR_FLOCK_NOT_PASS:{name}")
    preflight = _json(preflight_path, "PREFLIGHT")
    _require_fields_equal(preflight, {
        "schema": "storyclaw.nalu.preflight.v1", "status": "PASS",
        "engine_commit": release_commit,
        "engine_root": str(engine.resolve(strict=True)),
        "private_runtime_root": str(guard.runtime),
        "project_id": project_id,
        "series_scope_id": scope,
    }, "PREFLIGHT")
    checks = preflight.get("checks")
    if not isinstance(checks, dict):
        raise ValidationBlocked("PREFLIGHT_CHECKS_MISSING")
    required = (
        "engine_root", "nalu_pipeline", "nalu_paths", "runtime_persistent",
        "storage_contract", "engine_code_read_only", "workspace_store",
        "transaction_store", "writer_layers_store", "portable_media",
        "portable_audio_provider", "portable_renderer",
        "stable_release_signature_verifier", "model", "policy_profile",
        "series_scope", "voice_registry",
    )
    for name in required:
        if not isinstance(checks.get(name), dict) or checks[name].get("status") != "PASS":
            raise ValidationBlocked(f"PREFLIGHT_CHECK_NOT_PASS:{name}")
    if checks["model"].get("selected") not in ALLOWED_MODELS:
        raise ValidationBlocked("PREFLIGHT_MODEL_NOT_ALLOWED")
    for name in ("workspace_store", "transaction_store", "writer_layers_store"):
        if checks[name].get("flock") is not True:
            raise ValidationBlocked(f"PREFLIGHT_FLOCK_NOT_PASS:{name}")
    paid_lock = checks.get("paid_lock") or {}
    if paid_lock.get("status") != "PASS" or paid_lock.get("paid_requests_enabled") is not False \
            or paid_lock.get("api_key_present") is not False:
        raise ValidationBlocked("PREFLIGHT_WAS_NOT_CAPTURED_WITH_PAID_ACCESS_DISABLED")
    bindings = [
        _binding(install_path, "install_receipt"),
        _binding(preflight_path, "preflight"),
    ]
    extra: dict[str, Any] = {}
    if isolation_mode == "PER_PROJECT_VERIFIED_ARCHIVE_VIEW":
        base_engine = install.get("base_engine") or {}
        engine_facts = install.get("engine") or {}
        if (
            base_engine.get("checkout_kind") != "PACKAGE_VERIFIED_RELEASE_ARCHIVE"
            or engine_facts.get("checkout_kind")
            not in {"PACKAGE_VERIFIED_RELEASE_ARCHIVE", "VERIFIED_RELEASE_ARCHIVE"}
        ):
            raise ValidationBlocked("INSTALL_ARCHIVE_CHECKOUT_KIND_MISMATCH")
        baseline = install.get("release_baseline") or {}
        manifest_sha = str(baseline.get("talenthub_release_manifest_sha256") or "")
        if baseline.get("status") != "PASS" or not SHA256_RE.fullmatch(manifest_sha):
            raise ValidationBlocked("INSTALL_ARCHIVE_RELEASE_BASELINE_INVALID")
        bootstrap_path = guard.file(
            str(_evidence(inputs, "bootstrap_receipt")), "BOOTSTRAP_RECEIPT"
        )
        bootstrap = _json(bootstrap_path, "BOOTSTRAP_RECEIPT")
        _require_fields_equal(bootstrap, {
            "schema": "storyclaw.nalu.skill_bootstrap.v1",
            "status": "PASS",
            "git_commit": release_commit,
            "private_runtime_root": str(guard.runtime),
            "project_engine": str(engine.resolve(strict=True)),
            "provider_posts": 0,
        }, "BOOTSTRAP_RECEIPT")
        archive_sha = str(bootstrap.get("source_archive_sha256") or "")
        archive_size = bootstrap.get("source_archive_size_bytes")
        if (
            not SHA256_RE.fullmatch(archive_sha)
            or type(archive_size) is not int
            or archive_size <= 0
            or archive_size > 512 * 1024 * 1024
            or base_engine.get("source_archive_sha256") != archive_sha
        ):
            raise ValidationBlocked("BOOTSTRAP_ARCHIVE_BINDING_INVALID")
        archive_path = Path(str(bootstrap.get("source_archive") or "")).expanduser()
        if (
            not archive_path.is_absolute()
            or archive_path.is_symlink()
            or not archive_path.is_file()
            or archive_path.stat().st_size != archive_size
            or sha256_file(archive_path) != archive_sha
        ):
            raise ValidationBlocked("BOOTSTRAP_ARCHIVE_BYTES_MISMATCH")
        manifest_path = Path(
            str(bootstrap.get("talenthub_release_manifest") or "")
        ).expanduser()
        expected_suffix = Path("skills/qingshan-nalu/RELEASE_MANIFEST.json")
        if (
            not manifest_path.is_absolute()
            or manifest_path.is_symlink()
            or Path(*manifest_path.parts[-3:]) != expected_suffix
            or not manifest_path.is_file()
            or sha256_file(manifest_path) != manifest_sha
        ):
            raise ValidationBlocked("BOOTSTRAP_TALENTHUB_MANIFEST_BINDING_INVALID")
        package = _json(manifest_path, "BOOTSTRAP_TALENTHUB_MANIFEST")
        _require_fields_equal(package, {
            "schema": "qingshan.storyclaw.talenthub.release.v1",
            "agent_id": "ai-drama-factory",
            "skill": "qingshan-nalu",
            "git_commit": release_commit,
            "origin_tag_commit": release_commit,
            "source_archive_size_bytes": archive_size,
            "source_archive_sha256": archive_sha,
            "validation_receipt_status": "PASS",
            "public_runtime_only": True,
            "private_validation_contents_included": False,
        }, "BOOTSTRAP_TALENTHUB_MANIFEST")
        bindings.extend([
            _binding(bootstrap_path, "bootstrap_receipt"),
            _binding(manifest_path, "installed_talenthub_release_manifest"),
            _binding(archive_path, "verified_source_archive"),
        ])
        extra = {
            "bootstrap_receipt_sha256": sha256_file(bootstrap_path),
            "source_archive_sha256": archive_sha,
            "talenthub_release_manifest_sha256": manifest_sha,
        }
    return _check(
        preflight_path,
        bindings,
        isolation_mode=isolation_mode,
        flock_probe="PASS",
        provider_posts=0,
        **extra,
    )


def _validate_source(
    guard: PrivatePaths, project_id: str, scope: str,
) -> dict[str, Any]:
    receipt_root = guard.directory(
        guard.runtime / "runtime/receipts/source_intake", "SOURCE_RECEIPT_ROOT"
    )
    paths = sorted(receipt_root.glob("*.json"))
    if not paths:
        raise ValidationBlocked("SOURCE_RECEIPT_REQUIRED")
    bindings: list[dict[str, Any]] = []
    primary: Path | None = None
    source_ids: list[str] = []
    for receipt_index, candidate in enumerate(paths):
        path = guard.file(candidate, f"SOURCE_RECEIPT_{receipt_index}")
        primary = primary or path
        receipt = _json(path, f"SOURCE_RECEIPT_{receipt_index}")
        _require_fields_equal(receipt, {
            "schema": "storyclaw.nalu.source_intake.v1",
            "status": "INGESTED",
            "private_runtime": True,
            "project_id": project_id,
            "series_scope_id": scope,
            "publication_allowed": False,
        }, f"SOURCE_RECEIPT_{receipt_index}")
        source_id = str(receipt.get("source_id") or "")
        if not source_id or source_id in source_ids or path.stem != source_id:
            raise ValidationBlocked(f"SOURCE_RECEIPT_ID_INVALID_OR_DUPLICATE:{receipt_index}")
        source_ids.append(source_id)
        rows = receipt.get("artifacts")
        if not isinstance(rows, list) or not rows:
            raise ValidationBlocked(f"SOURCE_RECEIPT_ARTIFACTS_MISSING:{source_id}")
        bindings.append(_binding(path, f"source_intake_receipt_{receipt_index}"))
        for artifact_index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValidationBlocked(
                    f"SOURCE_ARTIFACT_ROW_INVALID:{receipt_index}:{artifact_index}"
                )
            relative = Path(str(row.get("path") or ""))
            if relative.is_absolute() or ".." in relative.parts:
                raise ValidationBlocked(
                    f"SOURCE_ARTIFACT_RELATIVE_PATH_INVALID:{receipt_index}:{artifact_index}"
                )
            artifact = guard.file(
                guard.runtime / relative,
                f"SOURCE_ARTIFACT_{receipt_index}_{artifact_index}",
            )
            if sha256_file(artifact) != row.get("sha256") \
                    or artifact.stat().st_size != row.get("size_bytes"):
                raise ValidationBlocked(
                    f"SOURCE_ARTIFACT_BINDING_MISMATCH:{receipt_index}:{artifact_index}"
                )
            bindings.append(
                _binding(artifact, f"source_artifact_{receipt_index}_{artifact_index}")
            )
    assert primary is not None
    return _check(primary, bindings, source_count=len(paths), source_ids=source_ids)


def _stage_status(state: Mapping[str, Any], stage: str) -> str:
    row = (state.get("stages") or {}).get(stage)
    return str((row or {}).get("status") or "") if isinstance(row, dict) else ""


def _state_and_writer(
    guard: PrivatePaths, project_id: str, scope: str, episode: str,
) -> tuple[dict[str, Any], Path, dict[str, Any], Path, dict[str, Any], Path, dict[str, Any]]:
    state_path = guard.file(
        guard.runtime / "runtime/pipeline_state" / f"{episode}.json", "PIPELINE_STATE"
    )
    state = _json(state_path, "PIPELINE_STATE")
    _require_fields_equal(state, {"schema": "nalu.pipeline_state.v1", "episode": episode}, "PIPELINE_STATE")
    state_scope = str(((state.get("series_scope") or {}).get("scope_id") or state.get("series_scope_id") or ""))
    if state_scope != scope:
        raise ValidationBlocked("PIPELINE_STATE_SCOPE_MISMATCH")
    if _stage_status(state, "S1") not in TERMINAL_STAGE_STATUSES or \
            _stage_status(state, "S2") not in TERMINAL_STAGE_STATUSES:
        raise ValidationBlocked("S1_OR_S2_NOT_PASS")
    verification = _writer.verify_writer_handoff(guard.runtime, episode)
    if verification.get("status") != "PASS":
        raise ValidationBlocked(
            "WRITER_HANDOFF_VERIFY_FAILED:" + ",".join(verification.get("failures") or [])
        )
    active_path = guard.file(
        guard.runtime / "writer_layers" / scope / episode / _writer.ACTIVE_NAME,
        "ACTIVE_WRITER_HANDOFF",
    )
    active = _json(active_path, "ACTIVE_WRITER_HANDOFF")
    _require_fields_equal(active, {
        "schema": _writer.ACTIVE_SCHEMA, "status": "SEALED",
        "project_id": project_id, "series_scope_id": scope, "episode": episode,
    }, "ACTIVE_WRITER_HANDOFF")
    s1_detail = ((state.get("stages") or {}).get("S1") or {}).get("details") or {}
    s1_ref = s1_detail.get("s1_gate_receipt") or {}
    s1_path = guard.file(str(s1_ref.get("path") or ""), "S1_GATE_RECEIPT")
    if s1_ref.get("sha256") != sha256_file(s1_path):
        raise ValidationBlocked("S1_GATE_RECEIPT_STATE_SHA_MISMATCH")
    s1 = _json(s1_path, "S1_GATE_RECEIPT")
    _require_fields_equal(s1, {
        "schema": "nalu.s1_gate_receipt.v1", "episode": episode,
        "series_scope_id": scope, "stage": "S1", "status": "PASS",
        "policy_profile": "CURRENT_PORTABLE",
    }, "S1_GATE_RECEIPT")
    gates = s1.get("gates")
    if not isinstance(gates, dict) or not gates or any(value != "PASS" for value in gates.values()):
        raise ValidationBlocked("S1_REGISTERED_GATE_NOT_PASS")
    active_layers = active.get("layers") or {}
    for active_key in (
        "narrative_canonical", "directing_script",
        "generation_contract", "writer_manifest",
    ):
        if (active_layers.get(active_key) or {}).get("sha256") != (s1.get("layer_sha256") or {}).get(active_key):
            raise ValidationBlocked(f"S1_ACTIVE_WRITER_LAYER_SHA_MISMATCH:{active_key}")
    selfcheck = s1.get("writer_selfcheck_seq29") or {}
    seq_path = guard.file(str(selfcheck.get("report") or ""), "SEQ29_REPORT")
    if selfcheck.get("status") != "PASS" or selfcheck.get("enforced") is not True \
            or selfcheck.get("report_sha256") != sha256_file(seq_path):
        raise ValidationBlocked("SEQ29_NOT_ENFORCED_PASS_OR_SHA_MISMATCH")
    seq = _json(seq_path, "SEQ29_REPORT")
    if seq.get("status") != "PASS" or seq.get("enforced") is not True or seq.get("episode") != episode:
        raise ValidationBlocked("SEQ29_REPORT_NOT_PASS")
    s2_detail = ((state.get("stages") or {}).get("S2") or {}).get("details") or {}
    s2_ref = s2_detail.get("s2_preproduction_receipt") or {}
    s2_raw = str(s2_ref.get("path") or "")
    if not s2_raw:
        s2_raw = str(guard.runtime / "runtime/pipeline_logs" / episode / "S2_PREPRODUCTION_RECEIPT.json")
    s2_path = guard.file(s2_raw, "S2_PREPRODUCTION_RECEIPT")
    if s2_ref.get("sha256") and s2_ref.get("sha256") != sha256_file(s2_path):
        raise ValidationBlocked("S2_RECEIPT_STATE_SHA_MISMATCH")
    s2 = _json(s2_path, "S2_PREPRODUCTION_RECEIPT")
    _require_fields_equal(s2, {
        "schema": "nalu.s2_preproduction_receipt.v1", "episode": episode,
        "series_scope_id": scope, "stage": "S2", "status": "PASS",
        "policy_profile": "CURRENT_PORTABLE", "keyframes_included": False,
    }, "S2_PREPRODUCTION_RECEIPT")
    if s2.get("generation_contract_sha256") != (active_layers.get("generation_contract") or {}).get("sha256") \
            or s2.get("writer_manifest_sha256") != (active_layers.get("writer_manifest") or {}).get("sha256"):
        raise ValidationBlocked("S2_WRITER_LAYER_SHA_MISMATCH")
    for field in ("global_space_map_sha256", "asset_requirements_sha256", "preproduction_report_sha256"):
        if not SHA256_RE.fullmatch(str(s2.get(field) or "")):
            raise ValidationBlocked(f"S2_ARTIFACT_SHA_INVALID:{field}")
    return state, state_path, active, active_path, s1, s1_path, {**s2, "_path": str(s2_path)}


def _validate_s1_s2(
    guard: PrivatePaths, project_id: str, scope: str, episode: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    state, state_path, active, active_path, s1, s1_path, s2 = _state_and_writer(
        guard, project_id, scope, episode
    )
    bindings = [
        _binding(state_path, "pipeline_state"), _binding(active_path, "active_writer_handoff"),
        _binding(s1_path, "s1_gate_receipt"),
        _binding(Path(s2["_path"]), "s2_preproduction_receipt"),
    ]
    for name, row in (active.get("layers") or {}).items():
        bindings.append(_binding(guard.file(str((row or {}).get("path") or ""), f"WRITER_LAYER_{name}"), f"writer_layer_{name}"))
    for name in ("four_layer_seal", "writer_receipt", "input_bundle", "project_lexicon"):
        row = active.get(name) or {}
        bound = guard.file(str(row.get("path") or ""), f"WRITER_{name}")
        if row.get("sha256") != sha256_file(bound):
            raise ValidationBlocked(f"ACTIVE_WRITER_{name.upper()}_SHA_MISMATCH")
        bindings.append(_binding(bound, name))
    return _check(state_path, bindings, s1="PASS", s2="PASS"), state, s2


def _validate_asset_confirmation(
    guard: PrivatePaths, marker: Mapping[str, Any], episode: str,
    state: Mapping[str, Any],
) -> dict[str, Any]:
    context, failures = _guided._asset_context(guard.runtime, marker, episode, state)
    if context is None:
        raise ValidationBlocked("ASSET_CONTEXT_INVALID:" + ",".join(failures))
    plan_path = guard.file(
        guard.runtime / "runtime/asset_plans" / str(marker["series_scope_id"])
        / f"{episode}_ASSET_MATCH_PLAN.json",
        "ASSET_PLAN",
    )
    report = _asset_gate.validate_asset_plan(plan_path, **context)
    if report.get("status") != "PASS":
        raise ValidationBlocked("ASSET_PLAN_NOT_PASS:" + ",".join(report.get("failures") or []))
    wrapper_path = guard.file(
        plan_path.parent / f"{episode}_ASSET_MATCH_CONFIRMATION.json",
        "ASSET_CONFIRMATION_BINDING",
    )
    wrapper = _json(wrapper_path, "ASSET_CONFIRMATION_BINDING")
    _require_fields_equal(wrapper, {
        "schema": "storyclaw.asset_plan_confirmation.v2",
        "status": "CONFIRMED", "episode": episode,
        "series_scope_id": marker["series_scope_id"],
        "asset_plan_sha256": report["asset_plan_sha256"],
        "script_evidence_sha256": report["script_evidence_sha256"],
    }, "ASSET_CONFIRMATION_BINDING")
    receipt_path = guard.file(str(wrapper.get("receipt_path") or ""), "ASSET_CONFIRMATION_RECEIPT")
    if wrapper.get("receipt_sha256") != sha256_file(receipt_path):
        raise ValidationBlocked("ASSET_CONFIRMATION_RECEIPT_SHA_MISMATCH")
    config = _json(guard.runtime / "qingshan.json", "PROJECT_CONFIG")
    confirmation = _asset_gate.validate_confirmation_receipt(
        receipt_path,
        receipt_root=Path(str((config.get("authorization") or {}).get("confirmation_receipts_root") or "")),
        expected_receipt_sha256=str(wrapper["receipt_sha256"]),
        expected_line_owner_id=str((config.get("authorization") or {}).get("line_owner_id") or ""),
        plan_path=plan_path,
        **context,
    )
    if confirmation.get("status") != "PASS":
        raise ValidationBlocked(
            "ASSET_CONFIRMATION_NOT_PASS:" + ",".join(confirmation.get("failures") or [])
        )
    return _check(
        wrapper_path,
        [_binding(plan_path, "complete_asset_plan"), _binding(wrapper_path, "confirmation_binding"),
         _binding(receipt_path, "line_owner_confirmation_receipt")],
        asset_plan_sha256=report["asset_plan_sha256"],
        script_evidence_sha256=report["script_evidence_sha256"],
        confirmation_count=1,
    )


def _validate_run_context(
    receipt: Mapping[str, Any], *, release_commit: str, project_id: str,
    scope: str, episode: str, label: str,
) -> None:
    _require_fields_equal(receipt, {
        "schema": "storyclaw.nalu.run.v1", "release_commit": release_commit,
        "project_id": project_id, "series_scope_id": scope, "episode": episode,
        "policy_profile": "CURRENT_PORTABLE",
    }, label)
    if receipt.get("model") not in ALLOWED_MODELS or (receipt.get("model_evidence") or {}).get("status") != "PASS":
        raise ValidationBlocked(f"{label}_MODEL_EVIDENCE_NOT_PASS")
    if receipt.get("singleflight_acquired") is not True:
        raise ValidationBlocked(f"{label}_SINGLEFLIGHT_NOT_ACQUIRED")


def _validate_s5_dry(
    inputs: Mapping[str, Any], guard: PrivatePaths, release_commit: str,
    project_id: str, scope: str, episode: str,
) -> dict[str, Any]:
    path = guard.file(str(_evidence(inputs, "s5_dry_run_receipt")), "S5_DRY_RUN_RECEIPT")
    receipt = _json(path, "S5_DRY_RUN_RECEIPT")
    _validate_run_context(receipt, release_commit=release_commit, project_id=project_id,
                          scope=scope, episode=episode, label="S5_DRY_RUN_RECEIPT")
    expected = {
        "from_stage": "S5", "until_stage": "S5", "target_stage": "S5",
        "dry_run": True, "provider_posts_allowed": False, "paid_posts": 0,
        "exit_code": 0,
    }
    _require_fields_equal(receipt, expected, "S5_DRY_RUN_RECEIPT")
    locks = receipt.get("paid_lock_evidence") or {}
    if locks.get("provider_key_present") is not False:
        raise ValidationBlocked("S5_DRY_RUN_PROVIDER_KEY_WAS_PRESENT")
    return _check(path, [_binding(path, "s5_dry_run_receipt")], paid_posts=0)


def _grouping_plan(guard: PrivatePaths, episode: str) -> tuple[Path, dict[str, Any], list[str]]:
    config = _json(guard.runtime / "qingshan.json", "PROJECT_CONFIG")
    backing = Path(str((((config.get("storyclaw") or {}).get("storage") or {}).get(
        "workspace_backing_path"
    )) or ""))
    path = guard.file(
        backing / episode / "preproduction" / f"{episode}_VIDEO_UNIT_GROUPING_PLAN_V1.json",
        "VIDEO_UNIT_GROUPING_PLAN",
    )
    plan = _json(path, "VIDEO_UNIT_GROUPING_PLAN")
    if not str(plan.get("schema") or "").startswith("qingshan.video_unit_grouping_plan."):
        raise ValidationBlocked("VIDEO_UNIT_GROUPING_PLAN_SCHEMA_INVALID")
    rows = plan.get("units")
    if not isinstance(rows, list) or len(rows) != 2:
        raise ValidationBlocked(f"PAID_TRIAL_REQUIRES_EXACTLY_TWO_UNITS:{len(rows or [])}")
    unit_ids = [str((row or {}).get("unit_id") or "") for row in rows]
    if any(not value for value in unit_ids) or len(set(unit_ids)) != 2:
        raise ValidationBlocked("PAID_TRIAL_UNIT_IDS_INVALID")
    return path, plan, unit_ids


def _validate_paid_trial(
    inputs: Mapping[str, Any], guard: PrivatePaths, release_commit: str,
    project_id: str, scope: str, episode: str, state: Mapping[str, Any], s2: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    raw_receipts = _evidence(inputs, "paid_run_receipts")
    if not isinstance(raw_receipts, list) or not raw_receipts:
        raise ValidationBlocked("PAID_RUN_RECEIPTS_MISSING")
    bindings: list[dict[str, Any]] = []
    saw_success = False
    paid_stage_coverage: set[str] = set()
    for index, raw in enumerate(raw_receipts):
        path = guard.file(str(raw), f"PAID_RUN_RECEIPT_{index}")
        receipt = _json(path, f"PAID_RUN_RECEIPT_{index}")
        _validate_run_context(receipt, release_commit=release_commit, project_id=project_id,
                              scope=scope, episode=episode, label=f"PAID_RUN_RECEIPT_{index}")
        if receipt.get("paid_requested") is not True or receipt.get("dry_run") is not False \
                or receipt.get("provider_posts_allowed") is not True:
            raise ValidationBlocked(f"PAID_RUN_NOT_REAL_PROVIDER_ROUTE:{index}")
        locks = receipt.get("paid_lock_evidence") or {}
        if locks.get("both_config_locks_enabled") is not True \
                or locks.get("generation_paid_requests_enabled") is not True \
                or locks.get("storyclaw_paid_requests_enabled") is not True \
                or locks.get("provider_key_present") is not True:
            raise ValidationBlocked(f"PAID_RUN_DOUBLE_LOCK_OR_SECRET_INJECTION_NOT_PROVEN:{index}")
        if not isinstance(receipt.get("exit_code"), int) or receipt.get("exception"):
            raise ValidationBlocked(f"PAID_RUN_RECEIPT_INVALID_EXIT:{index}")
        start = str(receipt.get("from_stage") or "")
        stop = str(receipt.get("until_stage") or start)
        if start not in {f"S{i}" for i in range(1, 9)} \
                or stop not in {f"S{i}" for i in range(1, 9)} \
                or int(start[1:]) > int(stop[1:]):
            raise ValidationBlocked(f"PAID_RUN_STAGE_RANGE_INVALID:{index}")
        paid_stage_coverage.update(
            f"S{i}" for i in range(int(start[1:]), int(stop[1:]) + 1)
            if i in range(3, 7)
        )
        saw_success = saw_success or receipt.get("exit_code") == 0
        bindings.append(_binding(path, f"paid_run_receipt_{index}"))
    if not saw_success:
        raise ValidationBlocked("PAID_TRIAL_HAS_NO_SUCCESSFUL_RUN")
    if paid_stage_coverage != {"S3", "S4", "S5", "S6"}:
        raise ValidationBlocked(
            f"PAID_RUN_RECEIPTS_DO_NOT_COVER_S3_S6:{sorted(paid_stage_coverage)}"
        )
    for stage in ("S3", "S4", "S5", "S6", "S7", "S8"):
        if _stage_status(state, stage) not in TERMINAL_STAGE_STATUSES:
            raise ValidationBlocked(f"PAID_TRIAL_STAGE_NOT_PASS:{stage}:{_stage_status(state, stage)}")
        receipts = ((state.get("stages") or {}).get(stage) or {}).get("receipts")
        if not isinstance(receipts, list) or not any(str(value).strip() for value in receipts):
            raise ValidationBlocked(f"PAID_TRIAL_STAGE_RECEIPTS_MISSING:{stage}")
        for receipt_index, value in enumerate(receipts):
            if not str(value).strip():
                continue
            stage_receipt = guard.file(
                str(value), f"{stage}_STAGE_RECEIPT_{receipt_index}"
            )
            bindings.append(
                _binding(stage_receipt, f"{stage.lower()}_stage_receipt_{receipt_index}")
            )
    if state.get("overall_status") != "APPROVED" or (state.get("approval") or {}).get("status") != "APPROVED":
        raise ValidationBlocked("PAID_TRIAL_NOT_APPROVED_AT_S8")
    grouping_path, _grouping, unit_ids = _grouping_plan(guard, episode)
    if s2.get("video_unit_count") != 2:
        raise ValidationBlocked("S2_RECEIPT_UNIT_COUNT_NOT_TWO")
    bindings.append(_binding(grouping_path, "two_unit_grouping_plan"))
    return _check(
        grouping_path, bindings, unit_count=2, unit_ids=unit_ids,
        stages={stage: "PASS" for stage in ("S3", "S4", "S5", "S6", "S7", "S8")},
    ), unit_ids


def _validate_paid_authority(
    guard: PrivatePaths, config: Mapping[str, Any], state: Mapping[str, Any],
    episode: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    authority = state.get("line_owner_authority")
    if not isinstance(authority, dict) or authority.get("status") != "PASS" or authority.get("failures"):
        raise ValidationBlocked("PIPELINE_LINE_OWNER_AUTHORITY_NOT_PASS")
    orders_path = guard.file(str(authority.get("orders_path") or ""), "SUPERVISOR_ORDERS")
    if authority.get("orders_file_sha256") != sha256_file(orders_path):
        raise ValidationBlocked("SUPERVISOR_ORDERS_STATE_SHA_MISMATCH")
    orders = _json(orders_path, "SUPERVISOR_ORDERS")
    if orders.get("_schema") != "supervisor_orders_v1":
        raise ValidationBlocked("SUPERVISOR_ORDERS_SCHEMA_INVALID")
    seq = authority.get("paid_order_seq")
    latest = authority.get("latest_order_seq")
    if not isinstance(seq, int) or seq < 1 or not isinstance(latest, int) or latest < seq \
            or orders.get("latest_order_seq") != latest:
        raise ValidationBlocked("SUPERVISOR_ORDER_SEQUENCE_INVALID")
    rows = orders.get("orders")
    matches = [row for row in (rows or []) if isinstance(row, dict) and row.get("seq") == seq]
    if len(matches) != 1:
        raise ValidationBlocked("ACTIVE_PAID_ORDER_NOT_UNIQUE")
    order = matches[0]
    owner = str((config.get("authorization") or {}).get("line_owner_id") or "")
    decision = order.get("decision") or {}
    cap = int((config.get("generation") or {}).get("budget_cap_credits_per_episode") or state.get("cap_credits") or 0)
    if not owner or order.get("status") != "active" or order.get("issued_by") != owner \
            or order.get("id") != authority.get("order_id"):
        raise ValidationBlocked("PAID_ORDER_OWNER_OR_ID_MISMATCH")
    if decision.get("kind") != "PAID_PRODUCTION_AUTHORIZATION" \
            or decision.get("paid_requests_allowed") is not True \
            or decision.get("publication_allowed") is not False \
            or set(decision.get("paid_stages") or []) != {"S3", "S4", "S5", "S6"} \
            or episode not in (decision.get("episode_scope") or []) \
            or decision.get("budget_cap_credits_per_episode") != cap:
        raise ValidationBlocked("PAID_ORDER_SCOPE_STAGES_OR_CAP_INVALID")
    source = order.get("source_receipt")
    if not isinstance(source, dict):
        raise ValidationBlocked("PAID_ORDER_SOURCE_RECEIPT_BINDING_MISSING")
    receipt_path = guard.file(str(source.get("path") or ""), "PAID_ORDER_SOURCE_RECEIPT")
    if source.get("sha256") != sha256_file(receipt_path):
        raise ValidationBlocked("PAID_ORDER_SOURCE_RECEIPT_SHA_MISMATCH")
    receipt = _json(receipt_path, "PAID_ORDER_SOURCE_RECEIPT")
    _require_fields_equal(receipt, {
        "schema": "qingshan.line_owner_order_source_receipt.v1",
        "status": "CONFIRMED",
        "order_seq": seq, "order_id": order.get("id"), "issued_by": owner,
        "verbatim": order.get("order"),
    }, "PAID_ORDER_SOURCE_RECEIPT")
    if not str(receipt.get("recorded_at_utc") or ""):
        raise ValidationBlocked("PAID_ORDER_SOURCE_RECEIPT_TIMESTAMP_MISSING")
    return _check(
        orders_path,
        [_binding(orders_path, "supervisor_orders"), _binding(receipt_path, "paid_order_source_receipt")],
        order_id=order.get("id"), order_seq=seq,
        paid_stages=["S3", "S4", "S5", "S6"], budget_cap_credits=cap,
        publication_allowed=False,
    ), {
        "id": order.get("id"), "seq": seq,
        "issued_by": owner,
        "orders_path": str(orders_path),
        "orders_sha256": sha256_file(orders_path),
        "source_receipt": dict(source),
    }


def _transaction_kind(path: Path, row: Mapping[str, Any]) -> str | None:
    if row.get("schema") == "qingshan.storyclaw_audio_transaction.v1":
        return "audio"
    if "submission_fingerprint" in row and "task_id" in row:
        if "giggle_video_submit_transactions" in path.parts:
            return "video"
        if "giggle_submit_transactions" in path.parts:
            return "image"
    return None


def _workspace_manifest_expectations(
    guard: PrivatePaths, config: Mapping[str, Any], episode: str,
    order: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Rebuild paid image/video fingerprints from the submitted manifests.

    Transaction JSON is an exactly-once store, not an independent description
    of what should have been submitted.  This binds each transaction back to
    the authoritative workspace task and re-hashes every prompt/reference file.
    """
    storage = ((config.get("storyclaw") or {}).get("storage") or {})
    backing = guard.directory(
        Path(str(storage.get("workspace_backing_path") or "")),
        "WORKSPACE_BACKING",
    )
    episode_root = guard.directory(backing / episode, "EPISODE_WORKSPACE")
    manifest_specs: tuple[tuple[str, Path, bool], ...] = (
        ("identity", episode_root / "identity/character_asset_plan.json", False),
        ("image", episode_root / "preproduction" / f"{episode}_KEYFRAME_IMAGE_MANIFEST_V1.json", False),
        ("video", episode_root / "preproduction" / f"{episode}_VIDEO_TRANSACTION_MANIFEST_V1.json", True),
    )
    expected: dict[str, dict[str, Any]] = {}
    bindings: list[dict[str, Any]] = []

    def artifact(value: Any, label: str) -> Path:
        raw = Path(str(value or "")).expanduser()
        if not raw.is_absolute():
            # Workspace manifests historically store repository-relative
            # ``workflow/nalu/...`` paths.  Map that prefix directly to the
            # private backing instead of trusting the public checkout.
            parts = raw.parts
            try:
                index = parts.index("nalu")
            except ValueError as exc:
                raise ValidationBlocked(f"{label}_RELATIVE_PATH_NOT_WORKSPACE:{raw}") from exc
            raw = backing.joinpath(*parts[index + 1:])
        return guard.file(raw, label)

    def add_task(kind: str, task: Mapping[str, Any], manifest_path: Path) -> None:
        if kind == "identity":
            key = str(task.get("id") or "")
            fingerprint = _identity_submitter.submission_fingerprint(
                dict(task), "gpt-image-2-pro", "2K"
            )
            references = list(task.get("reference_image_sha256s") or [])
            reference_paths = list(task.get("reference_images") or [])
        elif kind == "image":
            key = str(task.get("task_key") or "")
            fingerprint = _image_submitter.submission_fingerprint(dict(task))
            ref_rows = list(task.get("reference_bindings") or [])
            references = [str((row or {}).get("sha256") or "") for row in ref_rows]
            reference_paths = [
                (row or {}).get("path") or (row or {}).get("image_path")
                for row in ref_rows
            ]
        else:
            key = str(task.get("task_key") or "")
            fingerprint = _video_submitter.task_fingerprint(dict(task))
            references = list(task.get("reference_sha256") or [])
            reference_paths = list(task.get("reference_images") or [])
        if not key or key in expected:
            raise ValidationBlocked(f"PAID_MANIFEST_TASK_KEY_INVALID_OR_DUPLICATE:{key!r}")
        prompt_sha = str(task.get("prompt_sha256") or "")
        if not SHA256_RE.fullmatch(prompt_sha):
            raise ValidationBlocked(f"PAID_MANIFEST_PROMPT_SHA_INVALID:{key}")
        prompt_path = artifact(task.get("prompt_file"), f"PAID_PROMPT_{key}")
        if sha256_file(prompt_path) != prompt_sha:
            raise ValidationBlocked(f"PAID_MANIFEST_PROMPT_SHA_MISMATCH:{key}")
        if len(references) != len(reference_paths):
            raise ValidationBlocked(f"PAID_MANIFEST_REFERENCE_COUNT_MISMATCH:{key}")
        reference_bindings: list[dict[str, Any]] = []
        for index, (path_value, wanted) in enumerate(zip(reference_paths, references)):
            if not SHA256_RE.fullmatch(str(wanted or "")):
                raise ValidationBlocked(f"PAID_MANIFEST_REFERENCE_SHA_INVALID:{key}:{index}")
            reference_path = artifact(path_value, f"PAID_REFERENCE_{key}_{index}")
            actual = sha256_file(reference_path)
            if actual != wanted:
                raise ValidationBlocked(f"PAID_MANIFEST_REFERENCE_SHA_MISMATCH:{key}:{index}")
            reference_bindings.append(_binding(reference_path, f"reference_{key}_{index}"))
        expected[key] = {
            "kind": kind,
            "fingerprint": fingerprint,
            "prompt_sha256": prompt_sha,
            "reference_sha256": references,
            "manifest": str(manifest_path),
        }
        bindings.append(_binding(prompt_path, f"prompt_{key}"))
        bindings.extend(reference_bindings)

    for kind, raw_path, required in manifest_specs:
        if not raw_path.exists():
            if required:
                raise ValidationBlocked(f"PAID_MANIFEST_MISSING:{kind}:{raw_path}")
            continue
        path = guard.file(raw_path, f"PAID_{kind.upper()}_MANIFEST")
        payload = _json(path, f"PAID_{kind.upper()}_MANIFEST")
        if str(payload.get("episode") or "").upper() != episode:
            raise ValidationBlocked(f"PAID_MANIFEST_EPISODE_MISMATCH:{kind}")
        rows = payload.get("new_asset_groups") if kind == "identity" else payload.get("tasks")
        if not isinstance(rows, list):
            raise ValidationBlocked(f"PAID_MANIFEST_TASKS_INVALID:{kind}")
        if rows:
            paid_authority = payload.get("paid_authorization") or {}
            expected_authority = {
                "authorization_ref": order["id"],
                "provider_post_allowed": True,
            }
            _require_fields_equal(payload, expected_authority, f"PAID_{kind.upper()}_MANIFEST")
            _require_fields_equal(paid_authority, {
                "order_seq": order["seq"],
                "order_id": order["id"],
                "issued_by": order["issued_by"],
                "orders_file_sha256": order["orders_sha256"],
                "source_receipt": order["source_receipt"],
                "episode": episode,
            }, f"PAID_{kind.upper()}_MANIFEST_AUTHORITY")
            bound_orders = guard.file(
                str(paid_authority.get("orders_file") or ""),
                f"PAID_{kind.upper()}_MANIFEST_ORDERS",
            )
            if bound_orders != Path(str(order["orders_path"])).resolve(strict=True):
                raise ValidationBlocked(f"PAID_{kind.upper()}_MANIFEST_ORDERS_PATH_MISMATCH")
            source = paid_authority.get("source_receipt") or {}
            source_path = guard.file(
                str(source.get("path") or ""),
                f"PAID_{kind.upper()}_MANIFEST_ORDER_SOURCE",
            )
            if source.get("sha256") != sha256_file(source_path):
                raise ValidationBlocked(f"PAID_{kind.upper()}_MANIFEST_ORDER_SOURCE_SHA_MISMATCH")
            bindings.extend([
                _binding(bound_orders, f"{kind}_manifest_supervisor_orders"),
                _binding(source_path, f"{kind}_manifest_order_source"),
            ])
            for task_index, task in enumerate(rows):
                if not isinstance(task, dict) \
                        or task.get("authorization_ref") != order["id"] \
                        or task.get("provider_post_allowed") is not True \
                        or task.get("maximum_new_submissions") != 1 \
                        or task.get("status") != "READY_TO_SUBMIT":
                    raise ValidationBlocked(
                        f"PAID_{kind.upper()}_TASK_AUTHORITY_MISMATCH:{task_index}"
                    )
        bindings.append(_binding(path, f"{kind}_submission_manifest"))
        for task in rows:
            if not isinstance(task, dict):
                raise ValidationBlocked(f"PAID_MANIFEST_TASK_INVALID:{kind}")
            add_task(kind, task, path)
    return expected, bindings


def _validate_transactions(
    guard: PrivatePaths, config: Mapping[str, Any], episode: str,
    unit_ids: Sequence[str], order: Mapping[str, Any],
) -> tuple[dict[str, Any], set[str]]:
    root = guard.directory(
        Path(str((((config.get("storyclaw") or {}).get("storage") or {}).get(
            "transactions_backing_path"
        )) or "")), "TRANSACTION_STORE"
    )
    expectations, manifest_bindings = _workspace_manifest_expectations(
        guard, config, episode, order
    )
    rows: list[tuple[Path, dict[str, Any], str]] = []
    for candidate in sorted(root.rglob("*.json")):
        try:
            path = guard.file(candidate, "TRANSACTION_FILE")
            payload = _json(path, "TRANSACTION_FILE")
        except ValidationBlocked:
            raise
        kind = _transaction_kind(path, payload)
        if kind is None:
            continue
        if episode not in path.parts and str(payload.get("episode") or "").upper() != episode:
            continue
        rows.append((path, payload, kind))
    if not rows:
        raise ValidationBlocked("PAID_TRIAL_HAS_NO_DURABLE_TRANSACTIONS")
    task_ids: list[str] = []
    fingerprints: list[str] = []
    video_units: list[str] = []
    bindings: list[dict[str, Any]] = list(manifest_bindings)
    for index, (path, row, kind) in enumerate(rows):
        task_id = str(row.get("task_id") or "")
        if not task_id:
            raise ValidationBlocked(f"TRANSACTION_TASK_ID_MISSING:{path}")
        task_ids.append(task_id)
        key = str(row.get("task_key") or "")
        if kind == "audio":
            if row.get("state") != "TERMINAL_COMPLETED" or row.get("provider_post_count") != 1:
                raise ValidationBlocked(f"AUDIO_TRANSACTION_NOT_SINGLE_POST_COMPLETED:{path}")
            fingerprint = str(row.get("request_fingerprint_sha256") or "")
            request = row.get("request") or {}
            request_hash = request.get("prompt_sha256") or request.get("text_sha256")
            paid = row.get("paid_authority") or {}
            if paid.get("authorization_ref") != order["id"] \
                    or str(paid.get("order_seq")) != str(order["seq"]) \
                    or paid.get("orders_sha256") != order["orders_sha256"]:
                raise ValidationBlocked(f"AUDIO_TRANSACTION_ORDER_BINDING_MISMATCH:{path}")
            reference_values: list[str] = []
            result = row.get("result") or {}
            audio_outputs: list[Mapping[str, Any]] = []
            if isinstance(result.get("file"), dict):
                audio_outputs.append(result["file"])
            audio_outputs.extend(
                value for value in (result.get("files") or []) if isinstance(value, dict)
            )
            if not audio_outputs:
                raise ValidationBlocked(f"AUDIO_TRANSACTION_OUTPUT_BINDING_MISSING:{path}")
            for output_index, output in enumerate(audio_outputs):
                output_path = guard.file(
                    str(output.get("path") or ""),
                    f"AUDIO_TRANSACTION_OUTPUT_{index}_{output_index}",
                )
                if output.get("sha256") != sha256_file(output_path):
                    raise ValidationBlocked(
                        f"AUDIO_TRANSACTION_OUTPUT_SHA_MISMATCH:{path}:{output_index}"
                    )
                bindings.append(
                    _binding(output_path, f"audio_output_{index}_{output_index}")
                )
        else:
            if row.get("state") != "SUBMITTED_TASK_ID_BOUND":
                raise ValidationBlocked(f"IMAGE_VIDEO_TRANSACTION_NOT_TASK_BOUND:{path}")
            fingerprint = str(row.get("submission_fingerprint") or "")
            request_hash = row.get("prompt_sha256")
            raw_references = (
                row.get("reference_image_sha256s")
                if kind == "image" and "reference_image_sha256s" in row
                else row.get("reference_sha256")
            )
            reference_values = list(raw_references or [])
            expected = expectations.get(key)
            if expected is None or expected["kind"] != kind:
                raise ValidationBlocked(f"TRANSACTION_NOT_BOUND_TO_PAID_MANIFEST:{path}")
            if fingerprint != expected["fingerprint"] \
                    or request_hash != expected["prompt_sha256"] \
                    or reference_values != expected["reference_sha256"]:
                raise ValidationBlocked(f"TRANSACTION_MANIFEST_BINDING_MISMATCH:{path}")
            if kind == "video":
                video_units.append(key)
                if not reference_values:
                    raise ValidationBlocked(f"VIDEO_TRANSACTION_REFERENCE_SHA_MISSING:{path}")
        if not SHA256_RE.fullmatch(fingerprint) or not SHA256_RE.fullmatch(str(request_hash or "")):
            raise ValidationBlocked(f"TRANSACTION_FINGERPRINT_OR_PROMPT_SHA_INVALID:{path}")
        if any(not SHA256_RE.fullmatch(str(value or "")) for value in reference_values):
            raise ValidationBlocked(f"TRANSACTION_REFERENCE_SHA_INVALID:{path}")
        fingerprints.append(fingerprint)
        bindings.append(_binding(path, f"{kind}_transaction_{index}"))
    if len(task_ids) != len(set(task_ids)):
        raise ValidationBlocked("DUPLICATE_PROVIDER_TASK_ID_ACROSS_TRANSACTIONS")
    if len(fingerprints) != len(set(fingerprints)):
        raise ValidationBlocked("DUPLICATE_SUBMISSION_FINGERPRINT_ACROSS_TRANSACTIONS")
    if sorted(video_units) != sorted(unit_ids):
        raise ValidationBlocked(
            f"VIDEO_TRANSACTION_UNIT_SET_MISMATCH:{sorted(video_units)}!={sorted(unit_ids)}"
        )
    submitted_non_audio = {
        str(row.get("task_key") or "")
        for _path, row, kind in rows if kind != "audio"
    }
    expected_video = {
        key for key, value in expectations.items() if value["kind"] == "video"
    }
    if submitted_non_audio - set(expectations) or not expected_video.issubset(submitted_non_audio):
        raise ValidationBlocked("PAID_MANIFEST_TRANSACTION_COVERAGE_MISMATCH")
    return _check(
        rows[0][0], bindings, transaction_count=len(rows),
        task_id_count=len(task_ids), duplicate_posts_detected=False,
        video_unit_ids=sorted(unit_ids),
    ), set(task_ids)


def _validate_ledger(
    inputs: Mapping[str, Any], guard: PrivatePaths, episode: str,
    transaction_task_ids: set[str],
) -> dict[str, Any]:
    budget_path = guard.file(str(_evidence(inputs, "budget_report")), "BUDGET_REPORT")
    provider_path = guard.file(str(_evidence(inputs, "provider_ledger")), "PROVIDER_LEDGER")
    ledger_path = guard.file(
        guard.runtime / "runtime/budget/ledger.json", "PERSISTENT_BUDGET_LEDGER"
    )
    budget = _json(budget_path, "BUDGET_REPORT")
    _require_fields_equal(budget, {
        "schema": "nalu.episode_credit_budget_ledger.v1", "episode": episode,
        "status": "PASS",
    }, "BUDGET_REPORT")
    spend = budget.get("spend") or {}
    recorded = spend.get("recorded_total_credits")
    if spend.get("accounting_complete") is not True or budget.get("failures") \
            or not isinstance(recorded, (int, float)) or isinstance(recorded, bool) \
            or recorded < 0 or recorded > budget.get("cap_credits", -1):
        raise ValidationBlocked("BUDGET_REPORT_NOT_FULLY_RECONCILED_WITHIN_CAP")
    provider = _json(provider_path, "PROVIDER_LEDGER")
    closure = _credit_closure.validate(provider, require_actual_credits=True)
    if closure.get("status") != "PASS":
        raise ValidationBlocked("PROVIDER_LEDGER_CLOSURE_FAIL:" + ",".join(closure.get("failures") or []))
    provider_ids = {str(row.get("task_id")) for row in provider.get("tasks") or [] if row.get("task_id")}
    if provider_ids != transaction_task_ids:
        raise ValidationBlocked(
            f"PROVIDER_LEDGER_TASK_SET_MISMATCH:{sorted(provider_ids)}!={sorted(transaction_task_ids)}"
        )
    if provider.get("actual_credits_total") != recorded:
        raise ValidationBlocked("PROVIDER_AND_BUDGET_LEDGER_TOTAL_MISMATCH")
    ledger = _json(ledger_path, "PERSISTENT_BUDGET_LEDGER")
    if ledger.get("schema") != "nalu.episode_credit_budget_ledger_log.v1":
        raise ValidationBlocked("PERSISTENT_BUDGET_LEDGER_SCHEMA_INVALID")
    entries = [row for row in ledger.get("entries") or [] if row.get("episode") == episode]
    if not entries:
        raise ValidationBlocked("PERSISTENT_BUDGET_LEDGER_EPISODE_ENTRY_MISSING")
    latest = entries[-1]
    if latest.get("status") != "PASS" or latest.get("accounting_complete") is not True \
            or latest.get("recorded_total_credits") != recorded:
        raise ValidationBlocked("PERSISTENT_BUDGET_LEDGER_LATEST_ENTRY_MISMATCH")
    return _check(
        budget_path,
        [_binding(budget_path, "budget_reconciliation_report"),
         _binding(provider_path, "provider_credit_ledger"),
         _binding(ledger_path, "persistent_budget_ledger")],
        reconciled=True, recorded_total_credits=recorded,
        provider_task_count=len(provider_ids), accounting_complete=True,
    )


def _validate_final_qa(
    inputs: Mapping[str, Any], guard: PrivatePaths, config: Mapping[str, Any], episode: str,
) -> tuple[dict[str, Any], Path, str]:
    names = (
        "final_audience_request", "final_audience_report", "final_event_ledger",
        "audience_gate", "quality_gate", "final_qa_report",
    )
    paths = {name: guard.file(str(_evidence(inputs, name)), name.upper()) for name in names}
    request = _json(paths["final_audience_request"], "FINAL_AUDIENCE_REQUEST")
    report = _json(paths["final_audience_report"], "FINAL_AUDIENCE_REPORT")
    ledger = _json(paths["final_event_ledger"], "FINAL_EVENT_LEDGER")
    audience = _json(paths["audience_gate"], "AUDIENCE_GATE")
    quality = _json(paths["quality_gate"], "QUALITY_GATE")
    qa = _json(paths["final_qa_report"], "FINAL_QA_REPORT")
    _require_fields_equal(request, {
        "schema": "nalu.final_audience_review_request.v1", "status": "REVIEW_REQUIRED",
        "episode": episode,
    }, "FINAL_AUDIENCE_REQUEST")
    final_video = guard.file(str((request.get("media") or {}).get("path") or ""), "FINAL_VIDEO")
    final_sha = sha256_file(final_video)
    if (request.get("media") or {}).get("sha256") != final_sha:
        raise ValidationBlocked("FINAL_AUDIENCE_REQUEST_MEDIA_SHA_MISMATCH")
    request_evidence = request.get("evidence") or {}
    required_request_evidence = {
        "final_video", "objective_metrics", "contact_sheet", "asr",
        "detector_report", "technical_gate",
    }
    if not required_request_evidence.issubset(request_evidence):
        raise ValidationBlocked("FINAL_AUDIENCE_REQUEST_EVIDENCE_INCOMPLETE")
    request_evidence_bindings: list[dict[str, Any]] = []
    request_evidence_paths: dict[str, Path] = {}
    for name in sorted(required_request_evidence):
        row = request_evidence.get(name) or {}
        evidence_path = guard.file(
            str(row.get("path") or ""), f"FINAL_AUDIENCE_EVIDENCE_{name}"
        )
        if row.get("sha256") != sha256_file(evidence_path):
            raise ValidationBlocked(f"FINAL_AUDIENCE_EVIDENCE_SHA_MISMATCH:{name}")
        request_evidence_paths[name] = evidence_path
        request_evidence_bindings.append(_binding(evidence_path, f"audience_{name}"))
    request_sha = sha256_file(paths["final_audience_request"])
    _require_fields_equal(report, {
        "schema": "nalu.final_audience_score_report.v1", "episode": episode,
        "media_sha256": final_sha, "request_sha256": request_sha, "verdict": "PASS",
        "reviewer_process_separate_from_producer": True,
    }, "FINAL_AUDIENCE_REPORT")
    _require_fields_equal(ledger, {
        "schema": "nalu.final_cut_event_ledger.v1", "episode": episode,
        "media_sha256": final_sha, "request_sha256": request_sha,
    }, "FINAL_EVENT_LEDGER")
    report_sha = sha256_file(paths["final_audience_report"])
    ledger_sha = sha256_file(paths["final_event_ledger"])
    for label, gate in (("AUDIENCE", audience), ("QUALITY", quality)):
        if gate.get("gate_status") != "PASS":
            raise ValidationBlocked(f"FINAL_{label}_GATE_NOT_PASS")
        bindings = gate.get("evidence_bindings") or {}
        expected = {
            "final_video_sha256": final_sha, "request_sha256": request_sha,
            "audience_report_sha256": report_sha, "event_ledger_sha256": ledger_sha,
        }
        for key, value in expected.items():
            if bindings.get(key) != value:
                raise ValidationBlocked(f"FINAL_{label}_GATE_BINDING_MISMATCH:{key}")
    _require_fields_equal(qa, {
        "schema": "nalu.episode_final_qa_report.v1", "episode": episode,
        "final_video_sha256": final_sha, "final_gate_status": "PASS",
    }, "FINAL_QA_REPORT")
    final_audience = qa.get("final_audience_review") or {}
    if final_audience.get("status") != "PASS" or final_audience.get("final_video_sha256") != final_sha:
        raise ValidationBlocked("FINAL_QA_AUDIENCE_BINDING_NOT_PASS")
    qa_video = guard.file(str(qa.get("final_video") or ""), "FINAL_QA_VIDEO")
    if qa_video != final_video:
        raise ValidationBlocked("FINAL_QA_VIDEO_PATH_MISMATCH")
    loudness_path = guard.file(
        str(qa.get("loudness_report") or ""), "FINAL_LOUDNESS_REPORT"
    )
    loudness = _json(loudness_path, "FINAL_LOUDNESS_REPORT")
    if not str(loudness.get("schema") or "").endswith(".native_audio_loudness_qa.v1") \
            or loudness.get("episode") != episode \
            or not str(loudness.get("status") or "").startswith("PASS") \
            or loudness.get("video_stream_bit_exact") is not True \
            or loudness.get("failures") \
            or (loudness.get("output_release") or {}).get("sha256") != final_sha:
        raise ValidationBlocked("FINAL_LOUDNESS_QA_NOT_BOUND_PASS")
    technical = _json(
        request_evidence_paths["technical_gate"], "FINAL_CUT_TECHNICAL_GATE"
    )
    acceptance_bindings: list[dict[str, Any]] = []
    if technical.get("status") != "PASS":
        failing = _gate_acceptance.failing_detectors(technical)
        storage = ((config.get("storyclaw") or {}).get("storage") or {})
        workspace = guard.directory(
            Path(str(storage.get("workspace_backing_path") or "")),
            "FINAL_QA_WORKSPACE",
        )
        acceptance_path = guard.file(
            workspace / episode / "assembly/final_qa"
            / f"{episode}_LINE_OWNER_GATE_ACCEPTANCE.json",
            "FINAL_DETECTOR_ACCEPTANCE",
        )
        acceptance = _json(acceptance_path, "FINAL_DETECTOR_ACCEPTANCE")
        _require_fields_equal(acceptance, {
            "schema": "qingshan.line_owner_gate_acceptance.v2",
            "episode": episode,
            "gate_id": "FINAL-CUT-AUDIENCE-DETECTORS",
            "gate_status_kept": "FAIL",
            "accepted_detectors": sorted(failing),
            "media_sha256": final_sha,
            "media_sha256_bound_by_order": final_sha,
            "self_issued": False,
        }, "FINAL_DETECTOR_ACCEPTANCE")
        orders_path = guard.file(
            str((config.get("authorization") or {}).get("supervisor_orders_path") or ""),
            "FINAL_DETECTOR_SUPERVISOR_ORDERS",
        )
        orders = _json(orders_path, "FINAL_DETECTOR_SUPERVISOR_ORDERS")
        owner = str((config.get("authorization") or {}).get("line_owner_id") or "")
        match = _gate_acceptance.find_acceptance(
            list(orders.get("orders") or []), episode=episode,
            gate_id="FINAL-CUT-AUDIENCE-DETECTORS", failing=failing,
            media_sha256=final_sha, expected_issuer=owner,
            engine_root=Path(str(storage.get("engine_root") or "")),
        )
        if match is None or match.get("seq") != acceptance.get("order_seq") \
                or match.get("id") != acceptance.get("order_id") \
                or match.get("issued_by") != acceptance.get("issued_by") \
                or match.get("order") != acceptance.get("order_verbatim"):
            raise ValidationBlocked("FINAL_DETECTOR_ACCEPTANCE_ORDER_INVALID")
        source = acceptance.get("source_receipt") or {}
        source_path = guard.file(
            str(source.get("path") or ""), "FINAL_DETECTOR_ACCEPTANCE_SOURCE"
        )
        if source.get("sha256") != sha256_file(source_path):
            raise ValidationBlocked("FINAL_DETECTOR_ACCEPTANCE_SOURCE_SHA_MISMATCH")
        acceptance_bindings.extend([
            _binding(acceptance_path, "final_detector_acceptance"),
            _binding(orders_path, "final_detector_supervisor_orders"),
            _binding(source_path, "final_detector_acceptance_source"),
        ])
    bindings = [_binding(path, name) for name, path in paths.items()]
    bindings.extend(request_evidence_bindings)
    bindings.extend(acceptance_bindings)
    bindings.append(_binding(loudness_path, "final_loudness_report"))
    bindings.append(_binding(final_video, "final_video"))
    return _check(
        paths["final_qa_report"], bindings, final_video_sha256=final_sha,
        audience_gate="PASS", quality_gate="PASS", final_gate="PASS",
    ), final_video, final_sha


def _validate_checkpoint(
    inputs: Mapping[str, Any], guard: PrivatePaths, state: Mapping[str, Any],
    config: Mapping[str, Any], episode: str, final_video: Path, final_sha: str,
) -> dict[str, Any]:
    checkpoint = guard.file(str(_evidence(inputs, "checkpoint")), "CHECKPOINT")
    approval_path = guard.file(
        guard.runtime / "runtime/pipeline_state/approvals" / f"{episode}.APPROVED.json",
        "PIPELINE_APPROVAL",
    )
    approval = _json(approval_path, "PIPELINE_APPROVAL")
    _require_fields_equal(approval, {
        "schema": "nalu.pipeline_approval.v1", "episode": episode,
        "checkpoint_sha256": sha256_file(checkpoint),
        "final_video_sha256": final_sha,
    }, "PIPELINE_APPROVAL")
    approved_checkpoint = guard.file(
        str(approval.get("checkpoint") or ""), "PIPELINE_APPROVAL_CHECKPOINT"
    )
    approved_video = guard.file(
        str(approval.get("final_video") or ""), "PIPELINE_APPROVAL_FINAL_VIDEO"
    )
    if approved_checkpoint != checkpoint or approved_video != final_video:
        raise ValidationBlocked("PIPELINE_APPROVAL_ARTIFACT_PATH_MISMATCH")
    owner = str((config.get("authorization") or {}).get("line_owner_id") or "")
    if not owner or approval.get("approved_by") != owner:
        raise ValidationBlocked("PIPELINE_APPROVAL_OWNER_MISMATCH")
    state_approval = state.get("approval") or {}
    if state_approval.get("status") != "APPROVED" or state_approval.get("by") != approval.get("approved_by") \
            or _stage_status(state, "S8") not in TERMINAL_STAGE_STATUSES:
        raise ValidationBlocked("PIPELINE_STATE_APPROVAL_BINDING_MISMATCH")
    text = checkpoint.read_text(encoding="utf-8")
    if f"# {episode} CHECKPOINT" not in text or final_sha not in text:
        raise ValidationBlocked("CHECKPOINT_DOES_NOT_BIND_EPISODE_AND_FINAL_VIDEO")
    return _check(
        checkpoint,
        [_binding(checkpoint, "checkpoint"), _binding(approval_path, "line_owner_approval")],
        approved=True, final_video_sha256=final_sha,
    )


def evaluate_inputs(inputs_path: Path, expected_commit: str | None = None) -> dict[str, Any]:
    """Recompute every release-validation check from live private evidence."""
    inputs_path = inputs_path.expanduser()
    if not inputs_path.is_absolute() or inputs_path.is_symlink():
        raise ValidationBlocked(f"VALIDATION_INPUTS_PATH_INVALID:{inputs_path}")
    raw_inputs = _json(inputs_path, "VALIDATION_INPUTS")
    if raw_inputs.get("schema") != INPUT_SCHEMA:
        raise ValidationBlocked("VALIDATION_INPUT_SCHEMA_INVALID")
    runtime, engine, marker, config, project_id, scope, episode = _context(raw_inputs)
    guard = PrivatePaths(runtime, config)
    canonical_inputs = guard.file(inputs_path, "VALIDATION_INPUTS")
    release_commit = str(raw_inputs["release_commit"]).lower()
    if expected_commit is not None and release_commit != expected_commit:
        raise ValidationBlocked(
            f"VALIDATION_RELEASE_COMMIT_MISMATCH:{release_commit}!={expected_commit}"
        )
    git = _git_acceptance(engine.resolve(strict=True), release_commit)
    install = _validate_install_preflight(
        raw_inputs, guard, release_commit, project_id, scope, engine
    )
    source = _validate_source(guard, project_id, scope)
    s1_s2, state, s2 = _validate_s1_s2(guard, project_id, scope, episode)
    assets = _validate_asset_confirmation(guard, marker, episode, state)
    s5 = _validate_s5_dry(raw_inputs, guard, release_commit, project_id, scope, episode)
    paid_trial, unit_ids = _validate_paid_trial(
        raw_inputs, guard, release_commit, project_id, scope, episode, state, s2
    )
    authority, order = _validate_paid_authority(guard, config, state, episode)
    transactions, task_ids = _validate_transactions(
        guard, config, episode, unit_ids, order
    )
    ledger = _validate_ledger(raw_inputs, guard, episode, task_ids)
    final_qa, final_video, final_sha = _validate_final_qa(
        raw_inputs, guard, config, episode
    )
    checkpoint = _validate_checkpoint(
        raw_inputs, guard, state, config, episode, final_video, final_sha
    )
    checks = {
        "install_preflight": install,
        "source_intake": source,
        "s1_s2": s1_s2,
        "asset_plan_confirmation": assets,
        "s5_dry_run": s5,
        "two_unit_paid_trial": paid_trial,
        "paid_authority": authority,
        "transaction_integrity": transactions,
        "ledger_reconciliation": ledger,
        "final_qa": final_qa,
        "checkpoint": checkpoint,
    }
    if tuple(checks) != VALIDATION_CHECKS:
        raise AssertionError("validation check registry drift")
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "PASS",
        "release_commit": release_commit,
        **git,
        "project_id": project_id,
        "series_scope_id": scope,
        "episode": episode,
        "private_runtime_root": str(runtime.resolve(strict=True)),
        "input_manifest": {
            "path": str(canonical_inputs), "sha256": sha256_file(canonical_inputs),
        },
        "validator": {
            "schema": VALIDATOR_SCHEMA,
            "tool": str(Path(__file__).resolve()),
            "tool_sha256": sha256_file(Path(__file__).resolve()),
            "mode": "LIVE_PRIVATE_EVIDENCE_RECOMPUTED",
            "provider_posts": 0,
            "credentials_read": False,
        },
        "checks": checks,
        "private_validation_contents_included_in_public_release": False,
    }


def build_receipt(inputs_path: Path, out: Path) -> dict[str, Any]:
    result = evaluate_inputs(inputs_path)
    runtime = Path(result["private_runtime_root"])
    config = _json(runtime / "qingshan.json", "PROJECT_CONFIG")
    guard = PrivatePaths(runtime, config)
    output = out.expanduser()
    if not output.is_absolute():
        raise ValidationBlocked("VALIDATION_RECEIPT_OUTPUT_NOT_ABSOLUTE")
    if output.exists() and output.is_symlink():
        raise ValidationBlocked("VALIDATION_RECEIPT_OUTPUT_SYMLINK_REFUSED")
    parent = output.parent.resolve(strict=True)
    if not _inside(parent, guard.runtime):
        raise ValidationBlocked("VALIDATION_RECEIPT_OUTPUT_OUTSIDE_PRIVATE_RUNTIME")
    result["generated_at_utc"] = _now()
    _atomic_json(output, result)
    return {**result, "receipt_path": str(output.resolve()), "receipt_sha256": sha256_file(output)}


def verify_receipt(path: Path, expected_commit: str) -> dict[str, Any]:
    """Fail closed unless the receipt still matches all live private evidence."""
    receipt_path = path.expanduser()
    if not receipt_path.is_absolute() or receipt_path.is_symlink():
        raise ValidationBlocked(f"VALIDATION_RECEIPT_PATH_INVALID:{receipt_path}")
    receipt = _json(receipt_path, "VALIDATION_RECEIPT")
    _require_fields_equal(receipt, {
        "schema": RECEIPT_SCHEMA, "status": "PASS",
        "release_commit": expected_commit, "remote_engine_commit": expected_commit,
        "remote_worktree_clean": True, "remote_diff_sha256": EMPTY_SHA256,
        "private_validation_contents_included_in_public_release": False,
    }, "VALIDATION_RECEIPT")
    runtime_raw = Path(str(receipt.get("private_runtime_root") or "")).expanduser()
    if not runtime_raw.is_absolute() or runtime_raw.is_symlink() or not runtime_raw.is_dir():
        raise ValidationBlocked(f"PRIVATE_RUNTIME_ROOT_INVALID:{runtime_raw}")
    runtime = runtime_raw.resolve(strict=True)
    config = _json(runtime / "qingshan.json", "PROJECT_CONFIG")
    guard = PrivatePaths(runtime, config)
    canonical_receipt = guard.file(receipt_path, "VALIDATION_RECEIPT")
    input_binding = receipt.get("input_manifest") or {}
    input_path = guard.file(
        Path(str(input_binding.get("path") or "")), "VALIDATION_INPUT_MANIFEST"
    )
    recomputed = evaluate_inputs(input_path, expected_commit=expected_commit)
    if input_binding.get("sha256") != sha256_file(input_path):
        raise ValidationBlocked("VALIDATION_INPUT_MANIFEST_SHA_MISMATCH")
    for field in (
        "project_id", "series_scope_id", "episode", "private_runtime_root",
        "input_manifest", "validator", "checks",
    ):
        if receipt.get(field) != recomputed.get(field):
            raise ValidationBlocked(f"VALIDATION_RECEIPT_RECOMPUTED_FIELD_MISMATCH:{field}")
    return {
        "schema": RECEIPT_SCHEMA,
        "status": "PASS",
        "sha256": sha256_file(canonical_receipt),
        "release_commit": expected_commit,
        "remote_engine_commit": expected_commit,
        "remote_worktree_clean": True,
        "remote_diff_sha256": EMPTY_SHA256,
        "checks": {name: "PASS" for name in VALIDATION_CHECKS},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--inputs", required=True, type=Path)
    build.add_argument("--out", required=True, type=Path)
    verify = sub.add_parser("verify")
    verify.add_argument("--receipt", required=True, type=Path)
    verify.add_argument("--expected-commit", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build_receipt(args.inputs, args.out)
        else:
            result = verify_receipt(args.receipt, args.expected_commit)
    except ValidationBlocked as exc:
        print(json.dumps({
            "schema": VALIDATOR_SCHEMA, "status": "BLOCKED", "failure": str(exc),
            "provider_posts": 0, "credentials_read": False,
        }, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
