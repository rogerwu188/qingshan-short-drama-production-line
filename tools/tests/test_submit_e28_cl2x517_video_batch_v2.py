import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tools.submit_e28_cl2x517_video_batch_v2 as submitter


class SubmitE28VideoBatchCreditGateTest(unittest.TestCase):
    def test_blocked_standard_gate_prevents_all_remote_calls(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            prompt_gate = root / "prompt_gate.json"
            approval = root / "approval.json"
            receipt = root / "receipt.json"
            report = root / "E28_VIDEO_CREDIT_LIMIT_GATE.json"
            for path in (config, prompt_gate, approval):
                path.write_text("{}\n", encoding="utf-8")

            gate = {
                "status": "BLOCKED_VIDEO_CREDIT_LIMIT_EXCEEDED",
                "actual_charged_credits_known_total": 51024,
                "effective_limit_credits": 5000,
                "approval": {"valid": False},
            }

            def fake_sha(path):
                return (
                    submitter.EXPECTED_CONFIG_SHA
                    if Path(path) == config
                    else submitter.EXPECTED_GATE_SHA
                )

            def fake_load(path):
                if Path(path) == prompt_gate:
                    return {"status": "PASS"}
                if Path(path) == approval:
                    return {
                        "status": "EXEMPTED_BY_ROGER_FOR_THIS_EPISODE",
                        "approved_batch_config_sha256": submitter.EXPECTED_CONFIG_SHA,
                    }
                return {}

            argv = [
                "submit_e28_cl2x517_video_batch_v2.py",
                "--config", str(config),
                "--prompt-gate", str(prompt_gate),
                "--approval", str(approval),
                "--receipt", str(receipt),
            ]
            with (
                patch.object(sys, "argv", argv),
                patch.object(submitter, "sha256", side_effect=fake_sha),
                patch.object(submitter, "load", side_effect=fake_load),
                patch.object(submitter, "evaluate_episode_credit_gate", return_value=gate),
                patch.object(submitter, "credit_report_path", return_value=report),
                patch.object(submitter, "ensure_giggle_api_key") as ensure_key,
                patch.object(submitter, "register_audio") as register_audio,
                patch.object(submitter, "generate_omni_video") as generate_video,
                self.assertRaisesRegex(RuntimeError, "actual=51024"),
            ):
                submitter.main()

            ensure_key.assert_not_called()
            register_audio.assert_not_called()
            generate_video.assert_not_called()
            self.assertEqual(json.loads(report.read_text(encoding="utf-8")), gate)


if __name__ == "__main__":
    unittest.main()
