#!/usr/bin/env python3
"""Minimal Giggle OpenAPI client for shot-level short-drama repair.

This tool intentionally reads the API key only from GIGGLE_API_KEY. Do not
hardcode keys in workflow files, prompts, task cards, or portable bundles.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

try:
    from upload_giggle_asset import upload as upload_giggle_asset
except ModuleNotFoundError:  # Imported as tools.giggle_api_client.
    from tools.upload_giggle_asset import upload as upload_giggle_asset


BASE_URL = os.environ.get("GIGGLE_API_BASE", "https://giggle.pro")
RETRY_DELAY_SECONDS = float(os.environ.get("GIGGLE_API_RETRY_DELAY", "2"))
HTTP_TIMEOUT_SECONDS = float(os.environ.get("GIGGLE_API_HTTP_TIMEOUT_SECONDS", "30"))
GENERATION_POST_TIMEOUT_SECONDS = float(os.environ.get("GIGGLE_GENERATION_POST_TIMEOUT_SECONDS", "180"))
RETRYABLE_HTTP_CODES = {408, 409, 425, 429}
PRODUCTION_VIDEO_MODEL = "seedance-2.0-pro"
STANDARD_VIDEO_MODEL = PRODUCTION_VIDEO_MODEL
MINIMAX_H3_VIDEO_MODEL = "MiniMax-H3"
AUTHORIZED_VIDEO_MODELS = {PRODUCTION_VIDEO_MODEL, MINIMAX_H3_VIDEO_MODEL}
VIDEO_GENERATION_ENDPOINTS = {
    "/api/v1/generation/text-to-video",
    "/api/v1/generation/image-to-video",
    "/api/v1/generation/omni-video",
}


def _api_key() -> str:
    key = os.environ.get("GIGGLE_API_KEY", "").strip()
    if not key:
        raise SystemExit("GIGGLE_API_KEY is not set")
    return key


def _headers() -> Dict[str, str]:
    key = _api_key()
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "x-auth": key,
    }


def _retryable_http(code: int, raw: str) -> bool:
    return code in RETRYABLE_HTTP_CODES or code >= 500 or "error code: 1010" in raw.lower()


def _urlopen_json(
    req: urllib.request.Request, *, allow_retry: bool = True, timeout_seconds: float | None = None
) -> Dict[str, Any]:
    last_error = ""
    attempts = 2 if allow_retry else 1
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds or HTTP_TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            last_error = f"HTTP {exc.code}: {raw}"
            retryable = _retryable_http(exc.code, raw)
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = f"NETWORK: {exc}"
            retryable = True
        if allow_retry and attempt == 0 and retryable:
            print(f"Giggle interface failure; retrying once after {RETRY_DELAY_SECONDS:g}s", file=sys.stderr)
            time.sleep(RETRY_DELAY_SECONDS)
            continue
        raise SystemExit(last_error)
    raise SystemExit(last_error)


def _request(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if path in VIDEO_GENERATION_ENDPOINTS and payload.get("model") not in AUTHORIZED_VIDEO_MODELS:
        raise SystemExit(
            "paid video submission blocked: model must be seedance-2.0-pro "
            "or MiniMax-H3; Fast, Mini, the bare seedance-2.0 SKU, and unknown models are forbidden"
        )
    if path.startswith("/api/v1/generation/") and os.environ.get("QINGSHAN_DURABLE_SUBMITTER_CONTEXT") != "1":
        raise SystemExit(
            "paid generation blocked before network: durable transaction context is required"
        )
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=body,
        headers=_headers(),
        method="POST",
    )
    # Generation POSTs can be charged even when the response is lost. Fail
    # closed on ambiguous errors so callers query/reconcile before resubmitting.
    return _urlopen_json(
        req,
        allow_retry=False,
        timeout_seconds=GENERATION_POST_TIMEOUT_SECONDS,
    )


def _get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{BASE_URL}{path}?{query}",
        headers=_headers(),
        method="GET",
    )
    return _urlopen_json(req, allow_retry=True)


def _b64(path: str) -> str:
    p = Path(path).expanduser()
    data = p.read_bytes()
    return base64.b64encode(data).decode("ascii")


def _image_list(paths: List[str]) -> List[Dict[str, str]]:
    return [{"base64": _b64(p)} for p in paths]


def _registered_asset(path: str) -> Dict[str, str]:
    """Register audio/video files because omni-video rejects their base64 form."""
    source = Path(path).expanduser().resolve()
    response = upload_giggle_asset(source, True)
    data = response.get("data") or response
    asset_id = data.get("asset_id")
    if not asset_id:
        raise RuntimeError(f"Giggle asset registration returned no asset_id for {source}: {response}")
    return {"asset_id": str(asset_id)}


def generate_image(args: argparse.Namespace) -> Dict[str, Any]:
    reference_images = _image_list(args.reference_image or [])
    payload: Dict[str, Any] = {
        "prompt": args.prompt,
        "generate_count": args.count,
        "model": args.model,
        "aspect_ratio": args.aspect_ratio,
        "resolution": args.resolution,
        "watermark": False,
    }
    endpoint = "/api/v1/generation/text-to-image"
    if reference_images:
        endpoint = "/api/v1/generation/image-to-image"
        payload["reference_images"] = reference_images
    return _request(endpoint, payload)


def generate_video(args: argparse.Namespace) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "prompt": args.prompt,
        "model": args.model,
        "duration": args.duration,
        "aspect_ratio": args.aspect_ratio,
        "resolution": args.resolution,
        "generating_count": args.count,
    }
    if args.start_frame:
        payload["start_frame"] = {"base64": _b64(args.start_frame)}
    if args.end_frame:
        payload["end_frame"] = {"base64": _b64(args.end_frame)}
    return _request("/api/v1/generation/image-to-video", payload)


def generate_omni_video(args: argparse.Namespace) -> Dict[str, Any]:
    prompt = args.prompt
    if args.prompt_file:
        prompt = Path(args.prompt_file).expanduser().read_text(encoding="utf-8")
    payload: Dict[str, Any] = {
        "prompt": prompt,
        "model": args.model,
        "duration": args.duration,
        "aspect_ratio": args.aspect_ratio,
        "resolution": args.resolution,
        "generating_count": args.count,
        "images": _image_list(args.reference_image or []),
    }
    if args.image_url:
        payload["images"].extend({"url": item} for item in args.image_url)
    if args.image_asset_id:
        payload["images"].extend({"asset_id": item} for item in args.image_asset_id)
    if args.audio:
        payload["audios"] = [_registered_asset(p) for p in args.audio]
    if args.audio_asset_id:
        payload.setdefault("audios", [])
        payload["audios"].extend({"asset_id": item} for item in args.audio_asset_id)
    if args.video:
        payload["videos"] = [_registered_asset(p) for p in args.video]
    if args.video_asset_id:
        payload.setdefault("videos", [])
        payload["videos"].extend({"asset_id": item} for item in args.video_asset_id)
    return _request("/api/v1/generation/omni-video", payload)


def query_task(args: argparse.Namespace) -> Dict[str, Any]:
    return _get("/api/v1/generation/task/query", {"task_id": args.task_id})


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    img = sub.add_parser("image")
    img.add_argument("--prompt", required=True)
    img.add_argument("--reference-image", action="append")
    img.add_argument("--model", default="gpt-image-2-pro")
    img.add_argument("--aspect-ratio", default="9:16")
    img.add_argument("--resolution", default="1K")
    img.add_argument("--count", type=int, default=1)
    img.set_defaults(func=generate_image)

    vid = sub.add_parser("image-to-video")
    vid.add_argument("--prompt", required=True)
    vid.add_argument("--start-frame")
    vid.add_argument("--end-frame")
    vid.add_argument("--model", default=PRODUCTION_VIDEO_MODEL)
    vid.add_argument("--duration", type=int, default=4)
    vid.add_argument("--aspect-ratio", default="9:16")
    vid.add_argument("--resolution", default="720p")
    vid.add_argument("--count", type=int, default=1)
    vid.set_defaults(func=generate_video)

    omni = sub.add_parser("omni-video")
    omni.add_argument("--prompt", default="")
    omni.add_argument("--prompt-file")
    omni.add_argument("--reference-image", action="append")
    omni.add_argument("--image-url", action="append")
    omni.add_argument("--image-asset-id", action="append")
    omni.add_argument("--audio", action="append")
    omni.add_argument("--audio-asset-id", action="append")
    omni.add_argument("--video", action="append")
    omni.add_argument("--video-asset-id", action="append")
    omni.add_argument("--model", default=PRODUCTION_VIDEO_MODEL)
    omni.add_argument("--duration", type=int, default=4)
    omni.add_argument("--aspect-ratio", default="9:16")
    omni.add_argument("--resolution", default="720p")
    omni.add_argument("--count", type=int, default=1)
    omni.add_argument("--out")
    omni.set_defaults(func=generate_omni_video)

    query = sub.add_parser("query")
    query.add_argument("--task-id", required=True)
    query.set_defaults(func=query_task)

    args = parser.parse_args()
    if args.cmd != "query" and os.environ.get("QINGSHAN_DURABLE_SUBMITTER_CONTEXT") != "1":
        raise SystemExit(
            "direct paid generation CLI is disabled: use a durable transaction submitter "
            "(submit_giggle_image_manifest.py or deployed submit_giggle_video_manifest_v2.py)"
        )
    result = args.func(args)
    if getattr(args, "out", None):
        output = Path(args.out).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
