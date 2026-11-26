"""E29 S1 blocker (device 1101, 2026-11-26): the BILI_V1 director pass emptied the cast of silent units.

A silent unit has no speaker, so the shot grammar's "everyone but the speaker" was the unit's whole visible cast and a
SINGLE decision stripped it.  A silent unit that shows people keeps its cast and its framing; the director only
changes the scale.  Covers the three shapes: a silent single, a silent single carrying a beat tag, a silent
front/back pair; and the compiled screenplay path (（无声） lines).  Offline, no paid call."""
from __future__ import annotations

import copy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import director_pass as dp  # noqa: E402
import screenplay_compile as spc  # noqa: E402
from tools.tests.test_e27_prompt_round import A, B, scene_contract  # noqa: E402

FIXTURE = ROOT / "tools" / "tests" / "fixtures" / "screenplay_e25"


def silent_shot(sid: str, cast: list[tuple[str, str]], action: str, *, role: str = "") -> dict:
    plan = {"shot_scale": "MEDIUM", "scale_source": "screenplay_compile", "motion_family": "LOCKED",
            "motion_direction": "NONE", "start_framing": "x", "end_framing": "x"}
    spec = {"dialogue": "", "camera_plan": plan,
            "cast": [{"character": c, "character_id": c, "face_visibility": face} for c, face in cast],
            "action": {"primary_action": action},
            "role_semantic_disambiguation": {"entity_presence": {c: "VISIBLE_AND_IDENTITY_LOCKED" for c, _ in cast}}}
    if role:
        spec["beat_role"] = role
    return {"shot_id": sid, "scene_id": "E09-S01", "shot_size": "MEDIUM", "target_seconds": 4.0,
            "camera": "MEDIUM，固定机位", "prompt_spec": spec}


FRONT = "FRONT_FACE_VISIBLE"
BACK = "BACK_AND_SHOULDERS_ONLY"


class SilentCastTest(unittest.TestCase):
    def setUp(self):
        c = scene_contract(4)
        c["shots"].insert(0, silent_shot("E09-S01-00", [(A, FRONT)], f"{A}推门而入"))
        c["shots"].insert(3, silent_shot("E09-S01-02B", [(A, FRONT)], f"{A}停下，看着对方", role="TURN"))
        c["shots"].append(silent_shot("E09-S01-99", [(B, FRONT), (A, BACK)], f"{B}看着{A}的背影坐下"))
        self.contract = c
        self.out, self.report = dp.direct(copy.deepcopy(c), force=True)
        self.by_id = {s["shot_id"]: s for s in self.out["shots"]}

    def test_silent_single_keeps_its_cast(self):
        self.assertEqual(dp.visible_cast(self.by_id["E09-S01-00"]), [A])

    def test_silent_single_with_a_beat_tag_keeps_its_cast(self):
        self.assertEqual(dp.visible_cast(self.by_id["E09-S01-02B"]), [A])

    def test_silent_pair_keeps_cast_and_faces(self):
        shot = self.by_id["E09-S01-99"]
        self.assertEqual(dp.visible_cast(shot), [B, A])
        faces = {r["character_id"]: r["face_visibility"] for r in shot["prompt_spec"]["cast"]}
        self.assertEqual(faces, {B: FRONT, A: BACK})
        presence = shot["prompt_spec"]["role_semantic_disambiguation"]["entity_presence"]
        self.assertEqual(set(presence), {A, B})

    def test_no_silent_unit_loses_anyone_and_dialogue_grammar_still_runs(self):
        before = {s["shot_id"]: dp.visible_cast(s) for s in self.contract["shots"] if not dp.speaking(s)}
        for sid, cast in before.items():
            self.assertEqual(dp.visible_cast(self.by_id[sid]), cast, sid)
        self.assertTrue(any(a.startswith("SHOT_GRAMMAR:") and "/SINGLE" in a for a in self.report["applied"]))

    def test_compiled_silent_lines_keep_their_cast(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "e25"
            shutil.copytree(FIXTURE, work)
            path = work / "E25_SCREENPLAY.md"
            text = path.read_text(encoding="utf-8")
            for old, new in (("白桃停下令牌", "（无声）白桃停下令牌"),
                             ("商余烬看着令牌，低低笑了一声。", "（无声）商余烬看着令牌，低低笑了一声。 #转折:REVERSAL"),
                             ("商余烬把麒麟的手按下", "（无声）商余烬把麒麟的手按下")):
                self.assertIn(old, text)
                text = text.replace(old, new, 1)
            path.write_text(text, encoding="utf-8")
            contract = spc.compile_files(work, "E25")["contract"]
        before = {s["shot_id"]: dp.visible_cast(s) for s in contract["shots"] if not dp.speaking(s)}
        self.assertGreaterEqual(sum(1 for c in before.values() if len(c) == 1), 2)
        directed, report = dp.direct(copy.deepcopy(contract), force=True)
        self.assertEqual(report["integrity_failures"], [])
        for shot in directed["shots"]:
            if shot["shot_id"] in before:
                self.assertEqual(dp.visible_cast(shot), before[shot["shot_id"]], shot["shot_id"])


if __name__ == "__main__":
    unittest.main()
