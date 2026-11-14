#!/usr/bin/env python3
"""S7: a FAILed H3 burned-text cover verify is carried by a line-owner order bound to the subtitled picture.

Fleet 2026-11-14 (a device at E13 S7): the verify read residual text inside the bar and stopped the episode
with H3_BURNED_TEXT_STILL_VISIBLE; no order could carry it, so the episode stayed blocked at every re-run.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

OWNER = "owner-1"


def _order(sha: str, *, gate: str = "H3-BURNED-TEXT-COVER", issued_by: str = OWNER) -> dict:
    return {"seq": 7, "id": "ORDER-7", "issued_by": issued_by, "status": "active", "order": "accept",
            "decision": {"kind": "GATE_FAIL_ACCEPTANCE", "episode": "E99", "gate_id": gate,
                         "detectors": ["H3_BURNED_TEXT_STILL_VISIBLE"],
                         "media_sha256_by_item": {"H3_BURNED_TEXT_STILL_VISIBLE": sha}}}


class BurnedTextCoverOrderAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.np = importlib.import_module("nalu_pipeline")
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = Path(self._tmp.name)
        self.assembly = tmp / "assembly"
        self.assembly.mkdir()
        self.subbed = self.assembly / "E99_picture_native_subbed.mp4"
        self.subbed.write_bytes(b"subtitled picture")
        self.sha = hashlib.sha256(b"subtitled picture").hexdigest()
        self.check = self.assembly / "E99_H3_BURNED_TEXT_COVER_CHECK.json"
        self.check.write_text(json.dumps({"status": "FAIL", "text_inside_bar_not_the_caption": [{"t": 1.0}]}),
                              encoding="utf-8")
        self.said: list[str] = []
        self.ctx = SimpleNamespace(episode="E99", p=SimpleNamespace(assembly=self.assembly),
                                   authority={"orders_path": tmp / "orders.json", "latest_order_seq": 7,
                                              "line_owner_id": OWNER},
                                   authority_blockers=[], say=self.said.append)
        self.res = SimpleNamespace(details={}, receipts=[])

    def _run(self, orders: list[dict]) -> dict | None:
        step = {"name": "s7_burned_text_verify", "exit_code": 2}
        with mock.patch.object(self.np._rga, "_orders", return_value=orders), \
                mock.patch.object(self.np._rga, "_receipt_valid", return_value=True):
            out = self.np.s7_burned_text_cover_acceptance(self.ctx, self.res, self.subbed, self.check, step)
        self.step = step
        return out

    def test_order_bound_to_the_subtitled_picture_carries_the_fail(self) -> None:
        record = self._run([_order(self.sha)])
        self.assertIsNotNone(record)
        self.assertEqual(record["gate_status_kept"], "FAIL")
        self.assertEqual(record["media_sha256"], self.sha)
        self.assertEqual(self.step["accepted_by_line_owner_order"], 7)
        path = self.assembly / "final_qa" / "E99_H3_BURNED_TEXT_COVER_ACCEPTANCE.json"
        self.assertTrue(path.is_file())
        self.assertIn(str(path), self.res.receipts)
        self.assertEqual(json.loads(self.check.read_text(encoding="utf-8"))["status"], "FAIL")

    def test_no_order_keeps_the_block_and_names_what_an_order_must_bind(self) -> None:
        self.assertIsNone(self._run([]))
        hint = self.res.details["burned_text_cover_acceptance_hint"]
        self.assertEqual(hint["gate_id"], "H3-BURNED-TEXT-COVER")
        self.assertEqual(hint["media_sha256"], self.sha)
        self.assertFalse((self.assembly / "final_qa").exists())

    def test_order_for_another_picture_gate_or_issuer_is_not_used(self) -> None:
        self.assertIsNone(self._run([_order("0" * 64)]))
        self.assertIsNone(self._run([_order(self.sha, gate="FINAL-CUT-AUDIENCE-DETECTORS")]))
        self.assertIsNone(self._run([_order(self.sha, issued_by="someone-else")]))

    def test_a_verify_without_a_fail_report_is_never_carried(self) -> None:
        self.check.write_text(json.dumps({}), encoding="utf-8")
        self.assertIsNone(self._run([_order(self.sha)]))
        self.check.unlink()
        self.assertIsNone(self._run([_order(self.sha)]))
        self.assertNotIn("burned_text_cover_acceptance", self.res.details)

    def test_stage_s7_blocks_only_when_no_order_carries_the_fail(self) -> None:
        src = (ROOT / "lines/nalu/runtime/tools/nalu_pipeline.py").read_text(encoding="utf-8")
        body = src[src.index("def stage_s7("):src.index("def s7_qa(")]
        self.assertIn('if verify_step["exit_code"] != 0 and s7_burned_text_cover_acceptance(', body)


if __name__ == "__main__":
    unittest.main()
