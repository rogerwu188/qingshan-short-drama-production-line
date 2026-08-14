import unittest

from tools.anti_padding_gate import evaluate


def script(*payloads):
    return {
        "dialogue_draft": [
            {"dia_id": f"DIA-{index:03d}", "beat_id": "B01", "payload": payload}
            for index, payload in enumerate(payloads, 1)
        ]
    }


class AntiPaddingGateTests(unittest.TestCase):
    def test_all_payloads_pass(self):
        result = evaluate(script(["new_info"], ["power_shift", "hook"]))
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["metrics"]["padding_count"], 0)

    def test_more_than_ten_percent_padding_fails(self):
        result = evaluate(script(*([["new_info"]] * 7), [], ["button"]))
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("padding_ratio_exceeds_10_percent:1/9", result["failures"])

    def test_two_consecutive_padding_lines_fail(self):
        result = evaluate(script(["new_info"], [], [], ["hook"]))
        self.assertTrue(any(item.startswith("consecutive_padding:") for item in result["failures"]))

    def test_invalid_payload_fails(self):
        result = evaluate(script(["exposition"]))
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("DIA-001:invalid_payload=exposition", result["failures"])

    def test_missing_dialogue_fails(self):
        self.assertEqual(evaluate({})["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
