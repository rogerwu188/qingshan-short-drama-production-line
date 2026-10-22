"""Line owner 2026-10-22 packaging decisions: end card (A), opening title (B), tail ad default (C),
background music default ON (D).  Real ffmpeg where media is rendered; paid/network calls are mocked."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
NALU_TOOLS = REPO / "lines/nalu/runtime/tools"
SCRIPTS = REPO / "skills/nalu-claude-code/scripts"
for _p in (str(NALU_TOOLS), str(SCRIPTS), str(REPO / "tools")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import make_endcard  # noqa: E402
import nalu_bgm_default as bgm_default  # noqa: E402
import nalu_media_tools as media  # noqa: E402
import nalu_opening_title as opening  # noqa: E402
import nalu_tail_ad_opt_in as opt_in  # noqa: E402
import publish_x2creel as px  # noqa: E402

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def cjk_font_available() -> bool:
    try:
        media.resolve_cjk_font()
        return True
    except media.MediaToolBlocked:
        return False


def text_columns(png: Path, background: tuple[int, int, int], threshold: int = 40) -> list[int]:
    from PIL import Image

    image = Image.open(png).convert("RGB")
    width, height = image.size
    pixels = image.load()
    cols = []
    for x in range(width):
        for y in range(0, height, 2):
            r, g, b = pixels[x, y]
            if abs(r - background[0]) + abs(g - background[1]) + abs(b - background[2]) > threshold:
                cols.append(x)
                break
    return cols


def make_clip(path: Path, seconds: float = 4.0) -> None:
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=0x203040:s=720x1280:r=24:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=f=440:d={seconds}:sample_rate=48000",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)


def probe_duration(path: Path) -> float:
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def audio_md5(path: Path) -> str:
    out = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-map", "0:a", "-c", "copy", "-f", "md5", "-"],
                         capture_output=True, text=True, check=True).stdout
    return out.strip()


def frame(path: Path, ts: float, out: Path) -> Path:
    subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", str(ts), "-i", str(path), "-frames:v", "1", str(out)],
                   check=True)
    return out


# --------------------------------------------------------------------------------------- A. end card
@unittest.skipUnless(FFMPEG, "ffmpeg required")
class EndCardTests(unittest.TestCase):
    LONG_EN = "EPISODE 01 · The Arbiter Does Not Dream Of Electric Sheep Tonight"
    LONG_ZH = "第一集 · 仲裁者不会做梦而且这个集名真的非常非常长"

    def render(self, language: str, title: str, subtitle: str) -> Path:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, True)
        make_endcard.main(["--runtime-root", str(tmp), "--title", title, "--subtitle", subtitle,
                           "--language", language])
        self.assertTrue((tmp / "brand/NALU_MOTION_endcard_3s_9x16.mp4").is_file())
        return tmp / "brand/endcard_9x16.png"

    def assert_inside_margins(self, png: Path) -> None:
        cols = text_columns(png, (14, 12, 10))
        self.assertTrue(cols, "no text drawn")
        margin = int(make_endcard.W * 0.05)
        self.assertGreaterEqual(min(cols), margin)
        self.assertLess(max(cols), make_endcard.W - margin)

    def test_english_card_fits_and_needs_no_cjk_font(self) -> None:
        with mock.patch.object(make_endcard, "CANDIDATES", []), \
                mock.patch.dict(os.environ, {"QINGSHAN_CJK_FONT": ""}):
            png = self.render("en", "Twelve Gazes", self.LONG_EN)
        self.assert_inside_margins(png)
        self.assertEqual(make_endcard.TAGLINE["en"], "TO BE CONTINUED")

    def test_english_e01_subtitle_fits(self) -> None:
        self.assert_inside_margins(self.render("en", "Twelve Gazes", "EPISODE 01 · The Arbiter Does Not Dream"))

    @unittest.skipUnless(cjk_font_available() or any(Path(p).is_file() for p in make_endcard.CANDIDATES),
                         "CJK font required")
    def test_chinese_card_fits(self) -> None:
        self.assert_inside_margins(self.render("zh", "十二道凝视之长长长长长长剧名", self.LONG_ZH))

    def test_fit_lines_wraps_when_shrinking_is_not_enough(self) -> None:
        from PIL import Image, ImageDraw

        font = make_endcard.resolve_font("en")
        draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        f, size, lines = make_endcard.fit_lines(draw, self.LONG_EN, font, 40, 28, "en")
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(draw.textlength(line, font=f) <= make_endcard.MAX_TEXT_WIDTH for line in lines))


# ----------------------------------------------------------------------------------- B. opening title
class OpeningTitleTextTests(unittest.TestCase):
    def test_episode_line_by_language(self) -> None:
        self.assertEqual(opening.title_lines({"title": "Twelve Gazes"}, "E01", "en"), ("Twelve Gazes", "EPISODE 01"))
        self.assertEqual(opening.title_lines({"title": "青灯巷"}, "E12", "zh"), ("青灯巷", "第十二集"))
        self.assertEqual(opening.title_lines({"title": "T", "episode_title": "The Arbiter"}, "E01", "en")[1],
                         "EPISODE 01 · The Arbiter")

    def test_no_brief_title_is_skipped_with_reason(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = opening.apply_opening_title(runtime_root=Path(td), episode="E01", language="en",
                                              source=Path(td) / "missing.mp4", out=Path(td) / "o.mp4")
        self.assertEqual(out["status"], "SKIPPED")
        self.assertTrue(out["reason"].startswith("NO_BRIEF_TITLE:"))


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg/ffprobe required")
class OpeningTitleRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = self.tmp / "src.mp4"
        make_clip(self.src)
        (self.tmp / "briefs").mkdir()

    def run_title(self, language: str, brief: dict) -> dict:
        (self.tmp / "briefs/E01_PRODUCTION_BRIEF.json").write_text(json.dumps(brief, ensure_ascii=False),
                                                                    encoding="utf-8")
        out = self.tmp / f"titled_{language}.mp4"
        info = opening.apply_opening_title(runtime_root=self.tmp, episode="E01", language=language,
                                           source=self.src, out=out)
        self.assertEqual(info["status"], "APPLIED", info)
        self.assertAlmostEqual(probe_duration(out), probe_duration(self.src), places=2)
        self.assertEqual(audio_md5(out), audio_md5(self.src))  # audio stream copy
        self.assertLessEqual(info["widest_line_px"], info["max_width_px"])
        bg = (0x20, 0x30, 0x40)
        during = text_columns(frame(out, 1.25, self.tmp / f"{language}_during.png"), bg, threshold=90)
        after = text_columns(frame(out, 3.5, self.tmp / f"{language}_after.png"), bg, threshold=90)
        self.assertTrue(during, "title not visible at 1.25 s")
        self.assertEqual(after, [], "title still visible after 2.5 s")
        return info

    def test_english_overlay(self) -> None:
        info = self.run_title("en", {"title": "Twelve Gazes", "episode_title": "The Arbiter Does Not Dream"})
        self.assertEqual(info["episode_line"], "EPISODE 01 · The Arbiter Does Not Dream")

    @unittest.skipUnless(cjk_font_available(), "CJK font required")
    def test_chinese_overlay(self) -> None:
        info = self.run_title("zh", {"title": "青灯巷"})
        self.assertEqual(info["episode_line"], "第一集")


class PipelineOpeningTitleTests(unittest.TestCase):
    def test_s7_opening_title_skips_without_blocking(self) -> None:
        pipeline = importlib.import_module("nalu_pipeline")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            class P:
                assembly = root / "assembly"

            class Ctx:
                episode = "E01"
                language = "en"
                p = P()
                said: list[str] = []

                def say(self, line: str) -> None:
                    self.said.append(line)

            class Res:
                details: dict = {}

            res = Res()
            picture = root / "subbed.mp4"
            with mock.patch.object(pipeline._np, "RUNTIME_ROOT", root):
                out = pipeline.s7_opening_title(Ctx(), res, picture)
            self.assertEqual(out, picture)
            self.assertEqual(res.details["opening_title"]["status"], "SKIPPED")


# ------------------------------------------------------------------------------------------ C. tail ad
class TailAdPolicyTests(unittest.TestCase):
    DEFAULT = REPO / "configs/ads/AD_POLICY_DEFAULT.json"

    def test_repo_default_policy_by_language(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            missing_runtime_policy = Path(td) / "policy.json"
            policy = opt_in._load_policy(missing_runtime_policy, self.DEFAULT)
        self.assertIs(policy["ask"], False)
        self.assertEqual(opt_in.policy_default(policy, "zh"), "INBOX:giggle_tail5s")
        self.assertEqual(opt_in.policy_default(policy, "en"), "INBOX:giggle_tail5s_en")

    def test_runtime_policy_overrides_repo_default(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            runtime_policy = Path(td) / "policy.json"
            runtime_policy.write_text(json.dumps({"ask": False, "default": "NONE"}), encoding="utf-8")
            policy = opt_in._load_policy(runtime_policy, self.DEFAULT)
        self.assertEqual(opt_in.policy_default(policy, "en"), "NONE")

    def test_run_opt_in_uses_language_default(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            manifest = root / "E01_manifest_v1.json"
            manifest.write_text("{}", encoding="utf-8")
            decision = opt_in.run_opt_in("E01", prompts_dir=root, answer_dir=root, policy_path=root / "policy.json",
                                         ledger_path=root / "ledger.json", manifest_path=manifest, say=lambda _l: None,
                                         language="en", default_policy_path=self.DEFAULT)
            self.assertEqual(decision["answer"], "INBOX:giggle_tail5s_en")
            self.assertEqual(json.loads(manifest.read_text())["ad_slot"]["sku"], "giggle_tail5s_en")

    def test_missing_or_defaulted_decision_uses_policy_default_at_s7(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            policy = Path(td) / "policy.json"
            none = opt_in.default_decision_at_s7(None, policy_path=policy, language="zh",
                                                 default_policy_path=self.DEFAULT)
            self.assertEqual(none["answer"], "INBOX:giggle_tail5s")
            old_default = opt_in.default_decision_at_s7({"answer": "NONE", "reason": "TIMEOUT_DEFAULT"},
                                                        policy_path=policy, language="en",
                                                        default_policy_path=self.DEFAULT)
            self.assertEqual(old_default["answer"], "INBOX:giggle_tail5s_en")
            explicit = {"answer": "NONE", "reason": "ANSWERED"}
            self.assertEqual(opt_in.default_decision_at_s7(explicit, policy_path=policy, language="en",
                                                           default_policy_path=self.DEFAULT), explicit)


class TailAdPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pipeline = importlib.import_module("nalu_pipeline")
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        ads = self.tmp / "ads"
        self.repo_assets = self.tmp / "repo_assets"
        self.repo_assets.mkdir()
        self.patches = [
            mock.patch.object(self.pipeline, "ADS_INBOX", ads / "inbox"),
            mock.patch.object(self.pipeline, "ADS_PROMPTS", ads / "prompts"),
            mock.patch.object(self.pipeline, "ADS_POLICY", ads / "policy.json"),
            mock.patch.object(self.pipeline, "ADS_PACKAGED", ads / "packaged"),
            mock.patch.object(self.pipeline, "ADS_TRANSACTIONS", ads / "transactions"),
            mock.patch.object(self.pipeline, "ADS_REPO_ASSETS", self.repo_assets),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.runs: list[list[str]] = []
        tmp = self.tmp
        runs = self.runs

        class P:
            scope = {"scope_id": "S"}
            final_mp4 = tmp / "E01_final_9x16.mp4"
            ad_tail_video = tmp / "E01_final_9x16_AD.mp4"
            ad_tail_qa_report = tmp / "E01_AD_TAIL_QA.json"

        class Ctx:
            episode = "E01"
            language = "en"
            p = P()
            state: dict = {}
            paid_enabled = False

            def say(self, _line: str) -> None:
                pass

            def save_state(self) -> None:
                pass

            def run(self, argv, *, name, **_kw):
                runs.append([str(a) for a in argv])
                return {"name": name, "exit_code": 2}

        class Res:
            steps: list = []
            receipts: list = []

        self.ctx, self.res = Ctx(), Res()

    def test_missing_asset_is_recorded_and_never_blocks(self) -> None:
        out = self.pipeline.s7_tail_ad(self.ctx, self.res, endcard_seconds=3.0)
        self.assertEqual(out["status"], "SKIPPED")
        self.assertEqual(out["reason"], "AD_ASSET_MISSING:giggle_tail5s_en")
        self.assertEqual(self.ctx.state["tail_ad_opt_in"]["answer"], "INBOX:giggle_tail5s_en")
        self.assertEqual(self.runs, [])

    def test_repo_asset_is_packaged_with_english_language(self) -> None:
        (self.repo_assets / "giggle_tail5s_en.mp4").write_bytes(b"ad")
        out = self.pipeline.s7_tail_ad(self.ctx, self.res, endcard_seconds=3.0)
        self.assertEqual(out["reason"], "PACKAGE_QA_FAIL")
        package = self.runs[0]
        self.assertIn(str(self.repo_assets / "giggle_tail5s_en.mp4"), package)
        self.assertEqual(package[package.index("--language") + 1], "en")


class AdTailPackageLanguageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pkg = importlib.import_module("ad_tail_package")
        self.slot = json.loads((REPO / "configs/AD_SLOT_CONTRACT_V1.json").read_text(encoding="utf-8"))

    def test_label_by_language(self) -> None:
        self.assertEqual(self.pkg.label_text(self.slot, "en"), "Ad")
        self.assertEqual(self.pkg.label_text(self.slot, "zh"), "广告")
        self.assertEqual(self.slot["spoken_words_max_en"], 12)

    def test_english_spoken_words_cap(self) -> None:
        twelve = "Try Giggle today and make your own drama in minutes with friends"
        with mock.patch.object(self.pkg, "_transcribe", return_value=twelve):
            ok = self.pkg.check_spoken_content(Path("x.mp4"), self.slot, None, language="en")
        self.assertEqual((ok["status"], ok["spoken_words"]), ("PASS", 12))
        with mock.patch.object(self.pkg, "_transcribe", return_value=twelve + " now"):
            over = self.pkg.check_spoken_content(Path("x.mp4"), self.slot, None, language="en")
        self.assertEqual(over["failures"], ["SPOKEN_WORDS_OVER_CAP:13>12"])

    def test_english_cta_spoken_still_fails_closed(self) -> None:
        with mock.patch.object(self.pkg, "_transcribe", return_value="visit giggle.ai now"):
            out = self.pkg.check_spoken_content(Path("x.mp4"), self.slot, "giggle.ai", language="en")
        self.assertIn("CTA_URL_SPOKEN_MUST_BE_CAPTION_ONLY", out["failures"])

    def test_chinese_rule_unchanged(self) -> None:
        with mock.patch.object(self.pkg, "_transcribe", return_value="这是一个非常非常非常非常非常非常长的广告口播内容"):
            out = self.pkg.check_spoken_content(Path("x.mp4"), self.slot, None)
        self.assertEqual(out["status"], "FAIL")
        self.assertTrue(out["failures"][0].startswith("SPOKEN_CHARS_OVER_CAP:"))

    def test_english_badge_renders_without_cjk_font(self) -> None:
        def no_cjk():
            raise media.MediaToolBlocked("BLOCKED_CJK_FONT:test")

        with tempfile.TemporaryDirectory() as td, mock.patch.object(self.pkg, "resolve_cjk_font", no_cjk):
            png = self.pkg._render_badge_png("Ad", Path(td) / "badge.png", "en")
            self.assertTrue(png.is_file())


class PublishAdVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"NALU_RUNTIME_ROOT": str(root), "X2C_API_KEY": "x2c_sk_test"})
        self.env.start()
        self.folder = root / "deliverables/E01"
        self.folder.mkdir(parents=True)
        self.final = self.folder / "E01_final_9x16.mp4"
        self.final.write_bytes(b"final")
        (root / "cover.jpg").write_bytes(b"jpg")
        self.cover = str(root / "cover.jpg")
        self.puts: list[str] = []

        def fake_call(action, **payload):
            if action == "distribution/upload-url":
                return {"uploads": [{"file_type": f["file_type"], "upload_url": "u/" + f["file_name"],
                                     "public_url": "p/" + f["file_name"], "upload_headers": {}}
                                    for f in payload["files"]]}
            if action == "distribution/categories":
                return {"categories": [{"id": "c" * 36, "name": "Fantasy"}]}
            if action == "distribution/publish":
                return {"project_id": "proj", "status": "pending_review", "episodes": [{"episode_number": 1}]}
            raise AssertionError(action)

        self.saved = (px.call, px.put_file)
        px.call = fake_call
        px.put_file = lambda upload, path: self.puts.append(str(path))

    def tearDown(self) -> None:
        px.call, px.put_file = self.saved
        self.env.stop()
        self.tmp.cleanup()

    def publish(self):
        return px.cmd_publish(argparse.Namespace(episode="E01", title="Twelve Gazes", description="d",
                                                 category="Fantasy", lang="en", video="", cover=self.cover))

    def test_ad_version_is_published_when_present(self) -> None:
        ad = self.folder / "E01_final_9x16_AD.mp4"
        ad.write_bytes(b"final+ad")
        out = self.publish()
        self.assertEqual(out["status"], "PUBLISHED")
        self.assertEqual(out["published_variant"], "AD")
        self.assertEqual(out["published_video"], str(ad))
        self.assertIn(str(ad), self.puts)
        self.assertEqual(px.load_state()["episodes"]["E01"]["published_variant"], "AD")

    def test_final_is_published_without_ad(self) -> None:
        out = self.publish()
        self.assertEqual((out["published_variant"], out["published_video"]), ("FINAL", str(self.final)))

    def test_stale_ad_older_than_final_is_not_sent(self) -> None:
        ad = self.folder / "E01_final_9x16_AD.mp4"
        ad.write_bytes(b"old ad")
        os.utime(ad, (1, 1))
        self.assertEqual(px.default_video("E01"), (self.final, "FINAL"))

    def test_episode_sent_before_its_ad_existed_is_not_resent(self) -> None:
        self.publish()
        (self.folder / "E01_final_9x16_AD.mp4").write_bytes(b"final+ad")
        self.assertEqual(self.publish()["status"], "ALREADY_PUBLISHED")


# -------------------------------------------------------------------------------------------- D. BGM
def contract(bgm=None, *, omit=False) -> dict:
    shots = [{"shot_id": f"E01-S0{s}-0{i}", "scene_id": f"E01-S0{s}", "target_seconds": sec}
             for s, i, sec in ((1, 1, 3.5), (1, 2, 3.5), (2, 1, 4.0), (2, 2, 4.0), (2, 3, 3.5), (2, 4, 4.5))]
    payload = {"episode": "E01", "shots": shots, "audio_contract": {}}
    if not omit:
        payload["audio_contract"]["bgm"] = bgm
    return payload


class BgmDefaultTests(unittest.TestCase):
    def test_no_bgm_and_omission_get_default_selective(self) -> None:
        for c in (contract({"mode": "NO_BGM", "declaration": "本集只用原生环境声与对白"}), contract(omit=True),
                  contract("NO_BGM"), contract({"mode": None, "used": False})):
            decision = bgm_default.resolve(c)
            self.assertEqual(decision["source"], "LINE_DEFAULT", c["audio_contract"])
            self.assertEqual(decision["declaration"]["mode"], "SELECTIVE_NARRATIVE_CUES")
            cue = decision["declaration"]["cues"][0]
            self.assertEqual(cue["shots"], ["E01-S02-02", "E01-S02-03", "E01-S02-04"])
            covered = 4.0 + 3.5 + 4.5
            self.assertLessEqual(covered / 23.0, 0.85)
            self.assertGreaterEqual(23.0 - covered, 8.0)

    def test_explicit_none_is_respected(self) -> None:
        for bgm in ("NONE", "NONE_WHOLE_EPISODE", {"mode": "NONE"}, {"mode": "NO_BGM", "opt_out": True}):
            self.assertEqual(bgm_default.resolve(contract(bgm))["source"], "AUTHORED_OPT_OUT", bgm)
            self.assertIsNone(bgm_default.effective_contract(contract(bgm)))

    def test_authored_selective_is_unchanged(self) -> None:
        authored = {"mode": "SELECTIVE", "cues": [{"cue_id": "X", "shots": ["E01-S01-01"],
                                                   "narrative_function": "DREAD", "brief": "strings"}]}
        self.assertEqual(bgm_default.resolve(contract(authored)), {"source": "AUTHORED", "declaration": authored})

    def test_too_short_episode_has_no_default(self) -> None:
        short = {"episode": "E01", "shots": [{"shot_id": "A", "scene_id": "S", "target_seconds": 6}],
                 "audio_contract": {"bgm": "NO_BGM"}}
        self.assertEqual(bgm_default.resolve(short)["source"], "DEFAULT_NOT_APPLICABLE")

    def test_derived_contract_binds_selective_profile_and_source_plan(self) -> None:
        from audio_profile_binding import compile_audio_profile_binding

        sbgm = importlib.import_module("nalu_selective_bgm")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sealed = root / "E01_GENERATION_CONTRACT_v1.json"
            sealed.write_text(json.dumps(contract({"mode": "NO_BGM"}), ensure_ascii=False), encoding="utf-8")
            before = sealed.read_bytes()
            info = bgm_default.write_effective_contract(sealed, root / "bgm/E01_DEFAULT.json")
            self.assertEqual(sealed.read_bytes(), before)  # the writer-sealed contract is never touched
            derived = Path(info["contract"])
            first_sha = derived.read_bytes()
            bgm_default.write_effective_contract(sealed, derived)
            self.assertEqual(derived.read_bytes(), first_sha)  # byte-stable across S6/S7 re-entry
            payload = json.loads(derived.read_text(encoding="utf-8"))
            binding = compile_audio_profile_binding(payload, contract_path=derived)
            self.assertEqual(binding["resolved_audio_profile_id"], "NATIVE_MULTIMODAL_SELECTIVE_BGM")
            plan = sbgm._source_plan_payload(sbgm.Paths("E01", contract=derived, work=root / "work"), "E01")
            self.assertEqual(plan["planned_credits"], 8)
            self.assertEqual(plan["cues"][0]["volume"], 0.14)       # tool defaults, not changed here
            self.assertEqual(plan["cues"][0]["dialogue_duck_db"], -8.0)
            opted_out = root / "none.json"
            opted_out.write_text(json.dumps(contract("NONE")), encoding="utf-8")
            self.assertEqual(bgm_default.write_effective_contract(opted_out, root / "x.json")["contract"],
                             str(opted_out))

    def test_credit_reconciliation_reuse_and_best_effort_without_key(self) -> None:
        pipeline = importlib.import_module("nalu_pipeline")
        with tempfile.TemporaryDirectory() as td:
            tx_dir = Path(td)

            class Ctx:
                episode = "E01"

                def run(self, *_a, **_k):  # pragma: no cover - must not be called without a key
                    raise AssertionError("reconcile must not run without GIGGLE_API_KEY")

            with mock.patch.object(pipeline, "selective_bgm_transaction_dir", lambda _ctx: tx_dir), \
                    mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("GIGGLE_API_KEY", None)
                self.assertFalse(pipeline.bgm_credit_reconciled(Ctx()))
                (tx_dir / "k.json").write_text(json.dumps({"state": "TERMINAL_COMPLETED", "task_id": "t"}))
                self.assertEqual(pipeline.s6_bgm_reconcile_best_effort(Ctx(), None, [])["status"], "SKIPPED_NO_KEY")
                (tx_dir / "k.json").write_text(json.dumps({
                    "state": "TERMINAL_COMPLETED", "task_id": "t",
                    "credit": {"statement_status": "PASS_WINDOW_ISOLATED_LEDGER_NET"}}))
                self.assertTrue(pipeline.bgm_credit_reconciled(Ctx()))
                self.assertEqual(pipeline.s6_bgm_reconcile_best_effort(Ctx(), None, [])["status"],
                                 "ALREADY_RECONCILED")

    def test_pipeline_s6_runs_source_plan_for_default_and_s7_falls_back_without_it(self) -> None:
        pipeline = importlib.import_module("nalu_pipeline")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sealed = root / "E01_GENERATION_CONTRACT_v1.json"
            sealed.write_text(json.dumps(contract({"mode": "NO_BGM"})), encoding="utf-8")
            calls: list[list[str]] = []

            class P:
                scope = {"scope_id": "S"}
                assembly = root / "assembly"
                grouping_plan = root / "grouping.json"
                agentcut_project = root / "project.json"

            P.contract = sealed

            class Ctx:
                episode = "E01"
                p = P()

                def run(self, argv, *, name, **_kw):
                    calls.append([str(a) for a in argv])
                    return {"name": name, "exit_code": 1}

            class Res:
                steps: list = []
                details: dict = {}

            with mock.patch.object(pipeline, "bgm_work_dir", lambda _ctx: root / "bgm"):
                out = pipeline.s6_selective_bgm_sources(Ctx(), Res())
                self.assertEqual(out["blocker"], "SELECTIVE_BGM_SOURCE_PLAN_FAILED")  # the paid path was entered
                derived = calls[0][calls[0].index("--contract") + 1]
                self.assertTrue(derived.endswith("E01_GENERATION_CONTRACT_BGM_DEFAULT.json"))
                s7 = pipeline.s7_bgm_contract(Ctx())
                self.assertEqual(s7["source"], "LINE_DEFAULT_SKIPPED")      # S6 produced no source plan
                self.assertEqual(s7["contract"], str(sealed))
                (root / "bgm/E01_BGM_SOURCE_PLAN.json").write_text(json.dumps(
                    {"contract_sha256": pipeline.sha256_file(Path(derived))}), encoding="utf-8")
                self.assertEqual(pipeline.s7_bgm_contract(Ctx())["contract"], derived)

            sealed.write_text(json.dumps(contract("NONE")), encoding="utf-8")
            calls.clear()
            with mock.patch.object(pipeline, "bgm_work_dir", lambda _ctx: root / "bgm"):
                out = pipeline.s6_selective_bgm_sources(Ctx(), Res())
            self.assertEqual(out["status"], "NOT_APPLICABLE")
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
