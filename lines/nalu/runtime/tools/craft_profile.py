#!/usr/bin/env python3
"""One per-series craft profile: ``LEGACY`` (the historical line, the default) or ``BILI_V1``.

Owner 2026-11-23 (Bilibili benchmark, ep2 + ep3; ``~/nalu_lab/bili_work/CHANGE_SPEC.md`` WP0): every behaviour
change of the script / craft redesign (WP1-WP7) sits behind this one switch, so a PR can merge without changing any
running series and the owner turns it on per series.  Docs: ``docs/knowledge/CRAFT_PROFILE.md``.

Keys (each resolved on its own, first hit wins):

* ``craft_profile``: ``LEGACY`` | ``BILI_V1``; an unknown value is ignored (falls through, ends at ``LEGACY``);
* ``bgm_mood_cues``: bool, WP5-C per-episode mood cues (default False);
* ``writer_format``: ``CONTRACT_JSON`` | ``SCREENPLAY_V1``, WP2 (default ``CONTRACT_JSON``).

The two sub-switches only take effect under ``BILI_V1``: under ``LEGACY`` ``enabled("bgm_mood_cues")`` is False and
``writer_format`` is ``CONTRACT_JSON`` whatever is declared, so a LEGACY series is byte-identical to before.

Where a series declares them (mirrors ``render_style.py``):

1. the generation contract: top-level ``craft_profile`` / ``bgm_mood_cues`` / ``writer_format`` (also on a
   compiled unit), or the same keys inside a ``craft`` block;
2. the episode's production brief (``<runtime>/briefs/<EP>_PRODUCTION_BRIEF.json``), same keys;
3. the runtime ``qingshan.json`` ``project.craft_profile`` / ``project.bgm_mood_cues`` / ``project.writer_format``;
4. the defaults above.

Import (works under both the runtime-tools and the engine-tools roots)::

    try:
        from tools import craft_profile as _cp
    except ModuleNotFoundError:  # pragma: no cover - runtime tools dir only
        import craft_profile as _cp

Pure data and functions; the runtime lookups read two small JSON files and never raise.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LEGACY = "LEGACY"
BILI_V1 = "BILI_V1"
PROFILES = (LEGACY, BILI_V1)
DEFAULT_PROFILE = LEGACY
FIELD = "craft_profile"
BLOCK = "craft"

BGM_MOOD_CUES = "bgm_mood_cues"
WRITER_FORMAT = "writer_format"
CONTRACT_JSON = "CONTRACT_JSON"
SCREENPLAY_V1 = "SCREENPLAY_V1"
WRITER_FORMATS = (CONTRACT_JSON, SCREENPLAY_V1)
DEFAULTS: dict[str, Any] = {FIELD: LEGACY, BGM_MOOD_CUES: False, WRITER_FORMAT: CONTRACT_JSON}
KEYS = tuple(DEFAULTS)

_PROFILE_ALIASES = {
    "legacy": LEGACY, "default": LEGACY, "classic": LEGACY,
    "bili_v1": BILI_V1, "biliv1": BILI_V1, "bili": BILI_V1,
}
_FORMAT_ALIASES = {
    "contract_json": CONTRACT_JSON, "contract": CONTRACT_JSON, "json": CONTRACT_JSON,
    "screenplay_v1": SCREENPLAY_V1, "screenplay": SCREENPLAY_V1,
}
_TRUE = {"1", "true", "yes", "on", "y"}
_FALSE = {"0", "false", "no", "off", "n"}


# --------------------------------------------------------------------------- normalisation
def _token(value: Any) -> str:
    return str(value if value is not None else "").strip().lower().replace("-", "_").replace(" ", "_")


def normalise(value: Any) -> str | None:
    """"BILI_V1" / "bili-v1" / "legacy" ... -> one of PROFILES; anything else -> None."""
    return _PROFILE_ALIASES.get(_token(value))


def normalise_writer_format(value: Any) -> str | None:
    return _FORMAT_ALIASES.get(_token(value))


def _bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    text = _token(value)
    return True if text in _TRUE else False if text in _FALSE else None


_NORMALISERS = {FIELD: normalise, BGM_MOOD_CUES: _bool, WRITER_FORMAT: normalise_writer_format}


def _pick(source: Any, key: str) -> Any:
    """The normalised value of ``key`` a dict (or its ``craft`` block) declares; None = silent."""
    if not isinstance(source, dict):
        return None
    block = source.get(BLOCK)
    for where in (source, block if isinstance(block, dict) else None):
        if isinstance(where, dict) and key in where:
            value = _NORMALISERS[key](where.get(key))
            if value is not None:
                return value
    return None


def _project(config: Any) -> Any:
    return config.get("project") if isinstance(config, dict) else None


# --------------------------------------------------------------------------- resolution
def from_contract(contract: Any, key: str = FIELD) -> Any:
    """The value a generation contract or a compiled unit declares (None = silent)."""
    return _pick(contract, key)


def from_brief(brief: Any, key: str = FIELD) -> Any:
    return _pick(brief, key)


def from_config(config: Any, key: str = FIELD) -> Any:
    return _pick(_project(config), key)


def _resolve_key(key: str, contract: Any, brief: Any, config: Any) -> Any:
    for value in (from_contract(contract, key), from_brief(brief, key), from_config(config, key)):
        if value is not None:
            return value
    return DEFAULTS[key]


def resolve(contract: Any = None, brief: Any = None, config: Any = None) -> str:
    """contract -> brief -> runtime config -> LEGACY."""
    return _resolve_key(FIELD, contract, brief, config)


def settings(contract: Any = None, brief: Any = None, config: Any = None) -> dict[str, Any]:
    """All keys resolved; the sub-switches forced to their defaults unless the profile is BILI_V1."""
    profile = resolve(contract, brief, config)
    if profile != BILI_V1:
        return dict(DEFAULTS)
    return {FIELD: profile, **{k: _resolve_key(k, contract, brief, config) for k in KEYS if k != FIELD}}


def _read(path: Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def default_runtime_root() -> Path | None:
    try:
        import nalu_paths as _np  # noqa: PLC0415 - runtime tools dir
    except ImportError:  # pragma: no cover - imported from engine tools/ without the runtime dir
        try:
            import importlib.util as _util  # noqa: PLC0415
            spec = _util.spec_from_file_location("nalu_paths", Path(__file__).resolve().parent / "nalu_paths.py")
            _np = _util.module_from_spec(spec)
            spec.loader.exec_module(_np)  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            return None
    return Path(f"{_np.RUNTIME_ROOT}")


def brief_path(runtime_root: Path | str, episode: str) -> Path:
    return Path(runtime_root) / "briefs" / f"{episode}_PRODUCTION_BRIEF.json"


def runtime_sources(episode: str | None = None,
                    runtime_root: Path | str | None = None) -> tuple[Any, Any]:
    """(brief, qingshan.json) read from the runtime root (env / pin / beside tools); (None, None) if absent."""
    root = Path(runtime_root) if runtime_root else default_runtime_root()
    if root is None:
        return None, None
    brief = _read(brief_path(root, episode)) if episode else None
    return brief, _read(root / "qingshan.json")


def settings_runtime(episode: str | None = None, *, contract: Any = None,
                     runtime_root: Path | str | None = None) -> dict[str, Any]:
    """``settings`` with the brief and ``qingshan.json`` read from the runtime root."""
    brief, config = runtime_sources(episode, runtime_root)
    return settings(contract, brief, config)


def resolve_runtime(episode: str | None = None, *, contract: Any = None,
                    runtime_root: Path | str | None = None) -> str:
    """``resolve`` with the brief and ``qingshan.json`` read from the runtime root."""
    profile = from_contract(contract)
    if profile:
        return profile
    brief, config = runtime_sources(episode, runtime_root)
    return resolve(None, brief, config)


# --------------------------------------------------------------------------- helpers other WPs call
def _settings_of(value: Any, episode: str | None, runtime_root: Path | str | None,
                 brief: Any, config: Any) -> dict[str, Any]:
    """Settings for whatever a call site holds:

    * a pipeline ``Ctx`` (anything with a ``craft_settings`` / ``craft_profile`` attribute) -> its resolved values;
    * a ``Path`` -> a runtime root (brief of ``episode`` + ``qingshan.json``);
    * a dict -> a generation contract / unit; also the runtime when ``episode`` or ``runtime_root`` is given;
    * a str -> a profile value ("BILI_V1");
    * None -> the runtime (``episode`` / ``runtime_root``) when given, else the explicit ``brief`` / ``config``.
    """
    ctx_settings = getattr(value, "craft_settings", None)
    if isinstance(ctx_settings, dict):
        return ctx_settings
    if hasattr(value, "craft_profile") and not isinstance(value, (dict, str, Path)):
        return settings({FIELD: getattr(value, "craft_profile", None)})
    if isinstance(value, Path):
        return settings_runtime(episode, runtime_root=value)
    if isinstance(value, str):
        return settings({FIELD: value})
    contract = value if isinstance(value, dict) else None
    if episode is not None or runtime_root is not None:
        rt_brief, rt_config = runtime_sources(episode, runtime_root)
        return settings(contract, brief if brief is not None else rt_brief,
                        config if config is not None else rt_config)
    return settings(contract, brief, config)


def profile_of(value: Any = None, *, episode: str | None = None, runtime_root: Path | str | None = None,
               brief: Any = None, config: Any = None) -> str:
    """The resolved profile of a Ctx / contract / runtime root / profile string (see ``_settings_of``)."""
    return _settings_of(value, episode, runtime_root, brief, config)[FIELD]


def is_bili_v1(value: Any = None, *, episode: str | None = None, runtime_root: Path | str | None = None,
               brief: Any = None, config: Any = None) -> bool:
    """True when the series runs the BILI_V1 craft profile."""
    return profile_of(value, episode=episode, runtime_root=runtime_root, brief=brief, config=config) == BILI_V1


def is_legacy(value: Any = None, **kwargs: Any) -> bool:
    return not is_bili_v1(value, **kwargs)


def writer_format(value: Any = None, *, episode: str | None = None, runtime_root: Path | str | None = None,
                  brief: Any = None, config: Any = None) -> str:
    """``CONTRACT_JSON`` | ``SCREENPLAY_V1`` (always ``CONTRACT_JSON`` under LEGACY)."""
    return _settings_of(value, episode, runtime_root, brief, config)[WRITER_FORMAT]


def bgm_mood_cues(value: Any = None, *, episode: str | None = None, runtime_root: Path | str | None = None,
                  brief: Any = None, config: Any = None) -> bool:
    """WP5-C mood cues on (always False under LEGACY)."""
    return bool(_settings_of(value, episode, runtime_root, brief, config)[BGM_MOOD_CUES])


def enabled(name: str, value: Any = None, *, episode: str | None = None, runtime_root: Path | str | None = None,
            brief: Any = None, config: Any = None) -> bool:
    """One question for every switch: ``enabled("BILI_V1", ...)``, ``enabled("bgm_mood_cues", ...)``,
    ``enabled("SCREENPLAY_V1", ...)``.  An unknown name is False."""
    current = _settings_of(value, episode, runtime_root, brief, config)
    if normalise(name):
        return current[FIELD] == normalise(name)
    if normalise_writer_format(name):
        return current[WRITER_FORMAT] == normalise_writer_format(name)
    if _token(name) == BGM_MOOD_CUES:
        return bool(current[BGM_MOOD_CUES])
    return False


__all__ = [
    "LEGACY", "BILI_V1", "PROFILES", "DEFAULT_PROFILE", "FIELD", "BLOCK", "BGM_MOOD_CUES", "WRITER_FORMAT",
    "CONTRACT_JSON", "SCREENPLAY_V1", "WRITER_FORMATS", "DEFAULTS", "KEYS", "normalise", "normalise_writer_format",
    "from_contract", "from_brief", "from_config", "resolve", "settings", "default_runtime_root", "brief_path",
    "runtime_sources", "settings_runtime", "resolve_runtime", "profile_of", "is_bili_v1", "is_legacy",
    "writer_format", "bgm_mood_cues", "enabled",
]
