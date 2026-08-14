import argparse
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.giggle_api_client import generate_omni_video


class OmniImageAssetIdTest(unittest.TestCase):
    @patch("tools.giggle_api_client._request")
    def test_asset_ids_are_sent_without_base64_images(self, request):
        request.return_value = {"code": 200}
        args = argparse.Namespace(
            prompt="test",
            prompt_file=None,
            model="seedance-2.0-pro",
            duration=8,
            aspect_ratio="9:16",
            resolution="720p",
            count=1,
            reference_image=None,
            image_asset_id=["img-a", "img-b"],
            audio=None,
            audio_asset_id=None,
            video=None,
            video_asset_id=None,
        )

        generate_omni_video(args)

        payload = request.call_args.args[1]
        self.assertEqual(payload["images"], [{"asset_id": "img-a"}, {"asset_id": "img-b"}])


if __name__ == "__main__":
    unittest.main()
