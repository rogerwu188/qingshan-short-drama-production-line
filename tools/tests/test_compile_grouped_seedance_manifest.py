import tempfile
import unittest
from pathlib import Path

from tools.compile_grouped_seedance_manifest import compile_manifest


class CompileGroupedSeedanceManifestTest(unittest.TestCase):
    def test_preserves_transport_strategy_and_reference_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.png"
            later = Path(tmp) / "later.png"
            first.write_bytes(b"first")
            later.write_bytes(b"later")
            grouping = {
                "episode": "E41",
                "video_unit_count": 1,
                "runtime_seconds": 6,
                "units": [{
                    "unit_id": "VU-1", "scene_id": "S1", "duration_seconds": 6,
                    "editorial_shot_ids": ["S1-1", "S1-2"], "narrative_beat": "beat",
                }],
            }
            anchors = {"units": [{
                "unit_id": "VU-1", "planned_reference_image_count": 2,
                "reference_image_paths": [str(first), str(later)],
                "reference_transport_strategy": "OMNI_MULTI_REFERENCE",
                "anchor_count_decision": {
                    "anchor_roles": ["ADMITTED_SCENE_START_STATE", "IDENTITY_OR_PROP_REANCHOR"],
                },
                "semantic_reference_coverage_gate": {"status": "PASS"},
            }]}
            editorial = {"shots": [
                {"shot_id": "S1-1", "model": "seedance-2.0-fast", "resolution": "720p", "prompt_spec": {}},
                {"shot_id": "S1-2", "model": "seedance-2.0-fast", "resolution": "720p", "prompt_spec": {}},
            ]}
            result = compile_manifest(grouping, anchors, editorial)
            unit = result["units"][0]
            self.assertEqual(unit["reference_transport_strategy"], "OMNI_MULTI_REFERENCE")
            self.assertEqual(
                [row["role"] for row in unit["reference_images"]],
                ["ADMITTED_SCENE_START_STATE", "IDENTITY_OR_PROP_REANCHOR"],
            )
            self.assertEqual(unit["semantic_reference_coverage_gate"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
