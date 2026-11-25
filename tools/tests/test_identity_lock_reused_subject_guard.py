"""E28 S3 (device …1101, 2026-11-25): an identity review that names a subject the episode REUSES from the series
library (a hand-made supplementary review) must never re-lock or downgrade the series' LOCKED row."""
from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))

LOCKED_ROW = {"status": "LOCKED", "qa": {"status": "PASS"},
              "artifacts": [{"path": "/series/plates/CHAR-AYE.png", "sha256": "a" * 64}]}


class ReusedSubjectGuardTests(unittest.TestCase):
    def test_reused_locked_subject_is_left_unchanged_and_counts_as_pass(self):
        lock = importlib.import_module("identity_qa_lock")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            series = base / "series_asset_library.json"
            episode_lib = base / "episode_asset_library.json"
            for path in (series, episode_lib):
                path.write_text(json.dumps({"schema": lock.LIBRARY_SCHEMA, "project_id": "SER",
                                            "assets": {"characters": {"CHAR-AYE": dict(LOCKED_ROW)}}}))
            reqs = base / "asset_requirements.json"
            reqs.write_text(json.dumps({"assets": {"characters": [
                {"asset_id": "CHAR-AYE", "reuse": {"status": "REUSED_FROM_PRIOR_LIBRARY"}}]}}))
            submitted_path = base / "submitted.json"
            submitted_path.write_text("{}")
            p = SimpleNamespace(identity_library=episode_lib, asset_library=series, series_id="SER",
                                asset_requirements=reqs, character_registry=base / "reg.json",
                                identity_qa=base / "qa.json", identity=base, character_sources=base,
                                plates=base, scope_id="SER")
            submitted = {"kind": "identity", "questionnaire": {}, "items": [{
                "item_id": "CHAR-AYE", "verdict": "REJECT", "answers": {}, "defects": [],
                "request_item": {"category": "characters", "media": []}}]}
            with mock.patch.object(lock, "QaPaths", return_value=p), \
                    mock.patch.object(lock, "Expectations", return_value=SimpleNamespace(contract={})), \
                    mock.patch.object(lock, "build_registry", return_value={"status": "WRITTEN"}), \
                    mock.patch.object(lock, "distinctness_summary", return_value={}), \
                    mock.patch.object(lock._render_style, "resolve_runtime", return_value="live_action"):
                record = lock.materialise("E28", submitted, submitted_path, rights_basis="R")
            self.assertEqual(record["status"], "PASS")
            self.assertEqual(record["subjects"][0]["status"], "REUSED_LOCKED_UNCHANGED")
            for path in (series, episode_lib):
                row = json.loads(path.read_text())["assets"]["characters"]["CHAR-AYE"]
                self.assertEqual(row["status"], "LOCKED")
                self.assertEqual(row["artifacts"], LOCKED_ROW["artifacts"])


if __name__ == "__main__":
    unittest.main()
