"""Synthetic gate smoke tests for the public StoryClaw package.

The portable release must not depend on a prior show's contract, characters,
media measurements, or episode receipts merely to prove that its core gate
functions load and fail closed.
"""

import unittest

from tools import continuity_state_contract_gate as continuity
from tools import final_cut_audience_gate as audience
from tools import script_structure_contract_gate as structure


class GenericGateSmokeTest(unittest.TestCase):
    def test_project_lexicon_is_data_driven(self):
        contract = {
            "shots": [
                {
                    "shot_id": "E01-S01-01",
                    "prompt_spec": {"dialogue": "角色甲：禁用占位词"},
                }
            ]
        }
        lexicon = {
            "schema": "qingshan.lexicon.v1",
            "world": "SYNTHETIC_TEST",
            "forbidden_terms": ["禁用占位词"],
            "canonical_names": {},
            "address_terms": {},
        }
        result = structure.check_lexicon(contract, lexicon)
        self.assertTrue(any("禁用占位词" in row for row in result["failures"]))

    def test_continuity_rejects_undeclared_life_state(self):
        contract = {
            "shots": [
                {
                    "shot_id": "E01-S01-01",
                    "scene_id": "E01-S01",
                    "prompt_spec": {
                        "cast": [{"character_id": "CHAR-A"}],
                        "props": [],
                        "dialogue": "",
                        "action": {"subject_id": "CHAR-A", "primary_action": "行走"},
                    },
                }
            ]
        }
        failures = continuity.check_life_state(contract)["failures"]
        self.assertIn("LIFE_STATE_UNDECLARED:E01-S01-01:CHAR-A", failures)

    def test_audience_report_is_required_and_sha_bound(self):
        self.assertEqual("FAIL", audience.evaluate(None)["status"])
        report = {
            "schema": audience.REPORT_SCHEMA,
            "media_sha256": "a" * 64,
            "detectors": {"hook_present": {"status": "PASS"}},
        }
        self.assertEqual("PASS", audience.evaluate(report, video_sha256="a" * 64)["status"])
        stale = audience.evaluate(report, video_sha256="b" * 64)
        self.assertIn("AUDIENCE_DETECTOR_REPORT_STALE_MEDIA_SHA", stale["failures"])


if __name__ == "__main__":
    unittest.main()
