"""Prompt batch QA counts a multi-view character sheet as one identity reference (lab E05)."""
from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("prompt_batch_qa", ROOT / "lines/nalu/runtime/tools/prompt_batch_qa.py")


class SheetIdentityLineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = importlib.util.module_from_spec(SPEC)
        SPEC.loader.exec_module(cls.mod)

    def count(self, text: str) -> int:
        return len(re.findall(self.mod.V2_IDENTITY_LINE, text, flags=re.M))

    def test_plate_and_sheet_lines_both_count(self) -> None:
        text = ("@Image1 is the opening frame: match its setting.\n"
                "@Image2 is Helen's face and body.\n"
                "@Image3 is a character sheet of one person: Holmes's face close-up and full-body front, side and "
                "back views in the same clothes; these are views of a single person, render Holmes only once.\n")
        self.assertEqual(self.count(text), 2)

    def test_opening_frame_is_not_an_identity(self) -> None:
        self.assertEqual(self.count("@Image1 is the opening frame: match its setting.\n"), 0)


if __name__ == "__main__":
    unittest.main()
