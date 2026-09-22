#!/usr/bin/env python3
"""Install a tagged NALU checkout on a StoryClaw host without private-data drift.

The installer deliberately has a very small write surface.  It may create the
two private workflow backings, replace an absent or empty engine target with an
exact symlink, create a private virtual environment when explicitly requested,
and write installation receipts below the private runtime root.  It never
reads or writes project sources, episode media, reviews, ledgers, or secrets.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Sequence

try:
    from tools.storyclaw_release_surface import (
        TALENTHUB_MANAGED_EXACT,
        TALENTHUB_MANAGED_FILE_PREFIXES,
        TALENTHUB_MANAGED_TREE_ROOTS,
    )
    from tools import storyclaw_upgrade_transaction as _upgrade_transaction
    from tools import storyclaw_dependency_bundle as _dependency_bundle
except ModuleNotFoundError:  # direct ``python tools/...`` execution
    from storyclaw_release_surface import (  # type: ignore[no-redef]
        TALENTHUB_MANAGED_EXACT,
        TALENTHUB_MANAGED_FILE_PREFIXES,
        TALENTHUB_MANAGED_TREE_ROOTS,
    )
    import storyclaw_upgrade_transaction as _upgrade_transaction  # type: ignore[no-redef]
    import storyclaw_dependency_bundle as _dependency_bundle  # type: ignore[no-redef]


SCHEMA = "storyclaw.nalu.host_install.v1"
ERROR_SCHEMA = "storyclaw.nalu.host_install_error.v1"
RECEIPT_SCHEMA = "storyclaw.nalu.host_install_receipt.v1"
UPGRADE_SCHEMA = "storyclaw.nalu.release_channel.v1"
UPGRADE_RECEIPT_SCHEMA = "storyclaw.nalu.engine_upgrade_receipt.v1"
ARCHIVE_RELEASE_SCHEMA = "qingshan.storyclaw.release.v1"
TALENTHUB_RELEASE_SCHEMA = "qingshan.storyclaw.talenthub.release.v1"
INSTALLER_VERSION = "1.1.0"
ENGINE_ONLY = "ENGINE_ONLY"
PACKAGE_REQUIRED = "TALENTHUB_PACKAGE_REQUIRED"
AGENT_ID = "ai-drama-factory"
SKILL_NAME = "qingshan-nalu"
STABLE_CHANNEL_RELEASE_TAG = "storyclaw-stable-channel"
RELEASE_SIGNING_PUBLIC_KEY_SHA256 = "d27484512874011dc5e894b602d6a42ca846a4e048688d32389acf7852d3646f"

ENGINE_MARKERS = (
    "pyproject.toml",
    "lines/nalu/runtime/tools/nalu_pipeline.py",
)
WIRE_SPECS = (
    (
        "episode_workspace",
        "workflow/nalu",
        "runtime/storyclaw_storage/workflow/nalu",
    ),
    (
        "transaction_store",
        "workflow/tasks",
        "runtime/storyclaw_storage/workflow/tasks",
    ),
)
DEFAULT_VENV_RELATIVE = "runtime/storyclaw_host/venv"
VENV_SELECTOR_RELATIVE = Path("runtime/storyclaw_host/current-venv")
RECEIPT_ROOT_RELATIVE = "runtime/receipts/storyclaw_host_install"
UPGRADE_RECEIPT_ROOT_RELATIVE = "runtime/receipts/storyclaw_engine_upgrades"
UPGRADE_BARRIER_RELATIVE = Path("runtime/storyclaw_locks/__engine_upgrade__.lock")
DISCOVERY_STATE_RELATIVE = Path("runtime/storyclaw_release_discovery/trusted_state.json")
CURRENT_RELEASE_STATE_RELATIVE = Path("runtime/storyclaw_host/current-release.json")
DISCOVERY_RESULT_SCHEMA = "storyclaw.nalu.release_discovery.v1"
CURRENT_RELEASE_STATE_SCHEMA = "storyclaw.nalu.current_release.v1"
_COMMIT_RE = re.compile(r"[0-9a-fA-F]{40,64}\Z")
_SAFE_TAG_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/+\-]{0,199}\Z")
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}\Z")
_SAFE_RELEASE_DIR_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")

FORBIDDEN_ARCHIVE_PREFIXES = (
    "sources/",
    "deliverables/",
    "runtime/",
    "working_assets/",
    "workflow/nalu/",
    "workflow/tasks/",
)


class InstallBlocked(RuntimeError):
    """A fail-closed installation or verification refusal."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}:{detail}" if detail else code)


@contextmanager
def _upgrade_barrier(runtime: Path):
    """Exclude production runs for the full safety-check/switch transaction."""
    path = runtime / UPGRADE_BARRIER_RELATIVE
    _mkdir_private(path.parent, runtime)
    with path.open("a+b") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise InstallBlocked("ENGINE_UPGRADE_LOCKED", str(path)) from exc
        try:
            yield path
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _resolve_directory(path: Path, label: str) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise InstallBlocked(f"{label}_NOT_FOUND", str(path)) from exc
    if not resolved.is_dir():
        raise InstallBlocked(f"{label}_NOT_DIRECTORY", str(resolved))
    return resolved


def _validate_roots(
    engine_root: Path,
    runtime_root: Path,
    *,
    require_git_checkout: bool = True,
) -> tuple[Path, Path]:
    engine = _resolve_directory(engine_root, "ENGINE_ROOT")
    runtime = _resolve_directory(runtime_root, "RUNTIME_ROOT")
    if engine == runtime or _inside(engine, runtime) or _inside(runtime, engine):
        raise InstallBlocked("ENGINE_RUNTIME_OVERLAP", f"{engine} :: {runtime}")
    if require_git_checkout and not (engine / ".git").exists():
        raise InstallBlocked("ENGINE_NOT_GIT_CHECKOUT", str(engine))
    if not require_git_checkout and not (
        (engine / ".git").exists() or (engine / "RELEASE_MANIFEST.json").is_file()
    ):
        raise InstallBlocked("ENGINE_PROVENANCE_MISSING", str(engine))
    missing = [relative for relative in ENGINE_MARKERS if not (engine / relative).is_file()]
    if missing:
        raise InstallBlocked("ENGINE_MARKERS_MISSING", ",".join(missing))
    workflow = engine / "workflow"
    if not workflow.is_dir() or workflow.is_symlink():
        raise InstallBlocked("ENGINE_WORKFLOW_DIRECTORY_INVALID", str(workflow))
    if not _inside(workflow.resolve(strict=True), engine):
        raise InstallBlocked("ENGINE_WORKFLOW_ESCAPES_CHECKOUT", str(workflow))
    return engine, runtime


def _git(
    engine: Path,
    args: Sequence[str],
    *,
    text: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess[Any]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    result = subprocess.run(
        ["git", "--no-optional-locks", "-C", str(engine), *args],
        check=False,
        capture_output=True,
        text=text,
        env=environment,
    )
    if check and result.returncode != 0:
        raise InstallBlocked("GIT_COMMAND_FAILED", " ".join(args))
    return result


def _checked_tag(value: str) -> str:
    tag = str(value or "").strip()
    if (
        not _SAFE_TAG_RE.fullmatch(tag)
        or ".." in tag
        or "@{" in tag
        or tag.endswith(("/", ".", ".lock"))
        or tag.startswith("-")
    ):
        raise InstallBlocked("RELEASE_TAG_INVALID", tag)
    return tag


def _git_facts(
    engine: Path,
    *,
    release_tag: str | None = None,
    expected_commit: str | None = None,
    require_clean: bool = False,
    require_tag: bool = False,
) -> dict[str, Any]:
    head = _git(engine, ["rev-parse", "--verify", "HEAD"]).stdout.strip().lower()
    if not _COMMIT_RE.fullmatch(head):
        raise InstallBlocked("ENGINE_HEAD_INVALID", head)
    status_lines = [
        line for line in _git(
            engine, ["status", "--porcelain=v1", "--untracked-files=all"]
        ).stdout.splitlines() if line
    ]
    clean = not status_lines
    all_tags = sorted(
        line.strip()
        for line in _git(engine, ["tag", "--points-at", "HEAD"]).stdout.splitlines()
        if line.strip()
    )
    tags = [tag for tag in all_tags if tag != STABLE_CHANNEL_RELEASE_TAG]
    facts: dict[str, Any] = {
        "root": str(engine),
        "head_commit": head,
        "clean": clean,
        "dirty_entry_count": len(status_lines),
        "tags_at_head": tags,
        "non_engine_tags_at_head": [
            tag for tag in all_tags if tag == STABLE_CHANNEL_RELEASE_TAG
        ],
    }
    if require_clean and not clean:
        raise InstallBlocked("ENGINE_WORKTREE_NOT_CLEAN", str(len(status_lines)))
    if expected_commit:
        expected = expected_commit.strip().lower()
        if not _COMMIT_RE.fullmatch(expected):
            raise InstallBlocked("EXPECTED_COMMIT_INVALID", expected_commit)
        if head != expected:
            raise InstallBlocked("ENGINE_COMMIT_MISMATCH", f"expected={expected},actual={head}")
        facts["expected_commit"] = expected
    if release_tag:
        tag = _checked_tag(release_tag)
        tag_commit_result = _git(
            engine,
            ["rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}"],
            check=False,
        )
        if tag_commit_result.returncode != 0:
            raise InstallBlocked("RELEASE_TAG_NOT_FOUND", tag)
        tag_commit = tag_commit_result.stdout.strip().lower()
        if tag_commit != head:
            raise InstallBlocked(
                "RELEASE_TAG_HEAD_MISMATCH", f"tag={tag},tag_commit={tag_commit},head={head}"
            )
        facts.update({"release_tag": tag, "release_tag_commit": tag_commit})
    elif require_tag:
        raise InstallBlocked("RELEASE_TAG_REQUIRED")
    return facts


def _archive_engine_facts(
    engine: Path,
    runtime: Path,
    *,
    release_tag: str | None,
    expected_commit: str | None,
    require_tag: bool,
) -> dict[str, Any]:
    manifest_path = engine / "RELEASE_MANIFEST.json"
    try:
        release = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallBlocked("ARCHIVE_ENGINE_MANIFEST_INVALID", str(manifest_path)) from exc
    if not isinstance(release, dict) or release.get("schema") != ARCHIVE_RELEASE_SCHEMA:
        raise InstallBlocked("ARCHIVE_ENGINE_MANIFEST_INVALID", str(manifest_path))
    tag = _checked_tag(str(release.get("release_tag") or ""))
    commit = str(release.get("git_commit") or "").strip().lower()
    if not _COMMIT_RE.fullmatch(commit):
        raise InstallBlocked("ARCHIVE_ENGINE_COMMIT_INVALID", commit)
    if require_tag and not release_tag:
        raise InstallBlocked("RELEASE_TAG_REQUIRED")
    if release_tag and _checked_tag(release_tag) != tag:
        raise InstallBlocked("RELEASE_TAG_HEAD_MISMATCH", f"expected={release_tag},actual={tag}")
    if expected_commit:
        expected = expected_commit.strip().lower()
        if not _COMMIT_RE.fullmatch(expected):
            raise InstallBlocked("EXPECTED_COMMIT_INVALID", expected_commit)
        if expected != commit:
            raise InstallBlocked("ENGINE_COMMIT_MISMATCH", f"expected={expected},actual={commit}")
    receipt_path = runtime / UPGRADE_RECEIPT_ROOT_RELATIVE / f"{commit}.json"
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallBlocked("ARCHIVE_ENGINE_RECEIPT_INVALID", str(receipt_path)) from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != UPGRADE_RECEIPT_SCHEMA
        or receipt.get("status") != "PASS"
        or receipt.get("git_commit") != commit
        or receipt.get("release_tag") != tag
        or Path(str(receipt.get("current_engine") or "")).resolve(strict=False) != engine
    ):
        raise InstallBlocked("ARCHIVE_ENGINE_RECEIPT_MISMATCH", str(receipt_path))
    actual_tree = _tree_digest(engine)
    if receipt.get("candidate_tree_sha256") != actual_tree:
        raise InstallBlocked("ARCHIVE_ENGINE_TREE_MISMATCH", str(engine))
    return {
        "root": str(engine),
        "head_commit": commit,
        "clean": True,
        "dirty_entry_count": 0,
        "tags_at_head": [tag],
        "release_tag": tag,
        "release_tag_commit": commit,
        "checkout_kind": "VERIFIED_RELEASE_ARCHIVE",
        "immutable_tree_verified": True,
        "upgrade_receipt": str(receipt_path),
    }


def _bootstrap_archive_facts(
    engine: Path,
    archive: Path,
    package: Mapping[str, Any],
    *,
    release_tag: str,
    expected_commit: str,
) -> dict[str, Any]:
    """Authorize a first install from the package-bound immutable archive."""
    if archive.is_symlink() or not archive.is_file():
        raise InstallBlocked("BOOTSTRAP_ARCHIVE_INVALID", str(archive))
    if (
        archive.stat().st_size != package["source_archive_size_bytes"]
        or _sha256_file(archive) != package["source_archive_sha256"]
    ):
        raise InstallBlocked("BOOTSTRAP_ARCHIVE_BINDING_MISMATCH", str(archive))
    try:
        release = json.loads((engine / "RELEASE_MANIFEST.json").read_text(encoding="utf-8"))
        inventory = json.loads(
            (engine / "configs/DEPLOYMENT_CODE_SHA256.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallBlocked("BOOTSTRAP_ARCHIVE_ENGINE_INVALID", str(engine)) from exc
    if (
        release.get("schema") != ARCHIVE_RELEASE_SCHEMA
        or release.get("release_tag") != release_tag
        or release.get("git_commit") != expected_commit
        or release.get("private_runtime_included") is not False
        or release.get("credentials_included") is not False
    ):
        raise InstallBlocked("BOOTSTRAP_ARCHIVE_RELEASE_MANIFEST_MISMATCH")
    rows = inventory.get("files") if isinstance(inventory, dict) else None
    if (
        not isinstance(rows, list)
        or not rows
        or inventory.get("file_count") != len(rows)
    ):
        raise InstallBlocked("BOOTSTRAP_ARCHIVE_INVENTORY_INVALID")
    seen: set[str] = set()
    for row in rows:
        relative = str(row.get("path") or "") if isinstance(row, dict) else ""
        digest = str(row.get("sha256") or "") if isinstance(row, dict) else ""
        pure = PurePosixPath(relative)
        target = engine / Path(*pure.parts)
        if (
            not relative
            or pure.is_absolute()
            or ".." in pure.parts
            or relative in seen
            or not _SHA256_RE.fullmatch(digest)
            or target.is_symlink()
            or not target.is_file()
            or not _inside(target.resolve(strict=True), engine)
            or _sha256_file(target) != digest
        ):
            raise InstallBlocked("BOOTSTRAP_ARCHIVE_INVENTORY_MISMATCH", relative)
        seen.add(relative)
    return {
        "root": str(engine),
        "head_commit": expected_commit,
        "clean": True,
        "dirty_entry_count": 0,
        "tags_at_head": [release_tag],
        "release_tag": release_tag,
        "release_tag_commit": expected_commit,
        "checkout_kind": "PACKAGE_VERIFIED_RELEASE_ARCHIVE",
        "immutable_tree_verified": True,
        "source_archive_sha256": package["source_archive_sha256"],
    }


def _engine_facts(
    engine: Path,
    runtime: Path,
    *,
    release_tag: str | None,
    expected_commit: str | None,
    require_clean: bool,
    require_tag: bool,
) -> dict[str, Any]:
    if (engine / ".git").exists():
        facts = _git_facts(
            engine,
            release_tag=release_tag,
            expected_commit=expected_commit,
            require_clean=require_clean,
            require_tag=require_tag,
        )
        facts["checkout_kind"] = "GIT_CHECKOUT"
        return facts
    return _archive_engine_facts(
        engine,
        runtime,
        release_tag=release_tag,
        expected_commit=expected_commit,
        require_tag=require_tag,
    )


def _mkdir_private(path: Path, runtime: Path) -> None:
    if not _inside(path, runtime):
        raise InstallBlocked("PRIVATE_PATH_ESCAPES_RUNTIME", str(path))
    relative = path.relative_to(runtime)
    current = runtime
    for part in relative.parts:
        current = current / part
        if os.path.lexists(current):
            if current.is_symlink() or not current.is_dir():
                raise InstallBlocked("PRIVATE_DIRECTORY_INVALID", str(current))
        else:
            current.mkdir(mode=0o700)


def _backing_paths(engine: Path, runtime: Path, *, create: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, target_relative, backing_relative in WIRE_SPECS:
        target = engine / target_relative
        backing = runtime / backing_relative
        if create:
            _mkdir_private(backing, runtime)
        rows.append({
            "name": name,
            "target": target,
            "target_relative": target_relative,
            "backing": backing,
            "backing_relative": backing_relative,
        })
    return rows


def _target_state(target: Path, backing: Path) -> dict[str, Any]:
    if not os.path.lexists(target):
        return {"state": "ABSENT", "wired": False}
    if target.is_symlink():
        raw = os.readlink(target)
        try:
            resolved = target.resolve(strict=True)
        except OSError:
            return {"state": "BROKEN_SYMLINK", "wired": False, "symlink": raw}
        exact = resolved == backing.resolve(strict=True)
        return {
            "state": "EXACT_SYMLINK" if exact else "WRONG_SYMLINK",
            "wired": exact,
            "symlink": raw,
            "resolved": str(resolved),
        }
    if target.is_dir():
        try:
            empty = next(target.iterdir(), None) is None
        except OSError as exc:
            raise InstallBlocked("ENGINE_TARGET_UNREADABLE", str(target)) from exc
        return {"state": "EMPTY_DIRECTORY" if empty else "NONEMPTY_DIRECTORY", "wired": False}
    return {"state": "NON_DIRECTORY", "wired": False}


def _wire_target(target: Path, backing: Path) -> str:
    state = _target_state(target, backing)["state"]
    if state == "EXACT_SYMLINK":
        return "ALREADY_WIRED"
    if state not in {"ABSENT", "EMPTY_DIRECTORY"}:
        raise InstallBlocked("ENGINE_TARGET_NOT_SAFE_TO_WIRE", f"{target}:{state}")

    temporary = target.parent / f".{target.name}.storyclaw-link-{secrets.token_hex(6)}"
    os.symlink(str(backing), temporary)
    removed_empty = False
    try:
        if state == "EMPTY_DIRECTORY":
            target.rmdir()
            removed_empty = True
        os.replace(temporary, target)
    except Exception:
        if os.path.lexists(temporary):
            temporary.unlink()
        if removed_empty and not os.path.lexists(target):
            target.mkdir(mode=0o755)
        raise
    return "WIRED"


def _probe_writable_flock(path: Path) -> dict[str, Any]:
    probe = path / f".storyclaw-install-probe-{os.getpid()}-{secrets.token_hex(4)}"
    handle = None
    try:
        handle = probe.open("x+b")
        handle.write(b"storyclaw-nalu-storage-probe\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except (OSError, BlockingIOError) as exc:
        raise InstallBlocked("PRIVATE_STORAGE_PROBE_FAILED", str(path)) from exc
    finally:
        if handle is not None:
            handle.close()
        try:
            probe.unlink()
        except FileNotFoundError:
            pass
    return {"write": "PASS", "fsync": "PASS", "flock_nonblocking": "PASS"}


def _wire_report(rows: Iterable[Mapping[str, Any]], *, probe: bool) -> list[dict[str, Any]]:
    report: list[dict[str, Any]] = []
    for row in rows:
        target = Path(row["target"])
        backing = Path(row["backing"])
        if not backing.is_dir() or backing.is_symlink():
            raise InstallBlocked("PRIVATE_BACKING_INVALID", str(backing))
        state = _target_state(target, backing)
        if not state["wired"]:
            raise InstallBlocked("ENGINE_TARGET_NOT_WIRED", f"{target}:{state['state']}")
        try:
            same_storage = os.path.samefile(target, backing)
        except OSError as exc:
            raise InstallBlocked("ENGINE_TARGET_SAMEFILE_CHECK_FAILED", str(target)) from exc
        if not same_storage:
            raise InstallBlocked("ENGINE_TARGET_BACKING_MISMATCH", str(target))
        item: dict[str, Any] = {
            "name": row["name"],
            "target": str(target),
            "backing": str(backing),
            "state": state["state"],
            "same_storage_object": True,
        }
        if probe:
            item["storage_probe"] = _probe_writable_flock(target)
        report.append(item)
    return report


def _tracked_paths(engine: Path) -> list[Path]:
    result = _git(engine, ["ls-files", "-z"], text=False)
    values: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative_text = os.fsdecode(raw)
        relative = Path(relative_text)
        if relative.is_absolute() or ".." in relative.parts:
            raise InstallBlocked("TRACKED_PATH_INVALID", relative_text)
        path = engine / relative
        if not _inside(path, engine):
            raise InstallBlocked("TRACKED_PATH_ESCAPES_ENGINE", relative_text)
        values.append(path)
    if not values:
        raise InstallBlocked("ENGINE_TRACKED_FILES_EMPTY")
    return values


def _public_code_paths(engine: Path) -> tuple[list[Path], list[Path]]:
    files: list[Path] = []
    directories = {engine}
    for path in _tracked_paths(engine):
        if not os.path.lexists(path):
            raise InstallBlocked("TRACKED_FILE_MISSING", str(path.relative_to(engine)))
        if not path.is_symlink():
            files.append(path)
        parent = path.parent
        while parent != engine:
            directories.add(parent)
            parent = parent.parent
        directories.add(engine)
    return files, sorted(directories, key=lambda value: len(value.parts), reverse=True)


def _strip_write_bits(path: Path) -> None:
    if path.is_symlink():
        return
    current = stat.S_IMODE(path.stat().st_mode)
    desired = current & ~0o222
    if desired != current:
        os.chmod(path, desired)


def _require_engine_root_write_blocked(engine: Path) -> None:
    probe = engine / f".storyclaw-readonly-probe-{os.getpid()}-{secrets.token_hex(4)}"
    try:
        with probe.open("xb") as handle:
            handle.write(b"readonly-probe\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        if exc.errno in {1, 13, 30}:  # EPERM, EACCES, EROFS
            return
        raise InstallBlocked("ENGINE_READONLY_PROBE_FAILED", str(engine)) from exc
    else:
        probe.unlink(missing_ok=True)
        raise InstallBlocked("ENGINE_SEAL_INEFFECTIVE", str(engine))


def seal_public_engine(engine: Path) -> dict[str, Any]:
    """Strip write bits from Git-tracked public code and its parent directories."""
    files, directories = _public_code_paths(engine)
    for path in files:
        _strip_write_bits(path)
    for path in directories:
        _strip_write_bits(path)
    report = _sealed_report(engine)
    if not report["sealed"]:
        raise InstallBlocked("ENGINE_SEAL_FAILED", str(report["writable_path_count"]))
    _require_engine_root_write_blocked(engine)
    report["root_write_probe"] = "BLOCKED_AS_REQUIRED"
    return report


def _sealed_report(engine: Path) -> dict[str, Any]:
    files, directories = _public_code_paths(engine)
    writable: list[str] = []
    for path in [*files, *directories]:
        if path.is_symlink():
            continue
        if stat.S_IMODE(path.stat().st_mode) & 0o222:
            try:
                value = str(path.relative_to(engine)) or "."
            except ValueError:
                value = str(path)
            writable.append(value if value != "." else ".")
    return {
        "sealed": not writable,
        "tracked_file_count": len(files),
        "tracked_parent_directory_count": len(directories),
        "writable_path_count": len(writable),
        "writable_paths_sample": sorted(set(writable))[:20],
    }


def _extracted_sealed_report(engine: Path) -> dict[str, Any]:
    files: list[Path] = []
    directories: list[Path] = []
    for root, _names, filenames in os.walk(engine, topdown=False, followlinks=False):
        root_path = Path(root)
        files.extend(
            root_path / filename
            for filename in filenames
            if not (root_path / filename).is_symlink()
        )
        directories.append(root_path)
    writable = [
        str(path.relative_to(engine)) if path != engine else "."
        for path in [*files, *directories]
        if stat.S_IMODE(path.stat().st_mode) & 0o222
    ]
    return {
        "sealed": not writable,
        "tracked_file_count": len(files),
        "tracked_parent_directory_count": len(directories),
        "writable_path_count": len(writable),
        "writable_paths_sample": sorted(set(writable))[:20],
        "scope": "verified_release_archive",
    }


def _engine_seal_report(engine: Path) -> dict[str, Any]:
    return _sealed_report(engine) if (engine / ".git").exists() else _extracted_sealed_report(engine)


def _checked_private_venv(path: Path, runtime: Path, engine: Path) -> Path:
    runtime = runtime.resolve(strict=True)
    engine = engine.resolve(strict=True)
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = runtime / candidate
    resolved = candidate.resolve(strict=False)
    if not _inside(resolved, runtime) or _inside(resolved, engine):
        raise InstallBlocked("VENV_MUST_BE_PRIVATE_RUNTIME_PATH", str(resolved))
    return resolved


def install_dependencies(
    engine: Path,
    runtime: Path,
    *,
    venv_path: Path | None = None,
    python_executable: str = sys.executable,
    dependency_manifest: Path | None = None,
    dependency_archive: Path | None = None,
    release_tag: str | None = None,
    git_commit: str | None = None,
    release_sequence: int | None = None,
    expected_binding: Mapping[str, Any] | None = None,
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
) -> dict[str, Any]:
    """Create a private venv from one release-bound offline wheel bundle."""
    engine = engine.resolve(strict=True)
    runtime = runtime.resolve(strict=True)
    requested = venv_path or (runtime / DEFAULT_VENV_RELATIVE)
    venv = _checked_private_venv(requested, runtime, engine)
    if (
        dependency_manifest is None
        or dependency_archive is None
        or release_tag is None
        or git_commit is None
        or release_sequence is None
        or expected_binding is None
    ):
        raise InstallBlocked(
            "DEPENDENCY_BUNDLE_REQUIRED",
            "a release-bound manifest, archive, identity and profile binding are required",
        )
    try:
        controller_facts = _dependency_bundle.probe_interpreter(
            Path(python_executable), runner=runner
        )
        profile = _dependency_bundle.select_profile(controller_facts)
    except _dependency_bundle.DependencyBundleBlocked as exc:
        raise InstallBlocked(exc.code, exc.detail) from exc
    selected_binding = (
        expected_binding
        if expected_binding.get("profile_id") is not None
        else expected_binding.get(profile.profile_id)
    )
    if not isinstance(selected_binding, Mapping) or selected_binding.get("profile_id") != profile.profile_id:
        raise InstallBlocked(
            "DEPENDENCY_PROFILE_BINDING_MISMATCH",
            f"selected={profile.profile_id}",
        )
    expected_binding = selected_binding
    try:
        manifest_path = dependency_manifest.expanduser().resolve(strict=True)
        manifest_raw = manifest_path.read_bytes()
    except OSError as exc:
        raise InstallBlocked("DEPENDENCY_MANIFEST_NOT_FOUND", str(dependency_manifest)) from exc
    if (
        len(manifest_raw) != expected_binding.get("manifest_size_bytes")
        or hashlib.sha256(manifest_raw).hexdigest()
        != expected_binding.get("manifest_sha256")
    ):
        raise InstallBlocked("DEPENDENCY_MANIFEST_BINDING_MISMATCH", str(manifest_path))
    try:
        manifest_payload = json.loads(manifest_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallBlocked("DEPENDENCY_MANIFEST_JSON_INVALID", str(manifest_path)) from exc
    try:
        manifest = _dependency_bundle.validate_manifest(
            manifest_payload,
            release_tag=release_tag,
            git_commit=git_commit,
            release_sequence=release_sequence,
            expected_profile_id=profile.profile_id,
        )
    except _dependency_bundle.DependencyBundleBlocked as exc:
        raise InstallBlocked(exc.code, exc.detail) from exc
    archive_row = manifest["archive"]
    if (
        archive_row.get("url") != expected_binding.get("archive_url")
        or archive_row.get("size_bytes") != expected_binding.get("archive_size_bytes")
        or archive_row.get("sha256") != expected_binding.get("archive_sha256")
    ):
        raise InstallBlocked("DEPENDENCY_ARCHIVE_BINDING_MISMATCH")
    _mkdir_private(venv.parent, runtime)
    if os.path.lexists(venv) and (venv.is_symlink() or not venv.is_dir()):
        raise InstallBlocked("VENV_PATH_INVALID", str(venv))
    created = False
    if not venv.exists():
        # Keep the executable inside the private venv: default POSIX venv
        # symlinks point outside it and fail the selector containment check.
        result = runner([python_executable, "-m", "venv", "--copies", str(venv)], check=False)
        if result.returncode != 0:
            raise InstallBlocked("VENV_CREATE_FAILED", str(result.returncode))
        created = True
    venv_python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not venv_python.is_file():
        raise InstallBlocked("VENV_PYTHON_MISSING", str(venv_python))
    try:
        try:
            venv_facts = _dependency_bundle.probe_interpreter(venv_python, runner=runner)
            if _dependency_bundle.select_profile(venv_facts).profile_id != profile.profile_id:
                raise InstallBlocked("DEPENDENCY_VENV_PROFILE_MISMATCH")
        except _dependency_bundle.DependencyBundleBlocked as exc:
            raise InstallBlocked(exc.code, exc.detail) from exc
        staging_parent = runtime / "runtime/storyclaw_host/dependency_staging"
        _mkdir_private(staging_parent, runtime)
        with tempfile.TemporaryDirectory(prefix=f"{profile.profile_id}-", dir=staging_parent) as temp:
            try:
                extracted = _dependency_bundle.extract_verified_bundle(
                    manifest,
                    dependency_archive.expanduser().resolve(strict=True),
                    Path(temp) / "bundle",
                )
            except (_dependency_bundle.DependencyBundleBlocked, OSError) as exc:
                if isinstance(exc, _dependency_bundle.DependencyBundleBlocked):
                    raise InstallBlocked(exc.code, exc.detail) from exc
                raise InstallBlocked("DEPENDENCY_ARCHIVE_NOT_FOUND", str(dependency_archive)) from exc
            environment = os.environ.copy()
            for name in (
                "GIGGLE_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
                "AWS_SESSION_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            ):
                environment.pop(name, None)
            environment.update({
                "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                "PIP_NO_INPUT": "1",
                "PIP_NO_INDEX": "1",
                "PIP_REQUIRE_HASHES": "1",
                "PYTHONNOUSERSITE": "1",
            })
            install_command = [
                str(venv_python), "-m", "pip", "install", "--no-index",
                "--disable-pip-version-check", "--no-input", "--only-binary=:all:",
                "--require-hashes", "--find-links", extracted["wheelhouse"],
                "-r", extracted["lock"],
            ]
            result = runner(install_command, check=False, env=environment)
            if result.returncode != 0:
                raise InstallBlocked("DEPENDENCY_OFFLINE_INSTALL_FAILED", str(result.returncode))
            engine_command = [
                str(venv_python), "-m", "pip", "install", "--no-index", "--no-deps",
                "--no-build-isolation", str(engine),
            ]
            # pip cannot hash a local directory requirement. The caller has
            # already verified the engine's immutable Git/archive identity;
            # keep wheel hash enforcement above, but disable it for this
            # offline, dependency-free install of the verified engine tree.
            engine_environment = {**environment, "PIP_REQUIRE_HASHES": "0"}
            result = runner(engine_command, check=False, env=engine_environment)
            if result.returncode != 0:
                raise InstallBlocked("ENGINE_OFFLINE_INSTALL_FAILED", str(result.returncode))
            result = runner(
                [str(venv_python), "-m", "pip", "check"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            if result.returncode != 0:
                raise InstallBlocked("DEPENDENCY_PIP_CHECK_FAILED", str(result.returncode))
            listed = runner(
                [str(venv_python), "-m", "pip", "list", "--format=json"],
                check=False,
                capture_output=True,
                text=True,
                env=environment,
            )
            if listed.returncode != 0:
                raise InstallBlocked("DEPENDENCY_INVENTORY_FAILED", str(listed.returncode))
            try:
                installed_rows = json.loads(listed.stdout)
                installed = sorted(
                    [
                    {
                        "name": str(row["name"]),
                        "version": str(row["version"]),
                    }
                    for row in installed_rows
                    if isinstance(row, dict) and row.get("name") and row.get("version")
                    ],
                    key=lambda row: row["name"].lower(),
                )
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise InstallBlocked("DEPENDENCY_INVENTORY_INVALID") from exc
            inventory_bytes = (
                json.dumps(installed, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
                + "\n"
            ).encode("utf-8")
        return {
            "requested": True,
            "status": "INSTALLED",
            "venv": str(venv),
            "python": str(venv_python),
            "network_used": False,
            "dependency_profile": profile.profile_id,
            "interpreter_facts": venv_facts,
            "bundle_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "bundle_archive_sha256": manifest["archive"]["sha256"],
            "lock_sha256": manifest["lock"]["sha256"],
            "installed_package_count": len(installed),
            "installed_inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
            "pip_check": "PASS",
        }
    except Exception:
        if created and os.path.lexists(venv):
            _remove_readonly_tree(venv)
        raise


def _dependency_state(runtime: Path, venv_path: Path | None = None) -> dict[str, Any]:
    requested = venv_path or (runtime / DEFAULT_VENV_RELATIVE)
    candidate = requested if requested.is_absolute() else runtime / requested
    python = candidate / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return {
        "requested": False,
        "status": "PRESENT_NOT_MODIFIED" if python.is_file() else "NOT_INSTALLED",
        "venv": str(candidate),
        "python": str(python),
        "network_used": False,
    }


def _venv_python_path(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _venv_selector_report(
    runtime: Path,
    *,
    required: bool = False,
    expected_target: Path | None = None,
) -> dict[str, Any]:
    selector = runtime / VENV_SELECTOR_RELATIVE
    if not os.path.lexists(selector):
        if required:
            raise InstallBlocked("VENV_SELECTOR_MISSING", str(selector))
        return {"status": "ABSENT", "path": str(selector), "python": str(_venv_python_path(selector))}
    if not selector.is_symlink():
        raise InstallBlocked("VENV_SELECTOR_NOT_SYMLINK", str(selector))
    try:
        target = selector.resolve(strict=True)
    except OSError as exc:
        raise InstallBlocked("VENV_SELECTOR_BROKEN", str(selector)) from exc
    if not target.is_dir() or not _inside(target, runtime):
        raise InstallBlocked("VENV_SELECTOR_TARGET_INVALID", str(target))
    if expected_target is not None and target != expected_target.resolve(strict=True):
        raise InstallBlocked(
            "VENV_SELECTOR_TARGET_MISMATCH",
            f"expected={expected_target.resolve(strict=True)},actual={target}",
        )
    selector_python = _venv_python_path(selector)
    try:
        resolved_python = selector_python.resolve(strict=True)
    except OSError as exc:
        raise InstallBlocked("VENV_SELECTOR_PYTHON_MISSING", str(selector_python)) from exc
    if not resolved_python.is_file() or not _inside(resolved_python, target):
        raise InstallBlocked("VENV_SELECTOR_PYTHON_INVALID", str(resolved_python))
    return {
        "status": "PASS",
        "path": str(selector),
        "target": str(target),
        "python": str(selector_python),
        "resolved_python": str(resolved_python),
    }


def _venv_selector_status(runtime: Path, *, required: bool = False) -> dict[str, Any]:
    try:
        return _venv_selector_report(runtime, required=required)
    except InstallBlocked as exc:
        return {
            "status": "BLOCKED",
            "path": str(runtime / VENV_SELECTOR_RELATIVE),
            "code": exc.code,
            "detail": exc.detail,
        }


def _ensure_initial_venv_selector(runtime: Path, target: Path) -> dict[str, Any]:
    resolved = target.resolve(strict=True)
    if not resolved.is_dir() or not _inside(resolved, runtime):
        raise InstallBlocked("VENV_SELECTOR_TARGET_INVALID", str(resolved))
    selector = runtime / VENV_SELECTOR_RELATIVE
    _mkdir_private(selector.parent, runtime)
    if os.path.lexists(selector):
        report = _venv_selector_report(runtime, required=True, expected_target=resolved)
        report["action"] = "ALREADY_SELECTED"
        return report
    _atomic_switch(selector, resolved)
    report = _venv_selector_report(runtime, required=True, expected_target=resolved)
    report["action"] = "SELECTED"
    return report


def _atomic_json(path: Path, payload: Mapping[str, Any], runtime: Path) -> None:
    _mkdir_private(path.parent, runtime)
    _upgrade_transaction.atomic_json(path, payload)


def _write_receipt(runtime: Path, payload: Mapping[str, Any]) -> tuple[Path, str]:
    root = runtime / RECEIPT_ROOT_RELATIVE
    _mkdir_private(root, runtime)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    path = root / f"{stamp}-{secrets.token_hex(4)}.json"
    _atomic_json(path, payload, runtime)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, digest


def inspect_host(
    engine_root: Path,
    runtime_root: Path,
    *,
    release_tag: str | None = None,
    expected_commit: str | None = None,
    venv_path: Path | None = None,
) -> dict[str, Any]:
    """Return read-only JSON facts; no storage probe or directory creation occurs."""
    engine, runtime = _validate_roots(
        engine_root, runtime_root, require_git_checkout=False
    )
    git = _engine_facts(
        engine,
        runtime,
        release_tag=release_tag,
        expected_commit=expected_commit,
        require_clean=False,
        require_tag=False,
    )
    wiring: list[dict[str, Any]] = []
    for row in _backing_paths(engine, runtime, create=False):
        backing = Path(row["backing"])
        state = (
            _target_state(Path(row["target"]), backing)
            if backing.is_dir() and not backing.is_symlink()
            else {"state": "BACKING_ABSENT_OR_INVALID", "wired": False}
        )
        wiring.append({
            "name": row["name"],
            "target": str(row["target"]),
            "backing": str(backing),
            **state,
        })
    dependency_state = _dependency_state(runtime, venv_path)
    return {
        "schema": SCHEMA,
        "command": "INSPECT",
        "status": "PASS",
        "observed_at_utc": utc_now(),
        "engine": git,
        "runtime": {"root": str(runtime)},
        "wiring": wiring,
        "dependencies": dependency_state,
        "venv_selector": _venv_selector_status(
            runtime, required=dependency_state["status"] != "NOT_INSTALLED"
        ),
        "engine_seal": _engine_seal_report(engine),
        "mutations_performed": False,
    }


def verify_host(
    engine_root: Path,
    runtime_root: Path,
    *,
    release_tag: str,
    expected_commit: str | None = None,
    require_sealed: bool = False,
    venv_path: Path | None = None,
    verified_archive_facts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify tag, checkout, exact wiring, write/fsync/flock, and optional seal."""
    engine, runtime = _validate_roots(
        engine_root, runtime_root, require_git_checkout=False
    )
    if verified_archive_facts is None:
        git = _engine_facts(
            engine,
            runtime,
            release_tag=release_tag,
            expected_commit=expected_commit,
            require_clean=True,
            require_tag=True,
        )
    else:
        git = dict(verified_archive_facts)
        expected = str(expected_commit or "").lower()
        if (
            git.get("checkout_kind") != "PACKAGE_VERIFIED_RELEASE_ARCHIVE"
            or git.get("immutable_tree_verified") is not True
            or Path(str(git.get("root") or "")).resolve(strict=False) != engine
            or git.get("release_tag") != release_tag
            or (expected and git.get("head_commit") != expected)
        ):
            raise InstallBlocked("VERIFIED_BOOTSTRAP_FACTS_MISMATCH")
    wiring = _wire_report(_backing_paths(engine, runtime, create=False), probe=True)
    seal = _engine_seal_report(engine)
    dependencies = _dependency_state(runtime, venv_path)
    selector = _venv_selector_report(
        runtime, required=dependencies["status"] != "NOT_INSTALLED"
    )
    if require_sealed and not seal["sealed"]:
        raise InstallBlocked("ENGINE_NOT_SEALED", str(seal["writable_path_count"]))
    if require_sealed:
        _require_engine_root_write_blocked(engine)
        seal["root_write_probe"] = "BLOCKED_AS_REQUIRED"
    return {
        "schema": SCHEMA,
        "command": "VERIFY",
        "status": "PASS",
        "verified_at_utc": utc_now(),
        "engine": git,
        "runtime": {"root": str(runtime)},
        "wiring": wiring,
        "dependencies": dependencies,
        "venv_selector": selector,
        "engine_seal": seal,
        "mutations_performed": False,
    }


def _ensure_project_worktree(
    base_engine: Path,
    runtime: Path,
    view_root: Path,
    *,
    release_tag: str,
    expected_commit: str | None,
) -> tuple[Path, bool, dict[str, Any]]:
    """Create or verify an isolated per-project worktree at the same commit."""
    base_facts = _git_facts(
        base_engine,
        release_tag=release_tag,
        expected_commit=expected_commit,
        require_clean=True,
        require_tag=True,
    )
    requested = view_root.expanduser()
    if not requested.is_absolute():
        requested = requested.absolute()
    prospective = requested.resolve(strict=False)
    if (
        prospective == base_engine
        or _inside(prospective, base_engine)
        or _inside(base_engine, prospective)
        or _inside(prospective, runtime)
        or _inside(runtime, prospective)
    ):
        raise InstallBlocked("PROJECT_VIEW_ROOT_OVERLAP", str(prospective))

    created = False
    if not os.path.lexists(requested):
        requested.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        result = _git(
            base_engine,
            ["worktree", "add", "--detach", str(requested), base_facts["head_commit"]],
            check=False,
        )
        if result.returncode != 0:
            raise InstallBlocked("PROJECT_WORKTREE_CREATE_FAILED", str(requested))
        created = True
    view, checked_runtime = _validate_roots(requested, runtime)
    if checked_runtime != runtime:
        raise InstallBlocked("PROJECT_VIEW_RUNTIME_MISMATCH")
    facts = _git_facts(
        view,
        release_tag=release_tag,
        expected_commit=base_facts["head_commit"],
        require_clean=True,
        require_tag=True,
    )
    try:
        common = Path(_git(view, ["rev-parse", "--git-common-dir"]).stdout.strip()).expanduser()
        if not common.is_absolute():
            common = (view / common).resolve(strict=True)
        else:
            common = common.resolve(strict=True)
        base_common = Path(
            _git(base_engine, ["rev-parse", "--git-common-dir"]).stdout.strip()
        ).expanduser()
        if not base_common.is_absolute():
            base_common = (base_engine / base_common).resolve(strict=True)
        else:
            base_common = base_common.resolve(strict=True)
    except OSError as exc:
        raise InstallBlocked("PROJECT_WORKTREE_COMMON_GIT_INVALID", str(view)) from exc
    if common != base_common:
        raise InstallBlocked("PROJECT_VIEW_NOT_BASE_WORKTREE", str(view))
    return view, created, facts


def _ensure_project_engine_link(
    link_path: Path,
    view: Path,
    runtime: Path,
    base_engine: Path,
) -> dict[str, Any]:
    link = link_path.expanduser()
    if not link.is_absolute():
        link = link.absolute()
    prospective = link.resolve(strict=False) if not os.path.lexists(link) else link.absolute()
    if (
        _inside(prospective, runtime)
        or _inside(prospective, view)
        or _inside(prospective, base_engine)
    ):
        raise InstallBlocked("PROJECT_ENGINE_LINK_LOCATION_INVALID", str(link))
    if os.path.lexists(link):
        if not link.is_symlink():
            raise InstallBlocked("PROJECT_ENGINE_LINK_NOT_SYMLINK", str(link))
        try:
            resolved = link.resolve(strict=True)
        except OSError as exc:
            raise InstallBlocked("PROJECT_ENGINE_LINK_BROKEN", str(link)) from exc
        if resolved != view:
            raise InstallBlocked(
                "PROJECT_ENGINE_LINK_TARGET_MISMATCH", f"expected={view},actual={resolved}"
            )
        return {"path": str(link), "target": str(view), "action": "ALREADY_LINKED"}
    link.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    os.symlink(str(view), link)
    return {"path": str(link), "target": str(view), "action": "LINKED"}


def install_host(
    engine_root: Path,
    runtime_root: Path,
    *,
    release_tag: str,
    expected_commit: str | None = None,
    install_deps: bool = False,
    venv_path: Path | None = None,
    python_executable: str = sys.executable,
    seal_read_only: bool = False,
    project_view_root: Path | None = None,
    project_engine_link: Path | None = None,
    isolated_mount_namespace: bool = False,
    talenthub_release_manifest: Path | None = None,
    verified_bootstrap_archive: Path | None = None,
    dependency_manifest: Path | None = None,
    dependency_archive: Path | None = None,
    acceptance_channel_manifest: Path | None = None,
    acceptance_channel_manifest_sha256: str | None = None,
    dependency_installer: Callable[..., dict[str, Any]] = install_dependencies,
) -> dict[str, Any]:
    """Perform the bounded, idempotent host installation and write a receipt."""
    if project_engine_link is not None and project_view_root is None:
        raise InstallBlocked("PROJECT_ENGINE_LINK_REQUIRES_PROJECT_VIEW")
    if project_view_root is None and not isolated_mount_namespace:
        raise InstallBlocked(
            "PROJECT_VIEW_ROOT_REQUIRED",
            "provide --project-view-root, or assert a per-project mount namespace with "
            "--isolated-mount-namespace",
        )
    if project_view_root is not None and isolated_mount_namespace:
        raise InstallBlocked(
            "ISOLATION_MODE_CONFLICT",
            "choose either --project-view-root or --isolated-mount-namespace",
        )
    acceptance_requested = (
        acceptance_channel_manifest is not None
        or acceptance_channel_manifest_sha256 is not None
    )
    if acceptance_requested and (
        acceptance_channel_manifest is None
        or acceptance_channel_manifest_sha256 is None
    ):
        raise InstallBlocked(
            "ACCEPTANCE_CHANNEL_BINDING_INCOMPLETE",
            "both --acceptance-channel-manifest and its SHA-256 are required",
        )
    if acceptance_requested and (
        not install_deps
        or talenthub_release_manifest is not None
        or verified_bootstrap_archive is not None
    ):
        raise InstallBlocked(
            "ACCEPTANCE_INSTALL_MODE_INVALID",
            "candidate acceptance requires --install-deps, a Git checkout, and no "
            "TalentHub production manifest",
        )
    base_engine, runtime = _validate_roots(
        engine_root,
        runtime_root,
        require_git_checkout=verified_bootstrap_archive is None,
    )
    bootstrap_package: dict[str, Any] | None = None
    if verified_bootstrap_archive is not None:
        if talenthub_release_manifest is None or not expected_commit:
            raise InstallBlocked(
                "BOOTSTRAP_ARCHIVE_REQUIRES_PACKAGE_BINDING",
                "--talenthub-release-manifest and --expected-commit are required",
            )
        bootstrap_package = _validate_bootstrap_talenthub_manifest(
            talenthub_release_manifest,
            release_tag=release_tag,
            git_commit=expected_commit.lower(),
        )
        base_git = _bootstrap_archive_facts(
            base_engine,
            verified_bootstrap_archive.expanduser().resolve(strict=True),
            bootstrap_package,
            release_tag=release_tag,
            expected_commit=expected_commit.lower(),
        )
    else:
        base_git = _git_facts(
            base_engine,
            release_tag=release_tag,
            expected_commit=expected_commit,
            require_clean=True,
            require_tag=True,
        )
    acceptance_package = (
        _validate_acceptance_channel_manifest(
            acceptance_channel_manifest,
            str(acceptance_channel_manifest_sha256),
            release_tag=release_tag,
            git_commit=str(base_git["head_commit"]),
        )
        if acceptance_requested and acceptance_channel_manifest is not None
        else None
    )
    project_view: dict[str, Any] | None = None
    if project_view_root is not None:
        if verified_bootstrap_archive is not None:
            try:
                requested_view = project_view_root.expanduser().resolve(strict=True)
            except OSError as exc:
                raise InstallBlocked("PROJECT_VIEW_ROOT_INVALID", str(project_view_root)) from exc
            if requested_view != base_engine:
                raise InstallBlocked(
                    "BOOTSTRAP_ARCHIVE_PROJECT_VIEW_MISMATCH", str(requested_view)
                )
            isolation_mode = "PER_PROJECT_VERIFIED_ARCHIVE_VIEW"
            engine, created, git = base_engine, False, base_git
        else:
            isolation_mode = "PER_PROJECT_WORKTREE_VIEW"
            engine, created, git = _ensure_project_worktree(
                base_engine,
                runtime,
                project_view_root,
                release_tag=release_tag,
                expected_commit=base_git["head_commit"],
            )
        project_view = {
            "base_engine_root": str(base_engine),
            "engine_root": str(engine),
            "commit": git["head_commit"],
            "action": "CREATED" if created else "EXISTS_VERIFIED",
        }
    else:
        isolation_mode = "ISOLATED_MOUNT_NAMESPACE"
        engine, git = base_engine, base_git
    rows = _backing_paths(engine, runtime, create=True)
    actions = []
    for row in rows:
        action = _wire_target(Path(row["target"]), Path(row["backing"]))
        actions.append({"name": row["name"], "action": action})
    wiring = _wire_report(rows, probe=True)

    if install_deps:
        if talenthub_release_manifest is None and acceptance_package is None:
            raise InstallBlocked(
                "DEPENDENCY_PACKAGE_BINDING_REQUIRED",
                f"pass the installed skills/{SKILL_NAME}/RELEASE_MANIFEST.json",
            )
        dependency_package = acceptance_package or bootstrap_package
        if dependency_package is None:
            assert talenthub_release_manifest is not None
            dependency_package = _validate_bootstrap_talenthub_manifest(
                talenthub_release_manifest,
                release_tag=release_tag,
                git_commit=str(git["head_commit"]),
            )
        dependencies = dependency_installer(
            engine,
            runtime,
            venv_path=venv_path,
            python_executable=python_executable,
            dependency_manifest=dependency_manifest,
            dependency_archive=dependency_archive,
            release_tag=release_tag,
            git_commit=str(git["head_commit"]),
            release_sequence=int(dependency_package["release_sequence"]),
            expected_binding=dependency_package["dependency_profile_bindings"],
        )
        venv_value = Path(str(dependencies.get("venv") or ""))
        try:
            venv_target = venv_value.expanduser().resolve(strict=True)
        except OSError as exc:
            raise InstallBlocked("VENV_PATH_INVALID", str(venv_value)) from exc
        venv_selector = _ensure_initial_venv_selector(runtime, venv_target)
        dependencies = {
            **dependencies,
            "stable_python": venv_selector["python"],
        }
    else:
        dependencies = _dependency_state(runtime, venv_path)
        venv_selector = _venv_selector_report(
            runtime, required=dependencies["status"] != "NOT_INSTALLED"
        )

    if seal_read_only:
        seal = (
            _seal_extracted_engine(engine)
            if verified_bootstrap_archive is not None
            else seal_public_engine(engine)
        )
    else:
        seal = _engine_seal_report(engine)
    engine_link = (
        _ensure_project_engine_link(project_engine_link, engine, runtime, base_engine)
        if project_engine_link is not None else None
    )
    verification = verify_host(
        engine,
        runtime,
        release_tag=release_tag,
        expected_commit=expected_commit,
        require_sealed=seal_read_only,
        venv_path=venv_path,
        verified_archive_facts=(
            base_git if verified_bootstrap_archive is not None else None
        ),
    )
    if acceptance_package is not None:
        release_baseline = {
            "status": "ACCEPTANCE_ONLY",
            "channel_manifest_sha256": acceptance_package["sha256"],
            "production_authorization": False,
            "upgrade_eligible": False,
        }
    elif talenthub_release_manifest is not None:
        package = bootstrap_package or _validate_bootstrap_talenthub_manifest(
            talenthub_release_manifest,
            release_tag=release_tag,
            git_commit=str(git["head_commit"]),
        )
        release_baseline = _record_install_release_baseline(runtime, package)
    else:
        release_baseline = {
            "status": "UNBOUND",
            "reason": "talenthub_release_manifest_not_supplied",
            "upgrade_eligible": False,
        }
    if verified_bootstrap_archive is not None:
        initial_archive_receipt = {
            "schema": UPGRADE_RECEIPT_SCHEMA,
            "status": "PASS",
            "release_tag": release_tag,
            "release_sequence": bootstrap_package["release_sequence"],
            "git_commit": str(base_git["head_commit"]),
            "current_engine": str(engine),
            "candidate_tree_sha256": _tree_digest(engine),
            "source_archive_sha256": bootstrap_package["source_archive_sha256"],
            "source_archive_size_bytes": bootstrap_package["source_archive_size_bytes"],
            "talenthub_release_manifest_sha256": bootstrap_package["sha256"],
            "update_class": "TALENTHUB_PACKAGE_REQUIRED",
            "bootstrap_install": True,
            "verification_status": verification["status"],
            "release_baseline_status": release_baseline["status"],
            "network_used": False,
        }
        _atomic_json(
            runtime / UPGRADE_RECEIPT_ROOT_RELATIVE / f"{base_git['head_commit']}.json",
            initial_archive_receipt,
            runtime,
        )
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "status": "PASS",
        "installed_at_utc": utc_now(),
        "engine": git,
        "base_engine": base_git,
        "project_view": project_view,
        "project_engine_link": engine_link,
        "isolation_mode": isolation_mode,
        "runtime": {"root": str(runtime)},
        "actions": actions,
        "wiring": wiring,
        "dependencies": dependencies,
        "venv_selector": venv_selector,
        "release_baseline": release_baseline,
        "engine_seal": seal,
        "verification": {
            "status": verification["status"],
            "tag": verification["engine"]["release_tag"],
            "commit": verification["engine"]["head_commit"],
            "storage_probe": "PASS",
        },
        "source_or_media_paths_touched": [],
        "secret_values_recorded": False,
        "production_authorization": False if acceptance_package is not None else None,
    }
    receipt_path, receipt_sha = _write_receipt(runtime, receipt)
    return {
        "schema": SCHEMA,
        "command": "INSTALL",
        "status": "PASS",
        "engine": git,
        "base_engine": base_git,
        "project_view": project_view,
        "project_engine_link": engine_link,
        "isolation_mode": isolation_mode,
        "runtime": {"root": str(runtime)},
        "actions": actions,
        "wiring": wiring,
        "dependencies": dependencies,
        "venv_selector": venv_selector,
        "release_baseline": release_baseline,
        "engine_seal": seal,
        "receipt": {"path": str(receipt_path), "sha256": receipt_sha},
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_version(value: Any, label: str) -> tuple[int, int, int]:
    text = str(value or "").strip()
    match = re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", text)
    if not match:
        raise InstallBlocked(f"{label}_INVALID", text)
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _validate_acceptance_channel_manifest(
    path: Path,
    expected_sha256: str,
    *,
    release_tag: str,
    git_commit: str,
) -> dict[str, Any]:
    """Validate an unpromoted channel solely as a maintainer acceptance input.

    This path can bind offline dependencies for a real StoryClaw trial, but it
    deliberately creates no trusted release baseline and grants no production
    or upgrade authority.
    """
    expected = str(expected_sha256 or "").strip().lower()
    if not _SHA256_RE.fullmatch(expected):
        raise InstallBlocked("ACCEPTANCE_CHANNEL_SHA256_INVALID", expected_sha256)
    try:
        resolved = path.expanduser().resolve(strict=True)
        raw = resolved.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallBlocked("ACCEPTANCE_CHANNEL_INVALID", str(path)) from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise InstallBlocked(
            "ACCEPTANCE_CHANNEL_SHA256_MISMATCH",
            f"expected={expected},actual={actual}",
        )
    tag = _checked_tag(release_tag)
    commit = str(git_commit or "").strip().lower()
    exact = {
        "schema": UPGRADE_SCHEMA,
        "immutable": True,
        "channel": "stable",
        "release_tag": tag,
        "source_ref": f"refs/tags/{tag}",
        "git_commit": commit,
        "update_class": PACKAGE_REQUIRED,
        "runtime_migration": "NONE",
        "validation_receipt_status": "UNVALIDATED",
        "validation_receipt_sha256": None,
        "dependency_profiles_action": "REPLACE_WITH_RELEASE_BUNDLES",
        "release_signing_key_sha256": RELEASE_SIGNING_PUBLIC_KEY_SHA256,
    }
    failures = [
        field for field, value in exact.items() if payload.get(field) != value
    ] if isinstance(payload, dict) else ["payload"]
    sequence = payload.get("release_sequence") if isinstance(payload, dict) else None
    if type(sequence) is not int or sequence <= 0:
        failures.append("release_sequence")
    archive_sha = str(payload.get("source_archive_sha256") or "").lower()
    if not _SHA256_RE.fullmatch(archive_sha):
        failures.append("source_archive_sha256")
    archive_size = payload.get("source_archive_size_bytes")
    if type(archive_size) is not int or archive_size <= 0:
        failures.append("source_archive_size_bytes")
    try:
        bindings = _dependency_bundle.validate_release_bindings(
            payload.get("dependency_profiles"), release_tag=tag
        )
    except _dependency_bundle.DependencyBundleBlocked as exc:
        raise InstallBlocked(exc.code, exc.detail) from exc
    if failures:
        raise InstallBlocked(
            "ACCEPTANCE_CHANNEL_BINDING_MISMATCH", ",".join(failures[:10])
        )
    return {
        "status": "ACCEPTANCE_ONLY",
        "path": str(resolved),
        "sha256": actual,
        "release_sequence": sequence,
        "release_tag": tag,
        "git_commit": commit,
        "source_archive_size_bytes": archive_size,
        "source_archive_sha256": archive_sha,
        "dependency_profiles": payload.get("dependency_profiles"),
        "dependency_profile_bindings": bindings,
        "production_authorization": False,
    }


def _load_channel_manifest(path: Path, expected_sha256: str) -> tuple[dict[str, Any], str]:
    expected = str(expected_sha256 or "").strip().lower()
    if not _SHA256_RE.fullmatch(expected):
        raise InstallBlocked("CHANNEL_MANIFEST_SHA256_INVALID", expected_sha256)
    try:
        raw = path.expanduser().resolve(strict=True).read_bytes()
    except OSError as exc:
        raise InstallBlocked("CHANNEL_MANIFEST_NOT_FOUND", str(path)) from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise InstallBlocked("CHANNEL_MANIFEST_SHA256_MISMATCH", f"expected={expected},actual={actual}")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallBlocked("CHANNEL_MANIFEST_INVALID_JSON", str(path)) from exc
    if not isinstance(payload, dict) or payload.get("schema") != UPGRADE_SCHEMA:
        raise InstallBlocked("CHANNEL_MANIFEST_SCHEMA_INVALID", str(payload.get("schema")))
    if payload.get("immutable") is not True:
        raise InstallBlocked("CHANNEL_MANIFEST_NOT_IMMUTABLE")
    channel = str(payload.get("channel") or "").strip().lower()
    if channel not in {"stable", "security"}:
        raise InstallBlocked("RELEASE_CHANNEL_NOT_ALLOWED", channel)
    tag = _checked_tag(str(payload.get("release_tag") or ""))
    if tag.lower() in {"main", "master", "head"}:
        raise InstallBlocked("MUTABLE_BRANCH_RELEASE_FORBIDDEN", tag)
    source_ref = str(payload.get("source_ref") or "").strip().lower()
    if source_ref in {"main", "master", "head", "refs/heads/main", "refs/heads/master"}:
        raise InstallBlocked("MUTABLE_BRANCH_RELEASE_FORBIDDEN", source_ref)
    commit = str(payload.get("git_commit") or "").strip().lower()
    if not _COMMIT_RE.fullmatch(commit):
        raise InstallBlocked("CHANNEL_COMMIT_INVALID", commit)
    archive_sha = str(payload.get("source_archive_sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(archive_sha):
        raise InstallBlocked("CHANNEL_ARCHIVE_SHA256_INVALID", archive_sha)
    archive_size = payload.get("source_archive_size_bytes")
    if type(archive_size) is not int or archive_size <= 0:
        raise InstallBlocked("CHANNEL_ARCHIVE_SIZE_INVALID", str(archive_size))
    release_sequence = payload.get("release_sequence")
    if type(release_sequence) is not int or release_sequence <= 0:
        raise InstallBlocked("CHANNEL_RELEASE_SEQUENCE_INVALID", str(release_sequence))
    validation_sha = str(payload.get("validation_receipt_sha256") or "").strip().lower()
    if payload.get("validation_receipt_status") != "PASS" or not _SHA256_RE.fullmatch(
        validation_sha
    ):
        raise InstallBlocked("CHANNEL_NOT_STORYCLAW_VALIDATED")
    if payload.get("release_signing_key_sha256") != RELEASE_SIGNING_PUBLIC_KEY_SHA256:
        raise InstallBlocked("CHANNEL_RELEASE_SIGNING_KEY_MISMATCH")
    minimum = _parse_version(payload.get("min_installer_version"), "MIN_INSTALLER_VERSION")
    if _parse_version(INSTALLER_VERSION, "INSTALLER_VERSION") < minimum:
        raise InstallBlocked(
            "INSTALLER_VERSION_TOO_OLD",
            f"installed={INSTALLER_VERSION},required={payload.get('min_installer_version')}",
        )
    update_class = payload.get("update_class")
    if update_class not in {ENGINE_ONLY, PACKAGE_REQUIRED}:
        raise InstallBlocked("RUNTIME_MIGRATION_REQUIRES_PACKAGE_RELEASE", str(update_class))
    if type(payload.get("dependencies_changed")) is not bool:
        raise InstallBlocked("CHANNEL_DEPENDENCY_CLASSIFICATION_INVALID")
    if payload["dependencies_changed"] and update_class == ENGINE_ONLY:
        raise InstallBlocked("CHANNEL_DEPENDENCY_CLASSIFICATION_INVALID", ENGINE_ONLY)
    if payload.get("runtime_migration") != "NONE":
        raise InstallBlocked("RUNTIME_MIGRATION_REQUIRES_PACKAGE_RELEASE")
    dependency_action = payload.get("dependency_profiles_action")
    if dependency_action == "REUSE_CURRENT":
        if update_class != ENGINE_ONLY or payload["dependencies_changed"] or payload.get(
            "dependency_profiles"
        ) != []:
            raise InstallBlocked("CHANNEL_DEPENDENCY_PROFILE_ACTION_INVALID")
        bindings: dict[str, dict[str, Any]] = {}
    elif dependency_action == "REPLACE_WITH_RELEASE_BUNDLES":
        try:
            bindings = _dependency_bundle.validate_release_bindings(
                payload.get("dependency_profiles"), release_tag=tag
            )
        except _dependency_bundle.DependencyBundleBlocked as exc:
            raise InstallBlocked(exc.code, exc.detail) from exc
    else:
        raise InstallBlocked("CHANNEL_DEPENDENCY_PROFILE_ACTION_INVALID")
    runtime_schema = str(payload.get("runtime_schema") or "").strip()
    compatible = payload.get("compatible_runtime_schemas")
    if not runtime_schema or not isinstance(compatible, list) or not compatible:
        raise InstallBlocked("RUNTIME_SCHEMA_CONTRACT_INVALID")
    if not all(isinstance(value, str) and value.strip() for value in compatible):
        raise InstallBlocked("RUNTIME_SCHEMA_CONTRACT_INVALID")
    payload["release_tag"] = tag
    payload["git_commit"] = commit
    payload["source_archive_sha256"] = archive_sha
    payload["dependency_profile_bindings"] = bindings
    return payload, actual


def _package_update_required(detail: str) -> InstallBlocked:
    return InstallBlocked(
        "TALENTHUB_REPUBLISH_REQUIRED",
        f"{detail}; run `talenthub agent update ai-drama-factory`, then pass that installed "
        f"workspace's skills/{SKILL_NAME}/RELEASE_MANIFEST.json",
    )


INSTALLED_TALENTHUB_BOUND_FILES = frozenset({
    "IDENTITY.md",
    "USER.md",
    "SOUL.md",
    "AGENTS.md",
    "HEARTBEAT.md",
    f"skills/{SKILL_NAME}/SKILL.md",
    f"skills/{SKILL_NAME}/bootstrap_storyclaw.py",
})


def _load_installed_talenthub_manifest(path: Path | None) -> dict[str, Any]:
    if path is None:
        raise _package_update_required("installed TalentHub release manifest is missing")
    candidate = path.expanduser()
    try:
        resolved = candidate.resolve(strict=True)
        raw = resolved.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _package_update_required(
            f"TalentHub release manifest is unavailable or invalid: {candidate}"
        ) from exc
    expected_suffix = Path("skills") / SKILL_NAME / "RELEASE_MANIFEST.json"
    if Path(*resolved.parts[-3:]) != expected_suffix:
        raise _package_update_required(
            f"expected installed skills/{SKILL_NAME}/RELEASE_MANIFEST.json"
        )
    workspace = resolved.parents[2]
    if not isinstance(payload, dict) or payload.get("schema") != TALENTHUB_RELEASE_SCHEMA:
        raise _package_update_required("TalentHub release manifest schema is invalid")
    bindings = payload.get("installed_file_bindings")
    if not isinstance(bindings, dict) or set(bindings) != INSTALLED_TALENTHUB_BOUND_FILES:
        raise _package_update_required("installed Agent file binding set is invalid")
    verified: dict[str, dict[str, Any]] = {}
    for relative in sorted(INSTALLED_TALENTHUB_BOUND_FILES):
        expected = bindings.get(relative)
        target = workspace / relative
        if (
            not isinstance(expected, dict)
            or type(expected.get("size_bytes")) is not int
            or expected["size_bytes"] <= 0
            or not _SHA256_RE.fullmatch(str(expected.get("sha256") or "").lower())
            or target.is_symlink()
            or not target.is_file()
            or target.stat().st_size != expected["size_bytes"]
            or _sha256_file(target) != str(expected["sha256"]).lower()
        ):
            raise _package_update_required(f"installed Agent file binding mismatch: {relative}")
        verified[relative] = dict(expected)
    return {
        "resolved": resolved,
        "raw": raw,
        "payload": payload,
        "workspace": workspace,
        "installed_file_bindings": verified,
    }


def _validate_talenthub_release_manifest(
    path: Path | None,
    *,
    channel: Mapping[str, Any],
    channel_sha256: str,
    channel_size: int,
) -> dict[str, Any]:
    """Bind a package-required engine to the already-updated TalentHub workspace."""
    installed = _load_installed_talenthub_manifest(path)
    resolved = installed["resolved"]
    raw = installed["raw"]
    payload = installed["payload"]
    workspace = installed["workspace"]
    exact = {
        "agent_id": AGENT_ID,
        "skill": SKILL_NAME,
        "release_tag": channel["release_tag"],
        "git_commit": channel["git_commit"],
        "origin_tag_commit": channel["git_commit"],
        "source_archive_size_bytes": channel["source_archive_size_bytes"],
        "source_archive_sha256": channel["source_archive_sha256"],
        "release_channel_size_bytes": channel_size,
        "release_channel_sha256": channel_sha256,
        "release_channel_update_class": channel["update_class"],
        "release_sequence": channel["release_sequence"],
        "release_signing_key_sha256": RELEASE_SIGNING_PUBLIC_KEY_SHA256,
        "validation_receipt_status": "PASS",
        "validation_receipt_sha256": channel["validation_receipt_sha256"],
        "public_runtime_only": True,
        "private_validation_contents_included": False,
        "dependency_profiles": channel["dependency_profiles"],
        "dependency_profiles_action": channel["dependency_profiles_action"],
    }
    failures = [
        f"{field}={payload.get(field)!r}"
        for field, expected in exact.items()
        if payload.get(field) != expected
    ]
    if channel.get("source_archive_url") and (
        payload.get("source_archive_github_release_url") != channel["source_archive_url"]
    ):
        failures.append("source_archive_github_release_url")
    validation_sha = str(payload.get("validation_receipt_sha256") or "").lower()
    if not _SHA256_RE.fullmatch(validation_sha):
        failures.append("validation_receipt_sha256")
    if failures:
        raise _package_update_required(
            "TalentHub release binding mismatch: " + ",".join(failures[:8])
        )
    return {
        "status": "PASS",
        "path": str(resolved),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "workspace": str(workspace),
        "agent_id": AGENT_ID,
        "skill": SKILL_NAME,
        "release_tag": channel["release_tag"],
        "git_commit": channel["git_commit"],
        "release_channel_sha256": channel_sha256,
        "update_class": channel["update_class"],
        "installed_file_bindings": installed["installed_file_bindings"],
    }


def _validate_bootstrap_talenthub_manifest(
    path: Path,
    *,
    release_tag: str,
    git_commit: str,
) -> dict[str, Any]:
    """Verify the published package that authorizes a first-install baseline."""
    try:
        installed = _load_installed_talenthub_manifest(path)
    except InstallBlocked as exc:
        raise InstallBlocked("TALENTHUB_INSTALL_MANIFEST_INVALID", exc.detail) from exc
    resolved = installed["resolved"]
    raw = installed["raw"]
    payload = installed["payload"]
    sequence = payload.get("release_sequence")
    exact = {
        "schema": TALENTHUB_RELEASE_SCHEMA,
        "agent_id": AGENT_ID,
        "skill": SKILL_NAME,
        "release_tag": release_tag,
        "git_commit": git_commit,
        "origin_tag_commit": git_commit,
        "release_signing_key_sha256": RELEASE_SIGNING_PUBLIC_KEY_SHA256,
        "validation_receipt_status": "PASS",
        "public_runtime_only": True,
        "private_validation_contents_included": False,
        "dependency_profiles_action": "REPLACE_WITH_RELEASE_BUNDLES",
    }
    failures = [
        field for field, expected in exact.items() if payload.get(field) != expected
    ]
    if type(sequence) is not int or sequence <= 0:
        failures.append("release_sequence")
    if not _SHA256_RE.fullmatch(
        str(payload.get("validation_receipt_sha256") or "").lower()
    ):
        failures.append("validation_receipt_sha256")
    if (
        type(payload.get("source_archive_size_bytes")) is not int
        or payload["source_archive_size_bytes"] <= 0
        or not _SHA256_RE.fullmatch(
            str(payload.get("source_archive_sha256") or "").lower()
        )
    ):
        failures.append("source_archive_binding")
    try:
        dependency_bindings = _dependency_bundle.validate_release_bindings(
            payload.get("dependency_profiles"), release_tag=release_tag
        )
    except _dependency_bundle.DependencyBundleBlocked:
        failures.append("dependency_profiles")
        dependency_bindings = {}
    if failures:
        raise InstallBlocked(
            "TALENTHUB_INSTALL_MANIFEST_MISMATCH", ",".join(failures[:10])
        )
    return {
        "status": "PASS",
        "path": str(resolved),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "release_sequence": sequence,
        "release_tag": release_tag,
        "git_commit": git_commit,
        "validation_receipt_sha256": str(payload["validation_receipt_sha256"]).lower(),
        "source_archive_size_bytes": payload.get("source_archive_size_bytes"),
        "source_archive_sha256": str(payload.get("source_archive_sha256") or "").lower(),
        "dependency_profiles": payload.get("dependency_profiles"),
        "dependency_profile_bindings": dependency_bindings,
    }


def _current_engine_identity(current: Path, runtime: Path) -> dict[str, str]:
    facts = _engine_facts(
        current,
        runtime,
        release_tag=None,
        expected_commit=None,
        require_clean=False,
        require_tag=False,
    )
    tags = [str(value) for value in facts.get("tags_at_head") or []]
    return {
        "git_commit": str(facts["head_commit"]),
        "release_tag": str(facts.get("release_tag") or (tags[0] if len(tags) == 1 else "")),
    }


def _record_install_release_baseline(
    runtime: Path, package: Mapping[str, Any]
) -> dict[str, Any]:
    path = runtime / CURRENT_RELEASE_STATE_RELATIVE
    payload = {
        "schema": CURRENT_RELEASE_STATE_SCHEMA,
        "status": "PASS",
        "recorded_at_utc": utc_now(),
        "release_sequence": package["release_sequence"],
        "release_tag": package["release_tag"],
        "git_commit": package["git_commit"],
        "signing_key_sha256": RELEASE_SIGNING_PUBLIC_KEY_SHA256,
        "talenthub_release_manifest_sha256": package["sha256"],
        "validation_receipt_sha256": package["validation_receipt_sha256"],
    }
    if path.is_file():
        existing = _load_private_json(path, "CURRENT_RELEASE_BASELINE_MISSING_OR_INVALID")
        comparable = {
            key: value for key, value in payload.items() if key != "recorded_at_utc"
        }
        if any(existing.get(key) != value for key, value in comparable.items()):
            raise InstallBlocked("CURRENT_RELEASE_BASELINE_ALREADY_BOUND", str(path))
        return {**existing, "path": str(path), "action": "ALREADY_BOUND"}
    _atomic_json(path, payload, runtime)
    return {**payload, "path": str(path), "action": "BOUND"}


def _load_private_json(path: Path, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallBlocked(code, str(path)) from exc
    if not isinstance(payload, dict):
        raise InstallBlocked(code, str(path))
    return payload


def _trusted_upgrade_authority(
    runtime: Path,
    current: Path,
    manifest: Mapping[str, Any],
    *,
    channel_path: Path,
    channel_sha256: str,
) -> dict[str, Any]:
    """Bind an upgrade to the installed baseline and signed discovery state."""
    current_state_path = runtime / CURRENT_RELEASE_STATE_RELATIVE
    current_state = _load_private_json(
        current_state_path, "CURRENT_RELEASE_BASELINE_MISSING_OR_INVALID"
    )
    identity = _current_engine_identity(current, runtime)
    sequence = current_state.get("release_sequence")
    if (
        current_state.get("schema") != CURRENT_RELEASE_STATE_SCHEMA
        or current_state.get("status") != "PASS"
        or type(sequence) is not int
        or sequence <= 0
        or current_state.get("release_tag") != identity["release_tag"]
        or current_state.get("git_commit") != identity["git_commit"]
        or current_state.get("signing_key_sha256") != RELEASE_SIGNING_PUBLIC_KEY_SHA256
    ):
        raise InstallBlocked(
            "CURRENT_RELEASE_BASELINE_MISMATCH", str(current_state_path)
        )

    target_sequence = int(manifest["release_sequence"])
    if target_sequence < sequence:
        raise InstallBlocked(
            "RELEASE_SEQUENCE_ROLLBACK",
            f"current={sequence},target={target_sequence}",
        )
    same_identity = (
        target_sequence == sequence
        and manifest["release_tag"] == identity["release_tag"]
        and manifest["git_commit"] == identity["git_commit"]
    )
    if target_sequence == sequence and not same_identity:
        raise InstallBlocked("RELEASE_SEQUENCE_EQUIVOCATION")
    if same_identity:
        return {
            "status": "ALREADY_CURRENT_IDENTITY",
            "current": current_state,
            "current_state_path": str(current_state_path),
            "discovery_state_path": str(runtime / DISCOVERY_STATE_RELATIVE),
        }

    discovery_path = runtime / DISCOVERY_STATE_RELATIVE
    discovery = _load_private_json(discovery_path, "TRUSTED_DISCOVERY_STATE_REQUIRED")
    try:
        discovered_channel = Path(str(discovery.get("channel_manifest") or "")).resolve(
            strict=True
        )
    except OSError as exc:
        raise InstallBlocked("TRUSTED_DISCOVERY_STATE_INVALID", str(discovery_path)) from exc
    exact = {
        "schema": DISCOVERY_RESULT_SCHEMA,
        "status": "AVAILABLE",
        "current_release_tag": identity["release_tag"],
        "current_release_commit": identity["git_commit"],
        "baseline_release_sequence": sequence,
        "trusted_release_sequence": target_sequence,
        "trusted_release_tag": manifest["release_tag"],
        "trusted_release_commit": manifest["git_commit"],
        "update_class": manifest["update_class"],
        "signing_key_sha256": RELEASE_SIGNING_PUBLIC_KEY_SHA256,
        "channel_manifest_sha256": channel_sha256,
        "source_archive_size_bytes": manifest["source_archive_size_bytes"],
        "source_archive_sha256": manifest["source_archive_sha256"],
        "validation_receipt_sha256": manifest["validation_receipt_sha256"],
        "provider_posts": 0,
    }
    failures = [field for field, expected in exact.items() if discovery.get(field) != expected]
    if discovered_channel != channel_path:
        failures.append("channel_manifest")
    if failures:
        raise InstallBlocked(
            "TRUSTED_DISCOVERY_BINDING_MISMATCH", ",".join(failures[:12])
        )
    return {
        "status": "PASS",
        "current": current_state,
        "discovery": discovery,
        "current_state_path": str(current_state_path),
        "discovery_state_path": str(discovery_path),
    }


def _check_runtime_upgrade_safe(runtime: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    state_root = runtime / "runtime" / "pipeline_state"
    lock_root = runtime / "runtime" / "storyclaw_locks"
    active_locks: list[str] = []
    if lock_root.is_dir():
        for lock in sorted(lock_root.rglob("*.lock")):
            if lock.is_symlink() or not lock.is_file():
                continue
            if lock.resolve(strict=False) == (runtime / UPGRADE_BARRIER_RELATIVE).resolve(strict=False):
                # The updater itself holds this exclusive barrier throughout
                # this check and the eventual atomic switch.
                continue
            try:
                with lock.open("a+b") as handle:
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        active_locks.append(str(lock.relative_to(runtime)))
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError as exc:
                raise InstallBlocked("RUN_LOCK_INSPECTION_FAILED", str(lock)) from exc
    if active_locks:
        raise InstallBlocked("ACTIVE_EPISODE_LOCKED", ",".join(active_locks[:10]))

    compatible = {str(value) for value in manifest["compatible_runtime_schemas"]}
    safe_exact = {
        "NOT_STARTED", "REVIEW_REQUIRED", "AWAITING_APPROVAL",
        "READY_FOR_CHECKPOINT", "APPROVED", "PASS", "COMPLETE", "DRY_PLANNED",
        "STOPPED_BUDGET_HARD_STOP",
    }
    safe_prefixes = ("BLOCKED_", "AWAITING_")
    safe_stopped_stage = re.compile(
        r"STOPPED_AT_S[1-8]_(?:BLOCKED|DRY_PLANNED|NOT_STARTED)\Z"
    )
    rows: list[dict[str, Any]] = []
    if state_root.is_dir():
        for state_path in sorted(state_root.glob("*.json")):
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise InstallBlocked("PIPELINE_STATE_INVALID", str(state_path)) from exc
            if not isinstance(state, dict):
                raise InstallBlocked("PIPELINE_STATE_INVALID", str(state_path))
            schema = str(state.get("schema") or "")
            if schema not in compatible:
                raise InstallBlocked("RUNTIME_SCHEMA_INCOMPATIBLE", f"{state_path.name}:{schema}")
            status = str(state.get("overall_status") or "UNKNOWN").upper()
            if (
                status not in safe_exact
                and not status.startswith(safe_prefixes)
                and not safe_stopped_stage.fullmatch(status)
            ):
                raise InstallBlocked("EPISODE_NOT_AT_SAFE_STOP", f"{state_path.name}:{status}")
            rows.append({
                "state": str(state_path.relative_to(runtime)),
                "schema": schema,
                "overall_status": status,
                "current_stage": state.get("current_stage"),
            })
    return {
        "status": "PASS",
        "active_episode_locks": 0,
        "state_count": len(rows),
        "states": rows,
        "target_runtime_schema": manifest["runtime_schema"],
        "migration": "NONE",
    }


def _safe_archive_relative(name: str) -> Path:
    prefix = "qingshan-storyclaw-workflow/"
    if not name.startswith(prefix):
        raise InstallBlocked("ARCHIVE_MEMBER_OUTSIDE_PREFIX", name)
    relative_text = name[len(prefix):].rstrip("/")
    if not relative_text:
        return Path(".")
    pure = PurePosixPath(relative_text)
    if pure.is_absolute() or ".." in pure.parts or any(part in {"", "."} for part in pure.parts):
        raise InstallBlocked("ARCHIVE_MEMBER_PATH_INVALID", name)
    return Path(*pure.parts)


def _extract_release_archive(archive: Path, destination: Path) -> dict[str, Any]:
    total_bytes = 0
    declared_bytes = 0
    file_count = 0
    member_count = 0
    seen: set[str] = set()
    release_manifest: dict[str, Any] | None = None
    try:
        # Stream members so count and expanded-size limits are enforced before
        # tar metadata or payloads can be accumulated in memory/disk.
        source = tarfile.open(archive, mode="r|gz")
    except (OSError, tarfile.TarError) as exc:
        raise InstallBlocked("SOURCE_ARCHIVE_INVALID", str(archive)) from exc
    with source:
        for member in source:
            member_count += 1
            if member_count > 20000:
                raise InstallBlocked("SOURCE_ARCHIVE_TOO_MANY_MEMBERS", str(member_count))
            relative = _safe_archive_relative(member.name)
            if relative == Path("."):
                if not member.isdir():
                    raise InstallBlocked("ARCHIVE_PREFIX_ENTRY_INVALID")
                continue
            key = relative.as_posix()
            if key in seen:
                raise InstallBlocked("ARCHIVE_DUPLICATE_MEMBER", key)
            seen.add(key)
            if key.startswith(FORBIDDEN_ARCHIVE_PREFIXES):
                raise InstallBlocked("ARCHIVE_PRIVATE_RUNTIME_PATH_FORBIDDEN", key)
            lowered_parts = {part.lower() for part in relative.parts}
            if (
                ".env" in lowered_parts
                or "credentials.json" in lowered_parts
                or "secrets.json" in lowered_parts
                or any("token" in part and part.endswith(".json") for part in lowered_parts)
            ):
                raise InstallBlocked("ARCHIVE_CREDENTIAL_PATH_FORBIDDEN", key)
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise InstallBlocked("ARCHIVE_SPECIAL_MEMBER_FORBIDDEN", key)
            target = destination / relative
            if not _inside(target, destination):
                raise InstallBlocked("ARCHIVE_MEMBER_ESCAPES_DESTINATION", key)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o755)
                continue
            if not member.isfile():
                raise InstallBlocked("ARCHIVE_MEMBER_TYPE_INVALID", key)
            if member.size < 0 or member.size > 128 * 1024 * 1024:
                raise InstallBlocked("ARCHIVE_MEMBER_SIZE_INVALID", key)
            declared_bytes += member.size
            if declared_bytes > 1024 * 1024 * 1024:
                raise InstallBlocked("SOURCE_ARCHIVE_EXPANDED_SIZE_EXCEEDED")
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            stream = source.extractfile(member)
            if stream is None:
                raise InstallBlocked("ARCHIVE_MEMBER_READ_FAILED", key)
            with stream, target.open("xb") as output:
                actual_size = 0
                while True:
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    actual_size += len(chunk)
                    total_bytes += len(chunk)
                    if actual_size > member.size or total_bytes > 1024 * 1024 * 1024:
                        raise InstallBlocked("SOURCE_ARCHIVE_EXPANDED_SIZE_EXCEEDED")
                    output.write(chunk)
                if actual_size != member.size:
                    raise InstallBlocked("ARCHIVE_MEMBER_SIZE_MISMATCH", key)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(target, 0o755 if member.mode & 0o111 else 0o644)
            file_count += 1
            if key == "RELEASE_MANIFEST.json":
                try:
                    value = json.loads(target.read_text(encoding="utf-8"))
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise InstallBlocked("ARCHIVE_RELEASE_MANIFEST_INVALID") from exc
                if not isinstance(value, dict):
                    raise InstallBlocked("ARCHIVE_RELEASE_MANIFEST_INVALID")
                release_manifest = value
    if release_manifest is None:
        raise InstallBlocked("ARCHIVE_RELEASE_MANIFEST_MISSING")
    return {
        "file_count": file_count,
        "member_count": member_count,
        "expanded_bytes": total_bytes,
        "release_manifest": release_manifest,
    }


def _validate_archive_release_manifest(
    release: Mapping[str, Any], channel: Mapping[str, Any]
) -> None:
    if release.get("schema") != ARCHIVE_RELEASE_SCHEMA:
        raise InstallBlocked("ARCHIVE_RELEASE_MANIFEST_SCHEMA_INVALID")
    if release.get("release_tag") != channel["release_tag"]:
        raise InstallBlocked("ARCHIVE_RELEASE_TAG_MISMATCH")
    if str(release.get("git_commit") or "").lower() != channel["git_commit"]:
        raise InstallBlocked("ARCHIVE_RELEASE_COMMIT_MISMATCH")
    if release.get("private_runtime_included") is not False:
        raise InstallBlocked("ARCHIVE_PRIVATE_RUNTIME_FLAG_INVALID")
    if release.get("credentials_included") is not False:
        raise InstallBlocked("ARCHIVE_CREDENTIAL_FLAG_INVALID")


def _path_content_digest(path: Path) -> str:
    digest = hashlib.sha256()
    if not os.path.lexists(path):
        digest.update(b"MISSING\0")
        return digest.hexdigest()
    if path.is_symlink():
        digest.update(b"SYMLINK\0" + os.fsencode(os.readlink(path)))
        return digest.hexdigest()
    if path.is_file():
        digest.update(b"FILE\0" + path.read_bytes())
        return digest.hexdigest()
    digest.update(b"DIRECTORY\0")
    children = [
        child for child in path.rglob("*")
        if "__pycache__" not in child.relative_to(path).parts
        and child.name != ".DS_Store"
        and child.suffix not in {".pyc", ".pyo"}
    ]
    for child in sorted(children, key=lambda value: value.relative_to(path).as_posix()):
        relative = child.relative_to(path).as_posix().encode("utf-8", "surrogateescape")
        digest.update(relative + b"\0")
        if child.is_symlink():
            digest.update(b"L\0" + os.fsencode(os.readlink(child)))
        elif child.is_file():
            digest.update(b"F\0" + bytes.fromhex(_sha256_file(child)))
        elif child.is_dir():
            digest.update(b"D\0")
    return digest.hexdigest()


def _talenthub_managed_changes(current: Path, candidate: Path) -> list[str]:
    managed = set(TALENTHUB_MANAGED_EXACT)
    managed.update(TALENTHUB_MANAGED_TREE_ROOTS)
    for engine in (current, candidate):
        for prefix in TALENTHUB_MANAGED_FILE_PREFIXES:
            parent = engine / Path(prefix).parent
            if not parent.is_dir():
                continue
            relative_prefix = prefix
            for path in parent.rglob("*"):
                if path.is_file() or path.is_symlink():
                    relative = path.relative_to(engine).as_posix()
                    if relative.startswith(relative_prefix):
                        managed.add(relative)
    return [
        relative for relative in sorted(managed)
        if _path_content_digest(current / relative) != _path_content_digest(candidate / relative)
    ]


def _tree_digest(engine: Path) -> str:
    digest = hashlib.sha256()
    excluded = {Path(target) for _, target, _ in WIRE_SPECS}
    for path in sorted(engine.rglob("*"), key=lambda value: value.relative_to(engine).as_posix()):
        relative = path.relative_to(engine)
        if any(relative == item or item in relative.parents for item in excluded):
            continue
        encoded = relative.as_posix().encode("utf-8", "surrogateescape")
        digest.update(encoded + b"\0")
        if path.is_symlink():
            digest.update(b"L\0" + os.fsencode(os.readlink(path)))
        elif path.is_file():
            digest.update(b"F\0" + bytes.fromhex(_sha256_file(path)))
        elif path.is_dir():
            digest.update(b"D\0")
    return digest.hexdigest()


def _seal_extracted_engine(engine: Path) -> dict[str, Any]:
    """Seal a verified extracted tree; only the two verified runtime links may exist."""
    files: list[Path] = []
    directories: list[Path] = []
    allowed_links = {Path(target) for _, target, _ in WIRE_SPECS}
    for root, names, filenames in os.walk(engine, topdown=True, followlinks=False):
        root_path = Path(root)
        kept_names: list[str] = []
        for name in names:
            path = root_path / name
            if path.is_symlink():
                if path.relative_to(engine) not in allowed_links:
                    raise InstallBlocked(
                        "EXTRACTED_ENGINE_SPECIAL_ENTRY", str(path.relative_to(engine))
                    )
                continue
            if not path.is_dir():
                raise InstallBlocked(
                    "EXTRACTED_ENGINE_SPECIAL_ENTRY", str(path.relative_to(engine))
                )
            kept_names.append(name)
        names[:] = kept_names
        for filename in filenames:
            path = root_path / filename
            if path.is_symlink() or not path.is_file():
                raise InstallBlocked(
                    "EXTRACTED_ENGINE_SPECIAL_ENTRY", str(path.relative_to(engine))
                )
            files.append(path)
        directories.append(root_path)
    if not files:
        raise InstallBlocked("EXTRACTED_ENGINE_FILES_EMPTY")
    for path in files:
        _strip_write_bits(path)
    for path in sorted(directories, key=lambda value: len(value.parts), reverse=True):
        _strip_write_bits(path)
    writable = [
        str(path.relative_to(engine)) if path != engine else "."
        for path in [*files, *directories]
        if not path.is_symlink() and stat.S_IMODE(path.stat().st_mode) & 0o222
    ]
    if writable:
        raise InstallBlocked("UPGRADE_ENGINE_SEAL_FAILED", ",".join(writable[:10]))
    _require_engine_root_write_blocked(engine)
    report = _extracted_sealed_report(engine)
    report.update({
        "file_count": len(files),
        "directory_count": len(directories),
        "root_write_probe": "BLOCKED_AS_REQUIRED",
    })
    return report


def _remove_readonly_tree(path: Path) -> None:
    if not os.path.lexists(path):
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    for root, directories, files in os.walk(path, topdown=True, followlinks=False):
        root_path = Path(root)
        try:
            os.chmod(root_path, stat.S_IMODE(root_path.stat().st_mode) | 0o700)
        except OSError:
            pass
        for name in directories:
            candidate = root_path / name
            if candidate.is_symlink():
                continue
            try:
                os.chmod(candidate, stat.S_IMODE(candidate.stat().st_mode) | 0o700)
            except OSError:
                pass
    shutil.rmtree(path)


def _run_candidate_preflight(
    candidate: Path,
    runtime: Path,
    python: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
) -> dict[str, Any]:
    adapter = candidate / "tools" / "storyclaw_nalu_runtime.py"
    if not adapter.is_file():
        raise InstallBlocked("CANDIDATE_PREFLIGHT_ADAPTER_MISSING")
    if not python.is_file():
        raise InstallBlocked("PREFLIGHT_PYTHON_MISSING", str(python))
    environment = os.environ.copy()
    environment.pop("GIGGLE_API_KEY", None)
    environment.update({
        "NALU_ENGINE_ROOT": str(candidate),
        "NALU_RUNTIME_ROOT": str(runtime),
        "NALU_VENV_PYTHON": str(python),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    result = runner(
        [str(python), str(adapter), "preflight"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if result.returncode != 0:
        raise InstallBlocked("CANDIDATE_PREFLIGHT_FAILED", str(result.returncode))
    return {"status": "PASS", "exit_code": 0, "paid_provider_key_injected": False}


def _atomic_switch(link: Path, target: Path) -> None:
    _atomic_switch_raw(link, str(target))


def _atomic_switch_raw(link: Path, target: str) -> None:
    """Replace ``link`` with a symlink whose stored target is exactly ``target``."""
    _upgrade_transaction.atomic_symlink_raw(link, target)


def upgrade_engine(
    engine_link: Path,
    releases_root: Path,
    runtime_root: Path,
    *,
    channel_manifest: Path,
    channel_manifest_sha256: str,
    archive: Path,
    talenthub_release_manifest: Path | None = None,
    dependency_manifest: Path | None = None,
    dependency_archive: Path | None = None,
    install_deps: bool = False,
    new_venv_path: Path | None = None,
    python_executable: str = sys.executable,
    preflight_python: Path | None = None,
    preflight_runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
    dependency_installer: Callable[..., dict[str, Any]] = install_dependencies,
) -> dict[str, Any]:
    """Apply a release while holding the runtime-wide exclusive barrier."""
    runtime = _resolve_directory(runtime_root, "RUNTIME_ROOT")
    with _upgrade_barrier(runtime):
        try:
            _upgrade_transaction.recover(runtime)
        except _upgrade_transaction.RecoveryBlocked as exc:
            raise InstallBlocked("UPGRADE_RECOVERY_BLOCKED", str(exc)) from exc
        return _upgrade_engine_locked(
            engine_link,
            releases_root,
            runtime,
            channel_manifest=channel_manifest,
            channel_manifest_sha256=channel_manifest_sha256,
            archive=archive,
            talenthub_release_manifest=talenthub_release_manifest,
            dependency_manifest=dependency_manifest,
            dependency_archive=dependency_archive,
            install_deps=install_deps,
            new_venv_path=new_venv_path,
            python_executable=python_executable,
            preflight_python=preflight_python,
            preflight_runner=preflight_runner,
            dependency_installer=dependency_installer,
        )


def _upgrade_engine_locked(
    engine_link: Path,
    releases_root: Path,
    runtime_root: Path,
    *,
    channel_manifest: Path,
    channel_manifest_sha256: str,
    archive: Path,
    talenthub_release_manifest: Path | None = None,
    dependency_manifest: Path | None = None,
    dependency_archive: Path | None = None,
    install_deps: bool = False,
    new_venv_path: Path | None = None,
    python_executable: str = sys.executable,
    preflight_python: Path | None = None,
    preflight_runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
    dependency_installer: Callable[..., dict[str, Any]] = install_dependencies,
) -> dict[str, Any]:
    """Apply an immutable release with package binding and atomic rollback.

    Downloading the channel manifest and archive is intentionally outside this
    function.  The caller must provide a trusted manifest SHA-256; this updater
    never follows ``main`` and never makes a network request.
    """
    runtime = _resolve_directory(runtime_root, "RUNTIME_ROOT")
    link = engine_link.expanduser()
    if not link.is_absolute():
        link = link.absolute()
    if not link.is_symlink():
        raise InstallBlocked("ENGINE_LINK_MUST_BE_SYMLINK", str(link))
    try:
        current = link.resolve(strict=True)
    except OSError as exc:
        raise InstallBlocked("CURRENT_ENGINE_LINK_BROKEN", str(link)) from exc
    if not current.is_dir():
        raise InstallBlocked("CURRENT_ENGINE_INVALID", str(current))
    releases = releases_root.expanduser()
    if not releases.is_absolute():
        releases = releases.absolute()
    prospective_releases = releases.resolve(strict=False)
    if _inside(prospective_releases, runtime) or _inside(runtime, prospective_releases):
        raise InstallBlocked("RELEASES_RUNTIME_OVERLAP", f"{prospective_releases} :: {runtime}")
    if _inside(link, runtime):
        raise InstallBlocked("ENGINE_LINK_INSIDE_RUNTIME", str(link))
    if not releases.exists():
        releases.mkdir(parents=True, mode=0o755)
    releases = releases.resolve(strict=True)
    if _inside(releases, runtime) or _inside(runtime, releases):
        raise InstallBlocked("RELEASES_RUNTIME_OVERLAP", f"{releases} :: {runtime}")
    if not _inside(current, releases):
        raise InstallBlocked("CURRENT_ENGINE_OUTSIDE_RELEASES_ROOT", str(current))

    manifest, manifest_sha = _load_channel_manifest(
        channel_manifest, channel_manifest_sha256
    )
    channel_path = channel_manifest.expanduser().resolve(strict=True)
    package_binding: dict[str, Any] | None = None
    if manifest["update_class"] == PACKAGE_REQUIRED:
        package_binding = _validate_talenthub_release_manifest(
            talenthub_release_manifest,
            channel=manifest,
            channel_sha256=manifest_sha,
            channel_size=channel_path.stat().st_size,
        )
    elif talenthub_release_manifest is not None:
        raise InstallBlocked(
            "TALENTHUB_PACKAGE_EVIDENCE_UNEXPECTED",
            "ENGINE_ONLY releases do not use package override evidence",
        )

    dependency_path: Path | None = None
    try:
        archive_path = archive.expanduser().resolve(strict=True)
    except OSError as exc:
        raise InstallBlocked("SOURCE_ARCHIVE_NOT_FOUND", str(archive)) from exc
    if archive_path.stat().st_size != manifest["source_archive_size_bytes"]:
        raise InstallBlocked(
            "SOURCE_ARCHIVE_SIZE_MISMATCH",
            f"expected={manifest['source_archive_size_bytes']},actual={archive_path.stat().st_size}",
        )
    archive_sha = _sha256_file(archive_path)
    if archive_sha != manifest["source_archive_sha256"]:
        raise InstallBlocked(
            "SOURCE_ARCHIVE_SHA256_MISMATCH",
            f"expected={manifest['source_archive_sha256']},actual={archive_sha}",
        )
    upgrade_authority = _trusted_upgrade_authority(
        runtime,
        current,
        manifest,
        channel_path=channel_path,
        channel_sha256=manifest_sha,
    )
    runtime_check = _check_runtime_upgrade_safe(runtime, manifest)

    safe_tag = re.sub(r"[^A-Za-z0-9._-]+", "-", manifest["release_tag"]).strip("-.")
    release_name = f"{safe_tag}-{manifest['git_commit'][:12]}"
    if not _SAFE_RELEASE_DIR_RE.fullmatch(release_name):
        raise InstallBlocked("RELEASE_DIRECTORY_NAME_INVALID", release_name)
    candidate = releases / release_name
    receipt_path = runtime / UPGRADE_RECEIPT_ROOT_RELATIVE / f"{manifest['git_commit']}.json"

    if (
        upgrade_authority["status"] == "ALREADY_CURRENT_IDENTITY"
        and candidate != current
    ):
        raise InstallBlocked(
            "CURRENT_RELEASE_PATH_MISMATCH",
            f"recorded={current},expected={candidate}",
        )

    if candidate == current:
        try:
            existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InstallBlocked("CURRENT_UPGRADE_RECEIPT_INVALID", str(receipt_path)) from exc
        if (
            not isinstance(existing, dict)
            or existing.get("schema") != UPGRADE_RECEIPT_SCHEMA
            or existing.get("status") != "PASS"
            or existing.get("source_archive_sha256") != archive_sha
            or existing.get("channel_manifest_sha256") != manifest_sha
            or existing.get("update_class") != manifest["update_class"]
            or existing.get("release_sequence") != manifest["release_sequence"]
            or existing.get("candidate_tree_sha256") != _tree_digest(candidate)
        ):
            raise InstallBlocked("CURRENT_UPGRADE_RECEIPT_MISMATCH", str(receipt_path))
        if package_binding is not None and (
            (existing.get("talenthub_package_binding") or {}).get("sha256")
            != package_binding["sha256"]
        ):
            raise InstallBlocked("CURRENT_UPGRADE_RECEIPT_MISMATCH", "TalentHub binding")
        wiring = _wire_report(_backing_paths(candidate, runtime, create=False), probe=True)
        prior_dependency = existing.get("dependency_update") or {}
        selector_expected = (
            Path(str(prior_dependency.get("venv")))
            if prior_dependency.get("status") == "INSTALLED_NEW_PRIVATE_VENV"
            and prior_dependency.get("venv")
            else None
        )
        selector_report = _venv_selector_report(
            runtime,
            required=selector_expected is not None,
            expected_target=selector_expected,
        )
        return {
            "schema": SCHEMA,
            "command": "UPGRADE",
            "status": "ALREADY_CURRENT",
            "release_tag": manifest["release_tag"],
            "release_sequence": manifest["release_sequence"],
            "git_commit": manifest["git_commit"],
            "engine": str(candidate),
            "wiring": wiring,
            "runtime_preserved": True,
            "network_used": False,
            "update_class": manifest["update_class"],
            "talenthub_package_binding": existing.get("talenthub_package_binding"),
            "dependency_update": existing.get("dependency_update"),
            "venv_selector": selector_report,
            "upgrade_authority": upgrade_authority,
            "receipt": str(receipt_path),
        }
    if manifest["dependencies_changed"]:
        if not install_deps or new_venv_path is None:
            raise InstallBlocked(
                "DEPENDENCY_UPGRADE_REQUIRES_NEW_PRIVATE_VENV",
                "rerun with --install-deps --new-venv-path "
                "<runtime>/runtime/storyclaw_host/venvs/<release-tag>; the old venv "
                "is never reused",
            )
        dependency_path = _checked_private_venv(new_venv_path, runtime, current)
        if os.path.lexists(dependency_path):
            raise InstallBlocked("NEW_VENV_PATH_ALREADY_EXISTS", str(dependency_path))
        previous_venv_selector = _venv_selector_report(runtime, required=True)
    elif install_deps or new_venv_path is not None:
        raise InstallBlocked(
            "DEPENDENCY_INSTALL_NOT_DECLARED_BY_RELEASE",
            "channel manifest declares dependencies_changed=false",
        )
    else:
        previous_venv_selector = _venv_selector_report(runtime, required=False)
    if os.path.lexists(candidate):
        raise InstallBlocked("RELEASE_DIRECTORY_ALREADY_EXISTS", str(candidate))

    staging = Path(tempfile.mkdtemp(prefix=f".{release_name}.", dir=releases))
    switched = False
    venv_switched = False
    prior_raw_link = os.readlink(link)
    selector_path = runtime / VENV_SELECTOR_RELATIVE
    prior_raw_venv_link = (
        os.readlink(selector_path) if manifest["dependencies_changed"] else None
    )
    prior_current_release_state = dict(upgrade_authority["current"])
    prior_discovery_state = (
        dict(upgrade_authority["discovery"])
        if isinstance(upgrade_authority.get("discovery"), dict)
        else None
    )
    receipt_written = False
    current_release_state_written = False
    discovery_state_written = False
    journal_written = False
    completed_candidate = False
    try:
        extraction = _extract_release_archive(archive_path, staging)
        _validate_archive_release_manifest(extraction["release_manifest"], manifest)
        for marker in ENGINE_MARKERS:
            if not (staging / marker).is_file():
                raise InstallBlocked("CANDIDATE_ENGINE_MARKER_MISSING", marker)
        protected_changes = _talenthub_managed_changes(current, staging)
        if protected_changes and (
            manifest["update_class"] != PACKAGE_REQUIRED or package_binding is None
        ):
            raise InstallBlocked("TALENTHUB_REPUBLISH_REQUIRED", ",".join(protected_changes))

        staging_rows = _backing_paths(staging, runtime, create=False)
        for row in staging_rows:
            _wire_target(Path(row["target"]), Path(row["backing"]))
        _wire_report(staging_rows, probe=True)
        os.replace(staging, candidate)
        completed_candidate = True
        candidate_rows = _backing_paths(candidate, runtime, create=False)
        wiring = _wire_report(candidate_rows, probe=True)
        dependency_update: dict[str, Any]
        if manifest["dependencies_changed"]:
            assert dependency_path is not None
            dependency_update = dependency_installer(
                candidate,
                runtime,
                venv_path=dependency_path,
                python_executable=python_executable,
                dependency_manifest=dependency_manifest,
                dependency_archive=dependency_archive,
                release_tag=manifest["release_tag"],
                git_commit=manifest["git_commit"],
                release_sequence=manifest["release_sequence"],
                expected_binding=manifest["dependency_profile_bindings"],
            )
            dependency_python = Path(str(dependency_update.get("python") or ""))
            try:
                dependency_python = dependency_python.expanduser().resolve(strict=True)
            except OSError as exc:
                raise InstallBlocked(
                    "NEW_VENV_PYTHON_MISSING", str(dependency_update.get("python"))
                ) from exc
            try:
                resolved_dependency_path = dependency_path.resolve(strict=True)
            except OSError as exc:
                raise InstallBlocked("NEW_VENV_PATH_INVALID", str(dependency_path)) from exc
            if dependency_path.is_symlink() or not resolved_dependency_path.is_dir():
                raise InstallBlocked("NEW_VENV_PATH_INVALID", str(dependency_path))
            if not _inside(dependency_python, resolved_dependency_path):
                raise InstallBlocked(
                    "NEW_VENV_PYTHON_ESCAPES_VENV", str(dependency_python)
                )
            try:
                requested_preflight_python = (
                    preflight_python.expanduser().resolve(strict=True)
                    if preflight_python is not None
                    else None
                )
            except OSError as exc:
                raise InstallBlocked(
                    "PREFLIGHT_PYTHON_MISSING", str(preflight_python)
                ) from exc
            if (
                requested_preflight_python is not None
                and requested_preflight_python != dependency_python
            ):
                raise InstallBlocked(
                    "PREFLIGHT_PYTHON_MUST_MATCH_NEW_VENV", str(dependency_python)
                )
            python = dependency_python
            dependency_update = {
                **dependency_update,
                "status": "INSTALLED_NEW_PRIVATE_VENV",
                "activation_required": False,
                "installed_venv_python": str(dependency_python),
                # Production always enters through this project-local stable
                # selector.  Its resolved target changes only while the same
                # exclusive barrier that switches the engine is held.
                "next_nalu_venv_python": str(_venv_python_path(selector_path)),
            }
        else:
            dependency_update = {
                "status": "UNCHANGED",
                "network_used": False,
                "activation_required": False,
            }
            python = preflight_python
            if python is None and previous_venv_selector.get("status") == "PASS":
                python = Path(str(previous_venv_selector["resolved_python"]))
            if python is None:
                private_python = runtime / DEFAULT_VENV_RELATIVE / (
                    "Scripts/python.exe" if os.name == "nt" else "bin/python"
                )
                python = private_python if private_python.is_file() else Path(sys.executable)
            try:
                python = python.expanduser().resolve(strict=True)
            except OSError as exc:
                raise InstallBlocked("PREFLIGHT_PYTHON_MISSING", str(python)) from exc
        seal = _seal_extracted_engine(candidate)
        preflight = _run_candidate_preflight(
            candidate, runtime, python, runner=preflight_runner
        )
        tree_sha = _tree_digest(candidate)

        try:
            _upgrade_transaction.write_prepared(runtime, {
                "prepared_at_utc": utc_now(),
                "releases_root": str(releases),
                "engine_link": str(link),
                "old_engine": str(current),
                "new_engine": str(candidate),
                "old_engine_raw_link": prior_raw_link,
                "venv_selector": str(selector_path),
                "old_venv": previous_venv_selector.get("target"),
                "new_venv": str(dependency_path) if dependency_path is not None else None,
                "old_venv_raw_link": prior_raw_venv_link,
                "current_release_state_path": str(
                    runtime / CURRENT_RELEASE_STATE_RELATIVE
                ),
                "discovery_state_path": str(runtime / DISCOVERY_STATE_RELATIVE),
                "prior_current_release_state": prior_current_release_state,
                "prior_discovery_state": prior_discovery_state,
                "receipt_path": str(receipt_path),
            })
        except _upgrade_transaction.RecoveryBlocked as exc:
            raise InstallBlocked("UPGRADE_JOURNAL_BLOCKED", str(exc)) from exc
        journal_written = True

        if manifest["dependencies_changed"]:
            assert dependency_path is not None
            _atomic_switch(selector_path, dependency_path)
            venv_switched = True
            current_venv_selector = _venv_selector_report(
                runtime, required=True, expected_target=dependency_path
            )
            dependency_update = {
                **dependency_update,
                "previous_selector": previous_venv_selector,
                "current_selector": current_venv_selector,
            }
        else:
            current_venv_selector = previous_venv_selector

        _atomic_switch(link, candidate)
        switched = True
        if link.resolve(strict=True) != candidate:
            raise InstallBlocked("ATOMIC_SWITCH_VERIFICATION_FAILED")
        if manifest["dependencies_changed"]:
            # Re-check after the engine switch so a post-switch receipt cannot
            # claim a pair that is no longer selected.
            current_venv_selector = _venv_selector_report(
                runtime, required=True, expected_target=dependency_path
            )
        post_switch_wiring = _wire_report(
            _backing_paths(link, runtime, create=False), probe=True
        )
        receipt = {
            "schema": UPGRADE_RECEIPT_SCHEMA,
            "status": "PASS",
            "upgraded_at_utc": utc_now(),
            "channel": manifest["channel"],
            "release_tag": manifest["release_tag"],
            "release_sequence": manifest["release_sequence"],
            "git_commit": manifest["git_commit"],
            "channel_manifest_sha256": manifest_sha,
            "source_archive_sha256": archive_sha,
            "source_archive_size_bytes": archive_path.stat().st_size,
            "candidate_tree_sha256": tree_sha,
            "previous_engine": str(current),
            "current_engine": str(candidate),
            "runtime_root": str(runtime),
            "runtime_preserved": True,
            "runtime_check": runtime_check,
            "update_class": manifest["update_class"],
            "talenthub_package_binding": package_binding,
            "dependency_update": dependency_update,
            "previous_venv_selector": previous_venv_selector,
            "current_venv_selector": current_venv_selector,
            "upgrade_authority": upgrade_authority,
            "preflight": preflight,
            "wiring": post_switch_wiring,
            "engine_seal": seal,
            "talenthub_managed_files_changed": protected_changes,
            "network_used": False,
        }
        _atomic_json(receipt_path, receipt, runtime)
        receipt_written = True
        current_release_state = {
            "schema": CURRENT_RELEASE_STATE_SCHEMA,
            "status": "PASS",
            "recorded_at_utc": utc_now(),
            "release_sequence": manifest["release_sequence"],
            "release_tag": manifest["release_tag"],
            "git_commit": manifest["git_commit"],
            "signing_key_sha256": RELEASE_SIGNING_PUBLIC_KEY_SHA256,
            "talenthub_release_manifest_sha256": (
                package_binding["sha256"]
                if package_binding is not None
                else prior_current_release_state.get(
                    "talenthub_release_manifest_sha256"
                )
            ),
            "validation_receipt_sha256": manifest["validation_receipt_sha256"],
            "engine": str(candidate),
            "venv_selector": current_venv_selector,
            "upgrade_receipt": str(receipt_path),
        }
        _atomic_json(
            runtime / CURRENT_RELEASE_STATE_RELATIVE,
            current_release_state,
            runtime,
        )
        current_release_state_written = True
        if prior_discovery_state is not None:
            applied_discovery_state = {
                **prior_discovery_state,
                "status": "APPLIED",
                "current_release_tag": manifest["release_tag"],
                "current_release_commit": manifest["git_commit"],
                "baseline_release_sequence": manifest["release_sequence"],
                "applied_at_utc": utc_now(),
                "upgrade_receipt": str(receipt_path),
            }
            _atomic_json(
                runtime / DISCOVERY_STATE_RELATIVE,
                applied_discovery_state,
                runtime,
            )
            discovery_state_written = True
        _upgrade_transaction.clear(runtime)
        journal_written = False
        receipt_sha = _sha256_file(receipt_path)
        return {
            "schema": SCHEMA,
            "command": "UPGRADE",
            "status": "PASS",
            "release_tag": manifest["release_tag"],
            "release_sequence": manifest["release_sequence"],
            "git_commit": manifest["git_commit"],
            "previous_engine": str(current),
            "current_engine": str(candidate),
            "runtime_preserved": True,
            "runtime_check": runtime_check,
            "update_class": manifest["update_class"],
            "talenthub_package_binding": package_binding,
            "dependency_update": dependency_update,
            "previous_venv_selector": previous_venv_selector,
            "venv_selector": current_venv_selector,
            "upgrade_authority": upgrade_authority,
            "current_release_state": current_release_state,
            "preflight": preflight,
            "wiring": post_switch_wiring,
            "network_used": False,
            "receipt": {"path": str(receipt_path), "sha256": receipt_sha},
        }
    except Exception as original_error:
        rollback_failures: list[str] = []
        if switched:
            try:
                _atomic_switch_raw(link, prior_raw_link)
                if link.resolve(strict=True) != current:
                    raise OSError(f"resolved to {link.resolve(strict=False)}")
            except OSError as exc:
                rollback_failures.append(f"engine:{exc}")
        if venv_switched:
            try:
                assert prior_raw_venv_link is not None
                _atomic_switch_raw(selector_path, prior_raw_venv_link)
                expected_previous = Path(str(previous_venv_selector["target"]))
                _venv_selector_report(
                    runtime, required=True, expected_target=expected_previous
                )
            except (AssertionError, KeyError, OSError, InstallBlocked) as exc:
                rollback_failures.append(f"venv:{exc}")
        if rollback_failures:
            raise InstallBlocked(
                "ATOMIC_UPGRADE_ROLLBACK_FAILED", ";".join(rollback_failures)
            ) from original_error
        if discovery_state_written and prior_discovery_state is not None:
            _atomic_json(
                runtime / DISCOVERY_STATE_RELATIVE,
                prior_discovery_state,
                runtime,
            )
        if current_release_state_written:
            _atomic_json(
                runtime / CURRENT_RELEASE_STATE_RELATIVE,
                prior_current_release_state,
                runtime,
            )
        if receipt_written and receipt_path.is_file():
            receipt_path.unlink()
        if completed_candidate:
            _remove_readonly_tree(candidate)
        else:
            _remove_readonly_tree(staging)
        if dependency_path is not None and os.path.lexists(dependency_path):
            _remove_readonly_tree(dependency_path)
        if journal_written:
            _upgrade_transaction.clear(runtime)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install or verify a tagged NALU checkout on a StoryClaw host."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(command: argparse.ArgumentParser, *, tag_required: bool) -> None:
        command.add_argument("--engine-root", type=Path, required=True)
        command.add_argument("--runtime-root", type=Path, required=True)
        command.add_argument("--release-tag", required=tag_required)
        command.add_argument("--expected-commit")
        command.add_argument("--venv-path", type=Path)

    install = subparsers.add_parser(
        "install",
        help="Create a per-project engine view, wire private storage, and verify the host.",
    )
    common(install, tag_required=True)
    install.add_argument(
        "--install-deps",
        action="store_true",
        help="Install the release-bound dependency bundle offline into a private venv.",
    )
    install.add_argument("--dependency-manifest", type=Path)
    install.add_argument("--dependency-archive", type=Path)
    install.add_argument(
        "--acceptance-channel-manifest",
        type=Path,
        help=(
            "Unvalidated immutable channel manifest used only for maintainer "
            "StoryClaw acceptance; never creates production or upgrade authority."
        ),
    )
    install.add_argument("--acceptance-channel-manifest-sha256")
    install.add_argument("--python", default=sys.executable)
    install.add_argument(
        "--talenthub-release-manifest",
        type=Path,
        help=(
            f"Installed skills/{SKILL_NAME}/RELEASE_MANIFEST.json from this Agent package; "
            "required to establish the trusted sequence used by automatic upgrades."
        ),
    )
    install.add_argument(
        "--verified-bootstrap-archive",
        type=Path,
        help=(
            "First-install source archive already size/SHA-bound by the installed "
            "TalentHub manifest; permits a verified extracted archive project view."
        ),
    )
    install.add_argument(
        "--project-view-root",
        type=Path,
        help=(
            "Create or reuse a detached per-project Git worktree at the exact release commit; "
            "required for multiple host projects when mount namespaces are unavailable."
        ),
    )
    install.add_argument(
        "--project-engine-link",
        type=Path,
        help=(
            "Recommended stable symlink for the per-project engine view, used for atomic "
            "upgrades (requires --project-view-root)."
        ),
    )
    install.add_argument(
        "--isolated-mount-namespace",
        action="store_true",
        help=(
            "Explicitly assert that this process has a per-project mount namespace; only "
            "then may the installer wire the supplied engine root directly. Never use for "
            "a canonical checkout shared by host projects."
        ),
    )
    install.add_argument(
        "--seal-read-only",
        action="store_true",
        help="Strip write bits from Git-tracked public engine code after setup.",
    )

    inspect = subparsers.add_parser("inspect", help="Print read-only host facts as JSON.")
    common(inspect, tag_required=False)

    verify = subparsers.add_parser("verify", help="Run exact wiring and filesystem probes.")
    common(verify, tag_required=True)
    verify.add_argument("--require-sealed", action="store_true")

    upgrade = subparsers.add_parser(
        "upgrade",
        help="Atomically apply a locally supplied immutable release.",
    )
    upgrade.add_argument("--engine-link", type=Path, required=True)
    upgrade.add_argument("--releases-root", type=Path, required=True)
    upgrade.add_argument("--runtime-root", type=Path, required=True)
    upgrade.add_argument("--channel-manifest", type=Path, required=True)
    upgrade.add_argument("--channel-manifest-sha256", required=True)
    upgrade.add_argument("--archive", type=Path, required=True)
    upgrade.add_argument(
        "--talenthub-release-manifest",
        type=Path,
        help=(
            f"Installed skills/{SKILL_NAME}/RELEASE_MANIFEST.json from the TalentHub workspace; "
            "mandatory for TALENTHUB_PACKAGE_REQUIRED releases."
        ),
    )
    upgrade.add_argument(
        "--install-deps",
        action="store_true",
        help="Install the channel-bound dependency bundle offline when dependencies changed.",
    )
    upgrade.add_argument("--dependency-manifest", type=Path)
    upgrade.add_argument("--dependency-archive", type=Path)
    upgrade.add_argument(
        "--new-venv-path",
        type=Path,
        help="Brand-new private venv path required with --install-deps for dependency changes.",
    )
    upgrade.add_argument("--python", default=sys.executable)
    upgrade.add_argument("--preflight-python", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "install":
            report = install_host(
                args.engine_root,
                args.runtime_root,
                release_tag=args.release_tag,
                expected_commit=args.expected_commit,
                install_deps=args.install_deps,
                venv_path=args.venv_path,
                python_executable=args.python,
                seal_read_only=args.seal_read_only,
                project_view_root=args.project_view_root,
                project_engine_link=args.project_engine_link,
                isolated_mount_namespace=args.isolated_mount_namespace,
                talenthub_release_manifest=args.talenthub_release_manifest,
                verified_bootstrap_archive=args.verified_bootstrap_archive,
                dependency_manifest=args.dependency_manifest,
                dependency_archive=args.dependency_archive,
                acceptance_channel_manifest=args.acceptance_channel_manifest,
                acceptance_channel_manifest_sha256=(
                    args.acceptance_channel_manifest_sha256
                ),
            )
        elif args.command == "verify":
            report = verify_host(
                args.engine_root,
                args.runtime_root,
                release_tag=args.release_tag,
                expected_commit=args.expected_commit,
                require_sealed=args.require_sealed,
                venv_path=args.venv_path,
            )
        elif args.command == "inspect":
            report = inspect_host(
                args.engine_root,
                args.runtime_root,
                release_tag=args.release_tag,
                expected_commit=args.expected_commit,
                venv_path=args.venv_path,
            )
        else:
            report = upgrade_engine(
                args.engine_link,
                args.releases_root,
                args.runtime_root,
                channel_manifest=args.channel_manifest,
                channel_manifest_sha256=args.channel_manifest_sha256,
                archive=args.archive,
                talenthub_release_manifest=args.talenthub_release_manifest,
                dependency_manifest=args.dependency_manifest,
                dependency_archive=args.dependency_archive,
                install_deps=args.install_deps,
                new_venv_path=args.new_venv_path,
                python_executable=args.python,
                preflight_python=args.preflight_python,
            )
    except InstallBlocked as exc:
        print(json.dumps({
            "schema": ERROR_SCHEMA,
            "status": "BLOCKED",
            "code": exc.code,
            "detail": exc.detail,
        }, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
