import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import gate_result_contract
from tools.gate_result_contract import write_gate_result


class GateResultContractTests(unittest.TestCase):
    def test_true_invocation_writes_matrix_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            out = write_gate_result(
                "E32", "G1", invoked=True, status="PASS", runner="runner.py",
                evidence="qa/evidence.json", root=Path(temp),
            )
            payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertTrue(payload["invoked"])
        self.assertEqual(payload["status"], "PASS")

    def test_false_invocation_cannot_be_backfilled(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "invoked=false"):
                write_gate_result(
                    "E32", "G1", invoked=False, status="PASS", runner="runner.py",
                    evidence="none", root=Path(temp),
                )


class CleanupNeverSpeaksOverTheRealErrorTests(unittest.TestCase):
    """The execution matrix is the record that says a gate truly ran.

    Its writer used to end in ``finally: if exists: unlink``. On the production
    mount ``unlink`` is refused (``PermissionError [Errno 1]``, measured), so
    that cleanup raised on the way out of a failed write and the caller was
    handed the cleanup's error instead of the real one. These tests pin the
    property that matters: whatever goes wrong, the caller is told *what* went
    wrong, and whatever was already on disk is still there afterwards.
    """

    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.matrix_dir = self.root / "qa" / "gate_results" / "E32"

    def _write(self, **overrides):
        kwargs = dict(
            invoked=True, status="PASS", runner="runner.py",
            evidence="qa/evidence.json", root=self.root,
        )
        kwargs.update(overrides)
        return write_gate_result("E32", "G1", **kwargs)

    @staticmethod
    def _refuse_unlink(*_args, **_kwargs):
        raise PermissionError(1, "Operation not permitted")

    def _mount_refuses_delete(self):
        """Reproduce the measured mount behaviour: every delete is refused.

        Both spellings have to be patched. ``pathlib`` binds ``os.unlink`` at
        import time, so patching ``os.unlink`` alone leaves ``Path.unlink``
        working -- which would let these tests pass against code that never
        handled the refusal at all.
        """
        patches = [
            mock.patch.object(os, "unlink", self._refuse_unlink),
            mock.patch.object(Path, "unlink", autospec=True,
                              side_effect=PermissionError(1, "Operation not permitted")),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def _stray_files(self):
        return sorted(p.name for p in self.matrix_dir.iterdir() if p.name != "G1.json")

    def test_unserialisable_payload_reports_itself_not_the_cleanup(self):
        self._mount_refuses_delete()
        with self.assertRaises(TypeError):
            self._write(extra={"unserialisable": object()})

    def test_unserialisable_payload_creates_no_temporary_at_all(self):
        with self.assertRaises(TypeError):
            self._write(extra={"unserialisable": object()})
        self.assertEqual(self._stray_files(), [])
        self.assertFalse((self.matrix_dir / "G1.json").exists())

    def test_a_refused_replace_reports_itself_not_the_refused_unlink(self):
        self._mount_refuses_delete()
        boom = OSError(1, "replace refused by mount")
        with mock.patch.object(os, "replace", side_effect=boom):
            with self.assertRaises(OSError) as caught:
                self._write()
        self.assertIn("replace refused by mount", str(caught.exception))

    def test_a_temporary_that_cannot_be_deleted_is_renamed_out_of_the_way(self):
        self._mount_refuses_delete()
        with mock.patch.object(os, "replace", side_effect=OSError(1, "replace refused")):
            with self.assertRaises(OSError):
                self._write()
        stray = self._stray_files()
        self.assertEqual(len(stray), 1, stray)
        self.assertTrue(stray[0].endswith(".discarded"), stray)

    def test_when_delete_and_rename_are_both_refused_the_real_error_still_surfaces(self):
        self._mount_refuses_delete()
        with mock.patch.object(os, "replace", side_effect=OSError(1, "replace refused")), \
             mock.patch.object(Path, "replace", autospec=True,
                               side_effect=PermissionError(1, "rename refused")):
            with self.assertRaises(OSError) as caught:
                self._write()
        self.assertIn("replace refused", str(caught.exception))

    def test_a_failed_write_leaves_the_previous_verdict_byte_intact(self):
        self._write(status="FAIL")
        before = (self.matrix_dir / "G1.json").read_bytes()
        self._mount_refuses_delete()
        with mock.patch.object(os, "replace", side_effect=OSError(1, "replace refused")):
            with self.assertRaises(OSError):
                self._write(status="PASS")
        after = (self.matrix_dir / "G1.json").read_bytes()
        self.assertEqual(before, after)
        self.assertEqual(json.loads(after.decode("utf-8"))["status"], "FAIL")

    def test_a_failed_write_does_not_block_the_next_attempt(self):
        self._mount_refuses_delete()
        with mock.patch.object(os, "replace", side_effect=OSError(1, "replace refused")):
            with self.assertRaises(OSError):
                self._write()
        out = self._write(status="PASS")
        self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["status"], "PASS")

    def test_a_successful_write_leaves_no_residue(self):
        self._write()
        self.assertEqual(self._stray_files(), [])

    def test_the_record_is_flushed_to_disk_before_it_becomes_visible(self):
        order = []
        real_fsync, real_replace = os.fsync, os.replace

        def spy_fsync(fileno):
            # F-R530-01 之后还会有第三次 fsync，打在**父目录**上（让改名本身落盘）。
            # 分开记账，本断言问的仍是「内容有没有在 rename 之前落盘」。
            order.append("fsync_dir" if stat.S_ISDIR(os.fstat(fileno).st_mode) else "fsync")
            return real_fsync(fileno)

        def spy_replace(src, dst):
            order.append("replace")
            return real_replace(src, dst)

        with mock.patch.object(os, "fsync", spy_fsync), \
             mock.patch.object(os, "replace", spy_replace):
            self._write()
        # 内容 fsync → replace 提交 → 目录 fsync（F-R530-01：提交本身也落盘）。
        self.assertEqual(order, ["fsync", "replace", "fsync_dir"])

    def test_the_bytes_on_disk_are_unchanged_by_the_atomic_write(self):
        out = self._write(extra={"note": "太平醫館"}, score=4)
        text = out.read_text(encoding="utf-8")
        payload = json.loads(text)
        self.assertEqual(payload["schema"], "qingshan.gate_result.v1")
        self.assertEqual(payload["score"], 4)
        self.assertEqual(payload["note"], "太平醫館")
        self.assertIn('\n  "gate_id": "G1"', text)   # two-space indent preserved
        self.assertIn("太平醫館", text)                 # ensure_ascii=False preserved
        self.assertTrue(text.endswith("}\n"))        # trailing newline preserved

    def test_the_discard_ladder_is_silent_when_the_temporary_is_already_gone(self):
        missing = self.root / "does-not-exist.tmp"
        gate_result_contract._discard_temporary(missing)  # must not raise


if __name__ == "__main__":
    unittest.main()
