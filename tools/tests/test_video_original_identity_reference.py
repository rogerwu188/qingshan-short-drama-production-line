"""Video requests consume approved original sources without mutating old assets."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lines/nalu/runtime/tools'))
import build_nalu_preproduction as bnp


class OriginalVideoReferenceTests(unittest.TestCase):
    def test_original_wins_and_stale_original_cannot_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / 'approved-card.png'
            derivative = root / 'derived_FRONT_NEUTRAL_HEADSHOT.png'
            original.write_bytes(b'approved original fixture')
            derivative.write_bytes(b'generated derivative fixture')
            library = root / 'library.json'
            library.write_text(json.dumps({'project_id': 'TEST', 'assets': {'characters': {
                'CHAR-A': {'status': 'LOCKED',
                    'original_identity_authority': {'mode': 'APPROVED_ORIGINAL_SOURCE',
                        'approval_basis': 'fixture owner approval', 'path': str(original),
                        'sha256': hashlib.sha256(original.read_bytes()).hexdigest()},
                    'lock': {'identity_lock': {'canonical_view_paths': [str(derivative)]}}}}}}))
            with patch.object(bnp, '_scoped_asset_library_path', return_value=library), \
                 patch.object(bnp._series_scope, 'resolve_scope', return_value={'series_id': 'TEST'}):
                selected = bnp._locked_identity_plate('CHAR-A', episode='TEST')
                self.assertEqual(selected, original)
                rows, dropped, missing = bnp.identity_plate_reference_rows(
                    ['CHAR-A'], lambda _: selected, existing_paths=[])
                self.assertEqual(rows[0]['path'], str(original))
                self.assertEqual(rows[0]['view'], 'IDENTITY_REFERENCE_VIEW_UNSPECIFIED')
                self.assertEqual((dropped, missing), ([], []))
                original.write_bytes(b'changed')
                with self.assertRaisesRegex(ValueError, 'MISSING_OR_CHANGED'):
                    bnp._locked_identity_plate('CHAR-A', episode='TEST')


if __name__ == '__main__':
    unittest.main()
