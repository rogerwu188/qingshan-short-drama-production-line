"""A registration that drops a unit must not overwrite the previous good one.

E11 (2026-10-09): one stale planning-index row made prompt_batch_register drop E11-VU-004 and
still write the batch, so a 58-row registration on disk became 57 rows.  The gate then failed
closed, but the good registration was gone and had to be rebuilt.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "lines/nalu/runtime/tools/prompt_batch_register.py"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class RegisterRefusesToWriteOnProblemTests(unittest.TestCase):
    def _fixture(self, tmp: Path, *, stale: bool):
        work = tmp / "work"
        pre = work / "E99" / "preproduction"
        (pre / "prompts").mkdir(parents=True)
        (pre / "planned").mkdir()
        units, tasks, planned = [], [], []
        for n in (1, 2):
            uid, shot = f"E99-VU-00{n}", f"E99-S0{n}-01"
            kf = pre / "prompts" / f"{shot}.txt"
            kf.write_text(f"keyframe {n}", encoding="utf-8")
            vp = pre / "planned" / f"{uid}.txt"
            vp.write_text(f"video {n}", encoding="utf-8")
            units.append({"unit_id": uid, "editorial_shot_ids": [shot]})
            tasks.append({"shot_id": shot, "prompt_file": str(kf), "prompt_sha256": _sha(kf)})
            planned.append({"unit_id": uid, "path": str(vp),
                            "sha256": "0" * 64 if (stale and n == 2) else _sha(vp)})
        (pre / "E99_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps({"units": units}))
        (pre / "E99_KEYFRAME_IMAGE_MANIFEST_V1.json").write_text(json.dumps({"tasks": tasks}))
        (pre / "E99_GROUPED_SEEDANCE_MANIFEST_PLANNING_V1.planned_prompts.json").write_text(
            json.dumps({"rows": planned}))
        return work, pre

    def _run(self, tmp: Path, work: Path):
        runtime = tmp / "runtime"
        runtime.mkdir(exist_ok=True)
        qa = tmp / "qa"
        qa.mkdir(exist_ok=True)
        env = dict(os.environ, NALU_ENGINE_ROOT=str(ROOT), NALU_RUNTIME_ROOT=str(runtime),
                   NALU_WORK_ROOT=str(work))
        env.pop("GIGGLE_API_KEY", None)
        return subprocess.run([sys.executable, str(TOOL), "--episode", "E99", "--execution-id", "E99-B",
                               "--qa-dir", str(qa), "--report", str(tmp / "report.json")],
                              env=env, capture_output=True, text=True)

    def test_a_good_registration_survives_a_later_run_that_drops_a_unit(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            work, pre = self._fixture(tmp, stale=False)
            first = self._run(tmp, work)
            batch = pre / "E99_PROMPT_BATCH_V1.json"
            self.assertTrue(batch.is_file(), first.stderr[-600:])
            self.assertEqual(len(json.loads(batch.read_text())["rows"]), 2)
            before = batch.read_bytes()
            # the planning index goes stale for one unit
            work2, _ = self._fixture(tmp / "again", stale=True)
            idx = pre / "E99_GROUPED_SEEDANCE_MANIFEST_PLANNING_V1.planned_prompts.json"
            rows = json.loads(idx.read_text())["rows"]
            rows[1]["sha256"] = "0" * 64
            idx.write_text(json.dumps({"rows": rows}))
            second = self._run(tmp, work)
            self.assertEqual(second.returncode, 2)
            report = json.loads((tmp / "report.json").read_text())
            self.assertEqual(report["status"], "HOLD")
            self.assertFalse(report["manifest_written"])
            self.assertEqual(batch.read_bytes(), before, "the previous registration must be unchanged")


if __name__ == "__main__":
    unittest.main()
