"""A scoped repair wave must not skip the cross-unit sequence checks.

CC_H3 audit 2026-10-26 §四-缺口E: submit_giggle_video_manifest_v2 skipped
validate_camera_sequence / validate_transition_sequence / rhythm entirely
whenever a manifest carried partial_repair_scope or staged_generation_scope.
Not treating a non-contiguous subset as a contiguous episode was the right
intent, but the affected boundaries — where the batch meets the rest of the
episode — were never checked at all.

scoped_sequence_with_global_neighbours() restores the missing context from the
sha-bound global grouping plan and only ever reads those neighbours: they must
never re-enter manifest["tasks"] and never be POSTed again.

Synthetic units only — no episode text, task ids, media or production paths.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools import submit_giggle_video_manifest_v2 as submitter


def _plan_unit(uid, *, scene_id="T-SC", family="LOCKED", direction="NONE",
               framing="A holds", transition=None):
    unit = {
        "unit_id": uid, "scene_id": scene_id,
        "editorial_shot_ids": [f"{uid}-S1"],
        "duration_seconds": 4, "authorized_content_seconds": 4,
        "camera_plan": {
            "shot_scale": "MEDIUM", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
            "motion_family": family, "motion_direction": direction,
            "start_framing": framing, "end_framing": framing,
            "lens_intent": "synthetic lens intent", "axis_relation": "synthetic axis",
            "motivation": "synthetic motivation long enough",
        },
        "ordered_prompt_specs": [{"space": {"global": "G", "location": "L", "subspace": "S"},
                                  "visible_characters": [], "visible_props": []}],
    }
    if transition is not None:
        unit["transition_contract"] = transition
    return unit


def _write_plan(directory: Path, units):
    path = directory / "T01_VIDEO_UNIT_GROUPING_PLAN_V1.json"
    path.write_text(json.dumps({"units": units}), encoding="utf-8")
    import hashlib
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(plan_path: Path, sha: str, submitted):
    return {
        "episode": "T01",
        "tasks": submitted,
        "staged_generation_scope": {
            "kind": "ROLLING_WAVE_PARTIAL_READY",
            "global_grouping_plan": str(plan_path),
            "global_grouping_plan_sha256": sha,
        },
    }


def _projected(units):
    return [submitter.grouped_sequence_unit(
        {"semantic_video_unit": True, "task_key": unit["unit_id"],
         "machine_contract": unit}) for unit in units]


class NeighbourSplice(unittest.TestCase):
    def test_wave_gets_the_neighbours_it_actually_borders(self):
        units = [_plan_unit(f"T-VU{i:02d}") for i in range(1, 7)]
        with tempfile.TemporaryDirectory() as tmp:
            path, sha = _write_plan(Path(tmp), units)
            submitted = _projected([units[1], units[4]])
            sequence, report = submitter.scoped_sequence_with_global_neighbours(
                _manifest(path, sha, submitted), submitted)
        ids = [unit["unit_id"] for unit in sequence]
        self.assertEqual(ids, ["T-VU01", "T-VU02", "T-VU03",
                               "T-VU04", "T-VU05", "T-VU06"])
        self.assertEqual(report["status"], "VALIDATED_WITH_NEIGHBOURS")
        self.assertEqual(report["neighbour_units_read_only"],
                         ["T-VU01", "T-VU03", "T-VU04", "T-VU06"])
        self.assertEqual(report["submitted_unit_count"], 2)

    def test_neighbours_are_ordered_by_episode_not_by_subset(self):
        units = [_plan_unit(f"T-VU{i:02d}") for i in range(1, 5)]
        with tempfile.TemporaryDirectory() as tmp:
            path, sha = _write_plan(Path(tmp), units)
            submitted = _projected([units[2], units[0]])
            sequence, _ = submitter.scoped_sequence_with_global_neighbours(
                _manifest(path, sha, submitted), submitted)
        ids = [unit["unit_id"] for unit in sequence]
        self.assertEqual(ids, ["T-VU01", "T-VU02", "T-VU03", "T-VU04"])

    def test_submitted_tasks_are_never_rewritten_by_the_splice(self):
        units = [_plan_unit(f"T-VU{i:02d}") for i in range(1, 4)]
        with tempfile.TemporaryDirectory() as tmp:
            path, sha = _write_plan(Path(tmp), units)
            submitted = _projected([units[1]])
            manifest = _manifest(path, sha, submitted)
            before = json.dumps(manifest, sort_keys=True)
            submitter.scoped_sequence_with_global_neighbours(manifest, submitted)
            self.assertEqual(json.dumps(manifest, sort_keys=True), before,
                             "the read-only neighbours must not leak into the manifest")

    def test_a_plan_that_changed_after_build_is_refused(self):
        units = [_plan_unit(f"T-VU{i:02d}") for i in range(1, 4)]
        with tempfile.TemporaryDirectory() as tmp:
            path, sha = _write_plan(Path(tmp), units)
            units[0]["camera_plan"]["motion_family"] = "PAN"
            path.write_text(json.dumps({"units": units}), encoding="utf-8")
            submitted = _projected(units[1:2])
            with self.assertRaises(RuntimeError):
                submitter.scoped_sequence_with_global_neighbours(
                    _manifest(path, sha, submitted), submitted)

    def test_missing_plan_falls_back_to_per_task_validation_only(self):
        submitted = _projected([_plan_unit("T-VU01")])
        sequence, report = submitter.scoped_sequence_with_global_neighbours(
            {"tasks": submitted, "staged_generation_scope": {}}, submitted)
        self.assertEqual(sequence, [])
        self.assertEqual(report["status"], "MISSING_GLOBAL_PLAN")

    def test_wave_unit_absent_from_the_global_plan_is_refused(self):
        units = [_plan_unit("T-VU01")]
        with tempfile.TemporaryDirectory() as tmp:
            path, sha = _write_plan(Path(tmp), units)
            submitted = _projected([_plan_unit("T-VU99")])
            with self.assertRaises(RuntimeError):
                submitter.scoped_sequence_with_global_neighbours(
                    _manifest(path, sha, submitted), submitted)


if __name__ == "__main__":
    unittest.main()
