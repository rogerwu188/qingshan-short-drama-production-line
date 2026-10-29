"""s3ctl: the command-line wrapper every line uses instead of the AWS CLI."""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from tools import s3ctl
from tools.collective_learning import object_store as osm
from tools.tests.fake_s3 import FakeS3, S3Error

SECRET = "SENTINEL-SECRET-0123456789"
ENV = {
    osm.ENV_ACCESS_KEY: "sentinel-access", osm.ENV_SECRET_KEY: SECRET,
    "S3CTL_ENDPOINT_URL": "https://s3.example.test", "S3CTL_BUCKET": "drama01",
    "S3CTL_PUBLIC_BASE_URL": "https://cdn.example.test/drama01",
}


class S3ctlTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fake = FakeS3()
        self.env = {**ENV, "S3CTL_RECEIPT_DIR": str(self.tmp)}

    def run_cmd(self, *argv: str, env=None) -> tuple[int, dict]:
        buf = io.StringIO()
        code = s3ctl.main(list(argv), env=env or self.env, client_factory=lambda cfg, creds: self.fake, out=buf)
        return code, json.loads(buf.getvalue())

    def test_config_shows_no_secret_and_credential_source(self):
        code, out = self.run_cmd("config")
        self.assertEqual(code, 0)
        self.assertEqual(out["credentials"]["status"], "PRESENT")
        self.assertNotIn(SECRET, json.dumps(out))
        self.assertEqual(out["endpoint_url"], "https://s3.example.test")
        code, out = self.run_cmd("config", env={k: v for k, v in self.env.items() if k != osm.ENV_SECRET_KEY})
        self.assertEqual(out["credentials"]["status"], "MISSING")

    def test_missing_endpoint_is_a_clear_error(self):
        env = {k: v for k, v in self.env.items() if k != "S3CTL_ENDPOINT_URL"}
        code, out = self.run_cmd("ls", "nalu/", env=env)
        self.assertEqual((code, out["code"]), (2, "CONFIG_MISSING"))

    def test_put_requires_preflight_then_full_round_trip(self):
        src = self.tmp / "digest.json"
        src.write_text('{"ok": true}')
        code, out = self.run_cmd("put", str(src), "nalu/E13/reports/digest.json")
        self.assertEqual((code, out["code"]), (2, "PREFLIGHT_REQUIRED"))

        code, out = self.run_cmd("preflight", "nalu")
        self.assertEqual((code, out["status"]), (0, "PASSED"))
        self.assertTrue(Path(out["receipt_path"]).is_file())
        self.assertEqual(Path(out["receipt_path"]).parent, self.tmp)

        code, out = self.run_cmd("put", str(src), "nalu/E13/reports/digest.json")
        self.assertEqual((code, out["status"]), (0, "UPLOADED"), out)
        self.assertEqual(out["key"], "nalu/e13/reports/digest.json")
        self.assertEqual(out["content_type"], "application/json")
        self.assertEqual(out["public_url"], "https://cdn.example.test/drama01/nalu/e13/reports/digest.json")

        code, out = self.run_cmd("ls", "nalu/e13/")
        self.assertEqual([o["key"] for o in out["objects"]], ["nalu/e13/reports/digest.json"])
        code, out = self.run_cmd("head", "nalu/e13/reports/digest.json")
        self.assertEqual(out["size"], 12)
        code, out = self.run_cmd("url", "nalu/e13/reports/digest.json")
        self.assertEqual(out["public_url"], "https://cdn.example.test/drama01/nalu/e13/reports/digest.json")

        dest = self.tmp / "down" / "digest.json"
        code, out = self.run_cmd("get", "nalu/e13/reports/digest.json", str(dest))
        self.assertEqual((code, out["status"]), (0, "DOWNLOADED"))
        self.assertEqual(dest.read_text(), '{"ok": true}')

        code, out = self.run_cmd("mv", "nalu/e13/reports/digest.json", "nalu/e13/reports/moved.json")
        self.assertEqual(out["method"], "copy+delete")
        code, out = self.run_cmd("head", "nalu/e13/reports/digest.json")
        self.assertEqual((code, out["code"]), (2, "NOT_FOUND"))
        code, out = self.run_cmd("rm", "nalu/e13/reports/moved.json")
        self.assertEqual(out["status"], "DELETED")
        self.assertEqual(self.fake.objects, {})

    def test_media_and_sensitive_content_refused_through_the_cli(self):
        self.run_cmd("preflight", "nalu")
        clip = self.tmp / "clip.mp4"
        clip.write_bytes(b"\x00\x00\x00\x18ftyp")
        code, out = self.run_cmd("put", str(clip), "nalu/e13/clip.mp4")
        self.assertEqual((code, out["code"]), (2, "UPLOAD_REFUSED"))
        code, out = self.run_cmd("put", str(clip), "nalu/e13/clip.mp4", "--allow-media")
        self.assertEqual((code, out["status"]), (0, "UPLOADED"))
        leak = self.tmp / "leak.json"
        leak.write_text(json.dumps({"path": "/Us" + "ers/x/y.json"}))
        code, out = self.run_cmd("put", str(leak), "nalu/e13/leak.json")
        self.assertEqual((code, out["code"]), (2, "UPLOAD_REFUSED"))
        self.assertNotIn("nalu/e13/leak.json", [k for _, k in self.fake.objects])

    def test_bad_keys_and_cross_line_moves_are_rejected(self):
        self.run_cmd("preflight", "nalu")
        src = self.tmp / "a.json"
        src.write_text("{}")
        for key in ("/nalu/e13/a.json", "nalu/a.json", "nalu/e13/with space.json"):
            code, out = self.run_cmd("put", str(src), key)
            self.assertEqual(code, 2, key)
            self.assertIn(out["code"], ("INVALID_KEY", "INVALID_OBJECT_KEY"), key)
        self.run_cmd("put", str(src), "nalu/e13/a.json")
        code, out = self.run_cmd("mv", "nalu/e13/a.json", "qingshan/e50/a.json")
        self.assertEqual((code, out["code"]), (2, "CROSS_LINE_MOVE"))
        code, out = self.run_cmd("put", str(src), "nalu/_preflight/a.json")
        self.assertEqual((code, out["code"]), (2, "UPLOAD_REFUSED"))

    def test_sync_directory_skips_same_size_and_reports_refusals(self):
        self.run_cmd("preflight", "nalu")
        out_dir = self.tmp / "out"
        (out_dir / "sub").mkdir(parents=True)
        (out_dir / "a.json").write_text("{}")
        (out_dir / "sub" / "b.md").write_text("# b")
        (out_dir / "bad name.json").write_text("{}")
        (out_dir / ".hidden").write_text("x")
        code, out = self.run_cmd("sync", str(out_dir), "nalu/E13/reports/")
        self.assertEqual((code, out["status"]), (2, "PARTIAL"))
        self.assertEqual(sorted(u["key"] for u in out["uploaded"]),
                         ["nalu/e13/reports/a.json", "nalu/e13/reports/sub/b.md"])
        self.assertEqual(out["refused"][0]["file"], "bad name.json")
        code, out = self.run_cmd("sync", str(out_dir), "nalu/E13/reports/")
        self.assertEqual(len(out["skipped"]), 2)
        self.assertEqual(out["uploaded"], [])
        code, out = self.run_cmd("sync", str(out_dir), "nalu/E13/reports/", "--force")
        self.assertEqual(len(out["uploaded"]), 2)
        code, out = self.run_cmd("sync", str(out_dir), "nalu")
        self.assertEqual(out["code"], "INVALID_KEY")

    def test_recursive_rm_needs_yes(self):
        self.run_cmd("preflight", "nalu")
        src = self.tmp / "a.json"
        src.write_text("{}")
        self.run_cmd("put", str(src), "nalu/e13/a.json")
        self.run_cmd("put", str(src), "nalu/e13/b.json")
        code, out = self.run_cmd("rm", "nalu/e13/", "--recursive")
        self.assertEqual((code, out["code"]), (2, "CONFIRMATION_REQUIRED"))
        code, out = self.run_cmd("rm", "nalu/e13/", "--recursive", "--yes")
        self.assertEqual((code, out["count"]), (0, 2))
        self.assertEqual(self.fake.objects, {})

    def test_provider_error_surfaces_code_without_request(self):
        self.run_cmd("preflight", "nalu")
        self.fake.fail_put = S3Error("AccessDenied")
        src = self.tmp / "a.json"
        src.write_text("{}")
        code, out = self.run_cmd("put", str(src), "nalu/e13/a.json")
        self.assertEqual((code, out["code"]), (2, "AccessDenied"))
        self.assertNotIn(SECRET, json.dumps(out))

    def test_failed_preflight_exits_nonzero(self):
        self.fake.corrupt_get = True
        code, out = self.run_cmd("preflight", "nalu")
        self.assertEqual((code, out["status"]), (2, "FAILED"))


if __name__ == "__main__":
    unittest.main()
