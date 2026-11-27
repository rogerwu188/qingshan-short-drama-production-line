"""A CONTINUOUS_ACTION chain of any length registers every unit (device 1101 E29 2026-11-27).

prompt_batch_register walked a continuity-derived unit back to the nearest authored keyframe with a hard
6-hop cap, so in a 26-unit chain rooted at VU-001 every unit past the 6th link (VU-008..VU-026) failed with
"no keyframe task ... and no continuity source" and S5 could not register.  The walk now goes to the chain
root however long the chain is, and a cycle in previous_unit_id stops it instead of looping forever.
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


class LongContinuityChainRegistersTests(unittest.TestCase):
    def _fixture(self, tmp: Path, n_units: int, *, cycle: bool = False):
        work = tmp / "work"
        pre = work / "E99" / "preproduction"
        (pre / "prompts").mkdir(parents=True)
        (pre / "planned").mkdir()
        units, tasks, planned, anchors = [], [], [], []
        for n in range(1, n_units + 1):
            uid, shot = f"E99-VU-{n:03d}", f"E99-S01-{n:02d}"
            vp = pre / "planned" / f"{uid}.txt"
            vp.write_text(f"video {n}", encoding="utf-8")
            units.append({"unit_id": uid, "editorial_shot_ids": [shot]})
            planned.append({"unit_id": uid, "path": str(vp), "sha256": _sha(vp)})
            if n == 1 and not cycle:
                kf = pre / "prompts" / f"{shot}.txt"
                kf.write_text("root keyframe", encoding="utf-8")
                tasks.append({"shot_id": shot, "prompt_file": str(kf), "prompt_sha256": _sha(kf)})
                anchors.append({"unit_id": uid, "opening_anchor_contract": {}})
            else:
                prev = f"E99-VU-{(n - 1 if n > 1 else n_units):03d}"
                anchors.append({"unit_id": uid, "opening_anchor_contract": {
                    "source": "PREVIOUS_UNIT_REAL_TAIL", "previous_unit_id": prev}})
        (pre / "E99_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps({"units": units}))
        (pre / "E99_KEYFRAME_IMAGE_MANIFEST_V1.json").write_text(json.dumps({"tasks": tasks}))
        (pre / "E99_GROUPED_SEEDANCE_MANIFEST_PLANNING_V1.planned_prompts.json").write_text(
            json.dumps({"rows": planned}))
        (pre / "E99_VIDEO_UNIT_ANCHOR_PLAN_V1.json").write_text(json.dumps({"units": anchors}))
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
                              env=env, capture_output=True, text=True, timeout=120)

    def test_a_26_unit_chain_registers_every_unit_against_the_root_keyframe(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            work, pre = self._fixture(tmp, 26)
            run = self._run(tmp, work)
            batch = pre / "E99_PROMPT_BATCH_V1.json"
            self.assertTrue(batch.is_file(), run.stdout[-800:] + run.stderr[-800:])
            rows = {r["unit_id"]: r for r in json.loads(batch.read_text())["rows"]}
            self.assertEqual(len(rows), 26)
            for n in range(2, 27):
                kp = rows[f"E99-VU-{n:03d}"]["keyframe_prompt"]
                self.assertEqual(kp["shot_id"], "E99-S01-01")
                self.assertEqual(kp["derivation"]["keyframe_prompt_of_unit"], "E99-VU-001")
                self.assertEqual(kp["derivation"]["previous_unit_id"], f"E99-VU-{n - 1:03d}")

    def test_a_cycle_without_any_keyframe_terminates_and_holds(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            work, pre = self._fixture(tmp, 5, cycle=True)
            run = self._run(tmp, work)
            self.assertEqual(run.returncode, 2, run.stderr[-600:])
            report = json.loads((tmp / "report.json").read_text())
            self.assertEqual(report["status"], "HOLD")
            self.assertFalse((pre / "E99_PROMPT_BATCH_V1.json").is_file())


if __name__ == "__main__":
    unittest.main()
