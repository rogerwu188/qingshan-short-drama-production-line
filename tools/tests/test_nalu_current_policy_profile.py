import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "lines/nalu/runtime/tools/nalu_policy_profile.py"
SPEC = importlib.util.spec_from_file_location("nalu_policy_profile", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class NaluCurrentPolicyProfileTests(unittest.TestCase):
    def test_historical_default_keeps_legacy_e01_exception(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(MODULE.selected(), MODULE.LEGACY)
            self.assertTrue(MODULE.uses_legacy_first_episode_exception("E01"))

    def test_non_default_series_uses_current_policy_for_e01(self):
        with patch.dict(os.environ, {"NALU_SERIES_SCOPE_ID": "FOBENSHIDAO"}, clear=True):
            self.assertEqual(MODULE.selected(), MODULE.CURRENT)
            self.assertFalse(MODULE.uses_legacy_first_episode_exception("E01"))

    def test_explicit_current_profile_wins_for_default_scope(self):
        with patch.dict(os.environ, {
            "NALU_SERIES_SCOPE_ID": "NALU-YEWUJIANG",
            "NALU_POLICY_PROFILE": "CURRENT_PORTABLE",
        }, clear=True):
            self.assertTrue(MODULE.is_current())

    def test_unknown_profile_fails_closed(self):
        with patch.dict(os.environ, {"NALU_POLICY_PROFILE": "RELAXED"}, clear=True):
            with self.assertRaises(SystemExit):
                MODULE.selected()

    def test_new_series_e01_static_design_failures_are_blocking(self):
        contract = {
            "episode": "E01",
            "shots": [{
                "shot_id": "E01-S01-01",
                "scene_id": "E01-S01",
                "target_seconds": 4,
                "prompt_spec": {
                    "camera_plan": {
                        "motion_family": "LOCKED",
                        "camera_side": "FRONT",
                        "shot_scale": "MEDIUM",
                    },
                    "dialogue": "",
                    "action": {"primary_action": "站立"},
                },
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            contract_path = Path(tmp) / "contract.json"
            out = Path(tmp) / "report.json"
            contract_path.write_text(json.dumps(contract), encoding="utf-8")
            env = os.environ.copy()
            env["NALU_SERIES_SCOPE_ID"] = "FOBENSHIDAO"
            completed = subprocess.run([
                sys.executable,
                str(ROOT / "lines/nalu/runtime/tools/static_design_gate.py"),
                "--contract", str(contract_path),
                "--episode", "E01",
                "--out", str(out),
            ], cwd=ROOT, env=env, check=False, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 3, completed.stdout + completed.stderr)
            report = json.loads(out.read_text())
            self.assertEqual(report["mode"], "BLOCKING")
            self.assertEqual(report["policy_profile"], "CURRENT_PORTABLE")

    def test_new_series_e01_uses_current_post_generation_pacing(self):
        env = os.environ.copy()
        env["NALU_SERIES_SCOPE_ID"] = "FOBENSHIDAO"
        code = (
            "import json,sys;"
            f"sys.path.insert(0,{str(ROOT / 'lines/nalu/runtime/tools')!r});"
            "import post_generation_qa_runner as p;"
            "print(json.dumps(p.pacing_policy('E01')))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, env=env,
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(json.loads(completed.stdout)["static_hold_reject"])

    def test_pipeline_current_e01_uses_current_pacing_and_configured_python(self):
        env = os.environ.copy()
        env.update({
            "NALU_SERIES_SCOPE_ID": "PORTABLE-DEMO",
            "NALU_POLICY_PROFILE": "CURRENT_PORTABLE",
            "NALU_VENV_PYTHON": sys.executable,
        })
        code = """
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
import nalu_pipeline as p
ctx = object.__new__(p.Ctx)
ctx.episode = "E01"
class Paths: pass
ctx.p = Paths()
ctx.p.scope = {
    "voice_registry": pathlib.Path("/tmp/voice.json"),
    "entity_registry": pathlib.Path("/tmp/entity.json"),
    "agentcut_voice_policy": pathlib.Path("/tmp/voice_policy.json"),
    "character_registry": pathlib.Path("/tmp/missing-character-registry.json"),
}
child = ctx.child_env(paid=False)
print(json.dumps({
    "venv": str(p.VENV),
    "preferred": child.get("QINGSHAN_UNIT_PREFERRED_SECONDS"),
    "maximum": child.get("QINGSHAN_UNIT_MAX_SECONDS"),
    "minimum": child.get("QINGSHAN_UNIT_MIN_SECONDS"),
}))
"""
        completed = subprocess.run(
            [sys.executable, "-c", code, str(ROOT / "lines/nalu/runtime/tools")],
            cwd=ROOT, env=env, check=False, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["venv"], sys.executable)
        self.assertEqual(payload["preferred"], "4,6")
        self.assertEqual(payload["maximum"], "8")
        self.assertEqual(payload["minimum"], "4")

    def test_current_writer_selfcheck_requires_explicit_enforced_pass(self):
        env = os.environ.copy()
        env.update({
            "NALU_POLICY_PROFILE": "CURRENT_PORTABLE",
            "NALU_VENV_PYTHON": sys.executable,
        })
        code = """
import json, sys
sys.path.insert(0, sys.argv[1])
import nalu_pipeline as p
print(json.dumps([
    p.writer_selfcheck_admitted({"status": "PASS", "enforced": True}, 0),
    p.writer_selfcheck_admitted({"status": "PASS", "enforced": False}, 0),
    p.writer_selfcheck_admitted({"status": "FAIL", "enforced": True}, 3),
]))
"""
        completed = subprocess.run(
            [sys.executable, "-c", code, str(ROOT / "lines/nalu/runtime/tools")],
            cwd=ROOT, env=env, check=False, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout), [True, False, False])

    def test_current_s1_checks_layer_existence_before_hashing(self):
        env = os.environ.copy()
        env.update({
            "NALU_POLICY_PROFILE": "CURRENT_PORTABLE",
            "NALU_SERIES_SCOPE_ID": "PORTABLE-DEMO",
            "NALU_ENGINE_ROOT": str(ROOT),
            "NALU_VENV_PYTHON": sys.executable,
        })
        code = r'''
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
import nalu_pipeline as p

class Paths:
    def layers(self):
        return {
            "narrative_canonical": pathlib.Path(sys.argv[2]) / "missing-narrative.md",
            "directing_script": pathlib.Path(sys.argv[2]) / "missing-directing.md",
            "generation_contract": pathlib.Path(sys.argv[2]) / "missing-contract.json",
            "writer_manifest": pathlib.Path(sys.argv[2]) / "missing-manifest.json",
        }
class Context:
    p = Paths()

result = p.stage_s1(Context())
print(json.dumps({"status": result.status, "blockers": result.blockers}))
'''
        with tempfile.TemporaryDirectory() as tmp:
            env["NALU_RUNTIME_ROOT"] = tmp
            completed = subprocess.run(
                [sys.executable, "-c", code,
                 str(ROOT / "lines/nalu/runtime/tools"), tmp],
                cwd=ROOT, env=env, check=False, capture_output=True, text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "BLOCKED")
        self.assertEqual(len(payload["blockers"]), 4)
        self.assertTrue(all(value.startswith("SCRIPT_LAYER_MISSING:")
                            for value in payload["blockers"]))

    def test_current_s1_fingerprint_tracks_private_source_artifact_bytes(self):
        env = os.environ.copy()
        env.update({
            "NALU_POLICY_PROFILE": "CURRENT_PORTABLE",
            "NALU_SERIES_SCOPE_ID": "PORTABLE-DEMO",
            "NALU_ENGINE_ROOT": str(ROOT),
            "NALU_VENV_PYTHON": sys.executable,
        })
        code = r'''
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
import nalu_pipeline as p

root = pathlib.Path(sys.argv[2])
layers = root / "writer_layers/PORTABLE-DEMO/E01"
layers.mkdir(parents=True)
layer_paths = {}
for name, filename in {
    "narrative_canonical": "E01_NARRATIVE_CANONICAL_v1.md",
    "directing_script": "E01_DIRECTING_SCRIPT_v1.md",
    "generation_contract": "E01_GENERATION_CONTRACT_v1.json",
    "writer_manifest": "E01_manifest_v1.json",
}.items():
    layer_paths[name] = layers / filename
    layer_paths[name].write_text(name, encoding="utf-8")
lexicon = root / "runtime/series/PORTABLE-DEMO/lexicon.json"
lexicon.parent.mkdir(parents=True)
lexicon.write_text("{}", encoding="utf-8")
source = root / "sources/private.txt"
source.parent.mkdir(parents=True)
source.write_text("version one", encoding="utf-8")
source_receipt = root / "runtime/receipts/source_intake/source.json"
source_receipt.parent.mkdir(parents=True)
source_receipt.write_text("{}", encoding="utf-8")
bundle = root / "runtime/writer_inputs/input.json"
bundle.parent.mkdir(parents=True)
bundle.write_text(json.dumps({"source_receipts": [{
    "receipt_path": str(source_receipt),
    "artifacts": [{"path": str(source)}],
}]}), encoding="utf-8")
receipt = root / "runtime/receipts/writer/receipt.json"
receipt.parent.mkdir(parents=True)
receipt.write_text(json.dumps({"writer_rules": {"files": []}}), encoding="utf-8")
seal = root / "runtime/writer_seals/seal.json"
seal.parent.mkdir(parents=True)
seal.write_text("{}", encoding="utf-8")
active = layers / "ACTIVE_WRITER_HANDOFF.json"
active.write_text(json.dumps({
    "input_bundle": {"path": str(bundle)},
    "writer_receipt": {"path": str(receipt)},
    "four_layer_seal": {"path": str(seal)},
    "project_lexicon": {"path": str(lexicon)},
}), encoding="utf-8")

class Paths:
    writer_manifest = layer_paths["writer_manifest"]
    scope = {"lexicon": lexicon}
    def layers(self):
        return layer_paths
class Context:
    p = Paths()

before = p.fp_s1(Context())
source.write_text("version two", encoding="utf-8")
after = p.fp_s1(Context())
print(json.dumps({"before": before, "after": after}))
'''
        with tempfile.TemporaryDirectory() as tmp:
            env["NALU_RUNTIME_ROOT"] = tmp
            completed = subprocess.run(
                [sys.executable, "-c", code,
                 str(ROOT / "lines/nalu/runtime/tools"), tmp],
                cwd=ROOT, env=env, check=False, capture_output=True, text=True,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertNotEqual(payload["before"], payload["after"])

    def test_current_final_qa_never_omits_registered_gates(self):
        env = os.environ.copy()
        env.update({
            "NALU_POLICY_PROFILE": "CURRENT_PORTABLE",
            "NALU_SERIES_SCOPE_ID": "PORTABLE-DEMO",
            "NALU_ENGINE_ROOT": str(ROOT),
            "NALU_RUNTIME_ROOT": str(ROOT / ".test-current-final-qa-runtime"),
            "NALU_VENV_PYTHON": sys.executable,
        })
        code = """
import json, sys
sys.path.insert(0, sys.argv[1])
import final_qa_evidence_bundle as f
applicable, not_applicable, unsatisfiable = f._gate_sets("E01")
print(json.dumps({
    "applicable": list(applicable),
    "not_applicable": sorted(not_applicable),
    "unsatisfiable": list(unsatisfiable),
    "registered": list(f.FINAL_GATES + f.RELEASE_GATES),
}))
"""
        completed = subprocess.run(
            [sys.executable, "-c", code, str(ROOT / "lines/nalu/runtime/tools")],
            cwd=ROOT, env=env, check=False, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["applicable"], payload["registered"])
        self.assertEqual(payload["not_applicable"], [])
        self.assertEqual(payload["unsatisfiable"], [])
        for gate in (
            "BGM-SOURCE-PRIORITY-AUTHENTICITY",
            "AUDIENCE-SCORE-PRE-RELEASE",
            "FINAL-CUT-VIEWING-EVIDENCE",
            "FINAL-CUT-EVENT-LEDGER",
        ):
            self.assertIn(gate, payload["applicable"])

    def test_pipeline_requires_independent_final_audience_review_before_final_qa(self):
        env = os.environ.copy()
        env.update({
            "NALU_POLICY_PROFILE": "CURRENT_PORTABLE",
            "NALU_SERIES_SCOPE_ID": "PORTABLE-DEMO",
            "NALU_ENGINE_ROOT": str(ROOT),
            "NALU_RUNTIME_ROOT": str(ROOT / ".test-current-audience-runtime"),
            "NALU_VENV_PYTHON": sys.executable,
        })
        code = r'''
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
import nalu_pipeline as p

class Paths:
    scope = {"scope_id": "PORTABLE-DEMO"}
class Context:
    episode = "E01"
    p = Paths()

def run_case(steps):
    queue = list(steps)
    p.qa_run = lambda *_args, **_kwargs: queue.pop(0)
    p.qa_json = lambda step: step["payload"]
    result = p.StageResult(p.BLOCKED)
    detail = p.s7_final_audience_review(Context(), result)
    return {"status": detail["status"], "blockers": detail["blockers"],
            "step_count": len(result.steps)}

print(json.dumps({
    "prepare": run_case([
        {"exit_code": 4, "payload": {"status": "PREPARE_REQUIRED"}},
        {"exit_code": 0, "payload": {"status": "REVIEW_REQUIRED", "request": "/tmp/request.json"}},
    ]),
    "pass": run_case([
        {"exit_code": 0, "payload": {"status": "PASS"}},
    ]),
    "reject": run_case([
        {"exit_code": 3, "payload": {"status": "BLOCKED_BY_FINAL_AUDIENCE_GATE"}},
    ]),
}))
'''
        completed = subprocess.run(
            [sys.executable, "-c", code, str(ROOT / "lines/nalu/runtime/tools")],
            cwd=ROOT, env=env, check=False, capture_output=True, text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["prepare"]["status"], "REVIEW_REQUIRED")
        self.assertEqual(payload["prepare"]["step_count"], 2)
        self.assertEqual(payload["pass"]["status"], "PASS")
        self.assertEqual(payload["reject"]["status"], "BLOCKED")
        self.assertEqual(
            payload["reject"]["blockers"], ["FINAL_AUDIENCE_REVIEW_REJECTED"]
        )


if __name__ == "__main__":
    unittest.main()
