"""SHORT_DRAMA_PACING_V1 (line owner 2026-11-22: 「剧情推进太慢……一集基本就是人物在念台词」).

Covers: the deterministic script metrics on a slow (one chapter, all talk) vs a punchy contract in zh and en; the
bounded revision loop (rounds per distinct failing script, same bytes never use a round, admitted after two
revisions or on a stalled re-run, inactive contracts are advisory); S1 integration (blocks only an opted-in contract
whose other gates passed, records the metrics and the source coverage); source coverage across episodes; the
dispatch / contract / writer texts carry the rules; the tick resumes a session that stopped on a revision request
once per round; the final review and Gemini pass D receive the script plan.  Offline, no paid call."""
from __future__ import annotations

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


CAST = [{"character": "林岚", "character_id": "CHAR-LIN"}, {"character": "周默", "character_id": "CHAR-ZHOU"}]


def shot(sid: str, scene: str, seconds: float, dialogue: str = "", dims=("POSTURE",), beat_role: str = "",
         blocking: str = "", cast=None, location: str = "", family: str = "LOCKED", scale: str = "MEDIUM",
         props=None) -> dict:
    spec = {"shot_id": sid, "dialogue": dialogue, "cast": list(CAST if cast is None else cast),
            "camera_plan": {"motion_family": family, "shot_scale": scale}}
    if props:
        spec["props"] = list(props)
    if location:
        spec["space"] = {"location": location}
    if beat_role:
        spec["beat_role"] = beat_role
    return {"shot_id": sid, "scene_id": scene, "target_seconds": seconds, "state_delta_dimensions": list(dims),
            "blocking": blocking, "prompt_spec": spec}


def slow_contract(lang: str = "zh") -> dict:
    """One chapter, two scenes of people standing and talking, long explanatory lines, a resolved ending."""
    if lang == "zh":
        lines = ["林岚：你知道吗，自从三年前爸爸生病以后，我们家就一直很困难，我每天都在想办法。我真的很累。",
                 "林岚：我等了你整整三年。", "林岚：所以我才来找你。", "周默：好，我答应你。"]
    else:
        lines = ["Lin: As you know, ever since the accident last winter, this house has felt different. I keep "
                 "thinking about it every single night. I am so tired.",
                 "Lin: I waited for you three whole years.", "Lin: That is why I came to you.",
                 "Zhou: All right, I agree."]
    shots, t = [], 0
    for i in range(24):
        scene = "E02-S01" if i < 12 else "E02-S02"
        shots.append(shot(f"E02-S0{1 if i < 12 else 2}-{i + 1:02d}", scene, 4.8, lines[i % 4],
                          dims=("POSTURE",) if i % 3 else ("POSITION",), blocking="林岚站在桌边，抬起右手。",
                          location="LOC-HOUSE"))
        t += 4.8
    return {"schema": "qingshan.generation_contract.v3", "episode": "E02", "dialogue_language": lang,
            "pacing_policy": sp.POLICY, "pacing": {"hook": {"type": "dialogue", "at_seconds": 4.5}},
            "adaptation_plan": {"source_chapters": [2], "plot_events": [{"event": "she asks him for help"}]},
            "shots": shots}


def punchy_contract(lang: str = "zh") -> dict:
    """~115 s, 5 scenes, a turn every ~20 s, short lines, physical action in every scene, open ending."""
    zh = ["林岚：钱呢？", "周默：花了。", "林岚：给谁？", "周默：你妹妹。", "林岚：你敢再说一遍？", "周默：门锁了吗——"]
    en = ["Lin: Where is the money?", "Zhou: Spent.", "Lin: On whom?", "Zhou: Your sister.",
          "Lin: Say that again.", "Zhou: Did you lock the door—"]
    lines = zh if lang == "zh" else en
    grab = "林岚一把抓住周默的手腕。" if lang == "zh" else "Lin grabs Zhou's wrist."
    snatch = "周默夺过账本塞进怀里。" if lang == "zh" else "Zhou snatches the ledger and runs to the door."
    shots, beat_sheet, scene_plan = [], [], []
    n = 0
    for s in range(5):
        scene = f"E03-S0{s + 1}"
        location = ("LOC-OFFICE", "LOC-STREET", "LOC-CAR")[s % 3]
        scene_plan.append({"scene_id": scene, "objective": "get the ledger", "conflict": "he hides it",
                           "physical_action": "she grabs it"})
        for k in range(6):
            n += 1
            sid = f"{scene}-{k + 1:02d}"
            if k == 0 and s:
                # each new place is SHOWN (an arrival / establishing beat): the move is motivated, not a relocated
                # conversation (JA-01 E08)
                shots.append(shot(sid, scene, 4.0, "", dims=("POSITION",), beat_role="TRANSITION",
                                  blocking=("林岚走进" if lang == "zh" else "Lin walks in") , location=location,
                                  scale="WIDE"))
            elif k in (1, 4):
                shots.append(shot(sid, scene, 3.5, lines[n % len(lines)], dims=("CONTACT",), blocking=grab,
                                  location=location))
            elif k == 2:
                shots.append(shot(sid, scene, 4.0, "", dims=("POSSESSION",), beat_role="PAYOFF", blocking=snatch,
                                  location=location, family="HANDHELD"))
                beat_sheet.append({"shot_id": sid, "type": sp.TURN_TYPES[s % len(sp.TURN_TYPES)],
                                   "setup_shot_id": f"{scene}-01"})
            elif k == 3:
                shots.append(shot(sid, scene, 3.0, "", dims=("POSTURE",), beat_role="REACTION", cast=[],
                                  props=["ledger"], scale="INSERT", location=location))
            else:
                shots.append(shot(sid, scene, 4.0, lines[n % len(lines)], dims=("POSTURE",),
                                  blocking="林岚盯着他。" if lang == "zh" else "Lin stares at him.", location=location))
    shots[-1]["prompt_spec"]["dialogue"] = lines[-1]
    return {"schema": "qingshan.generation_contract.v3", "episode": "E03", "dialogue_language": lang,
            "pacing_policy": sp.POLICY,
            "pacing": {"hook": {"type": "dialogue", "at_seconds": 0.5, "line_or_shot_id": shots[0]["shot_id"]},
                       "beat_sheet": beat_sheet, "scene_plan": scene_plan,
                       "cliffhanger": {"shot_id": shots[-1]["shot_id"], "open_question": "who opened the door?"}},
            "adaptation_plan": {"source_chapters": [3, 4, 5],
                                "plot_events": [{"event": f"event {i}", "chapter": 3 + i // 2} for i in range(6)],
                                "cut": ["the walk to town", "the aunt"]},
            "shots": shots}


class MetricsTest(unittest.TestCase):
    def test_slow_script_fails_on_every_pacing_axis(self) -> None:
        for lang in ("zh", "en"):
            report = sp.evaluate(slow_contract(lang))
            codes = {c.split(":", 1)[0] for c in report["failures"]}
            self.assertEqual(report["status"], "FAIL", lang)
            self.assertTrue(report["active"])
            for code in ("FIRST_CONFLICT_LATE", "TOO_FEW_TURNS", "TURN_GAP_TOO_LONG", "DIALOGUE_ONLY_TOO_HIGH",
                         "LINE_TOO_LONG", "BACK_TO_BACK_MONOLOGUE", "SCENE_PLAN_MISSING", "ENDING_NOT_OPEN",
                         "ADAPTATION_TOO_THIN"):
                self.assertIn(code, codes, (lang, report["failures"]))
            m = report["metrics"]
            self.assertEqual(m["turn_count"], 0)
            self.assertGreater(m["dialogue_only_ratio"], 0.6)
            self.assertGreater(m["longest_line"]["units"], m["line_unit_cap"])
            self.assertIn("SINGLE_CHAPTER_EPISODE", report["warnings"])
            for code in codes:                                   # every failure comes with a fix line
                self.assertIn(code, report["fixes"])

    def test_punchy_script_passes(self) -> None:
        for lang in ("zh", "en", "ja", "ko"):
            report = sp.evaluate(punchy_contract("zh" if lang in ("zh", "ja") else "en"), language=lang
                                 if lang in ("zh", "en") else None)
            self.assertEqual(report["status"], "PASS", (lang, report["failures"]))
        m = sp.evaluate(punchy_contract("zh"))["metrics"]
        self.assertGreaterEqual(m["turn_count"], m["required_turns"])
        self.assertLessEqual(m["first_conflict_at"], 3.0)
        self.assertLessEqual(m["max_turn_gap_seconds"], 30.0)
        self.assertLessEqual(m["dialogue_only_ratio"], 0.6)
        self.assertTrue(m["ending"]["unresolved"])
        self.assertEqual(m["adaptation"]["source_chapter_count"], 3)
        self.assertAlmostEqual(m["beats_per_minute"], round(5 * 60 / m["duration_seconds"], 2))

    def test_talk_only_scene_and_unknown_turn_type(self) -> None:
        c = punchy_contract("zh")
        for s in c["shots"]:
            if s["scene_id"] == "E03-S02":
                s["blocking"] = "林岚抬头看他。"  # gestures only: the scene shows no physical action
        c["pacing"]["beat_sheet"].append({"shot_id": c["shots"][0]["shot_id"], "type": "VIBES"})
        report = sp.evaluate(c)
        self.assertIn("SCENE_TALK_ONLY:E03-S02", report["failures"])
        self.assertIn("TURN_TYPE_UNKNOWN:VIBES", report["warnings"])

    def test_ending_falls_back_to_an_open_last_line(self) -> None:
        c = punchy_contract("en")
        del c["pacing"]["cliffhanger"]
        self.assertTrue(sp.measure(c)["ending"]["unresolved"])               # "Did you lock the door—"
        c["shots"][-1]["prompt_spec"]["dialogue"] = "Zhou: Fine. Goodnight."
        self.assertFalse(sp.measure(c)["ending"]["unresolved"])

    def test_line_caps_are_per_language(self) -> None:
        self.assertEqual(sp.line_unit_cap("zh"), 28)
        self.assertEqual(sp.line_unit_cap("en"), 20)
        self.assertEqual(sp.line_unit_cap("ja"), 44)
        self.assertEqual(sp.line_unit_cap("ko"), 36)
        c = punchy_contract("en")
        c["shots"][1]["prompt_spec"]["dialogue"] = ("Zhou: " + "word " * 22).strip()
        self.assertTrue(any(c.startswith("LINE_TOO_LONG") for c in sp.evaluate(c)["failures"]))

    def test_inactive_contract_is_advisory(self) -> None:
        c = slow_contract()
        c["pacing_policy"] = "OFF"                                         # explicit opt-out only
        report = sp.evaluate(c)
        self.assertFalse(report["active"])
        self.assertEqual((report["authority"], report["policy_basis"]), ("ADVISORY_NOT_A_GATE", "OPT_OUT"))
        self.assertFalse(sp.evaluate(slow_contract(), environ={sp.ENV_SWITCH: "off"})["active"])

    def test_policy_is_the_default_without_a_key(self) -> None:
        """E07 (device 1485, 2026-11-22): the contract had no pacing_policy key -> advisory -> no revision."""
        c = slow_contract()
        del c["pacing_policy"]
        report = sp.evaluate(c)
        self.assertTrue(report["active"])
        self.assertEqual((report["policy_basis"], report["authority"]), ("DEFAULT", "WRITER_REVISION_LOOP"))
        for off in ("off", "NONE", "legacy", False):
            self.assertFalse(sp.evaluate({**c, "pacing_policy": off})["active"], off)
        # an episode already past a paid stage is grandfathered under the default, never under a declared policy
        grand = sp.evaluate(c, in_flight=True)
        self.assertFalse(grand["active"])
        self.assertEqual(grand["grandfathered"], "IN_FLIGHT_PAST_PAID_STAGE")
        self.assertTrue(sp.evaluate(slow_contract(), in_flight=True)["active"])
        self.assertFalse(sp.evaluate({"shots": []})["active"])              # nothing to revise

    def test_top_level_pacing_scene_plan_is_read(self) -> None:
        """E07: Codex wrote pacing_scene_plan at the top level; the check reported SCENE_PLAN_MISSING:4."""
        c = punchy_contract("zh")
        c["pacing_scene_plan"] = c["pacing"].pop("scene_plan")
        report = sp.evaluate(c)
        self.assertEqual(report["metrics"]["scene_plan_missing"], [], report["failures"])
        self.assertEqual(report["status"], "PASS", report["failures"])
        c2 = punchy_contract("zh")
        c2["pacing_cliffhanger"] = c2["pacing"].pop("cliffhanger")
        c2["pacing"]["scene_plan"] = c2["pacing"]["scene_plan"][:2]
        c2["pacing_scene_plan"] = punchy_contract("zh")["pacing"]["scene_plan"]   # lists merged, no duplicates
        self.assertEqual(len(sp.pacing_block(c2)["scene_plan"]), 5)
        self.assertTrue(sp.measure(c2)["ending"]["unresolved"])

    def test_self_declared_action_labels_do_not_count(self) -> None:
        """E07: every speaking shot labelled MOMENTUM/CONTACT -> dialogue_only_ratio 0.00 while the cut was
        'almost everything is characters talking, the scene barely changes'.  The storyboard decides."""
        shots = []
        for i in range(28):
            scene = f"E07-S0{1 + i // 7}"
            shots.append(shot(f"{scene}-{i:02d}", scene, 5.0, f"林岚：第{i}句。", dims=("MOMENTUM", "CONTACT"),
                              blocking="林岚身体前倾，右臂抬至腰侧。", location="LOC-HALL"))
        c = {"shots": shots, "dialogue_language": "zh"}
        m = sp.measure(c)
        self.assertEqual(m["dialogue_only_ratio_declared"], 0.0)
        self.assertEqual(m["dialogue_only_ratio"], 1.0)
        self.assertEqual(m["visual_action_ratio"], 0.0)
        self.assertEqual(m["shot_kinds"]["TALKING_HEAD"]["shots"], 28)
        self.assertEqual(m["location_count"], 1)
        report = sp.evaluate(c)
        codes = {f.split(":", 1)[0] for f in report["failures"]}
        for code in ("DIALOGUE_ONLY_TOO_HIGH", "VISUAL_ACTION_TOO_LOW", "VISUAL_BEATS_TOO_FEW", "VISUAL_VARIETY_LOW",
                     "SCENE_TALK_ONLY"):
            self.assertIn(code, codes, report["failures"])
            self.assertIn(code, report["fixes"])
        self.assertTrue(any(w.startswith("DECLARED_ACTION_NOT_IN_STORYBOARD") for w in report["warnings"]))

    def test_shot_kinds_from_the_storyboard(self) -> None:
        kind = sp.shot_kind
        self.assertEqual(kind(shot("a", "s", 3, blocking="林岚一把推开周默。"), True), "TALK_WITH_ACTION")
        self.assertEqual(kind(shot("a", "s", 3, blocking="Lin hands over the letter."), True), "TALK_WITH_ACTION")
        self.assertEqual(kind(shot("a", "s", 3, blocking="林岚向前跨出一步，镜头推近。"), True), "TALKING_HEAD")
        self.assertEqual(kind(shot("a", "s", 3, blocking="林岚转身走向门口。"), False), "ACTION")
        self.assertEqual(kind(shot("a", "s", 3, cast=[], props=["信"]), False), "INSERT")
        self.assertEqual(kind(shot("a", "s", 3, cast=[]), False), "ESTABLISHING")
        self.assertEqual(kind(shot("a", "s", 3, scale="WIDE"), False), "ESTABLISHING")
        self.assertEqual(kind(shot("a", "s", 3, family="TRACK"), False), "MOVEMENT")
        self.assertEqual(kind(shot("a", "s", 3, beat_role="TRANSITION"), False), "TRANSITION")
        self.assertEqual(kind(shot("a", "s", 3, blocking="林岚望着他。"), False), "STATIC_REACTION")

    def test_scene_changes(self) -> None:
        c = punchy_contract("zh")
        for s in c["shots"]:
            s["prompt_spec"]["space"] = {"location": "LOC-OFFICE"}
        failures = sp.evaluate(c)["failures"]
        # one place under five scene_ids, no time skip: the scenes are one scene (merge) ...
        self.assertIn("SCENE_SPLIT_SAME_LOCATION:E03-S01>E03-S02", failures)
        # ... but the in-place variety (action, inserts, movement) still satisfies the visual-variety target
        self.assertFalse(any(f.startswith("VISUAL_VARIETY_LOW") for f in failures), failures)
        for i, s in enumerate(c["shots"]):                          # one place, but night falls: a time change
            s["prompt_spec"]["scene_state"] = {"time": "day" if i < 15 else "night"}
        changes = sp.measure(c)["scene_changes"]
        self.assertEqual([c["kind"] for c in changes][1:3], ["SAME_PLACE_SPLIT", "MOTIVATED_TIME_CHANGE"])
        two = {"shots": [shot(f"x{i}", "S1" if i < 20 else "S2", 6.0, "", cast=[], location=f"L{i // 20}")
                         for i in range(23)]}
        self.assertTrue(sp.measure(two)["scene_changes"][0]["motivated"])  # a new place opened on its establishing view

    def test_source_action_beats_are_suggested(self) -> None:
        source = ("林岚走进院子。「你来做什么？」周默问。她一把夺过他手里的账本，转身冲出门去。\n"
                  "夜里下起了雨。周默摔碎了茶杯。")
        beats = sp.source_action_beats([source], "zh")
        self.assertEqual(beats, ["她一把夺过他手里的账本，转身冲出门去。", "周默摔碎了茶杯。"])
        shots = [shot(f"x{i}", "S1", 5.0, "林岚：说。", blocking="林岚站着。") for i in range(20)]
        report = sp.evaluate({"shots": shots}, source_texts=[source])
        self.assertEqual(report["source_action_beats"], beats)
        self.assertIn("账本", report["fixes"]["SOURCE_ACTION_BEATS"])
        self.assertEqual(sp.evaluate(punchy_contract(), source_texts=[source])["source_action_beats"], [])
        rt = Path(tempfile.mkdtemp())
        work = rt / "sources" / "书" / "as_delivered"
        work.mkdir(parents=True)
        (rt / "sources" / "书" / "SOURCE_INDEX.json").write_text(json.dumps({"canonical_reading_script":
                                                                          "as_delivered"}), encoding="utf-8")
        (work / "ch0029.md").write_text(source, encoding="utf-8")
        texts = sp.source_texts_for({"adaptation_plan": {"source_chapters": [29, 30]}, "shots": shots}, rt)
        self.assertEqual(texts, [source])
        self.assertEqual(sp.source_texts_for({"shots": shots}, rt), [])


class RevisionLoopTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rounds = Path(tempfile.mkdtemp()) / "SCRIPT_PACING_ROUNDS.json"

    def step(self, contract: dict, record: bool = True) -> dict:
        report = sp.evaluate(contract)
        return sp.decide(report, sp.contract_sha(contract), self.rounds, record=record)

    def test_two_revisions_then_admitted(self) -> None:
        draft = slow_contract()
        d1 = self.step(draft)
        self.assertEqual((d1["decision"], d1["revision_round"], d1["blocks"]), ("REVISE", 1, True))
        self.assertEqual(self.step(draft)["revision_round"], 1)             # same bytes: same round
        rev1 = {**slow_contract(), "title": "rev1"}
        d2 = self.step(rev1)
        self.assertEqual((d2["decision"], d2["revision_round"]), ("REVISE", 2))
        rev2 = {**slow_contract(), "title": "rev2"}
        d3 = self.step(rev2)
        self.assertEqual((d3["decision"], d3["blocks"], d3["reason"]),
                         ("ADMITTED_AFTER_REVISIONS", False, "REVISIONS_EXHAUSTED"))
        self.assertEqual(len(json.loads(self.rounds.read_text())["rounds"]), 3)

    def test_revision_that_passes_ends_the_loop(self) -> None:
        self.assertEqual(self.step(slow_contract())["decision"], "REVISE")
        self.assertEqual(self.step(punchy_contract())["decision"], "PASS")

    def test_stalled_rerun_of_the_same_bytes_is_admitted(self) -> None:
        draft = slow_contract()
        decisions = [self.step(draft)["decision"] for _ in range(sp.STALL_EVALUATIONS + 1)]
        self.assertEqual(decisions[:sp.STALL_EVALUATIONS], ["REVISE"] * sp.STALL_EVALUATIONS)
        self.assertEqual(decisions[-1], "ADMITTED_AFTER_REVISIONS")

    def test_unrecorded_rounds_do_not_count(self) -> None:
        for i in range(4):  # another S1 gate failed: reported, never counted
            self.step({**slow_contract(), "title": f"v{i}"}, record=False)
        self.assertFalse(self.rounds.exists())
        self.assertEqual(self.step(slow_contract())["revision_round"], 1)

    def test_blocker_codes(self) -> None:
        report = sp.evaluate(slow_contract())
        decision = self.step(slow_contract())
        codes = sp.blocker_codes(report, decision)
        self.assertEqual(codes[0], "SCRIPT_PACING_REVISE:round=1/2")
        self.assertTrue(all(c.startswith("SCRIPT_PACING_REVISE:") for c in codes))
        self.assertEqual(sp.blocker_codes(report, {"blocks": False}), [])

    def test_advisory_never_blocks_or_records(self) -> None:
        c = slow_contract()
        c["pacing_policy"] = "OFF"
        d = self.step(c)
        self.assertEqual((d["decision"], d["blocks"]), ("ADVISORY", False))
        self.assertFalse(self.rounds.exists())


class CoverageTest(unittest.TestCase):
    def test_coverage_progresses_through_the_book(self) -> None:
        rt = Path(tempfile.mkdtemp())
        self.assertIsNone(sp.coverage(rt)["next_chapter"])
        e1 = punchy_contract()
        e1["adaptation_plan"]["source_chapters"] = [1, 2, 3]
        sp.record_coverage(rt, "E01", e1)
        e2 = punchy_contract()
        e2["adaptation_plan"]["source_chapters"] = [4, 6]
        cov = sp.record_coverage(rt, "E02", e2)
        self.assertEqual((cov["last_chapter"], cov["next_chapter"], cov["skipped_chapters"]), (6, 7, [5]))
        e2["adaptation_plan"]["source_chapters"] = [4, 5]                  # re-recording replaces the row
        cov = sp.record_coverage(rt, "E02", e2)
        self.assertEqual((cov["next_chapter"], cov["skipped_chapters"]), (6, []))
        self.assertEqual(cov["episodes"]["E02"]["plot_event_count"], 6)
        self.assertEqual(sp.record_coverage(rt, "E03", {"shots": []}), {})  # no plan: nothing recorded
        self.assertNotIn("E03", sp.coverage(rt)["episodes"])

    def test_cli(self) -> None:
        rt = Path(tempfile.mkdtemp())
        path = rt / "c.json"
        path.write_text(json.dumps(slow_contract()), encoding="utf-8")
        self.assertEqual(sp.main(["check", "--contract", str(path), "--out", str(rt / "r.json")]), 0)
        self.assertEqual(sp.main(["check", "--contract", str(path), "--strict"]), 3)
        self.assertEqual(json.loads((rt / "r.json").read_text())["status"], "FAIL")
        self.assertEqual(sp.main(["coverage", "--runtime-root", str(rt)]), 0)


class S1IntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        import nalu_pipeline as npl
        self.npl = npl
        self.tmp = Path(tempfile.mkdtemp())
        self.ctx = SimpleNamespace(episode="E03", run_id="r1", language="zh")

    def run_s1(self, contract: dict, others_ok: bool = True):
        path = self.tmp / "contract.json"
        path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
        p = SimpleNamespace(contract=path, logs=self.tmp / "logs")
        with mock.patch.object(self.npl, "RUNTIME", self.tmp / "runtime"):
            return self.npl.s1_script_pacing(self.ctx, p, others_ok=others_ok)

    def test_opted_in_failing_script_gets_a_revision_request(self) -> None:
        row, blockers = self.run_s1(slow_contract())
        self.assertEqual(row["decision"], "REVISE")
        self.assertEqual(blockers[0], "SCRIPT_PACING_REVISE:round=1/2")
        self.assertIn("writer_instruction", row)
        self.assertTrue(Path(row["report"]).is_file())
        self.assertFalse((self.tmp / "runtime" / "series" / "SOURCE_COVERAGE.json").exists())

    def test_other_gate_failing_reports_without_blocking_or_counting(self) -> None:
        row, blockers = self.run_s1(slow_contract(), others_ok=False)
        self.assertEqual((row["decision"], blockers), ("PENDING_OTHER_S1_GATES", []))
        self.assertFalse((self.tmp / "logs" / "SCRIPT_PACING_ROUNDS.json").exists())

    def test_passing_script_records_metrics_and_coverage(self) -> None:
        row, blockers = self.run_s1(punchy_contract())
        self.assertEqual((row["decision"], blockers), ("PASS", []))
        self.assertEqual(row["metrics"]["turn_count"], 5)
        self.assertEqual(row["source_coverage"]["next_chapter"], 6)

    def test_opted_out_contract_is_untouched(self) -> None:
        c = slow_contract()
        c["pacing_policy"] = "OFF"
        row, blockers = self.run_s1(c)
        self.assertEqual((row["decision"], blockers), ("ADVISORY", []))
        self.assertEqual(row["status"], "FAIL")                             # metrics still recorded

    def test_default_policy_revises_a_new_episode(self) -> None:
        """E07: no pacing_policy key -> SCRIPT_PACING_REVISE now fires (round 1 of 2)."""
        c = slow_contract()
        del c["pacing_policy"]
        row, blockers = self.run_s1(c)
        self.assertEqual((row["decision"], row["policy_basis"]), ("REVISE", "DEFAULT"))
        self.assertEqual(blockers[0], "SCRIPT_PACING_REVISE:round=1/2")

    def test_default_policy_grandfathers_an_episode_past_a_paid_stage(self) -> None:
        c = slow_contract()
        del c["pacing_policy"]
        state = self.tmp / "state.json"
        state.write_text(json.dumps({"stages": {"S1": {"status": "PASS"}, "S5": {"status": "PASS"}}}), encoding="utf-8")
        path = self.tmp / "contract.json"
        path.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
        p = SimpleNamespace(contract=path, logs=self.tmp / "logs", state=state)
        with mock.patch.object(self.npl, "RUNTIME", self.tmp / "runtime"):
            row, blockers = self.npl.s1_script_pacing(self.ctx, p, others_ok=True)
        self.assertEqual((row["decision"], blockers, row["grandfathered"]), ("ADVISORY", [], "IN_FLIGHT_PAST_PAID_STAGE"))
        state.write_text(json.dumps({"stages": {"S4": {"status": "DRY_PLANNED"}, "S5": {"status": "NOT_RUN"}}}),
                         encoding="utf-8")
        self.assertFalse(self.npl.s1_pacing_in_flight(p))

    def test_broken_contract_never_raises(self) -> None:
        path = self.tmp / "missing.json"
        p = SimpleNamespace(contract=path, logs=self.tmp / "logs")
        row, blockers = self.npl.s1_script_pacing(self.ctx, p, others_ok=True)
        self.assertEqual(blockers, [])

    def test_stage_s1_wires_the_check(self) -> None:
        src = (ROOT / "lines/nalu/runtime/tools/nalu_pipeline.py").read_text(encoding="utf-8")
        body = src[src.index("def stage_s1("):src.index("def dialogue_register_blockers(")]
        self.assertIn("s1_script_pacing(\n        ctx, p, others_ok=(status == PASS and", body)
        self.assertIn('res.details["script_pacing"] = script_pacing', body)


class TextsTest(unittest.TestCase):
    def test_dispatch_templates_carry_the_rules(self) -> None:
        import codex_production as cp
        brief = cp.NEXT_EPISODE_BRIEF
        for needle in ("pacing_policy: SHORT_DRAMA_PACING_V1", "改编预算", "{coverage_cmd}", "next_chapter",
                       "不按章节", "≤3 秒"):
            self.assertIn(needle, brief)
        skill = (ROOT / "skills/nalu-claude-code/SKILL.md").read_text(encoding="utf-8")
        section = skill[skill.index("## 4. 派单"):skill.index("## 5.")]
        for needle in ("改编预算", "pacing_policy: SHORT_DRAMA_PACING_V1", "script_pacing_check.py coverage", "2–5 章"):
            self.assertIn(needle, section)

    def test_contract_writer_contract_and_standard(self) -> None:
        contract = (ROOT / "skills/nalu-claude-code/CLAUDE_CODE_PRODUCTION.md").read_text(encoding="utf-8")
        for needle in ("SHORT_DRAMA_PACING_V1", "SCRIPT_PACING_REVISE", "adaptation_plan", "pacing.beat_sheet",
                       "pacing.scene_plan", "pacing.cliffhanger", "授权你改写原著", "不报 BLOCKED"):
            self.assertIn(needle, contract)
        writer = (ROOT / "agent_factory/storyclaw_portable/WRITER_CONTRACT.md").read_text(encoding="utf-8")
        for needle in ("SHORT_DRAMA_PACING_V1", "plot events, not chapters", "SCRIPT_PACING_REVISE"):
            self.assertIn(needle, writer)
        standard = (ROOT / "lines/nalu/standards/NALU_CRAFT_STANDARD_v1.md").read_text(encoding="utf-8")
        self.assertIn("## 3b. 剧本阶段免费测量与改稿", standard)
        guide = (ROOT / "docs/knowledge/H3_SCRIPT_ADAPTATION_GUIDE.md").read_text(encoding="utf-8")
        self.assertIn("按剧情事件取材", guide)
        schema = json.loads((ROOT / "agent_factory/claude_writer_v2/schemas/generation_contract.schema.json")
                            .read_text(encoding="utf-8"))
        self.assertEqual(schema["properties"]["pacing_policy"]["enum"][0], sp.POLICY)
        self.assertIn("OFF", schema["properties"]["pacing_policy"]["enum"])
        self.assertIn("beat_sheet", schema["properties"]["pacing"]["properties"])
        self.assertIn("pacing_scene_plan", schema["properties"])           # the E07 spelling is an accepted alias
        template = json.loads((ROOT / "agent_factory/claude_writer_v2/templates/GENERATION_CONTRACT.template.json")
                              .read_text(encoding="utf-8"))
        self.assertEqual(template["pacing_policy"], sp.POLICY)
        self.assertIn("scene_plan", template["pacing"])                     # normalised spelling: inside pacing
        self.assertEqual(sp.policy_basis(template), "DECLARED")

    def test_next_episode_brief_formats(self) -> None:
        import codex_production as cp
        text = cp.NEXT_EPISODE_BRIEF.format(display=3, prev="p", ep="E02", nxt="E03", brief="b", done="d",
                                            status="s", skill="k", coverage_cmd="py x coverage")
        self.assertIn("py x coverage", text)


class TickTest(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = dict(os.environ)
        self.runtime = Path(tempfile.mkdtemp()) / "nalu_runtime"
        os.environ.update(NALU_ENGINE_ROOT=str(ROOT), NALU_RUNTIME_ROOT=str(self.runtime))
        import codex_production as cp
        self.cp = cp

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.saved)

    def state(self, blockers: list[str]) -> None:
        path = self.runtime / "runtime" / "pipeline_state" / "E03.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"stages": {"S1": {"status": "BLOCKED", "blockers": blockers}}}), encoding="utf-8")

    def test_pending_round_once_per_round(self) -> None:
        self.state(["SCRIPT_PACING_REVISE:round=1/2", "SCRIPT_PACING_REVISE:TOO_FEW_TURNS:0<4"])
        self.assertEqual(self.cp.pacing_revision_pending("E03", {}), "round=1/2")
        self.assertEqual(self.cp.pacing_revision_pending("E03", {"pacing_revise_resumed": ["round=1/2"]}), "")
        self.state(["SCRIPT_PACING_REVISE:round=2/2"])
        self.assertEqual(self.cp.pacing_revision_pending("E03", {"pacing_revise_resumed": ["round=1/2"]}),
                         "round=2/2")
        self.state(["STATIC_DESIGN_GATE_FAIL:x"])
        self.assertEqual(self.cp.pacing_revision_pending("E03", {}), "")
        self.assertIn("不要报 BLOCKED", self.cp.PACING_REVISE_MESSAGE)

    def test_tick_resumes_a_session_blocked_on_a_revision_request(self) -> None:
        self.state(["SCRIPT_PACING_REVISE:round=1/2"])
        d = self.cp.run_dir("E03")
        d.mkdir(parents=True, exist_ok=True)
        log = d / "codex.log"
        log.write_text("", encoding="utf-8")
        self.cp.write_json(d / "session.json", {"engine": "codex", "log": str(log), "pid": None})
        (self.runtime / "series").mkdir(parents=True, exist_ok=True)
        (self.runtime / "series" / "CURRENT_EPISODE").write_text("E03\n", encoding="utf-8")
        calls = []
        with mock.patch.object(self.cp, "parse_log", return_value={"nalu_status": {"state": "BLOCKED"}}), \
                mock.patch.object(self.cp, "publish_next", return_value=None), \
                mock.patch.object(self.cp, "engine_modification", return_value=None), \
                mock.patch.object(self.cp, "resume", side_effect=lambda ep, msg: calls.append(msg) or
                                  {"status": "STARTED"}):
            first = self.cp.tick(system=True)
            second = self.cp.tick(system=True)
        self.assertEqual(len(calls), 1)
        self.assertIn("resume_pacing_revision:round=1/2:STARTED", first["did"])
        self.assertNotIn("resume_pacing_revision", " ".join(second["did"]))


class ReviewContextTest(unittest.TestCase):
    def test_final_review_reads_the_script_record(self) -> None:
        import final_audience_review as far
        rt = Path(tempfile.mkdtemp())
        row = {**sp.summary(sp.evaluate(punchy_contract()), {"decision": "PASS", "revision_round": 0})}
        path = rt / "runtime" / "pipeline_state" / "E03.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"stages": {"S1": {"details": {"script_pacing": row}}}}), encoding="utf-8")
        with mock.patch.object(far, "RUNTIME", rt):
            ctx = far.script_pacing_context("E03")
            self.assertEqual(ctx["metrics"]["turn_count"], 5)
            self.assertIn("PLAN", ctx["basis"])
            self.assertEqual(far.script_pacing_context("E99"), {})

    def test_gemini_pass_d_shows_the_plan_separately(self) -> None:
        import gemini_review_passes as gp
        prompt = gp.build_pass_prompt("D", duration=110.0, context={}, measured_pacing={
            "mean_shot_seconds": 2.4, "script_plan": {"metrics": {"turn_count": 2}, "failures": ["TOO_FEW_TURNS"]}})
        self.assertIn("剧本阶段计划的节奏", prompt)
        self.assertIn("成片上量出来的节奏数据", prompt)
        self.assertIn("TOO_FEW_TURNS", prompt)
        plain = gp.build_pass_prompt("D", duration=110.0, context={}, measured_pacing={"mean_shot_seconds": 2.4})
        self.assertNotIn("剧本阶段计划的节奏", plain)


if __name__ == "__main__":
    unittest.main()
