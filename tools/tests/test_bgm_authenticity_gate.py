import unittest

from tools.bgm_authenticity_gate import validate_bgm_contract


class BgmAuthenticityContractTests(unittest.TestCase):
    def test_generated_bgm_contract_passes(self):
        project = {"metadata": {"bgm_contract": {
            "source_type": "GENERATED_EPISODE_BGM",
            "dialogue_duck_db": -8,
            "generation_task_id": "task-1",
            "generation_receipt": "workflow/tasks/bgm.json",
            "source_sha256": "a" * 64,
            "credit_evidence": "workflow/credit_reports/bgm.json",
        }}}
        self.assertEqual(validate_bgm_contract(project), [])

    def test_generated_bgm_ignores_unrelated_metadata(self):
        project = {"metadata": {"bgm_contract": {
            "source_type": "GENERATED_EPISODE_BGM",
            "dialogue_duck_db": -8,
            "generation_task_id": "task-1",
            "generation_receipt": "workflow/tasks/bgm.json",
            "source_sha256": "b" * 64,
            "credit_evidence": "workflow/credit_reports/bgm.json",
            "unrelated_metadata": None,
        }}}
        self.assertEqual(validate_bgm_contract(project), [])

    def test_library_fallback_needs_reason_and_similarity(self):
        project = {"metadata": {"bgm_contract": {
            "source_type": "LIBRARY_FALLBACK",
            "dialogue_duck_db": -8,
            "music_id": "MUSIC-1",
        }}}
        failures = validate_bgm_contract(project)
        self.assertIn("LIBRARY_BGM_FALLBACK_REASON_MISSING", failures)
        self.assertIn("LIBRARY_BGM_CROSS_EPISODE_SIMILARITY_NOT_PASS", failures)

    def test_missing_source_priority_contract_fails(self):
        self.assertEqual(validate_bgm_contract({}), ["BGM_SOURCE_PRIORITY_CONTRACT_MISSING"])


if __name__ == "__main__":
    unittest.main()
