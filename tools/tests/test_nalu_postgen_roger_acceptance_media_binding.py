"""Regression test for apply_roger_postgen_acceptance's media-binding lookup.

record_supervisor_order.py only ever writes decision.media_sha256_by_item
(per-item), never the singular decision.media_sha256 -- but
apply_roger_postgen_acceptance called roger_gate_acceptance.find_acceptance()
and .acceptance_record() without media_item_id, so _bound_sha() always
checked the singular key and never matched a real order. No S6
GATE_FAIL_ACCEPTANCE order could ever actually apply. Fixed by passing
media_item_id=unit_id at both call sites.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
sys.path.insert(0, str(TOOLS))


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


qa = load("post_generation_qa_runner")


class ApplyRogerPostgenAcceptanceMediaByItem(unittest.TestCase):
    def _write_order(self, root: Path, *, unit_id: str, media_sha: str, detector: str):
        verbatim = "Accept the sample-rate failure for this exact media file."
        receipt = {
            "schema": "qingshan.line_owner_order_source_receipt.v1", "status": "CONFIRMED",
            "issued_by": "Roger", "order_seq": 1, "order_id": "ACCEPT-1",
            "verbatim": verbatim, "recorded_at_utc": "2026-09-25T00:00:00Z",
        }
        receipt_path = root / "receipt.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        order = {
            "seq": 1, "id": "ACCEPT-1", "issued_by": "Roger", "status": "active",
            "order": verbatim,
            "decision": {
                "kind": "GATE_FAIL_ACCEPTANCE", "episode": "E99", "gate_id": qa.POSTGEN_GATE_ID,
                "detectors": [detector],
                # This is the ONLY shape record_supervisor_order.py ever writes.
                "media_sha256_by_item": {unit_id: media_sha},
            },
            "source_receipt": {"path": str(receipt_path),
                               "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest()},
        }
        inbox = root / "SUPERVISOR_ORDERS.json"
        inbox.write_text(json.dumps({"_schema": "supervisor_orders_v1", "latest_order_seq": 1,
                                     "orders": [order]}), encoding="utf-8")
        return inbox

    def test_a_real_recorder_shaped_order_is_actually_applied(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            media_sha = "b" * 64
            inbox = self._write_order(root, unit_id="E99-VU-001", media_sha=media_sha,
                                      detector="E99-VU-001:sample_rate:FAIL")
            rows = [{
                "unit_id": "E99-VU-001", "verdict": "REJECT",
                "reasons": ["sample_rate:FAIL"], "media_sha256": media_sha,
            }]
            with patch.dict(os.environ, {
                "NALU_SUPERVISOR_ORDERS_PATH": str(inbox),
                "NALU_LATEST_ORDER_SEQ": "1",
                "NALU_LINE_OWNER_ID": "Roger",
            }):
                result = qa.apply_roger_postgen_acceptance("E99", rows, root)
            self.assertEqual(result["accepted_unit_ids"], ["E99-VU-001"])
            self.assertEqual(result["still_rejected_unit_ids"], [])
            self.assertEqual(rows[0]["verdict"], "ADMIT")
            self.assertEqual(rows[0]["engine_verdict"], "REJECT")  # the measurement itself stays honest
            self.assertEqual(rows[0]["reasons"], [])

    def test_wrong_unit_id_binding_still_leaves_it_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            media_sha = "c" * 64
            inbox = self._write_order(root, unit_id="E99-VU-002", media_sha=media_sha,
                                      detector="E99-VU-001:sample_rate:FAIL")
            rows = [{
                "unit_id": "E99-VU-001", "verdict": "REJECT",
                "reasons": ["sample_rate:FAIL"], "media_sha256": media_sha,
            }]
            with patch.dict(os.environ, {
                "NALU_SUPERVISOR_ORDERS_PATH": str(inbox),
                "NALU_LATEST_ORDER_SEQ": "1",
                "NALU_LINE_OWNER_ID": "Roger",
            }):
                result = qa.apply_roger_postgen_acceptance("E99", rows, root)
            self.assertEqual(result["accepted_unit_ids"], [])
            self.assertEqual(result["still_rejected_unit_ids"], ["E99-VU-001"])
            self.assertEqual(rows[0]["verdict"], "REJECT")


if __name__ == "__main__":
    unittest.main()
