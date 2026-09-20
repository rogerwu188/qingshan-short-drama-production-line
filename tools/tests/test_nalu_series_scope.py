"""nalu_series_scope: the default scope is the historical NALU-YEWUJIANG layout; a foreign scope
(E59 on its own runtime root) must declare every registry path and never fall back to the default."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"


def load(runtime_root: str):
    for name in ("nalu_paths", "nalu_series_scope"):
        sys.modules.pop(name, None)
    sys.path.insert(0, str(TOOLS))
    spec = importlib.util.spec_from_file_location("nalu_series_scope", TOOLS / "nalu_series_scope.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["nalu_series_scope"] = mod
    # Both modules resolve their roots at import time.  Keep those environment
    # values scoped to the import so this suite cannot poison later portable
    # tests that deliberately exercise a different temporary engine root.
    with patch.dict(os.environ, {
        "NALU_RUNTIME_ROOT": runtime_root,
        "NALU_ENGINE_ROOT": str(ROOT),
    }):
        spec.loader.exec_module(mod)
    return mod


class SeriesScope(unittest.TestCase):
    def test_current_portable_never_falls_back_to_historical_default(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"NALU_POLICY_PROFILE": "CURRENT_PORTABLE"},
        ):
            mod = load(tmp)
            with self.assertRaisesRegex(
                SystemExit, "SERIES_SCOPES_CONFIG_REQUIRED_CURRENT_PORTABLE"
            ):
                mod.resolve_scope("E01")

    def test_default_scope_is_historical_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            mod = load(tmp)
            scope = mod.resolve_scope("E01")
            self.assertTrue(scope["is_default"])
            self.assertEqual(scope["asset_library"], Path(tmp, "runtime/asset_library.json").resolve())
            self.assertEqual(scope["voice_registry"], Path(tmp, "runtime/voice_registry.json").resolve())
            self.assertTrue(str(scope["lexicon"]).endswith("configs/LEXICON_yewujiang_v1.json"))
            self.assertIsNone(scope["charter"])

    def test_foreign_scope_must_declare_every_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp, "runtime"); cfg.mkdir()
            (cfg / "series_scopes.json").write_text(json.dumps({
                "schema": "nalu.series_scopes.v1", "default_scope": "NALU-YEWUJIANG",
                "episodes": {"E59": "OTHER"}, "scopes": {"OTHER": {"asset_library": "x/asset_library.json"}}}))
            mod = load(tmp)
            with self.assertRaises(SystemExit):
                mod.resolve_scope("E59")
            self.assertTrue(mod.resolve_scope("E01")["is_default"])

    def test_foreign_scope_resolves_inside_its_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp, "runtime"); cfg.mkdir()
            paths = {k: f"series/x/{k}.json" for k in ("asset_library", "asset_library_seed", "voice_registry", "voice_catalog",
                                                          "voice_cast", "entity_registry", "agentcut_voice_policy", "character_registry")}
            paths.update({"series_root": "series/x", "character_sources": "series/x/sources", "voice_refs": "series/x/refs",
                          "lexicon": "tools:configs/LEXICON_portable_template_v1.json", "charter": "series/x/AUTHORITY.md", "series_id": "X-LINE"})
            (cfg / "series_scopes.json").write_text(json.dumps({"schema": "nalu.series_scopes.v1", "default_scope": "NALU-YEWUJIANG",
                                                                 "episodes": {"E59": "X"}, "scopes": {"X": paths}}))
            mod = load(tmp)
            scope = mod.resolve_scope("E59")
            self.assertFalse(scope["is_default"])
            self.assertEqual(scope["series_id"], "X-LINE")
            for key in ("asset_library", "voice_registry", "character_sources", "charter"):
                self.assertTrue(str(scope[key]).startswith(str(Path(tmp).resolve())), key)
            self.assertTrue(scope["lexicon"].is_file())

    def test_explicit_scope_selects_new_series_with_reused_episode_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = Path(tmp, "runtime"); cfg.mkdir()
            paths = {k: f"series/fbsd/{k}.json" for k in (
                "asset_library", "asset_library_seed", "voice_registry", "voice_catalog",
                "voice_cast", "entity_registry", "agentcut_voice_policy", "character_registry",
            )}
            paths.update({
                "series_root": "series/fbsd",
                "character_sources": "series/fbsd/character_sources",
                "voice_refs": "series/fbsd/voice_refs",
                "lexicon": "tools:configs/LEXICON_portable_template_v1.json",
                "charter": None,
                "series_id": "FOBENSHIDAO",
            })
            (cfg / "series_scopes.json").write_text(json.dumps({
                "schema": "nalu.series_scopes.v1",
                "default_scope": "NALU-YEWUJIANG",
                "episodes": {},
                "scopes": {"FOBENSHIDAO": paths},
            }))
            with patch.dict(os.environ, {"NALU_SERIES_SCOPE_ID": "FOBENSHIDAO"}):
                mod = load(tmp)
                scope = mod.resolve_scope("E01")
            self.assertEqual(scope["scope_id"], "FOBENSHIDAO")
            self.assertFalse(scope["is_default"])
            self.assertIn("series/fbsd", str(scope["character_sources"]))


if __name__ == "__main__":
    unittest.main()
