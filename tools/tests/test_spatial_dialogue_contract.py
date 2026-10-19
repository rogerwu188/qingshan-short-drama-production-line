"""Spatial staging: who speaks to whom is not who they look at.

These tests pin the separation the production line kept collapsing: a character
can address someone while looking down at a letter, and the listener can stay
entirely offscreen.  Absence must render nothing and invent nothing.
"""

from __future__ import annotations

import unittest

from tools import spatial_dialogue_contract as sdc
from tools.role_semantic_prompt_gate import SCHEMA, validate_role_semantics
from tools.sd2_provider_prompt_renderer import _role_line


def row(**overrides):
    base = {
        "schema": SCHEMA,
        "status": "PASS",
        "shot_id": "E99-S01-01",
        "primary_actor": "陈迹",
        "primary_actor_kind": "CHARACTER",
        "dialogue_speaker": "陈迹",
        "dialogue_listener": "王龙",
        "dialogue_mode": "ADDRESSED_SPEECH",
        "action_patient": "",
        "entity_states": {"陈迹": "一字一句报出暗号", "王龙": "站在旁边闭口"},
        "entity_presence": {
            "陈迹": "VISIBLE_AND_IDENTITY_LOCKED",
            "王龙": "VISIBLE_AND_IDENTITY_LOCKED",
        },
        "forbidden_role_swaps": True,
        "unresolved": [],
    }
    base.update(overrides)
    return base


class SpatialValidationTests(unittest.TestCase):
    def test_fields_absent_is_legal_and_renders_nothing(self):
        value = row()
        self.assertEqual(sdc.validate(value), [])
        self.assertEqual(sdc.render_zh(value), "")
        self.assertNotIn("视线", _role_line(value))

    def test_speaking_to_someone_while_looking_at_an_object_is_legal(self):
        value = row(
            speaker_facing_direction="身体转向王龙",
            speaker_gaze_target="落在手中的药方",
            entity_states={"陈迹": "低头看药方说话", "王龙": "站在旁边闭口", "药方": "被展开"},
            entity_presence={
                "陈迹": "VISIBLE_AND_IDENTITY_LOCKED",
                "王龙": "VISIBLE_AND_IDENTITY_LOCKED",
                "药方": "VISIBLE_AND_IDENTITY_LOCKED",
            },
        )
        self.assertEqual(sdc.validate(value), [])
        clause = sdc.render_zh(value)
        self.assertIn("陈迹身体转向王龙", clause)
        self.assertIn("陈迹的视线落在手中的药方", clause)
        self.assertNotIn("王龙的视线", clause)

    def test_no_spatial_declaration_at_all_is_legal_even_with_an_offscreen_listener(self):
        # Absence must never break an in-production contract: E66 VU030 declares
        # an offscreen listener with no staging fields at all.
        value = row(
            entity_states={"陈迹": "报出暗号"},
            entity_presence={"陈迹": "VISIBLE_AND_IDENTITY_LOCKED", "王龙": "ABSENT_REFERENCE_ONLY"},
        )
        self.assertEqual(sdc.validate(value), [])
        self.assertEqual(sdc.render_zh(value), "")

    def test_declared_staging_with_an_offscreen_listener_requires_a_visual_cue(self):
        without = row(
            speaker_facing_direction="身体略转向画左门外",
            entity_states={"陈迹": "报出暗号"},
            entity_presence={"陈迹": "VISIBLE_AND_IDENTITY_LOCKED", "王龙": "ABSENT_REFERENCE_ONLY"},
        )
        self.assertIn("SPATIAL_OFFSCREEN_LISTENER_WITHOUT_VISUAL_CUES", sdc.validate(without))
        with_cue = dict(without, offscreen_listener_visual_cues="陈迹说完后视线扫向画左门外")
        self.assertEqual(sdc.validate(with_cue), [])
        self.assertIn("画内视觉线索", sdc.render_zh(with_cue))

    def test_offscreen_cue_on_a_visible_listener_is_a_contradiction(self):
        value = row(offscreen_listener_visual_cues="看向画外")
        self.assertIn("SPATIAL_OFFSCREEN_CUES_FOR_VISIBLE_LISTENER", sdc.validate(value))

    def test_gaze_at_an_unregistered_target_fails(self):
        value = row(speaker_gaze_target="落在第三个人的脸上")
        self.assertIn(
            "SPATIAL_GAZE_TARGET_UNREGISTERED:speaker_gaze_target:落在第三个人的脸上",
            sdc.validate(value),
        )

    def test_camera_and_offscreen_sentinels_are_legal_targets(self):
        for sentinel in ("CAMERA", "OFFSCREEN_LEFT"):
            value = row(speaker_gaze_target=sentinel)
            self.assertEqual(sdc.validate(value), [], sentinel)

    def test_listener_fields_without_a_listener_fail(self):
        value = row(dialogue_listener="", listener_gaze_target="落在陈迹脸上")
        self.assertIn(
            "SPATIAL_LISTENER_FIELD_WITHOUT_LISTENER:listener_gaze_target",
            sdc.validate(value),
        )

    def test_speaker_facing_without_a_speaker_fails(self):
        value = row(dialogue_speaker="", speaker_facing_direction="身体转向门口")
        self.assertIn("SPATIAL_SPEAKER_FACING_WITHOUT_SPEAKER", sdc.validate(value))


class SpatialRenderingTests(unittest.TestCase):
    def test_sd2_role_line_carries_the_declared_staging(self):
        value = row(
            speaker_facing_direction="身体转向王龙",
            listener_position_relative_to_speaker="坐在陈迹右侧约一米",
            listener_gaze_target="落在陈迹脸上",
        )
        line = _role_line(value)
        self.assertIn("陈迹身体转向王龙", line)
        self.assertIn("王龙坐在陈迹右侧约一米", line)
        self.assertIn("王龙的视线落在陈迹脸上", line)

    def test_english_clause_uses_provider_labels_not_chinese_names(self):
        value = row(
            speaker_facing_direction="身体转向王龙",
            speaker_gaze_target="落在药方上",
            entity_states={"陈迹": "报暗号", "王龙": "闭口", "药方": "被展开"},
        )
        clause = sdc.render_en(value, speaker_label="SUBJECT_1", listener_label="SUBJECT_2")
        self.assertIn("SUBJECT_1", clause)
        self.assertNotIn("陈迹", clause)

    def test_role_gate_reports_spatial_contradictions(self):
        value = row(offscreen_listener_visual_cues="看向画外")
        failures = validate_role_semantics(
            {"episode": "E99", "role_semantic_disambiguation": value},
            prompt_text="anything",
            required_from_episode=48,
        )
        self.assertTrue(any("SPATIAL_OFFSCREEN_CUES_FOR_VISIBLE_LISTENER" in item for item in failures))


if __name__ == "__main__":
    unittest.main()
