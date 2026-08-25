import tempfile
import unittest
from pathlib import Path

from tools.compile_grouped_seedance_manifest import (
    MAX_MODEL_PROMPT_CHARS,
    build_writer_agent_provenance,
    compile_manifest,
    prompt_text,
    validate_model_prompt,
)


class CompileGroupedSeedanceManifestTest(unittest.TestCase):
    def test_writer_agent_provenance_binds_paths_and_sha(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp:
            script = Path(tmp) / "script.md"
            contract = Path(tmp) / "contract.json"
            script.write_text("script", encoding="utf-8")
            contract.write_text("{}", encoding="utf-8")

            provenance = build_writer_agent_provenance(script, contract)

            self.assertEqual(provenance["status"], "PASS")
            self.assertEqual(provenance["provenance_type"], "claude_writer_script")
            self.assertEqual(len(provenance["source_script_sha256"]), 64)
            self.assertEqual(len(provenance["production_manifest_sha256"]), 64)

    def test_model_prompt_is_compact_and_does_not_leak_machine_contract(self):
        specs = []
        timeline = []
        dialogue = ["", "梁狗儿：不许再提。", "梁狗儿：你学刀做什么。", "陈迹：自保。", "梁狗儿：想保命，就握不住刀。"]
        actions = [
            ("梁狗儿醉醒过来，一把把陈迹拽过去。", "一把拽住臂弯把人带转半圈，两人错开半步站定"),
            ("不许再提。", "说话时另一只手指着院子那一头"),
            ("你学刀做什么。", "问的时候手还抓着对方的袖子"),
            ("自保。", "答得极快，答完没有补话"),
            ("想保命，就握不住刀。", "说完松开袖子，手往下一甩"),
        ]
        boundaries = [(0, 1.5), (1.5, 2.6), (2.6, 4.1), (4.1, 5.0), (5.0, 7.6)]
        for index, ((primary, terminal), raw_dialogue, (start, end)) in enumerate(zip(actions, dialogue, boundaries)):
            specs.append({
                "space": {"global": "GLOBAL-SPACE-E41", "location": "LOC-COURTYARD", "subspace": f"SUB-{index}"},
                "scene_state": {"weather": "上午，日头爬到院墙上沿", "palette": "warm"},
                "cast": [{"character": "梁狗儿"}, {"character": "陈迹"}],
                "props": [{"prop": "刀"}] if index in {2, 4} else [],
                "action": {"primary_action": primary, "completion_state": terminal},
                "dialogue": raw_dialogue,
            })
            timeline.append({"start_seconds": start, "end_seconds": end})
        unit = {
            "unit_id": "E41-VU-015",
            "scene_id": "S14",
            "duration_seconds": 7.6,
            "ordered_prompt_specs": specs,
            "action_timeline": timeline,
            "reference_images": [{"path": "frame.png", "sha256": "not-for-model", "role": "SCENE_START_ANCHOR"}],
        }

        text = prompt_text(unit, [{"id": "PF-001"}, {"id": "PF-042"}])
        result = validate_model_prompt(text, source_id=unit["unit_id"])

        self.assertEqual(result["status"], "PASS")
        self.assertLessEqual(len(text), MAX_MODEL_PROMPT_CHARS)
        self.assertNotIn("GLOBAL-SPACE-", text)
        self.assertNotIn("sha256", text)
        self.assertNotIn("PF-", text)
        self.assertNotIn("【逐节拍完整合同】", text)
        self.assertEqual(text.count("不许再提。"), 1)
        self.assertEqual(text.count("你学刀做什么。"), 1)
        self.assertEqual(text.count("自保。"), 1)
        self.assertEqual(text.count("想保命，就握不住刀。"), 1)

    def test_preserves_transport_strategy_and_reference_roles(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.png"
            later = Path(tmp) / "later.png"
            first.write_bytes(b"first")
            later.write_bytes(b"later")
            grouping = {
                "episode": "E41",
                "video_unit_count": 1,
                "runtime_seconds": 6,
                "units": [{
                    "unit_id": "VU-1", "scene_id": "S1", "duration_seconds": 6,
                    "editorial_shot_ids": ["S1-1", "S1-2"], "narrative_beat": "beat",
                }],
            }
            anchors = {"units": [{
                "unit_id": "VU-1", "planned_reference_image_count": 2,
                "reference_image_paths": [str(first), str(later)],
                "reference_transport_strategy": "OMNI_MULTI_REFERENCE",
                "anchor_count_decision": {
                    "anchor_roles": ["ADMITTED_SCENE_START_STATE", "IDENTITY_OR_PROP_REANCHOR"],
                },
                "semantic_reference_coverage_gate": {"status": "PASS"},
            }]}
            editorial = {"shots": [
                {"shot_id": "S1-1", "model": "seedance-2.0-fast", "resolution": "720p", "prompt_spec": {}},
                {"shot_id": "S1-2", "model": "seedance-2.0-fast", "resolution": "720p", "prompt_spec": {}},
            ]}
            result = compile_manifest(grouping, anchors, editorial)
            unit = result["units"][0]
            self.assertEqual(unit["reference_transport_strategy"], "OMNI_MULTI_REFERENCE")
            self.assertEqual(
                [row["role"] for row in unit["reference_images"]],
                ["ADMITTED_SCENE_START_STATE", "IDENTITY_OR_PROP_REANCHOR"],
            )
            self.assertEqual(unit["semantic_reference_coverage_gate"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
