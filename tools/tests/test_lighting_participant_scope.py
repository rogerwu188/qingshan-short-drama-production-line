"""Regression tests for scoping a lighting line to the shot's own cast.

The lighting line is authored per SCENE and copied into every shot of that
scene.  A person named in it is the light's motivation, not this shot's cast, so
carried into a shot that does not show that person the name reads to the provider
as a person to render — an empty plate comes back with a face in it.

The deciding evidence is the shot's own authored text, which is why these tests
are written against that text and not against a preference.
"""

import unittest

from tools.lighting_participant_scope import (
    POLICY_ID,
    audit_shots,
    scoped_lighting_line,
)

NAME2ID = {
    "秦铭": "CHAR-QINMING",
    "许岳平": "CHAR-XUYUEPING",
    "冯易安": "CHAR-FENGYIAN",
}
LABEL = {v: k for k, v in NAME2ID.items()}


def _shot(**overrides):
    shot = {
        "shot_id": "E99-S01-01",
        "axis": "",
        "blocking": "",
        "cast": [],
    }
    shot.update(overrides)
    return shot


class OffFrameShotTest(unittest.TestCase):
    """A shot that marks the named person 画外 must not carry their name."""

    def test_off_frame_marker_drops_the_name(self):
        shot = _shot(
            axis="许岳平（画面中央）站在池边，面向画右外的秦铭",
            cast=[{"character_id": "CHAR-XUYUEPING", "canonical_name": "许岳平"}],
        )
        line, removals = scoped_lighting_line(
            "火泉池火红的光照亮池边的老藤与秦铭俯身的脸",
            shot=shot, name_to_entity=NAME2ID, entity_label=LABEL,
        )
        self.assertEqual(line, "火泉池火红的光照亮池边的老藤")
        self.assertEqual([r["name"] for r in removals], ["秦铭"])
        self.assertEqual(removals[0]["reason"], "SHOT_MARKS_PERSON_OFF_FRAME")
        self.assertEqual(removals[0]["policy"], POLICY_ID)

    def test_each_off_frame_marker_is_recognised(self):
        for marker in ("画外", "画右外", "画左外", "画上外", "画下外"):
            shot = _shot(axis=f"许岳平（画面中央）面向{marker}的秦铭", cast=[])
            _, removals = scoped_lighting_line(
                "光照着秦铭的脸", shot=shot, name_to_entity=NAME2ID,
            )
            self.assertEqual(len(removals), 1, marker)
            self.assertEqual(removals[0]["reason"], "SHOT_MARKS_PERSON_OFF_FRAME", marker)


class NeverNamedShotTest(unittest.TestCase):
    """A shot that never mentions the person must not carry their name."""

    def test_name_absent_from_shot_text_is_dropped(self):
        shot = _shot(axis="火泉池水面（画面中央），几只红莹莹的贝壳半没在水中")
        _, removals = scoped_lighting_line(
            "灯盏的光照着许岳平偏向一边的脸，包间角落压在暗处",
            shot=shot, name_to_entity=NAME2ID, entity_label=LABEL,
        )
        self.assertEqual(removals[0]["reason"], "SHOT_NEVER_NAMES_PERSON")


class PresentCastTest(unittest.TestCase):
    """A shot that does put the person in frame keeps the name."""

    def test_cast_member_keeps_the_clause(self):
        shot = _shot(
            axis="秦铭（画面中央）俯身看向池中",
            cast=[{"character_id": "CHAR-QINMING", "canonical_name": "秦铭"}],
        )
        line, removals = scoped_lighting_line(
            "火泉池火红的光照亮池边的老藤与秦铭俯身的脸",
            shot=shot, name_to_entity=NAME2ID, entity_label=LABEL,
        )
        self.assertEqual(line, "火泉池火红的光照亮池边的老藤与秦铭俯身的脸")
        self.assertEqual(removals, [])

    def test_entity_id_in_cast_is_enough(self):
        shot = _shot(cast=[{"character_id": "CHAR-QINMING"}])
        line, removals = scoped_lighting_line(
            "光照着秦铭的脸", shot=shot, name_to_entity=NAME2ID,
        )
        self.assertEqual(removals, [])

    def test_alias_in_cast_is_enough(self):
        # A cast row may carry the display name while the line uses the same
        # string; the identity match must not depend on which namespace it is.
        shot = _shot(cast=[{"canonical_name": "许岳平"}])
        _, removals = scoped_lighting_line(
            "灯盏的光照着许岳平偏向一边的脸", shot=shot, name_to_entity=NAME2ID,
        )
        self.assertEqual(removals, [])


class LightPreservationTest(unittest.TestCase):
    """Only the participant clause goes; the light itself always survives."""

    def test_light_source_and_surfaces_are_preserved(self):
        shot = _shot(cast=[])
        for original, expected in (
            ("火泉池火红的光照亮池边的老藤与秦铭俯身的脸", "火泉池火红的光照亮池边的老藤"),
            ("窗外的雪光与灯盏橘光交叉照着窗边的秦铭", "窗外的雪光与灯盏橘光交叉照着窗边"),
            ("门开时风雪灌入，灯盏的光被吹得一晃，冯易安皮甲上落着雪",
             "门开时风雪灌入，灯盏的光被吹得一晃"),
        ):
            line, _ = scoped_lighting_line(
                original, shot=shot, name_to_entity=NAME2ID, entity_label=LABEL,
            )
            self.assertEqual(line, expected)

    def test_a_dangling_light_verb_reads_as_a_statement_about_the_light(self):
        shot = _shot(cast=[])
        line, _ = scoped_lighting_line(
            "檐下红灯笼在风雪里摇晃，橘红的光照着许岳平左脸那道很淡的手印",
            shot=shot, name_to_entity=NAME2ID, entity_label=LABEL,
        )
        self.assertEqual(line, "檐下红灯笼在风雪里摇晃，橘红的光亮着")
        self.assertNotIn("许岳平", line)

    def test_non_person_detail_is_never_touched(self):
        shot = _shot(cast=[])
        original = "雪面反着青蓝月色，密林里只有零星红光，箭出时雪屑扬起"
        line, removals = scoped_lighting_line(
            original, shot=shot, name_to_entity=NAME2ID, entity_label=LABEL,
        )
        self.assertEqual(line, original)
        self.assertEqual(removals, [])

    def test_empty_line_is_returned_unchanged(self):
        self.assertEqual(scoped_lighting_line("", shot=_shot(), name_to_entity=NAME2ID), ("", []))


class AuditReportTest(unittest.TestCase):
    """The audit is read-only and reports every finding with its reason."""

    def test_audit_reports_each_finding_once(self):
        shots = [
            _shot(shot_id="A", axis="面向画右外的秦铭", cast=[]),
            _shot(shot_id="B", cast=[{"character_id": "CHAR-QINMING"}]),
            _shot(shot_id="C", cast=[]),
        ]
        lighting = {
            "A": "光照着秦铭的脸",
            "B": "光照着秦铭的脸",
            "C": "雪面反着青蓝月色",
        }
        report = audit_shots(
            shots, lighting_of=lambda s: lighting[s["shot_id"]],
            name_to_entity=NAME2ID, entity_label=LABEL,
        )
        self.assertEqual(report["status"], "FINDINGS")
        self.assertEqual(report["finding_count"], 1)
        self.assertEqual(report["findings"][0]["shot_id"], "A")
        self.assertEqual(report["policy"], POLICY_ID)

    def test_clean_episode_reports_pass(self):
        shots = [_shot(shot_id="A", cast=[{"character_id": "CHAR-QINMING"}])]
        report = audit_shots(
            shots, lighting_of=lambda s: "光照着秦铭的脸",
            name_to_entity=NAME2ID, entity_label=LABEL,
        )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["findings"], [])

    def test_audit_does_not_mutate_the_shot(self):
        shot = _shot(axis="面向画右外的秦铭", cast=[])
        before = dict(shot)
        audit_shots(
            [shot], lighting_of=lambda s: "光照着秦铭的脸",
            name_to_entity=NAME2ID, entity_label=LABEL,
        )
        self.assertEqual(shot, before)

    def test_longest_name_wins_when_names_overlap(self):
        # 许岳平 / 岳平 — the longer key must be tried first or the shorter one
        # matches a substring and leaves a fragment behind.
        names = {"许岳平": "CHAR-XUYUEPING", "岳平": "CHAR-XUYUEPING"}
        line, removals = scoped_lighting_line(
            "光照着许岳平的脸", shot=_shot(cast=[]), name_to_entity=names,
        )
        self.assertNotIn("岳平", line)
        self.assertEqual(len(removals), 1)


if __name__ == "__main__":
    unittest.main()
