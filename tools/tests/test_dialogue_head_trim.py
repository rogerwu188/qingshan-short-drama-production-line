"""Dialogue head trim (CAMERA_GRAMMAR_V1, line owner 2026-10-26, lab Holmes E05): extra H3 speech before a
unit's scripted line ("Ha!", "That.", "Closh key") is cut with picture and sound together; internal repeats and
unstamped episodes are untouched."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
NALU_TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for _path in (str(REPO), str(REPO / "tools"), str(NALU_TOOLS), str(REPO / "tools" / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import dialogue_head_trim as head  # noqa: E402
import test_dialogue_tail_trim as _tail_tests  # noqa: E402

contract, grouping = _tail_tests.contract, _tail_tests.grouping


def seg(*words):
    return {"start": words[0][0], "end": words[-1][1], "text": "".join(w for _, _, w in words).strip(),
            "words": [{"start": a, "end": b, "word": w} for a, b, w in words]}


# measured on lab Holmes E05 (faster-whisper small, word_timestamps)
VU007 = [seg((0.0, 0.58, " Ha!")),
         seg((1.62, 2.26, " No,"), (2.92, 3.08, " it"), (3.08, 3.22, " is"), (3.22, 3.42, " not"),
             (3.42, 3.64, " even"), (3.64, 4.0, " attached"), (4.0, 4.34, " to"), (4.34, 4.46, " a"),
             (4.46, 4.76, " wire."))]
VU010 = [seg((0.0, 0.28, " It"), (0.28, 0.52, " was,"), (0.68, 1.26, " it"), (1.26, 1.44, " was"),
             (1.44, 2.0, " clamped"), (2.0, 2.18, " to"), (2.18, 2.3, " the"), (2.3, 2.58, " floor."))]
VU016 = [seg((0.0, 0.64, " Closh"), (0.64, 0.96, " key"), (0.96, 1.78, " which"), (1.78, 1.98, " has"),
             (1.98, 2.4, " disturbed"), (2.4, 2.76, " you"))]
VU012 = [seg((0.0, 0.3, " But"), (0.3, 0.6, " what"), (0.6, 0.8, " will"), (0.8, 1.0, " you"), (1.0, 1.4, " do?")),
         seg((2.0, 2.3, " What"), (2.3, 2.6, " will"), (2.6, 2.8, " you"), (2.8, 3.2, " do?"))]


def plan_one(text, segs, seconds=5.0, tail=None, shots=None):
    c = contract([("S1", "CHAR-A", text)], shots=shots)
    g = grouping([("U1", [s["shot_id"] for s in shots] if shots else ["S1"])])
    return head.plan(c, g, {"U1": segs}, {"U1": seconds}, tail)["units"][0]


class PlanTests(unittest.TestCase):
    def test_extra_word_before_line_is_cut(self):
        row = plan_one("Holmes：No, it is not even attached to a wire.", VU007)
        self.assertTrue(row["trimmed"])
        self.assertEqual(row["removed_text"], "Ha!")
        self.assertAlmostEqual(row["head_cut_seconds"], 1.47)  # 0.15 s before "No,"
        self.assertEqual(row["reason"], "TRIMMED_BEFORE_LINE_START")

    def test_cut_never_enters_the_line(self):
        row = plan_one("which has disturbed you.", VU016)
        self.assertEqual(row["removed_text"], "Closh key")
        self.assertAlmostEqual(row["head_cut_seconds"], 0.96)  # "key" ends where "which" starts

    def test_internal_repeats_are_not_trimmed(self):
        self.assertEqual(plan_one("It was clamped to the floor.", VU010)["reason"], "LEADING_WORDS_REPEAT_LINE_START")
        self.assertEqual(plan_one("But what will you do?", VU012)["reason"], "NO_EXTRA_SPEECH_BEFORE_LINE")

    def test_unmatched_line_short_unit_and_no_words_stay_untrimmed(self):
        self.assertEqual(plan_one("Something else entirely here.", VU007)["reason"], "LINE_START_NOT_MATCHED")
        self.assertEqual(plan_one("No, it is not even attached to a wire.", VU007, seconds=5.0,
                                  tail={"units": [{"unit_id": "U1", "trimmed": True, "kept_seconds": 2.5}]})["reason"],
                         "MIN_UNIT_LENGTH")
        no_words = [{k: v for k, v in s.items() if k != "words"} for s in VU007]
        self.assertEqual(plan_one("No, it is not even attached to a wire.", no_words)["reason"], "NO_ASR_WORDS")

    def test_shift_unit_asr_rebases_and_drops_extra_words(self):
        report = {"units": [{"unit_id": "U1", "trimmed": True, "head_cut_seconds": 0.96}]}
        shifted = head.strip_words(head.shift_unit_asr({"U1": VU016, "U2": VU016}, report))
        self.assertEqual(shifted["U1"], [{"start": 0.0, "end": 1.8, "text": "which has disturbed you"}])
        self.assertEqual(shifted["U2"][0]["text"], "Closh key which has disturbed you")


class BuildTests(unittest.TestCase):
    _fixture = _tail_tests.BuildTests._fixture
    _build = _tail_tests.BuildTests._build

    def test_head_trim_moves_in_point_of_picture_and_sound(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "head.json"
            report.write_text(json.dumps({"units": [
                {"unit_id": "E99-VU-001", "trimmed": True, "head_cut_seconds": 1.47},
                {"unit_id": "E99-VU-002", "trimmed": False, "head_cut_seconds": 0.0}]}))
            tail = root / "tail.json"
            tail.write_text(json.dumps({"units": [{"unit_id": "E99-VU-001", "trimmed": True, "kept_seconds": 5.3}]}))
            payload = json.loads(self._build(root, "h", dialogue_tail_trim=tail, dialogue_head_trim=report).read_text())
            video = payload["timeline"]["videoTracks"][0]["clips"]
            audio = payload["timeline"]["audioTracks"][0]["clips"]
            self.assertEqual([c["in"] for c in video], [1.47, 0.0])
            self.assertEqual([c["in"] for c in audio], [1.47, 0.0])
            self.assertEqual([round(c["duration"], 6) for c in video], [3.83, 5.0])
            self.assertEqual([round(c["start"], 6) for c in audio], [0.0, 3.83])
            self.assertEqual(video[0]["metadata"]["dialogue_head_trim"]["head_cut_seconds"], 1.47)

    def test_without_head_trim_project_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            plain = self._build(root, "a").read_bytes()
            none = self._build(root, "b", dialogue_head_trim=None).read_bytes()
            self.assertEqual(plain.replace(b"adm_a", b"X").replace(b"project_a", b"X"),
                             none.replace(b"adm_b", b"X").replace(b"project_b", b"X"))


class PipelineTests(unittest.TestCase):
    def test_stamped_s7_plans_head_trim_from_the_same_word_asr(self):
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
            c = contract([("S1", "CHAR-A", "No, it is not even attached to a wire.")])
            with mock.patch.object(nalu_pipeline, "transcribe_units", return_value={"E99-VU-001": VU007}) as asr, \
                    mock.patch.object(nalu_pipeline, "_probe_seconds", return_value=5.0):
                trimmed, _tail = nalu_pipeline.s7_dialogue_tail_trim(ctx, res, c)
            self.assertTrue(asr.call_args.kwargs.get("words"))
            report = root / "assembly" / "E99_DIALOGUE_HEAD_TRIM.json"
            self.assertEqual(res.details["dialogue_head_trim"]["apply"], str(report))
            self.assertEqual(json.loads(report.read_text())["trimmed_units"], 1)
            self.assertEqual([s["text"] for s in trimmed["E99-VU-001"]], ["No, it is not even attached to a wire."])
            self.assertNotIn("words", trimmed["E99-VU-001"][0])
            self.assertAlmostEqual(trimmed["E99-VU-001"][0]["start"], 0.15)


if __name__ == "__main__":
    unittest.main()
