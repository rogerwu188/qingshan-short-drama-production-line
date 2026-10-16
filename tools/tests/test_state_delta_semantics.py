"""STATE_DELTA_SEMANTICS_V1: a string change must not stand in for a physical change.

Plan §5 / §10 items 1, 2, 3 and 15.  All tests are free and offline.  The defect
chain they pin down: an adapter defaulted the state dimension to POSTURE and
copied the frame description in as the exit state; the description was a line
of dialogue; the motion gate compared two strings, found them different, and
accepted speech as a body change.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import tools.sd2_motion_density_gate as gate
from tools.sd2_motion_density_gate import (
    STATIC_POSTURE_PERFORMANCE,
    evidence_is_dialogue,
    state_delta_semantics_active,
    validate_state_delta,
)

LINE = "许叔，他们一而再地行恶事"


def _beat(**overrides):
    beat = {
        "entry_state": "他站在街上，双手垂着",
        "exit_state": "他攥紧了拳",
        "state_delta_dimensions": ["POSTURE"],
        "state_delta_evidence": {
            "POSTURE": {"entry": "双手垂着", "exit": "攥紧了拳",
                        "entry_code": "HANDS_DOWN", "exit_code": "FIST_CLENCHED"},
        },
        "dialogue": "",
        "microexpression_cue": "",
        "state_delta_semantics": "V1",
    }
    beat.update(overrides)
    return beat


class DialogueIsNotAPhysicalStateTest(unittest.TestCase):
    """§10.1: dialogue copied into state evidence yields no valid physical change."""

    def test_dialogue_in_exit_state_fails_even_though_strings_differ(self):
        beat = _beat(
            dialogue=f"秦铭：{LINE}",
            state_delta_evidence={"POSTURE": {
                "entry": "站在主街上", "exit": LINE,
                "entry_code": "STANDING", "exit_code": "SPEAKING"}},
        )
        report = validate_state_delta(beat, combat=False, source_id="E99-VU-001:BEAT_1")
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("STATE_DELTA_EVIDENCE_IS_DIALOGUE:E99-VU-001:BEAT_1:POSTURE:exit",
                      report["failures"])

    def test_dialogue_as_beat_endpoint_fails(self):
        beat = _beat(dialogue=LINE, exit_state=LINE)
        report = validate_state_delta(beat, combat=False, source_id="E99-VU-001:BEAT_1")
        self.assertIn("STATE_ENDPOINT_IS_DIALOGUE:E99-VU-001:BEAT_1:exit_state", report["failures"])

    def test_a_short_shared_word_is_not_copying(self):
        self.assertFalse(evidence_is_dialogue("攥拳", "他攥拳说话"))
        self.assertTrue(evidence_is_dialogue(LINE + "。", f"秦铭：{LINE}"))


class LegitimateStaticPostureTest(unittest.TestCase):
    """§10.2: a real dialogue shot may keep its posture without inventing movement."""

    def test_static_posture_dialogue_shot_passes_without_a_state_dimension(self):
        beat = _beat(
            dialogue=LINE, state_delta_mode=STATIC_POSTURE_PERFORMANCE,
            state_delta_dimensions=[], state_delta_evidence={},
            entry_state="他低头站着", exit_state="他低头站着",
            microexpression_cue="眼神先垂下再抬起一次，下颌随台词收紧",
        )
        report = validate_state_delta(beat, combat=False, source_id="E99-VU-002:BEAT_1")
        self.assertEqual(report["status"], "PASS", report["failures"])

    def test_static_posture_without_any_performance_is_a_frozen_frame(self):
        beat = _beat(
            dialogue=LINE, state_delta_mode=STATIC_POSTURE_PERFORMANCE,
            state_delta_dimensions=[], state_delta_evidence={},
            entry_state="他低头站着", exit_state="他低头站着",
        )
        report = validate_state_delta(beat, combat=False, source_id="E99-VU-002:BEAT_1")
        self.assertIn("STATIC_POSTURE_PERFORMANCE_EVIDENCE_MISSING:E99-VU-002:BEAT_1",
                      report["failures"])

    def test_static_posture_requires_dialogue(self):
        beat = _beat(
            state_delta_mode=STATIC_POSTURE_PERFORMANCE, state_delta_dimensions=[],
            state_delta_evidence={}, microexpression_cue="呼吸起伏",
        )
        report = validate_state_delta(beat, combat=False, source_id="E99-VU-003:BEAT_1")
        self.assertIn("STATIC_POSTURE_REQUIRES_DIALOGUE:E99-VU-003:BEAT_1", report["failures"])

    def test_without_the_declaration_an_unchanged_shot_still_fails(self):
        # Silence is not a declaration: no mode, no dimension -> still a failure.
        beat = _beat(dialogue=LINE, state_delta_dimensions=[], state_delta_evidence={})
        report = validate_state_delta(beat, combat=False, source_id="E99-VU-004:BEAT_1")
        self.assertIn("STATE_DELTA_DIMENSION_COUNT:E99-VU-004:BEAT_1:0<1", report["failures"])


class CombatKeepsItsRequirementsTest(unittest.TestCase):
    """§10.3: a fight without a physical result still fails."""

    def test_static_posture_is_refused_for_combat(self):
        beat = _beat(
            dialogue=LINE, state_delta_mode=STATIC_POSTURE_PERFORMANCE,
            state_delta_dimensions=[], state_delta_evidence={},
            microexpression_cue="怒视",
        )
        report = validate_state_delta(beat, combat=True, source_id="E99-VU-005:BEAT_1")
        self.assertIn("STATIC_POSTURE_FORBIDDEN_FOR_COMBAT:E99-VU-005:BEAT_1", report["failures"])
        self.assertIn("STATE_DELTA_DIMENSION_COUNT:E99-VU-005:BEAT_1:0<2", report["failures"])

    def test_combat_with_one_dimension_still_fails(self):
        report = validate_state_delta(_beat(), combat=True, source_id="E99-VU-006:BEAT_1")
        self.assertIn("STATE_DELTA_DIMENSION_COUNT:E99-VU-006:BEAT_1:1<2", report["failures"])

    def test_a_valid_physical_change_still_passes(self):
        report = validate_state_delta(_beat(), combat=False, source_id="E99-VU-007:BEAT_1")
        self.assertEqual(report["status"], "PASS", report["failures"])


class InactiveEpisodesKeepLockedBehaviourTest(unittest.TestCase):
    """§10.15: an episode that has not opted in sees no change at all."""

    def test_policy_is_off_by_default(self):
        self.assertFalse(state_delta_semantics_active("E12-VU-001:BEAT_1"))

    def test_without_opt_in_the_legacy_rule_runs(self):
        # The exact defect the new rule catches is accepted by the legacy rule,
        # which is the point: in-production episodes are not re-judged.
        beat = _beat(
            dialogue=LINE, state_delta_semantics="",
            state_delta_evidence={"POSTURE": {"entry": "站着", "exit": LINE,
                                              "entry_code": "A", "exit_code": "B"}},
        )
        report = validate_state_delta(beat, combat=False, source_id="E12-VU-001:BEAT_1")
        self.assertEqual(report["status"], "PASS")
        self.assertNotIn("semantics", report)

    def test_listing_an_episode_turns_it_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "policy.json"
            policy.write_text(json.dumps({"enabled_episodes": ["E99"]}), encoding="utf-8")
            with mock.patch.object(gate, "_SEMANTICS_POLICY", policy):
                self.assertTrue(state_delta_semantics_active("E99-VU-001:BEAT_1"))
                self.assertFalse(state_delta_semantics_active("E98-VU-001:BEAT_1"))

    def test_enabled_from_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            policy = Path(tmp) / "policy.json"
            policy.write_text(json.dumps({"enabled_from_episode": "E20"}), encoding="utf-8")
            with mock.patch.object(gate, "_SEMANTICS_POLICY", policy):
                self.assertTrue(state_delta_semantics_active("E21-VU-001"))
                self.assertFalse(state_delta_semantics_active("E19-VU-001"))


class ActionKindVocabularyTest(unittest.TestCase):
    """A declared fight must reach the plan compiler as COMBAT."""

    def test_combat_spellings_normalise_and_undeclared_stays_non_combat(self):
        import importlib.util, sys
        path = Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools/build_nalu_preproduction.py"
        tools_dir = str(path.parent)
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        spec = importlib.util.spec_from_file_location("bnp_under_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for value in ("COMBAT", "ACTION_COMBAT", "fight", "COMBAT_IMPULSE"):
            self.assertEqual(module.normalize_action_kind(value), "COMBAT", value)
        for value in (None, "", "DRAMA", "NON_COMBAT"):
            self.assertEqual(module.normalize_action_kind(value), "NON_COMBAT", value)


if __name__ == "__main__":
    unittest.main()
