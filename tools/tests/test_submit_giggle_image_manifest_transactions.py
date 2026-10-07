import json
import tempfile
import unittest
from pathlib import Path

from tools.submit_giggle_image_manifest import (
    DuplicateSubmissionBlocked,
    atomic_json,
    classify_ambiguous_failures,
    prior_submission_result,
    submission_fingerprint,
    transaction_path,
)


def task() -> dict:
    return {
        "task_key": "E99-U01-A1-STILL-V1",
        "prompt_sha256": "a" * 64,
        "reference_bindings": [{"sha256": "b" * 64}],
        "model": "gpt-image-2-pro",
        "aspect_ratio": "9:16",
        "resolution": "2K",
    }


class GiggleSubmitTransactionTests(unittest.TestCase):
    def test_bound_task_id_is_reused_without_resubmit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = task()
            path = transaction_path(root, item)
            atomic_json(path, {
                "submission_fingerprint": submission_fingerprint(item),
                "state": "SUBMITTED_TASK_ID_BOUND",
                "task_id": "task-123",
                "receipt": "receipt.json",
            })
            result = prior_submission_result(item, root)
            self.assertEqual(result["task_id"], "task-123")
            self.assertTrue(result["recovered_from_transaction"])

    def test_charged_missing_task_id_blocks_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = task()
            path = transaction_path(root, item)
            atomic_json(path, {
                "submission_fingerprint": submission_fingerprint(item),
                "state": "CHARGED_TASK_ID_MISSING",
            })
            with self.assertRaises(DuplicateSubmissionBlocked):
                prior_submission_result(item, root)

    def test_aggregate_ledger_absence_is_not_zero_charge_proof(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = task()
            path = transaction_path(root, item)
            atomic_json(path, {
                "submission_fingerprint": submission_fingerprint(item),
                "state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
            })
            failures = [{"task_key": item["task_key"], "transaction": str(path), "credit": None}]
            summary = classify_ambiguous_failures(
                failures,
                known_submitted=3,
                matched_ledger_rows=3,
                transaction_dir=root,
            )
            self.assertEqual(summary, "BATCH_RESPONSE_LOSSES_QUARANTINED_PENDING_TASK_HISTORY_RECOVERY")
            self.assertEqual(failures[0]["credit_status"], "CHARGE_STATE_UNRESOLVED_BATCH")
            self.assertEqual(json.loads(path.read_text())["state"], "CHARGE_STATE_UNRESOLVED_BATCH")

    def test_multiple_ambiguous_charges_quarantine_every_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failures = []
            for index in range(2):
                item = task()
                item["task_key"] = f"E99-U0{index + 1}-A1-STILL-V1"
                path = transaction_path(root, item)
                atomic_json(path, {
                    "submission_fingerprint": submission_fingerprint(item),
                    "state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
                })
                failures.append({"task_key": item["task_key"], "transaction": str(path), "credit": None})
            classify_ambiguous_failures(
                failures,
                known_submitted=4,
                matched_ledger_rows=5,
                transaction_dir=root,
            )
            self.assertTrue(all(row["credit_status"] == "CHARGE_STATE_UNRESOLVED_BATCH" for row in failures))
            self.assertTrue(all(json.loads(Path(row["transaction"]).read_text())["state"] == "CHARGE_STATE_UNRESOLVED_BATCH" for row in failures))


    def test_transport_timeout_with_full_pay_window_is_retryable(self) -> None:
        """K054/e24: a Cloudflare 5xx with no task_id and pay rows == task ids bought nothing.

        nalu E11 S5, 2026-10-07: 50 tasks, two of them came back HTTP 524.  The credit window held
        48 pay rows for the 48 bound task ids (528 credits) both immediately and on a re-read ten
        minutes later, and project_id is empty on every row, so task history can never resolve it.
        The video submitter classifies exactly this shape as retryable; the image submitter was
        written before the rule existed and quarantined the whole batch instead.

        The transaction records this the way the real ones do: no response at all
        (`provider_response: null`) and the transport error in `error`.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failures = []
            for index in range(2):
                item = task()
                item["task_key"] = f"E99-U0{index + 1}-A1-STILL-V1"
                path = transaction_path(root, item)
                atomic_json(path, {
                    "submission_fingerprint": submission_fingerprint(item),
                    "state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
                    "provider_response": None,
                })
                failures.append({
                    "task_key": item["task_key"], "transaction": str(path), "credit": None,
                    "error": ('HTTP 524: {"title":"Error 524: A timeout occurred","status":524,'
                              '"error_name":"origin_response_timeout"}'),
                })
            summary = classify_ambiguous_failures(
                failures,
                known_submitted=48,
                matched_ledger_rows=48,
                transaction_dir=root,
            )
            self.assertEqual(summary, "PROVIDER_DECLINED_AND_LEDGER_ROWS_EQUAL_KNOWN_TASK_IDS")
            for row in failures:
                self.assertEqual(row["credit_status"], "NOT_CHARGED_RETRYABLE")
                self.assertEqual(json.loads(Path(row["transaction"]).read_text())["state"], "NOT_CHARGED_RETRYABLE")

    def test_transport_timeout_with_an_extra_pay_row_stays_quarantined(self) -> None:
        """The window is the proof: a pay row beyond our task ids means the timeout was charged."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            failures = []
            for index in range(2):
                item = task()
                item["task_key"] = f"E99-U0{index + 1}-A1-STILL-V1"
                path = transaction_path(root, item)
                atomic_json(path, {
                    "submission_fingerprint": submission_fingerprint(item),
                    "state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
                    "provider_response": None,
                })
                failures.append({"task_key": item["task_key"], "transaction": str(path),
                                 "credit": None, "error": "HTTP 524: origin_response_timeout"})
            classify_ambiguous_failures(
                failures, known_submitted=3, matched_ledger_rows=5, transaction_dir=root,
            )
            self.assertTrue(all(r["credit_status"] == "CHARGE_STATE_UNRESOLVED_BATCH" for r in failures))

    def test_a_response_carrying_a_task_id_is_never_treated_as_unbought(self) -> None:
        """A response that carries a task_id is a success, whatever else it says."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = task()
            path = transaction_path(root, item)
            atomic_json(path, {
                "submission_fingerprint": submission_fingerprint(item),
                "state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION",
                "provider_response": '{"status": 524, "task_id": "6f0c1f5e-0000-4000-8000-000000000000"}',
            })
            failures = [{"task_key": item["task_key"], "transaction": str(path), "credit": None}]
            classify_ambiguous_failures(
                failures, known_submitted=3, matched_ledger_rows=3, transaction_dir=root,
            )
            self.assertEqual(failures[0]["credit_status"], "CHARGE_STATE_UNRESOLVED_BATCH")


if __name__ == "__main__":
    unittest.main()
