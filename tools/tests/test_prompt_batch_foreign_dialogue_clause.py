"""A unit's own line that contains another shot's line is not foreign dialogue."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import prompt_batch_qa as q  # noqa: E402

D = {"S1": ["女子：如憐妾而活之，須秘密，勿泄。"], "S2": ["王生：須秘密，勿泄。"], "S3": ["道士：此物尚在，速去勿疑。"]}


class ForeignDialogueClauseTest(unittest.TestCase):
    def test_clause_inside_own_line_is_not_foreign(self) -> None:
        self.assertEqual(q.foreign_dialogue("<d>[Chinese]如憐妾而活之，須秘密，勿泄。</d>", D, ["S1"]), [])

    def test_foreign_line_outside_own_line_is_still_caught(self) -> None:
        self.assertEqual(q.foreign_dialogue("<d>如憐妾而活之，須秘密，勿泄。</d> 須秘密，勿泄。", D, ["S1"]), ["須秘密，勿泄。"])
        self.assertEqual(q.foreign_dialogue("此物尚在，速去勿疑。", D, ["S1"]), ["此物尚在，速去勿疑。"])


if __name__ == "__main__":
    unittest.main()
