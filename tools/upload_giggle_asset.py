#!/usr/bin/env python3
"""Upload a local media file to Giggle's asset service and register it.

Reads the API key from GIGGLE_API_KEY only. The resulting asset metadata can be
merged into local manifests and reused by shot-level generation plans.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict


# The web client resolves its relative /asset endpoints against /api/v1.
# The previous helper omitted this prefix and therefore sent every request to
# https://giggle.pro/asset/... where Giggle correctly returned 404.
BASE_URL = os.environ.get("GIGGLE_WEB_BASE", "https://giggle.pro/api/v1").rstrip("/")


def api_key() -> str:
    key = os.environ.get("GIGGLE_API_KEY", "").strip()
    if not key:
        raise SystemExit("Missing GIGGLE_API_KEY")
    return key


def json_request(path: str, payload: Dict[str, Any], auth_mode: str = "raw") -> Dict[str, Any]:
    headers = {
        "Content-Type": "application/json",
        "Origin": "https://giggle.pro",
        "Referer": "https://giggle.pro/",
        "User-Agent": "qingshan-giggle-asset-upload/1.0",
        "x-auth": api_key() if auth_mode == "raw" else f"Bearer {api_key()}",
    }
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw}") from exc


def put_file(url: str, path: Path, content_type: str) -> None:
    req = urllib.request.Request(
        url,
        data=path.read_bytes(),
        headers={
            "Content-Type": content_type,
            "User-Agent": "qingshan-giggle-asset-upload/1.0",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"PUT failed: HTTP {resp.status}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"PUT failed: HTTP {exc.code}: {raw}") from exc


def upload(path: Path, is_public: bool) -> Dict[str, Any]:
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    # The public OpenAPI uses the raw x-auth key. Keep this as one transaction:
    # a failed upload must be reported rather than silently retried.
    auth_mode = "raw"
    presign = json_request(
        "/asset/get-presigned-url",
        {"file_name": path.name, "content_type": content_type, "is_public": is_public},
        auth_mode=auth_mode,
    )
    presign_data = presign.get("data") or presign
    object_key = presign_data.get("object_key")
    signed_url = presign_data.get("signed_url")
    if not object_key or not signed_url:
        raise RuntimeError(f"missing presign fields: {presign}")
    put_file(signed_url, path, content_type)
    registered = json_request(
        "/asset/register",
        {"object_key": object_key, "name": path.name},
        auth_mode=auth_mode,
    )
    registered["_upload_auth_mode"] = auth_mode
    registered["_content_type"] = content_type
    return registered


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload/register a Giggle asset.")
    parser.add_argument("--file", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--public", action="store_true")
    args = parser.parse_args()

    path = Path(args.file).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"File not found: {path}")
    result = upload(path, args.public)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
