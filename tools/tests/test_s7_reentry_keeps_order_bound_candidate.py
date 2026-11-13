"""S7 re-entry keeps the candidate a line-owner acceptance order is bound to (field device …0736 E08, 2026-11-13).

The S7 gates that FAIL before the independent review request exists (loudness, camera motion, audience
detectors) continue only on an order bound to the candidate's exact sha256.  Every S7 entry re-renders, and the
re-render is not byte-identical, so the order recorded for the previous candidate never matched the new one and
the stage returned FINAL_CUT_AUDIENCE_DETECTORS_FAIL again, forever.  With unchanged source bindings the
order-bound candidate is kept; changed sources or an order for another cut still replace it.
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class OrderBoundCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("nalu_pipeline")
        self.tmp = TemporaryDirectory()
        root = Path(self.tmp.name)
        assembly, video, preprod = root / "assembly", root / "video", root / "preprod"
        for d in (assembly, video, preprod):
            d.mkdir()
        (video / "E99-VU-001.mp4").write_bytes(b"unit-1")
        (preprod / "contract.json").write_text("{}", encoding="utf-8")
        self.p = SimpleNamespace(
            assembly=assembly, video_media=video, q2_index=preprod / "q2.json", contract=preprod / "contract.json",
            grouping_plan=preprod / "grouping.json", editorial=preprod / "editorial.json",
            final_candidate=assembly / "E99_final_candidate_9x16.mp4")
        self.orders_path = root / "orders.json"
        self.ctx = SimpleNamespace(p=self.p, episode="E99", authority_blockers=[],
                                   authority={"orders_path": self.orders_path, "latest_order_seq": 7})
        self._old_reviews = self.mod.REVIEWS_ROOT
        self.mod.REVIEWS_ROOT = root / "reviews"   # no final-audience request exists yet
        self.p.final_candidate.write_bytes(b"accepted-cut")
        self.accepted_sha = _sha(self.p.final_candidate)

    def tearDown(self) -> None:
        self.mod.REVIEWS_ROOT = self._old_reviews
        self.tmp.cleanup()

    def _manifest(self, bindings: dict) -> None:
        (self.p.assembly / "E99_FINAL_CANDIDATE_CHAIN.json").write_text(json.dumps(
            {"final_candidate_sha256": self.accepted_sha, "source_bindings": bindings}), encoding="utf-8")

    def _orders(self, *, sha: str, episode: str = "E99", status: str = "active", by_item: bool = True) -> None:
        decision = {"kind": "GATE_FAIL_ACCEPTANCE", "episode": episode, "gate_id": "FINAL-CUT-AUDIENCE-DETECTORS",
                    "detectors": ["loudness"]}
        decision.update({"media_sha256_by_item": {"loudness": sha}} if by_item else {"media_sha256": sha})
        self.orders_path.write_text(json.dumps({
            "_schema": "supervisor_orders_v1", "latest_order_seq": 7,
            "orders": [{"seq": 7, "id": "ORD-7", "status": status, "issued_by": "owner", "order": "accept",
                        "decision": decision}]}), encoding="utf-8")

    def _retain(self, new_sha: str = "f" * 64):
        return self.mod._review_bound_candidate_to_retain(
            self.ctx, self.mod.s7_candidate_source_bindings(self.ctx), new_sha)

    def test_same_sources_keep_the_order_bound_candidate(self) -> None:
        self._manifest(self.mod.s7_candidate_source_bindings(self.ctx))
        for by_item in (True, False):
            self._orders(sha=self.accepted_sha, by_item=by_item)
            kept = self._retain()
            self.assertIsNotNone(kept)
            self.assertEqual(kept["final_candidate_sha256"], self.accepted_sha)
            self.assertEqual(kept["rerender_sha256"], "f" * 64)
            self.assertEqual(kept["acceptance_order_seq"], 7)
            self.assertEqual(kept["reason"], "S7_REENTRY_SAME_SOURCES_ORDER_BOUND_CANDIDATE")

    def test_no_order_for_this_candidate_replaces_it(self) -> None:
        self._manifest(self.mod.s7_candidate_source_bindings(self.ctx))
        self.assertIsNone(self._retain())                      # no inbox at all
        self._orders(sha="0" * 64)
        self.assertIsNone(self._retain())                      # bound to another cut
        self._orders(sha=self.accepted_sha, episode="E98")
        self.assertIsNone(self._retain())                      # another episode
        self._orders(sha=self.accepted_sha, status="revoked")
        self.assertIsNone(self._retain())                      # not active

    def test_changed_unit_clip_or_legacy_manifest_replaces_the_candidate(self) -> None:
        self._orders(sha=self.accepted_sha)
        self._manifest({})
        self.assertIsNone(self._retain())
        self._manifest(self.mod.s7_candidate_source_bindings(self.ctx))
        (self.p.video_media / "E99-VU-001.mp4").write_bytes(b"unit-1-redo")
        self.assertIsNone(self._retain())

    def test_authority_blockers_give_no_retention(self) -> None:
        self._manifest(self.mod.s7_candidate_source_bindings(self.ctx))
        self._orders(sha=self.accepted_sha)
        self.ctx.authority_blockers = ["ORDER_INBOX_STALE"]
        self.assertIsNone(self._retain())


if __name__ == "__main__":
    unittest.main()
