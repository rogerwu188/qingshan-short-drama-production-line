import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.shot_prompt_professionalism_gate import (
    detect_glyph_reveal_failures,
    evaluate_batch,
    validate_task,
)
from tools.human_realism_prompt_contract import build_keyframe_realism_block


class ShotPromptProfessionalismGateTest(unittest.TestCase):
    @staticmethod
    def image_prompt(scale: str) -> str:
        return (
            f"《青山》电影级关键帧。[[char]] [[scene]] [[prop]]。剧本硬锁地点、时段、天气与事件。"
            "人物身份锁与道具锁不可修改。只表现一个决定性瞬间。"
            f"画面设计：{scale}；构图包含前景、中景与地点真实背景。"
            "palette 冷暖三角色，动机光来自场景内灯具，材质细节真实，空气层次克制。"
            "NEGATIVE_PROMPT: no text, no watermark, no identity drift, no collage, do not change location. "
            "真实空间纵深与人物尺度服务叙事，禁止装饰性奇观替代剧情。" * 3
        )

    def test_old_e27_animate_still_prompt_is_blocked(self):
        report = validate_task({
            "task_key": "E27-OLD",
            "tool_type": "video_generation",
            "prompt": "Animate the supplied still. Target one continuous 4-second shot. The hero fights the guard.",
        })
        self.assertEqual(report["status"], "BLOCK_SUBMIT")
        self.assertTrue(any(row["check"] == "generic_single_still_animation" for row in report["failures"]))

    def test_professional_seedance_storyboard_passes(self):
        prompt = (
            "实体绑定 [[char_chenji]] [[scene_clinic]] [[prop_blade]]。palette 冷蓝、朱红与暗木，动机光；"
            "大远景定场，力量画在木屑与碎片等环境介质。"
            "镜头1【中景，低机位跟拍】陈迹错步逼近，抬肘击中甲缝，守卫后退撞翻木架。{无对白}<甲片爆裂、木屑坠地>"
            "镜头2【近景，侧向快速推近】陈迹夹停刀锋，旋腕夺刀，碎甲沿地面滑出。{陈迹：让开。}<刀鸣、碎片擦地>"
        )
        self.assertEqual(validate_task({"task_key": "PRO", "tool_type": "video_generation", "prompt": prompt})["status"], "PASS")

    def test_duplicate_internal_decisive_action_is_blocked(self):
        prompt = (
            "实体绑定 [[char_chenji]] [[scene_room]] [[prop_door]]。palette 冷蓝与暖烛，动机光；"
            "大远景定场，力量画在木屑与碎片等环境介质。"
            "镜头1【中景，固定机位】主体稳定后，再完成：陈迹把沉柜顶死在门后；动作结果落到门闩。{无对白}<柜脚摩地>"
            "镜头2【近景，侧向跟拍】主体稳定后，再完成：陈迹把沉柜顶死在门后；动作结果落到冰线。{无对白}<冰层脆响>"
        )
        report = validate_task({"task_key": "DUP", "tool_type": "video_generation", "prompt": prompt})
        self.assertTrue(any(row["check"] == "duplicate_internal_action" for row in report["failures"]))

    def test_instructor_without_independent_identity_slot_is_blocked(self):
        prompt = (
            "实体绑定 [[char_chenji]] [[scene_corridor]] [[prop_blade]]。palette 青蓝与暖橙，动机光；"
            "大远景定场，力量画在木屑与碎片等环境介质。"
            "镜头1【中景，低机位跟拍】黑影教习踏碎冰层，翻越飞檐。{无对白}<碎冰坠地>"
        )
        report = validate_task({"task_key": "INSTRUCTOR", "tool_type": "video_generation", "prompt": prompt})
        self.assertTrue(any(row["check"] == "instructor_identity_binding" for row in report["failures"]))

    def test_black_shadow_bound_to_scene_killer_is_allowed(self):
        prompt = (
            "实体绑定 [[char_yunyang]] [[char_killer]] [[scene_street]]。palette 青蓝与暖红，动机光；"
            "大远景定场，力量画在雪粉与衣摆等环境介质。"
            "镜头1【中景，低机位跟拍】黑影扑向药铺，云羊落地截住，杀手急停转身。{无对白}<踏雪、衣袂破风>"
        )
        report = validate_task({"task_key": "SCENE-KILLER", "tool_type": "video_generation", "prompt": prompt})
        self.assertEqual(report["status"], "PASS")

    def test_visual_glyph_reveal_is_blocked_before_submit(self):
        prompt = (
            "镜头1【近景，固定机位】陈迹迎向斜光，压痕从空白处逐行浮起，纸上出现真名。"
            "{陈迹：凹痕留了真名。}<纸张摩擦>"
        )
        failures = detect_glyph_reveal_failures(prompt)
        self.assertTrue(any(row["check"] == "glyph_reveal_visual_directive" for row in failures))

    def test_spoken_name_with_abstract_non_glyph_surface_is_allowed(self):
        prompt = (
            "镜头1【近景，固定机位】镜头只看陈迹眼神与指尖，纸面仅保留无字符轮廓的抽象浅凹反光。"
            "{对白按本镜对白合同执行}<纸张摩擦>\n"
            "【对白与声音资产】陈迹只说一次：‘两张叠压，凹痕留了真名。’\n"
            "【现场声】纸张摩擦。"
        )
        self.assertEqual(detect_glyph_reveal_failures(prompt), [])

    def test_inline_native_dialogue_about_revealing_a_name_is_allowed(self):
        prompt = (
            "【对白音频】\n"
            "- 0.30-5.12秒：@音频1，陈迹逐字说‘他们不能让这条线露出名字。’，口型同步。\n"
            "镜头1【近景，固定机位】陈迹夹起半枚铜牌并翻面，印面保持不可读抽象纹理。"
            "{陈迹：他们不能让这条线露出名字。}<铜牌轻响>"
        )
        self.assertEqual(detect_glyph_reveal_failures(prompt), [])

    def test_unquoted_visual_name_reveal_remains_blocked(self):
        prompt = (
            "【对白音频】无对白。\n"
            "镜头1【近景，固定机位】铜牌表面逐渐露出名字。{无对白}<铜牌轻响>"
        )
        failures = detect_glyph_reveal_failures(prompt)
        self.assertTrue(any(row["check"] == "glyph_reveal_visual_directive" for row in failures))

    def test_portable_writer_image_prompt_passes(self):
        with TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "writer-image-prompt.txt"
            prompt.write_text(self.image_prompt("大远景航拍定场"), encoding="utf-8")
            report = validate_task({"task_key": "PORTABLE-N01", "tool_type": "image_generation", "prompt_file": str(prompt)})
        self.assertEqual(report["status"], "PASS")

    def test_generic_image_prompt_is_blocked(self):
        report = validate_task({"task_key": "GENERIC", "tool_type": "image_generation", "prompt": "cinematic hero in a beautiful room"})
        self.assertEqual(report["status"], "BLOCK_SUBMIT")

    def test_opted_in_character_prompt_requires_human_realism_contract(self):
        report = validate_task({
            "task_key": "GENERIC-REALISM",
            "tool_type": "image_generation",
            "prompt": self.image_prompt("近景特写"),
            "prompt_realism_contract_version": "1.0.0",
        })
        self.assertEqual(report["status"], "BLOCK_SUBMIT")
        self.assertTrue(any(row["check"] == "skin_microtexture" for row in report["failures"]))

    def test_opted_in_character_prompt_with_contract_passes(self):
        realism = build_keyframe_realism_block(
            character_ids=["char_chenji"],
            character_locks={"char_chenji": {"name": "陈迹", "immutable": {"age": "二十余岁"}}},
            shot_scale="近景特写",
            lens_intent="85mm肖像",
            action="陈迹抬眼",
            expression_arc="迟疑到确认",
            eyeline_target="门外来人",
        )
        report = validate_task({
            "task_key": "CONTRACT-REALISM",
            "tool_type": "image_generation",
            "prompt": self.image_prompt("近景特写") + realism,
            "prompt_realism_contract_version": "1.0.0",
        })
        self.assertEqual(report["status"], "PASS")

    def test_batch_reports_only_blocked_tasks(self):
        report = evaluate_batch({
            "episode": "E27",
            "tasks": [
                {"task_key": "bad", "tool_type": "video_generation", "prompt": "Animate the supplied still in one continuous 4-second shot."},
                {"task_key": "local", "tool_type": "agentcut"},
            ],
        })
        self.assertEqual(report["status"], "BLOCK_SUBMIT")
        self.assertEqual(report["blocked_tasks"], ["bad"])

    def test_all_medium_image_batch_is_blocked(self):
        report = evaluate_batch({
            "episode": "E27",
            "tasks": [
                {"task_key": "M1", "tool_type": "image_generation", "scene_id": "S1", "prompt": self.image_prompt("medium")},
                {"task_key": "M2", "tool_type": "image_generation", "scene_id": "S1", "prompt": self.image_prompt("medium close-up")},
            ],
        })
        self.assertEqual(report["status"], "BLOCK_SUBMIT")
        self.assertTrue(any(row["check"] == "episode_grand_establishing" for row in report["batch_failures"]))

    def test_full_shot_size_range_with_scene_establishing_passes(self):
        report = evaluate_batch({
            "episode": "E27",
            "tasks": [
                {"task_key": "W1", "tool_type": "image_generation", "scene_id": "S1", "prompt": self.image_prompt("大远景航拍定场")},
                {"task_key": "M1", "tool_type": "image_generation", "scene_id": "S1", "prompt": self.image_prompt("medium")},
                {"task_key": "C1", "tool_type": "image_generation", "scene_id": "S1", "prompt": self.image_prompt("close-up 特写")},
            ],
        })
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["batch_failures"], [])

    def test_targeted_replacement_inherits_episode_establishing_coverage(self):
        prompt = (
            "实体绑定 [[char_chenji]] [[char_assassin]] [[scene_clinic]] [[prop_blade]]。"
            "palette 冷蓝与暖烛，动机光；力量作用通过环境介质中的烛焰偏转表现。"
            "镜头1【近景，手持】刺客持刀贴近，抬腕维持刀锋，开口说话。{刺客：别动。}<刀鸣、呼吸>"
        )
        report = evaluate_batch({
            "episode": "E30", "targeted_unit_replacement": True,
            "tasks": [{
                "task_key": "U01-R1", "tool_type": "video_generation", "scene_id": "S1",
                "inherits_establishing_coverage": True, "prompt": prompt,
            }],
        })
        self.assertEqual(report["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
