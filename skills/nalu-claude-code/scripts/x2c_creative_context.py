#!/usr/bin/env python3
"""X2C 广告创意上下文: tell X2C (ROAN ad generation) each recurring character's reference images and locked voice.

Matrix API doc 1.3.1 「广告创意上下文」/「停用角色旧声音」:

  POST {matrix base}/advertising/creative-context   {device_sn, project_id, series_key, characters[...]}
  POST {matrix base}/advertising/voice-registry/retire {device_sn, project_id, series_key, character_id, voice_version}

Same base URL and X-API-Key as the publisher (publish_x2c_matrix.base_url(): PRODUCTION by default).  Called only
AFTER ``publish`` returned the series' ``project_id``: automatically (non-blocking) after every successful
publish / add-episodes, or by hand: ``publish_x2creel.py creative-context [--series K] [--episode EP] [--dry-run]``.

What goes out per character (main characters = contract ``protagonist_ids``; plus every character the asset library
marks SERIES_CORE and every speaker heard in >= 2 published episodes):

* reference_image_urls: <= 8 public HTTPS images in the order headshot, three-quarter bust, turnaround, full body,
  others.  A recorded public URL is used as is; a local identity card is uploaded once through the matrix
  ``distribution/upload-url`` (PUT) and its ``public_url`` cached by sha256 in the state.  Local paths, URLs with
  user:password, a #fragment or a signed/expiring query are never sent.
* voice: provider "giggle" (the anchor is a Giggle public asset), model = the episode's video model (the model that
  speaks it, MiniMax-H3), id = generation_voice_id, anchor_url = voice registry remote_url, version, status "active",
  language, gender, style, F0 band from voice_cast.json, a speaker_voice_contract line, metadata.duration_seconds.

A character without a locked public voice anchor or without any image is skipped with the reason recorded.

State: ``series[<key>].creative_context`` in $NALU_RUNTIME_ROOT/distribution/x2c_matrix.json -- per character the
payload sha256, voice version / identity, last status + http, sent_at.  A character is re-posted only when its
payload hash changes; when its voice (provider / id / anchor) changes the old version is retired first and the new
voice goes out as version + 1.  Every failure (4xx/5xx, UNKNOWN_ROUTE 404 where the route is not live) is recorded
and retried after the next episode; nothing here ever blocks a release.  ``X2C_CREATIVE_CONTEXT=off`` disables it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import publish_x2c_matrix as mx
import publish_x2creel as px

ENDPOINT = "advertising/creative-context"
RETIRE = "advertising/voice-registry/retire"
MAX_IMAGES = 8          # H3 uses the first 8 (the API accepts 16)
MAX_ANCHOR_SECONDS = 12.0
MAX_CHARACTERS = 12
LOCKED = {"LOCKED_PRODUCTION_READY", "AGENTCUT_GENERATED_REGISTERED_PRODUCTION_READY"}
IMAGE_ROLE_ORDER = ("FRONT_NEUTRAL_HEADSHOT", "HEADSHOT", "THREE_QUARTER_BUST", "BUST", "TURNAROUND",
                    "FULL_BODY_STANDING", "FULL_BODY")
LANG = {"zh": "zh-CN", "en": "en-US", "ja": "ja-JP", "ko": "ko-KR"}
SIGNED_QUERY = re.compile(r"(^|&)(x-amz-[^=]*|signature|sig|token|expires|x-goog-[^=]*|se|sp|st|sv)=", re.I)
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def enabled() -> bool:
    return os.environ.get("X2C_CREATIVE_CONTEXT", "").strip().lower() not in ("off", "0", "false", "no", "disabled")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path | None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8")) if path else None
    except (OSError, ValueError):
        return None


def public_https(url: Any) -> bool:
    """A URL X2C / H3 can download without credentials: https, host, no user:password, no #hash, not signed."""
    text = str(url or "").strip()
    if not text.lower().startswith("https://"):
        return False
    try:
        parts = urlsplit(text)
    except ValueError:
        return False
    if not parts.hostname or parts.username or parts.password or "@" in parts.netloc or parts.fragment or "#" in text:
        return False
    return not SIGNED_QUERY.search(parts.query or "")


# ---------------------------------------------------------------- inputs
def runtime_paths(episode: str | None) -> dict[str, Path]:
    """Registry paths of the episode's series scope (runtime/series_scopes.json), else the default scope."""
    root = px.runtime()
    paths = {"voice_registry": "runtime/voice_registry.json", "voice_cast": "runtime/voice_cast.json",
             "character_registry": "runtime/nalu_character_asset_registry.json",
             "asset_library": "runtime/asset_library.json"}
    cfg = read_json(Path(os.environ.get("NALU_SERIES_SCOPES") or root / "runtime" / "series_scopes.json")) or {}
    sid = (cfg.get("episodes") or {}).get(episode or "") or cfg.get("default_scope")
    declared = ((cfg.get("scopes") or {}).get(sid) or {}) if sid else {}
    out: dict[str, Path] = {}
    for key, rel in paths.items():
        value = declared.get(key) if isinstance(declared.get(key), str) else rel
        p = Path(value).expanduser()
        out[key] = p if p.is_absolute() else root / p
    if os.environ.get("QINGSHAN_VOICE_REGISTRY") and "voice_registry" not in declared:
        out["voice_registry"] = Path(os.environ["QINGSHAN_VOICE_REGISTRY"]).expanduser()
    return out


def engine_root() -> Path:
    env = os.environ.get("NALU_ENGINE_ROOT")
    return Path(env).expanduser() if env else Path(__file__).resolve().parents[3]


def contract_for(episode: str) -> dict[str, Any]:
    state = read_json(px.runtime() / "runtime" / "pipeline_state" / f"{episode}.json") or {}
    pinned = ((state.get("layers") or {}).get("paths") or {}).get("generation_contract")
    for path in (pinned, engine_root() / "workflow/claude_writer_agent/scripts" / f"{episode}_GENERATION_CONTRACT_v1.json"):
        data = read_json(Path(path)) if path else None
        if isinstance(data, dict) and data.get("character_entities"):
            return data
    return {}


def video_model(episode: str, row: dict[str, Any]) -> str:
    for value in (row.get("video_model"), row.get("speaking_model"),
                  (read_json(px.runtime() / "preproduction" / episode / "video_model.json") or {}).get("video_model")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "MiniMax-H3"


def _norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9一-鿿]", "", str(value or "").lower().removeprefix("char-"))


def voice_row(cid: str, entity: dict[str, Any], cast: dict[str, Any], registry: dict[str, Any]) -> dict[str, Any] | None:
    """The locked voice-registry row of a canonical CHAR-* id (registries keep compact legacy keys)."""
    keys = {_norm(k) for k in (cid, entity.get("voice_entity_id"), entity.get("canonical_name"),
                               cast.get("reference_entity_id")) if k}
    for row in registry.get("major_roles") or []:
        if not isinstance(row, dict) or row.get("status") not in LOCKED:
            continue
        mine = {_norm(row.get(k)) for k in ("character_id", "entity_id", "character", "name") if row.get(k)}
        if keys & mine:
            return row
    return None


def gender_of(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip().lower()
        if text in ("female", "f", "woman", "女", "女性") or text.startswith("female"):
            return "female"
        if text in ("male", "m", "man", "男", "男性") or text.startswith("male"):
            return "male"
    return None


def image_candidates(cid: str, char_registry: dict[str, Any], library: dict[str, Any]) -> list[dict[str, Any]]:
    """Identity-card images of a character, best views first: [{role, url|path, sha256}]."""
    found: list[dict[str, Any]] = []
    lib = ((library.get("assets") or {}).get("characters") or {}).get(cid) or {}
    for art in lib.get("artifacts") or []:
        if isinstance(art, dict) and str(art.get("media_type") or "image/").startswith("image/"):
            found.append({"role": str(art.get("role") or ""), "path": art.get("path"), "sha256": art.get("sha256"),
                          "url": art.get("remote_url") or art.get("public_url") or art.get("file_url")})
    reg = (char_registry.get("characters") or {}).get(cid) or {}
    for path in reg.get("canonical_reference_paths") or (reg.get("identity_lock") or {}).get("canonical_view_paths") or []:
        role = next((r for r in IMAGE_ROLE_ORDER if r in str(path).upper()), "")
        found.append({"role": role, "path": path, "sha256": (reg.get("canonical_reference_sha256") or {}).get(path)})
    for url in reg.get("reference_image_urls") or reg.get("remote_urls") or []:
        found.append({"role": "", "url": url})

    def rank(row: dict[str, Any]) -> int:
        role = row["role"].upper()
        return next((i for i, r in enumerate(IMAGE_ROLE_ORDER) if r in role), len(IMAGE_ROLE_ORDER))

    out, seen = [], set()
    for row in sorted(found, key=rank):
        key = row.get("sha256") or row.get("url") or row.get("path")
        if key and key not in seen:
            seen.add(key)
            out.append(row)
    return out


def resolve_images(cands: list[dict[str, Any]], uploads: dict[str, str], *, dry_run: bool,
                   notes: list[str]) -> list[str]:
    urls: list[str] = []
    for row in cands:
        if len(urls) >= MAX_IMAGES:
            break
        if row.get("url"):
            if public_https(row["url"]):
                urls.append(str(row["url"]).strip())
            else:
                notes.append("IMAGE_URL_NOT_PUBLIC_HTTPS")
            continue
        path = Path(str(row.get("path") or ""))
        ctype = IMAGE_TYPES.get(path.suffix.lower())
        if not ctype or not path.is_file():
            continue
        digest = row.get("sha256") or px.sha256(path)
        if uploads.get(digest):
            urls.append(uploads[digest])
        elif dry_run:
            urls.append(f"https://UPLOAD-PENDING.invalid/{digest[:16]}{path.suffix.lower()}")
        else:
            url = mx.upload(path, ctype)  # matrix distribution/upload-url + PUT -> public_url
            if not public_https(url):
                notes.append("UPLOADED_IMAGE_URL_NOT_PUBLIC_HTTPS")
                continue
            uploads[digest] = url
            urls.append(url)
    return urls


def roster(contracts: dict[str, dict[str, Any]], library: dict[str, Any]) -> tuple[dict[str, dict], set[str]]:
    """{cid: entity} of main + recurring characters, and the main-character ids."""
    entities: dict[str, dict[str, Any]] = {}
    mains: set[str] = set()
    speaks: dict[str, int] = {}
    for contract in contracts.values():
        for ent in contract.get("character_entities") or []:
            if isinstance(ent, dict) and ent.get("character_id"):
                entities.setdefault(str(ent["character_id"]), ent)
        mains |= {str(c) for c in contract.get("protagonist_ids") or []}
        for cid in {str(u.get("speaker_id")) for u in (contract.get("audio_contract") or {}).get("dialogue_units") or []
                    if isinstance(u, dict)}:
            speaks[cid] = speaks.get(cid, 0) + 1
    core = {cid for cid, row in ((library.get("assets") or {}).get("characters") or {}).items()
            if isinstance(row, dict) and row.get("priority") == "SERIES_CORE"}
    wanted = [c for c in entities if c in mains] + [c for c in entities if c not in mains and
                                                     (c in core or speaks.get(c, 0) >= 2)]
    return {c: entities[c] for c in wanted[:MAX_CHARACTERS]}, mains


# ---------------------------------------------------------------- payload
def build_character(cid: str, entity: dict[str, Any], *, is_main: bool, episode: str, language: str,
                    paths: dict[str, Path], registry: dict[str, Any], cast: dict[str, Any],
                    char_registry: dict[str, Any], library: dict[str, Any], uploads: dict[str, str],
                    version: int, dry_run: bool) -> tuple[dict[str, Any] | None, str | None]:
    """(character payload, None) or (None, skip reason)."""
    crow = (cast.get("characters") or {}).get(cid) or {}
    row = voice_row(cid, entity, crow, registry)
    if not row:
        return None, "NO_LOCKED_VOICE_IN_REGISTRY"
    anchor = str(row.get("remote_url") or "").strip()
    if not public_https(anchor):
        return None, "VOICE_ANCHOR_NOT_PUBLIC_HTTPS"
    voice_id = row.get("generation_voice_id") or row.get("voice_id") or row.get("remote_asset_id")
    if not voice_id:
        return None, "VOICE_ID_MISSING"
    try:
        duration = float(row.get("duration_seconds")) if row.get("duration_seconds") is not None else None
    except (TypeError, ValueError):
        duration = None
    if duration is not None and duration > MAX_ANCHOR_SECONDS:
        return None, f"VOICE_ANCHOR_OVER_{int(MAX_ANCHOR_SECONDS)}S:{duration}"
    notes: list[str] = []
    images = resolve_images(image_candidates(cid, char_registry, library), uploads, dry_run=dry_run, notes=notes)
    if not images:
        return None, "NO_PUBLIC_REFERENCE_IMAGE" + (f":{','.join(sorted(set(notes)))}" if notes else "")
    name = str(entity.get("canonical_name") or row.get("character") or cid)
    gender = gender_of(entity.get("sex"), entity.get("gender"), row.get("gender"), crow.get("gender"),
                       (entity.get("identity_lock") or {}).get("sex"))
    style = str(crow.get("timbre_brief") or row.get("voice_selection") or row.get("voice_name") or "").strip()
    lang = str(row.get("language") or "").strip() or LANG.get(str(language or "zh").lower().split("-")[0], "zh-CN")
    voice: dict[str, Any] = {
        "provider": "giggle", "model": video_model(episode, row), "id": str(voice_id), "anchor_url": anchor,
        "version": int(version), "status": "active", "language": lang}
    if gender:
        voice["gender"] = gender
    if style:
        voice["style"] = style[:200]
    band = crow.get("f0_band_hz")
    if isinstance(band, list) and len(band) == 2:
        voice["f0_min"], voice["f0_max"] = round(float(band[0]), 1), round(float(band[1]), 1)
    if crow.get("reference_f0_hz"):
        voice["f0_median"] = round(float(crow["reference_f0_hz"]), 1)
    voice["speaker_voice_contract"] = (
        f"{name} ({cid}): locked series voice v{version}; the same anchor audio for every episode and ad; "
        "native speech by the video model from the anchor, one speaking identity per voice, never shared with "
        "another character, no TTS substitution")
    vmeta = {"duration_seconds": duration, "voice_name": row.get("voice_name") or row.get("generation_voice_name"),
             "remote_asset_id": row.get("remote_asset_id"), "anchor_sha256": row.get("local_sha256"),
             "episode_first_locked": row.get("episode_first_locked"),
             "note": "anchor shorter than the recommended 3-10 s is the line's native H3 reference clip"
                     if duration is not None and duration < 3 else None}
    voice["metadata"] = {k: v for k, v in vmeta.items() if v is not None}
    role = str(entity.get("role") or ("main character" if is_main else "supporting character"))
    meta = {"source": "nalu", "episode": episode, "english_name": entity.get("english_name"),
            "apparent_age": entity.get("apparent_age_range")}
    return {"character_id": cid, "character_name": name, "role": role, "is_main_character": bool(is_main),
            "is_fictional": True, "reference_image_urls": images, "voice": voice,
            "metadata": {k: v for k, v in meta.items() if v}}, None


def voice_identity(char: dict[str, Any]) -> str:
    v = char["voice"]
    return hashlib.sha256(json.dumps([v["provider"], v["id"], v["anchor_url"]]).encode()).hexdigest()


def payload_hash(char: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(char, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- HTTP (non-blocking)
def try_call(endpoint: str, payload: dict[str, Any]) -> tuple[bool, int | None, Any]:
    """mx.call with 2 attempts; never raises -- returns (ok, http, body / error)."""
    try:
        http, data = mx.call(endpoint, payload, attempts=2)
        return True, http, data
    except SystemExit as exc:
        try:
            err = json.loads(str(exc.code))
        except ValueError:
            err = {"detail": str(exc.code)[:300]}
        return False, err.get("http") if isinstance(err, dict) else None, err
    except Exception as exc:  # noqa: BLE001
        return False, None, {"error": f"{type(exc).__name__}: {exc}"[:300]}


def _code(err: Any) -> str | None:
    if not isinstance(err, dict):
        return None
    body = err.get("body")
    return err.get("code") or (body.get("code") if isinstance(body, dict) else None)


# ---------------------------------------------------------------- main entry
def run(series_key: str | None = None, episode: str | None = None, *, dry_run: bool = False,
        force: bool = False) -> dict[str, Any]:
    if not mx.matrix_mode():  # single-machine / open-api deployments have no device matrix: nothing to send
        return {"status": "SKIPPED", "reason": "X2C_OPEN_API_MODE"}
    if not enabled() and not dry_run:
        return {"status": "DISABLED", "reason": "X2C_CREATIVE_CONTEXT=off"}
    state = mx.load_state()
    key = series_key or state.get("current_series")
    series = (state.get("series") or {}).get(key or "") or {}
    project = series.get("project_id")
    if not project and not dry_run:
        return {"status": "NO_PROJECT_YET", "series_key": key}
    published = [ep for ep, r in (series.get("episodes") or {}).items() if r.get("receipt")] or \
        list((series.get("episodes") or {}).keys())
    ep_sort = lambda e: int(re.sub(r"\D", "", e) or 0)  # noqa: E731
    episode = episode or (max(published, key=ep_sort) if published else None)
    if not episode:
        return {"status": "NO_EPISODE", "series_key": key}
    contracts = {ep: c for ep in sorted(set(published) | {episode}, key=ep_sort) if (c := contract_for(ep))}
    paths = runtime_paths(episode)
    registry = read_json(paths["voice_registry"]) or {}
    cast = read_json(paths["voice_cast"]) or {}
    char_registry = read_json(paths["character_registry"]) or \
        read_json(px.runtime() / "runtime" / "character_asset_registry.json") or {}
    library = read_json(paths["asset_library"]) or {}
    language = str((contracts.get(episode) or {}).get("dialogue_language") or "zh")
    ctx = series.setdefault("creative_context", {"characters": {}, "image_uploads": {}})
    ctx.setdefault("characters", {})
    uploads = dict(ctx.setdefault("image_uploads", {}))
    chosen, mains = roster(contracts, library)
    sn = mx.device_sn() if not dry_run else os.environ.get("NALU_DEVICE_SN", "<device_sn>")
    result: dict[str, Any] = {"status": "OK", "dry_run": dry_run, "series_key": key, "project_id": project,
                              "episode": episode, "environment": mx.environment(), "sent": [], "unchanged": [],
                              "skipped": {}, "failed": {}, "retired": []}
    if not chosen:
        result["status"] = "NO_CHARACTERS"
    payloads: list[dict[str, Any]] = []
    route_down = False
    for cid, entity in chosen.items():
        rec = ctx["characters"].setdefault(cid, {})
        version = int(rec.get("voice_version") or 1)
        try:
            char, why = build_character(cid, entity, is_main=cid in mains, episode=episode, language=language,
                                        paths=paths, registry=registry, cast=cast, char_registry=char_registry,
                                        library=library, uploads=uploads, version=version, dry_run=dry_run)
        except SystemExit as exc:  # an image upload failed
            char, why = None, f"IMAGE_UPLOAD_FAILED:{str(exc.code)[:200]}"
        if char is None:
            result["skipped"][cid] = why
            rec.update(skipped=why, checked_at=now())
            continue
        rec.pop("skipped", None)
        ident = voice_identity(char)
        needs_retire = bool(rec.get("voice_identity") and rec["voice_identity"] != ident and rec.get("acked_version"))
        if needs_retire:
            version = int(rec["acked_version"]) + 1
            char["voice"]["version"] = version
            char["voice"]["speaker_voice_contract"] = char["voice"]["speaker_voice_contract"].replace(
                f"voice v{rec['acked_version']}", f"voice v{version}", 1)
        digest = payload_hash(char)
        if not force and rec.get("payload_sha256") == digest and rec.get("last_status") == "SENT":
            result["unchanged"].append(cid)
            continue
        payloads.append(char)
        if dry_run or route_down:
            continue
        if needs_retire and int(rec["acked_version"]) not in (rec.get("retired_versions") or []):
            old = int(rec["acked_version"])
            ok, http, body = try_call(RETIRE, {"device_sn": sn, "project_id": project, "series_key": key,
                                               "character_id": cid, "voice_version": old})
            if not ok:
                rec.update(last_status="RETIRE_FAILED", http=http, error=body, last_attempt_at=now())
                result["failed"][cid] = {"step": "retire", "http": http, "code": _code(body)}
                route_down = route_down or _code(body) == "UNKNOWN_ROUTE"
                continue
            rec.setdefault("retired_versions", []).append(old)
            result["retired"].append({"character_id": cid, "voice_version": old})
        ok, http, body = try_call(ENDPOINT, {"device_sn": sn, "project_id": project, "series_key": key,
                                             "characters": [char]})
        rec["last_attempt_at"] = now()
        if ok:
            rec.update(payload_sha256=digest, voice_identity=ident, voice_version=version, acked_version=version,
                       voice_id=char["voice"]["id"], anchor_url=char["voice"]["anchor_url"], last_status="SENT",
                       http=http, sent_at=now(), image_count=len(char["reference_image_urls"]), error=None)
            result["sent"].append(cid)
        else:
            rec.update(last_status="FAILED", http=http, error=body, voice_version=version)
            result["failed"][cid] = {"step": "creative-context", "http": http, "code": _code(body)}
            route_down = route_down or _code(body) == "UNKNOWN_ROUTE"
    if route_down:
        result["route_not_live"] = True
    if result["failed"]:
        result["status"] = "PARTIAL" if result["sent"] else "FAILED"
    if dry_run:
        result["payload"] = {"device_sn": sn, "project_id": project, "series_key": key, "characters": payloads}
        return result
    ctx["image_uploads"] = uploads
    ctx["last_run"] = {k: result[k] for k in ("status", "episode", "sent", "unchanged", "skipped", "failed", "retired")}
    ctx["last_run"]["at"] = now()
    # re-read and merge: the publisher may have written the state while we were uploading
    fresh = mx.load_state()
    fresh.setdefault("series", {}).setdefault(key, series)["creative_context"] = ctx
    mx.save_state(fresh)
    return result


def after_publish(series_key: str, episode: str) -> dict[str, Any]:
    """Hook for publish / add-episodes: never raises, never blocks the release."""
    try:
        out = run(series_key, episode)
    except BaseException as exc:  # noqa: BLE001  (SystemExit included: nothing here may stop the line)
        out = {"status": "ERROR", "error": f"{type(exc).__name__}: {str(exc)[:300]}"}
        try:
            state = mx.load_state()
            ctx = state["series"][series_key].setdefault("creative_context", {"characters": {}})
            ctx["last_run"] = {"status": "ERROR", "episode": episode, "error": out["error"], "at": now()}
            mx.save_state(state)
        except Exception:  # noqa: BLE001
            pass
    return {k: v for k, v in out.items() if k != "payload"}
