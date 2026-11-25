#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""studio_asset_resolve.py — nalu-side entry to the studio asset library (S2 reuse, S5 keyframes, S6 video).

One resolver for every place that turns a recorded reference (old path + recorded sha256) into a local
file the renderer / reviewer / submitter will actually read:

  * the recorded path still exists and its bytes hash to the recorded sha  -> that path, exactly as before
    (so with the studio library disabled, behaviour is byte-for-byte the old behaviour);
  * otherwise, when the studio library is enabled and holds those exact bytes -> a COPY of the original
    under the library's work cache (same file name, same sha256), so a vanished episode folder no longer
    forces a paid regeneration;
  * otherwise None.

It never generates anything, never calls a provider, and never accepts bytes whose sha256 differs from
the one recorded.  If the library knows the bytes but its master is missing or damaged, the dependent
stage stops with STUDIO_ASSET_RESTORE_PENDING (a restore request is written); it does not fall through to
a paid redo.
"""
from __future__ import annotations
import sys as _sys, pathlib as _pathlib
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parents[0]))  # nalu_paths lives in tools/
import nalu_paths as _np  # portable ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON (env or auto-detect)

import os as _os
from pathlib import Path
from typing import Any


def _studio():
    engine = str(Path(f"{_np.ENGINE_ROOT}"))
    if engine not in _sys.path:
        _sys.path.insert(0, engine)
    from tools import studio_asset_library as studio  # noqa: PLC0415
    return studio


def resolve(path: Any, sha: Any, *, cache_dir: Any = None) -> Path | None:
    """Local path whose bytes are exactly ``sha`` (old path first, then the studio library, then an engine-restart
    archive), else None."""
    if not sha:
        return None
    studio = _studio()
    try:
        found = studio.resolve_reference(path, str(sha), cache_dir=cache_dir)
    except studio.StudioError as exc:
        if exc.code == "RESTORE_PENDING":
            raise SystemExit(f"STUDIO_ASSET_RESTORE_PENDING:{str(sha)[:12]}: the library knows these bytes but its "
                             "master is missing or damaged; run `studio_asset_library.py backup restore --sha256 "
                             "<sha>` (no regeneration was started)") from None
        return None
    return found if found is not None else restore_from_archive(path, sha)


def archive_root() -> Path:
    return Path(_os.environ.get("NALU_ARCHIVE_ROOT") or "~/nalu_archive").expanduser()


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def restore_from_archive(path: Any, sha: Any) -> Path | None:
    """An engine restart (skills/nalu-claude-code/scripts/engine_restart.py) MOVES the abandoned episode's files to
    ``~/nalu_archive/<EP>_abandoned_<UTC>_<sha7>/{engine,runtime}/<relative path>``.  A LOCKED library row that still
    records the old path (E28 2026-11-25, device …1101: reused characters failed
    ``cross_episode_reuse_source_not_locked_or_artifact_sha_mismatch`` after two restarts) is restored by copying the
    archived bytes back to the recorded path -- only when the sha matches exactly and nothing is at that path.
    Never generates anything; returns None when no archive holds those bytes."""
    if not path or not sha:
        return None
    recorded = Path(str(path))
    if recorded.exists():
        return None  # different bytes at the recorded path: never overwritten
    root = archive_root()
    if not root.is_dir():
        return None
    rels: list[tuple[str, Path]] = []
    for label, base in (("engine", Path(f"{_np.ENGINE_ROOT}")), ("runtime", Path(f"{_np.RUNTIME_ROOT}"))):
        try:
            rels.append((label, recorded.relative_to(base)))
        except ValueError:
            continue
    if not rels:
        return None
    try:
        archives = sorted((d for d in root.iterdir() if d.is_dir() and "_abandoned_" in d.name), reverse=True)
    except OSError:
        return None
    for archive in archives:
        for label, rel in rels:
            candidate = archive / label / rel
            try:
                if not candidate.is_file() or _sha256(candidate) != str(sha):
                    continue
                import shutil
                recorded.parent.mkdir(parents=True, exist_ok=True)
                tmp = recorded.with_name(recorded.name + ".restore.tmp")
                shutil.copy2(candidate, tmp)
                if _sha256(tmp) != str(sha):
                    tmp.unlink(missing_ok=True)
                    continue
                tmp.replace(recorded)
                return recorded
            except OSError:
                continue
    return None


def present(artifact: dict[str, Any]) -> bool:
    """True when the artifact's recorded bytes can be had locally (old path, or the studio original)."""
    return resolve(artifact.get("path"), artifact.get("sha256")) is not None
