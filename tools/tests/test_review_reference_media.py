"""A review request must show the references the task was actually given.

Line owner 2026-11-01, item 4.  Before this, a keyframe / video_q2 request listed
only the GENERATED asset.  A reviewer therefore answered "each visible character
is recognisably the locked identity plate person" without ever being shown that
plate — it could not be, and nothing said so.

Now the request carries ``reference_media``: one row per IDENTITY / WARDROBE /
SPACE / PROP reference the task's own authoring manifest declares, labelled with
its role, its version (the view/kind), the source sha256 and the transport sha256
(unknown at review time, present and null).  A reference the manifest names but
disk does not have is listed MISSING, never omitted.  The answer rule that
forbids claiming identity agreement from the generated frame alone is stated in
the request and enforced by ``reference_claim_failures``.

Everything here runs on a temp runtime root: no repo state, no paid stage.
"""
from __future__ import annotations

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


def _boot(runtime_root: Path):
    """Import the nalu tools against a throwaway runtime root."""
    env = {"NALU_ENGINE_ROOT": str(ROOT), "NALU_RUNTIME_ROOT": str(runtime_root)}
    with mock.patch.dict(os.environ, env):
        for name in ("nalu_paths", "nalu_qa_common", "nalu_series_scope", "vlm_review_protocol",
                     "visual_review_policy", "provider_request_digest"):
            sys.modules.pop(name, None)
        return {
            "vrp": importlib.import_module("vlm_review_protocol"),
            "common": importlib.import_module("nalu_qa_common"),
        }


class RoleAndManifestTest(unittest.TestCase):
    """The role vocabulary and the manifest index, without any review machinery."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mods = _boot(Path(self._tmp.name))
        self.common = self.mods["common"]

    def test_every_authored_role_folds_onto_a_review_role(self):
        cases = {
            "character": "IDENTITY", "CHARACTER_IDENTITY_REFERENCE": "IDENTITY",
            "operator_source_reference": "IDENTITY", "character_wardrobe": "WARDROBE",
            "WARDROBE_STATE_ON_IDENTITY_PLATE": "WARDROBE", "subspace_layout": "SPACE",
            "episode_global_space_map": "SPACE", "scene": "SPACE", "prop": "PROP",
            "PROP_REFERENCE": "PROP", "ADMITTED_NEW_EVENT_ENTRY_STATE": "GENERATED_TARGET",
            "contact_sheet_2fps": "GENERATED_TARGET", "": "OTHER", None: "OTHER",
        }
        for raw, expected in cases.items():
            self.assertEqual(self.common.review_role(raw), expected, raw)

    def test_manifest_index_answers_every_id_a_review_item_carries(self):
        manifest = {"tasks": [{
            "task_key": "E99-S01-01-KEYFRAME-V1", "shot_id": "E99-S01-01",
            "video_unit_id": "E99-VU-001",
            "reference_image_sequence": [{"role": "character", "path": "/p.png", "sha256": "a" * 64}],
        }]}
        index = self.common.manifest_reference_index(manifest)
        for key in ("E99-S01-01-KEYFRAME-V1", "E99-S01-01", "E99-VU-001"):
            self.assertEqual(len(self.common.manifest_references_for(index, key)), 1, key)
        self.assertIsNone(self.common.manifest_references_for(index, "E99-S99-99"))

    def test_grouped_units_are_indexed_by_unit_id(self):
        manifest = {"units": [{"unit_id": "E99-VU-007",
                               "reference_images": [{"role": "CHARACTER_IDENTITY_REFERENCE",
                                                     "path": "/p.png", "sha256": "b" * 64}]}]}
        index = self.common.manifest_reference_index(manifest)
        rows = self.common.manifest_references_for(index, "E99-VU-007")
        self.assertEqual(rows[0]["role"], "CHARACTER_IDENTITY_REFERENCE")

    def test_older_manifest_form_uses_the_parallel_role_array(self):
        manifest = {"tasks": [{"task_key": "T", "reference_images": ["/a.png", "/b.png"],
                               "reference_roles": ["character", "prop"]}]}
        rows = self.common.manifest_references_for(
            self.common.manifest_reference_index(manifest), "T")
        self.assertEqual([row["role"] for row in rows], ["character", "prop"])


class ReferenceSectionTest(unittest.TestCase):
    """What the reviewer is shown: role, version, source sha, transport sha, MISSING."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.vrp = _boot(self.tmp)["vrp"]
        self.plate = self.tmp / "plate.png"
        self.plate.write_bytes(b"plate-bytes")
        self.layout = self.tmp / "layout.png"
        self.layout.write_bytes(b"layout-bytes")

    def rows(self):
        import hashlib
        plate_sha = hashlib.sha256(b"plate-bytes").hexdigest()
        layout_sha = hashlib.sha256(b"layout-bytes").hexdigest()
        return self.vrp.review_reference_rows([
            {"role": "character", "entity_id": "CHAR-A", "view": "FRONT_NEUTRAL_HEADSHOT",
             "path": str(self.plate), "sha256": plate_sha},
            {"role": "subspace_layout", "entity_id": "SUBSPACE-1", "kind": "SHOT_SUBSPACE_LAYOUT",
             "path": str(self.layout), "sha256": layout_sha},
            {"role": "prop", "entity_id": "PROP-1", "path": str(self.tmp / "gone.png"),
             "sha256": "c" * 64},
            # the generated asset is the TARGET, never a reference
            {"role": "ADMITTED_NEW_EVENT_ENTRY_STATE", "path": str(self.plate)},
        ])

    def test_generated_target_is_not_listed_as_a_reference(self):
        roles = [row["role"] for row in self.rows()]
        self.assertEqual(roles, ["IDENTITY", "SPACE", "PROP"])

    def test_every_reference_carries_role_version_and_both_sha_keys(self):
        for row in self.rows():
            self.assertIn("version", row)
            self.assertTrue(row["version"])
            self.assertIn("source_sha256", row)
            self.assertIn("transport_sha256", row)
        first = self.rows()[0]
        self.assertEqual(first["version"], "FRONT_NEUTRAL_HEADSHOT")
        self.assertTrue(first["source_sha256"])
        self.assertIsNone(first["transport_sha256"])
        self.assertIn("NOT_ENCODED_YET", first["transport_sha256_note"])

    def test_a_missing_reference_is_reported_not_omitted(self):
        rows = self.rows()
        missing = [row for row in rows if row["status"] != "PRESENT"]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["role"], "PROP")
        self.assertIn("REFERENCE_FILE_NOT_ON_DISK", missing[0]["missing_reason"])
        self.assertEqual(self.vrp.reference_status(rows), "PARTIAL")

    def test_status_reflects_coverage(self):
        self.assertEqual(self.vrp.reference_status([]), "NOT_DECLARED")
        all_missing = [{"role": "PROP", "status": "MISSING"}]
        self.assertEqual(self.vrp.reference_status(all_missing), "MISSING")
        present = [{"role": "PROP", "status": "PRESENT"}]
        self.assertEqual(self.vrp.reference_status(present), "PRESENT")

    def test_identity_rule_forbids_claiming_agreement_without_the_reference(self):
        rules = {
            "NOT_DECLARED": self.vrp.identity_claim_rule([]),
            "MISSING": self.vrp.identity_claim_rule([{"role": "IDENTITY", "status": "MISSING",
                                                     "index": 1, "entity_id": "CHAR-A"}]),
            "PRESENT": self.vrp.identity_claim_rule([{"role": "IDENTITY", "status": "PRESENT",
                                                     "index": 1, "entity_id": "CHAR-A"}]),
        }
        self.assertIn("must NOT claim", rules["NOT_DECLARED"])
        self.assertIn("MISSING", rules["MISSING"])
        self.assertIn("UNCERTAIN", rules["MISSING"])
        self.assertIn("MISSING_REVIEW_REFERENCE", rules["MISSING"])
        self.assertIn("do not claim agreement", rules["PRESENT"])


class ReferenceClaimEnforcementTest(unittest.TestCase):
    """A PASS on a question whose reference is MISSING is refused, not banked."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.mods = _boot(Path(self._tmp.name))
        self.vrp = self.mods["vrp"]

    @staticmethod
    def item(identity_status: str) -> dict:
        return {"item_id": "E99-S01-01", "reference_media": {
            "per_item": True, "status": "PARTIAL",
            "references": [{"index": 1, "role": "IDENTITY", "status": identity_status,
                            "entity_id": "CHAR-A"}],
        }}

    def test_claiming_identity_from_a_missing_reference_is_a_failure(self):
        failures = self.vrp.reference_claim_failures(
            "keyframe", self.item("MISSING"),
            {"each_visible_character_identity_recognisable": "PASS"})
        self.assertTrue(any("reference_claim_without_reference" in row for row in failures), failures)

    def test_the_same_answer_is_fine_when_the_reference_was_shown(self):
        failures = self.vrp.reference_claim_failures(
            "keyframe", self.item("PRESENT"),
            {"each_visible_character_identity_recognisable": "PASS"})
        self.assertEqual(failures, [])

    def test_an_uncertain_answer_is_always_accepted(self):
        for status in ("MISSING", "PRESENT"):
            self.assertEqual(self.vrp.reference_claim_failures(
                "keyframe", self.item(status),
                {"each_visible_character_identity_recognisable": "UNCERTAIN"}), [])

    def test_a_request_without_the_block_is_judged_exactly_as_before(self):
        self.assertEqual(self.vrp.reference_claim_failures(
            "keyframe", {"item_id": "X"}, {"each_visible_character_identity_recognisable": "PASS"}), [])

    def test_the_switch_ships_on_but_can_be_turned_off_by_config(self):
        self.assertTrue(self.vrp.review_media_policy()["identity_claim_requires_reference"])
        with mock.patch.object(self.vrp, "review_media_policy",
                               lambda: {"identity_claim_requires_reference": False,
                                        "missing_reference_must_be_declared": True}):
            self.assertEqual(self.vrp.reference_claim_failures(
                "keyframe", self.item("MISSING"),
                {"each_visible_character_identity_recognisable": "PASS"}), [])

    def test_the_strict_default_applies_when_the_digest_module_is_missing(self):
        with mock.patch.object(self.vrp, "engine_module", side_effect=ImportError("gone")):
            policy = self.vrp.review_media_policy()
        self.assertTrue(policy["identity_claim_requires_reference"])


class BuildRequestCarriesReferencesTest(unittest.TestCase):
    """End to end through build_request, with the manifests supplied by a fixture."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.vrp = _boot(self.tmp)["vrp"]
        self.plate = self.tmp / "plate.png"
        self.plate.write_bytes(b"plate")
        self.keyframe = self.tmp / "keyframe.png"
        self.keyframe.write_bytes(b"keyframe")

    def _paths(self, **extra):
        import types
        base = dict(keyframe_manifest=self.tmp / "missing_manifest.json",
                    grouped_seedance=self.tmp / "missing_grouped.json")
        base.update(extra)
        return types.SimpleNamespace(**base)

    def _expectations(self):
        import types
        inst = types.SimpleNamespace()

        def keyframe_items():
            return [{"item_id": "E99-S01-01", "unit_id": "E99-VU-001",
                     "shot_id": "E99-S01-01", "media_path": str(self.keyframe),
                     "expectations": {"required_visible_characters": ["A"]}}]
        inst.keyframe_items = keyframe_items
        inst.shots = {}
        inst.library = {}
        inst.character_ids = lambda: []
        inst.character_name_to_id = lambda: {}
        inst.forbidden_terms = lambda: []
        inst.identity_subjects = lambda: []
        return inst

    def _build(self, manifest: dict | None):
        manifest_path = self.tmp / "manifest.json"
        manifest_path.write_text(json.dumps(manifest or {}), encoding="utf-8")
        with mock.patch.object(self.vrp, "Expectations", lambda episode: self._expectations()), \
                mock.patch.object(self.vrp, "QaPaths",
                                  lambda episode: self._paths(keyframe_manifest=manifest_path)):
            return self.vrp.build_request("keyframe", "E99", out=self.tmp / "request.json")

    def test_declared_references_reach_the_request_with_their_roles(self):
        import hashlib
        manifest = {"tasks": [{
            "task_key": "E99-S01-01-KEYFRAME-V1", "shot_id": "E99-S01-01",
            "video_unit_id": "E99-VU-001",
            "reference_image_sequence": [
                {"role": "character", "entity_id": "CHAR-A", "view": "FRONT_NEUTRAL_HEADSHOT",
                 "path": str(self.plate), "sha256": hashlib.sha256(b"plate").hexdigest()},
                {"role": "ADMITTED_NEW_EVENT_ENTRY_STATE", "path": str(self.keyframe)},
            ]}]}
        request = self._build(manifest)
        item = request["items"][0]
        self.assertEqual(item["reference_media"]["status"], "PRESENT")
        roles = [row["role"] for row in item["reference_media"]["references"]]
        self.assertEqual(roles, ["IDENTITY"])
        self.assertEqual(request["reference_media"]["status"], "PRESENT")
        self.assertIn("do not claim agreement", request["answer_rules"]["identity_claim_requires_reference"])
        self.assertEqual(request["answer_rules"]["identity_claim_reference_status"], "PRESENT")

    def test_a_missing_manifest_says_not_declared_rather_than_inventing_a_set(self):
        request = self._build(None)
        item = request["items"][0]
        self.assertEqual(item["reference_media"]["status"], "NOT_DECLARED")
        self.assertIn("No identity / wardrobe / space / prop reference",
                      request["answer_rules"]["identity_claim_requires_reference"])

    def test_a_manifest_row_whose_reference_is_gone_is_missing(self):
        manifest = {"tasks": [{
            "task_key": "E99-S01-01-KEYFRAME-V1", "shot_id": "E99-S01-01",
            "reference_image_sequence": [{"role": "character", "entity_id": "CHAR-A",
                                          "path": str(self.tmp / "gone.png"),
                                          "sha256": "a" * 64}]}]}
        request = self._build(manifest)
        self.assertEqual(request["reference_media"]["missing_count"], 1)
        self.assertEqual(request["reference_media"]["status"], "MISSING")
        self.assertIn("MISSING_REVIEW_REFERENCE",
                      request["answer_rules"]["identity_claim_requires_reference"])

    def test_the_reference_block_is_absent_for_an_unrelated_kind(self):
        """``post_gen_plot`` is not reference-aware; its request must not grow a block."""
        import types

        exp = types.SimpleNamespace()
        exp.unit_plot_items = lambda: [{"item_id": "U1", "unit_id": "U1",
                                        "expectations": {"editorial_shot_ids": []},
                                        "media_path": str(self.keyframe)}]
        exp.shots, exp.library = {}, {}
        exp.character_ids = lambda: []
        exp.character_name_to_id = lambda: {}
        exp.forbidden_terms = lambda: []
        exp.identity_subjects = lambda: []
        with mock.patch.object(self.vrp, "Expectations", lambda episode: exp), \
                mock.patch.object(self.vrp, "QaPaths", lambda episode: self._paths()):
            request = self.vrp.build_request(
                "post_gen_plot", "E99", out=self.tmp / "plot.json",
                media_override={"U1": [{"role": "UNIT_VIDEO", "path": str(self.keyframe),
                                        "exists": True, "sha256": None, "media_type": "IMAGE"}]})
        self.assertNotIn("reference_media", request)


if __name__ == "__main__":
    unittest.main()
