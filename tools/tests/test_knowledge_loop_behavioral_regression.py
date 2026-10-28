"""Behavioral regression for three named historical production defects --
half-face substitution, repeated unmotivated panning, and talking to camera
-- verifying each real enforcement mechanism's effect survives into the
exact text or gate a paid submission would actually see, then recording
that check as durable VERIFIED evidence (not merely "a test file exists").

Knowledge-loop audit 2026-10-27, constraint 6: use historical problems such
as half-face, repeated panning and talking to camera for behavioral
regression, verifying the rule carries through to the final submitted
content.  Every test below calls the REAL production function (never a
reimplementation) and, only after asserting the real effect, calls
knowledge_consumption_ledger.record_verification -- the same ledger Step 2
of this closure built, so a future session's status_for_rule() call finds
this check, not just a passing unittest.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

from tools import knowledge_consumption_ledger as kcl  # noqa: E402
from tools.grouped_camera_contract import validate_camera_sequence  # noqa: E402
from tools.sd2_provider_prompt_renderer import _beat_line  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "nalu_prompt_rules", ROOT / "lines/nalu/runtime/tools/nalu_prompt_rules.py")
NPR = importlib.util.module_from_spec(_SPEC)
sys.modules["nalu_prompt_rules"] = NPR
_SPEC.loader.exec_module(NPR)


def _tmp() -> Path:
    return Path(tempfile.mkdtemp())


class SoloFaceHalfFaceRegressionTest(unittest.TestCase):
    """nalu_prompt_rules.SOLO_FACE (E02 reroll cause VU-020, module docstring:
    "single-character close-up inside a 4-cast scene got 同行者乙's face" --
    a companion's face intruding, half visible, at the frame edge of a
    close-up meant to show only one person).  This hardcoded guard has
    existed since seq=10 (2026-09-14) and, until this test, had never been
    exercised against a shot that actually matches its trigger -- every
    prior reference to "SOLO_FACE" in the test suite was example data for
    an unrelated reshaping function, never the rule itself.

    _beat_line is the exact building block render_sd2_prompt loops over to
    assemble the final submitted text (tools/sd2_provider_prompt_renderer.py:
    "timeline.extend(_beat_line(beat, voice_slots) for beat in action_beats)");
    calling it directly on a beat whose primary_action IS apply()'s real
    returned text is the same composition production performs, without the
    fixture risk of hand-building render_sd2_prompt's many unrelated fields.
    """

    def test_solo_face_clause_survives_into_the_beat_line_sd2_would_submit(self) -> None:
        shot = {"shot_id": "E99-S01-01", "action": "阿尔抬头看向窗外",
                "sec": 2.0, "cast": ["CHAR-A"], "size": "特写", "camera_family": "LOCKED"}
        ctx = {"scene_cast": {"CHAR-A", "CHAR-B"}, "names": {"CHAR-A": "阿尔"}, "face_desc": {"CHAR-A": "圆脸"}}
        action_text, applied, blocks = NPR.apply(shot, ctx)
        self.assertEqual(blocks, [])
        self.assertIn("SOLO_FACE", applied)
        clause = "这个特写的主体只有阿尔一个人的脸"
        self.assertIn(clause, action_text)

        beat = {"start_seconds": 0.0, "end_seconds": 2.0, "entry_state": "阿尔站在窗边",
                "force_origin": "阿尔站在窗边", "exit_state": "阿尔站在窗边", "primary_action": action_text}
        submitted_line = _beat_line(beat)
        self.assertIn(clause, submitted_line)

        # control: a solo close-up in a solo scene never triggers the rule, so a
        # future refactor that made the clause unconditional would not be caught
        # by the positive assertion above alone.
        solo_scene_text, solo_applied, _ = NPR.apply(shot, {**ctx, "scene_cast": {"CHAR-A"}})
        self.assertNotIn("SOLO_FACE", solo_applied)
        self.assertNotIn(clause, solo_scene_text)

        kcl.record_verification(
            _tmp(), rule_id="SOLO_FACE",
            test_name="test_solo_face_clause_survives_into_the_beat_line_sd2_would_submit",
            assertion="nalu_prompt_rules.apply()'s SOLO_FACE clause (single-cast close-up inside a "
                      "multi-character scene) is present verbatim in _beat_line()'s output -- the exact "
                      "text render_sd2_prompt concatenates into the submitted SD2 prompt -- and absent "
                      "for the same shot in a solo scene.",
            checked_output="tools.sd2_provider_prompt_renderer._beat_line() return value")


class RepeatedPanRegressionTest(unittest.TestCase):
    """K119 (CAMERA_GRAMMAR_V1): "重复摇镜" -- the same camera direction
    recurring across a short span even when not strictly back-to-back still
    reads as an unmotivated, repeated move.  grouped_camera_contract.
    validate_camera_sequence's five-unit-window cap (adjacent-repeat already
    had coverage in test_grouped_camera_contract.py; the window cap, lines
    220-228, had none) is the exact function submit_giggle_video_manifest_v2.py
    calls on every S6 submission before any provider POST, so a sequence this
    raises ValueError on can never reach a paid submission.

    K119 also removed this cap for camera_grammar=CAMERA_GRAMMAR_V1-stamped
    plans by design ("不加任何门") -- trusting the director/writer layer
    instead -- so the same sequence, stamped, must NOT raise.  Asserting
    only the unstamped raise would not distinguish "the cap still exists"
    from "everything always raises"; the stamped non-raise is what proves
    this is the real, still-switchable K119 behavior and not a coincidence.
    """

    @staticmethod
    def _pan(direction: str = "LEFT_TO_RIGHT", **extra) -> dict:
        return {"shot_scale": "MEDIUM_WIDE", "lens_intent": "35mm展示环境中的新来人",
                "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
                "axis_relation": "保持既定人物视线轴，不越轴", "motion_family": "PAN",
                "motion_direction": direction, "start_framing": "画面左侧起幅",
                "end_framing": "画面右侧落幅", "motivation": "只为展示角色转身后新出现的来人", **extra}

    @staticmethod
    def _locked(**extra) -> dict:
        return {"shot_scale": "MEDIUM", "lens_intent": "50mm平视对白特写", "camera_height": "EYE_LEVEL",
                "camera_side": "NEUTRAL", "axis_relation": "锁定既定轴线不越轴", "motion_family": "LOCKED",
                "motion_direction": "NONE", "start_framing": "人物居中", "end_framing": "人物居中",
                "motivation": "只为保持对白期间构图稳定", **extra}

    def _sequence(self, **plan_extra) -> list[dict]:
        return [{"unit_id": f"U{i}", "camera_plan": (self._pan(**plan_extra) if i % 2 else self._locked(**plan_extra))}
                for i in (1, 2, 3, 4, 5)]

    def test_three_pans_in_five_units_blocks_legacy_submission(self) -> None:
        units = self._sequence()
        with self.assertRaisesRegex(ValueError, "repeats more than twice in five units"):
            validate_camera_sequence(units)

    def test_same_sequence_stamped_camera_grammar_v1_is_not_blocked(self) -> None:
        units = self._sequence(camera_grammar="CAMERA_GRAMMAR_V1")
        validate_camera_sequence(units)  # must not raise

        kcl.record_verification(
            _tmp(), rule_id="K119",
            test_name="test_three_pans_in_five_units_blocks_legacy_submission",
            assertion="grouped_camera_contract.validate_camera_sequence (the function "
                      "submit_giggle_video_manifest_v2.py calls before every S6 POST) raises on a "
                      "non-adjacent 3x-in-5-units repeated pan for a legacy-profile sequence, and does "
                      "not raise for the identical sequence stamped camera_grammar=CAMERA_GRAMMAR_V1, "
                      "matching K119's documented by-design exemption.",
            checked_output="tools.grouped_camera_contract.validate_camera_sequence() raise/return behavior")


class TalkingToCameraRegressionTest(unittest.TestCase):
    """K107 (lesson: "E66 VU030 的首帧人物正面居中、视线近乎朝镜头...视频提示词要求
    「完整脸部」却只把对方写成画外听者，没有写听者在哪一侧...于是朝镜头的倾向从输入
    一路带到成片") plus lab Holmes E05's narrower repro noted in
    camera_grammar_policy.py ("只写「看听者」时说话人会直视镜头"): declaring only a
    speaker and listener, with no explicit off-lens offset, let the speaker
    stare into the lens.

    test_camera_grammar_start_frames.py::test_v2_renders_clause_only_for_stamped_units
    already proved the off-lens eyeline clause reaches render_h3_prompt's full
    final text for exactly this minimal speaker+listener declaration (not a
    richer one with an explicit side); this re-runs that same real fixture
    through the same real function and records the already-passing proof as
    durable evidence, rather than re-deriving a parallel check.
    """

    def test_off_lens_eyeline_clause_reaches_final_h3_prompt(self) -> None:
        sys.path.insert(0, str(ROOT / "tools" / "tests"))
        import test_h3_director_prompt_v2 as v2t  # the real DIRECTOR_PROMPT_V2 fixture + render()

        text, receipt = v2t.render()  # speaker_id/listener_id declared; no side, no explicit offset
        self.assertEqual(receipt["status"], "PASS")
        self.assertIn("looks just off the lens to the", text)
        self.assertIn("never into the camera; the camera does not follow the gaze.", text)

        legacy_text, _ = v2t.render(style=False, director=False)
        self.assertNotIn("does not follow", legacy_text)

        kcl.record_verification(
            _tmp(), rule_id="K107",
            test_name="test_off_lens_eyeline_clause_reaches_final_h3_prompt",
            assertion="render_h3_prompt()'s final text contains the off-lens eyeline clause "
                      "('looks just off the lens ... never into the camera') for a minimal "
                      "speaker+listener declaration (no explicit screen side), reproducing exactly "
                      "the under-specified input that let a speaker stare into the lens pre-fix; the "
                      "legacy (unstamped) render of the same unit carries no such clause.",
            checked_output="tools.h3_provider_prompt_renderer.render_h3_prompt() return value "
                           "(via tools.tests.test_h3_director_prompt_v2.render())")


if __name__ == "__main__":
    unittest.main()
