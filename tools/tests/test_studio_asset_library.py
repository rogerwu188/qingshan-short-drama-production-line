"""Studio asset library core: store, versions, review, bindings, integrity, bundles, backup, migration.

Offline and stdlib-only.  Every directory is a temp directory; the S3 side is the repo's in-memory fake;
nothing here can reach a provider.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools import studio_asset_backup as backup  # noqa: E402
from tools import studio_asset_library as studio  # noqa: E402
from tools import studio_asset_migrate as migrate  # noqa: E402
from tools.tests.fake_s3 import FakeS3  # noqa: E402
from tools.tests.studio_asset_fixtures import REVIEW_REF, png_bytes, write_png  # noqa: E402

CONFIGURED = {"AWS_ACCESS_KEY_ID": "x", "AWS_SECRET_ACCESS_KEY": "y",
              backup.ENV_ENDPOINT: "https://example.invalid", backup.ENV_BUCKET: "studio-private-bucket",
              backup.ENV_ACCESS: "private", backup.ENV_PREFIX: "studio-assets"}
BACKUP_ENV_NAMES = [backup.ENV_ENDPOINT, backup.ENV_BUCKET, backup.ENV_ACCESS, backup.ENV_PREFIX,
                    *backup.FORBIDDEN_BUCKET_ENVS, studio.ENV_ROOT, studio.ENV_CACHE]


def clean_env(**extra: str):
    env = {k: v for k, v in os.environ.items() if k not in BACKUP_ENV_NAMES}
    env.update(extra)
    return mock.patch.dict(os.environ, env, clear=True)


class NoNetwork:
    def __enter__(self):
        def refuse(*_a, **_k):
            raise AssertionError("network access attempted in an offline studio asset test")
        self.patches = [mock.patch.object(socket.socket, "connect", refuse),
                        mock.patch.object(socket, "create_connection", refuse)]
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self.patches):
            patch.stop()
        return False


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.lib = studio.Library(self.tmp / "studio")
        self._env = clean_env()
        self._env.start()
        self.addCleanup(self._env.stop)
        self._net = NoNetwork()
        self._net.__enter__()
        self.addCleanup(self._net.__exit__)

    def png(self, name: str, seed: int) -> Path:
        return write_png(self.tmp / "episode" / name, seed)

    def approved_asset(self, seed: int = 1, label: str = "figure A", usages=("FRONT", "FULL")) -> dict:
        arts = [{"usage": u, "path": str(self.png(f"{label}-{u}.png", seed * 10 + i))} for i, u in enumerate(usages)]
        result = self.lib.register_version(category="characters", label=label, artifacts=arts,
                                           origin={"kind": "TEST", "project_id": "PROJ-A"})
        self.lib.set_review(result["asset_id"], result["version"], "APPROVED", REVIEW_REF, reviewer="tester")
        return result


class StoreTests(Base):
    def test_original_bytes_kept_exactly_and_not_linked(self):
        src = self.png("a.png", 1)
        record = self.lib.ingest_file(src, origin={"kind": "TEST"})
        stored = Path(record["object_path"])
        self.assertEqual(stored.read_bytes(), src.read_bytes())
        self.assertEqual(record["object_key"], f"objects/sha256/{record['content_sha256'][:2]}/{record['content_sha256']}.png")
        self.assertFalse(stored.is_symlink())
        self.assertNotEqual(os.stat(stored).st_ino, os.stat(src).st_ino)  # a copy, never a hard link
        self.assertEqual(os.stat(stored).st_mode & 0o222, 0)  # read only
        self.assertEqual((record["width"], record["height"]), (8, 8))

    def test_dedupe_by_bytes_only(self):
        a, b = self.png("same-a.png", 5), self.png("renamed.png", 5)
        other = self.png("same-a-name-different-bytes.png", 6)
        r1, r2, r3 = (self.lib.ingest_file(p) for p in (a, b, other))
        self.assertEqual(r1["content_sha256"], r2["content_sha256"])
        self.assertTrue(r1["created"] and not r2["created"])
        self.assertNotEqual(r1["content_sha256"], r3["content_sha256"])  # near-identical look is NOT merged
        objects = [p for p in (self.lib.root / "objects").rglob("*") if p.is_file()]
        self.assertEqual(len(objects), 2)

    def test_concurrent_threads_same_bytes_one_object(self):
        src = self.png("race.png", 9)
        results, errors = [], []

        def work():
            try:
                results.append(self.lib.ingest_file(src))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=work) for _ in range(12)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        self.assertEqual(sum(r["created"] for r in results), 1)
        self.assertEqual(len({r["content_sha256"] for r in results}), 1)
        self.assertEqual([p.name for p in (self.lib.root / "tmp").iterdir()], [])

    def test_concurrent_independent_processes_same_bytes_one_object(self):
        src = self.png("proc-race.png", 11)
        code = ("import json,sys;from tools.studio_asset_library import Library;"
                "r=Library(sys.argv[1]).ingest_file(sys.argv[2]);print(json.dumps({'c':r['created'],'s':r['content_sha256']}))")
        procs = [subprocess.Popen([sys.executable, "-c", code, str(self.lib.root), str(src)], cwd=REPO,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                  env={**os.environ, "PYTHONPATH": str(REPO)}) for _ in range(6)]
        outs = [p.communicate(timeout=120) + (p.returncode,) for p in procs]
        self.assertEqual([o[2] for o in outs], [0] * 6, [o[1] for o in outs])
        parsed = [json.loads(o[0]) for o in outs]
        self.assertEqual(sum(p["c"] for p in parsed), 1)
        report = self.lib.verify()
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(report["objects_checked"], 1)

    def test_source_not_a_file_and_empty_refused(self):
        with self.assertRaises(studio.StudioError):
            self.lib.ingest_file(self.tmp / "missing.png")
        empty = self.tmp / "empty.png"
        empty.write_bytes(b"")
        with self.assertRaises(studio.StudioError) as ctx:
            self.lib.ingest_file(empty)
        self.assertEqual(ctx.exception.code, "EMPTY_SOURCE_REFUSED")

    def test_origin_never_carries_absolute_path_or_signed_url(self):
        record = self.lib.ingest_file(self.png("o.png", 3), origin={
            "kind": "T", "source_path": "/some/where/private/x.png", "download_url": "https://h/x?X-Amz-Signature=abc",
            "note": "https://h/y?X-Amz-Signature=zzz", "api_key": "k"})
        text = json.dumps(record["origins"])
        self.assertNotIn("/some/where", text)
        self.assertNotIn("X-Amz", text)
        self.assertIn("LOCAL_PATH_REDACTED:x.png", text)


class VersionReviewBindingTests(Base):
    def test_same_content_is_same_version_and_new_content_is_new_version(self):
        a = self.approved_asset(seed=1)
        again = self.lib.register_version(category="characters", label="figure A", artifacts=[
            {"usage": "FRONT", "path": str(self.png("figure A-FRONT.png", 10))},
            {"usage": "FULL", "path": str(self.png("figure A-FULL.png", 11))}], asset_id=a["asset_id"])
        self.assertFalse(again["created"])
        self.assertEqual(again["version"], a["version"])
        v2 = self.lib.register_version(category="characters", label="figure A", asset_id=a["asset_id"],
                                       artifacts=[{"usage": "FRONT", "path": str(self.png("new-front.png", 99))}])
        self.assertTrue(v2["created"])
        self.assertEqual(v2["version"], 2)

    def test_same_version_different_content_is_a_reported_conflict_even_concurrently(self):
        outcomes = []

        def attempt(seed):
            try:
                self.lib.register_version(category="props", label="p", asset_id="AST-race-1", version=1,
                                          artifacts=[{"usage": "MAIN", "path": str(self.png(f"r{seed}.png", seed))}])
                outcomes.append("OK")
            except studio.StudioError as exc:
                outcomes.append(exc.code)

        threads = [threading.Thread(target=attempt, args=(s,)) for s in (21, 22, 23, 24)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(outcomes), ["OK", "VERSION_CONTENT_CONFLICT", "VERSION_CONTENT_CONFLICT", "VERSION_CONTENT_CONFLICT"])
        self.assertEqual(self.lib.versions_of("AST-race-1"), [1])

    def test_only_approved_is_selectable_unreviewed_and_rejected_stay_recorded(self):
        good = self.approved_asset(seed=1, label="good")
        pending = self.lib.register_version(category="props", label="pending", artifacts=[
            {"usage": "MAIN", "path": str(self.png("pending.png", 31))}])
        rejected = self.lib.register_version(category="props", label="rejected", artifacts=[
            {"usage": "MAIN", "path": str(self.png("rejected.png", 32))}])
        self.lib.set_review(rejected["asset_id"], 1, "REJECTED", None, reviewer="tester", note="failed")
        default = {r["asset_id"] for r in self.lib.search()}
        self.assertEqual(default, {good["asset_id"]})
        self.assertEqual({r["asset_id"] for r in self.lib.search(status="UNREVIEWED")}, {pending["asset_id"]})
        self.assertEqual({r["asset_id"] for r in self.lib.search(status="REJECTED")}, {rejected["asset_id"]})
        with self.assertRaises(studio.StudioError) as ctx:
            self.lib.bind("PROJ-X", "prop", "PROP-1", pending["asset_id"], 1)
        self.assertEqual(ctx.exception.code, "VERSION_NOT_APPROVED")

    def test_approval_requires_a_review_reference_with_a_sha(self):
        r = self.lib.register_version(category="props", label="p", artifacts=[{"usage": "M", "path": str(self.png("p.png", 41))}])
        for bad in (None, {"kind": "X"}, {"kind": "X", "sha256": "nothex"}):
            with self.assertRaises(studio.StudioError) as ctx:
                self.lib.set_review(r["asset_id"], 1, "APPROVED", bad)
            self.assertEqual(ctx.exception.code, "APPROVAL_REQUIRES_REVIEW_REFERENCE_WITH_SHA256")

    def test_new_version_does_not_change_a_pinned_binding(self):
        a = self.approved_asset(seed=2, label="pinned")
        self.lib.bind("PROJ-A", "character", "CHAR-1", a["asset_id"], 1, project_fields={"name": "A-name"})
        before = self.lib.resolve_binding("PROJ-A", "character", "CHAR-1", usage="FRONT", copy=False)
        v2 = self.lib.register_version(category="characters", label="pinned", asset_id=a["asset_id"],
                                       artifacts=[{"usage": "FRONT", "path": str(self.png("v2-front.png", 77))}])
        self.lib.set_review(v2["asset_id"], 2, "APPROVED", REVIEW_REF)
        self.assertEqual(self.lib.recommended_version(a["asset_id"]), 2)  # the recommendation moved...
        after = self.lib.resolve_binding("PROJ-A", "character", "CHAR-1", usage="FRONT", copy=False)
        self.assertEqual(before, after)  # ...the episode-facing pin did not
        self.assertEqual(after[0]["version"], 1)
        with self.assertRaises(studio.StudioError) as ctx:  # a different version needs an explicit rebind
            self.lib.bind("PROJ-A", "character", "CHAR-1", a["asset_id"], 2)
        self.assertEqual(ctx.exception.code, "BINDING_CONFLICT_REBIND_REQUIRED")

    def test_usage_is_explicit_no_costume_card_unless_pinned(self):
        a = self.approved_asset(seed=3, label="usage")
        self.lib.bind("PROJ-A", "character", "CHAR-U", a["asset_id"], 1, usages=["FRONT"])
        rows = self.lib.resolve_binding("PROJ-A", "character", "CHAR-U", copy=False)
        self.assertEqual([r["usage"] for r in rows], ["FRONT"])
        with self.assertRaises(studio.StudioError) as ctx:
            self.lib.resolve_binding("PROJ-A", "character", "CHAR-U", usage="FULL", copy=False)
        self.assertEqual(ctx.exception.code, "USAGE_NOT_PINNED")

    def test_cross_project_binding_shares_bytes_but_nothing_else(self):
        a = self.approved_asset(seed=4, label="shared actor")
        self.lib.bind("PROJ-A", "character", "CHAR-LEAD", a["asset_id"], 1,
                      project_fields={"name": "name in A", "relationship": "rel in A", "wardrobe": "wardrobe A", "voice": "voice A"})
        self.lib.bind("PROJ-B", "character", "CHAR-OTHER", a["asset_id"], 1,
                      project_fields={"name": "name in B", "wardrobe": "wardrobe B"})
        ba = self.lib.get_binding("PROJ-A", "character", "CHAR-LEAD")
        bb = self.lib.get_binding("PROJ-B", "character", "CHAR-OTHER")
        self.assertEqual({p["content_sha256"] for p in ba["pins"]}, {p["content_sha256"] for p in bb["pins"]})
        self.assertEqual(bb["project_fields"], {"name": "name in B", "wardrobe": "wardrobe B"})  # nothing inherited from A
        self.assertNotIn("voice", bb["project_fields"])
        self.assertNotIn("relationship", bb["project_fields"])
        self.assertTrue(bb["provenance"]["cross_project"])
        self.assertEqual(bb["provenance"]["origin_projects"], ["PROJ-A"])  # original provenance kept
        self.assertEqual({u["project_id"] for u in self.lib.used_by(a["asset_id"])}, {"PROJ-A", "PROJ-B"})
        # project isolation: a role bound only in A is invisible to B; no fall-through
        with self.assertRaises(studio.StudioError) as ctx:
            self.lib.resolve_binding("PROJ-B", "character", "CHAR-LEAD")
        self.assertEqual(ctx.exception.code, "BINDING_NOT_FOUND")
        self.assertEqual(self.lib.search(project="PROJ-B")[0]["asset_id"], a["asset_id"])

    def test_lineage_parent_and_transformation_never_overwrite_the_parent(self):
        a = self.approved_asset(seed=5, label="lineage")
        parent_sha = a["manifest"]["artifacts"][0]["content_sha256"]
        crop = self.png("crop.png", 123)
        child = self.lib.register_derivative(parent_sha, crop, {"operation": "CROP", "params": {"box": [0, 0, 4, 4]}})
        manifest = child["manifest"]
        self.assertEqual(manifest["parent_asset"]["asset_id"], a["asset_id"])
        self.assertEqual(manifest["transformation"]["source_sha256"], parent_sha)
        self.assertEqual(manifest["kind"], "DERIVATIVE")
        self.assertEqual(self.lib.get_version(a["asset_id"], 1)["artifacts"][0]["content_sha256"], parent_sha)
        with self.assertRaises(studio.StudioError) as ctx:  # an identical-bytes "derivative" is not a derivative
            self.lib.register_derivative(parent_sha, self.png("same.png", 50), {"operation": "COPY"})
        self.assertEqual(ctx.exception.code, "DERIVATIVE_IDENTICAL_TO_PARENT_BYTES")


class IntegrityAndRecoveryTests(Base):
    def test_resolve_legacy_serves_same_bytes_after_old_folder_is_gone(self):
        src = self.png("gone.png", 51)
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
        self.lib.ingest_file(src)
        self.lib.add_legacy_entry(sha, str(src), project_id="P", asset_id=None, version=None, artifact_id=None, source="T")
        old = src.read_bytes()
        src.unlink()
        found = self.lib.resolve_legacy(src, sha, cache_dir=self.tmp / "cache")
        self.assertEqual(found["status"], "STUDIO_OBJECT_COPY")
        self.assertEqual(Path(found["path"]).read_bytes(), old)
        self.assertEqual(Path(found["path"]).name, "gone.png")  # file name kept: view detection by name keeps working
        self.assertTrue(found["old_path_registered"])
        self.assertNotEqual(os.stat(found["path"]).st_ino, os.stat(self.lib.find_object(sha)).st_ino)

    def test_working_copy_edits_never_reach_the_master(self):
        src = self.png("m.png", 52)
        sha = self.lib.ingest_file(src)["content_sha256"]
        copy = self.lib.materialize(sha, self.tmp / "cache")
        os.chmod(copy, 0o644)
        copy.write_bytes(b"retouched")
        self.assertEqual(hashlib.sha256(self.lib.find_object(sha).read_bytes()).hexdigest(), sha)
        again = self.lib.materialize(sha, self.tmp / "cache")  # damaged cache is re-copied from the verified master
        self.assertEqual(hashlib.sha256(again.read_bytes()).hexdigest(), sha)

    def test_damaged_master_is_detected_and_only_a_matching_file_repairs_it(self):
        src = self.png("d.png", 53)
        sha = self.lib.ingest_file(src)["content_sha256"]
        master = self.lib.find_object(sha)
        os.chmod(master, 0o644)
        master.write_bytes(b"truncated")
        self.assertEqual(self.lib.verify()["status"], "FAIL")
        self.assertEqual(self.lib.verify()["corrupt"], [sha])
        with self.assertRaises(studio.StudioError) as ctx:
            self.lib.materialize(sha, self.tmp / "cache")
        self.assertEqual(ctx.exception.code, "OBJECT_CORRUPT")
        self.assertTrue((self.lib.root / "backup" / "restore_requests" / f"{sha}.json").is_file())  # a todo, not a regeneration
        impostor = self.png("impostor-same-name.png", 54)  # same name, different content
        report = self.lib.repair_object(sha, [impostor])
        self.assertEqual(report["status"], "NOT_REPAIRED")
        self.assertEqual(report["rejected"][0]["reason"], "SHA_MISMATCH_REJECTED")
        report = self.lib.repair_object(sha, [impostor, src])
        self.assertEqual(report["status"], "REPAIRED")
        self.assertEqual(self.lib.verify()["status"], "PASS")

    def test_missing_and_linked_masters_are_reported(self):
        a = self.png("l1.png", 61)
        b = self.png("l2.png", 62)
        sa, sb = (self.lib.ingest_file(p)["content_sha256"] for p in (a, b))
        self.lib.find_object(sa).unlink()
        mb = self.lib.find_object(sb)
        mb.unlink()
        os.symlink(b, mb)  # a link into an episode folder is not an independent original
        report = self.lib.verify()
        self.assertEqual((report["missing"], report["linked"]), ([sa], [sb]))

    def test_resolve_reference_uses_old_path_when_it_verifies_else_library(self):
        src = self.png("r.png", 71)
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
        with clean_env(**{studio.ENV_ROOT: str(self.lib.root)}):
            self.lib.ingest_file(src)
            self.assertEqual(studio.resolve_reference(src, sha), src)  # unchanged behaviour while the path is good
            src.write_bytes(b"changed in place")  # a path whose bytes moved is NOT accepted
            got = studio.resolve_reference(src, sha, cache_dir=self.tmp / "cache")
            self.assertNotEqual(got, src)
            self.assertEqual(hashlib.sha256(got.read_bytes()).hexdigest(), sha)
            self.assertIsNone(studio.resolve_reference(src, "0" * 64))  # unknown bytes: nothing, no regeneration
        with clean_env():  # library not enabled: nothing is resolved from it
            self.assertIsNone(studio.resolve_reference(self.tmp / "nowhere.png", sha))

    def test_resolve_reference_stops_on_damaged_master_instead_of_falling_through(self):
        src = self.png("rp.png", 72)
        sha = self.lib.ingest_file(src)["content_sha256"]
        master = self.lib.find_object(sha)
        os.chmod(master, 0o644)
        master.write_bytes(b"x")
        with clean_env(**{studio.ENV_ROOT: str(self.lib.root)}):
            with self.assertRaises(studio.StudioError) as ctx:
                studio.resolve_reference(self.tmp / "gone.png", sha, cache_dir=self.tmp / "c")
        self.assertEqual(ctx.exception.code, "RESTORE_PENDING")


class BundleTests(Base):
    def test_export_import_into_a_clean_library_is_verified_and_path_free(self):
        a = self.approved_asset(seed=8, label="portable")
        out = self.tmp / "bundle"
        report = studio.export_bundle(self.lib, [(a["asset_id"], 1)], out)
        self.assertEqual(report["status"], "EXPORTED")
        text = (out / "bundle.json").read_text()
        for needle in ("/Users", "/home/", "/private", str(self.tmp)):
            self.assertNotIn(needle, text)
        other = studio.Library(self.tmp / "other-device" / "studio")
        got = studio.import_bundle(other, out)
        self.assertEqual(got["versions_registered"], [f"{a['asset_id']}@v1"])
        self.assertEqual(other.verify()["status"], "PASS")
        rows = other.search()
        self.assertEqual([r["asset_id"] for r in rows], [a["asset_id"]])  # selectable on the new library
        other.bind("PROJ-NEW", "character", "CHAR-N", a["asset_id"], 1, project_fields={"name": "own"})
        paths = other.resolve_binding("PROJ-NEW", "character", "CHAR-N", cache_dir=self.tmp / "cache2")
        self.assertEqual({hashlib.sha256(Path(p["path"]).read_bytes()).hexdigest() for p in paths},
                         {x["content_sha256"] for x in a["manifest"]["artifacts"]})
        again = studio.import_bundle(other, out)  # idempotent
        self.assertEqual(again["versions_registered"], [])
        self.assertEqual(again["versions_already_present"], [f"{a['asset_id']}@v1"])

    def test_unapproved_is_not_exported_and_tampering_is_rejected(self):
        pend = self.lib.register_version(category="props", label="p", artifacts=[{"usage": "M", "path": str(self.png("e.png", 81))}])
        with self.assertRaises(studio.StudioError) as ctx:
            studio.export_bundle(self.lib, [(pend["asset_id"], 1)], self.tmp / "b1")
        self.assertEqual(ctx.exception.code, "EXPORT_REFUSED_NOT_APPROVED")
        a = self.approved_asset(seed=9, label="tamper")
        out = self.tmp / "b2"
        studio.export_bundle(self.lib, [(a["asset_id"], 1)], out)
        victim = next(out.rglob("*.png"))
        os.chmod(victim, 0o644)
        victim.write_bytes(png_bytes(8, 8, 200))
        with self.assertRaises(studio.StudioError) as ctx:
            studio.import_bundle(studio.Library(self.tmp / "dest"), out)
        self.assertEqual(ctx.exception.code, "BUNDLE_OBJECT_REJECTED")
        manifest = json.loads((out / "bundle.json").read_text())
        manifest["assets"][0]["manifest"]["label"] = "forged"
        (out / "bundle.json").write_text(json.dumps(manifest))
        with self.assertRaises(studio.StudioError) as ctx:
            studio.import_bundle(studio.Library(self.tmp / "dest2"), out)
        self.assertEqual(ctx.exception.code, "BUNDLE_MANIFEST_SHA_MISMATCH")

    def test_import_conflicts_with_same_version_different_content(self):
        a = self.approved_asset(seed=10, label="conf")
        out = self.tmp / "b3"
        studio.export_bundle(self.lib, [(a["asset_id"], 1)], out)
        other = studio.Library(self.tmp / "o2")
        other.register_version(category="characters", label="x", asset_id=a["asset_id"], version=1,
                               artifacts=[{"usage": "FRONT", "path": str(self.png("zz.png", 250))}])
        with self.assertRaises(studio.StudioError) as ctx:
            studio.import_bundle(other, out)
        self.assertEqual(ctx.exception.code, "VERSION_CONTENT_CONFLICT")


class CleanupBoundaryTests(Base):
    def test_episode_cache_cleanup_keeps_master_and_unique_files(self):
        episode = self.tmp / "ep"
        shared = write_png(episode / "plates" / "shared.png", 91)
        unique = write_png(episode / "plates" / "unique-not-in-library.png", 92)
        sha = self.lib.ingest_file(shared)["content_sha256"]
        plan = self.lib.episode_cache_cleanup_plan(episode)
        self.assertEqual([c["file"] for c in plan["cache_candidates"]], ["plates/shared.png"])
        self.assertTrue(any(k["file"].endswith("unique-not-in-library.png") and k["reason"].startswith("NOT_VERIFIED") for k in plan["kept"]))
        removed = self.lib.apply_episode_cache_cleanup(episode, plan)
        self.assertEqual(removed, ["plates/shared.png"])
        self.assertTrue(unique.is_file())  # the only copy is never a deletable cache
        self.assertEqual(self.lib.verify()["status"], "PASS")
        self.assertEqual(hashlib.sha256(self.lib.find_object(sha).read_bytes()).hexdigest(), sha)

    def test_cleanup_refuses_the_library_root_and_protects_in_use_paths(self):
        with self.assertRaises(studio.StudioError):
            self.lib.episode_cache_cleanup_plan(self.lib.root)
        with self.assertRaises(studio.StudioError):
            self.lib.episode_cache_cleanup_plan(self.lib.root / "objects")
        episode = self.tmp / "ep2"
        busy = write_png(episode / "busy.png", 93)
        self.lib.ingest_file(busy)
        plan = self.lib.episode_cache_cleanup_plan(episode, protect=[busy])
        self.assertEqual(plan["cache_candidates"], [])
        self.assertEqual(plan["kept"][0]["reason"], "PROTECTED_IN_USE")

    def test_no_verified_backup_means_no_releasable_original(self):
        self.lib.ingest_file(self.png("only.png", 94))
        plan = self.lib.library_release_plan()
        self.assertEqual(plan["releasable"], [])
        self.assertEqual(plan["held"][0]["state"], "LOCAL_ONLY_BACKUP_UNCONFIGURED")
        self.assertFalse(plan["deletes_anything"])


class BackupTests(Base):
    def _cfg(self):
        return {"state": "CONFIGURED_PRIVATE_ATTESTED", "bucket": "studio-private-bucket", "prefix": "studio-assets"}

    def test_unconfigured_is_honest_and_local_features_work(self):
        self.assertEqual(backup.backup_state({})["state"], "UNCONFIGURED")
        a = self.approved_asset(seed=12, label="local only")
        self.lib.bind("PROJ-A", "character", "CHAR-C", a["asset_id"], 1)
        self.assertEqual(len(self.lib.resolve_binding("PROJ-A", "character", "CHAR-C", cache_dir=self.tmp / "c")), 2)
        self.assertEqual(list((self.lib.root / "backup" / "queue").iterdir()), [])  # no invented todo
        report = backup.run(self.lib)
        self.assertEqual((report["status"], report["claim"]), ("UNCONFIGURED", "NOTHING_BACKED_UP"))
        sha = a["manifest"]["artifacts"][0]["content_sha256"]
        self.assertEqual(backup.object_storage_state(self.lib, sha), "LOCAL_ONLY_BACKUP_UNCONFIGURED")
        self.assertEqual(backup.restore_object(self.lib, sha)["status"], "UNCONFIGURED")

    def test_shared_or_public_buckets_are_refused(self):
        base = {**CONFIGURED}
        self.assertEqual(backup.backup_state({**base, "COLLECTIVE_OBJECT_BUCKET": base[backup.ENV_BUCKET]})["state"],
                         "REFUSED_BUCKET_SHARED_WITH_OTHER_PURPOSE")
        self.assertEqual(backup.backup_state({**base, "S3_RELAY_BUCKET": base[backup.ENV_BUCKET]})["state"],
                         "REFUSED_BUCKET_SHARED_WITH_OTHER_PURPOSE")
        no_access = {k: v for k, v in base.items() if k != backup.ENV_ACCESS}
        self.assertEqual(backup.backup_state(no_access)["state"], "REFUSED_ACCESS_MODE_NOT_DECLARED_PRIVATE")
        self.assertEqual(backup.backup_state({**base, backup.ENV_ACCESS: "public-read"})["state"],
                         "REFUSED_ACCESS_MODE_NOT_DECLARED_PRIVATE")
        self.assertEqual(backup.backup_state(base)["state"], "CONFIGURED_PRIVATE_ATTESTED")

    def test_run_verifies_by_readback_and_receipt_gates_storage_state(self):
        fake = FakeS3()
        with clean_env(**CONFIGURED):
            a = self.approved_asset(seed=13, label="to cloud")
            self.assertGreater(len(list((self.lib.root / "backup" / "queue").iterdir())), 0)
            report = backup.run(self.lib, client=fake, config=self._cfg())
            self.assertEqual(report["status"], "DONE", report)
            sha = a["manifest"]["artifacts"][0]["content_sha256"]
            self.assertEqual(backup.object_storage_state(self.lib, sha), "LOCAL_BACKUP_VERIFIED")
            self.assertEqual(list((self.lib.root / "backup" / "queue").iterdir()), [])
            keys = {k for (_, k) in fake.objects}
            self.assertIn(f"studio-assets/objects/sha256/{sha[:2]}/{sha}.png", keys)
            self.assertIn(f"studio-assets/catalog/assets/{a['asset_id']}/v0001.json", keys)
            self.assertTrue(any("/catalog/snapshots/assets/" in k and k.endswith(".json") for k in keys))
            self.assertEqual(backup.run(self.lib, client=fake, config=self._cfg())["status"], "NOTHING_QUEUED")

    def test_cloud_failure_keeps_the_todo_and_local_work_continues(self):
        fake = FakeS3()
        fake.fail_put = ConnectionError("network down")
        with clean_env(**CONFIGURED):
            a = self.approved_asset(seed=14, label="offline")
            report = backup.run(self.lib, client=fake, config=self._cfg())
            self.assertTrue(report["status"].startswith("PARTIAL"))
            self.assertGreater(len(list((self.lib.root / "backup" / "queue").iterdir())), 0)
            self.assertEqual(list((self.lib.root / "backup" / "receipts").iterdir()), [])  # nothing claimed
            failing = backup.status_report(self.lib)["failing"]
            self.assertTrue(failing and failing[0]["attempts"] == 1)
            self.lib.bind("PROJ-A", "character", "CHAR-C", a["asset_id"], 1)  # local use is unaffected
            self.assertTrue(self.lib.resolve_binding("PROJ-A", "character", "CHAR-C", cache_dir=self.tmp / "c"))
            fake.fail_put = None  # network back: the same queue completes
            self.assertEqual(backup.run(self.lib, client=fake, config=self._cfg())["status"], "DONE")

    def test_remote_key_with_other_bytes_is_never_overwritten(self):
        fake = FakeS3()
        with clean_env(**CONFIGURED):
            a = self.approved_asset(seed=15, label="conflict")
            sha = a["manifest"]["artifacts"][0]["content_sha256"]
            fake.objects[("studio-private-bucket", f"studio-assets/objects/sha256/{sha[:2]}/{sha}.png")] = (b"someone else", "x")
            report = backup.run(self.lib, client=fake, config=self._cfg())
            self.assertTrue(any("REMOTE_KEY_CONFLICT" in f["error"] for f in report["failed"]))
            self.assertEqual(fake.objects[("studio-private-bucket", f"studio-assets/objects/sha256/{sha[:2]}/{sha}.png")][0], b"someone else")
            self.assertNotEqual(backup.object_storage_state(self.lib, sha), "LOCAL_BACKUP_VERIFIED")

    def test_restore_accepts_only_matching_bytes(self):
        fake = FakeS3()
        with clean_env(**CONFIGURED):
            a = self.approved_asset(seed=16, label="restore")
            backup.run(self.lib, client=fake, config=self._cfg())
        sha = a["manifest"]["artifacts"][0]["content_sha256"]
        master = self.lib.find_object(sha)
        os.chmod(master, 0o644)
        master.unlink()
        self.assertEqual(backup.object_storage_state(self.lib, sha), "LOCAL_MISSING_BACKUP_VERIFIED")
        key = ("studio-private-bucket", f"studio-assets/objects/sha256/{sha[:2]}/{sha}.png")
        good = fake.objects[key]
        fake.objects[key] = (b"tampered remote bytes", good[1])
        rejected = backup.restore_object(self.lib, sha, client=fake, config=self._cfg())
        self.assertEqual(rejected["status"], "REJECTED_SHA_MISMATCH")
        self.assertIsNone(self.lib.find_object(sha))
        fake.objects[key] = good
        ok = backup.restore_object(self.lib, sha, client=fake, config=self._cfg())
        self.assertEqual(ok["status"], "RESTORED")
        self.assertEqual(self.lib.verify()["status"], "PASS")

    def test_catalog_rebuilds_from_remote_manifests_on_a_clean_library(self):
        fake = FakeS3()
        with clean_env(**CONFIGURED):
            a = self.approved_asset(seed=17, label="fresh device")
            self.lib.bind("PROJ-A", "character", "CHAR-R", a["asset_id"], 1, project_fields={"name": "kept"})
            backup.run(self.lib, client=fake, config=self._cfg())
        fresh = studio.Library(self.tmp / "fresh")
        report = backup.restore_catalog(fresh, client=fake, config=self._cfg())
        self.assertEqual(report["status"], "RESTORED_CATALOG", report)
        self.assertEqual(fresh.get_version(a["asset_id"], 1), self.lib.get_version(a["asset_id"], 1))
        self.assertEqual(fresh.get_review(a["asset_id"], 1)["review_status"], "APPROVED")
        self.assertEqual(fresh.get_binding("PROJ-A", "character", "CHAR-R")["project_fields"], {"name": "kept"})
        for artifact in a["manifest"]["artifacts"]:
            self.assertEqual(backup.restore_object(fresh, artifact["content_sha256"], client=fake, config=self._cfg())["status"], "RESTORED")
        self.assertEqual(fresh.verify()["status"], "PASS")
        self.assertEqual(backup.restore_catalog(fresh, client=fake, config=self._cfg())["conflicts"], [])  # idempotent

    def test_no_unsupported_gateway_operation_is_used(self):
        source = Path(backup.__file__).read_text()
        for name in ("put_object_tagging", "get_bucket_versioning", "put_object_lock_configuration", "list_object_versions"):
            self.assertNotIn(name, source)


class MigrationTests(Base):
    def _runtime(self):
        old = self.tmp / "old_runtime"
        plates = old / "workflow" / "E02" / "identity" / "plates"
        front, full = write_png(plates / "CHAR-X__FRONT.png", 101), write_png(plates / "CHAR-X.png", 102)
        prop = write_png(plates / "PROP-Y.png", 103)
        bad = write_png(plates / "PROP-BAD.png", 104)
        conflict = write_png(plates / "PROP-CHANGED.png", 105)
        sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()  # noqa: E731
        row = lambda aid, label, status, qa, arts: {"asset_id": aid, "label": label, "status": status,  # noqa: E731
                                                     "qa": {"status": qa, "reviewer": "r", "checks": []}, "artifacts": arts}
        library = {"schema": "ai_drama.production_asset_library.v1", "project_id": "OLD-PROJ", "assets": {
            "characters": {"CHAR-X": row("CHAR-X", "X", "LOCKED", "PASS", [
                {"role": "FRONT_NEUTRAL_HEADSHOT", "path": str(front), "sha256": sha(front)},
                {"role": "FULL_BODY_STANDING", "path": str(full), "sha256": sha(full)},
                {"role": "GONE", "path": str(plates / "missing.png"), "sha256": "e" * 64}])},
            "props": {"PROP-Y": row("PROP-Y", "Y", "LOCKED", "PASS", [{"role": "FULL_BODY_STANDING", "path": str(prop), "sha256": sha(prop)}]),
                      "PROP-BAD": row("PROP-BAD", "bad", "QA_FAILED_NOT_LOCKED", "FAIL", [{"role": "FULL_BODY_STANDING", "path": str(bad), "sha256": sha(bad)}]),
                      "PROP-CHANGED": row("PROP-CHANGED", "changed", "LOCKED", "PASS", [{"role": "FULL_BODY_STANDING", "path": str(conflict), "sha256": "d" * 64}])}}}
        lib_file = old / "runtime" / "asset_library.json"
        lib_file.parent.mkdir(parents=True)
        lib_file.write_text(json.dumps(library))
        (old / "receipt.json").write_text(json.dumps({"submit": "payload", "sha": "x"}))
        (old / "tx.json").write_text(json.dumps({"state": "BOUND"}))
        return old, lib_file, {"front": front, "full": full, "prop": prop, "bad": bad}

    def test_preview_counts_everything_and_writes_nothing(self):
        old, lib_file, _ = self._runtime()
        root = self.tmp / "migrated"
        report = migrate.run(root, libraries=[str(lib_file)])
        self.assertEqual(report["mode"], "PREVIEW")
        self.assertEqual(report["references"], 6)
        self.assertEqual(report["unique_objects_present"], 4)
        self.assertEqual(report["unique_objects_new"], 4)
        self.assertEqual(report["missing_files"], 1)
        self.assertEqual(report["sha_conflicts"], 1)
        self.assertEqual(report["unapproved_references"], 1)  # the QA_FAILED row; the conflicting one is approved-but-changed
        self.assertTrue(report["disk"]["enough_space"])
        self.assertGreater(report["bytes_to_add"], 0)
        self.assertFalse(root.exists())  # a preview creates nothing

    def test_apply_is_idempotent_keeps_old_files_and_builds_the_compat_map(self):
        old, lib_file, files = self._runtime()
        history_before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (lib_file, old / "receipt.json", old / "tx.json")}
        root = self.tmp / "migrated"
        first = migrate.run(root, libraries=[str(lib_file)], apply=True)
        self.assertEqual(first["status"], "APPLIED")
        self.assertEqual(first["objects_ingested_new"], 4)
        second = migrate.run(root, libraries=[str(lib_file)], apply=True)
        self.assertEqual(second["objects_ingested_new"], 0)
        self.assertEqual(second["versions_registered_new"], 0)
        lib = studio.Library(root, create=False)
        self.assertEqual(lib.verify()["status"], "PASS")
        self.assertEqual(len([p for p in (root / "objects").rglob("*") if p.is_file()]), 4)
        self.assertTrue(all(f.is_file() for f in files.values()))  # old files kept
        self.assertEqual(history_before, {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (lib_file, old / "receipt.json", old / "tx.json")})
        sha = hashlib.sha256(files["front"].read_bytes()).hexdigest()
        entry = studio.read_json(lib.legacy_path(sha))["entries"][0]
        self.assertEqual((entry["old_path"], entry["project_id"]), (str(files["front"]), "OLD-PROJ"))
        approved = {r["label"] for r in lib.search()}
        self.assertEqual(approved, {"X", "Y"})  # the failed row is recorded, not selectable
        self.assertEqual({r["label"] for r in lib.search(status="REJECTED")}, {"bad"})
        self.assertIsNotNone(lib.get_binding("OLD-PROJ", "character", "CHAR-X"))
        self.assertIsNone(lib.get_binding("OLD-PROJ", "prop", "PROP-BAD"))  # never bound
        self.assertEqual(lib.get_binding("OLD-PROJ", "character", "CHAR-X")["project_fields"], {"label": "X"})

    def test_old_files_gone_after_import_bytes_still_resolve(self):
        old, lib_file, files = self._runtime()
        root = self.tmp / "migrated"
        migrate.run(root, libraries=[str(lib_file)], apply=True)
        want = {k: hashlib.sha256(v.read_bytes()).hexdigest() for k, v in files.items()}
        for path in files.values():
            path.unlink()
        lib = studio.Library(root, create=False)
        for key in ("front", "full", "prop"):
            found = lib.resolve_legacy(files[key], want[key], cache_dir=self.tmp / "cache")
            self.assertEqual(found["status"], "STUDIO_OBJECT_COPY")
            self.assertEqual(hashlib.sha256(Path(found["path"]).read_bytes()).hexdigest(), want[key])

    def test_insufficient_disk_blocks_apply_with_a_number(self):
        old, lib_file, _ = self._runtime()
        with mock.patch.object(migrate, "_headroom", return_value={"free_bytes": 10, "total_bytes": 100}):
            report = migrate.run(self.tmp / "m2", libraries=[str(lib_file)], apply=True)
        self.assertEqual(report["status"], "BLOCKED_INSUFFICIENT_DISK_SPACE")
        self.assertGreater(report["disk"]["shortfall_bytes"], 0)
        self.assertFalse((self.tmp / "m2").exists())

    def test_batch_limit_defers_the_rest(self):
        old, lib_file, _ = self._runtime()
        first = migrate.run(self.tmp / "m3", libraries=[str(lib_file)], apply=True, limit=2)
        self.assertEqual(first["objects_ingested_new"], 2)
        done = migrate.run(self.tmp / "m3", libraries=[str(lib_file)], apply=True)
        self.assertEqual(done["objects_ingested_new"], 2)


class IndexTests(Base):
    def test_index_page_lists_selectable_assets_with_relative_links_and_escapes_labels(self):
        a = self.approved_asset(seed=18, label="<b>x</b> & y")
        page = self.lib.build_index(self.tmp / "idx", thumbnails=False)
        html_text = page.read_text()
        self.assertIn("&lt;b&gt;x&lt;/b&gt; &amp; y", html_text)
        self.assertNotIn(str(self.tmp), html_text)  # relative links only
        self.assertIn(a["manifest"]["artifacts"][0]["content_sha256"][:12], html_text)

    def test_thumbnail_is_a_derivative_never_the_original(self):
        a = self.approved_asset(seed=19, label="thumb")
        sha = a["manifest"]["artifacts"][0]["content_sha256"]
        thumb = self.lib.thumbnail(sha)
        if thumb is None:
            self.skipTest("no ffmpeg/sips on this machine")
        self.assertEqual(thumb.suffix, ".jpg")
        self.assertEqual(hashlib.sha256(self.lib.find_object(sha).read_bytes()).hexdigest(), sha)


class HookTests(Base):
    def test_hooks_are_inert_until_the_library_is_enabled(self):
        out = studio.archive_harvested_image(self.png("h.png", 111), episode="E01", row={"task_key": "T"}, project_id="P")
        self.assertEqual(out["status"], "STUDIO_LIBRARY_NOT_ENABLED")
        self.assertEqual(list((self.lib.root / "objects" / "sha256").iterdir()), [])

    def test_harvest_archive_is_unreviewed_and_refuses_a_sha_that_disagrees(self):
        src = self.png("h2.png", 112)
        sha = hashlib.sha256(src.read_bytes()).hexdigest()
        with clean_env(**{studio.ENV_ROOT: str(self.lib.root)}):
            out = studio.archive_harvested_image(src, episode="E01", project_id="P", row={"task_key": "K", "task_id": "T1", "sha256": sha})
            self.assertEqual(out["status"], "ARCHIVED_UNREVIEWED")
            bad = studio.archive_harvested_image(src, episode="E01", project_id="P", row={"task_key": "K", "sha256": "f" * 64})
            self.assertEqual(bad["status"], "ARCHIVE_REFUSED_SHA_DIFFERS_FROM_HARVEST_RECORD")
        self.assertEqual(self.lib.search(), [])  # not selectable
        self.assertEqual(len(self.lib.search(status="UNREVIEWED")), 1)
        origin = self.lib.object_record(sha)["origins"][0]
        self.assertEqual((origin["task_id"], origin["task_key"], origin["episode"]), ("T1", "K", "E01"))


if __name__ == "__main__":
    unittest.main()
