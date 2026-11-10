"""Same-speaker continuation lines render as one utterance without the repeated label (field device …1324 E04)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.h3_provider_prompt_renderer import _dialogue_partition  # noqa: E402


class ContinuationLabelTest(unittest.TestCase):
    def test_chinese_continuation_label_removed_and_joined(self):
        raw = "金公子：但是进天道宗的入门费需要一百块下品灵石，\n金公子：我搜集了这么多天还差五块啊！"
        speaker, sep, words = _dialogue_partition(raw, "zh")
        self.assertEqual((speaker, sep), ("金公子", "："))
        self.assertEqual(words, "但是进天道宗的入门费需要一百块下品灵石，我搜集了这么多天还差五块啊！")
        self.assertNotIn("金公子", words)

    def test_english_continuation_joined_with_space(self):
        _, _, words = _dialogue_partition("Ann: I came all this way,\nAnn: and you are not here.", "en")
        self.assertEqual(words, "I came all this way, and you are not here.")

    def test_single_line_unchanged(self):
        self.assertEqual(_dialogue_partition("金公子：还差五块。", "zh"), ("金公子", "：", "还差五块。"))


class TransactionDialogueAgreesWithRendererTest(unittest.TestCase):
    def test_transaction_spoken_text_matches_rendered_words(self):
        sys.path.insert(0, str(ROOT / "lines" / "nalu" / "runtime" / "tools"))
        import build_nalu_preproduction as bnp
        raw = "金公子：但是进天道宗的入门费需要一百块下品灵石，\n金公子：我搜集了这么多天还差五块啊！"
        rows = bnp._spec_dialogue_rows([{"dialogue": raw}], ["E04-S02-10"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["speaker"], "金公子")
        self.assertEqual(rows[0]["spoken_text"], _dialogue_partition(raw, "zh")[2])
        self.assertNotIn("金公子", rows[0]["spoken_text"])


if __name__ == "__main__":
    unittest.main()
