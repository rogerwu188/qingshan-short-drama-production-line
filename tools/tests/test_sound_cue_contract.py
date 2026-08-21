import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.sound_cue_contract import evaluate


def base_project(root: Path) -> dict:
    return {
        "metadata": {
            "audio_profile_id": "LAYERED_POST_WITH_BGM",
            "audio_profile_contract": "configs/audio_postproduction_profiles_v1_20260821.json",
            "source_audio_policy": "NO_NATIVE_DIALOGUE_WITH_EVIDENCE",
            "native_dialogue_absence_evidence": {"status": "PASS", "report": "qa/no_native_dialogue.json"},
            "bgm_contract": {"source_type": "LIBRARY_FALLBACK"},
            "sound_design_contract": {
                "mode": "LAYERED_CUES",
                "required_layers": ["AMBIENCE", "FOLEY", "SFX"],
                "external_bgm_allowed": True,
                "cues": [],
            },
        },
        "output": {"audioSampleRate": 48000},
        "masterAudioPolicy": {"sampleRateHz": 48000},
        "timeline": {"audioTracks": [{"id": "Audio.BGM", "clips": []}]},
    }


class SoundCueContractTests(unittest.TestCase):
    def test_layered_cues_require_source_sha_rights_space_and_cause(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "cue.wav"
            source.write_bytes(b"sound")
            project = base_project(root)
            project["metadata"]["sound_design_contract"]["cues"] = [
                {
                    "cue_id": f"CUE-{layer}",
                    "layer": layer,
                    "source": str(source),
                    "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    "rights_evidence": "RIGHTS-1",
                    "timeline_start": index,
                    "duration": 1.0,
                    "gain_db": -6.0,
                    "scene_id": "SC-1",
                    "room_id": "ROOM-1",
                    "visual_cause": "A visible event produces the sound.",
                }
                for index, layer in enumerate(("AMBIENCE", "FOLEY", "SFX"))
            ]
            self.assertEqual(evaluate(project, root=root)["status"], "PASS")

    def test_missing_cause_and_bad_sha_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "cue.wav"
            source.write_bytes(b"sound")
            project = base_project(root)
            project["metadata"]["sound_design_contract"]["required_layers"] = ["SFX"]
            project["metadata"]["sound_design_contract"]["cues"] = [{
                "cue_id": "CUE-1",
                "layer": "SFX",
                "source": str(source),
                "source_sha256": "0" * 64,
                "rights_evidence": "RIGHTS-1",
                "timeline_start": 0.0,
                "duration": 1.0,
                "gain_db": -6.0,
                "scene_id": "SC-1",
                "room_id": "ROOM-1",
            }]
            failures = evaluate(project, root=root)["failures"]
            self.assertIn("SOUND_CUE_CAUSE_MISSING:CUE-1", failures)
            self.assertIn("SOUND_CUE_SOURCE_SHA_MISMATCH:CUE-1", failures)

    def test_required_layer_can_only_be_omitted_with_reason(self):
        with tempfile.TemporaryDirectory() as td:
            project = base_project(Path(td))
            project["metadata"]["sound_design_contract"]["required_layers"] = ["FOLEY"]
            report = evaluate(project, root=Path(td))
            self.assertIn("SOUND_REQUIRED_LAYER_UNCOVERED:FOLEY", report["failures"])


if __name__ == "__main__":
    unittest.main()
