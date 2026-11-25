"""E28 S3 (device …1101, 2026-11-25): the S3 non-plate music row on a SCREENPLAY_V1 contract.

screenplay_compile writes ``audio_contract.bgm = "NO_BGM"`` for every contract that does not author music; the line
default (nalu_bgm_default) derives the cue later.  ``contract_bgm_policy_consistent`` only knew NONE / NO_EXTERNAL_BGM /
SELECTIVE and failed the row.  Voice rows before S4 are expected to be open and are now labelled as such."""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lines/nalu/runtime/tools"))


def _lock():
    return importlib.import_module("library_lock_non_plate")


def music_row(external: bool = False) -> dict:
    return {"asset_id": "MUSIC-E28-NO-EXTERNAL-BGM", "status": "PENDING",
            "specification": {"asset_kind": "MUSIC_POLICY_DECLARATION", "usage_scope": "EPISODE_E28_FULL",
                              "musical_identity": "NO_BGM", "external_bgm_allowed": external}}


def ctx_for(bgm) -> SimpleNamespace:
    contract = {"audio_contract": {} if bgm is ... else {"bgm": bgm}, "shots": []}
    return SimpleNamespace(contract=contract, contract_path=Path("/nonexistent/contract.json"),
                           contract_sha="0" * 64, rights_basis="LINE_OWNER", requirements={"assets": {}})


class MusicPolicyTests(unittest.TestCase):
    def check(self, bgm, external=False):
        row = _lock().lock_declared_audio(ctx_for(bgm), "music", music_row(external))
        return row["status"], {c["id"]: c["status"] for c in row["qa"]["checks"]}, row["lock"]

    def test_screenplay_no_bgm_declaration_locks(self):
        for bgm in ("NO_BGM", "no_bgm", None, "", ..., {"mode": "NO_BGM"}, {"declaration": "x"}):
            status, checks, lock = self.check(bgm)
            self.assertEqual(status, "LOCKED", bgm)
            self.assertEqual(checks["contract_bgm_policy_consistent"], "PASS", bgm)
            self.assertEqual(lock["bgm_mode"], "LINE_DEFAULT_DERIVED_LATER", bgm)

    def test_existing_policies_unchanged(self):
        self.assertEqual(self.check("NO_EXTERNAL_BGM_SOUNDSCAPE_ONLY")[0], "LOCKED")
        self.assertEqual(self.check({"mode": "NONE", "used": False, "declaration": "NO_EXTERNAL_BGM"})[0], "LOCKED")
        self.assertEqual(self.check({"mode": "SELECTIVE", "cues": [{"id": "c1"}]}, external=True)[0], "LOCKED")

    def test_inconsistent_declarations_still_fail(self):
        # an undecided contract whose requirement row claims external BGM, or authored prose asking for music
        self.assertEqual(self.check("NO_BGM", external=True)[0], "QA_FAILED_NOT_LOCKED")
        self.assertEqual(self.check("LAST_SCENE_ONLY_LOW_SUSTAIN")[0], "QA_FAILED_NOT_LOCKED")
        self.assertEqual(self.check({"mode": "SELECTIVE", "cues": []})[0], "QA_FAILED_NOT_LOCKED")


if __name__ == "__main__":
    unittest.main()
