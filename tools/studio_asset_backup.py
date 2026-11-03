#!/usr/bin/env python3
"""Backup and restore for the studio asset library (separate from every other bucket).

Boundaries (requirement doc section 6)
--------------------------------------
* The backup target is configured only through ``STUDIO_ASSET_BACKUP_*`` variables.  It is NOT the
  public-read knowledge bucket and NOT the published-finals relay bucket: a configured bucket that
  equals either of those is refused, and the operator must attest ``STUDIO_ASSET_BACKUP_ACCESS=private``
  (a new key prefix does not make a public-read bucket private).
* Nothing here is configured by default.  With no target the state is ``UNCONFIGURED`` and every
  local feature keeps working; no queue entry is invented and nothing is claimed as backed up.
* The same endpoint and credentials MECHANISM as the existing collective object store is reused
  (``object_store.make_client`` / ``resolve_credentials``); the policy is this module's own.
* Only the standard S3 subset is used (put/get/head/list).  No versioning, object lock or tagging:
  retention is application-level immutable keys + verified receipts.
* Originals go to ``objects/sha256/<2>/<sha>.<ext>`` and are never overwritten: an existing remote
  key with different bytes is a conflict, not an update.  Immutable version manifests follow the same
  rule.  Mutable records (review, binding) are uploaded as content-addressed snapshots, so two devices
  writing different assets never share one big JSON, and two writers of the same version collide
  loudly instead of silently winning.
* Backup is per object, queued durably on disk, run in parallel, resumable.  A network failure leaves
  the queue entry and ``attempts``/``last_error``; it never blocks local work and never triggers a
  regeneration.
* A receipt means: PUT + HEAD (size) + streamed read-back sha256 all matched.  Anything less is not a
  receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Mapping

try:
    from tools import studio_asset_library as core
except ImportError:  # pragma: no cover - flat tools/ on sys.path
    import studio_asset_library as core  # type: ignore[no-redef]

ENV_ENDPOINT = "STUDIO_ASSET_BACKUP_ENDPOINT"
ENV_BUCKET = "STUDIO_ASSET_BACKUP_BUCKET"
ENV_PREFIX = "STUDIO_ASSET_BACKUP_PREFIX"
ENV_REGION = "STUDIO_ASSET_BACKUP_REGION"
ENV_ACCESS = "STUDIO_ASSET_BACKUP_ACCESS"
ENV_PROFILE = "STUDIO_ASSET_BACKUP_PROFILE"
ENV_KEY_ID = "STUDIO_ASSET_BACKUP_ACCESS_KEY_ID"
ENV_SECRET = "STUDIO_ASSET_BACKUP_SECRET_ACCESS_KEY"
#: Buckets that must never double as the asset store: the public-read knowledge bucket (two env
#: spellings in use) and the published-finals relay bucket.
FORBIDDEN_BUCKET_ENVS = ("COLLECTIVE_OBJECT_BUCKET", "S3CTL_BUCKET", "S3_RELAY_BUCKET")
DEFAULT_PREFIX = "studio-assets"

QUEUE_DIR = "backup/queue"
RECEIPT_DIR = "backup/receipts"


def backup_state(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = os.environ if env is None else env
    endpoint = (env.get(ENV_ENDPOINT) or "").strip()
    bucket = (env.get(ENV_BUCKET) or "").strip()
    missing = [name for name, value in ((ENV_ENDPOINT, endpoint), (ENV_BUCKET, bucket)) if not value]
    if missing:
        return {"state": "UNCONFIGURED", "missing_env": missing, "local_features": "FULLY_AVAILABLE",
                "cross_device_restore": "NOT_AVAILABLE_UNTIL_CONFIGURED_AND_RUN"}
    for name in FORBIDDEN_BUCKET_ENVS:
        if bucket and bucket == (env.get(name) or "").strip():
            return {"state": "REFUSED_BUCKET_SHARED_WITH_OTHER_PURPOSE", "conflicts_with_env": name}
    if (env.get(ENV_ACCESS) or "").strip().lower() != "private":
        return {"state": "REFUSED_ACCESS_MODE_NOT_DECLARED_PRIVATE",
                "detail": f"set {ENV_ACCESS}=private only for a bucket that is NOT public-read"}
    prefix = (env.get(ENV_PREFIX) or DEFAULT_PREFIX).strip("/")
    return {"state": "CONFIGURED_PRIVATE_ATTESTED", "endpoint": endpoint.rstrip("/"), "bucket": bucket,
            "prefix": prefix, "region": env.get(ENV_REGION) or "us-east-1",
            "note": "private access is attested by the operator, not verified by this tool"}


def _config(config: Mapping[str, Any] | None) -> dict[str, Any] | None:
    state = dict(config) if config is not None else backup_state()
    if config is not None:  # explicit test/operator config: still must carry bucket + prefix
        state.setdefault("state", "CONFIGURED_PRIVATE_ATTESTED")
        state.setdefault("prefix", DEFAULT_PREFIX)
    return state if state.get("state") == "CONFIGURED_PRIVATE_ATTESTED" else None


def make_client(state: Mapping[str, Any], env: Mapping[str, str] | None = None):
    """boto3 client through the existing object-store transport (credentials from the environment)."""
    env = dict(os.environ if env is None else env)
    root = str(core.REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    from tools.collective_learning import object_store as osm  # noqa: PLC0415

    mapped = dict(env)
    if env.get(ENV_KEY_ID) and env.get(ENV_SECRET):
        mapped[osm.ENV_ACCESS_KEY], mapped[osm.ENV_SECRET_KEY] = env[ENV_KEY_ID], env[ENV_SECRET]
    config = osm.ObjectStoreConfig(endpoint_url=str(state["endpoint"]), bucket=str(state["bucket"]),
                                   region=str(state.get("region") or "us-east-1"), public_read=False)
    return osm.make_client(config, osm.resolve_credentials(mapped, env.get(ENV_PROFILE) or None))


def _is_missing(exc: BaseException) -> bool:
    response = getattr(exc, "response", None) or {}
    code = str((response.get("Error", {}) if isinstance(response, dict) else {}).get("Code") or "")
    return code in ("404", "NoSuchKey", "NotFound")


def _stream_sha(client: Any, bucket: str, key: str) -> tuple[str, int]:
    body = client.get_object(Bucket=bucket, Key=key)["Body"]
    digest, size = hashlib.sha256(), 0
    try:
        for chunk in iter(lambda: body.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    finally:
        body.close()
    return digest.hexdigest(), size


# --------------------------------------------------------------------------- #
# keys and queue (local, per object, durable)
# --------------------------------------------------------------------------- #
def object_key(prefix: str, sha: str, ext: str) -> str:
    return f"{prefix}/objects/sha256/{sha[:2]}/{sha}.{ext}"


def _queue_path(lib: core.Library, name: str) -> Path:
    return lib.root / QUEUE_DIR / f"{name}.json"


def _receipt_path(lib: core.Library, name: str) -> Path:
    return lib.root / RECEIPT_DIR / f"{name}.json"


def _write_queue(lib: core.Library, name: str, item: dict[str, Any]) -> None:
    path = _queue_path(lib, name)
    if path.exists() or _receipt_path(lib, name).exists():
        return
    core.atomic_write_json(path, {**item, "attempts": 0, "last_error": None, "queued_at": core.utc_now()})


def enqueue_object(lib: core.Library, sha: str, *, env: Mapping[str, str] | None = None) -> str:
    """Durable per-object backup todo.  No-op (and honest) when no backup target is configured."""
    if backup_state(env).get("state") != "CONFIGURED_PRIVATE_ATTESTED":
        return "UNCONFIGURED"
    _write_queue(lib, sha, {"kind": "object", "sha256": sha})
    return "QUEUED"


def enqueue_catalog_file(lib: core.Library, path: Path, *, snapshot: bool = False) -> str:
    if backup_state().get("state") != "CONFIGURED_PRIVATE_ATTESTED":
        return "UNCONFIGURED"
    return _enqueue_catalog(lib, path, snapshot)


def _enqueue_catalog(lib: core.Library, path: Path, snapshot: bool) -> str:
    path = Path(path)
    if not path.is_file():
        return "NO_FILE"
    rel = path.relative_to(lib.catalog).as_posix()
    data = path.read_bytes()
    content = core.sha256_bytes(data)
    if snapshot:
        key_suffix = f"catalog/snapshots/{re.sub(r'[.]json$', '', rel)}/{content}.json"
    else:
        key_suffix = f"catalog/{rel}"
    name = "cat_" + core.sha256_bytes(key_suffix.encode("utf-8"))[:40]
    _write_queue(lib, name, {"kind": "catalog_snapshot" if snapshot else "catalog_immutable",
                             "local_rel": rel, "key_suffix": key_suffix, "sha256": content})
    return "QUEUED"


def pending_catalog_count(lib: core.Library) -> int:
    base = lib.root / QUEUE_DIR
    return len(list(base.glob("cat_*.json"))) if base.is_dir() else 0


def object_storage_state(lib: core.Library, sha: str) -> str:
    local = lib.find_object(sha) is not None
    receipt = core.read_json(_receipt_path(lib, sha))
    verified = bool(receipt and receipt.get("status") == "VERIFIED" and receipt.get("content_sha256") == sha)
    queued = _queue_path(lib, sha).is_file()
    if local and verified:
        return "LOCAL_BACKUP_VERIFIED"
    if local and queued:
        return "LOCAL_BACKUP_PENDING"
    if local and backup_state().get("state") != "CONFIGURED_PRIVATE_ATTESTED":
        return "LOCAL_ONLY_BACKUP_UNCONFIGURED"
    if local:
        return "LOCAL_BACKUP_NOT_QUEUED"
    return "LOCAL_MISSING_BACKUP_VERIFIED" if verified else "LOCAL_MISSING_NO_VERIFIED_BACKUP"


def enqueue_all(lib: core.Library) -> dict[str, Any]:
    """Admin: queue every object and catalog file (use after configuring a target on an existing library)."""
    if backup_state().get("state") != "CONFIGURED_PRIVATE_ATTESTED":
        return {"status": "UNCONFIGURED", "queued": 0}
    queued = 0
    for record_file in sorted((lib.catalog / "objects").glob("*/*.json")):
        sha = (core.read_json(record_file) or {}).get("content_sha256")
        if sha:
            _write_queue(lib, sha, {"kind": "object", "sha256": sha})
            queued += 1
    for pattern, snapshot in (("assets/*/v????.json", False), ("assets/*/v????.review.json", True),
                              ("bindings/*/*.json", True)):
        for path in sorted(lib.catalog.glob(pattern)):
            _enqueue_catalog(lib, path, snapshot)
            queued += 1
    return {"status": "QUEUED", "queued": queued}


def status_report(lib: core.Library) -> dict[str, Any]:
    base = lib.root / QUEUE_DIR
    items = [core.read_json(p) or {} for p in sorted(base.glob("*.json"))] if base.is_dir() else []
    receipts = len(list((lib.root / RECEIPT_DIR).glob("*.json")))
    objects = len(list((lib.catalog / "objects").glob("*/*.json")))
    return {"backup": backup_state(), "objects_in_library": objects, "queued": len(items),
            "queued_objects": sum(1 for i in items if i.get("kind") == "object"),
            "queued_catalog_files": sum(1 for i in items if str(i.get("kind", "")).startswith("catalog")),
            "failing": [{"name": i.get("sha256", "")[:12], "attempts": i.get("attempts"), "last_error": i.get("last_error")}
                        for i in items if i.get("last_error")],
            "verified_receipts": receipts,
            "cross_device_restore": "NOT_VERIFIED_BY_THIS_REPORT"}


# --------------------------------------------------------------------------- #
# run (upload + verify), parallel per item
# --------------------------------------------------------------------------- #
def _upload_one(lib: core.Library, client: Any, state: Mapping[str, Any], name: str) -> dict[str, Any]:
    item = core.read_json(_queue_path(lib, name)) or {}
    bucket, prefix = str(state["bucket"]), str(state.get("prefix") or DEFAULT_PREFIX)
    try:
        if item["kind"] == "object":
            sha = item["sha256"]
            path, local_state = lib.verify_object(sha)
            if local_state != "OK" or path is None:
                raise RuntimeError(f"LOCAL_OBJECT_{local_state}_NOT_UPLOADED")
            ext = path.suffix.lstrip(".")
            key, data, ctype = object_key(prefix, sha, ext), path.read_bytes(), core.MEDIA_TYPES.get(ext, "application/octet-stream")
            expected = sha
        else:
            local = lib.catalog / item["local_rel"]
            data = local.read_bytes()
            expected = core.sha256_bytes(data)
            if item.get("sha256") and expected != item["sha256"] and item["kind"] == "catalog_snapshot":
                # the mutable record moved after queueing: the snapshot key is content-addressed, so queue the new content
                _enqueue_catalog(lib, local, True)
                _queue_path(lib, name).unlink(missing_ok=True)
                return {"name": name, "status": "REQUEUED_CONTENT_CHANGED"}
            key, ctype = f"{prefix}/{item['key_suffix']}", "application/json"
        try:
            head = client.head_object(Bucket=bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            if not _is_missing(exc):
                raise
            head = None
        if head is not None:
            remote_sha, remote_size = _stream_sha(client, bucket, key)
            if remote_sha != expected:  # never overwrite an immutable key with different bytes
                raise RuntimeError("REMOTE_KEY_CONFLICT_DIFFERENT_BYTES_NOT_OVERWRITTEN")
        else:
            client.put_object(Bucket=bucket, Key=key, Body=data, ContentLength=len(data), ContentType=ctype)
            head = client.head_object(Bucket=bucket, Key=key)
            if int(head.get("ContentLength", -1)) != len(data):
                raise RuntimeError("HEAD_SIZE_MISMATCH_AFTER_PUT")
            remote_sha, remote_size = _stream_sha(client, bucket, key)
            if remote_sha != expected or remote_size != len(data):
                raise RuntimeError("READBACK_SHA256_MISMATCH_AFTER_PUT")
        core.atomic_write_json(_receipt_path(lib, name), {
            "schema": "qingshan.studio_asset_backup_receipt.v1", "status": "VERIFIED",
            "kind": item["kind"], "content_sha256": expected, "bytes": len(data), "bucket": bucket, "key": key,
            "method": "PUT+HEAD_SIZE+READBACK_SHA256", "verified_at": core.utc_now()})
        _queue_path(lib, name).unlink(missing_ok=True)
        return {"name": name, "status": "VERIFIED"}
    except Exception as exc:  # noqa: BLE001 - keep the todo, record why (class only: no secrets in logs)
        item["attempts"] = int(item.get("attempts") or 0) + 1
        item["last_error"] = f"{type(exc).__name__}:{str(exc)[:120]}"
        if _queue_path(lib, name).exists():
            core.atomic_write_json(_queue_path(lib, name), item)
        return {"name": name, "status": "FAILED_KEPT_QUEUED", "error": item["last_error"]}


def run(lib: core.Library, *, client: Any = None, config: Mapping[str, Any] | None = None,
        limit: int | None = None, workers: int = 4) -> dict[str, Any]:
    state = _config(config)
    if state is None:
        return {"status": "UNCONFIGURED", "detail": backup_state() if config is None else dict(config),
                "queued_kept": len(list((lib.root / QUEUE_DIR).glob("*.json"))),
                "claim": "NOTHING_BACKED_UP"}
    names = sorted(p.stem for p in (lib.root / QUEUE_DIR).glob("*.json"))
    if limit:
        names = names[:limit]
    if not names:
        return {"status": "NOTHING_QUEUED", "claim": "NO_NEW_UPLOADS"}
    client = client or make_client(state)
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(names)))) as pool:
        results = list(pool.map(lambda n: _upload_one(lib, client, state, n), names))
    failed = [r for r in results if r["status"].startswith("FAILED")]
    return {"status": "DONE" if not failed else "PARTIAL_FAILURES_KEPT_QUEUED",
            "verified": sum(r["status"] == "VERIFIED" for r in results), "failed": failed,
            "requeued": sum(r["status"] == "REQUEUED_CONTENT_CHANGED" for r in results)}


# --------------------------------------------------------------------------- #
# restore: accept only bytes that match the expected sha
# --------------------------------------------------------------------------- #
def restore_object(lib: core.Library, sha: str | None, *, client: Any = None,
                   config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if not core.is_sha256(sha):
        return {"status": "SHA_INVALID"}
    state = _config(config)
    if state is None:
        return {"status": "UNCONFIGURED", "content_sha256": sha, "claim": "NOTHING_RESTORED"}
    bucket, prefix = str(state["bucket"]), str(state.get("prefix") or DEFAULT_PREFIX)
    client = client or make_client(state)
    record = lib.object_record(sha) or {}
    ext = record.get("ext")
    if not ext:  # fresh device before the catalog is restored: look the key up by sha prefix
        listing = client.list_objects_v2(Bucket=bucket, Prefix=f"{prefix}/objects/sha256/{sha[:2]}/{sha}.")
        keys = [row["Key"] for row in listing.get("Contents", [])]
        if not keys:
            return {"status": "NOT_IN_BACKUP", "content_sha256": sha}
        ext = keys[0].rsplit(".", 1)[-1]
    key = object_key(prefix, sha, ext)
    try:
        body = client.get_object(Bucket=bucket, Key=key)["Body"]
    except Exception as exc:  # noqa: BLE001
        return {"status": "NOT_IN_BACKUP" if _is_missing(exc) else "BACKUP_UNREACHABLE", "content_sha256": sha,
                "error": type(exc).__name__}
    lib.tmp_dir.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(dir=lib.tmp_dir, prefix="restore-", suffix=".part", delete=False)
    tmp = Path(handle.name)
    digest, size = hashlib.sha256(), 0
    try:
        with handle:
            try:
                for chunk in iter(lambda: body.read(1 << 20), b""):
                    digest.update(chunk)
                    size += len(chunk)
                    handle.write(chunk)
            finally:
                body.close()
        if digest.hexdigest() != sha or (record.get("bytes") not in (None, size)):
            core.atomic_write_json(lib.root / "backup" / "restore_requests" / f"{sha}.rejected.json", {
                "content_sha256": sha, "rejected_at": core.utc_now(), "reason": "BACKUP_BYTES_DO_NOT_MATCH_EXPECTED_SHA256",
                "got_sha256": digest.hexdigest()})
            return {"status": "REJECTED_SHA_MISMATCH", "content_sha256": sha}
        with lib.lock(f"obj:{sha}"):
            existing = lib.find_object(sha)
            if existing is not None:
                existing.unlink()
            final = lib.object_dir(sha) / f"{sha}.{ext}"
            final.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(tmp, 0o444)
            os.replace(tmp, final)
            core._fsync_dir(final.parent)
            lib._merge_object_record(sha, ext, size, {"kind": "RESTORED_FROM_VERIFIED_BACKUP"})
        (lib.root / "backup" / "restore_requests" / f"{sha}.json").unlink(missing_ok=True)
        return {"status": "RESTORED", "content_sha256": sha, "bytes": size}
    finally:
        tmp.unlink(missing_ok=True)


def restore_catalog(lib: core.Library, *, client: Any = None, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Rebuild the local catalog from the backed-up immutable manifests and snapshots.  A local file that
    differs from the remote one is reported as a conflict and left untouched."""
    state = _config(config)
    if state is None:
        return {"status": "UNCONFIGURED", "claim": "NOTHING_RESTORED"}
    bucket, prefix = str(state["bucket"]), str(state.get("prefix") or DEFAULT_PREFIX)
    client = client or make_client(state)

    def keys(sub: str) -> list[str]:
        out, token = [], None
        while True:
            kwargs = {"Bucket": bucket, "Prefix": f"{prefix}/{sub}"}
            if token:
                kwargs["ContinuationToken"] = token
            page = client.list_objects_v2(**kwargs)
            out.extend(row["Key"] for row in page.get("Contents", []))
            if not page.get("IsTruncated"):
                return out
            token = page.get("NextContinuationToken")

    def fetch(key: str) -> bytes:
        body = client.get_object(Bucket=bucket, Key=key)["Body"]
        try:
            return body.read()
        finally:
            body.close()

    report: dict[str, Any] = {"versions_restored": 0, "versions_present": 0, "conflicts": [], "rejected": [],
                              "reviews_restored": 0, "bindings_restored": 0}
    for key in keys("catalog/assets/"):
        match = re.search(r"catalog/assets/([^/]+)/v(\d{4})\.json$", key)
        if not match:
            continue
        data = fetch(key)
        try:
            manifest = json.loads(data)
            valid = (manifest["schema"] == core.SCHEMA_VERSION and manifest["asset_id"] == match.group(1)
                     and manifest["version"] == int(match.group(2))
                     and core.Library.content_set_sha(manifest["category"], manifest["artifacts"]) == manifest["content_set_sha256"])
        except (ValueError, KeyError, TypeError):
            valid = False
        if not valid:
            report["rejected"].append(key)
            continue
        local = lib.version_path(manifest["asset_id"], manifest["version"])
        if local.is_file():
            if core.canonical(core.read_json(local)) == core.canonical(manifest):
                report["versions_present"] += 1
            else:
                report["conflicts"].append(f"{manifest['asset_id']}@v{manifest['version']}")
            continue
        core.atomic_write_json(local, manifest)
        for artifact in manifest["artifacts"]:
            sha = artifact["content_sha256"]
            if lib.object_record(sha) is None:
                core.atomic_write_json(lib.object_record_path(sha), {
                    "schema": core.SCHEMA_OBJECT, "content_sha256": sha, "bytes": artifact["bytes"],
                    "ext": artifact["object_key"].rsplit(".", 1)[-1], "media_type": artifact["media_type"],
                    "width": artifact.get("width"), "height": artifact.get("height"),
                    "object_key": artifact["object_key"], "first_seen_at": core.utc_now(),
                    "origins": [manifest.get("origin") or {}], "restored_from_catalog": True})
        report["versions_restored"] += 1
    best: dict[str, dict[str, Any]] = {}
    for key in keys("catalog/snapshots/"):
        match = re.search(r"catalog/snapshots/((?:assets/[^/]+/v\d{4}\.review)|(?:bindings/[^/]+/[^/]+))/([0-9a-f]{64})\.json$", key)
        if not match:
            continue
        data = fetch(key)
        if core.sha256_bytes(data) != match.group(2):
            report["rejected"].append(key)
            continue
        record = json.loads(data)
        rank = (len(record.get("history") or []), str(record.get("updated_at") or ""))
        if match.group(1) not in best or rank > best[match.group(1)]["rank"]:
            best[match.group(1)] = {"rank": rank, "record": record}
    for rel, chosen in best.items():
        local = lib.catalog / f"{rel}.json"
        current = core.read_json(local)
        if current is None or (len(current.get("history") or []), str(current.get("updated_at") or "")) < chosen["rank"]:
            core.atomic_write_json(local, chosen["record"])
            report["reviews_restored" if rel.startswith("assets/") else "bindings_restored"] += 1
            if rel.startswith("bindings/"):
                rec = chosen["record"]
                core.atomic_write_json(lib.catalog / "used_by" / rec["asset_id"] / f"{rec['project_id']}__{rec['kind']}__{rec['role_id']}.json",
                                       {"asset_id": rec["asset_id"], "version": rec["version"], "project_id": rec["project_id"],
                                        "kind": rec["kind"], "role_id": rec["role_id"], "bound_at": rec.get("bound_at")})
    report["status"] = "RESTORED_CATALOG" if not (report["conflicts"] or report["rejected"]) else "RESTORED_WITH_CONFLICTS"
    report["objects_note"] = "originals are fetched per object with `backup restore --sha256` (sha-checked)"
    return report
