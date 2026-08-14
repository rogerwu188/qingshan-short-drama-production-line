import hashlib
import json
import unittest

from tools.build_e20_dialogue_performance_v2 import build_manifest


class E20DialoguePerformanceV2Tests(unittest.TestCase):
    def test_builds_complete_manifest_with_explicit_voice_gates(self):
        rows = []
        speakers = ["巡夜领队", "云羊", "陈迹", "白鲤", "皎兔", "佛子"]
        for index in range(38):
            rows.append(
                {
                    "dia_id": f"DIA-{index:03d}",
                    "speaker": speakers[index % len(speakers)],
                    "text": "这是测试台词。",
                    "beat_id": f"B{index % 6 + 1:02d}",
                    "function": "确认测试证据",
                }
            )
        beat_sheet = {"episode": "E20", "dialogue_draft": rows}
        raw = json.dumps(beat_sheet, ensure_ascii=False).encode()
        digest = hashlib.sha256(raw).hexdigest()
        manifest = build_manifest(beat_sheet, digest)
        self.assertEqual(manifest["dialogue_count"], 38)
        self.assertEqual(manifest["beat_sheet_sha256"], digest)
        self.assertTrue(manifest["checks"]["all_38_v2_lines_present"])
        unresolved = [row for row in manifest["lines"] if row["voice_asset_id"] is None]
        self.assertTrue(unresolved)
        self.assertTrue(all(row["voice_gate"] for row in unresolved))
        self.assertTrue(all(row["delivery"]["expression_arc"]["trigger"] for row in manifest["lines"]))


if __name__ == "__main__":
    unittest.main()
