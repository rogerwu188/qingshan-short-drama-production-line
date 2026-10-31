"""gpt-image-2 images through the HopsAPI router (owner decision 2026-10-30).

Every HTTP call is mocked at ``hopsapi_video_client._http`` (and the image download at
``_download_bytes``): no request leaves this host and no key is needed.  Covered: provider switch,
size mapping, reference selection (<=16) and preprocessing (the 16000x2200 panorama), upload MIME,
Txt2Img / Img2Img selection, the S3 and S5 submit paths, idempotent re-entry (no re-POST of a bound
task, retry after an uncharged terminal failure), the harvest, the Giggle-shaped adapters and the
budget-ledger cost leg.  Pillow is used only where a test says so (skip-guarded).
"""
from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for _path in (str(ROOT), str(ROOT / "tools"), str(ROOT / "lines" / "nalu" / "runtime" / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tools import hopsapi_image_client as images  # noqa: E402
from tools import submit_giggle_character_asset_plan as plan_submitter  # noqa: E402
from tools import submit_giggle_image_manifest as manifest_submitter  # noqa: E402
from tools import harvest_giggle_image_batch as harvester  # noqa: E402
from tools import giggle_api_client  # noqa: E402

#: the exact module object the image client calls (it may be loaded flat or as tools.*)
hops = images.hops

try:
    import PIL  # noqa: F401
    HAVE_PIL = True
except ImportError:  # pragma: no cover - depends on the interpreter
    HAVE_PIL = False

HOPS_ENV = {"NALU_IMAGE_PROVIDER": "hopsapi", "HOPSAPI_API_KEY": "test-key-not-real",
            "HOPSAPI_RETRY_DELAY_SECONDS": "0"}


def make_png(width: int, height: int, *, seed: int = 1, rows: int | None = None) -> bytes:
    """A real (decodable) RGB PNG.  ``rows`` limits the pixel payload for huge headers: the IHDR says
    width x height, which is all the header-only checks read."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    state = seed
    raw = bytearray()
    for _ in range(height if rows is None else rows):
        raw.append(0)
        for _ in range(width * 3):
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            raw.append(state >> 16 & 0xFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw))) + chunk(b"IEND", b"")


class FakeHops:
    """Scripted HopsAPI: records every request, answers uploads, create and queries."""

    def __init__(self, *, create=None, queries=None):
        self.calls: list[dict] = []
        self.create = create or (lambda: (200, {"code": 200, "message": "success",
                                                "task_id": f"tsk_img_{len(self.posts('/router/task/create'))}"}))
        self.queries = list(queries or [])

    def __call__(self, method, url, *, body=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "body": body, "headers": dict(headers or {})})
        if url.endswith("/api/file-stream-upload"):
            text = body.decode("latin-1")
            mime = text.split("Content-Type: ", 1)[1].split("\r\n", 1)[0]
            name = text.split('name="fileName"\r\n\r\n', 1)[1].split("\r\n", 1)[0]
            payload = {"success": True, "code": 200, "data": {
                "fileUrl": f"https://assets.hopsapi.com/public/tmp/1/x/{name}", "mimeType": mime,
                "expiresAt": "2026-10-31T00:00:00Z"}}
            return 200, payload, json.dumps(payload)
        if url.endswith("/router/task/create"):
            result = self.create()
            if isinstance(result, BaseException):
                raise result
            status, payload = result
            return status, payload, json.dumps(payload)
        if "/router/tasks/" in url:
            status, payload = self.queries.pop(0)
            return status, payload, json.dumps(payload)
        raise AssertionError(f"unexpected request {method} {url}")

    def posts(self, suffix):
        return [c for c in self.calls if c["method"] == "POST" and c["url"].endswith(suffix)]

    def created_payloads(self):
        return [json.loads(c["body"]) for c in self.posts("/router/task/create")]


class EnvCase(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, HOPS_ENV)
        self.env.start()
        self.addCleanup(self.env.stop)
        # belt and braces: nothing in these tests may reach a real socket
        offline = patch("urllib.request.urlopen", side_effect=AssertionError("network access in a unit test"))
        offline.start()
        self.addCleanup(offline.stop)


class ProviderSwitchAndPlanningTests(unittest.TestCase):
    def test_env_then_config_then_key_presence(self):
        self.assertEqual(images.image_provider(environ={"NALU_IMAGE_PROVIDER": "giggle", "HOPSAPI_API_KEY": "k"}), "giggle")
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "qingshan.json"
            config.write_text(json.dumps({"generation": {"image_provider": "giggle"}}), encoding="utf-8")
            self.assertEqual(images.image_provider(config_path=config, environ={"HOPSAPI_API_KEY": "k"}), "giggle")
        self.assertEqual(images.image_provider(environ={"HOPSAPI_API_KEY": "k"}), "hopsapi")
        self.assertEqual(images.image_provider(environ={}), "giggle")
        with self.assertRaises(ValueError):
            images.image_provider(environ={"NALU_IMAGE_PROVIDER": "openai"})

    def test_planning_rate_rounds_the_batch_up_and_is_configurable(self):
        self.assertEqual(images.estimated_batch_credits(45, environ={}), 54)  # E09: 17 assets + 28 keyframes
        self.assertEqual(images.estimated_batch_credits(1, environ={}), 2)
        self.assertEqual(images.estimated_batch_credits(0, environ={}), 0)
        self.assertEqual(images.estimated_task_credits(environ={}), 1.2)
        self.assertEqual(images.estimated_batch_credits(10, environ={"HOPSAPI_IMAGE_CREDITS_PER_IMAGE": "0.5"}), 5)

    def test_quality_defaults_high_and_is_configurable(self):
        self.assertEqual(images.image_quality(environ={}), "high")
        self.assertEqual(images.image_quality(environ={"HOPSAPI_IMAGE_QUALITY": "medium"}), "medium")
        with self.assertRaises(ValueError):
            images.image_quality(environ={"HOPSAPI_IMAGE_QUALITY": "ultra"})


class SizeMappingTests(unittest.TestCase):
    def test_portrait_keyframes_and_plates_map_to_the_verified_size(self):
        self.assertEqual(images.map_resolution("9:16", "2K"), "1152x2048")
        self.assertEqual(images.map_resolution("9:16", "1K"), "1152x2048")

    def test_every_table_size_is_valid(self):
        for aspect, size in images.SIZE_BY_ASPECT.items():
            width, height = map(int, size.split("x"))
            self.assertEqual(images.valid_size(width, height), [], aspect)
            a, b = map(int, aspect.split(":"))
            self.assertAlmostEqual(width / height, a / b, delta=0.01)

    def test_explicit_size_passes_and_invalid_sizes_are_refused(self):
        self.assertEqual(images.map_resolution("9:16", "1024x1536"), "1024x1536")
        for bad in ("1000x2000", "4096x2304", "512x512", "1152x4096"):
            with self.assertRaises(ValueError):
                images.map_resolution("9:16", bad)

    def test_unknown_aspect_is_derived_and_validated(self):
        self.assertEqual(images.map_resolution("21:9", None), "2048x880")
        with self.assertRaises(ValueError):
            images.map_resolution("8:1", None)


class ReferenceTests(unittest.TestCase):
    def test_png_and_jpeg_headers_give_dimensions_without_pillow(self):
        self.assertEqual(images.image_dimensions(make_png(16000, 2200, rows=1)), (16000, 2200))
        jpeg = (b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
                + b"\xff\xc0" + struct.pack(">HBHH", 17, 8, 2560, 1440) + b"\x00" * 12)
        self.assertEqual(images.image_dimensions(jpeg), (1440, 2560))

    def test_preprocessing_rule(self):
        self.assertEqual(images.preprocessing_reasons((1440, 2560), 5_500_000), [])
        self.assertEqual(images.preprocessing_reasons((1600, 2200), 400_000), [])
        self.assertEqual(images.preprocessing_reasons((16000, 2200), 385_002),
                         ["LONG_SIDE_ABOVE_4096", "ASPECT_ABOVE_3_TO_1"])
        self.assertEqual(images.preprocessing_reasons((3000, 900), 1000), ["ASPECT_ABOVE_3_TO_1"])
        self.assertEqual(images.preprocessing_reasons((2000, 2000), 21 * 1024 * 1024), ["FILE_ABOVE_20MB"])

    def test_small_reference_is_sent_byte_for_byte(self):
        data = make_png(64, 114)
        sent, mime, note = images.preprocess_reference(data, "plate.png")
        self.assertEqual(sent, data)
        self.assertEqual(mime, "image/png")
        self.assertFalse(note["preprocessed"])
        self.assertEqual(note["sent_sha256"], note["original_sha256"])

    def test_panorama_without_pillow_fails_before_any_upload(self):
        with patch.dict(sys.modules, {"PIL": None}):
            with self.assertRaises(images.ImageTransportError) as raised:
                images.preprocess_reference(make_png(16000, 2200, rows=1), "E09_EPISODE_GLOBAL_SPACE_MAP_V1.png")
        self.assertIn("REQUIRES_PILLOW", str(raised.exception))

    @unittest.skipUnless(HAVE_PIL, "Pillow not installed")
    def test_panorama_is_resized_to_2048_long_side_png(self):
        from PIL import Image
        import io
        buffer = io.BytesIO()
        Image.new("RGB", (16000, 2200), (40, 90, 140)).save(buffer, format="PNG")
        data = buffer.getvalue()
        sent, mime, note = images.preprocess_reference(data, "E09_EPISODE_GLOBAL_SPACE_MAP_V1.png")
        self.assertEqual(mime, "image/png")
        self.assertTrue(note["preprocessed"])
        self.assertEqual(note["original_size"], [16000, 2200])
        self.assertEqual(note["sent_size"], [2048, 282])
        self.assertEqual(note["original_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(note["sent_sha256"], hashlib.sha256(sent).hexdigest())
        with Image.open(io.BytesIO(sent)) as out:
            self.assertEqual(out.size, (2048, 282))

    def test_more_than_sixteen_references_drop_the_lowest_priority(self):
        kept, dropped = images.select_references([f"ref{i}" for i in range(18)])
        self.assertEqual(kept, [f"ref{i}" for i in range(16)])
        self.assertEqual([row["reference"] for row in dropped], ["ref16", "ref17"])
        self.assertEqual([row["index"] for row in dropped], [17, 18])


class RequestTests(EnvCase):
    def test_txt2img_without_references_has_no_images_or_aspect(self):
        payload = images.build_image_request(prompt="p", image_urls=[], resolution="1152x2048")
        self.assertEqual(payload["task"], "Txt2Img")
        self.assertEqual(payload["model"], "gpt-image-2")
        self.assertNotIn("images", payload["input"])
        self.assertNotIn("aspect_ratio", payload["input"])
        self.assertEqual(payload["input"]["quality"], "high")
        self.assertEqual(payload["input"]["output_format"], "png")

    def test_img2img_uploads_every_reference_with_an_explicit_mime(self):
        with tempfile.TemporaryDirectory() as tmp:
            refs = []
            for index in range(3):
                path = Path(tmp) / f"ref{index}.png"
                path.write_bytes(make_png(32, 57, seed=index + 2))
                refs.append(path)
            fake = FakeHops()
            with patch.object(hops, "_http", side_effect=fake):
                prepared = images.prepare_request(prompt="keyframe", reference_paths=refs, aspect_ratio="9:16",
                                                  resolution="2K", task_key="E09-S02-04-KEYFRAME-V1")
        uploads = fake.posts("/api/file-stream-upload")
        self.assertEqual(len(uploads), 3)
        for call in uploads:
            self.assertIn(b"Content-Type: image/png\r\n", call["body"])
        payload = prepared["payload"]
        self.assertEqual(payload["task"], "Img2Img")
        self.assertEqual(len(payload["input"]["images"]), 3)
        self.assertTrue(all(u.startswith("https://") for u in payload["input"]["images"]))
        self.assertEqual(payload["input"]["resolution"], "1152x2048")
        self.assertEqual(fake.posts("/router/task/create"), [])  # preparing never creates a task

    def test_create_outside_a_durable_submitter_is_blocked(self):
        payload = images.build_image_request(prompt="p", image_urls=[], resolution="1152x2048")
        with patch.dict(os.environ, {"QINGSHAN_DURABLE_SUBMITTER_CONTEXT": ""}), \
                patch.object(hops, "_http", side_effect=AssertionError("network")):
            with self.assertRaises(SystemExit):
                images.create_image_task(payload)


class CharacterPlanSubmitterTests(EnvCase):
    """S3: plates, headshots, multi-view sheets, prop / location cards."""

    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory(dir=plan_submitter.ROOT)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.ref = self.root / "base.png"
        self.ref.write_bytes(make_png(36, 64))
        prompt = self.root / "prompt.txt"
        prompt.write_text("vertical character plate", encoding="utf-8")
        self.row = {"id": "CHAR-HOLMES__FRONT_NEUTRAL_HEADSHOT", "episode": "E09", "prompt_file": str(prompt),
                    "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
                    "reference_images": [str(self.ref)],
                    "reference_image_sha256s": [hashlib.sha256(self.ref.read_bytes()).hexdigest()]}
        self.txdir = self.root / "transactions"

    def submit(self, fake, row=None):
        with patch.object(hops, "_http", side_effect=fake), \
                patch.object(plan_submitter, "_request", side_effect=AssertionError("Giggle POST on HopsAPI route")):
            return plan_submitter.submit(row or self.row, self.root / "receipts", self.txdir,
                                         "gpt-image-2-pro", "2K", None, "hopsapi")

    def tx(self, row=None):
        path = plan_submitter.transaction_path(self.txdir, row or self.row, "gpt-image-2-pro", "2K")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_img2img_binds_the_task_and_records_the_request(self):
        fake = FakeHops()
        result = self.submit(fake)
        self.assertEqual(result["provider"], "hopsapi")
        payload = fake.created_payloads()[0]
        self.assertEqual(payload["task"], "Img2Img")
        self.assertEqual(payload["input"]["resolution"], "1152x2048")
        tx = self.tx()
        self.assertEqual(tx["state"], "SUBMITTED_TASK_ID_BOUND")
        self.assertEqual(tx["provider"], "hopsapi")
        self.assertEqual(tx["task_id"], result["task_id"])
        self.assertEqual(tx["estimated_credits"], 1.2)
        self.assertEqual(tx["provider_request_input"]["quality"], "high")
        self.assertEqual(tx["reference_preprocessing"][0]["original_size"], [36, 64])
        self.assertEqual(tx["reference_preprocessing"][0]["sent_sha256"], tx["reference_image_sha256s"][0])
        self.assertNotIn("test-key-not-real", json.dumps(tx))

    def test_txt2img_when_the_row_has_no_reference(self):
        row = {**self.row, "id": "PROP-LAMP", "reference_images": [], "reference_image_sha256s": []}
        fake = FakeHops()
        self.submit(fake, row)
        self.assertEqual(fake.created_payloads()[0]["task"], "Txt2Img")
        self.assertEqual(fake.posts("/api/file-stream-upload"), [])

    def test_re_entry_never_re_posts_a_bound_task(self):
        fake = FakeHops()
        first = self.submit(fake)
        second = self.submit(fake)
        self.assertTrue(second["recovered_from_transaction"])
        self.assertEqual(second["task_id"], first["task_id"])
        self.assertEqual(len(fake.posts("/router/task/create")), 1)

    def test_a_giggle_bound_take_is_recovered_after_the_switch(self):
        path = plan_submitter.transaction_path(self.txdir, self.row, "gpt-image-2-pro", "2K")
        plan_submitter.atomic_json(path, {"submission_fingerprint": plan_submitter.submission_fingerprint(
            self.row, "gpt-image-2-pro", "2K"), "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "giggle-uuid-1"})
        fake = FakeHops()
        result = self.submit(fake)
        self.assertEqual(result["task_id"], "giggle-uuid-1")
        self.assertEqual(fake.calls, [])

    def test_explicit_decline_is_retryable_and_a_lost_response_is_not(self):
        declined = FakeHops(create=lambda: (400, {"code": 400, "message": "bad request"}))
        with self.assertRaises(RuntimeError):
            self.submit(declined)
        self.assertEqual(self.tx()["state"], "NOT_CHARGED_RETRYABLE")
        ok = FakeHops()
        self.submit(ok)
        self.assertEqual(self.tx()["state"], "SUBMITTED_TASK_ID_BOUND")

        row = {**self.row, "id": "CHAR-WATSON"}
        lost = FakeHops(create=lambda: hops.HopsapiHTTPError(502, None, "bad gateway"))
        with self.assertRaises(Exception):
            self.submit(lost, row)
        self.assertEqual(self.tx(row)["state"], "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION")
        again = FakeHops()
        with self.assertRaises(plan_submitter.PreIntentFailure):
            self.submit(again, row)
        self.assertEqual(again.posts("/router/task/create"), [])

    def test_uncharged_terminal_failure_may_post_again(self):
        fake = FakeHops()
        self.submit(fake)
        path = plan_submitter.transaction_path(self.txdir, self.row, "gpt-image-2-pro", "2K")
        tx = json.loads(path.read_text(encoding="utf-8"))
        hops.record_settlement(path, tx["task_id"], {"remote_status": "failed", "error": "Provider error"},
                               now="2026-10-30T00:00:00Z")
        retry = FakeHops(create=lambda: (200, {"code": 200, "task_id": "tsk_retry"}))
        result = self.submit(retry)
        self.assertEqual(result["task_id"], "tsk_retry")
        retired = list(self.txdir.glob("*.terminal-*.json"))
        self.assertEqual(len(retired), 1)
        self.assertEqual(json.loads(retired[0].read_text())["provider_cost_credits"], 0.0)


class ImageManifestSubmitterTests(EnvCase):
    """S5: keyframes, start frames and keyframe redos."""

    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.refs = []
        for index in range(2):
            path = self.root / f"ref{index}.png"
            path.write_bytes(make_png(36, 64, seed=index + 7))
            self.refs.append(path)
        prompt = self.root / "kf.txt"
        prompt.write_text("Holmes at the pawnshop door", encoding="utf-8")
        self.prompt = prompt
        self.task = {"task_key": "E09-S02-04-KEYFRAME-V1", "episode": "E09",
                     "prompt_file": str(prompt), "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
                     "reference_images": [str(p) for p in self.refs],
                     "reference_bindings": [{"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                            for p in self.refs],
                     "model": "gpt-image-2-pro", "aspect_ratio": "9:16", "resolution": "2K"}
        self.txdir = self.root / "tx"
        self.txdir.mkdir()

    def post(self, fake):
        with patch.object(hops, "_http", side_effect=fake), \
                patch.object(manifest_submitter, "_request", side_effect=AssertionError("Giggle POST")):
            recovered = manifest_submitter.prior_submission_result(self.task, self.txdir)
            if recovered:
                return recovered
            return manifest_submitter._submit_one_hopsapi(
                self.task, self.root, self.txdir, self.prompt.read_text(encoding="utf-8"),
                [str(p) for p in self.refs])

    def test_keyframe_binds_and_re_entry_recovers(self):
        fake = FakeHops()
        first = self.post(fake)
        self.assertEqual(first["provider"], "hopsapi")
        tx = json.loads(manifest_submitter.transaction_path(self.txdir, self.task).read_text())
        self.assertEqual(tx["provider_task"], "Img2Img")
        self.assertEqual(tx["provider_resolution"], "1152x2048")
        self.assertEqual(len(tx["sent_reference_sha256"]), 2)
        second = self.post(fake)
        self.assertTrue(second["recovered_from_transaction"])
        self.assertEqual(second["provider"], "hopsapi")
        self.assertEqual(len(fake.posts("/router/task/create")), 1)

    def test_batch_summary_is_per_task_not_a_giggle_statement(self):
        fake = FakeHops()
        result = self.post(fake)
        summary, ambiguity = manifest_submitter.hopsapi_credit_summary([result], [], self.txdir)
        self.assertEqual(summary["status"], "PASS_BOUNDED")
        self.assertIsNone(summary["charged_credits"])
        self.assertEqual(summary["estimated_credits"], 2)
        self.assertEqual(ambiguity, "NO_AMBIGUOUS_SUBMISSIONS")


class HarvestTests(EnvCase):
    def test_completed_task_lands_at_the_giggle_harvest_path_and_records_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            transaction = root / "tx.json"
            transaction.write_text(json.dumps({"provider": "hopsapi", "state": "SUBMITTED_TASK_ID_BOUND",
                                               "task_id": "tsk_k1", "estimated_credits": 1.2}), encoding="utf-8")
            image = make_png(48, 85)
            fake = FakeHops(queries=[(200, {"task_id": "tsk_k1", "status": 2, "cost": 0.97,
                                            "results": [{"urls": ["https://assets.hopsapi.com/x.png"]}]})])
            row = {"task_key": "E09-S02-04-KEYFRAME-V1", "task_id": "tsk_k1", "status": "submitted",
                   "provider": "hopsapi", "transaction": str(transaction)}
            with patch.object(hops, "_http", side_effect=fake), \
                    patch.object(hops, "_download_bytes", return_value=image), \
                    patch.object(harvester, "query_task", side_effect=AssertionError("Giggle query")):
                item = harvester.harvest_one(row, "E09", root / "out", root / "raw", None)
            expected = root / "out" / "E09_E09-S02-04-KEYFRAME-V1_tsk_k1.png"
            self.assertEqual(item["output_path"], str(expected))
            self.assertEqual(expected.read_bytes(), image)
            self.assertEqual(item["credit"], 0.97)
            self.assertEqual(item["remote_status"], "completed")
            settled = json.loads(transaction.read_text(encoding="utf-8"))
            self.assertEqual(settled["provider_cost_credits"], 0.97)

    def test_424_is_terminal_failed_and_not_charged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeHops(queries=[(200, {"code": 424, "message": "Provider error", "task_id": "tsk_f",
                                            "status": 3})])
            row = {"task_key": "K", "task_id": "tsk_f", "status": "submitted"}
            with patch.object(hops, "_http", side_effect=fake):
                item = harvester.harvest_one(row, "E09", root / "out", root / "raw", None)
            self.assertEqual(item["remote_status"], "failed")
            self.assertIn("failed", harvester.TERMINAL)
            self.assertEqual(item["credit"], 0)

    def test_a_non_image_download_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(hops.HopsapiError):
                images.download_image("https://x", Path(tmp) / "a.png", fetch=lambda url: b"<html>" * 400)


class GiggleShapedAdapterTests(EnvCase):
    def test_query_task_dispatches_hopsapi_ids(self):
        fake = FakeHops(queries=[(200, {"task_id": "tsk_q", "status": 2, "cost": 0.5,
                                        "results": [{"urls": ["https://assets.hopsapi.com/q.png"]}]})])
        with patch.object(hops, "_http", side_effect=fake), \
                patch.object(giggle_api_client, "_get", side_effect=AssertionError("Giggle GET")):
            response = giggle_api_client.query_task(type("A", (), {"task_id": "tsk_q"})())
        self.assertEqual(response["data"]["status"], "completed")
        self.assertEqual(response["data"]["urls"], ["https://assets.hopsapi.com/q.png"])

    def test_generate_image_cli_function_routes_to_hopsapi(self):
        fake = FakeHops()
        args = type("A", (), {"prompt": "apple", "reference_image": [], "aspect_ratio": "9:16",
                              "resolution": "2K", "count": 1, "model": "gpt-image-2-pro"})()
        with patch.object(hops, "_http", side_effect=fake), \
                patch.object(giggle_api_client, "_request", side_effect=AssertionError("Giggle POST")), \
                giggle_api_client.durable_generation_context():
            response = giggle_api_client.generate_image(args)
        self.assertTrue(response["data"]["task_id"].startswith("tsk_"))
        self.assertEqual(fake.created_payloads()[0]["task"], "Txt2Img")


class BudgetLedgerTests(unittest.TestCase):
    def test_image_cost_is_on_the_hopsapi_leg_not_the_giggle_upper_bound(self):
        import nalu_budget_ledger as ledger
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "workflow/tasks/giggle_submit_transactions/E09"
            store.mkdir(parents=True)
            rows = {
                "a": {"provider": "hopsapi", "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "tsk_a",
                      "estimated_credits": 1.2, "provider_cost_credits": 0.97},
                "b": {"provider": "hopsapi", "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "tsk_b",
                      "estimated_credits": 1.2},
                "c.terminal-tsk_c": {"provider": "hopsapi", "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "tsk_c",
                                     "estimated_credits": 1.2, "remote_terminal_state": "failed",
                                     "provider_cost_credits": 0.0},
                "d": {"state": "SUBMITTED_TASK_ID_BOUND", "task_id": "giggle-uuid-d"},
            }
            for name, row in rows.items():
                (store / f"{name}.json").write_text(json.dumps(row), encoding="utf-8")
            with patch.object(ledger, "ENGINE_ROOT", Path(tmp)):
                spend = ledger.scan_hopsapi_spend("E09")
                non_video = ledger.scan_non_video_spend("E09")
                pending = ledger.scan_pending_exposure("E09")
            self.assertEqual(spend["by_kind"]["image"]["settled_credits"], 0.97)
            self.assertEqual(spend["by_kind"]["image"]["pending_exposure_credits"], 1.2)
            self.assertEqual(spend["unsettled_task_count"], 1)
            self.assertEqual(non_video["bound_image_transaction_count"], 1)  # only the Giggle row
            self.assertEqual(non_video["bound_image_transaction_upper_credits"], 11)
            self.assertEqual(pending, 11)  # the Giggle row only; HopsAPI rows never double in


class ProviderOutageTests(EnvCase):
    """Lab E10/E11: uncharged 424 "Provider error" settlements are upstream refusals (identical requests
    failed and later completed; a reference-free Txt2Img failed the same way).  Canary first, cooldown."""

    def settled(self, store, episode, name, *, minute, ok, task_id=None):
        folder = store / episode
        folder.mkdir(parents=True, exist_ok=True)
        stamp = f"2026-10-31T06:{minute:02d}:00Z"
        row = {"provider": "hopsapi", "provider_model": "gpt-image-2", "state": "SUBMITTED_TASK_ID_BOUND",
               "task_id": task_id or f"tsk_{name}", "intent_recorded_at": stamp,
               "provider_status_observed_at": stamp}
        if ok:
            row.update({"provider_remote_status": "completed", "provider_cost_credits": 1.16})
        else:
            row.update({"provider_remote_status": "failed", "remote_terminal_state": "failed",
                        "remote_terminal_observed_at": stamp, "provider_cost_credits": 0.0,
                        "provider_failure": "Provider error (request id: aitk-x)"})
        (folder / f"{name}.json").write_text(json.dumps(row), encoding="utf-8")

    @staticmethod
    def at(minute):
        from datetime import datetime, timezone
        return datetime(2026, 10, 31, 6, minute, tzinfo=timezone.utc).timestamp()

    def test_provider_error_classification(self):
        self.assertTrue(images.is_provider_error_failure(
            {"remote_status": "failed", "provider_code": 424, "cost": 0.0, "error": "Provider error (request id: a)"}))
        self.assertTrue(images.is_provider_error_failure(
            {"provider_remote_status": "failed", "provider_cost_credits": 0.0,
             "provider_failure": "Provider error (request id: a)"}))
        self.assertFalse(images.is_provider_error_failure({"remote_status": "completed", "cost": 1.0}))
        self.assertFalse(images.is_provider_error_failure(
            {"remote_status": "failed", "provider_code": 500, "cost": 0.0, "error": "content policy"}))

    def test_a_trailing_run_of_424s_is_an_outage_until_the_cooldown_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            self.settled(store, "E10", "ok", minute=1, ok=True)
            for index in range(3):
                self.settled(store, "E11", f"f{index}", minute=10 + index, ok=False)
            outage = images.recent_provider_outage(store, now=self.at(20))
            self.assertEqual(outage["blocker"], "HOPSAPI_IMAGE_PROVIDER_OUTAGE")
            self.assertEqual(outage["consecutive_provider_errors"], 3)
            self.assertEqual(outage["retry_after_utc"], "2026-10-31T06:27:00Z")
            self.assertIsNone(images.recent_provider_outage(store, now=self.at(28)))
            with patch.dict(os.environ, {"HOPSAPI_IMAGE_OUTAGE_COOLDOWN_SECONDS": "0"}):
                self.assertIsNone(images.recent_provider_outage(store, now=self.at(20)))

    def test_a_success_after_the_failures_or_too_few_failures_is_no_outage(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            for index in range(3):
                self.settled(store, "E11", f"f{index}", minute=10 + index, ok=False)
            self.settled(store, "E11", "later.terminal-x", minute=14, ok=True)
            self.assertIsNone(images.recent_provider_outage(store, now=self.at(16)))
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp)
            for index in range(2):
                self.settled(store, "E11", f"f{index}", minute=10 + index, ok=False)
            self.assertIsNone(images.recent_provider_outage(store, now=self.at(13)))

    def test_canary_424_is_settled_on_its_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            transaction = Path(tmp) / "tx.json"
            transaction.write_text(json.dumps({"provider": "hopsapi", "state": "SUBMITTED_TASK_ID_BOUND",
                                               "task_id": "tsk_c"}), encoding="utf-8")
            fake = FakeHops(queries=[(200, {"task_id": "tsk_c", "status": 1}),
                                     (200, {"code": 424, "message": "Provider error (request id: aitk-1)",
                                            "task_id": "tsk_c", "status": 3})])
            with patch.object(hops, "_http", side_effect=fake):
                result = images.canary_check("tsk_c", transaction, wait_seconds=60, sleep=lambda _s: None)
            self.assertEqual(result["outcome"], "PROVIDER_ERROR")
            row = json.loads(transaction.read_text(encoding="utf-8"))
            self.assertEqual(row["remote_terminal_state"], "failed")
            self.assertEqual(row["provider_failure_code"], 424)
            self.assertEqual(row["provider_cost_credits"], 0.0)
            self.assertTrue(images.terminal_failed_binding(row))

    def test_canary_still_processing_after_the_wait_is_healthy(self):
        ticks = iter(range(0, 1000, 30))
        fake = FakeHops(queries=[(200, {"task_id": "tsk_p", "status": 1})] * 10)
        with patch.object(hops, "_http", side_effect=fake):
            result = images.canary_check("tsk_p", None, wait_seconds=60, sleep=lambda _s: None,
                                         clock=lambda: next(ticks))
        self.assertEqual(result["outcome"], "HEALTHY")

    def batch(self, outcome):
        tasks = [{"task_key": f"E11-S0{i}-KEYFRAME-V1"} for i in range(1, 5)]
        submitted = []

        def fake_submit(task, receipt_dir, transaction_dir, provider=None):
            submitted.append(task["task_key"])
            return {"task_key": task["task_key"], "task_id": f"tsk_{len(submitted)}", "status": "submitted",
                    "transaction": "workflow/tasks/x.json", "recovered_from_transaction": False}

        deferred = []
        with patch.object(manifest_submitter, "submit_one", side_effect=fake_submit), \
                patch.object(manifest_submitter.image_client, "canary_check",
                             return_value={"outcome": outcome, "task_id": "tsk_1"}) as canary:
            results, failures = manifest_submitter.submit_all(
                tasks, Path("."), Path("."), 6, "hopsapi", deferred=deferred)
        return submitted, results, failures, deferred, canary

    def test_batch_stops_after_a_424_canary_and_posts_nothing_else(self):
        submitted, results, failures, deferred, canary = self.batch("PROVIDER_ERROR")
        self.assertEqual(submitted, ["E11-S01-KEYFRAME-V1"])
        self.assertEqual(canary.call_count, 1)
        self.assertEqual(failures, [])
        not_posted = [row for row in deferred if "canary" not in row]
        self.assertEqual([row["status"] for row in not_posted], ["NOT_POSTED_PROVIDER_OUTAGE"] * 3)
        self.assertTrue(all(row["credit"] == 0 for row in not_posted))

    def test_batch_continues_after_a_healthy_canary(self):
        submitted, results, failures, deferred, _ = self.batch("HEALTHY")
        self.assertEqual(len(submitted), 4)
        self.assertEqual(len(results), 4)
        self.assertEqual([row for row in deferred if "canary" not in row], [])

    def test_harvest_tags_the_upstream_424(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = FakeHops(queries=[(200, {"code": 424, "message": "Provider error (request id: a)",
                                            "task_id": "tsk_f", "status": 3})])
            row = {"task_key": "K", "task_id": "tsk_f", "status": "submitted"}
            with patch.object(hops, "_http", side_effect=fake):
                item = harvester.harvest_one(row, "E11", root / "out", root / "raw", None)
            self.assertEqual(item["failure_class"], "HOPSAPI_PROVIDER_ERROR_424")


if __name__ == "__main__":
    unittest.main()
