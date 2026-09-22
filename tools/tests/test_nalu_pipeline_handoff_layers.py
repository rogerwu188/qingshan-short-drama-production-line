"""nalu_pipeline resolves the four layers from a SEALED writer handoff before the state cache."""
from __future__ import annotations

import importlib
import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"


class SealedHandoffLayersTest(unittest.TestCase):
    def test_sealed_handoff_paths_are_used(self) -> None:
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "rt"
            layer_dir = runtime / "writer_layers" / "SCOPE-X" / "E01"
            layer_dir.mkdir(parents=True)
            paths = {}
            for key, name in (("narrative_canonical", "E01_NARRATIVE_CANONICAL_v3.md"),
                              ("directing_script", "E01_DIRECTING_SCRIPT_v3.md"),
                              ("generation_contract", "E01_GENERATION_CONTRACT_v3.json"),
                              ("writer_manifest", "E01_manifest_v3.json")):
                (layer_dir / name).write_text("x", encoding="utf-8")
                paths[key] = {"path": str(layer_dir / name), "sha256": "0"}
            (layer_dir / "ACTIVE_WRITER_HANDOFF.json").write_text(
                json.dumps({"status": "SEALED", "episode": "E01", "layers": paths}), encoding="utf-8")
            old = os.environ.get("NALU_RUNTIME_ROOT")
            os.environ["NALU_RUNTIME_ROOT"] = str(runtime)
            sys.path.insert(0, str(TOOLS))
            try:
                for name in ("nalu_paths", "nalu_pipeline"):
                    sys.modules.pop(name, None)
                mod = importlib.import_module("nalu_pipeline")
                mod.RUNTIME = runtime
                out = mod.sealed_handoff_layers("E01", "SCOPE-X")
                self.assertIsNotNone(out)
                self.assertEqual(out["generation_contract"].name, "E01_GENERATION_CONTRACT_v3.json")
                self.assertIsNone(mod.sealed_handoff_layers("E01", "OTHER"))
                (layer_dir / "ACTIVE_WRITER_HANDOFF.json").write_text(
                    json.dumps({"status": "RUNNING", "episode": "E01", "layers": paths}), encoding="utf-8")
                self.assertIsNone(mod.sealed_handoff_layers("E01", "SCOPE-X"))
            finally:
                sys.path.remove(str(TOOLS))
                if old is None:
                    os.environ.pop("NALU_RUNTIME_ROOT", None)
                else:
                    os.environ["NALU_RUNTIME_ROOT"] = old


if __name__ == "__main__":
    unittest.main()
