import unittest

from tools.writer_production_field_gate import validate_generation_contract
from tools.visual_culture_contract import DEFAULT_CONTRACT


def valid_contract():
    ambient = {
        "grade": "B", "motion_trend": "树叶与衣摆错峰微动",
        "first_frame_state": "首帧已在风中运动",
        "reaction_progression": "近景先反应，中景随后，远景最后",
    }
    weather_provenance = {
        "source_type": "SOURCE", "source_ref": "ch1",
        "visibility_mode": "VISIBLE_EXTERIOR",
    }
    action_visualization = {
        "purpose_and_stake": "确认井台异常", "invisible_factor": "疑虑",
        "visible_phenomenon": "脚步停在水迹前",
        "readability_self_check": "遮掉文字仍能读懂发现异常",
    }
    prompt_spec = {
        "writer_camera_instruction": "中景同轴横移",
        "writer_shot_treatment": "保持运动方向",
        "writer_expression_arc": "警觉到确认",
        "source_first_frame_motion_state": "人物迈步途中",
        "space": {"global": "GLOBAL-99", "location": "LOC-1", "subspace": "院门至井台"},
        "scene_state": {
            "time": "晨", "weather": "晴", "palette": "暖",
            "ambient_life": ambient, "weather_provenance": weather_provenance,
        },
        "cast": [{"character": "行人", "character_id": "CHAR-PASSERBY"}], "props": [{"prop": "井台"}],
        "action": {
            "subject_id": "CHAR-PASSERBY",
            "action_kind": "PHYSICAL_ACTION", "start_state": "人物迈步途中",
            "primary_action": "行人走向井台", "completion_state": "脚步停在水迹前",
            "contact_point": "鞋底与青砖", "motion_direction": "院门向井台",
            "physical_causality": "脚步接近后目光才落到水迹",
            "microexpression_design": "眉峰先收紧一次并保持",
            "physical_action_design": "落脚承重后身体停稳",
        },
        "referent_resolution_contract": {
            "status": "PASS", "source_scan_complete": True,
            "resolved_source_referents": [{"surface_form": "行人", "entity_id": "CHAR-PASSERBY"}],
            "unresolved_source_referents": [],
        },
        "dialogue": "",
        "performance": {
            "psychological_state": "警觉确认", "emotion": "克制警觉", "emotion_intensity": 2,
            "expression_arc": "目视前方→发现水迹→眉峰收紧",
            "continuous_micro_action": "呼吸与步态连续", "event_reaction": "水迹进入视野后停步",
            "body_sync": "视线先落下，脚步随后停稳",
            "actor_performance": {"行人": {
                "expression_arc": "目视前方→发现水迹→眉峰收紧",
                "continuous_micro_action": "呼吸与步态连续",
                "event_reaction": "水迹进入视野后停步", "body_sync": "视线先落下，脚步随后停稳",
            }},
        },
        "visual_design": {
            "depth_layers": ["前景院门", "中景行人", "后景井台"], "scale_anchor": "人物肩宽",
            "key_light": "晨光侧照", "atmosphere": "晨雾低幅流动",
            "environmental_motion": ["树叶与衣摆错峰微动"], "material_detail": ["青砖水迹"],
            "palette": {"dominant": "暖灰", "contrast": "冷青", "accent": "水白"},
            "still_prompt_contract": "首帧人物迈步途中", "video_motion_contract": "实时连续不复位",
        },
        "sound_design": {"ambience": "晨风", "foley": "衣摆摩擦", "action_sound": "鞋底触砖"},
        "ambient_life": ambient, "action_visualization": action_visualization,
        "role_semantic_disambiguation": {
            "status": "PASS", "primary_actor": "行人", "primary_actor_id": "CHAR-PASSERBY",
            "dialogue_speaker": "", "dialogue_speaker_id": "",
            "dialogue_listener": "", "dialogue_listener_id": "",
            "action_patient": "", "action_patient_id": "",
            "lip_owner_id": "",
            "entity_states": {"CHAR-PASSERBY": "行走后停步"},
            "entity_presence": {"CHAR-PASSERBY": "VISIBLE_AND_IDENTITY_LOCKED"},
        },
        "negative_prompts": ["无字幕", "无水印", "无冻结"],
        "audio_contract": "DIEGETIC_OR_SILENT_NO_TTS",
    }
    return {
        "episode": "E99",
        "visual_culture_contract": DEFAULT_CONTRACT,
        "character_entities": [{
            "character_id": "CHAR-PASSERBY", "canonical_name": "行人", "aliases": []
        }],
        "scene_states": [{
            "scene_id": "E99-S01", "location_id": "LOC-1", "time_of_day_state": "晨",
            "weather_state": "晴", "visual_zone": "院中", "interior_exterior": "EXT",
            "palette_temperature": "暖",
            "ambient_life": ambient,
            "weather_provenance": weather_provenance,
        }],
        "shots": [{
            "shot_id": "E99-S01-01", "scene_id": "E99-S01",
            "first_frame_motion_state": "人物迈步途中",
            "camera": "中景同轴横移", "subspace_id": "院门至井台",
            "frame_content": "人物走向井台", "shot_treatment": "保持运动方向",
            "expression_arc": "警觉到确认",
            "dialogue": "", "negative_prompts": ["无字幕", "无水印", "无冻结"],
            "action_visualization": action_visualization,
            "prompt_spec": prompt_spec,
        }],
        "audio_contract": {"bgm": "FORBIDDEN", "ambient_by_scene": {"E99-S01": {"ambience": "晨风"}}},
    }


class WriterProductionFieldGateTests(unittest.TestCase):
    def test_complete_contract_passes(self):
        self.assertEqual(validate_generation_contract(valid_contract())["status"], "PASS")

    def test_plain_weather_string_cannot_masquerade_as_ambience(self):
        payload = valid_contract()
        payload["audio_contract"]["ambient_by_scene"]["E99-S01"] = "晴"
        report = validate_generation_contract(payload)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("AUDIO_AMBIENT_SCENE_VALUE_MUST_BE_STRUCTURED_NOT_WEATHER_STRING", report["failures"])

    def test_missing_writer_fields_refuses_seal(self):
        payload = valid_contract()
        payload["shots"][0].pop("shot_treatment")
        payload["scene_states"][0].pop("ambient_life")
        report = validate_generation_contract(payload)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("E99-S01_AMBIENT_LIFE_MISSING", report["failures"])
        self.assertIn("E99-S01-01_SHOT_TREATMENT_MISSING", report["failures"])

    def test_downstream_cannot_invent_missing_prompt_spec(self):
        payload = valid_contract()
        payload["shots"][0].pop("prompt_spec")
        report = validate_generation_contract(payload)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("E99-S01-01_PROMPT_SPEC_MISSING", report["failures"])

    def test_prompt_spec_must_bind_source_camera_and_weather(self):
        payload = valid_contract()
        payload["shots"][0]["prompt_spec"]["writer_camera_instruction"] = "通用跟拍"
        payload["shots"][0]["prompt_spec"]["scene_state"]["weather"] = "雨夜"
        report = validate_generation_contract(payload)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("E99-S01-01_WRITER_CAMERA_INSTRUCTION_SOURCE_BINDING_MISMATCH", report["failures"])
        self.assertIn("E99-S01-01_WEATHER_SOURCE_BINDING_MISMATCH", report["failures"])

    def test_unresolved_nominal_referent_refuses_writer_seal(self):
        payload = valid_contract()
        contract = payload["shots"][0]["prompt_spec"]["referent_resolution_contract"]
        contract["status"] = "FAIL"
        contract["unresolved_source_referents"] = ["睡着的人"]
        report = validate_generation_contract(payload)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("E99-S01-01_REFERENT_RESOLUTION_NOT_PASS", report["failures"])
        self.assertIn("E99-S01-01_UNRESOLVED_SOURCE_REFERENTS", report["failures"])


if __name__ == "__main__":
    unittest.main()
