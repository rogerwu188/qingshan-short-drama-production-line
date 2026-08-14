import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.submit_giggle_task_manifest import (
    resolve_picture_only_repair_gate,
    resolve_reference_images,
    resolve_submission_gate,
)


class PictureOnlyRepairGateTests(unittest.TestCase):
    def write_json(self, root: Path, name: str, payload: dict) -> tuple[str, str]:
        path = root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return name, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_passes_bound_picture_only_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prompt = root / "repair.txt"
            prompt.write_text(
                "VISUAL_PROMPT_NO_DIALOGUE_TEXT:\naction\n"
                "AUDIO_PROMPT_DIALOGUE_ONLY:\n[]\n",
                encoding="utf-8",
            )
            disposition, disposition_sha = self.write_json(
                root, "disposition.json", {"authorization_ref": "AUTH"}
            )
            preflight, preflight_sha = self.write_json(
                root,
                "preflight.json",
                {
                    "authorization_ref": "AUTH",
                    "status": "PASS_LOCAL",
                    "prompts": [{"source_id": "SRC"}],
                },
            )
            guard, guard_sha = self.write_json(
                root,
                "guard.json",
                {
                    "status": "PASS",
                    "failure_count": 0,
                    "results": [{"prompt_file": str(prompt)}],
                },
            )
            manifest = {
                "authorization_ref": "AUTH",
                "repair_gate": {
                    "gate_type": "picture_only_repair",
                    "authorization_ref": "AUTH",
                    "source_disposition": {"path": disposition, "sha256": disposition_sha},
                    "prompt_preflight": {"path": preflight, "sha256": preflight_sha},
                    "visual_text_guard": {"path": guard, "sha256": guard_sha},
                },
                "tasks": [
                    {
                        "source_id": "SRC",
                        "status": "READY_TO_SUBMIT",
                        "prompt_path": "repair.txt",
                        "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
                    }
                ],
            }
            with patch("tools.submit_giggle_task_manifest.BASE", root):
                result = resolve_picture_only_repair_gate(manifest)
            self.assertEqual(result["status"], "PASS")

    def test_rejects_nonempty_audio_and_stale_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            prompt = root / "repair.txt"
            prompt.write_text(
                "VISUAL_PROMPT_NO_DIALOGUE_TEXT:\naction\n"
                "AUDIO_PROMPT_DIALOGUE_ONLY:\n[dialogue]\n",
                encoding="utf-8",
            )
            evidence = {}
            for name, payload in {
                "source_disposition": {"authorization_ref": "AUTH"},
                "prompt_preflight": {
                    "authorization_ref": "AUTH",
                    "status": "PASS",
                    "prompts": [{"source_id": "SRC"}],
                },
                "visual_text_guard": {
                    "status": "PASS",
                    "failure_count": 0,
                    "results": [{"prompt_file": str(prompt)}],
                },
            }.items():
                path, digest = self.write_json(root, f"{name}.json", payload)
                evidence[name] = {"path": path, "sha256": digest}
            manifest = {
                "authorization_ref": "AUTH",
                "repair_gate": {
                    "gate_type": "picture_only_repair",
                    "authorization_ref": "AUTH",
                    **evidence,
                },
                "tasks": [
                    {
                        "source_id": "SRC",
                        "status": "READY_TO_SUBMIT",
                        "prompt_path": "repair.txt",
                        "prompt_sha256": "stale",
                    }
                ],
            }
            with patch("tools.submit_giggle_task_manifest.BASE", root):
                result = resolve_picture_only_repair_gate(manifest)
            self.assertEqual(result["status"], "FAIL")
            self.assertIn("repair_task_audio_not_empty:SRC", result["failures"])
            self.assertIn("repair_task_prompt_sha256_mismatch:SRC", result["failures"])

    def test_explicit_empty_reference_list_is_preserved(self):
        self.assertEqual(resolve_reference_images({"reference_images": []}), [])

    def test_e28_repair_cannot_bypass_local_claude_script_gate(self):
        manifest = {
            "episode": "E28",
            "authorization_ref": "AUTH",
            "repair_gate": {
                "gate_type": "picture_only_repair",
                "authorization_ref": "AUTH",
            },
            "tasks": [{"source_id": "SRC", "status": "READY_TO_SUBMIT"}],
        }
        with patch(
            "tools.submit_giggle_task_manifest.resolve_picture_only_repair_gate",
            return_value={"status": "PASS", "failures": []},
        ):
            result = resolve_submission_gate(manifest, None, None)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["supervisor"]["status"], "FAIL")
        self.assertFalse(result["supervisor"]["generation_allowed"])

    def test_legacy_reference_fields_remain_supported(self):
        task = {"visual_lock": "visual.png", "speaker_reference": "speaker.png"}
        self.assertEqual(resolve_reference_images(task), ["visual.png", "speaker.png"])


if __name__ == "__main__":
    unittest.main()
