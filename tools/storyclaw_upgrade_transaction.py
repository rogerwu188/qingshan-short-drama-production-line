#!/usr/bin/env python3
"""Crash recovery for the project engine/venv activation transaction.

The installer writes a durable PREPARED journal before changing either
selector and removes it only after links, receipts, and release state are
durable.  A producer that finds the journal takes the exclusive upgrade lock
and rolls the pair back before it may acquire the normal shared run lock.
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "storyclaw.nalu.upgrade_transaction.v1"
JOURNAL_RELATIVE = Path("runtime/storyclaw_host/upgrade-transaction.json")
VENV_SELECTOR_RELATIVE = Path("runtime/storyclaw_host/current-venv")


class RecoveryBlocked(RuntimeError):
    pass


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _canonical_entry(path: Path) -> Path:
    """Canonicalize a directory entry without following the final symlink."""
    expanded = path.expanduser()
    return expanded.parent.resolve(strict=True) / expanded.name


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        if os.path.lexists(temporary):
            temporary.unlink()


def atomic_symlink_raw(link: Path, raw_target: str) -> None:
    temporary = link.parent / f".{link.name}.storyclaw-recover-{secrets.token_hex(6)}"
    os.symlink(raw_target, temporary)
    try:
        os.replace(temporary, link)
        _fsync_directory(link.parent)
    finally:
        if os.path.lexists(temporary):
            temporary.unlink()


def _remove_tree(path: Path) -> None:
    if not os.path.lexists(path):
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    for root, directories, _files in os.walk(path, topdown=True, followlinks=False):
        root_path = Path(root)
        try:
            os.chmod(root_path, stat.S_IMODE(root_path.stat().st_mode) | 0o700)
        except OSError:
            pass
        for name in directories:
            child = root_path / name
            if not child.is_symlink():
                try:
                    os.chmod(child, stat.S_IMODE(child.stat().st_mode) | 0o700)
                except OSError:
                    pass
    shutil.rmtree(path)


def journal_path(runtime: Path) -> Path:
    return runtime / JOURNAL_RELATIVE


def write_prepared(runtime: Path, payload: Mapping[str, Any]) -> Path:
    path = journal_path(runtime)
    if os.path.lexists(path):
        raise RecoveryBlocked(f"upgrade journal already exists: {path}")
    atomic_json(path, {"schema": SCHEMA, "status": "PREPARED", **dict(payload)})
    return path


def clear(runtime: Path) -> None:
    path = journal_path(runtime)
    if path.exists():
        path.unlink()
        _fsync_directory(path.parent)


def recover(runtime: Path) -> dict[str, Any]:
    """Rollback one interrupted transaction. Caller must hold exclusive lock."""
    runtime = runtime.expanduser().resolve(strict=True)
    path = journal_path(runtime)
    if not path.is_file():
        return {"status": "NOT_NEEDED"}
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryBlocked(f"invalid upgrade journal: {path}") from exc
    if not isinstance(journal, dict) or journal.get("schema") != SCHEMA or journal.get("status") != "PREPARED":
        raise RecoveryBlocked(f"invalid upgrade journal contract: {path}")

    try:
        releases = Path(str(journal["releases_root"])).resolve(strict=True)
        engine_link = _canonical_entry(Path(str(journal["engine_link"])))
        old_engine = Path(str(journal["old_engine"])).resolve(strict=True)
        new_engine = Path(str(journal["new_engine"])).resolve(strict=False)
        selector = _canonical_entry(Path(str(journal["venv_selector"])))
    except (KeyError, OSError) as exc:
        raise RecoveryBlocked("upgrade journal paths are invalid") from exc
    if (
        engine_link.parent.resolve(strict=True) != releases.parent.resolve(strict=True)
        or selector != runtime / VENV_SELECTOR_RELATIVE
        or not _inside(old_engine, releases)
        or not _inside(new_engine, releases)
        or _inside(releases, runtime)
        or _inside(runtime, releases)
    ):
        raise RecoveryBlocked("upgrade journal path boundary check failed")
    if not engine_link.is_symlink():
        raise RecoveryBlocked("engine selector is unavailable during recovery")
    try:
        selected_engine = engine_link.resolve(strict=True)
    except OSError as exc:
        raise RecoveryBlocked("engine selector is broken during recovery") from exc
    if selected_engine not in {old_engine, new_engine}:
        raise RecoveryBlocked("engine selector target is outside interrupted transaction")

    old_engine_raw = str(journal.get("old_engine_raw_link") or "")
    if not old_engine_raw:
        raise RecoveryBlocked("old engine selector target missing")
    atomic_symlink_raw(engine_link, old_engine_raw)
    if engine_link.resolve(strict=True) != old_engine:
        raise RecoveryBlocked("engine selector rollback verification failed")

    old_venv_raw = journal.get("old_venv_raw_link")
    old_venv = journal.get("old_venv")
    new_venv = journal.get("new_venv")
    if old_venv_raw is not None:
        if not selector.is_symlink() or not old_venv or not new_venv:
            raise RecoveryBlocked("venv selector rollback contract missing")
        old_venv_path = Path(str(old_venv)).resolve(strict=True)
        new_venv_path = Path(str(new_venv)).resolve(strict=False)
        try:
            selected_venv = selector.resolve(strict=True)
        except OSError as exc:
            raise RecoveryBlocked("venv selector is broken during recovery") from exc
        if (
            not _inside(old_venv_path, runtime)
            or not _inside(new_venv_path, runtime)
            or selected_venv not in {old_venv_path, new_venv_path}
        ):
            raise RecoveryBlocked("venv selector target is outside interrupted transaction")
        atomic_symlink_raw(selector, str(old_venv_raw))
        if selector.resolve(strict=True) != old_venv_path:
            raise RecoveryBlocked("venv selector rollback verification failed")
    else:
        new_venv_path = None

    current_state_path = _canonical_entry(Path(str(journal["current_release_state_path"])))
    discovery_state_path = _canonical_entry(Path(str(journal["discovery_state_path"])))
    if (
        current_state_path != runtime / Path("runtime/storyclaw_host/current-release.json")
        or discovery_state_path != runtime / Path("runtime/storyclaw_release_discovery/trusted_state.json")
        or not isinstance(journal.get("prior_current_release_state"), dict)
    ):
        raise RecoveryBlocked("release-state recovery contract invalid")
    atomic_json(current_state_path, journal["prior_current_release_state"])
    prior_discovery = journal.get("prior_discovery_state")
    if isinstance(prior_discovery, dict):
        atomic_json(discovery_state_path, prior_discovery)

    receipt = _canonical_entry(Path(str(journal.get("receipt_path") or "")))
    receipt_root = runtime / "runtime/receipts/storyclaw_engine_upgrades"
    if _inside(receipt, receipt_root) and receipt.is_file():
        receipt.unlink()
        _fsync_directory(receipt.parent)
    if new_engine != old_engine and os.path.lexists(new_engine):
        _remove_tree(new_engine)
    if new_venv_path is not None and new_venv_path != Path(str(old_venv)).resolve(strict=True):
        _remove_tree(new_venv_path)

    clear(runtime)
    return {
        "status": "RECOVERED",
        "engine": str(old_engine),
        "venv": str(old_venv) if old_venv is not None else None,
    }
