import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lines/nalu/runtime/tools'))
from prompt_batch_qa import foreign_dialogue, load, wardrobe_expectation


class DialogueScopeTests(unittest.TestCase):
    def test_wardrobe_uses_full_scoped_override_not_global_prefix(self):
        bible = {'character_id': 'A', 'authored_description': '全局旧衣', 'outer_layer': '兽皮大衣'}
        spec = {'cast': [{'character_id': 'A', 'character': '甲'}],
                'wardrobe_state_overrides': {'A': '绛紫圆领袍、素白中衣'}}
        self.assertEqual(wardrobe_expectation(spec, '甲', bible), ('绛紫圆领袍、素白中衣', '绛紫圆领袍、素白中衣'))
        self.assertEqual(wardrobe_expectation({}, '甲', bible), ('全局旧衣', '兽皮大衣'))

    def test_transition_text_cannot_exempt_foreign_line(self):
        lines = {'S1': ['甲：本镜自己的台词'], 'S2': ['乙：下一个镜头的台词']}
        self.assertEqual(foreign_dialogue('转场交棒：下一个镜头的台词', lines, ['S1']),
                         ['下一个镜头的台词'])

    def test_authored_repeated_line_is_not_foreign(self):
        lines = {'S1': ['甲：这里是共同台词'], 'S2': ['乙：这里是共同台词']}
        self.assertEqual(foreign_dialogue('这里是共同台词', lines, ['S1']), [])

    def test_local_only_and_empty_dialogue(self):
        self.assertEqual(foreign_dialogue('本镜自己的台词', {'S1': ['甲：本镜自己的台词']}, ['S1']), [])
        self.assertEqual(foreign_dialogue('环境声', {}, ['S1']), [])

    def test_explicit_missing_contract_never_falls_back(self):
        with self.assertRaises(FileNotFoundError):
            load('SYNTHETIC', contract_file='/nonexistent/explicit_contract.json')


if __name__ == '__main__':
    unittest.main()
