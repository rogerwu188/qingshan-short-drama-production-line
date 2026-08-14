#!/usr/bin/env python3
"""Merge and optionally publish portable BacklotOS LoRA-ready prompt memory."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import fcntl


DATASET_RELATIVE = Path("components/pipeline-tools/local_lora/seedance2_prompt_failure_training.jsonl")
MANIFEST_RELATIVE = Path("components/pipeline-tools/local_lora/seedance2_prompt_memory_manifest.json")
ALLOWED_FIELDS = {
    "schema", "sample_id", "status", "generation_mode", "applicable_modes",
    "failure_evidence", "failed_prompt_sha256", "failed_asset_sha256",
    "root_cause", "optimization", "accepted_evidence", "accepted_prompt_sha256",
    "accepted_asset_sha256", "compiler_guard_clause", "tags", "source_kind",
    "source_url_sha256", "rights_basis", "content_policy",
    "admission_gate", "zero_credit_workaround_evidence", "zero_credit_workaround_sha256",
}
FORBIDDEN_KEY_PARTS = {"token", "secret", "password", "credential", "cookie", "authorization", "api_key"}
DEFAULT_REMOTE = "https://github.com/rogerwu188/backlot-os.git"
AUTO_SYNC_MARKER = Path("config/lora-auto-sync.enabled")
SYNC_RECEIPT = Path("state/lora-sync/latest-sync-receipt.json")
PENDING_DATASET = Path("state/lora-sync/pending-memory.jsonl")
SYNC_LOCK = Path("state/lora-sync/sync.lock")
COLLECTOR_URL_FILE = Path("config/lora-collector-url")


def _run(argv: list[str], cwd: Path, *, timeout: int = 90) -> str:
    completed = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if completed.returncode:
        raise RuntimeError(f"{' '.join(argv)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _install_root() -> Path:
    return Path(os.environ.get("BACKLOT_INSTALL_DIR", Path.home() / ".local/share/backlotos")).expanduser()


def auto_sync_enabled() -> bool:
    override = os.environ.get("BACKLOTOS_LORA_AUTO_SYNC")
    if override is not None:
        return override == "1"
    return (_install_root() / AUTO_SYNC_MARKER).is_file()


def _write_receipt(payload: dict) -> dict:
    receipt = _install_root() / SYNC_RECEIPT
    receipt.parent.mkdir(parents=True, exist_ok=True)
    safe = {
        **payload,
        "schema": "backlotos.local_lora_sync_receipt.v1",
        "machine": socket.gethostname(),
        "updatedUnix": int(time.time()),
    }
    receipt.write_text(json.dumps(safe, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return safe


def _configured_remote() -> str:
    explicit = os.environ.get("BACKLOTOS_LORA_SYNC_REMOTE")
    if explicit:
        return explicit
    origin_file = _install_root() / "source/git-origin"
    if origin_file.is_file() and origin_file.read_text(encoding="utf-8").strip():
        return origin_file.read_text(encoding="utf-8").strip()
    return DEFAULT_REMOTE


def _discover_checkout() -> Path:
    explicit = os.environ.get("BACKLOTOS_LORA_SYNC_CHECKOUT")
    if explicit:
        return Path(explicit).expanduser().resolve()
    cache_checkout = _install_root() / "state/lora-sync/repository"
    if not (cache_checkout / ".git").exists():
        cache_checkout.parent.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--filter=blob:none", _configured_remote(), str(cache_checkout)], cache_checkout.parent)
        _run(["git", "config", "user.name", "BacklotOS Memory Sync"], cache_checkout)
        _run(["git", "config", "user.email", "backlotos-memory-sync@users.noreply.github.com"], cache_checkout)
    return cache_checkout


@contextmanager
def _sync_lock():
    path = _install_root() / SYNC_LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _stage_pending(source: Path) -> Path:
    pending = _install_root() / PENDING_DATASET
    merged = _load(pending)
    # The compiler memory may also contain active defensive rewrites used as
    # local prompt guards. Only ADMITTED rows are training/sync candidates.
    for sample_id, row in _load(source.resolve(), skip_non_admitted=True).items():
        if sample_id in merged and merged[sample_id] != row:
            raise ValueError(f"immutable sample_id conflict in local pending memory: {sample_id}")
        merged[sample_id] = row
    _write_dataset(pending, merged)
    return pending


def _collector_url() -> str:
    explicit = os.environ.get("BACKLOTOS_LORA_COLLECTOR_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    path = _install_root() / COLLECTOR_URL_FILE
    return path.read_text(encoding="utf-8").strip().rstrip("/") if path.is_file() else ""


def upload_to_collector(source: Path) -> dict:
    url = _collector_url()
    if not url:
        raise RuntimeError("LoRA memory collector URL is not configured")
    rows = _load(source)
    canonical_body = "".join(
        json.dumps(rows[key], ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for key in sorted(rows)
    ).encode("utf-8")
    body = json.dumps({
        "schema": "backlotos.lora_memory_submission.v1",
        "datasetSha256": hashlib.sha256(canonical_body).hexdigest(),
        "sourceId": hashlib.sha256(socket.gethostname().encode("utf-8")).hexdigest()[:24],
        "samples": [rows[key] for key in sorted(rows)],
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    token = os.environ.get("BACKLOTOS_LORA_COLLECTOR_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{url}/v1/memory", data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=45) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("status") != "ACCEPTED":
        raise RuntimeError("LoRA memory collector did not accept the submission")
    return result


def _load(path: Path, *, skip_non_admitted: bool = False) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if not path.is_file():
        return rows
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        raw = json.loads(line)
        unknown = set(raw) - ALLOWED_FIELDS
        if unknown:
            raise ValueError(f"line {line_number} contains non-portable fields: {', '.join(sorted(unknown))}")
        if any(any(part in key.lower() for part in FORBIDDEN_KEY_PARTS) for key in raw):
            raise ValueError(f"line {line_number} contains a credential-like field")
        sample_id = str(raw.get("sample_id") or "").strip()
        if raw.get("status") != "ADMITTED" and skip_non_admitted:
            continue
        if not sample_id or raw.get("status") != "ADMITTED":
            raise ValueError(f"line {line_number} must be an ADMITTED sample with sample_id")
        if raw.get("source_kind") == "third_party":
            if raw.get("rights_basis") != "explicit_machine_learning_training_license":
                raise ValueError(
                    f"line {line_number} third-party content lacks an explicit machine-learning training license"
                )
            if raw.get("content_policy") not in {"abstracted_rule_only", "licensed_training_material"}:
                raise ValueError(f"line {line_number} third-party content_policy is not admissible")
            source_url_sha = str(raw.get("source_url_sha256") or "")
            if len(source_url_sha) != 64 or any(ch not in "0123456789abcdef" for ch in source_url_sha.lower()):
                raise ValueError(f"line {line_number} third-party source_url_sha256 is required")
        for evidence_key in ("failure_evidence", "accepted_evidence", "zero_credit_workaround_evidence"):
            evidence = str(raw.get(evidence_key) or "")
            if evidence and not evidence.startswith("redacted://"):
                raise ValueError(f"line {line_number} {evidence_key} must use redacted:// evidence")
        for key, value in raw.items():
            if isinstance(value, str) and (value.startswith("/") or "file://" in value.lower()):
                raise ValueError(f"line {line_number} contains a local path in {key}")
        canonical = json.loads(json.dumps(raw, ensure_ascii=False, sort_keys=True))
        previous = rows.get(sample_id)
        if previous is not None and previous != canonical:
            raise ValueError(f"conflicting duplicate sample_id in {path}: {sample_id}")
        rows[sample_id] = canonical
    return rows


def _write_dataset(path: Path, rows: dict[str, dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(json.dumps(rows[key], ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for key in sorted(rows))
    path.write_text(body, encoding="utf-8")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def synchronize(source: Path, checkout: Path, *, push: bool) -> dict:
    checkout = checkout.resolve()
    if not (checkout / ".git").exists():
        raise ValueError(f"sync checkout is not a Git repository: {checkout}")
    destination = checkout / DATASET_RELATIVE
    if push:
        _run(["git", "pull", "--rebase", "--autostash"], checkout)
    local_rows = _load(source.resolve())
    remote_rows = _load(destination)
    merged = dict(remote_rows)
    for sample_id, row in local_rows.items():
        if sample_id in merged and merged[sample_id] != row:
            raise ValueError(f"immutable sample_id conflict across machines: {sample_id}")
        merged[sample_id] = row
    dataset_sha = _write_dataset(destination, merged)
    manifest_path = checkout / MANIFEST_RELATIVE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    manifest.update({
        "schema": "backlotos.seedance_prompt_memory_manifest.v1",
        "format": "LoRA-ready JSONL plus deterministic compiler retrieval",
        "training_status": "RULE_ADAPTER_ACTIVE_WEIGHT_TRAINING_NOT_CLAIMED",
        "dataset": DATASET_RELATIVE.name,
        "sample_count": len(merged),
        "dataset_sha256": dataset_sha,
        "sync_policy": "PRIVACY_FILTERED_CONTENT_ADDRESSED_GITHUB_CONVERGENCE",
    })
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    changed = bool(_run(["git", "status", "--porcelain", "--", str(DATASET_RELATIVE), str(MANIFEST_RELATIVE)], checkout))
    commit = None
    if push and changed:
        _run(["git", "add", "--", str(DATASET_RELATIVE), str(MANIFEST_RELATIVE)], checkout)
        _run(["git", "commit", "-m", f"sync LoRA prompt memory ({len(merged)} samples)"], checkout)
        commit = _run(["git", "rev-parse", "HEAD"], checkout)
    if push:
        # Retry an earlier committed-but-unpushed memory update even when this
        # invocation added no new rows.
        _run(["git", "push"], checkout)
        commit = commit or _run(["git", "rev-parse", "HEAD"], checkout)
    return {"status": "PASS", "sampleCount": len(merged), "datasetSha256": dataset_sha,
            "changed": changed, "pushed": bool(push and changed), "commit": commit}


def auto_sync(source: Path) -> dict:
    if not auto_sync_enabled():
        return {"status": "DISABLED", "pushed": False}
    # Invalid or private training rows must stop prompt compilation. Operational
    # Git/GitHub failures are queued for the next compile and never hide locally
    # admitted memory from the current machine.
    with _sync_lock():
        pending = _stage_pending(source)
        try:
            mode = os.environ.get("BACKLOTOS_LORA_SYNC_MODE", "collector").strip().lower()
            if mode == "direct-git":
                result = synchronize(pending, _discover_checkout(), push=True)
            elif mode == "collector":
                result = upload_to_collector(pending)
            else:
                raise RuntimeError(f"unsupported LoRA memory sync mode: {mode}")
            return _write_receipt(result)
        except (RuntimeError, subprocess.SubprocessError, OSError, urllib.error.URLError) as exc:
            return _write_receipt({
                "status": "QUEUED_FOR_RETRY",
                "pushed": False,
                "pendingSampleCount": len(_load(pending)),
                "errorType": type(exc).__name__,
                "nextAction": "Retry automatically before the next Seedance prompt compilation; configure the collector URL/token if upload remains unavailable.",
            })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    print(json.dumps(synchronize(args.source, args.checkout, push=args.push), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
