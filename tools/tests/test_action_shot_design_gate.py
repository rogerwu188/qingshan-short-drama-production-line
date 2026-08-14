import unittest

from pathlib import Path
from tempfile import TemporaryDirectory

from tools.action_shot_design_gate import (
    contract_sha256,
    evaluate,
    prompt_marker,
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


if __name__ == "__main__":
    unittest.main()
