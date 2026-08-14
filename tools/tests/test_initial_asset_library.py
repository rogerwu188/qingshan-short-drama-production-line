#!/usr/bin/env python3

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools/initial_asset_library.py"
SPEC = importlib.util.spec_from_file_location("initial_asset_library", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def requirement(category: str, index: int, *, priority: str = "SERIES_CORE") -> dict:
    return {
        "asset_id": f"{category.upper()}-{index:02d}",
        "label": f"{category} {index}",
        "priority": priority,
        "first_use_episode": 1,
        "required_in_episodes": [1],
        "authority_refs": [{"source_id": "canonical", "sha256": SHA_A}],
        "specification": {"description": f"locked {category}"},
    }


def requirements() -> dict:
    return {
        "schema": MODULE.SCHEMA_REQUIREMENTS,
        "project_id": "project-001",
        "canonical_sha256": SHA_A,
        "series_bible_sha256": SHA_B,
        "assets": {
            category: [requirement(category, index)]
            for index, category in enumerate(MODULE.CATEGORIES, 1)
        },
    }


def lock_asset(category: str, asset: dict) -> None:
    lock_values = {
        "identity_lock": "same face and body",
        "owner_character_id": "CHAR-01",
        "appearance_lock": "same material, shape and color",
        "spatial_topology": "fixed entrance, windows and light direction",
        "physical_function": "performs the scripted contact action",
        "language": "zh-CN",
        "accent_id": "ACCENTS-06",
        "provider_voice_id": "voice-remote-1",
        "native_dialogue_eligible": True,
        "locale": "zh-CN",
        "pronunciation_profile": "natural standard Mandarin",
        "usage_scope": "series theme and controlled scene use",
        "musical_identity": "restrained mystery motif",
        "scene_scope": "interior room tone",
        "sound_field": "continuous natural stereo ambience",
        "physical_source": "wooden door contact",
        "sync_event": "hand reaches latch",
    }
    asset["status"] = "LOCKED"
    asset["lock"] = {
        field: lock_values[field] for field in MODULE.CATEGORY_LOCK_FIELDS[category]
    }
    asset["artifacts"] = [
        {
            "role": "canonical_reference",
            "media_type": "image/jpeg" if category not in {"voices", "music", "ambience", "sfx", "accents"} else "audio/wav",
            "provider_asset_id": f"remote-{asset['asset_id']}",
            "sha256": SHA_C,
        }
    ]
    asset["provenance"] = [{"source": "approved_generation", "task_id": "task-1"}]
    asset["rights"] = {"status": "PASS", "basis": "project-owned generated asset"}
    asset["qa"] = {"status": "PASS", "checks": ["identity", "continuity", "playable"]}


class InitialAssetLibraryTest(unittest.TestCase):
    def test_compile_creates_all_categories_and_gate_blocks_unlocked_assets(self) -> None:
        source = requirements()
        library, summary = MODULE.compile_library(source, None)
        self.assertEqual(summary["requirement_count"], len(MODULE.CATEGORIES))
        self.assertEqual(set(library["assets"]), set(MODULE.CATEGORIES))
        report = MODULE.gate_library(library, source, 1)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["failure_count"], len(MODULE.CATEGORIES))

    def test_gate_passes_only_after_every_required_asset_is_locked(self) -> None:
        source = requirements()
        library, _ = MODULE.compile_library(source, None)
        for category in MODULE.CATEGORIES:
            for asset in library["assets"][category].values():
                lock_asset(category, asset)
        report = MODULE.gate_library(library, source, 1)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["checked_asset_count"], len(MODULE.CATEGORIES))

    def test_changed_requirement_invalidates_a_locked_asset_without_deleting_history(self) -> None:
        source = requirements()
        library, _ = MODULE.compile_library(source, None)
        character = next(iter(library["assets"]["characters"].values()))
        lock_asset("characters", character)
        updated = copy.deepcopy(source)
        updated["assets"]["characters"][0]["specification"]["description"] = "new canonical face"
        rebuilt, summary = MODULE.compile_library(updated, library)
        changed = next(iter(rebuilt["assets"]["characters"].values()))
        self.assertEqual(changed["status"], "NEEDS_REVALIDATION")
        self.assertEqual(changed["version"], 2)
        self.assertEqual(changed["supersedes"], f"{changed['asset_id']}@v1")
        self.assertEqual(len(changed["history"]), 1)
        self.assertEqual(changed["history"][0]["status"], "LOCKED")
        self.assertEqual(changed["history"][0]["artifacts"], changed["artifacts"])
        self.assertIn(changed["asset_id"], summary["needs_revalidation"])
        self.assertTrue(changed["artifacts"])

    def test_episode_gate_ignores_future_optional_assets(self) -> None:
        source = requirements()
        future = requirement("props", 99, priority="OPTIONAL")
        future["first_use_episode"] = 9
        future["required_in_episodes"] = [9]
        source["assets"]["props"].append(future)
        library, _ = MODULE.compile_library(source, None)
        for category in MODULE.CATEGORIES:
            for asset in library["assets"][category].values():
                if asset["asset_id"] != future["asset_id"]:
                    lock_asset(category, asset)
        self.assertEqual(MODULE.gate_library(library, source, "E01")["status"], "PASS")
        self.assertEqual(MODULE.gate_library(library, source, "EP09")["status"], "FAIL")

    def test_atomic_write_replaces_existing_library(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            library_path = root / "library.json"
            library_path.write_text('{"stale": true}\n', encoding="utf-8")
            MODULE.atomic_write_json(library_path, {"ok": True})
            self.assertEqual(json.loads(library_path.read_text(encoding="utf-8")), {"ok": True})
            self.assertFalse(list(root.glob(f".{library_path.name}.*.tmp")))


if __name__ == "__main__":
    unittest.main()
