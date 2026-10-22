"""D-77 voice-reference duration pre-flight ignores superseded history rows
(Twelve Gazes E01 Elias, 2026-10-22: 1.405 s old row kept failing after regeneration at 3.239 s)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ENGINE = Path(__file__).resolve().parents[2]


def _pipeline():
    spec = importlib.util.spec_from_file_location("nalu_pipeline_vdur", ENGINE / "lines/nalu/runtime/tools/nalu_pipeline.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["nalu_pipeline_vdur"] = module
    spec.loader.exec_module(module)
    return module


def _ctx(tmp: Path, registry: dict):
    (tmp / "registry.json").write_text(json.dumps(registry))
    (tmp / "tx.json").write_text(json.dumps({"tasks": [{"speaker_voice_contract": {"bindings": [
        {"voice_entity_id": "elias"}]}}]}))
    return SimpleNamespace(p=SimpleNamespace(scope={"voice_registry": tmp / "registry.json"},
                                             video_transaction=tmp / "tx.json"))


def test_superseded_history_is_ignored(tmp_path):
    p = _pipeline()
    registry = {"major_roles": [{"entity_id": "elias", "duration_seconds": 3.239,
                                 "superseded_rows": [{"entity_id": "elias", "duration_seconds": 1.405}]},
                                {"entity_id": "elias", "status": "SUPERSEDED_BY_REGENERATION", "duration_seconds": 1.405}]}
    assert p.voice_reference_duration_failures(_ctx(tmp_path, registry)) == []


def test_live_short_reference_still_fails(tmp_path):
    p = _pipeline()
    registry = {"major_roles": [{"entity_id": "elias", "duration_seconds": 1.405}]}
    bad = p.voice_reference_duration_failures(_ctx(tmp_path, registry))
    assert [row["entity_id"] for row in bad] == ["elias"]
