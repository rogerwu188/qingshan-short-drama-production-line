"""tools/knowledge_consumption_ledger.py on synthetic fixtures (offline).

Codex knowledge-loop audit 2026-10-27, gap 3: "EXPORTED" (a briefing file
exists), "APPLIED" (a rule's clause actually fired on a real shot) and
"VERIFIED" (that firing's effect was checked against real compiled/submitted
content) must not collapse into one "READ" status.  These tests prove the
three states are independently true/false and that APPLIED evidence is
produced by the REAL production entry point
(``nalu_prompt_rules.apply`` -> ``applied_summary`` -> ``record_application``),
not a parallel tool that only looks like it is connected.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from tools import knowledge_consumption_ledger as kcl  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "nalu_prompt_rules", REPO / "lines/nalu/runtime/tools/nalu_prompt_rules.py")
NPR = importlib.util.module_from_spec(_SPEC)
sys.modules["nalu_prompt_rules"] = NPR
_SPEC.loader.exec_module(NPR)

MEMORY = [{"failure_code": "ACTION_NO_OUTCOME", "do_not_repeat": "动作段落必须收束",
           "stage": "prompt", "knowledge_id": "K043"}]


def shot(**kw):
    base = {"shot_id": "EXX-S01-01", "action": "甲走到乙面前", "sec": 4.0, "cast": ["A"], "size": "中景",
            "camera_family": "DOLLY"}
    base.update(kw)
    return base


class RealEntryWiringTest(unittest.TestCase):
    """Builds NPR_APPLIED exactly the way build_eNN_layers.py does (a loop
    calling nalu_prompt_rules.apply per shot, collecting the applied list per
    shot id) and feeds it through applied_summary -> record_application,
    proving the ledger is wired to the same function every real episode
    builder calls, not to a reimplementation of its logic."""

    def test_builder_loop_simulation_produces_applied_evidence(self) -> None:
        ctx = {"failure_memory": MEMORY}
        shots = [shot(shot_id="E99-S01-01", state_delta_dimensions=["CONTACT"]),  # triggers K043
                 shot(shot_id="E99-S01-02")]                                      # does not
        npr_applied: dict[str, list[str]] = {}
        for row in shots:
            _, applied, _ = NPR.apply(row, ctx)  # the exact call every build_eNN_layers.py makes
            npr_applied[row["shot_id"]] = applied

        tmp = Path(tempfile.mkdtemp())
        record = kcl.record_application(tmp, episode="E99", line="nalu", stage="S1",
                                        npr_applied=npr_applied)
        self.assertEqual(record["rule_ids_applied"], ["K043"])
        self.assertEqual(record["shots_by_rule_id"]["K043"], ["E99-S01-01"])
        self.assertEqual(record["shot_count"], 2)
        self.assertIn("E99-S01-01", record["raw_tags_by_shot"])

        status = kcl.status_for_rule(REPO, tmp, "E99", "K043")
        self.assertTrue(status["applied"])
        self.assertEqual(status["applied_evidence"][0]["shot_ids"], ["E99-S01-01"])
        # a rule that never triggered must not be reported as applied just
        # because something else in the same compile was
        other = kcl.status_for_rule(REPO, tmp, "E99", "K999")
        self.assertFalse(other["applied"])
        self.assertEqual(other["applied_evidence"], [])


class ThreeStateIndependenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.reports = self.tmp / "reports"
        self.reports.mkdir(parents=True)

    def _write_briefing(self, episode: str, rule_ids: list[str]) -> None:
        (self.reports / f"{episode}_KNOWLEDGE_BRIEFING.json").write_text(
            json.dumps({"rule_ids": rule_ids}), encoding="utf-8")

    def test_exported_without_applied_without_verified(self) -> None:
        """A rule can be in the briefing and never fire -- audit's own
        isolated repro: a new rule entered the briefing but the compiler
        output never changed because no trigger fired."""
        self._write_briefing("E99", ["K050"])
        status = kcl.status_for_rule(REPO, self.tmp, "E99", "K050")
        self.assertTrue(status["exported"])
        self.assertFalse(status["applied"])
        self.assertFalse(status["verified"])

    def test_applied_without_verified(self) -> None:
        self._write_briefing("E99", ["K050"])
        kcl.record_application(self.tmp, episode="E99", line="nalu", stage="S1",
                               npr_applied={"E99-S01-01": ["KNOWLEDGE:K050"]})
        status = kcl.status_for_rule(REPO, self.tmp, "E99", "K050")
        self.assertTrue(status["exported"])
        self.assertTrue(status["applied"])
        self.assertFalse(status["verified"])

    def test_applied_and_verified(self) -> None:
        self._write_briefing("E99", ["K050"])
        kcl.record_application(self.tmp, episode="E99", line="nalu", stage="S1",
                               npr_applied={"E99-S01-01": ["KNOWLEDGE:K050"]})
        kcl.record_verification(self.tmp, rule_id="K050", test_name="test_solo_face_survives_compile",
                                assertion="SOLO_FACE clause present in final compiled prompt text",
                                checked_output="compile_model_prompt() return value", episode="E99")
        status = kcl.status_for_rule(REPO, self.tmp, "E99", "K050")
        self.assertTrue(status["exported"] and status["applied"] and status["verified"])
        self.assertEqual(status["verified_evidence"][0]["test_name"], "test_solo_face_survives_compile")

    def test_not_exported_but_somehow_applied_is_still_reported_honestly(self) -> None:
        """No briefing at all: exported must read False, independent of the
        other two -- this function never infers one claim from another."""
        kcl.record_application(self.tmp, episode="E99", line="nalu", stage="S1",
                               npr_applied={"E99-S01-01": ["KNOWLEDGE:K050"]})
        status = kcl.status_for_rule(REPO, self.tmp, "E99", "K050")
        self.assertFalse(status["exported"])
        self.assertTrue(status["applied"])


class RecordApplicationValidationTest(unittest.TestCase):
    def test_requires_episode_and_stage(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        with self.assertRaises(ValueError):
            kcl.record_application(tmp, episode="", line="nalu", stage="S1", npr_applied={})
        with self.assertRaises(ValueError):
            kcl.record_application(tmp, episode="E99", line="nalu", stage="", npr_applied={})
        with self.assertRaises(ValueError):
            kcl.record_application(tmp, episode="E99", line="nalu", stage="S1", npr_applied="not a dict")

    def test_bare_tags_are_kept_raw_but_not_claimed_as_registry_evidence(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        record = kcl.record_application(tmp, episode="E99", line="nalu", stage="S1",
                                        npr_applied={"E99-S01-01": ["SOLO_FACE", "NO_BLACK"]})
        self.assertEqual(record["rule_ids_applied"], [])
        self.assertEqual(record["raw_tags_by_shot"]["E99-S01-01"], ["NO_BLACK", "SOLO_FACE"])

    def test_tag_to_rule_id_lets_a_caller_link_a_bare_tag_explicitly(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        record = kcl.record_application(tmp, episode="E99", line="nalu", stage="S1",
                                        npr_applied={"E99-S01-01": ["SOLO_FACE"]},
                                        tag_to_rule_id={"SOLO_FACE": "K009"})
        self.assertEqual(record["rule_ids_applied"], ["K009"])
        self.assertEqual(record["shots_by_rule_id"]["K009"], ["E99-S01-01"])


class RecordVerificationValidationTest(unittest.TestCase):
    def test_requires_every_field(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        base = dict(rule_id="K050", test_name="t", assertion="a", checked_output="o")
        for field in ("rule_id", "test_name", "assertion", "checked_output"):
            kwargs = dict(base)
            kwargs[field] = "   " if field != "rule_id" else ""
            with self.assertRaises(ValueError, msg=field):
                kcl.record_verification(tmp, **kwargs)

    def test_verification_is_queryable_by_rule_id(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        kcl.record_verification(tmp, rule_id="K050", test_name="t1", assertion="a1", checked_output="o1")
        kcl.record_verification(tmp, rule_id="K051", test_name="t2", assertion="a2", checked_output="o2")
        rows = kcl.verifications(tmp, rule_id="K050")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["test_name"], "t1")


class CorruptLedgerTest(unittest.TestCase):
    def test_corrupt_line_raises(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        path = kcl.ledger_path(tmp)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"kind": "APPLIED"}\nnot json\n', encoding="utf-8")
        with self.assertRaises(ValueError):
            kcl.applications(tmp)


if __name__ == "__main__":
    unittest.main()
