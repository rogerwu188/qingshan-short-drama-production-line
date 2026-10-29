"""Post-generation QA measures only new or changed clips (K129) and never asks for an
identical-prompt reroll when the model ignored a constraint already in the prompt (K130)."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
sys.path.insert(0, str(TOOLS))


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


qa = load("post_generation_qa_runner")

EXP = {"expected_dialogue": [{"shot_id": "S1", "spoken_text": "x"}], "duration_seconds": 4,
       "editorial_shot_ids": ["S1"], "narrative_beat": "irrelevant to measurement"}
POLICY = {"profile": "STRICT"}


def _record(tmp: Path, fingerprint: str, *, sheet_exists: bool = True, status: str = "PASS") -> Path:
    sheet = tmp / "contact_sheet_2fps.png"
    if sheet_exists:
        sheet.write_bytes(b"png")
    record = {
        "media_path": str(tmp / "u.mp4"), "media_sha256": "a" * 64,
        "technical_qa": {"status": "TECHNICAL_PASS_CONTENT_UNREVIEWED" if status == "PASS" else "TECHNICAL_FAIL",
                         "checks": {"decode": {"status": status}}, "supporting_measurements": {"fps": 24},
                         "failures": [] if status == "PASS" else ["decode:FAIL"]},
        "dialogue_qa": {"status": "PASS", "segments": [{"start": 1.0, "end": 2.0, "text": "x"}]},
        "speech_rate_qa": {"tier": "OK"}, "voice_consistency_qa": {"status": "PASS"},
        "basic_plot_qa": {"contact_sheet": {"path": str(sheet), "sha256": "s" * 64}},
        "measurement_fingerprint": fingerprint, "recorded_at": "2026-10-29T00:00:00Z",
    }
    path = tmp / "U_POST_GENERATION_QA.json"
    path.write_text(json.dumps(record))
    return path


class FingerprintTest(unittest.TestCase):
    def test_depends_on_clip_bytes_inputs_and_measurement_code_only(self):
        base = qa.measurement_fingerprint("a" * 64, EXP, language="zh", policy=POLICY, pacing=None, voice_cast=None)
        same = qa.measurement_fingerprint("a" * 64, {**EXP, "narrative_beat": "other"}, language="zh",
                                          policy=POLICY, pacing=None, voice_cast=None)
        self.assertEqual(base, same, "fields the measurers never read must not invalidate reuse")
        for changed in (
            dict(media_sha256="b" * 64), dict(language="en"), dict(policy={"profile": "WEAK"}),
            dict(pacing={"x": 1}), dict(voice_cast={"CHAR": {"f0_band_hz": [1, 2]}}),
            dict(expectations={**EXP, "expected_dialogue": []}),
            dict(expectations={**EXP, "duration_seconds": 6}),
        ):
            kwargs = dict(media_sha256="a" * 64, expectations=EXP, language="zh", policy=POLICY, pacing=None,
                          voice_cast=None)
            kwargs.update(changed)
            other = qa.measurement_fingerprint(kwargs.pop("media_sha256"), kwargs.pop("expectations"), **kwargs)
            self.assertNotEqual(base, other, changed)


class ReuseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.fp = qa.measurement_fingerprint("a" * 64, EXP, language="zh", policy=POLICY, pacing=None, voice_cast=None)

    def test_matching_record_is_reused_verbatim(self):
        path = _record(self.tmp, self.fp)
        got = qa.reuse_measurement(path, self.fp)
        self.assertIsNotNone(got)
        self.assertEqual(got["media_sha256"], "a" * 64)
        self.assertEqual(got["technical"]["status"], "PASS")
        self.assertEqual(got["technical"]["checks"], {"decode": {"status": "PASS"}})
        self.assertEqual(got["dialogue"]["segments"][0]["text"], "x")
        self.assertEqual(got["voice"], {"status": "PASS"})
        self.assertEqual(got["reused_from"]["recorded_at"], "2026-10-29T00:00:00Z")

    def test_failed_measurements_are_reused_too_never_upgraded(self):
        path = _record(self.tmp, self.fp, status="FAIL")
        got = qa.reuse_measurement(path, self.fp)
        self.assertEqual((got["technical"]["status"], got["technical"]["failures"]), ("FAIL", ["decode:FAIL"]))

    def test_changed_clip_or_missing_evidence_measures_again(self):
        path = _record(self.tmp, self.fp)
        other = qa.measurement_fingerprint("b" * 64, EXP, language="zh", policy=POLICY, pacing=None, voice_cast=None)
        self.assertIsNone(qa.reuse_measurement(path, other))
        self.assertIsNone(qa.reuse_measurement(self.tmp / "missing.json", self.fp))
        (self.tmp / "contact_sheet_2fps.png").unlink()
        path = _record(self.tmp, self.fp, sheet_exists=False)
        self.assertIsNone(qa.reuse_measurement(path, self.fp), "a lost contact sheet means re-measure")
        legacy = json.loads(path.read_text())
        legacy.pop("measurement_fingerprint")
        path.write_text(json.dumps(legacy))
        self.assertIsNone(qa.reuse_measurement(path, self.fp), "records from before K129 carry no fingerprint")

    def test_run_accepts_remeasure_flag(self):
        import inspect
        self.assertIn("remeasure", inspect.signature(qa.run).parameters)
        src = (TOOLS / "post_generation_qa_runner.py").read_text(encoding="utf-8")
        self.assertIn('"--remeasure"', src)
        self.assertIn("reuse_measurement(out_dir", src)


class IdenticalPromptRerollTest(unittest.TestCase):
    def test_constraint_ignored_failures_require_a_prompt_or_design_change(self):
        for reason in ("PLOT_DEFECT_P1:BURNED_IN_SUBTITLE_TEXT", "PLOT_DEFECT_P2:ONSCREEN_TEXT_IN_SET_DRESSING",
                       "PLOT_DEFECT_P1:EXTRA_VISIBLE_FIGURE_NOT_IN_UNIT_CAST"):
            change = qa.required_prompt_change_for(reason)
            self.assertIsNotNone(change, reason)
            self.assertIn("PROMPT_OR_DESIGN_CHANGE_REQUIRED", change)

    def test_speech_rate_keeps_its_own_rule_and_others_stay_open(self):
        self.assertIn("PERFORMANCE_INSTRUCTION_CHANGE", qa.required_prompt_change_for("dialogue:SPEECH_RATE_UNDER_TARGET:0.5"))
        self.assertIsNone(qa.required_prompt_change_for("voice:VOICE_OUT_OF_BAND:CHAR-X:140"))
        self.assertIsNone(qa.required_prompt_change_for("duration:FAIL"))

    def test_request_rows_carry_the_flag(self):
        src = (TOOLS / "post_generation_qa_runner.py").read_text(encoding="utf-8")
        self.assertIn('"identical_prompt_reroll_allowed": required_prompt_change_for(reason) is None', src)


if __name__ == "__main__":
    unittest.main()
