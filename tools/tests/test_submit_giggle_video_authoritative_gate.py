import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.submit_giggle_video_manifest_v2 import run_authoritative_submission_gate


ROOT = Path(__file__).resolve().parents[2]
DEPLOYED_TOOLS = Path.home() / ".local/share/backlotos/share/pipeline-tools"


class AuthoritativeVideoGateIntegrationTests(unittest.TestCase):
    def test_e39_style_mislabeled_action_is_blocked_by_real_submit_entrypoint(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            prompt = Path(tmp) / "u01.txt"
            prompt.write_text("0.0秒押送位移；4.8秒拦截扣腕；9.4秒按住前臂；禁止慢动作", encoding="utf-8")
            rel_prompt = prompt.relative_to(ROOT)
            manifest = {
                "episode": "CANARY",
                "machine_gate_reports": ["historical-pass.json"],
                "tasks": [{
                    "task_key": "CANARY-U01",
                    "prompt_file": str(rel_prompt),
                    "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
                    "duration_seconds": 15,
                    "action_unit": False,
                    "model": "seedance-2.0",
                }],
            }
            manifest_path = Path(tmp) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with patch.dict(os.environ, {"BACKLOT_PIPELINE_TOOLS_DIR": str(DEPLOYED_TOOLS)}):
                with self.assertRaisesRegex(ValueError, "ACTION_UNIT_CLASSIFICATION_MISSING"):
                    run_authoritative_submission_gate(manifest, manifest_path)

    def test_missing_deployment_fails_closed(self):
        with patch.dict(os.environ, {"BACKLOT_PIPELINE_TOOLS_DIR": "/definitely/missing"}):
            with self.assertRaisesRegex(ValueError, "fails closed"):
                run_authoritative_submission_gate({"tasks": []}, ROOT / "missing.json")


if __name__ == "__main__":
    unittest.main()
