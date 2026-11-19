"""The digest must read an unprefixed location id back out of the keyframe prompt.

A Japanese-language series named its locations ``ROYAL_HALL`` (no ``LOC-`` prefix, with an
underscore).  The keyframe builder rendered 「地点：ROYAL_HALL｜房间：ROOM-ROYAL_HALL」 and the
digest's ``LOC-[A-Z0-9-]+`` pattern found no location line, so ``kf_location_matches_scene``
and ``kf_room_exists_in_gsm`` failed for all 28 keyframes before any paid submit.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools"))
from prompt_batch_qa import keyframe_place_ids


def prompt(location, room, gsm, episode_gsm="GSM-JA01-E01"):
    return (
        "【空间解析顺序（不可跳级）】\n"
        f"{episode_gsm} → {gsm} → SUBSPACE-E01-S01-01 → 人物/道具站位\n"
        f"地点：{location}｜房间：{room}｜区域：ZONE-A、ZONE-B\n"
        "机位：ANGLE-1｜轴线：AXIS-1\n"
    )


class KeyframePlaceIdTests(unittest.TestCase):
    def test_unprefixed_location_with_underscore(self):
        loc, gm = keyframe_place_ids(prompt("ROYAL_HALL", "ROOM-ROYAL_HALL", "GSM-JA01-ROYAL_HALL"))
        self.assertIsNotNone(loc)
        self.assertEqual(loc.group(1), "ROYAL_HALL")
        self.assertEqual(loc.group(2), "ROOM-ROYAL_HALL")
        self.assertIsNotNone(gm)
        self.assertEqual(gm.group(1), "GSM-JA01-ROYAL_HALL")

    def test_prefixed_location_reads_as_before(self):
        loc, gm = keyframe_place_ids(prompt(
            "LOC-QINMING-HOUSE-INT", "ROOM-QINMING-INT", "GSM-YEWUJIANG-QINMING-LUZE-ADJOINING-HOMESTEAD"))
        self.assertEqual(loc.group(1), "LOC-QINMING-HOUSE-INT")
        self.assertEqual(loc.group(2), "ROOM-QINMING-INT")
        self.assertEqual(gm.group(1), "GSM-YEWUJIANG-QINMING-LUZE-ADJOINING-HOMESTEAD")

    def test_ids_stop_at_the_field_delimiter(self):
        loc, _ = keyframe_place_ids(prompt("ROYAL_HALL", "ROOM-ROYAL_HALL", "GSM-JA01-ROYAL_HALL"))
        self.assertNotIn("｜", loc.group(1))
        self.assertNotIn("｜", loc.group(2))

    def test_missing_location_line_is_still_a_miss(self):
        loc, gm = keyframe_place_ids("用途：E01 逐镜关键帧。\n景别：MEDIUM\n")
        self.assertIsNone(loc)
        self.assertIsNone(gm)

    def test_unresolved_room_is_not_hidden(self):
        """A room the builder could not resolve renders as None and stays visible to the caller."""
        loc, _ = keyframe_place_ids(prompt("ROYAL_HALL", "None", "None"))
        self.assertEqual(loc.group(2), "None")


if __name__ == "__main__":
    unittest.main()
