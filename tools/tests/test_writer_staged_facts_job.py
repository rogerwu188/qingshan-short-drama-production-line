import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.agent_task_journal import recover_task_state
from tools.writer_staged_facts_job import (
    accept_draft,
    accept_merged_evidence,
    append_atomic,
    bind_next_chapter,
    read_facts,
    record_evidence_note,
    record_dispatch,
    start_job,
    validate_draft,
)


def fact_row(n):
    return {
        "n": n,
        "title": f"chapter {n}",
        "summary": "full summary with causal detail",
        "characters": ["A", "B"],
        "locations": ["hall"],
        "key_events": [{"cause": "x", "effect": "y"}],
        "relationships": [{"from": "A", "to": "B", "change": "trust"}],
        "open_threads": ["thread"],
        "powers_items": ["item"],
        "time_weather": {"time": "day", "weather": "clear"},
        "source_anchors": ["paragraph 1"],
    }


class WriterStagedFactsJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.shared = self.root / "shared"
        self.project = self.shared / "factory/projects/p1"
        self.facts = self.project / "source/facts/chapter_facts.jsonl"
        self.checkpoint = self.project / "source/corpus/checkpoint.tsv"
        self.source = self.project / "source/corpus/chapter_0471.txt"
        self.version = self.shared / "factory/versions/2.0.13-dev"
        self.runtime = self.version / "runtime"
        self.facts.parent.mkdir(parents=True)
        self.checkpoint.parent.mkdir(parents=True)
        self.version.mkdir(parents=True)
        self.runtime.mkdir(parents=True)
        self.facts.write_text(
            "".join(
                json.dumps(fact_row(chapter), ensure_ascii=False) + "\n"
                for chapter in range(1, 471)
            ),
            encoding="utf-8",
        )
        self.checkpoint.write_text("470\tsha470\n", encoding="utf-8")
        paragraphs = [f"第{i}段：这是需要完整阅读并提取证据的正文。\n\n" for i in range(500)]
        self.source.write_text("".join(paragraphs), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def start(self):
        return start_job(
            self.shared,
            project_root=self.project,
            facts=self.facts,
            checkpoint=self.checkpoint,
            source=self.source,
            chapter=471,
            target_last=472,
            job_id="full-corpus-1",
            lease_id="lease-1",
            fence=7,
            cron_id="cron-1",
            package_version="2.0.13-dev",
            version_root=self.version,
            runtime_root=self.runtime,
            max_chars=1200,
        )

    def write_json(self, name, payload):
        path = self.root / name
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def complete_evidence(self, job):
        for index in range(job["fragment_count"]):
            note = self.write_json(f"note-{index}.json", {"facts": [f"evidence-{index}"]})
            job = record_evidence_note(self.shared, index, note)
        merged = self.write_json(
            "merged.json",
            {
                "chapter_n": 471,
                "source_sha256": job["source_sha256"],
                "fragments_used": list(range(job["fragment_count"])),
                "facts": ["all evidence represented"],
            },
        )
        return accept_merged_evidence(self.shared, merged)

    def test_large_chapter_is_resumable_and_appends_once(self):
        job = self.start()
        self.assertGreater(job["fragment_count"], 4)
        self.assertEqual(
            job["next_phase_event"]["dispatch_owner_agent_id"],
            "qingshan-producer-supervisor",
        )
        self.assertLessEqual(
            max(len(json.loads(line)["text"]) for line in Path(job["evidence_fragments_path"]).read_text(encoding="utf-8").splitlines()),
            1200,
        )
        job = self.complete_evidence(job)
        draft = self.write_json("draft.json", fact_row(471))
        job = accept_draft(self.shared, draft)
        self.assertEqual(job["phase"], "VALIDATE")
        job = validate_draft(self.shared)
        self.assertEqual(job["phase"], "APPEND_ATOMIC")
        job = append_atomic(self.shared)
        self.assertEqual(job["phase"], "NEXT_CHAPTER")
        self.assertEqual([row["n"] for row in read_facts(self.facts)][-2:], [470, 471])
        recovered = recover_task_state(self.shared, "qingshan-claude-writer")
        self.assertTrue(recovered["resume_required"])
        self.assertEqual(recovered["active_job"]["chapter_n"], 472)

    def test_recovery_does_not_depend_on_cwd(self):
        job = self.start()
        old = Path.cwd()
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        try:
            os.chdir(elsewhere)
            recovered = recover_task_state(self.shared, "qingshan-claude-writer")
        finally:
            os.chdir(old)
        self.assertTrue(recovered["active_job_valid"])
        self.assertEqual(recovered["active_job"]["source_path"], str(self.source))
        self.assertEqual(job["phase"], "READ_EVIDENCE")

    def test_completion_chained_dispatch_is_durable(self):
        self.start()
        job = record_dispatch(
            self.shared,
            dispatch_id="one-shot-472-draft",
            pending_key="full-corpus-1:471:READ_EVIDENCE:sha",
            next_due="2026-07-25T20:00:15Z",
            dispatch_mode="completion_chained_one_shot",
            watchdog_id="watchdog-1",
        )
        self.assertEqual(job["chained_dispatch_id"], "one-shot-472-draft")
        recovered = recover_task_state(self.shared, "qingshan-claude-writer")
        self.assertEqual(
            recovered["active_job"]["pending_key"],
            "full-corpus-1:471:READ_EVIDENCE:sha",
        )

    def test_schema_degradation_is_rejected_without_append(self):
        job = self.complete_evidence(self.start())
        slim = {"n": 471, "title": "slim"}
        draft = self.write_json("slim.json", slim)
        with self.assertRaisesRegex(ValueError, "schema mismatch"):
            accept_draft(self.shared, draft)
        self.assertEqual(read_facts(self.facts)[-1]["n"], 470)

    def test_fragment_tamper_blocks_progress(self):
        job = self.start()
        fragment_path = Path(job["evidence_fragments_path"])
        fragment_path.write_text("tampered\n", encoding="utf-8")
        note = self.write_json("note.json", {"facts": ["x"]})
        with self.assertRaisesRegex(ValueError, "SHA verification"):
            record_evidence_note(self.shared, 0, note)

    def test_next_chapter_binding_uses_absolute_source(self):
        job = self.complete_evidence(self.start())
        accept_draft(self.shared, self.write_json("draft.json", fact_row(471)))
        validate_draft(self.shared)
        append_atomic(self.shared)
        source_472 = self.project / "source/corpus/chapter_0472.txt"
        source_472.write_text("chapter 472 full text", encoding="utf-8")
        job = bind_next_chapter(self.shared, source_472, 1000)
        self.assertEqual(job["chapter_n"], 472)
        self.assertEqual(job["phase"], "READ_EVIDENCE")
        self.assertTrue(Path(job["source_path"]).is_absolute())


if __name__ == "__main__":
    unittest.main()
