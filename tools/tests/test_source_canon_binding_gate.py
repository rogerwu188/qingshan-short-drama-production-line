import argparse
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.source_canon_binding_gate import evaluate


def write_json(path: Path, payload: dict) -> str:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SourceCanonBindingGateTests(unittest.TestCase):
    def build_fixture(self, root: Path) -> argparse.Namespace:
        chapter_sha = "a" * 64
        source_path = root / "SOURCE_INGEST_MANIFEST.json"
        source_sha = write_json(source_path, {
            "schema": "qingshan.source_ingest_manifest.v1",
            "status": "PASS",
            "source_type": "url",
            "source_ref": "https://example.test/novel",
            "locked_scope": {"chapter_ids": ["CH001"]},
            "chapters": [{
                "chapter_id": "CH001",
                "source_ref": "https://example.test/chapter-1",
                "content_sha256": chapter_sha,
                "read_status": "READ",
                "fetched_at": "2026-07-24T00:00:00Z",
            }],
        })
        canon_path = root / "CANON_FACTS.json"
        facts = []
        for index, category in enumerate(("protagonist", "world", "era", "weather_daylight", "opening_event"), start=1):
            facts.append({
                "fact_id": f"F{index}",
                "category": category,
                "value": f"canonical-{category}",
                "source_refs": [{"chapter_id": "CH001", "content_sha256": chapter_sha}],
            })
        canon_sha = write_json(canon_path, {
            "schema": "qingshan.canon_facts.v1",
            "status": "PASS",
            "source_manifest_sha256": source_sha,
            "facts": facts,
        })
        beat_path = root / "CHAPTER_BEAT_MAP.json"
        beat_sha = write_json(beat_path, {
            "schema": "qingshan.chapter_beat_map.v1",
            "status": "PASS",
            "source_manifest_sha256": source_sha,
            "canon_facts_sha256": canon_sha,
            "episodes": [{
                "episode": "E01",
                "source_chapters": ["CH001"],
                "canon_fact_ids": ["F1", "F2", "F3", "F4", "F5"],
                "source_events": [{"event_id": "EV1", "chapter_id": "CH001", "content_sha256": chapter_sha}],
            }],
        })
        script_path = root / "E01.md"
        script_path.write_text("canonical script", encoding="utf-8")
        script_sha = hashlib.sha256(script_path.read_bytes()).hexdigest()
        series_path = root / "FULL_SERIES_MANIFEST.json"
        series_sha = write_json(series_path, {
            "schema": "qingshan.full_series_manifest.v1",
            "status": "PASS",
            "source_manifest_sha256": source_sha,
            "canon_facts_sha256": canon_sha,
            "beat_map_sha256": beat_sha,
            "scripts": [{
                "episode": "E01",
                "path": "E01.md",
                "sha256": script_sha,
                "source_bindings": {
                    "source_chapters": ["CH001"],
                    "canon_fact_ids": ["F1", "F2", "F3", "F4", "F5"],
                    "source_event_ids": ["EV1"],
                },
            }],
        })
        fidelity_path = root / "FULL_SERIES_SOURCE_FIDELITY.json"
        write_json(fidelity_path, {
            "schema": "qingshan.full_series_source_fidelity.v1",
            "auditor_agent": "qingshan-ai-aduit",
            "status": "PASS",
            "score_100": 96,
            "source_manifest_sha256": source_sha,
            "canon_facts_sha256": canon_sha,
            "beat_map_sha256": beat_sha,
            "full_series_manifest_sha256": series_sha,
            "episodes": [{
                "episode": "E01",
                "status": "PASS",
                "score_100": 96,
                "script_sha256": script_sha,
                "critical_fact_comparisons": [
                    {"category": category, "matches": True}
                    for category in ("protagonist", "world", "era", "weather_daylight", "opening_event")
                ],
            }],
        })
        return argparse.Namespace(
            mode="fidelity",
            source_manifest=source_path,
            canon_facts=canon_path,
            beat_map=beat_path,
            full_series_manifest=series_path,
            fidelity_report=fidelity_path,
            episode=None,
            canonical_script_sha256=None,
        )

    def test_full_chain_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.build_fixture(Path(temp))
            self.assertEqual(evaluate(args)["status"], "PASS")

    def test_unread_chapter_blocks_source(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.build_fixture(Path(temp))
            payload = json.loads(args.source_manifest.read_text(encoding="utf-8"))
            payload["chapters"][0]["read_status"] = "DISCOVERED"
            write_json(args.source_manifest, payload)
            args.mode = "source"
            args.full_series_manifest = None
            args.fidelity_report = None
            result = evaluate(args)
            self.assertEqual(result["status"], "BLOCKED_SOURCE_NOT_READ")
            self.assertIn("chapter_not_read:CH001", result["failures"])

    def test_missing_episode_binding_blocks_script(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.build_fixture(Path(temp))
            payload = json.loads(args.full_series_manifest.read_text(encoding="utf-8"))
            payload["scripts"][0]["source_bindings"]["source_event_ids"] = []
            write_json(args.full_series_manifest, payload)
            args.mode = "script"
            args.fidelity_report = None
            args.episode = "E01"
            args.canonical_script_sha256 = payload["scripts"][0]["sha256"]
            result = evaluate(args)
            self.assertEqual(result["status"], "BLOCKED_SOURCE_CANON_BINDING_MISSING")
            self.assertIn("script_source_event_binding_incomplete:E01", result["failures"])

    def test_failed_critical_comparison_blocks_full_series(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.build_fixture(Path(temp))
            report = json.loads(args.fidelity_report.read_text(encoding="utf-8"))
            report["episodes"][0]["critical_fact_comparisons"][0]["matches"] = False
            write_json(args.fidelity_report, report)
            result = evaluate(args)
            self.assertEqual(result["status"], "BLOCKED_SCRIPT_CANON_MISMATCH")
            self.assertTrue(any("protagonist" in item for item in result["failures"]))

    def test_major_transformation_requires_separate_approval(self):
        with tempfile.TemporaryDirectory() as temp:
            args = self.build_fixture(Path(temp))
            payload = json.loads(args.source_manifest.read_text(encoding="utf-8"))
            payload["adaptation_transform_authorization"] = {
                "status": "NOT_APPROVED",
                "requested_transformations": ["era", "protagonist_identity"],
                "allowed_transformations": [],
            }
            write_json(args.source_manifest, payload)
            args.mode = "source"
            args.full_series_manifest = None
            args.fidelity_report = None
            result = evaluate(args)
            self.assertEqual(result["status"], "BLOCKED_SOURCE_NOT_READ")
            self.assertTrue(any(item.startswith("unauthorized_major_transformation") for item in result["failures"]))


if __name__ == "__main__":
    unittest.main()
