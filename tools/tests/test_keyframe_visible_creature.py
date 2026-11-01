"""A carded creature the contract marks visible is on screen in the keyframe (nalu E13 2026-11-01)."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))
from build_keyframe_manifest import normalize_keyframe_role_semantics  # noqa: E402


class VisibleCreature(unittest.TestCase):
    def test_explicit_visible_creature_keeps_its_pose(self):
        role = {"entity_entry_states": {"CHAR-A": "A draws a knife", "PROP-LEOPARD": "leopard mid-air"},
                "entity_presence": {"CHAR-A": "VISIBLE_AND_IDENTITY_LOCKED", "PROP-LEOPARD": "VISIBLE_AND_IDENTITY_LOCKED"}}
        out = normalize_keyframe_role_semantics(role, shot_id="S1", entry_state="leopard mid-air, A draws",
                                                visible_contract_ids=["CHAR-A"])
        self.assertEqual(out["entity_states"]["PROP-LEOPARD"], "leopard mid-air")
        self.assertEqual(out["entity_presence"]["PROP-LEOPARD"], "VISIBLE_AND_IDENTITY_LOCKED")

    def test_creature_actor_is_keyed_by_entity_id_not_name(self):
        role = {"primary_actor_kind": "CREATURE", "primary_actor": "刺豹", "primary_actor_id": "",
                "primary_actor_entity_id": "PROP-LEOPARD",
                "entity_entry_states": {"PROP-LEOPARD": "leopard crouched"},
                "entity_presence": {"PROP-LEOPARD": "VISIBLE_AND_IDENTITY_LOCKED"}}
        out = normalize_keyframe_role_semantics(role, shot_id="S1", entry_state="leopard crouched",
                                                visible_contract_ids=[])
        self.assertNotIn("刺豹", out["entity_presence"])
        self.assertEqual(out["entity_presence"]["PROP-LEOPARD"], "VISIBLE_AND_IDENTITY_LOCKED")

    def test_unmarked_creature_stays_absent(self):
        role = {"entity_entry_states": {"CHAR-A": "A stands"}, "entity_states": {"PROP-LEOPARD": "x"}}
        out = normalize_keyframe_role_semantics(role, shot_id="S1", entry_state="A stands",
                                                visible_contract_ids=["CHAR-A"])
        self.assertEqual(out["entity_presence"]["PROP-LEOPARD"], "ABSENT_REFERENCE_ONLY")

    def test_batch_qa_cast_regex_ignores_the_creature_clause(self):
        source = (ROOT / "lines/nalu/runtime/tools/prompt_batch_qa.py").read_text(encoding="utf-8")
        pattern = re.search(r'allowed = re\.search\(r"(.+?)", kf_text\)', source).group(1)
        text = "本帧允许入画的人物（仅这些，且各只出现一次）：秦铭（CHAR-QINMING）；另有本帧可见的生物（仅这些，各只出现一次）：刺豹（PROP-X）"
        self.assertEqual(re.search(pattern, text).group(1), "秦铭（CHAR-QINMING）")


if __name__ == "__main__":
    unittest.main()
