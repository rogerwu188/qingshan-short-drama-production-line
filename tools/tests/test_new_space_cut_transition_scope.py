import unittest

from tools.video_execution_plan_compiler import _compact_transition


def _contract(space_relation: str, cut_reason: str) -> dict:
    return {
        "cut_reason": cut_reason,
        "space_relation": space_relation,
        "action_bridge": "「宝玉在厂门外驻足」→「万司事转身指向枪架」；动作因果不断裂，不复位不重演",
        "visual_bridge": "上一段停在门外，下一段从枪架承接",
        "source_terminal_state": {"blocking": "宝玉在厂门外驻足"},
        "target_initial_state": {"blocking": "万司事转身指向枪架"},
    }


class NewSpaceCutTransitionScopeTests(unittest.TestCase):
    def test_new_space_cut_keeps_only_each_units_own_state(self):
        boundary = _contract("SAME_LOCATION_NEW_SUBSPACE", "NEW_SPACE_MATCH_CUT")
        previous = _compact_transition({"outgoing_transition_contract": boundary})
        current = _compact_transition({"incoming_transition_contract": boundary})
        self.assertEqual(previous["outgoing"], "宝玉在厂门外驻足")
        self.assertNotIn("万司事", previous["outgoing"])
        self.assertEqual(current["incoming"], "万司事转身指向枪架")
        self.assertNotIn("宝玉", current["incoming"])

    def test_sound_bridge_into_new_location_is_also_scoped(self):
        boundary = _contract("NEW_LOCATION_SAME_GLOBAL", "SOUND_BRIDGE_NEW_SPACE")
        self.assertNotIn("万司事", _compact_transition({"outgoing_transition_contract": boundary})["outgoing"])

    def test_same_subspace_continuation_keeps_the_handoff(self):
        boundary = _contract("SAME_SUBSPACE", "CONTINUOUS_ACTION")
        compact = _compact_transition({"outgoing_transition_contract": boundary,
                                       "incoming_transition_contract": boundary})
        self.assertIn("→", compact["outgoing"])
        self.assertIn("→", compact["incoming"])


if __name__ == "__main__":
    unittest.main()
