"""The Q1 and SFE evidence records carry the provider-request binding.

Line owner 2026-11-01, item 1.  A gate PASS used to be bound to the review-request
sha and the asset sha — and to nothing about the provider request that produced
the asset.  So "the admitted still" and "the still a paid task actually generated"
could drift apart with every record still looking complete.

These tests drive the two record builders on a temp runtime root and assert:

  * every gate evidence file and the index carry ``provider_request_binding``;
  * at review time the task id and the payload sha are ``null`` WITH a reason —
    neither invented nor back-filled from another task;
  * the prompt sha, model and reference list come from the authoring manifest;
  * a reference the manifest names but disk lacks is recorded MISSING;
  * the roll-up says UNENFORCED when the policy does not cover the episode.

No paid stage, no provider call: the gate subprocess is replaced.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
for _path in (str(TOOLS), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _boot(runtime_root: Path, work_root: Path | None = None):
    env = {"NALU_ENGINE_ROOT": str(ROOT), "NALU_RUNTIME_ROOT": str(runtime_root)}
    if work_root is not None:
        env["NALU_WORK_ROOT"] = str(work_root)
    with mock.patch.dict(os.environ, env):
        for name in ("nalu_paths", "nalu_qa_common", "nalu_series_scope",
                     "provider_request_digest", "keyframe_q1_builder"):
            sys.modules.pop(name, None)
        return {
            "q1": importlib.import_module("keyframe_q1_builder"),
            "digest": importlib.import_module("provider_request_digest"),
        }


def _manifest(tmp: Path) -> Path:
    manifest = {
        "tasks": [{
            "task_key": "E99-S01-01-KEYFRAME-V1",
            "shot_id": "E99-S01-01",
            "video_unit_id": "E99-VU-001",
            "episode": "E99",
            "model": "gpt-image-2-pro",
            "prompt_file": str(tmp / "prompt.txt"),
            "prompt_sha256": _sha(b"keyframe prompt"),
            "reviewed_request_sha256": "r" * 64,
            "reference_image_sequence": [
                {"role": "character", "entity_id": "CHAR-A", "view": "FRONT_NEUTRAL_HEADSHOT",
                 "path": str(tmp / "plate.png"), "sha256": _sha(b"plate")},
                {"role": "ADMITTED_NEW_EVENT_ENTRY_STATE", "path": str(tmp / "asset.png")},
                {"role": "subspace_layout", "entity_id": "SUBSPACE-1",
                 "path": str(tmp / "gone-layout.png"), "sha256": "0" * 64},
            ],
        }],
    }
    # where QaPaths looks: <work root>/<EP>/preproduction/<EP>_KEYFRAME_IMAGE_MANIFEST_V1.json
    path = tmp / "work" / "E99" / "preproduction" / "E99_KEYFRAME_IMAGE_MANIFEST_V1.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


class Q1EvidenceBindingTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        (self.tmp / "plate.png").write_bytes(b"plate")
        (self.tmp / "prompt.txt").write_text("keyframe prompt", encoding="utf-8")
        self.manifest = _manifest(self.tmp)
        self.mods = _boot(self.tmp, work_root=self.tmp / "work")
        self.q1 = self.mods["q1"]

    def _paths(self, manifest: Path):
        import types
        return types.SimpleNamespace(keyframe_manifest=manifest)

    def test_the_block_records_role_version_and_sha_of_every_reference(self):
        manifest = _manifest(self.tmp)
        binding = self.q1.provider_request_binding(
            "E99", {"request_path": str(self.tmp / "req.json"), "request_sha256": "s" * 64},
            submitted_path=self.tmp / "submitted.json", shot_id="E99-S01-01")
        self.assertEqual(self.q1.manifest_task_for(
            "E99", shot_id="E99-S01-01")["task_key"], "E99-S01-01-KEYFRAME-V1")
        self.assertEqual(binding["stage"], "REVIEWED_BEFORE_SUBMISSION")
        self.assertIsNone(binding["task_id"])
        self.assertEqual(binding["nulls"]["task_id"], "NOT_YET_ASSIGNED_BY_PROVIDER")
        self.assertIsNone(binding["payload_sha256"])
        self.assertEqual(binding["provider_request"]["prompt_sha256"], _sha(b"keyframe prompt"))
        self.assertEqual(binding["provider_request"]["model"], "gpt-image-2-pro")
        self.assertEqual(binding["provider_request"]["request_sha256"], "r" * 64)
        self.assertEqual(binding["review"]["request_sha256"], "s" * 64)
        roles = [row["role"] for row in binding["references"]]
        self.assertEqual(roles, ["IDENTITY", "SPACE"])   # the generated target is not a reference
        self.assertEqual(binding["references"][0]["version"], "FRONT_NEUTRAL_HEADSHOT")
        self.assertEqual(binding["identity_reference_status"], "PRESENT")

    def test_a_missing_reference_is_recorded_with_its_reason(self):
        binding = self.q1.provider_request_binding(
            "E99", {}, submitted_path=self.tmp / "submitted.json", shot_id="E99-S01-01")
        missing = [row for row in binding["references"] if row["status"] != "PRESENT"]
        self.assertEqual([row["role"] for row in missing], ["SPACE"])
        self.assertIn(f"references[{missing[0]['index']}].source_sha256", binding["nulls"])

    def test_a_review_item_the_manifest_does_not_name_gets_no_invented_row(self):
        binding = self.q1.provider_request_binding(
            "E99", {}, submitted_path=self.tmp / "submitted.json", shot_id="E99-S99-99")
        self.assertEqual(binding["stage"], "NO_PROVIDER_REQUEST_DECLARED")
        self.assertIn("provider_request", binding["nulls"])
        self.assertIsNone(binding["provider_request"]["prompt_sha256"])
        self.assertIsNone(binding["provider_request"]["request_sha256"])

    def test_the_roll_up_says_unenforced_when_the_policy_does_not_cover_the_episode(self):
        binding = self.q1.provider_request_binding(
            "E99", {}, submitted_path=self.tmp / "submitted.json", shot_id="E99-S01-01")
        summary = self.q1.binding_summary("E99", [{"provider_request_binding": binding}])
        self.assertEqual(summary["status"], "UNENFORCED")
        self.assertIn("UNENFORCED", summary["note"])
        self.assertEqual(summary["rows_with_task_id"], 0)
        self.assertEqual(summary["rows_with_reviewed_request_sha"], 1)
        self.assertEqual(summary["identity_reference_missing"], 0)

    def test_the_roll_up_says_enforced_for_an_episode_the_policy_covers(self):
        policy = self.tmp / "policy.json"
        policy.write_text(json.dumps({"enabled_episodes": ["E99"]}), encoding="utf-8")
        with mock.patch.object(self.mods["digest"], "POLICY", policy):
            binding = self.q1.provider_request_binding(
                "E99", {}, submitted_path=self.tmp / "submitted.json", shot_id="E99-S01-01")
            summary = self.q1.binding_summary("E99", [{"provider_request_binding": binding}])
        self.assertEqual(summary["status"], "ENFORCED")
        self.assertTrue(binding["policy"]["binding_required"])

    def test_the_block_joins_the_reference_media_the_reviewer_saw(self):
        binding = self.q1.provider_request_binding(
            "E99", {}, submitted_path=self.tmp / "submitted.json", shot_id="E99-S01-01")
        binding["review_reference_media"] = {
            "status": "MISSING",
            "missing": [{"index": 1, "role": "IDENTITY", "entity_id": "CHAR-A"}],
            "source_shas": [{"index": 1, "role": "IDENTITY", "source_sha256": "a" * 64,
                             "version": "FRONT_NEUTRAL_HEADSHOT"}],
        }
        summary = self.q1.binding_summary("E99", [{"provider_request_binding": binding}])
        self.assertEqual(summary["review_identity_reference_missing"], 1)
        # the manifest DID declare an identity reference; the review was the gap
        self.assertEqual(summary["identity_reference_missing"], 0)


class Q1MaterialiseCarriesBindingTest(unittest.TestCase):
    """The materialiser writes the block into every evidence file, not only the index."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.asset = self.tmp / "keyframe.png"
        self.asset.write_bytes(b"keyframe-bytes")
        (self.tmp / "plate.png").write_bytes(b"plate")
        (self.tmp / "prompt.txt").write_text("keyframe prompt", encoding="utf-8")
        self.mods = _boot(self.tmp, work_root=self.tmp / "work")
        self.q1 = self.mods["q1"]
        self.manifest = _manifest(self.tmp)
        self.request_path = self.tmp / "review_request.json"
        self.request_path.write_text("{}", encoding="utf-8")

    def test_every_evidence_file_and_the_index_carry_the_binding(self):
        import types

        submitted = {
            "questionnaire": {}, "request_path": str(self.request_path),
            "request_sha256": _sha(b"{}"), "reviewed_at": "2026-11-01T00:00:00Z",
            "items": [{
                "item_id": "E99-S01-01", "verdict": "PASS",
                "answers": {}, "observed": {}, "observation": "x" * 30, "defects": [],
                "request_item": {
                    "unit_id": "E99-VU-001", "shot_id": "E99-S01-01",
                    "expectations": {"required_visible_character_ids": []},
                    "media": [{"role": "KEYFRAME", "path": str(self.asset),
                               "sha256": _sha(b"keyframe-bytes")}],
                    "reference_media": {"status": "PARTIAL", "references": [
                        {"index": 1, "role": "IDENTITY", "status": "PRESENT",
                         "source_sha256": "a" * 64, "version": "FRONT_NEUTRAL_HEADSHOT"}],
                        "missing": [{"index": 2, "role": "SPACE",
                                     "entity_id": "SUBSPACE-1"}]},
                },
            }],
        }
        written: list[Path] = []

        def _fake_read_json(path, default=None):
            # the manifest is read through this same helper; only the gate result
            # needs stubbing (its subprocess is replaced below)
            if Path(str(path)).name.endswith("KEYFRAME_IMAGE_MANIFEST_V1.json"):
                return json.loads(Path(path).read_text(encoding="utf-8"))
            return {"status": "ADMITTED",
                    "downstream_status": "ADMITTED_FOR_VIDEO_SUBMIT",
                    "passing_registered_gates": []}

        def fake_write(path, payload):
            written.append(Path(path))
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(json.dumps(payload), encoding="utf-8")
            return Path(path)

        with mock.patch.object(self.q1, "QaPaths", lambda episode: types.SimpleNamespace(
                keyframe_manifest=self.manifest,
                qa_root=self.tmp / "qa", q1_dir=self.tmp / "qa/q1",
                preprod_reports=self.tmp / "reports", keyframe_admission=self.tmp / "admission.json")), \
                mock.patch.object(self.q1, "Expectations", lambda episode: types.SimpleNamespace(
                    forbidden_terms=lambda: ["现代"])), \
                mock.patch.object(self.q1, "write_json", fake_write), \
                mock.patch.object(self.q1, "ocr_keyframes", lambda *a, **k: {
                    "E99-S01-01": {"exit_code": 0, "report": {"status": "PASS"},
                                   "report_path": str(self.tmp / "ocr.json")}}), \
                mock.patch.object(self.q1, "measure_still_identity", lambda *a, **k: {
                    "method": "INSIGHTFACE_COSINE_V1", "status": "PASS"}), \
                mock.patch.object(self.q1, "build_period_verification",
                                  lambda *a, **k: ({"decision": "PASS"}, [])), \
                mock.patch.object(self.q1, "build_identity_verification",
                                  lambda *a, **k: ({"decision": "PASS", "method": "M"},
                                                   [], "INSIGHTFACE_COSINE_V1")), \
                mock.patch.object(self.q1, "face_measurable_ids", lambda *a, **k: []), \
                mock.patch.object(self.q1, "still_gate_registry", lambda: self.tmp / "reg.json"), \
                mock.patch.object(self.q1, "subprocess") as proc, \
                mock.patch.object(self.q1, "read_json", _fake_read_json), \
                mock.patch.object(self.q1, "sha256_file", lambda path: _sha(
                    Path(path).read_bytes()) if Path(path).is_file() else None), \
                mock.patch.object(self.q1, "portable", lambda path, root=None: str(path)), \
                mock.patch.object(self.q1, "now", lambda: "2026-11-01T00:00:00Z"):
            proc.run.return_value = types.SimpleNamespace(returncode=0, stdout="", stderr="")
            record = self.q1.materialise("E99", submitted, self.request_path)

        evidence_files = [path for path in written if path.name.endswith("_evidence.json")]
        self.assertTrue(evidence_files, "the materialiser wrote no evidence file")
        for path in evidence_files:
            payload = json.loads(path.read_text(encoding="utf-8"))
            binding = payload.get("provider_request_binding")
            self.assertIsInstance(binding, dict, path.name)
            self.assertIsNone(binding["task_id"])
            self.assertEqual(binding["nulls"]["task_id"], "NOT_YET_ASSIGNED_BY_PROVIDER")
            self.assertEqual(binding["provider_request"]["prompt_sha256"], _sha(b"keyframe prompt"))
        summary = record["provider_request_binding_summary"]
        self.assertEqual(summary["status"], "UNENFORCED")
        self.assertEqual(summary["reference_occurrences_missing"], 1)
        self.assertEqual(record["results"][0]["provider_request_binding"]["stage"],
                         "REVIEWED_BEFORE_SUBMISSION")


if __name__ == "__main__":
    unittest.main()
