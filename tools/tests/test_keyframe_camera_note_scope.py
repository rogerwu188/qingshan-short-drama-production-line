"""K070 KEYFRAME_CAMERA_NOTE_SCOPE: 机位说明 must not carry other shots bound to the same angle.

E10 S5 Q1: the inherited angle label lists the shot_size／camera of every shot on that angle,
so E10-S03-03 / S10-01 / S05-01 keyframes drew another shot's box, covered mouth and end state.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools"))
import build_keyframe_manifest as bkm  # noqa: E402

POLICY = bkm.load_camera_note_policy()

# E10-S03-03 as compiled from disk (angle ANGLE-XU-HOUSE-INT-09 is shared with E10-S17-04).
SP_TASK = {"angle_id": "ANGLE-XU-HOUSE-INT-09"}
SUBSPACE = {
    "angle_id": "ANGLE-XU-HOUSE-INT-09",
    "axis_id": "AXIS-XU-HOUSE-INT-SOUTH-NORTH",
    "camera_position": [424.0, 28.9],
    "camera_facing": "north",
    "screen_direction": "A_BOTTOM_B_TOP",
    "authored_camera_note": "特写／特写横摇到愕然的许岳平；中近景／50mm环绕拄杖探身盯着木盒的刘老头（E10-S03-03、E10-S17-04）",
}
SHOT = {"shot_id": "E10-S03-03", "shot_size": "特写"}
SPEC = {"camera": "特写／特写横摇到愕然的许岳平；机位 ANGLE-XU-HOUSE-INT-09，轴线 AXIS-XU-HOUSE-INT-SOUTH-NORTH，子空间 SUBSPACE-E10-S03-03"}


class CameraNoteScopeTests(unittest.TestCase):
    def test_policy_gates_e11_onward_and_keeps_e01_e10_legacy(self):
        self.assertEqual(POLICY.get("schema"), bkm.CAMERA_NOTE_POLICY_SCHEMA)
        start = int(POLICY["active_from_episode"])
        self.assertEqual(start, 11)
        for episode in ("E01", "E09", "E10"):
            self.assertFalse(bkm.camera_note_scoped(episode))
        self.assertTrue(bkm.camera_note_scoped("E11"))
        self.assertTrue(bkm.camera_note_scoped("E12"))
        self.assertFalse(bkm.camera_note_scoped("E11", {}))  # missing policy = legacy

    def test_scoped_note_has_geometry_and_only_this_shot(self):
        note = bkm.scoped_camera_note(SP_TASK, SUBSPACE, SHOT, SPEC, POLICY)
        for token in ("ANGLE-XU-HOUSE-INT-09", "[424.0, 28.9]", "north",
                      "AXIS-XU-HOUSE-INT-SOUTH-NORTH", "A_BOTTOM_B_TOP", "景别 特写",
                      "本镜：特写／特写横摇到愕然的许岳平"):
            self.assertIn(token, note)
        for leaked in ("盯着木盒", "刘老头", "E10-S17-04", "E10-S03-03", "子空间"):
            self.assertNotIn(leaked, note)

    def test_own_camera_text_strips_machine_suffix_and_falls_back(self):
        self.assertEqual(bkm.own_camera_text(SPEC["camera"], "特写"), "特写／特写横摇到愕然的许岳平")
        self.assertEqual(bkm.own_camera_text("", "中景"), "中景")
        self.assertEqual(bkm.own_camera_text(None, None), "无")


if __name__ == "__main__":
    unittest.main()
