#!/usr/bin/env python3
"""Incrementally synchronize Qingshan producer-review data to StoryClaw S3.

S3 is the only StoryClaw transport. The tool uploads changed, public-safe
production evidence and automatically delivers final/re-cut/release MP4s with
SHA/size verification plus a c2sc notification. StoryClaw discovers and pulls
increments from the S3 manifest into its own local workspace.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELAY_PATH = ROOT / "workflow/s3_relay/relay_client.py"
SPEC = importlib.util.spec_from_file_location("qingshan_s3_relay_client", RELAY_PATH)
RELAY = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(RELAY)

DEFAULT_STATE = ROOT / "workflow/s3_relay/STORYCLAW_S3_AUTOSYNC_STATE.json"
DEFAULT_RECEIPT = ROOT / "workflow/s3_relay/STORYCLAW_S3_AUTOSYNC_RECEIPT.json"
DEFAULT_LOCK = ROOT / "workflow/s3_relay/STORYCLAW_S3_AUTOSYNC.lock"
DEFAULT_OUTBOX = ROOT / "workflow/s3_relay/outbox"
DEFAULT_ROOTS = (
    ROOT / "workflow/tasks",
    ROOT / "workflow/prompts",
    ROOT / "workflow/dashboard",
    ROOT / "workflow/runtime",
    ROOT / "workflow/release",
    ROOT / "workflow/claude_writer_agent/production",
    ROOT / "workflow/CODEX_TO_CLAUDE.md",
    ROOT / "configs",
    ROOT / "qa",
    ROOT / "working_assets",
)
# CLAUDE_TO_CODEX.md is a local audit index and can contain historical secret
# material copied from operator messages. Claude directives travel through the
# dedicated S3 claude channel, so this file must never enter the generic files
# manifest.
SYNC_SUFFIXES = {
    ".json", ".md", ".txt", ".csv", ".jpg", ".jpeg", ".png", ".webp",
    ".wav", ".mp3", ".m4a", ".mp4",
}
EXCLUDED_PARTS = {".secrets", "__pycache__", ".git", "packages", "node_modules"}
FINAL_REJECT_MARKERS = ("not_final", "rough", "trial", "draft", "pending")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_final_video(path: Path) -> bool:
    if path.suffix.lower() != ".mp4":
        return False
    lowered = path.as_posix().lower()
    if any(marker in lowered for marker in FINAL_REJECT_MARKERS):
        return False
    return "final_package" in lowered or "final_locked" in lowered or "release" in lowered


def safe_delivery_slug(path: Path, final_video: bool) -> str:
    try:
        relative = path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        relative = path.name
    encoded = re.sub(r"[^A-Za-z0-9_.-]", "__", relative)
    prefix = "final" if final_video else "sync"
    candidate = f"{prefix}__{encoded}"
    if len(candidate) <= 220:
        return candidate
    suffix = path.suffix.lower()
    return candidate[: 220 - len(suffix)] + suffix


def load_json(path: Path, default: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def iter_recent_files(lookback_hours: float) -> list[Path]:
    cutoff = time.time() - lookback_hours * 3600
    found: set[Path] = set()
    for root in DEFAULT_ROOTS:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else root.rglob("*")
        for path in candidates:
            try:
                is_file = path.is_file()
                stat = path.stat() if is_file else None
            except OSError:
                # Assets may be replaced while the scanner walks the tree.
                # Skip only the vanished path so the rest of the batch continues.
                continue
            if not is_file or path.suffix.lower() not in SYNC_SUFFIXES:
                continue
            try:
                relative_parts = set(path.resolve().relative_to(ROOT).parts)
            except ValueError:
                continue
            if relative_parts & EXCLUDED_PARTS or stat is None or stat.st_mtime < cutoff:
                continue
            found.add(path.resolve())

    exports = ROOT / "exports"
    if exports.exists():
        for path in exports.rglob("*.mp4"):
            try:
                modified = path.stat().st_mtime
            except OSError:
                continue
            if modified >= cutoff and is_final_video(path):
                found.add(path.resolve())
    return sorted(found)


def media_duration(path: Path) -> float | None:
    finder = ROOT / "tools/find_ffmpeg.sh"
    try:
        ffmpeg = subprocess.run(
            [str(finder), str(ROOT)], check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ).stdout.strip()
        sibling = Path(ffmpeg).with_name("ffprobe")
        ffprobe = str(sibling if sibling.exists() else (shutil.which("ffprobe") or sibling))
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        return round(float(result.stdout.strip()), 6)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def infer_episode(path: Path) -> str:
    match = re.search(r"(?i)(?:^|[/_.-])(E\d{2,3}R?)(?:[/_.-]|$)", path.as_posix())
    return match.group(1).upper() if match else "UNKNOWN_EPISODE"


def upload_priority(path: Path, explicit_final: set[Path]) -> tuple[int, float, str]:
    """Put final deliveries and compact control records ahead of bulk evidence."""
    final_video = path in explicit_final or is_final_video(path)
    suffix = path.suffix.lower()
    try:
        modified = path.stat().st_mtime
    except OSError:
        modified = 0.0
    if path in explicit_final:
        tier = 0
    elif final_video:
        tier = 1
    elif suffix in {".json", ".md", ".txt", ".csv"}:
        tier = 2
    elif suffix in {".wav", ".mp3", ".m4a", ".mp4"}:
        tier = 3
    else:
        tier = 4
    return tier, -modified, str(path)


def final_notification(
    path: Path,
    delivery: dict,
    ci_status: str,
    release_state: str,
    outbox: Path,
) -> Path:
    episode = infer_episode(path)
    message_id = f"C2SC-AUTO-FINAL-{episode}-{delivery['sha256'][:12]}"
    outbox.mkdir(parents=True, exist_ok=True)
    target = outbox / f"{message_id}.md"
    duration = media_duration(path)
    target.write_text(
        "\n".join(
            [
                f"# {message_id} | Codex -> StoryClaw | S3_FINAL_SYNCED",
                "",
                f"- episode: {episode}",
                f"- version: {path.parent.name}/{path.name}",
                f"- manifest_delivery_slug: {delivery['slug']}",
                f"- sha256: {delivery['sha256']}",
                f"- size_bytes: {delivery['size_bytes']}",
                f"- remote_size_verified: {str(delivery.get('remote_size_verified', False)).lower()}",
                f"- duration_seconds: {duration if duration is not None else 'UNKNOWN'}",
                f"- ci_status: {ci_status}",
                f"- release_state: {release_state}",
                "- transport: S3_PRIMARY_NO_BRIDGE",
                "- storyclaw_action: auto-download from files manifest to local workspace and run independent review",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return target


def existing_final_notification(state: dict, digest: str) -> dict | None:
    """Return or migrate the immutable notification record for a final SHA."""
    notifications = state.setdefault("final_notifications", {})
    if digest in notifications:
        record = notifications[digest]
        return record if record.get("status") in {"sending", "sent"} else None
    for record in state.get("files", {}).values():
        if record.get("sha256") != digest or not record.get("c2sc_seq"):
            continue
        migrated = {
            "status": "sent",
            "c2sc_seq": record["c2sc_seq"],
            "notification": record.get("notification"),
            "recorded_at": record.get("uploaded_at"),
        }
        notifications[digest] = migrated
        return migrated
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto-sync producer-review data and final MP4s to StoryClaw S3.")
    parser.add_argument("--path", action="append", type=Path, default=[])
    parser.add_argument("--final-video", action="append", type=Path, default=[])
    parser.add_argument("--lookback-hours", type=float, default=6.0)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--receipt", type=Path, default=DEFAULT_RECEIPT)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--checklist", type=Path, default=RELAY.DEFAULT_CHECKLIST)
    parser.add_argument("--ci-status", default="PENDING_OR_UNBOUND_AT_AUTOSYNC")
    parser.add_argument("--release-state", default="NOT_RELEASED_OR_UNBOUND_AT_AUTOSYNC")
    parser.add_argument(
        "--max-files",
        type=int,
        default=200,
        help="Maximum changed scan files per run; explicit final videos are never deferred. Use 0 for unlimited.",
    )
    parser.add_argument("--no-scan", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    args.lock.parent.mkdir(parents=True, exist_ok=True)
    lock_handle = args.lock.open("a+", encoding="utf-8")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)

    explicit_final = {path.expanduser().resolve() for path in args.final_video}
    candidates = {path.expanduser().resolve() for path in args.path} | explicit_final
    if not args.no_scan:
        candidates.update(iter_recent_files(args.lookback_hours))

    state = load_json(args.state, {"schema": "qingshan.storyclaw.s3_autosync.v1", "files": {}})
    known = state.setdefault("files", {})
    uploaded: list[dict] = []
    skipped: list[dict] = []
    failed: list[dict] = []
    deferred: list[dict] = []
    processed = 0

    for path in sorted(candidates, key=lambda item: upload_priority(item, explicit_final)):
        try:
            is_file = path.is_file()
        except OSError:
            is_file = False
        if not is_file:
            failed.append({"path": str(path), "error": "missing_file"})
            continue
        final_video = path in explicit_final or is_final_video(path)
        try:
            digest = sha256(path)
        except OSError as exc:
            failed.append({"path": str(path), "error": f"read_failed:{exc}"})
            continue
        state_key = str(path)
        previous = known.get(state_key, {})
        if previous.get("sha256") == digest and previous.get("uploaded_ok") and not args.force:
            skipped.append({"path": state_key, "reason": "unchanged", "sha256": digest})
            continue
        if args.max_files > 0 and processed >= args.max_files and path not in explicit_final:
            deferred.append({"path": state_key, "reason": "bounded_incremental_backfill"})
            continue
        processed += 1
        slug = safe_delivery_slug(path, final_video)
        try:
            delivery = RELAY.deliver_file(path, slug, args.checklist)
            record = {
                "path": state_key,
                "sha256": digest,
                "slug": delivery["slug"],
                "size_bytes": delivery["size_bytes"],
                "final_video": final_video,
                "uploaded_ok": True,
                "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            if final_video:
                existing_notification = existing_final_notification(state, digest)
                if existing_notification:
                    record["c2sc_seq"] = existing_notification.get("c2sc_seq")
                    record["notification"] = existing_notification.get("notification")
                    record["notification_deduplicated_by_sha"] = True
                else:
                    notification = final_notification(
                        path, delivery, args.ci_status, args.release_state, DEFAULT_OUTBOX
                    )
                    reservation = {
                        "status": "sending",
                        "notification": str(notification),
                        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    }
                    state.setdefault("final_notifications", {})[digest] = reservation
                    write_json_atomic(args.state, state)
                    sequence = RELAY.send("c2sc", notification, notification.name, args.checklist)
                    reservation.update({"status": "sent", "c2sc_seq": sequence})
                    record["c2sc_seq"] = sequence
                    record["notification"] = str(notification)
            known[state_key] = record
            uploaded.append(record)
            state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            state["transport"] = "S3_PRIMARY_NO_BRIDGE"
            write_json_atomic(args.state, state)
        except Exception as exc:  # Preserve per-file isolation; one failure must not stop the batch.
            failure = {"path": state_key, "final_video": final_video, "error": str(exc)}
            failed.append(failure)
            if final_video:
                reservation = state.setdefault("final_notifications", {}).get(digest)
                if reservation and reservation.get("status") == "sending":
                    reservation.update({"status": "failed", "error": str(exc)})
            known[state_key] = {**failure, "sha256": digest, "uploaded_ok": False}
            state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            state["transport"] = "S3_PRIMARY_NO_BRIDGE"
            write_json_atomic(args.state, state)

    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    state["transport"] = "S3_PRIMARY_NO_BRIDGE"
    write_json_atomic(args.state, state)
    receipt = {
        "schema": "qingshan.storyclaw.s3_autosync_receipt.v1",
        "updated_at": state["updated_at"],
        "transport": "S3_PRIMARY_NO_BRIDGE",
        "storyclaw_download_mode": "AUTO_DOWNLOAD_TO_LOCAL_AND_PROCESS",
        "candidate_count": len(candidates),
        "uploaded": uploaded,
        "skipped": skipped,
        "failed": failed,
        "deferred": deferred,
        "status": "PASS" if not failed else "PARTIAL",
    }
    write_json_atomic(args.receipt, receipt)
    print(json.dumps({
        "status": receipt["status"],
        "uploaded": len(uploaded),
        "final_videos_uploaded": sum(1 for item in uploaded if item["final_video"]),
        "skipped": len(skipped),
        "failed": len(failed),
        "deferred": len(deferred),
        "receipt": str(args.receipt),
    }, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
