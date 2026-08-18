import unittest
import hashlib

from pathlib import Path
from tempfile import TemporaryDirectory

from tools.action_shot_design_gate import (
    contract_sha256,
    evaluate,
    prompt_marker,
    prompt_spatial_block,
    validate_tail_chained_submission,
    validate_task_bindings,
)


def action_shot(shot_id="S1", entry="READY", exit_state="CONTACT_DONE", family="locked_side"):
    return {
        "shot_id": shot_id,
        "action_unit": True,
        "visual_tier": "CORE",
        "information_beats": ["paper figure catches the falling beam"],
        "camera": {
            "family": family,
            "moves": [],
            "axis": "left-to-right 180-degree axis",
            "screen_direction": "beam falls top-right to bottom-left",
            "contact_readable": True,
        },
        "primary_contacts": [{
            "pre_state": "beam is falling and paper arms are still below it",
            "actor": "paper figure",
            "action": "raises both arms",
            "contact_point": "paper palms against the underside of the beam",
            "force_direction": "beam downward, paper arms upward",
            "force_feedback": "paper elbows buckle and feet slide back",
            "result_state": "beam stops above the escape lane",
        }],
        "result_read_seconds": 0.6,
        "reset_or_replay_allowed": False,
        "continuity_group": "FIGHT",
        "entry_state_token": entry,
        "exit_state_token": exit_state,
    }


def add_spatial_action(shot, canonical_script_path=None):
    script_action = "陈迹从门槛内侧前移一步，以刀背格开右侧来箭后停在阿栓身前"
    if canonical_script_path is None:
        canonical_script_path = Path(__file__)
        script_action = "def add_spatial_action(shot, canonical_script_path=None):"
    shot["spatial_action_contract"] = {
        "episode_global_space_map_id": "EGSM-E40-WANGFU-001",
        "global_space_map_id": "GSM-WANGFU-001",
        "subspace_id": "SUBSPACE-R06A",
        "room_id": "ROOM-WANGFU-HALL",
        "angle_id": "ANGLE-SOUTH-WIDE",
        "axis_id": "AXIS-ASHUAN-ARROW",
        "script_action": script_action,
        "script_action_sha256": __import__("hashlib").sha256(script_action.encode("utf-8")).hexdigest(),
        "canonical_script_path": str(canonical_script_path),
        "canonical_script_sha256": hashlib.sha256(Path(canonical_script_path).read_bytes()).hexdigest(),
        "start_state_token": shot["entry_state_token"],
        "end_state_token": shot["exit_state_token"],
        "subspace_polygon": [[0, 0], [10, 0], [10, 10], [0, 10]],
        "non_traversable_obstacles": [{"element_id": "LONG-TABLE", "polygon": [[7, 7], [9, 7], [9, 9], [7, 9]]}],
        "trajectories": [{
            "entity_id": "CHAR-CHENJI", "trajectory_type": "DEFENSIVE_STEP",
            "start": [3, 3], "blocking_start_position": [3, 3],
            "waypoints": [[4, 4]], "end": [5, 5], "declared_end_position": [5, 5],
            "end_state": "between arrow and Ashuan", "zone_transition": False,
            "allowed_obstacle_contact_ids": [],
        }],
        "camera_readability": "PASS",
        "occlusion_constraints": ["contact point remains visible"],
        "escape_and_counter_paths": ["left rear remains open for Ashuan"],
        "declared_portal_ids": [],
    }
    return shot


class ActionShotDesignGateTests(unittest.TestCase):
    def test_atomic_contact_and_matching_handoff_pass(self):
        first = action_shot()
        second = action_shot("S2", "CONTACT_DONE", "WALL_OPEN", "locked_front")
        report = evaluate({"episode": "E00", "shots": [first, second]})
        self.assertEqual(report["status"], "PASS")

    def test_two_primary_contacts_fail(self):
        shot = action_shot()
        shot["primary_contacts"].append(dict(shot["primary_contacts"][0]))
        report = evaluate({"shots": [shot]})
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("primary_contact_count_exceeded" in value for value in report["failures"]))

    def test_non_core_action_and_state_reset_fail(self):
        first = action_shot()
        first["visual_tier"] = "NON_CORE"
        second = action_shot("S2", "RESET_TO_OLD_COMPOSITION", "DONE", "locked_front")
        report = evaluate({"shots": [first, second]})
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("action_shot_must_be_core_80" in value for value in report["failures"]))
        self.assertTrue(any("continuity_handoff_mismatch" in value for value in report["failures"]))

    def test_repeated_camera_family_and_information_overload_fail(self):
        shots = []
        for index in range(6):
            shot = action_shot(f"S{index}", "READY" if index == 0 else f"X{index}", f"X{index + 1}")
            if index:
                shot["entry_state_token"] = shots[-1]["exit_state_token"]
            shot["information_beats"] = ["a", "b", "c"]
            shots.append(shot)
        report = evaluate({"shots": shots})
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("camera_family_episode_share_exceeded" in value for value in report["failures"]))
        self.assertTrue(any("information_load_exceeded" in value for value in report["failures"]))

    def test_provider_prompt_must_embed_exact_design_contract(self):
        shot = action_shot()
        plan = {"shots": [shot]}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            prompt = root / "prompt.txt"
            prompt.write_text(prompt_marker(shot) + "\nlocked action prompt\n", encoding="utf-8")
            task = {
                "task_key": "T1",
                "tool_type": "video_generation",
                "action_design_shot_id": "S1",
                "action_design_contract_sha256": contract_sha256(shot),
                "prompt_path": "prompt.txt",
            }
            self.assertEqual(validate_task_bindings(plan, [task], root), [])
            prompt.write_text("unbound prompt\n", encoding="utf-8")
            self.assertTrue(any(
                "not_compiled_into_prompt" in value
                for value in validate_task_bindings(plan, [task], root)
            ))

    def test_tail_chain_allows_one_task_with_materialized_exact_tail(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            tail = root / "accepted-tail.png"
            tail.write_bytes(b"accepted tail")
            task = {
                "task_key": "B03",
                "generation_schedule_mode": "TAIL_CHAINED_SERIAL",
                "depends_on_task": "B02",
                "action_sequence_contract": {
                    "chain_id": "FIRE",
                    "sequence_index": 3,
                    "predecessor_tail_frame_ref": "accepted-tail.png",
                },
                "reference_image_sequence": [{
                    "role": "EXACT_PREDECESSOR_ACCEPTED_TAIL_AND_START_FRAME",
                    "path": "accepted-tail.png",
                }],
            }
            self.assertEqual(validate_tail_chained_submission([task], root), [])

    def test_tail_chain_rejects_parallel_or_generic_start(self):
        task = {
            "task_key": "B03",
            "generation_schedule_mode": "TAIL_CHAINED_SERIAL",
            "depends_on_task": "B02",
            "action_sequence_contract": {
                "chain_id": "FIRE",
                "sequence_index": 3,
                "predecessor_tail_frame_ref": "missing.png",
            },
            "reference_image_sequence": [{"role": "ACTION_STATE_ANCHOR", "path": "generic.png"}],
        }
        second = dict(task, task_key="B04")
        failures = validate_tail_chained_submission([task, second], Path("/tmp"))
        self.assertTrue(any("parallel_submission_forbidden" in value for value in failures))
        self.assertTrue(any("exact_predecessor_tail_not_materialized" in value for value in failures))
        self.assertTrue(any("first_reference_is_not_exact_predecessor_tail" in value for value in failures))

    def test_e40_action_requires_space_derived_trajectory(self):
        shot = action_shot()
        report = evaluate({"episode": "E40", "shots": [shot]})
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("spatial_action_contract_missing" in value for value in report["failures"]))

    def test_space_derived_trajectory_passes(self):
        shot = add_spatial_action(action_shot())
        report = evaluate({"episode": "E40", "shots": [shot]})
        self.assertEqual(report["status"], "PASS", report["failures"])

    def test_trajectory_crossing_fixed_obstacle_fails(self):
        shot = add_spatial_action(action_shot())
        trajectory = shot["spatial_action_contract"]["trajectories"][0]
        trajectory.update({
            "start": [3, 8], "blocking_start_position": [3, 8],
            "waypoints": [], "end": [9.5, 8], "declared_end_position": [9.5, 8],
        })
        report = evaluate({"episode": "E40", "shots": [shot]})
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("crosses_non_traversable:LONG-TABLE" in value for value in report["failures"]))

    def test_action_prompt_binding_checks_same_subspace_ids(self):
        shot = add_spatial_action(action_shot())
        plan = {"episode": "E40", "shots": [shot]}
        with TemporaryDirectory() as directory:
            root = Path(directory)
            prompt = root / "prompt.txt"
            prompt.write_text(prompt_marker(shot) + "\n" + prompt_spatial_block(shot), encoding="utf-8")
            task = {
                "task_key": "T1", "tool_type": "video_generation",
                "action_design_shot_id": "S1",
                "action_design_contract_sha256": contract_sha256(shot),
                "prompt_path": "prompt.txt",
                "episode_global_space_map_id": "WRONG",
                "global_space_map_id": "GSM-WANGFU-001",
                "room_id": "ROOM-WANGFU-HALL", "angle_id": "ANGLE-SOUTH-WIDE",
                "subspace_layout": {"subspace_id": "SUBSPACE-R06A", "axis_id": "AXIS-ASHUAN-ARROW"},
                "prompt_contract": {"source_action": shot["spatial_action_contract"]["script_action"]},
                "blocking": {"characters": [{"character_id": "CHAR-CHENJI", "position": [3, 3]}], "props": []},
                "action_end_blocking": {"characters": [{"character_id": "CHAR-CHENJI", "position": [5, 5]}], "props": []},
            }
            failures = validate_task_bindings(plan, [task], root)
            self.assertTrue(any("spatial_action_episode_global_space_map_id_mismatch" in value for value in failures))

    def test_e40_variant_name_still_requires_spatial_action(self):
        report = evaluate({"episode": "E40-REMAKE-V1", "shots": [action_shot()]})
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("spatial_action_contract_missing" in value for value in report["failures"]))

    def test_e40_non_combat_shot_still_requires_spatial_motion_contract(self):
        shot = action_shot()
        shot["action_unit"] = False
        report = evaluate({"episode": "E40", "shots": [shot]})
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("spatial_action_contract_missing" in value for value in report["failures"]))

    def test_canonical_action_must_be_verbatim(self):
        shot = add_spatial_action(action_shot())
        # Build the invalid action at runtime so the literal does not appear in
        # this test file, which is also the canonical fixture for passing cases.
        invalid_action = "这句不在" + "权威剧本里" + "-runtime-only"
        shot["spatial_action_contract"]["script_action"] = invalid_action
        shot["spatial_action_contract"]["script_action_sha256"] = hashlib.sha256(
            invalid_action.encode("utf-8")
        ).hexdigest()
        report = evaluate({"episode": "E40", "shots": [shot]})
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("not_verbatim_in_canonical" in value for value in report["failures"]))


if __name__ == "__main__":
    unittest.main()
