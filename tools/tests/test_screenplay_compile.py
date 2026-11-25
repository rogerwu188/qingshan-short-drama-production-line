"""SCREENPLAY_V1 compiler (owner 2026-11-23, Bilibili benchmark CHANGE_SPEC WP2).

Covers: the light YAML subset; screenplay parse (scenes, cards, dialogue / action / reaction / prop / silent rows,
tags); compile of the worked example from 剧本反推.md §6 (E25 妖皇宫, ch.226 -- fixtures/screenplay_e25) into a
contract that passes the S1 gates (gate10, character entity, static design, script structure + schema, continuity,
seq29 self-check, direction-policy integrity, pacing integrity and the anti-template v2 checks); prop declaration
and carry; reaction placement; emotion derivation (no rotation; explicit override); fallback marking; English twins
(request / answer cycle); the write round-trip; WP1 / WP5 / WP6 fields; the S1 pre-step (SCREENPLAY_V1 compiles,
LEGACY untouched) and the Codex prompt section (kept only for SCREENPLAY_V1).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "skills" / "nalu-claude-code" / "scripts", ROOT / "tools", ROOT,
           ROOT / "agent_factory" / "claude_writer_v2" / "gates"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import nalu_writer_selfcheck_seq29 as s29  # noqa: E402
import screenplay_checks as spk  # noqa: E402
import screenplay_compile as spc  # noqa: E402
import script_pacing_check as pace  # noqa: E402
import static_design_gate as sdg  # noqa: E402
import writer_scene_source_declaration_gate as gate10  # noqa: E402
from tools import character_entity_contract as cec  # noqa: E402
from tools import continuity_state_contract_gate as csg  # noqa: E402
from tools import direction_policy_gate as dpg  # noqa: E402
from tools import script_structure_contract_gate as ssg  # noqa: E402

FIXTURE = ROOT / "tools" / "tests" / "fixtures" / "screenplay_e25"
SOURCE_TXT = Path("/tmp/nalu_src/zaonie.txt")


def compiled() -> dict:
    return spc.compile_files(FIXTURE, "E25")


def shot(contract: dict, sid: str) -> dict:
    return next(s for s in contract["shots"] if s["shot_id"] == sid)


class LightYamlTest(unittest.TestCase):
    def test_subset(self):
        doc = spc.load_yaml(
            "# comment\n"
            "title: 妖皇称臣\n"
            "chapters: [226, 227]\n"
            "flags: {a: 1, b: true}\n"
            "cast:\n"
            "  - id: CHAR-A   # trailing comment\n"
            "    name: \"甲\"\n"
            "    aliases: [阿甲]\n"
            "  - id: CHAR-B\n"
            "    name: 乙\n"
            "note: |\n"
            "  line one\n"
            "  line two\n"
            "empty:\n"
            "list_at_key:\n"
            "- x\n"
            "- y\n")
        self.assertEqual("妖皇称臣", doc["title"])
        self.assertEqual([226, 227], doc["chapters"])
        self.assertEqual({"a": 1, "b": True}, doc["flags"])
        self.assertEqual(["阿甲"], doc["cast"][0]["aliases"])
        self.assertEqual("乙", doc["cast"][1]["name"])
        self.assertEqual("line one\nline two", doc["note"])
        self.assertIsNone(doc["empty"])
        self.assertEqual(["x", "y"], doc["list_at_key"])
        self.assertEqual({"k": [1]}, spc.load_yaml('{"k": [1]}'))

    def test_bad_indentation_is_an_error(self):
        with self.assertRaises(spc.YamlError):
            spc.load_yaml("a: 1\n   b: 2\n  c: 3\n")

    def test_outline_yaml_block(self):
        block = spc.yaml_blocks_in_markdown((FIXTURE / "E25_OUTLINE.md").read_text(encoding="utf-8"))
        self.assertEqual("MAIN", block["plot_events"][0]["role"])
        self.assertTrue(block["end_hook"]["open_question"])


class ParseTest(unittest.TestCase):
    def test_scene_card_and_rows(self):
        parsed = spc.parse((FIXTURE / "E25_SCREENPLAY.md").read_text(encoding="utf-8"))
        self.assertEqual([], parsed["errors"])
        scene = parsed["scenes"][0]
        self.assertEqual(("S01", "妖皇宫正殿", "日", "殿门逆光"),
                         (scene["num"], scene["location_name"], scene["time"], scene["light"]))
        card = scene["card"]
        self.assertEqual(["白桃", "战雷", "麒麟"], [g["who"] for g in card["goals"]])
        self.assertIn("私事", card["source_detail_ids"])
        self.assertIsNone(card["mirror_of"])
        kinds = [it["kind"] for it in scene["items"]]
        self.assertEqual(2, kinds.count("prop"))
        self.assertIn("reaction", kinds)
        silent = [it for it in scene["items"] if it.get("silent")]
        self.assertEqual(3, len(silent))
        tagged = next(it for it in scene["items"] if "转折:REVERSAL" in it.get("tags", []))
        self.assertIn("双关", tagged["tags"])

    def test_format_doc_example_parses(self):
        md = ("## S02 妖皇宫正殿 · 日 · 逆光\n"
              "@card goal[白桃]=拿一句臣服交差 | obstacle=妖皇不在 | turn=正主进门一口答应，狠话落空 | "
              "type=争吵→喜剧落空 | source=二郎腿;拱手求宽限 | mirror_of=-\n"
              "妖皇宝座上，白桃帝姬翘着二郎腿，指尖转着战神令。台阶下，战雷拱手。      ← action line\n"
              "白桃（不抬眼，对战雷）：三天到了。你们的妖皇呢？\n"
              "[麒麟 反应：离开柱子，拳头攥紧]\n"
              "{道具 战神令 @白桃.右手}\n")
        scene = spc.parse(md)["scenes"][0]
        self.assertEqual(["action", "dialogue_candidate", "reaction", "prop"], [i["kind"] for i in scene["items"]])
        self.assertEqual("右手", scene["items"][3]["hand"])
        self.assertNotIn("←", scene["items"][0]["text"])


class CompileE25Test(unittest.TestCase):
    """The 剧本反推.md §6 rewrite compiles into a contract that passes the S1 gates."""

    @classmethod
    def setUpClass(cls):
        cls.out = compiled()
        cls.c = cls.out["contract"]

    def test_report(self):
        report = self.out["report"]
        self.assertEqual("PASS", report["status"], report)
        self.assertEqual([], report["errors"])
        self.assertEqual(0, report["en_missing"])
        self.assertEqual(0, report["en_stale"])
        self.assertEqual(15, report["shots"])
        self.assertAlmostEqual(62.0, report["seconds"])  # 剧本反推 §6 L4: about 62 s

    def test_stamps_and_layers(self):
        c = self.c
        self.assertEqual(("BILI_V1", "SCREENPLAY_V1", "CAMERA_GRAMMAR_V1", "DIRECTOR_PROMPT_V2"),
                         (c["craft_profile"], c["writer_format"], c["camera_grammar_policy"], c["h3_prompt_style"]))
        self.assertTrue(spk.active(c) and spk.screenplay(c))
        self.assertIn("## E25-S01｜LOC-YAOHUANG-HALL｜日｜线A", self.out["narrative_md"])
        self.assertIn("白桃帝姬：三天到了。你们的妖皇呢？", self.out["narrative_md"])
        self.assertIn("### E25-S01-11", self.out["directing_md"])
        self.assertEqual(["E25-S01"], [r["scene_id"] for r in self.out["manifest"]["structure"]])

    def test_s1_gates_pass(self):
        c, manifest = self.c, self.out["manifest"]
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "E25_manifest_v1.json"
            path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            self.assertEqual("PASS", gate10.audit(str(path))["status"])
        entity = cec.validate_character_entity_contract(c)
        self.assertEqual("PASS", entity["status"], entity["failures"])
        self.assertEqual([], sdg.evaluate(c, dict(sdg.POLICY))["failures"])
        lexicon = json.loads((ROOT / "lines/nalu/runtime/configs/LEXICON_portable_template_v1.json")
                             .read_text(encoding="utf-8"))
        structure = ssg.evaluate(c, manifest, lexicon, schema=ssg.load_contract_schema())
        self.assertNotEqual("FAIL", structure["status"], structure["failures"])
        self.assertEqual("PASS", csg.evaluate(c)["status"])
        selfcheck = s29.evaluate(c)
        self.assertEqual("PASS", selfcheck["status"], selfcheck["failures"])
        report = dpg.evaluate(c, dpg.load_policy(ROOT / "configs" / "DIRECTION_POLICY_V1.json"))
        self.assertEqual([], dpg.integrity_failures(report))
        pacing = pace.evaluate(c, "zh")
        self.assertEqual([], pacing["integrity_failures"])
        self.assertEqual("PASS", pacing["integrity_status"])
        checks = spk.evaluate(c)
        self.assertEqual(([], []), (checks["integrity"], checks["taste"]), checks)
        self.assertEqual([], checks["advisory"])

    def test_props_declared_and_carried(self):
        cards = {r["name"]: r for r in self.c["props"]["reference_cards"]}
        self.assertEqual({"战神令", "长枪"}, set(cards))
        token = cards["战神令"]
        self.assertEqual(("CHAR-BAITAODIJI", "右手"), (token["owner_id"], token["hand"]))
        self.assertTrue(token["description_en"])
        self.assertGreaterEqual(len(token["used_in_shot_ids"]), 4)
        s01 = shot(self.c, "E25-S01-01")["prompt_spec"]["props"]
        self.assertIn({"prop": "战神令", "prop_id": "PROP-ZHANSHENLING", "entity_id": "PROP-ZHANSHENLING",
                       "owner_id": "CHAR-BAITAODIJI", "owner_name": "白桃帝姬", "hand": "右手"}, s01)
        self.assertTrue(all(s["prompt_spec"]["props"] for s in self.c["shots"]
                            if "令" in s["prompt_spec"]["action"]["primary_action"]))

    def test_dialogue_shot_has_the_listener_over_the_shoulder(self):
        cast = shot(self.c, "E25-S01-03")["prompt_spec"]["cast"]  # 战雷 asks for more time, 白桃 in frame
        self.assertEqual([("CHAR-ZHANLEI", "FRONT_FACE_VISIBLE"), ("CHAR-BAITAODIJI", "BACK_AND_SHOULDERS_ONLY")],
                         [(r["character_id"], r["face_visibility"]) for r in cast])
        dialogue_shots = [s for s in self.c["shots"] if s["prompt_spec"]["dialogue"]]
        two = [s for s in dialogue_shots if len(s["prompt_spec"]["cast"]) >= 2]
        self.assertGreaterEqual(len(two) / len(dialogue_shots), 0.9)

    def test_offscreen_line_plays_on_the_listener(self):
        spec = shot(self.c, "E25-S01-05")["prompt_spec"]  # 商余烬（OS，殿外）：找我何事？
        role = spec["role_semantic_disambiguation"]
        self.assertEqual("OFFSCREEN_VOICE_ONLY", role["entity_presence"]["CHAR-SHANGYUJIN"])
        self.assertEqual("", role["lip_owner_id"])
        self.assertEqual([("CHAR-BAITAODIJI", "FRONT_FACE_VISIBLE")],
                         [(r["character_id"], r["face_visibility"]) for r in spec["cast"]])

    def test_reaction_placement(self):
        a = shot(self.c, "E25-S01-04")["prompt_spec"]["action"]  # 三天变五天 -> [麒麟 反应]
        self.assertEqual("麒麟：离开柱子，右拳攥紧", a["listener_reaction"])
        self.assertTrue(a["listener_reaction_en"].startswith("Qilin"))
        silent = shot(self.c, "E25-S01-06")["prompt_spec"]  # the entrance; 白桃 sits up in the same frame
        self.assertIn("二郎腿放下", silent["action"]["listener_reaction"])
        self.assertIn("CHAR-BAITAODIJI", [r["character_id"] for r in silent["cast"]])
        parsed = spc.parse("## S01 殿 · 日\n@card goal[甲]=a | obstacle=b | turn=c\n[乙 反应：抬头]\n甲：走。\n")
        out = spc.compile_screenplay(parsed, {"cast": [{"id": "CHAR-A", "name": "甲"}, {"id": "CHAR-B", "name": "乙"}],
                                              "locations": [{"id": "LOC-X", "name": "殿"}]}, {}, {}, episode="E01")
        self.assertEqual("乙：抬头", out["contract"]["shots"][0]["prompt_spec"]["action"]["lead_in_reaction"])

    def test_creature_kind_and_card_reach_the_contract(self):
        parsed = spc.parse("## S01 殿 · 日\n@card goal[甲]=a | obstacle=b | turn=c\n[道具 白狐]\n甲：走。\n")
        card = {"body": "白色四足", "tails": 9}
        cast_props = {"cast": [{"id": "CHAR-A", "name": "甲"}], "locations": [{"id": "LOC-X", "name": "殿"}],
                      "props": [{"id": "PROP-FOX", "name": "白狐", "kind": "CREATURE", "description": "白狐"},
                                {"id": "PROP-CUP", "name": "茶杯", "description": "茶杯"}],
                      "non_character_entities": [
                          {"entity_id": "PROP-FOX", "name": "白狐", "kind": "CREATURE", "creature_card": card},
                          {"entity_id": "PROP-BIRD", "name": "青鸟", "kind": "ANIMAL"}]}
        c = spc.compile_screenplay(parsed, cast_props, {}, {}, episode="E01")["contract"]
        beings = {r["entity_id"]: r for r in c["non_character_entities"]}
        self.assertEqual({"PROP-FOX", "PROP-BIRD"}, set(beings))
        self.assertEqual(("CREATURE", card), (beings["PROP-FOX"]["kind"], beings["PROP-FOX"]["creature_card"]))
        self.assertEqual("ANIMAL", beings["PROP-BIRD"]["kind"])
        refs = {r["entity_id"]: r for r in c["props"]["reference_cards"]}
        self.assertEqual(card, refs["PROP-FOX"]["creature_card"])
        self.assertNotIn("kind", refs["PROP-CUP"])
        self.assertEqual([], self.c["non_character_entities"])  # plain props stay out
        # S2 asset requirements read row["note"] (E28 S2 KeyError 2026-11-25): every being carries one
        self.assertEqual("白狐", beings["PROP-FOX"]["note"])
        self.assertEqual("青鸟", beings["PROP-BIRD"]["note"])

    def test_partner_action_and_reactions_name_the_reacting_character(self):
        spec = shot(self.c, "E25-S01-10")["prompt_spec"]  # 商余烬看着令牌，低低笑了一声 / 白桃：你笑什么？
        self.assertEqual("CHAR-SHANGYUJIN", spec["action"]["subject_id"])
        self.assertEqual("CHAR-BAITAODIJI", spec["role_semantic_disambiguation"]["lip_owner_id"])
        self.assertEqual(["CHAR-QILINHUMAN"], shot(self.c, "E25-S01-04")["prompt_spec"]["action"]["listener_reaction_by"])

    def test_touch_in_the_two_person_beats(self):
        a13 = shot(self.c, "E25-S01-13")["prompt_spec"]["action"]
        self.assertEqual(("CHAR-QILINHUMAN", "CHAR-SHANGYUJIN", "CONTACT"),
                         (a13["subject_id"], a13["target_entity_id"], a13["interaction_mode"]))
        self.assertEqual(3, spk.evaluate(self.c)["metrics"]["touches_per_scene"]["E25-S01"])

    def test_emotion_is_derived_not_rotated(self):
        perf = {s["shot_id"]: s["prompt_spec"]["action"]["performance"] for s in self.c["shots"]
                if s["prompt_spec"]["dialogue"]}
        self.assertEqual(("讥", "parenthetical"), (perf["E25-S01-04"]["emotion"], perf["E25-S01-04"]["emotion_basis"]))
        self.assertEqual("急", perf["E25-S01-13"]["emotion"])  # 麒麟冲上一步 (the speaker's own action)
        lexicon = set(json.loads(spc.LEXICON_PATH.read_text(encoding="utf-8"))["emotions"])
        self.assertTrue(all(p["emotion"] in lexicon for p in perf.values()))
        period, score, _ = spk.periodicity([p["emotion"] for p in perf.values()])
        self.assertLess(score, 0.6)
        self.assertEqual(("怒", "explicit"), spc.derive_emotion("情绪=怒", "好。", "喜剧", "怒"))
        self.assertEqual("戏", spc.derive_emotion("", "好。", "争吵→喜剧")[0])  # the type's last word wins
        self.assertEqual("疑", spc.derive_emotion("", "你是谁？", "")[0])

    def test_fallback_is_marked(self):
        a = shot(self.c, "E25-S01-08")["prompt_spec"]["action"]  # 商余烬：私事。 (no action line)
        self.assertEqual("fallback", a["source"])
        self.assertEqual("fallback", a["field_sources"]["primary_action"])
        authored = [s["prompt_spec"]["action"] for s in self.c["shots"]
                    if s["prompt_spec"]["action"]["source"] == "screenplay"]
        self.assertGreaterEqual(len(authored), 8)
        for a in authored:  # no fallback in the action fields of an authored shot
            self.assertEqual("screenplay", a["field_sources"]["primary_action"])
            self.assertTrue(a.get("action_en"))

    def test_turn_push_and_beats(self):
        spec = shot(self.c, "E25-S01-11")["prompt_spec"]
        self.assertEqual(("DOLLY", "PUSH_IN", "TURN"), (spec["camera_plan"]["motion_family"],
                                                        spec["camera_plan"]["motion_direction"], spec["beat_role"]))
        self.assertIn("动机：", spec["camera_plan"]["motivation"])
        self.assertTrue(spec["double_meaning"])
        moving = [s for s in self.c["shots"] if s["prompt_spec"]["camera_plan"]["motion_family"] != "LOCKED"]
        self.assertEqual(1, len(moving))  # one push per scene
        self.assertEqual(["THREAT_ESCALATION", "IDENTITY_REVEAL", "CONFRONTATION", "REVERSAL"],
                         [b["type"] for b in self.c["pacing"]["beat_sheet"]])
        self.assertEqual("E25-S01-15", self.c["pacing"]["cliffhanger"]["shot_id"])
        self.assertEqual("ENDING", shot(self.c, "E25-S01-15")["prompt_spec"]["beat_role"])

    def test_wp1_wp5_wp6_fields(self):
        plan = self.c["pacing"]["scene_plan"][0]
        self.assertGreaterEqual(len(plan["source_detail_ids"]), 2)
        self.assertEqual(("comic_bounce", "E25-S01-12"), (plan["mood"], plan["music_stop"]))
        self.assertEqual(("E25-S01-11", "CHAR-SHANGYUJIN"), (plan["turn_shot_id"], plan["turn_owner"]))
        self.assertEqual(("日", "殿门逆光"), (plan["time_of_day"], plan["light"]))
        self.assertIn("妖皇宝座", plan["set_pieces"])
        self.assertEqual("MAIN", self.c["adaptation_plan"]["plot_events"][0]["role"])
        self.assertEqual(6, len(self.c["ledger"]))
        self.assertEqual(2, len(self.c["knowledge"]))
        names = {r["character_id"]: r for r in self.c["series_card"]["characters"]}
        self.assertEqual("翘着二郎腿转令牌", names["CHAR-BAITAODIJI"]["signature_business"])
        first = shot(self.c, "E25-S01-01")["prompt_spec"]
        self.assertEqual("CHAR-BAITAODIJI", first["signature_business"])
        self.assertEqual({"subject": "PROP", "of": "战神令", "then": "TILT_UP"}, first["object_first"])

    @unittest.skipUnless(SOURCE_TXT.is_file(), "novel text not on this machine")
    def test_source_details_are_in_chapter_226(self):
        text = SOURCE_TXT.read_text(encoding="utf-8", errors="ignore")
        start = text.index("三天的时间到了，你们的妖皇呢")
        chapter = "".join(text[start:start + 3000].split())
        for detail in self.c["pacing"]["scene_plan"][0]["source_detail_ids"]:
            self.assertIn(detail, chapter)


class EnglishTwinTest(unittest.TestCase):
    def test_missing_answers_request_rows_and_exit_3(self):
        with tempfile.TemporaryDirectory() as d:
            for f in FIXTURE.iterdir():
                if f.name != "E25_SCREENPLAY_EN.json":
                    shutil.copy(f, d)
            out = spc.compile_files(Path(d), "E25")
            self.assertEqual("NEEDS_EN", out["report"]["status"])
            rows = out["en_request"]["rows"]
            self.assertEqual(out["report"]["en_missing"], len(rows))
            self.assertTrue({"action", "delivery", "reaction", "prop"} <= {r["field"] for r in rows})
            self.assertEqual(spc.en_key(rows[0]["field"], rows[0]["zh"]), rows[0]["key"])
            self.assertEqual(3, spc.main(["E25", "--scripts-dir", d]))
            self.assertTrue((Path(d) / "E25_SCREENPLAY_EN_REQUEST.json").is_file())
            self.assertTrue((Path(d) / "E25_GENERATION_CONTRACT_v1.json").is_file())

    def test_entry_state_never_quotes_its_own_completion_or_action(self):
        # E27 (1101, 2026-11-24): the scene's opening action was both the "开场：" entry and the completion of
        # S01-01, so build_keyframe_manifest rejected the entry (COMPLETION_STATE_LEAK) and S5 blocked.
        for s in compiled()["contract"]["shots"]:
            entry = s["entry_state"]
            self.assertNotIn(s["completion_state"], entry, s["shot_id"])
            self.assertNotIn(s["frame_content"], entry, s["shot_id"])
        first = shot(compiled()["contract"], "E25-S01-01")
        self.assertIn("白桃帝姬翘着二郎腿", first["completion_state"])
        self.assertIn("已在场", first["entry_state"])

    def test_round_trip_write_and_reread(self):
        with tempfile.TemporaryDirectory() as d:
            for f in FIXTURE.iterdir():
                shutil.copy(f, d)
            self.assertEqual(0, spc.main(["E25", "--scripts-dir", d]))
            written = json.loads((Path(d) / "E25_GENERATION_CONTRACT_v1.json").read_text(encoding="utf-8"))
            self.assertEqual(compiled()["contract"], written)
            self.assertFalse(spc.needs_compile(Path(d), "E25"))
            self.assertFalse((Path(d) / "E25_SCREENPLAY_EN_REQUEST.json").exists())
            # a second compile keeps the first layers once as *.pre_compile
            self.assertEqual(0, spc.main(["E25", "--scripts-dir", d]))
            self.assertTrue((Path(d) / "E25_GENERATION_CONTRACT_v1.json.pre_compile").is_file())


class TranslationCycleTest(unittest.TestCase):
    """Missing English twins -> exactly those rows requested -> the writer fills them -> the contract passes WP4."""

    def test_missing_twin_request_fill_pass(self):
        from tools import bili_carry
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for f in FIXTURE.iterdir():
                shutil.copy(f, d)
            full = json.loads((d / "E25_SCREENPLAY_EN.json").read_text(encoding="utf-8"))
            dropped = sorted(full["rows"])[:3]
            partial = {**full, "rows": {k: v for k, v in full["rows"].items() if k not in dropped}}
            (d / "E25_SCREENPLAY_EN.json").write_text(json.dumps(partial, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(3, spc.main(["E25", "--scripts-dir", tmp]))
            request = json.loads((d / "E25_SCREENPLAY_EN_REQUEST.json").read_text(encoding="utf-8"))
            self.assertEqual(dropped, sorted(r["key"] for r in request["rows"]))  # exactly the missing ones
            contract = json.loads((d / "E25_GENERATION_CONTRACT_v1.json").read_text(encoding="utf-8"))
            self.assertTrue(bili_carry.en_twin_failures(contract))
            # the writer answers each row (here: the reference translation) and recompiles
            partial["rows"].update({r["key"]: full["rows"][r["key"]] for r in request["rows"]})
            (d / "E25_SCREENPLAY_EN.json").write_text(json.dumps(partial, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(0, spc.main(["E25", "--scripts-dir", tmp]))
            self.assertFalse((d / "E25_SCREENPLAY_EN_REQUEST.json").exists())
            contract = json.loads((d / "E25_GENERATION_CONTRACT_v1.json").read_text(encoding="utf-8"))
            self.assertEqual([], bili_carry.en_twin_failures(contract))

    def test_fallbacks_carry_compiler_english(self):
        a = shot(compiled()["contract"], "E25-S01-08")["prompt_spec"]["action"]  # 商余烬：私事。 (no action line)
        self.assertEqual("Shang Yujin says the line to Bai Tao", a["business_en"])
        self.assertEqual("fallback", a["field_sources"]["business_en"])
        b = shot(compiled()["contract"], "E25-S01-13")["prompt_spec"]["action"]["performance"]  # no parenthetical
        self.assertTrue(b["delivery_en"].startswith("urgent"))

    def test_codex_tick_resumes_three_times_spaced_then_falls_back(self):
        import codex_production as cxp
        blocker = "SCREENPLAY_EN_TRANSLATION_REQUIRED:abc123def456:3 (translate ...)"
        t0 = 1_000_000.0
        with unittest.mock.patch.object(cxp, "_s1_blockers", return_value=[blocker]):
            session: dict = {}
            self.assertEqual(("abc123def456", "RESUME"),
                             (cxp.translation_request_pending("E25", session, now=t0), cxp.translation_step("E25", session)))
            for i in range(3):
                session.setdefault("translation_resumes", {}).setdefault("abc123def456", []).append(t0 + i * 1800)
            # spaced: nothing within 30 min of the last resume
            self.assertEqual("", cxp.translation_request_pending("E25", session, now=t0 + 2 * 1800 + 60))
            with unittest.mock.patch.object(cxp.time, "time", return_value=t0 + 3 * 1800):
                self.assertEqual("FALLBACK", cxp.translation_step("E25", session))
            session["translation_fallback"] = ["abc123def456"]
            self.assertEqual("", cxp.translation_request_pending("E25", session, now=t0 + 10 * 1800))
        with tempfile.TemporaryDirectory() as tmp, \
                unittest.mock.patch.dict(os.environ, {"NALU_ENGINE_ROOT": tmp}):
            path = cxp.write_translation_fallback("E25", "abc123def456")
            self.assertEqual("abc123def456", json.loads(path.read_text(encoding="utf-8"))["key"])
            self.assertEqual("E25_SCREENPLAY_EN_FALLBACK.json", path.name)
        self.assertIn("SCREENPLAY_EN.json", cxp.TRANSLATION_REQUEST_MESSAGE)


class TranslationFallbackTest(unittest.TestCase):
    """3 unanswered resumes -> the tick's marker -> S1 proceeds on compiler English (never stall the line)."""

    def _setup(self, d: Path):
        import nalu_pipeline as npl
        for f in FIXTURE.iterdir():
            shutil.copy(f, d)
        full = json.loads((d / "E25_SCREENPLAY_EN.json").read_text(encoding="utf-8"))
        partial = {**full, "rows": {k: v for k, v in full["rows"].items() if k not in sorted(full["rows"])[:3]}}
        (d / "E25_SCREENPLAY_EN.json").write_text(json.dumps(partial, ensure_ascii=False), encoding="utf-8")
        p = SimpleNamespace(contract=d / "E25_GENERATION_CONTRACT_v1.json", episode="E25", logs=d / "logs",
                            state=d / "state.json")
        ctx = SimpleNamespace(episode="E25", p=p, craft_settings={"craft_profile": "BILI_V1", "bgm_mood_cues": False,
                                                                 "writer_format": "SCREENPLAY_V1"})
        return npl, ctx, p

    def test_tick_marker_lets_s1_proceed_on_fallback_english(self):
        from tools import bili_carry
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            npl, ctx, p = self._setup(d)
            row = npl.s1_screenplay_compile(ctx, p)
            self.assertTrue(row["blockers"][0].startswith(npl.SCREENPLAY_EN_TRANSLATION_REQUIRED))
            key = row["translation_request"]["key"]
            (d / "E25_SCREENPLAY_EN_FALLBACK.json").write_text(json.dumps({"key": key}), encoding="utf-8")
            row = npl.s1_screenplay_compile(ctx, p)
            self.assertEqual([], row["blockers"])
            self.assertEqual(("COMPILED", 3, "TICK_RESUMES_EXHAUSTED", "SCREENPLAY_EN_FALLBACK_USED:3"),
                             (row["status"], row["en_fallback_used"], row["en_fallback_basis"], row["marker"]))
            contract = json.loads(p.contract.read_text(encoding="utf-8"))
            self.assertEqual([], bili_carry.en_twin_failures(contract))
            marked = [s["shot_id"] for s in contract["shots"]
                      if any(k.endswith("_en") and v == "fallback"
                             for k, v in s["prompt_spec"]["action"]["field_sources"].items())]
            self.assertTrue(marked)
            # the next S1 run stays on the fallback (the marker still names the unanswered request)
            self.assertEqual([], npl.s1_screenplay_compile(ctx, p)["blockers"])

    def test_without_a_tick_s1_falls_back_after_repeated_unanswered_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            npl, ctx, p = self._setup(d)
            t0 = 2_000_000.0
            for i in range(npl.SCREENPLAY_EN_FALLBACK_EVALUATIONS - 1):
                with unittest.mock.patch.object(npl.time, "time", return_value=t0 + i * 1800):
                    self.assertTrue(npl.s1_screenplay_compile(ctx, p)["blockers"])
            with unittest.mock.patch.object(npl.time, "time", return_value=t0 + 3 * 1800):
                row = npl.s1_screenplay_compile(ctx, p)
            self.assertEqual(([], "S1_REQUEST_UNANSWERED"), (row["blockers"], row["en_fallback_basis"]))


class PipelinePreStepTest(unittest.TestCase):
    def _ctx(self, d: Path, writer_format: str | None):
        import nalu_pipeline as npl
        p = SimpleNamespace(contract=d / "E25_GENERATION_CONTRACT_v1.json", episode="E25",
                            logs=d / "logs", state=d / "state.json")
        settings = ({"craft_profile": "BILI_V1", "bgm_mood_cues": False, "writer_format": writer_format}
                    if writer_format else None)
        return npl, SimpleNamespace(episode="E25", p=p, **({"craft_settings": settings} if settings else {})), p

    def test_screenplay_v1_compiles_before_s1(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for f in FIXTURE.iterdir():
                shutil.copy(f, d)
            npl, ctx, p = self._ctx(d, "SCREENPLAY_V1")
            row = npl.s1_screenplay_compile(ctx, p)
            self.assertEqual("COMPILED", row["status"], row)
            self.assertEqual([], row["blockers"])
            self.assertTrue(p.contract.is_file())
            self.assertEqual("UP_TO_DATE", npl.s1_screenplay_compile(ctx, p)["status"])
            self.assertEqual({"series_card", "outline", "screenplay", "cast_props", "en_answers"},
                             set(npl.screenplay_input_paths(p)))
            answers = (d / "E25_SCREENPLAY_EN.json").read_text(encoding="utf-8")
            (d / "E25_SCREENPLAY_EN.json").unlink()
            os.utime(d / "E25_SCREENPLAY.md")
            row = npl.s1_screenplay_compile(ctx, p)
            # a translation request routed to the writer, never an S1 integrity round
            self.assertEqual(1, len(row["blockers"]))
            self.assertTrue(row["blockers"][0].startswith(npl.SCREENPLAY_EN_TRANSLATION_REQUIRED + ":"))
            self.assertFalse(row["blockers"][0].startswith(npl.S1_INTEGRITY_PREFIXES))
            self.assertEqual(row["en_missing"], row["translation_request"]["missing"])
            # the writer answers the request -> recompile -> clean
            (d / "E25_SCREENPLAY_EN.json").write_text(answers, encoding="utf-8")
            row = npl.s1_screenplay_compile(ctx, p)
            self.assertEqual(("COMPILED", []), (row["status"], row["blockers"]))

    def test_legacy_and_contract_json_are_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for f in FIXTURE.iterdir():
                shutil.copy(f, d)
            for wf in (None, "CONTRACT_JSON"):
                npl, ctx, p = self._ctx(d, wf)
                self.assertEqual({"status": "NOT_APPLICABLE"}, npl.s1_screenplay_compile(ctx, p))
                self.assertFalse(p.contract.exists())


class CodexPromptSectionTest(unittest.TestCase):
    def setUp(self):
        import codex_production as cxp
        self.cxp = cxp
        env = unittest.mock.patch.dict(os.environ, {"NALU_ENGINE_ROOT": str(ROOT)})
        env.start()
        self.addCleanup(env.stop)
        self.assertEqual(ROOT / "skills" / "nalu-claude-code" / "CLAUDE_CODE_PRODUCTION.md", cxp.contract_path())
        self.text = cxp.contract_path().read_text(encoding="utf-8")

    def test_section_is_kept_only_for_screenplay_v1(self):
        cxp = self.cxp
        self.assertIn(cxp.SCREENPLAY_V1_BEGIN, self.text)
        legacy = cxp.production_contract_text(writer_format="CONTRACT_JSON")
        begin, end = self.text.index(cxp.SCREENPLAY_V1_BEGIN), self.text.index(cxp.SCREENPLAY_V1_END)
        # LEGACY / CONTRACT_JSON: the contract without the block -- byte for byte what it was before WP2
        self.assertEqual(self.text[:begin] + self.text[end + len(cxp.SCREENPLAY_V1_END) + 1:], legacy)
        self.assertNotIn("SCREENPLAY_V1", legacy)
        bili = cxp.production_contract_text(writer_format="SCREENPLAY_V1")
        self.assertIn("screenplay_compile.py", bili)
        self.assertNotIn(cxp.SCREENPLAY_V1_BEGIN, bili)
        self.assertEqual(len(self.text) - len(cxp.SCREENPLAY_V1_BEGIN) - len(cxp.SCREENPLAY_V1_END) - 2, len(bili))

    def test_revise_message_legacy_unchanged(self):
        cxp = self.cxp
        with unittest.mock.patch.object(cxp, "writer_format_for", return_value="CONTRACT_JSON"):
            self.assertEqual(cxp.PACING_REVISE_MESSAGE, cxp.revise_message(cxp.PACING_REVISE_MESSAGE, "E25"))
        with unittest.mock.patch.object(cxp, "writer_format_for", return_value="SCREENPLAY_V1"):
            self.assertIn("screenplay_compile.py", cxp.revise_message(cxp.INTEGRITY_REVISE_MESSAGE, "E25"))


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
