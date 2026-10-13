#!/usr/bin/env python3
"""Two pending derived openers must not ask for each other in turn.

E11 (2026-10-11): VU-013 and VU-040 both had a continuity-derived start frame pending review.
Each was submitted as its own single-item request.  The derived-Q1 branch read answers from
``latest_submitted_review`` — the NEWEST review of the kind — so the newest always covered only
the other frame, each still looked unanswered, and the pipeline re-issued requests forever:
S19-03 → S19-03 → S05-06 → S05-06.  It never reached the Q1 build, so the line owner's standing
order (seq=29, NO_FACE_PIXELS_IN_STILL) could never be applied even after it was recorded.

``merge_keyframe_answers`` must gather one answer per still across valid submitted reviews, and
must refuse (returning the missing shots) rather than build on answers it does not have.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import nalu_pipeline as P  # noqa: E402


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MergeKeyframeAnswersTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.frames = self.root / "keyframes"
        self.frames.mkdir()
        self.reviews = self.root / "reviews" / "E11"
        self.reviews.mkdir(parents=True)
        self._reviews_root, self._reviewer = P.REVIEWS_ROOT, P.REVIEWER_ID
        P.REVIEWS_ROOT, P.REVIEWER_ID = self.root / "reviews", "claude-code-nalu-vlm"
        self.ctx = SimpleNamespace(episode="E11")

    def tearDown(self):
        P.REVIEWS_ROOT, P.REVIEWER_ID = self._reviews_root, self._reviewer
        self._tmp.cleanup()

    def frame(self, shot: str) -> Path:
        path = self.frames / f"{shot}-keyframe-v1.png"
        path.write_bytes(f"bytes-of-{shot}".encode())
        return path

    def review(self, when: str, items: dict[str, Path]) -> Path:
        path = self.reviews / f"E11-keyframe-{when}_submitted.json"
        path.write_text(json.dumps({
            "kind": "keyframe", "episode": "E11", "reviewer": "claude-code-nalu-vlm",
            "review_method": "CLAUDE_VLM_STRUCTURED_REVIEW", "reviewed_at": when,
            "validation": {"status": "PASS"},
            "items": [{"item_id": shot, "answers": {}, "observed": {}, "observation": "x",
                       "defects": [], "reviewed_at": when,
                       "request_item": {"unit_id": f"U-{shot}",
                                        "media": [{"path": str(p), "sha256": _sha(p), "role": "KEYFRAME"}]}}
                      for shot, p in items.items()],
        }, ensure_ascii=False), encoding="utf-8")
        return path

    def test_two_frames_answered_one_review_each_merge_into_one_file(self):
        a, b = self.frame("E11-S19-03"), self.frame("E11-S05-06")
        self.review("20261011T121000Z", {"E11-S05-06": b})
        self.review("20261011T121500Z", {"E11-S19-03": a})
        merged, covered, missing = P.merge_keyframe_answers(self.ctx, ["E11-S19-03", "E11-S05-06"])
        self.assertEqual(missing, [])
        self.assertEqual(covered, ["E11-S05-06", "E11-S19-03"])
        payload = json.loads(Path(merged).read_text(encoding="utf-8"))
        self.assertEqual(sorted(i["item_id"] for i in payload["items"]),
                         ["E11-S05-06", "E11-S19-03"])
        self.assertEqual(len(payload["_merged_from"]["reviews"]), 2)

    def test_one_frame_answered_only_in_the_older_review_is_still_found(self):
        # this is the regression: the newest review must not hide the other frame's answer
        a, b = self.frame("E11-S19-03"), self.frame("E11-S05-06")
        self.review("20261011T121000Z", {"E11-S05-06": b})
        self.review("20261011T121500Z", {"E11-S19-03": a})
        merged, covered, missing = P.merge_keyframe_answers(self.ctx, ["E11-S05-06"])
        self.assertEqual(missing, [])
        self.assertEqual(covered, ["E11-S05-06"])

    def test_a_regenerated_frame_invalidates_its_answer(self):
        b = self.frame("E11-S05-06")
        self.review("20261011T121000Z", {"E11-S05-06": b})
        b.write_bytes(b"different bytes")
        merged, covered, missing = P.merge_keyframe_answers(self.ctx, ["E11-S05-06"])
        self.assertIsNone(merged)
        self.assertEqual(missing, ["E11-S05-06"])

    def test_no_answer_at_all_refuses_and_names_the_shot(self):
        self.frame("E11-S05-06")
        merged, covered, missing = P.merge_keyframe_answers(self.ctx, ["E11-S05-06"])
        self.assertIsNone(merged)
        self.assertEqual(missing, ["E11-S05-06"])


if __name__ == "__main__":
    unittest.main()
