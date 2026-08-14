import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    ROOT
    / "workflow/cloud_factory_migration_v1_20260724/customer_workbench/build_status.py"
)
SPEC = importlib.util.spec_from_file_location("customer_workbench_builder", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class CustomerProducerWorkbenchTest(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        project = root / "project_demo"
        (project / "intake").mkdir(parents=True)
        (project / "credits").mkdir()
        (project / "episodes/E01/jobs").mkdir(parents=True)
        (project / "release").mkdir()
        (project / "intake/project.json").write_text(
            json.dumps(
                {
                    "schema": "qingshan.factory.project_intake.v2",
                    "tenant_id": "tenant_demo",
                    "project_id": "project_demo",
                    "title": "云端测试剧",
                    "creative": {"episode_count": 2},
                    "budget": {"limit": 6000, "currency": "provider_credits"},
                    "distribution": {"platforms": ["tiktok"]},
                    "stage": "INTAKE",
                    "status": "PASS",
                    "created_at": "2026-07-24T00:00:00Z",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (project / "project_ledger.jsonl").write_text(
            "\n".join(
                json.dumps(item, ensure_ascii=False)
                for item in (
                    {
                        "project_id": "project_demo",
                        "stage": "FULL_SERIES_WRITER",
                        "status": "PASS_READY_FOR_SUPERVISOR_SCRIPT_GATE",
                        "episodes_written": 2,
                        "from_agent": "qingshan-claude-writer",
                        "created_at": "2026-07-24T00:01:00Z",
                    },
                    {
                        "project_id": "project_demo",
                        "stage": "FULL_SERIES_SCRIPT_GATE",
                        "status": "PASS",
                        "from_agent": "qingshan-producer-supervisor",
                        "created_at": "2026-07-24T00:02:00Z",
                    },
                    {
                        "project_id": "project_demo",
                        "episode_id": "E01",
                        "stage": "PIPELINE",
                        "status": "RUNNING",
                        "progress_percent": 50,
                        "to_agent": "qingshan-ai-drama-pipeline",
                        "created_at": "2026-07-24T00:03:00Z",
                    },
                )
            )
            + "\n",
            encoding="utf-8",
        )
        (project / "credits/ledger.jsonl").write_text(
            "\n".join(
                json.dumps(item)
                for item in (
                    {
                        "project_id": "project_demo",
                        "episode_id": "E01",
                        "provider_task_id": "task-settled",
                        "credit_status": "SETTLED",
                        "settled_credits": 120,
                        "created_at": "2026-07-24T00:04:00Z",
                    },
                    {
                        "project_id": "project_demo",
                        "episode_id": "E01",
                        "provider_task_id": "task-refund",
                        "credit_status": "PENDING_REFUND",
                        "pending_refund_credits": 80,
                        "created_at": "2026-07-24T00:05:00Z",
                    },
                )
            )
            + "\n",
            encoding="utf-8",
        )
        (project / "release/tiktok.json").write_text(
            json.dumps(
                {
                    "project_id": "project_demo",
                    "platform": "tiktok",
                    "status": "ACCOUNT_CONNECTION_REQUIRED",
                    "created_at": "2026-07-24T00:06:00Z",
                }
            ),
            encoding="utf-8",
        )
        return project

    def make_gate_registry(self, root: Path) -> Path:
        registry = root / "gate_registry.json"
        registry.write_text(
            json.dumps(
                {
                    "version": "test-v1",
                    "gates": [
                        {"gate_id": "SCRIPT-READINESS", "stage": "SCRIPT", "parameters": {}},
                        {"gate_id": "FINAL-AUDIT", "stage": "AUDIT_FINAL", "parameters": {}},
                        {
                            "gate_id": "E21-ONLY",
                            "stage": "SCRIPT",
                            "parameters": {"applies_to_episodes": "E21_PLUS"},
                        },
                    ],
                    "withdrawn_gates": [{"former_gate_id": "WITHDRAWN-GATE"}],
                }
            ),
            encoding="utf-8",
        )
        return registry

    def test_snapshot_reports_pipeline_costs_refund_and_full_series_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(Path(tmp))
            snapshot = MODULE.build_snapshot(
                project,
                "tenant_demo",
                "project_demo",
                generated_at="2026-07-24T00:10:00Z",
            )
            self.assertEqual(snapshot["project"]["title"], "云端测试剧")
            self.assertEqual(snapshot["project"]["stage"], "PIPELINE")
            self.assertEqual(snapshot["script"]["completed_episodes"], 2)
            self.assertEqual(snapshot["script"]["gate_status"], "COMPLETE")
            self.assertEqual(snapshot["budget"]["settled"], 120)
            self.assertEqual(snapshot["budget"]["pending_refund"], 80)
            self.assertEqual(snapshot["budget"]["remaining"], 5800)
            self.assertEqual(snapshot["data_quality"]["unknown_credit_records"], 0)
            e01 = next(item for item in snapshot["episodes"] if item["episode_id"] == "E01")
            self.assertEqual(e01["settled_credits"], 120)

    def test_missing_credit_amount_stays_unknown_and_is_not_estimated(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(Path(tmp))
            with (project / "credits/ledger.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "project_id": "project_demo",
                            "provider_task_id": "task-unknown",
                            "credit_status": "SETTLED",
                            "created_at": "2026-07-24T00:07:00Z",
                        }
                    )
                    + "\n"
                )
            snapshot = MODULE.build_snapshot(project, "tenant_demo", "project_demo")
            self.assertEqual(snapshot["data_quality"]["unknown_credit_records"], 1)
            self.assertIsNone(snapshot["budget"]["remaining"])

    def test_full_series_manifest_overrides_stale_one_episode_intake(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(Path(tmp))
            intake_path = project / "intake/project.json"
            intake = json.loads(intake_path.read_text(encoding="utf-8"))
            intake["creative"]["episode_count"] = 1
            intake_path.write_text(json.dumps(intake), encoding="utf-8")
            episode_root = project / "full_series/episodes"
            for index in range(1, 13):
                (episode_root / f"ep{index:03d}").mkdir(parents=True)
            (project / "full_series/FULL_SERIES_MANIFEST.json").write_text(
                json.dumps(
                    {
                        "project_id": "project_demo",
                        "stage": "FULL_SERIES_SCRIPT_GATE",
                        "status": "PASS",
                        "total_episode_count": 12,
                        "created_at": "2026-07-24T00:09:00Z",
                    }
                ),
                encoding="utf-8",
            )
            snapshot = MODULE.build_snapshot(project, "tenant_demo", "project_demo")
            self.assertEqual(snapshot["project"]["episode_count"], 12)
            self.assertEqual(snapshot["script"]["total_episodes"], 12)
            self.assertEqual(len(snapshot["episodes"]), 12)

    def test_output_is_customer_safe_and_writes_offline_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = self.make_project(Path(tmp))
            (project / "blocked.json").write_text(
                json.dumps(
                    {
                        "project_id": "project_demo",
                        "stage": "PIPELINE",
                        "status": "BLOCKED",
                        "error_code": "PROVIDER_AUTH",
                        "message": "API_KEY=do-not-expose",
                        "created_at": "2026-07-24T00:08:00Z",
                    }
                ),
                encoding="utf-8",
            )
            snapshot = MODULE.build_snapshot(project, "tenant_demo", "project_demo")
            out = Path(tmp) / "published-workbench"
            MODULE.write_workbench(snapshot, out)
            serialized = (out / "status.json").read_text(encoding="utf-8")
            self.assertNotIn("do-not-expose", serialized)
            self.assertNotIn(str(project), serialized)
            self.assertTrue((out / "index.html").is_file())
            self.assertTrue((out / "status.js").is_file())

    def test_each_episode_reports_all_applicable_gates_scores_and_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root)
            registry = self.make_gate_registry(root)
            qa_root = project / "episodes/E01/qa"
            qa_root.mkdir(parents=True)
            (qa_root / "script_gate.json").write_text(
                json.dumps(
                    {
                        "project_id": "project_demo",
                        "episode_id": "E01",
                        "gate_id": "SCRIPT-READINESS",
                        "stage": "SCRIPT",
                        "status": "PASS",
                        "score": 88,
                        "threshold": 80,
                        "created_at": "2026-07-24T00:07:00Z",
                    }
                ),
                encoding="utf-8",
            )
            (qa_root / "final_lock.json").write_text(
                json.dumps(
                    {
                        "project_id": "project_demo",
                        "episode_id": "E01",
                        "stage": "AUDIT_FINAL",
                        "created_at": "2026-07-24T00:08:00Z",
                        "gates": {
                            "FINAL-AUDIT": {
                                "status": "FAIL",
                                "items": [
                                    {"score_100": 92, "minimum_score_100": 80},
                                    {"score_100": 74, "minimum_score_100": 80},
                                ],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            snapshot = MODULE.build_snapshot(
                project,
                "tenant_demo",
                "project_demo",
                gate_registry_path=registry,
            )
            e01 = next(item for item in snapshot["episodes"] if item["episode_id"] == "E01")
            self.assertEqual(e01["gate_summary"]["total"], 2)
            self.assertEqual(e01["gate_summary"]["passed"], 1)
            self.assertEqual(e01["gate_summary"]["failed"], 1)
            self.assertEqual(e01["gate_summary"]["pass_rate_percent"], 50.0)
            self.assertEqual(e01["gate_summary"]["lowest_score"], 74)
            gates = {item["gate_id"]: item for item in e01["gates"]}
            self.assertNotIn("E21-ONLY", gates)
            self.assertEqual(gates["SCRIPT-READINESS"]["score"], 88)
            self.assertEqual(gates["SCRIPT-READINESS"]["threshold"], 80)
            self.assertEqual(gates["FINAL-AUDIT"]["status"], "FAIL")
            self.assertEqual(gates["FINAL-AUDIT"]["score"], 74)
            self.assertEqual(gates["FINAL-AUDIT"]["score_method"], "minimum_item")
            self.assertEqual(gates["FINAL-AUDIT"]["evidence"], "episodes/E01/qa/final_lock.json")
            self.assertNotIn(str(project), json.dumps(snapshot))

    def test_unexecuted_registered_gates_are_not_reported_as_passed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root)
            snapshot = MODULE.build_snapshot(
                project,
                "tenant_demo",
                "project_demo",
                gate_registry_path=self.make_gate_registry(root),
            )
            e02 = next(item for item in snapshot["episodes"] if item["episode_id"] == "E02")
            self.assertEqual(e02["gate_summary"]["total"], 2)
            self.assertEqual(e02["gate_summary"]["not_run"], 2)
            self.assertTrue(all(item["status"] == "NOT_RUN" for item in e02["gates"]))

    def test_rejects_path_traversal_segments(self):
        with self.assertRaises(ValueError):
            MODULE.resolve_project_root(Path("/tmp/shared"), "../tenant", "project", None)
        with self.assertRaises(ValueError):
            MODULE.resolve_project_root(Path("/tmp/shared"), "tenant", "../project", None)


if __name__ == "__main__":
    unittest.main()
