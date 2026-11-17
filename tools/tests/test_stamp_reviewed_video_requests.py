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


    def test_reviewed_unchanged_prompt_that_differs_from_every_bound_take_declares_it(self):
        """E15 fight redo (2026-11-07): the reviewed batch prompt changed after the take was bound, the
        finalization digest says UNCHANGED (final == planned), and the submit was refused
        BOUND_UNDER_OTHER_FINGERPRINT on VU-014/015/017/018.  A bound take with a recorded, different
        prompt_sha256 is superseded; a take bound to the same prompt, or with no recorded prompt, is not."""
        store = self.tmp / "workflow/tasks/giggle_video_submit_transactions/E99"
        store.mkdir(parents=True)
        (store / "VU-001-VIDEO-V1__old.json").write_text(json.dumps(
            {"submission_fingerprint": "old-VU-001", "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "t",
             "prompt_sha256": _sha("the old take")}), encoding="utf-8")
        (store / "VU-002-VIDEO-V1__old.json").write_text(json.dumps(
            {"submission_fingerprint": "old-VU-002", "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "t",
             "prompt_sha256": _sha("reviewed")}), encoding="utf-8")
        tasks = [self._task("VU-001", "reviewed"), self._task("VU-002", "reviewed")]
        rows = [{"unit_id": "VU-001", "status": "UNCHANGED", "sha256": _sha("reviewed")},
                {"unit_id": "VU-002", "status": "UNCHANGED", "sha256": _sha("reviewed")}]
        rc, out = self._run(tasks, rows)
        self.assertEqual(rc, 0)
        self.assertEqual(out["VU-001"].get("supersedes_submission_fingerprints"), ["old-VU-001"])
        self.assertNotIn("supersedes_submission_fingerprints", out["VU-002"])


    def test_same_prompt_redo_from_a_new_start_frame_declares_the_earlier_take(self):
        """Field device ...1324 E16 VU-016 (2026-11-15): the engine's Q2 face-count redo regenerated the unit's
        own keyframe and kept the reviewed prompt; the redo wave was refused BOUND_UNDER_OTHER_FINGERPRINT.
        A bound take with this prompt but a different recorded reference set is superseded; the same
        references, or a take that recorded none, is an identical-request reroll and is not."""
        store = self.tmp / "workflow/tasks/giggle_video_submit_transactions/E99"
        store.mkdir(parents=True)
        for unit, refs in (("VU-001", ["old-frame"]), ("VU-002", ["new-frame"]), ("VU-003", None)):
            row = {"submission_fingerprint": f"old-{unit}", "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "t",
                   "prompt_sha256": _sha("reviewed")}
            if refs is not None:
                row["reference_sha256"] = refs
            (store / f"{unit}-VIDEO-V1__old.json").write_text(json.dumps(row), encoding="utf-8")
        tasks = []
        for unit in ("VU-001", "VU-002", "VU-003"):
            task = self._task(unit, "reviewed")
            task["reference_sha256"] = ["new-frame"]
            tasks.append(task)
        rows = [{"unit_id": unit, "status": "UNCHANGED", "sha256": _sha("reviewed")}
                for unit in ("VU-001", "VU-002", "VU-003")]
        rc, out = self._run(tasks, rows)
        self.assertEqual(rc, 0)
        self.assertEqual(out["VU-001"].get("supersedes_submission_fingerprints"), ["old-VU-001"])
        self.assertNotIn("supersedes_submission_fingerprints", out["VU-002"])
        self.assertNotIn("supersedes_submission_fingerprints", out["VU-003"])


    def test_redo_whose_own_take_failed_at_zero_cost_still_declares_the_original_take(self):
        """Field device ...0926 E14 VU-001/020 (2026-11-17): the reviewed redo was submitted, the provider
        failed it at zero cost, and on the next S6 entry the redo's own still-bound transaction (same prompt,
        same references) read as an identical-request reroll, so the supersede of the ORIGINAL take was
        dropped and the zero-cost retry was refused BOUND_UNDER_OTHER_FINGERPRINT.  The task's own transaction
        is not another take; a DIFFERENT-fingerprint take of the identical request still keeps the refusal."""
        store = self.tmp / "workflow/tasks/giggle_video_submit_transactions/E99"
        store.mkdir(parents=True)
        tasks = []
        for unit in ("VU-001", "VU-002"):
            task = self._task(unit, "reviewed redo")
            task["reference_sha256"] = ["new-frame"]
            tasks.append(task)
        own = {t["unit_id"]: stamp.task_fingerprint(t) for t in tasks}
        # VU-001: original billed take (old frame) + the redo's own failed-at-zero-cost bound row.
        (store / "VU-001-VIDEO-V1__old.json").write_text(json.dumps(
            {"submission_fingerprint": "old-VU-001", "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "t0",
             "prompt_sha256": _sha("reviewed redo"), "reference_sha256": ["old-frame"]}), encoding="utf-8")
        (store / "VU-001-VIDEO-V1__own.json").write_text(json.dumps(
            {"submission_fingerprint": own["VU-001"], "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "t1",
             "remote_terminal_state": "failed", "prompt_sha256": _sha("reviewed redo"),
             "reference_sha256": ["new-frame"]}), encoding="utf-8")
        # VU-002: same own row, but the other take is the identical request under a drifted fingerprint.
        (store / "VU-002-VIDEO-V1__old.json").write_text(json.dumps(
            {"submission_fingerprint": "old-VU-002", "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "t0",
             "prompt_sha256": _sha("reviewed redo"), "reference_sha256": ["new-frame"]}), encoding="utf-8")
        (store / "VU-002-VIDEO-V1__own.json").write_text(json.dumps(
            {"submission_fingerprint": own["VU-002"], "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "t1",
             "prompt_sha256": _sha("reviewed redo"), "reference_sha256": ["new-frame"]}), encoding="utf-8")
        rows = [{"unit_id": unit, "status": "UNCHANGED", "sha256": _sha("reviewed redo")}
                for unit in ("VU-001", "VU-002")]
        rc, out = self._run(tasks, rows)
        self.assertEqual(rc, 0)
        self.assertEqual(out["VU-001"].get("supersedes_submission_fingerprints"), ["old-VU-001"])
        self.assertNotIn("supersedes_submission_fingerprints", out["VU-002"])
        # The declaration does not move the fingerprint the own transaction is keyed by.
        self.assertEqual(stamp.task_fingerprint(out["VU-001"]), own["VU-001"])


if __name__ == "__main__":
    unittest.main()
