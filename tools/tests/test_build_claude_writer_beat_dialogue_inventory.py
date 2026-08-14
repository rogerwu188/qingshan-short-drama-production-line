import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.build_claude_writer_beat_dialogue_inventory import parse


class BuildClaudeWriterBeatDialogueInventoryTests(unittest.TestCase):
    def test_parses_timed_scene_headings_and_stops_before_appendices(self):
        text = """## 剧本正文
**13-1．王府 花厅　深夜　内**（≈5s，1 镜）
△【近景】动作。
◇首帧动势：动作正在发生｜禁例：禁结果态。
陈迹：（低）第一句。
**13-2。王府 侧厢　深夜　内**（≈5s，1 镜；**短打**）
△【近景】动作。
◇首帧动势：动作正在发生｜禁例：禁结果态。
云羊：第二句。
## 生产注记
①**对白节奏根治**：这不是角色对白。
"""
        manifest = {
            "episode": "E40",
            "title": "test",
            "scenes": 2,
            "scene_breakdown_seconds": {"13-1": 5, "13-2": 5},
        }
        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "script.md"
            script.write_text(text, encoding="utf-8")
            result = parse(script, manifest)
        self.assertEqual(result["scene_count"], 2)
        self.assertEqual(result["visual_beat_count"], 2)
        self.assertEqual(result["dialogue_line_count"], 2)
        dialogue = [
            row["spoken_text"]
            for scene in result["scenes"]
            for beat in scene["beats"]
            for row in beat["dialogue"]
        ]
        self.assertEqual(dialogue, ["第一句。", "第二句。"])


if __name__ == "__main__":
    unittest.main()
