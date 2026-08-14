#!/usr/bin/env python3
"""Delete one published episode's intermediates after a verified 24-hour hold."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA = "qingshan.episode_post_publish_retention.v1"
RECEIPT_SCHEMA = "qingshan.episode_post_publish_cleanup_receipt.v1"
RUNTIME_GATE_IDS = frozenset({"POST-PUBLISH-EPISODE-STORAGE-RETENTION"})
RUNTIME_GATE_BINDINGS = {
    "POST-PUBLISH-EPISODE-STORAGE-RETENTION": "apply_plan",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("published_at_timezone_required")
    return parsed.astimezone(timezone.utc)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def plan_fingerprint(plan: dict[str, Any]) -> str:
    protected = {
        "project_id": plan.get("project_id"),
        "episode": plan.get("episode"),
        "last_published_at": plan.get("last_published_at"),
        "latest_final_sha256": plan.get("latest_final_sha256"),
        "s3_archive_uri": plan.get("s3_archive_uri"),
        "s3_archive_receipt": plan.get("s3_archive_receipt"),
        "cleanup_roots": plan.get("cleanup_roots"),
        "delete_files": plan.get("delete_files"),
        "delete_file_count": plan.get("delete_file_count"),
        "delete_bytes": plan.get("delete_bytes"),
    }
    raw = json.dumps(
        protected,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_receipt_location(plan: dict[str, Any], out: Path) -> Path:
    resolved = out.expanduser().resolve()
    for raw in plan.get("cleanup_roots") or []:
        root = Path(raw).expanduser().resolve()
        if resolved == root or is_within(resolved, root):
            raise ValueError("cleanup_receipt_must_be_outside_episode_root")
    return resolved


def validate_dry_run_approval(path: Path, plan: dict[str, Any]) -> dict[str, Any]:
    try:
        approval = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("dry_run_approval_invalid") from exc
    if approval.get("schema") != RECEIPT_SCHEMA:
        raise ValueError("dry_run_approval_schema_mismatch")
    if approval.get("status") != "DRY_RUN_READY":
        raise ValueError("dry_run_approval_not_ready")
    expected = plan_fingerprint(plan)
    if approval.get("plan_fingerprint") != expected:
        raise ValueError("dry_run_approval_plan_changed")
    return approval


def build_plan(manifest: dict[str, Any], now: datetime) -> dict[str, Any]:
    failures: list[str] = []
    if manifest.get("schema") != SCHEMA:
        failures.append("manifest_schema_mismatch")
    if manifest.get("scope_complete") is not True:
        failures.append("cleanup_scope_not_complete")
    retention_hours = float(manifest.get("retention_hours") or 0)
    if retention_hours < 24:
        failures.append("retention_below_24_hours")
    project_root = Path(str(manifest.get("project_root") or "")).expanduser().resolve()
    episode_root = Path(str(manifest.get("episode_root") or "")).expanduser().resolve()
    if not project_root.is_dir():
        failures.append("project_root_missing")
    if not episode_root.is_dir() or not is_within(episode_root, project_root):
        failures.append("episode_root_invalid")

    required_targets = set(manifest.get("required_release_targets") or [])
    receipt_targets: dict[str, dict] = {}
    published_times: list[datetime] = []
    for receipt in manifest.get("release_receipts") or []:
        target = str(receipt.get("target") or "")
        if not target or target in receipt_targets:
            failures.append(f"release_receipt_target_invalid:{target or 'missing'}")
            continue
        receipt_targets[target] = receipt
        if receipt.get("status") != "PUBLISHED":
            failures.append(f"release_not_published:{target}")
        try:
            published_times.append(parse_time(str(receipt.get("published_at") or "")))
        except (TypeError, ValueError):
            failures.append(f"release_time_invalid:{target}")
        receipt_path = Path(str(receipt.get("path") or "")).expanduser().resolve()
        if not receipt_path.is_file():
            failures.append(f"release_receipt_missing:{target}")
        elif sha256(receipt_path) != receipt.get("sha256"):
            failures.append(f"release_receipt_sha_mismatch:{target}")
    missing_targets = sorted(required_targets - set(receipt_targets))
    failures.extend(f"required_release_target_missing:{target}" for target in missing_targets)
    if published_times:
        last_published_at = max(published_times)
        age_hours = (now.astimezone(timezone.utc) - last_published_at).total_seconds() / 3600
        if age_hours < retention_hours:
            failures.append(f"retention_hold_active:{age_hours:.3f}<{retention_hours:.3f}")
    else:
        last_published_at = None
        age_hours = None

    final = manifest.get("latest_final") or {}
    final_path = Path(str(final.get("path") or "")).expanduser().resolve()
    if not final_path.is_file() or not is_within(final_path, episode_root):
        failures.append("latest_final_missing_or_outside_episode")
    elif sha256(final_path) != final.get("sha256"):
        failures.append("latest_final_sha_mismatch")

    archive = manifest.get("cloud_archive") or {}
    archive_receipt_path = Path(
        str(archive.get("receipt_path") or "")
    ).expanduser().resolve()
    archive_receipt: dict[str, Any] = {}
    if archive.get("provider") != "s3" or archive.get("status") != "VERIFIED":
        failures.append("s3_archive_not_verified")
    if not archive_receipt_path.is_file():
        failures.append("s3_archive_receipt_missing")
    elif sha256(archive_receipt_path) != archive.get("receipt_sha256"):
        failures.append("s3_archive_receipt_sha_mismatch")
    else:
        try:
            archive_receipt = json.loads(
                archive_receipt_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            failures.append("s3_archive_receipt_invalid")
    archive_checks = {
        "schema": "qingshan.s3_episode_archive_receipt.v1",
        "status": "VERIFIED",
        "project_id": manifest.get("project_id"),
        "episode": manifest.get("episode"),
        "source_sha256": final.get("sha256"),
        "remote_sha256": final.get("sha256"),
        "bucket": archive.get("bucket"),
        "key": archive.get("key"),
        "head_verified": True,
        "stream_readback_verified": True,
    }
    for field, expected in archive_checks.items():
        if archive_receipt and archive_receipt.get(field) != expected:
            failures.append(f"s3_archive_receipt_mismatch:{field}")
    if archive.get("object_sha256") != final.get("sha256"):
        failures.append("s3_archive_object_sha_mismatch")

    cleanup_roots: list[Path] = []
    candidates: list[Path] = []
    for raw in manifest.get("cleanup_roots") or []:
        root = Path(str(raw)).expanduser().resolve()
        if not root.is_dir() or not is_within(root, episode_root):
            failures.append(f"cleanup_root_invalid:{root}")
            continue
        cleanup_roots.append(root)
        for item in root.rglob("*"):
            if item.is_symlink():
                failures.append(f"symlink_forbidden:{item}")
            elif item.is_file():
                candidates.append(item)
    candidates = sorted(set(candidates))
    if cleanup_roots and set(cleanup_roots) != {episode_root}:
        failures.append("cleanup_scope_must_equal_episode_root")
    plan = {
        "status": "READY" if not failures else "BLOCKED",
        "project_id": manifest.get("project_id"),
        "episode": manifest.get("episode"),
        "retention_hours": retention_hours,
        "last_published_at": last_published_at.isoformat() if last_published_at else None,
        "age_hours": round(age_hours, 3) if age_hours is not None else None,
        "latest_final": str(final_path),
        "latest_final_sha256": final.get("sha256"),
        "s3_archive_uri": (
            f"s3://{archive.get('bucket')}/{archive.get('key')}"
            if archive.get("bucket") and archive.get("key")
            else None
        ),
        "s3_archive_receipt": str(archive_receipt_path),
        "cleanup_roots": [str(path) for path in cleanup_roots],
        "delete_files": [str(path) for path in candidates],
        "delete_file_count": len(candidates),
        "delete_bytes": sum(path.stat().st_size for path in candidates),
        "failures": failures,
    }
    plan["plan_fingerprint"] = plan_fingerprint(plan)
    return plan


def apply_plan(plan: dict[str, Any], out: Path) -> dict[str, Any]:
    if plan.get("status") != "READY":
        raise ValueError("cleanup_plan_not_ready")
    out = validate_receipt_location(plan, out)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        **plan,
        "status": "APPLYING",
        "started_at": utc_now().isoformat(),
        "deleted_file_count": 0,
        "deleted_bytes": 0,
    }
    atomic_write(out, receipt)
    for raw in plan["delete_files"]:
        path = Path(raw)
        size = path.stat().st_size
        path.unlink()
        receipt["deleted_file_count"] += 1
        receipt["deleted_bytes"] += size
    for raw in sorted(plan["cleanup_roots"], key=len, reverse=True):
        root = Path(raw)
        for directory in sorted(
            (item for item in root.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            try:
                directory.rmdir()
            except OSError:
                pass
        try:
            root.rmdir()
        except OSError:
            pass
    remaining = [
        str(item)
        for raw in plan["cleanup_roots"]
        for item in Path(raw).rglob("*")
        if item.is_file() or item.is_symlink()
    ]
    if remaining:
        receipt["status"] = "FAIL_LOCAL_FILES_REMAIN"
        receipt["remaining"] = remaining
        atomic_write(out, receipt)
        raise RuntimeError("episode local files remain after cleanup")
    receipt["status"] = "PASS"
    receipt["completed_at"] = utc_now().isoformat()
    receipt["delete_files"] = []
    atomic_write(out, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approved-plan", type=Path)
    parser.add_argument("--now")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    now = parse_time(args.now) if args.now else utc_now()
    plan = build_plan(manifest, now)
    if args.apply and plan["status"] == "READY":
        if args.approved_plan is None:
            raise SystemExit("--approved-plan from a matching dry run is required")
        validate_dry_run_approval(args.approved_plan, plan)
        result = apply_plan(plan, args.out)
    else:
        out = validate_receipt_location(plan, args.out)
        result = {
            "schema": RECEIPT_SCHEMA,
            **plan,
            "status": plan["status"] if args.apply else f"DRY_RUN_{plan['status']}",
            "applied": False,
        }
        atomic_write(out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"PASS", "DRY_RUN_READY"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
