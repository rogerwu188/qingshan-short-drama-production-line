#!/usr/bin/env python3
"""Build and re-verify a clean TalentHub registry-install smoke receipt.

This verifier is deliberately independent from the release builder and host
installer.  It examines the bytes delivered by the TalentHub registry and the
private receipts produced by a *new* StoryClaw project.  A successful result
proves that the registry package, immutable engine archive, future engine
link, private storage mounts, offline dependency environment, and unpaid
preflight all describe the same release.

The detailed receipt is private because it contains host paths and project
identifiers.  Successful CLI output is a hash-only summary suitable for a
public release record.  No production stage and no provider request is run by
this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote, urlsplit


SCHEMA = "storyclaw.nalu.registry_clean_install_smoke.v1"
SNAPSHOT_SCHEMA = "storyclaw.nalu.transactions_snapshot.v1"
TALENTHUB_SCHEMA = "qingshan.storyclaw.talenthub.release.v1"
STABLE_INDEX_SCHEMA = "storyclaw.nalu.stable_index.v1"
BOOTSTRAP_SCHEMA = "storyclaw.nalu.skill_bootstrap.v1"
INSTALL_SCHEMA = "storyclaw.nalu.host_install_receipt.v1"
PREFLIGHT_SCHEMA = "storyclaw.nalu.preflight.v1"
CURRENT_RELEASE_SCHEMA = "storyclaw.nalu.current_release.v1"
AGENT_ID = "ai-drama-factory"
SKILL_NAME = "qingshan-nalu"
REPOSITORY = "https://github.com/rogerwu188/qingshan-short-drama-production-line"
SIGNING_KEY_SHA256 = "d27484512874011dc5e894b602d6a42ca846a4e048688d32389acf7852d3646f"
NESTED_MANIFEST = "skills/qingshan-nalu/RELEASE_MANIFEST.json"
SMOKE_RECEIPT_ROOT = Path("runtime/receipts/storyclaw_registry_clean_install_smoke")
SMOKE_PREFLIGHT_RELATIVE = SMOKE_RECEIPT_ROOT / "preflight.json"
BOOTSTRAP_RECEIPT_RELATIVE = Path("runtime/receipts/storyclaw_bootstrap/bootstrap.json")
INSTALL_RECEIPT_ROOT_RELATIVE = Path("runtime/receipts/storyclaw_host_install")
CURRENT_RELEASE_RELATIVE = Path("runtime/storyclaw_host/current-release.json")
VENV_SELECTOR_RELATIVE = Path("runtime/storyclaw_host/current-venv")
MAX_REGISTRY_PACKAGE = 50 * 1024 * 1024
MAX_ZIP_EXPANDED = 64 * 1024 * 1024
MAX_ZIP_MEMBER = 16 * 1024 * 1024
MAX_ZIP_MEMBERS = 2048
SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40,64}\Z")
TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,199}\Z")

BOUND_AGENT_FILES = frozenset({
    "IDENTITY.md",
    "USER.md",
    "SOUL.md",
    "AGENTS.md",
    "HEARTBEAT.md",
    "skills/qingshan-nalu/SKILL.md",
    "skills/qingshan-nalu/bootstrap_storyclaw.py",
})
PROVIDER_SECRET_NAMES = frozenset({
    "GIGGLE_API_KEY",
    "GIGGLEPRO_API_KEY",
    "GIGGLE_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "MINIMAX_API_KEY",
    "ELEVENLABS_API_KEY",
    "FAL_KEY",
})
FORBIDDEN_PACKAGE_BASENAMES = frozenset({
    ".env", "credentials.json", "secrets.json", "SUPERVISOR_ORDERS.json",
})


class SmokeBlocked(RuntimeError):
    """The clean-install evidence is incomplete, inconsistent, or unsafe."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}:{detail}" if detail else code)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) + "\n").encode("utf-8")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _normalized_leaf(path: Path) -> Path:
    """Canonicalize platform aliases in a parent without following the leaf."""
    try:
        return path.parent.resolve(strict=True) / path.name
    except OSError as exc:
        raise SmokeBlocked("PATH_PARENT_INVALID") from exc


def _root(path: Path | str, code: str) -> Path:
    raw = Path(path).expanduser()
    if not raw.is_absolute() or raw.is_symlink():
        raise SmokeBlocked(code)
    try:
        resolved = raw.resolve(strict=True)
    except OSError as exc:
        raise SmokeBlocked(code) from exc
    if not resolved.is_dir():
        raise SmokeBlocked(code)
    return resolved


def _contained(
    path: Path | str,
    root: Path,
    code: str,
    *,
    kind: str,
    allow_leaf_symlink: bool = False,
) -> Path:
    """Resolve one path while refusing every unapproved in-root symlink."""
    raw = Path(path).expanduser()
    if not raw.is_absolute():
        raise SmokeBlocked(code)
    absolute = raw.absolute()
    try:
        relative = absolute.relative_to(root)
    except ValueError as exc:
        # Accommodate only a platform-level alias above the trusted root (for
        # example macOS /var -> /private/var).  A symlink below the root is
        # still caught by the component walk when lexical containment works.
        prospective = absolute.resolve(strict=False)
        try:
            relative = prospective.relative_to(root)
            absolute = prospective
        except ValueError as nested:
            raise SmokeBlocked(code) from nested
    cursor = root
    parts = relative.parts
    for index, part in enumerate(parts):
        cursor = cursor / part
        is_leaf = index == len(parts) - 1
        if cursor.is_symlink() and not (is_leaf and allow_leaf_symlink):
            raise SmokeBlocked(code)
    try:
        resolved = absolute.resolve(strict=True)
    except OSError as exc:
        raise SmokeBlocked(code) from exc
    if not _inside(resolved, root):
        raise SmokeBlocked(code)
    if kind == "file" and (not resolved.is_file() or (raw.is_symlink() and not allow_leaf_symlink)):
        raise SmokeBlocked(code)
    if kind == "dir" and (not resolved.is_dir() or (raw.is_symlink() and not allow_leaf_symlink)):
        raise SmokeBlocked(code)
    if kind == "symlink" and (not raw.is_symlink() or not resolved.exists()):
        raise SmokeBlocked(code)
    return resolved


def _ensure_private_directory(path: Path, runtime: Path) -> Path:
    try:
        relative = path.absolute().relative_to(runtime)
    except ValueError as exc:
        raise SmokeBlocked("PRIVATE_OUTPUT_PATH_INVALID") from exc
    cursor = runtime
    for part in relative.parts:
        cursor = cursor / part
        if os.path.lexists(cursor):
            if cursor.is_symlink() or not cursor.is_dir():
                raise SmokeBlocked("PRIVATE_OUTPUT_PATH_INVALID")
        else:
            cursor.mkdir(mode=0o700)
    return cursor.resolve(strict=True)


def _json_file(path: Path, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeBlocked(code) from exc
    if not isinstance(payload, dict):
        raise SmokeBlocked(code)
    return payload


def _binding(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _require_exact(payload: Mapping[str, Any], expected: Mapping[str, Any], code: str) -> None:
    failures = [key for key, value in expected.items() if payload.get(key) != value]
    if failures:
        raise SmokeBlocked(code, ",".join(failures[:12]))


def _require_sha(value: Any, code: str) -> str:
    digest = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(digest):
        raise SmokeBlocked(code)
    return digest


def _require_positive(value: Any, code: str, maximum: int | None = None) -> int:
    if type(value) is not int or value <= 0 or (maximum is not None and value > maximum):
        raise SmokeBlocked(code)
    return value


def _safe_zip_name(name: str) -> str:
    if "\\" in name:
        raise SmokeBlocked("REGISTRY_PACKAGE_PATH_INVALID")
    pure = PurePosixPath(name.rstrip("/"))
    if (
        not name
        or pure.is_absolute()
        or ".." in pure.parts
        or any(part in {"", "."} for part in pure.parts)
    ):
        raise SmokeBlocked("REGISTRY_PACKAGE_PATH_INVALID")
    return pure.as_posix()


def _registry_package(path: Path, url: str) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    parsed = urlsplit(str(url or "").strip())
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or (host != "storyclaw.com" and not host.endswith(".storyclaw.com"))
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
        or not parsed.path
    ):
        raise SmokeBlocked("REGISTRY_PACKAGE_URL_INVALID")
    size = path.stat().st_size
    if size <= 0 or size > MAX_REGISTRY_PACKAGE:
        raise SmokeBlocked("REGISTRY_PACKAGE_SIZE_INVALID")
    rows: dict[str, bytes] = {}
    expanded = 0
    try:
        with zipfile.ZipFile(path) as package:
            infos = package.infolist()
            if len(infos) > MAX_ZIP_MEMBERS:
                raise SmokeBlocked("REGISTRY_PACKAGE_MEMBER_LIMIT")
            for info in infos:
                name = _safe_zip_name(info.filename)
                if name in rows:
                    raise SmokeBlocked("REGISTRY_PACKAGE_DUPLICATE_MEMBER")
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    raise SmokeBlocked("REGISTRY_PACKAGE_SYMLINK_REFUSED")
                if info.is_dir():
                    continue
                if (
                    info.file_size <= 0
                    or info.file_size > MAX_ZIP_MEMBER
                    or info.compress_size < 0
                    or info.compress_size > MAX_ZIP_MEMBER
                ):
                    raise SmokeBlocked("REGISTRY_PACKAGE_MEMBER_SIZE_INVALID")
                expanded += info.file_size
                if expanded > MAX_ZIP_EXPANDED:
                    raise SmokeBlocked("REGISTRY_PACKAGE_EXPANDED_SIZE_INVALID")
                if PurePosixPath(name).name in FORBIDDEN_PACKAGE_BASENAMES:
                    raise SmokeBlocked("REGISTRY_PACKAGE_PRIVATE_FILE_REFUSED")
                rows[name] = package.read(info)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SmokeBlocked("REGISTRY_PACKAGE_INVALID") from exc
    manifest_bytes = rows.get(NESTED_MANIFEST)
    if manifest_bytes is None:
        raise SmokeBlocked("REGISTRY_NESTED_MANIFEST_MISSING")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SmokeBlocked("REGISTRY_NESTED_MANIFEST_INVALID") from exc
    if not isinstance(manifest, dict):
        raise SmokeBlocked("REGISTRY_NESTED_MANIFEST_INVALID")
    bindings = manifest.get("installed_file_bindings")
    if not isinstance(bindings, dict) or set(bindings) != BOUND_AGENT_FILES:
        raise SmokeBlocked("REGISTRY_INSTALLED_BINDINGS_INVALID")
    for relative in sorted(BOUND_AGENT_FILES):
        row = bindings.get(relative)
        body = rows.get(relative)
        if (
            not isinstance(row, dict)
            or body is None
            or type(row.get("size_bytes")) is not int
            or row["size_bytes"] != len(body)
            or _require_sha(row.get("sha256"), "REGISTRY_INSTALLED_BINDING_INVALID")
            != _sha_bytes(body)
        ):
            raise SmokeBlocked("REGISTRY_INSTALLED_BINDING_INVALID", relative)
    return ({
        "path": str(path),
        "url": url,
        "url_sha256": _sha_bytes(url.encode("utf-8")),
        "size_bytes": size,
        "sha256": sha256_file(path),
        "entry_count": len(rows),
        "expanded_size_bytes": expanded,
    }, manifest, manifest_bytes)


def _validate_release_identity(
    index: Mapping[str, Any], manifest: Mapping[str, Any], *, index_sha: str
) -> tuple[str, str, int, str, int]:
    if index.get("schema") != STABLE_INDEX_SCHEMA:
        raise SmokeBlocked("STABLE_INDEX_SCHEMA_INVALID")
    tag = str(index.get("release_tag") or "")
    commit = str(index.get("git_commit") or "").lower()
    sequence = index.get("release_sequence")
    if not TAG_RE.fullmatch(tag) or not COMMIT_RE.fullmatch(commit):
        raise SmokeBlocked("STABLE_INDEX_IDENTITY_INVALID")
    _require_positive(sequence, "STABLE_INDEX_SEQUENCE_INVALID")
    archive_size = _require_positive(
        index.get("source_archive_size_bytes"), "STABLE_INDEX_ARCHIVE_SIZE_INVALID",
        512 * 1024 * 1024,
    )
    archive_sha = _require_sha(
        index.get("source_archive_sha256"), "STABLE_INDEX_ARCHIVE_SHA_INVALID"
    )
    _require_exact(index, {
        "channel": "stable",
        "validation_receipt_status": "PASS",
        "signing_key_sha256": SIGNING_KEY_SHA256,
    }, "STABLE_INDEX_TRUST_FIELDS_INVALID")
    expected_archive_url = (
        f"{REPOSITORY}/releases/download/{quote(tag)}/"
        f"qingshan-storyclaw-workflow-{quote(tag)}.tar.gz"
    )
    if index.get("source_archive_url") != expected_archive_url:
        raise SmokeBlocked("STABLE_INDEX_ARCHIVE_URL_INVALID")
    exact = {
        "schema": TALENTHUB_SCHEMA,
        "agent_id": AGENT_ID,
        "skill": SKILL_NAME,
        "release_tag": tag,
        "release_sequence": sequence,
        "git_commit": commit,
        "origin_tag_commit": commit,
        "source_archive_github_release_url": expected_archive_url,
        "source_archive_size_bytes": archive_size,
        "source_archive_sha256": archive_sha,
        "release_channel_sha256": index.get("release_channel_sha256"),
        "release_channel_update_class": index.get("update_class"),
        "stable_index_sha256": index_sha,
        "release_signing_key_sha256": SIGNING_KEY_SHA256,
        "validation_receipt_status": "PASS",
        "validation_receipt_sha256": index.get("validation_receipt_sha256"),
        "public_runtime_only": True,
        "private_validation_contents_included": False,
    }
    _require_exact(manifest, exact, "REGISTRY_MANIFEST_RELEASE_BINDING_MISMATCH")
    _require_sha(index.get("release_channel_sha256"), "STABLE_INDEX_CHANNEL_SHA_INVALID")
    _require_sha(index.get("validation_receipt_sha256"), "STABLE_INDEX_VALIDATION_SHA_INVALID")
    return tag, commit, int(sequence), archive_sha, archive_size


def _verify_stable_index_signature(
    index_path: Path, signature_path: Path, public_key_path: Path
) -> dict[str, Any]:
    if public_key_path.is_symlink() or signature_path.is_symlink():
        raise SmokeBlocked("STABLE_INDEX_SIGNATURE_PATH_INVALID")
    key_sha = sha256_file(public_key_path)
    if key_sha != SIGNING_KEY_SHA256:
        raise SmokeBlocked("RELEASE_PUBLIC_KEY_SHA256_MISMATCH")
    signature_size = signature_path.stat().st_size
    if signature_size <= 0 or signature_size > 16 * 1024:
        raise SmokeBlocked("STABLE_INDEX_SIGNATURE_SIZE_INVALID")
    try:
        result = subprocess.run(
            [
                "openssl", "pkeyutl", "-verify", "-pubin", "-inkey",
                str(public_key_path), "-rawin", "-in", str(index_path),
                "-sigfile", str(signature_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise SmokeBlocked("STABLE_INDEX_SIGNATURE_VERIFIER_UNAVAILABLE") from exc
    if result.returncode != 0:
        raise SmokeBlocked("STABLE_INDEX_SIGNATURE_INVALID")
    return {
        "signature": _binding(signature_path),
        "public_key": _binding(public_key_path),
        "verification": "PASS",
    }


def _secret_key_present(value: Any) -> bool:
    provider_names = {name.lower() for name in PROVIDER_SECRET_NAMES}
    def populated(candidate: Any) -> bool:
        return candidate is not None and candidate is not False and candidate != ""
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower()
            if normalized in provider_names and populated(nested):
                return True
            if normalized in {"api_key", "token", "password", "secret"} \
                    and populated(nested):
                return True
            if _secret_key_present(nested):
                return True
    elif isinstance(value, list):
        return any(_secret_key_present(item) for item in value)
    return False


def _tree_snapshot(root: Path) -> dict[str, Any]:
    if root.is_symlink() or not root.is_dir():
        raise SmokeBlocked("TRANSACTIONS_BACKING_INVALID")
    rows: list[dict[str, Any]] = []
    stack = [root]
    total = 0
    file_count = 0
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda row: row.name)
        except OSError as exc:
            raise SmokeBlocked("TRANSACTIONS_BACKING_UNREADABLE") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise SmokeBlocked("TRANSACTIONS_ENTRY_INVALID") from exc
            if entry.is_symlink():
                raise SmokeBlocked("TRANSACTIONS_SYMLINK_REFUSED")
            if entry.is_dir(follow_symlinks=False):
                rows.append({"path": relative, "type": "directory"})
                stack.append(path)
            elif entry.is_file(follow_symlinks=False):
                digest = sha256_file(path)
                rows.append({
                    "path": relative,
                    "type": "file",
                    "size_bytes": metadata.st_size,
                    "sha256": digest,
                })
                total += metadata.st_size
                file_count += 1
            else:
                raise SmokeBlocked("TRANSACTIONS_SPECIAL_ENTRY_REFUSED")
    rows.sort(key=lambda row: row["path"])
    return {
        "entry_count": len(rows),
        "file_count": file_count,
        "total_size_bytes": total,
        "tree_sha256": _sha_bytes(_canonical_json(rows)),
    }


def _receipt_inventory(root: Path, runtime: Path) -> list[dict[str, Any]]:
    if not os.path.lexists(root):
        return []
    directory = _contained(root, runtime, "INSTALL_RECEIPT_ROOT_INVALID", kind="dir")
    rows: list[dict[str, Any]] = []
    for entry in sorted(directory.iterdir(), key=lambda path: path.name):
        if entry.is_symlink() or not entry.is_file() or entry.suffix != ".json":
            raise SmokeBlocked("INSTALL_RECEIPT_ROOT_ENTRY_INVALID")
        rows.append(_binding(entry))
    return rows


def _phase_evidence(runtime: Path, config: Mapping[str, Any], label: str) -> dict[str, Any]:
    storage = ((config.get("storyclaw") or {}).get("storage") or {})
    engine_link = Path(str(storage.get("engine_root") or ""))
    if not engine_link.is_absolute() or _inside(engine_link.resolve(strict=False), runtime):
        raise SmokeBlocked("SNAPSHOT_ENGINE_LINK_INVALID")
    bootstrap_path = runtime / BOOTSTRAP_RECEIPT_RELATIVE
    preflight_path = runtime / SMOKE_PREFLIGHT_RELATIVE
    baseline_path = runtime / CURRENT_RELEASE_RELATIVE
    selector_path = runtime / VENV_SELECTOR_RELATIVE
    install_rows = _receipt_inventory(
        runtime / INSTALL_RECEIPT_ROOT_RELATIVE, runtime
    )
    if label == "before":
        if (
            os.path.lexists(engine_link)
            or os.path.lexists(bootstrap_path)
            or os.path.lexists(preflight_path)
            or os.path.lexists(baseline_path)
            or os.path.lexists(selector_path)
            or install_rows
        ):
            raise SmokeBlocked("BEFORE_SNAPSHOT_NOT_BEFORE_INSTALL")
        return {
            "engine_link_present": False,
            "bootstrap_receipt_present": False,
            "preflight_receipt_present": False,
            "current_release_present": False,
            "venv_selector_present": False,
            "install_receipt_count": 0,
        }
    if label not in {"after", "after_current"}:
        raise SmokeBlocked("TRANSACTIONS_SNAPSHOT_LABEL_INVALID")
    if not engine_link.is_symlink():
        raise SmokeBlocked("AFTER_SNAPSHOT_ENGINE_LINK_MISSING")
    bootstrap = _contained(
        bootstrap_path, runtime, "AFTER_SNAPSHOT_BOOTSTRAP_RECEIPT_MISSING", kind="file"
    )
    preflight = _contained(
        preflight_path, runtime, "AFTER_SNAPSHOT_PREFLIGHT_RECEIPT_MISSING", kind="file"
    )
    baseline = _contained(
        baseline_path, runtime, "AFTER_SNAPSHOT_BASELINE_MISSING", kind="file"
    )
    selector = _contained(
        selector_path, runtime, "AFTER_SNAPSHOT_VENV_SELECTOR_MISSING",
        kind="symlink", allow_leaf_symlink=True,
    )
    del selector
    if not install_rows:
        raise SmokeBlocked("AFTER_SNAPSHOT_INSTALL_RECEIPT_MISSING")
    bootstrap_payload = _json_file(
        bootstrap, "AFTER_SNAPSHOT_BOOTSTRAP_RECEIPT_INVALID"
    )
    expected_bootstrap_status = (
        "PREFLIGHT_PASS_PENDING_SNAPSHOT" if label == "after" else "PASS"
    )
    if (
        bootstrap_payload.get("schema") != BOOTSTRAP_SCHEMA
        or bootstrap_payload.get("status") != expected_bootstrap_status
    ):
        raise SmokeBlocked("AFTER_SNAPSHOT_BOOTSTRAP_RECEIPT_INVALID")
    preflight_payload = _json_file(
        preflight, "AFTER_SNAPSHOT_PREFLIGHT_RECEIPT_INVALID"
    )
    if (
        preflight_payload.get("schema") != PREFLIGHT_SCHEMA
        or preflight_payload.get("status") != "PASS"
    ):
        raise SmokeBlocked("AFTER_SNAPSHOT_PREFLIGHT_RECEIPT_INVALID")
    return {
        "engine_link_present": True,
        "engine_link_target_sha256": _sha_bytes(
            str(engine_link.resolve(strict=True)).encode("utf-8")
        ),
        "bootstrap_receipt_present": True,
        "bootstrap_receipt_sha256": sha256_file(bootstrap),
        "preflight_receipt_present": True,
        "preflight_receipt_sha256": sha256_file(preflight),
        "current_release_present": True,
        "current_release_sha256": sha256_file(baseline),
        "venv_selector_present": True,
        "venv_selector_target_sha256": _sha_bytes(
            str(selector_path.resolve(strict=True)).encode("utf-8")
        ),
        "install_receipt_count": len(install_rows),
        "install_receipts": install_rows,
    }


def _runtime_config(runtime: Path) -> tuple[Path, dict[str, Any], Path]:
    config_path = _contained(runtime / "qingshan.json", runtime, "CONFIG_PATH_INVALID", kind="file")
    config = _json_file(config_path, "CONFIG_INVALID")
    storage = ((config.get("storyclaw") or {}).get("storage") or {})
    backing_text = str(storage.get("transactions_backing_path") or "")
    if not backing_text:
        raise SmokeBlocked("TRANSACTIONS_BACKING_NOT_CONFIGURED")
    backing = _contained(backing_text, runtime, "TRANSACTIONS_BACKING_INVALID", kind="dir")
    return config_path, config, backing


def snapshot_transactions(
    runtime_root: Path,
    output: Path,
    *,
    label: str,
    prior_snapshot: Path | None = None,
) -> dict[str, Any]:
    """Write a private, hash-bound observation of the real transaction backing."""
    if label not in {"before", "after"}:
        raise SmokeBlocked("TRANSACTIONS_SNAPSHOT_LABEL_INVALID")
    runtime = _root(runtime_root, "RUNTIME_ROOT_INVALID")
    _config_path, config, backing = _runtime_config(runtime)
    expected_root = runtime / SMOKE_RECEIPT_ROOT
    if output.parent.resolve(strict=False) != expected_root.resolve(strict=False) \
            or output.name in {"", ".", ".."}:
        raise SmokeBlocked("SNAPSHOT_OUTPUT_PATH_INVALID")
    output_parent = _ensure_private_directory(expected_root, runtime)
    if output_parent != expected_root.resolve(strict=True):
        raise SmokeBlocked("SNAPSHOT_OUTPUT_PATH_INVALID")
    output = output_parent / output.name
    if os.path.lexists(output):
        raise SmokeBlocked("SNAPSHOT_OUTPUT_ALREADY_EXISTS")
    facts = _tree_snapshot(backing)
    present_secrets = sorted(
        name for name in PROVIDER_SECRET_NAMES if bool(os.environ.get(name))
    )
    if present_secrets:
        raise SmokeBlocked("PROVIDER_SECRETS_PRESENT_DURING_SNAPSHOT")
    if label == "before" and prior_snapshot is not None:
        raise SmokeBlocked("BEFORE_SNAPSHOT_MUST_NOT_HAVE_PRIOR")
    prior_binding: dict[str, Any] | None = None
    if label == "after":
        if prior_snapshot is None:
            raise SmokeBlocked("AFTER_SNAPSHOT_REQUIRES_PRIOR")
        prior_path = _contained(
            prior_snapshot, runtime, "PRIOR_SNAPSHOT_PATH_INVALID", kind="file"
        )
        prior_payload = _json_file(prior_path, "PRIOR_SNAPSHOT_INVALID")
        if prior_payload.get("schema") != SNAPSHOT_SCHEMA \
                or prior_payload.get("status") != "PASS" \
                or prior_payload.get("label") != "before":
            raise SmokeBlocked("PRIOR_SNAPSHOT_INVALID")
        prior_binding = _binding(prior_path)
    payload = {
        "schema": SNAPSHOT_SCHEMA,
        "status": "PASS",
        "label": label,
        "observation_sequence": 1 if label == "before" else 2,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="microseconds"
        ).replace("+00:00", "Z"),
        "private_runtime_root": str(runtime),
        "transactions_backing": str(backing),
        **facts,
        "provider_posts": 0,
        "provider_secret_names_present": present_secrets,
        "phase": _phase_evidence(runtime, config, label),
    }
    if prior_binding is not None:
        payload["prior_snapshot_sha256"] = prior_binding["sha256"]
    _atomic_json(output, payload, runtime)
    return {
        "schema": SCHEMA,
        "status": "PASS",
        "snapshot_sha256": sha256_file(output),
        "transactions_tree_sha256": facts["tree_sha256"],
    }


def _load_snapshot(path: Path, runtime: Path, backing: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    safe = _contained(path, runtime, "TRANSACTIONS_SNAPSHOT_PATH_INVALID", kind="file")
    payload = _json_file(safe, "TRANSACTIONS_SNAPSHOT_INVALID")
    _require_exact(payload, {
        "schema": SNAPSHOT_SCHEMA,
        "status": "PASS",
        "label": label,
        "observation_sequence": 1 if label == "before" else 2,
        "private_runtime_root": str(runtime),
        "transactions_backing": str(backing),
        "provider_posts": 0,
        "provider_secret_names_present": [],
    }, "TRANSACTIONS_SNAPSHOT_BINDING_MISMATCH")
    for field in ("entry_count", "file_count", "total_size_bytes"):
        if type(payload.get(field)) is not int or payload[field] < 0:
            raise SmokeBlocked("TRANSACTIONS_SNAPSHOT_COUNTS_INVALID")
    _require_sha(payload.get("tree_sha256"), "TRANSACTIONS_SNAPSHOT_DIGEST_INVALID")
    observed = str(payload.get("observed_at_utc") or "")
    try:
        datetime.fromisoformat(observed.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SmokeBlocked("TRANSACTIONS_SNAPSHOT_TIME_INVALID") from exc
    if not isinstance(payload.get("phase"), dict):
        raise SmokeBlocked("TRANSACTIONS_SNAPSHOT_PHASE_INVALID")
    return payload, _binding(safe)


def _atomic_json(path: Path, payload: Mapping[str, Any], runtime: Path) -> None:
    if not path.is_absolute() or not _inside(path.parent.resolve(strict=True), runtime):
        raise SmokeBlocked("PRIVATE_OUTPUT_PATH_INVALID")
    if os.path.lexists(path):
        raise SmokeBlocked("PRIVATE_OUTPUT_ALREADY_EXISTS")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json.dumps(
                payload, ensure_ascii=False, indent=2, sort_keys=True
            ).encode("utf-8") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _wiring_row(install: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    rows = install.get("wiring")
    if not isinstance(rows, list):
        raise SmokeBlocked("INSTALL_WIRING_INVALID")
    matches = [row for row in rows if isinstance(row, dict) and row.get("name") == name]
    if len(matches) != 1:
        raise SmokeBlocked("INSTALL_WIRING_INVALID", name)
    return matches[0]


def _verify_mount(
    *,
    name: str,
    configured_target: Path,
    configured_backing: Path,
    actual_target: Path,
    runtime: Path,
    project_home: Path,
    install: Mapping[str, Any],
) -> dict[str, Any]:
    backing = _contained(configured_backing, runtime, f"{name.upper()}_BACKING_INVALID", kind="dir")
    target_parent = _contained(
        actual_target.parent, project_home, f"{name.upper()}_TARGET_INVALID", kind="dir"
    )
    del target_parent
    target = _contained(
        actual_target, project_home, f"{name.upper()}_TARGET_INVALID",
        kind="symlink", allow_leaf_symlink=True,
    )
    if target != backing or configured_target.resolve(strict=True) != backing:
        raise SmokeBlocked(f"{name.upper()}_TARGET_BACKING_MISMATCH")
    try:
        if not os.path.samefile(actual_target, backing) or not os.path.samefile(configured_target, backing):
            raise SmokeBlocked(f"{name.upper()}_TARGET_BACKING_MISMATCH")
    except OSError as exc:
        raise SmokeBlocked(f"{name.upper()}_TARGET_BACKING_MISMATCH") from exc
    row = _wiring_row(install, name)
    probe = row.get("storage_probe") or {}
    row_target = Path(str(row.get("target") or ""))
    try:
        normalized_row_target = _normalized_leaf(row_target)
        normalized_actual_target = _normalized_leaf(actual_target)
    except SmokeBlocked as exc:
        raise SmokeBlocked("INSTALL_WIRING_RECEIPT_MISMATCH", name) from exc
    if (
        normalized_row_target != normalized_actual_target
        or Path(str(row.get("backing") or "")).resolve(strict=True) != backing
        or row.get("state") != "EXACT_SYMLINK"
        or row.get("same_storage_object") is not True
        or any(probe.get(key) != "PASS" for key in ("write", "fsync", "flock_nonblocking"))
    ):
        raise SmokeBlocked("INSTALL_WIRING_RECEIPT_MISMATCH", name)
    return {"target": str(configured_target), "backing": str(backing)}


def _verify_engine_seal(engine: Path, workspace_link: Path, transactions_link: Path) -> dict[str, Any]:
    allowed_links = {workspace_link, transactions_link}
    writable = 0
    entry_count = 0
    for root_text, directory_names, filenames in os.walk(engine, followlinks=False):
        root = Path(root_text)
        for name in [*directory_names, *filenames]:
            path = root / name
            entry_count += 1
            if path.is_symlink():
                if path not in allowed_links:
                    raise SmokeBlocked("ENGINE_UNEXPECTED_SYMLINK")
                continue
            try:
                mode = stat.S_IMODE(path.stat().st_mode)
            except OSError as exc:
                raise SmokeBlocked("ENGINE_SEAL_RECHECK_FAILED") from exc
            if mode & 0o222:
                writable += 1
    if stat.S_IMODE(engine.stat().st_mode) & 0o222:
        writable += 1
    if writable:
        raise SmokeBlocked("ENGINE_SEAL_RECHECK_FAILED")
    return {"status": "PASS", "entry_count": entry_count, "writable_path_count": 0}


def _evaluate(inputs: Mapping[str, Any]) -> dict[str, Any]:
    runtime = _root(str(inputs.get("runtime_root") or ""), "RUNTIME_ROOT_INVALID")
    project_home = _root(str(inputs.get("project_home") or ""), "PROJECT_HOME_INVALID")
    installed_root = _root(str(inputs.get("installed_agent_root") or ""), "INSTALLED_AGENT_ROOT_INVALID")
    artifact_root = _root(str(inputs.get("artifact_root") or ""), "ARTIFACT_ROOT_INVALID")
    if not _inside(runtime, project_home):
        raise SmokeBlocked("RUNTIME_NOT_IN_PROJECT_HOME")

    registry_path = _contained(
        str(inputs.get("registry_package") or ""), artifact_root,
        "REGISTRY_PACKAGE_PATH_INVALID", kind="file",
    )
    registry, manifest, manifest_bytes = _registry_package(
        registry_path, str(inputs.get("registry_package_url") or "")
    )
    index_path = _contained(
        str(inputs.get("stable_index") or ""), artifact_root,
        "STABLE_INDEX_PATH_INVALID", kind="file",
    )
    index = _json_file(index_path, "STABLE_INDEX_INVALID")
    index_binding = _binding(index_path)
    signature_path = _contained(
        str(inputs.get("stable_index_signature") or ""), artifact_root,
        "STABLE_INDEX_SIGNATURE_PATH_INVALID", kind="file",
    )
    public_key_path = _contained(
        str(inputs.get("release_public_key") or ""), project_home,
        "RELEASE_PUBLIC_KEY_PATH_INVALID", kind="file",
    )
    signature_binding = _verify_stable_index_signature(
        index_path, signature_path, public_key_path
    )
    tag, commit, sequence, archive_sha, archive_size = _validate_release_identity(
        index, manifest, index_sha=index_binding["sha256"]
    )

    archive_path = _contained(
        str(inputs.get("source_archive") or ""), project_home,
        "SOURCE_ARCHIVE_PATH_INVALID", kind="file",
    )
    if archive_path.stat().st_size != archive_size or sha256_file(archive_path) != archive_sha:
        raise SmokeBlocked("SOURCE_ARCHIVE_BYTES_MISMATCH")
    archive_binding = _binding(archive_path)

    installed_manifest_path = _contained(
        installed_root / NESTED_MANIFEST, installed_root,
        "INSTALLED_NESTED_MANIFEST_PATH_INVALID", kind="file",
    )
    if installed_manifest_path.read_bytes() != manifest_bytes:
        raise SmokeBlocked("INSTALLED_NESTED_MANIFEST_BYTES_MISMATCH")
    for relative in sorted(BOUND_AGENT_FILES):
        target = _contained(
            installed_root / relative, installed_root,
            "INSTALLED_AGENT_BOUND_FILE_INVALID", kind="file",
        )
        row = manifest["installed_file_bindings"][relative]
        if target.stat().st_size != row["size_bytes"] or sha256_file(target) != row["sha256"]:
            raise SmokeBlocked("INSTALLED_AGENT_BOUND_FILE_MISMATCH", relative)
    nested_binding = _binding(installed_manifest_path)

    receipt_paths: dict[str, Path] = {}
    receipts: dict[str, dict[str, Any]] = {}
    for key, schema in (
        ("bootstrap_receipt", BOOTSTRAP_SCHEMA),
        ("install_receipt", INSTALL_SCHEMA),
        ("preflight_receipt", PREFLIGHT_SCHEMA),
    ):
        path = _contained(
            str(inputs.get(key) or ""), runtime,
            f"{key.upper()}_PATH_INVALID", kind="file",
        )
        payload = _json_file(path, f"{key.upper()}_INVALID")
        if payload.get("schema") != schema or payload.get("status") != "PASS":
            raise SmokeBlocked(f"{key.upper()}_STATUS_INVALID")
        receipt_paths[key] = path
        receipts[key] = payload
    if receipt_paths["bootstrap_receipt"] != (
        runtime / BOOTSTRAP_RECEIPT_RELATIVE
    ).resolve(strict=True):
        raise SmokeBlocked("BOOTSTRAP_RECEIPT_PATH_NOT_CANONICAL")
    if receipt_paths["preflight_receipt"] != (
        runtime / SMOKE_PREFLIGHT_RELATIVE
    ).resolve(strict=True):
        raise SmokeBlocked("PREFLIGHT_RECEIPT_PATH_NOT_CANONICAL")
    if receipt_paths["install_receipt"].parent != (
        runtime / INSTALL_RECEIPT_ROOT_RELATIVE
    ).resolve(strict=True):
        raise SmokeBlocked("INSTALL_RECEIPT_PATH_NOT_CANONICAL")

    bootstrap = receipts["bootstrap_receipt"]
    install = receipts["install_receipt"]
    preflight = receipts["preflight_receipt"]
    if _secret_key_present(bootstrap) or _secret_key_present(install) or _secret_key_present(preflight):
        raise SmokeBlocked("PROVIDER_SECRET_RECORDED")

    marker_path = _contained(
        runtime / "runtime/project.json", runtime, "PROJECT_MARKER_PATH_INVALID", kind="file"
    )
    hidden_marker_path = _contained(
        runtime / ".qingshan-private-runtime.json", runtime,
        "PROJECT_HIDDEN_MARKER_PATH_INVALID", kind="file",
    )
    marker = _json_file(marker_path, "PROJECT_MARKER_INVALID")
    hidden_marker = _json_file(hidden_marker_path, "PROJECT_HIDDEN_MARKER_INVALID")
    if marker != hidden_marker or marker.get("status") != "INITIALIZED_PRIVATE":
        raise SmokeBlocked("PROJECT_MARKER_MISMATCH")
    config_path, config, transaction_backing = _runtime_config(runtime)
    if _secret_key_present(marker) or _secret_key_present(config):
        raise SmokeBlocked("PROVIDER_SECRET_RECORDED")
    project_id = str(marker.get("project_id") or "")
    scope_id = str(marker.get("series_scope_id") or "")
    if not project_id or not scope_id or marker.get("private_runtime_root") != str(runtime):
        raise SmokeBlocked("PROJECT_MARKER_IDENTITY_INVALID")

    future_link_text = str(marker.get("engine_root") or "")
    configured_engine = str((((config.get("storyclaw") or {}).get("storage") or {}).get("engine_root") or ""))
    if not future_link_text or configured_engine != future_link_text:
        raise SmokeBlocked("FUTURE_ENGINE_LINK_CONFIG_MISMATCH")
    future_link_raw = Path(future_link_text)
    future_engine = _contained(
        future_link_raw, project_home, "FUTURE_ENGINE_LINK_INVALID",
        kind="symlink", allow_leaf_symlink=True,
    )
    engine = future_engine
    if _inside(engine, runtime):
        raise SmokeBlocked("ENGINE_VIEW_OVERLAPS_RUNTIME")
    expected_public_key = engine / "configs/storyclaw_release_signing_public_key.pem"
    try:
        expected_public_key_resolved = expected_public_key.resolve(strict=True)
    except OSError as exc:
        raise SmokeBlocked("RELEASE_PUBLIC_KEY_ENGINE_BINDING_MISMATCH") from exc
    if public_key_path != expected_public_key_resolved:
        raise SmokeBlocked("RELEASE_PUBLIC_KEY_ENGINE_BINDING_MISMATCH")

    _require_exact(bootstrap, {
        "release_tag": tag,
        "git_commit": commit,
        "release_sequence": sequence,
        "source_archive": str(archive_path),
        "source_archive_size_bytes": archive_size,
        "source_archive_sha256": archive_sha,
        "talenthub_release_manifest": str(installed_manifest_path),
        "private_runtime_root": str(runtime),
        "project_engine_link": str(future_link_raw),
        "project_engine": str(engine),
        "provider_posts": 0,
    }, "BOOTSTRAP_RECEIPT_BINDING_MISMATCH")

    if install.get("isolation_mode") != "PER_PROJECT_VERIFIED_ARCHIVE_VIEW":
        raise SmokeBlocked("INSTALL_ISOLATION_MODE_INVALID")
    engine_facts = install.get("engine") or {}
    base_facts = install.get("base_engine") or {}
    project_view = install.get("project_view") or {}
    engine_link = install.get("project_engine_link") or {}
    _require_exact(engine_facts, {
        "root": str(engine), "head_commit": commit,
        "checkout_kind": "PACKAGE_VERIFIED_RELEASE_ARCHIVE",
        "immutable_tree_verified": True,
        "source_archive_sha256": archive_sha,
    }, "INSTALL_ENGINE_BINDING_MISMATCH")
    _require_exact(base_facts, {
        "root": str(engine), "head_commit": commit,
        "checkout_kind": "PACKAGE_VERIFIED_RELEASE_ARCHIVE",
        "immutable_tree_verified": True,
        "source_archive_sha256": archive_sha,
    }, "INSTALL_BASE_ENGINE_BINDING_MISMATCH")
    _require_exact(project_view, {
        "base_engine_root": str(engine), "engine_root": str(engine), "commit": commit,
    }, "INSTALL_PROJECT_VIEW_BINDING_MISMATCH")
    if (
        Path(str(engine_link.get("path") or "")) != future_link_raw
        or Path(str(engine_link.get("target") or "")).resolve(strict=True) != engine
    ):
        raise SmokeBlocked("INSTALL_PROJECT_ENGINE_LINK_MISMATCH")
    _require_exact(install.get("runtime") or {}, {"root": str(runtime)}, "INSTALL_RUNTIME_MISMATCH")
    verification = install.get("verification") or {}
    _require_exact(verification, {
        "status": "PASS", "tag": tag, "commit": commit, "storage_probe": "PASS",
    }, "INSTALL_VERIFICATION_INVALID")
    if install.get("secret_values_recorded") is not False \
            or install.get("source_or_media_paths_touched") != []:
        raise SmokeBlocked("INSTALL_CLEAN_BOUNDARY_INVALID")

    storage = ((config.get("storyclaw") or {}).get("storage") or {})
    if storage.get("mode") != "READ_ONLY_ENGINE_WITH_PRIVATE_WRITABLE_MOUNTS":
        raise SmokeBlocked("STORAGE_MODE_INVALID")
    expected_workspace_target = future_link_raw / "workflow/nalu"
    expected_transactions_target = future_link_raw / "workflow/tasks"
    workspace_backing = _contained(
        str(storage.get("workspace_backing_path") or ""), runtime,
        "WORKSPACE_BACKING_INVALID", kind="dir",
    )
    if Path(str(storage.get("workspace_mount_target") or "")) != expected_workspace_target \
            or Path(str(storage.get("transactions_mount_target") or "")) != expected_transactions_target:
        raise SmokeBlocked("CONFIGURED_MOUNT_TARGET_INVALID")
    workspace_actual = engine / "workflow/nalu"
    transactions_actual = engine / "workflow/tasks"
    workspace_binding = _verify_mount(
        name="episode_workspace", configured_target=expected_workspace_target,
        configured_backing=workspace_backing, actual_target=workspace_actual,
        runtime=runtime, project_home=project_home, install=install,
    )
    transaction_binding = _verify_mount(
        name="transaction_store", configured_target=expected_transactions_target,
        configured_backing=transaction_backing, actual_target=transactions_actual,
        runtime=runtime, project_home=project_home, install=install,
    )
    if workspace_backing == transaction_backing:
        raise SmokeBlocked("PRIVATE_STORAGE_BACKINGS_NOT_DISTINCT")

    seal = install.get("engine_seal") or {}
    if seal.get("sealed") is not True or seal.get("writable_path_count") != 0:
        raise SmokeBlocked("INSTALL_ENGINE_SEAL_INVALID")
    seal_recheck = _verify_engine_seal(engine, workspace_actual, transactions_actual)

    baseline = install.get("release_baseline") or {}
    if baseline.get("status") != "PASS" or baseline.get("action") not in {"BOUND", "ALREADY_BOUND"}:
        raise SmokeBlocked("INSTALL_RELEASE_BASELINE_INVALID")
    baseline_path = _contained(
        runtime / CURRENT_RELEASE_RELATIVE, runtime,
        "CURRENT_RELEASE_BASELINE_PATH_INVALID", kind="file",
    )
    if Path(str(baseline.get("path") or "")).resolve(strict=True) != baseline_path:
        raise SmokeBlocked("INSTALL_RELEASE_BASELINE_PATH_MISMATCH")
    current_release = _json_file(baseline_path, "CURRENT_RELEASE_BASELINE_INVALID")
    baseline_exact = {
        "schema": CURRENT_RELEASE_SCHEMA,
        "status": "PASS",
        "release_sequence": sequence,
        "release_tag": tag,
        "git_commit": commit,
        "signing_key_sha256": SIGNING_KEY_SHA256,
        "talenthub_release_manifest_sha256": nested_binding["sha256"],
        "validation_receipt_sha256": manifest.get("validation_receipt_sha256"),
    }
    _require_exact(current_release, baseline_exact, "CURRENT_RELEASE_BASELINE_MISMATCH")
    _require_exact(baseline, {
        key: value for key, value in baseline_exact.items() if key != "schema"
    }, "INSTALL_RELEASE_BASELINE_BINDING_MISMATCH")

    dependencies = install.get("dependencies") or {}
    profile_id = str(dependencies.get("dependency_profile") or "")
    profile_rows = manifest.get("dependency_profiles")
    if not isinstance(profile_rows, list):
        raise SmokeBlocked("REGISTRY_DEPENDENCY_PROFILES_INVALID")
    matches = [row for row in profile_rows if isinstance(row, dict) and row.get("profile_id") == profile_id]
    if len(matches) != 1:
        raise SmokeBlocked("INSTALL_DEPENDENCY_PROFILE_NOT_RELEASE_BOUND")
    profile = matches[0]
    for prefix in ("manifest", "archive"):
        _require_positive(profile.get(f"{prefix}_size_bytes"), "REGISTRY_DEPENDENCY_PROFILE_INVALID")
        _require_sha(profile.get(f"{prefix}_sha256"), "REGISTRY_DEPENDENCY_PROFILE_INVALID")
    _require_exact(dependencies, {
        "requested": True,
        "status": "INSTALLED",
        "network_used": False,
        "dependency_profile": profile_id,
        "bundle_manifest_sha256": profile.get("manifest_sha256"),
        "bundle_archive_sha256": profile.get("archive_sha256"),
        "pip_check": "PASS",
    }, "INSTALL_DEPENDENCY_RECEIPT_INVALID")
    for field in ("lock_sha256", "installed_inventory_sha256"):
        _require_sha(dependencies.get(field), "INSTALL_DEPENDENCY_RECEIPT_INVALID")
    _require_positive(dependencies.get("installed_package_count"), "INSTALL_DEPENDENCY_RECEIPT_INVALID")
    interpreter = dependencies.get("interpreter_facts") or {}
    if interpreter.get("schema") != "storyclaw.nalu.dependency_profile.v1":
        raise SmokeBlocked("INSTALL_DEPENDENCY_INTERPRETER_INVALID")

    selector = install.get("venv_selector") or {}
    selector_path = runtime / VENV_SELECTOR_RELATIVE
    recorded_selector_path = Path(str(selector.get("path") or ""))
    if _normalized_leaf(recorded_selector_path) != _normalized_leaf(selector_path):
        raise SmokeBlocked("VENV_SELECTOR_RECEIPT_MISMATCH")
    selected_venv = _contained(
        selector_path, runtime, "VENV_SELECTOR_INVALID", kind="symlink", allow_leaf_symlink=True
    )
    dependency_venv = _contained(
        str(dependencies.get("venv") or ""), runtime, "DEPENDENCY_VENV_INVALID", kind="dir"
    )
    if selected_venv != dependency_venv or selector.get("status") != "PASS" \
            or Path(str(selector.get("target") or "")).resolve(strict=True) != dependency_venv:
        raise SmokeBlocked("VENV_SELECTOR_RECEIPT_MISMATCH")
    selector_python = selector_path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    try:
        resolved_python = selector_python.resolve(strict=True)
    except OSError as exc:
        raise SmokeBlocked("VENV_SELECTOR_PYTHON_INVALID") from exc
    if not resolved_python.is_file() or not _inside(resolved_python, dependency_venv):
        raise SmokeBlocked("VENV_SELECTOR_PYTHON_INVALID")
    recorded_selector_python = recorded_selector_path / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    if (
        Path(str(selector.get("python") or "")) != recorded_selector_python
        or Path(str(selector.get("resolved_python") or "")).resolve(strict=True) != resolved_python
        or Path(str(dependencies.get("stable_python") or "")) != recorded_selector_python
    ):
        raise SmokeBlocked("VENV_SELECTOR_PYTHON_RECEIPT_MISMATCH")

    _require_exact(preflight, {
        "engine_commit": commit,
        "engine_root": str(engine),
        "private_runtime_root": str(runtime),
        "project_id": project_id,
        "series_scope_id": scope_id,
    }, "PREFLIGHT_CONTEXT_MISMATCH")
    checks = preflight.get("checks")
    if not isinstance(checks, dict) or not checks:
        raise SmokeBlocked("PREFLIGHT_CHECKS_INVALID")
    for name, row in checks.items():
        if not isinstance(row, dict) or row.get("status") != "PASS":
            raise SmokeBlocked("PREFLIGHT_CHECK_NOT_PASS", str(name))
    required_checks = {
        "engine_root", "nalu_pipeline", "nalu_paths", "runtime_persistent",
        "storage_contract", "engine_code_read_only", "workspace_store",
        "transaction_store", "writer_layers_store", "portable_media",
        "portable_audio_provider", "portable_renderer",
        "stable_release_signature_verifier", "model", "policy_profile",
        "series_scope", "voice_registry", "paid_lock",
    }
    if not required_checks.issubset(checks):
        raise SmokeBlocked("PREFLIGHT_REQUIRED_CHECK_MISSING")
    paid_lock = checks["paid_lock"]
    if paid_lock.get("paid_requests_enabled") is not False \
            or paid_lock.get("api_key_present") is not False:
        raise SmokeBlocked("PREFLIGHT_PROVIDER_ACCESS_NOT_DISABLED")
    for name, target, backing in (
        ("workspace_store", workspace_actual, workspace_backing),
        ("transaction_store", transactions_actual, transaction_backing),
    ):
        row = checks[name]
        if (
            Path(str(row.get("mount_target") or "")).resolve(strict=True) != backing
            or Path(str(row.get("backing_path") or "")).resolve(strict=True) != backing
            or row.get("same_storage_object") is not True
            or row.get("private_runtime_backing") is not True
            or row.get("writable") is not True
            or row.get("flock") is not True
        ):
            raise SmokeBlocked("PREFLIGHT_STORAGE_BINDING_MISMATCH", name)

    generation = config.get("generation") or {}
    storyclaw = config.get("storyclaw") or {}
    authorization = config.get("authorization") or {}
    if (
        marker.get("paid_requests_enabled") is not False
        or generation.get("paid_requests_enabled") is not False
        or storyclaw.get("paid_requests_enabled") not in {None, False}
        or authorization.get("paid_order_seq") not in {None, 0}
        or authorization.get("status") not in {None, "NOT_AUTHORIZED"}
    ):
        raise SmokeBlocked("PROJECT_PAID_ACCESS_NOT_DISABLED")

    before, before_binding = _load_snapshot(
        Path(str(inputs.get("transactions_before_snapshot") or "")),
        runtime, transaction_backing, "before",
    )
    after, after_binding = _load_snapshot(
        Path(str(inputs.get("transactions_after_snapshot") or "")),
        runtime, transaction_backing, "after",
    )
    expected_before_phase = {
        "engine_link_present": False,
        "bootstrap_receipt_present": False,
        "preflight_receipt_present": False,
        "current_release_present": False,
        "venv_selector_present": False,
        "install_receipt_count": 0,
    }
    if before.get("phase") != expected_before_phase:
        raise SmokeBlocked("BEFORE_SNAPSHOT_PHASE_INVALID")
    if after.get("prior_snapshot_sha256") != before_binding["sha256"]:
        raise SmokeBlocked("AFTER_SNAPSHOT_PRIOR_BINDING_INVALID")
    try:
        before_time = datetime.fromisoformat(
            str(before["observed_at_utc"]).replace("Z", "+00:00")
        )
        after_time = datetime.fromisoformat(
            str(after["observed_at_utc"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError) as exc:
        raise SmokeBlocked("TRANSACTIONS_SNAPSHOT_TIME_INVALID") from exc
    if after_time <= before_time:
        raise SmokeBlocked("TRANSACTIONS_SNAPSHOT_ORDER_INVALID")
    current_after_phase = _phase_evidence(runtime, config, "after_current")
    after_phase = after["phase"]
    stable_phase_fields = {
        "engine_link_present",
        "engine_link_target_sha256",
        "preflight_receipt_present",
        "preflight_receipt_sha256",
        "current_release_present",
        "current_release_sha256",
        "venv_selector_present",
        "venv_selector_target_sha256",
        "install_receipt_count",
        "install_receipts",
    }
    if any(
        after_phase.get(field) != current_after_phase.get(field)
        for field in stable_phase_fields
    ):
        raise SmokeBlocked("AFTER_SNAPSHOT_PHASE_INVALID")
    if (
        bootstrap.get("snapshot_bound_bootstrap_receipt_sha256")
        != after_phase.get("bootstrap_receipt_sha256")
        or bootstrap.get("transactions_before_snapshot")
        != str(before_binding["path"])
        or bootstrap.get("transactions_before_snapshot_sha256")
        != before_binding["sha256"]
        or bootstrap.get("transactions_after_snapshot")
        != str(after_binding["path"])
        or bootstrap.get("transactions_after_snapshot_sha256")
        != after_binding["sha256"]
        or bootstrap.get("preflight_receipt")
        != str(receipt_paths["preflight_receipt"])
        or bootstrap.get("preflight_receipt_sha256")
        != sha256_file(receipt_paths["preflight_receipt"])
        or after_phase.get("preflight_receipt_sha256")
        != sha256_file(receipt_paths["preflight_receipt"])
        or not any(
            isinstance(row, dict)
            and row.get("sha256") == sha256_file(receipt_paths["install_receipt"])
            for row in (after_phase.get("install_receipts") or [])
        )
    ):
        raise SmokeBlocked("AFTER_SNAPSHOT_RECEIPT_BINDING_INVALID")
    for field in ("entry_count", "file_count", "total_size_bytes", "tree_sha256"):
        if before.get(field) != after.get(field):
            raise SmokeBlocked("TRANSACTIONS_CHANGED_DURING_SMOKE", field)
    current_transactions = _tree_snapshot(transaction_backing)
    if any(current_transactions[key] != after.get(key) for key in current_transactions):
        raise SmokeBlocked("TRANSACTIONS_CHANGED_AFTER_SMOKE")

    receipt_bindings = {
        key: _binding(path) for key, path in receipt_paths.items()
    }
    controls = {
        "isolation_mode": "PER_PROJECT_VERIFIED_ARCHIVE_VIEW",
        "engine_seal": "PASS",
        "release_baseline": "PASS",
        "dependency_profile": "PASS",
        "venv_selector": "PASS",
        "provider_secrets_absent": True,
        "paid_requests_enabled": False,
        "provider_posts": 0,
        "transactions_unchanged": True,
    }
    return {
        "release": {"tag": tag, "commit": commit, "sequence": sequence},
        "registry_package": registry,
        "nested_manifest": {
            **nested_binding,
            "zip_entry": NESTED_MANIFEST,
        },
        "stable_index": index_binding,
        "stable_index_signature": signature_binding,
        "source_archive": archive_binding,
        "private_project": {
            "project_home": str(project_home),
            "runtime_root": str(runtime),
            "installed_agent_root": str(installed_root),
            "project_id": project_id,
            "series_scope_id": scope_id,
            "engine_link": str(future_link_raw),
            "engine_view": str(engine),
        },
        "private_files": {
            "marker": _binding(marker_path),
            "hidden_marker": _binding(hidden_marker_path),
            "config": _binding(config_path),
            "current_release": _binding(baseline_path),
        },
        "receipts": receipt_bindings,
        "storage": {
            "workspace": workspace_binding,
            "transactions": transaction_binding,
        },
        "engine_seal_recheck": seal_recheck,
        "dependency": {
            "profile_id": profile_id,
            "bundle_manifest_sha256": dependencies["bundle_manifest_sha256"],
            "bundle_archive_sha256": dependencies["bundle_archive_sha256"],
            "lock_sha256": dependencies["lock_sha256"],
            "installed_inventory_sha256": dependencies["installed_inventory_sha256"],
            "venv": str(dependency_venv),
            "selector": str(selector_path),
            "python_sha256": sha256_file(resolved_python),
        },
        "transactions": {
            "backing": str(transaction_backing),
            "before_snapshot": before_binding,
            "after_snapshot": after_binding,
            **current_transactions,
        },
        "controls": controls,
    }


def _normalized_inputs(**values: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values.items():
        result[key] = str(Path(value).expanduser().absolute()) if key != "registry_package_url" else str(value)
    return result


def _public_summary(receipt_path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    facts = payload["facts"]
    hashes = {
        "receipt_sha256": sha256_file(receipt_path),
        "facts_sha256": _sha_bytes(_canonical_json(facts)),
        "release_identity_sha256": _sha_bytes(_canonical_json(facts["release"])),
        "registry_package_sha256": facts["registry_package"]["sha256"],
        "registry_package_url_sha256": facts["registry_package"]["url_sha256"],
        "nested_manifest_sha256": facts["nested_manifest"]["sha256"],
        "stable_index_sha256": facts["stable_index"]["sha256"],
        "stable_index_signature_sha256": facts["stable_index_signature"]["signature"]["sha256"],
        "release_public_key_sha256": facts["stable_index_signature"]["public_key"]["sha256"],
        "source_archive_sha256": facts["source_archive"]["sha256"],
        "bootstrap_receipt_sha256": facts["receipts"]["bootstrap_receipt"]["sha256"],
        "install_receipt_sha256": facts["receipts"]["install_receipt"]["sha256"],
        "preflight_receipt_sha256": facts["receipts"]["preflight_receipt"]["sha256"],
        "transactions_before_snapshot_sha256": facts["transactions"]["before_snapshot"]["sha256"],
        "transactions_after_snapshot_sha256": facts["transactions"]["after_snapshot"]["sha256"],
        "transactions_tree_sha256": facts["transactions"]["tree_sha256"],
        "controls_sha256": _sha_bytes(_canonical_json(facts["controls"])),
        "dependency_profile_sha256": _sha_bytes(
            str(facts["dependency"]["profile_id"]).encode("utf-8")
        ),
        "dependency_bundle_manifest_sha256": facts["dependency"]["bundle_manifest_sha256"],
        "dependency_bundle_archive_sha256": facts["dependency"]["bundle_archive_sha256"],
    }
    if any(not SHA_RE.fullmatch(str(value)) for value in hashes.values()):
        raise SmokeBlocked("PUBLIC_SUMMARY_HASH_INVALID")
    return {"schema": SCHEMA, "status": "PASS", "hashes": hashes}


def build_receipt(
    *,
    runtime_root: Path,
    project_home: Path,
    installed_agent_root: Path,
    artifact_root: Path,
    registry_package: Path,
    registry_package_url: str,
    stable_index: Path,
    stable_index_signature: Path,
    release_public_key: Path,
    source_archive: Path,
    bootstrap_receipt: Path,
    install_receipt: Path,
    preflight_receipt: Path,
    transactions_before_snapshot: Path,
    transactions_after_snapshot: Path,
    output: Path,
) -> dict[str, Any]:
    inputs = _normalized_inputs(
        runtime_root=runtime_root,
        project_home=project_home,
        installed_agent_root=installed_agent_root,
        artifact_root=artifact_root,
        registry_package=registry_package,
        registry_package_url=registry_package_url,
        stable_index=stable_index,
        stable_index_signature=stable_index_signature,
        release_public_key=release_public_key,
        source_archive=source_archive,
        bootstrap_receipt=bootstrap_receipt,
        install_receipt=install_receipt,
        preflight_receipt=preflight_receipt,
        transactions_before_snapshot=transactions_before_snapshot,
        transactions_after_snapshot=transactions_after_snapshot,
    )
    facts = _evaluate(inputs)
    runtime = _root(inputs["runtime_root"], "RUNTIME_ROOT_INVALID")
    expected_root = runtime / SMOKE_RECEIPT_ROOT
    if output.parent.resolve(strict=False) != expected_root.resolve(strict=False) \
            or output.name in {"", ".", ".."}:
        raise SmokeBlocked("SMOKE_OUTPUT_PATH_INVALID")
    output_parent = _ensure_private_directory(expected_root, runtime)
    if output_parent != expected_root.resolve(strict=True):
        raise SmokeBlocked("SMOKE_OUTPUT_PATH_INVALID")
    output = output_parent / output.name
    payload = {"schema": SCHEMA, "status": "PASS", "inputs": inputs, "facts": facts}
    _atomic_json(output, payload, runtime)
    return verify_receipt(output)


def verify_receipt(receipt_path: Path) -> dict[str, Any]:
    raw = Path(receipt_path).expanduser()
    if not raw.is_absolute() or raw.is_symlink():
        raise SmokeBlocked("SMOKE_RECEIPT_PATH_INVALID")
    try:
        initial = _json_file(raw.resolve(strict=True), "SMOKE_RECEIPT_INVALID")
    except OSError as exc:
        raise SmokeBlocked("SMOKE_RECEIPT_INVALID") from exc
    if initial.get("schema") != SCHEMA or initial.get("status") != "PASS" \
            or not isinstance(initial.get("inputs"), dict) \
            or not isinstance(initial.get("facts"), dict):
        raise SmokeBlocked("SMOKE_RECEIPT_SCHEMA_INVALID")
    runtime = _root(str(initial["inputs"].get("runtime_root") or ""), "RUNTIME_ROOT_INVALID")
    safe = _contained(raw, runtime, "SMOKE_RECEIPT_PATH_INVALID", kind="file")
    expected_parent = (runtime / SMOKE_RECEIPT_ROOT).resolve(strict=True)
    if safe.parent != expected_parent:
        raise SmokeBlocked("SMOKE_RECEIPT_PATH_INVALID")
    actual = _evaluate(initial["inputs"])
    if actual != initial["facts"]:
        raise SmokeBlocked("SMOKE_RECEIPT_RECOMPUTED_FACTS_MISMATCH")
    return _public_summary(safe, initial)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("--runtime-root", type=Path, required=True)
    snapshot.add_argument("--label", choices=("before", "after"), required=True)
    snapshot.add_argument("--prior-snapshot", type=Path)
    snapshot.add_argument("--output", type=Path, required=True)
    build = sub.add_parser("build")
    build.add_argument("--runtime-root", type=Path, required=True)
    build.add_argument("--project-home", type=Path, required=True)
    build.add_argument("--installed-agent-root", type=Path, required=True)
    build.add_argument("--artifact-root", type=Path, required=True)
    build.add_argument("--registry-package", type=Path, required=True)
    build.add_argument("--registry-package-url", required=True)
    build.add_argument("--stable-index", type=Path, required=True)
    build.add_argument("--stable-index-signature", type=Path, required=True)
    build.add_argument("--release-public-key", type=Path, required=True)
    build.add_argument("--source-archive", type=Path, required=True)
    build.add_argument("--bootstrap-receipt", type=Path, required=True)
    build.add_argument("--install-receipt", type=Path, required=True)
    build.add_argument("--preflight-receipt", type=Path, required=True)
    build.add_argument("--transactions-before-snapshot", type=Path, required=True)
    build.add_argument("--transactions-after-snapshot", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("receipt", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "snapshot":
            result = snapshot_transactions(
                args.runtime_root, args.output, label=args.label,
                prior_snapshot=args.prior_snapshot,
            )
        elif args.command == "verify":
            result = verify_receipt(args.receipt)
        else:
            result = build_receipt(
                runtime_root=args.runtime_root,
                project_home=args.project_home,
                installed_agent_root=args.installed_agent_root,
                artifact_root=args.artifact_root,
                registry_package=args.registry_package,
                registry_package_url=args.registry_package_url,
                stable_index=args.stable_index,
                stable_index_signature=args.stable_index_signature,
                release_public_key=args.release_public_key,
                source_archive=args.source_archive,
                bootstrap_receipt=args.bootstrap_receipt,
                install_receipt=args.install_receipt,
                preflight_receipt=args.preflight_receipt,
                transactions_before_snapshot=args.transactions_before_snapshot,
                transactions_after_snapshot=args.transactions_after_snapshot,
                output=args.output,
            )
    except SmokeBlocked as exc:
        # Do not print private paths or receipt contents on the public-facing
        # command surface.  The stable code is enough to diagnose in private.
        print(json.dumps({"schema": SCHEMA, "status": "BLOCKED", "code": exc.code}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
