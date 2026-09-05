from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.build_video_unit_anchor_plan import build
from tools.cross_episode_event_continuity_gate import evaluate as evaluate_cross_episode
from tools.editorial_selection_gate import evaluate_rows
from tools.keyframe_entry_state_gate import evaluate_task
from tools.media_frame_integrity import recommend_window
from tools.prop_state_contract import compile_prop_states
from tools.video_execution_plan_compiler import compile_video_execution_plan
from tools.event_boundary_continuity_contract import (
    classify_boundary, compile_internal_shot_boundaries,
)


class E51PipelineRectificationTests(unittest.TestCase):
    def test_same_scene_second_unit_uses_previous_real_final_frame(self):
        grouping = {"episode": "E52", "units": [
            {"unit_id": "U1", "scene_id": "S1", "editorial_shot_ids": ["A"]},
            {"unit_id": "U2", "scene_id": "S1", "editorial_shot_ids": ["B"]},
        ]}
        editorial = {"shots": [
            {"shot_id": "A", "scene_id": "S1", "prompt_spec": {}},
            {"shot_id": "B", "scene_id": "S1", "prompt_spec": {}},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "A-keyframe-v1.png").touch()
            plan = build(grouping, editorial, Path(tmp))
        self.assertEqual(plan["units"][1]["reference_image_task_keys"][0], "U1:REAL_FINAL_FRAME")
        self.assertEqual(plan["units"][1]["opening_anchor_contract"]["source"], "PREVIOUS_UNIT_REAL_FINAL_FRAME")
        self.assertEqual(plan["missing_anchor_shot_ids"], [])

    @staticmethod
    def _persistent_state(*, posture="卧床", injury="重伤", population="四人在房内"):
        person = {
            "presence": "IN_ROOM_VISIBLE_OR_ESTABLISHED_OFFSCREEN",
            "posture": posture,
            "injury": injury,
            "wardrobe": "深色中衣，胸前包扎",
            "position": "通铺画心",
        }
        environment = {
            "time": "当夜亥时",
            "weather": "晴夜无雨",
            "lighting": "两盏油灯，月光自画左窗入",
            "space_topology": "通铺画心、窗画左、门画右",
            "population": population,
            "ambient_life": "灯焰与呼吸自然微动",
        }
        return {
            "status": "PASS",
            "tracked_character_ids": ["CHAR-CHENJI"],
            "characters": [{"character_id": "CHAR-CHENJI", "entry_state": dict(person), "exit_state": dict(person)}],
            "environment": {"entry_state": dict(environment), "exit_state": dict(environment)},
            "authorized_boundary_changes": [],
        }

    def test_cross_scene_same_event_preserves_state_and_routes_camera_cut(self):
        previous = {
            "episode": "E54", "unit_id": "E54-VU-001", "scene_id": "E54-S01",
            "camera_plan": {"shot_scale": "MEDIUM", "camera_side": "AXIS_A"},
            "persistent_state_contract": self._persistent_state(),
            "ordered_prompt_specs": [{"space": {"global": "MAP-1", "location": "LOC-ROOM", "subspace": "BED"}, "scene_state": {"time": "当夜亥时"}}],
            "outgoing_transition_contract": {"source_terminal_state": {"space": {"global": "MAP-1", "location": "LOC-ROOM", "subspace": "BED"}}},
        }
        current = {
            "episode": "E54", "unit_id": "E54-VU-002", "scene_id": "E54-S02",
            "camera_plan": {"shot_scale": "CLOSE", "camera_side": "AXIS_A"},
            "persistent_state_contract": self._persistent_state(),
            "ordered_prompt_specs": [{"space": {"global": "MAP-1", "location": "LOC-ROOM", "subspace": "DOOR"}, "scene_state": {"time": "当夜亥时"}}],
            "incoming_transition_contract": {
                "transition_device": "REACTION_CUT",
                "plot_motivation": "切到门口人物对陈迹伤势的直接反应",
                "target_initial_state": {"space": {"global": "MAP-1", "location": "LOC-ROOM", "subspace": "DOOR"}},
            },
        }
        decision = classify_boundary(previous, current)
        self.assertEqual(decision["status"], "PASS")
        self.assertTrue(decision["same_continuous_event"])
        self.assertTrue(decision["scene_id_changed"])
        self.assertEqual(decision["boundary_class"], "MOTIVATED_CUT")
        self.assertEqual(decision["opening_source"], "CONTINUITY_DERIVED_KEYFRAME")

    def test_continuous_event_rejects_unexplained_injury_posture_and_population_reset(self):
        previous = {
            "episode": "E54", "unit_id": "E54-VU-001", "scene_id": "E54-S01",
            "persistent_state_contract": self._persistent_state(),
            "ordered_prompt_specs": [{"space": {"global": "MAP-1", "location": "LOC-ROOM"}, "scene_state": {"time": "当夜亥时"}}],
        }
        current = {
            "episode": "E54", "unit_id": "E54-VU-002", "scene_id": "E54-S02",
            "persistent_state_contract": self._persistent_state(posture="直立", injury="无伤", population="十余人在房内"),
            "ordered_prompt_specs": [{"space": {"global": "MAP-1", "location": "LOC-ROOM"}, "scene_state": {"time": "当夜亥时"}}],
            "incoming_transition_contract": {"transition_device": "GAZE_MATCH"},
        }
        decision = classify_boundary(previous, current)
        self.assertEqual(decision["status"], "FAIL")
        joined = "\n".join(decision["failures"])
        self.assertIn("characters.CHAR-CHENJI.posture", joined)
        self.assertIn("characters.CHAR-CHENJI.injury", joined)
        self.assertIn("environment.population", joined)

    def test_internal_shot_boundary_preserves_state_across_motivated_camera_cut(self):
        state = self._persistent_state()
        unit = {
            "episode": "E54", "unit_id": "E54-VU-TEST", "editorial_shot_ids": ["S1", "S2"],
            "persistent_state_contract": state,
            "shot_state_contracts": [
                {"shot_id": "S1", "persistent_state_contract": state, "camera_state": {
                    "shot_scale": "MEDIUM", "camera_position_id": "BED_FOOT",
                    "axis_id": "AXIS_A", "lens_intent": "50MM", "motion_family": "LOCKED",
                }},
                {"shot_id": "S2", "persistent_state_contract": state, "camera_state": {
                    "shot_scale": "CLOSE", "camera_position_id": "BED_SIDE",
                    "axis_id": "AXIS_A", "lens_intent": "85MM", "motion_family": "LOCKED",
                }},
            ],
            "internal_transition_contracts": [{
                "transition_mode": "REACTION_CUT",
                "camera_change_reason": "切近景观察伤者呼吸反应",
            }],
        }
        report = compile_internal_shot_boundaries(unit)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["boundaries"][0]["boundary_class"], "MOTIVATED_CUT")
        self.assertTrue(report["boundaries"][0]["state_inheritance_survives_camera_change"])

    def test_internal_shot_camera_change_without_motivation_fails(self):
        state = self._persistent_state()
        unit = {
            "episode": "E54", "unit_id": "E54-VU-TEST", "editorial_shot_ids": ["S1", "S2"],
            "persistent_state_contract": state,
            "shot_state_contracts": [
                {"shot_id": "S1", "persistent_state_contract": state, "camera_state": {
                    "shot_scale": "MEDIUM", "camera_position_id": "A", "axis_id": "AXIS_A",
                    "lens_intent": "50MM", "motion_family": "LOCKED",
                }},
                {"shot_id": "S2", "persistent_state_contract": state, "camera_state": {
                    "shot_scale": "CLOSE", "camera_position_id": "B", "axis_id": "AXIS_A",
                    "lens_intent": "85MM", "motion_family": "LOCKED",
                }},
            ],
            "internal_transition_contracts": [{"transition_mode": "HARD_CONTINUATION"}],
        }
        report = compile_internal_shot_boundaries(unit)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("UNMOTIVATED_INTERNAL_CAMERA_CHANGE" in value for value in report["failures"]))

    def test_keyframe_rejects_completion_and_extend_state(self):
        report = evaluate_task({
            "task_key": "K1",
            "source_shot_contract": {"entry_state": "人物持续挥刀", "completion_state": "刀已落下"},
            "target_completion_state": {
                "state_delta_dimensions": ["POSTURE"],
                "state_delta_evidence": {"POSTURE": {"entry": "站立", "exit": "半跪"}},
            },
        })
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("COMPLETION_STATE_FORBIDDEN" in value for value in report["failures"]))
        self.assertTrue(any("EXTEND_WORD_FORBIDDEN" in value for value in report["failures"]))

    def test_prop_state_fails_without_visual_confirmation(self):
        _, failures = compile_prop_states({"action": {"action_kind": "DIALOGUE"}, "props": [{
            "prop": "长刀",
            "state": {
                "entry": {"owner": "甲", "hand": "RIGHT", "position": "腰侧", "disposition": "HELD"},
                "exit": {"owner": "甲", "hand": "RIGHT", "position": "腰侧", "disposition": "HELD"},
            },
        }]}, source_id="U1:B1")
        self.assertIn("START_FRAME_PROP_STATE_NOT_VISUALLY_CONFIRMED:U1:B1:长刀", failures)

    def test_editorial_gate_rejects_full_media_and_uniform_long_shots(self):
        rows = [
            {"source_id": f"U{i}", "selected_in_seconds": 0, "selected_out_seconds": 6, "source_duration_seconds": 6, "selection_policy": "USE_FULL_PROVIDER_MEDIA"}
            for i in range(5)
        ]
        report = evaluate_rows(rows)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("ALL_TAIL_TRIMS_ZERO", report["failures"])

    def test_objective_window_trims_black_or_static_tail(self):
        scan = {
            "fps": 10.0,
            "duration_seconds": 2.0,
            "median_luma": 100.0,
            "median_frame_difference": 10.0,
            "luma": [100.0] * 15 + [0.0] * 5,
            "frame_difference": [0.0] + [10.0] * 14 + [0.0] * 5,
        }
        window = recommend_window(scan)
        self.assertGreater(window["tail_trim_seconds"], 0)
        self.assertEqual(window["safety_handle_seconds"], 0.25)

    def test_objective_window_trims_inactive_head_within_point_eight_seconds(self):
        scan = {
            "fps": 10.0,
            "duration_seconds": 2.0,
            "median_luma": 100.0,
            "median_frame_difference": 10.0,
            "luma": [100.0] * 20,
            "frame_difference": [0.0] * 5 + [10.0] * 15,
        }
        window = recommend_window(scan)
        self.assertEqual(window["selected_in_seconds"], 0.5)

    def test_continuing_prior_event_cannot_be_static(self):
        report = evaluate_cross_episode({
            "prior_episode_event_relation": "CONTINUING",
            "event_motion_class": "QUEUE",
            "writer_authored_continuation_action": "众人继续围攻",
        })
        self.assertEqual(report["status"], "FAIL")

    def test_execution_compiler_enforces_first_scene_cross_episode_gate(self):
        unit = {
            "unit_id": "E51-VU-X01",
            "episode": "E51",
            "model": "seedance-2.0-pro",
            "duration_seconds": 4,
            "pipeline_rectification_version": "E51_V1",
            "episode_first_scene_unit": True,
            "episode_opening_event_contract": {
                "prior_episode_event_relation": "CONTINUING",
                "event_motion_class": "QUEUE",
                "writer_authored_continuation_action": "众人继续围攻",
            },
            "camera_plan": {"shot_size": "MEDIUM", "camera_motion": "STATIC"},
            "ordered_prompt_specs": [{
                "cast": [{"character": "甲"}],
                "action": {
                    "action_kind": "PHYSICAL_ACTION",
                    "t0_seconds": 0,
                    "t1_seconds": 4,
                    "start_state": "甲站在门内",
                    "primary_action": "甲推门",
                    "completion_state": "门已打开",
                    "state_delta_dimensions": ["POSITION"],
                    "state_delta_evidence": {"POSITION": {"entry": "门内", "exit": "门口"}},
                },
                "props": [],
            }],
        }
        with self.assertRaisesRegex(ValueError, "CONTINUING_EVENT_DEGRADED_TO_STATIC"):
            compile_video_execution_plan(unit)

    def test_e51_vu010_and_vu011_fail_class_laundering(self):
        root = Path(__file__).resolve().parents[2]
        path = root / "workflow/claude_writer_agent/production/e51_v4_20260901/E51_V4_VIDEO_UNIT_GROUPING_PLAN_V1.json"
        if not path.is_file():
            self.skipTest("E51 fixture is not packaged")
        payload = json.loads(path.read_text(encoding="utf-8"))
        selected = [row for row in payload["units"] if row["unit_id"] in {"E51-VU-010", "E51-VU-011"}]
        self.assertEqual(len(selected), 2)
        for unit in selected:
            with self.subTest(unit=unit["unit_id"]), self.assertRaisesRegex(ValueError, "UNIT_CLASS_LAUNDERING"):
                compile_video_execution_plan(unit)

    def test_safety_handle_never_reintroduces_short_terminal_black_tail(self):
        scan = {
            "fps": 24.0,
            "duration_seconds": 6.0,
            "median_luma": 100.0,
            "median_frame_difference": 10.0,
            "luma": [100.0] * 141 + [0.0] * 3,
            "frame_difference": [0.0] + [10.0] * 140 + [0.0] * 3,
            "black_ranges": [{"start_seconds": 5.875, "end_seconds": 6.0}],
            "solid_color_ranges": [],
            "freeze_ranges": [{"start_seconds": 5.875, "end_seconds": 6.0}],
        }
        window = recommend_window(scan)
        self.assertLessEqual(window["selected_out_seconds"], 5.875)
        self.assertGreaterEqual(window["tail_trim_seconds"], 0.125)


if __name__ == "__main__":
    unittest.main()
