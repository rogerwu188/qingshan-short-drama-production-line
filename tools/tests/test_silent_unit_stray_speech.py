#!/usr/bin/env python3
"""H3 quality, fleet 2026-11-13: stray speech in silent units (S6 records it, S7 mutes it) and the V2 prompt's
spoken-not-written rule against burned-in subtitles."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
NALU_TOOLS = ROOT / "lines/nalu/runtime/tools"
for _path in (str(ROOT), str(ROOT / "tools"), str(NALU_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tools import silent_unit_stray_speech as stray  # noqa: E402
from tools import h3_director_prompt_v2 as v2  # noqa: E402


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def seg(start: float, end: float, text: str = "我等无疆") -> dict:
    return {"start": start, "end": end, "text": text, "no_speech_prob": 0.05, "avg_logprob": -0.6}


class AssessTests(unittest.TestCase):
    def test_minority_murmur_is_muted_with_padding(self) -> None:
        row = stray.assess([seg(0.34, 1.8)], 6.0)
        self.assertTrue(row["mutable"])
        self.assertEqual(row["type"], stray.ADJUDICATION_TYPE)
        self.assertEqual(row["mute_source_windows"], [[0.26, 1.88]])
        self.assertAlmostEqual(row["speech_seconds"], 1.62)

    def test_close_windows_merge_and_clamp_to_the_clip(self) -> None:
        self.assertEqual(stray.merged_windows([seg(1.33, 2.29), seg(2.4, 2.9), seg(4.9, 5.2)], 5.0),
                         [[1.25, 2.98], [4.82, 5.0]])

    def test_mostly_speech_keeps_the_reject(self) -> None:
        row = stray.assess([seg(0.2, 4.6)], 5.0)
        self.assertFalse(row["mutable"])
        self.assertEqual(row["reason"], "STRAY_SPEECH_COVERS_MOST_OF_THE_CLIP")

    def test_unknown_duration_or_no_window_is_not_muted(self) -> None:
        self.assertFalse(stray.assess([seg(0.2, 1.0)], None)["mutable"])
        self.assertFalse(stray.assess([], 5.0)["mutable"])


def record(*, lines: int = 0, adjudications: list | None = None, sha: str = "a" * 64,
           duration: float = 5.167) -> dict:
    return {"media_sha256": sha,
            "technical_qa": {"checks": {"duration": {"measured_seconds": duration}}},
            "dialogue_qa": {"expected_line_count": lines, "machine_adjudications": adjudications or []}}


class RecordAndPlanTests(unittest.TestCase):
    def test_new_record_uses_the_s6_adjudication(self) -> None:
        adj = stray.assess([seg(0.0, 1.08)], 5.167)
        windows, reason = stray.windows_from_record(record(adjudications=[adj]))
        self.assertEqual(windows, [[0.0, 1.16]])
        self.assertEqual(reason, adj["reason"])

    def test_old_record_is_reassessed_from_real_speech_segments(self) -> None:
        old = record(adjudications=[{"type": "ASR_NO_SPEECH_VERIFICATION",
                                     "real_speech_segments": [seg(0.14, 2.22)]}])
        self.assertEqual(stray.windows_from_record(old)[0], [[0.06, 2.3]])

    def test_dialogue_unit_is_never_muted(self) -> None:
        adj = stray.assess([seg(0.0, 1.0)], 5.0)
        self.assertEqual(stray.windows_from_record(record(lines=1, adjudications=[adj])), ([], "UNIT_HAS_DIALOGUE"))

    def test_plan_binds_the_record_to_the_clip_on_disk(self) -> None:
        adj = stray.assess([seg(0.0, 1.0)], 5.0)
        clips = {"E01-VU-001": Path("/c/E01-VU-001.mp4"), "E01-VU-002": Path("/c/E01-VU-002.mp4"),
                 "E01-VU-003": Path("/c/E01-VU-003.mp4")}
        records = {"E01-VU-001": record(adjudications=[adj]),
                   "E01-VU-002": record(adjudications=[adj], sha="b" * 64)}
        report = stray.plan(clips, records, lambda path: "a" * 64)
        rows = {r["unit_id"]: r for r in report["units"]}
        self.assertTrue(rows["E01-VU-001"]["muted"])
        self.assertEqual(rows["E01-VU-002"]["reason"], "QA_RECORD_MEASURED_ANOTHER_CLIP")
        self.assertEqual(rows["E01-VU-003"]["reason"], "NO_POSTGEN_QA_RECORD")
        self.assertEqual(report["muted_units"], 1)

    def test_timeline_mapping_honours_in_point_trim_and_skips_recut(self) -> None:
        report = {"units": [{"unit_id": "U1", "muted": True, "mute_source_windows": [[0.0, 1.0], [3.5, 4.5]]},
                            {"unit_id": "U2", "muted": True, "mute_source_windows": [[0.0, 1.0]]}]}
        project = {"timeline": {"audioTracks": [{"clips": [
            {"start": 10.0, "in": 0.5, "duration": 3.5, "metadata": {"source_id": "U1"}},
            {"start": 20.0, "in": 0.0, "duration": 4.0, "metadata": {"source_id": "U2", "unit_recut": {"x": 1}}},
        ]}]}}
        self.assertEqual(stray.timeline_windows(report, project),
                         [{"unit_id": "U1", "start_seconds": 10.0, "end_seconds": 10.5},
                          {"unit_id": "U1", "start_seconds": 13.0, "end_seconds": 13.5}])

    def test_mix_filter_mutes_each_window_with_ramps(self) -> None:
        text = stray.mix_filter([{"start_seconds": 1.0, "end_seconds": 2.0}])
        self.assertTrue(text.startswith("asetnsamples=n=64:p=0,volume='"))
        self.assertIn("(1.000000-t)/0.03", text)
        self.assertIn("(t-2.000000)/0.03", text)
        self.assertEqual(stray.gain_expression([]), "1")


class RunnerSilentUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.qa = load("post_generation_qa_runner", NALU_TOOLS / "post_generation_qa_runner.py")

    def _check(self, real: list[dict], duration: float = 6.0) -> dict:
        def fake_run(argv, *, timeout=1800):
            argv = [str(v) for v in argv]
            Path(argv[argv.index("--out") + 1]).write_text(json.dumps({
                "status": "FAIL", "transcript": "我等无疆菜沙", "duration_seconds": duration,
                "failures": ["unexpected_native_mandarin_speech_present"]}), encoding="utf-8")
            return types.SimpleNamespace(returncode=2, stderr="", stdout="")

        verify = {"type": "ASR_NO_SPEECH_VERIFICATION", "segments": real, "real_speech_segments": real}
        engine = lambda name: stray if name == "silent_unit_stray_speech" else None  # noqa: E731
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(self.qa, "_run", fake_run), \
                patch.object(self.qa, "require_ffprobe", return_value="/bin/ffprobe"), \
                patch.object(self.qa, "engine_module", engine), \
                patch.object(self.qa, "_verify_no_speech", lambda media, language="zh": dict(verify)):
            return self.qa.dialogue_check("E08-VU-005", Path(tmp) / "clip.mp4", [], Path(tmp), language="zh")

    def test_short_murmur_is_recorded_not_rejected(self) -> None:
        result = self._check([seg(0.34, 1.8)])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["advisories"],
                         ["dialogue:unexpected_native_mandarin_speech_present:MUTED_AT_S7:1.62s"])
        types_ = [row.get("type") for row in result["machine_adjudications"]]
        self.assertIn(stray.ADJUDICATION_TYPE, types_)
        self.assertEqual(result["duration_seconds"], 6.0)

    def test_mostly_speech_keeps_the_failure(self) -> None:
        result = self._check([seg(0.1, 5.5)])
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failures"], ["unexpected_native_mandarin_speech_present"])
        self.assertEqual(result["advisories"], [])

    def test_song_credit_boilerplate_is_a_known_hallucination(self) -> None:
        self.assertTrue(any(p in "詞曲 李宗盛" for p in self.qa.ASR_HALLUCINATION_PATTERNS))


class DirectorV2SpokenNotWrittenTests(unittest.TestCase):
    def test_stamped_dialogue_unit_says_the_line_is_heard_not_written(self) -> None:
        from tools.tests.test_h3_director_prompt_v2 import render
        text, _ = render()
        dialogue = text.split("\n\nDialogue (", 1)[1].split("\n\n", 1)[0]
        self.assertIn(v2.SPOKEN_NOT_WRITTEN_ONE, dialogue)
        self.assertLess(dialogue.index("</d>"), dialogue.index(v2.SPOKEN_NOT_WRITTEN_ONE))
        self.assertIn("Never: " + v2.NEVER_V2_STAMPED.split(";")[0], text)
        # no all-caps label H3 could voice, and the scope-gate marker survives
        self.assertNotIn("TEXT-FREE", text)
        self.assertIn("captions, subtitles", text)

    def test_unstamped_units_keep_the_old_wording(self) -> None:
        from tools.tests.test_h3_director_prompt_v2 import render
        text, _ = render(director=False)
        self.assertNotIn(v2.SPOKEN_NOT_WRITTEN_ONE, text)
        self.assertIn("Never: " + v2.NEVER_V2, text)


if __name__ == "__main__":
    unittest.main()
