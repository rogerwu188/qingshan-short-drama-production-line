"""WP7 benchmark craft metrics (tools/craft_metrics.py): report only, never blocks.

Media part on a 10 s synthetic clip (ffmpeg lavfi: two different patterns -> one cut, a steady tone); skipped
without ffmpeg / OpenCV, like the other media-gated tests.  insightface is optional and not used here."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tools import craft_metrics as cm

ROOT = Path(__file__).resolve().parents[2]
HAVE_CV2 = importlib.util.find_spec("cv2") is not None and importlib.util.find_spec("numpy") is not None
HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def contract() -> dict:
    def shot(sid, scene, seconds, cast, **spec):
        return {"shot_id": sid, "scene_id": scene, "target_seconds": seconds,
                "prompt_spec": {"cast": [{"character_id": c} for c in cast], **spec}}
    return {"shots": [
        shot("E01-S01-01", "S1", 3, ["A", "B"], dialogue="A：你好。", beat_role="PAYOFF",
             action={"listener_reaction_en": "B grips the armrest", "contact_point": "A's hand on B's wrist",
                     "microexpression_design": "眼神一冷", "physical_causality": "x"},
             props=[{"prop_id": "PROP-1"}, {"prop_id": "PROP-2"}],
             camera_plan={"motion_family": "PUSH_IN"}),
        shot("E01-S01-02", "S1", 2, ["B"], beat_role="REACTION",
             internal_transition_authoring={"transition_mode": "REACTION_CUT"}, action={},
             camera_plan={"motion_family": "LOCKED"}),
        shot("E01-S02-01", "S2", 5, ["A"], dialogue="A：走。", action={},
             props=[{"prop_id": "PROP-3"}], camera_plan={"motion_family": "LOCKED"}),
    ], "setup_payoff_ledger": [{"id": "L1"}, {"id": "L2"}]}


class ScriptMetrics(unittest.TestCase):
    def test_contract_metrics(self):
        m = cm.measure_contract(contract())
        self.assertEqual(m["status"], "MEASURED")
        self.assertEqual(m["multi_person_plan_pct"], 30.0)
        self.assertEqual((m["dialogue_shots"], m["reaction_share_pct"], m["dedicated_reaction_shots"]), (2, 50.0, 1))
        self.assertEqual(m["reaction_after_payoff_pct"], 100.0)
        self.assertEqual(m["props_per_scene"], 1.5)
        self.assertEqual(m["touches_per_two_person_scene"], 1.0)
        self.assertEqual(m["camera_move_plan_pct"], 33.3)
        # 3 shots x 4 template fields + 1 authored contact = 13 slots, 3 authored
        self.assertEqual(m["fallback_share_pct"], round(100 * 10 / 13, 1))
        self.assertEqual(m["ledger"], {"setup_payoff_ledger": 2})

    def test_band_and_summary_never_need_media(self):
        report = cm.build_report(video=None, contract=contract(), episode="E01")
        rows = {r["metric"]: r for r in report["band"]}
        self.assertEqual(rows["multi_person_time_pct"]["status"], "OUT_OF_BAND")  # 30 < 35, plan source
        self.assertEqual(rows["multi_person_time_pct"]["source"], "plan_cast_incl_ots")
        self.assertEqual(rows["props_per_scene"]["status"], "OUT_OF_BAND")
        self.assertEqual(rows["speech_coverage_pct"]["status"], "NOT_MEASURED")
        self.assertEqual(rows["camera_moving_pct"]["source"], "plan_camera")
        self.assertTrue(report["summary"].startswith("CRAFT_METRICS 1/4 in band · out: "))
        self.assertIn("| speech coverage | — | ≥55 ≤70 | 62 | 58 | NOT_MEASURED |", cm.markdown(report))

    def test_speech_and_pauses_from_asr_windows(self):
        windows = [{"start": 0.0, "end": 2.0}, {"start": 2.2, "end": 4.0}, {"start": 8.0, "end": 9.0}]
        s = cm.measure_speech(windows, 10.0)
        self.assertEqual((s["speech_coverage_pct"], s["utterances"], s["pauses_gt3s"], s["longest_gap_s"]),
                         (50.0, 2, 1, 4.0))
        self.assertEqual(cm.measure_speech(None, 10.0)["status"], "NOT_MEASURED")

    def test_pause_loudness_and_music_presence(self):
        loud = [(t / 10, -20.0 if t < 40 or t >= 80 else -30.0) for t in range(100)]
        r = cm.measure_pause_loudness(loud, [[0.0, 4.0], [8.0, 10.0]], 10.0)
        self.assertEqual((r["pause_vs_speech_lu"], r["music_in_pauses_pct"]), (10.0, 100))
        quiet = [(t / 10, -20.0 if t < 40 or t >= 80 else -60.0) for t in range(100)]
        self.assertEqual(cm.measure_pause_loudness(quiet, [[0.0, 4.0], [8.0, 10.0]], 10.0)["music_in_pauses_pct"], 0)


@unittest.skipUnless(HAVE_CV2 and HAVE_FFMPEG, "needs OpenCV + ffmpeg")
class MediaMetrics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.video = cls.tmp / "clip.mp4"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc2=size=288x512:rate=24:duration=5",
                        "-f", "lavfi", "-i", "smptebars=size=288x512:rate=24:duration=5",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=10:sample_rate=48000",
                        "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]", "-map", "2:a",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(cls.video)],
                       check=True)

    def test_cut_shots_motion_speech_and_loudness(self):
        windows = [{"start": 0.5, "end": 3.5}, {"start": 7.5, "end": 9.5}]
        report = cm.build_report(video=self.video, contract=contract(), asr_windows=windows,
                                 timeline={"content_runtime_seconds": 10.0}, episode="E01", faces=False)
        picture = report["picture"]
        self.assertEqual(picture["status"], "MEASURED")
        self.assertEqual(picture["shots"], 2)
        self.assertAlmostEqual(report["shots"][1]["start"], 5.0, delta=0.1)
        self.assertEqual(picture["faces"], "NOT_MEASURED")
        self.assertIn("camera_moving_pct", picture)
        self.assertEqual(report["speech"]["pauses_gt3s"], 1)
        self.assertEqual(report["pause_loudness"]["status"], "MEASURED")
        self.assertLess(abs(report["pause_loudness"]["pause_vs_speech_lu"]), 1.0)  # a steady tone
        self.assertEqual(report["pause_loudness"]["music_in_pauses_pct"], 100)

    def test_cli_always_writes_a_report_and_exits_0(self):
        out, md = self.tmp / "m.json", self.tmp / "m.md"
        rc = cm.main(["--video", str(self.video), "--episode", "E01", "--no-faces", "--out", str(out), "--md", str(md)])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.read_text())["schema"], cm.SCHEMA)
        self.assertIn("Craft metrics vs Bilibili benchmark", md.read_text())
        rc = cm.main(["--video", str(self.tmp / "missing.mp4"), "--out", str(out)])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out.read_text())["picture"]["status"], "NOT_MEASURED")


class PipelineHook(unittest.TestCase):
    """S7: runs on BILI_V1 (or NALU_CRAFT_METRICS=on), records + notes, never blocks."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "lines" / "nalu" / "runtime" / "tools"))
        try:
            import nalu_pipeline  # noqa: PLC0415
        except Exception as exc:  # noqa: BLE001
            raise unittest.SkipTest(f"nalu_pipeline not importable: {exc}")
        cls.np = nalu_pipeline

    def ctx(self, profile: str, tmp: Path, exit_code: int = 1):
        assembly = tmp / "assembly"
        assembly.mkdir(parents=True, exist_ok=True)
        p = SimpleNamespace(assembly=assembly, final_candidate=tmp / "final.mp4", contract=tmp / "c.json")
        calls = []

        def run(argv, *, name, timeout=None, **_):
            calls.append([str(a) for a in argv])
            out = Path(str(argv[argv.index("--out") + 1]))
            out.write_text(json.dumps({"summary": "CRAFT_METRICS 3/5 in band", "band": []}))
            return {"name": name, "exit_code": exit_code}
        ctx = SimpleNamespace(p=p, episode="E07", craft_profile=profile, run=run, say=lambda *_: None)
        return ctx, calls

    def test_legacy_does_not_run_and_bili_records_without_blocking(self):
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(self.np, "RUNTIME", Path(raw)), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(self.np.CRAFT_METRICS_ENV, None)
            tmp = Path(raw)
            ctx, calls = self.ctx("LEGACY", tmp)
            res = SimpleNamespace(details={}, receipts=[])
            self.assertIsNone(self.np.s7_craft_metrics(ctx, res, None, None))
            self.assertEqual((calls, res.details), ([], {}))
            ctx, calls = self.ctx("BILI_V1", tmp)
            step = self.np.s7_craft_metrics(ctx, res, None, None)
            self.assertEqual((step["exit_code"], step["diagnostic_only"]), (0, True))
            self.assertEqual(res.details["craft_metrics"]["summary"], "CRAFT_METRICS 3/5 in band")
            self.assertIn("E07 S7 CRAFT_METRICS 3/5 in band", (tmp / "series" / "STATUS.md").read_text())
            self.np.s7_craft_metrics(ctx, res, None, None)  # one note per episode and summary
            self.assertEqual((tmp / "series" / "STATUS.md").read_text().count("E07 S7 CRAFT_METRICS"), 1)

    def test_env_switch(self):
        with mock.patch.dict(os.environ, {self.np.CRAFT_METRICS_ENV: "on"}):
            self.assertTrue(self.np.s7_craft_metrics_due(SimpleNamespace(craft_profile="LEGACY")))
        with mock.patch.dict(os.environ, {self.np.CRAFT_METRICS_ENV: "off"}):
            self.assertFalse(self.np.s7_craft_metrics_due(SimpleNamespace(craft_profile="BILI_V1")))


if __name__ == "__main__":
    unittest.main()
