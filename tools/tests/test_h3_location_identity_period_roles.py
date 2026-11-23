"""Device 1101 E24 review (2026-11-23): location first, nobody outside the frame, period-aware identity traits, the
period Never / Look line, named props described, and the post-gen VLM plan questions as objective redo failures.

Offline: no provider call, no network; every paid path is exercised only up to its free planning half.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

from tools import h3_director_prompt_v2 as v2
from tools import visual_culture_contract as vcc
from tools.h3_english_contract_io import apply_answers, request_row
from tools.h3_provider_prompt_renderer import render_h3_prompt
from tools.tests.test_h3_director_prompt_v2 import A, B, fixture

RT = Path(__file__).resolve().parents[2] / "lines" / "nalu" / "runtime" / "tools"
sys.path.insert(0, str(RT))
import build_nalu_preproduction as bnp  # noqa: E402
import character_distinctness as cd  # noqa: E402
import q2_auto_redo as redo  # noqa: E402
import scene_location_lock as sll  # noqa: E402
import scene_location_still as sls  # noqa: E402
import vlm_review_protocol as vrp  # noqa: E402
import video_q2_builder as vq2  # noqa: E402

XIANXIA = {"schema": vcc.SCHEMA, "status": "LOCKED", "profile_id": "LINGYAO-XIANXIA", "era_lock": "EAST_ASIAN_PERIOD",
           "story_world": "Ancient East Asian xianxia realm",
           "production_design": "Ancient East Asian Xuanmen mountain gate and broad spirit fields; no modern objects."}
AUTHORED_PERIOD = {**XIANXIA, "era_lock": "AUTHORED_WORLD"}
NEAR_FUTURE = {**XIANXIA, "era_lock": "AUTHORED_WORLD", "story_world": "Near-future London",
               "production_design": "glass towers"}


def located(unit: dict, location: str = "LOC-ANCHENG-TEAHOUSE", world: dict | None = None) -> dict:
    unit = deepcopy(unit)
    unit["visual_culture_contract"] = dict(world or XIANXIA)
    for spec in unit["ordered_prompt_specs"]:
        spec.setdefault("space", {})["location"] = location
    return unit


class LocationFirst(unittest.TestCase):
    def test_setting_leads_with_the_scene_location_and_drops_series_places(self):
        unit, _ = fixture()
        text = v2.setting_source(located(unit))
        self.assertTrue(text.startswith("Ancheng teahouse"), text)
        self.assertNotIn("Xuanmen", text)                       # series production_design left out
        self.assertIn("Ancient East Asian xianxia realm", text)  # story_world kept after, as era context
        self.assertLess(text.index("Ancheng teahouse"), text.index("Ancient East Asian"))
        # no location of its own: the series design is the only place the unit has
        bare = located(unit, location="")
        self.assertIn("Xuanmen", v2.setting_source(bare))

    def test_location_words(self):
        self.assertEqual(v2.location_id_words("LOC-ANCHENG-TEAHOUSE"), "Ancheng teahouse")
        self.assertEqual(v2.location_id_words("LOC-E24-ROUGE_SHOP"), "Rouge shop")
        self.assertEqual(v2.location_id_words("UNKNOWN_LOCATION"), "")

    def test_translator_is_told_location_first(self):
        unit, plan = fixture()
        unit = located(unit, location="LOC-茶馆")
        row = request_row(unit, plan)
        self.assertTrue(row["source"]["director_v2"]["setting"].startswith("茶馆"))
        self.assertIn("START with the scene's own location", row["source"]["director_v2"]["instructions"])

    def test_location_reference_on_every_unit_and_engine_still_fallback(self):
        editorial = {"scene_location_lock": {}, "shots": [
            {"shot_id": "E24-S01-01", "scene_id": "E24-S01",
             "prompt_spec": {"space": {"location": "LOC-ANCHENG-TEAHOUSE"}, "cast": [{"character_id": A}]}},
            {"shot_id": "E24-S01-02", "scene_id": "E24-S01",
             "prompt_spec": {"space": {"location": "LOC-ANCHENG-TEAHOUSE"}, "cast": [{"character_id": B}]}}]}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            kf = root / "kf"
            kf.mkdir()
            (kf / "E24-S01-01-keyframe-v1.png").write_bytes(b"png-a" * 400)
            (kf / "E24-S01-02-keyframe-v1.png").write_bytes(b"png-b" * 400)
            # a unit that is NOT tail-rejected now gets the place too (its own shot excluded, cast-safe keyframe)
            unit = {"unit_id": "E24-VU-002", "reference_image_paths": [str(kf / "E24-S01-02-keyframe-v1.png")]}
            editorial["shots"][0]["prompt_spec"]["cast"] = []           # the establishing frame shows nobody
            ref = sll.location_reference_for_unit(unit, ["E24-S01-02"], editorial)
            self.assertEqual((ref["source"], ref["source_shot_id"]), ("SCENE_KEYFRAME", "E24-S01-01"))
            # the free plan of an S5 still: one row per location, the fewest-people keyframe as its source
            rows = sls.plan(editorial, kf, episode="E24", runtime_root=root)
            self.assertEqual([(r["location_id"], r["source_shot_id"]) for r in rows],
                             [("LOC-ANCHENG-TEAHOUSE", "E24-S01-01")])
            self.assertIn("every person removed", sls.still_prompt(rows[0]))
            self.assertIn("Ancheng teahouse", sls.still_prompt(rows[0]))
            # a READY still (sha-bound) is what the H3 compile binds when no stage-3(a) plate exists
            still_dir = sls.stills_dir(root, "E24")
            still_dir.mkdir(parents=True)
            still = still_dir / "E24_LOC-ANCHENG-TEAHOUSE_LOCATION_STILL.png"
            still.write_bytes(b"still" * 400)
            registry = {"schema": sls.SCHEMA, "locations": {"LOC-ANCHENG-TEAHOUSE": {
                "status": "READY", "path": str(still), "sha256": hashlib.sha256(still.read_bytes()).hexdigest()}}}
            sls.registry_path(root, "E24").write_text(json.dumps(registry), encoding="utf-8")
            self.assertEqual(sls.registered_still("LOC-ANCHENG-TEAHOUSE", episode="E24", runtime_root=root), still)
            self.assertEqual(sls.plan(editorial, kf, episode="E24", runtime_root=root), [])  # nothing left to make
            with mock.patch.object(bnp, "_scoped_asset_library_path", return_value=root / "absent.json"), \
                    mock.patch.object(bnp._np, "RUNTIME_ROOT", root):
                self.assertEqual(bnp._locked_scene_plate("LOC-ANCHENG-TEAHOUSE", episode="E24"), still)
            still.write_bytes(b"tampered" * 400)                           # bytes moved: never bound
            self.assertIsNone(sls.registered_still("LOC-ANCHENG-TEAHOUSE", episode="E24", runtime_root=root))

    def test_still_generation_is_durable_and_registered(self):
        import types

        class FakeClient:
            MODEL = "gpt-image-2"
            hops = types.SimpleNamespace(HopsapiNotCharged=type("HopsapiNotCharged", (Exception,), {}))
            posts = 0

            def prepare_request(self, **kw):
                return {"payload": {"task": "img2img", "model": self.MODEL}, "resolution": "1024x1536"}

            def intent_fields(self, prepared):
                return {"provider": "hopsapi"}

            def create_image_task(self, payload):
                FakeClient.posts += 1
                return {"task_id": "tsk_1"}

            def query_task(self, task_id):
                return {"remote_status": "completed", "urls": ["https://x/y.png"], "cost": 1.2}

            def record_settlement(self, tx, task_id, status, now):
                row = json.loads(Path(tx).read_text())
                row["provider_cost_credits"] = status["cost"]
                Path(tx).write_text(json.dumps(row))

            def download_image(self, url, dest):
                Path(dest).write_bytes(b"location" * 300)
                return {"path": str(dest)}

            def normalise_portrait_9_16(self, path):
                return {"status": "UNCHANGED"}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frame = root / "E24-S01-01-keyframe-v1.png"
            frame.write_bytes(b"frame" * 300)
            row = {"location_id": "LOC-ANCHENG-TEAHOUSE", "scene_ids": ["E24-S01"], "source_shot_id": "E24-S01-01",
                   "source_keyframe": str(frame), "source_keyframe_sha256": "f" * 64, "location_words": ""}
            registry: dict = {}
            out = sls.stills_dir(root, "E24")
            out.mkdir(parents=True)
            result = sls.generate_one(row, registry, client=FakeClient(), engine_root=root, out_dir=out, episode="E24",
                                      sleep=lambda s: None)
            self.assertEqual(result["status"], "READY")
            entry = registry["locations"]["LOC-ANCHENG-TEAHOUSE"]
            self.assertEqual(entry["status"], "READY")
            tx = json.loads(Path(entry["attempts"][0]["transaction"]).read_text())
            self.assertEqual((tx["state"], tx["provider_cost_credits"]), ("SUBMITTED_TASK_ID_BOUND", 1.2))
            self.assertIn("giggle_submit_transactions/E24/", entry["attempts"][0]["transaction"])
            # a re-run resumes the bound transaction: never a second POST
            sls.generate_one(row, registry, client=FakeClient(), engine_root=root, out_dir=out, episode="E24",
                             sleep=lambda s: None)
            self.assertEqual(FakeClient.posts, 1)

    def test_location_reference_line_says_background_only(self):
        unit, plan = fixture()
        unit["reference_images"].append({"path": "loc.png", "role": "SCENE_LOCATION_REFERENCE"})
        text, _ = render_h3_prompt(unit, plan)
        self.assertIn("@Image4 is this scene's location, for the background and location only", text)


class ActionNamesOnlyTheFrame(unittest.TestCase):
    def _with_absent(self, action: str) -> tuple[dict, dict]:
        unit, plan = fixture()
        unit["character_entities"].append({"character_id": "CHAR-WANGDEFA", "canonical_name": "王德发",
                                           "aliases": ["Wang Defa"]})
        unit["h3_provider_english_contract"]["beats"][0]["primary_action"] = action
        return unit, plan

    def test_action_naming_someone_not_in_frame_is_refused(self):
        unit, plan = self._with_absent("Alpha presses a dagger to Wang Defa's throat and demands the name")
        self.assertEqual(v2.people_named_outside_frame(unit, plan, ["Alpha presses a dagger to Wang Defa's throat"]),
                         ["Wang Defa"])
        with self.assertRaisesRegex(ValueError, "H3_ACTION_NAMES_PERSON_NOT_IN_FRAME:Wang Defa"):
            render_h3_prompt(unit, plan)

    def test_lowercase_words_and_in_frame_names_pass(self):
        unit, plan = self._with_absent("Alpha holds her dagger level, its point toward frame left; Beta watches")
        self.assertEqual(v2.people_named_outside_frame(unit, plan, ["the wang family sword is old"]), [])
        render_h3_prompt(unit, plan)  # no raise

    def test_writer_gets_the_finding_back(self):
        unit, plan = self._with_absent("Alpha presses a dagger to Wang Defa's throat")
        english = deepcopy(unit.pop("h3_provider_english_contract"))
        row = request_row(unit, plan)
        answers = {"units": {row["answer_key"]: {"execution_semantics_sha256": row["execution_semantics_sha256"],
                                                  "english": {**row["english"], **{
                                                      k: english[k] for k in row["english"] if k in english}}}}}
        # fill any template slot the fixture contract does not carry
        filled = answers["units"][row["answer_key"]]["english"]
        if "director_v2" in row["english"]:
            filled["director_v2"] = json.loads(json.dumps(row["english"]["director_v2"]).replace('""', '"x"'))
        with mock.patch("tools.h3_english_contract_io.plan_for", return_value=plan):
            result = apply_answers(unit, answers)
        self.assertIsNotNone(result)
        self.assertEqual(result["reason"], "ANSWER_INVALID")
        self.assertTrue(any("NAMES_PERSON_NOT_IN_FRAME:Wang Defa" in p for p in result["problems"]), result["problems"])

    def test_background_figures_only_when_extras_are_declared(self):
        unit, plan = fixture()
        unit["provider_scope_projection"]["background_population_count"] = 3   # no declared extras
        text, _ = render_h3_prompt(unit, plan)
        never = text.split("\n\nNever: ")[1]
        self.assertNotIn("background figures", never)
        self.assertIn("anyone else in frame", never)


class PeriodTraitsAndNever(unittest.TestCase):
    def test_premodern_detection(self):
        self.assertTrue(vcc.is_premodern_period(XIANXIA))
        self.assertTrue(vcc.is_premodern_period(AUTHORED_PERIOD))
        self.assertFalse(vcc.is_premodern_period(NEAR_FUTURE))
        self.assertFalse(vcc.is_premodern_period({"era_lock": "AUTHORED_WORLD", "story_world": "Victorian London"}))
        self.assertFalse(vcc.is_premodern_period(None))

    def test_period_trait_plan_has_no_glasses_greying_or_modern_cut(self):
        for sex in ("男", "女"):
            for n in range(40):
                own = {"subject_id": f"CHAR-{n}", "name": f"N{n}", "sex": sex, "age": "30-40"}
                text = cd.contrast_block(own, [], language="en", period=True) + \
                    cd.contrast_block(own, [], language="zh", period=True)
                for word in ("glasses", "眼镜", "greying", "斑白", "crew cut", "寸头", "pixie", "bob", "black hair",
                             "黑色"):
                    self.assertNotIn(word, text, (sex, n, word))
        # the default (modern) table still offers glasses, but never a hair colour
        self.assertTrue(any("glasses" in en for _, en in cd.TRAITS["extra_m"]))
        self.assertFalse(any("black" in en for _, en in cd.TRAITS["hair_f"]))

    def test_card_with_glasses_is_regenerated_once_through_the_distinctness_path(self):
        prompt = "面部：圆脸、细框眼镜、清瘦。\nConcrete traits: a round face; thin-rimmed glasses; slim."
        findings = cd.period_trait_findings(prompt)
        self.assertEqual(findings, ["细框眼镜", "thin-rimmed glasses"])
        self.assertNotIn("眼镜", cd.strip_period_traits(prompt))
        self.assertEqual(cd.period_trait_findings("不戴眼镜、眉形平直"), [])
        cast = {"CHAR-DEMON": {"subject_id": "CHAR-DEMON", "name": "妖", "sex": "男"},
                "CHAR-TOWNSMAN": {"subject_id": "CHAR-TOWNSMAN", "name": "镇民", "sex": "男"}}
        emb = {"CHAR-DEMON": [[1.0, 0.0]], "CHAR-TOWNSMAN": [[0.0, 1.0]]}
        report = cd.evaluate(emb, order=list(cast), cast=cast, policy={}, regenerable=[],
                             locked_regenerable=["CHAR-DEMON", "CHAR-TOWNSMAN"], period=True,
                             period_recards={"CHAR-DEMON": findings, "CHAR-TOWNSMAN": ["black-framed glasses"]})
        self.assertEqual(report["status"], "REGENERATE")
        actions = {a["subject_id"]: a for a in report["regenerate"]}
        self.assertEqual(set(actions), {"CHAR-DEMON", "CHAR-TOWNSMAN"})
        self.assertTrue(all(a["unlock_locked"] and a["reason"] == cd.PERIOD_RECARD_REASON for a in actions.values()))
        self.assertIn("不戴任何眼镜", actions["CHAR-DEMON"]["block"])
        # once only: a card already regenerated is never planned again
        done = {"regenerations": {"CHAR-DEMON": {"block": "x"}, "CHAR-TOWNSMAN": {"block": "x"}}}
        again = cd.evaluate(emb, order=list(cast), cast=cast, policy=done, regenerable=[],
                            locked_regenerable=list(cast), period=True,
                            period_recards={"CHAR-DEMON": findings, "CHAR-TOWNSMAN": ["glasses"]})
        self.assertEqual(again["regenerate"], [])

    def test_never_and_look_lines_for_a_premodern_world(self):
        unit, plan = fixture()
        text, receipt = render_h3_prompt(located(unit), plan)
        never = text.split("\n\nNever: ")[1]
        self.assertIn("eyeglasses or spectacles", never)
        self.assertIn("modern accessories", never)
        self.assertEqual(receipt.get("period_lock"), "PRE_MODERN")
        # an AUTHORED_WORLD pre-modern unit now states its period Look line too (it was left out as filler)
        text, _ = render_h3_prompt(located(unit, world=AUTHORED_PERIOD), plan)
        self.assertIn(v2.PERIOD_LOOK_V2, text)
        self.assertIn("eyeglasses or spectacles", text.split("\n\nNever: ")[1])
        # a modern authored world: no period ban, no Look line
        text, receipt = render_h3_prompt(located(unit, world=NEAR_FUTURE), plan)
        self.assertNotIn("eyeglasses", text)
        self.assertNotIn("Look:", text)
        self.assertNotIn("period_lock", receipt)

    def test_authored_world_fallback_forbids_glasses(self):
        import bootstrap_identity_cards as bic
        self.assertIn("eyeglasses/spectacles", bic.AUTHORED_WORLD_FALLBACK_CONTRACT["forbidden_influences"])
        self.assertIn("modern accessories", bic.AUTHORED_WORLD_FALLBACK_CONTRACT["forbidden_influences"])


class NamedProps(unittest.TestCase):
    def test_named_prop_is_described_and_logged_without_card(self):
        unit, plan = fixture()
        unit["ordered_prompt_specs"][0]["props"] = [{"prop_id": "PROP-DAGGER", "prop": "匕首",
                                                     "english_name": "dagger",
                                                     "description_en": "A short bronze dagger with a red cord hilt"}]
        unit["h3_provider_english_contract"]["beats"][0]["primary_action"] = "Alpha raises the dagger"
        text, receipt = render_h3_prompt(unit, plan)
        self.assertIn("Props: the dagger is a short bronze dagger with a red cord hilt.", text)
        self.assertEqual(receipt["props_named"]["without_card"], ["PROP-DAGGER"])

    def test_undeclared_prop_gets_a_translation_slot(self):
        unit, plan = fixture()
        unit["ordered_prompt_specs"][0]["action"] = {"primary_action": "凌瑶把符纸贴在门上"}
        rows = v2.named_props(unit, ["凌瑶把符纸贴在门上"])
        self.assertEqual([(r["key"], r["declared"]) for r in rows], [("talisman", False)])
        row = request_row(unit, plan)
        self.assertEqual(row["english"]["director_v2"]["props"], {"talisman": {"description": ""}})


class PostGenVlmQuestions(unittest.TestCase):
    def test_question_set(self):
        questions = vrp.QUESTIONNAIRES["video_q2"]
        for key in ("action_roles_as_planned", "no_person_outside_declared_cast", "location_matches_scene",
                    "no_modern_object_in_period_world"):
            self.assertIn(key, questions)
        self.assertIn("Who performs the action, on whom, and who holds the named prop?",
                      questions["action_roles_as_planned"]["question"])
        self.assertIn("Are there people not in the declared cast?",
                      questions["no_person_outside_declared_cast"]["question"])
        self.assertIn("Does the location match the scene?", questions["location_matches_scene"]["question"])
        self.assertIn("eyeglasses", questions["no_modern_object_in_period_world"]["question"])
        self.assertEqual(vrp.VLM_OBJECTIVE_FAILURES, redo.VLM_QUESTION_FAILURES)
        gate_keys = {k for keys in vq2.GATE_QUESTIONS.values() for k in keys}
        self.assertTrue(set(redo.VLM_QUESTION_FAILURES) <= gate_keys)

    def test_vlm_failures_are_objective_and_redone_once_under_the_cap(self):
        prepare = {"E24-VU-001": {"media_sha256": "aaa"}, "E24-VU-004": {"media_sha256": "bbb"},
                   "E24-VU-007": {"media_sha256": "ccc"}}

        def item(uid, sha, **answers):
            return {"item_id": uid, "answers": answers, "observation": "the blade is at Lingyao's own throat",
                    "request_item": {"unit_id": uid, "media": [{"role": "UNIT_VIDEO", "sha256": sha}]}}
        review = {"items": [item("E24-VU-001", "aaa", action_roles_as_planned="FAIL"),
                            item("E24-VU-004", "bbb", location_matches_scene="FAIL",
                                 no_modern_object_in_period_world="FAIL"),
                            item("E24-VU-007", "OLD", no_person_outside_declared_cast="FAIL")]}  # stale clip
        rows = redo.with_vlm_failures(prepare, review)
        self.assertEqual(redo.objective_failures(rows["E24-VU-001"]), ["role_reversed"])
        self.assertEqual(redo.objective_failures(rows["E24-VU-004"]), ["wrong_location", "anachronism"])
        self.assertEqual(redo.objective_failures(rows["E24-VU-007"]), [])
        # anime / CAMERA_GRAMMAR_V1 off: the VLM answers still count (they are not InsightFace)
        self.assertEqual(redo.objective_failures(rows["E24-VU-001"], technical_only=True), ["role_reversed"])
        self.assertTrue(redo.needs_own_keyframe(["wrong_location"]))
        decision = redo.plan(rows, {"E24-VU-004": {"source": "SUPERSEDED_CLIP_ON_DISK"}}, headroom=30,
                             unit_cost=lambda uid: 20)
        self.assertEqual([r["unit_id"] for r in decision["selected"]], ["E24-VU-001"])
        self.assertEqual({r["unit_id"]: r["reason"] for r in decision["skipped"]},
                         {"E24-VU-004": "ALREADY_REDONE_ONCE"})
        self.assertEqual(redo.vlm_objective_failures({"location_matches_scene": "PASS"}), [])

    def test_q2_expectations_carry_roles_location_and_period(self):
        import types
        import nalu_qa_common as qc
        stub = types.SimpleNamespace(
            contract={"visual_culture_contract": XIANXIA,
                      "character_entities": [{"character_id": "CHAR-LINGYAO", "canonical_name": "凌瑶"},
                                             {"character_id": "CHAR-WANGDEFA", "canonical_name": "王德发"}]},
            shots={"E24-S01-01": {"prompt_spec": {
                "space": {"location": "LOC-ANCHENG-TEAHOUSE"}, "props": [{"prop": "匕首"}],
                "action": {"primary_action": "Lingyao presses a dagger to Wang Defa's throat",
                           "initiator_entity_id": "CHAR-LINGYAO", "target_entity_id": "CHAR-WANGDEFA"}}}},
            character_name_to_id=lambda: {})
        facts = qc.Expectations.q2_role_location_period(stub, ["E24-S01-01"])
        self.assertEqual(facts["period_setting"], "PRE_MODERN")
        self.assertEqual(facts["scene_location"]["words"], "ancheng teahouse")
        self.assertEqual({k: facts["action_roles"][0][k] for k in ("initiator", "target", "prop_holder")},
                         {"initiator": "凌瑶", "target": "王德发", "prop_holder": "凌瑶"})


if __name__ == "__main__":
    unittest.main()
