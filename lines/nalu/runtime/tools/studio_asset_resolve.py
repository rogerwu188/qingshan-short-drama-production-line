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

from pathlib import Path
from typing import Any


def _studio():
    engine = str(Path(f"{_np.ENGINE_ROOT}"))
    if engine not in _sys.path:
        _sys.path.insert(0, engine)
    from tools import studio_asset_library as studio  # noqa: PLC0415
    return studio


def resolve(path: Any, sha: Any, *, cache_dir: Any = None) -> Path | None:
    """Local path whose bytes are exactly ``sha`` (old path first, then the studio library), else None."""
    if not sha:
        return None
    studio = _studio()
    try:
        return studio.resolve_reference(path, str(sha), cache_dir=cache_dir)
    except studio.StudioError as exc:
        if exc.code == "RESTORE_PENDING":
            raise SystemExit(f"STUDIO_ASSET_RESTORE_PENDING:{str(sha)[:12]}: the library knows these bytes but its "
                             "master is missing or damaged; run `studio_asset_library.py backup restore --sha256 "
                             "<sha>` (no regeneration was started)") from None
        return None


def present(artifact: dict[str, Any]) -> bool:
    """True when the artifact's recorded bytes can be had locally (old path, or the studio original)."""
    return resolve(artifact.get("path"), artifact.get("sha256")) is not None
