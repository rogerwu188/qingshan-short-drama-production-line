"""Multi-pass video-native final review (gemini_review_passes.py, line owner 2026-11-20).

Offline: Gemini is a fake ``post``, the transcoder writes bytes, no ffmpeg / network."""
from __future__ import annotations

import hashlib
import json
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

import final_fix_round as ffr  # noqa: E402
import gemini_review_passes as mp  # noqa: E402
import gemini_video_review as gvr  # noqa: E402
import nalu_knowledge_events as kb  # noqa: E402
import nalu_qa_defect_checklist as qa  # noqa: E402

PRICES = gvr.PRICES
MODEL = gvr.DEFAULT_MODEL


def _pack_and_request(root: Path, duration: float = 100.0, measurements: dict | None = None) -> Path:
    video = root / "E19_final_9x16.mp4"
    video.write_bytes(b"final-video")
    pack = root / "E19_AV_EVIDENCE_PACK.json"
    pack.write_text(json.dumps({"summary": {
        "tail_cut_suspects": [{"cut": 22.71, "gap_s": 0.0, "level_db": 16.5}],
        "bgm_suspects": [{"window": [10.75, 13.75], "reasons": ["X"]}],
        "letterbox_shots": [{"window": [70.2, 74.6], "kind": "LETTERBOX", "content_aspect": 1.75}],
        "burned_text_runs": [{"window": [21.0, 22.7], "text": "毕竟我们不熟"}]}}), encoding="utf-8")
    req = root / "final_audience_request.json"
    req.write_text(json.dumps({
        "episode": "E19", "media": {"path": str(video), "sha256": hashlib.sha256(b"final-video").hexdigest()},
        "objective_summary": {"duration_seconds": duration},
        "shots": [{"shot_index": 0, "start_seconds": 0.0, "end_seconds": 3.0},
                  {"shot_index": 1, "start_seconds": 3.0, "end_seconds": 9.5}],
        "craft_standard_request": {"measured_pacing": {"mean_shot_seconds": 3.4}},
        "evidence": {"av_evidence_pack": {"path": str(pack), "sha256": hashlib.sha256(pack.read_bytes()).hexdigest()}},
        "qa_defect_checklist_request": {"measurements": measurements or {}}}), encoding="utf-8")
    return req


ANSWERS = {
    "PICTURE_AI_ARTEFACTS": {"findings": [
        {"class": "QA-HAND-ARTIFACT", "start": 12.0, "end": 13.0, "severity": "P1", "description": "六指"},
        {"class": "QA-SKIN-SHEEN-DRIFT", "start": 30.0, "end": 32.0, "severity": "P2", "description": "脸突然油亮"},
        {"class": "QA-BURNED-TEXT", "start": 21.0, "end": 22.7, "severity": "P1", "description": "烧字"}],
        "suspect_checks": [{"id": "S3", "decision": "CONFIRMED", "reason": "上下黑边"}],
        "shot_log": [{"start": 0, "end": 3, "note": "ok"}]},
    "IDENTITY_CONTINUITY": {"findings": [
        {"class": "LOOK-DRIFT", "start": 29.0, "end": 43.0, "severity": "P1", "description": "胡子和袍子变了"},
        {"class": "QA-BURNED-TEXT", "start": 21.2, "end": 22.0, "severity": "P2", "description": "又看到烧字"}]},
    "SOUND": {"findings": [{"class": "QA-LIPSYNC", "start": 40.0, "end": 41.0, "severity": "P2"}],
              "suspect_checks": [{"id": "S1", "decision": "CONFIRMED", "reason": "『熟』被切"}],
              "line_log": [{"start": 50.0, "end": 52.0, "tail": "clipped", "level": "ok"},
                           {"start": 40.0, "end": 41.0, "lipsync": "off"}]},
    "DIRECTOR_CRAFT": {"findings": [{"class": "CRAFT-PACING", "start": 48.0, "end": 59.6, "severity": "P2",
                                     "scope_hint": "global"}],
                       "craft_summary": {"opening_hook": {"at": 0.5, "ok": True}}, "verdict": "REJECT_RECUT"},
}


def _post(captured: list, fail: dict | None = None):
    fail = fail or {}

    def post(url, body, headers, timeout):
        data = json.loads(body)
        prompt = data["contents"][0]["parts"][-1]["text"]
        name = next(k for k in ANSWERS if f"（{k}）" in prompt)
        captured.append({"name": name, "body": data, "headers": headers, "prompt": prompt})
        mode = fail.get(name)
        if mode == "500":
            return 500, b'{"error": "upstream sk-test-SECRET"}'
        if mode == "garbage":
            return 200, json.dumps({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}).encode()
        if mode == "429_once" and sum(1 for c in captured if c["name"] == name) == 1:
            return 429, b'{"error": {"code": 429}}'
        payload = {"candidates": [{"content": {"parts": [{"text": json.dumps(ANSWERS[name], ensure_ascii=False)}]}}],
                   "usageMetadata": {"promptTokenCount": 20000, "candidatesTokenCount": 800,
                                     "thoughtsTokenCount": 1200, "totalTokenCount": 22000}}
        return 200, json.dumps(payload).encode()
    return post


def _transcode(video, out, **kw):
    out.write_bytes(b"x" * 100)
    return out


def _card(image, out):
    out.write_bytes(b"jpeg")
    return out


CONTEXT_NAMES = ("沈青", "陆九")


def _context(root: Path) -> dict:
    card = root / "card.png"
    card.write_bytes(b"png")
    return {"cards": [{"label": "角色A", "character_id": "CHAR-A", "image": str(card), "appearance": "年轻女子",
                       "wardrobe": "青灰短衫"},
                      {"label": "角色B", "character_id": "CHAR-B", "image": None, "appearance": "年轻男子"}],
            "scenes": [{"scene": "S01", "start": 0.0, "end": 50.0, "cast": ["角色A", "角色B"]}],
            "shots": [{"unit": "VU-001", "scene": "S01", "start": 0.0, "end": 7.0, "scale": "MEDIUM",
                       "cast": ["角色A"], "beat": "角色A推门冲进来"}]}


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = {"HOPSAPI_API_KEY": "sk-test-SECRET", "NALU_ENGINE_ROOT": str(ROOT),
                    "NALU_RUNTIME_ROOT": str(self.root)}
        patcher = mock.patch.object(mp, "card_jpeg", side_effect=_card)
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = mock.patch.object(mp.time, "sleep")
        self.sleep = sleeper.start()
        self.addCleanup(sleeper.stop)

    def tearDown(self):
        self.tmp.cleanup()

    def run_review(self, captured, fail=None, **kw):
        req = kw.pop("request", None) or _pack_and_request(self.root)
        return gvr.run(request_path=req, out=self.root / "final_reviewer" / "gemini_review.json",
                       post=_post(captured, fail), transcoder=_transcode, environ=self.env,
                       context=kw.pop("context", _context(self.root)), **kw)


class PromptTest(_Base):
    def test_each_pass_gets_its_own_focused_prompt_media_and_context(self):
        captured: list = []
        record = self.run_review(captured)
        self.assertEqual(record["status"], "OK")
        self.assertEqual(record["mode"], "multipass")
        by = {c["name"]: c for c in captured}
        self.assertEqual(set(by), set(ANSWERS))
        a, b, c, d = (by[k] for k in ANSWERS)
        # A: high media resolution, picture checklist, OCR lead, letterbox suspect; no audio-pass classes
        self.assertEqual(a["body"]["generationConfig"]["mediaResolution"], "MEDIA_RESOLUTION_HIGH")
        for cls in ("QA-FACE-ARTIFACT", "QA-HAND-ARTIFACT", "QA-SKIN-SHEEN-DRIFT", "QA-FLICKER", "QA-BURNED-TEXT",
                    "LETTERBOX"):
            self.assertIn(cls, a["prompt"])
        self.assertNotIn("QA-LIPSYNC", a["prompt"])
        self.assertIn("毕竟我们不熟", a["prompt"])
        self.assertIn("1.75", a["prompt"])
        self.assertIn("[0.0,3.0]", a["prompt"])                    # measured cuts for shot-by-shot checking
        # B: the identity card goes inline as an image, labels only, scenes, bounded thinking
        parts = b["body"]["contents"][0]["parts"]
        self.assertEqual([p["inline_data"]["mime_type"] for p in parts if "inline_data" in p],
                         ["video/mp4", "image/jpeg"])
        self.assertIn("角色A", b["prompt"])
        self.assertIn("青灰短衫", b["prompt"])
        self.assertIn('"scene":"S01"', b["prompt"])
        self.assertEqual(b["body"]["generationConfig"]["thinkingConfig"], {"thinkingBudget": 3072})
        # C: sound classes + the tail / music suspects, low resolution
        self.assertEqual(c["body"]["generationConfig"]["mediaResolution"], "MEDIA_RESOLUTION_LOW")
        for cls in ("QA-LIPSYNC", "QA-VOICE-INCONSISTENT", "QA-LOUDNESS-JUMP", "QA-DIALOGUE-TAIL-CUT"):
            self.assertIn(cls, c["prompt"])
        self.assertIn("22.71", c["prompt"])
        self.assertNotIn('"letterbox"', c["prompt"])
        # D: storyboard beats, craft standard items, measured pacing
        self.assertIn("角色A推门冲进来", d["prompt"])
        self.assertIn("S-01", d["prompt"])
        self.assertIn("mean_shot_seconds", d["prompt"])
        for cap in captured:
            self.assertEqual(cap["headers"]["Authorization"], "Bearer sk-test-SECRET")
        self.assertNotIn("sk-test-SECRET", (self.root / "final_reviewer" / "gemini_review.json").read_text())

    def test_episode_context_anonymises_names_and_maps_units_to_scenes(self):
        work = self.root / "E01"
        pre, plates, asm = work / "preproduction", work / "identity" / "plates", work / "assembly"
        for d in (pre, plates, asm):
            d.mkdir(parents=True)
        (plates / "E01_CHAR-SHENQING_aaaa.png").write_bytes(b"png")
        (plates / "E01_CHAR-SHENQING__FRONT_NEUTRAL_HEADSHOT_bbbb.png").write_bytes(b"png")
        (pre / "E01_EDITORIAL_SEEDANCE_MANIFEST_V1.json").write_text(json.dumps({"shots": [
            {"shot_id": "E01-S01-01", "prompt_spec": {"cast": [{"character": "沈青", "character_id": "CHAR-SHENQING"},
                                                              {"character": "陆九", "character_id": "CHAR-LUJIU"}]}}]}))
        (pre / "E01_VIDEO_UNIT_GROUPING_PLAN_V1.json").write_text(json.dumps({
            "wardrobe_bible": {"characters": [{"character_id": "CHAR-SHENQING", "appearance_ch1": "沈青二十二岁",
                                               "authored_description": "青灰短衫"}]},
            "units": [{"unit_id": "E01-VU-001", "scene_id": "E01-S01", "editorial_shot_ids": ["E01-S01-01"],
                       "narrative_beat": "陆九冲进来对沈青喊「快走」", "camera_plan": {"shot_scale": "MEDIUM"}}]}))
        (asm / "E01_release_timeline.json").write_text(json.dumps({"segments": [
            {"unit_id": "E01-VU-001", "output_start": 0.0, "output_end": 7.07}]}))
        ctx = mp.episode_context("E01", work_root=work)
        self.assertEqual([c["label"] for c in ctx["cards"]], ["角色A", "角色B"])
        self.assertTrue(ctx["cards"][0]["image"].endswith("E01_CHAR-SHENQING_aaaa.png"))   # the full sheet
        self.assertIsNone(ctx["cards"][1]["image"])
        self.assertEqual(ctx["scenes"], [{"scene": "S01", "start": 0.0, "end": 7.1, "cast": ["角色A", "角色B"]}])
        text = json.dumps(ctx, ensure_ascii=False)
        for name in CONTEXT_NAMES:
            self.assertNotIn(name, text)
        self.assertIn("角色B冲进来对角色A喊「…」", text)

    def test_skin_sheen_leads_of_pr284_become_pass_a_suspects(self):
        captured: list = []
        req = _pack_and_request(self.root, measurements={"skin_sheen": {"units": [
            {"unit_id": "E19-VU-001", "reasons": ["SPECULAR_SHARE_UP"]}]}})
        record = self.run_review(captured, request=req)
        a = next(c for c in captured if c["name"] == "PICTURE_AI_ARTEFACTS")
        self.assertIn("SPECULAR_SHARE_UP", a["prompt"])
        sheen = [c for c in record["suspect_checks"] if "unit" in c["suspect"]]
        self.assertEqual(sheen[0]["suspect"]["window"], [0.0, 7.0])
        self.assertEqual(sheen[0]["decision"], "NOT_ANSWERED")


class BudgetTest(unittest.TestCase):
    def test_split_degrades_lowest_priority_first_then_skips(self):
        chars = {p: 2500 for p in mp.PASS_IDS}
        full = mp.plan_budget(MODEL, PRICES, duration=60, cap=20, prompt_chars=chars, images={"B": 2})
        self.assertTrue(all(v["degraded_steps"] == 0 for v in full["passes"].values()))
        plan = mp.plan_budget(MODEL, PRICES, duration=100, cap=8, prompt_chars=chars, images={"B": 2})
        p = plan["passes"]
        self.assertLessEqual(plan["estimated_credits"], 8)
        self.assertEqual((p["A"]["fps"], p["A"]["res"]), (2.0, "HIGH"))     # the top pass keeps its settings
        self.assertEqual(p["D"]["degraded_steps"], 1)
        self.assertEqual(p["C"]["degraded_steps"], 1)
        self.assertGreaterEqual(p["B"]["degraded_steps"], 1)
        tight = mp.plan_budget(MODEL, PRICES, duration=100, cap=3.0, prompt_chars=chars)["passes"]
        self.assertEqual(tight["D"], {"skipped": "BUDGET_SKIPPED"})
        self.assertEqual(tight["C"], {"skipped": "BUDGET_SKIPPED"})
        self.assertIn("fps", tight["A"])
        none = mp.plan_budget(MODEL, PRICES, duration=1000, cap=0.5, prompt_chars=chars)
        self.assertEqual({v.get("skipped") for v in none["passes"].values()}, {"ESTIMATE_OVER_BUDGET"})
        self.assertEqual(none["estimated_credits"], 0.0)

    def test_estimate_counts_audio_and_cards_only_where_sent(self):
        a = mp.estimate_pass(MODEL, PRICES, pid="A", duration=100, fps=2, res="HIGH", prompt_chars=0)
        c = mp.estimate_pass(MODEL, PRICES, pid="C", duration=100, fps=2, res="LOW", prompt_chars=0)
        self.assertGreater(a, c)
        b0 = mp.estimate_pass(MODEL, PRICES, pid="B", duration=100, fps=1, res="HIGH", prompt_chars=0)
        b2 = mp.estimate_pass(MODEL, PRICES, pid="B", duration=100, fps=1, res="HIGH", prompt_chars=0, images=2)
        self.assertAlmostEqual(b2 - b0, 2 * mp.IMAGE_TOKENS["HIGH"] * PRICES[MODEL][0] / 1e6, places=3)

    def test_over_budget_episode_skips_without_a_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            req = _pack_and_request(root, duration=6000)
            calls: list = []
            record = gvr.run(request_path=req, out=root / "g.json", post=_post(calls), transcoder=_transcode,
                             environ={"HOPSAPI_API_KEY": "k"}, context={"cards": []})
            self.assertEqual((record["status"], record["reason"]), ("SKIPPED", "ESTIMATE_OVER_BUDGET"))
            self.assertEqual(calls, [])

    def test_large_upload_is_chunked_and_times_shifted(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)

            def big(video, out, **kw):
                out.write_bytes(b"x" * (mp.MAX_UPLOAD_BYTES + 10 if kw.get("start") is None else 10))
                return out
            media = mp.prepare_media(Path("v.mp4"), "A", work, duration=120.0, transcoder=big)
            self.assertEqual([m["window"] for m in media], [(0.0, 60.0), (60.0, 120.0)])
            parsed = mp.parse_pass(json.dumps({"findings": [{"class": "QA-HAND-ARTIFACT", "start": 5.0, "end": 6.0}]}),
                                   pid="A", duration=120.0, offset=60.0, window_len=60.0)
            self.assertEqual((parsed["findings"][0]["start"], parsed["findings"][0]["end"]), (65.0, 66.0))
            prompt = mp.build_pass_prompt("A", duration=120.0, window=(60.0, 120.0),
                                          context={"cuts": [{"start": 58.0, "end": 63.0}]})
            self.assertIn("60-120", prompt)
            self.assertIn("[0.0,3.0]", prompt)


class MergeTest(_Base):
    def test_merge_is_backward_compatible_and_folds_cross_pass_duplicates(self):
        captured: list = []
        record = self.run_review(captured)
        items = [(f["id"], f["item"], f["pass"]) for f in record["findings"]]
        self.assertEqual([i[0] for i in items], [f"G{n}" for n in range(1, len(items) + 1)])
        burned = [f for f in record["findings"] if f["item"] == "QA-BURNED-TEXT"]
        self.assertEqual(len(burned), 1)                 # A and B saw the same burned text -> one finding
        self.assertEqual(burned[0]["also_pass"], ["B"])
        self.assertEqual(burned[0]["severity"], "P1")
        promoted = [f for f in record["findings"] if f.get("from_log")]
        self.assertEqual([(f["item"], f["start"]) for f in promoted], [("QA-DIALOGUE-TAIL-CUT", 52.0)])
        for f in record["findings"]:
            for key in ("id", "item", "start", "end", "severity", "description", "evidence", "scope_hint", "pass"):
                self.assertIn(key, f)
        self.assertEqual(next(f for f in record["findings"] if f["item"] == "QA-LIPSYNC")["scope_hint"], "language")
        decisions = {c["id"]: c["decision"] for c in record["suspect_checks"]}
        self.assertEqual(decisions, {"S1": "CONFIRMED", "S2": "NOT_ANSWERED", "S3": "CONFIRMED"})
        self.assertEqual(record["verdict"], "REJECT_RECUT")
        self.assertEqual(record["craft_summary"]["opening_hook"]["at"], 0.5)
        self.assertAlmostEqual(record["cost_credits"], 4 * (20000 * 50.25e-6 + 2000 * 251.25e-6), places=2)
        self.assertEqual(set(record["passes"]), set(mp.PASS_IDS))
        self.assertEqual(record["cards_sent"], 1)
        # the summary lines and the must-check record still read it
        self.assertTrue(any("[A]" in line for line in gvr.summary_lines(record)))
        parsed = qa.parse_block({"items": {}, "gemini_verification": [
            {"id": "G1", "decision": "CONFIRMED", "reason": "六指"}]})
        checklist = qa.build_record(parsed, {}, episode="E19", gemini=record)
        rows = {g["id"]: g for g in checklist["video_review"]["findings"]}
        self.assertEqual(rows["G1"]["status"], "CONFIRMED")
        self.assertEqual(rows["G1"]["pass"], "A")
        self.assertIn("scope_hint", rows["G1"])
        self.assertTrue(checklist["items"]["QA-SKIN-SHEEN-DRIFT"]["gemini_findings"])

    def test_two_findings_of_one_pass_are_two_instances(self):
        rows = [{"item": "QA-BURNED-TEXT", "start": 16.5, "end": 17.5, "severity": "P1", "description": "a", "pass": "A"},
                {"item": "QA-BURNED-TEXT", "start": 17.6, "end": 19.0, "severity": "P1", "description": "b", "pass": "A"}]
        merged = mp.merge({"A": {"status": "OK", "findings": rows}}, {})
        self.assertEqual([(f["id"], f["start"]) for f in merged["findings"]], [("G1", 16.5), ("G2", 17.6)])

    def test_merge_without_passes_is_empty_and_safe(self):
        merged = mp.merge({}, {"tail": [{"id": "S1", "at": 1.0}]})
        self.assertEqual(merged["findings"], [])
        self.assertEqual(merged["suspect_checks"][0]["decision"], "NOT_ANSWERED")
        self.assertIsNone(merged["verdict"])


class FailOpenTest(_Base):
    def test_one_failing_pass_leaves_the_others(self):
        captured: list = []
        record = self.run_review(captured, fail={"SOUND": "500", "DIRECTOR_CRAFT": "garbage"})
        self.assertEqual(record["status"], "OK")
        self.assertEqual(record["passes"]["C"]["status"], "ERROR")
        self.assertEqual(record["passes"]["C"]["reason"], "HTTP_500")
        self.assertTrue(record["passes"]["D"]["reason"].startswith("UNPARSABLE_ANSWER"))
        self.assertEqual(record["passes"]["A"]["status"], "OK")
        self.assertFalse(any(f["pass"] in ("C", "D") for f in record["findings"]))
        self.assertNotIn("sk-test-SECRET", json.dumps(record))

    def test_all_failing_is_an_error_record_that_never_raises(self):
        captured: list = []
        record = self.run_review(captured, fail={k: "500" for k in ANSWERS})
        self.assertEqual(record["status"], "ERROR")
        self.assertTrue(record["reason"].startswith("ALL_PASSES_FAILED"))

    def test_a_429_is_retried_with_backoff(self):
        captured: list = []
        record = self.run_review(captured, fail={"SOUND": "429_once"})
        self.assertEqual(record["passes"]["C"]["status"], "OK")
        self.assertEqual(record["passes"]["C"]["retries"], 1)
        self.assertIn(mock.call(mp.RETRY_BACKOFF_S[0]), self.sleep.call_args_list)

    def test_the_deadline_bounds_calls_and_retries(self):
        seen = []

        def post(url, body, headers, timeout):
            seen.append(timeout)
            return 429, b"busy"
        with tempfile.TemporaryDirectory() as tmp:
            out = mp.run_passes(video=Path("v.mp4"), duration=60.0, model=MODEL, prices=PRICES, cap=20, key="k",
                                base_url="https://x", post=post, context={"cards": []}, leads={}, suspects={},
                                anime=False, craft=[], measured_pacing=None, transcoder=_transcode, passes=("C",),
                                sleep=lambda s: None, deadline_s=60.0, clock=lambda: 0.0)
        self.assertEqual(seen, [60.0])                      # timeout = time left; no retry without backoff + 60 s
        self.assertEqual(out["passes"]["C"]["reason"], "HTTP_429")
        with tempfile.TemporaryDirectory() as tmp:
            out = mp.run_passes(video=Path("v.mp4"), duration=60.0, model=MODEL, prices=PRICES, cap=20, key="k",
                                base_url="https://x", post=post, context={"cards": []}, leads={}, suspects={},
                                anime=False, craft=[], measured_pacing=None, transcoder=_transcode, passes=("C",),
                                sleep=lambda s: None, deadline_s=10.0, clock=lambda: 0.0)
        self.assertEqual(len(seen), 1)                      # under 30 s left: no call at all
        self.assertEqual(out["passes"]["C"]["status"], "ERROR")

    def test_media_failure_of_every_pass_is_an_error(self):
        def boom(video, out, **kw):
            raise RuntimeError("ffmpeg died")
        req = _pack_and_request(self.root)
        record = gvr.run(request_path=req, out=self.root / "g.json", post=_post([]), transcoder=boom,
                         environ=self.env, context={"cards": []})
        self.assertEqual(record["status"], "ERROR")
        self.assertTrue(all(v["reason"].startswith("MEDIA:") for v in record["passes"].values()))

    def test_single_mode_is_still_available(self):
        self.assertEqual(gvr.review_mode({"NALU_GEMINI_REVIEW_MODE": "single"}), "single")
        self.assertEqual(gvr.review_mode({}), "multipass")
        self.assertEqual(gvr.review_mode({"NALU_GEMINI_REVIEW_MODE": "bogus"}), "multipass")


class RoutingTest(unittest.TestCase):
    def test_new_classes_map_to_fix_round_kinds(self):
        cases = {"QA-HAND-ARTIFACT": ("HAND_ARTIFACT", ffr.PAID), "QA-SKIN-SHEEN-DRIFT": ("SKIN_SHEEN", ffr.PAID),
                 "QA-FACE-ARTIFACT": ("FACE_DRIFT", ffr.PAID), "QA-IDENTITY-MISMATCH": ("FACE_DRIFT", ffr.PAID),
                 "QA-BURNED-TEXT": ("BURNED_TEXT", ffr.PAID), "QA-LOUDNESS-JUMP": ("AUDIO_SMOOTHING", ffr.FREE),
                 "QA-AUDIO-ARTIFACT": ("AUDIO_SMOOTHING", ffr.FREE),
                 "QA-DIALOGUE-TAIL-CUT": ("DIALOGUE_TAIL_GUARD", ffr.FREE),
                 "QA-BGM-DISCONTINUOUS": ("BGM_FADES", ffr.FREE), "QA-LIPSYNC": ("ASR_MISMATCH", ffr.RECORD),
                 "QA-VOICE-INCONSISTENT": ("VOICE", ffr.RECORD), "QA-FLICKER": ("AI_ARTIFACT", ffr.RECORD),
                 "QA-PROP-CONTINUITY": ("CONTINUITY", ffr.RECORD), "CRAFT-PACING": ("PACING", ffr.RECORD),
                 "CRAFT-SHOT-GRAMMAR": ("SHOT_GRAMMAR", ffr.RECORD), "CRAFT-ENDING-HOOK": ("HOOK", ffr.RECORD),
                 "CRAFT-SUBTITLE-READABILITY": ("SUBTITLE_READABILITY", ffr.RECORD)}
        for item, (kind, cls) in cases.items():
            self.assertEqual((ffr.classify(item), ffr.fix_class(ffr.classify(item))), (kind, cls), item)
        self.assertEqual(ffr.classify("LOOK-DRIFT", "袍子颜色变了"), "COSTUME_IDENTITY")
        for cls in mp.CLASSES:   # every class the passes can emit has a fix-round kind
            self.assertTrue(cls in ffr.ITEM_KIND or cls in ("LOOK-DRIFT", "OTHER"), cls)
        self.assertIn("five separate fingers", ffr.redo_sentence(["HAND_ARTIFACT"]))
        self.assertNotRegex(ffr.SENTENCES["HAND_ARTIFACT"], r"\d")
        plan = ffr.plan_paid([{"class": ffr.PAID, "kind": "HAND_ARTIFACT", "unit_id": "U2", "on_screen_seconds": 9},
                              {"class": ffr.PAID, "kind": "BURNED_TEXT", "unit_id": "U1", "on_screen_seconds": 2}],
                             budget=10, headroom=None, unit_cost=lambda uid: 6)
        self.assertEqual([r["unit_id"] for r in plan["selected"]], ["U1"])
        self.assertEqual(plan["skipped"][0]["reason"], "BUDGET_CAP")

    def test_confirmed_gemini_findings_carry_pass_and_scope_hint_to_the_kb(self):
        checklist = {"items": {}, "video_review": {"findings": [
            {"id": "G1", "item": "QA-HAND-ARTIFACT", "window": [12.0, 13.0], "status": "CONFIRMED", "note": "六指",
             "pass": "A", "scope_hint": "global"},
            {"id": "G2", "item": "CRAFT-SUBTITLE-READABILITY", "window": [5.0, 6.0], "status": "CONFIRMED",
             "note": "字幕太快", "pass": "D", "scope_hint": "language"},
            {"id": "G3", "item": "OTHER", "window": [7.0, 8.0], "status": "CONFIRMED", "note": "怪", "pass": "D",
             "scope_hint": "language"},
            {"id": "G4", "item": "QA-LIPSYNC", "window": [9.0, 9.5], "status": "UNVERIFIED", "note": "x"}]}}
        found = ffr.map_findings(ffr.collect_findings({}, checklist), [])
        self.assertEqual([(f["kind"], f["class"], f["pass"]) for f in found],
                         [("HAND_ARTIFACT", ffr.PAID, "A"), ("SUBTITLE_READABILITY", ffr.RECORD, "D"),
                          ("OTHER", ffr.RECORD, "D")])
        self.assertEqual(kb.final_review_scope(found[0], "HAND_ARTIFACT")["scope"], "global")
        self.assertEqual(kb.final_review_scope(found[1], "SUBTITLE_READABILITY")["scope"], "language")
        decision = kb.final_review_scope(found[2], "OTHER")
        self.assertEqual((decision["scope"], decision["basis"]), ("language", "GEMINI_HINT"))
        reviewer = kb.final_review_scope({**found[2], "kb_scope": "global"}, "OTHER")
        self.assertEqual(reviewer["basis"], "REVIEWER")       # the reviewer's call wins over the hint
        self.assertEqual(kb.FINAL_REVIEW_ROUTES["HAND_ARTIFACT"], "MODEL_CONSTRAINT")
        self.assertEqual(kb.FINAL_REVIEW_ROUTES["SHOT_GRAMMAR"], "DIRECTING_GUIDANCE")

    def test_reviewer_prompt_asks_to_verify_every_new_class(self):
        sys.path.insert(0, str(ROOT / "skills/nalu-claude-code/scripts"))
        import codex_production as cp  # noqa: PLC0415
        step = cp.gemini_step(Path("/d/gemini_review.json"))
        for cls in ("QA-HAND-ARTIFACT", "QA-SKIN-SHEEN-DRIFT", "QA-IDENTITY-MISMATCH", "QA-LIPSYNC",
                    "QA-LOUDNESS-JUMP", "CRAFT-PACING", "CRAFT-ENDING-HOOK", "gemini_verification", "kb_scope"):
            self.assertIn(cls, step)
        self.assertEqual(cp.REVIEWER_PROMPT_VERSION.split()[0], "4")


if __name__ == "__main__":
    unittest.main()
