"""Regression tests for same-numbered episodes in independent NALU series scopes."""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
RUNTIME_TOOLS = ROOT / "lines/nalu/runtime/tools"
MODULES = (
    "nalu_paths", "nalu_series_scope", "nalu_qa_common",
    "identity_qa_lock", "vlm_review_protocol", "library_lock_non_plate",
    "build_nalu_preproduction", "video_q2_builder", "nalu_pipeline",
    "keyframe_q1_builder",
    "materialize_paid_authorization",
)


def _scope_paths(name: str, series_id: str) -> dict[str, object]:
    base = f"series/{name}"
    return {
        "series_root": base,
        "asset_library": f"{base}/asset_library.json",
        "asset_library_seed": f"{base}/asset_library_seed.json",
        "voice_registry": f"{base}/voice_registry.json",
        "voice_catalog": f"{base}/voice_catalog.json",
        "voice_cast": f"{base}/voice_cast.json",
        "entity_registry": f"{base}/entity_registry.json",
        "agentcut_voice_policy": f"{base}/agentcut_voice_policy.json",
        "character_registry": f"{base}/character_registry.json",
        "character_sources": f"{base}/character_sources",
        "voice_refs": f"{base}/voice_refs",
        "lexicon": f"{base}/lexicon.json",
        "charter": None,
        "series_id": series_id,
    }


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return path


@contextmanager
def _loaded(runtime_root: Path, engine_root: Path, scope_id: str):
    saved = {name: sys.modules.get(name) for name in MODULES}
    old_path = list(sys.path)
    env = {
        "NALU_RUNTIME_ROOT": str(runtime_root),
        "NALU_ENGINE_ROOT": str(engine_root),
        "NALU_SERIES_SCOPE_ID": scope_id,
    }
    try:
        with patch.dict(os.environ, env, clear=False):
            for name in MODULES:
                sys.modules.pop(name, None)
            sys.path.insert(0, str(RUNTIME_TOOLS))
            yield
    finally:
        for name in MODULES:
            sys.modules.pop(name, None)
        for name, module in saved.items():
            if module is not None:
                sys.modules[name] = module
        sys.path[:] = old_path


class ScopedQaPaths(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, dict[str, object]]:
        runtime = root / "runtime-root"
        engine = root / "engine"
        cfg = {
            "schema": "nalu.series_scopes.v1",
            "default_scope": "NALU-YEWUJIANG",
            "episodes": {},
            "scopes": {
                "FOBENSHIDAO": _scope_paths("fobenshidao", "FOBENSHIDAO"),
                "OTHER": _scope_paths("other", "OTHER"),
            },
        }
        _write(runtime / "runtime/series_scopes.json", cfg)
        return runtime, engine, cfg

    def test_identity_review_and_lock_use_nested_scoped_sources_and_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime, engine, _ = self._fixture(Path(tmp))
            default_library = runtime / "runtime/asset_library.json"
            scoped_library = runtime / "series/fobenshidao/asset_library.json"
            source = runtime / "series/fobenshidao/character_sources/E01/CHAR-FBS__SOURCE_USER.png"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"private source")
            plate = engine / "workflow/nalu/E01/identity/plates/PROP-FBS__FULL_BODY_STANDING.png"
            plate.parent.mkdir(parents=True, exist_ok=True)
            plate.write_bytes(b"plate")
            library = {
                "schema": "ai_drama.production_asset_library.v1",
                "project_id": "FOBENSHIDAO",
                "marker": "SCOPED",
                "assets": {
                    "characters": {"CHAR-FBS": {
                        "label": "周青", "status": "REQUIRED_UNCREATED",
                        "specification": {"canonical_name": "周青", "card_deliverables": []},
                    }},
                    "props": {"PROP-FBS": {
                        "label": "测试法器", "status": "REQUIRED_UNCREATED",
                        "specification": {"physical_function": "承载测试"},
                    }},
                },
            }
            _write(scoped_library, library)
            _write(runtime / "series/fobenshidao/asset_library_seed.json", library)
            _write(default_library, {
                "schema": "ai_drama.production_asset_library.v1", "project_id": "NALU-YEWUJIANG",
                "marker": "DEFAULT", "assets": {"props": {"PROP-FBS": {"status": "DEFAULT_SENTINEL"}}},
            })
            _write(runtime / "runtime/nalu_character_asset_registry.json", {"sentinel": "DEFAULT"})
            _write(runtime / "series/fobenshidao/entity_registry.json", {"entity_aliases": {}})
            scoped_lexicon = _write(runtime / "series/fobenshidao/lexicon.json", {
                "schema": "qingshan.lexicon.v1", "status": "SCRIPT_DERIVED",
                "forbidden_terms": [], "canonical_names": {},
            })
            scoped_voice_cast = _write(runtime / "series/fobenshidao/voice_cast.json", {
                "schema": "qingshan.voice_cast.v1", "characters": {},
            })
            private_layers = runtime / "writer_layers/FOBENSHIDAO/E01"
            private_narrative = _write(private_layers / "E01_NARRATIVE_CANONICAL_v1.md", {})
            private_contract = _write(private_layers / "E01_GENERATION_CONTRACT_v1.json", {})
            private_manifest = _write(private_layers / "E01_manifest_v1.json", {})
            private_directing = _write(private_layers / "E01_DIRECTING_SCRIPT_v1.md", {})
            _write(runtime / "runtime/pipeline_state/E01.json", {
                "episode": "E01", "series_scope": {"scope_id": "FOBENSHIDAO"},
                "layers": {"paths": {
                    "narrative_canonical": str(private_narrative),
                    "directing_script": str(private_directing),
                    "generation_contract": str(private_contract),
                    "writer_manifest": str(private_manifest),
                }},
            })
            local_library = engine / "workflow/nalu/E01/identity/asset_library.json"
            _write(local_library, {**library, "project_id": "NALU-YEWUJIANG"})

            with _loaded(runtime, engine, "FOBENSHIDAO"):
                common = importlib.import_module("nalu_qa_common")
                with self.assertRaisesRegex(SystemExit, "EPISODE_ASSET_LIBRARY_PROJECT_MISMATCH"):
                    common.Expectations("E01")
                _write(local_library, library)
                lock = importlib.import_module("identity_qa_lock")
                review = importlib.import_module("vlm_review_protocol")
                paths = common.QaPaths("E01")
                self.assertEqual(paths.asset_library, scoped_library.resolve())
                self.assertEqual(paths.lexicon, scoped_lexicon.resolve())
                self.assertEqual(paths.voice_cast, scoped_voice_cast.resolve())
                # macOS may expose the same tempfile through both /var and
                # /private/var.  Identity of the file is authoritative; path
                # spelling is not a series-isolation boundary.
                self.assertTrue(paths.narrative.samefile(private_narrative))
                self.assertTrue(paths.contract.samefile(private_contract))
                self.assertTrue(paths.writer_manifest.samefile(private_manifest))
                self.assertEqual(common.Expectations("E01").library["marker"], "SCOPED")
                self.assertEqual(lock.find_operator_source("CHAR-FBS", paths.character_sources),
                                 source.resolve())

                request = review.build_request("identity", "E01", out=Path(tmp) / "request.json")
                char_item = next(row for row in request["items"] if row["item_id"] == "CHAR-FBS")
                source_rows = [row for row in char_item["media"]
                               if row["role"] == "OPERATOR_SOURCE_REFERENCE"]
                self.assertEqual([row["path"] for row in source_rows], [str(source.resolve())])

                submitted_path = _write(Path(tmp) / "submitted.json", {"kind": "identity"})
                submitted = {
                    "kind": "identity", "questionnaire": {}, "reviewed_at": "2026-09-20T00:00:00Z",
                    "items": [{
                        "item_id": "PROP-FBS", "verdict": "PASS", "answers": {}, "defects": [],
                        "request_item": {
                            "category": "props",
                            "expectations": {"appearance": "测试法器", "card_deliverables": []},
                            "media": [{"role": "IDENTITY_PLATE", "path": str(plate)}],
                        },
                    }],
                }
                result = lock.materialise("E01", submitted, submitted_path, rights_basis="TEST_RIGHTS")
                self.assertEqual(result["status"], "PASS")

            self.assertEqual(json.loads(scoped_library.read_text())["assets"]["props"]["PROP-FBS"]["status"],
                             "LOCKED")
            self.assertEqual(json.loads(default_library.read_text())["assets"]["props"]["PROP-FBS"]["status"],
                             "DEFAULT_SENTINEL")
            self.assertEqual(json.loads((runtime / "runtime/nalu_character_asset_registry.json").read_text()),
                             {"sentinel": "DEFAULT"})

    def test_preproduction_q2_and_non_plate_authorities_follow_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime, engine, _ = self._fixture(Path(tmp))
            plates: dict[str, Path] = {}
            for scope_id, folder, char_id in (
                ("FOBENSHIDAO", "fobenshidao", "CHAR-FBS"),
                ("OTHER", "other", "CHAR-OTHER"),
            ):
                plate = runtime / f"series/{folder}/{char_id}__FRONT_NEUTRAL_HEADSHOT.png"
                plate.parent.mkdir(parents=True, exist_ok=True)
                plate.write_bytes(scope_id.encode())
                plates[scope_id] = plate
                library = {
                    "schema": "ai_drama.production_asset_library.v1", "project_id": scope_id,
                    "assets": {"characters": {"CHAR-SAME": {
                        "status": "LOCKED", "lock": {"identity_lock": {
                            "canonical_view_paths": [str(plate)],
                        }},
                    }}},
                }
                _write(runtime / f"series/{folder}/asset_library.json", library)
                _write(runtime / f"series/{folder}/asset_library_seed.json", library)
                _write(runtime / f"series/{folder}/character_registry.json",
                       {"series_id": scope_id,
                        "characters": {char_id: {"reference_image": str(plate)}}})
            _write(runtime / "runtime/nalu_character_asset_registry.json",
                   {"characters": {"CHAR-DEFAULT": {}}})

            with _loaded(runtime, engine, "FOBENSHIDAO"):
                preprod = importlib.import_module("build_nalu_preproduction")
                non_plate = importlib.import_module("library_lock_non_plate")
                q2 = importlib.import_module("video_q2_builder")
                q1 = importlib.import_module("keyframe_q1_builder")
                self.assertEqual(preprod._locked_identity_plate("CHAR-SAME", episode="E01"),
                                 plates["FOBENSHIDAO"])
                with patch.dict(os.environ, {"NALU_SERIES_SCOPE_ID": "OTHER"}):
                    self.assertEqual(preprod._locked_identity_plate("CHAR-SAME", episode="E01"),
                                     plates["OTHER"])

                authorities = non_plate.resolve_runtime_authorities("E01")
                self.assertEqual(authorities["asset_library"],
                                 (runtime / "series/fobenshidao/asset_library.json").resolve())
                self.assertEqual(authorities["voice_registry"],
                                 (runtime / "series/fobenshidao/voice_registry.json").resolve())
                self.assertEqual(authorities["voice_registry_policy"],
                                 "DECLARED_SERIES_SCOPE_AUTHORITY")
                with patch.dict(os.environ, {"NALU_SERIES_SCOPE_ID": ""}):
                    default_authorities = non_plate.resolve_runtime_authorities("E01")
                self.assertEqual(default_authorities["voice_registry"],
                                 runtime / "runtime/voice_registry.json")
                self.assertEqual(default_authorities["voice_registry_policy"],
                                 "DEFAULT_SCOPE_SHARED_RUNTIME_AUTHORITY")
                config_path = runtime / "runtime/series_scopes.json"
                config = json.loads(config_path.read_text())
                config["scopes"]["NALU-YEWUJIANG"] = {
                    "voice_registry": "declared-default/voice_registry.json",
                }
                _write(config_path, config)
                with patch.dict(os.environ, {"NALU_SERIES_SCOPE_ID": ""}):
                    declared_default = non_plate.resolve_runtime_authorities("E01")
                self.assertEqual(declared_default["voice_registry"],
                                 (runtime / "declared-default/voice_registry.json").resolve())
                self.assertEqual(declared_default["voice_registry_policy"],
                                 "DECLARED_SERIES_SCOPE_AUTHORITY")

                with patch.object(q2, "engine_module", side_effect=RuntimeError("test stop")):
                    measured = q2.measure_unit_identity(
                        "E01", "UNIT-1", [], ["CHAR-FBS"], Path(tmp) / "q2")
                self.assertEqual(measured["character_registry"],
                                 str((runtime / "series/fobenshidao/character_registry.json").resolve()))
                self.assertFalse(any(row.startswith("CHARACTER_NOT_IN_REGISTRY")
                                     for row in measured["failures"]))

                with patch.object(q1, "engine_module", side_effect=RuntimeError("test stop")):
                    still = q1.measure_still_identity(
                        "E01", {}, {"ITEM-1": ["CHAR-FBS"]})
                self.assertEqual(still["character_registry"],
                                 str((runtime / "series/fobenshidao/character_registry.json").resolve()))
                self.assertFalse(any(row.startswith("CHARACTER_REGISTRY_SERIES_MISMATCH")
                                     for row in still["failures"]))

                _write(runtime / "series/fobenshidao/character_registry.json",
                       {"series_id": "OTHER", "characters": {"CHAR-FBS": {}}})
                bad_q1 = q1.measure_still_identity("E01", {}, {"ITEM-1": ["CHAR-FBS"]})
                bad_q2 = q2.measure_unit_identity(
                    "E01", "UNIT-1", [], ["CHAR-FBS"], Path(tmp) / "q2-bad")
                for bad in (bad_q1, bad_q2):
                    self.assertTrue(any(row == "CHARACTER_REGISTRY_SERIES_MISMATCH:OTHER!=FOBENSHIDAO"
                                        for row in bad["failures"]))

    def test_project_scope_check_uses_declared_root_not_host_spelling(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime, engine, _ = self._fixture(Path(tmp))
            series_root = runtime / "series/fobenshidao"
            library = _write(series_root / "asset_library.json", {"project_id": "FOBENSHIDAO"})
            _write(series_root / "lexicon.json", {
                "schema": "qingshan.lexicon.v1",
                "status": "SCRIPT_DERIVED",
                "forbidden_terms": [],
                "canonical_names": {},
            })
            gsm = _write(Path(tmp) / "gsm.json", {
                "status": "LOCKED",
                "space_maps": [{"scene_mappings": [{"scene_id": "SCENE-1"}]}],
            })
            contract = _write(Path(tmp) / "contract.json", {"scene_states": [{"scene_id": "SCENE-1"}]})

            with _loaded(runtime, engine, "FOBENSHIDAO"):
                scope_mod = importlib.import_module("nalu_series_scope")
                pipeline = importlib.import_module("nalu_pipeline")
                scope = scope_mod.resolve_scope("E01")
                scope["asset_library"] = library
                fake = SimpleNamespace(p=SimpleNamespace(scope=scope, gsm_own=gsm, contract=contract))
                clean = pipeline.project_scope_check(fake)
                self.assertEqual(clean["status"], "PASS", clean["failures"])

                # A fresh portable project runs S1 before S2 has authored its
                # first map.  It still needs a script-derived project lexicon,
                # but must not be blocked merely because the S2 map is absent.
                private_lexicon = _write(series_root / "lexicon.json", {
                    "schema": "qingshan.lexicon.v1",
                    "status": "SCRIPT_DERIVED",
                    "forbidden_terms": [],
                    "canonical_names": {},
                })
                fresh_scope = dict(scope)
                fresh_scope["lexicon"] = private_lexicon
                fresh = SimpleNamespace(p=SimpleNamespace(
                    scope=fresh_scope,
                    gsm_own=Path(tmp) / "not-created-until-s2.json",
                    contract=contract,
                ))
                s1_scope = pipeline.project_scope_check(
                    fresh, require_preproduction_map=False
                )
                self.assertEqual(s1_scope["status"], "PASS", s1_scope["failures"])
                _write(private_lexicon, {
                    "schema": "qingshan.lexicon.v1",
                    "status": "EMPTY_PENDING_SCRIPT_DERIVATION",
                    "forbidden_terms": [],
                    "canonical_names": {},
                })
                empty_lexicon = pipeline.project_scope_check(
                    fresh, require_preproduction_map=False
                )
                self.assertIn(
                    "PROJECT_LEXICON_NOT_DERIVED_FROM_SCRIPT",
                    empty_lexicon["failures"],
                )
                _write(private_lexicon, {
                    "schema": "qingshan.lexicon.v1",
                    "status": "SCRIPT_DERIVED",
                    "forbidden_terms": [],
                    "canonical_names": {},
                })

                seed_ctx = SimpleNamespace(p=SimpleNamespace(
                    scope={"series_id": "FOBENSHIDAO"},
                    rt_pre_reports=Path(tmp) / "preproduction/E01/reports",
                ))
                seed_path = pipeline.initial_global_space_map_seed(seed_ctx)
                seed = json.loads(seed_path.read_text(encoding="utf-8"))
                self.assertEqual(seed["status"], "EMPTY_SEED_NOT_ADMITTED")
                self.assertEqual(seed["space_maps"], [])
                self.assertNotEqual(seed["status"], "PASS")

                # Existing private references need not be moved: a broad
                # declared root can contain an explicitly namespaced source
                # folder, while exact reuse of any default authority is still
                # rejected structurally.
                broad = dict(scope)
                broad["series_root"] = runtime.resolve()
                broad["character_sources"] = (
                    runtime / "character_sources/fobenshidao").resolve()
                broad_ok = pipeline.project_scope_check(
                    SimpleNamespace(p=SimpleNamespace(scope=broad, gsm_own=gsm, contract=contract)))
                self.assertEqual(broad_ok["status"], "PASS", broad_ok["failures"])
                broad["voice_registry"] = (runtime / "runtime/voice_registry.json").resolve()
                broad_bad = pipeline.project_scope_check(
                    SimpleNamespace(p=SimpleNamespace(scope=broad, gsm_own=gsm, contract=contract)))
                self.assertTrue(any(row.startswith("SCOPE_PATH_REUSES_DEFAULT_AUTHORITY:voice_registry:")
                                    for row in broad_bad["failures"]))

                # This is the actual StoryClaw mount spelling that the former
                # '/nalu_runtime/runtime/' substring check failed to detect.
                leaked = dict(scope)
                leaked["voice_registry"] = Path("/home/storyclaw/nalu-runtime/runtime/voice_registry.json")
                leaked_asset = _write(runtime / "runtime/default_asset_library.json",
                                      {"project_id": "FOBENSHIDAO"})
                leaked["asset_library"] = leaked_asset
                bad = pipeline.project_scope_check(
                    SimpleNamespace(p=SimpleNamespace(scope=leaked, gsm_own=gsm, contract=contract)))
                self.assertEqual(bad["status"], "FAIL")
                self.assertTrue(any(row.startswith("SCOPE_PATH_OUTSIDE_SERIES_ROOT:voice_registry:")
                                    for row in bad["failures"]))
                self.assertTrue(any(row.startswith("SCOPE_PATH_OUTSIDE_SERIES_ROOT:asset_library:")
                                    for row in bad["failures"]))


if __name__ == "__main__":
    unittest.main()
