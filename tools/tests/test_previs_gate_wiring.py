"""The previs gate actually runs in front of a paid stage (plan §4, §10.7/§10.13).

Before this, ``tools/episode_previs.py`` was a library nobody called: every
episode reached its first paid stage without a single machine check of dialogue
coverage, dialogue fit, grouping coverage or speaker registration.  These tests
call the pipeline's own gate function — not the previs module — so a gate that
is never wired fails here.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[2]
for _path in (_ROOT / "lines" / "nalu" / "runtime" / "tools", _ROOT / "tools", _ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import episode_previs
import nalu_pipeline


def _contract(**overrides):
    contract = {
        "episode": "E98",
        "shots": [
            {"shot_id": "S1", "scene_id": "SC1", "target_seconds": 4,
             "prompt_spec": {"cast": [{"character_id": "CHAR-A"}]}},
            {"shot_id": "S2", "scene_id": "SC1", "target_seconds": 4,
             "prompt_spec": {"cast": [{"character_id": "CHAR-A"}]}},
        ],
        "scene_states": [{"scene_id": "SC1"}],
        "character_entities": [{"character_id": "CHAR-A"}],
        "audio_contract": {"dialogue_units": [
            {"shot_id": "S1", "speaker_id": "CHAR-A", "text": "甲：走 吧"},
        ]},
    }
    contract.update(overrides)
    return contract


def _grouping():
    return {"units": [{"unit_id": "U1", "editorial_shot_ids": ["S1", "S2"]}]}


class _Paths:
    """Only the attributes previs_gate touches."""

    def __init__(self, root: Path, contract: dict, grouping: dict | None):
        self.contract = root / "contract.json"
        self.contract.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
        self.grouping_plan = root / "grouping.json"
        if grouping is not None:
            self.grouping_plan.write_text(json.dumps(grouping), encoding="utf-8")
        self.keyframes = root / "keyframes"
        self.keyframes.mkdir(exist_ok=True)
        self.preprod_reports = root / "reports"
        self.preprod_reports.mkdir(exist_ok=True)


class _Ctx:
    def __init__(self, paths: _Paths, episode: str = "E98", rounds: dict | None = None):
        self.p = paths
        self.episode = episode
        self.state = {"previs_review_rounds": dict(rounds or {})}


class PrevisGateWiringTest(unittest.TestCase):
    def _policy(self, **body):
        policy = {
            "enabled_episodes": ["E98"],
            "blocks": {"S5": "PAID_KEYFRAMES", "S6": "PAID_VIDEO_UNITS"},
            "machine_failure_mode": "BLOCK",
            "director_review": {"blocking": False, "max_rounds": 2},
        }
        policy.update(body)
        return policy

    def _run(self, contract, grouping=None, policy=None, rounds=None):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _Paths(Path(tmp), contract, _grouping() if grouping is None else grouping)
            ctx = _Ctx(paths, rounds=rounds)
            with mock.patch.object(episode_previs, "policy_settings",
                                   lambda: self._policy(**(policy or {}))), \
                 mock.patch.object(nalu_pipeline, "_previs_policy",
                                   lambda: self._policy(**(policy or {}))):
                row = nalu_pipeline.previs_gate(ctx, "S5")
            # the temp tree dies with the context; keep what the assertions read
            if row.get("receipt") and Path(row["receipt"]).is_file():
                row["_receipt"] = json.loads(Path(row["receipt"]).read_text(encoding="utf-8"))
            return row

    def test_a_clean_contract_passes_and_writes_a_receipt(self):
        row = self._run(_contract())
        self.assertEqual(row["status"], "PASS")
        self.assertFalse(row["blocked"])
        self.assertEqual(row["machine_failures"], [])
        self.assertTrue(row["receipt"].endswith("E98_PREVIS_S5.json"))
        self.assertEqual(row["_receipt"]["scope"],
                         "ZERO_CREDIT_PREVIS_NOT_A_CUT_NOT_IDENTITY_OR_LIPSYNC_EVIDENCE")

    def test_an_unauthorised_repeated_line_blocks_the_paid_stage(self):
        contract = _contract()
        contract["audio_contract"]["dialogue_units"].append(
            {"shot_id": "S2", "speaker_id": "CHAR-A", "text": "甲：走 吧"})
        row = self._run(contract)
        self.assertTrue(row["blocked"])
        self.assertEqual(row["status"], "BLOCKED")
        codes = {f["code"] for f in row["machine_failures"]}
        self.assertIn("DIALOGUE_REPEATED_WITHOUT_REASON", codes)

    def test_an_unregistered_speaker_blocks(self):
        contract = _contract()
        contract["audio_contract"]["dialogue_units"][0]["speaker_id"] = "CHAR-GHOST"
        row = self._run(contract)
        self.assertTrue(row["blocked"])
        self.assertIn("DIALOGUE_SPEAKER_NOT_REGISTERED",
                      {f["code"] for f in row["machine_failures"]})

    def test_dialogue_that_cannot_fit_its_shot_blocks(self):
        contract = _contract()
        contract["audio_contract"]["dialogue_units"][0]["text"] = "甲：" + "这是一句非常长的台词" * 3
        row = self._run(contract)
        self.assertTrue(row["blocked"])
        self.assertIn("DIALOGUE_DOES_NOT_FIT_SHOT",
                      {f["code"] for f in row["machine_failures"]})

    def test_a_shot_no_unit_covers_blocks(self):
        row = self._run(_contract(), grouping={"units": [{"unit_id": "U1",
                                                          "editorial_shot_ids": ["S1"]}]})
        self.assertTrue(row["blocked"])
        self.assertIn("SHOT_NOT_IN_ANY_UNIT", {f["code"] for f in row["machine_failures"]})

    def test_a_missing_grouping_plan_blocks_rather_than_passing(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _Paths(Path(tmp), _contract(), grouping=None)
            paths.grouping_plan.unlink(missing_ok=True)
            ctx = _Ctx(paths)
            with mock.patch.object(nalu_pipeline, "_previs_policy", lambda: self._policy()), \
                 mock.patch.object(episode_previs, "policy_settings", lambda: self._policy()):
                row = nalu_pipeline.previs_gate(ctx, "S5")
            self.assertTrue(row["blocked"])
            self.assertIn("GROUPING_PLAN_MISSING_OR_EMPTY", " ".join(row["failures"]))

    def test_an_unenabled_episode_is_untouched(self):
        policy = {"enabled_episodes": [], "enabled_from_episode": None,
                  "machine_failure_mode": "BLOCK"}
        contract = _contract()
        contract["audio_contract"]["dialogue_units"].append(
            {"shot_id": "S2", "speaker_id": "CHAR-A", "text": "甲：走 吧"})
        with tempfile.TemporaryDirectory() as tmp:
            paths = _Paths(Path(tmp), contract, _grouping())
            ctx = _Ctx(paths)
            with mock.patch.object(nalu_pipeline, "_previs_policy", lambda: policy), \
                 mock.patch.object(episode_previs, "policy_settings", lambda: policy):
                row = nalu_pipeline.previs_gate(ctx, "S5")
        self.assertEqual(row["status"], "NOT_ENABLED")
        self.assertFalse(row["blocked"])

    def test_a_contract_may_opt_in_on_its_own(self):
        contract = _contract(previs_policy="EPISODE_PREVIS_V1")
        policy = {"enabled_episodes": [], "enabled_from_episode": None,
                  "machine_failure_mode": "BLOCK"}
        policy.update(self._policy())
        policy["enabled_episodes"] = []
        with tempfile.TemporaryDirectory() as tmp:
            paths = _Paths(Path(tmp), contract, _grouping())
            ctx = _Ctx(paths)
            with mock.patch.object(nalu_pipeline, "_previs_policy", lambda: policy), \
                 mock.patch.object(episode_previs, "policy_settings", lambda: policy):
                row = nalu_pipeline.previs_gate(ctx, "S5")
        self.assertEqual(row["status"], "PASS")

    def test_the_director_review_never_blocks_and_stops_after_the_round_limit(self):
        row = self._run(_contract(), rounds={"S5": 99})
        self.assertFalse(row["blocked"])
        self.assertEqual(row["director_review"]["status"], "CLOSED_ADVISORY")
        self.assertFalse(row["director_review"]["blocking"])

    def test_the_round_limit_never_waives_a_machine_failure(self):
        contract = _contract()
        contract["audio_contract"]["dialogue_units"].append(
            {"shot_id": "S2", "speaker_id": "CHAR-A", "text": "甲：走 吧"})
        row = self._run(contract, rounds={"S5": 99})
        self.assertTrue(row["blocked"], "advisory rounds must not excuse a contract conflict")

    def test_estimated_durations_stay_labelled_estimated(self):
        row = self._run(_contract())
        previs = row["_receipt"]
        self.assertGreaterEqual(previs["estimated_dialogue_lines"], 1)
        self.assertEqual(previs["measured_dialogue_lines"], 0)


class PaidStagesCallTheGateTest(unittest.TestCase):
    """S5 and S6 must actually call it, not merely import it."""

    def test_s5_and_s6_start_with_the_gate(self):
        import inspect
        for func in (nalu_pipeline.stage_s5, nalu_pipeline.stage_s6):
            source = inspect.getsource(func)
            self.assertIn("previs_gate(ctx,", source, func.__name__)
            head = source.splitlines()[:20]
            self.assertTrue(any("previs_gate(ctx," in line for line in head),
                            f"{func.__name__} must gate before any work")

    def test_a_blocked_gate_stops_s5_before_building_a_manifest(self):
        blocked = {"status": "BLOCKED", "blocked": True, "receipt": "/tmp/x.json",
                   "machine_failures": [{"code": "SHOT_NOT_IN_ANY_UNIT", "ref": "S1"}]}
        with mock.patch.object(nalu_pipeline, "previs_gate", lambda _c, _s: blocked), \
             mock.patch.object(nalu_pipeline.Ctx, "run",
                               side_effect=AssertionError("nothing may run when the gate blocks")):
            ctx = mock.MagicMock()
            ctx.p.contract = Path("/nonexistent")
            result = nalu_pipeline.stage_s5(ctx)
        self.assertEqual(result.status, nalu_pipeline.BLOCKED)
        self.assertIn("PREVIS_MACHINE_FAILURE:SHOT_NOT_IN_ANY_UNIT:S1", result.blockers)


if __name__ == "__main__":
    unittest.main()
