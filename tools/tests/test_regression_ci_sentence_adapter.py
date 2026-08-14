import unittest

from tools.run_regression_ci import sentence_audit_stats


class SentenceAuditAdapterTest(unittest.TestCase):
    def test_accepts_storyboard_sentence_groups(self):
        payload = {
            "status": "PASS",
            "groups": [
                {
                    "source_id": "B01-P1",
                    "speech_present": True,
                    "cut_inside_sentence": False,
                    "complete": True,
                }
            ],
        }

        result = sentence_audit_stats(payload)

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(len(result["rows"]), 1)
        self.assertTrue(result["rows"][0]["pass"])

    def test_empty_payload_is_not_silently_passed(self):
        result = sentence_audit_stats({"status": "PASS", "groups": []})

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["rows"], [])

    def test_failed_group_uses_source_id_in_evidence(self):
        result = sentence_audit_stats(
            {
                "groups": [
                    {
                        "source_id": "B06-P2",
                        "speech_present": True,
                        "cut_inside_sentence": True,
                        "complete": False,
                    }
                ]
            }
        )

        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(
            result["failures"],
            ["sentence_incomplete_or_cut:B06-P2"],
        )


if __name__ == "__main__":
    unittest.main()
