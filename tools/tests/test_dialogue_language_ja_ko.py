#!/usr/bin/env python3
"""Japanese / Korean dialogue (dialogue_language "ja" / "ko", 2026-11-18): the shared lang_profile, counting,
ASR normalisation, H3 tags and leak checks, subtitles, title / end card text, intake encodings, DR1 thresholds
and language resolution.  zh / en keep their historical values (asserted beside each ja / ko case)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import types
import unittest.mock
import unittest
from pathlib import Path

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


lang = load("lang_profile", NALU_TOOLS / "lang_profile.py")
gate = load("source_video_dialogue_gate", ROOT / "tools/source_video_dialogue_gate.py")
burnin = load("build_burnin_subtitles", NALU_TOOLS / "build_burnin_subtitles.py")
speech_rate = load("speech_rate_check", NALU_TOOLS / "speech_rate_check.py")
prompt_rules = load("nalu_prompt_rules", NALU_TOOLS / "nalu_prompt_rules.py")
title = load("nalu_opening_title", NALU_TOOLS / "nalu_opening_title.py")
media = load("nalu_media_tools", NALU_TOOLS / "nalu_media_tools.py")

from tools import dialogue_cut_safety, dialogue_head_trim, dialogue_register_gate, dialogue_tail_trim  # noqa: E402
from tools import final_cut_audience_detectors, h3_provider_english_contract, h3_provider_prompt_renderer  # noqa: E402
from tools import intake_source_text, multimodal_character_binding_guard, performance_cut  # noqa: E402
from tools import portable_runtime, visual_culture_contract, voice_over_narration, voice_reference_sample  # noqa: E402
from tools import lang_profile as tools_lang  # noqa: E402

JA = "ずっと、あなたを待ってた。"
KO = "이제야 왔구나. 기다렸어."


class ProfileTests(unittest.TestCase):
    def test_four_languages_with_their_values(self) -> None:
        self.assertEqual(lang.LANGUAGES, ("zh", "en", "ja", "ko"))
        ja, ko = lang.profile("ja"), lang.profile("ko-KR")
        self.assertEqual((ja.locale, ja.whisper, ja.h3_tag, ja.unit, ja.joiner), ("ja-JP", "ja", "Japanese", "char", ""))
        self.assertEqual((ko.locale, ko.whisper, ko.h3_tag, ko.unit, ko.joiner), ("ko-KR", "ko", "Korean", "char", " "))
        self.assertEqual((ja.rate, ko.rate), (6.0, 5.0))
        self.assertEqual((ja.endcard, ko.endcard), ("つづく", "다음 화에 계속"))
        self.assertEqual(ja.whisper_model, "small")
        self.assertEqual(ko.whisper_model, "small")
        self.assertIn("ja-JP Japanese", ja.voice_locale_text)
        self.assertIn("ko-KR Korean", ko.voice_locale_text)
        self.assertEqual(lang.profile("zh").voice_locale_text, "zh-CN Mandarin, no accent processing, no pitch shifting")
        self.assertEqual(lang.profile("en").endcard, "TO BE CONTINUED")
        self.assertEqual(lang.profile("fr").code, "zh")  # unknown -> the historical line

    def test_episode_labels(self) -> None:
        self.assertEqual(lang.episode_label(3, "ja"), "第3話")
        self.assertEqual(lang.episode_label(3, "ko"), "제3화")
        self.assertEqual(lang.episode_label(12, "zh"), "第十二集")
        self.assertEqual(lang.episode_label(1, "en"), "EPISODE 01")

    def test_counting_is_non_zero_for_ja_and_ko(self) -> None:
        self.assertEqual(lang.speech_units(JA, "ja"), 11)   # kana + kanji, punctuation excluded
        self.assertEqual(lang.speech_units("カタカナー", "ja"), 5)
        self.assertEqual(lang.speech_units(KO, "ko"), 10)   # Hangul syllables, spaces excluded
        self.assertEqual(lang.speech_units("Don't go back there.", "en"), 4)

    def test_asr_normalisation_keeps_kana_and_hangul(self) -> None:
        self.assertEqual(lang.normalise("ズット、あなたを待ってた！", "ja"), "ずっとあなたを待ってた")
        self.assertEqual(lang.normalise("이제야 왔구나. 기다렸어.", "ko"), "이제야왔구나기다렸어")
        self.assertEqual(lang.normalise("你好，世界", "zh"), "你好世界")

    def test_speaker_split_accepts_both_colons(self) -> None:
        self.assertEqual(lang.split_speaker("Sato：" + JA, "ja")[2], JA)
        self.assertEqual(lang.split_speaker("Kim: " + KO, "ko")[2].strip(), KO)

    def test_tools_shim_reexports_the_same_profile(self) -> None:
        self.assertEqual(tools_lang.profile("ja").h3_tag, "Japanese")
        self.assertEqual(tools_lang.speech_units(KO, "ko"), 10)

    def test_tables_that_mirror_the_profile_agree(self) -> None:
        tags = {code: lang.PROFILES[code].h3_tag for code in lang.LANGUAGES}
        self.assertEqual(h3_provider_prompt_renderer.DIALOGUE_LANGUAGE_TAGS, tags)
        self.assertEqual(portable_runtime.LANGUAGE_WHISPER_MODELS,
                         {c: p.whisper_model for c, p in lang.PROFILES.items() if p.whisper_model != "small"})
        make_endcard = load("make_endcard", ROOT / "skills/nalu-claude-code/scripts/make_endcard.py") \
            if importlib.util.find_spec("PIL") else None
        if make_endcard:
            self.assertEqual(make_endcard.TAGLINE, {c: p.endcard for c, p in lang.PROFILES.items()})


class LanguageResolutionTests(unittest.TestCase):
    def test_ja_and_ko_are_no_longer_coerced_to_zh(self) -> None:
        src = (NALU_TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")
        ns: dict = {}
        exec(src[src.index("DIALOGUE_LANGUAGES"):].split("\n", 1)[0], ns)
        exec(src[src.index("DIALOGUE_LANGUAGE_LOCALES"):].split("\n", 1)[0], ns)
        for name in ("_dialogue_language_code", "resolve_dialogue_language"):
            i = src.index(f"def {name}(")
            exec("from typing import Any\n" + src[i:src.index("\n\n\n", i)], ns)
        resolve = ns["resolve_dialogue_language"]
        self.assertEqual(resolve({"dialogue_language": "ja"}, None), "ja")
        self.assertEqual(resolve({}, {"project": {"language": "ko-KR"}}), "ko")
        self.assertEqual(resolve({"dialogue_language": "ja-JP"}, {"project": {"language": "en-US"}}), "ja")
        self.assertEqual(resolve(None, None), "zh")
        self.assertEqual(ns["DIALOGUE_LANGUAGES"], lang.LANGUAGES)
        self.assertEqual(ns["DIALOGUE_LANGUAGE_LOCALES"], {c: p.locale for c, p in lang.PROFILES.items()})

    def test_voice_over_contract_language(self) -> None:
        self.assertEqual(voice_over_narration.contract_language({"dialogue_language": "ja-JP"}), "ja")
        self.assertEqual(voice_over_narration.contract_language({"dialogue_language": "ko"}), "ko")
        self.assertEqual(voice_over_narration.contract_language({"dialogue_language": "en"}), "en")
        self.assertEqual(voice_over_narration.contract_language({}), "zh")
        self.assertEqual(voice_over_narration.partition_line("Kim: 가자", "ko")[0], "Kim")

    def test_fixups_write_the_locale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "runtime").mkdir()
            subprocess.run([sys.executable, str(ROOT / "skills/nalu-claude-code/scripts/apply_runtime_fixups.py"),
                            "--runtime-root", tmp, "--language", "ko"], check=True, capture_output=True)
            cfg = json.loads((Path(tmp) / "qingshan.json").read_text(encoding="utf-8"))
        self.assertEqual(cfg["project"]["language"], "ko-KR")


class AsrComparisonTests(unittest.TestCase):
    def test_korean_expected_text_is_no_longer_empty(self) -> None:
        self.assertEqual(gate.spoken(KO, "ko"), "이제야왔구나기다렸어")
        self.assertEqual(gate.recall(KO, "이제야 왔구나 기다렸어", "ko"), 1.0)
        self.assertLess(gate.recall(KO, "전혀 다른 말", "ko"), 0.3)

    def test_japanese_recall_folds_katakana(self) -> None:
        self.assertEqual(gate.recall(JA, "ズットアナタヲ待ってた", "ja"), 1.0)

    def test_gate_reports_language_neutral_codes(self) -> None:
        rows = [{"dia_id": "D1", "spoken_text": KO}]
        probe = {"streams": [{"codec_type": "video"}, {"codec_type": "audio"}], "format": {"duration": "5"}}
        missing = gate.evaluate(Path("x.mp4"), rows, probe_payload=probe, transcript="", segments=[],
                                minimum_recall=0.55, language="ko")
        self.assertIn("native_speech_missing", missing["failures"])
        ok = gate.evaluate(Path("x.mp4"), rows, probe_payload=probe, transcript="이제야 왔구나. 기다렸어.",
                           segments=[{"start": 0.2, "end": 2.0}], minimum_recall=0.55, language="ko")
        self.assertEqual(ok["status"], "PASS", ok["failures"])
        zh = gate.evaluate(Path("x.mp4"), [{"dia_id": "D1", "spoken_text": "走吧"}], probe_payload=probe,
                           transcript="", segments=[], minimum_recall=0.55)
        self.assertIn("native_mandarin_speech_missing", zh["failures"])

    def test_whisper_model_prefers_medium_for_japanese_only_when_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"HF_HOME": tmp}
            roots = (Path(tmp) / "hub",)  # only this temporary cache, never the host's real one
            with unittest.mock.patch.dict("os.environ", env, clear=False), \
                    unittest.mock.patch.object(portable_runtime, "_whisper_cache_roots", return_value=roots):
                import os
                os.environ.pop(portable_runtime.WHISPER_ENV, None)
                self.assertEqual(portable_runtime.language_whisper_model_name("ja"), "small")
                snap = Path(tmp) / "hub/models--Systran--faster-whisper-medium/snapshots/abc"
                snap.mkdir(parents=True)
                self.assertEqual(portable_runtime.language_whisper_model_name("ja"), "small")  # still downloading
                (snap / "model.bin").write_bytes(b"x")
                # small is the default even with medium installed (…1485: medium stalled S6 post-gen QA)
                self.assertEqual(portable_runtime.language_whisper_model_name("ja"), "small")
                os.environ[portable_runtime.WHISPER_JA_ENV] = "medium"  # opt-in on a host that can afford it
                try:
                    self.assertEqual(Path(portable_runtime.language_whisper_model_name("ja")).name, "abc")
                finally:
                    os.environ.pop(portable_runtime.WHISPER_JA_ENV, None)
                self.assertEqual(portable_runtime.language_whisper_model_name("zh"), "small")
                self.assertEqual(portable_runtime.language_whisper_model_name("ko"), "small")

    def test_cjk_alignment_tokens(self) -> None:
        self.assertEqual(dialogue_head_trim._line_tokens("Kim：가자"), ["가", "자"])
        self.assertEqual(dialogue_head_trim._line_tokens("走吧"), ["走", "吧"])
        self.assertEqual(dialogue_tail_trim._cjk("待ってタ"), "待ってた")
        self.assertTrue(performance_cut._is_cjk("가") and performance_cut._is_cjk("か") and performance_cut._is_cjk("走"))
        self.assertEqual(performance_cut.script_tokens(["Sato：カギ"], True), ["か", "ぎ"])

    def test_subtitle_readback_skips_t2s_for_japanese(self) -> None:
        norm = final_cut_audience_detectors.normalise_subtitle_text
        self.assertEqual(norm("「話」をする。", "ja"), "話をする")
        self.assertEqual(norm("말해 줘.", "ko"), "말해줘")
        self.assertEqual(final_cut_audience_detectors.cue_similarity("말해줘", "말해줘", "ko"), 1.0)


class TimingTests(unittest.TestCase):
    def test_min_dialogue_seconds(self) -> None:
        # 11 chars / 6.0 + lead + tail, rounded up to 0.5
        self.assertGreater(prompt_rules.min_dialogue_seconds(JA, None, "ja"), 2.0)
        self.assertGreater(prompt_rules.min_dialogue_seconds(KO, None, "ko"), 2.0)
        self.assertEqual(prompt_rules.min_dialogue_seconds("走吧", None), prompt_rules.min_dialogue_seconds("走吧", None, "zh"))

    def test_cut_safety_estimate(self) -> None:
        ja = dialogue_cut_safety.estimated_spoken_seconds("Sato：" + JA, language="ja")
        self.assertAlmostEqual(ja, round(11 / 6.0 + 2 * 0.16, 3))
        ko = dialogue_cut_safety.estimated_spoken_seconds("Kim: " + KO, language="ko")
        self.assertAlmostEqual(ko, round(10 / 5.0 + 2 * 0.16, 3))

    def test_speech_rate_units(self) -> None:
        self.assertEqual(speech_rate.spoken_count(KO, "ko"), 10)
        contract = {"shots": [{"shot_id": "S1", "prompt_spec": {"dialogue": "Sato：" + JA}}]}
        self.assertEqual(speech_rate.shot_targets(contract, "ja")["S1"]["cps"], 7.0)
        summary = speech_rate.episode_summary([{"spoken_chars": 60, "speech_seconds": 10, "measured_cps": 6.0}], "ja")
        self.assertEqual(summary["rate_unit"], "characters_per_second")
        self.assertTrue(summary["below_episode_min"])

    def test_binding_guard_limits(self) -> None:
        guard = multimodal_character_binding_guard
        self.assertEqual(guard._dialogue_length(KO, "ko"), 10)
        self.assertEqual(guard.dialogue_limit("ja"), 42)
        self.assertEqual(guard.dialogue_limit("ko"), 36)
        self.assertEqual(guard.dialogue_limit(), 30)

    def test_voice_reference_sample(self) -> None:
        self.assertEqual(voice_reference_sample.CALIBRATION_SENTENCES["ja"], lang.PROFILES["ja"].calibration)
        self.assertEqual(voice_reference_sample._norm("カナ 한글"), "カナ한글")
        out = voice_reference_sample.calibration_sample({"speed": 1.0}, [], "ko")
        self.assertEqual(out["sample_text"], lang.PROFILES["ko"].calibration[0])
        self.assertTrue(3 <= out["estimated_duration_seconds"] <= 10)


class H3Tests(unittest.TestCase):
    def test_japanese_and_korean_tags_pass_the_boundary(self) -> None:
        for text in (f"Subject 1 says <d>[Japanese] {JA}</d>.", f"Subject 1 says <d>[Korean] {KO}</d>."):
            report = h3_provider_english_contract.validate_h3_provider_text_boundary(text, source_id="U1")
            self.assertEqual(report["status"], "PASS", report["failures"])

    def test_kana_and_hangul_outside_tags_are_leaks(self) -> None:
        for leak in ("さとう", "김민준"):
            report = h3_provider_english_contract.validate_h3_provider_text_boundary(
                f"{leak} says <d>[Korean] {KO}</d>", source_id="U1")
            self.assertIn("H3_CJK_OUTSIDE_DIALOGUE:U1", report["failures"])

    def test_beat_emits_language_tags(self) -> None:
        translated = {"entry_state": "standing", "primary_action": "turns.", "exit_state": "still"}
        binding = {"provider_entity_label": "Subject 1", "subject_token": "S1", "image_slot": "@Image1",
                   "speaker_slot": "S1", "audio_slot": "@Audio1", "visible_speaker": True}
        for language, raw, tag in (("ja", "Sato：" + JA, f"<d>[Japanese] {JA}</d>"),
                                   ("ko", "Kim: " + KO, f"<d>[Korean] {KO}</d>")):
            line, evidence = h3_provider_prompt_renderer._beat(
                {"source_index": 1, "start_seconds": 0, "end_seconds": 3, "dialogue": raw}, translated,
                dialogue_binding=binding, language=language)
            self.assertIn(tag, line)

    def test_continuation_fragments_join_per_language(self) -> None:
        part = h3_provider_prompt_renderer._dialogue_partition
        self.assertEqual(part("Kim: 이제야\nKim: 왔구나", "ko")[2], "이제야 왔구나")
        self.assertEqual(part("Sato：ずっと\nSato：待ってた", "ja")[2], "ずっと待ってた")

    def test_visual_lock_is_the_authored_world(self) -> None:
        self.assertTrue(visual_culture_contract.is_authored_world(None, dialogue_language="ja", episode_number=60))
        self.assertTrue(visual_culture_contract.is_authored_world(None, dialogue_language="ko-KR", episode_number=1))
        self.assertFalse(visual_culture_contract.is_authored_world(None, dialogue_language="zh", episode_number=1))
        self.assertFalse(visual_culture_contract.is_authored_world({"era_lock": "EAST_ASIAN_PERIOD"},
                                                                   dialogue_language="ja"))


class TitleAndSubtitleTests(unittest.TestCase):
    def test_title_lines(self) -> None:
        brief = {"title": "待ち人", "episode_title": "再会"}
        self.assertEqual(title.title_lines(brief, "E01", "ja"), ("待ち人", "第1話 · 再会"))
        self.assertEqual(title.title_lines({"title": "기다림"}, "E02", "ko"), ("기다림", "제2화"))
        self.assertEqual(title.title_lines({"title": "等待"}, "E02", "zh")[1], "第二集")

    def test_language_font_never_needs_a_chinese_only_face(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            face = Path(tmp) / "noto.ttc"
            face.write_bytes(b"x")
            font, source = media.resolve_language_font("ko", environ={}, candidates=(face,))
            self.assertEqual((font, source), (str(face.resolve()), "COMMON_EXISTING_PATH:ko"))
            explicit, src = media.resolve_language_font("ja", environ={"QINGSHAN_JA_FONT": str(face)})
            self.assertEqual(src, "QINGSHAN_JA_FONT")
            fallback, src = media.resolve_language_font("ja", environ={"QINGSHAN_CJK_FONT": str(face)}, candidates=())
            self.assertEqual(src, "CJK_FALLBACK:QINGSHAN_CJK_FONT")

    def test_subtitle_speech_and_wrap(self) -> None:
        self.assertEqual(burnin.speech("이제야 왔구나", "ko"), "이제야왔구나")
        self.assertEqual(burnin.weight(JA, "ja"), 11)
        self.assertNotIn("\\N", burnin.wrap_ko("이제야 왔구나"))
        wrapped = burnin.wrap_ko("이제야 왔구나 기다렸어 정말 오래 기다렸어")
        self.assertEqual(len(wrapped.split("\\N")), 2)
        self.assertTrue(all(" " not in part[:1] for part in wrapped.split("\\N")))


class IntakeTests(unittest.TestCase):
    JA_TEXT = "第1話 出会い\n彼はずっと待っていた。雨の中で、ひとりで。\n第2話 別れ\nそして彼女は来なかった。\n" * 3
    KO_TEXT = "제1장 만남\n그는 오랫동안 기다렸다. 비가 내리는 거리에서 혼자.\n제2장 이별\n그리고 그녀는 오지 않았다.\n" * 3

    def test_legacy_japanese_and_korean_encodings_are_detected(self) -> None:
        for enc in ("shift_jis", "euc_jp"):
            text, got = intake_source_text.decode(self.JA_TEXT.encode(enc))
            self.assertEqual(text, self.JA_TEXT, enc)
            self.assertIn(got, ("cp932", "euc_jp"))
        text, got = intake_source_text.decode(self.KO_TEXT.encode("cp949"))
        self.assertEqual((text, got), (self.KO_TEXT, "cp949"))
        zh = "第一章 开始\n他在雨里等了很久，一个人，没有说话。\n" * 5
        self.assertEqual(intake_source_text.decode(zh.encode("gbk")), (zh, "gb18030"))

    def test_language_heading_defaults(self) -> None:
        self.assertEqual(intake_source_text.detect_language(self.JA_TEXT), "ja")
        self.assertEqual(intake_source_text.detect_language(self.KO_TEXT), "ko")
        import re
        ja = re.compile(intake_source_text.DEFAULT_HEADING_BY_LANGUAGE["ja"], re.M)
        ko = re.compile(intake_source_text.DEFAULT_HEADING_BY_LANGUAGE["ko"], re.M)
        self.assertEqual(sorted(intake_source_text.split_chapters(self.JA_TEXT, ja, None)), [1, 2])
        self.assertEqual(sorted(intake_source_text.split_chapters(self.KO_TEXT, ko, None)), [1, 2])
        self.assertTrue(ko.match("3화"))
        self.assertFalse(ko.match("3화가 났다고 했다"))

    def test_cli_never_simplifies_japanese(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "novel.txt"
            src.write_bytes(self.JA_TEXT.encode("shift_jis"))
            done = subprocess.run([sys.executable, str(ROOT / "tools/intake_source_text.py"), "--input", str(src),
                                   "--work", "w", "--out", tmp, "--to-simplified"], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            index = json.loads((Path(tmp) / "w/SOURCE_INDEX.json").read_text(encoding="utf-8"))
        self.assertEqual((index["source_language"], index["simplified_copy"], index["chapters_found"]), ("ja", False, 2))


class KnowledgeAndRegisterTests(unittest.TestCase):
    def test_dr1_thresholds(self) -> None:
        policy = json.loads((ROOT / "configs/DIALOGUE_REGISTER_V1.json").read_text(encoding="utf-8"))
        self.assertEqual(dialogue_register_gate.verbatim_min_run_for("ja", policy), 12)
        self.assertEqual(dialogue_register_gate.verbatim_min_run_for("ko-KR", policy), 10)
        self.assertEqual(dialogue_register_gate.verbatim_min_run_for("zh", policy), 8)
        self.assertEqual(dialogue_register_gate.verbatim_min_run_for(None, policy), 8)

    def test_authoring_clause_prefers_english_for_ja_ko(self) -> None:
        from tools.collective_learning import authoring
        rule = {"application": {"prompt_clause": {"zh": "中文", "en": "English"}}}
        self.assertEqual(authoring._clause_text(rule, "ja"), "English")
        self.assertEqual(authoring._clause_text(rule, "ko"), "English")
        self.assertEqual(authoring._clause_text(rule, "zh"), "中文")
        self.assertEqual(authoring._clause_text({"application": {"prompt_clause": {"zh": "中文", "ko": "한국어"}}}, "ko"),
                         "한국어")


if __name__ == "__main__":
    unittest.main()
