"""Q2 auto redo skips a unit whose current clip the line owner already accepted (field device …1324 E01, 2026-11-06)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lines" / "nalu" / "runtime" / "tools"))

import q2_auto_redo  # noqa: E402

FAIL = {"status": "FAIL"}


class OwnerAcceptedSkipTest(unittest.TestCase):
    def rows(self):
        return {"E01-VU-002": {"push_in": FAIL, "media_sha256": "a" * 64},
                "E01-VU-006": {"face_count": FAIL, "media_sha256": "b" * 64}}

    def test_owner_accepted_unit_is_not_redone(self):
        out = q2_auto_redo.plan(self.rows(), {}, headroom=100, unit_cost=lambda _uid: 6,
                                owner_accepted={"E01-VU-006": 36})
        self.assertEqual([r["unit_id"] for r in out["selected"]], ["E01-VU-002"])
        self.assertEqual(out["planned_credits"], 6)
        self.assertIn({"unit_id": "E01-VU-006", "failures": ["face_count"],
                       "reason": "LINE_OWNER_ACCEPTED_THIS_CLIP", "order_seq": 36}, out["skipped"])

    def test_without_orders_behaviour_is_unchanged(self):
        out = q2_auto_redo.plan(self.rows(), {}, headroom=100, unit_cost=lambda _uid: 6)
        self.assertEqual(sorted(r["unit_id"] for r in out["selected"]), ["E01-VU-002", "E01-VU-006"])


if __name__ == "__main__":
    unittest.main()
