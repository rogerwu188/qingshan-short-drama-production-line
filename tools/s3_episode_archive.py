#!/usr/bin/env python3
"""Upload the latest episode final to S3 and verify it by streaming readback."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


SCHEMA = "qingshan.s3_episode_archive_receipt.v1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        temporary = Path(stream.name)
    os.replace(temporary, path)


def normalized_key(prefix: str, project_id: str, episode: str, version: str, name: str) -> str:
    parts = [
        prefix.strip("/"),
        "published-finals",
        project_id.strip("/"),
        episode.strip("/"),
        version.strip("/"),
        name,
    ]
    return "/".join(part for part in parts if part)


def stream_object_sha(client, bucket: str, key: str) -> tuple[str, int]:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    digest = hashlib.sha256()
    size = 0
    try:
        while True:
            chunk = body.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
    finally:
        body.close()
    return digest.hexdigest(), size


def upload_and_verify(
    source: Path,
    *,
    project_id: str,
    episode: str,
    version: str,
    bucket: str,
    key: str,
    endpoint: str | None,
    client=None,
) -> dict:
    source = source.expanduser().resolve()
    if not source.is_file() or source.stat().st_size <= 0:
        raise ValueError(f"source final missing or empty: {source}")
    local_sha = sha256(source)
    local_bytes = source.stat().st_size
    if client is None:
        import boto3

        client = boto3.client("s3", endpoint_url=endpoint or None)
    content_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
    client.upload_file(
        str(source),
        bucket,
        key,
        ExtraArgs={
            "ContentType": content_type,
            "Metadata": {
                "sha256": local_sha,
                "project-id": project_id,
                "episode": episode,
                "version": version,
            },
        },
    )
    head = client.head_object(Bucket=bucket, Key=key)
    metadata = {str(k).lower(): str(v) for k, v in (head.get("Metadata") or {}).items()}
    head_verified = (
        int(head.get("ContentLength") or -1) == local_bytes
        and metadata.get("sha256") == local_sha
    )
    remote_sha, remote_bytes = stream_object_sha(client, bucket, key)
    readback_verified = remote_sha == local_sha and remote_bytes == local_bytes
    status = "VERIFIED" if head_verified and readback_verified else "FAIL"
    return {
        "schema": SCHEMA,
        "status": status,
        "project_id": project_id,
        "episode": episode,
        "version": version,
        "source_path": str(source),
        "source_sha256": local_sha,
        "source_bytes": local_bytes,
        "bucket": bucket,
        "key": key,
        "uri": f"s3://{bucket}/{key}",
        "head_verified": head_verified,
        "stream_readback_verified": readback_verified,
        "remote_sha256": remote_sha,
        "remote_bytes": remote_bytes,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--episode", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--bucket", default=os.environ.get("S3_RELAY_BUCKET"))
    parser.add_argument("--prefix", default=os.environ.get("S3_RELAY_PREFIX", ""))
    parser.add_argument("--key")
    parser.add_argument("--endpoint", default=os.environ.get("S3_RELAY_ENDPOINT"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if not args.bucket:
        raise SystemExit("S3_RELAY_BUCKET or --bucket is required")
    key = args.key or normalized_key(
        args.prefix,
        args.project_id,
        args.episode,
        args.version,
        args.file.name,
    )
    receipt = upload_and_verify(
        args.file,
        project_id=args.project_id,
        episode=args.episode,
        version=args.version,
        bucket=args.bucket,
        key=key,
        endpoint=args.endpoint,
    )
    atomic_write(args.out.expanduser().resolve(), receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
