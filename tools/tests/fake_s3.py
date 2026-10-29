"""In-memory S3 fake for tests: the standard subset only.  Unsupported gateway
operations raise, so any accidental call surfaces as a test failure."""
from __future__ import annotations

import io

from tools.collective_learning import contracts as c
from tools.collective_learning import object_store as osm


class S3Error(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeS3:
    """In-memory S3: standard subset only.  Unsupported gateway operations raise, so any
    accidental call surfaces as a test failure."""

    def __init__(self):
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.calls: list[str] = []
        self.corrupt_get = False
        self.ignore_delete = False
        self.fail_put: Exception | None = None

    def __getattr__(self, name):
        if name in osm.UNSUPPORTED_OPERATIONS:
            raise AssertionError(f"unsupported gateway operation called: {name}")
        raise AttributeError(name)

    def put_object(self, *, Bucket, Key, Body, ContentLength, ContentType="application/octet-stream"):
        self.calls.append("put_object")
        assert ContentLength == len(Body), "explicit Content-Length must match the body"
        if self.fail_put:
            raise self.fail_put
        self.objects[(Bucket, Key)] = (bytes(Body), ContentType)
        return {"ETag": '"' + c.sha256_bytes(bytes(Body))[:32] + '"'}

    def get_object(self, *, Bucket, Key):
        self.calls.append("get_object")
        if (Bucket, Key) not in self.objects:
            raise S3Error("NoSuchKey")
        data, ctype = self.objects[(Bucket, Key)]
        if self.corrupt_get:
            data = data[:-1] + bytes([data[-1] ^ 0xFF])
        return {"Body": io.BytesIO(data), "ContentType": ctype}

    def head_object(self, *, Bucket, Key):
        self.calls.append("head_object")
        if (Bucket, Key) not in self.objects:
            raise S3Error("404")
        data, ctype = self.objects[(Bucket, Key)]
        return {"ContentLength": len(data), "ETag": '"x"', "ContentType": ctype}

    def delete_object(self, *, Bucket, Key):
        self.calls.append("delete_object")
        if not self.ignore_delete:
            self.objects.pop((Bucket, Key), None)
        return {}

    def list_objects_v2(self, *, Bucket, Prefix="", MaxKeys=1000, ContinuationToken=None):
        self.calls.append("list_objects_v2")
        keys = sorted(k for (b, k) in self.objects if b == Bucket and k.startswith(Prefix))
        start = int(ContinuationToken or 0)
        page = keys[start:start + MaxKeys]
        truncated = start + MaxKeys < len(keys)
        return {"Contents": [{"Key": k, "Size": len(self.objects[(Bucket, k)][0])} for k in page],
                "IsTruncated": truncated,
                **({"NextContinuationToken": str(start + MaxKeys)} if truncated else {})}

    def copy_object(self, *, Bucket, Key, CopySource):
        self.calls.append("copy_object")
        src = (CopySource["Bucket"], CopySource["Key"])
        if src not in self.objects:
            raise S3Error("NoSuchKey")
        self.objects[(Bucket, Key)] = self.objects[src]
        return {}
