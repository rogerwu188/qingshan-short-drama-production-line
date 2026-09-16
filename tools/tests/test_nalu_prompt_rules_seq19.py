"""seq=19 (E04 review): emotion delivery clause and prompt-stage failure-memory injection."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "nalu_prompt_rules", ROOT / "lines/nalu/runtime/tools/nalu_prompt_rules.py")
rules = importlib.util.module_from_spec(SPEC)
sys.modules["nalu_prompt_rules"] = rules
SPEC.loader.exec_module(rules)

MEMORY = [
    {"failure_code": "ACTION_NO_OUTCOME", "do_not_repeat": "动作段落必须收束", "stage": "prompt", "knowledge_id": "K043"},
    {"failure_code": "CREATURE_FORM_DRIFT", "do_not_repeat": "步态跨镜锁定", "stage": "prompt", "knowledge_id": "K048"},
    {"failure_code": "HOOK_MISSING", "do_not_repeat": "前 5 秒必须有台词", "stage": "pipeline", "knowledge_id": "K042"},
]


def shot(**kw):
    base = {"shot_id": "EXX-S01-01", "action": "甲走到乙面前", "sec": 4.0, "cast": ["A"], "size": "中景",
            "camera_family": "DOLLY"}
    base.update(kw)
    return base


class EmotionAndKnowledgeInjection(unittest.TestCase):
    def test_emotion_clause_added_and_unknown_emotion_blocks(self):
        text, applied, blocks = rules.apply(shot(dialogue=("A", "救命啊", None), emotion="plead"), {})
        self.assertIn("EMOTION:plead", applied)
        self.assertIn("哀求", text)
        _, _, blocks = rules.apply(shot(dialogue=("A", "救命啊", None), emotion="angry"), {})
        self.assertTrue(any(b.startswith("EMOTION_UNKNOWN") for b in blocks))
        _, _, blocks = rules.apply(shot(dialogue=("A", "救命啊", None)), {"emotion_required": True})
        self.assertTrue(any(b.startswith("EMOTION_UNDECLARED") for b in blocks))

    def test_only_prompt_stage_rows_are_injected_and_only_on_trigger(self):
        ctx = {"failure_memory": MEMORY, "creature_ids": ["PROP-BEAST"]}
        text, applied, _ = rules.apply(shot(state_delta_dimensions=["CONTACT"]), ctx)
        self.assertIn("KNOWLEDGE:K043", applied)
        self.assertIn("勿重蹈 ACTION_NO_OUTCOME", text)
        self.assertNotIn("KNOWLEDGE:K042", applied)          # pipeline row never enters a prompt
        self.assertNotIn("KNOWLEDGE:K048", applied)          # no creature in this shot
        text, applied, _ = rules.apply(shot(props=["PROP-BEAST"]), ctx)
        self.assertIn("KNOWLEDGE:K048", applied)
        text, applied, _ = rules.apply(shot(), ctx)
        self.assertFalse([a for a in applied if a.startswith("KNOWLEDGE:")])


if __name__ == "__main__":
    unittest.main()
