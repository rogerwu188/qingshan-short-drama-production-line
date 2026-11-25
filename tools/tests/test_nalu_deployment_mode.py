"""skills/nalu-claude-code deployment_mode: single-machine vs fleet deployment (line owner 2026-11-25)."""
from __future__ import annotations

import io
import json
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[2] / "skills/nalu-claude-code/scripts"
sys.path.insert(0, str(SCRIPTS))
import codex_production as cp  # noqa: E402
import deployment_mode as dm  # noqa: E402
import publish_x2c_matrix as mx  # noqa: E402
import publish_x2creel as px  # noqa: E402
import x2c_creative_context as xcc  # noqa: E402

ENV = ("NALU_RUNTIME_ROOT", "NALU_ENGINE_ROOT", "NALU_DEPLOYMENT_MODE", "X2C_API_MODE", "X2C_CREATIVE_CONTEXT",
       "NALU_DEVICE_SN", "X2C_MATRIX_API_URL")


class DeploymentModeTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.get(k) for k in ENV}
        for k in ENV:
            os.environ.pop(k, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.rt = Path(self.tmp.name) / "rt"
        self.rt.mkdir()
        os.environ["NALU_RUNTIME_ROOT"] = str(self.rt)
        os.environ["NALU_ENGINE_ROOT"] = str(Path(self.tmp.name) / "no_engine")

    def tearDown(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def cfg(self, data):
        (self.rt / "qingshan.json").write_text(json.dumps(data), encoding="utf-8")

    # ------------------------------------------------------------ precedence
    def test_default_is_fleet_and_matrix(self):
        self.assertEqual(dm.resolve()["mode"], "fleet")
        self.assertEqual(dm.x2c_api_mode(), "")
        self.assertTrue(mx.matrix_mode())
        self.cfg({"project": {"language": "zh-CN"}})  # a config without the section
        self.assertEqual(dm.mode(), "fleet")
        self.assertTrue(mx.matrix_mode())
        (self.rt / "qingshan.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(dm.mode(), "fleet")
        self.assertTrue(mx.matrix_mode())

    def test_single_in_config_means_open_api(self):
        self.cfg({"deployment": {"mode": "single"}})
        self.assertEqual(dm.resolve()["x2c_api_mode_source"], "single_mode_default")
        self.assertFalse(mx.matrix_mode())
        self.cfg({"deployment": {"mode": "single", "x2c_api_mode": "matrix"}})
        self.assertTrue(mx.matrix_mode())  # explicit config beats the single default
        self.cfg({"deployment": {"mode": "fleet", "x2c_api_mode": "open"}})
        self.assertFalse(mx.matrix_mode())

    def test_env_overrides_config(self):
        self.cfg({"deployment": {"mode": "single", "x2c_api_mode": "open"}})
        os.environ["X2C_API_MODE"] = "matrix"
        self.assertTrue(mx.matrix_mode())
        os.environ.pop("X2C_API_MODE")
        os.environ["NALU_DEPLOYMENT_MODE"] = "fleet"
        self.assertEqual(dm.mode(), "fleet")
        self.assertFalse(mx.matrix_mode())  # x2c_api_mode still from qingshan.json
        self.cfg({"deployment": {"mode": "fleet"}})
        os.environ["NALU_DEPLOYMENT_MODE"] = "single"
        self.assertEqual(dm.resolve()["mode_source"], "env:NALU_DEPLOYMENT_MODE")
        self.assertFalse(mx.matrix_mode())

    # ------------------------------------------------------------ CLI
    def test_cli_set_keeps_other_keys_and_mode_bits(self):
        path = self.rt / "qingshan.json"
        self.cfg({"project": {"language": "en-US"}, "generation": {"paid_requests_enabled": True}})
        os.chmod(path, 0o644)
        with redirect_stdout(io.StringIO()) as buf:
            dm.main(["set", "单机"])
        out = json.loads(buf.getvalue())
        self.assertEqual((out["mode"], out["x2c_api_mode"], out["source_note"]),
                         ("single", "open", dm.SOURCE_REQUIRED_REASON))
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["project"], {"language": "en-US"})
        self.assertEqual(data["deployment"], {"mode": "single", "x2c_api_mode": "open"})
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        with redirect_stdout(io.StringIO()):
            dm.main(["set", "fleet"])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["deployment"], {"mode": "fleet"})
        self.assertTrue(mx.matrix_mode())
        self.assertEqual([p.name for p in self.rt.iterdir()], ["qingshan.json"])  # no temp file left

    def test_cli_new_file_is_600_and_show(self):
        with redirect_stdout(io.StringIO()):
            dm.main(["set", "single", "--x2c-api-mode", "matrix"])
        path = self.rt / "qingshan.json"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        with redirect_stdout(io.StringIO()) as buf:
            dm.main(["show"])
        out = json.loads(buf.getvalue())
        self.assertEqual((out["mode"], out["x2c_api_mode"]), ("single", "matrix"))
        with redirect_stdout(io.StringIO()) as buf:
            dm.main(["mode"])
        self.assertEqual(buf.getvalue().strip(), "single")

    # ------------------------------------------------------------ open mode skips matrix-only features
    def test_open_mode_skips_creative_context_and_matrix_commands(self):
        self.cfg({"deployment": {"mode": "single"}})
        with mock.patch.object(mx, "call", side_effect=AssertionError("no matrix call in open mode")):
            self.assertEqual(xcc.run(None, None)["status"], "SKIPPED")
            self.assertEqual(xcc.after_publish("k", "E01")["status"], "SKIPPED")
            for argv in (["close", "--series", "x"], ["creative-context"], ["list"]):
                with mock.patch.object(sys, "argv", ["publish_x2creel.py", *argv]), \
                        redirect_stdout(io.StringIO()) as buf:
                    self.assertEqual(px.main(), 0)
                self.assertEqual(json.loads(buf.getvalue())["reason"], "X2C_OPEN_API_MODE")

    def test_fleet_mode_creative_context_still_runs(self):
        self.assertNotEqual(xcc.run(None, None)["status"], "SKIPPED")  # NO_PROJECT_YET with an empty state

    # ------------------------------------------------------------ source rule
    def test_single_mode_requires_user_source(self):
        self.assertIsNone(dm.source_check())  # fleet: unchanged
        self.cfg({"deployment": {"mode": "single"}})
        blocked = dm.source_check()
        self.assertEqual((blocked["status"], blocked["reason"]), ("BLOCKED", "SOURCE_REQUIRED_FROM_USER"))
        with mock.patch.object(cp, "launch", side_effect=AssertionError("must not launch")):
            out = cp.start("E01", "派单")
        self.assertEqual((out["status"], out["reason"], out["episode"]), ("BLOCKED", "SOURCE_REQUIRED_FROM_USER", "E01"))
        # a scraped / intaken source without the user's delivered file does not count
        (self.rt / "sources" / "书" / "zh-CN").mkdir(parents=True)
        (self.rt / "sources" / "书" / "zh-CN" / "ch0001.md").write_text("x", encoding="utf-8")
        self.assertIsNotNone(dm.source_check())
        delivered = self.rt / "sources" / "书" / "delivered"
        delivered.mkdir()
        (delivered / "novel.txt").write_text("第一章", encoding="utf-8")
        self.assertIsNone(dm.source_check())
        with mock.patch.object(cp, "launch", return_value={"status": "STARTED"}) as launch, \
                mock.patch.object(cp, "knowledge_guidance", return_value={"section": ""}), \
                mock.patch.object(cp, "craft_standard_section", return_value=""):
            self.assertEqual(cp.start("E01", "派单")["status"], "STARTED")
        prompt = launch.call_args[0][1]
        self.assertIn("单机模式", prompt)
        self.assertIn("SOURCE_REQUIRED_FROM_USER", prompt)
        self.assertIn("genre_lang", prompt)

    def test_fleet_prompt_has_no_single_section(self):
        self.assertEqual(dm.codex_section(), "")
        self.assertEqual(cp.deployment_section(), "")


if __name__ == "__main__":
    unittest.main()
