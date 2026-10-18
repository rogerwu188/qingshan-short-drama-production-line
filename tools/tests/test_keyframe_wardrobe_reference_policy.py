"""KEYFRAME_WARDROBE_REFERENCE_POLICY: the K059 wardrobe drop is a declared-work decision.

codex review 2026-10-17: a shared default must not delete creative inputs by episode number.
The drop happens only when (a) the work is declared in the policy with
drop_wardrobe_references=true AND (b) the substitute evidence (authored 服装锁 text for every
character in the shot) is present.  Everything else keeps the reference array and its order
exactly as authored, and says why.
"""
import json
import os
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))
sys.path.insert(0, str(ROOT))
import build_keyframe_manifest as bkm  # noqa: E402

SHIPPED_POLICY = bkm.load_wardrobe_policy()

ROWS = [
    {"role": "episode_global_space_map", "path": "/x/map-episode.png"},
    {"role": "global_space_map", "path": "/x/map-global.png"},
    {"role": "subspace_layout", "path": "/x/map-subspace.png"},
    {"role": "character", "entity_id": "CHAR-A", "path": "/x/face-a.png"},
    {"role": "scene", "path": "/x/scene.png"},
    {"role": "character_wardrobe", "entity_id": "CHAR-A", "path": "/x/wardrobe-a.png"},
]


def _roles(rows):
    return [r["role"] for r in rows]


def _real_drops(dropped):
    """Rows actually removed from `kept`; OVER_CAP_NOT_DROPPED_* entries are reports, not removals."""
    return [r for r in dropped if not str(r.get("dropped_reason", "")).startswith("OVER_CAP_NOT_DROPPED")]


class ShippedPolicy(unittest.TestCase):
    def test_shipped_policy_declares_only_the_nalu_work(self):
        self.assertEqual(SHIPPED_POLICY.get("schema"), bkm.WARDROBE_POLICY_SCHEMA)
        self.assertEqual(list(SHIPPED_POLICY["scopes"]), ["NALU-YEWUJIANG"])
        self.assertIs(SHIPPED_POLICY["scopes"]["NALU-YEWUJIANG"]["drop_wardrobe_references"], True)
        self.assertIs(SHIPPED_POLICY["default"]["drop_wardrobe_references"], False)

    def test_decision_outcomes_are_distinct(self):
        self.assertEqual(bkm.wardrobe_reference_decision("NALU-YEWUJIANG", episode="E12")["drop"], True)
        # Declared work, but the episode predates the scope's activation: references stay as authored.
        for ep in ("E01", "E09", "E10", "E11"):
            before = bkm.wardrobe_reference_decision("NALU-YEWUJIANG", episode=ep)
            self.assertEqual((before["drop"], before["reason"]), (False, "WARDROBE_POLICY_BEFORE_ACTIVATION:E12"), ep)
        noep = bkm.wardrobe_reference_decision("NALU-YEWUJIANG")
        self.assertEqual((noep["drop"], noep["reason"]), (False, "WARDROBE_POLICY_EPISODE_UNRESOLVED"))
        undeclared = bkm.wardrobe_reference_decision("QINGSHAN-E59")
        self.assertEqual((undeclared["drop"], undeclared["reason"]), (False, "WARDROBE_POLICY_SCOPE_UNDECLARED"))
        unresolved = bkm.wardrobe_reference_decision("")
        self.assertEqual((unresolved["drop"], unresolved["reason"]), (False, "WARDROBE_POLICY_SCOPE_UNRESOLVED"))
        unresolved = bkm.wardrobe_reference_decision(None)
        self.assertEqual((unresolved["drop"], unresolved["reason"]), (False, "WARDROBE_POLICY_SCOPE_UNRESOLVED"))
        absent = bkm.wardrobe_reference_decision("NALU-YEWUJIANG", {})
        self.assertEqual((absent["drop"], absent["reason"]), (False, "WARDROBE_POLICY_FILE_ABSENT"))
        opted_out = bkm.wardrobe_reference_decision("W", {"scopes": {"W": {"drop_wardrobe_references": False}}})
        self.assertEqual((opted_out["drop"], opted_out["reason"]), (False, "WARDROBE_POLICY_SCOPE_OPTED_OUT"))
        # A truthy non-boolean is not an opt-in: enum-strict, not "anything that is not false".
        sloppy = bkm.wardrobe_reference_decision("W", {"scopes": {"W": {"drop_wardrobe_references": "yes"}}})
        self.assertEqual((sloppy["drop"], sloppy["reason"]), (False, "WARDROBE_POLICY_SCOPE_OPTED_OUT"))

    def test_invalid_schema_is_rejected_not_defaulted(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "p.json"
            bad.write_text(json.dumps({"schema": "something.else", "scopes": {"W": {"drop_wardrobe_references": True}}}))
            with self.assertRaises(ValueError):
                bkm.load_wardrobe_policy(bad)


class CapBehaviour(unittest.TestCase):
    def test_undeclared_work_keeps_array_and_order_byte_for_byte(self):
        rows = deepcopy(ROWS)
        kept, dropped = bkm.cap_non_character_bindings(
            rows, wardrobe_decision=bkm.wardrobe_reference_decision("QINGSHAN-E59"),
            wardrobe_text_present=True, episode="E12")
        self.assertEqual(kept, ROWS)
        self.assertEqual(dropped, [])

    def test_no_decision_passed_keeps_array(self):
        # Legacy / direct callers that never consulted the policy must not lose references.
        kept, dropped = bkm.cap_non_character_bindings(deepcopy(ROWS), episode="E12")
        self.assertEqual(kept, ROWS)
        self.assertEqual(dropped, [])

    def test_episode_number_is_not_a_decision_input(self):
        for episode in ("E01", "E09", "E10", "E12", "E59", None):
            kept, dropped = bkm.cap_non_character_bindings(deepcopy(ROWS), episode=episode)
            self.assertEqual(_roles(kept), _roles(ROWS), episode)
            self.assertEqual(dropped, [], episode)

    def test_declared_work_with_substitute_evidence_drops_wardrobe_only(self):
        kept, dropped = bkm.cap_non_character_bindings(
            deepcopy(ROWS), wardrobe_decision=bkm.wardrobe_reference_decision("NALU-YEWUJIANG", episode="E12"),
            wardrobe_text_present=True)
        self.assertEqual(_roles(kept), [r for r in _roles(ROWS) if r != "character_wardrobe"])
        self.assertEqual([r["role"] for r in dropped], ["character_wardrobe"])
        self.assertTrue(dropped[0]["dropped_reason"].startswith("WARDROBE_DROPPED_BY_WORK_POLICY:NALU-YEWUJIANG:"))

    def test_declared_work_without_substitute_evidence_keeps_wardrobe_and_says_why(self):
        for present in (False, None):
            kept, dropped = bkm.cap_non_character_bindings(
                deepcopy(ROWS), wardrobe_decision=bkm.wardrobe_reference_decision("NALU-YEWUJIANG", episode="E12"),
                wardrobe_text_present=present)
            self.assertEqual(_roles(kept), _roles(ROWS))
            self.assertEqual(dropped, [])
            note = [r.get("policy_note") for r in kept if r["role"] == "character_wardrobe"]
            self.assertEqual(note, ["WARDROBE_KEPT_SUBSTITUTE_EVIDENCE_ABSENT"])

    def test_counterexample_pass_with_empty_output_is_impossible(self):
        # Every path returns the full non-wardrobe set; a "drop everything" outcome cannot occur.
        kept, _ = bkm.cap_non_character_bindings(
            deepcopy(ROWS), wardrobe_decision={"drop": True, "scope": "W", "reason": "X"},
            wardrobe_text_present=True)
        self.assertEqual(sum(1 for r in kept if r["role"] == "character"), 1)
        self.assertEqual(sum(1 for r in kept if r["role"].endswith("space_map") or r["role"] in ("subspace_layout", "scene")), 4)
        self.assertGreaterEqual(len(kept), 5)


class RealCallSite(unittest.TestCase):
    """build_bindings is the only production caller; it must derive the work id from the asset
    library's project_id and the substitute evidence from the authored wardrobe map."""

    def _inputs(self, project_id, wardrobe_map):
        class I:  # noqa: N801 - minimal SimpleNamespace stand-in with the attributes build_bindings touches
            pass
        inputs = I()
        inputs.episode = "E12"
        inputs.asset_library = {"project_id": project_id, "assets": {"characters": {}}}
        inputs.asset_library_path = Path("/x/asset_library.json")
        inputs.engine_root = Path("/x")
        inputs.awaited_asset_dir = Path("/x/awaited")
        inputs.wardrobe_by_character = wardrobe_map
        inputs.shots = {"E12-S01-01": {"prompt_spec": {"cast": []}}}
        inputs.subspace_tasks = {"E12-S01-01": {"blocking": {"characters": [{"character_id": "CHAR-A", "character": "甲"}], "props": []}}}
        return inputs

    def _run(self, inputs):
        space = [{"role": "episode_global_space_map", "path": "/x/e.png"},
                 {"role": "global_space_map", "path": "/x/g.png"},
                 {"role": "subspace_layout", "path": "/x/s.png"}]
        scene = {"role": "scene", "path": "/x/scene.png"}

        def fake_entity_binding(_inputs, role, category, asset_id, name, kind, view=None):
            return {"role": role, "entity_id": asset_id, "path": f"/x/{role}-{asset_id}.png"}
        with patch.object(bkm, "map_bindings", return_value=space), \
             patch.object(bkm, "scene_binding", return_value=scene), \
             patch.object(bkm, "entity_binding", side_effect=fake_entity_binding), \
             patch.object(bkm, "wardrobe_plate_excluded", return_value=False):
            rows, _, _ = bkm.build_bindings(inputs, "E12-S01-01", "gate")
        return _roles(rows), getattr(inputs, "wardrobe_policy_report", {})

    def test_declared_work_before_activation_keeps_plate(self):
        inputs = self._inputs("NALU-YEWUJIANG", {"CHAR-A": {"authored_description": "粗布袍"}})
        inputs.episode = "E11"
        inputs.shots = {"E11-S01-01": inputs.shots["E12-S01-01"]}; inputs.subspace_tasks = {"E11-S01-01": inputs.subspace_tasks["E12-S01-01"]}
        space = [{"role": "episode_global_space_map", "path": "/x/e.png"}, {"role": "global_space_map", "path": "/x/g.png"}, {"role": "subspace_layout", "path": "/x/s.png"}]
        def fake_entity_binding(_inputs, role, category, asset_id, name, kind, view=None):
            return {"role": role, "entity_id": asset_id, "path": f"/x/{role}-{asset_id}.png"}
        with patch.object(bkm, "map_bindings", return_value=space), patch.object(bkm, "scene_binding", return_value={"role": "scene", "path": "/x/scene.png"}), \
             patch.object(bkm, "entity_binding", side_effect=fake_entity_binding), patch.object(bkm, "wardrobe_plate_excluded", return_value=False):
            rows, _, _ = bkm.build_bindings(inputs, "E11-S01-01", "gate")
        self.assertIn("character_wardrobe", _roles(rows))
        self.assertEqual(inputs.wardrobe_policy_report["decision"]["reason"], "WARDROBE_POLICY_BEFORE_ACTIVATION:E12")

    def test_declared_work_with_authored_wardrobe_drops_plate(self):
        roles, report = self._run(self._inputs("NALU-YEWUJIANG", {"CHAR-A": {"authored_description": "粗布袍"}}))
        self.assertNotIn("character_wardrobe", roles)
        self.assertEqual(report["work_id"], "NALU-YEWUJIANG")
        self.assertIs(report["decision"]["drop"], True)
        self.assertEqual(report["shots"]["E12-S01-01"], {"wardrobe_text_present": True, "wardrobe_rows_authored": 1, "wardrobe_rows_kept": 0})

    def test_declared_work_without_authored_wardrobe_keeps_plate(self):
        roles, report = self._run(self._inputs("NALU-YEWUJIANG", {}))
        self.assertIn("character_wardrobe", roles)
        self.assertEqual(report["shots"]["E12-S01-01"]["wardrobe_text_present"], False)
        self.assertEqual(report["shots"]["E12-S01-01"]["wardrobe_rows_kept"], 1)

    def test_undeclared_work_keeps_plate_regardless_of_episode(self):
        roles, report = self._run(self._inputs("QINGSHAN-E59", {"CHAR-A": {"authored_description": "x"}}))
        self.assertIn("character_wardrobe", roles)
        self.assertEqual(report["decision"]["reason"], "WARDROBE_POLICY_SCOPE_UNDECLARED")

    def test_missing_project_id_keeps_plate_and_records_unresolved(self):
        roles, report = self._run(self._inputs(None, {"CHAR-A": {"authored_description": "x"}}))
        self.assertIn("character_wardrobe", roles)
        self.assertIsNone(report["work_id"])
        self.assertEqual(report["decision"]["reason"], "WARDROBE_POLICY_SCOPE_UNRESOLVED")


if __name__ == "__main__":
    unittest.main()
