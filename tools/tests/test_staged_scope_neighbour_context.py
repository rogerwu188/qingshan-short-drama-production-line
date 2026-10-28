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
            segments, report = submitter.scoped_sequence_with_global_neighbours(
                _manifest(path, sha, submitted), submitted)
        self.assertEqual(len(segments), 1, "touching spans must merge into one segment")
        ids = [unit["unit_id"] for unit in segments[0]]
        self.assertEqual(ids, ["T-VU01", "T-VU02", "T-VU03",
                               "T-VU04", "T-VU05", "T-VU06"])
        self.assertEqual(report["status"], "VALIDATED_WITH_NEIGHBOURS")
        self.assertEqual(report["neighbour_units_read_only"],
                         ["T-VU01", "T-VU03", "T-VU04", "T-VU06"])
        self.assertEqual(report["submitted_unit_count"], 2)

    def test_far_apart_waves_stay_in_separate_segments(self):
        """E12-VU-012/VU-028/VU-051 (2026-10-28): three wave units 16+ apart in a
        53-unit episode must not be concatenated into one flat list.  The old
        implementation appended each unit's neighbours back to back regardless
        of distance, so unit 13's "after" neighbour landed directly next to
        unit 27's "before" neighbour -- two units the episode never places
        next to each other -- and validate_transition_sequence raised
        "E12-VU-013->E12-VU-027 transition_contract unit binding mismatch"
        although neither unit was even in the wave."""
        units = [_plan_unit(f"T-VU{i:02d}") for i in range(1, 14)]
        with tempfile.TemporaryDirectory() as tmp:
            path, sha = _write_plan(Path(tmp), units)
            # 0-based indices 1, 6, 11 -> T-VU02, T-VU07, T-VU12: each pair of
            # consecutive wave units leaves a real gap (T-VU04 and T-VU09 are
            # covered by neither neighbour span), unlike spans that merely
            # touch at a shared boundary unit.
            submitted = _projected([units[1], units[6], units[11]])
            segments, report = submitter.scoped_sequence_with_global_neighbours(
                _manifest(path, sha, submitted), submitted)
        self.assertEqual(len(segments), 3)
        self.assertEqual([unit["unit_id"] for unit in segments[0]],
                         ["T-VU01", "T-VU02", "T-VU03"])
        self.assertEqual([unit["unit_id"] for unit in segments[1]],
                         ["T-VU06", "T-VU07", "T-VU08"])
        self.assertEqual([unit["unit_id"] for unit in segments[2]],
                         ["T-VU11", "T-VU12", "T-VU13"])
        self.assertEqual(report["segment_count"], 3)
        self.assertEqual(report["submitted_unit_count"], 3)
        self.assertEqual(report["sequence_unit_count"], 9)
        # Camera-sequence validation has the same pairwise-adjacency shape as
        # the transition check; it must run per segment without raising on
        # the T-VU03 | T-VU06 and T-VU08 | T-VU11 gaps a flat concatenation
        # would have treated as adjacent (the synthetic units are all LOCKED,
        # which validate_camera_sequence never flags, so this only exercises
        # that each segment is accepted as its own list).
        from tools import grouped_camera_contract as camera
        for segment in segments:
            camera.validate_camera_sequence(segment)

    def test_adjacent_wave_units_share_one_segment(self):
        """Two wave units right next to each other must not be split or
        duplicated: their neighbour spans overlap at the shared middle unit."""
        units = [_plan_unit(f"T-VU{i:02d}") for i in range(1, 6)]
        with tempfile.TemporaryDirectory() as tmp:
            path, sha = _write_plan(Path(tmp), units)
            submitted = _projected([units[1], units[2]])
            segments, report = submitter.scoped_sequence_with_global_neighbours(
                _manifest(path, sha, submitted), submitted)
        self.assertEqual(len(segments), 1)
        ids = [unit["unit_id"] for unit in segments[0]]
        self.assertEqual(ids, ["T-VU01", "T-VU02", "T-VU03", "T-VU04"])
        self.assertEqual(report["submitted_unit_count"], 2)

    def test_neighbours_are_ordered_by_episode_not_by_subset(self):
        units = [_plan_unit(f"T-VU{i:02d}") for i in range(1, 5)]
        with tempfile.TemporaryDirectory() as tmp:
            path, sha = _write_plan(Path(tmp), units)
            submitted = _projected([units[2], units[0]])
            segments, _ = submitter.scoped_sequence_with_global_neighbours(
                _manifest(path, sha, submitted), submitted)
        self.assertEqual(len(segments), 1)
        ids = [unit["unit_id"] for unit in segments[0]]
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
        segments, report = submitter.scoped_sequence_with_global_neighbours(
            {"tasks": submitted, "staged_generation_scope": {}}, submitted)
        self.assertEqual(segments, [])
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
            segments, _ = submitter.scoped_sequence_with_global_neighbours(
                _manifest(path, sha, submitted), submitted)
        sequence = segments[0]
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
            segments, _ = submitter.scoped_sequence_with_global_neighbours(
                manifest, _projected(units[1:2]))
        sequence = segments[0]
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
