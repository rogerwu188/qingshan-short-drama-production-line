"""S1 structural integrity gates (device 1101 E24 review, 2026-11-23).

E24 was a 56 s episode from a degenerate script: 22 one-person CU/MCU locked singles in one location, a framing /
ambience / axis template on every shot, transition rows copied from E18, listener ids nobody defined, two-person
actions with one-person casts, 62 s planned against a 110 s brief -- and S1 admitted it after two pacing rounds.
Every rule here is an INTEGRITY blocker (returned to the writer, free, outside the admit-after-2 taste loop), tested
offline on E24-like synthetic contracts next to a valid contract that must keep passing.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "skills" / "nalu-claude-code" / "scripts",
           ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import script_pacing_check as sp  # noqa: E402
from tools import character_entity_contract as cec  # noqa: E402
from tools import direction_policy_gate as dpg  # noqa: E402
from tools import script_structure_contract_gate as ssg  # noqa: E402
from tools import writer_capability as wc  # noqa: E402

CHARS = [("CHAR-LINGYAO", "凌瑶", "Lingyao"), ("CHAR-WANGDEFA", "王德发", "Wang Defa"),
         ("CHAR-MENGZIQIU", "孟子秋", "Meng Ziqiu")]
NAME = {cid: en for cid, _, en in CHARS}
ZH = {cid: zh for cid, zh, _ in CHARS}


def shot(sid: str, scene: str, cast: list[str], action: str, *, line: str = "", scale: str = "MEDIUM",
         ambience: str = "", location: str = "LOC-TEAHOUSE", seconds: float = 5.0, target: str = "",
         mode: str = "NONE", faces: dict[str, str] | None = None) -> dict:
    subject = cast[0] if cast else ""
    faces = faces or {}
    return {
        "shot_id": sid, "scene_id": scene, "location_id": location, "target_seconds": seconds,
        "entry_state": f"{NAME.get(subject, 'Someone')} starts the beat.",
        "completion_state": action,
        "prompt_spec": {
            "cast": [{"character": ZH[c], "character_id": c, "life_state": "alive",
                      "face_visibility": faces.get(c, "FRONT_FACE_VISIBLE")} for c in cast],
            "dialogue": f"{ZH[subject]}：{line}" if line else "",
            "action": {"subject_id": subject, "initiator_entity_id": subject, "target_entity_id": target or subject,
                       "primary_action": action, "interaction_mode": mode},
            "camera_plan": {"shot_scale": scale, "motion_family": "LOCKED",
                            "start_framing": f"{NAME.get(subject, '')} framed for {sid}."},
            "role_semantic_disambiguation": {
                "primary_actor": ZH.get(subject, ""), "primary_actor_id": subject, "primary_actor_kind": "CHARACTER",
                "dialogue_speaker": ZH[subject] if line else "", "dialogue_speaker_id": subject if line else "",
                "dialogue_listener": "", "dialogue_listener_id": "",
                "lip_owner_id": subject if line else "",
                "entity_states": {}, "entity_presence": {c: "VISIBLE_AND_IDENTITY_LOCKED" for c in cast}},
            "sound": {"ambience": ambience or f"Room tone of {scene}."},
        },
    }


def base_contract(shots: list[dict], **extra) -> dict:
    scenes = sorted({s["scene_id"] for s in shots})
    contract = {
        "schema": "qingshan.generation_contract.v3", "episode": "E24",
        "visual_culture_contract": {"schema": "qingshan.visual_culture_contract.v1", "status": "LOCKED",
                                    "profile_id": "P", "decision_owner": "WRITER_DIRECTOR",
                                    "decision_basis": "b", "source_ref": "ch0021"},
        "character_entities": [{"character_id": c, "canonical_name": z, "aliases": []} for c, z, _ in CHARS],
        "scene_states": [{"scene_id": sc, "location_id": "LOC-TEAHOUSE", "time_id": "DAY"} for sc in scenes],
        "shots": shots,
        "audio_contract": {"dialogue_units": []},
    }
    contract.update(extra)
    return contract


def valid_contract() -> dict:
    """A small, structurally whole episode: two scenes in two places, two-person shots, per-scene ambience."""
    shots = [
        shot("E24-S01-01", "E24-S01", ["CHAR-LINGYAO", "CHAR-WANGDEFA"],
             "Lingyao presses a dagger to Wang Defa's throat.", scale="MEDIUM", ambience="Teahouse chatter."),
        shot("E24-S01-02", "E24-S01", ["CHAR-WANGDEFA", "CHAR-LINGYAO"], "Wang Defa raises both hands.",
             line="女侠饶命！", scale="MEDIUM_CLOSE_UP", ambience="Teahouse chatter.",
             faces={"CHAR-LINGYAO": "BACK_AND_SHOULDERS_ONLY"}),
        shot("E24-S01-03", "E24-S01", ["CHAR-LINGYAO"], "Lingyao lowers the dagger, eyes on Wang Defa offscreen.",
             line="三天之内。", scale="CLOSE_UP", ambience="Teahouse chatter."),
        shot("E24-S02-01", "E24-S02", ["CHAR-MENGZIQIU", "CHAR-LINGYAO"],
             "Meng Ziqiu pulls Lingyao toward the boat.", scale="MEDIUM", location="LOC-PIER",
             ambience="Water lapping at the pier."),
        shot("E24-S02-02", "E24-S02", ["CHAR-LINGYAO", "CHAR-MENGZIQIU"], "Lingyao kneels beside the skeleton.",
             scale="MEDIUM_WIDE", location="LOC-PIER", ambience="Water lapping at the pier."),
    ]
    c = base_contract(shots)
    c["scene_states"][1]["location_id"] = "LOC-PIER"
    c["audio_contract"]["dialogue_units"] = [
        {"shot_id": "E24-S01-02", "speaker_id": "CHAR-WANGDEFA", "listener_id": "CHAR-LINGYAO", "text": "女侠饶命！"}]
    return c


def e24_like() -> dict:
    """The degenerate pattern: one-person CU/MCU singles, one location, one template, undefined ids."""
    amb = "Bamboo wind and field insects; no unassigned voices."
    shots = [
        shot("E24-S01-01", "E24-S01", ["CHAR-LINGYAO"], "Lingyao presses a dagger to Wang Defa throat.",
             line="你说认识龙夜澈？", scale="CLOSE_UP", ambience=amb, seconds=4),
        shot("E24-S01-02", "E24-S01", ["CHAR-WANGDEFA"], "Wang Defa raises both hands and backs away.",
             line="女侠饶命！", scale="MEDIUM_CLOSE_UP", ambience=amb, seconds=4),
        shot("E24-S02-01", "E24-S02", ["CHAR-MENGZIQIU"], "Meng Ziqiu places the handkerchief by the box.",
             scale="CLOSE_UP", ambience=amb, seconds=2),
        shot("E24-S02-02", "E24-S02", ["CHAR-LINGYAO"], "Lingyao pulls the ledger toward herself.",
             line="账本给我。", scale="CLOSE_UP", ambience=amb, seconds=4),
        shot("E24-S03-01", "E24-S03", ["CHAR-LINGYAO"], "Lingyao looks down at a skeleton on a fishing boat.",
             scale="CLOSE_UP", ambience=amb, seconds=2),
        shot("E24-S03-02", "E24-S03", ["CHAR-MENGZIQIU"], "Meng Ziqiu pulls Lingyao away from the crowd.",
             scale="MEDIUM_CLOSE_UP", ambience=amb, seconds=2),
        shot("E24-S04-01", "E24-S04", ["CHAR-MENGZIQIU"], "Meng Ziqiu leads the captive into the street.",
             scale="MEDIUM_CLOSE_UP", ambience=amb, seconds=2),
        shot("E24-S04-02", "E24-S04", ["CHAR-LINGYAO"], "Lingyao raises one finger.", line="谁能证明？",
             scale="CLOSE_UP", ambience=amb, seconds=4),
    ]
    c = base_contract(shots)
    c["audio_contract"]["dialogue_units"] = [
        {"shot_id": "E24-S01-01", "speaker_id": "CHAR-LINGYAO", "listener_id": "CHAR-AYE", "text": "你说认识龙夜澈？"},
        {"shot_id": "E24-S04-02", "speaker_id": "CHAR-LINGYAO", "listener_id": "CHAR-LINGYAO", "text": "谁能证明？"}]
    c["antagonist_groups"] = [{"group_id": "G", "character_ids": ["CHAR-MUYUNER"], "first_action_shot_id": "E24-S04-01",
                               "motive_setup": {"kind": "line", "ref": "E24-S01-01"}}]
    c["internal_transition_authoring"] = [{"from_shot_id": "E18-S01-01", "to_shot_id": "E18-S01-02"}]
    c["source_binding"] = {"source_chapters": ["21", "22"], "source_file": "/x/as_delivered/ch0018.md"}
    c["pacing"] = {"scene_plan": [{"scene_id": f"E24-S0{i}", "objective": "推进调查并制造可见冲突",
                                   "conflict": "嫌疑人或证据阻碍调查", "physical_action": "抓、夺、定身、捆绑或人群逼近"}
                                  for i in range(1, 5)]}
    return c


# --------------------------------------------------------------------------- 1. SCRIPT_TOO_SHORT
class ScriptTooShortTest(unittest.TestCase):
    def check(self, seconds, brief_target, *, contract_extra=None, in_flight=False):
        import nalu_pipeline as npl
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            contract = d / "contract.json"
            contract.write_text(json.dumps({"shots": [{"target_seconds": s} for s in seconds],
                                            **(contract_extra or {})}), encoding="utf-8")
            (d / "briefs").mkdir()
            if brief_target is not None:
                (d / "briefs" / "E24_PRODUCTION_BRIEF.json").write_text(json.dumps({"target_seconds": brief_target}))
            ctx = SimpleNamespace(episode="E24", p=SimpleNamespace(contract=contract))
            with mock.patch.object(npl, "RUNTIME", d), mock.patch.object(npl, "_camera_grammar_on", lambda _c: True), \
                    mock.patch.object(npl, "s1_pacing_in_flight", lambda _p: in_flight):
                return npl.script_length_check(ctx)

    def test_e24_62s_against_110s_brief_is_an_integrity_blocker(self):
        out = self.check([4.0] * 10 + [2.0] * 11, 110)  # 62 s
        self.assertEqual(out["status"], "BLOCKED")
        self.assertNotIn("blocker", out)  # not the early-return too-long path: the other S1 gates still run
        self.assertTrue(out["integrity_blocker"].startswith("SCRIPT_TOO_SHORT:62.0s<93.5s"))

    def test_floor_is_085_of_target_and_contract_target_counts(self):
        self.assertEqual(self.check([4.0] * 24, 110)["status"], "PASS")              # 96 s >= 93.5
        out = self.check([4.0] * 10, None, contract_extra={"target_seconds": 60})    # 40 s < 51 s
        self.assertTrue(out["integrity_blocker"].startswith("SCRIPT_TOO_SHORT:40.0s<51.0s"))

    def test_undeclared_target_or_in_flight_is_not_held_to_the_floor(self):
        self.assertEqual(self.check([4.0] * 10, None)["status"], "PASS")
        self.assertEqual(self.check([4.0] * 10, 110, in_flight=True)["status"], "PASS")

    def test_too_long_is_unchanged(self):
        out = self.check([4.0] * 60, 110)
        self.assertTrue(out["blocker"].startswith("SCRIPT_TOO_LONG:240.0s>143.0s"))


# --------------------------------------------------------------------------- 2. character entities
class CharacterEntityIntegrityTest(unittest.TestCase):
    def failures(self, contract):
        return cec.validate_character_entity_contract(contract)["failures"]

    def test_valid_contract_passes(self):
        self.assertEqual(self.failures(valid_contract()), [])

    def test_e24_two_person_action_with_one_person_cast(self):
        f = self.failures(e24_like())
        self.assertIn("E24-S01-01_ACTION_NAMES_CHARACTER_NOT_IN_CAST:CHAR-WANGDEFA", f)
        self.assertIn("E24-S03-02_ACTION_NAMES_CHARACTER_NOT_IN_CAST:CHAR-LINGYAO", f)

    def test_undefined_ids_and_self_listener(self):
        f = self.failures(e24_like())
        self.assertIn("E24-S01-01_AUDIO_LISTENER_UNDEFINED:CHAR-AYE", f)
        self.assertIn("E24-S04-02_AUDIO_LISTENER_IS_SPEAKER:CHAR-LINGYAO", f)
        self.assertIn("CHARACTER_ID_REFERENCED_BUT_UNDEFINED:CHAR-AYE", f)
        self.assertIn("CHARACTER_ID_REFERENCED_BUT_UNDEFINED:CHAR-MUYUNER", f)

    def test_declared_offscreen_character_is_defined(self):
        c = e24_like()
        c["offscreen_character_entities"] = [{"character_id": "CHAR-AYE"}, {"character_id": "CHAR-MUYUNER"}]
        f = self.failures(c)
        self.assertFalse([x for x in f if "CHAR-AYE" in x or "CHAR-MUYUNER" in x])

    def test_interaction_target_rules(self):
        c = valid_contract()
        action = c["shots"][0]["prompt_spec"]["action"]
        action.update(interaction_mode="CONTACT", target_entity_id="CHAR-LINGYAO")  # target == subject
        self.assertIn("E24-S01-01_ACTION_TARGET_IS_SUBJECT:CHAR-LINGYAO:CONTACT", self.failures(c))
        action.update(target_entity_id="CHAR-MENGZIQIU")  # physical target not in the frame
        self.assertIn("E24-S01-01_ACTION_TARGET_NOT_IN_CAST:CHAR-MENGZIQIU:CONTACT", self.failures(c))
        c["shots"][0]["prompt_spec"]["role_semantic_disambiguation"]["entity_presence"]["CHAR-MENGZIQIU"] = \
            "OFFSCREEN_VOICE_ONLY"
        self.assertEqual(self.failures(c), [])

    def test_gaze_or_address_to_an_absent_person_is_not_a_defect(self):
        c = valid_contract()
        for text in ("Lingyao glares toward Wang Defa offscreen left.", "凌瑶质问画外王德发。",
                     "Lingyao speaks toward Wang Defa just off lens right.", "凌瑶向王德发逼问。"):
            c["shots"][2]["prompt_spec"]["action"]["primary_action"] = text
            self.assertEqual(self.failures(c), [], text)

    def test_chinese_contact_and_subject(self):
        c = valid_contract()
        c["shots"][2]["prompt_spec"]["action"]["primary_action"] = "凌瑶用匕首抵住王德发的咽喉。"
        self.assertIn("E24-S01-03_ACTION_NAMES_CHARACTER_NOT_IN_CAST:CHAR-WANGDEFA", self.failures(c))
        c["shots"][2]["prompt_spec"]["action"]["primary_action"] = "凌瑶收刀，王德发转身逃走。"
        self.assertIn("E24-S01-03_ACTION_NAMES_CHARACTER_NOT_IN_CAST:CHAR-WANGDEFA", self.failures(c))

    def test_ots_listener_in_a_speaking_unit_is_accepted(self):
        """Line owner 2026-11-23: the listener may be an over-the-shoulder / back-of-head figure in a speaking
        unit; the speaker stays the only one speaking (valid_contract shot E24-S01-02)."""
        c = valid_contract()
        spec = c["shots"][1]["prompt_spec"]
        self.assertEqual(len(spec["cast"]), 2)
        spec["role_semantic_disambiguation"].update(dialogue_listener="凌瑶", dialogue_listener_id="CHAR-LINGYAO")
        self.assertEqual(self.failures(c), [])


# --------------------------------------------------------------------------- 3. structure gate
class StructureIntegrityTest(unittest.TestCase):
    def test_foreign_episode_shot_ids_fail_unless_carried_in(self):
        report = ssg.check_episode_shot_ids(e24_like())
        self.assertIn("FOREIGN_EPISODE_SHOT_ID:$.internal_transition_authoring[].from_shot_id:E18-S01-01",
                      report["failures"])
        c = e24_like()
        c["internal_transition_authoring"][0]["carry_in"] = True
        c["props"] = {"reference_cards": [{"entity_id": "P", "acquired": {"episode": "E20", "shot_id": "E20-S01-01"}}]}
        c["carry_in"] = {"from_shot_id": "E23-S07-01"}
        self.assertEqual(ssg.check_episode_shot_ids(c)["failures"], [])

    def test_source_file_must_be_one_of_the_source_chapters(self):
        self.assertEqual(ssg.check_source_binding(e24_like())["failures"],
                         ["SOURCE_FILE_NOT_IN_SOURCE_CHAPTERS:ch0018.md:[21, 22]"])
        c = e24_like()
        c["source_binding"]["source_file"] = "/x/as_delivered/ch0021.md"
        self.assertEqual(ssg.check_source_binding(c)["failures"], [])
        c["source_binding"]["source_file"] = "/x/E24_NARRATIVE_CANONICAL_v1.md"  # no chapter in the name
        self.assertEqual(ssg.check_source_binding(c)["failures"], [])

    def test_schema_validation(self):
        schema = ssg.load_contract_schema()
        self.assertIsNotNone(schema)
        self.assertEqual(ssg.check_schema(valid_contract(), schema)["failures"], [])
        broken = valid_contract()
        del broken["visual_culture_contract"]
        broken["shots"][0]["target_seconds"] = "five"
        failures = ssg.check_schema(broken, schema)["failures"]
        self.assertIn("SCHEMA_INVALID:$:REQUIRED:visual_culture_contract", failures)
        self.assertIn("SCHEMA_INVALID:$.shots[0].target_seconds:TYPE_NOT_number", failures)

    def test_schema_accepts_the_field_spellings_real_contracts_use(self):
        """Gaps fixed against the lab corpus (holmes / huayuan / urban / wusong, E24): free-text emotions,
        antagonist character_ids, entity_introductions without first_shot_id, a hook without line_or_shot_id,
        a slithering creature."""
        c = valid_contract()
        c["audio_contract"]["dialogue_units"][0]["emotion"] = "急"
        c["antagonist_groups"] = [{"group_id": "G", "character_ids": ["CHAR-WANGDEFA"],
                                   "first_action_shot_id": "E24-S01-02",
                                   "motive_setup": {"kind": "line", "ref": "E24-S01-01"}}]
        c["entity_introductions"] = [{"entity_id": "CHAR-WANGDEFA", "payoff_shot_id": "E24-S01-02"}]
        c["pacing"] = {"hook": {"type": "dialogue", "at_seconds": 0, "shot_id": "E24-S01-01"}}
        c["non_character_entities"] = [{"entity_id": "SNAKE", "kind": "CREATURE", "creature_card": {
            "locomotion": "slithering", "eye_color": "black", "silhouette_ref": "x"}}]
        self.assertEqual(ssg.check_schema(c, ssg.load_contract_schema())["failures"], [])

    def test_cli_validates_the_schema_and_library_default_does_not(self):
        self.assertIn("schema: NOT_REQUESTED", ssg.evaluate(valid_contract())["unverified"])
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.json"
            broken = valid_contract()
            del broken["audio_contract"]
            path.write_text(json.dumps(broken), encoding="utf-8")
            out = Path(d) / "r.json"
            with mock.patch("sys.stdout"):
                ssg.main(["--contract", str(path), "--out", str(out)])
            self.assertIn("SCHEMA_INVALID:$:REQUIRED:audio_contract", json.loads(out.read_text())["failures"])


# --------------------------------------------------------------------------- 4/5. boilerplate + location
class BoilerplateAndLocationTest(unittest.TestCase):
    def test_e24_boilerplate_is_integrity_not_taste(self):
        report = sp.evaluate(e24_like(), environ={})
        integrity = report["integrity_failures"]
        self.assertIn("BOILERPLATE_TEXT:ambience:8/8", integrity)
        self.assertIn("BOILERPLATE_TEXT:scene_plan.objective:4/4", integrity)
        self.assertTrue(any(f.startswith("BOILERPLATE_PHRASE:bamboo wind and field insects") for f in integrity))
        self.assertTrue(report["integrity_active"])
        self.assertFalse([f for f in report["failures"] if f.startswith("BOILERPLATE")])  # outside the taste loop
        self.assertEqual(sp.integrity_blocker_codes(report)[0], "SCRIPT_INTEGRITY_FAIL:" + integrity[0])

    def test_scene_split_whose_action_names_another_place_is_not_admittable(self):
        report = sp.evaluate(e24_like(), environ={})
        self.assertIn("SCENE_SPLIT_LOCATION_CONTRADICTS_ACTION:E24-S02>E24-S03:boat", report["integrity_failures"])
        self.assertIn("SCENE_SPLIT_LOCATION_CONTRADICTS_ACTION:E24-S03>E24-S04:boat/street",
                      report["integrity_failures"])
        self.assertNotIn("SCENE_SPLIT_SAME_LOCATION:E24-S03>E24-S04", report["failures"])
        self.assertIn("SCENE_SPLIT_SAME_LOCATION:E24-S01>E24-S02", report["failures"])  # plain split stays taste

    def test_valid_contract_and_legit_repeats_pass(self):
        self.assertEqual(sp.evaluate(valid_contract(), environ={})["integrity_failures"], [])
        # one long scene with one ambience is that scene's own sound, not a series template
        one_scene = base_contract([shot(f"E24-S01-0{i}", "E24-S01", ["CHAR-LINGYAO"], "Lingyao waits.",
                                        ambience="Rain on the teahouse roof.") for i in range(1, 7)])
        self.assertEqual(sp.boilerplate_failures(one_scene), [])
        # a capitalised street name and a 临街 window are not places the action moves to
        self.assertEqual(sp._place_mentions("Holmes sits in the Baker Street sitting-room."), [])
        self.assertEqual(sp._place_mentions("沈青走到临街纸窗前。"), [])
        self.assertEqual(sp._place_mentions("Lingyao steps onto the old fishing boat."), [("BOAT", "boat")])

    def test_integrity_switch_and_in_flight(self):
        self.assertFalse(sp.evaluate(e24_like(), environ={sp.INTEGRITY_SWITCH: "off"})["integrity_active"])
        report = sp.evaluate(e24_like(), environ={}, in_flight=True)
        self.assertFalse(report["integrity_active"])
        self.assertEqual(sp.integrity_blocker_codes(report), [])

    def test_performance_text_fields_cover_camera_sound_transition(self):
        wheres = {w for w, _ in sp.PERFORMANCE_TEXT_FIELDS}
        self.assertTrue({"camera_plan", "sound", "transition"} <= wheres)


# --------------------------------------------------------------------------- 6. independent script review
class ScriptReviewIndependenceTest(unittest.TestCase):
    def test_self_written_review_is_not_independent(self):
        out = wc.review_independence({"reviewer": "codex", "status": "PASS"})
        self.assertFalse(out["independent"])
        self.assertIn("REVIEWER_NOT_INDEPENDENT:codex", out["failures"])
        self.assertIn("REQUEST_SHA256_MISSING", out["failures"])

    def test_independent_review_with_request_sha(self):
        with tempfile.TemporaryDirectory() as d:
            request = Path(d) / "request.json"
            request.write_text("{}", encoding="utf-8")
            sha = hashlib.sha256(request.read_bytes()).hexdigest()
            good = {"reviewer": "claude-code-nalu-vlm", "responder": "codex", "request_sha256": sha,
                    "request_path": str(request)}
            self.assertTrue(wc.review_independence(good)["independent"])
            self.assertEqual(wc.review_independence({**good, "request_sha256": "0" * 64})["failures"],
                             ["REQUEST_SHA256_MISMATCH"])
            self.assertIn("REVIEWER_IS_RESPONDER:codex-2",
                          wc.review_independence({**good, "reviewer": "codex-2", "responder": "codex-2"})["failures"])

    def test_blocking_follows_the_switch(self):
        rows = {"arc_ledger": {"present": True, "status": "PASS"},
                "adaptation_disposition": {"present": True, "status": "PASS"},
                "script_review": {"present": True, "status": "COMPLETE", "independent": False},
                "rule8_response": {"present": True}}
        with mock.patch.dict(os.environ, {wc.INDEPENDENCE_ENV: ""}):
            self.assertNotIn("SCRIPT_REVIEW_NOT_INDEPENDENT", wc.blocking_policy(rows, {}))
            self.assertIn("SCRIPT_REVIEW_NOT_INDEPENDENT",
                          wc.blocking_policy(rows, {"independent_script_review": True}))
        with mock.patch.dict(os.environ, {wc.INDEPENDENCE_ENV: "block"}):
            self.assertIn("SCRIPT_REVIEW_NOT_INDEPENDENT", wc.blocking_policy(rows, {}))

    def test_s1_row_ignores_the_contract_self_claim(self):
        import nalu_pipeline as npl
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "c.json"
            path.write_text(json.dumps({"script_review": {"reviewer": "codex", "status": "PASS"}}), encoding="utf-8")
            row = npl.script_review_independence_row(
                {"profile": "WRITER_CAPABILITY_V1", "inputs": {"script_review": {
                    "present": True, "independent": False, "independence_failures": ["REVIEWER_NOT_INDEPENDENT:codex"]}},
                 "blocks_stage": []}, path)
        self.assertEqual(row["status"], "NOT_INDEPENDENT")
        self.assertTrue(row["contract_self_review_ignored"])


# --------------------------------------------------------------------------- 7. direction policy DP9
class DirectionPolicyCoverageTest(unittest.TestCase):
    policy = dpg.load_policy(ROOT / "configs" / "DIRECTION_POLICY_V1.json")

    def test_e24_singles_only_fail_dp9(self):
        failures = dpg.integrity_failures(dpg.evaluate(e24_like(), self.policy))
        self.assertIn("DP9_CU_MCU_RATIO_1.0_OVER_0.8", failures)
        self.assertIn("DP9_MULTI_CHARACTER_SCENE_ALL_SINGLES:E24-S01:0<2", failures)

    def test_valid_contract_with_two_shots_and_ots_listener_passes(self):
        report = dpg.evaluate(valid_contract(), self.policy)
        self.assertEqual(dpg.integrity_failures(report), [])
        self.assertEqual(report["measurements"]["DP9"]["scenes"]["E24-S01"]["group_shots"], 2)

    def test_offscreen_voice_is_not_a_group_shot_and_solo_scene_is_exempt(self):
        c = valid_contract()
        c["shots"][1]["prompt_spec"]["cast"][1]["face_visibility"] = "OFFSCREEN_VOICE_ONLY"
        self.assertIn("DP9_MULTI_CHARACTER_SCENE_ALL_SINGLES:E24-S01:1<2",
                      dpg.integrity_failures(dpg.evaluate(c, self.policy)))
        solo = base_contract([shot(f"E24-S01-0{i}", "E24-S01", ["CHAR-LINGYAO"], "Lingyao waits.",
                                   scale="MEDIUM") for i in range(1, 4)])
        self.assertEqual(dpg.integrity_failures(dpg.evaluate(solo, self.policy)), [])

    def test_only_dp9_is_integrity(self):
        self.assertEqual(dpg.integrity_failures({"failures": ["DP1_CU_MCU_RATIO_0.1_BELOW_0.55", "DP9_X"]}),
                         ["DP9_X"])


# --------------------------------------------------------------------------- bounded loop + tick
class IntegrityLoopTest(unittest.TestCase):
    def test_rounds_are_bounded_and_rerun_of_same_bytes_is_free(self):
        import nalu_pipeline as npl
        with tempfile.TemporaryDirectory() as d:
            p = SimpleNamespace(logs=Path(d))
            blockers = ["CHARACTER_ENTITY_CONTRACT_FAIL:x", "GATE10_WRITER_SCENE_SOURCE_DECLARATION_FAIL"]
            first = npl.s1_integrity_round(p, {"contract": "a"}, blockers)
            self.assertEqual((first["decision"], first["round"]), ("REVISE", 1))
            self.assertEqual(npl.s1_integrity_round(p, {"contract": "a"}, blockers)["round"], 1)
            self.assertEqual(npl.s1_integrity_blockers(first, blockers)[0], "SCRIPT_INTEGRITY_REVISE:round=1/4")
            for i, sha in enumerate("bcd", 2):
                self.assertEqual(npl.s1_integrity_round(p, {"contract": sha}, blockers)["round"], i)
            last = npl.s1_integrity_round(p, {"contract": "e"}, blockers)
            self.assertEqual(last["decision"], "EXHAUSTED")
            # after the cap the integrity failures are admitted: only the non-integrity blocker remains
            marked = npl.s1_integrity_blockers(last, blockers)
            self.assertEqual(marked, ["GATE10_WRITER_SCENE_SOURCE_DECLARATION_FAIL"])
            self.assertFalse(any(b.startswith("SCRIPT_INTEGRITY_REVISE:round=") for b in marked))
            self.assertEqual(npl.s1_integrity_round(p, {"contract": "f"}, ["GATE10_X"])["decision"], "PASS")

    def test_admission_marker_and_fleet_note_once(self):
        import nalu_pipeline as npl
        blockers = ["SCRIPT_TOO_SHORT:62.0s<93.5s (target 110.0s): adapt more",
                    "SCRIPT_INTEGRITY_FAIL:BOILERPLATE_TEXT:ambience:22/22",
                    "SCRIPT_INTEGRITY_FAIL:BOILERPLATE_PHRASE:bamboo wind and field insects:22",
                    "DIRECTION_POLICY_INTEGRITY_FAIL:DP9_CU_MCU_RATIO_1.0_OVER_0.8",
                    "CHARACTER_ENTITY_CONTRACT_FAIL:E24-S01-01_ACTION_NAMES_CHARACTER_NOT_IN_CAST:CHAR-WANGDEFA",
                    "PROJECT_SCOPE_FAIL:x"]
        self.assertEqual(npl.s1_integrity_admission_marker(blockers),
                         "SCRIPT_INTEGRITY_ADMITTED_AFTER_EXHAUSTION:SCRIPT_TOO_SHORT,SCRIPT_INTEGRITY_FAIL:"
                         "BOILERPLATE_TEXT,SCRIPT_INTEGRITY_FAIL:BOILERPLATE_PHRASE,DIRECTION_POLICY_INTEGRITY_FAIL:"
                         "DP9_CU_MCU_RATIO_1.0_OVER_0.8,CHARACTER_ENTITY_CONTRACT_FAIL")
        with tempfile.TemporaryDirectory() as d, mock.patch.object(npl, "RUNTIME", Path(d)):
            ctx = SimpleNamespace(episode="E24")
            npl.s1_integrity_fleet_note(ctx, "SCRIPT_INTEGRITY_ADMITTED_AFTER_EXHAUSTION:SCRIPT_TOO_SHORT")
            npl.s1_integrity_fleet_note(ctx, "SCRIPT_INTEGRITY_ADMITTED_AFTER_EXHAUSTION:SCRIPT_TOO_SHORT")
            lines = (Path(d) / "series" / "STATUS.md").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn("E24 S1 SCRIPT_INTEGRITY_ADMITTED_AFTER_EXHAUSTION:SCRIPT_TOO_SHORT", lines[0])

    def test_stage_s1_admits_after_exhaustion_and_continues(self):
        """Round 5 of an E24-like script: S1 PASSES with the admitted codes recorded (no stall), and the S1 blockers
        carry no round marker for the tick to resume."""
        import nalu_pipeline as npl
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            work = root / "work"
            work.mkdir()
            contract = work / "contract.json"
            contract.write_text(json.dumps(e24_like(), ensure_ascii=False), encoding="utf-8")
            layers = {"narrative_canonical": work / "n.md", "directing_script": work / "d.md",
                      "generation_contract": contract, "writer_manifest": work / "m.json"}
            for path in layers.values():
                if not path.exists():
                    path.write_text("{}", encoding="utf-8")
            (root / "briefs").mkdir()
            (root / "briefs" / "E24_PRODUCTION_BRIEF.json").write_text(json.dumps({"target_seconds": 110}))
            logs = root / "logs"
            logs.mkdir()
            (logs / npl.S1_INTEGRITY_LEDGER).write_text(json.dumps({"rounds": [
                {"layers_sha256": f"old{i}"} for i in range(4)]}), encoding="utf-8")
            paths = SimpleNamespace(layers=lambda: layers, contract=contract, writer_manifest=layers["writer_manifest"],
                                    gate10="g", logs=logs, scope={"lexicon": "x", "scope_id": "S"},
                                    narrative=layers["narrative_canonical"], directing=layers["directing_script"],
                                    layers_source="t", state=root / "state.json", work=work)
            entity = json.dumps(cec.validate_character_entity_contract(e24_like()), ensure_ascii=False)

            def run(argv, name=""):
                ok = "entity" not in name
                return {"exit_code": 0, "log": str(root / f"{name}.log"),
                        "stdout_tail": '{"status": "PASS", "failures": []}' if ok else entity}
            ctx = SimpleNamespace(p=paths, episode="E24", run_id="R5", run=run)
            with mock.patch.object(npl, "RUNTIME", root), \
                    mock.patch.object(npl, "_record_line_upgrade", lambda *a, **k: None), \
                    mock.patch.object(npl, "_camera_grammar_on", lambda _c: True), \
                    mock.patch.object(npl, "project_scope_check", lambda *a, **k: {"status": "PASS", "failures": []}), \
                    mock.patch.object(npl, "writer_selfcheck_admitted", lambda *a: True), \
                    mock.patch.object(npl, "writer_capability_record", lambda *a: {}), \
                    mock.patch.object(npl._policy, "selected", lambda: "LEGACY"):
                res = npl.stage_s1(ctx)
            self.assertEqual(res.status, "PASS", res.blockers)
            self.assertEqual(res.blockers, [])
            marker = res.details["s1_integrity_admitted"]
            self.assertTrue(marker.startswith("SCRIPT_INTEGRITY_ADMITTED_AFTER_EXHAUSTION:"))
            for code in ("SCRIPT_TOO_SHORT", "SCRIPT_INTEGRITY_FAIL:BOILERPLATE_TEXT", "CHARACTER_ENTITY_CONTRACT_FAIL",
                         "DIRECTION_POLICY_INTEGRITY_FAIL:DP9_CU_MCU_RATIO_1.0_OVER_0.8"):
                self.assertIn(code, marker)
            self.assertEqual(res.details["s1_integrity"]["decision"], "EXHAUSTED")
            self.assertIn(marker, (root / "series" / "STATUS.md").read_text(encoding="utf-8"))
            receipt = json.loads((logs / "S1_GATE_RECEIPT.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "PASS")

    def test_tick_resumes_once_per_integrity_round(self):
        saved = dict(os.environ)
        runtime = Path(tempfile.mkdtemp()) / "nalu_runtime"
        try:
            os.environ.update(NALU_ENGINE_ROOT=str(ROOT), NALU_RUNTIME_ROOT=str(runtime))
            import codex_production as cp

            def state(blockers):
                path = runtime / "runtime" / "pipeline_state" / "E24.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"stages": {"S1": {"status": "BLOCKED", "blockers": blockers}}}),
                                encoding="utf-8")

            state(["SCRIPT_INTEGRITY_REVISE:round=1/4", "SCRIPT_INTEGRITY_FAIL:BOILERPLATE_TEXT:ambience:8/8"])
            self.assertEqual(cp.integrity_revision_pending("E24", {}), "round=1/4")
            self.assertEqual(cp.integrity_revision_pending("E24", {"integrity_revise_resumed": ["round=1/4"]}), "")
            # after exhaustion S1 carries no round marker (admitted, or only non-integrity blockers): no resume loop
            state(["PROJECT_SCOPE_FAIL:x"])
            self.assertEqual(cp.integrity_revision_pending("E24", {}), "")

            state(["SCRIPT_INTEGRITY_REVISE:round=2/4"])
            d = cp.run_dir("E24")
            d.mkdir(parents=True, exist_ok=True)
            log = d / "codex.log"
            log.write_text("", encoding="utf-8")
            cp.write_json(d / "session.json", {"engine": "codex", "log": str(log), "pid": None})
            (runtime / "series").mkdir(parents=True, exist_ok=True)
            (runtime / "series" / "CURRENT_EPISODE").write_text("E24\n", encoding="utf-8")
            calls = []
            with mock.patch.object(cp, "parse_log", return_value={"nalu_status": {"state": "BLOCKED"}}), \
                    mock.patch.object(cp, "publish_next", return_value=None), \
                    mock.patch.object(cp, "engine_modification", return_value=None), \
                    mock.patch.object(cp, "resume", side_effect=lambda ep, msg: calls.append(msg) or
                                      {"status": "STARTED"}):
                first = cp.tick(system=True)
                second = cp.tick(system=True)
            self.assertEqual(len(calls), 1)
            self.assertIn("SCRIPT_INTEGRITY_REVISE", calls[0])
            self.assertIn("resume_integrity_revision:round=2/4:STARTED", first["did"])
            self.assertNotIn("resume_integrity_revision", " ".join(second["did"]))
        finally:
            os.environ.clear()
            os.environ.update(saved)


if __name__ == "__main__":
    unittest.main()


class ActionTemplateIntegrityTest(unittest.TestCase):
    """Deep review 1485 E09 (JA anime, 2026-11-23): one primary_action / blocking / exit / gesture template on all
    38 shots of five scenes; H3 rendered one stock raised-index-finger gesture for every line."""

    @staticmethod
    def e09_like() -> dict:
        shots = []
        for k, scene in enumerate(("E09-S01", "E09-S02", "E09-S03", "E09-S04")):
            for i in range(1, 4):
                cid = CHARS[(k + i) % 3][0]
                s = shot(f"{scene}-0{i}", scene, [cid],
                         f"{NAME[cid]} grabs the desk or clenches a fist while delivering the line, visibly "
                         "changing the scene state.", line="你说什么", location=f"LOC-{k}")
                s["blocking"] = s["prompt_spec"]["action"]["primary_action"]
                s["completion_state"] = "the speaker finishes the gesture as the threat escalates"
                s["prompt_spec"]["performance"] = {"body_action": "one distinct gesture driven by the conflict"}
                shots.append(s)
        return base_contract(shots)

    def test_shot_action_template_is_integrity(self):
        fails = sp.boilerplate_failures(self.e09_like())
        for key in ("primary_action", "blocking", "completion_state", "body_action"):
            self.assertIn(f"BOILERPLATE_TEXT:{key}:12/12", fails)
        self.assertTrue(any(f.startswith("BOILERPLATE_PHRASE:grabs the desk or clenches a fist") for f in fails))
        report = sp.evaluate(self.e09_like(), environ={})
        self.assertIn("BOILERPLATE_TEXT:primary_action:12/12", report["integrity_failures"])

    def test_neutral_entry_pose_template_is_advisory_only(self):
        c = valid_contract()
        for s in c["shots"]:
            s["entry_state"] = "Someone is visible with both arms lowered before the action begins."
        self.assertEqual(sp.evaluate(c, environ={})["integrity_failures"], [])
        self.assertFalse([f for f in sp.boilerplate_failures(c) if "entry_state" in f])


class SceneContiguityTest(unittest.TestCase):
    """1485 E09: the scenes' silent closing shots were appended after the last scene (a 9 s end montage)."""

    def test_shot_filed_after_a_later_scene_is_integrity(self):
        c = valid_contract()
        scenes = [s["scene_id"] for s in c["shots"]]
        self.assertEqual(sp.scene_order_failures(c), [])
        first = dict(c["shots"][0])
        first["shot_id"] = first["shot_id"] + "-CLOSE"
        c["shots"].append(first)                      # scene 1's closing beat filed at the very end
        if len(set(scenes)) < 2:
            self.skipTest("valid contract has one scene")
        fails = sp.scene_order_failures(c)
        self.assertEqual(fails, [f"SCENE_NOT_CONTIGUOUS:{first['scene_id']}:{first['shot_id']}"])
        report = sp.evaluate(c, environ={})
        self.assertIn(fails[0], report["integrity_failures"])

    def test_declared_intercut_may_return(self):
        c = valid_contract()
        back = dict(c["shots"][0])
        back["intercut"] = True
        c["shots"].append(back)
        self.assertEqual(sp.scene_order_failures(c), [])
