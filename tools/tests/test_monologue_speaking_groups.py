"""Monologue speaking groups (CAMERA_GRAMMAR_V1, owner 2026-11-01, lab Holmes E12 long-take test).

One continuous 12-14 s take of a single speaker's consecutive lines, with a silent cutaway between groups, played
far better than one shot per line.  Covered here (the grouping itself: test_grouping_respects_cuts.py):
speaking_unit_duration multi-line rules, the S1 writer self-check (R5A multi-line timing, R12 warnings), the V2
camera section of a group (one entry, no all-caps label), keyframe reuse of the earlier same-setup take, the S5
copy of that keyframe, the compiled plan fields, and the S7 head/tail trims on a three-line unit.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
NALU_TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for _path in (str(REPO), str(REPO / "tools"), str(NALU_TOOLS), str(REPO / "tools" / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import build_keyframe_manifest as bkm  # noqa: E402
import dialogue_head_trim as head  # noqa: E402
import dialogue_tail_trim as tail  # noqa: E402
import nalu_pipeline as npl  # noqa: E402
import nalu_writer_selfcheck_seq29 as sc  # noqa: E402
from tools import build_video_unit_grouping_spec as grouping  # noqa: E402
from tools import compile_video_unit_plan as cvp  # noqa: E402
from tools import h3_director_prompt_v2 as v2  # noqa: E402
from tools import speaking_unit_duration as sud  # noqa: E402
from tools.h3_provider_english_contract import ALL_CAPS_LABEL, CAMERA_LOCK_STRICT  # noqa: E402

CAMERA = {"shot_scale": "MEDIUM_WIDE", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
          "motion_family": "LOCKED", "motion_direction": "NONE", "lens_intent": "50mm",
          "start_framing": "Holmes seated, centered", "end_framing": "Holmes seated, centered",
          "camera_grammar": "CAMERA_GRAMMAR_V1"}


class DurationTest(unittest.TestCase):
    def test_single_line_rule_unchanged_and_one_speakers_lines_fit_12s(self):
        one = "Holmes：I beg that you will look upon it"
        self.assertEqual(sud.max_seconds_for([one]), sud.MAX_SECONDS)
        three = [one, "Holmes：not as a battered billycock but as an intellectual problem.",
                 "Holmes：That the man was highly intellectual is of course obvious"]
        self.assertEqual(sud.max_seconds_for(three), 12)
        self.assertEqual(sud.max_seconds_for([one, "Peterson：The goose, Mr. Holmes!"]), sud.MAX_SECONDS)
        row = sud.speaking_duration(12, three, "en")
        self.assertNotIn("WRITER_SPLIT", row["action"])
        self.assertLessEqual(row["duration_seconds"], 12)
        group = sud.group_duration([[line] for line in three], "en")
        self.assertEqual(group["verdict"], "FITS")
        self.assertEqual(group["duration_seconds"], row["duration_seconds"])
        self.assertEqual(sud.group_duration([three, three], "en")["verdict"], "WRITER_SPLIT_REQUIRED")

    def test_setup_key(self):
        self.assertEqual(sud.setup_key(CAMERA), sud.setup_key({**CAMERA, "motivation": "other", "end_framing": "x"}))
        self.assertNotEqual(sud.setup_key(CAMERA), sud.setup_key({**CAMERA, "shot_scale": "CLOSE_UP"}))
        self.assertFalse(sud.locked_setup({**CAMERA, "motion_family": "DOLLY"}))


def _contract_shot(sid, dialogue, mode, camera=None, seconds=4, scene="S01"):
    return {"shot_id": sid, "scene_id": scene, "target_seconds": seconds,
            "internal_transition_authoring": {"transition_mode": mode},
            "prompt_spec": {"dialogue": dialogue, "camera_plan": camera or CAMERA,
                            "cast": [{"character_id": "CHAR-HOLMES", "face_visibility": "VISIBLE_PER_FRAME_CONTENT"}],
                            "role_semantic_disambiguation": {"dialogue_speaker_id": "CHAR-HOLMES"}}}


class SelfCheckTest(unittest.TestCase):
    def test_multi_line_shot_is_timed_by_all_its_lines(self):
        one = "Holmes：I beg that you will look upon it"
        self.assertEqual(sc.derived_dialogue_seconds(one, None),
                         sc.npr.min_dialogue_seconds("I beg that you will look upon it", None, "en"))
        both = one + "\nHolmes：not as a battered billycock but as an intellectual problem."
        joined = sc.derived_dialogue_seconds("Holmes：I beg that you will look upon it not as a battered "
                                             "billycock but as an intellectual problem.", None)
        self.assertEqual(sc.derived_dialogue_seconds(both, None), joined)  # no speaker name counted twice

    def test_r12_warns_on_a_cut_between_lines_and_a_monologue_over_12s(self):
        close = {**CAMERA, "shot_scale": "CLOSE_UP"}
        shots = [_contract_shot("A1", "Holmes：one", "MOTIVATED_CUT"),
                 _contract_shot("A2", "Holmes：two", "MOTIVATED_CUT"),          # authored cut: warn
                 _contract_shot("A3", "Holmes：three", "CONTINUOUS_ACTION", close),  # setup change: warn
                 _contract_shot("A4", "Holmes：four", "CONTINUOUS_ACTION", close),
                 _contract_shot("A5", "Holmes：five", "CONTINUOUS_ACTION", close),
                 _contract_shot("A6", "Holmes：six", "CONTINUOUS_ACTION", close),
                 _contract_shot("A7", "", "MOTIVATED_CUT"),                      # cutaway ends the run
                 _contract_shot("A8", "Holmes：seven", "MOTIVATED_CUT", close)]
        warnings = sc.monologue_warnings({"episode": "E99", "camera_grammar_policy": "CAMERA_GRAMMAR_V1",
                                          "shots": shots})
        self.assertEqual(warnings, ["R12_MONOLOGUE_CUT_BETWEEN_LINES:A2", "R12_MONOLOGUE_CUT_BETWEEN_LINES:A3",
                                    "R12_MONOLOGUE_OVER_12S_ADD_CUTAWAY:A3:16"])
        self.assertEqual(sc.monologue_warnings({"episode": "E99", "shots": shots}), [])  # unstamped: nothing


class CameraSectionTest(unittest.TestCase):
    def _unit(self, modes):
        return {"internal_transition_contracts": [{"transition_mode": m} for m in modes]}

    def _rows(self, *cameras):
        return [{"shot_id": f"S{i}", "start": 4 * i, "end": 4 * i + 4, "camera_plan": c} for i, c in enumerate(cameras)]

    def test_one_setup_take_only_for_an_unchanged_locked_setup_without_a_cut(self):
        rows = self._rows(CAMERA, dict(CAMERA), dict(CAMERA))
        self.assertTrue(v2.one_setup_take(self._unit(["CONTINUOUS_ACTION"] * 2), rows, "U"))
        self.assertFalse(v2.one_setup_take(self._unit(["CONTINUOUS_ACTION", "MOTIVATED_CUT"]), rows, "U"))
        moved = self._rows(CAMERA, {**CAMERA, "shot_scale": "CLOSE_UP"})
        self.assertFalse(v2.one_setup_take(self._unit(["CONTINUOUS_ACTION"]), moved, "U"))
        unstamped = self._rows(*[{k: v for k, v in CAMERA.items() if k != "camera_grammar"}] * 2)
        self.assertFalse(v2.one_setup_take(self._unit(["CONTINUOUS_ACTION"]), unstamped, "U"))
        self.assertFalse(v2.one_setup_take(self._unit([]), rows[:1], "U"))

    def test_the_lock_is_a_sentence_and_no_all_caps_label_remains(self):
        self.assertTrue(ALL_CAPS_LABEL.search(CAMERA_LOCK_STRICT))
        self.assertFalse(ALL_CAPS_LABEL.search(v2.CAMERA_LOCK_TRIPOD))
        self.assertFalse(ALL_CAPS_LABEL.search("Camera:\nLocked camera, eye level. Framing: Holmes seated."))
        self.assertTrue(ALL_CAPS_LABEL.search("WORLD VISUAL LOCK: keep the world"))


def _keyframe_inputs(units):
    return SimpleNamespace(contract={"camera_grammar_policy": "CAMERA_GRAMMAR_V1"}, episode="E99",
                           grouping_plan={"units": units})


class KeyframeReuseTest(unittest.TestCase):
    UNITS = [{"unit_id": "VU-001", "editorial_shot_ids": ["S1", "S2"]},
             {"unit_id": "VU-002", "editorial_shot_ids": ["S3"]},
             {"unit_id": "VU-003", "editorial_shot_ids": ["S4", "S5"], "same_setup_as_unit": "VU-001"}]

    def _rows(self, first="NEW_KEYFRAME"):
        return [{"shot_id": "S1", "decision": first, "novelty_classes": ["NEW_CHARACTER_IDENTITY"]},
                {"shot_id": "S3", "decision": "NEW_KEYFRAME", "novelty_classes": ["NEW_LOCATION_OR_SUBSPACE"]},
                {"shot_id": "S4", "decision": "NEW_KEYFRAME", "video_unit_id": "VU-003",
                 "novelty_classes": ["ENTRY_STATE_DIFFERS_FROM_SETUP_OWNER"]}]

    def test_continuation_reuses_the_earlier_takes_keyframe(self):
        rows = self._rows()
        changed = bkm.monologue_keyframe_reuse(_keyframe_inputs(self.UNITS), rows)
        self.assertEqual([r["shot_id"] for r in changed], ["S4"])
        self.assertEqual((rows[2]["decision"], rows[2]["reuse_mode"], rows[2]["reuse_source"]),
                         ("REUSE_NO_NEW_KEYFRAME", bkm.MONOLOGUE_REUSE_MODE, "S1"))
        self.assertEqual(rows[1]["decision"], "NEW_KEYFRAME")  # the cutaway keeps its own image

    def test_tail_derived_source_or_unstamped_contract_changes_nothing(self):
        rows = self._rows("DEFERRED_TO_PREVIOUS_UNIT_REAL_FINAL_FRAME")
        self.assertEqual(bkm.monologue_keyframe_reuse(_keyframe_inputs(self.UNITS), rows), [])
        rows = self._rows()
        self.assertEqual(bkm.monologue_keyframe_reuse(_keyframe_inputs(self.UNITS), rows, camera_grammar=False), [])
        self.assertEqual(rows[2]["decision"], "NEW_KEYFRAME")

    def test_s5_copies_the_source_bytes_and_recopies_after_a_redo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keyframes = root / "keyframes"
            keyframes.mkdir()
            report = root / "report.json"
            report.write_text(json.dumps({"decision_table": [
                {"shot_id": "S4", "video_unit_id": "VU-003", "decision": "REUSE_NO_NEW_KEYFRAME",
                 "reuse_mode": bkm.MONOLOGUE_REUSE_MODE, "reuse_source": "S1", "reuse_source_unit_id": "VU-001"}]}))
            ctx = SimpleNamespace(p=SimpleNamespace(keyframe_manifest_report=report, keyframes=keyframes))
            self.assertEqual(npl.materialise_monologue_reuse_keyframes(ctx)[0]["status"], "SOURCE_NOT_YET_ON_DISK")
            (keyframes / "S1-keyframe-v1.png").write_bytes(b"first")
            self.assertEqual(npl.materialise_monologue_reuse_keyframes(ctx)[0]["status"], "MATERIALISED")
            self.assertEqual((keyframes / "S4-keyframe-v1.png").read_bytes(), b"first")
            self.assertEqual(npl.materialise_monologue_reuse_keyframes(ctx)[0]["status"], "ALREADY_PRESENT")
            (keyframes / "S1-keyframe-v1.png").write_bytes(b"redo")
            self.assertEqual(npl.materialise_monologue_reuse_keyframes(ctx)[0]["status"], "MATERIALISED")
            self.assertEqual((keyframes / "S4-keyframe-v1.png").read_bytes(), b"redo")
            side = json.loads((keyframes / "S4-keyframe-v1.monologue_reuse.json").read_text())
            self.assertEqual(side["source_shot_id"], "S1")


class CompiledPlanTest(unittest.TestCase):
    def test_plan_carries_the_group_fields(self):
        from unittest.mock import patch
        from tools.tests.test_grouping_respects_cuts import _line, _manifest, _shot
        shots = [_line("01", "I beg that you will look upon it"), _line("02", "not as a battered billycock"),
                 _shot("03", 4, ["H"], "MOTIVATED_CUT"),
                 _line("04", "That the man was highly intellectual", "MOTIVATED_CUT")]
        production, spec = grouping.build(_manifest(shots), "sha")
        with patch.object(cvp, "validate_transition_sequence", lambda units: None):
            plan = cvp.compile_grouping_spec(production, spec)
        units = plan["units"]
        self.assertEqual(units[0]["speaking_group"], {"speaker_id": "CHAR-H", "line_count": 2})
        self.assertEqual(units[2]["same_setup_as_unit"], "E09-VU-001")
        self.assertNotIn("same_setup_as_unit", units[1])


def _seg(*words):
    return {"start": words[0][0], "end": words[-1][1], "text": "".join(w for _, _, w in words).strip(),
            "words": [{"start": a, "end": b, "word": w} for a, b, w in words]}


class TrimTest(unittest.TestCase):
    """S7: the head trim acts before the first line, the tail trim after the last; lines in between stay."""

    LINES = [("S1", "I beg that you will look upon it"),
             ("S2", "not as a battered billycock but as an intellectual problem."),
             ("S3", "That the man was highly intellectual is of course obvious")]

    def _contract(self):
        return {"episode": "E99", "dialogue_language": "en", "camera_grammar_policy": "CAMERA_GRAMMAR_V1",
                "character_entities": [{"character_id": "CHAR-H", "identity_source": {"mode": "TEXT_TO_IMAGE"}}],
                "shots": [{"shot_id": sid, "target_seconds": 4.0} for sid, _ in self.LINES],
                "audio_contract": {"dialogue_units": [{"shot_id": sid, "speaker_id": "CHAR-H", "text": text}
                                                      for sid, text in self.LINES]}}

    def test_three_line_unit(self):
        asr = {"U1": [_seg((0.0, 0.4, " Ha!")),
                      _seg((0.9, 1.1, " I"), (1.1, 1.3, " beg"), (1.3, 1.5, " that"), (1.5, 1.7, " you"),
                           (1.7, 1.9, " will"), (1.9, 2.1, " look"), (2.1, 2.3, " upon"), (2.3, 2.6, " it")),
                      _seg((3.0, 3.3, " not"), (3.3, 3.5, " as"), (3.5, 3.6, " a"), (3.6, 4.0, " battered"),
                           (4.0, 4.5, " billycock"), (4.5, 4.7, " but"), (4.7, 4.8, " as"), (4.8, 4.9, " an"),
                           (4.9, 5.5, " intellectual"), (5.5, 6.0, " problem.")),
                      _seg((7.0, 7.2, " That"), (7.2, 7.4, " the"), (7.4, 7.6, " man"), (7.6, 7.8, " was"),
                           (7.8, 8.1, " highly"), (8.1, 8.7, " intellectual"), (8.7, 8.8, " is"),
                           (8.8, 8.9, " of"), (8.9, 9.2, " course"), (9.2, 9.8, " obvious.")),
                      _seg((10.4, 10.8, " and"), (10.8, 11.2, " moreover"))]}
        grouping_plan = {"units": [{"unit_id": "U1", "editorial_shot_ids": ["S1", "S2", "S3"]}]}
        clips = {"U1": 12.25}
        tail_report = tail.plan(self._contract(), grouping_plan, asr, clips)
        row = tail_report["units"][0]
        self.assertTrue(row["trimmed"])
        self.assertAlmostEqual(row["line_end_seconds"], 9.8)
        self.assertAlmostEqual(row["kept_seconds"], 10.3)  # 0.5 s after the last line, before "and moreover"
        head_row = head.plan(self._contract(), grouping_plan, asr, clips, tail_report)["units"][0]
        self.assertTrue(head_row["trimmed"])
        self.assertEqual(head_row["removed_text"], "Ha!")
        self.assertAlmostEqual(head_row["head_cut_seconds"], 0.75)  # 0.15 s before "I beg"


if __name__ == "__main__":
    unittest.main()
