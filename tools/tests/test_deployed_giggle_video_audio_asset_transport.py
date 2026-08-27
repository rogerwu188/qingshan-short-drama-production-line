import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEPLOYED = Path.home() / ".local/share/backlotos/share/pipeline-tools/exact_first_frame_transport.py"


def load_transport():
    spec = importlib.util.spec_from_file_location("deployed_exact_first_frame_transport", DEPLOYED)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load deployed transport: {DEPLOYED}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeployedGiggleVideoAudioAssetTransportTests(unittest.TestCase):
    def test_provider_asset_ids_are_preferred_over_public_urls(self):
        module = load_transport()
        task = {
            "task_key": "E40-TRANSPORT-REGRESSION",
            "model": "seedance-2.0-pro",
            "duration_seconds": 4,
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "reference_images": ["frame.png"],
            "reference_roles": ["CONTINUITY_REFERENCE"],
            "exact_dialogue_audio_asset_ids": ["provider-audio-id"],
            "exact_dialogue_audio_urls": ["https://assets.giggle.pro/public/dialogue.wav"],
        }

        endpoint, payload = module.build_provider_request(
            task,
            prompt_text="画外对白，无可见口型。",
            root=ROOT,
            encode_image=lambda path: {"base64": path},
        )

        self.assertEqual(endpoint, "/api/v1/generation/omni-video")
        self.assertEqual(payload["audios"], [{"asset_id": "provider-audio-id"}])

    def test_public_url_remains_fallback_without_asset_id(self):
        module = load_transport()
        task = {
            "task_key": "E40-TRANSPORT-URL-FALLBACK",
            "model": "seedance-2.0-pro",
            "duration_seconds": 4,
            "aspect_ratio": "9:16",
            "resolution": "720p",
            "reference_images": ["frame.png"],
            "reference_roles": ["CONTINUITY_REFERENCE"],
            "exact_dialogue_audio_urls": ["https://assets.giggle.pro/public/dialogue.wav"],
        }

        _, payload = module.build_provider_request(
            task,
            prompt_text="画外对白，无可见口型。",
            root=ROOT,
            encode_image=lambda path: {"base64": path},
        )

        self.assertEqual(
            payload["audios"],
            [{"url": "https://assets.giggle.pro/public/dialogue.wav"}],
        )


if __name__ == "__main__":
    unittest.main()
