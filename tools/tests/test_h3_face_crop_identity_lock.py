"""A PIXEL_CROP identity transport locks the face only (E12 2026-10-30: the face crop's collar pulled the
source card's robe and crown onto every clip because the line said "lock ... body and wardrobe")."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from tools import h3_provider_prompt_renderer as h3  # noqa: E402
from tools.tests.test_h3_director_prompt_v2 import fixture  # noqa: E402


def path_of(ref):
    return str(ref.get("path")) if isinstance(ref, dict) else str(ref)


def identity_lines(text):
    return [line for line in text.splitlines()
            if line.startswith("@Image") and ("identity of" in line or "face and body" in line or "face only" in line)]


class FaceCropIdentityLockTest(unittest.TestCase):
    def test_face_crop_line_drops_wardrobe_lock_and_others_keep_it(self):
        for kwargs in ({"style": True, "director": False}, {"style": False, "director": False}):
            unit, plan = fixture(**kwargs)
            before = identity_lines(h3.render_h3_prompt(unit, plan)[0])
            self.assertTrue(before, kwargs)
            crop = path_of(unit["reference_images"][-1])
            unit["face_only_identity_references"] = [crop]
            after = identity_lines(h3.render_h3_prompt(unit, plan)[0])
            last = len(unit["reference_images"])
            cropped = [line for line in after if re.match(rf"@Image{last}[: ]", line)]
            self.assertEqual(len(cropped), 1, after)
            self.assertRegex(cropped[0], r"face, age and hair only|face only: a face crop")
            self.assertNotIn("wardrobe;", cropped[0])
            self.assertNotIn("face and body", cropped[0])
            self.assertEqual([l for l in after if not re.match(rf"@Image{last}[: ]", l)],
                             [l for l in before if not re.match(rf"@Image{last}[: ]", l)])

    def test_opening_frame_is_never_treated_as_a_face_crop(self):
        unit, plan = fixture(style=True, director=False)
        text = h3.render_h3_prompt(unit, plan)[0]
        unit["face_only_identity_references"] = [path_of(unit["reference_images"][0])]
        self.assertEqual(h3.render_h3_prompt(unit, plan)[0], text)


if __name__ == "__main__":
    unittest.main()


class AppearanceAnchorLineTest(unittest.TestCase):
    """E12 2026-10-31: a bound character's appearance_anchor_en is stated right after the TEXT-FREE rule."""

    def test_anchor_line_follows_text_free_rule_only_when_declared(self):
        unit, plan = fixture(style=False, director=False)
        plain = h3.render_h3_prompt(unit, plan)[0]
        self.assertNotIn("Same look in every frame", plain)
        labels = h3._entity_labels(unit, plan)
        cid = next(iter(labels))
        unit["character_entities"] = [{"character_id": cid, "appearance_anchor_en": "thick full black beard, leather armour"},
                                      {"character_id": "CHAR-NOT-BOUND", "appearance_anchor_en": "should not appear"}]
        lines = h3.render_h3_prompt(unit, plan)[0].splitlines()
        self.assertTrue(lines[0].startswith(h3.ANTI_TEXT))
        self.assertEqual(lines[1], f"Same look in every frame: {labels[cid]} = "
                                   "thick full black beard, leather armour.")
        self.assertNotIn("should not appear", "\n".join(lines))


    def test_compact_anchor_keeps_the_two_distinguishing_traits(self):
        unit, plan = fixture(style=False, director=False)
        cid = next(iter(h3._entity_labels(unit, plan)))
        unit["character_entities"] = [{"character_id": cid, "appearance_anchor_en":
                                       "burly middle-aged man, thick full black beard, brown leather armour, cloak"}]
        line = h3.appearance_anchor_line(unit, plan, compact=True)
        self.assertTrue(line.endswith("= thick full black beard, brown leather armour."))
