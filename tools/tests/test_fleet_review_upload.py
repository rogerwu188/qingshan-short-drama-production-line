"""Fleet review_upload (owner 2026-11-23): system code -- not the StoryClaw agent -- uploads the fixed review files
of one episode (final cut, generation contract, release timeline, device Gemini review) and returns the URLs in
the command result.  Offline: the HopsAPI upload is mocked."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "nalu-claude-code" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import fleet_sync  # noqa: E402

KEY = "sk-review-upload-test-key-0123456789"


class ReviewUploadTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.engine, self.runtime = root / "engine", root / "runtime"
        (self.runtime / "credentials").mkdir(parents=True)
        (self.runtime / "credentials/llm_provider.json").write_text(
            json.dumps({"base_url": "https://hopsapi.com/v1", "api_key": KEY}))
        self.engine.mkdir()
        self.cp = SimpleNamespace(roots=lambda: (self.engine, self.runtime), current_episode=lambda: "E06")
        self.calls: list[dict] = []
        self.fail_kind: str | None = None

        def upload_bytes(data, *, file_name, upload_path, mime):
            self.calls.append({"file_name": file_name, "upload_path": upload_path, "mime": mime,
                               "key": os.environ.get("HOPSAPI_API_KEY"), "bytes": len(data)})
            if self.fail_kind and self.fail_kind in file_name:
                raise RuntimeError(f"UPLOAD_REJECTED: bad auth Bearer {KEY}")
            return {"url": f"https://cdn.test/maint-review/{file_name}", "mime_type": mime,
                    "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data),
                    "expires_at": "2026-11-30T00:00:00Z", "file_name": file_name, "upload_path": upload_path}
        fake = SimpleNamespace(API_KEY_ENV="HOPSAPI_API_KEY", upload_bytes=upload_bytes)
        self.patches = [mock.patch.dict(sys.modules, {"hopsapi_video_client": fake}),
                        mock.patch.dict(os.environ, {"NALU_WORK_ROOT": str(self.engine / "workflow" / "nalu")}),
                        mock.patch.object(fleet_sync, "_engine_sha", lambda e: "c" * 40)]
        for p in self.patches:
            p.start()
        os.environ.pop("HOPSAPI_API_KEY", None)

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self._tmp.cleanup()

    def write(self, path: Path, content) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(json.dumps(content))
        return path

    def episode(self, ep="E05"):
        self.write(self.runtime / "deliverables" / ep / f"{ep}_final_9x16.mp4", b"\x00mp4" * 100)
        # the writer slot holds another episode's contract under this name (a device once uploaded that one)
        self.write(self.engine / "workflow/claude_writer_agent/scripts" / f"{ep}_GENERATION_CONTRACT_v1.json",
                   {"episode": "E04"})
        self.write(self.engine / "workflow/nalu" / ep / f"{ep}_GENERATION_CONTRACT_v1.json", {"episode": ep, "x": 1})
        self.write(self.engine / "workflow/nalu" / ep / "assembly" / f"{ep}_release_timeline.json", {"episode": ep})
        self.write(self.runtime / "claude_code" / ep / "final_reviewer" / "gemini_review.json", {"status": "OK"})

    def test_uploads_the_fixed_files_with_explicit_mime_and_returns_urls(self):
        self.episode()
        ok, res, extra = fleet_sync.run_command(self.cp, {"type": "review_upload",
                                                          "payload": {"episode": "E05", "files": list(fleet_sync.REVIEW_FILES)}})
        self.assertTrue(ok, res)
        self.assertEqual(extra, {})
        self.assertEqual(sorted(res["files"]), sorted(fleet_sync.REVIEW_FILES))
        self.assertEqual(res["missing"], [])
        self.assertEqual([c["file_name"] for c in self.calls],
                         ["E05_final_9x16.mp4", "E05_GENERATION_CONTRACT_v1.json", "E05_release_timeline.json",
                          "E05_gemini_review.json"])
        self.assertEqual({c["upload_path"] for c in self.calls}, {"maint-review"})
        self.assertEqual([c["mime"] for c in self.calls], ["video/mp4"] + ["application/json"] * 3)
        self.assertEqual({c["key"] for c in self.calls}, {KEY})            # the line's key for the upload ...
        self.assertNotIn("HOPSAPI_API_KEY", os.environ)                    # ... and gone afterwards
        self.assertNotIn(KEY, json.dumps(res))
        cut = res["files"]["final_cut"]
        self.assertEqual(cut["sha256"], hashlib.sha256(b"\x00mp4" * 100).hexdigest())
        self.assertEqual((cut["bytes"], cut["expires_at"]), (400, "2026-11-30T00:00:00Z"))
        self.assertTrue(cut["url"].startswith("https://"))
        self.assertEqual(res["engine_sha"], "c" * 12)

    def test_subset_missing_and_wrong_episode_contract(self):
        self.write(self.runtime / "runtime/deliverables/E07/E07_final_9x16.mp4", b"v")
        self.write(self.engine / "workflow/claude_writer_agent/scripts/E07_GENERATION_CONTRACT_v1.json", {"episode": "E06"})
        ok, res, _ = fleet_sync.review_upload(self.cp, {"episode": "e07", "files": ["final_cut", "contract", "timeline"]})
        self.assertTrue(ok)  # missing files are reported, not a failure
        self.assertEqual(list(res["files"]), ["final_cut"])
        reasons = {m["file"]: m["reason"] for m in res["missing"]}
        self.assertTrue(reasons["contract"].startswith("EPISODE_MISMATCH:E07_GENERATION_CONTRACT_v1.json:episode=E06"))
        self.assertEqual(reasons["timeline"], "NOT_FOUND")
        self.assertNotIn("gemini_review", reasons)  # not asked for

    def test_recorded_pipeline_contract_wins(self):
        self.episode("E08")
        explicit = self.write(self.runtime / "writer_layers/s1/E08/E08_GENERATION_CONTRACT_v3.json", {"episode": "E08"})
        self.write(self.runtime / "runtime/pipeline_state/E08.json",
                   {"layers": {"paths": {"generation_contract": str(explicit)}}})
        ok, res, _ = fleet_sync.review_upload(self.cp, {"episode": "E08", "files": ["contract"]})
        self.assertEqual(res["files"]["contract"]["file_name"], "E08_GENERATION_CONTRACT_v3.json")
        # a recorded path not named for the episode is ignored
        self.write(self.runtime / "runtime/pipeline_state/E08.json",
                   {"layers": {"paths": {"generation_contract": "/etc/passwd"}}})
        ok, res, _ = fleet_sync.review_upload(self.cp, {"episode": "E08", "files": ["contract"]})
        self.assertEqual(res["files"]["contract"]["file_name"], "E08_GENERATION_CONTRACT_v1.json")

    def test_size_cap_symlink_outside_and_upload_failure(self):
        self.episode()
        outside = Path(self._tmp.name) / "elsewhere.json"
        outside.write_text(json.dumps({"episode": "E05"}))
        tl = self.engine / "workflow/nalu/E05/assembly/E05_release_timeline.json"
        tl.unlink()
        tl.symlink_to(outside)
        self.fail_kind = "gemini_review"
        with mock.patch.object(fleet_sync, "REVIEW_MAX_BYTES", 100):
            ok, res, _ = fleet_sync.review_upload(self.cp, {"episode": "E05"})
        self.assertFalse(ok)
        reasons = {m["file"]: m["reason"] for m in res["missing"]}
        self.assertEqual(reasons["final_cut"], "TOO_LARGE:400")
        self.assertEqual(reasons["timeline"], "OUTSIDE_ENGINE_OR_RUNTIME")
        self.assertTrue(reasons["gemini_review"].startswith("UPLOAD_FAILED:"))
        self.assertNotIn(KEY, json.dumps(res))
        self.assertEqual(list(res["files"]), ["contract"])

    def test_held_episode_uploads_the_newest_assembly_cut(self):
        # RELEASE_HELD (2026-11-27, 1101 E29): no deliverable -> the newest assembly cut as <EP>_held_cut.mp4
        asm = self.engine / "workflow/nalu/E29/assembly"
        bgm = self.write(asm / "E29_picture_native_subbed_endcard_bgm.mp4", b"\x00bgm" * 10)
        cand = self.write(asm / "E29_final_candidate_9x16.mp4", b"\x00cand" * 10)
        os.utime(bgm, (1_000_000, 1_000_000))
        ok, res, _ = fleet_sync.run_command(self.cp, {"type": "review_upload",
                                                      "payload": {"episode": "E29", "files": ["final_cut"]}})
        self.assertTrue(ok)
        self.assertTrue(res["held"])
        row = res["files"]["final_cut"]
        self.assertEqual((row["file_name"], row["held"], row["source"]),
                         ("E29_held_cut.mp4", True, "E29_final_candidate_9x16.mp4"))
        self.assertEqual(self.calls[-1]["bytes"], len(b"\x00cand" * 10))
        os.utime(cand, (900_000, 900_000))  # the end-card + BGM cut is newer now
        _, res, _ = fleet_sync.run_command(self.cp, {"type": "review_upload",
                                                     "payload": {"episode": "E29", "files": ["final_cut"]}})
        self.assertEqual(res["files"]["final_cut"]["source"], "E29_picture_native_subbed_endcard_bgm.mp4")
        # a released episode keeps its deliverable and no held flag
        self.episode()
        _, res, _ = fleet_sync.run_command(self.cp, {"type": "review_upload",
                                                     "payload": {"episode": "E05", "files": ["final_cut"]}})
        self.assertNotIn("held", res)
        self.assertEqual(res["files"]["final_cut"]["file_name"], "E05_final_9x16.mp4")
        _, res, _ = fleet_sync.run_command(self.cp, {"type": "review_upload",
                                                     "payload": {"episode": "E30", "files": ["final_cut"]}})
        self.assertEqual(res["missing"], [{"file": "final_cut", "reason": "NOT_FOUND"}])

    def test_rejects_bad_payloads_and_needs_a_key(self):
        for payload, err in (({"episode": "../E05"}, "REVIEW_UPLOAD_BAD_EPISODE"), ({}, "REVIEW_UPLOAD_BAD_EPISODE"),
                             ({"episode": "E05", "files": ["/etc/passwd"]}, "REVIEW_UPLOAD_BAD_FILES"),
                             ({"episode": "E05", "files": "final_cut"}, "REVIEW_UPLOAD_BAD_FILES")):
            ok, res, _ = fleet_sync.review_upload(self.cp, payload)
            self.assertEqual((ok, res["error"]), (False, err))
        (self.runtime / "credentials/llm_provider.json").unlink()
        self.episode()
        ok, res, _ = fleet_sync.review_upload(self.cp, {"episode": "E05"})
        self.assertEqual((ok, res["error"]), (False, "NO_HOPSAPI_KEY"))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
