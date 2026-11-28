"""Deep review 1205 E15 (2026-11-28): a phone call written with both callers in one room (the father rendered at
the daughter's meeting table, the phone visible in 2 of 17 shots).  script_pacing_check reports
REMOTE_CALL_ONE_PLACE (writer revision, taste -- never a block) unless the far caller's shots are cross-cut to their
own location.  Offline."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines" / "nalu" / "runtime" / "tools"))

import script_pacing_check as sp  # noqa: E402

CAST_M = [{"character": "Matilda", "character_id": "CHAR-M"}]
CAST_D = [{"character": "Wilson", "character_id": "CHAR-W"}]


def _shot(sid: str, who: str, line: str, blocking: str) -> dict:
    return {"shot_id": sid, "scene_id": "E15-S01", "target_seconds": 4.0, "state_delta_dimensions": ["POSTURE"],
            "blocking": blocking, "prompt_spec": {"shot_id": sid, "dialogue": f"{who}: {line}",
                                                  "cast": CAST_M if who == "Matilda" else CAST_D}}


def _contract(cross_cut: bool) -> dict:
    shots = [_shot("E15-S01-01", "Matilda", "Hello.", "She answers the phone and keeps it at her ear."),
             _shot("E15-S01-02", "Wilson", "Hey sweetheart, it's Dad.", "He keeps a plain phone at his ear."),
             _shot("E15-S01-03", "Matilda", "Please call me Matilda.", "She grips the phone and looks down.")]
    c = {"dialogue_language": "en", "shots": shots,
         "scene_states": [{"scene_id": "E15-S01", "location_id": "LOC-REFUGE-ROOM", "time_id": "DAY"}]}
    if cross_cut:
        c["shot_scene_overrides"] = {"E15-S01-02": {"location_id": "LOC-WILSON-HOUSE"}}
    return c


class RemoteCallOnePlace(unittest.TestCase):
    def test_call_in_one_room_is_reported_with_a_fix(self):
        c = _contract(cross_cut=False)
        self.assertEqual(sp.measure(c, "en").get("remote_call_one_place", []), ["E15-S01"])
        r = sp.evaluate(c, "en")
        self.assertIn("REMOTE_CALL_ONE_PLACE:E15-S01", r["failures"])
        self.assertIn("shot_scene_overrides", r["fixes"]["REMOTE_CALL_ONE_PLACE"])

    def test_cross_cut_call_passes(self):
        self.assertEqual(sp.measure(_contract(cross_cut=True), "en").get("remote_call_one_place", []), [])

    def test_in_room_talk_with_a_phone_prop_is_not_a_call(self):
        c = _contract(cross_cut=False)
        for s in c["shots"]:
            s["blocking"] = "She shows him a photo on her phone."
        self.assertEqual(sp.measure(c, "en").get("remote_call_one_place", []), [])

    def test_writer_contract_carries_the_rule(self):
        text = (ROOT / "agent_factory" / "storyclaw_portable" / "WRITER_CONTRACT.md").read_text(encoding="utf-8")
        self.assertIn("REMOTE_CALL_ONE_PLACE", text)


if __name__ == "__main__":
    unittest.main()
