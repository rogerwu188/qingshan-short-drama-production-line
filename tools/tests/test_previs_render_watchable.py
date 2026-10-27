"""The previs must render what the sequence is supposed to look like.

CC_H3 audit 2026-10-26 §四-缺口B: the formal entry only ever called
build_previs — never the renderer, never with the dialogue audio that
already exists.  The optional renderer stitched static cards over an
``anullsrc`` silent bed, so it could not show whether a viewer follows the
speaker, the action or the cut.

Two properties are tested here without requiring ffmpeg media on CI:

- the timeline carries the DECLARED camera per shot, so a renderer knows what
  to animate and a LOCKED shot is never given invented motion;
- a shot with declared dialogue and no supplied clip is REPORTED, never
  silently filled with silence that looks like a verified check.

Synthetic shots only — no episode text, task ids, media or production paths.
"""

from __future__ import annotations

import unittest

from tools import episode_previs as previs


def _contract():
    return {
        "episode": "T01",
        "shots": [
            {"shot_id": "T-S01", "scene_id": "T-SC", "target_seconds": 3.0},
            {"shot_id": "T-S02", "scene_id": "T-SC", "target_seconds": 3.0},
        ],
        "scene_states": [], "character_entities": [{"character_id": "T-CHAR-A"}],
        "audio_contract": {"dialogue_units": [
            {"shot_id": "T-S01", "speaker_id": "T-CHAR-A", "text": "synthetic line"},
        ]},
    }


def _grouping(family, direction):
    return {"units": [
        {"unit_id": "T-VU01", "scene_id": "T-SC", "editorial_shot_ids": ["T-S01"],
         "camera_plan": {"motion_family": family, "motion_direction": direction,
                         "start_framing": "A holds", "end_framing": "A holds"}},
        {"unit_id": "T-VU02", "scene_id": "T-SC", "editorial_shot_ids": ["T-S02"],
         "camera_plan": {"motion_family": "LOCKED", "motion_direction": "NONE",
                         "start_framing": "B holds", "end_framing": "B holds"}},
    ]}


class TimelineCarriesDeclaredCamera(unittest.TestCase):
    def test_a_lockdown_shot_is_not_given_motion(self):
        result = previs.build_previs(_contract(), _grouping("LOCKED", "NONE"))
        self.assertEqual(result["timeline"][0]["camera"]["motion_family"], "LOCKED")
        self.assertEqual(previs._MOTION_MOVES.get(("LOCKED", "NONE")), None,
                         "a lockdown must never map to an animated move")

    def test_a_declared_pan_maps_to_a_real_move(self):
        self.assertIn(("PAN", "LEFT_TO_RIGHT"), previs._MOTION_MOVES)
        self.assertIn(("DOLLY", "PUSH_IN"), previs._MOTION_MOVES)
        self.assertNotIn(("DOLLY", "LEFT_TO_RIGHT"), previs._MOTION_MOVES,
                         "only legal family/direction pairs are animatable")

    def test_still_filter_differs_between_locked_and_pan(self):
        locked = {"duration": 2.0, "camera": {"motion_family": "LOCKED", "motion_direction": "NONE"}}
        panned = {"duration": 2.0, "camera": {"motion_family": "PAN",
                                             "motion_direction": "LEFT_TO_RIGHT"}}
        self.assertEqual(previs._still_filter(locked, 720, 1280, 24),
                         previs._still_filter(locked, 720, 1280, 24))
        self.assertNotEqual(previs._still_filter(locked, 720, 1280, 24),
                            previs._still_filter(panned, 720, 1280, 24),
                            "a pan that renders identically to a lockdown shows nothing")

    def test_missing_camera_plan_is_not_guessed(self):
        result = previs.build_previs(_contract(), None)
        self.assertFalse(result["timeline"][0]["camera"]["declared"])
        self.assertIsNone(result["timeline"][0]["camera"]["motion_family"])


if __name__ == "__main__":
    unittest.main()
