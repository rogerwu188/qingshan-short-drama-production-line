"""Fleet device …1101 E04 S6 (2026-11-11): a hard-continuation unit opens on the previous unit's real
final frame (its first-shot keyframe is deferred to that tail).  The video task bound entities only to
"<shot>-keyframe" images, so the tail bound nothing and the submitter precheck raised
MISSING_ANCHOR_FOR_CANONICAL_ENTITY for the opening shot's character and props."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (str(TOOLS), str(ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)


class TailUnitEntityAnchorsTest(unittest.TestCase):
    def setUp(self):
        import build_nalu_preproduction as bnp
        self.bnp = bnp
        self.tail = {"path": "/rt/real_final_frames/E04-VU-011.png", "sha256": "t",
                     "role": "PREVIOUS_UNIT_REAL_FINAL_FRAME"}
        self.kf = {"path": "/wf/keyframes/E04-S03-05-keyframe-v1.png", "sha256": "k", "role": "SEMANTIC_ANCHOR"}
        self.plate = {"path": "/lib/CHAR-LINGYAO__SHEET.png", "sha256": "p", "role": "CHARACTER_IDENTITY_REFERENCE",
                      "entity_id": "CHAR-LINGYAO"}

    def test_tail_stands_in_for_the_first_shot(self):
        got = self.bnp.semantic_refs_by_shot([self.tail, self.kf, self.plate], ["E04-S03-04", "E04-S03-05"])
        self.assertIs(got["E04-S03-04"], self.tail)
        self.assertIs(got["E04-S03-05"], self.kf)

    def test_own_first_keyframe_wins_over_tail(self):
        own = {"path": "/wf/keyframes/E04-S03-04-keyframe-v1.png", "sha256": "o", "role": "X"}
        got = self.bnp.semantic_refs_by_shot([self.tail, own], ["E04-S03-04"])
        self.assertIs(got["E04-S03-04"], own)

    def test_no_tail_no_binding(self):
        self.assertEqual(self.bnp.semantic_refs_by_shot([self.plate], ["E04-S03-04"]), {})

    def test_present_plate_binds_by_entity_reference(self):
        src = (TOOLS / "build_nalu_preproduction.py").read_text(encoding="utf-8")
        body = src.split("def finalize_video_tasks(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("ref_by_shot = semantic_refs_by_shot(refs, shot_ids)", body)
        self.assertIn("plate = present_plates.get(cid) or _locked_identity_plate(cid, episode=episode)", body)


if __name__ == "__main__":
    unittest.main()
