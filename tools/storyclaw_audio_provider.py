#!/usr/bin/env python3
"""Durable, dependency-free Giggle speech and BGM provider for StoryClaw.

The command surface intentionally mirrors AgentCut's ``speech-generate`` and
``bgm-generate`` commands.  Provider POSTs are possible only with ``--paid``
and an absolute, caller-selected transaction path.  The transaction is locked
and persisted before the POST so an ambiguous response can never trigger a
blind retry.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from giggle_api_client import _get, _request, durable_generation_context
except ModuleNotFoundError:  # Imported as tools.storyclaw_audio_provider.
    from tools.giggle_api_client import _get, _request, durable_generation_context


SCHEMA = "qingshan.storyclaw_audio_transaction.v1"
IMPLEMENTATION = "qingshan.storyclaw_giggle_audio.v1"
SPEECH_CAPABILITY = "AGENTCUT-SPEECH-001"
BGM_CAPABILITY = "AGENTCUT-BGM-001"
CAPABILITY_VERSION = "1.0"
SPEECH_ENDPOINT = "/api/v1/generation/text-to-audio"
BGM_ENDPOINT = "/api/v1/generation/generate-music"
QUERY_ENDPOINT = "/api/v1/generation/task/query"
VOICES_ENDPOINT = "/api/v1/project/preset_tones"
TERMINAL_FAILURES = {"failed", "error", "canceled", "cancelled"}


class AudioProviderError(RuntimeError):
    """Fail-closed portable audio provider error."""


class DuplicateSubmissionBlocked(AudioProviderError):
    """A transaction already consumed its one allowed provider POST."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _absolute_transaction(value: str | Path) -> Path:
    supplied = Path(value).expanduser()
    if not supplied.is_absolute():
        raise AudioProviderError("--transaction must be an absolute path")
    if supplied.is_symlink():
        raise AudioProviderError("--transaction must not be a symlink")
    path = supplied.resolve(strict=False)
    if path.suffix.lower() != ".json":
        raise AudioProviderError("--transaction must name a .json file")
    return path


@contextmanager
def _transaction_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    if lock.is_symlink():
        raise AudioProviderError("transaction lock must not be a symlink")
    with lock.open("a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def _read_transaction(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AudioProviderError(f"invalid transaction file: {path}") from exc
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise AudioProviderError(f"unsupported transaction schema: {path}")
    return value


def _safe_request_summary(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind == "speech":
        return {
            "text_sha256": _sha256_bytes(payload["text"].encode("utf-8")),
            "voice_id": payload["voice_id"],
            "emotion": payload["emotion"],
            "speed": payload["speed"],
        }
    return {
        "prompt_sha256": _sha256_bytes(payload["prompt"].encode("utf-8")),
        "instrumental": True,
    }


def _paid_authority_from_env() -> dict[str, str]:
    """Require StoryClaw's config lock plus the exact line-owner order binding."""
    values = {
        "config_lock": str(os.environ.get("NALU_PAID_CONFIG_LOCK") or "").strip(),
        "authorization_ref": str(
            os.environ.get("NALU_PAID_AUTHORIZATION_REF") or ""
        ).strip(),
        "order_seq": str(os.environ.get("NALU_PAID_ORDER_SEQ") or "").strip(),
        "orders_sha256": str(
            os.environ.get("NALU_SUPERVISOR_ORDERS_SHA256") or ""
        ).strip(),
    }
    failures = []
    if values["config_lock"] != "1":
        failures.append("NALU_PAID_CONFIG_LOCK")
    if not values["authorization_ref"]:
        failures.append("NALU_PAID_AUTHORIZATION_REF")
    if not values["order_seq"].isdigit() or int(values["order_seq"]) <= 0:
        failures.append("NALU_PAID_ORDER_SEQ")
    if not re.fullmatch(r"[0-9a-f]{64}", values["orders_sha256"]):
        failures.append("NALU_SUPERVISOR_ORDERS_SHA256")
    if failures:
        raise AudioProviderError(
            "paid authority is incomplete: " + ",".join(failures)
        )
    return values


def _fingerprint(
    kind: str,
    payload: dict[str, Any],
    output_dir: Path,
    file_name: str | None,
) -> str:
    return _canonical_sha256(
        {
            "kind": kind,
            "payload": payload,
            "output_dir": str(output_dir),
            "file_name": file_name,
        }
    )


def _api_post(endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    with durable_generation_context():
        return _request(endpoint, payload)


def _api_query(task_id: str) -> dict[str, Any]:
    return _get(QUERY_ENDPOINT, {"task_id": task_id})


def list_speech_voices() -> dict[str, Any]:
    """Return the provider's current voice catalog without a paid request."""
    response = _get(VOICES_ENDPOINT, {})
    data = response.get("data") if isinstance(response, dict) else None
    if not isinstance(data, list):
        raise AudioProviderError("Giggle speech voices response was invalid")
    voices = []
    for row in data:
        if not isinstance(row, dict):
            continue
        voice_id = row.get("voice_id") or row.get("voiceId")
        if not isinstance(voice_id, str) or not voice_id.strip():
            continue
        voices.append({
            "voice_id": voice_id.strip(),
            "voice_name": row.get("name"),
            "style": row.get("style"),
            "gender": row.get("gender"),
            "age": row.get("age"),
            "language": row.get("language"),
        })
    return {
        "ok": bool(voices),
        "schema": "storyclaw.giggle_voice_catalog.v1",
        "status": "PASS" if voices else "BLOCKED",
        "capability": SPEECH_CAPABILITY,
        "voices": voices,
    }


def _provider_data(response: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(response, dict):
        return {}
    data = response.get("data")
    return data if isinstance(data, dict) else {}


def _download(url: str, destination: Path, *, overwrite: bool) -> dict[str, Any]:
    if destination.exists() and not overwrite:
        raise AudioProviderError(f"audio output exists (use --overwrite): {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            content_type = response.headers.get(
                "Content-Type", "application/octet-stream"
            )
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".partial",
                delete=False,
            ) as stream:
                temporary_name = stream.name
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
        temporary = Path(temporary_name)
        if temporary.stat().st_size == 0:
            raise AudioProviderError("provider audio download returned an empty file")
        os.replace(temporary, destination)
        return {
            "path": str(destination),
            "size": destination.stat().st_size,
            "sha256": _sha256_file(destination),
            "contentType": content_type,
        }
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _download_or_recover(
    url: str,
    destination: Path,
    *,
    overwrite: bool,
    transaction: dict[str, Any],
    transaction_path: Path,
) -> dict[str, Any]:
    """Resume a completed download without fetching or replacing it again."""
    saved_rows = transaction.get("downloaded_files") or []
    if not isinstance(saved_rows, list):
        raise AudioProviderError("transaction downloaded_files must be an array")
    for saved in saved_rows:
        if not isinstance(saved, dict) or saved.get("path") != str(destination):
            continue
        if not destination.is_file() or _sha256_file(destination) != saved.get("sha256"):
            raise AudioProviderError("previously downloaded audio SHA mismatch")
        return saved
    receipt = _download(url, destination, overwrite=overwrite)
    transaction.update(
        {
            "state": "TASK_ID_BOUND_COMPLETED_DOWNLOAD_PENDING",
            "downloaded_files": [*saved_rows, receipt],
        }
    )
    _atomic_json(transaction_path, transaction)
    return receipt


def _validate_common(
    *,
    kind: str,
    payload: dict[str, Any],
    output_dir: str | Path,
    file_name: str | None,
    transaction: str | Path,
) -> tuple[Path, Path, str]:
    output = Path(output_dir).expanduser().resolve()
    if kind == "speech":
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 10_000:
            raise AudioProviderError("speech text must contain 1 to 10,000 characters")
        for field in ("voice_id", "emotion"):
            if not isinstance(payload.get(field), str) or not payload[field].strip():
                raise AudioProviderError(f"{field} must be a non-empty string")
        speed = payload.get("speed")
        if not isinstance(speed, (int, float)) or isinstance(speed, bool) or not 0.5 <= float(speed) <= 2.0:
            raise AudioProviderError("speed must be between 0.5 and 2.0")
        if not file_name or Path(file_name).name != file_name or not file_name.lower().endswith(".mp3"):
            raise AudioProviderError("file name must be a local .mp3 name")
    else:
        prompt = payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 10_000:
            raise AudioProviderError("BGM prompt must contain 1 to 10,000 characters")
        if payload.get("instrumental") is not True:
            raise AudioProviderError("BGM generation requires instrumental=true")
    transaction_path = _absolute_transaction(transaction)
    return output, transaction_path, _fingerprint(kind, payload, output, file_name)


def _base_result(
    kind: str, payload: dict[str, Any], transaction: Path
) -> dict[str, Any]:
    summary = _safe_request_summary(kind, payload)
    base: dict[str, Any] = {
        "capability": SPEECH_CAPABILITY if kind == "speech" else BGM_CAPABILITY,
        "capabilityVersion": CAPABILITY_VERSION,
        "providerImplementation": IMPLEMENTATION,
        "transaction": str(transaction),
        "commercialUseMetadata": {"present": False, "releaseBlocked": True},
    }
    if kind == "speech":
        base.update(
            {
                "voiceId": payload["voice_id"],
                "emotion": payload["emotion"],
                "speed": float(payload["speed"]),
                "textSha256": summary["text_sha256"],
            }
        )
    else:
        base.update(
            {
                "instrumental": True,
                "promptSha256": summary["prompt_sha256"],
            }
        )
    return base


def _existing_result(
    transaction: dict[str, Any], base: dict[str, Any]
) -> dict[str, Any] | None:
    state = transaction.get("state")
    if state == "TERMINAL_COMPLETED":
        saved = transaction.get("result")
        if not isinstance(saved, dict):
            raise AudioProviderError("completed transaction is missing its result")
        artifact_rows = []
        if isinstance(saved.get("file"), dict):
            artifact_rows.append(saved["file"])
        artifact_rows.extend(saved.get("files") or [])
        for artifact in artifact_rows:
            path = Path(str(artifact.get("path") or ""))
            if not path.is_file() or _sha256_file(path) != artifact.get("sha256"):
                raise AudioProviderError("completed transaction output SHA mismatch")
        return {"ok": True, **saved, "recoveredFromTransaction": True}
    if state == "RESPONSE_LOST" or state == "INTENT_RECORDED":
        raise DuplicateSubmissionBlocked(
            "provider response is unbound; reconcile provider history/ledger before any retry"
        )
    if state == "TERMINAL_FAILED":
        return {
            "ok": False,
            **base,
            "status": "failed",
            "taskId": transaction.get("task_id"),
            "error": transaction.get("provider_error") or "provider task failed",
            "releaseEligible": False,
            "recoveredFromTransaction": True,
        }
    return None


def _poll_and_download(
    *,
    kind: str,
    payload: dict[str, Any],
    output: Path,
    file_name: str | None,
    transaction_path: Path,
    transaction: dict[str, Any],
    poll_interval_seconds: float,
    timeout_seconds: float,
    overwrite: bool,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    monotonic = monotonic or time.monotonic
    sleep = sleep or time.sleep
    base = _base_result(kind, payload, transaction_path)
    task_id = transaction.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise AudioProviderError("task-bound transaction is missing task_id")
    submitted = {**base, "status": "started", "taskId": task_id}
    started = monotonic()
    while True:
        elapsed = monotonic() - started
        if elapsed >= timeout_seconds:
            transaction.update(
                {
                    "state": "TASK_ID_BOUND_QUERY_PENDING",
                    "last_query_at": _utc_now(),
                    "last_remote_status": "timeout",
                }
            )
            _atomic_json(transaction_path, transaction)
            tail = {"file": None} if kind == "speech" else {"files": []}
            return {
                "ok": False,
                **submitted,
                "status": "timeout",
                "elapsedSeconds": round(elapsed, 3),
                **tail,
                "releaseEligible": False,
            }
        sleep(poll_interval_seconds)
        try:
            response = _api_query(task_id)
        except (Exception, SystemExit) as exc:
            transaction.update(
                {
                    "state": "TASK_ID_BOUND_QUERY_PENDING",
                    "last_query_at": _utc_now(),
                    "last_query_error_type": type(exc).__name__,
                }
            )
            _atomic_json(transaction_path, transaction)
            raise AudioProviderError(
                "task is bound, but the status query failed; rerun to resume without POST"
            ) from exc
        data = _provider_data(response)
        status = str(data.get("status") or "").lower()
        transaction.update(
            {
                "state": "TASK_ID_BOUND_QUERY_PENDING",
                "last_query_at": _utc_now(),
                "last_remote_status": status or "unknown",
                "last_url_count": len(data.get("urls") or []),
            }
        )
        _atomic_json(transaction_path, transaction)
        if status in TERMINAL_FAILURES:
            provider_error = str(data.get("err_msg") or "provider task failed")
            transaction.update(
                {
                    "state": "TERMINAL_FAILED",
                    "finished_at": _utc_now(),
                    "provider_error": "provider task failed",
                    "provider_error_sha256": _sha256_bytes(
                        provider_error.encode("utf-8")
                    ),
                }
            )
            _atomic_json(transaction_path, transaction)
            tail = {"file": None} if kind == "speech" else {"files": []}
            return {
                "ok": False,
                **submitted,
                "status": "failed",
                "error": transaction["provider_error"],
                "elapsedSeconds": round(monotonic() - started, 3),
                **tail,
                "releaseEligible": False,
            }
        if status != "completed":
            continue
        urls = [url for url in data.get("urls") or [] if isinstance(url, str) and url]
        if not urls:
            transaction.update(
                {
                    "state": "TASK_ID_BOUND_COMPLETED_DOWNLOAD_PENDING",
                    "download_error": "completed task returned no audio URL",
                }
            )
            _atomic_json(transaction_path, transaction)
            raise AudioProviderError("provider task completed without an audio URL")
        try:
            if kind == "speech":
                file_receipt = _download_or_recover(
                    urls[0],
                    output / str(file_name),
                    overwrite=overwrite,
                    transaction=transaction,
                    transaction_path=transaction_path,
                )
                result = {
                    **submitted,
                    "status": "completed",
                    "urlCount": len(urls),
                    "file": file_receipt,
                    "elapsedSeconds": round(monotonic() - started, 3),
                    "releaseEligible": False,
                    "directTrackUse": {
                        "track": "Audio.Dialogue",
                        "source": file_receipt["path"],
                    },
                    "requiredPostGenerationGates": [
                        "mediaProbe",
                        "dialogueTiming",
                        "humanListen",
                        "commercialRights",
                    ],
                }
            else:
                files = [
                    _download_or_recover(
                        url,
                        output / f"bgm_candidate_{index}.mp3",
                        overwrite=overwrite,
                        transaction=transaction,
                        transaction_path=transaction_path,
                    )
                    for index, url in enumerate(urls, 1)
                ]
                result = {
                    **submitted,
                    "status": "completed",
                    "urlCount": len(urls),
                    "files": files,
                    "elapsedSeconds": round(monotonic() - started, 3),
                    "releaseEligible": False,
                    "requiredPostGenerationGates": [
                        "mediaProbe",
                        "noVocals",
                        "loopability",
                        "loudness",
                        "humanListen",
                        "commercialRights",
                    ],
                }
        except Exception as exc:
            transaction.update(
                {
                    "state": "TASK_ID_BOUND_COMPLETED_DOWNLOAD_PENDING",
                    "download_error_type": type(exc).__name__,
                }
            )
            _atomic_json(transaction_path, transaction)
            raise
        transaction.update(
            {
                "state": "TERMINAL_COMPLETED",
                "finished_at": _utc_now(),
                "result": result,
            }
        )
        _atomic_json(transaction_path, transaction)
        return {"ok": True, **result, "recoveredFromTransaction": False}


def generate_audio(
    *,
    kind: str,
    payload: dict[str, Any],
    output_dir: str | Path,
    file_name: str | None,
    transaction: str | Path,
    paid: bool,
    poll_interval_seconds: float,
    timeout_seconds: float,
    overwrite: bool = False,
) -> dict[str, Any]:
    output, transaction_path, fingerprint = _validate_common(
        kind=kind,
        payload=payload,
        output_dir=output_dir,
        file_name=file_name,
        transaction=transaction,
    )
    base = _base_result(kind, payload, transaction_path)
    if not paid:
        return {
            "ok": True,
            **base,
            "status": "DRY_RUN",
            "paid": False,
            "providerPostAllowed": False,
            "requestFingerprintSha256": fingerprint,
            "releaseEligible": False,
        }
    if kind == "speech":
        if not 2 <= poll_interval_seconds <= 30 or not 10 <= timeout_seconds <= 600:
            raise AudioProviderError(
                "speech poll interval must be 2..30 seconds and timeout 10..600 seconds"
            )
        endpoint = SPEECH_ENDPOINT
    else:
        if not 15 <= poll_interval_seconds <= 60 or not 30 <= timeout_seconds <= 1500:
            raise AudioProviderError(
                "BGM poll interval must be 15..60 seconds and timeout 30..1500 seconds"
            )
        endpoint = BGM_ENDPOINT
    if not os.environ.get("GIGGLE_API_KEY", "").strip():
        raise AudioProviderError("GIGGLE_API_KEY is required only with --paid")
    paid_authority = _paid_authority_from_env()

    with _transaction_lock(transaction_path):
        if transaction_path.exists():
            persisted = _read_transaction(transaction_path)
            if persisted.get("request_fingerprint_sha256") != fingerprint:
                raise DuplicateSubmissionBlocked(
                    "transaction path is already bound to a different audio request"
                )
            if persisted.get("paid_authority") != paid_authority:
                raise DuplicateSubmissionBlocked(
                    "transaction paid authority differs from the current line-owner order"
                )
            existing = _existing_result(persisted, base)
            if existing is not None:
                return existing
            transaction_record = persisted
        else:
            transaction_record = {
                "schema": SCHEMA,
                "transaction_id": str(uuid.uuid4()),
                "state": "INTENT_RECORDED",
                "intent_recorded_at": _utc_now(),
                "provider_post_count": 1,
                "maximum_new_submissions": 0,
                "automatic_retry": False,
                "retry_guard": "RESPONSE_LOST_REQUIRES_PROVIDER_LEDGER_RECONCILIATION",
                "request_fingerprint_sha256": fingerprint,
                "request": _safe_request_summary(kind, payload),
                "capability": base["capability"],
                "provider_implementation": IMPLEMENTATION,
                "paid_authority": paid_authority,
            }
            _atomic_json(transaction_path, transaction_record)
            try:
                response = _api_post(endpoint, payload)
            except (Exception, SystemExit) as exc:
                transaction_record.update(
                    {
                        "state": "RESPONSE_LOST",
                        "response_lost_at": _utc_now(),
                        "transport_error_type": type(exc).__name__,
                    }
                )
                _atomic_json(transaction_path, transaction_record)
                raise AudioProviderError(
                    "provider POST response was lost; transaction quarantined with no automatic retry"
                ) from exc
            task_id = _provider_data(response).get("task_id")
            if not isinstance(task_id, str) or not task_id:
                transaction_record.update(
                    {
                        "state": "RESPONSE_LOST",
                        "response_lost_at": _utc_now(),
                        "transport_error_type": "MISSING_TASK_ID",
                        "provider_response_sha256": _canonical_sha256(response),
                    }
                )
                _atomic_json(transaction_path, transaction_record)
                raise AudioProviderError(
                    "provider POST returned no task_id; transaction quarantined with no automatic retry"
                )
            transaction_record.update(
                {
                    "state": "TASK_ID_BOUND_QUERY_PENDING",
                    "task_id": task_id,
                    "task_id_bound_at": _utc_now(),
                    "provider_response_sha256": _canonical_sha256(response),
                }
            )
            _atomic_json(transaction_path, transaction_record)

        return _poll_and_download(
            kind=kind,
            payload=payload,
            output=output,
            file_name=file_name,
            transaction_path=transaction_path,
            transaction=transaction_record,
            poll_interval_seconds=poll_interval_seconds,
            timeout_seconds=timeout_seconds,
            overwrite=overwrite,
        )


def generate_speech(
    text: str,
    output_dir: str | Path,
    *,
    voice_id: str,
    emotion: str,
    transaction: str | Path,
    paid: bool = False,
    speed: float = 1.0,
    poll_interval_seconds: float = 5,
    timeout_seconds: float = 120,
    overwrite: bool = False,
    file_name: str = "dialogue_voice.mp3",
) -> dict[str, Any]:
    return generate_audio(
        kind="speech",
        payload={
            "text": text,
            "voice_id": voice_id,
            "emotion": emotion,
            "speed": float(speed),
        },
        output_dir=output_dir,
        file_name=file_name,
        transaction=transaction,
        paid=paid,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
        overwrite=overwrite,
    )


def generate_bgm(
    prompt: str,
    output_dir: str | Path,
    *,
    transaction: str | Path,
    paid: bool = False,
    poll_interval_seconds: float = 20,
    timeout_seconds: float = 1500,
    overwrite: bool = False,
) -> dict[str, Any]:
    return generate_audio(
        kind="bgm",
        payload={"prompt": prompt, "instrumental": True},
        output_dir=output_dir,
        file_name=None,
        transaction=transaction,
        paid=paid,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
        overwrite=overwrite,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Durable StoryClaw speech/BGM provider (dry-run unless --paid)."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    voices = sub.add_parser(
        "speech-voices", help="List the current Giggle speech voice catalog"
    )
    voices.add_argument("--out")
    bgm = sub.add_parser(
        "bgm-generate", help="Generate instrumental BGM with durable task binding"
    )
    bgm.add_argument("prompt")
    bgm.add_argument("--output-dir", required=True)
    bgm.add_argument("--transaction", required=True)
    bgm.add_argument("--paid", action="store_true")
    bgm.add_argument("--poll-interval", type=float, default=20)
    bgm.add_argument("--timeout", type=float, default=1500)
    bgm.add_argument("--overwrite", action="store_true")

    speech = sub.add_parser(
        "speech-generate", help="Generate speech with durable task binding"
    )
    speech.add_argument("text")
    speech.add_argument("--voice-id", required=True)
    speech.add_argument("--emotion", required=True)
    speech.add_argument("--output-dir", required=True)
    speech.add_argument("--transaction", required=True)
    speech.add_argument("--paid", action="store_true")
    speech.add_argument("--speed", type=float, default=1)
    speech.add_argument("--file-name", default="dialogue_voice.mp3")
    speech.add_argument("--poll-interval", type=float, default=5)
    speech.add_argument("--timeout", type=float, default=120)
    speech.add_argument("--overwrite", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "speech-voices":
            result = list_speech_voices()
            if args.out:
                out = Path(args.out).expanduser()
                if not out.is_absolute():
                    raise AudioProviderError("--out must be an absolute path")
                _atomic_json(out, result)
        elif args.command == "speech-generate":
            result = generate_speech(
                args.text,
                args.output_dir,
                voice_id=args.voice_id,
                emotion=args.emotion,
                transaction=args.transaction,
                paid=args.paid,
                speed=args.speed,
                file_name=args.file_name,
                poll_interval_seconds=args.poll_interval,
                timeout_seconds=args.timeout,
                overwrite=args.overwrite,
            )
        else:
            result = generate_bgm(
                args.prompt,
                args.output_dir,
                transaction=args.transaction,
                paid=args.paid,
                poll_interval_seconds=args.poll_interval,
                timeout_seconds=args.timeout,
                overwrite=args.overwrite,
            )
    except AudioProviderError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
