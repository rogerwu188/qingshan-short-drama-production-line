import unittest

from tools.wardrobe_identity_contract import validate_wardrobe_contract, wardrobe_prompt_block


def row(name, tier, silhouette, primary, secondary, accessory):
    return {
        "character": name, "social_tier": tier, "role_basis": f"剧本中的{tier}",
        "silhouette": silhouette, "outer_layer": f"{primary}外袍", "inner_layer": f"{secondary}内衫",
        "primary_color": primary, "secondary_color": secondary, "material": "细密棉绸",
        "pattern": "低对比暗纹", "belt_or_fastening": f"{secondary}束带", "footwear": "软底短靴",
        "accessory": accessory, "condition": "符合当前剧情的使用状态",
        "continuity_key": f"{name}-{primary}-{secondary}",
    }


def unit(rows):
    return {
        "unit_id": "U1",
        "ordered_prompt_specs": [{"cast": [
            {"character": "甲", "face_visibility": "VISIBLE_PER_FRAME_CONTENT"},
            {"character": "乙", "face_visibility": "VISIBLE_PER_FRAME_CONTENT"},
        ]}],
        "wardrobe_contract": {"characters": rows},
    }


class WardrobeIdentityContractTest(unittest.TestCase):
    def test_peer_roles_must_be_visually_distinct(self):
        same = [
            row("甲", "MERCHANT", "宽袖直身", "灰褐", "土黄", "算盘袋"),
            row("乙", "MERCHANT", "宽袖直身", "灰褐", "土黄", "算盘袋"),
        ]
        report = validate_wardrobe_contract(unit(same))
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("PEER_DISTINCTION_INSUFFICIENT" in item for item in report["failures"]))

    def test_role_aware_itemized_distinct_clothing_compiles(self):
        distinct = [
            row("甲", "MERCHANT", "圆肩宽袖短褙子", "铜褐", "米白", "算盘袋"),
            row("乙", "MERCHANT", "窄肩长衫加半臂", "苔绿", "黛青", "钥匙串"),
        ]
        current = unit(distinct)
        self.assertEqual(validate_wardrobe_contract(current)["status"], "PASS")
        text = wardrobe_prompt_block(current)
        self.assertIn("地位依据", text)
        self.assertIn("禁止全员默认麻布或粗布", text)

    def test_generic_ma_bu_default_is_forbidden(self):
        rows = [row("甲", "LABORER", "短打", "灰", "褐", "草绳")]
        rows[0]["material"] = "麻布"
        current = {
            "unit_id": "U2",
            "ordered_prompt_specs": [{"cast": [{"character": "甲"}]}],
            "wardrobe_contract": {"characters": rows},
        }
        self.assertEqual(validate_wardrobe_contract(current)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
