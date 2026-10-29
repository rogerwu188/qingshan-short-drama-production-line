"""S3-compatible object storage for collective-learning artifacts (bundles, evidence).

Target: a self-hosted S3 gateway (MinIO / JuiceFS gateway).  What this module
guarantees, and what the tests pin:

* **Credentials never live in code, config or documents.**  They are read from the
  environment (``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY``) or, failing that,
  from a named AWS profile.  :class:`ObjectStoreConfig` carries endpoint, bucket and
  region only; ``to_dict()``/``repr()`` can be logged safely.
* **Keys are line-prefixed**: ``<line>/<batch_id>/<artifact>``, lowercase ASCII, no
  spaces, no leading slash, no ``..``.  Lines cannot overwrite each other.
* **Only the standard subset** of the S3 API is used: PUT / GET / HEAD / LIST /
  DELETE / COPY (plus multipart through boto3's managed upload).  Object Lock,
  Versioning, Object Tagging and storage classes are not supported by the gateway
  and are never called; rename is copy + delete.
* **Preflight before formal use.**  :meth:`ObjectStore.preflight` PUTs a 1 KB object
  under ``<line>/_preflight/``, GETs it back, compares bytes, DELETEs it and verifies
  it is gone, then writes a receipt.  :meth:`ObjectStore.put_artifact` (the formal
  path) refuses to run without a fresh PASSED receipt for the same endpoint/bucket.
* **The bucket is public-read.**  Every uploaded object is downloadable by anyone,
  permanently, via the public base URL.  The formal path therefore scans payload text
  and metadata with :func:`contracts.sensitive_findings` and refuses media content
  types unless ``allow_media`` is explicitly enabled (requirement §C of
  AUTHORIZATIONS_REQUIRED: private media is not uploaded by default).
* Nothing here runs inside the production pipeline.  Preflight is an operator
  command; S1 never waits on the network (requirement §2.2: no cloud barrier before
  paid tasks).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

if __package__ in (None, ""):  # allow `python tools/collective_learning/object_store.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "tools.collective_learning"  # noqa: A001

from . import contracts as c  # noqa: E402

ENV_ACCESS_KEY = "AWS_ACCESS_KEY_ID"
ENV_SECRET_KEY = "AWS_SECRET_ACCESS_KEY"
ENV_ENDPOINT = "AWS_ENDPOINT_URL"
ENV_REGION = "AWS_DEFAULT_REGION"
ENV_PROFILE = "AWS_PROFILE"
ENV_BUCKET = "COLLECTIVE_OBJECT_BUCKET"
ENV_PUBLIC_BASE = "COLLECTIVE_OBJECT_PUBLIC_BASE_URL"

PREFLIGHT_DIR = "_preflight"
PREFLIGHT_BYTES = 1024
PREFLIGHT_MAX_AGE_S = 24 * 3600
PREFLIGHT_RECEIPT = "COLLECTIVE_OBJECT_STORE_PREFLIGHT.json"
SERVICE_LINE = "collective"  # key prefix for tenant-wide artifacts the cloud service mirrors

# Gateway limitations (documented by the storage owner).  These API operations are
# never called; a test scans this module's source for them.
UNSUPPORTED_OPERATIONS = (
    "put_object_tagging", "get_object_tagging", "delete_object_tagging",
    "put_bucket_versioning", "get_bucket_versioning", "list_object_versions",
    "put_object_lock_configuration", "put_object_retention", "put_object_legal_hold",
    "restore_object",
)

TEXT_CONTENT_TYPES = frozenset({
    "application/json", "application/x-ndjson", "text/plain", "text/markdown", "text/csv",
})
MEDIA_PREFIXES = ("video/", "image/", "audio/")

_SEGMENT_RE = re.compile(r"^[a-z0-9_][a-z0-9._-]*$")
_SHA_HEX = re.compile(r"^[0-9a-f]{64}$")


# --------------------------------------------------------------------------- errors
class ObjectStoreError(RuntimeError):
    code = "OBJECT_STORE_ERROR"


class CredentialsMissing(ObjectStoreError):
    code = "CREDENTIALS_MISSING"


class InvalidKey(ObjectStoreError):
    code = "INVALID_OBJECT_KEY"


class PreflightRequired(ObjectStoreError):
    code = "PREFLIGHT_REQUIRED"


class UploadRefused(ObjectStoreError):
    code = "UPLOAD_REFUSED"


# --------------------------------------------------------------------------- keys
def normalize_segment(value: str, *, what: str) -> str:
    """Lowercase a key segment and validate it.  Raises :class:`InvalidKey`."""
    text = str(value or "").strip().lower()
    if not text:
        raise InvalidKey(f"{what} empty")
    if " " in text or "/" in text or text in (".", "..") or ".." in text.split("."):
        raise InvalidKey(f"{what} contains a space, slash or '..': {text!r}")
    if not _SEGMENT_RE.match(text):
        raise InvalidKey(f"{what} must be lowercase ascii [a-z0-9._-] (leading _ reserved): {text!r}")
    return text


def object_key(line_id: str, batch_id: str, artifact: str) -> str:
    """``<line>/<batch_id>/<artifact>``; ``artifact`` may hold ``/``-separated sub-paths."""
    line = normalize_segment(line_id, what="line_id")
    batch = normalize_segment(batch_id, what="batch_id")
    raw = str(artifact or "").strip()
    if raw.startswith("/") or raw.endswith("/"):
        raise InvalidKey("artifact must not start or end with '/'")
    parts = [normalize_segment(p, what="artifact segment") for p in raw.split("/")]
    return "/".join([line, batch, *parts])


def preflight_key(line_id: str, nonce: str) -> str:
    return object_key(line_id, PREFLIGHT_DIR, f"preflight-{nonce}.bin")


# --------------------------------------------------------------------------- config
@dataclass(frozen=True)
class ObjectStoreConfig:
    """Non-secret connection parameters.  Safe to log, serialise and commit."""

    endpoint_url: str
    bucket: str
    region: str = "us-east-1"
    addressing_style: str = "path"
    signature_version: str = "s3v4"
    public_base_url: str | None = None      # e.g. https://cdn.example/<bucket>
    public_read: bool = True                # the storage owner states the bucket is world-readable
    allow_media: bool = False               # media evidence stays off until decided (§C)
    profile: str | None = None              # AWS profile fallback when env credentials are absent
    preflight_max_age_s: int = PREFLIGHT_MAX_AGE_S

    @classmethod
    def from_mapping(cls, cfg: Mapping[str, Any] | None = None,
                     env: Mapping[str, str] | None = None) -> "ObjectStoreConfig":
        cfg = dict(cfg or {})
        env = os.environ if env is None else env
        for secret in (ENV_ACCESS_KEY, ENV_SECRET_KEY, "access_key", "secret_key", "aws_secret_access_key"):
            if secret in cfg:
                raise UploadRefused(f"config must not carry credentials ({secret}); use the environment")
        endpoint = cfg.get("endpoint_url") or env.get(ENV_ENDPOINT)
        bucket = cfg.get("bucket") or env.get(ENV_BUCKET)
        if not endpoint or not bucket:
            raise ObjectStoreError("endpoint_url and bucket are required (config or environment)")
        return cls(
            endpoint_url=str(endpoint).rstrip("/"),
            bucket=normalize_segment(bucket, what="bucket"),
            region=str(cfg.get("region") or env.get(ENV_REGION) or "us-east-1"),
            addressing_style=str(cfg.get("addressing_style") or "path"),
            signature_version=str(cfg.get("signature_version") or "s3v4"),
            public_base_url=(str(cfg.get("public_base_url") or env.get(ENV_PUBLIC_BASE) or "").rstrip("/") or None),
            public_read=bool(cfg.get("public_read", True)),
            allow_media=bool(cfg.get("allow_media", False)),
            profile=cfg.get("profile") or env.get(ENV_PROFILE) or None,
            preflight_max_age_s=int(cfg.get("preflight_max_age_s", PREFLIGHT_MAX_AGE_S)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "endpoint_url": self.endpoint_url, "bucket": self.bucket, "region": self.region,
            "addressing_style": self.addressing_style, "signature_version": self.signature_version,
            "public_base_url": self.public_base_url, "public_read": self.public_read,
            "allow_media": self.allow_media, "profile": self.profile,
            "credentials": "FROM_ENVIRONMENT",
        }

    def public_url(self, key: str) -> str | None:
        if not self.public_base_url:
            return None
        return f"{self.public_base_url}/{key}"


@dataclass(frozen=True)
class Credentials:
    access_key: str
    secret_key: str
    source: str

    def __repr__(self) -> str:  # never print the secret
        return f"Credentials(access_key={self.access_key[:4]}…, source={self.source})"


def resolve_credentials(env: Mapping[str, str] | None = None, profile: str | None = None) -> Credentials:
    """Environment first, then the named AWS profile (via boto3).  Never a file in the repo."""
    env = os.environ if env is None else env
    access, secret = env.get(ENV_ACCESS_KEY), env.get(ENV_SECRET_KEY)
    if access and secret:
        return Credentials(access, secret, "environment")
    if profile:
        try:
            import boto3  # noqa: PLC0415 -- optional dependency (extra ``cloud``)
            session = boto3.Session(profile_name=profile)
            creds = session.get_credentials()
        except Exception as exc:  # noqa: BLE001
            raise CredentialsMissing(f"profile {profile!r} unavailable: {type(exc).__name__}") from exc
        if creds and creds.access_key and creds.secret_key:
            return Credentials(creds.access_key, creds.secret_key, f"profile:{profile}")
    raise CredentialsMissing(f"set {ENV_ACCESS_KEY} and {ENV_SECRET_KEY} in the environment"
                             + (f" or configure profile {profile!r}" if profile else ""))


# --------------------------------------------------------------------------- client
class S3Client(Protocol):
    """The subset of the boto3 S3 client this module uses (fakes implement the same)."""

    def put_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def get_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def head_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def delete_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def list_objects_v2(self, **kwargs: Any) -> dict[str, Any]: ...
    def copy_object(self, **kwargs: Any) -> dict[str, Any]: ...


def make_client(config: ObjectStoreConfig, credentials: Credentials) -> S3Client:
    try:
        import boto3  # noqa: PLC0415
        from botocore.config import Config  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise ObjectStoreError("boto3 is required: pip install -e '.[cloud]'") from exc
    return boto3.client(
        "s3", endpoint_url=config.endpoint_url, region_name=config.region,
        aws_access_key_id=credentials.access_key, aws_secret_access_key=credentials.secret_key,
        config=Config(signature_version=config.signature_version,
                      s3={"addressing_style": config.addressing_style},
                      retries={"max_attempts": 4, "mode": "standard"},
                      # boto3 >= 1.36 defaults to aws-chunked uploads with trailing checksums;
                      # the MinIO/JuiceFS gateway answers MissingContentLength to those
                      # (found by the real preflight on 2026-10-29).  Plain signed PUTs work.
                      request_checksum_calculation="when_required",
                      response_checksum_validation="when_required"),
    )


def _error_code(exc: BaseException) -> str:
    response = getattr(exc, "response", None) or {}
    error = response.get("Error", {}) if isinstance(response, dict) else {}
    return str(error.get("Code") or getattr(exc, "code", "") or "")


def is_not_found(exc: BaseException) -> bool:
    return _error_code(exc) in ("404", "NoSuchKey", "NotFound")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- store
class ObjectStore:
    """One line's view of the bucket.  Raw operations never touch unsupported APIs; the
    formal path (:meth:`put_artifact`) adds the preflight and privacy gates."""

    def __init__(self, config: ObjectStoreConfig, client: S3Client, *, line_id: str,
                 receipt_path: Path | str | None = None, clock: Callable[[], float] = time.time):
        self.config = config
        self.client = client
        self.line_id = normalize_segment(line_id, what="line_id")
        self.receipt_path = Path(receipt_path) if receipt_path else None
        self._clock = clock
        self._preflight: dict[str, Any] | None = None
        if self.receipt_path and self.receipt_path.is_file():
            try:
                self._preflight = json.loads(self.receipt_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._preflight = None

    @classmethod
    def from_env(cls, cfg: Mapping[str, Any] | None, *, line_id: str, env: Mapping[str, str] | None = None,
                 receipt_path: Path | str | None = None) -> "ObjectStore":
        config = ObjectStoreConfig.from_mapping(cfg, env)
        credentials = resolve_credentials(env, config.profile)
        return cls(config, make_client(config, credentials), line_id=line_id, receipt_path=receipt_path)

    # -- keys ----------------------------------------------------------------
    def key(self, batch_id: str, artifact: str) -> str:
        return object_key(self.line_id, batch_id, artifact)

    def public_url(self, key: str) -> str | None:
        return self.config.public_url(key)

    # -- raw operations (standard S3 subset only) ----------------------------
    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> dict[str, Any]:
        response = self.client.put_object(Bucket=self.config.bucket, Key=key, Body=bytes(data),
                                          ContentLength=len(data), ContentType=content_type)
        return {"key": key, "size": len(data), "sha256": _sha256(data), "etag": response.get("ETag"),
                "content_type": content_type, "public_url": self.public_url(key)}

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.config.bucket, Key=key)
        body = response["Body"]
        return body.read() if hasattr(body, "read") else bytes(body)

    def head(self, key: str) -> dict[str, Any] | None:
        try:
            response = self.client.head_object(Bucket=self.config.bucket, Key=key)
        except Exception as exc:  # noqa: BLE001
            if is_not_found(exc):
                return None
            raise
        return {"key": key, "size": response.get("ContentLength"), "etag": response.get("ETag"),
                "content_type": response.get("ContentType")}

    def delete(self, key: str) -> dict[str, Any]:
        self.client.delete_object(Bucket=self.config.bucket, Key=key)
        return {"key": key, "status": "DELETED"}

    def list(self, prefix: str, *, limit: int = 1000) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": self.config.bucket, "Prefix": prefix, "MaxKeys": min(limit, 1000)}
            if token:
                kwargs["ContinuationToken"] = token
            response = self.client.list_objects_v2(**kwargs)
            for item in response.get("Contents") or []:
                rows.append({"key": item["Key"], "size": item.get("Size"), "etag": item.get("ETag"),
                             "last_modified": str(item.get("LastModified") or "")})
                if len(rows) >= limit:
                    return rows
            token = response.get("NextContinuationToken") if response.get("IsTruncated") else None
            if not token:
                return rows

    def rename(self, src: str, dst: str) -> dict[str, Any]:
        """Copy + delete.  The gateway has no versioning/tagging, so the client-side
        ``rename`` helpers of some SDKs fail with "functionality not implemented"."""
        self.client.copy_object(Bucket=self.config.bucket, Key=dst,
                                CopySource={"Bucket": self.config.bucket, "Key": src})
        if self.head(dst) is None:
            raise ObjectStoreError(f"copy did not materialise {dst}")
        self.client.delete_object(Bucket=self.config.bucket, Key=src)
        return {"from": src, "to": dst, "status": "RENAMED", "method": "copy+delete"}

    # -- preflight -----------------------------------------------------------
    def preflight(self, *, verify_public: bool = False) -> dict[str, Any]:
        """PUT 1 KB -> GET (bytes equal) -> DELETE -> HEAD is gone.  Writes the receipt
        (PASSED or FAILED) and returns it.  Never raises on a failed step: the receipt
        carries the step and the error class so the operator can see what broke."""
        nonce = secrets.token_hex(8)
        key = preflight_key(self.line_id, nonce)
        payload = secrets.token_bytes(PREFLIGHT_BYTES)
        steps: list[dict[str, Any]] = []
        status = "PASSED"

        def step(name: str, fn: Callable[[], Any], check: Callable[[Any], str | None] | None = None) -> bool:
            started = time.perf_counter()
            try:
                result = fn()
                problem = check(result) if check else None
            except Exception as exc:  # noqa: BLE001
                steps.append({"op": name, "ok": False, "ms": round((time.perf_counter() - started) * 1000, 1),
                              "error": f"{type(exc).__name__}: {str(exc)[:300]}", "code": _error_code(exc)})
                return False
            steps.append({"op": name, "ok": problem is None, "ms": round((time.perf_counter() - started) * 1000, 1),
                          **({"error": problem} if problem else {})})
            return problem is None

        ok = step("PUT", lambda: self.put_bytes(key, payload, "application/octet-stream"))
        if ok:
            ok = step("GET", lambda: self.get_bytes(key),
                      lambda got: None if got == payload else f"bytes differ: got {len(got)} B sha {_sha256(got)[:12]}")
        if ok and verify_public and self.public_url(key):
            ok = step("GET_PUBLIC", lambda: _http_get(self.public_url(key) or ""),
                      lambda got: None if got == payload else "public download differs from PUT payload")
        # always try to delete what was written, even after a failed GET
        if steps and steps[0]["ok"]:
            deleted = step("DELETE", lambda: self.delete(key))
            ok = ok and deleted
            if deleted:
                ok = step("VERIFY_GONE", lambda: self.head(key),
                          lambda got: None if got is None else "object still present after DELETE") and ok
        if not ok:
            status = "FAILED"
        receipt = {
            "status": status, "line_id": self.line_id, "endpoint_url": self.config.endpoint_url,
            "bucket": self.config.bucket, "region": self.config.region, "key": key,
            "size": PREFLIGHT_BYTES, "sha256": _sha256(payload), "steps": steps,
            "checked_at": c.now_iso(), "checked_at_epoch": self._clock(), "credentials": "FROM_ENVIRONMENT",
            "public_read": self.config.public_read, "verify_public": verify_public,
        }
        self._preflight = receipt
        if self.receipt_path:
            self.receipt_path.parent.mkdir(parents=True, exist_ok=True)
            self.receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt

    def preflight_status(self) -> tuple[bool, str]:
        rec = self._preflight
        if not rec:
            return False, "no preflight receipt"
        if rec.get("status") != "PASSED":
            return False, f"preflight status {rec.get('status')}"
        if rec.get("endpoint_url") != self.config.endpoint_url or rec.get("bucket") != self.config.bucket:
            return False, "preflight receipt is for a different endpoint/bucket"
        if rec.get("line_id") != self.line_id:
            return False, "preflight receipt is for a different line"
        age = self._clock() - float(rec.get("checked_at_epoch") or 0)
        if age > self.config.preflight_max_age_s:
            return False, f"preflight receipt is stale ({int(age)} s > {self.config.preflight_max_age_s} s)"
        return True, "ok"

    def require_preflight(self) -> None:
        ok, why = self.preflight_status()
        if not ok:
            raise PreflightRequired(f"{why}; run `object_store.py preflight --line {self.line_id}` first")

    # -- formal path ---------------------------------------------------------
    def put_artifact(self, batch_id: str, artifact: str, data: bytes, *, content_type: str,
                     metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Upload one artifact under ``<line>/<batch_id>/<artifact>`` with every gate on."""
        self.require_preflight()
        if normalize_segment(batch_id, what="batch_id") == PREFLIGHT_DIR:
            raise UploadRefused(f"{PREFLIGHT_DIR!r} is reserved for preflight objects")
        if not isinstance(data, (bytes, bytearray)) or not data:
            raise UploadRefused("artifact bytes required")
        ctype = str(content_type or "").split(";")[0].strip().lower()
        if not ctype:
            raise UploadRefused("content_type required")
        if ctype.startswith(MEDIA_PREFIXES) and not self.config.allow_media:
            raise UploadRefused("media upload is disabled (bucket is public-read; enable allow_media only once "
                                "the private-media decision in AUTHORIZATIONS_REQUIRED.md §C is made)")
        scan_targets: dict[str, Any] = {"metadata": dict(metadata or {})}
        if ctype in TEXT_CONTENT_TYPES:
            try:
                scan_targets["payload"] = bytes(data).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise UploadRefused(f"{ctype} payload is not utf-8") from exc
        findings = c.sensitive_findings(scan_targets)
        if findings:
            refused = UploadRefused("artifact carries sensitive content; refused because the bucket is public-read: "
                                    + "; ".join(findings[:5]))
            refused.findings = findings  # type: ignore[attr-defined]
            raise refused
        key = self.key(batch_id, artifact)
        result = self.put_bytes(key, bytes(data), ctype)
        result.update({"bucket": self.config.bucket, "endpoint_url": self.config.endpoint_url,
                       "line_id": self.line_id, "batch_id": normalize_segment(batch_id, what="batch_id"),
                       "public_read": self.config.public_read, "uploaded_at": c.now_iso()})
        return result


def _http_get(url: str) -> bytes:
    import urllib.request  # noqa: PLC0415

    # The CDN in front of the public domain answers 403 to the default urllib
    # User-Agent (found by the real preflight on 2026-10-29); any explicit UA passes.
    request = urllib.request.Request(url, headers={"User-Agent": "collective-learning-preflight/1"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310 -- operator preflight only
        return response.read()


# --------------------------------------------------------------------------- evidence helper
def upload_evidence(store: ObjectStore, *, batch_id: str, artifact: str, data: bytes, content_type: str,
                    register: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                    visibility: str = "LINE", links: Mapping[str, list[str]] | None = None,
                    retention_until: str | None = None, metadata: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Put bytes through the formal path, then register the metadata with the cloud
    service (``register`` is ``Service.register_evidence`` bound to a principal, or an
    HTTP transport call).  The registered record carries storage_key + sha256, never a
    signed URL."""
    put = store.put_artifact(batch_id, artifact, data, content_type=content_type, metadata=metadata)
    meta = {
        "evidence_id": c.new_uuid(), "sha256": put["sha256"], "storage_key": put["key"],
        "visibility": visibility, "line_id": store.line_id, "size": put["size"], "content_type": put["content_type"],
        "public_read": store.config.public_read,
    }
    if retention_until:
        meta["retention_until"] = retention_until
    if links:
        meta["links"] = {k: list(v) for k, v in links.items()}
    registered = register(meta) if register else {"status": "NOT_REGISTERED"}
    return {"object": put, "evidence": meta, "registered": registered}


# --------------------------------------------------------------------------- CLI
def _load_config_file(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return dict(doc.get("object_store") or doc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S3-compatible object store operations (credentials from env)")
    parser.add_argument("--config", help="JSON file with an object_store block (endpoint_url, bucket, region, ...)")
    parser.add_argument("--endpoint-url"), parser.add_argument("--bucket"), parser.add_argument("--region")
    parser.add_argument("--public-base-url")
    parser.add_argument("--line", required=True, help="line id used as the key prefix")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_pre = sub.add_parser("preflight", help="PUT 1 KB under <line>/_preflight/, GET, DELETE, verify")
    p_pre.add_argument("--receipt", default=PREFLIGHT_RECEIPT)
    p_pre.add_argument("--verify-public", action="store_true")
    p_ls = sub.add_parser("ls")
    p_ls.add_argument("--prefix", default="")
    p_put = sub.add_parser("put", help="formal path: needs a PASSED preflight receipt")
    p_put.add_argument("--receipt", default=PREFLIGHT_RECEIPT)
    p_put.add_argument("--batch", required=True), p_put.add_argument("--artifact", required=True)
    p_put.add_argument("--file", required=True), p_put.add_argument("--content-type", default="application/json")
    p_rm = sub.add_parser("rm")
    p_rm.add_argument("key")
    p_mv = sub.add_parser("mv", help="copy + delete")
    p_mv.add_argument("src"), p_mv.add_argument("dst")
    args = parser.parse_args(argv)

    cfg = _load_config_file(args.config)
    for name in ("endpoint_url", "bucket", "region", "public_base_url"):
        if getattr(args, name, None):
            cfg[name] = getattr(args, name)
    receipt = Path(getattr(args, "receipt", PREFLIGHT_RECEIPT)) if hasattr(args, "receipt") else None
    try:
        store = ObjectStore.from_env(cfg, line_id=args.line, receipt_path=receipt)
        if args.cmd == "preflight":
            out = store.preflight(verify_public=args.verify_public)
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 0 if out["status"] == "PASSED" else 2
        if args.cmd == "ls":
            out = store.list(args.prefix)
        elif args.cmd == "put":
            out = store.put_artifact(args.batch, args.artifact, Path(args.file).read_bytes(),
                                     content_type=args.content_type)
        elif args.cmd == "rm":
            out = store.delete(args.key)
        else:
            out = store.rename(args.src, args.dst)
    except ObjectStoreError as exc:
        print(json.dumps({"status": "ERROR", "code": exc.code, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
