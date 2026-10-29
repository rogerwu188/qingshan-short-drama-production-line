"""Object storage: key naming, credentials from env only, preflight gate, privacy gate,
standard-API-only, bundle mirroring.  Runs against an in-memory fake S3 client; the
real gateway is exercised only by the operator preflight command (receipt in the
runtime reports directory, never in the repository)."""
from __future__ import annotations

import io
import json
import re
import tempfile
import unittest
from pathlib import Path

from tools.collective_learning import contracts as c
from tools.collective_learning import object_store as osm
from tools.collective_learning import service as svc_mod

ROOT = Path(__file__).resolve().parents[2]
SECRET_SENTINEL = "SENTINEL-SECRET-DO-NOT-LEAK-0123456789"
ENV = {
    osm.ENV_ACCESS_KEY: "sentinel-access-key",
    osm.ENV_SECRET_KEY: SECRET_SENTINEL,
    osm.ENV_ENDPOINT: "https://s3.example.test",
    osm.ENV_REGION: "us-east-1",
}
CFG = {"endpoint_url": "https://s3.example.test", "bucket": "drama01", "region": "us-east-1",
       "public_base_url": "https://cdn.example.test/drama01"}


class _S3Error(Exception):
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
            raise _S3Error("NoSuchKey")
        data, ctype = self.objects[(Bucket, Key)]
        if self.corrupt_get:
            data = data[:-1] + bytes([data[-1] ^ 0xFF])
        return {"Body": io.BytesIO(data), "ContentType": ctype}

    def head_object(self, *, Bucket, Key):
        self.calls.append("head_object")
        if (Bucket, Key) not in self.objects:
            raise _S3Error("404")
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
            raise _S3Error("NoSuchKey")
        self.objects[(Bucket, Key)] = self.objects[src]
        return {}


def _store(tmp: Path, fake: FakeS3 | None = None, *, line="nalu", clock=None, **cfg_over) -> tuple[osm.ObjectStore, FakeS3]:
    fake = fake or FakeS3()
    config = osm.ObjectStoreConfig.from_mapping({**CFG, **cfg_over}, env=ENV)
    kwargs = {"clock": clock} if clock else {}
    return osm.ObjectStore(config, fake, line_id=line, receipt_path=tmp / osm.PREFLIGHT_RECEIPT, **kwargs), fake


class KeyNamingTest(unittest.TestCase):
    def test_line_prefixed_lowercase(self):
        self.assertEqual(osm.object_key("NALU", "E13", "S6/Unit-001.json"), "nalu/e13/s6/unit-001.json")
        self.assertEqual(osm.object_key("qingshan", "e50", "final.mp4"), "qingshan/e50/final.mp4")

    def test_rejects_spaces_leading_slash_and_traversal(self):
        for line, batch, art in (("nalu", "e13", "clip 1.mp4"), ("nalu", "e13", "/abs.json"),
                                 ("nalu", "e13", "../other/x.json"), ("na lu", "e13", "x"),
                                 ("nalu", "", "x"), ("nalu", "e13", "中文.json"), ("nalu", "e13", "x/")):
            with self.subTest(art=art, line=line, batch=batch):
                with self.assertRaises(osm.InvalidKey):
                    osm.object_key(line, batch, art)

    def test_preflight_key_lives_under_reserved_dir(self):
        self.assertTrue(osm.preflight_key("nalu", "abc").startswith("nalu/_preflight/preflight-abc"))


class CredentialsTest(unittest.TestCase):
    def test_credentials_come_from_environment_only(self):
        with self.assertRaises(osm.CredentialsMissing):
            osm.resolve_credentials(env={}, profile=None)
        creds = osm.resolve_credentials(env=ENV)
        self.assertEqual(creds.source, "environment")
        self.assertNotIn(SECRET_SENTINEL, repr(creds))

    def test_config_never_carries_or_prints_secrets(self):
        with self.assertRaises(osm.UploadRefused):
            osm.ObjectStoreConfig.from_mapping({**CFG, "secret_key": "x"}, env=ENV)
        cfg = osm.ObjectStoreConfig.from_mapping(CFG, env=ENV)
        blob = json.dumps(cfg.to_dict()) + repr(cfg)
        self.assertNotIn(SECRET_SENTINEL, blob)
        self.assertNotIn("sentinel-access-key", blob)
        self.assertEqual(cfg.to_dict()["credentials"], "FROM_ENVIRONMENT")
        self.assertEqual(cfg.addressing_style, "path")
        self.assertEqual(cfg.signature_version, "s3v4")

    def test_endpoint_and_bucket_from_env_when_config_absent(self):
        cfg = osm.ObjectStoreConfig.from_mapping({}, env={**ENV, osm.ENV_BUCKET: "Drama01"})
        self.assertEqual((cfg.endpoint_url, cfg.bucket), ("https://s3.example.test", "drama01"))
        with self.assertRaises(osm.ObjectStoreError):
            osm.ObjectStoreConfig.from_mapping({}, env=ENV)


class PreflightTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_put_get_delete_verify_and_receipt(self):
        store, fake = _store(self.tmp)
        rec = store.preflight()
        self.assertEqual(rec["status"], "PASSED", rec)
        self.assertEqual([s["op"] for s in rec["steps"]], ["PUT", "GET", "DELETE", "VERIFY_GONE"])
        self.assertTrue(all(s["ok"] for s in rec["steps"]))
        self.assertEqual(rec["size"], 1024)
        self.assertTrue(rec["key"].startswith("nalu/_preflight/"))
        self.assertEqual(fake.objects, {}, "preflight object must be deleted")
        saved = json.loads((self.tmp / osm.PREFLIGHT_RECEIPT).read_text())
        self.assertEqual(saved["status"], "PASSED")
        self.assertNotIn(SECRET_SENTINEL, json.dumps(saved))
        self.assertEqual(saved["credentials"], "FROM_ENVIRONMENT")
        self.assertEqual(store.preflight_status(), (True, "ok"))

    def test_corrupted_readback_fails_and_still_cleans_up(self):
        store, fake = _store(self.tmp)
        fake.corrupt_get = True
        rec = store.preflight()
        self.assertEqual(rec["status"], "FAILED")
        get = next(s for s in rec["steps"] if s["op"] == "GET")
        self.assertFalse(get["ok"])
        self.assertIn("bytes differ", get["error"])
        self.assertIn("DELETE", [s["op"] for s in rec["steps"]])
        self.assertEqual(fake.objects, {})
        with self.assertRaises(osm.PreflightRequired):
            store.require_preflight()

    def test_delete_not_honoured_fails(self):
        store, fake = _store(self.tmp)
        fake.ignore_delete = True
        rec = store.preflight()
        self.assertEqual(rec["status"], "FAILED")
        gone = next(s for s in rec["steps"] if s["op"] == "VERIFY_GONE")
        self.assertIn("still present", gone["error"])

    def test_put_failure_is_reported_with_error_code(self):
        store, fake = _store(self.tmp)
        fake.fail_put = _S3Error("AccessDenied")
        rec = store.preflight()
        self.assertEqual(rec["status"], "FAILED")
        self.assertEqual(rec["steps"][0]["code"], "AccessDenied")
        self.assertEqual(len(rec["steps"]), 1)

    def test_receipt_is_reloaded_and_expires(self):
        now = [1_000_000.0]
        store, fake = _store(self.tmp, clock=lambda: now[0])
        store.preflight()
        again, _ = _store(self.tmp, fake, clock=lambda: now[0])  # fresh instance reads the receipt
        self.assertEqual(again.preflight_status(), (True, "ok"))
        now[0] += osm.PREFLIGHT_MAX_AGE_S + 1
        ok, why = again.preflight_status()
        self.assertFalse(ok)
        self.assertIn("stale", why)
        other, _ = _store(self.tmp, fake, bucket="other", clock=lambda: 1_000_000.0)
        self.assertIn("different endpoint/bucket", other.preflight_status()[1])
        other_line, _ = _store(self.tmp, fake, line="qingshan", clock=lambda: 1_000_000.0)
        self.assertIn("different line", other_line.preflight_status()[1])


class FormalPathTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store, self.fake = _store(self.tmp)

    def test_requires_preflight_then_uploads_with_public_url(self):
        with self.assertRaises(osm.PreflightRequired):
            self.store.put_artifact("E13", "digest.json", b"{}", content_type="application/json")
        self.store.preflight()
        out = self.store.put_artifact("E13", "reports/digest.json", b'{"ok": true}', content_type="application/json")
        self.assertEqual(out["key"], "nalu/e13/reports/digest.json")
        self.assertEqual(out["public_url"], "https://cdn.example.test/drama01/nalu/e13/reports/digest.json")
        self.assertEqual(out["sha256"], c.sha256_bytes(b'{"ok": true}'))
        self.assertTrue(out["public_read"])
        self.assertEqual(self.store.get_bytes(out["key"]), b'{"ok": true}')

    def test_media_refused_by_default_allowed_only_explicitly(self):
        self.store.preflight()
        with self.assertRaises(osm.UploadRefused):
            self.store.put_artifact("E13", "clip.mp4", b"\x00\x00\x00\x18ftyp", content_type="video/mp4")
        with self.assertRaises(osm.UploadRefused):
            self.store.put_artifact("E13", "frame.png", b"\x89PNG", content_type="image/png")
        allowed, fake = _store(self.tmp, self.fake, allow_media=True)
        out = allowed.put_artifact("E13", "clip.mp4", b"\x00\x00\x00\x18ftyp", content_type="video/mp4")
        self.assertEqual(out["content_type"], "video/mp4")

    def test_sensitive_text_or_metadata_refused_because_public(self):
        self.store.preflight()
        home = "/Us" + "ers/someone/nalu_runtime/x.json"
        with self.assertRaises(osm.UploadRefused) as ctx:
            self.store.put_artifact("E13", "r.json", json.dumps({"path": home}).encode(), content_type="application/json")
        self.assertTrue(any("ABSOLUTE_HOME_PATH" in f for f in ctx.exception.findings))
        with self.assertRaises(osm.UploadRefused):
            self.store.put_artifact("E13", "r.json", b"{}", content_type="application/json",
                                    metadata={"url": "https://x/y?X-Amz-Signature=abc"})
        with self.assertRaises(osm.UploadRefused):
            self.store.put_artifact("E13", "r.txt", b"\xff\xfe", content_type="text/plain")
        self.assertEqual(self.fake.objects, {})

    def test_reserved_preflight_dir_and_empty_payload_refused(self):
        self.store.preflight()
        with self.assertRaises(osm.UploadRefused):
            self.store.put_artifact("_preflight", "x.json", b"{}", content_type="application/json")
        with self.assertRaises(osm.UploadRefused):
            self.store.put_artifact("E13", "x.json", b"", content_type="application/json")

    def test_rename_is_copy_plus_delete_and_list_paginates(self):
        self.store.preflight()
        for i in range(3):
            self.store.put_artifact("E13", f"u{i}.json", b"{}", content_type="application/json")
        self.fake.calls.clear()
        out = self.store.rename("nalu/e13/u0.json", "nalu/e13/moved.json")
        self.assertEqual(out["method"], "copy+delete")
        self.assertEqual(self.fake.calls[:2], ["copy_object", "head_object"])
        self.assertIn("delete_object", self.fake.calls)
        self.assertIsNone(self.store.head("nalu/e13/u0.json"))
        keys = [r["key"] for r in self.store.list("nalu/e13/", limit=2)]
        self.assertEqual(len(keys), 2)
        self.assertEqual(len(self.store.list("nalu/")), 3)

    def test_module_source_never_calls_unsupported_gateway_apis(self):
        src = (ROOT / "tools" / "collective_learning" / "object_store.py").read_text(encoding="utf-8")
        calls = re.findall(r"client\.([a-z_0-9]+)\(", src)
        self.assertTrue(calls)
        for name in calls:
            self.assertNotIn(name, osm.UNSUPPORTED_OPERATIONS, name)
        self.assertNotIn("StorageClass", src)

    def test_upload_evidence_registers_storage_key_without_urls(self):
        self.store.preflight()
        seen: list[dict] = []

        def register(meta):
            self.assertEqual(c.sensitive_findings({k: v for k, v in meta.items() if k != "sha256"}), [])
            seen.append(meta)
            return {"evidence_id": meta["evidence_id"], "status": "REGISTERED"}

        out = osm.upload_evidence(self.store, batch_id="E13", artifact="vu-006/review.json",
                                  data=b'{"score": 1}', content_type="application/json", register=register,
                                  links={"CANDIDATE": ["cand-1"]}, retention_until="2027-01-01T00:00:00Z")
        self.assertEqual(out["registered"]["status"], "REGISTERED")
        self.assertEqual(seen[0]["storage_key"], "nalu/e13/vu-006/review.json")
        self.assertTrue(c.is_sha256(seen[0]["sha256"]))
        self.assertEqual(seen[0]["links"], {"CANDIDATE": ["cand-1"]})
        self.assertTrue(seen[0]["public_read"])


class ServiceMirrorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.store, self.fake = _store(self.tmp, line=osm.SERVICE_LINE)
        self.store.preflight()
        self.svc = svc_mod.Service(self.tmp / "svc.sqlite", signature_verifier=lambda b, p: (True, "TEST"),
                                   object_store=self.store)
        boot = self.svc.bootstrap_tenant("tenant-a", admin_id="admin-1")
        self.admin = self.svc.authenticate(boot["token"])
        pub = self.svc.register_principal(self.admin, principal_id="pub-1", role="publisher")
        self.pub = self.svc.authenticate(pub["token"])

    def _body(self, version="1", payload=b'{"rules": []}'):
        import base64
        return {"bundle_id": "b1", "version": version, "digest": c.sha256_bytes(payload),
                "payload_b64": base64.b64encode(payload).decode(), "signature_b64": "sig", "key_id": "k1",
                "manifest": {"scope": {"models": ["M"], "stages": ["S6"]}}}

    def test_bundle_mirrored_under_collective_prefix(self):
        out = self.svc.upload_bundle(self.pub, self._body())
        self.assertEqual(out["object_mirror"]["status"], "MIRRORED", out)
        self.assertEqual(out["object_mirror"]["key"], "collective/tenant-a/bundles/b1/1.json")
        self.assertIn(("drama01", "collective/tenant-a/bundles/b1/1.json"), self.fake.objects)
        self.assertEqual(self.store.get_bytes(out["object_mirror"]["key"]), b'{"rules": []}')
        self.assertEqual(self.svc.get_bundle(self.pub, "b1", "1")["digest"], out["digest"])

    def test_mirror_failure_never_fails_the_upload(self):
        self.fake.fail_put = _S3Error("AccessDenied")
        out = self.svc.upload_bundle(self.pub, self._body(version="2"))
        self.assertEqual(out["object_mirror"]["status"], "MIRROR_FAILED")
        self.assertIn("AccessDenied", out["object_mirror"]["error"])
        self.assertEqual(self.svc.get_bundle(self.pub, "b1", "2")["digest"], out["digest"])

    def test_without_object_store_nothing_changes(self):
        svc = svc_mod.Service(self.tmp / "plain.sqlite", signature_verifier=lambda b, p: (True, "TEST"))
        boot = svc.bootstrap_tenant("t", admin_id="a")
        admin = svc.authenticate(boot["token"])
        out = svc.upload_bundle(admin, self._body())
        self.assertEqual(out["object_mirror"], {"status": "NOT_CONFIGURED"})


class DocumentationTest(unittest.TestCase):
    def test_ops_doc_names_endpoint_and_keeps_secrets_out(self):
        doc = (ROOT / "docs" / "collective_learning" / "DEPLOYMENT_OPERATIONS.md").read_text(encoding="utf-8")
        self.assertIn("s3api.arkfs.co", doc)
        self.assertIn("drama01", doc)
        self.assertIn("us-east-1", doc)
        self.assertIn("环境变量", doc)
        for path in (ROOT / "docs" / "collective_learning").glob("*.md"):
            text = path.read_text(encoding="utf-8")
            for m in re.finditer(r"AWS_SECRET_ACCESS_KEY\s*[=:]\s*(\S+)", text):
                self.assertTrue(m.group(1).startswith(("<", "$", "`<", "…", "(")), f"{path.name}: {m.group(0)}")
        src = (ROOT / "tools" / "collective_learning" / "object_store.py").read_text(encoding="utf-8")
        self.assertEqual(c.sensitive_findings({"src": src}), [])


if __name__ == "__main__":
    unittest.main()
