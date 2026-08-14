import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.e40_u18_v17_output_machine_promotion import ASSETS, CREDIT_NAME, RESULT_NAMES, ROOT, V11_BOUNDARY, V7_FILES, compile_promotion
from tools.e40_u18_v9_offline_snapshot_ingest import EXPECTED, TEMPLATES


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(root: Path) -> tuple[Path, Path]:
    for relative, _ in [*V7_FILES.values(), V11_BOUNDARY]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    snapshots = root / "snapshots"
    snapshots.mkdir()
    result_rows = []
    for task_id, (task_key, fingerprint) in EXPECTED.items():
        target = root / ASSETS[task_id]["expected_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(("fixture-" + task_id).encode())
        row = {
            "source": "EXACT_TASK_RESULT_SNAPSHOT",
            "task_id": task_id,
            "task_key": task_key,
            "submission_fingerprint": fingerprint,
            "download_template_sha256": TEMPLATES["download"],
            "machine_contract_sha256": TEMPLATES["machine"],
            "status": "SUCCESS",
            "output": {
                "path": ASSETS[task_id]["expected_path"],
                "sha256": sha(target),
                "dimensions": {"width": 1024, "height": 1024},
                "provenance": "exact task result synthetic fixture",
                "license_or_local_authorship": "local test fixture only",
                "mask_path": None,
                "mask_sha256": None,
            },
        }
        path = snapshots / RESULT_NAMES[task_id]
        path.write_text(json.dumps(row), encoding="utf-8")
        result_rows.append({"task_id": task_id, "snapshot_sha256": sha(path), "output_sha256": sha(target)})
    credit = {
        "source": "AUTHORITATIVE_CREDIT_STATEMENT_SNAPSHOT",
        "credit_template_sha256": TEMPLATES["credit"],
        "task_ids": list(EXPECTED),
        "rows": [{"row_id": "pay-1"}, {"row_id": "pay-2"}],
        "classification": {"pay": 128, "refund": 0, "net": 128, "status": "PASS"},
    }
    credit_path = snapshots / CREDIT_NAME
    credit_path.write_text(json.dumps(credit), encoding="utf-8")
    readiness = {
        "status": "READY_FOR_LOCAL_OUTPUT_QA",
        "ingest": {"status": "PASS", "result_rows": result_rows, "credit_snapshot_sha256": sha(credit_path)},
        "admission_permitted": False,
    }
    readiness_path = root / "v15_readiness.json"
    readiness_path.write_text(json.dumps(readiness), encoding="utf-8")
    return snapshots, readiness_path


class PromotionContractTest(unittest.TestCase):
    def test_exact_valid_snapshot_compiles_no_admission_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshots, readiness = fixture(root)
            result = compile_promotion(snapshots, readiness, root)
            self.assertTrue(result["status"].startswith("PROMOTION_MANIFEST_READY"))
            self.assertEqual(len(result["promotion_manifest"]["assets"]), 2)
            self.assertFalse(result["output_admission_permitted"])
            self.assertFalse(result["assembly_permitted"])
            self.assertFalse(result["video_authorization_permitted"])

    def test_v15_not_ready_stays_remote_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshots, readiness = fixture(root)
            data = json.loads(readiness.read_text())
            data["status"] = "TASK_LOCAL_REMOTE_WAIT"
            readiness.write_text(json.dumps(data))
            self.assertEqual(compile_promotion(snapshots, readiness, root)["status"], "TASK_LOCAL_REMOTE_WAIT")

    def test_incomplete_credit_stays_remote_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshots, readiness = fixture(root)
            credit = json.loads((snapshots / CREDIT_NAME).read_text())
            credit["classification"]["refund"] = None
            (snapshots / CREDIT_NAME).write_text(json.dumps(credit))
            self.assertEqual(compile_promotion(snapshots, readiness, root)["status"], "TASK_LOCAL_REMOTE_WAIT")

    def test_missing_provenance_and_path_drift_stay_remote_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshots, readiness = fixture(root)
            path = snapshots / next(iter(RESULT_NAMES.values()))
            row = json.loads(path.read_text())
            row["output"]["provenance"] = ""
            row["output"]["path"] = "wrong.png"
            path.write_text(json.dumps(row))
            result = compile_promotion(snapshots, readiness, root)
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")
            self.assertTrue(any("PROVENANCE_MISSING" in failure for failure in result["failures"]))
            self.assertTrue(any("DOWNLOAD_PATH_LOCK_FAILED" in failure for failure in result["failures"]))

    def test_stale_v15_snapshot_lock_stays_remote_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshots, readiness = fixture(root)
            data = json.loads(readiness.read_text())
            data["ingest"]["credit_snapshot_sha256"] = "0" * 64
            readiness.write_text(json.dumps(data))
            result = compile_promotion(snapshots, readiness, root)
            self.assertEqual(result["status"], "TASK_LOCAL_REMOTE_WAIT")
            self.assertIn("V15_CREDIT_SNAPSHOT_SHA_LOCK_FAILED", result["failures"])


if __name__ == "__main__":
    unittest.main()
