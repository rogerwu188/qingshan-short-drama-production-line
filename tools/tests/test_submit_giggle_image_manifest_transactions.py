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

    def test_zero_charge_timeout_becomes_retryable(self) -> None:
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
            self.assertEqual(summary, "ALL_RESPONSE_LOSSES_VERIFIED_NOT_CHARGED")
            self.assertEqual(failures[0]["credit_status"], "FAILED_ZERO_VERIFIED")
            self.assertEqual(json.loads(path.read_text())["state"], "NOT_CHARGED_RETRYABLE")

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


if __name__ == "__main__":
    unittest.main()
