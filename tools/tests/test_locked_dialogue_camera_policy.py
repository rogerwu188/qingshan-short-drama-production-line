"""LOCKED_DIALOGUE_CAMERA_V1 (Roger 2026-10-30, E12 成片审看 item 2; SUPERVISOR_ORDERS seq=57 「1. 重投」).

Dialogue units default to a locked camera; a move must be authored; a move never reverses inside a unit;
every beat of a dialogue unit without a dialogue literal says that nobody speaks (K138).
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))
sys.path.insert(0, str(ROOT / "tools"))

from tools import locked_dialogue_camera_policy as policy  # noqa: E402
import camera_move_lint as lint  # noqa: E402


class PolicyActivationTests(unittest.TestCase):
    def test_never_retroactive_and_contract_field_wins(self):
        listed = json.loads((ROOT / "configs/LOCKED_DIALOGUE_CAMERA_V1.json").read_text("utf-8"))["enabled_episodes"]
        self.assertIn("E12", listed)
        self.assertTrue(policy.active({"episode": "E12"}))
        self.assertFalse(policy.active({"episode": "E11"}))
        self.assertTrue(policy.active({"episode": "E13", "locked_dialogue_camera_policy": "LOCKED_DIALOGUE_CAMERA_V1"}))
        self.assertFalse(policy.active({"episode": "E12", "locked_dialogue_camera_policy": "LEGACY_FORCED_MOTION"}))
        self.assertTrue(policy.plan_under_policy({"camera_policy": "LOCKED_DIALOGUE_CAMERA_V1"}))
        self.assertFalse(policy.plan_under_policy({}))


class LintTests(unittest.TestCase):
    def test_authored_move_and_locked_prompt(self):
        self.assertTrue(lint.authored_move("特写推近把话说出口的秦铭"))
        self.assertFalse(lint.authored_move("特写固定机位把话说出口的秦铭"))
        r = lint.dialogue_unit_locked_camera("camera: shot scale=CLOSE_UP; Fixed camera position: no push in, no pull out, "
                                             "no pan, no tilt, no tracking. The camera is on a tripod for the whole take.",
                                             has_dialogue=True, authored_camera_text="特写固定机位把话说出口的秦铭")
        self.assertEqual(r["status"], "PASS")
        r = lint.dialogue_unit_locked_camera("camera: one short dolly move; direction=PUSH_IN", has_dialogue=True,
                                             authored_camera_text="特写固定机位秦铭")
        self.assertEqual(r["status"], "FAIL")
        # the negative-constraints line names moves to forbid; it is not a move request
        r = lint.dialogue_unit_locked_camera("camera: shot scale=CLOSE_UP; Fixed camera position: no pan.\n"
                                             "negative_constraints: No freeze, loop, pose interpolation, unmotivated orbit, or jump.",
                                             has_dialogue=True, authored_camera_text="特写固定机位秦铭")
        self.assertEqual(r["status"], "PASS", r)

    def test_single_direction_and_silent_beats(self):
        self.assertEqual(lint.single_direction([{"motion_family": "DOLLY", "motion_direction": "PUSH_IN"},
                                                {"motion_family": "DOLLY", "motion_direction": "PULL_OUT"}])["status"], "FAIL")
        self.assertEqual(lint.single_direction([{"motion_family": "LOCKED", "motion_direction": "NONE"},
                                                {"motion_family": "LOCKED", "motion_direction": "NONE"}])["status"], "PASS")
        ok = "[0s-2s] Start from a. No speech in this beat: X keeps the mouth closed. End at b.\n[2s-5s] X says <d>[Chinese] 你好</d>."
        bad = "[0s-2s] Start from a. End at b.\n[2s-5s] X says <d>[Chinese] 你好</d>."
        self.assertEqual(lint.silent_beats_declared(ok, has_dialogue=True)["status"], "PASS")
        self.assertEqual(lint.silent_beats_declared(bad, has_dialogue=True)["status"], "FAIL")
        self.assertEqual(lint.silent_beats_declared(bad, has_dialogue=False)["status"], "PASS")


class RendererTests(unittest.TestCase):
    def test_locked_plan_renders_a_tripod_and_a_moving_plan_one_direction(self):
        from tools import h3_provider_prompt_renderer as r
        legacy = r._camera({"motion_family": "LOCKED", "motion_direction": "NONE", "shot_scale": "CLOSE_UP"})
        self.assertIn("execute the declared move once", legacy)          # byte-identical outside the policy
        locked = r._camera({"motion_family": "LOCKED", "motion_direction": "NONE", "shot_scale": "CLOSE_UP",
                            "camera_policy": "LOCKED_DIALOGUE_CAMERA_V1"})
        self.assertIn("Fixed camera position", locked)
        self.assertIn("tripod", locked)
        self.assertNotIn("execute the declared move", locked)
        moving = r._camera({"motion_family": "DOLLY", "motion_direction": "PUSH_IN", "shot_scale": "MEDIUM",
                            "camera_policy": "LOCKED_DIALOGUE_CAMERA_V1"})
        self.assertIn("in one direction only", moving)
        self.assertIn("never reverses", moving)

    def test_beat_without_dialogue_in_a_dialogue_unit_declares_no_speech_and_short_lines_breathe(self):
        from tools import h3_provider_prompt_renderer as r
        source = {"source_index": 1, "start_seconds": 0, "end_seconds": 2, "dialogue": ""}
        translated = {"entry_state": "A", "primary_action": "B", "exit_state": "C"}
        line, ev = r._beat(source, translated, dialogue_binding=None, locked_dialogue_policy=True,
                           unit_has_dialogue=True, speaker_label="Qinming")
        self.assertIn("No speech in this beat: Qinming keeps the mouth closed", line)
        self.assertIn("BEAT.1.NO_SPEECH", ev)
        line, ev = r._beat(source, translated, dialogue_binding=None, locked_dialogue_policy=False, unit_has_dialogue=True)
        self.assertNotIn("No speech in this beat", line)
        binding = {"provider_entity_label": "Qinming", "subject_token": "SUBJECT_1", "image_slot": "@Image1",
                   "speaker_slot": "SPEAKER_1", "audio_slot": "@Audio1", "visible_speaker": True}
        short = {"source_index": 2, "start_seconds": 2, "end_seconds": 4, "dialogue": "秦铭：许叔！"}
        line, ev = r._beat(short, translated, dialogue_binding=binding, locked_dialogue_policy=True, unit_has_dialogue=True)
        self.assertIn("at least one full second", line)
        self.assertIn("BEAT.2.SHORT_LINE_DELIVERY", ev)


class GateTests(unittest.TestCase):
    def _contract(self, shots, episode="E12"):
        return {"episode": episode, "locked_dialogue_camera_policy": "LOCKED_DIALOGUE_CAMERA_V1", "shots": shots,
                "character_entities": []}

    def _shot(self, sid, scene, fam, direction, dialogue, camera, secs=4.0):
        return {"shot_id": sid, "scene_id": scene, "target_seconds": secs, "camera": camera,
                "prompt_spec": {"camera_plan": {"motion_family": fam, "motion_direction": direction, "camera_side": "AXIS_A",
                                                "shot_scale": "CLOSE_UP", "lens_intent": camera},
                                "dialogue": dialogue, "action": {"primary_action": "说话"}}}

    def test_locked_dialogue_is_advisory_and_r9_r10_block(self):
        import static_design_gate as g
        shots = [self._shot("S1-01", "S1", "LOCKED", "NONE", "甲：你好", "特写固定机位甲"),
                 self._shot("S1-02", "S1", "LOCKED", "NONE", "乙：你好", "特写固定机位乙"),
                 self._shot("S1-03", "S1", "DOLLY", "PUSH_IN", "甲：再见", "特写固定机位甲"),      # moving, unauthored
                 self._shot("S1-04", "S1", "DOLLY", "PULL_OUT", "", "特写拉开乙")]               # reversal in scene
        ev = g.evaluate(self._contract(shots), dict(g.POLICY))
        failures = " ".join(ev["failures"])
        self.assertIn("R9_DIALOGUE_SHOT_MOVING_CAMERA_UNAUTHORED", failures)
        self.assertIn("R10_CAMERA_DIRECTION_REVERSAL_IN_SCENE", failures)
        self.assertNotIn("R2_", failures)                     # consecutive locked only advises under the policy
        self.assertNotIn("R1_LOCKED_SHARE", failures)
        self.assertEqual(ev["locked_dialogue_camera_policy"], "LOCKED_DIALOGUE_CAMERA_V1")

    def test_outside_the_policy_nothing_changes(self):
        import static_design_gate as g
        shots = [self._shot("S1-01", "S1", "LOCKED", "NONE", "甲：你好", "特写固定机位甲"),
                 self._shot("S1-02", "S1", "LOCKED", "NONE", "乙：你好", "特写固定机位乙")]
        contract = self._contract(shots, episode="E05")
        contract.pop("locked_dialogue_camera_policy")
        ev = g.evaluate(contract, dict(g.POLICY))
        self.assertTrue(any("R2_" in f for f in ev["failures"]))
        self.assertNotIn("locked_dialogue_camera_policy", ev)


class AdapterTests(unittest.TestCase):
    def test_dialogue_shot_defaults_locked_under_policy_and_direction_never_alternates(self):
        import adapt_v4_layers_to_runtime as ad
        locked = ad.default_camera_plan(1, True, "特写看着对方的甲", "", "DOLLY", "PUSH_IN", 4.0, "ref", locked_policy=True)
        self.assertEqual((locked["motion_family"], locked["motion_direction"]), ("LOCKED", "NONE"))
        authored = ad.default_camera_plan(1, True, "特写推近看着对方的甲", "", None, None, 4.0, "ref", locked_policy=True)
        self.assertNotEqual(authored["motion_family"], "LOCKED")
        a = ad.default_camera_plan(0, False, "x", "", None, None, 3.0, "ref", locked_policy=True)
        b = ad.default_camera_plan(1, False, "x", "", a["motion_family"], a["motion_direction"], 3.0, "ref", locked_policy=True)
        self.assertEqual(b["motion_direction"], ad.DIRECTION[b["motion_family"]][0])
        legacy = ad.default_camera_plan(1, True, "特写看着对方的甲", "", None, None, 4.0, "ref", locked_policy=False)
        self.assertIn(legacy["motion_family"], ad.DIALOGUE_FAMILIES)


if __name__ == "__main__":
    unittest.main()
