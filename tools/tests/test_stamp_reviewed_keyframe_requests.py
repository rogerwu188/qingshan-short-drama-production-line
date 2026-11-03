"""The review-binding stamp: only a prompt the registered batch reviewed is stamped, and a reviewed change to an
already-submitted task declares the supersede the duplicate-POST guard asks for (E14 S5, 2026-11-02)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location(
    "stamp_tool", ROOT / "lines/nalu/runtime/tools/stamp_reviewed_keyframe_requests.py")
stamp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stamp)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class StampTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.original_engine = stamp.ENGINE
        stamp.ENGINE = self.tmp
        self.addCleanup(setattr, stamp, "ENGINE", self.original_engine)
        self.tasks = []
        self.rows = []
        for shot, text in (("E99-S01-01", "reviewed prompt"), ("E99-S01-02", "prompt changed after review")):
            path = self.tmp / f"{shot}.txt"
            path.write_text(text, encoding="utf-8")
            self.tasks.append({"task_key": f"{shot}-KEYFRAME-V1", "shot_id": shot, "episode": "E99",
                               "prompt_file": str(path), "prompt_sha256": _sha(text),
                               "model": "m", "reference_images": [], "reference_bindings": []})
            reviewed = text if shot == "E99-S01-01" else "the text the reviewer saw"
            self.rows.append({"keyframe_prompt": {"shot_id": shot, "sha256": _sha(reviewed)}})

    def _run(self, status="PASS"):
        manifest = self.tmp / "manifest.json"
        manifest.write_text(json.dumps({"tasks": self.tasks}), encoding="utf-8")
        batch = self.tmp / "batch.json"
        batch.write_text(json.dumps({"execution_id": "X", "rows": self.rows}), encoding="utf-8")
        report = self.tmp / "report.json"
        report.write_text(json.dumps({"status": status, "execution_id": "X"}), encoding="utf-8")
        rc = stamp.main(["--episode", "E99", "--manifest", str(manifest), "--batch-manifest", str(batch),
                         "--register-report", str(report)])
        return rc, json.loads(manifest.read_text(encoding="utf-8"))["tasks"]

    def test_only_the_reviewed_prompt_is_stamped(self):
        rc, tasks = self._run()
        self.assertEqual(rc, 0)
        self.assertTrue(tasks[0].get("reviewed_request_sha256"))
        self.assertNotIn("reviewed_request_sha256", tasks[1])

    def test_nothing_is_stamped_when_the_batch_is_not_registered_pass(self):
        rc, tasks = self._run(status="HOLD")
        self.assertEqual(rc, 2)
        self.assertNotIn("reviewed_request_sha256", tasks[0])

    def test_a_reviewed_change_to_a_submitted_task_declares_the_supersede(self):
        old = self.tmp / "workflow/tasks/giggle_submit_transactions/E99"
        old.mkdir(parents=True)
        (old / "E99-S01-01-KEYFRAME-V1__oldoldoldoldoldo.json").write_text(
            json.dumps({"submission_fingerprint": "f" * 64, "state": "SUBMITTED_TASK_ID_BOUND",
                        "task_id": "t"}), encoding="utf-8")
        _, tasks = self._run()
        self.assertEqual(tasks[0]["supersedes_submission_fingerprints"], ["f" * 64])
        self.assertNotIn("supersedes_submission_fingerprints", tasks[1])   # unreviewed: still refused


if __name__ == "__main__":
    unittest.main()
