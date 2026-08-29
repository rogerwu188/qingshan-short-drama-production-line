import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.script_density_gate_preflight import evaluate_density_gate, update_time_ledger
from tools.submit_giggle_task_manifest import resolve_script_density_gate


class ScriptDensityGatePreflightTests(unittest.TestCase):
    def setup_case(self, marker="PASS", stale=False):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        script = root / "script.json"
        reviews = root / "reviews"
        reviews.mkdir()
        script.write_text('{"episode":"E99"}\n', encoding="utf-8")
        sha = hashlib.sha256(script.read_bytes()).hexdigest()
        bound = "0" * 64 if stale else sha
        review = reviews / "E99_剧情密度审核_20260717.md"
        review.write_text(
            f"SCRIPT_DENSITY_GATE_RESULT={marker} | script_sha256={bound}\n"
            "duration_seconds=120\ntrue_event_count=10\nevent_rate_per_minute=5\n"
            "max_event_gap_seconds=18\nnon_progress_atmosphere_shot_count=2\n"
            "total_shot_count=20\nnon_progress_atmosphere_pct=10\n",
            encoding="utf-8",
        )
        return temp, script, reviews, review

    def test_pass_requires_exact_script_sha(self):
        temp, script, reviews, _ = self.setup_case()
        with temp:
            result = evaluate_density_gate("E99", script, reviews)
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(result["blocked_by"], "NONE")

    def test_stale_pass_blocks_generation(self):
        temp, script, reviews, _ = self.setup_case(stale=True)
        with temp:
            result = evaluate_density_gate("E99", script, reviews)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("density_review_script_sha256_mismatch", result["failures"])

    def test_revise_blocks_generation(self):
        temp, script, reviews, _ = self.setup_case(marker="REVISE")
        with temp:
            result = evaluate_density_gate("E99", script, reviews)
            self.assertIn("density_review_requires_revision", result["failures"])
            self.assertEqual(result["blocked_by"], "SCRIPT_DENSITY_GATE")

    def test_missing_review_blocks_generation(self):
        temp, script, reviews, review = self.setup_case()
        with temp:
            review.unlink()
            result = evaluate_density_gate("E99", script, reviews)
            self.assertIn("density_review_missing", result["failures"])

    def test_time_ledger_is_blocked_then_unblocked(self):
        temp, script, reviews, review = self.setup_case(stale=True)
        with temp:
            ledger = Path(temp.name) / "ledger.json"
            ledger.write_text(json.dumps({"blocked_by": "NONE"}), encoding="utf-8")
            failed = evaluate_density_gate("E99", script, reviews)
            update_time_ledger(ledger, failed)
            self.assertEqual(json.loads(ledger.read_text())["blocked_by"], "SCRIPT_DENSITY_GATE")
            sha = hashlib.sha256(script.read_bytes()).hexdigest()
            review.write_text(
                f"SCRIPT_DENSITY_GATE_RESULT=PASS | script_sha256={sha}\n"
                "duration_seconds=120\ntrue_event_count=10\nevent_rate_per_minute=5\n"
                "max_event_gap_seconds=18\nnon_progress_atmosphere_shot_count=2\n"
                "total_shot_count=20\nnon_progress_atmosphere_pct=10\n",
                encoding="utf-8",
            )
            passed = evaluate_density_gate("E99", script, reviews)
            update_time_ledger(ledger, passed)
            self.assertEqual(json.loads(ledger.read_text())["blocked_by"], "NONE")

    def test_giggle_submission_binding_requires_density_review(self):
        result = resolve_script_density_gate({"episode": "E99"}, None, None)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("script_density_gate_binding_missing", result["failures"])

    def test_numeric_density_failure_blocks_even_with_pass_marker(self):
        temp, script, reviews, review = self.setup_case()
        with temp:
            sha = hashlib.sha256(script.read_bytes()).hexdigest()
            review.write_text(
                f"SCRIPT_DENSITY_GATE_RESULT=PASS | script_sha256={sha}\n"
                "duration_seconds=120\ntrue_event_count=6\nevent_rate_per_minute=3\n"
                "max_event_gap_seconds=25\nnon_progress_atmosphere_shot_count=4\n"
                "total_shot_count=20\nnon_progress_atmosphere_pct=20\n",
                encoding="utf-8",
            )
            result = evaluate_density_gate("E99", script, reviews)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("true_event_rate_below_4_per_minute", result["failures"])
            self.assertIn("max_event_gap_exceeds_20_seconds", result["failures"])
            self.assertIn("non_progress_atmosphere_exceeds_15_percent", result["failures"])

    def test_registered_v3_density_json_is_accepted_with_exact_manifest_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = root / "manifest.json"
            review = root / "density.json"
            script.write_text('{"episode":"E41"}\n', encoding="utf-8")
            script_sha = hashlib.sha256(script.read_bytes()).hexdigest()
            review.write_text(json.dumps({
                "schema": "qingshan.us_drama_event_density_gate.v3",
                "episode": "E41",
                "status": "PASS",
                "manifest_sha256": script_sha,
                "observed": {
                    "structure_target_seconds": 180.0,
                    "planned_event_count": 110,
                    "max_information_gap_seconds": 8.7,
                    "non_advancing_percentage": 0.0,
                    "narrative_causal_v3": {
                        "story_move_count": 110,
                        "story_moves_per_minute": 36.667,
                    },
                },
            }), encoding="utf-8")
            result = evaluate_density_gate("E41", script, root, review)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["matched_review"]["review_schema"], "qingshan.us_drama_event_density_gate.v3")


if __name__ == "__main__":
    unittest.main()
