"""Offline regressions for the end-to-end reliability audit; never calls providers."""
import argparse
import hashlib
import json
import tempfile
import shutil
import subprocess
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from qingshan_engine import cli
from tools import giggle_api_client as client
from tools import submit_giggle_video_manifest_v2 as submit
from tools import render_portable_timeline as renderer
from tools.release_order_watch import completed_platforms
from tools.tests import test_render_portable_timeline as timeline_fixtures
from tools.tests.test_h3_crossmodal_speaker_gate import _unit
from tools.h3_crossmodal_speaker_gate import evaluate
from tools.platform_release_preflight import evaluate_release_preflight, validate_media_boundary_acceptance, validate_speaker_identity_voice_release
from tools import submit_giggle_image_manifest as image_submit
from tools import episode_stage_gate_runner as stages


class SubmissionAuditTests(unittest.TestCase):
    def fixture(self, root):
        prompt = root / "prompt.txt"
        prompt.write_text("offline fixture", encoding="utf-8")
        return {"task_key": "AUDIT-U01", "prompt_file": str(prompt),
                "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
                "reference_images": [], "reference_sha256": [], "model": "MiniMax-H3",
                "resolution": "768p", "duration_seconds": 4}

    def test_concurrent_identical_tasks_post_once(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task = self.fixture(root)
            def response(*_):
                time.sleep(0.03)
                return {"data": {"task_id": "remote-1"}}
            with patch.object(submit, "_image_list", return_value=[]), patch.object(submit, "_request", side_effect=response) as post:
                with ThreadPoolExecutor(max_workers=4) as pool:
                    results = list(pool.map(lambda _: submit.submit_one(task, root / "receipts", root / "tx"), range(4)))
            self.assertEqual(post.call_count, 1)
            self.assertEqual({r["task_id"] for r in results}, {"remote-1"})

    def test_receipt_failure_keeps_bound_task_and_recovers_without_post(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task = self.fixture(root)
            write = submit.atomic_json
            def fail_receipt(path, payload):
                if path.parent.name == "receipts":
                    raise OSError("simulated receipt disk error")
                write(path, payload)
            with patch.object(submit, "_image_list", return_value=[]), patch.object(submit, "_request", return_value={"task_id": "bound-1"}) as post:
                with patch.object(submit, "atomic_json", side_effect=fail_receipt):
                    with self.assertRaises(OSError):
                        submit.submit_one(task, root / "receipts", root / "tx")
                result = submit.submit_one(task, root / "receipts", root / "tx")
                self.assertEqual(post.call_count, 1)
            self.assertEqual(result["task_id"], "bound-1")
            self.assertTrue(Path(result["receipt"]).is_file())

    def test_aggregate_ledger_absence_cannot_authorize_retry(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "tx.json"
            path.write_text(json.dumps({"state": "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION"}))
            submit.classify_failures([{"transaction": str(path)}], 2, 2, Path(td))
            self.assertNotEqual(json.loads(path.read_text())["state"], "VERIFIED_ZERO_RETRYABLE")

    def test_thread_local_paid_context_does_not_authorize_another_thread(self):
        with client.paid_video_submission_context():
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaisesRegex(SystemExit, "durable video submitter"):
                    pool.submit(client._request, "/api/v1/generation/omni-video", {"model": "MiniMax-H3"}).result()

    def test_transaction_key_cannot_escape_directory(self):
        with self.assertRaises(ValueError):
            submit.transaction_path(Path("tx"), {"task_key": "../../escaped"})

    def test_image_concurrency_uses_one_post_and_external_receipts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task = self.fixture(root)
            task["model"] = "gpt-image-2-pro"
            with patch.object(image_submit, "precheck_submission_inputs", return_value={"status": "PASS"}), patch.object(image_submit, "_image_list", return_value=[]), patch.object(image_submit, "_request", return_value={"data": {"task_id": "image-1"}}) as post:
                with ThreadPoolExecutor(max_workers=3) as pool:
                    results = list(pool.map(lambda _: image_submit.submit_one(task, root / "receipts", root / "tx"), range(3)))
            self.assertEqual(post.call_count, 1)
            self.assertTrue(all(r["task_id"] == "image-1" for r in results))

    def test_unknown_image_transaction_state_is_not_retryable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            task = self.fixture(root)
            path = image_submit.transaction_path(root, task)
            image_submit.atomic_json(path, {"submission_fingerprint": image_submit.submission_fingerprint(task), "state": "NEW_UNKNOWN_FAILURE"})
            with self.assertRaises(image_submit.DuplicateSubmissionBlocked):
                image_submit.prior_submission_result(task, root)


class CompilerAndReleaseAuditTests(unittest.TestCase):
    def test_source_stage_does_not_require_not_yet_written_script_and_rejects_stale_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "AUDIT-SOURCE.json"
            report.write_text(json.dumps({"status": "PASS"}))
            spec = {"tool": "tools/source_canon_binding_gate.py", "skip_canonical_script_binding": True}
            with patch.dict(stages.EXECUTORS, {"AUDIT-SOURCE": spec}), patch.object(stages.subprocess, "run", return_value=argparse.Namespace(returncode=0, stdout="", stderr="")):
                result = stages.execute_gate("AUDIT-SOURCE", "E99", {}, root)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["implementation_status"], "MISSING")
            self.assertEqual(len(list(root.glob("*.previous-*.json"))), 1)

    def test_no_episode_line_cannot_pass_release_preflight(self):
        self.assertFalse(evaluate_release_preflight("E1", {"lines": {}})["release_allowed"])

    def test_zero_boundary_is_valid_but_boolean_or_string_count_is_not(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "boundary.json"
            for count, valid in ((0, True), (False, False), ("0", False)):
                path.write_text(json.dumps({"schema": "qingshan.media_boundary_acceptance.v1_safe_cut_and_real_transition", "status": "PASS", "rows": [], "boundary_count": count}))
                self.assertEqual(validate_media_boundary_acceptance({"media_boundary_acceptance": str(path)}, root)["valid"], valid)

    def test_speaker_evidence_cannot_be_reused_after_final_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            final = root / "final.mp4"
            final.write_bytes(b"old")
            report = root / "speaker.json"
            report.write_text(json.dumps({"schema": "qingshan.speaker_identity_voice_release_gate.v2_diarization_lip_owner_voice_similarity", "episode": "E56", "status": "PASS", "failures": [], "required_dialogue_count": 1, "evidence_count": 1, "final_sha256": hashlib.sha256(b"old").hexdigest()}))
            line = {"episode": "E56", "final": str(final), "speaker_identity_voice_release_gate": str(report)}
            self.assertTrue(validate_speaker_identity_voice_release(line, root)["valid"])
            final.write_bytes(b"new")
            self.assertFalse(validate_speaker_identity_voice_release(line, root)["valid"])
    def test_h3_rejects_zero_fractional_boolean_and_out_of_range_images(self):
        for index in (0, -1, True, 1.5, 10):
            with self.subTest(index=index):
                unit = _unit()
                unit["reference_images"] = ["one", "two", "three"]
                unit["provider_scope_projection"]["reference_identity_bindings"][0]["reference_index"] = index
                self.assertEqual(evaluate(unit)["status"], "FAIL")

    def test_h3_rejects_duplicate_voice_binding(self):
        unit = _unit()
        unit["speaker_voice_contract"]["bindings"] *= 2
        self.assertEqual(evaluate(unit)["status"], "FAIL")

    def test_douyin_mentioned_in_youtube_receipt_is_not_published(self):
        receipt = {"platform": "YouTube", "status": "PUBLISHED", "video_id": "real-id", "next": "DOUYIN PENDING"}
        self.assertEqual(completed_platforms(receipt), {"YOUTUBE"})
        self.assertEqual(completed_platforms({"release_complete": True}), set())
        self.assertEqual(completed_platforms({"douyin": {"status": "PUBLISHED", "aweme_id": "123"}, "youtube": receipt}), {"YOUTUBE", "DOUYIN"})

    def test_documented_cli_separator_and_relative_paths(self):
        args = argparse.Namespace(arguments=["--", "--episode", "E56", "--work-queue", "runtime/queue.json", "--project-root=runtime"])
        with patch.object(cli, "_run", return_value=0) as run:
            cli.command_release_preflight(args)
        command = run.call_args.args[0]
        self.assertNotIn("--", command)
        self.assertIn(str(Path("runtime/queue.json").resolve()), command)
        self.assertIn("--project-root=" + str(Path("runtime").resolve()), command)


class RendererAuditTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required for synthetic-media integration")
    def test_native_av_real_render(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            media = root / "native.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x96:r=24:d=1", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(media)], check=True)
            clip = {"source": "native.mp4", "start": 0, "in": 0, "duration": 1}
            project = root / "project.json"
            project.write_text(json.dumps({"output": {"path": "final.mp4", "width": 64, "height": 96}, "timeline": {"videoTracks": [{"clips": [clip]}], "audioTracks": [{"clips": [clip]}]}}))
            self.assertEqual(renderer.execute_render(renderer.build_ffmpeg_command(project)), 0)
            info = json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(root / "final.mp4")]))
            self.assertEqual({s["codec_type"] for s in info["streams"]}, {"video", "audio"})
            self.assertAlmostEqual(float(info["format"]["duration"]), 1, places=1)
    def test_non_finite_parameters_fail(self):
        for value in (float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                renderer._number(value, "duration")

    def test_reuses_native_input_and_preserves_encoding_quality(self):
        with tempfile.TemporaryDirectory() as td:
            project = timeline_fixtures.PortableTimelineRendererTests()._project(Path(td))
            data = json.loads(project.read_text())
            for video, audio in zip(data["timeline"]["videoTracks"][0]["clips"], data["timeline"]["audioTracks"][0]["clips"]):
                audio["source"] = video["source"]
            project.write_text(json.dumps(data))
            command = renderer.build_ffmpeg_command(project)
            self.assertEqual(command.count("-i"), 2)
            self.assertEqual(command[command.index("-crf") + 1], "18")
            self.assertFalse((Path(td) / "out").exists())
            with self.assertRaisesRegex(ValueError, "source media"):
                renderer.build_ffmpeg_command(project, Path(td) / "v1.mp4")

    def test_unsupported_editing_features_are_not_silently_discarded(self):
        for payload in ({"speed": 2}, {"effects": ["fade"]}, {"subtitleTracks": [{}]}):
            with self.assertRaises(ValueError):
                renderer._reject_unsupported(payload)

    def test_failed_render_preserves_existing_final(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "final.mp4"
            output.write_bytes(b"approved")
            with patch.object(renderer.subprocess, "run", return_value=argparse.Namespace(returncode=1)):
                self.assertEqual(renderer.execute_render(["ffmpeg", str(output)]), 1)
            self.assertEqual(output.read_bytes(), b"approved")
            self.assertEqual(list(Path(td).iterdir()), [output])


if __name__ == "__main__":
    unittest.main()
