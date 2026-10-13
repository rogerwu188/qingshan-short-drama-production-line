#!/usr/bin/env python3
"""A newer non-paid order must not require a hand edit of NALU_LATEST_ORDER_SEQ; a paid one must.

E11 stopped twice (2026-10-09, 2026-10-11) with nothing to decide: the line owner signed a gate
acceptance / standing rule, the inbox's latest_order_seq moved, and every reader refused until
someone edited .env.  newer_orders_self_acknowledging lets receipted, active, non-paid rows from
the expected issuer through, and keeps refusing a newer paid order, a bad receipt, a foreign
issuer or an inbox below the acknowledged seq.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import roger_gate_acceptance as R  # noqa: E402


class SelfAcknowledgingOrdersTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def row(self, seq: int, kind: str, *, issuer: str = "Roger", status: str = "active",
            paid: bool = False, receipt_ok: bool = True) -> dict:
        order_id, verbatim = f"ORDER-{seq}", f"order {seq}"
        receipt = self.root / f"r{seq}.json"
        receipt.write_text(json.dumps({
            "schema": R.RECEIPT_SCHEMA, "status": "CONFIRMED", "issued_by": issuer,
            "order_seq": seq, "order_id": order_id, "verbatim": verbatim,
            "recorded_at_utc": "2026-10-11T00:00:00Z"}), encoding="utf-8")
        sha = hashlib.sha256(receipt.read_bytes()).hexdigest()
        decision = {"kind": kind}
        if paid:
            decision["paid_requests_allowed"] = True
        return {"seq": seq, "id": order_id, "order": verbatim, "issued_by": issuer, "status": status,
                "decision": decision,
                "source_receipt": {"path": str(receipt), "sha256": sha if receipt_ok else "0" * 64}}

    def check(self, rows, acknowledged=27, issuer="Roger"):
        return R.newer_orders_self_acknowledging(rows, expected_latest_seq=acknowledged,
                                                 expected_issuer=issuer, engine_root=None)

    def test_newer_receipted_non_paid_orders_self_acknowledge(self):
        rows = [self.row(27, "PAID_PRODUCTION"), self.row(28, "GATE_FAIL_ACCEPTANCE"),
                self.row(29, "STANDING_RULE"), self.row(30, "S8_APPROVAL")]
        ok, why = self.check(rows)
        self.assertTrue(ok, why)

    def test_newer_paid_order_still_needs_acknowledgement(self):
        ok, why = self.check([self.row(27, "PAID_PRODUCTION"), self.row(28, "PAID_PRODUCTION", paid=True)])
        self.assertFalse(ok)
        self.assertIn("ORDER_SEQ_28_NEEDS_ACKNOWLEDGEMENT", why)

    def test_non_paid_kind_carrying_paid_flag_is_refused(self):
        ok, _ = self.check([self.row(28, "STANDING_RULE", paid=True)])
        self.assertFalse(ok)

    def test_bad_receipt_foreign_issuer_or_revoked_are_refused(self):
        for row in (self.row(28, "STANDING_RULE", receipt_ok=False),
                    self.row(28, "STANDING_RULE", issuer="Mallory"),
                    self.row(28, "STANDING_RULE", status="revoked")):
            ok, _ = self.check([row])
            self.assertFalse(ok)

    def test_inbox_below_acknowledged_and_missing_issuer_refuse(self):
        self.assertFalse(self.check([self.row(26, "STANDING_RULE")])[0])
        self.assertFalse(self.check([self.row(28, "STANDING_RULE")], issuer="")[0])

    def test_orders_reader_returns_rows_when_newer_rows_self_acknowledge(self):
        rows = [self.row(27, "PAID_PRODUCTION"), self.row(28, "STANDING_RULE")]
        inbox = self.root / "SUPERVISOR_ORDERS.json"
        inbox.write_text(json.dumps({"_schema": R.ORDERS_SCHEMA, "orders": rows,
                                     "latest_order_seq": 28}), encoding="utf-8")
        import os
        old = os.environ.get("NALU_LINE_OWNER_ID")
        os.environ["NALU_LINE_OWNER_ID"] = "Roger"
        try:
            self.assertEqual(len(R._orders(inbox, expected_latest_seq=27)), 2)
            rows.append(self.row(29, "PAID_PRODUCTION", paid=True))
            inbox.write_text(json.dumps({"_schema": R.ORDERS_SCHEMA, "orders": rows,
                                         "latest_order_seq": 29}), encoding="utf-8")
            self.assertEqual(R._orders(inbox, expected_latest_seq=27), [])
        finally:
            if old is None:
                os.environ.pop("NALU_LINE_OWNER_ID", None)
            else:
                os.environ["NALU_LINE_OWNER_ID"] = old


if __name__ == "__main__":
    unittest.main()
