from __future__ import annotations

from copy import deepcopy
import unittest

from tools.camera_language_selector import select_camera_language


def camera() -> dict:
    return {
        "shot_scale": "MEDIUM_WIDE", "lens_intent": "35mm交代双方与接触路径",
        "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
        "axis_relation": "保持既定人物轴不越轴", "motion_family": "TRACK",
        "motion_direction": "LEFT_TO_RIGHT", "start_framing": "双方起势同框",
        "end_framing": "接触后的新站位同框", "motivation": "只跟随唯一冲量到结果态",
    }


class CameraLanguageSelectorTest(unittest.TestCase):
    def test_hybrid_is_deterministic_and_preserves_director_fields(self) -> None:
        original = camera()
        first, receipt1 = select_camera_language(original, unit_class="COMBAT_IMPULSE", source_id="U1")
        second, receipt2 = select_camera_language(original, unit_class="COMBAT_IMPULSE", source_id="U1")
        self.assertEqual(first, second)
        self.assertEqual(receipt1, receipt2)
        for key, value in original.items():
            self.assertEqual(first[key], value)
        self.assertEqual(first["camera_profile_id"], "CAM-COMBAT-IMPULSE-CLEAR-V1")
        self.assertEqual(first["depth_of_field_intent"], "DEEP_SPATIAL_READABILITY")

    def test_locked_is_audit_only(self) -> None:
        locked = camera()
        locked["selection_mode"] = "LOCKED"
        selected, receipt = select_camera_language(locked, unit_class="DIALOGUE", source_id="U2")
        self.assertNotIn("lens_mm", selected)
        self.assertEqual(receipt["filled_fields"], [])

    def test_effects_require_structured_authorization(self) -> None:
        selected, _ = select_camera_language(camera(), unit_class="PHYSICAL_ACTION", source_id="U3")
        self.assertNotIn("effect_intent", selected)
        authorized, _ = select_camera_language(
            camera(), unit_class="PHYSICAL_ACTION", source_id="U3",
            unit={"camera_style_authorizations": {"effect_intent": "CONTACT_MICRO_SHAKE"}},
        )
        self.assertEqual(authorized["effect_intent"], "CONTACT_MICRO_SHAKE")


if __name__ == "__main__":
    unittest.main()
