"""DIRECTOR_SCORE_V1 episode evaluation (requirement section 6; T20, T21).

Offline, synthetic: no media, no model call.  Every evaluation here is built by
the real ``director_score.evaluate`` and checked on its returned record.
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from tools.collective_learning import contracts as c
from tools.collective_learning import director_score as ds

ROOT = Path(__file__).resolve().parents[2]
VIDEO = "a" * 64
RECUT = "b" * 64


def _tc(start: int = 1000, end: int = 3000, video: str = VIDEO) -> dict:
    return {"video_sha256": video, "timeline": "FINAL_CUT", "start_ms": start, "end_ms": end}


def _dims(level: int = 4, video: str = VIDEO, skip: tuple[str, ...] = ()) -> dict:
    return {
        key: {"level": level, "reasons": f"{key} 在完整带声观看中有明确的画面与声音证据",
              "evidence": [_tc(video=video)], "strengths": [f"{key} 做法有效"], "weaknesses": [f"{key} 仍可改进"]}
        for key in ds.EXPECTED_WEIGHTS if key not in skip
    }


def _evaluator(role: str = "INDEPENDENT", model: str = "model-x", prompt: str = "p1", pid: str = "rev-1") -> dict:
    return {"role": role, "model": model, "prompt_version": prompt, "process_id": pid}


FULL = {"mode": "CONTINUOUS_AV", "with_sound": True, "whole_film_pacing_pass": True}


def _evaluate(**overrides) -> dict:
    kwargs = dict(episode_id="EP07", video_sha256=VIDEO, timeline_version="tl-1", evaluator=_evaluator(),
                  coverage=FULL, dimensions=_dims())
    kwargs.update(overrides)
    return ds.evaluate(**kwargs)


class RubricTest(unittest.TestCase):
    def test_rubric_frozen_weights_and_complete_anchors(self):
        rubric = ds.load_rubric()
        self.assertEqual({d["key"]: d["weight"] for d in rubric["dimensions"]}, ds.EXPECTED_WEIGHTS)
        self.assertEqual(sum(ds.EXPECTED_WEIGHTS.values()), 100)
        self.assertTrue(c.is_sha256(rubric["rubric_sha256"]))
        for dim in rubric["dimensions"]:
            self.assertEqual(sorted(dim["anchors"]), [str(i) for i in range(6)], dim["key"])
            self.assertTrue(dim["examples"]["positive"] and dim["examples"]["negative"])
        ids = {row["id"] for row in rubric["creative_counterexamples_not_defects"]}
        self.assertEqual(ids, {"INTENTIONAL_PARTIAL_CLOSE_UP", "MOTIVATED_OFFSCREEN_DIALOGUE",
                               "PURPOSEFUL_CAMERA_MOVEMENT", "DESIGNED_DIRECT_TO_CAMERA"})

    def test_changed_weight_without_new_version_is_refused(self):
        data = json.loads(ds.RUBRIC_PATH.read_text(encoding="utf-8"))
        data["dimensions"][0]["weight"] = 25
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.json"
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(c.ContractError) as ctx:
                ds.load_rubric(path)
        self.assertIn("RUBRIC_WEIGHTS_CHANGED_WITHOUT_NEW_VERSION", ctx.exception.codes)

    def test_work_agnostic(self):
        # No production titles or character names in the shared rubric or scorer.
        banned = ("夜无疆", "青山", "秦铭", "许岳平", "梁婉清", "银藤", "Qinming", "nalu")
        for path in (ds.RUBRIC_PATH, ROOT / "tools" / "collective_learning" / "director_score.py"):
            text = path.read_text(encoding="utf-8")
            for token in banned:
                self.assertNotIn(token, text, f"{token} in {path.name}")
            self.assertIsNone(re.search(r"\bE\d{2}\b", text), path.name)


class EvaluateTest(unittest.TestCase):
    def test_formula_and_complete_status(self):
        dims = _dims(4)
        dims["narrative_causality"]["level"] = 5
        dims["sound_dialogue"]["level"] = 3
        record = _evaluate(dimensions=dims)
        expected = round(20 * 5 / 5 + 15 * 4 / 5 + 20 * 4 / 5 + 15 * 4 / 5 + 15 * 4 / 5 + 10 * 3 / 5 + 5 * 4 / 5)
        self.assertEqual(record["total"], expected)
        self.assertEqual(record["status"], "COMPLETE")
        self.assertTrue(record["comparable"])
        self.assertEqual(record["final_video_sha256"], VIDEO)
        self.assertEqual(record["rubric_version"], "DIRECTOR_SCORE_V1")
        self.assertFalse(record["authority"]["publication"])
        self.assertFalse(record["authority"]["redo_threshold"])

    def test_missing_dimension_is_not_zero_filled_or_renormalised(self):
        dims = _dims(5)
        dims["emotion_continuation"] = {"level": "UNASSESSED"}
        record = _evaluate(dimensions=dims)
        self.assertIsNone(record["total"])
        self.assertFalse(record["comparable"])
        self.assertEqual(record["missing_dimensions"], ["emotion_continuation"])
        self.assertEqual(record["status"], "PARTIAL")

    def test_assessed_dimension_needs_bound_timecode_and_reasons(self):
        dims = _dims()
        dims["pacing_information"]["evidence"] = []
        dims["sound_dialogue"]["evidence"] = [_tc(video=RECUT)]
        dims["narrative_causality"]["reasons"] = "短"
        with self.assertRaises(c.ContractError) as ctx:
            _evaluate(dimensions=dims)
        codes = ctx.exception.codes
        self.assertIn("DIMENSION_EVIDENCE_TIMECODE_REQUIRED:pacing_information", codes)
        self.assertTrue(any("TIMECODE_BOUND_TO_OTHER_VIDEO" in x for x in codes))
        self.assertIn("DIMENSION_REASONS_TOO_SHORT:narrative_causality", codes)

    def test_t20_contact_sheet_only_is_partial_and_cannot_score_av_dimensions(self):
        still = {"mode": "CONTACT_SHEET"}
        with self.assertRaises(c.ContractError) as ctx:
            _evaluate(coverage=still, dimensions=_dims())
        for key in ds.STILL_ONLY_UNASSESSABLE:
            self.assertIn(f"DIMENSION_NOT_ASSESSABLE_FROM_COVERAGE:{key}", ctx.exception.codes)
        record = _evaluate(coverage=still, dimensions=_dims(skip=ds.STILL_ONLY_UNASSESSABLE))
        self.assertEqual(record["status"], "PARTIAL")
        self.assertIsNone(record["total"])
        self.assertEqual(sorted(record["missing_dimensions"]), sorted(ds.STILL_ONLY_UNASSESSABLE))
        for key in ds.STILL_ONLY_UNASSESSABLE:
            self.assertEqual(record["dimensions"][key]["level"], "UNASSESSED")
        none = _evaluate(coverage={"mode": "NONE"}, dimensions={})
        self.assertEqual(none["status"], "UNASSESSED")

    def test_segmented_review_must_cover_every_segment_and_join(self):
        cov = {"mode": "SEGMENTED_AV", "with_sound": True, "whole_film_pacing_pass": True,
               "segments_expected": ["s1", "s2", "s3"], "segments_reviewed": ["s1", "s2", "s3"],
               "joins_expected": ["s1|s2", "s2|s3"], "joins_reviewed": ["s1|s2"]}
        self.assertIn("editing_action_continuity", ds.assess_coverage(cov)["unassessable_dimensions"])
        cov["joins_reviewed"] = ["s1|s2", "s2|s3"]
        self.assertEqual(ds.assess_coverage(cov)["status"], "FULL")
        cov["segments_reviewed"] = ["s1"]
        missing = ds.assess_coverage(cov)
        self.assertEqual(missing["status"], "PARTIAL")
        self.assertFalse(missing["total_assessable"])
        self.assertIsNone(_evaluate(coverage=cov)["total"])

    def test_accepted_imperfection_is_never_relabelled_as_fixed(self):
        with self.assertRaises(c.ContractError) as ctx:
            _evaluate(accepted_imperfections=[{"description": "轻微手部变形", "accepted_by": "line-owner",
                                               "outcome": "DEFECT_FIXED"}])
        self.assertTrue(any(code.startswith("ACCEPTED_IMPERFECTION_CANNOT_BE_RELABELLED") for code in ctx.exception.codes))
        record = _evaluate(accepted_imperfections=[{"description": "轻微手部变形", "accepted_by": "line-owner"}],
                           severe_defects=[{"severity": "P1", "description": "对白最后两个字被截断",
                                            "evidence": [_tc()], "owner_interface": "post_edit_sound"}])
        self.assertEqual(record["accepted_imperfections"][0]["outcome"], "ACCEPTED_IMPERFECTION")
        self.assertEqual(len(record["severe_defects"]), 1)


class IndependenceTest(unittest.TestCase):
    def test_self_and_independent_are_separate_records_with_disagreement(self):
        mine = _evaluate(evaluator=_evaluator(role="CREATOR_SELF", pid="producer-1"), dimensions=_dims(5))
        theirs = _evaluate(dimensions=_dims(3))
        self.assertNotEqual(mine["evaluation_id"], theirs["evaluation_id"])
        with tempfile.TemporaryDirectory() as tmp:
            archive = ds.EvaluationArchive(Path(tmp))
            archive.save(mine)
            archive.save(theirs)
            stored = archive.list("EP07")
        self.assertEqual({r["evaluator"]["role"] for r in stored}, {"CREATOR_SELF", "INDEPENDENT"})
        diff = ds.disagreement(mine, theirs)
        self.assertEqual(diff["dimensions"]["narrative_causality"]["delta"], 2)
        self.assertEqual(mine["dimensions"]["narrative_causality"]["level"], 5)  # not overwritten

    def test_blind_packet_and_round1_leak_rejected(self):
        packet = {"video": "v", "scene_intent": "x", "creator_score": 90, "target_score": 95,
                  "notes": {"fix_rationale": "because", "keep": 1}}
        blind = ds.build_blind_review_packet(packet)
        self.assertNotIn("creator_score", blind)
        self.assertNotIn("target_score", blind)
        self.assertNotIn("fix_rationale", blind["notes"])
        self.assertEqual(blind["notes"]["keep"], 1)
        self.assertEqual(len(blind["stripped_keys"]), 3)
        mine = _evaluate(evaluator=_evaluator(role="CREATOR_SELF", pid="producer-1"))
        with self.assertRaises(c.ContractError) as ctx:
            _evaluate(declared_inputs=[mine["evaluation_id"], "creator_score"],
                      creator_evaluation_ids=[mine["evaluation_id"]])
        self.assertTrue(any(x.startswith("INDEPENDENT_ROUND1_SAW_CREATOR_EVALUATION") for x in ctx.exception.codes))
        self.assertTrue(any(x.startswith("INDEPENDENT_ROUND1_SAW_CREATOR_FIELDS") for x in ctx.exception.codes))
        # Round 2 (re-check against intent) may see the creator's view.
        second = _evaluate(declared_inputs=[mine["evaluation_id"]], creator_evaluation_ids=[mine["evaluation_id"]],
                           review_round=2)
        self.assertEqual(second["review_round"], 2)


class VersioningTest(unittest.TestCase):
    def test_t21_recut_or_new_rubric_is_a_new_version_not_comparable(self):
        first = _evaluate()
        recut = _evaluate(video_sha256=RECUT, dimensions=_dims(video=RECUT), supersedes=first["evaluation_id"])
        self.assertNotEqual(first["evaluation_id"], recut["evaluation_id"])
        with tempfile.TemporaryDirectory() as tmp:
            archive = ds.EvaluationArchive(Path(tmp))
            p1, p2 = archive.save(first), archive.save(recut)
            self.assertTrue(p1.is_file() and p2.is_file())
            self.assertEqual(len(archive.list("EP07")), 2)
            changed = dict(first, total=1)
            with self.assertRaises(c.ContractError):
                archive.save(changed)
        refused = ds.compare(first, recut)
        self.assertFalse(refused["comparable"])
        self.assertIn("DIFFERENT_FINAL_VIDEO_NOT_DECLARED_RECUT", refused["reasons"])
        self.assertTrue(ds.compare(first, recut, recut=True)["comparable"])
        other_rubric = dict(first, rubric_version="DIRECTOR_SCORE_V2", rubric_sha256="c" * 64)
        self.assertIn("RUBRIC_VERSION_DIFFERS", ds.compare(first, other_rubric)["reasons"])
        other_model = _evaluate(evaluator=_evaluator(model="model-y"))
        self.assertIn("EVALUATOR_MODEL_DIFFERS", ds.compare(first, other_model)["reasons"])
        other_prompt = _evaluate(evaluator=_evaluator(prompt="p2"))
        self.assertIn("EVALUATOR_PROMPT_VERSION_DIFFERS", ds.compare(first, other_prompt)["reasons"])


class EfficiencyTest(unittest.TestCase):
    def test_denominators_and_zero_minute_cost(self):
        attempts = [
            {"unit_id": "u1", "attempt": 1, "outcome": "ACCEPTED"},
            {"unit_id": "u2", "attempt": 1, "outcome": "ACCEPTED_IMPERFECTION"},
            {"unit_id": "u3", "attempt": 1, "outcome": "REJECTED"},
            {"unit_id": "u3", "attempt": 2, "outcome": "ACCEPTED"},
            {"unit_id": "u4", "attempt": 1, "outcome": "TIMEOUT"},
            {"unit_id": "u5", "attempt": 1, "outcome": "PENDING_REVIEW"},
            {"unit_id": "u6", "attempt": 1, "outcome": "CANCELLED"},
        ]
        report = ds.efficiency_report(episode_id="EP07", attempts=attempts, confirmed_spend=1200,
                                      accepted_minutes=0, unresolved_cost_risk=40)
        fp = report["first_pass_usable"]
        self.assertEqual((fp["first_submissions"], fp["with_result"], fp["no_result_or_timeout"],
                          fp["pending_review"], fp["cancelled"], fp["reviewed"]), (6, 4, 1, 1, 1, 3))
        self.assertEqual((fp["accepted_normal"], fp["accepted_imperfection"]), (1, 1))
        self.assertAlmostEqual(fp["rate"], 2 / 3)
        self.assertAlmostEqual(fp["review_coverage"], 3 / 4)
        self.assertIsNone(report["cost"]["cost_per_usable_minute"])
        self.assertEqual(report["cost"]["cost_per_usable_minute_status"], "NOT_COMPUTABLE")
        self.assertEqual(report["cost"]["confirmed_spend"], 1200)
        empty = ds.efficiency_report(episode_id="EP07", attempts=[], confirmed_spend=0, accepted_minutes=1)
        self.assertEqual(empty["first_pass_usable"]["rate_status"], "NOT_COMPUTABLE")

    def test_wall_time_is_interval_union_not_sum(self):
        tasks = [{"start": 0, "end": 100}, {"start": 50, "end": 150}, {"start": 200, "end": 260}]
        waits = [{"category": "provider_generation", "start": 0, "end": 100},
                 {"category": "provider_generation", "start": 10, "end": 90},
                 {"category": "review", "start": "2026-01-01T00:00:00Z", "end": "2026-01-01T00:01:00Z"}]
        report = ds.efficiency_report(episode_id="EP07", attempts=[], confirmed_spend=0, accepted_minutes=0,
                                      task_intervals=tasks, wait_intervals=waits)
        self.assertEqual(report["time"]["wall_seconds"], 210)
        self.assertEqual(report["time"]["summed_task_seconds_not_wall_time"], 260)
        self.assertEqual(report["time"]["wait_seconds_by_category"]["provider_generation"], 100)
        self.assertEqual(report["time"]["wait_seconds_by_category"]["review"], 60)
        with self.assertRaises(c.ContractError):
            ds.efficiency_report(episode_id="EP07", attempts=[], confirmed_spend=0, accepted_minutes=0,
                                 wait_intervals=[{"category": "coffee", "start": 0, "end": 1}])


class PlanTest(unittest.TestCase):
    def test_plan_targets_keep_list_and_no_higher_score_demand(self):
        dims = _dims(4)
        dims["performance_interaction"].update(level=2, weaknesses=["对白段视线目标与交谈对象不一致"])
        dims["editing_action_continuity"].update(level=3)
        dims["narrative_causality"].update(level=5, strengths=["转折都有画面原因"])
        record = _evaluate(dimensions=dims)
        plan = ds.next_episode_plan([record], episode_id="EP07", next_episode_id="EP08", candidate_refs=["cand-1"])
        self.assertTrue(1 <= len(plan["targets"]) <= 3)
        first = plan["targets"][0]
        self.assertEqual(first["dimension"], "performance_interaction")
        self.assertIn(first["owner_interface"], ds.OWNER_INTERFACES)
        self.assertTrue(first["verification_method"] and first["evidence_refs"])
        self.assertIn("narrative_causality", {k["dimension"] for k in plan["keep_list"]})
        self.assertFalse(plan["score_policy"]["higher_total_required"])
        self.assertFalse(plan["authority"]["paid_redo"])
        self.assertTrue(any("SINGLE_EVALUATOR_MODEL" in u for u in plan["unconfirmed_because"]))
        md = ds.render_markdown(record, plan)
        self.assertIn("下一集改进目标", md)
        self.assertIn("保留清单", md)

    def test_plan_from_self_only_is_marked_unconfirmed(self):
        mine = _evaluate(evaluator=_evaluator(role="CREATOR_SELF", pid="producer-1"))
        plan = ds.next_episode_plan([mine], episode_id="EP07")
        self.assertTrue(any(u.startswith("ONLY_CREATOR_SELF") for u in plan["unconfirmed_because"]))
        self.assertGreaterEqual(len(plan["targets"]), 1)

    def test_latest_improvement_plan_picks_newest_earlier_episode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "runtime").mkdir()
            for ep in ("EP05", "EP07", "EP09"):
                ds.publish_plan(root, ds.next_episode_plan([_evaluate(episode_id=ep)], episode_id=ep))
            self.assertEqual(ds.latest_improvement_plan(root, "EP08")["episode_id"], "EP07")
            self.assertEqual(ds.latest_improvement_plan(root / "runtime", "EP08")["episode_id"], "EP07")
            self.assertIsNone(ds.latest_improvement_plan(root, "EP05"))
            self.assertIsNone(ds.latest_improvement_plan(root, "XX10"))


if __name__ == "__main__":
    unittest.main()
