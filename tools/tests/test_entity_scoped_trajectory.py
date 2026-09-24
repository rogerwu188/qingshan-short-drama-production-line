import sys
import unittest
import tempfile
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools"))
from build_nalu_preproduction import entity_scoped_trajectory, bind_dialogue_cast, locked_artifact_headshot, scoped_interaction, migrate_shot_camera_state, bind_entry_supports


class EntrySupportTests(unittest.TestCase):
    def test_declared_support_follows_owner_not_independent_slot(self):
        chars = [{'character_id':'A','position':[1,2],'zone_id':'Z'}]
        props = [{'prop_id':'CHAIR','position':[9,8],'zone_id':'Z'}]
        result = bind_entry_supports(chars, props, {'CHAIR':'A'})
        self.assertEqual(result[0]['position'], [1,2])
        self.assertEqual(props[0]['position'], [9,8])
        self.assertEqual(bind_entry_supports(chars, props, {}), props)

    def test_missing_owner_cannot_be_invented(self):
        with self.assertRaisesRegex(ValueError, 'ENTRY_SUPPORT_BINDING_UNRESOLVED'):
            bind_entry_supports([], [{'prop_id':'CHAIR'}], {'CHAIR':'A'})


class ExplicitNoContact(unittest.TestCase):
    def test_legacy_camera_does_not_override_current_plan(self):
        old = {'camera_state': {'motion_family': 'LOCKED', 'axis_id': 'old'}}
        shot = {'angle_id': 'current_camera', 'prompt_spec': {'camera_plan': {'motion_family': 'ARC'},
                                'space': {'axis_id': 'new', 'angle_id': 'camera2'}}}
        result = migrate_shot_camera_state(old, shot)
        self.assertEqual(result['camera_state']['motion_family'], 'ARC')
        self.assertEqual(result['camera_state']['axis_id'], 'new')
        self.assertEqual(result['camera_state']['camera_position_id'], 'current_camera')
        self.assertEqual(old['camera_state']['motion_family'], 'LOCKED')

    def test_observation_target_does_not_imply_contact(self):
        self.assertEqual(scoped_interaction({'interaction_mode': 'NONE'}, '观察者', '睡者', '观察呼吸'),
                         {'contact_point': '', 'interaction_mode': 'NONE'})


class SoloInteractionTests(unittest.TestCase):
    def test_speech_without_patient_is_not_contact(self):
        self.assertEqual(scoped_interaction({}, '演员', '', '睁眼念诗'),
                         {'contact_point': '', 'interaction_mode': 'NONE'})

    def test_authored_object_contact_is_preserved(self):
        self.assertEqual(scoped_interaction({'contact_point': '手指碰杯沿'}, '演员', '', '伸手'),
                         {'contact_point': '手指碰杯沿'})

    def test_explicit_non_contact_is_preserved(self):
        self.assertEqual(scoped_interaction({'interaction_mode': 'EVASION', 'contact_point': '刀刃掠过'},
                                          '甲', '乙', '侧身')['interaction_mode'], 'EVASION')


class ArtifactHeadshotTests(unittest.TestCase):
    def test_locked_current_schema_resolves_sha_bound_headshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'ACTOR__FRONT_NEUTRAL_HEADSHOT.png'
            p.write_bytes(b'test reference')
            row = {'status': 'LOCKED', 'qa': {'status': 'PASS'}, 'artifacts': [
                {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}]}
            self.assertEqual(locked_artifact_headshot(row), p)
            p.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'SHA_MISMATCH'):
                locked_artifact_headshot(row)

    def test_unapproved_artifact_not_reused(self):
        self.assertIsNone(locked_artifact_headshot({'status': 'REQUIRED_UNCREATED'}))


class DialogueBindingTests(unittest.TestCase):
    def setUp(self):
        self.entities = {"A": {"canonical_name": "人物甲", "aliases": ["别名甲"]},
                         "B": {"canonical_name": "人物乙", "aliases": []}}

    def test_alias_does_not_add_offscreen_duplicate(self):
        text, cast = bind_dialogue_cast("别名甲：你好！", [{"character_id": "A"}], self.entities)
        self.assertEqual(text, "人物甲：你好！")
        self.assertEqual(len(cast), 1)

    def test_multiple_speakers_resolve_individually(self):
        _, cast = bind_dialogue_cast("别名甲：甲。\n人物乙：乙。", [], self.entities)
        self.assertEqual([c["character_id"] for c in cast], ["A", "B"])

    def test_unknown_speaker_not_silently_assigned(self):
        with self.assertRaisesRegex(ValueError, "UNREGISTERED"):
            bind_dialogue_cast("未知：你好", [], self.entities)

    def test_conflicting_alias_blocked(self):
        self.entities["B"]["aliases"] = ["别名甲"]
        with self.assertRaisesRegex(ValueError, "COLLISION"):
            bind_dialogue_cast("别名甲：你好", [], self.entities)

    def test_no_dialogue_valid(self):
        self.assertEqual(bind_dialogue_cast("", [], self.entities), ("", []))


class EntityTrajectoryTests(unittest.TestCase):
    def setUp(self):
        self.specs = [
            {"cast": [{"character_id": "A"}], "props": [{"prop_id": "COIN"}],
             "action": {"start_state": "A holds coin", "completion_state": "A opens hand"}},
            {"cast": [{"character_id": "B"}],
             "action": {"start_state": "B holds pen", "completion_state": "B writes"}},
        ]

    def test_no_cross_character_end_state(self):
        a = entity_scoped_trajectory("A", self.specs, ["S1", "S2"], {}, {})
        b = entity_scoped_trajectory("B", self.specs, ["S1", "S2"], {}, {})
        self.assertEqual(a["to"], "A opens hand")
        self.assertEqual(b["from"], "B holds pen")
        self.assertEqual(a["source_shot_ids"], ["S1"])
        self.assertNotIn("pen", a["action"])

    def test_prop_not_assigned_other_character_action(self):
        r = entity_scoped_trajectory("COIN", self.specs, ["S1", "S2"], {}, {})
        self.assertNotIn("writes", str(r))

    def test_missing_entity_does_not_invent_states(self):
        with self.assertRaisesRegex(ValueError, "ENTITY_TRAJECTORY_SOURCE_MISSING"):
            entity_scoped_trajectory("UNKNOWN", self.specs, ["S1", "S2"], {}, {})

    def test_alias_resolved_from_registered_map(self):
        specs = [{"cast": [{"character": "alias"}], "action": {"start_state": "ready"}}]
        r = entity_scoped_trajectory("A", specs, ["S1"], {"alias": "A"}, {})
        self.assertEqual(r["from"], "ready")


if __name__ == "__main__":
    unittest.main()
