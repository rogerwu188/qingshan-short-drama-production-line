import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/storyclaw_s3_autosync.py"
SPEC = importlib.util.spec_from_file_location("storyclaw_s3_autosync", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StoryClawS3AutosyncTests(unittest.TestCase):
    def test_writer_agent_production_prompts_and_configs_are_sync_roots(self):
        production = (ROOT / "workflow/claude_writer_agent/production").resolve()
        self.assertIn(production, {path.resolve() for path in MODULE.DEFAULT_ROOTS})

    def test_local_claude_audit_index_is_not_a_sync_root(self):
        audit_index = (ROOT / "codex_docs/CLAUDE_TO_CODEX.md").resolve()
        self.assertNotIn(audit_index, {path.resolve() for path in MODULE.DEFAULT_ROOTS})

    def test_final_package_video_is_final(self):
        path = ROOT / "exports/e21/final_package_v8/qingshan_E21_final.mp4"
        self.assertTrue(MODULE.is_final_video(path))

    def test_not_final_video_is_rejected(self):
        path = ROOT / "exports/e21/final_package_v8/qingshan_E21_NOT_FINAL.mp4"
        self.assertFalse(MODULE.is_final_video(path))

    def test_rough_video_is_rejected(self):
        path = ROOT / "exports/e21/rough_cut/qingshan_E21_final.mp4"
        self.assertFalse(MODULE.is_final_video(path))

    def test_delivery_slug_is_flat_and_stable(self):
        path = ROOT / "exports/e21/final_package_v8/qingshan_E21_final.mp4"
        slug = MODULE.safe_delivery_slug(path, True)
        self.assertTrue(slug.startswith("final__exports__e21__final_package_v8__"))
        self.assertNotIn("/", slug)

    def test_explicit_external_path_uses_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "final.mp4"
            self.assertEqual(MODULE.safe_delivery_slug(path, True), "final__final.mp4")

    def test_explicit_final_has_highest_upload_priority(self):
        final = ROOT / "exports/e21/final_package_v8/qingshan_E21_final.mp4"
        record = ROOT / "workflow/tasks/E21_TASK.md"
        explicit = {final.resolve()}
        self.assertLess(
            MODULE.upload_priority(final.resolve(), explicit)[0],
            MODULE.upload_priority(record.resolve(), explicit)[0],
        )

    def test_final_notification_deduplicates_by_sha_across_paths(self):
        digest = "a" * 64
        state = {
            "files": {
                "/old/path/final.mp4": {
                    "sha256": digest,
                    "c2sc_seq": 22,
                    "notification": "/outbox/C2SC-AUTO-FINAL-E20-aaaaaaaaaaaa.md",
                    "uploaded_at": "2026-07-19T00:00:00-0700",
                }
            }
        }
        first = MODULE.existing_final_notification(state, digest)
        second = MODULE.existing_final_notification(state, digest)
        self.assertEqual(first["c2sc_seq"], 22)
        self.assertEqual(second["c2sc_seq"], 22)
        self.assertEqual(len(state["final_notifications"]), 1)

    def test_failed_notification_reservation_can_retry(self):
        digest = "b" * 64
        state = {
            "files": {},
            "final_notifications": {digest: {"status": "failed", "error": "network"}},
        }
        self.assertIsNone(MODULE.existing_final_notification(state, digest))


if __name__ == "__main__":
    unittest.main()
