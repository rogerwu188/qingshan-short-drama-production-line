import unittest
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from tools.script_readiness_gate import (
    evaluate_script_readiness,
    portable_bound_path,
    verify_script_readiness_report,
)
from tools.submit_giggle_task_manifest import resolve_script_gate


class ScriptReadinessGateTests(unittest.TestCase):
    def evaluate(self, payload):
        return evaluate_script_readiness(
            payload,
            {"status": "PASS", "failures": [], "report": "blind.json"},
        )

    def base(self):
        return {
            "episode": "E99",
            "review_status": "APPROVED",
            "runtime_target_seconds": {"min": 40},
            "opening_hook": {"within_seconds": 2, "conflict": "argument already underway"},
            "narrative_engine": "INTERROGATION",
            "structure": [
                {"beat_id": "B01", "target_seconds": 20, "new_information": "fact one", "power_shift": "A to B"},
                {"beat_id": "B02", "target_seconds": 20, "new_information": "fact two", "power_shift": "B to A"},
            ],
            "dialogue_draft": [
                {"dia_id": f"DIA-{index:03d}", "text": "这是六字台词呀"}
                for index in range(9)
            ],
            "burst_segments": [{"duration_seconds": 24, "max_asl_seconds": 2}],
            "relief_beats": [{"beat_id": "B01", "type": "dry_humor"}],
            "end_hook": {"line": "谁还在门外？"},
            "silence_windows": [],
        }

    def test_complete_approved_script_passes(self):
        self.assertEqual(self.evaluate(self.base())["status"], "PASS")

    def test_dialogue_count_is_not_a_density_proxy_but_review_status_still_blocks(self):
        payload = self.base()
        payload["review_status"] = "DRAFT"
        payload["dialogue_draft"] = [{"dia_id": "DIA-001", "text": "这条信息足够完整"}]
        result = self.evaluate(payload)
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(any(item.startswith("dialogue_budget_below_minimum:") for item in result["failures"]))
        self.assertIn("script_review_not_approved:DRAFT", result["failures"])

    def test_few_payload_dense_dialogue_lines_are_not_rejected_by_count(self):
        payload = self.base()
        payload["dialogue_draft"] = [{"dia_id": "DIA-001", "text": "证人刚改了口供"}]
        result = self.evaluate(payload)
        self.assertFalse(any(item.startswith("dialogue_budget_below_minimum:") for item in result["failures"]))

    def test_repeated_empty_information_and_long_silence_fail(self):
        payload = self.base()
        payload["structure"] = [{"beat_id": "B01"}, {"beat_id": "B02"}]
        payload["silence_windows"] = [
            {"duration_seconds": 9},
            {"duration_seconds": 10, "reason": "declared action"},
            {"duration_seconds": 11, "reason": "declared action"},
            {"duration_seconds": 12, "reason": "declared action"},
        ]
        result = self.evaluate(payload)
        self.assertIn("consecutive_beats_without_new_information:2", result["failures"])
        self.assertIn("long_silence_missing_reason:1:9.000", result["failures"])
        self.assertIn("too_many_long_silence_windows:4", result["failures"])

    def test_excitement_fields_are_required(self):
        payload = self.base()
        payload.pop("opening_hook")
        payload.pop("narrative_engine")
        payload.pop("burst_segments")
        payload.pop("relief_beats")
        payload.pop("end_hook")
        result = self.evaluate(payload)
        self.assertIn("opening_hook_conflict_missing", result["failures"])
        self.assertIn("narrative_engine_missing", result["failures"])
        self.assertIn("burst_segment_missing_or_invalid", result["failures"])
        self.assertIn("relief_beat_count_invalid:0", result["failures"])
        self.assertIn("concrete_suspense_end_hook_missing", result["failures"])

    def test_short_dialogue_median_fails(self):
        payload = self.base()
        for row in payload["dialogue_draft"]:
            row["text"] = "太短"
        result = self.evaluate(payload)
        self.assertIn("dialogue_median_characters_out_of_range:2", result["failures"])

    def test_structure_seconds_must_match_runtime_target(self):
        payload = self.base()
        payload["structure"][0]["target_seconds"] = 24
        result = self.evaluate(payload)
        self.assertIn(
            "structure_runtime_target_mismatch:structure=44:target=40",
            result["failures"],
        )

    def test_cli_report_hash_rejects_stale_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            beat = root / "beat.json"
            report = root / "report.json"
            beat.write_text(json.dumps(self.base()), encoding="utf-8")
            blind = root / "blind.json"
            blind.write_text(
                json.dumps(
                    {
                        "episode": "E99",
                        "status": "PASS",
                        "beat_sheet_sha256": hashlib.sha256(beat.read_bytes()).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            subprocess.run(
                [
                    "python3",
                    "tools/script_readiness_gate.py",
                    "--beat-sheet",
                    str(beat),
                    "--out",
                    str(report),
                    "--blind-tests-report",
                    str(blind),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            saved = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(saved["beat_sheet_sha256"], hashlib.sha256(beat.read_bytes()).hexdigest())
            beat.write_text(json.dumps({**self.base(), "changed": True}), encoding="utf-8")
            proc = subprocess.run(
                [
                    "python3",
                    "tools/script_readiness_gate.py",
                    "--beat-sheet",
                    str(beat),
                    "--verify-report",
                    str(report),
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("beat_sheet_sha256_mismatch", proc.stdout)

    def test_symbolic_keyword_requires_declaration(self):
        payload = self.base()
        payload["structure"][0]["new_information"] = "主角看见三个化身"
        result = self.evaluate(payload)
        self.assertIn(
            "symbolic_declaration_missing:B01",
            result["failures"],
        )

    def test_symbolic_declaration_requires_intended_read_and_three_dimensions(self):
        payload = self.base()
        payload["structure"][0].update(
            {
                "new_information": "主角看见三个化身",
                "symbolic_shot": True,
                "intended_read": "",
                "differentiation_spec": {"dimensions": ["face"]},
            }
        )
        result = self.evaluate(payload)
        self.assertIn("symbolic_intended_read_missing:B01", result["failures"])
        self.assertIn(
            "symbolic_differentiation_dimensions_below_3:B01",
            result["failures"],
        )

    def test_blind_tests_report_is_required(self):
        result = evaluate_script_readiness(self.base())
        self.assertIn("blind_tests_report_missing", result["failures"])

    def test_reusable_verifier_rejects_non_pass_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            beat = root / "beat.json"
            report = root / "report.json"
            beat.write_text(json.dumps(self.base()), encoding="utf-8")
            report.write_text(
                json.dumps(
                    {
                        "status": "FAIL",
                        "beat_sheet_sha256": hashlib.sha256(beat.read_bytes()).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            result = verify_script_readiness_report(beat, report)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("report_not_pass:FAIL", result["failures"])

    def test_project_relative_blind_binding_survives_repo_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = base / "repo_a"
            second = base / "repo_b"
            (first / "qa").mkdir(parents=True)
            beat = first / "qa" / "beat.json"
            blind = first / "qa" / "blind.json"
            report = first / "qa" / "report.json"
            beat.write_text(json.dumps(self.base()), encoding="utf-8")
            blind.write_text("blind evidence", encoding="utf-8")
            bound, kind = portable_bound_path(blind, first)
            self.assertEqual(bound, "qa/blind.json")
            self.assertEqual(kind, "PROJECT_RELATIVE")
            report.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "beat_sheet_sha256": hashlib.sha256(beat.read_bytes()).hexdigest(),
                        "blind_tests_report": bound,
                        "blind_tests_report_sha256": hashlib.sha256(blind.read_bytes()).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            first.rename(second)
            result = verify_script_readiness_report(
                second / "qa" / "beat.json",
                second / "qa" / "report.json",
                project_root=second,
            )
            self.assertEqual(result["status"], "PASS")

    def test_manifest_submission_opener_requires_script_binding(self):
        result = resolve_script_gate({}, None, None)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("script_gate_binding_missing", result["failures"])

    def test_manifest_submission_opener_rejects_stale_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            beat = root / "beat.json"
            report = root / "report.json"
            beat.write_text(json.dumps(self.base()), encoding="utf-8")
            report.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "beat_sheet_sha256": hashlib.sha256(beat.read_bytes()).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            beat.write_text(json.dumps({**self.base(), "changed": True}), encoding="utf-8")
            result = resolve_script_gate(
                {"script_gate": {"beat_sheet": str(beat), "report": str(report)}},
                None,
                None,
            )
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("beat_sheet_sha256_mismatch", result["failures"])


if __name__ == "__main__":
    unittest.main()
