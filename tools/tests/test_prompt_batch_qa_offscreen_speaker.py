"""An offscreen speaker is not part of the keyframe's visible cast.

Fleet 1144 E02 VU029: the unit was replaced by an empty prop insert whose line is spoken
offscreen.  bind_dialogue_cast appended the speaker as OFFSCREEN_VOICE_ONLY, the keyframe prompt
correctly rendered a frame without people, and the batch gate then failed
``kf_visible_cast_equals_contract: [] vs [Rodther]`` and ``kf_wardrobe_line_present:Rodther``,
so the unit could never be registered.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools"))
from build_nalu_preproduction import bind_dialogue_cast
from prompt_batch_qa import keyframe_contract_cast


class OffscreenSpeakerKeyframeCastTests(unittest.TestCase):
    entities = {"C1": {"canonical_name": "Rodther", "aliases": []},
                "C2": {"canonical_name": "Mira", "aliases": []}}

    def test_empty_insert_with_offscreen_line_expects_no_visible_cast(self):
        _, cast = bind_dialogue_cast("Rodther: Insane.", [], self.entities, "en")
        self.assertEqual([c["character"] for c in cast], ["Rodther"])
        self.assertEqual(keyframe_contract_cast({"cast": cast}), [])

    def test_visible_cast_is_kept_next_to_an_offscreen_speaker(self):
        visible = [{"character": "Mira", "character_id": "C2", "face_visibility": "FRONT_CLEAR"}]
        _, cast = bind_dialogue_cast("Rodther: Insane.", visible, self.entities, "en")
        self.assertEqual(keyframe_contract_cast({"cast": cast}), ["Mira"])

    def test_hidden_at_entry_is_still_excluded_and_names_are_deduplicated(self):
        cast = [{"character": "Mira"}, {"character": "Mira"},
                {"character": "Rodther", "first_frame_visible": False}]
        self.assertEqual(keyframe_contract_cast({"cast": cast}), ["Mira"])

    def test_missing_cast_is_empty(self):
        self.assertEqual(keyframe_contract_cast({}), [])


if __name__ == "__main__":
    unittest.main()
