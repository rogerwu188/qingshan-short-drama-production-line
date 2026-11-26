"""WP3 L4 director pass + BILI_V1 engine relaxations (line owner 2026-11-23, Bilibili benchmark ep2 + ep3).

Covers: the content-hash guard (DIRECTOR_CHANGED_CONTENT), OTS listener default (kept when the writer declared one,
added when absent, never a third subject), small vs large action while speaking, one slow push-in per scene on the
writer's hardest line (TURN fallback, object-first / authored move counts), lead-in duration math, music passages,
reaction coverage (a / b / c), LEGACY byte-identity, the renderer's push clause and SOFT_PROFILE listener, push-in
compensation / S7 lock-off never undoing the authored push, the BILI_V1 locked-off floor, DP3 band + music passage,
the static design gate accepting the director's push, the BILI_V1 craft reviewer checks and the S1 hook.
Offline, no paid call."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import director_pass as dp  # noqa: E402
from tools import direction_policy_gate as dpg  # noqa: E402

A, B = "CHAR-A", "CHAR-B"
CAMERA = {"shot_scale": "MEDIUM_CLOSE_UP", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
          "motion_family": "LOCKED", "motion_direction": "NONE", "lens_intent": "hold the speaker",
          "axis_relation": "SAME_SIDE", "start_framing": "A speaks, chest up", "end_framing": "A speaks, chest up",
          "motivation": "Hold the declared beat."}


def shot(sid, scene, *, speaker=None, listener=None, line="", cast=(A,), role="", action="", seconds=4.0,
         hardest=False, extra_action=None):
    spec = {"dialogue": f"{speaker}：{line}" if line else "",
            "cast": [{"character": c, "character_id": c, "face_visibility": "FRONT_FACE_VISIBLE"} for c in cast],
            "action": {"primary_action": action, **(extra_action or {})},
            "camera_plan": dict(CAMERA), "props": [{"prop_id": "PROP-CUP"}] if sid.endswith("01") else []}
    if speaker:
        spec["role_semantic_disambiguation"] = {"dialogue_speaker_id": speaker, "dialogue_listener_id": listener or "",
                                                "entity_presence": {c: "VISIBLE_AND_IDENTITY_LOCKED" for c in cast}}
    if role:
        spec["beat_role"] = role
    if hardest:
        spec["hardest_line"] = True
    return {"shot_id": sid, "scene_id": scene, "target_seconds": seconds, "camera": "固定机位", "prompt_spec": spec}


def contract(profile="BILI_V1"):
    shots = [
        shot("E05-S01-01", "S01", cast=(A, B), action="A sets the cup down"),                      # silent two-shot
        shot("E05-S01-02", "S01", speaker=A, listener=B, line="你骗了我。", cast=(A, B), role="ATTACK",
             action="A holds the cup, turning it slowly"),                                         # B FRONT -> OTS
        shot("E05-S01-03", "S01", speaker=B, listener=A, line="我没有。", cast=(B,),
             extra_action={"lead_in_reaction_en": "B looks down at the cup, then up"}),           # A added as OTS
        shot("E05-S01-04", "S01", speaker=A, listener=B, line="那这是什么？", cast=(A,), hardest=True,
             action="A grabs the letter"),                                                          # large + push
        shot("E05-S02-01", "S02", speaker=B, listener=A, line="走吧。", cast=(B, A), role="TURN"),
        shot("E05-S02-02", "S02", cast=(A,), role="MUSIC_PASSAGE", seconds=2.5),
        shot("E05-S02-03", "S02", cast=(B,), role="MUSIC_PASSAGE", seconds=2.5),
        shot("E05-S02-04", "S02", cast=(A,), role="MUSIC_PASSAGE", seconds=2.5),
    ]
    out = {"episode": "E05", "shots": shots, "props": [{"prop_id": "PROP-CUP"}],
           "character_entities": [{"character_id": A, "canonical_name": "阿甲"}, {"character_id": B, "canonical_name": "阿乙"}]}
    if profile:
        out["craft_profile"] = profile
    return out


def by_id(c):
    return {s["shot_id"]: s for s in c["shots"]}


class ContentGuardTest(unittest.TestCase):
    def test_legacy_is_returned_untouched(self):
        c = contract(profile=None)
        before = json.dumps(c, sort_keys=True)
        out, report = dp.direct(c)
        self.assertIs(out, c)
        self.assertEqual(report["status"], "NOT_APPLICABLE")
        self.assertEqual(json.dumps(c, sort_keys=True), before)

    def test_director_never_changes_content(self):
        c = contract()
        out, report = dp.direct(c)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(dp.content_fingerprint(c), dp.content_fingerprint(out))
        self.assertEqual(out["director_pass"]["content_sha256"], dp.content_fingerprint(c))
        self.assertEqual(dp.content_failures(c, out), [])
        changed = copy.deepcopy(out)
        changed["shots"][1]["prompt_spec"]["dialogue"] = "阿甲：你骗了我们。"
        self.assertEqual(dp.content_failures(c, changed), ["DIRECTOR_CHANGED_CONTENT"])
        for mutate in (lambda x: x["shots"].reverse(),
                       lambda x: x["shots"][0]["prompt_spec"]["props"].clear(),
                       lambda x: x["shots"][2]["prompt_spec"]["action"].update(lead_in_reaction_en="smiles")):
            other = copy.deepcopy(out)
            mutate(other)
            self.assertEqual(dp.content_failures(c, other), ["DIRECTOR_CHANGED_CONTENT"])

    def test_a_pass_that_would_change_content_writes_nothing(self):
        c = contract()
        real = dp.content_fingerprint
        calls = iter(["before", "after"])
        with mock.patch.object(dp, "content_fingerprint", lambda _c: next(calls)):
            out, report = dp.direct(c)
        self.assertIs(out, c)
        self.assertEqual(report["integrity_failures"], ["DIRECTOR_CHANGED_CONTENT"])
        self.assertEqual(real(c), real(contract()))

    def test_idempotent(self):
        once, _ = dp.direct(contract())
        twice, report = dp.direct(once)
        self.assertEqual(json.dumps(once["shots"], sort_keys=True), json.dumps(twice["shots"], sort_keys=True))
        self.assertEqual(report["applied"], [])


class CoverageDefaultsTest(unittest.TestCase):
    def setUp(self):
        self.out, self.report = dp.direct(contract())
        self.s = by_id(self.out)

    def test_listener_is_over_the_shoulder(self):
        cast = {r["character_id"]: r for r in self.s["E05-S01-02"]["prompt_spec"]["cast"]}
        self.assertEqual(cast[B]["face_visibility"], dp.OTS_LISTENER)        # was a second front face
        self.assertEqual(cast[A]["face_visibility"], "FRONT_FACE_VISIBLE")    # the speaker keeps the face
        added = {r["character_id"]: r for r in self.s["E05-S01-03"]["prompt_spec"]["cast"]}
        self.assertEqual(added[A]["face_visibility"], dp.OTS_LISTENER)
        self.assertTrue(added[A]["director_added"])
        self.assertEqual(self.s["E05-S01-03"]["prompt_spec"]["role_semantic_disambiguation"]["entity_presence"][A],
                         "VISIBLE_AND_IDENTITY_LOCKED")
        self.assertIn("LISTENER_OTS_ADDED:E05-S01-03:CHAR-A", self.report["applied"])
        self.assertGreaterEqual(self.report["metrics"]["listener_in_frame_share"], dp.LISTENER_IN_FRAME_TARGET)

    def test_writer_declared_listener_framing_is_kept_and_no_third_subject(self):
        c = contract()
        c["shots"][1]["prompt_spec"]["cast"][1]["face_visibility"] = "SOFT_PROFILE"
        c["shots"][3]["prompt_spec"]["cast"].append({"character": "C", "character_id": "CHAR-C",
                                                     "face_visibility": "FRONT_FACE_VISIBLE"})
        out, _ = dp.direct(c)
        s = by_id(out)
        self.assertEqual(s["E05-S01-02"]["prompt_spec"]["cast"][1]["face_visibility"], "SOFT_PROFILE")
        self.assertEqual(s["E05-S01-02"]["prompt_spec"]["director"]["listener_framing"], "WRITER_SOFT_PROFILE")
        self.assertEqual(len(s["E05-S01-04"]["prompt_spec"]["cast"]), 2)
        self.assertEqual(s["E05-S01-04"]["prompt_spec"]["director"]["listener_framing"], "FRAME_FULL")

    def test_listener_never_added_when_not_in_the_scene(self):
        c = contract()
        for sh in c["shots"][:4]:  # B never appears in S01
            sh["prompt_spec"]["cast"] = [r for r in sh["prompt_spec"]["cast"] if r["character_id"] != B]
        c["shots"][2]["prompt_spec"]["cast"] = [{"character": A, "character_id": A, "face_visibility": "FRONT_FACE_VISIBLE"}]
        out, _ = dp.direct(c)
        self.assertEqual(by_id(out)["E05-S01-04"]["prompt_spec"]["director"]["listener_framing"], "SINGLE_PERSON_SCENE")

    def test_small_action_while_speaking_large_action_flagged(self):
        self.assertEqual(self.s["E05-S01-02"]["prompt_spec"]["director"]["speaking_action"], "SMALL_CONTINUOUS")
        self.assertEqual(self.s["E05-S01-04"]["prompt_spec"]["director"]["speaking_action"], "LARGE")
        self.assertIn("LARGE_ACTION_WHILE_SPEAKING:E05-S01-04", self.report["advisories"])
        for text in ("他嚼着薯片", "she adjusts her sunglasses", "擦泪", "counts on her fingers"):
            self.assertEqual(dp.action_class({"prompt_spec": {"action": {"primary_action": text}}}),
                             "SMALL_CONTINUOUS", text)
        for text in ("他走进门", "she shoves him", "he walks to the window"):
            self.assertEqual(dp.action_class({"prompt_spec": {"action": {"primary_action": text}}}), "LARGE", text)

    def test_lead_in_adds_time_once_within_caps(self):
        self.assertEqual(self.s["E05-S01-03"]["target_seconds"], 5.5)
        self.assertEqual(self.s["E05-S01-03"]["prompt_spec"]["director"]["lead_in_seconds_added"], 1.5)
        c = contract()
        c["shots"][2]["target_seconds"] = 11.5   # a two-person unit holds up to 12 s
        self.assertEqual(by_id(dp.direct(c)[0])["E05-S01-03"]["target_seconds"], 12.0)


class PushInTest(unittest.TestCase):
    def test_one_push_per_scene_on_the_hardest_line_else_turn(self):
        out, report = dp.direct(contract())
        s = by_id(out)
        plan = s["E05-S01-04"]["prompt_spec"]["camera_plan"]
        self.assertTrue(dp.is_push_in(plan))
        self.assertEqual((plan["motion_family"], plan["motion_direction"]), ("DOLLY", "PUSH_IN"))
        self.assertNotEqual(plan["start_framing"], plan["end_framing"])     # a moving plan (grouped_camera_contract)
        self.assertIn("动机：", s["E05-S01-04"]["camera"])
        self.assertTrue(dp.is_push_in(s["E05-S02-01"]["prompt_spec"]["camera_plan"]))   # TURN fallback
        self.assertEqual(report["metrics"]["push_ins_per_scene"], {"S01": 1, "S02": 1})
        for sid in ("E05-S01-01", "E05-S01-02", "E05-S01-03"):
            self.assertEqual(s[sid]["prompt_spec"]["camera_plan"]["motion_family"], "LOCKED")
        from tools.grouped_camera_contract import validate_camera_plan
        validate_camera_plan(plan, source_id="E05-S01-04")

    def test_object_first_or_authored_move_is_the_scenes_move(self):
        c = contract()
        # the entrance tilts up from the object to the face: that is the scene's move (WP6 object_first_of)
        c["shots"][0]["prompt_spec"]["object_first"] = {"subject": "PROP", "of": "PROP-CUP", "then": "TILT_UP"}
        c["shots"][4]["prompt_spec"]["camera_plan"].update(motion_family="PAN", motion_direction="LEFT_TO_RIGHT")
        out, report = dp.direct(c)
        self.assertEqual(report["metrics"]["push_ins_per_scene"], {})
        c = contract()
        c["shots"][1]["prompt_spec"]["hardest_line"] = True
        self.assertIn("PUSH_IN_EXTRA_MARK:S01:2", dp.direct(c)[1]["advisories"])

    def test_wp6_hints_object_first_mirror_and_insert_alternative(self):
        hints = {"object_first": [{"shot_id": "E05-S01-01", "subject": "PROP", "of": "PROP-CUP", "then": "TILT_UP",
                                   "counts_as_scene_move": True}],
                 "mirror_setups": {"S02": {"mirror_of": "S01", "shot_scale": "CLOSE_UP", "camera_side": "AXIS_B",
                                           "start_framing": "B in the doorway, chest up"}},
                 "insert_alternative_en": "foreground hands / object in sharp focus, the face soft behind",
                 "insert_max": 0}
        c = contract()
        c["shots"][5]["prompt_spec"]["beat_role"] = "INSERT"
        with mock.patch.object(dp, "ledger_hints", lambda _c: hints):
            out, report = dp.direct(c)
        s = by_id(out)
        self.assertEqual(report["metrics"]["push_ins_per_scene"], {"S02": 1})   # S01's move is the object-first
        self.assertTrue(s["E05-S01-01"]["prompt_spec"]["director"]["object_first"]["counts_as_scene_move"])
        self.assertIn("MIRROR_SETUP:E05-S02-01:S01", report["applied"])
        self.assertEqual(report["advisories"][-1][:22], "INSERT_ALTERNATIVE:1>0")
        self.assertEqual(dp.content_fingerprint(c), dp.content_fingerprint(out))
        # a writer flag WP6 does not count as a move (then INSERT) leaves the push in place
        hints["object_first"][0].update(then="INSERT", counts_as_scene_move=False)
        with mock.patch.object(dp, "ledger_hints", lambda _c: hints):
            self.assertEqual(dp.direct(contract())[1]["metrics"]["push_ins_per_scene"], {"S01": 1, "S02": 1})

    def test_static_design_gate_reads_the_push_as_authored_with_motive(self):
        import static_design_gate as g
        out, _ = dp.direct(contract())
        out.update(locked_dialogue_camera_policy="LOCKED_DIALOGUE_CAMERA_V1", locked_dialogue_writer_motive=True,
                   episode="E13")
        failures = " ".join(g.evaluate(out, dict(g.POLICY))["failures"])
        self.assertNotIn("R9_", failures)
        self.assertNotIn("R11_", failures)


class ReactionsAndMusicTest(unittest.TestCase):
    def test_coverage_a_b_c(self):
        cov = dp.reaction_coverage(dp.direct(contract())[0])
        self.assertEqual(cov["covered"]["E05-S01-02"], "B_LEAD_IN")          # B's next line opens on the reaction
        self.assertIn("E05-S02-01", cov["uncovered"])                         # TURN followed by a music passage
        c = contract()
        c["shots"][4]["prompt_spec"]["action"]["listener_reaction_en"] = "A's hand stops on the door"
        self.assertEqual(dp.reaction_coverage(c)["covered"]["E05-S02-01"], "A_IN_FRAME")
        c = contract()
        c["shots"][5]["prompt_spec"]["beat_role"] = "REACTION"
        cov = dp.reaction_coverage(c)
        self.assertEqual(cov["covered"]["E05-S02-01"], "C_DEDICATED")
        self.assertEqual(cov["misplaced_dedicated"], [])                      # after a TURN

    def test_music_passage_cap(self):
        self.assertEqual(dp.music_passages(contract())["codes"], [])
        c = contract()
        c["shots"][7]["target_seconds"] = 4.0
        self.assertEqual(dp.music_passages(c)["codes"], ["MUSIC_PASSAGE_TOO_LONG:E05-S02-02:9>8"])
        c["shots"][6]["prompt_spec"]["beat_role"] = ""
        self.assertIn("MUSIC_PASSAGES_OVER:2>1", dp.music_passages(c)["codes"])


class DirectionPolicyTest(unittest.TestCase):
    POLICY = dpg.load_policy(ROOT / "configs" / "DIRECTION_POLICY_V1.json")

    def _shots(self, roles, talk=2):
        out = [{"shot_id": f"S{i}", "scene_id": "SC1", "target_seconds": 2.5,
                "prompt_spec": {"dialogue": "甲：台词" if i < talk else "", "camera_plan": {"shot_scale": "MEDIUM_CLOSE_UP"},
                                "beat_role": roles[i] if i < len(roles) else ""}} for i in range(talk + 3)]
        return out

    def test_dialogue_ratio_is_a_band_and_one_music_passage_is_allowed(self):
        shots = self._shots(["", "", "MUSIC_PASSAGE", "MUSIC_PASSAGE", "MUSIC_PASSAGE"])
        legacy = dpg.evaluate({"episode": "E09", "shots": shots}, self.POLICY)
        self.assertTrue(any(f.startswith("DP3_DIALOGUE_TIME_RATIO_") for f in legacy["failures"]))
        self.assertTrue(any(f.startswith("DP3_SILENCE_RUN_OVER_3S") for f in legacy["failures"]))
        for c, profile in (({"episode": "E09", "shots": shots, "craft_profile": "BILI_V1"}, None),
                           ({"episode": "E09", "shots": shots}, "BILI_V1")):
            bili = dpg.evaluate(c, self.POLICY, profile)
            self.assertEqual([f for f in bili["failures"] if f.startswith("DP3")], [])
            dp3 = bili["measurements"]["DP3"]
            self.assertEqual(dp3["dialogue_time_ratio_band"], [0.5, 0.75])
            self.assertFalse(dp3["dialogue_time_ratio_in_band"])          # 0.4: reported, never a failure
            self.assertEqual(dp3["music_passages"][0]["seconds"], 7.5)

    def test_silence_cap_is_four_seconds_outside_a_music_passage(self):
        shots = self._shots([])  # three silent shots, 7.5 s, no reason
        bili = dpg.evaluate({"episode": "E09", "shots": shots}, self.POLICY, "BILI_V1")
        self.assertTrue(any(f.startswith("DP3_SILENCE_RUN_OVER_4S") for f in bili["failures"]))
        shots = self._shots(["", "", "MUSIC_PASSAGE", "MUSIC_PASSAGE", "MUSIC_PASSAGE"]) + \
            [dict(s, shot_id=f"T{s['shot_id']}") for s in self._shots(["", "", "MUSIC_PASSAGE", "MUSIC_PASSAGE"])]
        for s in shots[5:]:
            s["prompt_spec"] = dict(s["prompt_spec"])
        bili = dpg.evaluate({"episode": "E09", "shots": shots}, self.POLICY, "BILI_V1")
        self.assertIn("DP3_MUSIC_PASSAGES_2_OVER_1", bili["failures"])


class CameraRelaxationTest(unittest.TestCase):
    def test_renderer_v1_push_clause_and_legacy_unchanged(self):
        from tools import h3_provider_prompt_renderer as r
        plan = {"motion_family": "DOLLY", "motion_direction": "PUSH_IN", "shot_scale": "MEDIUM_CLOSE_UP",
                "camera_policy": "LOCKED_DIALOGUE_CAMERA_V1"}
        plain = r._camera(plan)
        self.assertNotIn("about 10 %", plain)
        pushed = r._camera({**plan, "bili_slow_push_in": True})
        self.assertIn("slow, steady push-in toward the speaker, about 10 % closer", pushed)
        self.assertNotIn("one short dolly move", pushed)

    def test_renderer_v2_push_line(self):
        from tools import h3_director_prompt_v2 as v2
        plan = {**CAMERA, "motion_family": "DOLLY", "motion_direction": "PUSH_IN", "bili_slow_push_in": True}
        text = v2._camera_entry(plan, {})
        self.assertIn("One slow, steady push-in toward the speaker, about 10 % closer", text)
        self.assertNotIn("One short dolly move", text)
        self.assertIn("One short dolly move", v2._camera_entry({**plan, "bili_slow_push_in": False}, {}))

    def test_push_in_compensation_and_s7_lockoff_never_undo_the_push(self):
        from tools import push_in_compensation as pic
        locked = {"unit_id": "U1", "camera_plan": {"motion_family": "LOCKED"}}
        pushed = {"unit_id": "U2", "camera_plan": {"motion_family": "LOCKED", "bili_slow_push_in": True}}
        self.assertTrue(pic.locked_camera_unit(locked))
        self.assertFalse(pic.locked_camera_unit(pushed))
        import nalu_pipeline as npl
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "grouping.json"
            path.write_text(json.dumps({"units": [locked, pushed,
                                                  {"unit_id": "U3", "per_shot_camera_plans": [
                                                      {"camera_plan": {"bili_slow_push_in": True}}]}]}))
            self.assertEqual(npl.s7_authored_push_in_units(path), {"U2", "U3"})
            self.assertEqual(npl.s7_authored_push_in_units(Path(d) / "missing.json"), set())

    def test_locked_off_floor_is_lower_only_under_bili_v1(self):
        import camera_motion_metrics as cmm
        self.assertEqual(cmm.locked_off_share_min({"craft_profile": "BILI_V1"}), 0.55)
        self.assertEqual(cmm.locked_off_share_min({}), 0.70)
        rows = [{"camera_class": "LOCKED_OFF", "locked_off": i < 6, "unstable": False} for i in range(10)]
        self.assertEqual(cmm.summary_counts(rows)["status"], "FAIL")
        self.assertEqual(cmm.summary_counts(rows)["targets"]["locked_off_share_min"], 0.70)
        self.assertEqual(cmm.summary_counts(rows, 0.55)["status"], "PASS")

    def test_soft_profile_listener_clause(self):
        from tools import h3_provider_prompt_renderer as r
        self.assertEqual(r.partial_visibility_part("SOFT_PROFILE"), r.SOFT_PROFILE_PART)
        self.assertIn("seen in profile and slightly out of focus", r.partial_clause("Beta", r.SOFT_PROFILE_PART))
        self.assertIn("mouth stays closed", r.partial_clause("Beta", r.SOFT_PROFILE_PART))


class CraftStandardProfileTest(unittest.TestCase):
    def test_bili_v1_reviewer_checks_only_for_bili_v1(self):
        import nalu_craft_standard as craft
        legacy = craft.reviewer_request({}, ROOT)
        same = craft.reviewer_request({}, ROOT, profile="LEGACY")
        self.assertEqual(json.dumps(legacy, sort_keys=True), json.dumps(same, sort_keys=True))
        bili = craft.reviewer_request({}, ROOT, profile="BILI_V1")
        checks = {row["id"]: row["check"] for row in bili["items"]}
        old = {row["id"]: row["check"] for row in legacy["items"]}
        self.assertIn("过肩背影或虚焦侧脸的听者不算问题", checks["C-07"])
        self.assertIn("双人同框、一人说话", old["C-07"])
        self.assertIn("持续小动作不算问题", checks["C-03"])
        self.assertEqual(checks["S-01"], old["S-01"])


class LegacyByteIdentityTest(unittest.TestCase):
    """LEGACY series stay byte-identical (golden sha256 computed on origin/main 4103b32, before WP3)."""

    # render_v1/v2 re-pinned 2026-11-25 ("AI face" prompt fix: texture + character-count negatives, no look text in
    # stamped H3 prompts); render_v2 re-pinned 2026-11-26 (E28 burned dialogue: clean-picture line closes Setting);
    # the pacing / direction-policy goldens are unchanged
    GOLDEN = {
        "render_v2": "7c56dfeb19f4d85b2be53abfb57be98d4295c5804e25d3d363818e7e276df134",
        "render_v1": "89c204a6cc204e7e620e7aa283f505ecc38771c57eac76c893e9b1b5ecdb931c",
        "pace_slow": "47e90e1b7ed68fbcaed51428ae083c7b66d7c7ae849d89b9aaca4b2bdf72aa7a",
        "dpg_slow": "a7c6df758eea676a7bee201349e63afcb98e4a742c69e354c4e00888db8690b8",
        "pace_punchy": "ba4b0982db328d7ba73d03ffe7089b8b81fd8b800593d055e6d4e70c10fcd5a0",
        "dpg_punchy": "ddad38358ff4b9d61ea1e5ea65afd42ec7bf479de0e4b722a9fc78cb0594d880",
    }

    @staticmethod
    def _sha(value):
        import hashlib
        text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def test_rendered_h3_prompts(self):
        from tools.h3_provider_prompt_renderer import render_h3_prompt
        from tools.tests.test_h3_director_prompt_v2 import fixture
        unit, plan = fixture()
        self.assertEqual(self._sha(render_h3_prompt(unit, plan)[0]), self.GOLDEN["render_v2"])
        unit, plan = fixture()
        unit.pop("h3_prompt_style", None)
        plan.pop("h3_prompt_style", None)
        self.assertEqual(self._sha(render_h3_prompt(unit, plan)[0]), self.GOLDEN["render_v1"])

    def test_s1_pacing_and_direction_policy_reports(self):
        import script_pacing_check as sp
        from tools.tests.test_nalu_script_pacing import punchy_contract, slow_contract
        policy = dpg.load_policy(ROOT / "configs" / "DIRECTION_POLICY_V1.json")
        for name, c in (("slow", slow_contract("zh")), ("punchy", punchy_contract("en"))):
            self.assertEqual(self._sha(sp.evaluate(c)), self.GOLDEN[f"pace_{name}"], name)
            self.assertEqual(self._sha(dpg.evaluate(c, policy)), self.GOLDEN[f"dpg_{name}"], name)
            self.assertEqual(self._sha(dpg.evaluate(c, policy, "LEGACY")), self.GOLDEN[f"dpg_{name}"], name)


FIXTURE_E25 = ROOT / "tools" / "tests" / "fixtures" / "director_pass" / "E25_SCREENPLAY_V1_CONTRACT.json"


class ScreenplayE25Test(unittest.TestCase):
    """The approved E25 妖皇宫 rewrite as WP2 (PR #331) compiles it (62 s / 15 shots, a frozen copy so this PR stands
    alone): under BILI_V1 its authored business counts as visual action and its reactions are covered."""

    def setUp(self):
        self.c = json.loads(FIXTURE_E25.read_text(encoding="utf-8"))

    def test_pacing_passes_under_bili_v1_and_legacy_is_unchanged(self):
        import script_pacing_check as sp
        directed, report = dp.direct(self.c)
        self.assertEqual(report["status"], "PASS")
        r = sp.evaluate(directed, "zh")
        # ADAPTATION_TOO_THIN is WP1's (it deletes the event floor under BILI_V1); nothing else may fail
        self.assertEqual([f for f in r["failures"] if not f.startswith("ADAPTATION_TOO_THIN")], [])
        self.assertLessEqual(r["metrics"]["dialogue_only_ratio"], 0.6)
        self.assertGreaterEqual(r["metrics"]["visual_action_ratio"], 0.3)
        self.assertEqual(r["metrics"]["reaction_coverage"]["uncovered"], [])
        legacy = dict(self.c, craft_profile="LEGACY")
        self.assertTrue(any(f.startswith("DIALOGUE_ONLY_TOO_HIGH") for f in sp.evaluate(legacy, "zh")["failures"]))

    def test_director_on_the_fixture(self):
        directed, report = dp.direct(self.c)
        self.assertIn("PUSH_IN_ADOPTED:E25-S01-11", report["applied"])   # the compiler's push on the turn, kept
        cuts = [a for a in report["applied"] if a.startswith("AUTHORED_CUT:")]
        self.assertEqual(cuts[0], "AUTHORED_CUT:E25-S01-11:MOTIVATED_CUT")  # the turn first
        self.assertEqual(len(cuts), dp.AUTHORED_CUT_MAX)
        self.assertEqual(by_id(directed)["E25-S01-11"]["incoming_transition_mode"], "MOTIVATED_CUT")
        self.assertEqual(dp.content_fingerprint(self.c), dp.content_fingerprint(directed))
        listener = {r["character_id"]: r["face_visibility"] for r in by_id(directed)["E25-S01-10"]["prompt_spec"]["cast"]}
        self.assertEqual(listener["CHAR-SHANGYUJIN"], "THREE_QUARTER_BUST")   # writer's framing kept

    def test_bili_action_lexicon(self):
        import script_pacing_check as sp

        def spoken(text, **action):
            return {"prompt_spec": {"dialogue": "甲：嗯。", "action": {"primary_action": text, **action},
                                    "cast": [{"character_id": "A"}]}}
        for text in ("白桃停下令牌，嗒地磕在扶手上。", "她把令牌亮出来。", "他把她的手按下。", "拍了两下手背。",
                     "机の上に置いた。", "잔을 내려놓는다.", "He taps the token on the armrest."):
            self.assertEqual(sp.shot_kind(spoken(text), True, bili=True), "TALK_WITH_ACTION", text)
            self.assertEqual(sp.shot_kind(spoken(text), True), "TALKING_HEAD", text)   # LEGACY lexicon unchanged
        self.assertEqual(sp.shot_kind(spoken("甲对乙说出「嗯」", source="fallback"), True, bili=True), "TALKING_HEAD")
        touch = spoken("说着", interaction_mode="CONTACT", subject_id="A", target_entity_id="B")
        self.assertEqual(sp.shot_kind(touch, True, bili=True), "TALK_WITH_ACTION")


class AuthoredCutTest(unittest.TestCase):
    def test_turn_first_capped_and_writer_cuts_count(self):
        c = contract()
        for sid, role in (("E05-S01-03", "REVEAL"), ("E05-S01-04", "PAYOFF")):
            by_id(c)[sid]["prompt_spec"]["beat_role"] = role
        out, report = dp.direct(c)
        cuts = [a for a in report["applied"] if a.startswith("AUTHORED_CUT:")]
        self.assertEqual(cuts, ["AUTHORED_CUT:E05-S01-03:REACTION_CUT", "AUTHORED_CUT:E05-S01-02:REACTION_CUT",
                                "AUTHORED_CUT:E05-S01-04:REACTION_CUT"])
        c = contract()
        c["shots"][2]["incoming_transition_mode"] = "HARD_CUT"
        c["shots"][3]["incoming_transition_mode"] = "HARD_CUT"
        c["shots"][1]["incoming_transition_mode"] = "MATCH_CUT"
        out, report = dp.direct(c)
        self.assertFalse([a for a in report["applied"] if a.startswith("AUTHORED_CUT:")])


class H3MinUnitKnobTest(unittest.TestCase):
    def test_provider_minimum_two_and_the_legacy_floor_stays_four(self):
        from tools import h3_limits
        from tools import hopsapi_video_client as hv
        from tools import speaking_unit_duration as sud
        from tools import build_video_unit_grouping_spec as grouping
        missing = Path("/nonexistent/H3_LIMITS_V1.json")
        self.assertEqual(h3_limits.min_unit_seconds({}, config_path=missing), 4)
        self.assertEqual(h3_limits.min_unit_seconds({}), 2)                  # shipped config (2 s live probe passed)
        self.assertEqual(h3_limits.unit_floor_seconds({}), 4)                 # LEGACY grouping / speaking floor
        self.assertEqual(h3_limits.unit_floor_seconds({"NALU_H3_MIN_UNIT_SECONDS": "2"}), 4)
        self.assertEqual(h3_limits.unit_floor_seconds({"NALU_H3_UNIT_FLOOR_SECONDS": "2",
                                                       "NALU_H3_MIN_UNIT_SECONDS": "2"}), 2)
        self.assertEqual(h3_limits.unit_floor_seconds({"NALU_H3_UNIT_FLOOR_SECONDS": "2",
                                                       "NALU_H3_MIN_UNIT_SECONDS": "4"}), 4)   # never below min
        self.assertEqual(h3_limits.min_unit_seconds({"NALU_H3_MIN_UNIT_SECONDS": "4"}), 4)
        self.assertEqual(h3_limits.min_unit_seconds({"NALU_H3_MIN_UNIT_SECONDS": "1"}, config_path=missing), 4)
        self.assertEqual(h3_limits.min_unit_seconds({"NALU_H3_MIN_UNIT_SECONDS": "abc"}, config_path=missing), 4)
        with tempfile.TemporaryDirectory() as d:
            two = Path(d) / "H3_LIMITS_V1.json"
            two.write_text(json.dumps({"min_unit_seconds": 2}), encoding="utf-8")
            self.assertEqual(h3_limits.min_unit_seconds({}, config_path=two), 2)
            self.assertEqual(h3_limits.unit_floor_seconds({}, config_path=two), 4)
        for floor in (4, 2):
            with mock.patch.dict(os.environ, {"NALU_H3_MIN_UNIT_SECONDS": str(floor)}):
                os.environ.pop("NALU_H3_UNIT_FLOOR_SECONDS", None)
                self.assertEqual(hv.min_duration_seconds(), floor)
                # grouping / speaking units keep the 4 s floor either way (no 2 s talking units)
                self.assertEqual(grouping.provider_min_seconds("MiniMax-H3"), 4.0)
                self.assertEqual(sud.group_duration(["你好"], "zh")["duration_seconds"], 4.0)
                self.assertEqual(dp.unit_min_seconds(), floor)
                self.assertEqual(dp.dedicated_reaction_max(), 3 if floor == 4 else 6)
                self.assertEqual(hv.estimated_task_credits(2, resolution="480p"),
                                 hv.estimated_task_credits(floor, resolution="480p"))
                if floor == 4:
                    with self.assertRaises(ValueError):
                        hv.build_omni_request(prompt="x", image_urls=["u"], audio_urls=[], duration=2, resolution="480p")
                else:
                    self.assertEqual(hv.build_omni_request(prompt="x", image_urls=["u"], audio_urls=[], duration=2,
                                                           resolution="480p")["input"]["duration"], 2)

    def test_short_dedicated_units_only_at_two_seconds(self):
        c = contract()
        c["shots"][5]["prompt_spec"]["beat_role"] = "REACTION"
        c["shots"][5]["target_seconds"] = 4.0
        with mock.patch.dict(os.environ, {"NALU_H3_MIN_UNIT_SECONDS": "2"}):
            out, report = dp.direct(c)
            self.assertIn("SHORT_UNIT:E05-S02-02:4->2", report["applied"])
            self.assertEqual(by_id(out)["E05-S02-02"]["target_seconds"], 2.0)
            self.assertEqual(dp.reaction_coverage(out)["dedicated_max"], 6)
        with mock.patch.dict(os.environ, {"NALU_H3_MIN_UNIT_SECONDS": "4"}):
            out, report = dp.direct(c)
        self.assertFalse([a for a in report["applied"] if a.startswith("SHORT_UNIT")])
        self.assertEqual(by_id(out)["E05-S02-02"]["target_seconds"], 4.0)

    def test_only_director_short_units_are_requested_below_the_floor(self):
        from tools import build_video_unit_grouping_spec as grouping
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lines" / "nalu" / "runtime" / "tools"))
        import build_nalu_preproduction as bnp
        silent = {"shot_id": "X-01", "prompt_spec": {"dialogue": "", "cast": []},
                  "director_short_unit": {"seconds": 2.0}}
        talking = {"shot_id": "X-02", "prompt_spec": {"dialogue": "你好", "cast": [
            {"character_id": "A", "face_visibility": "FRONT_FACE_VISIBLE"}]}, "director_short_unit": {"seconds": 2.0}}
        plain = {"shot_id": "X-03", "prompt_spec": {"dialogue": "", "cast": []}}
        with mock.patch.dict(os.environ, {"NALU_H3_MIN_UNIT_SECONDS": "2"}):
            self.assertEqual(grouping.short_unit_minimum([silent]), 2.0)
            self.assertIsNone(grouping.short_unit_minimum([plain]))
            self.assertIsNone(grouping.short_unit_minimum([silent, plain]))   # grouped: the unit floor applies
            self.assertIsNone(grouping.short_unit_minimum([talking]))
        with mock.patch.dict(os.environ, {"NALU_H3_MIN_UNIT_SECONDS": "4"}):
            self.assertIsNone(grouping.short_unit_minimum([silent]))
        plan = {"duration_policy_seconds": {"minimum": 4.0}, "runtime_seconds": 4.0, "units": [
            {"unit_id": "U1", "duration_seconds": 2.0, "duration_exception_reason": "PROVIDER_MINIMUM_PADDED",
             "provider_minimum_seconds": 2.0},
            {"unit_id": "U2", "duration_seconds": 2.0, "duration_exception_reason": "PROVIDER_MINIMUM_PADDED"}]}
        slots = [u["duration_seconds"] for u in bnp.project_provider_slots(plan)["units"]]
        self.assertEqual(slots, [2, 4])


class DigitalPushTest(unittest.TestCase):
    """WP3 lab 2026-11-24 (unit iv): H3 ignored "slow push-in about 10 %" -> S7 realises it as a digital push."""

    @staticmethod
    def faces(growth, n=9, end=4.0):
        return [{"t": end * i / (n - 1), "width": 0.16 * (1 + growth * i / (n - 1)), "cx": 0.6, "cy": 0.25}
                for i in range(n)]

    def test_plan_eases_from_one_to_the_target_on_the_face(self):
        from tools import push_in_compensation as pic
        plan = pic.digital_push_plan([], (0.5, 4.5))
        crops = [p["crop"] for p in plan["curve"]]
        self.assertEqual((crops[0], crops[-1]), (1.0, pic.DIGITAL_PUSH_ZOOM))
        self.assertAlmostEqual(crops[len(crops) // 2], 1.05, places=3)            # smoothstep midpoint
        self.assertLess(crops[1] - crops[0], crops[len(crops) // 2] - crops[len(crops) // 2 - 1])   # eases in
        self.assertEqual(plan["centre_source"], "DEFAULT")
        self.assertEqual(pic.crop_window(0.0, plan, 768, 1344)[0], 1.0)            # before the span: untouched
        c, x0, y0 = pic.crop_window(4.5, plan, 768, 1344)
        self.assertAlmostEqual(c, 1.10)
        self.assertAlmostEqual(x0 + 0.5 * 768 / c, 0.5 * 768)                     # the centre stays put
        on_face = pic.digital_push_plan(self.faces(0.0), (0.0, 4.0))
        self.assertEqual((on_face["anchor"]["cx"], on_face["zoom"]), (0.6, 1.10))
        topped = pic.digital_push_plan(self.faces(0.086), (0.0, 4.0))             # H3 already drifted in 8.6 %
        self.assertEqual(topped["zoom"], pic.DIGITAL_PUSH_MIN_ZOOM)
        self.assertAlmostEqual(pic.digital_push_plan(self.faces(0.03), (0.0, 4.0))["zoom"], round(1.10 / 1.03, 4))

    def test_report_applies_only_marked_units_and_legacy_report_is_unchanged(self):
        from tools import push_in_compensation as pic
        clips = {"U1": Path("u1.mp4"), "U2": Path("u2.mp4")}
        windows = {"U1": (0.0, 4.0), "U2": (0.0, 4.0)}
        legacy = {"units": [{"unit_id": "U1", "camera_plan": {"motion_family": "DOLLY"}},
                            {"unit_id": "U2", "camera_plan": {"motion_family": "DOLLY"}}]}

        def render(clip, out, plan):
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(json.dumps(plan["curve"][-1]).encode())
            return {"frames": 1}
        with tempfile.TemporaryDirectory() as d, mock.patch.object(pic, "sha256_file", lambda _p: "sha"):
            report = pic.build_report("E01", legacy, clips, windows, Path(d), measure_fn=lambda *_: [],
                                      render_fn=render)
            self.assertNotIn("digital_push_units", report)
            self.assertEqual({r["status"] for r in report["units"].values()}, {"SKIPPED_MOVING_CAMERA"})
            marked = json.loads(json.dumps(legacy))
            marked["units"][1]["camera_plan"]["bili_slow_push_in"] = True
            report = pic.build_report("E01", marked, clips, windows, Path(d), measure_fn=lambda *_: [],
                                      render_fn=render)
            self.assertEqual(report["digital_push_units"], ["U2"])
            self.assertEqual(report["compensated_units"], ["U2"])                  # handed to the AgentCut build
            self.assertEqual(report["units"]["U2"]["kind"], pic.DIGITAL_PUSH_KIND)

    def test_render_on_a_real_clip(self):
        import shutil
        import subprocess
        if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
            self.skipTest("ffmpeg not installed")
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("OpenCV not installed")
        from tools import push_in_compensation as pic
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "U1.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=144x256:rate=24:duration=2",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-pix_fmt",
                            "yuv420p", "-c:a", "aac", "-shortest", str(src)], check=True)
            out = Path(d) / "out" / "U1.mp4"
            info = pic.render(src, out, pic.digital_push_plan([], (0.0, 2.0)))
            self.assertTrue(info["audio_bit_exact"])
            self.assertEqual(pic.probe(out)["frames"], pic.probe(src)["frames"])

    def test_s7_step_runs_for_bili_v1_outside_camera_grammar(self):
        import nalu_pipeline as npl
        import push_in_compensation as flat_pic
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "video").mkdir()
            (d / "assembly").mkdir()
            (d / "video" / "E05-VU-001.mp4").write_bytes(b"clip")
            (d / "video" / "E05-VU-002.mp4").write_bytes(b"clip")
            (d / "grouping.json").write_text(json.dumps({"units": [
                {"unit_id": "E05-VU-001", "camera_plan": {"motion_family": "LOCKED"}},
                {"unit_id": "E05-VU-002", "camera_plan": {"motion_family": "DOLLY", "bili_slow_push_in": True}}]}))
            p = SimpleNamespace(video_media=d / "video", assembly=d / "assembly", grouping_plan=d / "grouping.json")

            def render(clip, out, plan, **_k):
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(b"pushed")
                return {"frames": 1}
            for profile, expect in (("LEGACY", None), ("BILI_V1", ["E05-VU-002"])):
                ctx = SimpleNamespace(episode="E05", p=p, craft_profile=profile, render_style="anime")
                res = npl.StageResult(npl.PASS)
                with mock.patch.object(flat_pic, "render", render), \
                        mock.patch.object(flat_pic, "face_backend", side_effect=AssertionError("no faces for anime")), \
                        mock.patch.object(npl, "_probe_seconds", return_value=4.0):
                    path = npl.s7_push_in_compensation(ctx, res, {"episode": "E05"})
                if expect is None:
                    self.assertIsNone(path)
                    continue
                report = json.loads(path.read_text())
                self.assertEqual(report["digital_push_units"], expect)
                self.assertEqual(report["units"]["E05-VU-001"]["status"], "SKIPPED_MOVING_CAMERA")  # no compensation


class PostureHoldTest(unittest.TestCase):
    def test_bili_v1_units_keep_the_first_frame_posture_unless_the_beats_change_it(self):
        from tools import h3_provider_prompt_renderer as r
        from tools.tests.test_h3_director_prompt_v2 import fixture
        unit, plan = fixture()
        legacy = r.render_h3_prompt(unit, plan)[0]
        self.assertNotIn(r.POSTURE_HOLD, legacy)
        unit, plan = fixture()
        unit["craft_profile"] = "BILI_V1"
        self.assertIn(r.POSTURE_HOLD, r.render_h3_prompt(unit, plan)[0])
        self.assertEqual(r.posture_hold_sentence(["Alpha stands up and walks to the door"]), "")
        self.assertEqual(r.posture_hold_sentence(["Alpha leans forward and points at the contract"]), r.POSTURE_HOLD)


class PipelineHookTest(unittest.TestCase):
    def _run(self, c, profile):
        import nalu_pipeline as npl
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            path = d / "E05_GENERATION_CONTRACT_v1.json"
            raw = json.dumps(c, ensure_ascii=False)
            path.write_text(raw, encoding="utf-8")
            (d / "logs").mkdir()
            ctx = SimpleNamespace(episode="E05", run_id="r1", craft_profile=profile)
            p = SimpleNamespace(contract=path, logs=d / "logs")
            with mock.patch.object(npl, "s1_pacing_in_flight", lambda _p: False):
                row, blockers = npl.s1_director_pass(ctx, p)
            return row, blockers, path.read_text(encoding="utf-8") == raw, json.loads(path.read_text()), \
                path.with_name(path.stem + ".pre_director.json").exists()

    def test_legacy_reads_and_writes_nothing(self):
        row, blockers, same, _, backup = self._run(contract(profile=None), "LEGACY")
        self.assertIsNone(row)
        self.assertEqual(blockers, [])
        self.assertTrue(same)
        self.assertFalse(backup)

    def test_bili_v1_directs_the_contract_before_s1_hashes_it(self):
        row, blockers, same, after, backup = self._run(contract(profile=None), "BILI_V1")
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(blockers, [])
        self.assertFalse(same)
        self.assertTrue(backup)
        self.assertEqual(after["craft_profile"], "BILI_V1")
        self.assertIn("director_pass", after)

    def test_content_change_is_an_integrity_blocker(self):
        calls = iter(["before", "after"])
        with mock.patch.object(dp, "content_fingerprint", lambda _c: next(calls)):
            row, blockers, same, _, backup = self._run(contract(), "BILI_V1")
        self.assertEqual(blockers, ["SCRIPT_INTEGRITY_FAIL:DIRECTOR_CHANGED_CONTENT"])
        self.assertTrue(same)
        self.assertFalse(backup)


if __name__ == "__main__":
    unittest.main()
