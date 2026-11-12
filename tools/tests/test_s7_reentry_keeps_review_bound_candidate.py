"""S7 re-entry keeps the candidate the independent final reviewer is bound to (field device …1284 E06, 2026-11-12).

S7 re-renders on every entry.  When the re-render is not byte-identical (12090d <-> 84afdc), replacing the candidate
made the submitted final-audience review stale before S7 could read it, so the episode could never leave S7.
With unchanged source bindings the review-bound candidate is kept; changed sources still replace it.
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


class ReviewBoundCandidateTests(unittest.TestCase):
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
        self.ctx = SimpleNamespace(p=self.p, episode="E99")
        self._old_reviews = self.mod.REVIEWS_ROOT
        self.mod.REVIEWS_ROOT = root / "reviews"
        (root / "reviews" / "E99").mkdir(parents=True)
        self.p.final_candidate.write_bytes(b"reviewed-cut")
        self.reviewed_sha = _sha(self.p.final_candidate)
        (root / "reviews" / "E99" / "final_audience_request.json").write_text(
            json.dumps({"request_id": "E99-FINAL", "media": {"sha256": self.reviewed_sha}}), encoding="utf-8")

    def tearDown(self) -> None:
        self.mod.REVIEWS_ROOT = self._old_reviews
        self.tmp.cleanup()

    def _manifest(self, bindings: dict) -> None:
        (self.p.assembly / "E99_FINAL_CANDIDATE_CHAIN.json").write_text(json.dumps(
            {"final_candidate_sha256": self.reviewed_sha, "source_bindings": bindings}), encoding="utf-8")

    def test_same_sources_keep_the_review_bound_candidate(self) -> None:
        bindings = self.mod.s7_candidate_source_bindings(self.ctx)
        self._manifest(bindings)
        kept = self.mod._review_bound_candidate_to_retain(self.ctx, bindings, "f" * 64)
        self.assertIsNotNone(kept)
        self.assertEqual(kept["final_candidate_sha256"], self.reviewed_sha)
        self.assertEqual(kept["rerender_sha256"], "f" * 64)

    def test_changed_unit_clip_replaces_the_candidate(self) -> None:
        self._manifest(self.mod.s7_candidate_source_bindings(self.ctx))
        (self.p.video_media / "E99-VU-001.mp4").write_bytes(b"unit-1-redo")
        bindings = self.mod.s7_candidate_source_bindings(self.ctx)
        self.assertIsNone(self.mod._review_bound_candidate_to_retain(self.ctx, bindings, "f" * 64))

    def test_legacy_manifest_or_unbound_request_replaces_the_candidate(self) -> None:
        bindings = self.mod.s7_candidate_source_bindings(self.ctx)
        self._manifest({})
        self.assertIsNone(self.mod._review_bound_candidate_to_retain(self.ctx, bindings, "f" * 64))
        self._manifest(bindings)
        (self.mod.REVIEWS_ROOT / "E99" / "final_audience_request.json").write_text(
            json.dumps({"media": {"sha256": "0" * 64}}), encoding="utf-8")
        self.assertIsNone(self.mod._review_bound_candidate_to_retain(self.ctx, bindings, "f" * 64))

    def test_identical_rerender_needs_no_retention(self) -> None:
        bindings = self.mod.s7_candidate_source_bindings(self.ctx)
        self._manifest(bindings)
        self.assertIsNone(self.mod._review_bound_candidate_to_retain(self.ctx, bindings, self.reviewed_sha))

    def test_chain_wires_the_retention_before_replacing(self) -> None:
        src = (ROOT / "lines/nalu/runtime/tools/nalu_pipeline.py").read_text(encoding="utf-8")
        body = src[src.index("def s7_post_level_audio_chain("):src.index("FINAL_RELEASE_GATE_ID =")]
        self.assertLess(body.index("_review_bound_candidate_to_retain("), body.index("_park_superseded(p.final_candidate)"))
        self.assertIn('"source_bindings": bindings', body)


if __name__ == "__main__":
    unittest.main()
