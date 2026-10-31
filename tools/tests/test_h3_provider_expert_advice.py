"""MiniMax-H3 provider-expert advice (line owner 2026-10-26, lab Holmes E04; synthetic fixtures).

1. voice: silent units say nobody speaks; speaking units "only this one line, once";
2. camera: one continuous take + fixed camera position, said once;
3. anti-duplicate sentence is the prompt's last line (not on object inserts);
   + the optional Chinese constraint wording (h3_constraint_language "zh") and its A/B variant;
4./5. multi-view character reference sheet (+ physical traits, state variants);
6. speaking-shot duration (line + 0.5 s, 3-5 s);
7. the engine's own one controlled redo after an objective Q2 FAIL.
CAMERA_GRAMMAR_V1-stamped units only; unstamped renders are pinned to the origin/main (b2ba893) bytes.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import character_reference_sheet as sheet  # noqa: E402
import nalu_pipeline as npl  # noqa: E402
import q2_auto_redo  # noqa: E402
from tools import h3_provider_prompt_renderer as h3  # noqa: E402
from tools.h3_provider_english_contract import H3_CONSTRAINT_ZH, validate_h3_provider_text_boundary  # noqa: E402
from tools.speaking_unit_duration import speaking_duration  # noqa: E402
from tools.tests.test_h3_director_performance import unit_plan  # noqa: E402
from tools.tests.test_h3_director_prompt import vu011, vu012  # noqa: E402
from tools.tests.test_h3_director_prompt_v2 import STYLE, fixture  # noqa: E402

render = h3.render_h3_prompt
ZH_CAMERA = H3_CONSTRAINT_ZH["one_take"] + "；" + H3_CONSTRAINT_ZH["fixed_camera"] + "。"

#: sha256 of the renderer output for unstamped fixtures: nothing here may move them except a renderer-wide
#: redundancy fix.  Re-pinned 2026-10-28 (10,000-rune budget fix, E12-VU-003): "Start from X. Force origin: X."
#: no longer repeats X when force_origin equals entry_state; v2_unstamped's beat has a distinct force_origin
#: so it is untouched (confirmed: still matches the b2ba893 bytes).  Every other pin here moved by exactly that
#: one dropped clause, confirmed by diffing old vs new rendered text.
#: Re-pinned 2026-10-30 (E12 burned subtitles, K143): TEXT-FREE FRAME moved from negative_constraints to the first
#: line; diffing old vs new rendered text shows that move only.
UNSTAMPED_PINS = {
    "v2_unstamped": "8604f0b83bd9f1ea20b7f3127ea5d58fda388166968d537613521ab813fc19b2",
    "v1_unstamped_two": "838e3f8960139ef5810a783a67462bfac6cf944b0b6546c9966f6524a07d8323",
    "v1_unstamped_dialogue": "a50f6df329cbfcaae1bd79f276879941ff7010a51db3a88029374e892b3f3efe",
    "v1_unstamped_vu011": "4ba536b1b9000a2e1f278f6a35830a62dd73d6c1257a43e124482f83b7ea065d",
    "v1_unstamped_vu012": "58e507cf970ea11a4d688138288135654821f7656165f175c436ca65e20e08a2",
}
UNSTAMPED = {
    "v2_unstamped": lambda: fixture(style=True, director=False),
    "v1_unstamped_two": lambda: fixture(style=False, director=False),
    "v1_unstamped_dialogue": lambda: unit_plan(stamped=False, performance=None),
    "v1_unstamped_vu011": lambda: vu011(stamped=False),
    "v1_unstamped_vu012": lambda: vu012(stamped=False),
}


def v2(**kwargs):
    unit, plan = fixture(**kwargs)
    return unit, plan


def zh(pair):
    unit, plan = pair
    unit["h3_constraint_language"] = "zh"
    return unit, plan


class VoiceAndCameraTest(unittest.TestCase):
    def test_v2_speaking_unit(self):
        text, _ = render(*v2())
        self.assertIn(h3.ONLY_THIS_LINE, text)
        self.assertNotIn("After the line nobody speaks", text)
        camera = text.split("Camera:\n", 1)[1].split("\n\n", 1)[0]
        self.assertIn("Locked camera, eye level, medium shot. " + h3.ONE_TAKE + " " + h3.FIXED_CAMERA_POSITION, camera)
        self.assertNotIn("The camera never moves", camera)
        self.assertNotIn("still, composed frame", camera)
        self.assertEqual(camera.count("no pan"), 1)

    def test_v2_silent_unit(self):
        unit, plan = vu011(stamped=True)
        unit.update(STYLE)
        text, _ = render(unit, plan)
        self.assertIn("Dialogue: none. " + h3.NO_VOICE_SILENT, text)
        self.assertIn(h3.ONE_TAKE, text)  # a moving camera is still one continuous take

    def test_v1_stamped_units(self):
        text, _ = render(*unit_plan(stamped=True, performance=None))
        vocal = next(line for line in text.splitlines() if line.startswith("vocal_rule: "))
        self.assertTrue(vocal.endswith(h3.ONLY_THIS_LINE))
        camera = next(line for line in text.splitlines() if line.startswith("camera: "))
        self.assertIn("locked camera; fixed camera position: no push in, no pull out, no pan, no tilt, no tracking",
                      camera)
        self.assertIn("one continuous take from the first frame to the last, no cuts or splices", camera)
        self.assertNotIn("no drift", camera)
        self.assertEqual(h3.locked_camera_move_conflicts(text), [])
        silent, _ = render(*vu011(stamped=True))
        self.assertTrue(next(line for line in silent.splitlines()
                             if line.startswith("vocal_rule: ")).endswith(h3.NO_VOICE_SILENT))

    def test_hard_cut_units_are_not_one_take(self):
        self.assertFalse(h3.one_take_applies([{"camera_grammar": "CAMERA_GRAMMAR_V1"}] * 2,
                                             ["opening shot", "hard cut to a new framing"]))
        self.assertTrue(h3.one_take_applies([{"camera_grammar": "CAMERA_GRAMMAR_V1"}] * 2,
                                            ["opening shot", "no cut; one continuous camera move into this framing"]))
        self.assertFalse(h3.one_take_applies([{}], []))


class AntiDuplicateTest(unittest.TestCase):
    def test_last_line_of_stamped_prompts_with_people(self):
        for text in (render(*v2())[0], render(*unit_plan(stamped=True, performance=None))[0],
                     render(*vu011(stamped=True))[0]):
            self.assertEqual(text.rstrip("\n").splitlines()[-1], h3.NO_DUPLICATE_PEOPLE)

    def test_object_insert_gets_no_person_clause(self):
        unit, plan = vu012(stamped=True)
        self.assertNotIn(h3.NO_DUPLICATE_PEOPLE, render(unit, plan)[0])
        unit.update(STYLE)
        self.assertNotIn(h3.NO_DUPLICATE_PEOPLE, render(unit, plan)[0])


class ConstraintLanguageTest(unittest.TestCase):
    def test_zh_swaps_only_the_constraint_sentences(self):
        en, _ = render(*v2())
        text, receipt = render(*zh(v2()))
        self.assertEqual(receipt["h3_constraint_language"], "zh")
        self.assertIn(ZH_CAMERA, text)
        self.assertIn(H3_CONSTRAINT_ZH["only_this_line"], text)
        self.assertEqual(text.rstrip("\n").splitlines()[-1], H3_CONSTRAINT_ZH["no_duplicate"])
        for sentence in (h3.ONE_TAKE, h3.FIXED_CAMERA_POSITION, h3.ONLY_THIS_LINE, h3.NO_DUPLICATE_PEOPLE):
            self.assertNotIn(sentence, text)
        self.assertEqual(h3.localize_constraints(en, "zh"), text)
        v1_text, _ = render(*zh(unit_plan(stamped=True, performance=None)))
        self.assertIn("locked camera; " + H3_CONSTRAINT_ZH["fixed_camera"], v1_text)
        self.assertIn(H3_CONSTRAINT_ZH["only_this_line"], v1_text)
        silent, _ = render(*zh(vu011(stamped=True)))
        self.assertIn(H3_CONSTRAINT_ZH["silent"], silent)

    def test_boundary_accepts_only_the_verbatim_sentences(self):
        text, _ = render(*zh(v2()))
        self.assertEqual(validate_h3_provider_text_boundary(text, source_id="T")["status"], "PASS")
        self.assertEqual(validate_h3_provider_text_boundary(text + "机位固定，不推、不拉、不摇、不移。\n",
                                                            source_id="T")["status"], "PASS")
        self.assertEqual(validate_h3_provider_text_boundary(text + "机位固定。\n", source_id="T")["status"], "FAIL")
        self.assertEqual(validate_h3_provider_text_boundary(text + "人物不要动。\n", source_id="T")["status"], "FAIL")

    def test_unstamped_units_ignore_the_flag_and_stay_byte_identical(self):
        for name, make in UNSTAMPED.items():
            for flag in (False, True):
                unit, plan = make()
                if flag:
                    unit["h3_constraint_language"] = "zh"
                text, receipt = render(unit, plan)
                self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), UNSTAMPED_PINS[name], (name, flag))
                self.assertNotIn("h3_constraint_language", receipt)

    def test_ab_variant_task(self):
        import h3_constraint_ab_variant as ab
        task = {"task_key": "E04-VU-008", "unit_id": "E04-VU-008", "submission_status": "SUBMITTED"}
        variant = ab.variant_task(task)
        self.assertEqual(variant["task_key"], "E04-VU-008-ZH")
        self.assertEqual(variant["h3_constraint_language"], "zh")
        self.assertEqual(variant["ab_variant_of"], "E04-VU-008")
        self.assertNotIn("submission_status", variant)
        self.assertEqual(task["task_key"], "E04-VU-008")


class CameraLockStrictTest(unittest.TestCase):
    """Strict camera lock: DEFAULT for CAMERA_GRAMMAR_V1 single-take locked units (owner 2026-10-26 after the
    lab Holmes E06 A/B: VU-008 push-in 65% -> 15%, VU-001 98% -> 39%); "standard" opts out."""

    @staticmethod
    def mode(pair, value):
        unit, plan = pair
        unit["h3_camera_lock"] = value
        return unit, plan

    def test_v2_default_adds_exactly_three_things(self):
        from tools.h3_provider_english_contract import (
            CAMERA_LOCK_FROZEN_FRAME, CAMERA_LOCK_NEVER, CAMERA_LOCK_STRICT, is_director_v2_text,
            validate_h3_provider_text_boundary as boundary)
        base, base_receipt = render(*self.mode(v2(), "standard"))
        text, receipt = render(*v2())
        self.assertEqual(receipt["h3_camera_lock"], "strict")
        self.assertNotIn("h3_camera_lock", base_receipt)
        self.assertEqual(render(*self.mode(v2(), "strict"))[0], text)  # explicit strict == the default
        self.assertEqual(render(*self.mode(v2(), "loose"))[0], text)  # unknown value == the default
        self.assertTrue(text.startswith(CAMERA_LOCK_STRICT + "\n\nReferences:\n"))
        camera = text.split("Camera:\n", 1)[1].split("\n\n", 1)[0]
        self.assertTrue(camera.endswith("\n" + CAMERA_LOCK_FROZEN_FRAME))
        self.assertIn(h3.FIXED_CAMERA_POSITION, camera)  # the expert wording stays
        never = next(line for line in text.splitlines() if line.startswith("Never: "))
        self.assertTrue(never.endswith("; music; " + CAMERA_LOCK_NEVER + "."))
        self.assertEqual(text.rstrip("\n").splitlines()[-1], h3.NO_DUPLICATE_PEOPLE)
        undone = (text.replace(CAMERA_LOCK_STRICT + "\n\n", "", 1)
                  .replace("\n" + CAMERA_LOCK_FROZEN_FRAME, "", 1).replace("; " + CAMERA_LOCK_NEVER, "", 1))
        self.assertEqual(undone, base)
        self.assertEqual(boundary(text, source_id="T")["status"], "PASS")
        self.assertTrue(is_director_v2_text(text) and is_director_v2_text(base))
        import prompt_batch_qa
        self.assertTrue(prompt_batch_qa.is_h3_director_v2(text))
        self.assertTrue(prompt_batch_qa.section(text, "锚点").startswith("@Image1"))

    def test_moving_camera_keeps_its_wording_and_explicit_strict_is_refused(self):
        from tools.h3_provider_english_contract import CAMERA_LOCK_STRICT
        unit, plan = vu011(stamped=True)
        unit.update(STYLE)
        text, receipt = render(unit, plan)
        self.assertNotIn(CAMERA_LOCK_STRICT, text)
        self.assertNotIn("h3_camera_lock", receipt)
        unit, plan = vu011(stamped=True)
        unit.update(STYLE, h3_camera_lock="strict")
        with self.assertRaisesRegex(ValueError, "H3_CAMERA_LOCK_STRICT_ON_MOVING_CAMERA"):
            render(unit, plan)

    def test_v1_director_default_and_opt_out(self):
        from tools.h3_provider_english_contract import CAMERA_LOCK_FROZEN_CLAUSE
        text, receipt = render(*unit_plan(stamped=True, performance=None))
        base, base_receipt = render(*self.mode(unit_plan(stamped=True, performance=None), "standard"))
        camera = next(line for line in text.splitlines() if line.startswith("camera: "))
        self.assertTrue(camera.rstrip(".").endswith("; " + CAMERA_LOCK_FROZEN_CLAUSE), camera)
        self.assertEqual(text.replace("; " + CAMERA_LOCK_FROZEN_CLAUSE, "", 1), base)
        self.assertEqual((receipt.get("h3_camera_lock"), base_receipt.get("h3_camera_lock")), ("strict", None))
        self.assertEqual(h3.locked_camera_move_conflicts(text), [])
        moving, _ = render(*vu011(stamped=True))  # V1 moving camera: unchanged
        self.assertNotIn(CAMERA_LOCK_FROZEN_CLAUSE, moving)

    def test_unstamped_stay_byte_identical_whatever_is_declared(self):
        for name, make in UNSTAMPED.items():
            for value in (None, "strict", "standard"):
                unit, plan = make()
                if value:
                    unit["h3_camera_lock"] = value
                text, receipt = render(unit, plan)
                self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), UNSTAMPED_PINS[name], (name, value))
                self.assertNotIn("h3_camera_lock", receipt)

    def test_declared_mode_parsing(self):
        from tools.h3_provider_english_contract import h3_camera_lock, strict_camera_lock_applies
        self.assertEqual([h3_camera_lock({"h3_camera_lock": v}) for v in ("strict", " Standard ", "loose", None)],
                         ["strict", "standard", "", ""])
        self.assertFalse(strict_camera_lock_applies({}, stamped=False, locked_single_take=True))
        self.assertTrue(strict_camera_lock_applies({}, stamped=True, locked_single_take=True))
        self.assertFalse(strict_camera_lock_applies({}, stamped=True, locked_single_take=False))
        self.assertFalse(strict_camera_lock_applies({"h3_camera_lock": "standard"}, stamped=True,
                                                    locked_single_take=True))

    def test_provider_prompt_unit_carries_the_flag(self):
        from tools.submit_giggle_video_manifest_v2 import provider_prompt_unit
        with mock.patch("tools.submit_giggle_video_manifest_v2.grouped_sequence_unit", lambda _t: {}):
            self.assertEqual(provider_prompt_unit({"h3_camera_lock": "strict"}).get("h3_camera_lock"), "strict")
            self.assertNotIn("h3_camera_lock", provider_prompt_unit({}))

    def test_ab_variant_task(self):
        import h3_constraint_ab_variant as ab
        task = {"task_key": "E06-VU-008", "unit_id": "E06-VU-008", "prompt_batch_finalization": {"path": "x"}}
        variant = ab.variant_task(task, variant_name="camera_lock_strict")
        self.assertEqual(variant["task_key"], "E06-VU-008-LOCK")
        self.assertEqual(variant["h3_camera_lock"], "strict")
        self.assertNotIn("h3_constraint_language", variant)
        self.assertNotIn("prompt_batch_finalization", variant)
        self.assertEqual(ab.variant_task(task)["task_key"], "E06-VU-008-ZH")
        self.assertEqual(ab.SCHEMA_VARIANT[ab.LOCK_SCHEMA], "camera_lock_strict")
        self.assertEqual(ab.SCHEMA_VARIANT[ab.SCHEMA], "zh")
        self.assertEqual(ab.verify({"ab_variant_schema": ab.LOCK_SCHEMA, "tasks": []})[:2],
                         ["AB_VARIANT_KIND_MISMATCH:None", "AB_VARIANT_TASK_COUNT:0"])


class ReferenceSheetTest(unittest.TestCase):
    CONTRACT = {"episode": "E05", "camera_grammar_policy": "CAMERA_GRAMMAR_V1", "character_entities": [
        {"character_id": "CHAR-HELEN", "canonical_name": "Helen", "english_name": "Helen",
         "appearance_ch1": "An English woman of thirty, pale face, dark hair."},
        {"character_id": "CHAR-JOHN", "canonical_name": "John", "english_name": "John",
         "appearance_ch1": "A soldier of forty. His left arm is missing below the elbow. Short brown hair.",
         "state_variants": {"one_arm": "left arm missing below the elbow, sleeve pinned up"}},
        {"character_id": "CHAR-CROW", "identity_source": {"mode": "VOICE_ONLY_NO_PLATE"}}]}

    def _library(self, tmp: Path) -> dict:
        rows = {}
        for cid in ("CHAR-HELEN", "CHAR-JOHN"):
            full, head = tmp / f"E01_{cid}_aaaaaaaa.png", tmp / f"E01_{cid}__FRONT_NEUTRAL_HEADSHOT_bbbbbbbb.png"
            full.write_bytes(cid.encode() + b"full"); head.write_bytes(cid.encode() + b"head")
            rows[cid] = {"status": "LOCKED", "qa": {"status": "PASS"}, "artifacts": [
                {"role": "FULL_BODY_STANDING", "path": str(full), "sha256": sheet.sha256_file(full)},
                {"role": "FRONT_NEUTRAL_HEADSHOT", "path": str(head), "sha256": sheet.sha256_file(head)}]}
        return {"assets": {"characters": rows}}

    def test_registered_characters_get_one_sheet_each_plus_declared_states(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            rows, deferred, skipped = sheet.plan_rows(self.CONTRACT, self._library(tmp), episode="E05",
                                                      prompt_dir=tmp / "prompts", plates_dir=tmp / "plates",
                                                      new_subject_ids=set())
            self.assertEqual([r["id"] for r in rows], ["CHAR-HELEN__MULTIVIEW_REFERENCE_SHEET",
                                                       "CHAR-JOHN__MULTIVIEW_REFERENCE_SHEET",
                                                       "CHAR-JOHN__MULTIVIEW_REFERENCE_SHEET__ONE_ARM"])
            self.assertEqual((deferred, skipped), ([], []))
            self.assertTrue(all(len(r["reference_images"]) == 2 for r in rows))  # locked full body + headshot
            john = Path(rows[1]["prompt_file"]).read_text()
            self.assertIn("全身侧面", john)
            self.assertIn("【身体特征·必须呈现】His left arm is missing below the elbow", john)
            self.assertIn("【本图状态·必须呈现】left arm missing below the elbow",
                          Path(rows[2]["prompt_file"]).read_text())
            self.assertNotIn("身体特征", Path(rows[0]["prompt_file"]).read_text())

    def test_unstamped_or_opted_out_plans_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            for contract in ({**self.CONTRACT, "camera_grammar_policy": "LEGACY_FORCED_MOTION"},
                             {**self.CONTRACT, "character_reference_sheet": "NONE"}):
                self.assertEqual(sheet.plan_rows(contract, self._library(tmp), episode="E05", prompt_dir=tmp,
                                                 plates_dir=None, new_subject_ids=set()), ([], [], []))

    def test_new_character_waits_for_its_base_plate(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            contract = {**self.CONTRACT, "character_entities": self.CONTRACT["character_entities"][:1]}
            rows, deferred, _ = sheet.plan_rows(contract, {}, episode="E05", prompt_dir=tmp, plates_dir=tmp / "p",
                                                new_subject_ids={"CHAR-HELEN"})
            self.assertEqual((rows, [r["id"] for r in deferred]), ([], ["CHAR-HELEN__MULTIVIEW_REFERENCE_SHEET"]))

    def test_register_and_lookup(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            library = self._library(tmp)
            path = tmp / "library.json"; path.write_text(json.dumps(library))
            plates = tmp / "plates"; plates.mkdir()
            (plates / "E05_CHAR-HELEN__MULTIVIEW_REFERENCE_SHEET_1234abcd.png").write_bytes(b"sheet")
            (plates / "E05_CHAR-JOHN__MULTIVIEW_REFERENCE_SHEET_1234abcd.png").write_bytes(b"sheet j")
            (plates / "E05_CHAR-JOHN__MULTIVIEW_REFERENCE_SHEET__ONE_ARM_1234abcd.png").write_bytes(b"sheet j1")
            scores = {"CHAR-HELEN": 0.62, "CHAR-JOHN": 0.2}
            report = sheet.register(path, plates, "E05", measure=lambda s, h: scores[s.name.split("_")[1]])
            self.assertEqual({(r["character_id"], r["state"]): r["status"] for r in report},
                             {("CHAR-HELEN", "DEFAULT"): "PASS", ("CHAR-JOHN", "DEFAULT"): "FAIL_FACE_MISMATCH",
                              ("CHAR-JOHN", "ONE_ARM"): "FAIL_FACE_MISMATCH"})
            rows = json.loads(path.read_text())["assets"]["characters"]
            self.assertEqual(sheet.registered_sheet(rows["CHAR-HELEN"]).name,
                             "E05_CHAR-HELEN__MULTIVIEW_REFERENCE_SHEET_1234abcd.png")
            self.assertIsNone(sheet.registered_sheet(rows["CHAR-JOHN"]))  # mismatch: H3 keeps the headshot
            self.assertEqual(rows["CHAR-HELEN"]["artifacts"], library["assets"]["characters"]["CHAR-HELEN"]["artifacts"])
            # registered sheets are not planned again
            planned, _, _ = sheet.plan_rows(self.CONTRACT, rows and json.loads(path.read_text()), episode="E06",
                                            prompt_dir=tmp / "p6", plates_dir=None, new_subject_ids=set())
            self.assertNotIn("CHAR-HELEN__MULTIVIEW_REFERENCE_SHEET", [r["id"] for r in planned])

    def test_identity_review_never_sees_the_sheet(self):
        import vlm_review_protocol as vrp
        self.assertIn('"__MULTIVIEW_REFERENCE_SHEET" not in item.name', Path(vrp.__file__).read_text())

    def test_renderers_name_the_sheet_as_one_person(self):
        unit, plan = v2()
        unit["reference_images"][1]["path"] = "plates/E05_CHAR-A__MULTIVIEW_REFERENCE_SHEET_1234abcd.png"
        text, _ = render(unit, plan)
        self.assertIn("@Image2 is a character sheet of one person: Alpha's face close-up and full-body front, side "
                      "and back views in the same clothes; these are views of a single person, render Alpha only once.",
                      text)
        self.assertIn("@Image3 is Beta's face and body.", text)

    def test_bnp_prefers_the_registered_sheet_only_when_active(self):
        import build_nalu_preproduction as bnp
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            sheet_png = tmp / "E05_CHAR-A__MULTIVIEW_REFERENCE_SHEET_1234abcd.png"; sheet_png.write_bytes(b"s")
            head = tmp / "head.png"; head.write_bytes(b"h")
            library = {"assets": {"characters": {"CHAR-A": {"reference_sheets": {"DEFAULT": {
                "path": str(sheet_png), "sha256": sheet.sha256_file(sheet_png), "status": "PASS"}}}}}}
            lib_path = tmp / "library.json"
            with mock.patch.object(bnp, "_locked_identity_plate", lambda *_a, **_k: head), \
                    mock.patch.object(bnp, "_scoped_asset_library_path", lambda _e: lib_path), \
                    mock.patch.dict(bnp._ASSET_LIBRARY_CACHE, {str(lib_path.resolve()): library}), \
                    mock.patch.object(bnp, "_has_original_authority", lambda *_a: False):
                with mock.patch.dict(bnp._REFERENCE_SHEET_POLICY, {"active": False}):
                    self.assertEqual(bnp._h3_reference_plate("CHAR-A", episode="E05"), head)
                with mock.patch.dict(bnp._REFERENCE_SHEET_POLICY, {"active": True}):
                    self.assertEqual(bnp._h3_reference_plate("CHAR-A", episode="E05"), sheet_png)
                    self.assertEqual(bnp._h3_reference_plate("CHAR-B", episode="E05"), head)
        self.assertEqual(bnp.unit_reference_states([{"cast": [{"character_id": "CHAR-A", "reference_state": "one_arm"}]}]),
                         {"CHAR-A": "one_arm"})


class SpeakingDurationTest(unittest.TestCase):
    def test_rule(self):
        short = speaking_duration(8, ["Holmes: Which of you is Holmes?"], "en")  # 2.01 s line
        self.assertEqual((short["duration_seconds"], short["action"]), (3.0, "SHORTENED"))
        self.assertEqual(speaking_duration(3, ["A: Which of you is Holmes?"], "en")["action"], "UNCHANGED")
        mid = speaking_duration(3, ["A: one two three four five six seven eight nine ten"], "en")  # 3.70 s
        self.assertEqual((mid["duration_seconds"], mid["action"]), (5.0, "LENGTHENED"))
        long = speaking_duration(6, ["A: He will be away all day. There would be nothing to disturb you."], "en")
        self.assertEqual((long["duration_seconds"], long["action"]), (6.0, "WRITER_SPLIT_REQUIRED_KEPT"))
        longer = speaking_duration(7.5, ["A: He will be away all day. There would be nothing to disturb you."], "en")
        self.assertEqual((longer["duration_seconds"], longer["action"]), (6.0, "WRITER_SPLIT_REQUIRED_SHORTENED"))
        self.assertEqual(speaking_duration(4, ["甲：你好。"], "zh")["duration_seconds"], 3.0)

    def test_bnp_applies_it_to_on_screen_lines_only(self):
        import build_nalu_preproduction as bnp
        shot = {"shot_id": "S1", "target_seconds": 8, "prompt_spec": {
            "dialogue": "Holmes: Which of you is Holmes?",
            "role_semantic_disambiguation": {"lip_owner_id": "CHAR-H", "dialogue_speaker_id": "CHAR-H"},
            "cast": [{"character_id": "CHAR-H"}]}}
        report: list = []
        self.assertEqual(bnp._speaking_shot_duration(shot, None, "en", 8.0, report), 3.0)
        self.assertEqual(report[0]["action"], "SHORTENED")
        offscreen = json.loads(json.dumps(shot))
        offscreen["prompt_spec"]["cast"][0]["face_visibility"] = "OFFSCREEN_VOICE_ONLY"
        self.assertEqual(bnp._speaking_shot_duration(offscreen, None, "en", 8.0, []), 8.0)
        self.assertEqual(bnp._speaking_shot_duration(shot, ("", [{"line": "vo"}]), "en", 8.0, []), 8.0)
        source = Path(bnp.__file__).read_text()
        self.assertIn("if camera_grammar:  # CAMERA_GRAMMAR_V1: a speaking shot runs line + 0.5 s", source)


class Q2AutoRedoTest(unittest.TestCase):
    ROWS = {"U1": {"speaker_framing": {"status": "FAIL"}, "media_sha256": "s1"},
            "U2": {"face_count": {"status": "FAIL"}, "media_sha256": "s2"},
            "U3": {"face_count": {"status": "PASS"}, "speaker_framing": {"status": "PASS"}},
            "U4": {"speaker_framing": {"status": "FAIL"}}}

    def test_priority_once_and_budget(self):
        plan = q2_auto_redo.plan(self.ROWS, {}, headroom=1000, unit_cost=lambda _u: 100,
                                 unit_order=["U1", "U2", "U3", "U4"])
        self.assertEqual([r["unit_id"] for r in plan["selected"]], ["U2", "U1", "U4"])
        plan = q2_auto_redo.plan(self.ROWS, {"U2": {}}, headroom=150, unit_cost=lambda _u: 100,
                                 unit_order=["U1", "U2", "U3", "U4"])
        self.assertEqual([r["unit_id"] for r in plan["selected"]], ["U1"])
        self.assertEqual({r["unit_id"]: r["reason"] for r in plan["skipped"]},
                         {"U2": "ALREADY_REDONE_ONCE", "U4": "BUDGET_HEADROOM_SHORT"})
        self.assertEqual(q2_auto_redo.plan(self.ROWS, {}, headroom=None, unit_cost=lambda _u: 1)["selected"], [])

    def _ctx(self, tmp: Path, contract: dict):
        preprod = tmp / "pre"; (preprod / "reports").mkdir(parents=True)
        (tmp / "video").mkdir()
        (tmp / "contract.json").write_text(json.dumps(contract))
        (preprod / "E04_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps(
            {"units": [{"unit_id": "E04-VU-001"}, {"unit_id": "E04-VU-002"}]}))
        (tmp / "tx.json").write_text(json.dumps({"tasks": [{"unit_id": "E04-VU-001", "duration_seconds": 5},
                                                           {"unit_id": "E04-VU-002", "duration_seconds": 4}]}))
        q2_dir = preprod / "reports" / "qa" / "q2"
        for uid, row in (("E04-VU-001", {"face_count": {"status": "FAIL"}, "media_sha256": "a"}),
                         ("E04-VU-002", {"speaker_framing": {"status": "PASS"}})):
            (q2_dir / uid).mkdir(parents=True); (q2_dir / uid / "prepare.json").write_text(json.dumps(row))
            (tmp / "video" / f"{uid}.mp4").write_bytes(b"mp4")
        checks = []
        ctx = SimpleNamespace(
            episode="E04", dry=False, run_id="RUN9", say=lambda *_a, **_k: None,
            budget_check=lambda planned, label: checks.append(label) or {"budget_verdict": {"headroom_credits": 500}},
            p=SimpleNamespace(preprod=preprod, preprod_reports=preprod / "reports", contract=tmp / "contract.json",
                              video_media=tmp / "video", q2_dir=q2_dir, video_transaction=tmp / "tx.json"))
        return ctx, checks

    def test_pipeline_parks_once_and_records(self):
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            ctx, checks = self._ctx(tmp, {"episode": "E04", "camera_grammar_policy": "CAMERA_GRAMMAR_V1"})
            with mock.patch.object(npl, "episode_video_model", lambda _e: "MiniMax-H3"):
                first = npl.s6_q2_auto_redo(ctx)
                self.assertEqual(first["status"], "PARKED_FOR_REDO")
                self.assertEqual(first["selected"][0]["cost"], 5 * 14 + 6 + 11)
                self.assertFalse((tmp / "video" / "E04-VU-001.mp4").exists())
                self.assertTrue((tmp / "video" / "_superseded_RUN9_q2_auto_redo" / "E04-VU-001.mp4").exists())
                state = json.loads((ctx.p.preprod_reports / "E04_S6_WAVE_STATE.json").read_text())
                self.assertIn("E04-VU-001", state["q2_auto_redo"])
                # the redone clip fails again: no second redo, it goes to review + default accept
                (tmp / "video" / "E04-VU-001.mp4").write_bytes(b"mp4 v2")
                second = npl.s6_q2_auto_redo(ctx)
                self.assertEqual(second["status"], "NONE_SELECTED")
                self.assertEqual(second["skipped"][0]["reason"], "ALREADY_REDONE_ONCE")
            self.assertEqual(checks, ["s6_q2_auto_redo_headroom"] * 2)

    def test_unstamped_never_redoes(self):
        with tempfile.TemporaryDirectory() as d:
            ctx, checks = self._ctx(Path(d), {"episode": "E04", "camera_grammar_policy": "LEGACY_FORCED_MOTION"})
            self.assertEqual(npl.s6_q2_auto_redo(ctx), {"status": "NOT_APPLICABLE"})
            self.assertEqual(checks, [])

    def test_s6_q2_returns_before_requesting_a_review(self):
        source = Path(npl.__file__).read_text()
        hook = source.index("auto_redo = s6_q2_auto_redo(ctx)")
        self.assertLess(source.index('prep_step = qa_run(ctx, [VIDEO_Q2, "prepare"'), hook)
        self.assertLess(hook, source.index('review_path, review = latest_submitted_review(ctx, "video_q2")'))
        self.assertIn("return stage_s6(ctx)", source)


if __name__ == "__main__":
    unittest.main()
