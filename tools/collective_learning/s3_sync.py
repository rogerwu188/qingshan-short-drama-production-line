"""Collective learning over the shared object store: the bucket IS the cloud.

Line owner 2026-10-29: no separate HTTP host.  Devices and the collector only ever
talk to the S3-compatible bucket (``object_store.ObjectStore``); the relational
service (``service.Service``) runs wherever the collector runs and ingests what the
devices dropped into the bucket.  Nothing on a production path waits for the
network: ``device-sync`` and ``collect`` are operator / cron commands, S1 reads the
local bundle cache only.

Key layout (``object_store.object_key`` → line ``collective``, batch = tenant id)::

    collective/<tenant>/trust.json                                  publisher public keys
    collective/<tenant>/revocations.json                            signed revocation list
    collective/<tenant>/inbox/<line>/<device>/<kind>/<batch>.json   device uploads (durable)
    collective/<tenant>/acks/<line>/<device>/<batch>.json           collector acknowledgements
    collective/<tenant>/processed/<line>/<device>/<kind>/<batch>.json
    collective/<tenant>/quarantine/<line>/<device>/<kind>/<batch>.json
    collective/<tenant>/bundles/<bundle_id>/<version>.json          signed bundle envelopes (immutable)
    collective/<tenant>/channels/<CANARY|RELEASED>.json             signed channel pointer

The bucket is public-read: every object goes through ``ObjectStore.put_artifact``
(preflight receipt + ``contracts.sensitive_findings`` on the JSON); items that
carry sensitive text are acknowledged REJECTED and never uploaded.  Credentials
are read from the environment only.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
import plistlib
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping

if __package__ in (None, ""):  # allow `python tools/collective_learning/s3_sync.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "tools.collective_learning"  # noqa: A001

from . import bundles as b  # noqa: E402
from . import contracts as c  # noqa: E402
from . import device_store as ds  # noqa: E402
from . import object_store as osm  # noqa: E402
from . import service as svc_mod  # noqa: E402
from . import sync_client as sc  # noqa: E402

SERVICE_LINE = osm.SERVICE_LINE  # "collective"
BATCH_SCHEMA = "collective.s3_batch.v1"
ACK_SCHEMA = "collective.s3_ack.v1"
POINTER_SCHEMA = "collective.channel_pointer.v1"
POINTER_SIGNING_DOMAIN = b"collective-channel-pointer:"
KIND_BY_PATH = {path: (kind, key) for kind, (path, key) in sc.ROUTE_BY_KIND.items()}
INGEST_BY_KIND = {"EVENT": "ingest_events", "REVIEW": "ingest_reviews",
                  "ADOPTION": "ingest_adoptions", "EVALUATION": "ingest_evaluations"}
COLLECTIVE_DIR = "runtime/collective"
PUBLISHER_KEY_FILE = "publisher.key.json"
TRUST_FILE = "trust.json"
DB_FILE = "collective.sqlite"
ADMIN_TOKEN_FILE = "admin.token"
PREFLIGHT_FILE = "S3_PREFLIGHT_collective.json"
ENV_FILE = "env"
STATUS_FILE = "status.json"
LOCK_FILE = "collector.lock"
LOG_DIR = "logs"
AGENT_LABEL = "com.nalu.collective-collector"
DEFAULT_INTERVAL_S = 300
REQUIRED_ENV = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "S3CTL_ENDPOINT_URL", "S3CTL_BUCKET",
                "S3CTL_PUBLIC_BASE_URL")


# --------------------------------------------------------------------------- keys
def tenant_key(tenant_id: str, artifact: str) -> str:
    return osm.object_key(SERVICE_LINE, tenant_id, artifact)


def _seg(value: str) -> str:
    return osm.normalize_segment(value, what="key segment")


def inbox_prefix(tenant_id: str, line_id: str | None = None, device_id: str | None = None) -> str:
    parts = ["inbox"]
    if line_id:
        parts.append(_seg(line_id))
        if device_id:
            parts.append(_seg(device_id))
    return tenant_key(tenant_id, "/".join(parts)) + "/"


def _json_bytes(doc: Any) -> bytes:
    return (json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


# --------------------------------------------------------------------------- device side
class S3Transport:
    """``sync_client.Transport`` over the bucket.  A POST batch becomes one durable inbox
    object; the ack is ``CREATED`` with ``stage: ACCEPTED_TO_INBOX`` (the service's own
    CREATED/DUPLICATE/CONFLICT verdict follows in the collector's ack object)."""

    def __init__(self, store: osm.ObjectStore, *, tenant_id: str, line_id: str, device_id: str):
        self.store = store
        self.tenant_id, self.line_id, self.device_id = tenant_id, line_id, device_id

    # -- helpers --------------------------------------------------------------
    def _key(self, artifact: str) -> str:
        return tenant_key(self.tenant_id, artifact)

    def _read_json(self, key: str) -> Any | None:
        try:
            return json.loads(self.store.get_bytes(key).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            if osm.is_not_found(exc):
                return None
            raise sc.TransportError(f"{type(exc).__name__}:{str(exc)[:200]}") from exc

    def request(self, method: str, path: str, body: Any | None = None,
                headers: dict[str, str] | None = None) -> tuple[int, Any, dict[str, str]]:
        try:
            if method == "POST" and path in KIND_BY_PATH:
                return self._upload_batch(path, body or {})
            if method == "POST" and path == "/v1/bundles:resolve":
                return self._resolve(body or {})
            if method == "GET" and path.startswith("/v1/bundles/"):
                return self._get_bundle(path)
            if method == "GET" and path == "/v1/sync-status":
                return 200, self.sync_status(), {}
            if method == "GET" and path.startswith("/v1/failures"):
                return 200, self.failures(), {}
        except sc.TransportError:
            raise
        except osm.UploadRefused as exc:
            return 400, {"error": {"code": exc.code, "message": str(exc)[:300]}}, {}
        except Exception as exc:  # noqa: BLE001 -- bucket unreachable: retry later, never crash the host
            raise sc.TransportError(f"{type(exc).__name__}:{str(exc)[:200]}") from exc
        return 404, {"error": {"code": "ROUTE_UNKNOWN", "message": path}}, {}

    def _upload_batch(self, path: str, body: dict[str, Any]) -> tuple[int, Any, dict[str, str]]:
        kind, key_name = KIND_BY_PATH[path]
        items = body.get(key_name)
        if not isinstance(items, list):
            return 400, {"error": {"code": "PAYLOAD_INVALID", "message": f"{key_name} must be a list"}}, {}
        id_field = {"EVENT": "event_id", "REVIEW": "review_id", "ADOPTION": "receipt_id",
                    "EVALUATION": "receipt_id"}[kind]
        clean, results = [], []
        for item in items:
            item_id = item.get(id_field) if isinstance(item, dict) else None
            findings = c.sensitive_findings(item) if isinstance(item, dict) else ["ITEM_NOT_OBJECT"]
            if findings:
                results.append({"id": item_id, "status": "REJECTED", "codes": findings[:8],
                                "stage": "REFUSED_BEFORE_UPLOAD_PUBLIC_BUCKET"})
            else:
                clean.append(item)
        key = None
        if clean:
            batch_id = c.digest([self.tenant_id, self.line_id, self.device_id, kind, [i.get(id_field) for i in clean],
                                 [c.digest(i) for i in clean]])
            doc = {"schema": BATCH_SCHEMA, "tenant_id": self.tenant_id, "line_id": self.line_id,
                   "device_id": self.device_id, "kind": kind, "items_key": key_name, "batch_id": batch_id,
                   "item_count": len(clean), "items": clean, "uploaded_at": c.now_iso()}
            key = self._key(f"inbox/{_seg(self.line_id)}/{_seg(self.device_id)}/{_seg(kind)}/{batch_id}.json")
            self.store.put_artifact(self.tenant_id, key.split("/", 2)[2], _json_bytes(doc),
                                    content_type="application/json",
                                    metadata={"kind": kind, "batch_id": batch_id})
            for item in clean:
                results.append({"id": item.get(id_field), "status": "CREATED", "stage": "ACCEPTED_TO_INBOX",
                                "key": key, "batch_id": batch_id})
        return 200, {"results": results, "inbox_key": key}, {}

    # -- bundles (same shapes as the HTTP service, so SyncClient.pull_bundles works) ---
    def _resolve(self, body: dict[str, Any]) -> tuple[int, Any, dict[str, str]]:
        channels = list(body.get("channels") or ["RELEASED"])
        out: list[dict[str, Any]] = []
        for channel in channels:
            pointer = self._read_json(self._key(f"channels/{_seg(channel)}.json"))
            if not pointer:
                continue
            for bundle_id, ref in ((pointer.get("body") or {}).get("bundles") or {}).items():
                out.append({"bundle_id": bundle_id, "version": str(ref["version"]), "digest": ref["payload_sha256"],
                            "release_channel": channel})
        return 200, {"bundles": out, "source": "S3_CHANNEL_POINTER"}, {}

    def _get_bundle(self, path: str) -> tuple[int, Any, dict[str, str]]:
        parts = path.strip("/").split("/")  # v1 bundles <id> versions <v>
        if len(parts) != 5:
            return 404, {"error": {"code": "ROUTE_UNKNOWN", "message": path}}, {}
        bundle_id, version = parts[2], parts[4]
        try:
            raw = self.store.get_bytes(self._key(f"bundles/{_seg(bundle_id)}/{_seg(version)}.json"))
        except Exception as exc:  # noqa: BLE001
            if osm.is_not_found(exc):
                return 404, {"error": {"code": "BUNDLE_NOT_FOUND", "message": f"{bundle_id}@{version}"}}, {}
            raise
        envelope = json.loads(raw.decode("utf-8"))
        return 200, {"bundle_id": bundle_id, "version": version, "digest": c.sha256_bytes(raw),
                     "payload_b64": base64.b64encode(raw).decode("ascii"),
                     "signature_b64": (envelope.get("signature") or {}).get("value_b64"),
                     "key_id": (envelope.get("signature") or {}).get("key_id"),
                     "manifest": {"scope": (envelope.get("bundle") or {}).get("compat") or {}}}, {}

    # -- status ---------------------------------------------------------------
    def sync_status(self) -> dict[str, Any]:
        prefix = self._key(f"acks/{_seg(self.line_id)}/{_seg(self.device_id)}") + "/"
        pending = self.store.list(inbox_prefix(self.tenant_id, self.line_id, self.device_id))
        acks = self.store.list(prefix)
        accepted = rejected = 0
        for row in acks:
            doc = self._read_json(row["key"]) or {}
            for r in doc.get("results") or []:
                if r.get("status") in sc.DELIVERED_STATUSES:
                    accepted += 1
                elif r.get("status") in sc.QUARANTINE_STATUSES:
                    rejected += 1
        return {"device_id": self.device_id, "line_id": self.line_id, "inbox_pending_batches": len(pending),
                "acked_batches": len(acks), "accepted": accepted, "rejected": rejected}

    def failures(self) -> dict[str, Any]:
        rows = self.store.list(self._key(f"quarantine/{_seg(self.line_id)}/{_seg(self.device_id)}") + "/")
        return {"quarantined_batches": [r["key"] for r in rows]}


class S3Channel:
    """Signed channel pointers in the bucket; publish on the collector side, resolve on devices."""

    def __init__(self, store: osm.ObjectStore, *, tenant_id: str):
        self.store = store
        self.tenant_id = tenant_id

    def _key(self, artifact: str) -> str:
        return tenant_key(self.tenant_id, artifact)

    def put_json(self, artifact: str, doc: Any) -> dict[str, Any]:
        return self.store.put_artifact(self.tenant_id, artifact, _json_bytes(doc), content_type="application/json")

    def get_json(self, artifact: str) -> Any | None:
        try:
            return json.loads(self.store.get_bytes(self._key(artifact)).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            if osm.is_not_found(exc):
                return None
            raise

    # -- publisher side -------------------------------------------------------
    def publish_trust(self, trust: dict[str, Any]) -> dict[str, Any]:
        return self.put_json("trust.json", trust)

    def publish_revocations(self, signed: dict[str, Any]) -> dict[str, Any]:
        return self.put_json("revocations.json", signed)

    def publish(self, channel: str, *, bundle_id: str, version: str, bundle_digest: str, payload_sha256: str,
                key_id: str, private_raw: bytes) -> dict[str, Any]:
        """Move the channel pointer for ``bundle_id`` to ``version`` (other bundle ids untouched)."""
        if channel not in b.CHANNELS:
            raise b.BundleError([f"CHANNEL_INVALID:{channel}"])
        current = self.get_json(f"channels/{_seg(channel)}.json") or {}
        body_prev = current.get("body") or {}
        entries = dict(body_prev.get("bundles") or {})
        entries[bundle_id] = {"version": str(version), "digest": bundle_digest, "payload_sha256": payload_sha256}
        body = {"schema": POINTER_SCHEMA, "tenant_id": self.tenant_id, "channel": channel,
                "sequence": int(body_prev.get("sequence") or 0) + 1, "published_at": c.now_iso(),
                "bundles": entries}
        digest = c.digest(body)
        pointer = {"body": body, "digest": digest,
                   "signature": {"key_id": key_id, "algorithm": "Ed25519",
                                 "value_b64": b._sign(private_raw, POINTER_SIGNING_DOMAIN + digest.encode("ascii"))}}
        put = self.put_json(f"channels/{_seg(channel)}.json", pointer)
        return {"channel": channel, "sequence": body["sequence"], "bundles": entries, "key": put["key"],
                "public_url": put.get("public_url")}

    # -- device side ----------------------------------------------------------
    @staticmethod
    def verify_pointer(pointer: Any, trust: dict[str, Any]) -> dict[str, Any]:
        body = (pointer or {}).get("body") if isinstance(pointer, dict) else None
        if not isinstance(body, dict) or body.get("schema") != POINTER_SCHEMA:
            raise b.BundleError(["CHANNEL_POINTER_INVALID"])
        digest = c.digest(body)
        if digest != pointer.get("digest"):
            raise b.BundleError([f"CHANNEL_POINTER_DIGEST_MISMATCH:declared={pointer.get('digest')}:actual={digest}"])
        failures = b._check_signer(trust, pointer.get("signature") or {}, b.KNOWLEDGE_PUBLISHER,
                                   POINTER_SIGNING_DOMAIN + digest.encode("ascii"))
        if failures:
            raise b.BundleError(failures)
        return body

    def fetch_into_cache(self, cache: b.BundleCache, trust: dict[str, Any], *, channel: str = "RELEASED") -> dict[str, Any]:
        """Verify the pointer, fetch every listed envelope, admit into the cache (verified)."""
        pointer = self.get_json(f"channels/{_seg(channel)}.json")
        if pointer is None:
            return {"status": "NO_POINTER", "channel": channel, "fetched": []}
        body = self.verify_pointer(pointer, trust)
        fetched = []
        for bundle_id, ref in (body.get("bundles") or {}).items():
            key = self._key(f"bundles/{_seg(bundle_id)}/{_seg(str(ref['version']))}.json")
            try:
                raw = self.store.get_bytes(key)
            except Exception as exc:  # noqa: BLE001
                fetched.append({"bundle_id": bundle_id, "version": ref["version"], "status": "FETCH_FAILED",
                                "error": f"{type(exc).__name__}"})
                continue
            if c.sha256_bytes(raw) != ref.get("payload_sha256"):
                fetched.append({"bundle_id": bundle_id, "version": ref["version"], "status": "PAYLOAD_SHA_MISMATCH"})
                continue
            try:
                entry = cache.admit(raw, source=f"s3:{key}")
            except b.BundleError as exc:
                fetched.append({"bundle_id": bundle_id, "version": ref["version"], "status": "REJECTED",
                                "codes": exc.codes})
                continue
            if entry["digest"] != ref.get("digest"):
                fetched.append({"bundle_id": bundle_id, "version": ref["version"], "status": "DIGEST_MISMATCH_WITH_POINTER"})
                continue
            fetched.append({"bundle_id": bundle_id, "version": ref["version"], "digest": entry["digest"],
                            "status": "FETCHED"})
        return {"status": "OK", "channel": channel, "sequence": body.get("sequence"), "fetched": fetched}

    def revoked_digests(self, trust: dict[str, Any]) -> set[str]:
        signed = self.get_json("revocations.json")
        return b.verify_revocations(signed, trust) if signed else set()

    def resolve(self, capabilities: dict[str, Any], cache: b.BundleCache, trust: dict[str, Any], *,
                channel: str = "RELEASED", baseline: dict[str, Any] | None = None) -> dict[str, Any]:
        """Fetch what the pointer lists, then resolve exactly like ``bundles.resolve_local``."""
        accepted = b.CHANNEL_ACCEPTS.get(channel)
        if accepted is None:
            raise b.BundleError([f"CHANNEL_INVALID:{channel}"])
        pulls = [self.fetch_into_cache(cache, trust, channel=ch) for ch in sorted(accepted)]
        revoked = self.revoked_digests(trust)
        resolved = b.resolve_local(capabilities, cache, channel=channel, revoked=revoked, baseline=baseline)
        resolved["s3_pull"] = pulls
        return resolved


# --------------------------------------------------------------------------- collector side
class Collector:
    """Ingest inbox objects through the service; ack; move to processed/ or quarantine/."""

    def __init__(self, service: svc_mod.Service, store: osm.ObjectStore, *, tenant_id: str):
        self.service, self.store, self.tenant_id = service, store, tenant_id

    def _key(self, artifact: str) -> str:
        return tenant_key(self.tenant_id, artifact)

    def _move(self, key: str, bucket_dir: str) -> str:
        rel = key.split("/inbox/", 1)[1]
        dst = self._key(f"{bucket_dir}/{rel}")
        self.store.rename(key, dst)
        return dst

    def _put(self, artifact: str, doc: Any) -> str:
        return self.store.put_artifact(self.tenant_id, artifact, _json_bytes(doc), content_type="application/json")["key"]

    def run_once(self, *, limit: int = 500) -> dict[str, Any]:
        summary = {"ingested_batches": 0, "items": 0, "created": 0, "duplicate": 0, "conflict": 0, "rejected": 0,
                   "quarantined_batches": 0, "acks": []}
        for row in self.store.list(inbox_prefix(self.tenant_id), limit=limit):
            key = row["key"]
            try:
                doc = json.loads(self.store.get_bytes(key).decode("utf-8"))
                if not isinstance(doc, dict) or doc.get("schema") != BATCH_SCHEMA or doc.get("tenant_id") != self.tenant_id:
                    raise ValueError("BATCH_SCHEMA_INVALID")
                kind = str(doc.get("kind"))
                method = INGEST_BY_KIND.get(kind)
                if method is None:
                    raise ValueError(f"KIND_UNKNOWN:{kind}")
                principal = svc_mod.Principal(principal_id=str(doc["device_id"]), tenant_id=self.tenant_id,
                                              role="device_writer", line_ids=(str(doc["line_id"]),))
                results = getattr(self.service, method)(principal, doc.get("items") or [])
            except Exception as exc:  # noqa: BLE001 -- one bad object never stops the queue
                dst = self._move(key, "quarantine")
                note = {"schema": ACK_SCHEMA, "status": "QUARANTINED", "source_key": key,
                        "error": f"{type(exc).__name__}:{str(exc)[:300]}", "at": c.now_iso()}
                if c.sensitive_findings(note):  # never echo a sensitive fragment into the public bucket
                    note["error"] = f"{type(exc).__name__}:<redacted>"
                self._put(dst.split("/", 2)[2] + ".error.json", note)
                summary["quarantined_batches"] += 1
                continue
            counts = {"created": 0, "duplicate": 0, "conflict": 0, "rejected": 0}
            for r in results:
                counts[str(r.get("status", "")).lower()] = counts.get(str(r.get("status", "")).lower(), 0) + 1
            ack = {"schema": ACK_SCHEMA, "status": "INGESTED", "batch_id": doc["batch_id"], "kind": kind,
                   "line_id": doc["line_id"], "device_id": doc["device_id"], "results": results,
                   "counts": counts, "source_key": key, "at": c.now_iso()}
            ack_key = self._put(f"acks/{_seg(doc['line_id'])}/{_seg(doc['device_id'])}/{doc['batch_id']}.json", ack)
            self._move(key, "processed")
            summary["ingested_batches"] += 1
            summary["items"] += len(results)
            for k in ("created", "duplicate", "conflict", "rejected"):
                summary[k] += counts.get(k, 0)
            summary["acks"].append(ack_key)
        return summary


# --------------------------------------------------------------------------- runtime root layout
class CollectiveRoot:
    """``<runtime_root>/runtime/collective/``: sqlite, publisher key (0600), trust store, preflight receipt."""

    def __init__(self, runtime_root: Path | str):
        self.root = Path(runtime_root).expanduser()
        self.dir = self.root / COLLECTIVE_DIR
        self.db = self.dir / DB_FILE
        self.key_path = self.dir / PUBLISHER_KEY_FILE
        self.trust_path = self.dir / TRUST_FILE
        self.admin_token_path = self.dir / ADMIN_TOKEN_FILE
        self.preflight_path = self.dir / PREFLIGHT_FILE
        self.env_path = self.dir / ENV_FILE
        self.status_path = self.dir / STATUS_FILE
        self.lock_path = self.dir / LOCK_FILE
        self.log_dir = self.dir / LOG_DIR

    def trust(self) -> dict[str, Any]:
        return b.load_trust_store(self.trust_path)

    def publisher_key(self) -> tuple[str, bytes]:
        doc = json.loads(self.key_path.read_text(encoding="utf-8"))
        return str(doc["key_id"]), base64.b64decode(doc["private_key_b64"])

    def _write_secret(self, path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8")
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def open_object_store(cfg: Mapping[str, Any] | None, *, line_id: str, receipt_path: Path | None,
                      env: Mapping[str, str] | None = None,
                      client_factory: Callable[[osm.ObjectStoreConfig, osm.Credentials], osm.S3Client] | None = None,
                      ensure_preflight: bool = True) -> osm.ObjectStore:
    """Object store from a config block + environment; runs the preflight when the receipt is
    missing or stale (operator commands only; never on a production stage)."""
    env = os.environ if env is None else env
    merged: dict[str, Any] = dict(cfg or {})
    for name, var in (("endpoint_url", "S3CTL_ENDPOINT_URL"), ("bucket", "S3CTL_BUCKET"),
                      ("public_base_url", "S3CTL_PUBLIC_BASE_URL"), ("region", "S3CTL_REGION")):
        if not merged.get(name) and env.get(var):
            merged[name] = env[var]
    config = osm.ObjectStoreConfig.from_mapping(merged, env)
    credentials = osm.resolve_credentials(env, config.profile)
    client = (client_factory or osm.make_client)(config, credentials)
    store = osm.ObjectStore(config, client, line_id=line_id, receipt_path=receipt_path)
    if ensure_preflight and not store.preflight_status()[0]:
        receipt = store.preflight()
        if receipt["status"] != "PASSED":
            raise osm.PreflightRequired(f"preflight FAILED for {line_id}: {receipt['steps']}")
    return store


def open_service(root: CollectiveRoot, store: osm.ObjectStore | None) -> svc_mod.Service:
    return svc_mod.Service(root.db, trust_store=root.trust(), object_store=store)


def principal(tenant_id: str, principal_id: str, role: str, line_ids: tuple[str, ...] = ()) -> svc_mod.Principal:
    return svc_mod.Principal(principal_id=principal_id, tenant_id=tenant_id, role=role, line_ids=line_ids)


# --------------------------------------------------------------------------- background collector
def load_env_file(path: Path) -> dict[str, str]:
    """``KEY=VALUE`` lines (0600, outside the repo).  Values are never logged."""
    env: dict[str, str] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key.startswith("export "):
            key = key[7:].strip()
        env[key] = value
    return env


def _log(root: CollectiveRoot, message: str) -> None:
    root.log_dir.mkdir(parents=True, exist_ok=True)
    with (root.log_dir / "collector.log").open("a", encoding="utf-8") as fh:
        fh.write(f"[{c.now_iso()}] {message}\n")


def _write_status(root: CollectiveRoot, status: dict[str, Any]) -> dict[str, Any]:
    root.dir.mkdir(parents=True, exist_ok=True)
    root.status_path.write_text(json.dumps(status, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8")
    return status


def read_status(root: CollectiveRoot) -> dict[str, Any] | None:
    if not root.status_path.is_file():
        return None
    try:
        return json.loads(root.status_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def sync_channels(service: svc_mod.Service, store: osm.ObjectStore, root: CollectiveRoot, tenant_id: str) -> dict[str, Any]:
    """Make the bucket's signed channel pointers match the service's channel table (idempotent)."""
    channel = S3Channel(store, tenant_id=tenant_id)
    rows = service._read("SELECT bundle_id, channel, version FROM channels WHERE tenant_id=? ORDER BY channel, bundle_id",
                         (tenant_id,))
    published, unchanged = [], []
    pointers: dict[str, dict[str, Any]] = {}
    for bundle_id, ch, version in rows:
        if ch not in pointers:
            pointers[ch] = ((channel.get_json(f"channels/{_seg(ch)}.json") or {}).get("body") or {}).get("bundles") or {}
        current = pointers[ch].get(bundle_id) or {}
        if str(current.get("version")) == str(version):
            unchanged.append({"channel": ch, "bundle_id": bundle_id, "version": str(version)})
            continue
        pub = principal(tenant_id, "collector", "publisher")
        record = service.get_bundle(pub, bundle_id, str(version))
        raw = base64.b64decode(record["payload_b64"])
        envelope = json.loads(raw.decode("utf-8"))
        b.verify_bundle(envelope, root.trust())
        artifact = f"bundles/{_seg(bundle_id)}/{_seg(str(version))}.json"
        if store.head(tenant_key(tenant_id, artifact)) is None:
            store.put_artifact(tenant_id, artifact, raw, content_type="application/json")
        key_id, private = root.publisher_key()
        out = channel.publish(ch, bundle_id=bundle_id, version=str(version), bundle_digest=envelope["digest"],
                              payload_sha256=c.sha256_bytes(raw), key_id=key_id, private_raw=private)
        pointers[ch] = out["bundles"]
        published.append({"channel": ch, "bundle_id": bundle_id, "version": str(version), "sequence": out["sequence"]})
    latest = {ch: {bid: ref.get("version") for bid, ref in entries.items()} for ch, entries in pointers.items()}
    return {"published": published, "unchanged": unchanged, "latest_by_channel": latest}


def run_cycle(runtime_root: Path | str, tenant_id: str, *, interval_s: int = DEFAULT_INTERVAL_S,
              env: Mapping[str, str] | None = None, client_factory=None) -> dict[str, Any]:
    """One collector cycle: env file → lock → collect → publish channels → status.  Fails closed:
    a missing env file or a held lock produces a status entry and a non-OK status, never a crash."""
    root = CollectiveRoot(runtime_root)
    root.dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    base = {"schema": "collective.collector_status.v1", "tenant": tenant_id, "interval_s": interval_s,
            "runtime_root": str(root.root), "started_at": c.now_iso(), "agent_label": AGENT_LABEL}
    previous = read_status(root) or {}
    if env is None:
        if not root.env_path.is_file():
            status = {**base, "status": "CREDENTIALS_MISSING", "reason": f"env file missing: {root.env_path}",
                      "required_lines": [f"{k}=<value>" for k in REQUIRED_ENV],
                      "last_ok_run_at": previous.get("last_ok_run_at")}
            _log(root, "CREDENTIALS_MISSING: " + str(root.env_path))
            return _write_status(root, status)
        env = {**os.environ, **load_env_file(root.env_path)}
    missing = [k for k in REQUIRED_ENV if not env.get(k)]
    if missing:
        status = {**base, "status": "CREDENTIALS_MISSING", "reason": f"missing in env file: {missing}",
                  "required_lines": [f"{k}=<value>" for k in REQUIRED_ENV], "last_ok_run_at": previous.get("last_ok_run_at")}
        _log(root, f"CREDENTIALS_MISSING: {missing}")
        return _write_status(root, status)
    root.lock_path.touch()
    with root.lock_path.open("r+") as lock_fh:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            status = {**previous, **base, "status": "SKIPPED_OVERLAP", "reason": "previous cycle still running"}
            _log(root, "SKIPPED_OVERLAP")
            return _write_status(root, status)
        try:
            store = open_object_store(None, line_id=SERVICE_LINE, receipt_path=root.preflight_path, env=env,
                                      client_factory=client_factory)
            service = open_service(root, store)
            collected = Collector(service, store, tenant_id=tenant_id).run_once()
            channels = sync_channels(service, store, root, tenant_id)
            backlog = len(store.list(inbox_prefix(tenant_id)))
            status = {**base, "status": "OK", "finished_at": c.now_iso(), "duration_s": round(time.time() - started, 2),
                      "last_ok_run_at": c.now_iso(), "backlog_inbox_batches": backlog,
                      "collected": {k: collected[k] for k in ("ingested_batches", "items", "created", "duplicate",
                                                             "conflict", "rejected", "quarantined_batches")},
                      "channels": channels, "latest_bundle_versions": channels["latest_by_channel"],
                      "event_counts": service.event_counts(tenant_id),
                      "boundary": "collector runs only while this machine is on; published bundles stay "
                                  "downloadable from the public bucket meanwhile; the backlog is processed on restart"}
            _log(root, f"OK collected={status['collected']} published={len(channels['published'])} backlog={backlog}")
        except Exception as exc:  # noqa: BLE001 -- the agent must never die on a transient bucket error
            status = {**base, "status": "ERROR", "error": f"{type(exc).__name__}:{str(exc)[:300]}",
                      "last_ok_run_at": previous.get("last_ok_run_at")}
            _log(root, f"ERROR {type(exc).__name__}: {str(exc)[:300]}")
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
    return _write_status(root, status)


def agent_plist(runtime_root: Path, tenant_id: str, *, interval_s: int, python: str, script: str) -> dict[str, Any]:
    root = CollectiveRoot(runtime_root)
    return {
        "Label": AGENT_LABEL,
        "ProgramArguments": [python, script, "run-cycle", "--runtime-root", str(root.root), "--tenant", tenant_id,
                             "--interval", str(interval_s)],
        "StartInterval": int(interval_s), "RunAtLoad": True, "ProcessType": "Background",
        "StandardOutPath": str(root.log_dir / "launchd.out.log"), "StandardErrorPath": str(root.log_dir / "launchd.err.log"),
        "WorkingDirectory": str(Path(script).resolve().parents[2]),
    }


def install_agent(runtime_root: Path | str, tenant_id: str, *, interval_s: int = DEFAULT_INTERVAL_S,
                  python: str | None = None, agents_dir: Path | None = None, load: bool = False) -> dict[str, Any]:
    root = CollectiveRoot(runtime_root)
    root.log_dir.mkdir(parents=True, exist_ok=True)
    python = python or sys.executable
    script = str(Path(__file__).resolve())
    agents_dir = Path(agents_dir) if agents_dir else Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = agents_dir / f"{AGENT_LABEL}.plist"
    doc = agent_plist(root.root, tenant_id, interval_s=interval_s, python=python, script=script)
    plist_path.write_bytes(plistlib.dumps(doc))
    out = {"status": "OK", "plist": str(plist_path), "label": AGENT_LABEL, "interval_s": interval_s,
           "env_file": str(root.env_path), "env_file_present": root.env_path.is_file(),
           "required_env_lines": [f"{k}=<value>" for k in REQUIRED_ENV],
           "load_command": f"launchctl bootstrap gui/{os.getuid()} {plist_path}",
           "unload_command": f"launchctl bootout gui/{os.getuid()}/{AGENT_LABEL}",
           "kick_command": f"launchctl kickstart -k gui/{os.getuid()}/{AGENT_LABEL}", "loaded": None}
    if load:
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{AGENT_LABEL}"], capture_output=True, text=True)
        proc = subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)],
                              capture_output=True, text=True)
        out["loaded"] = proc.returncode == 0
        out["launchctl"] = (proc.stdout + proc.stderr).strip()[:300]
        if proc.returncode != 0:
            out["status"] = "PLIST_WRITTEN_NOT_LOADED"
    return out


# --------------------------------------------------------------------------- CLI
def cmd_bootstrap(args, env, factory) -> dict[str, Any]:
    root = CollectiveRoot(args.runtime_root)
    root.dir.mkdir(parents=True, exist_ok=True)
    if root.key_path.exists() and not args.rotate_key:
        key_id, _ = root.publisher_key()
        created_key = False
    else:
        private, public = b.generate_keypair()
        key_id = args.key_id or f"pub-{_seg(args.tenant)}"
        root._write_secret(root.key_path, json.dumps({"key_id": key_id, "algorithm": "Ed25519",
                                                      "private_key_b64": base64.b64encode(private).decode("ascii"),
                                                      "public_key_b64": public, "created_at": c.now_iso()}, indent=1))
        created_key = True
    pub_b64 = json.loads(root.key_path.read_text(encoding="utf-8"))["public_key_b64"]
    trust = b.make_trust_store({key_id: {"public_key_b64": pub_b64, "status": "ACTIVE", "roles": [b.KNOWLEDGE_PUBLISHER]}})
    root.trust_path.write_text(json.dumps(trust, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    store = open_object_store(getattr(args, "object_store_cfg", None), line_id=SERVICE_LINE,
                              receipt_path=root.preflight_path, env=env, client_factory=factory)
    service = open_service(root, store)
    tenant_status = "EXISTS"
    if not service._read("SELECT 1 FROM tenants WHERE tenant_id=?", (args.tenant,)):
        boot = service.bootstrap_tenant(args.tenant, admin_id=f"admin-{_seg(args.tenant)}")
        root._write_secret(root.admin_token_path, boot["token"] + "\n")
        tenant_status = "CREATED"
    channel = S3Channel(store, tenant_id=args.tenant)
    put = channel.publish_trust(trust)
    return {"status": "OK", "runtime_root": str(root.root), "collective_dir": str(root.dir), "tenant": args.tenant,
            "tenant_status": tenant_status, "publisher_key_id": key_id, "publisher_key_created": created_key,
            "publisher_public_key_b64": pub_b64, "trust_uploaded": put["key"], "trust_public_url": put.get("public_url"),
            "db": str(root.db), "secrets_mode": "0600 (publisher.key.json, admin.token)"}


def cmd_collect(args, env, factory) -> dict[str, Any]:
    root = CollectiveRoot(args.runtime_root)
    store = open_object_store(None, line_id=SERVICE_LINE, receipt_path=root.preflight_path, env=env, client_factory=factory)
    service = open_service(root, store)
    out = Collector(service, store, tenant_id=args.tenant).run_once(limit=args.limit)
    out["event_counts"] = service.event_counts(args.tenant)
    return {"status": "OK", **out}


def cmd_publish_channel(args, env, factory) -> dict[str, Any]:
    root = CollectiveRoot(args.runtime_root)
    store = open_object_store(None, line_id=SERVICE_LINE, receipt_path=root.preflight_path, env=env, client_factory=factory)
    service = open_service(root, store)
    pub = principal(args.tenant, "publisher-cli", "publisher")
    record = service.get_bundle(pub, args.bundle_id, str(args.version))
    raw = base64.b64decode(record["payload_b64"])
    envelope = json.loads(raw.decode("utf-8"))
    b.verify_bundle(envelope, root.trust())
    channel = S3Channel(store, tenant_id=args.tenant)
    key = tenant_key(args.tenant, f"bundles/{_seg(args.bundle_id)}/{_seg(str(args.version))}.json")
    if store.head(key) is None:  # the service mirror may have failed earlier; the sqlite copy is authoritative
        store.put_artifact(args.tenant, f"bundles/{_seg(args.bundle_id)}/{_seg(str(args.version))}.json", raw,
                           content_type="application/json")
    service.release(pub, bundle_id=args.bundle_id, version=str(args.version), channel=args.channel)
    key_id, private = root.publisher_key()
    out = channel.publish(args.channel, bundle_id=args.bundle_id, version=str(args.version),
                          bundle_digest=envelope["digest"], payload_sha256=c.sha256_bytes(raw),
                          key_id=key_id, private_raw=private)
    return {"status": "OK", **out}


def load_device_config(path: Path) -> tuple[dict[str, Any], Path]:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    return config, Path(path).resolve().parent


def device_sync(config_path: Path, *, env: Mapping[str, str] | None = None, client_factory=None,
                channel: str | None = None) -> dict[str, Any]:
    """Push the outbox to the bucket and pull the channel bundles into the local cache."""
    config, base = load_device_config(config_path)

    def _path(value: str) -> Path:
        p = Path(value).expanduser()
        return p if p.is_absolute() else base / p

    tenant, line = str(config["tenant_id"]), str(config["line_id"])
    receipt = _path(config.get("object_store", {}).get("preflight_receipt") or f"S3_PREFLIGHT_{_seg(line)}.json")
    store = open_object_store(config.get("object_store"), line_id=SERVICE_LINE, receipt_path=receipt, env=env,
                              client_factory=client_factory)
    dstore = ds.DeviceStore(base / "COLLECTIVE_DEVICE_STORE.sqlite", tenant_id=tenant, line_id=line)
    transport = S3Transport(store, tenant_id=tenant, line_id=line, device_id=dstore.device_id)
    push = sc.SyncClient(dstore, transport).run_once()
    trust = b.load_trust_store(_path(config["trust_store"]))
    cache = b.BundleCache(_path(config["cache_dir"]), trust)
    chan = S3Channel(store, tenant_id=tenant)
    wanted = channel or config.get("channel", "RELEASED")
    pulls = [chan.fetch_into_cache(cache, trust, channel=ch) for ch in sorted(b.CHANNEL_ACCEPTS[wanted])]
    revocations = None
    signed = chan.get_json("revocations.json")
    if signed and config.get("revocations"):
        b.verify_revocations(signed, trust)  # verify before writing the local copy
        _path(config["revocations"]).write_text(json.dumps(signed, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        revocations = str(_path(config["revocations"]))
    return {"status": "OK", "mode": "s3", "device_id": dstore.device_id, "push": push, "pull": pulls,
            "cache_entries": [{k: e[k] for k in ("bundle_id", "version", "digest", "release_channel")} for e in cache.entries()],
            "revocations_file": revocations, "sync_status": transport.sync_status()}


def cmd_device_sync(args, env, factory) -> dict[str, Any]:
    return device_sync(Path(args.config), env=env, client_factory=factory, channel=args.channel)


def cmd_status(args, env, factory) -> dict[str, Any]:
    root = CollectiveRoot(args.runtime_root)
    out: dict[str, Any] = {"status": "OK", "tenant": args.tenant, "collector": read_status(root),
                           "env_file_present": root.env_path.is_file(),
                           "agent_plist_present": (Path.home() / "Library" / "LaunchAgents" / f"{AGENT_LABEL}.plist").is_file()}
    if root.env_path.is_file() and env is os.environ:
        env = {**os.environ, **load_env_file(root.env_path)}
    try:
        store = open_object_store(None, line_id=SERVICE_LINE, receipt_path=root.preflight_path, env=env,
                                  client_factory=factory, ensure_preflight=False)
        counts = {name: len(store.list(tenant_key(args.tenant, name) + "/"))
                  for name in ("inbox", "processed", "quarantine", "acks", "bundles", "channels")}
        out.update({"objects": counts, "trust_in_bucket": store.head(tenant_key(args.tenant, "trust.json")) is not None,
                    "preflight": store.preflight_status()})
    except osm.ObjectStoreError as exc:
        out["bucket"] = f"UNAVAILABLE:{exc.code}"
    if root.db.is_file():
        out["event_counts"] = open_service(root, None).event_counts(args.tenant)
    return out


def cmd_run_cycle(args, env, factory) -> dict[str, Any]:
    status = run_cycle(args.runtime_root, args.tenant, interval_s=args.interval,
                       env=None if env is os.environ else env, client_factory=factory)
    return status if status.get("status") == "OK" else {**status, "status": status["status"]}


def cmd_install_agent(args, env, factory) -> dict[str, Any]:
    return install_agent(args.runtime_root, args.tenant, interval_s=args.interval, python=args.python,
                         agents_dir=Path(args.agents_dir) if args.agents_dir else None, load=args.load)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="s3_sync", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("bootstrap", help="create <runtime>/runtime/collective (sqlite, publisher key, trust) and upload trust")
    p.add_argument("--runtime-root", required=True), p.add_argument("--tenant", required=True)
    p.add_argument("--key-id"), p.add_argument("--rotate-key", action="store_true")
    p = sub.add_parser("collect", help="ingest inbox objects through the service once")
    p.add_argument("--runtime-root", required=True), p.add_argument("--tenant", required=True)
    p.add_argument("--limit", type=int, default=500)
    p = sub.add_parser("publish-channel", help="release a stored bundle version and sign the channel pointer")
    p.add_argument("--runtime-root", required=True), p.add_argument("--tenant", required=True)
    p.add_argument("--channel", required=True, choices=list(b.CHANNELS))
    p.add_argument("--bundle-id", required=True), p.add_argument("--version", required=True)
    p = sub.add_parser("device-sync", help="push the device outbox to the bucket and pull channel bundles")
    p.add_argument("--config", required=True), p.add_argument("--channel", choices=list(b.CHANNELS))
    p = sub.add_parser("status", help="collector status file, object counts per area and local event counts")
    p.add_argument("--runtime-root", required=True), p.add_argument("--tenant", required=True)
    p = sub.add_parser("run-cycle", help="one background cycle: env file -> lock -> collect -> publish channels -> status")
    p.add_argument("--runtime-root", required=True), p.add_argument("--tenant", required=True)
    p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S)
    p = sub.add_parser("install-agent", help="write the launchd user agent plist (and load it with --load)")
    p.add_argument("--runtime-root", required=True), p.add_argument("--tenant", required=True)
    p.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S), p.add_argument("--python")
    p.add_argument("--agents-dir"), p.add_argument("--load", action="store_true")
    return parser


COMMANDS = {"bootstrap": cmd_bootstrap, "collect": cmd_collect, "publish-channel": cmd_publish_channel,
            "device-sync": cmd_device_sync, "status": cmd_status, "run-cycle": cmd_run_cycle,
            "install-agent": cmd_install_agent}


def main(argv: list[str] | None = None, *, env: Mapping[str, str] | None = None, client_factory=None, out=None) -> int:
    env = os.environ if env is None else env
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    try:
        result = COMMANDS[args.cmd](args, env, client_factory)
    except (osm.ObjectStoreError, b.BundleError, svc_mod.ServiceError) as exc:
        result = {"status": "ERROR", "code": getattr(exc, "code", type(exc).__name__), "error": str(exc)[:500]}
    except Exception as exc:  # noqa: BLE001
        result = {"status": "ERROR", "code": osm._error_code(exc) or type(exc).__name__, "error": str(exc)[:500]}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str), file=out)
    return 0 if result.get("status") == "OK" else 2


if __name__ == "__main__":
    sys.exit(main())
