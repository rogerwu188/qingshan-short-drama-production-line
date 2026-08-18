import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from fractions import Fraction
from io import StringIO
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "e40_u17_offline_callback_intake.py"
PRODUCTION_ROOT = SCRIPT.parents[1]
SPEC = importlib.util.spec_from_file_location("e40_u17_offline_callback_intake", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class U17OfflineCallbackIntakeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / MODULE.INBOX_REL).mkdir(parents=True)
        self.task_id = MODULE.TASK_ID
        self.tx_rel = MODULE.TRANSACTION_REL
        self.report_rel = MODULE.SUBMISSION_REPORT_REL
        self.submit_receipt_rel = MODULE.SUBMIT_RECEIPT_REL
        self.manifest_rel = MODULE.AUTHORIZED_MANIFEST_REL
        for rel in (self.tx_rel, self.report_rel, self.submit_receipt_rel, self.manifest_rel):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        self._write_authorities()
        self.source = self.root / "incoming.mp4"
        self.source.write_bytes(b"offline-real-video-fixture")
        self.sidecar = self.root / "incoming-sidecar.json"
        self._write_sidecar()

    def tearDown(self):
        self.temp.cleanup()

    def _write_json(self, rel: Path, value):
        (self.root / rel).write_text(json.dumps(value), encoding="utf-8")

    def _write_authorities(self):
        for rel in (self.tx_rel, self.report_rel, self.submit_receipt_rel, self.manifest_rel):
            shutil.copyfile(PRODUCTION_ROOT / rel, self.root / rel)

    def _write_sidecar(self, **overrides):
        value = {
            "schema": MODULE.SIDECAR_SCHEMA,
            "episode": "E40",
            "unit_id": "U17",
            "task_key": MODULE.TASK_KEY,
            "task_id": self.task_id,
            "model": MODULE.MODEL,
            "resolution": "720p",
            "aspect_ratio": "9:16",
            "credits": {"pay": 64, "refund": 0},
            "source": {
                "sha256": digest(self.source),
                "is_synthetic": False,
                "is_failed_or_quarantined_asset": False,
            },
            "transaction": {"path": self.tx_rel.as_posix(), "sha256": digest(self.root / self.tx_rel)},
            "submission_report": {
                "path": self.report_rel.as_posix(),
                "sha256": digest(self.root / self.report_rel),
            },
            "submit_receipt": {
                "path": self.submit_receipt_rel.as_posix(),
                "sha256": digest(self.root / self.submit_receipt_rel),
            },
        }
        value.update(overrides)
        self.sidecar.write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def probe(_path, frames=97):
        return {"width": 720, "height": 1280, "fps": Fraction(24, 1), "frames": frames}

    def test_accepts_97_frame_fast720_result_atomically(self):
        result = MODULE.run_intake(self.root, self.source, self.sidecar, self.probe)
        bundle = self.root / MODULE.INBOX_REL / MODULE.BUNDLE_NAME
        self.assertEqual(result["frames"], 97)
        self.assertTrue((bundle / MODULE.SOURCE_NAME).is_file())
        self.assertTrue((bundle / MODULE.SIDECAR_NAME).is_file())
        self.assertEqual(result["receipt_sha256"], digest(bundle / MODULE.RECEIPT_NAME))
        self.assertFalse(any(p.name.startswith(".u17-intake-stage-") for p in bundle.parent.iterdir()))
        accepted = MODULE.validate_accepted_bundle(self.root, self.probe)
        successor = self.root / "working_assets/successor/E40_U17_BOUND_RAW_MIN96F.mp4"
        mapping = MODULE.map_validated_source(
            accepted["source"], successor, accepted["source_sha256"]
        )
        self.assertFalse(mapping["reused"])
        self.assertEqual(digest(successor), accepted["source_sha256"])

    def test_writes_pinned_source_bound_sidecar_then_accepts_it(self):
        generated = self.root / "operator-drop/U17-sidecar.json"
        result = MODULE.write_source_bound_sidecar(
            self.root, self.source, generated, self.probe
        )
        self.assertEqual(result["frames"], 97)
        payload = json.loads(generated.read_text())
        self.assertEqual(payload["task_id"], MODULE.TASK_ID)
        self.assertEqual(payload["model"], "seedance-2.0-fast")
        self.assertEqual(payload["credits"], {"pay": 64, "refund": 0})
        self.assertEqual(payload["source"]["sha256"], digest(self.source))
        self.assertEqual(
            payload["transaction"],
            {"path": MODULE.TRANSACTION_REL.as_posix(), "sha256": MODULE.TRANSACTION_SHA256},
        )
        intake = MODULE.run_intake(self.root, self.source, generated, self.probe)
        self.assertEqual(intake["status"], "ACCEPTED_ATOMIC_OFFLINE_CALLBACK")

    def test_sidecar_writer_rejects_under96_and_overwrite(self):
        generated = self.root / "operator-drop/U17-sidecar.json"
        with self.assertRaises(MODULE.IntakeError):
            MODULE.write_source_bound_sidecar(
                self.root,
                self.source,
                generated,
                lambda _path: self.probe(_path, frames=95),
            )
        self.assertFalse(generated.exists())
        MODULE.write_source_bound_sidecar(self.root, self.source, generated, self.probe)
        original_sha = digest(generated)
        with self.assertRaises(MODULE.IntakeError):
            MODULE.write_source_bound_sidecar(self.root, self.source, generated, self.probe)
        self.assertEqual(digest(generated), original_sha)

    def test_rejects_under_96_frames_without_partial_bundle(self):
        with self.assertRaises(MODULE.IntakeError):
            MODULE.run_intake(
                self.root,
                self.source,
                self.sidecar,
                lambda _path: self.probe(_path, frames=95),
            )
        inbox = self.root / MODULE.INBOX_REL
        self.assertFalse((inbox / MODULE.BUNDLE_NAME).exists())
        self.assertEqual(list(inbox.iterdir()), [])

    def test_rejects_model_or_credit_mismatch_without_partial_bundle(self):
        self._write_sidecar(model="seedance-2.0-pro")
        with self.assertRaises(MODULE.IntakeError):
            MODULE.run_intake(self.root, self.source, self.sidecar, self.probe)
        self.assertFalse((self.root / MODULE.INBOX_REL / MODULE.BUNDLE_NAME).exists())

    def test_is_one_shot_and_refuses_to_overwrite_accepted_bundle(self):
        MODULE.run_intake(self.root, self.source, self.sidecar, self.probe)
        with self.assertRaises(MODULE.IntakeError):
            MODULE.run_intake(self.root, self.source, self.sidecar, self.probe)

    def test_cli_missing_source_returns_2_without_partial_bundle(self):
        with redirect_stdout(StringIO()):
            rc = MODULE.main(
                [
                    "--repo-root",
                    str(self.root),
                    "--source",
                    str(self.root / "missing.mp4"),
                    "--sidecar",
                    str(self.sidecar),
                ]
            )
        self.assertEqual(rc, 2)
        self.assertFalse((self.root / MODULE.INBOX_REL / MODULE.BUNDLE_NAME).exists())

    def test_rejects_forged_task_id_and_unrelated_authorities(self):
        forged_id = "11111111-2222-3333-4444-555555555555"
        forged_tx = Path("workflow/tasks/giggle_video_submit_transactions/E40/forged.json")
        forged_report = Path("qa/e40/forged-report.json")
        forged_receipt = Path("qa/e40/forged-submit-receipt.json")
        for rel in (forged_tx, forged_report, forged_receipt):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        self._write_json(
            forged_receipt, {"code": 200, "data": {"task_id": forged_id}}
        )
        self._write_json(
            forged_tx,
            {
                "task_key": MODULE.TASK_KEY,
                "state": "SUBMITTED_TASK_ID_BOUND",
                "task_id": forged_id,
                "model": MODULE.MODEL,
                "receipt": forged_receipt.as_posix(),
            },
        )
        self._write_json(forged_report, {"status": "PASS", "submitted": 1})
        self._write_sidecar(
            task_id=forged_id,
            transaction={"path": forged_tx.as_posix(), "sha256": digest(self.root / forged_tx)},
            submission_report={
                "path": forged_report.as_posix(),
                "sha256": digest(self.root / forged_report),
            },
            submit_receipt={
                "path": forged_receipt.as_posix(),
                "sha256": digest(self.root / forged_receipt),
            },
        )
        with self.assertRaises(MODULE.IntakeError):
            MODULE.run_intake(self.root, self.source, self.sidecar, self.probe)
        self.assertFalse((self.root / MODULE.INBOX_REL / MODULE.BUNDLE_NAME).exists())


if __name__ == "__main__":
    unittest.main()
