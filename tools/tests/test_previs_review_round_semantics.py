"""Previs director review counts SUBMITTED reviews, never pipeline runs.

CC_H3_提示词与跨镜头预演修复方案_20261026 §四-C / §七「审阅次数」:
a stage that was merely *run* twice has not been *reviewed* twice, so it must
stay NOT_VERIFIED.  Only a submitted review receipt advances the round count,
and unresolved items carried between rounds are never dropped.

Synthetic shots only — no episode text, task ids, media or absolute paths from
any production line.
"""

from __future__ import annotations

import unittest

from tools import episode_previs as previs


def _previs_stub() -> dict:
    return {"schema": previs.SCHEMA, "shot_count": 2, "timeline": [
        {"shot_id": "T-S01", "scene_id": "T-SC", "start": 0.0, "duration": 3.0,
         "visual": "PLACEHOLDER_CARD", "visual_source": "PLACEHOLDER", "dialogue": []},
        {"shot_id": "T-S02", "scene_id": "T-SC", "start": 3.0, "duration": 3.0,
         "visual": "PLACEHOLDER_CARD", "visual_source": "PLACEHOLDER", "dialogue": []},
    ], "machine_failures": [], "advisories": []}


class DirectorReviewRoundSemantics(unittest.TestCase):
    def test_runs_without_answers_never_close_the_loop(self):
        """Three consecutive runs with no submitted review stay unverified."""
        for run in (1, 2, 3, 4):
            review = previs.director_review_request(
                _previs_stub(), round_number=run, submitted_reviews=0)
            self.assertNotEqual(review["status"], "CLOSED_ADVISORY",
                                f"run {run} closed the loop without a submitted review")
            self.assertEqual(review["status"], "NOT_VERIFIED")

    def test_two_submitted_reviews_close_as_advisory(self):
        """The first review is requested, the second leaves only advisories."""
        first = previs.director_review_request(
            _previs_stub(), round_number=1, submitted_reviews=0)
        self.assertEqual(first["status"], "NOT_VERIFIED")

        second = previs.director_review_request(
            _previs_stub(), round_number=2, submitted_reviews=1)
        self.assertEqual(second["status"], "REVIEW_REQUESTED")

        closed = previs.director_review_request(
            _previs_stub(), round_number=3, submitted_reviews=2)
        self.assertEqual(closed["status"], "CLOSED_ADVISORY")
        self.assertEqual(closed["submitted_reviews"], 2)

    def test_carried_items_survive_the_close(self):
        open_items = ["attention_not_continuous", "camera_restart_unmotivated"]
        review = previs.director_review_request(
            _previs_stub(), round_number=3, submitted_reviews=2, prior_open=open_items)
        self.assertEqual(review["advisory_carried"], open_items)

    def test_machine_failures_are_never_waived_by_rounds(self):
        stub = _previs_stub()
        stub["machine_failures"] = [{"code": "DIALOGUE_DOES_NOT_FIT_SHOT", "shot_id": "T-S01"}]
        review = previs.director_review_request(
            stub, round_number=3, submitted_reviews=2)
        self.assertEqual(review["status"], "CLOSED_ADVISORY")
        self.assertEqual(review["machine_failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
