import unittest
from unittest.mock import patch

from tools import giggle_api_client


class GiggleVideoStandardModelGateTests(unittest.TestCase):
    def test_pro_is_blocked_before_credentials_or_network(self):
        with patch.object(giggle_api_client, "_headers") as headers, patch.object(giggle_api_client, "_urlopen_json") as network:
            with self.assertRaisesRegex(SystemExit, "standard"):
                giggle_api_client._request(
                    "/api/v1/generation/image-to-video",
                    {"model": "seedance-2.0-pro", "prompt": "test"},
                )
        headers.assert_not_called()
        network.assert_not_called()

    def test_standard_reaches_transport(self):
        with patch.object(giggle_api_client, "_headers", return_value={}), patch.object(
            giggle_api_client, "_urlopen_json", return_value={"data": {"task_id": "test"}}
        ) as network:
            result = giggle_api_client._request(
                "/api/v1/generation/image-to-video",
                {"model": "seedance-2.0", "prompt": "test"},
            )
        self.assertEqual(result["data"]["task_id"], "test")
        network.assert_called_once()


if __name__ == "__main__":
    unittest.main()
