#!/usr/bin/env python3
"""HopsAPI router transport for MiniMax-H3 video (owner decision 2026-10-29).

MiniMax-H3 video generation moves from Giggle's omni-video endpoint to the HopsAPI router
(https://github.com/giggle-official/skills/tree/main/skills/hopsapi-minimax-h3).  Images, TTS and
BGM stay on Giggle.  This module is the only place that talks to HopsAPI; the durable submitter
(``submit_giggle_video_manifest_v2.py``) keeps every guard (intent-before-POST, fingerprint store,
live-binding idempotency, prompt-scope gate, whole-batch QA, reservation) and only swaps the
transport, and the poller (``poll_giggle_submit_report.py``) dispatches HopsAPI task ids here.

Provider switch
---------------
``video_provider`` = ``hopsapi`` | ``giggle``: env ``NALU_VIDEO_PROVIDER`` wins, then
``generation.video_provider`` in the runtime ``qingshan.json`` (``QINGSHAN_CONFIG`` or
``$NALU_RUNTIME_ROOT/qingshan.json``), else ``hopsapi`` when ``HOPSAPI_API_KEY`` is set and
``giggle`` otherwise.  Only MiniMax-H3 tasks ever take the HopsAPI route; ``giggle`` is the
rollback switch and keeps the old path byte-for-byte.

Facts from the paid probe (2026-10-29, ~/Desktop/nalu_lab_preview/hopsapi_probe/PROBE.md)
------------------------------------------------------------------------------------
* POST {base}/router/task/create {task:"OmniVideo", model:"MiniMax-H3", input:{prompt, images[],
  audios[], duration (int 4-15), resolution:"768p", aspect_ratio:"9:16", generate_audio:true}}
  -> top-level ``task_id`` (``tsk_…``).  No idempotency key exists: a lost response is never resent.
* GET {base}/router/tasks/{id} -> integer status 0 queued, 1 processing, 2 success (settled,
  ``cost``), 3 failed (not charged), 4 cancelled (not charged); a failure may come back as HTTP 200
  with ``code: 424``.  Video URL in ``results[0].urls[0]`` or ``result.content.video_url``.
* Uploads: POST {console}/api/file-stream-upload (multipart ``file``, ``uploadPath``, ``fileName``)
  -> ``data.fileUrl``.  The part MUST carry an explicit MIME type (else it is stored as text/plain
  and served without Range).  URLs expire 24 h after upload, so references are uploaded at submit
  time and never cached across runs.
* ``cost`` is in the same credits as Giggle (100 credits = 1 USD): 6.23 for a 4 s 768p ref-image
  task (list 8.9/s x 4 x account multiplier 0.175).  The planning estimate is configurable and
  rounded up.

The API key is read from ``HOPSAPI_API_KEY`` only, sent as a Bearer header, and never printed,
logged or written to any artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, Callable

PROVIDER_HOPSAPI = "hopsapi"
PROVIDER_GIGGLE = "giggle"
PROVIDERS = (PROVIDER_HOPSAPI, PROVIDER_GIGGLE)
PROVIDER_ENV = "NALU_VIDEO_PROVIDER"
API_KEY_ENV = "HOPSAPI_API_KEY"
GIGGLE_KEY_ENV = "GIGGLE_API_KEY"
DEFAULT_BASE_URL = "https://hopsapi.com/v1"
DEFAULT_CONSOLE_URL = "https://hopsapi.com"
H3_MODEL = "MiniMax-H3"
H3_MODELS = {"minimax-h3", "h3"}
OMNI_TASK = "OmniVideo"
MIN_DURATION_SECONDS = 4
MAX_DURATION_SECONDS = 15
RESOLUTIONS = {"480p", "768p"}
MAX_IMAGES = 9
MAX_AUDIOS = 3
FREE_REFERENCE_IMAGES = 5
#: Planning price for H3 768p ref-image mode in credits per output second: probe 6.23 / 4 s
#: (= list 8.9/s x account multiplier 0.175).  Override: env HOPSAPI_H3_CREDITS_PER_SECOND or
#: qingshan.json generation.hopsapi_h3_credits_per_second.
DEFAULT_H3_CREDITS_PER_SECOND = Decimal("1.56")
#: 6th+ reference image: list 1.8/output-second x 0.175, rounded up.
DEFAULT_H3_EXTRA_IMAGE_CREDITS_PER_SECOND = Decimal("0.32")
HTTP_TIMEOUT_SECONDS = float(os.environ.get("HOPSAPI_HTTP_TIMEOUT_SECONDS", "60"))
CREATE_TIMEOUT_SECONDS = float(os.environ.get("HOPSAPI_CREATE_TIMEOUT_SECONDS", "120"))
UPLOAD_ATTEMPTS = 3
QUERY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = float(os.environ.get("HOPSAPI_RETRY_DELAY_SECONDS", "2"))
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36")
STATUS_NAMES = {0: "queued", 1: "processing", 2: "completed", 3: "failed", 4: "cancelled"}
TERMINAL_FAILED = {"failed", "cancelled"}
INSUFFICIENT_TERMS = ("insufficient", "余额不足", "积分不足", "额度不足", "not enough credit")
MIME_BY_SUFFIX = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac",
    ".mp4": "video/mp4", ".mov": "video/quicktime",
}
EXT_BY_MIME = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "audio/wav": "wav",
               "audio/mpeg": "mp3", "audio/mp4": "m4a", "audio/aac": "aac", "video/mp4": "mp4",
               "video/quicktime": "mov"}


class HopsapiError(RuntimeError):
    """Any HopsAPI transport failure."""


class HopsapiNotCharged(HopsapiError):
    """The create request provably created no task: never sent, or explicitly declined (4xx / code!=200
    with no task_id).  The attempt is VERIFIED_ZERO_RETRYABLE."""

    def __init__(self, message: str, *, response: Any = None, http_status: int | None = None,
                 insufficient_credits: bool = False) -> None:
        super().__init__(message)
        self.response = response
        self.http_status = http_status
        self.insufficient_credits = insufficient_credits


class HopsapiResponseLost(HopsapiError):
    """The create request may have reached HopsAPI and no task id came back (timeout, reset, 5xx).
    There is no idempotency key, so this is never resent automatically."""


class HopsapiHTTPError(HopsapiError):
    def __init__(self, status: int, body: Any, raw: str) -> None:
        super().__init__(f"HTTP {status}: {raw[:500]}")
        self.status = status
        self.body = body
        self.raw = raw


class HopsapiNotSent(HopsapiError):
    """The request never left this host (DNS failure / connection refused)."""


# --------------------------------------------------------------------------- #
# provider switch and planning price
# --------------------------------------------------------------------------- #
def _config_path(config_path: str | Path | None = None, environ: dict[str, str] | None = None) -> Path | None:
    env = os.environ if environ is None else environ
    if config_path:
        return Path(config_path)
    if env.get("QINGSHAN_CONFIG"):
        return Path(env["QINGSHAN_CONFIG"])
    if env.get("NALU_RUNTIME_ROOT"):
        return Path(env["NALU_RUNTIME_ROOT"]) / "qingshan.json"
    return None


def _generation_config(config_path: str | Path | None = None,
                       environ: dict[str, str] | None = None) -> dict[str, Any]:
    path = _config_path(config_path, environ)
    if path is None or not path.is_file():
        return {}
    try:
        return dict((json.loads(path.read_text(encoding="utf-8")) or {}).get("generation") or {})
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def resolve_video_provider(config_path: str | Path | None = None,
                           environ: dict[str, str] | None = None) -> dict[str, str]:
    """{provider, source}.  env NALU_VIDEO_PROVIDER > qingshan.json generation.video_provider >
    hopsapi when HOPSAPI_API_KEY is set, else giggle.  An unknown explicit value fails closed."""
    env = os.environ if environ is None else environ
    explicit = str(env.get(PROVIDER_ENV) or "").strip().lower()
    if explicit:
        if explicit not in PROVIDERS:
            raise ValueError(f"{PROVIDER_ENV}={explicit!r} is not one of {PROVIDERS}")
        return {"provider": explicit, "source": f"ENV:{PROVIDER_ENV}"}
    configured = str(_generation_config(config_path, env).get("video_provider") or "").strip().lower()
    if configured:
        if configured not in PROVIDERS:
            raise ValueError(f"qingshan.json generation.video_provider={configured!r} is not one of {PROVIDERS}")
        return {"provider": configured, "source": "QINGSHAN_JSON:generation.video_provider"}
    if str(env.get(API_KEY_ENV) or "").strip():
        return {"provider": PROVIDER_HOPSAPI, "source": f"DEFAULT:{API_KEY_ENV}_PRESENT"}
    return {"provider": PROVIDER_GIGGLE, "source": f"DEFAULT:{API_KEY_ENV}_ABSENT"}


def video_provider(config_path: str | Path | None = None, environ: dict[str, str] | None = None) -> str:
    return resolve_video_provider(config_path, environ)["provider"]


def is_h3(model: Any) -> bool:
    return str(model or "").strip().lower() in H3_MODELS


def provider_for_model(model: Any, provider: str | None = None) -> str:
    """The transport a task of ``model`` takes: HopsAPI only serves MiniMax-H3."""
    chosen = provider or video_provider()
    return PROVIDER_HOPSAPI if chosen == PROVIDER_HOPSAPI and is_h3(model) else PROVIDER_GIGGLE


def task_uses_hopsapi(task: dict[str, Any], provider: str | None = None) -> bool:
    return provider_for_model(task.get("model"), provider) == PROVIDER_HOPSAPI


def required_key_env(provider: str) -> str:
    return API_KEY_ENV if provider == PROVIDER_HOPSAPI else GIGGLE_KEY_ENV


def _decimal_setting(env_name: str, config_key: str, default: Decimal,
                     config_path: str | Path | None = None, environ: dict[str, str] | None = None) -> Decimal:
    env = os.environ if environ is None else environ
    for raw in (env.get(env_name), _generation_config(config_path, env).get(config_key)):
        if raw in (None, ""):
            continue
        try:
            value = Decimal(str(raw))
        except Exception:  # noqa: BLE001 - a malformed override falls back to the conservative default
            continue
        if value > 0:
            return value
    return default


def h3_credits_per_second(config_path: str | Path | None = None, environ: dict[str, str] | None = None) -> Decimal:
    return _decimal_setting("HOPSAPI_H3_CREDITS_PER_SECOND", "hopsapi_h3_credits_per_second",
                            DEFAULT_H3_CREDITS_PER_SECOND, config_path, environ)


def h3_extra_image_credits_per_second(config_path: str | Path | None = None,
                                      environ: dict[str, str] | None = None) -> Decimal:
    return _decimal_setting("HOPSAPI_H3_EXTRA_IMAGE_CREDITS_PER_SECOND",
                            "hopsapi_h3_extra_image_credits_per_second",
                            DEFAULT_H3_EXTRA_IMAGE_CREDITS_PER_SECOND, config_path, environ)


def _ceil(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def estimated_task_credits(seconds: float, image_count: int = 0, *, config_path: str | Path | None = None,
                           environ: dict[str, str] | None = None) -> int:
    """Conservative (rounded-up) credits one HopsAPI H3 768p task may cost."""
    seconds_d = Decimal(str(max(float(seconds or 0), float(MIN_DURATION_SECONDS))))
    total = seconds_d * h3_credits_per_second(config_path, environ)
    extra = max(0, int(image_count or 0) - FREE_REFERENCE_IMAGES)
    total += Decimal(extra) * seconds_d * h3_extra_image_credits_per_second(config_path, environ)
    return _ceil(total)


def estimated_batch_credits(total_seconds: float, tasks: int, *, config_path: str | Path | None = None,
                            environ: dict[str, str] | None = None) -> int:
    """Planning price for ``tasks`` tasks totalling ``total_seconds``: rounded up, plus one credit of
    rounding headroom per task so it never undercuts the sum of per-task estimates."""
    floor_seconds = max(float(total_seconds or 0), float(MIN_DURATION_SECONDS * max(0, int(tasks or 0))))
    return _ceil(Decimal(str(floor_seconds)) * h3_credits_per_second(config_path, environ)) + max(0, int(tasks or 0))


# --------------------------------------------------------------------------- #
# HTTP (the one place requests leave this host; tests mock _http)
# --------------------------------------------------------------------------- #
def base_url() -> str:
    return (os.environ.get("HOPSAPI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")


def console_url() -> str:
    return (os.environ.get("HOPSAPI_CONSOLE_URL") or DEFAULT_CONSOLE_URL).rstrip("/")


def _api_key() -> str:
    key = str(os.environ.get(API_KEY_ENV) or "").strip()
    if not key:
        raise SystemExit(f"{API_KEY_ENV} is not set")
    return key


def _auth_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {_api_key()}", "Accept": "application/json", "User-Agent": USER_AGENT}
    headers.update(extra or {})
    return headers


def _not_sent(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", exc)
    return isinstance(reason, (socket.gaierror, ConnectionRefusedError))


def _http(method: str, url: str, *, body: bytes | None = None, headers: dict[str, str] | None = None,
          timeout: float = HTTP_TIMEOUT_SECONDS) -> tuple[int, Any, str]:
    """(status, parsed JSON or None, raw text).  HTTP errors raise HopsapiHTTPError with the body;
    a request that never left the host raises HopsapiNotSent; other transport failures propagate."""
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            parsed = json.loads(raw)
        except ValueError:
            parsed = None
        raise HopsapiHTTPError(int(exc.code), parsed, raw) from None
    except (urllib.error.URLError, OSError) as exc:
        if _not_sent(exc):
            raise HopsapiNotSent(f"NOT_SENT: {type(exc).__name__}") from None
        raise
    try:
        parsed = json.loads(raw) if raw.strip() else None
    except ValueError:
        parsed = None
    return status, parsed, raw


def _download_bytes(url: str, timeout: float = 240) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


# --------------------------------------------------------------------------- #
# uploads (free; always before the intent record)
# --------------------------------------------------------------------------- #
def sniff_mime(data: bytes, name: str = "") -> str:
    """MIME type from the bytes (preferred) or the file name; unknown fails closed."""
    head = bytes(data[:16])
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "audio/wav"
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return "audio/mpeg"
    suffix = Path(str(name).split("?", 1)[0]).suffix.lower()
    if suffix in MIME_BY_SUFFIX:
        return MIME_BY_SUFFIX[suffix]
    raise HopsapiError(f"UNKNOWN_MIME_TYPE:{Path(str(name)).name or 'bytes'}")


def _multipart(fields: dict[str, str], *, file_field: str, file_name: str, data: bytes,
               mime: str) -> tuple[bytes, str]:
    boundary = f"----qingshan{uuid.uuid4().hex}"
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n"
                      f"{value}\r\n").encode("utf-8"))
    parts.append((f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
                  f"filename=\"{file_name}\"\r\nContent-Type: {mime}\r\n\r\n").encode("utf-8"))
    parts.append(data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def upload_bytes(data: bytes, *, file_name: str, upload_path: str, mime: str) -> dict[str, Any]:
    """Upload one reference with an explicit MIME type; returns {url, mime_type, sha256, bytes, expires_at}.

    Free, so transient failures (network, 5xx, 429) are retried.  A stored MIME type different from the
    one sent is a failure: a text/plain asset is served without Range (probe 2026-10-29)."""
    if not mime or "/" not in mime:
        raise HopsapiError("UPLOAD_REQUIRES_EXPLICIT_MIME_TYPE")
    body, content_type = _multipart({"uploadPath": upload_path, "fileName": file_name},
                                    file_field="file", file_name=file_name, data=data, mime=mime)
    url = f"{console_url()}/api/file-stream-upload"
    last = ""
    for attempt in range(UPLOAD_ATTEMPTS):
        try:
            _status, parsed, raw = _http("POST", url, body=body,
                                         headers=_auth_headers({"Content-Type": content_type}),
                                         timeout=HTTP_TIMEOUT_SECONDS)
        except HopsapiHTTPError as exc:
            last = str(exc)
            if exc.status >= 500 or exc.status in (408, 425, 429):
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            raise HopsapiError(f"UPLOAD_REJECTED:{last}") from None
        except (HopsapiNotSent, urllib.error.URLError, OSError) as exc:
            last = f"NETWORK:{type(exc).__name__}"
            time.sleep(RETRY_DELAY_SECONDS)
            continue
        payload = parsed if isinstance(parsed, dict) else {}
        info = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        file_url = str(info.get("fileUrl") or info.get("downloadUrl") or "")
        if not file_url.startswith("https://"):
            raise HopsapiError(f"UPLOAD_RETURNED_NO_FILE_URL:{raw[:300]}")
        stored = str(info.get("mimeType") or "").split(";", 1)[0].strip().lower()
        if stored and stored != mime.lower():
            raise HopsapiError(f"UPLOAD_MIME_NOT_PRESERVED:{stored}!={mime}")
        return {"url": file_url, "mime_type": stored or mime, "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data), "expires_at": info.get("expiresAt"), "file_name": file_name,
                "upload_path": upload_path}
    raise HopsapiError(f"UPLOAD_FAILED_AFTER_{UPLOAD_ATTEMPTS}_ATTEMPTS:{last}")


# --------------------------------------------------------------------------- #
# create / query
# --------------------------------------------------------------------------- #
def build_omni_request(*, prompt: str, image_urls: list[str], audio_urls: list[str], duration: int,
                       resolution: str, aspect_ratio: str = "9:16", model: str = H3_MODEL,
                       generate_audio: bool = True) -> dict[str, Any]:
    if not is_h3(model):
        raise ValueError(f"HopsAPI route serves MiniMax-H3 only, got {model!r}")
    if int(duration) != duration or not MIN_DURATION_SECONDS <= int(duration) <= MAX_DURATION_SECONDS:
        raise ValueError(f"HOPSAPI_H3_DURATION_OUT_OF_RANGE:{duration} (integer {MIN_DURATION_SECONDS}-"
                         f"{MAX_DURATION_SECONDS} s)")
    if str(resolution).lower() not in RESOLUTIONS:
        raise ValueError(f"HOPSAPI_H3_RESOLUTION_UNSUPPORTED:{resolution}")
    if len(image_urls) > MAX_IMAGES:
        raise ValueError(f"HOPSAPI_OMNI_TOO_MANY_IMAGES:{len(image_urls)}>{MAX_IMAGES}")
    if len(audio_urls) > MAX_AUDIOS:
        raise ValueError(f"HOPSAPI_OMNI_TOO_MANY_AUDIOS:{len(audio_urls)}>{MAX_AUDIOS}")
    if not image_urls and not audio_urls:
        raise ValueError("HOPSAPI_OMNI_REQUIRES_A_REFERENCE")
    data: dict[str, Any] = {"prompt": prompt, "images": list(image_urls)}
    if audio_urls:
        data["audios"] = list(audio_urls)
    data.update({"duration": int(duration), "resolution": str(resolution).lower(),
                 "aspect_ratio": aspect_ratio, "generate_audio": bool(generate_audio)})
    return {"task": OMNI_TASK, "model": H3_MODEL, "input": data}


def _paid_context_active() -> bool:
    """True inside giggle_api_client.paid_video_submission_context() (the durable submitter) or a step
    the orchestrator launched as paid.  The client may be loaded flat or as tools.*; check both."""
    if os.environ.get("QINGSHAN_DURABLE_SUBMITTER_CONTEXT") == "1":
        return True
    for name in ("tools.giggle_api_client", "giggle_api_client"):
        module = sys.modules.get(name)
        depth = getattr(module, "_PAID_VIDEO_SUBMISSION_CONTEXT_DEPTH", None) if module else None
        if depth is not None and depth.get() > 0:
            return True
    return False


def _insufficient(text: str) -> bool:
    lowered = text.lower()
    return any(term in lowered for term in INSUFFICIENT_TERMS)


def create_task(payload: dict[str, Any]) -> dict[str, Any]:
    """ONE POST, never retried (no server-side idempotency).  Returns the parsed response with a
    task id; raises HopsapiNotCharged (provably no task) or HopsapiResponseLost (maybe charged)."""
    if not _paid_context_active():
        raise SystemExit("paid HopsAPI video transport blocked before network: invoke the durable video "
                         "submitter; a direct POST cannot bypass the transaction and prompt-lineage gates")
    if not is_h3(payload.get("model")) or payload.get("task") != OMNI_TASK:
        raise SystemExit("paid HopsAPI submission blocked: only OmniVideo / MiniMax-H3 is authorised")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = f"{base_url()}/router/task/create"
    try:
        status, parsed, raw = _http("POST", url, body=body,
                                    headers=_auth_headers({"Content-Type": "application/json"}),
                                    timeout=CREATE_TIMEOUT_SECONDS)
    except HopsapiNotSent as exc:
        raise HopsapiNotCharged(f"NETWORK: {exc}") from None
    except HopsapiHTTPError as exc:
        task_id = (exc.body or {}).get("task_id") if isinstance(exc.body, dict) else None
        if task_id:  # a task exists whatever the status line said: bind it
            return {**exc.body, "http_status": exc.status}
        if 400 <= exc.status < 500 and exc.status not in (408, 425, 429):
            raise HopsapiNotCharged(f"HTTP {exc.status}: {exc.raw[:500]}", response=exc.body,
                                    http_status=exc.status,
                                    insufficient_credits=exc.status == 402 or _insufficient(exc.raw)) from None
        raise HopsapiResponseLost(f"HTTP {exc.status}: {exc.raw[:500]}") from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise HopsapiResponseLost(f"NETWORK: {type(exc).__name__}: {exc}") from None
    response = parsed if isinstance(parsed, dict) else {"raw": raw[:2000]}
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    task_id = response.get("task_id") or data.get("task_id")
    if task_id:
        return {**response, "task_id": str(task_id), "http_status": status}
    code = response.get("code")
    if isinstance(code, int) and code != 200:
        # an explicit application-level refusal with no task id: nothing was created
        raise HopsapiNotCharged(f"code {code}: {raw[:500]}", response=response, http_status=status,
                                insufficient_credits=code == 402 or _insufficient(raw))
    raise HopsapiResponseLost(f"response missing task_id: {raw[:500]}")


def result_urls(body: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for row in body.get("results") or []:
        if isinstance(row, dict):
            urls.extend(str(u) for u in row.get("urls") or [] if u)
            if row.get("url"):
                urls.append(str(row["url"]))
    content = ((body.get("result") or {}).get("content") or {}) if isinstance(body.get("result"), dict) else {}
    if not urls and content.get("video_url"):
        urls.append(str(content["video_url"]))
    return urls


def normalize_task(body: Any, http_status: int = 200) -> dict[str, Any]:
    """Map a /router/tasks/{id} body to the poller's vocabulary (remote_status completed/failed/...)."""
    body = body if isinstance(body, dict) else {}
    data = body.get("data") if isinstance(body.get("data"), dict) and "status" not in body else body
    code = body.get("code")
    raw_status = data.get("status")
    try:
        status_code = int(raw_status) if raw_status is not None and str(raw_status).strip() != "" else None
    except (TypeError, ValueError):
        status_code = None
    if http_status == 424 or code == 424:
        remote = "cancelled" if status_code == 4 else "failed"
        status_code = status_code if status_code in (3, 4) else 3
    elif status_code in STATUS_NAMES:
        remote = STATUS_NAMES[status_code]
    else:
        remote = "unknown"
    cost = data.get("cost")
    cost_value = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None
    if remote in TERMINAL_FAILED:
        cost_value = 0.0  # status 3/4 are not charged (gateway billing rule)
    return {"task_id": data.get("task_id") or body.get("task_id"), "status_code": status_code,
            "remote_status": remote, "urls": result_urls(data) if remote == "completed" else [],
            "cost": cost_value, "provider_code": code,
            "error": ((data.get("error") or data.get("message") or body.get("message"))
                      if remote in TERMINAL_FAILED else None)}


def query_task(task_id: str) -> dict[str, Any]:
    """GET the task (free; transient failures retried)."""
    url = f"{base_url()}/router/tasks/{task_id}"
    last = ""
    for _attempt in range(QUERY_ATTEMPTS):
        try:
            status, parsed, raw = _http("GET", url, headers=_auth_headers(), timeout=HTTP_TIMEOUT_SECONDS)
            return normalize_task(parsed, status)
        except HopsapiHTTPError as exc:
            if exc.status == 424:
                return normalize_task(exc.body if isinstance(exc.body, dict) else {}, 424)
            last = str(exc)
            if exc.status >= 500 or exc.status in (408, 425, 429):
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            raise
        except (HopsapiNotSent, urllib.error.URLError, OSError) as exc:
            last = f"NETWORK:{type(exc).__name__}"
            time.sleep(RETRY_DELAY_SECONDS)
    raise HopsapiError(f"QUERY_FAILED_AFTER_{QUERY_ATTEMPTS}_ATTEMPTS:{last}")


# --------------------------------------------------------------------------- #
# download + verify, settlement record
# --------------------------------------------------------------------------- #
def _ffprobe_has_video(path: Path) -> bool | None:
    """True/False when ffprobe is available, None when it is not (the byte check still applies)."""
    if os.environ.get("HOPSAPI_VERIFY_FFPROBE", "1") == "0" or not shutil.which("ffprobe"):
        return None
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=codec_type", "-of", "csv=p=0", str(path)],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0 and "video" in out.stdout


def verify_video_bytes(data: bytes) -> None:
    if len(data) < 1024 or data[4:8] != b"ftyp":
        raise HopsapiError(f"DOWNLOADED_FILE_IS_NOT_AN_MP4:{len(data)}B")


def download_video(url: str, destination: Path, fetch: Callable[[str], bytes] | None = None) -> dict[str, Any]:
    """Atomic .part -> replace, verified as an MP4 (and by ffprobe when present) before it lands."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = (fetch or _download_bytes)(url)
    verify_video_bytes(data)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(data)
    probe = _ffprobe_has_video(temporary)
    if probe is False:
        temporary.unlink(missing_ok=True)
        raise HopsapiError("DOWNLOADED_FILE_HAS_NO_VIDEO_STREAM")
    temporary.replace(destination)
    return {"path": str(destination), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "ffprobe_verified": bool(probe)}


def record_settlement(transaction: Path, task_id: str, status: dict[str, Any], *, now: str) -> dict[str, Any] | None:
    """Write the provider's settlement onto the durable transaction (under its flock).  The budget
    ledger reads ``provider_cost_credits`` from here (nalu_budget_ledger.scan_hopsapi_video_spend).
    Only the transaction bound to this exact task id is touched; a terminal failure records 0 credits
    and ``remote_terminal_state`` (tools/video_live_binding treats it as not live)."""
    import fcntl  # noqa: PLC0415
    transaction = Path(transaction)
    if not transaction.is_file():
        return None
    with transaction.with_suffix(".lock").open("a") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        row = json.loads(transaction.read_text(encoding="utf-8"))
        if str(row.get("task_id") or "") != str(task_id):
            return None
        remote = status.get("remote_status")
        row["provider"] = row.get("provider") or PROVIDER_HOPSAPI
        row["provider_remote_status"] = remote
        row["provider_status_observed_at"] = now
        if remote == "completed" and status.get("cost") is not None:
            row["provider_cost_credits"] = float(status["cost"])
            row["provider_cost_recorded_at"] = now
            row["provider_cost_unit"] = "credits (HopsAPI cost; 100 credits = 1 USD, same unit as Giggle)"
        elif remote in TERMINAL_FAILED:
            row["provider_cost_credits"] = 0.0
            row["provider_cost_recorded_at"] = now
            row.setdefault("remote_terminal_state", remote)
            row.setdefault("remote_terminal_observed_at", now)
            if status.get("error"):
                row["provider_failure"] = str(status["error"])[:500]
        else:
            return row
        temporary = transaction.with_suffix(transaction.suffix + ".part")
        temporary.write_text(json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(transaction)
        return row


def is_hopsapi_task_id(task_id: Any) -> bool:
    return str(task_id or "").startswith("tsk_")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HopsAPI video provider helper (no network for these commands).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("resolve-provider", help="print hopsapi|giggle (env > qingshan.json > key presence)")
    est = sub.add_parser("estimate", help="planning credits for H3 768p via HopsAPI")
    est.add_argument("--seconds", type=float, required=True)
    est.add_argument("--tasks", type=int, default=1)
    args = parser.parse_args(argv)
    if args.cmd == "resolve-provider":
        print(video_provider())
        return 0
    print(json.dumps({"planned_credits": estimated_batch_credits(args.seconds, args.tasks),
                      "credits_per_second": str(h3_credits_per_second())}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
