#!/usr/bin/env python3
"""English-dialogue path (dialogue_language == "en"): ASR gate, QA runner, subtitles, H3 tags,
speech rate, duration estimates, speaker separators and language resolution.  Chinese stays the
default everywhere; these tests only exercise the "en" branches plus the zh codes they sit beside."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import types
import unittest
try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:  # CI image has no Pillow; production installs it
    HAVE_PIL = False
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
NALU_TOOLS = ROOT / "lines/nalu/runtime/tools"
for _path in (str(ROOT), str(NALU_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


gate = load("source_video_dialogue_gate", ROOT / "tools/source_video_dialogue_gate.py")
burnin = load("build_burnin_subtitles", NALU_TOOLS / "build_burnin_subtitles.py")
speech_rate = load("speech_rate_check", NALU_TOOLS / "speech_rate_check.py")

from tools import dialogue_cut_safety, h3_provider_english_contract, h3_provider_prompt_renderer  # noqa: E402
from tools import initial_asset_library, multimodal_character_binding_guard  # noqa: E402


def probe(*, duration: float = 5.0) -> dict:
    return {"streams": [{"codec_type": "video"}, {"codec_type": "audio"}],
            "format": {"duration": str(duration)}}


class LanguageResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = load("nalu_pipeline", NALU_TOOLS / "nalu_pipeline.py")

    def test_contract_field_wins_over_config(self) -> None:
        resolve = self.pipeline.resolve_dialogue_language
        self.assertEqual(resolve({"dialogue_language": "en"}, {"project": {"language": "zh-CN"}}), "en")
        self.assertEqual(resolve({"dialogue_language": "zh"}, {"project": {"language": "en-US"}}), "zh")

    def test_config_project_language_is_the_fallback(self) -> None:
        resolve = self.pipeline.resolve_dialogue_language
        self.assertEqual(resolve({}, {"project": {"language": "en-US"}}), "en")
        self.assertEqual(resolve(None, {"project": {"language": "zh-CN"}}), "zh")
        self.assertEqual(resolve({"dialogue_language": "fr"}, {"project": {"language": "en-GB"}}), "en")

    def test_default_is_zh(self) -> None:
        resolve = self.pipeline.resolve_dialogue_language
        self.assertEqual(resolve(None, None), "zh")
        self.assertEqual(resolve({}, {"project": {}}), "zh")

    def test_subtitle_name_keeps_zh_and_adds_en(self) -> None:
        p = types.SimpleNamespace(assembly=Path("/tmp/asm"))
        zh = types.SimpleNamespace(p=p, episode="E01")  # a stand-in without .language is the zh line
        en = types.SimpleNamespace(p=p, episode="E01", language="en")
        self.assertEqual(self.pipeline.subtitles_ass_path(zh).name, "E01_subtitles_zh.ass")
        self.assertEqual(self.pipeline.subtitles_ass_path(en).name, "E01_subtitles_en.ass")
        self.assertEqual(self.pipeline.ctx_language_locale(en), "en-US")
        self.assertEqual(self.pipeline.ctx_language_locale(zh), "zh-CN")


class EnglishDialogueGateTests(unittest.TestCase):
    rows = [{"dia_id": "D01", "text": "Don't go back there."}, {"dia_id": "D02", "text": "Why not?"}]

    def test_word_recall_passes_despite_case_and_punctuation(self) -> None:
        report = gate.evaluate(Path("clip.mp4"), self.rows, probe_payload=probe(),
                               transcript="don't go back there why not",
                               segments=[{"start": 0.2, "end": 2.5, "text": "don't go back there why not"}],
                               minimum_recall=0.55, language="en")
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(report["recall_score"], 1.0)
        self.assertEqual(report["language"], "en")

    def test_word_recall_below_threshold_fails(self) -> None:
        report = gate.evaluate(Path("clip.mp4"), self.rows, probe_payload=probe(),
                               transcript="Go home now.",
                               segments=[{"start": 0.2, "end": 1.5, "text": "Go home now."}],
                               minimum_recall=0.55, language="en")
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(code.startswith("dialogue_recall_below_threshold") for code in report["failures"]))

    def test_language_neutral_codes_for_english(self) -> None:
        report = gate.evaluate(Path("clip.mp4"), self.rows, probe_payload=probe(), transcript="",
                               segments=[], minimum_recall=0.55, language="en")
        self.assertIn("native_speech_missing", report["failures"])
        self.assertNotIn("native_mandarin_speech_missing", report["failures"])
        silent = gate.evaluate(Path("clip.mp4"), [], probe_payload=probe(), transcript="Hello there.",
                               segments=[], minimum_recall=0.55, require_no_dialogue=True, language="en")
        self.assertIn("unexpected_native_speech_present", silent["failures"])

    def test_chinese_codes_unchanged(self) -> None:
        report = gate.evaluate(Path("clip.mp4"), [{"dia_id": "D01", "text": "陆哥"}], probe_payload=probe(),
                               transcript="", segments=[], minimum_recall=0.55)
        self.assertIn("native_mandarin_speech_missing", report["failures"])

    def test_recall_counts_words_in_order(self) -> None:
        self.assertAlmostEqual(gate.recall("one two three four", "one two five four", "en"), 0.75)
        self.assertEqual(gate.transcription_prompt("Don't  go\nback.", "en"), "Don't go back.")

    def test_main_transcribes_with_english_language_and_expected_prompt(self) -> None:
        calls: dict = {}

        class FakeModel:
            def __init__(self, *args, **kwargs):
                pass

            def transcribe(self, path, **kwargs):
                calls.update(kwargs)
                segment = types.SimpleNamespace(start=0.2, end=2.0, text=" Don't go back there. Why not?")
                return [segment], None

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            video = tmp_path / "clip.mp4"
            video.write_bytes(b"not really a video")
            dialogue = tmp_path / "dialogue.json"
            dialogue.write_text(json.dumps({"dialogue": self.rows}), encoding="utf-8")
            out = tmp_path / "report.json"
            argv = ["gate", "--video", str(video), "--dialogue-json", str(dialogue), "--out", str(out),
                    "--language", "en"]
            with patch.object(sys, "argv", argv), \
                    patch.object(gate, "resolve_media_binary", return_value=(Path("/bin/ffprobe"), "TEST")), \
                    patch.object(gate, "resolve_whisper_model", return_value=("small", "TEST")), \
                    patch.object(gate, "probe", return_value=probe(duration=5.0)), \
                    patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=FakeModel)}), \
                    patch("builtins.print"):
                code = gate.main()
            report = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(calls["language"], "en")
        self.assertEqual(calls["initial_prompt"], "Don't go back there. Why not?")
        self.assertEqual(code, 0, report["failures"])
        self.assertEqual(report["transcript"], "Don't go back there. Why not?")


class EnglishPostGenerationDialogueCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.qa = load("post_generation_qa_runner", NALU_TOOLS / "post_generation_qa_runner.py")

    def test_dialogue_check_passes_language_and_strips_ascii_speaker(self) -> None:
        seen: dict = {}

        def fake_run(argv, *, timeout=1800):
            seen["argv"] = [str(value) for value in argv]
            report = Path(seen["argv"][seen["argv"].index("--out") + 1])
            contract = Path(seen["argv"][seen["argv"].index("--dialogue-json") + 1])
            seen["contract"] = json.loads(contract.read_text(encoding="utf-8"))
            report.write_text(json.dumps({"status": "FAIL", "transcript": "Go home.",
                                          "failures": ["dialogue_recall_below_threshold:0.000"]}),
                              encoding="utf-8")
            return types.SimpleNamespace(returncode=2, stderr="", stdout="")

        reverify_calls = []

        def fake_reverify(media, expected, language="zh"):
            reverify_calls.append(language)
            return {"status": "REVERIFIED", "recall": 0.2, "transcript": "Go home.", "segments": []}

        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(self.qa, "_run", fake_run), \
                patch.object(self.qa, "require_ffprobe", return_value="/bin/ffprobe"), \
                patch.object(self.qa, "_reverify_dialogue", fake_reverify):
            result = self.qa.dialogue_check(
                "E01-VU-001", Path(tmp) / "clip.mp4",
                [{"shot_id": "S1", "spoken_text": "Detective Harris: Don't go back there."}],
                Path(tmp), language="en")
        self.assertEqual(seen["argv"][seen["argv"].index("--language") + 1], "en")
        self.assertEqual(seen["contract"]["dialogue"][0]["spoken_text"], "Don't go back there.")
        self.assertEqual(reverify_calls, ["en"])
        # no pinyin/homophone rescue on English: the recall miss stays a failure
        self.assertEqual(result["homophone_adjudications"], [])
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["language"], "en")

    def test_english_text_helpers(self) -> None:
        self.assertTrue(self.qa._has_speech_text("Hello", "en"))
        self.assertFalse(self.qa._has_speech_text("Hello", "zh"))
        self.assertEqual(self.qa._script_normalise("Colour", "en"), "Colour")
        self.assertEqual(self.qa._speech_codes("en")["missing"], "native_speech_missing")
        self.assertEqual(self.qa._speech_codes("zh")["missing"], "native_mandarin_speech_missing")


class EnglishSubtitleTests(unittest.TestCase):
    def test_wrap_on_word_boundaries_max_two_lines(self) -> None:
        text = "I told you never to come back here, not after what you did to my family."
        rows = burnin.wrap_en(text).split("\\N")
        self.assertEqual(len(rows), 2)
        self.assertEqual(" ".join(rows), text)
        self.assertTrue(all(len(row) <= burnin.EN_WRAP_CHARS for row in rows))
        self.assertEqual(burnin.wrap_en("Short line."), "Short line.")

    # lab E02 VU-001: a 197-character line was wrapped into 2 rows of ~98 characters and shrunk, so the
    # caption ran off both frame edges.
    E02_VU001 = ("My name is Helen Stoner, and I am living with my stepfather, who is the last survivor of one of "
                 "the oldest Saxon families in England, the Roylotts of Stoke Moran, on the western border of Surrey.")
    E02_VU001_ASR = [{"start": 0.0, "end": 5.68, "text": "My name is Helen Stoner, and I am living with my stepfather, "
                                                          "who is the last survivor of one of"},
                     {"start": 5.68, "end": 12.4, "text": "the oldest Saxon families in England, the Roylets of Stoke "
                                                           "Moran, on the western border of Surrey."}]

    def _fits(self):
        from PIL import Image, ImageDraw, ImageFont
        font = ImageFont.truetype(burnin._media.resolve_latin_font()[0], burnin.EN_FONT_SIZE)
        draw = ImageDraw.Draw(Image.new("RGBA", (8, 8)))

        def fits(chunk: str) -> bool:
            rows = burnin.wrap_en(chunk).split("\\N")
            return len(rows) <= 2 and all(draw.textlength(r, font=font) <= burnin.CAPTION_MAX_WIDTH for r in rows)
        return fits

    @unittest.skipUnless(HAVE_PIL, "Pillow not installed")
    def test_long_line_splits_into_sequential_normal_size_cues(self) -> None:
        fits = self._fits()
        self.assertFalse(fits(self.E02_VU001))
        cues = burnin.split_cues(self.E02_VU001, fits, "en")
        self.assertGreaterEqual(len(cues), 2)
        self.assertEqual(" ".join(cues), self.E02_VU001)
        self.assertTrue(all(fits(cue) for cue in cues))
        self.assertTrue(all(cue[-1] in ",." for cue in cues))  # clause breaks preferred
        bounds = burnin.cue_boundaries(cues, 0.0, 12.4, self.E02_VU001_ASR, "en")
        self.assertEqual((bounds[0], bounds[-1]), (0.0, 12.4))
        self.assertEqual(bounds, sorted(bounds))
        self.assertEqual(len(bounds), len(cues) + 1)
        # a line that fits stays one cue
        self.assertEqual(burnin.split_cues("Pray be precise as to details.", fits, "en"),
                         ["Pray be precise as to details."])

    def test_cue_boundaries_follow_asr_segments(self) -> None:
        segs = [{"start": 0.0, "end": 2.0, "text": "aaaa aaaa"}, {"start": 6.0, "end": 8.0, "text": "bbbb bbbb"}]
        self.assertEqual(burnin.cue_boundaries(["aaaa aaaa", "bbbb bbbb"], 0.0, 8.0, segs, "en"), [0.0, 4.0, 8.0])
        # single segment: proportional to speech characters
        self.assertEqual(burnin.cue_boundaries(["aa", "aaaaaa"], 0.0, 8.0, segs[:1], "en"), [0.0, 2.0, 8.0])

    def test_chinese_long_line_splits_into_two_row_cues(self) -> None:
        text = "一二三四五六七八九十，一二三四五六七八九十一二三四五六七八九十。一二三四五"
        cues = burnin.split_cues(text, lambda c: len(burnin.wrap(c).split("\\N")) <= 2, "zh")
        self.assertEqual("".join(cues), text)
        self.assertTrue(all(len(burnin.wrap(c).split("\\N")) <= 2 for c in cues))

    def test_assignment_matches_english_segments(self) -> None:
        lines = [{"text": "Where were you last night?"}, {"text": "At home, alone."}]
        segs = [{"start": 0.1, "end": 1.0, "text": "Where were you"},
                {"start": 1.0, "end": 1.8, "text": "last night?"},
                {"start": 2.4, "end": 3.4, "text": "At home, alone."}]
        out = burnin.assign(lines, segs, 5.0, "en")
        self.assertEqual([(round(s, 2), round(e, 2)) for _, s, e in out], [(0.1, 1.8), (2.4, 3.4)])
        # the zh path ignores Latin-only segments entirely
        zh = burnin.assign(lines, segs, 5.0)
        self.assertEqual([(s, e) for _, s, e in zh], [(0.0, 2.5), (2.5, 5.0)])

    def test_fewer_segments_split_by_word_count(self) -> None:
        lines = [{"text": "One two three."}, {"text": "Four."}]
        out = burnin.assign(lines, [{"start": 0.0, "end": 4.0, "text": "one two three four"}], 5.0, "en")
        self.assertAlmostEqual(out[0][2], 3.0)
        self.assertAlmostEqual(out[1][2], 4.0)


class EnglishH3TagTests(unittest.TestCase):
    def test_english_dialogue_tag_is_accepted(self) -> None:
        text = "Subject 1 says exactly once <d>[English] Don't go back there.</d>."
        report = h3_provider_english_contract.validate_h3_provider_text_boundary(text, source_id="U1")
        self.assertEqual(report["status"], "PASS", report["failures"])

    def test_cjk_outside_tags_still_fails(self) -> None:
        text = "陆哥 says <d>[English] Hello.</d>"
        report = h3_provider_english_contract.validate_h3_provider_text_boundary(text, source_id="U1")
        self.assertIn("H3_CJK_OUTSIDE_DIALOGUE:U1", report["failures"])

    def test_beat_emits_english_tag_with_ascii_colon(self) -> None:
        source = {"source_index": 1, "start_seconds": 0, "end_seconds": 3,
                  "dialogue": "Harris: Don't go back there."}
        translated = {"entry_state": "standing", "primary_action": "turns.", "exit_state": "still"}
        binding = {"provider_entity_label": "Subject 1", "subject_token": "S1", "image_slot": "@Image1",
                   "speaker_slot": "S1", "audio_slot": "@Audio1", "visible_speaker": True}
        line, evidence = h3_provider_prompt_renderer._beat(source, translated, dialogue_binding=binding,
                                                           language="en")
        self.assertIn("<d>[English] Don't go back there.</d>", line)
        self.assertEqual(evidence["BEAT.1.DIALOGUE_SPEAKER"], "Harris")
        zh_line, _ = h3_provider_prompt_renderer._beat(
            dict(source, dialogue="陆哥：走吧。"), translated, dialogue_binding=binding)
        self.assertIn("<d>[Chinese] 走吧。</d>", zh_line)


class EnglishSpeechRateTests(unittest.TestCase):
    def test_words_per_second_against_english_target(self) -> None:
        contract = {"shots": [{"shot_id": "S1", "prompt_spec": {"dialogue": "Harris: Go now."},
                               "dialogue_delivery": {"english_words_per_second": 3.0}}]}
        targets = speech_rate.shot_targets(contract, "en")
        self.assertEqual(targets["S1"]["cps"], 3.0)
        segments = [{"start": 0.0, "end": 2.0, "text": "Don't go back there, ever."}]
        result = speech_rate.measure_unit("U1", segments, [{"shot_id": "S1", "spoken_text": "x"}],
                                          targets, language="en")
        self.assertEqual(result["rate_unit"], "words_per_second")
        self.assertEqual(result["spoken_chars"], 5)
        self.assertEqual(result["measured_cps"], 2.5)
        self.assertEqual(result["tier"], "OK")
        slow = speech_rate.measure_unit("U1", [{"start": 0.0, "end": 4.0, "text": "Go home now."}],
                                        [{"shot_id": "S1", "spoken_text": "x"}], targets, language="en")
        self.assertEqual(slow["code"], "SPEECH_RATE_UNDER_TARGET_BLOCKER")

    def test_default_target_and_episode_floor(self) -> None:
        targets = speech_rate.shot_targets({"shots": [{"shot_id": "S1", "prompt_spec": {"dialogue": "A: hi"}}]}, "en")
        self.assertEqual(targets["S1"]["cps"], speech_rate.DEFAULT_TARGET_WPS)
        summary = speech_rate.episode_summary([{"unit_id": "U1", "spoken_chars": 5, "speech_seconds": 2.5,
                                                "measured_cps": 2.0, "tier": "OK"}], "en")
        self.assertTrue(summary["below_episode_min"])
        self.assertEqual(summary["episode_mean_min_cps"], speech_rate.EPISODE_MEAN_MIN_WPS)


class EnglishDurationAndSeparatorTests(unittest.TestCase):
    def test_ascii_colon_speaker_split(self) -> None:
        self.assertEqual(dialogue_cut_safety.spoken_text("Harris: Go now.", "en"), "Go now.")
        self.assertEqual(dialogue_cut_safety.spoken_text("Harris: Go now."), "Harris: Go now.")
        self.assertEqual(dialogue_cut_safety.spoken_text("陆哥：走吧", "en"), "走吧")
        prompt_batch_qa = load("prompt_batch_qa", NALU_TOOLS / "prompt_batch_qa.py")
        self.assertEqual(prompt_batch_qa.spoken_part("Harris: Go now."), "Go now.")
        self.assertEqual(prompt_batch_qa.spoken_part("陆哥：走吧"), "走吧")
        uvc = load("unit_voice_consistency", NALU_TOOLS / "unit_voice_consistency.py")
        rows = uvc.expected_lines([{"shot_id": "S1", "spoken_text": "Harris: Go now!"}], {"Harris": "harris"}, "en")
        self.assertEqual(rows[0]["character_id"], "harris")
        self.assertEqual(rows[0]["text"], "gonow")
        bootstrap = load("bootstrap_voice_references", NALU_TOOLS / "bootstrap_voice_references.py")
        dialogue = bootstrap.extract_dialogue(
            {"shots": [{"shot_id": "S1", "prompt_spec": {"dialogue": "Harris: Go now.\nMara：Wait."}}]}, "en")
        self.assertEqual([(row["speaker"], row["text"]) for row in dialogue], [("Harris", "Go now."), ("Mara", "Wait.")])
        self.assertEqual(bootstrap.spoken_length("Don't go back there.", "en"), 4)

    def test_english_duration_estimate_by_words(self) -> None:
        seconds = dialogue_cut_safety.estimated_spoken_seconds(
            "Harris: one two three four five six seven eight nine.", language="en")
        self.assertAlmostEqual(seconds, round(9 / 2.7 + 0.16, 3))
        zh = dialogue_cut_safety.estimated_spoken_seconds("陆哥：走吧。")
        self.assertAlmostEqual(zh, round(2 / 4.2 + 0.16, 3))

    def test_english_unit_dialogue_windows_record_words_per_second(self) -> None:
        unit = {"unit_id": "U1", "duration_seconds": 6, "dialogue_language": "en",
                "ordered_prompt_specs": [{"action": {"t0_seconds": 0, "t1_seconds": 6},
                                          "dialogue": "Harris: Don't go back there."}]}
        rows = dialogue_cut_safety.compile_dialogue_windows(unit)
        self.assertEqual(rows[0]["english_words_per_second"], 2.7)
        self.assertAlmostEqual(rows[0]["end_seconds"] - rows[0]["start_seconds"], round(4 / 2.7 + 0.16, 3), places=2)

    def test_english_long_line_split_at_ascii_punctuation(self) -> None:
        pre = load("build_nalu_preproduction", NALU_TOOLS / "build_nalu_preproduction.py")
        length = lambda text: multimodal_character_binding_guard._dialogue_length(text, "en")  # noqa: E731
        line = ("Harris: I came back for the letters, the photographs and the key, "
                "and I am not leaving this house without every single one of them.")
        dialogue, splits = pre.split_dialogue(line, 20, length, "en")
        heads = dialogue.split("\n")
        self.assertEqual(len(heads), 2)
        self.assertTrue(all(row.startswith("Harris：") for row in heads))
        self.assertEqual(splits[0]["status"], "SPLIT_AT_EXISTING_PUNCTUATION_BOUNDARY")
        self.assertTrue(splits[0]["text_preserved_exactly"])

    def test_binding_guard_counts_english_words(self) -> None:
        guard = multimodal_character_binding_guard
        self.assertEqual(guard._dialogue_length("Don't go back there.", "en"), 4)
        self.assertEqual(guard.dialogue_limit("en"), guard.DIALOGUE_WORD_LIMIT_EN)
        self.assertEqual(guard.dialogue_limit(), guard.DIALOGUE_CHARACTER_LIMIT)

    def test_voice_language_gate_follows_locale(self) -> None:
        asset = {"lock": {"language": "en-US"}}
        self.assertIn("voice_language_not_zh-CN", initial_asset_library.gate_asset("voices", asset))
        self.assertNotIn("voice_language_not_en-US",
                         initial_asset_library.gate_asset("voices", asset, "en-US"))


if __name__ == "__main__":
    unittest.main()
