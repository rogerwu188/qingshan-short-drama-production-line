"""X2C 广告创意上下文 (skills/nalu-claude-code/scripts/x2c_creative_context.py) through a fake HTTP layer (no network)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/nalu-claude-code/scripts"
sys.path.insert(0, str(SCRIPTS))
import publish_x2c_matrix as mx  # noqa: E402
import publish_x2creel as px  # noqa: E402
import x2c_creative_context as xcc  # noqa: E402

ENV = ("NALU_RUNTIME_ROOT", "NALU_ENGINE_ROOT", "X2C_API_KEY", "NALU_DEVICE_SN", "X2C_API_MODE", "X2C_MATRIX_API_URL",
       "X2C_CREATIVE_CONTEXT", "QINGSHAN_VOICE_REGISTRY", "NALU_SERIES_SCOPES")
ANCHOR_A = "https://assets.giggle.pro/public/ai_director/aa/linqiao.wav"
ANCHOR_B = "https://assets.giggle.pro/public/ai_director/bb/zhouheng.wav"


class Fake:
    def __init__(self):
        self.requests: list[tuple[str, dict]] = []
        self.fail: dict[str, list[tuple[int, dict]]] = {}
        self.n = 0
        self.episodes: dict = {}

    def __call__(self, url, body, headers):
        assert url.startswith(mx.base_url() + "/"), url
        assert headers["X-API-Key"] == "x2c_sk_test"
        endpoint = url.split("/matrix-api/v1/", 1)[1]
        payload = json.loads(body)
        self.requests.append((endpoint, payload))
        if self.fail.get(endpoint):
            return self.fail[endpoint].pop(0)
        if endpoint == "distribution/upload-url":
            self.n += 1
            ext = {"video/mp4": "mp4", "image/jpeg": "jpg", "image/png": "png"}[payload["content_type"]]
            return 200, {"upload_url": f"https://s/put/{self.n}.{ext}?X-Amz-Signature=abc", "upload_method": "PUT",
                         "public_url": f"https://media.x2c.test/pub/{self.n}.{ext}"}
        if endpoint in ("distribution/publish", "distribution/add-episodes"):
            return 202, {"project_id": "p-1", "episode_id": f"e-{payload['episode_number']}",
                         "episode_number": payload["episode_number"], "review_status": "pending_review"}
        if endpoint == xcc.ENDPOINT:
            return 200, {"ok": True, "characters": [c["character_id"] for c in payload["characters"]]}
        if endpoint == xcc.RETIRE:
            return 200, {"ok": True, "retired_version": payload["voice_version"]}
        return 404, {"code": "UNKNOWN_ROUTE", "error": endpoint}

    def sent(self, endpoint):
        return [p for e, p in self.requests if e == endpoint]


class CreativeContextTests(unittest.TestCase):
    def setUp(self):
        self.env = {k: os.environ.get(k) for k in ENV}
        for k in ENV:
            os.environ.pop(k, None)
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = Path(self.tmp.name) / "runtime"
        engine = Path(self.tmp.name) / "engine"
        os.environ.update(NALU_RUNTIME_ROOT=str(root), NALU_ENGINE_ROOT=str(engine), X2C_API_KEY="x2c_sk_test",
                          NALU_DEVICE_SN="test_00111")
        rt = root / "runtime"
        plates = Path(self.tmp.name) / "plates"
        for d in (rt / "pipeline_state", plates, root / "preproduction/E01", engine / "workflow/claude_writer_agent/scripts"):
            d.mkdir(parents=True, exist_ok=True)
        contract = {"dialogue_language": "zh", "protagonist_ids": ["CHAR-LINQIAO"],
                    "character_entities": [
                        {"character_id": "CHAR-LINQIAO", "canonical_name": "林乔", "sex": "female", "role": "female lead",
                         "english_name": "Lin Qiao", "voice_entity_id": "linqiao"},
                        {"character_id": "CHAR-ZHOUHENG", "canonical_name": "周衡", "gender": "男"},
                        {"character_id": "CHAR-EXTRA", "canonical_name": "路人", "gender": "男"}],
                    "audio_contract": {"dialogue_units": [{"speaker_id": "CHAR-LINQIAO"}, {"speaker_id": "CHAR-ZHOUHENG"},
                                                          {"speaker_id": "CHAR-EXTRA"}]}}
        cpath = Path(self.tmp.name) / "E01_GENERATION_CONTRACT_v1.json"
        cpath.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
        (rt / "pipeline_state/E01.json").write_text(json.dumps({"layers": {"paths": {"generation_contract": str(cpath)}}}))
        (root / "preproduction/E01/video_model.json").write_text(json.dumps({"video_model": "MiniMax-H3"}))
        self.registry = {"major_roles": [
            {"character_id": "linqiao", "entity_id": "linqiao", "status": "LOCKED_PRODUCTION_READY",
             "voice_id": "ttv-voice-linqiao", "remote_asset_id": "8skp", "remote_url": ANCHOR_A,
             "local_reference": "/Users/x/VOICE-linqiao.wav", "duration_seconds": 2.04, "language": "zh-CN",
             "voice_name": "勇敢独立女主"},
            {"character_id": "zhouheng", "status": "LOCKED_PRODUCTION_READY", "generation_voice_id": "clone_zh",
             "remote_url": ANCHOR_B, "duration_seconds": 3.8}]}
        self.write_registry()
        (rt / "voice_cast.json").write_text(json.dumps({"schema": "qingshan.voice_cast.v1", "characters": {
            "CHAR-LINQIAO": {"voice_id": "ttv-voice-linqiao", "reference_entity_id": "linqiao", "reference_f0_hz": 226.21,
                             "f0_band_hz": [192.28, 260.14], "timbre_brief": "年轻女性中音，清晰果断"}}}, ensure_ascii=False))
        views = {}
        for cid in ("CHAR-LINQIAO", "CHAR-ZHOUHENG"):
            paths = []
            for role in ("FULL_BODY_STANDING", "FRONT_NEUTRAL_HEADSHOT", "THREE_QUARTER_BUST"):
                p = plates / f"E01_{cid}__{role}_x.png"
                p.write_bytes(f"{cid}{role}".encode())
                paths.append(str(p))
            views[cid] = {"canonical_reference_paths": paths}
        (rt / "nalu_character_asset_registry.json").write_text(json.dumps({"characters": views}))
        mx.save_state({"schema": "nalu.x2c_matrix_distribution.v1", "current_series": "urban-zh", "series": {
            "urban-zh": {"project_id": "p-1", "closed": False, "title": "T",
                         "episodes": {"E01": {"episode_number": 1, "receipt": {"project_id": "p-1"}}}}}})
        self.fake = Fake()
        self.puts: list[str] = []
        self.saved = (mx._post, mx.SLEEP, px.put_file)
        mx._post = self.fake
        mx.SLEEP = lambda s: None
        px.put_file = lambda up, path: self.puts.append(path.name)

    def tearDown(self):
        mx._post, mx.SLEEP, px.put_file = self.saved
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def write_registry(self):
        (self.root / "runtime/voice_registry.json").write_text(json.dumps(self.registry, ensure_ascii=False))

    def ctx(self):
        return mx.load_state()["series"]["urban-zh"]["creative_context"]

    def test_dry_run_payload_shape_no_network(self):
        out = xcc.run(dry_run=True)
        self.assertEqual(self.fake.requests, [])
        self.assertEqual(self.puts, [])
        self.assertNotIn("creative_context", mx.load_state()["series"]["urban-zh"])  # dry run writes nothing
        body = out["payload"]
        self.assertEqual((body["project_id"], body["series_key"], body["device_sn"]), ("p-1", "urban-zh", "test_00111"))
        self.assertEqual([c["character_id"] for c in body["characters"]], ["CHAR-LINQIAO"])
        self.assertEqual(out["skipped"], {})  # zhouheng / extra speak in 1 episode only, not SERIES_CORE: not recurring
        lin = body["characters"][0]
        self.assertTrue(lin["is_main_character"] and lin["is_fictional"])
        self.assertEqual((lin["character_name"], lin["role"]), ("林乔", "female lead"))
        self.assertEqual(len(lin["reference_image_urls"]), 3)
        self.assertIn("UPLOAD-PENDING", lin["reference_image_urls"][0])
        v = lin["voice"]
        self.assertEqual((v["provider"], v["model"], v["id"], v["anchor_url"], v["version"], v["status"]),
                         ("giggle", "MiniMax-H3", "ttv-voice-linqiao", ANCHOR_A, 1, "active"))
        self.assertEqual((v["language"], v["gender"], v["f0_min"], v["f0_max"], v["f0_median"]),
                         ("zh-CN", "female", 192.3, 260.1, 226.2))
        self.assertEqual(v["metadata"]["duration_seconds"], 2.04)
        self.assertIn("speaker_voice_contract", v)
        # CLI
        self.assertEqual(mx.main(["creative-context", "--dry-run"]), 0)

    def test_send_then_idempotent_skip(self):
        self.registry["major_roles"].append({"character_id": "extra", "status": "LOCKED_PRODUCTION_READY",
                                             "voice_id": "v-x", "remote_url": ANCHOR_B})
        self.write_registry()
        lib = {"assets": {"characters": {"CHAR-ZHOUHENG": {"priority": "SERIES_CORE"}}}}
        (self.root / "runtime/asset_library.json").write_text(json.dumps(lib))
        out = xcc.run()
        self.assertEqual(out["status"], "OK")
        self.assertEqual(sorted(out["sent"]), ["CHAR-LINQIAO", "CHAR-ZHOUHENG"])
        posts = self.fake.sent(xcc.ENDPOINT)
        self.assertEqual(len(posts), 2)
        zh = posts[1]["characters"][0]
        self.assertFalse(zh["is_main_character"])
        self.assertEqual((zh["voice"]["id"], zh["voice"]["gender"]), ("clone_zh", "male"))
        # headshot first, uploaded through the matrix upload-url, public_url used
        self.assertEqual(len(self.fake.sent("distribution/upload-url")), 6)
        self.assertTrue(all(u.startswith("https://media.x2c.test/pub/") for u in posts[0]["characters"][0]["reference_image_urls"]))
        self.assertIn("FRONT_NEUTRAL_HEADSHOT", self.puts[0])
        # never a local path or a credential/signed URL anywhere in what was sent
        blob = json.dumps(posts, ensure_ascii=False)
        self.assertNotIn("/Users/", blob)
        self.assertNotIn(self.tmp.name, blob)
        self.assertNotIn("Signature", blob)
        rec = self.ctx()["characters"]["CHAR-LINQIAO"]
        self.assertEqual((rec["last_status"], rec["voice_version"], rec["http"]), ("SENT", 1, 200))
        self.assertTrue(rec["payload_sha256"] and rec["sent_at"])
        # second run: nothing changed -> no POST, no re-upload
        n = len(self.fake.requests)
        out = xcc.run()
        self.assertEqual(sorted(out["unchanged"]), ["CHAR-LINQIAO", "CHAR-ZHOUHENG"])
        self.assertEqual(len(self.fake.requests), n)

    def test_voice_change_retires_then_bumps_version(self):
        xcc.run()
        self.registry["major_roles"][0]["remote_url"] = "https://assets.giggle.pro/public/ai_director/cc/linqiao-v2.wav"
        self.write_registry()
        out = xcc.run()
        self.assertEqual(out["retired"], [{"character_id": "CHAR-LINQIAO", "voice_version": 1}])
        order = [e for e, _ in self.fake.requests if e.startswith("advertising/")]
        self.assertEqual(order, [xcc.ENDPOINT, xcc.RETIRE, xcc.ENDPOINT])
        retire = self.fake.sent(xcc.RETIRE)[0]
        self.assertEqual(retire, {"device_sn": "test_00111", "project_id": "p-1", "series_key": "urban-zh",
                                  "character_id": "CHAR-LINQIAO", "voice_version": 1})
        self.assertEqual(self.fake.sent(xcc.ENDPOINT)[-1]["characters"][0]["voice"]["version"], 2)
        self.assertEqual(self.ctx()["characters"]["CHAR-LINQIAO"]["voice_version"], 2)
        # a style-only change later resends v2 without another retire
        self.registry["major_roles"][0]["voice_name"] = "x"
        self.write_registry()
        xcc.run()
        self.assertEqual(len(self.fake.sent(xcc.RETIRE)), 1)

    def test_retire_ok_submit_failed_retries_without_second_retire(self):
        xcc.run()
        self.registry["major_roles"][0]["voice_id"] = "ttv-voice-new"
        self.write_registry()
        self.fake.fail[xcc.ENDPOINT] = [(400, {"code": "VALIDATION_ERROR"})]
        out = xcc.run()
        self.assertEqual(out["status"], "FAILED")
        xcc.run()
        self.assertEqual(len(self.fake.sent(xcc.RETIRE)), 1)
        self.assertEqual(self.fake.sent(xcc.ENDPOINT)[-1]["characters"][0]["voice"]["version"], 2)
        self.assertEqual(self.ctx()["characters"]["CHAR-LINQIAO"]["last_status"], "SENT")

    def test_failure_never_blocks_publish_and_retries_next_episode(self):
        d = self.root / "deliverables/E02"
        d.mkdir(parents=True)
        (d / "E02_final_9x16.mp4").write_bytes(b"v2")
        (self.root / "cover.jpg").write_bytes(b"jpg")
        saved = (px.cover_from_video, mx.duration_seconds)
        px.cover_from_video = lambda video: self.root / "cover.jpg"
        mx.duration_seconds = lambda path: 90.0
        try:
            self.fake.fail[xcc.ENDPOINT] = [(404, {"code": "UNKNOWN_ROUTE", "error": "x"})]
            out = mx.cmd_publish(argparse.Namespace(episode="E02", title="T", description="", hashtags="", video="",
                                                    cover="", series_key="", lang="zh", episode_number=2, resend=False))
            self.assertEqual(out["status"], "PUBLISHED")
            self.assertEqual(out["creative_context"]["status"], "FAILED")
            self.assertTrue(out["creative_context"]["route_not_live"])
            rec = self.ctx()["characters"]["CHAR-LINQIAO"]
            self.assertEqual((rec["last_status"], rec["http"]), ("FAILED", 404))
            self.assertEqual(self.ctx()["last_run"]["status"], "FAILED")
            # a 5xx storm: retried twice, still non-blocking
            self.fake.fail[xcc.ENDPOINT] = [(503, {}), (503, {})]
            self.assertEqual(xcc.after_publish("urban-zh", "E02")["status"], "FAILED")
            # the next run succeeds
            self.assertEqual(xcc.after_publish("urban-zh", "E02")["sent"], ["CHAR-LINQIAO"])
            # an exception inside never escapes
            orig, xcc.run = xcc.run, lambda *a, **k: (_ for _ in ()).throw(SystemExit("boom"))
            try:
                self.assertEqual(xcc.after_publish("urban-zh", "E02")["status"], "ERROR")
            finally:
                xcc.run = orig
        finally:
            px.cover_from_video, mx.duration_seconds = saved

    def test_disabled_by_env(self):
        os.environ["X2C_CREATIVE_CONTEXT"] = "off"
        self.assertEqual(mx._creative_context_after_publish("urban-zh", "E01", "p-1")["status"], "DISABLED")
        self.assertEqual(xcc.run()["status"], "DISABLED")
        self.assertEqual(self.fake.requests, [])

    def test_skips_and_url_hygiene(self):
        for bad in ("http://a.test/x.wav", "https://user:pw@a.test/x.wav", "https://a.test/x.wav#t",
                    "https://a.test/x.wav?X-Amz-Signature=1&X-Amz-Expires=60", "/Users/x/a.wav", "s3://b/x.wav"):
            self.assertFalse(xcc.public_https(bad), bad)
        self.assertTrue(xcc.public_https(ANCHOR_A))
        self.registry["major_roles"][0]["remote_url"] = "https://u:p@assets.giggle.pro/x.wav"
        self.write_registry()
        out = xcc.run(dry_run=True)
        self.assertEqual(out["skipped"], {"CHAR-LINQIAO": "VOICE_ANCHOR_NOT_PUBLIC_HTTPS"})
        self.registry["major_roles"][0].update(remote_url=ANCHOR_A, duration_seconds=14.0)
        self.write_registry()
        self.assertTrue(xcc.run(dry_run=True)["skipped"]["CHAR-LINQIAO"].startswith("VOICE_ANCHOR_OVER_12S"))
        self.registry["major_roles"][0]["duration_seconds"] = 2.0
        self.write_registry()
        (self.root / "runtime/nalu_character_asset_registry.json").write_text(json.dumps({"characters": {
            "CHAR-LINQIAO": {"reference_image_urls": ["https://u:p@cdn.test/a.png"]}}}))
        self.assertTrue(xcc.run(dry_run=True)["skipped"]["CHAR-LINQIAO"].startswith("NO_PUBLIC_REFERENCE_IMAGE"))
        out = xcc.run()
        self.assertEqual(self.fake.requests, [])  # nothing sendable -> no request at all
        self.assertIn("NO_PUBLIC_REFERENCE_IMAGE", self.ctx()["characters"]["CHAR-LINQIAO"]["skipped"])
        # a recorded public image URL is used as is (no upload); at most 8
        (self.root / "runtime/nalu_character_asset_registry.json").write_text(json.dumps({"characters": {
            "CHAR-LINQIAO": {"reference_image_urls": [f"https://cdn.test/{i}.png" for i in range(11)]}}}))
        out = xcc.run()
        self.assertEqual(len(self.fake.sent(xcc.ENDPOINT)[0]["characters"][0]["reference_image_urls"]), 8)
        self.assertEqual(self.fake.sent("distribution/upload-url"), [])

    def test_no_project_yet(self):
        mx.save_state({"schema": "s", "current_series": "k", "series": {"k": {"project_id": None, "episodes": {}}}})
        self.assertEqual(xcc.run()["status"], "NO_PROJECT_YET")
        self.assertEqual(mx._creative_context_after_publish("k", "E01", None)["status"], "NO_PROJECT_YET")


if __name__ == "__main__":
    unittest.main()
