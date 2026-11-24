"""A SCREENPLAY_V1 manifest (no episode_global_space_map_id / global_space_map_refs) gets
those fields from the episode GSM instead of crashing S2 with a KeyError
(fleet device 1101 E27, 2026-11-24)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import build_episode_asset_requirements as bear  # noqa: E402

GSM = {
    "episode_global_space_map_id": "EGSM-X-E27",
    "space_maps": [
        {"global_space_map_id": "GSM-A",
         "rooms": [{"room_id": "R1", "zones": [{"zone_id": "Z1", "name": "门口"}, {"zone_id": "Z2"}]}],
         "scene_mappings": [{"scene_id": "E27-S01", "room_id": "R1"}, {"scene_id": "E26-S03"}]},
        {"global_space_map_id": "GSM-B", "rooms": [], "scene_mappings": [{"scene_id": "E25-S01"}]},
    ],
}


class ScreenplayManifestGsmFieldsTests(unittest.TestCase):

    def test_missing_fields_come_from_the_gsm(self):
        manifest = {"schema": "qingshan.writer.manifest.v2", "writer_format": "SCREENPLAY_V1"}
        out = bear.fill_space_map_fields(manifest, GSM, "E27")
        self.assertEqual(out["episode_global_space_map_id"], "EGSM-X-E27")
        self.assertEqual(len(out["global_space_map_refs"]), 1)
        ref = out["global_space_map_refs"][0]
        self.assertEqual(ref["map_id"], "GSM-A")
        self.assertEqual(ref["scenes"], ["E27-S01"])
        self.assertEqual(ref["anchors"], ["门口", "Z2"])
        self.assertNotIn("episode_global_space_map_id", manifest)  # input untouched

    def test_present_fields_are_kept(self):
        manifest = {"episode_global_space_map_id": "EGSM-OWN",
                    "global_space_map_refs": [{"anchors": ["a"], "axis_note": "n"}]}
        out = bear.fill_space_map_fields(manifest, GSM, "E27")
        self.assertEqual(out["episode_global_space_map_id"], "EGSM-OWN")
        self.assertEqual(out["global_space_map_refs"], [{"anchors": ["a"], "axis_note": "n"}])

    def test_no_gsm_still_yields_indexable_fields(self):
        out = bear.fill_space_map_fields({}, None, "E27")
        self.assertTrue(out["episode_global_space_map_id"])
        self.assertIn("anchors", out["global_space_map_refs"][0])
        self.assertIn("axis_note", out["global_space_map_refs"][0])


if __name__ == "__main__":
    unittest.main()
