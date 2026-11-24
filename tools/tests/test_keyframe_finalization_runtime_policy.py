"""Keyframe prompt finalization with a runtime-registered prompt-batch policy (device 1101 E27 S6, 2026-11-24).

The episode's execution is registered only in <runtime>/workflow/production_line/EPISODE_PROMPT_BATCH_POLICY.json
(registration_write_path).  attach_keyframe_prompt_batch_finalization.py read only the engine copy and refused
it ("prompt batch execution is not registered and required"), so the S6 own keyframes could never be bound and
the submit failed FINAL_PROMPT_NOT_BOUND_TO_BATCH.  It must resolve the policy exactly as the gate does (env or
the deployment pin), and its receipt must survive the S5 manifest rebuild (stamp re-attaches it).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools import attach_keyframe_prompt_batch_finalization as attach  # noqa: E402
from tools.episode_prompt_batch_gate import (POLICY_RELPATH, require_generation_batch,  # noqa: E402
                                             resolve_policy_path, runtime_root)

_spec = importlib.util.spec_from_file_location(
    "stamp_tool_kf_fin", ROOT / "lines/nalu/runtime/tools/stamp_reviewed_keyframe_requests.py")
stamp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stamp)

EXE = "E27-PROMPT-BATCH-V1"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DeviceLayout:
    """engine/ (no E27 registration, an unrelated historical one) + runtime/ (E27 registered)."""

    def __init__(self, base: Path):
        self.engine = base / "engine"
        self.runtime = base / "runtime"
        self.pre = self.engine / "workflow/nalu/E27/preproduction"
        prompts = self.pre / "prompts/keyframes"
        prompts.mkdir(parents=True)
        # VU-010 opens on its own reviewed keyframe; VU-011 was tail-derived (batch row = VU-010's keyframe
        # prompt) and S6 switched it to an own keyframe whose prompt was written after registration.
        self.kf10 = prompts / "E27-S02-01-KEYFRAME-V1.txt"
        self.kf10.write_text("reviewed keyframe of VU-010", encoding="utf-8")
        self.kf11 = prompts / "E27-S02-02-KEYFRAME-V1.txt"
        self.kf11.write_text("own keyframe of VU-011: new entry state\nreordered identity refs", encoding="utf-8")
        rows, qa_dir = [], self.pre / "prompt_qa"
        qa_dir.mkdir()
        for uid, kf in (("E27-VU-010", self.kf10), ("E27-VU-011", self.kf10)):
            vp = self.pre / f"{uid}.video.txt"
            vp.write_text(f"planned video prompt {uid}", encoding="utf-8")
            row = {"unit_id": uid,
                   "keyframe_prompt": {"path": str(kf.relative_to(self.engine)), "sha256": _sha(kf),
                                       "shot_id": "E27-S02-01"},
                   "video_prompt": {"path": str(vp.relative_to(self.engine)), "sha256": _sha(vp)}}
            qa = {"execution_id": EXE, "unit_id": uid, "status": "PASS",
                  "scope": "PLANNED_PROMPTS_AND_CROSS_UNIT_CONTINUITY", "cross_unit_continuity_checked": True,
                  "keyframe_prompt_sha256": row["keyframe_prompt"]["sha256"],
                  "video_prompt_sha256": row["video_prompt"]["sha256"]}
            qp = qa_dir / f"{uid}.json"
            qp.write_text(json.dumps(qa), encoding="utf-8")
            row["prompt_qa"] = {"path": str(qp.relative_to(self.engine)), "sha256": _sha(qp)}
            rows.append(row)
        self.batch = self.pre / "E27_PROMPT_BATCH_V1.json"
        self.batch.write_text(json.dumps({"execution_id": EXE, "episode": "E27", "rows": rows}), encoding="utf-8")
        self.register = self.pre / "reports/E27_PROMPT_BATCH_REGISTER.json"
        self.register.parent.mkdir(parents=True)
        self.register.write_text(json.dumps({"status": "PASS", "execution_id": EXE}), encoding="utf-8")
        config = {"required": True, "manifest_ref": str(self.batch.relative_to(self.engine)),
                  "unit_ids": ["E27-VU-010", "E27-VU-011"],
                  "unit_aliases": {"E27-S02-01": "E27-VU-010", "E27-S02-02": "E27-VU-011"}}
        engine_policy = self.engine / POLICY_RELPATH
        engine_policy.parent.mkdir(parents=True)
        engine_policy.write_text(json.dumps({"executions": {"E05-PROMPT-BATCH-V1": {"required": True}},
                                             "task_key_execution_prefixes": {}}), encoding="utf-8")
        runtime_policy = self.runtime / POLICY_RELPATH
        runtime_policy.parent.mkdir(parents=True)
        runtime_policy.write_text(json.dumps({"executions": {EXE: config},
                                              "task_key_execution_prefixes": {"E27-": EXE}}), encoding="utf-8")
        self.manifest = self.pre / "E27_KEYFRAME_IMAGE_MANIFEST_V1.json"
        self.receipts = self.pre / "keyframe_prompt_batch_finalization"
        self.write_manifest()

    def tasks(self):
        return [{"task_key": f"{p.stem}", "shot_id": p.stem.replace("-KEYFRAME-V1", ""), "episode": "E27",
                 "prompt_file": str(p.relative_to(self.engine)), "prompt_sha256": _sha(p), "model": "m",
                 "reference_images": [], "reference_bindings": []} for p in (self.kf10, self.kf11)]

    def write_manifest(self):
        """build_keyframe_manifest: a fresh manifest, no receipts attached."""
        self.manifest.write_text(json.dumps({"episode": "E27", "tasks": self.tasks()}), encoding="utf-8")

    def read_tasks(self):
        return {t["task_key"]: t for t in json.loads(self.manifest.read_text(encoding="utf-8"))["tasks"]}

    def attach_argv(self, *extra):
        return ["--engine-root", str(self.engine), "--manifest", str(self.manifest), "--execution-id", EXE, *extra]

    def attach(self):
        return attach.main(self.attach_argv(
            "--reviewer", "claude-code-nalu-vlm", "--review-note", "reviewed",
            "--receipt-dir", str(self.receipts),
            "--report", str(self.pre / "reports/E27_KEYFRAME_PROMPT_FINALIZATION_REPORT.json")))


class KeyframeFinalizationRuntimePolicyTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.d = DeviceLayout(Path(tmp.name))
        env = {k: v for k, v in os.environ.items() if k not in ("NALU_RUNTIME_ROOT", "NALU_IGNORE_DEPLOYMENT_PIN")}
        patcher = patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        original = stamp.ENGINE
        stamp.ENGINE = self.d.engine
        self.addCleanup(setattr, stamp, "ENGINE", original)

    def pin(self):
        (self.d.engine / ".nalu_deployment.json").write_text(
            json.dumps({"runtime_root": str(self.d.runtime)}), encoding="utf-8")

    def test_engine_only_policy_is_still_refused(self):
        # no env, no pin: the engine copy has no E27 registration (the honest refusal stays)
        with self.assertRaisesRegex(SystemExit, "not registered and required"):
            self.d.attach()

    def test_runtime_policy_from_env_is_used(self):
        os.environ["NALU_RUNTIME_ROOT"] = str(self.d.runtime)
        self.assertEqual(self.d.attach(), 0)
        tasks = self.d.read_tasks()
        self.assertIn("prompt_batch_finalization", tasks["E27-S02-02-KEYFRAME-V1"])
        # the batch-approved prompt needs no receipt
        self.assertNotIn("prompt_batch_finalization", tasks["E27-S02-01-KEYFRAME-V1"])
        receipt = json.loads((self.d.receipts / "E27-S02-02-KEYFRAME-V1.json").read_text(encoding="utf-8"))
        self.assertEqual(receipt["unit_id"], "E27-VU-011")
        self.assertEqual(receipt["artifact_kind"], "keyframe_prompt")

    def test_runtime_policy_from_deployment_pin_is_used(self):
        # an agent running the tool by hand has no NALU_RUNTIME_ROOT; the engine's pin names the runtime
        self.pin()
        self.assertEqual(runtime_root(self.d.engine), self.d.runtime)
        self.assertEqual(resolve_policy_path(self.d.engine), self.d.runtime / POLICY_RELPATH)
        self.assertEqual(self.d.attach(), 0)

    def test_diff_out_writes_digest_without_receipts(self):
        self.pin()
        out = self.d.pre / "reports/digest.json"
        self.assertEqual(attach.main(self.d.attach_argv("--diff-out", str(out))), 0)
        digest = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual([r["task_key"] for r in digest["rows"]], ["E27-S02-02-KEYFRAME-V1"])
        self.assertTrue(digest["rows"][0]["changed_lines"])
        self.assertFalse(self.d.receipts.exists())
        self.assertNotIn("prompt_batch_finalization", self.d.read_tasks()["E27-S02-02-KEYFRAME-V1"])

    def _stamp(self):
        return stamp.main(["--episode", "E27", "--manifest", str(self.d.manifest),
                           "--batch-manifest", str(self.d.batch), "--register-report", str(self.d.register)])

    def test_receipt_survives_manifest_rebuild_and_passes_the_gate(self):
        os.environ["NALU_RUNTIME_ROOT"] = str(self.d.runtime)
        own = "E27-S02-02-KEYFRAME-V1"
        # before review: stamp leaves the own keyframe unstamped and the gate refuses it
        self.assertEqual(self._stamp(), 0)
        self.assertNotIn("reviewed_request_sha256", self.d.read_tasks()[own])
        with self.assertRaisesRegex(ValueError, "FINAL_PROMPT_NOT_BOUND_TO_BATCH"):
            require_generation_batch(self.d.read_tasks()[own], self.d.engine, artifact_kind="keyframe_prompt")
        # review + attach, then S5 rebuilds the manifest (receipt field gone) and stamps again
        self.assertEqual(self.d.attach(), 0)
        self.d.write_manifest()
        self.assertNotIn("prompt_batch_finalization", self.d.read_tasks()[own])
        self.assertEqual(self._stamp(), 0)
        tasks = self.d.read_tasks()
        self.assertIn("prompt_batch_finalization", tasks[own])
        self.assertTrue(tasks[own].get("reviewed_request_sha256"))
        self.assertTrue(tasks["E27-S02-01-KEYFRAME-V1"].get("reviewed_request_sha256"))
        for task in tasks.values():
            self.assertEqual(require_generation_batch(task, self.d.engine, artifact_kind="keyframe_prompt")["status"],
                             "PASS")

    def test_receipt_for_other_bytes_is_not_reattached(self):
        os.environ["NALU_RUNTIME_ROOT"] = str(self.d.runtime)
        self.assertEqual(self.d.attach(), 0)
        self.d.kf11.write_text("prompt rewritten again after the review", encoding="utf-8")
        self.d.write_manifest()
        self.assertEqual(self._stamp(), 0)
        task = self.d.read_tasks()["E27-S02-02-KEYFRAME-V1"]
        self.assertNotIn("prompt_batch_finalization", task)
        self.assertNotIn("reviewed_request_sha256", task)


if __name__ == "__main__":
    unittest.main()
