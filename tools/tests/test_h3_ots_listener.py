"""OTS_LISTENER_V1 (line owner 2026-11-23): a dialogue unit may show the non-speaking listener as an
over-the-shoulder foreground figure -- back of the head and one shoulder, face never shown.

Before this, "HEAD" was no body-part word, so BACK_OF_HEAD_ONLY / BACK_OF_HEAD_OTS / OTS_LISTENER were
ignored and the listener was rendered (and keyframed, and counted) as a fully visible person: two front faces.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

from tools import h3_provider_prompt_renderer as h3v1
from tools.h3_director_prompt_v2 import director_v2_self_check
from tools.h3_provider_prompt_renderer import render_h3_prompt
from tools.tests.test_h3_director_prompt_v2 import B, fixture

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

OTS_VALUES = ("BACK_OF_HEAD_ONLY", "BACK_OF_HEAD_OTS", "OTS_LISTENER")
OTS_SENTENCE = ("0–3 s: Beta is seen from behind in the foreground, over-the-shoulder: only the back of Beta's head "
                "and one shoulder, slightly out of focus, at the frame edge; Beta's face is never shown; Beta does "
                "not speak.")


def ots_render(face_visibility: str) -> tuple[str, dict, dict, dict]:
    unit, plan = fixture()
    for member in unit["ordered_prompt_specs"][0]["cast"]:
        if member["character_id"] == B:
            member["face_visibility"] = face_visibility
    text, receipt = render_h3_prompt(unit, plan)
    return text, receipt, unit, plan


class OtsVocabularyTest(unittest.TestCase):
    def test_each_new_value_is_an_ots_part(self):
        for value in OTS_VALUES + ("ots_listener",):
            self.assertEqual(h3v1.partial_visibility_part(value), h3v1.OTS_PART, value)
        self.assertEqual(h3v1.partial_visibility_part("BACK_AND_SHOULDERS_ONLY"), "back and shoulders")
        self.assertEqual(h3v1.partial_visibility_part("HANDS_ONLY"), "hands")
        self.assertIsNone(h3v1.partial_visibility_part("VISIBLE_PER_FRAME_CONTENT"))
        self.assertFalse(h3v1.is_ots_visibility("SHOTS_VISIBLE"))

    def test_v1_partial_clause_for_ots_keeps_the_named_face_prohibition(self):
        clause = h3v1.partial_clause("Beta", h3v1.OTS_PART)
        self.assertIn("Beta is seen from behind in the foreground, over-the-shoulder", clause)
        self.assertIn("do not reveal Beta's face", clause)


class OtsDirectorRenderTest(unittest.TestCase):
    def test_each_value_renders_the_ots_listener(self):
        for value in OTS_VALUES + ("BACK_AND_SHOULDERS_ONLY",):  # PR #306 declaration, listener of a visible speaker
            text, receipt, unit, plan = ots_render(value)
            self.assertIn(OTS_SENTENCE, text, value)
            self.assertNotIn("Beta's face and body", text, value)
            self.assertEqual(receipt["shot_scope"]["status"], "PASS", value)
            self.assertEqual(director_v2_self_check(text, unit, plan), [], value)

    def test_reference_line_uses_the_sheet_for_the_back_only(self):
        text, *_ = ots_render("BACK_OF_HEAD_ONLY")
        self.assertIn("@Image3 is Beta's identity reference: use @Image3 only for Beta's hair, build and wardrobe "
                      "from behind; Beta's face is not shown.", text)
        self.assertIn("@Image2 is Alpha's face and body.", text)

    def test_header_says_who_faces_camera_and_who_is_behind(self):
        text, *_ = ots_render("OTS_LISTENER")
        self.assertIn("Who is in frame (exactly these two people, each exactly once, Alpha faces camera; Beta in the "
                      "foreground from behind (face not shown)):", text)
        self.assertNotIn("visible from the first frame to the last", text)
        self.assertNotIn("presence as noted for each", text)

    def test_hands_only_listener_keeps_the_old_wording(self):
        text, *_ = ots_render("HANDS_ONLY")
        self.assertIn("only Beta's hands in frame; Beta's face is not shown.", text)
        self.assertIn("use @Image3 only for Beta's build and wardrobe; Beta's face is not shown.", text)
        self.assertNotIn("over-the-shoulder", text)

    def test_no_ots_declaration_renders_unchanged(self):
        unit, plan = fixture()
        text, _ = render_h3_prompt(unit, plan)
        self.assertIn("@Image3 is Beta's face and body.", text)
        self.assertNotIn("over-the-shoulder", text)


class OtsKeyframeTest(unittest.TestCase):
    def test_keyframe_hides_the_face_and_states_the_ots_figure(self):
        import build_keyframe_manifest as bkm
        for value in OTS_VALUES + ("BACK_AND_SHOULDERS_ONLY",):
            spec = {"cast": [{"character_id": "CHAR-A", "character": "阿尔"},
                             {"character_id": "CHAR-B", "character": "贝塔", "face_visibility": value}]}
            self.assertTrue(bkm.shot_keeps_face_hidden(spec, "CHAR-B"), value)  # no headshot plate
            self.assertFalse(bkm.shot_keeps_face_hidden(spec, "CHAR-A"))
            lines = bkm.ots_listener_lines(spec)
            self.assertEqual(len(lines), 1)
            self.assertIn("只露出贝塔的后脑与一侧肩膀", lines[0])
            self.assertIn("the face is never shown", lines[0])
            self.assertIsNone(bkm.has_forbidden_word(lines[0]))
        self.assertEqual(bkm.ots_listener_lines({"cast": [{"character_id": "CHAR-A"}]}), [])
        src = (TOOLS / "build_keyframe_manifest.py").read_text(encoding="utf-8")
        self.assertIn('(f"ots_listener_{index}", line, True) for index, line in enumerate(ots_listener_lines(spec))',
                      src)


class OtsReviewExpectationTest(unittest.TestCase):
    EXP = {"cast": [{"character_id": "CHAR-A", "character": "阿尔", "shot_id": "S1"},
                    {"character_id": "CHAR-B", "character": "贝塔", "shot_id": "S1",
                     "face_visibility": "BACK_OF_HEAD_OTS"}],
           "required_visible_character_ids": ["CHAR-A", "CHAR-B"]}

    def test_q2_face_budget_expects_one_visible_face(self):
        import video_q2_builder as q2
        self.assertEqual(q2.declared_face_budget(self.EXP), (1, ["CHAR-A"]))
        one = [{"frame_index": i, "faces": 1} for i in range(1, 10)]
        self.assertEqual(q2.face_count_verdict(self.EXP, one)["status"], "PASS")
        two = [{"frame_index": i, "faces": 2} for i in range(1, 10)]
        self.assertEqual(q2.face_count_verdict(self.EXP, two)["status"], "FAIL")  # a second front face

    def test_q2_identity_measures_only_the_speaker(self):
        import video_q2_builder as q2
        measurable, exempt = q2.pose_scoped_ids({"expectations": self.EXP})
        self.assertEqual(measurable, ["CHAR-A"])
        self.assertEqual(exempt, {"CHAR-B": "BACK_OF_HEAD_OTS"})

    def test_q1_does_not_measure_the_ots_face(self):
        import keyframe_q1_builder as q1
        for value in OTS_VALUES + ("BACK_AND_SHOULDERS_ONLY",):
            self.assertTrue(q1.pose_exempt(value), value)
        self.assertEqual(q1.face_measurable_ids({"expectations": self.EXP}), ["CHAR-A"])

    def test_reviewer_is_told_the_ots_figure_is_present_not_invented(self):
        import nalu_qa_common as qa
        note = qa.ots_expectation(self.EXP["cast"])
        self.assertEqual(note["over_the_shoulder_characters"], ["贝塔"])
        self.assertEqual(qa.ots_expectation([{"character": "阿尔"}]), {})
        source = (TOOLS / "vlm_review_protocol.py").read_text(encoding="utf-8")
        # + the off-screen limb question's exception (2026-11-24)
        self.assertEqual(source.count("expectations.over_the_shoulder_characters"), 4)


if __name__ == "__main__":
    unittest.main()
