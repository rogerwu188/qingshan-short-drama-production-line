import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))
sys.path.insert(0, str(ROOT))

import prompt_batch_qa as qa  # noqa: E402


class KeyframeLocationIdFormatTest(unittest.TestCase):
    def test_prefixed_ids_still_match(self):
        text = "地点：LOC-HALL｜房间：ROOM-HALL-1 … → GSM-NALU-HALL → SUBSPACE"
        self.assertEqual(qa.KF_LOCATION_RE.search(text).groups(), ("LOC-HALL", "ROOM-HALL-1"))
        self.assertEqual(qa.KF_GSM_RE.search(text).group(1), "GSM-NALU-HALL")

    def test_unprefixed_underscore_ids_match(self):
        """JA-01 E01 on 1485: ROYAL_HALL / ROYAL_HALL_1 failed every keyframe under the prefix-only patterns."""
        text = "地点：ROYAL_HALL｜房间：ROYAL_HALL_1 … → GSM-NALU-ROYAL_HALL → SUBSPACE"
        self.assertEqual(qa.KF_LOCATION_RE.search(text).groups(), ("ROYAL_HALL", "ROYAL_HALL_1"))
        self.assertEqual(qa.KF_GSM_RE.search(text).group(1), "GSM-NALU-ROYAL_HALL")


if __name__ == "__main__":
    unittest.main()
