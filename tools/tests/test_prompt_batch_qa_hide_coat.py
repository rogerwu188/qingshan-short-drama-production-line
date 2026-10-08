"""K085 — the wardrobe hide-coat test must not count a denial as a requirement.

nalu E11 秦铭 outer_layer reads

    无外披（全集不披裘氅、不带毛领：沿 E09 审定口径，新生后体热，源章 ch11 未写添衣）

The old check scanned that field for the bare token 裘氅 and read the denial as a demand for
a fur coat, so the gate compared True against a correctly-plain rendered line and reported
``kf_wardrobe_hide_coat_consistent`` FAIL — the right verdict with the wrong shape, which is
what sent E11's batch gate to the reference plate.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lines/nalu/runtime/tools"))
from prompt_batch_qa import mentions_hide_coat


class HideCoatNegationTests(unittest.TestCase):
    def test_the_e11_field_is_not_a_requirement(self):
        self.assertFalse(mentions_hide_coat(
            "无外披（全集不披裘氅、不带毛领：沿 E09 审定口径，新生后体热，源章 ch11 未写添衣）"))

    def test_recorded_denial_idioms(self):
        for value in ("无外披兽皮", "无兽皮外披", "不披裘氅", "无毛领、无裘氅的粗布棉衣",
                      "无裘氅", "不带毛领", "无外披（全集不披裘氅、不带毛领）"):
            with self.subTest(value=value):
                self.assertFalse(mentions_hide_coat(value))

    def test_a_fur_coat_is_still_a_requirement(self):
        for value in ("整张兽皮大衣（外层，及膝、毛面在外，非坎肩）",
                      "深褐粗麻交领长袍外罩及膝整张兽皮大衣", "兽皮短袄", "兽皮大衣，毛面在外"):
            with self.subTest(value=value):
                self.assertTrue(mentions_hide_coat(value))

    def test_a_negation_scoped_to_another_garment_does_not_clear_the_coat(self):
        """「无毛领的兽皮大衣」: 无 scopes to 毛领; the coat is still there."""
        for value in ("无毛领的兽皮大衣", "没有毛领的兽皮大衣", "非坎肩的整张兽皮大衣",
                      "不是坎肩，是整张兽皮大衣"):
            with self.subTest(value=value):
                self.assertTrue(mentions_hide_coat(value))

    def test_a_fur_hat_is_not_an_outer_coat(self):
        for value in ("兽皮护耳帽", "皮帽", "兽皮帽"):
            with self.subTest(value=value):
                self.assertFalse(mentions_hide_coat(value))

    def test_plain_inner_garment(self):
        self.assertFalse(mentions_hide_coat("粗布棉衣（内层，旧、洗白）"))


if __name__ == "__main__":
    unittest.main()
