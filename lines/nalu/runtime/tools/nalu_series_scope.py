#!/usr/bin/env python3
"""nalu_series_scope — per-episode asset-library / registry scope for the nalu pipeline.

Roger 2026-09-18: an episode that belongs to another production (the Codex line's E59 v4 four
layers) must run on its OWN asset library and registries and must never read the
NALU-YEWUJIANG E01–E05 assets.  ``<RUNTIME_ROOT>/runtime/series_scopes.json`` binds episodes to
named scopes; every registry path the pipeline used to take from module constants is resolved
here instead.  Without the config file (or for an unbound episode) the default scope resolves
to exactly the historical paths, so E01–E05 behave as before.

Resolved keys (all absolute ``Path``): asset_library, asset_library_seed, voice_registry,
voice_catalog, voice_cast, entity_registry, agentcut_voice_policy, character_registry,
character_sources, voice_refs, lexicon, charter (may be None), series_root.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import nalu_paths as _np

SCHEMA = "nalu.series_scopes.v1"
DEFAULT_SCOPE_ID = "NALU-YEWUJIANG"
CONFIG_NAME = "series_scopes.json"

_RUNTIME = Path(f"{_np.RUNTIME_ROOT}")
_RT = _RUNTIME / "runtime"
_TOOLS = Path(f"{_np.TOOLS_DIR}")

DEFAULT_PATHS: dict[str, str | None] = {
    "series_root": "runtime",
    "asset_library": "runtime/asset_library.json",
    "asset_library_seed": "runtime/E01_ASSET_LIBRARY_V1.json",
    "voice_registry": "runtime/voice_registry.json",
    "voice_catalog": "runtime/voice_catalog.json",
    "voice_cast": "runtime/voice_cast.json",
    "entity_registry": "runtime/nalu_entity_registry.json",
    "agentcut_voice_policy": "runtime/agentcut_character_voice_reference_policy_nalu.json",
    "character_registry": "runtime/nalu_character_asset_registry.json",
    "character_sources": "runtime/character_sources",
    "voice_refs": "runtime/voice_refs",
    "lexicon": "tools:configs/LEXICON_yewujiang_v1.json",
    "charter": None,
}


def config_path() -> Path:
    return Path(os.environ.get("NALU_SERIES_SCOPES") or (_RT / CONFIG_NAME))


def _abs(value: str | None) -> Path | None:
    if value is None:
        return None
    if value.startswith("tools:"):
        return (_TOOLS.parent / value[len("tools:"):]).resolve()
    path = Path(value).expanduser()
    return path if path.is_absolute() else (_RUNTIME / path).resolve()


def load_config() -> dict[str, Any]:
    path = config_path()
    if not path.is_file():
        return {"schema": SCHEMA, "default_scope": DEFAULT_SCOPE_ID, "scopes": {}, "episodes": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise SystemExit(f"SERIES_SCOPES_SCHEMA_INVALID:{path}")
    return data


def scope_id_for(episode: str, config: dict[str, Any] | None = None) -> str:
    config = config if config is not None else load_config()
    return str((config.get("episodes") or {}).get(episode) or config.get("default_scope") or DEFAULT_SCOPE_ID)


def resolve_scope(episode: str) -> dict[str, Any]:
    config = load_config()
    sid = scope_id_for(episode, config)
    declared = (config.get("scopes") or {}).get(sid) or {}
    if sid != DEFAULT_SCOPE_ID and not declared:
        raise SystemExit(f"SERIES_SCOPE_UNDECLARED:{sid}:{episode}")
    merged = dict(DEFAULT_PATHS)
    if sid != DEFAULT_SCOPE_ID:
        # a foreign scope must declare every path explicitly — inheriting a default-scope
        # registry silently would be exactly the cross-line asset leak this module prevents.
        missing = [k for k in DEFAULT_PATHS if k not in declared and k != "charter"]
        if missing:
            raise SystemExit(f"SERIES_SCOPE_PATHS_MISSING:{sid}:{','.join(missing)}")
    for key, value in declared.items():
        if key in DEFAULT_PATHS:
            merged[key] = value
    out: dict[str, Any] = {key: _abs(value) for key, value in merged.items()}
    out["scope_id"] = sid
    out["series_id"] = str(declared.get("series_id") or sid)
    out["is_default"] = sid == DEFAULT_SCOPE_ID
    out["config_path"] = str(config_path()) if config_path().is_file() else None
    out["isolation"] = declared.get("isolation") or (
        "default nalu scope" if sid == DEFAULT_SCOPE_ID else "declared scope; default-scope registries are never read")
    return out


def describe(episode: str) -> dict[str, Any]:
    scope = resolve_scope(episode)
    return {k: (str(v) if isinstance(v, Path) else v) for k, v in scope.items()}


if __name__ == "__main__":
    import sys
    print(json.dumps(describe(sys.argv[1] if len(sys.argv) > 1 else "E01"), ensure_ascii=False, indent=2))
