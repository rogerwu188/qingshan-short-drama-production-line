import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.h3_compile_anchor_freshness import compile_anchor_path, stale_reason

ENGINE = Path(__file__).resolve().parents[2]


class H3CompileAnchorFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pre = Path(self.tmp.name)

    def write(self, **fields):
        compile_anchor_path(self.pre, "E06").write_text(json.dumps({"units": [], **fields}), encoding="utf-8")

    def test_no_compile_copy_is_not_stale(self):
        self.assertIsNone(stale_reason(self.pre, "E06"))

    def test_complete_plan_is_not_stale(self):
        self.write(h3_identity_plates_missing=[], h3_prop_reference_cards_missing=[])
        self.assertIsNone(stale_reason(self.pre, "E06"))

    def test_plate_missing_before_keyframes_is_stale(self):
        self.write(h3_identity_plates_missing=["CHAR-LEO"], h3_prop_reference_cards_missing=[])
        self.assertEqual(stale_reason(self.pre, "E06"),
                         "H3_COMPILE_ANCHOR_PLAN_PREDATES_LOCKS:h3_identity_plates_missing=CHAR-LEO")

    def test_prop_card_missing_before_keyframes_is_stale(self):
        self.write(h3_prop_reference_cards_missing=["E06-VU-002:PROP-SABRE"])
        self.assertIn("h3_prop_reference_cards_missing=E06-VU-002:PROP-SABRE", stale_reason(self.pre, "E06"))

    def test_empty_keyframe_dir_does_not_hide_staleness(self):
        (self.pre / "keyframes").mkdir()
        self.write(h3_identity_plates_missing=["CHAR-LEO"])
        self.assertIsNotNone(stale_reason(self.pre, "E06"))

    def test_existing_keyframes_leave_the_plan_to_the_s6_rebuild(self):
        (self.pre / "keyframes").mkdir()
        (self.pre / "keyframes" / "E06-S01-01-keyframe-v1.png").write_bytes(b"png")
        self.write(h3_identity_plates_missing=["CHAR-LEO"])
        self.assertIsNone(stale_reason(self.pre, "E06"))

    def test_unreadable_plan_is_left_to_the_compile(self):
        compile_anchor_path(self.pre, "E06").write_text("{not json", encoding="utf-8")
        self.assertIsNone(stale_reason(self.pre, "E06"))

    def test_cli_exit_code_and_reason(self):
        argv = [sys.executable, str(ENGINE / "tools/h3_compile_anchor_freshness.py"),
                "--episode", "E06", "--preproduction-dir", str(self.pre)]
        self.assertEqual(subprocess.run(argv, capture_output=True, text=True).returncode, 1)
        self.write(h3_identity_plates_missing=["CHAR-LEO"])
        done = subprocess.run(argv, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0)
        self.assertTrue(done.stdout.startswith("H3_COMPILE_ANCHOR_PLAN_PREDATES_LOCKS:"))

    def test_prompt_batch_prepare_refreshes_s2_before_the_planning_compile(self):
        script = (ENGINE / "skills/nalu-claude-code/scripts/prompt_batch_prepare.sh").read_text(encoding="utf-8")
        check = script.index("tools/h3_compile_anchor_freshness.py")
        rebuild = script.index("--from S2 --until S2 --force")
        self.assertLess(check, rebuild)
        self.assertLess(rebuild, script.index("--from S5 --until S5"))
        self.assertLess(rebuild, script.index("plan_compile.sh"))


if __name__ == "__main__":
    unittest.main()
