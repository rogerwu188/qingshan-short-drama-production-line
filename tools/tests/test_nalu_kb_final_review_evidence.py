"""Final-review findings feed the collective knowledge base (line owner 2026-11-20: a very poor KO E01 taught the
knowledge base nothing).

Offline: no provider, no credits.  Covers the FINAL_REVIEW:<kind>|<language> producer (confirmed findings only,
anonymised description, route / lesson_class, dedupe), its S7 pipeline hook, and the release train's author-side
thresholds (one device, two episodes) next to the strict model / engine thresholds."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
for entry in (str(TOOLS), str(ROOT / "tools"), str(ROOT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import knowledge_event_log as kel  # noqa: E402
import nalu_knowledge_events as kbe  # noqa: E402
from tools.collective_learning import contracts as c  # noqa: E402
from tools.collective_learning import release_train as rt_mod  # noqa: E402
from tools.tests.test_collective_release_train import T0, Harness  # noqa: E402

SHA = "c" * 64
REPORT = {
    "verdict": "REJECT_RECUT", "overall": 2, "media_sha256": SHA,
    "problems": [
        {"severity": "P0", "at_seconds": 88.0, "issue": "No end hook: 金민준 just walks away, the episode stops flat",
         "fix": "end on an open threat or reveal in the last 3 s"},
        {"severity": "P1", "window": [30.0, 66.0], "issue": "36 s middle sag, nothing changes between scenes",
         "fix": "cut the repeated apology beat"},
        {"severity": "P1", "at_seconds": 2.0, "issue": "Opening title card covers both faces",
         "fix": "move the title below the faces"},
    ],
}
CHECKLIST = {
    "bindings": {"final_video_sha256": SHA},
    "items": {"QA-BURNED-TEXT": {"status": "DEFECT", "reviewer_findings": [{"at_seconds": 12.0, "note": "stray caption"}]},
              "QA-SUBTITLE-WRAP": {"status": "PASS"}},
    "video_review": {"findings": [
        {"status": "CONFIRMED", "item": "QA-BGM-DISCONTINUOUS", "at_seconds": 40.0, "note": "music stops abruptly"},
        {"status": "DISMISSED", "item": "LOOK-DRIFT", "at_seconds": 50.0, "note": "face changes"}]},
}
CAST = [("CHAR-KIM", "金민준"), ("CHAR-LEE", "이서준")]


def _write(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


class ProducerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.rt = Path(tempfile.mkdtemp()) / "runtime"
        (self.rt / "reports").mkdir(parents=True)
        self.report = _write(self.rt / "E01_AUDIENCE_SCORE_REPORT.json", REPORT)
        self.checklist = _write(self.rt / "E01_QA_DEFECT_CHECKLIST.json", CHECKLIST)

    def record(self, **kw):
        args = dict(episode="E01", report_path=str(self.report), checklist_path=str(self.checklist), media_sha256=SHA,
                    language="ko-KR", cast_names=CAST, dialogue_lines=["금민준: 다시는 오지 마"])
        args.update(kw)
        return kbe.record_final_review_findings(self.rt, **args)

    def rows(self):
        return [r for r in kel.events(self.rt, episode="E01")
                if str((r.get("evidence") or {}).get("failure_type") or "").startswith("FINAL_REVIEW:")]

    def test_one_event_per_confirmed_finding_with_route_language_and_scrubbed_text(self) -> None:
        out = self.record()
        self.assertEqual(out["status"], "OK", out)
        self.assertTrue(all(e["status"] == "RECORDED" for e in out["events"]), out)
        rows = self.rows()
        keys = sorted(r["evidence"]["cluster_key"] for r in rows)
        # 3 reviewer problems + 1 checklist DEFECT + 1 confirmed Gemini finding; the dismissed one is left out
        self.assertEqual(len(rows), 5, keys)
        # 2026-11-20 global fast-track: picture / model / edit findings are language-independent (|global)
        self.assertIn("FINAL_REVIEW:BURNED_TEXT|global", keys)
        self.assertIn("FINAL_REVIEW:BGM_FADES|global", keys)
        self.assertNotIn("FINAL_REVIEW:FACE_DRIFT|global", keys)
        by_route = {}
        for r in rows:
            ev = r["evidence"]
            self.assertEqual(ev["language"], "ko")
            self.assertTrue(ev["cluster_key"].startswith(ev["failure_type"] + "|"))
            by_route.setdefault(ev["lesson_route"], []).append(r)
        self.assertEqual({r["evidence"]["failure_type"] for r in by_route["MODEL_CONSTRAINT"]},
                         {"FINAL_REVIEW:BURNED_TEXT"})
        bgm = next(r for r in rows if r["evidence"]["failure_type"] == "FINAL_REVIEW:BGM_FADES")
        self.assertEqual((bgm["evidence"]["lesson_route"], bgm["evidence"]["lesson_class"], bgm["stage"]),
                         ("ENGINE", "ENGINE_THRESHOLD", "S7"))
        author = [r for r in by_route["DIRECTING_GUIDANCE"]]
        self.assertTrue(author)
        self.assertTrue(all(r["stage"] == "SCRIPT_AUTHORING" for r in author))
        blob = json.dumps([r["evidence"] for r in rows] + [r["symptom"] for r in rows], ensure_ascii=False)
        for secret in ("금민준", "이서준", "/Users"):
            self.assertNotIn(secret, blob)
        self.assertIn("Character A", blob)  # the cast name became a role
        self.assertEqual(c.sensitive_findings([r["evidence"] for r in rows]), [])
        # the release train sees them as lessons (author / model) or engine items (ENGINE)
        for r in rows:
            event = {**r, "event_kind": "FAILURE_OBSERVATION"}
            self.assertEqual(rt_mod.cluster_key(event), r["evidence"]["cluster_key"])
            self.assertEqual(rt_mod.is_lesson(event), r["evidence"]["lesson_route"] != "ENGINE")
        sample = rt_mod.evidence_sample(author[0])
        self.assertEqual((sample["language"], sample["lesson_route"]), ("ko", "DIRECTING_GUIDANCE"))
        # re-entry is deduplicated
        again = self.record()
        self.assertEqual({e["status"] for e in again["events"]}, {"DUPLICATE"})

    def test_checklist_of_another_cut_and_missing_report(self) -> None:
        out = self.record(media_sha256="d" * 64)
        self.assertEqual({r["evidence"]["detail"]["source"] for r in self.rows()}, {"REVIEW_PROBLEM"}, out)
        self.assertEqual(kbe.record_final_review_findings(self.rt, episode="E01", report_path=None)["status"],
                         "NO_REVIEW_REPORT")
        clean = _write(self.rt / "clean.json", {"verdict": "PASS", "problems": []})
        self.assertEqual(kbe.record_final_review_findings(self.rt, episode="E02", report_path=str(clean))["status"],
                         "NO_FINDINGS")

    def test_language_normalisation(self) -> None:
        self.assertEqual([kbe.final_review_language(x) for x in ("ko-KR", "ja", "zh_CN", "", None, "EN")],
                         ["ko", "ja", "zh", "zh", "zh", "en"])


class PipelineHookTest(unittest.TestCase):
    def test_hook_passes_report_checklist_language_and_cast(self) -> None:
        import nalu_pipeline as mod
        base = Path(tempfile.mkdtemp())
        report = _write(base / "final_qa" / "E01_AUDIENCE_SCORE_REPORT.json", REPORT)
        _write(base / "final_qa" / "E01_QA_DEFECT_CHECKLIST.json", CHECKLIST)
        contract = _write(base / "E01_GENERATION_CONTRACT_v1.json", {
            "character_entities": [{"character_id": "CHAR-KIM", "canonical_name": "금민준", "aliases": ["민준"]}],
            "audio_contract": {"dialogue_units": [{"text": "다시는 오지 마"}]}})
        ctx = SimpleNamespace(episode="E01", language="ko", p=SimpleNamespace(contract=contract, assembly=base))
        calls = []
        with mock.patch.object(mod, "kb_events", side_effect=lambda fn, **kw: calls.append((fn, kw)) or {"status": "OK"}):
            out = mod.kb_final_review_findings(ctx, {"report": str(report), "final_video_sha256": SHA})
        self.assertEqual(out, {"status": "OK"})
        fn, kw = calls[0]
        self.assertEqual(fn, "record_final_review_findings")
        self.assertEqual((kw["language"], kw["media_sha256"], kw["review_round"]), ("ko", SHA, "first"))
        self.assertTrue(kw["checklist_path"].endswith("E01_QA_DEFECT_CHECKLIST.json"))
        self.assertIn(("CHAR-KIM", "민준"), kw["cast_names"])
        self.assertEqual(kw["dialogue_lines"], ["다시는 오지 마"])
        # after a fix round the second review is tagged
        _write(base / "final_qa" / "final_fix_round.json",
               {"status": "S7_RERUN", "first_review": {"final_video_sha256": "e" * 64}})
        with mock.patch.object(mod, "kb_events", side_effect=lambda fn, **kw: calls.append((fn, kw)) or {"status": "OK"}):
            mod.kb_final_review_findings(ctx, {"report": str(report), "final_video_sha256": SHA})
        self.assertEqual(calls[-1][1]["review_round"], "after_fix")

    def test_s7_calls_the_hook_next_to_the_qa_defects(self) -> None:
        src = (TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")
        qa = src.index('res.details["knowledge_events_qa_defects"] = kb_qa_defects(ctx, final_audience)')
        hook = src.index('res.details["knowledge_events_final_review_findings"] = kb_final_review_findings(')
        self.assertLess(qa, hook)
        self.assertLess(hook - qa, 200)


class AuthorThresholdTest(Harness):
    def ev(self, device: str, episode: str, ft: str, **evidence) -> None:
        principal = rt_mod.svc_mod.Principal(device, "nalu", "device_writer", ("nalu",))
        event = c.make_observation(
            tenant_id="nalu", line_id="nalu", device_id=device, run_id=f"nalu.{episode}.B1", episode_id=episode,
            stage="S7", event_kind="FAILURE_OBSERVATION", symptom=f"synthetic {ft} {device} {episode}",
            evidence={"failure_type": ft, **evidence}, detected_by="nalu_pipeline", producer_sequence=1,
            unit_ids=[], visibility="LINE", occurred_at=rt_mod._iso(T0 - 3600),
            opportunity={"applicable_units": 1, "observed_units": 1}, provider_model_version="MiniMax-H3")
        self.assertEqual(self.svc.ingest_events(principal, [event])[0]["status"], "CREATED")

    def test_author_lessons_learn_from_one_device_two_episodes(self) -> None:
        for ep in ("E01", "E02"):
            self.ev("sn-r1", ep, "FINAL_REVIEW:PACING", cluster_key="FINAL_REVIEW:PACING|ko",
                    lesson_route="DIRECTING_GUIDANCE", language="ko")
            self.ev("sn-r1", ep, "CRAFT_STD_GAP", cluster_key="CRAFT_STD_GAP|S-03", language="ko")
            self.ev("sn-r1", ep, "FINAL_REVIEW:BURNED_TEXT", cluster_key="FINAL_REVIEW:BURNED_TEXT|ko",
                    lesson_route="MODEL_CONSTRAINT", language="ko")
            self.ev("sn-r1", ep, "FINAL_REVIEW:BGM_FADES", cluster_key="FINAL_REVIEW:BGM_FADES|ko",
                    lesson_route="ENGINE", lesson_class="ENGINE_THRESHOLD", language="ko")
        self.ev("sn-r2", "E01", "FINAL_REVIEW:STORY", cluster_key="FINAL_REVIEW:STORY|ja",
                lesson_route="DIRECTING_GUIDANCE", language="ja")              # one episode: not yet
        clusters = {cl["cluster_key"]: cl for cl in self.train.clusters()}
        self.assertNotIn("FINAL_REVIEW:BGM_FADES|ko", clusters)               # engine item, never a lesson
        self.assertTrue(clusters["FINAL_REVIEW:PACING|ko"]["eligible"])
        self.assertTrue(clusters["CRAFT_STD_GAP|S-03"]["eligible"])
        self.assertFalse(clusters["FINAL_REVIEW:BURNED_TEXT|ko"]["eligible"])  # model constraint: strict thresholds
        self.assertFalse(clusters["FINAL_REVIEW:STORY|ja"]["eligible"])
        pacing = clusters["FINAL_REVIEW:PACING|ko"]
        self.assertEqual((pacing["lesson_route"], pacing["languages"], pacing["thresholds"]),
                         ("DIRECTING_GUIDANCE", ["ko"], {"min_devices": 2, "min_episodes": 2}))
        self.assertEqual(clusters["CRAFT_STD_GAP|S-03"]["lesson_route"], "DIRECTING_GUIDANCE")
        request = self.request()
        self.assertEqual({cl["cluster_key"] for cl in request["clusters"]},
                         {"FINAL_REVIEW:PACING|ko", "CRAFT_STD_GAP|S-03"})
        self.assertEqual((request["thresholds"]["directing_min_devices"], request["thresholds"]["directing_min_episodes"]),
                         (2, 2))
        self.assertIn("FINAL_REVIEW:<kind>|<language>", request["instructions"])
        self.assertIn("AUTHOR-side lesson", request["instructions"])
        # the old strict behaviour is one config away
        strict = self.make_train(directing_min_devices=3, directing_min_episodes=5)
        self.assertFalse({cl["cluster_key"]: cl for cl in strict.clusters()}["FINAL_REVIEW:PACING|ko"]["eligible"])

    def test_zero_cluster_request_closes_with_empty_decisions(self) -> None:
        state = self.train.state()
        state["open_review"] = "rv-zero"
        (self.train.dir / "review_requests").mkdir(parents=True, exist_ok=True)
        (self.train.dir / "review_requests" / "rv-zero.json").write_text(json.dumps({"request_id": "rv-zero",
                                                                                       "clusters": []}))
        self.train.save(state)
        out = self.train.import_review({"schema": rt_mod.RESULT_SCHEMA, "request_id": "rv-zero", "decisions": [],
                                        "exemplar_veto": ["ex-0123456789abcdef"], "exemplar_veto_reason": "leak"})
        self.assertEqual(out["status"], "IMPORTED")
        self.assertIsNone(self.train.state()["open_review"])
        self.assertIn("ex-0123456789abcdef", self.train.state()["exemplars"]["vetoed"])


if __name__ == "__main__":
    unittest.main()
