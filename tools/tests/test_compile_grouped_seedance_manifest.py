import tempfile
import unittest
from pathlib import Path

from tools.compile_grouped_seedance_manifest import (
    MAX_MODEL_PROMPT_CHARS,
    build_writer_agent_provenance,
    compile_manifest,
    prompt_text,
    validate_model_prompt,
)


def locked_camera(label="双人中景"):
    return {
        "shot_scale": "MEDIUM", "lens_intent": "50mm自然透视",
        "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
        "axis_relation": "保持既定人物视线轴，不越轴",
        "motion_family": "LOCKED", "motion_direction": "NONE",
        "start_framing": label, "end_framing": label,
        "motivation": "让对白眼神和手部表演在稳定构图内自行发生",
    }


def creative_contract(*, dialogue=""):
    contract = {
        "performance": {
            "psychological_state": "压住即时反应",
            "emotion": "克制",
            "emotion_intensity": 2,
            "expression_arc": "目光停住→下颌微收→重新看向对方",
            "continuous_micro_action": "指腹轻压袖口且呼吸不断",
            "event_reaction": "听见关键词后眼神停顿半拍",
            "body_sync": "重音落下时肩线轻微下沉",
            "actor_performance": {
                "梁狗儿": {
                    "expression_arc": "醉眼半合→突然盯住对方→眼神放松",
                    "continuous_micro_action": "抓袖的指节持续轻动",
                    "event_reaction": "听见回答后鼻翼轻张",
                    "body_sync": "说话时肩背随呼吸起伏",
                },
                "陈迹": {
                    "expression_arc": "垂眼→短暂抬眼→重新垂下",
                    "continuous_micro_action": "被抓住后前臂维持细小抵抗",
                    "event_reaction": "问题落下时下颌收紧",
                    "body_sync": "回答时身体保持克制不后退",
                },
            },
        },
        "visual_design": {
            "depth_layers": ["前景门框", "中景人物", "后景院墙"],
            "scale_anchor": "人物肩宽与桌沿",
            "key_light": "窗侧自然斜光",
            "atmosphere": "细尘在光柱中缓慢浮动",
            "environmental_motion": ["帘角轻摆"],
            "material_detail": ["旧木桌纹", "粗布袖口"],
            "palette": {"dominant": "灰褐", "contrast": "冷青", "accent": "暖金"},
            "still_prompt_contract": "首帧保持动作中途而非完成态",
            "video_motion_contract": "人物持续微动且不得循环或冻结补时",
        },
        "sound_design": {
            "ambience": "院内远风",
            "foley": "衣袖摩擦",
            "action_sound": "杯底轻触桌面",
        },
        "negative_prompts": ["无字幕", "无水印", "无循环动作"],
    }
    if dialogue:
        spoken = dialogue.partition("：")[2]
        contract["dialogue_delivery"] = {
            "pace": "中慢",
            "pause_map": "句中停半拍",
            "emphasis_words": [spoken[:1]],
            "volume_arc": "低到更低",
            "breath_pattern": "短吸后平稳呼出",
            "delivery_transition": "试探转为笃定",
        }
    return contract


class CompileGroupedSeedanceManifestTest(unittest.TestCase):
    def test_writer_agent_provenance_binds_paths_and_sha(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            script = Path(tmp) / "script.md"
            contract = Path(tmp) / "contract.json"
            script.write_text("script", encoding="utf-8")
            contract.write_text("{}", encoding="utf-8")

            provenance = build_writer_agent_provenance(script, contract)

            self.assertEqual(provenance["status"], "PASS")
            self.assertEqual(provenance["provenance_type"], "claude_writer_script")
            self.assertEqual(len(provenance["source_script_sha256"]), 64)
            self.assertEqual(len(provenance["production_manifest_sha256"]), 64)

    def test_model_prompt_is_compact_and_does_not_leak_machine_contract(self):
        specs = []
        timeline = []
        dialogue = ["", "梁狗儿：不许再提。", "梁狗儿：你学刀做什么。", "陈迹：自保。", "梁狗儿：想保命，就握不住刀。"]
        actions = [
            ("梁狗儿醉醒过来，一把把陈迹拽过去。", "一把拽住臂弯把人带转半圈，两人错开半步站定"),
            ("不许再提。", "说话时另一只手指着院子那一头"),
            ("你学刀做什么。", "问的时候手还抓着对方的袖子"),
            ("自保。", "答得极快，答完没有补话"),
            ("想保命，就握不住刀。", "说完松开袖子，手往下一甩"),
        ]
        boundaries = [(0, 1.5), (1.5, 2.6), (2.6, 4.1), (4.1, 5.0), (5.0, 7.6)]
        for index, ((primary, terminal), raw_dialogue, (start, end)) in enumerate(zip(actions, dialogue, boundaries)):
            spec = {
                "space": {"global": "GLOBAL-SPACE-E41", "location": "LOC-COURTYARD", "subspace": f"SUB-{index}"},
                "scene_state": {"weather": "上午，日头爬到院墙上沿", "palette": "warm"},
                "cast": [{"character": "梁狗儿"}, {"character": "陈迹"}],
                "props": [{"prop": "刀"}] if index in {2, 4} else [],
                "action": {
                    "start_state": "动作尚未完成",
                    "primary_action": primary,
                    "completion_state": terminal,
                    "contact_point": "手部与袖口或道具",
                    "motion_direction": "由当前姿态连续走向终态",
                    "physical_causality": "身体发力先于物件或对方反应",
                },
                "dialogue": raw_dialogue,
            }
            spec.update(creative_contract(dialogue=raw_dialogue))
            specs.append(spec)
            timeline.append({"start_seconds": start, "end_seconds": end})
        unit = {
            "unit_id": "E41-VU-015",
            "scene_id": "S14",
            "duration_seconds": 7.6,
            "ordered_prompt_specs": specs,
            "action_timeline": timeline,
            "reference_images": [{"path": "frame.png", "sha256": "not-for-model", "role": "SCENE_START_ANCHOR"}],
            "camera_plan": locked_camera(),
        }

        text = prompt_text(unit, [{"id": "PF-001"}, {"id": "PF-042"}])
        result = validate_model_prompt(text, source_id=unit["unit_id"])

        self.assertEqual(result["status"], "PASS")
        self.assertLessEqual(len(text), MAX_MODEL_PROMPT_CHARS)
        self.assertIn("竖屏9:16", text)
        self.assertIn("seedance-2.0-pro", text)
        self.assertNotIn("seedance-2.0-fast", text)
        self.assertNotIn("16:9", text)
        self.assertNotIn("GLOBAL-SPACE-", text)
        self.assertNotIn("sha256", text)
        self.assertNotIn("PF-", text)
        self.assertNotIn("【逐节拍完整合同】", text)
        self.assertIn("【镜头硬合同】", text)
        self.assertIn("全段锁定机位", text)
        self.assertNotIn("镜头随主要动作平稳调整景别", text)
        self.assertEqual(text.count("不许再提。"), 1)
        self.assertEqual(text.count("你学刀做什么。"), 1)
        self.assertEqual(text.count("自保。"), 1)
        self.assertEqual(text.count("想保命，就握不住刀。"), 1)

    def test_preserves_transport_strategy_and_reference_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.png"
            later = Path(tmp) / "later.png"
            first.write_bytes(b"first")
            later.write_bytes(b"later")
            grouping = {
                "episode": "E41",
                "video_unit_count": 1,
                "runtime_seconds": 6,
                "units": [{
                    "unit_id": "VU-1", "scene_id": "S1", "duration_seconds": 6,
                    "editorial_shot_ids": ["S1-1", "S1-2"], "narrative_beat": "beat",
                    "camera_plan": locked_camera(),
                }],
            }
            anchors = {"units": [{
                "unit_id": "VU-1", "planned_reference_image_count": 2,
                "reference_image_paths": [str(first), str(later)],
                "reference_transport_strategy": "OMNI_MULTI_REFERENCE",
                "anchor_count_decision": {
                    "anchor_roles": ["ADMITTED_SCENE_START_STATE", "IDENTITY_OR_PROP_REANCHOR"],
                },
                "semantic_reference_coverage_gate": {"status": "PASS"},
            }]}
            prompt_spec = {
                "action": {
                    "start_state": "手在桌边", "primary_action": "抬起杯子", "completion_state": "杯到唇边",
                    "contact_point": "手指与杯壁", "motion_direction": "由桌面向唇边上移",
                    "physical_causality": "手指收紧后杯子才离开桌面",
                },
                "dialogue": "",
                "cast": [{"character": "梁狗儿"}, {"character": "陈迹"}],
                **creative_contract(),
            }
            editorial = {"shots": [
                {"shot_id": "S1-1", "model": "seedance-2.0-pro", "resolution": "720p", "prompt_spec": prompt_spec},
                {"shot_id": "S1-2", "model": "seedance-2.0-pro", "resolution": "720p", "prompt_spec": prompt_spec},
            ]}
            result = compile_manifest(grouping, anchors, editorial)
            unit = result["units"][0]
            self.assertEqual(unit["reference_transport_strategy"], "STANDARD_MULTI_REFERENCE")
            self.assertEqual(unit["source_reference_transport_strategy"], "OMNI_MULTI_REFERENCE")
            self.assertEqual(
                [row["role"] for row in unit["reference_images"]],
                ["ADMITTED_SCENE_START_STATE", "IDENTITY_OR_PROP_REANCHOR"],
            )
            self.assertEqual(unit["semantic_reference_coverage_gate"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
