"""A one-word line of another shot is not matched inside the renderer's identity prose (…1122 E03)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

import prompt_batch_qa as q  # noqa: E402

D = {"S1": [], "S2": ["Matteo：Seraphina."], "S3": ["Matteo: Take her home now."]}
PROSE = ("@Image2 is a character sheet of one person: Seraphina's face close-up; render Seraphina only once. "
         "This is the same Seraphina already in @Image1 — one person; never draw a second Seraphina.\n"
         "Dialogue: none. Nobody speaks; every visible person keeps their mouth closed.")


class OneWordForeignLineTest(unittest.TestCase):
    def test_name_ending_a_prose_sentence_is_not_foreign_dialogue(self) -> None:
        self.assertEqual(q.foreign_dialogue(PROSE, D, ["S1"]), [])

    def test_one_word_line_leaked_as_dialogue_is_caught(self) -> None:
        for leaked in ("Dialogue (Matteo only, once, lips in sync):\nSeraphina.",
                       "1. Matteo, 0-2s: Seraphina.", 'Matteo says "Seraphina."', "Seraphina."):
            self.assertEqual(q.foreign_dialogue(PROSE + "\n" + leaked, D, ["S1"]), ["Seraphina."], leaked)

    def test_longer_foreign_line_keeps_plain_substring_match(self) -> None:
        self.assertEqual(q.foreign_dialogue("He adds Take her home now.", D, ["S1"]), ["Take her home now."])

    def test_own_one_word_line_is_never_foreign(self) -> None:
        self.assertEqual(q.foreign_dialogue("Dialogue:\nSeraphina.", D, ["S2"]), [])


if __name__ == "__main__":
    unittest.main()
