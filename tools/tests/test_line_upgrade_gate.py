"""tools/line_upgrade_gate.py + tools/knowledge_sync_core.py on synthetic repos (offline)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "tools" / "line_upgrade_gate.py"
NALU_SYNC = REPO / "lines" / "nalu" / "runtime" / "tools" / "knowledge_sync.py"
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def _rule(key: str, **extra) -> dict:
    row = {"id": key, "stage": "pipeline", "rule": f"rule {key}", "lesson": "l", "recovery": "r",
           "implementation": ["tools/knowledge_registry.py"], "status": "REFERENCE_IMPLEMENTATION",
           "owner": "o", "authority": "a", "decision_record": "docs/decisions/DECISION_RECORDS.md",
           "regression": "tools/tests/test_knowledge_registry.py", "runtime_gate_added": False}
    row.update(extra)
    return row


class LineUpgradeGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.env = dict(os.environ, **GIT_ENV)
        self.env.pop("PYTHONPATH", None)
        self.env.pop("QINGSHAN_ENGINE_OVERLAY_DIRS", None)
        self.origin = self.tmp / "origin.git"
        self.engine = self.tmp / "engine"
        self.runtime = self.tmp / "runtime"
        self.runtime.mkdir()
        self._git(self.tmp, "init", "--bare", "-b", "main", str(self.origin))
        seed = self.tmp / "seed"
        self._git(self.tmp, "clone", "-q", str(self.origin), str(seed))
        self._populate(seed)
        self._git(seed, "add", "-A")
        self._git(seed, "commit", "-qm", "seed")
        self._git(seed, "push", "-q", "origin", "HEAD:main")
        self._git(self.tmp, "clone", "-q", str(self.origin), str(self.engine))
        self.seed = seed

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------ fixtures
    def _git(self, cwd: Path, *args: str) -> None:
        subprocess.run(["git", *args], cwd=cwd, env=self.env, check=True, capture_output=True)

    def _populate(self, root: Path) -> None:
        for rel in ("tools/knowledge_registry.py", "tools/knowledge_sync_core.py", "tools/line_upgrade_gate.py"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, root / rel)
        (root / "tools/tests").mkdir(parents=True, exist_ok=True)
        (root / "tools/tests/test_knowledge_registry.py").write_text("# stub\n")
        (root / "tools/sample_gate.py").write_text("VALUE = 1\n")
        (root / "docs/decisions").mkdir(parents=True)
        (root / "docs/decisions/DECISION_RECORDS.md").write_text("# decisions\n")
        (root / "docs/knowledge").mkdir(parents=True)
        (root / "docs/knowledge/ENGINEERING_KNOWLEDGE_BASE.md").write_text("# kb\n")
        rules = [_rule("K001"), _rule("K002", failure_code="HOOK_MISSING", do_not_repeat="hook first",
                                      scope="episode", category="c", stage="prompt")]
        registry = {"schema": "qingshan.knowledge_registry.v1", "version": "1.0.0",
                    "scope": "PORTABLE_KNOWLEDGE_NOT_PRODUCTION_AUTHORIZATION", "license": "x",
                    "rules": rules}
        (root / "configs").mkdir()
        (root / "configs/ENGINEERING_KNOWLEDGE_V1.json").write_text(json.dumps(registry, indent=2))
        (root / "knowledge").mkdir()
        (root / "knowledge/failure_memory.jsonl").write_text(json.dumps(
            {"failure_code": "HOOK_MISSING", "do_not_repeat": "hook first", "stage": "prompt",
             "scope": "episode", "knowledge_id": "K002"}) + "\n")

    def _run(self, *args: str, extra_env: dict | None = None) -> tuple[int, dict]:
        env = dict(self.env, **(extra_env or {}))
        proc = subprocess.run([sys.executable, str(GATE), *args], env=env, capture_output=True, text=True)
        try:
            return proc.returncode, json.loads(proc.stdout)
        except ValueError:
            self.fail(proc.stdout + proc.stderr)

    def _preflight(self, *extra: str, extra_env: dict | None = None) -> tuple[int, dict]:
        return self._run("preflight", "--line", "testline", "--episode", "E01",
                         "--runtime-root", str(self.runtime), "--engine-root", str(self.engine),
                         *extra, extra_env=extra_env)

    def _overlay(self, body: str = "VALUE = 2\n") -> Path:
        overlay = self.tmp / "elsewhere" / "overlay_local"
        (overlay / "tools").mkdir(parents=True)
        (overlay / "tools/sample_gate.py").write_text(body)
        return overlay

    # ------------------------------------------------------------------ freshness
    def test_fresh_engine_passes(self) -> None:
        code, out = self._preflight()
        self.assertEqual((code, out["status"]), (0, "PASS"), out)
        self.assertEqual(out["engine"]["behind"], 0)
        self.assertEqual(out["overlays"]["status"], "PASS")

    def test_head_behind_tracking_branch_is_stale(self) -> None:
        (self.seed / "tools/sample_gate.py").write_text("VALUE = 3\n")
        self._git(self.seed, "commit", "-qam", "upstream moved")
        self._git(self.seed, "push", "-q", "origin", "HEAD:main")
        code, out = self._preflight()  # no fetch: tracking ref still old
        self.assertEqual(out["status"], "PASS")
        code, out = self._preflight("--fetch")
        self.assertEqual((code, out["status"]), (0, "STALE_ENGINE"), out)
        self.assertEqual(out["engine"]["behind"], 1)
        code, out = self._preflight("--strict")
        self.assertEqual((code, out["status"], out["blocking"]), (2, "STALE_ENGINE", True))

    def test_dirty_tracked_file_is_reported_not_failed(self) -> None:
        (self.engine / "tools/sample_gate.py").write_text("VALUE = 9\n")
        code, out = self._preflight()
        self.assertEqual(out["status"], "PASS")
        self.assertIn("DIRTY_TRACKED_FILES", out["notes"])
        self.assertIn("tools/sample_gate.py", out["engine"]["dirty_tracked_files"])

    # ------------------------------------------------------------------ overlays
    def test_overlay_shadowing_engine_module_is_undeclared(self) -> None:
        overlay = self._overlay()
        code, out = self._preflight("--overlay-dir", str(overlay))
        self.assertEqual((code, out["status"]), (0, "UNDECLARED_OVERLAY"), out)
        shadow = out["overlays"]["overlays"][0]["shadowed_modules"]
        self.assertEqual([row["module"] for row in shadow], ["tools.sample_gate"])
        self.assertNotEqual(shadow[0]["overlay_sha256"], shadow[0]["engine_sha256"])
        code, _ = self._preflight("--overlay-dir", str(overlay), "--strict")
        self.assertEqual(code, 2)

    def test_overlay_is_auto_discovered_next_to_runtime(self) -> None:
        overlay = self.runtime / "engine_overlay_prod" / "tools"
        overlay.mkdir(parents=True)
        (overlay / "sample_gate.py").write_text("VALUE = 2\n")
        _, out = self._preflight()
        self.assertEqual(out["status"], "UNDECLARED_OVERLAY")

    def test_identical_overlay_copy_is_not_shadowing(self) -> None:
        overlay = self._overlay("VALUE = 1\n")
        _, out = self._preflight("--overlay-dir", str(overlay))
        self.assertEqual(out["status"], "PASS")

    def test_declared_overlay_is_reported_not_failed(self) -> None:
        overlay = self._overlay()
        for args, env in ((("--declare-overlay", str(overlay)), None),
                          (("--overlay-dir", str(overlay)),
                           {"QINGSHAN_ENGINE_OVERLAY_DIRS": str(overlay)})):
            code, out = self._preflight(*args, "--strict", extra_env=env)
            self.assertEqual((code, out["status"]), (0, "PASS"), out)
            self.assertIn("DECLARED_OVERLAY", out["notes"])
            row = out["overlays"]["overlays"][0]
            self.assertEqual((row["declared"], row["status"]), (True, "DECLARED_OVERLAY"))
            self.assertEqual(row["shadowed_modules"][0]["module"], "tools.sample_gate")

    # ------------------------------------------------------------------ knowledge read / close
    def test_briefing_contains_every_registry_rule(self) -> None:
        _, out = self._preflight()
        brief_path = self.runtime / "reports" / "E01_KNOWLEDGE_BRIEFING.json"
        brief = json.loads(brief_path.read_text())
        registry = json.loads((self.engine / "configs/ENGINEERING_KNOWLEDGE_V1.json").read_text())
        ids = [row["id"] for row in registry["rules"]]
        self.assertEqual(brief["rule_ids"], ids)
        self.assertEqual([row["id"] for row in brief["context"]["rules"]], ids)
        self.assertEqual([row["failure_code"] for row in brief["failure_memory"]], ["HOOK_MISSING"])
        self.assertTrue(brief["failure_memory_in_sync"])
        self.assertEqual(len(brief["registry_sha256"]), 64)
        md = (self.runtime / "reports" / "E01_KNOWLEDGE_BRIEFING.md").read_text()
        for key in ids + ["HOOK_MISSING", brief["registry_sha256"]]:
            self.assertIn(key, md)
        self.assertTrue((self.runtime / "reports" / "E01_LINE_UPGRADE_PREFLIGHT.json").is_file())
        self.assertEqual(out["knowledge"]["status"], "READ")

    def test_close_without_briefing_is_knowledge_not_read(self) -> None:
        args = ("close", "--line", "testline", "--episode", "E02", "--runtime-root", str(self.runtime),
                "--engine-root", str(self.engine))
        code, out = self._run(*args)
        self.assertEqual((code, out["status"]), (0, "KNOWLEDGE_NOT_READ"), out)
        self.assertEqual(out["knowledge_sync"]["status"], "NO_NEW_KNOWLEDGE")
        code, out = self._run(*args, "--strict")
        self.assertEqual(code, 2)

    def test_preflight_then_close_writes_authored_rows(self) -> None:
        self._preflight()
        (self.runtime / "reports" / "E01_knowledge_candidates.json").write_text(json.dumps([
            {"key": "x", "stage": "pipeline", "rule": "abstract rule", "lesson": "l", "recovery": "rec",
             "status": "GUIDANCE_ONLY", "implementation": [], "authority": "a", "evidence": "e"}]))
        args = ("close", "--line", "testline", "--episode", "E01", "--runtime-root", str(self.runtime),
                "--engine-root", str(self.engine))
        code, out = self._run(*args)
        self.assertEqual((code, out["status"]), (0, "PASS"), out)
        self.assertEqual(out["knowledge_read"]["status"], "READ")
        self.assertTrue(out["knowledge_read"]["receipt_matches"])
        self.assertEqual(out["knowledge_sync"]["new_ids"], ["K003"])
        registry = json.loads((self.engine / "configs/ENGINEERING_KNOWLEDGE_V1.json").read_text())
        self.assertEqual(registry["rules"][-1]["id"], "K003")
        self.assertIn("K003", (self.engine / "docs/knowledge/ENGINEERING_KNOWLEDGE_BASE.md").read_text())
        _, again = self._run(*args)  # idempotent
        self.assertEqual(again["knowledge_sync"]["status"], "NO_NEW_KNOWLEDGE")

    # ------------------------------------------------------------------ nalu wrapper unchanged
    def test_nalu_knowledge_sync_cli_unchanged(self) -> None:
        copy = self.tmp / "realcopy"
        (copy / "configs").mkdir(parents=True)
        shutil.copy2(REPO / "configs/ENGINEERING_KNOWLEDGE_V1.json", copy / "configs/")
        rt = self.tmp / "rt"
        (rt / "reports").mkdir(parents=True)
        (rt / "reports" / "E99_knowledge_candidates.json").write_text(json.dumps([
            {"key": "x", "stage": "pipeline", "rule": "r", "lesson": "l", "recovery": "rec",
             "status": "GUIDANCE_ONLY", "implementation": [], "authority": "a", "evidence": "e"},
            {"key": "gap", "stage": "pipeline", "rule": "r", "lesson": "l", "recovery": "",
             "status": "GUIDANCE_ONLY", "implementation": [], "authority": "a", "evidence": "e"}]))
        before = (copy / "configs/ENGINEERING_KNOWLEDGE_V1.json").read_bytes()
        rule_count = len(json.loads(before)["rules"])
        env = dict(self.env, NALU_ENGINE_ROOT=str(REPO), NALU_RUNTIME_ROOT=str(rt))
        proc = subprocess.run([sys.executable, str(NALU_SYNC), "--episode", "E99", "--root", str(copy),
                               "--runtime-root", str(rt), "--dry-run"], env=env, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"status": "DRY_RUN", "episode": "E99", "new_ids": [],
                                                   "candidates": 2, "gaps": ["E99-gap"],
                                                   "rule_count": rule_count})
        self.assertEqual((copy / "configs/ENGINEERING_KNOWLEDGE_V1.json").read_bytes(), before)
        (rt / "not_a_list.json").write_text("{}")
        proc = subprocess.run([sys.executable, str(NALU_SYNC), "--episode", "E99", "--root", str(copy),
                               "--runtime-root", str(rt), "--from-file", str(rt / "not_a_list.json")],
                              env=env, capture_output=True, text=True)
        self.assertEqual((proc.returncode, json.loads(proc.stdout)["status"]), (1, "FAIL"))
        sys.path.insert(0, str(NALU_SYNC.parent))
        try:
            import knowledge_sync as ks
            import importlib
            core = importlib.import_module("knowledge_sync_core")
        finally:
            sys.path.remove(str(NALU_SYNC.parent))
        for name in ("REGISTRY", "MARKDOWN", "FAILURE_MEMORY", "FORBIDDEN_TOKENS", "sync", "assign_ids",
                     "candidates_from_evidence", "_next_id", "_clean", "_markdown_section"):
            self.assertIs(getattr(ks, name), getattr(core, name))
        self.assertEqual(ks._next_id([{"id": "K070"}]), "K071")


if __name__ == "__main__":
    unittest.main()
