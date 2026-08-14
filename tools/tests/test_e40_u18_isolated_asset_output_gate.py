import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from tools.e40_u18_isolated_asset_output_gate import validate_asset


class IsolatedAssetOutputGateTest(unittest.TestCase):
    def test_valid_transparent_arrow_passes_machine_geometry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "arrow.png"
            image = Image.new("RGBA", (1024, 320), (0, 0, 0, 0))
            ImageDraw.Draw(image).rectangle((180, 140, 850, 180), fill=(120, 80, 40, 255))
            image.save(path)
            import hashlib
            asset = {
                "asset_id": "E40-U18-ISO-LOW-AXIS-ARROW-V1",
                "output_path": "arrow.png",
                "output_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "output_mask_path": None,
                "output_mask_sha256": None,
                "provenance": "local test fixture",
                "license_or_local_authorship": "locally authored test fixture",
            }
            self.assertEqual(validate_asset(asset, root), [])

    def test_small_arrow_fails_readability(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "arrow.png"
            image = Image.new("RGBA", (1024, 320), (0, 0, 0, 0))
            ImageDraw.Draw(image).rectangle((800, 150, 900, 165), fill=(120, 80, 40, 255))
            image.save(path)
            import hashlib
            asset = {
                "asset_id": "E40-U18-ISO-LOW-AXIS-ARROW-V1",
                "output_path": "arrow.png",
                "output_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "output_mask_path": None,
                "output_mask_sha256": None,
                "provenance": "local test fixture",
                "license_or_local_authorship": "locally authored test fixture",
            }
            self.assertIn("E40-U18-ISO-LOW-AXIS-ARROW-V1:ARROW_NOT_DELIVERY_READABLE", validate_asset(asset, root))


if __name__ == "__main__":
    unittest.main()
