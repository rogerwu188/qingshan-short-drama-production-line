#!/usr/bin/env python3
"""Portable runtime discovery shared by cloud-packaged media tools."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


WHISPER_ENV = "QINGSHAN_WHISPER_MODEL"
FFMPEG_ENV = "QINGSHAN_FFMPEG"
FFPROBE_ENV = "QINGSHAN_FFPROBE"


def _existing_file(value: str | os.PathLike[str] | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path.resolve() if path.is_file() else None


def _command_path(name: str) -> Path | None:
    value = shutil.which(name)
    return Path(value).resolve() if value else None


def _agentcut_vendor_binary(name: str, root: Path | None) -> Path | None:
    if root is None:
        return None
    patterns = (
        f".agentcut_env/lib/python*/site-packages/agentcut/vendor/*/{name}",
        f".venv/lib/python*/site-packages/agentcut/vendor/*/{name}",
        f"venv/lib/python*/site-packages/agentcut/vendor/*/{name}",
    )
    for pattern in patterns:
        for candidate in sorted(root.glob(pattern)):
            if candidate.is_file():
                return candidate.resolve()
    return None


def resolve_media_binary(
    name: str,
    *,
    explicit: str | os.PathLike[str] | None = None,
    root: Path | None = None,
) -> tuple[Path, str]:
    """Resolve ffmpeg/ffprobe without assuming an OS, Python, or username."""
    env_name = FFMPEG_ENV if name == "ffmpeg" else FFPROBE_ENV
    candidates = (
        (_existing_file(explicit), "explicit"),
        (_existing_file(os.environ.get(env_name)), env_name),
        (_agentcut_vendor_binary(name, root), "agentcut_vendor"),
        (_command_path(name), "PATH"),
    )
    for candidate, source in candidates:
        if candidate is not None:
            return candidate, source
    raise FileNotFoundError(
        f"{name} not found; set {env_name}, install it on PATH, "
        "or install the packaged AgentCut runtime"
    )


def _whisper_cache_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for value in (
        os.environ.get("HF_HOME"),
        os.environ.get("HUGGINGFACE_HUB_CACHE"),
        str(Path.home() / ".cache/huggingface"),
    ):
        if not value:
            continue
        path = Path(value).expanduser()
        roots.append(path if path.name == "hub" else path / "hub")
    unique: list[Path] = []
    for root in roots:
        resolved = root.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return tuple(unique)


def _cached_whisper_snapshot(model_name: str) -> Path | None:
    normalized = model_name.replace("/", "--")
    directory = f"models--Systran--faster-whisper-{normalized}"
    for cache_root in _whisper_cache_roots():
        snapshots = cache_root / directory / "snapshots"
        if not snapshots.is_dir():
            continue
        candidates = sorted(
            (path for path in snapshots.iterdir() if path.is_dir()),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return candidates[0].resolve()
    return None


def resolve_whisper_model(
    explicit: str | os.PathLike[str] | None = None,
    *,
    default_name: str = "small",
) -> tuple[str, str]:
    """Return a local snapshot when available, otherwise a model identifier."""
    requested = str(explicit or os.environ.get(WHISPER_ENV) or default_name).strip()
    path = Path(requested).expanduser()
    if path.exists():
        return str(path.resolve()), "explicit_or_env_path"
    cached = _cached_whisper_snapshot(requested)
    if cached is not None:
        return str(cached), "huggingface_cache"
    return requested, "model_identifier"


def runtime_probe(root: Path | None = None) -> dict[str, object]:
    result: dict[str, object] = {}
    for binary in ("ffmpeg", "ffprobe"):
        try:
            path, source = resolve_media_binary(binary, root=root)
            result[binary] = {"status": "ready", "path": str(path), "source": source}
        except FileNotFoundError as exc:
            result[binary] = {"status": "blocked", "reason": str(exc)}
    model, source = resolve_whisper_model()
    result["whisper_model"] = {
        "status": "ready_local" if Path(model).exists() else "download_required",
        "value": model,
        "source": source,
    }
    return result
