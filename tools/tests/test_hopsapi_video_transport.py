"""MiniMax-H3 video through the HopsAPI router (owner decision 2026-10-29).

Every HTTP call is mocked at ``hopsapi_video_client._http`` (and the reference download at
``_download_bytes``): no request leaves this host and no key is needed.  Covered: provider switch,
upload MIME, create, poll 0->1->2 / 3 / 424, harvest + verify, idempotent re-entry (no re-POST),
per-attempt failure classification, the budget-ledger cost leg, and the 4 s duration floor.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for _path in (str(ROOT), str(ROOT / "tools"), str(ROOT / "lines" / "nalu" / "runtime" / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tools import submit_giggle_video_manifest_v2 as video  # noqa: E402
import poll_giggle_submit_report as poller  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 64
MP4 = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 2048
HOPS_ENV = {"NALU_VIDEO_PROVIDER": "hopsapi", "HOPSAPI_API_KEY": "test-key-not-real",
            "HOPSAPI_VERIFY_FFPROBE": "0", "HOPSAPI_RETRY_DELAY_SECONDS": "0"}


class FakeHops:
    """Scripted HopsAPI: records every request, answers uploads, create and queries."""

    def __init__(self, *, create=None, queries=None, store_mime=None):
        self.calls: list[dict] = []
        self.create = create or (lambda: (200, {"code": 200, "message": "task created",
                                                "task_id": "tsk_mvtw42uw_aead3bfa7fa718aa3ab01c87"}))
        self.queries = list(queries or [])
        self.store_mime = store_mime

    def __call__(self, method, url, *, body=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "body": body, "headers": dict(headers or {})})
        if url.endswith("/api/file-stream-upload"):
            text = body.decode("latin-1")
            mime = text.split("Content-Type: ", 1)[1].split("\r\n", 1)[0]
            name = text.split('name="fileName"\r\n\r\n', 1)[1].split("\r\n", 1)[0]
            payload = {"success": True, "code": 200, "data": {
                "fileUrl": f"https://assets.hopsapi.com/public/tmp/1/x/{name}",
                "mimeType": self.store_mime or mime, "expiresAt": "2026-10-30T00:00:00Z"}}
            return 200, payload, json.dumps(payload)
        if url.endswith("/router/task/create"):
            result = self.create()
            if isinstance(result, BaseException):
                raise result
            status, payload = result
            return status, payload, json.dumps(payload)
        if "/router/tasks/" in url:
            result = self.queries.pop(0)
            if isinstance(result, BaseException):
                raise result
            status, payload = result
            return status, payload, json.dumps(payload)
        raise AssertionError(f"unexpected request {method} {url}")

    def posts(self, suffix):
        return [c for c in self.calls if c["method"] == "POST" and c["url"].endswith(suffix)]


class HopsapiTestBase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, HOPS_ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.receipts = self.root / "receipts"
        self.transactions = self.root / "transactions" / "E10"
        self.refs = []
        for index in range(2):
            path = self.root / f"ref-{index}.png"
            path.write_bytes(PNG + bytes([index]))
            self.refs.append(path)

    def task(self, *, duration=4, key="E10-VU-001"):
        prompt = self.root / f"{key}.txt"
        prompt.write_text("provider prompt", encoding="utf-8")
        return {
            "task_key": key, "episode": "E10", "unit_id": key, "model": "MiniMax-H3",
            "duration_seconds": duration, "resolution": "768p", "aspect_ratio": "9:16",
            "prompt_file": str(prompt), "prompt_sha256": video.sha256(prompt),
            "reference_images": [str(p) for p in self.refs],
            "reference_sha256": [video.sha256(p) for p in self.refs],
            "reference_audio_urls": ["https://assets.giggle.pro/public/ai_director/x/voice.wav"],
        }

    def submit(self, task, fake):
        with patch.object(video.hopsapi, "_http", side_effect=fake), \
             patch.object(video.hopsapi, "_download_bytes", return_value=WAV), \
             patch.object(video, "prompt_scope_gate_active", return_value=False), \
             patch("tools.episode_prompt_batch_gate.require_generation_batch"), \
             patch.object(video, "_request", side_effect=AssertionError("Giggle POST on HopsAPI route")):
            return video.submit_one(task, self.receipts, self.transactions)

    def tx(self, task):
        return json.loads(video.transaction_path(self.transactions, task).read_text(encoding="utf-8"))


class ProviderSwitchTests(unittest.TestCase):
    def test_env_then_config_then_key_presence(self):
        from tools import hopsapi_video_client as hops
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp) / "qingshan.json"
            cfg.write_text(json.dumps({"generation": {"video_provider": "giggle"}}), encoding="utf-8")
            self.assertEqual(hops.video_provider(cfg, {"NALU_VIDEO_PROVIDER": "hopsapi"}), "hopsapi")
            self.assertEqual(hops.video_provider(cfg, {"HOPSAPI_API_KEY": "k"}), "giggle")
            self.assertEqual(hops.video_provider(Path(tmp) / "none.json", {"HOPSAPI_API_KEY": "k"}), "hopsapi")
            self.assertEqual(hops.video_provider(Path(tmp) / "none.json", {}), "giggle")
            with self.assertRaises(ValueError):
                hops.video_provider(cfg, {"NALU_VIDEO_PROVIDER": "bogus"})

    def test_only_h3_takes_the_hopsapi_route(self):
        from tools import hopsapi_video_client as hops
        self.assertEqual(hops.provider_for_model("MiniMax-H3", "hopsapi"), "hopsapi")
        self.assertEqual(hops.provider_for_model("seedance-2.0-pro", "hopsapi"), "giggle")
        self.assertEqual(hops.provider_for_model("MiniMax-H3", "giggle"), "giggle")
        self.assertEqual(hops.required_key_env("hopsapi"), "HOPSAPI_API_KEY")

    def test_planning_estimate_is_rounded_up_and_configurable(self):
        from tools import hopsapi_video_client as hops
        self.assertEqual(hops.estimated_task_credits(4, 2, environ={}), 7)       # 6.24 -> 7 (probe 6.23)
        self.assertEqual(hops.estimated_task_credits(3, 2, environ={}), 7)       # floor 4 s
        self.assertEqual(hops.estimated_task_credits(4, 7, environ={}), 9)       # 6.24 + 2 imgs x 4 s x 0.32
        self.assertEqual(hops.estimated_task_credits(5, 1, environ={"HOPSAPI_H3_CREDITS_PER_SECOND": "2"}), 10)
        self.assertGreaterEqual(hops.estimated_batch_credits(12, 3, environ={}), 3 * 7)


class UploadMimeTests(HopsapiTestBase):
    def test_every_part_carries_an_explicit_mime_type(self):
        fake = FakeHops()
        result = self.submit(self.task(), fake)
        uploads = fake.posts("/api/file-stream-upload")
        self.assertEqual(len(uploads), 3)
        bodies = [c["body"].decode("latin-1") for c in uploads]
        self.assertIn("Content-Type: image/png", bodies[0])
        self.assertIn("Content-Type: image/png", bodies[1])
        self.assertIn("Content-Type: audio/wav", bodies[2])
        self.assertTrue(all(c["headers"]["Authorization"].startswith("Bearer ") for c in uploads))
        tx = self.tx(self.task())
        self.assertEqual(tx["sent_reference_mime_types"], ["image/png", "image/png"])
        self.assertEqual(result["provider"], "hopsapi")

    def test_text_plain_storage_is_refused_before_any_intent(self):
        fake = FakeHops(store_mime="text/plain")
        task = self.task()
        with self.assertRaisesRegex(Exception, "UPLOAD_MIME_NOT_PRESERVED"):
            self.submit(task, fake)
        self.assertEqual(fake.posts("/router/task/create"), [])
        self.assertFalse(video.transaction_path(self.transactions, task).exists())

    def test_sniffs_jpeg_png_wav_mp3(self):
        from tools import hopsapi_video_client as hops
        self.assertEqual(hops.sniff_mime(b"\xff\xd8\xff\xe0" + b"0" * 10), "image/jpeg")
        self.assertEqual(hops.sniff_mime(PNG), "image/png")
        self.assertEqual(hops.sniff_mime(WAV), "audio/wav")
        self.assertEqual(hops.sniff_mime(b"ID3\x04" + b"0" * 10), "audio/mpeg")
        with self.assertRaises(hops.HopsapiError):
            hops.sniff_mime(b"????", "x.bin")


class CreateAndIdempotencyTests(HopsapiTestBase):
    def test_create_binds_task_id_and_records_the_transaction(self):
        fake = FakeHops()
        task = self.task()
        result = self.submit(task, fake)
        creates = fake.posts("/router/task/create")
        self.assertEqual(len(creates), 1)
        body = json.loads(creates[0]["body"])
        self.assertEqual((body["task"], body["model"]), ("OmniVideo", "MiniMax-H3"))
        self.assertEqual(body["input"]["duration"], 4)
        self.assertEqual(body["input"]["resolution"], "768p")
        self.assertEqual(body["input"]["aspect_ratio"], "9:16")
        self.assertIs(body["input"]["generate_audio"], True)
        self.assertEqual(len(body["input"]["images"]), 2)
        self.assertEqual(len(body["input"]["audios"]), 1)
        self.assertEqual(body["input"]["prompt"], "provider prompt")
        tx = self.tx(task)
        self.assertEqual(tx["state"], "SUBMITTED_TASK_ID_BOUND")
        self.assertEqual(tx["task_id"], "tsk_mvtw42uw_aead3bfa7fa718aa3ab01c87")
        self.assertEqual(tx["provider"], "hopsapi")
        self.assertEqual(tx["prompt_sha256"], task["prompt_sha256"])
        self.assertEqual(tx["reference_sha256"], task["reference_sha256"])
        self.assertTrue(tx["request_binding"]["request_sha256"])
        self.assertEqual(len(tx["sent_reference_sha256"]), 2)
        self.assertEqual(tx["estimated_credits"], 7)
        self.assertEqual(result["task_id"], tx["task_id"])
        self.assertNotIn("test-key-not-real", json.dumps(tx))

    def test_re_entry_never_re_posts_a_bound_task(self):
        task = self.task()
        self.submit(task, FakeHops())
        again = FakeHops(create=lambda: AssertionError("re-POST"))
        result = self.submit(self.task(), again)
        self.assertTrue(result["recovered_from_transaction"])
        self.assertEqual(result["provider"], "hopsapi")
        self.assertEqual(again.calls, [])  # no upload, no create

    def test_explicit_decline_is_retryable_and_a_lost_response_is_not(self):
        hops = video.hopsapi
        task = self.task()
        declined = FakeHops(create=lambda: hops.HopsapiHTTPError(400, {"code": 400, "message": "bad"}, "bad"))
        with self.assertRaisesRegex(RuntimeError, "not charged"):
            self.submit(task, declined)
        self.assertEqual(self.tx(task)["state"], "VERIFIED_ZERO_RETRYABLE")
        lost = FakeHops(create=lambda: TimeoutError("read timed out"))
        with self.assertRaises(Exception):
            self.submit(self.task(), lost)  # VERIFIED_ZERO_RETRYABLE lets ONE new attempt through
        self.assertEqual(len(lost.posts("/router/task/create")), 1)
        self.assertEqual(self.tx(task)["state"], "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION")
        blocked = FakeHops()
        with self.assertRaisesRegex(RuntimeError, "blocked by transaction state"):
            self.submit(self.task(), blocked)
        self.assertEqual(blocked.calls, [])

    def test_server_error_is_response_lost_never_resent(self):
        hops = video.hopsapi
        task = self.task()
        fake = FakeHops(create=lambda: hops.HopsapiHTTPError(502, None, "bad gateway"))
        with self.assertRaises(hops.HopsapiResponseLost):
            self.submit(task, fake)
        self.assertEqual(self.tx(task)["state"], "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION")

    def test_insufficient_credits_trips_the_fuse(self):
        hops = video.hopsapi
        fake = FakeHops(create=lambda: hops.HopsapiHTTPError(402, {"code": 402, "message": "insufficient balance"},
                                                             "insufficient balance"))
        with self.assertRaises(video.ProviderInsufficientCreditsError):
            self.submit(self.task(), fake)

    def test_three_second_unit_is_refused_before_upload_or_intent(self):
        fake = FakeHops()
        task = self.task(duration=3)
        with self.assertRaisesRegex(ValueError, "HOPSAPI_H3_DURATION_OUT_OF_RANGE"):
            self.submit(task, fake)
        self.assertEqual(fake.calls, [])
        self.assertFalse(video.transaction_path(self.transactions, task).exists())
        self.assertEqual(video.hopsapi_request_window_failures(task), ["HOPSAPI_H3_DURATION_OUT_OF_RANGE:3"])

    def test_create_outside_the_durable_submitter_is_blocked(self):
        from tools import hopsapi_video_client as hops
        with patch.object(hops, "_http", side_effect=AssertionError("network")), \
             patch.dict(os.environ, {"QINGSHAN_DURABLE_SUBMITTER_CONTEXT": ""}):
            with self.assertRaises(SystemExit):
                hops.create_task(hops.build_omni_request(prompt="p", image_urls=["https://a/x.png"],
                                                         audio_urls=[], duration=4, resolution="768p"))

    def test_giggle_switch_keeps_the_old_route(self):
        task = self.task()
        with patch.dict(os.environ, {"NALU_VIDEO_PROVIDER": "giggle"}):
            self.assertFalse(video.hopsapi.task_uses_hopsapi(task))
            self.assertEqual(video.estimated_video_credits(task), 4 * 14 + 6)


class BatchReportTests(HopsapiTestBase):
    """main(): HopsAPI-only batches never touch Giggle credit statements and need HOPSAPI_API_KEY."""

    def run_main(self, task, *, submit):
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps({"episode": "E10", "tasks": [task],
                                        "machine_gate_reports": ["gate.json"]}), encoding="utf-8")
        out = self.root / "reports" / "E10_VIDEO_SUBMIT.json"
        argv = ["submit", "--manifest", str(manifest), "--out", str(out), "--concurrency", "2"]
        with patch.object(sys, "argv", argv), \
             patch.object(video, "require_e47_efficiency_contract", return_value={"status": "PASS"}), \
             patch.object(video, "run_authoritative_submission_gate", return_value={"status": "PASS"}), \
             patch.object(video, "validate_gate", return_value={"status": "PASS"}), \
             patch.object(video, "validate_task"), \
             patch.object(video, "validate_task_submission_gates", return_value=[]), \
             patch.object(video, "validate_camera_sequence"), \
             patch.object(video, "validate_transition_sequence"), \
             patch.object(video, "validate_combat_sequence_rhythm", return_value={"status": "PASS"}), \
             patch.object(video, "submit_one", side_effect=submit), \
             patch.object(video, "fetch_pay_statements", side_effect=AssertionError("Giggle statements")):
            code = video.main()
        return code, out

    def test_hopsapi_batch_reports_per_task_cost_method(self):
        task = self.task()
        bound = {**task, "task_id": "tsk_1", "state": "remote_running", "provider": "hopsapi",
                 "transaction": "t.json", "recovered_from_transaction": False}
        code, out = self.run_main(task, submit=lambda *_a: bound)
        report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual((code, report["status"]), (0, "PASS"))
        self.assertEqual(report["credit_reconciliation"]["method"], "HOPSAPI_PER_TASK_COST_RECORDED_AT_SETTLEMENT")
        self.assertEqual(report["credit_reconciliation"]["estimated_credits"], 7)
        self.assertEqual(report["video_providers"], {task["task_key"]: "hopsapi"})
        self.assertFalse((out.parent / f"{out.stem}_credit_statement.json").exists())

    def test_missing_hopsapi_key_stops_before_any_submit(self):
        task = self.task()
        with patch.dict(os.environ, {"HOPSAPI_API_KEY": ""}):
            with self.assertRaisesRegex(SystemExit, "HOPSAPI_API_KEY is not set"):
                self.run_main(task, submit=lambda *_a: self.fail("submitted without a key"))


class PollHarvestTests(HopsapiTestBase):
    def bound(self):
        task = self.task()
        self.submit(task, FakeHops())
        tx_path = video.transaction_path(self.transactions, task)
        report = self.root / "submit.json"
        report.write_text(json.dumps({"tasks": [{"task_key": task["task_key"],
                                                 "task_id": "tsk_mvtw42uw_aead3bfa7fa718aa3ab01c87",
                                                 "transaction": str(tx_path)}]}), encoding="utf-8")
        return task, tx_path, report

    def poll(self, report, queries, out):
        fake = FakeHops(queries=queries)
        with patch.object(poller.hopsapi, "_http", side_effect=fake), \
             patch.object(poller.hopsapi, "_download_bytes", return_value=MP4) as download, \
             patch.object(poller, "query_task", side_effect=AssertionError("Giggle query for a HopsAPI task")), \
             patch.dict(os.environ, {"GIGGLE_API_KEY": ""}):
            payload = poller.poll(report, out, self.root / "status.json", True)
        return payload, fake, download

    def test_queued_processing_then_completed_downloads_and_records_cost(self):
        task, tx_path, report = self.bound()
        out = self.root / "video"
        payload, _fake, _dl = self.poll(report, [(200, {"task_id": "tsk_x", "status": 0, "results": []})], out)
        self.assertFalse(payload["all_completed"])
        payload, _fake, _dl = self.poll(report, [(200, {"task_id": "tsk_x", "status": 1, "results": []})], out)
        self.assertEqual(payload["status_counts"], {"processing": 1})
        self.assertNotIn("provider_cost_credits", json.loads(tx_path.read_text()))
        done = (200, {"task_id": "tsk_x", "status": 2, "cost": 6.23,
                      "results": [{"urls": ["https://static.giggle.pro/ipimg/airouter/x.mp4"]}]})
        payload, _fake, download = self.poll(report, [done], out)
        self.assertTrue(payload["all_completed"])
        clip = out / f"{task['task_key']}.mp4"
        self.assertEqual(clip.read_bytes(), MP4)
        self.assertEqual(payload["results"][0]["downloaded_files"], [str(clip)])
        tx = json.loads(tx_path.read_text())
        self.assertEqual(tx["provider_cost_credits"], 6.23)
        self.assertEqual(tx["state"], "SUBMITTED_TASK_ID_BOUND")
        # result.content.video_url shape, and a second poll does not re-download
        alt = (200, {"task_id": "tsk_x", "status": 2, "cost": 6.23,
                     "result": {"content": {"video_url": "https://static.example/v.mp4"}}})
        _payload, _fake, download = self.poll(report, [alt], out)
        download.assert_not_called()

    def test_failed_and_424_are_terminal_and_not_charged(self):
        _task, tx_path, report = self.bound()
        payload, _f, _d = self.poll(report, [(200, {"task_id": "tsk_x", "status": 3, "error": "moderation"})],
                                    self.root / "video")
        self.assertEqual(payload["status_counts"], {"failed": 1})
        tx = json.loads(tx_path.read_text())
        self.assertEqual((tx["provider_cost_credits"], tx["remote_terminal_state"]), (0.0, "failed"))

    def test_http_424_and_code_424_map_to_failed(self):
        from tools import hopsapi_video_client as hops
        self.assertEqual(hops.normalize_task({"code": 424, "message": "upstream failed"}, 200)["remote_status"],
                         "failed")
        _task, _tx, report = self.bound()
        err = poller.hopsapi.HopsapiHTTPError(424, {"code": 424, "task_id": "tsk_x", "status": 3}, "failed")
        payload, _f, _d = self.poll(report, [err], self.root / "video")
        self.assertEqual(payload["results"][0]["remote_status"], "failed")

    def test_a_non_mp4_download_is_refused(self):
        from tools import hopsapi_video_client as hops
        with self.assertRaises(hops.HopsapiError):
            hops.download_video("https://x/v.mp4", self.root / "v.mp4", fetch=lambda _u: b"<html>" * 400)
        self.assertFalse((self.root / "v.mp4").exists())


class DurationFloorTests(unittest.TestCase):
    def test_stamped_units_floor_at_four_seconds(self):
        from tools import build_video_unit_grouping_spec as grouping
        from tools.speaking_unit_duration import speaking_duration
        self.assertEqual(grouping.provider_min_seconds("MiniMax-H3"), 4.0)
        self.assertEqual(grouping.cut_grammar_target("MiniMax-H3")[0], 4.0)
        self.assertEqual(speaking_duration(3, ["A: Yes."], "en")["duration_seconds"], 4.0)
        self.assertEqual(speaking_duration(8, ["A: one two three four five six seven eight nine ten"], "en")
                         ["duration_seconds"], 5.0)


class BudgetLedgerTests(unittest.TestCase):
    def test_cost_is_settled_spend_and_unsettled_is_exposure(self):
        import nalu_budget_ledger as ledger
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "workflow/tasks/giggle_video_submit_transactions/E10"
            store.mkdir(parents=True)
            rows = {
                "a": {"provider": "hopsapi", "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "tsk_a",
                      "estimated_credits": 7, "provider_cost_credits": 6.23},
                "b": {"provider": "hopsapi", "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "tsk_b",
                      "estimated_credits": 7},
                "c": {"provider": "hopsapi", "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "tsk_c",
                      "estimated_credits": 7, "remote_terminal_state": "failed"},
                "d": {"state": "SUBMITTED_TASK_ID_BOUND", "task_id": "uuid-d", "estimated_credits": 62},
            }
            for name, row in rows.items():
                (store / f"{name}.json").write_text(json.dumps(row), encoding="utf-8")
            with patch.object(ledger, "ENGINE_ROOT", Path(tmp)):
                hops = ledger.scan_hopsapi_video_spend("E10")
                giggle_exposure = ledger.scan_unevidenced_exposure("E10", {"batch_reconciled_credits": 0})
            self.assertEqual(hops["settled_credits"], 6.23)
            self.assertEqual(hops["pending_exposure_credits"], 7)
            self.assertEqual(hops["unsettled_task_count"], 1)
            self.assertEqual(giggle_exposure, 62)  # HopsAPI rows never double into the Giggle leg


if __name__ == "__main__":
    unittest.main()
