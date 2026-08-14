#!/usr/bin/env python3
"""
Generate and register Qingshan reference assets through Giggle OpenAPI.

The API key is read only from GIGGLE_API_KEY. This tool is meant for missing
character, prop, scene, and future sound assets: generate the asset, download
the result, hash it, and write it back to a local manifest with evidence.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_URL = "https://giggle.pro/api/v1/generation"


def api_key() -> str:
    key = os.environ.get("GIGGLE_API_KEY", "").strip()
    if not key:
        raise SystemExit("Missing GIGGLE_API_KEY.")
    return key


def request_json(method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data = None
    headers = {
        "x-auth": api_key(),
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://giggle.pro",
        "Referer": "https://giggle.pro/",
        "User-Agent": "qingshan-giggle-asset-factory/1.0",
    }
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw}") from exc


def media_b64(path: Path) -> str:
    # Giggle image-to-image expects the raw Base64 payload here, not a data URI.
    return base64.b64encode(path.read_bytes()).decode("ascii")


def query_task(task_id: str) -> Dict[str, Any]:
    query = urllib.parse.urlencode({"task_id": task_id})
    return request_json("GET", f"/task/query?{query}")


def wait_for_task(task_id: str, out_dir: Path, poll_seconds: int, timeout_minutes: int) -> Dict[str, Any]:
    deadline = time.time() + timeout_minutes * 60
    while time.time() < deadline:
        response = query_task(task_id)
        (out_dir / "last_query_response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        data = response.get("data") or {}
        status = data.get("status")
        if status == "completed":
            return response
        if status in {"failed", "error", "canceled", "cancelled"}:
            raise SystemExit(json.dumps(response, ensure_ascii=False, indent=2))
        time.sleep(poll_seconds)
    raise SystemExit(f"Timed out waiting for task {task_id}; last response saved in {out_dir}.")


def download(url: str, out_path: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "qingshan-giggle-asset-factory/1.0"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        out_path.write_bytes(resp.read())


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(path: Path) -> Dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "schema": "qingshan.reference_asset_manifest.v1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "purpose": "Giggle API generated or registered reference assets.",
        "assets": {},
    }


def update_manifest(args: argparse.Namespace, asset_path: Path, task_id: Optional[str], source_urls: List[str]) -> None:
    manifest_path = Path(args.manifest).expanduser().resolve()
    manifest = load_manifest(manifest_path)
    assets = manifest.setdefault("assets", {})
    assets[args.asset_id] = {
        "path": str(asset_path.resolve()),
        "sha256": sha256(asset_path),
        "role": args.role,
        "category": args.category,
        "source": {
            "tool": "tools/giggle_asset_factory.py",
            "mode": args.cmd,
            "model": getattr(args, "model", None),
            "task_id": task_id,
            "urls": source_urls,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def prompt_text(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return Path(args.prompt_file).expanduser().read_text(encoding="utf-8")
    return args.prompt


def image_ext_from_url(url: str) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suffix if suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"


def generate_image(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    refs = [Path(path).expanduser().resolve() for path in args.reference_image or []]
    for path in refs:
        if not path.exists():
            raise SystemExit(f"Missing reference image: {path}")

    payload: Dict[str, Any] = {
        "prompt": prompt_text(args),
        "generate_count": args.count,
        "model": args.model,
        "aspect_ratio": args.aspect_ratio,
        "resolution": args.resolution,
        "watermark": False,
    }
    endpoint = "/text-to-image"
    if refs:
        endpoint = "/image-to-image"
        payload["reference_images"] = [{"base64": media_b64(path)} for path in refs]

    submit_response = request_json("POST", endpoint, payload)
    (out_dir / "submit_response.json").write_text(json.dumps(submit_response, ensure_ascii=False, indent=2), encoding="utf-8")
    task_id = (submit_response.get("data") or {}).get("task_id")
    if not task_id:
        raise SystemExit("Submit response did not contain data.task_id.")
    result = wait_for_task(task_id, out_dir, args.poll_seconds, args.timeout_minutes)
    urls = (result.get("data") or {}).get("urls") or []
    if not urls:
        raise SystemExit("Completed image task returned no urls.")

    first = urls[0]
    asset_path = Path(args.asset_path).expanduser().resolve() if args.asset_path else out_dir / f"{args.asset_id}{image_ext_from_url(first)}"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    download(first, asset_path)
    # Keep every returned still candidate locally so visual QA can select a lock
    # before one video-generation pass spends additional credits.
    for index, url in enumerate(urls[1:], 2):
        candidate = out_dir / f"{args.asset_id}_candidate_{index:02d}{image_ext_from_url(url)}"
        download(url, candidate)
    update_manifest(args, asset_path, task_id, urls)
    print(json.dumps({"asset_id": args.asset_id, "asset_path": str(asset_path), "task_id": task_id}, ensure_ascii=False, indent=2))
    return 0


def register_media(args: argparse.Namespace) -> int:
    media_path = Path(args.media).expanduser().resolve()
    if not media_path.exists():
        raise SystemExit(f"Missing media file: {media_path}")
    update_manifest(args, media_path, None, [])
    print(json.dumps({"asset_id": args.asset_id, "asset_path": str(media_path)}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate/register Giggle-backed Qingshan reference assets.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    image = sub.add_parser("image", help="Generate a text-to-image or image-to-image asset and register it.")
    image.add_argument("--asset-id", required=True)
    image.add_argument("--category", required=True, choices=["character", "scene", "prop", "audio", "music", "sfx", "other"])
    image.add_argument("--role", required=True)
    image.add_argument("--manifest", required=True)
    image.add_argument("--out-dir", required=True)
    image.add_argument("--asset-path")
    image.add_argument("--prompt")
    image.add_argument("--prompt-file")
    image.add_argument("--reference-image", action="append")
    image.add_argument("--model", default="gpt-image-2-pro")
    image.add_argument("--aspect-ratio", default="9:16")
    image.add_argument("--resolution", default="1K")
    image.add_argument("--count", type=int, default=1)
    image.add_argument("--poll-seconds", type=int, default=10)
    image.add_argument("--timeout-minutes", type=int, default=20)
    image.set_defaults(func=generate_image)

    register = sub.add_parser("register-media", help="Register an existing image/audio/video file into a manifest.")
    register.add_argument("--asset-id", required=True)
    register.add_argument("--category", required=True, choices=["character", "scene", "prop", "audio", "music", "sfx", "other"])
    register.add_argument("--role", required=True)
    register.add_argument("--manifest", required=True)
    register.add_argument("--media", required=True)
    register.set_defaults(func=register_media)

    args = parser.parse_args()
    if getattr(args, "cmd", "") == "image" and not (args.prompt or args.prompt_file):
        raise SystemExit("--prompt or --prompt-file is required for image generation.")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
