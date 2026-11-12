"""Production event sources for the collective knowledge base (audit 2026-11-12 §6: zero producers).

Offline, fakes only: the pipeline's S5 Q1 / S6 Q2 / post-generation QA / S7 final-review hooks call
``nalu_knowledge_events`` through ``nalu_pipeline.kb_events``; facts go through
``knowledge_event_log.record_event`` (JSONL + the opt-in DeviceStore mirror); every hook is best-effort
and idempotent; HopsAPI 424s are split into content rejections (lessons) and outages (anomalies)."""
from __future__ import annotations

import importlib
import json
import os
import sqlite3
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

import nalu_knowledge_events as kbe  # noqa: E402
from tools import knowledge_event_log as kel  # noqa: E402


def _rt(config: bool = True) -> Path:
    rt = Path(tempfile.mkdtemp()) / "runtime"
    (rt / "reports").mkdir(parents=True)
    if config:
        (rt / "reports" / "COLLECTIVE_LEARNING_CONFIG.json").write_text(json.dumps({
            "tenant_id": "nalu", "line_id": "nalu", "device_id": "sn-test-1", "device_store": True,
            "batch_id": "B1", "trust_store": "trust.json", "cache_dir": "bundle_cache", "engine_api_version": "x"}))
    return rt


def _store_events(rt: Path) -> list[dict]:
    path = rt / "reports" / "COLLECTIVE_DEVICE_STORE.sqlite"
    if not path.exists():
        return []
    with sqlite3.connect(path) as db:
        return [json.loads(r[0]) for r in db.execute("SELECT payload FROM events ORDER BY producer_sequence")]


class ReviewRoundTest(unittest.TestCase):
    def test_round_rate_fact_and_one_event_per_failure_code_mirrored_once(self) -> None:
        rt = _rt()
        rows = [{"unit_id": "E01-VU-001", "passed": True, "codes": []},
                {"unit_id": "E01-VU-002", "passed": False, "codes": ["FACE_COUNT_ZERO:S01-02", "OCR_LATIN:x"]},
                {"unit_id": "E01-VU-003", "passed": False, "codes": ["FACE_COUNT_ZERO:S02-01"]}]
        out = kbe.record_review_round(rt, episode="E01", stage="S5", kind="Q1", round_key="ab" * 32, rows=rows,
                                      evidence={"gate": "g", "review": "/Us" + "ers/someone/reviews/E01_q1.json"})
        self.assertEqual([e["status"] for e in out["events"]], ["RECORDED"] * 3, out)
        types = sorted(e["failure_type"] for e in out["events"])
        self.assertEqual(types, ["Q1_REJECT:FACE_COUNT_ZERO", "Q1_REJECT:OCR_LATIN", "Q1_ROUND"])
        events = _store_events(rt)
        self.assertEqual(len(events), 3)
        by_type = {e["evidence"]["failure_type"]: e for e in events}
        self.assertEqual(by_type["Q1_ROUND"]["event_kind"], "FAILURE_OBSERVATION")
        self.assertEqual(by_type["Q1_ROUND"]["opportunity"], {"applicable_units": 3, "observed_units": 2})
        self.assertEqual(by_type["Q1_REJECT:FACE_COUNT_ZERO"]["unit_ids"], ["E01-VU-002", "E01-VU-003"])
        self.assertEqual(by_type["Q1_REJECT:FACE_COUNT_ZERO"]["device_id"], "sn-test-1")
        # the absolute path was reduced to its basename before it could be refused by the public-bucket filter
        self.assertEqual(by_type["Q1_ROUND"]["evidence"]["review"], "E01_q1.json")
        # re-entry with the same review round records nothing new
        again = kbe.record_review_round(rt, episode="E01", stage="S5", kind="Q1", round_key="ab" * 32, rows=rows)
        self.assertEqual({e["status"] for e in again["events"]}, {"DUPLICATE"})
        self.assertEqual(len(_store_events(rt)), 3)
        self.assertEqual(len(kel.events(rt)), 3)

    def test_all_pass_round_is_a_success_observation(self) -> None:
        rt = _rt()
        rows = [{"unit_id": f"E02-VU-00{i}", "passed": True} for i in range(1, 5)]
        out = kbe.record_review_round(rt, episode="E02", stage="S6", kind="Q2", round_key="r1", rows=rows)
        self.assertEqual(len(out["events"]), 1)
        event = _store_events(rt)[0]
        self.assertEqual((event["event_kind"], event["evidence"]["failure_type"]), ("SUCCESS_OBSERVATION", "Q2_ROUND"))
        self.assertEqual(event["opportunity"], {"applicable_units": 4, "observed_units": 4})

    def test_inactive_without_config_still_records_locally(self) -> None:
        rt = _rt(config=False)
        out = kbe.record_review_round(rt, episode="E01", stage="S6", kind="POSTGEN", round_key="r",
                                      rows=[{"unit_id": "E01-VU-001", "passed": False, "codes": ["BLACK_FRAMES"]}])
        self.assertEqual({e["mirror"] for e in out["events"]}, {"INACTIVE"})
        self.assertEqual(len(kel.events(rt)), 2)
        self.assertFalse((rt / "reports" / "COLLECTIVE_DEVICE_STORE.sqlite").exists())

    def test_logging_failure_never_raises(self) -> None:
        rt = _rt()
        with mock.patch.object(kbe._kel(), "record_event", side_effect=RuntimeError("disk full")):
            out = kbe.record_review_round(rt, episode="E01", stage="S5", kind="Q1", round_key="r",
                                          rows=[{"unit_id": "E01-VU-001", "passed": False, "codes": ["X_Y"]}])
        self.assertEqual({e["status"] for e in out["events"]}, {"ERROR"})
        # nothing was marked emitted: the next round retries
        out = kbe.record_review_round(rt, episode="E01", stage="S5", kind="Q1", round_key="r",
                                      rows=[{"unit_id": "E01-VU-001", "passed": False, "codes": ["X_Y"]}])
        self.assertEqual({e["status"] for e in out["events"]}, {"RECORDED"})
        self.assertEqual(kbe.emit(Path("/nonexistent-root-for-test") / "x", episode="", stage="", failure_type="t",
                                  symptom="", evidence={}, dedupe_key="k")["status"], "ERROR")

    def test_final_cut_events_deduped_per_candidate_sha(self) -> None:
        rt = _rt()
        out = kbe.record_final_cut(rt, episode="E03", kind="S7_DETECTOR", items=["hook_present", "loudness"],
                                   media_sha256="c" * 64)
        self.assertEqual([e["failure_type"] for e in out["events"]], ["S7_DETECTOR:hook_present", "S7_DETECTOR:loudness"])
        again = kbe.record_final_cut(rt, episode="E03", kind="S7_DETECTOR", items=["loudness"], media_sha256="c" * 64)
        self.assertEqual(again["events"][0]["status"], "DUPLICATE")
        recut = kbe.record_final_cut(rt, episode="E03", kind="S7_DETECTOR", items=["loudness"], media_sha256="d" * 64)
        self.assertEqual(recut["events"][0]["status"], "RECORDED")
        gate = kbe.record_final_cut(rt, episode="E03", kind="S7_FINAL_GATE", items=["final:FINAL-AUDIT"],
                                    media_sha256="d" * 64)
        self.assertEqual(gate["events"][0]["failure_type"], "S7_FINAL_GATE:FINAL-AUDIT")
        rej = kbe.record_final_cut(rt, episode="E03", kind="S7_FINAL_REVIEW_REJECT", items=["low:pacing"],
                                   media_sha256="d" * 64)
        self.assertEqual(rej["events"][0]["failure_type"], "S7_FINAL_REVIEW_REJECT")


def _tx(store: Path, name: str, *, task_key: str, status: str, at: str, code=424, cost=0.0, model="gpt-image-2"):
    row = {"provider": "hopsapi", "provider_model": model, "task_key": task_key, "task_id": f"t-{name}",
           "provider_remote_status": status, "provider_status_observed_at": at, "provider_cost_credits": cost}
    if status == "failed":
        row.update({"remote_terminal_state": "failed", "remote_terminal_observed_at": at, "provider_failure_code": code,
                    "provider_failure": "Provider error (request id: aitk-1)" if code == 424 else f"upstream {code}"})
    (store / f"{name}.json").write_text(json.dumps(row))


class ProviderRejectionTest(unittest.TestCase):
    def test_same_task_refused_twice_while_others_complete_is_content(self) -> None:
        store = Path(tempfile.mkdtemp())
        _tx(store, "a", task_key="S01-01", status="completed", at="2026-11-10T10:00:00Z", cost=1.2)
        _tx(store, "b.terminal-1", task_key="S01-02", status="failed", at="2026-11-10T10:01:00Z")
        _tx(store, "b", task_key="S01-02", status="failed", at="2026-11-10T10:20:00Z")
        _tx(store, "c", task_key="S01-03", status="failed", at="2026-11-10T10:21:00Z")  # once: ambiguous
        verdict = kbe.classify_424s(kbe._settled_rows(store))
        self.assertEqual(verdict["outages"], [])
        self.assertEqual([r["task"] for r in verdict["content"]], ["S01-02"])

    def test_burst_across_tasks_without_completion_is_outage_not_content(self) -> None:
        store = Path(tempfile.mkdtemp())
        for i, minute in enumerate((0, 1, 2, 3)):
            _tx(store, f"o{i}", task_key=f"S0{i}-01", status="failed", at=f"2026-11-10T11:0{minute}:00Z")
        _tx(store, "o0b", task_key="S00-01", status="failed", at="2026-11-10T11:05:00Z")
        _tx(store, "late", task_key="S09-01", status="completed", at="2026-11-10T11:30:00Z", cost=1.2)
        verdict = kbe.classify_424s(kbe._settled_rows(store))
        self.assertEqual(len(verdict["outages"]), 1)
        self.assertEqual(verdict["content"], [], "refusals inside an outage are never content lessons")
        # charged failures and other codes are not 424 content facts at all
        _tx(store, "charged", task_key="S20-01", status="failed", at="2026-11-10T13:00:00Z", cost=2.0)
        _tx(store, "other", task_key="S21-01", status="failed", at="2026-11-10T13:00:00Z", code=500)
        rows = kbe._settled_rows(store)
        self.assertNotIn("S20-01", {r["task"] for r in rows})
        self.assertNotIn("S21-01", {r["task"] for r in rows})

    def test_scan_records_content_as_failure_and_outage_as_anomaly_once(self) -> None:
        rt = _rt()
        image = Path(tempfile.mkdtemp())
        _tx(image, "ok", task_key="S01-01", status="completed", at="2026-11-10T10:00:00Z", cost=1.2)
        _tx(image, "r1.terminal-1", task_key="S01-02", status="failed", at="2026-11-10T10:01:00Z")
        _tx(image, "r1", task_key="S01-02", status="failed", at="2026-11-10T10:30:00Z")
        video = Path(tempfile.mkdtemp())
        for i in range(3):
            _tx(video, f"v{i}", task_key=f"E01-VU-00{i}", status="failed", at=f"2026-11-10T12:0{i}:00Z",
                model="MiniMax-H3")
        out = kbe.scan_provider_rejections(rt, episode="E01", stores={"image": image, "video": video,
                                                                      "missing": image / "nope"})
        self.assertEqual(sorted(e["failure_type"] for e in out["events"]),
                         ["PROVIDER_CONTENT_REJECTION:image", "PROVIDER_OUTAGE:video"])
        kinds = {e["evidence"]["failure_type"]: e["event_kind"] for e in _store_events(rt)}
        self.assertEqual(kinds, {"PROVIDER_CONTENT_REJECTION:image": "FAILURE_OBSERVATION",
                                 "PROVIDER_OUTAGE:video": "RUN_ANOMALY"})
        again = kbe.scan_provider_rejections(rt, episode="E01", stores={"image": image, "video": video})
        self.assertEqual({e["status"] for e in again["events"]}, {"DUPLICATE"})


class PipelineHookTest(unittest.TestCase):
    """The real stage functions call the producer at their judgement points (helpers faked)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp())
        cls.old = os.environ.get("NALU_RUNTIME_ROOT")
        os.environ["NALU_RUNTIME_ROOT"] = str(cls.tmp / "rt")
        for name in ("nalu_paths", "nalu_pipeline"):
            sys.modules.pop(name, None)
        cls.mod = importlib.import_module("nalu_pipeline")

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.old is None:
            os.environ.pop("NALU_RUNTIME_ROOT", None)
        else:
            os.environ["NALU_RUNTIME_ROOT"] = cls.old

    def ctx(self) -> SimpleNamespace:
        base = Path(tempfile.mkdtemp())
        keyframes, media = base / "kf", base / "media"
        keyframes.mkdir(), media.mkdir()
        (keyframes / "S01-01-keyframe-v1.png").write_bytes(b"x")
        (media / "E01-VU-001.mp4").write_bytes(b"x")
        p = SimpleNamespace(preprod_reports=base / "reports", keyframes=keyframes, keyframe_admission=base / "adm.json",
                            video_media=media, postgen_qa=base / "pg.json")
        return SimpleNamespace(p=p, episode="E01", say=lambda *_: None)

    def _step(self, payload: dict) -> dict:
        return {"stdout_tail": json.dumps(payload), "exit_code": 0}

    def test_s5_q1_records_the_round(self) -> None:
        mod, ctx = self.mod, self.ctx()
        index_path = ctx.p.preprod_reports / "q1.json"
        index_path.parent.mkdir(parents=True)
        index = {"status": "PARTIAL_1_OF_2_ADMITTED", "results": [
            {"unit_id": "E01-VU-001", "downstream_status": "ADMITTED_FOR_VIDEO_SUBMIT", "failures": []},
            {"unit_id": "E01-VU-002", "downstream_status": "FAIL_NOT_ADMITTED", "failures": ["FACE_COUNT_ZERO:x"]}]}
        index_path.write_text(json.dumps(index))
        review = ctx.p.preprod_reports / "review.json"
        review.write_text("{}")
        calls = []
        with mock.patch.object(mod, "qa_run", side_effect=lambda c, argv, name: {"name": name}), \
                mock.patch.object(mod, "qa_json", side_effect=lambda step: {"status": "PARTIAL", "out": str(index_path)}
                                  if step["name"] == "s5_q1_build_admission" else {}), \
                mock.patch.object(mod, "latest_submitted_review", return_value=(review, {})), \
                mock.patch.object(mod, "apply_line_owner_q1_acceptance", return_value={}), \
                mock.patch.object(mod, "kb_events", side_effect=lambda fn, **kw: calls.append((fn, kw)) or {"status": "OK"}):
            detail = mod.s5_q1(ctx, mod.StageResult("RUNNING"))
        self.assertEqual(detail["status"], mod.BLOCKED)
        self.assertEqual(detail["knowledge_events"], {"status": "OK"})
        fn, kw = calls[0]
        self.assertEqual((fn, kw["kind"], kw["stage"]), ("record_review_round", "Q1", "S5"))
        self.assertEqual([r["passed"] for r in kw["rows"]], [True, False])
        self.assertEqual(kw["rows"][1]["codes"], ["FACE_COUNT_ZERO:x"])

    def test_s6_q2_and_postgen_record_their_rounds(self) -> None:
        mod, ctx = self.mod, self.ctx()
        d = ctx.p.preprod_reports
        d.mkdir(parents=True)
        q2_index = d / "q2.json"
        q2_index.write_text(json.dumps({"results": [
            {"unit_id": "E01-VU-001", "downstream_status": "FAIL", "failures": ["IDENTITY_LOW:x"]}]}))
        pg = d / "pg_summary.json"
        pg.write_text(json.dumps({"units": [{"unit_id": "E01-VU-001", "verdict": "REJECT", "reasons": ["BLACK_FRAMES"]}]}))
        review = d / "review.json"
        review.write_text("{}")
        calls = []

        def fake_json(step):
            return {"s6_q2_prepare_frames_ocr_identity": {"status": "READY"},
                    "s6_q2_build_admission": {"status": "PARTIAL", "out": str(q2_index)},
                    "s6_qa_post_generation_qa_runner": {"status": "PARTIAL_0_OF_1", "out": str(pg)}}.get(step["name"], {})

        with mock.patch.object(mod, "qa_run", side_effect=lambda c, argv, name: {"name": name}), \
                mock.patch.object(mod, "qa_json", side_effect=fake_json), \
                mock.patch.object(mod, "s6_q2_auto_redo", return_value={"status": "NONE"}), \
                mock.patch.object(mod, "latest_submitted_review", return_value=(review, {})), \
                mock.patch.object(mod, "ctx_language", return_value="zh"), \
                mock.patch.object(mod, "kb_events", side_effect=lambda fn, **kw: calls.append((fn, kw)) or {"status": "OK"}):
            q2 = mod.s6_q2(ctx, mod.StageResult("RUNNING"))
            qa = mod.s6_qa(ctx, mod.StageResult("RUNNING"))
        self.assertEqual((q2["knowledge_events"], qa["knowledge_events"]), ({"status": "OK"}, {"status": "OK"}))
        self.assertEqual([(kw["kind"], kw["rows"][0]["codes"]) for _, kw in calls],
                         [("Q2", ["IDENTITY_LOW:x"]), ("POSTGEN", ["BLACK_FRAMES"])])

    def test_final_review_reject_records_reject_and_low_dimensions(self) -> None:
        mod = self.mod
        report = Path(tempfile.mkdtemp()) / "report.json"
        report.write_text(json.dumps({"verdict": "REJECT_RECUT", "overall": 2.5, "hard_fail": False,
                                      "dimensions": {"pacing": 2, "acting": 4, "clarity": 2.5}}))
        calls = []
        with mock.patch.object(mod, "kb_events", side_effect=lambda fn, **kw: calls.append(kw) or {"status": "OK"}):
            mod.kb_final_review_reject(SimpleNamespace(episode="E01"),
                                       {"report": str(report), "final_video_sha256": "e" * 64})
        self.assertEqual([c["kind"] for c in calls], ["S7_FINAL_REVIEW_REJECT", "S7_FINAL_REVIEW_LOW"])
        self.assertEqual(calls[1]["items"], ["clarity", "pacing"])

    def test_kb_events_is_best_effort_and_has_a_kill_switch(self) -> None:
        mod = self.mod
        with mock.patch.object(kbe, "record_final_cut", side_effect=RuntimeError("boom")):
            out = mod.kb_events("record_final_cut", episode="E01", kind="S7_DETECTOR", items=["x"], media_sha256=None)
        self.assertEqual(out["status"], "ERROR")
        with mock.patch.dict(os.environ, {"NALU_KNOWLEDGE_EVENTS": "off"}):
            self.assertEqual(mod.kb_events("record_final_cut", episode="E01", kind="S7_DETECTOR", items=["x"],
                                           media_sha256=None), {"status": "DISABLED"})

    def test_stage_s7_and_stage_loop_call_the_producers(self) -> None:
        source = (TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")
        for needle in ('kind="S7_DETECTOR"', 'kind="S7_FINAL_GATE"', "kb_final_review_reject(ctx, final_audience)",
                       '"scan_provider_rejections"'):
            self.assertIn(needle, source)


if __name__ == "__main__":
    unittest.main()
