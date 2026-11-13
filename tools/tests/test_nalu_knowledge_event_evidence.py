"""Evidence quality of the collective-learning production events (first daily review 2026-11-13 rejected all
46 clusters: thin evidence, S7 gates that only "failed" as bookkeeping, run-level technical noise).

Offline, fakes only.  Covers: S7 final-package rows that are not failures of their own are not recorded;
genuine failures carry the concrete cause (measured vs threshold, unit context, excerpts); the public-bucket
filter still sees no paths / URLs / secrets; the release train clusters on the finer key, keeps engine items
and default-accepted facts out of the candidates, and puts concrete samples into the review request."""
from __future__ import annotations

import json
import sqlite3
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

import nalu_knowledge_events as kbe  # noqa: E402
from tools.collective_learning import contracts as c  # noqa: E402
from tools.collective_learning import release_train as rt  # noqa: E402
from tools.collective_learning import service as svc_mod  # noqa: E402
from tools.tests.test_collective_release_train import TENANT, Harness  # noqa: E402

HOME = "/Us" + "ers/someone"


def _rt() -> Path:
    root = Path(tempfile.mkdtemp()) / "runtime"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "COLLECTIVE_LEARNING_CONFIG.json").write_text(json.dumps({
        "tenant_id": "nalu", "line_id": "nalu", "device_id": "sn-test-1", "device_store": True,
        "batch_id": "B1", "trust_store": "trust.json", "cache_dir": "bundle_cache", "engine_api_version": "x"}))
    return root


def _store_events(root: Path) -> list[dict]:
    path = root / "reports" / "COLLECTIVE_DEVICE_STORE.sqlite"
    if not path.exists():
        return []
    with sqlite3.connect(path) as db:
        return [json.loads(r[0]) for r in db.execute("SELECT payload FROM events ORDER BY producer_sequence")]


def _write(path: Path, payload: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False))
    return str(path)


class FinalGateClassificationTest(unittest.TestCase):
    def _summary(self, base: Path) -> tuple[str, list[dict]]:
        quality_combined = {"gate_status": "ESCALATE_TO_SUPERVISOR", "findings": [
            {"severity": "ESCALATE", "gate": "G5_NO_SELF_WAIVER", "detail": "problems reported; adjudication "
             "belongs to supervisor/Roger, not the gate", "count": 4},
            {"severity": "OBSERVE", "gate": "G6_LOCATION_DIVERSITY", "detail": "observation only"}]}
        quality_blocked = {"gate_status": "REJECT_RECUT", "findings": [
            {"severity": "BLOCKER", "gate": "G4_WEAKEST_LINK", "detail": "weakest craft dimension pacing=2.0 < 3",
             "dimension": "pacing", "score": 2.0},
            {"severity": "ESCALATE", "gate": "G5_NO_SELF_WAIVER", "detail": "problems reported"}]}
        out = base / "gates"
        rows = [
            {"gate_id": "FINAL-CUT-NO-SELF-WAIVER", "invoked": True, "status": "FAIL",
             "output": _write(out / "a.json", quality_combined), "failures": ["gate_execution_failed"]},
            {"gate_id": "FINAL-CUT-GATE-NAMING-HONESTY", "invoked": True, "status": "FAIL",
             "output": _write(out / "b.json", quality_blocked), "failures": ["gate_execution_failed"]},
            {"gate_id": "FINAL-CUT-WEAKEST-LINK-SCORING", "invoked": True, "status": "FAIL",
             "output": _write(out / "c.json", quality_blocked), "failures": ["gate_execution_failed"]},
            {"gate_id": "AUDIENCE-SCORE-PRE-RELEASE", "invoked": True, "status": "FAIL",
             "output": _write(out / "d.json", {"gate_status": "INVALID", "validation_failures": [
                 "technical_gate_must_pass_before_audience_gate"]}), "failures": ["gate_execution_failed"]},
            {"gate_id": "FINAL-AUDIO-PROVENANCE", "invoked": False, "status": "FAIL", "failures": [
                f"required_evidence_missing:audio_provenance_manifest:missing:{HOME}/w/E01_AUDIO_PROVENANCE.json"]},
            {"gate_id": "RELEASE-SIGNOFF-INTEGRITY", "invoked": False, "status": "FAIL", "failures": [
                f"required_evidence_missing:watch_report:missing:{HOME}/rt/approvals/E01.APPROVED.json"]},
            {"gate_id": "GIGGLE-CREDIT-LEDGER-CLOSURE", "invoked": True, "status": "FAIL",
             "output": _write(out / "e.json", {"status": "FAIL", "failures": ["invalid_schema"]}),
             "failures": ["gate_execution_failed"]},
            {"gate_id": "FINAL-CUT-AUDIENCE-DETECTORS", "invoked": True, "status": "FAIL",
             "output": _write(out / "f.json", {"status": "FAIL", "failures": ["loudness:FAIL:TRUE_PEAK_OVER:-0.1"]}),
             "failures": ["gate_execution_failed"]},
            {"gate_id": "FINAL-STATIC-HOLD", "invoked": True, "status": "FAIL",
             "output": _write(out / "g.json", {"status": "FAIL", "failures": [
                 "ci_component_failed:static_hold_gate:FAIL"], "evidence": {"component": "static_hold_gate",
                 "result": {"status": "FAIL", "longest_hold_s": 6.2, "limit_s": 4.0}}}),
             "failures": ["gate_execution_failed"]},
            {"gate_id": "FINAL-OCR-POLICY", "invoked": True, "status": "PASS", "failures": []},
        ]
        path = _write(base / "summary.json", {"status": "FAIL", "results": rows})
        compact = [{"gate_id": r["gate_id"], "status": r["status"], "first_failure": (r["failures"] or [None])[0]}
                   for r in rows]
        return path, compact

    def test_bookkeeping_and_combined_verdict_rows_are_not_recorded(self) -> None:
        root, base = _rt(), Path(tempfile.mkdtemp())
        summary, rows = self._summary(base)
        out = kbe.record_final_gates(root, episode="E01", summary_path=summary, rows=rows, media_sha256="a" * 64)
        recorded = sorted(e["failure_type"] for e in out["events"] if e["status"] == "RECORDED")
        self.assertEqual(recorded, ["S7_FINAL_GATE:FINAL-CUT-WEAKEST-LINK-SCORING", "S7_FINAL_GATE:FINAL-STATIC-HOLD"])
        reasons = {s["gate_id"]: s["reason"] for s in out["skipped"]}
        self.assertEqual(reasons, {
            "FINAL-CUT-NO-SELF-WAIVER": "COMBINED_VERDICT_NO_OWN_FINDING",      # ESCALATE only: informational
            "FINAL-CUT-GATE-NAMING-HONESTY": "COMBINED_VERDICT_NO_OWN_FINDING",  # failed on G4's finding
            "AUDIENCE-SCORE-PRE-RELEASE": "CASCADE_OR_REVIEW_DUPLICATE",
            "FINAL-AUDIO-PROVENANCE": "EVIDENCE_NOT_PRODUCED",
            "RELEASE-SIGNOFF-INTEGRITY": "EVIDENCE_NOT_PRODUCED",
            "GIGGLE-CREDIT-LEDGER-CLOSURE": "ENGINE_BOOKKEEPING",
            "FINAL-CUT-AUDIENCE-DETECTORS": "DUPLICATE_OF_DETECTOR_EVENTS"})
        events = {e["evidence"]["failure_type"]: e for e in _store_events(root)}
        self.assertEqual(len(events), 2, "skipped rows never reach the outbox")
        weakest = events["S7_FINAL_GATE:FINAL-CUT-WEAKEST-LINK-SCORING"]["evidence"]
        self.assertEqual(weakest["cluster_key"], "S7_FINAL_GATE:FINAL-CUT-WEAKEST-LINK-SCORING|g4_weakest_link")
        self.assertEqual(weakest["detail"]["findings"][0]["dimension"], "pacing")
        self.assertNotIn("default_accepted", weakest)
        hold = events["S7_FINAL_GATE:FINAL-STATIC-HOLD"]["evidence"]
        self.assertEqual(hold["detail"]["measured"]["longest_hold_s"], 6.2)
        self.assertIn("ci_component_failed", events["S7_FINAL_GATE:FINAL-STATIC-HOLD"]["symptom"])
        self.assertEqual(c.sensitive_findings(_store_events(root)), [])

    def test_failure_already_accepted_by_order_is_flagged_and_excluded_by_default(self) -> None:
        root, base = _rt(), Path(tempfile.mkdtemp())
        summary, rows = self._summary(base)
        kbe.record_final_gates(root, episode="E01", summary_path=summary, rows=rows, media_sha256="b" * 64,
                               accepted_order_seq=17)
        events = _store_events(root)
        self.assertTrue(events)
        self.assertTrue(all(e["evidence"]["default_accepted"] is True and e["evidence"]["accepted_order_seq"] == 17
                            for e in events))
        self.assertTrue(all(not rt.is_lesson(e) for e in events))
        self.assertTrue(all(rt.is_lesson(e, include_default_accepted=True) for e in events))


class DetectorAndReviewEvidenceTest(unittest.TestCase):
    def test_detector_events_carry_codes_measured_and_threshold(self) -> None:
        root, base = _rt(), Path(tempfile.mkdtemp())
        report = _write(base / "det.json", {"detectors": {
            "loudness": {"status": "FAIL", "measured": {"integrated_lufs": -14.0, "true_peak_dbtp": -0.1},
                         "threshold": {"true_peak_dbtp_max": -1.0}, "failures": ["TRUE_PEAK_OVER:-0.1"]},
            "voice_distinctness": {"status": "FAIL", "measured": {"lines_total": 13, "collisions": 2},
                                   "threshold": {"collision_ratio": 0.15},
                                   "evidence": {"failures": ["F0_COLLISION:E01-S02:CHAR-A/CHAR-B"],
                                                "note": f"see {HOME}/w/E01_windows.json"}},
            "hook_present": {"status": "PASS"}}})
        out = kbe.record_final_cut(root, episode="E01", kind="S7_DETECTOR", items=["loudness", "voice_distinctness"],
                                   media_sha256="c" * 64, evidence={"gate": "FINAL-CUT-AUDIENCE-DETECTORS"},
                                   detector_report=report)
        self.assertEqual([e["status"] for e in out["events"]], ["RECORDED", "RECORDED"])
        events = {e["evidence"]["failure_type"]: e for e in _store_events(root)}
        loud = events["S7_DETECTOR:loudness"]
        self.assertEqual(loud["evidence"]["detail"]["measured"]["true_peak_dbtp"], -0.1)
        self.assertEqual(loud["evidence"]["detail"]["threshold"]["true_peak_dbtp_max"], -1.0)
        self.assertEqual(loud["evidence"]["detail_category"], "true_peak_over")
        self.assertEqual(loud["evidence"]["lesson_class"], "ENGINE_THRESHOLD")
        self.assertFalse(rt.is_lesson(loud))
        voice = events["S7_DETECTOR:voice_distinctness"]
        self.assertEqual(voice["evidence"]["cluster_key"], "S7_DETECTOR:voice_distinctness|f0_collision")
        self.assertEqual(voice["evidence"]["detail"]["note"], "see E01_windows.json")
        self.assertTrue(rt.is_lesson(voice))
        self.assertEqual(c.sensitive_findings(_store_events(root)), [])

    def test_low_review_dimension_carries_reviewer_reason_and_problems(self) -> None:
        root, base = _rt(), Path(tempfile.mkdtemp())
        report = _write(base / "rev.json", {
            "verdict": "REJECT_RECUT", "overall": 2.5, "dimensions": {"pacing": 2.0},
            "dimension_reasons": {"pacing": "S02 holds the same two-shot for 9 s while nothing changes"},
            "problems": [{"severity": "P2", "shot_index": 4, "at_seconds": 30.0, "issue": "lip flap", "fix": "trim"},
                         {"severity": "P1", "shot_index": 7, "at_seconds": 41.5,
                          "issue": "static two-shot drags after the reveal line", "fix": "cut to the reaction"}]})
        kbe.record_final_cut(root, episode="E01", kind="S7_FINAL_REVIEW_LOW", items=["pacing"], media_sha256="d" * 64,
                             review_report=report)
        event = _store_events(root)[0]
        detail = event["evidence"]["detail"]
        self.assertEqual(detail["score"], 2.0)
        self.assertIn("same two-shot", detail["reviewer_reason"])
        self.assertEqual(detail["top_problems"][0]["severity"], "P1")
        self.assertIn("same two-shot", event["symptom"])


class ReviewRoundEvidenceTest(unittest.TestCase):
    def test_postgen_events_split_by_cause_with_transcript_and_measurements(self) -> None:
        root = _rt()
        transcript = ("他说你别走 " * 60) + f" saved to {HOME}/w/asr.json https://x.example/a?X-Amz-Signature=abc"
        record = {
            "item_id": "E01-S02-03",
            "technical_qa": {"checks": {
                "resolution": {"check": "resolution", "status": "FAIL", "measured": "480x854",
                               "expected": "720x1280 (SD2) or 768x1344..1366"},
                "freeze": {"check": "freeze", "status": "FAIL", "frozen_runs": [], "static_hold_status": "FAIL"}}},
            "dialogue_qa": {"status": "FAIL", "recall_score": 0.31, "minimum_recall": 0.55, "expected_line_count": 2,
                            "transcript": transcript, "gate_status": "FAIL", "language": "zh",
                            "gate_report": f"{HOME}/w/gate.json"},
            "basic_plot_qa": {"defects": [], "observation": "two people stand"}}
        rows = [{"unit_id": "E01-VU-004", "passed": False, "source": record, "codes": [
                    "resolution:FAIL", "freeze:FAIL", "dialogue:unexpected_native_mandarin_speech_present"]},
                {"unit_id": "E01-VU-005", "passed": False, "codes": ["dialogue:native_mandarin_speech_missing"]},
                {"unit_id": "E01-VU-006", "passed": True, "codes": []}]
        out = kbe.record_review_round(root, episode="E01", stage="S6", kind="POSTGEN", round_key="r1", rows=rows,
                                      evidence={"gate": "post_generation_qa_runner"})
        self.assertEqual({e["status"] for e in out["events"]}, {"RECORDED"})
        events = {e["evidence"].get("cluster_key") or e["evidence"]["failure_type"]: e for e in _store_events(root)}
        self.assertEqual(sorted(events), [
            "POSTGEN_FAIL:DIALOGUE|native_mandarin_speech_missing",
            "POSTGEN_FAIL:DIALOGUE|unexpected_native_mandarin_speech_present",
            "POSTGEN_FAIL:FREEZE|unmotivated_static_hold",
            "POSTGEN_FAIL:RESOLUTION",
            "POSTGEN_ROUND"])
        speech = events["POSTGEN_FAIL:DIALOGUE|unexpected_native_mandarin_speech_present"]
        sample = speech["evidence"]["samples"][0]
        self.assertEqual((sample["unit_id"], sample["item_id"]), ("E01-VU-004", "E01-S02-03"))
        self.assertEqual(sample["detail"]["recall_score"], 0.31)
        self.assertLessEqual(len(sample["detail"]["asr_transcript_excerpt"]), kbe.EXCERPT_MAX)
        self.assertNotIn("gate_report", json.dumps(speech["evidence"]))
        self.assertEqual(speech["evidence"]["failure_type"], "POSTGEN_FAIL:DIALOGUE")
        self.assertEqual(speech["unit_ids"], ["E01-VU-004"])
        resolution = events["POSTGEN_FAIL:RESOLUTION"]["evidence"]
        self.assertEqual(resolution["lesson_class"], "ENGINE_THRESHOLD")
        self.assertEqual(resolution["samples"][0]["detail"]["measured"], "480x854")
        self.assertIn("measured 480x854", events["POSTGEN_FAIL:RESOLUTION"]["symptom"])
        self.assertEqual(c.sensitive_findings(_store_events(root)), [])

    def test_q2_positional_evidence_codes_become_gates_and_defects_split(self) -> None:
        root = _rt()
        source = {"unit_id": "E03-VU-010", "item_id": "E03-S04-01", "asset_path": f"{HOME}/kf/x.png",
                  "vlm_verdict": "REJECT", "failures": [
                      "evidence_1:CHARACTER-IDENTITY-ADMISSION:registered_gate_not_pass:FAIL_NOT_ADMITTED:P0",
                      "evidence_5:DEFECT-TIER-TOLERANCE:registered_gate_not_pass:FAIL_NOT_ADMITTED:P1",
                      "required_registered_gate_not_pass:CHARACTER-IDENTITY-ADMISSION",
                      "required_registered_gate_not_pass:DEFECT-TIER-TOLERANCE"],
                  "blocking_defects": [{"code": "CAST_DUPLICATED_OR_EXTRA_PERSON", "severity": "P1", "shot_index": 1,
                                        "description": "后半段林乔复制成前后两人，声明仅一人。"}]}
        rows = [{"unit_id": "E03-VU-010", "passed": False, "codes": source["failures"], "source": source}]
        kbe.record_review_round(root, episode="E03", stage="S6", kind="Q2", round_key="r", rows=rows)
        keys = sorted(e["evidence"].get("cluster_key", "") for e in _store_events(root))
        self.assertEqual(keys, ["", "Q2_REJECT:CHARACTER_IDENTITY_ADMISSION|registered_gate_not_pass",
                                "Q2_REJECT:DEFECT_TIER_TOLERANCE|cast_duplicated_or_extra_person"])
        defect = [e for e in _store_events(root) if "DEFECT" in e["evidence"]["failure_type"]][0]
        self.assertEqual(defect["evidence"]["samples"][0]["detail"]["blocking_defects"][0]["code"],
                         "CAST_DUPLICATED_OR_EXTRA_PERSON")
        self.assertIn("复制成前后两人", defect["symptom"])
        self.assertNotIn("x.png", json.dumps(defect))

    def test_scrub_strips_paths_urls_and_secrets(self) -> None:
        text = (f"read {HOME}/w/E01/review.json then https://bucket.s3.amazonaws.com/x?X-Amz-Signature=deadbeef "
                "with Bearer abcdefghijklmnop and sk-ABCDEFGHIJKLMNOPQRST and C:\\Users\\me\\x.json")
        clean = kbe.excerpt(text, 500)
        self.assertEqual(c.sensitive_findings({"x": clean, "y": kbe._scrub({"t": text})}), [])
        self.assertIn("review.json", clean)
        self.assertNotIn("amazonaws", clean)
        self.assertLessEqual(len(kbe.excerpt("x" * 999)), kbe.EXCERPT_MAX)

    def test_provider_content_rejection_names_the_asset_kind(self) -> None:
        root, store = _rt(), Path(tempfile.mkdtemp())
        rows = [("ok", "S01-01", "completed", "2026-11-10T10:00:00Z", 1.2),
                ("r1.terminal-1", "CHAR-LINQIAO__FRONT_NEUTRAL_HEADSHOT", "failed", "2026-11-10T10:01:00Z", 0.0),
                ("r1", "CHAR-LINQIAO__FRONT_NEUTRAL_HEADSHOT", "failed", "2026-11-10T10:30:00Z", 0.0)]
        for name, key, status, at, cost in rows:
            row = {"provider": "hopsapi", "provider_model": "gpt-image-2", "task_key": key, "task_id": f"t-{name}",
                   "provider_remote_status": status, "provider_status_observed_at": at, "provider_cost_credits": cost,
                   "prompt_sha256": "ab" * 32, "reference_image_sha256s": ["cd" * 32],
                   "endpoint": "/api/v1/generation/image-to-image"}
            if status == "failed":
                row.update({"remote_terminal_state": "failed", "remote_terminal_observed_at": at,
                            "provider_failure_code": 424, "provider_failure": "Provider error (request id: aitk-1)"})
            (store / f"{name}.json").write_text(json.dumps(row))
        kbe.scan_provider_rejections(root, episode="E01", stores={"image": store})
        event = _store_events(root)[0]
        ev = event["evidence"]
        self.assertEqual((ev["asset_kind"], ev["view"]), ("character_reference", "front_neutral_headshot"))
        self.assertEqual(ev["cluster_key"], "PROVIDER_CONTENT_REJECTION:image|character_reference")
        detail = ev["samples"][0]["detail"]
        self.assertEqual((detail["endpoint"], detail["reference_images"], detail["identical_prompt_resubmitted"]),
                         ("image-to-image", 1, True))
        self.assertNotIn("prompt", json.dumps({k: v for k, v in ev.items() if k != "samples"}).replace(
            "identical_prompt", ""))


class ReleaseTrainEvidenceTest(Harness):
    def ev(self, device: str, episode: str, ft: str, evidence: dict | None = None, *, at: float | None = None) -> None:
        principal = svc_mod.Principal(device, TENANT, "device_writer", ("nalu",))
        event = c.make_observation(
            tenant_id=TENANT, line_id="nalu", device_id=device, run_id=f"nalu.{episode}.B1", episode_id=episode,
            stage="S6", event_kind="FAILURE_OBSERVATION", symptom=f"{ft} on {device} {episode}",
            evidence={"failure_type": ft, "gate": "test", **(evidence or {})}, detected_by="nalu_pipeline",
            producer_sequence=1, unit_ids=[f"{episode}-VU-001"], visibility="LINE",
            occurred_at=rt._iso(at if at is not None else self.clock[0] - 3600),
            opportunity={"applicable_units": 4, "observed_units": 1}, provider_model_version="MiniMax-H3")
        self.assertEqual(self.svc.ingest_events(principal, [event])[0]["status"], "CREATED")

    def test_finer_cluster_key_engine_items_default_accepted_and_samples(self) -> None:
        devices = ["sn-c1", "sn-r1", "sn-r2"]
        for i, d in enumerate(devices):
            self.ev(d, "E01", "POSTGEN_FAIL:DIALOGUE", {
                "failure_code": "DIALOGUE", "detail_category": "unexpected_native_mandarin_speech_present",
                "cluster_key": "POSTGEN_FAIL:DIALOGUE|unexpected_native_mandarin_speech_present",
                "samples": [{"unit_id": f"E01-VU-00{i}", "item_id": "E01-S01-01", "reason": "dialogue:unexpected",
                             "detail": {"asr_transcript_excerpt": "你别走"}}]})
            self.ev(d, "E01", "POSTGEN_FAIL:DIALOGUE", {
                "detail_category": "native_mandarin_speech_missing",
                "cluster_key": "POSTGEN_FAIL:DIALOGUE|native_mandarin_speech_missing"})
            self.ev(d, "E01", "POSTGEN_FAIL:DIALOGUE", {"samples": ["dialogue:x"]})              # old thin event
            self.ev(d, "E01", "POSTGEN_FAIL:RESOLUTION", {"samples": ["resolution:FAIL"]})        # legacy engine type
            self.ev(d, "E01", "POSTGEN_FAIL:FREEZE", {"lesson_class": "ENGINE_THRESHOLD",
                                                      "cluster_key": "POSTGEN_FAIL:FREEZE"})
            self.ev(d, "E01", "S7_FINAL_GATE:FINAL-STATIC-HOLD", {"default_accepted": True, "accepted_order_seq": 3})
            self.ev(d, "E01", "POSTGEN_FAIL:OTHER", {"cluster_key": "Q1_REJECT:FORGED|x"})       # inconsistent key
        clusters = {cl["cluster_key"]: cl for cl in self.train.clusters()}
        self.assertEqual(sorted(clusters), [
            "POSTGEN_FAIL:DIALOGUE",
            "POSTGEN_FAIL:DIALOGUE|native_mandarin_speech_missing",
            "POSTGEN_FAIL:DIALOGUE|unexpected_native_mandarin_speech_present",
            "POSTGEN_FAIL:OTHER"])
        # old thin events keep the cluster id they always had
        self.assertEqual(clusters["POSTGEN_FAIL:DIALOGUE"]["cluster_id"], rt.cluster_id("POSTGEN_FAIL:DIALOGUE"))
        fine = clusters["POSTGEN_FAIL:DIALOGUE|unexpected_native_mandarin_speech_present"]
        self.assertEqual((fine["failure_type"], fine["detail_category"]),
                         ("POSTGEN_FAIL:DIALOGUE", "unexpected_native_mandarin_speech_present"))
        request = self.request()
        by_key = {cl["cluster_key"]: cl for cl in request["clusters"]}
        samples = by_key["POSTGEN_FAIL:DIALOGUE|unexpected_native_mandarin_speech_present"]["evidence_samples"]
        self.assertEqual(len(samples), 3)
        self.assertEqual(len({s["device"] for s in samples}), 3)
        self.assertEqual(samples[0]["unit_samples"][0]["detail"]["asr_transcript_excerpt"], "你别走")
        self.assertEqual(by_key["POSTGEN_FAIL:DIALOGUE"]["evidence_samples"][0]["reasons"], ["dialogue:x"])
        engine = {row["cluster_key"] for row in request["engine_items"]["items"]}
        self.assertEqual(engine, {"POSTGEN_FAIL:RESOLUTION", "POSTGEN_FAIL:FREEZE"})
        self.assertIn("prompt rule cannot", request["engine_items"]["note"])
        # an approved fine cluster targets its cluster key; recurrence matches it
        cid = by_key["POSTGEN_FAIL:DIALOGUE|unexpected_native_mandarin_speech_present"]["cluster_id"]
        rule = {"rule_id": "kb-fine", "category": "MODEL_CONSTRAINT",
                "scope": {"models": ["MiniMax-H3"], "stages": ["VIDEO_COMPILE"]},
                "trigger": "a silent unit", "recommendation": "state silence explicitly", "exceptions": [],
                "verification": "rate drops", "cost_class": "FREE_COMPILE_REPLAY", "evidence_level": "MULTI_CASE",
                "validation_scope": "REAL_MEDIA_REVIEW",
                "application": {"carrier": "NEGATIVE_CONSTRAINT", "prompt_clause": {"zh": "无对白", "en": "no dialogue"}}}
        out = self.train.import_review({"schema": rt.RESULT_SCHEMA, "request_id": request["request_id"],
                                        "reviewer": "patrol", "decisions": [
                                            {"cluster_id": cid, "decision": "APPROVE", "reason": "prompt fix", "rule": rule}]})
        self.assertEqual(out["outcomes"][0]["status"], "VALIDATED", out)
        cand = self.svc.get_candidate(self.train.pub, "kb-fine")
        self.assertEqual(cand["payload"]["target_failure_types"],
                         ["POSTGEN_FAIL:DIALOGUE|unexpected_native_mandarin_speech_present"])
        with mock.patch.object(self.train, "receipts", return_value=[
                {"state": "APPLIED", "rule_id": "kb-fine", "device_id": "sn-c1", "_at": self.clock[0] - 7200}]):
            rec = self.train.rule_recurrence(["kb-fine"])["kb-fine"]
        self.assertEqual(rec["after"]["target_events"], 1, "only the matching fine-key event on sn-c1")

    def test_default_accepted_included_on_request(self) -> None:
        train = self.make_train(include_default_accepted=True)
        for d in ["sn-c1", "sn-r1", "sn-r2"]:
            self.ev(d, "E01", "S7_FINAL_GATE:FINAL-STATIC-HOLD", {"default_accepted": True})
        self.assertEqual([cl["failure_type"] for cl in train.clusters()], ["S7_FINAL_GATE:FINAL-STATIC-HOLD"])
        self.assertEqual(self.train.clusters(), [])


class PipelinePostgenRowsTest(unittest.TestCase):
    def test_rejected_unit_carries_its_qa_record_as_source(self) -> None:
        import importlib
        import os
        old = os.environ.get("NALU_RUNTIME_ROOT")
        os.environ["NALU_RUNTIME_ROOT"] = str(Path(tempfile.mkdtemp()) / "rt")
        try:
            sys.modules.pop("nalu_paths", None)
            sys.modules.pop("nalu_pipeline", None)
            mod = importlib.import_module("nalu_pipeline")
        finally:
            if old is None:
                os.environ.pop("NALU_RUNTIME_ROOT", None)
            else:
                os.environ["NALU_RUNTIME_ROOT"] = old
        record = _write(Path(tempfile.mkdtemp()) / "E01-VU-002_POST_GENERATION_QA.json",
                        {"dialogue_qa": {"transcript": "你好"}})
        rows = mod.kb_postgen_rows({"units": [
            {"unit_id": "E01-VU-001", "verdict": "ADMIT", "reasons": [], "record": record},
            {"unit_id": "E01-VU-002", "verdict": "REJECT", "reasons": ["dialogue:x"], "record": record}]})
        self.assertNotIn("source", rows[0])
        self.assertEqual(rows[1]["source"]["dialogue_qa"]["transcript"], "你好")
        self.assertEqual(rows[1]["codes"], ["dialogue:x"])


if __name__ == "__main__":
    unittest.main()
