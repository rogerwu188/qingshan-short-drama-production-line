import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_agent_mistake_ledger import closed_status, valid_status


class ValidateAgentMistakeLedgerStatusTest(unittest.TestCase):
    def test_extended_statuses_are_valid(self) -> None:
        for value in (
            "OPEN_PENDING_SOURCE_DISPOSITION",
            "PARTIAL_LOCAL_FIX",
            "CLOSED_WITH_WATCHDOG",
        ):
            self.assertTrue(valid_status(value))

    def test_unrelated_status_is_invalid(self) -> None:
        self.assertFalse(valid_status("DONE"))

    def test_extended_closed_status_is_counted_closed(self) -> None:
        self.assertTrue(closed_status("CLOSED_GENERATION_STOPPED"))
        self.assertFalse(closed_status("OPEN"))


if __name__ == "__main__":
    unittest.main()
