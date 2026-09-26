"""stage_s3 reuse: a LOCKED character's per-view plan rows are skipped, not re-rendered (2026-09-21)."""
from __future__ import annotations

import hashlib
import importlib
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "lines/nalu/runtime/tools"))


class LockedViewReuse(unittest.TestCase):
    def test_paid_plan_excludes_reuse_and_keeps_recovery(self):
        import copy
        pipeline = importlib.import_module('nalu_pipeline')
        plan = {'new_asset_groups': [
            {'id': 'reuse', 'prompt_sha256': 'a'},
            {'id': 'bound', 'prompt_sha256': 'b'},
            {'id': 'new', 'prompt_sha256': 'c'}]}
        before = copy.deepcopy(plan)
        selected = pipeline.s3_submission_plan(plan, {'reuse': {}}, [])
        self.assertEqual([r['id'] for r in selected['new_asset_groups']], ['bound', 'new'])
        self.assertEqual(selected['reuse_excluded_subject_ids'], ['reuse'])
        self.assertEqual(plan, before)
        subset = pipeline.s3_submission_plan(plan, {'reuse': {}}, ['reuse', 'new'])
        self.assertEqual(subset['new_asset_groups'], [{'id': 'new', 'prompt_sha256': 'c'}])

    def test_view_rows_registered_for_locked_subject(self):
        pipeline = importlib.import_module("nalu_pipeline")
        with tempfile.TemporaryDirectory() as tmp:
            arts = []
            for role in ("FULL_BODY_STANDING", "FRONT_NEUTRAL_HEADSHOT", "THREE_QUARTER_BUST"):
                f = Path(tmp) / f"{role}.png"; f.write_bytes(role.encode())
                arts.append({"role": role, "path": str(f), "sha256": hashlib.sha256(role.encode()).hexdigest()})
            library = {"assets": {"characters": {
                "CHAR-A": {"status": "LOCKED", "qa": {"status": "PASS"}, "artifacts": arts},
                "CHAR-B": {"status": "REQUIRED_UNCREATED", "qa": {"status": "FAIL"}, "artifacts": arts},
            }}}
            already = pipeline.locked_subjects(library)
        self.assertIn("CHAR-A", already)
        self.assertIn("CHAR-A__FRONT_NEUTRAL_HEADSHOT", already)
        self.assertIn("CHAR-A__THREE_QUARTER_BUST", already)
        self.assertEqual(already["CHAR-A__THREE_QUARTER_BUST"]["via"], "CHAR-A")
        self.assertNotIn("CHAR-B", already)
        self.assertNotIn("CHAR-B__FRONT_NEUTRAL_HEADSHOT", already)


if __name__ == "__main__":
    unittest.main()


class StalePayloadRetire(unittest.TestCase):
    def test_stage_s4_retires_payloads_older_than_catalog(self):
        import json, os, time, types
        pipeline = importlib.import_module("nalu_pipeline")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payloads = root / "speech_task_payloads.json"; payloads.write_text('{"tasks": []}')
            catalog = root / "voice_catalog.json"
            old = time.time() - 3600
            os.utime(payloads, (old, old))
            catalog.write_text('{"voices": {"a": {"voice_id": "v1"}}}')
            registry = root / "voice_registry.json"; registry.write_text('{"major_roles": []}')
            calls = []

            class P:  # minimal QaPaths stand-in
                speech_payloads = payloads
                voice = root
                voice_report = root / "r.json"
                contract = root / "c.json"; asset_requirements = root / "a.json"
                scope = {"voice_catalog": str(catalog), "voice_registry": str(registry)}

            def run(argv, name):
                calls.append(name)
                payloads.write_text(json.dumps({"tasks": []}))
                return {"exit_code": 0, "log": ""}

            ctx = types.SimpleNamespace(p=P(), episode="E01", run=run)
            try:
                pipeline.stage_s4(ctx)
            except Exception:
                pass  # the rest of stage_s4 needs a full Ctx; only the retire/rebuild prefix is under test
            self.assertIn("s4_bootstrap_voice_references", calls)
            self.assertTrue(any(f.name.startswith("speech_task_payloads.json.stale_") for f in root.iterdir()))
