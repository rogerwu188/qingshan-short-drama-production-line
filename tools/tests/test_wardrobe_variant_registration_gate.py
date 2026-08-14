import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.asset_binding_validator import build_errors


ROOT = Path(__file__).resolve().parents[2]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WardrobeVariantRegistrationGateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.identity = root / "identity.png"
        self.identity.write_bytes(b"identity-parent")
        self.wardrobe = root / "wardrobe.png"
        self.wardrobe.write_bytes(b"wardrobe-variant")
        self.registry_path = root / "registry.json"
        self.registry = {
            "assets": {
                "characters": {
                    "CHAR-A": {
                        "status": "LOCKED_RETURNING",
                        "identity_reference_image": str(self.identity),
                        "reference_image": str(self.identity),
                        "identity_lock": {"face": "locked"},
                        "wardrobe_variants": {
                            "white_v1": {
                                "reference_image": str(self.wardrobe),
                                "reference_sha256": _sha256(self.wardrobe),
                                "allowed_context": "test",
                                "identity_verification": "PASS",
                                "verification_status": "PASS",
                            }
                        },
                        "variants": {
                            "white_v1": {
                                "reference_image": str(self.wardrobe),
                                "allowed_context": "test",
                                "verification_status": "PASS",
                            }
                        },
                    }
                }
            }
        }
        self.registry_path.write_text(json.dumps(self.registry), encoding="utf-8")
        self.config = {
            "episode": "E40",
            "character_state": {
                "CHAR-A": {
                    "wardrobe_variant_id": "white_v1",
                    "wardrobe_reference_image": str(self.wardrobe),
                }
            },
            "shots": [],
        }
        self.manifest = {
            "episode": "E40",
            "historical_asset_inheritance_required": True,
            "series_character_registry": str(self.registry_path),
            "characters": {
                "CHAR-A": {
                    "history_status": "RETURNING",
                    "identity_reference_image": str(self.identity),
                    "reference_image": str(self.wardrobe),
                    "wardrobe_variant_id": "white_v1",
                    "wardrobe_variant_required": True,
                    "level": "B",
                }
            },
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_registered_identity_verified_exact_sha_variant_passes(self):
        self.assertEqual(build_errors(self.config, self.manifest), [])

    def test_required_but_missing_variant_id_fails_closed(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["characters"]["CHAR-A"].pop("wardrobe_variant_id")
        errors = build_errors(self.config, manifest)
        self.assertTrue(any("requires registered wardrobe variant" in row for row in errors))

    def test_unregistered_variant_id_fails_closed(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["characters"]["CHAR-A"]["wardrobe_variant_id"] = "not_registered"
        errors = build_errors(self.config, manifest)
        self.assertTrue(any("wardrobe variant is not registered" in row for row in errors))

    def test_identity_qa_not_pass_fails_closed(self):
        registry = copy.deepcopy(self.registry)
        registry["assets"]["characters"]["CHAR-A"]["wardrobe_variants"]["white_v1"][
            "identity_verification"
        ] = "PENDING"
        self.registry_path.write_text(json.dumps(registry), encoding="utf-8")
        errors = build_errors(self.config, self.manifest)
        self.assertTrue(any("lacks same-face/same-body PASS" in row for row in errors))

    def test_state_bible_and_production_binding_must_match(self):
        config = copy.deepcopy(self.config)
        config["character_state"]["CHAR-A"]["wardrobe_variant_id"] = "other_variant"
        errors = build_errors(config, self.manifest)
        self.assertTrue(any("State Bible wardrobe variant does not match" in row for row in errors))

    def test_e40_promoted_asset_registry_manifest_and_state_bible_are_consistent(self):
        promoted = ROOT / "assets/reference/e40_wardrobe_variants_20260808/characters/CHAR-chenji-age20-plain-white-fine-linen-turnaround-v1-20260808.png"
        working = ROOT / "working_assets/e40_preproduction_20260808/character_assets_wardrobe_correction/CHAR-chenji-E40-white-robe-turnaround-v1.png"
        asset_manifest = json.loads(
            (ROOT / "assets/reference/e40_wardrobe_variants_20260808/manifest.json").read_text(
                encoding="utf-8"
            )
        )
        registry = json.loads(
            (ROOT / "configs/series_continuity_asset_registry_20260712.json").read_text(
                encoding="utf-8"
            )
        )
        state_bible = json.loads(
            (ROOT / "configs/e40_state_bible_20260808.json").read_text(encoding="utf-8")
        )
        variant_id = "age20_plain_white_fine_linen_e40_v1"
        variant = registry["assets"]["characters"]["CHAR-陈迹-古装"]["wardrobe_variants"][
            variant_id
        ]
        mirrored = registry["assets"]["characters"]["CHAR-陈迹-古装"]["variants"][variant_id]
        manifest_asset = asset_manifest["assets"][0]

        self.assertEqual(_sha256(promoted), manifest_asset["promoted_asset"]["sha256"])
        self.assertEqual(_sha256(working), _sha256(promoted))
        self.assertEqual(variant["reference_sha256"], _sha256(promoted))
        self.assertEqual(mirrored["reference_image"], str(promoted))
        self.assertEqual(manifest_asset["wardrobe_variant_id"], variant_id)
        self.assertEqual(
            state_bible["character_state"]["CHAR-陈迹-古装"]["wardrobe_variant_id"],
            variant_id,
        )
        parent = Path(manifest_asset["identity_parent"]["path"])
        self.assertEqual(_sha256(parent), manifest_asset["identity_parent"]["sha256"])


if __name__ == "__main__":
    unittest.main()
