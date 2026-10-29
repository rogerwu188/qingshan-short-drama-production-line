#!/usr/bin/env python3
"""s3ctl: the only command-line entry to the shared object store (no AWS CLI needed).

Thin wrapper over ``tools/collective_learning/object_store.py`` so every line
(nalu, qingshan, ...) talks to the gateway the same way:

* credentials only from the environment (``AWS_ACCESS_KEY_ID`` /
  ``AWS_SECRET_ACCESS_KEY``) or an AWS profile; never from flags or files here;
* endpoint / bucket / region / public base URL from flags, or from
  ``S3CTL_ENDPOINT_URL`` (falls back to ``AWS_ENDPOINT_URL``), ``S3CTL_BUCKET``,
  ``S3CTL_REGION`` (falls back to ``AWS_DEFAULT_REGION``), ``S3CTL_PUBLIC_BASE_URL``;
* keys are ``<line>/<batch_id>/<artifact>`` (lowercase, no spaces); the first
  segment is the line and decides the preflight receipt that gates uploads;
* ``put`` and ``sync`` go through the formal path (preflight receipt, sensitive
  content scan, media off unless ``--allow-media``); ``ls``/``get``/``head``/``rm``/
  ``mv``/``url`` are plain operations; ``mv`` is copy + delete.

Every command prints one JSON document.  Exit 0 on success, 2 on a refused or
failed operation (the JSON says why), 1 on bad arguments.

Examples::

    s3ctl preflight nalu --verify-public
    s3ctl ls nalu/e13/
    s3ctl put ./out/digest.json nalu/e13/reports/digest.json
    s3ctl sync ./out/ nalu/e13/reports/
    s3ctl get nalu/e13/reports/digest.json ./digest.json
    s3ctl mv nalu/e13/a.json nalu/e13/b.json
    s3ctl url nalu/e13/reports/digest.json
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.collective_learning import object_store as osm  # noqa: E402

ENV_PREFIX = "S3CTL_"
RECEIPT_DIR_ENV = "S3CTL_RECEIPT_DIR"
ClientFactory = Callable[[osm.ObjectStoreConfig, osm.Credentials], osm.S3Client]


class S3ctlError(Exception):
    def __init__(self, code: str, message: str, **extra: Any):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


def _env(env: Mapping[str, str], name: str, *fallbacks: str) -> str | None:
    for key in (ENV_PREFIX + name, *fallbacks):
        if env.get(key):
            return env[key]
    return None


def build_config(args: argparse.Namespace, env: Mapping[str, str]) -> osm.ObjectStoreConfig:
    cfg: dict[str, Any] = {
        "endpoint_url": args.endpoint_url or _env(env, "ENDPOINT_URL", osm.ENV_ENDPOINT),
        "bucket": args.bucket or _env(env, "BUCKET", osm.ENV_BUCKET),
        "region": args.region or _env(env, "REGION", osm.ENV_REGION) or "us-east-1",
        "public_base_url": args.public_base_url or _env(env, "PUBLIC_BASE_URL", osm.ENV_PUBLIC_BASE),
        "allow_media": bool(getattr(args, "allow_media", False) or env.get(ENV_PREFIX + "ALLOW_MEDIA") == "1"),
        "profile": args.profile or env.get(osm.ENV_PROFILE),
    }
    if not cfg["endpoint_url"] or not cfg["bucket"]:
        raise S3ctlError("CONFIG_MISSING", "endpoint and bucket required: --endpoint-url/--bucket or "
                         f"{ENV_PREFIX}ENDPOINT_URL/{ENV_PREFIX}BUCKET in the environment")
    return osm.ObjectStoreConfig.from_mapping(cfg, env)


def line_of(key: str) -> str:
    text = str(key or "").strip()
    if not text or text.startswith("/") or "/" not in text:
        raise S3ctlError("INVALID_KEY", f"key must look like <line>/<batch_id>/<artifact>: {key!r}")
    return text.split("/", 1)[0]


def split_key(key: str) -> tuple[str, str, str]:
    parts = str(key).strip().split("/")
    if len(parts) < 3 or not all(parts):
        raise S3ctlError("INVALID_KEY", f"key must look like <line>/<batch_id>/<artifact>: {key!r}")
    return parts[0], parts[1], "/".join(parts[2:])


def receipt_path(args: argparse.Namespace, env: Mapping[str, str], line: str) -> Path:
    if getattr(args, "receipt", None):
        return Path(args.receipt)
    base = Path(env.get(RECEIPT_DIR_ENV) or ".")
    return base / f"S3CTL_PREFLIGHT_{osm.normalize_segment(line, what='line_id')}.json"


def open_store(args: argparse.Namespace, env: Mapping[str, str], line: str,
               client_factory: ClientFactory | None) -> osm.ObjectStore:
    config = build_config(args, env)
    credentials = osm.resolve_credentials(env, config.profile)
    client = (client_factory or osm.make_client)(config, credentials)
    return osm.ObjectStore(config, client, line_id=line, receipt_path=receipt_path(args, env, line))


def guess_content_type(path: Path, override: str | None) -> str:
    if override:
        return override
    guessed, _ = mimetypes.guess_type(str(path))
    if path.suffix.lower() in (".json",):
        return "application/json"
    if path.suffix.lower() in (".md", ".markdown"):
        return "text/markdown"
    if path.suffix.lower() in (".jsonl", ".ndjson"):
        return "application/x-ndjson"
    return guessed or "application/octet-stream"


# --------------------------------------------------------------------------- commands
def cmd_preflight(args, env, factory) -> dict[str, Any]:
    store = open_store(args, env, args.line, factory)
    out = store.preflight(verify_public=args.verify_public)
    out["receipt_path"] = str(store.receipt_path)
    return out


def cmd_ls(args, env, factory) -> dict[str, Any]:
    prefix = (args.prefix or "").lstrip("/")
    store = open_store(args, env, prefix.split("/")[0] or "_", factory)
    rows = store.list(prefix, limit=args.limit)
    return {"status": "OK", "prefix": prefix, "count": len(rows), "objects": rows}


def cmd_put(args, env, factory) -> dict[str, Any]:
    src = Path(args.file)
    if not src.is_file():
        raise S3ctlError("FILE_NOT_FOUND", str(src))
    line, batch, artifact = split_key(args.key)
    store = open_store(args, env, line, factory)
    out = store.put_artifact(batch, artifact, src.read_bytes(),
                             content_type=guess_content_type(src, args.content_type))
    out["status"] = "UPLOADED"
    out["source"] = src.name
    return out


def cmd_sync(args, env, factory) -> dict[str, Any]:
    root = Path(args.dir)
    if not root.is_dir():
        raise S3ctlError("DIR_NOT_FOUND", str(root))
    prefix = args.prefix.strip().strip("/")
    parts = [p for p in prefix.split("/") if p]
    if len(parts) < 2:
        raise S3ctlError("INVALID_KEY", f"sync prefix must be <line>/<batch_id>[/<sub>]: {args.prefix!r}")
    line, batch, sub = parts[0], parts[1], "/".join(parts[2:])
    store = open_store(args, env, line, factory)
    uploaded, skipped, refused = [], [], []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not p.name.startswith(".")):
        rel = path.relative_to(root).as_posix()
        artifact = f"{sub}/{rel}" if sub else rel
        try:
            key = osm.object_key(line, batch, artifact)
        except osm.InvalidKey as exc:
            refused.append({"file": rel, "code": exc.code, "error": str(exc)})
            continue
        data = path.read_bytes()
        existing = None if args.force else store.head(key)
        if existing and existing.get("size") == len(data) and not args.force:
            skipped.append({"key": key, "reason": "same size (use --force to overwrite)"})
            continue
        try:
            out = store.put_artifact(batch, artifact, data, content_type=guess_content_type(path, None))
            uploaded.append({"key": out["key"], "size": out["size"], "sha256": out["sha256"],
                             "public_url": out.get("public_url")})
        except osm.ObjectStoreError as exc:
            refused.append({"file": rel, "code": exc.code, "error": str(exc)[:300]})
    status = "OK" if not refused else "PARTIAL"
    return {"status": status, "prefix": prefix, "uploaded": uploaded, "skipped": skipped, "refused": refused}


def cmd_get(args, env, factory) -> dict[str, Any]:
    store = open_store(args, env, line_of(args.key), factory)
    data = store.get_bytes(args.key)
    dest = Path(args.dest)
    if dest.is_dir():
        dest = dest / Path(args.key).name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {"status": "DOWNLOADED", "key": args.key, "dest": str(dest), "size": len(data),
            "sha256": osm._sha256(data)}


def cmd_head(args, env, factory) -> dict[str, Any]:
    store = open_store(args, env, line_of(args.key), factory)
    meta = store.head(args.key)
    if meta is None:
        raise S3ctlError("NOT_FOUND", args.key)
    meta["status"] = "OK"
    meta["public_url"] = store.public_url(args.key)
    return meta


def cmd_rm(args, env, factory) -> dict[str, Any]:
    store = open_store(args, env, line_of(args.key), factory)
    if args.recursive:
        if not args.yes:
            raise S3ctlError("CONFIRMATION_REQUIRED", "rm --recursive needs --yes")
        rows = store.list(args.key, limit=args.limit)
        for row in rows:
            store.delete(row["key"])
        return {"status": "DELETED", "prefix": args.key, "count": len(rows), "keys": [r["key"] for r in rows]}
    if store.head(args.key) is None:
        raise S3ctlError("NOT_FOUND", args.key)
    return store.delete(args.key)


def cmd_mv(args, env, factory) -> dict[str, Any]:
    if line_of(args.src) != line_of(args.dst):
        raise S3ctlError("CROSS_LINE_MOVE", "src and dst must stay within one line prefix")
    split_key(args.dst)
    store = open_store(args, env, line_of(args.src), factory)
    if store.head(args.src) is None:
        raise S3ctlError("NOT_FOUND", args.src)
    return store.rename(args.src, args.dst)


def cmd_url(args, env, factory) -> dict[str, Any]:
    config = build_config(args, env)
    url = config.public_url(args.key)
    if not url:
        raise S3ctlError("NO_PUBLIC_BASE", f"set --public-base-url or {ENV_PREFIX}PUBLIC_BASE_URL")
    return {"status": "OK", "key": args.key, "public_url": url, "public_read": config.public_read}


def cmd_config(args, env, factory) -> dict[str, Any]:
    config = build_config(args, env)
    try:
        creds = osm.resolve_credentials(env, config.profile)
        cred_status = {"status": "PRESENT", "source": creds.source, "access_key_prefix": creds.access_key[:4]}
    except osm.CredentialsMissing as exc:
        cred_status = {"status": "MISSING", "error": str(exc)}
    return {"status": "OK", **config.to_dict(), "credentials": cred_status}


COMMANDS = {
    "preflight": cmd_preflight, "ls": cmd_ls, "put": cmd_put, "sync": cmd_sync, "get": cmd_get,
    "head": cmd_head, "rm": cmd_rm, "mv": cmd_mv, "url": cmd_url, "config": cmd_config,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="s3ctl", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--endpoint-url"), parser.add_argument("--bucket"), parser.add_argument("--region")
    parser.add_argument("--public-base-url"), parser.add_argument("--profile")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("preflight", help="PUT 1 KB under <line>/_preflight/, GET, DELETE, verify; writes the receipt")
    p.add_argument("line"), p.add_argument("--verify-public", action="store_true"), p.add_argument("--receipt")

    p = sub.add_parser("ls", help="list objects under a prefix")
    p.add_argument("prefix", nargs="?", default=""), p.add_argument("--limit", type=int, default=1000)

    p = sub.add_parser("put", help="upload one file to <line>/<batch_id>/<artifact> (gated)")
    p.add_argument("file"), p.add_argument("key"), p.add_argument("--content-type")
    p.add_argument("--allow-media", action="store_true"), p.add_argument("--receipt")

    p = sub.add_parser("sync", help="upload a directory under <line>/<batch_id>[/<sub>] (gated, size-skip)")
    p.add_argument("dir"), p.add_argument("prefix"), p.add_argument("--force", action="store_true")
    p.add_argument("--allow-media", action="store_true"), p.add_argument("--receipt")

    p = sub.add_parser("get", help="download one object")
    p.add_argument("key"), p.add_argument("dest")

    p = sub.add_parser("head", help="metadata of one object")
    p.add_argument("key")

    p = sub.add_parser("rm", help="delete one object, or a prefix with --recursive --yes")
    p.add_argument("key"), p.add_argument("--recursive", action="store_true"), p.add_argument("--yes", action="store_true")
    p.add_argument("--limit", type=int, default=1000)

    p = sub.add_parser("mv", help="rename within one line (copy + delete)")
    p.add_argument("src"), p.add_argument("dst")

    p = sub.add_parser("url", help="public download URL for a key")
    p.add_argument("key")

    sub.add_parser("config", help="show effective non-secret configuration and whether credentials resolve")
    return parser


def main(argv: list[str] | None = None, *, env: Mapping[str, str] | None = None,
         client_factory: ClientFactory | None = None, out=None) -> int:
    env = os.environ if env is None else env
    out = out or sys.stdout
    args = build_parser().parse_args(argv)
    try:
        result = COMMANDS[args.cmd](args, env, client_factory)
    except S3ctlError as exc:
        result = {"status": "ERROR", "code": exc.code, "error": exc.message, **exc.extra}
    except osm.ObjectStoreError as exc:
        result = {"status": "ERROR", "code": exc.code, "error": str(exc)[:500]}
    except Exception as exc:  # noqa: BLE001 -- provider errors: show class + code, never the request
        result = {"status": "ERROR", "code": osm._error_code(exc) or type(exc).__name__, "error": str(exc)[:500]}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str), file=out)
    if result.get("status") in ("ERROR", "FAILED", "PARTIAL"):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
