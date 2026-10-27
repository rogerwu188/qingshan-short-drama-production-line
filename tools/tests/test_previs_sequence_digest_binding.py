"""A previs director-review receipt is bound to the sequence it actually
reviewed, not to the episode/stage in general.

CC_H3 audit 2026-10-26 §四-缺口D: nalu_pipeline recorded receipt_sha256 of the
OUTPUT file (which includes director_review and gate metadata that change on
every run), never a snapshot of the INPUT sequence a reviewer looked at.  So
nothing could tell "this review still describes the current cut" from "the
cut changed after the review was submitted".

sequence_digest() hashes only timeline + boundaries — the parts a reviewer
actually judges — so editing a shot's camera, duration or a boundary's
transition invalidates every prior receipt for that stage automatically,
while an unrelated field (e.g. only advisories) does not.

Synthetic shots only — no episode text, task ids, media or absolute paths from
any production line.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import episode_previs as previs


def _contract(target_seconds=(3.0, 3.0)):
    return {
        "episode": "T01",
        "shots": [
            {"shot_id": "T-S01", "scene_id": "T-SC", "target_seconds": target_seconds[0]},
            {"shot_id": "T-S02", "scene_id": "T-SC", "target_seconds": target_seconds[1]},
        ],
        "scene_states": [], "character_entities": [],
        "audio_contract": {"dialogue_units": []},
    }


def _grouping(direction="NONE", family="LOCKED"):
    return {"units": [
        {"unit_id": "T-VU01", "scene_id": "T-SC", "editorial_shot_ids": ["T-S01"],
         "camera_plan": {"motion_family": "LOCKED", "motion_direction": "NONE",
                         "start_framing": "x", "end_framing": "x"}},
        {"unit_id": "T-VU02", "scene_id": "T-SC", "editorial_shot_ids": ["T-S02"],
         "camera_plan": {"motion_family": family, "motion_direction": direction,
                         "start_framing": "y", "end_framing": "y" if family == "LOCKED" else "y2"}},
    ]}


def _receipt(digest: str, reviewer: str = "test-reviewer") -> dict:
    answers = {qid: "PASS" for qid, _ in previs.DIRECTOR_QUESTIONS}
    return {"schema": previs.REVIEW_SCHEMA,
            "rounds": [{"reviewer": reviewer, "answers": answers, "sequence_digest": digest}]}


class SequenceDigestStability(unittest.TestCase):
    def test_identical_input_gives_identical_digest(self):
        contract, grouping = _contract(), _grouping()
        first = previs.build_previs(contract, grouping)
        second = previs.build_previs(contract, grouping)
        self.assertEqual(first["sequence_digest"], second["sequence_digest"])

    def test_changed_camera_changes_the_digest(self):
        contract = _contract()
        locked = previs.build_previs(contract, _grouping())
        panned = previs.build_previs(contract, _grouping(direction="LEFT_TO_RIGHT", family="PAN"))
        self.assertNotEqual(locked["sequence_digest"], panned["sequence_digest"])

    def test_changed_duration_changes_the_digest(self):
        grouping = _grouping()
        original = previs.build_previs(_contract((3.0, 3.0)), grouping)
        retimed = previs.build_previs(_contract((4.0, 3.0)), grouping)
        self.assertNotEqual(original["sequence_digest"], retimed["sequence_digest"])


class ReviewReceiptVersionBinding(unittest.TestCase):
    def test_receipt_counts_against_the_sequence_it_reviewed(self):
        previs_result = previs.build_previs(_contract(), _grouping())
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            previs.review_receipt_path(directory, "T01", "S5").write_text(
                json.dumps(_receipt(previs_result["sequence_digest"])))
            count = previs.submitted_review_count(directory, "T01", "S5", previs_result["sequence_digest"])
            self.assertEqual(count, 1)

    def test_editing_a_boundary_invalidates_the_prior_receipt(self):
        """The exact audit gap: a receipt sha of the OUTPUT file could not
        distinguish 'still describes this cut' from 'the cut changed since'."""
        contract = _contract()
        before = previs.build_previs(contract, _grouping())
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            previs.review_receipt_path(directory, "T01", "S5").write_text(
                json.dumps(_receipt(before["sequence_digest"])))
            after = previs.build_previs(contract, _grouping(direction="LEFT_TO_RIGHT", family="PAN"))
            stale_count = previs.submitted_review_count(directory, "T01", "S5", after["sequence_digest"])
            self.assertEqual(stale_count, 0, "a receipt bound to the old camera must not cover the new one")

    def test_without_a_digest_argument_legacy_callers_still_count_structurally_valid_receipts(self):
        """Backward compatibility: a caller that does not pass sequence_digest_value
        gets the pre-D behaviour (structural validity only), it is not silently 0."""
        previs_result = previs.build_previs(_contract(), _grouping())
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            previs.review_receipt_path(directory, "T01", "S5").write_text(
                json.dumps(_receipt(previs_result["sequence_digest"])))
            count = previs.submitted_review_count(directory, "T01", "S5")
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
