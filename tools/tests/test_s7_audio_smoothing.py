"""S7 sound smoothing (line owner 2026-10-27, lab Holmes E07: "BGM not continuous between shots, the sound goes
louder/quieter").  CAMERA_GRAMMAR_V1 only: merged smooth BGM duck, per-unit native-audio levelling (+-6 dB) before
the AgentCut build, equal-power audio crossfades / fade-throughs at every cut.  Unstamped episodes: byte-identical.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nalu_pipeline as npl  # noqa: E402
import nalu_selective_bgm as sbgm  # noqa: E402
from tools import render_portable_timeline as rpt  # noqa: E402
from tools import s7_audio_smoothing as smooth  # noqa: E402

STAMPED = {"episode": "E07", "camera_grammar_policy": "CAMERA_GRAMMAR_V1"}
LEGACY = {"episode": "E07", "camera_grammar_policy": "LEGACY_FORCED_MOTION"}

E07_WINDOWS = [(23.3, 24.22), (29.134, 30.114), (30.556, 34.716), (38.056, 42.816), (55.181, 57.841),
               (61.265, 63.055), (66.339, 70.499), (70.797, 74.837), (91.671, 94.401), (94.679, 98.879),
               (99.137, 103.377), (103.595, 107.695)]


def cue(**extra):
    return {"timeline_start": 21.43, "duration": 86.612, "volume": 0.14, "dialogue_duck_db": -8.0,
            "dialogue_windows": [{"start": a, "end": b, "unit_id": "U"} for a, b in E07_WINDOWS], **extra}


class BgmDuckTest(unittest.TestCase):
    def test_close_lines_merge_into_one_duck(self) -> None:
        merged = smooth.merge_windows(cue()["dialogue_windows"])
        self.assertEqual(merged, [(23.3, 24.22), (29.134, 34.716), (38.056, 42.816), (55.181, 57.841),
                                  (61.265, 63.055), (66.339, 74.837), (91.671, 107.695)])
        self.assertEqual(smooth.merge_windows([{"start": 0, "end": 1}, {"start": 3.6, "end": 4}]), [(0.0, 1.0), (3.6, 4.0)])

    def test_smooth_duck_expression(self) -> None:
        row = cue(dialogue_duck_db=smooth.STAMPED_DUCK_DB, duck_shape=smooth.duck_shape(cue()["dialogue_windows"]))
        expr = sbgm.duck_expr(row)
        self.assertEqual(expr.count("cos(PI*"), 7)          # one ramp pair per merged window
        self.assertTrue(expr.startswith("1-(1-0.5012)*"))   # -6 dB
        self.assertIn("/0.4,0,1)", expr)                    # 0.4 s down
        self.assertIn("/1.2,0,1)", expr)                    # 1.2 s up
        self.assertGreaterEqual(smooth.STAMPED_DUCK_DB, -6.0)  # bgm_authenticity_gate -6..-10 contract
        self.assertLessEqual(smooth.STAMPED_DUCK_DB, -6.0)

    def test_unstamped_duck_expression_is_unchanged(self) -> None:
        row = cue(dialogue_windows=[{"start": 23.3, "end": 24.22}, {"start": 29.134, "end": 30.114}])
        self.assertEqual(sbgm.duck_expr(row),
                         "1-(1-0.3981)*(max(max(0,min(1,min((t-(1.620))/0.25,((3.040)-t)/0.25))),"
                         "max(0,min(1,min((t-(7.454))/0.25,((8.934)-t)/0.25)))))")
        self.assertIsNone(sbgm._smoothing(LEGACY, "E07"))
        self.assertIs(sbgm._smoothing(STAMPED, "E07"), sys.modules["s7_audio_smoothing"])


class UnitLevellingTest(unittest.TestCase):
    def test_gain_is_clamped_to_six_db(self) -> None:
        self.assertEqual(smooth.plan_gain(-40.5, -22.0)["gain_db"], 6.0)
        self.assertEqual(smooth.plan_gain(-12.3, -18.0)["gain_db"], -5.7)
        self.assertTrue(smooth.plan_gain(-10.0, -18.0)["clamped"])

    def test_report_measures_dialogue_on_speech_and_renders(self) -> None:
        measured = []

        def measure(clip, spans):
            measured.append((Path(clip).name, spans))
            return {"integrated_loudness_lufs": -12.0 if "A" in Path(clip).name else -30.0, "true_peak_dbtp": -3.0}

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            clips = {}
            for uid in ("E07-VU-A", "E07-VU-B"):
                clips[uid] = root / f"{uid}.mp4"
                clips[uid].write_bytes(uid.encode())

            def render(clip, picture, out, gain):
                out.write_bytes(f"{clip.name}:{gain}".encode())
                return {"filter": "x"}

            report = smooth.build_levelling_report(
                "E07", clips, {"E07-VU-A": (1.0, 4.0), "E07-VU-B": (0.0, 3.0)},
                {"E07-VU-A": "DIALOGUE", "E07-VU-B": "AMBIENCE"},
                {"E07-VU-A": [{"start": 0.2, "end": 1.4}, {"start": 1.6, "end": 9.0}]},
                {"DIALOGUE": -18.0, "AMBIENCE": -22.0}, root / "out", measure_fn=measure, render_fn=render)
            a, b = report["units"]["E07-VU-A"], report["units"]["E07-VU-B"]
            self.assertEqual(a["method"], "SPEECH_WINDOWS")
            self.assertEqual(a["spans"], [[1.2, 2.4], [2.6, 4.0]])   # source time, clipped to the cut
            self.assertEqual((a["gain_db"], b["gain_db"]), (-6.0, 6.0))
            self.assertEqual(b["method"], "WHOLE_CUT_WINDOW")
            self.assertEqual(report["applied_units"], ["E07-VU-A", "E07-VU-B"])
            applied = smooth.applied_sources(report)
            self.assertEqual(set(applied), {"E07-VU-A", "E07-VU-B"})
            Path(a["output"]).write_bytes(b"changed")
            self.assertEqual(set(smooth.applied_sources(report)), {"E07-VU-B"})

    def test_pipeline_step_is_stamped_only(self) -> None:
        self.assertIsNone(npl.s7_unit_audio_levelling(mock.Mock(episode="E07"), mock.Mock(), LEGACY, None))


class CrossfadeTest(unittest.TestCase):
    def test_plan_uses_handles_fades_through_without_and_keeps_bridges_hard(self) -> None:
        clips = [{"in": 0.0, "duration": 3.0}, {"in": 0.5, "duration": 3.0}, {"in": 0.0, "duration": 3.0},
                 {"in": 0.0, "duration": 2.0, "metadata": {"sound_bridge_out": {"seconds": 0.5}}},
                 {"in": 0.0, "duration": 2.0}]
        plan = smooth.crossfade_plan(clips, [4.0, 3.5, 3.0, 2.0, 2.0])
        self.assertEqual(plan[0], {"mode": "CROSSFADE", "head": 0.04, "tail": 0.04, "seconds": 0.08, "fade": 0.0})
        self.assertEqual(plan[1]["mode"], "FADE_THROUGH")   # clip 1 has no tail, clip 2 no head
        self.assertEqual(plan[1]["fade"], smooth.FADE_THROUGH_HALF_S)
        self.assertEqual(plan[2]["mode"], "FADE_THROUGH")
        self.assertEqual(plan[3]["mode"], "HARD")

    def _project(self, root: Path, crossfade: bool) -> Path:
        media = []
        for i in range(2):
            path = root / f"u{i}.mp4"
            path.write_bytes(b"x")
            media.append(path)
        clips_v = [{"source": str(media[0]), "start": 0.0, "in": 0.0, "duration": 3.0},
                   {"source": str(media[1]), "start": 3.0, "in": 0.0, "duration": 3.0}]
        clips_a = [{**c, "volume": 0.78} for c in clips_v]
        project = {"metadata": {}, "output": {"path": str(root / "out.mp4")},
                   "timeline": {"videoTracks": [{"clips": clips_v}], "audioTracks": [{"clips": clips_a}]}}
        if crossfade:
            project["metadata"]["audio_cut_crossfade"] = {"seconds": 0.08, "curve": "qsin"}
        path = root / "p.json"
        path.write_text(json.dumps(project), encoding="utf-8")
        return path

    def test_render_without_crossfade_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            command = rpt.build_ffmpeg_command(self._project(Path(td), False))
            graph = command[command.index("-filter_complex") + 1]
            self.assertEqual(graph, ";".join([
                "[0:v:0]trim=start=0.000000:duration=3.000000,setpts=PTS-STARTPTS,scale=720:1280:"
                "force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,fps=24,format=yuv420p[v0]",
                "[0:a:0]atrim=start=0.000000:duration=3.000000,asetpts=PTS-STARTPTS,aresample=48000,volume=0.78[a0]",
                "[1:v:0]trim=start=0.000000:duration=3.000000,setpts=PTS-STARTPTS,scale=720:1280:"
                "force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2:black,fps=24,format=yuv420p[v1]",
                "[1:a:0]atrim=start=0.000000:duration=3.000000,asetpts=PTS-STARTPTS,aresample=48000,volume=0.78[a1]",
                "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vout][aout]"]))

    def test_render_with_crossfade_fades_through_and_locks_slots(self) -> None:
        with tempfile.TemporaryDirectory() as td, mock.patch.object(rpt, "_audio_seconds", return_value=3.0):
            command = rpt.build_ffmpeg_command(self._project(Path(td), True))
            graph = command[command.index("-filter_complex") + 1]
            self.assertIn("tpad=stop_mode=clone:stop=2,trim=end_frame=72", graph)
            self.assertIn("[v0][v1]concat=n=2:v=1:a=0[vout]", graph)
            self.assertIn("afade=t=out:st=2.970000:d=0.030000:curve=qsin[c0]", graph)
            self.assertIn("afade=t=in:st=0:d=0.030000:curve=qsin[c1]", graph)
            self.assertIn("[c0][c1]concat=n=2:v=0:a=1[x1]", graph)
            self.assertTrue(graph.endswith("[x1]apad=whole_dur=6.000000,atrim=duration=6.000000[aout]"))


if __name__ == "__main__":
    unittest.main()
