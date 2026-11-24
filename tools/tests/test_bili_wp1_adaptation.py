"""BILI_V1 WP1: adaptation and episode allocation (CHANGE_SPEC WP1, owner 2026-11-23, Bilibili benchmark ep2/ep3).

Covers: the event cap replaces the minimum-events floor (ADAPTATION_TOO_DENSE; no ADAPTATION_TOO_THIN /
SINGLE_CHAPTER_EPISODE; the "deepen" fix texts), source-detail retention (>= 2 ids per scene, found in the source),
report-style lines <= 20 %, the anti-slogan check (advisory on round 0), reveal-name fidelity as an S1 integrity code
(E25: 商余烬天神 where the source says 容凌天神), the widened no-copy gate (every declared chapter of any work, active
from E01, <= 2 listed short source lines per scene), gate10 and the authoritative adaptation_plan chapters -- and that
a LEGACY series decides byte-identically to origin/main 4103b32.  Offline, no paid call."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "skills" / "nalu-claude-code" / "scripts",
           ROOT / "tools", ROOT, Path(__file__).resolve().parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import bili_adaptation_check as bili  # noqa: E402
import script_pacing_check as sp  # noqa: E402
from test_nalu_script_pacing import punchy_contract, slow_contract  # noqa: E402
from tools import dialogue_register_gate as drg  # noqa: E402
from tools import script_structure_contract_gate as ssg  # noqa: E402

SOURCE = ("三天期满。白桃坐在椅子上翘着二郎腿，眼神轻蔑。战雷拱手：请帝姬再宽限两日。白桃冷笑：把我当什么了？"
          "林岚把账本拍在桌上，一把抓住周默的手腕。周默攥紧了拳头，话到嘴边又咽了回去。天君颤声道：你是容凌天神！")
DETAILS = {f"E03-S0{i}": ["翘着二郎腿", "账本拍在桌上"] for i in range(1, 6)}


def bili_ok(lang: str = "zh") -> dict:
    """The punchy contract allocated BILI_V1-style: 1 main + 1 secondary event, 2 source details per scene."""
    c = punchy_contract(lang)
    c["craft_profile"] = "BILI_V1"
    c["adaptation_plan"]["plot_events"] = [{"event": "she takes the ledger back", "chapter": 3, "role": "MAIN"},
                                           {"event": "the sister's debt", "chapter": 3, "role": "SECONDARY"}]
    cards = [("逼战雷交出妖皇的下落", "战雷只会拱手求宽限", "她把令牌磕在扶手上"),
             ("从周默手里夺回账本", "周默把账本压在身下", "林岚一把抓住他的手腕"),
             ("让妹妹认下那笔欠债", "妹妹哭着不肯开口", "姐姐把欠条拍在桌上"),
             ("骗守卫打开后门", "守卫认出了她的玉佩", "她反手把玉佩塞进守卫掌心"),
             ("当众揭穿天君的身份", "天君抢先下令拿人", "天君颤声认出容凌")]
    for row, (goal, obstacle, turn) in zip(c["pacing"]["scene_plan"], cards):
        # each scene's own card (WP2 SCENE_CARD_REPEATED: a BILI_V1 contract's cards are pairwise distinct)
        row.update({"objective": goal, "conflict": obstacle, "physical_action": turn})
    for row in c["pacing"]["scene_plan"]:
        row["source_detail_ids"] = list(DETAILS[row["scene_id"]])
    return c


def codes(report: dict) -> set[str]:
    return {f.split(":", 1)[0] for f in report["failures"]}


class LegacyByteIdentityTest(unittest.TestCase):
    """LEGACY decisions are byte-identical to origin/main 4103b32 (goldens computed there)."""

    GOLDEN = {"slow_zh": "c4725bb000c4d64261f284c9a6ed275647dd71e61fe326ea5193ee897406c2bf",
              "slow_en": "c4725bb000c4d64261f284c9a6ed275647dd71e61fe326ea5193ee897406c2bf",
              "punchy_zh": "13a7abc719cb12f0ff9ed3278291b51a2db4f7709ca385c7642aeebbbced7df0"}
    BRIEF_SHA = "333ef90468fcd1d0573b7adfb9388d6c393bc12fdfb43c292ceb32336bdd3e13"

    def decisions(self, contract: dict, **kw) -> str:
        r = sp.evaluate(contract, source_texts=["他推开门，抓住她的手腕。"], **kw)
        d = {k: r[k] for k in ("status", "failures", "warnings", "integrity_failures", "fixes", "source_action_beats")}
        return hashlib.sha256(json.dumps(d, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def test_pacing_decisions_match_origin_main(self) -> None:
        for name, c in (("slow_zh", slow_contract("zh")), ("slow_en", slow_contract("en")),
                        ("punchy_zh", punchy_contract("zh"))):
            self.assertEqual(self.decisions(c), self.GOLDEN[name], name)
            self.assertEqual(self.decisions(c, craft_profile="LEGACY", revision_round=3), self.GOLDEN[name], name)
            report = sp.evaluate(c)
            self.assertNotIn("craft_profile", report)
            self.assertNotIn("bili_v1", report["metrics"])
            self.assertNotIn("bili_v1", sp.summary(report, None))

    def test_legacy_keeps_the_floor_and_single_chapter_warning(self) -> None:
        report = sp.evaluate(slow_contract("zh"))
        self.assertIn("ADAPTATION_TOO_THIN", codes(report))
        self.assertIn("SINGLE_CHAPTER_EPISODE", report["warnings"])

    def test_legacy_dispatch_template_is_unchanged(self) -> None:
        import codex_production as cp
        self.assertEqual(hashlib.sha256(cp.NEXT_EPISODE_BRIEF.encode()).hexdigest(), self.BRIEF_SHA)
        with tempfile.TemporaryDirectory() as d:
            self.assertIs(cp.next_episode_brief_template(Path(d), "E04"), cp.NEXT_EPISODE_BRIEF)
            Path(d, "qingshan.json").write_text(json.dumps({"project": {"craft_profile": "BILI_V1"}}))
            self.assertIs(cp.next_episode_brief_template(Path(d), "E04"), cp.NEXT_EPISODE_BRIEF_BILI_V1)
        bili_text = cp.NEXT_EPISODE_BRIEF_BILI_V1
        self.assertIn("1 个主事件", bili_text)
        self.assertNotIn("max(4", bili_text)
        bili_text.format(display=3, prev="p", ep="E02", nxt="E03", brief="b", done="d", status="s", skill="k",
                         coverage_cmd="py x coverage")

    def test_legacy_source_lookup_and_gates_unchanged(self) -> None:
        c = {"adaptation_plan": {"source_chapters": [2]}, "source_binding": {"source_file": "/nope/ch0002.md"}}
        self.assertEqual(sp.source_texts_for(c, None), sp.source_texts_for(c, None, craft_profile="LEGACY"))
        self.assertEqual(ssg.check_source_binding(c), ssg.check_source_binding(c, None))


class EventCapTest(unittest.TestCase):
    def test_event_cap_and_deepen_fix(self) -> None:
        c = punchy_contract("zh")                          # 6 plot events, no roles
        report = sp.evaluate(c, craft_profile="BILI_V1", source_texts=[SOURCE])
        self.assertEqual(report["craft_profile"], "BILI_V1")
        self.assertIn("ADAPTATION_TOO_DENSE:6>2(main=0,secondary=0)", report["failures"])
        self.assertIn("PLOT_EVENT_ROLE_MISSING:6", report["warnings"])
        self.assertIn("deepen", report["fixes"]["ADAPTATION_TOO_DENSE"] + report["fixes"].get("TOO_FEW_TURNS", "deepen"))
        slow = slow_contract("zh")
        r = sp.evaluate(slow, craft_profile="BILI_V1")
        self.assertNotIn("ADAPTATION_TOO_THIN", codes(r))
        self.assertNotIn("SINGLE_CHAPTER_EPISODE", r["warnings"])
        self.assertIn("TOO_FEW_TURNS", codes(r))           # turns are still required -- inside the scenes
        self.assertIn("not new plot events", r["fixes"]["TOO_FEW_TURNS"])
        self.assertNotIn("take the next chapters", r["fixes"]["TOO_FEW_TURNS"])
        two_main = bili_ok()
        two_main["adaptation_plan"]["plot_events"][1]["role"] = "MAIN"
        self.assertIn("ADAPTATION_TOO_DENSE", codes(sp.evaluate(two_main, craft_profile="BILI_V1",
                                                                 source_texts=[SOURCE])))

    def test_allocated_contract_passes(self) -> None:
        report = sp.evaluate(bili_ok(), source_texts=[SOURCE])   # the contract declares BILI_V1 itself
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(report["integrity_failures"], [])
        self.assertEqual(report["metrics"]["bili_v1"]["events"]["main"], 1)
        self.assertIn("bili_v1", sp.summary(report, None))


class SourceDetailTest(unittest.TestCase):
    def test_source_details_required_and_found(self) -> None:
        c = bili_ok()
        c["pacing"]["scene_plan"][0]["source_detail_ids"] = ["翘着二郎腿"]
        c["pacing"]["scene_plan"][1]["source_detail_ids"] = ["翘着 二郎腿！", "她把茶杯摔碎"]
        report = sp.evaluate(c, source_texts=[SOURCE])
        self.assertIn("SOURCE_DETAIL_MISSING:E03-S01", report["failures"])
        self.assertIn("SOURCE_DETAIL_NOT_IN_SOURCE:她把茶杯摔碎", report["failures"])
        self.assertNotIn("SOURCE_DETAIL_NOT_IN_SOURCE:翘着 二郎腿！", report["failures"])  # punctuation-insensitive
        self.assertIn("SOURCE_DETAIL_MISSING", report["fixes"])
        self.assertTrue(report["source_action_beats"])                 # source candidates suggested in the fix
        # without a source text only the count is checked
        r = sp.evaluate(c)
        self.assertIn("SOURCE_TEXT_UNAVAILABLE", r["warnings"])
        self.assertNotIn("SOURCE_DETAIL_NOT_IN_SOURCE", codes(r))
        # a taste code: the bounded revision loop admits it after MAX_REVISIONS
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "rounds.json"
            for i in range(sp.MAX_REVISIONS):
                self.assertEqual(sp.decide(report, f"sha{i}", path)["decision"], "REVISE")
            self.assertEqual(sp.decide(report, "shaX", path)["decision"], "ADMITTED_AFTER_REVISIONS")
            self.assertEqual(sp.prior_failing_rounds(path, "shaX"), sp.MAX_REVISIONS)


class ReportLineTest(unittest.TestCase):
    def test_report_line_share(self) -> None:
        c = bili_ok()
        reports = ["探子：十万天兵已经压境。", "探子：城门已被攻破。", "探子：据说北营失守。"]
        speaking = [s for s in c["shots"] if s["prompt_spec"].get("dialogue")]
        for s, line in zip(speaking, reports * 3):
            s["prompt_spec"]["dialogue"] = line
        report = sp.evaluate(c, source_texts=[SOURCE])
        over = [f for f in report["failures"] if f.startswith("REPORT_LINES_OVER:")]
        self.assertTrue(over, report["failures"])
        lex = bili.report_lexicon("zh")
        self.assertEqual(bili.classify_line({"text": "你敢再说一遍？"}, "zh", lex, []), "SPEECH")
        self.assertEqual(bili.classify_line({"text": "师兄，别把自己送进陷阱。"}, "zh", lex, []), "SPEECH")
        self.assertEqual(bili.classify_line({"text": "十万天兵已经压境。"}, "zh", lex, []), "REPORT")
        self.assertEqual(bili.classify_line({"text": "我回来了。", "tag_report": True}, "zh", lex, []), "REPORT")
        self.assertEqual(bili.classify_line({"text": "账本已经烧了。"}, "zh", lex, ["账本"]), "SPEECH")
        # the writer's (交代) tag is read and stripped from the line
        line = bili.spoken_lines({"shots": [{"shot_id": "A", "scene_id": "S", "prompt_spec": {
            "dialogue": "探子：（交代）三日后开战。"}}]}, "zh")[0]
        self.assertTrue(line["tag_report"])
        self.assertEqual(line["text"], "三日后开战。")


class SloganTest(unittest.TestCase):
    def test_slogan_advisory_then_taste(self) -> None:
        c = bili_ok()
        c["shots"][1]["prompt_spec"]["dialogue"] = "林岚：今天不让任何人替我们低头。"
        first = sp.evaluate(c, source_texts=[SOURCE])
        self.assertIn(f"SLOGAN_LINE:{c['shots'][1]['shot_id']}", first["warnings"])
        self.assertNotIn("SLOGAN_LINE", codes(first))
        later = sp.evaluate(c, source_texts=[SOURCE], revision_round=1)
        self.assertIn("SLOGAN_LINE", codes(later))
        # anchored in the scene's source details -> not a slogan
        c["pacing"]["scene_plan"][0]["source_lines"] = ["谁也不许低头"]
        self.assertNotIn("SLOGAN_LINE", codes(sp.evaluate(c, source_texts=[SOURCE], revision_round=1)))


class RevealFidelityTest(unittest.TestCase):
    def e25_like(self, line: str, **spec) -> dict:
        c = bili_ok()
        c["character_entities"] = [{"character_id": "C1", "canonical_name": "商余烬", "aliases": []},
                                   {"character_id": "C2", "canonical_name": "天君", "aliases": []}]
        c["shots"][1]["prompt_spec"]["dialogue"] = f"天君：{line}"
        c["shots"][1]["prompt_spec"].update(spec)
        return c

    def test_reveal_name_fidelity_is_integrity(self) -> None:
        c = self.e25_like("你是……商余烬天神！")
        sid = c["shots"][1]["shot_id"]
        report = sp.evaluate(c, source_texts=[SOURCE])
        self.assertIn(f"REVEAL_NAME_NOT_IN_SOURCE:{sid}:商余烬天神", report["integrity_failures"])
        self.assertEqual(report["integrity_status"], "FAIL")
        self.assertIn("REVEAL_NAME_NOT_IN_SOURCE", report["fixes"])
        blockers = sp.integrity_blocker_codes(report)
        self.assertIn(f"SCRIPT_INTEGRITY_FAIL:REVEAL_NAME_NOT_IN_SOURCE:{sid}:商余烬天神", blockers)
        import nalu_pipeline as npl
        self.assertTrue(all(b.startswith(npl.S1_INTEGRITY_PREFIXES) for b in blockers))  # bounded loop, then admit
        self.assertEqual(sp.evaluate(self.e25_like("你是……容凌天神！"), source_texts=[SOURCE])["integrity_failures"],
                         [])
        # tagged reveal: every canonical name must be in the source
        tagged = self.e25_like("商余烬回来了。", beat_role="REVEAL")
        self.assertIn(f"REVEAL_NAME_NOT_IN_SOURCE:{sid}:商余烬", sp.evaluate(tagged, source_texts=[SOURCE])[
            "integrity_failures"])
        # not a reveal: a question, or "谁才是"
        for line in ("你是谁？", "让他们先看清谁才是妖皇。"):
            self.assertEqual(sp.evaluate(self.e25_like(line), source_texts=[SOURCE])["integrity_failures"], [], line)
        # no source text: nothing to check against
        self.assertEqual(sp.evaluate(c)["integrity_failures"], [])
        # LEGACY never runs it
        legacy = copy.deepcopy(c)
        legacy.pop("craft_profile")
        self.assertEqual(sp.evaluate(legacy, source_texts=[SOURCE])["integrity_failures"], [])


class SourceTextsTest(unittest.TestCase):
    def test_bili_lookup_reads_every_declared_chapter_of_any_work(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            work = Path(d, "sources", "造孽啊", "as_delivered")
            work.mkdir(parents=True)
            Path(d, "sources", "造孽啊", "SOURCE_INDEX.json").write_text("{}")
            for n, text in ((26, "第二十六章 白桃翘着二郎腿。"), (27, "第二十七章 你是容凌天神！")):
                (work / f"ch{n:04d}.md").write_text(text, encoding="utf-8")
            c = {"adaptation_plan": {"source_chapters": [26, 27]},
                 "source_binding": {"source_chapters": ["1"], "work": "造孽啊"}}
            texts = sp.source_texts_for(c, Path(d), craft_profile="BILI_V1")
            self.assertEqual(len(texts), 2)
            self.assertIn("容凌天神", texts[1])
            # the plan is authoritative; the binding is only the fallback
            self.assertEqual(bili.declared_chapters({"source_binding": {"source_chapters": ["26"]}}), [26])

    def test_structure_gate_adaptation_plan_is_authoritative(self) -> None:
        e25 = {"adaptation_plan": {"source_chapters": [21, 22, 23, 24, 25]},
               "source_binding": {"source_chapters": ["26", "27"], "source_file": "/x/ch0026.md"}}
        out = ssg.check_source_binding(e25, "BILI_V1")
        self.assertTrue(any(f.startswith("SOURCE_BINDING_CHAPTERS_NOT_IN_ADAPTATION_PLAN") for f in out["failures"]))
        self.assertTrue(any(f.startswith("SOURCE_FILE_NOT_IN_ADAPTATION_PLAN:ch0026.md") for f in out["failures"]))
        e25["adaptation_plan"]["source_chapters"] = [26, 27]
        self.assertEqual(ssg.check_source_binding(e25, "BILI_V1")["failures"], [])
        self.assertEqual(ssg.check_source_binding(e25, "BILI_V1")["measurements"]["authority"], "adaptation_plan")


class DialogueRegisterBiliTest(unittest.TestCase):
    def contract(self) -> dict:
        return {"episode": "E03", "dialogue_language": "zh",
                "pacing": {"scene_plan": [{"scene_id": "E03-S01", "source_lines": ["请帝姬再宽限两日", "把我当什么了"]}]},
                "shots": [{"shot_id": f"E03-S01-0{i}", "scene_id": "E03-S01",
                           "prompt_spec": {"dialogue": f"战雷：{t}"}}
                          for i, t in enumerate(["请帝姬再宽限两日。", "把我当什么了？", "白桃坐在椅子上翘着二郎腿，眼神轻蔑。"], 1)]}

    def test_verbatim_allowance_per_scene(self) -> None:
        c = self.contract()
        lines = drg.lines_from_contract(c)
        legacy = drg.analyse(lines, SOURCE)
        self.assertEqual(legacy["failures"], ["DIALOGUE_SOURCE_VERBATIM:2"])   # 2 of 3 lines share >= 8 chars
        self.assertNotIn("verbatim_allowed", legacy)
        allowed = drg.analyse(lines, SOURCE, allowance=drg.verbatim_allowance(c, "zh"))
        self.assertEqual(len(allowed["verbatim_allowed"]), 1)                # the listed short line
        self.assertEqual(allowed["failures"], ["DIALOGUE_SOURCE_VERBATIM:1"])  # the unlisted long one still fails
        c["pacing"]["scene_plan"][0]["source_lines"].append("白桃坐在椅子上翘着二郎腿，眼神轻蔑")
        allowed = drg.analyse(drg.lines_from_contract(c), SOURCE, allowance=drg.verbatim_allowance(c, "zh"))
        self.assertEqual(allowed["failures"], ["DIALOGUE_SOURCE_VERBATIM:1"])  # listed but longer than 12 chars
        cap = drg.verbatim_allowance(c, "zh")
        cap["per_scene"] = 0
        self.assertEqual(drg.analyse(drg.lines_from_contract(c), SOURCE, allowance=cap)["verbatim_allowed"], [])

    def run_gate(self, c: dict, *extra: str) -> dict:
        with tempfile.TemporaryDirectory() as d:
            cpath, out = Path(d, "c.json"), Path(d, "out.json")
            cpath.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
            a, b = Path(d, "ch1.md"), Path(d, "ch2.md")
            a.write_text(SOURCE[:40], encoding="utf-8")
            b.write_text(SOURCE[40:], encoding="utf-8")
            args = [sys.executable, str(ROOT / "tools/dialogue_register_gate.py"), "--contract", str(cpath),
                    "--out", str(out)]
            args += [x.replace("{a}", str(a)).replace("{b}", str(b)) for x in extra]
            subprocess.run(args, capture_output=True, text=True, check=False)
            return json.loads(out.read_text(encoding="utf-8"))

    def test_active_from_e01_under_profile(self) -> None:
        c = self.contract()
        self.assertEqual(self.run_gate(c, "--source", "{a}")["status"], "NOT_ACTIVE")      # LEGACY: from E15
        report = self.run_gate(c, "--source", "{a}", "--craft-profile", "BILI_V1")
        self.assertNotEqual(report["status"], "NOT_ACTIVE")
        self.assertEqual(report["craft_profile"], "BILI_V1")

    def test_multi_chapter_source_lookup(self) -> None:
        c = self.contract()
        c["shots"][0]["prompt_spec"]["dialogue"] = "天君：颤声道你是容凌天神"      # only in the second chapter
        c["pacing"]["scene_plan"][0]["source_lines"] = []
        one = self.run_gate(c, "--source", "{a}", "--craft-profile", "BILI_V1")
        both = self.run_gate(c, "--source", "{a}", "--source", "{b}", "--craft-profile", "BILI_V1")
        self.assertGreater(len(both["verbatim"]), len(one["verbatim"]))
        # the pipeline concatenates the declared chapters of any work into one file
        import nalu_pipeline as npl
        with tempfile.TemporaryDirectory() as d:
            work = Path(d, "sources", "别的作品", "as_delivered")
            work.mkdir(parents=True)
            Path(d, "sources", "别的作品", "SOURCE_INDEX.json").write_text("{}")
            (work / "ch0007.md").write_text("第七章", encoding="utf-8")
            (work / "ch0008.md").write_text("第八章", encoding="utf-8")
            contract = Path(d, "c.json")
            contract.write_text(json.dumps({"adaptation_plan": {"source_chapters": [7, 8]}}), encoding="utf-8")
            p = SimpleNamespace(contract=contract, logs=Path(d, "logs"))
            with mock.patch.object(npl, "RUNTIME", Path(d)):
                path = npl.s1_dialogue_register_source(SimpleNamespace(run_id="R1"), p)
            self.assertIn("第七章", path.read_text(encoding="utf-8"))
            self.assertIn("第八章", path.read_text(encoding="utf-8"))


class Gate10Test(unittest.TestCase):
    GATE = ROOT / "agent_factory/claude_writer_v2/gates/writer_scene_source_declaration_gate.py"

    def run_gate10(self, manifest: dict, contract: dict | None, *extra: str) -> int:
        with tempfile.TemporaryDirectory() as d:
            m, c = Path(d, "m.json"), Path(d, "c.json")
            m.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            c.write_text(json.dumps(contract or {}, ensure_ascii=False), encoding="utf-8")
            args = [sys.executable, str(self.GATE), str(m), "--warn-is-fail"]
            args += [x.replace("{c}", str(c)) for x in extra]
            return subprocess.run(args, capture_output=True, text=True).returncode

    def test_gate10_accepts_source_detail_ids_and_never_blocks_under_bili(self) -> None:
        manifest = {"episode": "E99", "version": "v1", "structure": [{"scene_id": "E99-S01"}, {"scene_id": "E99-S02"}],
                    "beat_disposition": [], "★authorized_insertions": []}
        contract = {"pacing": {"scene_plan": [{"scene_id": "E99-S01", "source_detail_ids": ["翘着二郎腿", "拱手"]}]}}
        self.assertEqual(self.run_gate10(manifest, contract), 1)                                    # LEGACY: fails
        self.assertEqual(self.run_gate10(manifest, contract, "--craft-profile", "BILI_V1", "--contract", "{c}"), 0)
        sys.path.insert(0, str(self.GATE.parent))
        import writer_scene_source_declaration_gate as g10
        with tempfile.TemporaryDirectory() as d:
            m, c = Path(d, "m.json"), Path(d, "c.json")
            m.write_text(json.dumps(manifest), encoding="utf-8")
            c.write_text(json.dumps(contract), encoding="utf-8")
            r = g10.audit(str(m), "BILI_V1", str(c))
        self.assertEqual(r["scenes_from_source"], ["E99-S01"])
        self.assertEqual(r["status"], "PASS")
        self.assertTrue(r["warnings"][0].startswith("UNSOURCED_AND_UNDECLARED_SCENES_ADVISORY:E99-S02"))


class PipelineWiringTest(unittest.TestCase):
    def test_s1_passes_the_profile_only_under_bili(self) -> None:
        src = (ROOT / "lines/nalu/runtime/tools/nalu_pipeline.py").read_text(encoding="utf-8")
        body = src[src.index("def stage_s1("):src.index("def s1_dialogue_register_source(")]
        self.assertIn('["--craft-profile", "BILI_V1", "--contract", p.contract] if ctx_craft_profile(ctx) == "BILI_V1"',
                      body)
        self.assertIn('RUNTIME / "sources" / "夜无疆" / "zh-CN"', body)               # LEGACY lookup kept

    def test_script_too_short_deepen_text_under_bili(self) -> None:
        import nalu_pipeline as npl
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            contract = d / "contract.json"
            contract.write_text(json.dumps({"shots": [{"target_seconds": 4.0}] * 10}), encoding="utf-8")
            (d / "briefs").mkdir()
            (d / "briefs" / "E24_PRODUCTION_BRIEF.json").write_text(json.dumps({"target_seconds": 110}))
            out = {}
            for profile in ("LEGACY", "BILI_V1"):
                ctx = SimpleNamespace(episode="E24", p=SimpleNamespace(contract=contract), craft_profile=profile)
                with mock.patch.object(npl, "RUNTIME", d), mock.patch.object(npl, "_camera_grammar_on", lambda _c: True), \
                        mock.patch.object(npl, "s1_pacing_in_flight", lambda _p: False):
                    out[profile] = npl.script_length_check(ctx)["integrity_blocker"]
        self.assertIn("adapt more plot events", out["LEGACY"])
        self.assertTrue(out["BILI_V1"].startswith("SCRIPT_TOO_SHORT:40.0s<93.5s"))
        self.assertIn("deepen the scenes you have", out["BILI_V1"])
        self.assertIn("do not add plot events", out["BILI_V1"])


class TextsTest(unittest.TestCase):
    def test_docs_carry_the_bili_rule(self) -> None:
        for rel, needle in (("skills/nalu-claude-code/CLAUDE_CODE_PRODUCTION.md", "1 个主事件"),
                            ("skills/nalu-claude-code/SKILL.md", "1 个主事件"),
                            ("docs/knowledge/H3_SCRIPT_ADAPTATION_GUIDE.md", "1 个主事件"),
                            ("agent_factory/claude_writer_v2/templates/NARRATIVE_CANONICAL.template.md", "1 个主事件"),
                            ("lines/nalu/standards/NALU_CRAFT_STANDARD_v1.md", "1 个主事件"),
                            ("agent_factory/storyclaw_portable/WRITER_CONTRACT.md", "1 main + ≤1 secondary"),
                            ("agent_factory/claude_writer_v2/docs/CHARTER.md", "BILI_V1")):
            self.assertIn(needle, (ROOT / rel).read_text(encoding="utf-8"), rel)
        for name in ("REPORT_LINE_PATTERNS_V1.json", "SLOGAN_PATTERNS_V1.json"):
            data = json.loads((ROOT / "configs" / name).read_text(encoding="utf-8"))
            self.assertEqual(set(data["languages"]), {"zh", "en", "ja", "ko"})
        policy = json.loads((ROOT / "configs/DIALOGUE_REGISTER_V1.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["enabled_from_episode"], "E15")
        self.assertEqual(policy["enabled_from_episode_by_profile"]["BILI_V1"], "E01")
        self.assertEqual(policy["verbatim_allowance_per_scene"], 2)


if __name__ == "__main__":
    unittest.main()
