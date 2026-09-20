#!/usr/bin/env python3
"""One-command bootstrap for a TalentHub-installed NALU Agent.

This file is bundled inside the skill, so it is available before the engine.
It verifies the installed package binding and immutable release asset, obtains
the exact Git commit, initializes a private project against its future stable
engine link, and delegates the bounded host installation to that engine.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote, urlsplit


SCHEMA = "qingshan.storyclaw.talenthub.release.v1"
RECEIPT_SCHEMA = "storyclaw.nalu.skill_bootstrap.v1"
INSTALL_RECEIPT_SCHEMA = "storyclaw.nalu.host_install_receipt.v1"
PREFLIGHT_SCHEMA = "storyclaw.nalu.preflight.v1"
SNAPSHOT_SCHEMA = "storyclaw.nalu.transactions_snapshot.v1"
AGENT_ID = "ai-drama-factory"
SKILL_NAME = "qingshan-nalu"
REPOSITORY = "https://github.com/rogerwu188/qingshan-short-drama-production-line"
SIGNING_KEY_SHA256 = "d27484512874011dc5e894b602d6a42ca846a4e048688d32389acf7852d3646f"
BOUND_FILES = frozenset({
    "IDENTITY.md",
    "USER.md",
    "SOUL.md",
    "AGENTS.md",
    "HEARTBEAT.md",
    "skills/qingshan-nalu/SKILL.md",
    "skills/qingshan-nalu/bootstrap_storyclaw.py",
})
RUNTIME_LINK_PATHS = frozenset({"workflow/nalu", "workflow/tasks"})
PROVIDER_CREDENTIAL_NAMES = frozenset({
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
_TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}\Z")
_COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
DEPENDENCY_PROFILE_BY_PYTHON = {
    (3, 10): "storyclaw-linux-x86_64-cpython310-cpu-v1",
    (3, 11): "storyclaw-linux-x86_64-cpython311-cpu-v1",
}
MAX_DEPENDENCY_MANIFEST_BYTES = 1024 * 1024
MAX_DEPENDENCY_ARCHIVE_BYTES = 1024 * 1024 * 1024
BOOTSTRAP_RECEIPT_RELATIVE = Path(
    "runtime/receipts/storyclaw_bootstrap/bootstrap.json"
)
SMOKE_RECEIPT_ROOT_RELATIVE = Path(
    "runtime/receipts/storyclaw_registry_clean_install_smoke"
)
SMOKE_PREFLIGHT_RELATIVE = SMOKE_RECEIPT_ROOT_RELATIVE / "preflight.json"
INSTALL_RECEIPT_ROOT_RELATIVE = Path("runtime/receipts/storyclaw_host_install")
VENV_SELECTOR_RELATIVE = Path("runtime/storyclaw_host/current-venv")


class BootstrapBlocked(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _project_directory(project_home: Path, relative: str) -> Path:
    """Create a private project directory without following pre-existing links."""
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or any(
        part in {"", "."} for part in pure.parts
    ):
        raise BootstrapBlocked(f"PROJECT_DIRECTORY_INVALID:{relative}")
    current = project_home
    for part in pure.parts:
        current = current / part
        if os.path.lexists(current):
            if current.is_symlink() or not current.is_dir():
                raise BootstrapBlocked(f"PROJECT_DIRECTORY_UNSAFE:{current}")
        else:
            current.mkdir(mode=0o700)
    return current


def _regular_file_facts(root: Path) -> dict[str, tuple[int, str]]:
    """Hash transaction files without following links or accepting special nodes."""
    if not os.path.lexists(root):
        return {}
    if root.is_symlink() or not root.is_dir():
        raise BootstrapBlocked("TRANSACTION_STORE_INVALID")
    facts: dict[str, tuple[int, str]] = {}
    for current, directories, filenames in os.walk(root, followlinks=False):
        base = Path(current)
        for name in directories:
            path = base / name
            if path.is_symlink():
                raise BootstrapBlocked("TRANSACTION_STORE_SYMLINK")
        for name in filenames:
            path = base / name
            if path.is_symlink() or not path.is_file():
                raise BootstrapBlocked("TRANSACTION_STORE_SPECIAL_ENTRY")
            facts[path.relative_to(root).as_posix()] = (path.stat().st_size, _sha256(path))
    return facts


def _manifest_path(workspace: Path) -> Path:
    return workspace / "skills" / SKILL_NAME / "RELEASE_MANIFEST.json"


def _asset_url(tag: str, filename: str) -> str:
    return f"{REPOSITORY}/releases/download/{quote(tag)}/{quote(filename)}"


def _dependency_asset_names(tag: str, profile_id: str) -> tuple[str, str]:
    stem = f"qingshan-storyclaw-dependencies-{profile_id}-{tag}"
    return f"{stem}.json", f"{stem}.tar.gz"


def _validate_dependency_bindings(value: object, *, tag: str) -> dict[str, dict[str, Any]]:
    """Validate the exact two release-bound dependency assets before networking."""
    expected_profiles = set(DEPENDENCY_PROFILE_BY_PYTHON.values())
    if not isinstance(value, list) or len(value) != len(expected_profiles):
        raise BootstrapBlocked("INSTALLED_DEPENDENCY_BINDINGS_INVALID")
    bindings: dict[str, dict[str, Any]] = {}
    for row in value:
        if not isinstance(row, dict):
            raise BootstrapBlocked("INSTALLED_DEPENDENCY_BINDING_INVALID")
        profile_id = str(row.get("profile_id") or "")
        if profile_id not in expected_profiles or profile_id in bindings:
            raise BootstrapBlocked(
                f"INSTALLED_DEPENDENCY_BINDING_INVALID:{profile_id}"
            )
        manifest_name, archive_name = _dependency_asset_names(tag, profile_id)
        if (
            row.get("manifest_url") != _asset_url(tag, manifest_name)
            or row.get("archive_url") != _asset_url(tag, archive_name)
        ):
            raise BootstrapBlocked(
                f"INSTALLED_DEPENDENCY_BINDING_URL_INVALID:{profile_id}"
            )
        for prefix, maximum in (
            ("manifest", MAX_DEPENDENCY_MANIFEST_BYTES),
            ("archive", MAX_DEPENDENCY_ARCHIVE_BYTES),
        ):
            size = row.get(f"{prefix}_size_bytes")
            digest = str(row.get(f"{prefix}_sha256") or "").lower()
            if (
                type(size) is not int
                or not 0 < size <= maximum
                or not _SHA_RE.fullmatch(digest)
            ):
                raise BootstrapBlocked(
                    f"INSTALLED_DEPENDENCY_BINDING_DIGEST_INVALID:{profile_id}"
                )
        bindings[profile_id] = dict(row)
    if set(bindings) != expected_profiles:
        raise BootstrapBlocked("INSTALLED_DEPENDENCY_BINDINGS_INVALID")
    return bindings


def _select_dependency_binding(release: Mapping[str, Any]) -> dict[str, Any]:
    """Select one supported Linux/glibc/CPython profile without fallback."""
    system = platform.system()
    machine = platform.machine().lower()
    implementation = platform.python_implementation().lower()
    libc_name, libc_text = platform.libc_ver()
    if (
        system != "Linux"
        or machine not in {"x86_64", "amd64"}
        or implementation != "cpython"
        or libc_name.lower() != "glibc"
    ):
        raise BootstrapBlocked(
            "DEPENDENCY_PLATFORM_UNSUPPORTED:"
            f"system={system},machine={machine},implementation={implementation},libc={libc_name}"
        )
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.\d+)?", libc_text.strip())
    if match is None or (int(match.group(1)), int(match.group(2))) < (2, 31):
        raise BootstrapBlocked(f"DEPENDENCY_LIBC_UNSUPPORTED:{libc_text}")
    profile_id = DEPENDENCY_PROFILE_BY_PYTHON.get(
        (sys.version_info.major, sys.version_info.minor)
    )
    if profile_id is None:
        raise BootstrapBlocked(
            f"DEPENDENCY_PYTHON_UNSUPPORTED:{sys.version_info.major}.{sys.version_info.minor}"
        )
    bindings = release.get("dependency_profile_bindings")
    if not isinstance(bindings, dict) or profile_id not in bindings:
        raise BootstrapBlocked(f"DEPENDENCY_PROFILE_BINDING_MISSING:{profile_id}")
    return dict(bindings[profile_id])


def _workspace_file(workspace: Path, relative: str) -> Path:
    """Return an installed file only when every path component is local and real."""
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or any(
        part in {"", "."} for part in pure.parts
    ):
        raise BootstrapBlocked(f"INSTALLED_PATH_INVALID:{relative}")
    current = workspace
    for part in pure.parts:
        current = current / part
        try:
            if current.is_symlink():
                raise BootstrapBlocked(f"INSTALLED_PATH_SYMLINK:{relative}")
        except OSError as exc:
            raise BootstrapBlocked(f"INSTALLED_PATH_INVALID:{relative}") from exc
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(workspace)
    except (OSError, ValueError) as exc:
        raise BootstrapBlocked(f"INSTALLED_PATH_ESCAPE:{relative}") from exc
    return current


def load_installed_release(workspace: Path) -> dict[str, Any]:
    workspace = workspace.expanduser().resolve(strict=True)
    manifest_path = _workspace_file(
        workspace, "skills/qingshan-nalu/RELEASE_MANIFEST.json"
    )
    try:
        if manifest_path.is_symlink():
            raise OSError("manifest symlink")
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BootstrapBlocked("INSTALLED_RELEASE_MANIFEST_INVALID") from exc
    tag = str(payload.get("release_tag") or "")
    commit = str(payload.get("git_commit") or "").lower()
    archive_sha = str(payload.get("source_archive_sha256") or "").lower()
    archive_size = payload.get("source_archive_size_bytes")
    expected_url = (
        f"{REPOSITORY}/releases/download/{quote(tag)}/"
        f"qingshan-storyclaw-workflow-{quote(tag)}.tar.gz"
    )
    exact = {
        "schema": SCHEMA,
        "agent_id": AGENT_ID,
        "skill": SKILL_NAME,
        "origin_tag_commit": commit,
        "repository": REPOSITORY,
        "source_archive_github_release_url": expected_url,
        "release_signing_key_sha256": SIGNING_KEY_SHA256,
        "validation_receipt_status": "PASS",
        "public_runtime_only": True,
        "private_validation_contents_included": False,
        "dependency_profiles_action": "REPLACE_WITH_RELEASE_BUNDLES",
    }
    failures = [key for key, expected in exact.items() if payload.get(key) != expected]
    if not _TAG_RE.fullmatch(tag):
        failures.append("release_tag")
    if not _COMMIT_RE.fullmatch(commit):
        failures.append("git_commit")
    if not _SHA_RE.fullmatch(archive_sha):
        failures.append("source_archive_sha256")
    if type(archive_size) is not int or archive_size <= 0 or archive_size > 512 * 1024 * 1024:
        failures.append("source_archive_size_bytes")
    sequence = payload.get("release_sequence")
    if type(sequence) is not int or sequence <= 0:
        failures.append("release_sequence")
    try:
        dependency_bindings = _validate_dependency_bindings(
            payload.get("dependency_profiles"), tag=tag
        )
    except BootstrapBlocked:
        failures.append("dependency_profiles")
        dependency_bindings = {}
    bindings = payload.get("installed_file_bindings")
    if not isinstance(bindings, dict) or set(bindings) != BOUND_FILES:
        failures.append("installed_file_bindings")
    else:
        for relative in sorted(BOUND_FILES):
            row = bindings.get(relative)
            try:
                target = _workspace_file(workspace, relative)
            except BootstrapBlocked:
                failures.append(f"binding:{relative}")
                continue
            if (
                not isinstance(row, dict)
                or type(row.get("size_bytes")) is not int
                or row["size_bytes"] <= 0
                or not _SHA_RE.fullmatch(str(row.get("sha256") or "").lower())
                or target.is_symlink()
                or not target.is_file()
                or target.stat().st_size != row["size_bytes"]
                or _sha256(target) != str(row["sha256"]).lower()
            ):
                failures.append(f"binding:{relative}")
    if failures:
        raise BootstrapBlocked("INSTALLED_RELEASE_BINDING_MISMATCH:" + ",".join(failures[:12]))
    return {
        **payload,
        "dependency_profile_bindings": dependency_bindings,
        "manifest_path": str(manifest_path),
        "workspace": str(workspace),
    }


def _download_archive(url: str, expected_size: int) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "github.com" or parsed.fragment:
        raise BootstrapBlocked("SOURCE_ARCHIVE_URL_INVALID")
    request = urllib.request.Request(url, headers={"User-Agent": "qingshan-storyclaw-bootstrap/1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read(expected_size + 1)
    except OSError as exc:
        raise BootstrapBlocked(f"SOURCE_ARCHIVE_DOWNLOAD_FAILED:{exc}") from exc
    if len(body) != expected_size:
        raise BootstrapBlocked("SOURCE_ARCHIVE_SIZE_MISMATCH")
    return body


def _cached_asset(
    cache_root: Path,
    *,
    filename: str,
    url: str,
    expected_size: int,
    expected_sha256: str,
    fetcher: Callable[[str, int], bytes],
) -> Path:
    """Reuse an exact private cache entry or atomically materialize bound bytes."""
    target = cache_root / filename
    if target.exists():
        if (
            target.is_symlink()
            or not target.is_file()
            or target.stat().st_size != expected_size
            or _sha256(target) != expected_sha256
        ):
            raise BootstrapBlocked(f"RELEASE_ASSET_CACHE_MISMATCH:{filename}")
        return target
    body = fetcher(url, expected_size)
    if (
        len(body) != expected_size
        or hashlib.sha256(body).hexdigest() != expected_sha256
    ):
        raise BootstrapBlocked(f"RELEASE_ASSET_DIGEST_MISMATCH:{filename}")
    _atomic_bytes(target, body)
    return target


def _extract_verified_archive(
    archive: bytes,
    destination: Path,
    *,
    release_tag: str,
    git_commit: str,
) -> None:
    """Strictly stream one release archive and verify any existing view bytewise."""
    if destination.is_symlink():
        raise BootstrapBlocked("SOURCE_ARCHIVE_DESTINATION_SYMLINK")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent))
    prefix = "qingshan-storyclaw-workflow/"
    seen: set[str] = set()
    member_count = 0
    total = 0
    release_manifest: dict[str, Any] | None = None
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r|gz") as source:
            for member in source:
                member_count += 1
                if member_count > 20000:
                    raise BootstrapBlocked("SOURCE_ARCHIVE_TOO_MANY_MEMBERS")
                if member.name.rstrip("/") == prefix.rstrip("/"):
                    if not member.isdir():
                        raise BootstrapBlocked("SOURCE_ARCHIVE_ROOT_INVALID")
                    continue
                if not member.name.startswith(prefix):
                    raise BootstrapBlocked("SOURCE_ARCHIVE_PREFIX_INVALID")
                relative_text = member.name[len(prefix):].rstrip("/")
                if not relative_text:
                    if not member.isdir():
                        raise BootstrapBlocked("SOURCE_ARCHIVE_ROOT_INVALID")
                    continue
                pure = PurePosixPath(relative_text)
                if pure.is_absolute() or ".." in pure.parts or any(
                    part in {"", "."} for part in pure.parts
                ):
                    raise BootstrapBlocked("SOURCE_ARCHIVE_PATH_INVALID")
                relative = Path(*pure.parts)
                key = relative.as_posix()
                if key in seen:
                    raise BootstrapBlocked("SOURCE_ARCHIVE_DUPLICATE_MEMBER")
                seen.add(key)
                if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                    raise BootstrapBlocked("SOURCE_ARCHIVE_SPECIAL_MEMBER")
                target = staging / relative
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o755)
                    continue
                if not member.isfile() or member.size < 0 or member.size > 128 * 1024 * 1024:
                    raise BootstrapBlocked("SOURCE_ARCHIVE_MEMBER_INVALID")
                total += member.size
                if total > 1024 * 1024 * 1024:
                    raise BootstrapBlocked("SOURCE_ARCHIVE_EXPANDED_SIZE_EXCEEDED")
                stream = source.extractfile(member)
                if stream is None:
                    raise BootstrapBlocked("SOURCE_ARCHIVE_MEMBER_READ_FAILED")
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
                actual = 0
                with stream, target.open("xb") as output:
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        actual += len(chunk)
                        if actual > member.size:
                            raise BootstrapBlocked("SOURCE_ARCHIVE_MEMBER_SIZE_MISMATCH")
                        output.write(chunk)
                if actual != member.size:
                    raise BootstrapBlocked("SOURCE_ARCHIVE_MEMBER_SIZE_MISMATCH")
                os.chmod(target, 0o755 if member.mode & 0o111 else 0o644)
                if key == "RELEASE_MANIFEST.json":
                    try:
                        value = json.loads(target.read_text(encoding="utf-8"))
                    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                        raise BootstrapBlocked("SOURCE_ARCHIVE_RELEASE_MANIFEST_INVALID") from exc
                    if not isinstance(value, dict):
                        raise BootstrapBlocked("SOURCE_ARCHIVE_RELEASE_MANIFEST_INVALID")
                    release_manifest = value
        if (
            release_manifest is None
            or release_manifest.get("schema") != "qingshan.storyclaw.release.v1"
            or release_manifest.get("release_tag") != release_tag
            or release_manifest.get("git_commit") != git_commit
            or release_manifest.get("private_runtime_included") is not False
            or release_manifest.get("credentials_included") is not False
        ):
            raise BootstrapBlocked("SOURCE_ARCHIVE_RELEASE_BINDING_MISMATCH")
        if destination.exists():
            if not destination.is_dir():
                raise BootstrapBlocked("SOURCE_ARCHIVE_DESTINATION_INVALID")
            if not _existing_view_matches(destination, staging):
                raise BootstrapBlocked("SOURCE_ARCHIVE_EXISTING_VIEW_MISMATCH")
        else:
            os.replace(staging, destination)
    except BootstrapBlocked:
        raise
    except (OSError, EOFError, tarfile.TarError) as exc:
        raise BootstrapBlocked("SOURCE_ARCHIVE_INVALID") from exc
    finally:
        if staging.exists():
            import shutil
            shutil.rmtree(staging)


def _tree_facts(
    root: Path, *, allow_runtime_links: bool = False
) -> dict[str, tuple[str, int, str, int]]:
    """Describe a tree without following links; any special entry blocks reuse."""
    if root.is_symlink() or not root.is_dir():
        raise BootstrapBlocked("SOURCE_ARCHIVE_EXISTING_VIEW_INVALID")
    facts: dict[str, tuple[str, int, str, int]] = {}
    stack = [root]
    while stack:
        directory = stack.pop()
        try:
            entries = sorted(os.scandir(directory), key=lambda row: row.name)
        except OSError as exc:
            raise BootstrapBlocked("SOURCE_ARCHIVE_EXISTING_VIEW_INVALID") from exc
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(root).as_posix()
            try:
                stat = entry.stat(follow_symlinks=False)
            except OSError as exc:
                raise BootstrapBlocked("SOURCE_ARCHIVE_EXISTING_VIEW_INVALID") from exc
            mode = stat.st_mode & 0o777
            if entry.is_symlink():
                if not allow_runtime_links or relative not in RUNTIME_LINK_PATHS:
                    raise BootstrapBlocked("SOURCE_ARCHIVE_EXISTING_VIEW_SYMLINK")
                try:
                    target = path.resolve(strict=True)
                    project_home = root.parents[2].resolve(strict=True)
                    target.relative_to(project_home)
                    target.relative_to(root)
                except ValueError:
                    # Expected: the private target is inside the project but
                    # outside the immutable engine release view.
                    try:
                        target.relative_to(project_home)
                    except ValueError as exc:
                        raise BootstrapBlocked(
                            "SOURCE_ARCHIVE_RUNTIME_LINK_ESCAPE"
                        ) from exc
                except OSError as exc:
                    raise BootstrapBlocked("SOURCE_ARCHIVE_RUNTIME_LINK_INVALID") from exc
                if not target.is_dir() or target == root or root in target.parents:
                    raise BootstrapBlocked("SOURCE_ARCHIVE_RUNTIME_LINK_INVALID")
                facts[relative] = ("runtime_link", 0, "", 0)
                continue
            if entry.is_dir(follow_symlinks=False):
                facts[relative] = ("directory", 0, "", mode)
                stack.append(path)
            elif entry.is_file(follow_symlinks=False):
                facts[relative] = ("file", stat.st_size, _sha256(path), mode)
            else:
                raise BootstrapBlocked("SOURCE_ARCHIVE_EXISTING_VIEW_SPECIAL")
    return facts


def _existing_view_matches(existing: Path, extracted: Path) -> bool:
    expected = _tree_facts(extracted)
    actual = _tree_facts(existing, allow_runtime_links=True)
    for relative, row in list(actual.items()):
        if row[0] != "runtime_link":
            continue
        expected_row = expected.get(relative)
        if expected_row is None:
            del actual[relative]
            continue
        if expected_row[0] != "directory" or any(
            key.startswith(relative + "/") for key in expected
        ):
            return False
    if set(expected) != set(actual):
        return False
    for relative, expected_row in expected.items():
        actual_row = actual[relative]
        if actual_row[0] == "runtime_link":
            continue
        if actual_row[:3] != expected_row[:3]:
            return False
        expected_mode = expected_row[3]
        if actual_row[3] not in {expected_mode, expected_mode & ~0o222}:
            return False
    return True


def _run(
    command: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    extra_env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    for name in PROVIDER_CREDENTIAL_NAMES:
        environment.pop(name, None)
    for name, value in (extra_env or {}).items():
        if name in PROVIDER_CREDENTIAL_NAMES:
            raise BootstrapBlocked(f"PROVIDER_ENV_OVERRIDE_REFUSED:{name}")
        environment[str(name)] = str(value)
    # These locks are forced *after* bounded overrides so a caller cannot turn
    # a clean-install/preflight process into a paid provider process.
    environment["QINGSHAN_PAID_REQUESTS_ENABLED"] = "0"
    environment["QINGSHAN_BOOTSTRAP_NO_PROVIDER_POSTS"] = "1"
    result = runner(
        list(command), text=True, capture_output=True, check=False,
        env={**environment, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()[-1:]
        raise BootstrapBlocked(
            "COMMAND_FAILED:" + " ".join(command[:3]) + ":" + (detail[0] if detail else str(result.returncode))
        )
    return result


def _json_result(result: subprocess.CompletedProcess[str], code: str) -> dict[str, Any]:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise BootstrapBlocked(code) from exc
    if not isinstance(value, dict) or value.get("status") not in {
        "PASS", "INITIALIZED_PRIVATE", "EXISTS_UNCHANGED"
    }:
        raise BootstrapBlocked(code)
    return value


def _private_json_binding(
    path: Path,
    runtime: Path,
    *,
    expected_parent: Path,
    schema: str,
    code: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Open one private receipt without accepting a link or path escape."""
    candidate = path.expanduser()
    if not candidate.is_absolute() or candidate.is_symlink():
        raise BootstrapBlocked(code)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(runtime)
        parent = expected_parent.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise BootstrapBlocked(code) from exc
    if resolved.parent != parent or not resolved.is_file():
        raise BootstrapBlocked(code)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BootstrapBlocked(code) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != schema
        or payload.get("status") != "PASS"
    ):
        raise BootstrapBlocked(code)
    return payload, {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": _sha256(resolved),
    }


def _run_smoke_snapshot(
    view: Path,
    runtime: Path,
    *,
    label: str,
    output: Path,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    prior_snapshot: Path | None = None,
) -> dict[str, Any]:
    """Delegate transaction/phase observation to the independent smoke tool."""
    tool = view / "tools/storyclaw_registry_clean_install_smoke.py"
    if tool.is_symlink() or not tool.is_file():
        raise BootstrapBlocked("REGISTRY_SMOKE_TOOL_MISSING")
    command = [
        sys.executable,
        str(tool),
        "snapshot",
        "--runtime-root",
        str(runtime),
        "--label",
        label,
        "--output",
        str(output),
    ]
    if prior_snapshot is not None:
        command += ["--prior-snapshot", str(prior_snapshot)]
    result = _json_result(
        _run(command, runner=runner),
        f"REGISTRY_SMOKE_{label.upper()}_SNAPSHOT_FAILED",
    )
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BootstrapBlocked(
            f"REGISTRY_SMOKE_{label.upper()}_SNAPSHOT_INVALID"
        ) from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema") != SNAPSHOT_SCHEMA
        or payload.get("status") != "PASS"
        or payload.get("label") != label
        or payload.get("private_runtime_root") != str(runtime)
        or payload.get("provider_posts") != 0
        or payload.get("provider_secret_names_present") != []
        or result.get("snapshot_sha256") != _sha256(output)
    ):
        raise BootstrapBlocked(
            f"REGISTRY_SMOKE_{label.upper()}_SNAPSHOT_INVALID"
        )
    return {
        "path": str(output),
        "size_bytes": output.stat().st_size,
        "sha256": _sha256(output),
        "transactions_tree_sha256": payload.get("tree_sha256"),
    }


def _load_existing_snapshot(
    path: Path, runtime: Path, *, label: str
) -> dict[str, Any]:
    payload, binding = _private_json_binding(
        path,
        runtime,
        expected_parent=runtime / SMOKE_RECEIPT_ROOT_RELATIVE,
        schema=SNAPSHOT_SCHEMA,
        code=f"REGISTRY_SMOKE_{label.upper()}_SNAPSHOT_INVALID",
    )
    if (
        payload.get("label") != label
        or payload.get("private_runtime_root") != str(runtime)
        or payload.get("provider_posts") != 0
        or payload.get("provider_secret_names_present") != []
        or not re.fullmatch(r"[0-9a-f]{64}", str(payload.get("tree_sha256") or ""))
    ):
        raise BootstrapBlocked(
            f"REGISTRY_SMOKE_{label.upper()}_SNAPSHOT_INVALID"
        )
    return {
        **binding,
        "transactions_tree_sha256": payload["tree_sha256"],
    }


def _validate_preflight_result(
    payload: Mapping[str, Any],
    *,
    engine: Path,
    runtime: Path,
    marker: Mapping[str, Any],
    git_commit: str,
) -> None:
    checks = payload.get("checks")
    paid = checks.get("paid_lock") if isinstance(checks, dict) else None
    if (
        payload.get("schema") != PREFLIGHT_SCHEMA
        or payload.get("status") != "PASS"
        or payload.get("engine_commit") != git_commit
        or payload.get("engine_root") != str(engine.resolve(strict=True))
        or payload.get("private_runtime_root") != str(runtime)
        or payload.get("project_id") != str(marker.get("project_id") or "")
        or payload.get("series_scope_id")
        != str(marker.get("series_scope_id") or "")
        or not isinstance(checks, dict)
        or not checks
        or any(
            not isinstance(row, dict) or row.get("status") != "PASS"
            for row in checks.values()
        )
        or not isinstance(paid, dict)
        or paid.get("paid_requests_enabled") is not False
        or paid.get("api_key_present") is not False
    ):
        raise BootstrapBlocked("PREFLIGHT_RECEIPT_INVALID")


def bootstrap_project(
    workspace: Path,
    project_home: Path,
    *,
    title: str = "Untitled short drama",
    project_id: str | None = None,
    scope_id: str | None = None,
    install_deps: bool = True,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    fetcher: Callable[[str, int], bytes] = _download_archive,
) -> dict[str, Any]:
    release = load_installed_release(workspace)
    tag = str(release["release_tag"])
    commit = str(release["git_commit"])
    project_home = project_home.expanduser()
    if not project_home.is_absolute():
        project_home = project_home.absolute()
    if os.path.lexists(project_home) and (
        project_home.is_symlink() or not project_home.is_dir()
    ):
        raise BootstrapBlocked("PROJECT_HOME_UNSAFE")
    project_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    project_home = project_home.resolve(strict=True)
    engine_home = _project_directory(project_home, "engine")
    releases = _project_directory(project_home, "engine/releases")
    view = releases / tag
    engine_link = engine_home / "current"
    projects_root = _project_directory(project_home, "projects")
    cache_root = _project_directory(project_home, "bootstrap-cache")

    archive_url = str(release["source_archive_github_release_url"])
    archive_size = int(release["source_archive_size_bytes"])
    archive_filename = f"qingshan-storyclaw-workflow-{tag}.tar.gz"
    archive_path = _cached_asset(
        cache_root,
        filename=archive_filename,
        url=archive_url,
        expected_size=archive_size,
        expected_sha256=str(release["source_archive_sha256"]),
        fetcher=fetcher,
    )
    archive = archive_path.read_bytes()

    _extract_verified_archive(
        archive, view, release_tag=tag, git_commit=commit
    )

    dependency_binding: dict[str, Any] | None = None
    dependency_manifest_path: Path | None = None
    dependency_archive_path: Path | None = None
    if install_deps:
        dependency_binding = _select_dependency_binding(release)
        profile_id = str(dependency_binding["profile_id"])
        dependency_manifest_name, dependency_archive_name = _dependency_asset_names(
            tag, profile_id
        )
        dependency_manifest_path = _cached_asset(
            cache_root,
            filename=dependency_manifest_name,
            url=str(dependency_binding["manifest_url"]),
            expected_size=int(dependency_binding["manifest_size_bytes"]),
            expected_sha256=str(dependency_binding["manifest_sha256"]),
            fetcher=fetcher,
        )
        dependency_archive_path = _cached_asset(
            cache_root,
            filename=dependency_archive_name,
            url=str(dependency_binding["archive_url"]),
            expected_size=int(dependency_binding["archive_size_bytes"]),
            expected_sha256=str(dependency_binding["archive_sha256"]),
            fetcher=fetcher,
        )

    intake_command = [
        sys.executable, str(view / "tools/storyclaw_project_intake.py"), "init",
        "--projects-root", str(projects_root), "--engine-root", str(engine_link),
        "--title", title,
    ]
    if project_id:
        intake_command += ["--project-id", project_id]
    if scope_id:
        intake_command += ["--scope-id", scope_id]
    project = _json_result(_run(intake_command, runner=runner), "PROJECT_INITIALIZATION_FAILED")
    runtime = Path(str(project["private_runtime_root"])).resolve(strict=True)
    transaction_store = runtime / "runtime/storyclaw_storage/workflow/tasks"
    transaction_before = _regular_file_facts(transaction_store)
    smoke_before: dict[str, Any] | None = None
    smoke_after: dict[str, Any] | None = None
    smoke_root = runtime / SMOKE_RECEIPT_ROOT_RELATIVE
    before_snapshot_path = smoke_root / "transactions-before.json"
    after_snapshot_path = smoke_root / "transactions-after.json"
    receipt_path = runtime / BOOTSTRAP_RECEIPT_RELATIVE
    resume_pending_preflight = False
    resume_pending_snapshot = False
    if install_deps:
        pending = None
        if os.path.lexists(receipt_path):
            if receipt_path.is_symlink() or not receipt_path.is_file():
                raise BootstrapBlocked("BOOTSTRAP_RECEIPT_INVALID")
            try:
                pending = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise BootstrapBlocked("BOOTSTRAP_RECEIPT_INVALID") from exc
        pending_status = pending.get("status") if isinstance(pending, dict) else None
        if pending_status in {
            "PREFLIGHT_PENDING", "PREFLIGHT_PASS_PENDING_SNAPSHOT",
        }:
            if (
                pending.get("schema") != RECEIPT_SCHEMA
                or pending.get("release_tag") != tag
                or pending.get("git_commit") != commit
                or pending.get("private_runtime_root") != str(runtime)
                or pending.get("project_engine_link") != str(engine_link)
                or pending.get("project_engine") != str(view)
                or pending.get("provider_posts") != 0
                or pending.get("provider_secret_names_present") != []
            ):
                raise BootstrapBlocked("BOOTSTRAP_RESUME_BINDING_MISMATCH")
            smoke_before = _load_existing_snapshot(
                before_snapshot_path, runtime, label="before"
            )
            if (
                pending.get("transactions_before_snapshot_sha256")
                != smoke_before["sha256"]
                or pending.get("transactions_before_tree_sha256")
                != smoke_before["transactions_tree_sha256"]
            ):
                raise BootstrapBlocked("BOOTSTRAP_RESUME_BINDING_MISMATCH")
            if os.path.lexists(after_snapshot_path):
                raise BootstrapBlocked("BOOTSTRAP_RESUME_AFTER_SNAPSHOT_AMBIGUOUS")
            resume_pending_preflight = pending_status == "PREFLIGHT_PENDING"
            resume_pending_snapshot = (
                pending_status == "PREFLIGHT_PASS_PENDING_SNAPSHOT"
            )
        elif pending is not None:
            raise BootstrapBlocked("BOOTSTRAP_RECEIPT_ALREADY_EXISTS")
        else:
            smoke_before = _run_smoke_snapshot(
                view,
                runtime,
                label="before",
                output=before_snapshot_path,
                runner=runner,
            )
    venv = runtime / "runtime/storyclaw_host/venv"
    install_command = [
        sys.executable, str(view / "tools/storyclaw_install.py"), "install",
        "--engine-root", str(view), "--runtime-root", str(runtime),
        "--release-tag", tag, "--expected-commit", commit,
        "--project-view-root", str(view), "--project-engine-link", str(engine_link),
        "--venv-path", str(venv), "--seal-read-only",
        "--talenthub-release-manifest", str(release["manifest_path"]),
        "--verified-bootstrap-archive", str(archive_path),
    ]
    if install_deps:
        assert dependency_manifest_path is not None
        assert dependency_archive_path is not None
        install_command += [
            "--install-deps",
            "--dependency-manifest", str(dependency_manifest_path),
            "--dependency-archive", str(dependency_archive_path),
        ]
    if resume_pending_preflight or resume_pending_snapshot:
        assert pending is not None
        pending_install_path = Path(str(pending.get("host_install_receipt") or ""))
        pending_install, pending_install_binding = _private_json_binding(
            pending_install_path,
            runtime,
            expected_parent=runtime / INSTALL_RECEIPT_ROOT_RELATIVE,
            schema=INSTALL_RECEIPT_SCHEMA,
            code="HOST_INSTALL_RECEIPT_INVALID",
        )
        if (
            pending.get("host_install_receipt_sha256")
            != pending_install_binding["sha256"]
            or pending.get("host_install_receipt_size_bytes")
            != pending_install_binding["size_bytes"]
        ):
            raise BootstrapBlocked("BOOTSTRAP_RESUME_BINDING_MISMATCH")
        installed = {
            **pending_install,
            "status": "PASS",
            "receipt": {
                "path": pending_install_binding["path"],
                "sha256": pending_install_binding["sha256"],
            },
        }
    else:
        installed = _json_result(
            _run(install_command, runner=runner), "HOST_INSTALL_FAILED"
        )
    transaction_after_install = _regular_file_facts(transaction_store)
    if transaction_after_install != transaction_before:
        raise BootstrapBlocked("BOOTSTRAP_TRANSACTION_STORE_CHANGED")

    try:
        marker = json.loads((runtime / "runtime/project.json").read_text(encoding="utf-8"))
        config = json.loads((runtime / "qingshan.json").read_text(encoding="utf-8"))
        storage = config["storyclaw"]["storage"]
        configured_engine = storage["engine_root"]
        workspace_backing = Path(str(storage["workspace_backing_path"])).resolve(strict=True)
        transaction_backing = Path(str(storage["transactions_backing_path"])).resolve(strict=True)
        if (
            not engine_link.is_symlink()
            or engine_link.resolve(strict=True) != view.resolve(strict=True)
            or Path(str(marker.get("engine_root") or "")) != engine_link
            or Path(str(configured_engine)) != engine_link
            or Path(str(storage.get("workspace_mount_target") or ""))
               != engine_link / "workflow/nalu"
            or Path(str(storage.get("transactions_mount_target") or ""))
               != engine_link / "workflow/tasks"
            or not (view / "workflow/nalu").is_symlink()
            or not (view / "workflow/tasks").is_symlink()
            or (view / "workflow/nalu").resolve(strict=True) != workspace_backing
            or (view / "workflow/tasks").resolve(strict=True) != transaction_backing
            or not workspace_backing.is_relative_to(runtime)
            or not transaction_backing.is_relative_to(runtime)
            or installed.get("release_baseline", {}).get("status") != "PASS"
        ):
            raise BootstrapBlocked("PROJECT_ENGINE_LINK_BINDING_MISMATCH")
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise BootstrapBlocked("PROJECT_ENGINE_LINK_BINDING_MISMATCH") from exc

    install_reference = installed.get("receipt")
    if not isinstance(install_reference, dict):
        raise BootstrapBlocked("HOST_INSTALL_RECEIPT_REFERENCE_INVALID")
    install_receipt_path = Path(str(install_reference.get("path") or ""))
    _install_receipt, install_binding = _private_json_binding(
        install_receipt_path,
        runtime,
        expected_parent=runtime / INSTALL_RECEIPT_ROOT_RELATIVE,
        schema=INSTALL_RECEIPT_SCHEMA,
        code="HOST_INSTALL_RECEIPT_INVALID",
    )
    if install_reference.get("sha256") != install_binding["sha256"]:
        raise BootstrapBlocked("HOST_INSTALL_RECEIPT_DIGEST_MISMATCH")

    receipt = {
        "schema": RECEIPT_SCHEMA,
        "status": "PASS",
        "release_tag": tag,
        "git_commit": commit,
        "release_sequence": release["release_sequence"],
        "source_archive": str(archive_path),
        "source_archive_size_bytes": archive_size,
        "source_archive_sha256": release["source_archive_sha256"],
        "talenthub_release_manifest": release["manifest_path"],
        "dependency_profile_id": (
            dependency_binding["profile_id"] if dependency_binding else None
        ),
        "dependency_manifest_sha256": (
            dependency_binding["manifest_sha256"] if dependency_binding else None
        ),
        "dependency_archive_sha256": (
            dependency_binding["archive_sha256"] if dependency_binding else None
        ),
        "private_runtime_root": str(runtime),
        "project_engine_link": str(engine_link),
        "project_engine": str(view),
        "host_install_receipt": install_binding["path"],
        "host_install_receipt_size_bytes": install_binding["size_bytes"],
        "host_install_receipt_sha256": install_binding["sha256"],
        "provider_posts": 0,
        "provider_secret_names_present": [],
        "transaction_file_count_before": len(transaction_before),
        "transaction_file_count_after": len(transaction_after_install),
        "transaction_file_delta": 0,
        "registry_clean_install_smoke_status": (
            "PREFLIGHT_PENDING" if install_deps else "NOT_RUN_LOCAL_SKIP_DEPS"
        ),
    }
    if smoke_before is not None:
        receipt.update({
            "transactions_before_snapshot": smoke_before["path"],
            "transactions_before_snapshot_sha256": smoke_before["sha256"],
            "transactions_before_tree_sha256": smoke_before[
                "transactions_tree_sha256"
            ],
        })
    # The adapter must authenticate an archive view during the first preflight.
    # Publish this exact package/archive/host-install binding first; a clean
    # smoke cannot pass until the same receipt is finalized and the after
    # observation binds its final digest.
    if install_deps and not resume_pending_snapshot:
        receipt["status"] = "PREFLIGHT_PENDING"
        _atomic_bytes(
            receipt_path,
            (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode(),
        )
    elif not install_deps:
        _atomic_bytes(
            receipt_path,
            (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode(),
        )

    preflight_binding: dict[str, Any] | None = None
    if install_deps:
        selector_python = runtime / VENV_SELECTOR_RELATIVE / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        try:
            resolved_python = selector_python.resolve(strict=True)
        except OSError as exc:
            raise BootstrapBlocked("VENV_SELECTOR_PYTHON_INVALID") from exc
        if not resolved_python.is_file() or not resolved_python.is_relative_to(runtime):
            raise BootstrapBlocked("VENV_SELECTOR_PYTHON_INVALID")
        preflight_path = runtime / SMOKE_PREFLIGHT_RELATIVE
        if resume_pending_snapshot:
            assert pending is not None
            preflight, preflight_binding = _private_json_binding(
                preflight_path,
                runtime,
                expected_parent=smoke_root,
                schema=PREFLIGHT_SCHEMA,
                code="PREFLIGHT_RECEIPT_INVALID",
            )
            if (
                pending.get("preflight_receipt") != preflight_binding["path"]
                or pending.get("preflight_receipt_sha256")
                != preflight_binding["sha256"]
                or pending.get("preflight_receipt_size_bytes")
                != preflight_binding["size_bytes"]
            ):
                raise BootstrapBlocked("BOOTSTRAP_RESUME_BINDING_MISMATCH")
        else:
            preflight_command = [
                str(selector_python),
                str(view / "tools/storyclaw_nalu_runtime.py"),
                "preflight",
            ]
            preflight = _json_result(
                _run(
                    preflight_command,
                    runner=runner,
                    extra_env={
                        "NALU_ENGINE_ROOT": str(engine_link),
                        "NALU_RUNTIME_ROOT": str(runtime),
                        "NALU_VENV_PYTHON": str(selector_python),
                    },
                ),
                "PREFLIGHT_FAILED",
            )
        _validate_preflight_result(
            preflight,
            engine=view,
            runtime=runtime,
            marker=marker,
            git_commit=commit,
        )
        if not resume_pending_snapshot:
            _atomic_bytes(
                preflight_path,
                (json.dumps(preflight, ensure_ascii=False, indent=2) + "\n").encode(),
            )
            _preflight, preflight_binding = _private_json_binding(
                preflight_path,
                runtime,
                expected_parent=smoke_root,
                schema=PREFLIGHT_SCHEMA,
                code="PREFLIGHT_RECEIPT_INVALID",
            )
        assert preflight_binding is not None
        transaction_after_preflight = _regular_file_facts(transaction_store)
        if transaction_after_preflight != transaction_before:
            raise BootstrapBlocked("BOOTSTRAP_TRANSACTION_STORE_CHANGED")
        receipt.update({
            "status": "PREFLIGHT_PASS_PENDING_SNAPSHOT",
            "registry_clean_install_smoke_status": "AFTER_SNAPSHOT_PENDING",
            "preflight_receipt": preflight_binding["path"],
            "preflight_receipt_size_bytes": preflight_binding["size_bytes"],
            "preflight_receipt_sha256": preflight_binding["sha256"],
            "transaction_file_count_after": len(transaction_after_preflight),
        })
        _atomic_bytes(
            receipt_path,
            (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode(),
        )
        provisional_receipt_sha256 = _sha256(receipt_path)
        smoke_after = _run_smoke_snapshot(
            view,
            runtime,
            label="after",
            output=after_snapshot_path,
            runner=runner,
            prior_snapshot=before_snapshot_path,
        )
        if (
            smoke_before is None
            or smoke_after["transactions_tree_sha256"]
            != smoke_before["transactions_tree_sha256"]
        ):
            raise BootstrapBlocked("BOOTSTRAP_TRANSACTION_STORE_CHANGED")
        receipt.update({
            "status": "PASS",
            "registry_clean_install_smoke_status": "SNAPSHOTS_PASS",
            "snapshot_bound_bootstrap_receipt_sha256": (
                provisional_receipt_sha256
            ),
            "transactions_after_snapshot": smoke_after["path"],
            "transactions_after_snapshot_sha256": smoke_after["sha256"],
            "transactions_after_tree_sha256": smoke_after[
                "transactions_tree_sha256"
            ],
        })
        _atomic_bytes(
            receipt_path,
            (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode(),
        )

    result = {**receipt, "receipt": str(receipt_path)}
    if smoke_after is not None:
        result.update({
            "registry_clean_install_smoke_status": "SNAPSHOTS_PASS",
            "transactions_after_snapshot": smoke_after["path"],
            "transactions_after_snapshot_sha256": smoke_after["sha256"],
            "transactions_after_tree_sha256": smoke_after[
                "transactions_tree_sha256"
            ],
        })
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--project-home", type=Path, required=True)
    parser.add_argument("--title", default="Untitled short drama")
    parser.add_argument("--project-id")
    parser.add_argument("--scope-id")
    parser.add_argument("--skip-deps", action="store_true", help="local validation only")
    args = parser.parse_args(argv)
    try:
        result = bootstrap_project(
            args.workspace, args.project_home, title=args.title,
            project_id=args.project_id, scope_id=args.scope_id,
            install_deps=not args.skip_deps,
        )
    except BootstrapBlocked as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
