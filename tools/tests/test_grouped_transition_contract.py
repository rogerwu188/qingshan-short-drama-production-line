import copy
import unittest

from tools.grouped_transition_contract import compile_transition_prompt, validate_transition_sequence


def unit(unit_id, scene_id, space, framing, characters=None):
    characters = characters or []
    return {
        "unit_id": unit_id,
        "scene_id": scene_id,
        "camera_plan": {
            "shot_scale": "MEDIUM",
            "lens_intent": "50mm自然透视",
            "camera_height": "EYE_LEVEL",
            "camera_side": "AXIS_A",
            "axis_relation": "保持人物视线轴",
            "motion_family": "LOCKED",
            "motion_direction": "NONE",
            "start_framing": framing,
            "end_framing": framing,
            "motivation": "让人物表演在稳定构图中自然完成",
        },
        "ordered_prompt_specs": [{
            "space": space,
            "cast": [{"character": name, "face_visibility": "VISIBLE_PER_FRAME_CONTENT"} for name in characters],
            "props": [],
        }],
    }


def contract():
    return {
        "boundary_id": "BND-U1-U2",
        "from_unit_id": "U1",
        "to_unit_id": "U2",
        "authorship": "DIRECTOR_AUTHORED",
        "transition_device": "OCCLUSION_WIPE",
        "outgoing_handle_seconds": 0.9,
        "incoming_handle_seconds": 0.9,
        "plot_motivation": "帘幕遮挡把观众从凉亭秘密自然带进宴席反应",
        "cut_reason": "NEW_SPACE_MATCH_CUT",
        "space_relation": "NEW_LOCATION_SAME_GLOBAL",
        "visual_bridge": "前段帘缘落在画面中央，后段同尺度帘缘仍在同一画面位置",
        "action_bridge": "前段帘缘落下完成，后段由另一侧的手接力将帘缘挑开",
        "sound_bridge": "同一声帘布摩擦跨越剪辑点并自然延续",
        "axis_strategy": "利用正面帘面作为中性轴位完成空间重新建立",
        "continuity_intent": "明确从凉亭转到宴席，同时保持帘的形状、动作与声音连续",
        "source_terminal_state": {
            "scene_id": "S1",
            "space": {"global": "G", "location": "L1", "subspace": "A"},
            "camera_framing": "帘缘居中",
            "camera_side": "AXIS_A",
            "blocking": "帘缘落回中央并停止，人物退到画面边缘",
        },
        "target_initial_state": {
            "scene_id": "S2",
            "space": {"global": "G", "location": "L2", "subspace": "B"},
            "camera_framing": "白鲤与帘口同框",
            "camera_side": "AXIS_A",
            "blocking": "白鲤在帘后站定并由内向外挑开帘角",
        },
        "anchor_semantic_requirements": {
            "target_visible_characters": ["白鲤"],
            "target_visible_props": [],
            "target_space_anchors": ["女眷帘口", "宴席桌案"],
            "empty_establishing_frame_allowed": False,
        },
    }


class GroupedTransitionContractTests(unittest.TestCase):
    def setUp(self):
        self.first = unit("U1", "S1", {"global": "G", "location": "L1", "subspace": "A"}, "帘缘居中")
        self.second = unit("U2", "S2", {"global": "G", "location": "L2", "subspace": "B"}, "白鲤与帘口同框", ["白鲤"])
        self.second["transition_contract"] = contract()

    def test_accepts_authored_space_change_with_bound_visual_action_and_sound_bridge(self):
        units = [self.first, self.second]
        validate_transition_sequence(units, require_prompt_specs=True)
        self.assertEqual(units[0]["outgoing_transition_contract"]["to_unit_id"], "U2")
        self.assertEqual(units[1]["incoming_transition_contract"]["from_unit_id"], "U1")
        first_prompt = compile_transition_prompt(units[0])
        second_prompt = compile_transition_prompt(units[1])
        self.assertIn("出场边界=BND-U1-U2", first_prompt)
        self.assertIn("片尾转场预留=0.9秒", first_prompt)
        self.assertIn("片尾剧情动作=", first_prompt)
        self.assertIn("入场边界=BND-U1-U2", second_prompt)
        self.assertIn("入场预留=0.9秒", second_prompt)
        self.assertIn("剧情动机=", second_prompt)

    def test_rejects_missing_boundary_contract(self):
        del self.second["transition_contract"]
        with self.assertRaisesRegex(ValueError, "transition_contract is required"):
            validate_transition_sequence([self.first, self.second], require_prompt_specs=True)

    def test_rejects_empty_frame_when_target_beat_requires_visible_actor(self):
        self.second["transition_contract"]["anchor_semantic_requirements"]["empty_establishing_frame_allowed"] = True
        with self.assertRaisesRegex(ValueError, "cannot allow an empty establishing frame"):
            validate_transition_sequence([self.first, self.second], require_prompt_specs=True)

    def test_rejects_contract_bound_to_wrong_target_space(self):
        broken = copy.deepcopy(self.second["transition_contract"])
        broken["target_initial_state"]["space"]["location"] = "WRONG"
        self.second["transition_contract"] = broken
        with self.assertRaisesRegex(ValueError, "target space is not bound"):
            validate_transition_sequence([self.first, self.second], require_prompt_specs=True)

    def test_rejects_missing_transition_handle(self):
        del self.second["transition_contract"]["outgoing_handle_seconds"]
        with self.assertRaisesRegex(ValueError, "outgoing_handle_seconds"):
            validate_transition_sequence([self.first, self.second], require_prompt_specs=True)

    def test_rejects_non_deterministic_boundary_id(self):
        self.second["transition_contract"]["boundary_id"] = "WRONG"
        with self.assertRaisesRegex(ValueError, "boundary_id must be BND-U1-U2"):
            validate_transition_sequence([self.first, self.second], require_prompt_specs=True)


if __name__ == "__main__":
    unittest.main()
