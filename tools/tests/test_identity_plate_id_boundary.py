"""Identity review plates match the exact asset id (field device …1324 E02: PROP-BAMBOO took PROP-BAMBOO-SPLIT's plate)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import vlm_review_protocol as vrp  # noqa: E402


class PlateIdBoundaryTest(unittest.TestCase):
    def test_exact_id_only(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d)
            names = ["E02_PROP-BAMBOO_tsk_a.png", "E02_PROP-BAMBOO-SPLIT_tsk_b.png", "PROP-BAMBOO-plate-v1.png",
                     "CHAR-LU__FRONT_NEUTRAL_HEADSHOT.png", "CHAR-LU2_tsk_c.png", "XPROP-BAMBOO_tsk_d.png"]
            for name in names:
                (folder / name).write_bytes(b"x")
            self.assertEqual([p.name for p in vrp.plates_for_asset(folder, "PROP-BAMBOO")],
                             ["E02_PROP-BAMBOO_tsk_a.png", "PROP-BAMBOO-plate-v1.png"])
            self.assertEqual([p.name for p in vrp.plates_for_asset(folder, "PROP-BAMBOO-SPLIT")],
                             ["E02_PROP-BAMBOO-SPLIT_tsk_b.png"])
            self.assertEqual([p.name for p in vrp.plates_for_asset(folder, "CHAR-LU")],
                             ["CHAR-LU__FRONT_NEUTRAL_HEADSHOT.png"])
            self.assertEqual(vrp.plates_for_asset(folder / "missing", "CHAR-LU"), [])


if __name__ == "__main__":
    unittest.main()
