"""Script-stage review: anonymised synopsis, no PASS, INCOMPLETE until the writer answers.

The narrative fixture is invented here; it deliberately contains the labelling
that must never reach a reviewer (episode number, version, chapter, season
position) so the anonymiser is actually exercised.
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"

NARRATIVE = """# 《Fixture》E14 叙事权威 v3（narrative canonical）

集号 E14｜片名《关门》｜目标时长 108 秒
授权 SUPERVISOR_ORDERS seq=99
唯一剧情来源 原著第 14 章《关门》
季位 第2季第14集
★观众已知，本集不得复证：门在夜里锁过

本集终局：她终于进了门。

## E14-S01｜LOC-GATE｜TIME-NIGHT｜线A

她走到门口，门已经关了。

守卫：天黑之前不开。

## E14-S02｜LOC-SIDE-DOOR｜TIME-NIGHT｜线A

侧门虚掩着，她推了一下。
"""


def _boot():
    """Import the nalu tools with a throwaway runtime root (no repo state is read)."""
    tmp = tempfile.mkdtemp(prefix="nalu-script-review-")
    env = {"NALU_ENGINE_ROOT": str(ROOT), "NALU_RUNTIME_ROOT": tmp}
    with patch.dict(os.environ, env):
        for name in list(sys.modules):
            if name in {"nalu_paths", "nalu_qa_common", "nalu_series_scope",
                        "vlm_review_protocol", "script_review", "visual_review_policy"}:
                sys.modules.pop(name)
        sys.path.insert(0, str(TOOLS))
        modules = {
            "vrp": importlib.import_module("vlm_review_protocol"),
            "sr": importlib.import_module("script_review"),
            "common": importlib.import_module("nalu_qa_common"),
        }
    return modules, Path(tmp)


MODULES, RUNTIME_ROOT = _boot()
VRP = MODULES["vrp"]
SR = MODULES["sr"]
COMMON = MODULES["common"]


def answers(request: dict, request_sha: str, *, exclude: str | None = None,
            points: list[dict] | None = None, reviewer: str | None = None) -> dict:
    payload = {
        "schema": COMMON.SCHEMA_ANSWERS,
        "request_path": "x",
        "request_sha256": request_sha,
        "reviewer": reviewer or COMMON.REVIEWER_ID,
        "reviewed_at": "2026-11-01T00:00:00Z",
        "items": [{
            "item_id": "SYNOPSIS",
            "media_reviewed": [],
            "answers": {key: (None if key == exclude else "PASS")
                        for key in request["questionnaire"]},
            "observed": {"observed_read_scenes": ["S01", "S02"]},
            "observation": "Two scenes: a shut gate, then a side door that gives.",
            "defects": [],
            "confusion_points": points if points is not None else [],
        }],
    }
    return payload


class AnonymiseTests(unittest.TestCase):
    def test_the_preamble_is_dropped(self):
        result = SR.anonymise(NARRATIVE)
        self.assertNotIn("集号", result["synopsis"])
        self.assertNotIn("授权", result["synopsis"])
        self.assertNotIn("SUPERVISOR_ORDERS", result["synopsis"])
        self.assertNotIn("观众已知", result["synopsis"])
        self.assertGreater(result["dropped_preamble_lines"], 0)

    def test_episode_version_and_chapter_labels_are_gone(self):
        text = SR.anonymise(NARRATIVE)["synopsis"]
        for leaked in ("E14", "v3", "第 14 章", "第2季"):
            self.assertNotIn(leaked, text, leaked)

    def test_scene_content_survives(self):
        text = SR.anonymise(NARRATIVE)["synopsis"]
        self.assertIn("她走到门口，门已经关了。", text)
        self.assertIn("守卫：天黑之前不开。", text)

    def test_scene_headers_become_neutral_labels(self):
        result = SR.anonymise(NARRATIVE)
        self.assertEqual(result["scene_labels"], ["S01", "S02"])
        self.assertIn("## S01", result["synopsis"])
        self.assertNotIn("LOC-GATE", result["synopsis"])
        self.assertNotIn("TIME-NIGHT", result["synopsis"])

    def test_location_ids_are_replaced_consistently(self):
        text = SR.anonymise(NARRATIVE)["synopsis"]
        self.assertIn("L1", text)
        self.assertIn("L2", text)

    def test_a_narrative_without_headers_is_returned_neutralised(self):
        result = SR.anonymise("E14：只是正文。")
        self.assertNotIn("E14", result["synopsis"])
        self.assertEqual(result["scene_labels"], [])


class ProtocolIntegrationTests(unittest.TestCase):
    def test_script_review_is_a_registered_kind(self):
        self.assertIn("script_review", COMMON.KINDS)
        self.assertIn("script_review", VRP.QUESTIONNAIRES)
        self.assertIn("script_review", VRP.OBSERVED_FIELDS)
        self.assertNotIn("script_review", COMMON.MEDIA_KINDS)

    def test_media_kinds_are_unchanged(self):
        self.assertEqual(COMMON.MEDIA_KINDS, ("identity", "keyframe", "start_frame",
                                              "post_gen_plot", "video_q2", "action_role"))

    def test_every_script_question_has_an_enum_and_a_maps_to(self):
        for key, row in VRP.QUESTIONNAIRES["script_review"].items():
            self.assertTrue(row["question"].strip(), key)
            self.assertTrue(row["enum"], key)
            self.assertTrue(row["maps_to"], key)

    def test_build_request_binds_the_anonymised_synopsis(self):
        with tempfile.TemporaryDirectory() as tmp:
            narrative = Path(tmp) / "E14_NARRATIVE_CANONICAL_v1.md"
            narrative.write_text(NARRATIVE, encoding="utf-8")
            request = VRP.build_request("script_review", "E14", narrative=narrative,
                                        out=Path(tmp) / "request.json")
            self.assertEqual(request["kind"], "script_review")
            self.assertEqual(request["item_count"], 1)
            item = request["items"][0]
            self.assertEqual(item["media"][0]["role"], "ANONYMISED_SYNOPSIS")
            anon = item["anonymisation"]
            self.assertEqual(len(anon["narrative_sha256"]), 64)
            self.assertEqual(len(anon["synopsis_sha256"]), 64)
            synopsis = Path(anon["synopsis_path"]).read_text(encoding="utf-8")
            self.assertNotIn("E14", synopsis)
            self.assertEqual(request["reviewer_contract"]["review_method"], "AI_REVIEW")

    def test_other_kinds_do_not_gain_a_script_item(self):
        self.assertNotIn("anonymisation", VRP.QUESTIONNAIRES)
        self.assertNotIn("script_review", VRP.QUESTIONNAIRES["post_gen_plot"])


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        narrative = tmp / "E14_NARRATIVE_CANONICAL_v1.md"
        narrative.write_text(NARRATIVE, encoding="utf-8")
        self.request_path = tmp / "request.json"
        self.request = VRP.build_request("script_review", "E14", narrative=narrative,
                                         out=self.request_path)
        self.sha = COMMON.sha256_file(self.request_path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_complete_answers_validate(self):
        failures, verdicts = SR.validate(self.request, self.sha, answers(self.request, self.sha))
        self.assertEqual(failures, [])
        self.assertEqual(verdicts[0]["verdict"], "REVIEWED")

    def test_a_script_review_never_yields_pass(self):
        _, verdicts = SR.validate(self.request, self.sha, answers(self.request, self.sha))
        self.assertNotIn(verdicts[0]["verdict"], {"PASS", "PASS_WITH_P2"})

    def test_a_fail_answer_is_not_a_rejection(self):
        # the media validator would REJECT on a FAIL answer; a script review must not.
        payload = answers(self.request, self.sha, points=[
            {"scene": "S01", "question": "why does the guard refuse?",
             "why": "the text never says what the guard is afraid of"}])
        failures, verdicts = SR.validate(self.request, self.sha, payload)
        self.assertEqual(failures, [])
        self.assertEqual(verdicts[0]["verdict"], "REVIEWED")
        self.assertEqual(len(verdicts[0]["confusion_points"]), 1)

    def test_the_untouched_template_is_refused(self):
        payload = answers(self.request, self.sha)
        payload[COMMON.TEMPLATE_MARKER] = True
        failures, _ = SR.validate(self.request, self.sha, payload)
        self.assertTrue(any("template" in code for code in failures))

    def test_a_null_answer_is_refused(self):
        failures, verdicts = SR.validate(
            self.request, self.sha, answers(self.request, self.sha, exclude="payoff_is_felt"))
        self.assertTrue(any("answer_null:payoff_is_felt" in code for code in failures))
        self.assertEqual(verdicts[0]["verdict"], "INCOMPLETE")

    def test_the_wrong_reviewer_is_refused(self):
        failures, _ = SR.validate(self.request, self.sha,
                                  answers(self.request, self.sha, reviewer="someone-else"))
        self.assertTrue(any(code.startswith("reviewer_not_") for code in failures))

    def test_a_confusion_point_naming_an_unknown_scene_is_refused(self):
        failures, _ = SR.validate(self.request, self.sha, answers(
            self.request, self.sha,
            points=[{"scene": "S99", "question": "what is this?",
                     "why": "the text never introduces the place this scene happens in"}]))
        self.assertTrue(any("scene_unknown:S99" in code for code in failures))

    def test_answers_are_bound_to_the_exact_request_sha(self):
        # the answers declare a sha the request file does not have
        failures, _ = SR.validate(self.request, self.sha,
                                  answers(self.request, "0" * 64))
        self.assertTrue(any(code.startswith("request_sha256_mismatch") for code in failures))


def _submit(request_path: Path, answers_path: Path) -> dict:
    """Drive the protocol's own submit path (through script_review.submit)."""
    original_argv = sys.argv
    sys.argv = ["script_review.py", "submit", "--request", str(request_path),
                "--answers", str(answers_path)]
    try:
        out = request_path.with_name(request_path.name.replace("_request.json", "_submitted.json"))
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            code = SR.main(sys.argv[1:])
    finally:
        sys.argv = original_argv
    return {"exit": code, "submitted": json.loads(out.read_text(encoding="utf-8")),
            "path": out}


class SubmitAndRespondTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        narrative = tmp / "E14_NARRATIVE_CANONICAL_v1.md"
        narrative.write_text(NARRATIVE, encoding="utf-8")
        self.request_path = tmp / "E14-script_review-request_request.json"
        self.request = VRP.build_request("script_review", "E14", narrative=narrative,
                                         out=self.request_path)
        self.sha = COMMON.sha256_file(self.request_path)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_answers(self, payload: dict) -> Path:
        path = self.request_path.with_name("answers.json")
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_submit_writes_a_pending_report_and_never_pass(self):
        points = [{"scene": "S01", "question": "why is the gate shut?",
                   "why": "the text never says who shut it or why it matters tonight"}]
        path = self._write_answers(answers(self.request, self.sha, points=points))
        result = _submit(self.request_path, path)
        self.assertEqual(result["exit"], 0)
        report = json.loads((result["path"].with_name(
            result["path"].name.replace("_submitted.json", "_script_review_report.json")))
            .read_text(encoding="utf-8"))
        self.assertNotIn(report["script_verdict"], {"PASS", "FAIL"})
        self.assertEqual(report["review_state"], "INCOMPLETE")
        self.assertFalse(report["blocking"])
        self.assertEqual(report["confusion_points"][0]["status"], "OPEN")
        self.assertEqual(report["confusion_points"][0]["confusion_id"], "CP-01-S01")
        self.assertEqual(report["reviewer"], COMMON.REVIEWER_ID)

    def test_an_upper_case_request_name_is_never_overwritten(self):
        # lab 化神 E04: *_REQUEST.json was not rewritten and submit replaced the request with the record
        upper = self.request_path.with_name("E14_SCRIPT_REVIEW_REQUEST.json")
        upper.write_bytes(self.request_path.read_bytes())
        before = upper.read_bytes()
        path = self._write_answers(answers(self.request, COMMON.sha256_file(upper)))
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            code = SR.main(["submit", "--request", str(upper), "--answers", str(path)])
        self.assertEqual(code, 0)
        self.assertEqual(upper.read_bytes(), before)
        self.assertTrue(upper.with_name("E14_SCRIPT_REVIEW_submitted.json").is_file())

    def test_a_review_with_no_confusion_is_complete_on_arrival(self):
        path = self._write_answers(answers(self.request, self.sha))
        result = _submit(self.request_path, path)
        report = json.loads((result["path"].with_name(
            result["path"].name.replace("_submitted.json", "_script_review_report.json")))
            .read_text(encoding="utf-8"))
        self.assertEqual(report["review_state"], "COMPLETE")
        self.assertEqual(report["unanswered"], [])

    def test_an_unanswered_point_keeps_the_report_incomplete(self):
        points = [{"scene": "S02", "question": "who is behind the door?",
                   "why": "the text says there is someone inside and never returns to it"}]
        path = self._write_answers(answers(self.request, self.sha, points=points))
        submitted = _submit(self.request_path, path)["submitted"]
        responses = {"schema": SR.RESPONSES_SCHEMA, "responder": "nalu-writer",
                     "submitted_sha256": COMMON.sha256_file(
                         self.request_path.with_name("E14-script_review-request_submitted.json")),
                     "items": []}
        report = SR.respond(submitted, self.request_path.with_name(
            "E14-script_review-request_submitted.json"), responses)
        self.assertEqual(report["review_state"], "INCOMPLETE")
        self.assertEqual(report["unanswered"], ["CP-01-S02"])

    def test_an_answered_point_completes_the_report(self):
        points = [{"scene": "S02", "question": "who is behind the door?",
                   "why": "the text says there is someone inside and never returns to it"}]
        path = self._write_answers(answers(self.request, self.sha, points=points))
        submitted = _submit(self.request_path, path)["submitted"]
        submitted_path = self.request_path.with_name(
            "E14-script_review-request_submitted.json")
        responses = {"schema": SR.RESPONSES_SCHEMA, "responder": "nalu-writer",
                     "submitted_sha256": COMMON.sha256_file(submitted_path),
                     "items": [{"confusion_id": "CP-01-S02", "disposition": "REVISED",
                                "response": "added the watcher's hand at the door crack"}]}
        report = SR.respond(submitted, submitted_path, responses)
        self.assertEqual(report["review_state"], "COMPLETE")
        self.assertEqual(report["confusion_points"][0]["status"], "REVISED")

    def test_the_writer_cannot_be_the_reviewer(self):
        points = [{"scene": "S02", "question": "who is behind the door?",
                   "why": "the text says there is someone inside and never returns to it"}]
        path = self._write_answers(answers(self.request, self.sha, points=points))
        submitted = _submit(self.request_path, path)["submitted"]
        submitted_path = self.request_path.with_name(
            "E14-script_review-request_submitted.json")
        responses = {"schema": SR.RESPONSES_SCHEMA, "responder": COMMON.REVIEWER_ID,
                     "items": [{"confusion_id": "CP-01-S02", "disposition": "EXPLAINED",
                                "response": "the door is answered in the next episode"}]}
        report = SR.respond(submitted, submitted_path, responses)
        self.assertEqual(report["review_state"], "INCOMPLETE")
        self.assertTrue(any(code.startswith("WRITER_AND_REVIEWER_MUST_DIFFER")
                            for code in report["validation"]["failures"]))

    def test_a_too_short_response_does_not_count(self):
        points = [{"scene": "S02", "question": "who is behind the door?",
                   "why": "the text says there is someone inside and never returns to it"}]
        path = self._write_answers(answers(self.request, self.sha, points=points))
        submitted = _submit(self.request_path, path)["submitted"]
        submitted_path = self.request_path.with_name(
            "E14-script_review-request_submitted.json")
        responses = {"schema": SR.RESPONSES_SCHEMA, "responder": "nalu-writer",
                     "items": [{"confusion_id": "CP-01-S02", "disposition": "EXPLAINED",
                                "response": "ok"}]}
        report = SR.respond(submitted, submitted_path, responses)
        self.assertEqual(report["review_state"], "INCOMPLETE")

    def test_disagreement_escalates_to_the_line_owner_only(self):
        points = [{"scene": "S02", "question": "who is behind the door?",
                   "why": "the text says there is someone inside and never returns to it"}]
        path = self._write_answers(answers(self.request, self.sha, points=points))
        submitted = _submit(self.request_path, path)["submitted"]
        submitted_path = self.request_path.with_name(
            "E14-script_review-request_submitted.json")
        base = {"schema": SR.RESPONSES_SCHEMA, "responder": "nalu-writer"}
        wrong = {**base, "items": [{"confusion_id": "CP-01-S02", "disposition": "DISAGREE_ESCALATED",
                                    "response": "the empty door is the point of the scene",
                                    "escalation": {"to": "REVIEWER", "reason": "we differ"}}]}
        self.assertEqual(SR.respond(submitted, submitted_path, wrong)["review_state"], "INCOMPLETE")
        right = {**base, "items": [{"confusion_id": "CP-01-S02", "disposition": "DISAGREE_ESCALATED",
                                    "response": "the empty door is the point of the scene",
                                    "escalation": {"to": "LINE_OWNER",
                                                   "reason": "reviewer wants the watcher shown"}}]}
        report = SR.respond(submitted, submitted_path, right)
        self.assertEqual(report["review_state"], "COMPLETE_WITH_ESCALATION")
        self.assertEqual(report["escalations"][0]["to"], "LINE_OWNER")
        self.assertFalse(report["blocking"])


class BlockingSwitchTests(unittest.TestCase):
    def test_blocking_is_off_unless_the_caller_turns_it_on(self):
        with tempfile.TemporaryDirectory() as tmp:
            narrative = Path(tmp) / "E14_NARRATIVE_CANONICAL_v1.md"
            narrative.write_text(NARRATIVE, encoding="utf-8")
            request = VRP.build_request("script_review", "E14", narrative=narrative,
                                        out=Path(tmp) / "request.json")
            submitted = {"episode": "E14", "reviewer": COMMON.REVIEWER_ID, "items": [
                {"confusion_points": [{"scene": "S01", "question": "q", "why": "w"}]}]}
            report = SR.report_pending(submitted, Path(tmp) / "submitted.json")
            self.assertFalse(report["blocking"])
            forced = SR.report_pending(submitted, Path(tmp) / "submitted.json", blocking=True)
            self.assertTrue(forced["blocking"])
            self.assertEqual(request["kind"], "script_review")


class NoScriptTextTests(unittest.TestCase):
    def test_the_tool_carries_no_script_text(self):
        text = (TOOLS / "script_review.py").read_text(encoding="utf-8")
        for line in NARRATIVE.splitlines():
            if line.startswith("她走") or line.startswith("侧门虚掩"):
                self.assertNotIn(line, text)


if __name__ == "__main__":
    unittest.main()
