import importlib
import sys
import unittest
import tempfile
import json
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lines/nalu/runtime/tools'))


class OriginalPreservation(unittest.TestCase):
    def test_reuse_requires_actual_bytes_and_passed_lock(self):
        mod = importlib.import_module('bootstrap_identity_cards')
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / 'card.png'
            image.write_bytes(b'verified fixture')
            library = Path(tmp) / 'library.json'
            asset = {'status': 'LOCKED', 'qa': {'status': 'PASS'},
                     'artifacts': [{'path': str(image), 'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}]}
            library.write_text(json.dumps({'assets': {'characters': {'CHAR-TEST': asset}}}))
            req = {'assets': {'characters': [{'asset_id': 'CHAR-TEST', 'reuse': {
                'status': 'REUSED_FROM_PRIOR_LIBRARY', 'prior_library': str(library)}}]}}
            self.assertEqual(mod.verified_requirement_reuse(req), {'CHAR-TEST'})
            image.write_bytes(b'tampered')
            self.assertEqual(mod.verified_requirement_reuse(req), set())
            image.unlink()
            self.assertEqual(mod.verified_requirement_reuse(req), set())

    def test_group_card_is_one_sample_not_replicated_crowd(self):
        mod = importlib.import_module('build_episode_asset_requirements')
        row = {'asset_id': 'GROUP-TEST', 'specification': {'canonical_name': '侍女群',
               'apparent_age_range': '20-35', 'sex': 'female', 'appearance_ch1': '成年群像'}}
        body, _ = mod.character_prompt(row, '素色服装', '写实')
        self.assertIn('本卡只展示群体中一名成年成员', body)
        self.assertIn('其他成员使用不同面孔', body)

    def test_explicit_policy_disables_deaging_and_wardrobe_override(self):
        mod = importlib.import_module('bootstrap_identity_cards')
        base, view = mod.source_clauses([{'file': 'original.png'}], preserve_original=True)
        for text in (base, view):
            self.assertIn('不年轻化', text)
            self.assertIn('不换装', text)
            self.assertNotIn('只去除年龄痕迹', text)
        self.assertEqual(mod.source_clauses([{'file': 'original.png'}])[0], mod.SOURCE_FACE_CLAUSE)
        self.assertEqual(mod.source_clauses([{'file': 'SOURCE_V2.png'}])[0], mod.SOURCE_FACE_CLAUSE_V2)
