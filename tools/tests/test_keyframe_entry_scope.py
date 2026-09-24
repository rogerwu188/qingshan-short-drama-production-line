"""Entry-frame roles must not inherit another actor's video trajectory."""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lines/nalu/runtime/tools'))
from build_keyframe_manifest import normalize_keyframe_role_semantics, wardrobe_plate_excluded


class EntryScope(unittest.TestCase):
    def run_role(self, role, visible):
        return normalize_keyframe_role_semantics(role, shot_id='S1',
            entry_state='A reaches toward B', visible_contract_ids=visible)

    def test_independent_entry_states_and_immutable_source(self):
        role = {'entity_states': {'A': 'A acts later', 'B': 'B wakes later'},
                'entity_entry_states': {'A': 'A holds coins', 'B': 'B sleeps'}}
        before = copy.deepcopy(role)
        result = self.run_role(role, ['A', 'B'])
        self.assertEqual(result['entity_states'], role['entity_entry_states'])
        self.assertEqual(role, before)

    def test_missing_multi_actor_entry_blocks(self):
        with self.assertRaisesRegex(ValueError, 'ENTITY_ENTRY_STATE_REQUIRED'):
            self.run_role({'entity_states': {'A': 'acts', 'B': 'sleeps'}}, ['A', 'B'])

    def test_offscreen_does_not_copy_visible_action(self):
        result = self.run_role({'entity_states': {'A': 'acts', 'B': 'speaks'},
                               'entity_presence': {'B': 'OFFSCREEN_VOICE_ONLY'}}, ['A'])
        self.assertEqual(result['entity_states']['A'], 'A reaches toward B')
        self.assertNotEqual(result['entity_states']['B'], result['entity_states']['A'])
        self.assertEqual(result['entity_presence']['B'], 'OFFSCREEN_VOICE_ONLY')

    def test_visible_cast_omission_still_blocks(self):
        with self.assertRaisesRegex(ValueError, 'ENTITY_ENTRY_STATE_REQUIRED:B'):
            self.run_role({'entity_entry_states': {'A': 'holding coins'}}, ['A', 'B'])

    def test_empty_legacy_role_is_unchanged(self):
        self.assertEqual(self.run_role({}, []), {})

    def test_wardrobe_exclusion_requires_record_and_authored_costume(self):
        self.assertFalse(wardrobe_plate_excluded({}, 'A'))
        spec = {'wardrobe_reference_exclusions': {'A': {'reason': 'wrong color', 'evidence_ref': 'review.json'}}}
        with self.assertRaisesRegex(ValueError, 'AUTHORED_STATE_REQUIRED'):
            wardrobe_plate_excluded(spec, 'A')
        spec['wardrobe_state_overrides'] = {'A': 'purple round collar'}
        self.assertTrue(wardrobe_plate_excluded(spec, 'A'))
        del spec['wardrobe_reference_exclusions']['A']['evidence_ref']
        with self.assertRaisesRegex(ValueError, 'EVIDENCE_REQUIRED'):
            wardrobe_plate_excluded(spec, 'A')

if __name__ == '__main__':
    unittest.main()
