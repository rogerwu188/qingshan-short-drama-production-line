#!/usr/bin/env python3
"""Remove episode-scoped launchctl jobs only after a SHA-verified final lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EPISODE_RE = re.compile(r"^E\d+$")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_final_lock(episode: str, receipt: dict) -> tuple[Path | None, list[str]]:
    failures: list[str] = []
    if not EPISODE_RE.fullmatch(episode):
        failures.append("invalid_episode")
    if str(receipt.get("episode") or "").upper() != episode:
        failures.append("receipt_episode_mismatch")
    if not str(receipt.get("status") or "").startswith("FINAL_LOCKED"):
        failures.append("receipt_not_final_locked")

    final_value = str(receipt.get("final") or "")
    final = Path(final_value).expanduser() if final_value else None
    if final and not final.is_absolute():
        final = ROOT / final
    if not final or not final.is_file():
        failures.append("final_file_missing")
        return final, failures

    expected = str(receipt.get("final_sha256") or "")
    if not expected:
        failures.append("final_sha256_missing")
    elif sha256(final) != expected:
        failures.append("final_sha256_mismatch")
    return final, failures


def matching_labels(episode: str, labels: list[str]) -> list[str]:
    prefix = f"ai.qingshan.{episode.lower()}."
    return sorted(label for label in labels if label.lower().startswith(prefix))


def launchctl_labels() -> list[str]:
    result = subprocess.run(
        ["launchctl", "list"], check=True, capture_output=True, text=True
    )
    labels = []
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) >= 3:
            labels.append(columns[-1])
    return labels


def close_jobs(episode: str, receipt: dict, *, apply: bool) -> dict:
    final, failures = verify_final_lock(episode, receipt)
    labels = launchctl_labels() if not failures else []
    matched = matching_labels(episode, labels)
    removed: list[str] = []
    remove_failures: list[dict] = []
    if apply and not failures:
        for label in matched:
            result = subprocess.run(
                ["launchctl", "remove", label], capture_output=True, text=True
            )
            if result.returncode == 0:
                removed.append(label)
            else:
                remove_failures.append({
                    "label": label,
                    "exit_code": result.returncode,
                    "stderr": result.stderr.strip(),
                })
        remaining = matching_labels(episode, launchctl_labels())
    else:
        remaining = matched

    failures.extend(f"launchctl_remove_failed:{row['label']}" for row in remove_failures)
    return {
        "schema": "qingshan.episode_launch_job_closure.v1",
        "episode": episode,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "status": "PASS" if not failures and (not apply or not remaining) else "FAIL",
        "mode": "APPLY" if apply else "DRY_RUN",
        "final": str(final) if final else None,
        "matched_labels": matched,
        "removed_labels": removed,
        "remaining_labels": remaining,
        "remove_failures": remove_failures,
        "failures": failures,
        "credit_consumption": "NOT_APPLICABLE_LOCAL_PROCESS_CONTROL",
        "policy": "A released episode may not retain restartable generation, retry, or render jobs.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episode", required=True)
    parser.add_argument("--delivery-receipt", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--out")
    args = parser.parse_args()

    episode = args.episode.upper()
    receipt_path = Path(args.delivery_receipt).expanduser()
    if not receipt_path.is_absolute():
        receipt_path = ROOT / receipt_path
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    report = close_jobs(episode, receipt, apply=args.apply)
    report["delivery_receipt"] = str(receipt_path)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        out = Path(args.out).expanduser()
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
