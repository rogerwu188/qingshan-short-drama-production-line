import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.release_branding_contract_gate import evaluate


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReleaseBrandingContractGateTests(unittest.TestCase):
    def _project(self, root: Path) -> dict:
        logo = root / "logo.png"
        chime = root / "chime.wav"
        logo.write_bytes(b"logo")
        chime.write_bytes(b"chime")
        return {
            "requireBurnedSubtitles": True,
            "requireBrandedOutro": True,
            "expectedDialogueIds": ["D1", "D2"],
            "metadata": {
                "episode": "E37",
                "subtitle_contract": {"coverage": "2/2", "burned_in": True},
            },
            "timeline": {
                "subtitleTracks": [
                    {
                        "enabled": True,
                        "clips": [
                            {"dialogue_id": "D1", "text": "甲"},
                            {"dialogue_id": "D2", "text": "乙"},
                        ],
                    }
                ]
            },
            "outro": {
                "enabled": True,
                "brand": "nalu_motion",
                "duration": 3,
                "includeInTotalDuration": True,
                "assetPath": str(logo),
                "audioPath": str(chime),
            },
            "releaseGate": {"required": True},
        }

    def test_complete_project_and_render_pass(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            final = root / "final.mp4"
            final.write_bytes(b"final")
            project = self._project(root)
            render = {
                "coverage": {"subtitles": {"required": True, "count": "2/2"}},
                "outro": {
                    "present": True,
                    "brand": "nalu_motion",
                    "endsAtTimelineEnd": True,
                },
                "releaseGate": {"finalSha256": digest(final)},
            }
            result = evaluate(project, root=root, render_manifest=render, final_video=final)
        self.assertEqual(result["status"], "PASS")

    def test_missing_subtitles_and_outro_fail(self):
        result = evaluate(
            {
                "metadata": {"episode": "E37"},
                "timeline": {"subtitleTracks": []},
                "releaseGate": {"required": False},
            }
        )
        self.assertIn("burned_subtitles_not_required", result["failures"])
        self.assertIn("outro_not_enabled", result["failures"])
        self.assertIn("agentcut_release_gate_not_required", result["failures"])

    def test_declared_but_wrong_caption_order_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._project(root)
            project["timeline"]["subtitleTracks"][0]["clips"].reverse()
            result = evaluate(project, root=root)
        self.assertIn("subtitle_order_or_coverage_mismatch", result["failures"])


if __name__ == "__main__":
    unittest.main()
