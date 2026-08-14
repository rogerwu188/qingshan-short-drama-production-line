import io
import json
import unittest
from argparse import Namespace
from unittest import mock
from urllib.error import HTTPError

import tools.giggle_api_client as client


class Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def http_error(code, body):
    return HTTPError("https://giggle.pro/test", code, "error", {}, io.BytesIO(body.encode()))


class GiggleRetryTest(unittest.TestCase):
    @mock.patch.object(client, "_request")
    def test_image_without_references_uses_text_to_image(self, request):
        request.return_value = {"code": 200}
        args = Namespace(
            prompt="identity plate",
            reference_image=None,
            count=1,
            model="gpt-image-2-pro",
            aspect_ratio="9:16",
            resolution="1K",
        )

        client.generate_image(args)

        endpoint, payload = request.call_args.args
        self.assertEqual(endpoint, "/api/v1/generation/text-to-image")
        self.assertNotIn("reference_images", payload)

    @mock.patch.object(client, "_image_list", return_value=[{"base64": "encoded"}])
    @mock.patch.object(client, "_request")
    def test_image_with_references_uses_image_to_image(self, request, _image_list):
        request.return_value = {"code": 200}
        args = Namespace(
            prompt="keyframe",
            reference_image=["character.png"],
            count=1,
            model="gpt-image-2-pro",
            aspect_ratio="9:16",
            resolution="1K",
        )

        client.generate_image(args)

        endpoint, payload = request.call_args.args
        self.assertEqual(endpoint, "/api/v1/generation/image-to-image")
        self.assertEqual(payload["reference_images"], [{"base64": "encoded"}])

    @mock.patch.object(client.time, "sleep")
    @mock.patch.object(client.urllib.request, "urlopen")
    def test_retries_403_1010_once(self, urlopen, _sleep):
        urlopen.side_effect = [http_error(403, "error code: 1010"), Response({"code": 200})]
        result = client._urlopen_json(mock.Mock())
        self.assertEqual(result["code"], 200)
        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(urlopen.call_args.kwargs["timeout"], client.HTTP_TIMEOUT_SECONDS)

    @mock.patch.object(client.time, "sleep")
    @mock.patch.object(client.urllib.request, "urlopen")
    def test_stops_after_second_interface_failure(self, urlopen, _sleep):
        urlopen.side_effect = [http_error(503, "upstream"), http_error(503, "upstream")]
        with self.assertRaises(SystemExit):
            client._urlopen_json(mock.Mock())
        self.assertEqual(urlopen.call_count, 2)

    @mock.patch.object(client.time, "sleep")
    @mock.patch.object(client.urllib.request, "urlopen")
    def test_does_not_retry_auth_or_parameter_failure(self, urlopen, _sleep):
        urlopen.side_effect = http_error(401, "invalid key")
        with self.assertRaises(SystemExit):
            client._urlopen_json(mock.Mock())
        self.assertEqual(urlopen.call_count, 1)

    @mock.patch.object(client.time, "sleep")
    @mock.patch.object(client.urllib.request, "urlopen")
    def test_does_not_retry_plain_permission_403(self, urlopen, _sleep):
        urlopen.side_effect = http_error(403, "resource forbidden")
        with self.assertRaises(SystemExit):
            client._urlopen_json(mock.Mock())
        self.assertEqual(urlopen.call_count, 1)

    @mock.patch.object(client, "_headers", return_value={})
    @mock.patch.object(client.time, "sleep")
    @mock.patch.object(client.urllib.request, "urlopen")
    def test_post_generation_never_retries_ambiguous_failure(
        self, urlopen, sleep, _headers
    ):
        urlopen.side_effect = http_error(503, "upstream")

        with self.assertRaises(SystemExit):
            client._request("/api/v1/generation/text-to-image", {"prompt": "one"})

        self.assertEqual(urlopen.call_count, 1)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
