"""S7 candidate → deliverable promotion (Roger 2026-10-30, E12 成片审看 item 0).

A cut that has not passed every S7 gate is never written to deliverables/.  S7 levels,
measures and QA-checks ``assembly/<EP>_final_candidate_9x16.mp4``; only a full PASS
byte-copies it (sha-verified) to ``deliverables/<EP>/<EP>_final_9x16.mp4``.
"""
from __future__ import annotations

import hashlib
import importlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _paths(tmp: Path) -> SimpleNamespace:
    assembly = tmp / "assembly"
    deliver = tmp / "deliverables" / "E99"
    assembly.mkdir(parents=True)
    return SimpleNamespace(
        assembly=assembly, deliver=deliver,
        final_candidate=assembly / "E99_final_candidate_9x16.mp4",
        ad_tail_candidate=assembly / "E99_final_candidate_9x16_AD.mp4",
        final_mp4=deliver / "E99_final_9x16.mp4",
        ad_tail_video=deliver / "E99_final_9x16_AD.mp4",
    )


class PromoteFinalCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("nalu_pipeline")

    def test_candidate_is_copied_byte_exact_and_ad_variant_alongside(self) -> None:
        with TemporaryDirectory() as tmp:
            p = _paths(Path(tmp))
            p.final_candidate.write_bytes(b"final-bytes-v1")
            p.ad_tail_candidate.write_bytes(b"ad-bytes-v1")
            out = self.mod.promote_final_candidate(p)
            self.assertTrue(p.final_mp4.is_file() and p.ad_tail_video.is_file())
            self.assertEqual(_sha(p.final_mp4), _sha(p.final_candidate))
            self.assertEqual(out["final_video_sha256"], _sha(p.final_candidate))
            self.assertEqual(out["final_video_action"], "COPIED")
            self.assertEqual(out["ad_tail_video_action"], "COPIED")
            # the candidate stays where S7 measured it — the deliverable is a copy, not a move
            self.assertTrue(p.final_candidate.is_file())

    def test_missing_candidate_raises_and_writes_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            p = _paths(Path(tmp))
            with self.assertRaises(FileNotFoundError):
                self.mod.promote_final_candidate(p)
            self.assertFalse(p.final_mp4.exists())

    def test_identical_deliverable_is_left_alone_and_different_one_is_parked(self) -> None:
        with TemporaryDirectory() as tmp:
            p = _paths(Path(tmp))
            p.final_candidate.write_bytes(b"same")
            p.deliver.mkdir(parents=True)
            p.final_mp4.write_bytes(b"same")
            out = self.mod.promote_final_candidate(p)
            self.assertEqual(out["final_video_action"], "ALREADY_IN_PLACE")
            # a repaired candidate supersedes the old deliverable; the old bytes are parked, never deleted
            p.final_candidate.write_bytes(b"repaired")
            out = self.mod.promote_final_candidate(p)
            self.assertEqual(out["final_video_action"], "COPIED")
            self.assertEqual(p.final_mp4.read_bytes(), b"repaired")
            parked = Path(out["final_video_superseded_parked"])
            self.assertTrue(parked.is_file())
            self.assertEqual(parked.read_bytes(), b"same")
            self.assertIn("__superseded_", parked.name)

    def test_no_ad_candidate_means_no_ad_deliverable(self) -> None:
        with TemporaryDirectory() as tmp:
            p = _paths(Path(tmp))
            p.final_candidate.write_bytes(b"x")
            out = self.mod.promote_final_candidate(p)
            self.assertNotIn("ad_tail_video", out)
            self.assertFalse(p.ad_tail_video.exists())


class StageS7UsesCandidatePathsTests(unittest.TestCase):
    """Static guard: the S7 measurement chain must reference the candidate, never the deliverable."""

    def test_s7_argv_binds_the_candidate(self) -> None:
        src = (ROOT / "lines/nalu/runtime/tools/nalu_pipeline.py").read_text(encoding="utf-8")
        start = src.index("def stage_s7(")
        end = src.index("def s7_qa(")
        body = src[start:end]
        for needle in ('"--output-video", p.final_candidate',
                       '"--output", p.final_candidate',
                       '"--media", p.final_candidate',
                       '"--final", p.final_candidate',
                       '"--video", p.final_candidate',
                       "promote_final_candidate(p)"):
            self.assertIn(needle, body, needle)
        # the deliverable path appears in S7 only as the promotion target / report label
        for forbidden in ('"--output-video", p.final_mp4', '"--output", p.final_mp4', '"--media", p.final_mp4',
                          '"--final", p.final_mp4', '"--video", p.final_mp4'):
            self.assertNotIn(forbidden, body, forbidden)

    def test_tail_ad_is_built_from_the_candidate(self) -> None:
        src = (ROOT / "lines/nalu/runtime/tools/nalu_pipeline.py").read_text(encoding="utf-8")
        start = src.index("def _s7_tail_ad_body(")
        end = src.index("def s7_final_audience_review(")
        body = src[start:end]
        self.assertIn('"--content", p.final_candidate', body)
        self.assertIn('"--out", p.ad_tail_candidate', body)
        self.assertNotIn("p.final_mp4", body)


if __name__ == "__main__":
    unittest.main()
