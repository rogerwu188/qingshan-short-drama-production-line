import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


class ImageSubmissionEntrypointContractCoverageTests(unittest.TestCase):
    def test_every_active_e40_image_entrypoint_uses_shared_paid_model_contract(self):
        required = {
            "tools/submit_giggle_image_manifest.py": (
                "require_paid_image_model_contract",
                "prompt_text=prompt",
            ),
            "tools/episode_parallel_batch_supervisor.py": (
                "require_paid_image_model_contract",
                "prompt_text=prompt",
            ),
        }
        for relative, tokens in required.items():
            with self.subTest(entrypoint=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                for token in tokens:
                    self.assertIn(token, source)

    def test_low_level_paid_generation_requires_durable_submitter_context(self):
        source = (ROOT / "tools/giggle_api_client.py").read_text(encoding="utf-8")
        self.assertIn("QINGSHAN_DURABLE_SUBMITTER_CONTEXT", source)
        self.assertIn("durable transaction context is required", source)


if __name__ == "__main__":
    unittest.main()
