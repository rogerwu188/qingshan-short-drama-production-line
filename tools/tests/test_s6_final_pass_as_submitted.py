"""S6 final pass keeps what was actually submitted (lab Holmes E06 2026-10-26).

The final full compile re-attached predecessor tails to units whose bound take opened on their own keyframe,
and the V2 renderer turned a CHAR-tagged start frame into an identity line, so prompt finalization asked to
approve 10 prompts that would never be submitted.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nalu_pipeline as npl  # noqa: E402
from tools import h3_director_prompt_v2 as v2  # noqa: E402
from tools.tests.test_camera_grammar_start_frames import LEGACY, STAMPED, PipelineFixture  # noqa: E402


def _unit(role: str) -> dict:
    return {"reference_images": [{"path": "/kf/B.png", "role": role},
                                 {"path": "/id/A.png", "role": "CHARACTER_IDENTITY_REFERENCE",
                                  "entity_id": "CHAR-A", "provider_entity_label": "Alpha"}],
            "reference_image_sequence": [{"entity_id": "CHAR-A", "role": "CHARACTER_REFERENCE",
                                          "path": "/kf/B.png", "provider_entity_label": "Alpha"}]}


class OpeningFrameRendering(unittest.TestCase):
    def lines(self, role: str, stamped: bool) -> list[str]:
        return v2._reference_lines(_unit(role), {}, onscreen=set(), people=1, beings=0, exact_first_frame=stamped)

    def test_char_tagged_start_frame_is_the_exact_first_frame_when_stamped(self):
        for role in ("CONTINUITY_DERIVED_ENTRY_STATE", "ADMITTED_NEW_EVENT_ENTRY_STATE"):
            lines = self.lines(role, True)
            self.assertTrue(lines[0].startswith("@Image1 is the exact first frame:"), (role, lines[0]))
            self.assertTrue(lines[1].startswith("@Image2 is Alpha's face and body."), lines[1])

    def test_unstamped_rendering_is_unchanged(self):
        self.assertEqual(self.lines("CONTINUITY_DERIVED_ENTRY_STATE", False)[0], "@Image1 is Alpha's face and body.")

    def test_identity_role_at_image1_stays_an_identity_line(self):
        self.assertEqual(self.lines("CHARACTER_REFERENCE", True)[0], "@Image1 is Alpha's face and body.")


class PreproductionKeepsSubmittedStartFrame(unittest.TestCase):
    def test_reads_only_untailed_submissions_and_only_for_stamped(self):
        import build_nalu_preproduction as bnp
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "reports").mkdir()
            (Path(tmp) / "reports" / "E03_S6_WAVE_STATE.json").write_text(json.dumps({"start_frame_as_submitted": {
                "E03-VU-002": {"predecessor_tail_submitted": False},
                "E03-VU-003": {"predecessor_tail_submitted": True}}}))
            self.assertEqual(bnp.submitted_without_tail_units(Path(tmp), "E03", STAMPED), {"E03-VU-002"})
            self.assertEqual(bnp.submitted_without_tail_units(Path(tmp), "E03", LEGACY), set())

    def _build(self, boundary_class: str, withheld: bool, flag: bool):
        from tools import build_video_unit_anchor_plan as bva

        def boundary(prev, unit):
            if prev is None:
                return {"status": "PASS", "boundary_class": "NEW_EVENT_ANCHOR", "previous_unit_id": None}
            return {"status": "PASS", "boundary_class": boundary_class, "previous_unit_id": prev["unit_id"],
                    "same_continuous_event": True}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(bva, "classify_boundary", boundary), \
                mock.patch.object(bva, "compile_internal_shot_boundaries", lambda _u: {"status": "PASS"}), \
                mock.patch.object(bva.unit_action_continuity_contract, "evaluate", lambda *_a: {"status": "PASS"}):
            for name in ("A", "B"):
                Path(tmp, f"{name}-keyframe-v1.png").touch()
            tail = {"path": str(Path(tmp) / "U1.png"), "sha256": "abc"}
            u2 = {"unit_id": "U2", "scene_id": "S1", "editorial_shot_ids": ["B"],
                  ("withheld_previous_unit_final_frame" if withheld else "previous_unit_final_frame"): tail}
            if flag:
                u2["start_frame_source"] = "OWN_KEYFRAME_TAIL_REJECTED"
            grouping = {"units": [{"unit_id": "U1", "scene_id": "S1", "editorial_shot_ids": ["A"]}, u2]}
            editorial = {"shots": [{"shot_id": "A", "scene_id": "S1", "prompt_spec": {}},
                                   {"shot_id": "B", "scene_id": "S1", "prompt_spec": {}}]}
            return bva.build(grouping, editorial, Path(tmp))["units"][1], tail["path"]

    def test_withheld_tail_is_audit_only_for_an_own_keyframe_cut(self):
        unit, tail = self._build("MOTIVATED_CUT", withheld=True, flag=True)
        self.assertNotIn(tail, unit["reference_image_paths"])
        self.assertEqual(unit["anchor_count_decision"]["anchor_roles"], ["CONTINUITY_DERIVED_ENTRY_STATE"])
        self.assertEqual(unit["opening_anchor_contract"]["rejected_tail_path"], tail)

    def test_hard_continuation_still_opens_on_a_withheld_tail(self):
        unit, tail = self._build("HARD_CONTINUATION", withheld=True, flag=True)
        self.assertEqual(unit["reference_image_paths"][0], tail)


class StartFrameAsSubmittedRecord(unittest.TestCase):
    def _take(self, refs):
        return [{"task_id": "T2", "transaction": "/store/E03-VU-002__x.json", "prompt_sha256": "p",
                 "reference_sha256": refs}]

    def test_records_whether_the_bound_take_carried_the_tail(self):
        with tempfile.TemporaryDirectory() as d, PipelineFixture(Path(d), STAMPED) as fx:
            (fx.ctx.p.video_media / "E03-VU-002.mp4").write_bytes(b"clip")
            tail_sha = npl.sha256_file(fx.tail)
            with mock.patch.object(npl, "s6_live_bindings", return_value=self._take(["kf"])):
                rows = npl.record_start_frames_as_submitted(fx.ctx)
            self.assertEqual(rows["E03-VU-002"]["predecessor_tail_submitted"], False)
            state = json.loads((fx.ctx.p.preprod_reports / "E03_S6_WAVE_STATE.json").read_text())
            self.assertEqual(state["start_frame_as_submitted"], rows)
            with mock.patch.object(npl, "s6_live_bindings", return_value=self._take(["kf", tail_sha])):
                rows = npl.record_start_frames_as_submitted(fx.ctx)
            self.assertEqual(rows["E03-VU-002"]["predecessor_tail_submitted"], True)
            # a parked clip (redo) drops out: its next submission decides afresh
            (fx.ctx.p.video_media / "E03-VU-002.mp4").unlink()
            with mock.patch.object(npl, "s6_live_bindings", return_value=self._take(["kf"])):
                self.assertEqual(npl.record_start_frames_as_submitted(fx.ctx), {})

    def test_unstamped_records_nothing(self):
        with tempfile.TemporaryDirectory() as d, PipelineFixture(Path(d), LEGACY) as fx:
            (fx.ctx.p.video_media / "E03-VU-002.mp4").write_bytes(b"clip")
            with mock.patch.object(npl, "s6_live_bindings", return_value=self._take(["kf"])):
                self.assertEqual(npl.record_start_frames_as_submitted(fx.ctx), {})
            self.assertFalse((fx.ctx.p.preprod_reports / "E03_S6_WAVE_STATE.json").exists())

    def test_bound_take_on_disk_needs_clip_and_binding(self):
        with tempfile.TemporaryDirectory() as d, PipelineFixture(Path(d), STAMPED) as fx:
            with mock.patch.object(npl, "s6_live_bindings", return_value=self._take(["kf"])):
                self.assertIsNone(npl.bound_take_on_disk(fx.ctx, "E03-VU-002"))
                (fx.ctx.p.video_media / "E03-VU-002.mp4").write_bytes(b"clip")
                self.assertEqual(npl.bound_take_on_disk(fx.ctx, "E03-VU-002")["task_id"], "T2")
            with mock.patch.object(npl, "s6_live_bindings", return_value=[]):
                self.assertIsNone(npl.bound_take_on_disk(fx.ctx, "E03-VU-002"))


class FinalizationExemptsHarvestedBoundTakes(unittest.TestCase):
    TAKE = [{"task_id": "T2", "transaction": "/store/E03-VU-002__x.json", "prompt_sha256": "sub",
             "reference_sha256": ["kf"]}]
    REPORT = {"rows": [{"unit_id": "E03-VU-001", "status": "CHANGED", "planned_sha256": "a", "final_sha256": "b"},
                       {"unit_id": "E03-VU-002", "status": "CHANGED", "planned_sha256": "c", "final_sha256": "re"}]}

    def test_clip_from_bound_take_needs_no_receipt_others_still_do(self):
        with tempfile.TemporaryDirectory() as d, PipelineFixture(Path(d), STAMPED) as fx:
            (fx.ctx.p.video_media / "E03-VU-002.mp4").write_bytes(b"clip")
            live = lambda _ctx, uid, **_k: self.TAKE if uid == "E03-VU-002" else []  # noqa: E731
            with mock.patch.object(npl, "s6_live_bindings", live):
                left, exempt = npl.exempt_harvested_bound_takes(
                    fx.ctx, ["E03-VU-001", "E03-VU-002"], self.REPORT, {"E03-VU-002": {"x": 1}})
            self.assertEqual(left, ["E03-VU-001"])
            row = exempt["E03-VU-002"]
            self.assertEqual((row["task_id"], row["submitted_prompt_sha256"], row["recompiled_prompt_sha256"]),
                             ("T2", "sub", "re"))
            self.assertFalse(row["recompiled_matches_submitted"])
            self.assertEqual(row["submitted_prompt_review"], "NO_MATCHING_RECEIPT_ON_DISK")

    def test_parked_clip_is_resubmitted_so_it_still_needs_a_receipt(self):
        with tempfile.TemporaryDirectory() as d, PipelineFixture(Path(d), STAMPED) as fx:
            with mock.patch.object(npl, "s6_live_bindings", return_value=self.TAKE):
                left, exempt = npl.exempt_harvested_bound_takes(fx.ctx, ["E03-VU-002"], self.REPORT, {})
            self.assertEqual((left, exempt), (["E03-VU-002"], {}))


class HardContinuationOpeningRendering(unittest.TestCase):
    def test_char_tagged_previous_real_final_frame_opens_the_clip(self):
        unit = _unit("PREVIOUS_UNIT_REAL_FINAL_FRAME")
        lines = v2._reference_lines(unit, {}, onscreen=set(), people=1, beings=0, exact_first_frame=True)
        self.assertTrue(lines[0].startswith("@Image1 is the exact first frame:"), lines[0])


if __name__ == "__main__":
    unittest.main()
