"""Series poster cover (owner 2026-11-13): AI key art without text + a programmatically typeset title.

No network: HopsAPI is mocked at ``hopsapi_video_client._http`` / ``_download_bytes`` and X2C / the fleet
service through fakes.  Pillow is required (skip-guarded); InsightFace / RapidOCR are replaced by fakes
wherever a test depends on them.
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "skills" / "nalu-claude-code" / "scripts"
for _path in (str(ROOT), str(ROOT / "tools"), str(SCRIPTS)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

try:
    from PIL import Image, ImageDraw
    HAVE_PIL = True
except ImportError:  # pragma: no cover
    HAVE_PIL = False

from tools import series_poster as sp  # noqa: E402
from tools import hopsapi_image_client as images  # noqa: E402

hops = images.hops
NO_DETECTORS = {"face_detector": None, "ocr": None}


def art_image(width: int = 540, height: int = 960, colour=(90, 110, 140), noise: bool = True):
    img = Image.new("RGB", (width, height), colour)
    if noise:
        draw = ImageDraw.Draw(img)
        for i in range(0, width, 7):
            draw.line([(i, 0), (width - i, height)], fill=((i * 3) % 255, (i * 5) % 255, (i * 7) % 255))
    return img


def png_bytes(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class TypesettingTest(unittest.TestCase):
    def test_exact_title_rendered_and_fits(self):
        out = sp.typeset(art_image(), "契约婚姻", genre="霸总甜宠", **NO_DETECTORS)
        chosen = out["attempts"][-1]
        self.assertEqual(out["chosen"], "bottom")
        self.assertEqual("".join(chosen["lines"]), "契约婚姻")
        self.assertTrue(chosen["fits"])
        self.assertLessEqual(chosen["bbox"][2], 540)
        self.assertGreaterEqual(chosen["bbox"][1], int(960 * 0.6))  # inside the bottom band

    def test_long_cjk_title_wraps_by_character(self):
        out = sp.typeset(art_image(), "修仙义务教育我最秀", genre="仙侠古装", **NO_DETECTORS)
        lines = out["attempts"][-1]["lines"]
        self.assertGreater(len(lines), 1)
        self.assertEqual("".join(lines), "修仙义务教育我最秀")
        self.assertTrue(all(len(line) >= 2 for line in lines))

    def test_long_latin_title_wraps_by_word(self):
        title = "The Lycan King's Rejected Shadow"
        out = sp.typeset(art_image(), title, genre="Werewolf", language="en", **NO_DETECTORS)
        lines = out["attempts"][-1]["lines"]
        self.assertGreater(len(lines), 1)
        self.assertEqual(" ".join(lines), title.upper())  # Cinzel slot sets capitals
        for line in lines:
            self.assertTrue(set(line.split()) <= set(title.upper().split()))

    def test_fit_shrinks_to_width(self):
        spec = sp.FONTS["zh"]["plain"][0]
        fit = sp.fit_title("这是一个非常非常长的标题需要缩小", spec, max_width=300, max_height=200,
                           start_size=200, min_size=10, max_lines=2)
        font = sp.load_font(spec, fit["size"])
        self.assertTrue(fit["fits"])
        self.assertLessEqual(max(font.getlength(line) for line in fit["lines"]), 301)

    def test_contrast_band_is_darkened_on_bright_art(self):
        out = sp.typeset(art_image(colour=(250, 250, 250), noise=False), "焚骨宴", genre="悬疑惊悚", **NO_DETECTORS)
        chosen = out["attempts"][-1]
        self.assertGreater(chosen["band_darkening"], 0.55)
        self.assertGreaterEqual(chosen["contrast_ratio"], sp.CONTRAST_MIN)
        self.assertEqual(chosen["problems"], [])

    def test_face_in_bottom_band_moves_title_to_top(self):
        out = sp.typeset(art_image(), "契约婚姻", face_detector=lambda img: [(0, 700, 540, 960)], ocr=None)
        self.assertEqual(out["chosen"], "top")
        self.assertIn("TEXT_OVERLAPS_FACE", out["attempts"][0]["problems"])

    def test_faces_everywhere_fall_back_to_plain_bar(self):
        out = sp.typeset(art_image(), "契约婚姻", face_detector=lambda img: [(0, 0, 540, 960)], ocr=None)
        self.assertEqual(out["chosen"], "bar")
        self.assertEqual(out["attempts"][-1]["font"], "NotoSansSC-Bold-GB2312.ttf")

    def test_ocr_mismatch_tries_next_placement(self):
        reads = iter(["完全不同", "契约婚姻"])
        out = sp.typeset(art_image(), "契约婚姻", face_detector=None, ocr=lambda img: next(reads))
        self.assertEqual(out["chosen"], "top")
        self.assertIn("OCR_READBACK_MISMATCH", out["attempts"][0]["problems"])
        self.assertEqual(out["attempts"][1]["ocr_similarity"], 1.0)

    def test_ocr_tolerates_one_misread_calligraphic_glyph(self):
        self.assertTrue(sp.ocr_readback_ok("焚骨宴", "楚骨宴"))
        self.assertTrue(sp.ocr_readback_ok("焚骨宴", "焚骨宴一场宴席"))
        self.assertFalse(sp.ocr_readback_ok("焚骨宴", "楚"))
        self.assertFalse(sp.ocr_readback_ok("修仙义务教育我最秀", "修仙教"))

    def test_missing_glyph_falls_back_to_a_covering_font(self):
        style = sp.style_for("仙侠", "", "zh")
        self.assertEqual(sp.pick_font(style, "修仙"), style["fonts"][0])
        rare = "鬯"  # GB2312 level 2: not in the display subsets, present in the bundled Noto Sans SC
        self.assertFalse(sp.font_covers(style["fonts"][0], rare))
        self.assertEqual(sp.pick_font(style, "修仙" + rare), sp.FONTS["zh"]["plain"][0])

    def test_output_files_respect_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            art = Path(tmp) / "art.png"
            art.write_bytes(png_bytes(art_image(1152, 2048)))
            meta = sp.render_cover_files(art, Path(tmp), {"title": "焚骨宴", "genre": "悬疑", "language": "zh"},
                                         **NO_DETECTORS)
            self.assertLessEqual(meta["cover"]["bytes"], sp.COVER_MAX_BYTES)
            self.assertEqual(meta["cover"]["size"], [1152, 2048])
            self.assertLessEqual(meta["thumb"]["bytes"], sp.THUMB_MAX_BYTES)
            self.assertEqual(meta["thumb"]["size"][0], 360)
            self.assertTrue((Path(tmp) / "cover.json").is_file())


class FontMapTest(unittest.TestCase):
    def test_genre_and_language_pick_the_slot(self):
        self.assertEqual(sp.style_for("仙侠古装")["slot"], "brush")
        self.assertEqual(sp.style_for("宫斗")["slot"], "brush")
        self.assertEqual(sp.style_for("霸总甜宠")["slot"], "elegant")
        self.assertEqual(sp.style_for("悬疑惊悚")["slot"], "hard")
        self.assertEqual(sp.style_for("都市复仇")["slot"], "hard")
        self.assertEqual(sp.style_for("热门综合")["slot"], "elegant")  # default
        self.assertEqual(sp.style_for("悬疑惊悚", "古装")["slot"], "brush")  # historical first
        en = sp.style_for("Suspense & Horror", language="en")
        self.assertEqual((en["slot"], en["language"], en["fonts"][0][0]), ("hard", "en", "BebasNeue-Regular.ttf"))
        self.assertEqual(sp.style_for("Romance", language="en-US")["fonts"][0][0], "PlayfairDisplay-wght.ttf")
        self.assertEqual(sp.style_for("仙侠")["fonts"][0][0], "MaShanZheng-Regular-GB2312L1.ttf")

    def test_every_bundled_font_and_license_exists(self):
        for lang in sp.FONTS.values():
            for chain in lang.values():
                for spec in chain:
                    self.assertTrue(sp._font_path(spec).is_file(), spec)
        licenses = list((sp.FONT_DIR / "licenses").glob("*-OFL.txt"))
        self.assertEqual(len(licenses), 7)
        for path in licenses:
            self.assertIn("SIL OPEN FONT LICENSE", path.read_text(encoding="utf-8").upper())


class FakeHops:
    """HopsAPI router: upload, create, query.  Records every call; never touches the network."""

    def __init__(self, image: bytes, create: list | None = None, query: list | None = None):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.image = image
        self.create = list(create or [])
        self.query = list(query or [])
        self.n = 0

    def http(self, method, url, *, body=None, headers=None, timeout=0):
        assert "Bearer test-key" == (headers or {}).get("Authorization")
        if url.endswith("/api/file-stream-upload"):
            self.n += 1
            self.calls.append(("upload", url, None))
            return 200, {"data": {"fileUrl": f"https://f/ref{self.n}.png", "mimeType": "image/png"}}, ""
        if url.endswith("/router/task/create"):
            payload = json.loads(body)
            self.calls.append(("create", url, payload))
            if self.create:
                nxt = self.create.pop(0)
                if isinstance(nxt, BaseException):
                    raise nxt
                return nxt
            return 200, {"code": 200, "data": {"task_id": f"tsk_{len(self.calls)}"}}, ""
        if "/router/tasks/" in url:
            self.calls.append(("query", url, None))
            if self.query:
                return self.query.pop(0)
            return 200, {"code": 200, "data": {"status": 2, "cost": 1.7, "results": [{"urls": ["https://r/art.png"]}]}}, ""
        raise AssertionError(url)

    def creates(self):
        return [c for c in self.calls if c[0] == "create"]


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class KeyArtTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.engine, self.runtime = root / "engine", root / "runtime"
        plates = self.engine / "workflow" / "nalu" / "E01" / "identity" / "plates"
        plates.mkdir(parents=True)
        (self.runtime / "runtime").mkdir(parents=True)
        (self.runtime / "briefs").mkdir()
        chars = {}
        for cid, colour in (("CHAR-LIN", (200, 50, 50)), ("CHAR-SU", (50, 200, 50)), ("CHAR-X", (50, 50, 200))):
            head = plates / f"E01_{cid}__FRONT_NEUTRAL_HEADSHOT_a.png"
            plate = plates / f"E01_{cid}_b.png"
            head.write_bytes(png_bytes(art_image(256, 256, colour)))
            plate.write_bytes(png_bytes(art_image(256, 456, colour)))
            chars[cid] = {"registry_id": cid, "canonical_name": cid, "generation_reference_image": str(plate),
                          "canonical_reference_paths": [str(plate), str(head)]}
        (self.runtime / "runtime" / "nalu_character_asset_registry.json").write_text(
            json.dumps({"characters": chars}), encoding="utf-8")
        (self.runtime / "qingshan.json").write_text(json.dumps({"generation": {"paid_requests_enabled": True}}),
                                                    encoding="utf-8")
        self.brief = {"title": "契约婚姻", "genre": "霸总甜宠", "dialogue_language": "zh", "style": "都市",
                      "synopsis": "苏晚与林总签下契约，林总步步紧逼。林总的秘密……",
                      "characters": [{"character_id": "CHAR-SU", "canonical_name": "苏晚"},
                                     {"character_id": "CHAR-X", "canonical_name": "路人"},
                                     {"character_id": "CHAR-LIN", "canonical_name": "林总"}]}
        self.art = png_bytes(art_image(576, 1024))
        self.env = mock.patch.dict(os.environ, {"HOPSAPI_API_KEY": "test-key", "NALU_IMAGE_PROVIDER": "",
                                                "NALU_SERIES_POSTER_ART": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_ensure(self, fake, **kw):
        with mock.patch.object(hops, "_http", side_effect=fake.http), \
                mock.patch.object(hops, "_download_bytes", side_effect=lambda url, timeout=240: fake.image), \
                mock.patch.object(hops.time, "sleep"):
            return sp.ensure_series_cover(self.engine, self.runtime, "E01", self.brief, wait_seconds=0,
                                          **NO_DETECTORS, **kw)

    def store(self):
        return sorted((self.engine / "workflow" / "tasks" / "giggle_submit_transactions" / "E01").glob("SERIES-POSTER-ART__*.json"))

    def test_lead_ranking_and_references(self):
        refs = sp.find_lead_references(self.engine, self.runtime, "E01", self.brief)
        self.assertEqual([(r["character_id"], r["role"]) for r in refs],
                         [("CHAR-LIN", "LEAD"), ("CHAR-LIN", "LEAD"), ("CHAR-SU", "SECOND_LEAD")])
        self.assertIn("FRONT_NEUTRAL_HEADSHOT", Path(refs[0]["path"]).name)
        self.brief["lead_character_id"] = "CHAR-X"
        self.assertEqual(sp.find_lead_references(self.engine, self.runtime, "E01", self.brief)[0]["character_id"], "CHAR-X")

    def test_request_has_no_text_constraint_references_and_transaction(self):
        fake = FakeHops(self.art)
        out = self.run_ensure(fake)
        self.assertEqual(out["status"], "RENDERED", out)
        self.assertEqual(out["art"]["status"], "ART_GENERATED")
        [(_, _, payload)] = fake.creates()
        self.assertEqual((payload["task"], payload["model"]), ("Img2Img", "gpt-image-2"))
        self.assertEqual(len(payload["input"]["images"]), 3)
        self.assertEqual(payload["input"]["resolution"], sp.DEFAULT_ART_SIZE)
        prompt = payload["input"]["prompt"]
        for phrase in ("ABSOLUTELY NO TEXT", "no letters", "no logos", "no watermarks", "bottom 30%",
                       "dark gradient zone", "reference image 1"):
            self.assertIn(phrase, prompt)
        [tx_path] = self.store()
        tx = json.loads(tx_path.read_text(encoding="utf-8"))
        self.assertEqual(tx["state"], "SUBMITTED_TASK_ID_BOUND")
        self.assertEqual(tx["provider"], "hopsapi")
        self.assertEqual(tx["provider_cost_credits"], 1.7)
        self.assertTrue(tx["series_poster"])
        self.assertNotIn("test-key", tx_path.read_text(encoding="utf-8"))
        manifest = json.loads((self.runtime / "series/cover/poster_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "READY")
        self.assertEqual(manifest["cost_credits"], 1.7)
        self.assertEqual(len(manifest["references"]), 3)
        self.assertEqual(manifest["prompt_sha256"], tx["prompt_sha256"])
        for name in ("poster_art.png", "cover.jpg", "cover_thumb.jpg", "cover.json"):
            self.assertTrue((self.runtime / "series/cover" / name).is_file(), name)

    def test_generated_once_per_series(self):
        fake = FakeHops(self.art)
        self.run_ensure(fake)
        again = self.run_ensure(fake)
        self.assertEqual(again["status"], "CURRENT")
        self.brief["episode_title"] = "next"
        self.assertEqual(self.run_ensure(fake)["status"], "CURRENT")
        self.assertEqual(len(fake.creates()), 1)
        # a changed tagline re-typesets for free (no second POST)
        self.brief["poster_tagline"] = "一纸契约"
        out = self.run_ensure(fake)
        self.assertEqual((out["status"], out["art"]["status"]), ("RENDERED", "ART_CACHED"))
        self.assertEqual(len(fake.creates()), 1)

    def test_new_series_archives_the_old_cover(self):
        self.run_ensure(FakeHops(self.art))
        self.brief["title"] = "另一部剧"
        fake = FakeHops(self.art)
        out = self.run_ensure(fake)
        self.assertIn("archived_previous_series", out)
        self.assertEqual(len(fake.creates()), 1)

    def test_uncharged_failure_gets_exactly_one_redo(self):
        fake = FakeHops(self.art, create=[hops.HopsapiHTTPError(400, {"code": 400}, "bad")] * 2)
        first = self.run_ensure(fake)
        self.assertEqual((first["status"], first["art"]["status"]), ("NO_ART", "ART_SUBMIT_DECLINED"))
        second = self.run_ensure(fake)
        self.assertEqual(second["art"]["status"], "ART_SUBMIT_DECLINED")
        self.assertEqual(fake.creates()[1][2]["input"]["resolution"], sp.REDO_ART_SIZE)
        third = self.run_ensure(fake)
        self.assertEqual(third["art"]["status"], "ART_FAILED")
        self.assertEqual(len(fake.creates()), 2)

    def test_terminal_failed_task_then_redo_succeeds(self):
        fake = FakeHops(self.art, query=[(200, {"code": 200, "data": {"status": 3, "error": "Provider error"}}, "")])
        self.assertEqual(self.run_ensure(fake)["art"]["status"], "ART_TASK_FAILED")
        out = self.run_ensure(fake)
        self.assertEqual(out["art"]["status"], "ART_GENERATED")
        self.assertEqual(len(fake.creates()), 2)

    def test_lost_response_is_never_resent(self):
        fake = FakeHops(self.art, create=[OSError("reset")])
        self.assertEqual(self.run_ensure(fake)["art"]["status"], "ART_RESPONSE_LOST")
        self.assertEqual(self.run_ensure(fake)["art"]["status"], "ART_RESPONSE_LOST")
        self.assertEqual(len(fake.creates()), 1)
        [tx] = self.store()
        self.assertEqual(json.loads(tx.read_text())["state"], "RESPONSE_LOST_PENDING_LEDGER_RECONCILIATION")

    def test_pending_task_is_polled_not_reposted(self):
        fake = FakeHops(self.art, query=[(200, {"code": 200, "data": {"status": 1}}, "")])
        self.assertEqual(self.run_ensure(fake)["art"]["status"], "ART_PENDING")
        self.assertEqual(self.run_ensure(fake)["art"]["status"], "ART_GENERATED")
        self.assertEqual(len(fake.creates()), 1)

    def test_no_paid_call_without_the_runtime_paid_lock(self):
        (self.runtime / "qingshan.json").write_text(json.dumps({"generation": {"paid_requests_enabled": False}}))
        fake = FakeHops(self.art)
        out = self.run_ensure(fake)
        self.assertEqual(out["art"], {"status": "ART_NOT_AUTHORIZED", "reason": "PAID_REQUESTS_DISABLED"})
        self.assertEqual(fake.calls, [])
        with mock.patch.dict(os.environ, {"NALU_SERIES_POSTER_ART": "off"}):
            (self.runtime / "qingshan.json").write_text(json.dumps({"generation": {"paid_requests_enabled": True}}))
            self.assertEqual(self.run_ensure(fake)["art"]["reason"], "DISABLED_BY_ENV")
        self.assertEqual(fake.calls, [])

    def test_operator_art_is_adopted_without_a_call(self):
        cover = self.runtime / "series" / "cover"
        cover.mkdir(parents=True)
        (cover / "poster_art.png").write_bytes(self.art)
        fake = FakeHops(self.art)
        out = self.run_ensure(fake, allow_paid=False)
        self.assertEqual((out["status"], out["art"]["status"]), ("RENDERED", "ART_ADOPTED"))
        self.assertEqual(fake.calls, [])


@unittest.skipUnless(HAVE_PIL, "Pillow not installed")
class UseTheCoverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.tmp.name)
        art = self.runtime / "art.png"
        art.write_bytes(png_bytes(art_image()))
        self.meta = sp.render_cover_files(art, sp.cover_dir(self.runtime),
                                          {"title": "Sherlock Holmes: The Blue Carbuncle", "language": "en"},
                                          **NO_DETECTORS)

    def tearDown(self):
        self.tmp.cleanup()

    def test_publisher_prefers_the_series_cover(self):
        import publish_x2creel as px
        with mock.patch.dict(os.environ, {"NALU_RUNTIME_ROOT": str(self.runtime)}), \
                mock.patch.object(px, "cover_from_video", return_value=Path("/frame.jpg")):
            cover, source = px.pick_cover("", Path("/v.mp4"), "Sherlock Holmes: The Blue Carbuncle")
            self.assertEqual((cover.name, source), ("cover.jpg", "SERIES_POSTER"))
            self.assertEqual(px.pick_cover("", Path("/v.mp4"), "Another Series"), (Path("/frame.jpg"), "FRAME_GRAB"))
            self.assertEqual(px.pick_cover("/x.png", Path("/v.mp4"), None)[1], "EXPLICIT")
            (sp.cover_dir(self.runtime) / "cover.jpg").unlink()
            self.assertEqual(px.pick_cover("", Path("/v.mp4"), None)[1], "FRAME_GRAB")

    def test_matrix_publish_uploads_the_series_cover(self):
        import publish_x2c_matrix as mx
        import publish_x2creel as px
        from tools.tests.test_nalu_publish_x2c_matrix import FakeX2C
        fake, puts = FakeX2C(), []
        ep = self.runtime / "deliverables" / "E01"
        ep.mkdir(parents=True)
        (ep / "E01_final_9x16.mp4").write_bytes(b"video")
        (self.runtime / "briefs").mkdir()
        (self.runtime / "briefs" / "E01_PRODUCTION_BRIEF.json").write_text(json.dumps(
            {"title": "Sherlock Holmes: The Blue Carbuncle", "dialogue_language": "en"}))
        env = {"NALU_RUNTIME_ROOT": str(self.runtime), "X2C_API_KEY": "k", "NALU_DEVICE_SN": "sn_1"}
        with mock.patch.dict(os.environ, env), mock.patch.object(mx, "_post", side_effect=fake), \
                mock.patch.object(px, "put_file", side_effect=lambda up, path: puts.append(Path(path))), \
                mock.patch.object(px, "cover_from_video", side_effect=AssertionError("frame grab used")), \
                mock.patch.object(mx, "duration_seconds", return_value=60.0):
            out = mx.cmd_publish(SimpleNamespace(episode="E01", title="", description="", hashtags="", video="",
                                                 cover="", series_key="", lang="", episode_number=None, resend=False))
        self.assertEqual(out["status"], "PUBLISHED", out)
        self.assertEqual(out["cover_source"], "SERIES_POSTER")
        self.assertIn(sp.cover_dir(self.runtime) / "cover.jpg", puts)

    def test_cover_tick_prefers_the_poster_thumb(self):
        import fleet_sync
        posts = []
        cp = SimpleNamespace(roots=lambda: (self.runtime / "engine", self.runtime))
        with mock.patch.object(fleet_sync, "_req", side_effect=lambda m, p, b=None, token="": posts.append(b) or (200, {})), \
                mock.patch.object(fleet_sync, "series_cover", side_effect=AssertionError("frame used")):
            self.assertEqual(fleet_sync.cover_tick(cp, "tok", now=10_000), "UPLOADED_POSTER:200")
            self.assertEqual(fleet_sync.cover_tick(cp, "tok", now=20_000), "UNCHANGED")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["episode"], "SERIES_POSTER")
        self.assertEqual(base64.b64decode(posts[0]["image_b64"]),
                         (sp.cover_dir(self.runtime) / "cover_thumb.jpg").read_bytes())


if __name__ == "__main__":
    unittest.main()
