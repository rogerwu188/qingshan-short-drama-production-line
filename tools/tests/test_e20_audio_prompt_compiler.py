import json
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPILER = ROOT / "tools" / "compile_e20_audio_prompt_skeleton.py"


def delivery():
    return {
        "tone_code": "quiet_order",
        "subtext_code": "advance_claim",
        "pace": "medium",
        "volume": "normal",
        "breath": "steady",
        "temperature": 0,
        "energy": 2,
        "stress": ["证据"],
        "expression_arc": {"start": "平静", "trigger": "证据", "end": "警惕"},
    }


class E20AudioPromptCompilerTests(unittest.TestCase):
    def run_compiler(self, manifest, beat_sheet):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            manifest_path = tmp_path / "manifest.json"
            beat_path = tmp_path / "beat.json"
            out_path = tmp_path / "out.json"
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
            beat_path.write_text(json.dumps(beat_sheet, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(COMPILER),
                    "--manifest",
                    str(manifest_path),
                    "--beat-sheet",
                    str(beat_path),
                    "--out",
                    str(out_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            output = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else None
            return result, output

    def base_data(self):
        manifest = {
            "episode": "E20",
            "relationship_strategy_by_beat": {"B01": "test pressure"},
            "lines": [
                {
                    "dia_id": "DIA-001",
                    "beat_id": "B01",
                    "speaker": "陈迹",
                    "character_id": "CHAR-陈迹-古装",
                    "voice_asset_id": "voice-1",
                    "text": "证据。",
                    "text_with_pause": "证据。",
                    "function": "proof",
                    "delivery": delivery(),
                }
            ],
        }
        beat_sheet = {
            "structure": [{"beat_id": "B01"}],
            "dialogue_draft": [{"dia_id": "DIA-001"}],
        }
        raw = json.dumps(beat_sheet, ensure_ascii=False).encode()
        manifest["beat_sheet_sha256"] = hashlib.sha256(raw).hexdigest()
        return manifest, beat_sheet

    def test_compiles_audio_only_skeleton(self):
        manifest, beat_sheet = self.base_data()
        result, output = self.run_compiler(manifest, beat_sheet)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output["checks"]["dialogue_count"], 1)
        self.assertFalse(output["visual_prompt_fields_present"])
        self.assertNotIn("VISUAL_PROMPT_NO_DIALOGUE_TEXT", output["beats"][0])

    def test_rejects_dialogue_order_drift(self):
        manifest, beat_sheet = self.base_data()
        beat_sheet["dialogue_draft"] = [{"dia_id": "DIA-999"}]
        manifest["beat_sheet_sha256"] = hashlib.sha256(
            json.dumps(beat_sheet, ensure_ascii=False).encode()
        ).hexdigest()
        result, output = self.run_compiler(manifest, beat_sheet)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(output)
        self.assertIn("dialogue ID or order mismatch", result.stderr)

    def test_rejects_unresolved_voice_without_gate(self):
        manifest, beat_sheet = self.base_data()
        manifest["lines"][0]["voice_asset_id"] = None
        result, output = self.run_compiler(manifest, beat_sheet)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(output)
        self.assertIn("unresolved voice lacks explicit gate", result.stderr)

    def test_rejects_stale_manifest_hash(self):
        manifest, beat_sheet = self.base_data()
        manifest["beat_sheet_sha256"] = "stale"
        result, output = self.run_compiler(manifest, beat_sheet)
        self.assertNotEqual(result.returncode, 0)
        self.assertIsNone(output)
        self.assertIn("beat sheet SHA256 mismatch", result.stderr)


if __name__ == "__main__":
    unittest.main()
