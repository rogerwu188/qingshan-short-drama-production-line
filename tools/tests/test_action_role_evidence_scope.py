"""Repair reviews must not overwrite another runtime's same-numbered unit."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'lines/nalu/runtime/tools'))
import action_role_evidence_writer as writer


class ActionRoleEvidenceScopeTest(unittest.TestCase):
    def test_context_uses_validated_qa_paths(self):
        with patch.dict(os.environ, {'NALU_QA_CONTEXT': '/context.json'}), \
             patch.object(writer, 'QaPaths', return_value=SimpleNamespace(preprod_reports=Path('/isolated/reports'))):
            self.assertEqual(writer.evidence_path('EP', 'U1'),
                             Path('/isolated/reports/action_role_evidence/U1_action_role_verification.json'))

    def test_default_path_stays_compatible(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(writer.evidence_path('EP', 'U1'),
                writer.ENGINE / writer.ACTION_ROLE_EVIDENCE_RELDIR / 'U1_action_role_verification.json')

    def test_invalid_context_is_not_silently_ignored(self):
        with patch.dict(os.environ, {'NALU_QA_CONTEXT': '/invalid.json'}), \
             patch.object(writer, 'QaPaths', side_effect=SystemExit('QA_CONTEXT_SCOPE_MISMATCH')):
            with self.assertRaises(SystemExit):
                writer.evidence_path('EP', 'U1')
