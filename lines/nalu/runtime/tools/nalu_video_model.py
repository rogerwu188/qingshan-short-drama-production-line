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

Episode attribution (K145 binding).  A lock, an editorial manifest or a task row that DECLARES an
``episode`` other than the one being resolved raises ``VIDEO_MODEL_*_EPISODE_MISMATCH`` before any model is
returned; the record is left exactly as it is (never deleted, overwritten or replaced by the config).
A record WITHOUT an ``episode`` field (key absent or ``null``) is a different case: legacy records predate
the field and are accepted only for the episode whose own path holds them
(``preproduction/<EP>/video_model.json``, ``<EP>/preproduction/<EP>_EDITORIAL_SEEDANCE_MANIFEST_V1.json``);
the selection reports ``episode_attribution`` = ``path_legacy`` for them, ``declared`` otherwise, so the
two cases are never conflated.  Any other declared value (another id, empty string, non-string) declares
a different episode and is refused.

H3 resolution (line owner 2026-11-12: MiniMax-H3 drops from 768p to 480p from each device's NEXT episode).
The resolution is fixed per episode exactly like the model and never changes once recorded:

1. a ``resolution`` field in the episode lock (written by :func:`claim_video_model` at the first S2 build);
2. else the resolution its existing editorial manifest was compiled at (``model_contract.resolution`` /
   shot rows), else the resolution any H3 video transaction of the episode was requested at;
3. an episode that is already started -- it has a lock or an editorial manifest, or a bound H3 transaction --
   but records no resolution anywhere predates this rule and stays ``768p``;
4. else (a new episode) qingshan.json ``generation.h3_resolution``; when the key is absent the engine default
   ``480p`` applies.  A present but empty / non-string / unsupported value fails closed.

A lock, manifest or transaction naming an unsupported resolution, or two records naming different ones,
raises :class:`VideoModelSelectionError` (``VIDEO_RESOLUTION_*``); nothing is rewritten.  seedance-2.0-pro
is always 720p.
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
SD2_RESOLUTION = "720p"
H3_RESOLUTIONS = ("480p", "768p")
#: Engine default for NEW H3 episodes when qingshan.json has no generation.h3_resolution (owner 2026-11-12).
DEFAULT_H3_RESOLUTION = "480p"
#: What an episode started before the resolution was recorded was generated at.
LEGACY_H3_RESOLUTION = "768p"
MODEL_RESOLUTIONS = {SD2: (SD2_RESOLUTION,), H3: H3_RESOLUTIONS}
#: H3 native rasters.  768p was delivered as 768x1344 (E02, 2026-10-14; older builders assumed 768x1366).
#: No source states the exact 480p raster (registry, HopsAPI docs and the hopsapi-minimax-h3 skill only name
#: "480p"), so it is checked as a 9:16-ish portrait frame whose short edge is 480 (post_generation_qa_runner).
H3_NATIVE_RASTERS = {"768p": "768x1344", "480p": None}
H3_NATIVE_SHORT_EDGE = {"480p": 480, "768p": 768}


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


def transactions_dir(episode: str) -> Path:
    """The durable video submit store of the episode (tools/submit_giggle_video_manifest_v2.py)."""
    return Path(_np.ENGINE_ROOT) / "workflow" / "tasks" / "giggle_video_submit_transactions" / episode


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


def _attribution(record: dict[str, Any], *, code: str, episode: str, source: str, path: Path) -> str:
    """``declared`` when the record names this episode, ``path_legacy`` when it names none; raise otherwise."""
    if record.get("episode") is None:
        return "path_legacy"
    if record.get("episode") != episode:
        raise VideoModelSelectionError(code, episode=episode, expected=episode, actual=record.get("episode"),
                                       source=source, files=[path],
                                       detail="the record declares another episode; it is not this episode's "
                                              "authority and is left untouched")
    return "declared"


def recorded_selection(episode: str) -> dict[str, Any] | None:
    """{video_model, source, files, episode_attribution} from the episode lock and/or editorial manifest;
    None for a new episode."""
    found: list[tuple[str, str, Path]] = []
    attribution: dict[str, str] = {}
    lock = record_path(episode)
    data = _load(lock, code="VIDEO_MODEL_LOCK_UNREADABLE", episode=episode, source="episode_lock")
    if data is not None:
        attribution["episode_lock"] = _attribution(data, code="VIDEO_MODEL_LOCK_EPISODE_MISMATCH", episode=episode,
                                                   source="episode_lock", path=lock)
        found.append((_supported(data.get("video_model"), code="VIDEO_MODEL_LOCK_INVALID", episode=episode,
                                 source="episode_lock", path=lock), "episode_lock", lock))
    editorial = editorial_path(episode)
    manifest = _load(editorial, code="VIDEO_MODEL_MANIFEST_UNREADABLE", episode=episode, source="editorial_manifest")
    if manifest is not None:
        attribution["editorial_manifest"] = _attribution(manifest, code="VIDEO_MODEL_MANIFEST_EPISODE_MISMATCH",
                                                         episode=episode, source="editorial_manifest",
                                                         path=editorial)
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
    return {"video_model": found[0][0], "source": found[0][1], "files": [str(p) for _, _, p in found],
            "episode_attribution": attribution}


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
    # the resolution an already-started episode was generated at, else the configured one for a new episode;
    # resolved BEFORE the lock is written so an invalid config leaves no lock behind
    resolution = (SD2_RESOLUTION if model == SD2
                  else recorded_h3_resolution(episode) or configured_h3_resolution())
    lock = record_path(episode)
    lock.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    fd, tmp = tempfile.mkstemp(prefix=".video_model.", suffix=".tmp", dir=lock.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"episode": episode, "video_model": model, "resolution": resolution,
                                     "chosen_at": stamp}, ensure_ascii=False, indent=2) + "\n")
        try:
            os.link(tmp, lock)
        except FileExistsError:
            pass
    finally:
        os.unlink(tmp)
    selection = recorded_selection(episode)
    if selection is None:  # pragma: no cover - the lock was just linked
        raise VideoModelSelectionError("VIDEO_MODEL_LOCK_NOT_WRITTEN", episode=episode, files=[lock])
    episode_video_resolution(episode)  # the winner's lock must agree with every other record (raises otherwise)
    return selection["video_model"]


def check_task_models(episode: str, *, tasks: list[dict[str, Any]], format_contract: dict[str, Any] | None = None,
                      allowed_video_models: list[Any] | None = None, manifest_path: Any = None) -> str:
    """Every model a video manifest names must equal the episode's recorded model.  Returns that model.

    A task row that declares another episode is refused first (VIDEO_MODEL_TASK_EPISODE_MISMATCH): it is
    neither judged against this episode's record nor re-attributed.  A row without ``episode`` belongs to
    the episode the caller resolved."""
    files = [manifest_path] if manifest_path else []
    foreign = [f"task:{task.get('task_key')}.episode={task.get('episode')}" for task in tasks
               if task.get("episode") is not None and task.get("episode") != episode]
    if foreign:
        raise VideoModelSelectionError("VIDEO_MODEL_TASK_EPISODE_MISMATCH", episode=episode, expected=episode,
                                       actual=foreign, source="video manifest tasks", files=files)
    selection = recorded_selection(episode)
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


# --------------------------------------------------------------------------- #
# Per-episode resolution (owner 2026-11-12: H3 480p from each device's NEXT episode)
# --------------------------------------------------------------------------- #
def _resolution(value: Any, *, model: str, code: str, episode: str | None, source: str, path: Path) -> str:
    allowed = MODEL_RESOLUTIONS.get(model, ())
    if not isinstance(value, str) or value.strip().lower() not in allowed:
        raise VideoModelSelectionError(code, episode=episode, expected=list(allowed), actual=value,
                                       source=source, files=[path])
    return value.strip().lower()


def configured_h3_resolution() -> str:
    """qingshan.json ``generation.h3_resolution`` for a NEW H3 episode; absent -> engine default 480p.

    The key is optional (the engine default does the fleet rollout), but a value that is present must be
    a supported H3 resolution: empty, null, non-string or unknown values fail closed."""
    path = config_path()
    cfg = _load(path, code="VIDEO_RESOLUTION_CONFIG_UNREADABLE", episode=None, source="qingshan.json")
    if cfg is None:
        raise VideoModelSelectionError("VIDEO_RESOLUTION_CONFIG_MISSING", expected=list(H3_RESOLUTIONS),
                                       source="qingshan.json", files=[path],
                                       detail="a new episode needs the runtime qingshan.json")
    generation = cfg.get("generation")
    if generation is None:
        return DEFAULT_H3_RESOLUTION
    if not isinstance(generation, dict):
        raise VideoModelSelectionError("VIDEO_RESOLUTION_CONFIG_INVALID", expected="object", actual=generation,
                                       source="qingshan.json generation", files=[path])
    if "h3_resolution" not in generation:
        return DEFAULT_H3_RESOLUTION
    return _resolution(generation["h3_resolution"], model=H3, code="VIDEO_RESOLUTION_CONFIG_INVALID",
                       episode=None, source="qingshan.json generation.h3_resolution", path=path)


def _manifest_resolutions(manifest: dict[str, Any]) -> list[Any]:
    named = [(manifest.get("model_contract") or {}).get("resolution")]
    named += [row.get("resolution") for row in manifest.get("shots") or [] if isinstance(row, dict)]
    return [value for value in named if value is not None]


def _transaction_resolutions(episode: str) -> list[tuple[str, Path]]:
    """(resolution, path) of every H3 transaction of the episode that formed or bound a request.

    New transactions record ``resolution`` (and HopsAPI ones ``provider_request_input.resolution``); a BOUND
    H3 row without either was written before resolutions were recorded and was therefore 768p.  Unreadable
    rows are skipped here as video_live_binding skips them (the submitter's own guards own them)."""
    directory = transactions_dir(episode)
    if not directory.is_dir():
        return []
    found: list[tuple[str, Path]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(row, dict) or row.get("model") != H3:
            continue
        request = row.get("provider_request_input")
        value = row.get("resolution")
        if value is None and isinstance(request, dict):
            value = request.get("resolution")
        if value is None:
            if row.get("state") != "SUBMITTED_TASK_ID_BOUND" or not row.get("task_id"):
                continue
            value = LEGACY_H3_RESOLUTION
        found.append((_resolution(value, model=H3, code="VIDEO_RESOLUTION_TRANSACTION_INVALID", episode=episode,
                                  source="video_transaction", path=path), path))
    return found


def recorded_h3_resolution(episode: str) -> str | None:
    """The H3 resolution an already-started episode is fixed at; None for a new episode (see module doc)."""
    found: list[tuple[str, str, Path]] = []
    lock = record_path(episode)
    data = _load(lock, code="VIDEO_MODEL_LOCK_UNREADABLE", episode=episode, source="episode_lock")
    if data is not None and data.get("resolution") is not None:
        found.append((_resolution(data["resolution"], model=str(data.get("video_model")),
                                  code="VIDEO_RESOLUTION_LOCK_INVALID", episode=episode, source="episode_lock",
                                  path=lock), "episode_lock", lock))
    editorial = editorial_path(episode)
    manifest = _load(editorial, code="VIDEO_MODEL_MANIFEST_UNREADABLE", episode=episode, source="editorial_manifest")
    if manifest is not None:
        named = _manifest_resolutions(manifest)
        if len(set(map(str, named))) > 1:
            raise VideoModelSelectionError("VIDEO_RESOLUTION_MANIFEST_SELF_CONFLICT", episode=episode,
                                           expected=named[0], actual=sorted(set(map(str, named))),
                                           source="editorial_manifest", files=[editorial])
        if named:
            model = (manifest.get("model_contract") or {}).get("model") or manifest.get("model") or H3
            found.append((_resolution(named[0], model=str(model), code="VIDEO_RESOLUTION_MANIFEST_INVALID",
                                      episode=episode, source="editorial_manifest", path=editorial),
                          "editorial_manifest", editorial))
    transactions = _transaction_resolutions(episode)
    found += [(value, "video_transaction", path) for value, path in transactions]
    values = sorted({value for value, _, _ in found})
    if len(values) > 1:
        raise VideoModelSelectionError("VIDEO_RESOLUTION_RECORDS_CONFLICT", episode=episode, expected=values[0],
                                       actual=values, source="+".join(sorted({s for _, s, _ in found})),
                                       files=sorted({str(p) for _, _, p in found}),
                                       detail="an episode's resolution is fixed; records disagree")
    if values:
        return values[0]
    if data is not None or manifest is not None:
        return LEGACY_H3_RESOLUTION  # started before the resolution was recorded: keeps 768p
    return None


def episode_video_resolution(episode: str) -> str:
    """The provider resolution every video task of ``episode`` is generated at (fixed once recorded)."""
    model = episode_video_model(episode)
    if model != H3:
        return SD2_RESOLUTION
    return recorded_h3_resolution(episode) or configured_h3_resolution()


def check_task_resolutions(episode: str, *, tasks: list[dict[str, Any]], manifest_path: Any = None) -> str:
    """Every H3 task of a video manifest must carry the episode's resolution (no mixing inside an episode)."""
    expected = episode_video_resolution(episode)
    wrong = [f"task:{task.get('task_key')}.resolution={task.get('resolution')}" for task in tasks
             if task.get("model") == H3 and str(task.get("resolution") or "").lower() != expected]
    if wrong:
        raise VideoModelSelectionError("VIDEO_RESOLUTION_MISMATCH", episode=episode, expected=expected, actual=wrong,
                                       source="episode resolution",
                                       files=[record_path(episode), *([manifest_path] if manifest_path else [])])
    return expected
