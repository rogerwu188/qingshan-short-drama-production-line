"""compile_grouped_seedance_manifest: optional duration authority declared by the grouping plan
(integer provider slot over a half-second editorial sum) must reach the compiled unit unchanged,
and stay absent when the plan does not declare it (nalu D-63, 2026-09-18)."""
import re, unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "compile_grouped_seedance_manifest.py"


class DurationAuthorityPassthroughTests(unittest.TestCase):
    def test_compiled_unit_copies_declared_fields_only_when_present(self):
        text = SRC.read_text(encoding="utf-8")
        block = text[text.index("compiled_unit = {"):text.index("compiled_unit = {") + 1200]
        for field in ("authorized_content_seconds", "authorized_tail_handle_seconds"):
            self.assertRegex(block, re.compile(r'\*\*\(\{"%s": unit\["%s"\]\}\s*if unit\.get\("%s"\) is not None else \{\}\)' % (field, field, field)))

    def test_execution_plan_reads_the_same_fields(self):
        plan = (SRC.parent / "video_execution_plan_compiler.py").read_text(encoding="utf-8")
        self.assertIn('unit.get("authorized_content_seconds")', plan)
        self.assertIn('unit.get("authorized_tail_handle_seconds")', plan)


if __name__ == "__main__":
    unittest.main()
