import unittest

from tools.anachronism_lock_gate import evaluate


def payload(elements=None):
    return {
        "period_contract": {
            "era": "架空宋明世界",
            "status": "PASS",
            "source_refs": ["world_bible://period-lock-v3"],
        },
        "units": [
            {
                "unit_id": "U01",
                "period_lock": {
                    "status": "PASS",
                    "reviewed_visible_elements": elements or ["木门", "铜锁", "油盏"],
                    "detected_anachronisms": [],
                    "evidence_refs": ["contact-sheet://U01"],
                },
            }
        ],
    }


class AnachronismLockGateTests(unittest.TestCase):
    def test_reviewed_period_elements_pass(self):
        self.assertEqual(evaluate(payload())["status"], "PASS")

    def test_known_modern_element_fails_without_roger_exception(self):
        result = evaluate(payload(["木桌", "玻璃罩煤油灯"]))
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("U01:forbidden_visible_element:玻璃罩煤油灯", result["failures"])

    def test_missing_unit_evidence_fails_closed(self):
        data = payload()
        del data["units"][0]["period_lock"]
        self.assertEqual(evaluate(data)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
