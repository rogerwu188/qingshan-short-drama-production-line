#!/usr/bin/env python3
"""Discover the next validated NALU stable release from a signed index.

The stable URL is intentionally mutable, but the bytes served there are not
trusted on their own.  The installed engine pins an Ed25519 public-key digest,
verifies the detached signature over the exact index bytes, and then verifies
the immutable tag-specific channel manifest named by that index.  No branch,
``latest`` tag, or unsigned GitHub API response becomes release authority.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

try:
    from tools import storyclaw_dependency_bundle as _dependency_bundle
except ModuleNotFoundError:  # direct ``python tools/...`` execution
    import storyclaw_dependency_bundle as _dependency_bundle  # type: ignore[no-redef]


SCHEMA = "storyclaw.nalu.stable_index.v1"
RESULT_SCHEMA = "storyclaw.nalu.release_discovery.v1"
ERROR_SCHEMA = "storyclaw.nalu.release_discovery_error.v1"
CHANNEL_SCHEMA = "storyclaw.nalu.release_channel.v1"
TALENTHUB_RELEASE_SCHEMA = "qingshan.storyclaw.talenthub.release.v1"
AGENT_ID = "ai-drama-factory"
SKILL_NAME = "qingshan-nalu"
GITHUB_REPO = "https://github.com/rogerwu188/qingshan-short-drama-production-line"
STABLE_CHANNEL_RELEASE_TAG = "storyclaw-stable-channel"
STABLE_INDEX_URL = (
    f"{GITHUB_REPO}/releases/download/{STABLE_CHANNEL_RELEASE_TAG}/"
    "qingshan-storyclaw-stable-index.json"
)
STABLE_SIGNATURE_URL = STABLE_INDEX_URL + ".sig"
TRUSTED_PUBLIC_KEY_RELATIVE = Path("configs/storyclaw_release_signing_public_key.pem")
TRUSTED_PUBLIC_KEY_SHA256 = "d27484512874011dc5e894b602d6a42ca846a4e048688d32389acf7852d3646f"
SIGNING_PROBE_RELATIVE = Path("configs/storyclaw_release_signing_probe.txt")
SIGNING_PROBE_SIGNATURE_RELATIVE = Path("configs/storyclaw_release_signing_probe.txt.sig")
SIGNING_PROBE_SHA256 = "1d129175c2cf04e1fb5e5d944532e3c7d20865cae3928b0a2c84e27b283cd5a1"
SIGNING_PROBE_SIGNATURE_SHA256 = "727a646aaa46b87fb5e404b9d7c675b1beece7758bf9a750c4c3057f79a96af3"
DISCOVERY_ROOT_RELATIVE = Path("runtime/storyclaw_release_discovery")
DISCOVERY_STATE_RELATIVE = DISCOVERY_ROOT_RELATIVE / "trusted_state.json"
DISCOVERY_LOCK_RELATIVE = DISCOVERY_ROOT_RELATIVE / "discovery.lock"
CURRENT_RELEASE_STATE_RELATIVE = Path("runtime/storyclaw_host/current-release.json")
CURRENT_RELEASE_STATE_SCHEMA = "storyclaw.nalu.current_release.v1"

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40,64}\Z")
_SAFE_TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,199}\Z")
_ALLOWED_UPDATE_CLASSES = {
    "ENGINE_ONLY",
    "TALENTHUB_PACKAGE_REQUIRED",
    "RUNTIME_MIGRATION_REQUIRED",
}
_ALLOWED_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}


class DiscoveryBlocked(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}:{detail}" if detail else code)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _safe_tag(value: Any) -> str:
    tag = str(value or "").strip()
    if not _SAFE_TAG_RE.fullmatch(tag) or tag.lower() in {
        "main", "master", "head", "latest", "stable",
    }:
        raise DiscoveryBlocked("STABLE_INDEX_TAG_INVALID", tag)
    return tag


def _require_sha(value: Any, code: str) -> str:
    digest = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(digest):
        raise DiscoveryBlocked(code, digest)
    return digest


def _require_positive_int(value: Any, code: str) -> int:
    if type(value) is not int or value <= 0:
        raise DiscoveryBlocked(code, str(value))
    return value


def _expected_asset_url(tag: str, filename: str) -> str:
    return (
        f"{GITHUB_REPO}/releases/download/"
        f"{urllib.parse.quote(tag)}/{urllib.parse.quote(filename)}"
    )


def _validate_asset_url(value: Any, expected: str, code: str) -> str:
    url = str(value or "").strip()
    if url != expected:
        raise DiscoveryBlocked(code, url)
    return url


def validate_index(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise DiscoveryBlocked("STABLE_INDEX_SCHEMA_INVALID", str(getattr(payload, "get", lambda _x: None)("schema")))
    if payload.get("channel") != "stable":
        raise DiscoveryBlocked("STABLE_INDEX_CHANNEL_INVALID", str(payload.get("channel")))
    if payload.get("validation_receipt_status") != "PASS":
        raise DiscoveryBlocked("STABLE_INDEX_NOT_VALIDATED")
    if payload.get("signing_key_sha256") != TRUSTED_PUBLIC_KEY_SHA256:
        raise DiscoveryBlocked("STABLE_INDEX_SIGNING_KEY_MISMATCH")
    sequence = _require_positive_int(payload.get("release_sequence"), "STABLE_INDEX_SEQUENCE_INVALID")
    tag = _safe_tag(payload.get("release_tag"))
    commit = str(payload.get("git_commit") or "").strip().lower()
    if not _COMMIT_RE.fullmatch(commit):
        raise DiscoveryBlocked("STABLE_INDEX_COMMIT_INVALID", commit)
    update_class = str(payload.get("update_class") or "")
    if update_class not in _ALLOWED_UPDATE_CLASSES:
        raise DiscoveryBlocked("STABLE_INDEX_UPDATE_CLASS_INVALID", update_class)
    channel_filename = f"qingshan-storyclaw-release-channel-{tag}.json"
    archive_filename = f"qingshan-storyclaw-workflow-{tag}.tar.gz"
    channel_url = _validate_asset_url(
        payload.get("release_channel_url"),
        _expected_asset_url(tag, channel_filename),
        "STABLE_INDEX_CHANNEL_URL_INVALID",
    )
    archive_url = _validate_asset_url(
        payload.get("source_archive_url"),
        _expected_asset_url(tag, archive_filename),
        "STABLE_INDEX_ARCHIVE_URL_INVALID",
    )
    archive_size = _require_positive_int(
        payload.get("source_archive_size_bytes"), "STABLE_INDEX_ARCHIVE_SIZE_INVALID"
    )
    if archive_size > 512 * 1024 * 1024:
        raise DiscoveryBlocked("STABLE_INDEX_ARCHIVE_SIZE_INVALID", str(archive_size))
    return {
        **payload,
        "release_sequence": sequence,
        "release_tag": tag,
        "git_commit": commit,
        "update_class": update_class,
        "release_channel_url": channel_url,
        "release_channel_size_bytes": _require_positive_int(
            payload.get("release_channel_size_bytes"), "STABLE_INDEX_CHANNEL_SIZE_INVALID"
        ),
        "release_channel_sha256": _require_sha(
            payload.get("release_channel_sha256"), "STABLE_INDEX_CHANNEL_SHA256_INVALID"
        ),
        "source_archive_url": archive_url,
        "source_archive_size_bytes": archive_size,
        "source_archive_sha256": _require_sha(
            payload.get("source_archive_sha256"), "STABLE_INDEX_ARCHIVE_SHA256_INVALID"
        ),
        "validation_receipt_sha256": _require_sha(
            payload.get("validation_receipt_sha256"), "STABLE_INDEX_VALIDATION_SHA256_INVALID"
        ),
    }


def verify_signed_index(
    index_bytes: bytes,
    signature_bytes: bytes,
    public_key: Path,
    *,
    openssl: str = "openssl",
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
) -> dict[str, Any]:
    try:
        resolved_public_key = public_key.expanduser().resolve(strict=True)
        key_bytes = resolved_public_key.read_bytes()
    except OSError as exc:
        raise DiscoveryBlocked("TRUSTED_PUBLIC_KEY_UNAVAILABLE", str(public_key)) from exc
    key_sha = _sha256_bytes(key_bytes)
    if key_sha != TRUSTED_PUBLIC_KEY_SHA256:
        raise DiscoveryBlocked(
            "TRUSTED_PUBLIC_KEY_SHA256_MISMATCH",
            f"expected={TRUSTED_PUBLIC_KEY_SHA256},actual={key_sha}",
        )
    if not index_bytes or len(index_bytes) > 128 * 1024:
        raise DiscoveryBlocked("STABLE_INDEX_SIZE_INVALID", str(len(index_bytes)))
    if not signature_bytes or len(signature_bytes) > 16 * 1024:
        raise DiscoveryBlocked("STABLE_SIGNATURE_SIZE_INVALID", str(len(signature_bytes)))
    with tempfile.TemporaryDirectory(prefix="storyclaw-index-verify-") as temporary:
        root = Path(temporary)
        index_path = root / "index.json"
        signature_path = root / "index.json.sig"
        index_path.write_bytes(index_bytes)
        signature_path.write_bytes(signature_bytes)
        try:
            result = runner(
                [
                    openssl, "pkeyutl", "-verify", "-pubin", "-inkey", str(resolved_public_key),
                    "-rawin", "-in", str(index_path), "-sigfile", str(signature_path),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        except OSError as exc:
            raise DiscoveryBlocked("SIGNATURE_VERIFIER_UNAVAILABLE", openssl) from exc
    if result.returncode != 0:
        raise DiscoveryBlocked("STABLE_INDEX_SIGNATURE_INVALID")
    try:
        payload = json.loads(index_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscoveryBlocked("STABLE_INDEX_JSON_INVALID") from exc
    return validate_index(payload)


def verifier_readiness(
    engine: Path,
    *,
    openssl: str = "openssl",
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
) -> dict[str, Any]:
    """Verify the pinned key and a checked-in Ed25519 signature test vector."""
    key = engine / TRUSTED_PUBLIC_KEY_RELATIVE
    probe = engine / SIGNING_PROBE_RELATIVE
    signature = engine / SIGNING_PROBE_SIGNATURE_RELATIVE
    try:
        key_sha = _sha256_bytes(key.read_bytes())
        probe_sha = _sha256_bytes(probe.read_bytes())
        signature_sha = _sha256_bytes(signature.read_bytes())
    except OSError as exc:
        return {"status": "BLOCKED", "reason": f"SIGNING_PROBE_MISSING:{exc}"}
    expected = {
        "public_key_sha256": TRUSTED_PUBLIC_KEY_SHA256,
        "probe_sha256": SIGNING_PROBE_SHA256,
        "signature_sha256": SIGNING_PROBE_SIGNATURE_SHA256,
    }
    actual = {
        "public_key_sha256": key_sha,
        "probe_sha256": probe_sha,
        "signature_sha256": signature_sha,
    }
    if actual != expected:
        return {
            "status": "BLOCKED",
            "reason": "SIGNING_PROBE_DIGEST_MISMATCH",
            "expected": expected,
            "actual": actual,
        }
    try:
        result = runner(
            [
                openssl, "pkeyutl", "-verify", "-pubin", "-inkey", str(key),
                "-rawin", "-in", str(probe), "-sigfile", str(signature),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return {"status": "BLOCKED", "reason": f"OPENSSL_UNAVAILABLE:{exc}"}
    return {
        "status": "PASS" if result.returncode == 0 else "BLOCKED",
        "reason": None if result.returncode == 0 else "ED25519_PKEYUTL_VERIFY_FAILED",
        "openssl": openssl,
        "exit_code": result.returncode,
        **actual,
    }


def fetch_https(url: str, max_bytes: int, *, timeout: float = 20.0) -> bytes:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_DOWNLOAD_HOSTS:
        raise DiscoveryBlocked("DISCOVERY_URL_NOT_ALLOWED", url)
    request = urllib.request.Request(url, headers={"User-Agent": "StoryClaw-NALU-release-discovery/1"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            final_url = response.geturl()
            final = urllib.parse.urlparse(final_url)
            if final.scheme != "https" or final.hostname not in _ALLOWED_DOWNLOAD_HOSTS:
                raise DiscoveryBlocked("DISCOVERY_REDIRECT_NOT_ALLOWED", final_url)
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > max_bytes:
                raise DiscoveryBlocked("DISCOVERY_DOWNLOAD_TOO_LARGE", declared)
            body = response.read(max_bytes + 1)
    except DiscoveryBlocked:
        raise
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise DiscoveryBlocked("DISCOVERY_DOWNLOAD_FAILED", url) from exc
    if len(body) > max_bytes:
        raise DiscoveryBlocked("DISCOVERY_DOWNLOAD_TOO_LARGE", str(len(body)))
    return body


def _channel_matches_index(channel_bytes: bytes, index: Mapping[str, Any]) -> dict[str, Any]:
    if len(channel_bytes) != index["release_channel_size_bytes"]:
        raise DiscoveryBlocked("DISCOVERED_CHANNEL_SIZE_MISMATCH")
    if _sha256_bytes(channel_bytes) != index["release_channel_sha256"]:
        raise DiscoveryBlocked("DISCOVERED_CHANNEL_SHA256_MISMATCH")
    try:
        payload = json.loads(channel_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiscoveryBlocked("DISCOVERED_CHANNEL_JSON_INVALID") from exc
    exact = {
        "schema": CHANNEL_SCHEMA,
        "immutable": True,
        "channel": "stable",
        "release_sequence": index["release_sequence"],
        "release_tag": index["release_tag"],
        "git_commit": index["git_commit"],
        "source_archive_url": index["source_archive_url"],
        "source_archive_size_bytes": index["source_archive_size_bytes"],
        "source_archive_sha256": index["source_archive_sha256"],
        "update_class": index["update_class"],
        "validation_receipt_status": "PASS",
        "validation_receipt_sha256": index["validation_receipt_sha256"],
        "release_signing_key_sha256": TRUSTED_PUBLIC_KEY_SHA256,
    }
    if not isinstance(payload, dict):
        raise DiscoveryBlocked("DISCOVERED_CHANNEL_JSON_INVALID")
    failures = [field for field, expected in exact.items() if payload.get(field) != expected]
    if failures:
        raise DiscoveryBlocked("DISCOVERED_CHANNEL_BINDING_MISMATCH", ",".join(failures))
    action = payload.get("dependency_profiles_action")
    if action == "REUSE_CURRENT":
        if index["update_class"] != "ENGINE_ONLY" or payload.get("dependencies_changed") or payload.get(
            "dependency_profiles"
        ) != []:
            raise DiscoveryBlocked("DISCOVERED_DEPENDENCY_PROFILE_ACTION_INVALID")
    elif action == "REPLACE_WITH_RELEASE_BUNDLES":
        try:
            _dependency_bundle.validate_release_bindings(
                payload.get("dependency_profiles"), release_tag=index["release_tag"]
            )
        except _dependency_bundle.DependencyBundleBlocked as exc:
            raise DiscoveryBlocked(exc.code, exc.detail) from exc
    else:
        raise DiscoveryBlocked("DISCOVERED_DEPENDENCY_PROFILE_ACTION_INVALID")
    return payload


def _load_json(path: Path, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.expanduser().resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryBlocked(code, str(path)) from exc
    if not isinstance(payload, dict):
        raise DiscoveryBlocked(code, str(path))
    return payload


def _current_engine_identity(engine: Path) -> tuple[str, str]:
    resolved = engine.expanduser().resolve(strict=True)
    archive_manifest = resolved / "RELEASE_MANIFEST.json"
    if archive_manifest.is_file():
        payload = _load_json(archive_manifest, "CURRENT_ENGINE_MANIFEST_INVALID")
        tag = _safe_tag(payload.get("release_tag"))
        commit = str(payload.get("git_commit") or "").strip().lower()
    else:
        try:
            commit_run = subprocess.run(
                ["git", "-C", str(resolved), "rev-parse", "--verify", "HEAD"],
                check=False, capture_output=True, text=True,
            )
            tags_run = subprocess.run(
                ["git", "-C", str(resolved), "tag", "--points-at", "HEAD"],
                check=False, capture_output=True, text=True,
            )
        except OSError as exc:
            raise DiscoveryBlocked("CURRENT_ENGINE_IDENTITY_UNAVAILABLE") from exc
        if commit_run.returncode != 0 or tags_run.returncode != 0:
            raise DiscoveryBlocked("CURRENT_ENGINE_IDENTITY_UNAVAILABLE")
        commit = commit_run.stdout.strip().lower()
        tags = sorted(
            value.strip()
            for value in tags_run.stdout.splitlines()
            if value.strip() and value.strip() != STABLE_CHANNEL_RELEASE_TAG
        )
        if len(tags) != 1:
            raise DiscoveryBlocked("CURRENT_ENGINE_RELEASE_TAG_AMBIGUOUS", ",".join(tags))
        tag = _safe_tag(tags[0])
    if not _COMMIT_RE.fullmatch(commit):
        raise DiscoveryBlocked("CURRENT_ENGINE_COMMIT_INVALID", commit)
    return tag, commit


def _package_baseline(path: Path) -> dict[str, Any]:
    try:
        resolved = path.expanduser().resolve(strict=True)
        raw = resolved.read_bytes()
    except OSError as exc:
        raise DiscoveryBlocked("TALENTHUB_RELEASE_MANIFEST_INVALID", str(path)) from exc
    payload = _load_json(resolved, "TALENTHUB_RELEASE_MANIFEST_INVALID")
    exact = {
        "schema": TALENTHUB_RELEASE_SCHEMA,
        "agent_id": AGENT_ID,
        "skill": SKILL_NAME,
        "validation_receipt_status": "PASS",
        "release_signing_key_sha256": TRUSTED_PUBLIC_KEY_SHA256,
    }
    failures = [field for field, expected in exact.items() if payload.get(field) != expected]
    if payload.get("dependency_profiles_action") != "REPLACE_WITH_RELEASE_BUNDLES":
        failures.append("dependency_profiles_action")
    if failures:
        raise DiscoveryBlocked("TALENTHUB_RELEASE_TRUST_MISMATCH", ",".join(failures))
    commit = str(payload.get("git_commit") or "").strip().lower()
    if not _COMMIT_RE.fullmatch(commit):
        raise DiscoveryBlocked("TALENTHUB_RELEASE_COMMIT_INVALID")
    tag = _safe_tag(payload.get("release_tag"))
    try:
        _dependency_bundle.validate_release_bindings(
            payload.get("dependency_profiles"), release_tag=tag
        )
    except _dependency_bundle.DependencyBundleBlocked as exc:
        raise DiscoveryBlocked(exc.code, exc.detail) from exc
    return {
        "manifest_sha256": _sha256_bytes(raw),
        "release_sequence": _require_positive_int(
            payload.get("release_sequence"), "TALENTHUB_RELEASE_SEQUENCE_INVALID"
        ),
        "release_tag": tag,
        "git_commit": commit,
        "update_class": str(payload.get("release_channel_update_class") or ""),
        "channel_manifest_sha256": _require_sha(
            payload.get("release_channel_sha256"),
            "TALENTHUB_RELEASE_CHANNEL_SHA256_INVALID",
        ),
        "source_archive_size_bytes": _require_positive_int(
            payload.get("source_archive_size_bytes"),
            "TALENTHUB_RELEASE_ARCHIVE_SIZE_INVALID",
        ),
        "source_archive_sha256": _require_sha(
            payload.get("source_archive_sha256"),
            "TALENTHUB_RELEASE_ARCHIVE_SHA256_INVALID",
        ),
        "validation_receipt_sha256": _require_sha(
            payload.get("validation_receipt_sha256"),
            "TALENTHUB_RELEASE_VALIDATION_SHA256_INVALID",
        ),
    }


def _release_binding(payload: Mapping[str, Any], *, trusted: bool) -> dict[str, Any]:
    if trusted:
        sequence = payload.get("trusted_release_sequence")
        tag = payload.get("trusted_release_tag")
        commit = payload.get("trusted_release_commit")
    else:
        sequence = payload.get("release_sequence")
        tag = payload.get("release_tag")
        commit = payload.get("git_commit")
    return {
        "release_sequence": sequence,
        "release_tag": tag,
        "git_commit": commit,
        "update_class": payload.get("update_class"),
        "channel_manifest_sha256": (
            payload.get("channel_manifest_sha256")
            or payload.get("release_channel_sha256")
        ),
        "source_archive_size_bytes": payload.get("source_archive_size_bytes"),
        "source_archive_sha256": payload.get("source_archive_sha256"),
        "validation_receipt_sha256": payload.get("validation_receipt_sha256"),
    }


def _mkdir_private(runtime: Path, path: Path) -> None:
    if path != runtime and runtime not in path.parents:
        raise DiscoveryBlocked("DISCOVERY_PRIVATE_PATH_ESCAPE", str(path))
    current = runtime
    for part in path.relative_to(runtime).parts:
        current = current / part
        if os.path.lexists(current):
            if current.is_symlink() or not current.is_dir():
                raise DiscoveryBlocked("DISCOVERY_PRIVATE_DIRECTORY_INVALID", str(current))
        else:
            current.mkdir(mode=0o700)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_private_json(runtime: Path, path: Path, payload: Mapping[str, Any]) -> None:
    _mkdir_private(runtime, path.parent)
    encoded = json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
    except OSError as exc:
        raise DiscoveryBlocked("DISCOVERY_PRIVATE_WRITE_FAILED", str(temporary)) from exc
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.lexists(temporary):
            temporary.unlink()


def _write_verified_artifact(runtime: Path, path: Path, body: bytes) -> None:
    _mkdir_private(runtime, path.parent)
    if os.path.lexists(path):
        if path.is_symlink() or not path.is_file():
            raise DiscoveryBlocked("DISCOVERY_ARTIFACT_PATH_INVALID", str(path))
        if path.read_bytes() != body:
            raise DiscoveryBlocked("DISCOVERY_ARTIFACT_EQUIVOCATION", str(path))
        return
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.lexists(temporary):
            temporary.unlink()


def discover_stable_release(
    engine: Path,
    runtime: Path,
    talenthub_release_manifest: Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """Serialize discovery so the highest trusted sequence cannot be lost."""
    runtime_root = runtime.expanduser().resolve(strict=True)
    if not runtime_root.is_dir():
        raise DiscoveryBlocked("RUNTIME_ROOT_INVALID", str(runtime_root))
    lock_path = runtime_root / DISCOVERY_LOCK_RELATIVE
    _mkdir_private(runtime_root, lock_path.parent)
    if os.path.lexists(lock_path) and (lock_path.is_symlink() or not lock_path.is_file()):
        raise DiscoveryBlocked("DISCOVERY_LOCK_PATH_INVALID", str(lock_path))
    descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    with os.fdopen(descriptor, "a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise DiscoveryBlocked("DISCOVERY_ALREADY_RUNNING", str(lock_path)) from exc
        try:
            return _discover_stable_release_locked(
                engine, runtime_root, talenthub_release_manifest, **kwargs
            )
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _discover_stable_release_locked(
    engine: Path,
    runtime: Path,
    talenthub_release_manifest: Path,
    *,
    public_key: Path | None = None,
    index_url: str = STABLE_INDEX_URL,
    signature_url: str = STABLE_SIGNATURE_URL,
    fetcher: Callable[[str, int], bytes] = fetch_https,
    openssl: str = "openssl",
    download_archive: bool = False,
) -> dict[str, Any]:
    runtime_root = runtime.expanduser().resolve(strict=True)
    if not runtime_root.is_dir():
        raise DiscoveryBlocked("RUNTIME_ROOT_INVALID", str(runtime_root))
    engine_root = engine.expanduser().resolve(strict=True)
    key = public_key or (engine_root / TRUSTED_PUBLIC_KEY_RELATIVE)
    current_tag, current_commit = _current_engine_identity(engine_root)
    package = _package_baseline(talenthub_release_manifest)
    if not _COMMIT_RE.fullmatch(package["git_commit"]):
        raise DiscoveryBlocked("TALENTHUB_RELEASE_COMMIT_INVALID")

    current_state_path = runtime_root / CURRENT_RELEASE_STATE_RELATIVE
    current_state = _load_json(
        current_state_path, "CURRENT_RELEASE_BASELINE_MISSING_OR_INVALID"
    )
    current_sequence = _require_positive_int(
        current_state.get("release_sequence"), "CURRENT_RELEASE_BASELINE_INVALID"
    )
    current_state_exact = {
        "schema": CURRENT_RELEASE_STATE_SCHEMA,
        "status": "PASS",
        "release_tag": current_tag,
        "git_commit": current_commit,
        "signing_key_sha256": TRUSTED_PUBLIC_KEY_SHA256,
        "talenthub_release_manifest_sha256": package["manifest_sha256"],
    }
    current_failures = [
        field
        for field, expected in current_state_exact.items()
        if current_state.get(field) != expected
    ]
    if current_failures:
        raise DiscoveryBlocked(
            "CURRENT_RELEASE_BASELINE_MISMATCH", ",".join(current_failures)
        )

    state_path = runtime_root / DISCOVERY_STATE_RELATIVE
    state: dict[str, Any] | None = None
    if state_path.is_file():
        state = _load_json(state_path, "DISCOVERY_STATE_INVALID")
        if state.get("schema") != RESULT_SCHEMA or state.get("status") not in {"CURRENT", "AVAILABLE", "APPLIED"}:
            raise DiscoveryBlocked("DISCOVERY_STATE_INVALID", str(state_path))

    if (
        current_commit == package["git_commit"]
        and current_tag == package["release_tag"]
        and current_sequence == package["release_sequence"]
    ):
        installed_binding = _release_binding(package, trusted=False)
    elif (
        state
        and state.get("status") == "APPLIED"
        and state.get("trusted_release_commit") == current_commit
        and state.get("trusted_release_tag") == current_tag
    ):
        installed_binding = _release_binding(state, trusted=True)
    else:
        raise DiscoveryBlocked(
            "CURRENT_ENGINE_NOT_BOUND_TO_TRUSTED_RELEASE",
            f"tag={current_tag},commit={current_commit}",
        )
    baseline_sequence = current_sequence
    if installed_binding.get("release_sequence") != baseline_sequence:
        raise DiscoveryBlocked("CURRENT_RELEASE_BASELINE_MISMATCH", "release_sequence")
    cached_binding: dict[str, Any] | None = None
    if state:
        cached_binding = _release_binding(state, trusted=True)
        cached_sequence = _require_positive_int(
            cached_binding.get("release_sequence"), "DISCOVERY_STATE_SEQUENCE_INVALID"
        )
        if cached_sequence > baseline_sequence:
            baseline_sequence = cached_sequence

    index_bytes = fetcher(index_url, 128 * 1024)
    signature_bytes = fetcher(signature_url, 16 * 1024)
    index = verify_signed_index(index_bytes, signature_bytes, key, openssl=openssl)
    if index["release_sequence"] < baseline_sequence:
        raise DiscoveryBlocked(
            "STABLE_INDEX_ROLLBACK",
            f"baseline={baseline_sequence},index={index['release_sequence']}",
        )
    if index["release_sequence"] == baseline_sequence:
        expected_binding = (
            cached_binding
            if cached_binding is not None
            and cached_binding["release_sequence"] == baseline_sequence
            else installed_binding
        )
        if _release_binding(index, trusted=False) != expected_binding:
            raise DiscoveryBlocked("STABLE_INDEX_SEQUENCE_EQUIVOCATION")

    channel_bytes = fetcher(index["release_channel_url"], 1024 * 1024)
    _channel_matches_index(channel_bytes, index)
    release_dir = (
        runtime_root / DISCOVERY_ROOT_RELATIVE /
        f"{index['release_sequence']}-{index['release_tag']}"
    )
    _mkdir_private(runtime_root, release_dir)
    index_path = release_dir / "stable-index.json"
    signature_path = release_dir / "stable-index.json.sig"
    channel_path = release_dir / f"qingshan-storyclaw-release-channel-{index['release_tag']}.json"
    for path, body in (
        (index_path, index_bytes), (signature_path, signature_bytes), (channel_path, channel_bytes),
    ):
        _write_verified_artifact(runtime_root, path, body)

    status = "CURRENT" if index["git_commit"] == current_commit else "AVAILABLE"
    archive_path: Path | None = None
    if status == "AVAILABLE" and download_archive:
        archive_bytes = fetcher(
            index["source_archive_url"], index["source_archive_size_bytes"]
        )
        if len(archive_bytes) != index["source_archive_size_bytes"]:
            raise DiscoveryBlocked("DISCOVERED_ARCHIVE_SIZE_MISMATCH")
        if _sha256_bytes(archive_bytes) != index["source_archive_sha256"]:
            raise DiscoveryBlocked("DISCOVERED_ARCHIVE_SHA256_MISMATCH")
        archive_path = release_dir / f"qingshan-storyclaw-workflow-{index['release_tag']}.tar.gz"
        _write_verified_artifact(runtime_root, archive_path, archive_bytes)
    receipt = {
        "schema": RESULT_SCHEMA,
        "status": status,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "current_release_tag": current_tag,
        "current_release_commit": current_commit,
        "baseline_release_sequence": baseline_sequence,
        "trusted_release_sequence": index["release_sequence"],
        "trusted_release_tag": index["release_tag"],
        "trusted_release_commit": index["git_commit"],
        "update_class": index["update_class"],
        "index_url": index_url,
        "index_sha256": _sha256_bytes(index_bytes),
        "signature_url": signature_url,
        "signature_sha256": _sha256_bytes(signature_bytes),
        "signing_key_sha256": TRUSTED_PUBLIC_KEY_SHA256,
        "channel_manifest": str(channel_path),
        "channel_manifest_sha256": index["release_channel_sha256"],
        "source_archive_url": index["source_archive_url"],
        "source_archive_size_bytes": index["source_archive_size_bytes"],
        "source_archive_sha256": index["source_archive_sha256"],
        "source_archive_path": str(archive_path) if archive_path else None,
        "validation_receipt_sha256": index["validation_receipt_sha256"],
        "provider_posts": 0,
    }
    _atomic_private_json(runtime_root, state_path, receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine-root", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--talenthub-release-manifest", type=Path, required=True)
    parser.add_argument("--public-key", type=Path)
    parser.add_argument("--index-url", default=STABLE_INDEX_URL)
    parser.add_argument("--signature-url", default=STABLE_SIGNATURE_URL)
    parser.add_argument("--openssl", default="openssl")
    parser.add_argument(
        "--download-archive",
        action="store_true",
        help="download and verify the immutable source archive when an update is available",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = discover_stable_release(
            args.engine_root,
            args.runtime_root,
            args.talenthub_release_manifest,
            public_key=args.public_key,
            index_url=args.index_url,
            signature_url=args.signature_url,
            openssl=args.openssl,
            download_archive=args.download_archive,
        )
    except DiscoveryBlocked as exc:
        print(json.dumps({
            "schema": ERROR_SCHEMA,
            "status": "BLOCKED",
            "code": exc.code,
            "detail": exc.detail,
        }, ensure_ascii=False, sort_keys=True), file=os.sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
