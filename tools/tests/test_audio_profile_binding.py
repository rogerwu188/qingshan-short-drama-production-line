import copy
import json
import tempfile
import unittest
from pathlib import Path

from tools.audio_profile_binding import (
    apply_audio_profile_binding,
    classify_bgm_declaration,
    compile_audio_profile_binding,
    validate_audio_profile_binding,
)


class AudioProfileBindingTests(unittest.TestCase):
    def test_legacy_no_bgm_declarations_bind_no_external_profile(self):
        for declaration in ("NONE_WHOLE_EPISODE", "NONE_THIS_EPISODE", "NONE_BY_DESIGN"):
            binding = compile_audio_profile_binding({
                "episode": "E99", "audio_contract": {"bgm": declaration}
            })
            self.assertEqual(binding["creative_bgm_mode"], "FORBIDDEN")
            self.assertEqual(binding["resolved_audio_profile_id"], "NATIVE_MULTIMODAL_NO_EXTERNAL_BGM")

    def test_selective_legacy_declarations_bind_selective_profile(self):
        declarations = (
            "DREAM_SCENES_ONLY_S08_S10_S11",
            "LAST_SCENE_ONLY_LOW_SUSTAIN",
            "只在 S11 最后一次进入，其余全片不加。",
            {"used": True, "windows": ["S07-S08"], "basis": "唯一一次"},
        )
        for declaration in declarations:
            binding = compile_audio_profile_binding({
                "episode": "E99", "audio_contract": {"bgm": declaration}
            })
            self.assertEqual(binding["creative_bgm_mode"], "SELECTIVE")
            self.assertEqual(binding["resolved_audio_profile_id"], "NATIVE_MULTIMODAL_SELECTIVE_BGM")

    def test_required_declaration_binds_layered_profile(self):
        binding = compile_audio_profile_binding({
            "episode": "E99", "audio_contract": {"bgm": "REQUIRED_WHOLE_EPISODE"}
        })
        self.assertEqual(binding["resolved_audio_profile_id"], "LAYERED_POST_WITH_BGM")

    def test_ambiguous_declaration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            classify_bgm_declaration("看情况配一点音乐")

    def test_binding_is_sha_bound_and_detects_manual_profile_override(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "contract.json"
            contract = {"episode": "E99", "audio_contract": {"bgm": "NONE_WHOLE_EPISODE"}}
            path.write_text(json.dumps(contract, ensure_ascii=False))
            project = {"metadata": {"episode": "E99", "sound_design_contract": {}}}
            apply_audio_profile_binding(project, contract, contract_path=path)
            self.assertEqual(validate_audio_profile_binding(project), [])
            overridden = copy.deepcopy(project)
            overridden["metadata"]["audio_profile_id"] = "NATIVE_MULTIMODAL_SELECTIVE_BGM"
            self.assertIn(
                "AUDIO_PROFILE_ID_GENERATION_CONTRACT_MISMATCH",
                validate_audio_profile_binding(overridden),
            )

    def test_binding_detects_generation_contract_mutation(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "contract.json"
            contract = {"episode": "E99", "audio_contract": {"bgm": "NONE_WHOLE_EPISODE"}}
            path.write_text(json.dumps(contract, ensure_ascii=False))
            project = {"metadata": {"episode": "E99", "sound_design_contract": {}}}
            apply_audio_profile_binding(project, contract, contract_path=path)
            path.write_text(json.dumps({
                "episode": "E99", "audio_contract": {"bgm": "S08_ONLY_LOW_SUSTAIN"}
            }, ensure_ascii=False))
            self.assertIn(
                "AUDIO_PROFILE_BINDING_GENERATION_CONTRACT_SHA_MISMATCH",
                validate_audio_profile_binding(project),
            )


if __name__ == "__main__":
    unittest.main()
