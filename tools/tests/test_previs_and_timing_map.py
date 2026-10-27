"""Plan §4 / §6 / §10 items 7, 8, 12, 13: previs and the timing map.  Free and offline."""

import unittest

from tools.episode_previs import MAX_REVIEW_ROUNDS, build_previs, director_review_request
from tools.unit_timing_map import build_timing_map
from tools.video_unit_grouping_gate import evaluate as grouping_gate


def _contract(dialogue=None, target=3.0):
    return {
        "episode": "E99",
        "character_entities": [{"character_id": "CHAR-A"}, {"character_id": "CHAR-B"}],
        "shots": [
            {"shot_id": "E99-S01-01", "scene_id": "E99-S01", "target_seconds": target},
            {"shot_id": "E99-S01-02", "scene_id": "E99-S01", "target_seconds": target},
        ],
        "scene_states": [{"scene_id": "E99-S01", "source_events": ["EV-1"]}],
        "audio_contract": {"dialogue_units": dialogue or []},
    }


def _grouping(*unit_shots, durations=None):
    return {"units": [{"unit_id": f"E99-VU-{i:03d}", "editorial_shot_ids": list(shots),
                       "duration_seconds": (durations or [6] * len(unit_shots))[i - 1]}
                      for i, shots in enumerate(unit_shots, 1)]}


class PrevisMachineChecksTest(unittest.TestCase):
    def test_unauthorised_repeated_dialogue_is_caught(self):          # §10.7
        lines = [{"shot_id": "E99-S01-01", "speaker_id": "CHAR-A", "text": "甲：我们走吧"},
                 {"shot_id": "E99-S01-02", "speaker_id": "CHAR-A", "text": "甲：我们走吧"}]
        report = build_previs(_contract(lines))
        self.assertIn("DIALOGUE_REPEATED_WITHOUT_REASON", [f["code"] for f in report["machine_failures"]])

    def test_a_declared_repeat_is_allowed(self):
        lines = [{"shot_id": "E99-S01-01", "speaker_id": "CHAR-A", "text": "甲：我们走吧"},
                 {"shot_id": "E99-S01-02", "speaker_id": "CHAR-A", "text": "甲：我们走吧",
                  "repeat_reason": "回声：剧本写明重复"}]
        self.assertEqual(build_previs(_contract(lines))["status"], "PASS")

    def test_dialogue_that_cannot_fit_its_shot_is_caught(self):     # §10.7
        lines = [{"shot_id": "E99-S01-01", "speaker_id": "CHAR-A", "text": "甲：" + "长" * 40}]
        report = build_previs(_contract(lines, target=2.0))
        self.assertIn("DIALOGUE_DOES_NOT_FIT_SHOT", [f["code"] for f in report["machine_failures"]])

    def test_estimated_duration_is_never_labelled_measured(self):    # §10.8
        lines = [{"shot_id": "E99-S01-01", "speaker_id": "CHAR-A", "text": "甲：好"}]
        report = build_previs(_contract(lines))
        line = report["timeline"][0]["dialogue"][0]
        self.assertEqual(line["duration_source"], "ESTIMATED")
        self.assertEqual(report["measured_dialogue_lines"], 0)

    def test_unregistered_speaker_and_unit_gaps_are_caught(self):
        lines = [{"shot_id": "E99-S01-01", "speaker_id": "CHAR-GHOST", "text": "某：喂喂喂"}]
        report = build_previs(_contract(lines), _grouping(["E99-S01-01"]))
        codes = [f["code"] for f in report["machine_failures"]]
        self.assertIn("DIALOGUE_SPEAKER_NOT_REGISTERED", codes)
        self.assertIn("SHOT_NOT_IN_ANY_UNIT", codes)

    def test_missing_director_intent_is_advisory_not_blocking(self):
        report = build_previs(_contract())
        self.assertEqual(report["status"], "PASS")
        self.assertIn("SCENE_INTENT_NOT_DECLARED", [a["code"] for a in report["advisories"]])


class DirectorReviewLoopTest(unittest.TestCase):                     # §10.13
    def test_rounds_stop_after_the_limit_without_regeneration(self):
        previs = build_previs(_contract())
        first = director_review_request(previs, round_number=1, submitted_reviews=0)
        self.assertEqual(first["status"], "NOT_VERIFIED",
                         "a run with no submitted review must not read as reviewed")
        self.assertFalse(first["blocking"])
        request = director_review_request(previs, round_number=2, submitted_reviews=1)
        self.assertEqual(request["status"], "REVIEW_REQUESTED")
        self.assertFalse(request["blocking"])
        closed = director_review_request(previs, round_number=3, submitted_reviews=MAX_REVIEW_ROUNDS,
                                         prior_open=["pace"])
        self.assertEqual(closed["status"], "CLOSED_ADVISORY")
        self.assertEqual(closed["advisory_carried"], ["pace"])
        self.assertNotIn("questions", closed)

    def test_round_limit_never_waives_a_machine_failure(self):
        lines = [{"shot_id": "E99-S01-01", "speaker_id": "CHAR-A", "text": "甲：" + "长" * 40}]
        previs = build_previs(_contract(lines, target=1.0))
        director_review_request(previs, round_number=MAX_REVIEW_ROUNDS + 1,
                                submitted_reviews=MAX_REVIEW_ROUNDS)
        self.assertEqual(previs["status"], "FAIL")


class TimingMapTest(unittest.TestCase):
    def test_one_line_two_units_is_a_doubled_line(self):              # §6
        lines = [{"shot_id": "E99-S01-01", "text": "甲：我们走吧"},
                 {"shot_id": "E99-S01-02", "text": "甲：我们走吧"}]
        report = build_timing_map(_contract(lines), _grouping(["E99-S01-01"], ["E99-S01-02"]))
        self.assertIn("DIALOGUE_GENERATED_BY_TWO_UNITS", [f["code"] for f in report["failures"]])

    def test_request_beyond_story_is_recorded_not_hidden(self):
        report = build_timing_map(_contract(target=2.0), _grouping(["E99-S01-01", "E99-S01-02"], durations=[6]))
        self.assertEqual([n["code"] for n in report["notes"]], ["REQUEST_EXCEEDS_STORY"])
        self.assertEqual(report["units"][0]["returned_source"], "NOT_YET_GENERATED")

    def test_units_without_a_tail_dependency_stay_parallel(self):     # §10.12
        tasks = {"tasks": [
            {"unit_id": "E99-VU-001"},
            {"unit_id": "E99-VU-002", "action_sequence_contract": {"depends_on_task": "E99-VU-001"},
             "predecessor_tail_frame": "tail.png"},
        ]}
        report = build_timing_map(_contract(), _grouping(["E99-S01-01"], ["E99-S01-02"]),
                                  transaction_manifest=tasks)
        self.assertEqual(report["tail_dependent_units"], ["E99-VU-002"])
        self.assertEqual(report["independent_units"], 1)

    def test_cut_beyond_the_media_is_caught(self):
        report = build_timing_map(_contract(), _grouping(["E99-S01-01"]),
                                  edit_decisions=[{"unit_id": "E99-VU-001", "in": 2, "out": 1}])
        self.assertIn("CUT_INTERVAL_EMPTY", [f["code"] for f in report["failures"]])


class GroupingHardBoundsTest(unittest.TestCase):
    def _plan(self, duration, reason="CONTINUOUS_CAUSAL_ACTION"):
        return {
            "schema": "qingshan.video_unit_grouping_plan.v1",
            "editorial_shot_count": 1, "video_unit_count": 1,
            "derivation": {"unit_count_selected_in_advance": False, "formula_division_used": False},
            "preferred_duration_seconds": {"minimum": 4, "maximum": 6},
            "duration_policy_seconds": {"minimum": 4, "maximum": 8},
            "units": [{"unit_id": "U1", "editorial_shot_ids": ["S1"], "duration_seconds": duration,
                       "duration_exception_reason": reason}],
        }

    def test_an_exception_reason_cannot_carry_a_unit_past_the_hard_maximum(self):
        report = grouping_gate(self._plan(9))
        self.assertIn("unit_exceeds_hard_maximum:U1:9>8", report["failures"])

    def test_inside_the_hard_window_the_reason_still_works(self):
        self.assertEqual(grouping_gate(self._plan(8))["status"], "PASS")


if __name__ == "__main__":
    unittest.main()


class UpstreamChangeRevokesReviewTest(unittest.TestCase):           # §10.5
    """An edited keyframe prompt must not keep the PASS its old bytes earned."""

    def test_editing_a_reviewed_prompt_puts_the_batch_on_hold(self):
        import hashlib, json, tempfile
        from pathlib import Path
        from tools.episode_prompt_batch_gate import evaluate

        def sha(p):
            return hashlib.sha256(Path(p).read_bytes()).hexdigest()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kf = root / "kf.txt"; kf.write_text("v1", encoding="utf-8")
            vp = root / "vp.txt"; vp.write_text("video", encoding="utf-8")
            qa = root / "qa.json"
            qa.write_text(json.dumps({
                "status": "PASS", "unit_id": "U1", "execution_id": "X",
                "keyframe_prompt_sha256": sha(kf), "video_prompt_sha256": sha(vp),
                "scope": "PLANNED_PROMPTS_AND_CROSS_UNIT_CONTINUITY",
                "cross_unit_continuity_checked": True}), encoding="utf-8")
            row = {"unit_id": "U1",
                   "keyframe_prompt": {"path": "kf.txt", "sha256": sha(kf)},
                   "video_prompt": {"path": "vp.txt", "sha256": sha(vp)},
                   "prompt_qa": {"path": "qa.json", "sha256": sha(qa)}}
            (root / "batch.json").write_text(json.dumps({"execution_id": "X", "rows": [row]}), encoding="utf-8")
            config = {"required": True, "unit_ids": ["U1"], "manifest_ref": "batch.json"}
            self.assertEqual(evaluate(root, config, execution_id="X", unit_id="U1")["status"], "PASS")

            kf.write_text("v2 — upstream end state changed", encoding="utf-8")
            report = evaluate(root, config, execution_id="X", unit_id="U1")
            self.assertEqual(report["status"], "HOLD")
            self.assertIn("MISSING_OR_STALE_ARTIFACT:U1:keyframe_prompt", report["failures"])


class PortableManifestFilesAreTrackedTest(unittest.TestCase):
    """A required portable file that .gitignore swallows never reaches a release.

    /configs/* is ignored with an allow-list; a new policy file added without
    its allow-line is committed nowhere, and code that reads it falls back to
    "off" without any error.  This happened once; this test makes it loud.
    """

    def test_every_required_file_is_tracked_or_not_ignored(self):
        import json, subprocess
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        if not (root / ".git").exists():
            self.skipTest("not a git checkout")
        manifest = json.loads((root / "configs/PORTABLE_CORE_MANIFEST.json").read_text(encoding="utf-8"))
        ignored = []
        for relative in manifest["required_files"]:
            result = subprocess.run(["git", "check-ignore", "-q", relative], cwd=root)
            if result.returncode == 0:
                ignored.append(relative)
        self.assertEqual(ignored, [], "required portable files are git-ignored")
