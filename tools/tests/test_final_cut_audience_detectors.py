import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools import final_cut_audience_detectors as fcd

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "e04_negative_sample"
ROOT = Path(__file__).resolve().parents[2]


def line(start: float, end: float, **extra) -> dict:
    row = {"start": start, "end": end, "f0_median_hz": 180.0, "rms_dbfs": -14.0, "lufs_window": -14.0}
    row.update(extra)
    return row


class HookTests(unittest.TestCase):
    def test_dialogue_inside_window_passes(self):
        row = fcd.decide_hook(3.2, 4.0, hook_seconds=5.0, cut_threshold=25.0)
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["evidence"]["fired"], ["dialogue"])

    def test_shock_cut_passes_without_dialogue(self):
        row = fcd.decide_hook(40.0, 41.0, hook_seconds=5.0, cut_threshold=25.0)
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["evidence"]["fired"], ["shock_cut"])

    def test_neither_fails(self):
        row = fcd.decide_hook(47.3, 10.4, hook_seconds=5.0, cut_threshold=25.0, max_frame_diff=27.0)
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["failures"], ["HOOK_MISSING"])
        self.assertEqual(row["measured"]["max_frame_diff"], 27.0)

    def test_no_inputs_is_unverified(self):
        self.assertEqual(fcd.decide_hook(None, None, hook_seconds=5.0, cut_threshold=25.0)["status"], "UNVERIFIED")


class CoverageAndGapTests(unittest.TestCase):
    def test_coverage_threshold(self):
        segs = [line(0, 20), line(30, 50)]
        self.assertEqual(fcd.decide_coverage(segs, 100.0, min_coverage=0.35)["status"], "PASS")
        self.assertEqual(fcd.decide_coverage(segs, 200.0, min_coverage=0.35)["status"], "FAIL")
        self.assertEqual(fcd.decide_coverage(segs, None, min_coverage=0.35)["status"], "UNVERIFIED")

    def test_leading_gap_counts_and_trailing_gap_does_not(self):
        segs = [line(20, 22), line(24, 26)]
        row = fcd.decide_silence_gaps(segs, 60.0, max_run=15.0, max_run_action=25.0)
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["measured"]["largest_gap_s"], 20.0)
        self.assertEqual(row["measured"]["trailing_gap_s"], 34.0)
        self.assertTrue(row["failures"][0].startswith("SILENT_RUN:0.0-20.0"))

    def test_action_window_uses_longer_limit(self):
        segs = [line(0, 2), line(22, 24)]
        strict = fcd.decide_silence_gaps(segs, 30.0, max_run=15.0, max_run_action=25.0)
        self.assertEqual(strict["status"], "FAIL")
        relaxed = fcd.decide_silence_gaps(segs, 30.0, max_run=15.0, max_run_action=25.0, action_windows=[[1.0, 23.0]])
        self.assertEqual(relaxed["status"], "PASS")

    def test_no_speech_at_all_is_one_leading_gap(self):
        row = fcd.decide_silence_gaps([], 40.0, max_run=15.0, max_run_action=25.0)
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["measured"]["largest_gap_s"], 40.0)


class LexiconTests(unittest.TestCase):
    LEXICON = {"forbidden_terms": ["变异", "系统"], "canonical_names": {"秦铭": ["秦明"]}}

    def test_no_lexicon_is_unverified(self):
        self.assertEqual(fcd.decide_lexicon(None, asr_texts=[], subtitle_texts=[], ocr_texts=[])["status"], "UNVERIFIED")

    def test_forbidden_term_in_subtitle_fails(self):
        row = fcd.decide_lexicon(self.LEXICON, asr_texts=[], subtitle_texts=["这是 变 异 的生物"], ocr_texts=[])
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("LEXICON_FORBIDDEN:变异:subtitle", row["failures"])

    def test_name_variant_in_ocr_fails_but_asr_variant_does_not(self):
        row = fcd.decide_lexicon(self.LEXICON, asr_texts=[{"start": 1.0, "text": "秦明回来了"}], subtitle_texts=[], ocr_texts=[])
        self.assertEqual(row["status"], "PASS")
        row = fcd.decide_lexicon(self.LEXICON, asr_texts=[], subtitle_texts=[], ocr_texts=[{"time": 2.5, "text": "秦明回来了"}])
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("NAME_VARIANT:秦明:ocr", row["failures"])

    def test_asr_only_forbidden_hit_is_marked_and_fails(self):
        row = fcd.decide_lexicon(self.LEXICON, asr_texts=[{"start": 9.0, "text": "系统提示"}], subtitle_texts=["无"], ocr_texts=[])
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("LEXICON_FORBIDDEN:系统:asr", row["failures"])
        hit = row["evidence"]["hits"][0]
        self.assertTrue(hit["asr_only"])
        self.assertNotIn("text", hit)

    def test_normalise_text_drops_punctuation_and_folds_width(self):
        self.assertEqual(fcd.normalise_text("Ｓystem, 系统！"), "system系统")


class MascotAndLoudnessTests(unittest.TestCase):
    def test_mascot_requires_brand_and_story(self):
        self.assertEqual(fcd.decide_mascot(None, threshold=0.85, brand_available=False, story_available=True)["status"], "UNVERIFIED")
        self.assertEqual(fcd.decide_mascot(None, threshold=0.85, brand_available=True, story_available=False)["status"], "UNVERIFIED")

    def test_mascot_scores(self):
        scores = [{"time": 1.0, "template": "endcard.png", "score": 0.3}, {"time": 2.0, "template": "endcard.png", "score": 0.91}]
        row = fcd.decide_mascot(scores, threshold=0.85, brand_available=True, story_available=True)
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["failures"], ["MASCOT_IN_STORY:endcard.png:2.0"])
        row = fcd.decide_mascot(scores[:1], threshold=0.85, brand_available=True, story_available=True)
        self.assertEqual(row["status"], "PASS")

    def test_loudness_pass(self):
        windows = [line(0, 1, lufs_window=-13.0), line(2, 3, lufs_window=-15.0)]
        row = fcd.decide_loudness(-14.2, -1.5, windows, release_lufs=-14.0, tolerance=1.0, release_tp=-1.0,
                                  window_range=(-18, -12), adjacent_delta_max=6.0)
        self.assertEqual(row["status"], "PASS")

    def test_loudness_failures_each_named(self):
        windows = [line(0, 1, lufs_window=-11.0), line(2, 3, lufs_window=-17.5), line(4, 5, lufs_window=None)]
        row = fcd.decide_loudness(-16.0, -0.5, windows, release_lufs=-14.0, tolerance=1.0, release_tp=-1.0,
                                  window_range=(-18, -12), adjacent_delta_max=6.0)
        self.assertEqual(row["status"], "FAIL")
        self.assertIn("LOUDNESS_INTEGRATED_OUT_OF_BAND:-16.0", row["failures"])
        self.assertIn("TRUE_PEAK_OVER:-0.5", row["failures"])
        self.assertIn("WINDOW_LUFS_OUT_OF_RANGE:0.0:-11.0", row["failures"])
        self.assertTrue(any(f.startswith("ADJACENT_LINE_DELTA:0.0->2.0:6.5") for f in row["failures"]))
        self.assertEqual(row["measured"]["windows_measured"], 2)

    def test_loudness_unmeasured_is_unverified(self):
        row = fcd.decide_loudness(None, None, [], release_lufs=-14.0, tolerance=1.0, release_tp=-1.0,
                                  window_range=(-18, -12), adjacent_delta_max=6.0)
        self.assertEqual(row["status"], "UNVERIFIED")


class ReportAssemblyTests(unittest.TestCase):
    def test_overall_status_and_unverified_list(self):
        detectors = {"a": fcd.detector("PASS"), "b": fcd.detector("UNVERIFIED", reason="x"), "c": fcd.detector("NOT_IMPLEMENTED")}
        self.assertEqual(fcd.overall_status(detectors), ("UNVERIFIED", ["b", "c"]))
        detectors["d"] = fcd.detector("FAIL")
        self.assertEqual(fcd.overall_status(detectors)[0], "FAIL")
        self.assertEqual(fcd.overall_status({"a": fcd.detector("PASS")}), ("PASS", []))

    def test_missing_inputs_never_pass(self):
        report = fcd.evaluate_from_measurements({"duration_s": 60.0, "segments": [line(1, 30)], "max_cut_spike": 30.0,
                                                 "integrated_lufs": -14.0, "true_peak_dbtp": -2.0})
        det = report["detectors"]
        self.assertEqual(det["hook_present"]["status"], "PASS")
        self.assertEqual(det["dialogue_coverage"]["status"], "PASS")
        self.assertEqual(det["silence_gap_max"]["status"], "PASS")
        self.assertEqual(det["loudness"]["status"], "PASS")
        for name in ("voice_distinctness", "emotion_dynamics", "lexicon_violation", "mascot_in_story",
                     "subtitle_asr_agreement"):
            self.assertEqual(det[name]["status"], "UNVERIFIED", name)
            self.assertTrue(det[name]["reason"])
        for name in fcd.HUMAN_REVIEW_DETECTORS:
            self.assertEqual(det[name], {"status": "NOT_IMPLEMENTED", "measured": None, "threshold": None,
                                         "evidence": {}, "reason": "human review question"})
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertEqual(set(report["unverified"]), {"voice_distinctness", "emotion_dynamics", "lexicon_violation",
                                                     "mascot_in_story", "subtitle_asr_agreement",
                                                     *fcd.HUMAN_REVIEW_DETECTORS})
        self.assertEqual(list(report["detectors"]), list(fcd.DETECTOR_ORDER))
        self.assertEqual(report["schema"], fcd.SCHEMA)

    def test_speaker_map_by_time_and_index(self):
        segs = [line(47.31, 48.51), line(54.94, 56.9), line(60.74, 61.5)]
        rows = fcd.apply_speaker_map(segs, [
            {"time": 47.3, "speaker": "A", "emotion": "calm", "scene": "S1"},
            {"index": 2, "speaker": "B"},
            {"time": 90.0, "speaker": "ZZ"},
        ])
        self.assertEqual(rows[0]["speaker"], "A")
        self.assertEqual(rows[0]["scene"], "S1")
        self.assertEqual(rows[2]["speaker"], "B")
        self.assertNotIn("speaker", rows[1])
        self.assertEqual(rows[0]["_speaker_map_unmatched"][0]["speaker"], "ZZ")

    def test_parse_ass_strips_tags(self):
        with tempfile.TemporaryDirectory(prefix="fcd_ass_") as tmp:
            path = Path(tmp) / "sub.ass"
            path.write_text("[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                            "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,{\\an8}第一行\\N第二行\n"
                            "Comment: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,忽略\n", encoding="utf-8")
            self.assertEqual(fcd.parse_ass_texts(path), ["第一行 第二行"])

    def test_story_windows_from_release_timeline(self):
        with tempfile.TemporaryDirectory(prefix="fcd_tl_") as tmp:
            path = Path(tmp) / "release_timeline.json"
            path.write_text(json.dumps({"content_runtime_seconds": 10.0, "segments": [
                {"unit_id": "U1", "output_start": 0.0, "output_end": 4.0},
                {"unit_id": "U2", "output_start": 4.0, "output_end": 8.0, "type": "action"},
                {"unit_id": "END", "output_start": 8.0, "output_end": 13.0, "type": "endcard"},
                {"unit_id": "U3", "output_start": 9.0, "output_end": 13.0},
            ]}), encoding="utf-8")
            story, action = fcd.load_story_windows(path)
            self.assertEqual(story, [[0.0, 4.0], [4.0, 8.0], [9.0, 10.0]])
            self.assertEqual(action, [[4.0, 8.0]])


def fixture_measurements(fixture: dict) -> dict:
    segments = fcd.apply_speaker_map(fixture["segments"], fixture["speaker_map"]["lines"])
    return {
        "duration_s": fixture["duration_s"],
        "segments": segments,
        "max_cut_spike": fixture["frame_analysis_first_5s"]["max_cut_spike"],
        "max_frame_diff": fixture["frame_analysis_first_5s"]["max_frame_diff"],
        "integrated_lufs": fixture["integrated_lufs"],
        "true_peak_dbtp": fixture["true_peak_dbtp"],
        "voice_cast": fixture["voice_cast"],
    }


class E04NegativeSampleRegressionTests(unittest.TestCase):
    """The E04 final cut must fail exactly the way the audit report describes (report §一 #1, #8, #9, #10)."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads((FIXTURE_DIR / "audio_metrics.json").read_text(encoding="utf-8"))
        cls.summary = json.loads((FIXTURE_DIR / "final_cut_summary.json").read_text(encoding="utf-8"))
        cls.report = fcd.evaluate_from_measurements(fixture_measurements(cls.fixture))

    def test_fixture_contains_no_text_or_personal_paths(self):
        raw = (FIXTURE_DIR / "audio_metrics.json").read_text(encoding="utf-8")
        for banned in ("/Users/", "/home/", '"text"'):   # no personal paths, no dialogue text
            self.assertNotIn(banned, raw)
        self.assertIn("derived_from", self.fixture)
        self.assertEqual(self.summary["duration"], self.fixture["duration_s"])

    def test_hook_present_fails(self):
        row = self.report["detectors"]["hook_present"]
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["evidence"]["fired"], [])
        self.assertGreater(row["measured"]["first_speech_s"], 40.0)

    def test_dialogue_coverage_fails_at_0_206(self):
        row = self.report["detectors"]["dialogue_coverage"]
        self.assertEqual(row["status"], "FAIL")
        self.assertAlmostEqual(row["measured"]["coverage"], 0.206, delta=0.01)
        self.assertAlmostEqual(row["measured"]["coverage"], self.summary["coverage"], delta=0.001)

    def test_silence_gap_max_fails_at_47_3_seconds(self):
        row = self.report["detectors"]["silence_gap_max"]
        self.assertEqual(row["status"], "FAIL")
        self.assertAlmostEqual(row["measured"]["largest_gap_s"], 47.3, delta=0.2)
        self.assertEqual(row["measured"]["largest_gap"]["kind"], "leading")
        self.assertGreaterEqual(row["measured"]["gaps_over_limit"], 3)

    def test_voice_distinctness_fails_with_collision(self):
        row = self.report["detectors"]["voice_distinctness"]
        self.assertEqual(row["status"], "FAIL")
        collisions = [f for f in row["failures"] if f.startswith("VOICE_COLLISION:")]
        self.assertTrue(collisions, row["failures"])
        self.assertIn("VOICE_COLLISION:CHAR-HUYONG:CHAR-VILLAGER-A", collisions)   # 求饶者 / 指责者 same register
        self.assertIn("VOICE_COLLISION:CHAR-LUWENRUI:CHAR-MAYANG", collisions)     # 救命啊 / 松子真香 same voice
        self.assertTrue(any(f.startswith("VOICE_OUT_OF_BAND:CHAR-HUYONG:") for f in row["failures"]))

    def test_emotion_dynamics_fails_flat_plead_against_calm_baseline(self):
        row = self.report["detectors"]["emotion_dynamics"]
        self.assertEqual(row["status"], "FAIL")
        flat = [f for f in row["failures"] if f.startswith("FLAT_EMOTION:CHAR-MAYANG:151.")]
        self.assertEqual(len(flat), 1, row["failures"])
        baseline = row["measured"]["calm_baseline_dbfs"]["CHAR-MAYANG"]
        calm_line = next(s for s in self.fixture["segments"] if abs(s["start"] - 60.7) < 0.3)
        self.assertEqual(baseline, calm_line["rms_dbfs"])
        plead = next(l for l in row["measured"]["emotive_lines"] if abs(l["start"] - 151.7) < 0.3)
        self.assertLess(plead["delta_db"], 6.0)
        self.assertIn("NO_CALM_BASELINE:CHAR-HUYONG", row["evidence"]["unverified"])

    def test_loudness_fails_against_minus_14(self):
        row = self.report["detectors"]["loudness"]
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["measured"]["integrated_lufs"], -16.0)
        self.assertIn("LOUDNESS_INTEGRATED_OUT_OF_BAND:-16.0", row["failures"])
        self.assertLessEqual(row["measured"]["true_peak_dbtp"], -1.0)

    def test_overall_fail_and_unverified_list(self):
        self.assertEqual(self.report["status"], "FAIL")
        # subtitle_asr_agreement is UNVERIFIED here: the fixture carries no subtitle cues / read-back (K136)
        self.assertEqual(set(self.report["unverified"]), {"lexicon_violation", "mascot_in_story", "subtitle_asr_agreement",
                                                          *fcd.HUMAN_REVIEW_DETECTORS})
        for name in fcd.HUMAN_REVIEW_DETECTORS:
            self.assertEqual(self.report["detectors"][name]["status"], "NOT_IMPLEMENTED")

    def test_precheck_on_fixture_cast_fails_the_two_elders_under_the_40hz_rule(self):
        from tools import voice_cast_gate as vcg

        result = vcg.precheck(self.fixture["voice_cast"], self.fixture["scene_copresence"])
        # before 2026-10-30 the overlapping elders were only REQUIRES_HUMAN; Roger's E12 ruling (K135) makes
        # a co-present pair under 40 Hz apart a hard FAIL, while the overlap note is still recorded
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("F0_BAND_OVERLAP_REQUIRES_HUMAN:CHAR-LUZE:CHAR-MAYANG", result["requires_human"])
        self.assertTrue(any(f.startswith("F0_MEDIAN_SEPARATION_LT_40HZ:CHAR-LUZE:CHAR-MAYANG:") for f in result["failures"]),
                        result["failures"])


@unittest.skipUnless(os.environ.get("NALU_E04_NEGATIVE_SAMPLE") and Path(os.environ["NALU_E04_NEGATIVE_SAMPLE"]).is_file(),
                     "set NALU_E04_NEGATIVE_SAMPLE to the local E04 final cut to run the live regression")
class E04LiveCliTests(unittest.TestCase):
    """Runs the real CLI (ASR + F0 + ebur128 + frame analysis) on the local E04 deliverable."""

    def test_cli_end_to_end_matches_fixture_statuses(self):
        fixture = json.loads((FIXTURE_DIR / "audio_metrics.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="fcd_live_") as tmp:
            root = Path(tmp)
            (root / "voice_cast.json").write_text(json.dumps(fixture["voice_cast"]), encoding="utf-8")
            (root / "speaker_map.json").write_text(json.dumps(fixture["speaker_map"]), encoding="utf-8")
            out = root / "detectors.json"
            proc = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "final_cut_audience_detectors.py"),
                 "--media", os.environ["NALU_E04_NEGATIVE_SAMPLE"], "--out", str(out),
                 "--voice-cast", str(root / "voice_cast.json"), "--speaker-map", str(root / "speaker_map.json")],
                cwd=str(ROOT), env={**os.environ, "PYTHONPATH": str(ROOT)}, capture_output=True, text=True, check=False,
            )
            self.assertEqual(proc.returncode, 1, proc.stderr[-2000:])
            report = json.loads(out.read_text(encoding="utf-8"))
        det = report["detectors"]
        self.assertEqual(report["status"], "FAIL")
        for name in ("hook_present", "dialogue_coverage", "silence_gap_max", "voice_distinctness", "emotion_dynamics", "loudness"):
            self.assertEqual(det[name]["status"], "FAIL", name)
        self.assertAlmostEqual(det["dialogue_coverage"]["measured"]["coverage"], 0.206, delta=0.02)
        self.assertAlmostEqual(det["silence_gap_max"]["measured"]["largest_gap_s"], 47.3, delta=0.5)
        self.assertTrue(any(f.startswith("VOICE_COLLISION:") for f in det["voice_distinctness"]["failures"]))
        self.assertTrue(any(f.startswith("FLAT_EMOTION:CHAR-MAYANG:151.") for f in det["emotion_dynamics"]["failures"]))
        self.assertAlmostEqual(det["loudness"]["measured"]["integrated_lufs"], -16.0, delta=0.3)
        self.assertFalse(report["inputs"]["asr_text_kept"])
        self.assertTrue(all("text" not in seg for seg in report["segments"]))
        self.assertEqual(set(report["unverified"]), {"lexicon_violation", "mascot_in_story", *fcd.HUMAN_REVIEW_DETECTORS})


if __name__ == "__main__":
    unittest.main()


class SubtitleReadbackTests(unittest.TestCase):
    """subtitle_asr_agreement (Roger 2026-10-30 item 1a; F2: H3 babble lives OUTSIDE the cues)."""

    def _readback(self, words):
        return [{"start": words[0][1], "end": words[-1][2], "text": "".join(w[0] for w in words),
                 "words": [{"w": w, "s": s, "e": e} for w, s, e in words]}]

    def test_cue_similarity_keeps_a_cue_that_is_one_of_two_lines_in_the_window(self):
        self.assertGreaterEqual(fcd.cue_similarity("冯兄客气了", "冯兄客气了知道你巡山辛苦"), 0.8)
        self.assertLess(fcd.cue_similarity("冯兄客气了", "troeperandhorwes"), 0.3)
        self.assertEqual(fcd.cue_similarity("", "anything"), 1.0)
        self.assertEqual(fcd.cue_similarity("x", ""), 0.0)

    def test_babble_outside_every_cue_fails_even_when_cues_match(self):
        cues = [{"start": 3.0, "end": 5.0, "text": "冯兄客气了"}]
        words = [("特", 0.2, 0.5), ("罗", 0.5, 0.8), ("佩", 0.8, 1.1), ("尔", 1.1, 1.4),   # 1.2 s babble before the line
                 ("冯", 3.1, 3.4), ("兄", 3.4, 3.7), ("客", 3.7, 4.0), ("气", 4.0, 4.3), ("了", 4.3, 4.6)]
        row = fcd.decide_subtitle_agreement(cues, self._readback(words), similarity=0.8, window_s=1.5,
                                            min_agreement=0.95, outside_max_s=1.0)
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["measured"]["agreement"], 1.0)
        self.assertEqual(row["measured"]["speech_outside_cues_seconds"], 1.2)
        self.assertTrue(any(f.startswith("SPEECH_OUTSIDE_SUBTITLES:") for f in row["failures"]))
        self.assertEqual(row["evidence"]["speech_outside_cues"][0]["start"], 0.2)

    def test_whisper_boilerplate_is_not_speech(self):
        cues = [{"start": 3.0, "end": 5.0, "text": "冯兄客气了"}]
        # boilerplate comes as its own segment (a whole decoded sentence), the line as another
        readback = self._readback([("字幕by索兰娅", 0.2, 1.4)]) + self._readback([("冯兄客气了", 3.1, 4.6)])
        row = fcd.decide_subtitle_agreement(cues, readback, similarity=0.8, window_s=1.5,
                                            min_agreement=0.95, outside_max_s=1.0)
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["measured"]["speech_outside_cues_seconds"], 0.0)

    def test_unheard_line_counts_as_a_non_match(self):
        cues = [{"start": 3.0, "end": 5.0, "text": "冯兄客气了"}, {"start": 8.0, "end": 9.0, "text": "许叔"}]
        words = [("冯兄客气了", 3.1, 4.6)]
        row = fcd.decide_subtitle_agreement(cues, self._readback(words), similarity=0.8, window_s=1.5,
                                            min_agreement=0.95, outside_max_s=1.0)
        self.assertEqual(row["status"], "FAIL")
        self.assertEqual(row["measured"]["agreement"], 0.5)

    def test_incremental_cache_resumes_from_the_last_finished_window(self):
        import tempfile
        from unittest import mock
        calls = []

        def fake_transcribe(media, *, model, language="zh", windows=None, on_window_done=None):
            rows = []
            for i, (s, e) in enumerate(windows or []):
                calls.append((s, e))
                rows.append({"start": s, "end": e, "text": f"w{s}", "words": [{"w": f"w{s}", "s": s, "e": e}]})
                if on_window_done:
                    on_window_done(i, rows)
                if len(calls) == 2 and not getattr(fake_transcribe, "resumed", False):
                    fake_transcribe.resumed = True
                    raise KeyboardInterrupt   # killed after two windows
            return rows

        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "m.mp4"
            media.write_bytes(b"media")
            cache = Path(tmp) / "rb.json"
            windows = [(0.0, 30.0), (30.0, 60.0), (60.0, 90.0), (90.0, 120.0)]     # >= chunk size: no merging
            with mock.patch.object(fcd, "readback_transcribe", fake_transcribe), \
                    mock.patch.object(fcd.dvm, "media_sha256", lambda p: "sha-m"):
                with self.assertRaises(KeyboardInterrupt):
                    fcd.load_or_run_readback(media, cache, model="small", windows=windows)
                partial = json.loads(cache.read_text())
                self.assertTrue(partial["partial"])
                self.assertEqual(partial["windows_done"], 2)
                segments, source = fcd.load_or_run_readback(media, cache, model="small", windows=windows)
            self.assertEqual([s["start"] for s in segments], [0.0, 30.0, 60.0, 90.0])
            self.assertIn("resumed_from_window_2", source)
            self.assertEqual(calls, [(0.0, 30.0), (30.0, 60.0), (60.0, 90.0), (90.0, 120.0)])
            self.assertFalse(json.loads(cache.read_text())["partial"])


class CueSimilarityScriptTests(unittest.TestCase):
    def test_homophone_and_traditional_script_read_as_the_line(self):
        # whisper-small on E12: 微甜→威田, 赶到后→趕到後 — a listener hears the right line
        self.assertGreaterEqual(fcd.cue_similarity(fcd.normalise_subtitle_text("微甜。"), fcd.normalise_subtitle_text("威田")), 0.8)
        self.assertGreaterEqual(fcd.cue_similarity(fcd.normalise_subtitle_text("等我们赶到后，那里也光秃秃了"),
                                                   fcd.normalise_subtitle_text("等我們趕到後,那裡也光突突了")), 0.8)
        # English / gibberish still fails on both scripts
        self.assertLess(fcd.cue_similarity(fcd.normalise_subtitle_text("冯兄客气了"), fcd.normalise_subtitle_text("like a tester trained")), 0.5)


class ReadbackSegmentFilterTests(unittest.TestCase):
    def test_boilerplate_prompt_echo_and_noise_segments_are_dropped_whole(self):
        self.assertFalse(fcd.readback_segment_is_speech({"text": "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目", "no_speech_prob": 0.1, "avg_logprob": -0.3}))
        self.assertFalse(fcd.readback_segment_is_speech({"text": "是普通话对白，简体中文。", "no_speech_prob": 0.1, "avg_logprob": -0.3}))
        # confidently decoded speech under an ambient bed: no_speech alone is high, the line is kept
        self.assertTrue(fcd.readback_segment_is_speech({"text": "冯兄客气了", "no_speech_prob": 0.68, "avg_logprob": -0.22}))
        self.assertTrue(fcd.readback_segment_is_speech({"text": "冯兄客气了", "no_speech_prob": 0.1, "avg_logprob": -1.4}))
        self.assertFalse(fcd.readback_segment_is_speech({"text": "冯兄客气了", "no_speech_prob": 0.9, "avg_logprob": -1.4}))
        self.assertFalse(fcd.readback_segment_is_speech({"text": "冯兄客气了", "no_speech_prob": 0.97, "avg_logprob": -0.3}))
        self.assertTrue(fcd.readback_segment_is_speech({"text": "冯兄客气了", "no_speech_prob": 0.1, "avg_logprob": -0.3}))

    def test_dropped_segments_do_not_count_as_babble(self):
        cues = [{"start": 3.0, "end": 5.0, "text": "冯兄客气了"}]
        readback = [{"start": 0.0, "end": 2.0, "text": "优优独播剧场 YoYo Series Exclusive", "no_speech_prob": 0.2, "avg_logprob": -0.5,
                     "words": [{"w": "优优", "s": 0.0, "e": 0.5}, {"w": "独播剧场", "s": 0.5, "e": 1.2}, {"w": "YoYo", "s": 1.2, "e": 2.0}]},
                    {"start": 3.1, "end": 4.6, "text": "冯兄客气了", "no_speech_prob": 0.05, "avg_logprob": -0.2,
                     "words": [{"w": "冯兄客气了", "s": 3.1, "e": 4.6}]}]
        row = fcd.decide_subtitle_agreement(cues, readback, similarity=0.8, window_s=1.0, min_agreement=0.95, outside_max_s=1.0)
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["measured"]["readback_segments_dropped_as_noise"], 1)


class ReadbackChunkingTests(unittest.TestCase):
    def test_consecutive_unit_windows_merge_into_context_sized_chunks(self):
        windows = [(0.0, 4.3), (4.3, 9.0), (9.0, 15.5), (15.5, 22.0), (22.0, 27.0), (27.0, 31.0), (31.0, 60.0), (60.0, 63.0)]
        chunks = fcd.group_readback_windows(windows, min_s=25.0)
        self.assertEqual(chunks[0], [0.0, 27.0])          # grew until >= 25 s, never split a unit
        self.assertEqual(chunks[1], [27.0, 60.0])
        self.assertEqual(chunks[2], [60.0, 63.0])         # the tail stays its own chunk
        self.assertEqual(fcd.group_readback_windows(None), [])

    def test_a_gap_between_windows_starts_a_new_chunk(self):
        chunks = fcd.group_readback_windows([(0.0, 5.0), (8.0, 12.0)], min_s=25.0)
        self.assertEqual(chunks, [[0.0, 5.0], [8.0, 12.0]])
