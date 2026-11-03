"""Studio asset library: the REAL entry points read and write it (offline stubs, zero provider calls).

Each test drives the production function that does the work -- the image harvester's poll tick, the identity
lock writer, S2 reuse verification, the cross-episode reuse lock, the S5 keyframe reference binding, the S6
video identity-plate lookup, and the provider request digest -- not just the new module.  Providers are
replaced by stubs that fail the test if a generation or query is attempted where none is allowed.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
RUNTIME_TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for entry in (str(REPO), str(REPO / "tools"), str(RUNTIME_TOOLS)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

from tools import harvest_giggle_image_batch as harvest  # noqa: E402
from tools import initial_asset_library as ial  # noqa: E402
from tools import provider_request_digest as digest  # noqa: E402
from tools import studio_asset_library as studio  # noqa: E402
from tools import studio_asset_migrate as migrate  # noqa: E402
from tools.tests.studio_asset_fixtures import png_bytes, write_png  # noqa: E402
from tools.tests.test_studio_asset_library import NoNetwork, clean_env  # noqa: E402

import build_keyframe_manifest as bkm  # noqa: E402
import build_nalu_preproduction as bnp  # noqa: E402
import bootstrap_identity_cards as bic  # noqa: E402
import library_lock_non_plate as llnp  # noqa: E402

PROJECT = "STUDIO-WIRING-PROJECT"


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Offline:
    """No network, and any provider query / POST helper raises."""

    def __enter__(self):
        def boom(*_a, **_k):
            raise AssertionError("a provider call was attempted; the studio library must never cause one")

        self._net = NoNetwork().__enter__()
        self._patches = [mock.patch.object(harvest, "query_task", boom),
                         mock.patch("urllib.request.urlopen", boom)]
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self._patches):
            patch.stop()
        self._net.__exit__()
        return False


class WiringBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / "studio"
        self._env = clean_env()
        self._env.start()
        self.addCleanup(self._env.stop)
        self._offline = Offline().__enter__()
        self.addCleanup(self._offline.__exit__)

    def enabled(self):
        return clean_env(**{studio.ENV_ROOT: str(self.root)})

    def old_runtime(self):
        """An 'old' episode folder + asset library with one approved character (two views) and a prop."""
        old = self.tmp / "old_runtime"
        plates = old / "workflow" / "E02" / "identity" / "plates"
        files = {
            "head": write_png(plates / "E02_CHAR-A__FRONT_NEUTRAL_HEADSHOT_task1.png", 1),
            "body": write_png(plates / "E02_CHAR-A_task2.png", 2),
            "prop": write_png(plates / "E02_PROP-B_task3.png", 3),
        }
        library = {"schema": "ai_drama.production_asset_library.v1", "project_id": PROJECT, "assets": {
            "characters": {"CHAR-A": {
                "asset_id": "CHAR-A", "category": "characters", "label": "A", "status": "LOCKED",
                "qa": {"status": "PASS", "reviewer": "r", "checks": []},
                "artifacts": [{"role": "FULL_BODY_STANDING", "canonical_identity_reference": True, "media_type": "image/png",
                               "path": str(files["body"]), "sha256": sha(files["body"])},
                              {"role": "FRONT_NEUTRAL_HEADSHOT", "media_type": "image/png",
                               "path": str(files["head"]), "sha256": sha(files["head"])}],
                "lock": {"identity_lock": {"canonical_view_paths": [str(files["body"]), str(files["head"])],
                                            "canonical_view_sha256": {str(files["body"]): sha(files["body"]),
                                                                       str(files["head"]): sha(files["head"])}}}}},
            "props": {"PROP-B": {
                "asset_id": "PROP-B", "category": "props", "label": "B", "status": "LOCKED",
                "qa": {"status": "PASS", "checks": []},
                "artifacts": [{"role": "FULL_BODY_STANDING", "media_type": "image/png", "path": str(files["prop"]),
                               "sha256": sha(files["prop"])}]}}}}
        lib_file = old / "runtime" / "asset_library.json"
        lib_file.parent.mkdir(parents=True)
        lib_file.write_text(json.dumps(library))
        return old, lib_file, files, library

    def migrated_then_old_files_removed(self):
        old, lib_file, files, library = self.old_runtime()
        report = migrate.run(self.root, libraries=[str(lib_file)], apply=True)
        self.assertEqual(report["status"], "APPLIED", report)
        shas = {k: sha(v) for k, v in files.items()}
        for path in files.values():
            path.unlink()  # the old episode folder is gone
        return old, lib_file, files, shas, library


class HarvestEntryTests(WiringBase):
    def _submit_report(self, rows):
        path = self.tmp / "submit.json"
        path.write_text(json.dumps({"episode": "E21", "results": rows}))
        return path

    def _run_poll(self, rows, project):
        source = {"u1": write_png(self.tmp / "provider" / "u1.png", 41), "u2": write_png(self.tmp / "provider" / "u2.png", 42),
                  "u3": write_png(self.tmp / "provider" / "u3.png", 41)}  # u3 is byte-identical to u1
        calls = []

        def fake_query(args):
            calls.append(args.task_id)
            return {"data": {"status": "completed", "urls": [f"https://provider.invalid/{args.task_id}"]}}

        def fake_download(url, destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(source[url.rsplit("/", 1)[1]].read_bytes())

        with mock.patch.object(harvest, "query_task", fake_query), mock.patch.object(harvest, "download", fake_download):
            payload = harvest.poll_once(self._submit_report(rows), self.tmp / "plates", self.tmp / "raw", project)
        return payload, calls

    ROWS = [{"task_key": "CHAR-X__FRONT_NEUTRAL_HEADSHOT", "task_id": "u1"}, {"task_key": "CHAR-X", "task_id": "u2"},
            {"task_key": "CHAR-X__DUP", "task_id": "u3"}]

    def test_real_harvest_archives_each_original_unreviewed_and_dedupes_by_bytes(self):
        with self.enabled():
            payload, calls = self._run_poll(self.ROWS, PROJECT)
        self.assertEqual(sorted(calls), ["u1", "u2", "u3"])  # only the stubbed status queries; no POST exists on this path
        lib = studio.Library(self.root, create=False)
        statuses = [r["studio_archive"]["status"] for r in payload["results"]]
        self.assertEqual(statuses, ["ARCHIVED_UNREVIEWED"] * 3)
        objects = [p for p in (self.root / "objects").rglob("*") if p.is_file()]
        self.assertEqual(len(objects), 2)  # u1 and u3 are the same bytes: one original
        for item in payload["results"]:
            self.assertEqual(sha(Path(item["output_path"])), item["sha256"])
            self.assertEqual(sha(lib.find_object(item["sha256"])), item["sha256"])
        self.assertEqual(lib.search(), [])  # archived is not approved
        self.assertEqual(len(lib.search(status="UNREVIEWED")), 2)  # one pending record per distinct original
        record = lib.object_record(payload["results"][0]["sha256"])
        self.assertEqual({o["task_id"] for o in record["origins"]}, {"u1", "u3"})
        self.assertTrue(all(o["raw_response_sha256"] for o in record["origins"]))
        self.assertEqual(lib.verify()["status"], "PASS")

    def test_library_not_enabled_or_keyframe_harvest_changes_nothing(self):
        payload, _ = self._run_poll(self.ROWS, PROJECT)
        self.assertEqual({r["studio_archive"]["status"] for r in payload["results"]}, {"STUDIO_LIBRARY_NOT_ENABLED"})
        self.assertFalse(self.root.exists())
        with self.enabled():
            payload, _ = self._run_poll(self.ROWS, None)  # S5 keyframe harvest passes no project
        self.assertTrue(all("studio_archive" not in r for r in payload["results"]))
        self.assertFalse(self.root.exists())

    def test_s3_harvest_command_carries_the_studio_flag(self):
        source = (RUNTIME_TOOLS / "nalu_pipeline.py").read_text(encoding="utf-8")
        self.assertIn('"--studio-archive-project", ctx.p.scope["series_id"]', source)


class _LoadedNalu:
    """Same module-isolation pattern as test_nalu_scoped_qa_paths: reload the nalu tools against a temp runtime."""

    MODULES = ("nalu_paths", "nalu_series_scope", "nalu_qa_common", "identity_qa_lock", "vlm_review_protocol",
               "studio_asset_resolve")

    def __init__(self, runtime: Path, engine: Path, scope: str):
        self.runtime, self.engine, self.scope = runtime, engine, scope

    def __enter__(self):
        self.saved = {n: sys.modules.get(n) for n in self.MODULES}
        self.path = list(sys.path)
        self.patch = mock.patch.dict(os.environ, {"NALU_RUNTIME_ROOT": str(self.runtime), "NALU_ENGINE_ROOT": str(self.engine),
                                                  "NALU_SERIES_SCOPE_ID": self.scope})
        self.patch.start()
        for name in self.MODULES:
            sys.modules.pop(name, None)
        sys.path.insert(0, str(RUNTIME_TOOLS))
        return self

    def __exit__(self, *exc):
        for name in self.MODULES:
            sys.modules.pop(name, None)
        for name, module in self.saved.items():
            if module is not None:
                sys.modules[name] = module
        sys.path[:] = self.path
        self.patch.stop()
        return False


class LockEntryTests(WiringBase):
    def _scoped_runtime(self):
        runtime, engine = self.tmp / "runtime-root", self.tmp / "engine"
        base = "series/studio"
        scope = {"series_root": base, "asset_library": f"{base}/asset_library.json", "asset_library_seed": f"{base}/asset_library_seed.json",
                 "voice_registry": f"{base}/voice_registry.json", "voice_catalog": f"{base}/voice_catalog.json",
                 "voice_cast": f"{base}/voice_cast.json", "entity_registry": f"{base}/entity_registry.json",
                 "agentcut_voice_policy": f"{base}/agentcut_voice_policy.json", "character_registry": f"{base}/character_registry.json",
                 "character_sources": f"{base}/character_sources", "voice_refs": f"{base}/voice_refs",
                 "lexicon": f"{base}/lexicon.json", "charter": None, "series_id": PROJECT}
        (runtime / "runtime").mkdir(parents=True)
        (runtime / "runtime/series_scopes.json").write_text(json.dumps({
            "schema": "nalu.series_scopes.v1", "default_scope": "NALU-YEWUJIANG", "episodes": {}, "scopes": {"STUDIOSCOPE": scope}}))
        row = lambda label: {"label": label, "status": "REQUIRED_UNCREATED",  # noqa: E731
                             "specification": {"physical_function": "fixture", "card_deliverables": []}}
        library = {"schema": "ai_drama.production_asset_library.v1", "project_id": PROJECT,
                   "assets": {"props": {"PROP-OK": row("good prop"), "PROP-BAD": row("bad prop")}}}
        for name in ("asset_library.json", "asset_library_seed.json"):
            (runtime / base).mkdir(parents=True, exist_ok=True)
            (runtime / base / name).write_text(json.dumps(library))
        (runtime / base / "entity_registry.json").write_text(json.dumps({"entity_aliases": {}}))
        (runtime / "runtime/pipeline_state").mkdir(parents=True)
        layers = runtime / "writer_layers/E01"
        layers.mkdir(parents=True)
        paths = {}
        for key, name in (("narrative_canonical", "E01_NARRATIVE_CANONICAL_v1.md"), ("directing_script", "E01_DIRECTING_SCRIPT_v1.md"),
                          ("generation_contract", "E01_GENERATION_CONTRACT_v1.json"), ("writer_manifest", "E01_manifest_v1.json")):
            (layers / name).write_text("{}")
            paths[key] = str(layers / name)
        (runtime / "runtime/pipeline_state/E01.json").write_text(json.dumps({
            "episode": "E01", "series_scope": {"scope_id": "STUDIOSCOPE"}, "layers": {"paths": paths}}))
        local = engine / "workflow/nalu/E01/identity/asset_library.json"
        local.parent.mkdir(parents=True)
        local.write_text(json.dumps(library))
        return runtime, engine, local

    def _submitted(self, plate_ok: Path, plate_bad: Path):
        item = lambda aid, plate, verdict: {  # noqa: E731
            "item_id": aid, "verdict": verdict, "answers": {}, "defects": [],
            "request_item": {"category": "props", "expectations": {"appearance": "fixture", "card_deliverables": []},
                             "media": [{"role": "IDENTITY_PLATE", "path": str(plate)}]}}
        return {"kind": "identity", "questionnaire": {}, "reviewed_at": "2026-09-20T00:00:00Z", "reviewer": "fixture-reviewer",
                "items": [item("PROP-OK", plate_ok, "PASS"), item("PROP-BAD", plate_bad, "FAIL")]}

    def test_real_lock_writer_links_the_verdict_to_original_versions_and_binds_the_project(self):
        runtime, engine, _local = self._scoped_runtime()
        ok = write_png(engine / "workflow/nalu/E01/identity/plates/PROP-OK__FULL_BODY_STANDING.png", 61)
        bad = write_png(engine / "workflow/nalu/E01/identity/plates/PROP-BAD__FULL_BODY_STANDING.png", 62)
        review_file = self.tmp / "submitted.json"
        review_file.write_text(json.dumps({"kind": "identity"}))
        with _LoadedNalu(runtime, engine, "STUDIOSCOPE"), self.enabled():
            # the harvester's pending record for the good plate (the S3 harvest happens before the lock)
            studio.archive_harvested_image(ok, episode="E01", project_id=PROJECT, row={"task_key": "PROP-OK", "task_id": "t-ok"})
            lock = importlib.import_module("identity_qa_lock")
            result = lock.materialise("E01", self._submitted(ok, bad), review_file, rights_basis="TEST_RIGHTS")
            by_id = {row["asset_id"]: row for row in result["subjects"]}
        self.assertEqual(by_id["PROP-OK"]["studio_asset_library"]["status"], "LINKED_APPROVED")
        self.assertEqual(by_id["PROP-BAD"]["studio_asset_library"]["status"], "LINKED_REJECTED")
        lib = studio.Library(self.root, create=False)
        approved = lib.search()
        self.assertEqual([r["label"] for r in approved], ["good prop"])  # only the audited image is selectable
        rejected = lib.search(status="REJECTED", include_pending_singles=True)
        self.assertIn("bad prop", {r["label"] for r in rejected})  # a rejected image keeps its true state
        asset_id, version = approved[0]["asset_id"], approved[0]["version"]
        review = lib.get_review(asset_id, version)
        self.assertEqual(review["review_ref"]["sha256"], sha(review_file))  # bound to the real review file
        self.assertEqual(review["review_ref"]["kind"], "IDENTITY_QA_MACHINE_REVIEW")
        binding = lib.get_binding(PROJECT, "prop", "PROP-OK")
        self.assertEqual((binding["asset_id"], binding["version"]), (asset_id, version))
        self.assertIsNone(lib.get_binding(PROJECT, "prop", "PROP-BAD"))  # rejected is never bound
        pend = lib.get_review(f"PND-{sha(ok)[:16]}", 1)  # the harvest-time record follows the group's verdict
        self.assertEqual(pend["review_status"], "APPROVED")
        self.assertEqual(sha(lib.find_object(sha(ok))), sha(ok))

    def test_lock_without_the_library_enabled_is_unchanged(self):
        runtime, engine, _local = self._scoped_runtime()
        ok = write_png(engine / "workflow/nalu/E01/identity/plates/PROP-OK__FULL_BODY_STANDING.png", 63)
        bad = write_png(engine / "workflow/nalu/E01/identity/plates/PROP-BAD__FULL_BODY_STANDING.png", 64)
        review_file = self.tmp / "submitted.json"
        review_file.write_text("{}")
        with _LoadedNalu(runtime, engine, "STUDIOSCOPE"):
            lock = importlib.import_module("identity_qa_lock")
            result = lock.materialise("E01", self._submitted(ok, bad), review_file, rights_basis="TEST_RIGHTS")
        self.assertEqual({r["studio_asset_library"]["status"] for r in result["subjects"]}, {"STUDIO_LIBRARY_NOT_ENABLED"})
        self.assertEqual({r["status"] for r in result["subjects"]}, {"LOCKED", "QA_FAILED_NOT_LOCKED"})
        self.assertFalse(self.root.exists())


class ReuseAndConsumptionTests(WiringBase):
    """Acceptance 1 and 3: old episode files removed; S2 reuse, S5 keyframe binding and S6 video references still
    get the same-sha originals, with no generation."""

    def test_s2_reuse_survives_the_loss_of_the_old_episode_folder(self):
        old, lib_file, files, shas, library = self.migrated_then_old_files_removed()
        requirements = {"assets": {"characters": [{"asset_id": "CHAR-A", "reuse": {"status": "REUSED_FROM_PRIOR_LIBRARY",
                                                                                   "prior_library": str(lib_file)}}]}}
        self.assertEqual(bic.verified_requirement_reuse(requirements), set())  # library off: the old behaviour (=> paid redo)
        with self.enabled():
            self.assertEqual(bic.verified_requirement_reuse(requirements), {"CHAR-A"})  # on: reuse, no generation

    def test_s2_reuse_is_unchanged_while_old_files_exist(self):
        old, lib_file, files, library = self.old_runtime()
        requirements = {"assets": {"characters": [{"asset_id": "CHAR-A", "reuse": {"status": "REUSED_FROM_PRIOR_LIBRARY",
                                                                                   "prior_library": str(lib_file)}}]}}
        self.assertEqual(bic.verified_requirement_reuse(requirements), {"CHAR-A"})
        files["head"].write_bytes(b"changed in place")  # bytes that do not match the recorded sha are never accepted
        self.assertEqual(bic.verified_requirement_reuse(requirements), set())

    def test_s2_cross_episode_reuse_lock_copies_the_row_with_verified_originals(self):
        old, lib_file, files, shas, library = self.migrated_then_old_files_removed()
        runtime_library = json.loads(lib_file.read_text())
        episode_library = {"schema": library["schema"], "project_id": PROJECT, "assets": {}}
        requirement = {"asset_id": "CHAR-A", "reuse": {"status": "REUSED_FROM_PRIOR_LIBRARY"}, "label": "A"}
        ctx = SimpleNamespace(
            episode="E05", library=episode_library, runtime_library=runtime_library, runtime_library_path=lib_file,
            runtime_library_seed_path=self.tmp / "seed.json", library_path=self.tmp / "episode_library.json",
            requirements={"assets": {"characters": [requirement]}}, scope_id="S", series_id=PROJECT,
            voice_registry_path=self.tmp / "vr.json", voice_registry_policy="X", rights_basis="TEST", identity_review=None)
        with self.enabled():
            report = llnp.run_lock(ctx, self.tmp / "lock_report.json", force=False)
        self.assertEqual(report["failures"], [], report)
        row = json.loads(ctx.library_path.read_text())["assets"]["characters"]["CHAR-A"]
        self.assertEqual(row["status"], "LOCKED")
        by_role = {a["role"]: a for a in row["artifacts"]}
        for role, key in (("FRONT_NEUTRAL_HEADSHOT", "head"), ("FULL_BODY_STANDING", "body")):
            artifact = by_role[role]
            self.assertEqual(artifact["sha256"], shas[key])
            self.assertEqual(sha(Path(artifact["path"])), shas[key])  # real bytes at the new path
            self.assertEqual(artifact["studio_resolved_from"]["sha256"], shas[key])
            self.assertTrue(Path(artifact["path"]).name == files[key].name)  # file name (view detection) kept

    def test_s5_keyframe_binding_resolves_the_library_original_and_the_digest_binds_the_recorded_sha(self):
        old, lib_file, files, shas, library = self.migrated_then_old_files_removed()
        inputs = SimpleNamespace(asset_library=library, asset_library_path=lib_file, engine_root=self.tmp / "engine",
                                 awaited_asset_dir=self.tmp / "awaited")
        pending = bkm.entity_binding(inputs, "character", "characters", "CHAR-A", "A", "CHARACTER_IDENTITY_PLATE",
                                     view=bkm.CHARACTER_FACE_VIEW)
        self.assertEqual(pending["binding_status"], "PENDING_ASSET_LIBRARY_ARTIFACT")  # library off: blocked (the redo trap)
        with self.enabled():
            bound = bkm.entity_binding(inputs, "character", "characters", "CHAR-A", "A", "CHARACTER_IDENTITY_PLATE",
                                       view=bkm.CHARACTER_FACE_VIEW)
            wardrobe = bkm.entity_binding(inputs, "character_wardrobe", "characters", "CHAR-A", "A", "CHARACTER_WARDROBE_PLATE",
                                          view=bkm.CHARACTER_WARDROBE_VIEW)
        self.assertEqual(bound["binding_status"], "BOUND_EXACT_SHA")
        self.assertEqual(bound["sha256"], shas["head"])
        self.assertEqual(sha(Path(bound["path"])), shas["head"])
        self.assertEqual(bound["view"], "FRONT_NEUTRAL_HEADSHOT")  # usage is explicit: the face plate, not the costume card
        self.assertNotEqual(bound["path"], wardrobe["path"])
        self.assertEqual(wardrobe["sha256"], shas["body"])
        self.assertEqual(bound["studio_asset_resolved_from"]["sha256"], shas["head"])
        # the request digest binds the bytes that will be sent: identical to what it would have bound from the old path
        evidence = digest.reference_evidence([bound])
        self.assertEqual((evidence[0]["status"], evidence[0]["source_sha256"]), ("PRESENT", shas["head"]))
        task = {"model": "m", "aspect_ratio": "9:16", "reference_images": [bound["path"]],
                "reference_image_sequence": [{"role": "character"}]}
        sent = digest.task_request_digest(task, prompt_text="p", reference_paths=[Path(bound["path"])])
        self.assertEqual(sent["reference_sha256_in_send_order"], [shas["head"]])
        self.assertEqual(sent["request_sha256"], digest.request_digest(
            prompt_text="p", model="m", aspect_ratio="9:16", reference_sha256=[shas["head"]], reference_roles=["character"]))

    def test_s6_video_identity_plate_lookup_uses_the_library_original(self):
        old, lib_file, files, shas, library = self.migrated_then_old_files_removed()
        scope = {"series_id": PROJECT, "asset_library": str(lib_file), "asset_library_seed": str(lib_file)}
        bnp._ASSET_LIBRARY_CACHE.clear()
        with mock.patch.object(bnp._series_scope, "resolve_scope", return_value=scope), self.enabled():
            plate = bnp._locked_identity_plate("CHAR-A", episode="E05")
            rows, dropped, missing = bnp.identity_plate_reference_rows(["CHAR-A"], lambda cid: bnp._locked_identity_plate(cid, episode="E05"),
                                                                         existing_paths=[])
            head = bnp.locked_artifact_headshot(library["assets"]["characters"]["CHAR-A"])
        self.assertEqual(sha(plate), shas["head"])  # the front-neutral headshot is still the one chosen
        self.assertEqual((dropped, missing), ([], []))
        self.assertEqual((rows[0]["sha256"], rows[0]["view"]), (shas["head"], "FRONT_NEUTRAL_HEADSHOT"))
        self.assertEqual(sha(head), shas["head"])
        bnp._ASSET_LIBRARY_CACHE.clear()
        with mock.patch.object(bnp._series_scope, "resolve_scope", return_value=scope):
            # library off: exactly the old, fail-closed behaviour (the recorded view is gone and nothing replaces it)
            with self.assertRaisesRegex(ValueError, "IDENTITY_ARTIFACT_SHA_MISMATCH"):
                bnp._locked_identity_plate("CHAR-A", episode="E05")

    def test_damaged_master_blocks_the_dependent_stage_with_a_restore_request_not_a_redo(self):
        old, lib_file, files, shas, library = self.migrated_then_old_files_removed()
        lib = studio.Library(self.root, create=False)
        master = lib.find_object(shas["head"])
        os.chmod(master, 0o644)
        master.write_bytes(b"damaged")
        requirements = {"assets": {"characters": [{"asset_id": "CHAR-A", "reuse": {"status": "REUSED_FROM_PRIOR_LIBRARY",
                                                                                   "prior_library": str(lib_file)}}]}}
        with self.enabled():
            with self.assertRaises(SystemExit) as ctx:
                bic.verified_requirement_reuse(requirements)
        self.assertIn("STUDIO_ASSET_RESTORE_PENDING", str(ctx.exception))
        self.assertTrue((self.root / "backup" / "restore_requests" / f"{shas['head']}.json").is_file())

    def test_migration_leaves_history_evidence_bytes_unchanged(self):
        old, lib_file, files, library = self.old_runtime()
        receipt = old / "review_receipt.json"
        receipt.write_text(json.dumps({"verdict": "PASS"}))
        tx = old / "transaction.json"
        tx.write_text(json.dumps({"state": "BOUND"}))
        before = {p: sha(p) for p in (lib_file, receipt, tx)}
        migrate.run(self.root, libraries=[str(lib_file)], apply=True)
        migrate.run(self.root, libraries=[str(lib_file)], apply=True)
        self.assertEqual(before, {p: sha(p) for p in before})

    def test_new_studio_version_does_not_change_what_the_project_already_resolved(self):
        old, lib_file, files, shas, library = self.migrated_then_old_files_removed()
        lib = studio.Library(self.root, create=False)
        before = lib.resolve_binding(PROJECT, "character", "CHAR-A", usage="FRONT_NEUTRAL_HEADSHOT", cache_dir=self.tmp / "c")
        new = lib.register_version(category="characters", label="A", asset_id=before[0]["asset_id"],
                                   artifacts=[{"usage": "FRONT_NEUTRAL_HEADSHOT", "path": str(write_png(self.tmp / "n" / "new.png", 77))}])
        lib.set_review(new["asset_id"], new["version"], "APPROVED", {"kind": "T", "sha256": "b" * 64})
        after = lib.resolve_binding(PROJECT, "character", "CHAR-A", usage="FRONT_NEUTRAL_HEADSHOT", cache_dir=self.tmp / "c")
        self.assertEqual((before[0]["version"], before[0]["content_sha256"]), (after[0]["version"], after[0]["content_sha256"]))
        self.assertEqual(lib.recommended_version(before[0]["asset_id"]), 2)


class ProjectIsolationCompatibilityTests(WiringBase):
    def test_a_studio_reference_names_where_bytes_live_but_never_relaxes_project_isolation(self):
        asset = {"status": "LOCKED", "artifacts": [{"role": "R", "media_type": "image/png",
                                                    "studio_ref": {"asset_id": "AST-1", "version": 1, "content_sha256": "c" * 64},
                                                    "sha256": "c" * 64}]}
        self.assertEqual(ial.artifact_errors(asset), [])
        bad = {"artifacts": [{"role": "R", "media_type": "image/png", "sha256": "c" * 64, "studio_ref": {"asset_id": "AST-1"}}]}
        self.assertEqual(ial.artifact_errors(bad), ["artifact_0_location_missing"])
        requirements = {"schema": ial.SCHEMA_REQUIREMENTS, "project_id": "PROJ-NEW", "canonical_sha256": "a" * 64,
                        "series_bible_sha256": "b" * 64, "assets": {c: [] for c in ial.CATEGORIES}}
        existing = {"schema": ial.SCHEMA_LIBRARY, "project_id": "PROJ-OTHER", "assets": {}}
        with self.assertRaisesRegex(ValueError, "existing_library_project_mismatch"):
            ial.compile_library(requirements, existing)  # the project_id check is intact

    def test_two_projects_use_one_original_with_independent_role_fields(self):
        old, lib_file, files, shas, library = self.migrated_then_old_files_removed()
        lib = studio.Library(self.root, create=False)
        approved = {r["label"]: r for r in lib.search()}
        asset_id = approved["A"]["asset_id"]
        lib.bind("PROJECT-TWO", "character", "CHAR-NEWROLE", asset_id, 1, project_fields={"name": "second project's own name"})
        first = lib.get_binding(PROJECT, "character", "CHAR-A")
        second = lib.get_binding("PROJECT-TWO", "character", "CHAR-NEWROLE")
        self.assertEqual({p["content_sha256"] for p in first["pins"]}, {p["content_sha256"] for p in second["pins"]})
        self.assertEqual(first["project_fields"], {"label": "A"})
        self.assertEqual(second["project_fields"], {"name": "second project's own name"})
        self.assertEqual(second["provenance"]["origin_projects"], [PROJECT])
        a = lib.resolve_binding(PROJECT, "character", "CHAR-A", cache_dir=self.tmp / "c1")
        b = lib.resolve_binding("PROJECT-TWO", "character", "CHAR-NEWROLE", cache_dir=self.tmp / "c2")
        self.assertEqual(sorted(sha(Path(x["path"])) for x in a), sorted(sha(Path(x["path"])) for x in b))


if __name__ == "__main__":
    unittest.main()
