"""A card S3 regenerates for distinctness is never treated as cross-episode reuse (device 1101 E29 2026-11-27).

S3 re-designed the LOCKED card CHAR-MOHANYUAN (s3_unlock_locked_card: series row -> SUPERSEDED_DISTINCTNESS_PENDING_
REGENERATION, ``distinctness_regeneration.episode`` = E29) and generated a new plate, but its requirement row still
said REUSED_FROM_PRIOR_LIBRARY, so the identity review request dropped it, it was never locked and the asset-library
gate failed (ASSET_LIBRARY_GATE_FAIL).  The regenerated card must enter the review request; a genuinely reused card
must still stay out of it.
"""
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

cd = importlib.import_module("character_distinctness")


def _locked(**extra):
    return {"status": "LOCKED", "qa": {"status": "PASS"}, "artifacts": [{"path": "/x.png", "sha256": "a" * 64}],
            **extra}


class RegeneratedThisEpisodeTests(unittest.TestCase):
    def test_superseded_and_planned_and_this_episode_regen_count_as_regenerated(self):
        library = {"assets": {"characters": {
            "CHAR-MOHANYUAN": {"status": cd.LOCKED_SUPERSEDED_STATUS,
                               "distinctness_regeneration": {"episode": "E29"}},
            "CHAR-LOCKEDNOW": _locked(distinctness_regeneration={"episode": "E29"}),
            "CHAR-OLDREGEN": _locked(distinctness_regeneration={"episode": "E12"}),
            "CHAR-AYE": _locked()}}}
        plan = {"new_asset_groups": [{"id": "CHAR-NEW", "view": "FRONT"},
                                     {"id": "CHAR-NEW__SHEET", "subject_id": "CHAR-NEW"}]}
        got = cd.regenerated_this_episode("E29", plan=plan, libraries=[library, None])
        self.assertEqual(got, {"CHAR-MOHANYUAN", "CHAR-LOCKEDNOW", "CHAR-NEW"})

    def test_never_raises_on_garbage(self):
        self.assertEqual(cd.regenerated_this_episode("E29", plan={"new_asset_groups": "x"},
                                                     libraries=[{"assets": {"characters": []}}]), set())


class IdentityRequestKeepsRegeneratedCardTests(unittest.TestCase):
    def test_regenerated_card_is_not_subtracted_but_true_reuse_is(self):
        vrp = importlib.import_module("vlm_review_protocol")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "E29").mkdir()
            (base / "E29" / "asset_requirements.json").write_text(json.dumps({"assets": {"characters": [
                {"asset_id": "CHAR-MOHANYUAN", "reuse": {"status": "REUSED_FROM_PRIOR_LIBRARY"}},
                {"asset_id": "CHAR-AYE", "reuse": {"status": "REUSED_FROM_PRIOR_LIBRARY"}},
                {"asset_id": "CREATURE-WINGBEAST"}]}}))
            series = base / "series.json"
            series.write_text(json.dumps({"assets": {"characters": {
                "CHAR-MOHANYUAN": {"status": cd.LOCKED_SUPERSEDED_STATUS,
                                   "distinctness_regeneration": {"episode": "E29"}},
                "CHAR-AYE": _locked()}}}))
            p = SimpleNamespace(asset_library=series, identity_library=base / "missing.json")
            plan = {"new_asset_groups": [{"id": "CHAR-MOHANYUAN", "distinctness_regeneration": {"round": 1}},
                                         {"id": "CREATURE-WINGBEAST"}]}
            with mock.patch.object(vrp, "RUNTIME_PREPRODUCTION", base):
                reused = vrp.identity_reused_subjects("E29", p, plan)
            self.assertEqual(reused, {"CHAR-AYE"})
            planned = {"CHAR-MOHANYUAN", "CREATURE-WINGBEAST", "CHAR-AYE"} - reused
            self.assertIn("CHAR-MOHANYUAN", planned)

    def test_regenerated_card_found_from_library_even_without_plan_row(self):
        vrp = importlib.import_module("vlm_review_protocol")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "E29").mkdir()
            (base / "E29" / "asset_requirements.json").write_text(json.dumps({"assets": {"characters": [
                {"asset_id": "CHAR-MOHANYUAN", "reuse": {"status": "REUSED_FROM_PRIOR_LIBRARY"}}]}}))
            ep_lib = base / "ep.json"
            ep_lib.write_text(json.dumps({"assets": {"characters": {
                "CHAR-MOHANYUAN": _locked(distinctness_regeneration={"episode": "E29"})}}}))
            p = SimpleNamespace(asset_library=base / "none.json", identity_library=ep_lib)
            with mock.patch.object(vrp, "RUNTIME_PREPRODUCTION", base):
                self.assertEqual(vrp.identity_reused_subjects("E29", p, {}), set())
                # a later episode reuses the re-designed card normally
                (base / "E30").mkdir()
                (base / "E30" / "asset_requirements.json").write_text(
                    (base / "E29" / "asset_requirements.json").read_text())
                self.assertEqual(vrp.identity_reused_subjects("E30", p, {}), {"CHAR-MOHANYUAN"})


class IdentityLockLocksRegeneratedCardTests(unittest.TestCase):
    def test_regenerated_card_is_not_left_reused_unchanged(self):
        lock = importlib.import_module("identity_qa_lock")
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            series = base / "series_asset_library.json"
            episode_lib = base / "episode_asset_library.json"
            # the series row is still LOCKED-looking (e.g. re-locked copy) but S3 regenerated it in this episode
            for path in (series, episode_lib):
                path.write_text(json.dumps({"schema": lock.LIBRARY_SCHEMA, "project_id": "SER", "assets": {
                    "characters": {"CHAR-MOHANYUAN": _locked(distinctness_regeneration={"episode": "E29"})}}}))
            reqs = base / "asset_requirements.json"
            reqs.write_text(json.dumps({"assets": {"characters": [
                {"asset_id": "CHAR-MOHANYUAN", "reuse": {"status": "REUSED_FROM_PRIOR_LIBRARY"}}]}}))
            submitted_path = base / "submitted.json"
            submitted_path.write_text("{}")
            p = SimpleNamespace(identity_library=episode_lib, asset_library=series, series_id="SER",
                                asset_requirements=reqs, character_registry=base / "reg.json",
                                identity_qa=base / "qa.json", identity=base, character_sources=base,
                                plates=base, scope_id="SER")
            submitted = {"kind": "identity", "questionnaire": {}, "items": [{
                "item_id": "CHAR-MOHANYUAN", "verdict": "REJECT", "answers": {}, "defects": [],
                "request_item": {"category": "characters", "media": []}}]}
            with mock.patch.object(lock, "QaPaths", return_value=p), \
                    mock.patch.object(lock, "Expectations", return_value=SimpleNamespace(contract={})), \
                    mock.patch.object(lock, "build_registry", return_value={"status": "WRITTEN"}), \
                    mock.patch.object(lock, "distinctness_summary", return_value={}), \
                    mock.patch.object(lock._render_style, "resolve_runtime", return_value="live_action"):
                record = lock.materialise("E29", submitted, submitted_path, rights_basis="R")
            self.assertNotEqual(record["subjects"][0]["status"], "REUSED_LOCKED_UNCHANGED")


if __name__ == "__main__":
    unittest.main()
