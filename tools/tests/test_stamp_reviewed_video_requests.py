"""The video review-binding stamp: S6 rebuilds the manifest on every entry, so the stamp is applied inside the
stage, and only to a prompt the batch gate reviewed or whose change carries a signed incremental receipt (E14 S6,
2026-11-04: the first wave was refused twelve times with REVIEWED_REQUEST_NOT_BOUND before any charge)."""
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
    "stamp_video_tool", ROOT / "lines/nalu/runtime/tools/stamp_reviewed_video_requests.py")
stamp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stamp)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class VideoStampTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        original = stamp.ENGINE
        stamp.ENGINE = self.tmp
        self.addCleanup(setattr, stamp, "ENGINE", original)

    def _task(self, unit, text, *, on_disk=None, receipt=False):
        path = self.tmp / f"{unit}.txt"
        path.write_text(on_disk if on_disk is not None else text, encoding="utf-8")
        task = {"task_key": f"{unit}-VIDEO-V1", "unit_id": unit, "episode": "E99", "model": "m",
                "prompt_file": str(path), "prompt_sha256": _sha(text), "duration_seconds": 5,
                "reference_images": []}
        if receipt:
            task["prompt_batch_finalization"] = {"status": "PASS"}
        return task

    def _run(self, tasks, rows):
        manifest = self.tmp / "manifest.json"
        manifest.write_text(json.dumps({"tasks": tasks}), encoding="utf-8")
        digest = self.tmp / "digest.json"
        digest.write_text(json.dumps({"rows": rows}), encoding="utf-8")
        rc = stamp.main(["--episode", "E99", "--manifest", str(manifest), "--finalization-digest", str(digest)])
        return rc, {t["unit_id"]: t for t in json.loads(manifest.read_text(encoding="utf-8"))["tasks"]}

    def test_only_reviewed_or_signed_prompts_are_stamped(self):
        tasks = [
            self._task("VU-001", "reviewed"),
            self._task("VU-002", "changed, signed", receipt=True),
            self._task("VU-003", "changed, unsigned"),
            self._task("VU-004", "reviewed", on_disk="edited after the manifest was built"),
        ]
        rows = [
            {"unit_id": "VU-001", "status": "UNCHANGED", "sha256": _sha("reviewed")},
            {"unit_id": "VU-002", "status": "CHANGED", "final_sha256": _sha("changed, signed")},
            {"unit_id": "VU-003", "status": "CHANGED", "final_sha256": _sha("changed, unsigned")},
            {"unit_id": "VU-004", "status": "UNCHANGED", "sha256": _sha("reviewed")},
        ]
        rc, out = self._run(tasks, rows)
        self.assertEqual(rc, 0)
        self.assertTrue(out["VU-001"].get("reviewed_request_sha256"))
        self.assertTrue(out["VU-002"].get("reviewed_request_sha256"))
        self.assertNotIn("reviewed_request_sha256", out["VU-003"])
        self.assertNotIn("reviewed_request_sha256", out["VU-004"])

    def test_unchanged_row_with_a_different_sha_is_not_stamped(self):
        rc, out = self._run([self._task("VU-001", "final")],
                            [{"unit_id": "VU-001", "status": "UNCHANGED", "sha256": _sha("what was reviewed")}])
        self.assertEqual(rc, 0)
        self.assertNotIn("reviewed_request_sha256", out["VU-001"])

    def test_signed_redo_of_a_bound_unit_declares_the_earlier_take(self):
        """E14 wave 33 (2026-11-05): the reviewed fight redesign was refused BOUND_UNDER_OTHER_FINGERPRINT."""
        store = self.tmp / "workflow/tasks/giggle_video_submit_transactions/E99"
        store.mkdir(parents=True)
        for unit in ("VU-002", "VU-001"):
            (store / f"{unit}-VIDEO-V1__old.json").write_text(json.dumps(
                {"submission_fingerprint": f"old-{unit}", "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "t"}),
                encoding="utf-8")
        tasks = [self._task("VU-001", "reviewed"), self._task("VU-002", "redo, signed", receipt=True)]
        rows = [{"unit_id": "VU-001", "status": "UNCHANGED", "sha256": _sha("reviewed")},
                {"unit_id": "VU-002", "status": "CHANGED", "final_sha256": _sha("redo, signed")}]
        rc, out = self._run(tasks, rows)
        self.assertEqual(rc, 0)
        self.assertEqual(out["VU-002"].get("supersedes_submission_fingerprints"), ["old-VU-002"])
        self.assertNotIn("supersedes_submission_fingerprints", out["VU-001"])


if __name__ == "__main__":
    unittest.main()
