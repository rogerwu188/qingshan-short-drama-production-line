"""Which video model an episode uses (line owner 2026-10-13: new episodes generate video with MiniMax-H3).

An episode's model is fixed by its first S2 build and never changes afterwards:

1. ``<runtime>/preproduction/<EP>/video_model.json`` (written by build_nalu_preproduction.select_video_model);
2. else the model its existing editorial manifest was built with (an episode already in production when
   this file was introduced keeps seedance-2.0-pro);
3. else ``None`` — a new episode; the caller uses qingshan.json ``generation.video_model``.

Fail closed (K145).  "No record" and "a record that cannot be trusted" are different answers: a lock or
manifest that exists but is unreadable, names no / an unsupported model, or disagrees with the other one
raises :class:`VideoModelSelectionError`; it is never treated as absent.  A new episode's model must be
named explicitly in qingshan.json — a missing / unreadable config, a missing, empty, non-string or unknown
``generation.video_model`` raises too.  There is no default model: a silent default used to be written
into the episode lock by the first S2 and then followed by every paid stage.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nalu_paths as _np

SD2 = "seedance-2.0-pro"
H3 = "MiniMax-H3"
SUPPORTED = (SD2, H3)


class VideoModelSelectionError(RuntimeError):
    """The episode's video model cannot be determined safely; model-dependent work must stop."""

    def __init__(self, code: str, *, episode: str | None = None, expected: Any = None, actual: Any = None,
                 source: str | None = None, files: list[str] | tuple[str, ...] = (), detail: str = "") -> None:
        self.code = code
        self.details = {"code": code, "episode": episode, "expected": expected, "actual": actual,
                        "source": source, "files": [str(f) for f in files], "detail": detail}
        super().__init__(f"{code}: " + json.dumps(self.details, ensure_ascii=False))


def record_path(episode: str) -> Path:
    return Path(f"{_np.RUNTIME_ROOT}") / "preproduction" / episode / "video_model.json"


def editorial_path(episode: str) -> Path:
    return Path(_np.WORK_ROOT).expanduser() / episode / "preproduction" / f"{episode}_EDITORIAL_SEEDANCE_MANIFEST_V1.json"


def config_path() -> Path:
    return Path(f"{_np.RUNTIME_ROOT}") / "qingshan.json"


def _load(path: Path, *, code: str, episode: str | None, source: str) -> dict[str, Any] | None:
    """None only when the file does not exist; anything present but unusable raises."""
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VideoModelSelectionError(code, episode=episode, source=source, files=[path],
                                       detail=f"{type(exc).__name__}: {exc}") from exc
    if not isinstance(value, dict):
        raise VideoModelSelectionError(code, episode=episode, source=source, files=[path],
                                       detail=f"top level is {type(value).__name__}, not an object")
    return value


def _supported(model: Any, *, code: str, episode: str | None, source: str, path: Path) -> str:
    if not isinstance(model, str) or model not in SUPPORTED:
        raise VideoModelSelectionError(code, episode=episode, expected=list(SUPPORTED), actual=model,
                                       source=source, files=[path])
    return model


def recorded_selection(episode: str) -> dict[str, Any] | None:
    """{video_model, source, files} from the episode lock and/or editorial manifest; None for a new episode."""
    found: list[tuple[str, str, Path]] = []
    lock = record_path(episode)
    data = _load(lock, code="VIDEO_MODEL_LOCK_UNREADABLE", episode=episode, source="episode_lock")
    if data is not None:
        found.append((_supported(data.get("video_model"), code="VIDEO_MODEL_LOCK_INVALID", episode=episode,
                                 source="episode_lock", path=lock), "episode_lock", lock))
    editorial = editorial_path(episode)
    manifest = _load(editorial, code="VIDEO_MODEL_MANIFEST_UNREADABLE", episode=episode, source="editorial_manifest")
    if manifest is not None:
        named = [value for value in ((manifest.get("model_contract") or {}).get("model"), manifest.get("model"))
                 if value is not None]
        if len(set(map(str, named))) > 1:
            raise VideoModelSelectionError("VIDEO_MODEL_MANIFEST_SELF_CONFLICT", episode=episode, expected=named[0],
                                           actual=named[1], source="editorial_manifest", files=[editorial])
        found.append((_supported(named[0] if named else None, code="VIDEO_MODEL_MANIFEST_INVALID",
                                 episode=episode, source="editorial_manifest", path=editorial),
                      "editorial_manifest", editorial))
    if not found:
        return None
    if len({model for model, _, _ in found}) > 1:
        raise VideoModelSelectionError("VIDEO_MODEL_RECORDS_CONFLICT", episode=episode, expected=found[0][0],
                                       actual=found[1][0], source="+".join(s for _, s, _ in found),
                                       files=[p for _, _, p in found])
    return {"video_model": found[0][0], "source": found[0][1], "files": [str(p) for _, _, p in found]}


def recorded_video_model(episode: str) -> str | None:
    selection = recorded_selection(episode)
    return selection["video_model"] if selection else None


def configured_video_model() -> str:
    """qingshan.json ``generation.video_model`` — required, explicit, supported.  No default."""
    path = config_path()
    cfg = _load(path, code="VIDEO_MODEL_CONFIG_UNREADABLE", episode=None, source="qingshan.json")
    if cfg is None:
        raise VideoModelSelectionError("VIDEO_MODEL_CONFIG_MISSING", expected=list(SUPPORTED),
                                       source="qingshan.json", files=[path],
                                       detail="a new episode needs an explicit generation.video_model")
    generation = cfg.get("generation")
    model = generation.get("video_model") if isinstance(generation, dict) else None
    if model is None or model == "":
        raise VideoModelSelectionError("VIDEO_MODEL_NOT_CONFIGURED", expected=list(SUPPORTED), actual=model,
                                       source="qingshan.json generation.video_model", files=[path])
    return _supported(model, code="VIDEO_MODEL_CONFIG_INVALID", episode=None,
                      source="qingshan.json generation.video_model", path=path)


def episode_video_model(episode: str) -> str:
    return recorded_video_model(episode) or configured_video_model()


def claim_video_model(episode: str, model: str) -> str:
    """Write the episode lock exactly once and return the model it holds.

    The lock is written to a temp file and hard-linked into place, which fails if the lock already
    exists: two first builds racing never both write, a reader never sees a half-written lock, and the
    loser adopts the winner's model instead of overwriting it.
    """
    _supported(model, code="VIDEO_MODEL_INVALID", episode=episode, source="claim", path=record_path(episode))
    lock = record_path(episode)
    lock.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    fd, tmp = tempfile.mkstemp(prefix=".video_model.", suffix=".tmp", dir=lock.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"episode": episode, "video_model": model, "chosen_at": stamp},
                                    ensure_ascii=False, indent=2) + "\n")
        try:
            os.link(tmp, lock)
        except FileExistsError:
            pass
    finally:
        os.unlink(tmp)
    selection = recorded_selection(episode)
    if selection is None:  # pragma: no cover - the lock was just linked
        raise VideoModelSelectionError("VIDEO_MODEL_LOCK_NOT_WRITTEN", episode=episode, files=[lock])
    return selection["video_model"]


def check_task_models(episode: str, *, tasks: list[dict[str, Any]], format_contract: dict[str, Any] | None = None,
                      allowed_video_models: list[Any] | None = None, manifest_path: Any = None) -> str:
    """Every model a video manifest names must equal the episode's recorded model.  Returns that model."""
    selection = recorded_selection(episode)
    files = [manifest_path] if manifest_path else []
    if selection is None:
        raise VideoModelSelectionError("VIDEO_MODEL_NOT_SELECTED", episode=episode, source="no episode lock or "
                                       "editorial manifest", files=[record_path(episode), editorial_path(episode),
                                                                    *files])
    expected = selection["video_model"]
    named: list[tuple[str, Any]] = []
    if format_contract and "model" in format_contract:
        named.append(("format_contract.model", (format_contract or {}).get("model")))
    if allowed_video_models is not None:
        named += [("allowed_video_models", value) for value in allowed_video_models or [None]]
    named += [(f"task:{task.get('task_key')}.model", task.get("model")) for task in tasks]
    wrong = [(where, value) for where, value in named if value != expected]
    if wrong:
        raise VideoModelSelectionError("VIDEO_MODEL_MISMATCH", episode=episode, expected=expected,
                                       actual=[f"{where}={value}" for where, value in wrong],
                                       source=selection["source"], files=[*selection["files"], *files])
    return expected
