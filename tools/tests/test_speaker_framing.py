"""CAMERA_GRAMMAR_V1 objective Q2 speaker framing (video_q2_builder): synthetic face boxes only."""
from __future__ import annotations

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

import video_q2_builder as q2  # noqa: E402

W = 768.0


def solo(fv="FRONT_VISIBLE", line="Helen：My name is Helen Stoner."):
    return {"cast": [{"shot_id": "S1", "character": "Helen", "character_id": "CHAR-HELEN",
                      "screen_slot": "SLOT_1", "face_visibility": fv}],
            "expected_dialogue": [{"shot_id": "S1", "spoken_text": line}] if line else []}


def two_shot():
    return {"cast": [{"shot_id": "S1", "character": "Helen", "character_id": "CHAR-HELEN",
                      "screen_slot": "SLOT_1", "face_visibility": "FRONT_VISIBLE"},
                     {"shot_id": "S1", "character": "Holmes", "character_id": "CHAR-HOLMES",
                      "screen_slot": "SLOT_2", "face_visibility": "FRONT_VISIBLE"}],
            "expected_dialogue": [{"shot_id": "S1", "spoken_text": "Helen：It was the band!"}]}


def face(x1, x2, sims=None):
    row = {"bbox": [x1, 400.0, x2, 540.0]}
    if sims is not None:
        row["similarity"] = sims
    return row


def frames(face_lists):
    return [{"frame_index": i + 1, "at_seconds": float(i), "width": W, "faces": faces}
            for i, faces in enumerate(face_lists)]


CENTRED = [face(300.0, 420.0)]
CUT_LEFT = [face(-60.0, 100.0)]          # 37% of the box outside the frame
TOUCH_LEFT = [face(8.0, 180.0)]          # x1 within 2% of the edge, small face, centre 0.122
BAND_RIGHT = [face(640.0, 740.0)]        # centre 0.90 (outer 12%), not touching


class SpeakerDeclarationTests(unittest.TestCase):
    def test_only_face_visible_cast_speakers(self):
        self.assertEqual(q2.declared_speakers(solo())["speaker_ids"], ["CHAR-HELEN"])
        self.assertEqual(q2.declared_speakers(solo("OFFSCREEN_VOICE_ONLY"))["speaker_ids"], [])
        self.assertEqual(q2.declared_speakers(solo("BACK_TO_CAMERA"))["speaker_ids"], [])
        self.assertEqual(q2.declared_speakers(solo(line=None))["speaker_ids"], [])
        self.assertEqual(q2.declared_speakers(solo(line="Narrator：Long ago."))["speaker_ids"], [])
        sides = q2.declared_speakers(two_shot())["speaker_sides"]
        self.assertEqual(sides, {"CHAR-HELEN": "LEFT"})

    def test_not_applicable_without_on_screen_speaker(self):
        v = q2.speaker_framing_verdict(solo(line=None), frames([CUT_LEFT] * 9))
        self.assertEqual(v["status"], "NOT_APPLICABLE")


class SpeakerVerdictTests(unittest.TestCase):
    def test_three_of_nine_flagged_fails(self):
        v = q2.speaker_framing_verdict(solo(), frames([CENTRED] * 7 + [CUT_LEFT, []]))
        self.assertEqual(v["status"], "PASS")
        self.assertEqual(v["frames_flagged"], 2)
        v = q2.speaker_framing_verdict(solo(), frames([CENTRED] * 6 + [CUT_LEFT, [], TOUCH_LEFT]))
        self.assertEqual(v["status"], "FAIL")
        self.assertEqual(v["failure"], "OBJECTIVE_SPEAKER_FRAMING_CRAMPED_OR_CUT:"
                                       "f7=FACE_CUT_AT_EDGE,f8=NO_FACE_DETECTED,f9=FACE_TOUCHES_EDGE")

    def test_flags(self):
        v = q2.speaker_framing_verdict(solo(), frames([CUT_LEFT, TOUCH_LEFT, BAND_RIGHT, []]))
        self.assertEqual([r["flag"] for r in v["per_frame"]],
                         ["FACE_CUT_AT_EDGE", "FACE_TOUCHES_EDGE", "FACE_CENTRE_IN_OUTER_BAND",
                          "NO_FACE_DETECTED"])

    def test_close_up_may_touch_the_edge(self):
        close_up = [face(-10.0, 300.0)]  # 40% of the width, 3% outside, centre 0.19
        v = q2.speaker_framing_verdict(solo(), frames([close_up] * 9))
        self.assertEqual(v["status"], "PASS")

    def test_two_shot_identity_picks_speaker_not_listener(self):
        helen = {"CHAR-HELEN": 0.6, "CHAR-HOLMES": 0.2}
        holmes = {"CHAR-HELEN": 0.2, "CHAR-HOLMES": 0.6}
        # listener centred, speaker cut at the left edge -> speaker is judged
        cut = [face(300.0, 420.0, holmes), face(-60.0, 100.0, helen)]
        v = q2.speaker_framing_verdict(two_shot(), frames([cut] * 3))
        self.assertEqual({r["flag"] for r in v["per_frame"]}, {"FACE_CUT_AT_EDGE"})
        self.assertEqual(v["status"], "FAIL")
        # speaker centred, listener cut -> pass
        ok = [face(300.0, 420.0, helen), face(-60.0, 100.0, holmes)]
        self.assertEqual(q2.speaker_framing_verdict(two_shot(), frames([ok] * 9))["status"], "PASS")
        # only the listener in frame -> the speaker is out of frame
        gone = [face(300.0, 420.0, holmes)]
        v = q2.speaker_framing_verdict(two_shot(), frames([gone] * 3))
        self.assertEqual(v["per_frame"][0]["flag"], "SPEAKER_NOT_IN_FRAME")

    def test_two_shot_without_identity_uses_declared_side_or_skips(self):
        both = [face(300.0, 420.0), face(-60.0, 100.0)]  # Helen declared LEFT -> left face
        v = q2.speaker_framing_verdict(two_shot(), frames([both] * 3))
        self.assertEqual(v["per_frame"][0]["flag"], "FACE_CUT_AT_EDGE")
        one = [face(640.0, 740.0)]  # one face of two declared, no identity -> ambiguous, not flagged
        v = q2.speaker_framing_verdict(two_shot(), frames([one] * 9))
        self.assertEqual(v["status"], "PASS")
        self.assertEqual(v["per_frame"][0]["basis"], "AMBIGUOUS_NO_FLAG")

    def test_undeclared_extra_is_not_the_speaker(self):
        extra = [face(640.0, 740.0, {"CHAR-HELEN": 0.1})]
        v = q2.speaker_framing_verdict(solo(), frames([extra] * 3))
        self.assertEqual(v["per_frame"][0]["flag"], "SPEAKER_NOT_IN_FRAME")


class SpeakerApplyTests(unittest.TestCase):
    def test_objective_fail_overrides_reviewer_pass(self):
        checks = [{"question_id": "cast_exactly_as_declared", "answer": "PASS", "reviewer_answer": "PASS"}]
        failures: list = []
        fail = {"status": "FAIL", "failure": "OBJECTIVE_SPEAKER_FRAMING_CRAMPED_OR_CUT:f1=NO_FACE_DETECTED",
                "speaker_ids": ["CHAR-HELEN"], "frames_flagged": 3}
        self.assertTrue(q2.apply_speaker_framing(fail, checks, failures))
        self.assertEqual(checks[0]["answer"], "FAIL")
        self.assertEqual(checks[0]["reviewer_answer"], "PASS")
        self.assertEqual(checks[-1]["question_id"], "objective_speaker_framing")
        self.assertEqual(failures[0], "cast_exactly_as_declared")
        self.assertFalse(q2.apply_speaker_framing({"status": "PASS"}, [], []))
        self.assertFalse(q2.apply_speaker_framing({"status": "NOT_APPLICABLE"}, [], []))
        self.assertFalse(q2.apply_speaker_framing(None, [], []))


class SpeakerMeasureTests(unittest.TestCase):
    def test_measure_on_synthetic_detections(self):
        import numpy as np
        from PIL import Image

        class Face:
            def __init__(self, x1, x2):
                self.bbox = np.array([x1, 400.0, x2, 560.0])
                self.det_score = 0.9
                self.normed_embedding = np.array([1.0, 0.0])

        per_frame = iter([[Face(300, 420)], [Face(-60, 100)], [], [Face(8, 180)]])
        backend = mock.Mock()
        backend._app.get.side_effect = lambda image: next(per_frame)
        with tempfile.TemporaryDirectory() as td:
            rows = []
            for i in range(4):
                path = Path(td) / f"f{i}.png"
                Image.new("RGB", (768, 1344)).save(path)
                rows.append({"path": str(path), "at_seconds": i * 1.0})
            with mock.patch.object(q2, "_insightface_backend", return_value=backend), \
                    mock.patch.object(q2, "engine_module"), \
                    mock.patch.object(q2, "_speaker_canonicals", return_value={}):
                detections = q2.detect_unit_faces(rows)
                v = q2.measure_speaker_framing("E99", solo(), rows, detections)
                count = q2.measure_face_count(solo(), rows, detections)
        self.assertEqual(v["speaker_identity"], "GEOMETRY_ONLY")
        self.assertEqual([r["flag"] for r in v["per_frame"]],
                         [None, "FACE_CUT_AT_EDGE", "NO_FACE_DETECTED", "FACE_TOUCHES_EDGE"])
        self.assertEqual(v["status"], "FAIL")
        self.assertEqual([r["faces"] for r in count["per_frame"]], [1, 1, 0, 1])  # one detection pass


if __name__ == "__main__":
    unittest.main()
