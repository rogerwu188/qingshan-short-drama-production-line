#!/usr/bin/env python3
"""Resolve ffmpeg-family binaries without assuming one host platform."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def resolve_media_binary(name: str, *extra_env_names: str) -> Path:
    """Return an executable media binary from env, PATH, or AgentCut vendors."""
    normalized = name.strip().lower()
    if normalized not in {"ffmpeg", "ffprobe"}:
        raise ValueError(f"Unsupported media binary: {name}")

    env_names = (*extra_env_names, f"QINGSHAN_{normalized.upper()}", normalized.upper())
    candidates: list[Path] = []
    for env_name in env_names:
        value = os.environ.get(env_name)
        if value:
            candidates.append(Path(value).expanduser())

    discovered = shutil.which(normalized)
    if discovered:
        candidates.append(Path(discovered))

    vendor_root = ROOT / ".agentcut_env"
    candidates.extend(
        sorted(vendor_root.glob(f"lib/python*/site-packages/agentcut/vendor/*/{normalized}"))
    )

    checked: list[str] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        checked.append(str(resolved))
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    raise FileNotFoundError(f"{normalized} executable not found; checked={checked}")
