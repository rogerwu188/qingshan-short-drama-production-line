"""Static design gate: camera motion purposefulness (plan §2 supplement, R3 fix).

Before the optimisation plan, R3 fired on every no-dialogue locked shot — which
forced the writer to add a camera move even when a purposeful reaction or
breathing character was already sufficient.  R7 (seq=10) already catches a
no-dialogue locked shot >= 3 s with no body-level action verbs; R3 now fires only
when R7 would NOT apply (shot < 3 s) and there is still no body motion.

These tests prove:
  1. A locked no-dialogue shot WITH body-level action does NOT trigger R3 (but
     may still trigger R7 for a long hold without a moving camera).
  2. A locked no-dialogue shot with no body motion STILL triggers R3 (the gate
     still catches truly empty statics).
  3. A moving camera (PUSH_IN etc.) on a no-dialogue shot never triggers R3.
  4. The changed flag name (R3_LOCKED_NO_DIALOGUE_NO_BODY_MOTION) is used, not
     the old R3_NO_DIALOGUE_SHOT_WITHOUT_CAMERA_MOTION.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _p in (_ROOT / "lines" / "nalu" / "runtime" / "tools", _ROOT / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import unittest
import nalu_prompt_rules as npr

# Import the gate directly so we do not need the CLI or a real contract file.
from static_design_gate import evaluate, POLICY


def _shot(sid: str, motion: str = "LOCKED", dialogue: str = "", seconds: float = 4.0,
          action: str = "") -> dict:
    return {
        "shot_id": sid,
        "scene_id": "SC1",
        "target_seconds": seconds,
        "prompt_spec": {
            "camera_plan": {
                "motion_family": motion,
                "motion_direction": "STATIC",
                "shot_scale": "MEDIUM",
                "camera_height": "EYE_LEVEL",
                "camera_side": "LEFT",
                "lens_intent": "standard",
                "axis_relation": "same axis",
                "start_framing": "两人居中",
                "end_framing": "两人居中",
                "motivation": "保持构图稳定呈现细节",
            },
            "dialogue": dialogue or None,
            "action": {"primary_action": action},
        },
    }


def _eval(shots: list, *, episode: str = "E98") -> dict:
    """Evaluate with the narrow R3 in force for this episode.

    The narrow rule is gated by the same policy switch as the previs gate, so an
    episode already paid for keeps the original R3.  The tests list E98 in the
    policy rather than relying on the production default.
    """
    from unittest import mock
    contract = {"episode": episode, "shots": shots}
    with mock.patch("episode_previs.gate_active", lambda *_a, **_k: True):
        return evaluate(contract, POLICY)


def _eval_legacy(shots: list) -> dict:
    """An episode not listed in the policy keeps the original blanket R3."""
    from unittest import mock
    contract = {"episode": "E01", "shots": shots}
    with mock.patch("episode_previs.gate_active", lambda *_a, **_k: False):
        return evaluate(contract, POLICY)


class R3MotionPurposeTest(unittest.TestCase):

    def test_locked_no_dialogue_no_body_motion_still_flags_r3(self):
        """An empty static hold (no dialogue, no body verbs) must still be caught."""
        ev = _eval([_shot("S1", motion="LOCKED", dialogue="", action="等待")])
        codes = {f.split(":", 1)[-1] for f in ev["failures"]}
        self.assertIn("R3_LOCKED_NO_DIALOGUE_NO_BODY_MOTION", codes)

    def test_locked_no_dialogue_with_body_motion_does_not_trigger_r3(self):
        """A locked shot where the character is visibly performing is fine."""
        body_action = next(iter(npr.BODY_VERBS)) + "转身看向远方"
        ev = _eval([_shot("S1", motion="LOCKED", dialogue="", action=body_action)])
        codes = {f.split(":", 1)[-1] for f in ev["failures"]}
        self.assertNotIn("R3_LOCKED_NO_DIALOGUE_NO_BODY_MOTION", codes)
        self.assertNotIn("R3_NO_DIALOGUE_SHOT_WITHOUT_CAMERA_MOTION", codes)

    def test_moving_camera_no_dialogue_does_not_trigger_r3(self):
        """A camera move on a no-dialogue shot satisfies R3."""
        push_shot = _shot("S1", motion="PUSH_IN", dialogue="", action="静立")
        push_shot["prompt_spec"]["camera_plan"]["motion_direction"] = "FORWARD"
        push_shot["prompt_spec"]["camera_plan"]["end_framing"] = "人物面孔填满画幅"
        ev = _eval([push_shot])
        codes = {f.split(":", 1)[-1] for f in ev["failures"]}
        self.assertNotIn("R3_LOCKED_NO_DIALOGUE_NO_BODY_MOTION", codes)
        self.assertNotIn("R3_NO_DIALOGUE_SHOT_WITHOUT_CAMERA_MOTION", codes)

    def test_old_r3_flag_name_is_gone(self):
        """The old blanket flag name must not appear anywhere; only the new one may."""
        ev = _eval([_shot("S1", motion="LOCKED", dialogue="", action="等待")])
        for f in ev["failures"]:
            self.assertNotIn("R3_NO_DIALOGUE_SHOT_WITHOUT_CAMERA_MOTION", f,
                             "old R3 flag must not be emitted")

    def test_dialogue_shot_with_locked_camera_is_always_fine_for_r3(self):
        """A dialogue shot may use a locked camera; R3 does not apply."""
        ev = _eval([_shot("S1", motion="LOCKED", dialogue="秦铭：走吧。", action="")])
        codes = {f.split(":", 1)[-1] for f in ev["failures"]}
        self.assertNotIn("R3_LOCKED_NO_DIALOGUE_NO_BODY_MOTION", codes)

    def test_short_locked_no_body_shot_flags_r3_not_r7(self):
        """A < 3 s shot with no body motion: R3 fires; R7 (>= 3 s threshold) does not."""
        ev = _eval([_shot("S1", motion="LOCKED", dialogue="", action="等待", seconds=2.0)])
        codes = {f.split(":", 1)[-1] for f in ev["failures"]}
        self.assertIn("R3_LOCKED_NO_DIALOGUE_NO_BODY_MOTION", codes)
        self.assertNotIn("R7_NO_DIALOGUE_HOLD_WITHOUT_BODY_MOTION", codes)

    def test_an_episode_not_listed_keeps_the_original_r3(self):
        """No retroactive rework: an already-produced episode keeps the blanket rule."""
        ev = _eval_legacy([_shot("S1", motion="LOCKED", dialogue="", action="转身看向远方")])
        codes = {f.split(":", 1)[-1] for f in ev["failures"]}
        self.assertIn("R3_NO_DIALOGUE_SHOT_WITHOUT_CAMERA_MOTION", codes)


if __name__ == "__main__":
    unittest.main()
