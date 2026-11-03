#!/usr/bin/env python3
"""HopsAPI router transport for gpt-image-2 images (owner decision 2026-10-30).

Every image the line generates (character plates / headshots / busts / multi-view sheets, prop and
location cards, space-map-driven keyframes and start frames, keyframe redos) moves from Giggle
``gpt-image-2-pro`` (11 credits/image) to HopsAPI ``gpt-image-2``.  TTS and BGM stay on Giggle; video
already uses HopsAPI (``tools/hopsapi_video_client.py``, whose HTTP / upload / query / settlement
helpers this module reuses — there is still exactly one HTTP implementation).

The durable submitters keep every guard (intent-before-POST, fingerprint store, harvested-binding
reuse, reviewed-request digest, whole-batch prompt gate) and only swap the transport:
``tools/submit_giggle_character_asset_plan.py`` (S3) and ``tools/submit_giggle_image_manifest.py``
(S5 keyframes, start frames and redos).  ``tools/harvest_giggle_image_batch.py`` dispatches HopsAPI
task ids here, downloads to the exact file name the Giggle harvest uses and writes the settled
``cost`` onto the transaction.  The submission fingerprint is the logical request (task, prompt,
reference shas, logical model, aspect, resolution) and does NOT include the provider, so switching
provider never re-POSTs a bound task.

Provider switch
---------------
``image_provider`` = ``hopsapi`` | ``giggle``: env ``NALU_IMAGE_PROVIDER`` wins, then
``generation.image_provider`` in the runtime ``qingshan.json``, else ``hopsapi`` when
``HOPSAPI_API_KEY`` is set and ``giggle`` otherwise (the Giggle path stays as the rollback).

Facts from the paid probe (2026-10-30, ~/Desktop/nalu_lab_preview/hopsapi_image_probe/)
-------------------------------------------------------------------------------------
* POST {base}/router/task/create {task:"Txt2Img"|"Img2Img", model:"gpt-image-2", input:{prompt,
  images:[<=16 public HTTPS URLs from file-stream-upload with an explicit MIME], resolution:"WxH",
  quality:"high", output_format:"png"}}; ``input.aspect_ratio`` is NOT supported.
* GET {base}/router/tasks/{id}: status 0/1/2/3/4, ``results[0].urls[0]``, ``cost`` in credits
  (100 = 1 USD, same unit as Giggle).  Keyframe E09-S02-04 at high: 0.97 credits, 66 s, identity
  0.725 (Giggle 0.68).  Txt2Img low: 0.13.
* A 16000x2200 reference (the E09 global space-map panorama) makes the provider fail every task
  with 424 "Provider error"; shrinking it to a 2048 px long side fixed it.  Hence the reference
  preprocessing rule below.

Reference preprocessing (before upload; the files on disk are never changed)
---------------------------------------------------------------------------
A reference whose long side > 4096 px, or whose aspect ratio > 3:1, or whose file is > 20 MB is
resized (Lanczos) to a 2048 px long side (aspect kept) and re-encoded PNG (JPEG q90 if the PNG is
still > 20 MB).  Every reference's original and sent sha256 / size / dims are recorded on the
transaction.  Other references are uploaded byte-for-byte.

The API key is read from ``HOPSAPI_API_KEY`` only and never printed, logged or written anywhere.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import struct
import sys
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, Callable

try:
    import hopsapi_video_client as hops
except ModuleNotFoundError:  # imported as tools.hopsapi_image_client
    from tools import hopsapi_video_client as hops

PROVIDER_HOPSAPI = hops.PROVIDER_HOPSAPI
PROVIDER_GIGGLE = hops.PROVIDER_GIGGLE
PROVIDERS = hops.PROVIDERS
PROVIDER_ENV = "NALU_IMAGE_PROVIDER"
API_KEY_ENV = hops.API_KEY_ENV
GIGGLE_KEY_ENV = hops.GIGGLE_KEY_ENV
MODEL = "gpt-image-2"
#: the engine's logical image model (manifests, fingerprints, digests keep naming it): the image
#: registry's active SKU (tools/image_model_policy.py; gpt-image-2-fast @1K since seq=54/56).  Both
#: 1K and 2K tiers map to the probe-verified HopsAPI pixel size below.
try:
    from tools.image_model_policy import ACTIVE_IMAGE_MODEL as LOGICAL_MODEL
except ModuleNotFoundError:  # pragma: no cover - flat tools/ on sys.path
    from image_model_policy import ACTIVE_IMAGE_MODEL as LOGICAL_MODEL  # type: ignore[no-redef]
TXT2IMG = "Txt2Img"
IMG2IMG = "Img2Img"
MAX_IMAGES = 16
QUALITIES = ("low", "medium", "high", "auto")
DEFAULT_QUALITY = "high"
OUTPUT_FORMAT = "png"
#: planning price per image (high quality, with references): probe 0.97, rounded up with headroom.
#: Override: env HOPSAPI_IMAGE_CREDITS_PER_IMAGE or qingshan.json generation.hopsapi_image_credits_per_image.
DEFAULT_CREDITS_PER_IMAGE = Decimal("1.2")

# provider size limits (gpt-image-2): edges multiple of 16, max edge 3840, long:short <= 3:1,
# total pixels 655,360 .. 8,294,400 (= 3840x2160)
SIZE_MULTIPLE = 16
MAX_EDGE = 3840
MAX_RATIO = 3.0
MIN_PIXELS = 655_360
MAX_PIXELS = 8_294_400
#: engine aspect -> provider pixel size (long side 2048).  9:16 1152x2048 is probe-verified.
SIZE_BY_ASPECT = {
    "9:16": "1152x2048",
    "16:9": "2048x1152",
    "2:3": "1024x1536",
    "3:2": "1536x1024",
    "3:4": "1536x2048",
    "4:3": "2048x1536",
    "4:5": "1632x2048",
    "5:4": "2048x1632",
    "1:1": "2048x2048",
}

# reference preprocessing rule (see module docstring)
REF_MAX_LONG_SIDE = 4096
REF_MAX_ASPECT = 3.0
REF_MAX_BYTES = 20 * 1024 * 1024
REF_TARGET_LONG_SIDE = 2048
REF_JPEG_QUALITY = 90


class ImageTransportError(hops.HopsapiError):
    """A pre-intent HopsAPI image failure (nothing was POSTed, nothing was charged)."""


# --------------------------------------------------------------------------- #
# provider switch, quality, planning price
# --------------------------------------------------------------------------- #
def resolve_image_provider(config_path: str | Path | None = None,
                           environ: dict[str, str] | None = None) -> dict[str, str]:
    """{provider, source}.  env NALU_IMAGE_PROVIDER > qingshan.json generation.image_provider >
    hopsapi when HOPSAPI_API_KEY is set, else giggle.  An unknown explicit value fails closed."""
    env = os.environ if environ is None else environ
    explicit = str(env.get(PROVIDER_ENV) or "").strip().lower()
    if explicit:
        if explicit not in PROVIDERS:
            raise ValueError(f"{PROVIDER_ENV}={explicit!r} is not one of {PROVIDERS}")
        return {"provider": explicit, "source": f"ENV:{PROVIDER_ENV}"}
    configured = str(hops._generation_config(config_path, env).get("image_provider") or "").strip().lower()
    if configured:
        if configured not in PROVIDERS:
            raise ValueError(f"qingshan.json generation.image_provider={configured!r} is not one of {PROVIDERS}")
        return {"provider": configured, "source": "QINGSHAN_JSON:generation.image_provider"}
    if str(env.get(API_KEY_ENV) or "").strip():
        return {"provider": PROVIDER_HOPSAPI, "source": f"DEFAULT:{API_KEY_ENV}_PRESENT"}
    return {"provider": PROVIDER_GIGGLE, "source": f"DEFAULT:{API_KEY_ENV}_ABSENT"}


def image_provider(config_path: str | Path | None = None, environ: dict[str, str] | None = None) -> str:
    return resolve_image_provider(config_path, environ)["provider"]


def required_key_env(provider: str) -> str:
    return API_KEY_ENV if provider == PROVIDER_HOPSAPI else GIGGLE_KEY_ENV


def image_quality(config_path: str | Path | None = None, environ: dict[str, str] | None = None) -> str:
    """env HOPSAPI_IMAGE_QUALITY > qingshan.json generation.hopsapi_image_quality > high."""
    env = os.environ if environ is None else environ
    for raw in (env.get("HOPSAPI_IMAGE_QUALITY"), hops._generation_config(config_path, env).get("hopsapi_image_quality")):
        value = str(raw or "").strip().lower()
        if value:
            if value not in QUALITIES:
                raise ValueError(f"HopsAPI image quality {value!r} is not one of {QUALITIES}")
            return value
    return DEFAULT_QUALITY


def credits_per_image(config_path: str | Path | None = None, environ: dict[str, str] | None = None) -> Decimal:
    return hops._decimal_setting("HOPSAPI_IMAGE_CREDITS_PER_IMAGE", "hopsapi_image_credits_per_image",
                                 DEFAULT_CREDITS_PER_IMAGE, config_path, environ)


def estimated_task_credits(*, config_path: str | Path | None = None,
                           environ: dict[str, str] | None = None) -> float:
    """Planning exposure of ONE image task (the configured rate, unrounded; the ledger sums these)."""
    return float(credits_per_image(config_path, environ))


def estimated_batch_credits(images: int, *, config_path: str | Path | None = None,
                            environ: dict[str, str] | None = None) -> int:
    """Planning price for ``images`` image tasks: images x rate, rounded up (E09: 45 x 1.2 = 54)."""
    count = max(0, int(images or 0))
    if not count:
        return 0
    total = Decimal(count) * credits_per_image(config_path, environ)
    return int(total.to_integral_value(rounding=ROUND_CEILING))


# --------------------------------------------------------------------------- #
# size mapping
# --------------------------------------------------------------------------- #
def valid_size(width: int, height: int) -> list[str]:
    """Reasons a WxH is not a valid gpt-image-2 size (empty = valid)."""
    problems: list[str] = []
    if width % SIZE_MULTIPLE or height % SIZE_MULTIPLE:
        problems.append("EDGE_NOT_MULTIPLE_OF_16")
    if max(width, height) > MAX_EDGE:
        problems.append("EDGE_ABOVE_3840")
    if max(width, height) > MAX_RATIO * min(width, height):
        problems.append("ASPECT_ABOVE_3_TO_1")
    if not MIN_PIXELS <= width * height <= MAX_PIXELS:
        problems.append("PIXELS_OUT_OF_RANGE")
    return problems


def map_resolution(aspect_ratio: Any = "9:16", resolution: Any = None) -> str:
    """The provider pixel size for the engine's requested aspect (and size hint).

    An explicit valid ``WxH`` hint is passed through; the engine's ``1K``/``2K`` tiers map to the
    long-side-2048 size of the aspect (9:16 -> 1152x2048, probe-verified).  Unknown aspects are
    derived (long side 2048, short side rounded to 16) and validated."""
    hint = str(resolution or "").strip().lower()
    match = re.fullmatch(r"(\d+)\s*x\s*(\d+)", hint)
    if match:
        width, height = int(match.group(1)), int(match.group(2))
        problems = valid_size(width, height)
        if problems:
            raise ValueError(f"HOPSAPI_IMAGE_SIZE_INVALID:{width}x{height}:{','.join(problems)}")
        return f"{width}x{height}"
    aspect = str(aspect_ratio or "9:16").strip()
    if aspect in SIZE_BY_ASPECT:
        return SIZE_BY_ASPECT[aspect]
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", aspect)
    if not match:
        raise ValueError(f"HOPSAPI_IMAGE_ASPECT_UNPARSEABLE:{aspect}")
    a, b = float(match.group(1)), float(match.group(2))
    if a <= 0 or b <= 0:
        raise ValueError(f"HOPSAPI_IMAGE_ASPECT_UNPARSEABLE:{aspect}")
    long_side = 2048
    short = max(SIZE_MULTIPLE, int(round(long_side * min(a, b) / max(a, b) / SIZE_MULTIPLE)) * SIZE_MULTIPLE)
    width, height = (long_side, short) if a >= b else (short, long_side)
    problems = valid_size(width, height)
    if problems:
        raise ValueError(f"HOPSAPI_IMAGE_ASPECT_UNSUPPORTED:{aspect}:{','.join(problems)}")
    return f"{width}x{height}"


# --------------------------------------------------------------------------- #
# reference preprocessing
# --------------------------------------------------------------------------- #
def image_dimensions(data: bytes) -> tuple[int, int] | None:
    """(width, height) from PNG / JPEG / WEBP headers without Pillow (None when unknown)."""
    head = bytes(data[:32])
    if head.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        chunk = head[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            return (1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little"))
        if chunk == b"VP8 " and len(data) >= 30:
            return (struct.unpack("<H", data[26:28])[0] & 0x3FFF, struct.unpack("<H", data[28:30])[0] & 0x3FFF)
        if chunk == b"VP8L" and len(data) >= 25:
            bits = int.from_bytes(data[21:25], "little")
            return ((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)
        return None
    if head.startswith(b"\xff\xd8"):
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                index += 2
                continue
            length = struct.unpack(">H", data[index + 2:index + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(">HH", data[index + 5:index + 9])
                return width, height
            index += 2 + length
    return None


def preprocessing_reasons(size: tuple[int, int] | None, byte_count: int) -> list[str]:
    reasons: list[str] = []
    if size:
        width, height = size
        if max(width, height) > REF_MAX_LONG_SIDE:
            reasons.append(f"LONG_SIDE_ABOVE_{REF_MAX_LONG_SIDE}")
        if min(width, height) > 0 and max(width, height) > REF_MAX_ASPECT * min(width, height):
            reasons.append("ASPECT_ABOVE_3_TO_1")
    if byte_count > REF_MAX_BYTES:
        reasons.append("FILE_ABOVE_20MB")
    return reasons


def preprocess_reference(data: bytes, name: str = "") -> tuple[bytes, str, dict[str, Any]]:
    """(bytes to upload, MIME, note).  Applies the reference rule; never touches the source file."""
    original_mime = hops.sniff_mime(data, name)
    size = image_dimensions(data)
    note: dict[str, Any] = {
        "source": Path(str(name)).name, "original_sha256": hashlib.sha256(data).hexdigest(),
        "original_bytes": len(data), "original_size": list(size) if size else None,
        "original_mime": original_mime,
    }
    reasons = preprocessing_reasons(size, len(data))
    if size is None and len(data) <= REF_MAX_BYTES:
        try:  # an unknown header: ask Pillow when it is there; otherwise send as is
            from PIL import Image  # noqa: PLC0415
            with Image.open(io.BytesIO(data)) as probe:
                size = probe.size
            note["original_size"] = list(size)
            reasons = preprocessing_reasons(size, len(data))
        except Exception:  # noqa: BLE001
            pass
    if not reasons:
        note.update({"preprocessed": False, "sent_sha256": note["original_sha256"], "sent_bytes": len(data),
                     "sent_size": note["original_size"], "sent_mime": original_mime})
        return data, original_mime, note
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        raise ImageTransportError(f"REFERENCE_PREPROCESS_REQUIRES_PILLOW:{note['source']}:{','.join(reasons)}") from None
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        width, height = image.size
        scale = REF_TARGET_LONG_SIDE / max(width, height)
        target = (max(1, round(width * scale)), max(1, round(height * scale)))
        work = image
        if work.mode not in ("RGB", "RGBA", "L", "LA"):
            work = work.convert("RGBA" if "A" in work.mode or "transparency" in work.info else "RGB")
        resized = work.resize(target, Image.LANCZOS)
    buffer = io.BytesIO()
    resized.save(buffer, format="PNG", optimize=True)
    out, mime = buffer.getvalue(), "image/png"
    if len(out) > REF_MAX_BYTES:
        buffer = io.BytesIO()
        resized.convert("RGB").save(buffer, format="JPEG", quality=REF_JPEG_QUALITY, optimize=True)
        out, mime = buffer.getvalue(), "image/jpeg"
    note.update({"preprocessed": True, "reasons": reasons, "resample": "LANCZOS",
                 "sent_sha256": hashlib.sha256(out).hexdigest(), "sent_bytes": len(out),
                 "sent_size": list(target), "sent_mime": mime})
    return out, mime, note


def select_references(paths: list[Any], limit: int = MAX_IMAGES) -> tuple[list[Any], list[dict[str, Any]]]:
    """Keep the engine's priority order; drop the lowest-priority extras beyond ``limit`` (recorded)."""
    items = list(paths or [])
    kept, dropped = items[:limit], items[limit:]
    notes = [{"index": limit + offset + 1, "reference": str(value),
              "reason": f"HOPSAPI_IMG2IMG_MAX_{limit}_REFERENCES_LOWEST_PRIORITY_DROPPED"}
             for offset, value in enumerate(dropped)]
    return kept, notes


# --------------------------------------------------------------------------- #
# request
# --------------------------------------------------------------------------- #
def build_image_request(*, prompt: str, image_urls: list[str], resolution: str,
                        quality: str = DEFAULT_QUALITY, output_format: str = OUTPUT_FORMAT) -> dict[str, Any]:
    """Txt2Img with no references, Img2Img with 1..16.  No ``aspect_ratio`` (not supported)."""
    if not str(prompt or "").strip():
        raise ValueError("HOPSAPI_IMAGE_PROMPT_EMPTY")
    if len(image_urls) > MAX_IMAGES:
        raise ValueError(f"HOPSAPI_IMG2IMG_TOO_MANY_IMAGES:{len(image_urls)}>{MAX_IMAGES}")
    match = re.fullmatch(r"(\d+)x(\d+)", str(resolution))
    if not match or valid_size(int(match.group(1)), int(match.group(2))):
        raise ValueError(f"HOPSAPI_IMAGE_SIZE_INVALID:{resolution}")
    if quality not in QUALITIES:
        raise ValueError(f"HOPSAPI_IMAGE_QUALITY_INVALID:{quality}")
    data: dict[str, Any] = {"prompt": prompt}
    if image_urls:
        data["images"] = list(image_urls)
    data.update({"resolution": str(resolution), "quality": quality, "output_format": output_format})
    return {"task": IMG2IMG if image_urls else TXT2IMG, "model": MODEL, "input": data}


def prepare_request(*, prompt: str, reference_paths: list[Any], aspect_ratio: Any = "9:16",
                    resolution: Any = None, task_key: str = "image", quality: str | None = None,
                    read: Callable[[Any], bytes] | None = None) -> dict[str, Any]:
    """Free, pre-intent: select (<=16), preprocess and upload every reference, map the size and build
    the create payload.  Returns {payload, uploads, reference_notes, dropped_references, resolution,
    quality}.  Any failure here means nothing was POSTed and nothing was charged."""
    size = map_resolution(aspect_ratio, resolution)
    chosen_quality = quality or image_quality()
    kept, dropped = select_references(reference_paths)
    key = re.sub(r"[^A-Za-z0-9._-]+", "-", str(task_key)).strip("-.") or "image"
    reader = read or (lambda value: Path(value).read_bytes())
    uploads: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    for index, value in enumerate(kept, 1):
        data, mime, note = preprocess_reference(reader(value), str(value))
        note["index"] = index
        notes.append(note)
        uploads.append(hops.upload_bytes(data, file_name=f"{key}-ref{index}.{hops.EXT_BY_MIME[mime]}",
                                         upload_path="images", mime=mime))
    payload = build_image_request(prompt=prompt, image_urls=[row["url"] for row in uploads],
                                  resolution=size, quality=chosen_quality)
    return {"payload": payload, "uploads": uploads, "reference_notes": notes,
            "dropped_references": dropped, "resolution": size, "quality": chosen_quality}


def intent_fields(prepared: dict[str, Any], *, estimated_credits: float | None = None) -> dict[str, Any]:
    """The provider block every HopsAPI image transaction carries (no secrets, no prompt text)."""
    payload = prepared["payload"]
    uploads = prepared["uploads"]
    return {
        "provider": PROVIDER_HOPSAPI, "provider_endpoint": "POST /router/task/create",
        "hopsapi_key_fingerprint": hops.key_fingerprint(),
        "provider_task": payload["task"], "provider_model": MODEL,
        "provider_resolution": prepared["resolution"], "provider_quality": prepared["quality"],
        "estimated_credits": estimated_task_credits() if estimated_credits is None else estimated_credits,
        "sent_reference_sha256": [row["sha256"] for row in uploads],
        "sent_reference_mime_types": [row["mime_type"] for row in uploads],
        "uploaded_reference_urls": [row["url"] for row in uploads],
        "upload_expires_at": [row.get("expires_at") for row in uploads],
        "reference_preprocessing": prepared["reference_notes"],
        "dropped_references": prepared["dropped_references"],
        "provider_request_sha256": hashlib.sha256(json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        "provider_request_input": {k: v for k, v in payload["input"].items() if k != "prompt"},
    }


def _paid_context_active() -> bool:
    """True inside a durable submitter (env flag, giggle_api_client.durable_generation_context or the
    paid video context).  The client may be loaded flat or as tools.*; check both."""
    if os.environ.get("QINGSHAN_DURABLE_SUBMITTER_CONTEXT") == "1":
        return True
    for name in ("tools.giggle_api_client", "giggle_api_client"):
        module = sys.modules.get(name)
        if module is None:
            continue
        durable = getattr(module, "_DURABLE_GENERATION_CONTEXT", None)
        if durable is not None and durable.get():
            return True
        depth = getattr(module, "_PAID_VIDEO_SUBMISSION_CONTEXT_DEPTH", None)
        if depth is not None and depth.get() > 0:
            return True
    return False


def create_image_task(payload: dict[str, Any]) -> dict[str, Any]:
    """ONE create POST, never retried (no idempotency key).  Raises HopsapiNotCharged (provably no
    task) or HopsapiResponseLost (maybe charged; never resent automatically)."""
    if not _paid_context_active():
        raise SystemExit("paid HopsAPI image transport blocked before network: invoke a durable image "
                         "submitter; a direct POST cannot bypass the transaction and prompt gates")
    if payload.get("model") != MODEL or payload.get("task") not in (TXT2IMG, IMG2IMG):
        raise SystemExit("paid HopsAPI image submission blocked: only Txt2Img / Img2Img gpt-image-2 is authorised")
    if payload["task"] == IMG2IMG and not (payload.get("input") or {}).get("images"):
        raise SystemExit("paid HopsAPI image submission blocked: Img2Img without references")
    return hops.post_create(payload)


# --------------------------------------------------------------------------- #
# query / download / settlement
# --------------------------------------------------------------------------- #
query_task = hops.query_task
record_settlement = hops.record_settlement
is_hopsapi_task_id = hops.is_hopsapi_task_id


def verify_image_bytes(data: bytes) -> str:
    if len(data) < 1024:
        raise hops.HopsapiError(f"DOWNLOADED_FILE_TOO_SMALL_FOR_AN_IMAGE:{len(data)}B")
    try:
        mime = hops.sniff_mime(data, "")
    except hops.HopsapiError:
        raise hops.HopsapiError("DOWNLOADED_FILE_IS_NOT_AN_IMAGE") from None
    if not mime.startswith("image/"):
        raise hops.HopsapiError(f"DOWNLOADED_FILE_IS_NOT_AN_IMAGE:{mime}")
    return mime


def download_image(url: str, destination: Path, fetch: Callable[[str], bytes] | None = None) -> dict[str, Any]:
    """Download, verify (magic bytes; Pillow decode when available) and land atomically.  A non-PNG
    body bound for a ``.png`` name is converted to PNG with Pillow (refused without it)."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = (fetch or hops._download_bytes)(url)
    mime = verify_image_bytes(data)
    size = image_dimensions(data)
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        Image = None  # type: ignore[assignment]
    if Image is not None:
        try:
            with Image.open(io.BytesIO(data)) as probe:
                probe.verify()
            with Image.open(io.BytesIO(data)) as image:
                size = image.size
                if destination.suffix.lower() == ".png" and mime != "image/png":
                    buffer = io.BytesIO()
                    image.save(buffer, format="PNG")
                    data, mime = buffer.getvalue(), "image/png"
        except Exception as exc:  # noqa: BLE001
            raise hops.HopsapiError(f"DOWNLOADED_IMAGE_UNDECODABLE:{type(exc).__name__}") from None
    elif destination.suffix.lower() == ".png" and mime != "image/png":
        raise hops.HopsapiError(f"DOWNLOADED_IMAGE_NOT_PNG_AND_PILLOW_UNAVAILABLE:{mime}")
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_bytes(data)
    temporary.replace(destination)
    return {"path": str(destination), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "mime_type": mime, "size": list(size) if size else None}


def terminal_failed_binding(transaction: dict[str, Any]) -> bool:
    """A bound HopsAPI image task that settled as failed/cancelled (not charged, no image)."""
    return (str(transaction.get("provider") or "").lower() == PROVIDER_HOPSAPI
            and transaction.get("state") == "SUBMITTED_TASK_ID_BOUND"
            and str(transaction.get("remote_terminal_state") or transaction.get("provider_remote_status") or "").lower()
            in hops.TERMINAL_FAILED
            and not transaction.get("provider_cost_credits"))


# --------------------------------------------------------------------------- #
# provider-side 424 outages (lab E10/E11, 2026-10-30/31)
# --------------------------------------------------------------------------- #
#: A HopsAPI image task that settles status 3 with ``code: 424`` "Provider error (request id: aitk-…)"
#: at zero cost is the upstream gpt-image-2 channel refusing, not our request: E10's 27 keyframes failed
#: twice (21:37Z, 21:54Z) and then 21/27 of the byte-identical requests (same prompt sha, same reference
#: shas) completed at 22:12Z; E11 7/27 completed, 20 failed twice; at 07:4xZ on 2026-10-31 a
#: previously-completed E11 request, the failed ones and a reference-free Txt2Img "red apple" probe all
#: failed the same way.  Such failures settle within seconds; a healthy task stays processing for
#: ~60 s.  So: never fire a whole batch into an outage (canary first), and refuse a new batch while
#: the store's most recent attempts are an unbroken run of these failures (cooldown).
PROVIDER_ERROR_CODE = 424
OUTAGE_MIN_FAILURES = 3
OUTAGE_COOLDOWN_SECONDS = 900
CANARY_WAIT_SECONDS = 75
CANARY_POLL_SECONDS = 5


def _int_setting(env_name: str, default: int, environ: dict[str, str] | None = None) -> int:
    env = os.environ if environ is None else environ
    try:
        return max(0, int(str(env.get(env_name) or "").strip()))
    except ValueError:
        return default


def is_provider_error_failure(status: dict[str, Any]) -> bool:
    """A settled status (query_task shape) or a transaction that is the uncharged upstream 424."""
    remote = str(status.get("remote_status") or status.get("provider_remote_status")
                 or status.get("remote_terminal_state") or "").lower()
    if remote not in hops.TERMINAL_FAILED:
        return False
    cost = status.get("cost", status.get("provider_cost_credits"))
    if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost > 0:
        return False
    code = status.get("provider_code", status.get("provider_failure_code"))
    text = str(status.get("error") or status.get("provider_failure") or "")
    return code == PROVIDER_ERROR_CODE or str(code) == str(PROVIDER_ERROR_CODE) or text.startswith("Provider error")


def _parse_utc(value: Any) -> float | None:
    from datetime import datetime  # noqa: PLC0415
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def recent_provider_outage(store_root: Path, *, now: float | None = None,
                           environ: dict[str, str] | None = None) -> dict[str, Any] | None:
    """The outage in force, or None.  Reads every HopsAPI image transaction under ``store_root``
    (all episodes, retired ``.terminal-*`` records included), orders the SETTLED attempts by intent
    time and looks at the trailing run after the last completed one: ``OUTAGE_MIN_FAILURES`` or more
    uncharged 424s whose newest settled less than the cooldown ago = outage.  Free (no network).
    Env: HOPSAPI_IMAGE_OUTAGE_COOLDOWN_SECONDS (0 disables), HOPSAPI_IMAGE_OUTAGE_MIN_FAILURES."""
    import time as _time  # noqa: PLC0415
    cooldown = _int_setting("HOPSAPI_IMAGE_OUTAGE_COOLDOWN_SECONDS", OUTAGE_COOLDOWN_SECONDS, environ)
    minimum = max(1, _int_setting("HOPSAPI_IMAGE_OUTAGE_MIN_FAILURES", OUTAGE_MIN_FAILURES, environ))
    if not cooldown:
        return None
    now = _time.time() if now is None else now
    settled: list[tuple[float, bool, float, str]] = []
    for path in Path(store_root).glob("*/*.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(row, dict) or str(row.get("provider") or "").lower() != PROVIDER_HOPSAPI:
            continue
        if row.get("provider_model") != MODEL:
            continue
        remote = str(row.get("provider_remote_status") or row.get("remote_terminal_state") or "").lower()
        if remote != "completed" and remote not in hops.TERMINAL_FAILED:
            continue
        started = _parse_utc(row.get("intent_recorded_at"))
        observed = _parse_utc(row.get("remote_terminal_observed_at") or row.get("provider_status_observed_at"))
        if started is None:
            continue
        settled.append((started, is_provider_error_failure(row), observed or started, str(row.get("task_id") or "")))
    settled.sort()
    run: list[tuple[float, bool, float, str]] = []
    for item in reversed(settled):
        if not item[1]:
            break
        run.append(item)
    if len(run) < minimum:
        return None
    last = max(item[2] for item in run)
    if now - last >= cooldown:
        return None
    from datetime import datetime, timezone  # noqa: PLC0415
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    return {"blocker": "HOPSAPI_IMAGE_PROVIDER_OUTAGE", "consecutive_provider_errors": len(run),
            "last_failure_observed_at": iso(last), "retry_after_utc": iso(last + cooldown),
            "cooldown_seconds": cooldown, "latest_task_ids": [item[3] for item in run[:5]],
            "rule": ("the most recent HopsAPI gpt-image-2 attempts are an unbroken run of uncharged 424 "
                     "'Provider error' settlements (upstream refusal, not the request): no POST until "
                     "retry_after_utc, then the next batch starts with one canary task")}


def canary_check(task_id: str, transaction: Path | None = None, *,
                 query: Callable[[str], dict[str, Any]] | None = None,
                 wait_seconds: int | None = None, poll_seconds: int = CANARY_POLL_SECONDS,
                 sleep: Callable[[float], None] | None = None,
                 clock: Callable[[], float] | None = None) -> dict[str, Any]:
    """Poll ONE freshly bound task (free GETs) before the rest of a batch is POSTed.

    PROVIDER_ERROR when it settles as the uncharged 424 (the settlement is written onto its
    transaction so the next attempt retires it); HEALTHY when it completes or is still queued /
    processing after ``wait_seconds`` (424s settle within seconds); OTHER for any other terminal
    failure or an unreadable status (the batch proceeds: that is not an outage signal)."""
    import time as _time  # noqa: PLC0415
    query = query or query_task
    sleep = sleep or _time.sleep
    clock = clock or _time.monotonic
    wait = _int_setting("HOPSAPI_IMAGE_CANARY_WAIT_SECONDS", CANARY_WAIT_SECONDS) if wait_seconds is None else wait_seconds
    deadline = clock() + wait
    status: dict[str, Any] = {}
    while True:
        try:
            status = query(task_id)
        except hops.HopsapiError as exc:
            status = {"remote_status": "unknown", "error": str(exc)[:200]}
        remote = str(status.get("remote_status") or "unknown")
        if remote == "completed":
            return {"outcome": "HEALTHY", "task_id": task_id, "remote_status": remote}
        if remote in hops.TERMINAL_FAILED:
            if transaction is not None:
                record_settlement(Path(transaction), task_id, status,
                                  now=_time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()))
            outcome = "PROVIDER_ERROR" if is_provider_error_failure(status) else "OTHER"
            return {"outcome": outcome, "task_id": task_id, "remote_status": remote,
                    "provider_code": status.get("provider_code"), "error": status.get("error")}
        if clock() >= deadline:
            return {"outcome": "HEALTHY", "task_id": task_id, "remote_status": remote,
                    "note": f"still {remote} after {wait}s (a 424 settles within seconds)"}
        sleep(poll_seconds)


def retire_terminal_failed(path: Path, transaction: dict[str, Any]) -> Path | None:
    """Move a terminal-failed (uncharged) bound HopsAPI image transaction aside so the same
    fingerprint may POST a new attempt; the retired record stays in the store for the ledger.
    Returns the retired path, or None when the transaction is not terminal-failed."""
    if not terminal_failed_binding(transaction):
        return None
    task_id = re.sub(r"[^A-Za-z0-9._-]+", "-", str(transaction.get("task_id") or "unknown"))
    retired = Path(path).with_name(f"{Path(path).stem}.terminal-{task_id}.json")
    os.replace(path, retired)
    return retired


# --------------------------------------------------------------------------- #
# Giggle-shaped adapters (giggle_api_client.generate_image / query_task callers)
# --------------------------------------------------------------------------- #
GIGGLE_STATUS = {"completed": "completed", "failed": "failed", "cancelled": "cancelled",
                 "queued": "pending", "processing": "processing", "unknown": "unknown"}


def giggle_shaped_status(status: dict[str, Any]) -> dict[str, Any]:
    return {"code": 200, "provider": PROVIDER_HOPSAPI,
            "data": {"task_id": status.get("task_id"), "status": GIGGLE_STATUS.get(status.get("remote_status"), "unknown"),
                     "urls": list(status.get("urls") or []), "cost": status.get("cost"),
                     "error": status.get("error")}}


def generate_image_compat(*, prompt: str, reference_paths: list[Any], aspect_ratio: Any, resolution: Any,
                          task_key: str = "image") -> dict[str, Any]:
    """One image through HopsAPI for a caller written against Giggle's response shape
    ({data:{task_id}}).  The caller still owns its own transaction record."""
    prepared = prepare_request(prompt=prompt, reference_paths=reference_paths, aspect_ratio=aspect_ratio,
                               resolution=resolution, task_key=task_key)
    response = create_image_task(prepared["payload"])
    return {"code": 200, "provider": PROVIDER_HOPSAPI, "data": {"task_id": str(response["task_id"])},
            "hopsapi_request": intent_fields(prepared)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="HopsAPI image provider helper (no network for these commands).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("resolve-provider", help="print hopsapi|giggle (env > qingshan.json > key presence)")
    est = sub.add_parser("estimate", help="planning credits for N gpt-image-2 images via HopsAPI")
    est.add_argument("--images", type=int, required=True)
    size = sub.add_parser("size", help="provider pixel size for an engine aspect")
    size.add_argument("--aspect-ratio", default="9:16")
    size.add_argument("--resolution", default=None)
    args = parser.parse_args(argv)
    if args.cmd == "resolve-provider":
        print(image_provider())
        return 0
    if args.cmd == "size":
        print(map_resolution(args.aspect_ratio, args.resolution))
        return 0
    print(json.dumps({"planned_credits": estimated_batch_credits(args.images),
                      "credits_per_image": str(credits_per_image()), "quality": image_quality()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
