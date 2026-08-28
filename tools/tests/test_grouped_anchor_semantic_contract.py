import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.grouped_anchor_semantic_contract import validate_start_anchor_semantics


class GroupedAnchorSemanticContractTests(unittest.TestCase):
    def test_rejects_empty_anchor_when_first_beat_requires_actor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "start.png"
            image.write_bytes(b"image")
            image_sha = hashlib.sha256(image.read_bytes()).hexdigest()
            evidence = root / "evidence.json"
            evidence.write_text(json.dumps({
                "status": "PASS", "reference_path": str(image), "reference_sha256": image_sha,
                "observed_visible_characters": [], "observed_visible_props": [],
                "observed_space_anchors": ["帘口"], "camera_start_framing_match": True,
                "space_match": True, "empty_establishing_frame": True,
            }), encoding="utf-8")
            contract = {
                "status": "PASS", "reference_path": str(image), "reference_sha256": image_sha,
                "evidence_ref": str(evidence), "observed_visible_characters": [],
                "observed_visible_props": [], "observed_space_anchors": ["帘口"],
                "camera_start_framing_match": True, "space_match": True,
                "empty_establishing_frame": True,
            }
            with self.assertRaisesRegex(ValueError, "missing visible characters"):
                validate_start_anchor_semantics(
                    contract, unit_id="U2",
                    first_reference={"path": str(image), "sha256": image_sha},
                    first_prompt_spec={"cast": [{"character": "白鲤", "face_visibility": "VISIBLE_PER_FRAME_CONTENT"}]},
                    camera_plan={"start_framing": "白鲤与帘口同框"},
                    required_space_anchors=["帘口"], root=root,
                )


if __name__ == "__main__":
    unittest.main()
