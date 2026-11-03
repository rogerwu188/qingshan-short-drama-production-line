import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import throughput_baseline_gate as g  # noqa: E402

BASELINE = json.loads((ROOT / "configs/THROUGHPUT_BASELINE_V1.json").read_text(encoding="utf-8"))


def _run_log(path: Path, start: str, lines: list[tuple[str, str]]) -> None:
    text = [f"[{start}] nalu_pipeline run  episode=E99  stages=S6..S8"]
    text += [f"[{t}] {body}" for t, body in lines]
    path.write_text("\n".join(text) + "\n", encoding="utf-8")


class ThroughputGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.logs = Path(self.tmp.name)
        # run 1: S6 submits (PROVIDER_SUBMIT 60s), polls (PROVIDER_POLL 10s), ends BLOCKED on render -> 2h gap = PROVIDER_RENDER_WAIT
        _run_log(self.logs / "run_20260101T000000Z_a.log", "2026-01-01T00:00:00Z", [
            ("2026-01-01T00:00:00Z", "-- S6 video"),
            ("2026-01-01T00:00:00Z", "$ python tools/submit_giggle_video_manifest_v2.py --manifest m.json"),
            ("2026-01-01T00:01:00Z", "  -> exit=0 log=x"),
            ("2026-01-01T00:01:00Z", "$ python tools/poll_giggle_submit_report.py --submit-report r.json"),
            ("2026-01-01T00:01:10Z", "  -> exit=0 log=y"),
            ("2026-01-01T00:01:10Z", "   S6 => BLOCKED   blockers: VIDEO_NOT_ALL_COMPLETED   [70s, cum 70s]"),
        ])
        # run 2: QA compute 5 min, REVIEW_REQUIRED -> 1h gap = CC_REVIEW_WAIT
        _run_log(self.logs / "run_20260101T020110Z_b.log", "2026-01-01T02:01:10Z", [
            ("2026-01-01T02:01:10Z", "-- S6 video"),
            ("2026-01-01T02:01:10Z", "$ python lines/nalu/runtime/tools/post_generation_qa_runner.py run --episode E99"),
            ("2026-01-01T02:06:10Z", "  -> exit=0 log=z"),
            ("2026-01-01T02:06:10Z", "   S6 => REVIEW_REQUIRED   blockers: S6.qa:REVIEW_REQUIRED:post_gen_plot   [300s, cum 370s]"),
        ])
        # run 3: S6 PASS, S7 DRY_PLANNED (human) -> 30 min gap = HUMAN_AUTH_WAIT
        _run_log(self.logs / "run_20260101T030610Z_c.log", "2026-01-01T03:06:10Z", [
            ("2026-01-01T03:06:10Z", "-- S6 video"),
            ("2026-01-01T03:06:12Z", "   S6 => PASS   [2s, cum 372s]"),
            ("2026-01-01T03:06:12Z", "-- S7 assembly"),
            ("2026-01-01T03:06:13Z", "   S7 => DRY_PLANNED   blockers: PAID_STEPS_DISABLED   [1s, cum 373s]"),
        ])
        # run 4: S7 PASS
        _run_log(self.logs / "run_20260101T033613Z_d.log", "2026-01-01T03:36:13Z", [
            ("2026-01-01T03:36:13Z", "-- S7 assembly"),
            ("2026-01-01T03:40:13Z", "   S7 => PASS   [240s, cum 613s]"),
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_second_is_bucketed_and_waits_are_kept(self):
        m = g.measure(str(self.logs))
        self.assertEqual(m["runs"], 4)
        total = sum(m["bucket_hours"].values())
        self.assertAlmostEqual(total, m["window_hours"], places=6)
        self.assertAlmostEqual(m["bucket_hours"]["PROVIDER_RENDER_WAIT"], 2.0, places=6)
        self.assertAlmostEqual(m["bucket_hours"]["CC_REVIEW_WAIT"], 1.0, places=6)
        self.assertAlmostEqual(m["bucket_hours"]["HUMAN_AUTH_WAIT"], 0.5, places=6)
        self.assertAlmostEqual(m["bucket_hours"]["PROVIDER_SUBMIT"], 60 / 3600, places=6)
        self.assertAlmostEqual(m["bucket_hours"]["PROVIDER_POLL"], 10 / 3600, places=6)
        self.assertAlmostEqual(m["bucket_hours"]["PIPELINE_COMPUTE"], 300 / 3600, places=6)
        # run 4 has no child command: its 240 s are RUN_OVERHEAD, still counted
        self.assertGreaterEqual(m["bucket_hours"]["RUN_OVERHEAD"], 240 / 3600)
        # stage span: S6 first seen 00:00:00, first PASS 03:06:12
        self.assertAlmostEqual(m["stage_span_hours"]["S6"], 3 + 6 / 60 + 12 / 3600, places=6)

    def test_within_budget_passes_and_over_budget_fails(self):
        m = g.measure(str(self.logs))
        verdict = g.evaluate(m, BASELINE, units=53)
        self.assertEqual(verdict["status"], "PASS", verdict["failures"])
        tight = json.loads(json.dumps(BASELINE))
        tight["target"]["class_hours_max"]["provider"] = 1.0
        tight["target"]["stage_span_hours_max"]["S6"] = 1.0
        verdict = g.evaluate(m, tight, units=53)
        self.assertEqual(verdict["status"], "FAIL")
        self.assertTrue(any(f.startswith("CLASS_OVER_BUDGET:provider") for f in verdict["failures"]))
        self.assertTrue(any(f.startswith("STAGE_SPAN_OVER_BUDGET:S6") for f in verdict["failures"]))

    def test_gap_classifier(self):
        self.assertEqual(g.gap_bucket("REVIEW_REQUIRED", "S5.q1:REVIEW_REQUIRED:keyframe"), "CC_REVIEW_WAIT")
        self.assertEqual(g.gap_bucket("BLOCKED", "VIDEO_NOT_ALL_COMPLETED"), "PROVIDER_RENDER_WAIT")
        self.assertEqual(g.gap_bucket("DRY_PLANNED", "Q1_NOT_ALL_ADMITTED"), "HUMAN_AUTH_WAIT")
        self.assertEqual(g.gap_bucket("BLOCKED", "KEYFRAME_SUBMIT_FAILED"), "CC_FIX_WAIT")
        self.assertEqual(g.gap_bucket("PASS", ""), "UNATTRIBUTED_IDLE")

    def test_cli_enforce_exit_code(self):
        import subprocess
        tight = json.loads(json.dumps(BASELINE))
        tight["target"]["episode_window_hours_max"] = 0.1
        bpath = Path(self.tmp.name) / "b.json"
        bpath.write_text(json.dumps(tight), encoding="utf-8")
        r = subprocess.run([sys.executable, str(ROOT / "tools/throughput_baseline_gate.py"), "--episode", "E99",
                            "--logs-dir", str(self.logs), "--baseline", str(bpath), "--enforce"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        r = subprocess.run([sys.executable, str(ROOT / "tools/throughput_baseline_gate.py"), "--episode", "E99",
                            "--logs-dir", str(self.logs), "--baseline", str(bpath)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)

    def test_baseline_config_shape(self):
        self.assertEqual(BASELINE["schema"], "qingshan.throughput_baseline.v1")
        for cls in ("human", "provider", "cc_llm", "idle"):
            self.assertIn(cls, BASELINE["target"]["class_hours_max"])
            self.assertIn(cls, BASELINE["measurement"]["classes"])
        flat = [b for bs in BASELINE["measurement"]["classes"].values() for b in bs]
        self.assertEqual(sorted(flat), sorted(g.BUCKETS))


if __name__ == "__main__":
    unittest.main()
