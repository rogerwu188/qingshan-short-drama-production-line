"""MiniMax-H3 480p from each episode's NEXT start (line owner 2026-11-12).

The H3 resolution is fixed per episode like the model (nalu_video_model): a new episode records
``generation.h3_resolution`` (engine default 480p) at its first S2 build; an episode that was already started
-- a lock or editorial manifest without a recorded resolution, or a bound H3 transaction -- stays 768p,
whatever the config or engine version says later.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_nalu_h3_video_model import (  # noqa: E402
    H3_ID, NALU_TOOLS, SD2_ID, capture_request_payload, nalu_manifest, nalu_roots, run_submit_main,
    write_editorial, write_lock,
)


def h3_config(**generation):
    return {"generation": {"video_model": H3_ID, **generation}}


def write_editorial_resolution(work: Path, episode: str, resolution: str) -> Path:
    path = write_editorial(work, episode, H3_ID)
    doc = json.loads(path.read_text())
    doc["model_contract"]["resolution"] = resolution
    doc["shots"] = [{"shot_id": "S01", "model": H3_ID, "resolution": resolution}]
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def write_transaction(tx_root: Path, episode: str, name: str, **row) -> Path:
    path = tx_root / episode / f"{episode}-VU-001__{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"task_key": f"{episode}-VU-001", "model": H3_ID, **row}), encoding="utf-8")
    return path


class EpisodeResolutionLockTests(unittest.TestCase):
    def test_new_episode_records_480p_and_sends_it(self):
        with nalu_roots(qingshan=h3_config()) as (tmp, runtime, work, vm, bnp):
            self.assertEqual(vm.configured_h3_resolution(), "480p")  # key absent -> engine default
            contract = bnp.select_video_model("E80")
            self.assertEqual(contract["resolution"], "480p")
            self.assertIsNone(contract["native_raster"])
            self.assertEqual(contract["native_short_edge"], 480)
            lock = json.loads(vm.record_path("E80").read_text())
            self.assertEqual((lock["video_model"], lock["resolution"]), (H3_ID, "480p"))
            self.assertEqual(vm.episode_video_resolution("E80"), "480p")
            prompt = tmp / "E80-VU-001.txt"
            prompt.write_text("subject_definitions:\n@Image1: h3\n", encoding="utf-8")
            manifest = nalu_manifest("E80", H3_ID, prompt=prompt, h3_resolution=contract["resolution"])
            from tools import submit_giggle_video_manifest_v2 as video
            video.require_episode_video_model(manifest, tmp / "m.json")
            self.assertEqual(capture_request_payload(video, manifest["tasks"][0], tmp)["resolution"], "480p")
            from tools import hopsapi_video_client as hops
            body = hops.build_omni_request(prompt="p", image_urls=["https://x/i.png"], audio_urls=[], duration=4,
                                           resolution=manifest["tasks"][0]["resolution"])
            self.assertEqual(body["input"]["resolution"], "480p")

    def test_legacy_lock_without_resolution_stays_768p(self):
        with nalu_roots(qingshan=h3_config(h3_resolution="480p")) as (tmp, runtime, work, vm, bnp):
            lock = write_lock(runtime, "E81", H3_ID)  # written by an engine before 2026-11-12
            before = lock.read_bytes()
            self.assertEqual(vm.episode_video_resolution("E81"), "768p")
            contract = bnp.select_video_model("E81")  # a mid-episode S2/S6 recompile on the new engine
            self.assertEqual((contract["resolution"], contract["native_raster"]), ("768p", "768x1344"))
            self.assertEqual(lock.read_bytes(), before, "the legacy lock is never rewritten")

    def test_existing_768p_editorial_manifest_stays_768p(self):
        with nalu_roots(qingshan=h3_config()) as (tmp, runtime, work, vm, bnp):
            write_editorial_resolution(work, "E82", "768p")
            self.assertEqual(vm.episode_video_resolution("E82"), "768p")
            self.assertEqual(bnp.select_video_model("E82")["resolution"], "768p")
            self.assertEqual(json.loads(vm.record_path("E82").read_text())["resolution"], "768p")
            # a pre-resolution editorial manifest (model only) is a started episode too
            write_editorial(work, "E83", H3_ID)
            self.assertEqual(vm.episode_video_resolution("E83"), "768p")

    def test_recorded_resolution_never_changes_after_config_change(self):
        with nalu_roots(qingshan=h3_config()) as (tmp, runtime, work, vm, bnp):
            bnp.select_video_model("E84")
            (runtime / "qingshan.json").write_text(json.dumps(h3_config(h3_resolution="768p")))
            self.assertEqual(vm.episode_video_resolution("E84"), "480p")
            self.assertEqual(bnp.select_video_model("E84")["resolution"], "480p")
            self.assertEqual(bnp.select_video_model("E85")["resolution"], "768p")  # the next new one follows
            (runtime / "qingshan.json").write_text(json.dumps(h3_config(h3_resolution="480p")))
            self.assertEqual(vm.episode_video_resolution("E85"), "768p")

    def test_config_768p_applies_to_new_episodes(self):
        with nalu_roots(qingshan=h3_config(h3_resolution="768p")) as (tmp, runtime, work, vm, bnp):
            contract = bnp.select_video_model("E86")
            self.assertEqual((contract["resolution"], contract["native_raster"]), ("768p", "768x1344"))
            self.assertEqual(json.loads(vm.record_path("E86").read_text())["resolution"], "768p")

    def test_invalid_config_fails_closed_without_lock(self):
        for value in ("", "720p", "1080p", 480, None, ["480p"]):
            with self.subTest(value=value), nalu_roots(qingshan=h3_config(h3_resolution=value)) as (
                    tmp, runtime, work, vm, bnp):
                with self.assertRaises(vm.VideoModelSelectionError) as caught:
                    vm.episode_video_resolution("E87")
                self.assertEqual(caught.exception.code, "VIDEO_RESOLUTION_CONFIG_INVALID")
                with self.assertRaises(SystemExit) as stopped:
                    bnp.select_video_model("E87")
                self.assertIn("VIDEO_RESOLUTION_CONFIG_INVALID", str(stopped.exception))
                self.assertFalse(vm.record_path("E87").exists(), "no lock may be written")
        with nalu_roots(qingshan={"generation": {"video_model": SD2_ID, "h3_resolution": "bogus"}}) as (
                tmp, runtime, work, vm, bnp):
            self.assertEqual(vm.episode_video_resolution("E87"), "720p")  # SD2 never reads the H3 key

    def test_invalid_or_conflicting_records_fail_closed(self):
        with nalu_roots(qingshan=h3_config()) as (tmp, runtime, work, vm, bnp):
            lock = vm.record_path("E88")
            lock.parent.mkdir(parents=True)
            lock.write_text(json.dumps({"episode": "E88", "video_model": H3_ID, "resolution": "720p"}))
            with self.assertRaises(vm.VideoModelSelectionError) as caught:
                vm.episode_video_resolution("E88")
            self.assertEqual(caught.exception.code, "VIDEO_RESOLUTION_LOCK_INVALID")
            lock.write_text(json.dumps({"episode": "E88", "video_model": H3_ID, "resolution": "480p"}))
            write_editorial_resolution(work, "E88", "768p")
            with self.assertRaises(vm.VideoModelSelectionError) as caught:
                vm.episode_video_resolution("E88")
            self.assertEqual(caught.exception.code, "VIDEO_RESOLUTION_RECORDS_CONFLICT")
            with self.assertRaises(SystemExit):
                bnp.select_video_model("E88")

    def test_bound_h3_transaction_keeps_episode_at_its_resolution(self):
        with nalu_roots(qingshan=h3_config()) as (tmp, runtime, work, vm, bnp):
            tx_root = tmp / "tx"
            with mock.patch.object(vm, "transactions_dir", lambda episode: tx_root / episode):
                # a bound Giggle-era H3 task (no resolution recorded): 768p, even without lock or manifest
                write_transaction(tx_root, "E89", "a", state="SUBMITTED_TASK_ID_BOUND", task_id="t-1")
                self.assertEqual(vm.episode_video_resolution("E89"), "768p")
                self.assertEqual(bnp.select_video_model("E89")["resolution"], "768p")
                # an intent that never bound and records nothing does not start an episode
                write_transaction(tx_root, "E90", "a", state="VERIFIED_ZERO_RETRYABLE")
                self.assertEqual(vm.episode_video_resolution("E90"), "480p")
                # a HopsAPI transaction carries the request it sent
                write_transaction(tx_root, "E91", "a", state="SUBMITTED_TASK_ID_BOUND", task_id="tsk_1",
                                  provider_request_input={"resolution": "768p"})
                self.assertEqual(vm.episode_video_resolution("E91"), "768p")
                # a 480p lock next to a 768p bound task is a mixed episode: refused
                vm.record_path("E92").parent.mkdir(parents=True)
                vm.record_path("E92").write_text(json.dumps({"episode": "E92", "video_model": H3_ID,
                                                             "resolution": "480p"}))
                write_transaction(tx_root, "E92", "a", state="SUBMITTED_TASK_ID_BOUND", task_id="t-2")
                with self.assertRaises(vm.VideoModelSelectionError) as caught:
                    vm.episode_video_resolution("E92")
                self.assertEqual(caught.exception.code, "VIDEO_RESOLUTION_RECORDS_CONFLICT")

    def test_submitter_refuses_a_task_at_another_resolution_before_post(self):
        with nalu_roots(qingshan=h3_config()) as (tmp, runtime, work, vm, bnp):
            write_lock(runtime, "E93", H3_ID)  # legacy episode -> 768p
            write_editorial(work, "E93", H3_ID)
            error, post = run_submit_main(nalu_manifest("E93", H3_ID, h3_resolution="480p"), tmp)
            self.assertIsInstance(error, vm.VideoModelSelectionError)
            self.assertEqual(error.code, "VIDEO_RESOLUTION_MISMATCH")
            self.assertEqual(error.details["expected"], "768p")
            self.assertEqual(post.call_count, 0)


class H3PriceTests(unittest.TestCase):
    def test_480p_planning_price_is_lower_and_overrides_scale(self):
        from tools import hopsapi_video_client as hops
        env: dict[str, str] = {}
        missing = Path(tempfile.gettempdir()) / "no-such-qingshan.json"
        self.assertEqual(hops.estimated_task_credits(4, config_path=missing, environ=env), 7)          # 4 x 1.56
        self.assertEqual(hops.estimated_task_credits(4, config_path=missing, environ=env, resolution="480p"), 5)
        self.assertEqual(hops.estimated_task_credits(10, 6, config_path=missing, environ=env, resolution="480p"),
                         13)  # 10 x 1.09 + 1 x 10 x 0.16
        self.assertEqual(hops.estimated_batch_credits(8, 2, config_path=missing, environ=env, resolution="480p"),
                         9 + 2)
        # a device that overrides the 768p rate gets a proportionally scaled (rounded-up) 480p rate
        scaled = hops.h3_credits_per_second(missing, {"HOPSAPI_H3_CREDITS_PER_SECOND": "2.0"}, "480p")
        self.assertEqual(str(scaled), "1.40")
        own = hops.h3_credits_per_second(missing, {"HOPSAPI_H3_480P_CREDITS_PER_SECOND": "1.2"}, "480p")
        self.assertEqual(str(own), "1.2")

    def test_grouped_compiler_accepts_both_native_h3_resolutions(self):
        from tools.compile_grouped_seedance_manifest import NATIVE_VIDEO_MODEL_RESOLUTIONS
        self.assertEqual(NATIVE_VIDEO_MODEL_RESOLUTIONS[H3_ID], {"480p", "768p"})


class H3NativeRasterQaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if str(NALU_TOOLS) not in sys.path:
            sys.path.insert(0, str(NALU_TOOLS))
        import post_generation_qa_runner as qa
        cls.qa = qa

    def test_raster_rule_per_resolution(self):
        ok = self.qa.h3_native_raster
        for size in ((480, 854), (480, 848), (480, 864), (480, 840)):
            self.assertTrue(ok(*size, "480p"), size)
            self.assertTrue(ok(*size, None), size)
            self.assertFalse(ok(*size, "768p"), size)
        for size in ((480, 480), (480, 640), (854, 480), (480, 960), (360, 640)):
            self.assertFalse(ok(*size, "480p"), size)
        self.assertTrue(ok(768, 1344, "768p"))
        self.assertTrue(ok(768, 1366, None))
        self.assertFalse(ok(768, 1344, "480p"))

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg not installed")
    def test_technical_checks_accept_480p_clip_and_reject_wrong_aspect(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)

            def clip(name, size):
                path = out / f"{name}.mp4"
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=24",
                                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "2",
                                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
                               check=True)
                return path

            good = self.qa.technical_checks("U1", clip("good", "480x854"), 2.0, out / "U1", h3_resolution="480p")
            self.assertEqual(good["checks"]["resolution"]["status"], "PASS", good["checks"]["resolution"])
            self.assertEqual(good["checks"]["resolution"]["observed_native_raster"], "480x854")
            self.assertEqual(good["checks"]["aspect_ratio"]["status"], "PASS")
            square = self.qa.technical_checks("U2", clip("square", "480x640"), 2.0, out / "U2",
                                              h3_resolution="480p")
            self.assertEqual(square["checks"]["resolution"]["status"], "FAIL")
            self.assertEqual(square["checks"]["aspect_ratio"]["status"], "FAIL")
            legacy = self.qa.technical_checks("U3", clip("legacy", "480x854"), 2.0, out / "U3",
                                              h3_resolution="768p")
            self.assertEqual(legacy["checks"]["resolution"]["status"], "FAIL")  # a 768p episode never takes 480p


if __name__ == "__main__":
    unittest.main()
