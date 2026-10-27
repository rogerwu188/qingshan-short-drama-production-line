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

import copy
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

    def test_the_opening_neighbour_keeps_its_inbound_transition(self):
        """A sliced sequence starts inside the episode, so units[0] is a real
        predecessor with a real inbound transition.  Treating it as the
        episode's first unit rejected every repair wave whose neighbour had
        one (E12 VU-053 re-entry, 2026-10-27)."""
        from tools import grouped_transition_contract as transitions

        units = [_plan_unit("T-VU01", transition={
            "from_unit_id": "T-VU00", "to_unit_id": "T-VU01",
            "boundary_id": "BND-T-VU00-T-VU01",
            "cut_reason": "REACTION_CUT", "space_relation": "SAME_SUBSPACE",
            "authorship": "DIRECTOR_AUTHORED", "transition_device": "GAZE_MATCH",
            "outgoing_handle_seconds": 0.8, "incoming_handle_seconds": 0.8,
            "plot_motivation": "the reaction reveals new information to the audience",
            "visual_bridge": "A's raised eyes carry into B's matching look",
            "action_bridge": "A looks up then B looks back",
            "sound_bridge": "room tone continues unbroken",
            "axis_strategy": "stays on axis A side",
            "continuity_intent": "no reset, no replay of the prior beat",
            "source_terminal_state": {"scene_id": "T-SC",
                                      "space": {"global": "G", "location": "L", "subspace": "S"},
                                      "camera_framing": "A holds", "camera_side": "AXIS_A",
                                      "blocking": "A seated at table"},
            "target_initial_state": {"scene_id": "T-SC",
                                     "space": {"global": "G", "location": "L", "subspace": "S"},
                                     "camera_framing": "A holds", "camera_side": "AXIS_A",
                                     "blocking": "A seated at table"},
            "anchor_semantic_requirements": {"target_visible_characters": [],
                                             "target_visible_props": [],
                                             "target_space_anchors": ["L"],
                                             "empty_establishing_frame_allowed": True},
        }), _plan_unit("T-VU02", transition={
            "from_unit_id": "T-VU01", "to_unit_id": "T-VU02",
            "boundary_id": "BND-T-VU01-T-VU02",
            "cut_reason": "REACTION_CUT", "space_relation": "SAME_SUBSPACE",
            "authorship": "DIRECTOR_AUTHORED", "transition_device": "GAZE_MATCH",
            "outgoing_handle_seconds": 0.8, "incoming_handle_seconds": 0.8,
            "plot_motivation": "the reaction reveals new information to the audience",
            "visual_bridge": "A's raised eyes carry into B's matching look",
            "action_bridge": "A looks up then B looks back",
            "sound_bridge": "room tone continues unbroken",
            "axis_strategy": "stays on axis A side",
            "continuity_intent": "no reset, no replay of the prior beat",
            "source_terminal_state": {"scene_id": "T-SC",
                                      "space": {"global": "G", "location": "L", "subspace": "S"},
                                      "camera_framing": "A holds", "camera_side": "AXIS_A",
                                      "blocking": "A seated at table"},
            "target_initial_state": {"scene_id": "T-SC",
                                     "space": {"global": "G", "location": "L", "subspace": "S"},
                                     "camera_framing": "A holds", "camera_side": "AXIS_A",
                                     "blocking": "A seated at table"},
            "anchor_semantic_requirements": {"target_visible_characters": [],
                                             "target_visible_props": [],
                                             "target_space_anchors": ["L"],
                                             "empty_establishing_frame_allowed": True},
        })]
        with tempfile.TemporaryDirectory() as tmp:
            path, sha = _write_plan(Path(tmp), units)
            submitted = _projected([units[1]])
            sequence, _ = submitter.scoped_sequence_with_global_neighbours(
                _manifest(path, sha, submitted), submitted)
        self.assertEqual(sequence[0]["unit_id"], "T-VU01")
        self.assertTrue(sequence[0].get("transition_contract"),
                        "the read-only neighbour's own inbound must survive the slice check")
        transitions.validate_transition_sequence(sequence, require_prompt_specs=True,
                                                 starts_episode=False)

    def test_a_whole_episode_run_still_rejects_an_inbound_first_unit(self):
        """The guard must stay on for normal submissions: an episode's first
        unit may not declare an inbound transition."""
        from tools import grouped_transition_contract as transitions

        units = [_plan_unit("T-VU01", transition={"cut_reason": "REACTION_CUT"})]
        with self.assertRaises(ValueError):
            transitions.validate_transition_sequence(_projected(units))

    def test_neighbour_prompt_specs_come_from_the_recorded_context_plan(self):
        """The grouping plan has no ordered_prompt_specs, and the boundary check
        binds target requirements to the neighbour's first/last beat.  Without
        the context plan every scoped wave died on 'requires ordered prompt
        specs' (E12 VU-053 re-entry, 2026-10-27)."""
        units = [_plan_unit(f"T-VU{i:02d}") for i in range(1, 4)]
        bare = copy.deepcopy(units)
        for unit in bare:
            unit.pop("ordered_prompt_specs", None)
        with tempfile.TemporaryDirectory() as tmp:
            plan_path, plan_sha = _write_plan(Path(tmp), bare)
            context_path = Path(tmp) / "T01_CONTEXT_UNITS.json"
            context_path.write_text(json.dumps({"units": units}), encoding="utf-8")
            import hashlib
            manifest = _manifest(plan_path, plan_sha, _projected(units[1:2]))
            manifest["staged_generation_scope"].update({
                "global_context_units": str(context_path),
                "global_context_units_sha256":
                    hashlib.sha256(context_path.read_bytes()).hexdigest(),
            })
            sequence, _ = submitter.scoped_sequence_with_global_neighbours(
                manifest, _projected(units[1:2]))
        self.assertTrue(sequence[0]["ordered_prompt_specs"])
        self.assertTrue(sequence[2]["ordered_prompt_specs"])

    def test_a_changed_context_plan_is_refused(self):
        units = [_plan_unit(f"T-VU{i:02d}") for i in range(1, 4)]
        bare = copy.deepcopy(units)
        for unit in bare:
            unit.pop("ordered_prompt_specs", None)
        with tempfile.TemporaryDirectory() as tmp:
            plan_path, plan_sha = _write_plan(Path(tmp), bare)
            context_path = Path(tmp) / "T01_CONTEXT_UNITS.json"
            context_path.write_text(json.dumps({"units": units}), encoding="utf-8")
            import hashlib
            stale_sha = hashlib.sha256(context_path.read_bytes()).hexdigest()
            context_path.write_text(json.dumps({"units": units[:1]}), encoding="utf-8")
            manifest = _manifest(plan_path, plan_sha, _projected(units[1:2]))
            manifest["staged_generation_scope"].update({
                "global_context_units": str(context_path),
                "global_context_units_sha256": stale_sha,
            })
            with self.assertRaises(RuntimeError):
                submitter.scoped_sequence_with_global_neighbours(
                    manifest, _projected(units[1:2]))

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
