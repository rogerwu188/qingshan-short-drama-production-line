"""H3 V2 video prompt honours a per-shot wardrobe state override like the keyframe does (…1324 E05-S04-26)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.h3_director_prompt_v2 import subject_sources  # noqa: E402

BASE = "Faded brown patched coarse cotton tunic, worn dark trousers and frayed cloth shoes."
CLEAN = "Clean plain brown cotton tunic, clean dark trousers and clean cloth shoes."


def unit(**spec_extra):
    return {
        "character_entities": [{"character_id": "CHAR-LUZHU", "appearance_en": "slim young woman"}],
        "wardrobe_contract": {"characters": [{"character_id": "CHAR-LUZHU", "authored_description": BASE}]},
        "ordered_prompt_specs": [{"cast": [{"character_id": "CHAR-LUZHU", "character": "鹿竹"}], **spec_extra}],
    }


class WardrobeStateOverrideTest(unittest.TestCase):
    def test_override_replaces_base_wardrobe(self):
        row = subject_sources(unit(wardrobe_state_overrides={"CHAR-LUZHU": CLEAN}))[0]
        self.assertEqual(row["wardrobe"], CLEAN)

    def test_without_override_base_wardrobe_kept(self):
        self.assertEqual(subject_sources(unit())[0]["wardrobe"], BASE)


if __name__ == "__main__":
    unittest.main()
