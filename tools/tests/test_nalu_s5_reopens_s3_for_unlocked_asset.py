"""A keyframe that must be POSTed but binds an asset the library has not locked re-opens S3.

Device ...0030 E19 (2026-11-16): a script revision after S3 PASS added a prop.  S3 has no input
fingerprint and stayed SKIPPED_ALREADY_PASS; S5 then failed in the stamper / submitter on the awaited
file and the paid entry offered no way back to S3.
"""
import importlib
import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
for _p in (str(TOOLS), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _task(key, pending):
    return {"task_key": key,
            "pending_bindings": [{"role": "prop", "entity_id": eid,
                                  "binding_status": "PENDING_ASSET_LIBRARY_ARTIFACT"} for eid in pending]}


class S5ReopensS3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("nalu_pipeline")

    def test_pending_asset_on_a_task_that_needs_a_post_is_reported(self) -> None:
        tasks = [_task("E19-S03-05-KEYFRAME-V1", ["PROP-HAIRDRYER"]), _task("E19-S01-01-KEYFRAME-V1", [])]
        out = self.mod.s5_unlocked_identity_assets(tasks, ["E19-S03-05-KEYFRAME-V1", "E19-S01-01-KEYFRAME-V1"])
        self.assertEqual(out, ["PROP-HAIRDRYER"])

    def test_pending_asset_on_an_already_admitted_task_is_ignored(self) -> None:
        tasks = [_task("E19-S03-05-KEYFRAME-V1", ["PROP-HAIRDRYER"]), _task("E19-S01-01-KEYFRAME-V1", [])]
        self.assertEqual(self.mod.s5_unlocked_identity_assets(tasks, ["E19-S01-01-KEYFRAME-V1"]), [])

    def test_fully_bound_tasks_report_nothing(self) -> None:
        tasks = [_task("A", []), {"task_key": "B"}]
        self.assertEqual(self.mod.s5_unlocked_identity_assets(tasks, ["A", "B"]), [])

    def test_ids_are_unique_and_sorted(self) -> None:
        tasks = [_task("A", ["PROP-B", "PROP-A"]), _task("B", ["PROP-A"])]
        self.assertEqual(self.mod.s5_unlocked_identity_assets(tasks, ["A", "B"]), ["PROP-A", "PROP-B"])

    def test_stage_s5_blocks_before_authorisation_and_reopens_s3(self) -> None:
        src = inspect.getsource(self.mod.stage_s5)
        check = src.index("s5_unlocked_identity_assets(tasks, needs_post)")
        self.assertLess(check, src.index("materialize_paid_authorization("))
        self.assertIn('ctx.stage_state("S3")["reopen_required"]', src)
        self.assertIn("IDENTITY_ASSET_NOT_LOCKED:", src)

    def test_runner_does_not_skip_a_reopened_s3_and_clears_the_flag_when_it_runs(self) -> None:
        src = (TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('and not (sid == "S3" and row.get("reopen_required"))', src)
        self.assertIn('row.pop("reopen_required", None)', src)


if __name__ == "__main__":
    unittest.main()
