import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "repair_periodic_duplicate_frames.py"
SPEC = importlib.util.spec_from_file_location("repair_periodic_duplicate_frames", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RepairPeriodicDuplicateFramesTest(unittest.TestCase):
    def test_uses_only_frames_from_confirmed_chains(self):
        chains = [
            {
                "verification_status": "CONFIRMED_MPDECIMATE",
                "mpdecimate_matching_frames": [14, 10, 14],
            },
            {
                "verification_status": "UNCONFIRMED",
                "mpdecimate_matching_frames": [99],
            },
        ]
        self.assertEqual(MODULE.confirmed_chain_frames(chains), [10, 14])


if __name__ == "__main__":
    unittest.main()
