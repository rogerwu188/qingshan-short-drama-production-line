"""A monologue reuse unit is registered against the keyframe it actually reuses.

Lycan King E05 (2026-11-15): VU-004/007/017 continue a speaker's take after a listener cutaway and
start from that take's keyframe (MONOLOGUE_SAME_SETUP_KEYFRAME_REUSE, no keyframe task of their
own).  The register walked previous_unit_id instead and bound the cutaway's keyframe prompt, so the
whole-batch prompt review covered the wrong still.
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
QA = ROOT / "lines/nalu/runtime/tools/prompt_batch_qa.py"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


class RegisterMonologueReuseTests(unittest.TestCase):
    def _fixture(self, tmp: Path, *, with_report: bool = True, chain: bool = False):
        """VU-001 speaker take (S01-01), VU-002 cutaway (S01-03), VU-003 speaker again (S01-04, reuse),
        VU-004 tail-derived from VU-003, and with chain=True VU-005 (S01-07) reusing through S01-04."""
        work = tmp / "work"
        pre = work / "E99" / "preproduction"
        (pre / "prompts").mkdir(parents=True)
        (pre / "planned").mkdir()
        spec = [("E99-VU-001", "E99-S01-01", True), ("E99-VU-002", "E99-S01-03", True),
                ("E99-VU-003", "E99-S01-04", False), ("E99-VU-004", "E99-S01-06", False)]
        if chain:
            spec.append(("E99-VU-005", "E99-S01-07", False))
        units, tasks, planned = [], [], []
        for uid, shot, own_keyframe in spec:
            vp = pre / "planned" / f"{uid}.txt"
            vp.write_text(f"video {uid}", encoding="utf-8")
            units.append({"unit_id": uid, "editorial_shot_ids": [shot]})
            planned.append({"unit_id": uid, "path": str(vp), "sha256": _sha(vp)})
            if own_keyframe:
                kf = pre / "prompts" / f"{shot}.txt"
                kf.write_text(f"keyframe {shot}", encoding="utf-8")
                tasks.append({"shot_id": shot, "prompt_file": str(kf), "prompt_sha256": _sha(kf)})
        units[2]["same_setup_as_unit"] = "E99-VU-001"
        anchors = [{"unit_id": "E99-VU-003", "opening_anchor_contract": {"previous_unit_id": "E99-VU-002"}},
                   {"unit_id": "E99-VU-004", "opening_anchor_contract": {
                       "source": "CONTINUITY_DERIVED_KEYFRAME", "previous_unit_id": "E99-VU-002"}}]
        table = [{"shot_id": "E99-S01-01", "decision": "NEW_KEYFRAME"},
                 {"shot_id": "E99-S01-03", "decision": "NEW_KEYFRAME"},
                 {"shot_id": "E99-S01-04", "decision": "REUSE_NO_NEW_KEYFRAME",
                  "reuse_mode": "MONOLOGUE_SAME_SETUP_KEYFRAME_REUSE",
                  "reuse_source": "E99-S01-01", "reuse_source_unit_id": "E99-VU-001"}]
        if chain:
            anchors.append({"unit_id": "E99-VU-005", "opening_anchor_contract": {"previous_unit_id": "E99-VU-004"}})
            table.append({"shot_id": "E99-S01-07", "decision": "REUSE_NO_NEW_KEYFRAME",
                          "reuse_mode": "MONOLOGUE_SAME_SETUP_KEYFRAME_REUSE",
                          "reuse_source": "E99-S01-04", "reuse_source_unit_id": "E99-VU-003"})
        (pre / "E99_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps({"units": units}))
        (pre / "E99_KEYFRAME_IMAGE_MANIFEST_V1.json").write_text(json.dumps({"tasks": tasks}))
        (pre / "E99_VIDEO_UNIT_ANCHOR_PLAN_V1.json").write_text(json.dumps({"units": anchors}))
        if with_report:
            (pre / "E99_KEYFRAME_IMAGE_MANIFEST_V1_report.json").write_text(json.dumps({"decision_table": table}))
        (pre / "E99_GROUPED_SEEDANCE_MANIFEST_PLANNING_V1.planned_prompts.json").write_text(
            json.dumps({"rows": planned}))
        return work, pre

    def _rows(self, tmp: Path, work: Path, pre: Path):
        runtime = tmp / "runtime"
        runtime.mkdir(exist_ok=True)
        qa = tmp / "qa"
        qa.mkdir(exist_ok=True)
        env = dict(os.environ, NALU_ENGINE_ROOT=str(ROOT), NALU_RUNTIME_ROOT=str(runtime),
                   NALU_WORK_ROOT=str(work))
        env.pop("GIGGLE_API_KEY", None)
        run = subprocess.run([sys.executable, str(TOOL), "--episode", "E99", "--execution-id", "E99-B",
                              "--qa-dir", str(qa), "--report", str(tmp / "report.json")],
                             env=env, capture_output=True, text=True)
        batch = pre / "E99_PROMPT_BATCH_V1.json"
        self.assertTrue(batch.is_file(), run.stdout[-400:] + run.stderr[-600:])
        return {r["unit_id"]: r["keyframe_prompt"] for r in json.loads(batch.read_text())["rows"]}

    def test_reuse_unit_binds_the_speakers_keyframe_not_the_cutaway(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            work, pre = self._fixture(tmp)
            rows = self._rows(tmp, work, pre)
            kp = rows["E99-VU-003"]
            self.assertEqual(kp["shot_id"], "E99-S01-01")
            self.assertEqual(kp["sha256"], _sha(pre / "prompts" / "E99-S01-01.txt"))
            self.assertEqual(kp["derivation"]["kind"], "MONOLOGUE_SAME_SETUP_KEYFRAME_REUSE")
            self.assertEqual(kp["derivation"]["reuse_source_shot_id"], "E99-S01-01")
            self.assertEqual(kp["derivation"]["reuse_source_unit_id"], "E99-VU-001")

    def test_tail_derived_unit_is_unchanged(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            work, pre = self._fixture(tmp)
            kp = self._rows(tmp, work, pre)["E99-VU-004"]
            self.assertEqual(kp["shot_id"], "E99-S01-03")
            self.assertEqual(kp["derivation"]["kind"], "CONTINUITY_DERIVED_FROM_PREVIOUS_UNIT_TAIL")

    def test_reuse_chain_resolves_to_the_keyframe_that_exists(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            work, pre = self._fixture(tmp, chain=True)
            kp = self._rows(tmp, work, pre)["E99-VU-005"]
            self.assertEqual(kp["shot_id"], "E99-S01-01")
            self.assertEqual(kp["derivation"]["kind"], "MONOLOGUE_SAME_SETUP_KEYFRAME_REUSE")
            self.assertEqual(kp["derivation"]["reuse_source_unit_id"], "E99-VU-001")

    def test_without_a_decision_table_the_old_walk_still_applies(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            work, pre = self._fixture(tmp, with_report=False)
            kp = self._rows(tmp, work, pre)["E99-VU-003"]
            self.assertEqual(kp["shot_id"], "E99-S01-03")
            self.assertEqual(kp["derivation"]["kind"], "CONTINUITY_DERIVED_FROM_PREVIOUS_UNIT_TAIL")

    def test_digest_names_the_reuse_instead_of_a_previous_tail(self):
        text = QA.read_text(encoding="utf-8")
        self.assertIn('derived == "MONOLOGUE_SAME_SETUP_KEYFRAME_REUSE"', text)
        self.assertIn("kf_prompt_monologue_same_setup_reuse", text)


if __name__ == "__main__":
    unittest.main()
