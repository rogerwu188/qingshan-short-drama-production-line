"""An off-screen voice owner in an empty insert still gets a map slot.

Fleet 1144 E02 VU029: an empty prop insert (no visible cast) carries a line spoken off screen.
The video task's blocking ledger got a row for the speaker with no zone_id / position / facing,
because the row borrowed them from a visible character and there was none.  The space gate then
failed the unit before any video POST with ``blocking: id_zone_position_or_facing_invalid``.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_nalu_preproduction import offscreen_voice_anchor

TASK = {"zone_id": "Z-STREET",
        "subspace_layout": {"zone_ids": ["Z-STREET", "Z-CURB"], "camera_position": [3.0, 1.5],
                            "camera_facing": "north",
                            "polygon": [[0, 0], [10, 0], [10, 4], [0, 4]]}}


def gate_accepts(row: dict, task: dict) -> bool:
    """The exact row condition of global_space_layout_gate.evaluate_task."""
    zone_ids = (task.get("subspace_layout") or {}).get("zone_ids") or []
    return bool(row.get("character_id") and row.get("zone_id") in zone_ids
                and row.get("position") and row.get("facing"))


class OffscreenVoiceAnchorTests(unittest.TestCase):
    def test_visible_character_is_the_first_choice(self):
        block = {"characters": [{"character_id": "C2", "zone_id": "Z-CURB", "position": [1, 1], "facing": "south"}],
                 "props": [{"prop_id": "P1", "zone_id": "Z-STREET", "position": [5, 2], "facing": "east"}]}
        self.assertEqual(offscreen_voice_anchor(block, TASK),
                         {"zone_id": "Z-CURB", "position": [1, 1], "facing": "south"})

    def test_empty_insert_borrows_the_visible_prop(self):
        block = {"characters": [],
                 "props": [{"prop_id": "P1", "zone_id": "Z-STREET", "position": [5, 2], "facing": "east"}]}
        anchor = offscreen_voice_anchor(block, TASK)
        self.assertEqual(anchor, {"zone_id": "Z-STREET", "position": [5, 2], "facing": "east"})
        self.assertTrue(gate_accepts({"character_id": "C1", **anchor}, TASK))

    def test_empty_insert_without_any_row_uses_the_camera_position(self):
        anchor = offscreen_voice_anchor({"characters": [], "props": []}, TASK)
        self.assertEqual(anchor, {"zone_id": "Z-STREET", "position": [3.0, 1.5], "facing": "north"})
        self.assertTrue(gate_accepts({"character_id": "C1", **anchor}, TASK))

    def test_camera_without_a_position_falls_back_to_the_subspace_polygon(self):
        task = {"zone_id": "Z-STREET", "subspace_layout": {**TASK["subspace_layout"], "camera_position": None}}
        anchor = offscreen_voice_anchor({}, task)
        self.assertEqual(anchor["position"], [5.0, 2.0])
        self.assertTrue(gate_accepts({"character_id": "C1", **anchor}, task))

    def test_incomplete_rows_are_not_borrowed(self):
        block = {"characters": [{"character_id": "C2", "screen_slot": "OFFSCREEN"}], "props": []}
        self.assertEqual(offscreen_voice_anchor(block, TASK)["zone_id"], "Z-STREET")

    def test_the_anchor_is_a_copy(self):
        block = {"characters": [], "props": [{"prop_id": "P1", "zone_id": "Z-STREET", "position": [5, 2], "facing": "east"}]}
        offscreen_voice_anchor(block, TASK)["position"].append(9)
        self.assertEqual(block["props"][0]["position"], [5, 2])

    def test_nothing_to_borrow_and_no_map_returns_none(self):
        self.assertIsNone(offscreen_voice_anchor({"characters": [], "props": []}, {}))


if __name__ == "__main__":
    unittest.main()
