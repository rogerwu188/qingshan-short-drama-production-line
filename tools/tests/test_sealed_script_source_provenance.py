"""Free regression of source provenance; no local episode data or external API."""
import ast
import hashlib
import tempfile
import unittest
from pathlib import Path
from typing import Any


class SourceProvenanceTests(unittest.TestCase):
    def setUp(self):
        p=Path(__file__).resolve().parents[2]/'lines/nalu/runtime/tools/build_episode_asset_requirements.py'
        function=next(n for n in ast.parse(p.read_text()).body
                      if isinstance(n,ast.FunctionDef) and n.name=='validate_execution_source')
        env={'Path':Path,'Any':Any,'sha256_file':lambda p:hashlib.sha256(p.read_bytes()).hexdigest()}
        exec(compile(ast.Module(body=[function],type_ignores=[]),str(p),'exec'),env)
        self.validate=env['validate_execution_source']

    def test_existing_chapter_mode_unchanged(self):
        self.assertEqual(self.validate({}),'SOURCE_CHAPTER')

    def test_unknown_mode_rejected(self):
        with self.assertRaisesRegex(ValueError,'unsupported'): self.validate({'source_kind':'GUESS'})

    def test_sealed_script_requires_real_file_sha_and_note(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'canonical.md';p.write_text('supplied sealed script')
            b={'source_kind':'SEALED_SCRIPT','source_file':str(p),'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'source_note':'Supplied script; original chapter not independently reviewed.'}
            self.assertEqual(self.validate(b),'SEALED_SCRIPT')
            with self.assertRaisesRegex(ValueError,'SHA_MISMATCH'): self.validate({**b,'source_sha256':'0'*64})
            with self.assertRaisesRegex(ValueError,'NOTE_REQUIRED'): self.validate({**b,'source_note':''})
            with self.assertRaisesRegex(ValueError,'FILE_MISSING'): self.validate({**b,'source_file':str(p)+'missing'})

if __name__=='__main__': unittest.main()
