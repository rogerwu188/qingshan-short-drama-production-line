import json
import tempfile
import unittest
from pathlib import Path

from tools.episode_stage_gate_runner import (
    EXECUTORS,
    PHASE_GATES,
    execute_gate,
    require_release_builder_gate_admission,
)


class EpisodeStageGateRunnerTests(unittest.TestCase):
    def _canonical(self, root: Path) -> dict:
        script = root / "script.md"
        script.write_text("canonical", encoding="utf-8")
        import hashlib
        return {
            "canonical_script": str(script),
            "canonical_script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
        }

    def test_phase_contract_has_no_duplicate_gates_within_each_phase(self):
        for phase, gates in PHASE_GATES.items():
            self.assertEqual(len(gates), len(set(gates)), phase)

    def test_script_density_entry_forwards_writer_receipt(self):
        optional = EXECUTORS["SCRIPT-US-DRAMA-EVENT-DENSITY"]["optional_arguments"]
        self.assertIn(("--writer-receipt", "writer_receipt"), optional)

    def test_missing_evidence_fails_closed_without_invocation(self):
        with tempfile.TemporaryDirectory() as temp:
            result = execute_gate(
                "SCRIPT-COUNCIL-DRAMATIC-QUALITY", "E32", self._canonical(Path(temp)), Path(temp)
            )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["invoked"])
        self.assertIn(
            "required_evidence_missing:dramatic_quality_report", result["failures"]
        )

    def test_mechanical_default_gate_is_actually_invoked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            canonical = self._canonical(root)
            plan = root / "plan.json"
            plan.write_text(
                json.dumps(
                    {
                        "source_script_sha256": canonical["canonical_script_sha256"],
                        "units": [
                            {"unit_id": "U1", "duration_seconds": 8},
                            {"unit_id": "U2", "duration_seconds": 9},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = execute_gate(
                "MECHANICAL-DEFAULT-META-GATE",
                "E32",
                {**canonical, "unit_plan": str(plan)},
                root / "out",
            )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["invoked"])
        self.assertEqual(result["implementation_status"], "PASS")

    def test_causality_gate_is_actually_invoked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            canonical = self._canonical(root)
            plan = root / "causality.json"
            plan.write_text(
                json.dumps(
                    {
                        "source_script_sha256": canonical["canonical_script_sha256"],
                        "units": [{
                            "unit_id": "U01",
                            "causality": {
                                "applicable": True,
                                "purpose": "封住出口",
                                "intended_effect": "对手不能逃离",
                                "preconditions": ["门已关闭"],
                                "mechanism_chain": ["门闩落入搭扣", "门框承受推力"],
                                "visible_causality": "推门时门框颤动但门不开",
                                "viewer_read": "出口确实被封住",
                                "counterfactual_test": {
                                    "opponent_can_bypass": False,
                                    "reasoning": "没有第二出口且门闩在内侧",
                                },
                                "prop_function_status": "PASS",
                                "evidence_refs": ["storyboard://U01"],
                            },
                        }]
                    }
                ),
                encoding="utf-8",
            )
            result = execute_gate(
                "COMMON-SENSE-CAUSALITY-COUNTERFACTUAL",
                "E32",
                {**canonical, "causality_plan": str(plan)},
                root / "out",
            )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["invoked"])

    def test_period_lock_gate_is_actually_invoked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            canonical = self._canonical(root)
            plan = root / "period.json"
            plan.write_text(
                json.dumps(
                    {
                        "source_script_sha256": canonical["canonical_script_sha256"],
                        "period_contract": {
                            "era": "架空宋明世界",
                            "status": "PASS",
                            "source_refs": ["world-bible://period-v3"],
                        },
                        "units": [{
                            "unit_id": "U01",
                            "period_lock": {
                                "status": "PASS",
                                "reviewed_visible_elements": ["木门", "铜锁", "油盏"],
                                "detected_anachronisms": [],
                                "evidence_refs": ["contact-sheet://U01"],
                            },
                        }],
                    }
                ),
                encoding="utf-8",
            )
            result = execute_gate(
                "PERIOD-ANACHRONISM-LOCK",
                "E32",
                {**canonical, "period_lock_plan": str(plan)},
                root / "out",
            )
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["invoked"])

    def test_script_evidence_from_another_sha_is_not_invoked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = root / "plan.json"
            plan.write_text(json.dumps({"source_script_sha256": "0" * 64, "units": []}), encoding="utf-8")
            result = execute_gate(
                "MECHANICAL-DEFAULT-META-GATE",
                "E32",
                {**self._canonical(root), "unit_plan": str(plan)},
                root / "out",
            )
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["invoked"])
        self.assertTrue(any(row.startswith("script_binding_sha_mismatch") for row in result["failures"]))

    def test_twelve_second_fight_unit_used_as_one_edit_shot_is_blocked_by_runner(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            canonical = self._canonical(root)
            script = Path(canonical["canonical_script"])
            script.write_text("△【打斗·起·12s】完整打斗生成单元。", encoding="utf-8")
            import hashlib
            canonical["canonical_script_sha256"] = hashlib.sha256(script.read_bytes()).hexdigest()
            plan = root / "fight-plan.json"
            plan.write_text(json.dumps({
                "episode": "E41",
                "fight_scenes": [{
                    "scene_id": "14-7",
                    "units": [{
                        "unit_id": "14-7-U1",
                        "generated_duration": 12.0,
                        "scene_id": "14-7",
                        "light_key": "LOCKED",
                        "axis_line": "A_TO_B",
                        "eyeline": "TARGET",
                        "cut_plan": [{
                            "duration": 12.0,
                            "phase": "burst",
                            "cut_reason": "ACTION_BEAT",
                            "action": "整段生成片未拆分",
                            "cut_reason_note": "整段生成片未拆分",
                        }],
                    }],
                }],
            }), encoding="utf-8")
            result = execute_gate(
                "ACTION-SHOT-DESIGN-AND-STATE-HANDOFF",
                "E41",
                {**canonical, "fight_cut_plan": str(plan)},
                root / "out",
            )
            payload = json.loads(Path(result["output"]).read_text(encoding="utf-8"))
        self.assertTrue(result["invoked"])
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["implementation_status"], "BLOCK")
        self.assertTrue(any(row["gate"] == "F1_PLAN_PRESENT" for row in payload["findings"]))

    def test_release_builder_guard_fails_before_runner_when_bundle_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "RELEASE_EDIT_GATE_EVIDENCE_BUNDLE_MISSING"):
                require_release_builder_gate_admission(
                    episode="E99",
                    evidence_bundle=Path(temp) / "missing.json",
                    out_dir=Path(temp) / "out",
                )


if __name__ == "__main__":
    unittest.main()
