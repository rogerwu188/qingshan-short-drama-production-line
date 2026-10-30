import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import english_contract_forbidden_terms_lint as lint  # noqa: E402


class EnglishForbiddenTermsLintTest(unittest.TestCase):
    def test_glass_lamp_is_caught_in_english_contract(self):
        doc = {"units": {"E99-VU-041@abc": {"english": {"beats": [{"entry_state": "the sunstone in the glass lamp casts light"}]}},
                         "E99-VU-001@def": {"english": {"beats": [{"entry_state": "a shallow glazed ceramic lamp-dish holds a glowing sun-stone"}]}}}}
        hits = lint.lint_contracts(doc, lint.forbidden_patterns())
        self.assertEqual({h["unit"].split("@")[0] for h in hits}, {"E99-VU-041"})
        self.assertIn("glass lamp", hits[0]["matched"].lower())

    def test_english_rows_of_engine_set_and_prompt_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "E99-VU-002.txt").write_text("a man checks his smartphone under a QR code sign", encoding="utf-8")
            Path(tmp, "E99-VU-003.txt").write_text("snow road, red lanterns under the eaves", encoding="utf-8")
            hits = lint.lint_prompt_files(Path(tmp), lint.forbidden_patterns())
            self.assertEqual(sorted({h["unit"] for h in hits}), ["E99-VU-002"])

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp, "c.json"); good.write_text(json.dumps({"units": {"u@1": {"english": {"x": "red lantern"}}}}), encoding="utf-8")
            bad = Path(tmp, "b.json"); bad.write_text(json.dumps({"units": {"u@1": {"english": {"x": "a kerosene lamp"}}}}), encoding="utf-8")
            tool = str(ROOT / "tools/english_contract_forbidden_terms_lint.py")
            self.assertEqual(subprocess.run([sys.executable, tool, "--contracts", str(good)], capture_output=True).returncode, 0)
            self.assertEqual(subprocess.run([sys.executable, tool, "--contracts", str(bad)], capture_output=True).returncode, 1)


if __name__ == "__main__":
    unittest.main()
