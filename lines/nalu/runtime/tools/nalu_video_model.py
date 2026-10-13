"""Which video model an episode uses (line owner 2026-10-13: new episodes generate video with MiniMax-H3).

An episode's model is fixed by its first S2 build and never changes afterwards:

1. ``<runtime>/preproduction/<EP>/video_model.json`` (written by build_nalu_preproduction.select_video_model);
2. else the model its existing editorial manifest was built with (an episode already in production when
   this file was introduced keeps seedance-2.0-pro);
3. else ``None`` — a new episode; the caller falls back to qingshan.json ``generation.video_model``.
"""
from __future__ import annotations

import json
from pathlib import Path

import nalu_paths as _np

SD2 = "seedance-2.0-pro"
H3 = "MiniMax-H3"
SUPPORTED = (SD2, H3)


def record_path(episode: str) -> Path:
    return Path(f"{_np.RUNTIME_ROOT}") / "preproduction" / episode / "video_model.json"


def recorded_video_model(episode: str) -> str | None:
    try:
        model = str(json.loads(record_path(episode).read_text(encoding="utf-8")).get("video_model") or "")
        if model:
            return model
    except (OSError, ValueError):
        pass
    editorial = Path(_np.WORK_ROOT).expanduser() / episode / "preproduction" / f"{episode}_EDITORIAL_SEEDANCE_MANIFEST_V1.json"
    try:
        manifest = json.loads(editorial.read_text(encoding="utf-8"))
        model = str((manifest.get("model_contract") or {}).get("model") or manifest.get("model") or "")
        return model or None
    except (OSError, ValueError):
        return None


def configured_video_model() -> str:
    try:
        cfg = json.loads((Path(f"{_np.RUNTIME_ROOT}") / "qingshan.json").read_text(encoding="utf-8"))
        return str((cfg.get("generation") or {}).get("video_model") or SD2)
    except (OSError, ValueError):
        return SD2


def episode_video_model(episode: str) -> str:
    return recorded_video_model(episode) or configured_video_model()
