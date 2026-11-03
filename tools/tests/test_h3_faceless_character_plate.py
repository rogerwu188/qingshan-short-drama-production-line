"""K075 (nalu E14 巡山者乙): a person whose face is never shown gets no H3 face plate.

A plate makes the H3 prompt say "lock this entity's face", which invites the model to turn
the man to camera.  Only a character marked NOT_MEASURABLE / FACE_OUT_OF_FRAME in every shot
of the episode is skipped; a character whose face is shown once keeps the plate everywhere.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (str(TOOLS), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _editorial():
    return {"shots": [
        {"shot_id": "S1", "prompt_spec": {"cast": [
            {"character_id": "CHAR-A"},
            {"character_id": "CHAR-B", "face_visibility": "BACK_THREE_QUARTER_FLEEING_NOT_MEASURABLE"}]}},
        {"shot_id": "S2", "prompt_spec": {"cast": [
            {"character_id": "CHAR-B", "face_visibility": "BACK_THREE_QUARTER_FLEEING_NOT_MEASURABLE"},
            {"character_id": "CHAR-C", "face_visibility": "BACK_THREE_QUARTER_TO_QIN_NOT_MEASURABLE"}]}},
        {"shot_id": "S3", "prompt_spec": {"cast": [{"character_id": "CHAR-C"}]}},
        {"shot_id": "S4", "prompt_spec": {"cast": [
            {"character_id": "CHAR-D", "face_visibility": "HANDS_ONLY_FACE_OUT_OF_FRAME"}]}},
    ]}


class FacelessCharacterGetsNoPlateTest(unittest.TestCase):
    def test_only_characters_never_shown_face_on_are_skipped(self):
        import build_nalu_preproduction as bnp
        self.assertEqual(bnp.faceless_character_ids(_editorial()), {"CHAR-B", "CHAR-D"})

    def test_a_face_shown_once_keeps_the_plate(self):
        import build_nalu_preproduction as bnp
        self.assertNotIn("CHAR-C", bnp.faceless_character_ids(_editorial()))


if __name__ == "__main__":
    unittest.main()


class KeyframeFaceHiddenTest(unittest.TestCase):
    def test_keyframe_skips_the_face_plate_only_where_the_shot_hides_the_face(self):
        import build_keyframe_manifest as bkm
        spec = {"cast": [{"character_id": "CHAR-A"},
                         {"character_id": "CHAR-B", "face_visibility": "BACK_THREE_QUARTER_FLEEING_NOT_MEASURABLE"},
                         {"character_id": "CHAR-C", "face_visibility": "HANDS_ONLY_FACE_OUT_OF_FRAME"}]}
        self.assertFalse(bkm.shot_keeps_face_hidden(spec, "CHAR-A"))
        self.assertTrue(bkm.shot_keeps_face_hidden(spec, "CHAR-B"))
        self.assertTrue(bkm.shot_keeps_face_hidden(spec, "CHAR-C"))
        self.assertFalse(bkm.shot_keeps_face_hidden(spec, "CHAR-Z"))
