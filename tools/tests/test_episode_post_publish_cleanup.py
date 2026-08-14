#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools/episode_post_publish_cleanup.py"
SPEC = importlib.util.spec_from_file_location("episode_post_publish_cleanup", PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class EpisodePostPublishCleanupTests(unittest.TestCase):
    def fixture(self, published_hours_ago: float = 25) -> tuple[Path, dict, Path, Path]:
        root = Path(tempfile.mkdtemp())
        project = root / "project"
        episode = project / "episodes/E01"
        assets = episode / "intermediates"
        final_dir = episode / "final"
        receipts = episode / "release_receipts"
        assets.mkdir(parents=True)
        final_dir.mkdir()
        receipts.mkdir()
        (assets / "frame.png").write_bytes(b"frame")
        (assets / "clip.mp4").write_bytes(b"clip")
        (assets / "notes.md").write_text("notes", encoding="utf-8")
        old_final = final_dir / "final-v1.mp4"
        old_final.write_bytes(b"old")
        latest = final_dir / "final-v2.mp4"
        latest.write_bytes(b"latest")
        release = receipts / "youtube.json"
        release.write_text('{"status":"PUBLISHED"}', encoding="utf-8")
        published = datetime.now(timezone.utc) - timedelta(hours=published_hours_ago)
        archive_receipt = root / "central_receipts/E01_s3_archive.json"
        archive_receipt.parent.mkdir(parents=True)
        archive_receipt.write_text(json.dumps({
            "schema": "qingshan.s3_episode_archive_receipt.v1",
            "status": "VERIFIED",
            "project_id": "project-1",
            "episode": "E01",
            "source_sha256": MODULE.sha256(latest),
            "remote_sha256": MODULE.sha256(latest),
            "bucket": "shared",
            "key": "published-finals/project-1/E01/v2/final-v2.mp4",
            "head_verified": True,
            "stream_readback_verified": True,
        }), encoding="utf-8")
        manifest = {
            "schema": MODULE.SCHEMA,
            "project_id": "project-1",
            "episode": "E01",
            "project_root": str(project),
            "episode_root": str(episode),
            "scope_complete": True,
            "retention_hours": 24,
            "required_release_targets": ["youtube"],
            "release_receipts": [
                {
                    "target": "youtube",
                    "status": "PUBLISHED",
                    "published_at": published.isoformat(),
                    "path": str(release),
                    "sha256": MODULE.sha256(release),
                }
            ],
            "latest_final": {
                "version": "v2",
                "path": str(latest),
                "sha256": MODULE.sha256(latest),
            },
            "cloud_archive": {
                "provider": "s3",
                "status": "VERIFIED",
                "bucket": "shared",
                "key": "published-finals/project-1/E01/v2/final-v2.mp4",
                "object_sha256": MODULE.sha256(latest),
                "receipt_path": str(archive_receipt),
                "receipt_sha256": MODULE.sha256(archive_receipt),
            },
            "cleanup_roots": [str(episode)],
        }
        return root, manifest, latest, assets

    def test_blocks_before_24_hour_hold_expires(self) -> None:
        root, manifest, _latest, _assets = self.fixture(23.5)
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        plan = MODULE.build_plan(manifest, datetime.now(timezone.utc))
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertTrue(any(item.startswith("retention_hold_active") for item in plan["failures"]))

    def test_apply_deletes_all_local_episode_files_after_verified_s3_archive(self) -> None:
        root, manifest, latest, _assets = self.fixture(25)
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        plan = MODULE.build_plan(manifest, datetime.now(timezone.utc))
        out = root / "central_receipts/E01_cleanup.json"
        receipt = MODULE.apply_plan(plan, out)
        self.assertFalse(latest.exists())
        episode_root = Path(manifest["episode_root"])
        self.assertFalse(episode_root.exists())
        self.assertEqual(receipt["status"], "PASS")
        self.assertTrue(out.is_file())

    def test_rejects_cleanup_root_outside_episode(self) -> None:
        root, manifest, _latest, _assets = self.fixture(25)
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        outside = root / "shared_asset_library"
        outside.mkdir()
        (outside / "character.png").write_bytes(b"keep")
        manifest["cleanup_roots"] = [str(outside)]
        plan = MODULE.build_plan(manifest, datetime.now(timezone.utc))
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertTrue((outside / "character.png").is_file())

    def test_rejects_cleanup_receipt_inside_episode(self) -> None:
        root, manifest, _latest, _assets = self.fixture(25)
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        plan = MODULE.build_plan(manifest, datetime.now(timezone.utc))
        inside = Path(manifest["episode_root"]) / "cleanup.json"
        with self.assertRaisesRegex(ValueError, "outside_episode_root"):
            MODULE.apply_plan(plan, inside)

    def test_apply_requires_matching_dry_run_fingerprint(self) -> None:
        root, manifest, _latest, _assets = self.fixture(25)
        self.addCleanup(lambda: __import__("shutil").rmtree(root, ignore_errors=True))
        plan = MODULE.build_plan(manifest, datetime.now(timezone.utc))
        approval = root / "central_receipts/E01_cleanup_dry_run.json"
        MODULE.atomic_write(
            approval,
            {
                "schema": MODULE.RECEIPT_SCHEMA,
                **plan,
                "status": "DRY_RUN_READY",
            },
        )
        self.assertEqual(
            MODULE.validate_dry_run_approval(approval, plan)["plan_fingerprint"],
            plan["plan_fingerprint"],
        )
        changed = dict(plan)
        changed["delete_files"] = [*plan["delete_files"], "/unexpected"]
        changed["plan_fingerprint"] = MODULE.plan_fingerprint(changed)
        with self.assertRaisesRegex(ValueError, "plan_changed"):
            MODULE.validate_dry_run_approval(approval, changed)


if __name__ == "__main__":
    unittest.main()
