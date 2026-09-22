import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lines.nalu.runtime.tools import final_audience_review as review


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    else:
        path.write_bytes(payload)
    return path


def _metrics() -> dict:
    return {
        "schema": "qingshan.final_cut_objective_metrics.v1",
        "measured_from": "DECODED_FINAL_MP4",
        "duration_seconds": 12.0,
        "shot_count": 2,
        "sampled_shot_count": 2,
        "sampling_basis": "per_shot_midpoint",
        "picture_repetition": {
            "near_duplicate_shot_pct": 0.0,
            "near_duplicate_shot_pct_non_adjacent": 0.0,
            "clusters": [],
            "non_adjacent_clusters": [],
        },
        "palette_uniformity_ADVISORY": {"dominant_cluster_pct": 20.0},
        "audio": {
            "shot_levels": [
                {"shot": 0, "start": 0.0, "mean_dbfs": -18.0},
                {"shot": 1, "start": 6.0, "mean_dbfs": -17.0},
            ],
            "digital_zero_shots": [],
            "level_jump_over_12db_count": 0,
        },
    }


class FinalAudienceReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.video = _write(self.root / "E01_final_9x16.mp4", b"real-final-video-bytes")
        self.asr = _write(self.root / "asr.json", {"segments": [{"start": 0, "end": 2}]})
        self.detector = _write(
            self.root / "detector.json",
            {
                "schema": "qingshan.final_cut_audience_detectors.v1",
                "media_sha256": _sha(self.video),
                "status": "PASS",
                "detectors": {},
            },
        )
        self.technical = _write(
            self.root / "technical.json",
            {"gate_id": "FINAL-CUT-AUDIENCE-DETECTORS", "status": "PASS"},
        )
        self.subtitle = _write(
            self.root / "subtitles.json",
            {"schema": "nalu.burnin_subtitles.v1", "captions": 2, "ffmpeg_exit": 0},
        )
        self.metrics = self.root / "metrics.json"
        self.contact = self.root / "contact.jpg"
        self.request = self.root / "request.json"
        self.report = self.root / "E01_AUDIENCE_SCORE_REPORT.json"
        self.ledger = self.root / "E01_FINAL_CUT_EVENT_LEDGER.json"
        self.audience_gate = self.root / "audience_gate.json"
        self.quality_gate = self.root / "quality_gate.json"

    def tearDown(self):
        self.temp.cleanup()

    def _prepare(self):
        def fake_metrics(_video, out, _workdir):
            _write(out, _metrics())
            return _metrics()

        def fake_sheet(_video, shots, out, _frames):
            self.assertEqual([row["shot_index"] for row in shots], [0, 1])
            _write(out, b"contact-sheet-pixels")

        with mock.patch.object(review, "run_objective_metrics", side_effect=fake_metrics), \
             mock.patch.object(review, "build_contact_sheet", side_effect=fake_sheet):
            return review.prepare(
                episode="E01",
                video=self.video,
                metrics_path=self.metrics,
                contact_sheet=self.contact,
                request_path=self.request,
                asr_path=self.asr,
                detector_path=self.detector,
                technical_path=self.technical,
                subtitle_report_path=self.subtitle,
                producer_process_id="production-process-7",
            )

    def _answers(self) -> dict:
        return {
            "schema": review.ANSWERS_SCHEMA,
            "request_sha256": _sha(self.request),
            "final_video_sha256": _sha(self.video),
            "reviewer": {
                "agent_id": review.REVIEWER_AGENT_ID,
                "role": review.REVIEWER_ROLE,
                "model": "storyclaw/gpt-6-astra",
                "process_id": "independent-review-process-3",
                "reviewed_at": "2026-09-20T12:00:00Z",
            },
            "viewing_passes": {
                "full_1x": {"completed": True, "observation": "完整观看时人物行动、台词和剪辑节奏都能前后连贯对应。"},
                "muted": {"completed": True, "observation": "静音观看仍能从动作变化和镜头衔接理解事件因果与角色目标。"},
                "sound": {"completed": True, "observation": "只听声音时对白归属清楚，环境声和音乐没有遮挡关键语句。"},
            },
            "shots": [
                {"shot_index": 0, "note": "第一镜角色从门外进入室内，把信件放到桌面并看向对方。"},
                {"shot_index": 1, "note": "第二镜对方拿起信件读完，神情变化后转身走向窗边。"},
            ],
            "dimensions": {
                key: {"score": 4.0, "reason": f"{key}维度在完整三遍观看中有明确的画面和声音证据支持。"}
                for key in review.DIMENSIONS
            },
            "overall": {
                "score": 4.1,
                "reason": "综合三种观看方式，这一成片的故事可读性、节奏和完成度已经达到发布标准。",
            },
            "checks": {
                "identity_color_consistent": {"value": True, "observation": "两镜人物脸部、服装颜色和光线方向保持一致。"},
                "opening_10s_hook": {"value": True, "observation": "前十秒内信件被交付并立刻引出明确悬念。"},
                "opening_3s_hook": {"value": True, "observation": "前三秒角色急促进入并亮出信件，动作目标清楚。"},
                "tail_5s_hook_intact": {"value": True, "observation": "结尾五秒停在角色看向窗外的未决反应上。"},
                "narrative_stagnation": {"value": False, "observation": "每六秒都发生新的外部动作或信息变化，没有停滞。"},
            },
            "events": [
                {"shot_index": 0, "t": 2.0, "what": "角色进入房间并把信件放到桌面"},
                {"shot_index": 1, "t": 8.0, "what": "对方读完信件后转身走向窗边"},
            ],
            "problems": [],
        }

    def _submit(self, answers: dict):
        answer_path = _write(self.root / "answers.json", answers)
        return review.submit(
            request_path=self.request,
            answers_path=answer_path,
            report_path=self.report,
            ledger_path=self.ledger,
            audience_gate_path=self.audience_gate,
            quality_gate_path=self.quality_gate,
        )

    def test_prepare_binds_real_media_and_never_writes_reviewer_outputs(self):
        result = self._prepare()
        request = json.loads(self.request.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertEqual(request["media"]["sha256"], _sha(self.video))
        self.assertEqual(request["objective_summary"]["shot_count"], 2)
        self.assertEqual(len(request["shots"]), 2)
        self.assertTrue(self.metrics.is_file())
        self.assertTrue(self.contact.is_file())
        self.assertFalse(self.report.exists())
        self.assertFalse(self.ledger.exists())
        self.assertFalse(request["producer_may_submit_answers"])

    def test_prepare_reentry_reuses_request_without_changing_its_sha(self):
        self._prepare()
        first_sha = _sha(self.request)

        with mock.patch.object(review, "run_objective_metrics") as rerun, \
             mock.patch.object(review, "build_contact_sheet") as resheet:
            result = review.prepare(
                episode="E01",
                video=self.video,
                metrics_path=self.metrics,
                contact_sheet=self.contact,
                request_path=self.request,
                asr_path=self.asr,
                detector_path=self.detector,
                technical_path=self.technical,
                subtitle_report_path=self.subtitle,
                producer_process_id="production-process-7",
            )

        self.assertTrue(result["reused_existing_request"])
        self.assertEqual(_sha(self.request), first_sha)
        rerun.assert_not_called()
        resheet.assert_not_called()

    def test_valid_independent_review_materialises_reports_and_passes_both_gates(self):
        self._prepare()
        code, result = self._submit(self._answers())

        self.assertEqual(code, 0, result)
        self.assertEqual(result["status"], "PASS")
        report = json.loads(self.report.read_text(encoding="utf-8"))
        ledger = json.loads(self.ledger.read_text(encoding="utf-8"))
        self.assertEqual(report["media_sha256"], _sha(self.video))
        self.assertEqual(report["request_sha256"], _sha(self.request))
        self.assertEqual(len(report["evidence"]["shot_notes"]), 2)
        self.assertEqual(len(ledger["events"]), 2)
        self.assertEqual(result["audience_gate_status"], "PASS")
        self.assertEqual(result["quality_gate_status"], "PASS")

        status_code, status_result = review.status(
            episode="E01",
            video=self.video,
            request_path=self.request,
            report_path=self.report,
            ledger_path=self.ledger,
            audience_gate_path=self.audience_gate,
            quality_gate_path=self.quality_gate,
        )
        self.assertEqual(status_code, 0)
        self.assertEqual(status_result["status"], "PASS")

    def test_producer_process_cannot_submit_as_reviewer(self):
        self._prepare()
        answers = self._answers()
        answers["reviewer"]["process_id"] = "production-process-7"

        code, result = self._submit(answers)

        self.assertEqual(code, 2)
        self.assertEqual(result["status"], "INVALID_SUBMISSION")
        self.assertIn("reviewer_process_must_differ_from_producer", result["failures"])
        self.assertFalse(self.report.exists())
        self.assertFalse(self.ledger.exists())

    def test_gpt_5_6_sol_is_accepted_only_as_explicit_high_capability_fallback(self):
        self._prepare()
        answers = self._answers()
        answers["reviewer"]["model"] = "storyclaw/gpt-5.6-sol"

        code, result = self._submit(answers)

        self.assertEqual(code, 0, result)
        self.assertEqual(result["status"], "PASS")

    def test_non_allowlisted_reviewer_model_is_rejected(self):
        self._prepare()
        answers = self._answers()
        answers["reviewer"]["model"] = "storyclaw/kimi-2.7"

        code, result = self._submit(answers)

        self.assertEqual(code, 2)
        self.assertIn("reviewer_model_not_allowed:storyclaw/kimi-2.7", result["failures"])
        self.assertFalse(self.report.exists())

    def test_prepare_recomputes_technical_verdict_and_rejects_fake_pass(self):
        _write(
            self.detector,
            {
                "schema": "qingshan.final_cut_audience_detectors.v1",
                "media_sha256": _sha(self.video),
                "status": "FAIL",
                "detectors": {
                    "hook_present": {"status": "FAIL", "failures": ["HOOK_MISSING"]},
                },
            },
        )
        with self.assertRaisesRegex(ValueError, "disagrees with canonical"):
            review.prepare(
                episode="E01",
                video=self.video,
                metrics_path=self.metrics,
                contact_sheet=self.contact,
                request_path=self.request,
                asr_path=self.asr,
                detector_path=self.detector,
                technical_path=self.technical,
                subtitle_report_path=self.subtitle,
                producer_process_id="production-process-7",
            )
        self.assertFalse(self.request.exists())

    def test_stale_final_media_sha_rejects_submission_without_reports(self):
        self._prepare()
        answers = self._answers()
        self.video.write_bytes(b"changed-after-request")

        code, result = self._submit(answers)

        self.assertEqual(code, 2)
        self.assertIn("final_video_missing_or_sha_changed", result["failures"])
        self.assertFalse(self.report.exists())

    def test_real_reject_is_written_then_blocks(self):
        self._prepare()
        answers = self._answers()
        answers["checks"]["opening_10s_hook"] = {
            "value": False,
            "observation": "前十秒只有角色静止等待，没有信息变化或可辨识的行动目标。",
        }
        answers["problems"] = [{
            "severity": "P1",
            "shot_index": 0,
            "at_seconds": 2.0,
            "issue": "开场十秒没有建立冲突、目标或悬念，观众缺少继续观看的理由。",
            "fix": "重剪开场并把信件交付与角色反应提前到前三秒内清楚呈现。",
        }]

        code, result = self._submit(answers)

        self.assertEqual(code, 3, result)
        self.assertEqual(result["status"], "BLOCKED_BY_FINAL_AUDIENCE_GATE")
        self.assertTrue(self.report.is_file())
        self.assertTrue(self.ledger.is_file())
        report = json.loads(self.report.read_text(encoding="utf-8"))
        self.assertEqual(report["verdict"], "REJECT_RECUT")
        self.assertIn("opening_10s_no_hook", report["hard_fail"])


class ShotWindowTests(unittest.TestCase):
    def test_requires_one_timestamped_row_per_measured_shot(self):
        broken = _metrics()
        broken["audio"]["shot_levels"] = broken["audio"]["shot_levels"][:1]
        with self.assertRaisesRegex(ValueError, "one timestamped row"):
            review.shot_windows(broken)


if __name__ == "__main__":
    unittest.main()
