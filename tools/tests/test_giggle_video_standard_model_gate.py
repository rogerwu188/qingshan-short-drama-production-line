import unittest
from unittest.mock import patch

from tools import giggle_api_client


class GiggleVideoStandardModelGateTests(unittest.TestCase):
    def test_fast_is_blocked_before_credentials_or_network(self):
        with patch.object(giggle_api_client, "_headers") as headers, patch.object(giggle_api_client, "_urlopen_json") as network:
            with self.assertRaisesRegex(SystemExit, "seedance-2.0-pro"):
                giggle_api_client._request(
                    "/api/v1/generation/image-to-video",
                    {"model": "seedance-2.0-fast", "prompt": "test"},
                )
        headers.assert_not_called()
        network.assert_not_called()

    def test_standard_pro_reaches_transport(self):
        with patch.dict("os.environ", {"QINGSHAN_DURABLE_SUBMITTER_CONTEXT": "1"}), patch.object(giggle_api_client, "_headers", return_value={}), patch.object(
            giggle_api_client, "_urlopen_json", return_value={"data": {"task_id": "test"}}
        ) as network:
            result = giggle_api_client._request(
                "/api/v1/generation/image-to-video",
                {"model": "seedance-2.0-pro", "prompt": "test"},
            )
        self.assertEqual(result["data"]["task_id"], "test")
        network.assert_called_once()

    def test_standard_without_durable_context_is_blocked_before_network(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(
            giggle_api_client, "_urlopen_json"
        ) as network:
            with self.assertRaisesRegex(SystemExit, "durable transaction context"):
                giggle_api_client._request(
                    "/api/v1/generation/image-to-video",
                    {"model": "seedance-2.0-pro", "prompt": "test"},
                )
        network.assert_not_called()


if __name__ == "__main__":
    unittest.main()
