import unittest
from unittest.mock import patch

from agentcut import bgm, speech


class AgentCutGeneratedAssetRightsPolicyTest(unittest.TestCase):
    def test_bgm_submission_is_account_owned(self):
        with patch.object(bgm, "_request", return_value={"data": {"task_id": "bgm-task"}}):
            result = bgm.submit_bgm("instrumental suspense score")
        self.assertEqual(result["ownershipStatus"], "SELF_GENERATED_ACCOUNT_OWNED")
        self.assertFalse(result["externalCommercialRightsMetadataRequired"])
        self.assertFalse(result["commercialUseMetadata"]["releaseBlocked"])

    def test_speech_submission_is_account_owned(self):
        with patch.object(speech, "_request", return_value={"data": {"task_id": "speech-task"}}):
            result = speech.submit_speech("测试对白", voice_id="voice", emotion="克制")
        self.assertEqual(result["ownershipStatus"], "SELF_GENERATED_ACCOUNT_OWNED")
        self.assertFalse(result["externalCommercialRightsMetadataRequired"])
        self.assertFalse(result["commercialUseMetadata"]["releaseBlocked"])


if __name__ == "__main__":
    unittest.main()
