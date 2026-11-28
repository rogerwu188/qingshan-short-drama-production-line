"""craft_profile (owner 2026-11-23, Bilibili benchmark CHANGE_SPEC WP0): a per-series LEGACY | BILI_V1 switch.

Covers: precedence contract > brief > runtime config > default; unknown values fall back; LEGACY is the default and
forces the sub-switches (bgm_mood_cues, writer_format) off; the helpers other WPs call (is_bili_v1 / enabled /
writer_format / bgm_mood_cues) on a contract, a Ctx, a runtime root and a profile string; the pipeline Ctx property;
imports under both the runtime-tools and the engine-tools roots.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import craft_profile as cp  # noqa: E402  (runtime tools dir)
from tools import craft_profile as cp_shim  # noqa: E402


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class Resolution(unittest.TestCase):
    def test_default_is_legacy(self):
        self.assertEqual(cp.resolve(), "LEGACY")
        self.assertEqual(cp.resolve({"episode": "E01"}, {}, {"project": {}}), "LEGACY")
        self.assertEqual(cp.settings(), {"craft_profile": "LEGACY", "bgm_mood_cues": False,
                                         "writer_format": "CONTRACT_JSON"})
        self.assertFalse(cp.is_bili_v1())
        self.assertFalse(cp.is_bili_v1({}))

    def test_aliases(self):
        self.assertEqual(cp.normalise("bili-v1"), "BILI_V1")
        self.assertEqual(cp.normalise(" BILI_V1 "), "BILI_V1")
        self.assertEqual(cp.normalise("legacy"), "LEGACY")
        self.assertIsNone(cp.normalise("BILI_V2"))
        self.assertIsNone(cp.normalise(None))
        self.assertEqual(cp.normalise_writer_format("screenplay-v1"), "SCREENPLAY_V1")

    def test_unknown_value_falls_back_to_legacy(self):
        self.assertEqual(cp.resolve({"craft_profile": "BILI_V9"}), "LEGACY")
        self.assertEqual(cp.resolve(None, {"craft_profile": 3}, {"project": {"craft_profile": "x"}}), "LEGACY")
        # an unknown value is silent, so a lower source still decides (as render_style)
        self.assertEqual(cp.resolve({"craft_profile": "?"}, None, {"project": {"craft_profile": "BILI_V1"}}),
                         "BILI_V1")

    def test_precedence_contract_brief_config(self):
        bili, legacy = {"craft_profile": "BILI_V1"}, {"craft_profile": "LEGACY"}
        self.assertEqual(cp.resolve(bili, legacy, {"project": legacy}), "BILI_V1")
        self.assertEqual(cp.resolve(legacy, bili, {"project": bili}), "LEGACY")
        self.assertEqual(cp.resolve(None, bili, {"project": legacy}), "BILI_V1")
        self.assertEqual(cp.resolve(None, legacy, {"project": bili}), "LEGACY")
        self.assertEqual(cp.resolve(None, None, {"project": bili}), "BILI_V1")
        self.assertEqual(cp.resolve({"craft": bili}), "BILI_V1")  # craft block form
        self.assertEqual(cp.resolve(None, None, bili), "LEGACY")  # top-level config key is not project.*

    def test_sub_switches_only_under_bili_v1(self):
        flags = {"bgm_mood_cues": True, "writer_format": "SCREENPLAY_V1"}
        self.assertEqual(cp.settings({**flags}), cp.DEFAULTS)
        self.assertFalse(cp.bgm_mood_cues({**flags}))
        self.assertEqual(cp.writer_format({**flags}), "CONTRACT_JSON")
        on = cp.settings({"craft_profile": "BILI_V1", **flags})
        self.assertEqual(on, {"craft_profile": "BILI_V1", "bgm_mood_cues": True, "writer_format": "SCREENPLAY_V1"})
        # each key on its own precedence: profile from config, flags from brief / contract
        mixed = cp.settings({"writer_format": "SCREENPLAY_V1"}, {"bgm_mood_cues": "yes"},
                            {"project": {"craft_profile": "BILI_V1", "bgm_mood_cues": False}})
        self.assertEqual(mixed, {"craft_profile": "BILI_V1", "bgm_mood_cues": True,
                                 "writer_format": "SCREENPLAY_V1"})
        self.assertEqual(cp.settings({"craft_profile": "BILI_V1"}), {
            "craft_profile": "BILI_V1", "bgm_mood_cues": False, "writer_format": "CONTRACT_JSON"})

    def test_enabled(self):
        c = {"craft_profile": "BILI_V1", "bgm_mood_cues": True, "writer_format": "SCREENPLAY_V1"}
        for name in ("BILI_V1", "bgm_mood_cues", "SCREENPLAY_V1"):
            self.assertTrue(cp.enabled(name, c), name)
            self.assertFalse(cp.enabled(name, {}), name)
        self.assertTrue(cp.enabled("LEGACY", {}))
        self.assertFalse(cp.enabled("CONTRACT_JSON", c))
        self.assertFalse(cp.enabled("no_such_switch", c))


class CallSites(unittest.TestCase):
    def test_runtime_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(cp.resolve_runtime("E01", runtime_root=root), "LEGACY")
            _write(root / "qingshan.json", {"project": {"craft_profile": "BILI_V1", "bgm_mood_cues": True}})
            self.assertEqual(cp.resolve_runtime("E01", runtime_root=root), "BILI_V1")
            self.assertTrue(cp.is_bili_v1(root, episode="E01"))
            self.assertTrue(cp.is_bili_v1(None, runtime_root=root))
            self.assertTrue(cp.bgm_mood_cues(root))
            _write(cp.brief_path(root, "E02"), {"craft_profile": "LEGACY"})
            self.assertEqual(cp.resolve_runtime("E02", runtime_root=root), "LEGACY")
            self.assertFalse(cp.is_bili_v1(root, episode="E02"))
            self.assertEqual(cp.resolve_runtime("E02", contract={"craft_profile": "BILI_V1"}, runtime_root=root),
                             "BILI_V1")
            self.assertTrue(cp.is_bili_v1({"craft_profile": "BILI_V1"}, episode="E02", runtime_root=root))
            self.assertFalse(cp.is_bili_v1({}, episode="E02", runtime_root=root))
            self.assertEqual(cp.settings_runtime("E01", runtime_root=root)["bgm_mood_cues"], True)

    def test_contract_alone_never_reads_the_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write(Path(tmp) / "qingshan.json", {"project": {"craft_profile": "BILI_V1"}})
            self.assertFalse(cp.is_bili_v1({"episode": "E01"}))

    def test_ctx_and_strings(self):
        self.assertTrue(cp.is_bili_v1("BILI_V1"))
        self.assertFalse(cp.is_bili_v1("legacy"))
        self.assertTrue(cp.is_bili_v1(SimpleNamespace(craft_profile="BILI_V1")))
        self.assertFalse(cp.is_bili_v1(SimpleNamespace()))  # stage test double without the attribute
        ctx = SimpleNamespace(craft_settings=cp.settings({"craft_profile": "BILI_V1",
                                                          "writer_format": "SCREENPLAY_V1"}))
        self.assertTrue(cp.is_bili_v1(ctx))
        self.assertEqual(cp.writer_format(ctx), "SCREENPLAY_V1")
        self.assertTrue(cp.is_legacy(SimpleNamespace(craft_settings=dict(cp.DEFAULTS))))

    def test_shim_is_the_same_api(self):
        self.assertEqual(sorted(cp_shim.__all__), sorted(cp.__all__))
        self.assertEqual(cp_shim.resolve({"craft_profile": "BILI_V1"}), "BILI_V1")

    def test_pipeline_ctx_property(self):
        import nalu_pipeline as pipe  # noqa: PLC0415
        self.assertEqual(pipe.ctx_craft_profile(SimpleNamespace()), "LEGACY")
        self.assertEqual(pipe.ctx_craft_profile(SimpleNamespace(craft_profile="BILI_V1")), "BILI_V1")
        self.assertEqual(pipe.resolve_craft_settings({"craft_profile": "BILI_V1"}, None)["craft_profile"],
                         "BILI_V1")
        self.assertEqual(pipe.resolve_craft_settings(None, {"project": {"craft_profile": "BILI_V1"}})["craft_profile"],
                         "BILI_V1")
        self.assertEqual(pipe.resolve_craft_settings(None, {}), cp.DEFAULTS)


class ImportRoots(unittest.TestCase):
    """CHANGE_SPEC WP0 acceptance: importable from PACE / PIPE / PRE / nalu_bgm_default (runtime-tools root) and
    from engine tools modules (repo root and flat tools/ root), with the REND try/except pattern."""

    SNIPPET = ("try:\n    from tools import craft_profile as _cp\nexcept ModuleNotFoundError:\n"
               "    import craft_profile as _cp\nprint(_cp.resolve({'craft_profile': 'bili_v1'}))\n")

    def _run(self, path: Path) -> str:
        code = f"import sys; sys.path[:0] = [{str(path)!r}]\n" + self.SNIPPET
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd=str(path),
                             timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def test_both_roots(self):
        for path in (TOOLS, ROOT, ROOT / "tools"):
            self.assertEqual(self._run(path), "BILI_V1", path)


if __name__ == "__main__":
    unittest.main()


class SeriesSwitchCli(unittest.TestCase):
    """craft_profile.py set/show: the deterministic series switch (fleet 2026-11-28, English series 1205)."""

    def test_set_backs_up_and_keeps_other_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / "qingshan.json"
            cfg.write_text(json.dumps({"project": {"language": "en-US", "name": "x"}, "deployment": {"mode": "fleet"}}))
            cfg.chmod(0o640)
            out = cp.write_runtime(root, "bili-v1", "screenplay", True, stamp="T")
            data = json.loads(cfg.read_text())
            self.assertEqual(data["project"], {"language": "en-US", "name": "x", "craft_profile": "BILI_V1",
                                               "writer_format": "SCREENPLAY_V1", "bgm_mood_cues": True})
            self.assertEqual(data["deployment"], {"mode": "fleet"})
            self.assertEqual(cfg.stat().st_mode & 0o777, 0o640)
            backup = root / "qingshan.json.bak-craft-T"
            self.assertEqual(json.loads(backup.read_text())["project"], {"language": "en-US", "name": "x"})
            self.assertEqual(out["settings"], {"craft_profile": "BILI_V1", "bgm_mood_cues": True,
                                               "writer_format": "SCREENPLAY_V1"})
            self.assertTrue(cp.is_bili_v1(root))
            self.assertEqual(cp.writer_format(root), "SCREENPLAY_V1")

    def test_unknown_values_write_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "qingshan.json").write_text('{"project": {}}')
            for args in (("BILI_V9", None), ("BILI_V1", "PROSE")):
                with self.assertRaises(ValueError):
                    cp.write_runtime(root, *args)
            self.assertEqual((root / "qingshan.json").read_text(), '{"project": {}}')
            self.assertEqual(sorted(p.name for p in root.iterdir()), ["qingshan.json"])

    def test_cli_set_then_show(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = TOOLS / "craft_profile.py"
            done = subprocess.run([sys.executable, str(script), "--runtime", tmp, "set", "--profile", "BILI_V1",
                                   "--writer-format", "SCREENPLAY_V1", "--bgm-mood-cues", "on"],
                                  capture_output=True, text=True, check=True)
            self.assertIn("CRAFT_PROFILE: ", done.stdout)
            shown = subprocess.run([sys.executable, str(script), "--runtime", tmp, "show"],
                                   capture_output=True, text=True, check=True)
            self.assertEqual(json.loads(shown.stdout)["settings"],
                             {"craft_profile": "BILI_V1", "bgm_mood_cues": True, "writer_format": "SCREENPLAY_V1"})
            bad = subprocess.run([sys.executable, str(script), "--runtime", tmp, "set", "--profile", "BILI_V1",
                                  "--bgm-mood-cues", "maybe"], capture_output=True, text=True)
            self.assertEqual(bad.returncode, 2)
