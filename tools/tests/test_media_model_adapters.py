import unittest

from tools.image_model_adapter import validate_image_model_contract
from tools.video_model_adapter import validate_model_contract


def video_task(model):
    return {
        "episode": "E40", "model": model, "prompt_file": "prompt.txt",
        "duration_seconds": 10, "aspect_ratio": "9:16", "resolution": "720p",
        "blocking": {"characters": [{"character_id": "A"}]},
        "action_end_blocking": {"characters": [{"character_id": "A"}]},
        "trajectory_overlays": [{"entity_id": "A"}],
        "space_chain_id": "EGSM->GSM->SUBSPACE",
    }


def image_task(model):
    return {
        "episode": "E40", "model": model, "prompt_file": "prompt.txt",
        "aspect_ratio": "9:16", "resolution": "1K",
        "reference_bindings": [{"entity_id": "A", "role": "character"}],
        "space_chain_id": "EGSM->GSM->SUBSPACE",
        "canonical_characters": ["A"],
    }


class MediaModelAdapterTests(unittest.TestCase):
    def test_current_video_model_is_deployed_and_paid_authorized(self):
        self.assertEqual(validate_model_contract(video_task("seedance-2.0-fast"), mode="PAID_SUBMIT")["status"], "PASS")

    def test_future_video_families_have_contract_but_no_paid_bypass(self):
        for model in ("sora2", "kling", "h3", "wan2.7"):
            with self.subTest(model=model):
                self.assertEqual(
                    validate_model_contract(video_task(model))["status"],
                    "PASS_PORTABLE_CONTRACT_PROVIDER_CONFIG_REQUIRED",
                )
                self.assertEqual(validate_model_contract(video_task(model), mode="PAID_SUBMIT")["status"], "FAIL")

    def test_current_image_model_is_deployed_and_paid_authorized(self):
        self.assertEqual(validate_image_model_contract(image_task("gpt-image-2-pro"), mode="PAID_SUBMIT")["status"], "PASS")

    def test_future_image_families_and_nano_banana_have_contract_only(self):
        for model in ("sd2", "seed", "nanubanner", "nano-banana"):
            with self.subTest(model=model):
                self.assertEqual(
                    validate_image_model_contract(image_task(model))["status"],
                    "PASS_PORTABLE_CONTRACT_PROVIDER_CONFIG_REQUIRED",
                )
                self.assertEqual(validate_image_model_contract(image_task(model), mode="PAID_SUBMIT")["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
