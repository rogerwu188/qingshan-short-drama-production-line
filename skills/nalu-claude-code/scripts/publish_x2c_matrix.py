#!/usr/bin/env python3
"""Distribute finished NALU episodes through X2C's "StoryClaw 设备矩阵 API" (matrix mode).

Doc: https://www.x2creel.ai/matrix-api-docs (V1.3.0, OpenAPI /matrix-openapi.json).  Six POST JSON
endpoints, header ``X-API-Key`` (the user's existing X2C key) and ``device_sn`` in every body; no
``action`` field, no category.  This mode is selected by ``publish_x2creel.py`` when
``X2C_API_MODE=matrix`` (or, with X2C_API_MODE unset, when NALU_DEVICE_SN / X2C_MATRIX_API_URL is set);
``X2C_API_MODE=open`` forces the legacy open-api flow.

  publish_x2creel.py publish --episode E01 [--title --description --hashtags a,b --video --cover
                                            --series-key --episode-number N --resend]
  publish_x2creel.py status        (/distribution/status: review_status + matrix_jobs per episode)
  publish_x2creel.py list          (/distribution/list: this device's series)
  publish_x2creel.py close --series <series_key>   (/distribution/close; then a new series can start)

Env: NALU_DEVICE_SN (required), NALU_DEVICE_NAME (optional), X2C_MATRIX_API_URL (default = X2C PRODUCTION
https://ukbyfmmerxhlghlhbxtz.supabase.co/functions/v1/matrix-api/v1, where the device mappings live; TEST is
https://pdypbtafttzriqdnpmta.supabase.co/functions/v1/matrix-api/v1).  Key: $X2C_API_KEY or $NALU_RUNTIME_ROOT/credentials/x2c_api_key, never printed.

publish: upload-url + PUT for the video (default the clean final <EP>_final_9x16.mp4 — X2C adds ads
itself) and the cover (default a frame grab), then /distribution/publish for the series' first episode
and /distribution/add-episodes for every later one.  title / description / hashtags default to the
brief ($NALU_RUNTIME_ROOT/briefs/<EP>_PRODUCTION_BRIEF.json: title, synopsis, hashtags);
episode_number = brief episode_display_number, else the EP number; duration_seconds = ffprobe of the
exact file uploaded.  series_key = brief ``series_key``, else "<title slug>-<lang>"; it is recorded in
the state and reused for every later episode of the series.

X2C's idempotency key is device + series_key + episode_number: the same body again -> 200
``idempotent: true``; different content -> 409.  The request body is saved in the state BEFORE it is
sent, so a crashed or retried run re-sends the identical body (never new URLs, never a new key/number).
A recorded episode is answered locally (ALREADY_PUBLISHED) unless ``--resend`` re-posts the saved body.
State: $NALU_RUNTIME_ROOT/distribution/x2c_matrix.json (separate from the legacy x2creel.json).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import publish_x2creel as px  # noqa: E402

# X2C's matrix API environments.  Default PRODUCTION (owner 2026-11-05: the device mappings live there;
# production test passed).  TEST ("outbound dispatch paused", no production device mappings) via
# X2C_MATRIX_API_URL=<TEST_API>.
TEST_API = "https://pdypbtafttzriqdnpmta.supabase.co/functions/v1/matrix-api/v1"
PROD_API = "https://ukbyfmmerxhlghlhbxtz.supabase.co/functions/v1/matrix-api/v1"
MAX_VIDEO = 1 << 30
MAX_COVER = 20 << 20
RETRY_HTTP = (429, 500, 502, 503, 504)
SLEEP = time.sleep  # patched in tests


def matrix_mode() -> bool:
    mode = os.environ.get("X2C_API_MODE", "").strip().lower()
    if mode in ("open", "legacy", "open-api"):
        return False
    if mode == "matrix":
        return True
    return bool(os.environ.get("NALU_DEVICE_SN", "").strip() or os.environ.get("X2C_MATRIX_API_URL", "").strip())


def base_url() -> str:
    return (os.environ.get("X2C_MATRIX_API_URL") or PROD_API).rstrip("/")


def environment() -> str:
    return {TEST_API: "TEST", PROD_API: "PRODUCTION"}.get(base_url(), "CONFIGURED")


def device_sn() -> str:
    """$NALU_DEVICE_SN, else this machine's hardware serial (device_sn.py: cache, sysfs, dmidecode, sudo -n)."""
    import device_sn as dsn  # same directory
    sn, _source = dsn.resolve()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", sn):
        raise SystemExit(json.dumps({"status": "BLOCKED", "reason": "NALU_DEVICE_SN_MISSING" if not sn else
                                     "NALU_DEVICE_SN_INVALID",
                                     "hint": "no hardware serial readable: set NALU_DEVICE_SN to this device's SN "
                                             "registered in X2C 设备矩阵映射"}))
    return sn


def device_name() -> str:
    return os.environ.get("NALU_DEVICE_NAME", "").strip()[:100]


# ---------------------------------------------------------------- state
def state_path() -> Path:
    return px.runtime() / "distribution" / "x2c_matrix.json"


def load_state() -> dict[str, Any]:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": "nalu.x2c_matrix_distribution.v1", "current_series": None, "series": {}}


def save_state(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sent_episodes() -> dict[str, Any]:
    """EP -> record for every episode X2C acknowledged in the current (open) series."""
    state = load_state()
    series = state["series"].get(state.get("current_series") or "") or {}
    return {ep: row for ep, row in (series.get("episodes") or {}).items() if row.get("receipt")}


# ---------------------------------------------------------------- HTTP
def _post(url: str, body: bytes, headers: dict[str, str]) -> tuple[int, Any]:
    """One POST; returns (http status, parsed JSON or raw text).  The fake HTTP layer in tests."""
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    text = raw.decode("utf-8", "replace")
    try:
        return status, json.loads(text)
    except ValueError:
        return status, text[:500]


def call(endpoint: str, payload: dict[str, Any], attempts: int = 5) -> tuple[int, dict[str, Any]]:
    """POST {base}/{endpoint}; retries network errors / 429 / 5xx with the identical body."""
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = f"{base_url()}/{endpoint.lstrip('/')}"
    last: Any = None
    for attempt in range(attempts):
        headers = {"X-API-Key": px.api_key(), "Content-Type": "application/json", "User-Agent": px.UA}
        try:
            status, data = _post(url, body, headers)
        except (urllib.error.URLError, OSError) as exc:
            last = {"network": type(exc).__name__}
            SLEEP(15 * (attempt + 1))
            continue
        if 200 <= status < 300 and isinstance(data, dict):
            return status, data
        last = {"http": status, "body": data}
        if status in RETRY_HTTP:
            SLEEP(15 * (attempt + 1))
            continue
        code = data.get("code") if isinstance(data, dict) else None
        raise SystemExit(json.dumps({"status": "ERROR", "endpoint": endpoint, "http": status, "code": code,
                                     "body": data}, ensure_ascii=False))
    raise SystemExit(json.dumps({"status": "ERROR", "endpoint": endpoint, "reason": "RETRIES_EXHAUSTED",
                                 "last": last}, ensure_ascii=False))


def upload(path: Path, content_type: str) -> str:
    _, up = call("distribution/upload-url", {"device_sn": device_sn(), "content_type": content_type})
    px.put_file(up, path)
    return up["public_url"]


# ---------------------------------------------------------------- helpers
def duration_seconds(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                          "default=noprint_wrappers=1:nokey=1", str(path)], check=True, capture_output=True, text=True)
    return round(float(out.stdout.strip()), 3)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def derive_series_key(brief: dict[str, Any], title: str, lang: str) -> str:
    if brief.get("series_key"):
        return str(brief["series_key"]).strip()[:150]
    lang = px._lang_code(lang)
    base = slug(title)[:120] or "series-" + hashlib.sha256(title.encode("utf-8")).hexdigest()[:12]
    return f"{base}-{lang}"


def episode_number(episode: str, brief: dict[str, Any]) -> int | None:
    try:
        return int(brief.get("episode_display_number"))
    except (TypeError, ValueError):
        m = re.search(r"(\d+)", episode)
        return int(m.group(1)) if m else None


def read_brief(episode: str) -> dict[str, Any]:
    try:
        return json.loads((px.runtime() / "briefs" / f"{episode}_PRODUCTION_BRIEF.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _hashtags(raw: Any) -> list[str]:
    items = raw if isinstance(raw, list) else str(raw or "").split(",")
    tags = [str(t).strip() for t in items if str(t).strip()]
    return [t for t in tags if re.fullmatch(r"#?[A-Za-z0-9_]{1,80}", t)][:20]


# ---------------------------------------------------------------- commands
def cmd_publish(a: argparse.Namespace) -> dict[str, Any]:
    sn = device_sn()
    brief = read_brief(a.episode)
    state = load_state()
    open_series = state["series"].get(state.get("current_series") or "") or {}
    title = (getattr(a, "title", "") or str(brief.get("title") or "") or str(open_series.get("title") or "")).strip()[:100]
    description = (getattr(a, "description", "") or str(brief.get("synopsis") or "")).strip()[:2000]
    lang = getattr(a, "lang", "") or str(brief.get("genre_lang") or brief.get("dialogue_language") or "zh")
    key = (getattr(a, "series_key", "") or "").strip() or state.get("current_series") \
        or (derive_series_key(brief, title, lang) if title else "")
    number = getattr(a, "episode_number", None) or episode_number(a.episode, brief)
    video = Path(a.video).expanduser() if getattr(a, "video", "") else \
        px.runtime() / "deliverables" / a.episode / f"{a.episode}_final_9x16.mp4"
    if not video.is_file():
        return {"status": "BLOCKED", "reason": f"FINAL_CUT_MISSING:{video}"}
    if not title or not key or not number:
        return {"status": "BLOCKED", "reason": "MATRIX_PUBLISH_NEEDS_TITLE_SERIES_KEY_EPISODE_NUMBER",
                "title": bool(title), "series_key": key or None, "episode_number": number}
    if state.get("current_series") and key != state["current_series"]:
        return {"status": "BLOCKED", "reason": "ANOTHER_SERIES_OPEN", "open_series": state["current_series"],
                "hint": "X2C allows one open series per device: `close --series <open_series>` first"}
    if video.stat().st_size > MAX_VIDEO:
        return {"status": "BLOCKED", "reason": "VIDEO_OVER_1GIB", "bytes": video.stat().st_size}
    digest = px.sha256(video)
    series = state["series"].setdefault(key, {"project_id": None, "closed": False, "title": title, "episodes": {}})
    if series.get("closed"):
        return {"status": "BLOCKED", "reason": "SERIES_CLOSED", "series_key": key}
    row = series["episodes"].get(a.episode)
    clash = sorted(ep for ep, r in series["episodes"].items() if ep != a.episode and r.get("episode_number") == number)
    if clash:
        return {"status": "BLOCKED", "reason": "EPISODE_NUMBER_TAKEN", "episode_number": number, "held_by": clash}

    if row and row.get("video_sha256") != digest:
        if row.get("receipt"):  # same key, new content -> X2C answers 409; never change key/number to dodge it
            return {"status": "BLOCKED", "reason": "EPISODE_ALREADY_SENT_WITH_OTHER_VIDEO", "episode": a.episode,
                    "series_key": key, "episode_number": row.get("episode_number"),
                    "hint": "X2C keeps the first version (409 on different content); ask the line owner / X2C admin"}
        row = None  # an unsent pending request for an older cut: rebuild it
    if row and row.get("receipt") and not getattr(a, "resend", False):
        return {"status": "ALREADY_PUBLISHED", "episode": a.episode, "series_key": key,
                "project_id": series.get("project_id"), "episode_id": row.get("episode_id"),
                "episode_number": row.get("episode_number"), "published_video": row.get("published_video")}

    if row and row.get("request"):
        endpoint, body = row["endpoint"], row["request"]  # identical body: X2C's idempotent path
    else:
        cover = Path(a.cover).expanduser() if getattr(a, "cover", "") else px.cover_from_video(video)
        ctype = px.mime(cover)
        if ctype not in ("image/jpeg", "image/png"):
            return {"status": "BLOCKED", "reason": f"COVER_TYPE_UNSUPPORTED:{ctype}"}
        if cover.stat().st_size > MAX_COVER:
            return {"status": "BLOCKED", "reason": "COVER_OVER_20MIB", "bytes": cover.stat().st_size}
        dur = duration_seconds(video)
        body = {"device_sn": sn, "series_key": key, "episode_number": int(number), "title": title,
                "video_url": upload(video, "video/mp4"), "cover_url": upload(cover, ctype), "duration_seconds": dur}
        if device_name():
            body["device_name"] = device_name()
        if description:
            body["description"] = description
        tags = _hashtags(getattr(a, "hashtags", "") or brief.get("hashtags"))
        if tags:
            body["hashtags"] = tags
        endpoint = "distribution/add-episodes" if series.get("project_id") else "distribution/publish"
        row = {"episode_number": int(number), "video_sha256": digest, "published_video": str(video),
               "endpoint": endpoint, "request": body, "prepared_at": datetime.now(timezone.utc).isoformat()}
        series["episodes"][a.episode] = row
        state["current_series"] = key
        save_state(state)  # saved before sending: a retry re-sends this exact body

    http, res = call(endpoint, body)
    series["project_id"] = series.get("project_id") or res.get("project_id")
    row.update(episode_id=res.get("episode_id"), receipt=res, http=http,
               last_sent_at=datetime.now(timezone.utc).isoformat())
    row.setdefault("first_receipt", res)
    state["current_series"] = key
    save_state(state)
    return {"status": "PUBLISHED", "environment": environment(), "endpoint": endpoint, "http": http,
            "idempotent": bool(res.get("idempotent")), "episode": a.episode, "series_key": key,
            "project_id": res.get("project_id"), "episode_id": res.get("episode_id"),
            "episode_number": res.get("episode_number", number), "account_id": res.get("account_id"),
            "routing_status": res.get("routing_status"), "review_status": res.get("review_status"),
            "x2c_status": res.get("review_status"), "published_video": str(video), "published_variant": "FINAL",
            "duration_seconds": body.get("duration_seconds")}


def _project_for(state: dict[str, Any], key: str | None) -> tuple[str | None, str | None]:
    key = key or state.get("current_series")
    return key, ((state["series"].get(key or "") or {}).get("project_id"))


def cmd_status(a: argparse.Namespace) -> dict[str, Any]:
    state = load_state()
    key, project = _project_for(state, getattr(a, "series", None))
    if not project:
        return {"status": "NO_PROJECT_YET", "series_key": key, "state": state}
    sn, offset, episodes, head = device_sn(), 0, [], {}
    while offset is not None:
        _, page = call("distribution/status", {"device_sn": sn, "project_id": project, "offset": offset})
        head = page
        episodes += page.get("episodes") or []
        offset = page.get("next_offset")
    local = {r.get("episode_id"): ep for ep, r in (state["series"][key].get("episodes") or {}).items()}
    return {"status": "OK", "environment": environment(), "series_key": key, "project_id": project,
            "closed": head.get("closed"), "routing_status": head.get("routing_status"),
            "account_id": head.get("account_id"), "blocked_reason": head.get("blocked_reason"),
            "episodes": [{"local_episode": local.get(e.get("id")), "episode_number": e.get("episode_number"),
                          "episode_id": e.get("id"), "review_status": e.get("review_status"),
                          "review_note": e.get("review_note"), "matrix_jobs": e.get("matrix_jobs"),
                          **({"matrix_publications": e["matrix_publications"]} if "matrix_publications" in e else {})}
                         for e in episodes]}


def cmd_list(a: argparse.Namespace) -> dict[str, Any]:
    sn, offset, projects = device_sn(), 0, []
    while True:
        _, page = call("distribution/list", {"device_sn": sn, "offset": offset})
        rows = page.get("projects") or []
        projects += rows
        if len(rows) < 100:
            break
        offset += 100
    return {"status": "OK", "environment": environment(), "device_sn": sn, "projects": projects}


def cmd_close(a: argparse.Namespace) -> dict[str, Any]:
    state = load_state()
    key, project = _project_for(state, a.series)
    if not project:
        return {"status": "BLOCKED", "reason": "SERIES_NOT_IN_LOCAL_STATE", "series_key": a.series}
    _, res = call("distribution/close", {"device_sn": device_sn(), "project_id": project})
    state["series"][key]["closed"] = bool(res.get("closed", True))
    state["series"][key]["closed_at"] = datetime.now(timezone.utc).isoformat()
    if state.get("current_series") == key:
        state["current_series"] = None
    save_state(state)
    return {"status": "CLOSED", "series_key": key, "project_id": project, "response": res}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("publish")
    p.add_argument("--episode", required=True)
    for opt in ("--title", "--description", "--hashtags", "--video", "--cover", "--series-key", "--lang"):
        p.add_argument(opt, default="")
    p.add_argument("--episode-number", type=int, default=None)
    p.add_argument("--resend", action="store_true", help="re-post the recorded request (X2C answers idempotent:true)")
    s = sub.add_parser("status"); s.add_argument("--series", default=None)
    sub.add_parser("list")
    c = sub.add_parser("close"); c.add_argument("--series", required=True)
    a = ap.parse_args(argv)
    out = {"publish": cmd_publish, "status": cmd_status, "list": cmd_list, "close": cmd_close}[a.cmd](a)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["status"] not in ("BLOCKED", "ERROR") else 3


if __name__ == "__main__":
    sys.exit(main())
