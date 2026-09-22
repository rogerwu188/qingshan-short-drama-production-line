"""A gate FAIL is accepted only by a source-receipted line owner and exact media SHA."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "roger_gate_acceptance", ROOT / "lines/nalu/runtime/tools/roger_gate_acceptance.py")
mod = importlib.util.module_from_spec(SPEC)
sys.modules["roger_gate_acceptance"] = mod
SPEC.loader.exec_module(mod)

SHA = "a" * 64


def _order(root: Path, *, bound=SHA, issuer="owner-1", status="active",
           detectors=("a", "b"), include_receipt=True):
    verbatim = "Accept the named gate failures for this exact media file."
    row = {
        "seq": 2, "id": "ACCEPT-2", "issued_by": issuer, "status": status,
        "order": verbatim,
        "decision": {"kind": mod.KIND, "episode": "E04", "gate_id": "G",
                     "detectors": list(detectors), "media_sha256": bound},
    }
    if include_receipt:
        receipt = {
            "schema": mod.RECEIPT_SCHEMA, "status": "CONFIRMED", "issued_by": issuer,
            "order_seq": 2, "order_id": "ACCEPT-2", "verbatim": verbatim,
            "recorded_at_utc": "2026-09-20T00:00:00Z",
        }
        path = root / "accept-source.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        row["source_receipt"] = {
            "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return row


class Acceptance(unittest.TestCase):
    def test_matching_order_is_found(self):
        with tempfile.TemporaryDirectory() as d:
            row = _order(Path(d))
            self.assertIs(mod.find_acceptance(
                [row], episode="E04", gate_id="G", failing=["a"],
                media_sha256=SHA, expected_issuer="owner-1"), row)

    def test_missing_null_or_mismatched_media_binding_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for bound, current in ((None, SHA), (SHA, None), ("b" * 64, SHA)):
                row = _order(root, bound=bound)
                self.assertIsNone(mod.find_acceptance(
                    [row], episode="E04", gate_id="G", failing=["a"],
                    media_sha256=current, expected_issuer="owner-1"))

    def test_new_or_empty_failing_detector_is_not_covered(self):
        with tempfile.TemporaryDirectory() as d:
            row = _order(Path(d))
            self.assertIsNone(mod.find_acceptance(
                [row], episode="E04", gate_id="G", failing=["a", "c"],
                media_sha256=SHA, expected_issuer="owner-1"))
            self.assertIsNone(mod.find_acceptance(
                [row], episode="E04", gate_id="G", failing=[],
                media_sha256=SHA, expected_issuer="owner-1"))

    def test_wrong_issuer_status_or_unreceipted_order_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            rows = [_order(root, issuer="agent"), _order(root, status="superseded"),
                    _order(root, include_receipt=False)]
            for row in rows:
                self.assertIsNone(mod.find_acceptance(
                    [row], episode="E04", gate_id="G", failing=["a"],
                    media_sha256=SHA, expected_issuer="owner-1"))

    def test_record_keeps_fail_and_exact_binding(self):
        with tempfile.TemporaryDirectory() as d:
            row = _order(Path(d))
            rec = mod.acceptance_record(
                row, episode="E04", gate_id="G", failing=["b", "a"],
                media_sha256=SHA, gate_result_path="r.json")
            self.assertEqual(rec["gate_status_kept"], "FAIL")
            self.assertEqual(rec["accepted_detectors"], ["a", "b"])
            self.assertFalse(rec["self_issued"])
            self.assertEqual(rec["media_sha256_bound_by_order"], SHA)
            with self.assertRaises(ValueError):
                mod.acceptance_record(row, episode="E04", gate_id="G", failing=["a"],
                                      media_sha256="b" * 64, gate_result_path="r.json")

    def test_private_order_inbox_requires_current_unique_latest_seq(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); row = _order(root)
            inbox = root / "SUPERVISOR_ORDERS.json"
            inbox.write_text(json.dumps({"_schema": mod.ORDERS_SCHEMA,
                                         "latest_order_seq": 2, "orders": [row]}))
            self.assertEqual(mod._orders(inbox, expected_latest_seq=2), [row])
            self.assertEqual(mod._orders(inbox, expected_latest_seq=3), [])
            inbox.write_text(json.dumps({"_schema": mod.ORDERS_SCHEMA,
                                         "latest_order_seq": 2, "orders": [row, dict(row)]}))
            self.assertEqual(mod._orders(inbox, expected_latest_seq=2), [])

    def test_failing_detectors_from_gate_result(self):
        self.assertEqual(mod.failing_detectors({"detectors": {"a": "FAIL", "b": "PASS"}}), ["a"])
        self.assertEqual(mod.failing_detectors({"failures": ["x:FAIL:code", "y:FAIL"]}), ["x", "y"])


if __name__ == "__main__":
    unittest.main()
