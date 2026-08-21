#!/usr/bin/env python3
"""
Giggle OpenAPI per-shot runner for Qingshan repairs.

Use only when the AI Director UI cannot reliably bind or generate one shot.
The prompt and references must come from the same local asset manifest used by
the browser workflow. Never store API keys in files; use GIGGLE_API_KEY.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


BASE_URL = "https://giggle.pro/api/v1/generation"
RETRY_DELAY_SECONDS = float(os.environ.get("GIGGLE_API_RETRY_DELAY", "2"))
RETRYABLE_HTTP_CODES = {408, 409, 425, 429}


def read_json(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    return json.loads(Path(path).expanduser().read_text(encoding="utf-8"))


def media_payload(path: Path) -> Dict[str, str]:
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"base64": data}


def image_payload(path: Path) -> Dict[str, str]:
    return media_payload(path)


AudioReference = Union[Path, str, Dict[str, str]]


def audio_payload(ref: AudioReference) -> Dict[str, str]:
    if isinstance(ref, dict):
        payload = {key: value for key, value in ref.items() if key in {"asset_id", "url"} and value}
        if payload:
            return payload
        if ref.get("path"):
            return media_payload(Path(ref["path"]).expanduser().resolve())
        raise ValueError(f"Unsupported audio reference: {ref}")
    if isinstance(ref, Path):
        return media_payload(ref)
    if ref.startswith(("http://", "https://")):
        return {"url": ref}
    path = Path(ref).expanduser()
    if path.exists():
        return media_payload(path.resolve())
    return {"asset_id": ref}


def request_json(method: str, url: str, api_key: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "x-auth": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://giggle.pro",
            "Referer": "https://giggle.pro/",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        },
    )
    last_error = ""
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            last_error = f"HTTP {exc.code}: {detail}"
            retryable = exc.code in RETRYABLE_HTTP_CODES or exc.code >= 500 or "error code: 1010" in detail.lower()
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = f"NETWORK: {exc}"
            retryable = True
        if attempt == 0 and retryable:
            time.sleep(RETRY_DELAY_SECONDS)
            continue
        raise RuntimeError(last_error)
    raise RuntimeError(last_error)


def submit(
    api_key: str,
    prompt: str,
    images: List[Path],
    audios: List[AudioReference],
    model: str,
    duration: int,
    ratio: str,
    resolution: str,
    *,
    transaction_intent: dict[str, Any] | None = None,
) -> Dict[str, Any]:
    if not transaction_intent or transaction_intent.get("state") != "INTENT_RECORDED":
        raise SystemExit("paid video submission blocked before network: durable transaction intent is required")
    if transaction_intent.get("model") != model:
        raise SystemExit("paid video submission blocked: transaction model mismatch")
    if len(images) > 9:
        raise SystemExit("omni-video supports at most 9 reference images.")
    payload = {
        "prompt": prompt,
        "model": model,
        "duration": duration,
        "aspect_ratio": ratio,
        "resolution": resolution,
        "generating_count": 1,
        "images": [image_payload(path) for path in images],
    }
    if audios:
        payload["audios"] = [audio_payload(ref) for ref in audios]
    return request_json("POST", f"{BASE_URL}/omni-video", api_key, payload)


def query(api_key: str, task_id: str) -> Dict[str, Any]:
    quoted = urllib.parse.quote(task_id)
    return request_json("GET", f"{BASE_URL}/task/query?task_id={quoted}", api_key)


def download(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=180) as resp:
        out_path.write_bytes(resp.read())


def main() -> int:
    parser = argparse.ArgumentParser(description="Submit and poll one Giggle omni-video shot.")
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--image", action="append", default=[], help="Reference image path. Repeat up to 9 times.")
    parser.add_argument("--audio", action="append", default=[], help="Reference audio path for voice/ambience/music. Repeat as needed.")
    parser.add_argument("--audio-asset-id", action="append", default=[], help="Giggle audio asset_id. Repeat as needed.")
    parser.add_argument("--audio-url", action="append", default=[], help="Public audio URL. Repeat as needed.")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--model", default="seedance-2.0-fast")
    parser.add_argument("--duration", type=int, default=4)
    parser.add_argument("--ratio", default="9:16")
    parser.add_argument("--resolution", default="720p")
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--timeout-minutes", type=int, default=30)
    parser.add_argument("--api-key-env", default="GIGGLE_API_KEY")
    parser.add_argument(
        "--transaction-intent",
        required=True,
        help="Durable JSON transaction already persisted with state=INTENT_RECORDED",
    )
    args = parser.parse_args()

    if args.model != "seedance-2.0-fast":
        raise SystemExit(
            "paid video submission blocked: E40+ requires seedance-2.0-fast; "
            "Pro, Mini, bare seedance-2.0, and unknown models are forbidden"
        )

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        raise SystemExit(f"Missing API key env var: {args.api_key_env}")

    prompt = Path(args.prompt_file).expanduser().read_text(encoding="utf-8")
    transaction_path = Path(args.transaction_intent).expanduser().resolve()
    if not transaction_path.is_file():
        raise SystemExit(f"Missing durable transaction intent: {transaction_path}")
    transaction = read_json(str(transaction_path))
    if transaction.get("state") != "INTENT_RECORDED":
        raise SystemExit("Durable transaction must be persisted in INTENT_RECORDED state before POST")
    if transaction.get("model") != args.model:
        raise SystemExit("Durable transaction model does not match submit model")
    prompt_sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    if transaction.get("prompt_sha256") != prompt_sha:
        raise SystemExit("Durable transaction prompt SHA does not match prompt file")
    images = [Path(item).expanduser().resolve() for item in args.image]
    for path in images:
        if not path.exists():
            raise SystemExit(f"Missing reference image: {path}")
    audios: List[AudioReference] = [Path(item).expanduser().resolve() for item in args.audio]
    for path in audios:
        if isinstance(path, Path) and not path.exists():
            raise SystemExit(f"Missing reference audio: {path}")
    audios.extend({"asset_id": item} for item in args.audio_asset_id)
    audios.extend({"url": item} for item in args.audio_url)
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    submit_response = submit(
        api_key,
        prompt,
        images,
        audios,
        args.model,
        args.duration,
        args.ratio,
        args.resolution,
        transaction_intent=transaction,
    )
    (out_dir / "submit_response.json").write_text(json.dumps(submit_response, ensure_ascii=False, indent=2), encoding="utf-8")
    task_id = (submit_response.get("data") or {}).get("task_id")
    if not task_id:
        raise SystemExit("Submit response did not contain data.task_id.")

    deadline = time.time() + args.timeout_minutes * 60
    while time.time() < deadline:
        response = query(api_key, task_id)
        (out_dir / "last_query_response.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
        data = response.get("data") or {}
        status = data.get("status")
        if status == "completed":
            urls = data.get("urls") or []
            if not urls:
                raise SystemExit("Completed task returned no urls.")
            for idx, url in enumerate(urls, 1):
                download(url, out_dir / f"result_{idx:02d}.mp4")
            print(json.dumps({"task_id": task_id, "status": status, "urls": urls}, ensure_ascii=False, indent=2))
            return 0
        if status in {"failed", "error", "canceled", "cancelled"}:
            raise SystemExit(json.dumps(response, ensure_ascii=False, indent=2))
        time.sleep(args.poll_seconds)

    raise SystemExit(f"Timed out waiting for task {task_id}. Last query response saved in {out_dir}.")


if __name__ == "__main__":
    raise SystemExit(main())
