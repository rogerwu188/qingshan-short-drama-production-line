import unittest

from tools.image_model_adapter import (
    FLAT_IDENTITY_MODE,
    compile_labeled_flat_identity_transport,
    validate_identity_reference_transport,
    validate_image_model_contract,
)
from tools.video_model_adapter import validate_model_contract


def video_task(model, episode="E40", resolution="720p"):
    return {
        "episode": episode, "model": model, "prompt_file": "prompt.txt",
        "duration_seconds": 10, "aspect_ratio": "9:16", "resolution": resolution,
        "blocking": {"characters": [{"character_id": "A"}]},
        "action_end_blocking": {"characters": [{"character_id": "A"}]},
        "trajectory_overlays": [{"entity_id": "A"}],
        "space_chain_id": "EGSM->GSM->SUBSPACE",
    }


def image_task(model):
    return {
        "episode": "E40", "model": model, "prompt_file": "prompt.txt",
        "aspect_ratio": "9:16", "resolution": "1K",
        "reference_bindings": [{"entity_id": "A", "role": "character", "path": "a.png"}],
        "reference_images": ["a.png"],
        "reference_image_sequence": [{"entity_id": "A", "role": "character", "path": "a.png"}],
        "space_chain_id": "EGSM->GSM->SUBSPACE",
        "canonical_characters": ["A"],
        "generation_stage": "IDENTITY_PLATE",
        "identity_reference_transport": {
            "schema": "qingshan.identity_reference_transport.v1",
            "mode": "IDENTITY_ONLY_PLATE",
        },
    }


class MediaModelAdapterTests(unittest.TestCase):
    def test_current_video_model_is_deployed_and_paid_authorized(self):
        self.assertEqual(validate_model_contract(video_task("seedance-2.0-pro"), mode="PAID_SUBMIT")["status"], "PASS")

    def test_sd2_and_h3_are_both_paid_authorized_after_e45(self):
        e44 = validate_model_contract(
            video_task("seedance-2.0-pro", episode="E44", resolution="720p"),
            episode="E44", mode="PAID_SUBMIT",
        )
        e45 = validate_model_contract(
            video_task("MiniMax-H3", episode="E45", resolution="768p"),
            episode="E45", mode="PAID_SUBMIT",
        )
        self.assertEqual(e44["status"], "PASS", e44)
        self.assertEqual(e45["status"], "PASS", e45)
        self.assertEqual(
            validate_model_contract(
                video_task("seedance-2.0-pro", episode="E45", resolution="720p"),
                episode="E45", mode="PAID_SUBMIT",
            )["status"],
            "PASS",
        )
        self.assertEqual(
            validate_model_contract(
                video_task("MiniMax-H3", episode="E45", resolution="1080p"),
                episode="E45", mode="PAID_SUBMIT",
            )["status"],
            "FAIL",
        )

    def test_future_video_families_have_contract_but_no_paid_bypass(self):
        for model in ("sora2", "kling", "wan2.7"):
            with self.subTest(model=model):
                self.assertEqual(
                    validate_model_contract(video_task(model))["status"],
                    "PASS_PORTABLE_CONTRACT_PROVIDER_CONFIG_REQUIRED",
                )
                self.assertEqual(validate_model_contract(video_task(model), mode="PAID_SUBMIT")["status"], "FAIL")

    def test_current_image_model_is_deployed_and_paid_authorized(self):
        self.assertEqual(validate_image_model_contract(image_task("gpt-image-2-pro"), mode="PAID_SUBMIT")["status"], "PASS")

    def test_visible_character_cannot_silently_use_flat_reference_list(self):
        task = image_task("gpt-image-2-pro")
        task.pop("identity_reference_transport")
        report = validate_image_model_contract(task, mode="PAID_SUBMIT")
        self.assertEqual(report["status"], "FAIL")
        self.assertIn(
            "IDENTITY_REFERENCE_TRANSPORT_NOT_DECLARED",
            report["identity_reference_transport"]["failures"],
        )

    def test_current_provider_cannot_claim_native_identity_lock(self):
        task = image_task("gpt-image-2-pro")
        task["identity_reference_transport"] = {
            "schema": "qingshan.identity_reference_transport.v1",
            "mode": "PROVIDER_NATIVE_IDENTITY_LOCK",
        }
        report = validate_image_model_contract(task, mode="PAID_SUBMIT")
        self.assertIn(
            "PROVIDER_NATIVE_IDENTITY_LOCK_NOT_IMPLEMENTED",
            report["identity_reference_transport"]["failures"],
        )

    def test_labeled_flat_mode_requires_exact_output_gate_and_prompt_block(self):
        task = image_task("gpt-image-2-pro")
        task["generation_stage"] = "SCENE_KEYFRAME"
        task["reference_image_sequence"] = [{
            "entity_id": "A", "role": "character", "path": "a.png",
            "asset_label": "@图片1", "identity_authority": "PRIMARY_NATIVE_REGISTRY",
        }]
        task["identity_reference_transport"] = {
            "schema": "qingshan.identity_reference_transport.v1",
            "mode": FLAT_IDENTITY_MODE,
            "transport_guarantee": "SOFT_REFERENCE_REQUIRES_EXACT_OUTPUT_GATE",
            "output_identity_verification_method": "INSIGHTFACE_COSINE_V1",
            "exact_output_sha_required": True,
            "authority_map": {"A": "@图片1"},
            "authority_prompt_token": "IDENTITY-AUTHORITY-A",
        }
        missing = validate_image_model_contract(task, mode="PAID_SUBMIT", prompt_text="no block")
        self.assertIn(
            "IDENTITY_AUTHORITY_PROMPT_BLOCK_NOT_TRANSMITTED",
            missing["identity_reference_transport"]["failures"],
        )
        passed = validate_image_model_contract(
            task, mode="PAID_SUBMIT", prompt_text="IDENTITY-AUTHORITY-A"
        )
        self.assertEqual(passed["status"], "PASS", passed["failures"])

    def test_compiler_emits_identity_authority_map_without_claiming_hard_lock(self):
        sequence, contract, prompt = compile_labeled_flat_identity_transport(
            "E40-U01",
            [
                {"role": "character", "entity_id": "CHAR-A", "path": "a.png", "sha256": "a" * 64},
                {"role": "scene", "entity_id": "SCENE-A", "path": "s.png", "sha256": "b" * 64},
            ],
            "正文",
        )
        self.assertEqual(sequence[0]["identity_authority"], "PRIMARY_NATIVE_REGISTRY")
        self.assertEqual(contract["authority_map"], {"CHAR-A": "@图片1"})
        self.assertEqual(contract["transport_guarantee"], "SOFT_REFERENCE_REQUIRES_EXACT_OUTPUT_GATE")
        self.assertIn(contract["authority_prompt_token"], prompt)
        self.assertIn("不得定义或改变任何人物脸", prompt)

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
