"""GLOBAL fast-track for confirmed, language-independent final-review lessons (line owner 2026-11-20: "通用的问题不分
语言 ... 应该是 global 的 lesson 立即生效"; the engine decides global vs language per finding, no kind whitelist).

Offline: no provider, no credits.  Covers the producer's scope classifier (structured kind / QA item, text signals,
the reviewer's kb_scope for ambiguous findings, default global), the reviewer-side kb_scope plumbing, the release
train's fast-track (1 confirmed episode, separate ft- review slot, RELEASED directly with the service waiver,
language override -> canary path, rule cap), the safety valves (recurrence auto-retire, regression retire, manual
kill, kill switch) and the device-side DIRECTING_GUIDANCE injection of a rule without scope.languages."""
from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
for entry in (str(TOOLS), str(ROOT / "tools"), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import final_audience_review as far  # noqa: E402
import final_fix_round as ffr  # noqa: E402
import knowledge_event_log as kel  # noqa: E402
import nalu_knowledge_events as kbe  # noqa: E402
import nalu_qa_defect_checklist as qa  # noqa: E402
from tools.collective_learning import authoring  # noqa: E402
from tools.collective_learning import contracts as c  # noqa: E402
from tools.collective_learning import object_store as osm  # noqa: E402
from tools.collective_learning import release_train as rt  # noqa: E402
from tools.collective_learning import s3_sync as s3  # noqa: E402
from tools.collective_learning import service as svc_mod  # noqa: E402
from tools.tests.fake_s3 import FakeS3  # noqa: E402
from tools.tests.test_collective_release_train import T0, TENANT, Harness  # noqa: E402

H3 = "MiniMax-H3"
SHA = "f" * 64


def scope_of(kind: str, text: str = "", item: str | None = None, **extra) -> dict:
    return kbe.final_review_scope({"item": item, "text": text, **extra}, kind)


# --------------------------------------------------------------------------- 1. classifier
class ScopeClassifierTest(unittest.TestCase):
    def test_structured_kinds_and_items(self) -> None:
        for kind in ("VOICE", "ASR_MISMATCH", "SUBTITLE_WRAP"):
            self.assertEqual(scope_of(kind, "anything")["scope"], "language", kind)
            self.assertEqual(scope_of(kind)["basis"], "KIND")
        for kind in ("BURNED_TEXT", "FACE_DRIFT", "COSTUME_IDENTITY", "LOOKALIKE", "STATIC_SHOT_SPLIT", "LETTERBOX",
                     "MASK", "BGM_FADES", "AUDIO_SMOOTHING", "DIALOGUE_TAIL_GUARD"):
            # model constraints (burned text, face / costume drift, look-alike cast) are global too
            self.assertEqual((scope_of(kind, "subtitle line")["scope"], scope_of(kind)["basis"]), ("global", "KIND"))
        self.assertEqual(scope_of("OTHER", "", item="QA-SUBTITLE-WRAP")["scope"], "language")
        self.assertEqual(scope_of("OTHER", "", item="LOOK-DRIFT")["basis"], "QA_ITEM")

    def test_text_signals_across_categories(self) -> None:
        global_texts = (
            "static hold for 7 s during the argument, nothing moves",          # static hold in dialogue
            "four same-size close-ups in a row, no wider shot",                  # shot-size monotony
            "jump cut: same subject, same framing",                              # jump cut
            "eyeline mismatch, the two look the same way across the cut",        # eyeline / 180
            "opening has no on-screen conflict for 6 s",                         # opening
            "episode ends on a mood fade, no cliffhanger",                       # ending hook
            "the reveal is not set up, plot logic breaks",                       # story
            "镜头一直是同一景别的特写，没有反应镜",                                 # zh picture / edit
            "剧情逻辑断裂，动机不清",                                               # zh story
        )
        for text in global_texts:
            got = scope_of("OTHER", text)
            self.assertEqual((got["scope"], got["basis"]), ("global", "TEXT_SIGNAL"), text)
        language_texts = (
            "honorifics wrong: the junior uses banmal to the boss",
            "translation reads stiff, word choice is literal",
            "pronunciation of the name is wrong in the ASR",
            "台词用词太书面，翻译腔",
            "존댓말 / 반말 mixed up",
        )
        for text in language_texts:
            got = scope_of("OTHER", text)
            self.assertEqual((got["scope"], got["basis"]), ("language", "TEXT_SIGNAL"), text)
        # pacing / story kinds are global unless the text points at the language
        self.assertEqual(scope_of("PACING", "the middle drags, pacing too slow")["scope"], "global")
        self.assertEqual(scope_of("STORY", "the idiom in the dialogue makes no sense to this market")["scope"],
                         "language")

    def test_ambiguous_uses_the_reviewer_else_default_global(self) -> None:
        mixed = "the honorific joke lands on a static shot"                     # both signals
        none = "feels off overall"                                              # no signal
        for text in (mixed, none):
            got = scope_of("OTHER", text, kb_scope="language", kb_scope_reason="joke only works in Korean")
            self.assertEqual((got["scope"], got["basis"]), ("language", "REVIEWER"), text)
            self.assertIn("Korean", got["reason"])
            got = scope_of("OTHER", text, kb_scope="global")
            self.assertEqual((got["scope"], got["basis"]), ("global", "REVIEWER"))
            got = scope_of("OTHER", text, kb_scope="maybe")                    # malformed -> ignored
            self.assertEqual((got["scope"], got["basis"]), ("global", "DEFAULT"))
            self.assertEqual(scope_of("OTHER", text)["scope"], "global")
        # a structured signal wins over the reviewer
        self.assertEqual(scope_of("VOICE", "", kb_scope="global")["scope"], "language")


# --------------------------------------------------------------------------- 2. reviewer plumbing + producer
class ReviewerScopePlumbingTest(unittest.TestCase):
    def test_reviewer_rows_carry_kb_scope(self) -> None:
        self.assertEqual(far.kb_scope_fields({"kb_scope": "Language", "kb_scope_reason": " only  in ko "}),
                         {"kb_scope": "language", "kb_scope_reason": "only in ko"})
        self.assertEqual(far.kb_scope_fields({"kb_scope": "both"}), {})
        self.assertIn("global|language", json.dumps(far.KB_SCOPE_HINT))
        parsed = qa.parse_block({"items": {}, "gemini_verification": [
            {"id": "G1", "decision": "CONFIRMED", "reason": "seen at 3 s", "kb_scope": "global",
             "kb_scope_reason": "framing"},
            {"id": "G2", "decision": "CONFIRMED", "reason": "heard", "kb_scope": "nope"}]})
        self.assertEqual(parsed["gemini_verification"]["G1"]["kb_scope"], "global")
        self.assertNotIn("kb_scope", parsed["gemini_verification"]["G2"])
        block = qa.gemini_block({"status": "OK", "findings": [
            {"id": "G1", "item": "OTHER", "start": 3.0, "end": 4.0, "severity": "P1", "description": "headroom cut"},
            {"id": "G2", "item": "OTHER", "start": 9.0, "end": 9.5, "severity": "P2", "description": "x"}]},
            parsed, [])
        rows = {r["id"]: r for r in block["findings"]}
        self.assertEqual((rows["G1"]["status"], rows["G1"]["kb_scope"]), ("CONFIRMED", "global"))
        found = ffr.collect_findings({"problems": [{"severity": "P1", "issue": "x" * 12, "fix": "y" * 12,
                                                    "kb_scope": "language", "kb_scope_reason": "honorific"}]},
                                     {"video_review": block})
        self.assertEqual(sorted((f["source"], f.get("kb_scope") or "") for f in found),
                         [("GEMINI_CONFIRMED", ""), ("GEMINI_CONFIRMED", "global"), ("REVIEW_PROBLEM", "language")])

    def test_reviewer_prompt_asks_for_kb_scope(self) -> None:
        src = (ROOT / "skills/nalu-claude-code/scripts/codex_production.py").read_text(encoding="utf-8")
        self.assertIn("kb_scope", src)
        self.assertIn("kb_scope_reason", src)


class ProducerScopeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rt = Path(tempfile.mkdtemp()) / "runtime"
        (self.rt / "reports").mkdir(parents=True)
        report = {"verdict": "REJECT_RECUT", "overall": 2, "media_sha256": SHA, "problems": [
            {"severity": "P1", "at_seconds": 5.0, "issue": "four same-size close-ups in a row",
             "fix": "cut to a reaction or a wider shot"},
            {"severity": "P1", "at_seconds": 20.0, "issue": "the junior uses the wrong honorific to the boss",
             "fix": "fix the speech level"},
            {"severity": "P2", "at_seconds": 40.0, "issue": "feels off overall here",
             "fix": "tighten it somehow", "kb_scope": "language", "kb_scope_reason": "joke only works in Korean"},
            {"severity": "P2", "at_seconds": 60.0, "issue": "two characters share the same voice", "fix": "recast"},
        ]}
        self.report = self.rt / "report.json"
        self.report.write_text(json.dumps(report), encoding="utf-8")

    def test_cluster_key_scope_decision_and_confirmation(self) -> None:
        out = kbe.record_final_review_findings(self.rt, episode="E01", report_path=str(self.report),
                                               media_sha256=SHA, language="ko-KR")
        self.assertEqual(out["status"], "OK", out)
        rows = [r for r in kel.events(self.rt, episode="E01")
                if str((r.get("evidence") or {}).get("failure_type") or "").startswith("FINAL_REVIEW:")]
        by_key = {r["evidence"]["cluster_key"]: r["evidence"] for r in rows}
        self.assertEqual(sorted(by_key), ["FINAL_REVIEW:OTHER|global", "FINAL_REVIEW:OTHER|ko",
                                          "FINAL_REVIEW:VOICE|ko"], by_key)
        glob = by_key["FINAL_REVIEW:OTHER|global"]
        self.assertEqual((glob["kb_scope"], glob["scope_decision"]["basis"], glob["confirmed"], glob["language"],
                          glob["detail_category"]), ("global", "TEXT_SIGNAL", True, "ko", "global"))
        bases = sorted(r["evidence"]["scope_decision"]["basis"] for r in rows)
        self.assertEqual(bases, ["KIND", "REVIEWER", "TEXT_SIGNAL", "TEXT_SIGNAL"])
        self.assertEqual(c.sensitive_findings([r["evidence"] for r in rows]), [])
        sample = rt.evidence_sample({**rows[0], "event_kind": "FAILURE_OBSERVATION"})
        self.assertIn("scope_decision", sample)
        self.assertIn("kb_scope", sample)


# --------------------------------------------------------------------------- 3. release train fast-track
def directing_rule(rule_id: str, **scope) -> dict:
    return {"rule_id": rule_id, "category": "DIRECTING_HEURISTIC",
            "scope": {"models": [H3], "stages": ["SCRIPT_AUTHORING", "STORYBOARD_AUTHORING"], **scope},
            "trigger": "a scene cut as a run of same-size close-ups",
            "recommendation": "vary shot size: after two close-ups cut to a reaction or a wider shot",
            "exceptions": ["a deliberate one-take confrontation"], "verification": "the finding stops recurring",
            "cost_class": "FREE_LOCAL", "evidence_level": "SINGLE_CASE", "validation_scope": "REAL_MEDIA_REVIEW",
            "application": {"carrier": "DIRECTING_GUIDANCE",
                            "prompt_clause": {"zh": "同一景别特写不连续超过两镜，之后切反应镜或更宽的镜头",
                                              "en": "Never cut more than two same-size close-ups in a row"}}}


class FastTrackHarness(Harness):
    def fr(self, device: str, episode: str, kind: str, scope: str = "global", *, at: float | None = None,
           route: str = "DIRECTING_GUIDANCE", confirmed: bool | None = True, language: str = "ko", **extra) -> None:
        evidence = {"failure_type": f"FINAL_REVIEW:{kind}", "cluster_key": f"FINAL_REVIEW:{kind}|{scope}",
                    "lesson_route": route, "language": language, "kb_scope": "global" if scope == "global" else "language",
                    "scope_decision": {"scope": "global" if scope == "global" else "language", "basis": "TEXT_SIGNAL",
                                       "reason": "picture / edit"}, **extra}
        if confirmed is not None:
            evidence["confirmed"] = confirmed
        if route == "ENGINE":
            evidence["lesson_class"] = "ENGINE_THRESHOLD"
        event = c.make_observation(
            tenant_id=TENANT, line_id="nalu", device_id=device, run_id=f"nalu.{episode}.B1", episode_id=episode,
            stage="SCRIPT_AUTHORING", event_kind="FAILURE_OBSERVATION", symptom=f"final review {kind} {episode}",
            evidence=evidence, detected_by="nalu_pipeline", producer_sequence=1, unit_ids=[], visibility="LINE",
            occurred_at=rt._iso(at if at is not None else self.clock[0] - 600),
            opportunity={"applicable_units": 1, "observed_units": 1}, provider_model_version=H3)
        principal = svc_mod.Principal(device, TENANT, "device_writer", ("nalu",))
        self.assertEqual(self.svc.ingest_events(principal, [event])[0]["status"], "CREATED")

    def ft_request(self) -> dict:
        out = self.train.fasttrack_export()
        self.assertEqual(out["status"], "EXPORTED", out)
        return json.loads(Path(out["path"]).read_text())

    def approve(self, request: dict, rules: dict[str, dict] | None = None, **extra) -> dict:
        decisions = []
        for cl in request["clusters"]:
            self.counter += 1
            decisions.append({"cluster_id": cl["cluster_id"], "decision": "APPROVE",
                              "reason": "obvious global craft lesson",
                              "rule": (rules or {}).get(cl["cluster_key"]) or directing_rule(f"kb-ft{self.counter}")})
        return self.train.import_review({"schema": rt.RESULT_SCHEMA, "request_id": request["request_id"],
                                         "reviewer": "patrol", "decisions": decisions, **extra})

    def store(self):
        cfg = osm.ObjectStoreConfig.from_mapping({"endpoint_url": "https://s3.test", "bucket": "drama01"},
                                                 env={osm.ENV_ACCESS_KEY: "k", osm.ENV_SECRET_KEY: "s"})
        store = osm.ObjectStore(cfg, FakeS3(), line_id=s3.SERVICE_LINE, receipt_path=self.tmp / "pre.json")
        store.preflight()
        return store


class FastTrackEligibilityTest(FastTrackHarness):
    def test_one_confirmed_global_episode_is_fast_track_language_and_unconfirmed_are_not(self) -> None:
        self.fr("sn-r1", "E01", "OTHER")                                                 # global, confirmed
        self.fr("sn-r1", "E01", "BURNED_TEXT", route="MODEL_CONSTRAINT")                # global model constraint
        self.fr("sn-r2", "E01", "PACING", scope="ko")                                    # language-scoped
        self.fr("sn-r2", "E01", "STORY", confirmed=None)                                 # not marked confirmed
        self.fr("sn-r3", "E01", "LENGTH", confirmed=False)
        self.fr("sn-r3", "E01", "BGM_FADES", route="ENGINE")                             # engine item
        clusters = {cl["cluster_key"]: cl for cl in self.train.clusters()}
        self.assertTrue(clusters["FINAL_REVIEW:OTHER|global"]["fast_track_eligible"])
        self.assertTrue(clusters["FINAL_REVIEW:BURNED_TEXT|global"]["fast_track_eligible"])
        self.assertNotIn("fast_track", clusters["FINAL_REVIEW:PACING|ko"])
        self.assertFalse(clusters["FINAL_REVIEW:PACING|ko"]["eligible"])                # still 2 episodes
        self.assertNotIn("fast_track", clusters["FINAL_REVIEW:STORY|global"])
        self.assertNotIn("fast_track", clusters["FINAL_REVIEW:LENGTH|global"])
        self.assertNotIn("FINAL_REVIEW:BGM_FADES|global", clusters)
        request = self.ft_request()
        self.assertTrue(request["request_id"].startswith("ft-") and request["fast_track"])
        self.assertEqual({cl["cluster_key"] for cl in request["clusters"]},
                         {"FINAL_REVIEW:OTHER|global", "FINAL_REVIEW:BURNED_TEXT|global"})
        self.assertIn("no canary", request["instructions"])
        self.assertEqual(self.train.fasttrack_export()["status"], "OPEN_REVIEW_PENDING")
        # the daily request does not duplicate fast-track clusters, and both slots are open side by side
        self.fr("sn-r2", "E02", "PACING", scope="ko")
        daily = self.request()
        self.assertEqual({cl["cluster_key"] for cl in daily["clusters"]}, {"FINAL_REVIEW:PACING|ko"})
        status = self.train.status()
        self.assertEqual((status["open_review_request"], status["open_fasttrack_review_request"]),
                         (daily["request_id"], request["request_id"]))

    def test_kill_switch_stops_export_and_daily_takes_global_clusters_on_normal_thresholds(self) -> None:
        self.fr("sn-r1", "E01", "OTHER")
        (self.train.dir / rt.FASTTRACK_KILL_FILE).write_text("owner")
        self.assertEqual(self.train.fasttrack_export()["status"], "KILLED")
        self.assertEqual(self.train.export_review()["status"], "NOTHING_TO_REVIEW")    # 1 episode < 2
        self.fr("sn-r1", "E02", "OTHER")
        self.assertEqual({cl["cluster_key"] for cl in self.request()["clusters"]}, {"FINAL_REVIEW:OTHER|global"})
        self.assertIn("快速通道已关闭", self.train.status()["summary_zh"])
        self.assertFalse(self.make_train(fasttrack_enabled=False).fasttrack_active())


class FastTrackPublishTest(FastTrackHarness):
    def test_approved_global_rule_is_released_to_every_device_at_once(self) -> None:
        self.fr("sn-r1", "E01", "OTHER")
        out = self.approve(self.ft_request())
        self.assertEqual(out["fasttrack_publish"]["status"], "PUBLISHED_TO_RELEASED", out)
        rule_id = out["fasttrack_publish"]["promoted"][0]
        rec = self.svc.get_candidate(self.train.pub, rule_id)
        self.assertEqual(rec["state"], "RELEASED")
        self.assertNotIn("languages", rec["payload"]["scope"])
        history = self.svc.candidate_history(self.train.pub, rule_id)
        self.assertEqual([h["to_state"] for h in history if h["action"] == "TRANSITION"],
                         ["VALIDATED", "CANARY", "RELEASED"])
        self.assertEqual(history[-1]["detail"]["waivers"], ["FAST_TRACK_SINGLE_SOURCE"])
        synced = s3.sync_channels(self.svc, self.store(), self.root, TENANT)              # through the release gate
        version = str(out["fasttrack_publish"]["version"])
        self.assertEqual(synced["latest_by_channel"], {"RELEASED": {"nalu-kb": version},
                                                       "CANARY": {"nalu-kb": version}})
        state = self.train.state()
        self.assertEqual(state["released_rules"], [rule_id])
        self.assertIsNone(state["open_fasttrack_review"])
        status = self.train.status()
        self.assertEqual(status["fast_track"]["live_rules"], [rule_id])
        self.assertIn("快速通道 1", status["summary_zh"])

    def test_waiver_is_publisher_only_and_needed_for_one_source(self) -> None:
        self.fr("sn-r1", "E01", "OTHER")
        request = self.ft_request()
        self.train.publisher_key, key = None, self.train.publisher_key                   # import only, no publish
        out = self.approve(request)
        self.assertEqual(out["fasttrack_publish"]["code"], "PUBLISHER_KEY_UNAVAILABLE")
        rule_id = self.train.state()["fasttrack"]["queue"][0]
        rec = self.svc.get_candidate(self.train.pub, rule_id)
        self.svc.transition_candidate(self.train.pub, rule_id, to="CANARY", if_match=rec["etag"])
        rec = self.svc.get_candidate(self.train.pub, rule_id)
        with self.assertRaises(svc_mod.Conflict):                                        # one source, no waiver
            self.svc.transition_candidate(self.train.pub, rule_id, to="RELEASED", if_match=rec["etag"])
        reviewer = svc_mod.Principal("patrol", TENANT, "reviewer")
        with self.assertRaises(svc_mod.Forbidden):
            self.svc.transition_candidate(reviewer, rule_id, to="REJECTED", if_match=rec["etag"],
                                          waive=("FAST_TRACK_SINGLE_SOURCE",))
        with self.assertRaises(svc_mod.PayloadInvalid):
            self.svc.transition_candidate(self.train.pub, rule_id, to="RELEASED", if_match=rec["etag"],
                                          waive=("ANYTHING",))
        # the hourly run publishes what the import could not
        self.train.publisher_key = key
        self.assertEqual(self.train.fasttrack()["publish"]["status"], "PUBLISHED_TO_RELEASED")

    def test_language_override_and_cap_take_the_canary_path(self) -> None:
        self.fr("sn-r1", "E01", "OTHER")
        self.fr("sn-r1", "E01", "STORY")
        self.fr("sn-r1", "E01", "LENGTH")
        self.train = self.make_train(fasttrack_max_rules=1)
        request = self.ft_request()
        rules = {"FINAL_REVIEW:LENGTH|global": directing_rule("kb-ko-only", languages=["ko"])}
        out = self.approve(request, rules)
        fast = [o for o in out["outcomes"] if o.get("fast_track")]
        self.assertEqual(len(fast), 1)
        self.assertEqual(len(out["fasttrack_publish"]["promoted"]), 1)
        state = self.train.state()
        self.assertEqual(len(state["backlog"]), 2)                                     # override + over the cap
        self.assertIn("kb-ko-only", state["backlog"])
        declined = sorted(r.get("fast_track_declined") for r in state["clusters"].values() if r.get("fast_track_declined"))
        self.assertEqual(declined, ["FASTTRACK_CAP", "SCOPED_TO_LANGUAGE"])

    def test_in_flight_canary_is_re_signed_and_rollback_keeps_the_global_rule(self) -> None:
        canary = self.ship_canary(1)
        self.fr("sn-r1", "E01", "OTHER")
        out = self.approve(self.ft_request())["fasttrack_publish"]
        rule_id = out["promoted"][0]
        self.assertIn("canary_version", out)
        state = self.train.state()
        pack = self.train._canary_pack(state)
        self.assertEqual(pack["superseded_versions"], [canary["version"]])
        self.assertIn(rule_id, pack["kept_rules"])
        synced = s3.sync_channels(self.svc, self.store(), self.root, TENANT)
        self.assertEqual(synced["latest_by_channel"], {"RELEASED": {"nalu-kb": str(out["version"])},
                                                       "CANARY": {"nalu-kb": str(out["canary_version"])}})
        # the canary turns out clearly worse: rolled back, canary devices fall back to the RELEASED set
        self.clock[0] = T0 + 25 * 3600
        self.rounds(["sn-c1", "sn-c2"], at=T0 + 3600, failed=8, episodes=2)
        self.rounds(["sn-r1", "sn-r2"], at=T0 + 3600, failed=0, episodes=2)
        self.assertEqual(self.train.evaluate()["status"], "ROLLED_BACK")
        row = self.svc._read("SELECT version FROM channels WHERE tenant_id=? AND channel='CANARY'", (TENANT,))
        self.assertEqual(row[0][0], str(out["version"]))
        self.assertEqual(self.svc.get_candidate(self.train.pub, rule_id)["state"], "RELEASED")


class FastTrackSafetyValveTest(FastTrackHarness):
    def released(self) -> str:
        self.fr("sn-r1", "E01", "OTHER")
        return self.approve(self.ft_request())["fasttrack_publish"]["promoted"][0]

    def test_recurring_target_retires_the_rule_and_republishes(self) -> None:
        rule_id = self.released()
        self.clock[0] = T0 + 2 * 3600
        self.fr("sn-r2", "E05", "OTHER", at=T0 + 3600)                                  # inside the grace period
        self.clock[0] = T0 + 10 * 3600
        for ep in ("E06", "E07"):
            self.fr("sn-r2", ep, "OTHER", at=T0 + 8 * 3600)
        self.assertEqual(self.train.fasttrack_retire()["retired"], [])                  # 2 < 3
        self.fr("sn-r3", "E06", "OTHER", at=T0 + 9 * 3600)
        out = self.train.fasttrack_retire()
        self.assertEqual(out["retired"], [rule_id])
        self.assertEqual(self.svc.get_candidate(self.train.pub, rule_id)["state"], "DEPRECATED")
        state = self.train.state()
        self.assertEqual(state["released_rules"], [])
        self.assertEqual(state["fasttrack"]["rules"][rule_id]["status"], "RETIRED")
        self.assertTrue(any(h["action"] == "fasttrack_retire" for h in state["history"]))
        synced = s3.sync_channels(self.svc, self.store(), self.root, TENANT)
        self.assertEqual(synced["latest_by_channel"]["RELEASED"], {"nalu-kb": str(out["shipped"]["released_version"])})
        # the retired cluster is handled: it is not offered again
        self.assertEqual(self.train.fasttrack_export()["status"], "NOTHING_TO_REVIEW")

    def test_regression_after_release_retires_the_batch(self) -> None:
        self.rounds(["sn-r1", "sn-r2"], at=T0 - 3600, failed=0, episodes=2)             # before: clean
        rule_id = self.released()
        self.clock[0] = T0 + 20 * 3600
        self.rounds(["sn-r1", "sn-r2"], at=T0 + 3600, failed=8, episodes=2)             # after: much worse
        out = self.train.fasttrack_retire()
        self.assertEqual(out["retired"], [rule_id])
        self.assertTrue(out["regression_checks"][0]["worse"])
        self.assertIn("FAST_TRACK_REGRESSION", self.train.state()["retired"][-1]["reason"])

    def test_not_worse_is_kept(self) -> None:
        self.rounds(["sn-r1", "sn-r2"], at=T0 - 3600, failed=0, episodes=2)
        rule_id = self.released()
        self.clock[0] = T0 + 20 * 3600
        self.rounds(["sn-r1", "sn-r2"], at=T0 + 3600, failed=0, episodes=2)
        self.assertEqual(self.train.fasttrack_retire()["retired"], [])
        self.assertEqual(self.train.state()["fasttrack"]["rules"][rule_id]["regression_checked"], "NOT_WORSE")

    def test_manual_kill_by_cli_and_by_review_result(self) -> None:
        first = self.released()
        out = io.StringIO()
        args = ["fasttrack-kill", "--runtime-root", str(self.root.root), "--tenant", TENANT, "--rule", first,
                "--reason", "owner: hurts pacing"]
        self.assertEqual(rt.main(args, out=out), 0, out.getvalue())
        self.assertEqual(json.loads(out.getvalue())["retired"], [first])
        self.assertEqual(self.svc.get_candidate(self.train.pub, first)["state"], "DEPRECATED")
        self.fr("sn-r1", "E02", "STORY")
        second = self.approve(self.ft_request())["fasttrack_publish"]["promoted"][0]
        self.fr("sn-r2", "E01", "PACING", scope="ko")
        self.fr("sn-r2", "E02", "PACING", scope="ko")
        daily = self.request()
        res = self.train.import_review({"schema": rt.RESULT_SCHEMA, "request_id": daily["request_id"],
                                        "reviewer": "patrol", "decisions": [
                                            {"cluster_id": daily["clusters"][0]["cluster_id"], "decision": "REJECT",
                                             "reason": "one-off"}],
                                        "fasttrack_kill": [second], "fasttrack_kill_reason": "regression seen"})
        self.assertEqual(res["fasttrack_kill"]["retired"], [second])
        self.assertEqual(rt.main(["fasttrack-kill", "--runtime-root", str(self.root.root), "--tenant", TENANT],
                                 out=io.StringIO()), 2)                                  # needs rule + reason

    def test_hourly_cli_runs_valves_even_when_killed(self) -> None:
        self.released()
        (self.train.dir / rt.FASTTRACK_KILL_FILE).write_text("x")
        out = io.StringIO()
        self.assertEqual(rt.main(["fasttrack", "--runtime-root", str(self.root.root), "--tenant", TENANT], out=out), 0)
        res = json.loads(out.getvalue())
        self.assertFalse(res["active"])
        self.assertIn("retire", res)
        self.assertNotIn("review", res)


# --------------------------------------------------------------------------- 4. device-side injection
class GlobalInjectionTest(unittest.TestCase):
    def rule(self, rule_id: str, **scope) -> dict:
        row = directing_rule(rule_id, **scope)
        row.update({"rule_version": 1, "_bundle_digest": "sha256:" + "0" * 64})
        return row

    def test_rule_without_languages_applies_to_every_language_line(self) -> None:
        rules = [self.rule("kb-global"), self.rule("kb-ko", languages=["ko"])]
        for lang, expect in (("zh", {"kb-global"}), ("en", {"kb-global"}), ("ja", {"kb-global"}),
                             ("ko", {"kb-global", "kb-ko"})):
            caps = {"model": H3, "engine_api_version": "nalu-engine-api-1", "stage": "SCRIPT_AUTHORING",
                    "language": lang, "genre": "", "flags": []}
            rows, decisions = authoring.directing_rules(rules, caps)
            self.assertEqual({r["rule_id"] for r in rows}, expect, (lang, decisions))
            clause = next(r["clause"] for r in rows if r["rule_id"] == "kb-global")
            self.assertEqual(clause.startswith("Never"), lang != "zh")                  # en clause for en / ja / ko


if __name__ == "__main__":
    unittest.main()
