import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.global_space_layout_gate import (
    RESOLUTION_ORDER,
    content_sha256,
    evaluate_authority,
    evaluate_batch,
)


class GlobalSpaceLayoutGateTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.episode_image = self.media("episode-map.png")
        self.place_image = self.media("place-map.png")
        self.subspace_image = self.media("subspace.png")

    def media(self, name):
        path = self.root / name
        path.write_bytes(name.encode("utf-8"))
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "qa_status": "PASS"}

    def authority(self, episode="E40"):
        place_map = {
            "global_space_map_id": "GSM-WANGFU-001",
            "map_version": 1,
            "name": "Wangfu Hall",
            "coordinate_system": {"origin": "southwest", "x_axis": "east", "y_axis": "north", "unit": "m"},
            "overall_bounds": {"width": 18, "depth": 24},
            "layout_image": {**self.place_image, "kind": "PLACE_TOP_DOWN_COMPLETE_SPACE_MAP"},
            "rooms": [{
                "room_id": "ROOM-WANGFU-HALL",
                "zones": [{"zone_id": "ZONE-FRONT", "polygon": [[0, 0], [9, 0], [9, 12], [0, 12]]}],
                "fixed_elements": [{"element_id": "FIXED-CURTAIN", "zone_id": "ZONE-FRONT", "position": [4.5, 10]}],
                "entrances": [{"entrance_id": "ENTRY-SOUTH", "zone_id": "ZONE-FRONT", "position": [4.5, 0]}],
                "axes": [{
                    "axis_id": "AXIS-MAIN", "endpoint_a": [0, 6], "endpoint_b": [9, 6],
                    "default_screen_direction": "A_LEFT_B_RIGHT", "crossing_policy": "NO_CROSS",
                }],
                "camera_positions": [{
                    "angle_id": "ANGLE-SOUTH-WIDE", "zone_id": "ZONE-FRONT",
                    "position": [4.5, 1], "facing": "north", "axis_id": "AXIS-MAIN",
                    "screen_direction": "A_LEFT_B_RIGHT",
                }],
            }],
            "scene_mappings": [{"scene_id": "S1", "room_id": "ROOM-WANGFU-HALL", "zone_ids": ["ZONE-FRONT"]}],
        }
        authority = {
            "schema": "qingshan.episode_global_space_map.v1",
            "episode": episode,
            "episode_global_space_map_id": "EGSM-WANGFU-SEQUENCE-001",
            "map_version": 1,
            "authority_ref": "ROGER-TEST",
            "status": "LOCKED",
            "inheritance": {"mode": "NEW"},
            "map_image": {**self.episode_image, "kind": "EPISODE_TOP_DOWN_COMPLETE_SPACE_MAP"},
            "space_maps": [place_map],
        }
        authority["topology_sha256"] = content_sha256(authority["space_maps"])
        return authority

    def task(self, authority):
        place = authority["space_maps"][0]
        subspace_ref = {
            **self.subspace_image,
            "kind": "SHOT_SUBSPACE_LAYOUT",
            "derived_from_place_map_sha256": place["layout_image"]["sha256"],
        }
        return {
            "task_key": "E40-R01-A1", "tool_type": "image_generation",
            "spatial_layout_stage": "SHOT_KEYFRAME", "scene_id": "S1",
            "episode_global_space_map_id": authority["episode_global_space_map_id"],
            "global_space_map_id": place["global_space_map_id"],
            "room_id": "ROOM-WANGFU-HALL", "zone_id": "ZONE-FRONT",
            "angle_id": "ANGLE-SOUTH-WIDE", "resolution_order": RESOLUTION_ORDER,
            "subspace_layout": {
                "subspace_id": "SUBSPACE-R01-A1",
                "derived_from_episode_global_space_map_id": authority["episode_global_space_map_id"],
                "derived_from_global_space_map_id": place["global_space_map_id"],
                "room_id": "ROOM-WANGFU-HALL", "zone_ids": ["ZONE-FRONT"],
                "angle_id": "ANGLE-SOUTH-WIDE", "camera_position_id": "ANGLE-SOUTH-WIDE",
                "axis_id": "AXIS-MAIN", "visible_fixed_element_ids": ["FIXED-CURTAIN"],
                "reference_image": subspace_ref,
            },
            "blocking": {
                "resolved_after_subspace_lock": True,
                "characters": [{"character_id": "CHAR-CHENJI", "zone_id": "ZONE-FRONT", "position": [4, 5], "facing": "north"}],
                "props": [],
            },
            "reference_bindings": [
                {"role": "episode_global_space_map", "path": authority["map_image"]["path"], "sha256": authority["map_image"]["sha256"]},
                {"role": "global_space_map", "path": place["layout_image"]["path"], "sha256": place["layout_image"]["sha256"]},
                {"role": "subspace_layout", "path": subspace_ref["path"], "sha256": subspace_ref["sha256"]},
                {"role": "character", "entity_id": "CHAR-CHENJI", "path": "not_checked_by_this_gate"},
            ],
        }

    def test_complete_chain_passes(self):
        authority = self.authority()
        report = evaluate_batch(authority, [self.task(authority)], episode="E40")
        self.assertEqual(report["status"], "PASS", report["failures"])

    def test_missing_episode_map_id_blocks_shot(self):
        authority = self.authority()
        task = self.task(authority)
        task.pop("episode_global_space_map_id")
        report = evaluate_batch(authority, [task], episode="E40")
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(row.get("check") == "episode_global_space_map_id" for row in report["failures"]))

    def test_character_before_subspace_binding_is_rejected(self):
        authority = self.authority()
        task = self.task(authority)
        task["reference_bindings"][1], task["reference_bindings"][3] = task["reference_bindings"][3], task["reference_bindings"][1]
        report = evaluate_batch(authority, [task], episode="E40")
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(row.get("reason") == "order_must_be_episode_map_place_map_subspace_then_character_prop" for row in report["failures"]))

    def test_exact_cross_episode_inheritance_preserves_id_version_topology_and_image(self):
        source = self.authority("E40")
        source_path = self.root / "E40-map.json"
        source_path.write_text(json.dumps(source), encoding="utf-8")
        inherited = self.authority("E41")
        inherited["inheritance"] = {
            "mode": "INHERITED_EXACT", "source_episode": "E40",
            "source_authority_path": str(source_path),
            "source_authority_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "source_episode_global_space_map_id": source["episode_global_space_map_id"],
            "source_map_version": source["map_version"],
            "source_topology_sha256": source["topology_sha256"],
            "source_map_image_sha256": source["map_image"]["sha256"],
        }
        self.assertEqual(evaluate_authority(inherited)["status"], "PASS")
        inherited["map_version"] = 2
        self.assertEqual(evaluate_authority(inherited)["status"], "FAIL")

    def test_pre_e40_legacy_batch_is_not_retroactively_blocked(self):
        report = evaluate_batch(None, [{"task_key": "OLD", "tool_type": "video_generation"}], episode="E39")
        self.assertEqual(report["status"], "N_A")

    def test_e40_variant_name_cannot_bypass_gate(self):
        report = evaluate_batch(
            None,
            [{"task_key": "REMAKE", "tool_type": "video_generation"}],
            episode="E40-REMAKE-V1",
        )
        self.assertEqual(report["status"], "FAIL")

    def test_e42_explicit_false_cannot_bypass_complete_map_mode(self):
        report = evaluate_batch(
            None,
            [{"task_key": "E42-SHOT", "tool_type": "video_generation"}],
            episode="E42",
            required=False,
        )
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(row.get("check") == "authority_load" for row in report["failures"]))


if __name__ == "__main__":
    unittest.main()
