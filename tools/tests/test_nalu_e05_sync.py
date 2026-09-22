"""E05 sync (K053–K058): voice-only characters, provider-decline classification, shot-plan parity diagnostic."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


parity = load("final_cut_shot_plan_parity", "lines/nalu/runtime/tools/final_cut_shot_plan_parity.py")
submit = load("submit_giggle_video_manifest_v2_e05", "tools/submit_giggle_video_manifest_v2.py")
boot = load("bootstrap_identity_cards_e05", "lines/nalu/runtime/tools/bootstrap_identity_cards.py")

CONTRACT = {"episode": "E05", "shots": [{"shot_id": f"E05-S01-0{i}", "target_seconds": 5} for i in range(1, 5)]}


class VoiceOnly(unittest.TestCase):
    def test_marker_is_stable(self):
        self.assertEqual(boot.VOICE_ONLY_NO_PLATE, "VOICE_ONLY_NO_PLATE")


class ProviderDecline(unittest.TestCase):
    def test_explicit_500_without_task_id_is_declined(self):
        self.assertTrue(submit._provider_declined({"provider_response": "{'code': 500, 'message': 'payment failed'}"}))

    def test_response_with_task_id_is_not_declined(self):
        self.assertFalse(submit._provider_declined({"provider_response": "{'code': 200, 'data': {'task_id': 'abc'}}"}))

    def test_transport_failure_without_task_id_is_declined(self):
        # nalu E08 wave 2 (2026-09-21): a transport failure that never produced a task id is a decline at this
        # level; the caller still requires the ledger window to show no extra pay row before it retries.
        self.assertTrue(submit._provider_declined({"provider_response": "", "error": "timed out"}))

    def test_lost_response_with_task_id_is_not_declined(self):
        self.assertFalse(submit._provider_declined({"provider_response": "", "error": "timed out after task_id=abc"}))


class Parity(unittest.TestCase):
    def test_planned_timeline_and_segments(self):
        plan = parity.planned_timeline(CONTRACT)
        self.assertEqual([r["end"] for r in plan], [5.0, 10.0, 15.0, 20.0])
        self.assertEqual(parity.segments_from_cuts([5.0, 10.0, 15.0], 20.0), [(0.0, 5.0), (5.0, 10.0), (10.0, 15.0), (15.0, 20.0)])
        self.assertEqual([r["shot_id"] for r in parity.shots_overlapping(plan, 4.0, 11.0)], ["E05-S01-01", "E05-S01-02", "E05-S01-03"])

    def _evaluate(self, cuts, lumas, total=23.0):
        saved = (parity.probe_duration, parity.scene_cuts, parity.luma_samples)
        parity.probe_duration = lambda p: total
        parity.scene_cuts = lambda p, th, until: cuts
        parity.luma_samples = lambda p, until, fps=5: lumas
        try:
            return parity.evaluate(Path("x.mp4"), CONTRACT, end_card_seconds=3.0, scene_threshold=8.0,
                                   static_yavg_delta=2.0, blank_high=217.0, blank_low=38.0)
        finally:
            parity.probe_duration, parity.scene_cuts, parity.luma_samples = saved

    def test_clean_cut_matches_plan(self):
        lumas = [(t / 5, 100.0 + (t % 7)) for t in range(100)]
        rep = self._evaluate([5.0, 10.0, 15.0], lumas)
        self.assertEqual(rep["status"], "CLEAN")
        self.assertEqual(rep["detected_segments"], 4)
        self.assertEqual(rep["body_seconds"], 20.0)

    def test_stretched_static_and_blank_are_diagnosed_not_blocked(self):
        lumas = [(t / 5, 100.0) for t in range(50)] + [(t / 5, 250.0) for t in range(50, 100)]
        rep = self._evaluate([10.0], lumas)
        codes = [f["code"] for f in rep["findings"]]
        self.assertIn("SHOT_COUNT_DRIFT", codes)
        self.assertIn("SHOT_STRETCHED", codes)
        self.assertIn("STATIC_HOLD_IN_DIALOGUE", codes)
        self.assertIn("BLANK_SCREEN", codes)
        self.assertEqual(rep["status"], "FINDINGS")
        self.assertNotIn("gate_id", rep)
        block = parity.checkpoint_block(rep)
        self.assertIn("不阻断", block)
        self.assertIn("BLANK_SCREEN", block)


if __name__ == "__main__":
    unittest.main()
