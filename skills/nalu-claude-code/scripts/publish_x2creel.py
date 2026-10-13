#!/usr/bin/env python3
"""Distribute finished NALU episodes to X2C (x2creel.ai) through its open API.

Workflow (https://www.x2creel.ai/api-docs, 分发 API):
  distribution/categories -> distribution/upload-url -> HTTP PUT the files -> distribution/publish
  (first episode creates the project) / distribution/add-episodes (every later episode) ->
  distribution/query.  Developer-JWT publishing (3.5) is not used.

  publish_x2creel.py categories [--lang zh]
  publish_x2creel.py publish --episode E01 --title <剧名> --description <简介> --category <名称或 id>
                             [--video <mp4>] [--cover <jpg/png>]
  publish_x2creel.py status
  publish_x2creel.py forget --episode E02     (drop one episode's local record, backed up, so it can be re-sent)

State lives in $NALU_RUNTIME_ROOT/distribution/x2creel.json: the project id, the category, and every
episode already sent (with the video SHA-256), so a re-run never publishes or appends an episode
twice (the key is the video SHA-256; to re-send the same cut, ``forget`` the episode first).

Pending-review guard: X2C numbers an appended episode as (approved episodes + 1), so appending while an
earlier episode is still ``pending_review`` silently gives the new one the SAME number and replaces it.
``publish`` therefore queries the project first and returns DEFERRED_PENDING_REVIEW (exit 0, nothing
sent) while ``pending_videos`` is non-empty; the caller retries on a later heartbeat.  A number already
held by another local episode is reported as EPISODE_NUMBER_COLLISION.  The first ``publish`` creates the project; every later episode is appended to it.  The default
video is $NALU_RUNTIME_ROOT/deliverables/<EP>/<EP>_final_9x16.mp4 and the default cover is a frame
taken from it with ffmpeg.

The API key is read from $X2C_API_KEY, else $NALU_RUNTIME_ROOT/credentials/x2c_api_key (mode 600).
It is never printed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API = os.environ.get("X2C_API_URL", "https://ukbyfmmerxhlghlhbxtz.supabase.co/functions/v1/open-api")
UA = "nalu-short-drama-workflow/1.0"


def runtime() -> Path:
    return Path(os.environ.get("NALU_RUNTIME_ROOT") or "~/nalu_runtime").expanduser()


def state_path() -> Path:
    return runtime() / "distribution" / "x2creel.json"


def load_state() -> dict[str, Any]:
    try:
        return json.loads(state_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": "nalu.x2creel_distribution.v1", "project_id": None, "episodes": {}}


def save_state(state: dict[str, Any]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def api_key() -> str:
    key = os.environ.get("X2C_API_KEY", "").strip()
    if not key:
        f = runtime() / "credentials" / "x2c_api_key"
        key = f.read_text(encoding="utf-8").strip() if f.is_file() else ""
    if not key:
        raise SystemExit(json.dumps({"status": "BLOCKED", "reason": "X2C_API_KEY_MISSING",
                                     "hint": "write the key to $NALU_RUNTIME_ROOT/credentials/x2c_api_key (chmod 600)"}))
    return key


def call(action: str, **payload: Any) -> dict[str, Any]:
    body = json.dumps({"action": action, **payload}, ensure_ascii=False).encode("utf-8")
    for attempt in range(5):
        req = urllib.request.Request(API, data=body, method="POST", headers={
            "X-API-Key": api_key(), "Content-Type": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", "replace")[:500]
            if exc.code == 429 or exc.code >= 500:
                time.sleep(15 * (attempt + 1))
                continue
            raise SystemExit(json.dumps({"status": "ERROR", "action": action, "http": exc.code, "body": text},
                                        ensure_ascii=False))
        except urllib.error.URLError:
            time.sleep(15 * (attempt + 1))
            continue
        if not data.get("success"):
            raise SystemExit(json.dumps({"status": "ERROR", "action": action, "response": data}, ensure_ascii=False))
        return data
    raise SystemExit(json.dumps({"status": "ERROR", "action": action, "reason": "RETRIES_EXHAUSTED"}))


def put_file(upload: dict[str, Any], path: Path) -> None:
    headers = {k: v for k, v in (upload.get("upload_headers") or {}).items() if k.lower() != "host"}
    for attempt in range(4):
        req = urllib.request.Request(upload["upload_url"], data=path.read_bytes(),
                                     method=upload.get("upload_method") or "PUT", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=900) as resp:
                if 200 <= resp.status < 300:
                    return
        except (urllib.error.HTTPError, urllib.error.URLError):
            time.sleep(20 * (attempt + 1))
    raise SystemExit(json.dumps({"status": "ERROR", "reason": "UPLOAD_FAILED", "file": path.name}))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cover_from_video(video: Path) -> Path:
    out = Path(tempfile.mkdtemp()) / "cover.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "1.5", "-i", str(video), "-frames:v", "1", "-q:v", "2",
                    str(out)], check=True)
    return out


def mime(path: Path) -> str:
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
            ".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}.get(path.suffix.lower(),
                                                                                     "application/octet-stream")


def resolve_category(category: str) -> str:
    if len(category) == 36 and category.count("-") == 4:
        return category
    cats = call("distribution/categories", lang="zh").get("categories") or []
    for c in cats:
        if category in (c.get("name"), c.get("name_key")):
            return c["id"]
    for c in cats:  # fall back to the catch-all category
        if c.get("name") == "热门综合":
            return c["id"]
    raise SystemExit(json.dumps({"status": "ERROR", "reason": f"CATEGORY_NOT_FOUND:{category}",
                                 "available": [c.get("name") for c in cats]}, ensure_ascii=False))


def cmd_publish(a: argparse.Namespace) -> dict[str, Any]:
    state = load_state()
    video = Path(a.video or runtime() / "deliverables" / a.episode / f"{a.episode}_final_9x16.mp4").expanduser()
    if not video.is_file():
        return {"status": "BLOCKED", "reason": f"FINAL_CUT_MISSING:{video}"}
    digest = sha256(video)
    done = state["episodes"].get(a.episode)
    if done and done.get("video_sha256") == digest:
        return {"status": "ALREADY_PUBLISHED", "episode": a.episode, "project_id": state["project_id"],
                "episode_number": done.get("episode_number")}

    if not state.get("project_id") and not (a.title and a.description and a.category):
        return {"status": "BLOCKED", "reason": "FIRST_PUBLISH_NEEDS_TITLE_DESCRIPTION_CATEGORY"}
    files = [{"file_type": "video", "file_name": f"{a.episode}.mp4", "content_type": mime(video)}]
    cover = None
    if not state.get("project_id"):
        cover = Path(a.cover).expanduser() if a.cover else cover_from_video(video)
        files.insert(0, {"file_type": "cover", "file_name": f"cover{cover.suffix or '.jpg'}", "content_type": mime(cover)})
    if state.get("project_id"):
        remote = call("distribution/query", project_id=state["project_id"])
        pending = remote.get("pending_videos") or []
        if pending:
            return {"status": "DEFERRED_PENDING_REVIEW", "episode": a.episode, "project_id": state["project_id"],
                    "pending_videos": pending, "approved_episodes": remote.get("total_episodes"),
                    "note": "an earlier episode is still pending review; appending now would reuse its number. "
                            "Nothing was sent; retry on a later heartbeat."}
    up = call("distribution/upload-url", files=files)
    urls: dict[str, str] = {}
    for row in up.get("uploads") or []:
        path = cover if row.get("file_type") == "cover" else video
        put_file(row, path)
        urls[row["file_type"]] = row["public_url"]

    now = datetime.now(timezone.utc).isoformat()
    if not state.get("project_id"):
        cat = resolve_category(a.category)
        res = call("distribution/publish", title=a.title[:100], description=a.description[:2000], category_id=cat,
                   cover_url=urls["cover"], video_urls=[urls["video"]], enable_prediction=False)
        state.update(project_id=res["project_id"], tag_id=res.get("tag_id"), category_id=cat,
                     title=a.title[:100], created_at=now)
        number = ((res.get("episodes") or [{}])[0]).get("episode_number", 1)
        status = res.get("status")
    else:
        res = call("distribution/add-episodes", project_id=state["project_id"], video_urls=[urls["video"]])
        number = ((res.get("new_episodes") or [{}])[0]).get("episode_number")
        status = res.get("routed_to")
    clash = sorted(ep for ep, row in state["episodes"].items()
                   if ep != a.episode and number is not None and row.get("episode_number") == number)
    state["episodes"][a.episode] = {"episode_number": number, "video_sha256": digest, "video_url": urls["video"],
                                    "sent_at": now, "status": status}
    if clash:
        state["episodes"][a.episode]["collides_with"] = clash
    save_state(state)
    return {"status": "EPISODE_NUMBER_COLLISION" if clash else "PUBLISHED", "episode": a.episode,
            "project_id": state["project_id"], "episode_number": number, "x2c_status": status,
            **({"collides_with": clash,
                "note": "X2C gave this episode a number another local episode already holds; that episode "
                        "was probably replaced. Check `status` and re-send it after this one is approved."}
               if clash else {})}


def cmd_forget(a: argparse.Namespace) -> dict[str, Any]:
    state = load_state()
    row = state["episodes"].pop(a.episode, None)
    if row is None:
        return {"status": "NOT_FOUND", "episode": a.episode}
    backup = state_path().with_name(f"x2creel.{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.bak.json")
    backup.write_text(state_path().read_text(encoding="utf-8"), encoding="utf-8")
    save_state(state)
    return {"status": "FORGOTTEN", "episode": a.episode, "removed": row, "backup": str(backup)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("categories"); c.add_argument("--lang", default="zh")
    p = sub.add_parser("publish")
    p.add_argument("--episode", required=True); p.add_argument("--title", default="")
    p.add_argument("--description", default=""); p.add_argument("--category", default="")
    p.add_argument("--video", default=""); p.add_argument("--cover", default="")
    sub.add_parser("status")
    f = sub.add_parser("forget"); f.add_argument("--episode", required=True)
    a = ap.parse_args()
    if a.cmd == "categories":
        out = {"status": "OK", "categories": [{"id": x["id"], "name": x["name"]}
                                              for x in call("distribution/categories", lang=a.lang).get("categories") or []]}
    elif a.cmd == "publish":
        out = cmd_publish(a)
    elif a.cmd == "forget":
        out = cmd_forget(a)
    else:
        state = load_state()
        numbers: dict[Any, list[str]] = {}
        for ep, row in state["episodes"].items():
            numbers.setdefault(row.get("episode_number"), []).append(ep)
        dupes = {str(n): eps for n, eps in numbers.items() if n is not None and len(eps) > 1}
        out = {"status": "NO_PROJECT_YET", "state": state} if not state.get("project_id") else {
            "status": "OK", "local": state, "local_number_collisions": dupes,
            "remote": call("distribution/query", project_id=state["project_id"])}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out["status"] not in ("BLOCKED", "ERROR") else 3


if __name__ == "__main__":
    sys.exit(main())
