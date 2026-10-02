"""S6 prompt-finalisation ``diff`` is parallel across units, byte-identical to the serial digest.

The digest is reviewed by a human and SHA-bound downstream, so the parallel run must produce the
exact same bytes as the old serial loop for the same inputs.  These tests build a multi-unit fixture
(no network, no engine checkout) and prove (a) byte-identity against a serial reference, (b) a unit
whose comparison raises does not corrupt the others' rows, and (c) the comparison runs once per unit.
"""
import difflib
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools"))
import prompt_batch_finalize as finalizer  # noqa: E402


def _serial_reference_rows(tx, planned, engine):
    """The exact per-unit loop ``diff`` ran before parallelisation, kept here as the oracle."""
    rows = []
    for task in tx["tasks"]:
        uid = task["unit_id"]
        final_path = engine / task["prompt_file"]
        if not final_path.is_file():
            rows.append({"unit_id": uid, "status": "FINAL_PROMPT_MISSING"}); continue
        final_sha = finalizer.sha(final_path)
        pl = planned[uid]
        planned_path = engine / pl["video_prompt"]["path"]
        planned_sha = pl["video_prompt"]["sha256"]
        if final_sha == planned_sha:
            rows.append({"unit_id": uid, "status": "UNCHANGED", "sha256": final_sha}); continue
        a = planned_path.read_text(encoding="utf-8").splitlines()
        b = final_path.read_text(encoding="utf-8").splitlines()
        ud = list(difflib.unified_diff(a, b, fromfile="planned", tofile="final", lineterm="", n=0))
        changed = [l for l in ud if l.startswith(("+", "-")) and not l.startswith(("+++", "---"))]
        rows.append({"unit_id": uid, "status": "CHANGED", "planned_sha256": planned_sha, "final_sha256": final_sha,
                     "planned_path": finalizer.rel(planned_path), "final_path": finalizer.rel(final_path),
                     "changed_line_count": len(changed), "diff": changed[:80]})
    return rows


class PromptBatchFinalizeParallelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = self.root / "engine"
        self.human_dir = self.root / "human"
        self.prompts = self.engine / "prompts"
        self.prompts.mkdir(parents=True)
        # Four units: U1 unchanged, U2/U4 changed, U3 missing final prompt.
        self.units = ["U1", "U2", "U3", "U4"]
        rows, tasks = [], []
        for uid in self.units:
            planned_path = self.prompts / f"{uid}_planned.txt"
            planned_path.write_text(f"line one\nline two {uid}\n", encoding="utf-8")
            final_rel = f"prompts/{uid}_final.txt"
            if uid != "U3":
                final_text = (f"line one\nline two {uid}\n" if uid == "U1"
                              else f"line one CHANGED\nline two {uid}\n")
                (self.engine / final_rel).write_text(final_text, encoding="utf-8")
            rows.append({"unit_id": uid, "video_prompt": {
                "path": finalizer.rel(planned_path),
                "sha256": finalizer.sha(planned_path),
            }})
            tasks.append({"unit_id": uid, "prompt_file": final_rel})
        self.batch = {"episode": "E99", "execution_id": "E99-PROMPT-BATCH-V1", "rows": rows}
        self.tx = {"tasks": tasks}
        self.batch_path = self.human_dir / "batch.json"
        self.tx_path = self.human_dir / "tx.json"
        self.batch_path.parent.mkdir(parents=True, exist_ok=True)
        self.batch_path.write_text(json.dumps(self.batch), encoding="utf-8")
        self.tx_path.write_text(json.dumps(self.tx), encoding="utf-8")
        self._fixed = datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc)

    def _run_diff(self, out_name):
        out = self.root / out_name
        with patch.object(finalizer, "ENGINE", self.engine), \
             patch.object(finalizer, "rel", side_effect=lambda p: str(Path(p).resolve().relative_to(self.engine.resolve()))
                        if str(Path(p).resolve()).startswith(str(self.engine.resolve())) else str(p)), \
             patch.object(finalizer, "datetime") as dt:
            dt.now.return_value = self._fixed
            dt.now.side_effect = None
            report = finalizer.diff("E99", "E99-PROMPT-BATCH-V1", out,
                                    batch_path=self.batch_path, transaction_path=self.tx_path)
        return out, report

    def test_digest_is_byte_identical_to_serial_reference(self):
        out, report = self._run_diff("parallel_digest.json")
        planned = {r["unit_id"]: r for r in self.batch["rows"]}
        with patch.object(finalizer, "ENGINE", self.engine), \
             patch.object(finalizer, "rel", side_effect=lambda p: str(Path(p).resolve().relative_to(self.engine.resolve()))
                        if str(Path(p).resolve()).startswith(str(self.engine.resolve())) else str(p)):
            serial_rows = _serial_reference_rows(self.tx, planned, self.engine)
        serial_report = {
            "schema": "nalu.prompt_batch_finalization_digest.v1", "episode": "E99",
            "execution_id": "E99-PROMPT-BATCH-V1", "generated_at": self._fixed.isoformat(),
            "rows": serial_rows,
            "summary": {"unchanged": 1, "changed": 2, "missing": 1},
        }
        expected_bytes = (json.dumps(serial_report, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        self.assertEqual(out.read_bytes(), expected_bytes)
        self.assertEqual(report["summary"], {"unchanged": 1, "changed": 2, "missing": 1})

    def test_comparison_runs_once_per_unit(self):
        calls = []
        real_compare = finalizer.compare_unit

        def counting(task, planned, **kwargs):
            calls.append(task["unit_id"])
            return real_compare(task, planned, **kwargs)

        with patch.object(finalizer, "compare_unit", side_effect=counting):
            self._run_diff("count_digest.json")
        self.assertEqual(sorted(calls), sorted(self.units))
        self.assertEqual(len(calls), len(self.units))

    def test_raising_unit_is_reported_without_corrupting_others(self):
        real_compare = finalizer.compare_unit

        def flaky(task, planned, **kwargs):
            if task["unit_id"] == "U2":
                raise RuntimeError("boom in U2")
            return real_compare(task, planned, **kwargs)

        with patch.object(finalizer, "compare_unit", side_effect=flaky):
            out, report = self._run_diff("flaky_digest.json")
        by_uid = {row["unit_id"]: row for row in report["rows"]}
        self.assertEqual(by_uid["U2"]["status"], "COMPARE_FAILED")
        self.assertIn("boom in U2", by_uid["U2"]["error"])
        # Other units still carry their real rows.
        self.assertEqual(by_uid["U1"]["status"], "UNCHANGED")
        self.assertEqual(by_uid["U4"]["status"], "CHANGED")
        self.assertEqual(by_uid["U3"]["status"], "FINAL_PROMPT_MISSING")
        self.assertEqual(report["summary"]["compare_failed"], 1)
        self.assertEqual(report["summary"]["changed"], 1)
        # Row order still follows the transaction's task order.
        self.assertEqual([row["unit_id"] for row in report["rows"]], self.units)


if __name__ == "__main__":
    unittest.main()
