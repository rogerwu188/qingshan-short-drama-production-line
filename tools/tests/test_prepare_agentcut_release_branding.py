import tempfile
import unittest
from pathlib import Path

from tools.prepare_agentcut_release_branding import build


class PrepareAgentcutReleaseBrandingTests(unittest.TestCase):
    def test_builds_exact_ordered_subtitles_and_outro(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            logo, chime, font = root / "logo", root / "chime", root / "font"
            for path in (logo, chime, font):
                path.write_bytes(b"x")
            project = {
                "metadata": {"episode": "E37"},
                "output": {},
                "timeline": {
                    "videoTracks": [
                        {
                            "clips": [
                                {
                                    "id": "U1",
                                    "start": 0,
                                    "duration": 6,
                                    "metadata": {"canonical_lines": [1, 2]},
                                },
                                {
                                    "id": "U2",
                                    "start": 6,
                                    "duration": 4,
                                    "metadata": {"canonical_lines": [3]},
                                },
                            ]
                        }
                    ]
                },
            }
            contract = {
                "schema": "dialogue.v1",
                "episode": "E37",
                "dialogue": [
                    {"line_id": 1, "speaker": "A", "spoken_text": "第一句"},
                    {"line_id": 2, "speaker": "A", "spoken_text": "第二句更长"},
                    {"line_id": 3, "speaker": "B", "spoken_text": "第三句"},
                ],
            }
            result = build(
                project,
                contract,
                output_media=root / "out.mp4",
                logo=logo,
                chime=chime,
                font=font,
            )
        self.assertEqual(result["expectedDialogueIds"], ["E37-L001", "E37-L002", "E37-L003"])
        self.assertEqual(result["metadata"]["subtitle_contract"]["coverage"], "3/3")
        self.assertTrue(result["requireBurnedSubtitles"])
        self.assertTrue(result["requireBrandedOutro"])
        self.assertEqual(result["outro"]["brand"], "nalu_motion")
        self.assertTrue(result["releaseGate"]["required"])

    def test_missing_canonical_line_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            assets = [root / name for name in ("logo", "chime", "font")]
            for path in assets:
                path.write_bytes(b"x")
            project = {
                "timeline": {
                    "videoTracks": [
                        {"clips": [{"start": 0, "duration": 4, "metadata": {"canonical_lines": [2]}}]}
                    ]
                }
            }
            contract = {"episode": "E37", "dialogue": [{"line_id": 1, "spoken_text": "甲"}]}
            with self.assertRaises(ValueError):
                build(
                    project,
                    contract,
                    output_media=root / "out.mp4",
                    logo=assets[0],
                    chime=assets[1],
                    font=assets[2],
                )


if __name__ == "__main__":
    unittest.main()
