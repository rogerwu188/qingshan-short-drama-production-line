"""A bound HopsAPI image task that answers 404 after the fleet key was replaced (field E08 2026-11-15)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import harvest_giggle_image_batch as harvest  # noqa: E402
import hopsapi_image_client as image_client  # noqa: E402

hops = image_client.hops
LOST = "tsk_mwhc0001_aaaaaaaaaaaaaaaaaaaaaaaa"
KEPT = "tsk_mwhc0002_bbbbbbbbbbbbbbbbbbbbbbbb"
LIVE = "tsk_mwhc0003_cccccccccccccccccccccccc"


def not_found():
    return hops.HopsapiHTTPError(404, {"code": 404, "message": "Task not found", "task_id": ""},
                                 '{"code":404,"message":"Task not found","task_id":""}')


class ImageHarvestUnreachableAfterKeyChangeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / "transactions"
        self.out = self.root / "harvest"
        self.raw = self.out / "_raw"
        for path in (self.store, self.raw):
            path.mkdir(parents=True)
        env = mock.patch.dict(os.environ, {hops.API_KEY_ENV: "new-key", "NALU_FLEET_URL": "off",
                                           "NALU_HARVEST_WORKERS": "1"})
        env.start()
        self.addCleanup(env.stop)

    def transaction(self, key: str, task_id: str, **fields) -> Path:
        row = {"task_key": key, "provider": "hopsapi", "state": "SUBMITTED_TASK_ID_BOUND", "task_id": task_id,
               "attempt_id": "a1", "hopsapi_key_fingerprint": "0123456789abcdef", "estimated_credits": 1.2}
        row.update(fields)
        path = self.store / f"{key}__8ee6d38a08241e54.json"
        path.write_text(json.dumps(row), encoding="utf-8")
        return path

    def report(self, rows) -> Path:
        path = self.root / "submit.json"
        path.write_text(json.dumps({"episode": "E08", "results": rows}), encoding="utf-8")
        return path

    def row(self, key: str, task_id: str, transaction: Path) -> dict:
        return {"task_key": key, "task_id": task_id, "provider": "hopsapi", "transaction": str(transaction)}

    def poll(self, rows, query, status_report=None):
        with mock.patch.object(image_client, "query_task", side_effect=query), \
                mock.patch.object(image_client, "download_image",
                                  side_effect=lambda url, dest: Path(dest).write_bytes(b"png-bytes")):
            return harvest.poll_once(self.report(rows), self.out, self.raw, None, status_report)

    def test_unharvested_task_of_another_key_is_written_off_and_the_tick_survives(self) -> None:
        lost = self.transaction("E08-S01-01-KEYFRAME-V1", LOST)
        live = self.transaction("E08-S01-02-KEYFRAME-V1", LIVE, hopsapi_key_fingerprint=hops.key_fingerprint())

        def query(task_id):
            if task_id == LOST:
                raise not_found()
            return {"task_id": task_id, "status_code": 200, "remote_status": "completed",
                    "urls": ["https://example.invalid/a.png"], "cost": 0.9, "provider_code": None, "error": None}

        payload = self.poll([self.row("E08-S01-01-KEYFRAME-V1", LOST, lost),
                             self.row("E08-S01-02-KEYFRAME-V1", LIVE, live)], query)
        first, second = payload["results"]
        self.assertEqual(first["remote_status"], harvest.UNREACHABLE_STATUS)
        self.assertEqual(first["credit"], 1.2)
        self.assertEqual(second["remote_status"], "completed")
        self.assertTrue(payload["all_terminal"])
        self.assertFalse(payload["all_completed"])
        self.assertEqual(payload["unreachable_after_key_change_count"], 1)
        saved = json.loads(lost.read_text(encoding="utf-8"))
        self.assertEqual(saved["state"], "WRITTEN_OFF_UNATTRIBUTABLE_RETRYABLE")
        self.assertEqual(saved["written_off_credits"], 1.2)
        self.assertEqual(saved["unreachable_task"]["task_id"], LOST)

    def test_plate_harvested_before_the_key_change_is_kept(self) -> None:
        key = "E08-S01-03-KEYFRAME-V1"
        path = self.transaction(key, KEPT, provider_cost_credits=0.9, provider_remote_status="completed")
        plate = self.out / f"E08_{key}_{KEPT}.png"
        plate.write_bytes(b"png-bytes")
        raw = self.raw / f"{key}_{KEPT}.json"
        kept = {"provider": "hopsapi", "task_id": KEPT, "status_code": 200, "remote_status": "completed",
                "urls": ["https://example.invalid/b.png"], "cost": 0.9}
        raw.write_text(json.dumps(kept), encoding="utf-8")

        def query(_task_id):
            raise not_found()

        payload = self.poll([self.row(key, KEPT, path)], query)
        item = payload["results"][0]
        self.assertEqual(item["remote_status"], "completed")
        self.assertEqual(item["output_path"], str(plate))
        self.assertEqual(item["credit"], 0.9)
        self.assertTrue(payload["all_completed"])
        self.assertEqual(json.loads(raw.read_text(encoding="utf-8")), kept)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["state"], "SUBMITTED_TASK_ID_BOUND")

    def test_reentry_after_the_plate_was_materialised_keeps_the_earlier_harvest(self) -> None:
        """harvest -> apply_keyframe_renames moved the plate -> S5 re-entry -> GET 404 (device 1271 E08)."""
        key = "E08-S03-01-KEYFRAME-V1"
        path = self.transaction(key, KEPT, hopsapi_key_fingerprint=hops.key_fingerprint())
        status_report = self.root / "E08_KEYFRAME_HARVEST_STATUS.json"
        answer = {"task_id": KEPT, "status_code": 200, "remote_status": "completed",
                  "urls": ["https://example.invalid/c.png"], "cost": 0.9, "provider_code": None, "error": None}
        rows = [self.row(key, KEPT, path)]
        first = self.poll(rows, lambda _task_id: dict(answer), status_report)
        harvest.atomic_json(status_report, first)
        plate = Path(first["results"][0]["output_path"])
        digest = first["results"][0]["sha256"]
        keyframe = self.root / "keyframes" / "E08-S03-01-keyframe-v1.png"
        keyframe.parent.mkdir()
        os.replace(plate, keyframe)  # the pipeline's normal materialisation

        def query(_task_id):
            raise not_found()

        with mock.patch.object(image_client, "download_image") as download:
            with mock.patch.object(image_client, "query_task", side_effect=query):
                payload = harvest.poll_once(self.report(rows), self.out, self.raw, None, status_report)
        download.assert_not_called()
        item = payload["results"][0]
        self.assertEqual(item["remote_status"], "completed")
        self.assertEqual(item["sha256"], digest)
        self.assertEqual(item["plate_state"], "MOVED_AFTER_EARLIER_HARVEST")
        self.assertEqual(item["credit"], 0.9)
        self.assertTrue(payload["all_completed"])
        self.assertFalse(plate.exists())
        self.assertNotIn("unreachable_task", json.loads(path.read_text(encoding="utf-8")))
        # the carried record survives a further re-entry too
        harvest.atomic_json(status_report, payload)
        with mock.patch.object(image_client, "query_task", side_effect=query):
            again = harvest.poll_once(self.report(rows), self.out, self.raw, None, status_report)
        self.assertEqual(again["results"][0]["sha256"], digest)

    def test_moved_plate_without_an_earlier_harvest_record_is_not_assumed(self) -> None:
        key = "E08-S03-02-KEYFRAME-V1"
        path = self.transaction(key, KEPT, hopsapi_key_fingerprint=hops.key_fingerprint())
        raw = self.raw / f"{key}_{KEPT}.json"
        raw.write_text(json.dumps({"provider": "hopsapi", "task_id": KEPT, "remote_status": "completed",
                                   "urls": ["https://example.invalid/d.png"], "cost": 0.9}), encoding="utf-8")

        def query(_task_id):
            raise not_found()

        with self.assertRaises(hops.HopsapiError):
            self.poll([self.row(key, KEPT, path)], query, self.root / "absent_status.json")

    def test_moved_plate_is_kept_on_the_settled_transaction_when_the_report_was_replaced(self) -> None:
        """Device 0334 E05: a later batch replaced the status report, then S5 recovered the old task."""
        key = "E05-S01-02-KEYFRAME-V1"
        path = self.transaction(key, KEPT, provider_cost_credits=0.9, provider_remote_status="completed")
        before = path.read_text(encoding="utf-8")
        raw = self.raw / f"{key}_{KEPT}.json"
        raw.write_text(json.dumps({"provider": "hopsapi", "task_id": KEPT, "remote_status": "completed",
                                   "urls": ["https://example.invalid/e.png"], "cost": 0.9}), encoding="utf-8")
        status_report = self.root / "E05_KEYFRAME_HARVEST_STATUS.json"
        status_report.write_text(json.dumps({"results": [
            {"task_id": LIVE, "remote_status": "completed", "sha256": "0" * 64, "output_path": "x.png"}]}),
            encoding="utf-8")

        def query(_task_id):
            raise not_found()

        with mock.patch.object(image_client, "download_image") as download:
            with mock.patch.object(image_client, "query_task", side_effect=query):
                payload = harvest.poll_once(self.report([self.row(key, KEPT, path)]), self.out, self.raw, None,
                                            status_report)
        download.assert_not_called()
        item = payload["results"][0]
        self.assertEqual(item["remote_status"], "completed")
        self.assertEqual(item["plate_state"], "MOVED_AFTER_EARLIER_HARVEST")
        self.assertEqual(item["harvest_proof"], "SETTLED_TRANSACTION")
        self.assertNotIn("output_path", item)
        self.assertEqual(item["credit"], 0.9)
        self.assertTrue(payload["all_completed"])
        self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_settlement_of_another_task_does_not_vouch_for_this_one(self) -> None:
        key = "E05-S01-03-KEYFRAME-V1"
        path = self.transaction(key, LIVE, provider_cost_credits=0.9, provider_remote_status="completed",
                                hopsapi_key_fingerprint=hops.key_fingerprint())
        raw = self.raw / f"{key}_{KEPT}.json"
        raw.write_text(json.dumps({"provider": "hopsapi", "task_id": KEPT, "remote_status": "completed",
                                   "urls": ["https://example.invalid/f.png"], "cost": 0.9}), encoding="utf-8")

        def query(_task_id):
            raise not_found()

        with self.assertRaises(hops.HopsapiError):
            self.poll([self.row(key, KEPT, path)], query)

    def test_404_under_the_same_key_still_fails_and_names_the_task(self) -> None:
        key = "E08-S01-04-KEYFRAME-V1"
        path = self.transaction(key, LOST, hopsapi_key_fingerprint=hops.key_fingerprint())

        def query(_task_id):
            raise not_found()

        with self.assertRaises(hops.HopsapiError) as caught:
            self.poll([self.row(key, LOST, path)], query)
        self.assertIn(key, str(caught.exception))
        self.assertIn(LOST, str(caught.exception))
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["state"], "SUBMITTED_TASK_ID_BOUND")

    def test_other_http_errors_are_not_touched(self) -> None:
        key = "E08-S01-05-KEYFRAME-V1"
        path = self.transaction(key, LOST)

        def query(_task_id):
            raise hops.HopsapiHTTPError(403, {"message": "forbidden"}, "forbidden")

        with self.assertRaises(hops.HopsapiHTTPError):
            self.poll([self.row(key, LOST, path)], query)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["state"], "SUBMITTED_TASK_ID_BOUND")


if __name__ == "__main__":
    unittest.main()
