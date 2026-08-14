#!/usr/bin/env python3
"""Mirror newly generated review assets to the StoryClaw bridge inbox.

The bridge has no shared filesystem, so Codex must upload every producer-
relevant artifact as it is created or changed. This tool keeps a local state
file of content hashes and uploads only changed files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional


from storyclaw_bridge_config import base_url as configured_base_url
from storyclaw_bridge_config import communication_mode
from storyclaw_bridge_config import storyclaw_writes_enabled
from storyclaw_bridge_config import token as configured_token


DEFAULT_BASE_URL = configured_base_url()
DEFAULT_INCLUDE_ROOTS = [
    "workflow/tasks",
    "workflow/prompts",
    "workflow/dashboard",
    "workflow/storyclaw_sync",
    "workflow/CODEX_TO_CLAUDE.md",
    "codex_docs/AGENT协作信箱协议_20260711.md",
    "codex_docs/每集标准生产全流程_v1_E17起_20260713.md",
    "codex_docs/生产线全流程与门禁总览_20260713.md",
    "codex_docs/共享审稿_青山E17剧本对白_v0_20260714.md",
    "configs",
    "bootstrap/dist/ai_drama_factory_agent_core_latest.tgz",
    "qa/e17_full_assembly_trial_v0_20260714",
    "qa/e17_watch_gate_v9_20260714",
    "qa/e18_selected_source_contacts_20260714",
    "qa/e18_visual_fix_r2_contacts_20260714",
    "qa/e18_e19_runtime_beds_batch1_ocr_20260715",
    "qa/e18_e19_runtime_beds_batch1_contacts_20260715",
    "qa/e18_e19_runtime_beds_batch2_ocr_20260715",
    "qa/e18_e19_runtime_beds_batch2_contacts_20260715",
    "qa/e18_e19_timeline_draft_v0_20260715",
    "qa/e19_selected_source_contacts_20260714",
    "qa/e19_visual_fix_r3_contacts_20260714",
    "qa/e19_visual_strict_reroll_contacts_20260714",
    "qa/e17_preflight_20260714",
    "qa/e17_first_wave_video_20260714",
    "qa/e20_preflight_20260716",
    "exports/e17",
    "exports/e18_e19_timeline_draft_v0_20260715",
    "working_assets/e17_first_wave_video_20260714",
    "working_assets/e20_voice_source_candidates_20260716/review_windows",
    "tools/storyclaw_realtime_sync.py",
    "tools/storyclaw_bridge_reply.py",
    "tools/storyclaw_outbox_poller.py",
    "tools/source_video_bottom_text_audit.py",
    "tools/visual_text_prompt_guard.py",
    "libraries/tools/TOOL_CAPABILITY_REGISTRY.md",
]
DEFAULT_SUFFIXES = {
    ".json",
    ".html",
    ".js",
    ".md",
    ".txt",
    ".csv",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".mp4",
    ".wav",
    ".py",
    ".tgz",
}
DEFAULT_EXCLUDE_PARTS = {
    "__pycache__",
    ".DS_Store",
    "packages",
}
DEFAULT_EXCLUDE_NAMES = {
    "STORYCLAW_REALTIME_SYNC_STATE.json",
    "STORYCLAW_REALTIME_SYNC_RECEIPT.md",
    "STORYCLAW_OUTBOX_POLLER_STATE.json",
    "STORYCLAW_OUTBOX_POLLER_RECEIPT.md",
    "STORYCLAW_BRIDGE_REPLY_RECEIPT.md",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def encoded_name(path: Path, base: Path) -> str:
    rel = path.relative_to(base).as_posix()
    return rel.replace("/", "__")


def iter_files(base: Path, include_roots: list[str], max_bytes: int) -> list[Path]:
    files: list[Path] = []
    for root in include_roots:
        p = (base / root).resolve()
        if not p.exists():
            continue
        candidates = [p] if p.is_file() else sorted(x for x in p.rglob("*") if x.is_file())
        for item in candidates:
            rel_parts = set(item.relative_to(base).parts)
            if rel_parts & DEFAULT_EXCLUDE_PARTS:
                continue
            if item.name in DEFAULT_EXCLUDE_NAMES:
                continue
            if item.suffix.lower() not in DEFAULT_SUFFIXES:
                continue
            if item.stat().st_size > max_bytes:
                continue
            files.append(item)
    return sorted(set(files))


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"files": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def upload(path: Path, name: str, base_url: str, token: str, dry_run: bool) -> dict:
    if dry_run:
        return {"ok": True, "dry_run": True, "name": name, "size": path.stat().st_size}
    url = f"{base_url.rstrip('/')}/upload?token={token}"
    result = subprocess.run(
        [
            "curl",
            "-sS",
            "-X",
            "POST",
            "-F",
            f"file=@{path};filename={name}",
            url,
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return {"ok": False, "name": name, "error": result.stderr.strip()}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "name": name, "error": "non_json_response", "stdout": result.stdout[:500]}


def daily_write_quota_exhausted(response: dict) -> bool:
    text = " ".join(
        str(response.get(key, ""))
        for key in ("error", "stdout", "message")
    ).casefold()
    return "kv put() limit exceeded for the day" in text


def next_daily_quota_retry(now: Optional[datetime] = None) -> datetime:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    next_day = (current + timedelta(days=1)).date()
    return datetime(
        next_day.year,
        next_day.month,
        next_day.day,
        0,
        5,
        tzinfo=timezone.utc,
    )


def retry_is_deferred(state: dict, now: Optional[datetime] = None) -> bool:
    raw = state.get("write_retry_after_utc")
    if not raw:
        return False
    try:
        retry_after = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc) < retry_after.astimezone(timezone.utc)


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload changed producer-review files to StoryClaw bridge.")
    parser.add_argument("--base", default="/Users/rogerwu/qingshan_short_drama")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--state", default="/Users/rogerwu/qingshan_short_drama/workflow/storyclaw_sync/STORYCLAW_REALTIME_SYNC_STATE.json")
    parser.add_argument("--receipt", default="/Users/rogerwu/qingshan_short_drama/workflow/storyclaw_sync/STORYCLAW_REALTIME_SYNC_RECEIPT.md")
    parser.add_argument("--max-bytes", type=int, default=80 * 1024 * 1024)
    parser.add_argument("--token-env", default="STORYCLAW_BRIDGE_TOKEN")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if communication_mode().get("mode") == "DUAL_SUPERVISOR_S3_PRIMARY_NO_BRIDGE":
        if args.dry_run:
            print(json.dumps({
                "dry_run": True,
                "transport": "S3_PRIMARY_NO_BRIDGE",
                "command": "tools/run_storyclaw_s3_autosync.sh",
            }, ensure_ascii=False))
            return 0
        result = subprocess.run(
            [str(Path(args.base).resolve() / "tools/run_storyclaw_s3_autosync.sh")],
            check=False,
        )
        return result.returncode

    if not storyclaw_writes_enabled() and not args.dry_run:
        print(
            json.dumps(
                {
                    "disabled": True,
                    "mode": "LOCAL_CLAUDE_PRIMARY",
                    "uploaded": 0,
                    "failed": 0,
                    "deferred": 0,
                    "remote_request_performed": False,
                },
                ensure_ascii=False,
            )
        )
        return 0

    base = Path(args.base).resolve()
    token = configured_token(args.token_env)
    if not token and not args.dry_run:
        raise SystemExit(f"Missing token env: {args.token_env}")

    state_path = Path(args.state).resolve()
    state = load_state(state_path)
    seen = state.setdefault("files", {})
    changed = []
    for path in iter_files(base, DEFAULT_INCLUDE_ROOTS, args.max_bytes):
        digest = sha256(path)
        rel = path.relative_to(base).as_posix()
        current = seen.get(rel)
        if current and current.get("sha256") == digest and current.get("uploaded_ok"):
            continue
        changed.append((path, rel, digest))

    uploaded = []
    failed = []
    deferred = []
    quota_blocked = retry_is_deferred(state)
    attempted_changed = [] if quota_blocked else changed
    if quota_blocked:
        deferred = [
            {
                "relative_path": rel,
                "bridge_name": encoded_name(path, base),
                "sha256": digest,
                "size": path.stat().st_size,
                "reason": "daily_write_quota_cooldown",
            }
            for path, rel, digest in changed
        ]
    for index, (path, rel, digest) in enumerate(attempted_changed):
        name = encoded_name(path, base)
        response = upload(path, name, args.base_url, token, args.dry_run)
        record = {
            "relative_path": rel,
            "bridge_name": name,
            "sha256": digest,
            "size": path.stat().st_size,
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            "uploaded_ok": bool(response.get("ok")),
            "response": response,
        }
        seen[rel] = record
        (uploaded if record["uploaded_ok"] else failed).append(record)
        if daily_write_quota_exhausted(response):
            quota_blocked = True
            state["write_retry_after_utc"] = next_daily_quota_retry().isoformat()
            deferred = [
                {
                    "relative_path": remaining_rel,
                    "bridge_name": encoded_name(remaining_path, base),
                    "sha256": remaining_digest,
                    "size": remaining_path.stat().st_size,
                    "reason": "daily_write_quota_exhausted",
                }
                for remaining_path, remaining_rel, remaining_digest in changed[index + 1 :]
            ]
            break
        if record["uploaded_ok"]:
            state.pop("write_retry_after_utc", None)

    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    state["write_quota_blocked"] = quota_blocked
    state["deferred_count"] = len(deferred)
    save_state(state_path, state)

    receipt = Path(args.receipt).resolve()
    lines = [
        "# StoryClaw Realtime Sync Receipt",
        "",
        f"Updated: {state['updated_at']}",
        f"Changed files considered: {len(changed)}",
        f"Uploaded OK: {len(uploaded)}",
        f"Failed: {len(failed)}",
        f"Deferred without attempt: {len(deferred)}",
        f"Daily write quota blocked: {quota_blocked}",
        f"Write retry after UTC: {state.get('write_retry_after_utc', '')}",
        "",
        "## Uploaded",
    ]
    for item in uploaded[-80:]:
        lines.append(f"- `{item['relative_path']}` -> `{item['bridge_name']}` ({item['size']} bytes)")
    if failed:
        lines.extend(["", "## Failed"])
        for item in failed:
            lines.append(f"- `{item['relative_path']}`: {item['response'].get('error', 'unknown error')}")
    if deferred:
        lines.extend(["", "## Deferred"])
        for item in deferred:
            lines.append(f"- `{item['relative_path']}`: {item['reason']}")
    receipt.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "uploaded": len(uploaded),
        "failed": len(failed),
        "deferred": len(deferred),
        "write_quota_blocked": quota_blocked,
        "write_retry_after_utc": state.get("write_retry_after_utc"),
        "state": str(state_path),
        "receipt": str(receipt),
    }, ensure_ascii=False))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
