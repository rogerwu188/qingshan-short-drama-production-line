"""FINAL-CUT-AUDIENCE-DETECTORS wrapper: consumes the detector report, never re-measures, never hides UNVERIFIED."""
import json
import unittest
from pathlib import Path

from tools.final_cut_audience_gate import evaluate, REPORT_SCHEMA

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tools/tests/fixtures/e04_negative_sample"


def report(**detectors):
    return {"schema": REPORT_SCHEMA, "media_sha256": "abc", "detectors": detectors}


class WrapperGate(unittest.TestCase):
    def test_missing_report_is_fail_not_na(self):
        self.assertEqual(evaluate(None)["status"], "FAIL")
        self.assertIn("AUDIENCE_DETECTOR_REPORT_MISSING", evaluate(None)["failures"])

    def test_pass_lists_unverified_and_not_implemented(self):
        r = evaluate(report(hook_present={"status": "PASS"}, emotion_dynamics={"status": "UNVERIFIED", "reason": "no map"},
                            state_machine={"status": "NOT_IMPLEMENTED"}))
        self.assertEqual(r["status"], "PASS")
        self.assertTrue(any(u.startswith("emotion_dynamics:UNVERIFIED") for u in r["unverified"]))
        self.assertTrue(any(u.startswith("count_consistency:NOT_IMPLEMENTED") for u in r["unverified"]))

    def test_any_fail_fails_with_codes(self):
        r = evaluate(report(hook_present={"status": "FAIL", "evidence": {"failures": ["HOOK_MISSING"]}}))
        self.assertEqual(r["status"], "FAIL")
        self.assertIn("hook_present:FAIL:HOOK_MISSING", r["failures"])

    def test_stale_media_sha_fails(self):
        r = evaluate(report(hook_present={"status": "PASS"}), video_sha256="other")
        self.assertIn("AUDIENCE_DETECTOR_REPORT_STALE_MEDIA_SHA", r["failures"])


class E04NegativeSample(unittest.TestCase):
    """The E04 fixture measurements, run through the detector decision functions, must FAIL the wrapper."""

    def test_e04_measurements_fail_the_gate(self):
        from tools.final_cut_audience_detectors import evaluate_from_measurements
        from tools.tests.test_final_cut_audience_detectors import fixture_measurements
        m = json.loads((FIXTURE / "audio_metrics.json").read_text(encoding="utf-8"))
        result = evaluate_from_measurements(fixture_measurements(m))
        wrapped = evaluate({"schema": REPORT_SCHEMA, "media_sha256": result.get("media_sha256"),
                            "detectors": result["detectors"]})
        self.assertEqual(wrapped["status"], "FAIL")
        failed = {f.split(":")[0] for f in wrapped["failures"]}
        for name in ("hook_present", "dialogue_coverage", "silence_gap_max", "loudness"):
            self.assertIn(name, failed)


if __name__ == "__main__":
    unittest.main()


class E04MeasuredReferenceBands(unittest.TestCase):
    """With the REAL reference bands (measured from the S4 clips) the E04 take still fails: the model
    ignored the references (CHAR-MAYANG spoke at ~101 Hz against a 242–327 Hz reference band)."""

    def test_e04_take_leaves_its_measured_reference_bands(self):
        from tools.final_cut_audience_detectors import evaluate_from_measurements
        from tools.tests.test_final_cut_audience_detectors import fixture_measurements
        m = json.loads((FIXTURE / "audio_metrics.json").read_text(encoding="utf-8"))
        measured = fixture_measurements(dict(m, voice_cast=m["measured_voice_cast"]))
        result = evaluate_from_measurements(measured)
        vd = result["detectors"]["voice_distinctness"]
        self.assertEqual(vd["status"], "FAIL")
        codes = " ".join(vd.get("failures") or [])
        self.assertIn("VOICE_OUT_OF_BAND:CHAR-MAYANG", codes)
