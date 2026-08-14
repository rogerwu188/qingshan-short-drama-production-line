import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "storyclaw_realtime_sync.py"
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location("storyclaw_realtime_sync", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class StoryClawRealtimeSyncTests(unittest.TestCase):
    def test_detects_daily_kv_write_quota_error(self):
        self.assertTrue(
            MODULE.daily_write_quota_exhausted(
                {"ok": False, "error": "KV put() limit exceeded for the day."}
            )
        )

    def test_does_not_classify_other_bridge_errors_as_daily_quota(self):
        self.assertFalse(
            MODULE.daily_write_quota_exhausted(
                {"ok": False, "error": "temporary upstream timeout"}
            )
        )

    def test_next_daily_quota_retry_uses_next_utc_day(self):
        retry = MODULE.next_daily_quota_retry(
            datetime(2026, 7, 16, 12, 3, tzinfo=timezone.utc)
        )
        self.assertEqual(
            retry,
            datetime(2026, 7, 17, 0, 5, tzinfo=timezone.utc),
        )

    def test_retry_is_deferred_before_retry_window(self):
        state = {"write_retry_after_utc": "2026-07-17T00:05:00+00:00"}
        self.assertTrue(
            MODULE.retry_is_deferred(
                state,
                datetime(2026, 7, 16, 12, 3, tzinfo=timezone.utc),
            )
        )
        self.assertFalse(
            MODULE.retry_is_deferred(
                state,
                datetime(2026, 7, 17, 0, 5, tzinfo=timezone.utc),
            )
        )

    def test_local_mailbox_and_bridge_receipts_are_not_sync_roots(self):
        self.assertNotIn(
            "workflow/storyclaw_outbox",
            MODULE.DEFAULT_INCLUDE_ROOTS,
        )
        self.assertNotIn(
            "workflow/storyclaw_bridge_outgoing",
            MODULE.DEFAULT_INCLUDE_ROOTS,
        )
        self.assertNotIn(
            "codex_docs/CLAUDE_TO_CODEX.md",
            MODULE.DEFAULT_INCLUDE_ROOTS,
        )

    def test_dashboard_is_a_sync_root_with_web_asset_suffixes(self):
        self.assertIn("workflow/dashboard", MODULE.DEFAULT_INCLUDE_ROOTS)
        self.assertIn(".html", MODULE.DEFAULT_SUFFIXES)
        self.assertIn(".js", MODULE.DEFAULT_SUFFIXES)

    def test_dashboard_status_refresh_is_discovered(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            dashboard = base / "workflow" / "dashboard"
            dashboard.mkdir(parents=True)
            expected = {
                "README.md",
                "build_status.py",
                "index.html",
                "pipeline_state.json",
                "status.js",
                "status.json",
            }
            for name in expected:
                (dashboard / name).write_text(name, encoding="utf-8")
            files = MODULE.iter_files(
                base,
                ["workflow/dashboard"],
                1024 * 1024,
            )
            self.assertEqual({path.name for path in files}, expected)

    def test_iter_files_excludes_self_changing_sync_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            root = base / "workflow" / "storyclaw_sync"
            root.mkdir(parents=True)
            state = root / "STORYCLAW_REALTIME_SYNC_STATE.json"
            receipt = root / "STORYCLAW_REALTIME_SYNC_RECEIPT.md"
            payload = root / "RECOVERY_RUNBOOK.md"
            state.write_text("{}", encoding="utf-8")
            receipt.write_text("receipt", encoding="utf-8")
            payload.write_text("payload", encoding="utf-8")
            files = MODULE.iter_files(
                base,
                ["workflow/storyclaw_sync"],
                1024 * 1024,
            )
            self.assertEqual(files, [payload])


if __name__ == "__main__":
    unittest.main()
