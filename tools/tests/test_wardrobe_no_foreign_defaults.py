import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lines/nalu/runtime/tools'))

class WardrobeNoForeignDefaults(unittest.TestCase):
    def test_absent_values_are_not_snow_farmer_or_cotton(self):
        module = importlib.import_module('build_nalu_preproduction')
        entity = {'character_id': 'CHAR-TEST', 'canonical_name': '人物', 'appearance_ch1': '晴夜衣冠整齐'}
        row = module.wardrobe_bible({'character_entities': [entity]}, 'TEST')['characters'][0]
        for key in ('condition', 'material', 'social_tier'):
            self.assertIsNone(row[key])
        entity['wardrobe_garments'] = {'condition': '被雨淋湿', 'material': '丝绢'}
        row = module.wardrobe_bible({'character_entities': [entity]}, 'TEST')['characters'][0]
        self.assertEqual(row['condition'], '被雨淋湿')
        self.assertEqual(row['material'], '丝绢')
