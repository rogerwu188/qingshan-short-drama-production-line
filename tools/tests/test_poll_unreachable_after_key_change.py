"""A bound HopsAPI video task that answers 404 after the fleet key was replaced (field E09 2026-11-15)."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import hopsapi_video_client as hopsapi  # noqa: E402
import poll_giggle_submit_report as poller  # noqa: E402
import video_live_binding  # noqa: E402

TASK_ID = "tsk_mwhb48ce_382a9be7766d5689f6ae3ee9"
NOW = "2026-11-15T04:36:11Z"


def not_found(_task_id):
    raise hopsapi.HopsapiHTTPError(404, {"code": 404, "message": "Task not found", "task_id": ""},
                                   '{"code":404,"message":"Task not found","task_id":""}')


class UnreachableAfterKeyChangeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store = self.root / "transactions"
        self.store.mkdir()
        env = mock.patch.dict(os.environ, {hopsapi.API_KEY_ENV: "new-key", "NALU_FLEET_URL": "off"})
        env.start()
        self.addCleanup(env.stop)
        self.new_key = hopsapi.key_fingerprint()

    def transaction(self, **fields) -> Path:
        row = {"task_key": "E09-VU-001", "provider": "hopsapi", "state": "SUBMITTED_TASK_ID_BOUND",
               "task_id": TASK_ID, "attempt_id": "a1", "submission_fingerprint": "8ee6d38a08241e54",
               "hopsapi_key_fingerprint": "0123456789abcdef", "estimated_credits": 5.5,
               "response_recorded_at": "2026-11-15T04:00:10Z"}
        row.update(fields)
        path = self.store / "E09-VU-001__8ee6d38a08241e54.json"
        path.write_text(json.dumps(row), encoding="utf-8")
        return path

    def write_off(self, path: Path):
        return hopsapi.write_off_task_unreachable_after_key_change(path, TASK_ID, now=NOW, error="HTTP 404")

    def test_task_created_under_another_key_is_written_off_at_the_planned_price(self) -> None:
        path = self.transaction()
        row = self.write_off(path)
        self.assertIsNotNone(row)
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["state"], "WRITTEN_OFF_UNATTRIBUTABLE_RETRYABLE")
        self.assertEqual(saved["written_off_credits"], 5.5)
        self.assertEqual(saved["retry_guard"], "RETRY_ALLOWED_NEW_ATTEMPT")
        self.assertEqual(saved["unreachable_task"]["task_id"], TASK_ID)
        self.assertEqual(saved["unreachable_task"]["queried_key_fingerprint"], self.new_key)
        self.assertEqual(saved["state_history"][-1]["state"], "SUBMITTED_TASK_ID_BOUND")
        # no longer a live binding: the next S6 re-entry compiles and POSTs the one new attempt
        self.assertEqual(video_live_binding.live_bindings(self.store, "E09-VU-001", root=self.root,
                                                          episode="E09", failed_task_ids=set()), [])

    def test_missing_planned_price_uses_the_fallback(self) -> None:
        path = self.transaction(estimated_credits=None)
        self.assertEqual(self.write_off(path)["written_off_credits"], hopsapi.UNREACHABLE_FALLBACK_CREDITS)

    def test_same_key_is_never_written_off(self) -> None:
        path = self.transaction(hopsapi_key_fingerprint=self.new_key)
        self.assertIsNone(self.write_off(path))
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["state"], "SUBMITTED_TASK_ID_BOUND")

    def test_row_without_a_recorded_key_is_never_written_off(self) -> None:
        path = self.transaction(hopsapi_key_fingerprint=None)
        self.assertIsNone(self.write_off(path))

    def test_settled_terminal_or_rebound_rows_are_left_alone(self) -> None:
        for fields in ({"provider_cost_credits": 5.5}, {"remote_terminal_state": "failed"},
                       {"task_id": "tsk_other"}, {"state": "CHARGED_WRITTEN_OFF_BY_ORDER"}):
            with self.subTest(fields=fields):
                path = self.transaction(**fields)
                before = path.read_text(encoding="utf-8")
                self.assertIsNone(self.write_off(path))
                self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_open_h3_lease_is_released(self) -> None:
        path = self.transaction(h3_lease={"lease_id": "L1", "mode": "local"})
        with mock.patch("h3_fleet_queue.release", return_value=True) as release:
            self.write_off(path)
        self.assertEqual(release.call_args.args[1], "failed")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["h3_lease"]["released_at"], NOW)

    def poll_row(self, path: Path) -> dict:
        row = {"task_key": "E09-VU-001", "task_id": TASK_ID, "provider": "hopsapi", "transaction": str(path)}
        with mock.patch.object(hopsapi, "query_task", side_effect=not_found):
            return poller.poll_one(1, row, self.root / "video", True)

    def test_poll_reports_the_unit_instead_of_raising(self) -> None:
        status = self.poll_row(self.transaction())
        self.assertEqual(status["remote_status"], "unreachable_after_key_change")
        self.assertEqual(status["transaction_state"], "WRITTEN_OFF_UNATTRIBUTABLE_RETRYABLE")
        self.assertEqual(status["written_off_credits"], 5.5)
        self.assertEqual(status["downloaded_files"], [])

    def test_poll_still_raises_on_a_404_under_the_same_key(self) -> None:
        path = self.transaction(hopsapi_key_fingerprint=self.new_key)
        with self.assertRaises(hopsapi.HopsapiHTTPError):
            self.poll_row(path)

    def test_poll_still_raises_on_other_http_errors(self) -> None:
        path = self.transaction()
        row = {"task_key": "E09-VU-001", "task_id": TASK_ID, "provider": "hopsapi", "transaction": str(path)}
        with mock.patch.object(hopsapi, "query_task", side_effect=hopsapi.HopsapiHTTPError(403, {}, "forbidden")):
            with self.assertRaises(hopsapi.HopsapiHTTPError):
                poller.poll_one(1, row, self.root / "video", True)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["state"], "SUBMITTED_TASK_ID_BOUND")


if __name__ == "__main__":
    unittest.main()
