"""Plan parity in the NALU final review (2026-11-23, device 1101 E24: everything shipped although the delivered shots
did not match the plan -- wrong locations, reversed roles, invented people, missing beats, 56 s vs 110 s).

Offline: Gemini is a fake ``post``, the transcoder writes bytes; no ffmpeg, no network, no credits.

Covers: pass D's prompt carries the per-unit plan (generation contract + release timeline); local OCR text runs and
the ASR of planned-silent units are pass A / C suspects; ``unit_parity`` parsing and the merged ``plan_parity``;
routing of P0 NO units into the final fix round (paid PLAN_MISMATCH, a trigger, ranked with the P0s); the per-unit
parity record (final_cut_shot_plan_parity, final_fix_round.json, fleet note, checkpoint); the objective defects and
the owner's release policy (2026-11-23, option iii): hold the X2C release only for runtime < 0.85 x target or
unresolved burned text that is not ACCEPT_CORRECT, never stall the line (redo backlog, publisher skips the episode,
the tick moves on), env override."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
for entry in (str(TOOLS), str(ROOT / "tools"), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import final_cut_shot_plan_parity as fcp  # noqa: E402
import final_fix_round as ffr  # noqa: E402
import gemini_review_passes as mp  # noqa: E402
import gemini_video_review as gvr  # noqa: E402
import nalu_knowledge_events as kb  # noqa: E402
import nalu_pipeline as P  # noqa: E402
import nalu_qa_defect_checklist as qa  # noqa: E402
from tools.tests.test_nalu_final_fix_round import SEGMENTS, _Ctx, checklist, sha  # noqa: E402

EP = "E24"


def _shot(sid, cast, action, dialogue="", loc="LOC-ANCHENG-ROUGE-SHOP", props=None):
    return {"shot_id": sid, "location_id": loc, "target_seconds": 4,
            "prompt_spec": {"cast": [{"character": n, "character_id": c} for n, c in cast], "dialogue": dialogue,
                            "action": {"primary_action": action}, "props": props or []}}


CONTRACT = {"episode": EP, "shots": [
    _shot("E24-S01-01", [("凌瑶", "CHAR-LINGYAO")], "Lingyao presses a dagger to Wang Defa throat.",
          "凌瑶：你说认识龙夜澈？那就把他找出来。", loc="LOC-ANCHENG-TEAHOUSE", props=[{"name": "dagger"}]),
    _shot("E24-S01-02", [("王德发", "CHAR-WANGDEFA")], "Wang Defa raises both hands and backs away.",
          "王德发：女侠饶命！", loc="LOC-ANCHENG-TEAHOUSE"),
    _shot("E24-S03-01", [("凌瑶", "CHAR-LINGYAO")], "Lingyao looks down at a fresh skeleton on a fishing boat.",
          loc="LOC-RIVER-FISHING-BOAT"),
    _shot("E24-S05-05", [("百姓", "CHAR-CROWD")], "The crowd closes ranks around the captive."),
]}
GROUPING = {"units": [{"unit_id": f"E24-VU-00{i + 1}", "scene_id": f"E24-S0{i + 1}", "editorial_shot_ids": [sid],
                       "narrative_beat": beat}
                      for i, (sid, beat) in enumerate((("E24-S01-01", "凌瑶逼问王德发"), ("E24-S01-02", "王德发求饶"),
                                                       ("E24-S03-01", "发现尸骨"), ("E24-S05-05", "百姓合围")))]}
TIMELINE = {"content_runtime_seconds": 12.0, "segments": [   # VU-004 never made the cut
    {"unit_id": "E24-VU-001", "output_start": 0.0, "output_end": 3.5},
    {"unit_id": "E24-VU-002", "output_start": 3.5, "output_end": 7.0},
    {"unit_id": "E24-VU-003", "output_start": 7.0, "output_end": 12.0}]}
#: final-cut ASR: VU-001's line, its tail spilling into VU-002, and a stray voice inside the planned-silent VU-003
ASR = [{"start": 0.2, "end": 3.6, "text": "你说认识龙夜澈？那就把他找出来。",
        "words": [{"w": "你说认识龙夜澈", "s": 0.2, "e": 2.0}, {"w": "那就把他找出", "s": 2.1, "e": 3.3},
                  {"w": "来", "s": 3.3, "e": 3.6}]},
       {"start": 3.8, "end": 5.5, "text": "女侠饶命！"},
       {"start": 8.0, "end": 9.4, "text": "丁师兄去死吧", "words": [{"w": "丁师兄", "s": 8.0, "e": 8.6},
                                                                    {"w": "去死吧", "s": 8.7, "e": 9.4}]}]


def _episode(root: Path) -> Path:
    work = root / EP
    pre, asm = work / "preproduction", work / "assembly"
    for d in (pre, asm):
        d.mkdir(parents=True)
    (pre / f"{EP}_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps(GROUPING), encoding="utf-8")
    (pre / f"{EP}_GENERATION_CONTRACT_v1.json").write_text(json.dumps(CONTRACT), encoding="utf-8")
    (asm / f"{EP}_release_timeline.json").write_text(json.dumps(TIMELINE), encoding="utf-8")
    return work


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _request(root: Path, pack_summary: dict) -> Path:
    video = root / f"{EP}_final_9x16.mp4"
    video.write_bytes(b"final-video")
    pack = root / f"{EP}_AV_EVIDENCE_PACK.json"
    pack.write_text(json.dumps({"summary": pack_summary}), encoding="utf-8")
    asr = root / f"{EP}_FINAL_CUT_ASR_WINDOWS.json"
    asr.write_text(json.dumps(ASR, ensure_ascii=False), encoding="utf-8")
    req = root / "final_audience_request.json"
    req.write_text(json.dumps({
        "episode": EP, "media": {"path": str(video), "sha256": _digest(video)},
        "objective_summary": {"duration_seconds": 12.0},
        "evidence": {"av_evidence_pack": {"path": str(pack), "sha256": _digest(pack)},
                     "asr": {"path": str(asr), "sha256": _digest(asr)}},
        "qa_defect_checklist_request": {"measurements": {}}}), encoding="utf-8")
    return req


PACK = {"burned_text_runs": [{"window": [7.5, 8.2], "text": "不姒伴", "garbled": True}],
        "stacked_subtitle_runs": [{"window": [4.0, 5.0], "texts": ["女侠饶命！", "女侠饶命！"], "similarity": 1.0}]}

D_ANSWER = {"findings": [], "craft_summary": {"opening_hook": {"at": 0.0, "ok": False}},
            "unit_parity": [
                {"unit": "VU-001", "delivered": "NO", "reasons": ["role reversed", "WRONG_LOCATION"],
                 "seen": "刀架在角色A自己脖子上，野外凉亭", "pacing": "ok"},
                {"unit": "2", "delivered": "yes", "reasons": []},
                {"unit": "VU-003", "delivered": "PARTIAL", "reasons": ["MISSING_PROP", "bogus"],
                 "seen": "桌上一个玩具骷髅，没有船", "severity": "P2"}],
            "verdict": "REJECT_RECUT"}
A_ANSWER = {"findings": [], "suspect_checks": [{"id": "S1", "decision": "DISMISSED", "reason": "只有我方字幕"},
                                               {"id": "S2", "decision": "CONFIRMED", "reason": "乱码字"}]}
C_ANSWER = {"findings": [], "suspect_checks": [{"id": "S3", "decision": "CONFIRMED", "reason": "听到男声"}]}
ANSWERS = {"PICTURE_AI_ARTEFACTS": A_ANSWER, "IDENTITY_CONTINUITY": {"findings": []}, "SOUND": C_ANSWER,
           "DIRECTOR_CRAFT": D_ANSWER}


def _post(captured: list):
    def post(url, body, headers, timeout):
        data = json.loads(body)
        prompt = data["contents"][0]["parts"][-1]["text"]
        name = next(k for k in ANSWERS if f"（{k}）" in prompt)
        captured.append({"name": name, "prompt": prompt})
        payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(ANSWERS[name], ensure_ascii=False)}]}}],
                   "usageMetadata": {"promptTokenCount": 10000, "candidatesTokenCount": 900,
                                     "thoughtsTokenCount": 600, "totalTokenCount": 11500}}
        return 200, json.dumps(payload).encode()
    return post


def _transcode(video, out, **kw):
    out.write_bytes(b"x" * 100)
    return out


class _Review(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        sleeper = mock.patch.object(mp.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)
        self.context = mp.episode_context(EP, work_root=_episode(self.root))
        self.captured: list = []
        self.record = gvr.run(request_path=_request(self.root, PACK), out=self.root / "gemini_review.json",
                              post=_post(self.captured), transcoder=_transcode,
                              environ={"HOPSAPI_API_KEY": "k", "NALU_ENGINE_ROOT": str(ROOT)},
                              context=self.context)
        self.prompts = {c["name"]: c["prompt"] for c in self.captured}

    def tearDown(self):
        self.tmp.cleanup()


# ===================================================================================== 1. the plan in the prompt
class PlanPromptTest(_Review):
    def test_plan_units_come_from_the_contract_anonymised_with_windows(self):
        units = {u["unit"]: u for u in self.context["plan_units"]}
        self.assertEqual(list(units), ["VU-001", "VU-002", "VU-003", "VU-004"])
        one = units["VU-001"]
        self.assertEqual((one["start"], one["end"], one["location"]), (0.0, 3.5, "ancheng teahouse"))
        self.assertEqual(one["cast"], ["角色A"])
        self.assertEqual(one["action"], "角色A presses a dagger to 角色B throat.")   # romanised names too
        self.assertEqual(one["props"], ["dagger"])
        self.assertEqual(one["dialogue"], ["角色A：你说认识龙夜澈？那就把他找出来。"])
        self.assertTrue(units["VU-003"]["silent"])
        self.assertIsNone(units["VU-004"]["start"])                                # not in the cut
        text = json.dumps([{k: v for k, v in u.items() if k != "_lines"} for u in units.values()], ensure_ascii=False)
        for name in ("凌瑶", "王德发", "Lingyao", "Wang Defa"):
            self.assertNotIn(name, text)

    def test_pass_d_prompt_carries_per_unit_plan_and_asks_unit_parity(self):
        d = self.prompts["DIRECTOR_CRAFT"]
        for text in ("逐单元计划", '"unit":"VU-001"', '"where":"ancheng teahouse"', "presses a dagger",
                     '"props":["dagger"]', "fishing boat", "无台词", "unit_parity", "ROLE_REVERSED", "WRONG_LOCATION",
                     "INVENTED_PERSON", "MISSING_BEAT", "QA-PLAN-MISMATCH"):
            self.assertIn(text, d)
        self.assertNotIn("VU-004", d)                       # a unit not in the cut is decided locally
        self.assertNotIn('"beats"', d)                      # the per-unit rows replace the beat rows
        self.assertNotIn("unit_parity", self.prompts["PICTURE_AI_ARTEFACTS"])

    def test_local_ocr_and_silent_unit_asr_are_suspects_to_confirm(self):
        a, c = self.prompts["PICTURE_AI_ARTEFACTS"], self.prompts["SOUND"]
        self.assertIn('"burned_text"', a)
        self.assertIn("不姒伴", a)
        self.assertIn("字幕带", a)
        self.assertNotIn("本地 OCR 线索", a)                 # no longer a mere lead
        self.assertIn('"stray_voice"', c)
        self.assertIn("丁师兄去死吧", c)
        self.assertNotIn("找出来", c.split('"stray_voice"')[1])   # a planned line spilling over a cut is not stray
        checks = {s["id"]: s for s in self.record["suspect_checks"]}
        self.assertEqual(checks["S1"]["suspect"]["kind"], "burned_text")
        self.assertEqual(checks["S1"]["decision"], "DISMISSED")
        self.assertEqual(checks["S3"]["suspect"]["kind"], "stray_voice")
        self.assertEqual(checks["S3"]["suspect"]["unit"], "VU-003")

    def test_stray_voice_skips_planned_lines_and_short_noise(self):
        units = self.context["plan_units"]
        spill = [{"start": 3.6, "end": 4.4, "text": "找出来"}]
        self.assertEqual(mp.stray_voice_suspects(units, spill, 0), [])
        noise = [{"start": 8.0, "end": 8.6, "text": "啊"}]
        self.assertEqual(mp.stray_voice_suspects(units, noise, 0), [])
        vo = [{"start": 8.0, "end": 9.0, "text": "旁白说的话", "presence": "VOICE_OVER"}]
        self.assertEqual(mp.stray_voice_suspects(units, vo, 0), [])


# ===================================================================================== 2. parsing
class ParityParseTest(_Review):
    def test_unit_parity_rows_are_parsed_leniently(self):
        rows = mp.parse_unit_parity(D_ANSWER["unit_parity"] + ["junk", {"delivered": "NO"}])
        self.assertEqual([r["unit"] for r in rows], ["VU-001", "VU-002", "VU-003"])
        self.assertEqual(rows[0]["reasons"], ["ROLE_REVERSED", "WRONG_LOCATION"])
        self.assertEqual(rows[1]["delivered"], "YES")
        self.assertEqual(rows[2]["reasons"], ["MISSING_PROP", "OTHER"])
        self.assertIsNone(mp.parse_unit_parity([{"unit": "VU-009", "delivered": "maybe"}])[0]["delivered"])

    def test_merged_record_has_plan_parity_for_every_planned_unit(self):
        parity = self.record["plan_parity"]
        by = {u["unit"]: u for u in parity["units"]}
        self.assertEqual({k: v["delivered"] for k, v in by.items()},
                         {"VU-001": "NO", "VU-002": "YES", "VU-003": "PARTIAL", "VU-004": mp.NOT_IN_CUT})
        self.assertEqual(by["VU-001"]["severity"], "P0")                       # role reversed -> P0
        self.assertEqual(by["VU-003"]["severity"], "P2")                       # the model's own severity kept
        self.assertEqual((parity["delivered"], parity["total"]), (1, 4))
        self.assertEqual(parity["note"], "plan parity: 1/4 delivered")
        self.assertEqual(parity["no_units"], ["E24-VU-001"])
        promoted = [f for f in self.record["findings"] if f["item"] == "QA-PLAN-MISMATCH"]
        self.assertEqual([(f["start"], f["end"], f["severity"], f["pass"]) for f in promoted], [(0.0, 3.5, "P0", "D")])
        self.assertIn("刀架在角色A自己脖子上", promoted[0]["evidence"])
        self.assertNotIn("unit_parity", self.record["passes"]["D"])
        self.assertTrue(any("plan parity: 1/4 delivered" in line for line in gvr.summary_lines(self.record)))

    def test_pass_d_failure_leaves_parity_not_answered(self):
        out = mp.merge({"D": {"status": "ERROR"}}, {}, self.context["plan_units"])
        self.assertEqual(out["plan_parity"]["status"], "NOT_ANSWERED")
        self.assertTrue(out["plan_parity"]["note"].startswith("plan parity: not reviewed"))
        self.assertNotIn("plan_parity", mp.merge({}, {}))                       # no plan: record unchanged


# ===================================================================================== 3. routing + parity record
class RoutingTest(_Review):
    def checklist_record(self) -> dict:
        return qa.build_record({"items": {}}, {}, episode=EP, gemini=self.record)

    def test_checklist_carries_plan_parity_and_p0_no_triggers_the_round(self):
        cl = self.checklist_record()
        self.assertEqual(cl["plan_parity"]["note"], "plan parity: 1/4 delivered")
        segments = TIMELINE["segments"]
        mapped = ffr.dedupe(ffr.map_findings(ffr.collect_findings({}, cl), segments))
        plan = [f for f in mapped if f["source"] == ffr.PLAN_SOURCE]
        self.assertEqual([(f["kind"], f["class"], f["unit_id"], f["severity"]) for f in plan],
                         [("PLAN_MISMATCH", ffr.PAID, "E24-VU-001", "P0"),
                          (ffr.PLAN_NOT_IN_CUT, ffr.RECORD, "E24-VU-004", "P2")])
        self.assertTrue(ffr.triggered(False, mapped))                           # PASS review, P0 NO -> trigger
        self.assertTrue(ffr.needs_round(False, mapped))
        p1 = [{**f, "severity": "P1", "trigger": False} for f in plan]
        self.assertFalse(ffr.triggered(False, p1))                              # a P1 NO is not a trigger alone
        # the parity rows are Gemini's own verdicts: never knowledge events as "confirmed by the review"
        self.assertEqual(kb.FINAL_REVIEW_ROUTES["PLAN_MISMATCH"], "MODEL_CONSTRAINT")

    def test_plan_mismatch_is_paid_and_ranked_with_the_p0s(self):
        self.assertEqual(ffr.classify("QA-PLAN-MISMATCH"), "PLAN_MISMATCH")
        self.assertEqual(ffr.fix_class("PLAN_MISMATCH"), ffr.PAID)
        order = ffr.PAID_KINDS
        self.assertLess(order.index("REFERENCE_SHEET_LEAK"), order.index("PLAN_MISMATCH"))
        self.assertLess(order.index("PLAN_MISMATCH"), order.index("CAMERA_WOBBLE"))
        mapped = [{"kind": "BURNED_TEXT", "class": ffr.PAID, "unit_id": "U1", "severity": "P1", "on_screen_seconds": 6},
                  {"kind": "PLAN_MISMATCH", "class": ffr.PAID, "unit_id": "U2", "severity": "P0",
                   "on_screen_seconds": 2}]
        plan = ffr.plan_paid(mapped, budget=45, headroom=10, unit_cost=lambda uid: 8)   # room for one redo
        self.assertEqual([r["unit_id"] for r in plan["selected"]], ["U2"])
        self.assertEqual(plan["skipped"][0]["reason"], "BUDGET_CAP")
        sentence = ffr.redo_sentence(["PLAN_MISMATCH"])
        self.assertIn("planned moment", sentence)
        self.assertNotRegex(sentence, r"\d")

    def test_round_parks_the_p0_no_unit_for_a_paid_redo(self):
        root = self.root / "round"
        from types import SimpleNamespace
        p = SimpleNamespace(
            assembly=root / "assembly", video_media=root / "video", preprod_reports=root / "reports",
            preprod=root / "pre", final_candidate=root / "assembly" / "E01_final_candidate_9x16.mp4",
            video_transaction=root / "pre" / "tx.json", agentcut_project=root / "assembly" / "proj.json",
            grouping_plan=root / "pre" / "grouping.json", editorial=root / "pre" / "editorial.json")
        for d in (p.assembly / "final_qa", p.video_media, p.preprod_reports, p.preprod):
            d.mkdir(parents=True, exist_ok=True)
        for i in range(1, 5):
            (p.video_media / f"E01-VU-00{i}.mp4").write_bytes(f"clip{i}".encode())
        (p.assembly / "E01_release_timeline.json").write_text(json.dumps({"segments": SEGMENTS}), encoding="utf-8")
        p.final_candidate.write_bytes(b"cut-1")
        ctx = _Ctx(episode="E01", p=p, run_id="RUN1", state={}, lines=[], headroom=500, dry=False, config={},
                   paid_order=None, authority={})
        cl = checklist(sha=sha(p.final_candidate))
        cl["plan_parity"] = {"units": [{"unit_id": "E01-VU-002", "start": 5.0, "end": 12.0, "delivered": "NO",
                                        "reasons": ["WRONG_LOCATION"], "severity": "P0"},
                                       {"unit_id": "E01-VU-003", "start": 12.0, "end": 16.0, "delivered": "YES"}]}
        final_qa = p.assembly / "final_qa"
        (final_qa / "E01_AUDIENCE_SCORE_REPORT.json").write_text(json.dumps({"problems": []}), encoding="utf-8")
        (final_qa / "E01_QA_DEFECT_CHECKLIST.json").write_text(json.dumps(cl), encoding="utf-8")
        first = {"report": str(final_qa / "E01_AUDIENCE_SCORE_REPORT.json"), "final_video_sha256": sha(p.final_candidate)}
        patches = [mock.patch.object(P, "episode_video_model", return_value="MiniMax-H3"),
                   mock.patch.object(P, "episode_video_resolution", return_value="768p"),
                   mock.patch.object(P, "video_task_credits", return_value=8),
                   mock.patch.object(P, "credits_summary", side_effect=lambda _c: {"recorded_total_credits": 100.0}),
                   mock.patch.object(P, "REVIEWS_ROOT", root / "reviews"),
                   mock.patch.dict(os.environ, {}, clear=False)]
        for patch in patches:
            patch.start()
        try:
            for name in ("NALU_FINAL_FIX_ROUNDS", "NALU_FINAL_FIX_BUDGET_CREDITS"):
                os.environ.pop(name, None)
            out = P.s7_final_fix_round(ctx, None, first, False)          # first review PASS
        finally:
            for patch in reversed(patches):
                patch.stop()
        self.assertEqual(out["action"], "S6_REDO_PENDING")
        self.assertEqual(out["units"], ["E01-VU-002"])
        rec = json.loads((final_qa / "final_fix_round.json").read_text(encoding="utf-8"))
        self.assertEqual(rec["paid"]["selected"][0]["kind"], "PLAN_MISMATCH")
        self.assertLessEqual(rec["paid"]["planned_credits"], ffr.DEFAULT_BUDGET)

    def test_final_cut_parity_report_consumes_the_review(self):
        base = {"final_duration_seconds": 15.0, "body_seconds": 12.0, "planned_shots": 4, "detected_segments": 3,
                "average_segment_seconds": 4.0, "average_planned_shot_seconds": 4.0, "findings": [],
                "status": "CLEAN"}
        merged = fcp.merge_review_parity(base, self.record, final_sha256=self.record["final_video_sha256"])
        self.assertEqual(merged["status"], "FINDINGS")
        self.assertEqual(merged["unit_parity"]["note"], "plan parity: 1/4 delivered")
        self.assertEqual([u["delivered"] for u in merged["unit_parity"]["units"]],
                         ["NO", "YES", "PARTIAL", "NOT_IN_CUT"])
        finding = next(f for f in merged["findings"] if f["code"] == "PLAN_UNIT_NOT_DELIVERED")
        self.assertEqual(finding["units"][0]["unit_id"], "E24-VU-001")
        again = fcp.merge_review_parity(merged, self.record, final_sha256=self.record["final_video_sha256"])
        self.assertEqual(len(again["findings"]), 1)                              # idempotent
        block = fcp.checkpoint_block(merged)
        self.assertIn("plan parity: 1/4 delivered", block)
        self.assertIn("计划未拍出：E24-VU-001", block)
        stale = fcp.merge_review_parity(base, self.record, final_sha256="other-cut")
        self.assertEqual((stale["unit_parity"]["status"], stale["status"]), ("STALE", "CLEAN"))
        none = fcp.merge_review_parity(base, None)
        self.assertEqual(none["unit_parity"]["status"], "NO_REVIEW_PARITY")


# ===================================================================================== 4. objective defects + policy
class ObjectiveDefectTest(_Review):
    def objective(self, record: dict | None = None) -> dict:
        return ffr.objective_defects(record or {"status": "NOT_NEEDED", "findings": []}, runtime_s=56.4,
                                     target_s=110.0, plan_parity=self.record["plan_parity"],
                                     suspect_checks=self.record["suspect_checks"])

    def test_objective_defects_summarise_runtime_burns_voices_and_plan(self):
        obj = self.objective()
        self.assertTrue(obj["runtime"]["short"])
        self.assertEqual(obj["runtime"]["ratio"], round(56.4 / 110, 3))
        self.assertEqual([(b["source"], b["window"], b["blocking"]) for b in obj["unresolved_burns"]],
                         [("LOCAL_OCR", [7.5, 8.2], True)])                     # S1 dismissed, S2 confirmed
        self.assertEqual([(v["unit"], v["heard"]) for v in obj["stray_voices"]], [("VU-003", "丁师兄去死吧")])
        self.assertEqual([u["unit_id"] for u in obj["plan_no_units"]], ["E24-VU-001"])
        self.assertEqual(obj["plan_not_in_cut"], ["E24-VU-004"])
        self.assertEqual(obj["count"], 4)
        self.assertEqual(obj["classes"], ["RUNTIME_SHORT", "BURN_UNRESOLVED", "STRAY_VOICES", "PLAN_NO_UNITS"])
        self.assertEqual(obj["blocking_classes"], obj["classes"])
        # an unresolved burned finding of the round and the OCR run at the same time are one burn
        rec = {"status": "DONE", "unresolved": [{"kind": "BURNED_TEXT", "unit_id": "E24-VU-003",
                                                 "window": [7.6, 8.0], "state": "PERSISTS"}]}
        self.assertEqual([b["source"] for b in self.objective(rec)["unresolved_burns"]], ["FINAL_FIX_UNRESOLVED"])
        # the reviewer's decision wins over Gemini's
        checks = [{"id": "S3", "gemini": "CONFIRMED", "reviewer": "DISMISSED",
                   "suspect": {"kind": "stray_voice", "unit": "VU-003"}}]
        self.assertEqual(ffr.objective_defects({}, suspect_checks=checks)["stray_voices"], [])

    def test_release_policy_holds_only_short_runtime_and_unresolved_burns(self):
        self.assertTrue(ffr.RELEASE_BLOCK_OBJECTIVE_DEFECTS)
        self.assertEqual(ffr.RELEASE_BLOCK_CLASSES, {"RUNTIME_SHORT", "BURN_UNRESOLVED"})
        self.assertEqual(ffr.RUNTIME_MIN_RATIO, 0.85)
        held = ffr.release_policy(self.objective(), env={})
        self.assertEqual((held["blocks"], held["held_classes"], held["hold"]),
                         (True, ["RUNTIME_SHORT", "BURN_UNRESOLVED"], "RELEASE_HELD:RUNTIME_SHORT,BURN_UNRESOLVED"))
        # (1) runtime alone: 0.84 x target holds, 0.85 does not
        short = ffr.objective_defects({}, runtime_s=92.4, target_s=110.0)
        self.assertEqual(ffr.release_policy(short, env={})["hold"], "RELEASE_HELD:RUNTIME_SHORT")
        ok = ffr.objective_defects({}, runtime_s=93.5, target_s=110.0)
        self.assertFalse(ffr.release_policy(ok, env={})["blocks"])
        # (2) burn alone: an unresolved burned finding of the round holds ...
        rec = {"status": "DONE", "unresolved": [{"kind": "BURNED_TEXT", "unit_id": "U3", "window": [7.6, 8.0],
                                                 "state": "PERSISTS"}]}
        burn = ffr.objective_defects(rec, runtime_s=100, target_s=110)
        self.assertEqual(ffr.release_policy(burn, env={})["hold"], "RELEASE_HELD:BURN_UNRESOLVED")
        # ... unless the burned-text handling accepted it (ACCEPT_CORRECT / our copy suppressed for the cue's line)
        accepted = {**rec, "findings": [{"kind": "BURNED_TEXT", "unit_id": "U3", "burn_verdict": "ACCEPT_CORRECT"}]}
        obj = ffr.objective_defects(accepted, runtime_s=100, target_s=110)
        self.assertEqual((obj["classes"], obj["blocking_classes"]), (["BURN_UNRESOLVED"], []))
        self.assertFalse(ffr.release_policy(obj, env={})["blocks"])
        # an OCR run only Gemini did not dismiss (NOT_ANSWERED) is recorded, not held
        ocr = [{"id": "S1", "decision": "NOT_ANSWERED", "suspect": {"kind": "burned_text", "window": [1.0, 2.0]}}]
        self.assertFalse(ffr.release_policy(ffr.objective_defects({}, suspect_checks=ocr), env={})["blocks"])
        # stray voices / plan NO units are record-only
        rest = ffr.objective_defects({}, runtime_s=100, target_s=110, plan_parity=self.record["plan_parity"],
                                     suspect_checks=self.record["suspect_checks"][2:])
        self.assertEqual(rest["blocking_classes"], ["STRAY_VOICES", "PLAN_NO_UNITS"])
        self.assertFalse(ffr.release_policy(rest, env={})["blocks"])

    def test_env_override_disables_or_widens_the_hold(self):
        obj = self.objective()
        self.assertFalse(ffr.release_policy(obj, env={ffr.RELEASE_POLICY_ENV: "off"})["blocks"])
        self.assertFalse(ffr.release_policy(obj, env={ffr.RELEASE_CLASSES_ENV: "none"})["blocks"])
        wide = ffr.release_policy(obj, env={ffr.RELEASE_CLASSES_ENV: "all"})
        self.assertEqual(wide["held_classes"], ["RUNTIME_SHORT", "BURN_UNRESOLVED", "STRAY_VOICES", "PLAN_NO_UNITS"])
        only = ffr.release_policy(obj, env={ffr.RELEASE_CLASSES_ENV: "plan_no_units, bogus"})
        self.assertEqual(only["hold"], "RELEASE_HELD:PLAN_NO_UNITS")
        with mock.patch.object(ffr, "RELEASE_BLOCK_OBJECTIVE_DEFECTS", False):     # the one-line switch
            self.assertFalse(ffr.release_policy(obj, env={})["blocks"])
            self.assertTrue(ffr.release_policy(obj, env={ffr.RELEASE_POLICY_ENV: "on"})["blocks"])

    def test_record_note_and_checkpoint_carry_parity_and_objective_defects(self):
        rec = {"status": "NOT_NEEDED", "findings": [], "plan_parity": ffr.plan_parity_summary(self.record["plan_parity"])}
        rec["objective_defects"] = self.objective(rec)
        rec["release_policy"] = ffr.release_policy(rec["objective_defects"], env={})
        note = ffr.status_note(rec)
        self.assertIn("final-fix: not needed", note)
        self.assertIn("plan parity: 1/4 delivered", note)
        self.assertIn("objective defects 4 (RUNTIME_SHORT,BURN_UNRESOLVED,STRAY_VOICES,PLAN_NO_UNITS)", note)
        self.assertIn("RELEASE_HELD:RUNTIME_SHORT,BURN_UNRESOLVED (not sent to X2C; redo candidate)", note)
        s = ffr.summary(rec)
        self.assertEqual(s["plan_parity"]["no_units"], ["E24-VU-001"])
        self.assertEqual((s["release_policy"]["blocks"], s["release_hold"]),
                         (True, "RELEASE_HELD:RUNTIME_SHORT,BURN_UNRESOLVED"))
        lines = "\n".join(ffr.checkpoint_lines(rec))
        self.assertIn("plan parity: 1/4 delivered — NO: E24-VU-001", lines)
        self.assertIn("runtime 56.4 s vs target 110.0 s", lines)
        self.assertIn("`release_block_objective_defects` = ON", lines)
        self.assertIn("**RELEASE_HELD:RUNTIME_SHORT,BURN_UNRESOLVED**: not sent to X2C", lines)
        self.assertEqual(ffr.status_note({}), "")

    def test_pipeline_holds_the_release_without_stalling_the_line(self):
        from types import SimpleNamespace
        root = self.root / "pipe"
        asm = root / "assembly"
        (asm / "final_qa").mkdir(parents=True)
        cand = asm / f"{EP}_final_candidate_9x16.mp4"
        cand.write_bytes(b"final-video")                                         # the reviewed bytes
        (asm / f"{EP}_release_timeline.json").write_text(json.dumps({**TIMELINE, "content_runtime_seconds": 56.4}))
        (asm / f"{EP}_FINAL_CUT_SHOT_PLAN_PARITY.json").write_text(json.dumps({
            "final_duration_seconds": 59.4, "body_seconds": 56.4, "planned_shots": 4, "detected_segments": 3,
            "average_segment_seconds": 4.0, "average_planned_shot_seconds": 4.0, "findings": [], "status": "CLEAN"}))
        (asm / "final_qa" / "final_fix_round.json").write_text(json.dumps({"status": "NOT_NEEDED", "findings": []}))
        gemini = root / "runtime" / "claude_code" / EP / "final_reviewer" / "gemini_review.json"
        gemini.parent.mkdir(parents=True)
        gemini.write_text(json.dumps(self.record, ensure_ascii=False))
        said: list = []
        ctx = SimpleNamespace(episode=EP, p=SimpleNamespace(assembly=asm, final_candidate=cand), say=said.append)
        res = SimpleNamespace(details={"shot_plan_parity": {"report": "x"}})
        with mock.patch.dict(os.environ, {"NALU_RUNTIME_ROOT": str(root / "runtime")}), \
                mock.patch.object(P, "RUNTIME", root / "runtime"):
            for name in (ffr.RELEASE_POLICY_ENV, ffr.RELEASE_CLASSES_ENV):
                os.environ.pop(name, None)
            out = P.s7_review_plan_parity(ctx, res, {"final_video_sha256": _digest(cand)})
            again = P.s7_review_plan_parity(ctx, res, {"final_video_sha256": _digest(cand)})   # re-entry
        self.assertEqual(out["status"], "RECORDED")
        self.assertEqual(out["release_hold"], "RELEASE_HELD:RUNTIME_SHORT,BURN_UNRESOLVED")
        self.assertEqual(again["release_hold"], out["release_hold"])
        rec = json.loads((asm / "final_qa" / "final_fix_round.json").read_text())
        self.assertEqual(rec["release_hold"]["status"], "RELEASE_HELD")
        backlog = json.loads((root / "runtime" / "series" / "REDO_BACKLOG.json").read_text())
        self.assertEqual(backlog["episodes"][EP]["status"], "REDO_CANDIDATE")
        self.assertEqual(backlog["episodes"][EP]["hold"], "RELEASE_HELD:RUNTIME_SHORT,BURN_UNRESOLVED")
        status = (root / "runtime" / "series" / "STATUS.md").read_text()
        self.assertEqual(status.count(f"RELEASE_HELD:RUNTIME_SHORT,BURN_UNRESOLVED {EP}"), 1)      # once
        self.assertNotIn("blockers", vars(res))                                 # nothing for S7 to stop on
        rec = json.loads((asm / "final_qa" / "final_fix_round.json").read_text())
        self.assertEqual(rec["plan_parity"]["note"], "plan parity: 1/4 delivered")
        self.assertEqual(rec["objective_defects"]["runtime"]["target_seconds"], 110.0)   # default brief target
        self.assertIn("STRAY_VOICES", rec["objective_defects"]["classes"])
        report = json.loads((asm / f"{EP}_FINAL_CUT_SHOT_PLAN_PARITY.json").read_text())
        self.assertEqual(report["unit_parity"]["delivered"], 1)
        self.assertIn("plan parity: 1/4 delivered", (asm / f"{EP}_FINAL_CUT_SHOT_PLAN_PARITY.md").read_text())
        self.assertEqual(res.details["shot_plan_parity"]["unit_parity"]["no_units"], ["E24-VU-001"])
        self.assertEqual(res.details["shot_plan_parity"]["report"], "x")
        self.assertTrue(any("S7_OBJECTIVE_DEFECTS" in line and "release=RELEASE_HELD" in line for line in said))


# ===================================================================================== 5. never stall the line
class HoldDoesNotStallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        scripts = ROOT / "skills" / "nalu-claude-code" / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import codex_production as cp  # noqa: PLC0415
        import publish_x2creel as px  # noqa: PLC0415
        import publish_x2c_matrix as mx  # noqa: PLC0415
        self.cp, self.px, self.mx = cp, px, mx

    def tearDown(self):
        self.tmp.cleanup()

    def _episode(self, runtime: Path, work: Path, ep: str, hold: str | None) -> None:
        d = runtime / "claude_code" / ep
        d.mkdir(parents=True)
        (d / "session.json").write_text(json.dumps({"log": str(d / "run.jsonl"), "pid": None}))
        mp4 = runtime / "deliverables" / ep / f"{ep}_final_9x16.mp4"
        mp4.parent.mkdir(parents=True)
        mp4.write_bytes(b"v")
        fq = work / ep / "assembly" / "final_qa"
        fq.mkdir(parents=True)
        rec = {"status": "DONE", **({"release_hold": {"status": "RELEASE_HELD", "hold": hold}} if hold else {})}
        (fq / "final_fix_round.json").write_text(json.dumps(rec))

    def test_publisher_skips_a_held_episode_and_sends_the_next(self):
        runtime, work = self.root / "runtime", self.root / "work"
        self._episode(runtime, work, "E24", "RELEASE_HELD:RUNTIME_SHORT")
        self._episode(runtime, work, "E25", None)
        sent: list = []
        env = {"NALU_RUNTIME_ROOT": str(runtime), "NALU_ENGINE_ROOT": str(ROOT), "NALU_WORK_ROOT": str(work)}
        with mock.patch.dict(os.environ, env), \
                mock.patch.object(self.cp, "parse_log", return_value={"nalu_status": {"state": "FINAL_CUT_READY"}}), \
                mock.patch.object(self.cp, "alive", return_value=False), \
                mock.patch.object(self.cp, "ensure_poster", return_value=None), \
                mock.patch.object(self.mx, "matrix_mode", return_value=False), \
                mock.patch.object(self.px, "load_state", return_value={"episodes": {}}), \
                mock.patch.object(self.px, "cmd_publish",
                                  side_effect=lambda a: sent.append(a.episode) or {"status": "PUBLISHED"}):
            self.assertEqual(self.cp.release_hold("E24"), "RELEASE_HELD:RUNTIME_SHORT")
            self.assertEqual(self.cp.release_hold("E25"), "")
            out = self.cp.publish_next()
            self.assertEqual((out["episode"], sent), ("E25", ["E25"]))      # E24 is never sent ...
            with mock.patch.object(self.px, "load_state", return_value={"episodes": {"E25": {}}}):
                self.assertIsNone(self.cp.publish_next())                  # ... nor retried: nothing left to send
            self.assertEqual(sent, ["E25"])

    def test_s8_approves_a_held_episode_so_the_tick_moves_on(self):
        from types import SimpleNamespace
        root = self.root / "s8"
        (root / "final_qa").mkdir(parents=True)
        final = root / "deliver" / "E24_final_9x16.mp4"
        final.parent.mkdir(parents=True)
        final.write_bytes(b"v")
        hold = {"status": "RELEASE_HELD", "hold": "RELEASE_HELD:BURN_UNRESOLVED"}
        (root / "final_qa" / "final_fix_round.json").write_text(json.dumps({"status": "DONE", "release_hold": hold}))
        p = SimpleNamespace(assembly=root, final_mp4=final, checkpoint=root / "CHECKPOINT.md",
                            approval=root / "approvals" / "E24.APPROVED.json")
        ctx = _Ctx(episode="E24", p=p, state={"stages": {"S7": {"status": "PASS"}}}, lines=[], paid_order=None)
        out = P.s8_auto_approve(ctx)
        self.assertEqual(out["status"], "APPROVED")                          # S8 never waits on a hold
        self.assertEqual(json.loads(p.approval.read_text())["release_hold"], hold)


if __name__ == "__main__":
    unittest.main()
