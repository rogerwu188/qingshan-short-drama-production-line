import unittest

from tools.action_xuanhuan_script_gate import validate


class ActionXuanhuanGateTest(unittest.TestCase):
    def test_passes_complete_action_contract(self):
        report = validate({"episode": "E99", "structure": [{
            "beat_id": "B01",
            "payload_delivery": "ACTION_XUANHUAN",
            "action_spine": "雨中短打擒拿",
            "xuanhuan_element": "冰流显痕",
            "power_visualization": "雨幕冻结",
        }]})
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["final_lock_allowed"])

    def test_blocks_missing_fields_and_fight(self):
        report = validate({"episode": "E99", "structure": [{"beat_id": "B01"}]})
        self.assertEqual(report["status"], "FAIL")
        self.assertFalse(report["final_lock_allowed"])
        self.assertIn("missing_complete_fight_sequence", {row["check"] for row in report["failures"]})


if __name__ == "__main__":
    unittest.main()
