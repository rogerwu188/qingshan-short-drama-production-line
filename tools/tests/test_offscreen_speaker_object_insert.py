"""An object insert whose only cast row is an offscreen speaker (field E11 2026-11-15, device 1101)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import build_nalu_preproduction as pre  # noqa: E402
import h3_director_prompt_v2 as director  # noqa: E402

SISTER = "CHAR-XUANMENSISTER"
OFFSCREEN_ROW = {"character": "玄门宗师妹", "character_id": SISTER, "life_state": "alive",
                 "face_visibility": "OFFSCREEN_VOICE_ONLY"}


def unit(cast) -> dict:
    return {
        "reference_images": [{"path": "open.png", "role": "ADMITTED_NEW_EVENT_ENTRY_STATE"},
                             {"path": "sister.png", "role": "CHARACTER_IDENTITY_REFERENCE", "entity_id": SISTER,
                              "provider_entity_label": "Xuanmensister"}],
        "ordered_prompt_specs": [{
            "cast": cast,
            "role_semantic_disambiguation": {"lip_owner_id": "", "dialogue_speaker_id": SISTER,
                                             "entity_presence": {SISTER: "OFFSCREEN_VOICE_ONLY"}},
        }],
    }


class OffscreenSpeakerObjectInsertTest(unittest.TestCase):
    def test_authored_offscreen_speaker_gets_no_blocking_slot(self) -> None:
        visible = {"character": "孟子秋", "character_id": "CHAR-MENGZIQIU"}
        hidden = {"character": "路人", "character_id": "CHAR-EXTRA", "first_frame_visible": False}
        self.assertEqual(pre.blocking_cast({"cast": [OFFSCREEN_ROW]}), [])
        self.assertEqual(pre.blocking_cast({"cast": [visible, OFFSCREEN_ROW, hidden]}), [visible])

    def test_sheet_of_an_offscreen_only_speaker_is_identity_only_when_nobody_is_on_screen(self) -> None:
        lines = director._reference_lines(unit([OFFSCREEN_ROW]), {}, onscreen=set(), people=0, beings=0,
                                          exact_first_frame=True)
        sheet = lines[1]
        self.assertIn("Xuanmensister stays out of frame in this clip", sheet)
        self.assertNotIn("already in @Image1", sheet)

    def test_visible_character_keeps_the_same_person_sentence(self) -> None:
        shown = {"character": "玄门宗师妹", "character_id": SISTER, "face_visibility": "VISIBLE_PER_FRAME_CONTENT"}
        subject = unit([shown])
        subject["ordered_prompt_specs"][0]["role_semantic_disambiguation"]["entity_presence"] = {
            SISTER: "VISIBLE_AND_IDENTITY_LOCKED"}
        self.assertEqual(director.offscreen_only_entity_ids(subject), set())
        lines = director._reference_lines(subject, {}, onscreen=set(), people=1, beings=0, exact_first_frame=True)
        self.assertIn("already in @Image1", lines[1])

    def test_offscreen_in_one_shot_but_shown_in_another_is_not_offscreen_only(self) -> None:
        subject = unit([OFFSCREEN_ROW])
        subject["ordered_prompt_specs"].append({
            "cast": [{"character": "玄门宗师妹", "character_id": SISTER}],
            "role_semantic_disambiguation": {"entity_presence": {SISTER: "VISIBLE_AND_IDENTITY_LOCKED"}}})
        self.assertEqual(director.offscreen_only_entity_ids(subject), set())


if __name__ == "__main__":
    unittest.main()
