import copy
import unittest

from tools.grouped_performance_contract import (
    compile_performance_clause,
    validate_grouped_beat_contract,
)
from tools.submit_giggle_video_manifest_v2 import grouped_sequence_unit, validate_grouped_creative_task


def valid_spec():
    return {
        "action": {
            "start_state": "手掌压在杯沿",
            "primary_action": "他抬起杯子说完一句话",
            "completion_state": "杯停在唇边",
            "contact_point": "手指与杯壁",
            "motion_direction": "由桌面向唇边上移",
            "physical_causality": "手指收紧后杯子才离开桌面",
        },
        "dialogue": "陈迹：不是为了钱。",
        "performance": {
            "psychological_state": "确认推断但不暴露急切",
            "emotion": "克制笃定",
            "emotion_intensity": 3,
            "expression_arc": "目光压低→说到钱时抬眼→视线停稳",
            "continuous_micro_action": "拇指沿杯沿缓慢摩擦",
            "event_reaction": "对方沉默后眼睑轻抬",
            "body_sync": "重音落下时杯子停止上移",
        },
        "dialogue_delivery": {
            "pace": "中慢",
            "pause_map": "为了｜钱前停半拍",
            "emphasis_words": ["钱"],
            "volume_arc": "低声起、句末收紧",
            "breath_pattern": "短吸后一次说完",
            "delivery_transition": "陈述转为确认",
        },
        "visual_design": {
            "depth_layers": ["前景帘角", "中景人物", "后景水面"],
            "scale_anchor": "酒杯与手掌",
            "key_light": "水面反射的侧逆光",
            "atmosphere": "暖尘缓慢浮动",
            "environmental_motion": ["帘角轻摆"],
            "material_detail": ["瓷杯釉面", "旧木桌纹"],
            "palette": {"dominant": "灰青", "contrast": "暖褐", "accent": "瓷白"},
            "still_prompt_contract": "首帧保持动作中途",
            "video_motion_contract": "动作实时连续且不得循环补时",
        },
        "sound_design": {
            "ambience": "池水和远处席间低语",
            "foley": "衣袖擦过桌沿",
            "action_sound": "杯底轻响",
        },
        "negative_prompts": ["无字幕", "无水印", "无循环动作"],
    }


class GroupedPerformanceContractTest(unittest.TestCase):
    def test_accepts_and_compiles_complete_performance_contract(self):
        spec = valid_spec()
        validate_grouped_beat_contract(spec, source_id="S1")
        text = compile_performance_clause(spec)
        self.assertIn("表情弧=目光压低→说到钱时抬眼→视线停稳", text)
        self.assertIn("重音钱", text)

    def test_rejects_missing_micro_expression_contract(self):
        spec = valid_spec()
        del spec["performance"]["continuous_micro_action"]
        with self.assertRaisesRegex(ValueError, "continuous_micro_action"):
            validate_grouped_beat_contract(spec, source_id="S1")

    def test_rejects_uniform_dialogue_without_delivery_contract(self):
        spec = valid_spec()
        del spec["dialogue_delivery"]
        with self.assertRaisesRegex(ValueError, "dialogue_delivery"):
            validate_grouped_beat_contract(spec, source_id="S1")

    def test_rejects_flat_expression_arc(self):
        spec = copy.deepcopy(valid_spec())
        spec["performance"]["expression_arc"] = "始终面无表情"
        with self.assertRaisesRegex(ValueError, "visible change"):
            validate_grouped_beat_contract(spec, source_id="S1")

    def test_paid_submission_rejects_grouped_task_without_creative_contract(self):
        task = {"task_key": "E42-VU-001-VIDEO-A1", "semantic_video_unit": True}
        with self.assertRaisesRegex(ValueError, "camera_plan"):
            validate_grouped_creative_task(task, "legacy generic prompt")

    def test_submission_binding_preserves_both_transition_contracts(self):
        incoming = {"boundary_id": "BND-E43-VU-001-E43-VU-002"}
        outgoing = {"boundary_id": "BND-E43-VU-002-E43-VU-003"}
        task = {
            "unit_id": "E43-VU-002",
            "machine_contract": {
                "incoming_transition_contract": incoming,
                "outgoing_transition_contract": outgoing,
            },
        }
        unit = grouped_sequence_unit(task)
        self.assertEqual(unit["transition_contract"], incoming)
        self.assertEqual(unit["incoming_transition_contract"], incoming)
        self.assertEqual(unit["outgoing_transition_contract"], outgoing)


if __name__ == "__main__":
    unittest.main()
