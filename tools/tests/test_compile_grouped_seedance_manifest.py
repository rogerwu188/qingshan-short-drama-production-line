import tempfile
import unittest
import hashlib
import json
from pathlib import Path

from tools.compile_grouped_seedance_manifest import (
    MAX_MODEL_PROMPT_CHARS,
    action_timeline,
    build_writer_agent_provenance,
    compile_manifest,
    prompt_text,
    validate_model_prompt,
    validate_transition_prompt_binding,
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


def wardrobe_row(character, tier, primary, secondary, silhouette, accessory):
    return {
        "character": character, "social_tier": tier,
        "role_basis": f"剧本声明的{tier}身份与当前职业",
        "silhouette": silhouette, "outer_layer": f"{primary}交领外衫",
        "inner_layer": f"{secondary}窄袖内衫", "primary_color": primary,
        "secondary_color": secondary, "material": "细密棉绸混纺",
        "pattern": "领缘低对比几何暗纹", "belt_or_fastening": f"{secondary}束带",
        "footwear": "深色软底短靴", "accessory": accessory,
        "condition": "整洁但带符合剧情的一线使用痕迹",
        "continuity_key": f"{character}-{primary}-{secondary}-V1",
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


def internal_contract(unit_id, from_shot, to_shot, previous, current, mode="CAMERA_REFRAME"):
    def visible(spec):
        return sorted({row["character"] for row in spec.get("cast", []) if row.get("character") and row.get("face_visibility") != "OFFSCREEN_VOICE_ONLY"})

    def props(spec):
        return sorted({row["prop"] for row in spec.get("props", []) if row.get("prop")})

    def space(spec):
        source = spec.get("space") or {}
        return {key: str(source.get(key) or "") for key in ("global", "location", "subspace")}

    def sound(spec):
        source = spec.get("sound_design") or {}
        return {key: str(source.get(key) or "") for key in ("ambience", "foley", "action_sound")}

    previous_terminal = previous["action"]["completion_state"]
    current_start = current["action"]["start_state"]
    return {
        "boundary_id": f"INT-{unit_id}-{from_shot}-{to_shot}",
        "from_shot_id": from_shot,
        "to_shot_id": to_shot,
        "transition_mode": mode,
        "authorship": "DIRECTOR_AUTHORED",
        "cast_bridge": {
            "from_visible_characters": visible(previous),
            "to_visible_characters": visible(current),
            "identity_preservation": "所有既有人物脸、发型和服装保持原身份不漂移",
            "entry_exit_or_reveal": "摄影机重新构图并明确保留或揭示当前人物，不发生身份替换",
        },
        "scene_bridge": {
            "from_space": space(previous),
            "to_space": space(current),
            "continuity": "保持同一地点的建筑、光线、时间与天气，若子空间变化则由镜头明确建立",
        },
        "prop_bridge": {
            "from_props": props(previous),
            "to_props": props(current),
            "ownership_or_handoff": "道具由当前持有人连续保管，新增或离场道具通过可见动作交接",
        },
        "sound_bridge": {
            "from_sound": sound(previous),
            "to_sound": sound(current),
            "bridge": "同一环境底声连续，接触声只在真实动作点发生，对白说话人不变更",
        },
        "camera_bridge": {
            "axis_strategy": "保持既定轴侧，换侧前以固定物重新建立方向",
            "transition_execution": "按当前镜头计划完成一次重新构图，不用人物变形代替转场",
        },
        "action_bridge": f"前拍保持“{previous_terminal}”，随后从“{current_start}”继续，不复位",
        "reference_bridge": {
            "entity_mapping": "每张参考图只绑定其具名人物、场景和道具，不把后图人物覆盖前图人物",
            "different_character_same_slot_forbidden": True,
            "same_slot_reuse_allowed": False,
        },
    }


class CompileGroupedSeedanceManifestTest(unittest.TestCase):
    def test_long_authored_beat_expands_into_non_repeating_physical_phases(self):
        unit = {
            "duration_seconds": 6.6,
            "ordered_prompt_specs": [{
                "space": {"location": "LOC-POND", "subspace": "SUB-TABLE"},
                "cast": [{"character": "陈问孝"}],
                "props": [],
                "action": {
                    "t0_seconds": 0,
                    "t1_seconds": 6.6,
                    "start_state": "倚坐",
                    "primary_action": "把腰背坐直并报出数目",
                    "completion_state": "直立坐稳，手指停在案面",
                    "motion_direction": "上身向上挺直，手指向下落到案面",
                },
            }],
        }

        rows = action_timeline(unit)

        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["end_seconds"] - row["start_seconds"] <= 3.0 for row in rows))
        self.assertEqual(rows[-1]["end_seconds"], 6.6)
        self.assertIn("接触点已成立", rows[0]["actions"][0])
        self.assertIn("眼神与下颌", rows[1]["actions"][0])
        self.assertIn("直立坐稳", rows[-1]["actions"][0])

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
        dialogue = ["", "梁狗儿：不许再提。", "梁狗儿：你学刀做什么。", "陈迹：自保。", "梁狗儿：握刀难保命。"]
        actions = [
            ("梁狗儿醉醒过来，一把把陈迹拽过去。", "一把拽住臂弯把人带转半圈，两人错开半步站定"),
            ("不许再提。", "说话时另一只手指着院子那一头"),
            ("你学刀做什么。", "问的时候手还抓着对方的袖子"),
            ("自保。", "答得极快，答完没有补话"),
            ("握刀难保命。", "说完松开袖子，手往下一甩"),
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
            "duration_seconds": 15.0,
            "ordered_prompt_specs": specs,
            "action_timeline": timeline,
            "reference_images": [{"path": "frame.png", "sha256": "not-for-model", "role": "SCENE_START_ANCHOR"}],
            "camera_plan": locked_camera(),
            "wardrobe_contract": {"characters": [
                wardrobe_row("梁狗儿", "LOW_RANK_ENFORCER", "暗赭", "旧金", "短阔肩外衫", "旧铜酒牌"),
                wardrobe_row("陈迹", "MODEST_SCHOLAR", "烟青", "深靛", "窄身长线条", "素木药囊扣"),
            ]},
        }
        unit["editorial_shot_ids"] = [f"E41-S14-{index + 1:02d}" for index in range(len(specs))]
        unit["internal_transition_contracts"] = [
            internal_contract(
                unit["unit_id"], unit["editorial_shot_ids"][index], unit["editorial_shot_ids"][index + 1],
                specs[index], specs[index + 1],
            )
            for index in range(len(specs) - 1)
        ]

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
        self.assertIn("【转场硬合同】", text)
        self.assertIn("入场边界=SEQUENCE_START", text)
        self.assertIn("出场边界=SEQUENCE_END", text)
        self.assertEqual(validate_transition_prompt_binding(text, unit)["status"], "PASS")
        self.assertIn("全段锁定机位", text)
        self.assertNotIn("镜头随主要动作平稳调整景别", text)
        self.assertEqual(text.count("不许再提。"), 1)
        self.assertEqual(text.count("你学刀做什么。"), 1)
        self.assertEqual(text.count("自保。"), 1)
        self.assertEqual(text.count("握刀难保命。"), 1)

    def test_preserves_transport_strategy_and_reference_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.png"
            later = Path(tmp) / "later.png"
            first.write_bytes(b"first")
            later.write_bytes(b"later")
            first_sha = hashlib.sha256(first.read_bytes()).hexdigest()
            evidence = Path(tmp) / "semantic-evidence.json"
            evidence.write_text(json.dumps({
                "status": "PASS",
                "reference_path": str(first),
                "reference_sha256": first_sha,
                "observed_visible_characters": ["梁狗儿", "陈迹"],
                "observed_visible_props": [],
                "observed_space_anchors": ["院墙"],
                "camera_start_framing_match": True,
                "space_match": True,
                "empty_establishing_frame": False,
            }), encoding="utf-8")
            grouping = {
                "episode": "E41",
                "video_unit_count": 1,
                "runtime_seconds": 6,
                "wardrobe_bible": {"bible_id": "E41-WARDROBE-V1", "characters": [
                    wardrobe_row("梁狗儿", "LOW_RANK_ENFORCER", "暗赭", "旧金", "短阔肩外衫", "旧铜酒牌"),
                    wardrobe_row("陈迹", "MODEST_SCHOLAR", "烟青", "深靛", "窄身长线条", "素木药囊扣"),
                ]},
                "units": [{
                    "unit_id": "VU-1", "scene_id": "S1", "duration_seconds": 6,
                    "editorial_shot_ids": ["S1-1", "S1-2"], "narrative_beat": "beat",
                    "camera_plan": locked_camera(),
                    "internal_transition_contracts": [],
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
                "required_start_space_anchors": ["院墙"],
                "start_frame_semantic_contract": {
                    "status": "PASS",
                    "reference_path": str(first),
                    "reference_sha256": first_sha,
                    "evidence_ref": str(evidence),
                    "observed_visible_characters": ["梁狗儿", "陈迹"],
                    "observed_visible_props": [],
                    "observed_space_anchors": ["院墙"],
                    "camera_start_framing_match": True,
                    "space_match": True,
                    "empty_establishing_frame": False,
                },
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
            grouping["units"][0]["internal_transition_contracts"] = [
                internal_contract("VU-1", "S1-1", "S1-2", prompt_spec, prompt_spec)
            ]
            result = compile_manifest(grouping, anchors, editorial)
            unit = result["units"][0]
            self.assertEqual(unit["reference_transport_strategy"], "STANDARD_MULTI_REFERENCE")
            self.assertEqual(unit["source_reference_transport_strategy"], "OMNI_MULTI_REFERENCE")
            self.assertEqual(
                [row["role"] for row in unit["reference_images"]],
                ["ADMITTED_SCENE_START_STATE", "IDENTITY_OR_PROP_REANCHOR"],
            )
            self.assertEqual(unit["semantic_reference_coverage_gate"]["status"], "PASS")

    def test_compile_rejects_non_native_1080p_sd2_contract(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            anchor = Path(tmp) / "anchor.png"
            anchor.write_bytes(b"portrait-reference")
            first_sha = hashlib.sha256(anchor.read_bytes()).hexdigest()
            evidence = Path(tmp) / "evidence.json"
            evidence_payload = {
                "status": "PASS", "reference_path": str(anchor), "reference_sha256": first_sha,
                "observed_visible_characters": ["梁狗儿", "陈迹"], "observed_visible_props": [],
                "observed_space_anchors": ["L", "S"], "camera_start_framing_match": True,
                "space_match": True, "empty_establishing_frame": False,
            }
            evidence.write_text(json.dumps(evidence_payload, ensure_ascii=False), encoding="utf-8")
            grouping = {"episode": "E44", "video_unit_count": 1, "runtime_seconds": 6.0, "units": [{
                "unit_id": "E44-VU-001", "scene_id": "E44-S01", "duration_seconds": 6.0,
                "editorial_shot_ids": ["E44-S01-01"], "narrative_beat": "人物完成一次交接",
                "camera_plan": locked_camera(), "transition_contract": None,
            }]}
            anchors = {"units": [{
                "unit_id": "E44-VU-001", "planned_reference_image_count": 1,
                "reference_image_paths": [str(anchor)],
                "reference_transport_strategy": "STANDARD_MULTI_REFERENCE",
                "anchor_count_decision": {"anchor_roles": ["ADMITTED_SCENE_START_STATE"]},
                "semantic_reference_coverage_gate": {"status": "PASS"},
                "required_start_space_anchors": ["L", "S"],
                "start_frame_semantic_contract": {
                    "status": "PASS", "reference_path": str(anchor), "reference_sha256": first_sha,
                    "evidence_ref": str(evidence), "observed_visible_characters": ["梁狗儿", "陈迹"],
                    "observed_visible_props": [], "observed_space_anchors": ["L", "S"],
                    "camera_start_framing_match": True, "space_match": True,
                    "empty_establishing_frame": False,
                },
            }]}
            spec = {
                "space": {"global": "G", "location": "L", "subspace": "S"},
                "scene_state": {"weather": "晴", "palette": "灰青"},
                "cast": [{"character": "梁狗儿"}, {"character": "陈迹"}], "props": [],
                "action": {"t0_seconds": 0, "t1_seconds": 6, "start_state": "站定", "primary_action": "递出物件", "completion_state": "手臂收回", "contact_point": "手与物件", "motion_direction": "向前后收回", "physical_causality": "接触先于收手"},
                "dialogue": "", **creative_contract(),
            }
            editorial = {"shots": [{"shot_id": "E44-S01-01", "model": "seedance-2.0-pro", "resolution": "1080p", "aspect_ratio": "9:16", "prompt_spec": spec}]}
            with self.assertRaisesRegex(ValueError, "non-native resolution 1080p"):
                compile_manifest(grouping, anchors, editorial)


if __name__ == "__main__":
    unittest.main()
