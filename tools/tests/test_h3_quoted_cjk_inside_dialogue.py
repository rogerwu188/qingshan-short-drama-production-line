"""Chinese quotes inside <d>[Chinese]...</d> are dialogue; outside the tag they stay forbidden."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.h3_provider_english_contract import validate_h3_provider_text_boundary as v  # noqa: E402


class QuotedCjkInsideDialogueTest(unittest.TestCase):
    def test_quotes_inside_dialogue_pass(self) -> None:
        self.assertEqual(v('He says <d>[Chinese]「好，走吧。」</d> and turns.', source_id="A")["status"], "PASS")
        self.assertEqual(v('<d>[Chinese]这是「十三响毛瑟」。</d>', source_id="B")["status"], "PASS")

    def test_quotes_outside_dialogue_fail(self) -> None:
        out = v('Sign reads 「当铺」 <d>[Chinese]走吧。</d>', source_id="C")
        self.assertIn("H3_QUOTED_CJK_FORBIDDEN:C", out["failures"])


if __name__ == "__main__":
    unittest.main()
