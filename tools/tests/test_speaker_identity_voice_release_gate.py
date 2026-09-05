import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.speaker_identity_voice_release_gate import evaluate


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SpeakerIdentityVoiceReleaseGateTest(unittest.TestCase):
    def payload(self, root: Path):
        frame = root / "speaking.png"
        face = root / "face.png"
        frame.write_bytes(b"frame")
        face.write_bytes(b"face")
        final = root / "final.mp4"
        final.write_bytes(b"final-fixture")
        return {
            "episode": "E99",
            "final": str(final),
            "final_sha256": sha(final),
            "required_dialogue_ids": ["D1"],
            "dialogue_evidence": [{
                "dia_id": "D1",
                "entity_id": "chenji",
                "visible_speaker_verification": "PASS",
                "canonical_face_verification": "PASS",
                "canonical_voice_verification": "PASS",
                "speaker_diarization_verification": "PASS",
                "visible_lip_owner_verification": "PASS",
                "canonical_voice_similarity_verification": "PASS",
                "machine_verifier": "test-machine-verifier",
                "confidence": 0.95,
                "voice_similarity_confidence": 0.91,
                "lip_owner_confidence": 0.93,
                "speaking_frame": str(frame),
                "speaking_frame_sha256": sha(frame),
                "canonical_face_reference": str(face),
                "canonical_face_reference_sha256": sha(face),
                "canonical_voice_asset_id": "voice-chenji",
            }],
        }, face

    def test_requires_diarization_lip_owner_and_voice_similarity(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload, face = self.payload(Path(tmp))
            with patch(
                "tools.speaker_identity_voice_release_gate._character_authority",
                return_value={"chenji": {"identity_reference_image": str(face)}},
            ), patch(
                "tools.speaker_identity_voice_release_gate._voice_authority",
                return_value={"chenji": {"remote_asset_id": "voice-chenji"}},
            ):
                self.assertEqual(evaluate(payload)["status"], "PASS")
                del payload["dialogue_evidence"][0]["visible_lip_owner_verification"]
                report = evaluate(payload)
                self.assertEqual(report["status"], "FAIL")
                self.assertIn("visible_lip_owner_not_pass:D1", report["failures"])


if __name__ == "__main__":
    unittest.main()
