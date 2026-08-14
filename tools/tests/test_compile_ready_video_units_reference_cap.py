import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tools.compile_ready_video_units import (
    build_timeline,
    bind_exact_dialogue_audio,
    cap_reference_states,
    native_dialogue_instruction,
    playable_clauses,
)


class ReferenceCapTest(unittest.TestCase):
    def test_keeps_two_states_for_each_of_four_shots(self):
        states = {
            f"S{shot}": [{"state_id": f"S{shot}-C{state}"} for state in range(1, 4)]
            for shot in range(1, 5)
        }

        selected, report = cap_reference_states(states)

        self.assertTrue(report["applied"])
        self.assertEqual(report["before"], 12)
        self.assertEqual(report["after"], 8)
        self.assertEqual(
            [[row["state_id"] for row in selected[f"S{shot}"]] for shot in range(1, 5)],
            [[f"S{shot}-C1", f"S{shot}-C3"] for shot in range(1, 5)],
        )

    def test_rejects_unit_that_cannot_keep_two_states_per_shot(self):
        states = {f"S{shot}": [{"state_id": f"S{shot}-C1"}, {"state_id": f"S{shot}-C2"}] for shot in range(1, 6)}
        with self.assertRaisesRegex(RuntimeError, "regroup"):
            cap_reference_states(states)

    def test_filters_post_production_directives_from_playable_actions(self):
        self.assertEqual(
            playable_clauses("陈迹在空白名册上写入身份；后期用真字体叠加"),
            ["陈迹在空白名册上写入身份"],
        )

    def test_timeline_states_are_monotonic_and_actions_remain_visible(self):
        unit = {"editorial_shot_ids": ["S1"]}
        shots = {"S1": {
            "duration_seconds": 9,
            "action": "陈迹在空白名册上写入身份；后期用真字体叠加",
            "motion_beats": [
                {"subject": "陈迹右手", "action": "抬笔移向纸面", "contact_point": "笔尖与纸面上方一寸", "direction": "垂直向下", "end_state": "笔尖停在落笔点"},
                {"subject": "陈迹右手", "action": "落笔并向右运笔", "contact_point": "笔尖与纸面", "direction": "从左向右", "end_state": "墨迹沿笔尖轨迹留在纸面"},
                {"subject": "陈迹右手", "action": "提笔离开纸面", "contact_point": "笔尖与最后落点", "direction": "垂直向上", "end_state": "笔尖离纸且手腕停稳"},
            ],
        }}
        states = {"S1": [{"state_id": "S1-C1"}, {"state_id": "S1-C2"}]}

        timeline = build_timeline(unit, shots, states)

        self.assertEqual([row["reference_state_id"] for row in timeline], ["S1-C1", "S1-C1", "S1-C2"])
        self.assertFalse(any("后期" in action or "叠加" in action for row in timeline for action in row["actions"]))
        self.assertIn("接触点=笔尖与纸面", timeline[1]["actions"][1])
        self.assertIn("终态=笔尖离纸且手腕停稳", timeline[2]["actions"][2])

    def test_rejects_generic_action_without_authored_physical_beats(self):
        with self.assertRaisesRegex(RuntimeError, "missing authored motion_beats"):
            build_timeline(
                {"editorial_shot_ids": ["S1"]},
                {"S1": {"duration_seconds": 3, "action": "人物打斗"}},
                {"S1": [{"state_id": "S1-C1"}]},
            )

    def test_native_dialogue_uses_exact_audio_reference_and_lip_sync(self):
        text, rows = native_dialogue_instruction("S1", {"dialogue": [{
            "dia_id": "D1", "speaker": "陈迹", "spoken_text": "别动。"
        }]}, {"D1": {"audio_slot": "@音频1"}})
        self.assertEqual(len(rows), 1)
        self.assertIn("@音频1", text)
        self.assertIn("精确目标对白参考", text)
        self.assertIn("口型", text)
        self.assertNotIn("后期绑定", text)

    def test_rejects_missing_dialogue_mapping(self):
        with self.assertRaisesRegex(RuntimeError, "missing explicit dialogue mapping"):
            native_dialogue_instruction("S1", {}, {})

    def test_binds_one_local_audio_file_per_dialogue_id(self):
        with TemporaryDirectory(dir="/Users/rogerwu/qingshan_short_drama") as tmp:
            audio = Path(tmp) / "D1.wav"
            audio.write_bytes(b"exact-dialogue-audio")
            shot = {"dialogue": [{
                "dia_id": "D1", "speaker": "陈迹", "spoken_text": "别动。",
                "reference_audio": str(audio),
            }]}
            assets, by_dia = bind_exact_dialogue_audio(
                {"unit_id": "U1", "editorial_shot_ids": ["S1"]}, {"S1": shot}
            )
        self.assertEqual(assets[0]["audio_slot"], "@音频1")
        self.assertEqual(assets[0]["purpose"], "EXACT_TARGET_DIALOGUE_REFERENCE")
        self.assertEqual(by_dia["D1"]["sha256"], assets[0]["sha256"])

    def test_rejects_dialogue_without_exact_audio_file(self):
        with self.assertRaisesRegex(RuntimeError, "missing reference_audio"):
            bind_exact_dialogue_audio(
                {"unit_id": "U1", "editorial_shot_ids": ["S1"]},
                {"S1": {"dialogue": [{"dia_id": "D1", "speaker": "陈迹", "spoken_text": "别动。"}]}},
            )


if __name__ == "__main__":
    unittest.main()
