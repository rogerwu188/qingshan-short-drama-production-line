"""Authored-world / English-line policy for the hard-blocking QA gates (no network, no paid calls).

Rule (tools/authored_world.py): ``visual_culture_contract.era_lock`` decides; otherwise an
English-dialogue line is an authored world and every Chinese line keeps the period behaviour.
Each kept item has an English/authored case and a Chinese case proving the zh output is unchanged.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
NALU_TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for _path in (str(REPO), str(REPO / "tools"), str(NALU_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tools import authored_world as aw  # noqa: E402
from tools.anachronism_lock_gate import FORBIDDEN_VISIBLE_TERMS  # noqa: E402
from tools.h3_provider_prompt_renderer import authored_world as h3_authored_world  # noqa: E402
import keyframe_q1_builder as q1  # noqa: E402
import nalu_qa_common as qa  # noqa: E402
import speech_rate_check as src  # noqa: E402
import video_q2_builder as q2  # noqa: E402
import vlm_review_protocol as vlm  # noqa: E402

LEGACY_Q1_PERIOD_KEYS = {
    "method", "decision", "engine", "closed_set_source", "closed_set", "ocr_report",
    "ocr_report_sha256", "ocr_status", "ocr_recognitions", "ocr_exit_code", "checks",
    "failures", "questions_must_be_closed_and_contract_derived",
}
LEGACY_Q2_PERIOD_KEYS = {
    "method", "decision", "engine", "closed_set_source", "closed_set", "frames_scanned",
    "per_frame", "checks", "failures", "questions_must_be_closed_and_contract_derived",
}


class RuleTest(unittest.TestCase):
    def test_era_lock_decides_then_language(self):
        self.assertTrue(aw.authored_world_from(None, "en"))
        self.assertTrue(aw.authored_world_from({}, "en-US"))
        self.assertFalse(aw.authored_world_from(None, "zh"))
        self.assertFalse(aw.authored_world_from(None, None))
        self.assertTrue(aw.authored_world_from({"era_lock": "authored_world"}, "zh"))
        self.assertFalse(aw.authored_world_from({"era_lock": "EAST_ASIAN_PERIOD"}, "en"))

    def test_h3_renderer_uses_the_same_rule(self):
        for vcc, language in ((None, "en"), (None, "zh"), ({"era_lock": "AUTHORED_WORLD"}, "zh"),
                              ({"era_lock": "EAST_ASIAN_PERIOD"}, "en"), ("bad", "en")):
            unit = {"visual_culture_contract": vcc, "dialogue_language": language}
            self.assertEqual(h3_authored_world(unit), aw.authored_world_from(vcc, language))

    def test_dialogue_language_resolution_order(self):
        self.assertEqual(aw.resolve_dialogue_language({"dialogue_language": "en"}, {"project": {"language": "zh"}}), "en")
        self.assertEqual(aw.resolve_dialogue_language({}, {"project": {"language": "en-US"}}), "en")
        self.assertEqual(aw.resolve_dialogue_language(None, None), "zh")
        self.assertTrue(aw.authored_world_for({}, {"project": {"language": "en"}}))
        self.assertFalse(aw.authored_world_for({"dialogue_language": "zh"}))


def _expectations(contract: dict, runtime: Path) -> qa.Expectations:
    exp = object.__new__(qa.Expectations)
    exp.contract = contract
    exp.shots = {"S1": {"prompt_spec": {"negative_prompts": ["冻结帧、速度斜坡或慢动作"]}}}
    return exp


class ForbiddenTermsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.runtime = Path(tmp.name)
        patcher = mock.patch.object(qa, "RUNTIME", self.runtime)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_chinese_line_keeps_the_closed_modern_object_set(self):
        exp = _expectations({"visual_culture_contract": {"forbidden_influences": ["欧洲中世纪骑士"]}}, self.runtime)
        self.assertEqual(exp.forbidden_terms(),
                         [str(v) for v in FORBIDDEN_VISIBLE_TERMS] + ["冻结帧、速度斜坡或慢动作"])
        self.assertIsNone(exp.ocr_text_language())
        self.assertFalse(exp.authored_world())

    def test_english_line_has_no_modern_object_ban(self):
        exp = _expectations({"dialogue_language": "en",
                             "visual_culture_contract": {"forbidden_influences": ["game-poster light"]}},
                            self.runtime)
        terms = exp.forbidden_terms()
        self.assertEqual(terms, ["game-poster light", "冻结帧、速度斜坡或慢动作"])
        self.assertNotIn("zipper", terms)
        self.assertEqual(exp.ocr_text_language(), "en")

    def test_runtime_config_language_is_honoured(self):
        (self.runtime / "qingshan.json").write_text(json.dumps({"project": {"language": "en"}}))
        exp = _expectations({}, self.runtime)
        self.assertTrue(exp.authored_world())
        self.assertNotIn("phone", exp.forbidden_terms())


class QuestionnaireTest(unittest.TestCase):
    def test_chinese_questionnaire_is_unchanged(self):
        for kind in ("keyframe", "video_q2", "identity"):
            self.assertEqual(vlm.questionnaire_for(kind), vlm.QUESTIONNAIRES[kind])

    def test_authored_english_wording_keeps_ids_enums_and_gates(self):
        for kind in ("keyframe", "video_q2"):
            rows = vlm.questionnaire_for(kind, authored_world=True, language="en")
            legacy = vlm.QUESTIONNAIRES[kind]
            self.assertEqual(set(rows), set(legacy))
            for key in rows:
                self.assertEqual(rows[key]["enum"], legacy[key]["enum"])
                self.assertEqual(rows[key]["maps_to"], legacy[key]["maps_to"])
            self.assertIn("authored world", rows["no_anachronism_from_closed_set"]["question"])
            self.assertNotIn("Latin", rows["no_burned_in_text_or_subtitle"]["question"])
            # every period question the builders score is still asked
            for key in q1.GATE_QUESTIONS[q1.PERIOD_GATE]:
                self.assertIn(key, rows)


def _q1_item():
    return {"answers": {"no_anachronism_from_closed_set": "PASS", "no_burned_in_text_or_subtitle": "PASS"},
            "observed": {"observed_text_strings": []}}


def _q1_ocr(rows):
    return {"exit_code": 0, "report_path": "/tmp/x.json", "report_sha256": "0",
            "report": {"status": "PASS", "recognitions": rows}}


LATIN_ROW = {"text": "ARCHIVE 07", "confidence": 0.95, "allowed": False, "forbidden_tokens": [],
             "latin_chars": 7, "unlisted_chinese": False, "numeric_string": True}


class KeyframePeriodTest(unittest.TestCase):
    def test_chinese_line_latin_text_still_fails_and_shape_is_unchanged(self):
        v, failures = q1.build_period_verification(_q1_item(), {}, _q1_ocr([dict(LATIN_ROW)]), ["phone"])
        self.assertIn("OCR_LATIN_CHARACTERS_PRESENT:7", failures)
        self.assertEqual(set(v), LEGACY_Q1_PERIOD_KEYS)
        self.assertEqual(v["decision"], "FAIL")

    def test_english_line_latin_text_is_advisory(self):
        v, failures = q1.build_period_verification(_q1_item(), {}, _q1_ocr([dict(LATIN_ROW)]), [],
                                                   authored_world=True, language="en")
        self.assertEqual(failures, [])
        self.assertEqual(v["decision"], "PASS")
        self.assertEqual(v["method"], "CLOSED_SET_ANACHRONISM_OCR_V1")
        self.assertEqual(v["period_anachronism_lock"], "NOT_APPLICABLE")
        self.assertTrue(v["not_applicable_reason"])
        self.assertEqual([row["text"] for row in v["advisory_findings"]], ["ARCHIVE 07"])

    def test_english_line_still_fails_a_forbidden_term(self):
        row = dict(LATIN_ROW, text="game poster", forbidden_tokens=["game poster"])
        _v, failures = q1.build_period_verification(_q1_item(), {}, _q1_ocr([row]), ["game poster"],
                                                    authored_world=True, language="en")
        self.assertTrue(any(f.startswith("OCR_FORBIDDEN_TERM_VISIBLE") for f in failures))


class VideoPeriodTest(unittest.TestCase):
    def _rows(self, tmp: Path, entries, latin):
        report = tmp / "f1_ocr.json"
        report.write_text(json.dumps({"status": "PASS" if not latin else "FAIL", "recognitions": entries,
                                      "latin_chars": latin, "critical_text_failures": 0}))
        return [{"frame": str(tmp / "f1.png"), "exit_code": 0, "report_path": str(report)}]

    def test_chinese_line_latin_text_still_fails_and_shape_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = self._rows(Path(tmp), [dict(LATIN_ROW)], 7)
            v, failures = q2.build_period_verification(_q1_item(), {}, rows, ["phone"])
        self.assertTrue(any("OCR_LATIN_CHARACTERS_PRESENT:7" in f for f in failures))
        self.assertEqual(set(v), LEGACY_Q2_PERIOD_KEYS)

    def test_english_line_latin_text_is_advisory(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = self._rows(Path(tmp), [dict(LATIN_ROW)], 7)
            v, failures = q2.build_period_verification(_q1_item(), {}, rows, [],
                                                       authored_world=True, language="en")
        self.assertEqual(failures, [])
        self.assertEqual(v["decision"], "PASS")
        self.assertEqual(v["period_anachronism_lock"], "NOT_APPLICABLE")
        self.assertEqual([row["text"] for row in v["advisory_findings"]], ["ARCHIVE 07"])


class StillOcrAuditTest(unittest.TestCase):
    def _run(self, extra):
        try:
            import still_image_ocr_audit as audit
        except ImportError as exc:  # pragma: no cover - OCR runtime not installed
            self.skipTest(f"OCR runtime unavailable: {exc}")

        class FakeOcr:
            def __call__(self, frame):
                return [(None, "ARCHIVE", 0.9)], 0.0

        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "k.png"
            image.write_bytes(b"x")
            out = Path(tmp) / "r.json"
            argv = ["still_image_ocr_audit.py", "--image", str(image), "--out", str(out), *extra]
            with mock.patch.object(audit, "RapidOCR", FakeOcr), \
                    mock.patch.object(audit.cv2, "imread", return_value=object()), \
                    mock.patch.object(sys, "argv", argv), \
                    mock.patch("builtins.print"):
                code = audit.main()
            return code, json.loads(out.read_text())

    def test_chinese_policy_latin_is_critical(self):
        code, report = self._run(["--forbid-text", "phone"])
        self.assertEqual((code, report["status"], report["critical_text_failures"]), (1, "FAIL", 1))
        self.assertNotIn("text_language", report)

    def test_english_policy_latin_is_advisory(self):
        code, report = self._run(["--text-language", "en"])
        self.assertEqual((code, report["status"], report["critical_text_failures"]), (0, "PASS", 0))
        self.assertEqual(report["latin_policy"], "ADVISORY")
        self.assertEqual(report["latin_chars"], 7)


class SpeechRateTrailingOffTest(unittest.TestCase):
    def _measure(self, text, language):
        segments = [{"text": text, "start": 0.0, "end": 10.0}]
        targets = {"S1": {"cps": 4.9 if language == "zh" else 2.8, "hook": False, "conflict": False}}
        return src.measure_unit("U1", segments, [{"shot_id": "S1", "spoken_text": text}], targets, language)

    def test_english_ascii_ellipsis_is_authored_trailing_off(self):
        result = self._measure("I thought you were...", "en")
        self.assertTrue(result["authored_trailing_off"])
        self.assertEqual(result["code"], "SPEECH_RATE_UNDER_TARGET_AUTHORED_TRAILING_OFF")

    def test_chinese_results_unchanged(self):
        self.assertEqual(self._measure("我以为你……", "zh")["code"],
                         "SPEECH_RATE_UNDER_TARGET_AUTHORED_TRAILING_OFF")
        self.assertEqual(self._measure("我以为你", "zh")["code"], "SPEECH_RATE_UNDER_TARGET_BLOCKER")


if __name__ == "__main__":
    unittest.main()
