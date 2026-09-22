#!/usr/bin/env python3
"""Resolve ffmpeg/ffprobe for the NALU runtime without assuming macOS.

An explicit override is authoritative: when it is configured but invalid, the
resolver blocks instead of silently selecting a different executable.  This is
important for QA receipts because the measured binary must be the one selected
by the deployment.  PATH is used next.  The old Homebrew paths are compatibility
fallbacks only when those files actually exist and are executable.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Callable


class MediaToolBlocked(RuntimeError):
    """The requested media executable cannot be resolved safely."""


ENV_NAMES = {
    "ffmpeg": ("QINGSHAN_FFMPEG", "NALU_FFMPEG", "NALU_FFMPEG_BIN"),
    "ffprobe": ("QINGSHAN_FFPROBE", "NALU_FFPROBE", "NALU_FFPROBE_BIN"),
}

LEGACY_PATHS = {
    "ffmpeg": (Path("/opt/homebrew/bin/ffmpeg"),),
    "ffprobe": (Path("/opt/homebrew/bin/ffprobe"),),
}

CJK_FONT_ENV_NAMES = ("QINGSHAN_CJK_FONT", "NALU_CJK_FONT")
CJK_FONT_PATHS = (
    # Debian/Ubuntu fonts-noto-cjk layouts.
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf"),
    Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"),
    # Common Linux fallback with real CJK glyph coverage.
    Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"),
    # Existing macOS production hosts.
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
)


def _executable(path: str | os.PathLike[str]) -> Path | None:
    candidate = Path(path).expanduser()
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate.resolve()
    return None


def _regular_file(path: str | os.PathLike[str]) -> Path | None:
    candidate = Path(path).expanduser()
    return candidate.resolve() if candidate.is_file() else None


def _configured_executable(
    value: str,
    *,
    which: Callable[[str], str | None],
) -> Path | None:
    # A bare command name is useful in container manifests.  A value containing
    # a path separator is a declared path and must exist exactly as configured.
    if os.sep not in value and (os.altsep is None or os.altsep not in value):
        located = which(value)
        return _executable(located) if located else None
    return _executable(value)


def resolve_media_tool(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] | None = None,
    legacy_paths: tuple[Path, ...] | None = None,
) -> tuple[str, str]:
    """Return ``(absolute executable, provenance)`` or raise an explicit BLOCKED.

    Resolution order is deployment override, PATH, then an existing legacy
    Homebrew executable.  The first non-empty override wins; an invalid value is
    a configuration error and is never hidden by PATH.
    """
    if name not in ENV_NAMES:
        raise ValueError(f"unsupported media tool: {name}")
    environment = os.environ if environ is None else environ
    command_lookup = shutil.which if which is None else which

    for env_name in ENV_NAMES[name]:
        raw = str(environment.get(env_name) or "").strip()
        if not raw:
            continue
        candidate = _configured_executable(raw, which=command_lookup)
        if candidate is None:
            raise MediaToolBlocked(
                f"BLOCKED_MEDIA_TOOL:{name}:{env_name}={raw!r} is not an executable file or command"
            )
        return str(candidate), env_name

    located = command_lookup(name)
    candidate = _executable(located) if located else None
    if candidate is not None:
        return str(candidate), "PATH"

    for legacy in LEGACY_PATHS[name] if legacy_paths is None else legacy_paths:
        candidate = _executable(legacy)
        if candidate is not None:
            return str(candidate), "LEGACY_EXISTING_PATH"

    expected = "/".join(ENV_NAMES[name][:3])
    raise MediaToolBlocked(
        f"BLOCKED_MEDIA_TOOL:{name}: executable unavailable; set {expected} or install {name} on PATH"
    )


def require_ffmpeg() -> str:
    return resolve_media_tool("ffmpeg")[0]


def require_ffprobe() -> str:
    return resolve_media_tool("ffprobe")[0]


def resolve_cjk_font(
    *,
    environ: Mapping[str, str] | None = None,
    candidates: tuple[Path, ...] | None = None,
) -> tuple[str, str]:
    """Return a real CJK font file for subtitle rasterisation or block.

    Falling back to Pillow's default bitmap font would render Chinese as empty
    boxes while still producing a video.  Treat that as a capability failure,
    not a successful subtitle burn-in.
    """
    environment = os.environ if environ is None else environ
    for env_name in CJK_FONT_ENV_NAMES:
        raw = str(environment.get(env_name) or "").strip()
        if not raw:
            continue
        font = _regular_file(raw)
        if font is None:
            raise MediaToolBlocked(
                f"BLOCKED_CJK_FONT:{env_name}={raw!r} is not a readable font file"
            )
        return str(font), env_name

    for path in CJK_FONT_PATHS if candidates is None else candidates:
        font = _regular_file(path)
        if font is not None:
            return str(font), "COMMON_EXISTING_PATH"

    raise MediaToolBlocked(
        "BLOCKED_CJK_FONT:no CJK font found; set QINGSHAN_CJK_FONT/NALU_CJK_FONT "
        "or install fonts-noto-cjk"
    )
