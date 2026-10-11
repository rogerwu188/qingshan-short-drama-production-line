"""skills/nalu-claude-code publish_x2creel: create once, append later, never send an episode twice."""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/nalu-claude-code/scripts"
sys.path.insert(0, str(SCRIPTS))
import publish_x2creel as px  # noqa: E402


class PublishFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        os.environ["NALU_RUNTIME_ROOT"] = str(root)
        os.environ["X2C_API_KEY"] = "x2c_sk_test"
        for ep in ("E01", "E02"):
            d = root / "deliverables" / ep
            d.mkdir(parents=True)
            (d / f"{ep}_final_9x16.mp4").write_bytes(f"video-{ep}".encode())
        (root / "cover.jpg").write_bytes(b"jpg")
        self.cover = str(root / "cover.jpg")
        self.calls: list[tuple[str, dict]] = []
        self.puts: list[str] = []

        def fake_call(action, **payload):
            self.calls.append((action, payload))
            if action == "distribution/upload-url":
                return {"success": True, "uploads": [
                    {"file_type": f["file_type"], "upload_url": "https://s3/put/" + f["file_name"],
                     "public_url": "https://v/" + f["file_name"], "upload_headers": {}} for f in payload["files"]]}
            if action == "distribution/categories":
                return {"success": True, "categories": [{"id": "c" * 36, "name": "仙侠古装", "name_key": "xianxia"}]}
            if action == "distribution/publish":
                return {"success": True, "project_id": "proj-1", "status": "pending_review",
                        "episodes": [{"episode_number": 1}]}
            if action == "distribution/add-episodes":
                return {"success": True, "new_episodes": [{"episode_number": 2}], "routed_to": "writer_director"}
            raise AssertionError(action)

        self.saved = (px.call, px.put_file)
        px.call = fake_call
        px.put_file = lambda upload, path: self.puts.append(upload["upload_url"])

    def tearDown(self):
        px.call, px.put_file = self.saved
        self.tmp.cleanup()

    def args(self, ep, **kw):
        base = dict(episode=ep, title="", description="", category="", video="", cover="")
        base.update(kw)
        return argparse.Namespace(**base)

    def test_first_episode_creates_project_then_appends_and_is_idempotent(self):
        out = px.cmd_publish(self.args("E01", title="剧名", description="简介", category="仙侠古装", cover=self.cover))
        self.assertEqual(out["status"], "PUBLISHED")
        self.assertEqual(out["project_id"], "proj-1")
        publish = next(p for a, p in self.calls if a == "distribution/publish")
        self.assertEqual(publish["category_id"], "c" * 36)
        self.assertEqual(publish["video_urls"], ["https://v/E01.mp4"])
        self.assertEqual(len(self.puts), 2)  # cover + video

        again = px.cmd_publish(self.args("E01"))
        self.assertEqual(again["status"], "ALREADY_PUBLISHED")

        out2 = px.cmd_publish(self.args("E02"))
        self.assertEqual(out2["status"], "PUBLISHED")
        self.assertEqual(out2["episode_number"], 2)
        add = next(p for a, p in self.calls if a == "distribution/add-episodes")
        self.assertEqual(add["project_id"], "proj-1")
        self.assertEqual(sum(1 for a, _ in self.calls if a == "distribution/publish"), 1)

    def test_first_publish_requires_metadata(self):
        out = px.cmd_publish(self.args("E01", cover=self.cover))
        self.assertEqual(out["status"], "BLOCKED")
        self.assertEqual(self.calls, [])  # nothing uploaded before the metadata check


if __name__ == "__main__":
    unittest.main()
