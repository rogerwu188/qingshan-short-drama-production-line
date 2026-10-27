"""S7 push-in compensation (line owner 2026-10-26, lab Holmes E06; synthetic face curves and boxes).

Locked-camera H3 units that still push in get their early frames zoomed in (face-centred, <= 1.6x) so the face
keeps the end size; cuts, few faces and small pushes are left alone; CAMERA_GRAMMAR_V1 only; never blocks S7.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nalu_pipeline as npl  # noqa: E402
import push_in_compensation as flat_pic  # noqa: E402  - the module object nalu_pipeline imports
from tools import push_in_compensation as pic  # noqa: E402

STAMPED = {"episode": "E06", "camera_grammar_policy": "CAMERA_GRAMMAR_V1"}
LEGACY = {"episode": "E06", "camera_grammar_policy": "LEGACY_FORCED_MOTION"}


def samples(widths, cx=0.5, cy=0.35, end=4.4):
    times = pic.sample_times(0.0, end, len(widths))
    return [{"t": t, "width": w, "cx": cx, "cy": cy} if w else {"t": t, "width": None} for t, w in zip(times, widths)]


PUSH = [0.40, 0.43, 0.47, 0.53, 0.60, 0.68, 0.74, 0.78, 0.80]  # E06-VU-001-like: +100 %


class AnalyzeTests(unittest.TestCase):
    def test_big_push_is_compensated_to_the_cap(self):
        plan = pic.analyze(samples(PUSH))
        self.assertEqual(plan["status"], "COMPENSATE")
        crops = [p["crop"] for p in plan["curve"]]
        self.assertEqual((crops[0], crops[-1]), (pic.MAX_CROP, 1.0))
        self.assertTrue(all(a >= b for a, b in zip(crops, crops[1:])))
        self.assertTrue(plan["cap_hit"])
        self.assertAlmostEqual(plan["predicted_residual_growth"], 2.0 / pic.MAX_CROP - 1, places=3)

    def test_moderate_push_is_left_alone(self):
        # owner 2026-10-27: only big push-ins (>= GROWTH_MIN) are corrected; +35 % stays native and sharp
        widths = [0.40, 0.41, 0.43, 0.45, 0.47, 0.49, 0.51, 0.53, 0.54]
        self.assertEqual(pic.analyze(samples(widths))["status"], "NO_PUSH_IN")

    def test_compensation_never_exceeds_the_cap(self):
        widths = [0.40, 0.44, 0.48, 0.52, 0.56, 0.58, 0.60, 0.61, 0.62]  # +55 %
        plan = pic.analyze(samples(widths))
        self.assertEqual(plan["status"], "COMPENSATE")
        self.assertLessEqual(max(p["crop"] for p in plan["curve"]), pic.MAX_CROP + 1e-9)

    def test_small_growth_cut_and_few_faces_are_left_alone(self):
        self.assertEqual(pic.analyze(samples([0.40 + 0.01 * i for i in range(9)]))["status"], "NO_PUSH_IN")  # +20 %
        cut = [0.30, 0.31, 0.32, 0.33, 0.60, 0.61, 0.62, 0.63, 0.64]  # 0.33 -> 0.60 = +82 % between samples
        self.assertEqual(pic.analyze(samples(cut))["status"], "SKIPPED_INTERNAL_CUT")
        few = [0.40, 0.50, 0.60, 0.70, 0.80, None, None, None, None]
        self.assertEqual(pic.analyze(samples(few))["status"], "SKIPPED_FEW_FACES")
        self.assertEqual(pic.analyze(samples([0.6, 0.55, 0.5, 0.45, 0.4, 0.4, 0.4, 0.4, 0.4]))["status"], "NO_PUSH_IN")

    def test_zigzag_is_not_a_push_in(self):
        zigzag = [0.40, 0.55, 0.40, 0.55, 0.40, 0.55, 0.40, 0.55, 0.62]
        self.assertEqual(pic.analyze(samples(zigzag))["status"], "SKIPPED_NOT_MONOTONIC")

    def test_monotone_fit(self):
        self.assertEqual(pic.monotone_fit([1, 3, 2, 4]), [1, 2.5, 2.5, 4])
        self.assertEqual(pic.monotone_fit([1, 2, 3]), [1, 2, 3])

    def test_sample_times_stay_inside_the_cut_window(self):
        times = pic.sample_times(1.65, 4.4583)
        self.assertEqual(len(times), 9)
        self.assertTrue(1.65 < times[0] < times[-1] < 4.4583)


class CropWindowTests(unittest.TestCase):
    def plan(self, cx_start=0.40):
        rows = samples(PUSH)
        for i, row in enumerate(rows):
            row["cx"] = cx_start + (0.5 - cx_start) * i / 8
        return pic.analyze(rows)

    def test_end_frame_is_untouched_and_face_keeps_its_end_position(self):
        plan = self.plan()
        c, x0, y0 = pic.crop_window(10.0, plan, 768, 1344)
        self.assertEqual((c, x0, y0), (1.0, 0.0, 0.0))
        c, x0, y0 = pic.crop_window(0.0, plan, 768, 1344)
        self.assertAlmostEqual(c, pic.MAX_CROP)
        first = plan["curve"][0]
        face_out = (first["cx"] * 768 - x0) / (768 / c)
        self.assertAlmostEqual(face_out, plan["anchor"]["cx"], places=3)

    def test_window_never_leaves_the_frame(self):
        plan = self.plan(cx_start=0.02)
        for t in (0.0, 0.5, 1.0, 2.0, 4.4):
            c, x0, y0 = pic.crop_window(t, plan, 768, 1344)
            self.assertTrue(0 <= x0 <= 768 - 768 / c + 1e-6 and 0 <= y0 <= 1344 - 1344 / c + 1e-6, (t, c, x0, y0))


class PlanningTests(unittest.TestCase):
    GROUPING = {"units": [
        {"unit_id": "E06-VU-001", "camera_plan": {"motion_family": "LOCKED"}},
        {"unit_id": "E06-VU-002", "camera_plan": {"motion_family": "DOLLY"}},
        {"unit_id": "E06-VU-003", "camera_plan": {"motion_family": "STATIC"},
         "per_shot_camera_plans": [{"camera_plan": {"motion_family": "STATIC"}}, {"motion_family": "PAN"}]},
    ]}

    def test_locked_camera_units(self):
        self.assertEqual([pic.locked_camera_unit(u) for u in self.GROUPING["units"]], [True, False, False])

    def test_cut_windows_follow_the_head_and_tail_trims(self):
        tail = {"units": [{"unit_id": "A", "trimmed": True, "kept_seconds": 4.4},
                          {"unit_id": "B", "trimmed": False, "kept_seconds": 3.042}]}
        head = {"units": [{"unit_id": "B", "trimmed": True, "head_cut_seconds": 1.65},
                          {"unit_id": "A", "trimmed": False, "head_cut_seconds": 0.0}]}
        self.assertEqual(pic.cut_windows(["A", "B", "C"], {"A": 5.0, "B": 5.0, "C": 4.0}, tail, head),
                         {"A": (0.0, 4.4), "B": (1.65, 3.042), "C": (0.0, 4.0)})

    def test_report_renders_only_locked_pushing_units_and_never_raises(self):
        with tempfile.TemporaryDirectory() as d:
            clips = {}
            for uid in ("E06-VU-001", "E06-VU-002", "E06-VU-003"):
                clips[uid] = Path(d) / f"{uid}.mp4"
                clips[uid].write_bytes(uid.encode())

            def render(clip, out, plan):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"compensated " + clip.read_bytes())
                return {"frames": 1}
            windows = {uid: (0.0, 4.4) for uid in clips}
            report = pic.build_report("E06", self.GROUPING, clips, windows, Path(d) / "out",
                                      measure_fn=lambda _c, _t: samples(PUSH), render_fn=render)
            rows = report["units"]
            self.assertEqual(report["compensated_units"], ["E06-VU-001"])
            self.assertEqual(rows["E06-VU-002"]["status"], "SKIPPED_MOVING_CAMERA")
            self.assertEqual(rows["E06-VU-003"]["status"], "SKIPPED_MOVING_CAMERA")
            row = rows["E06-VU-001"]
            self.assertEqual(row["source_sha256"], pic.sha256_file(clips["E06-VU-001"]))
            self.assertEqual(pic.applied_sources(report), {"E06-VU-001": row})
            Path(row["output"]).write_bytes(b"changed after the report")
            self.assertEqual(pic.applied_sources(report), {})  # a stale output is never used

            def boom(*_a):
                raise RuntimeError("decode")
            failed = pic.build_report("E06", self.GROUPING, clips, windows, Path(d) / "out", measure_fn=boom)
            self.assertTrue(failed["units"]["E06-VU-001"]["status"].startswith("SKIPPED_ERROR:RuntimeError"))
            failed = pic.build_report("E06", self.GROUPING, clips, windows, Path(d) / "out",
                                      measure_fn=lambda _c, _t: samples(PUSH), render_fn=boom)
            self.assertTrue(failed["units"]["E06-VU-001"]["status"].startswith("SKIPPED_RENDER_ERROR"))
            self.assertEqual(failed["compensated_units"], [])


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")
class RenderTests(unittest.TestCase):
    def test_render_keeps_frames_duration_and_audio(self):
        try:
            import cv2  # noqa: F401
        except ImportError:  # pragma: no cover
            self.skipTest("OpenCV not installed")
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "E06-VU-001.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=144x256:rate=24:duration=2",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt",
                            "yuv420p", "-c:a", "aac", "-shortest", str(src)], check=True)
            plan = pic.analyze(samples(PUSH, end=2.0))
            out = Path(d) / "out" / "E06-VU-001.mp4"
            info = pic.render(src, out, plan)
            before, after = pic.probe(src), pic.probe(out)
            self.assertEqual((after["width"], after["height"], after["frames"]), (144, 256, before["frames"]))
            self.assertTrue(info["audio_bit_exact"])
            self.assertEqual(pic._audio_md5(src, "ffmpeg"), pic._audio_md5(out, "ffmpeg"))


class BuildTests(unittest.TestCase):
    def test_compensated_clip_replaces_picture_and_sound_of_its_unit_only(self):
        sys.path.insert(0, str(ROOT / "tools" / "tests"))
        import test_dialogue_tail_trim as tail_tests
        build_tests = tail_tests.BuildTests()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plain = build_tests._build(root, "a").read_bytes()
            source = root / "E99-VU-001.mp4"
            out = root / "push_in_compensation" / "E99-VU-001.mp4"
            out.parent.mkdir()
            out.write_bytes(b"compensated")
            report = root / "push.json"
            row = {"status": "APPLIED", "source": str(source), "source_sha256": pic.sha256_file(source),
                   "output": str(out), "output_sha256": pic.sha256_file(out), "max_crop": 1.6, "cap_hit": True}
            report.write_text(json.dumps({"units": {"E99-VU-001": row,
                                                    "E99-VU-002": {"status": "NO_PUSH_IN"}}}))
            payload = json.loads(build_tests._build(root, "p", push_in_compensation=report).read_text())
            video = payload["timeline"]["videoTracks"][0]["clips"]
            audio = payload["timeline"]["audioTracks"][0]["clips"]
            self.assertEqual([Path(c["source"]).name for c in video], ["E99-VU-001.mp4", "E99-VU-002.mp4"])
            self.assertEqual((video[0]["source"], audio[0]["source"]), (str(out), str(out)))
            self.assertEqual((video[1]["source"], audio[1]["source"]), (str(root / "E99-VU-002.mp4"),) * 2)
            self.assertEqual(video[0]["metadata"]["push_in_compensation"]["original_source"], str(source))
            self.assertNotIn("push_in_compensation", video[1]["metadata"])
            # a stale report (source changed since) is ignored; no report = byte-identical project
            report.write_text(json.dumps({"units": {"E99-VU-001": {**row, "source_sha256": "0" * 64}}}))
            payload = json.loads(build_tests._build(root, "s", push_in_compensation=report).read_text())
            self.assertNotEqual(payload["timeline"]["videoTracks"][0]["clips"][0]["source"], str(out))
            none = build_tests._build(root, "b", push_in_compensation=None).read_bytes()
            self.assertEqual(plain.replace(b"adm_a", b"X").replace(b"project_a", b"X"),
                             none.replace(b"adm_b", b"X").replace(b"project_b", b"X"))


class PipelineWiringTests(unittest.TestCase):
    def ctx(self, d: Path, contract: dict):
        (d / "video").mkdir()
        (d / "assembly").mkdir()
        (d / "contract.json").write_text(json.dumps(contract))
        (d / "grouping.json").write_text(json.dumps({"units": [{"unit_id": "E06-VU-001",
                                                               "camera_plan": {"motion_family": "LOCKED"}}]}))
        (d / "video" / "E06-VU-001.mp4").write_bytes(b"clip")
        return SimpleNamespace(episode="E06", p=SimpleNamespace(video_media=d / "video", assembly=d / "assembly",
                                                                grouping_plan=d / "grouping.json"))

    def test_unstamped_episode_is_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = self.ctx(Path(d), LEGACY)
            res = npl.StageResult(npl.PASS)
            self.assertIsNone(npl.s7_push_in_compensation(ctx, res, LEGACY))
            self.assertEqual(list((Path(d) / "assembly").iterdir()), [])
            self.assertNotIn("push_in_compensation", res.details)

    def test_failure_is_recorded_and_never_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = self.ctx(Path(d), STAMPED)
            res = npl.StageResult(npl.PASS)
            with mock.patch.object(flat_pic, "face_backend", side_effect=RuntimeError("INSIGHTFACE_RUNTIME_UNAVAILABLE")), \
                    mock.patch.object(npl, "_probe_seconds", return_value=4.0):
                self.assertIsNone(npl.s7_push_in_compensation(ctx, res, STAMPED))
            report = json.loads((Path(d) / "assembly" / "E06_PUSH_IN_COMPENSATION.json").read_text())
            self.assertTrue(report["status"].startswith("SKIPPED_ERROR:RuntimeError"))
            self.assertEqual(res.status, npl.PASS)
            self.assertEqual(res.blockers, [])

    def test_compensated_report_is_handed_to_the_build(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = self.ctx(Path(d), STAMPED)
            res = npl.StageResult(npl.PASS)

            def render(clip, out, plan, **_k):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"compensated")
                return {"frames": 1}
            with mock.patch.object(flat_pic, "face_backend", return_value=object()), \
                    mock.patch.object(flat_pic, "measure", lambda *_a, **_k: samples(PUSH)), \
                    mock.patch.object(flat_pic, "render", render), \
                    mock.patch.object(npl, "_probe_seconds", return_value=4.4):
                path = npl.s7_push_in_compensation(ctx, res, STAMPED)
            self.assertEqual(path, Path(d) / "assembly" / "E06_PUSH_IN_COMPENSATION.json")
            self.assertEqual(res.details["push_in_compensation"]["compensated_units"], ["E06-VU-001"])
            self.assertTrue((Path(d) / "assembly" / "push_in_compensation" / "E06-VU-001.mp4").is_file())


if __name__ == "__main__":
    unittest.main()
