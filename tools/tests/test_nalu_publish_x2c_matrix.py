"""skills/nalu-claude-code publish_x2c_matrix: X2C 设备矩阵 API through a fake HTTP layer (no network)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/nalu-claude-code/scripts"
sys.path.insert(0, str(SCRIPTS))
import publish_x2c_matrix as mx  # noqa: E402
import publish_x2creel as px  # noqa: E402

ENV = ("NALU_RUNTIME_ROOT", "X2C_API_KEY", "NALU_DEVICE_SN", "NALU_DEVICE_NAME", "X2C_API_MODE", "X2C_MATRIX_API_URL")


class FakeX2C:
    """Answers like the matrix API: idempotency key = device + series_key + episode_number."""

    def __init__(self):
        self.requests: list[tuple[str, dict, dict]] = []
        self.episodes: dict[tuple, dict] = {}
        self.fail_next: list[tuple[int, dict] | Exception] = []
        self.n = 0

    def __call__(self, url, body, headers):
        endpoint = url.split("/matrix-api/v1/", 1)[1]
        payload = json.loads(body)
        self.requests.append((endpoint, payload, headers))
        if self.fail_next:
            nxt = self.fail_next.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
            return nxt
        if endpoint == "distribution/upload-url":
            self.n += 1
            ext = {"video/mp4": "mp4", "image/jpeg": "jpg", "image/png": "png"}[payload["content_type"]]
            return 200, {"upload_url": f"https://s/put/{self.n}.{ext}", "upload_method": "PUT",
                         "upload_headers": {"Content-Type": payload["content_type"]},
                         "public_url": f"https://s/pub/{self.n}.{ext}"}
        if endpoint in ("distribution/publish", "distribution/add-episodes"):
            key = (payload["device_sn"], payload["series_key"], payload["episode_number"])
            if key in self.episodes:
                old = self.episodes[key]
                if old["payload"] != payload:
                    return 409, {"code": "EPISODE_CONFLICT", "error": "different content"}
                return 200, {**old["receipt"], "idempotent": True}
            if endpoint == "distribution/add-episodes" and not any(k[1] == payload["series_key"] for k in self.episodes):
                return 404, {"code": "SERIES_NOT_FOUND", "error": "no series"}
            receipt = {"project_id": "p-1", "episode_id": f"e-{payload['episode_number']}",
                       "episode_number": payload["episode_number"], "account_id": None,
                       "routing_status": "UNMAPPED_PENDING", "review_status": "pending_review"}
            self.episodes[key] = {"payload": payload, "receipt": receipt}
            return 202, receipt
        if endpoint == "distribution/status":
            eps = [{"id": v["receipt"]["episode_id"], "episode_number": k[2], "review_status": "pending_review",
                    "review_note": None, "matrix_jobs": None} for k, v in self.episodes.items()]
            page = eps[payload["offset"]:payload["offset"] + 1]  # one per page to exercise next_offset
            nxt = payload["offset"] + 1 if payload["offset"] + 1 < len(eps) else None
            return 200, {"project_id": payload["project_id"], "series_key": "s", "account_id": None, "closed": False,
                         "routing_status": "UNMAPPED_PENDING", "blocked_reason": "ACCOUNT_UNASSIGNED",
                         "episodes": page, "next_offset": nxt}
        if endpoint == "distribution/list":
            return 200, {"projects": [{"project_id": "p-1", "series_key": "s", "closed": False}]}
        if endpoint == "distribution/close":
            return 200, {"closed": True, "project_id": payload["project_id"]}
        return 404, {"code": "UNKNOWN_ROUTE", "error": endpoint}


class MatrixPublishTests(unittest.TestCase):
    def setUp(self):
        self.env = {k: os.environ.get(k) for k in ENV}
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = Path(self.tmp.name)
        os.environ.update(NALU_RUNTIME_ROOT=str(root), X2C_API_KEY="x2c_sk_test", NALU_DEVICE_SN="test_00111")
        for k in ("NALU_DEVICE_NAME", "X2C_API_MODE", "X2C_MATRIX_API_URL"):
            os.environ.pop(k, None)
        (root / "briefs").mkdir()
        for i, ep in enumerate(("E03", "E04", "E05"), start=2):
            d = root / "deliverables" / ep
            d.mkdir(parents=True)
            (d / f"{ep}_final_9x16.mp4").write_bytes(f"video-{ep}".encode())
            (d / f"{ep}_final_9x16_AD.mp4").write_bytes(f"ad-{ep}".encode())
            (root / "briefs" / f"{ep}_PRODUCTION_BRIEF.json").write_text(json.dumps(
                {"title": "Sherlock Holmes: The Blue Carbuncle", "synopsis": "A goose, a gem.",
                 "genre_lang": "en", "episode_display_number": i - 1}), encoding="utf-8")
        (root / "cover.jpg").write_bytes(b"jpg")
        self.fake = FakeX2C()
        self.puts: list[tuple[str, str]] = []
        self.saved = (mx._post, mx.SLEEP, px.put_file, px.cover_from_video, mx.duration_seconds)
        mx._post = self.fake
        mx.SLEEP = lambda s: None
        px.put_file = lambda up, path: self.puts.append((up["upload_url"], path.name))
        px.cover_from_video = lambda video: root / "cover.jpg"
        mx.duration_seconds = lambda path: 97.5

    def tearDown(self):
        mx._post, mx.SLEEP, px.put_file, px.cover_from_video, mx.duration_seconds = self.saved
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def args(self, ep, **kw):
        base = dict(episode=ep, title="", description="", hashtags="", video="", cover="", series_key="", lang="",
                    episode_number=None, resend=False)
        base.update(kw)
        return argparse.Namespace(**base)

    def sent(self, endpoint):
        return [p for e, p, _ in self.fake.requests if e == endpoint]

    def test_mode_selection(self):
        self.assertTrue(mx.matrix_mode())  # NALU_DEVICE_SN set
        os.environ["X2C_API_MODE"] = "open"
        self.assertFalse(mx.matrix_mode())
        os.environ.pop("X2C_API_MODE")
        os.environ.pop("NALU_DEVICE_SN")
        self.assertFalse(mx.matrix_mode())
        os.environ["X2C_API_MODE"] = "matrix"
        self.assertTrue(mx.matrix_mode())
        self.assertEqual(mx.environment(), "TEST")
        os.environ["X2C_MATRIX_API_URL"] = mx.PROD_API
        self.assertEqual(mx.environment(), "PRODUCTION")
        os.environ.pop("X2C_MATRIX_API_URL")
        with self.assertRaises(SystemExit) as raised:
            mx.device_sn()
        self.assertIn("NALU_DEVICE_SN_MISSING", str(raised.exception.code))

    def test_first_publish_then_add_episodes_with_brief_metadata(self):
        out = mx.cmd_publish(self.args("E03"))
        self.assertEqual((out["status"], out["http"], out["endpoint"]), ("PUBLISHED", 202, "distribution/publish"))
        self.assertEqual((out["project_id"], out["routing_status"]), ("p-1", "UNMAPPED_PENDING"))
        body = self.sent("distribution/publish")[0]
        self.assertEqual(body["series_key"], "sherlock-holmes-the-blue-carbuncle-en")
        self.assertEqual(body["episode_number"], 1)
        self.assertEqual(body["device_sn"], "test_00111")
        self.assertEqual(body["duration_seconds"], 97.5)
        self.assertEqual(body["description"], "A goose, a gem.")
        self.assertNotIn("hashtags", body)
        self.assertEqual([n for _, n in self.puts], ["E03_final_9x16.mp4", "cover.jpg"])  # clean final, not _AD
        self.assertEqual([p["content_type"] for p in self.sent("distribution/upload-url")], ["video/mp4", "image/jpeg"])
        headers = self.fake.requests[0][2]
        self.assertEqual(headers["X-API-Key"], "x2c_sk_test")
        self.assertNotIn("action", body)

        out2 = mx.cmd_publish(self.args("E04"))
        self.assertEqual((out2["endpoint"], out2["episode_number"]), ("distribution/add-episodes", 2))
        self.assertEqual(self.sent("distribution/add-episodes")[0]["series_key"], body["series_key"])
        state = mx.load_state()
        self.assertEqual(state["current_series"], body["series_key"])
        self.assertEqual(set(mx.sent_episodes()), {"E03", "E04"})
        self.assertEqual(state["series"][body["series_key"]]["episodes"]["E04"]["episode_id"], "e-2")
        self.assertNotIn("x2c_sk_test", mx.state_path().read_text(encoding="utf-8"))

    def test_rerun_is_local_and_resend_hits_x2c_idempotently(self):
        mx.cmd_publish(self.args("E03"))
        n = len(self.fake.requests)
        self.assertEqual(mx.cmd_publish(self.args("E03"))["status"], "ALREADY_PUBLISHED")
        self.assertEqual(len(self.fake.requests), n)
        again = mx.cmd_publish(self.args("E03", resend=True))
        self.assertEqual((again["http"], again["idempotent"]), (200, True))
        self.assertEqual(self.sent("distribution/upload-url").__len__(), 2)  # nothing re-uploaded
        self.assertEqual(len(self.fake.episodes), 1)

    def test_crash_after_upload_resends_the_same_body(self):
        # uploads succeed, then the process dies during the publish POST; the body is already saved
        orig = self.fake.__call__

        def flaky(url, body, headers):
            if url.endswith("distribution/publish") and not getattr(flaky, "done", False):
                flaky.done = True
                raise SystemExit(json.dumps({"status": "ERROR", "simulated": "crash"}))
            return orig(url, body, headers)
        mx._post = flaky
        with self.assertRaises(SystemExit):
            mx.cmd_publish(self.args("E03"))
        self.assertEqual(mx.sent_episodes(), {})
        out = mx.cmd_publish(self.args("E03"))
        self.assertEqual(out["status"], "PUBLISHED")
        self.assertEqual(len(self.sent("distribution/upload-url")), 2)  # the retry reused the uploaded URLs

    def test_retries_network_503_429_then_reports_4xx_with_code(self):
        self.fake.fail_next = [urllib.error.URLError("down"), (503, {"code": "BACKEND_UNAVAILABLE"}),
                               (429, {"code": "RATE_LIMITED"})]
        self.assertEqual(mx.cmd_publish(self.args("E03"))["status"], "PUBLISHED")
        self.fake.fail_next = [(404, {"code": "DEVICE_NOT_FOUND", "error": "Device not found for this user"})]
        with self.assertRaises(SystemExit) as raised:
            mx.cmd_list(argparse.Namespace())
        err = json.loads(raised.exception.code)
        self.assertEqual((err["http"], err["code"]), (404, "DEVICE_NOT_FOUND"))
        self.assertNotIn("x2c_sk_test", raised.exception.code)

    def test_new_cut_of_a_sent_episode_is_blocked_not_rekeyed(self):
        mx.cmd_publish(self.args("E03"))
        (self.root / "deliverables/E03/E03_final_9x16.mp4").write_bytes(b"recut")
        out = mx.cmd_publish(self.args("E03"))
        self.assertEqual(out["reason"], "EPISODE_ALREADY_SENT_WITH_OTHER_VIDEO")
        self.assertEqual(len(self.sent("distribution/publish")), 1)

    def test_status_pages_and_maps_local_episodes_list_and_close(self):
        mx.cmd_publish(self.args("E03"))
        mx.cmd_publish(self.args("E04"))
        st = mx.cmd_status(argparse.Namespace(series=None))
        self.assertEqual([e["local_episode"] for e in st["episodes"]], ["E03", "E04"])
        self.assertEqual(st["episodes"][0]["review_status"], "pending_review")
        self.assertEqual(len(self.sent("distribution/status")), 2)
        self.assertEqual(mx.cmd_list(argparse.Namespace())["projects"][0]["project_id"], "p-1")
        key = mx.load_state()["current_series"]
        self.assertEqual(mx.cmd_close(argparse.Namespace(series=key))["status"], "CLOSED")
        self.assertEqual(self.sent("distribution/close")[0], {"device_sn": "test_00111", "project_id": "p-1"})
        self.assertIsNone(mx.load_state()["current_series"])
        self.assertEqual(mx.cmd_publish(self.args("E05"))["reason"], "SERIES_CLOSED")

    def test_explicit_overrides_and_one_open_series(self):
        out = mx.cmd_publish(self.args("E05", series_key="holmes-test", episode_number=1, hashtags="#Holmes,bad tag",
                                       cover=str(self.root / "cover.jpg")))
        body = self.sent("distribution/publish")[0]
        self.assertEqual((body["series_key"], body["episode_number"], body["hashtags"]), ("holmes-test", 1, ["#Holmes"]))
        self.assertEqual(out["series_key"], "holmes-test")
        other = mx.cmd_publish(self.args("E03", series_key="another"))
        self.assertEqual(other["reason"], "ANOTHER_SERIES_OPEN")
        taken = mx.cmd_publish(self.args("E04", episode_number=1))
        self.assertEqual(taken["reason"], "EPISODE_NUMBER_TAKEN")

    def test_legacy_cli_dispatches_to_matrix(self):
        import contextlib
        import io
        argv = sys.argv
        sys.argv = ["publish_x2creel.py", "list"]
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                self.assertEqual(px.main(), 0)
        finally:
            sys.argv = argv
        self.assertEqual(json.loads(buf.getvalue())["device_sn"], "test_00111")


if __name__ == "__main__":
    unittest.main()
