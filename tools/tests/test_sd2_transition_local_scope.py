import unittest
from tools.sd2_provider_prompt_renderer import scoped_transition_text, _role_line
from tools.event_boundary_continuity_contract import provider_state_lock_text


class LocalTransitionTests(unittest.TestCase):
    def test_explicit_silent_visual_speech_not_all_mouths_closed(self):
        row = {'primary_actor': '甲', 'entity_names': {'A': '甲'}, 'silent_visual_speaker_id': 'A'}
        text = _role_line(row)
        self.assertNotIn('所有人物闭口', text)
        self.assertIn('不生成、不重复任何对白', text)
        with self.assertRaisesRegex(ValueError, 'BINDING_CONFLICT'):
            _role_line({**row, 'dialogue_speaker': '甲'})
        with self.assertRaisesRegex(ValueError, 'BINDING_CONFLICT'):
            _role_line({**row, 'silent_visual_speaker_id': 'B'})

    def test_neighbour_action_not_rendered(self):
        plan = {"unit_id": "U", "beats": [{"entry_state": "甲握笔", "exit_state": "甲放笔"}],
                "transition": {"incoming": "乙举碗→甲握笔", "outgoing": "甲放笔→丙拔刀"}}
        text = scoped_transition_text(plan)
        self.assertEqual(text, {"incoming": "甲握笔", "outgoing": "甲放笔"})
        self.assertIn("丙拔刀", plan["transition"]["outgoing"])

    def test_missing_endpoint_fails_before_provider(self):
        with self.assertRaisesRegex(ValueError, "LOCAL_ENDPOINT_MISSING"):
            scoped_transition_text({"beats": [], "transition": {"outgoing": "next"}})

    def test_no_transition_unchanged(self):
        self.assertEqual(scoped_transition_text({}), {})

    def test_per_entity_state_is_rendered_and_absent_listener_not_added(self):
        row = {'primary_actor': '甲', 'dialogue_speaker': '甲', 'dialogue_listener': '丙',
               'entity_names': {'A': '甲', 'B': '乙'}, 'entity_states': {'A': '俯身', 'B': '沉睡'}}
        text = _role_line(row)
        self.assertIn('乙的独立状态：沉睡', text)
        self.assertNotIn('丙闭口聆听', text)

    def test_empty_legacy_ledger_does_not_instruct_empty_frame(self):
        text = provider_state_lock_text({'persistent_state_contract': {'characters': []},
            'role_bindings': [{'entity_states': {'A': '沉睡'}}]}, language='ZH')
        self.assertNotIn('无人物', text)
        self.assertIn('逐镜角色', text)


if __name__ == "__main__":
    unittest.main()
