#!/usr/bin/env python3
"""A unit with no on-screen scripted line follows the performance cut, not the measured edit.

Fleet E13 (2026-11-14): VU-013 carried a 4.296 s narration, the performance cut held 0-4.796 s for it
(VO_HOLD), the measured edit's in-point 3.74 s turned that into a 1.056 s clip in the AgentCut build
and S7 stopped on VOICE_OVER_OVERLAPS_DIALOGUE on every rerun.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
NALU_TOOLS = ROOT / "lines/nalu/runtime/tools"
for _path in (str(ROOT), str(NALU_TOOLS), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tools import measured_edit_constraints as mec  # noqa: E402
from tools import performance_cut as pc  # noqa: E402


def _row(uid: str, a: float, b: float) -> dict:
    return {"unit_id": uid, "media_path": f"/x/{uid}.mp4", "media_sha256": "0" * 64,
            "source_asr_ref": f"/x/{uid}.json", "source_asr_sha256": "1" * 64,
            "recommended_source_in_seconds": a, "recommended_source_out_seconds": b}


PAYLOAD = {"schema": "nalu.measured_edit_constraints.v1", "episode": "E13",
           "units": [_row("E13-VU-012", 0.5, 3.0), _row("E13-VU-013", 3.74, 6.2)]}
PERF = {"schema": pc.SCHEMA, "units": [
    {"unit_id": "E13-VU-012", "kind": "SPEAKING", "reasons": ["TRIM_TAIL_TO_LINE"]},
    {"unit_id": "E13-VU-013", "kind": "SILENT", "reasons": ["SILENT_SPEECH_WINDOW"],
     "after_in": 0.0, "after_out": 4.796},
    {"unit_id": "E13-VU-014", "kind": "SILENT", "reasons": []}]}


class YieldTests(unittest.TestCase):
    def test_silent_unit_row_is_dropped_and_kept_for_audit(self):
        out, dropped = mec.yield_to_performance_cut(PAYLOAD, PERF)
        self.assertEqual(dropped, ["E13-VU-013"])
        self.assertEqual([r["unit_id"] for r in out["units"]], ["E13-VU-012"])
        kept = out["yielded_to_performance_cut"]
        self.assertEqual([(r["unit_id"], r["reason"], r["recommended_source_in_seconds"]) for r in kept],
                         [("E13-VU-013", "NO_ON_SCREEN_SCRIPTED_LINE", 3.74)])
        self.assertEqual(len(PAYLOAD["units"]), 2, "the input payload is not mutated")

    def test_speaking_units_and_missing_report_change_nothing(self):
        for perf in ({}, None, {"units": [{"unit_id": "E13-VU-012", "kind": "SPEAKING"},
                                          {"unit_id": "E13-VU-013", "kind": "SPEAKING"}]}):
            out, dropped = mec.yield_to_performance_cut(PAYLOAD, perf)
            self.assertEqual(dropped, [])
            self.assertIs(out, PAYLOAD)

    def test_applying_twice_is_stable(self):
        once, _ = mec.yield_to_performance_cut(PAYLOAD, PERF)
        twice, dropped = mec.yield_to_performance_cut(once, PERF)
        self.assertEqual(dropped, [])
        self.assertEqual(twice, once)

    def test_real_plan_marks_the_vo_only_unit_silent_and_keeps_room_for_its_vo(self):
        """The E13 shape end to end: narration voiced inside a V.O.-only unit, dialogue right after it."""
        contract = {"dialogue_language": "en", "audio_contract": {"dialogue_units": [
            {"shot_id": "S2", "speaker_id": "CHAR-A", "text": "You came back."}]}}
        grouping = {"units": [{"unit_id": "U1", "editorial_shot_ids": ["S1"]},
                              {"unit_id": "U2", "editorial_shot_ids": ["S2"]}]}
        asr = {"U1": [{"start": 3.8, "end": 6.0, "text": "I never forgot that night",
                       "words": [{"start": 3.8, "end": 6.0, "word": "night"}]}],
               "U2": [{"start": 0.2, "end": 1.4, "text": "You came back.", "words": [
                   {"start": 0.2, "end": 0.6, "word": "You"}, {"start": 0.6, "end": 1.0, "word": "came"},
                   {"start": 1.0, "end": 1.4, "word": "back."}]}]}
        perf = pc.plan(contract, grouping, asr, {"U1": 6.0, "U2": 4.0}, vo_seconds={"U1": [4.296]})
        u1 = next(r for r in perf["units"] if r["unit_id"] == "U1")
        self.assertEqual(u1["kind"], "SILENT")
        need = pc.VO_LEAD_IN + 4.296 + pc.VO_SEPARATION
        self.assertGreaterEqual(u1["after_out"] - u1["after_in"], need - 1e-6, "the unit keeps room for its V.O.")
        payload = {"units": [_row("U1", 3.72, 6.0), _row("U2", 0.12, 1.52)]}
        out, dropped = mec.yield_to_performance_cut(payload, perf)
        # U2's line is matched word by word with a tail guard: it follows the performance cut too (owner
        # 2026-11-21, E21 lines cut off -- the measured out-point is the S6 segment end + 0.12 s)
        self.assertEqual(dropped, ["U1", "U2"])
        self.assertEqual(out["units"], [])
        self.assertEqual([r["reason"] for r in out["yielded_to_performance_cut"]],
                         ["NO_ON_SCREEN_SCRIPTED_LINE", "PERFORMANCE_CUT_WORD_TIMED_TAIL_GUARD"])


class PipelineStepTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("nalu_pipeline_me_yield", NALU_TOOLS / "nalu_pipeline.py")
        cls.pipeline = importlib.util.module_from_spec(spec)
        sys.modules["nalu_pipeline_me_yield"] = cls.pipeline
        spec.loader.exec_module(cls.pipeline)

    def run_step(self, tmp: Path, *, perf: dict | None, constraints: dict | None):
        ctx = SimpleNamespace(episode="E13", p=SimpleNamespace(assembly=tmp))
        res = SimpleNamespace(details={})
        path = tmp / "E13_MEASURED_EDIT_CONSTRAINTS.json"
        if constraints is not None:
            path.write_text(json.dumps(constraints))
        if perf is not None:
            (tmp / "E13_PERFORMANCE_CUT.json").write_text(json.dumps(perf))
        dropped = self.pipeline.s7_measured_edit_yield_to_performance_cut(
            ctx, res, path if constraints is not None else None)
        return dropped, res, path

    def test_file_is_rewritten_without_the_silent_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            dropped, res, path = self.run_step(Path(tmp), perf=PERF, constraints=PAYLOAD)
            self.assertEqual(dropped, ["E13-VU-013"])
            self.assertEqual(res.details["measured_edit_yielded_to_performance_cut"], ["E13-VU-013"])
            self.assertEqual(sorted(mec.load_constraints(path)), ["E13-VU-012"])

    def test_no_report_or_no_constraints_is_a_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            dropped, res, path = self.run_step(Path(tmp), perf=None, constraints=PAYLOAD)
            self.assertEqual((dropped, res.details), ([], {}))
            self.assertEqual(json.loads(path.read_text()), PAYLOAD)
        with tempfile.TemporaryDirectory() as tmp:
            dropped, res, _ = self.run_step(Path(tmp), perf=PERF, constraints=None)
            self.assertEqual((dropped, res.details), ([], {}))

    def test_step_runs_after_the_performance_cut_and_before_the_build(self):
        src = (NALU_TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")
        cut = src.index("trimmed_asr, tail_trim = s7_dialogue_tail_trim(ctx, res")
        step = src.index("s7_measured_edit_yield_to_performance_cut(ctx, res, constraints_file)")
        self.assertLess(cut, step)
        self.assertLess(step, src.index('build_argv += ["--dialogue-tail-trim", tail_trim]'))


if __name__ == "__main__":
    unittest.main()
