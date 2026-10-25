"""Dialogue tail trim (CAMERA_GRAMMAR_V1, line owner 2026-10-23): H3 babble after a unit's last line
never reaches the viewer; unstamped episodes assemble exactly as before."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
NALU_TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for _path in (str(REPO), str(REPO / "tools"), str(NALU_TOOLS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import dialogue_tail_trim as trim  # noqa: E402
from tools.build_agentcut_from_admitted_storyboard_sources import build  # noqa: E402


def contract(lines, *, language="en", shots=None, stamped=True, voice_only=()):
    body = {
        "episode": "E99", "dialogue_language": language,
        "character_entities": [{"character_id": "CHAR-A", "identity_source": {"mode": "TEXT_TO_IMAGE"}}]
        + [{"character_id": cid, "identity_source": {"mode": "VOICE_ONLY_NO_PLATE"}} for cid in voice_only],
        "shots": shots or [{"shot_id": sid, "target_seconds": 7.0} for sid, _, _ in lines],
        "audio_contract": {"bgm": "NONE_WHOLE_EPISODE", "native_dialogue_only": True,
                           "dialogue_units": [{"shot_id": sid, "speaker_id": spk, "text": text}
                                              for sid, spk, text in lines]},
    }
    if stamped:
        body["camera_grammar_policy"] = "CAMERA_GRAMMAR_V1"
    return body


def grouping(units):
    return {"units": [{"unit_id": uid, "editorial_shot_ids": shots} for uid, shots in units]}


HOLMES_009 = [{"start": 0.0, "end": 4.32,
               "text": "I have heard of you, Mr. Holmes. I have heard of you from Mrs. Fiorentitian,"},
              {"start": 4.32, "end": 7.28, "text": "all in lust, lust-bassal, billyxedigory, dogfiger."}]


class PlanTests(unittest.TestCase):
    def test_matched_line_end_cuts_babble(self):
        c = contract([("S1", "CHAR-A", "I have heard of you, Mr. Holmes; I have heard of you from Mrs. Farintosh,")])
        report = trim.plan(c, grouping([("U1", ["S1"])]), {"U1": HOLMES_009}, {"U1": 7.292})
        row = report["units"][0]
        self.assertTrue(row["trimmed"])
        self.assertAlmostEqual(row["kept_seconds"], 4.32)  # the babble segment starts at the line end
        self.assertTrue(row["tail_capped_by_next_speech"])
        self.assertEqual(row["reason"], "TRIMMED_AT_LINE_END")
        self.assertIn("Fiorentitian", row["matched_text"])
        asr = trim.trim_unit_asr({"U1": HOLMES_009, "U2": HOLMES_009}, report)
        self.assertEqual([s["text"] for s in asr["U1"]], [HOLMES_009[0]["text"]])
        self.assertEqual(asr["U2"], HOLMES_009)

    def test_unmatched_line_stays_untrimmed(self):
        c = contract([("S1", "CHAR-A", "Whom you helped in the hour of her sore need.")])
        segs = [{"start": 0.0, "end": 2.0, "text": "Totally different words here."}]
        row = trim.plan(c, grouping([("U1", ["S1"])]), {"U1": segs}, {"U1": 7.0})["units"][0]
        self.assertFalse(row["trimmed"])
        self.assertEqual(row["reason"], "LINE_END_NOT_MATCHED")
        self.assertEqual(row["kept_seconds"], 7.0)

    def test_multi_shot_never_cut_inside_non_final_shot(self):
        shots = [{"shot_id": "S1", "target_seconds": 4.0}, {"shot_id": "S2", "target_seconds": 3.0}]
        c = contract([("S2", "CHAR-A", "Go now.")], shots=shots)
        segs = [{"start": 0.2, "end": 1.0, "text": "Go now."}, {"start": 1.0, "end": 6.9, "text": "blah blah"}]
        row = trim.plan(c, grouping([("U1", ["S1", "S2"])]), {"U1": segs}, {"U1": 7.0})["units"][0]
        self.assertTrue(row["trimmed"])
        self.assertAlmostEqual(row["kept_seconds"], 4.0)
        self.assertEqual(row["reason"], "TRIMMED_AT_LAST_SHOT_START")

    def test_dialogue_only_in_earlier_shot_is_not_trimmed(self):
        shots = [{"shot_id": "S1", "target_seconds": 3.0}, {"shot_id": "S2", "target_seconds": 3.0}]
        c = contract([("S1", "CHAR-A", "Go now.")], shots=shots)
        segs = [{"start": 0.2, "end": 1.0, "text": "Go now."}]
        row = trim.plan(c, grouping([("U1", ["S1", "S2"])]), {"U1": segs}, {"U1": 6.0})["units"][0]
        self.assertEqual(row["reason"], "NO_DIALOGUE_IN_LAST_SHOT")

    def test_minimum_length_and_voice_over(self):
        c = contract([("S1", "CHAR-A", "What, then?"), ("S2", "CHAR-V", "Long ago.")], voice_only=("CHAR-V",))
        asr = {"U1": [{"start": 0.0, "end": 0.6, "text": "What then?"}, {"start": 0.6, "end": 3.0, "text": "all our lysings"}],
               "U2": [{"start": 0.0, "end": 1.0, "text": "Long ago."}]}
        report = trim.plan(c, grouping([("U1", ["S1"]), ("U2", ["S2"])]), asr, {"U1": 3.042, "U2": 5.0})
        u1, u2 = report["units"]
        self.assertAlmostEqual(u1["kept_seconds"], trim.MIN_UNIT_SECONDS)
        self.assertEqual(u1["reason"], "TRIMMED_AT_MIN_LENGTH")
        self.assertEqual(u2["reason"], "LAST_SHOT_HAS_VOICE_OVER")
        self.assertFalse(u2["trimmed"])

    def test_chinese_tail_match(self):
        c = contract([("S1", "CHAR-A", "你终于来了，我等你很久。")], language="zh")
        segs = [{"start": 0.0, "end": 2.4, "text": "你终于来了我等你很久"}, {"start": 3.6, "end": 6.0, "text": "阿巴阿巴"}]
        row = trim.plan(c, grouping([("U1", ["S1"])]), {"U1": segs}, {"U1": 6.0})["units"][0]
        self.assertAlmostEqual(row["kept_seconds"], 2.9)
        self.assertFalse(row["tail_capped_by_next_speech"])

    # lab E02 VU-007: ASR split the last word into its own segment; the fuzzy tail match accepted the
    # first segment and the next-speech cap then cut "woman".
    E02_VU007 = [{"start": 0.0, "end": 7.28,
                  "text": "Suddenly, amid all the hubbub of the gale, there burst forth the wild scream of a terrified"},
                 {"start": 7.28, "end": 7.8, "text": "woman."}]
    E02_LINE = "Suddenly, amid all the hubbub of the gale, there burst forth the wild scream of a terrified woman."

    def test_last_word_in_next_segment_is_never_cut(self):
        c = contract([("S1", "CHAR-A", self.E02_LINE)])
        row = trim.plan(c, grouping([("U1", ["S1"])]), {"U1": self.E02_VU007}, {"U1": 8.0})["units"][0]
        self.assertFalse(row["trimmed"])
        self.assertEqual(row["line_end_seconds"], 7.8)
        self.assertTrue(row["line_end_extended_to_last_word"])
        self.assertEqual(row["kept_seconds"], 8.0)
        # a longer slot is still cut — after "woman", never before it
        segs = self.E02_VU007 + [{"start": 8.6, "end": 9.9, "text": "and then blabber"}]
        row = trim.plan(c, grouping([("U1", ["S1"])]), {"U1": segs}, {"U1": 10.0})["units"][0]
        self.assertTrue(row["trimmed"])
        self.assertAlmostEqual(row["kept_seconds"], 8.3)
        asr = trim.trim_unit_asr({"U1": segs}, {"units": [row]})
        self.assertEqual([s["text"] for s in asr["U1"]], ["Suddenly, amid all the hubbub of the gale, there burst "
                                                          "forth the wild scream of a terrified", "woman."])

    def test_last_word_never_heard_stays_untrimmed(self):
        c = contract([("S1", "CHAR-A", self.E02_LINE)])
        row = trim.plan(c, grouping([("U1", ["S1"])]), {"U1": self.E02_VU007[:1]}, {"U1": 8.0})["units"][0]
        self.assertFalse(row["trimmed"])
        self.assertEqual(row["reason"], "LINE_LAST_WORD_NOT_HEARD")

    def test_energy_after_cut_moves_cut_or_skips(self):
        c = contract([("S1", "CHAR-A", "Go now.")])
        segs = [{"start": 0.2, "end": 1.0, "text": "Go now."}]
        hop = trim.ENERGY_HOP
        loud, quiet = -12.0, -80.0

        def frames(loud_until, total=5.0):
            return [loud if i * hop < 1.0 or 1.5 <= i * hop < loud_until else quiet for i in range(int(total / hop))]

        g = grouping([("U1", ["S1"])])
        # quiet after the 1.5 s cut: unchanged
        row = trim.plan(c, g, {"U1": segs}, {"U1": 5.0}, unit_energy={"U1": frames(1.5)})["units"][0]
        self.assertAlmostEqual(row["kept_seconds"], 1.5)
        self.assertTrue(row["energy_checked"])
        # speech-level energy runs on to 2.1 s: the cut moves there
        row = trim.plan(c, g, {"U1": segs}, {"U1": 5.0}, unit_energy={"U1": frames(2.1)})["units"][0]
        self.assertAlmostEqual(row["kept_seconds"], 2.1, places=2)
        self.assertTrue(row["trimmed"])
        # energy runs on past the extension limit: untrimmed
        row = trim.plan(c, g, {"U1": segs}, {"U1": 5.0}, unit_energy={"U1": frames(4.5)})["units"][0]
        self.assertFalse(row["trimmed"])
        self.assertEqual(row["reason"], "SPEECH_ENERGY_AT_CUT")
        # a cut at the onset of the next ASR segment (the babble) is not energy-checked
        c9 = contract([("S1", "CHAR-A", "I have heard of you, Mr. Holmes; I have heard of you from Mrs. Farintosh,")])
        row = trim.plan(c9, g, {"U1": HOLMES_009}, {"U1": 7.292},
                        unit_energy={"U1": [loud] * int(7.292 / hop)})["units"][0]
        self.assertAlmostEqual(row["kept_seconds"], 4.32)
        self.assertNotIn("energy_checked", row)


class BuildTests(unittest.TestCase):
    def _fixture(self, root):
        clips = []
        for name in ("E99-VU-001", "E99-VU-002"):
            path = root / f"{name}.mp4"
            path.write_bytes(name.encode())
            clips.append(path)
        receipt = root / "receipt.json"
        receipt.write_text(json.dumps({"tasks": [
            {"source_id": "E99-VU-001", "status": "qa_pass", "output_path": str(clips[0]), "duration": 7.292},
            {"source_id": "E99-VU-002", "status": "qa_pass", "output_path": str(clips[1]), "duration": 5.0}]}))
        review = root / "review.json"
        review.write_text(json.dumps({"passed_items": [{"path": str(p)} for p in clips]}))
        gc = root / "gc.json"
        gc.write_text(json.dumps(contract([("S1", "CHAR-A", "x")], stamped=False)))
        return receipt, review, gc

    def _build(self, root, tag, **kwargs):
        receipt, review, gc = self._fixture(root)
        project = root / f"project_{tag}.json"
        build("E99", [receipt], review, project, root / f"adm_{tag}.json", root / "out.mp4", 2, gc, **kwargs)
        return project

    def test_trim_shortens_clip_and_restacks_timeline(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "trim.json"
            report.write_text(json.dumps({"units": [
                {"unit_id": "E99-VU-001", "trimmed": True, "kept_seconds": 4.82},
                {"unit_id": "E99-VU-002", "trimmed": False, "kept_seconds": 5.0}]}))
            payload = json.loads(self._build(root, "t", dialogue_tail_trim=report).read_text())
            video = payload["timeline"]["videoTracks"][0]["clips"]
            audio = payload["timeline"]["audioTracks"][0]["clips"]
            self.assertEqual([c["duration"] for c in video], [4.82, 5.0])
            self.assertEqual([c["start"] for c in audio], [0.0, 4.82])
            self.assertEqual(video[0]["metadata"]["dialogue_tail_trim"]["provider_slot_seconds"], 7.292)
            self.assertNotIn("dialogue_tail_trim", video[1]["metadata"])
            self.assertAlmostEqual(payload["metadata"]["runtime_seconds"], 9.82)

    def test_without_trim_project_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plain = self._build(root, "a").read_bytes()
            explicit_none = self._build(root, "b", dialogue_tail_trim=None).read_bytes()
            self.assertEqual(plain.replace(b"adm_a", b"X").replace(b"project_a", b"X"),
                             explicit_none.replace(b"adm_b", b"X").replace(b"project_b", b"X"))
            self.assertNotIn(b"dialogue_tail_trim", plain)


class PipelineTests(unittest.TestCase):
    def test_unstamped_episode_skips_early_asr(self):
        import nalu_pipeline
        ctx = mock.Mock(episode="E99")
        res = nalu_pipeline.StageResult(nalu_pipeline.BLOCKED)
        with mock.patch.object(nalu_pipeline, "transcribe_units") as asr:
            self.assertEqual(nalu_pipeline.s7_dialogue_tail_trim(
                ctx, res, contract([("S1", "CHAR-A", "x")], stamped=False)), (None, None))
            asr.assert_not_called()
        self.assertNotIn("dialogue_tail_trim", res.details)

    def test_stamped_episode_writes_report_and_trims_asr(self):
        import nalu_pipeline
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "video").mkdir()
            (root / "video" / "E99-VU-001.mp4").write_bytes(b"x")
            g = root / "grouping.json"
            g.write_text(json.dumps(grouping([("E99-VU-001", ["S1"])])))
            ctx = mock.Mock(episode="E99")
            ctx.p = mock.Mock(video_media=root / "video", assembly=root / "assembly", grouping_plan=g)
            res = nalu_pipeline.StageResult(nalu_pipeline.BLOCKED)
            c = contract([("S1", "CHAR-A", "I have heard of you, Mr. Holmes; I have heard of you from Mrs. Farintosh,")])
            with mock.patch.object(nalu_pipeline, "transcribe_units", return_value={"E99-VU-001": HOLMES_009}), \
                 mock.patch.object(nalu_pipeline, "_probe_seconds", return_value=7.292):
                asr, report = nalu_pipeline.s7_dialogue_tail_trim(ctx, res, c)
            self.assertEqual(len(asr["E99-VU-001"]), 1)
            self.assertEqual(report, root / "assembly" / "E99_DIALOGUE_TAIL_TRIM.json")
            self.assertTrue((root / "assembly" / "E99_unit_asr_untrimmed.json").is_file())
            self.assertEqual(res.details["dialogue_tail_trim"]["trimmed_units"], 1)


if __name__ == "__main__":
    unittest.main()
