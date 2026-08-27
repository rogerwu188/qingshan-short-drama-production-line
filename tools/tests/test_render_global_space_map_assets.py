import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.global_space_layout_gate import RESOLUTION_ORDER, evaluate_batch
from tools.render_global_space_map_assets import build


class RenderGlobalSpaceMapAssetsTest(unittest.TestCase):
    def test_rendered_assets_form_a_valid_locked_chain(self):
        authority = {
            "schema": "qingshan.episode_global_space_map.v1", "episode": "E40",
            "episode_global_space_map_id": "EGSM-TEST", "map_version": 1,
            "authority_ref": "ROGER-TEST", "status": "PENDING",
            "inheritance": {"mode": "NEW"}, "map_image": {},
            "space_maps": [{
                "global_space_map_id": "GSM-TEST", "map_version": 1, "name": "Hall",
                "coordinate_system": {"origin": "south", "x_axis": "east", "y_axis": "north", "unit": "m"},
                "overall_bounds": {"width": 10, "depth": 10}, "layout_image": {},
                "rooms": [{
                    "room_id": "ROOM-TEST",
                    "zones": [{"zone_id": "ZONE-TEST", "name": "Zone", "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]}],
                    "fixed_elements": [{"element_id": "TABLE", "type": "table", "zone_id": "ZONE-TEST", "position": [8, 8], "traversable": False}],
                    "entrances": [{"entrance_id": "ENTRY", "zone_id": "ZONE-TEST", "position": [5, 0]}],
                    "axes": [{"axis_id": "AXIS", "endpoint_a": [1, 5], "endpoint_b": [9, 5], "default_screen_direction": "A_LEFT", "crossing_policy": "NO_CROSS"}],
                    "camera_positions": [{"angle_id": "ANGLE", "zone_id": "ZONE-TEST", "position": [5, 1], "facing": "north", "axis_id": "AXIS", "screen_direction": "A_LEFT"}],
                }],
                "scene_mappings": [{"scene_id": "S1", "room_id": "ROOM-TEST", "zone_ids": ["ZONE-TEST"]}],
            }],
        }
        task = {
            "task_key": "T1", "unit_id": "R1", "tool_type": "video_generation", "spatial_layout_stage": "VIDEO_GENERATION",
            "scene_id": "S1", "episode_global_space_map_id": "EGSM-TEST", "global_space_map_id": "GSM-TEST",
            "room_id": "ROOM-TEST", "zone_id": "ZONE-TEST", "angle_id": "ANGLE", "resolution_order": RESOLUTION_ORDER,
            "subspace_layout": {"subspace_id": "SUBSPACE", "derived_from_episode_global_space_map_id": "EGSM-TEST", "derived_from_global_space_map_id": "GSM-TEST", "room_id": "ROOM-TEST", "zone_ids": ["ZONE-TEST"], "angle_id": "ANGLE", "camera_position_id": "ANGLE", "axis_id": "AXIS", "visible_fixed_element_ids": ["TABLE"], "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]},
            "blocking": {"resolved_after_subspace_lock": True, "characters": [{"character_id": "CHAR", "zone_id": "ZONE-TEST", "position": [2, 2], "facing": "north"}], "props": []},
            "action_end_blocking": {"characters": [{"character_id": "CHAR", "zone_id": "ZONE-TEST", "position": [3, 3], "facing": "north"}], "props": []},
            "trajectory_overlays": [{"entity_id": "CHAR", "start": [2, 2], "waypoints": [], "end": [3, 3]}],
            "entity_reference_bindings": [{"role": "character", "entity_id": "CHAR", "path": "identity.png"}],
        }
        with tempfile.TemporaryDirectory() as directory:
            locked, plan, receipt = build(authority, {"episode": "E40", "tasks": [task]}, Path(directory))
            report = evaluate_batch(locked, plan["tasks"], episode="E40")
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual(locked["topology_sha256"], hashlib.sha256(
            __import__("json").dumps(locked["space_maps"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest())

    def test_renderer_supports_multiple_place_maps(self):
        authority = {
            "schema": "qingshan.episode_global_space_map.v1", "episode": "E42",
            "episode_global_space_map_id": "EGSM-E42", "map_version": 1,
            "authority_ref": "ROGER-20260827-E42-COMPLETE-MAP-MODE", "status": "PENDING",
            "inheritance": {"mode": "NEW"}, "map_image": {}, "space_maps": [],
        }
        tasks = []
        for index in range(2):
            map_id, scene_id = f"GSM-{index}", f"S{index}"
            room_id, zone_id, angle_id = f"ROOM-{index}", f"ZONE-{index}", f"ANGLE-{index}"
            authority["space_maps"].append({
                "global_space_map_id": map_id, "map_version": 1, "name": f"Place {index}",
                "coordinate_system": {"origin": "south", "x_axis": "east", "y_axis": "north", "unit": "m"},
                "overall_bounds": {"width": 10, "depth": 10}, "layout_image": {},
                "rooms": [{
                    "room_id": room_id,
                    "zones": [{"zone_id": zone_id, "name": "Zone", "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]}],
                    "fixed_elements": [{"element_id": f"FIXED-{index}", "type": "table", "zone_id": zone_id, "position": [8, 8], "traversable": False}],
                    "entrances": [{"entrance_id": f"ENTRY-{index}", "zone_id": zone_id, "position": [5, 0]}],
                    "axes": [{"axis_id": f"AXIS-{index}", "endpoint_a": [1, 5], "endpoint_b": [9, 5], "default_screen_direction": "A_LEFT", "crossing_policy": "NO_CROSS"}],
                    "camera_positions": [{"angle_id": angle_id, "zone_id": zone_id, "position": [5, 1], "facing": "north", "axis_id": f"AXIS-{index}", "screen_direction": "A_LEFT"}],
                }],
                "scene_mappings": [{"scene_id": scene_id, "room_id": room_id, "zone_ids": [zone_id]}],
            })
            tasks.append({
                "task_key": f"T{index}", "unit_id": f"R{index}", "tool_type": "video_generation", "spatial_layout_stage": "VIDEO_GENERATION",
                "scene_id": scene_id, "episode_global_space_map_id": "EGSM-E42", "global_space_map_id": map_id,
                "room_id": room_id, "zone_id": zone_id, "angle_id": angle_id, "resolution_order": RESOLUTION_ORDER,
                "subspace_layout": {"subspace_id": f"SUB-{index}", "derived_from_episode_global_space_map_id": "EGSM-E42", "derived_from_global_space_map_id": map_id, "room_id": room_id, "zone_ids": [zone_id], "angle_id": angle_id, "camera_position_id": angle_id, "axis_id": f"AXIS-{index}", "visible_fixed_element_ids": [f"FIXED-{index}"], "polygon": [[0, 0], [10, 0], [10, 10], [0, 10]]},
                "blocking": {"resolved_after_subspace_lock": True, "characters": [], "props": []},
            })
        with tempfile.TemporaryDirectory() as directory:
            locked, plan, receipt = build(authority, {"episode": "E42", "tasks": tasks}, Path(directory))
            report = evaluate_batch(locked, plan["tasks"], episode="E42")
        self.assertEqual(len(receipt["place_maps"]), 2)
        self.assertEqual(report["status"], "PASS", report["failures"])


if __name__ == "__main__":
    unittest.main()
