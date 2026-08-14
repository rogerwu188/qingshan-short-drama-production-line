import unittest

from tools.dramatic_quality_gate import ADVISORS, TECHNIQUES, evaluate


def valid_report():
    beats = [
        {
            "beat_id": "B01",
            "scene_entry": "late",
            "scene_exit": "early",
            "power_shift": "A gains leverage",
            "intercut_with": "B03",
            "end_button": {"line": "The seal was already broken."},
            "unresolved_question_id": "Q01",
            "act_out": True,
            "dialogue_interruption_refs": ["DIA-002"],
        },
        {
            "beat_id": "B02",
            "scene_entry": "late",
            "scene_exit": "early",
            "power_shift": "B exposes the lie",
            "intercut_with": None,
            "end_button": {"reveal": "The witness is alive."},
            "unresolved_question_id": "Q02",
            "act_out": True,
            "dialogue_interruption_refs": [],
        },
    ]
    return {
        "episode": "E99",
        "script_sha256": "a" * 64,
        "council": {
            "advisors": [
                {"role": role, "independent": True, "analysis": "Independent analysis with enough concrete story detail."}
                for role in sorted(ADVISORS)
            ],
            "chair_verdict": "PASS",
            "experience_memory_ref": "tenants/tenant_test/projects/project_test/quality_memory/lessons.jsonl",
        },
        "runtime_seconds": 100,
        "narrative_technique_contract": {
            "cold_open": {"enabled": True, "within_seconds": 2, "event_in_progress": True},
            "dual_line_episode": True,
        },
        "beats": beats,
        "two_episode_fight_floor": {
            "qualifying_true_fight_scene_count": 1,
            "minimum_qualifying_duration_seconds": 15,
        },
    }


class DramaticQualityGateTests(unittest.TestCase):
    def test_complete_council_techniques_and_fight_floor_pass(self):
        self.assertEqual(evaluate(valid_report())["status"], "PASS")

    def test_missing_advisor_and_technique_block(self):
        report = valid_report()
        report["council"]["advisors"] = report["council"]["advisors"][:-1]
        report["beats"][0]["scene_entry"] = "early"
        result = evaluate(report)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("beat_not_late_in_early_out:1", result["failures"])

    def test_cross_cut_is_conditional_but_dangles_and_interruptions_are_not(self):
        report = valid_report()
        report["narrative_technique_contract"]["dual_line_episode"] = False
        report["beats"][0]["intercut_with"] = None
        self.assertEqual(evaluate(report)["status"], "PASS")
        report["beats"][0]["dialogue_interruption_refs"] = []
        self.assertIn("overlap_interrupt_evidence_missing", evaluate(report)["failures"])

    def test_fight_floor_skip_needs_roger(self):
        report = valid_report()
        report["two_episode_fight_floor"] = {
            "qualifying_true_fight_scene_count": 0,
            "minimum_qualifying_duration_seconds": 0,
        }
        self.assertIn(
            "fs1_true_fight_floor_not_met_and_no_roger_approval",
            evaluate(report)["failures"],
        )
        report["two_episode_fight_floor"]["roger_skip_approval_ref"] = "ROGER-E99-FS1-SKIP"
        self.assertEqual(evaluate(report)["status"], "PASS")

    def test_revise_requires_started_cascade_and_roger_for_published_impact(self):
        report = valid_report()
        report["council"]["chair_verdict"] = "REVISE"
        result = evaluate(report)
        self.assertIn("revision_cascade_targets_missing", result["failures"])
        self.assertEqual(result["next_action"], "BLOCK_GENERATION_AND_EXECUTE_REVISION_CASCADE")
        report["council"]["revision_cascade"] = {
            "status": "TASKS_CREATED",
            "affected_unproduced_episodes": ["E100"],
            "affected_published_episodes": ["E98"],
        }
        self.assertIn(
            "published_episode_revision_missing_roger_approval",
            evaluate(report)["failures"],
        )


if __name__ == "__main__":
    unittest.main()
