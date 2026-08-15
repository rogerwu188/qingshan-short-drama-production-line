#!/usr/bin/env python3
"""Fail-closed, offline-only one-shot intake for the paid E40 U17 result.

The command can first create a source-bound sidecar from an explicit local
video, then consume that video and sidecar.  It does not contact Giggle (or any
other network service), poll, download, submit, or mutate shared scheduling
state.  Only after every authority, credit, SHA, and media check passes is a
complete bundle renamed atomically into the fixed U17 inbox.

All validation failures return exit code 2 and leave no accepted bundle.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable


TASK_KEY = (
    "E40-U17-V3-FAST720-ARROW-ENTRY-EXACT-FIRST-FRAME-POSTMUX-"
    "DIA015-EXACTLY-ONE-V1"
)
MODEL = "seedance-2.0-fast"
TASK_ID = "60380322-2b8c-450e-b282-4e25a502c522"
TRANSACTION_REL = Path(
    "workflow/tasks/giggle_video_submit_transactions/E40/"
    "E40-U17-V3-FAST720-ARROW-ENTRY-EXACT-FIRST-FRAME-POSTMUX-"
    "DIA015-EXACTLY-ONE-V1__0613450b90268e43.json"
)
TRANSACTION_SHA256 = "ce9eedd5663d54e2a9215eab86d7301c1732623e299dfbdfba8236a7c9a19217"
SUBMISSION_REPORT_REL = Path(
    "qa/e40_production_20260814/u17_v3_fast720_remote_submission_v1/"
    "E40_U17_V3_FAST720_EXACTLY_ONCE_SUBMISSION_REPORT_V1.json"
)
SUBMISSION_REPORT_SHA256 = "0366b1c42b7305da25156417942dd6b5b7fde2ce7f4bac1faf3a55b41bbc40f4"
SUBMIT_RECEIPT_REL = Path(
    "qa/e40_production_20260814/u17_v3_fast720_remote_submission_v1/"
    "E40_U17_V3_FAST720_EXACTLY_ONCE_SUBMISSION_REPORT_V1_receipts/"
    "E40-U17-V3-FAST720-ARROW-ENTRY-EXACT-FIRST-FRAME-POSTMUX-"
    "DIA015-EXACTLY-ONE-V1_submit_receipt.json"
)
SUBMIT_RECEIPT_SHA256 = "7e327d487f5204e6d61adaa1f24af7be5f42fb7f98e20fbe12760fc5fcf384f5"
AUTHORIZED_MANIFEST_REL = Path(
    "workflow/claude_writer_agent/production/"
    "e40_claude_writer_v3_140d4b7b_20260808/u17_v3_fast720_exactly_once_v1/"
    "E40_U17_V3_FAST720_AUTHORIZED_EXACTLY_ONCE_MANIFEST_V1.json"
)
AUTHORIZED_MANIFEST_SHA256 = "a3d5b82514fec0e900279dd24c074500f767455ca7ac5f817099c66ae87778da"
INBOX_REL = Path(
    "working_assets/e40_offline_arrivals_20260814/"
    "e40_u17_u18_u19_u21_callback_intake_v1/U17"
)
BUNDLE_NAME = "E40_U17_OFFLINE_CALLBACK_ACCEPTED_V1"
SOURCE_NAME = "E40_U17_REAL_SOURCE_720X1280_24FPS_MIN96F.mp4"
SIDECAR_NAME = "E40_U17_OFFLINE_CALLBACK_SIDECAR_V1.json"
RECEIPT_NAME = "E40_U17_OFFLINE_CALLBACK_INTAKE_RECEIPT_V1.json"
SIDECAR_SCHEMA = "qingshan.e40.u17.offline_callback_sidecar.v1"
RECEIPT_SCHEMA = "qingshan.e40.u17.offline_callback_intake_receipt.v1"


class IntakeError(RuntimeError):
    """A fail-closed intake validation error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError(f"{label} is not readable JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise IntakeError(f"{label} must be a JSON object")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise IntakeError(message)


def repo_file(repo_root: Path, relative: Any, label: str) -> Path:
    require(isinstance(relative, str) and relative, f"{label}.path is required")
    candidate = (repo_root / relative).resolve()
    try:
        candidate.relative_to(repo_root)
    except ValueError as exc:
        raise IntakeError(f"{label}.path escapes repo root") from exc
    require(candidate.is_file(), f"{label}.path is not a file: {relative}")
    return candidate


def verified_authority(
    repo_root: Path, sidecar: dict[str, Any], key: str
) -> tuple[Path, dict[str, Any], str]:
    binding = sidecar.get(key)
    require(isinstance(binding, dict), f"sidecar.{key} object is required")
    path = repo_file(repo_root, binding.get("path"), f"sidecar.{key}")
    actual_sha = sha256_file(path)
    require(
        binding.get("sha256") == actual_sha,
        f"sidecar.{key}.sha256 does not match authority file",
    )
    return path, load_json(path, key), actual_sha


def probe_media(source: Path) -> dict[str, Any]:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-count_frames",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate,nb_read_frames,nb_frames",
        "-of",
        "json",
        str(source),
    ]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
    except OSError as exc:
        raise IntakeError(f"ffprobe is unavailable: {exc}") from exc
    require(result.returncode == 0, f"ffprobe failed: {result.stderr.strip()}")
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise IntakeError("ffprobe returned no usable primary video stream") from exc
    raw_frames = stream.get("nb_read_frames") or stream.get("nb_frames")
    try:
        frames = int(raw_frames)
        fps = Fraction(stream.get("avg_frame_rate") or stream["r_frame_rate"])
        width = int(stream["width"])
        height = int(stream["height"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise IntakeError("ffprobe returned incomplete geometry/fps/frame count") from exc
    return {"width": width, "height": height, "fps": fps, "frames": frames}


def _validate_credit(report: dict[str, Any], task_id: str) -> None:
    reconciliation = report.get("credit_reconciliation")
    require(isinstance(reconciliation, dict), "submission report credit reconciliation missing")
    require(reconciliation.get("status") == "PASS", "credit reconciliation is not PASS")
    require(reconciliation.get("model") == MODEL, "credit reconciliation model mismatch")
    rows = reconciliation.get("statement_rows")
    require(isinstance(rows, list), "credit statement_rows missing")
    bound_rows = [
        row
        for row in rows
        if isinstance(row, dict)
        and row.get("project_id") == task_id
        and row.get("model") == MODEL
    ]
    pay = sum(abs(int(row["credit"])) for row in bound_rows if row.get("event_type") == "Pay")
    refund = sum(
        abs(int(row["credit"])) for row in bound_rows if row.get("event_type") == "Refund"
    )
    require(pay == 64, f"authoritative task-bound Pay must be 64, got {pay}")
    require(refund == 0, f"authoritative task-bound Refund must be 0, got {refund}")
    require(reconciliation.get("charged_credits") == 64, "charged_credits must be 64")


def validate(
    repo_root: Path,
    source: Path,
    sidecar_path: Path,
    media_probe: Callable[[Path], dict[str, Any]] = probe_media,
) -> dict[str, Any]:
    require(source.is_file(), f"source is missing: {source}")
    require(sidecar_path.is_file(), f"sidecar is missing: {sidecar_path}")
    sidecar = load_json(sidecar_path, "sidecar")
    require(sidecar.get("schema") == SIDECAR_SCHEMA, "sidecar schema mismatch")
    require(sidecar.get("episode") == "E40", "sidecar episode must be E40")
    require(sidecar.get("unit_id") == "U17", "sidecar unit_id must be U17")
    require(sidecar.get("task_key") == TASK_KEY, "sidecar task_key mismatch")
    task_id = sidecar.get("task_id")
    require(task_id == TASK_ID, "sidecar task_id does not equal the pinned paid U17 task")
    require(sidecar.get("model") == MODEL, f"sidecar model must be {MODEL}")
    require(sidecar.get("resolution") == "720p", "sidecar resolution must be 720p")
    require(sidecar.get("aspect_ratio") == "9:16", "sidecar aspect_ratio must be 9:16")
    credits = sidecar.get("credits")
    require(credits == {"pay": 64, "refund": 0}, "sidecar credits must be Pay64/Refund0")
    source_binding = sidecar.get("source")
    require(isinstance(source_binding, dict), "sidecar.source object is required")
    source_sha = sha256_file(source)
    require(source_binding.get("sha256") == source_sha, "sidecar source SHA mismatch")
    require(source_binding.get("is_synthetic") is False, "synthetic source is forbidden")
    require(
        source_binding.get("is_failed_or_quarantined_asset") is False,
        "failed/quarantined source is forbidden",
    )

    transaction_path, transaction, transaction_sha = verified_authority(
        repo_root, sidecar, "transaction"
    )
    report_path, report, report_sha = verified_authority(
        repo_root, sidecar, "submission_report"
    )
    submit_receipt_path, submit_receipt, submit_receipt_sha = verified_authority(
        repo_root, sidecar, "submit_receipt"
    )
    require(
        transaction_path == repo_root / TRANSACTION_REL
        and transaction_sha == TRANSACTION_SHA256,
        "transaction is not the pinned paid U17 authority",
    )
    require(
        report_path == repo_root / SUBMISSION_REPORT_REL
        and report_sha == SUBMISSION_REPORT_SHA256,
        "submission report is not the pinned paid U17 authority",
    )
    require(
        submit_receipt_path == repo_root / SUBMIT_RECEIPT_REL
        and submit_receipt_sha == SUBMIT_RECEIPT_SHA256,
        "submit receipt is not the pinned paid U17 authority",
    )

    require(transaction.get("task_key") == TASK_KEY, "transaction task_key mismatch")
    require(transaction.get("state") == "SUBMITTED_TASK_ID_BOUND", "transaction state mismatch")
    require(transaction.get("task_id") == task_id, "transaction task_id mismatch")
    require(transaction.get("model") == MODEL, "transaction model mismatch")
    require(
        transaction.get("receipt") == submit_receipt_path.relative_to(repo_root).as_posix(),
        "transaction submit receipt path mismatch",
    )
    require(submit_receipt.get("code") == 200, "submit receipt code is not 200")
    require(submit_receipt.get("data", {}).get("task_id") == task_id, "submit receipt task_id mismatch")

    report_tasks = report.get("tasks")
    require(isinstance(report_tasks, list), "submission report tasks missing")
    matches = [
        row
        for row in report_tasks
        if isinstance(row, dict) and row.get("task_key") == TASK_KEY
    ]
    require(len(matches) == 1, "submission report must contain exactly one U17 task")
    report_task = matches[0]
    require(report.get("status") == "PASS" and report.get("submitted") == 1, "submission report not PASS/1")
    require(report_task.get("task_id") == task_id, "submission report task_id mismatch")
    require(
        report_task.get("transaction") == transaction_path.relative_to(repo_root).as_posix(),
        "submission report transaction path mismatch",
    )
    require(
        report_task.get("receipt") == submit_receipt_path.relative_to(repo_root).as_posix(),
        "submission report receipt path mismatch",
    )
    _validate_credit(report, task_id)

    manifest_rel = report.get("manifest")
    manifest_path = repo_file(repo_root, manifest_rel, "submission_report.manifest")
    manifest_sha = sha256_file(manifest_path)
    require(report.get("manifest_sha256") == manifest_sha, "submission report manifest SHA mismatch")
    require(
        manifest_path == repo_root / AUTHORIZED_MANIFEST_REL
        and manifest_sha == AUTHORIZED_MANIFEST_SHA256,
        "authorized manifest is not the pinned paid U17 authority",
    )
    manifest = load_json(manifest_path, "authorized manifest")
    manifest_tasks = manifest.get("tasks")
    require(isinstance(manifest_tasks, list), "authorized manifest tasks missing")
    authorized = [
        row
        for row in manifest_tasks
        if isinstance(row, dict) and row.get("task_key") == TASK_KEY
    ]
    require(len(authorized) == 1, "authorized manifest must contain exactly one U17 task")
    task = authorized[0]
    require(task.get("unit_id") == "U17", "authorized manifest unit mismatch")
    require(task.get("model") == MODEL, "authorized manifest model mismatch")
    require(task.get("resolution") == "720p", "authorized manifest resolution mismatch")
    require(task.get("aspect_ratio") == "9:16", "authorized manifest aspect ratio mismatch")
    authorization = task.get("submission_authorization", {})
    require(
        authorization.get("authorized") is True
        and authorization.get("paid_submission_allowed") is True,
        "authorized manifest paid submission binding missing",
    )

    media = media_probe(source)
    require(media.get("width") == 720, "source width must be 720")
    require(media.get("height") == 1280, "source height must be 1280")
    require(media.get("fps") == Fraction(24, 1), "source fps must be exactly 24")
    frames = media.get("frames")
    require(isinstance(frames, int) and frames >= 96, "source must contain at least 96 decoded frames")

    return {
        "sidecar": sidecar,
        "source_sha256": source_sha,
        "source_bytes": source.stat().st_size,
        "media": {"width": 720, "height": 1280, "fps": "24/1", "frames": frames},
        "task_id": task_id,
        "transaction_path": transaction_path.relative_to(repo_root).as_posix(),
        "transaction_sha256": transaction_sha,
        "submission_report_path": report_path.relative_to(repo_root).as_posix(),
        "submission_report_sha256": report_sha,
        "submit_receipt_path": submit_receipt_path.relative_to(repo_root).as_posix(),
        "submit_receipt_sha256": submit_receipt_sha,
        "manifest_path": manifest_path.relative_to(repo_root).as_posix(),
        "manifest_sha256": manifest_sha,
    }


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def validate_accepted_bundle(
    repo_root: Path,
    media_probe: Callable[[Path], dict[str, Any]] = probe_media,
) -> dict[str, Any]:
    """Revalidate the immutable accepted bundle for an independent successor.

    This deliberately repeats source, sidecar, authority, credit, and media
    validation.  A successor therefore never trusts the existence of a marker
    alone and never needs the legacy four-unit arrival arbiter.
    """

    repo_root = repo_root.resolve()
    bundle = repo_root / INBOX_REL / BUNDLE_NAME
    source = bundle / SOURCE_NAME
    sidecar_path = bundle / SIDECAR_NAME
    receipt_path = bundle / RECEIPT_NAME
    require(bundle.is_dir(), f"accepted U17 callback bundle missing: {bundle}")
    require(
        {path.name for path in bundle.iterdir()} == {SOURCE_NAME, SIDECAR_NAME, RECEIPT_NAME},
        "accepted U17 callback bundle contains missing or unexpected files",
    )
    receipt = load_json(receipt_path, "accepted bundle receipt")
    require(receipt.get("schema") == RECEIPT_SCHEMA, "accepted bundle receipt schema mismatch")
    require(
        receipt.get("status") == "ACCEPTED_ATOMIC_OFFLINE_CALLBACK",
        "accepted bundle receipt status mismatch",
    )
    require(receipt.get("episode") == "E40" and receipt.get("unit_id") == "U17", "receipt unit mismatch")
    require(receipt.get("task_key") == TASK_KEY, "receipt task_key mismatch")
    require(receipt.get("model") == MODEL, "receipt model mismatch")
    require(receipt.get("resolution") == "720p", "receipt resolution mismatch")
    require(receipt.get("aspect_ratio") == "9:16", "receipt aspect ratio mismatch")
    require(receipt.get("credits") == {"pay": 64, "refund": 0}, "receipt credits mismatch")
    expected_source_rel = (INBOX_REL / BUNDLE_NAME / SOURCE_NAME).as_posix()
    expected_sidecar_rel = (INBOX_REL / BUNDLE_NAME / SIDECAR_NAME).as_posix()
    require(receipt.get("source", {}).get("path") == expected_source_rel, "receipt source path mismatch")
    require(
        receipt.get("input_sidecar", {}).get("path") == expected_sidecar_rel,
        "receipt sidecar path mismatch",
    )

    validated = validate(repo_root, source, sidecar_path, media_probe)
    require(receipt.get("task_id") == validated["task_id"], "receipt task_id mismatch")
    require(receipt.get("source", {}).get("sha256") == validated["source_sha256"], "receipt source SHA mismatch")
    require(receipt.get("source", {}).get("bytes") == validated["source_bytes"], "receipt source size mismatch")
    for key, value in validated["media"].items():
        require(receipt.get("source", {}).get(key) == value, f"receipt source {key} mismatch")
    require(
        receipt.get("input_sidecar", {}).get("sha256") == sha256_file(sidecar_path),
        "receipt sidecar SHA mismatch",
    )
    authority_map = {
        "transaction": (validated["transaction_path"], validated["transaction_sha256"]),
        "submission_report": (
            validated["submission_report_path"],
            validated["submission_report_sha256"],
        ),
        "submit_receipt": (
            validated["submit_receipt_path"],
            validated["submit_receipt_sha256"],
        ),
        "authorized_manifest": (validated["manifest_path"], validated["manifest_sha256"]),
    }
    receipt_authorities = receipt.get("authorities")
    require(isinstance(receipt_authorities, dict), "receipt authorities missing")
    for key, (path, digest) in authority_map.items():
        require(
            receipt_authorities.get(key) == {"path": path, "sha256": digest},
            f"receipt {key} authority mismatch",
        )
    return {
        "source": source,
        "source_sha256": validated["source_sha256"],
        "receipt": receipt_path,
        "receipt_sha256": sha256_file(receipt_path),
        "task_id": validated["task_id"],
        "frames": validated["media"]["frames"],
    }


def map_validated_source(source: Path, target: Path, expected_sha256: str) -> dict[str, Any]:
    """Atomically and idempotently map a validated raw source to a successor."""

    source = source.resolve()
    target = target.resolve()
    require(source.is_file(), f"validated source missing: {source}")
    require(sha256_file(source) == expected_sha256, "validated source SHA changed before mapping")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        require(target.is_file(), f"successor target is not a file: {target}")
        require(sha256_file(target) == expected_sha256, "successor target collision")
        return {"path": target, "sha256": expected_sha256, "reused": True}
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        require(sha256_file(temporary) == expected_sha256, "successor mapping SHA changed during copy")
        _fsync_file(temporary)
        os.replace(temporary, target)
        _fsync_dir(target.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return {"path": target, "sha256": expected_sha256, "reused": False}


def write_source_bound_sidecar(
    repo_root: Path,
    source: Path,
    output: Path,
    media_probe: Callable[[Path], dict[str, Any]] = probe_media,
) -> dict[str, Any]:
    """Atomically write the only sidecar accepted for the pinned U17 task."""

    repo_root = repo_root.resolve()
    source = source.resolve()
    output = output.resolve()
    inbox = (repo_root / INBOX_REL).resolve()
    require(repo_root.is_dir(), f"repo root missing: {repo_root}")
    require(source.is_file(), f"source is missing: {source}")
    require(not output.exists(), f"sidecar output already exists: {output}")
    for candidate, label in ((source, "source"), (output, "sidecar output")):
        try:
            candidate.relative_to(inbox)
        except ValueError:
            pass
        else:
            raise IntakeError(f"{label} must remain outside the fixed inbox")

    authorities = (
        ("transaction", TRANSACTION_REL, TRANSACTION_SHA256),
        ("submission_report", SUBMISSION_REPORT_REL, SUBMISSION_REPORT_SHA256),
        ("submit_receipt", SUBMIT_RECEIPT_REL, SUBMIT_RECEIPT_SHA256),
        ("authorized_manifest", AUTHORIZED_MANIFEST_REL, AUTHORIZED_MANIFEST_SHA256),
    )
    authority_bindings: dict[str, dict[str, str]] = {}
    for label, relative, expected_sha in authorities:
        path = (repo_root / relative).resolve()
        require(path.is_file(), f"pinned {label} authority missing: {relative}")
        require(
            sha256_file(path) == expected_sha,
            f"pinned {label} authority SHA mismatch",
        )
        authority_bindings[label] = {
            "path": relative.as_posix(),
            "sha256": expected_sha,
        }

    media = media_probe(source)
    require(media.get("width") == 720, "source width must be 720")
    require(media.get("height") == 1280, "source height must be 1280")
    require(media.get("fps") == Fraction(24, 1), "source fps must be exactly 24")
    frames = media.get("frames")
    require(isinstance(frames, int) and frames >= 96, "source must contain at least 96 decoded frames")
    source_sha = sha256_file(source)
    payload = {
        "schema": SIDECAR_SCHEMA,
        "episode": "E40",
        "unit_id": "U17",
        "task_key": TASK_KEY,
        "task_id": TASK_ID,
        "model": MODEL,
        "resolution": "720p",
        "aspect_ratio": "9:16",
        "credits": {"pay": 64, "refund": 0},
        "source": {
            "sha256": source_sha,
            "bytes": source.stat().st_size,
            "width": 720,
            "height": 1280,
            "fps": "24/1",
            "frames": frames,
            "is_synthetic": False,
            "is_failed_or_quarantined_asset": False,
        },
        "transaction": authority_bindings["transaction"],
        "submission_report": authority_bindings["submission_report"],
        "submit_receipt": authority_bindings["submit_receipt"],
        "authorized_manifest": authority_bindings["authorized_manifest"],
        "side_effect_contract": {
            "network": False,
            "provider_query": False,
            "provider_poll": False,
            "provider_download": False,
            "provider_submit": False,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{output.name}.", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
        _fsync_dir(output.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "status": "WROTE_PINNED_SOURCE_BOUND_SIDECAR",
        "path": output,
        "sha256": sha256_file(output),
        "source_sha256": source_sha,
        "frames": frames,
    }


def run_intake(
    repo_root: Path,
    source: Path,
    sidecar_path: Path,
    media_probe: Callable[[Path], dict[str, Any]] = probe_media,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    source = source.resolve()
    sidecar_path = sidecar_path.resolve()
    inbox = (repo_root / INBOX_REL).resolve()
    bundle = inbox / BUNDLE_NAME
    require(repo_root.is_dir(), f"repo root missing: {repo_root}")
    require(inbox.is_dir(), f"fixed U17 inbox missing: {inbox}")
    for candidate, label in ((source, "source"), (sidecar_path, "sidecar")):
        try:
            candidate.relative_to(inbox)
        except ValueError:
            pass
        else:
            raise IntakeError(f"{label} must be an external explicit input, not inside fixed inbox")
    require(not bundle.exists(), f"accepted U17 callback bundle already exists: {bundle}")

    validated = validate(repo_root, source, sidecar_path, media_probe)
    stage = Path(tempfile.mkdtemp(prefix=".u17-intake-stage-", dir=inbox))
    try:
        staged_source = stage / SOURCE_NAME
        staged_sidecar = stage / SIDECAR_NAME
        staged_receipt = stage / RECEIPT_NAME
        shutil.copyfile(source, staged_source)
        shutil.copyfile(sidecar_path, staged_sidecar)
        require(
            sha256_file(staged_source) == validated["source_sha256"],
            "staged source SHA changed during copy",
        )
        require(
            sha256_file(staged_sidecar) == sha256_file(sidecar_path),
            "staged sidecar SHA changed during copy",
        )
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "status": "ACCEPTED_ATOMIC_OFFLINE_CALLBACK",
            "episode": "E40",
            "unit_id": "U17",
            "task_key": TASK_KEY,
            "task_id": validated["task_id"],
            "model": MODEL,
            "resolution": "720p",
            "aspect_ratio": "9:16",
            "credits": {"pay": 64, "refund": 0},
            "source": {
                "path": (INBOX_REL / BUNDLE_NAME / SOURCE_NAME).as_posix(),
                "sha256": validated["source_sha256"],
                "bytes": validated["source_bytes"],
                **validated["media"],
            },
            "input_sidecar": {
                "path": (INBOX_REL / BUNDLE_NAME / SIDECAR_NAME).as_posix(),
                "sha256": sha256_file(sidecar_path),
            },
            "authorities": {
                "transaction": {
                    "path": validated["transaction_path"],
                    "sha256": validated["transaction_sha256"],
                },
                "submission_report": {
                    "path": validated["submission_report_path"],
                    "sha256": validated["submission_report_sha256"],
                },
                "submit_receipt": {
                    "path": validated["submit_receipt_path"],
                    "sha256": validated["submit_receipt_sha256"],
                },
                "authorized_manifest": {
                    "path": validated["manifest_path"],
                    "sha256": validated["manifest_sha256"],
                },
            },
            "side_effect_contract": {
                "network": False,
                "provider_query": False,
                "provider_poll": False,
                "shared_scheduler_mutation": False,
            },
        }
        staged_receipt.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        for path in (staged_source, staged_sidecar, staged_receipt):
            _fsync_file(path)
        _fsync_dir(stage)
        os.replace(stage, bundle)
        _fsync_dir(inbox)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise

    final_receipt = bundle / RECEIPT_NAME
    return {
        "status": "ACCEPTED_ATOMIC_OFFLINE_CALLBACK",
        "bundle": bundle.relative_to(repo_root).as_posix(),
        "receipt": final_receipt.relative_to(repo_root).as_posix(),
        "receipt_sha256": sha256_file(final_receipt),
        "source_sha256": validated["source_sha256"],
        "frames": validated["media"]["frames"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--sidecar", type=Path)
    mode.add_argument("--write-sidecar", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.write_sidecar is not None:
            result = write_source_bound_sidecar(args.repo_root, args.source, args.write_sidecar)
            result["path"] = str(result["path"])
        else:
            result = run_intake(args.repo_root, args.source, args.sidecar)
    except IntakeError as exc:
        print(json.dumps({"status": "REJECTED", "error": str(exc)}, ensure_ascii=False))
        return 2
    except Exception as exc:  # fail closed without a traceback in unattended use
        print(json.dumps({"status": "REJECTED", "error": f"internal intake failure: {exc}"}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
