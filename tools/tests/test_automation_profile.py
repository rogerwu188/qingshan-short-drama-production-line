"""The unattended-run profile must stay portable and must not be able to widen itself.

Two properties are load-bearing:

* ``.claude/settings.json`` is **tracked**, so it may not carry a single absolute path — else one
  machine's layout ships to every clone.
* The profile is *permissions*, never authority.  It must not contain an order sequence, a credit
  cap or a credential, and it must deny editing the order file and editing itself, because those
  are the two ways a model would manufacture its own authorisation.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools"))
import automation_profile as ap


class TrackedProfileTests(unittest.TestCase):
    def test_no_absolute_path_anywhere(self):
        import re
        payload = json.dumps(ap._settings_payload(Path("/Users/someone/nalu"), None), ensure_ascii=False)
        self.assertIsNone(re.search(r"/Users/|/home/|/Volumes/", payload))

    def test_publication_and_destructive_git_are_denied(self):
        deny = ap._settings_payload(Path("/tmp/repo"), None)["permissions"]["deny"]
        for rule in ("Bash(git push:*)", "Bash(gh pr merge:*)", "Bash(git reset --hard:*)",
                     "Bash(git checkout --:*)"):
            with self.subTest(rule=rule):
                self.assertIn(rule, deny)

    def test_self_widening_and_order_editing_are_denied(self):
        deny = ap._settings_payload(Path("/tmp/repo"), None)["permissions"]["deny"]
        for rule in ("Edit(./.claude/**)", "Write(./.claude/**)",
                     "Edit(./workflow/**)", "Write(./workflow/**)"):
            with self.subTest(rule=rule):
                self.assertIn(rule, deny)

    def test_credentials_are_not_readable(self):
        deny = ap._settings_payload(Path("/tmp/repo"), None)["permissions"]["deny"]
        self.assertIn("Read(./.env)", deny)
        self.assertIn("Read(./.env.*)", deny)

    def test_the_paid_entry_point_is_allowed(self):
        allow = ap._settings_payload(Path("/tmp/repo"), None)["permissions"]["allow"]
        self.assertTrue(any(rule.startswith("Bash(lines/nalu/runtime/tools/paid_stage.sh")
                            for rule in allow))

    def test_the_profile_carries_no_authority_fields(self):
        payload = json.dumps(ap._settings_payload(Path("/tmp/repo"), None), ensure_ascii=False)
        for forbidden in ("paid_requests_allowed", "NALU_PAID_ORDER_SEQ", "credits", "GIGGLE_API_KEY"):
            with self.subTest(field=forbidden):
                self.assertNotIn(forbidden, payload)


class LocalProfileTests(unittest.TestCase):
    def test_the_private_order_file_is_denied_by_absolute_path(self):
        runtime = Path("/tmp/nalu_runtime")
        payload = ap._local_payload(Path("/tmp/repo"), runtime, {})
        deny = payload["permissions"]["deny"]
        self.assertIn(f"Edit({runtime}/**/SUPERVISOR_ORDERS.json)", deny)
        self.assertIn(f"Write({runtime}/**/qingshan.json)", deny)

    def test_runtime_root_is_added_to_additional_directories(self):
        runtime = Path("/tmp/nalu_runtime")
        payload = ap._local_payload(Path("/tmp/repo"), runtime, {})
        self.assertIn(str(runtime), payload["additionalDirectories"])

    def test_existing_rules_are_kept(self):
        existing = {"permissions": {"allow": ["Bash(wc:*)"]}, "defaultMode": "auto"}
        payload = ap._local_payload(Path("/tmp/repo"), Path("/tmp/rt"), existing)
        self.assertIn("Bash(wc:*)", payload["permissions"]["allow"])
        self.assertEqual(payload["defaultMode"], "auto")

    def test_a_local_human_channel_is_allowed(self):
        allow = ap._local_payload(Path("/tmp/repo"), Path("/tmp/rt"), {})["permissions"]["allow"]
        self.assertIn("Bash(open:*)", allow)


class WriteGuardTests(unittest.TestCase):
    def test_write_refuses_when_the_tracked_profile_would_leak_a_path(self):
        original = ap.TRACKED_ALLOW
        ap.TRACKED_ALLOW = original + ["Bash(/Users/someone/private/tool:*)"]
        try:
            with tempfile.TemporaryDirectory() as repo_tmp, \
                 tempfile.TemporaryDirectory() as runtime_tmp:
                args = type("A", (), {"repo_root": repo_tmp, "runtime_root": runtime_tmp,
                                      "line_owner": "Roger", "force": False})()
                self.assertEqual(ap.cmd_write(args), 2)
                self.assertFalse((Path(repo_tmp) / ".claude/settings.json").exists())
        finally:
            ap.TRACKED_ALLOW = original

    def test_write_then_check_passes(self):
        with tempfile.TemporaryDirectory() as repo_tmp, \
             tempfile.TemporaryDirectory() as runtime_tmp:
            args = type("A", (), {"repo_root": repo_tmp, "runtime_root": runtime_tmp,
                                  "line_owner": "Roger", "force": False})()
            self.assertEqual(ap.cmd_write(args), 0)
            check = type("A", (), {"repo_root": repo_tmp})()
            self.assertEqual(ap.cmd_check(check), 0)

    def test_check_fails_without_a_profile(self):
        with tempfile.TemporaryDirectory() as repo_tmp:
            check = type("A", (), {"repo_root": repo_tmp})()
            self.assertEqual(ap.cmd_check(check), 2)


if __name__ == "__main__":
    unittest.main()
