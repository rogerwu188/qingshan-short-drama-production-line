import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIDEO_SUBMISSION_ENTRYPOINTS = (
    "tools/episode_parallel_batch_supervisor.py",
    "tools/submit_giggle_task_manifest.py",
    "tools/submit_giggle_video_manifest_v2.py",
)
IMAGE_SUBMISSION_ENTRYPOINTS = (
    "tools/episode_parallel_batch_supervisor.py",
    "tools/submit_giggle_task_manifest.py",
    "tools/submit_giggle_image_manifest.py",
)


def called_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


class VideoSubmissionEntrypointContractCoverageTest(unittest.TestCase):
    def test_every_video_submission_entrypoint_calls_action_contract(self):
        missing = [
            relative for relative in VIDEO_SUBMISSION_ENTRYPOINTS
            if "validate_action_contract" not in called_functions(ROOT / relative)
        ]
        self.assertEqual([], missing, f"video submit paths bypass action contract: {missing}")

    def test_every_video_submission_entrypoint_calls_model_adapter_gate(self):
        missing = [
            relative for relative in VIDEO_SUBMISSION_ENTRYPOINTS
            if "require_paid_model_contract" not in called_functions(ROOT / relative)
        ]
        self.assertEqual([], missing, f"video submit paths bypass model adapter gate: {missing}")

    def test_entrypoint_inventory_exists_and_is_python(self):
        for relative in VIDEO_SUBMISSION_ENTRYPOINTS + IMAGE_SUBMISSION_ENTRYPOINTS:
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_every_image_submission_entrypoint_calls_model_adapter_gate(self):
        missing = [
            relative for relative in IMAGE_SUBMISSION_ENTRYPOINTS
            if "require_paid_image_model_contract" not in called_functions(ROOT / relative)
        ]
        self.assertEqual([], missing, f"image submit paths bypass model adapter gate: {missing}")


if __name__ == "__main__":
    unittest.main()
